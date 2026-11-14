"""Filigrane de Capital Simple (le C avec la pousse) sur fond transparent, d'après assets/finance/images/avatar.svg.

    python tools/finance/watermark.py      # -> assets/finance/images/capital_simple_watermark.png (240 px)
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

INK, TURQUOISE, GOLD = "#1A1A1A", "#0E9F8E", "#E0A526"
OUT = Path(__file__).resolve().parents[2] / "assets" / "finance" / "images" / "capital_simple_watermark.png"


def ellipse(size: int, rx: float, ry: float, angle: float, color: str) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse([size / 2 - rx, size / 2 - ry, size / 2 + rx, size / 2 + ry], fill=color)
    return img.rotate(-angle, resample=Image.BICUBIC)


def main(px: int = 240, ss: int = 8) -> Path:
    n = px * ss
    k = n / 84                                   # le logo tient dans ±42 unités (rayon 34 + trait)
    c = n / 2
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r, w = 34 * k, 7 * k
    start = math.degrees(math.atan2(22, 26))     # de (26, 22) à (26, -22) par la gauche
    d.arc([c - r - w / 2, c - r - w / 2, c + r + w / 2, c + r + w / 2], start, 360 - start, fill=INK, width=round(w))
    for sign in (1, -1):                         # bouts arrondis du C
        x, y = c + 26 * k, c + sign * 22 * k
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=INK)
    d.line([(c, c + 16 * k), (c, c - 4 * k)], fill=TURQUOISE, width=round(4 * k))
    for y in (c + 16 * k, c - 4 * k):
        d.ellipse([c - 2 * k, y - 2 * k, c + 2 * k, y + 2 * k], fill=TURQUOISE)
    for cx, cy, angle, color in ((-8, -7, -30, TURQUOISE), (8, -11, 30, GOLD)):
        leaf = ellipse(round(24 * k), 9 * k, 5 * k, angle, color)
        img.alpha_composite(leaf, (round(c + cx * k - leaf.width / 2), round(c + cy * k - leaf.height / 2)))
    img = img.resize((px, px), Image.LANCZOS)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT)
    return OUT


if __name__ == "__main__":
    print(main())
