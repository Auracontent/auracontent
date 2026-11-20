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


BURST_WIDE = (960, 540)


def burst_wide(seed: str = "burst-wide", color: str = GOLD) -> Image.Image:
    """Éclat large (ovale) derrière le gros chiffre de l'accroche : un montant comme « 23 245 € » y tient en
    entier, alors qu'il débordait de l'éclat rond."""
    w, h = BURST_WIDE
    img, d = _canvas(w, h)
    cx, cy, n = w / 2, h / 2, 30
    pts = []
    for k in range(n):
        rx, ry = (470, 262) if k % 2 == 0 else (400, 214)
        a = math.pi * 2 * k / n
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    _poly(d, pts, seed, fill=color, width=6)
    return img


def cup(seed: str = "cup") -> Image.Image:
    """Tasse de café fumante."""
    img, d = _canvas(260, 260)
    _poly(d, [(40, 90), (190, 90), (176, 230), (54, 230)], seed, fill=PALE)
    _ellipse(d, (176, 120, 236, 190), seed + "h", width=W)
    _ellipse(d, (196, 140, 220, 172), seed + "hi", fill=PAPER, width=4)
    d.rectangle([48, 98, 182, 118], fill="#8B5A3C")
    for x in (85, 120, 155):
        d.line([(x, 70), (x - 8, 50), (x + 4, 30), (x - 4, 12)], fill=GRAY, width=5, joint="curve")
    return img


def card(seed: str = "card") -> Image.Image:
    """Carte bancaire générique."""
    img, d = _canvas(360, 240)
    _rounded(d, (12, 12, 348, 228), 26, seed, fill=TURQUOISE)
    d.rectangle([12, 58, 348, 92], fill=INK)
    _rounded(d, (40, 120, 100, 168), 8, seed + "p", fill=GOLD, width=4)
    for k in range(4):
        d.line([(130 + k * 50, 190), (162 + k * 50, 190)], fill=PALE, width=6)
    return img


def car(seed: str = "car") -> Image.Image:
    img, d = _canvas(440, 240)
    _poly(d, [(20, 170), (20, 120), (90, 110), (150, 50), (300, 50), (360, 110), (420, 120), (420, 170)], seed,
          fill=CORAL)
    _poly(d, [(165, 64), (230, 64), (230, 108), (120, 108)], seed + "w1", fill=PALE, width=5)
    _poly(d, [(245, 64), (292, 64), (338, 108), (245, 108)], seed + "w2", fill=PALE, width=5)
    for cx in (110, 330):
        _ellipse(d, (cx - 40, 140, cx + 40, 220), seed + str(cx), fill=INK)
        _ellipse(d, (cx - 16, 164, cx + 16, 196), seed + str(cx) + "i", fill=GRAY, width=4)
    return img


def cart(seed: str = "cart") -> Image.Image:
    """Caddie de courses."""
    img, d = _canvas(380, 300)
    d.line([(20, 30), (70, 30), (110, 200), (320, 200)], fill=INK, width=W, joint="curve")
    _poly(d, [(80, 70), (350, 70), (320, 180), (104, 180)], seed, fill=PALE)
    for x in (150, 210, 270):
        d.line([(x, 74), (x - 8, 176)], fill=GRAY, width=4)
    for cx in (130, 300):
        _ellipse(d, (cx - 24, 226, cx + 24, 274), seed + str(cx), fill=INK, width=5)
    return img


def banknote(seed: str = "note") -> Image.Image:
    img, d = _canvas(380, 210)
    _rounded(d, (12, 12, 368, 198), 14, seed, fill="#BFE3C9")
    _ellipse(d, (140, 50, 240, 160), seed + "c", fill=PALE, width=5)
    d.text((190, 106), "€", font=_font(64, "ui"), fill=INK, anchor="mm")
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
    "burst-wide": lambda: burst_wide(),
    "cup": lambda: cup(),
    "card": lambda: card(),
    "car": lambda: car(),
    "cart": lambda: cart(),
    "banknote": lambda: banknote(),
}

# Objets qui racontent chaque calcul (scènes d'accroche et de personnages)
CONCEPT_PROPS: dict[str, tuple[str, ...]] = {
    "abonnements": ("app-play", "app-note", "app-gym"),
    "depenses_repetees": ("cup", "coin", "cup"),
    "remises_successives": ("cart", "banknote"),
    "paiement_fractionne": ("card", "cart"),
    "credit_amortissable": ("car", "banknote"),
    "decouvert_agios": ("card", "coin"),
    "forfait_appareil": ("phone", "card"),
    "carte_fidelite": ("card", "cart"),
    "epargne_age": ("piggy", "coin"),
    "salaire_vs_prix": ("banknote", "cart"),
    "taux_reel": ("piggy", "cart"),
    "leasing_epargne": ("car", "piggy"),
    "interets_composes": ("piggy", "coin"),
    "inflation": ("cart", "banknote"),
    "cout_du_temps": ("piggy", "coin"),
    "frais": ("coin", "banknote"),
    "regle_72": ("piggy", "coin"),
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
