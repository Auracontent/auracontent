"""Effets sonores de Capital Simple, synthétisés (aucun fichier tiers, aucune licence) : courts, doux, calés sur
l'action des scènes dessinées (scene["sfx_cues"] du compositeur). Même famille que les effets du moteur B1
(papier, tap, pop, carillon, tintement), plus pousse, crayon, jauge, horloge et sursaut.

    python tools/finance/sfx.py      # -> assets/finance/sfx/*.wav (48 kHz, mono, 16 bits)
"""
import math
import random
import struct
import wave
from pathlib import Path

RATE = 48000
OUT = Path(__file__).resolve().parents[2] / "assets" / "finance" / "sfx"


def _noise(seed: int):
    rnd = random.Random(seed)
    return lambda: rnd.uniform(-1, 1)


def _write(name: str, samples: list[float], peak: float = 0.8) -> Path:
    top = max(1e-9, max(abs(v) for v in samples))
    data = b"".join(struct.pack("<h", int(max(-1, min(1, v / top * peak)) * 32767)) for v in samples)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(data)
    return path


def _render(duration: float, fn) -> list[float]:
    fade = int(0.004 * RATE)                       # micro fondus : jamais de clic au début ni à la fin
    n = int(duration * RATE)
    out = [fn(i / RATE) for i in range(n)]
    for i in range(min(fade, n)):
        out[i] *= i / fade
        out[-1 - i] *= i / fade
    return out


def build() -> list[Path]:
    paper_n, tap_n, draw_n = _noise(1), _noise(2), _noise(3)
    files = [
        _write("paper.wav", _render(0.22, lambda t: paper_n() * math.exp(-t * 25))),
        _write("tap.wav", _render(0.12, lambda t: (tap_n() * 0.6 + math.sin(2 * math.pi * 170 * t) * 0.4)
                                  * math.exp(-t * 30))),
        _write("pop.wav", _render(0.14, lambda t: math.sin(2 * math.pi * (500 + 900 * t) * t) * math.exp(-t * 22))),
        _write("tick.wav", _render(0.05, lambda t: math.sin(2 * math.pi * 2200 * t) * math.exp(-t * 90))),
        _write("chime.wav", _render(0.7, lambda t: (math.sin(2 * math.pi * 880 * t) + 0.4 * math.sin(2 * math.pi * 1320 * t))
                                    * math.exp(-t * 7))),
        _write("grow.wav", _render(0.7, lambda t: math.sin(2 * math.pi * (220 * t + 330 * t * t))
                                   * math.sin(math.pi * t / 0.7) * (0.8 + 0.2 * math.sin(2 * math.pi * 12 * t)))),
        _write("fill.wav", _render(0.9, lambda t: math.sin(2 * math.pi * (300 * t + 250 * t * t))
                                   * math.sin(math.pi * t / 0.9) * 0.7)),
        _write("draw.wav", _render(0.7, lambda t: draw_n() * (0.5 + 0.5 * math.sin(2 * math.pi * 9 * t)) ** 2
                                   * math.sin(math.pi * t / 0.7))),
        _write("boing.wav", _render(0.5, lambda t: math.sin(2 * math.pi * (300 * t + 80 * math.sin(2 * math.pi * 6 * t) / 6))
                                    * math.exp(-t * 6))),
    ]

    def coins(t: float) -> float:                  # trois contacts métalliques irréguliers
        v = 0.0
        for delay, f in ((0, 2460), (0.085, 3110), (0.21, 2080)):
            q = t - delay
            if q >= 0:
                v += (math.sin(2 * math.pi * f * q) * 0.55 + math.sin(2 * math.pi * f * 1.73 * q) * 0.25
                      + math.sin(2 * math.pi * f * 2.31 * q) * 0.12) * math.exp(-q * 18)
        return v

    def clock(t: float) -> float:                  # tic-tac : quatre petits coups alternés
        v = 0.0
        for j in range(4):
            q = t - j * 0.4
            if q >= 0:
                v += math.sin(2 * math.pi * (1800 if j % 2 == 0 else 1300) * q) * math.exp(-q * 120)
        return v

    files.append(_write("coins.wav", _render(0.55, coins)))
    files.append(_write("clock.wav", _render(1.7, clock)))
    return files


if __name__ == "__main__":
    for path in build():
        print(path)
