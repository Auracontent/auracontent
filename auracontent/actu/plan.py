"""Contrôle de plan.json d'un short « L'éco du jour » : bloquant avant la voix, la planche et le rendu.

Règle d'or de la chaîne : aucun chiffre sans source. Une phrase qui contient un chiffre porte `source` (clé de
`sources`) ou `calc` (le calcul fait à partir de chiffres sourcés). Chaque scène de données porte `source`.
"""
from __future__ import annotations

import re

SCENE_TYPES = ("titre", "chiffre", "courbe", "barres", "points", "fin")
DATA_TYPES = ("titre", "chiffre", "courbe", "barres")
# La vidéo explique l'actualité, elle ne dit jamais quoi faire de son argent (comme le format automatique)
IMPERATIVES = ("achète", "achetez", "investis", "investissez", "place ton", "placez", "vends", "vendez",
               "souscris", "souscrivez", "emprunte", "empruntez")
PROMISES = ("rendement garanti", "gain garanti", "sans risque", "placement sûr", "valeur sûre", "devenir riche")


class PlanError(ValueError):
    pass


def spoken_words(line: dict) -> int:
    """Mots réellement prononcés (`say` s'il existe : « trois mille cinq cent... » compte pour ce qu'il dure)."""
    return len(re.findall(r"[\wÀ-ÿ'’-]+", line.get("say") or line.get("text", "")))  # noqa: RUF001


def _num(line: dict) -> bool:
    return bool(re.search(r"\d", line.get("text", "") + " " + line.get("say", "")))


def check(plan: dict) -> list[str]:
    """Liste des problèmes bloquants (vide = plan valide)."""
    errs: list[str] = []
    for key in ("slug", "title", "caption", "date", "sources", "lines", "scenes"):
        if not plan.get(key):
            errs.append(f"champ manquant : {key}")
    if errs:
        return errs
    sources = plan["sources"]
    for k, s in sources.items():
        if not isinstance(s, dict) or not str(s.get("url", "")).startswith("http") or not s.get("name"):
            errs.append(f"source {k!r} : il faut name et url (http...)")
    lines = plan["lines"]
    words = sum(spoken_words(ln) for ln in lines)
    if not 90 <= words <= 155:
        errs.append(f"voix de {words} mots prononcés : viser 120 à 150 (45 à 60 s ; montants comptés en toutes lettres)")
    for i, ln in enumerate(lines):
        text = ln.get("text", "")
        if not text:
            errs.append(f"phrase {i} vide")
            continue
        if len(text.split()) > 22:
            errs.append(f"phrase {i} trop longue ({len(text.split())} mots, 22 au plus)")
        if _num(ln) and not ln.get("calc") and ln.get("source") not in sources:
            errs.append(f"phrase {i} : chiffre sans « source » (clé de sources) ni « calc » : « {text[:50]} »")
        low = f" {text.lower()} "
        for w in IMPERATIVES:
            if re.search(rf"(^|[.!?]\s+){re.escape(w)}\b", text.lower()):
                errs.append(f"phrase {i} : ordre donné au spectateur (« {w} ») : la vidéo explique, elle ne conseille pas")
        for w in PROMISES:
            if w in low:
                errs.append(f"phrase {i} : promesse interdite (« {w} »)")
    scenes = plan["scenes"]
    for j, sc in enumerate(scenes):
        typ = sc.get("type")
        if typ not in SCENE_TYPES:
            errs.append(f"scène {j} : type {typ!r} inconnu ({', '.join(SCENE_TYPES)})")
            continue
        if "from" not in sc:
            errs.append(f"scène {j} : « from » manquant")
        if typ in DATA_TYPES and sc.get("source") not in sources:
            errs.append(f"scène {j} ({typ}) : « source » manquante ou absente de sources")
        if typ == "courbe":
            pts = sc.get("points") or []
            if len(pts) < 3 or any(len(p) != 2 for p in pts):
                errs.append(f"scène {j} (courbe) : au moins 3 points [x, y]")
            elif [p[0] for p in pts] != sorted(p[0] for p in pts):
                errs.append(f"scène {j} (courbe) : points non triés par x")
        if typ == "barres" and not 2 <= len(sc.get("bars") or []) <= 5:
            errs.append(f"scène {j} (barres) : 2 à 5 barres")
        if typ == "points" and not 1 <= len(sc.get("items") or []) <= 3:
            errs.append(f"scène {j} (points) : 1 à 3 cartes")
        if typ == "chiffre" and not isinstance(sc.get("value"), (int, float)):
            errs.append(f"scène {j} (chiffre) : « value » doit être un nombre")
    if scenes and scenes[0].get("from") not in (0, "0", 0.0):
        errs.append("la première scène commence à 0")
    if scenes and scenes[-1].get("type") != "fin":
        errs.append("la dernière scène est la carte de fin (type « fin »)")
    if len(plan.get("title", "")) > 70:
        errs.append("title : 70 caractères au plus")
    return errs


def validate(plan: dict) -> None:
    errs = check(plan)
    if errs:
        raise PlanError("plan.json invalide :\n  - " + "\n  - ".join(errs))
