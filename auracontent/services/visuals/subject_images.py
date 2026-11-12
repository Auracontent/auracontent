"""Photos réelles du sujet : images de l'article Wikipédia source, puis de sa catégorie Wikimedia Commons,
puis gravures et documents anciens du même lieu sur Commons.

Ces images forment une réserve propre à la vidéo (`SubjectImagePool`). Chaque fichier sert deux fois au
plus : plusieurs photos différentes du même lieu sont bienvenues, la même photo répétée ne l'est pas.

Image exploitable : licence qui permet la réutilisation (domaine public, CC0, CC BY, CC BY-SA ; ni NC ni ND),
au moins 1000 px de large, ni logo, ni carte, ni plan, ni schéma, ni blason, ni pictogramme : le filtre porte
sur le nom du fichier, ses catégories Commons et son type (subject_images.allowed_mime).

Objet précis (anecdote « Le saviez-vous ? ») : quand le sujet est un objet ou un édifice et non l'article
entier (une statue dans une église de la commune), ses images passent en tête : illustration de l'anecdote,
catégorie Commons de l'objet ou de l'édifice, puis recherche Commons qui nomme l'objet ET la commune.

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
from dataclasses import dataclass, replace

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

# Pas des photos du lieu : logos, blasons, drapeaux, cartes, plans, schémas, relevés géographiques, graphiques.
# Mots entiers du NOM du fichier (« 32194-Larressingle-Routes-Hydro.png », « Sols.png », « argile.jpg »).
EXCLUDED_TITLE = re.compile(
    r"\b(logo|blason|armoiries|coat[ _]of[ _]arms|flag|drapeau|location[ _]map|locator|maps?|cartes?|"
    r"carte[ _]de[ _]situation|icon|icône|pictogram|pictogramme|symbole?|signature|diagrams?|diagramme|"
    r"sch[ée]mas?|schematic|plans?|floor[ _]?plan|cadastre|cadastral|routes?|road|roads|hydro|hydrographie|"
    r"hydrographic|sols?|soils?|argiles?|clay|g[ée]ologi\w*|geology|(?<!bas )(?<!haut )reliefs?|topograph\w*|altitude|"
    r"occupation|landuse|land[ _]use|corine|climat\w*|climograph\w*|pluviom\w*|population|demograph\w*|"
    r"d[ée]mographi\w*|graph|graphique|chart|statisti\w*|localisation|situation|isohyp\w*|"
    r"lithologi\w*|p[ée]dologi\w*|bassin[ _]versant|r[ée]seau)\b",
    re.IGNORECASE,
)
# Catégories Commons des cartes, plans et schémas (« Road maps of communes in Gers », « Floor plans of
# churches », « Geological maps », « Population diagrams of municipalities »...)
EXCLUDED_CATEGORY = re.compile(
    r"\b(maps?|cartes?|plans?|floor[ _]plans?|diagrams?|diagrammes?|sch[ée]mas?|charts?|graphs?|"
    r"cadastr\w*|g[ée]olog\w*|hydrograph\w*|topograph\w*|soils?|sols|climat\w*|climograph\w*|"
    r"population|demograph\w*|d[ée]mograph\w*|statisti\w*|coats? of arms|blasons?|logos?|locator)\b",
    re.IGNORECASE,
)
# Les cartes postales sont des photos anciennes, pas des cartes : retirées avant le filtre
POSTCARD = re.compile(r"\b(cartes?[ _-]postales?|post[ _-]?cards?)\b", re.IGNORECASE)
# Fin du contenu de l'article : boîtes de navigation et bandeaux de portail (leurs images sont hors sujet,
# par exemple « Notre-Dame de Paris.jpg » dans la palette « Abbayes cisterciennes »)
END_OF_CONTENT = re.compile(r'class="[^"]*\b(navbox|bandeau-portail)\b')
FILE_LINK = re.compile(r'href="/wiki/(?:Fichier|File):([^"#?]+)"')

ORIGINS = ("object", "article", "commons", "document")   # ordre de priorité ; object : l'objet de l'anecdote
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


def is_map_or_diagram(title: str, categories: str = "") -> bool:
    """Carte, plan, schéma, graphique, blason... d'après le nom du fichier et ses catégories Commons."""
    name = POSTCARD.sub(" ", re.sub(r"[_\-.()]+", " ", file_key(title).rsplit(".", 1)[0]))
    if EXCLUDED_TITLE.search(name):
        return True
    return any(EXCLUDED_CATEGORY.search(POSTCARD.sub(" ", c)) for c in str(categories or "").split("|"))


def usable(info: dict, title: str, min_width: int = DEFAULT_MIN_WIDTH, min_height: int = DEFAULT_MIN_HEIGHT,
           allowed_mime=ALLOWED_MIME) -> bool:
    """Image exploitable : type autorisé (JPEG, PNG), licence libre, assez grande, ni logo, ni carte, ni plan,
    ni schéma, ni blason, ni pictogramme (nom du fichier et catégories Commons)."""
    if info.get("mime") not in set(allowed_mime or ALLOWED_MIME):
        return False
    if int(info.get("width") or 0) < min_width or int(info.get("height") or 0) < min_height:
        return False
    if is_map_or_diagram(title, _meta(info, "Categories")):
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


def _to_image(page: dict, origin: str, min_width: int, min_height: int,
              allowed_mime=ALLOWED_MIME) -> SubjectImage | None:
    infos = page.get("imageinfo") or []
    if not infos or not usable(infos[0], page.get("title", ""), min_width, min_height, allowed_mime):
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


def _images_for_titles(titles: list[str], origin: str, min_width: int, min_height: int,
                       allowed_mime=ALLOWED_MIME) -> list[SubjectImage]:
    by_key: dict[str, SubjectImage] = {}
    for i in range(0, len(titles), BATCH):
        data = _get(COMMONS_API_URL, _imageinfo_params(titles="|".join(titles[i:i + BATCH])))
        for page in (data or {}).get("query", {}).get("pages", []):
            image = _to_image(page, origin, min_width, min_height, allowed_mime)
            if image:
                by_key[image.key] = image
    return [by_key[file_key(t)] for t in titles if file_key(t) in by_key]   # ordre de l'article


def article_images(page_title: str, min_width: int = DEFAULT_MIN_WIDTH,
                   min_height: int = DEFAULT_MIN_HEIGHT, allowed_mime=ALLOWED_MIME) -> list[SubjectImage]:
    data = _get(WIKIPEDIA_API_URL, {"action": "parse", "page": page_title, "prop": "text", "redirects": 1})
    html = ((data or {}).get("parse") or {}).get("text") or ""
    titles = article_file_titles(html) if isinstance(html, str) else []
    return _images_for_titles(titles, "article", min_width, min_height, allowed_mime) if titles else []


# ==========================================
# (b) CATÉGORIE COMMONS DU LIEU
# ==========================================
def category_images(category: str, limit: int = DEFAULT_CATEGORY_LIMIT, min_width: int = DEFAULT_MIN_WIDTH,
                    min_height: int = DEFAULT_MIN_HEIGHT, allowed_mime=ALLOWED_MIME,
                    origin: str = "commons") -> list[SubjectImage]:
    name = category.split(":", 1)[1] if category.lower().startswith(("category:", "catégorie:")) else category
    data = _get(COMMONS_API_URL, _imageinfo_params(generator="categorymembers", gcmtitle=f"Category:{name}",
                                                   gcmtype="file", gcmlimit=min(limit, 500)))
    pages = sorted((data or {}).get("query", {}).get("pages", []), key=lambda p: p.get("title", ""))
    return [img for img in (_to_image(p, origin, min_width, min_height, allowed_mime) for p in pages) if img]


# ==========================================
# (c) GRAVURES ET DOCUMENTS ANCIENS
# ==========================================
def place_query(place_terms: list[str]) -> str:
    """« ("Chaux-lès-Passavant" OR "Doubs") » : commune ou département ajouté à une recherche Commons."""
    terms = [t for t in place_terms if t]
    return "(" + " OR ".join(f'"{t}"' for t in terms) + ")" if terms else ""


DOCUMENT_TERMS = ("gravure", "engraving", "lithographie", "lithograph", '"carte postale"', "postcard", "estampe")


def document_images(subject: str, place_terms: list[str], limit: int = DEFAULT_DOCUMENT_LIMIT,
                    min_width: int = DEFAULT_MIN_WIDTH, min_height: int = DEFAULT_MIN_HEIGHT,
                    min_relevance: float = 0.6, allowed_mime=ALLOWED_MIME) -> list[SubjectImage]:
    """Gravures, lithographies, cartes postales anciennes de Commons sur le sujet (nom de l'édifice).

    Une requête par type de document : la recherche Commons ne traite pas les groupes « (a OR b) » comme
    attendu (0 résultat). La notice doit être pertinente (nom de l'édifice) ET nommer la commune, le
    département ou l'édifice par un nom propre distinctif ; sinon c'est un homonyme probable. Sans commune
    ni département connus : aucune recherche. Journal : requête, résultats bruts, retenus, rejets."""
    if not place_terms:
        print("   📜 Documents Commons : ni commune ni département connus, aucune recherche (homonymes).")
        return []
    images: list[SubjectImage] = []
    seen: set[str] = set()
    for term in DOCUMENT_TERMS:
        query = f'"{subject}" {term} filetype:bitmap'
        data = _get(COMMONS_API_URL, _imageinfo_params(generator="search", gsrnamespace=6, gsrlimit=limit,
                                                       gsrsearch=query))
        pages = sorted((data or {}).get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
        rejects: dict[str, int] = {}
        kept = 0
        for page in pages:
            if file_key(page.get("title", "")) in seen:
                continue
            seen.add(file_key(page.get("title", "")))
            image = _to_image(page, "document", min_width, min_height, allowed_mime)
            reason = None
            if not image:
                reason = "non exploitable (licence, taille, type, carte ou plan)"
            elif calculate_relevance(subject, image.description) < min_relevance \
                    and not name_matches(image.description, subject):
                reason = "notice qui ne nomme pas l'édifice"
            elif not (mentions_place(image.description, place_terms)
                      or (is_distinctive(subject, place_terms)
                          and name_matches(image.description, subject, place_terms))):
                reason = "ni la commune ni l'édifice nommés (homonyme ?)"
            if reason:
                rejects[reason] = rejects.get(reason, 0) + 1
            else:
                images.append(image)
                kept += 1
        detail = ", ".join(f"{n} {r}" for r, n in sorted(rejects.items(), key=lambda kv: -kv[1]))
        print(f"   📜 Documents Commons « {query} » : {len(pages)} résultat(s), {kept} retenu(s)"
              + (f" ; rejets : {detail}" if detail else ""))
        if len(images) >= limit:
            break
    return images[:limit]


# ==========================================
# (0) OBJET PRÉCIS DE L'ANECDOTE ET SON ÉDIFICE
# ==========================================
NAME_STOPWORDS = {"le", "la", "les", "l", "de", "du", "des", "d", "et", "en", "au", "aux", "a", "un", "une",
                  "sur", "sous", "dans", "par", "pour"}
WEAK_NAME_WORDS = {"saint", "sainte", "saints", "saintes", "st", "ste", "notre", "dame", "grand", "grande",
                   "petit", "petite", "vieux", "vieille", "vieil", "nouveau", "nouvelle", "haut", "haute", "bas"}


def name_tokens(name: str, exclude: list[str] | None = None) -> tuple[list[str], list[str]]:
    """(noms propres, noms communs) d'un nom d'objet, sans les mots des lieux `exclude` (commune...).

    « église Saint-Sigismond de Larressingle » -> (["saint", "sigismond"], ["eglise"]).
    """
    skip = {w for t in exclude or [] for w in _fold(t).split()}
    words = re.findall(r"[^\W\d_]+", str(name or ""))
    proper, common = [], []
    for i, word in enumerate(words):
        token = _fold(word)
        if not token or token in NAME_STOPWORDS or token in skip:
            continue
        (proper if word[:1].isupper() and (i > 0 or len(words) == 1) else common).append(token)
    return proper, common


def name_matches(text: str, name: str, exclude: list[str] | None = None) -> bool:
    """Le texte (nom de fichier, description, catégories) désigne-t-il cet objet ou cet édifice ?

    Avec un nom propre distinctif (« Sigismond ») : tous les noms propres doivent y figurer. Sinon (« statue
    équestre ») : tous les mots. Casse, accents et tirets ignorés."""
    proper, common = name_tokens(name, exclude)
    words = set(_fold(text).split())
    if any(t not in WEAK_NAME_WORDS and len(t) >= 4 for t in proper):
        return all(t in words for t in proper)
    needed = proper + common
    return bool(needed) and all(t in words for t in needed)


def is_distinctive(name: str, exclude: list[str] | None = None) -> bool:
    """Le nom contient un nom propre distinctif (« Sigismond », « Gard ») : assez pour écarter les homonymes
    sans la commune. « Abbaye X » ou « église Saint-Martin » ne le sont pas."""
    proper, _ = name_tokens(name, exclude)
    return any(t not in WEAK_NAME_WORDS and len(t) >= 4 for t in proper)


def mentions_focus(text: str, names: list[str], exclude: list[str] | None = None) -> bool:
    """Le texte (un titre) nomme-t-il l'objet ou l'édifice : un nom propre distinctif (« Sigismond ») ou le
    nom commun qui le désigne (« statue », « église ») ?"""
    words = set(_fold(text).split())
    for name in names:
        proper, common = name_tokens(name, exclude)
        strong = [t for t in proper if t not in WEAK_NAME_WORDS and len(t) >= 4]
        if any(t in words for t in strong) or (common and common[0] in words):
            return True
    return False


def _search(query: str, namespace: int, limit: int, **extra) -> dict | None:
    if namespace == 6:
        return _get(COMMONS_API_URL, _imageinfo_params(generator="search", gsrnamespace=6, gsrlimit=limit,
                                                       gsrsearch=query, **extra))
    return _get(COMMONS_API_URL, {"action": "query", "list": "search", "srnamespace": namespace,
                                  "srlimit": limit, "srsearch": query})


def focus_categories(name: str, place_terms: list[str], limit: int = 2) -> list[str]:
    """Catégories Commons de l'objet ou de l'édifice dans sa commune (« Église Saint-Sigismond de
    Larressingle »). Sans commune ni département connus : aucune (homonymes)."""
    if not place_terms:
        return []
    data = _search(f"{name} {place_query(place_terms)}", 14, 10)
    found = []
    for hit in (data or {}).get("query", {}).get("search", []):
        title = hit.get("title", "")
        if name_matches(title, name, place_terms) and mentions_place(title, place_terms):
            found.append(title)
    return found[:limit]


def object_images(names: list[str], place_terms: list[str], files: list[str] | None = None,
                  limit: int = DEFAULT_CATEGORY_LIMIT, min_width: int = DEFAULT_MIN_WIDTH,
                  min_height: int = DEFAULT_MIN_HEIGHT, allowed_mime=ALLOWED_MIME) -> list[SubjectImage]:
    """Images de l'objet de l'anecdote et de son édifice, dans l'ordre : illustration de l'anecdote, catégorie
    Commons de l'objet ou de l'édifice, recherche Commons qui nomme l'objet ET la commune ou le département."""
    filters = {"min_width": min_width, "min_height": min_height, "allowed_mime": allowed_mime}
    images: list[SubjectImage] = []
    if files:   # choisie par les contributeurs pour illustrer l'anecdote : c'est l'objet lui-même
        images += _images_for_titles([f"File:{file_key(f)}" for f in files], "object", **filters)
    for name in [n for n in names if str(n or "").strip()]:
        for category in focus_categories(name, place_terms):
            print(f"   🎯 Catégorie Commons de l'objet : {category}")
            images += category_images(category, limit, origin="object", **filters)
        if not place_terms:
            continue
        data = _search(f"{name} {place_query(place_terms)} filetype:bitmap", 6, 30)
        pages = sorted((data or {}).get("query", {}).get("pages", []), key=lambda p: p.get("index", 0))
        for page in pages:
            image = _to_image(page, "object", **filters)
            if image and name_matches(image.description, name, place_terms) \
                    and mentions_place(image.description, place_terms):
                images.append(image)
    seen, unique = set(), []
    for img in images:
        if img.key not in seen:
            seen.add(img.key)
            unique.append(img)
    return unique


def focus_image_count(images: list[SubjectImage]) -> int:
    return sum(1 for img in images if img.origin == "object")


def subject_name(source_title: str) -> str:
    """« Abbaye de la Grâce-Dieu (Doubs) » -> « Abbaye de la Grâce-Dieu » (précision d'homonymie retirée)."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(source_title or "")).strip()


def place_terms_of(pick: dict | None) -> list[str]:
    """Commune et département du sujet (Wikidata), pour les requêtes et le contrôle des homonymes."""
    pick = pick or {}
    return [t for t in (str(pick.get("commune") or "").strip(), str(pick.get("department") or "").strip()) if t]


def collect_subject_images(source_title: str | None, commons_category: str | None = None,
                           cfg: dict | None = None, place_terms: list[str] | None = None,
                           documents: bool | None = None, focus: list[str] | None = None,
                           focus_files: list[str] | None = None) -> list[SubjectImage]:
    """Réserve du sujet, sans doublon, dans l'ordre (0) objet précis, (a) article, (b) catégorie Commons,
    (c) documents.

    `focus` : noms de l'objet de l'anecdote et de son édifice, quand ce n'est pas l'article entier (une statue
    dans l'église d'une commune). Leurs images passent en tête (origine « object »), y compris celles de
    l'article et de la catégorie qui les nomment ; les autres images de la commune viennent ensuite.
    `focus_files` : illustration de l'anecdote.

    La catégorie vient de Wikidata (P373) quand elle existe : elle est alors fiable. Sinon elle est devinée
    d'après le nom du sujet, et chaque image doit nommer la commune ou le département (homonymes).
    """
    cfg = cfg or {}
    place_terms = list(place_terms or [])
    focus = [str(n).strip() for n in focus or [] if str(n or "").strip()]
    sizes = {"min_width": int(cfg.get("min_width", DEFAULT_MIN_WIDTH)),
             "min_height": int(cfg.get("min_height", DEFAULT_MIN_HEIGHT)),
             "allowed_mime": set(cfg.get("allowed_mime") or ALLOWED_MIME)}
    name = subject_name(source_title or "")
    found: list[SubjectImage] = []
    steps = []
    if focus or focus_files:
        steps.append(("objet", lambda: object_images(focus, place_terms, focus_files,
                                                     int(cfg.get("category_limit", DEFAULT_CATEGORY_LIMIT)), **sizes)))
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
        # documents d'époque de l'édifice qui contient l'objet, sinon du sujet
        steps.append(("document", lambda: document_images(focus[-1] if focus else name, place_terms,
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
        if focus and label != "objet":   # images de la commune qui montrent l'objet : en tête aussi
            new = [replace(img, origin="object") if any(name_matches(img.description, n, place_terms)
                                                        for n in focus) else img for img in new]
        seen.update(img.key for img in new)
        found.extend(new)
        print(f"   🖼️ {label} : {len(new)} image(s) exploitable(s)")
    if focus or focus_files:
        print(f"   🎯 Images de l'objet ou de l'édifice : {focus_image_count(found)}")
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
