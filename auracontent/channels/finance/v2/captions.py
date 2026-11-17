"""Minutage des mots et sous-titres mot par mot (ASS, brûlés par FFmpeg/libass).

Le minutage vient des événements WordBoundary d'Edge TTS (offsets en unités de 100 ns) quand la voix est
synthétisée ; à défaut (aperçu sans voix), il est estimé à partir de la longueur des mots.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Word:
    text: str
    start: float
    end: float


def from_edge(boundaries: list[dict], offset: float = 0.0) -> list[Word]:
    """Événements WordBoundary d'Edge TTS -> mots minutés (secondes)."""
    words = []
    for b in boundaries:
        start = b["offset"] / 1e7 + offset
        words.append(Word(b["text"], start, start + b["duration"] / 1e7))
    return words


def estimate(text: str, start: float, duration: float, pause: float = 0.12) -> list[Word]:
    """Minutage estimé : temps réparti selon la longueur des mots, petite pause après la ponctuation."""
    tokens = [x for x in text.split(" ") if x]          # espaces normaux seulement : « 1 768 » reste un mot
    if not tokens:
        return []
    weights = [max(2, len(re.sub(r"\W", "", t))) + (4 if re.search(r"[.,:;!?]$", t) else 0) for t in tokens]
    unit = duration / sum(weights)
    words, t = [], start
    for tok, w in zip(tokens, weights, strict=True):
        speak = w * unit - (pause if re.search(r"[.,:;!?]$", tok) else 0)
        words.append(Word(tok, t, t + max(0.08, speak)))
        t += w * unit
    return words


def find(words: list[Word], needle: str, default: float = 0.0) -> float:
    """Instant où commence le premier mot contenant `needle` (pour caler une animation sur la voix)."""
    n = needle.lower()
    for w in words:
        if n in w.text.lower():
            return w.start
    return default


def groups(words: list[Word], max_words: int = 3, max_chars: int = 18) -> list[list[Word]]:
    """Paquets de mots affichés ensemble : coupure après la ponctuation, 3 mots ou 18 caractères au plus."""
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= max_words or len(" ".join(x.text for x in cur + [w])) > max_chars):
            out.append(cur)
            cur = []
        cur.append(w)
        if re.search(r"[.,:;!?]$", w.text):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _bgr(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}"


def _esc(text: str) -> str:
    return text.replace("{", "(").replace("}", ")").replace("\\", "/")


def build_ass(words: list[Word], *, bandeau: tuple[str, str] | None = None, total: float = 0.0,
              size: int = 76, y_bottom: int = 1400, ink: str = "#1A1A1A", highlight: str = "#0E9F8E",
              gold: str = "#E0A526", paper: str = "#F7F3EA", font: str = "Poppins") -> str:
    """Fichier ASS : sous-titres mot par mot (mot prononcé en couleur, légèrement agrandi) et bandeau en haut."""
    margin_v = 1920 - y_bottom
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{size},{_bgr(ink)},{_bgr(ink)},{_bgr(paper)},&H00000000,-1,0,0,0,100,100,0,0,1,7,0,2,90,150,{margin_v},1
Style: Top,{font},66,{_bgr(ink)},{_bgr(ink)},{_bgr(paper)},&H00000000,-1,0,0,0,100,100,0,0,1,6,0,8,90,150,250,1
Style: TopBox,{font},70,{_bgr(ink)},{_bgr(ink)},{_bgr(gold)},&H00000000,-1,0,0,0,100,100,0,0,3,14,0,8,90,150,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if bandeau and total > 0:
        top, box = bandeau
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(total)},Top,,0,0,0,,{_esc(top)}")
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(total)},TopBox,,0,0,0,,{_esc(box)}")
    hi = _bgr(highlight)
    flat = [w for grp in groups(words) for w in grp]
    nxt = {id(w): (flat[k + 1].start if k + 1 < len(flat) else w.end + 0.3) for k, w in enumerate(flat)}
    for grp in groups(words):
        for i, w in enumerate(grp):
            end = grp[i + 1].start if i + 1 < len(grp) else min(w.end + 0.25, nxt[id(w)])
            parts = []
            for j, x in enumerate(grp):
                if j == i:
                    parts.append(f"{{\\c{hi}\\fscx108\\fscy108}}{_esc(x.text)}{{\\r}}")
                else:
                    parts.append(_esc(x.text))
            lines.append(f"Dialogue: 0,{_ass_time(w.start)},{_ass_time(end)},Cap,,0,0,0,,{' '.join(parts)}")
    return head + "\n".join(lines) + "\n"
