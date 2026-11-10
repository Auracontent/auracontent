"""Recherche d'images d'archives libres de droits (Openverse, Wikimedia Commons)."""

from __future__ import annotations

import time
from typing import NamedTuple

import requests
from config.settings import WIKIMEDIA_CONTACT
from auracontent.utils.scraping_helpers import (
    calculate_relevance,
    download_file,
    is_used,
    mark_used,
)

OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"
OPENVERSE_LICENSES = "commercial,modification"
OPENVERSE_PAGE_SIZE = 10
COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"

REQUEST_TIMEOUT = 25
WIKI_API_ATTEMPTS = 2
DEFAULT_RETRY_AFTER = 5
DEFAULT_MIN_RELEVANCE = 0.3
PAUSE_BEFORE_FULLTEXT_SEARCH = 0.5
CATEGORY_PREFIXES = ("Category:", "Catégorie:")


class Candidate(NamedTuple):
    score: float
    image_id: str
    url: str


class ArchiveProvider:
    """Récupère des images d'archives via Openverse et Wikimedia Commons."""

    def __init__(self, history):
        self.wiki_headers = {
            "User-Agent": (
                f"AuraContentPipeline/2.0 ({WIKIMEDIA_CONTACT}) "
                f"requests/{requests.__version__}"
            )
        }
        self.history = history

    # Openverse
    def _rank_openverse_results(self, query: str, results: list[dict]) -> list[Candidate]:
        """Filtre les images déjà utilisées et trie les autres par pertinence."""
        candidates = []
        for item in results:
            image_id = item.get("id")
            if is_used(self.history, "openverse", image_id):
                continue

            tags = " ".join(tag.get("name", "") for tag in item.get("tags", []))
            score = calculate_relevance(query, f"{item.get('title', '')} {tags}")

            if item.get("url"):
                candidates.append(Candidate(score, image_id, item.get("url")))

        candidates.sort(key=lambda candidate: candidate.score, reverse=True)
        return candidates

    def get_openverse(
        self,
        query: str,
        output_path: str,
        min_relevance: float = DEFAULT_MIN_RELEVANCE,
    ) -> bool:
        print(f"🌍 Recherche Openverse (Archives mondiales) : '{query}'...")
        params = {
            "q": query,
            "license_type": OPENVERSE_LICENSES,
            "page_size": OPENVERSE_PAGE_SIZE,
        }

        try:
            response = requests.get(
                OPENVERSE_API_URL, params=params, timeout=REQUEST_TIMEOUT
            )
            if response.status_code == 200:
                candidates = self._rank_openverse_results(
                    query, response.json().get("results", [])
                )
                if candidates and candidates[0].score >= min_relevance:
                    best = candidates[0]
                    if download_file(best.url, output_path, headers=self.wiki_headers):
                        mark_used(self.history, "openverse", best.image_id)
                        print(f"✅ Openverse OK (Score {best.score:.2f})")
                        return True
        except Exception as e:
            print(f"❌ Openverse Erreur: {e}")
        return False

    # Wikimedia Commons
    def _wiki_api(self, params: dict) -> requests.Response | None:
        """Interroge l'API Commons, avec une pause si le quota est atteint (429)."""
        for _ in range(WIKI_API_ATTEMPTS):
            try:
                response = requests.get(
                    COMMONS_API_URL,
                    params=params,
                    headers=self.wiki_headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if response.status_code == 200:
                    return response
                if response.status_code == 429:
                    time.sleep(
                        int(response.headers.get("Retry-After", DEFAULT_RETRY_AFTER))
                    )
            except Exception:
                pass
        return None

    def _process_wiki_pages(
        self, pages: dict, output_path: str, query: str, min_relevance: float
    ) -> bool:
        """Télécharge la première image pertinente, non utilisée et non PDF."""
        for page_id, info in pages.items():
            image_infos = info.get("imageinfo", [])
            if not image_infos:
                continue

            image_url = image_infos[0].get("url", "")
            title = info.get("title", "")

            if not image_url or "pdf" in image_url.lower():
                continue
            if is_used(self.history, "wikimedia", page_id):
                continue

            score = calculate_relevance(query, title)
            if score >= min_relevance and download_file(
                image_url, output_path, headers=self.wiki_headers
            ):
                mark_used(self.history, "wikimedia", page_id)
                print(f"✅ Wikimedia OK (Score {score:.2f})")
                return True
        return False

    @staticmethod
    def _category_params(category: str) -> dict:
        return {
            "action": "query",
            "format": "json",
            "generator": "categorymembers",
            "gcmtitle": category,
            "gcmtype": "file",
            "gcmlimit": "3",
            "prop": "imageinfo",
            "iiprop": "url",
        }

    @staticmethod
    def _fulltext_params(query: str) -> dict:
        return {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:bitmap",
            "gsrnamespace": "6",
            "gsrlimit": "5",
            "prop": "imageinfo",
            "iiprop": "url",
        }

    @staticmethod
    def _pages_of(response: requests.Response) -> dict:
        return response.json().get("query", {}).get("pages", {})

    def get_wikimedia(self, query: str, output_path: str) -> bool:
        """Catégorie Commons, puis Openverse, puis recherche plein texte Commons."""
        category = query if query.startswith(CATEGORY_PREFIXES) else f"Catégorie:{query}"

        response = self._wiki_api(self._category_params(category))
        if response and self._process_wiki_pages(
            self._pages_of(response), output_path, query, min_relevance=0.0
        ):
            return True

        if self.get_openverse(query, output_path):
            return True
        time.sleep(PAUSE_BEFORE_FULLTEXT_SEARCH)

        print(f"🏛️ Recherche Wikimedia plein texte : '{query}'...")
        response = self._wiki_api(self._fulltext_params(query))
        if response and self._process_wiki_pages(
            self._pages_of(response), output_path, query, min_relevance=0.3
        ):
            return True

        return False