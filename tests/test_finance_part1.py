"""Capital Simple, partie 1 (1.2 à 1.7) : fiabilité de la validation des scripts."""
import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance.brain import FinanceBrain

INFL_1000 = {"amount": 1000, "inflation": 2, "years": 30}
INFL_10000 = {"amount": 10000, "inflation": 3, "years": 30}


def _brain(concept, params, llm=None):
    brain = BaseChannel("finance", FinanceBrain, llm).brain
    params = brain.resolve_params(concept, dict(params))
    brain.last_pick = {"concept": concept, "params": params, "topic_key": brain.topic_key(concept, params)}
    return brain


# ---------- 1.2 « perdre » sans pouvoir d'achat ----------
@pytest.mark.parametrize("text", ["Ton argent perd 448 € de pouvoir d'achat en 30 ans.",
                                  "Tes 1 000 € n'ont plus que la valeur réelle de 552 €, tu perds en valeur réelle.",
                                  "Ce que ton argent peut acheter perd du terrain chaque année."])
def test_loss_with_allowed_wording_is_accepted(text):
    assert _brain("inflation", INFL_1000).text_issues(text, "s") == []


def test_loss_of_euros_is_rejected_with_sentence_and_fixes():
    brain = _brain("inflation", INFL_1000)
    issues = brain.text_issues("Ton argent perd 448 € en 30 ans.", "la scène 3")
    assert len(issues) == 1
    msg = issues[0]
    assert "« Ton argent perd 448 € en 30 ans. »" in msg
    assert "« ton argent perd 45 % de pouvoir d'achat »" in msg and "valeur réelle de 552 €" in msg


def test_prompt_lists_forbidden_and_allowed_wording_from_first_call():
    brain = _brain("inflation", INFL_1000)
    prompt = brain.build_script_prompt("t", 7, {"text": "h"})[1]["content"]
    assert "INTERDIT" in prompt and "AUTORISÉ" in prompt and "valeur réelle de 552 €" in prompt


# ---------- 1.3 Valeurs dérivées autorisées ----------
def test_complement_and_cumulative_multiplier_accepted():
    brain = _brain("inflation", INFL_10000)
    assert brain.text_issues("Il ne reste que 41 % du pouvoir d'achat.", "s") == []
    assert brain.text_issues("Les prix sont multipliés par 2,43 en 30 ans.", "s") == []
    assert brain.text_issues("Les prix sont multipliés par 2,4 en 30 ans.", "s") == []          # arrondi accepté
    assert brain.text_issues("Il faudrait 24 300 € pour acheter autant.", "s") == []


def test_derived_values_of_the_other_subject():
    brain = _brain("inflation", INFL_1000)
    assert brain.text_issues("Il ne reste que 55 % du pouvoir d'achat.", "s") == []
    assert brain.text_issues("Les prix sont multipliés par 1,81.", "s") == []
    assert any("non autorisé" in i for i in brain.text_issues("Les prix sont multipliés par 2,43.", "s"))
    assert any("non autorisé" in i for i in brain.text_issues("Il ne reste que 41 % du pouvoir d'achat.", "s"))


def test_money_has_no_extra_tolerance():
    brain = _brain("inflation", INFL_1000)
    assert any("non autorisé" in i for i in brain.text_issues("Il reste 550 €.", "s"))               # 552 € exact


# ---------- 1.4 Structure corrigée sans relancer le LLM ----------
from auracontent.channels.finance import storyboard  # noqa: E402

FRAIS = {"amount": 5000, "rate": 6, "fees": 2, "years": 20}


def _frais_data(first: str, bandeau="2 % DE FRAIS | 5 300 € PERDUS"):
    board = storyboard.storyboard("frais")
    scenes = [{"id": i, "text": "Les frais grignotent ton argent chaque année.", "visual": ""}
              for i in range(1, len(board) + 1)]
    scenes[0]["text"] = first
    scenes[[r for r, _ in board].index("reveal")]["text"] = "Les frais te coûtent 5 300 €."
    return {"title": "Les frais", "on_screen_title": bandeau, "closing_cta": "Pourquoi ?", "scenes": scenes}


def test_hook_is_prefixed_to_scene_one(capsys):
    brain = _brain("frais", FRAIS)
    brain.chosen_hook_text = "2 % de frais te coûtent 5 300 €."
    data = _frais_data("Imagine 5000 € pendant 20 ans. 2 % de frais te coûtent 5300 € !")
    brain.validate_script_specifics(data, "t")
    assert data["scenes"][0]["text"] == "2 % de frais te coûtent 5 300 €. Imagine 5 000 € pendant 20 ans."
    assert "cinq mille trois cents euros" in data["scenes"][0]["spoken"]         # texte parlé recalculé
    assert "Accroche ajoutée" in capsys.readouterr().out


@pytest.mark.parametrize("raw, expected", [
    ({"affirmation": "2 % DE FRAIS", "punchline": "5 300 € PERDUS"}, "2 % DE FRAIS | 5 300 € PERDUS"),
    (["2 % DE FRAIS", "5 300 € PERDUS"], "2 % DE FRAIS | 5 300 € PERDUS"),
    ("2 % de frais \u2013 5 300 € perdus", "2 % DE FRAIS | 5 300 € PERDUS"),
    ("2 % DE FRAIS : 5 300 € PERDUS", "2 % DE FRAIS | 5 300 € PERDUS"),
])
def test_malformed_bandeau_is_rebuilt(raw, expected):
    brain = _brain("frais", FRAIS)
    data = _frais_data("Les frais grignotent ton argent.", bandeau=raw)
    brain.validate_script_specifics(data, "t")
    assert data["on_screen_title"] == expected


def test_bandeau_impossible_to_rebuild_asks_the_llm():
    brain = _brain("frais", FRAIS)
    with pytest.raises(ValueError, match=r"AFFIRMATION \| PUNCHLINE"):
        brain.validate_script_specifics(_frais_data("x", bandeau="FRAIS"), "t")
