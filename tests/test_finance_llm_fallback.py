"""Capital Simple, texte : Gemini d'abord, puis repli automatique vers gpt-oss-120b (Groq, puis Cloudflare) dès que
le quota Gemini est épuisé, sans attente ni blocage. Cascade réelle du client LLM, fournisseurs simulés."""
import pytest
from auracontent.channels.base_channel import BaseChannel
from auracontent.channels.finance.brain import FinanceBrain
from auracontent.core.brain import llm_client
from auracontent.core.brain.llm_client import LLMClient

CI_ENV = {"GEMINI_API_KEY": "g", "GROQ_API_KEY": "q", "CLOUDFLARE_ACCOUNT_ID": "acc", "CLOUDFLARE_API_TOKEN": "cf",
          "OPENROUTER_API_KEY": "", "DEEPSEEK_API_KEY": "", "GITHUB_TOKEN": "", "ZAI_API_KEY": "", "DASHSCOPE_API_KEY": ""}


class _Answer:
    def __init__(self, text):
        self.choices = [type("Ch", (), {"message": type("M", (), {"content": text})(), "finish_reason": "stop"})()]
        self.usage = {"prompt_tokens": 100, "completion_tokens": 50}


def _fake_openai(log, behaviour):
    class Completions:
        def create(self, model, **kw):
            log.append(model)
            outcome = behaviour(model)
            if isinstance(outcome, Exception):
                raise outcome
            return _Answer(outcome)

    class Client:
        def __init__(self, **kw):
            self.chat = type("Chat", (), {"completions": Completions()})()

    return Client


@pytest.fixture
def ci_client(monkeypatch):
    for k, v in CI_ENV.items():
        monkeypatch.setenv(k, v) if v else monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(llm_client.requests, "get", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("hors ligne")))
    monkeypatch.setattr(llm_client, "_DEAD_MODELS", set())
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError(f"attente {s} s")))
    return LLMClient.create_default()


def _routing():
    return BaseChannel("finance", FinanceBrain, None).brain.script_routing()


def test_ci_providers_cover_the_script_fallback(ci_client):
    names = {p["name"] for p in ci_client.providers}
    models = [p["model"] for p in ci_client.providers if ci_client.model_allowed(p["model"], _routing()["allowed_models"])]
    assert {"Gemini", "Groq", "Cloudflare"} <= names
    assert models[0].startswith("gemini") and any("gpt-oss-120b" in m for m in models[1:])


def test_gemini_daily_quota_falls_back_to_gpt_oss_120b(ci_client, monkeypatch):
    log = []

    def behaviour(model):
        if model.startswith("gemini"):
            return RuntimeError("Error code: 429 - Quota exceeded for GenerateRequestsPerDayPerProjectPerModel (per day)")
        if model == "openai/gpt-oss-120b":                        # Groq : limite par minute
            return RuntimeError("Error code: 429 - Rate limit reached for model on tokens per minute (TPM)")
        return '{"ok": true}'

    monkeypatch.setattr(llm_client, "OpenAI", _fake_openai(log, behaviour))
    out = ci_client.call_json_with_retry([{"role": "user", "content": "x"}], **_routing())
    assert out == {"ok": True}
    assert log[0].startswith("gemini") and "openai/gpt-oss-120b" in log and log[-1] == "@cf/openai/gpt-oss-120b"
    assert log.count("openai/gpt-oss-120b") == 1                  # bascule au premier 429, sans réessayer


def test_dead_gemini_is_skipped_for_the_rest_of_the_run(ci_client, monkeypatch):
    log = []
    behaviour = lambda model: (RuntimeError("Error code: 429 - per day quota") if model.startswith("gemini")  # noqa: E731
                               else '{"ok": true}')
    monkeypatch.setattr(llm_client, "OpenAI", _fake_openai(log, behaviour))
    ci_client.call_json_with_retry([{"role": "user", "content": "x"}], **_routing())
    log.clear()
    ci_client.call_json_with_retry([{"role": "user", "content": "x"}], **_routing())
    assert not any(m.startswith("gemini") for m in log)          # plus jamais rappelé dans l'exécution
