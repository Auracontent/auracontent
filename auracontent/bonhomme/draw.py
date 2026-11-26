"""Dessin du format « expliqué par un bonhomme » : fond noir, trait blanc, écriture à la main, bonhomme à écharpe verte.

Tout est dessiné avec PIL sur une toile suréchantillonnée (SS) puis réduite : traits lisses, aucune image externe.
Les coordonnées passées aux fonctions sont en pixels de sortie ; `Box` convertit les coordonnées virtuelles des
accessoires (une scène est dessinée dans un cadre de 1000 x 560) vers la zone d'accessoires du format choisi.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONTS = {
    "main": ROOT / "assets" / "finance" / "fonts" / "GochiHand-Regular.ttf",
    "petit": ROOT / "assets" / "finance" / "fonts" / "PatrickHand-Regular.ttf",
}
SS = 2                      # suréchantillonnage

BLACK = (8, 8, 10)
WHITE = (245, 245, 240)
RED = (235, 45, 50)
YELLOW = (255, 214, 60)
GREEN = (40, 170, 110)      # l'écharpe et la marque Capital Simple
GOLD = (240, 185, 40)
GOLD_DARK = (150, 105, 10)
GREY = (120, 120, 125)
BLUE = (90, 150, 255)
PINK = (240, 150, 170)
PINK_DARK = (180, 80, 110)
PHONE = (30, 30, 35)
SCREEN = (55, 60, 75)
CARD_BLUE = (40, 60, 120)
COLORS = {"blanc": WHITE, "rouge": RED, "jaune": YELLOW, "vert": GREEN, "or": GOLD, "gris": GREY}


def color(name: str | None, default=WHITE):
    return COLORS.get(name or "", default)


def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def ease(t: float) -> float:
    t = clamp(t)
    return t * t * (3 - 2 * t)


def back(t: float) -> float:
    """Arrivée avec un petit rebond (0 -> 1, dépasse un peu)."""
    t = clamp(t) - 1
    return t * t * (2.7 * t + 1.7) + 1


@lru_cache(None)
def font(size: float, kind: str = "main") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS[kind]), max(8, int(size * SS)))


def wrap(text: str, size: float, width: float, kind: str = "main") -> list[str]:
    f = font(size, kind)
    lines, cur = [], ""
    for w in text.split():
        test = f"{cur} {w}".strip()
        if cur and f.getlength(test) / SS > width:
            lines.append(cur)
            cur = w
        else:
            cur = test
    return lines + ([cur] if cur else [])


def fit(text: str, size: float, width: float, max_lines: int, kind: str = "main", min_size: float = 26):
    """Plus grande taille (<= size) pour laquelle le texte tient en max_lines lignes de largeur width."""
    while size >= min_size:
        lines = wrap(text, size, width, kind)
        if len(lines) <= max_lines and all(font(size, kind).getlength(ln) / SS <= width for ln in lines):
            return size, lines
        size -= 3
    raise ValueError(f"texte trop long pour sa zone : « {text[:60]} »")


class Pen:
    """Toile suréchantillonnée ; toutes les coordonnées en pixels de sortie."""

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.im = Image.new("RGB", (w * SS, h * SS), BLACK)
        self.d = ImageDraw.Draw(self.im)

    def image(self) -> Image.Image:
        return self.im.resize((self.w, self.h), Image.LANCZOS)

    @staticmethod
    def _p(x, y):
        return (x * SS, y * SS)

    def line(self, pts, col=WHITE, w=10.0):
        p = [self._p(*q) for q in pts]
        self.d.line(p, fill=col, width=max(1, int(w * SS)), joint="curve")
        r = w * SS / 2
        for q in (p[0], p[-1]):
            self.d.ellipse([q[0] - r, q[1] - r, q[0] + r, q[1] + r], fill=col)

    def circ(self, x, y, r, fill=None, out=None, w=8.0):
        if r <= 0:
            return
        self.d.ellipse([self._p(x - r, y - r), self._p(x + r, y + r)], fill=fill, outline=out,
                       width=max(1, int(w * SS)))

    def rect(self, x0, y0, x1, y1, fill=None, out=None, w=8.0, rad=0.0):
        if x1 <= x0 or y1 <= y0:
            return
        self.d.rounded_rectangle([self._p(x0, y0), self._p(x1, y1)], radius=max(0, rad * SS), fill=fill,
                                 outline=out, width=max(1, int(w * SS)))

    def poly(self, pts, fill=None):
        self.d.polygon([self._p(*q) for q in pts], fill=fill)

    def arc(self, x, y, r, a0, a1, col=BLACK, w=6.0):
        if r <= 0 or a1 <= a0:
            return
        self.d.arc([self._p(x - r, y - r), self._p(x + r, y + r)], a0, a1, fill=col, width=max(1, int(w * SS)))

    def text(self, x, y, txt, size, col=WHITE, kind="main", reveal=1.0, anchor="mm"):
        """Texte centré en (x, y) ; reveal < 1 l'écrit de gauche à droite (sans bouger sa position finale)."""
        if not txt or reveal <= 0:
            return
        f = font(size, kind)
        if reveal >= 1:
            self.d.text(self._p(x, y), txt, font=f, fill=col, anchor=anchor)
            return
        n = max(1, round(len(txt) * reveal))
        full = f.getlength(txt) / SS
        x0 = x - full / 2 if anchor == "mm" else x
        self.d.text(self._p(x0, y), txt[:n], font=f, fill=col, anchor="lm")

    def block(self, x, y, lines, size, col=WHITE, kind="main", reveal=1.0, spacing=1.08):
        """Plusieurs lignes centrées autour de y ; reveal écrit les lignes l'une après l'autre."""
        total = sum(len(ln) for ln in lines) or 1
        lh = size * spacing
        y0 = y - lh * (len(lines) - 1) / 2
        done = 0
        for i, ln in enumerate(lines):
            r = clamp((reveal * total - done) / max(1, len(ln)))
            self.text(x, y0 + i * lh, ln, size, col, kind, r)
            done += len(ln)


class Box:
    """Cadre virtuel 1000 x 560 posé (sans déformation) au centre d'une zone en pixels de sortie."""

    VW, VH = 1000.0, 560.0

    def __init__(self, rect):
        x0, y0, x1, y1 = rect
        self.k = min((x1 - x0) / self.VW, (y1 - y0) / self.VH)
        self.ox = x0 + ((x1 - x0) - self.VW * self.k) / 2
        self.oy = y0 + ((y1 - y0) - self.VH * self.k) / 2

    def p(self, x, y):
        return (self.ox + x * self.k, self.oy + y * self.k)

    def s(self, v):
        return v * self.k


# ---------- le bonhomme ----------
EXPRS = ("neutre", "content", "triste", "choc", "stresse", "pense", "fier")
ARMS = ("bas", "haut", "tete", "montre", "pouce", "salut", "menton")


def figure(pen: Pen, x: float, y: float, s: float = 1.0, expr: str = "neutre", arms: str = "bas", t: float = 0.0,
           hop: float = 0.0, look: float = 0.0, flip: bool = False) -> tuple[float, float, float]:
    """Bonhomme blanc à tête ronde et écharpe verte ; (x, y) = entre les pieds ; hauteur ~ 520 * s.
    Renvoie (x, y, rayon) de la tête. flip : montre vers la gauche au lieu de la droite."""
    y = y - hop
    sd = -1 if flip else 1
    hr = 95 * s
    hx, hy = x, y - 520 * s + hr
    neck, hip = (x, hy + hr), (x, y - 200 * s)
    pen.line([hip, (x - 55 * s, y)], WHITE, 16 * s)
    pen.line([hip, (x + 55 * s, y)], WHITE, 16 * s)
    pen.line([neck, hip], WHITE, 18 * s)
    sh = (x, hy + hr + 40 * s)
    sw = math.sin(t * 6) * 8 * s
    down = (x - 70 * s, sh[1] + 120 * s + sw)
    if arms == "haut":
        a = [(x - 90 * s, sh[1] - 40 * s), (x - 120 * s, sh[1] - 150 * s + sw)]
        b = [(x + 90 * s, sh[1] - 40 * s), (x + 120 * s, sh[1] - 150 * s - sw)]
    elif arms == "tete":
        a = [(x - 110 * s, sh[1] - 30 * s), (x - 70 * s, hy - 20 * s)]
        b = [(x + 110 * s, sh[1] - 30 * s), (x + 70 * s, hy - 20 * s)]
    elif arms == "montre":
        a = [down]
        b = [(x + sd * 120 * s, sh[1] - 10 * s), (x + sd * 230 * s, sh[1] - 60 * s + sw)]
    elif arms == "pouce":
        a = [down]
        b = [(x + sd * 110 * s, sh[1] + 40 * s), (x + sd * 150 * s, sh[1] - 40 * s)]
    elif arms == "salut":
        a = [down]
        b = [(x + sd * 100 * s, sh[1] - 30 * s), (x + sd * (120 * s + math.sin(t * 14) * 40 * s), sh[1] - 150 * s)]
    elif arms == "menton":
        a = [down]
        b = [(x + sd * 80 * s, sh[1] + 60 * s), (x + sd * 30 * s, hy + hr * 0.75)]
    else:
        a = [down]
        b = [(x + 70 * s, sh[1] + 120 * s - sw)]
    pen.line([sh, *a], WHITE, 14 * s)
    pen.line([sh, *b], WHITE, 14 * s)
    if arms == "pouce":
        tx, ty = x + sd * 150 * s, sh[1] - 40 * s
        pen.line([(tx, ty), (tx, ty - 45 * s)], WHITE, 14 * s)
    pen.circ(hx, hy, hr, fill=WHITE)
    # écharpe : la marque du personnage
    pen.poly([(hx - hr * 0.75, hy + hr * 0.82), (hx + hr * 0.75, hy + hr * 0.82),
              (hx + hr * 0.6, hy + hr * 1.15), (hx - hr * 0.6, hy + hr * 1.15)], fill=GREEN)
    pen.poly([(hx + hr * 0.25, hy + hr * 1.05), (hx + hr * 0.55, hy + hr * 1.05),
              (hx + hr * 0.7, hy + hr * 1.75), (hx + hr * 0.4, hy + hr * 1.7)], fill=GREEN)
    _face(pen, hx, hy, hr, s, expr, t, look)
    return hx, hy, hr


def _face(pen: Pen, hx, hy, hr, s, expr, t, look):
    ex, ey, lk = hr * 0.36, hy - hr * 0.08, look * hr * 0.12
    blink = (t % 3.1) < 0.08
    for sx in (-1, 1):
        cx = hx + sx * ex + lk
        if blink:
            pen.line([(cx - 10 * s, ey), (cx + 10 * s, ey)], BLACK, 6 * s)
        elif expr == "choc":
            pen.circ(cx, ey, 17 * s, out=BLACK, w=6 * s)
            pen.circ(cx, ey, 6 * s, fill=BLACK)
        else:
            pen.circ(cx, ey, 9 * s, fill=BLACK)
        if expr == "triste":
            pen.line([(cx + 18 * s * sx, ey - 30 * s), (cx - 14 * s * sx, ey - 40 * s)], BLACK, 6 * s)
        elif expr == "stresse":
            pen.line([(cx - 16 * s, ey - 36 * s + sx * 4 * s), (cx + 16 * s, ey - 36 * s - sx * 4 * s)], BLACK, 6 * s)
        elif expr == "pense" and sx == 1:
            pen.line([(cx - 16 * s, ey - 42 * s), (cx + 16 * s, ey - 34 * s)], BLACK, 6 * s)
        elif expr == "fier":
            pen.arc(cx, ey + 4 * s, 12 * s, 200, 340, BLACK, 5 * s)
    my = hy + hr * 0.42
    if expr in ("content", "fier"):
        pen.arc(hx + lk, my - 22 * s, 30 * s, 20, 160, BLACK, 7 * s)
    elif expr == "triste":
        pen.arc(hx + lk, my + 20 * s, 26 * s, 205, 335, BLACK, 7 * s)
    elif expr == "choc":
        pen.circ(hx + lk, my, 16 * s, fill=BLACK)
    elif expr == "stresse":
        pen.line([(hx - 28 * s + lk, my), (hx - 10 * s + lk, my - 8 * s), (hx + 8 * s + lk, my),
                  (hx + 26 * s + lk, my - 8 * s)], BLACK, 6 * s)
        dx, dy = hx + hr * 0.95, hy - hr * 0.5 + (t * 60 % 40) * s      # goutte de sueur
        pen.poly([(dx, dy - 26 * s), (dx - 13 * s, dy + 4 * s), (dx + 13 * s, dy + 4 * s)], fill=BLUE)
        pen.circ(dx, dy + 6 * s, 13 * s, fill=BLUE)
    elif expr == "pense":
        pen.line([(hx - 18 * s + lk, my), (hx + 22 * s + lk, my - 6 * s)], BLACK, 6 * s)
    else:
        pen.line([(hx - 22 * s + lk, my), (hx + 22 * s + lk, my)], BLACK, 6 * s)


# ---------- accessoires (coordonnées virtuelles via Box) ----------
def coin(pen: Pen, b: Box, x, y, r=34):
    X, Y = b.p(x, y)
    R = b.s(r)
    pen.circ(X, Y, R, fill=GOLD, out=GOLD_DARK, w=max(2, R * 0.15))
    pen.text(X, Y + R * 0.05, "€", R * 1.1, GOLD_DARK, "petit")


def coin_pile(pen: Pen, b: Box, cx, base, n, progress=1.0, fall=600):
    """Pile de pièces qui tombent l'une après l'autre (progress 0 -> 1)."""
    shown = progress * n
    for i in range(n):
        row, col = divmod(i, 4)
        x, y = cx - 108 + col * 72 + (row % 2) * 36, base - row * 62
        if i < int(shown):
            coin(pen, b, x, y)
        elif i == int(shown) and progress < 1:
            coin(pen, b, x, y - (1 - shown % 1) * fall)


def bank_card(pen: Pen, b: Box, cx, cy, text, a=1.0, col=RED):
    if a <= 0:
        return
    x0, y0 = b.p(cx - 230 * a, cy - 140 * a)
    x1, y1 = b.p(cx + 230 * a, cy + 140 * a)
    pen.rect(x0, y0, x1, y1, fill=CARD_BLUE, out=WHITE, w=b.s(6), rad=b.s(24))
    cx0, cy0 = b.p(cx - 180 * a, cy - 80 * a)
    cx1, cy1 = b.p(cx - 110 * a, cy - 30 * a)
    pen.rect(cx0, cy0, cx1, cy1, fill=GOLD, rad=b.s(8))
    if a > 0.7 and text:
        size, lines = fit(text, b.s(92), b.s(420), 1)
        pen.text(*b.p(cx, cy + 50), lines[0], size, col)


def phone(pen: Pen, b: Box, cx, cy, h=540):
    w = h * 0.53
    x0, y0 = b.p(cx - w / 2, cy - h / 2)
    x1, y1 = b.p(cx + w / 2, cy + h / 2)
    pen.rect(x0, y0, x1, y1, fill=PHONE, out=WHITE, w=b.s(7), rad=b.s(36))
    sx0, sy0 = b.p(cx - w / 2 + 20, cy - h / 2 + 36)
    sx1, sy1 = b.p(cx + w / 2 - 20, cy + h / 2 - 40)
    pen.rect(sx0, sy0, sx1, sy1, fill=SCREEN, rad=b.s(14))


def notif(pen: Pen, b: Box, cx, cy, text, a, width=250, col=RED):
    if a <= 0:
        return
    k = back(a)
    x0, y0 = b.p(cx - width / 2 * k, cy - 34 * k)
    x1, y1 = b.p(cx + width / 2 * k, cy + 34 * k)
    pen.rect(x0, y0, x1, y1, fill=WHITE, rad=b.s(16 * k))
    if k > 0.6:
        size, lines = fit(text, b.s(36), b.s(width - 24), 1, "petit", min_size=10)
        pen.text(*b.p(cx, cy), lines[0], size, col, "petit")


def value_box(pen: Pen, b: Box, cx, cy, w, h, label, value, col, a):
    if a <= 0:
        return
    k = back(a)
    x0, y0 = b.p(cx - w / 2, cy - h / 2 * k)
    x1, y1 = b.p(cx + w / 2, cy + h / 2 * k)
    pen.rect(x0, y0, x1, y1, out=col, w=b.s(8), rad=b.s(20))
    if k > 0.7:
        if label:
            size, lines = fit(label, b.s(48), b.s(w - 30), 1, min_size=10)
            pen.text(*b.p(cx, cy - h * 0.2), lines[0], size, col)
        if value:
            size, lines = fit(value, b.s(84), b.s(w - 30), 1, min_size=10)
            pen.text(*b.p(cx, cy + h * 0.15), lines[0], size, WHITE if col != GREY else GREY)


def brain_bubble(pen: Pen, b: Box, cx, cy, a, r=150):
    if a <= 0:
        return
    for dx, dy, rr in ((-r * 1.13, r * 1.13, 16), (-r * 0.87, r * 0.8, 26)):
        pen.circ(*b.p(cx + dx, cy + dy), b.s(rr * a), fill=WHITE)
    pen.circ(*b.p(cx, cy), b.s(r * a), fill=WHITE)
    if a > 0.8:
        pen.circ(*b.p(cx - 40, cy - 10), b.s(70), fill=PINK)
        pen.circ(*b.p(cx + 40, cy - 10), b.s(70), fill=PINK)
        for k in range(4):
            pen.arc(*b.p(cx - 40 + k * 25, cy - 20 + (k % 2) * 25), b.s(30), 200, 340, PINK_DARK, b.s(6))


def arrow(pen: Pen, b: Box, x0, y0, x1, y1, k, col=WHITE, w=10):
    if k <= 0:
        return
    xe, ye = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
    pen.line([b.p(x0, y0), b.p(xe, ye)], col, b.s(w))
    if k > 0.95:
        ang = math.atan2(y1 - y0, x1 - x0)
        tip = b.p(x1, y1)
        L = b.s(34)
        pen.poly([tip, (tip[0] - L * math.cos(ang - 0.45), tip[1] - L * math.sin(ang - 0.45)),
                  (tip[0] - L * math.cos(ang + 0.45), tip[1] - L * math.sin(ang + 0.45))], fill=col)


def jar(pen: Pen, b: Box, cx, cy, fill, col=GREEN, size=1.0):
    w, h = 200 * size, 190 * size
    x0, y0 = b.p(cx - w / 2, cy - h / 2)
    x1, y1 = b.p(cx + w / 2, cy + h / 2)
    pen.rect(x0, y0, x1, y1, out=WHITE, w=b.s(8), rad=b.s(30 * size))
    lx0, ly0 = b.p(cx - w * 0.38, cy - h / 2 - 32 * size)
    lx1, ly1 = b.p(cx + w * 0.38, cy - h / 2 + 2)
    pen.rect(lx0, ly0, lx1, ly1, fill=WHITE, rad=b.s(10))
    if fill > 0:
        fx0, fy0 = b.p(cx - w / 2 + 12, cy + h / 2 - 12 - (h - 24) * clamp(fill))
        fx1, fy1 = b.p(cx + w / 2 - 12, cy + h / 2 - 12)
        pen.rect(fx0, fy0, fx1, fy1, fill=col, rad=b.s(22 * size))


def rain(pen: Pen, t: float, dens: int = 60):
    for i in range(dens):
        x = (i * 97.3 * pen.w / 1920) % pen.w
        sp = 700 + (i * 37) % 400
        y = ((t * sp + i * 173) % (pen.h + 200)) - 100
        pen.line([(x, y), (x - 8, y + 40)], GREY, 4)
