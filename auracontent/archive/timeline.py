"""Plan d'un short d'archives : chargement, références de temps, mots et sous-titres.

Un épisode est un dossier qui contient `plan.json` (écrit par le réalisateur) et, après l'étape voix,
`voice/timing.json` : début et fin de chaque phrase dans `voice/voice.wav`.

Références de temps acceptées partout dans le plan (shots, tampons, étiquettes, musique) :
  12.5          secondes depuis le début
  "L3"          début de la phrase 3 (0 = première phrase)
  "L3@0.5"      à 50 % de la phrase 3
  "L3.end"      fin de la phrase 3
  "w:Quarante"  début du premier mot qui contient « Quarante » ; "w:mort@L4" : à partir de la phrase 4
  "end"         fin de la voix ; "fin" : fin de la vidéo (carton compris)
  "L3+0.4", "w:Rien-0.1"   décalage en secondes
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

FPS = 30
W, H = 1080, 1920
LEAD_IN = 0.25          # silence avant la première phrase
END_CARD = 3.2          # carton final après la voix


def syllables(word: str) -> float:
    """Syllabes approximatives ; un nombre écrit en chiffres compte comme sa lecture (1927 : ~6 syllabes)."""
    digits = len(re.findall(r"\d", word))
    return max(1.0, len(re.findall(r"[aeiouyàâéèêëîïôûùœ]+", word.lower())) + 1.5 * digits)


@dataclass
class Timeline:
    plan: dict
    lines: list[tuple[float, float, str]]               # (début, fin, texte) dans la vidéo
    vo_end: float
    words: list[tuple[float, float, str]] = field(default_factory=list)
    chunks: list[list] = field(default_factory=list)

    @property
    def dur(self) -> float:
        return self.vo_end + float(self.plan.get("end_card_seconds", END_CARD))

    @property
    def nframes(self) -> int:
        return int(round(self.dur * FPS))

    # ---------- références de temps ----------
    def t(self, ref) -> float:
        if isinstance(ref, (int, float)):
            return float(ref)
        s = str(ref).strip()
        try:
            return float(s)
        except ValueError:
            pass
        m = re.fullmatch(r"(.*\S)([+-]\d+(?:\.\d+)?)", s)
        if m:
            return self.t(m.group(1)) + float(m.group(2))
        if s == "end":
            return self.vo_end
        if s == "fin":
            return self.dur
        if s.startswith("w:"):
            word, _, after = s[2:].partition("@")
            start = self.t(after) if after else 0.0
            for a, _b, w in self.words:
                if a >= start - 1e-6 and word.lower() in w.lower():
                    return a
            raise KeyError(f"mot introuvable dans la voix : {word!r}")
        m = re.fullmatch(r"L(\d+)(?:@(\d*\.?\d+)|\.(end))?", s)
        if m:
            i = int(m.group(1))
            if i >= len(self.lines):
                raise KeyError(f"phrase {i} inexistante ({len(self.lines)} phrases)")
            a, b, _ = self.lines[i]
            if m.group(3):
                return b
            if m.group(2):
                return a + float(m.group(2)) * (b - a)
            return a
        raise ValueError(f"référence de temps invalide : {ref!r}")


def load(episode: Path) -> Timeline:
    plan = json.loads((episode / "plan.json").read_text(encoding="utf-8"))
    timing = json.loads((episode / "voice" / "timing.json").read_text(encoding="utf-8"))
    lines = [(LEAD_IN + x["t0"], LEAD_IN + x["t1"], x["text"]) for x in timing["lines"]]
    tl = Timeline(plan=plan, lines=lines, vo_end=LEAD_IN + timing["duration"])
    tl.words = split_words(lines)
    tl.chunks = caption_chunks(tl.words)
    return tl


def split_words(lines) -> list[tuple[float, float, str]]:
    """Temps de chaque mot, réparti dans sa phrase selon les syllabes, avec une pause après la ponctuation."""
    out = []
    for t0, t1, text in lines:
        ws = []
        for w in re.split(r"[ \t\n]+", text.replace("New York", "New\u00a0York").strip()):
            if re.fullmatch(r"[:;…?!»«]+", w) and ws:
                ws[-1] += w
            else:
                ws.append(w)
        weights = [(syllables(w), 1.6 if re.search(r"[.…:?!]$", w) else (0.7 if w.endswith(",") else 0.0)) for w in ws]
        total = sum(a + b for a, b in weights) or 1
        u, c = (t1 - t0) / total, t0
        for w, (a, b) in zip(ws, weights):
            out.append((c, c + a * u, w))
            c += (a + b) * u
    return out


def caption_chunks(words, max_words: int = 2, max_chars: int = 14) -> list[list]:
    """Sous-titres de 1-2 mots : coupe à la ponctuation, sur deux mots ou au-delà de max_chars."""
    chunks, cur = [], []
    for i, (a, b, w) in enumerate(words):
        cur.append((a, b, w))
        txt = " ".join(x[2] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        brk = bool(re.search(r"[.…:?!,]$", w)) or len(cur) >= max_words or len(txt) > max_chars - 3
        if nxt and len(txt) + 1 + len(nxt[2]) > max_chars:
            brk = True
        if brk or not nxt:
            chunks.append([cur[0][0], cur[-1][1], cur])
            cur = []
    for i in range(len(chunks) - 1):   # le sous-titre reste jusqu'au suivant (0,5 s au plus)
        chunks[i][1] = min(chunks[i + 1][0], chunks[i][1] + 0.5)
    return chunks
