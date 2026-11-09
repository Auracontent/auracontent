"""Point d'entrée unique. À lancer depuis la racine du dépôt :

    python main.py              # toutes les chaînes du registre
    python main.py mystery      # une seule chaîne
"""
import sys

from auracontent.core.brain.global_brain import GlobalBrain
from auracontent.core.brain.llm_client import LLMClient


def main(argv: list[str]) -> int:
    brain = GlobalBrain(llm_client=LLMClient.create_default())
    if argv:
        results = {name: brain.run_channel(name) for name in argv}
    else:
        results = brain.run_all()
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
