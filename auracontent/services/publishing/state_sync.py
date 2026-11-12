"""Synchronise l'état (historiques) entre assets/shared/state/ et le dataset Hugging Face.

Les runners GitHub Actions sont éphémères : sans ça, l'anti-doublon de sujets et le
bandit des hooks repartiraient de zéro à chaque exécution.

    pull_state()  # début de run : HF meta/*.json -> assets/shared/state/
    push_state()  # fin de run   : assets/shared/state/*.json -> HF meta/

Chaîne à état isolé (`state: {isolated: true}` dans son YAML) : ses historiques vivent dans
assets/shared/state/<chaîne>/ et meta/<chaîne>/ sur HF. Les autres chaînes gardent les fichiers partagés
historiques, sans migration : leur comportement ne change pas.
"""
from __future__ import annotations

import os
import shutil
from functools import lru_cache
from pathlib import Path

from config.settings import ASSETS_DIR

STATE_DIR = ASSETS_DIR / "shared" / "state"
STATE_FILES = ("global_history.json", "hook_history.json", "asset_history.json", "geocode_cache.json",
               "pending_topics.json")   # sujet validé en attente de script (reprise après un échec)
STATE_REPO = os.getenv("HF_STATE_REPO", "soradata/AIShortvideos")
STATE_FOLDER = "meta"
CHANNEL_STATE_FILES = ("global_history.json", "hook_history.json", "pending_topics.json")


@lru_cache(maxsize=None)
def is_isolated(channel: str | None) -> bool:
    """`state.isolated` dans config/channels/<chaîne>.yaml (absent = fichiers partagés historiques)."""
    if not channel:
        return False
    from auracontent.channels.base_channel import load_channel_config

    try:
        return bool((load_channel_config(channel).get("state") or {}).get("isolated"))
    except FileNotFoundError:
        return False


def channel_state_dir(channel: str | None) -> Path | None:
    """Dossier d'état propre à la chaîne, ou None si elle utilise les fichiers partagés."""
    return STATE_DIR / channel if is_isolated(channel) else None


def _targets(names, channels) -> list[tuple[Path, str]]:
    """(fichier local, chemin sur HF). Sans `channels` : les fichiers partagés, comme avant."""
    channels = list(channels or [])
    targets = []
    if not channels or any(not is_isolated(c) for c in channels):
        targets += [(STATE_DIR / n, f"{STATE_FOLDER}/{n}") for n in (names or STATE_FILES)]
    for c in channels:
        if is_isolated(c):
            wanted = [n for n in (names or CHANNEL_STATE_FILES) if n in CHANNEL_STATE_FILES]
            targets += [(STATE_DIR / c / n, f"{STATE_FOLDER}/{c}/{n}") for n in wanted]
    return targets


def _api():
    token = os.getenv("HF_TOKEN")
    if not token:
        print("ℹ️ HF_TOKEN absent : état gardé en local uniquement.")
        return None, None
    from huggingface_hub import HfApi

    return HfApi(token=token), token


def pull_state(channels=None) -> None:
    """`channels` : chaînes de l'exécution (fichiers partagés et/ou dossiers isolés) ; None = partagés."""
    api, token = _api()
    if api is None:
        return
    from huggingface_hub import hf_hub_download

    for local, remote in _targets(None, channels):
        try:
            path = hf_hub_download(repo_id=STATE_REPO, repo_type="dataset", filename=remote, token=token)
            local.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(path, local)
            print(f"📥 État récupéré : {STATE_REPO}/{remote}")
        except Exception as e:
            print(f"ℹ️ {remote} absent sur HF (première exécution ?) : {type(e).__name__}")


def push_state(names: tuple[str, ...] | None = None, channels=None) -> None:
    """`names` : seulement ces fichiers (après un échec : le sujet en attente, jamais les historiques).
    `channels` : chaînes de l'exécution ; None = fichiers partagés (comportement historique)."""
    api, _ = _api()
    if api is None:
        return
    for local, remote in _targets(names, channels):
        if not local.exists():
            continue
        try:
            api.upload_file(
                path_or_fileobj=str(local),
                path_in_repo=remote,
                repo_id=STATE_REPO,
                repo_type="dataset",
                commit_message=f"chore: update {remote.removeprefix(STATE_FOLDER + '/')}",
            )
            print(f"📤 État sauvegardé : {STATE_REPO}/{remote}")
        except Exception as e:
            print(f"⚠️ Sauvegarde de {remote} impossible : {e}")
