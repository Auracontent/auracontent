"""Chaîne finance, phase 2 : calc.py (seule source des chiffres), validation des nombres, choix du sujet."""
import math

import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance import calc
from auracontent.channels.finance.brain import FinanceBrain, numbers_in


def _brain(llm=None) -> FinanceBrain:
    return BaseChannel("finance", FinanceBrain, llm).brain


def _all_combos():
    brain = _brain()
    for concept in brain.config["brain"]["concepts"]:
        for params in brain.combinations(concept):
            yield concept, params


# ---------- Formules, vérifiées par une simulation indépendante ----------
def _simulate_yearly(amount, rate, years, fees=0.0):
    for _ in range(years):
        amount *= 1 + rate / 100
        amount -= amount * fees / 100            # frais prélevés en fin d'année sur le total
    return amount


def _simulate_monthly(monthly, rate, months):
    total, rm = 0.0, (1 + rate / 100) ** (1 / 12) - 1
    for _ in range(months):
        total = total * (1 + rm) + monthly       # versement en fin de mois
    return total


def test_grow_matches_simulation():
    assert calc.grow(100, 7, 45) == pytest.approx(_simulate_yearly(100, 7, 45))
    assert calc.grow(100, 7, 45) == pytest.approx(2100.25, abs=0.01)


def test_monthly_rate_is_equivalent_to_annual():
    assert (1 + calc.monthly_rate(5)) ** 12 == pytest.approx(1.05)
    assert calc.grow_monthly(100, 5, 12 * 30) == pytest.approx(_simulate_monthly(100, 5, 12 * 30))
    assert calc.grow_monthly(100, 0, 12) == 1200
    assert calc.grow_monthly(100, 5, 0) == 0


def test_interets_composes_lea_hugo():
    r = calc.compute("interets_composes", {"early_age": 20, "late_age": 40, "early_amount": 100,
                                           "late_amount": 300, "rate": 7, "end_age": 65})
    assert (r["lea_final"], r["hugo_final"], r["gap"]) == (2100, 1630, 470)
    assert (r["lea_years"], r["hugo_years"]) == (45, 25)
    assert r.headline == "lea_final" and r.main.text == "2 100 €"
    assert r.series["a"][0] == 100 and r.series["b"][0] is None and r.series["b"][20] == 300


def test_inflation():
    r = calc.compute("inflation", {"amount": 10000, "inflation": 3, "years": 20})
    assert r["real_value"] == calc.round_money(10000 / 1.03 ** 20) == 5540
    assert r["lost"] == 10000 - 5540 and r["lost_pct"] == 45 and r["price_of_100"] == 181
    assert 100 in r.numbers()                                  # « ce qui coûte 100 € »


def test_cout_du_temps():
    p = {"monthly": 100, "rate": 5, "delay_years": 10, "horizon_years": 40}
    r = calc.compute("cout_du_temps", p)
    assert r["final_now"] == calc.round_money(_simulate_monthly(100, 5, 480))
    assert r["final_late"] == calc.round_money(_simulate_monthly(100, 5, 360))
    assert r["cost"] == r["final_now"] - r["final_late"]
    assert (r["paid_now"], r["paid_late"], r["paid_gap"]) == (48000, 36000, 12000)
    assert r.series["b"][:11] == [0] * 11                      # rien avant la fin de l'attente


def test_frais():
    p = {"amount": 5000, "rate": 6, "fees": 2, "years": 20}
    r = calc.compute("frais", p)
    assert r["final_without"] == calc.round_money(_simulate_yearly(5000, 6, 20)) == 16000
    assert r["final_with"] == calc.round_money(_simulate_yearly(5000, 6, 20, fees=2)) == 10700
    assert r["lost"] == 5300 and r["lost_pct_gains"] == 48 and r["lost_pct_final"] == 33


def test_regle_72():
    r = calc.compute("regle_72", {"rate": 12})
    assert (r["years_rule"], r["years_exact"], r["years_quadruple"]) == (6, 6.1, 12)
    assert {72, 2} <= r.numbers()


def test_unknown_concept():
    with pytest.raises(KeyError, match="sans calcul"):
        calc.compute("crypto", {})


# ---------- Arrondis et format ----------
def test_round_money_and_format():
    assert [calc.round_money(x) for x in (897.6, 1634.4, 16035.7)] == [898, 1630, 16000]
    assert calc.fmt_number(16000) == "16 000" and calc.fmt_number(6.1) == "6,1" and calc.fmt_number(0.5) == "0,5"
    for text in ("16 000", "6,1", "0,5", "1 630"):            # le format produit est relu à l'identique
        assert len(numbers_in(text)) == 1


# ---------- Toutes les combinaisons du YAML ----------
def test_every_combination_is_consistent():
    count = 0
    for concept, params in _all_combos():
        r = calc.compute(concept, params)
        count += 1
        assert r.headline in r.values
        for v in r.values.values():
            assert math.isfinite(v.value), (concept, params, v)
            assert numbers_in(v.text) == [v.value], (concept, params, v)     # le texte se relit sans perte
        if concept == "interets_composes":
            assert r["gap"] == r["lea_final"] - r["hugo_final"] > 0          # Léa gagne toujours
        if concept == "frais":
            assert r["lost"] == r["final_without"] - r["final_with"] > 0
        if concept == "inflation":
            assert r["lost"] == params["amount"] - r["real_value"] > 0
        if concept == "cout_du_temps":
            assert r["cost"] == r["final_now"] - r["final_late"] > 0
        if concept == "regle_72":
            assert abs(r["years_rule"] - r["years_exact"]) < 1.1             # l'approximation reste proche
    assert count > 100


# ---------- Validation des chiffres du script ----------
def _picked(concept, params):
    brain = _brain()
    resolved = brain.resolve_params(concept, params)
    brain.last_pick = {"concept": concept, "params": resolved, "topic_key": brain.topic_key(concept, resolved)}
    return brain


def _frais_script(reveal: str):
    scenes = [{"id": i, "text": "Les frais grignotent ton argent chaque année.", "role": "mechanism",
               "visual": "une fuite", "template": "deux_courbes", "mood": "calm", "pause_after_ms": 300}
              for i in range(1, 7)]
    scenes.append({"id": 7, "text": reveal, "role": "reveal", "visual": "deux courbes",
                   "template": "deux_courbes", "mood": "surprise", "pause_after_ms": 300})
    return {"title": "Les frais", "on_screen_title": "2 % DE FRAIS | 5 300 € PERDUS",
            "closing_cta": "Tu regardes les frais avant de signer ?", "scenes": scenes}


FRAIS = {"amount": 5000, "rate": 6, "fees": 2, "years": 20}


def test_script_citing_computed_results_passes():
    brain = _picked("frais", FRAIS)
    assert brain.check_script_logic("t", _frais_script("Les frais te coûtent 5 300 €, soit 48 % des gains.")) == []


def test_script_with_invented_number_is_rejected():
    brain = _picked("frais", FRAIS)
    issues = brain.check_script_logic("t", _frais_script("Les frais te coûtent 5 300 €, presque 5 336 €."))
    assert any("5336" in i or "5 336" in i for i in issues)


def test_script_without_main_result_is_rejected():
    brain = _picked("frais", FRAIS)
    issues = brain.check_script_logic("t", _frais_script("Au final, les frais mangent une grande part."))
    assert any("résultat principal" in i and "5 300 €" in i for i in issues)


def test_prompts_carry_computed_results():
    brain = _picked("frais", FRAIS)
    messages = brain.build_script_prompt("t", 7, {"text": "x"})
    assert "coût total des frais : 5 300 €" in messages[1]["content"]
    assert "RÉSULTAT PRINCIPAL" in messages[1]["content"]
    assert "résultat sans frais : 16 000 €" in brain.numbers_block()


def test_validate_stores_calc_for_templates():
    brain = _picked("frais", FRAIS)
    data = _frais_script("Les frais te coûtent 5 300 €.")
    brain.validate_script_specifics(data, "t")
    assert data["calc"]["values"]["lost"]["text"] == "5 300 €"
    assert len(data["calc"]["series"]["a"]) == 21


# ---------- Choix du sujet ----------
@pytest.fixture
def finance_state(monkeypatch, tmp_path):
    from auracontent.services.publishing import state_sync
    from auracontent.utils import hook_tracker, pending_topic, topic_tracker

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(topic_tracker, "HISTORY_PATH", tmp_path / "global_history.json")
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hook_history.json")
    monkeypatch.setattr(pending_topic, "PENDING_PATH", tmp_path / "pending_topics.json")
    return tmp_path


class _ChoiceLLM:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def call_json_with_retry(self, messages, **kw):
        self.prompts.append(messages[1]["content"])
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_candidates_one_per_fresh_concept(finance_state):
    from auracontent.utils.topic_tracker import save_global_history

    save_global_history("x", "finance", category="frais", topic_key="frais:x")
    cands = _brain().topic_candidates()
    assert sorted(c for c, _ in cands) == ["cout_du_temps", "inflation", "interets_composes", "regle_72"]


def test_llm_choice_is_used(finance_state):
    llm = _ChoiceLLM({"choice": 2, "reason": "le plus surprenant"})
    brain = _brain(llm)
    brain.config["brain"]["concept_selection"] = "llm"
    cands = brain.topic_candidates()
    assert brain.choose_candidate(cands) == cands[1]
    assert "1. " in llm.prompts[0] and "résultat" in llm.prompts[0]


@pytest.mark.parametrize("answer", [{"choice": 99}, {"choice": "deux"}, {}, RuntimeError("429")])
def test_llm_choice_falls_back_to_random_pick(finance_state, answer, capsys):
    brain = _brain(_ChoiceLLM(answer))
    brain.config["brain"]["concept_selection"] = "llm"
    cands = brain.topic_candidates()
    assert brain.choose_candidate(cands) == cands[0]
    assert "tirage au hasard" in capsys.readouterr().out


def test_random_selection_never_calls_llm(finance_state):
    llm = _ChoiceLLM({"choice": 2})
    brain = _brain(llm)
    brain.config["brain"]["concept_selection"] = "random"
    brain.pick_topic()
    assert llm.prompts == [] and brain.last_pick["topic_key"].startswith(brain.last_pick["concept"])
