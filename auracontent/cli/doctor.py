"""Diagnostic avant génération : teste RÉELLEMENT chaque service avec les clés présentes.

    python -m auracontent.cli.doctor              # local
    python -m auracontent.cli.doctor --require-hf # CI : l'upload Hugging Face est obligatoire

Code de sortie 1 si un service CRITIQUE est indisponible (ffmpeg, aucun LLM, HF si requis) :
le workflow s'arrête en 20 s avec un message clair au lieu d'échouer après 10 min de génération.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

import requests
from dotenv import load_dotenv

TIMEOUT = 15
OK, WARN, FAIL = "✅", "⚠️ ", "❌"


def _http(method: str, url: str, **kw) -> requests.Response | None:
    try:
        return requests.request(method, url, timeout=TIMEOUT, **kw)
    except requests.RequestException:
        return None


def _status(r: requests.Response | None) -> str:
    return "pas de réponse réseau" if r is None else f"HTTP {r.status_code} {r.text[:120].strip()}"


def check_ffmpeg():
    return (OK, "installé") if shutil.which("ffmpeg") else (FAIL, "binaire introuvable (packages.txt)")


def check_llm():
    """Un mini appel par fournisseur configuré. Au moins un doit répondre."""
    from auracontent.core.brain.llm_client import LLMClient

    client = LLMClient.create_default()
    lines, any_ok = [], False
    for group in client.order:
        providers = client._provider_group(group)
        if not providers:
            lines.append(f"{group}: pas de clé")
            continue
        single = LLMClient(**{**client.__dict__, "order": [group]})
        try:
            single.call_with_fallback([{"role": "user", "content": "Réponds juste OK."}],
                                      temperature=0, max_completion_tokens=20)
            lines.append(f"{group}: OK")
            any_ok = True
        except Exception as e:
            lines.append(f"{group}: KO ({str(e)[:90]})")
    return (OK if any_ok else FAIL), " | ".join(lines)


def check_pexels():
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        return WARN, "clé absente (vidéos d'ambiance remplacées par des images)"
    r = _http("GET", "https://api.pexels.com/videos/search", headers={"Authorization": key},
              params={"query": "forest", "per_page": 1})
    return (OK, "OK") if r is not None and r.status_code == 200 else (WARN, _status(r))


def check_pixabay():
    key = os.getenv("PIXABAY_API_KEY")
    if not key:
        return WARN, "clé absente"
    r = _http("GET", "https://pixabay.com/api/videos/", params={"key": key, "q": "forest", "per_page": 3})
    return (OK, "OK") if r is not None and r.status_code == 200 else (WARN, _status(r))


def check_pollinations():
    # Pas d'appel réel : chaque image consomme du quota
    return (OK, "jeton présent") if os.getenv("POLLINATIONS_TOKEN") else (WARN, "POLLINATIONS_TOKEN absent : 402 probables")


def check_wikimedia():
    contact = os.getenv("WIKIMEDIA_CONTACT")
    return (OK, "contact présent") if contact else (WARN, "WIKIMEDIA_CONTACT absent (risque de blocage User-Agent)")


def check_hf(repo: str):
    token = os.getenv("HF_TOKEN")
    if not token:
        return WARN, "HF_TOKEN absent"
    r = _http("GET", f"https://huggingface.co/api/datasets/{repo}", headers={"Authorization": f"Bearer {token}"})
    return (OK, f"accès à {repo}") if r is not None and r.status_code == 200 else (FAIL, _status(r))


def check_zernio():
    key = os.getenv("ZERNIO_API_KEY")
    if not key:
        return WARN, "ZERNIO_API_KEY absente : pas de boucle de feedback"
    r = _http("GET", "https://zernio.com/api/v1/analytics", headers={"Authorization": f"Bearer {key}"},
              params={"limit": 1})
    return (OK, "OK") if r is not None and r.status_code == 200 else (WARN, _status(r))


def main(argv: list[str]) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Diagnostic des services AuraContent")
    parser.add_argument("--require-hf", action="store_true", help="Hugging Face obligatoire (CI)")
    parser.add_argument("--hf-repo", default=os.getenv("HF_STATE_REPO", "soradata/AIShortvideos"))
    args = parser.parse_args(argv)

    checks = {
        "ffmpeg": (check_ffmpeg, True),
        "LLM": (check_llm, True),
        "Hugging Face": (lambda: check_hf(args.hf_repo), args.require_hf),
        "Pexels": (check_pexels, False),
        "Pixabay": (check_pixabay, False),
        "Pollinations": (check_pollinations, False),
        "Wikimedia": (check_wikimedia, False),
        "Zernio": (check_zernio, False),
    }
    print("\n🩺 Diagnostic AuraContent\n")
    blocking = []
    for name, (fn, critical) in checks.items():
        icon, detail = fn()
        if icon == FAIL and not critical:
            icon = WARN
        print(f"  {icon} {name:<13} {detail}")
        if icon == FAIL:
            blocking.append(name)

    if blocking:
        print(f"\n❌ Service(s) critique(s) indisponible(s) : {', '.join(blocking)}. Génération annulée.")
        return 1
    print("\n✅ Prêt pour la génération.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
