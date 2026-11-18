"""Tendances YouTube Shorts d'une niche, pour inspirer les sujets (jamais pour copier).

Service partagé : chaque chaîne le configure dans son YAML (section `trends`) avec ses mots-clés, sa langue, son
pays et la consigne d'usage propre à sa ligne éditoriale. Sans clé `YOUTUBE_API_KEY`, sans section `trends`, avec
`enabled: false` ou en cas d'erreur de l'API, il renvoie une liste vide : la chaîne fonctionne comme avant.

Méthode (API YouTube Data v3, gratuite) :
1. search.list : vidéos courtes récentes par mot-clé (100 unités de quota par mot-clé) ;
2. videos.list + channels.list : vues de chaque vidéo et abonnés de sa chaîne (1 unité par lot de 50) ;
3. score de surperformance = vues / max(abonnés, plancher) : une vidéo qui dépasse largement la taille de sa
   chaîne montre un sujet qui a plu au public, pas seulement une grosse audience déjà acquise ;
4. une à deux vidéos par chaîne au plus, les meilleures d'abord.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import requests

API = "https://www.googleapis.com/youtube/v3"
DEFAULTS = {
    "enabled": True,
    "queries": [],
    "language": "fr",
    "region": "FR",
    "max_age_days": 30,
    "max_duration_s": 90,        # Shorts
    "per_query": 25,
    "max_queries": 6,            # 6 x 100 unités : bien sous le quota gratuit quotidien (10 000)
    "min_views": 5000,
    "subscriber_floor": 1000,
    "per_channel": 1,
    "top": 8,
    "usage": "",
}
_CACHE: dict[tuple, list] = {}   # une seule interrogation par run et par configuration


@dataclass
class TrendVideo:
    title: str
    channel: str
    views: int
    subscribers: int
    published: str
    video_id: str
    score: float

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/shorts/{self.video_id}"


def settings(cfg: dict | None) -> dict:
    return {**DEFAULTS, **(cfg or {})}


def _duration_s(iso: str) -> int:
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def _get(session, path: str, params: dict) -> dict:
    r = session.get(f"{API}/{path}", params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch(cfg: dict | None, api_key: str | None = None, session=None, now: datetime | None = None) -> list[TrendVideo]:
    """Vidéos qui surperforment sur la niche, les meilleures d'abord ; [] si désactivé, sans clé ou en erreur."""
    s = settings(cfg)
    key = api_key if api_key is not None else os.environ.get("YOUTUBE_API_KEY", "")
    queries = [q for q in s["queries"] if str(q).strip()][: int(s["max_queries"])]
    if not s["enabled"] or not key or not queries:
        return []
    cache_key = (tuple(queries), s["language"], s["region"], s["max_age_days"])
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    session = session or requests.Session()
    now = now or datetime.now(UTC)
    after = (now - timedelta(days=int(s["max_age_days"]))).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        ids: list[str] = []
        for q in queries:
            data = _get(session, "search", {"part": "snippet", "q": q, "type": "video", "videoDuration": "short",
                                            "order": "viewCount", "publishedAfter": after,
                                            "relevanceLanguage": s["language"], "regionCode": s["region"],
                                            "maxResults": int(s["per_query"]), "key": key})
            ids += [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]
        ids = list(dict.fromkeys(ids))
        videos = []
        for i in range(0, len(ids), 50):
            data = _get(session, "videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50]),
                                            "key": key})
            videos += data.get("items", [])
        chan_ids = list(dict.fromkeys(v["snippet"]["channelId"] for v in videos))
        subs: dict[str, int] = {}
        for i in range(0, len(chan_ids), 50):
            data = _get(session, "channels", {"part": "statistics", "id": ",".join(chan_ids[i:i + 50]), "key": key})
            for c in data.get("items", []):
                st = c.get("statistics", {})
                subs[c["id"]] = 0 if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0) or 0)
    except Exception as e:  # noqa: BLE001 — l'inspiration ne doit jamais bloquer une génération
        print(f"⚠️ Tendances YouTube indisponibles ({str(e)[:160]}) : génération sans inspiration externe.")
        _CACHE[cache_key] = []
        return []
    out = []
    for v in videos:
        views = int(v.get("statistics", {}).get("viewCount", 0) or 0)
        if views < int(s["min_views"]):
            continue
        if _duration_s(v.get("contentDetails", {}).get("duration", "")) > int(s["max_duration_s"]):
            continue
        sn = v["snippet"]
        n_subs = subs.get(sn["channelId"], 0)
        score = views / max(n_subs, int(s["subscriber_floor"]))
        out.append(TrendVideo(sn.get("title", "").strip(), sn.get("channelTitle", ""), views, n_subs,
                              sn.get("publishedAt", "")[:10], v["id"], round(score, 1)))
    out.sort(key=lambda t: (-t.score, -t.views))
    kept, per_chan = [], {}
    for t in out:
        if per_chan.get(t.channel, 0) >= int(s["per_channel"]):
            continue
        per_chan[t.channel] = per_chan.get(t.channel, 0) + 1
        kept.append(t)
        if len(kept) >= int(s["top"]):
            break
    _CACHE[cache_key] = kept
    print(f"📈 Tendances YouTube : {len(kept)} vidéo(s) retenue(s) sur {len(videos)} analysée(s) "
          f"({len(queries)} mot(s)-clé(s)).")
    for t in kept:
        print(f"   • « {t.title[:80]} » — {_fmt(t.views)} vues, x{t.score:g} la taille de sa chaîne")
    return kept


def _fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} M".replace(".", ",")
    if n >= 1000:
        return f"{n / 1000:.0f} k"
    return str(n)


def block(videos: list[TrendVideo], cfg: dict | None = None) -> str:
    """Bloc de prompt : thèmes qui marchent, avec la consigne d'usage de la chaîne. Vide s'il n'y a rien."""
    if not videos:
        return ""
    s = settings(cfg)
    lines = [f"- « {t.title} » ({_fmt(t.views)} vues, x{t.score:g} la taille de sa chaîne)" for t in videos]
    head = ("CE QUI MARCHE EN CE MOMENT sur YouTube Shorts dans ta niche (vidéos récentes qui dépassent largement "
            "la taille de leur chaîne). Inspire-toi des THÈMES et des ANGLES qui plaisent ; ne copie jamais un "
            "titre, une formule ni un chiffre de ces vidéos.")
    usage = str(s.get("usage") or "").strip()
    return "\n".join([head, *lines] + ([usage] if usage else []))


def trends_block(cfg: dict | None, api_key: str | None = None, session=None) -> str:
    """Raccourci : interroge (une fois par run) et renvoie le bloc de prompt, ou « » ."""
    return block(fetch(cfg, api_key, session), cfg)
