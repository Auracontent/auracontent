"""Rendu image par image d'un short d'archives (1080x1920, 30 i/s) à partir de plan.json.

Types de plans (clé "type", "image" par défaut) :
  image  {"image": clé, "keys": [[u, cx, cy, h], ...], "fx": {"gray": 1, "dark": 0.2, "shake": 1}}
         u : 0..1 dans le plan ; cx, cy : centre du cadre (0..1 de l'image) ; h : hauteur du cadre (0..1)
  fog    brouillard sombre animé (océan, disparition, ellipse)
  split  {"top": {"image", "keys"}, "bottom": {"image", "keys"}, "labels": ["HAUT", "BAS"]}
  map    {"bbox": [lon0, lon1, lat0, lat1], "cam": [[u, cx, cy, h]], "pins": [{"lon", "lat", "label", "at"}],
          "route": {"from": [lon, lat], "to": [lon, lat], "at": réf, "until": réf, "cross": true},
          "names": [{"text", "lon", "lat"}], "fog": [début, fin]}
  sign   plaque de rue : {"lines": ["RUE", "NOM", "« inscription »"], "background": clé}
  card   carton texte : {"title": "9 MAI 1927", "sub": "TERRE-NEUVE", "background": clé (facultatif)}
"""
from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from config.settings import ASSETS_DIR

from .timeline import FPS, H, W, Timeline

FONTS = ASSETS_DIR / "archive" / "fonts"
ANTON, MONT, SERIF = FONTS / "Anton-Regular.ttf", FONTS / "Montserrat-Variable.ttf", FONTS / "Caladea-Bold.ttf"
YEL = (255, 212, 0); RED = (214, 46, 40); WHITE = (255, 255, 255); INK = (20, 14, 12)
CAPTION_Y = 1344        # 70 % de la hauteur, au-dessus de la zone basse (y > 1440) couverte par les plateformes
HEADER_Y = 300; LABEL_Y = 420; STAMP_Y = 1060; HOOK_TOP = 215


@lru_cache(maxsize=64)
def font(path: Path, size: int, var: str | None = None) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(path), size)
    if var:
        f.set_variation_by_name(var)
    return f


def ease(x: float) -> float:
    x = min(1.0, max(0.0, x)); return x * x * (3 - 2 * x)


def paste(fr: np.ndarray, spr: np.ndarray, cx: float, cy: float, alpha: float = 1.0, scale: float = 1.0) -> None:
    if alpha <= 0:
        return
    if scale != 1.0:
        spr = cv2.resize(spr, (max(1, int(spr.shape[1] * scale)), max(1, int(spr.shape[0] * scale))))
    h, w = spr.shape[:2]; x0, y0 = int(cx - w / 2), int(cy - h / 2)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(fr.shape[1], x0 + w), min(fr.shape[0], y0 + h)
    if xa >= xb or ya >= yb:
        return
    s = spr[ya - y0:yb - y0, xa - x0:xb - x0].astype(np.float32); a = s[..., 3:4] / 255 * alpha
    fr[ya:yb, xa:xb] = fr[ya:yb, xa:xb] * (1 - a) + s[..., :3] * a


def keyed(keys, u):
    keys = [list(k) for k in keys]
    if len(keys) == 1:
        return keys[0][1:]
    for (f0, *a), (f1, *b) in zip(keys, keys[1:]):
        if u <= f1:
            v = ease((u - f0) / max(1e-6, f1 - f0)); return [p + (q - p) * v for p, q in zip(a, b)]
    return keys[-1][1:]


class Renderer:
    def __init__(self, episode: Path, tl: Timeline):
        self.ep, self.tl, self.plan = episode, tl, tl.plan
        self.rng = np.random.default_rng(3)
        self.images: dict[str, np.ndarray] = {}
        self.shots = []
        for s in self.plan["shots"]:
            d = dict(s); d["t0"], d["t1"] = tl.t(s["from"]), tl.t(s["to"]); self.shots.append(d)
        self.shots.sort(key=lambda s: s["t0"])
        self._check_shots()
        self.keywords = {k.lower() for k in self.plan.get("keywords", [])}
        self.stamps = [(self._stamp(s["text"], int(s.get("size", 150))), tl.t(s["at"]), tl.t(s.get("until", "fin")),
                        int(s.get("y", STAMP_Y))) for s in self.plan.get("stamps", [])]
        self.labels = [(self._label(s["text"]), tl.t(s["from"]), tl.t(s["to"]), int(s.get("y", LABEL_Y)))
                       for s in self.plan.get("labels", [])]
        self.flashes = [tl.t(x) for x in self.plan.get("flash", [])]
        self.hook = self._hook(self.plan["hook"]); self.hook_end = float(self.plan.get("hook_seconds", 3.6))
        self.header = self._header(self.plan.get("header", ""))
        self.endcard = self._endcard(self.plan.get("end_title", ""), self.plan.get("end_sub", ["LE DOCUMENTAIRE COMPLET", "SUR LA CHAÎNE"]))
        self.wm = self._watermark()
        self.caps: dict[int, np.ndarray] = {}
        self.maps: dict[int, tuple] = {}
        yy, xx = np.mgrid[0:H, 0:W]
        self.vig = (1 - 0.6 * (((xx - W / 2) / (W / 2)) ** 2 * 0.7 + ((yy - H / 2) / (H / 2)) ** 2) ** 1.4).clip(0.3, 1)[..., None].astype(np.float32)
        g = np.ones((H, 1, 1), np.float32); g[:420, 0, 0] = np.linspace(0.5, 1, 420); g[H - 900:, 0, 0] = np.linspace(1, 0.62, 900)
        self.grad = g
        self.grain = [cv2.GaussianBlur(self.rng.normal(0, 8, (H, W)).astype(np.float32), (0, 0), 0.8)[..., None] for _ in range(6)]
        fog = cv2.GaussianBlur(self.rng.normal(0, 1, (900, 2400)).astype(np.float32), (0, 0), 40)
        self.fog_tex = (fog - fog.min()) / (fog.max() - fog.min())

    # ---------- vérifications ----------
    def _check_shots(self):
        if not self.shots:
            raise ValueError("plan.json : aucun plan")
        if self.shots[0]["t0"] > 0.01:
            raise ValueError("plan.json : le premier plan doit commencer à 0")
        for a, b in zip(self.shots, self.shots[1:]):
            if abs(a["t1"] - b["t0"]) > 0.05:
                raise ValueError(f"plan.json : trou ou chevauchement entre {a['from']}→{a['to']} et {b['from']}→{b['to']}")
        if self.shots[-1]["t1"] < self.tl.dur - 0.05:
            raise ValueError("plan.json : le dernier plan doit aller jusqu'à \"fin\"")
        for s in self.shots:
            kind = s.get("type", "image")
            for key in [s.get("image"), s.get("background"), (s.get("top") or {}).get("image"), (s.get("bottom") or {}).get("image")]:
                if key and not (self.ep / "img" / f"{key}.jpg").exists():
                    raise ValueError(f"plan.json : image « {key} » absente de img/ (plan {kind} {s['from']})")

    # ---------- sources ----------
    def img(self, key: str) -> np.ndarray:
        if key not in self.images:
            a = cv2.imread(str(self.ep / "img" / f"{key}.jpg"), cv2.IMREAD_COLOR)[..., ::-1].astype(np.float32)
            g = a.mean(axis=2, keepdims=True)
            grade = self.plan.get("grade", "sepia")
            if grade == "sepia":
                a = 0.35 * a + 0.65 * np.concatenate([g * 1.07, g * 0.98, g * 0.84], axis=2)
            a = (a - a.mean()) * 1.18 + a.mean()
            self.images[key] = np.clip(a, 0, 255).astype(np.uint8)
        return self.images[key]

    def crop(self, key, cx, cy, h, ow=W, oh=H) -> np.ndarray:
        a = self.img(key); ih, iw = a.shape[:2]
        ch = h * ih; cw = ch * ow / oh
        if cw > iw:
            cw = iw; ch = cw * oh / ow
        x0 = min(max(cx * iw - cw / 2, 0), iw - cw); y0 = min(max(cy * ih - ch / 2, 0), ih - ch); s = ow / cw
        return cv2.warpAffine(a, np.float32([[s, 0, -x0 * s], [0, s, -y0 * s]]), (ow, oh), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)

    def fog(self, t: float) -> np.ndarray:
        x = int(80 + t * 60) % 1200
        f = cv2.resize(self.fog_tex[:, x:x + 506], (W, H))
        return np.array([28, 34, 40], np.float32) + f[..., None] * np.array([63, 70, 76], np.float32)

    def blurred(self, key: str | None) -> np.ndarray:
        if not key:
            return self.fog(0)
        return cv2.GaussianBlur(self.crop(key, 0.5, 0.5, 1.0).astype(np.float32), (0, 0), 18) * 0.35

    # ---------- habillage ----------
    def _stamp(self, text, size):
        f = font(ANTON, size); bw = f.getbbox(text)[2]; w, h = bw + 90, int(size * 1.55)
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rectangle([8, 8, w - 8, h - 8], outline=RED + (240,), width=max(6, size // 13))
        d.text((45, int(size * 0.12)), text, font=f, fill=RED + (240,))
        a = np.asarray(im).astype(np.float32); a[..., 3][self.rng.random(a.shape[:2]) < 0.14] *= 0.2
        out = Image.fromarray(a.astype(np.uint8)).rotate(-8, expand=True, resample=Image.BICUBIC)
        if out.width > 860:
            out = out.resize((860, int(out.height * 860 / out.width)))
        return np.asarray(out)

    def _label(self, text, size=42):
        f = font(MONT, size, "ExtraBold"); bw = f.getbbox(text)[2]
        im = Image.new("RGBA", (bw + 56, int(size * 1.9)), (14, 12, 10, 225))
        ImageDraw.Draw(im).text((28, int(size * 0.35)), text, font=f, fill=(245, 238, 222, 255))
        if im.width > 860:
            im = im.resize((860, int(im.height * 860 / im.width)))
        return np.asarray(im)

    def _hook(self, lines):
        im = Image.new("RGBA", (W, 480), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        for i, tx in enumerate(lines[:3]):
            size = 116
            while font(ANTON, size).getbbox(tx)[2] > W - 140 and size > 60:
                size -= 4
            f = font(ANTON, size); bw = f.getbbox(tx)[2]
            c = YEL if i == len(lines) - 1 and len(lines) > 1 else WHITE
            d.text(((W - bw) // 2, 10 + i * 145), tx, font=f, fill=c + (255,), stroke_width=8, stroke_fill=INK + (255,))
        return np.asarray(im)

    def _header(self, tx):
        if not tx:
            return None
        f = font(ANTON, 60); bw = f.getbbox(tx)[2]
        im = Image.new("RGBA", (bw + 60, 104), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((30, 10), tx, font=f, fill=(250, 246, 236, 255), stroke_width=6, stroke_fill=INK + (255,))
        return np.asarray(im)

    def _endcard(self, title, sub):
        im = Image.new("RGBA", (W, 560), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        size = 150
        while title and font(ANTON, size).getbbox(title)[2] > W - 120:
            size -= 6
        rows = ([(title, font(ANTON, size), WHITE, 0)] if title else []) + \
               [(s, font(MONT, 54, "Black"), YEL, 230 + 75 * i) for i, s in enumerate(sub)]
        for tx, f, c, y in rows:
            bw = f.getbbox(tx)[2]; d.text(((W - bw) // 2, y), tx, font=f, fill=c + (255,), stroke_width=7, stroke_fill=INK + (255,))
        return np.asarray(im)

    def _watermark(self):
        b = self.plan.get("brand", {})
        path = ASSETS_DIR / b.get("watermark", "mystery/images/cest_arrive_ici_watermark.png")
        if not path.exists():
            return None
        im = Image.open(path).convert("RGBA"); w = int(b.get("watermark_width", 190))
        im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
        return np.asarray(im), float(b.get("watermark_opacity", 0.85)), int(b.get("watermark_x", 42)), int(b.get("watermark_y", 56))

    def caption(self, i: int) -> np.ndarray:
        if i in self.caps:
            return self.caps[i]
        words = self.tl.chunks[i][2]
        toks = [re.sub(r"[,.:;]+$", "", w[2]).replace(" ", " ").upper() for w in words]

        def hot(w):
            parts = re.sub(r"[^\w'’ -]", "", w.lower()).split(" ")
            return any(p in self.keywords for p in parts) or bool(re.search(r"\d", w))
        cols = [YEL if hot(w[2]) else WHITE for w in words]
        f = font(MONT, 94, "Black"); sp = 26; widths = [f.getbbox(t)[2] for t in toks]
        tw = sum(widths) + sp * (len(toks) - 1); pad = 30
        im = Image.new("RGBA", (tw + 2 * pad, 150), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = pad
        for t, c, wd in zip(toks, cols, widths):
            d.text((x, 18), t, font=f, fill=c + (255,), stroke_width=9, stroke_fill=INK + (255,)); x += wd + sp
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sh.putalpha(im.getchannel("A").filter(ImageFilter.GaussianBlur(10)).point(lambda v: v * 0.6))
        out = Image.new("RGBA", im.size, (0, 0, 0, 0)); out.alpha_composite(sh, (0, 6)); out.alpha_composite(im)
        a = np.asarray(out)
        if a.shape[1] > W - 60:
            a = cv2.resize(a, (W - 60, int(a.shape[0] * (W - 60) / a.shape[1])))
        self.caps[i] = a
        return a

    # ---------- plans ----------
    def shot_frame(self, s: dict, t: float) -> np.ndarray:
        u = (t - s["t0"]) / max(1e-6, s["t1"] - s["t0"]); kind = s.get("type", "image")
        if kind == "fog":
            return self.fog(t)
        if kind == "split":
            top = self.crop(s["top"]["image"], *keyed(s["top"]["keys"], u), W, H // 2)
            bot = self.crop(s["bottom"]["image"], *keyed(s["bottom"]["keys"], u), W, H // 2)
            fr = np.concatenate([top, bot], 0).astype(np.float32); fr[H // 2 - 5:H // 2 + 5] = 245
            for txt, y in zip(s.get("labels", []), (H // 2 - 70, H // 2 + 80)):
                paste(fr, self._label_cached(txt), W / 2, y)
            return fr
        if kind == "map":
            return self.map_frame(s, t, u)
        if kind == "sign":
            return self.sign_frame(s, u)
        if kind == "card":
            fr = self.blurred(s.get("background")).copy() if s.get("background") else self.fog(t)
            v = ease(u * 4)
            paste(fr, self._card_cached(s.get("title", ""), s.get("sub", "")), W / 2, 880 - (1 - v) * 60, v, 0.9 + 0.1 * v)
            return fr
        cx, cy, h = keyed(s["keys"], u); fx = s.get("fx", {})
        if fx.get("shake"):
            cx += 0.004 * math.sin(t * 37) + 0.003 * math.sin(t * 23); cy += 0.004 * math.sin(t * 29)
        fr = self.crop(s["image"], cx, cy, h).astype(np.float32)
        if fx.get("gray"):
            fr[:] = fr.mean(axis=2, keepdims=True)
        if fx.get("dark"):
            fr *= 1 - float(fx["dark"])
        return fr

    @lru_cache(maxsize=32)
    def _label_cached(self, txt):
        return self._label(txt)

    @lru_cache(maxsize=16)
    def _card_cached(self, title, sub):
        im = Image.new("RGBA", (W, 420), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        size = 170
        while font(ANTON, size).getbbox(title)[2] > W - 120:
            size -= 6
        for tx, f, c, y in [(title, font(ANTON, size), WHITE, 0), (sub, font(MONT, 58, "Black"), YEL, size + 40)]:
            if tx:
                bw = f.getbbox(tx)[2]; d.text(((W - bw) // 2, y), tx, font=f, fill=c + (255,), stroke_width=7, stroke_fill=INK + (255,))
        return np.asarray(im)

    def sign_frame(self, s, u):
        fr = self.blurred(s.get("background")).copy()
        key = repr(s["lines"])
        if key not in self.maps:
            lines = s["lines"]; w, h = 940, 160 + 110 * len(lines)
            sg = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(sg)
            d.rounded_rectangle([0, 0, w - 1, h - 1], radius=34, fill=(26, 60, 116, 255), outline=(240, 240, 240, 255), width=12)
            d.rounded_rectangle([26, 26, w - 27, h - 27], radius=22, outline=(240, 240, 240, 255), width=4)
            y = 70
            for i, tx in enumerate(lines):
                size = 84 if i == 1 else (64 if i == 0 else 46)
                while font(SERIF, size).getbbox(tx)[2] > w - 90:
                    size -= 4
                f = font(SERIF, size); bw = f.getbbox(tx)[2]; d.text(((w - bw) // 2, y), tx, font=f, fill=(244, 244, 244, 255))
                y += int(size * 1.35)
            shd = Image.new("RGBA", (w + 80, h + 80), (0, 0, 0, 0))
            ImageDraw.Draw(shd).rounded_rectangle([40, 40, w + 40, h + 40], 34, fill=(0, 0, 0, 200))
            self.maps[key] = (np.asarray(sg), np.asarray(shd.filter(ImageFilter.GaussianBlur(24))))
        sg, shd = self.maps[key]; v = ease(u * 4); sc = 0.86 + 0.14 * v + 0.04 * u
        paste(fr, shd, W / 2, 912, v, sc); paste(fr, sg, W / 2, 900 - (1 - v) * 80, v, sc)
        return fr

    # ---------- carte ----------
    def _map(self, s):
        key = repr((s["bbox"], s.get("names")))
        if key in self.maps:
            return self.maps[key]
        from global_land_mask import globe
        lo0, lo1, la0, la1 = s["bbox"]
        kx = math.cos(math.radians((la0 + la1) / 2))
        mw = 1300; mh = int(mw * (la1 - la0) / ((lo1 - lo0) * kx))
        lon = np.linspace(lo0, lo1, mw); lat = np.linspace(la1, la0, mh); LO, LA = np.meshgrid(lon, lat)
        land = globe.is_land(LA, LO).astype(np.uint8)
        sea = np.zeros((mh, mw, 3), np.float32); sea[:] = (190, 180, 150); sea += self.rng.normal(0, 5, (mh, mw, 1))
        img = np.where(land[..., None] > 0, np.array([224, 210, 176], np.float32), sea)
        dist = cv2.distanceTransform((1 - land).astype(np.uint8), cv2.DIST_L2, 3)
        for r in (7, 15, 26):
            ring = (np.abs(dist - r) < 0.9) & (land == 0); img[ring] *= 0.85
        img[cv2.morphologyEx(land, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8)) > 0] = (70, 58, 46)
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)); d = ImageDraw.Draw(im)
        step = max(1, round((lo1 - lo0) / 5))
        for lo in range(math.ceil(lo0), math.floor(lo1) + 1, step):
            x = (lo - lo0) / (lo1 - lo0) * mw; d.line([(x, 0), (x, mh)], fill=(150, 138, 112), width=2)
        for la in range(math.ceil(la0), math.floor(la1) + 1, step):
            y = (la1 - la) / (la1 - la0) * mh; d.line([(0, y), (mw, y)], fill=(150, 138, 112), width=2)
        for n in s.get("names", []):
            x, y = (n["lon"] - lo0) / (lo1 - lo0) * mw, (la1 - n["lat"]) / (la1 - la0) * mh
            f = font(SERIF, int(n.get("size", 56))); bw = f.getbbox(n["text"])[2]
            d.text((x - bw / 2, y), n["text"], font=f, fill=(105, 92, 72))
        self.maps[key] = (np.asarray(im).astype(np.float32), (lo0, lo1, la0, la1))
        return self.maps[key]

    def map_frame(self, s, t, u):
        M, (lo0, lo1, la0, la1) = self._map(s); mh, mw = M.shape[:2]
        cx, cy, h = keyed(s.get("cam", [[0, 0.5, 0.5, 1.0]]), u)
        ch = h * mh; cw = ch * W / H
        if cw > mw:
            cw = mw; ch = cw * H / W
        x0 = min(max(cx * mw - cw / 2, 0), mw - cw); y0 = min(max(cy * mh - ch / 2, 0), mh - ch); sc = W / cw
        fr = cv2.warpAffine(M, np.float32([[sc, 0, -x0 * sc], [0, sc, -y0 * sc]]), (W, H), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REFLECT)

        def P(lon, lat):
            return (((lon - lo0) / (lo1 - lo0) * mw - x0) * sc, ((la1 - lat) / (la1 - la0) * mh - y0) * sc)
        r = s.get("route")
        if r:
            a, b = P(*r["from"]), P(*r["to"]); ta, tb = self.tl.t(r.get("at", s["from"])), self.tl.t(r.get("until", s["to"]))
            k = min(1.0, max(0.0, (t - ta) / max(0.1, tb - ta)))
            bend = float(r.get("bend", 0.25)) * math.hypot(b[0] - a[0], b[1] - a[1])
            pts = [(a[0] + (b[0] - a[0]) * q, a[1] + (b[1] - a[1]) * q - bend * math.sin(math.pi * q)) for q in np.linspace(0, k, 70)]
            for i in range(0, len(pts) - 1, 2):
                cv2.line(fr, tuple(map(int, pts[i])), tuple(map(int, pts[i + 1])), RED, 9, cv2.LINE_AA)
            if r.get("cross") and k >= 1:
                v = min(1.0, (t - tb) / 0.15); x, y = map(int, b); rr = int(46 * v)
                cv2.line(fr, (x - rr, y - rr), (x + rr, y + rr), RED, 14, cv2.LINE_AA)
                cv2.line(fr, (x - rr, y + rr), (x + rr, y - rr), RED, 14, cv2.LINE_AA)
        for p in s.get("pins", []):
            ta = self.tl.t(p.get("at", s["from"]))
            if t < ta:
                continue
            a = min(1.0, (t - ta) / 0.25); x, y = P(p["lon"], p["lat"])
            cv2.circle(fr, (int(x), int(y)), int(22 * (1 + 0.6 * (1 - a))), RED, -1, cv2.LINE_AA)
            cv2.circle(fr, (int(x), int(y)), 30, (240, 236, 226), 4, cv2.LINE_AA)
            if p.get("label"):
                lab = self._label_cached(p["label"])
                lx = min(max(x, lab.shape[1] / 2 + 30), W - lab.shape[1] / 2 - 30)
                paste(fr, lab, lx, y - 80, a)
        fg = s.get("fog")
        if fg:
            amt = fg[0] + (fg[1] - fg[0]) * ease(u)
            fr = fr * (1 - amt) + self.fog(t) * amt
        return fr

    # ---------- image finale ----------
    def frame(self, fi: int) -> np.ndarray:
        t = fi / FPS; tl = self.tl
        cur = next((s for s in self.shots if s["t0"] <= t < s["t1"]), self.shots[-1])
        fr = self.shot_frame(cur, t)
        nxt = [s for s in self.shots if 0 < s["t0"] - t < 0.22]
        if nxt:
            v = 1 - (nxt[0]["t0"] - t) / 0.22; fr = fr * (1 - v) + self.shot_frame(nxt[0], nxt[0]["t0"]) * v
        for fl in self.flashes:
            if fl - 0.05 <= t < fl + 0.2:
                fr = fr + (255 - fr) * (1 - (t - fl + 0.05) / 0.25) * 0.85
        flick = 1 + 0.025 * math.sin(t * 61) * math.sin(t * 13)
        fr = fr * self.vig * self.grad * flick + self.grain[fi % len(self.grain)]
        out = max(0.0, (t - tl.vo_end + 0.4) / 1.4)
        if out > 0:
            fr = fr * (1 - 0.7 * min(1.0, out))
        for spr, t0, t1, y in self.stamps:
            if t0 <= t < t1 - 0.1:
                v = min(1.0, (t - t0) / 0.12); paste(fr, spr, W / 2, y, min(1.0, v * 1.2), 1 + 0.5 * (1 - v))
        for spr, a, b, y in self.labels:
            if a <= t < b:
                paste(fr, spr, W / 2, y, min(1.0, (t - a) / 0.25, (b - t) / 0.25))
        if t < self.hook_end + 0.3:
            v = min(1.0, t / 0.15) * min(1.0, (self.hook_end + 0.3 - t) / 0.3)
            paste(fr, self.hook, W / 2, HOOK_TOP + 240, v, 1 + 0.03 * (1 - min(1.0, t / 0.3)))
        elif t < tl.vo_end and self.header is not None:
            paste(fr, self.header, W / 2, HEADER_Y, min(1.0, (t - self.hook_end - 0.3) / 0.4) * 0.95)
        if t < tl.vo_end:
            for i, (a, b, _) in enumerate(tl.chunks):
                if a - 0.03 <= t < b:
                    pop = min(1.0, (t - a + 0.03) / 0.09); paste(fr, self.caption(i), W / 2, CAPTION_Y, 1, 0.86 + 0.14 * pop)
                    break
        if t >= tl.vo_end - 0.1:
            v = min(1.0, (t - tl.vo_end + 0.1) / 0.5); paste(fr, self.endcard, W / 2, 880, v, 0.92 + 0.08 * v)
        if self.wm:
            spr, op, x, y = self.wm; paste(fr, spr, x + spr.shape[1] / 2, y + spr.shape[0] / 2, op)
        return np.clip(fr, 0, 255).astype(np.uint8)
