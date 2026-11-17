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


# ---------- 503 / délai dépassé chez Gemini : fournisseur suivant tout de suite (brain.unavailable) ----------
@pytest.mark.parametrize("error", ["Request timed out.", "Error code: 503 - {'error': 'overloaded'}"])
def test_gemini_unavailable_goes_to_next_provider_without_retry(ci_client, monkeypatch, error):
    log = []
    monkeypatch.setattr(llm_client, "OpenAI", _fake_openai(
        log, lambda m: RuntimeError(error) if m.startswith("gemini") else '{"ok": true}'))
    brain = BaseChannel("finance", FinanceBrain, ci_client).brain
    assert brain.script_routing()["unavailable"] == "fallback"
    assert ci_client.call_json_with_retry([{"role": "user", "content": "x"}], **brain.script_routing()) == {"ok": True}
    assert sum(m.startswith("gemini") for m in log) == 1 and "gpt-oss-120b" in log[-1]   # un seul essai Gemini


def test_mystery_keeps_retrying_on_503(ci_client, monkeypatch):
    from auracontent.channels.base_channel import load_channel_config
    from auracontent.core.brain.base_brain import rate_limit_routing_from

    assert "unavailable" not in rate_limit_routing_from(load_channel_config("mystery").get("brain"))
    log = []
    monkeypatch.setattr(llm_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm_client, "OpenAI", _fake_openai(
        log, lambda m: RuntimeError("Error code: 503") if m.startswith("gemini") else '{"ok": true}'))
    ci_client.call_json_with_retry([{"role": "user", "content": "x"}])
    assert sum(m.startswith("gemini") for m in log) == 3                                   # comportement inchangé


def test_free_topics_and_meaning_check_run_without_gemini(ci_client, monkeypatch):
    """Gemini muet : la génération libre, la vérification des situations, le choix du sujet et la vérification
    du sens passent par les petits modèles gratuits (Groq, Cloudflare), jamais bloqués par Gemini."""
    log = []
    candidates = {"candidats": [{"situation": "Hugo reste à découvert de 300 € pendant 3 jours chaque mois",
                                 "domaine": "banque et paiements", "concept": "agios",
                                 "calcul": {"type": "decouvert_agios",
                                            "params": {"overdraft": 300, "days": 3, "rate": 15}},
                                 "question_spectateur": "Combien coûtent 3 jours de découvert ?"}]}

    def behaviour(model):
        if model.startswith("gemini"):
            return RuntimeError("Request timed out.")
        return __import__("json").dumps(candidates)

    monkeypatch.setattr(llm_client, "OpenAI", _fake_openai(log, behaviour))
    brain = BaseChannel("finance", FinanceBrain, ci_client).brain
    monkeypatch.setattr(type(brain), "history_window", lambda self, n: [])
    pick = brain.free_pick()
    assert pick and pick["concept"] == "decouvert_agios" and not any(m.startswith("gemini") for m in log)
    log.clear()
    monkeypatch.setattr(llm_client, "OpenAI", _fake_openai(
        log, lambda m: RuntimeError("Error code: 503") if m.startswith("gemini") else '{"ok": true, "problems": []}'))
    brain.last_pick = pick
    brain.config["brain"]["meaning_check"] = "llm"
    scenes = [{"id": 1, "text": "Le découvert coûte 0,37 €.", "role": "reveal"}]
    assert brain.llm_meaning_issues({"scenes": scenes, "on_screen_title": "A | B", "title": "t",
                                     "closing_cta": "?"}) == []
    assert not any(m.startswith("gemini") for m in log)
