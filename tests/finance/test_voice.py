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
    generate = next(s for s in job["steps"] if s.get("name", "").startswith("🎬"))
    run = generate["run"]
    assert 'ACTIVE_GEMINI="$GEMINI_API_KEY_FINANCE"' in run and 'GEMINI_API_KEY="$ACTIVE_GEMINI"' in run
    assert "GEMINI_API_KEY_FINANCE absent" in run and "exit 1" in run          # jamais de repli sur la clé mystery
    assert "--upload --sync-state" in run                                      # Hugging Face, pas de publication
    assert not any("publish" in s.get("run", "") for s in job["steps"])


def _workflow():
    from pathlib import Path

    import yaml

    return yaml.safe_load(Path(".github/workflows/generator_video.yml").read_text(encoding="utf-8"))


def _gh_eval(expr: str, ctx: dict):
    """Évalue une expression GitHub Actions simple (||, &&, !, ==, !=, chaînes, true/false, contextes pointés),
    pour vérifier les conditions RÉELLES du workflow ; un contexte absent vaut None (comme sur GitHub)."""
    import re

    body = expr.strip()
    if body.startswith("${{"):
        body = body[3:-2]
    body = " ".join(body.split())

    def lookup(path: str):
        cur = ctx
        for part in path.split("."):
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur

    names = {}

    def ident(m):
        word = m.group(0)
        if word in ("true", "false"):
            return "True" if word == "true" else "False"
        key = f"_v{len(names)}"
        names[key] = lookup(word)
        return key

    out, i = [], 0
    for m in re.finditer(r"'(?:[^']|'')*'", body):                 # chaînes protégées, le reste traduit
        code = body[i:m.start()]
        code = re.sub(r"[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*", ident, code)
        out.append(code.replace("||", " or ").replace("&&", " and ").replace("!=", " _NE_ ")
                   .replace("!", " not ").replace(" _NE_ ", " != "))
        out.append(repr(m.group(0)[1:-1].replace("''", "'")))
        i = m.end()
    code = body[i:]
    code = re.sub(r"[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*", ident, code)
    out.append(code.replace("||", " or ").replace("&&", " and ").replace("!=", " _NE_ ")
               .replace("!", " not ").replace(" _NE_ ", " != "))
    return eval("".join(out), {"__builtins__": {}}, names)      # noqa: S307 (expression du workflow du dépôt)


def _ctx(event, channel=None, archive_var=False, archive_box=None, upload_box=None, payload_channel=None):
    inputs = {}
    if event == "workflow_dispatch":                              # GitHub applique les valeurs par défaut
        inputs = {"channel": channel or "all", "mystery_archive": bool(archive_box),
                  "archive_upload": True if upload_box is None else upload_box}
    return {"github": {"event_name": event,
                       "event": {"inputs": {k: str(v).lower() if isinstance(v, bool) else v for k, v in inputs.items()}
                                 if inputs else None,
                                 "client_payload": {"channel": payload_channel} if payload_channel else None}},
            "inputs": inputs, "vars": {"MYSTERY_MODE": "archive" if archive_var else ""}}


@pytest.mark.parametrize("ctx, generate, direct", [
    # le cron : workflow_dispatch sans option
    (_ctx("workflow_dispatch"), True, False),
    (_ctx("workflow_dispatch", archive_var=True), True, True),
    # lancements manuels
    (_ctx("workflow_dispatch", "all", archive_box=True), True, True),
    (_ctx("workflow_dispatch", "mystery", archive_box=True), False, True),
    (_ctx("workflow_dispatch", "mystery", archive_var=True), True, False),      # ancien mode, en secours
    (_ctx("workflow_dispatch", "mystery"), True, False),
    (_ctx("workflow_dispatch", "finance", archive_var=True), True, False),
    (_ctx("workflow_dispatch", "finance", archive_box=True), True, False),
    # signal trigger-videos
    (_ctx("repository_dispatch"), True, False),
    (_ctx("repository_dispatch", archive_var=True), True, True),
    (_ctx("repository_dispatch", payload_channel="finance", archive_var=True), True, False),
])
def test_workflow_unique_lance_le_bon_moteur_pour_mystery(ctx, generate, direct):
    jobs = _workflow()["jobs"]
    assert bool(_gh_eval(jobs["generate"]["if"], ctx)) is generate
    assert bool(_gh_eval(jobs["direct"]["if"], ctx)) is direct
    if direct and generate:                                       # les deux tournent : generate saute mystery
        assert _gh_eval(jobs["generate"]["env"]["MYSTERY_MODE"], ctx) == "archive"


@pytest.mark.parametrize("ctx, upload", [
    (_ctx("workflow_dispatch", archive_var=True), True),                       # le cron dépose toujours
    (_ctx("repository_dispatch", archive_var=True), True),
    (_ctx("workflow_dispatch", "mystery", archive_box=True, upload_box=False), False),   # essai manuel
    (_ctx("workflow_dispatch", "mystery", archive_box=True, upload_box=True), True),
])
def test_short_d_archives_depose_sauf_essai_manuel(ctx, upload):
    step = next(s for s in _workflow()["jobs"]["direct"]["steps"] if s.get("name") == "Déposer sur Hugging Face")
    assert bool(_gh_eval(step["if"], ctx)) is upload


def test_archive_mode_hands_mystery_to_the_director():
    from pathlib import Path

    wf = _workflow()
    assert not Path(".github/workflows/director.yml").exists()                # un seul workflow pour le cron
    assert "trigger-videos" in wf[True]["repository_dispatch"]["types"]        # `on:` lu comme True par PyYAML
    gen, direct = wf["jobs"]["generate"], wf["jobs"]["direct"]
    run = next(s for s in gen["steps"] if s.get("name", "").startswith("🎬"))["run"]
    assert "vars.MYSTERY_MODE" in gen["env"]["MYSTERY_MODE"]
    assert '"$MYSTERY_MODE" = "archive"' in run and 'CHANNELS="finance"' in run
    assert gen["concurrency"]["group"] != direct["concurrency"]["group"]      # le Réalisateur (75 min) ne bloque pas
    assert "concurrency" not in wf                                             # pas de file commune aux deux tâches


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


# ---------- Run 2 du 15/11 : accroche fautive du sujet inflation en attente ----------
def test_pending_inflation_hook_is_regenerated_before_resume(tmp_path, monkeypatch):
    from auracontent.core.brain import global_brain as gbm
    from auracontent.services.publishing import state_sync
    from auracontent.utils import pending_topic as pt

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(pt, "PENDING_PATH", tmp_path / "pending_topics.json")
    state_sync.is_isolated.cache_clear()
    params = {"amount": 10000, "inflation": 3, "years": 30}
    pick = {"category": "inflation", "concept": "inflation", "params": params,
            "topic_key": "inflation:amount=10000,inflation=3,years=30"}
    topic = "Inflation : 10000 € qui dorment pendant 30 ans avec 3 % d'inflation par an"
    bad = {"text": "Dormir ton argent, c\\u2019est perdre 5 880 € en 30 ans.", "pattern": "chiffre", "score": 9}
    pt.save_pending("finance", {"topic": topic, "hooks": [bad], "chosen_hook": bad, "brain": {"last_pick": pick}})

    gb = gbm.GlobalBrain(llm_client=None)
    brain = gb.channels["finance"].brain
    good = {"text": "Tes 10 000 € achètent moins chaque année.", "pattern": "chiffre", "score": 8}
    monkeypatch.setattr(brain, "generate_hook_variants", lambda t, **k: [good])
    monkeypatch.setattr(brain, "pick_topic", lambda: (_ for _ in ()).throw(AssertionError("même sujet gardé")))
    monkeypatch.setattr(gbm, "compute_pattern_scores", lambda *a: {})
    monkeypatch.setattr(gbm, "load_hook_history", lambda c: [])
    got_topic, _, chosen = gb._topic_and_hook("finance", gb.channels["finance"], brain, brain.config["brain"], True, [])
    assert got_topic == topic and chosen["text"] == good["text"]
    assert pt.load_pending("finance")["chosen_hook"]["text"] == good["text"]


def test_valid_pending_hook_is_kept(tmp_path, monkeypatch):
    from auracontent.channels.base_channel import BaseChannel
    from auracontent.channels.finance.brain import FinanceBrain

    brain = BaseChannel("finance", FinanceBrain, None).brain
    brain.last_pick = {"concept": "inflation", "params": {"amount": 10000, "inflation": 3, "years": 30}}
    assert brain.pending_hook_issues("Tu perds 5 880 € de pouvoir d'achat en 30 ans.", "t") == []
    assert brain.pending_hook_issues("Dormir ton argent, c'est perdre 5 880 € en 30 ans.", "t")
