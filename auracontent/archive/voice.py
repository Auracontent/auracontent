"""Voix off dirigée d'un short d'archives.

Le réalisateur écrit dans plan.json la voix Gemini et une consigne de jeu propre à l'histoire, puis, pour chaque
phrase, le temps de silence qui la suit (`pause`) et, s'il le faut, une indication de jeu (`direction`).

Toute la narration part en UNE requête Gemini (quota), phrase par phrase. Le fichier est ensuite découpé aux
silences, chaque phrase est rognée de ses blancs, puis la narration est recomposée avec les pauses du plan :
c'est ce qui donne le temps avant un « Sauf que… » et le silence après une révélation.

Pas de voix de secours robotique : si Gemini ne répond pas, l'étape échoue et la vidéo n'est pas produite.
Une voix enregistrée à la main peut remplacer Gemini : déposer voice/lines/00.wav, 01.wav... (une par phrase).
"""
from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 24000
DEFAULT_VOICE = "Charon"
DEFAULT_STYLE = ("French documentary narrator telling a true story. Deep, calm and intimate, never theatrical. "
                 "Unhurried pace with real silences; a short beat before each reveal.")


def _read(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768


def _write(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


def trim(x: np.ndarray, pad: float = 0.06, floor_db: float = -38) -> np.ndarray:
    """Retire les blancs au début et à la fin d'une phrase (énergie par fenêtres de 10 ms)."""
    hop = int(0.01 * SR)
    n = len(x) // hop
    if n == 0:
        return x
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    on = np.where(db > max(floor_db, db.max() - 40))[0]
    if len(on) == 0:
        return x
    a = max(0, on[0] * hop - int(pad * SR))
    b = min(len(x), (on[-1] + 1) * hop + int(pad * SR))
    return x[a:b]


def prompt_for(plan: dict, texts: list[str]) -> tuple[str, dict]:
    v = plan.get("voice", {})
    header = [v.get("style") or DEFAULT_STYLE,
              "Read this French narration as one continuous documentary voice-over. "
              "Each numbered line is one sentence: make a clear pause of about one second after every line. "
              "Never read the numbers."]
    notes = [f"- Line {i + 1}: {ln['direction']}" for i, ln in enumerate(plan["lines"]) if ln.get("direction")]
    if notes:
        header.append("Delivery per line:\n" + "\n".join(notes))
    body = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(texts))
    speech = {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v.get("name") or DEFAULT_VOICE}}}
    return "\n\n".join(header) + "\n\nTRANSCRIPT TO READ ALOUD (read only this):\n\n" + body, speech


def generate_lines(plan: dict, out: Path, attempts: int = 2) -> list[np.ndarray]:
    """Une requête Gemini pour toute la narration, découpée en phrases. Lève une erreur sans voix de secours."""
    from auracontent.services.audios.audio import AudioEngine, audio_duration

    eng = AudioEngine({"engines": ["gemini"], "gemini": {}, "pronunciation": plan.get("pronunciation", {})},
                      output_dir=str(out))
    if "gemini" not in eng.engines:
        raise RuntimeError("GEMINI_API_KEY absent : pas de voix (aucune voix de secours robotique).")
    texts = [eng.prepare_text(ln.get("say") or ln["text"]) for ln in plan["lines"]]
    prompt, speech = prompt_for(plan, texts)
    for k in range(attempts):
        full = out / f"gemini_{k}.wav"
        eng._gemini_request(prompt, speech, full)
        total = audio_duration(str(full))
        cuts = eng.split_points(total, [len(t) for t in texts], eng.detect_silences(str(full), min_silence=0.25))
        if cuts is not None:
            x = _read(full)
            bounds = [0.0] + cuts + [total]
            return [trim(x[int(a * SR):int(b * SR)]) for a, b in zip(bounds, bounds[1:])]
        print(f"   découpage aux silences impossible (essai {k + 1}/{attempts})")
    raise RuntimeError("la voix Gemini ne se découpe pas en phrases : relancer, ou raccourcir les phrases.")


def build(episode: Path) -> dict:
    """Écrit voice/voice.wav et voice/timing.json à partir de plan.json."""
    plan = json.loads((episode / "plan.json").read_text(encoding="utf-8"))
    out = episode / "voice"
    out.mkdir(exist_ok=True)
    manual = sorted((out / "lines").glob("*.wav")) if (out / "lines").is_dir() else []
    if manual:
        if len(manual) != len(plan["lines"]):
            raise RuntimeError(f"{len(manual)} fichiers dans voice/lines pour {len(plan['lines'])} phrases")
        pieces = [trim(_read(p)) for p in manual]
    else:
        pieces = generate_lines(plan, out)
    tempo = float(plan.get("voice", {}).get("tempo", 1.0))
    seq, lines, t = [], [], 0.0
    default_pause = float(plan.get("voice", {}).get("pause", 0.35))
    for i, (ln, x) in enumerate(zip(plan["lines"], pieces)):
        if len(x) < int(0.2 * SR):
            raise RuntimeError(f"phrase {i} vide ou trop courte dans la voix : « {ln['text'][:40]} »")
        if tempo != 1.0:
            x = _tempo(x, tempo)
        f = int(0.015 * SR)
        x = x.copy(); x[:f] *= np.linspace(0, 1, f); x[-f:] *= np.linspace(1, 0, f)
        lines.append({"t0": round(t, 3), "t1": round(t + len(x) / SR, 3), "text": ln["text"]})
        seq.append(x); t += len(x) / SR
        pause = float(ln.get("pause", default_pause))
        if ln is not plan["lines"][-1]:
            seq.append(np.zeros(int(pause * SR))); t += pause
    _write(out / "voice.wav", np.concatenate(seq))
    timing = {"duration": round(t, 3), "lines": lines}
    (out / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   voix : {len(lines)} phrases, {t:.1f} s")
    return timing


def _tempo(x: np.ndarray, factor: float) -> np.ndarray:
    """Ralentit (<1) ou accélère (>1) sans changer la hauteur (ffmpeg atempo)."""
    p = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", "-",
                        "-af", f"atempo={factor}", "-f", "s16le", "-"],
                       input=(np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes(), capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.int16).astype(np.float32) / 32768
