"""Objets du quotidien dessinés par le code, dans le style « trait à la main » de Capital Simple.

Chaque objet est une image RGBA (fond transparent) : contour d'encre légèrement tremblé, aplats de la charte.
Les images sont générées une fois puis mises en cache dans un dossier (PNG), et utilisées comme calques
« image » du moteur linework (chemin absolu). Aucune marque réelle : les applis sont des pictogrammes génériques.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

INK, TURQUOISE, GOLD, GRAY, PAPER = "#1A1A1A", "#0E9F8E", "#E0A526", "#454950", "#F7F3EA"
CORAL, PLUM, PALE = "#E5735C", "#6C5BA8", "#FFFDF7"
FONTS = Path(__file__).resolve().parents[4] / "assets" / "finance" / "fonts"
W = 8                     # épaisseur de trait (px, à la taille de dessin)


def _rng(seed: str) -> random.Random:
    return random.Random(seed)


def _wob(points, seed: str, amp: float = 2.2):
    r = _rng(seed)
    return [(x + r.uniform(-amp, amp), y + r.uniform(-amp, amp)) for x, y in points]


def _poly(d: ImageDraw.ImageDraw, pts, seed: str, fill=None, width: int = W, close: bool = True):
    pts = _wob(pts, seed)
    if fill:
        d.polygon(pts, fill=fill)
    line = pts + [pts[0]] if close else pts
    d.line(line, fill=INK, width=width, joint="curve")


def _rounded(d, box, r, seed, fill=None, width=W):
    x0, y0, x1, y1 = box
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for k in range(7):
            a = math.radians(a0 + k * 15)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    _poly(d, pts, seed, fill=fill, width=width)


def _ellipse(d, box, seed, fill=None, width=W, n=36):
    x0, y0, x1, y1 = box
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    pts = [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]
    _poly(d, pts, seed, fill=fill, width=width)


def _font(size: int, kind: str = "hand") -> ImageFont.FreeTypeFont:
    name = "Caveat.ttf" if kind == "hand" else "Poppins-Bold.ttf"
    return ImageFont.truetype(str(FONTS / name), size)


def _canvas(w: int, h: int):
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


# ---------- Objets ----------
def coin(seed: str = "coin") -> Image.Image:
    img, d = _canvas(140, 140)
    _ellipse(d, (10, 10, 130, 130), seed, fill=GOLD)
    _ellipse(d, (34, 34, 106, 106), seed + "i", width=5)
    d.text((70, 72), "€", font=_font(58, "ui"), fill=INK, anchor="mm")
    return img


def coin_side(seed: str = "coin-side") -> Image.Image:
    """Pièce vue de côté, pour les piles."""
    img, d = _canvas(150, 46)
    _rounded(d, (6, 6, 144, 40), 16, seed, fill=GOLD, width=6)
    return img


def app_tile(glyph: str, color: str, seed: str) -> Image.Image:
    """Pictogramme d'appli générique : « play », « note », « haltere »."""
    img, d = _canvas(220, 220)
    _rounded(d, (12, 12, 208, 208), 46, seed, fill=color)
    if glyph == "play":
        _poly(d, [(88, 64), (88, 156), (162, 110)], seed + "g", fill=PALE, width=6)
    elif glyph == "note":
        d.line([(132, 58), (132, 140)], fill=PALE, width=12)
        d.line([(132, 58), (166, 72)], fill=PALE, width=12)
        _ellipse(d, (84, 126, 136, 166), seed + "g", fill=PALE, width=5)
    else:  # haltère
        d.line([(66, 110), (154, 110)], fill=PALE, width=14)
        for x in (58, 146):
            _rounded(d, (x, 74, x + 22, 146), 6, seed + str(x), fill=PALE, width=5)
    return img


def price_tag(label: str, seed: str, color: str = PALE) -> Image.Image:
    font = _font(64)
    tw = int(font.getlength(label))
    w, h = tw + 120, 110
    img, d = _canvas(w + 20, h + 20)
    _poly(d, [(50, 10), (w + 8, 10), (w + 8, h + 8), (50, h + 8), (12, (h + 18) / 2)], seed, fill=color)
    _ellipse(d, (40, h / 2, 60, h / 2 + 20), seed + "o", width=5)
    d.text((84, (h + 18) / 2), label, font=font, fill=INK, anchor="lm")
    return img


def phone(seed: str = "phone") -> Image.Image:
    img, d = _canvas(260, 460)
    _rounded(d, (14, 14, 246, 446), 38, seed, fill=GRAY)
    _rounded(d, (34, 54, 226, 392), 14, seed + "s", fill=PALE, width=5)
    _ellipse(d, (112, 404, 148, 432), seed + "b", width=5)
    return img


def piggy(seed: str = "piggy") -> Image.Image:
    img, d = _canvas(420, 330)
    _ellipse(d, (40, 60, 360, 290), seed, fill="#F2B8B0")
    _ellipse(d, (320, 140, 400, 210), seed + "n", fill="#F2B8B0")       # groin
    for x in (346, 370):
        _ellipse(d, (x, 165, x + 12, 183), seed + str(x), fill=INK, width=2)
    _poly(d, [(250, 74), (282, 20), (300, 86)], seed + "e", fill="#F2B8B0")
    for x in (100, 170, 240, 300):
        _poly(d, [(x, 270), (x + 30, 270), (x + 30, 318), (x, 318)], seed + f"l{x}", fill="#F2B8B0", width=6)
    _ellipse(d, (276, 120, 298, 142), seed + "y", fill=INK, width=2)
    d.line([(170, 78), (240, 78)], fill=INK, width=10)                  # fente
    return img


def calendar(month: str, seed: str) -> Image.Image:
    img, d = _canvas(260, 280)
    _rounded(d, (14, 34, 246, 266), 18, seed, fill=PALE)
    _poly(d, [(14, 34), (246, 34), (246, 100), (14, 100)], seed + "h", fill=CORAL, width=6)
    for x in (70, 190):
        d.line([(x, 14), (x, 56)], fill=INK, width=10)
    d.text((130, 182), month, font=_font(72), fill=INK, anchor="mm")
    return img


def receipt(lines: list[str], total: str, seed: str = "receipt") -> Image.Image:
    """Ticket de caisse : une ligne par prélèvement, total souligné en bas, bord dentelé."""
    font, big = _font(44), _font(66)
    lh = 52
    h = 60 + lh * len(lines) + 150
    img, d = _canvas(440, h + 40)
    zig = [(20 + k * 25, h + (12 if k % 2 else 0)) for k in range(17)]
    _poly(d, [(20, 20), (420, 20), (420, h)] + zig[::-1] + [(20, h)], seed, fill=PALE, width=6)
    for i, line in enumerate(lines):
        d.text((48, 50 + i * lh), line, font=font, fill=GRAY, anchor="la")
    y = 60 + lh * len(lines) + 10
    d.line([(40, y), (400, y)], fill=INK, width=4)
    d.text((48, y + 22), "TOTAL", font=_font(40, "ui"), fill=INK, anchor="la")
    d.text((400, y + 14), total, font=big, fill=INK, anchor="ra")
    return img


def burst(seed: str = "burst", color: str = GOLD) -> Image.Image:
    """Éclat derrière un chiffre clé."""
    img, d = _canvas(600, 600)
    pts = []
    for k in range(24):
        r = 290 if k % 2 == 0 else 220
        a = math.pi * 2 * k / 24
        pts.append((300 + r * math.cos(a), 300 + r * math.sin(a)))
    _poly(d, pts, seed, fill=color, width=6)
    return img


BUILDERS = {
    "coin": lambda: coin(),
    "coin-side": lambda: coin_side(),
    "app-play": lambda: app_tile("play", CORAL, "app-play"),
    "app-note": lambda: app_tile("note", TURQUOISE, "app-note"),
    "app-gym": lambda: app_tile("gym", PLUM, "app-gym"),
    "phone": lambda: phone(),
    "piggy": lambda: piggy(),
    "burst": lambda: burst(),
}


def ensure(name: str, out_dir: Path, builder=None) -> str:
    """Chemin absolu du PNG de l'objet (généré s'il n'existe pas encore)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    if not path.exists():
        img = builder() if builder else BUILDERS[name]()
        img.save(path)
    return str(path.resolve())
