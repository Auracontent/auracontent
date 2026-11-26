"""Images du format « expliqué par un bonhomme » : chaque image est calculée à partir du temps (rendu parallèle,
planche à n'importe quel instant). Deux formats pour le même plan :

  vertical (1080 x 1920, Shorts) : zone sûre x 60-930, y 200-1440 (interface YouTube/TikTok au-delà)
    215-415   titre écrit à la main (2 lignes) + titre2 (jaune)
    440-950   accessoires (cadre virtuel 1000 x 560)
    915-1435  le bonhomme (pieds à y = 1435)
  paysage (1920 x 1080, vidéos longues)
    40-215    titre + titre2
    230-1010  accessoires à droite ; bonhomme à gauche (pieds à y = 1045)
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from . import draw as D

if TYPE_CHECKING:
    from pathlib import Path

    from auracontent.archive.timeline import Timeline

NNBSP = "\u202f"          # espace fine insécable entre les milliers

LAYOUTS = {
    "vertical": {
        "size": (1080, 1920), "props": (60, 440, 930, 950), "fig_y": 1435, "fig_s": 1.0,
        "fig_x": {"gauche": 300, "centre": 495, "droite": 690}, "fig_default": "centre",
        "title_y": 295, "title_size": 78, "title_w": 860, "title_lines": 2, "title2_y": 405, "title2_size": 58,
        "hook_size": 112, "look": 0.0,
    },
    "paysage": {
        "size": (1920, 1080), "props": (820, 230, 1870, 1010), "fig_y": 1045, "fig_s": 1.31,
        "fig_x": {"gauche": 400, "centre": 400, "droite": 400}, "fig_default": "gauche",
        "title_y": 100, "title_size": 78, "title_w": 1780, "title_lines": 1, "title2_y": 188, "title2_size": 64,
        "hook_size": 150, "look": 0.7,
    },
}
DISCLAIMER = "Contenu pédagogique, pas un conseil en investissement."
DEFAULT_POSE = {"accroche": ("triste", "bas"), "compteur": ("content", "bas"), "notifications": ("stresse", "bas"),
                "choix": ("pense", "menton"), "repartition": ("content", "montre"), "liste": ("content", "montre"),
                "fin": ("content", "salut")}


class Renderer:
    def __init__(self, episode: Path, tl: Timeline):
        self.ep, self.tl = episode, tl
        self.fmt = tl.plan.get("format", "vertical")
        self.L = LAYOUTS[self.fmt]
        self.W, self.H = self.L["size"]
        self.box = D.Box(self.L["props"])
        self.scenes = []
        raw = tl.plan["scenes"]
        for i, sc in enumerate(raw):
            t0 = tl.t(sc["from"])
            t1 = tl.t(raw[i + 1]["from"]) if i + 1 < len(raw) else tl.dur
            self.scenes.append({**sc, "t0": t0, "t1": t1})

    # ---------- temps ----------
    def at(self, sc: dict, ref, default: float) -> float:
        return self.tl.t(ref) if ref is not None else sc["t0"] + default

    def scene_at(self, t: float) -> dict:
        cur = self.scenes[0]
        for sc in self.scenes:
            if sc["t0"] <= t + 1e-6:
                cur = sc
        return cur

    # ---------- image ----------
    def frame(self, fi: int) -> np.ndarray:
        t = fi / 30.0
        sc = self.scene_at(t)
        pen = D.Pen(self.W, self.H)
        u = t - sc["t0"]
        if sc.get("pluie"):
            D.rain(pen, t)
        getattr(self, "_" + sc["type"])(pen, sc, t, u)
        self._titles(pen, sc, t)
        self._figure(pen, sc, t)
        return np.asarray(pen.image())

    def _titles(self, pen: D.Pen, sc: dict, t: float):
        L = self.L
        hook = sc["type"] == "accroche"
        if sc.get("title"):
            t0 = self.at(sc, sc.get("title_at"), 0.05)
            size0 = L["hook_size"] if hook else L["title_size"]
            col = D.color(sc.get("title_color"), D.RED if hook else D.WHITE)
            size, lines = D.fit(sc["title"], size0, L["title_w"], L["title_lines"] if not hook else 2)
            y = L["title_y"] + ((30 if self.fmt == "vertical" else 40) if hook else 0)
            pen.block(self.W / 2, y, lines, size, col, reveal=(t - t0) / (1.4 if hook else 0.9))
        if sc.get("title2"):
            t0 = self.at(sc, sc.get("title2_at"), 1.5)
            size, lines = D.fit(sc["title2"], L["title2_size"], L["title_w"], 1)
            y = L["title2_y"] + (40 if hook and self.fmt == "vertical" else 0)
            pen.block(self.W / 2, y, lines, size, D.color(sc.get("title2_color"), D.YELLOW), reveal=(t - t0) / 0.8)

    def _figure(self, pen: D.Pen, sc: dict, t: float):
        bh = sc.get("bonhomme") or {}
        if bh.get("cache"):
            return
        expr, arms = DEFAULT_POSE.get(sc["type"], ("neutre", "bas"))
        expr, arms = bh.get("expr", expr), bh.get("arms", arms)
        hop = 0.0
        for r in sorted(bh.get("reactions", []), key=lambda r: self.tl.t(r["at"])):
            ra = self.tl.t(r["at"])
            if ra <= t:
                expr, arms = r.get("expr", expr), r.get("arms", arms)
                if r.get("hop") and t - ra < 0.9:
                    hop = abs(math.sin((t - ra) * 7)) * 45 * (1 - (t - ra) / 0.9)
        L = self.L
        pos = bh.get("pos", L["fig_default"])
        D.figure(pen, L["fig_x"].get(pos, L["fig_x"][L["fig_default"]]), L["fig_y"], L["fig_s"], expr, arms, t,
                 hop=hop, look=L["look"])

    # ---------- scènes (coordonnées virtuelles 1000 x 560) ----------
    def _accroche(self, pen, sc, t, u):
        b = self.box
        if sc.get("carte"):
            D.bank_card(pen, b, 500, 200, sc["carte"], D.back((t - self.at(sc, sc.get("carte_at"), 1.2)) / 0.5))
        if sc.get("sous_titre"):
            t0 = self.at(sc, sc.get("sous_titre_at"), 2.5)
            size, lines = D.fit(sc["sous_titre"], b.s(66), b.s(980), 2)
            pen.block(*b.p(500, 420), lines, size, D.YELLOW, reveal=(t - t0) / 0.9)

    def _compteur(self, pen, sc, t, u):
        b = self.box
        c0 = self.at(sc, sc.get("count_at"), 0.4)
        k = D.ease((t - c0) / float(sc.get("count_seconds", 1.8)))
        start, end = float(sc.get("start", 0)), float(sc["value"])
        val = start + (end - start) * k
        txt = sc.get("format", "{n} €").replace("{n}", f"{round(val):,}".replace(",", NNBSP))
        col = D.color(sc.get("color"), D.GOLD if end >= start else D.RED)
        size, lines = D.fit(txt, b.s(130), b.s(960), 1)
        pen.text(*b.p(500, 110), lines[0], size, col)
        if sc.get("legende"):
            size, lines = D.fit(sc["legende"], b.s(46), b.s(960), 1, min_size=10)
            pen.text(*b.p(500, 215), lines[0], size, D.WHITE, reveal=(t - c0) / 0.8)
        if sc.get("pieces") == "pile":
            D.coin_pile(pen, b, 500, 500, 14, k)
        elif sc.get("pieces") == "fuite":
            self._leak(pen, t, c0, 8, (420, 360))

    def _leak(self, pen, t, t0, n, origin):
        b = self.box
        for i in range(n):
            k = t - t0 - i * 0.45
            if 0 < k < 1.3:
                D.coin(pen, b, origin[0] + k * 700, origin[1] - math.sin(k * 2.4) * 300, 28)

    def _notifications(self, pen, sc, t, u):
        b = self.box
        items = sc["items"]
        ats = [self.tl.t(a) for a in sc["at"]] if sc.get("at") else [sc["t0"] + 0.6 + 0.7 * i for i in range(len(items))]
        cx = 680 if sc.get("compteur") else 500
        D.phone(pen, b, cx, 300, 500)
        step = min(86, 400 / max(1, len(items)))
        for i, (it, a) in enumerate(zip(items, ats, strict=True)):
            D.notif(pen, b, cx, 130 + i * step, it, (t - a) / 0.35, 236)
        cp = sc.get("compteur")
        if cp:
            start, end = float(cp.get("start", 0)), float(cp["value"])
            k = D.ease((t - ats[0]) / max(0.5, ats[-1] - ats[0] + 0.5))
            val = start + (end - start) * k
            txt = cp.get("format", "{n} €").replace("{n}", f"{round(val):,}".replace(",", NNBSP))
            col = D.RED if end < start and k > 0.6 else D.WHITE
            size, lines = D.fit(txt, b.s(100), b.s(420), 1)
            pen.text(*b.p(230, 200), lines[0], size, col)
            if cp.get("fuite", True):
                self._leak(pen, t, ats[0] + 0.2, len(items) + 3, (230, 300))

    def _choix(self, pen, sc, t, u):
        b = self.box
        brain = sc.get("cerveau", True)
        if brain:
            D.brain_bubble(pen, b, 170, 250, D.back((t - sc["t0"] - 0.3) / 0.6))
        xs = (510, 830) if brain else (300, 700)
        for side, x, a_def, col_def in (("left", xs[0], 1.0, "vert"), ("right", xs[1], 2.4, "gris")):
            o = sc[side]
            a = D.back((t - self.at(sc, o.get("at"), a_def)) / 0.5)
            D.value_box(pen, b, x, 260, 290, 220, o.get("label", ""), o.get("value", ""), D.color(o.get("couleur"), D.color(col_def)), a)
        if "pick" in sc:
            p0 = self.at(sc, sc.get("pick_at"), 4.0)
            k = D.ease((t - p0) / 0.6)
            x = xs[int(sc["pick"])]
            if brain and int(sc["pick"]) == 0:
                D.arrow(pen, b, 330, 260, 360, 260, k, D.RED)
            pen.arc(*b.p(x, 260), b.s(175), 0, 360 * k, D.RED, b.s(9))
            if sc.get("pick_label"):
                size, lines = D.fit(sc["pick_label"], b.s(54), b.s(600), 1, min_size=10)
                pen.text(*b.p(x, 485), lines[0], size, D.RED, reveal=(t - p0 - 0.6) / 0.8)

    def _repartition(self, pen, sc, t, u):
        b = self.box
        src = sc.get("source_label", "salaire")
        x0, y0 = b.p(40, 225)
        x1, y1 = b.p(270, 335)
        pen.rect(x0, y0, x1, y1, out=D.GOLD, w=b.s(7), rad=b.s(18))
        size, lines = D.fit(src, b.s(58), b.s(200), 1, min_size=10)
        pen.text(*b.p(155, 280), lines[0], size, D.GOLD)
        parts = sc["parts"]
        ys = {1: [280], 2: [130, 430], 3: [70, 280, 490]}[len(parts)]
        for i, (p, y) in enumerate(zip(parts, ys, strict=True)):
            a0 = self.at(sc, p.get("at"), 0.8 + 1.4 * i)
            col = D.color(p.get("couleur"), D.GREEN if i == 0 else D.GREY)
            k = D.ease((t - a0) / 0.7)
            D.arrow(pen, b, 285, 280, 470, y, k, col)
            if k > 0.9:
                if p.get("bocal"):
                    D.jar(pen, b, 570, y + 10, D.ease((t - a0 - 0.7) / 1.4) * float(p.get("fill", 0.7)), col, 0.55)
                size, lines = D.fit(p["label"], b.s(50), b.s(330), 2, min_size=10)
                pen.block(*b.p(830, y), lines, size, col if p.get("bocal") else D.WHITE, reveal=(t - a0 - 0.7) / 0.6)

    def _liste(self, pen, sc, t, u):
        b = self.box
        items = sc["items"]
        ats = [self.tl.t(a) for a in sc["at"]] if sc.get("at") else [sc["t0"] + 0.5 + 1.2 * i for i in range(len(items))]
        ys = {1: [280], 2: [160, 400], 3: [90, 280, 470]}[len(items)]
        for i, (it, a, y) in enumerate(zip(items, ats, ys, strict=True)):
            k = D.back((t - a) / 0.45)
            if k <= 0:
                continue
            x0, y0 = b.p(500 - 470 * k, y - 80)
            x1, y1 = b.p(500 + 470 * k, y + 80)
            pen.rect(x0, y0, x1, y1, out=D.WHITE, w=b.s(6), rad=b.s(24))
            if k > 0.8:
                pen.circ(*b.p(90, y), b.s(42), fill=D.YELLOW)
                pen.text(*b.p(90, y), str(i + 1), b.s(54), D.BLACK)
                size, lines = D.fit(it, b.s(48), b.s(780), 2, min_size=10)
                pen.block(*b.p(555, y), lines, size, D.WHITE)

    def _fin(self, pen, sc, t, u):
        b = self.box
        pen.text(*b.p(500, 80), sc.get("kicker", "la suite :"), b.s(64), D.WHITE, reveal=u / 0.5)
        size, lines = D.fit(sc["next"], b.s(86), b.s(960), 2)
        pen.block(*b.p(500, 230), lines, size, D.YELLOW, reveal=(u - 0.4) / 1.0)
        pen.text(*b.p(500, 370), "Capital Simple", b.s(54), D.GREEN, "petit")
        pen.text(*b.p(500, 445), DISCLAIMER, b.s(32), D.GREY, "petit")


def stills_times(r: Renderer) -> list[float]:
    ts = [0.4, 1.5]
    for s in r.scenes:
        ts += [s["t0"] + min(2.5, (s["t1"] - s["t0"]) * 0.5), s["t1"] - 0.15]
    return sorted({round(min(r.tl.dur - 0.05, max(0.0, x)), 2) for x in ts})
