"""Europeana : images du patrimoine européen (musées, archives, bibliothèques) sous licence ouverte."""
from __future__ import annotations

import os

import requests

from auracontent.utils.scraping_helpers import calculate_relevance, download_file, is_used, mark_used

EUROPEANA_SEARCH_URL = "https://api.europeana.eu/record/v2/search.json"
MIN_RELEVANCE = 0.3
MIN_IMAGE_BYTES = 40_000  # écarte les vignettes (edmPreview ~ 200 px)


class EuropeanaProvider:
    def __init__(self, history):
        self.history = history
        self.api_key = os.getenv("EUROPEAN_API_KEY") or os.getenv("EUROPEANA_API_KEY")

    @staticmethod
    def _text(value) -> str:
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
        if isinstance(value, dict):  # champs multilingues {"fr": [...], "def": [...]}
            return " ".join(" ".join(v) if isinstance(v, list) else str(v) for v in value.values())
        return str(value or "")

    def get_image(self, query: str, output_path: str) -> bool:
        if not self.api_key:
            return False
        print(f"🏺 Recherche Europeana : '{query}'...")
        params = {
            "wskey": self.api_key,
            "query": query,
            "media": "true",
            "qf": "TYPE:IMAGE",
            "reusability": "open",  # CC0, CC BY, CC BY-SA, domaine public : réutilisable commercialement
            "rows": 15,
        }
        try:
            r = requests.get(EUROPEANA_SEARCH_URL, params=params, timeout=20)
        except requests.RequestException as e:
            print(f"❌ Europeana : {e}")
            return False
        if r.status_code != 200:
            print(f"❌ Europeana HTTP {r.status_code} : {r.text[:150]}")
            return False

        candidates = []
        for item in r.json().get("items", []):
            item_id = item.get("id")
            urls = item.get("edmIsShownBy") or []
            if not item_id or not urls or is_used(self.history, "europeana", item_id):
                continue
            text = f"{self._text(item.get('title'))} {self._text(item.get('dcDescriptionLangAware') or item.get('dcDescription'))}"
            candidates.append((calculate_relevance(query, text), item_id, urls[0]))

        for score, item_id, url in sorted(candidates, reverse=True)[:3]:
            if score < MIN_RELEVANCE:
                break
            if download_file(url, output_path, min_bytes=MIN_IMAGE_BYTES):
                mark_used(self.history, "europeana", item_id)
                print(f"✅ Europeana OK (Score {score:.2f})")
                return True
        print(f"ℹ️ Europeana : aucune image pertinente pour '{query}' ({len(candidates)} candidats).")
        return False
