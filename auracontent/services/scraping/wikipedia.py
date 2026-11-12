"""Recherche de pages Wikipédia (FR) utilisables comme source d'un script."""
import os
import time

import requests

from constants import WIKI_API_URL, WIKIPEDIA_API_URL

HEADERS = {"User-Agent": os.getenv("WIKIMEDIA_CONTACT", "auraContentPipeline/1.0 (contact non configure)")}
MIN_EXTRACT_CHARS = 1500     # en dessous, pas assez de matière pour 11 scènes
MAX_EXTRACT_CHARS = 60000    # au-dessus : article généraliste (ville, région, pays), pas un sujet précis
DELAY_BETWEEN_CALLS = 0.3
DEPARTMENT_TYPES = {"Q6465", "Q202216"}   # département français, département et région d'outre-mer
COMMUNE_TYPES = {"Q484170", "Q2989454", "Q22927616"}   # commune de France, commune nouvelle, commune déléguée
MAX_ADMIN_LEVELS = 4                      # commune -> canton -> arrondissement -> département


def _get(params: dict, retries: int = 2) -> dict | None:
    params = {"format": "json", "formatversion": 2, **params}
    for attempt in range(retries + 1):
        time.sleep(DELAY_BETWEEN_CALLS)
        try:
            r = requests.get(WIKIPEDIA_API_URL, params=params, headers=HEADERS, timeout=15)
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == retries:
                print(f"⚠️ Wikipédia indisponible : {e}")
                return None
            time.sleep(2)
    return None


def _search_titles(query: str, limit: int) -> list[str]:
    data = _get({"action": "query", "list": "search", "srsearch": query,
                 "srlimit": limit, "srnamespace": 0})
    if not data:
        return []
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def _coordinates(page: dict) -> dict | None:
    """Coordonnées principales de la page (prop=coordinates), sur Terre uniquement."""
    for c in page.get("coordinates") or []:
        if c.get("globe", "earth") != "earth":
            continue
        try:
            lat, lon = float(c["lat"]), float(c["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return {"lat": lat, "lon": lon}
    return None


def _fetch_page(title: str) -> dict | None:
    data = _get({"action": "query", "prop": "extracts|info|pageprops|coordinates", "titles": title,
                 "explaintext": 1, "inprop": "url", "redirects": 1})
    pages = (data or {}).get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    page = pages[0]
    if "disambiguation" in page.get("pageprops", {}):
        return None
    extract = (page.get("extract") or "").strip()
    if not MIN_EXTRACT_CHARS <= len(extract) <= MAX_EXTRACT_CHARS:
        return None
    return {"title": page["title"], "url": page.get("fullurl", ""), "extract": extract,
            "coordinates": _coordinates(page), "wikibase_item": page.get("pageprops", {}).get("wikibase_item")}


def _wikidata(params: dict) -> dict | None:
    time.sleep(DELAY_BETWEEN_CALLS)
    try:
        r = requests.get(WIKI_API_URL, params={"format": "json", **params}, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"⚠️ Wikidata indisponible : {e}")
        return None


def _claim_value(claims: dict, prop: str):
    """Valeur du premier énoncé de rang « preferred », sinon « normal » (les « deprecated » sont ignorés)."""
    statements = [c for c in claims.get(prop, []) if c.get("rank") != "deprecated"]
    statements.sort(key=lambda c: c.get("rank") != "preferred")
    for c in statements:
        value = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if value:
            return value
    return None


def _kinds(claims: dict) -> set:
    """Natures de l'élément (P31)."""
    return {(c.get("mainsnak", {}).get("datavalue", {}).get("value") or {}).get("id")
            for c in claims.get("P31", [])}


def place_details(wikibase_item: str | None) -> dict:
    """Commune (P131), département (P131 de la commune) et catégorie Commons (P373), d'après Wikidata.

    Six requêtes au plus ; {} si l'élément est inconnu ou Wikidata indisponible (jamais bloquant).
    """
    if not wikibase_item:
        return {}
    data = _wikidata({"action": "wbgetentities", "ids": wikibase_item, "props": "labels|claims", "languages": "fr"})
    entity = (data or {}).get("entities", {}).get(wikibase_item) or {}
    claims = entity.get("claims") or {}
    details = {}
    category = _claim_value(claims, "P373")
    if isinstance(category, str) and category.strip():
        details["commons_category"] = category.strip()
    if _kinds(claims) & COMMUNE_TYPES:
        # l'article EST la commune (anecdote sur un objet de la commune) : son P131 est le canton, pas elle
        label = entity.get("labels", {}).get("fr", {}).get("value")
        if label:
            details["commune"] = label
        commune = entity
    else:
        admin = _claim_value(claims, "P131")
        commune_id = admin.get("id") if isinstance(admin, dict) else None
        if not commune_id:
            return details
        data = _wikidata({"action": "wbgetentities", "ids": commune_id, "props": "labels|claims", "languages": "fr"})
        commune = (data or {}).get("entities", {}).get(commune_id) or {}
    label = commune.get("labels", {}).get("fr", {}).get("value")
    if label:
        details.setdefault("commune", label)
    # département : on remonte les entités qui contiennent la commune (canton, arrondissement...)
    parent = _claim_value(commune.get("claims") or {}, "P131")
    for _ in range(MAX_ADMIN_LEVELS):
        parent_id = parent.get("id") if isinstance(parent, dict) else None
        if not parent_id:
            break
        data = _wikidata({"action": "wbgetentities", "ids": parent_id, "props": "labels|claims", "languages": "fr"})
        entity = (data or {}).get("entities", {}).get(parent_id) or {}
        if _kinds(entity.get("claims") or {}) & DEPARTMENT_TYPES:
            label = entity.get("labels", {}).get("fr", {}).get("value")
            if label:
                details["department"] = label
            break
        parent = _claim_value(entity.get("claims") or {}, "P131")
    return details


def fetch_intro(title: str, max_chars: int = 2000) -> dict | None:
    """Résumé introductif d'un article (sans seuil de longueur) : {"title", "url", "extract"} ou None.

    Sert aux articles cités par une anecdote « Le saviez-vous ? », qui complètent la source du script."""
    data = _get({"action": "query", "prop": "extracts|info|pageprops", "titles": title, "explaintext": 1,
                 "exintro": 1, "inprop": "url", "redirects": 1})
    pages = (data or {}).get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing") or "disambiguation" in pages[0].get("pageprops", {}):
        return None
    extract = (pages[0].get("extract") or "").strip()
    if not extract:
        return None
    return {"title": pages[0]["title"], "url": pages[0].get("fullurl", ""), "extract": extract[:max_chars]}


def fetch_page(title: str) -> dict | None:
    """Page exploitable (assez de matière, pas d'homonymie) ou None. Voir find_candidates."""
    return _fetch_page(title)


def find_candidates(query: str, limit: int = 8, exclude: set[str] | None = None) -> list[dict]:
    """Pages exploitables pour `query` : [{"title", "url", "extract", "coordinates", "wikibase_item"}].

    `coordinates` : {"lat", "lon"} de la page (lieu de l'article), ou None.
    `wikibase_item` : identifiant Wikidata (« Q1775473 »), ou None.

    `exclude` : titres (en minuscules) à ignorer, par exemple les sources déjà utilisées.
    """
    exclude = exclude or set()
    results = []
    for title in _search_titles(query, limit=limit * 2):
        if title.lower() in exclude or title.lower().startswith(("liste ", "chronologie ")):
            continue
        page = _fetch_page(title)
        if page:
            results.append(page)
        if len(results) >= limit:
            break
    return results
