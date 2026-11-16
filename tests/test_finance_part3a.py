"""Capital Simple, partie 3a : calculs du quotidien dans calc.py (valeurs vérifiées à la main), valeurs dérivées
autorisées, paramètres validés (plages réalistes, raison lisible quand un calcul est impossible)."""
import math

import pytest
from auracontent.channels.finance import calc as c
from auracontent.channels.finance.spoken import display_text, spoken_text

NEW = {
    "depenses_repetees": {"amount": 2, "per_week": 5, "years": 10},
    "abonnements": {"sub_1": 13.49, "sub_2": 9.99, "sub_3": 5.99, "years": 5},
    "remises_successives": {"price": 100, "first": 30, "second": 20},
    "paiement_fractionne": {"price": 400, "installments": 4, "fee_pct": 2.2, "late_fee": 0},
    "credit_amortissable": {"amount": 15000, "rate": 6, "years": 5},
    "decouvert_agios": {"overdraft": 500, "days": 10, "rate": 16},
    "forfait_appareil": {"phone_price": 600, "upfront": 1, "monthly_with": 45, "monthly_without": 15, "months": 24},
    "carte_fidelite": {"spend": 100, "pct": 10},
    "epargne_age": {"monthly": 50, "rate": 5, "age_a": 20, "age_b": 35, "end_age": 65},
    "salaire_vs_prix": {"salary": 2000, "raise_pct": 3, "inflation": 3},
    "taux_reel": {"nominal": 3, "inflation": 2, "amount": 1000},
}


def _calc(concept, **override):
    params, why = c.check_params(concept, {**NEW[concept], **override})
    assert params is not None, why
    return c.compute(concept, params)


def test_every_new_concept_has_a_calc_and_a_spec():
    assert set(NEW) <= set(c.CONCEPTS) and set(c.CONCEPTS) == set(c.SPECS)


@pytest.mark.parametrize("concept", list(NEW))
def test_results_are_consistent(concept):
    calc = _calc(concept)
    assert calc.headline in calc.values and all(math.isfinite(v.value) for v in calc.values.values())
    a, b = calc.compare
    assert a in calc.values and b in calc.values
    assert len(calc.series["a"]) == len(calc.series["x"])
    for value in calc.values.values():                      # chaque valeur se dit à voix haute
        assert spoken_text(display_text(f"Il y a {value.text}."))


# ---------- Valeurs vérifiées à la main ----------
def test_small_repeated_spending():
    calc = _calc("depenses_repetees")                        # 2 € x 5 fois x 52 semaines
    assert (calc["per_week_total"], calc["per_year"], calc["over_years"]) == (10, 520, 5200)
    assert calc["per_month"] == 43.33 and calc.values["per_month"].text == "43,33 €"


def test_subscriptions_add_up():
    calc = _calc("abonnements")                              # 13,49 + 9,99 + 5,99 = 29,47 €/mois
    assert calc["total_month"] == 29.47 and calc["total_year"] == 354 and calc["over_years"] == 1770
    assert calc["count"] == 3


def test_successive_discounts_are_not_added():
    calc = _calc("remises_successives")                      # -30 % puis -20 % = -44 %, pas -50 %
    assert calc["total_pct"] == 44 and calc["naive_pct"] == 50
    assert (calc["after_first"], calc["final_price"], calc["naive_price"], calc["gap_eur"]) == (70, 56, 50, 6)
    assert 56 in calc.numbers()                              # « tu paies 56 % du prix » : complément autorisé


def test_split_payment_cost_and_equivalent_rate():
    calc = _calc("paiement_fractionne")                      # 400 € en 4 fois, 2,2 % de frais
    assert (calc["installment"], calc["total_paid"], calc["extra_cost"]) == (102.2, 408.8, 8.8)
    assert calc.values["installment"].text == "102,20 €" and calc["extra_pct"] == 2.2
    r = (1 + calc["annual_rate"] / 100) ** (1 / 12) - 1      # le taux équivalent rend la valeur actuelle = prix
    assert abs(sum(102.2 / (1 + r) ** k for k in range(4)) - 400) < 0.1
    assert calc["annual_rate"] > 15                          # 2,2 % sur 3 mois en moyenne : bien plus par an
    late = _calc("paiement_fractionne", late_fee=15)
    assert late["extra_cost"] == 23.8 and late["annual_rate"] > calc["annual_rate"]
    assert "annual_rate_complement" not in calc.values       # un taux n'est pas une part d'un tout


def test_amortized_loan():
    calc = _calc("credit_amortissable")                      # 15 000 € à 6 % sur 5 ans : 289,99 €/mois
    assert calc["monthly"] == 290 and calc["months"] == 60
    assert calc["total_paid"] == 17400 and calc["interest"] == 2400 and calc["interest_pct"] == 16
    assert calc["yearly_payment"] == 3480
    assert calc.series["b"][0] == 15000 and calc.series["b"][-1] == 0


def test_zero_rate_loan():
    calc = _calc("credit_amortissable", rate=0.5, amount=12000, years=1)
    assert calc["interest"] < 100


def test_overdraft_fees():
    calc = _calc("decouvert_agios")                          # 500 € x 16 % x 10 / 365 = 2,19 €
    assert calc["agios"] == 2.19 and calc["agios_year"] == 26.3 and calc["per_day"] == 0.22


def test_phone_paid_through_the_plan():
    calc = _calc("forfait_appareil")                         # 1 € + 30 € x 24 mois = 721 € pour 600 €
    assert (calc["extra_monthly"], calc["real_price"], calc["overcost"], calc["overcost_pct"]) == (30, 721, 121, 20)
    params, why = c.check_params("forfait_appareil", {**NEW["forfait_appareil"], "phone_price": 800})
    assert params is None and "pas plus cher" in why


def test_loyalty_voucher_is_less_than_an_immediate_discount():
    calc = _calc("carte_fidelite")                           # 10 € de bon pour 110 € de produits : 9,1 %
    assert (calc["voucher"], calc["effective_pct"], calc["gap_pct"], calc["immediate_price"]) == (10, 9.1, 0.9, 90)


def test_monthly_saving_by_starting_age():
    calc = _calc("epargne_age")
    assert calc["final_a"] > calc["final_b"] and calc["gap"] == calc["final_a"] - calc["final_b"]
    assert (calc["paid_a"], calc["paid_b"], calc["paid_gap"]) == (27000, 18000, 9000)
    assert (calc["years_a"], calc["years_b"]) == (45, 30)


@pytest.mark.parametrize("raise_pct, inflation, pct, real", [(3, 3, 0, 2000), (2, 4, -1.9, 1960), (5, 2, 2.9, 2060)])
def test_salary_versus_prices(raise_pct, inflation, pct, real):
    calc = _calc("salaire_vs_prix", raise_pct=raise_pct, inflation=inflation)
    assert calc["real_change_pct"] == pct and calc["real_salary"] == real
    assert c.fmt_number(calc["real_change_pct"]) != "-0"


def test_real_rate_exact_formula():
    calc = _calc("taux_reel")                                # 1,03 / 1,02 - 1 = 0,98 %, pas 1 %
    assert calc["real_exact"] == 0.98 and calc["real_approx"] == 1
    assert calc["nominal_gain"] == 30 and calc["real_gain"] == 9.8


# ---------- Paramètres : calcul possible ou raison lisible ----------
@pytest.mark.parametrize("concept, params, reason", [
    ("loyer_vs_achat", {"rent": 800}, "aucun calcul disponible"),
    ("decouvert_agios", {"overdraft": 500, "days": 10}, "paramètre manquant : taux annuel du découvert"),
    ("decouvert_agios", {"overdraft": 500, "days": 10, "rate": 45}, "hors plage réaliste"),
    ("decouvert_agios", {"overdraft": 500, "days": 10, "rate": "seize"}, "non numérique"),
    ("decouvert_agios", {"overdraft": 500, "days": 10, "rate": 16, "fees": 8}, "paramètres inconnus"),
    ("remises_successives", {"price": 100, "first": 60, "second": 50}, "100 %"),
    ("epargne_age", {"monthly": 50, "rate": 5, "age_a": 35, "age_b": 20, "end_age": 65}, "âge de départ"),
    ("paiement_fractionne", {"price": 400, "installments": 4, "fee_pct": 0, "late_fee": 0}, "rien à calculer"),
])
def test_impossible_calculation_gives_a_reason(concept, params, reason):
    out, why = c.check_params(concept, params)
    assert out is None and reason in why


def test_params_accept_french_decimals_and_optional_subscriptions():
    params, why = c.check_params("abonnements", {"sub_1": "13,49", "years": 3})
    assert why == "" and params == {"sub_1": 13.49, "sub_2": 0, "sub_3": 0, "sub_4": 0, "years": 3}


def test_old_concepts_keep_their_values():
    calc = c.compute("frais", {"amount": 5000, "rate": 6, "fees": 2, "years": 20})
    assert calc["lost"] == 5300
    params, _ = c.check_params("interets_composes", {"early_age": 20, "late_age": 40, "early_amount": 100,
                                                     "late_amount_factor": 3, "rate": 7, "end_age": 65})
    assert params["late_amount"] == 300


# ---------- Montants avec centimes : écran et voix ----------
@pytest.mark.parametrize("text, spoken", [
    ("4,93 €", "quatre euros quatre-vingt-treize"), ("2,50 €", "deux euros cinquante"),
    ("0,50 €", "cinquante centimes"), ("1,20 €", "un euro vingt"), ("10 000 €", "dix mille euros"),
    ("0,98 %", "zéro virgule quatre-vingt-dix-huit pour cent"),
])
def test_cents_are_spoken_naturally(text, spoken):
    assert spoken_text(text) == spoken


def test_money_with_cents_is_displayed_with_two_decimals():
    assert c.Value("x", "x", 2.5, "€").text == "2,50 €" and c.Value("x", "x", 1234.5, "€").text == "1 234,50 €"
    assert c.Value("x", "x", 6.1, "ans").text == "6,1 ans"


@pytest.mark.parametrize("raw, shown", [("Tu paies 2,5 € par jour.", "Tu paies 2,50 € par jour."),
                                        ("Chaque paiement fait 102,2 €.", "Chaque paiement fait 102,20 €."),
                                        ("Ça fait 1234,5 euros.", "Ça fait 1 234,50 euros."),
                                        ("Un taux de 0,98 %.", "Un taux de 0,98 %."),
                                        ("Il faut 6,1 ans.", "Il faut 6,1 ans.")])
def test_screen_shows_cents_with_two_digits(raw, shown):
    assert display_text(raw) == shown
