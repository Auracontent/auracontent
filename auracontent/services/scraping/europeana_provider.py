"""Europeana : images du patrimoine européen (musées, archives, bibliothèques) sous licence ouverte."""
from __future__ import annotations

import os
from collections import Counter

import requests
from auracontent.utils.scraping_helpers import calculate_relevance, download_file, is_used, mark_used
from config.settings import WIKIMEDIA_CONTACT

HEADERS = {"User-Agent": f"AuraContentPipeline/2.0 ({WIKIMEDIA_CONTACT}) requests/{requests.__version__}"}
EUROPEANA_SEARCH_URL = "https://api.europeana.eu/record/v2/search.json"
MIN_RELEVANCE = 0.3
MIN_IMAGE_BYTES = 40_000  # écarte les vignettes (edmPreview ~ 200 px)


class EuropeanaProvider:
    def __init__(self, history):
        self.history = history
        # strip : un espace / retour à la ligne collé dans un Secret GitHub rend la clé invalide (401)
        self.api_key = (os.getenv("EUROPEAN_API_KEY") or os.getenv("EUROPEANA_API_KEY") or "").strip() or None
        self.last_text = ""   # titre + description de la dernière notice retenue (contrôle des homonymes)
        self.last_url = ""

    @staticmethod
    def _text(value) -> str:
        if isinstance(value, list):
            return " ".join(str(v) for v in value)
        if isinstance(value, dict):  # champs multilingues {"fr": [...], "def": [...]}
            return " ".join(" ".join(v) if isinstance(v, list) else str(v) for v in value.values())
        return str(value or "")

    def get_image(self, query: str, output_path: str, accept=None) -> bool:
        """Première image pertinente pour `query`. `accept(texte)` : contrôle supplémentaire de la notice
        (homonymes). Journal : requête, résultats bruts, retenus, et raison de chaque rejet."""
        if not self.api_key:
            print("🏺 Europeana : clé EUROPEANA_API_KEY absente, source ignorée.")
            return False
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
            print(f"🏺 Europeana « {query} » : erreur réseau {e}")
            return False
        if r.status_code != 200:
            print(f"🏺 Europeana « {query} » : HTTP {r.status_code} {r.text[:150]}")
            return False

        data = r.json()
        items = data.get("items", [])
        rejects: Counter = Counter()
        candidates = []
        for item in items:
            item_id = item.get("id")
            urls = item.get("edmIsShownBy") or []
            if not item_id or not urls:
                rejects["sans image en grand"] += 1
                continue
            if is_used(self.history, "europeana", item_id):
                rejects["déjà utilisée"] += 1
                continue
            text = f"{self._text(item.get('title'))} {self._text(item.get('dcDescriptionLangAware') or item.get('dcDescription'))}"
            score = calculate_relevance(query, text)
            if score < MIN_RELEVANCE:
                rejects[f"pertinence < {MIN_RELEVANCE}"] += 1
                continue
            if accept is not None and not accept(text):
                rejects["ni la commune ni l'édifice nommés (homonyme ?)"] += 1
                continue
            candidates.append((score, item_id, urls[0], text))
        print(f"🏺 Europeana « {query} » : {data.get('totalResults', len(items))} résultat(s), {len(items)} "
              f"examiné(s), {len(candidates)} retenu(s)" + (f" ; rejets : {_reasons(rejects)}" if rejects else ""))

        for score, item_id, url, text in sorted(candidates, reverse=True)[:3]:
            # Wikimedia (hébergeur de nombreuses notices) refuse les requêtes sans User-Agent identifié (403)
            if download_file(url, output_path, min_bytes=MIN_IMAGE_BYTES, headers=HEADERS):
                self.last_text, self.last_url = text, url
                mark_used(self.history, "europeana", item_id)
                print(f"✅ Europeana OK (Score {score:.2f}) : {url}")
                return True
            print(f"   ↯ Europeana : téléchargement impossible ou image trop petite ({url})")
        return False


def _reasons(counter: Counter) -> str:
    return ", ".join(f"{n} {reason}" for reason, n in counter.most_common())
