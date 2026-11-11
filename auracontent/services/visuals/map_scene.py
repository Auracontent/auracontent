"""Scène de carte animée « où ça se passe » : la France, zoom vers la région, point jaune qui pulse, nom du lieu.

Rendu image par image avec Pillow (vecteurs redessinés à chaque image : net à tous les niveaux de zoom),
encodé par FFmpeg en un .mp4 muet de la durée exacte de la scène. Le Composer le traite comme une vidéo.

Fonds de carte : Natural Earth (domaine public), voir assets/shared/maps/README.md.
Coordonnées : page Wikipédia source (prop=coordinates), sinon géocodage Nominatim du sujet et de sa commune.
Étiquette : le nom du sujet (page source) ou de sa commune, jamais un lieu deviné par le LLM ou le géocodeur.
Repère : la grande ville la plus proche (assets/shared/maps/france_cities.json, Natural Earth).
"""
from __future__ import annotations

import contextlib
import functools
import json
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import ffmpeg
import requests
from PIL import Image, ImageDraw, ImageFont

from auracontent.services.publishing.state_sync import STATE_DIR
from config.settings import ASSETS_DIR

MAPS_DIR = ASSETS_DIR / "shared" / "maps"
FONT_PATH = ASSETS_DIR / "shared" / "fonts" / "Montserrat-Bold.ttf"

# Charte : bleu nuit, frontières claires, un seul accent jaune
SEA = (6, 10, 22)
LAND_OTHER = (18, 27, 48)
LAND_FRANCE = (30, 46, 82)
BORDER = (150, 172, 200)
ACCENT = (255, 212, 0)                      # #FFD400
REGION_FILL_ALPHA = 0.38

# Métropole (Corse comprise) : au-delà, cadrage monde centré sur le territoire
METRO_BBOX = (-5.6, 41.2, 9.8, 51.2)        # lon min, lat min, lon max, lat max

# Nominatim (OpenStreetMap) : https://operations.osmfoundation.org/policies/nominatim/
# Au plus une requête par seconde, agent utilisateur identifié, résultats en cache, attribution affichée,
# service remplaçable sans changer le code (visuals.map_scene.geocoder_url).
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_MIN_INTERVAL = 1.1
GEOCODE_CACHE = STATE_DIR / "geocode_cache.json"   # synchronisé sur Hugging Face avec les historiques
_last_nominatim_call = 0.0


# ==========================================
# CONFIGURATION ET CIBLE
# ==========================================
@dataclass
class MapTarget:
    index: int          # indice de la scène qui reçoit la carte
    lat: float
    lon: float
    label: str          # nom du sujet ou de sa commune, affiché en capitales
    source: str         # "wikipedia" ou "nominatim"
    sublabel: str = ""  # seconde ligne : commune (si l'étiquette est le sujet), sinon la région


def map_settings(visuals_cfg: dict | None) -> dict:
    """Section visuals.map_scene du YAML ; désactivée si absente (autres chaînes)."""
    cfg = dict((visuals_cfg or {}).get("map_scene") or {})
    cfg.setdefault("enabled", False)
    cfg.setdefault("scene_index", 1)
    cfg.setdefault("geocode_fallback", True)
    cfg.setdefault("geocoder_url", NOMINATIM_URL)
    cfg.setdefault("zoom", 3.0)                 # métropole : vue finale 3 fois plus serrée que la France entière
    cfg.setdefault("overseas_view_km", 4500)    # outre-mer : largeur de la vue de départ
    cfg.setdefault("overseas_zoom", 10.0)     # Réunion : ~130 px de large à la fin
    cfg.setdefault("tagline", "")               # accroche de marque sous le nom du lieu (facultative)
    cfg.setdefault("label_max_chars", 26)       # au-delà, l'étiquette prend le nom de la commune
    cfg.setdefault("landmark", True)            # grande ville la plus proche en repère
    cfg.setdefault("landmark_min_population", 100_000)
    cfg.setdefault("landmark_min_population_overseas", 30_000)
    cfg.setdefault("landmark_min_km", 6)        # plus près, c'est la même ville : pas de repère
    return cfg


def _valid_coords(lat, lon) -> tuple[float, float] | None:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
        return None
    return lat, lon


def _read_cache() -> dict:
    try:
        return json.loads(GEOCODE_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cache(cache: dict) -> None:
    try:
        GEOCODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        GEOCODE_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        print(f"⚠️ Cache de géocodage non enregistré : {e}")


def geocode_nominatim(query: str, user_agent: str | None = None,
                      url: str = NOMINATIM_URL) -> tuple[float, float] | None:
    """Géocodage d'un nom de lieu : cache d'abord, sinon une requête (1 requête/s au plus).

    Les échecs sont aussi mis en cache : la même requête n'est jamais renvoyée.
    """
    global _last_nominatim_call
    query = (query or "").strip()
    if not query:
        return None
    key = " ".join(query.lower().split())
    cache = _read_cache()
    if key in cache:
        hit = cache[key]
        return _valid_coords(hit.get("lat"), hit.get("lon")) if hit else None
    agent = user_agent or os.getenv("WIKIMEDIA_CONTACT") or "auraContentPipeline/1.0 (contact non configure)"
    wait = NOMINATIM_MIN_INTERVAL - (time.time() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call = time.time()
    try:
        r = requests.get(url, params={"q": query, "format": "jsonv2", "limit": 1},
                         headers={"User-Agent": agent, "Accept-Language": "fr"}, timeout=15)
        r.raise_for_status()
        hits = r.json()
    except (requests.RequestException, ValueError) as e:
        print(f"⚠️ Nominatim indisponible ({query}) : {e}")
        return None                                     # erreur réseau : pas de cache, on réessaiera
    coords = _valid_coords(hits[0].get("lat"), hits[0].get("lon")) if hits else None
    cache[key] = {"lat": coords[0], "lon": coords[1]} if coords else None
    _write_cache(cache)
    return coords


def _subject_name(title: str) -> str:
    """« Abbaye de X (Doubs) » -> « Abbaye de X » (précision d'homonymie retirée)."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(title or "")).strip()


def map_labels(script: dict, scenes: list[dict], cfg: dict) -> tuple[str, str]:
    """(étiquette, seconde ligne) : nom du sujet, ou de sa commune s'il est trop long.

    Jamais le lieu d'une autre scène ni celui que renvoie le géocodeur. Anciens scripts sans page source :
    lieu de la scène 1 (le sujet, par construction du prompt).
    """
    pick = script.get("pick") or {}
    subject = _subject_name(pick.get("source_title") or "")
    commune = str(pick.get("commune") or "").strip()
    region = str(pick.get("region") or "").split("(")[0].strip()
    max_chars = int(cfg.get("label_max_chars", 26))
    if subject and (len(subject) <= max_chars or not commune):
        return subject, (commune if commune and commune.lower() not in subject.lower() else "")
    if commune:
        return commune, ""
    first = (scenes[0] if scenes else {}).get("location_name") or ""
    return str(first).strip() or region, ""


def pick_map_target(script: dict, scenes: list[dict], cfg: dict, geocoder=None) -> MapTarget | None:
    """Scène et coordonnées de la carte, ou None (pas de carte : la scène garde son visuel habituel)."""
    if not cfg.get("enabled"):
        return None
    if geocoder is None:
        geocoder = functools.partial(geocode_nominatim, url=cfg.get("geocoder_url") or NOMINATIM_URL)
    idx = int(cfg.get("scene_index", 1))
    if not 0 <= idx < len(scenes):
        return None
    scene = scenes[idx]
    if scene.get("role") == "cta" or scene.get("reuse_previous_asset"):
        return None

    first = scenes[0] if scenes else {}
    pick = script.get("pick") or {}
    label, sublabel = map_labels(script, scenes, cfg)

    coords = _valid_coords(pick.get("lat"), pick.get("lon"))
    source = "wikipedia"
    if coords is None and cfg.get("geocode_fallback", True):
        # le sujet et sa commune d'abord, puis la commune seule, puis le lieu de la scène 1 (anciens scripts)
        subject, commune = _subject_name(pick.get("source_title") or ""), str(pick.get("commune") or "").strip()
        queries = [", ".join(x for x in (subject, commune, "France") if x) if subject else "",
                   f"{commune}, France" if commune else "",
                   ", ".join(x for x in (first.get("location_name"), first.get("location_country")) if x)]
        for query in dict.fromkeys(q for q in queries if q):
            coords = geocoder(query)
            if coords:
                break
        source = "nominatim"
    if coords is None:
        print("🗺️ Pas de coordonnées pour le lieu : pas de carte, visuel habituel.")
        return None
    return MapTarget(index=idx, lat=coords[0], lon=coords[1], label=label, source=source, sublabel=sublabel)


# ==========================================
# DONNÉES GÉOGRAPHIQUES
# ==========================================
def _rings(geometry: dict) -> list[list[list[float]]]:
    """Anneaux extérieurs et trous, à plat (le remplissage pair-impair n'est pas nécessaire ici)."""
    if geometry["type"] == "Polygon":
        return list(geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return [ring for poly in geometry["coordinates"] for ring in poly]
    return []


def _polygons(geometry: dict) -> list[list[list[list[float]]]]:
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


@functools.lru_cache(maxsize=1)
def load_layers(maps_dir: str = str(MAPS_DIR)) -> dict:
    def read(name):
        return json.loads(Path(maps_dir, name).read_text(encoding="utf-8"))["features"]

    return {"regions": read("france_regions.geojson"), "countries": read("countries.geojson")}


@functools.lru_cache(maxsize=1)
def load_cities(maps_dir: str = str(MAPS_DIR)) -> list[dict]:
    """Villes françaises (Natural Earth, domaine public) : [{name, lat, lon, pop}]."""
    try:
        return json.loads(Path(maps_dir, "france_cities.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance orthodromique (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(min(a, 1.0)))


def _point_in_ring(lon: float, lat: float, ring) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _contains(geometry: dict, lon: float, lat: float) -> bool:
    for poly in _polygons(geometry):
        if poly and _point_in_ring(lon, lat, poly[0]) and not any(_point_in_ring(lon, lat, h) for h in poly[1:]):
            return True
    return False


def _distance_km(lat: float, lon: float, geometry: dict) -> float:
    """Distance approchée du point au sommet le plus proche du contour (suffisant à quelques km près)."""
    kx = math.cos(math.radians(lat))
    best = float("inf")
    for ring in _rings(geometry):
        for x, y in ring:
            d = ((x - lon) * kx) ** 2 + (y - lat) ** 2
            if d < best:
                best = d
    return math.sqrt(best) * 111.0


def find_region(lat: float, lon: float, layers: dict | None = None, max_km: float = 25.0) -> dict | None:
    """Région française (ou territoire d'outre-mer) qui contient le point.

    Si le point tombe juste en mer (port, golfe : le trait de côte est simplifié), on retient la région
    la plus proche à moins de `max_km`.
    """
    layers = layers or load_layers()
    candidates = layers["regions"] + [f for f in layers["countries"] if f["properties"].get("sovereign") == "France"]
    for f in candidates:
        if _contains(f["geometry"], lon, lat):
            return f
    nearest = min(candidates, key=lambda f: _distance_km(lat, lon, f["geometry"]), default=None)
    if nearest and _distance_km(lat, lon, nearest["geometry"]) <= max_km:
        return nearest
    return None


def is_metropolitan(lat: float, lon: float) -> bool:
    lon0, lat0, lon1, lat1 = METRO_BBOX
    return lon0 <= lon <= lon1 and lat0 <= lat <= lat1


# ==========================================
# CAMÉRA
# ==========================================
@dataclass
class Frame:
    """Vue : point du monde (lon, lat) placé au point d'ancrage de l'écran, à `scale` pixels par degré."""
    lon: float
    lat: float
    scale: float


class MapRenderer:
    # Le point et l'étiquette restent entre le bandeau-titre (y ≈ 230-610) et les sous-titres (y ≈ 1200),
    # et à gauche de x = 930 (interface YouTube / TikTok)
    ANCHOR = (465, 860)
    OVERVIEW_BOX = (50, 560, 900, 1330)       # la France entière tient dans ce cadre au départ

    def __init__(self, lat: float, lon: float, label: str, cfg: dict | None = None,
                 width: int = 1080, height: int = 1920, fps: int = 30, supersample: int = 2,
                 sublabel: str = ""):
        cfg = map_settings({"map_scene": cfg or {}})
        self.cfg = cfg
        self.lat, self.lon = lat, lon
        self.label = (label or "").strip().upper()
        self.sublabel = (sublabel or "").strip().upper()
        self.width, self.height, self.fps = width, height, fps
        self.ss = supersample
        self.layers = load_layers()
        self.region = find_region(lat, lon, self.layers)
        self.region_name = (self.region or {}).get("properties", {}).get("name", "")
        self.metro = is_metropolitan(lat, lon)

        # projection équirectangulaire locale : longitude ramenée près du centre (antiméridien)
        self.ref_lon = 2.5 if self.metro else lon
        self.ref_lat = 46.5 if self.metro else lat
        self.kx = math.cos(math.radians(self.ref_lat))

        sx = width / 1080
        self.anchor = (self.ANCHOR[0] * sx, self.ANCHOR[1] * height / 1920)
        if self.metro:
            box = [v * sx if i % 2 == 0 else v * height / 1920 for i, v in enumerate(self.OVERVIEW_BOX)]
            (x0, y0), (x1, y1) = self._xy(METRO_BBOX[0], METRO_BBOX[3]), self._xy(METRO_BBOX[2], METRO_BBOX[1])
            scale0 = min((box[2] - box[0]) / (x1 - x0), (box[3] - box[1]) / (y1 - y0))
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            # point du monde au centre du cadre de départ, exprimé par rapport à l'ancrage
            ox = cx - ((box[0] + box[2]) / 2 - self.anchor[0]) / scale0
            oy = cy - ((box[1] + box[3]) / 2 - self.anchor[1]) / scale0
            self.start = Frame(ox, oy, scale0)
            self.end = Frame(*self._xy(lon, lat), scale0 * float(cfg["zoom"]))
        else:
            deg = float(cfg["overseas_view_km"]) / 111.0
            scale0 = (self.OVERVIEW_BOX[2] - self.OVERVIEW_BOX[0]) * sx / deg
            px, py = self._xy(lon, lat)
            self.start = Frame(px, py, scale0)
            self.end = Frame(px, py, scale0 * float(cfg["overseas_zoom"]))

        self._prepare_rings()
        self.font_label = self._fit_font(self.label, 84, int(820 * sx))
        self.font_region = ImageFont.truetype(str(FONT_PATH), int(42 * sx))
        self.tagline = str(cfg.get("tagline") or "").strip().upper()
        self.font_tag = ImageFont.truetype(str(FONT_PATH), int(40 * sx))
        self.font_city = ImageFont.truetype(str(FONT_PATH), int(38 * sx))
        self.label_below = self._choose_label_side()
        self.landmark = self._choose_landmark() if cfg.get("landmark", True) else None

    # --- projection ---
    def _wrap(self, lon: float) -> float:
        return (lon - self.ref_lon + 180) % 360 - 180

    def _xy(self, lon: float, lat: float) -> tuple[float, float]:
        """Coordonnées « monde » projetées (degrés, y vers le bas)."""
        return self._wrap(lon) * self.kx, -lat

    def _ring_shift(self, ring) -> float:
        """Décalage de 360° appliqué à tout l'anneau (évite de couper un polygone à l'antiméridien)."""
        mean = sum(p[0] for p in ring) / len(ring)
        return self._wrap(mean) - (mean - self.ref_lon)

    @staticmethod
    def _ease(t: float) -> float:
        """Décélération seule (ease-out) : la caméra bouge dès la première image, puis se pose."""
        t = min(max(t, 0.0), 1.0)
        return 1 - (1 - t) ** 3

    def frame_at(self, progress: float) -> Frame:
        """Zoom : position interpolée linéairement, échelle géométriquement (vitesse perçue constante)."""
        e = self._ease(progress)
        s = self.start.scale * (self.end.scale / self.start.scale) ** e
        return Frame(self.start.lon + (self.end.lon - self.start.lon) * e,
                     self.start.lat + (self.end.lat - self.start.lat) * e, s)

    def to_screen(self, frame: Frame, lon: float, lat: float) -> tuple[float, float]:
        x, y = self._xy(lon, lat)
        return self.anchor[0] + (x - frame.lon) * frame.scale, self.anchor[1] + (y - frame.lat) * frame.scale

    # --- dessin ---
    def _fit_font(self, text: str, size: int, max_width: int):
        size = max(size, 30)
        while size > 30:
            font = ImageFont.truetype(str(FONT_PATH), size)
            if not text or font.getlength(text) <= max_width:
                return font
            size -= 4
        return ImageFont.truetype(str(FONT_PATH), size)

    def _prepare_rings(self) -> None:
        """Projette chaque anneau une seule fois et ne garde que ceux visibles pendant l'animation.

        La vue de départ est la plus large (on ne fait que zoomer) : tout ce qui est hors de cette vue
        n'apparaîtra jamais.
        """
        s0, (ax, ay) = self.start.scale, self.anchor
        margin = 0.15 * max(self.width, self.height) / s0
        view = (self.start.lon - ax / s0 - margin, self.start.lat - ay / s0 - margin,
                self.start.lon + (self.width - ax) / s0 + margin, self.start.lat + (self.height - ay) / s0 + margin)

        def prepared(features):
            out = []
            for feat in features:
                rings = []
                for ring in _rings(feat["geometry"]):
                    if len(ring) < 3:
                        continue
                    shift = self._ring_shift(ring)
                    pts = [((x - self.ref_lon + shift) * self.kx, -y) for x, y in ring]
                    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    if bbox[2] < view[0] or bbox[0] > view[2] or bbox[3] < view[1] or bbox[1] > view[3]:
                        continue
                    rings.append((pts, bbox))
                if rings:
                    out.append(rings)
            return out

        self.countries = prepared(self.layers["countries"])
        self.regions = prepared(self.layers["regions"])
        self.highlight = prepared([self.region]) if self.region else []

    def _screen_rings(self, prepared, frame: Frame, f: float):
        """Anneaux visibles dans `frame`, en pixels (échelle de suréchantillonnage `f`)."""
        s, ax, ay = frame.scale, self.anchor[0], self.anchor[1]
        x0, y0 = frame.lon - ax / s, frame.lat - ay / s
        x1, y1 = frame.lon + (self.width - ax) / s, frame.lat + (self.height - ay) / s
        k, ox, oy = s * f, (ax - frame.lon * s) * f, (ay - frame.lat * s) * f
        for rings in prepared:
            for pts, (bx0, by0, bx1, by1) in rings:
                if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                    continue
                yield [(x * k + ox, y * k + oy) for x, y in pts]

    def draw_map(self, frame: Frame) -> Image.Image:
        f = self.ss
        view = (self.width * f, self.height * f)
        img = Image.new("RGB", view, SEA)
        draw = ImageDraw.Draw(img)
        for pts in self._screen_rings(self.countries, frame, f):
            draw.polygon(pts, fill=LAND_OTHER)
        for pts in self._screen_rings(self.regions, frame, f):
            draw.polygon(pts, fill=LAND_FRANCE)

        if self.highlight:   # région en jaune translucide : calque à part, sans double opacité
            mask = Image.new("L", view, 0)
            mdraw = ImageDraw.Draw(mask)
            for pts in self._screen_rings(self.highlight, frame, f):
                mdraw.polygon(pts, fill=int(255 * REGION_FILL_ALPHA))
            img.paste(ACCENT, (0, 0, view[0], view[1]), mask)

        # frontières claires par-dessus tout (masquent aussi les petits écarts entre couches)
        width = max(int(1.2 * f), 1)
        for prepared, color in ((self.countries, tuple(int(c * 0.55) for c in BORDER)), (self.regions, BORDER)):
            for pts in self._screen_rings(prepared, frame, f):
                draw.line([*pts, pts[0]], fill=color, width=width)
        return img.reduce(f) if f > 1 else img

    def _draw_marker(self, img: Image.Image, t_since: float, pos: tuple[float, float]) -> None:
        """Point jaune contouré de noir + anneau qui s'élargit et s'efface (une pulsation par seconde)."""
        x, y = pos
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        sx = self.width / 1080
        pop = min(t_since / 0.25, 1.0)                    # apparition rapide
        r = 20 * sx * (0.6 + 0.4 * pop)
        for k in (0.0, 0.5):                              # deux anneaux décalés d'une demi-période
            phase = ((t_since + k) % 1.0)
            ring_r = r + phase * 70 * sx
            alpha = int(230 * (1 - phase) * pop)
            d.ellipse([x - ring_r, y - ring_r, x + ring_r, y + ring_r], outline=(*ACCENT, alpha),
                      width=max(int(6 * sx), 2))
        d.ellipse([x - r - 5 * sx, y - r - 5 * sx, x + r + 5 * sx, y + r + 5 * sx], fill=(0, 0, 0, int(255 * pop)))
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*ACCENT, int(255 * pop)))
        img.paste(overlay, (0, 0), overlay)

    def _label_lines(self):
        """[(texte, police, accent)] : nom du lieu, région, puis accroche de marque (noir sur jaune)."""
        lines = [(self.label, self.font_label, False)] if self.label else []
        second = self.sublabel or self.region_name.upper()
        if lines and second and second not in self.label:
            lines.append((second, self.font_region, False))
        if self.tagline:
            lines.append((self.tagline, self.font_tag, True))
        return lines

    @staticmethod
    def _line_height(font, accent: bool) -> float:
        return font.size * (1.6 if accent else 1.18)   # l'accroche a un cartouche : un peu plus d'air

    def _label_box(self, below: bool, pos: tuple[float, float] | None = None) -> tuple[float, float, float, float]:
        """Cadre de l'étiquette (sous le point `pos` ou au-dessus), contenu dans la zone sûre."""
        px, py = pos or self.anchor
        sx = self.width / 1080
        lines = self._label_lines()
        height = sum(self._line_height(font, accent) for _, font, accent in lines)
        width = max((font.getlength(text) + (font.size * 0.6 if accent else 0) for text, font, accent in lines),
                    default=0)
        x0 = min(max(px - width / 2, 40 * sx), 930 * sx - width)
        y0 = py + 70 * sx if below else py - 60 * sx - height
        return x0, y0, x0 + width, y0 + height

    def _choose_label_side(self) -> bool:
        """Sous le point par défaut ; au-dessus si l'étiquette masquerait davantage le territoire.

        Utile outre-mer : à Saint-Denis (nord de La Réunion), l'île est juste sous le point.
        """
        boxes = [pts for pts in self._screen_rings(self.highlight, self.end, 1)]
        if not boxes:
            return True

        def covered(box):
            x0, y0, x1, y1 = box
            total = 0.0
            for pts in boxes:
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                w = min(x1, max(xs)) - max(x0, min(xs))
                h = min(y1, max(ys)) - max(y0, min(ys))
                total += max(w, 0) * max(h, 0)
            return total

        below, above = covered(self._label_box(True)), covered(self._label_box(False))
        # au-dessus, l'étiquette ne doit pas remonter sous le bandeau-titre (y ≈ 610)
        return below <= above or self._label_box(False)[1] < 620 * self.height / 1920

    def _draw_label(self, img: Image.Image, alpha: float, pos: tuple[float, float]) -> None:
        lines = self._label_lines()
        if not lines or alpha <= 0:
            return
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        a = int(255 * alpha)
        x0, y, x1, _ = self._label_box(self.label_below, pos)
        for text, font, accent in lines:
            x = x0 + (x1 - x0 - font.getlength(text)) / 2
            if accent:   # même style que la chute du bandeau-titre : noir sur jaune
                pad = font.size * 0.3
                top = y + font.size * 0.25
                d.rectangle([x - pad, top - pad * 0.6, x + font.getlength(text) + pad, top + font.size + pad * 0.6],
                            fill=(*ACCENT, a))
                d.text((x, top), text, font=font, fill=(0, 0, 0, a))
            else:
                d.text((x, y), text, font=font, fill=(255, 255, 255, a),
                       stroke_width=max(int(font.size * 0.08), 3), stroke_fill=(0, 0, 0, a))
            y += self._line_height(font, accent)
        img.paste(overlay, (0, 0), overlay)

    # --- repère : grande ville la plus proche ---
    SAFE_BOX = (40, 620, 930, 1400)            # entre le bandeau-titre et les sous-titres, à gauche de x = 930
    CITY_DOT = 10
    MARKER_CLEARANCE = 45                      # point jaune et son contour (les anneaux translucides passent dessous)

    def _city_label_boxes(self, x: float, y: float, name: str):
        """Positions possibles du nom à côté du point de la ville : à droite, à gauche, au-dessus, dessous."""
        sx = self.width / 1080
        w, h, gap = self.font_city.getlength(name), self.font_city.size * 1.15, 18 * sx
        yield (x + gap, y - h / 2, x + gap + w, y + h / 2)
        yield (x - gap - w, y - h / 2, x - gap, y + h / 2)
        yield (x - w / 2, y - gap - h, x + w / 2, y - gap)
        yield (x - w / 2, y + gap, x + w / 2, y + gap + h)

    def _choose_landmark(self) -> dict | None:
        """Ville la plus proche, assez grande, visible à la fin du zoom sans gêner le point ni l'étiquette.

        Retourne {name, lat, lon, box} ou None (aucune ville ne tient dans la zone sûre).
        """
        min_pop = self.cfg["landmark_min_population" if self.metro else "landmark_min_population_overseas"]
        sx, sy = self.width / 1080, self.height / 1920
        safe = (self.SAFE_BOX[0] * sx, self.SAFE_BOX[1] * sy, self.SAFE_BOX[2] * sx, self.SAFE_BOX[3] * sy)
        label_box = self._label_box(self.label_below, self.to_screen(self.end, self.lon, self.lat))
        mx, my = self.to_screen(self.end, self.lon, self.lat)

        def overlaps(a, b):
            return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

        cities = sorted((c for c in load_cities() if c.get("pop", 0) >= min_pop),
                        key=lambda c: distance_km(self.lat, self.lon, c["lat"], c["lon"]))
        for city in cities:
            if distance_km(self.lat, self.lon, city["lat"], city["lon"]) < float(self.cfg["landmark_min_km"]):
                return None                    # le sujet est dans la grande ville : son nom suffit
            x, y = self.to_screen(self.end, city["lon"], city["lat"])
            if not (safe[0] <= x <= safe[2] and safe[1] <= y <= safe[3]):
                continue                       # hors champ à la fin du zoom : ville suivante
            if math.hypot(x - mx, y - my) < self.MARKER_CLEARANCE * sx:
                continue                       # collée au point jaune : illisible
            dot = (x - self.CITY_DOT * sx, y - self.CITY_DOT * sx, x + self.CITY_DOT * sx, y + self.CITY_DOT * sx)
            if overlaps(dot, label_box):
                continue
            name = city["name"].upper()
            for box in self._city_label_boxes(x, y, name):
                inside = safe[0] <= box[0] and box[2] <= safe[2] and safe[1] <= box[1] and box[3] <= safe[3]
                clear = not overlaps(box, label_box) and not overlaps(
                    box, (mx - self.MARKER_CLEARANCE * sx, my - self.MARKER_CLEARANCE * sx,
                          mx + self.MARKER_CLEARANCE * sx, my + self.MARKER_CLEARANCE * sx))
                if inside and clear:
                    return {"name": name, "lat": city["lat"], "lon": city["lon"], "offset": (box[0] - x, box[1] - y)}
        return None

    def _draw_landmark(self, img: Image.Image, frame: Frame, alpha: float) -> None:
        """Point blanc et nom de la ville, qui suivent la carte pendant le zoom."""
        if not self.landmark or alpha <= 0:
            return
        x, y = self.to_screen(frame, self.landmark["lon"], self.landmark["lat"])
        if not (-200 <= x <= self.width + 200 and -200 <= y <= self.height + 200):
            return
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        a, r, sx = int(255 * alpha), self.CITY_DOT * self.width / 1080, self.width / 1080
        d.ellipse([x - r - 3 * sx, y - r - 3 * sx, x + r + 3 * sx, y + r + 3 * sx], fill=(0, 0, 0, a))
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, a))
        ox, oy = self.landmark["offset"]
        d.text((x + ox, y + oy), self.landmark["name"], font=self.font_city, fill=(255, 255, 255, a),
               stroke_width=max(int(self.font_city.size * 0.08), 3), stroke_fill=(0, 0, 0, a))
        img.paste(overlay, (0, 0), overlay)

    @staticmethod
    def zoom_end(duration: float) -> float:
        return 0.62 * duration

    def camera(self, t: float, duration: float) -> Frame:
        """Vue à l'instant t : le zoom part de la première image (aucun plan fixe au début)."""
        return self.frame_at(t / max(self.zoom_end(duration), 1e-6))

    def render_frame(self, t: float, duration: float) -> Image.Image:
        """Déroulé : le zoom commence dès la première image et finit à 62 % ; le point qui pulse et le nom
        du lieu apparaissent juste avant la fin du zoom. Le repère (grande ville) apparaît dès le tiers.
        """
        zoom_end = self.zoom_end(duration)
        frame = self.camera(t, duration)
        img = self.draw_map(frame)
        landmark_start = 0.3 * duration
        if t >= landmark_start:
            self._draw_landmark(img, frame, min((t - landmark_start) / (0.1 * duration), 1.0))
        marker_start = zoom_end - 0.15 * duration
        if t >= marker_start:
            pos = self.to_screen(frame, self.lon, self.lat)
            self._draw_marker(img, t - marker_start, pos)
            self._draw_label(img, min((t - zoom_end + 0.1 * duration) / (0.12 * duration), 1.0), pos)
        return img


# ==========================================
# ENCODAGE
# ==========================================
def frame_count(duration: float, fps: int) -> int:
    """Nombre d'images couvrant la durée (arrondi au-dessus : le Composer ne doit jamais boucler la carte)."""
    return max(math.ceil(duration * fps - 1e-6), 1)


def render_map_scene(target: MapTarget, duration: float, output_path: str, cfg: dict | None = None,
                     width: int = 1080, height: int = 1920, fps: int = 30) -> bool:
    """Écrit un .mp4 muet de `duration` secondes. Retourne False (sans lever) en cas d'échec."""
    started = time.time()
    try:
        renderer = MapRenderer(target.lat, target.lon, target.label, cfg, width=width, height=height, fps=fps,
                               sublabel=target.sublabel)
        n = frame_count(duration, fps)
        process = (
            ffmpeg.input("pipe:", format="rawvideo", pix_fmt="rgb24", s=f"{width}x{height}", r=fps)
            .output(output_path, vcodec="libx264", pix_fmt="yuv420p", crf=18, preset="veryfast",
                    r=fps, frames=n, movflags="+faststart")
            .overwrite_output()
            .run_async(pipe_stdin=True, quiet=True)
        )
        try:
            for i in range(n):
                process.stdin.write(renderer.render_frame(i / fps, duration).tobytes())
        finally:
            process.stdin.close()
            code = process.wait()
        if code != 0 or not os.path.exists(output_path):
            raise RuntimeError(f"ffmpeg a échoué (code {code})")
        print(f"🗺️ Carte : {target.label or '?'} ({target.lat:.4f}, {target.lon:.4f}, source {target.source}, "
              f"région {renderer.region_name or 'inconnue'}, repère "
              f"{(renderer.landmark or {}).get('name', 'aucun')}) — {n} images en {time.time() - started:.1f} s")
        return True
    except Exception as e:
        print(f"⚠️ Carte animée impossible ({e}) : la scène garde son visuel habituel.")
        with contextlib.suppress(OSError):
            os.remove(output_path)
        return False
