"""Capital Simple, partie 2 : variété des sujets (fenêtre anti-répétition au niveau du concept, sujets
abandonnés inscrits à l'historique, même concept avec d'autres chiffres = même sujet, journal du choix)."""
import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance.brain import FinanceBrain
from auracontent.services.publishing import state_sync

ALL = ["interets_composes", "inflation", "cout_du_temps", "frais", "regle_72"]


@pytest.fixture
def state(monkeypatch, tmp_path):
    from auracontent.utils import hook_tracker, pending_topic, topic_tracker

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(topic_tracker, "HISTORY_PATH", tmp_path / "global_history.json")
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hook_history.json")
    monkeypatch.setattr(pending_topic, "PENDING_PATH", tmp_path / "pending_topics.json")
    return tmp_path


def _brain(window=None):
    brain = BaseChannel("finance", FinanceBrain, None).brain
    brain.config["brain"]["concept_selection"] = "random"
    if window is not None:
        brain.config["brain"]["concept_window"] = window
    return brain


def _done(brain, concept, status=None, **params):
    from auracontent.utils.topic_tracker import save_global_history

    params = params or brain.combinations(concept)[0]
    save_global_history(brain.describe(concept, params), "finance", concept=concept, category=concept,
                        params=params, topic_key=brain.topic_key(concept, params), status=status)


def _concepts(brain):
    return sorted(c for c, _ in brain.topic_candidates())


def test_default_windows(state):
    brain = _brain()
    assert brain.concept_window() == 3 and brain.situation_window() == 30


def test_window_is_respected(state):
    brain = _brain()
    for concept in ("inflation", "frais", "regle_72"):
        _done(brain, concept)
    assert _concepts(brain) == ["cout_du_temps", "interets_composes"]
    assert _concepts(_brain(window=1)) == sorted(set(ALL) - {"regle_72"})


def test_concept_older_than_the_window_comes_back(state):
    brain = _brain(window=3)
    for i, concept in enumerate(("inflation", "frais", "regle_72", "frais")):    # inflation : il y a 4 vidéos
        _done(brain, concept, **brain.combinations(concept)[i])
    assert "inflation" in _concepts(brain) and "frais" not in _concepts(brain)


def _concepts_done(state):
    import json

    path = state / "finance" / "global_history.json"
    return json.loads(path.read_text()) if path.exists() else []


def test_same_concept_with_other_numbers_is_rejected(state, capsys):
    brain = _brain()
    _done(brain, "inflation", amount=1000, inflation=2, years=30)
    fresh = brain.resolve_params("inflation", {"amount": 10000, "inflation": 3, "years": 30})
    used = {e["topic_key"] for e in _concepts_done(state)}
    assert fresh in brain.combinations("inflation") and brain.topic_key("inflation", fresh) not in used
    assert "inflation" not in _concepts(brain)                          # 10 000 € / 30 ans / 3 % aussi
    assert "inflation : écarté, traité il y a 1 vidéo(s) (même concept, chiffres différents" in capsys.readouterr().out


def test_abandoned_subject_is_excluded_for_the_window(state, capsys):
    brain = _brain()
    brain.last_pick = {"concept": "inflation", "params": brain.combinations("inflation")[0]}
    brain.on_topic_abandoned("Inflation : 10 000 €", "3 échec(s) du script", brain.last_pick)
    entries = _concepts_done(state)
    assert entries[-1]["status"] == "abandonné" and entries[-1]["concept"] == "inflation"
    assert "inflation" not in _concepts(brain)
    assert "inflation : écarté, abandonné il y a 1 vidéo(s)" in capsys.readouterr().out


def test_abandoned_subject_leaves_the_window_after_ten_videos(state):
    brain = _brain(window=2)
    _done(brain, "inflation", status="abandonné")
    _done(brain, "frais")
    assert "inflation" not in _concepts(brain)                          # abandonné depuis la 1re vidéo
    _done(brain, "regle_72", **brain.combinations("regle_72")[0])
    _done(brain, "regle_72", **brain.combinations("regle_72")[1])
    assert "inflation" in _concepts(brain)                              # 2 vidéos produites depuis


def test_abandoned_numbers_never_come_back(state):
    brain = _brain(window=0)
    params = brain.combinations("inflation")[0]
    _done(brain, "inflation", status="abandonné", **params)
    for _ in range(20):
        assert all(p != params for c, p in brain.topic_candidates() if c == "inflation")


def test_all_concepts_in_window_least_recent_comes_back(state, capsys):
    brain = _brain(window=10)
    for concept in ALL:
        _done(brain, concept)
    _done(brain, "interets_composes", status="abandonné")
    assert _concepts(brain) == ["inflation"]          # interets_composes plus ancien, mais abandonné ensuite
    assert "est le moins récent et revient" in capsys.readouterr().out


def test_logs_list_candidates_rejections_and_choice(state, capsys):
    brain = _brain()
    _done(brain, "frais")
    brain.pick_topic()
    out = capsys.readouterr().out
    assert "🧾 Sujets candidats (fenêtre anti-répétition : 3 dernières vidéos)" in out
    assert "✖ frais : écarté" in out and out.count("✔ ") == 4 and "🧭 Sujet retenu : " in out


# ---------- Branchement dans le tronc commun (opt-in : mystery sans effet) ----------
def test_three_failures_record_the_abandoned_subject(state, monkeypatch):
    from auracontent.core.brain import global_brain as gbm
    from auracontent.utils import pending_topic as pt

    brain = _brain()
    brain.last_pick = {"concept": "frais", "params": brain.combinations("frais")[0]}
    pt.save_pending("finance", {"topic": "Frais", "hooks": [], "chosen_hook": {}, "brain": brain.export_state()})
    for _ in range(3):
        pt.note_script_attempt("finance")
    assert pt.load_pending("finance", max_attempts=3, on_abandon=gbm._pending_abandon_hook(brain)) is None
    assert _concepts_done(state)[-1]["status"] == "abandonné" and "frais" not in _concepts(brain)


def test_veracity_abandon_goes_through_the_hook(state):
    from auracontent.core.brain import global_brain as gbm

    brain = _brain()
    pick = {"concept": "regle_72", "params": brain.combinations("regle_72")[0]}
    gbm._notify_abandon(brain, "Règle des 72", "contrôle de véracité : x", pick)
    assert _concepts_done(state)[-1]["concept"] == "regle_72"


def test_mystery_has_no_abandon_hook():
    from auracontent.channels.mystery.brain import MysteryBrain
    from auracontent.core.brain import global_brain as gbm

    assert not hasattr(MysteryBrain, "on_topic_abandoned")
    assert gbm._pending_abandon_hook(object()) is None
