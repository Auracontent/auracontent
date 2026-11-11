"""Publie la vidéo du jour d'une chaîne via Zernio. À lancer depuis la racine du dépôt :

    python -m auracontent.cli.publish mystery
    python -m auracontent.cli.publish mystery finance

Tout est configuré dans la section `publish:` de config/channels/<chaîne>.yaml.
Seuls les NOMS des variables d'environnement y figurent ; les valeurs viennent
des Secrets GitHub, de Vault (Onyxia) ou du .env.
"""
import argparse
import os
import sys
import time

import requests
from dotenv import load_dotenv

from auracontent.channels.base_channel import load_channel_config
from auracontent.services.publishing.caption import apply_hashtag_rules
from auracontent.services.publishing.hf_storage import get_latest_video
from auracontent.services.publishing.zernio import check_audio_loudness, publish_to_platform


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"❌ Variable d'environnement manquante : {name}")
    return value


def _fetch_caption(caption_url: str, fallback: str) -> str:
    try:
        r = requests.get(caption_url, timeout=15)
        if r.status_code == 200 and r.text.strip():
            print("✅ Légende IA récupérée depuis Hugging Face.")
            return r.text.strip()
        print(f"⚠️ Légende introuvable sur HF (code {r.status_code}), légende de secours.")
    except requests.RequestException as e:
        print(f"⚠️ Téléchargement de la légende impossible ({e}), légende de secours.")
    return fallback


def publish_channel(channel: str) -> bool:
    cfg = load_channel_config(channel).get("publish")
    if not cfg:
        print(f"⏭️ {channel} : pas de section `publish` dans le YAML, ignorée.")
        return True

    print(f"\n📣 Publication de la chaîne : {channel.upper()}")
    video = get_latest_video(cfg["hf_repo"], cfg.get("hf_folder", channel))
    check_audio_loudness(video.url, report_path=f"loudness_report_{channel}.txt")

    api_key = _require_env(cfg["zernio_key_env"])
    platforms = [(p["platform"], _require_env(p["account_env"])) for p in cfg["platforms"]]
    caption = _fetch_caption(video.caption_url, f"{video.title} {cfg.get('fallback_hashtags', '')}".strip())
    # légende générée avant le changement de nom : on retire l'ancien hashtag au moment de publier
    caption = apply_hashtag_rules(caption, cfg.get("brand_hashtag"), cfg.get("banned_hashtags", ()))
    print(f"📝 Légende :\n{caption}")

    delay = cfg.get("delay_between_platforms", 15)
    all_ok = True
    for i, (platform, account_id) in enumerate(platforms):
        if i:
            print(f"⏳ Pause de {delay}s...")
            time.sleep(delay)
        ok = publish_to_platform(platform, account_id, video.url, video.title, caption, api_key)
        if not ok and platform == "tiktok":
            time.sleep(10)
            ok = publish_to_platform(platform, account_id, video.url, video.title, caption, api_key, draft=True)
        all_ok &= ok

    print(f"\n🏁 {channel} : publication terminée.")
    return all_ok


def main(argv: list[str]) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Publie la vidéo du jour via Zernio")
    parser.add_argument("channels", nargs="+", help="chaînes à publier (ex : mystery)")
    args = parser.parse_args(argv)
    results = {}
    for channel in args.channels:
        try:
            results[channel] = publish_channel(channel)
        except Exception as e:
            print(f"❌ {channel} : {e}")
            results[channel] = False
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
