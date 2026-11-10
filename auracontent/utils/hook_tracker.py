"""Bandit manchot (epsilon-greedy) pour choisir le pattern de hook.

Chaque pattern (question, affirmation, paradoxe, chiffre, anecdote) est un bras.
On mémorise quel pattern a servi pour chaque vidéo, puis on recroise avec les stats
Zernio (vues, likes) pour scorer chaque pattern.

Historique : assets/shared/state/hook_history.json (synchronisé sur HF par state_sync),
entrées {"title", "pattern", "channel", "caption"}. Compatible avec l'ancien format {"title", "pattern"}.
"""
from __future__ import annotations

import json
import os
import random

from auracontent.services.publishing.state_sync import STATE_DIR

HOOK_HISTORY_PATH = STATE_DIR / "hook_history.json"
EPSILON = float(os.getenv("HOOK_BANDIT_EPSILON", "0.2"))  # 20 % d'exploration
MAX_HISTORY = 500


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def load_hook_history(channel: str | None = None) -> list[dict]:
    try:
        data = json.loads(HOOK_HISTORY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    entries = [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    # Les anciennes entrées sans "channel" viennent de Minute Mystère
    return [e for e in entries if channel is None or e.get("channel", "mystery") == channel]


def record_hook_usage(title: str, pattern: str | None, channel: str, caption: str = "") -> None:
    if not pattern:
        return
    entries = load_hook_history()
    entries.append({"title": title, "pattern": pattern, "channel": channel, "caption": caption})
    HOOK_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HOOK_HISTORY_PATH.write_text(json.dumps(entries[-MAX_HISTORY:], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📊 Hook enregistré ({pattern}) pour : {title}")


def _min_max(values: list[float]) -> dict[float, float]:
    if not values:
        return {}
    lo, hi = min(values), max(values)
    return {v: 0.5 if hi == lo else (v - lo) / (hi - lo) for v in values}


def _match_stat(entry: dict, stats: list[dict]) -> dict | None:
    """Zernio renvoie le texte du post (= la légende) : on matche sur la légende, sinon sur le titre."""
    caption, title = _norm(entry.get("caption")), _norm(entry.get("title"))
    for stat in stats:
        content = _norm(stat.get("title"))
        if not content:
            continue
        if (caption and (caption == content or caption[:80] in content)) or (title and title in content):
            return stat
    return None


def compute_pattern_scores(stats: list[dict] | None, history: list[dict]) -> dict[str, float]:
    """Score moyen par pattern = 0.5 * vues normalisées + 0.5 * likes normalisés."""
    stats = [s for s in (stats or []) if isinstance(s, dict)]
    if not stats or not history:
        return {}
    views = _min_max([float(s.get("views", 0) or 0) for s in stats])
    likes = _min_max([float(s.get("likes", 0) or 0) for s in stats])

    totals: dict[str, list[float]] = {}
    for entry in history:
        stat = _match_stat(entry, stats)
        if not stat or not entry.get("pattern"):
            continue
        score = 0.5 * views.get(float(stat.get("views", 0) or 0), 0.0) + 0.5 * likes.get(
            float(stat.get("likes", 0) or 0), 0.0
        )
        totals.setdefault(entry["pattern"], []).append(score)
    return {p: sum(v) / len(v) for p, v in totals.items()}


def select_hook(hooks: list[dict], pattern_scores: dict[str, float] | None = None, epsilon: float = EPSILON):
    """Exploitation du meilleur pattern connu (1 - epsilon), exploration aléatoire sinon."""
    if not hooks:
        return None
    explore = random.random() < epsilon
    if not explore and pattern_scores:
        scored = [(h, pattern_scores[h.get("pattern")]) for h in hooks if h.get("pattern") in pattern_scores]
        if scored:
            best, score = max(scored, key=lambda x: x[1])
            print(f"🎯 Hook par exploitation (pattern {best.get('pattern')}, score {score:.3f})")
            return best
    chosen = random.choice(hooks)
    reason = "exploration" if explore else "aucun score historique"
    print(f"🎲 Hook aléatoire ({reason}), pattern {chosen.get('pattern', '?')}")
    return chosen
