"""Options partagées activées par le YAML d'une chaîne (PR 0bis).

Deux garanties sont testées pour chaque option :
1. absente du YAML : le comportement et les sorties restent ceux d'avant (non-régression mystery) ;
2. présente : l'effet attendu, sans toucher aux fichiers des autres chaînes.
"""
import json

import pytest
from tests.test_core import _client_with, _completion, _fake_openai

from auracontent.channels.base_channel import load_channel_config
from auracontent.core.brain.base_brain import BaseBrain, rate_limit_routing_from, simple_routing_from
from auracontent.services.publishing import state_sync

RATE_429 = ("Error code: 429 - Rate limit reached on tokens per minute (TPM): Limit 8000, Used 7900, "
            "Requested 500. Please try again in 3s.")


class _RateLimited(Exception):
    pass


# ---------- 429 : attendre (défaut) ou basculer (brain.rate_limit: fallback) ----------
def _two_model_client(monkeypatch):
    return _client_with(monkeypatch, {"groq": ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]})


def test_429_default_waits_and_retries_same_model(monkeypatch):
    from auracontent.core.brain import llm_client as lc

    client = _two_model_client(monkeypatch)
    calls = _fake_openai(monkeypatch, [_RateLimited(RATE_429), _completion("ok")])
    sleeps = []
    monkeypatch.setattr(lc.time, "sleep", sleeps.append)
    assert client.call_with_fallback([{"role": "user", "content": "x"}]) == "ok"
    assert [c["model"] for c in calls] == ["openai/gpt-oss-20b", "openai/gpt-oss-20b"]
    assert sleeps == [4.0]                       # « try again in 3s » + 1 s


def test_429_fallback_switches_provider_without_waiting(monkeypatch):
    from auracontent.core.brain import llm_client as lc

    client = _two_model_client(monkeypatch)
    calls = _fake_openai(monkeypatch, [_RateLimited(RATE_429), _completion("ok")])
    sleeps = []
    monkeypatch.setattr(lc.time, "sleep", sleeps.append)
    assert client.call_with_fallback([{"role": "user", "content": "x"}], rate_limit="fallback") == "ok"
    assert [c["model"] for c in calls] == ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]
    assert sleeps == []


def test_unknown_rate_limit_value_is_rejected(monkeypatch):
    client = _two_model_client(monkeypatch)
    with pytest.raises(ValueError):
        client.call_with_fallback([], rate_limit="patience")


def test_routing_unchanged_without_rate_limit_option():
    # mystery a choisi `rate_limit: fallback` ; sans l'option, le routage reste celui d'avant
    mystery = {k: v for k, v in load_channel_config("mystery")["brain"].items() if k != "rate_limit"}
    assert "rate_limit" not in simple_routing_from(mystery)
    assert rate_limit_routing_from(mystery) == {}
    assert simple_routing_from({}) == {}
    assert simple_routing_from({"rate_limit": "fallback"}) == {"rate_limit": "fallback"}
    assert simple_routing_from({"simple_models": ["gpt-oss-20b"], "rate_limit": "fallback"})["rate_limit"] == "fallback"


# ---------- Avertissements de style : publiés (défaut) ou script régénéré (style_warnings: reject) ----------
class _ScriptLLM:
    def call_json_with_retry(self, messages, **kw):
        return {"title": "T", "scenes": [{"text": f"Phrase {i}."} for i in range(5)]}


class _StyleBrain(BaseBrain):
    def build_script_prompt(self, topic, scene_count, chosen_hook, correction_feedback):
        return [{"role": "user", "content": topic}]

    def check_script_logic(self, topic, data):
        return ["phrase trop longue"]


def test_style_warnings_kept_by_default():
    data = _StyleBrain(config={"brain": {}}, llm=_ScriptLLM()).generate_script_with_target("sujet", scene_count=5)
    assert data["unresolved_issues"] == ["phrase trop longue"]


def test_style_warnings_reject_never_returns_a_script():
    brain = _StyleBrain(config={"brain": {"style_warnings": "reject"}}, llm=_ScriptLLM())
    with pytest.raises(RuntimeError, match="avertissements non résolus"):
        brain.generate_script_with_target("sujet", scene_count=5)


def test_build_visuals_default_keeps_asset_search():
    assert _StyleBrain(config={}, llm=None).build_visuals({}, [], None, {}) is None


# ---------- Historiques : fichiers partagés (défaut) ou dossier propre à la chaîne (state.isolated) ----------
@pytest.fixture
def isolated_state(monkeypatch, tmp_path):
    from auracontent.utils import hook_tracker, pending_topic, topic_tracker

    monkeypatch.setattr(state_sync, "STATE_DIR", tmp_path)
    monkeypatch.setattr(state_sync, "is_isolated", lambda channel: channel == "finance")
    monkeypatch.setattr(topic_tracker, "HISTORY_PATH", tmp_path / "global_history.json")
    monkeypatch.setattr(hook_tracker, "HOOK_HISTORY_PATH", tmp_path / "hook_history.json")
    monkeypatch.setattr(pending_topic, "PENDING_PATH", tmp_path / "pending_topics.json")
    return tmp_path


def test_mystery_keeps_shared_state_files():
    state_sync.is_isolated.cache_clear()
    assert state_sync.is_isolated("mystery") is False
    assert state_sync.channel_state_dir("mystery") is None
    assert state_sync._targets(None, ["mystery"]) == state_sync._targets(None, None)
    assert [r for _, r in state_sync._targets(None, None)] == [f"meta/{n}" for n in state_sync.STATE_FILES]


def test_isolated_channel_history_never_reaches_shared_files(isolated_state):
    from auracontent.utils.topic_tracker import load_global_history, save_global_history

    save_global_history("Le trésor de Gourdon", "mystery")
    save_global_history("Intérêts composés · 7 % · 45 ans", "finance", concept="interets_composes")
    assert load_global_history() == ["Le trésor de Gourdon"]                 # appel de mystery (sans filtre)
    assert load_global_history("finance") == ["Intérêts composés · 7 % · 45 ans"]
    shared = json.loads((isolated_state / "global_history.json").read_text(encoding="utf-8"))
    assert [e["channel"] for e in shared] == ["mystery"]
    assert (isolated_state / "finance" / "global_history.json").exists()


def test_isolated_channel_hooks_and_pending(isolated_state):
    from auracontent.utils import hook_tracker, pending_topic

    hook_tracker.record_hook_usage("Titre M", "question", "mystery")
    hook_tracker.record_hook_usage("Titre F", "chiffre", "finance")
    assert [e["title"] for e in hook_tracker.load_hook_history("mystery")] == ["Titre M"]
    assert [e["title"] for e in hook_tracker.load_hook_history("finance")] == ["Titre F"]
    assert [e["title"] for e in hook_tracker.load_hook_history()] == ["Titre M"]  # fichier partagé seul

    pending_topic.save_pending("finance", {"topic": "F"})
    pending_topic.save_pending("mystery", {"topic": "M"})
    assert set(json.loads((isolated_state / "pending_topics.json").read_text(encoding="utf-8"))) == {"mystery"}
    assert pending_topic.load_pending("finance")["topic"] == "F"
    pending_topic.note_rejected("finance", "page", None, "raison")
    assert pending_topic.load_rejected("mystery") == (set(), set())


def test_sync_targets_by_channel(isolated_state):
    remote = lambda names, channels: [r for _, r in state_sync._targets(names, channels)]  # noqa: E731
    assert remote(None, ["finance"]) == ["meta/finance/global_history.json", "meta/finance/hook_history.json",
                                         "meta/finance/pending_topics.json"]
    assert remote(("pending_topics.json",), ["finance"]) == ["meta/finance/pending_topics.json"]
    assert remote(("pending_topics.json",), ["mystery"]) == ["meta/pending_topics.json"]
    both = remote(None, ["mystery", "finance"])
    assert both[:len(state_sync.STATE_FILES)] == [f"meta/{n}" for n in state_sync.STATE_FILES]


# ---------- Statistiques Zernio : tous les comptes de la clé (défaut) ou comptes de la chaîne ----------
def test_stats_default_unchanged_and_account_envs(monkeypatch):
    from auracontent.core.brain import global_brain

    calls = []
    monkeypatch.setattr(global_brain, "get_latest_videos_stats",
                        lambda key, platform=None, account_id=None, limit=20: calls.append(account_id) or
                        [{"title": account_id, "views": 1}])
    monkeypatch.setenv("ZK", "key")
    global_brain.GlobalBrain._fetch_stats({"zernio_key_env": "ZK"})
    assert calls == [None]

    calls.clear()
    monkeypatch.setenv("TT_F", "tiktok-f")
    monkeypatch.delenv("YT_F", raising=False)
    stats = global_brain.GlobalBrain._fetch_stats({"zernio_key_env": "ZK", "stats": {"account_envs": ["TT_F", "YT_F"]}})
    assert calls == ["tiktok-f"] and [s["title"] for s in stats] == ["tiktok-f"]

    calls.clear()
    monkeypatch.delenv("TT_F")
    assert global_brain.GlobalBrain._fetch_stats({"zernio_key_env": "ZK", "stats": {"account_envs": ["TT_F"]}}) is None
    assert calls == []                                    # jamais « tous les comptes » à la place


# ---------- Légende : mention fixe ----------
def test_caption_footer_optional():
    from auracontent.services.publishing.caption import apply_caption_footer

    assert apply_caption_footer("Légende #a", None) == "Légende #a"
    footer = "Contenu pédagogique, pas un conseil en investissement."
    once = apply_caption_footer("Légende #a", footer)
    assert once.endswith(footer) and apply_caption_footer(once, footer) == once


# ---------- Composer : valeurs par défaut inchangées ----------
def test_composer_defaults_unchanged_for_mystery():
    from auracontent.services.video.composer import Composer

    composer = Composer(load_channel_config("mystery")["video_composer"], channel_name="mystery")
    assert composer.fonts_dir.endswith("assets/shared/fonts")
    assert composer.sfx_dir.endswith("assets/shared/sfx")
    assert composer.source_credit_enabled is True
    assert (composer.headline_text_color, composer.headline_border_color, composer.headline_border_ratio,
            composer.headline_shadow_color, composer.headline_accent_text_color) == \
        ("white", "black", 0.07, "black@0.6", "black")


def test_composer_channel_options():
    from auracontent.services.video.composer import Composer

    composer = Composer({"fonts_dir": "finance/fonts", "sfx_dir": "finance/sfx", "source_credit_enabled": False,
                         "headline_text_color": "0x1A1A1A", "headline_border_ratio": 0},
                        channel_name="finance_test_options")
    assert composer.fonts_dir.endswith("assets/finance/fonts") and composer.sfx_dir.endswith("assets/finance/sfx")
    assert composer.source_credit_enabled is False and composer.headline_border_ratio == 0
