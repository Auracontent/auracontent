"""Mascotte de la chaîne : une épingle jaune expressive (assets/<chaîne>/images/mascotte_<expression>.png).

- Carte : à la fin du zoom, l'expression « curieux » se pose sur le lieu, pointe sur le point, avec un rebond.
- Vidéo : petite mascotte (≈ 150 px) à gauche, sous le bandeau-titre et au-dessus des sous-titres ;
  « curieux » par défaut, « surpris » pendant la phrase de la révélation, « clin » sur la dernière scène.
  Sans ombre portée dans le coin ; l'ombre ne sert que sur la carte.

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


SHADOW_MAX_ALPHA = 90        # ombre portée : ellipse sombre presque transparente (alpha ≈ 28) sous la pointe
SHADOW_BAND = 0.14           # cherchée dans le bas de l'image seulement (bords lissés du contour ailleurs)


def strip_shadow(img: Image.Image) -> Image.Image:
    """Retire l'ombre portée : pixels sombres et presque transparents du bas de la mascotte."""
    img = img.copy()
    box = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
    top = int(box[3] - (box[3] - box[1]) * SHADOW_BAND)
    px = img.load()
    for y in range(top, box[3]):
        for x in range(box[0], box[2]):
            r, g, b, a = px[x, y]
            if 0 < a <= SHADOW_MAX_ALPHA and max(r, g, b) < 60:
                px[x, y] = (r, g, b, 0)
    return img


@functools.lru_cache(maxsize=16)
def load_mascot(path: str, height: int | None = None, shadow: bool = True) -> Image.Image:
    """Image RGBA recadrée sur sa partie visible, à la hauteur demandée. `shadow=False` : sans l'ombre portée
    (mascotte du coin de l'écran ; l'ombre ne sert que posée sur la carte)."""
    with Image.open(path) as img:
        img = img.convert("RGBA")
        if not shadow:
            img = strip_shadow(img)
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


def overlay_png(path: str, height: int, out_dir: str, shadow: bool = False) -> str:
    """PNG à la taille d'affichage, pour le filtre overlay de FFmpeg (pas de mise à l'échelle par image).
    Coin de l'écran : sans ombre portée par défaut."""
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"mascot_{height}_{'ombre' if shadow else 'sans_ombre'}_{os.path.basename(path)}")
    if not os.path.exists(out):
        load_mascot(path, height, shadow).save(out)
    return out


def reveal_window(scene: dict) -> tuple[float, float] | None:
    """(début, fin) en secondes de la phrase de la révélation dans la scène, estimés au prorata des
    caractères prononcés (la voix lit le texte d'un trait). None si la scène ne la contient pas."""
    sentence, text = str(scene.get("reveal_sentence") or ""), str(scene.get("text") or "")
    duration = float(scene.get("duration") or 0)
    start = text.find(sentence) if sentence else -1
    if start < 0 or duration <= 0 or not text:
        return None
    return round(duration * start / len(text), 2), round(duration * (start + len(sentence)) / len(text), 2)


def expression_for(scene: dict, index: int, count: int, cfg: dict, skip: set[int] | None = None) -> str | None:
    """Expression de fond de la mascotte dans le coin pour la scène `index` sur `count` : « clin » sur la
    dernière, « curieux » ailleurs. « Surpris » n'est montré que pendant la phrase de la révélation
    (voir reveal_window), jamais sur une scène entière choisie d'après son rôle.

    None : pas de mascotte dans le coin (scène de la carte, où elle se pose déjà sur le lieu).
    """
    if index in (skip or set()):
        return None
    if index == count - 1:
        return "clin"
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
