"""Rendu V2 des scènes du pipeline finance (option `visuals.linework.engine: v2` du YAML finance).

Principe « montrer plutôt que tracer », un seul graphique par vidéo au plus :
- gabarit « barres » (hors jauge) -> étiquettes de prix qui glissent et s'empilent ; en accroche, gros chiffre
  sur un éclat, avec les objets du sujet qui tombent ;
- gabarit « personnages » -> la scène actuelle + les objets du sujet qui apparaissent autour du personnage ;
- autres gabarits (courbe, deux montants, frise, carte de fin) -> rendu actuel ;
- toutes les scènes : caméra (léger travelling ; zoom avec élan sur le chiffre clé des révélations).

Tous les chiffres viennent de calc.py (mêmes données que visuals.py). Une scène V2 qui ne passe pas le contrôle
de mise en page bloquant retombe sur le rendu actuel (jamais de vidéo refusée à cause de la V2).
"""
from __future__ import annotations

import re
from pathlib import Path

from auracontent.channels.finance import calc as fcalc
from auracontent.channels.finance import visuals as fvis
from auracontent.services.visuals.linework import templates as tpl
from auracontent.services.visuals.linework.engine import Scene
from auracontent.services.visuals.linework.layout import LayoutError, Zones, check_layout

from . import captions, director, props
from .director import Shot

INK, T, GOLD, GRAY = props.INK, props.TURQUOISE, props.GOLD, props.GRAY
S = 1280 / 1080
REVEAL_ROLES = ("reveal", "example")
HOOK_BURST_W, HOOK_BURST_Y = 860, 560        # éclat de l'accroche (pixels de sortie) : x 110..970, y 560..1044
HOOK_NUMBER_MAX_W = 640                      # largeur du gros chiffre : tient dans l'ovale intérieur de l'éclat


def d(px: float) -> float:
    return px * S


def _pop(t, ease="back", dur=0.35, scale=True) -> list[dict]:
    k = [{"t": t, "alpha": 0}, {"t": t + dur * 0.5, "alpha": 1}]
    if scale:
        k += [{"t": t, "scaleX": 0.4, "scaleY": 0.4}, {"t": t + dur, "scaleX": 1, "scaleY": 1, "ease": ease}]
    return k


def _number_time(words: list[captions.Word], text: str, default: float) -> float:
    """Instant où la voix dit le nombre de `text` (« 1 768 € » -> le mot qui contient « 768 »)."""
    nums = re.findall(r"\d+(?:[.,]\d+)?", text.replace(" ", "").replace(" ", "").replace(" ", ""))
    if not nums:
        return default
    tail = nums[0][-3:]
    for w in words:
        if tail in w.text.replace(" ", "").replace(" ", ""):
            return w.start
    return default


def _items(concept: str, params: dict, c: fcalc.Calc, role: str):
    """Montants du gabarit « barres » (mêmes données que le rendu actuel). La jauge des concepts d'origine
    a aussi ses montants (« sur le compte » / « ce que ça achète ») : la V2 les montre en étiquettes."""
    if concept in fvis.GENERIC:
        return fvis._g_bars(concept, params, c)
    items, _share, _ = fvis._bars(concept, params, c, role)
    return items


def value_text(item: tpl.Item) -> str:
    """Texte affiché d'un montant : le modèle du rendu actuel (« × 2,7 », « 4 656 € »), valeur de calc.py."""
    if item.count_template and "{n}" in item.count_template:
        return item.count_template.replace("{n}", tpl.fmt_num(item.value)).strip()
    return item.text


def key_index(items: list[tpl.Item], c: fcalc.Calc) -> int | None:
    """Rang du montant qui porte le résultat principal de calc.py (c.headline) ; None s'il n'est pas parmi eux.
    Jamais « le plus grand » par défaut : il peut s'agir de l'idée fausse que la vidéo corrige (remise crue)."""
    head = c.values[c.headline].value
    for i, item in enumerate(items):
        if abs(float(item.value) - float(head)) < 1e-6:
            return i
    return None


def _icons(concept: str, pdir: Path) -> list[str]:
    return [props.ensure(n, pdir) for n in props.CONCEPT_PROPS.get(concept, ("coin", "piggy"))]


# ---------- Accroche : gros chiffre sur un éclat, objets du sujet qui tombent ----------
def hook_layers(items: list[tpl.Item], icons: list[str], duration: float, c: fcalc.Calc) -> tuple[list[dict], float]:
    """Gros chiffre = résultat principal de calc.py (jamais l'intuition fausse), libellé du montant correspondant."""
    k = key_index(items, c)
    if k is not None:
        best = items[k]
    else:
        v = c.values[c.headline]
        best = tpl.Item(v.label, v.value, v.text, T, "")
    t_num = 0.0                      # le résultat est visible dès la première image (rétention des 2 premières s)
    start = [{"t": 0, "alpha": 1, "scaleX": 0.8, "scaleY": 0.8}, {"t": 0.45, "scaleX": 1, "scaleY": 1, "ease": "back"}]
    # Éclat ovale centré, assez large pour le chiffre entier (l'éclat rond de 560 px laissait déborder
    # « 23 » et « € ») ; il grossit depuis son centre. Bas de l'éclat à y = 560 + 484 = 1044.
    bw, bx, by = HOOK_BURST_W, (1080 - HOOK_BURST_W) / 2, HOOK_BURST_Y
    bh = bw * props.BURST_WIDE[1] / props.BURST_WIDE[0]
    L = [{"type": "image", "id": "eclat", "role": "decor", "path": props.ensure("burst-wide", Path(icons[0]).parent),
          "x": d(bx), "y": d(by), "w": d(bw), "pivotX": d(bw / 2), "pivotY": d(bh / 2), "from": 0, "keys": start}]
    n = len(icons)
    for i, p in enumerate(icons):
        x = 120 + i * (640 / max(1, n - 1)) if n > 1 else 400
        L.append({"type": "image", "id": f"objet-{i}", "role": "prop", "path": p, "x": d(x), "w": d(150),
                  "keys": [{"t": 0.05 + i * 0.18, "y": d(470), "alpha": 0}, {"t": 0.12 + i * 0.18, "alpha": 1},
                           {"t": 0.7 + i * 0.18, "y": d(480 + (i % 2) * 20), "ease": "bounce"}],
                  "sfx": [{"at": 0.6 + i * 0.18, "file": "pop.wav", "gain": 0.28}]})
    # Gros chiffre sur une ligne, centré dans l'ovale intérieur de l'éclat (mesuré en Poppins, sa police)
    shown_value = value_text(best)
    size = 170
    while size > 90 and props._font(size, "ui").getlength(shown_value) > HOOK_NUMBER_MAX_W:
        size -= 10
    tw = props._font(size, "ui").getlength(shown_value)
    ny = by + bh / 2 - 0.66 * size                # centre visuel des chiffres sur le centre de l'éclat
    L.append({"type": "text", "id": "chiffre", "role": "value", "text": shown_value, "font": "ui", "size": d(size),
              "x": d(540 - tw / 2), "y": d(ny), "w": d(tw + 40), "pivotX": d(tw / 2), "pivotY": d(0.66 * size),
              "color": INK, "from": 0, "keys": list(start), "sfx": [{"at": 0.05, "file": "chime.wav", "gain": 0.4}]})
    # Libellé sous l'éclat (il passait sur ses pointes), centré ; plus petit s'il tient sur deux lignes
    # Centré sous le chiffre quand il tient, toujours dans la zone sûre x 70..910 (droite masquée par l'interface)
    label_size = 84 if tpl.lines_of(best.label, d(84), 820) <= 1 else 64
    lw = min(820.0, props._font(label_size, "hand").getlength(best.label))
    lx = max(70.0, min(540 - lw / 2, 910 - lw - 20))
    L.append({"type": "text", "id": "libelle", "role": "text", "text": best.label, "font": "hand",
              "size": d(label_size), "x": d(lx), "y": d(by + bh + 14), "w": d(lw + 20), "color": INK,
              "from": 0, "keys": [{"t": 0, "alpha": 0.6}, {"t": 0.35, "alpha": 1}]})
    return L, t_num


# ---------- Étiquettes de prix qui glissent et s'empilent ----------
def tag_layers(items: list[tpl.Item], words: list[captions.Word], duration: float, pdir: Path,
               hypothesis: str = "", c: fcalc.Calc | None = None) -> tuple[list[dict], float]:
    L = []
    top = 490
    if hypothesis:
        L.append({"type": "text", "id": "hypothese", "role": "text", "text": hypothesis, "font": "hand",
                  "size": d(56), "x": d(70), "y": d(top), "w": d(850), "color": GRAY, "from": 0.1,
                  "keys": [{"t": 0.1, "alpha": 0}, {"t": 0.35, "alpha": 1}]})
        top += 70 * tpl.lines_of(hypothesis, d(56), 850)
    n = len(items)
    step = min(200, (1180 - top) / max(n, 1))
    k = key_index(items, c) if c is not None else None
    best = k if k is not None else max(range(n), key=lambda i: items[i].value)
    t_best = 0.0
    for i, item in enumerate(items):
        default = 0.3 + i * min(0.8, duration / (n + 2))
        t = min(max(0.2, _number_time(words, item.text, default)), duration - 1.0)
        y = top + 20 + i * step
        shown_text = value_text(item)
        key = re.sub(r"\W", "", shown_text) or str(i)
        tag = props.ensure(f"etiquette-{key}-{int(i == best)}", pdir,
                           lambda txt=shown_text, i=i: props.price_tag(txt, f"etiquette-{i}",
                                                                       color=props.PALE if i != best else "#F6E1A8"))
        from PIL import Image
        tw = min(500, Image.open(tag).width * 1.15)
        L.append({"type": "image", "id": f"etiquette-{i}", "role": "prop", "path": tag, "x": d(80), "y": d(y),
                  "w": d(tw), "from": t, "keys": [{"t": t, "x": d(-500), "alpha": 0}, {"t": t + 0.1, "alpha": 1},
                                                  {"t": t + 0.45, "x": d(80), "ease": "back"}],
                  "sfx": [{"at": t, "file": "tap.wav", "gain": 0.3}]})
        L.append({"type": "text", "id": f"libelle-{i}", "role": "text", "text": item.label, "font": "hand",
                  "size": d(64), "x": d(80 + tw + 30), "y": d(y + 18), "w": d(max(200, 900 - 80 - tw - 30)),
                  "color": INK if i == best else GRAY, "from": t + 0.3,
                  "keys": [{"t": t + 0.3, "alpha": 0}, {"t": t + 0.55, "alpha": 1}]})
        if i == best:
            t_best = t
            L.append({"type": "marker", "id": "surligneur", "role": "decor", "x": d(80 + tw + 24), "y": d(y + 92),
                      "w": d(min(320, 900 - 80 - tw - 30)), "h": d(22), "color": GOLD, "opacity": 0.7,
                      "from": t + 0.6, "keys": [{"t": t + 0.6, "progress": 0}, {"t": t + 0.95, "progress": 1}],
                      "sfx": [{"at": t + 0.6, "file": "chime.wav", "gain": 0.3}]})
    return L, t_best


# ---------- Personnages : objets du sujet autour ----------
def with_icons(layers: list[dict], icons: list[str], duration: float,
               words: list[captions.Word] | None = None) -> list[dict]:
    """Objets du sujet autour du personnage. Avec `words` (minutage de la voix de la scène), chaque objet
    apparaît pendant que la voix parle, réparti sur la phrase ; sans eux, instants fixes (comportement d'origine)."""
    out = list(layers)
    shown = icons[:3]
    for i, p in enumerate(shown):
        t = 0.5 + i * 0.3
        if words:
            k = min(len(words) - 1, int((i + 1) * len(words) / (len(shown) + 1)))
            t = min(max(0.3, words[k].start), max(0.3, duration - 0.9))
        y = 640 + i * 170
        out.append({"type": "image", "id": f"objet-{i}", "role": "prop", "path": p, "x": d(760), "y": d(y), "w": d(140),
                    "from": t, "keys": _pop(t, "back", 0.35) + [{"t": t + 0.35, "angle": 0},
                                                                 {"t": t + 0.8, "angle": 0.08, "ease": "smooth"},
                                                                 {"t": t + 1.3, "angle": 0.0, "ease": "smooth"}],
                    "sfx": [{"at": t, "file": "pop.wav", "gain": 0.25}]})
    return out


# ---------- Caméra ----------
def _scene_index(scene: dict) -> int:
    """Rang de la scène (pour alterner le sens de la dérive de caméra) ; 0 si l'identifiant n'est pas un entier."""
    try:
        return int(scene.get("id", 0))
    except (TypeError, ValueError):
        return 0


def camera(role: str, duration: float, focus_t: float | None, focus_y: float = 860, index: int = 0) -> list[dict]:
    """Caméra d'une scène. Reste dans la zone sûre : au plus 1,10 de zoom, et un centre horizontal qui garde la
    zone sûre x 60..930 (layout.Zones) entièrement visible (le cadrage est appliqué après le contrôle de mise en page).
    - accroche : coup de zoom net sur le gros chiffre (1,0 -> 1,06), puis lente avancée ;
    - révélation : élan sur le chiffre clé au moment où la voix le dit, puis léger retour (rebond) ;
    - autres scènes : travelling lent dont le sens alterne d'une scène à l'autre ;
    - question finale et mention : plan fixe."""
    if role in ("disclaimer", "cta"):
        return []
    even = index % 2 == 0
    if role == "hook" and duration > 0.6:
        return [{"t": 0, "zoom": 1.0}, {"t": 0.45, "zoom": 1.06, "cx": 540, "cy": 900, "ease": "back"},
                {"t": duration, "zoom": 1.08, "cx": 540, "cy": 900, "ease": "linear"}]
    if role in REVEAL_ROLES and focus_t is not None:
        keys = [{"t": 0, "zoom": 1.0}, {"t": focus_t, "zoom": 1.0},
                {"t": min(duration, focus_t + 0.5), "zoom": 1.1, "cx": 500 if even else 540, "cy": focus_y,
                 "ease": "back"}]
        if focus_t + 1.2 < duration - 0.05:
            keys.append({"t": focus_t + 1.2, "zoom": 1.07, "ease": "smooth"})   # rebond : léger retour après l'élan
        return keys
    return [{"t": 0, "zoom": 1.0},
            {"t": duration, "zoom": 1.04, "cx": 500 if even else 560, "cy": 860 if even else 960, "ease": "linear"}]


# ---------- Une scène ----------
def scene_shot(concept: str, params: dict, scene: dict, duration: float, *, hypothesis: str, question: str,
               pdir: Path) -> tuple[Shot, str]:
    """(plan V2, moteur utilisé : « v2 » ou « v1 ») ; les calques V1 servent de repli et de base."""
    c = fcalc.compute(concept, params)
    role, template = scene.get("role"), scene.get("template")
    words = captions.estimate(scene.get("text", ""), 0.15, max(0.5, duration - 0.5))
    icons = _icons(concept, pdir)
    focus = None
    layers = None
    # Barres et jauge : en V2, étiquettes (ou gros chiffre en accroche), un graphique de moins dans la vidéo.
    if template == "barres":
        items = _items(concept, params, c, role)
        if items:
            if role == "hook":
                layers, focus = hook_layers(items, icons, duration, c)
            else:
                layers, focus = tag_layers(items, words, duration, pdir, hypothesis, c)
    elif template == "personnages":
        base = fvis.scene_layers(concept, params, scene, duration, hypothesis=hypothesis, question=question)
        layers = with_icons(base, icons, duration, words)
    idx = _scene_index(scene)
    if layers is None:
        base = fvis.scene_layers(concept, params, scene, duration, hypothesis=hypothesis, question=question)
        focus = duration * 0.55 if role in REVEAL_ROLES else None
        return Shot(base, duration, camera(role, duration, focus, index=idx)), "v1"
    return Shot(layers, duration, camera(role, duration, focus, index=idx)), "v2"


def _scene_kwargs(cfg: dict) -> dict:
    return {"background": cfg.get("background", tpl.PAPER), "grid": cfg.get("grid", True),
            "fonts": {k: str(v) for k, v in fvis.FONTS.items()}, "asset_dirs": [str(p) for p in fvis.ASSET_DIRS]}


def render_scenes(script: dict, scenes: list[dict], work_dir: Path, cfg: dict | None = None) -> list[str]:
    """Même contrat que visuals.render_scenes : un clip MP4 par scène (durée = voix + 0,25 s), effets sonores
    dans scene["sfx_cues"]. La voix, le bandeau, les sous-titres et les transitions restent au compositeur."""
    cfg = dict(cfg or {})
    pick = script.get("pick") or {}
    concept, params = pick["concept"], pick["params"]
    out = Path(work_dir) / "visuals"
    pdir = out / "objets"
    zones = Zones.from_config(cfg.get("layout"))
    kwargs = _scene_kwargs(cfg)
    clips = []
    for scene in scenes:
        duration = float(scene.get("duration") or 4.0) + 0.25
        hyp, question = script.get("hypothesis", ""), script.get("closing_cta", "")
        shot, engine = scene_shot(concept, params, scene, duration, hypothesis=hyp, question=question, pdir=pdir)
        if engine == "v2":
            try:
                check_layout(Scene(layers=shot.layers, duration=duration, **kwargs), zones)
            except LayoutError as e:
                print(f"     ↩️ Scène {scene['id']} : mise en page V2 refusée ({str(e)[:160]}), rendu actuel utilisé")
                base = fvis.scene_layers(concept, params, scene, duration, hypothesis=hyp, question=question)
                shot, engine = Shot(base, duration, camera(scene.get("role"), duration, None,
                                                           index=_scene_index(scene))), "v1"
        if engine == "v1":
            check_layout(Scene(layers=shot.layers, duration=duration, **kwargs), zones)
        scene["sfx_cues"] = tpl.cues(shot.layers, duration - 0.25)
        clips.append(str(director.render_shot(shot, kwargs, out / f"scene_{scene['id']}.mp4")))
        print(f"     🎬 Scène {scene['id']} [{scene.get('role')} / {scene.get('template', 'carte_fin')}] "
              f"V2 ({engine}) {duration:.1f} s, {len(scene['sfx_cues'])} effet(s)")
    return clips
