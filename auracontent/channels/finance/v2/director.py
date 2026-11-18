"""Réalisateur V2 : plans animés (easing par image clé, caméra), transitions et assemblage final.

Un plan (Shot) = des calques du moteur linework + une durée + des images clés de caméra + la transition vers le
plan suivant. Chaque plan est rendu en MP4 (Pillow -> FFmpeg), puis les plans sont enchaînés avec le filtre
xfade de FFmpeg, les effets sonores sont mixés à leur instant, et les sous-titres ASS sont brûlés.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from auracontent.services.visuals.linework.engine import ANIMATED, Painter, Scene, visible
from PIL import Image

from . import easing

TRANSITIONS = ("fade", "slideleft", "slideup", "circleopen", "wipeleft", "zoomin", "smoothleft", "radial")
FONTS_DIR = Path(__file__).resolve().parents[4] / "assets" / "finance" / "fonts"
# Effets sonores propres à Capital Simple uniquement (jamais ceux de mystery ni du dossier partagé).
SFX_DIRS = [Path(__file__).resolve().parents[4] / "assets" / "finance" / "sfx"]


def key_state(layer: dict, t: float) -> dict:
    """Comme engine.key_state, mais la clé d'arrivée peut choisir sa courbe : {"t": 1.2, "y": 400, "ease": "bounce"}."""
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
            x = (t - a["t"]) / (b["t"] - a["t"])
            out[prop] = a[prop] + (b[prop] - a[prop]) * easing.ease(b.get("ease"), x)
    return out


def camera_at(keys: list[dict], t: float) -> tuple[float, float, float]:
    """(zoom, cx, cy) à l'instant t ; cx, cy en pixels de sortie. Sans clé : plan fixe."""
    if not keys:
        return 1.0, 540.0, 960.0
    base = {"zoom": 1.0, "cx": 540.0, "cy": 960.0}
    vals = {}
    for prop in base:
        frames = [k for k in keys if prop in k]
        if not frames:
            vals[prop] = base[prop]
        elif t <= frames[0]["t"]:
            vals[prop] = frames[0][prop]
        elif t >= frames[-1]["t"]:
            vals[prop] = frames[-1][prop]
        else:
            i = next(i for i, k in enumerate(frames) if k["t"] > t)
            a, b = frames[i - 1], frames[i]
            x = (t - a["t"]) / (b["t"] - a["t"])
            vals[prop] = a[prop] + (b[prop] - a[prop]) * easing.ease(b.get("ease"), x)
    return vals["zoom"], vals["cx"], vals["cy"]


class V2Painter(Painter):
    def __init__(self, scene: Scene, camera: list[dict] | None = None):
        super().__init__(scene)
        self.camera = camera or []

    def frame(self, t: float) -> Image.Image:
        img = self.base.copy()
        for layer in self.scene.layers:
            if visible(layer, t):
                self.paint(img, key_state(layer, t), t)
        zoom, cx, cy = camera_at(self.camera, t)
        if abs(zoom - 1) > 1e-3:
            W, H = img.size
            w, h = W / zoom, H / zoom
            x0 = min(max(cx - w / 2, 0), W - w)
            y0 = min(max(cy - h / 2, 0), H - h)
            img = img.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h))
        return img.convert("RGB")


@dataclass
class Shot:
    layers: list[dict]
    duration: float
    camera: list[dict] = field(default_factory=list)
    transition: str = "fade"            # transition vers le plan SUIVANT
    sfx: list[dict] = field(default_factory=list)   # [{"at": s, "file": "pop.wav", "gain": 0.35}] relatifs au plan


def render_shot(shot: Shot, scene_kwargs: dict, target: Path, crf: int = 20) -> Path:
    scene = Scene(layers=shot.layers, duration=shot.duration, **scene_kwargs)
    painter = V2Painter(scene, shot.camera)
    frames = max(1, math.ceil(shot.duration * scene.fps - 1e-6))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{scene.width}x{scene.height}",
           "-r", str(scene.fps), "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
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


def starts(shots: list[Shot], overlap: float) -> list[float]:
    """Début de chaque plan sur la timeline finale (les transitions chevauchent les plans de `overlap` s)."""
    out, t = [], 0.0
    for s in shots:
        out.append(t)
        t += s.duration - overlap
    return out


def _sfx_path(name: str) -> Path | None:
    for d in SFX_DIRS:
        if (d / name).exists():
            return d / name
    return None


def assemble(clips: list[Path], shots: list[Shot], target: Path, *, overlap: float = 0.35,
             ass: Path | None = None, voices: list[tuple[Path, float]] | None = None, music: Path | None = None,
             music_gain: float = 0.12, crf: int = 20) -> Path:
    """Enchaîne les plans (xfade), mixe voix + musique + effets, brûle les sous-titres, limite le pic à -1,5 dBTP."""
    target = Path(target)
    t0 = starts(shots, overlap)
    total = t0[-1] + shots[-1].duration
    inputs = []
    for c in clips:
        inputs += ["-i", str(c)]
    vf, last = [], "[0:v]"
    for i in range(1, len(clips)):
        trans = shots[i - 1].transition if shots[i - 1].transition in TRANSITIONS else "fade"
        offset = t0[i]
        vf.append(f"{last}[{i}:v]xfade=transition={trans}:duration={overlap}:offset={offset:.3f}[v{i}]")
        last = f"[v{i}]"
    if ass:
        fontsdir = str(FONTS_DIR).replace(":", r"\:")
        assp = str(ass).replace(":", r"\:")
        vf.append(f"{last}subtitles='{assp}':fontsdir='{fontsdir}'[vout]")
        last = "[vout]"
    # audio : voix, musique, effets
    n = len(clips)
    a_parts, a_labels = [], []
    for j, (vpath, vstart) in enumerate(voices or []):      # voix de chaque plan, posée à son instant
        inputs += ["-i", str(vpath)]
        ms = int(vstart * 1000)
        a_parts.append(f"[{n}:a]adelay={ms}|{ms}[vo{j}]")
        a_labels.append(f"[vo{j}]")
        n += 1
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        a_parts.append(f"[{n}:a]volume={music_gain},atrim=0:{total:.3f},afade=t=out:st={max(0, total - 1):.3f}:d=1[mus]")
        a_labels.append("[mus]")
        n += 1
    k = 0
    for start, shot in zip(t0, shots, strict=True):
        for cue in shot.sfx:
            p = _sfx_path(cue["file"])
            if not p:
                continue
            inputs += ["-i", str(p)]
            ms = int((start + cue["at"]) * 1000)
            a_parts.append(f"[{n}:a]volume={cue.get('gain', 0.35)},adelay={ms}|{ms}[s{k}]")
            a_labels.append(f"[s{k}]")
            n += 1
            k += 1
    if a_labels:
        a_parts.append(f"{''.join(a_labels)}amix=inputs={len(a_labels)}:normalize=0:duration=longest,"
                       f"apad,atrim=0:{total:.3f},alimiter=limit=0.84:level=false[aout]")
    graph = ";".join(vf + a_parts)
    cmd = ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", last]
    if a_labels:
        cmd += ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-t", f"{total:.3f}", str(target)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"assemblage FFmpeg en échec : {res.stderr[-1500:]}")
    return target
