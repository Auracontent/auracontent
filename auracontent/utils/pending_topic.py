"""Reprise : sujet, titre et accroche validés, gardés tant que le script n'a pas abouti.

Choisir un sujet coûte des appels LLM (page, titre, retournement, doublon, accroches). Si l'écriture du
script échoue (quotas), l'exécution suivante reprend ce sujet au lieu de repartir de zéro.

Fichier : assets/shared/state/pending_topics.json, une entrée par chaîne, synchronisé sur Hugging Face
(y compris quand la génération échoue, voir cli/generate.py).
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from auracontent.services.publishing.state_sync import STATE_DIR

PENDING_FILE = "pending_topics.json"
PENDING_PATH = STATE_DIR / PENDING_FILE


def _load() -> dict:
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> None:
    try:
        PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PENDING_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(PENDING_PATH)
    except OSError as e:
        print(f"⚠️ Sujet en attente non enregistré : {e}")


def save_pending(channel: str, state: dict) -> None:
    """Enregistre (ou met à jour) l'état validé de la chaîne ; compte les tentatives d'écriture du script."""
    data = _load()
    previous = data.get(channel) or {}
    same = previous.get("topic") == state.get("topic")
    data[channel] = {**state, "saved_at": previous.get("saved_at") if same else
                     datetime.now(UTC).isoformat(timespec="seconds"),
                     "script_attempts": int(previous.get("script_attempts", 0)) if same else 0}
    _write(data)


def note_script_attempt(channel: str) -> None:
    data = _load()
    if channel in data:
        data[channel]["script_attempts"] = int(data[channel].get("script_attempts", 0)) + 1
        _write(data)


def load_pending(channel: str, max_attempts: int = 3, max_age_days: float = 7) -> dict | None:
    """État à reprendre, ou None (aucun, trop vieux, ou trop de tentatives : il est alors abandonné)."""
    entry = _load().get(channel)
    if not entry or not entry.get("topic"):
        return None
    try:
        saved = datetime.fromisoformat(entry["saved_at"])
    except (KeyError, TypeError, ValueError):
        saved = datetime.now(UTC)
    if int(entry.get("script_attempts", 0)) >= max_attempts or \
            datetime.now(UTC) - saved > timedelta(days=max_age_days):
        print(f"🗑️ Sujet en attente abandonné ({entry['topic']}) : trop de tentatives ou trop ancien.")
        clear_pending(channel)
        return None
    return entry


def clear_pending(channel: str) -> None:
    data = _load()
    if data.pop(channel, None) is not None:
        _write(data)
