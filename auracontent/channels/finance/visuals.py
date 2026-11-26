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
from auracontent.services.visuals.linework.engine import LINE_HEIGHT, Scene, render_mp4
from auracontent.services.visuals.linework.layout import Zones, check_layout

ASSETS = Path(__file__).resolve().parents[3] / "assets" / "finance"
ASSET_DIRS = [ASSETS / "characters", ASSETS / "props", ASSETS / "images"]
FONTS = {"hand": ASSETS / "fonts" / "Caveat.ttf", "ui": ASSETS / "fonts" / "Poppins-Bold.ttf"}
NAME, BASELINE = "Le Fric en Clair", "L'argent, sans langue de bois."
MENTION = "Contenu pédagogique, pas un conseil en investissement."
PROMISE = "Une astuce chiffrée par jour."           # carte de fin : la valeur promise, pour donner envie de suivre
SUBSCRIBE = "Abonne-toi pour la prochaine."
T, K, G = tpl.TURQUOISE, tpl.INK, tpl.GRAY      # turquoise, encre, gris
fmt = fcalc.fmt_number


def resolve(name: str) -> Path:
    for base in ASSET_DIRS:
        if (base / name).exists():
            return base / name
    raise FileNotFoundError(f"sprite finance introuvable : {name}")


# ---------- Carte de fin : la mascotte célèbre, l'abonnement est un bouton ----------
MASCOT_END = "mascotte_content.png"     # assets/finance/images : la mascotte bras levés
SUBSCRIBE_SIZE = 72                     # taille du texte du bouton (plan de conception)


QUESTION_SIZE = 84                      # question finale (plan de conception), comme tpl.end_card


def _text_height(lines: int, size: float, k: float) -> float:
    """Hauteur en pixels de sortie d'un texte de `lines` lignes (même calcul que le moteur)."""
    return (lines * size * LINE_HEIGHT + size * 0.4) / k


MASCOT_SWAY = 0.05                      # balancement de la mascotte (radians, ~3°), pieds au sol


def mascot_keys(t0: float, duration: float) -> list[dict]:
    """Animation de la mascotte de la carte de fin : elle surgit en grossissant (rebond « back »), puis se
    balance doucement de gauche à droite, pieds au sol (pivot en bas), jusqu'à la fin de la carte ; un petit
    saut de joie à chaque aller-retour. Mouvement discret : l'œil reste sur la question et le bouton."""
    keys = [{"t": t0, "alpha": 0, "scaleX": 0.5, "scaleY": 0.5, "angle": 0},
            {"t": t0 + 0.15, "alpha": 1},
            {"t": t0 + 0.45, "scaleX": 1, "scaleY": 1, "ease": "back"}]
    t, side, step = t0 + 0.45, 1, 0.55
    while t + step <= duration - 0.05:
        t += step
        keys.append({"t": round(t, 3), "angle": MASCOT_SWAY * side, "ease": "smooth"})
        if side < 0:                                     # saut de joie : écrasement puis étirement, une fois sur deux
            keys.append({"t": round(t - step / 2, 3), "scaleY": 1.04, "scaleX": 0.98, "ease": "smooth"})
            keys.append({"t": round(t, 3), "scaleY": 1, "scaleX": 1, "ease": "smooth"})
        side = -side
    return keys


def cta_layers(question: str, duration: float) -> list[dict]:
    """Carte de fin, placée d'après la hauteur RÉELLE de la question finale (jusqu'à 14 mots, soit 3 lignes :
    l'ancienne carte à hauteurs fixes faisait alors chevaucher question et abonnement, mise en page refusée) :
    - logo (230 px ; 150 px si la question tient sur 3 lignes), nom, promesse « une astuce chiffrée par jour » ;
    - la mascotte de la chaîne, bras levés, à droite du logo et du nom, au-dessus de la question ; rôle
      « character » : le contrôle de mise en page refuse un texte qui la touche ;
    - la question finale ;
    - « Abonne-toi pour la prochaine. » dans un bouton doré, encre sur or comme la punchline du bandeau.
    Mascotte absente des assets : carte sans elle (jamais d'erreur)."""
    f = tpl.Frame()
    k = f.k
    width = f.right - f.left
    lines = tpl.lines_of(question, QUESTION_SIZE, width) if question else 0
    logo = 230 if lines <= 2 else 150
    cx = (f.left + f.right) / 2
    y = f.top + 20
    layers: list[dict] = [{"type": "image", "role": "prop", "id": "logo", "path": "capital_simple_watermark.png",
                           "x": (cx - logo / 2) * k, "y": y * k, "w": logo * k, "h": logo * k,
                           "pivotX": logo / 2 * k, "pivotY": logo / 2 * k, "sfx": tpl._sfx(0.15, "pop.wav", 0.3),
                           "keys": [{"t": 0.15, "alpha": 0, "scaleX": 0.6, "scaleY": 0.6},
                                    {"t": 0.55, "alpha": 1, "scaleX": 1, "scaleY": 1}],
                           "motion": "le logo apparaît"}]
    y += logo + 20
    layers.append(tpl.text("nom", NAME, f.left, y, 84, f, font="ui", start=0.5, w_px=width))
    y += 95
    layers.append(tpl.text("baseline", PROMISE, f.left, y, 60, f, color=tpl.TURQUOISE, start=0.7, w_px=width))
    y += 90
    question_top = y
    if question:
        layers.append(tpl.text("question", question, f.left, y, QUESTION_SIZE, f, role="value", start=1.0,
                               w_px=width, sfx=tpl._sfx(1.0, "paper.wav", 0.3)))
        y += _text_height(lines, QUESTION_SIZE, k) + 16
    # Mascotte : bas posé 14 px au-dessus de la question, à droite du logo (x 690..920, le logo s'arrête à 612)
    path = ASSETS / "images" / MASCOT_END
    if path.exists():
        from PIL import Image
        with Image.open(path) as im:
            ratio = im.height / im.width
        mh = min(271.0, question_top - 14 - (f.top + 20))
        mw = mh / ratio
        mx, my = 905 - mw, question_top - 14 - mh       # 25 px de marge : le balancement reste avant x = 930
        layers.append({"type": "image", "role": "character", "id": "mascotte", "path": MASCOT_END,
                       "x": mx * k, "y": my * k, "w": mw * k, "pivotX": mw / 2 * k, "pivotY": mh * k,
                       "from": 0.6, "keys": mascot_keys(0.6, duration),
                       "sfx": tpl._sfx(0.65, "pop.wav", 0.3), "motion": "la mascotte lève les bras"})
    # Bouton d'abonnement sous la question ; texte réduit s'il ne tient pas au-dessus des sous-titres
    size = SUBSCRIBE_SIZE
    while size > 52 and y + 12 + _text_height(1, size, k) > f.bottom:
        size -= 4
    tw = tpl.text_width(SUBSCRIBE, size, f.width)
    pad_x, pad_y = 30, 12
    th = size / k * 1.25
    bw = min(width, tw + 2 * pad_x)
    layers.append({"type": "box", "role": "decor", "id": "bouton", "x": f.left * k, "y": y * k,
                   "w": bw * k, "h": (th + 2 * pad_y) * k, "fill": tpl.GOLD, "outline": tpl.INK, "lineWidth": 4,
                   "from": 1.3, "keys": [{"t": 1.3, "alpha": 0}, {"t": 1.5, "alpha": 1}]})
    layers.append(tpl.text("abonne", SUBSCRIBE, f.left + pad_x, y + pad_y, size, f, color=tpl.INK, start=1.4,
                           w_px=bw - pad_x, sfx=tpl._sfx(1.4, "pop.wav", 0.3)))
    return layers


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


# ---------- Concepts du quotidien (partie 3) : une table par concept, scènes génériques ----------
# two   : (clé ou "param:nom", libellé) x 2 -> deux montants (piles de pièces), Léa et Hugo réagissent ;
#         bad = True : le plus grand montant est la mauvaise nouvelle (Hugo sursaute devant, Léa sourit à côté)
# bars  : jusqu'à 3 (clé, libellé, couleur) ; curve : (libellé a, clé de sa valeur finale, libellé b ou None,
#         clé de b ou None (légende sans valeur), clé de l'écart ou None, (x début, x fin), unité de l'axe) :
#         les valeurs écrites viennent de calc.py, jamais de la série (98 000 €, pas 97 997 €) ;
#         cast : (pose de départ, réaction, annotation, note)
# Les libellés sont des modèles remplis avec les paramètres du sujet ({years}, {days}...).
GENERIC: dict[str, dict] = {
    "depenses_repetees": {
        "two": (("over_years", "en {years} ans"), ("per_year", "en 1 an")), "bad": True,
        "bars": [("per_week_total", "par semaine", G), ("per_year", "par an", K), ("over_years", "en {years} ans", T)],
        "curve": ("total dépensé", "over_years", None, None, None, ("0", "{years} ans"), "€"),
        "cast": ("lea-neutral.png", "lea-surprise.png", "{amount_eur} \u00d7 {per_week}", "par semaine")},
    "abonnements": {
        "two": (("total_year", "par an"), ("total_month", "par mois")), "bad": True,
        "bars": [("total_month", "par mois", G), ("total_year", "par an", K), ("over_years", "en {years} ans", T)],
        "curve": ("total payé", "over_years", None, None, None, ("0", "{years} ans"), "€"),
        "cast": ("hugo-neutral.png", "hugo-shock.png", "{count} abonnements", "{total_month_eur} par mois")},
    "remises_successives": {
        "two": (("final_price", "prix payé"), ("naive_price", "prix qu'on croit")), "bad": True,
        "bars": [("naive_pct", "remise crue", K), ("total_pct", "remise réelle", T)],
        "curve": ("prix payé", "final_price", None, None, None, ("départ", "2 remises"), "€"),
        "cast": ("lea-neutral.png", "lea-shrug.png", "\u2212{first} % puis \u2212{second} %", "ça fait \u2212{naive_pct} % ?")},
    "paiement_fractionne": {
        "two": (("total_paid", "total payé"), ("param:price", "prix affiché")), "bad": True,
        "bars": [("param:price", "prix", G), ("total_paid", "payé", K), ("extra_cost", "frais", T)],
        "curve": ("total payé", "total_paid", None, None, None, ("1er paiement", "dernier"), "€"),
        "cast": ("hugo-neutral.png", "hugo-smug.png", "{price_eur} en {installments} fois", "et les frais ?")},
    "credit_amortissable": {
        "two": (("total_paid", "remboursé"), ("param:amount", "emprunté")), "bad": True,
        "bars": [("param:amount", "emprunté", G), ("interest", "intérêts", K), ("total_paid", "remboursé", T)],
        "curve": ("total remboursé", "total_paid", "reste à rembourser", None, None, ("0", "{years} ans"), "€"),
        "cast": ("hugo-neutral.png", "hugo-shock.png", "{amount_eur} sur {years} ans", "à {rate} % par an")},
    "decouvert_agios": {
        "two": (("agios_year", "sur 1 an"), ("agios", "en {days} jours")), "bad": True,
        "bars": [("per_day", "par jour", G), ("agios", "{days} jours", K), ("agios_year", "sur 1 an", T)],
        "curve": ("agios", "agios", None, None, None, ("0", "{days} jours"), "€"),
        "cast": ("lea-neutral.png", "lea-surprise.png", "\u2212{overdraft_eur}", "pendant {days} jours")},
    "forfait_appareil": {                    # surcoût OU économie : « {diff} » et le rôle des piles suivent calc.py
        # deux coûts pour le même appareil : le plus élevé est toujours la mauvaise nouvelle
        "two": (("real_price", "via le forfait"), ("param:phone_price", "comptant")), "bad": True,
        "bars": [("param:phone_price", "comptant", G), ("real_price", "via le forfait", K), ("difference", "{diff}", T)],
        "curve": ("payé pour l'appareil", "real_price", "prix comptant", "param:phone_price", "difference",
                  ("0", "{months} mois"), "€"),
        "cast": ("hugo-neutral.png", "hugo-smug.png", "téléphone à {upfront_eur}", "+{extra_monthly_eur} par mois")},
    "carte_fidelite": {
        "two": (("param:pct", "remise immédiate"), ("effective_pct", "bon d'achat")), "bad": False,
        "bars": [("param:pct", "remise immédiate", T), ("effective_pct", "bon d'achat", K)],
        "curve": ("remise immédiate", "voucher", "bon d'achat", None, None, ("0 €", "{spend_eur}"), "€"),
        "cast": ("lea-neutral.png", "lea-shrug.png", "{pct} % offerts", "en bon d'achat")},
    "epargne_age": {
        "two": (("final_a", "dès {age_a} ans"), ("final_b", "dès {age_b} ans")), "bad": False,
        "bars": [("paid_a", "versé", G), ("final_a", "dès {age_a} ans", T), ("final_b", "dès {age_b} ans", K)],
        "curve": ("dès {age_a} ans", "final_a", "dès {age_b} ans", "final_b", "gap", ("{age_a} ans", "{end_age} ans"), "€"),
        "cast": ("lea-neutral.png", "lea-joy.png", "{monthly_eur} par mois", "dès {age_a} ou {age_b} ans ?")},
    "salaire_vs_prix": {
        "two": (("new_salary", "sur la fiche de paie"), ("real_salary", "ce qu'il achète")), "bad": False,
        "bars": [("param:salary", "avant", G), ("new_salary", "après", K), ("real_salary", "ce qu'il achète", T)],
        "curve": ("augmentation par mois", "raise_eur", "hausse des prix par mois", "basket_rise_eur", None,
                  ("aujourd'hui", "dans 1 an"), "€"),
        "cast": ("hugo-neutral.png", "hugo-smug.png", "+{raise_pct} % de salaire", "+{inflation} % de prix")},
    "taux_reel": {
        "two": (("nominal_gain", "intérêts"), ("real_gain", "gain réel")), "bad": False,
        "bars": [("param:nominal", "taux affiché", K), ("param:inflation", "inflation", G), ("real_exact", "taux réel", T)],
        "curve": ("intérêts", "nominal_gain", "gain réel", "real_gain", None, ("0", "12 mois"), "€"),
        "cast": ("lea-neutral.png", "lea-shrug.png", "{nominal} % \u2212 {inflation} %", "= {real_approx} % ?")},
    "leasing_epargne": {
        "two": (("saving_final", "mis de côté"), ("leasing_paid", "loyers payés")), "bad": False,
        "bars": [("leasing_paid", "loyers payés", K), ("leasing_left", "reste du leasing", G), ("saving_final", "mis de côté", T)],
        "curve": ("mis de côté", "saving_final", "loyers payés", "leasing_paid", None, ("0", "{years} ans"), "€"),
        "cast": ("hugo-neutral.png", "hugo-smug.png", "{monthly_eur} par mois", "pendant {years} ans")},
}


def _fields(p: dict, c: fcalc.Calc) -> dict:
    """Valeurs des modèles de libellés : paramètres (« {years} », « {price_eur} » = « 400 € ») et résultats."""
    spec = fcalc.SPECS.get(c.concept, {}).get("params", {})
    out = {k: fmt(v) for k, v in p.items() if isinstance(v, (int, float))}
    out.update({f"{k}_eur": fcalc.money_text(v) for k, v in p.items()
                if isinstance(v, (int, float)) and spec.get(k, ("", ""))[1] == "€"})
    for key, v in c.values.items():
        out.setdefault(key, fmt(v.value))
        out[f"{key}_eur"] = v.text
    if "difference" in c.values:                            # « surcoût » ou « économie », d'après calc.py
        out["diff"] = c.values["difference"].label.split()[0]
    return out


def _g_item(c: fcalc.Calc, p: dict, ref: str, label: str, color: str = T) -> tpl.Item:
    """Item d'un résultat de calc.py, ou d'un paramètre (« param:price »), avec son libellé rempli."""
    label = label.format(**_fields(p, c))
    if ref.startswith("param:"):
        name = ref.split(":", 1)[1]
        unit = fcalc.SPECS[c.concept]["params"][name][1]
        value = fcalc.Value(name, label, float(p[name]), unit)
        return tpl.Item(label, value.value, value.text, color, ("{n} " + unit).strip() if unit else "{n}")
    return _item(c, ref, label, color)


def _g_two(concept, p, c):
    g = GENERIC[concept]
    (ka, la), (kb, lb) = g["two"]
    a, b = _g_item(c, p, ka, la), _g_item(c, p, kb, lb)
    big, small = (a, b) if a.value >= b.value else (b, a)
    bad = g.get("bad")
    if isinstance(bad, str):                                # clé de calc.py : surcoût = mauvaise nouvelle
        bad = c.values[bad].label.startswith("surcoût")
    good_big = not bad
    big_side = tpl.Side(big.label, big.value, big.text, color=T if good_big else K,
                        react="lea-joy.png" if good_big else "hugo-shock.png", count_template=big.count_template)
    small_side = tpl.Side(small.label, small.value, small.text, color=K if good_big else T,
                          idle="hugo-neutral.png" if good_big else "lea-neutral.png",
                          react="hugo-shock.png" if good_big else "lea-joy.png", count_template=small.count_template)
    return big_side, small_side, ""


def _g_curve(concept, p, c):
    g = GENERIC[concept]
    la, ka, lb, kb, gap_key, (xa, xb), unit = g["curve"]
    f = _fields(p, c)

    def end(label, key, color):
        if key is None:                                   # légende sans valeur : aucun chiffre hors de calc.py
            return tpl.Item(label.format(**f), 0, "", color, "")
        return _g_item(c, p, key, label, color)

    a = end(la, ka, T)
    b = end(lb, kb, K) if lb and c.series.get("b") else None
    # légende courte (une ligne) : « économie » / « surcoût » pour le forfait, « écart » sinon
    gap = _item(c, gap_key, f.get("diff", "écart") if gap_key == "difference" else "écart", K) if gap_key else None
    return a, b, gap, (xa.format(**f), xb.format(**f)), unit


def _g_bars(concept, p, c):
    return [_g_item(c, p, ref, label, color) for ref, label, color in GENERIC[concept]["bars"]]


def _g_cast(concept, p, c):
    pose, then, annotation, note = GENERIC[concept]["cast"]
    f = _fields(p, c)
    return [{"pose": pose, "then": then, "x": 420}], annotation.format(**f), note.format(**f)


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
        return steps, _item(c, "lea_years", "de croissance pour Léa", T), "lea-neutral.png"
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
    if concept == "inflation":
        return ([{"pose": "lea-neutral.png", "then": "lea-surprise.png", "x": 420,
                  "motion": "Léa découvre que son argent achète moins"}],
                f"{fmt(p['amount'])} € qui dorment", f"pendant {p['years']} ans")
    return [{"pose": "lea-neutral.png", "then": "lea-surprise.png", "x": 420}], "", ""


# ---------- Scène ----------
def scene_layers(concept: str, params: dict, scene: dict, duration: float, *, hypothesis: str = "",
                 question: str = "") -> list[dict]:
    """Calques d'une scène du script (rôle, gabarit, variante) d'après calc.py."""
    c = fcalc.compute(concept, params)
    role, template, variant = scene.get("role"), scene.get("template"), scene.get("visual")
    if concept in GENERIC and template in ("deux_arbres", "deux_courbes", "barres", "personnages"):
        return _generic_layers(concept, params, c, template, variant, duration, hypothesis)
    if role == "cta":
        return cta_layers(question, duration)
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


def _generic_layers(concept, params, c, template, variant, duration, hypothesis) -> list[dict]:
    """Scènes génériques d'un concept du quotidien : deux montants (piles), barres et courbe avec Léa ou Hugo,
    graduations sur l'axe vertical, personnages avec annotation."""
    if template == "deux_arbres":
        win, lose, _ = _g_two(concept, params, c)
        return tpl.two_amounts(win, lose, resolve=resolve, subtitle=hypothesis, duration=duration, variant="piles")
    if template == "deux_courbes":
        a, b, gap, xl, unit = _g_curve(concept, params, c)
        return tpl.curve_in_time(c.series, a, b, x_labels=xl, subtitle=hypothesis, gap=gap, duration=duration,
                                 variant="ecart" if variant == "ecart" and gap is not None and b is not None
                                 else "courbes", y_ticks=True, y_unit=unit, companion="hugo-point.png",
                                 resolve=resolve)
    if template == "barres":
        return tpl.bars(_g_bars(concept, params, c), subtitle=hypothesis, duration=duration,
                        companion="lea-point.png", resolve=resolve)
    cast, annotation, note = _g_cast(concept, params, c)
    return tpl.characters(cast, resolve=resolve, annotation=annotation, note=note, duration=duration)


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
