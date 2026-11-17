"""Capital Simple, partie 3b : scènes génériques des concepts du quotidien (deux montants, barres, courbe avec
Léa ou Hugo, personnages), graduations de l'axe vertical, chiffres de l'écran tirés de calc.py, zone sûre."""
import re

import pytest
from auracontent.channels.finance import calc as fcalc
from auracontent.channels.finance import visuals
from auracontent.services.visuals.linework import templates as tpl
from tests.test_finance_part3a import NEW

PARAMS = {**NEW, "leasing_epargne": {"monthly": 300, "years": 4, "rate": 3}}
SCENES = {"deux_montants": {"role": "reveal", "template": "deux_arbres", "visual": "piles"},
          "barres": {"role": "takeaway", "template": "barres", "visual": "barres"},
          "courbe": {"role": "mechanism", "template": "deux_courbes", "visual": "ecart"},
          "personnages": {"role": "context", "template": "personnages", "visual": "seul"}}


def _params(concept):
    params, why = fcalc.check_params(concept, PARAMS[concept])
    assert params, why
    return params


def _layers(concept, scene):
    params = _params(concept)
    built = visuals.build_scene(concept, params, SCENES[scene], 6.0,
                                hypothesis=fcalc.hypothesis_text(concept, params))     # contrôle bloquant
    return built.layers


def test_every_daily_concept_has_generic_visuals():
    assert set(visuals.GENERIC) == set(fcalc.HYPOTHESES) == set(PARAMS)


@pytest.mark.parametrize("scene", list(SCENES))
@pytest.mark.parametrize("concept", list(PARAMS))
def test_generic_scene_passes_the_layout_check(concept, scene):
    layers = _layers(concept, scene)
    texts = [lay["text"] for lay in layers if lay["type"] == "text"]
    assert texts
    for t in texts:                                                  # espace des milliers, jamais « 1000 € »
        assert not re.search(r"\d{4,}", t), t


@pytest.mark.parametrize("concept", list(PARAMS))
def test_bars_and_curve_show_lea_or_hugo_facing_the_chart(concept):
    for scene in ("barres", "courbe"):
        companion = [lay for lay in _layers(concept, scene) if lay.get("id") == "compagnon"]
        assert len(companion) == 1 and companion[0]["path"].startswith(("lea-", "hugo-")) and companion[0]["flip"]


@pytest.mark.parametrize("concept", list(PARAMS))
def test_curve_has_vertical_ticks_and_values_from_calc(concept):
    layers = _layers(concept, "courbe")
    ticks = {lay["text"] for lay in layers if lay.get("id", "").startswith("graduation-texte")}
    assert "0 €" in ticks and len(ticks) >= 2
    calc = fcalc.compute(concept, _params(concept))
    allowed = {v.text for v in calc.values.values()} | {fcalc.money_text(v) for v in _params(concept).values()
                                                       if isinstance(v, (int, float))}
    for lay in layers:
        if lay["type"] == "text" and lay.get("id", "").startswith("legende-") and " : " in lay["text"] and not lay.get("count"):
            assert lay["text"].split(" : ", 1)[1] in allowed, lay["text"]
    top = max(ticks - {"0 €"}, key=lambda t: float(t.replace(" ", "").replace(",", ".").rstrip("€")))
    assert top in allowed, top                                      # valeur la plus haute : celle de calc.py


def test_epargne_curve_writes_calc_values_not_the_raw_series():
    layers = _layers("epargne_age", "courbe")
    texts = " ".join(lay["text"] for lay in layers if lay["type"] == "text")
    assert "98 000 €" in texts and "97 997" not in texts and "40 770" not in texts


def test_cents_keep_two_digits_on_screen():
    texts = " ".join(lay["text"] for lay in _layers("paiement_fractionne", "barres") if lay["type"] == "text")
    assert "408,80 €" in texts and "8,80 €" in texts and "408,8 €" not in texts


def test_small_pile_is_proportional():
    layers = _layers("decouvert_agios", "deux_montants")
    big = next(lay for lay in layers if lay.get("id") == "objet-gagnant")
    small = next(lay for lay in layers if lay.get("id") == "objet-perdant")
    assert small["path"] == big["path"] and small["h"] < 0.2 * big["h"]       # 2,19 € contre 26,30 €


def test_long_hypothesis_takes_two_lines_without_overlap():
    params = _params("epargne_age")
    hyp = fcalc.hypothesis_text("epargne_age", params)
    assert "jusqu'à 65 ans" in hyp and "taux mensuel équivalent" in hyp
    assert tpl.lines_of(hyp, 50, 855) == 2


def test_old_concepts_keep_their_own_scenes():
    params = {"amount": 5000, "rate": 6, "fees": 2, "years": 20}
    layers = visuals.scene_layers("frais", params, SCENES["courbe"], 6.0, hypothesis="h")
    assert not any(lay.get("id") == "compagnon" for lay in layers)
    assert not any(lay.get("id", "").startswith("graduation") for lay in layers)
