"""Chaîne finance, phase 2bis : exagération, sens des chiffres, storyboard fixé par le code, taux plafonnés."""
import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance import storyboard
from auracontent.channels.finance.brain import FinanceBrain

COUT = {"monthly": 50, "rate": 4, "delay_years": 10, "horizon_years": 40}
LEA = {"early_age": 20, "late_age": 40, "early_amount": 100, "late_amount_factor": 3, "rate": 7, "end_age": 65}


def _picked(concept, params, llm=None):
    brain = BaseChannel("finance", FinanceBrain, llm).brain
    resolved = brain.resolve_params(concept, params)
    brain.last_pick = {"concept": concept, "params": resolved, "topic_key": brain.topic_key(concept, resolved)}
    return brain


# ---------- 1. Exagération ----------
@pytest.mark.parametrize("text", [
    "Seulement 2 % de frais peuvent détruire toute ta richesse.",
    "Tu perds une fortune sans le savoir.",
    "Ces frais peuvent te ruiner.",
    "Attendre, c'est tout perdre.",
    "Un raccourci magique pour doubler.",
    "La différence est énorme.",
])
def test_hype_is_rejected(text):
    brain = _picked("frais", {"amount": 5000, "rate": 6, "fees": 2, "years": 20})
    assert any("exagère" in i for i in brain.hook_issues(text, "sujet"))


def test_measured_hook_passes():
    brain = _picked("frais", {"amount": 5000, "rate": 6, "fees": 2, "years": 20})
    assert brain.hook_issues("2 % de frais par an te coûtent 5 300 € sur 20 ans.", "sujet") == []


# ---------- 2. Coût du temps : écart de versements ----------
def test_cout_du_temps_hook_example_is_valid():
    brain = _picked("cout_du_temps", COUT)
    example = brain.hook_example()
    assert example == "Verser 6 000 € de plus rapporte 23 800 € de plus."
    assert brain.hook_issues(example, "sujet") == []


def _script(reveal: str, concept="cout_du_temps"):
    scenes = [{"id": i, "text": "Le temps travaille pour toi.", "visual": "", "mood": "calm",
               "pause_after_ms": 300, "role": role, "template": template}
              for i, (role, template) in enumerate(storyboard.storyboard(concept), 1)]
    next(s for s in scenes if s["role"] == "reveal")["text"] = reveal
    scenes[-1]["text"] = "C'est un exemple simplifié."
    return {"title": "Le coût du temps", "on_screen_title": "ATTENDRE 10 ANS | COÛTE 23 800 €",
            "closing_cta": "Tu as commencé à quel âge ?", "scenes": scenes}


def test_cout_du_temps_reveal_must_say_paid_gap():
    brain = _picked("cout_du_temps", COUT)
    issues = brain.check_script_logic("t", _script("Attendre 10 ans te coûte 23 800 €."))
    assert any("versements en plus" in i and "6 000 €" in i for i in issues)
    ok = "Verser 6 000 € de plus rapporte 23 800 € de plus."
    assert brain.check_script_logic("t", _script(ok)) == []


# ---------- 3. Taux plafonnés à 8 % ----------
def test_all_rates_capped_at_8():
    brain = BaseChannel("finance", FinanceBrain, None).brain
    assert brain.config["brain"]["concepts"]["regle_72"]["params"]["rate"] == [2, 3, 4, 6, 8]
    for concept in brain.config["brain"]["concepts"]:
        assert all(p.get("rate", 0) <= 8 and p.get("rate_b", 0) <= 8 for p in brain.combinations(concept))
    brain.config["brain"]["concepts"]["regle_72"]["params"]["rate_b"] = [8, 9, 12]  # même si le YAML dérape
    assert {p["rate_b"] for p in brain.combinations("regle_72")} == {8}


# ---------- 4. Sens des chiffres : contrôle par le code ----------
@pytest.mark.parametrize("text, expected", [
    ("Mettre 50 € aujourd'hui te donne 58 100 € plus tard.", "versement mensuel"),
    ("Tu mets 58 100 € par mois de côté.", "n'est pas mensuel"),
    ("Attendre te coûte 23 800 % de ton résultat.", "ne correspond à rien"),
    ("Tu attends 41 ans avant de commencer.", "ne correspond à rien"),
])
def test_meaning_errors_are_caught(text, expected):
    brain = _picked("cout_du_temps", COUT)
    assert any(expected in i for i in brain.text_issues(text, "x")), brain.text_issues(text, "x")


@pytest.mark.parametrize("text", [
    "Tu verses 50 € par mois pendant 40 ans.",
    "Avec 50 euros chaque mois, à 4 % par an.",
    "Le résultat chute à 34 300 € au lieu de 58 100 €.",
    "Tu perds 41 % du résultat en attendant 10 ans.",
])
def test_meaning_correct_sentences_pass(text):
    assert _picked("cout_du_temps", COUT).text_issues(text, "x") == []


def test_ages_and_durations_both_read_as_ans():
    brain = _picked("interets_composes", LEA)
    assert brain.text_issues("Léa commence à 20 ans et place 45 ans.", "x") == []
    assert brain.text_issues("Léa a 2 100 € à 65 ans.", "x") == []


# ---------- 4. Sens des chiffres : vérification par le LLM ----------
class _Verifier:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def call_json_with_retry(self, messages, **kw):
        self.prompts.append(messages[1]["content"])
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


GOOD = "Verser 6 000 € de plus rapporte 23 800 € de plus."


def test_llm_meaning_check_receives_table_and_accepts():
    llm = _Verifier({"ok": True, "problems": []})
    brain = _picked("cout_du_temps", COUT, llm)
    assert brain.check_script_logic("t", _script(GOOD)) == []
    assert "coût de l'attente : 23 800 €" in llm.prompts[0] and "versement mensuel (€) : 50 €/mois" in llm.prompts[0]


@pytest.mark.parametrize("answer, expected", [
    ({"ok": False, "problems": [{"ou": "Scène 5", "motif": "le total versé est présenté comme un gain"}]},
     "total versé"),
    ({"ok": False}, "sans motif"),
    (RuntimeError("quota"), "impossible"),
])
def test_llm_meaning_check_rejects(answer, expected):
    brain = _picked("cout_du_temps", COUT, _Verifier(answer))
    assert any(expected in i for i in brain.check_script_logic("t", _script(GOOD)))


def test_llm_meaning_check_skipped_when_code_already_rejects():
    llm = _Verifier({"ok": True, "problems": []})
    brain = _picked("cout_du_temps", COUT, llm)
    assert brain.check_script_logic("t", _script("Attendre te coûte tout.")) and llm.prompts == []


# ---------- 5. Storyboard fixé par le code ----------
def test_every_concept_has_a_complete_storyboard():
    brain = BaseChannel("finance", FinanceBrain, None).brain
    for concept in brain.config["brain"]["concepts"]:
        board = storyboard.storyboard(concept)
        roles = [r for r, _ in board]
        assert roles.count("reveal") == 1 and roles[0] == "hook" and board[-1] == ("disclaimer", "carte_fin")
        assert all(t in storyboard.VARIANTS and r in storyboard.ROLES for r, t in board)


def test_apply_forces_roles_templates_and_known_variants():
    scenes = [{"text": "x", "visual": v, "role": "nimporte", "template": "nimporte"}
              for v in ("piles", "SABLIER", "une fusée", "ecart", "arbres", "jauge", "logo")]
    notes = storyboard.apply("interets_composes", scenes)
    assert [s["template"] for s in scenes] == [t for _, t in storyboard.storyboard("interets_composes")]
    assert [s["visual"] for s in scenes] == ["piles", "sablier", "barres", "ecart", "arbres", "jauge", "logo"]
    assert len(notes) == 1 and "une fusée" in notes[0]


def test_wrong_scene_count_is_corrected_by_llm():
    brain = _picked("frais", {"amount": 5000, "rate": 6, "fees": 2, "years": 20})
    data = _script("x", concept="frais")
    data["scenes"] = data["scenes"][:5]
    with pytest.raises(ValueError, match="exactement 6"):
        brain.validate_script_specifics(data, "t")


# ---------- Reprise d'un sujet en attente devenu invalide ----------
def test_restore_state_validates_pending_pick():
    brain = BaseChannel("finance", FinanceBrain, None).brain
    ok = {"concept": "regle_72", "params": {"rate": 6, "rate_b": 8}, "topic_key": "regle_72:rate=6,rate_b=8"}
    brain.restore_state({"last_pick": ok})
    assert brain.last_pick == ok
    with pytest.raises(ValueError, match="hors des combinaisons"):
        brain.restore_state({"last_pick": {"concept": "regle_72", "params": {"rate": 6, "rate_b": 12}}})  # > 8 %
    with pytest.raises(ValueError, match="absent"):
        brain.restore_state({"last_pick": {"concept": "crypto", "params": {}}})


def test_invalid_pending_topic_is_dropped_not_fatal(tmp_path, monkeypatch, capsys):
    from auracontent.core.brain import global_brain
    from auracontent.services.publishing import state_sync
    from auracontent.utils import hook_tracker, pending_topic, topic_tracker

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(topic_tracker, "HISTORY_PATH", tmp_path / "global_history.json")
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hook_history.json")
    monkeypatch.setattr(pending_topic, "PENDING_PATH", tmp_path / "pending_topics.json")
    pending_topic.save_pending("finance", {"topic": "vieux sujet", "hooks": [], "chosen_hook": {"text": "x"},
                                           "brain": {"last_pick": {"concept": "regle_72", "params": {"rate": 12}}}})
    gb = global_brain.GlobalBrain(llm_client=None)
    brain = gb.channels["finance"].brain
    brain.config["brain"]["concept_selection"] = "random"
    brain.generate_hook_variants = lambda topic, **k: [{"text": "Ton argent double plus vite qu'on croit.",
                                                        "pattern": "chiffre", "score": 8}]
    topic, _, _ = gb._topic_and_hook("finance", gb.channels["finance"], brain, brain.config["brain"], True, [])
    assert "Sujet en attente abandonné" in capsys.readouterr().out
    assert topic != "vieux sujet" and brain.last_pick["params"].get("rate", 0) <= 8


def test_script_retries_opt_in(monkeypatch):
    from auracontent.channels.registry import CHANNEL_REGISTRY

    seen = {}
    for name in ("mystery", "finance"):
        brain = BaseChannel(name, CHANNEL_REGISTRY[name], None).brain
        brain.last_pick = {"concept": "frais", "params": {}}
        monkeypatch.setattr(type(brain), "generate_script_with_target",
                            lambda self, topic, **k: seen.setdefault(self.channel_name, k["max_retries"]))
        brain.generate_script("sujet")
    assert seen == {"mystery": 2, "finance": 4}                  # mystery : comportement inchangé


# ---------- Storyboards propres à chaque concept ----------
def test_storyboards_differ_per_concept():
    lengths = {c: len(storyboard.storyboard(c)) for c in storyboard.STORYBOARDS}
    assert all(5 <= n <= 7 for n in lengths.values()) and len(set(lengths.values())) > 1
    roles_72 = [r for r, _ in storyboard.storyboard("regle_72")]
    assert "belief" not in roles_72 and {"reveal", "example"} <= set(roles_72)


R72 = {"rate": 4, "rate_b": 8}


def _r72(texts):
    scenes = [{"id": i, "text": t, "role": role, "template": tpl}
              for i, ((role, tpl), t) in enumerate(zip(storyboard.storyboard("regle_72"), texts, strict=True), 1)]
    return {"title": "La règle des 72", "on_screen_title": "RÈGLE DES 72 | 4 % : 18 ANS",
            "closing_cta": "Tu connaissais cette règle ?", "scenes": scenes}


GOOD_72 = ["À 4 % par an, ton argent double en 18 ans.", "C'est la règle des 72 : divise 72 par le taux.",
           "72 divisé par 4 = 18 ans.", "À 8 % par an, il double en 9 ans.",
           "La durée exacte à 4 % est de 17,7 ans.", "C'est une approximation, sur un exemple simplifié."]


def test_regle_72_two_examples_and_named_rule():
    brain = _picked("regle_72", R72)
    assert brain.check_script_logic("t", _r72(GOOD_72)) == []
    missing_b = [*GOOD_72[:3], "Avec un taux plus élevé, ça va plus vite.", *GOOD_72[4:]]
    assert any("deuxième exemple" in i and "9 ans" in i for i in brain.check_script_logic("t", _r72(missing_b)))
    unnamed = [GOOD_72[0], "Divise 72 par le taux.", *GOOD_72[2:]]
    assert any("règle des 72" in i for i in brain.check_script_logic("t", _r72(unnamed)))


def test_disclaimer_scene_has_no_number_and_reminds_example():
    brain = _picked("regle_72", R72)
    with_number = [*GOOD_72[:5], "Pour quadrupler, compte 36 ans."]
    issues = brain.check_script_logic("t", _r72(with_number))
    assert any("aucun nouveau chiffre" in i for i in issues) and any("exemple simplifié" in i for i in issues)


def test_closing_question_without_number():
    brain = _picked("regle_72", R72)
    data = _r72(GOOD_72)
    data["closing_cta"] = "Tu vises 8 % par an ?"
    assert any("question finale" in i for i in brain.check_script_logic("t", data))


# ---------- « multipliée par 24 » ----------
def test_par_n_fois_is_rejected():
    brain = _picked("interets_composes", LEA)
    assert any("sans « fois »" in i for i in brain.text_issues("Sa mise est multipliée par 21 fois.", "x"))
    assert brain.text_issues("Sa mise est multipliée par 21.", "x") == []
    assert brain.text_issues("Léa a 21 fois sa mise.", "x") == []


# ---------- Texte affiché et texte parlé ----------
def test_validate_builds_display_and_spoken_text():
    brain = _picked("regle_72", R72)
    data = _r72(["À 4 % par an, ton argent double en 18 ans.", "C'est la règle des 72.",
                 "72 divisé par 4 = 18 ans.", "À 8 % par an : 9 ans.", "Exactement 17.7 ans.",
                 "C'est un exemple simplifié."])
    brain.validate_script_specifics(data, "t")
    third, fifth = data["scenes"][2], data["scenes"][4]
    assert third["spoken"] == "soixante-douze divisé par quatre égale dix-huit ans."
    assert fifth["text"] == "Exactement 17,7 ans." and fifth["spoken"] == "Exactement dix-sept virgule sept ans."


def test_symbol_left_in_spoken_forces_regeneration():
    brain = _picked("regle_72", R72)
    data = _r72([*GOOD_72[:2], "72 / 4 & 18 ans.", *GOOD_72[3:]])
    with pytest.raises(ValueError, match="symbole"):
        brain.validate_script_specifics(data, "t")


def test_audio_reads_spoken_when_present():
    from auracontent.services.audios.audio import AudioEngine

    assert AudioEngine.voice_text({"text": "72 = 18", "spoken": "soixante-douze égale dix-huit"}) == \
        "soixante-douze égale dix-huit"
    assert AudioEngine.voice_text({"text": "Texte de mystery"}) == "Texte de mystery"   # sans `spoken` : inchangé
