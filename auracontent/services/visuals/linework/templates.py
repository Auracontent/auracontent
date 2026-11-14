"""Gabarits de scènes dessinées, par FORME DE DONNÉES (réutilisables par tout concept) :

- two_amounts : deux montants comparés (variantes « arbres » et « piles ») ;
- (à venir) courbe dans le temps, part d'un tout, compte à rebours, scène de personnages, carte de fin.

Chaque gabarit renvoie une liste de calques pour engine.Scene. Les positions sont calculées en pixels de sortie
(1080x1920) dans la zone utile (entre le bandeau et les sous-titres, à gauche de x=930), puis converties sur le
plan de conception de 1280 de large du moteur. Les objets posés le sont d'après les pixels réels de leur sprite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from auracontent.services.visuals.linework.engine import DESIGN_WIDTH, _sprite

INK, TURQUOISE, GOLD, GRAY, PAPER = "#1A1A1A", "#0E9F8E", "#E0A526", "#5d6168", "#F7F3EA"


@dataclass
class Frame:
    """Zone utile en pixels de sortie et facteur vers le plan de conception."""
    width: int = 1080
    top: int = 470            # sous le bandeau
    bottom: int = 1185        # au-dessus des sous-titres
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
    idle: str = ""                         # pose au début (« hugo-neutral »)
    react: str = ""                        # pose à la révélation (« hugo-shock » / « lea-joy »)
    count_template: str = ""               # « Léa ≈ {n} € » : compteur ; vide = texte fixe
    extra: dict = field(default_factory=dict)


@lru_cache(maxsize=128)
def content_box(path: str) -> tuple[float, float, float, float]:
    """Boîte des pixels visibles du sprite, en fraction de sa taille (0..1)."""
    img = _sprite(path)
    bb = img.getchannel("A").getbbox() or (0, 0, img.width, img.height)
    return bb[0] / img.width, bb[1] / img.height, bb[2] / img.width, bb[3] / img.height


def _fade(t0: float, dur: float = 0.3) -> list[dict]:
    return [{"t": t0, "alpha": 0}, {"t": t0 + dur, "alpha": 1}]


def grounded(resolve, name: str, height_px: float, cx_px: float, surface_px: float, frame: Frame,
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


def two_amounts(left: Side, right: Side, *, resolve, title: str = "", subtitle: str = "",
                duration: float = 6.7, variant: str = "arbres", frame: Frame | None = None) -> list[dict]:
    """Deux montants comparés. Le plus petit pousse d'abord, le plus grand ensuite et le dépasse (suspense) ;
    compteurs sur les montants, le gagnant arrive et le perdant change d'expression ; surligneur or sur le
    résultat gagnant. `left` est le gagnant attendu (grande valeur), `right` le perdant."""
    f = frame or Frame()
    k = f.k
    winner, loser = (left, right) if left.value >= right.value else (right, left)
    D = duration
    t_small, t_big = 0.35, max(1.9, 0.65 * D)                       # rythme de la vidéo test (4,35 s sur 6,7)
    surface = f.bottom - 125                                        # sol ; montants écrits en dessous
    layers: list[dict] = []

    # Titre et hypothèse (Caveat), sous le bandeau
    if title:
        layers.append({"type": "text", "role": "text", "id": "titre", "text": title, "x": f.left * k,
                       "y": (f.top + 5) * k, "size": 76, "bold": True, "color": INK, "w": (f.right - f.left) * k,
                       "keys": _fade(0.1)})
    if subtitle:
        layers.append({"type": "text", "role": "text", "id": "hypothese", "text": subtitle, "x": f.left * k,
                       "y": (f.top + (68 if title else 5)) * k, "size": 42, "bold": True, "color": GRAY,
                       "w": (f.right - f.left) * k, "keys": _fade(0.1)})
    top_free = f.top + 5 + (62 if title else 0) + (45 if subtitle else 0)   # haut de la zone des objets

    # Objets : arbres (sprite tree-lea pour le gagnant, tree-hugo pour le perdant) ou piles de pièces
    big_h = surface - top_free - 10
    ratio = max(0.45, min(0.9, loser.value / max(winner.value, 1e-9)))
    cols = {"win_obj": f.left + 175, "win_char": f.left + 390, "lose_obj": f.left + 560, "lose_char": f.right - 75}
    if variant == "arbres":
        big_sprite, small_sprite = "tree-lea.png", "tree-hugo.png"
    elif variant == "piles":
        big_sprite, small_sprite = "stack-16.png", "stack-9.png"
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
    for obj, oid, t0, who in ((small, "objet-perdant", t_small, loser), (big, "objet-gagnant", t_big, winner)):
        hidden = surface * k + 8                                   # caché derrière le sol, puis il pousse
        obj.update(id=oid, role="prop", rests_on="sol",
                   keys=[{"t": t0, "y": hidden}, {"t": t0 + 1.1, "y": obj["y"]}],
                   motion=f"{who.name} : l'objet pousse jusqu'à {who.value_text}")
        layers.append(obj)

    # Sol (dessiné après les objets : il les cache pendant qu'ils poussent)
    ground_path = str(resolve("ground.png"))
    _, gy0, _, _ = content_box(ground_path)
    g_img = _sprite(ground_path)
    g_w = DESIGN_WIDTH
    g_h = g_w * g_img.height / g_img.width
    layers.append({"type": "image", "role": "decor", "id": "sol", "path": "ground.png", "x": 0,
                   "y": surface * k - g_h * gy0 - 4 * k, "w": g_w, "h": g_h, "surface": g_h * gy0 + 4 * k})

    # Personnages : le perdant attend (pose neutre), puis réagit ; le gagnant arrive à la révélation
    char_h = min(330, surface - top_free - 40)
    t_react = t_big + 1.0
    if loser.idle:
        idle = grounded(resolve, loser.idle, char_h, cols["lose_char"], surface, f)
        idle.update(id="perdant", role="character", rests_on="sol", to=t_react, keys=_fade(0.2))
        layers.append(idle)
    if loser.react:
        react = grounded(resolve, loser.react, char_h * 1.03, cols["lose_char"], surface, f)
        y = react["y"]
        react.update(id="perdant-reaction", role="character", rests_on="sol", **{"from": t_react},
                     keys=[{"t": t_react, "y": y}, {"t": t_react + 0.25, "y": y - 30}, {"t": t_react + 0.6, "y": y}],
                     motion=f"{loser.name} sursaute devant le résultat de {winner.name}")
        layers.append(react)
    if winner.react:
        enter = grounded(resolve, winner.react, char_h * 1.03, cols["win_char"], surface, f)
        x = enter["x"]
        enter.update(id="gagnant", role="character", rests_on="sol", **{"from": t_big + 0.6},
                     keys=[{"t": t_big + 0.6, "x": x - 120, "alpha": 0}, {"t": t_big + 1.1, "x": x, "alpha": 1}],
                     motion=f"{winner.name} arrive quand son résultat apparaît")
        layers.append(enter)

    # Montants sous le sol : compteur, puis surligneur or sous le résultat gagnant
    for who, oid, x_px, t0 in ((loser, "montant-perdant", f.left + 480, t_small + 0.9),
                               (winner, "montant-gagnant", f.left, t_big + 0.9)):
        layer = {"type": "text", "role": "value", "id": oid, "text": who.count_template.replace(
            "{n}", who.value_text) if who.count_template else who.value_text,
            "x": x_px * k, "y": (surface + 14) * k, "size": 64, "bold": True, "color": who.color,
            "w": 430 * k, **{"from": t0}, "keys": _fade(t0, 0.2)}
        if who.count_template:
            layer["text"] = who.count_template
            layer["count"] = {"from": 0, "to": who.value, "t0": t0, "t1": t0 + 0.9,
                              "template": who.count_template, "step": who.extra.get("step", 10)}
        if who is winner:                                    # surligneur or sous le résultat gagnant
            layers.append({"type": "marker", "role": "decor", "id": "surligneur", "x": x_px * k - 6,
                           "y": (surface + 58) * k, "w": 330 * k, "h": 20, "color": GOLD, "opacity": 0.6,
                           "from": t0 + 0.9, "keys": [{"t": t0 + 0.9, "progress": 0}, {"t": t0 + 1.4, "progress": 1}]})
        layers.append(layer)
        if who.caption:
            layers.append({"type": "text", "role": "text", "id": f"{oid}-legende", "text": who.caption,
                           "x": x_px * k, "y": (surface + 72) * k, "size": 40, "bold": False, "color": GRAY,
                           "w": 430 * k, **{"from": t0}, "keys": _fade(t0, 0.2)})
    return layers
