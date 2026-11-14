"""Scènes dessinées de Capital Simple : chiffres de calc.py -> gabarits linework (forme de données).

Les sprites (Léa, Hugo, accessoires) sont ceux de la vidéo test, versionnés dans assets/finance/characters et
assets/finance/props ; tools/finance/draw-assets.mjs (hors CI) les redessine. Fond papier #F7F3EA quadrillé,
annotations en Caveat, chiffres soulignés à l'or de la charte.
"""
from __future__ import annotations

from pathlib import Path

from auracontent.channels.finance import calc as fcalc
from auracontent.services.visuals.linework import templates as tpl
from auracontent.services.visuals.linework.engine import Scene
from auracontent.services.visuals.linework.layout import Zones, check_layout

ASSETS = Path(__file__).resolve().parents[3] / "assets" / "finance"
ASSET_DIRS = [ASSETS / "characters", ASSETS / "props"]
FONTS = {"hand": ASSETS / "fonts" / "Caveat.ttf", "ui": ASSETS / "fonts" / "Poppins-Bold.ttf"}


def resolve(name: str) -> Path:
    for base in ASSET_DIRS:
        if (base / name).exists():
            return base / name
    raise FileNotFoundError(f"sprite finance introuvable : {name}")


def make_scene(layers: list[dict], duration: float, cfg: dict | None = None) -> Scene:
    cfg = dict(cfg or {})
    return Scene(layers=layers, duration=duration, background=cfg.get("background", tpl.PAPER),
                 grid=cfg.get("grid", True), fonts={k: str(v) for k, v in FONTS.items()},
                 asset_dirs=[str(d) for d in ASSET_DIRS])


def lea_hugo_trees(params: dict, duration: float = 6.7, cfg: dict | None = None) -> Scene:
    """Intérêts composés, scène du résultat : l'arbre de Hugo pousse, puis celui de Léa le dépasse."""
    c = fcalc.compute("interets_composes", params)
    lea = tpl.Side(name="Léa", value=c["lea_final"], value_text=c.values["lea_final"].text,
                   caption=f"({fcalc.fmt_number(params['early_amount'])} € à {params['early_age']} ans)",
                   color=tpl.TURQUOISE, react="lea-joy.png", count_template="Léa ≈ {n} €")
    hugo = tpl.Side(name="Hugo", value=c["hugo_final"], value_text=c.values["hugo_final"].text,
                    caption=f"({fcalc.fmt_number(params['late_amount'])} € à {params['late_age']} ans)",
                    color=tpl.INK, idle="hugo-neutral.png", react="hugo-shock.png", count_template="Hugo ≈ {n} €")
    layers = tpl.two_amounts(lea, hugo, resolve=resolve, title=f"À {params['end_age']} ans",
                             subtitle=f"Hypothèse : {fcalc.fmt_number(params['rate'])} %/an, versement unique",
                             duration=duration, variant="arbres")
    scene = make_scene(layers, duration, cfg)
    check_layout(scene, Zones.from_config((cfg or {}).get("layout")))
    return scene
