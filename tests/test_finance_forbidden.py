"""Capital Simple, partie 1.1 : aucun mot interdit dans ce qui est envoyé au LLM (consignes, exemples,
corrections) ; « acheter » autorisé (descriptif), l'ordre donné au spectateur interdit ; avertissement de fin fixe."""
import re

import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance import storyboard
from auracontent.channels.finance.brain import FinanceBrain, _fold_keep, contains_term

PARAMS = {
    "interets_composes": {"early_age": 20, "late_age": 40, "early_amount": 100, "late_amount_factor": 3, "rate": 7,
                          "end_age": 65},
    "inflation": {"amount": 1000, "inflation": 2, "years": 30},
    "cout_du_temps": {"monthly": 100, "rate": 5, "delay_years": 10, "horizon_years": 40},
    "frais": {"amount": 5000, "rate": 6, "fees": 2, "years": 20},
    "regle_72": {"rate": 4, "rate_b": 8},
}


class _Capture:
    """Faux LLM : garde chaque message envoyé et renvoie une réponse plausible."""

    def __init__(self):
        self.sent = []

    def call_json_with_retry(self, messages, **kw):
        self.sent += [m["content"] for m in messages]
        system = messages[0]["content"]
        if "accroches de vidéos" in system:
            return {"hooks": [{"text": "Le temps change tout le résultat.", "pattern": "chiffre", "score": 8}]}
        if "vérifies des accroches" in system:
            return {"rejets": []}
        if "choisis le sujet" in system:
            return {"choice": 1, "reason": "clair"}
        return {"ok": True, "problems": []}


def _brain(concept, llm=None):
    brain = BaseChannel("finance", FinanceBrain, llm).brain
    params = brain.resolve_params(concept, dict(PARAMS[concept]))
    brain.last_pick = {"concept": concept, "params": params, "topic_key": brain.topic_key(concept, params)}
    brain.config["brain"]["meaning_check"] = "llm"
    return brain


def _offending(brain, text: str) -> list[str]:
    found = [t for t in brain.all_forbidden() if contains_term(text, t)]
    found += [p for p in brain.style_cfg().get("hype_patterns") or [] if re.search(p, _fold_keep(text))]
    return found


@pytest.mark.parametrize("concept", list(PARAMS))
def test_nothing_sent_to_the_llm_contains_a_forbidden_word(concept):
    llm = _Capture()
    brain = _brain(concept, llm)
    topic = brain.describe(concept, brain.last_pick["params"])
    brain.generate_hook_variants(topic)                                     # accroches + vérification
    llm.sent += [m["content"] for m in brain.build_script_prompt(topic, 7, {"text": "h"})]
    scenes = [{"id": i, "text": "Le temps travaille.", "role": r, "template": t}
              for i, (r, t) in enumerate(storyboard.storyboard(concept), 1)]
    scenes[-1].update(text=brain.disclaimer_text(), fixed_text=True)
    brain.llm_meaning_issues({"scenes": scenes, "on_screen_title": "A | B", "title": "t", "closing_cta": "?"})
    other = _brain("frais", llm)
    other.config["brain"]["concept_selection"] = "llm"
    other.choose_candidate([("frais", other.last_pick["params"]), ("inflation", PARAMS["inflation"])])
    assert llm.sent
    for message in llm.sent:
        assert _offending(brain, message) == [], message[:300]


def test_corrections_sent_back_are_masked():
    brain = _brain("frais")
    feedback = "CORRECTIONS : la scène 3 dit « ouvre un livret A à la banque », « un conseil » ; « détruire »."
    sent = brain.build_script_prompt("t", 6, {"text": "h"}, correction_feedback=feedback)[1]["content"]
    assert _offending(brain, sent) == [] and "[terme interdit]" in sent and "[terme exagéré]" in sent


def test_rejection_messages_never_repeat_the_word():
    brain = _brain("frais")
    for term in brain.forbidden_terms():
        issues = brain.text_issues(f"Ici, {term} change tout.", "la scène 2")
        assert any("terme interdit" in i for i in issues)
        assert all(_offending(brain, i) == [] for i in issues), (term, issues)


def test_fixed_disclaimer_with_conseil_is_accepted():
    brain = _brain("frais")
    brain.config["brain"]["voice_words_per_second"] = 0
    assert "conseil" in brain.disclaimer_text()
    scenes = [{"id": i, "text": "Les frais grignotent ton argent chaque année.", "visual": ""}
              for i in range(1, len(storyboard.storyboard("frais")) + 1)]
    reveal = next(i for i, (r, _) in enumerate(storyboard.storyboard("frais")) if r == "reveal")
    scenes[reveal]["text"] = "Les frais te coûtent 5 300 €."
    scenes[-1]["text"] = "Fin."
    data = {"title": "Les frais", "on_screen_title": "2 % DE FRAIS | 5 300 € PERDUS", "closing_cta": "Pourquoi ?",
            "scenes": scenes}
    brain.validate_script_specifics(data, "t")
    assert data["scenes"][-1]["text"] == brain.disclaimer_text() and data["scenes"][-1]["fixed_text"]
    assert data["scenes"][-1]["spoken"]
    assert not [i for i in brain.check_script_logic("t", data) if "interdit" in i or "fin" in i]


@pytest.mark.parametrize("text, ok", [
    ("Ce que ton argent peut acheter baisse chaque année.", True),
    ("Tes 1 000 € achètent moins dans 30 ans.", True),
    ("Achète un appartement dès maintenant.", False),
    ("Investis ton argent chaque mois.", False),
    ("Place 100 € par mois.", False),
])
def test_acheter_allowed_orders_forbidden(text, ok):
    brain = _brain("inflation")
    issues = [i for i in brain.text_issues(text, "s") if "nombre non autorisé" not in i]
    assert (issues == []) is ok, issues


def test_forbidden_list_has_a_reason_for_each_term():
    brain = _brain("frais")
    reasons = {**brain.forbidden_terms(), **brain.cta_terms()}
    assert "achète" not in reasons and "banque" in reasons and "conseil" in reasons
    assert all(reason.strip() for reason in reasons.values())
