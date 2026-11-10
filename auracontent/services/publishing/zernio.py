"""Publication multi-plateformes via l'API Zernio."""
from __future__ import annotations

import os
import subprocess
import tempfile

import requests

ZERNIO_POSTS_URL = "https://zernio.com/api/v1/posts"


def _platform_settings(platform: str, title: str, draft: bool) -> dict:
    if platform == "youtube":
        return {"youtubeSettings": {"title": title, "privacy_status": "PUBLIC"}}
    if platform == "tiktok":
        return {
            "tiktokSettings": {
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "allow_comment": True,
                "allow_duet": False,
                "allow_stitch": False,
                "content_preview_confirmed": True,
                "express_consent_given": True,
                "video_made_with_ai": True,
                "draft": draft,  # brouillon si les serveurs TikTok sont saturés
            }
        }
    return {}


def publish_to_platform(
    platform: str,
    account_id: str,
    video_url: str,
    title: str,
    caption: str,
    api_key: str,
    draft: bool = False,
) -> bool:
    """Publie une vidéo (par URL) sur une plateforme. True si publiée ou doublon."""
    print(f"\n🚀 Publication sur {platform.upper()}{' (brouillon)' if draft else ''}...")
    payload = {
        "content": caption,
        "mediaItems": [{"type": "video", "url": video_url}],
        "platforms": [{"platform": platform, "accountId": account_id}],
        "publishNow": True,
        **_platform_settings(platform, title, draft),
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        response = requests.post(ZERNIO_POSTS_URL, headers=headers, json=payload, timeout=60)
    except requests.exceptions.Timeout:
        print(f"❌ Timeout vers {platform}.")
        return False

    name = platform.capitalize()
    if response.status_code in (200, 201):
        print(f"✅ Publiée sur {name}.")
        return True
    if response.status_code == 409:
        print(f"⚠️ {name} : doublon détecté (considéré comme traité).")
        return True
    if response.status_code == 207:
        print(f"⚠️ {name} (207) : publication partielle ou en file d'attente.\n{response.text}")
        return False
    print(f"❌ Échec sur {name} (code {response.status_code}) : {response.text}")
    return False


def check_audio_loudness(video_url: str, report_path: str = "loudness_report.txt") -> None:
    """Télécharge la vidéo, mesure le loudness (ffmpeg) et écrit un rapport. Non bloquant."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
            tmp_path = tmp_file.name
            with requests.get(video_url, stream=True, timeout=60) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=8192):
                    tmp_file.write(chunk)

        result = subprocess.run(
            ["ffmpeg", "-i", tmp_path, "-af", "loudnorm=print_format=summary", "-f", "null", "-"],
            capture_output=True, text=True, timeout=60,
        )
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(result.stderr)
        for line in result.stderr.splitlines():
            if any(k in line for k in ("Input Integrated", "Input LRA", "Output Integrated")):
                print(f"   {line.strip()}")
    except Exception as e:
        print(f"⚠️ Analyse loudness impossible (non bloquant) : {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


# ---------- Analytics (boucle de feedback) ----------
ZERNIO_ANALYTICS_URL = "https://zernio.com/api/v1/analytics"
_VIEW_ALIASES = ("views", "plays", "videoViews", "impressions")
_LIKE_ALIASES = ("likes", "reactions")
_COMMENT_ALIASES = ("comments",)
_POSTS_ROOT_ALIASES = ("posts", "data", "results", "items")


def _first(d: dict, keys, default=0.0) -> float:
    for k in keys:
        try:
            if d.get(k) is not None:
                return float(d[k])
        except (TypeError, ValueError):
            continue
    return default


def _post_metrics(post: dict, platform: str | None) -> dict:
    """Zernio renvoie soit `analytics` à plat, soit `platforms: {tiktok: {...}, youtube: {...}}`."""
    flat = post.get("analytics")
    if isinstance(flat, dict) and any(k in flat for k in _VIEW_ALIASES + _LIKE_ALIASES):
        sources = [flat]
    else:
        platforms = post.get("platforms") if isinstance(post.get("platforms"), dict) else {}
        sources = [platforms[platform]] if platform in platforms else list(platforms.values())
    sources = [s for s in sources if isinstance(s, dict)]
    return {
        "views": int(sum(_first(s, _VIEW_ALIASES) for s in sources)),
        "likes": int(sum(_first(s, _LIKE_ALIASES) for s in sources)),
        "comments": int(sum(_first(s, _COMMENT_ALIASES) for s in sources)),
    }


def get_latest_videos_stats(
    api_key: str | None, platform: str | None = None, account_id: str | None = None, limit: int = 5
) -> list[dict] | None:
    """Top posts par engagement : [{"title" (texte du post), "views", "likes", "comments"}]. None si indisponible."""
    if not api_key:
        print("ℹ️ Pas de clé Zernio : boucle de feedback désactivée.")
        return None
    params = {"sortBy": "engagement", "limit": limit}
    if platform:
        params["platform"] = platform
    if account_id:
        params["accountId"] = account_id

    try:
        response = requests.get(
            ZERNIO_ANALYTICS_URL, params=params, timeout=15,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        if response.status_code == 403:
            print("❌ Zernio 403 : vérifie que l'add-on Analytics est actif sur ton plan.")
            return None
        if response.status_code == 429:
            print("❌ Zernio 429 : trop de requêtes.")
            return None
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        print(f"⚠️ Stats Zernio indisponibles : {e}")
        return None

    posts = data if isinstance(data, list) else next(
        (data[k] for k in _POSTS_ROOT_ALIASES if isinstance(data, dict) and isinstance(data.get(k), list)), []
    )
    stats = [
        {"title": p.get("content", ""), **_post_metrics(p, platform)} for p in posts if isinstance(p, dict)
    ]
    if not stats or all(s["views"] == 0 and s["likes"] == 0 for s in stats):
        print("⚠️ Aucune statistique Zernio exploitable.")
        return None
    print(f"📊 Stats Zernio : {len(stats)} vidéos analysées.")
    return stats
