"""Téléchargement des archives d'un épisode depuis Wikimedia Commons, avec licence et auteur.

plan.json : "images": {"<clé>": "File:Nom du fichier.jpg", ...}
Sortie    : img/<clé>.jpg (1920 px de large au plus) et img/credits.json (titre, auteur, licence, page).
Seules les licences libres sont acceptées (domaine public, CC0, CC BY, CC BY-SA).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import requests

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": f"AuraContent-archive/1.0 ({os.getenv('WIKIMEDIA_CONTACT', 'contact non configuré')})"}
FREE = re.compile(r"public domain|domaine public|^pd|cc0|cc[- ]by|attribution", re.I)
WIDTH = 1920


def _strip(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html or "").strip()


def info(titles: list[str]) -> dict[str, dict]:
    out = {}
    for i in range(0, len(titles), 40):
        r = requests.get(API, headers=UA, timeout=60, params={
            "action": "query", "format": "json", "prop": "imageinfo", "titles": "|".join(titles[i:i + 40]),
            "iiprop": "url|extmetadata|size", "iiurlwidth": WIDTH})
        r.raise_for_status()
        q = r.json()["query"]
        norm = {n["to"]: n["from"] for n in q.get("normalized", [])}
        for p in q["pages"].values():
            if "imageinfo" not in p:
                continue
            ii = p["imageinfo"][0]; md = ii.get("extmetadata", {})
            out[norm.get(p["title"], p["title"])] = {
                "url": ii.get("thumburl") or ii["url"], "page": ii.get("descriptionurl"),
                "width": ii.get("width"), "height": ii.get("height"),
                "license": _strip(md.get("LicenseShortName", {}).get("value", "")),
                "author": re.sub(r"^(.+?)\1$", r"\1", _strip(md.get("Artist", {}).get("value", "")))[:120]}
    return out


def direct_url(title: str) -> str:
    """URL du fichier sans passer par l'API (repli quand l'API refuse : 429)."""
    name = title.split(":", 1)[1].replace(" ", "_")
    h = hashlib.md5(name.encode()).hexdigest()
    q = urllib.parse.quote(name)
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/{WIDTH}px-{q}"


def original_url(title: str) -> str:
    name = title.split(":", 1)[1].replace(" ", "_")
    h = hashlib.md5(name.encode()).hexdigest()
    return f"https://upload.wikimedia.org/wikipedia/commons/{h[0]}/{h[:2]}/{urllib.parse.quote(name)}"


def fetch(episode: Path) -> dict:
    plan = json.loads((episode / "plan.json").read_text(encoding="utf-8"))
    wanted = {k: (v if v.startswith("File:") else "File:" + v) for k, v in plan.get("images", {}).items()}
    out = episode / "img"; out.mkdir(exist_ok=True)
    try:
        meta = info(list(wanted.values()))
    except requests.RequestException as e:
        print(f"   API Commons indisponible ({e}) : téléchargement direct, licences non vérifiées")
        meta = {}
    old = out / "credits.json"
    credits = json.loads(old.read_text(encoding="utf-8")) if old.exists() else {}
    missing = []
    for key, title in wanted.items():
        path = out / f"{key}.jpg"
        m = meta.get(title, {})
        if m and not FREE.search(m.get("license", "")):
            missing.append(f"{key} ({title}) : licence « {m.get('license')} » non libre")
            continue
        if not path.exists():
            for url in [u for u in (m.get("url"), direct_url(title), original_url(title)) if u]:
                try:
                    r = requests.get(url, headers=UA, timeout=120)
                except requests.RequestException as e:
                    print(f"   {key} : {type(e).__name__} sur {url.split('/')[2]}, adresse suivante")
                    continue
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                    _save_jpeg(r.content, path)
                    break
                print(f"   {key} : HTTP {r.status_code} sur {url.split('/')[2]}")
                time.sleep(1)
        if not path.exists():
            missing.append(f"{key} ({title}) : téléchargement impossible")
            continue
        if m or key not in credits:
            credits[key] = {"title": title, **{k: m.get(k) for k in ("author", "license", "page")}}
    (out / "credits.json").write_text(json.dumps(credits, ensure_ascii=False, indent=1), encoding="utf-8")
    for line in missing:
        print("   ⚠️ " + line)
    print(f"   archives : {len(credits)}/{len(wanted)} images")
    if missing:
        raise RuntimeError("archives manquantes : " + "; ".join(missing))
    return credits


def _save_jpeg(data: bytes, path: Path) -> None:
    import io

    from PIL import Image
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.width > WIDTH:
        im = im.resize((WIDTH, int(im.height * WIDTH / im.width)), Image.LANCZOS)
    im.save(path, quality=92)
