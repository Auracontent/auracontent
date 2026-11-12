"""Historique des sujets publiés, partagé par toutes les chaînes.

Stocké dans assets/shared/state/global_history.json, sous forme de liste d'entrées :
{"topic", "channel", "date", + métadonnées libres (region, category, source_title, source_url...)}.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

HISTORY_PATH = Path(__file__).resolve().parents[2] / "assets" / "shared" / "state" / "global_history.json"


def _history_path(channel: str | None = None) -> Path:
    """Chaîne à état isolé (`state.isolated`) : son propre fichier ; sinon le fichier partagé historique."""
    from auracontent.services.publishing.state_sync import channel_state_dir

    own = channel_state_dir(channel)
    return own / HISTORY_PATH.name if own else HISTORY_PATH


def _load_entries(channel: str | None = None) -> list[dict]:
    path = _history_path(channel)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"⚠️ Historique illisible ({path}) : {e}")
        return []
    return [e for e in data if isinstance(e, dict) and e.get("topic")] if isinstance(data, list) else []


def _filter(entries, channel):
    return [e for e in entries if channel is None or e.get("channel") == channel]


def load_global_history(channel: str | None = None) -> list[str]:
    """Titres des sujets déjà traités, du plus ancien au plus récent (toutes chaînes par défaut)."""
    return [e["topic"] for e in _filter(_load_entries(channel), channel)]


def load_topic_history(channel: str | None = None) -> list[str]:
    """Alias conservé pour asset_manager."""
    return load_global_history(channel)


def _last_values(key: str, n: int, channel: str | None) -> list[str]:
    values = [e[key] for e in _filter(_load_entries(channel), channel) if e.get(key)]
    return values[-n:] if n > 0 else []


def load_last_regions(n: int = 3, channel: str | None = None) -> list[str]:
    return _last_values("region", n, channel)


def load_last_categories(n: int = 2, channel: str | None = None) -> list[str]:
    return _last_values("category", n, channel)


def load_used_sources(channel: str | None = None) -> set[str]:
    """Titres des pages sources déjà exploitées (en minuscules)."""
    return {e["source_title"].lower() for e in _filter(_load_entries(channel), channel) if e.get("source_title")}


def load_used_values(field: str, channel: str | None = None) -> set[str]:
    """Valeurs déjà prises par un champ de l'historique (ex. « anecdote_id »), en chaînes."""
    return {str(e[field]) for e in _filter(_load_entries(channel), channel) if e.get(field) not in (None, "")}


def save_global_history(topic: str, channel: str, **meta) -> None:
    path = _history_path(channel)
    entries = _load_entries(channel)
    entry = {"topic": topic, "channel": channel,
             "date": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    entry.update({k: v for k, v in meta.items() if k not in entry and v is not None})
    entries.append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
