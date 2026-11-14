"""Contrôles de mise en page BLOQUANTS d'une scène dessinée (coordonnées de sortie, en pixels).

- texte coupé : un mot plus large que sa zone, ou un texte qui sort du cadre ;
- zone de sécurité : texte, chiffres et personnages dans le rectangle sûr (rien au-dessus de y=200, en
  dessous de y=1440, ni à droite de x=930 : interface des plateformes) ;
- zones réservées : rien d'important sous le bandeau ni sous les sous-titres posés ensuite par le compositeur ;
- chevauchement : un texte ne touche ni un personnage ni un autre texte ;
- support : un objet posé (« rests_on ») a sa base sur la surface de son support (pot sur le sol, pieds sur
  le sol), sans flotter ni s'enfoncer.

Rôles (clé « role » du calque) : « text », « value » (chiffre), « character », « limb » (bras séparé),
« prop » (objet du propos : arbre, pile, courbe), « decor » (sol, fond : exempté).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from auracontent.services.visuals.linework.engine import (
    LINE_HEIGHT,
    Painter,
    Scene,
    _sized,
    counter_text,
    key_state,
    visible,
    wrap,
)

IMPORTANT = ("text", "value", "character", "limb", "prop")


class LayoutError(ValueError):
    """La scène ne respecte pas la mise en page : elle n'est jamais rendue telle quelle."""


@dataclass
class Zones:
    """Zones en pixels de sortie. Valeurs par défaut : vidéo 1080x1920 de Capital Simple."""
    safe: tuple = (0, 200, 930, 1440)                       # x0, y0, x1, y1
    reserved: dict = field(default_factory=lambda: {"bandeau": (0, 200, 1080, 470),
                                                     "sous-titres": (0, 1190, 1080, 1440)})
    support_tolerance: float = 14.0                          # px entre la base d'un objet et sa surface

    @classmethod
    def from_config(cls, cfg: dict | None) -> Zones:
        cfg = dict(cfg or {})
        zones = cls()
        if cfg.get("safe"):
            zones.safe = tuple(cfg["safe"])
        if cfg.get("reserved"):
            zones.reserved = {k: tuple(v) for k, v in cfg["reserved"].items()}
        if cfg.get("support_tolerance") is not None:
            zones.support_tolerance = float(cfg["support_tolerance"])
        return zones


def _intersect(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _inside(box, rect) -> bool:
    return box[0] >= rect[0] - 0.5 and box[1] >= rect[1] - 0.5 and box[2] <= rect[2] + 0.5 and box[3] <= rect[3] + 0.5


class Boxes:
    """Boîtes réelles (pixels visibles, sans le transparent des sprites) des calques à un instant donné."""

    def __init__(self, scene: Scene):
        self.scene, self.painter, self.s = scene, Painter.__new__(Painter), scene.scale
        self.painter.scene, self.painter.s = scene, scene.scale

    def box(self, lay: dict, t: float):
        s, x, y = self.s, lay.get("x", 0), lay.get("y", 0)
        if lay["type"] == "image":
            path = str(self.scene.resolve(lay["path"]))
            from auracontent.services.visuals.linework.engine import _sprite
            src = _sprite(path)
            w = lay.get("w", 200)
            h = lay.get("h") or w * src.height / src.width
            sized = _sized(path, max(1, round(w * s)), max(1, round(h * s)))
            bb = sized.getchannel("A").getbbox() or (0, 0, 0, 0)
            sx, sy = abs(lay.get("scaleX", 1)), abs(lay.get("scaleY", 1))
            box = (x * s + bb[0] * sx, y * s + bb[1] * sy, x * s + bb[2] * sx, y * s + bb[3] * sy)
        elif lay["type"] == "text":
            size = round(lay.get("size", 52) * s)
            font = self.painter.font(lay, size)
            lines = wrap(font, counter_text(lay, t), lay.get("w", 1280 - x) * s)
            # pixels réellement dessinés (glyphes), pas la hauteur nominale de la police
            parts = [font.getbbox(line, anchor="la") for line in lines] or [(0, 0, 0, 0)]
            top = min(b[1] for b in parts)
            bottom = max(b[3] + i * size * LINE_HEIGHT for i, b in enumerate(parts))
            width = max(b[2] for b in parts)
            box = (x * s, y * s + top, x * s + width, y * s + bottom)
        elif lay["type"] == "marker":
            box = (x * s, y * s, (x + lay.get("w", 200)) * s, (y + lay.get("h", 40)) * s)
        else:
            w = lay.get("w", 200)
            box = (x * s, (y - 30) * s, (x + w) * s, (y + 30) * s)
        angle = lay.get("angle", 0) or 0
        if angle and lay["type"] == "image":
            px, py = (x + lay.get("pivotX", 0)) * s, (y + lay.get("pivotY", 0)) * s
            c, sn = math.cos(angle), math.sin(angle)
            pts = [(px + (bx - px) * c - (by - py) * sn, py + (bx - px) * sn + (by - py) * c)
                   for bx in (box[0], box[2]) for by in (box[1], box[3])]
            box = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
        return box


def check_times(scene: Scene) -> list[float]:
    """Instants contrôlés : apparitions, disparitions, images clés et toutes les 0,5 s."""
    times = {0.0, max(0.0, scene.duration - 1 / scene.fps)}
    for lay in scene.layers:
        times.add(lay.get("from", 0))
        if math.isfinite(lay.get("to", math.inf)):
            times.add(max(0.0, lay["to"] - 1 / scene.fps))
        times.update(k["t"] for k in lay.get("keys") or [])
    t = 0.0
    while t < scene.duration:
        times.add(t)
        t += 0.5
    return sorted(x for x in times if 0 <= x < scene.duration)


def layout_issues(scene: Scene, zones: Zones | None = None) -> list[str]:
    zones = zones or Zones()
    boxes, issues = Boxes(scene), []

    seen: set[str] = set()

    def note(msg: str) -> None:
        """Un motif n'est signalé qu'une fois (à son premier instant), pas à chaque instant contrôlé."""
        key = re.sub(r" à \d+\.\d+ s", "", msg)
        if key not in seen:
            seen.add(key)
            issues.append(msg)

    by_id = {lay["id"]: lay for lay in scene.layers if lay.get("id")}
    for t in check_times(scene):
        shown = [(lay, key_state(lay, t)) for lay in scene.layers if visible(lay, t)]
        placed = []
        for raw, lay in shown:
            name = raw.get("id") or raw.get("text") or raw.get("path") or raw["type"]
            role = raw.get("role", "text" if raw["type"] == "text" else "decor")
            try:
                box = boxes.box(lay, t)
            except ValueError as e:                       # mot plus large que sa zone
                note(f"texte coupé « {name} » : {e}")
                continue
            if (lay.get("alpha", 1) or 0) <= 0.05:
                continue                                    # invisible à cet instant
            if raw["type"] == "text" and (box[2] > scene.width or box[0] < 0):
                note(f"texte coupé « {name} » : sort du cadre ({box[0]:.0f}..{box[2]:.0f} px)")
            settled = t >= max((k["t"] for k in raw.get("keys") or [{"t": 0}]), default=0)
            if role in IMPORTANT and settled and not _inside(box, zones.safe):
                note(f"hors zone de sécurité « {name} » à {t:.2f} s : {tuple(round(v) for v in box)} "
                     f"(zone {zones.safe})")
            if role in IMPORTANT and settled:
                for zone, rect in zones.reserved.items():
                    if _intersect(box, rect) > 0:
                        note(f"« {name} » empiète sur la zone réservée « {zone} » à {t:.2f} s")
            placed.append((raw, lay, role, box, name))
        for i, (raw, _, role, box, name) in enumerate(placed):
            if role not in ("text", "value"):
                continue
            for other, _, orole, obox, oname in placed:
                if other is raw:
                    continue
                if orole == "character" and _intersect(box, obox) > 0:
                    note(f"chevauchement texte/personnage : « {name} » et « {oname} » à {t:.2f} s")
            for _other, _, orole, obox, oname in placed[i + 1:]:
                if orole in ("text", "value") and _intersect(box, obox) > 0:
                    note(f"chevauchement de textes : « {name} » et « {oname} » à {t:.2f} s")
        # support : vérifié une fois l'objet posé (après sa dernière image clé)
        current = {raw.get("id"): (lay, box) for raw, lay, _, box, _ in placed if raw.get("id")}
        for raw, _lay, _, box, name in placed:
            sup_id = raw.get("rests_on")
            if not sup_id:
                continue
            if t < max((k["t"] for k in raw.get("keys") or [{"t": 0}]), default=0):
                continue
            if sup_id not in by_id:
                note(f"support inconnu « {sup_id} » pour « {name} »")
                continue
            if sup_id not in current:
                note(f"« {name} » posé sur « {sup_id} », absent à {t:.2f} s")
                continue
            sl, sbox = current[sup_id]
            surface = (sl.get("y", 0) + by_id[sup_id].get("surface", 0)) * scene.scale
            if abs(box[3] - surface) > zones.support_tolerance:
                note(f"« {name} » hors de son support « {sup_id} » : base à {box[3]:.0f} px, surface à "
                     f"{surface:.0f} px")
            if box[0] < sbox[0] - 1 or box[2] > sbox[2] + 1:
                note(f"« {name} » déborde de son support « {sup_id} » horizontalement")
    return issues


def check_layout(scene: Scene, zones: Zones | None = None) -> None:
    issues = layout_issues(scene, zones)
    if issues:
        raise LayoutError("mise en page refusée : " + " ; ".join(issues[:8])
                          + (f" (+{len(issues) - 8})" if len(issues) > 8 else ""))
