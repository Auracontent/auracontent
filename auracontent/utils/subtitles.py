"""Sous-titres SRT par petits groupes de mots, calés sur la durée de la scène."""
from __future__ import annotations

import os
import re

_CLAUSE_END = (".", ",", ";", ":", "!", "?", "…")
_LINK_WORDS = frozenset(
    "le la les l' un une des de du d' et ou à au aux en ne n'a n'est qu'il qu'elle que qui "
    "ce cet cette ces son sa ses leur leurs par pour sur dans avec sans a est ont sont".split()
)
_SILENT_PUNCT = ".,;:…"          # retirée à l'affichage ; « ? » et « ! » restent


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _group_words(words: list[str], max_words: int) -> list[list[str]]:
    """Groupes de `max_words` mots au plus, coupés à la ponctuation.

    Une légende ne chevauche jamais deux propositions : plus de « divisés, et » à l'écran.
    """
    groups, current = [], []
    for word in words:
        current.append(word)
        if word.endswith(_CLAUSE_END):
            groups.append(current)
            current = []
        elif len(current) >= max_words:
            # un mot-outil en fin de légende (« n'a », « de », « et ») passe au groupe suivant
            carry = [current.pop()] if len(current) > 1 and word.lower() in _LINK_WORDS else []
            groups.append(current)
            current = carry
    if current:
        groups.append(current)
    return groups


def _display(group: list[str], uppercase: bool, highlight_color: str | None) -> str:
    shown = []
    for i, word in enumerate(group):
        if i == len(group) - 1:
            word = word.rstrip(_SILENT_PUNCT) or word
        if uppercase:
            word = word.upper()
        # les chiffres (dates, quantités) sont l'information la plus forte : on les met en couleur
        if highlight_color and re.search(r"\d", word):
            word = f'<font color="{highlight_color}">{word}</font>'
        shown.append(word)
    return " ".join(shown)


def generate_grouped_srt(
    text: str,
    duration: float,
    output_path: str,
    max_words_per_caption: int = 3,
    min_caption_dur: float = 0.45,
    uppercase: bool = False,
    highlight_color: str | None = None,
) -> str | None:
    """Découpe `text` en groupes de mots dont la durée est proportionnelle à leur longueur."""
    words = str(text or "").split()
    if not words or duration <= 0:
        return None

    groups = _group_words(words, max_words_per_caption)
    weights = [sum(len(w) for w in g) + len(g) for g in groups]
    total = sum(weights)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    lines, start = [], 0.0
    for i, (group, weight) in enumerate(zip(groups, weights), start=1):
        end = duration if i == len(groups) else min(start + max(duration * weight / total, min_caption_dur), duration)
        lines.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{_display(group, uppercase, highlight_color)}\n")
        start = end

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return output_path
