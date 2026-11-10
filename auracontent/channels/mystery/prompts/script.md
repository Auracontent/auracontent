# System
Tu produis uniquement du JSON valide. La cle 'scenes' contient EXACTEMENT {scene_count} scenes, ni plus ni moins -- c'est une contrainte absolue et non negociable. Ne montre jamais ton raisonnement, reponds directement avec le JSON final.

# User
SUJET : {topic}
ACCROCHE OBLIGATOIRE : {chosen_hook}
{grounding_block}

REGLES STRICTES DE NARRATION ET VISUEL :
1. Interdiction de faire de longs discours d'introduction ("Nous allons vous raconter...").
2. Dès la scène 2, entre DIRECTEMENT dans le vif du sujet avec des faits concrets.
3. Le milieu de la vidéo doit développer l'histoire en profondeur.
4. Les dernières scènes doivent apporter une conclusion claire ou une révélation.
5. CORRECTION VISUELLE MAJEURE ('image_prompt') : TU DOIS OBLIGATOIREMENT L'ÉCRIRE EN ANGLAIS. Génère une description STRICTEMENT VISUELLE ET MATÉRIELLE de 15 mots maximum (objets concrets, architecture, lumière). Interdiction absolue d'utiliser des termes de synthèse (CGI, 3D) ou des concepts abstraits.
6. LECTURE AUDIO : N'utilise JAMAIS de chiffres romains. Écris-les obligatoirement EN TOUTES LETTRES (ex: "vingtième siècle").
7. 'stock_search' : OBLIGATOIREMENT EN ANGLAIS. Ne demande JAMAIS de lieux géographiques précis. Fournis TOUJOURS un mot-clé très générique et d'ambiance.
8. RYTHME : Le 'text' de chaque scène doit contenir 2 phrases (environ 20 à 30 mots) pour laisser la narration respirer (5 à 7 secondes par scène).
9. RE-HOOK OBLIGATOIRE : La scène {rehook_scene} doit contenir une phrase de rupture qui relance la curiosité (ex: 'Mais ce n'est pas la le plus troublant...').
10. CTA FINAL : Génère un champ 'closing_cta' indépendant dans le JSON, une phrase courte (8-10 mots) qui invite à s'abonner en créant une attente spécifique pour la prochaine vidéo.
11. Les clés 'mood' doivent être choisies parmi : "ominous", "intriguing", "tense", "awe", "scientific", "investigation".
12. Les clés 'role' doivent être choisies parmi : "hook", "tension", "context", "value", "escalation", "reveal", "cta".

FORMAT DE SORTIE ATTENDU :
Retourne un JSON avec les clés : title, visual_identity, audio_profile, closing_cta, scenes.
Chaque scene dans le tableau 'scenes' doit contenir : id, text, voice_direction, pause_after_ms, stock_search, image_prompt, location_name, location_country, voice_type, mood, role, scene_type, event_context.