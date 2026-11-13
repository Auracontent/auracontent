"""Calculs de la chaîne finance « Capital Simple ».

Seule source des chiffres d'une vidéo : le LLM choisit un concept et des paramètres, ce module calcule les
résultats, et la validation du script rejette tout nombre qui n'est ni une donnée d'entrée ni un résultat
d'ici. Fonctions pures, sans I/O ; chaque résultat est arrondi UNE fois, à la forme sous laquelle il est dit
à voix haute (les montants à la dizaine ou à la centaine), pour que le texte et l'écran citent la même valeur.
Les écarts sont calculés sur les valeurs arrondies : « 2 100 € moins 1 630 € » donne 470 €, jamais 472 €.

Conventions (rappelées par l'hypothèse affichée) : intérêts capitalisés une fois par an, versements mensuels
en fin de mois au taux mensuel équivalent, frais prélevés chaque année sur le total, avant impôts et avant
inflation (sauf le concept inflation lui-même).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Value:
    key: str
    label: str           # libellé donné au LLM et aux gabarits
    value: float         # déjà arrondi : c'est la valeur citée
    unit: str            # "€", "%", "ans", "fois"

    @property
    def text(self) -> str:
        return f"{fmt_number(self.value)} {self.unit}".strip()


@dataclass
class Calc:
    concept: str
    values: dict[str, Value]
    headline: str                                   # clé du résultat principal, à dire dans la vidéo
    series: dict[str, list] = field(default_factory=dict)   # courbes annuelles pour les gabarits
    extra_numbers: tuple[float, ...] = ()           # nombres de référence citables (ex. « 100 € »)

    def __getitem__(self, key: str) -> float:
        return self.values[key].value

    @property
    def main(self) -> Value:
        return self.values[self.headline]

    def numbers(self) -> set[float]:
        return {v.value for v in self.values.values()} | {float(n) for n in self.extra_numbers}

    def to_dict(self) -> dict:
        return {"concept": self.concept, "headline": self.headline,
                "values": {k: {"label": v.label, "value": v.value, "unit": v.unit, "text": v.text}
                           for k, v in self.values.items()},
                "series": self.series, "extra_numbers": list(self.extra_numbers)}


# ---------- Arrondis et format ----------
def round_money(x: float) -> float:
    """Montant tel qu'on le dit : à l'euro sous 1 000, à la dizaine sous 10 000, à la centaine au-delà."""
    step = 1 if abs(x) < 1000 else 10 if abs(x) < 10_000 else 100
    return float(round(x / step) * step)


def round_pct(x: float) -> float:
    return float(round(x))


def round_1(x: float) -> float:
    return float(round(x, 1))


def fmt_number(x: float) -> str:
    """Format français : « 16 040 », « 0,5 », « 6,1 » (espace des milliers, virgule décimale)."""
    if float(x).is_integer():
        return f"{int(x):,}".replace(",", " ")
    return f"{x:g}".replace(".", ",")


# ---------- Formules ----------
def grow(amount: float, rate_pct: float, years: float) -> float:
    """Versement unique, intérêts capitalisés chaque année."""
    return amount * (1 + rate_pct / 100) ** years


def monthly_rate(rate_pct: float) -> float:
    """Taux mensuel équivalent à rate_pct par an (12 mois composés = le taux annuel)."""
    return (1 + rate_pct / 100) ** (1 / 12) - 1


def grow_monthly(monthly: float, rate_pct: float, months: int) -> float:
    """Valeur finale de versements mensuels en fin de mois."""
    if months <= 0:
        return 0.0
    rm = monthly_rate(rate_pct)
    return monthly * months if rm == 0 else monthly * ((1 + rm) ** months - 1) / rm


def _v(key: str, label: str, value: float, unit: str) -> Value:
    return Value(key, label, value, unit)


# ---------- Concepts ----------
def interets_composes(p: dict) -> Calc:
    lea_years, hugo_years = p["end_age"] - p["early_age"], p["end_age"] - p["late_age"]
    lea, hugo = grow(p["early_amount"], p["rate"], lea_years), grow(p["late_amount"], p["rate"], hugo_years)
    lea_r, hugo_r = round_money(lea), round_money(hugo)
    values = [
        _v("lea_years", "durée de placement de Léa", lea_years, "ans"),
        _v("hugo_years", "durée de placement de Hugo", hugo_years, "ans"),
        _v("lea_final", f"Léa à {p['end_age']} ans", lea_r, "€"),
        _v("hugo_final", f"Hugo à {p['end_age']} ans", hugo_r, "€"),
        _v("gap", "écart en faveur de Léa", lea_r - hugo_r, "€"),
        # sans unité : on écrit « multipliée par 24 », jamais « multipliée par 24 fois »
        _v("lea_multiple", "la mise de Léa est multipliée par", round_1(lea / p["early_amount"]), ""),
        _v("hugo_multiple", "la mise de Hugo est multipliée par", round_1(hugo / p["late_amount"]), ""),
    ]
    ages = list(range(p["early_age"], p["end_age"] + 1))
    series = {"x": ages, "x_label": "âge",
              "a": [round(grow(p["early_amount"], p["rate"], a - p["early_age"])) for a in ages],
              "b": [round(grow(p["late_amount"], p["rate"], a - p["late_age"])) if a >= p["late_age"] else None
                    for a in ages],
              "a_label": "Léa", "b_label": "Hugo"}
    return Calc("interets_composes", {v.key: v for v in values}, "lea_final", series)


def inflation(p: dict) -> Calc:
    factor = (1 + p["inflation"] / 100) ** p["years"]
    real = round_money(p["amount"] / factor)
    values = [
        _v("real_value", f"pouvoir d'achat de {fmt_number(p['amount'])} € après {p['years']} ans", real, "€"),
        _v("lost", "pouvoir d'achat perdu", p["amount"] - real, "€"),
        _v("lost_pct", "part du pouvoir d'achat perdue", round_pct((1 - 1 / factor) * 100), "%"),
        _v("price_of_100", f"ce qui coûte 100 € aujourd'hui coûtera, dans {p['years']} ans", round_money(100 * factor), "€"),
    ]
    years = list(range(p["years"] + 1))
    series = {"x": years, "x_label": "années",
              "a": [p["amount"]] * len(years),
              "b": [round(p["amount"] / (1 + p["inflation"] / 100) ** y) for y in years],
              "a_label": "sur le compte", "b_label": "ce que ça achète"}
    return Calc("inflation", {v.key: v for v in values}, "real_value", series, extra_numbers=(100,))


def cout_du_temps(p: dict) -> Calc:
    late_years = p["horizon_years"] - p["delay_years"]
    now = grow_monthly(p["monthly"], p["rate"], p["horizon_years"] * 12)
    late = grow_monthly(p["monthly"], p["rate"], late_years * 12)
    now_r, late_r = round_money(now), round_money(late)
    values = [
        _v("late_years", "durée des versements si on attend", late_years, "ans"),
        _v("final_now", "résultat en commençant tout de suite", now_r, "€"),
        _v("final_late", f"résultat en commençant {p['delay_years']} ans plus tard", late_r, "€"),
        _v("cost", "coût de l'attente", now_r - late_r, "€"),
        _v("cost_pct", "part du résultat perdue en attendant", round_pct((now - late) / now * 100), "%"),
        _v("paid_now", "total versé en commençant tout de suite", round_money(p["monthly"] * 12 * p["horizon_years"]), "€"),
        _v("paid_late", "total versé en attendant", round_money(p["monthly"] * 12 * late_years), "€"),
        _v("paid_gap", "versements en plus quand on commence tout de suite",
           round_money(p["monthly"] * 12 * p["delay_years"]), "€"),
    ]
    years = list(range(p["horizon_years"] + 1))
    series = {"x": years, "x_label": "années",
              "a": [round(grow_monthly(p["monthly"], p["rate"], y * 12)) for y in years],
              "b": [round(grow_monthly(p["monthly"], p["rate"], (y - p["delay_years"]) * 12)) for y in years],
              "a_label": "tout de suite", "b_label": f"{p['delay_years']} ans plus tard"}
    return Calc("cout_du_temps", {v.key: v for v in values}, "cost", series)


def frais(p: dict) -> Calc:
    net = (1 + p["rate"] / 100) * (1 - p["fees"] / 100)     # frais prélevés chaque année sur le total
    without = grow(p["amount"], p["rate"], p["years"])
    with_fees = p["amount"] * net ** p["years"]
    lost = without - with_fees
    without_r, with_r = round_money(without), round_money(with_fees)
    values = [
        _v("final_without", "résultat sans frais", without_r, "€"),
        _v("final_with", f"résultat avec {fmt_number(p['fees'])} % de frais par an", with_r, "€"),
        _v("lost", "coût total des frais", without_r - with_r, "€"),
        _v("lost_pct_gains", "part des gains mangée par les frais", round_pct(lost / (without - p["amount"]) * 100), "%"),
        _v("lost_pct_final", "part du résultat final mangée par les frais", round_pct(lost / without * 100), "%"),
    ]
    years = list(range(p["years"] + 1))
    series = {"x": years, "x_label": "années",
              "a": [round(grow(p["amount"], p["rate"], y)) for y in years],
              "b": [round(p["amount"] * net ** y) for y in years],
              "a_label": "sans frais", "b_label": "avec frais"}
    return Calc("frais", {v.key: v for v in values}, "lost", series)


def regle_72(p: dict) -> Calc:
    """Deux exemples : `rate` (le premier) et `rate_b` (le second, plus élevé)."""
    def double(rate):
        return round_1(72 / rate), round_1(math.log(2) / math.log(1 + rate / 100))

    rule, exact = double(p["rate"])
    rule_b, exact_b = double(p["rate_b"])
    values = [
        _v("years_rule", f"72 divisé par {fmt_number(p['rate'])} (temps pour doubler à {fmt_number(p['rate'])} %)",
           rule, "ans"),
        _v("years_exact", f"durée exacte pour doubler à {fmt_number(p['rate'])} %", exact, "ans"),
        _v("years_rule_b", f"72 divisé par {fmt_number(p['rate_b'])} (temps pour doubler à "
           f"{fmt_number(p['rate_b'])} %)", rule_b, "ans"),
        _v("years_exact_b", f"durée exacte pour doubler à {fmt_number(p['rate_b'])} %", exact_b, "ans"),
    ]
    n = math.ceil(exact)
    series = {"x": list(range(n + 1)), "x_label": "années",
              "a": [round(grow(100, p["rate"], y)) for y in range(n + 1)],
              "b": [round(grow(100, p["rate_b"], y)) for y in range(n + 1)],
              "a_label": f"{fmt_number(p['rate'])} %/an", "b_label": f"{fmt_number(p['rate_b'])} %/an"}
    return Calc("regle_72", {v.key: v for v in values}, "years_rule", series, extra_numbers=(72, 2))


CONCEPTS = {"interets_composes": interets_composes, "inflation": inflation, "cout_du_temps": cout_du_temps,
            "frais": frais, "regle_72": regle_72}


def compute(concept: str, params: dict) -> Calc:
    try:
        fn = CONCEPTS[concept]
    except KeyError:
        raise KeyError(f"Concept sans calcul : {concept}") from None
    return fn(params)
