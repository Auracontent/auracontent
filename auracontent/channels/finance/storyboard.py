"""Storyboard de la chaîne finance : la suite des scènes de chaque concept est fixée ici, pas par le LLM.

Chaque concept a sa propre suite (5 à 7 scènes, rôles adaptés : la règle des 72 n'a pas de scène « belief »
mais deux exemples chiffrés). Le LLM écrit le texte de chaque scène et choisit seulement, dans `visual`, une
variante parmi celles que le gabarit sait réellement dessiner (VARIANTS). Les rôles et les gabarits viennent
de STORYBOARDS ; SCENE_KEYS dit quels résultats de calc.py chaque rôle doit citer (par défaut : la scène
« reveal » cite le résultat principal) ; MUST_SAY, les expressions que la narration doit contenir.
"""
from __future__ import annotations

# Variantes dessinables de chaque gabarit (nom -> description donnée au LLM). La première est le défaut.
VARIANTS: dict[str, dict[str, str]] = {
    "deux_arbres": {"arbres": "deux arbres de tailles différentes, Léa et Hugo à côté",
                    "piles": "deux piles de pièces de hauteurs différentes"},
    "deux_courbes": {"courbes": "deux courbes qui montent sur un graphique",
                     "ecart": "deux courbes avec l'écart entre elles coloré"},
    "barres": {"barres": "deux ou trois barres verticales comparées",
               "jauge": "une barre qui se vide ou se remplit"},
    "curseur_temps": {"frise": "une frise des années avec un curseur qui avance",
                      "sablier": "un sablier qui s'écoule"},
    "carte_fin": {"logo": "carte de fin avec le logo et l'hypothèse"},
}

ROLES: dict[str, str] = {
    "hook": "l'accroche",
    "context": "la situation de départ",
    "belief": "ce que tout le monde croit",
    "mechanism": "le mécanisme, avec une image concrète",
    "reveal": "le résultat chiffré",
    "example": "un deuxième exemple chiffré, avec l'autre taux",
    "takeaway": "ce qu'il faut retenir",
    "disclaimer": "rappel : exemple simplifié",
}

# (rôle, gabarit) scène par scène, propre à chaque concept : 5 à 7 scènes de ~7-9 s, 45-60 s de vidéo.
STORYBOARDS: dict[str, tuple[tuple[str, str], ...]] = {
    # deux personnages, une intuition à contredire : la suite complète
    "interets_composes": (("hook", "deux_arbres"), ("context", "curseur_temps"), ("belief", "barres"),
                          ("mechanism", "deux_courbes"), ("reveal", "deux_arbres"), ("takeaway", "barres"),
                          ("disclaimer", "carte_fin")),
    # pas d'intuition contraire à poser : le mécanisme (les prix montent) suffit
    "inflation": (("hook", "barres"), ("context", "curseur_temps"), ("mechanism", "deux_courbes"),
                  ("reveal", "barres"), ("takeaway", "curseur_temps"), ("disclaimer", "carte_fin")),
    "cout_du_temps": (("hook", "deux_courbes"), ("context", "curseur_temps"), ("belief", "barres"),
                      ("mechanism", "curseur_temps"), ("reveal", "deux_courbes"), ("takeaway", "barres"),
                      ("disclaimer", "carte_fin")),
    "frais": (("hook", "barres"), ("context", "curseur_temps"), ("mechanism", "barres"),
              ("reveal", "deux_courbes"), ("takeaway", "barres"), ("disclaimer", "carte_fin")),
    # une règle et deux exemples chiffrés, sans scène « belief »
    "regle_72": (("hook", "curseur_temps"), ("mechanism", "curseur_temps"), ("reveal", "barres"),
                 ("example", "barres"), ("takeaway", "deux_courbes"), ("disclaimer", "carte_fin")),
}

# Résultats (clés de calc.py) que chaque rôle doit citer ; absent = {"reveal": (résultat principal,)}.
SCENE_KEYS: dict[str, dict[str, tuple[str, ...]]] = {
    "cout_du_temps": {"reveal": ("cost", "paid_gap")},
    "regle_72": {"reveal": ("years_rule",), "example": ("years_rule_b",)},
}

# Expressions que la narration doit contenir (comparaison sans casse ni accents).
MUST_SAY: dict[str, tuple[str, ...]] = {
    "regle_72": ("règle des 72",),
}


def storyboard(concept: str) -> tuple[tuple[str, str], ...]:
    try:
        return STORYBOARDS[concept]
    except KeyError:
        raise KeyError(f"Concept sans storyboard : {concept}") from None


def scene_keys(concept: str, headline: str) -> dict[str, tuple[str, ...]]:
    return SCENE_KEYS.get(concept, {"reveal": (headline,)})


def must_say(concept: str) -> tuple[str, ...]:
    return MUST_SAY.get(concept, ())


def describe(concept: str) -> str:
    """Bloc du prompt : rôle, gabarit et variantes possibles de chaque scène."""
    lines = []
    for i, (role, template) in enumerate(storyboard(concept), 1):
        options = ", ".join(f'"{name}" ({desc})' for name, desc in VARIANTS[template].items())
        lines.append(f"Scène {i} : {ROLES[role]}. 'visual' au choix : {options}")
    return "\n".join(lines)


def apply(concept: str, scenes: list[dict]) -> list[str]:
    """Impose rôle, gabarit et numérotation ; ramène une variante inconnue au défaut. Retourne les remarques."""
    notes = []
    for i, ((role, template), scene) in enumerate(zip(storyboard(concept), scenes, strict=True), 1):
        scene.update(id=i, role=role, template=template)
        variant = str(scene.get("visual", "")).strip().strip('"').lower()
        if variant not in VARIANTS[template]:
            default = next(iter(VARIANTS[template]))
            notes.append(f"scène {i} : variante « {scene.get('visual')} » inconnue pour {template}, "
                         f"« {default} » retenue")
            variant = default
        scene["visual"] = variant
    return notes
