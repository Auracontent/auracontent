"""mystery : sujet abandonné sur le comptage des scènes, matière courte (4 scènes au moins), repli sans contrôle
du retournement, bascule au premier 429, motif de chaque titre rejeté."""
import pytest
from auracontent.channels.base_channel import load_channel_config
from auracontent.channels.mystery.brain import MysteryBrain
from auracontent.core.brain import base_brain
from auracontent.core.brain.base_brain import BaseBrain, SceneCountError, TopicRejected


def _mystery(llm=None) -> MysteryBrain:
    return MysteryBrain(config=load_channel_config("mystery"), llm=llm)


# ---------- 1. Comptage des scènes : sujet abandonné tout de suite ----------
class _WrongCountLLM:
    """Renvoie toujours 9 scènes, quelle que soit la cible."""

    def __init__(self):
        self.calls = 0

    def call_json_with_retry(self, messages, **kw):
        self.calls += 1
        return {"scenes": [{"id": i, "text": "Une phrase."} for i in range(1, 10)]}


def test_scene_count_failure_raises_scene_count_error(monkeypatch):
    monkeypatch.delenv("VIDEO_DURATION", raising=False)
    brain = _mystery(_WrongCountLLM())
    brain.build_script_prompt = lambda *a, **k: [{"role": "user", "content": "x"}]
    with pytest.raises(RuntimeError) as err:
        BaseBrain.generate_script_with_target(brain, "t", scene_count=5, max_retries=1)
    assert isinstance(err.value.__cause__, SceneCountError)


def test_mystery_abandons_topic_on_scene_count(monkeypatch):
    brain = _mystery()

    def fail(self, topic, **k):
        raise RuntimeError("Impossible de générer un script.") from SceneCountError("comptage")

    monkeypatch.setattr(BaseBrain, "generate_script_with_target", fail)
    monkeypatch.setattr(MysteryBrain, "target_scene_count", lambda self: 5)
    with pytest.raises(TopicRejected, match="nombre de scènes"):
        brain.generate_script("Opéra de Lyon")


@pytest.mark.parametrize("error", [RuntimeError("quota"), TopicRejected("fait absent de la source")])
def test_other_script_failures_unchanged(monkeypatch, error):
    brain = _mystery()

    def fail(self, topic, **k):
        raise error

    monkeypatch.setattr(BaseBrain, "generate_script_with_target", fail)
    monkeypatch.setattr(MysteryBrain, "target_scene_count", lambda self: 5)
    with pytest.raises(type(error)) as err:
        brain.generate_script("t")
    assert err.value is error                                       # le sujet reste repris s'il n'est pas rejeté


def test_scene_count_rejection_drops_pending_and_moves_on(monkeypatch, tmp_path):
    """Opéra de Lyon en attente : repris une fois, rejeté, plus jamais proposé ; le sujet suivant est traité."""
    from auracontent.core.brain import global_brain as gb
    from auracontent.utils import pending_topic as pt

    monkeypatch.setattr(pt, "PENDING_PATH", tmp_path / "pending.json")
    pt.save_pending("mystery", {"topic": "Opéra de Lyon", "hooks": [], "chosen_hook": {"text": "h"},
                                "brain": {"last_pick": {"source_title": "Opéra de Lyon", "anecdote_id": "42"}}})

    class Brain:
        last_pick: dict | None = None

        def pick_topic(self):
            self.last_pick = {"source_title": "Abbaye", "anecdote_id": "7"}
            return "Abbaye"

        def generate_hook_variants(self, topic, **k):
            return [{"text": "accroche", "pattern": "chiffre"}]

        def generate_script(self, topic, chosen_hook=None):
            if topic == "Opéra de Lyon":
                raise TopicRejected("nombre de scènes non tenu")
            return {"scenes": []}

        def export_state(self):
            return {}

        def restore_state(self, state):
            self.last_pick = dict(state.get("last_pick") or {})

    class Channel:
        brain = Brain()

        def section(self, key):
            return {"brain": {"veracity_topic_rounds": 3}}.get(key, {})

    g = gb.GlobalBrain.__new__(gb.GlobalBrain)
    g.channels, g.output_dir = {"mystery": Channel()}, tmp_path
    monkeypatch.setattr(gb, "save_global_history", lambda *a, **k: None)
    monkeypatch.setattr(gb, "compute_pattern_scores", lambda *a: {})
    monkeypatch.setattr(gb, "load_hook_history", lambda c: [])
    path = g.run_channel("mystery", previous_stats_list=[])
    assert '"topic": "Abbaye"' in path.read_text(encoding="utf-8")
    titles, ids = pt.load_rejected("mystery")
    assert titles == {"opéra de lyon"} and ids == {"42"}
    assert pt.load_pending("mystery") is None


def test_base_brain_exports_scene_count_error():
    assert issubclass(base_brain.SceneCountError, ValueError)        # même traitement qu'avant pour les autres


# ---------- 2. Matière courte : 4 scènes au moins ----------
def test_short_material_never_below_four_scenes(monkeypatch):
    monkeypatch.delenv("VIDEO_DURATION", raising=False)
    brain = _mystery()
    assert brain.min_scenes() == 4
    brain._source = {"facts": ["f"] * 4}
    assert brain.target_scene_count() == 4
    brain._source = {"facts": ["f"] * 9}
    assert brain.target_scene_count() > 4


class _Facts:
    def __init__(self, n):
        self.n = n

    def call_json_with_retry(self, messages, **kw):
        return {"faits": [f"fait {i}" for i in range(self.n)], "reponse": "Parce que."}


def test_too_few_facts_for_four_scenes_rejects_before_script(capsys):
    trial = {"source": {"title": "Opéra de Lyon", "extract": "x"}, "focus": ["Opéra"]}
    brain = _mystery(_Facts(3))
    brain.config["brain"]["min_facts"] = 2                         # même avec un min_facts plus bas
    assert brain.extract_facts(dict(trial), "t") is False
    assert "4 scènes au moins" in capsys.readouterr().out
    assert _mystery(_Facts(4)).extract_facts(dict(trial), "t") is True


def test_tolerance_never_goes_below_floor():
    brain = _mystery()
    data = {"scenes": [{"id": i, "text": "x"} for i in range(1, 4)], "closing_cta": "?"}
    with pytest.raises(SceneCountError, match="au moins 4"):
        brain.validate_script_specifics(data, "t")
