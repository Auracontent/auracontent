"""Normalisation du texte français avant synthèse vocale (porté de l'ancien AudioEngine).

La prononciation propre à une chaîne (mythe -> mite, château -> châto...) reste dans
la section `audio.pronunciation` du YAML de la chaîne ; ici uniquement le commun :
ponctuation, siècles et rois en chiffres romains, abréviations.
"""
import re

_ORDINALS = {
    "I": "premier", "II": "deuxième", "III": "troisième", "IV": "quatrième", "V": "cinquième",
    "VI": "sixième", "VII": "septième", "VIII": "huitième", "IX": "neuvième", "X": "dixième",
    "XI": "onzième", "XII": "douzième", "XIII": "treizième", "XIV": "quatorzième",
    "XV": "quinzième", "XVI": "seizième", "XVII": "dix-septième", "XVIII": "dix-huitième",
    "XIX": "dix-neuvième", "XX": "vingtième", "XXI": "vingt et unième",
}
_CARDINALS = {
    "II": "deux", "III": "trois", "IV": "quatre", "V": "cinq", "VI": "six", "VII": "sept",
    "VIII": "huit", "IX": "neuf", "X": "dix", "XI": "onze", "XII": "douze", "XIII": "treize",
    "XIV": "quatorze", "XV": "quinze", "XVI": "seize", "XVII": "dix-sept", "XVIII": "dix-huit",
}
_ROMAN = "|".join(sorted(_ORDINALS, key=len, reverse=True))
_SOVEREIGNS = r"Louis|Henri|Charles|Philippe|François|Napoléon|Jean|Pie|Benoît|Grégoire|Léon"

_PUNCTUATION = [
    (re.compile(r"«\s*|\s*»|[“”]"), '"'),
    (re.compile(r"[‘’]"), "'"),
    (re.compile(r"…|\.{4,}"), "..."),
    (re.compile(r"\s*[–—]\s*"), ", "),        # tirets d'incise -> pause courte
    (re.compile(r"\s+([,;:!?])"), r"\1"),     # pas d'espace avant la ponctuation
    (re.compile(r"([,;:!?])(?=[^\s\d\"'])"), r"\1 "),  # un espace après
]
_ABBREVIATIONS = [
    (re.compile(r"\bav\.\s*J\.-C\.", re.I), "avant Jésus-Christ"),
    (re.compile(r"\bap\.\s*J\.-C\.", re.I), "après Jésus-Christ"),
    (re.compile(r"\benv\.", re.I), "environ"),
    (re.compile(r"(?<=\d)\s*km\b", re.I), " kilomètres"),
    (re.compile(r"(?<=\d)\s*m\b"), " mètres"),
]


def _century(match: re.Match) -> str:
    return f"{_ORDINALS[match.group(1).upper()]} siècle"


def _sovereign(match: re.Match) -> str:
    name, numeral = match.group(1), match.group(2)
    if numeral in ("I", "Ier", "1er"):
        return f"{name} premier"
    return f"{name} {_CARDINALS.get(numeral, numeral)}"


def normalize_fr(text: str) -> str:
    text = str(text or "").strip()
    for pattern, repl in _PUNCTUATION:
        text = pattern.sub(repl, text)

    text = re.sub(rf"\b({_ROMAN})(?:e|ème|eme|er)?\s+siècles?\b", _century, text)
    text = re.sub(rf"\b({_SOVEREIGNS})\s+(Ier|1er|{_ROMAN})\b", _sovereign, text)
    for pattern, repl in _ABBREVIATIONS:
        text = pattern.sub(repl, text)

    return " ".join(text.split())
