"""Bande son d'un short « L'éco du jour » : voix + nappe et battement discrets (synthétisés, aucun droit) + effets de
Capital Simple (pop à chaque scène, pièces sur les compteurs), mixés à -14 LUFS sous la voix."""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100
SFX = Path(__file__).resolve().parents[2] / "assets" / "finance" / "sfx"
CHORDS = {"calme": [[220, 261.6, 329.6], [174.6, 220, 261.6], [196, 261.6, 329.6], [196, 246.9, 293.7]],
          "tension": [[146.8, 174.6, 220], [155.6, 196, 233.1], [146.8, 174.6, 220], [130.8, 164.8, 196]]}


def _note(f, d, amp, att=0.15):
    t = np.arange(int(d * SR)) / SR
    s = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)
    return s * np.minimum(1, t / att) * np.exp(-t * 0.9) * amp


def _kick():
    t = np.arange(int(0.3 * SR)) / SR
    return np.sin(2 * np.pi * np.cumsum(48 + 80 * np.exp(-t * 30)) / SR) * np.exp(-t * 10) * 0.55


def _hat():
    t = np.arange(int(0.04 * SR)) / SR
    return np.random.default_rng(1).standard_normal(len(t)) * np.exp(-t * 90) * 0.05


def music(dur: float, mood: str = "calme", bpm: int = 92) -> np.ndarray:
    out = np.zeros(int(dur * SR) + SR)
    beat = 60 / bpm
    chords = CHORDS.get(mood, CHORDS["calme"])
    b = 0
    while b * beat < dur:
        t0 = b * beat
        i = int(t0 * SR)

        def add(x, i=i):
            j = min(len(out), i + len(x))
            out[i:j] += x[: j - i]

        if b % 4 == 0:
            for f in chords[(b // 4) % 4]:
                add(_note(f, beat * 4.2, 0.07))
        if b % 2 == 0:
            add(_kick())
        add(_hat())
        b += 1
    fo = int(1.5 * SR)
    out = out[: int(dur * SR)]
    out[-fo:] *= np.linspace(1, 0, min(fo, len(out)))
    return out / (np.abs(out).max() or 1) * 0.5


def _write(path: Path, x: np.ndarray) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def build(episode: Path, dur: float, lead: float, cues: list[tuple[float, str, float]], mood: str = "calme") -> Path:
    """Écrit build/mix.wav : voix (décalée de `lead`), musique à -22 dB sous la voix, effets aux instants `cues`."""
    work = episode / "build"
    work.mkdir(exist_ok=True)
    mpath = work / "music.wav"
    _write(mpath, music(dur, mood))
    inputs = ["-i", str(episode / "voice" / "voice.wav"), "-i", str(mpath)]
    parts = [f"[0:a]adelay={int(lead * 1000)}|{int(lead * 1000)},aresample={SR}[vo]",
             "[1:a]volume=0.22[mu]"]
    labels = ["[vo]", "[mu]"]
    n = 2
    for k, (at, name, gain) in enumerate(cues):
        p = SFX / name
        if not p.exists():
            continue
        inputs += ["-i", str(p)]
        ms = max(0, int(at * 1000))
        parts.append(f"[{n}:a]aresample={SR},volume={gain},adelay={ms}|{ms}[s{k}]")
        labels.append(f"[s{k}]")
        n += 1
    parts.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=longest,apad,"
                 f"atrim=0:{dur:.3f},loudnorm=I=-14:TP=-1.5:LRA=11[out]")
    out = work / "mix.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(parts), "-map", "[out]",
                    "-ar", str(SR), "-ac", "2", str(out)], check=True)
    return out
