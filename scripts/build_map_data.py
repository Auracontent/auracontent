"""Construit les fonds de carte de assets/shared/maps/ à partir de Natural Earth (domaine public).

À lancer seulement pour régénérer les fichiers versionnés (shapely n'est pas une dépendance du pipeline) :

    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson
    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson
    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson
    uv run --with shapely python -m scripts.build_map_data <dossier des deux fichiers>

Sorties :
- france_regions.geojson : 13 régions métropolitaines + 5 DROM, départements fusionnés par région ;
- countries.geojson      : tous les pays (sauf la France, dessinée par ses régions), pour le contexte ;
- france_cities.json     : villes françaises de plus de 30 000 habitants (agglomération), repères de la carte ;
- france_prefectures.json: préfectures (chefs-lieux des départements et collectivités), repère de secours.

Les deux derniers fichiers ne demandent pas shapely :
    python -m scripts.build_map_data --cities <dossier>
    python -m scripts.build_map_data --prefectures      # interroge Wikidata (CC0), réseau nécessaire
"""
import json
import sys
from pathlib import Path

try:   # shapely ne sert qu'aux fonds de carte : --cities s'en passe
    from shapely.geometry import MultiPolygon, mapping, shape
    from shapely.ops import unary_union
except ImportError:
    MultiPolygon = mapping = shape = unary_union = None


OUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "shared" / "maps"
SIMPLIFY_DEG = 0.004       # ~400 m : invisible même au zoom maximal de la carte (France et voisins)
SIMPLIFY_WORLD_DEG = 0.03  # ~3 km : reste du monde, vu seulement en cadrage large (outre-mer)
ROUND_DIGITS = 4
MIN_FAR_ISLAND_DEG2 = 0.02 # ~200 km² : îlots lointains supprimés (sauf territoires français)
EUROPE_BBOX = (-10.0, 36.0, 16.0, 56.0)   # lon min, lat min, lon max, lat max autour de la France


def _rounded(geom, tolerance: float = SIMPLIFY_DEG, digits: int = ROUND_DIGITS) -> dict:
    def rnd(coords):
        if isinstance(coords[0], (int, float)):
            return [round(coords[0], digits), round(coords[1], digits)]
        return [rnd(c) for c in coords]

    g = mapping(geom.simplify(tolerance, preserve_topology=True))
    return {"type": g["type"], "coordinates": rnd(g["coordinates"])}


def _country_geometry(geom, keep_small: bool = False) -> dict:
    """Détail fin pour les polygones proches de la France, simplification forte ailleurs (fichier léger).

    Décision polygone par polygone : la Russie continentale est grossière, Kaliningrad reste fin.
    """
    parts = list(geom.geoms) if isinstance(geom, MultiPolygon) else [geom]
    kept = []
    for part in parts:
        lon0, lat0, lon1, lat1 = part.bounds
        near = lon0 < EUROPE_BBOX[2] and lon1 > EUROPE_BBOX[0] and lat0 < EUROPE_BBOX[3] and lat1 > EUROPE_BBOX[1]
        if not near and not keep_small and part.area < MIN_FAR_ISLAND_DEG2:
            continue                                                 # îlot lointain : invisible en vue large
        simplified = part.simplify(SIMPLIFY_DEG if near else SIMPLIFY_WORLD_DEG, preserve_topology=True)
        kept.append(part if simplified.is_empty else simplified)   # petites îles : géométrie d'origine
    if not kept:
        kept = [max(parts, key=lambda g: g.area)]
    merged = kept[0] if len(kept) == 1 else MultiPolygon(
        [p for k in kept for p in (k.geoms if isinstance(k, MultiPolygon) else [k])])
    return _rounded(merged, tolerance=0)


def _write(name: str, features: list[dict]) -> None:
    path = OUT_DIR / name
    path.write_text(json.dumps({"type": "FeatureCollection", "features": features},
                               ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{path} : {len(features)} entités, {path.stat().st_size / 1e6:.2f} Mo")


MIN_CITY_POP = 30_000         # le seuil « grande ville » est appliqué au rendu (visuals.map_scene)
# Natural Earth abrège ou écorche quelques noms : on rétablit l'orthographe affichée à l'écran
CITY_NAMES = {"St.-Denis": "Saint-Denis", "St.-Brieuc": "Saint-Brieuc", "St.-Benoit": "Saint-Benoît",
              "Poitier": "Poitiers", "Basse-terre": "Basse-Terre", "Brive": "Brive-la-Gaillarde"}


def build_cities(src: Path) -> None:
    places = json.loads((src / "ne_10m_populated_places_simple.geojson").read_text(encoding="utf-8"))
    cities = []
    for f in places["features"]:
        p = f["properties"]
        if "FRA" not in (p.get("adm0_a3"), p.get("sov_a3")) or (p.get("pop_max") or 0) < MIN_CITY_POP:
            continue
        name = CITY_NAMES.get(p["name"], p["name"])
        cities.append({"name": name, "lat": round(p["latitude"], 4), "lon": round(p["longitude"], 4),
                       "pop": int(p["pop_max"])})
    cities.sort(key=lambda c: -c["pop"])
    path = OUT_DIR / "france_cities.json"
    lines = ",\n".join(json.dumps(c, ensure_ascii=False) for c in cities)   # une ville par ligne : diff lisible
    path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")
    print(f"{path} : {len(cities)} villes")


WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
# Chefs-lieux en vigueur (ni énoncé terminé, ni rang déprécié) des entités qui ont un code de département
PREFECTURES_QUERY = """SELECT ?code ?depLabel ?capLabel ?rank (SAMPLE(?coord) AS ?c) WHERE {
  ?dep wdt:P2586 ?code .
  ?dep p:P36 ?st . ?st ps:P36 ?cap ; wikibase:rank ?rank .
  FILTER(?rank != wikibase:DeprecatedRank)
  FILTER NOT EXISTS { ?st pq:P582 ?end }
  FILTER NOT EXISTS { ?dep wdt:P576 ?gone }
  ?cap wdt:P625 ?coord .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "fr". }
} GROUP BY ?code ?depLabel ?capLabel ?rank"""


def build_prefectures() -> None:
    import os
    import re

    import requests

    agent = f"AuraContentMapData/1.0 ({os.getenv('WIKIMEDIA_CONTACT', 'contact non configuré')})"
    r = requests.get(WIKIDATA_SPARQL, params={"query": PREFECTURES_QUERY}, timeout=120,
                     headers={"Accept": "application/sparql-results+json", "User-Agent": agent})
    r.raise_for_status()
    by_code: dict[str, list[dict]] = {}
    for b in r.json()["results"]["bindings"]:
        lon, lat = map(float, re.findall(r"-?\d+(?:\.\d+)?", b["c"]["value"])[:2])
        by_code.setdefault(b["code"]["value"], []).append({
            "name": b["capLabel"]["value"], "department": b["depLabel"]["value"], "code": b["code"]["value"],
            "lat": round(lat, 4), "lon": round(lon, 4), "preferred": b["rank"]["value"].endswith("PreferredRank")})
    prefectures = []
    for code in sorted(by_code):
        rows = by_code[code]
        rows = [x for x in rows if x["preferred"]] or rows      # rang « préféré » quand il existe (Rhône : Lyon)
        for x in rows:
            x.pop("preferred")
            prefectures.append(x)
    path = OUT_DIR / "france_prefectures.json"
    lines = ",\n".join(json.dumps(x, ensure_ascii=False) for x in prefectures)
    path.write_text(f"[\n{lines}\n]\n", encoding="utf-8")
    print(f"{path} : {len(prefectures)} préfectures ({len(by_code)} départements et collectivités)")


def build(src: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    admin1 = json.loads((src / "ne_10m_admin_1_states_provinces.geojson").read_text(encoding="utf-8"))
    by_region: dict[str, list] = {}
    for f in admin1["features"]:
        p = f["properties"]
        if p.get("adm0_a3") == "FRA":
            by_region.setdefault(p["region"].strip(), []).append(shape(f["geometry"]))
    regions = [
        {"type": "Feature", "properties": {"name": name}, "geometry": _rounded(unary_union(geoms))}
        for name, geoms in sorted(by_region.items())
    ]
    _write("france_regions.geojson", regions)

    admin0 = json.loads((src / "ne_10m_admin_0_countries.geojson").read_text(encoding="utf-8"))
    countries = []
    for f in admin0["features"]:
        p = f["properties"]
        if p.get("ADM0_A3") == "FRA":
            continue
        countries.append({
            "type": "Feature",
            "properties": {"name": p.get("NAME_FR") or p.get("NAME"), "iso": p.get("ADM0_A3"),
                           "sovereign": p.get("SOVEREIGNT")},
            # territoires français d'outre-mer (COM) : on garde toutes leurs îles, même minuscules
            "geometry": _country_geometry(shape(f["geometry"]), keep_small=p.get("SOVEREIGNT") == "France"),
        })
    _write("countries.geojson", countries)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = Path(args[0] if args else ".")
    if "--prefectures" in sys.argv[1:]:
        build_prefectures()
    elif "--cities" in sys.argv[1:]:
        build_cities(folder)
    else:
        build(folder)
        build_cities(folder)
