"""Contrôle de plan.json d'un épisode « expliqué par un bonhomme » : bloquant avant la voix, la planche et le rendu.

Règles reprises de « L'éco du jour » : un chiffre dans la voix porte `source`, `calc` ou `exemple` (montant fictif
présenté comme un exemple : « imagine que tu gagnes 1 850 € ») ; jamais d'ordre d'investir ni de promesse.
"""
from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from auracontent.actu.plan import IMPERATIVES, PROMISES, PlanError, spoken_words

from . import draw as D

if TYPE_CHECKING:
    from pathlib import Path

SCENE_TYPES = ("accroche", "compteur", "notifications", "choix", "repartition", "liste", "fin")
FORMATS = ("vertical", "paysage")
# mots prononcés : Short de 40 à 65 s ; vidéo longue de 3 à 12 min
WORDS = {"vertical": (90, 165), "paysage": (400, 1700)}

__all__ = ["PlanError", "check", "check_refs", "check_suite", "pending_promise", "validate"]


def _num(line: dict) -> bool:
    return bool(re.search(r"\d", line.get("text", "") + " " + line.get("say", "")))


def check(plan: dict) -> list[str]:
    """Liste des problèmes bloquants (vide = plan valide)."""
    errs: list[str] = []
    for key in ("slug", "title", "caption", "lines", "scenes"):
        if not plan.get(key):
            errs.append(f"champ manquant : {key}")
    if errs:
        return errs
    fmt = plan.get("format", "vertical")
    if fmt not in FORMATS:
        return [f"format {fmt!r} inconnu ({', '.join(FORMATS)})"]
    sources = plan.get("sources") or {}
    for k, s in sources.items():
        if not isinstance(s, dict) or not str(s.get("url", "")).startswith("http") or not s.get("name"):
            errs.append(f"source {k!r} : il faut name et url (http...)")
    lines = plan["lines"]
    words = sum(spoken_words(ln) for ln in lines)
    lo, hi = WORDS[fmt]
    if not lo <= words <= hi:
        errs.append(f"voix de {words} mots prononcés : il en faut {lo} à {hi} pour le format {fmt}")
    for i, ln in enumerate(lines):
        text = ln.get("text", "")
        if not text:
            errs.append(f"phrase {i} vide")
            continue
        if len(text.split()) > 22:
            errs.append(f"phrase {i} trop longue ({len(text.split())} mots, 22 au plus)")
        if _num(ln) and not (ln.get("calc") or ln.get("exemple") or ln.get("source") in sources):
            errs.append(f"phrase {i} : chiffre sans « source », « calc » ni « exemple » : « {text[:50]} »")
        if _num(ln) and not ln.get("say"):
            errs.append(f"phrase {i} : chiffre sans « say » (la phrase telle qu'elle doit être lue)")
        low = text.lower()
        for w in IMPERATIVES:
            if re.search(rf"(^|[.!?]\s+){re.escape(w)}\b", low):
                errs.append(f"phrase {i} : ordre d'investir (« {w} ») : la vidéo explique, elle ne conseille pas")
        for w in PROMISES:
            if w in f" {low} ":
                errs.append(f"phrase {i} : promesse interdite (« {w} »)")
    scenes = plan["scenes"]
    for j, sc in enumerate(scenes):
        typ = sc.get("type")
        if typ not in SCENE_TYPES:
            errs.append(f"scène {j} : type {typ!r} inconnu ({', '.join(SCENE_TYPES)})")
            continue
        if "from" not in sc:
            errs.append(f"scène {j} : « from » manquant")
        if sc.get("source") and sc["source"] not in sources:
            errs.append(f"scène {j} : source {sc['source']!r} absente de sources")
        bh = sc.get("bonhomme") or {}
        for r in [bh, *bh.get("reactions", [])]:
            if r.get("expr") and r["expr"] not in D.EXPRS:
                errs.append(f"scène {j} : expression {r['expr']!r} inconnue ({', '.join(D.EXPRS)})")
            if r.get("arms") and r["arms"] not in D.ARMS:
                errs.append(f"scène {j} : bras {r['arms']!r} inconnus ({', '.join(D.ARMS)})")
        if typ == "compteur" and not isinstance(sc.get("value"), (int, float)):
            errs.append(f"scène {j} (compteur) : « value » doit être un nombre")
        if typ == "notifications":
            items = sc.get("items") or []
            if not 1 <= len(items) <= 5:
                errs.append(f"scène {j} (notifications) : 1 à 5 notifications")
            if sc.get("at") and len(sc["at"]) != len(items):
                errs.append(f"scène {j} (notifications) : autant de « at » que de notifications")
            if sc.get("compteur") and not isinstance(sc["compteur"].get("value"), (int, float)):
                errs.append(f"scène {j} (notifications) : compteur.value doit être un nombre")
        if typ == "choix":
            if not (isinstance(sc.get("left"), dict) and isinstance(sc.get("right"), dict)):
                errs.append(f"scène {j} (choix) : « left » et « right » ({{label, value}})")
            if "pick" in sc and sc["pick"] not in (0, 1):
                errs.append(f"scène {j} (choix) : pick vaut 0 (gauche) ou 1 (droite)")
        if typ == "repartition":
            parts = sc.get("parts") or []
            if not 1 <= len(parts) <= 3 or any(not p.get("label") for p in parts):
                errs.append(f"scène {j} (repartition) : 1 à 3 « parts » avec un label")
        if typ == "liste":
            items = sc.get("items") or []
            if not 1 <= len(items) <= 3:
                errs.append(f"scène {j} (liste) : 1 à 3 cartes")
            if sc.get("at") and len(sc["at"]) != len(items):
                errs.append(f"scène {j} (liste) : autant de « at » que de cartes")
        if typ == "fin" and not sc.get("next"):
            errs.append(f"scène {j} (fin) : « next » (le sujet du prochain épisode) manquant")
        if len(sc.get("title", "")) > 60:
            errs.append(f"scène {j} : titre de plus de 60 caractères (illisible à la main sur un téléphone)")
        if "abonne" in (sc.get("title", "") + sc.get("title2", "") + sc.get("next", "")).lower():
            errs.append(f"scène {j} : pas d'« abonne-toi » à l'écran (n'apporte rien au spectateur)")
    if scenes and scenes[0].get("from") not in (0, "0", 0.0):
        errs.append("la première scène commence à 0")
    if scenes and scenes[0].get("type") != "accroche":
        errs.append("la première scène est l'accroche (type « accroche »)")
    elif scenes and len(scenes[0].get("title", "")) > 30:
        errs.append("accroche : titre de 30 caractères au plus (2 lignes énormes, lisibles en une seconde)")
    if lines and len(lines[0].get("text", "").split()) > 10:
        errs.append("phrase 0 (l'accroche) : 10 mots au plus, elle doit claquer dès la 1re seconde")
    if scenes and scenes[-1].get("type") != "fin":
        errs.append("la dernière scène est la carte de fin (type « fin »)")
    if len(plan.get("title", "")) > 70:
        errs.append("title : 70 caractères au plus")
    return errs


def check_refs(plan: dict, tl) -> list[str]:
    """Références de temps du plan introuvables dans la voix (à lancer quand voice/timing.json existe)."""
    errs = []

    def ref(j, what, r):
        if r is None:
            return
        try:
            tl.t(r)
        except (KeyError, ValueError) as e:
            errs.append(f"scène {j} ({what}) : {e}")

    for j, sc in enumerate(plan["scenes"]):
        ref(j, "from", sc.get("from"))
        for k in ("title_at", "title2_at", "carte_at", "chiffre_at", "sous_titre_at", "count_at", "pick_at"):
            ref(j, k, sc.get(k))
        for r in sc.get("at") or []:
            ref(j, "at", r)
        for side in ("left", "right"):
            ref(j, f"{side}.at", (sc.get(side) or {}).get("at"))
        for p in sc.get("parts") or []:
            ref(j, "parts.at", p.get("at"))
        for r in (sc.get("bonhomme") or {}).get("reactions", []):
            ref(j, "reactions.at", r.get("at"))
    return errs


# ---------- la suite promise ----------
def _episodes(root: Path) -> list[tuple[str, dict]]:
    """Épisodes publiés (dossiers datés avec plan.json, sans PROBLEME.md ni ESSAI.md), dans l'ordre."""
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}-", p.name)):
        if (d / "plan.json").exists() and not (d / "PROBLEME.md").exists() and not (d / "ESSAI.md").exists():
            out.append((d.name, json.loads((d / "plan.json").read_text(encoding="utf-8"))))
    return out


def _promise(plan: dict) -> str:
    fin = (plan.get("scenes") or [{}])[-1]
    return str(fin.get("next", "")).strip() if fin.get("type") == "fin" else ""


def pending_promise(root: Path, before: str | None = None) -> tuple[str, str] | None:
    """(dossier, sujet) de la dernière « suite » annoncée et pas encore tenue, parmi les épisodes antérieurs à `before`.

    Un épisode tient la promesse quand son plan porte "suite_de": "<dossier qui l'a annoncée>". Un épisode hors suite
    (sujet imposé) porte "hors_suite": "<raison>" et réannonce la même suite : la promesse reste due au suivant.
    """
    pending = None
    for name, plan in _episodes(root):
        if before and name >= before:
            break
        if pending and plan.get("hors_suite"):
            continue                                   # la promesse en attente reste due
        promise = _promise(plan)
        pending = (name, promise) if promise else None
    return pending


def check_suite(plan: dict, root: Path, name: str) -> list[str]:
    """L'épisode `name` tient-il la suite promise par l'épisode précédent ?"""
    pending = pending_promise(root, before=name)
    if not pending:
        return []
    src, promise = pending
    if plan.get("suite_de") == src:
        return []
    if plan.get("hors_suite"):
        if _promise(plan).lower() != promise.lower():
            return [f"épisode hors suite : la carte de fin doit réannoncer la suite promise « {promise} » (next)"]
        return []
    return [f"l'épisode {src} a promis « {promise} » : traite ce sujet et mets \"suite_de\": \"{src}\" "
            "(ou, si le sujet est imposé, \"hors_suite\": \"<raison>\" et réannonce cette suite à la fin)"]


def validate(plan: dict) -> None:
    errs = check(plan)
    if errs:
        raise PlanError("plan.json invalide :\n  - " + "\n  - ".join(errs))
