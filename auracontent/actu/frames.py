"""Images d'un short « L'éco du jour » : fond vert sapin, titres à empattements, gros chiffres, graphiques sourcés sur
carte blanche, bonhomme qui réagit, sous-titres mot par mot. Chaque image est calculée à partir du temps : le rendu
peut être coupé en morceaux (processus parallèles) et la planche tire n'importe quel instant.

Zones de la chaîne (1080 x 1920) : rien d'important au-dessus de y = 200, sous y = 1440, ni à droite de x = 930.
  200-270   pastille d'en-tête (« DETTE PUBLIQUE · NOV. 2026 »)
  290-450   titre de la scène (serif crème)
  470-1240  contenu (carte de graphique, gros chiffre, bonhomme)
  1270-1440 sous-titres (crème, chiffres et mots clés en or)
"""
from __future__ import annotations

import itertools
import math
import re
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from auracontent.archive.timeline import FPS, H, Timeline, W

ROOT = Path(__file__).resolve().parents[2]
FONTS = {
    "serif": ROOT / "assets" / "archive" / "fonts" / "Caladea-Bold.ttf",
    "big": ROOT / "assets" / "archive" / "fonts" / "Anton-Regular.ttf",
    "ui": ROOT / "assets" / "finance" / "fonts" / "Poppins-Bold.ttf",
    "ui2": ROOT / "assets" / "finance" / "fonts" / "Poppins-SemiBold.ttf",
}
BG = (13, 50, 43)              # vert sapin
BG2 = (22, 70, 60)
CREAM = (250, 246, 232)
INK = (28, 32, 38)
GOLD = (240, 178, 36)
RED = (214, 45, 40)
MINT = (52, 205, 165)
GREY = (120, 124, 130)
PAPER = (252, 250, 245)
SAFE_R = 930
CARD = (60, 470, 1020, 1240)
DISCLAIMER = "Contenu pédagogique, pas un conseil en investissement."


# ---------- outils ----------
@lru_cache(None)
def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS[kind]), max(8, int(size)))


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def back_out(x):
    x = clamp(x)
    c1 = 1.70158
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def fr_num(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return s


def wrap(text: str, f: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines, cur = [], ""
    for w in text.split():
        test = f"{cur} {w}".strip()
        if cur and f.getlength(test) > width:
            lines.append(cur)
            cur = w
        else:
            cur = test
    return lines + ([cur] if cur else [])


def fit(text: str, kind: str, size: int, width: float, height: float, spacing: float = 1.12, min_size: int = 26):
    """Plus grande taille (<= size) pour laquelle le texte tient dans width x height. Lève une erreur sinon."""
    while size >= min_size:
        f = font(kind, size)
        lines = wrap(text, f, width)
        if len(lines) * size * spacing <= height and all(f.getlength(ln) <= width for ln in lines):
            return f, lines
        size -= 4
    raise ValueError(f"texte trop long pour sa zone : « {text[:60]} »")


def draw_text(img, text, cx, cy, kind, size, box_w, box_h, fill=CREAM, stroke=None, sw=0, alpha=1.0, scale=1.0,
              spacing=1.12, colors: dict | None = None, anchor_x="center"):
    """Texte centré (ou aligné à gauche) dans une boîte, avec pop (scale) et fondu (alpha). `colors` : mot -> couleur."""
    if alpha <= 0.01 or scale <= 0.05:
        return
    f, lines = fit(text, kind, size, box_w, box_h, spacing)
    if abs(scale - 1) > 1e-3:
        f = font(kind, f.size * scale)
    lh = f.size * spacing
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    y0 = cy - lh * len(lines) / 2
    sw = int(sw * scale)
    for i, ln in enumerate(lines):
        y = y0 + i * lh + lh / 2
        total = f.getlength(ln)
        x = cx - total / 2 if anchor_x == "center" else cx
        for w in ln.split(" "):
            key = re.sub(r"[.,;:!?…»«]", "", w)
            col = (colors or {}).get(key, fill)
            d.text((x, y), w, font=f, fill=col, anchor="lm", stroke_width=sw, stroke_fill=stroke)
            x += f.getlength(w + " ")
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(layer)


def rrect(img, box, r, fill, alpha=1.0, outline=None, width=0):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, r, fill=(*fill[:3], int(255 * alpha)),
                                            outline=(*outline, int(255 * alpha)) if outline else None, width=width)
    img.alpha_composite(layer)


def stick(img, cx, cy, s, pose, t):
    """Bonhomme crème (tête, corps, bras selon la pose) : choc, montre, content, pense."""
    d = ImageDraw.Draw(img)
    w = max(3, int(9 * s))
    hr = 55 * s
    d.ellipse([cx - hr, cy - hr, cx + hr, cy + hr], fill=PAPER, outline=CREAM, width=w)
    by = cy + hr
    hip = by + 170 * s
    d.line([cx, by, cx, hip], fill=CREAM, width=w)
    d.line([cx, hip, cx - 60 * s, hip + 150 * s], fill=CREAM, width=w)
    d.line([cx, hip, cx + 60 * s, hip + 150 * s], fill=CREAM, width=w)
    sh = by + 45 * s
    wob = math.sin(t * 9) * 10 * s
    eye = lambda x, y, r: d.ellipse([x - r, y - r, x + r, y + r], fill=INK)  # noqa: E731
    if pose == "choc":
        for sg in (-1, 1):
            d.line([cx, sh, cx + sg * 80 * s, sh - 40 * s], fill=CREAM, width=w)
            d.line([cx + sg * 80 * s, sh - 40 * s, cx + sg * 50 * s + sg * wob, cy - 40 * s], fill=CREAM, width=w)
        eye(cx - 15 * s, cy - 8 * s, 8 * s)
        eye(cx + 15 * s, cy - 8 * s, 8 * s)
        d.ellipse([cx - 13 * s, cy + 16 * s, cx + 13 * s, cy + 40 * s], outline=INK, width=max(2, int(6 * s)))
    elif pose == "montre":
        d.line([cx, sh, cx - 70 * s, sh + 90 * s], fill=CREAM, width=w)
        d.line([cx, sh, cx + 150 * s, sh - 30 * s + wob], fill=CREAM, width=w)
        eye(cx - 3 * s, cy - 6 * s, 7 * s)
        eye(cx + 25 * s, cy - 6 * s, 7 * s)
        d.arc([cx - 10 * s, cy + 5 * s, cx + 30 * s, cy + 35 * s], 0, 180, fill=INK, width=max(2, int(6 * s)))
    elif pose == "pense":
        d.line([cx, sh, cx - 70 * s, sh + 90 * s], fill=CREAM, width=w)
        d.line([cx, sh, cx + 60 * s, sh + 40 * s], fill=CREAM, width=w)
        d.line([cx + 60 * s, sh + 40 * s, cx + 20 * s, cy + 45 * s], fill=CREAM, width=w)
        eye(cx - 15 * s, cy - 14 * s, 7 * s)
        eye(cx + 15 * s, cy - 14 * s, 7 * s)
        d.line([cx - 15 * s, cy + 25 * s, cx + 15 * s, cy + 22 * s], fill=INK, width=max(2, int(6 * s)))
    else:  # content
        for sg in (-1, 1):
            d.line([cx, sh, cx + sg * 110 * s, sh - 110 * s + sg * wob], fill=CREAM, width=w)
        eye(cx - 15 * s, cy - 10 * s, 8 * s)
        eye(cx + 15 * s, cy - 10 * s, 8 * s)
        d.arc([cx - 25 * s, cy - 5 * s, cx + 25 * s, cy + 35 * s], 0, 180, fill=INK, width=max(2, int(7 * s)))


def nice_step(span: float) -> float:
    raw = span / 4
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


# ---------- moteur ----------
class Renderer:
    def __init__(self, episode: Path, tl: Timeline):
        self.ep, self.tl, self.plan = episode, tl, tl.plan
        self.scenes = []
        sc = self.plan["scenes"]
        for i, s in enumerate(sc):
            t0 = tl.t(s["from"])
            t1 = tl.t(sc[i + 1]["from"]) if i + 1 < len(sc) else tl.dur
            if t1 <= t0:
                raise ValueError(f"scène {i} : durée nulle ou négative ({t0:.2f} -> {t1:.2f} s)")
            self.scenes.append({**s, "t0": t0, "t1": t1})
        kw = {re.sub(r"[.,;:!?…]", "", k).lower() for k in self.plan.get("keywords", [])}
        self.keywords = kw
        self.sources = self.plan["sources"]
        self.bg = self._background()

    def _background(self) -> Image.Image:
        img = Image.new("RGBA", (W, H), (*BG, 255))
        d = ImageDraw.Draw(img)
        for y in range(80, H, 80):
            for x in range(60, W, 80):
                d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=BG2)
        return img

    def scene_at(self, t: float) -> dict:
        for s in self.scenes:
            if s["t0"] <= t < s["t1"]:
                return s
        return self.scenes[-1]

    def frame(self, fi: int):
        import numpy as np

        t = fi / FPS
        img = self.bg.copy()
        s = self.scene_at(t)
        lt = t - s["t0"]
        self.header(img, t)
        getattr(self, "s_" + s["type"])(img, s, lt)
        if s.get("title") and s["type"] not in ("titre", "fin"):
            draw_text(img, s["title"], 495, 370, "serif", 88, 860, 160, scale=back_out(lt / 0.35), spacing=1.0)
        self.subtitles(img, t)
        return np.asarray(img.convert("RGB"))

    # ---------- habillage ----------
    def header(self, img, t):
        txt = self.plan.get("header") or "L'ÉCO DU JOUR"
        f = font("ui", 34)
        w = f.getlength(txt) + 90
        a = ease_out(t / 0.4)
        rrect(img, (540 - w / 2, 205, 540 + w / 2, 263), 29, (0, 0, 0), alpha=0.35 * a)
        d = ImageDraw.Draw(img)
        d.ellipse([540 - w / 2 + 22, 222, 540 - w / 2 + 46, 246], fill=MINT)
        draw_text(img, txt, 540 + 18, 234, "ui", 34, w, 50, fill=GOLD, alpha=a)

    def source_line(self, img, s, y, alpha=1.0, color=GREY, width=820):
        src = self.sources.get(s.get("source", ""), {})
        if src:
            draw_text(img, "Source : " + src["name"], 495, y, "ui2", 27, width, 70, fill=color, alpha=alpha)

    def subtitles(self, img, t):
        for a, b, words in self.tl.chunks:
            if a <= t < b:
                parts = []
                cols = {}
                for wa, _wb, w in words:
                    key = re.sub(r"[.,;:!?…»«]", "", w)
                    parts.append(w)
                    hot = bool(re.search(r"\d", w)) or key.lower() in self.keywords
                    cols[key] = GOLD if hot else (CREAM if t >= wa else (205, 210, 200))
                pop = back_out((t - a) / 0.18)
                draw_text(img, " ".join(parts), 495, 1350, "ui", 78, 860, 170, fill=CREAM, stroke=BG, sw=9,
                          scale=0.85 + 0.15 * pop, colors=cols)
                return

    # ---------- scènes ----------
    def s_titre(self, img, s, lt):
        draw_text(img, s.get("title", ""), 495, 380, "serif", 100, 860, 170, scale=back_out(lt / 0.35), spacing=1.0)
        p = back_out((lt - 0.3) / 0.4)
        draw_text(img, s["number"], 495, 640, "big", 220, 860, 260, fill=GOLD, stroke=INK, sw=12, scale=p)
        if s.get("sub"):
            draw_text(img, s["sub"], 495, 820, "serif", 70, 860, 110, fill=(255, 150, 130),
                      scale=back_out((lt - 1.1) / 0.35))
        self.source_line(img, s, 895, ease_out((lt - 0.8) / 0.4), color=(150, 175, 165))
        if s.get("pose"):
            self.figure(img, s["pose"], 960, lt)

    def figure(self, img, pose, top, lt):
        """Bonhomme entre `top` et y = 1235 (jamais sur les sous-titres), qui monte en entrant."""
        scale = clamp((1235 - top) / 380, 0.45, 0.95)
        stick(img, 495, top + 55 * scale + 30 * (1 - ease_out((lt - 0.4) / 0.4)), scale, pose, lt)

    def s_chiffre(self, img, s, lt):
        top = 520
        if s.get("calc"):
            draw_text(img, s["calc"], 495, top, "ui2", 52, 860, 120, alpha=ease_out((lt - 0.2) / 0.4))
            top += 110
        t_count = self.tl.t(s["count_at"]) - s["t0"] if s.get("count_at") else 0.5
        v = float(s["value"]) * ease_out((lt - t_count) / 1.4)
        dec = int(s.get("decimals", 0))
        txt = s.get("format", "{n}").replace("{n}", fr_num(v, dec))
        draw_text(img, txt, 495, top + 150, "big", 200, 860, 250, fill=GOLD, stroke=INK, sw=12,
                  scale=back_out((lt - t_count + 0.25) / 0.3))
        y = top + 260
        if s.get("caption"):
            draw_text(img, s["caption"], 495, top + 310, "big", 76, 860, 110,
                      alpha=ease_out((lt - t_count - 1.2) / 0.35))
            y = top + 380
        self.source_line(img, s, y, ease_out((lt - 0.8) / 0.4), color=(150, 175, 165))
        if s.get("pose") and y + 60 < 1080:
            self.figure(img, s["pose"], y + 50, lt)

    def _card(self, img, s, lt, title):
        a = ease_out(lt / 0.3)
        rrect(img, CARD, 30, PAPER, alpha=a)
        if title:
            draw_text(img, title, 540, CARD[1] + 50, "ui", 40, 820, 60, fill=INK, alpha=a)
        self.source_line(img, s, CARD[3] - 32, a, color=GREY, width=860)
        return a

    def s_courbe(self, img, s, lt):
        self._card(img, s, lt, s.get("chart_title"))
        pts = [(float(x), float(y)) for x, y in s["points"]]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if s.get("y_range"):
            lo, hi = (float(v) for v in s["y_range"])
            step = nice_step(hi - lo)
        else:
            lo, hi = min([*ys, s.get("ref_line", {}).get("y", min(ys))]), max(ys)
            step = nice_step(hi - lo)
            lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step + step
        gx0, gx1, gy0, gy1 = CARD[0] + 125, SAFE_R - 30, CARD[1] + 120, CARD[3] - 140
        X = lambda x: gx0 + (x - xs[0]) / (xs[-1] - xs[0]) * (gx1 - gx0)  # noqa: E731
        Y = lambda y: gy1 - (y - lo) / (hi - lo) * (gy1 - gy0)            # noqa: E731
        d = ImageDraw.Draw(img)
        unit = s.get("unit", "")
        v = math.ceil(lo / step - 1e-9) * step
        while v <= hi + 1e-9:
            d.line([gx0, Y(v), gx1, Y(v)], fill=(226, 226, 222), width=2)
            draw_text(img, f"{fr_num(v, 0 if step >= 1 else 1)}{unit}", gx0 - 60, Y(v), "ui2", 28, 110, 40, fill=GREY)
            v += step
        ticks = s.get("x_ticks") or [xs[0], xs[len(xs) // 3], xs[2 * len(xs) // 3], xs[-1]]
        for x in ticks:
            label = str(int(x)) if float(x).is_integer() else fr_num(float(x), 1)
            draw_text(img, label, X(x), gy1 + 38, "ui2", 28, 120, 40, fill=GREY)
        end, t_done = self.curve_end(s, lt, xs)
        reveal = (end - xs[0]) / (xs[-1] - xs[0])
        ref = s.get("ref_line")
        if ref and reveal >= 1:
            a = ease_out((lt - t_done) / 0.5)
            for xx in range(int(gx0), int(gx1), 30):
                d.line([xx, Y(ref["y"]), xx + 16, Y(ref["y"])], fill=(30, 90, 200), width=4)
            draw_text(img, ref.get("label", ""), (gx0 + gx1) / 2, Y(ref["y"]) + 34, "ui", 30, 600, 44,
                      fill=(30, 90, 200), alpha=a)
        hl = s.get("highlight_from")
        prev = None
        for i, (x, y) in enumerate(pts):
            if x > end and i > 0:
                px, py = pts[i - 1]
                f = (end - px) / (x - px) if x != px else 1
                x, y = end, py + (y - py) * f
            cur = (X(x), Y(y))
            if prev:
                col = RED if hl is not None and x > float(hl) else (60, 62, 66)
                d.line([prev, cur], fill=col, width=9)
            prev = cur
            if x >= end:
                break
        if prev:
            d.ellipse([prev[0] - 13, prev[1] - 13, prev[0] + 13, prev[1] + 13], fill=RED)
        for an in s.get("annotations", []):
            if end >= float(an["x"]):
                yy = next((y for x, y in pts if x >= float(an["x"])), ys[-1])
                a = ease_out((end - float(an["x"])) / max(0.5, (xs[-1] - xs[0]) * 0.06))
                dy = float(an.get("dy", -55))
                draw_text(img, an["label"], X(float(an["x"])) + float(an.get("dx", 0)), Y(yy) + dy, "ui", 32, 280, 44,
                          fill=INK, alpha=a)
        if s.get("end_label") and reveal >= 1:
            draw_text(img, s["end_label"], min(X(xs[-1]) - 120, SAFE_R - 140), max(Y(ys[-1]) - 70, CARD[1] + 115), "big", 72, 260, 90,
                      fill=RED, scale=back_out((lt - t_done) / 0.35))

    def curve_end(self, s, lt, xs) -> tuple[float, float]:
        """Abscisse atteinte par la courbe à l'instant lt, et instant (relatif) où elle est complète.
        `sync` : [{"x": 2009, "at": "w:2008@L2"}, ...] -> la courbe arrive à x quand la voix le dit
        sinon tracé
        régulier en `draw_seconds` (4 s par défaut)."""
        knots = [(0.4, xs[0])]
        for k in s.get("sync", []):
            knots.append((self.tl.t(k["at"]) - s["t0"], float(k["x"])))
        if not s.get("sync") or knots[-1][1] < xs[-1]:
            knots.append((knots[-1][0] + (float(s.get("draw_seconds", 4.0)) if not s.get("sync") else 1.2), xs[-1]))
        knots.sort()
        if lt <= knots[0][0]:
            return xs[0], knots[-1][0]
        for (ta, xa), (tb, xb) in itertools.pairwise(knots):
            if lt < tb:
                return xa + (xb - xa) * ease_out((lt - ta) / max(1e-3, tb - ta)), knots[-1][0]
        return xs[-1], knots[-1][0]

    def s_barres(self, img, s, lt):
        self._card(img, s, lt, s.get("chart_title"))
        bars = s["bars"]
        n = len(bars)
        top, base = CARD[1] + 240, CARD[3] - 140
        vmax = max(float(b["value"]) for b in bars)
        span = SAFE_R - 40 - (CARD[0] + 60)
        bw = min(200, span / n * 0.62)
        d = ImageDraw.Draw(img)
        hl = s.get("highlight", n - 1)
        for i, b in enumerate(bars):
            g = ease_out((lt - 0.4 - i * 0.6) / 1.0)
            cx = CARD[0] + 60 + span * (i + 0.5) / n
            h = (base - top) * float(b["value"]) / vmax * g
            col = RED if i == hl else (95, 98, 104)
            if h > 1:
                d.rectangle([cx - bw / 2, base - h, cx + bw / 2, base], fill=col)
            draw_text(img, b["label"], cx, base + 38, "ui", 34, span / n, 44, fill=INK)
            if g > 0.05:
                draw_text(img, b.get("text") or fr_num(float(b["value"]) * g), cx, base - h - 40, "big", 58,
                          span / n + 20, 70, fill=col)
        if s.get("delta"):
            p = back_out((lt - 0.4 - n * 0.6 - 0.3) / 0.35)
            draw_text(img, s["delta"], CARD[0] + 60 + span / 2, CARD[1] + 122, "big", 66, 300, 80, fill=RED, scale=p)

    def s_points(self, img, s, lt):
        items = s["items"]
        colors = [(MINT, INK), (GOLD, INK), (RED, CREAM)]
        ats = [self.tl.t(a) - s["t0"] for a in s.get("at", [])] or [0.5 + k * 1.6 for k in range(len(items))]
        h = 210 if len(items) == 3 else 250
        gap = (CARD[3] - 40 - CARD[1] - len(items) * h) / max(1, len(items) - 1) if len(items) > 1 else 0
        for k, it in enumerate(items):
            p = back_out((lt - ats[k]) / 0.35)
            if p <= 0.02:
                continue
            fill, txt = colors[k % 3]
            y = CARD[1] + 20 + k * (h + gap) + h / 2
            hw, hh = 430 * p, h / 2 * p
            rrect(img, (495 - hw, y - hh, 495 + hw, y + hh), int(36 * p), fill)
            draw_text(img, it, 495, y, "ui", 50, 780, h - 40, fill=txt, scale=p)

    def s_fin(self, img, s, lt):
        draw_text(img, s.get("kicker", "DEMAIN"), 495, 470, "ui", 64, 860, 80, fill=MINT, alpha=ease_out(lt / 0.3))
        draw_text(img, s.get("next", ""), 495, 680, "serif", 100, 860, 300, scale=back_out((lt - 0.2) / 0.4),
                  spacing=1.0)
        p = back_out((lt - 0.9) / 0.4) * (1 + 0.04 * math.sin(lt * 8) if lt > 1.3 else 1)
        if p > 0.05:
            rrect(img, (495 - 320 * p, 1000 - 80 * p, 495 + 320 * p, 1000 + 80 * p), int(80 * p), RED)
            draw_text(img, "ABONNE-TOI", 495, 1000, "big", 92, 600, 120, fill=CREAM, scale=p)
        draw_text(img, s.get("promise", "L'actu éco expliquée simplement."), 495, 1140, "ui2", 50, 860, 70,
                  alpha=ease_out((lt - 1.4) / 0.4))
        draw_text(img, DISCLAIMER, 495, 1215, "ui2", 28, 860, 44, fill=(150, 175, 165),
                  alpha=ease_out((lt - 1.4) / 0.4))
