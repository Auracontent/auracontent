"""Synchronise l'état (historiques) entre assets/shared/state/ et le dataset Hugging Face.

Les runners GitHub Actions sont éphémères : sans ça, l'anti-doublon de sujets et le
bandit des hooks repartiraient de zéro à chaque exécution.

    pull_state()  # début de run : HF meta/*.json -> assets/shared/state/
    push_state()  # fin de run   : assets/shared/state/*.json -> HF meta/
"""
from __future__ import annotations

import os
import shutil

from config.settings import ASSETS_DIR

STATE_DIR = ASSETS_DIR / "shared" / "state"
STATE_FILES = ("global_history.json", "hook_history.json", "asset_history.json", "geocode_cache.json",
               "pending_topics.json")   # sujet validé en attente de script (reprise après un échec)
STATE_REPO = os.getenv("HF_STATE_REPO", "soradata/AIShortvideos")
STATE_FOLDER = "meta"


def _api():
    token = os.getenv("HF_TOKEN")
    if not token:
        print("ℹ️ HF_TOKEN absent : état gardé en local uniquement.")
        return None, None
    from huggingface_hub import HfApi

    return HfApi(token=token), token


def pull_state() -> None:
    api, token = _api()
    if api is None:
        return
    from huggingface_hub import hf_hub_download

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    for name in STATE_FILES:
        try:
            path = hf_hub_download(
                repo_id=STATE_REPO, repo_type="dataset", filename=f"{STATE_FOLDER}/{name}", token=token
            )
            shutil.copy(path, STATE_DIR / name)
            print(f"📥 État récupéré : {STATE_REPO}/{STATE_FOLDER}/{name}")
        except Exception as e:
            print(f"ℹ️ {name} absent sur HF (première exécution ?) : {type(e).__name__}")


def push_state(names: tuple[str, ...] | None = None) -> None:
    """`names` : seulement ces fichiers (après un échec : le sujet en attente, jamais les historiques)."""
    api, _ = _api()
    if api is None:
        return
    for name in names or STATE_FILES:
        local = STATE_DIR / name
        if not local.exists():
            continue
        try:
            api.upload_file(
                path_or_fileobj=str(local),
                path_in_repo=f"{STATE_FOLDER}/{name}",
                repo_id=STATE_REPO,
                repo_type="dataset",
                commit_message=f"chore: update {name}",
            )
            print(f"📤 État sauvegardé : {STATE_REPO}/{STATE_FOLDER}/{name}")
        except Exception as e:
            print(f"⚠️ Sauvegarde de {name} impossible : {e}")
