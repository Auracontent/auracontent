"""`enabled: false` : une chaîne coupée ne tourne jamais en CI (generate, publish) ; mystery inchangée."""
from typing import ClassVar

import pytest
from auracontent.channels.base_channel import channel_enabled
from auracontent.cli import generate, publish


def test_mystery_enabled_finance_disabled():
    assert channel_enabled("mystery") is True          # pas de clé `enabled` : comportement inchangé
    assert channel_enabled("finance") is False


class _Recorder:
    """Remplace LLMClient et GlobalBrain : enregistre les chaînes réellement lancées."""

    ran: ClassVar[list] = []

    def __init__(self, *a, **k):
        self.channels = {}

    @classmethod
    def create_default(cls):
        return cls()

    def run_channel(self, name):
        _Recorder.ran.append(name)
        return "script.json"

    def usage_report(self):
        return []


@pytest.fixture
def recorder(monkeypatch):
    _Recorder.ran = []
    synced = []
    monkeypatch.setattr(generate, "LLMClient", _Recorder)
    monkeypatch.setattr(generate, "GlobalBrain", _Recorder)
    monkeypatch.setattr(generate, "pull_state", lambda channels: synced.append(("pull", list(channels))))
    monkeypatch.setattr(generate, "push_state", lambda *a, channels: synced.append(("push", list(channels))))
    return synced


def test_generate_skips_disabled_channel(recorder, capsys):
    assert generate.main(["finance", "--upload", "--sync-state"]) == 0
    assert _Recorder.ran == [] and recorder == []      # ni LLM, ni historique Hugging Face
    assert "désactivée" in capsys.readouterr().out


def test_generate_without_argument_runs_only_enabled(recorder):
    assert generate.main(["--script-only", "--sync-state"]) == 0
    assert _Recorder.ran == ["mystery"]
    assert recorder == [("pull", ["mystery"]), ("push", ["mystery"])]


def test_generate_mystery_unchanged(recorder):
    assert generate.main(["mystery", "--script-only"]) == 0
    assert _Recorder.ran == ["mystery"]


def test_allow_disabled_is_local_only(recorder):
    assert generate.main(["finance", "--script-only", "--allow-disabled"]) == 0
    assert _Recorder.ran == ["finance"]
    for flag in ("--upload", "--sync-state"):
        with pytest.raises(SystemExit):
            generate.main(["finance", "--script-only", "--allow-disabled", flag])


def test_publish_skips_disabled_channel(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("aucun accès réseau pour une chaîne coupée")

    monkeypatch.setattr(publish, "get_latest_video", boom)
    assert publish.publish_channel("finance") is True
