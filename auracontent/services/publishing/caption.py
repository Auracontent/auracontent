"""Légende des réseaux sociaux générée par le LLM à partir du script complet."""
from __future__ import annotations

import re
import unicodedata

HASHTAG_RE = re.compile(r"#[^\s#]+")

CAPTION_PROMPT = """Voici le texte exact de ma vidéo TikTok/Shorts ({title}) :
"{script}"

Rédige une légende ultra-captivante.
Règles :
1. 1ère ligne très accrocheuse avec un emoji.
2. 1 ou 2 phrases courtes pour teaser le contenu sans le spoiler.
3. Termine par une question courte pour inciter aux commentaires.
4. Ajoute 4 hashtags pertinents, en t'inspirant de : {hashtags}
Ne mets pas de guillemets autour de ta réponse, pas de préambule : renvoie uniquement la légende."""


def _fold(tag: str) -> str:
    """#MinuteMystère -> #minutemystere (comparaison sans casse ni accents)."""
    return "".join(c for c in unicodedata.normalize("NFD", tag.lower()) if unicodedata.category(c) != "Mn")


def apply_hashtag_rules(caption: str, brand_hashtag: str | None = None, banned_hashtags=()) -> str:
    """Retire les hashtags interdits (ancien nom de chaîne) et ajoute le hashtag de marque s'il manque.

    Sans `brand_hashtag` ni `banned_hashtags` (autres chaînes), la légende est rendue telle quelle.
    """
    banned = {_fold(h) for h in banned_hashtags or ()}
    if banned:
        caption = HASHTAG_RE.sub(lambda m: "" if _fold(m.group(0).rstrip(".,;:!?")) in banned else m.group(0), caption)
        caption = "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in caption.splitlines()).strip()
    brand = (brand_hashtag or "").strip()
    if brand and _fold(brand) not in {_fold(h) for h in HASHTAG_RE.findall(caption)}:
        caption = f"{caption} {brand}".strip()
    return caption


def generate_caption(llm, title: str, scenes: list[dict], fallback_hashtags: str = "",
                     brand_hashtag: str | None = None, banned_hashtags=()) -> str:
    caption = _generate_caption(llm, title, scenes, fallback_hashtags)
    return apply_hashtag_rules(caption, brand_hashtag, banned_hashtags)


def _generate_caption(llm, title: str, scenes: list[dict], fallback_hashtags: str = "") -> str:
    fallback = f"{title} {fallback_hashtags}".strip()
    script = " ".join(str(s.get("text", "")) for s in scenes)
    messages = [{
        "role": "user",
        "content": CAPTION_PROMPT.format(title=title, script=script[:3000], hashtags=fallback_hashtags or "#PourToi"),
    }]
    try:
        caption = llm.call_with_fallback(messages, temperature=0.8, max_completion_tokens=300).strip().strip('"')
        return caption or fallback
    except Exception as e:
        print(f"⚠️ Légende IA impossible ({e}), légende de secours.")
        return fallback
