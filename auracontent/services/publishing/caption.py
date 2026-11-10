"""Légende des réseaux sociaux générée par le LLM à partir du script complet."""
from __future__ import annotations

CAPTION_PROMPT = """Voici le texte exact de ma vidéo TikTok/Shorts ({title}) :
"{script}"

Rédige une légende ultra-captivante.
Règles :
1. 1ère ligne très accrocheuse avec un emoji.
2. 1 ou 2 phrases courtes pour teaser le contenu sans le spoiler.
3. Termine par une question courte pour inciter aux commentaires.
4. Ajoute 4 hashtags pertinents, en t'inspirant de : {hashtags}
Ne mets pas de guillemets autour de ta réponse, pas de préambule : renvoie uniquement la légende."""


def generate_caption(llm, title: str, scenes: list[dict], fallback_hashtags: str = "") -> str:
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
