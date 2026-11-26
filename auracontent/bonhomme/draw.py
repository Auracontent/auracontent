"""Dessin du format « expliqué par un bonhomme » de Le Fric en Clair : fond noir, bonhomme blanc du logo, or, écriture à la main.

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
    "titre": ROOT / "assets" / "finance" / "fonts" / "Anton-Regular.ttf",     # le lettrage du logo
}
SS = 2                      # suréchantillonnage

BLACK = (8, 8, 10)
WHITE = (245, 245, 240)
RED = (235, 45, 50)
YELLOW = (255, 214, 60)
GREEN = (40, 170, 110)      # épargne, ce qui va bien
GOLD = (246, 184, 28)       # l'or du logo « Le Fric en Clair »
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

    def image(self, zoom: float = 1.0, cx: float | None = None, cy: float | None = None,
              dx: float = 0.0, dy: float = 0.0) -> Image.Image:
        """Image finale ; zoom > 1 recadre autour de (cx, cy) (caméra), dx/dy décalent (tremblement)."""
        if zoom <= 1.0001 and not dx and not dy:
            return self.im.resize((self.w, self.h), Image.LANCZOS)
        zoom = max(1.0, zoom)
        cx = self.w / 2 if cx is None else cx
        cy = self.h / 2 if cy is None else cy
        w, h = self.w / zoom, self.h / zoom
        x0 = min(max(0.0, cx - w / 2 - dx), self.w - w)
        y0 = min(max(0.0, cy - h / 2 - dy), self.h - h)
        box = tuple(round(v * SS) for v in (x0, y0, x0 + w, y0 + h))
        return self.im.resize((self.w, self.h), Image.LANCZOS, box=box)

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


# ---------- le bonhomme (personnage du logo « Le Fric en Clair ») ----------
EXPRS = ("neutre", "content", "triste", "choc", "stresse", "pense", "fier", "malin", "colere")
ARMS = ("bas", "haut", "tete", "montre", "pouce", "salut", "menton", "piece", "hanches")
MARKS = {"pense": "?", "choc": "!", "stresse": "?!", "colere": "!"}


def figure(pen: Pen, x: float, y: float, s: float = 1.0, expr: str = "neutre", arms: str = "bas", t: float = 0.0,
           hop: float = 0.0, look: float = 0.0, flip: bool = False, marks: bool = True) -> tuple[float, float, float]:
    """Bonhomme blanc du logo : grosse tête ronde, corps plein, membres épais ; (x, y) = entre les pieds ;
    hauteur ~ 520 * s. `piece` : il brandit la pièce d'or du logo. Renvoie (x, y, rayon) de la tête."""
    y = y - hop
    sd = -1 if flip else 1
    hr = 100 * s
    hx, hy = x, y - 520 * s + hr
    sh_y = hy + hr + 22 * s                      # épaules
    hip_y = y - 205 * s
    lw = 30 * s                                  # épaisseur des membres
    # jambes
    pen.line([(x - 26 * s, hip_y), (x - 58 * s, y)], WHITE, lw)
    pen.line([(x + 26 * s, hip_y), (x + 58 * s, y)], WHITE, lw)
    # corps plein (forme de haricot, plus large aux épaules)
    pen.poly([(x - 62 * s, sh_y), (x + 62 * s, sh_y), (x + 50 * s, hip_y + 8 * s), (x - 50 * s, hip_y + 8 * s)], fill=WHITE)
    pen.circ(x - 40 * s, sh_y + 10 * s, 26 * s, fill=WHITE)
    pen.circ(x + 40 * s, sh_y + 10 * s, 26 * s, fill=WHITE)
    pen.rect(x - 52 * s, hip_y - 30 * s, x + 52 * s, hip_y + 18 * s, fill=WHITE, rad=22 * s)
    # bras
    sw = math.sin(t * 6) * 8 * s
    L0, R0 = (x - 55 * s, sh_y + 12 * s), (x + 55 * s, sh_y + 12 * s)
    down_l = [(x - 92 * s, sh_y + 90 * s), (x - 100 * s, sh_y + 170 * s + sw)]
    down_r = [(x + 92 * s, sh_y + 90 * s), (x + 100 * s, sh_y + 170 * s - sw)]
    coin_at = None
    if arms == "haut":
        a = [(x - 120 * s, sh_y - 40 * s), (x - 140 * s, sh_y - 150 * s + sw)]
        b = [(x + 120 * s, sh_y - 40 * s), (x + 140 * s, sh_y - 150 * s - sw)]
    elif arms == "tete":
        a = [(x - 135 * s, sh_y - 20 * s), (x - 85 * s, hy - 30 * s)]
        b = [(x + 135 * s, sh_y - 20 * s), (x + 85 * s, hy - 30 * s)]
    elif arms == "hanches":
        a = [(x - 115 * s, sh_y + 70 * s), (x - 52 * s, hip_y - 20 * s)]
        b = [(x + 115 * s, sh_y + 70 * s), (x + 52 * s, hip_y - 20 * s)]
    else:
        a = down_l
        if arms == "montre":
            b = [(x + sd * 140 * s, sh_y - 10 * s), (x + sd * 250 * s, sh_y - 70 * s + sw)]
        elif arms == "pouce":
            b = [(x + sd * 125 * s, sh_y + 50 * s), (x + sd * 165 * s, sh_y - 35 * s)]
        elif arms == "salut":
            b = [(x + sd * 125 * s, sh_y - 30 * s), (x + sd * (140 * s + math.sin(t * 14) * 40 * s), sh_y - 160 * s)]
        elif arms == "menton":
            b = [(x + sd * 105 * s, sh_y + 70 * s), (x + sd * 38 * s, hy + hr * 0.8)]
        elif arms == "piece":
            b = [(x + sd * 130 * s, sh_y - 20 * s), (x + sd * 150 * s, sh_y - 140 * s + sw * 0.5)]
            coin_at = b[-1]
        else:
            b = down_r
    pen.line([L0, *a], WHITE, lw)
    pen.line([R0, *b], WHITE, lw)
    for hand in (a[-1], b[-1]):
        pen.circ(*hand, lw * 0.75, fill=WHITE)
    if arms == "pouce":
        tx, ty = b[-1]
        pen.line([(tx, ty), (tx, ty - 48 * s)], WHITE, lw * 0.7)
    # tête
    pen.circ(hx, hy, hr, fill=WHITE)
    _face(pen, hx, hy, hr, s, expr, t, look)
    if coin_at:
        R = 62 * s
        cx, cy = coin_at[0] + sd * 10 * s, coin_at[1] - R * 0.7
        pen.circ(cx, cy, R, fill=GOLD, out=GOLD_DARK, w=6 * s)
        pen.circ(cx, cy, R * 0.78, out=GOLD_DARK, w=3 * s)
        pen.text(cx, cy + R * 0.04, "€", R * 1.15, GOLD_DARK, "titre")
    mark = MARKS.get(expr) if marks else None
    if mark:
        bob = math.sin(t * 9) * 6 * s
        mx, my = hx - hr * 0.95, hy - hr * 1.05 + bob
        for i, ch in enumerate(mark):
            pen.text(mx + i * 44 * s, my - (12 * s if i else 0), ch, 86 * s, RED if ch == "!" else WHITE, "titre")
    return hx, hy, hr


def _brow(pen, cx, cy, s, tilt, w=6.5):
    """Sourcil épais : tilt > 0 = intérieur relevé (inquiet), < 0 = froncé (colère / malin)."""
    pen.line([(cx - 22 * s, cy + tilt * s), (cx + 22 * s, cy - tilt * s)], BLACK, w * s)


def _face(pen: Pen, hx, hy, hr, s, expr, t, look):
    ex, ey, lk = hr * 0.36, hy - hr * 0.05, look * hr * 0.12
    blink = ((t + 1.3) % 3.1) < 0.08          # jamais à l'image 0 (miniature)
    for sx in (-1, 1):
        cx = hx + sx * ex + lk
        if blink:
            pen.line([(cx - 11 * s, ey), (cx + 11 * s, ey)], BLACK, 6 * s)
        elif expr == "choc":
            pen.circ(cx, ey, 18 * s, out=BLACK, w=6 * s)
            pen.circ(cx, ey, 7 * s, fill=BLACK)
        else:
            pen.circ(cx, ey, 11 * s, fill=BLACK)
        by = ey - 34 * s
        if expr in ("triste", "stresse"):
            _brow(pen, cx, by, s, -7 * sx)            # intérieur relevé
        elif expr in ("colere", "pense"):
            _brow(pen, cx, by + 4 * s, s, 8 * sx)     # froncé
        elif expr == "malin":
            _brow(pen, cx, by - (8 * s if sx == 1 else 0), s, 6 if sx == -1 else -3)
        elif expr == "choc":
            _brow(pen, cx, by - 14 * s, s, 0)
        elif expr in ("content", "fier"):
            pen.arc(cx, by + 12 * s, 18 * s, 205, 335, BLACK, 6 * s)
        else:
            _brow(pen, cx, by, s, 0, 5.5)
    my = hy + hr * 0.45
    if expr in ("content", "fier"):
        pen.d.chord([pen._p(hx - 34 * s + lk, my - 36 * s), pen._p(hx + 34 * s + lk, my + 24 * s)], 0, 180, fill=BLACK)
    elif expr == "malin":
        pen.arc(hx + 8 * s + lk, my - 22 * s, 28 * s, 25, 120, BLACK, 7 * s)
    elif expr == "triste":
        pen.arc(hx + lk, my + 22 * s, 26 * s, 205, 335, BLACK, 7 * s)
    elif expr == "choc":
        pen.circ(hx + lk, my + 4 * s, 18 * s, fill=BLACK)
    elif expr == "colere":
        pen.line([(hx - 24 * s + lk, my + 4 * s), (hx + 24 * s + lk, my - 2 * s)], BLACK, 7 * s)
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


def rays(pen: Pen, cx: float, cy: float, k: float, n: int = 14, r0: float = 160, r1: float = 900, rot: float = 0.0):
    """Rayons dorés du logo, qui jaillissent derrière l'accroche (k : 0 -> 1)."""
    if k <= 0:
        return
    for i in range(n):
        a = rot + i * 2 * math.pi / n
        ra, rb = r0 * (0.6 + 0.4 * k), r0 + (r1 - r0) * k
        w = 0.07
        pts = [(cx + ra * math.cos(a - w * 0.4), cy + ra * math.sin(a - w * 0.4)),
               (cx + rb * math.cos(a - w), cy + rb * math.sin(a - w)),
               (cx + rb * math.cos(a + w), cy + rb * math.sin(a + w)),
               (cx + ra * math.cos(a + w * 0.4), cy + ra * math.sin(a + w * 0.4))]
        pen.poly(pts, fill=(64, 48, 10) if i % 2 else (40, 31, 8))


def swoosh(pen: Pen, x0: float, x1: float, y: float, k: float, col=GOLD, w: float = 14):
    """Trait de pinceau doré sous un mot (k : 0 -> 1)."""
    if k <= 0:
        return
    pts = [(x0 + (x1 - x0) * i / 20, y + math.sin(i / 20 * math.pi) * 10) for i in range(int(20 * clamp(k)) + 1)]
    if len(pts) > 1:
        pen.line(pts, col, w)


def rain(pen: Pen, t: float, dens: int = 60):
    for i in range(dens):
        x = (i * 97.3 * pen.w / 1920) % pen.w
        sp = 700 + (i * 37) % 400
        y = ((t * sp + i * 173) % (pen.h + 200)) - 100
        pen.line([(x, y), (x - 8, y + 40)], GREY, 4)
