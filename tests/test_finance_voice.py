"""Capital Simple : voix Edge seule (sans quota), jamais d'autre voix ; si la vidéo échoue, le sujet reste en
attente et n'entre pas dans l'historique (brain.history_after_video). mystery inchangée."""
import asyncio
import json
from typing import ClassVar

import pytest
from auracontent.channels.base_channel import load_channel_config
from auracontent.services.audios.audio import AudioEngine


def test_finance_voice_is_edge_only_same_voice():
    audio = load_channel_config("finance")["audio"]
    assert audio["engines"] == ["edge"]
    assert audio["edge"]["narrator"] == {"voice": "fr-FR-RemyMultilingualNeural", "rate": "-8%", "pitch": "+0Hz"}


def test_mystery_voice_unchanged():
    assert "gemini" in load_channel_config("mystery")["audio"]["engines"]


def test_edge_failure_fails_without_other_voice(tmp_path, monkeypatch):
    engine = AudioEngine(load_channel_config("finance")["audio"], output_dir=str(tmp_path))
    calls = []

    async def broken_edge(self, text, role, path):
        calls.append("edge")
        raise ConnectionError("Edge indisponible")

    async def forbidden(*a, **k):
        raise AssertionError("aucune autre voix")

    async def no_wait(s):
        pass

    monkeypatch.setattr(AudioEngine, "_edge", broken_edge)
    monkeypatch.setattr(AudioEngine, "_gemini", forbidden, raising=False)
    monkeypatch.setattr("auracontent.services.audios.audio.asyncio.sleep", no_wait)
    with pytest.raises(RuntimeError, match="Aucun moteur TTS"):
        asyncio.run(engine.process_script([{"id": 1, "text": "Bonjour.", "role": "hook"},
                                           {"id": 2, "text": "Suite.", "role": "context"}]))
    assert calls == ["edge"] * 3                                   # même voix, 3 essais, puis échec


# ---------- Le sujet reste en attente si la vidéo échoue ----------
class _GB:
    finalized: ClassVar[list] = []

    def __init__(self, path, deferred):
        self.path, self.deferred = path, deferred
        brain_cfg = {"history_after_video": True} if deferred else {}
        self.channels = {"finance": type("C", (), {"section": lambda s, k: brain_cfg if k == "brain" else {}})()}

    def run_channel(self, name, finalize=True):
        self.finalize_arg = finalize
        return self.path

    def finalize_channel(self, name, path):
        _GB.finalized.append(name)


@pytest.mark.parametrize("video_ok", [True, False])
def test_history_only_after_video(monkeypatch, tmp_path, video_ok):
    from auracontent.cli import generate

    _GB.finalized = []
    script = tmp_path / "s.json"
    script.write_text(json.dumps({"topic": "t"}), encoding="utf-8")
    gb = _GB(script, deferred=True)

    class LLM:
        def __init__(self):
            self.usage = {}

        @classmethod
        def create_default(cls):
            return cls()

        def usage_report(self):
            return []

    def video(*a, **k):
        if not video_ok:
            raise RuntimeError("Aucun moteur TTS disponible")

    monkeypatch.setattr(generate, "LLMClient", LLM)
    monkeypatch.setattr(generate, "GlobalBrain", lambda llm_client: gb)
    monkeypatch.setattr(generate, "produce_video", video)
    monkeypatch.setattr(generate, "channel_enabled", lambda n: True)
    attached = []
    monkeypatch.setattr(generate, "attach_script", lambda name, script: attached.append((name, script)))
    code = generate.main(["finance"])
    assert gb.finalize_arg is False                                   # pas d'historique avant la vidéo
    assert (_GB.finalized == ["finance"]) is video_ok and code == (0 if video_ok else 1)
    assert attached == ([] if video_ok else [("finance", {"topic": "t"})])      # script validé gardé


def test_finance_yaml_defers_history_mystery_does_not():
    assert load_channel_config("finance")["brain"]["history_after_video"] is True
    assert "history_after_video" not in load_channel_config("mystery")["brain"]


def test_finalize_channel_saves_history_and_clears_pending(tmp_path, monkeypatch):
    from auracontent.core.brain import global_brain as gbm

    saved = []
    monkeypatch.setattr(gbm, "save_global_history", lambda topic, ch, **k: saved.append((topic, ch, k.get("concept"))))
    cleared = []
    monkeypatch.setattr(gbm, "clear_pending", lambda ch: cleared.append(ch))
    g = gbm.GlobalBrain.__new__(gbm.GlobalBrain)
    g.channels = {"finance": type("C", (), {"brain": type("B", (), {"export_state": 1, "restore_state": 1})()})()}
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"topic": "Frais", "pick": {"concept": "frais"}}), encoding="utf-8")
    g.finalize_channel("finance", path)
    assert saved == [("Frais", "finance", "frais")] and cleared == ["finance"]


# ---------- Workflow : clé Gemini propre à finance, jamais celle de mystery ----------
def test_workflow_uses_finance_gemini_key_only_for_finance():
    from pathlib import Path

    import yaml

    wf = yaml.safe_load(Path(".github/workflows/generator_video.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["generate"]
    assert job["env"]["GEMINI_API_KEY_FINANCE"] == "${{ secrets.GEMINI_API_KEY_FINANCE }}"
    assert job["env"]["GEMINI_API_KEY"] == "${{ secrets.GEMINI_API_KEY }}"          # mystery inchangée
    names = [s.get("name", "") for s in job["steps"]]
    key_step = next(s for s in job["steps"] if "Clé Gemini" in s.get("name", ""))
    assert names.index(key_step["name"]) < next(i for i, n in enumerate(names) if "Diagnostic" in n)
    assert 'GEMINI_API_KEY=$GEMINI_API_KEY_FINANCE' in key_step["run"] and "exit 1" in key_step["run"]
    generate = next(s for s in job["steps"] if s.get("name", "").startswith("🎬"))
    assert "--upload --sync-state" in generate["run"]                    # Hugging Face, pas de publication
    assert not any("publish" in s.get("run", "") for s in job["steps"])


# ---------- Même voix réessayée 3 fois, jamais une autre ----------
def _engine(tmp_path, monkeypatch, outcomes, cfg=None):
    engine = AudioEngine(cfg or load_channel_config("finance")["audio"], output_dir=str(tmp_path))
    calls, sleeps = [], []

    async def edge(self, text, role, path):
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        path.write_bytes(b"x")

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(AudioEngine, "_edge", edge)
    monkeypatch.setattr("auracontent.services.audios.audio.audio_duration", lambda p: 2.0)
    monkeypatch.setattr("auracontent.services.audios.audio.asyncio.sleep", fake_sleep)
    return engine, calls, sleeps


def test_edge_is_retried_then_succeeds(tmp_path, monkeypatch):
    engine, calls, sleeps = _engine(tmp_path, monkeypatch, [ConnectionError("1"), ConnectionError("2"), "ok"])
    _path, used = asyncio.run(engine.generate("Bonjour.", "s1"))
    assert used == "edge" and len(calls) == 3 and len(sleeps) == 2 and all(3 <= s <= 5 for s in sleeps)


def test_edge_fails_after_three_tries(tmp_path, monkeypatch):
    engine, calls, _ = _engine(tmp_path, monkeypatch, [ConnectionError("x")] * 3)
    with pytest.raises(RuntimeError, match="Aucun moteur TTS"):
        asyncio.run(engine.generate("Bonjour.", "s1"))
    assert len(calls) == 3


def test_without_retries_option_single_try(tmp_path, monkeypatch):
    cfg = {"engines": ["edge"], "edge": {"narrator": {"voice": "fr-FR-HenriNeural"}}}
    engine, calls, sleeps = _engine(tmp_path, monkeypatch, [ConnectionError("x")], cfg)
    with pytest.raises(RuntimeError):
        asyncio.run(engine.generate("Bonjour.", "s1"))
    assert len(calls) == 1 and sleeps == []
    assert "retries" not in load_channel_config("mystery")["audio"]


# ---------- Script validé conservé quand la vidéo échoue ----------
def test_validated_script_is_reused_after_video_failure(tmp_path, monkeypatch):
    from auracontent.core.brain import global_brain as gbm
    from auracontent.services.publishing import state_sync
    from auracontent.utils import pending_topic as pt

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(pt, "PENDING_PATH", tmp_path / "pending_topics.json")
    state_sync.is_isolated.cache_clear()
    params = {"amount": 5000, "rate": 6, "fees": 2, "years": 20}
    pick = {"concept": "frais", "params": params, "topic_key": "frais:x"}
    pt.save_pending("finance", {"topic": "Frais", "hooks": [], "chosen_hook": {"text": "h"},
                                "brain": {"last_pick": pick}})
    script = {"topic": "Frais", "title": "Les frais", "scenes": [{"id": 1, "text": "x"}], "pick": pick}
    assert pt.attach_script("finance", script) == 1

    gb = gbm.GlobalBrain(llm_client=None)
    gb.output_dir = tmp_path / "scripts"
    brain = gb.channels["finance"].brain

    def forbidden(*a, **k):
        raise AssertionError("aucun nouveau script : le script validé est repris")

    monkeypatch.setattr(brain, "generate_script", forbidden)
    monkeypatch.setattr(brain, "generate_hook_variants", forbidden)
    monkeypatch.setattr(gbm.GlobalBrain, "_fetch_stats", staticmethod(lambda cfg: None))
    path = gb.run_channel("finance", finalize=False)
    assert json.loads(path.read_text(encoding="utf-8"))["title"] == "Les frais"
    assert pt.load_pending("finance")["script"]["title"] == "Les frais"       # gardé jusqu'à la vidéo réussie


def test_mystery_pending_never_carries_a_script(tmp_path, monkeypatch):
    from auracontent.utils import pending_topic as pt

    monkeypatch.setattr(pt, "PENDING_PATH", tmp_path / "pending.json")
    pt.save_pending("mystery", {"topic": "t", "hooks": [], "chosen_hook": {}, "brain": {}})
    assert "script" not in pt.load_pending("mystery")
