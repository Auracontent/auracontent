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
_RATE_LIMIT_NUMS_RE = re.compile(r"Limit[:\s]+(\d+),?\s*(?:Used[:\s]+\d+,?\s*)?Requested[:\s]+(\d+)", re.IGNORECASE)
_RETRY_IN_RE = re.compile(r"(?:try again in|retryDelay['\"]?\s*[:=]\s*['\"]?)\s*(?:(\d+)m)?(\d+(?:\.\d+)?)s", re.IGNORECASE)
MAX_RATE_LIMIT_WAIT = 20  # au-delà, on bascule sur le fournisseur suivant (quota indépendant)
_MODELS_CACHE: dict[str, tuple[float, list[str]]] = {}
_FREE_MODELS_CACHE: dict[str, Any] = {"ts": 0.0, "models": []}
_DEAD_MODELS: set[str] = set()  # slugs 404 / décommissionnés / quota du jour épuisé pendant cette exécution


def _retry_after(e, err_str) -> float | None:
    """Délai d'attente conseillé par le fournisseur (corps d'erreur ou message), en secondes."""
    body = getattr(e, "body", None)
    text = f"{err_str} {json.dumps(body) if body is not None else ''}"
    m = _RETRY_IN_RE.search(text)
    if not m:
        return None
    return float(m.group(1) or 0) * 60 + float(m.group(2))


def _is_daily_quota(e, err_str) -> bool:
    body = getattr(e, "body", None)
    text = f"{err_str} {json.dumps(body) if body is not None else ''}".lower()
    return any(k in text for k in ("per day", "perday", "daily", "requests per day", "tokens per day"))


def _discover_models(name: str, base_url: str, api_key: str, configured: list[str],
                     preferences: list[str], limit: int = 3) -> list[str]:
    """Modèles réellement accessibles à CE compte via GET /models (évite les 404 de modèles retirés).

    Ordre : modèles configurés encore disponibles, puis disponibles selon `preferences`.
    En cas d'échec de la liste, on garde la configuration telle quelle.
    """
    now = time.time()
    cached = _MODELS_CACHE.get(name)
    if cached and now - cached[0] < FREE_MODELS_CACHE_TTL:
        available = cached[1]
    else:
        try:
            r = requests.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
            r.raise_for_status()
            data = r.json()
            items = data.get("data", data) if isinstance(data, dict) else data
            available = [m["id"] for m in items if isinstance(m, dict) and m.get("id") and m.get("active", True)]
            _MODELS_CACHE[name] = (now, available)
        except Exception as e:
            print(f"⚠️ Liste des modèles {name} indisponible ({type(e).__name__}) : configuration utilisée.")
            return configured[:limit]
    ordered = [m for m in configured if m in available]
    for pref in preferences:
        ordered += [m for m in available if pref in m.lower() and m not in ordered]
    return ordered[:limit] or configured[:limit]


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


# Registre des fournisseurs compatibles OpenAI. Chaque entrée a son PROPRE quota :
# plus il y en a, moins une saturation ponctuelle bloque la génération.
#   key_env     : variables d'environnement possibles pour la clé (la première trouvée gagne)
#   discover    : préférences pour la découverte via /models (None = liste configurée telle quelle)
#   budget_cap  : limite de tokens par minute très basse (Groq) -> budget de sortie plafonné
PROVIDER_SPECS: dict[str, dict[str, Any]] = {
    "gemini": {"label": "Gemini", "base_url": GEMINI_BASE_URL, "key_env": ["GEMINI_API_KEY"],
               "models": "GEMINI_TEXT_MODELS", "discover": None,
               # reasoning_effort bas : sinon la « réflexion » du modèle épuise le budget avant le JSON
               "extra": {"reasoning_effort": "low"}},
    "mistral": {"label": "Mistral", "base_url": "https://api.mistral.ai/v1", "key_env": ["MISTRAL_API_KEY"],
                "models": "MISTRAL_MODELS", "discover": None},
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "key_env": ["CEREBRAS_API_KEY"],
                 "models": "CEREBRAS_MODELS",
                 "discover": ["gpt-oss-120b", "llama-3.3-70b", "qwen-3-235b", "llama-4", "qwen-3-32b"]},
    "groq": {"label": "Groq", "base_url": GROQ_BASE_URL, "key_env": ["GROQ_API_KEY"], "models": "GROQ_MODELS",
             "discover": ["gpt-oss-120b", "llama-4-maverick", "kimi-k2", "qwen3-32b", "llama-4-scout", "gpt-oss-20b"],
             "budget_cap": True},
    "cloudflare": {"label": "Cloudflare", "base_url": None, "key_env": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_R2_TOKEN"],
                   "models": "CLOUDFLARE_TEXT_MODELS", "discover": None},
    "github": {"label": "GitHub Models", "base_url": "https://models.github.ai/inference", "key_env": ["GITHUB_TOKEN"],
               "models": "GITHUB_MODELS", "discover": None},
    # Fournisseurs chinois, endpoints INTERNATIONAUX (hors Chine continentale)
    "zhipu": {"label": "Z.ai GLM", "base_url": "https://api.z.ai/api/paas/v4", "key_env": ["ZAI_API_KEY", "ZHIPU_API_KEY"],
              "models": "ZHIPU_MODELS", "discover": None},
    "qwen": {"label": "Qwen", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
             "key_env": ["DASHSCOPE_API_KEY", "QWEN_API_KEY"], "models": "QWEN_MODELS",
             "discover": ["qwen-plus", "qwen-flash", "qwen-turbo", "qwen3"]},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "key_env": ["DEEPSEEK_API_KEY"],
                 "models": "DEEPSEEK_MODELS", "discover": None},  # payant (très bon marché) : en fin de cascade
    "openrouter": {"label": "OpenRouter", "base_url": OPENROUTER_BASE_URL, "key_env": ["OPENROUTER_API_KEY"],
                   "models": "OPENROUTER_ROUTING", "discover": None},
}


def _env_key(names: list[str]) -> str | None:
    """Première clé définie, sans espaces ni retours à la ligne parasites (copier-coller dans les Secrets)."""
    return next((os.getenv(n).strip() for n in names if (os.getenv(n) or "").strip()), None)


def _base_url(name: str) -> str | None:
    if name == "cloudflare":
        account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        return f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1" if account else None
    return PROVIDER_SPECS[name]["base_url"]


@dataclass
class LLMClient:
    keys: dict[str, str] = field(default_factory=dict)
    models: dict[str, list[str]] = field(default_factory=dict)
    order: list[str] = field(default_factory=lambda: list(PROVIDER_SPECS))

    @classmethod
    def create_default(cls):
        order = [p.strip() for p in os.getenv("LLM_PROVIDERS", "").split(",") if p.strip()]
        keys = {n: k for n, spec in PROVIDER_SPECS.items() if (k := _env_key(spec["key_env"])) and _base_url(n)}
        models = {n: list(getattr(settings, spec["models"], [])) for n, spec in PROVIDER_SPECS.items()}
        client = cls(keys=keys, models=models, order=order or list(settings.LLM_PROVIDER_ORDER))
        active = [n for n in client.order if n in keys]
        if active:
            print(f"🧠 Fournisseurs LLM actifs : {', '.join(active)}")
        else:
            print("⚠️ Aucun fournisseur LLM configuré (GEMINI_API_KEY, GROQ_API_KEY, CEREBRAS_API_KEY...).")
        return client

    def _provider_group(self, name: str) -> list[dict[str, Any]]:
        spec, key = PROVIDER_SPECS.get(name), self.keys.get(name)
        if not spec or not key:
            return []
        base_url = _base_url(name)
        if name == "openrouter":
            models = _discover_free_models()
            if OPENROUTER_FREE_ROUTER not in models:
                models.append(OPENROUTER_FREE_ROUTER)  # filet de sécurité gratuit
            models += [m for m in self.models.get(name, []) if m not in models]  # payants en dernier
        elif spec.get("discover"):
            models = _discover_models(spec["label"], base_url, key, self.models.get(name, []), spec["discover"])
        else:
            models = self.models.get(name, [])
        return [{"name": spec["label"], "model": m, "base_url": base_url, "api_key": key,
                 "is_groq": name == "groq", "budget_cap": spec.get("budget_cap", False),
                 "extra": spec.get("extra")} for m in models]

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
            client = OpenAI(
                base_url=provider["base_url"], api_key=provider["api_key"], max_retries=0, timeout=90,
                default_headers={
                    "HTTP-Referer": "https://github.com/SORADATA/auracontent_v2", "X-Title": "AuraContent",
                } if provider["name"] == "OpenRouter" else None,
            )
            max_tokens = max_completion_tokens
            if provider["budget_cap"]:  # Groq : limite de tokens par minute très basse
                ceiling = max(500, hard_token_cap - prompt_tokens - SAFETY_MARGIN_TOKENS)
                max_tokens = min(max_tokens, ceiling)
            else:
                ceiling = max(max_completion_tokens, 8000)
            use_json, temp, rate_hits = json_mode, temperature, 0
            extra = dict(provider.get("extra") or {})

            for attempt in range(3):
                try:
                    kwargs = {"model": provider["model"], "messages": messages, "temperature": temp,
                              "max_completion_tokens": max_tokens}
                    if use_json:
                        kwargs["response_format"] = {"type": "json_object"}
                    kwargs.update(extra)
                    content = self._extract_content(client.chat.completions.create(**kwargs))
                    print(f"✅ Réponse obtenue via {provider['name']} ({provider['model']})")
                    return content
                except Exception as e:
                    err_str, last_error = str(e), e
                    kind = _classify_error(e, err_str)
                    if extra and "error code: 400" in err_str.lower() and "reasoning" in err_str.lower():
                        extra = {}  # paramètre non supporté par ce modèle : on réessaie sans
                        continue
                    print(f"⚠️ Échec {provider['name']} [{provider['model']}] ({attempt + 1}/3, {kind}) : "
                          f"{err_str[:200]}{'…' if len(err_str) > 200 else ''}")

                    if kind == "json_failed":
                        salvaged = _repair_json_text(_extract_failed_generation(e, err_str))
                        if salvaged:
                            print("🩹 JSON récupéré et réparé depuis failed_generation.")
                            return salvaged
                        if use_json:
                            print("ℹ️ Nouvel essai sans le mode JSON strict (réparation locale).")
                            use_json = False
                        temp = max(0.2, temp - 0.2)
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
                        if _is_daily_quota(e, err_str):
                            _DEAD_MODELS.add(provider["model"])
                            print(f"⛔ Quota journalier atteint ({provider['model']}), ignoré pour cette exécution.")
                            break
                        nums = _RATE_LIMIT_NUMS_RE.search(err_str)
                        if nums and int(nums.group(2)) > int(nums.group(1)):  # requête plus grosse que la limite
                            limit, requested = int(nums.group(1)), int(nums.group(2))
                            max_tokens = max(500, max_tokens - (requested - limit) - SAFETY_MARGIN_TOKENS)
                            continue
                        delay = _retry_after(e, err_str)
                        if provider["name"] == "OpenRouter" and provider["model"].endswith(":free"):
                            break  # modèles gratuits partagés : saturés, inutile d'insister
                        if delay is None:
                            delay = 10
                        if delay > MAX_RATE_LIMIT_WAIT:
                            print(f"⏭️ {provider['model']} : attente de {delay:.0f}s trop longue, passage au suivant.")
                            break
                        print(f"⏳ Limite par minute sur {provider['model']}, attente de {delay:.0f}s...")
                        time.sleep(delay + 1)
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
