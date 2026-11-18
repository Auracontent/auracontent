"""Moteur de scènes dessinées « trait à la main » (Pillow + FFmpeg), sans Node ni navigateur.

Même modèle que le moteur du Skill directing-stickman-videos (style B1) qui a produit la vidéo test
videos/interets-composes-b1 : une scène est une liste de calques (texte, image, trait, surligneur) posés sur un
plan de conception de 1280 de large, animés par images clés (x, y, w, h, angle, alpha, progress, scaleX,
scaleY) interpolées en « smoothstep ». Un project.json de cette vidéo se rend donc à l'identique ou presque.

Calques (dict) :
- commun : type, x, y, from, to (secondes depuis le début de la scène), keys [{t, prop: valeur}], id,
  role (« character », « text », « decor »...), pivotX/pivotY (centre de rotation, relatif au calque) ;
- image : path, w, h (taille sur le plan) ;
- text : text, size, bold, color, w (largeur de retour à la ligne), font (« hand » par défaut, ou « ui ») ;
  count {from, to, t0, t1, template} : compteur dont la valeur courante remplace « {n} » dans template ;
- underline, arrow, path (points) : trait qui se dessine (progress 0..1), color, lineWidth ;
- marker : surligneur translucide (w, h, color, alpha), révélé de gauche à droite par progress.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DESIGN_WIDTH = 1280
ANIMATED = ("x", "y", "w", "h", "angle", "alpha", "progress", "scaleX", "scaleY")
LINE_HEIGHT = 1.15
INK = "#191916"


# ---------- Images clés ----------
def key_state(layer: dict, t: float) -> dict:
    """Valeurs du calque à l'instant t (secondes depuis le début de la scène) : interpolation smoothstep."""
    out = dict(layer)
    keys = layer.get("keys") or []
    for prop in ANIMATED:
        frames = [k for k in keys if prop in k]
        if not frames:
            continue
        if t <= frames[0]["t"]:
            out[prop] = frames[0][prop]
        elif t >= frames[-1]["t"]:
            out[prop] = frames[-1][prop]
        else:
            i = next(i for i, k in enumerate(frames) if k["t"] > t)
            a, b = frames[i - 1], frames[i]
            x = max(0.0, min(1.0, (t - a["t"]) / (b["t"] - a["t"])))
            out[prop] = a[prop] + (b[prop] - a[prop]) * x * x * (3 - 2 * x)
    return out


def visible(layer: dict, t: float) -> bool:
    return layer.get("from", 0) <= t < layer.get("to", math.inf)


def fr_number(value: float) -> str:
    """Compteur : entier au format français (« 2 100 »)."""
    return f"{round(value):,}".replace(",", " ")


def counter_text(layer: dict, t: float) -> str:
    count = layer.get("count")
    if not count:
        return str(layer.get("text", ""))
    t0, t1 = count.get("t0", 0), count.get("t1", 1)
    x = max(0.0, min(1.0, (t - t0) / max(t1 - t0, 1e-6)))
    x = x * x * (3 - 2 * x)
    value = count["from"] + (count["to"] - count["from"]) * x
    if count.get("step") and x < 1:          # défilement par pas ; la valeur finale est toujours exacte
        value = round(value / count["step"]) * count["step"]
    return count.get("template", "{n}").replace("{n}", fr_number(value))


# ---------- Scène ----------
@dataclass
class Scene:
    layers: list[dict]
    duration: float
    width: int = 1080
    height: int = 1920
    fps: int = 30
    background: str = "#FDFDFC"
    grid: bool = True
    grid_color: tuple = (76, 90, 105, 9)            # rgba(76,90,105,.036) du style B1
    fonts: dict = field(default_factory=dict)        # {"hand": Caveat.ttf, "ui": Poppins...}
    asset_dirs: list = field(default_factory=list)   # dossiers où chercher les images (path relatif)

    @property
    def scale(self) -> float:
        return self.width / DESIGN_WIDTH

    @property
    def design_height(self) -> float:
        return DESIGN_WIDTH * self.height / self.width

    def resolve(self, path: str) -> Path:
        p = Path(path)
        if p.is_absolute() and p.exists():
            return p
        for base in self.asset_dirs:
            if (Path(base) / path).exists():
                return Path(base) / path
        raise FileNotFoundError(f"image introuvable : {path} (dossiers : {self.asset_dirs})")


@lru_cache(maxsize=64)
def _font(path: str, size: int, bold: bool) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(path, size)
    try:                                    # police variable (Caveat) : graisse 700 ou 400
        axes = font.get_variation_axes()
        if axes:
            font.set_variation_by_axes([700 if bold else 400])
    except OSError:
        pass
    return font


@lru_cache(maxsize=256)
def _sprite(path: str) -> Image.Image:
    return Image.open(path).convert("RGBA")


@lru_cache(maxsize=512)
def _sized(path: str, w: int, h: int) -> Image.Image:
    """Image ajustée dans (w, h) en gardant ses proportions, centrée (comme drawImage du moteur B1)."""
    img = _sprite(path)
    k = min(w / img.width, h / img.height)
    iw, ih = max(1, round(img.width * k)), max(1, round(img.height * k))
    canvas = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    canvas.paste(img.resize((iw, ih), Image.LANCZOS), ((w - iw) // 2, (h - ih) // 2))
    return canvas


@lru_cache(maxsize=256)
def _mirrored(path: str, w: int, h: int) -> Image.Image:
    return _sized(path, w, h).transpose(Image.FLIP_LEFT_RIGHT)


def wrap(font: ImageFont.FreeTypeFont, text: str, max_width: float) -> list[str]:
    """Retour à la ligne au mot ; ValueError si un mot seul dépasse (texte coupé : jamais toléré)."""
    lines, line = [], ""
    for word in str(text).split():
        nxt = f"{line} {word}" if line else word
        if font.getlength(nxt) > max_width and line:
            lines.append(line)
            line = word
        else:
            line = nxt
        if font.getlength(line) > max_width:
            raise ValueError(f"mot trop large pour sa zone : « {word} » ({font.getlength(line):.0f} > {max_width:.0f})")
    if line:
        lines.append(line)
    return lines


def _rgba(color: str, alpha: float = 1.0) -> tuple:
    color = color.lstrip("#")
    r, g, b = (int(color[i:i + 2], 16) for i in (0, 2, 4))
    return r, g, b, int(255 * max(0.0, min(1.0, alpha)))


def stroke_points(layer: dict, w: float) -> list[tuple[float, float]]:
    if layer["type"] == "underline":
        return [(0, 1), (w * 0.25, -1), (w * 0.55, 2), (w, -2)]
    if layer["type"] == "arrow":
        bend = layer.get("bend", -26)
        return [(w * i / 29, bend * math.sin(i / 29 * math.pi)) for i in range(30)]
    return [tuple(p) for p in layer.get("points", [])]


def partial(points, progress: float):
    """Début de la polyligne jusqu'à `progress` de sa longueur (trait qui se dessine)."""
    if len(points) < 2:
        return list(points)
    lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
    left = sum(lengths) * max(0.0, min(1.0, progress))
    out = [points[0]]
    for i, seg in enumerate(lengths):
        if left <= 0:
            break
        f = min(1.0, left / max(seg, 1e-3))
        a, b = points[i], points[i + 1]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        left -= seg
    return out


# ---------- Rendu ----------
class Painter:
    def __init__(self, scene: Scene):
        self.scene = scene
        self.s = scene.scale
        self.base = self._background()

    def _background(self) -> Image.Image:
        sc = self.scene
        img = Image.new("RGBA", (sc.width, sc.height), _rgba(sc.background))
        if sc.grid:
            grid = Image.new("RGBA", img.size, (0, 0, 0, 0))
            d = ImageDraw.Draw(grid)
            x = 32.5
            while x < DESIGN_WIDTH:
                d.line([(x * self.s, 0), (x * self.s, sc.height)], fill=sc.grid_color, width=1)
                x += 64
            y = 16.5
            while y < sc.design_height:
                d.line([(0, y * self.s), (sc.width, y * self.s)], fill=sc.grid_color, width=1)
                y += 64
            img = Image.alpha_composite(img, grid)
        return img

    def font(self, layer: dict, size_px: int) -> ImageFont.FreeTypeFont:
        kind = layer.get("font", "hand")
        return _font(str(self.scene.fonts[kind]), max(1, size_px), bool(layer.get("bold", True)))

    def frame(self, t: float) -> Image.Image:
        img = self.base.copy()
        for layer in self.scene.layers:
            if visible(layer, t):
                self.paint(img, key_state(layer, t), t)
        return img.convert("RGB")

    def _place(self, canvas: Image.Image, piece: Image.Image, lay: dict, x: float, y: float) -> None:
        """Pose `piece` (déjà à l'échelle de sortie) en (x, y), avec rotation/échelle autour du pivot et alpha."""
        s = self.s
        alpha = max(0.0, min(1.0, lay.get("alpha", 1)))
        sx, sy = lay.get("scaleX", 1), lay.get("scaleY", 1)
        px, py = lay.get("pivotX", 0) * s, lay.get("pivotY", 0) * s
        ox, oy = x * s, y * s
        if (sx, sy) != (1, 1):
            # échelle autour du pivot (comme le moteur B1) : le pivot reste à sa place
            nw, nh = max(1, round(piece.width * abs(sx))), max(1, round(piece.height * abs(sy)))
            piece = piece.resize((nw, nh), Image.LANCZOS)
            if sx < 0:
                piece = piece.transpose(Image.FLIP_LEFT_RIGHT)
            ox, oy = ox + px * (1 - abs(sx)), oy + py * (1 - abs(sy))
            px, py = px * abs(sx), py * abs(sy)
        angle = lay.get("angle", 0) or 0
        if angle:
            # rotation autour du pivot : on centre le pivot dans un carré assez grand, puis on tourne
            r = math.ceil(max(math.hypot(px, py), math.hypot(piece.width - px, py), math.hypot(px, piece.height - py),
                              math.hypot(piece.width - px, piece.height - py))) + 2
            pad = Image.new("RGBA", (2 * r, 2 * r), (0, 0, 0, 0))
            pad.paste(piece, (round(r - px), round(r - py)))
            piece = pad.rotate(-math.degrees(angle), resample=Image.BICUBIC, center=(r, r))
            ox, oy = ox + px - r, oy + py - r
        if alpha < 1:
            a = piece.getchannel("A").point(lambda v: int(v * alpha))
            piece = piece.copy()
            piece.putalpha(a)
        canvas.alpha_composite(piece, (round(ox), round(oy))) if _inside(canvas, piece, ox, oy) else \
            _composite_clipped(canvas, piece, round(ox), round(oy))

    def _box(self, canvas: Image.Image, lay: dict) -> None:
        """Rectangle plein (fill) au contour d'encre tracé à la main (barres, jauges, cartes)."""
        s = self.s
        x, y = lay.get("x", 0) * s, lay.get("y", 0) * s
        w, h = lay.get("w", 100) * s, lay.get("h", 100) * s
        if w < 1 or h < 1:
            return
        alpha = lay.get("alpha", 1)
        overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        if lay.get("fill"):
            d.rectangle([x, y, x + w, y + h], fill=_rgba(lay["fill"], alpha * lay.get("fillOpacity", 1)))
        if lay.get("outline", INK):
            j = _wobble(str(lay.get("id") or lay.get("fill") or "box"), 8, 1.6 * s)
            pts = [(x + j[0], y + j[1]), (x + w + j[2], y + j[3]), (x + w + j[4], y + h + j[5]),
                   (x + j[6], y + h + j[7]), (x + j[0], y + j[1])]
            width = max(1, round(lay.get("lineWidth", 4) * s))
            d.line(pts, fill=_rgba(lay.get("outline", INK), alpha), width=width, joint="curve")
        canvas.alpha_composite(overlay)

    def paint(self, canvas: Image.Image, lay: dict, t: float) -> None:
        s, kind = self.s, lay["type"]
        x, y = lay.get("x", 0), lay.get("y", 0)
        if kind == "image":
            path = str(self.scene.resolve(lay["path"]))
            src = _sprite(path)
            w = lay.get("w", 200)
            h = lay.get("h") or w * src.height / src.width
            piece = _sized(path, max(1, round(w * s)), max(1, round(h * s)))
            if lay.get("flip"):                             # miroir horizontal (personnage tourné vers la gauche)
                piece = _mirrored(path, piece.width, piece.height)
            self._place(canvas, piece, lay, x, y)
        elif kind == "text":
            size = round(lay.get("size", 52) * s)
            font = self.font(lay, size)
            text = counter_text(lay, t)
            lines = wrap(font, text, lay.get("w", DESIGN_WIDTH - x) * s)
            height = round(len(lines) * size * LINE_HEIGHT + size * 0.4)
            width = round(max(font.getlength(line) for line in lines)) + 4 if lines else 1
            piece = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
            d = ImageDraw.Draw(piece)
            for i, line in enumerate(lines):
                d.text((0, i * size * LINE_HEIGHT), line, font=font, fill=_rgba(lay.get("color", INK)), anchor="la")
            self._place(canvas, piece, lay, x, y)
        elif kind == "box":
            self._box(canvas, lay)
        elif kind == "marker":
            w, h = lay.get("w", 200) * s, lay.get("h", 40) * s
            shown = w * max(0.0, min(1.0, lay.get("progress", 1)))
            if shown >= 1:
                piece = Image.new("RGBA", (round(shown), round(h)), _rgba(lay.get("color", "#E0A526"), lay.get("opacity", 0.55)))
                self._place(canvas, piece, {**lay, "angle": lay.get("angle", 0)}, x, y)
        elif kind in ("underline", "arrow", "path"):
            w = lay.get("w", 200)
            pts = partial(stroke_points(lay, w), lay.get("progress", 1))
            if len(pts) >= 2:
                overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                d = ImageDraw.Draw(overlay)
                width = max(1, round(lay.get("lineWidth", 6 if kind == "underline" else 3) * s))
                color = _rgba(lay.get("color", INK), lay.get("alpha", 1))
                xy = [((x + px) * s, (y + py) * s) for px, py in pts]
                d.line(xy, fill=color, width=width, joint="curve")
                for cx, cy in (xy[0], xy[-1]):
                    d.ellipse([cx - width / 2, cy - width / 2, cx + width / 2, cy + width / 2], fill=color)
                if kind == "arrow" and lay.get("progress", 1) > 0.95:
                    hx, hy = (x + w) * s, y * s
                    d.line([(hx - 17 * s, hy - 12 * s), (hx, hy), (hx - 19 * s, hy + 12 * s)], fill=color,
                           width=max(1, round(3 * s)), joint="curve")
                canvas.alpha_composite(overlay)
        else:
            raise ValueError(f"type de calque inconnu : {kind}")


def _wobble(seed: str, n: int, amp: float) -> list[float]:
    """Tremblé déterministe du trait (même scène, même dessin d'une image à l'autre)."""
    x = sum(ord(c) * (i + 1) for i, c in enumerate(seed)) or 1
    out = []
    for _ in range(n):
        x = (x * 1103515245 + 12345) % 2 ** 31
        out.append((x / 2 ** 31 * 2 - 1) * amp)
    return out


def _inside(canvas, piece, ox, oy) -> bool:
    return ox >= 0 and oy >= 0 and ox + piece.width <= canvas.width and oy + piece.height <= canvas.height


def _composite_clipped(canvas: Image.Image, piece: Image.Image, ox: int, oy: int) -> None:
    """alpha_composite refuse un dépassement du cadre : on rogne la partie hors champ."""
    left, top = max(0, -ox), max(0, -oy)
    right, bottom = min(piece.width, canvas.width - ox), min(piece.height, canvas.height - oy)
    if right > left and bottom > top:
        canvas.alpha_composite(piece.crop((left, top, right, bottom)), (ox + left, oy + top))


# ---------- Encodage ----------
def render_mp4(scene: Scene, target: Path, crf: int = 20) -> Path:
    """Toutes les images de la scène, encodées en H.264 (sans audio : la voix est posée par le compositeur)."""
    painter = Painter(scene)
    frames = max(1, math.ceil(scene.duration * scene.fps - 1e-6))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{scene.width}x{scene.height}",
           "-r", str(scene.fps), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", str(crf),
           "-pix_fmt", "yuv420p", str(target)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for i in range(frames):
            proc.stdin.write(painter.frame(i / scene.fps).tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError(f"encodage FFmpeg en échec : {err[-800:]}")
    except BaseException:
        proc.kill()
        raise
    return target
