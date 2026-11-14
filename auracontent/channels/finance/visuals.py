"""Scènes dessinées de Capital Simple : chiffres de calc.py -> gabarits linework (par forme de données).

Chaque scène du script porte son rôle, son gabarit (storyboard.py, fixé par le code) et sa variante (`visual`,
choisie par le LLM parmi les variantes dessinables). Les chiffres à l'écran viennent TOUJOURS de calc.py et des
paramètres du sujet, jamais du texte du LLM. Sprites de la vidéo test (assets/finance/characters, props), fond
papier quadrillé, annotations en Caveat, chiffres soulignés à l'or de la charte.
"""
from __future__ import annotations

from pathlib import Path

from auracontent.channels.finance import calc as fcalc
from auracontent.services.visuals.linework import templates as tpl
from auracontent.services.visuals.linework.engine import Scene, render_mp4
from auracontent.services.visuals.linework.layout import Zones, check_layout

ASSETS = Path(__file__).resolve().parents[3] / "assets" / "finance"
ASSET_DIRS = [ASSETS / "characters", ASSETS / "props", ASSETS / "images"]
FONTS = {"hand": ASSETS / "fonts" / "Caveat.ttf", "ui": ASSETS / "fonts" / "Poppins-Bold.ttf"}
NAME, BASELINE = "Capital Simple", "Les chiffres, sans jargon."
MENTION = "Contenu pédagogique, pas un conseil en investissement."
T, K, G = tpl.TURQUOISE, tpl.INK, tpl.GRAY      # turquoise, encre, gris
fmt = fcalc.fmt_number


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


def _item(c: fcalc.Calc, key: str, label: str, color: str = T, template: str | None = None) -> tpl.Item:
    v = c.values[key]
    unit = f" {v.unit}" if v.unit else ""
    return tpl.Item(label, v.value, v.text, color, template if template is not None else "{n}" + unit)


def _p(value: float, unit: str, label: str = "", color: str = T) -> tpl.Item:
    """Item d'un paramètre du sujet (montant, âge, durée)."""
    return tpl.Item(label, value, f"{fmt(value)} {unit}".strip(), color, "{n} " + unit if unit else "{n}")


# ---------- Correspondance concept -> données de chaque forme ----------
def _two(concept, p, c):
    """(gagnant, perdant) pour « deux montants »."""
    if concept == "interets_composes":
        lea = tpl.Side("Léa", c["lea_final"], c.values["lea_final"].text, f"({fmt(p['early_amount'])} € à {p['early_age']} ans)",
                       T, react="lea-joy.png", count_template="Léa ≈ {n} €")
        hugo = tpl.Side("Hugo", c["hugo_final"], c.values["hugo_final"].text, f"({fmt(p['late_amount'])} € à {p['late_age']} ans)",
                        K, idle="hugo-neutral.png", react="hugo-shock.png", count_template="Hugo ≈ {n} €")
        return lea, hugo, f"À {p['end_age']} ans"
    pairs = {"cout_du_temps": ("final_now", "Tout de suite", "final_late", f"{p.get('delay_years')} ans plus tard"),
             "frais": ("final_without", "Sans frais", "final_with", "Avec frais"),
             "inflation": (None, "Sur le compte", "real_value", "Ce que ça achète")}
    wk, wl, lk, ll = pairs[concept]
    win_v = p["amount"] if wk is None else c[wk]
    win_t = f"{fmt(p['amount'])} €" if wk is None else c.values[wk].text
    win = tpl.Side(wl, win_v, win_t, color=T, react="lea-joy.png", count_template=wl + " : {n} €")
    lose = tpl.Side(ll, c[lk], c.values[lk].text, color=K, idle="hugo-neutral.png", react="hugo-shock.png",
                    count_template=ll + " : {n} €")
    return win, lose, ""


def _curve(concept, p, c):
    s = c.series
    if concept == "interets_composes":
        return (_item(c, "lea_final", "Léa"), _item(c, "hugo_final", "Hugo", K), None,
                (f"{p['early_age']} ans", f"{p['end_age']} ans"))
    if concept == "cout_du_temps":
        return (_item(c, "final_now", "Tout de suite"), _item(c, "final_late", f"{p['delay_years']} ans plus tard", K),
                _item(c, "cost", "Coût de l'attente", K), ("0", f"{p['horizon_years']} ans"))
    if concept == "frais":
        return (_item(c, "final_without", "Sans frais"), _item(c, "final_with", "Avec frais", K),
                _item(c, "lost", "Coût des frais", K), ("0", f"{p['years']} ans"))
    if concept == "inflation":
        return (tpl.Item("Sur le compte", p["amount"], f"{fmt(p['amount'])} €", T, "{n} €"),
                _item(c, "real_value", "Ce que ça achète", K), _item(c, "lost", "Pouvoir d'achat perdu", K),
                ("0", f"{p['years']} ans"))
    if concept == "regle_72":                               # 100 € placés aux deux taux
        n = s["x"][-1]
        return (tpl.Item(f"À {fmt(p['rate_b'])} %", s["b"][-1], f"{fmt(s['b'][-1])} €", T, "{n} €"),
                tpl.Item(f"À {fmt(p['rate'])} %", s["a"][-1], f"{fmt(s['a'][-1])} €", K, "{n} €"), None,
                ("0", f"{n} ans"))
    raise KeyError(concept)


def _bars(concept, p, c, role):
    """(barres, part d'un tout ou None, légende de la part)."""
    if concept == "interets_composes":
        if role == "takeaway":
            return [_item(c, "lea_multiple", "mise de Léa", T, "\u00d7 {n}"),
                    _item(c, "hugo_multiple", "mise de Hugo", K, "\u00d7 {n}")], None, ""
        return [_p(p["early_amount"], "€", "Léa", T), _p(p["late_amount"], "€", "Hugo", K)], None, ""
    if concept == "inflation":
        share = _item(c, "lost_pct", "")
        return ([_p(p["amount"], "€", "sur le compte", T), _item(c, "real_value", "ce que ça achète", K)],
                share, f"du pouvoir d'achat perdu en {p['years']} ans")
    if concept == "cout_du_temps":
        share = _item(c, "cost_pct", "")
        return ([_item(c, "paid_gap", "versé en plus", K), _item(c, "cost", "gagné en plus", T)],
                share, f"du résultat perdu en attendant {p['delay_years']} ans")
    if concept == "frais":
        share = _item(c, "lost_pct_gains", "")
        items = [_item(c, "final_without", "sans frais", T), _item(c, "final_with", "avec frais", K)]
        if role == "takeaway":
            items.append(_item(c, "lost", "frais payés", G))
        return items, share, "des gains partent en frais"
    if concept == "regle_72":
        a = _item(c, "years_rule", f"à {fmt(p['rate'])} %", K)
        b = _item(c, "years_rule_b", f"à {fmt(p['rate_b'])} %", T)
        return ([a] if role == "reveal" else [a, b]), None, ""
    raise KeyError(concept)


def _time(concept, p, c, role):
    """(étapes de la frise, compte à rebours, marcheur)."""
    if concept == "interets_composes":
        steps = [_p(p["early_age"], "ans", f"Léa : {fmt(p['early_amount'])} €", T),
                 _p(p["late_age"], "ans", f"Hugo : {fmt(p['late_amount'])} €", K), _p(p["end_age"], "ans", "arrivée", G)]
        return steps, _item(c, "lea_years", "de placement pour Léa", T), "lea-neutral.png"
    if concept == "cout_du_temps":
        steps = [_p(0, "", "début", T), _p(p["delay_years"], "ans", "on attend", K),
                 _p(p["horizon_years"], "ans", "fin", G)]
        return steps, _p(p["delay_years"], "ans", "d'attente", K), "lea-neutral.png"
    if concept == "frais":
        steps = [_p(0, "", "départ", T), _p(p["years"], "ans", "arrivée", G)]
        return steps, _p(p["years"], "ans", f"à {fmt(p['rate'])} %/an et {fmt(p['fees'])} % de frais", T), "hugo-neutral.png"
    if concept == "inflation":
        steps = [_p(0, "", "aujourd'hui", T), _p(p["years"], "ans", "plus tard", G)]
        if role == "takeaway":
            return steps, _item(c, "price_of_100", "pour ce qui coûte 100 € aujourd'hui", T, "{n} €"), "lea-neutral.png"
        return steps, _p(p["years"], "ans", f"à {fmt(p['inflation'])} % d'inflation par an", T), "lea-neutral.png"
    if concept == "regle_72":
        steps = [_p(0, "", "départ", G), _item(c, "years_rule_b", f"double à {fmt(p['rate_b'])} %", T),
                 _item(c, "years_rule", f"double à {fmt(p['rate'])} %", K)]
        label = f"72 \u00f7 {fmt(p['rate'])} : pour doubler à {fmt(p['rate'])} %"
        return steps, _item(c, "years_rule", label, T, "{n} ans"), "lea-neutral.png"
    raise KeyError(concept)


def _cast(concept, p):
    """(personnages, annotation, note) de la scène de personnages : textes tirés des paramètres."""
    if concept == "interets_composes":
        cast = [{"pose": "lea-neutral.png", "then": "lea-shrug.png", "x": 250},
                {"pose": "hugo-neutral.png", "then": "hugo-smug.png", "x": 680, "motion": "Hugo, sûr de lui"}]
        return cast, f"\u00d7 {fmt(p['late_amount_factor'])}", f"Hugo met {fmt(p['late_amount_factor'])} fois plus"
    if concept == "cout_du_temps":
        return ([{"pose": "lea-neutral.png", "then": "lea-shrug.png", "x": 420}],
                f"Attendre {p['delay_years']} ans ?", f"{fmt(p['monthly'])} € par mois")
    return [{"pose": "lea-neutral.png", "then": "lea-surprise.png", "x": 420}], "", ""


# ---------- Scène ----------
def scene_layers(concept: str, params: dict, scene: dict, duration: float, *, hypothesis: str = "",
                 question: str = "") -> list[dict]:
    """Calques d'une scène du script (rôle, gabarit, variante) d'après calc.py."""
    c = fcalc.compute(concept, params)
    role, template, variant = scene.get("role"), scene.get("template"), scene.get("visual")
    if role == "cta":
        return tpl.end_card(resolve=resolve, name=NAME, baseline=BASELINE, question=question, duration=duration)
    if template == "carte_fin":
        return tpl.end_card(resolve=resolve, name=NAME, baseline=BASELINE, hypothesis=hypothesis, mention=MENTION,
                            duration=duration)
    if template == "deux_arbres":
        win, lose, title = _two(concept, params, c)
        return tpl.two_amounts(win, lose, resolve=resolve, title="", subtitle=(f"{title} · " if title else "") + hypothesis,
                               duration=duration, variant=variant if variant in ("arbres", "piles") else "arbres")
    if template == "deux_courbes":
        a, b, gap, xl = _curve(concept, params, c)
        series = c.series
        if concept == "regle_72":                          # courbe la plus haute en premier (« a »)
            series = {**series, "a": series["b"], "b": series["a"]}
        return tpl.curve_in_time(series, a, b, x_labels=xl, subtitle=hypothesis, gap=gap, duration=duration,
                                 variant=variant if variant in ("courbes", "ecart") else "courbes")
    if template == "barres":
        items, share, caption = _bars(concept, params, c, role)
        use_gauge = variant == "jauge" and share is not None
        return tpl.bars(items, subtitle=hypothesis, duration=duration, variant="jauge" if use_gauge else "barres",
                        share=share, share_caption=caption)
    if template == "curseur_temps":
        steps, countdown, walker = _time(concept, params, c, role)
        return tpl.timeline(steps, resolve=resolve, subtitle=hypothesis, duration=duration,
                            variant=variant if variant in ("frise", "sablier") else "frise",
                            walker=walker, countdown=countdown)
    if template == "personnages":
        cast, annotation, note = _cast(concept, params)
        return tpl.characters(cast, resolve=resolve, annotation=annotation, note=note, duration=duration)
    raise ValueError(f"gabarit inconnu : {template}")


def build_scene(concept: str, params: dict, scene: dict, duration: float, cfg: dict | None = None, **kw) -> Scene:
    """Scène prête à rendre ; LayoutError si la mise en page est refusée (jamais rendue telle quelle)."""
    layers = scene_layers(concept, params, scene, duration, **kw)
    built = make_scene(layers, duration, cfg)
    check_layout(built, Zones.from_config((cfg or {}).get("layout")))
    return built


def render_scenes(script: dict, scenes: list[dict], work_dir: Path, cfg: dict | None = None) -> list[str]:
    """Un clip MP4 par scène (durée = voix), effets sonores calés sur l'action dans scene["sfx_cues"]."""
    pick = script.get("pick") or {}
    concept, params = pick["concept"], pick["params"]
    out = Path(work_dir) / "visuals"
    clips = []
    for scene in scenes:
        duration = float(scene.get("duration") or 4.0) + 0.25
        built = build_scene(concept, params, scene, duration, cfg, hypothesis=script.get("hypothesis", ""),
                            question=script.get("closing_cta", ""))
        scene["sfx_cues"] = tpl.cues(built.layers, duration - 0.25)
        clips.append(str(render_mp4(built, out / f"scene_{scene['id']}.mp4")))
        print(f"     🎨 Scène {scene['id']} [{scene.get('role')} / {scene.get('template', 'carte_fin')}"
              f" : {scene.get('visual', '')}] dessinée ({duration:.1f} s, {len(scene['sfx_cues'])} effet(s))")
    return clips


def lea_hugo_trees(params: dict, duration: float = 6.7, cfg: dict | None = None) -> Scene:
    """Intérêts composés, scène du résultat (preuve de l'étape B) : Hugo pousse, puis Léa le dépasse."""
    scene = {"role": "reveal", "template": "deux_arbres", "visual": "arbres"}
    return build_scene("interets_composes", params, scene, duration, cfg,
                       hypothesis=f"{fmt(params['rate'])} %/an, versement unique")
