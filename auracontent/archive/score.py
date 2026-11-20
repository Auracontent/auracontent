"""Musique composée, bruitages et mixage d'un short d'archives.

plan.json, section "music" (toutes les bornes sont des références de temps, voir timeline.py) :
  "sections": [[début, fin, "Dm" | "Am" | "Dmaj", pas_en_s], ...]   nappes + arpège de piano
  "pulse":    [[début, fin, période_s, note_midi], ...]               battement de cœur grave
  "rise":     [[début, fin], ...]                                      nappes qui montent (tension)
  "drone":    [[début, fin], ...]                                      bourdon grave (après un choc)
  "hits":     [[instant, force_0_1], ...]                              impacts (retournement, révélation)
Ajoutés d'office : un impact court sur chaque tampon, un souffle à chaque changement de plan, un impact final.
Mixage : musique sous la voix avec compression par la voix (sidechain), loudnorm puis limiteur : ~ -14 LUFS.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .timeline import LEAD_IN, Timeline

SR = 44100
PROG = {"Dm": [[50, 57, 62, 65], [46, 53, 58, 62], [43, 50, 55, 58], [45, 52, 57, 61]],
        "Am": [[45, 52, 57, 60], [44, 51, 56, 60], [42, 49, 54, 57], [40, 47, 52, 56]],
        "Dmaj": [[50, 57, 62, 65], [46, 53, 58, 62], [41, 48, 53, 57], [45, 52, 57, 61]]}


def hz(m): return 440 * 2 ** ((m - 69) / 12)


def build(episode: Path, tl: Timeline, shot_starts: list[float], stamp_times: list[float]) -> Path:
    rng = np.random.default_rng(5)
    D = tl.dur; n = int(SR * D); t = np.arange(n) / SR
    mus, sfx = np.zeros(n), np.zeros(n)

    def lp(x, k):
        c = np.cumsum(np.concatenate([[0], x])); y = (c[k:] - c[:-k]) / k; return np.concatenate([y, np.zeros(len(x) - len(y))])

    def put(b, t0, s):
        i = int(t0 * SR); a = max(0, -i); j = min(n, i + len(s))
        if j > max(0, i):
            b[max(0, i):j] += s[a:a + j - max(0, i)]

    def piano(f, dur, amp):
        tt = np.arange(int(dur * SR)) / SR
        return amp * sum(a * np.sin(2 * np.pi * f * h * tt + ph) for h, a, ph in [(1, 1, 0), (2, .45, 1), (3, .18, 2), (4, .08, .5)]) \
            * np.exp(-tt * 1.4) * np.minimum(1, tt * 80)

    def pad(f, dur, amp, att=1.5):
        tt = np.arange(int(max(0.1, dur) * SR)) / SR
        s = sum(np.sin(2 * np.pi * f * (1 + d) * tt + k) for k, d in enumerate([-0.004, 0, 0.005])) / 3
        return amp * s * np.minimum(1, tt / att) * np.minimum(1, np.maximum(0, dur - tt) / att)

    def hit(f=40, dur=2.5, amp=0.5):
        tt = np.arange(int(dur * SR)) / SR
        return amp * (np.sin(2 * np.pi * f * tt * (1 - 0.25 * tt)) * np.exp(-tt * 2.2) + 0.5 * lp(rng.normal(0, 1, len(tt)), 30) * np.exp(-tt * 14))

    def whoosh(dur=0.7, amp=0.07):
        m = int(dur * SR); return amp * lp(rng.normal(0, 1, m), 14) * np.sin(np.linspace(0, np.pi, m)) ** 2

    M = tl.plan.get("music", {})
    for a, b, name, step in M.get("sections", [["0", "fin", "Dm", 4.0]]):
        t0, t1 = tl.t(a), tl.t(b); k = 0; tt = t0
        while tt < t1 - 0.3:
            ch = PROG.get(name, PROG["Dm"])[k % 4]; d = min(step, t1 - tt)
            put(mus, tt, pad(hz(ch[0] - 12), d + 1.2, 0.06)); put(mus, tt, pad(hz(ch[1]), d + 1.2, 0.036))
            for j, m in enumerate([ch[0], ch[2], ch[3], ch[2]]):
                if tt + j * step / 4 < t1 - 0.2:
                    put(mus, tt + j * step / 4, piano(hz(m + 12), 2.5, 0.05))
            tt += step; k += 1
    for a, b, per, note in M.get("pulse", []):
        for tb in np.arange(tl.t(a), tl.t(b), per):
            put(mus, tb, piano(hz(note), 0.6, 0.07)); put(mus, tb + 0.22, piano(hz(note), 0.4, 0.04))
    for a, b in M.get("rise", []):
        t0, t1 = tl.t(a), tl.t(b); sp = t1 - t0
        for k, m in enumerate([50, 52, 53, 55, 57, 58]):
            put(mus, t0 + k * sp / 6, pad(hz(m), sp / 6 + 1.5, 0.03 + 0.01 * k, att=1))
    for a, b in M.get("drone", []):
        put(mus, tl.t(a), pad(hz(38), tl.t(b) - tl.t(a), 0.085, att=2))
    for a, amp in M.get("hits", []):
        put(sfx, tl.t(a), hit(32, 4.5, float(amp)))
    put(sfx, tl.vo_end - 0.1, hit(36, 4, 0.8))
    mus += lp(rng.normal(0, 1, n), 600) * 0.3 * (0.6 + 0.4 * np.sin(2 * np.pi * 0.07 * t))
    for s0 in stamp_times:
        put(sfx, s0, hit(55, 0.7, 0.5))
    for s0 in shot_starts[1:]:
        put(sfx, s0 - 0.35, whoosh())

    def norm(x, p): return x / max(1e-9, np.abs(x).max()) * p
    mus = norm(mus * np.clip(t / 0.3, 0, 1) * np.clip((D - t) / 1.5, 0, 1), 0.8); sfx = norm(sfx, 0.8)
    work = episode / "build"; work.mkdir(exist_ok=True)
    for name, x in [("music", mus), ("sfx", sfx)]:
        with wave.open(str(work / f"{name}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((x * 32767).astype(np.int16).tobytes())
    mix = work / "mix.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(episode / "voice" / "voice.wav"), "-i", str(work / "music.wav"),
                    "-i", str(work / "sfx.wav"), "-filter_complex",
                    f"[0:a]adelay={int(LEAD_IN * 1000)}:all=1,apad,asplit[v1][v2];[1:a]volume=0.42[m];"
                    "[m][v1]sidechaincompress=threshold=0.03:ratio=4:attack=60:release=700[md];[2:a]volume=0.55[s];"
                    "[md][s][v2]amix=inputs=3:duration=shortest:weights=1 1 2.2:normalize=0,"
                    "loudnorm=I=-14:TP=-1.5:LRA=11,volume=3dB,alimiter=limit=0.89",
                    "-t", f"{D:.3f}", "-ar", "48000", "-ac", "2", str(mix)], check=True)
    return mix
