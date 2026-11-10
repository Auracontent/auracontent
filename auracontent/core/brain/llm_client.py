"""Client LLM : cascade Groq -> modèles OpenRouter gratuits (découverts dynamiquement) -> routeur openrouter/free.

Porté de l'ancien brain.py (v1) : chaque type d'erreur a sa stratégie
  json_failed            -> récupère/répare le `failed_generation` de Groq, sinon baisse la température
  not_found              -> modèle blacklisté pour l'exécution, passage au suivant
  no_credit              -> passage au suivant
  rate_limit             -> réduit le budget ou attend, quota journalier -> suivant
  json_mode_unsupported  -> réessaie sans response_format
  length                 -> augmente le budget de sortie
  refusal                -> suivant immédiatement
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import requests
from openai import OpenAI

from auracontent.utils.text_utils import _clean_json_response, _estimate_prompt_tokens
from config import settings

SAFETY_MARGIN_TOKENS = 400
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_FREE_ROUTER = "openrouter/free"
OPENROUTER_MAX_DISCOVERED = 3
FREE_MODELS_CACHE_TTL = 3600

# Ordre de préférence des modèles gratuits (le premier mot-clé trouvé gagne)
FREE_MODEL_PREFERENCES = [
    "llama-3.3-70b", "gpt-oss-120b", "qwen3-235b", "qwen3-next", "qwen3-coder",
    "qwen", "nemotron", "deepseek", "gemma-3-27b", "gemma", "mistral", "glm", "llama",
]
FREE_MODEL_BLACKLIST = ["vision", "-vl", "image", "audio", "embed", "thinking", "lfm", "guard", "safeguard"]
_SMALL_MODEL_RE = re.compile(r"(?<![0-9a-z])(0?\.?[1-9])b(?![a-z0-9])")  # 1b..9b : trop petit pour du JSON long
_RATE_LIMIT_NUMS_RE = re.compile(r"Limit[:\s]+(\d+),?\s*Requested[:\s]+(\d+)", re.IGNORECASE)

_FREE_MODELS_CACHE: dict[str, Any] = {"ts": 0.0, "models": []}
_DEAD_MODELS: set[str] = set()  # slugs 404 / décommissionnés pendant cette exécution


# ---------- JSON ----------
def _strip_reasoning(text):
    """Les modèles « reasoning » gratuits renvoient parfois <think>...</think>."""
    if not text:
        return text
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"^.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


def _repair_json_text(text):
    """Répare un JSON cassé (accolade de scène manquante, JSON tronqué). Retourne le texte ou None."""
    if not text:
        return None
    t = _strip_reasoning(_clean_json_response(text))
    try:
        json.loads(t)
        return t
    except Exception:
        pass

    t = re.sub(r'\}\s*,?\s*"id"\s*:', '},{"id":', t)  # ...},"id":5,... -> ...},{"id":5,...
    stack, in_str, escape = [], False, False
    for ch in t:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack and ((ch == "}" and stack[-1] == "{") or (ch == "]" and stack[-1] == "[")):
            stack.pop()

    repaired = t + ('"' if in_str else "")
    repaired = re.sub(r",\s*$", "", repaired)
    repaired += "".join("}" if o == "{" else "]" for o in reversed(stack))
    try:
        json.loads(repaired)
        return repaired
    except Exception:
        return None


def _extract_failed_generation(e, err_str):
    """Texte `failed_generation` d'une erreur 400 Groq (JSON généré mais refusé par le validateur)."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict) and inner.get("failed_generation"):
            return inner["failed_generation"]
    m = re.search(r"'failed_generation': '(.*)'\}\}", err_str, re.DOTALL)
    return m.group(1).replace("\\'", "'").replace("\\n", "\n") if m else None


# ---------- Erreurs ----------
def _is_rate_limit_error(low):
    return any(k in low for k in (
        "rate_limit_exceeded", "rate limit", "tokens per minute", "tpm", "requests per minute", "rpm",
        "error code: 429",
    ))


def _classify_error(e, err_str):
    low = err_str.lower()
    if isinstance(e, ValueError):
        return "length" if "budget de tokens" in low else "empty"
    if "json_validate_failed" in low or "failed to generate json" in low or "failed to validate json" in low:
        return "json_failed"
    if any(k in low for k in ("error code: 404", "no endpoints found", "unavailable", "not a valid model",
                              "decommissioned", "model_not_found", "does not exist")):
        return "not_found"
    if "error code: 402" in low or "more credits" in low or "insufficient" in low:
        return "no_credit"
    if _is_rate_limit_error(low):
        return "rate_limit"
    if "error code: 400" in low and any(k in low for k in ("response_format", "json_object", "structured")):
        return "json_mode_unsupported"
    if any(k in low for k in ("i'm sorry", "i’m sorry", "content_policy", "moderation")):
        return "refusal"
    return "other"


# ---------- Découverte des modèles gratuits OpenRouter ----------
def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _discover_free_models(max_models=OPENROUTER_MAX_DISCOVERED) -> list[str]:
    """Modèles `:free` à prix nul, compatibles JSON, contexte >= 16k. Override : OPENROUTER_FREE_MODELS=a,b."""
    env_models = [m.strip() for m in os.getenv("OPENROUTER_FREE_MODELS", "").split(",") if m.strip()]
    if env_models:
        return [m for m in env_models if m not in _DEAD_MODELS][:max_models]

    now = time.time()
    cached = _FREE_MODELS_CACHE["models"]
    if cached and now - _FREE_MODELS_CACHE["ts"] < FREE_MODELS_CACHE_TTL:
        return [m for m in cached if m not in _DEAD_MODELS][:max_models]

    try:
        r = requests.get(f"{OPENROUTER_BASE_URL}/models", timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
    except Exception as e:
        print(f"⚠️ Découverte des modèles gratuits OpenRouter impossible : {e}")
        return [m for m in cached if m not in _DEAD_MODELS][:max_models]

    scored = []
    for m in data:
        mid = str(m.get("id", ""))
        low = mid.lower()
        if not mid.endswith(":free") or mid in _DEAD_MODELS:
            continue
        pricing = m.get("pricing") or {}
        if _to_float(pricing.get("prompt")) not in (0.0, None) or _to_float(pricing.get("completion")) not in (0.0, None):
            continue
        params = m.get("supported_parameters") or []
        if not ("response_format" in params or "structured_outputs" in params):
            continue
        if (m.get("context_length") or 0) < 16000:
            continue
        if "text" not in ((m.get("architecture") or {}).get("output_modalities") or ["text"]):
            continue
        if any(b in low for b in FREE_MODEL_BLACKLIST) or _SMALL_MODEL_RE.search(low):
            continue
        score = next((len(FREE_MODEL_PREFERENCES) - i for i, k in enumerate(FREE_MODEL_PREFERENCES) if k in low), 0)
        scored.append((score, m.get("context_length") or 0, mid))

    models = [mid for _, _, mid in sorted(scored, reverse=True)]
    if models:
        _FREE_MODELS_CACHE.update({"ts": now, "models": models})
        print(f"🆓 Modèles OpenRouter gratuits retenus : {models[:max_models]}")
    return models[:max_models]


@dataclass
class LLMClient:
    gemini_key: str | None = None
    groq_key: str | None = None
    openrouter_key: str | None = None
    gemini_models: list[str] = field(default_factory=list)
    groq_models: list[str] = field(default_factory=list)
    openrouter_paid_models: list[str] = field(default_factory=list)
    order: list[str] = field(default_factory=lambda: ["gemini", "groq", "openrouter"])

    @classmethod
    def create_default(cls):
        order = [p.strip() for p in os.getenv("LLM_PROVIDERS", "").split(",") if p.strip()]
        client = cls(
            gemini_key=os.getenv("GEMINI_API_KEY"),
            groq_key=os.getenv("GROQ_API_KEY"),
            openrouter_key=os.getenv("OPENROUTER_API_KEY"),
            gemini_models=list(settings.GEMINI_TEXT_MODELS),
            groq_models=list(settings.GROQ_MODELS),
            openrouter_paid_models=list(settings.OPENROUTER_ROUTING),
            order=order or list(settings.LLM_PROVIDER_ORDER),
        )
        if not (client.gemini_key or client.groq_key or client.openrouter_key):
            print("⚠️ Aucun fournisseur LLM configuré : GEMINI_API_KEY / GROQ_API_KEY / OPENROUTER_API_KEY.")
        return client

    def _provider_group(self, name: str) -> list[dict[str, Any]]:
        if name == "gemini" and self.gemini_key:
            return [{"name": "Gemini", "model": m, "base_url": GEMINI_BASE_URL, "api_key": self.gemini_key,
                     "is_groq": False, "budget_cap": False} for m in self.gemini_models]
        if name == "groq" and self.groq_key:
            return [{"name": "Groq", "model": m, "base_url": GROQ_BASE_URL, "api_key": self.groq_key,
                     "is_groq": True, "budget_cap": True} for m in self.groq_models]
        if name == "openrouter" and self.openrouter_key:
            slugs = _discover_free_models()
            if OPENROUTER_FREE_ROUTER not in slugs:
                slugs.append(OPENROUTER_FREE_ROUTER)  # filet de sécurité gratuit
            slugs += [m for m in self.openrouter_paid_models if m not in slugs]  # payants en dernier
            return [{"name": "OpenRouter", "model": s, "base_url": OPENROUTER_BASE_URL,
                     "api_key": self.openrouter_key, "is_groq": False, "budget_cap": False} for s in slugs]
        return []

    @property
    def providers(self) -> list[dict[str, Any]]:
        """Fournisseurs dans l'ordre configuré (LLM_PROVIDER_ORDER / env LLM_PROVIDERS), modèles morts exclus."""
        providers = [p for name in self.order for p in self._provider_group(name)]
        return [p for p in providers if p["model"] not in _DEAD_MODELS]

    @staticmethod
    def _extract_content(response):
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        if not choices:
            raise ValueError(f"Réponse inattendue du LLM : {response}")
        choice0 = choices[0]
        message = getattr(choice0, "message", None)
        if message is None and isinstance(choice0, dict):
            message = choice0.get("message")
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        if isinstance(content, list):
            content = "".join(
                (i.get("text") or i.get("content") or "") if isinstance(i, dict) else str(i) for i in content
            )
        content = _strip_reasoning(content) if content else content
        if not content:
            finish = getattr(choice0, "finish_reason", None)
            if finish is None and isinstance(choice0, dict):
                finish = choice0.get("finish_reason")
            if finish == "length":
                raise ValueError("Contenu vide : budget de tokens épuisé (finish_reason='length').")
            raise ValueError("Contenu vide du LLM.")
        return content.strip()

    def call_with_fallback(self, messages, temperature=1.0, json_mode=False,
                           max_completion_tokens=3000, hard_token_cap=7500):
        providers = self.providers
        if not providers:
            raise RuntimeError("Aucune clé API LLM (GEMINI / GROQ / OPENROUTER) configurée.")

        last_error = None
        prompt_tokens = _estimate_prompt_tokens(messages)

        for provider in providers:
            if provider["model"] in _DEAD_MODELS:
                continue
            is_groq = provider["is_groq"]
            client = OpenAI(
                base_url=provider["base_url"], api_key=provider["api_key"], max_retries=0, timeout=90,
                default_headers=None if is_groq else {
                    "HTTP-Referer": "https://github.com/SORADATA/auracontent_v2", "X-Title": "AuraContent",
                },
            )
            max_tokens = max_completion_tokens
            if provider["budget_cap"]:  # Groq : limite de tokens par minute très basse
                ceiling = max(500, hard_token_cap - prompt_tokens - SAFETY_MARGIN_TOKENS)
                max_tokens = min(max_tokens, ceiling)
            else:
                ceiling = max(max_completion_tokens, 8000)
            use_json, temp, rate_hits = json_mode, temperature, 0

            for attempt in range(3):
                try:
                    kwargs = {"model": provider["model"], "messages": messages, "temperature": temp,
                              "max_completion_tokens": max_tokens}
                    if use_json:
                        kwargs["response_format"] = {"type": "json_object"}
                    content = self._extract_content(client.chat.completions.create(**kwargs))
                    print(f"✅ Réponse obtenue via {provider['name']} ({provider['model']})")
                    return content
                except Exception as e:
                    err_str, last_error = str(e), e
                    kind = _classify_error(e, err_str)
                    print(f"⚠️ Échec {provider['name']} [{provider['model']}] ({attempt + 1}/3, {kind}) : "
                          f"{err_str[:200]}{'…' if len(err_str) > 200 else ''}")

                    if kind == "json_failed":
                        salvaged = _repair_json_text(_extract_failed_generation(e, err_str))
                        if salvaged:
                            print("🩹 JSON récupéré et réparé depuis failed_generation.")
                            return salvaged
                        temp = max(0.2, temp - 0.2)
                        time.sleep(1)
                        continue
                    if kind == "not_found":
                        _DEAD_MODELS.add(provider["model"])
                        print(f"🚫 Modèle indisponible ({provider['model']}), ignoré pour cette exécution.")
                        break
                    if kind in ("no_credit", "refusal"):
                        break
                    if kind == "json_mode_unsupported":
                        use_json = False
                        continue
                    if kind == "length":
                        max_tokens = min(max_tokens + 1500, ceiling)
                        continue
                    if kind == "rate_limit":
                        rate_hits += 1
                        low = err_str.lower()
                        if "per day" in low or "daily" in low:
                            print(f"⛔ Quota journalier atteint ({provider['model']}), passage au suivant.")
                            break
                        nums = _RATE_LIMIT_NUMS_RE.search(err_str)
                        if nums:
                            limit, requested = int(nums.group(1)), int(nums.group(2))
                            max_tokens = max(500, max_tokens - (requested - limit) - SAFETY_MARGIN_TOKENS)
                            continue
                        if not is_groq and rate_hits >= 2:
                            break
                        time.sleep(25 if is_groq else 6)
                        continue
                    time.sleep(2)

        raise RuntimeError(f"Échec total après tous les fournisseurs LLM ({', '.join(self.order)}). Dernière erreur : {last_error}")

    def call_json_with_retry(self, messages, temperature=1.0, max_json_retries=2,
                             max_completion_tokens=6000, hard_token_cap=7500):
        last_error = None
        for attempt in range(max_json_retries):
            content = self.call_with_fallback(
                messages, temperature=temperature, json_mode=True,
                max_completion_tokens=max_completion_tokens, hard_token_cap=hard_token_cap,
            )
            try:
                try:
                    data = json.loads(_clean_json_response(content))
                except json.JSONDecodeError:
                    repaired = _repair_json_text(content)
                    if repaired is None:
                        raise
                    print("🩹 JSON malformé réparé localement.")
                    data = json.loads(repaired)
                return {"scenes": data} if isinstance(data, list) else data
            except json.JSONDecodeError as e:
                last_error = e
                print(f"⚠️ JSON malformé (tentative {attempt + 1}/{max_json_retries}), budget augmenté.")
                max_completion_tokens = min(max_completion_tokens + 1000, hard_token_cap)
        raise ValueError(f"Impossible d'obtenir un JSON valide : {last_error}")
