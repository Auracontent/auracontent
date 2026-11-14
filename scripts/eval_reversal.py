"""Évalue le contrôle « retournement » sur les 10 titres d'anecdotes du run 43445686241 (13/11/2026).

    python scripts/eval_reversal.py            # nouveau critère (anecdote : la surprise est-elle gardée ?)
    python scripts/eval_reversal.py --ancien   # critère d'avant, pour comparer

Un appel LLM par titre, sur les petits modèles de brain.simple_models (jamais Gemini, réservé au script).
Les clés viennent de l'environnement, comme en CI. Rien n'est écrit (ni historique, ni Hugging Face).
"""
import sys

from auracontent.channels.base_channel import load_channel_config
from auracontent.channels.mystery.brain import MysteryBrain
from auracontent.core.brain.llm_client import LLMClient

# (article, anecdote telle qu'affichée dans le log, titre écrit pendant le run, verdict du run). Le log coupe les
# anecdotes à 140 caractères : celles qui finissent par « … » sont tronquées (texte exact, rien d'ajouté).
CASES = [
    ("Barre des Écrins",
     "Longtemps point culminant de la France, la barre des Écrins ne l'était plus le jour de sa première ascension.",
     "1864 : La Barre des Écrins, 4\u202f101\u202fm, était\u2011elle déjà hors du top français ?",
     "rejeté (16 mots, faux compte)"),
    ("Grotte de Lascaux",
     "C'est en chassant un lapin que le chien Robòt permit à son maître Georges Ravidat de découvrir la grotte de "
     "Lascaux.",
     "1. Le chien Robòt a mené Georges Ravidat à la grotte de Lascaux", "rejeté (retournement)"),
    ("Stenay",
     "Le 11 novembre 1918, quelques heures avant l'armistice, la division d'infanterie américaine reprit la ville "
     "de Stenay (blason) au prix de 36…",
     "365 morts pour reprendre Stenay le 11 novembre 1918 : pourquoi les bains ?", "rejeté (ne nomme pas l'objet)"),
    ("Côte-d'Or",
     "Le département français de la Côte-d'Or doit son nom à l'aspect doré que prend le vignoble bourguignon à "
     "l'automne. C'est le seul départemen…",
     "1790, pourquoi Côte-d'Or porte un nom poétique plutôt que géographique?", "rejeté (retournement)"),
    ("Châteauneuf-du-pape (AOC)",
     "Il est possible, à Châteauneuf-du-Pape, pour l'élaboration des vins rouges, d'utiliser aussi, en assemblage, "
     "des cépages blancs.",
     "Châteauneuf-du-pape 18 cépages autorisés les rouges mélangent blancs", "rejeté (retournement)"),
    ("Tende (Alpes-Maritimes)",
     "Le monument aux morts de Tende porte l'inscription à ses enfants tombés glorieusement pendant la Première "
     "Guerre mondiale Grande Guerre 1915…",
     "Monument aux morts de Tende, enfants tombés glorieusement 1915\u20111918", "rejeté (retournement)"),
    ("Saint-Gingolph (Valais)",
     "Les défunts de Saint-Gingolph sont inhumés à l'étranger sans quitter leur paroisse.",
     "En 1153, Saint\u2011Gingolph est appelé Sancti Gengulfii. Pourquoi ce nom?", "rejeté (retournement)"),
    ("CEVA",
     "La mise en service complète du CEVA Cornavin - Eaux-Vives - Annemasse entre la France et la Suisse a pris "
     "131 ans, de 1888 à 2019.",
     "2019: Le CEVA Genève Annemasse enfin fonctionnel après 131 ans depuis 1888", "rejeté (retournement)"),
    ("Poissons (Haute-Marne)",
     "La ville de Poissons, dans la Haute-Marne, est jumelée à celle d'Avril, en Meurthe-et-Moselle.",
     "Pourquoi Poissons (Haute-Marne) est jumelé à Avril (Meurthe-et-Moselle) ?", "rejeté (ne nomme pas l'objet)"),
    ("Assemblée nationale (France)",
     "Les anciens députés français peuvent continuer à assister aux séances de l'Assemblée nationale depuis le "
     "« cimetière ».",
     "1986: Depuis la tenue des 577 députés, les anciens assistent au Palais depuis le cimetière",
     "rejeté (90 caractères)"),
]


def main(argv: list[str]) -> int:
    old = "--ancien" in argv
    brain = MysteryBrain(config=load_channel_config("mystery"), llm=LLMClient.create_default())
    passed = 0
    for article, anecdote, title, run in CASES:
        source = {"title": article, "extract": anecdote}
        if not old:
            source["anecdote"] = anecdote
        ok, reason = brain.has_reversal(title, source)
        passed += ok
        print(f"{'✅ passe ' if ok else '❌ rejeté'} | {title}\n           juge : {reason}\n           run : {run}")
    print(f"\n{passed}/{len(CASES)} titre(s) passent le critère {'ancien' if old else 'nouveau'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
