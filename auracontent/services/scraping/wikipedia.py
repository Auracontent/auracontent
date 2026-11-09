"""Recherche de pages Wikipédia (FR) utilisables comme source d'un script."""
import os
import time

import requests

from constants import WIKIPEDIA_API_URL

HEADERS = {"User-Agent": os.getenv("WIKIMEDIA_CONTACT", "auraContentPipeline/1.0 (contact non configure)")}
MIN_EXTRACT_CHARS = 1500     # en dessous, pas assez de matière pour 11 scènes
MAX_EXTRACT_CHARS = 60000    # au-dessus : article généraliste (ville, région, pays), pas un sujet précis
DELAY_BETWEEN_CALLS = 0.3


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


def _fetch_page(title: str) -> dict | None:
    data = _get({"action": "query", "prop": "extracts|info|pageprops", "titles": title,
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
    return {"title": page["title"], "url": page.get("fullurl", ""), "extract": extract}


def find_candidates(query: str, limit: int = 8, exclude: set[str] | None = None) -> list[dict]:
    """Pages exploitables pour `query` : [{"title", "url", "extract"}], dans l'ordre de pertinence.

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
