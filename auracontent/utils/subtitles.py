"""Sous-titres SRT par petits groupes de mots, calés sur la durée de la scène."""
from __future__ import annotations

import os


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def generate_grouped_srt(
    text: str,
    duration: float,
    output_path: str,
    max_words_per_caption: int = 3,
    min_caption_dur: float = 0.45,
) -> str | None:
    """Découpe `text` en groupes de mots dont la durée est proportionnelle à leur longueur."""
    words = str(text or "").split()
    if not words or duration <= 0:
        return None

    groups = [words[i : i + max_words_per_caption] for i in range(0, len(words), max_words_per_caption)]
    weights = [sum(len(w) for w in g) + len(g) for g in groups]
    total = sum(weights)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    lines, start = [], 0.0
    for i, (group, weight) in enumerate(zip(groups, weights), start=1):
        end = duration if i == len(groups) else min(start + max(duration * weight / total, min_caption_dur), duration)
        lines.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{' '.join(group)}\n")
        start = end

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path
