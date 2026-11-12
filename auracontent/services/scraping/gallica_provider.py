"""Gallica (BnF) : gravures, estampes, cartes postales et photographies anciennes du domaine public.

Recherche par l'API SRU, image par l'API IIIF :
- https://gallica.bnf.fr/SRU?operation=searchRetrieve&version=1.2&query=...
- https://gallica.bnf.fr/iiif/ark:/12148/<id>/f1/full/<largeur>,/0/native.jpg

ATTENTION, licence : la BnF rend libre la réutilisation NON commerciale ; la réutilisation commerciale
(chaîne monétisée, par exemple) demande une licence payante (utilisation.commerciale@bnf.fr).
D'où `visuals.subject_images.gallica: false` par défaut. L'activer est une décision de l'éditeur.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter

import requests
from auracontent.utils.scraping_helpers import calculate_relevance, download_file, is_used, mark_used
from config.settings import WIKIMEDIA_CONTACT

SRU_URL = "https://gallica.bnf.fr/SRU"
IIIF_URL = "https://gallica.bnf.fr/iiif/{ark}/f1/full/{width},/0/native.jpg"
IMAGE_WIDTH = 1600
MAX_RECORDS = 15
MIN_RELEVANCE = 0.5
MIN_IMAGE_BYTES = 40_000
ARK = re.compile(r"ark:/12148/[a-z0-9]+", re.IGNORECASE)
PUBLIC_DOMAIN = re.compile(r"domaine public|public domain", re.IGNORECASE)
DC = "{http://purl.org/dc/elements/1.1/}"


def parse_records(xml_text: str) -> list[dict]:
    """[{ark, title, public}] pour chaque notice Dublin Core de la réponse SRU."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    records = []
    for dc in root.iter():
        if not dc.tag.endswith("}dc"):
            continue
        values = {}
        for child in dc:
            if child.tag.startswith(DC) and child.text:
                values.setdefault(child.tag[len(DC):], []).append(child.text.strip())
        ark = next((m.group(0) for v in values.get("identifier", []) for m in [ARK.search(v)] if m), None)
        if not ark:
            continue
        records.append({
            "ark": ark,
            "title": " ".join(values.get("title", [])),
            "public": any(PUBLIC_DOMAIN.search(r) for r in values.get("rights", [])),
        })
    return records


class GallicaProvider:
    def __init__(self, history, enabled: bool = False):
        self.history = history
        self.enabled = enabled
        self.last_text = ""   # titre de la dernière notice retenue (contrôle des homonymes)
        self.last_url = ""
        self.headers = {"User-Agent": f"AuraContentPipeline/2.0 ({WIKIMEDIA_CONTACT}) requests/{requests.__version__}"}

    def get_image(self, query: str, output_path: str, accept=None) -> bool:
        """Première image du domaine public pertinente. Journal : requête, résultats bruts, retenus, rejets."""
        if not self.enabled or not query.strip():
            return False
        cql = f'gallica all "{query}" and dc.type all "image"'
        try:
            r = requests.get(SRU_URL, params={"operation": "searchRetrieve", "version": "1.2", "query": cql,
                                              "maximumRecords": MAX_RECORDS}, headers=self.headers, timeout=25)
        except requests.RequestException as e:
            print(f"📜 Gallica « {query} » : erreur réseau {e}")
            return False
        if r.status_code != 200 or "xml" not in r.headers.get("Content-Type", "xml"):
            print(f"📜 Gallica « {query} » : HTTP {r.status_code} (réponse non XML : accès probablement filtré)")
            return False
        records = parse_records(r.text)
        rejects: Counter = Counter()
        candidates = []
        for rec in records:
            if not rec["public"]:
                rejects["pas dans le domaine public"] += 1
            elif is_used(self.history, "gallica", rec["ark"]):
                rejects["déjà utilisée"] += 1
            elif (score := calculate_relevance(query, rec["title"])) < MIN_RELEVANCE:
                rejects[f"pertinence < {MIN_RELEVANCE}"] += 1
            elif accept is not None and not accept(rec["title"]):
                rejects["ni la commune ni l'édifice nommés (homonyme ?)"] += 1
            else:
                candidates.append((score, rec["ark"], rec["title"]))
        print(f"📜 Gallica « {query} » : {len(records)} résultat(s), {len(candidates)} retenu(s)"
              + (f" ; rejets : {', '.join(f'{n} {k}' for k, n in rejects.most_common())}" if rejects else ""))
        for score, ark, title in sorted(candidates, reverse=True)[:3]:
            url = IIIF_URL.format(ark=ark, width=IMAGE_WIDTH)
            if download_file(url, output_path, headers=self.headers, min_bytes=MIN_IMAGE_BYTES):
                self.last_text, self.last_url = title, url
                mark_used(self.history, "gallica", ark)
                print(f"✅ Gallica OK (Score {score:.2f})")
                return True
            print(f"   ↯ Gallica : téléchargement impossible ({url})")
        return False
