"""Stockage des vidéos sur un dataset Hugging Face.

Le générateur y dépose `<dossier>/<YYYYMMDD_HHMMSS>_<sujet>.mp4` (+ `.txt` pour la légende),
le publisher y récupère la vidéo du jour et transmet son URL publique à Zernio.

Upload manuel / depuis la CI :
    python -m auracontent.services.publishing.hf_storage mystery output/final_video.mp4 "Sujet" [caption.txt]
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from huggingface_hub import HfApi

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
TIMESTAMP_LENGTH = len("YYYYMMDD_HHMMSS_")


@dataclass
class StoredVideo:
    path_in_repo: str
    url: str
    caption_url: str

    @property
    def title(self) -> str:
        """`20261110_183000_Le_tresor_perdu.mp4` -> `Le tresor perdu`."""
        filename = self.path_in_repo.rsplit("/", 1)[-1]
        return filename.removesuffix(".mp4")[TIMESTAMP_LENGTH:].replace("_", " ")

    @property
    def date(self) -> str:
        return self.path_in_repo.rsplit("/", 1)[-1][:8]


def _direct_url(repo_id: str, path_in_repo: str) -> str:
    return f"https://huggingface.co/datasets/{repo_id}/resolve/main/{path_in_repo}"


def upload_video(
    video_path: str,
    topic: str,
    repo_id: str,
    folder: str,
    caption: str | None = None,
) -> str:
    """Envoie la vidéo (et sa légende) sur le dataset. Retourne le chemin dans le dépôt."""
    token = os.getenv("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN manquant : upload Hugging Face impossible.")
    if not os.path.exists(video_path):
        raise FileNotFoundError(video_path)

    api = HfApi(token=token)
    timestamp = datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)
    safe_topic = "".join(c if c.isalnum() else "_" for c in topic)[:50] or "video"
    path_in_repo = f"{folder}/{timestamp}_{safe_topic}.mp4"

    _upload_with_retry(api, video_path, path_in_repo, repo_id, f"Add generated short: {safe_topic}")
    print(f"✅ Vidéo uploadée sur Hugging Face : {repo_id}/{path_in_repo}")
    if caption:
        caption_path = path_in_repo.removesuffix(".mp4") + ".txt"
        _upload_with_retry(api, caption.encode("utf-8"), caption_path, repo_id, f"Add caption for: {safe_topic}")
        print(f"✅ Légende uploadée : {repo_id}/{caption_path}")
    return path_in_repo


def _upload_with_retry(api: HfApi, content, path_in_repo: str, repo_id: str, message: str, max_retries: int = 5):
    """Upload avec backoff exponentiel sur les 429 (rate limit Hugging Face)."""
    for attempt in range(1, max_retries + 1):
        try:
            api.upload_file(
                path_or_fileobj=content,
                path_in_repo=path_in_repo,
                repo_id=repo_id,
                repo_type="dataset",
                commit_message=message,
            )
            return
        except Exception as e:
            if "429" in str(e) and attempt < max_retries:
                wait_s = min(2**attempt, 20)
                print(f"⏳ Rate limit HF (tentative {attempt}/{max_retries}), nouvel essai dans {wait_s}s...")
                time.sleep(wait_s)
                continue
            raise


def get_latest_video(repo_id: str, folder: str, require_today: bool = True) -> StoredVideo:
    """Dernière vidéo du dossier. Refuse une vidéo qui n'est pas du jour (générateur en échec)."""
    api = HfApi(token=os.getenv("HF_TOKEN"))
    files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
    videos = sorted(f for f in files if f.startswith(f"{folder}/") and f.endswith(".mp4"))
    if not videos:
        raise RuntimeError(f"❌ Aucune vidéo dans {repo_id}/{folder}.")

    latest = videos[-1]
    video = StoredVideo(
        path_in_repo=latest,
        url=_direct_url(repo_id, latest),
        caption_url=_direct_url(repo_id, latest.removesuffix(".mp4") + ".txt"),
    )

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if require_today and video.date != today:
        raise RuntimeError(
            f"🛑 La dernière vidéo date du {video.date}, nous sommes le {today}. "
            "Le générateur a probablement échoué : publication annulée."
        )
    print(f"🎯 Vidéo du jour : {latest}")
    return video


if __name__ == "__main__":
    from auracontent.channels.base_channel import load_channel_config

    if len(sys.argv) < 4:
        sys.exit(__doc__)
    channel, video, topic = sys.argv[1:4]
    caption_text = None
    if len(sys.argv) > 4 and os.path.exists(sys.argv[4]):
        with open(sys.argv[4], encoding="utf-8") as f:
            caption_text = f.read().strip()

    cfg = load_channel_config(channel).get("publish", {})
    upload_video(video, topic, cfg["hf_repo"], cfg.get("hf_folder", channel), caption_text)
