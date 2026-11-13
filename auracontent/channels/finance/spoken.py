"""Texte affiché et texte parlé de la chaîne finance, produits par le code (jamais par le LLM).

- `display_text` : chiffres au format français de l'écran (« 10 000 € », « 6,1 ans ») ;
- `spoken_text` : ce que lit la voix, nombres en toutes lettres (« dix mille euros », « six virgule un ans »),
  « = » -> « égale », « % » -> « pour cent ». Aucun chiffre ni symbole ne doit rester : sinon SpokenError
  (le script est alors régénéré).
"""
from __future__ import annotations

import re

from auracontent.channels.finance.calc import fmt_number

_NUMBER_RE = re.compile(r"(?<![\w,])\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:,\d+)?(?![\d])|(?<![\w,])\d+(?:[.,]\d+)?(?![\d])")
_FORBIDDEN_RE = re.compile(r"[0-9=%€$£+\u00d7*/<>#&@^_|\\]")

_UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze",
          "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
_TENS = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}


class SpokenError(ValueError):
    """Un chiffre ou un symbole reste dans le texte parlé."""


# ---------- Nombres en toutes lettres ----------
def _below_100(n: int) -> str:
    if n < 20:
        return _UNITS[n]
    tens, unit = divmod(n, 10)
    if tens in (7, 9):                                   # soixante-dix..., quatre-vingt-dix...
        base = "soixante" if tens == 7 else "quatre-vingt"
        if tens == 7 and unit == 1:
            return "soixante et onze"
        return f"{base}-{_UNITS[10 + unit]}"
    if tens == 8:
        return "quatre-vingts" if unit == 0 else f"quatre-vingt-{_UNITS[unit]}"
    word = _TENS[tens]
    if unit == 0:
        return word
    return f"{word} et un" if unit == 1 else f"{word}-{_UNITS[unit]}"


def _below_1000(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_100(rest)
    head = "cent" if hundreds == 1 else f"{_UNITS[hundreds]} cent" + ("s" if rest == 0 else "")
    return head if rest == 0 else f"{head} {_below_100(rest)}"


def int_to_words(n: int) -> str:
    """Entier en toutes lettres (orthographe traditionnelle) : 1630 -> « mille six cent trente »."""
    if n < 0:
        return "moins " + int_to_words(-n)
    if n < 1000:
        return _below_1000(n)
    parts = []
    millions, rest = divmod(n, 1_000_000)
    if millions:
        parts.append("un million" if millions == 1 else f"{int_to_words(millions)} millions")
    thousands, rest = divmod(rest, 1000)
    if thousands:
        # « mille » invariable ; « deux cents » perd son s devant « mille » : « deux cent mille »
        words = _below_1000(thousands)
        if words.endswith("cents"):
            words = words[:-1]
        if words.endswith("quatre-vingts"):
            words = words[:-1]
        parts.append("mille" if thousands == 1 else f"{words} mille")
    if rest:
        parts.append(_below_1000(rest))
    return " ".join(parts)


def number_to_words(raw: str) -> str:
    """« 10 000 », « 6,1 », « 0,5 » -> mots ; les décimales sont lues chiffre à chiffre après « virgule »."""
    raw = re.sub(r"[ \u00a0\u202f]", "", raw).replace(".", ",")
    whole, _, decimals = raw.partition(",")
    words = int_to_words(int(whole))
    if decimals:
        words += " virgule " + (int_to_words(int(decimals)) if not decimals.startswith("0")
                                else " ".join(_UNITS[int(d)] for d in decimals))
    return words


# ---------- Texte affiché ----------
def display_text(text: str) -> str:
    """Reformate chaque nombre au format de l'écran : « 10000 € » -> « 10 000 € », « 6.1 » -> « 6,1 »."""
    def fmt(m: re.Match) -> str:
        value = float(re.sub(r"[ \u00a0\u202f]", "", m.group()).replace(",", "."))
        return fmt_number(value)
    return _NUMBER_RE.sub(fmt, text)


# ---------- Texte parlé ----------
_PER = re.compile(r"\s*/\s*(an|mois|jour|semaine)\b")          # « %/an », « €/mois » -> « par an/mois »
_SYMBOLS = [
    (re.compile(r"\s*=\s*"), " égale "),
    (re.compile(r"\s*\u00d7\s*|(?<=\d)\s*x\s*(?=\d)"), " fois "),
    (re.compile(r"\s*\+\s*"), " plus "),
    (re.compile(r"\s*%"), " pour cent"),
]


def _euros(m: re.Match) -> str:
    raw = m.group(1)
    value = float(re.sub(r"[ \u00a0\u202f]", "", raw).replace(",", "."))
    words = number_to_words(raw)
    if value == 1:
        return f"{words} euro"
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{words} d'euros"
    return f"{words} euros"


def spoken_text(text: str) -> str:
    """Texte lu par la voix : nombres en lettres, symboles en mots. SpokenError s'il reste un chiffre/symbole."""
    out = _PER.sub(r" par \1", display_text(text))
    out = re.sub(rf"({_NUMBER_RE.pattern})\s*(?:€|euros?\b)", _euros, out)
    for rx, repl in _SYMBOLS:
        out = rx.sub(repl, out)
    out = _NUMBER_RE.sub(lambda m: number_to_words(m.group()), out)
    out = re.sub(r"\s+([,.;:!?…])", r"\1", re.sub(r"\s{2,}", " ", out)).strip()
    left = sorted(set(_FORBIDDEN_RE.findall(out)))
    if left:
        raise SpokenError(f"texte parlé avec chiffres ou symboles {' '.join(left)} : « {out} »")
    return out
