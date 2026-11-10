"""Point d'entrée de la génération. À lancer depuis la racine du dépôt :

    python -m auracontent.cli.generate                # toutes les chaînes du registre, script + vidéo
    python -m auracontent.cli.generate mystery              # une seule chaîne
    python -m auracontent.cli.generate mystery --script-only
    python -m auracontent.cli.generate mystery --upload     # dépose la vidéo + légende sur Hugging Face (CI)
    python -m auracontent.cli.generate mystery --sync-state # historiques (sujets, hooks) lus/sauvés sur HF (CI)
"""
import argparse
import sys

from auracontent.core.brain.global_brain import GlobalBrain
from auracontent.core.brain.llm_client import LLMClient
from auracontent.core.pipeline import produce_video
from auracontent.services.publishing.state_sync import pull_state, push_state


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="AuraContent : génération de vidéos courtes")
    parser.add_argument("channels", nargs="*", help="chaînes à produire (défaut : toutes)")
    parser.add_argument("--script-only", action="store_true", help="s'arrêter au script JSON")
    parser.add_argument("--upload", action="store_true", help="envoyer la vidéo finale sur Hugging Face")
    parser.add_argument("--sync-state", action="store_true", help="lire/sauver les historiques sur Hugging Face")
    args = parser.parse_args(argv)

    if args.sync_state:
        pull_state()

    llm = LLMClient.create_default()
    brain = GlobalBrain(llm_client=llm)
    channels = args.channels or list(brain.channels)

    results = {}
    for name in channels:
        try:
            script_path = brain.run_channel(name)
            if not args.script_only:
                produce_video(brain.channels[name], llm, script_path, upload=args.upload)
            results[name] = True
        except Exception as e:
            print(f"❌ {name} : {e}")
            results[name] = False

    # On ne sauvegarde l'état que si au moins une chaîne a réussi (évite de « brûler » un sujet sans vidéo)
    if args.sync_state and any(results.values()):
        push_state()
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
