"""Gabarits de scènes dessinées, par FORME DE DONNÉES (réutilisables par tout concept) :

- two_amounts    : deux montants comparés (variantes « arbres » et « piles ») ;
- curve_in_time  : une ou deux courbes dans le temps (variantes « courbes » et « ecart ») ;
- bars           : barres comparées (« barres ») ou part d'un tout (« jauge ») ;
- timeline       : frise du temps parcourue par un personnage (« frise ») ou compte à rebours (« sablier ») ;
- characters     : scène de personnages qui réagissent, avec une annotation ;
- end_card       : carte de fin (logo, hypothèse, mention, question).

Chaque gabarit renvoie une liste de calques pour engine.Scene. Les positions sont calculées en pixels de sortie
(1080x1920) dans la zone utile (entre le bandeau et les sous-titres, à gauche de x=930), puis converties sur le
plan de conception de 1280 de large du moteur. Les objets posés le sont d'après les pixels réels de leur sprite.
Un calque animé peut porter « sfx » : [{"at": secondes, "file": "pop.wav", "gain": 0.3}] ; cues() en tire les
effets sonores calés sur l'action (scene["sfx_cues"] du compositeur).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from auracontent.services.visuals.linework.engine import DESIGN_WIDTH, _sprite

INK, TURQUOISE, GOLD, GRAY, PAPER = "#1A1A1A", "#0E9F8E", "#E0A526", "#454950", "#F7F3EA"   # gris foncé : lisible
Resolver = Callable[[str], object]


@dataclass
class Frame:
    """Zone utile en pixels de sortie et facteur vers le plan de conception."""
    width: int = 1080
    top: int = 470            # sous le bandeau
    bottom: int = 1235        # au-dessus des sous-titres (calés sur y=1440)
    right: int = 925          # zone de sécurité : x <= 930
    left: int = 40

    @property
    def k(self) -> float:                 # pixels de sortie -> unités du plan
        return DESIGN_WIDTH / self.width


@dataclass
class Side:
    """Un des deux montants comparés."""
    name: str                              # « Léa »
    value: float                           # valeur (taille relative de l'objet, compteur)
    value_text: str                        # « 2 100 € » (texte final, déjà formaté)
    caption: str = ""                      # « (100 € à 20 ans) »
    color: str = INK                       # couleur du nom
    idle: str = ""                         # pose au début (« hugo-neutral.png »)
    react: str = ""                        # pose à la révélation (« hugo-shock.png » / « lea-joy.png »)
    count_template: str = ""               # « Léa ≈ {n} € » : compteur ; vide = texte fixe
    extra: dict = field(default_factory=dict)


@dataclass
class Item:
    """Une barre, une étape de frise ou une courbe : libellé, valeur et texte final (de calc.py)."""
    label: str
    value: float
    text: str                              # « 16 000 € », « 18 ans » (jamais écrit par un LLM)
    color: str = TURQUOISE
    count_template: str = ""               # « {n} € » : compteur jusqu'à value


# ---------- Outils ----------
@lru_cache(maxsize=128)
def content_box(path: str) -> tuple[float, float, float, float]:
    """Boîte des pixels visibles du sprite, en fraction de sa taille (0..1)."""
    img = _sprite(path)
    bb = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
    return bb[0] / img.width, bb[1] / img.height, bb[2] / img.width, bb[3] / img.height


def _fade(t0: float, dur: float = 0.3) -> list[dict]:
    return [{"t": t0, "alpha": 0}, {"t": t0 + dur, "alpha": 1}]


def _sfx(at: float, file: str, gain: float = 0.35) -> list[dict]:
    return [{"at": round(at, 3), "file": file, "gain": gain}]


def cues(layers: list[dict], duration: float) -> list[dict]:
    """Effets sonores des calques, au format scene["sfx_cues"] du compositeur, triés et dans la scène."""
    out = [{"time": c["at"], "file": c["file"], "gain": c.get("gain", 0.35)}
           for lay in layers for c in lay.get("sfx") or [] if 0 <= c["at"] < duration - 0.05]
    return sorted(out, key=lambda c: c["time"])


def text(tid: str, value: str, x_px: float, y_px: float, size: float, frame: Frame, *, color: str = INK,
         role: str = "text", start: float = 0.1, w_px: float | None = None, bold: bool = True,
         count: dict | None = None, font: str = "hand", sfx: list | None = None) -> dict:
    k = frame.k
    layer = {"type": "text", "id": tid, "role": role, "text": value, "x": x_px * k, "y": y_px * k, "size": size,
             "bold": bold, "color": color, "w": (w_px if w_px is not None else frame.right - x_px) * k,
             "font": font, "from": start, "keys": _fade(start, 0.25)}
    if count:
        layer["count"] = count
    if sfx:
        layer["sfx"] = sfx
    return layer


def shown(item: Item, prefix: str = "") -> str:
    """Texte du calque : modèle du compteur (« {n} € ») s'il compte, sinon le texte final de calc.py."""
    if item.count_template and float(item.value) == int(item.value):
        return prefix + item.count_template
    if item.count_template:                  # décimal : même modèle, valeur écrite (« x 5,4 »), sans compteur
        return prefix + item.count_template.replace("{n}", f"{item.value:g}".replace(".", ","))
    return prefix + item.text


def counter(item: Item, t0: float, dur: float = 0.9, step: float | None = None, prefix: str = "") -> dict | None:
    if not item.count_template or float(item.value) != int(item.value):
        return None                        # valeur décimale (« x 5,4 ») : texte fixe, jamais arrondi par le compteur
    return {"from": 0, "to": item.value, "t0": t0, "t1": t0 + dur, "template": prefix + item.count_template,
            "step": step if step is not None else (10 if item.value >= 1000 else 1)}


def grounded(resolve: Resolver, name: str, height_px: float, cx_px: float, surface_px: float, frame: Frame,
             sink_px: float = 3.0) -> dict:
    """Calque image d'un sprite posé sur la surface : base de ses pixels visibles à `surface_px`."""
    path = str(resolve(name))
    img = _sprite(path)
    x0, y0, x1, y1 = content_box(path)
    h = height_px / max(y1 - y0, 1e-6)                  # hauteur du sprite entier pour ce contenu
    w = h * img.width / img.height
    k = frame.k
    return {"type": "image", "path": name, "w": w * k, "h": h * k,
            "x": (cx_px - w * (x0 + x1) / 2) * k, "y": (surface_px + sink_px - h * y1) * k}


def ground(resolve: Resolver, surface_px: float, frame: Frame) -> dict:
    """Sol de la vidéo test (trait d'encre, papier dessous) sur toute la largeur ; « surface » pour les appuis."""
    k = frame.k
    path = str(resolve("ground-paper.png"))
    _, gy0, _, _ = content_box(path)
    img = _sprite(path)
    g_h = DESIGN_WIDTH * img.height / img.width
    return {"type": "image", "role": "decor", "id": "sol", "path": "ground-paper.png", "x": 0,
            "y": surface_px * k - g_h * gy0 - 4 * k, "w": DESIGN_WIDTH, "h": g_h, "surface": g_h * gy0 + 4 * k}


def _title(layers: list[dict], title: str, subtitle: str, f: Frame) -> float:
    """Annotation de tête (Caveat) et hypothèse ; renvoie le haut de la zone libre en dessous."""
    y = f.top + 5
    if title:
        layers.append(text("titre", title, f.left, y, 76, f, start=0.1))
        y += 70
    if subtitle:
        layers.append(text("hypothese", subtitle, f.left, y, 50, f, color=GRAY, start=0.1))
        y += 58
    return y


# ---------- Deux montants comparés ----------
def two_amounts(left: Side, right: Side, *, resolve: Resolver, title: str = "", subtitle: str = "",
                duration: float = 6.7, variant: str = "arbres", frame: Frame | None = None) -> list[dict]:
    """Deux montants comparés. Le plus petit pousse d'abord, le plus grand ensuite et le dépasse (suspense) ;
    compteurs sur les montants, le gagnant arrive et le perdant change d'expression ; surligneur or sous le
    résultat gagnant."""
    f = frame or Frame()
    k = f.k
    winner, loser = (left, right) if left.value >= right.value else (right, left)
    D = duration
    t_small, t_big = 0.35, max(1.9, 0.65 * D)                       # rythme de la vidéo test (4,35 s sur 6,7)
    surface = f.bottom - 125                                        # sol ; montants écrits en dessous
    layers: list[dict] = []
    top_free = _title(layers, title, subtitle, f)

    big_h = surface - top_free - 10
    ratio = max(0.45, min(0.9, loser.value / max(winner.value, 1e-9)))
    cols = {"win_obj": f.left + 175, "win_char": f.left + 390, "lose_obj": f.left + 560, "lose_char": f.right - 75}
    if variant == "arbres":
        big_sprite, small_sprite = "tree-lea.png", "tree-hugo.png"
    elif variant == "piles":
        big_sprite, small_sprite = "stack-16.png", "stack-9.png"
        big_h = min(big_h, 420)
    else:
        raise ValueError(f"variante inconnue pour two_amounts : {variant}")
    big = grounded(resolve, big_sprite, big_h, cols["win_obj"], surface, f)
    if variant == "arbres":
        # même échelle pour les deux arbres (comme la vidéo test) : la forme raconte l'écart, pas un étirement
        scale = big["h"] / _sprite(str(resolve(big_sprite))).height
        _, by0, _, by1 = content_box(str(resolve(small_sprite)))
        small_h = _sprite(str(resolve(small_sprite))).height * scale / k * (by1 - by0)
    else:
        small_h = big_h * ratio                                     # piles : hauteur proportionnelle au montant
    small = grounded(resolve, small_sprite, small_h, cols["lose_obj"], surface, f)
    sound = "grow.wav" if variant == "arbres" else "coins.wav"
    for obj, oid, t0, who in ((small, "objet-perdant", t_small, loser), (big, "objet-gagnant", t_big, winner)):
        hidden = surface * k + 8                                   # caché derrière le sol, puis il pousse
        obj.update(id=oid, role="prop", rests_on="sol", sfx=_sfx(t0, sound, 0.3),
                   keys=[{"t": t0, "y": hidden}, {"t": t0 + 1.1, "y": obj["y"]}],
                   motion=f"{who.name} : l'objet pousse jusqu'à {who.value_text}")
        layers.append(obj)
    layers.append(ground(resolve, surface, f))           # dessiné après les objets : il les cache quand ils poussent

    char_h = min(330, surface - top_free - 40)
    t_react = t_big + 1.0
    if loser.idle:
        idle = grounded(resolve, loser.idle, char_h, cols["lose_char"], surface, f)
        idle.update(id="perdant", role="character", rests_on="sol", to=t_react, keys=_fade(0.2))
        layers.append(idle)
    if loser.react:
        react = grounded(resolve, loser.react, char_h * 1.03, cols["lose_char"], surface, f)
        y = react["y"]
        react.update(id="perdant-reaction", role="character", rests_on="sol", sfx=_sfx(t_react, "boing.wav", 0.3),
                     keys=[{"t": t_react, "y": y}, {"t": t_react + 0.25, "y": y - 30}, {"t": t_react + 0.6, "y": y}],
                     motion=f"{loser.name} sursaute devant le résultat de {winner.name}", **{"from": t_react})
        layers.append(react)
    if winner.react:
        enter = grounded(resolve, winner.react, char_h * 1.03, cols["win_char"], surface, f)
        x = enter["x"]
        enter.update(id="gagnant", role="character", rests_on="sol", sfx=_sfx(t_big + 0.6, "pop.wav", 0.3),
                     keys=[{"t": t_big + 0.6, "x": x - 120, "alpha": 0}, {"t": t_big + 1.1, "x": x, "alpha": 1}],
                     motion=f"{winner.name} arrive quand son résultat apparaît", **{"from": t_big + 0.6})
        layers.append(enter)

    for who, oid, x_px, t0 in ((loser, "montant-perdant", f.left + 480, t_small + 0.9),
                               (winner, "montant-gagnant", f.left, t_big + 0.9)):
        item = Item(who.name, who.value, who.value_text, who.color, who.count_template)
        layer = text(oid, shown(item), x_px, surface + 14, 64, f, color=who.color,
                     role="value", start=t0, w_px=430, count=counter(item, t0, step=who.extra.get("step")),
                     sfx=_sfx(t0, "tick.wav", 0.25))
        if who is winner:                                    # surligneur or sous le résultat gagnant
            layers.append({"type": "marker", "role": "decor", "id": "surligneur", "x": x_px * k - 6,
                           "y": (surface + 58) * k, "w": 330 * k, "h": 20, "color": GOLD, "opacity": 0.6,
                           "from": t0 + 0.9, "sfx": _sfx(t0 + 0.9, "chime.wav", 0.25),
                           "keys": [{"t": t0 + 0.9, "progress": 0}, {"t": t0 + 1.4, "progress": 1}]})
        layers.append(layer)
        if who.caption:
            layers.append(text(f"{oid}-legende", who.caption, x_px, surface + 72, 46, f, color=GRAY, start=t0,
                               w_px=430, bold=True))
    return layers


# ---------- Courbe dans le temps ----------
def curve_in_time(series: dict, a: Item, b: Item | None = None, *, x_labels: tuple[str, str], title: str = "",
                  subtitle: str = "", gap: Item | None = None, duration: float = 6.0, variant: str = "courbes",
                  frame: Frame | None = None) -> list[dict]:
    """Une ou deux courbes qui se tracent (series de calc.py : x, a, b). Légende en dessous avec compteurs ;
    variante « ecart » : l'écart final est marqué d'une accolade et annoncé (gap)."""
    f = frame or Frame()
    k, D = f.k, duration
    layers: list[dict] = []
    top = _title(layers, title, subtitle, f) + 30
    legend_rows = 1 + (b is not None) + (gap is not None and variant == "ecart")
    bottom = f.bottom - 60 - 58 * legend_rows                       # axe des x ; légende sous l'axe
    x0, x1 = f.left + 60, f.right - 30
    xs = series["x"]
    vals = [v for key in ("a", "b") for v in (series.get(key) or []) if v is not None]
    vmax = max(vals) * 1.08 if vals else 1

    def pt(i: int, v: float) -> tuple[float, float]:
        return ((x1 - x0) * (xs[i] - xs[0]) / max(xs[-1] - xs[0], 1e-9) * k, -(bottom - top) * v / vmax * k)

    layers.append({"type": "path", "role": "decor", "id": "axes", "x": x0 * k, "y": bottom * k, "lineWidth": 5,
                   "points": [(0, (top - bottom) * k), (0, 0), ((x1 - x0) * k, 0)], "color": INK,
                   "keys": [{"t": 0.1, "progress": 0}, {"t": 0.6, "progress": 1}], "sfx": _sfx(0.1, "paper.wav", 0.3)})
    layers.append(text("x-debut", x_labels[0], x0 - 20, bottom + 8, 50, f, color=GRAY, start=0.5, w_px=300))
    layers.append(text("x-fin", x_labels[1], x1 - 170, bottom + 8, 50, f, color=GRAY, start=0.5, w_px=190))
    curves = [("a", a, 0.32 * D)] + ([("b", b, 0.22 * D)] if b is not None else [])
    for key, item, t0 in curves:
        data = series.get(key) or []
        pts = [pt(i, v) for i, v in enumerate(data) if v is not None]
        layers.append({"type": "path", "role": "prop", "id": f"courbe-{key}", "x": x0 * k, "y": bottom * k,
                       "points": pts, "color": item.color, "lineWidth": 8, "sfx": _sfx(t0, "draw.wav", 0.3),
                       "keys": [{"t": t0, "progress": 0}, {"t": t0 + 0.4 * D, "progress": 1}],
                       "motion": f"la courbe « {item.label} » se trace jusqu'à {item.text}"})
    row = bottom + 62
    for key, item, t0 in sorted(curves, key=lambda c: c[2]):
        end = t0 + 0.4 * D
        layers.append({"type": "path", "role": "decor", "id": f"legende-trait-{key}", "x": f.left * k,
                       "y": (row + 30) * k, "points": [(0, 0), (60 * k, 0)], "color": item.color, "lineWidth": 8,
                       "from": end})
        label = f"{item.label} : "
        layers.append(text(f"legende-{key}", shown(item, label), f.left + 80,
                           row, 54, f, color=item.color if item.color != GRAY else INK, role="value", start=end,
                           w_px=f.right - f.left - 80, count=counter(item, end, 0.8, prefix=label),
                           sfx=_sfx(end, "tick.wav", 0.25)))
        row += 58
    if variant == "ecart" and gap is not None and b is not None:
        ya, yb = pt(len(series["a"]) - 1, series["a"][-1])[1], pt(len(series["b"]) - 1, series["b"][-1])[1]
        t_gap = 0.32 * D + 0.4 * D + 0.2
        layers.append({"type": "path", "role": "decor", "id": "accolade", "x": (x1 + 8) * k, "y": bottom * k,
                       "points": [(0, ya), (12 * k, ya), (12 * k, yb), (0, yb)], "color": GOLD, "lineWidth": 7,
                       "from": t_gap, "keys": [{"t": t_gap, "progress": 0}, {"t": t_gap + 0.4, "progress": 1}],
                       "sfx": _sfx(t_gap, "chime.wav", 0.25)})
        layers.append({"type": "marker", "role": "decor", "id": "surligneur", "x": (f.left + 76) * k,
                       "y": (row + 44) * k, "w": 420 * k, "h": 20, "color": GOLD, "opacity": 0.6, "from": t_gap,
                       "keys": [{"t": t_gap, "progress": 0}, {"t": t_gap + 0.5, "progress": 1}]})
        label = f"{gap.label} : "
        layers.append(text("ecart", shown(gap, label), f.left + 80, row, 54, f, role="value", start=t_gap,
                           w_px=f.right - f.left - 80, count=counter(gap, t_gap, 0.7, prefix=label)))
    return layers


# ---------- Barres comparées / part d'un tout ----------
def bars(items: list[Item], *, title: str = "", subtitle: str = "", duration: float = 6.0, variant: str = "barres",
         share: Item | None = None, share_caption: str = "", frame: Frame | None = None) -> list[dict]:
    """« barres » : 1 à 3 barres qui montent l'une après l'autre, valeur au-dessus (compteur), libellé dessous ;
    la plus grande est soulignée à l'or. « jauge » : part d'un tout (share, en %) qui se remplit."""
    f = frame or Frame()
    k, D = f.k, duration
    layers: list[dict] = []
    top = _title(layers, title, subtitle, f)
    if variant == "jauge" and share is not None:
        bar_y, bar_h = top + 210, 110
        x0, width = f.left + 10, f.right - f.left - 30
        t0 = 0.3 * D
        layers.append({"type": "box", "role": "prop", "id": "jauge-cadre", "x": x0 * k, "y": bar_y * k,
                       "w": width * k, "h": bar_h * k, "fill": "#FFFFFF", "fillOpacity": 0.55, "lineWidth": 5,
                       "keys": _fade(0.1)})
        layers.append({"type": "box", "role": "prop", "id": "jauge-part", "x": x0 * k, "y": bar_y * k, "h": bar_h * k,
                       "fill": GOLD, "outline": "", "w": 0, "sfx": _sfx(t0, "fill.wav", 0.3),
                       "keys": [{"t": t0, "w": 0}, {"t": t0 + 0.4 * D, "w": width * k * share.value / 100}],
                       "motion": f"la jauge se remplit jusqu'à {share.text}"})
        layers.append(text("jauge-valeur", shown(share), x0, top + 30, 140, f, role="value",
                           start=t0, w_px=width, count=counter(share, t0, 0.4 * D, step=1),
                           sfx=_sfx(t0, "tick.wav", 0.25)))
        layers.append(text("jauge-100", "100 %", x0 + width - 130, bar_y + bar_h + 12, 50, f, color=GRAY,
                           start=0.3, w_px=140))
        if share_caption:
            layers.append(text("jauge-legende", share_caption, x0, bar_y + bar_h + 70, 56, f, start=t0 + 0.4 * D,
                               w_px=width - 160))
        return layers

    n = len(items)
    if not 1 <= n <= 3:
        raise ValueError("bars : 1 à 3 barres")
    base = f.bottom - 120                                       # bas des barres ; libellés dessous
    max_h = base - top - 120                                    # place pour la valeur au-dessus
    col = (f.right - f.left) / n
    vmax = max(i.value for i in items) or 1
    best = max(range(n), key=lambda i: items[i].value)
    for i, item in enumerate(items):
        cx = f.left + col * (i + 0.5)
        bw = min(170, col * 0.55)
        h = max(18, max_h * item.value / vmax)
        t0 = 0.25 * D + i * 0.18 * D
        layers.append({"type": "box", "role": "prop", "id": f"barre-{i}", "x": (cx - bw / 2) * k, "w": bw * k,
                       "fill": item.color, "lineWidth": 5, "sfx": _sfx(t0, "grow.wav", 0.28),
                       "keys": [{"t": t0, "y": base * k, "h": 0}, {"t": t0 + 0.7, "y": (base - h) * k, "h": h * k}],
                       "motion": f"la barre « {item.label} » monte jusqu'à {item.text}"})
        layers.append(text(f"valeur-{i}", shown(item), cx - col / 2 + 10, base - h - 80, 60, f,
                           role="value", start=t0 + 0.2, w_px=col - 20, count=counter(item, t0 + 0.2, 0.6),
                           sfx=_sfx(t0 + 0.2, "tick.wav", 0.2)))
        layers.append(text(f"libelle-{i}", item.label, cx - col / 2 + 10, base + 14, 52, f, color=GRAY,
                           start=t0, w_px=col - 20, bold=True))
        if i == best:
            t1 = t0 + 0.9
            layers.append({"type": "marker", "role": "decor", "id": "surligneur", "x": (cx - col / 2 + 6) * k,
                           "y": (base - h - 28) * k, "w": (col - 30) * k, "h": 18, "color": GOLD, "opacity": 0.6,
                           "from": t1, "keys": [{"t": t1, "progress": 0}, {"t": t1 + 0.4, "progress": 1}],
                           "sfx": _sfx(t1, "chime.wav", 0.2)})
    layers.append({"type": "path", "role": "decor", "id": "ligne-de-base", "x": f.left * k, "y": base * k,
                   "points": [(0, 0), ((f.right - f.left) * k, 0)], "lineWidth": 5,
                   "keys": [{"t": 0.05, "progress": 0}, {"t": 0.4, "progress": 1}]})
    return layers


# ---------- Frise du temps / compte à rebours ----------
def timeline(steps: list[Item], *, resolve: Resolver, title: str = "", subtitle: str = "", duration: float = 6.0,
             variant: str = "frise", walker: str = "lea-neutral.png", countdown: Item | None = None,
             frame: Frame | None = None) -> list[dict]:
    """« frise » : une ligne du temps graduée (steps : valeur = position, text = libellé), parcourue par un
    personnage ; chaque étape apparaît à son passage. « sablier » : l'horloge de la vidéo test dont l'aiguille
    tourne pendant qu'un compteur égrène la durée (countdown)."""
    f = frame or Frame()
    k, D = f.k, duration
    layers: list[dict] = []
    top = _title(layers, title, subtitle, f)
    if variant == "sablier" and countdown is not None:
        size = min(330, f.bottom - top - 120)
        cx, cy = f.left + 30 + size / 2, top + 40 + size / 2
        layers.append({"type": "image", "role": "prop", "id": "horloge", "path": "clock-face.png",
                       "x": (cx - size / 2) * k, "y": (cy - size / 2) * k, "w": size * k, "h": size * k,
                       "keys": _fade(0.1)})
        hand = size / 2                                       # aiguille : moitié du cadran (vidéo test)
        pivot = 4 * hand / 110
        up = -3 * math.pi / 4
        t0, t1 = 0.25 * D, 0.8 * D
        layers.append({"type": "image", "role": "prop", "id": "aiguille", "path": "clock-hand.png",
                       "x": (cx - pivot) * k, "y": (cy - pivot) * k, "w": hand * k, "h": hand * k,
                       "pivotX": pivot * k, "pivotY": pivot * k, "sfx": _sfx(t0, "clock.wav", 0.3),
                       "keys": [{"t": t0, "angle": up}, {"t": t1, "angle": up + 4 * math.pi}],
                       "motion": f"l'aiguille tourne : {countdown.text}"})
        tx = f.left + size + 70
        layers.append(text("compteur", shown(countdown), tx, cy - 90, 130, f, role="value",
                           start=t0, w_px=f.right - tx, count=counter(countdown, t0, t1 - t0, step=1)))
        layers.append({"type": "marker", "role": "decor", "id": "surligneur", "x": tx * k, "y": (cy + 30) * k,
                       "w": (f.right - tx - 10) * k, "h": 20, "color": GOLD, "opacity": 0.6, "from": t1,
                       "keys": [{"t": t1, "progress": 0}, {"t": t1 + 0.4, "progress": 1}],
                       "sfx": _sfx(t1, "chime.wav", 0.25)})
        layers.append(text("compteur-legende", countdown.label, tx, cy + 60, 56, f, color=GRAY, start=t0,
                           w_px=f.right - tx))
        return layers

    surface = f.bottom - 150                                   # la frise est le sol du personnage
    x0, x1 = f.left + 40, f.right - 50
    lo, hi = steps[0].value, steps[-1].value
    pos = {i: x0 + (x1 - x0) * (s.value - lo) / max(hi - lo, 1e-9) for i, s in enumerate(steps)}
    layers.append({"type": "path", "role": "decor", "id": "sol", "x": f.left * k, "y": surface * k, "lineWidth": 6,
                   "points": [(0, 0), ((f.right - f.left) * k, 0)],
                   "keys": [{"t": 0.05, "progress": 0}, {"t": 0.5, "progress": 1}], "surface": 0})
    t_walk0, t_walk1 = 0.2 * D, 0.85 * D
    # libellés répartis sans se chevaucher : deux étapes proches (0 et 5 ans sur 40) gardent un écart minimal
    label_w, gap = 225, 10
    anchors = [min(max(pos[i] - 80, f.left), f.right - label_w) for i in range(len(steps))]
    for i in range(1, len(anchors)):
        anchors[i] = max(anchors[i], anchors[i - 1] + label_w + gap)
    for i in range(len(anchors) - 1, -1, -1):
        limit = f.right - label_w if i == len(anchors) - 1 else anchors[i + 1] - label_w - gap
        anchors[i] = min(anchors[i], limit)
    if len(steps) * (label_w + gap) - gap > f.right - f.left:
        raise ValueError(f"frise : {len(steps)} étapes ne tiennent pas côte à côte")
    for i, step in enumerate(steps):
        frac = (pos[i] - x0) / max(x1 - x0, 1)
        t = t_walk0 + (t_walk1 - t_walk0) * frac
        layers.append({"type": "path", "role": "decor", "id": f"graduation-{i}", "x": pos[i] * k,
                       "y": (surface - 18) * k, "points": [(0, 0), (0, 36 * k)], "lineWidth": 6, "color": step.color,
                       "from": t, "sfx": _sfx(t, "tap.wav", 0.25)})
        anchor = anchors[i]
        layers.append(text(f"etape-{i}", step.text, anchor, surface + 26, 58, f, color=step.color, role="value",
                           start=t, w_px=label_w))
        if step.label:
            layers.append(text(f"etape-{i}-legende", step.label, anchor, surface + 88, 46, f, color=GRAY, start=t,
                               w_px=label_w, bold=True))
    char_h = min(300, surface - top - 30)
    margin = 60                                             # le personnage reste entier sur la frise
    who = grounded(resolve, walker, char_h, x0 + margin, surface, f)
    dx = (x1 - x0 - 2 * margin) * k
    who.update(id="marcheur", role="character", rests_on="sol",
               keys=[{"t": t_walk0, "x": who["x"]}, {"t": t_walk1, "x": who["x"] + dx}],
               motion="le personnage avance le long du temps")
    layers.append(who)
    return layers


# ---------- Scène de personnages ----------
def characters(cast: list[dict], *, resolve: Resolver, annotation: str = "", note: str = "", duration: float = 5.0,
               frame: Frame | None = None) -> list[dict]:
    """Un ou deux personnages posés au sol ; chacun peut changer de pose (« then ») à mi-scène. Annotation en
    Caveat soulignée (chiffre ou question tirée des paramètres, jamais du LLM). cast : [{"pose", "then", "x"}]."""
    f = frame or Frame()
    k, D = f.k, duration
    layers: list[dict] = []
    surface = f.bottom - 40
    top = f.top + 5
    if annotation:
        layers.append(text("annotation", annotation, f.left, top, 96, f, role="value", start=0.2,
                           sfx=_sfx(0.2, "paper.wav", 0.3)))
        layers.append({"type": "underline", "role": "decor", "id": "souligne", "x": f.left * k, "y": (top + 112) * k,
                       "w": 420 * k, "color": GOLD, "lineWidth": 9, "from": 0.6,
                       "keys": [{"t": 0.6, "progress": 0}, {"t": 1.0, "progress": 1}]})
        top += 130
    if note:
        layers.append(text("note", note, f.left, top, 58, f, color=GRAY, start=0.5))
        top += 70
    char_h = min(430, surface - top - 20)
    t_switch = 0.5 * D
    for i, person in enumerate(cast):
        cx = person.get("x", f.left + 200 + i * 420)
        first = grounded(resolve, person["pose"], char_h, cx, surface, f)
        first.update(id=f"perso-{i}", role="character", rests_on="sol", keys=_fade(0.1 + 0.2 * i))
        if person.get("then"):
            first["to"] = t_switch
            second = grounded(resolve, person["then"], char_h * person.get("then_scale", 1.0), cx, surface, f)
            y = second["y"]
            second.update(id=f"perso-{i}-reaction", role="character", rests_on="sol", sfx=_sfx(t_switch, "pop.wav", 0.3),
                          keys=[{"t": t_switch, "y": y}, {"t": t_switch + 0.2, "y": y - 24}, {"t": t_switch + 0.5, "y": y}],
                          motion=person.get("motion", "le personnage change d'expression"), **{"from": t_switch})
            layers += [first, second]
        else:
            layers.append(first)
    layers.append(ground(resolve, surface, f))
    return layers


# ---------- Carte de fin ----------
def end_card(*, resolve: Resolver, name: str, baseline: str, hypothesis: str = "", mention: str = "",
             question: str = "", duration: float = 4.0, frame: Frame | None = None) -> list[dict]:
    """Logo qui apparaît, nom et baseline ; hypothèse et mention (scène « rappel ») ou question finale (CTA)."""
    f = frame or Frame()
    k = f.k
    size = 230
    cx = (f.left + f.right) / 2
    y = f.top + 20
    layers: list[dict] = [{"type": "image", "role": "prop", "id": "logo", "path": "capital_simple_watermark.png",
                           "x": (cx - size / 2) * k, "y": y * k, "w": size * k, "h": size * k,
                           "pivotX": size / 2 * k, "pivotY": size / 2 * k, "sfx": _sfx(0.15, "pop.wav", 0.3),
                           "keys": [{"t": 0.15, "alpha": 0, "scaleX": 0.6, "scaleY": 0.6},
                                    {"t": 0.55, "alpha": 1, "scaleX": 1, "scaleY": 1}],
                           "motion": "le logo apparaît"}]
    y += size + 20
    layers.append(text("nom", name, f.left, y, 84, f, font="ui", start=0.5, w_px=f.right - f.left))
    y += 95
    layers.append(text("baseline", baseline, f.left, y, 60, f, color=TURQUOISE, start=0.7, w_px=f.right - f.left))
    y += 90
    if question:
        layers.append(text("question", question, f.left, y, 84, f, role="value", start=1.0, w_px=f.right - f.left,
                           sfx=_sfx(1.0, "paper.wav", 0.3)))
        y += 210
    if hypothesis:
        layers.append(text("hypothese", f"Hypothèse : {hypothesis}", f.left, y, 52, f, color=GRAY, start=1.0,
                           w_px=f.right - f.left))
        y += 120
    if mention:
        layers.append(text("mention", mention, f.left, y, 52, f, color=GRAY, start=1.3, w_px=f.right - f.left))
    return layers
