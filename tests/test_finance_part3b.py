"""Capital Simple, partie 3b : génération libre de sujets du quotidien (8 candidats, 2 domaines tirés au hasard,
3 exemples au plus, 1 candidat sur 8 repris des exemples au plus), fenêtres concept (3) et concept + situation
(30), comparaison des situations, concept imposé prioritaire, concepts du quotidien branchés dans le script."""
import copy
import json
import re

import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance import calc as fcalc
from auracontent.channels.finance import storyboard
from auracontent.channels.finance.brain import FinanceBrain, contains_term
from auracontent.services.publishing import state_sync

CAFE = {"situation": "Léa prend un café à 2,50 € chaque matin en allant au travail", "domaine": "alimentation",
        "concept": "petite dépense répétée",
        "calcul": {"type": "depenses_repetees", "params": {"amount": 2.5, "per_week": 5, "years": 10}},
        "question_spectateur": "Combien coûte ce café sur 10 ans ?"}


def _cand(situation, type_, params, domaine="logement", question="Combien ça coûte vraiment ?"):
    return {"situation": situation, "domaine": domaine, "concept": "mécanisme",
            "calcul": {"type": type_, "params": params}, "question_spectateur": question}


GOOD = [
    _cand("Hugo paie son loyer avec 3 jours de découvert de 300 € chaque mois", "decouvert_agios",
          {"overdraft": 300, "days": 3, "rate": 15}, "banque et paiements"),
    _cand("Léa emprunte 8 000 € sur 4 ans pour payer son permis et sa première voiture", "credit_amortissable",
          {"amount": 8000, "rate": 5, "years": 4}, "transport"),
    _cand("Hugo cumule une salle de sport, une appli de musique et un service de vidéo chaque mois",
          "abonnements", {"sub_1": 29.99, "sub_2": 10.99, "sub_3": 8.99, "years": 3}, "loisirs et vacances"),
]


class _LLM:
    """Faux LLM : candidats, verdict sur les paires douteuses, choix du sujet ; garde tout ce qui est envoyé."""

    def __init__(self, candidates, same=(), choice=1, fail=False):
        self.candidates, self.same, self.choice, self.fail = candidates, list(same), choice, fail
        self.sent = []

    def call_json_with_retry(self, messages, **kw):
        self.sent.append(messages)
        system = messages[0]["content"]
        if "proposes des sujets" in system:
            if self.fail:
                raise RuntimeError("quota")
            return {"candidats": copy.deepcopy(self.candidates)}
        if "compares des situations" in system:
            return {"memes": self.same}
        if "choisis le sujet de la prochaine" in system:
            return {"choice": self.choice, "reason": "clair"}
        return {"ok": True, "problems": []}

    def kinds(self):
        return [m[0]["content"].split(".")[0] for m in self.sent]


@pytest.fixture
def state(monkeypatch, tmp_path):
    from auracontent.utils import hook_tracker, pending_topic, topic_tracker

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(topic_tracker, "HISTORY_PATH", tmp_path / "global_history.json")
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hook_history.json")
    monkeypatch.setattr(pending_topic, "PENDING_PATH", tmp_path / "pending_topics.json")
    monkeypatch.delenv("FINANCE_CONCEPT", raising=False)
    monkeypatch.setenv("FINANCE_SEED", "1")
    return tmp_path


def _brain(llm=None):
    return BaseChannel("finance", FinanceBrain, llm).brain


def _done(brain, concept, situation="", status=None, params=None):
    from auracontent.utils.topic_tracker import save_global_history

    params = params or fcalc.check_params(concept, next(
        e["calcul"]["params"] for e in brain.free_cfg()["examples"] if e["calcul"]["type"] == concept))[0]
    meta = {"concept": concept, "category": concept, "params": params, "topic_key": brain.topic_key(concept, params)}
    if situation:
        meta.update(situation=situation, situation_keywords=sorted(brain.situation_keywords(situation)))
    save_global_history(situation or concept, "finance", status=status, **meta)


# ---------- Prompt ----------
def test_prompt_shows_at_most_three_examples_and_no_forbidden_word(state):
    brain = _brain(_LLM([]))
    messages, drawn = brain.candidates_messages(brain.run_rng())
    user = messages[1]["content"]
    block = user.split("EXEMPLES")[1].split("RÈGLES")[0]
    assert len(re.findall(r"'situation'", block)) == 3
    assert "8 sujets NOUVEAUX" in user and len(drawn) == 2 and all(d in user for d in drawn)
    for message in messages:
        assert not [t for t in brain.all_forbidden() if contains_term(message["content"], t)]


def test_two_seeds_draw_different_domains(state, monkeypatch):
    brain = _brain(_LLM([]))
    draws = set()
    for seed in ("1", "2", "3"):
        monkeypatch.setenv("FINANCE_SEED", seed)
        draws.add(tuple(brain.draw_domains(brain.run_rng())))
    assert len(draws) >= 2
    monkeypatch.setenv("FINANCE_SEED", "7")
    assert brain.draw_domains(brain.run_rng()) == brain.draw_domains(brain.run_rng())     # graine = même tirage


# ---------- Vérification des candidats ----------
@pytest.mark.parametrize("cand, reason", [
    (_cand("Un café", "depenses_repetees", {"amount": 2, "per_week": 5, "years": 10}), "pas de situation concrète"),
    (_cand("Les gens achètent souvent des choses en ligne le soir", "depenses_repetees",
           {"amount": 2, "per_week": 5, "years": 10}), "pas de situation concrète"),
    (_cand("Hugo hésite entre louer et acheter son appartement en ville", "loyer_vs_achat", {"rent": 800}),
     "non calculable : aucun calcul disponible"),
    (_cand("Hugo paie 500 € de découvert pendant 10 jours ce mois-ci", "decouvert_agios",
           {"overdraft": 500, "days": 10}), "non calculable : paramètre manquant"),
    (_cand("Hugo paie 500 € de découvert pendant 10 jours ce mois-ci", "decouvert_agios",
           {"overdraft": 500, "days": 10, "rate": 45}), "hors plage réaliste"),
    (_cand("Léa ouvre un Livret A pour y laisser 1 000 € pendant un an", "taux_reel",
           {"nominal": 3, "inflation": 2, "amount": 1000}), "terme interdit"),
    (_cand("Hugo paie ses courses en 4 fois avec Klarna à la caisse", "paiement_fractionne",
           {"price": 400, "installments": 4, "fee_pct": 2, "late_fee": 0}), "terme interdit"),
])
def test_bad_candidates_are_rejected_with_a_reason(state, cand, reason):
    pick, why = _brain(_LLM([])).check_candidate(cand)
    assert pick is None and reason in why


def test_valid_candidate_becomes_a_pick(state):
    pick, why = _brain(_LLM([])).check_candidate(CAFE)
    assert why == "" and pick["concept"] == "depenses_repetees" and pick["params"]["amount"] == 2.5
    assert pick["situation"] == CAFE["situation"] and pick["source"] == "libre" and "cafe" in pick["situation_keywords"]


def test_rejections_are_logged_and_a_valid_subject_is_chosen(state, capsys):
    bad = _cand("Hugo hésite entre louer et acheter son appartement en ville", "loyer_vs_achat", {"rent": 800})
    brain = _brain(_LLM([bad, *GOOD], choice=2))
    topic = brain.pick_topic()
    out = capsys.readouterr().out
    assert "✖ 1. Hugo hésite entre louer" in out and "non calculable : aucun calcul disponible" in out
    assert out.count("✔ ") == 3 and "Sujet retenu par le LLM" in out
    assert brain.last_pick["concept"] == "credit_amortissable" and "permis" in topic


# ---------- Quota d'exemples ----------
def test_at_most_one_candidate_from_the_examples(state, capsys):
    examples = [_cand(e["situation"], e["calcul"]["type"], e["calcul"]["params"],
                      question=e["question_spectateur"]) for e in _brain().free_cfg()["examples"][:3]]
    brain = _brain(_LLM([*examples, *GOOD]))
    assert brain.free_pick() is not None
    out = capsys.readouterr().out
    assert out.count("(repris d'un exemple)") == 1 and out.count("quota de 1 atteint") == 2


# ---------- Fenêtres et comparaison des situations ----------
def test_same_scene_with_other_words_is_the_same_situation(state):
    brain = _brain()
    a = brain.situation_keywords("Léa prend un café chaque matin")
    b = brain.situation_keywords("Hugo boit un expresso tous les jours au bureau")
    c = brain.situation_keywords("Léa déjeune au restaurant le midi avec ses collègues")
    assert brain.same_situation(a, b) is True and brain.same_situation(a, c) is False


def test_concept_window_rejects_a_recent_concept(state, capsys):
    brain = _brain(_LLM([CAFE, *GOOD]))
    _done(brain, "depenses_repetees", "Hugo achète un sandwich tous les midis")
    _done(brain, "taux_reel")
    _done(brain, "carte_fidelite")                                  # depenses_repetees : il y a 3 vidéos
    brain.free_pick()
    assert "concept « depenses_repetees » traité il y a 3 vidéo(s) (fenêtre de 3)" in capsys.readouterr().out


def test_situation_window_rejects_same_concept_and_situation(state, capsys):
    brain = _brain(_LLM([CAFE, *GOOD]))
    _done(brain, "depenses_repetees", "Hugo boit un expresso tous les jours au bureau")
    for concept in ("taux_reel", "carte_fidelite", "epargne_age"):           # hors fenêtre des concepts
        _done(brain, concept)
    brain.free_pick()
    assert "même situation et même concept" in capsys.readouterr().out


def test_same_situation_with_another_concept_is_allowed(state, capsys):
    cafe_card = _cand("Léa prend un café chaque matin et cumule des points sur sa carte du café",
                      "carte_fidelite", {"spend": 100, "pct": 10}, "alimentation")
    brain = _brain(_LLM([cafe_card]))
    _done(brain, "depenses_repetees", "Léa prend un café chaque matin avant le travail")
    for concept in ("taux_reel", "epargne_age", "abonnements"):
        _done(brain, concept)
    assert brain.free_pick()["concept"] == "carte_fidelite"


def test_doubtful_pair_is_settled_by_one_llm_call(state, capsys):
    near = _cand("Hugo prend un café au distributeur de la gare chaque matin avant le train",
                 "depenses_repetees", {"amount": 1.5, "per_week": 5, "years": 10}, "transport")
    llm = _LLM([near, GOOD[0]], same=[1])
    brain = _brain(llm)
    _done(brain, "depenses_repetees", "Léa achète un croissant à la boulangerie de la gare le matin")
    for concept in ("taux_reel", "epargne_age", "abonnements"):
        _done(brain, concept)
    kw = brain.situation_keywords(near["situation"])
    old = brain.situation_keywords("Léa achète un croissant à la boulangerie de la gare le matin")
    assert brain.same_situation(kw, old) is None                       # doute : ni même ni différente
    pick = brain.free_pick()
    assert sum("compares des situations" in m[0]["content"] for m in llm.sent) == 1
    assert pick["concept"] == "decouvert_agios" and "vérifié par le LLM" in capsys.readouterr().out


def test_abandoned_free_subject_stays_excluded(state, capsys):
    brain = _brain(_LLM([CAFE, *GOOD]))
    _done(brain, "depenses_repetees", "Léa prend un café chaque matin au travail", status="abandonné")
    brain.free_pick()
    assert "concept « depenses_repetees » abandonné il y a 1 vidéo(s)" in capsys.readouterr().out


# ---------- Concept imposé ----------
def test_forced_concept_has_priority(state, monkeypatch, capsys):
    monkeypatch.setenv("FINANCE_CONCEPT", "credit_amortissable")
    llm = _LLM([CAFE, *GOOD])
    brain = _brain(llm)
    _done(brain, "credit_amortissable", "Hugo emprunte pour un canapé")      # fenêtre ignorée : concept imposé
    brain.pick_topic()
    assert brain.last_pick["concept"] == "credit_amortissable"
    assert "SUJET IMPOSÉ" in llm.sent[0][1]["content"] and "au lieu du concept imposé" in capsys.readouterr().out


def test_forced_concept_falls_back_to_its_example(state, monkeypatch):
    monkeypatch.setenv("FINANCE_CONCEPT", "remises_successives")
    brain = _brain(_LLM([], fail=True))
    topic = brain.pick_topic()
    assert brain.last_pick["concept"] == "remises_successives" and "soldes" in topic


def test_unknown_forced_concept_stops_the_run(state, monkeypatch):
    monkeypatch.setenv("FINANCE_CONCEPT", "loyer_vs_achat")
    with pytest.raises(RuntimeError, match="Concept imposé inconnu"):
        _brain(_LLM([])).pick_topic()


def test_generation_failure_falls_back_to_yaml_concepts(state, capsys):
    brain = _brain(_LLM([], fail=True))
    brain.config["brain"]["concept_selection"] = "random"
    brain.pick_topic()
    assert brain.last_pick["concept"] in brain.config["brain"]["concepts"]
    assert "repli sur les concepts du YAML" in capsys.readouterr().out


# ---------- Concepts du quotidien dans le script ----------
def _daily(concept, raw, situation="Léa vit une situation concrète du quotidien en ville"):
    brain = _brain()
    params, why = fcalc.check_params(concept, raw)
    assert params, why
    brain.last_pick = {"concept": concept, "params": params, "topic_key": brain.topic_key(concept, params),
                       "situation": situation, "question": "Combien ça coûte ?", "source": "libre"}
    return brain


def test_daily_concept_builds_a_script_prompt_with_its_numbers():
    brain = _daily("epargne_age", {"monthly": 50, "rate": 5, "age_a": 20, "age_b": 35, "end_age": 65})
    user = brain.build_script_prompt("t", 6, {"text": "h"})[1]["content"]
    assert "97 997 €" in user and "versement mensuel (€) : 50" in user
    hyp = brain.hypothesis("epargne_age", brain.last_pick["params"])
    assert "jusqu'à 65 ans" in hyp and "taux mensuel équivalent" in hyp
    assert storyboard.storyboard("epargne_age") == storyboard.DAILY and brain.target_scene_count() == 6
    assert brain.param_unit("monthly") == "€/mois" and brain.param_unit("age_a") == "âge"


def test_split_payment_rate_only_when_explained():
    brain = _daily("paiement_fractionne", {"price": 400, "installments": 4, "fee_pct": 2.2, "late_fee": 0})
    assert brain.text_issues("Ces 8,80 € de frais, c'est comme un crédit à 19,1 % par an.", "s") == []
    issues = brain.text_issues("Le taux grimpe à 19,1 %.", "la scène 3")
    assert issues and "sans l'expliquer" in issues[0] and "8,80 €" not in issues[0]
    assert "coût en euros" in brain._pick()[2]["idea"]


def test_free_subject_survives_a_restart(state):
    brain = _daily("decouvert_agios", {"overdraft": 500, "days": 10, "rate": 16})
    state_ = json.loads(json.dumps(brain.export_state()))
    other = _brain()
    other.restore_state(state_)
    assert other.last_pick["situation"] == brain.last_pick["situation"]
    state_["last_pick"]["params"]["rate"] = 99
    with pytest.raises(ValueError, match="plus calculable"):
        other.restore_state(state_)


def test_describe_uses_the_situation():
    brain = _daily("abonnements", {"sub_1": 10, "years": 3}, "Hugo garde trois abonnements qu'il n'utilise plus")
    assert brain.describe("abonnements", brain.last_pick["params"], brain.last_pick["situation"]) == \
        "Abonnements cumulés : Hugo garde trois abonnements qu'il n'utilise plus"


# ---------- Exemple d'accroche propre à chaque calcul ; règle « perdre » du taux réel et du salaire ----------
@pytest.mark.parametrize("concept", ["depenses_repetees", "abonnements", "remises_successives", "paiement_fractionne",
                                     "credit_amortissable", "decouvert_agios", "forfait_appareil", "carte_fidelite",
                                     "epargne_age", "salaire_vs_prix", "taux_reel", "leasing_epargne"])
def test_each_daily_concept_has_a_valid_hook_example(concept):
    from tests.test_finance_part3a import NEW

    raw = NEW.get(concept, {"monthly": 300, "years": 4, "rate": 3})
    brain = _daily(concept, raw)
    example = brain.hook_example()
    assert example != "Mettre moins d'argent… et finir avec plus." and "{" not in example
    assert brain.hook_issues(example, "sujet") == []


@pytest.mark.parametrize("concept, raw, bad, good", [
    ("taux_reel", {"nominal": 3, "inflation": 2, "amount": 1000},
     "Avec ce livret, tu perds 1 %.", "En pouvoir d'achat, tu gagnes 0,98 %."),
    ("salaire_vs_prix", {"salary": 2000, "raise_pct": 2, "inflation": 4},
     "Tu perds 38 € par mois.", "Tu perds 1,9 % de pouvoir d'achat."),
])
def test_loss_rule_for_real_rate_and_salary(concept, raw, bad, good):
    brain = _daily(concept, raw)
    issues = brain.text_issues(bad, "la scène 3")
    assert any("dit que l'argent se perd" in i and f"« {bad} »" in i for i in issues), issues
    assert brain.text_issues(good, "la scène 3") == []
    assert "INTERDIT" in brain.wording() and "AUTORISÉ" in brain.wording()
