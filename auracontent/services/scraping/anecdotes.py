"""Source de sujets : anecdotes de la rubrique « Le saviez-vous ? » de Wikipédia en français.

Chaque anecdote a déjà été proposée, discutée et sourcée par les contributeurs : c'est un fait surprenant,
rattaché à un article (le lien en gras). Accès par l'API MediaWiki, en wikitexte :
- « Wikipédia:Le saviez-vous ?/Anecdotes sur l'accueil »  : les anecdotes du moment ;
- « Wikipédia:Le saviez-vous ?/Archives/<année> »          : toutes celles parues cette année-là (2004-).

Une ligne par anecdote :
    * <!--@ID_23573-->[[Fichier:...]]Texte avec '''[[Article cible|lien en gras]]''' ...
    *:<small>présente 6 jours en page d'accueil ... [[Discussion:Article cible/LSV_23573|...]]</small>

On ne garde que les anecdotes dont l'article cible est un lieu ou un objet situé en France, d'après
Wikidata : pays (P17) = France, ou coordonnées (P625) sur le territoire français.
"""
from __future__ import annotations

import random
import re
import time

import requests
from config.settings import WIKIMEDIA_CONTACT
from constants import WIKI_API_URL, WIKIPEDIA_API_URL

HEADERS = {"User-Agent": f"AuraContentPipeline/2.0 ({WIKIMEDIA_CONTACT}) requests/{requests.__version__}"}
HOME_TITLE = "Wikipédia:Le saviez-vous ?/Anecdotes sur l'accueil"
ARCHIVE_TITLE = "Wikipédia:Le saviez-vous ?/Archives/{year}"
FRANCE_QID = "Q142"
BATCH = 50
DELAY_BETWEEN_CALLS = 0.3
REQUEST_TIMEOUT = 30

ID_RE = re.compile(r"<!--\s*@ID_(\d+)\s*-->")
BOLD_LINK_RE = re.compile(r"'''\s*\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
DISCUSSION_RE = re.compile(r"\[\[Discussion:([^\]/|]+)/LSV")
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
FILE_RE = re.compile(r"\[\[(?:Fichier|File|Image):(?:[^\[\]]|\[\[[^\]]*\]\])*\]\]", re.IGNORECASE)
LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")


def _get(url: str, params: dict) -> dict | None:
    time.sleep(DELAY_BETWEEN_CALLS)
    try:
        r = requests.get(url, params={"format": "json", "formatversion": 2, **params}, headers=HEADERS,
                         timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"⚠️ « Le saviez-vous ? » indisponible : {e}")
        return None


def fetch_wikitext(title: str) -> str:
    data = _get(WIKIPEDIA_API_URL, {"action": "query", "prop": "revisions", "rvprop": "content",
                                     "rvslots": "main", "titles": title})
    pages = (data or {}).get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return ""
    return ((pages[0].get("revisions") or [{}])[0].get("slots", {}).get("main", {}) or {}).get("content", "")


def _template_text(match: re.Match) -> str:
    """{{Unité|2|km}} -> « 2 km », {{date|11 novembre 1918}} -> « 11 novembre 1918 », {{Napoléon Ier}} -> « Napoléon Ier »."""
    parts = [p.strip() for p in match.group(1).split("|")]
    name, args = parts[0], [p for p in parts[1:] if "=" not in p]
    if name.lower() in ("s", "sp", "siècle", "s-", "-s") and args:          # {{s|XX}} -> « XXe siècle »
        return f"{args[0]}e siècle"
    if name.lower() in ("unité", "unite", "nombre", "date", "noble", "lang", "langue", "citation", "nobr"):
        return " ".join(args[-2:] if name.lower() == "lang" else args)
    return " ".join(args) if args else name


def plain_text(wikitext: str) -> str:
    text = COMMENT_RE.sub("", wikitext)
    text = FILE_RE.sub("", text)
    for _ in range(3):                                   # modèles imbriqués
        text = TEMPLATE_RE.sub(_template_text, text)
    text = LINK_RE.sub(lambda m: m.group(1), text)
    text = re.sub(r"'{2,}", "", text)
    text = re.sub(r"\((?:illustration|photo[^)]*|tableau|buste|portrait|carte|image|dessin|gravure|plan|statue|schéma)\)", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = " ".join(text.replace("’", "'").split())
    return re.sub(r"\s+([.,;:!?)])", r"\1", text).strip(" *")


ARTICLE_LINK_RE = re.compile(r"\[\[([^\]|#:]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def _illustration(line: str) -> tuple[str | None, str]:
    """(fichier, légende) de l'illustration de l'anecdote : « [[Fichier:X.JPG|40px|droite|Légende]] »."""
    match = FILE_RE.search(COMMENT_RE.sub("", line))
    if not match:
        return None, ""
    inner = match.group(0)[2:-2]
    name = inner.split("|", 1)[0].split(":", 1)[1].strip()
    params = re.split(r"\|(?![^\[]*\]\])", inner)[1:]
    caption = next((p for p in reversed(params) if p.strip() and not re.fullmatch(
        r"\s*(\d+px|droite|gauche|centre|right|left|center|vignette|thumb|upright[=0-9.]*|alt=.*|lien=.*)\s*", p)), "")
    return name or None, plain_text(caption)


def parse_anecdotes(wikitext: str) -> list[dict]:
    """[{id, text, target, links, file, caption}] : une entrée par anecdote, avec l'article cible (lien en
    gras), les autres articles qu'elle cite, et son illustration (fichier Commons et légende)."""
    anecdotes, lines = [], wikitext.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("*") or line.startswith("*:"):
            continue
        id_match = ID_RE.search(line)
        body = FILE_RE.sub("", COMMENT_RE.sub("", line))
        target = BOLD_LINK_RE.search(body)
        target = target.group(1).strip() if target else None
        if not target and i + 1 < len(lines):            # sinon : la page de discussion de la proposition
            disc = DISCUSSION_RE.search(lines[i + 1])
            target = disc.group(1).strip() if disc else None
        text = plain_text(line)
        if target and text:
            target = target.replace("_", " ")
            links = []
            for m in ARTICLE_LINK_RE.finditer(body):
                link = m.group(1).replace("_", " ").strip()
                if link and link.lower() != target.lower() and link not in links:
                    links.append(link)
            file, caption = _illustration(line)
            anecdotes.append({"id": id_match.group(1) if id_match else f"{target}:{text[:40]}",
                              "text": text, "target": target, "links": links, "file": file,
                              "caption": caption})
    return anecdotes


def _wikibase_items(titles: list[str]) -> dict[str, tuple[str, str]]:
    """Titre cité -> (titre canonique après redirection, identifiant Wikidata)."""
    out = {}
    for i in range(0, len(titles), BATCH):
        chunk = titles[i:i + BATCH]
        data = _get(WIKIPEDIA_API_URL, {"action": "query", "prop": "pageprops", "ppprop": "wikibase_item",
                                         "redirects": 1, "titles": "|".join(chunk)})
        query = (data or {}).get("query", {})
        renamed = {}
        for key in ("normalized", "redirects"):
            for m in query.get(key, []):
                renamed[m["from"]] = m["to"]
        by_title = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in query.get("pages", [])
                    if not p.get("missing")}
        for title in chunk:
            final = title
            for _ in range(3):
                final = renamed.get(final, final)
            if by_title.get(final):
                out[title] = (final, by_title[final])
    return out


LOCAL_PROPS = ("P131", "P276", "P195")   # entité administrative, lieu, collection : un lieu ou un objet situé


def _values(claims: dict, prop: str) -> list:
    return [c.get("mainsnak", {}).get("datavalue", {}).get("value") for c in claims.get(prop, [])
            if c.get("rank") != "deprecated"]


def _in_france(claims: dict, is_french_point) -> bool:
    """Lieu ou objet situé en France : coordonnées sur le territoire, ou pays France ET rattachement local
    (commune, lieu, collection). Écarte les personnes, organisations, journaux et colonies lointaines."""
    points = [v for v in _values(claims, "P625") if isinstance(v, dict) and v.get("latitude") is not None]
    if points:
        return any(is_french_point(v["latitude"], v["longitude"]) for v in points)
    french = any(isinstance(v, dict) and v.get("id") == FRANCE_QID for v in _values(claims, "P17"))
    return french and any(claims.get(prop) for prop in LOCAL_PROPS)


def located_in_france(qids: list[str], is_french_point=None) -> dict[str, dict | None]:
    """Éléments Wikidata situés en France -> leurs coordonnées (P625) {lat, lon}, ou None s'il n'en a pas."""
    if is_french_point is None:
        from auracontent.services.visuals.map_scene import find_region

        def is_french_point(lat, lon):
            return find_region(lat, lon, max_km=5) is not None
    keep: dict[str, dict | None] = {}
    for i in range(0, len(qids), BATCH):
        chunk = qids[i:i + BATCH]
        data = _get(WIKI_API_URL, {"action": "wbgetentities", "ids": "|".join(chunk), "props": "claims"})
        for qid, entity in ((data or {}).get("entities") or {}).items():
            claims = entity.get("claims") or {}
            if _in_france(claims, is_french_point):
                point = next((v for v in _values(claims, "P625") if isinstance(v, dict) and v.get("latitude") is not None),
                             None)
                keep[qid] = {"lat": point["latitude"], "lon": point["longitude"]} if point else None
    return keep


def collect_french_anecdotes(years: list[int], archives: int = 2, include_home: bool = True, sample: int = 120,
                             exclude_ids: set[str] | None = None, exclude_titles: set[str] | None = None,
                             rng: random.Random | None = None) -> list[dict]:
    """Anecdotes inédites sur un lieu ou un objet situé en France, dans un ordre aléatoire.

    Lit la page d'accueil et `archives` années tirées au hasard dans `years`, écarte les anecdotes et les
    articles déjà traités, puis interroge Wikidata pour `sample` anecdotes au plus (lots de 50).
    Retour : [{id, text, target (titre canonique), wikibase_item}]. Liste vide si Wikipédia est injoignable.
    """
    rng = rng or random.Random()
    exclude_ids, exclude_titles = exclude_ids or set(), {t.lower() for t in exclude_titles or set()}
    titles = [HOME_TITLE] if include_home else []
    years = list(years)
    titles += [ARCHIVE_TITLE.format(year=y) for y in rng.sample(years, min(archives, len(years)))]
    pool = []
    for title in titles:
        found = parse_anecdotes(fetch_wikitext(title))
        print(f"   📚 {title} : {len(found)} anecdote(s)")
        pool += found
    seen, fresh = set(), []
    for a in pool:
        if a["id"] in exclude_ids or a["target"].lower() in exclude_titles or a["target"].lower() in seen:
            continue
        seen.add(a["target"].lower())
        fresh.append(a)
    rng.shuffle(fresh)
    fresh = fresh[:sample]
    items = _wikibase_items([a["target"] for a in fresh])
    qids = sorted({qid for _, qid in items.values()})
    french = located_in_france(qids) if qids else {}
    kept = []
    for a in fresh:
        canonical, qid = items.get(a["target"], (None, None))
        if qid in french and canonical.lower() not in exclude_titles:
            coords = french.get(qid) if isinstance(french, dict) else None
            kept.append({**a, "target": canonical, "wikibase_item": qid, "coordinates": coords})
    print(f"   📚 « Le saviez-vous ? » : {len(kept)} anecdote(s) inédite(s) située(s) en France "
          f"sur {len(fresh)} examinée(s)")
    return kept
