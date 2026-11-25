"""Voix off des shorts « L'éco du jour » : Rémy (Edge TTS), la voix de Capital Simple.

Chaque phrase de `plan.json` est synthétisée à part (Edge TTS est gratuit et sans quota), rognée de ses blancs, puis la
narration est recomposée avec les pauses du plan. Résultat : voice/voice.wav et voice/timing.json, au même format que
les shorts d'archives (auracontent.archive.timeline les lit tels quels).

Une voix enregistrée à la main remplace Edge : déposer voice/lines/00.wav, 01.wav... (une par phrase).
`--preview` (sans réseau) : minutage estimé et voix muette, pour régler la planche ; jamais publiable (upload refuse).
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import numpy as np

from auracontent.archive.voice import SR, _read, _tempo, _write, trim

DEFAULT_VOICE = {"name": "fr-FR-RemyMultilingualNeural", "rate": "-6%", "pitch": "+0Hz"}   # comme finance.yaml
WORDS_PER_SECOND = 2.6          # Rémy ralenti, mesuré sur la chaîne (finance.yaml : voice_words_per_second)


async def _edge(text: str, path: Path, voice: dict) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice=voice["name"], rate=voice["rate"], pitch=voice["pitch"])
    await comm.save(str(path))


def spoken(line: dict) -> str:
    """Texte prononcé : `say` s'il existe, sinon `text`."""
    return (line.get("say") or line["text"]).strip()


def edge_lines(plan: dict, out: Path, attempts: int = 3) -> list[np.ndarray]:
    """Une requête Edge TTS par phrase (même voix à chaque fois, jamais de voix de secours)."""
    v = {**DEFAULT_VOICE, **{k: val for k, val in (plan.get("voice") or {}).items() if k in DEFAULT_VOICE}}
    tmp = out / "edge"
    tmp.mkdir(exist_ok=True)
    pieces = []
    for i, ln in enumerate(plan["lines"]):
        path = tmp / f"{i:02d}.mp3"
        for k in range(attempts):
            try:
                asyncio.run(_edge(spoken(ln), path, v))
                break
            except Exception as e:                       # réseau, 403 passager...
                if k == attempts - 1:
                    raise RuntimeError(f"Edge TTS a échoué sur la phrase {i} : {e}") from e
        pieces.append(trim(_read(path)))
    return pieces


def preview_lines(plan: dict) -> list[np.ndarray]:
    """Silence de la durée estimée de chaque phrase (aperçu sans réseau)."""
    out = []
    for ln in plan["lines"]:
        words = len(re.findall(r"[\wÀ-ÿ'’-]+", spoken(ln)))  # noqa: RUF001
        out.append(np.zeros(int(max(0.6, words / WORDS_PER_SECOND) * SR), np.float32))
    return out


def build(episode: Path, preview: bool = False) -> dict:
    """Écrit voice/voice.wav et voice/timing.json à partir de plan.json."""
    plan = json.loads((episode / "plan.json").read_text(encoding="utf-8"))
    out = episode / "voice"
    out.mkdir(exist_ok=True)
    manual = sorted((out / "lines").glob("*.wav")) if (out / "lines").is_dir() else []
    if manual:
        if len(manual) != len(plan["lines"]):
            raise RuntimeError(f"{len(manual)} fichiers dans voice/lines pour {len(plan['lines'])} phrases")
        pieces, source = [trim(_read(p)) for p in manual], "manuelle"
    elif preview:
        pieces, source = preview_lines(plan), "estimée"
    else:
        pieces, source = edge_lines(plan, out), "edge"
    tempo = float((plan.get("voice") or {}).get("tempo", 1.0))
    default_pause = float((plan.get("voice") or {}).get("pause", 0.3))
    seq, lines, t = [], [], 0.0
    for i, (ln, x) in enumerate(zip(plan["lines"], pieces, strict=True)):
        if len(x) < int(0.2 * SR):
            raise RuntimeError(f"phrase {i} vide ou trop courte dans la voix : « {ln['text'][:40]} »")
        if tempo != 1.0 and source != "estimée":
            x = _tempo(x, tempo)
        if source != "estimée":
            f = int(0.015 * SR)
            x = x.copy()
            x[:f] *= np.linspace(0, 1, f)
            x[-f:] *= np.linspace(1, 0, f)
        lines.append({"t0": round(t, 3), "t1": round(t + len(x) / SR, 3), "text": ln["text"]})
        seq.append(x)
        t += len(x) / SR
        if i < len(plan["lines"]) - 1:
            pause = float(ln.get("pause", default_pause))
            seq.append(np.zeros(int(pause * SR), np.float32))
            t += pause
    _write(out / "voice.wav", np.concatenate(seq))
    timing = {"duration": round(t, 3), "lines": lines, "source": source}
    (out / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"   voix {source} : {len(lines)} phrases, {t:.1f} s")
    return timing
