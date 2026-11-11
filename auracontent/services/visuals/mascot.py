"""Mascotte de la chaîne : une épingle jaune expressive (assets/<chaîne>/images/mascotte_<expression>.png).

- Carte : à la fin du zoom, l'expression « curieux » se pose sur le lieu, pointe sur le point, avec un rebond.
- Vidéo : petite mascotte (≈ 150 px) à gauche, sous le bandeau-titre et au-dessus des sous-titres ;
  « curieux » par défaut, « surpris » pendant la révélation, « clin » sur la dernière scène.

Réglage : section `mascot` du YAML ; absente = désactivée (autres chaînes). Fichier manquant = pas de
mascotte, avec un avertissement : la vidéo sort comme avant.
"""
from __future__ import annotations

import functools
import math
import os

from config.settings import ASSETS_DIR
from PIL import Image

EXPRESSIONS = ("curieux", "surpris", "clin")
DEFAULT_IMAGES = {name: f"mascotte_{name}.png" for name in EXPRESSIONS}


def mascot_settings(cfg: dict | None) -> dict:
    cfg = dict(cfg or {})
    cfg.setdefault("enabled", False)
    cfg["images"] = {**DEFAULT_IMAGES, **(cfg.get("images") or {})}
    cfg.setdefault("height", 150)          # hauteur à l'écran, en px (vidéo 1080 x 1920)
    cfg.setdefault("x", 40)                # bord gauche ; la droite (x > 930) est couverte par l'interface
    cfg.setdefault("y", None)              # None : juste sous le bandeau-titre (3 lignes au plus)
    cfg.setdefault("gap", 30)
    cfg.setdefault("on_map", True)         # remplace le point jaune de la carte animée
    cfg.setdefault("map_height", 190)
    cfg.setdefault("reveal_roles", ["reveal"])
    return cfg


def mascot_files(cfg: dict, channel_name: str) -> dict[str, str]:
    """{expression: chemin} des fichiers présents ; {} si la mascotte est désactivée."""
    if not cfg.get("enabled"):
        return {}
    folder = ASSETS_DIR / channel_name / "images"
    files = {}
    for name, filename in cfg["images"].items():
        path = folder / filename
        if path.exists():
            files[name] = str(path)
        else:
            print(f"⚠️ Mascotte « {name} » introuvable ({path}) : non affichée.")
    return files


@functools.lru_cache(maxsize=16)
def load_mascot(path: str, height: int | None = None) -> Image.Image:
    """Image RGBA recadrée sur sa partie visible (ombre comprise), à la hauteur demandée."""
    with Image.open(path) as img:
        img = img.convert("RGBA")
        box = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
        img = img.crop(box)
    if height:
        img = img.resize((max(round(img.width * height / img.height), 1), int(height)), Image.LANCZOS)
    return img


def tip_of(img: Image.Image) -> tuple[float, float]:
    """Pointe de l'épingle (pixels) : milieu de la dernière ligne nettement opaque et sombre (contour).

    L'ombre portée, grise et semi-transparente, n'est pas prise pour la pointe.
    """
    alpha, rgb = img.getchannel("A"), img.convert("RGB")
    for y in range(img.height - 1, -1, -1):
        xs = [x for x in range(img.width) if alpha.getpixel((x, y)) > 200 and max(rgb.getpixel((x, y))) < 80]
        if xs:
            return (min(xs) + max(xs)) / 2, float(y)
    return img.width / 2, float(img.height - 1)


def overlay_png(path: str, height: int, out_dir: str) -> str:
    """PNG à la taille d'affichage, pour le filtre overlay de FFmpeg (pas de mise à l'échelle par image)."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"mascot_{height}_{os.path.basename(path)}")
    if not os.path.exists(out):
        load_mascot(path, height).save(out)
    return out


def expression_for(scene: dict, index: int, count: int, cfg: dict, skip: set[int] | None = None) -> str | None:
    """Expression de la mascotte dans le coin pour la scène `index` sur `count`.

    None : pas de mascotte dans le coin (scène de la carte, où elle se pose déjà sur le lieu).
    """
    if index in (skip or set()):
        return None
    if index == count - 1:
        return "clin"
    if str(scene.get("role", "")).lower() in {r.lower() for r in cfg.get("reveal_roles", ["reveal"])}:
        return "surpris"
    return "curieux"


def landing(t: float, height: float) -> tuple[float, float, float, float]:
    """(décalage vertical px, échelle x, échelle y, opacité) à `t` s après le début de l'apparition.

    Chute de 0,28 s, écrasement à l'impact, un petit rebond (0,28 s), puis immobile.
    """
    fall, hop = 0.28, 0.28
    if t < 0:
        return -height, 1.0, 1.0, 0.0
    if t < fall:
        u = t / fall
        return -0.7 * height * (1 - u * u), 1.0, 1.0, min(u * 3, 1.0)
    u = (t - fall) / hop
    squash = math.exp(-6 * (t - fall)) * 0.14
    if squash < 0.005:                       # au repos : taille d'origine, sans redimensionner chaque image
        squash = 0.0
    if u < 1:
        return -0.16 * height * math.sin(math.pi * u), 1 + squash * 0.6, 1 - squash, 1.0
    return 0.0, 1 + squash * 0.6, 1 - squash, 1.0
