"""Photos réelles du sujet : images de l'article Wikipédia source, puis de sa catégorie Wikimedia Commons,
puis gravures et documents anciens du même lieu sur Commons.

Ces images forment une réserve propre à la vidéo (`SubjectImagePool`). Chaque fichier sert deux fois au
plus : plusieurs photos différentes du même lieu sont bienvenues, la même photo répétée ne l'est pas.

Image exploitable : licence qui permet la réutilisation (domaine public, CC0, CC BY, CC BY-SA ; ni NC ni ND),
au moins 1000 px de large, ni logo, ni carte, ni blason, ni pictogramme.

Homonymes : une image trouvée par RECHERCHE (et non par la page source ou la catégorie Commons que
Wikidata lui associe) doit nommer la commune ou le département dans son titre, sa description ou ses
catégories ; sinon elle est écartée (deux abbayes du même nom, deux « pont du Diable »...).

Tout échec réseau donne une réserve vide : la scène passe alors aux sources suivantes (AssetManager).
"""
from __future__ import annotations

import html
import re
import time
import unicodedata
import urllib.parse
from dataclasses import dataclass

import requests
from auracontent.utils.scraping_helpers import calculate_relevance
from config.settings import WIKIMEDIA_CONTACT
from constants import WIKIPEDIA_API_URL

COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": f"AuraContentPipeline/2.0 ({WIKIMEDIA_CONTACT}) requests/{requests.__version__}"}
REQUEST_TIMEOUT = 20
DELAY_BETWEEN_CALLS = 0.3
THUMB_WIDTH = 2000            # vignette Commons : assez pour un plein écran 1080 x 1920 recadré
BATCH = 50                    # titres par requête imageinfo (limite de l'API)

DEFAULT_MIN_WIDTH = 1000      # en dessous, l'image floute une fois agrandie en plein écran
DEFAULT_MIN_HEIGHT = 500
DEFAULT_CATEGORY_LIMIT = 60
DEFAULT_DOCUMENT_LIMIT = 15
DEFAULT_MAX_USES = 2
ALLOWED_MIME = {"image/jpeg", "image/png"}

# Pas des photos du lieu : logos, blasons, drapeaux, cartes de situation, pictogrammes
EXCLUDED_TITLE = re.compile(
    r"\b(logo|blason|armoiries|coat[ _]of[ _]arms|flag|drapeau|location[ _]map|locator|map|"
    r"carte[ _]de[ _]situation|icon|icône|pictogram|pictogramme|symbole?|signature|diagram|schéma)\b",
    re.IGNORECASE,
)
# Fin du contenu de l'article : boîtes de navigation et bandeaux de portail (leurs images sont hors sujet,
# par exemple « Notre-Dame de Paris.jpg » dans la palette « Abbayes cisterciennes »)
END_OF_CONTENT = re.compile(r'class="[^"]*\b(navbox|bandeau-portail)\b')
FILE_LINK = re.compile(r'href="/wiki/(?:Fichier|File):([^"#?]+)"')
DOCUMENT_WORDS = '(gravure OR lithographie OR "carte postale" OR engraving OR lithograph OR estampe)'

ORIGINS = ("article", "commons", "document")   # ordre de priorité
# Licences : NC (pas d'usage commercial), ND (pas de modification : le recadrage en est une), non libre
RESTRICTED_LICENSE = re.compile(r"\b(nc|nd)\b|non[- ]?commercial|no[- ]?deriv|non[- ]?free|fair[ _]use|all rights reserved|copyrighted",
                                re.IGNORECASE)
FREE_LICENSE = re.compile(r"public domain|domaine public|\bpd\b|cc0|cc[- ]by|gfdl|attribution|"
                          r"no restrictions|licence ouverte|etalab", re.IGNORECASE)
EXTMETADATA = "LicenseShortName|UsageTerms|NonFree|ImageDescription|ObjectName|Categories"


@dataclass(frozen=True)
class SubjectImage:
    key: str          # titre du fichier normalisé : identifie le fichier, quelle que soit la source
    title: str        # « File:Abbaye de la Grâce-Dieu.jpg »
    url: str          # vignette (THUMB_WIDTH px) ou original s'il est plus petit
    width: int
    height: int
    origin: str       # article | commons | document
    description: str = ""   # titre + description + catégories (contrôle des homonymes, journal)
    license: str = ""


def file_key(title: str) -> str:
    """« Fichier:Abbaye_de_la_Grâce-Dieu.jpg » et « File:Abbaye de la Grâce-Dieu.jpg » -> même clé."""
    name = html.unescape(urllib.parse.unquote(str(title)))
    if re.match(r"^(file|fichier|image):", name, re.IGNORECASE):
        name = name.split(":", 1)[1]
    name = name.replace("_", " ").strip()
    return name[:1].upper() + name[1:]


def _get(url: str, params: dict, retries: int = 2) -> dict | None:
    params = {"format": "json", "formatversion": 2, **params}
    for attempt in range(retries + 1):
        time.sleep(DELAY_BETWEEN_CALLS)
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 3 * (attempt + 1))))
                continue
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == retries:
                print(f"⚠️ Wikimedia indisponible : {e}")
                return None
            time.sleep(2)
    return None


# ==========================================
# FILTRES
# ==========================================
def _meta(info: dict, name: str) -> str:
    value = ((info.get("extmetadata") or {}).get(name) or {}).get("value", "")
    return re.sub(r"<[^>]+>", " ", str(value))   # la description Commons est du HTML


def license_ok(info: dict) -> bool:
    """La licence permet la réutilisation commerciale et la modification (recadrage)."""
    if _meta(info, "NonFree").strip().lower() in ("true", "1"):
        return False
    text = f"{_meta(info, 'LicenseShortName')} {_meta(info, 'UsageTerms')}"
    return bool(FREE_LICENSE.search(text)) and not RESTRICTED_LICENSE.search(text)


def usable(info: dict, title: str, min_width: int = DEFAULT_MIN_WIDTH, min_height: int = DEFAULT_MIN_HEIGHT) -> bool:
    """Image exploitable : JPEG/PNG, licence libre, assez grande, ni logo, ni carte, ni blason, ni pictogramme."""
    if info.get("mime") not in ALLOWED_MIME:
        return False
    if int(info.get("width") or 0) < min_width or int(info.get("height") or 0) < min_height:
        return False
    if EXCLUDED_TITLE.search(file_key(title)):
        return False
    return license_ok(info)


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", str(text).lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def mentions_place(text: str, place_terms: list[str]) -> bool:
    """Le texte nomme-t-il l'un des lieux (commune, département) ? Casse, accents et tirets ignorés."""
    folded = f" {_fold(text)} "
    return any(f" {_fold(t)} " in folded for t in place_terms if _fold(t))


def _to_image(page: dict, origin: str, min_width: int, min_height: int) -> SubjectImage | None:
    infos = page.get("imageinfo") or []
    if not infos or not usable(infos[0], page.get("title", ""), min_width, min_height):
        return None
    info = infos[0]
    url = info.get("thumburl") or info.get("url")
    if not url:
        return None
    description = " ".join(x for x in (file_key(page["title"]), _meta(info, "ObjectName"),
                                       _meta(info, "ImageDescription"), _meta(info, "Categories")) if x.strip())
    return SubjectImage(file_key(page["title"]), page["title"], url,
                        int(info.get("width") or 0), int(info.get("height") or 0), origin,
                        " ".join(description.split())[:600], _meta(info, "LicenseShortName").strip())


def _imageinfo_params(**extra) -> dict:
    return {"action": "query", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
            "iiextmetadatafilter": EXTMETADATA, "iiextmetadatalanguage": "fr", "iiurlwidth": THUMB_WIDTH, **extra}


# ==========================================
# (a) IMAGES DE L'ARTICLE
# ==========================================
def article_file_titles(html: str) -> list[str]:
    """Fichiers cités dans le corps de l'article, dans l'ordre (image principale d'abord)."""
    end = END_OF_CONTENT.search(html)
    body = html[: end.start()] if end else html
    seen, titles = set(), []
    for m in FILE_LINK.finditer(body):
        key = file_key(m.group(1))
        if key not in seen:
            seen.add(key)
            titles.append(f"File:{key}")
    return titles


def _images_for_titles(titles: list[str], origin: str, min_width: int, min_height: int) -> list[SubjectImage]:
    by_key: dict[str, SubjectImage] = {}
    for i in range(0, len(titles), BATCH):
        data = _get(COMMONS_API_URL, _imageinfo_params(titles="|".join(titles[i:i + BATCH])))
        for page in (data or {}).get("query", {}).get("pages", []):
            image = _to_image(page, origin, min_width, min_height)
            if image:
                by_key[image.key] = image
    return [by_key[file_key(t)] for t in titles if file_key(t) in by_key]   # ordre de l'article


def article_images(page_title: str, min_width: int = DEFAULT_MIN_WIDTH,
                   min_height: int = DEFAULT_MIN_HEIGHT) -> list[SubjectImage]:
    data = _get(WIKIPEDIA_API_URL, {"action": "parse", "page": page_title, "prop": "text", "redirects": 1})
    html = ((data or {}).get("parse") or {}).get("text") or ""
    titles = article_file_titles(html) if isinstance(html, str) else []
    return _images_for_titles(titles, "article", min_width, min_height) if titles else []


# ==========================================
# (b) CATÉGORIE COMMONS DU LIEU
# ==========================================
def category_images(category: str, limit: int = DEFAULT_CATEGORY_LIMIT, min_width: int = DEFAULT_MIN_WIDTH,
                    min_height: int = DEFAULT_MIN_HEIGHT) -> list[SubjectImage]:
    name = category.split(":", 1)[1] if category.lower().startswith(("category:", "catégorie:")) else category
    data = _get(COMMONS_API_URL, _imageinfo_params(generator="categorymembers", gcmtitle=f"Category:{name}",
                                                   gcmtype="file", gcmlimit=min(limit, 500)))
    pages = sorted((data or {}).get("query", {}).get("pages", []), key=lambda p: p.get("title", ""))
    return [img for img in (_to_image(p, "commons", min_width, min_height) for p in pages) if img]


# ==========================================
# (c) GRAVURES ET DOCUMENTS ANCIENS
# ==========================================
def place_query(place_terms: list[str]) -> str:
    """« ("Chaux-lès-Passavant" OR "Doubs") » : commune ou département ajouté à une recherche Commons."""
    terms = [t for t in place_terms if t]
    return "(" + " OR ".join(f'"{t}"' for t in terms) + ")" if terms else ""


def document_images(subject: str, place_terms: list[str], limit: int = DEFAULT_DOCUMENT_LIMIT,
                    min_width: int = DEFAULT_MIN_WIDTH, min_height: int = DEFAULT_MIN_HEIGHT,
                    min_relevance: float = 0.6) -> list[SubjectImage]:
    """Gravures, lithographies, cartes postales anciennes de Commons qui nomment le sujet ET sa commune
    ou son département (homonymes écartés). Sans commune ni département connus : aucune recherche."""
    if not place_terms:
        return []
    query = f'"{subject}" {place_query(place_terms)} {DOCUMENT_WORDS} filetype:bitmap'
    data = _get(COMMONS_API_URL, _imageinfo_params(generator="search", gsrnamespace=6, gsrlimit=limit,
                                                   gsrsearch=query))
    pages = sorted((data or {}).get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
    images = []
    for page in pages:
        image = _to_image(page, "document", min_width, min_height)
        if not image or calculate_relevance(subject, image.description) < min_relevance:
            continue
        if not mentions_place(image.description, place_terms):
            print(f"   ↯ Homonyme probable écarté : {image.title}")
            continue
        images.append(image)
    return images


def subject_name(source_title: str) -> str:
    """« Abbaye de la Grâce-Dieu (Doubs) » -> « Abbaye de la Grâce-Dieu » (précision d'homonymie retirée)."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(source_title or "")).strip()


def place_terms_of(pick: dict | None) -> list[str]:
    """Commune et département du sujet (Wikidata), pour les requêtes et le contrôle des homonymes."""
    pick = pick or {}
    return [t for t in (str(pick.get("commune") or "").strip(), str(pick.get("department") or "").strip()) if t]


def collect_subject_images(source_title: str | None, commons_category: str | None = None,
                           cfg: dict | None = None, place_terms: list[str] | None = None,
                           documents: bool | None = None) -> list[SubjectImage]:
    """Réserve du sujet, sans doublon, dans l'ordre (a) article, (b) catégorie Commons, (c) documents.

    La catégorie vient de Wikidata (P373) quand elle existe : elle est alors fiable. Sinon elle est devinée
    d'après le nom du sujet, et chaque image doit nommer la commune ou le département (homonymes).
    """
    cfg = cfg or {}
    place_terms = list(place_terms or [])
    sizes = {"min_width": int(cfg.get("min_width", DEFAULT_MIN_WIDTH)),
             "min_height": int(cfg.get("min_height", DEFAULT_MIN_HEIGHT))}
    name = subject_name(source_title or "")
    found: list[SubjectImage] = []
    steps = []
    if source_title:
        steps.append(("article", lambda: article_images(source_title, **sizes)))
    category = commons_category or name
    if category:
        def commons():
            images = category_images(category, int(cfg.get("category_limit", DEFAULT_CATEGORY_LIMIT)), **sizes)
            if commons_category:
                return images
            kept = [img for img in images if mentions_place(img.description, place_terms)]
            if len(kept) < len(images):
                print(f"   ↯ Catégorie devinée « {category} » : {len(images) - len(kept)} image(s) sans la "
                      f"commune ni le département, écartée(s)")
            return kept
        steps.append(("commons", commons))
    if name and (cfg.get("documents", True) if documents is None else documents):
        steps.append(("document", lambda: document_images(name, place_terms,
                                                          int(cfg.get("document_limit", DEFAULT_DOCUMENT_LIMIT)),
                                                          **sizes)))
    seen = set()
    for label, step in steps:
        try:
            images = step()
        except Exception as e:   # jamais bloquant : la scène passera aux sources suivantes
            print(f"⚠️ Images du sujet ({label}) : {e}")
            images = []
        new = [img for img in images if img.key not in seen]
        seen.update(img.key for img in new)
        found.extend(new)
        print(f"   🖼️ {label} : {len(new)} image(s) exploitable(s)")
    return found


# ==========================================
# RÉSERVE DE LA VIDÉO
# ==========================================
class SubjectImagePool:
    """Images du sujet distribuées aux scènes : chaque fichier sert `max_uses` fois au plus.

    `candidates(first_use_only=True)` : fichiers encore jamais montrés, dans l'ordre de priorité.
    `candidates(first_use_only=False)` : fichiers déjà montrés une fois, les moins utilisés d'abord.
    Le fichier `avoid` (visuel de la scène précédente) est écarté : jamais deux fois de suite.
    """

    def __init__(self, images: list[SubjectImage], max_uses: int = DEFAULT_MAX_USES):
        self.images = list(images)
        self.max_uses = max(int(max_uses), 1)
        self.uses: dict[str, int] = {}
        self.broken: set[str] = set()

    def __len__(self) -> int:
        return len(self.images)

    def candidates(self, avoid: str | None = None, first_use_only: bool = True) -> list[SubjectImage]:
        rank = {origin: i for i, origin in enumerate(ORIGINS)}
        pool = [img for img in self.images
                if img.key not in self.broken and img.key != avoid and self.uses.get(img.key, 0) < self.max_uses
                and (self.uses.get(img.key, 0) == 0) == first_use_only]
        return sorted(pool, key=lambda img: (self.uses.get(img.key, 0), rank.get(img.origin, len(ORIGINS))))

    def record(self, key: str) -> None:
        self.uses[key] = self.uses.get(key, 0) + 1

    def discard(self, key: str) -> None:
        """Téléchargement impossible : le fichier n'est plus proposé."""
        self.broken.add(key)
