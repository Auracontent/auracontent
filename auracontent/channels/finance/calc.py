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
import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class Value:
    key: str
    label: str           # libellé donné au LLM et aux gabarits
    value: float         # déjà arrondi : c'est la valeur citée
    unit: str            # "€", "%", "ans", "fois"

    @property
    def text(self) -> str:
        if self.unit == "€" and not float(self.value).is_integer():      # centimes : « 2,50 € »
            return f"{fmt_number(int(self.value))},{round(abs(self.value) * 100) % 100:02d} €"
        return f"{fmt_number(self.value)} {self.unit}".strip()


@dataclass
class Calc:
    concept: str
    values: dict[str, Value]
    headline: str                                   # clé du résultat principal, à dire dans la vidéo
    series: dict[str, list] = field(default_factory=dict)   # courbes annuelles pour les gabarits
    extra_numbers: tuple[float, ...] = ()           # nombres de référence citables (ex. « 100 € »)
    compare: tuple[str, str] | None = None          # deux résultats à comparer (barres, deux montants)

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
                "series": self.series, "extra_numbers": list(self.extra_numbers),
                "compare": list(self.compare) if self.compare else None}


# ---------- Arrondis et format ----------
def _half_up(x: float, digits: int = 0) -> float:
    """Arrondi commercial (0,5 vers le haut en valeur absolue), sans les surprises du flottant (1,005)."""
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP)) + 0.0


def round_money(x: float) -> float:
    """Règle unique des montants (écran et voix) : arrondi à l'euro (1 768 €, jamais 1 770 € sans « environ »).
    Les montants sous 100 € gardent leurs centimes (round_price)."""
    return _half_up(x)


def round_pct(x: float) -> float:
    return float(round(x))


def round_1(x: float) -> float:
    return float(round(x, 1)) + 0.0          # + 0.0 : jamais « -0 »


def round_price(x: float) -> float:
    """Petit montant au centime (« 4,93 € », « 2,50 € ») sous 100 € ; au-delà, comme round_money."""
    return _half_up(x, 2) if abs(x) < 100 else round_money(x)


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
        _v("lea_years", "années de croissance de l'argent de Léa", lea_years, "ans"),
        _v("hugo_years", "années de croissance de l'argent de Hugo", hugo_years, "ans"),
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
        _v("years_saved", f"années gagnées en passant de {fmt_number(p['rate'])} % à {fmt_number(p['rate_b'])} %",
           round_1(rule - rule_b), "ans"),
    ]
    n = math.ceil(exact)
    series = {"x": list(range(n + 1)), "x_label": "années",
              "a": [round(grow(100, p["rate"], y)) for y in range(n + 1)],
              "b": [round(grow(100, p["rate_b"], y)) for y in range(n + 1)],
              "a_label": f"{fmt_number(p['rate'])} %/an", "b_label": f"{fmt_number(p['rate_b'])} %/an"}
    return Calc("regle_72", {v.key: v for v in values}, "years_rule", series, extra_numbers=(72, 2))


# ---------- Concepts du quotidien (partie 3a) ----------
def _years_series(years: int, a, b=None, a_label="", b_label="") -> dict:
    xs = list(range(years + 1))
    out = {"x": xs, "x_label": "années", "a": [a(y) for y in xs], "a_label": a_label}
    if b is not None:
        out.update(b=[b(y) for y in xs], b_label=b_label)
    return out


def depenses_repetees(p: dict) -> Calc:
    """Petite dépense répétée : `amount` € `per_week` fois par semaine (52 semaines), sur 1 an et `years` ans."""
    year = p["amount"] * p["per_week"] * 52
    values = [
        _v("per_week_total", "dépense par semaine", round_price(p["amount"] * p["per_week"]), "€"),
        _v("per_month", "dépense par mois (en moyenne)", round_price(year / 12), "€"),
        _v("per_year", "dépense sur un an", round_money(year), "€"),
        _v("over_years", f"dépense sur {p['years']} ans", round_money(year * p["years"]), "€"),
    ]
    series = _years_series(p["years"], lambda y: round(year * y), a_label="total dépensé")
    return Calc("depenses_repetees", {v.key: v for v in values}, "over_years", series, extra_numbers=(52, 12),
                compare=("per_year", "over_years"))


def abonnements(p: dict) -> Calc:
    """Abonnements cumulés : `sub_1` à `sub_4` € par mois (0 = absent), sur un an et `years` ans."""
    subs = [p[k] for k in ("sub_1", "sub_2", "sub_3", "sub_4") if p.get(k)]
    month = sum(subs)
    values = [
        _v("count", "nombre d'abonnements", len(subs), ""),
        _v("total_month", "total par mois", round_price(month), "€"),
        _v("total_year", "total par an", round_money(month * 12), "€"),
        _v("over_years", f"total sur {p['years']} ans", round_money(month * 12 * p["years"]), "€"),
    ]
    series = _years_series(p["years"], lambda y: round(month * 12 * y), a_label="total payé")
    return Calc("abonnements", {v.key: v for v in values}, "total_year", series, extra_numbers=(12,),
                compare=("total_month", "total_year"))


def remises_successives(p: dict) -> Calc:
    """`first` % puis `second` % de remise sur `price` € : la remise totale n'est pas la somme des deux."""
    after_first = p["price"] * (1 - p["first"] / 100)
    final = after_first * (1 - p["second"] / 100)
    naive = p["first"] + p["second"]
    values = [
        _v("after_first", f"prix après {fmt_number(p['first'])} %", round_price(after_first), "€"),
        _v("final_price", "prix final", round_price(final), "€"),
        _v("total_pct", "remise totale réelle", round_1((1 - final / p["price"]) * 100), "%"),
        _v("naive_pct", "remise qu'on croit avoir (la somme)", naive, "%"),
        _v("naive_price", "prix si les remises s'additionnaient", round_price(p["price"] * (1 - naive / 100)), "€"),
    ]
    values.append(_v("gap_eur", "écart avec le prix qu'on croit payer",
                     round_price(values[1].value - values[4].value), "€"))
    series = {"x": [0, 1, 2], "x_label": "étapes", "a": [p["price"], round(after_first, 2), round(final, 2)],
              "a_label": "prix payé"}
    return Calc("remises_successives", {v.key: v for v in values}, "total_pct", series, extra_numbers=(100,),
                compare=("naive_price", "final_price"))


def _monthly_irr(price: float, payments: list[float]) -> float:
    """Taux mensuel r tel que price = somme des paiements actualisés (le premier payé tout de suite)."""
    def npv(r):
        return sum(pay / (1 + r) ** k for k, pay in enumerate(payments)) - price

    if npv(0.0) <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
    return (lo + hi) / 2


def paiement_fractionne(p: dict) -> Calc:
    """Achat de `price` € en `installments` fois, frais du service de `fee_pct` % du prix et `late_fee` € de frais
    pour un retard (0 = aucun retard), ajoutés au dernier paiement.

    Convention du taux annuel équivalent (fixée) : le bien vaut `price` le jour de l'achat ; le 1er paiement
    est fait ce jour-là (mois 0), les suivants tous les mois (mois 1, 2...). Le taux mensuel r égalise la valeur
    actuelle des paiements et le prix ; le taux annuel est COMPOSÉ : (1 + r)^12 - 1 (comme un TAEG). Le script
    cite d'abord le coût en euros ; le taux n'apparaît que s'il est expliqué (EXPLAIN)."""
    total = p["price"] * (1 + p["fee_pct"] / 100) + p["late_fee"]
    base = p["price"] * (1 + p["fee_pct"] / 100) / p["installments"]
    payments = [base] * p["installments"]
    payments[-1] += p["late_fee"]
    rate = ((1 + _monthly_irr(p["price"], payments)) ** 12 - 1) * 100
    values = [
        # au centime : 4 x 102,20 € = 408,80 €, sans écart d'arrondi entre le détail et le total
        _v("installment", "montant de chaque paiement", round(base, 2) + 0.0, "€"),
        _v("total_paid", "total payé", round(total, 2) + 0.0, "€"),
        _v("extra_cost", "coût du paiement en plusieurs fois", round(total - p["price"], 2) + 0.0, "€"),
        _v("extra_pct", "surcoût par rapport au prix", round_1((total / p["price"] - 1) * 100), "%"),
        _v("annual_rate", "taux annuel équivalent (comme un crédit)", round_1(rate), "%"),
    ]
    series = {"x": list(range(p["installments"])), "x_label": "mois",
              "a": [round(sum(payments[:k + 1]), 2) for k in range(p["installments"])], "a_label": "total payé"}
    return Calc("paiement_fractionne", {v.key: v for v in values}, "extra_cost", series,
                compare=("total_paid", "extra_cost"))


def credit_amortissable(p: dict) -> Calc:
    """Crédit de `amount` € à `rate` %/an (taux mensuel = taux annuel / 12) sur `years` ans, mensualités fixes."""
    n, r = p["years"] * 12, p["rate"] / 1200
    monthly = p["amount"] / n if r == 0 else p["amount"] * r / (1 - (1 + r) ** -n)
    total = round_money(monthly * n)
    remaining = [p["amount"] * ((1 + r) ** n - (1 + r) ** (12 * y)) / ((1 + r) ** n - 1) if r else
                 p["amount"] * (1 - y / p["years"]) for y in range(p["years"] + 1)]
    values = [
        _v("monthly", "mensualité", round_price(monthly), "€"),
        _v("months", "nombre de mensualités", n, ""),
        _v("total_paid", "total remboursé", total, "€"),
        _v("interest", "coût total des intérêts", total - p["amount"], "€"),
        _v("interest_pct", "intérêts en part du montant emprunté", round_pct((total - p["amount"]) / p["amount"] * 100), "%"),
    ]
    series = {"x": list(range(p["years"] + 1)), "x_label": "années",
              "a": [round(monthly * 12 * y) for y in range(p["years"] + 1)], "a_label": "total remboursé",
              "b": [round(v) for v in remaining], "b_label": "reste à rembourser"}
    return Calc("credit_amortissable", {v.key: v for v in values}, "interest", series, extra_numbers=(12,),
                compare=("total_paid", "interest"))


def decouvert_agios(p: dict) -> Calc:
    """Découvert de `overdraft` € pendant `days` jours à `rate` %/an : agios = montant x taux x jours / 365."""
    agios = p["overdraft"] * p["rate"] / 100 * p["days"] / 365
    values = [
        _v("agios", f"agios pour {p['days']} jours", round_price(agios), "€"),
        _v("agios_year", "agios si ça se répète chaque mois pendant un an", round_price(agios * 12), "€"),
        _v("per_day", "agios par jour de découvert", round_price(agios / p["days"]), "€"),
    ]
    series = {"x": list(range(p["days"] + 1)), "x_label": "jours",
              "a": [round(agios * d / p["days"], 2) for d in range(p["days"] + 1)], "a_label": "agios"}
    return Calc("decouvert_agios", {v.key: v for v in values}, "agios", series, extra_numbers=(365, 12),
                compare=("agios", "agios_year"))


def forfait_appareil(p: dict) -> Calc:
    """Option A : appareil à `upfront` € + forfait AVEC appareil à `monthly_with` €/mois pendant `months` mois.
    Option B : appareil acheté `phone_price` € comptant + le MÊME service sans appareil à `monthly_without` €/mois.
    Le service est payé des deux côtés : il se compense. Coût réel de l'appareil via le forfait =
    apport + (forfait avec - forfait sans) x durée, comparé au prix comptant. Le résultat est un surcoût OU une
    économie (clé « difference », libellé selon le signe) : la vidéo suit le vrai résultat."""
    extra = p["monthly_with"] - p["monthly_without"]
    real = round_price(p["upfront"] + extra * p["months"])
    gap = round_price(real - p["phone_price"])
    word = "surcoût" if gap > 0 else "économie"
    values = [
        _v("extra_monthly", "supplément par mois pour l'appareil (forfait avec moins forfait sans)", round_price(extra), "€"),
        _v("real_price", f"coût réel de l'appareil via le forfait sur {p['months']} mois", real, "€"),
        _v("difference", f"{word} par rapport à l'achat comptant", abs(gap), "€"),
        _v("difference_pct", f"{word} en part du prix comptant", round_pct(abs(gap) / p["phone_price"] * 100), "%"),
        _v("total_with", f"total payé en {p['months']} mois avec le forfait avec appareil",
           round_price(p["upfront"] + p["monthly_with"] * p["months"]), "€"),
        _v("total_without", f"total payé en {p['months']} mois : appareil comptant et forfait sans appareil",
           round_price(p["phone_price"] + p["monthly_without"] * p["months"]), "€"),
    ]
    series = {"x": list(range(p["months"] + 1)), "x_label": "mois",
              "a": [round(p["upfront"] + extra * m) for m in range(p["months"] + 1)], "a_label": "payé pour l'appareil",
              "b": [p["phone_price"]] * (p["months"] + 1), "b_label": "prix comptant"}
    return Calc("forfait_appareil", {v.key: v for v in values}, "difference", series,
                compare=("real_price", "difference"))


def carte_fidelite(p: dict) -> Calc:
    """`pct` % offerts en bon d'achat sur `spend` € : la remise réelle est bon / (dépense + bon), plus faible
    qu'une remise immédiate de `pct` %, et seulement si on revient dépenser le bon."""
    voucher = p["spend"] * p["pct"] / 100
    effective = voucher / (p["spend"] + voucher) * 100
    values = [
        _v("voucher", "bon d'achat reçu", round_price(voucher), "€"),
        _v("effective_pct", "remise réelle sur tout ce qui est acheté", round_1(effective), "%"),
        _v("gap_pct", "écart avec une remise immédiate", round_1(p["pct"] - effective), "%"),
        _v("immediate_price", "prix avec une remise immédiate", round_price(p["spend"] * (1 - p["pct"] / 100)), "€"),
    ]
    steps = [round(p["spend"] * i / 10, 2) for i in range(11)]                  # économie selon la dépense
    series = {"x": steps, "x_label": "€ dépensés", "a": [round(x * p["pct"] / 100, 2) for x in steps],
              "a_label": "remise immédiate", "b": [round(x * effective / 100, 2) for x in steps],
              "b_label": "bon d'achat"}
    return Calc("carte_fidelite", {v.key: v for v in values}, "effective_pct", series, extra_numbers=(100,),
                compare=("effective_pct", "gap_pct"))


def epargne_age(p: dict) -> Calc:
    """`monthly` € par mois à `rate` %/an jusqu'à `end_age` ans, en commençant à `age_a` ou à `age_b` ans."""
    years_a, years_b = p["end_age"] - p["age_a"], p["end_age"] - p["age_b"]
    fa, fb = grow_monthly(p["monthly"], p["rate"], years_a * 12), grow_monthly(p["monthly"], p["rate"], years_b * 12)
    fa_r, fb_r = round_money(fa), round_money(fb)
    values = [
        _v("final_a", f"résultat à {p['end_age']} ans en commençant à {p['age_a']} ans", fa_r, "€"),
        _v("final_b", f"résultat à {p['end_age']} ans en commençant à {p['age_b']} ans", fb_r, "€"),
        _v("paid_a", f"total versé en commençant à {p['age_a']} ans", round_money(p["monthly"] * 12 * years_a), "€"),
        _v("paid_b", f"total versé en commençant à {p['age_b']} ans", round_money(p["monthly"] * 12 * years_b), "€"),
        _v("gap", "écart entre les deux résultats", fa_r - fb_r, "€"),
        _v("years_a", f"années de versements en commençant à {p['age_a']} ans", years_a, "ans"),
        _v("years_b", f"années de versements en commençant à {p['age_b']} ans", years_b, "ans"),
    ]
    ages = list(range(p["age_a"], p["end_age"] + 1))
    series = {"x": ages, "x_label": "âge",
              "a": [round(grow_monthly(p["monthly"], p["rate"], (a - p["age_a"]) * 12)) for a in ages],
              "b": [round(grow_monthly(p["monthly"], p["rate"], (a - p["age_b"]) * 12)) if a >= p["age_b"] else None
                    for a in ages],
              "a_label": f"dès {p['age_a']} ans", "b_label": f"dès {p['age_b']} ans"}
    return Calc("epargne_age", {v.key: v for v in values}, "gap", series, compare=("final_a", "final_b"))


def salaire_vs_prix(p: dict) -> Calc:
    """Salaire de `salary` € qui augmente de `raise_pct` % quand les prix montent de `inflation` % en un an."""
    ratio = (1 + p["raise_pct"] / 100) / (1 + p["inflation"] / 100)
    new = round_money(p["salary"] * (1 + p["raise_pct"] / 100))
    real = round_money(p["salary"] * ratio)
    values = [
        _v("new_salary", "nouveau salaire", new, "€"),
        _v("real_salary", "nouveau salaire en euros d'aujourd'hui (ce qu'il achète)", real, "€"),
        _v("real_change_pct", "variation réelle du pouvoir d'achat", round_1((ratio - 1) * 100), "%"),
        _v("real_change_eur", "variation du pouvoir d'achat par mois", real - p["salary"], "€"),
        _v("raise_eur", "augmentation par mois", new - p["salary"], "€"),
        _v("basket_rise_eur", "hausse du coût, par mois, de ce que le salaire achetait",
           round_money(p["salary"] * p["inflation"] / 100), "€"),
    ]
    series = {"x": [0, 1], "x_label": "années", "a": [0, new - p["salary"]], "a_label": "augmentation",
              "b": [0, round_money(p["salary"] * p["inflation"] / 100)], "b_label": "hausse des prix"}
    return Calc("salaire_vs_prix", {v.key: v for v in values}, "real_change_pct", series,
                compare=("new_salary", "real_salary"))


def taux_reel(p: dict) -> Calc:
    """Taux réel exact (1 + nominal) / (1 + inflation) - 1, comparé à l'approximation nominal - inflation,
    sur `amount` € pendant un an."""
    exact = ((1 + p["nominal"] / 100) / (1 + p["inflation"] / 100) - 1) * 100
    values = [
        _v("real_exact", "taux réel (formule exacte)", round_2(exact), "%"),
        _v("real_approx", "taux réel approché (taux moins inflation)", round_2(p["nominal"] - p["inflation"]), "%"),
        _v("nominal_gain", f"intérêts gagnés en un an sur {fmt_number(p['amount'])} €",
           round_price(p["amount"] * p["nominal"] / 100), "€"),
        _v("real_gain", "gain réel en pouvoir d'achat", round_price(p["amount"] * exact / 100), "€"),
        _v("final_nominal", "sur le compte après un an", round_price(p["amount"] * (1 + p["nominal"] / 100)), "€"),
        _v("final_real", "ce que ça achète après un an, en euros d'aujourd'hui",
           round_price(p["amount"] * (1 + exact / 100)), "€"),
    ]
    months = list(range(13))                    # gains au fil de l'année : intérêts et gain réel, depuis 0
    series = {"x": months, "x_label": "mois",
              "a": [round(p["amount"] * p["nominal"] / 100 * m / 12, 2) for m in months], "a_label": "intérêts",
              "b": [round(p["amount"] * exact / 100 * m / 12, 2) for m in months], "b_label": "gain réel"}
    return Calc("taux_reel", {v.key: v for v in values}, "real_exact", series, compare=("real_approx", "real_exact"))


def leasing_epargne(p: dict) -> Calc:
    """`monthly` € par mois pendant `years` ans : loyer de leasing (la voiture est rendue, rien ne reste) ou
    même somme mise de côté chaque mois à `rate` %/an (taux mensuel équivalent)."""
    months = p["years"] * 12
    paid = round_money(p["monthly"] * months)
    saved = round_money(grow_monthly(p["monthly"], p["rate"], months))
    values = [
        _v("leasing_paid", f"loyers payés en {p['years']} ans", paid, "€"),
        _v("leasing_left", "ce qui reste à la fin du leasing", 0, "€"),
        _v("saving_final", f"la même somme mise de côté pendant {p['years']} ans", saved, "€"),
        _v("saving_gain", "intérêts gagnés en mettant de côté", saved - paid, "€"),
    ]
    series = _years_series(p["years"], lambda y: round(grow_monthly(p["monthly"], p["rate"], y * 12)),
                           lambda y: round(p["monthly"] * 12 * y), a_label="mis de côté", b_label="loyers payés")
    return Calc("leasing_epargne", {v.key: v for v in values}, "saving_final", series,
                compare=("saving_final", "leasing_left"))


CONCEPTS = {"interets_composes": interets_composes, "inflation": inflation, "cout_du_temps": cout_du_temps,
            "frais": frais, "regle_72": regle_72,
            "depenses_repetees": depenses_repetees, "abonnements": abonnements,
            "remises_successives": remises_successives, "paiement_fractionne": paiement_fractionne,
            "credit_amortissable": credit_amortissable, "decouvert_agios": decouvert_agios,
            "forfait_appareil": forfait_appareil, "carte_fidelite": carte_fidelite, "epargne_age": epargne_age,
            "salaire_vs_prix": salaire_vs_prix, "taux_reel": taux_reel, "leasing_epargne": leasing_epargne}


# ---------- Paramètres attendus et plages réalistes (hypothèses 2026, jamais des données officielles) ----------
# nom -> (libellé, unité, minimum, maximum). Un candidat hors plage, incomplet ou sans calcul est écarté.
SPECS: dict[str, dict] = {
    "interets_composes": {"label": "commencer tôt ou mettre plus tard", "params": {
        "early_age": ("âge de départ de Léa", "ans", 15, 40), "late_age": ("âge de départ de Hugo", "ans", 25, 55),
        "early_amount": ("somme de Léa", "€", 10, 10_000), "late_amount_factor": ("Hugo met N fois plus", "", 1, 5),
        "rate": ("rendement annuel", "%", 1, 8), "end_age": ("âge d'arrivée", "ans", 50, 70)}},
    "inflation": {"label": "argent qui dort face à l'inflation", "params": {
        "amount": ("somme", "€", 100, 100_000), "inflation": ("inflation annuelle", "%", 1, 6),
        "years": ("durée", "ans", 1, 40)}},
    "cout_du_temps": {"label": "coût d'attendre pour commencer", "params": {
        "monthly": ("versement mensuel", "€", 10, 1_000), "rate": ("rendement annuel", "%", 1, 8),
        "delay_years": ("années d'attente", "ans", 1, 20), "horizon_years": ("durée totale", "ans", 10, 45)}},
    "frais": {"label": "frais annuels", "params": {
        "amount": ("somme", "€", 500, 100_000), "rate": ("rendement annuel", "%", 1, 8),
        "fees": ("frais annuels", "%", 0.1, 4), "years": ("durée", "ans", 5, 40)}},
    "regle_72": {"label": "règle des 72", "params": {
        "rate": ("premier taux", "%", 1, 8), "rate_b": ("second taux", "%", 1.5, 12)}},
    "depenses_repetees": {"label": "petite dépense répétée", "params": {
        "amount": ("prix de la dépense", "€", 0.5, 50), "per_week": ("fois par semaine", "", 1, 14),
        "years": ("horizon", "ans", 2, 20)}},
    "abonnements": {"label": "abonnements cumulés", "params": {
        "sub_1": ("abonnement 1", "€", 1, 80), "sub_2": ("abonnement 2", "€", 0, 80),
        "sub_3": ("abonnement 3", "€", 0, 80), "sub_4": ("abonnement 4", "€", 0, 80),
        "years": ("horizon", "ans", 2, 10)}},
    "remises_successives": {"label": "remises successives", "params": {
        "price": ("prix de départ", "€", 10, 2_000), "first": ("première remise", "%", 5, 70),
        "second": ("seconde remise", "%", 5, 50)}},
    "paiement_fractionne": {"label": "paiement en plusieurs fois",
                            "note": "Dis d'abord le coût en euros ; le taux annuel équivalent n'apparaît que s'il est "
                                    "expliqué (« comme un crédit à X % par an », avec le taux calculé).", "params": {
        "price": ("prix", "€", 30, 3_000), "installments": ("nombre de paiements", "", 2, 12),
        "fee_pct": ("frais du service", "%", 0, 6), "late_fee": ("frais de retard", "€", 0, 50)}},
    "credit_amortissable": {"label": "crédit à mensualités fixes", "params": {
        "amount": ("montant emprunté", "€", 1_000, 60_000), "rate": ("taux annuel", "%", 0.5, 15),
        "years": ("durée", "ans", 1, 8)}},
    "decouvert_agios": {"label": "découvert et agios", "params": {
        "overdraft": ("découvert", "€", 50, 3_000), "days": ("jours à découvert", "jours", 1, 60),
        "rate": ("taux annuel du découvert", "%", 5, 22)}},
    "forfait_appareil": {"label": "téléphone payé avec le forfait", "params": {
        "phone_price": ("prix comptant de l'appareil", "€", 100, 2_000), "upfront": ("prix payé au départ", "€", 0, 500),
        "monthly_with": ("forfait avec appareil", "€", 10, 120), "monthly_without": ("forfait sans appareil", "€", 2, 80),
        "months": ("durée d'engagement", "mois", 12, 36)}},
    "carte_fidelite": {"label": "bon d'achat ou remise immédiate", "params": {
        "spend": ("dépense", "€", 20, 1_000), "pct": ("pourcentage offert", "%", 2, 30)}},
    "epargne_age": {"label": "épargne mensuelle selon l'âge de départ", "params": {
        "monthly": ("versement mensuel", "€", 10, 1_000), "rate": ("rendement annuel", "%", 1, 8),
        "age_a": ("premier âge de départ", "ans", 16, 45), "age_b": ("second âge de départ", "ans", 20, 55),
        "end_age": ("âge d'arrivée", "ans", 40, 70)}},
    "salaire_vs_prix": {"label": "salaire face aux prix", "params": {
        "salary": ("salaire net mensuel", "€", 800, 6_000), "raise_pct": ("augmentation", "%", 0, 10),
        "inflation": ("hausse des prix", "%", 0, 10)}},
    "taux_reel": {"label": "taux réel", "params": {
        "nominal": ("taux affiché", "%", 0, 10), "inflation": ("inflation", "%", 0, 10),
        "amount": ("somme", "€", 100, 100_000)}},
    "leasing_epargne": {"label": "leasing ou épargne", "params": {
        "monthly": ("loyer mensuel", "€", 50, 1_000), "years": ("durée", "ans", 2, 6),
        "rate": ("rendement annuel de l'épargne", "%", 1, 6)}},
}

# Hypothèse affichée à l'écran (jamais reformulée par le LLM) : conventions du calcul, chiffres du sujet
HYPOTHESES: dict[str, str] = {
    "depenses_repetees": "{amount} € · {per_week} fois par semaine · 52 semaines par an",
    "abonnements": "prix mensuels constants · sans hausse de tarif",
    "remises_successives": "remises appliquées l'une après l'autre",
    "paiement_fractionne": "1er paiement le jour de l'achat, puis 1 par mois · taux annuel composé",
    "credit_amortissable": "{rate} %/an · mensualités fixes · taux mensuel = taux annuel \u00f7 12 · hors assurance",
    "decouvert_agios": "{rate} %/an · agios = montant \u00d7 taux \u00d7 jours \u00f7 365",
    "forfait_appareil": "forfait avec appareil {monthly_with} €/mois, sans appareil {monthly_without} €/mois, même "
                        "service · appareil {phone_price} € comptant · {months} mois",
    "carte_fidelite": "bon d'achat dépensé en entier · même pourcentage en remise immédiate",
    "epargne_age": "{monthly} €/mois · {rate} %/an, taux mensuel équivalent · jusqu'à {end_age} ans · avant inflation",
    "salaire_vs_prix": "salaire net · prix sur 1 an · pouvoir d'achat = salaire \u00f7 prix",
    "taux_reel": "taux réel = (1 + taux) \u00f7 (1 + inflation) \u2212 1 · sur 1 an",
    "leasing_epargne": "{monthly} €/mois · le leasing paie l'usage d'une voiture, rendue à la fin ; l'épargne n'en "
                       "donne pas · {rate} %/an, taux mensuel équivalent",
}

# Résultats qui ne se citent qu'expliqués : la phrase qui les cite doit contenir l'une de ces expressions
EXPLAIN: dict[str, dict[str, tuple[str, ...]]] = {
    "paiement_fractionne": {"annual_rate": ("comme un crédit", "taux annuel", "par an")},
}


def money_text(x: float) -> str:
    """Montant d'un paramètre : « 2 € », « 2,50 € », « 13,49 € »."""
    return Value("", "", float(x), "€").text


def hypothesis_text(concept: str, p: dict) -> str:
    units = {k: spec[1] for k, spec in SPECS.get(concept, {}).get("params", {}).items()}
    fields = {}
    for k, v in p.items():
        if isinstance(v, (int, float)):           # montant à centimes : « 2,50 », jamais « 2,5 »
            fields[k] = money_text(v)[:-2] if units.get(k) == "€" else fmt_number(v)
        else:
            fields[k] = v
    return HYPOTHESES[concept].format(**fields)


def _constraint(concept: str, p: dict) -> str | None:
    """Cohérence entre paramètres : None si tout va bien, sinon la raison."""
    if concept == "remises_successives" and p["first"] + p["second"] >= 100:
        return "les deux remises additionnées atteignent 100 %"
    if concept == "abonnements" and not any(p.get(k) for k in ("sub_1", "sub_2", "sub_3", "sub_4")):
        return "aucun abonnement"
    if concept == "forfait_appareil" and p["monthly_with"] <= p["monthly_without"]:
        return "le forfait avec appareil doit coûter plus cher que sans"
    if concept == "epargne_age" and not p["age_a"] < p["age_b"] < p["end_age"]:
        return "il faut âge de départ 1 < âge de départ 2 < âge d'arrivée"
    if concept == "interets_composes" and not p["early_age"] < p["late_age"] < p["end_age"]:
        return "il faut âge de Léa < âge de Hugo < âge d'arrivée"
    if concept == "cout_du_temps" and p["delay_years"] >= p["horizon_years"]:
        return "l'attente dépasse la durée totale"
    if concept == "regle_72" and p["rate_b"] <= p["rate"]:
        return "le second taux doit être plus élevé"
    if concept == "paiement_fractionne" and p["fee_pct"] == 0 and p["late_fee"] == 0:
        return "sans frais ni retard, il n'y a rien à calculer"
    if concept == "forfait_appareil" and \
            abs(p["upfront"] + (p["monthly_with"] - p["monthly_without"]) * p["months"] - p["phone_price"]) < 1:
        return "avec ces chiffres, les deux options coûtent pareil : rien à montrer"
    return None


def check_params(concept: str, params: dict) -> tuple[dict | None, str]:
    """(paramètres numériques, "") si le calcul est possible ; sinon (None, raison lisible à journaliser)."""
    spec = SPECS.get(concept)
    if spec is None or concept not in CONCEPTS:
        return None, f"aucun calcul disponible pour « {concept} »"
    out = {}
    for name, (label, unit, lo, hi) in spec["params"].items():
        if name not in (params or {}):
            if name.startswith("sub_") and name != "sub_1":
                out[name] = 0
                continue
            return None, f"paramètre manquant : {label} ({name})"
        try:
            value = float(re.sub(r"\s", "", str(params[name])).replace(",", "."))
        except ValueError:
            return None, f"paramètre non numérique : {label} = {params[name]!r}"
        if not lo <= value <= hi:
            return None, f"{label} hors plage réaliste : {fmt_number(value)} {unit} (de {fmt_number(lo)} à {fmt_number(hi)})"
        out[name] = int(value) if value.is_integer() else value
    extra = sorted(set(params or {}) - set(spec["params"]))
    if extra:
        return None, f"paramètres inconnus pour « {concept} » : {', '.join(extra)}"
    if concept == "interets_composes":
        out["late_amount"] = out["early_amount"] * out["late_amount_factor"]
    reason = _constraint(concept, out)
    return (None, reason) if reason else (out, "")



def round_2(x: float) -> float:
    return float(round(x, 2))


# Pourcentages qui ne sont pas une part d'un tout : leur complément à 100 ne veut rien dire
NO_COMPLEMENT = {"annual_rate", "gap_pct", "real_exact", "real_approx", "extra_pct", "effective_pct",
                 "real_change_pct", "difference_pct"}


def derived(concept: str, p: dict, calc: Calc) -> list[Value]:
    """Valeurs dérivées qu'un script peut citer à bon droit : complément à 100 de chaque pourcentage (41 % =
    100 % - 59 %), multiplicateur cumulé (1 + taux)^n à 2 décimales (2,43), montant équivalent."""
    out = [_v(f"{v.key}_complement", f"100 % moins « {v.label} »", round_1(100 - v.value), "%")
           for v in calc.values.values() if v.unit == "%" and 0 < v.value < 100 and v.key not in NO_COMPLEMENT]
    if concept == "inflation":
        factor = (1 + p["inflation"] / 100) ** p["years"]
        out += [_v("price_factor", f"les prix sont multipliés par, en {p['years']} ans", round_2(factor), ""),
                _v("same_power", f"somme nécessaire dans {p['years']} ans pour acheter autant qu'avec "
                   f"{fmt_number(p['amount'])} € aujourd'hui", round_money(p["amount"] * factor), "€")]
    if concept == "frais":
        out += [_v("growth_without", "le capital sans frais est multiplié par", round_2(grow(1, p["rate"], p["years"])), ""),
                _v("growth_with", "le capital avec frais est multiplié par",
                   round_2(((1 + p["rate"] / 100) * (1 - p["fees"] / 100)) ** p["years"]), "")]
    if concept == "cout_du_temps":
        out.append(_v("growth_now", "chaque euro versé au départ est multiplié par",
                      round_2(grow(1, p["rate"], p["horizon_years"])), ""))
    # résultat négatif (« -1,9 % ») : sa valeur absolue se dit avec « perd » / « baisse » (« tu perds 1,9 % »)
    out += [_v(f"{v.key}_abs", f"baisse : {v.label}", abs(v.value), v.unit)
            for v in calc.values.values() if v.value < 0 and v.unit in ("%", "€")]
    if concept == "credit_amortissable":
        out.append(_v("yearly_payment", "remboursé chaque année", round_money(calc["monthly"] * 12), "€"))
    if concept == "epargne_age":
        out += [_v("paid_gap", "versements en plus en commençant plus tôt", calc["paid_a"] - calc["paid_b"], "€"),
                _v("gain_a", "intérêts gagnés en commençant plus tôt", calc["final_a"] - calc["paid_a"], "€"),
                _v("gain_b", "intérêts gagnés en commençant plus tard", calc["final_b"] - calc["paid_b"], "€")]
    if concept == "carte_fidelite":
        out.append(_v("total_value", "valeur totale obtenue (achat + bon)", round_price(p["spend"] + calc["voucher"]), "€"))
    return [v for v in out if v.key not in calc.values]


def compute(concept: str, params: dict) -> Calc:
    try:
        fn = CONCEPTS[concept]
    except KeyError:
        raise KeyError(f"Concept sans calcul : {concept}") from None
    calc = fn(params)
    for value in derived(concept, params, calc):
        calc.values[value.key] = value
    return calc
