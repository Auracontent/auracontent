"""Capital Simple, partie 1 (1.2 à 1.7) : fiabilité de la validation des scripts."""
import copy

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


# ---------- 1.5 / 1.6 Meilleur script gardé, réécriture ciblée, passe d'allongement ----------
class _Queue:
    """Faux LLM : renvoie les réponses dans l'ordre et garde les messages envoyés."""

    def __init__(self, *answers):
        self.answers, self.sent = list(answers), []

    def call_json_with_retry(self, messages, **kw):
        self.sent.append(messages)
        return copy.deepcopy(self.answers.pop(0))


FILLER = "Les frais grignotent ton argent chaque année."            # 7 mots, aucun chiffre


def _long_frais(brain, ratio=1.0):
    """Script de frais valide dont chaque scène vise `ratio` x sa longueur cible."""
    targets = brain.scene_word_targets()
    data = _frais_data("x")
    data["scenes"][0]["text"] = brain.chosen_hook_text
    for scene, target in zip(data["scenes"][1:-1], targets[1:-1], strict=True):
        base = scene["text"]
        n = max(1, round((target * ratio - brain.spoken_words({"text": base})) / 7))
        scene["text"] = " ".join([base] + [FILLER] * n) if n > 0 else base
    data["scenes"][-1]["text"] = "Fin."
    return data


def _near_short(brain):
    """Script court de 90 à 100 % du minimum de mots."""
    for r in (0.85, 0.83, 0.8, 0.78, 0.75):
        script = _long_frais(brain, ratio=r)
        issues = brain._checked("t", copy.deepcopy(script))
        if issues and 0.9 <= issues[0].ratio < 1:
            return script
    raise AssertionError("aucun script entre 90 et 100 % du minimum")


def _loop_brain(llm, retries=4):
    brain = _brain("frais", FRAIS, llm)
    brain.config["brain"].update(meaning_check="off", script_max_retries=retries, style_warnings="warn")
    brain.chosen_hook_text = "2 % de frais te coûtent 5 300 €."
    return brain


def _run(brain):
    return brain._generate_script_attempt("t", 6, {"text": brain.chosen_hook_text}, brain._brain()["script_max_retries"])


def test_only_failing_scene_is_sent_back():
    brain = _loop_brain(None)
    script = _long_frais(brain)
    good = script["scenes"][2]["text"]
    script["scenes"][2]["text"] = "Investis ton argent chaque mois. " + good
    brain.llm = llm = _Queue(script, {"scenes": [{"id": 3, "text": good}]})
    data = _run(brain)
    assert len(llm.sent) == 2
    user = llm.sent[1][1]["content"]
    assert "À RÉÉCRIRE" in user and "- Scène 3 :" in user and "- Scène 2 :" not in user
    assert "Investis" not in user.split("SCRIPT ACTUEL")[1]                  # formulation refusée masquée
    assert data["scenes"][2]["text"] == good and "unresolved_issues" not in data
    assert [s["text"] for s in data["scenes"][3:]] == [s["text"] for s in _run_checked(brain, script)[3:]]


def _run_checked(brain, script):
    clean = copy.deepcopy(script)
    clean["scenes"][2]["text"] = clean["scenes"][2]["text"].replace("Investis ton argent chaque mois. ", "")
    brain.validate_script_specifics(clean, "t")
    return clean["scenes"]


def test_best_script_is_kept_when_rewrite_is_worse():
    brain = _loop_brain(None, retries=1)
    script = _long_frais(brain)
    script["scenes"][2]["text"] = "Investis ton argent chaque mois. " + script["scenes"][2]["text"]
    worse = {"scenes": [{"id": 3, "text": "Investis 77 € par mois. Place 99 € par an. Tu vous perds."}]}
    brain.llm = _Queue(script, worse)
    data = _run(brain)
    assert data["scenes"][2]["text"].startswith("Investis ton argent")         # le meilleur (1 avertissement)
    assert len(data["unresolved_issues"]) == 2                     # terme interdit + ordre, pas les 5 du pire


def test_many_failing_scenes_regenerate_everything():
    brain = _loop_brain(None)
    script = _long_frais(brain)
    issues = [f"scène {i} : phrase de 20 mots (maximum 14)" for i in (1, 2, 3, 4)]
    assert brain.rewrite_plan(script, issues) is None
    assert brain.rewrite_plan(script, [*issues[:2], "le bandeau exagère"]) is not None
    assert brain.rewrite_plan(script, ["la narration doit nommer « x »"]) is None


def test_near_length_script_gets_one_lengthening_pass_then_is_accepted(capsys):
    brain = _loop_brain(None)
    script = _near_short(brain)
    brain.llm = llm = _Queue(script, {"scenes": []})                          # l'allongement échoue
    data = _run(brain)
    assert len(llm.sent) == 2 and "allonge à environ" in llm.sent[1][1]["content"]
    assert "accepté un peu court" in capsys.readouterr().out and data["unresolved_issues"]


def test_near_length_script_lengthened():
    brain = _loop_brain(None)
    short, full = _near_short(brain), _long_frais(brain)
    answer = {"scenes": [{"id": s["id"], "text": s["text"]} for s in full["scenes"][1:-1]]}
    brain.llm = _Queue(short, answer)
    data = _run(brain)
    assert "unresolved_issues" not in data and data["scenes"][1]["text"] == full["scenes"][1]["text"]


def test_too_short_script_is_regenerated_not_accepted():
    brain = _loop_brain(None, retries=0)
    script = _long_frais(brain, ratio=0.5)
    assert brain._checked("t", copy.deepcopy(script))[0].ratio < 0.9
    brain.llm = _Queue(script)
    assert "trop court" in _run(brain)["unresolved_issues"][0]
