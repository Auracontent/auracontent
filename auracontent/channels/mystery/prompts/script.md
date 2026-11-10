# System
Tu produis uniquement du JSON valide. La cle 'scenes' contient EXACTEMENT {scene_count} scenes, ni plus ni moins -- c'est une contrainte absolue et non negociable. Ne montre jamais ton raisonnement, reponds directement avec le JSON final.

# User
SUJET : {topic}
ACCROCHE OBLIGATOIRE : {chosen_hook}
{grounding_block}

REGLES STRICTES DE NARRATION ET VISUEL :
0. La scène 1 COMMENCE MOT POUR MOT par l'ACCROCHE OBLIGATOIRE, puis enchaîne immédiatement sur un fait concret.
1. Interdiction de faire de longs discours d'introduction ("Nous allons vous raconter...").
2. Dès la scène 2, entre DIRECTEMENT dans le vif du sujet avec des faits concrets.
3. Le milieu de la vidéo doit développer l'histoire en profondeur.
4. Les dernières scènes doivent apporter une conclusion claire ou une révélation.
5. CORRECTION VISUELLE MAJEURE ('image_prompt') : TU DOIS OBLIGATOIREMENT L'ÉCRIRE EN ANGLAIS. Génère une description STRICTEMENT VISUELLE ET MATÉRIELLE de 15 mots maximum (objets concrets, architecture, lumière). Interdiction absolue d'utiliser des termes de synthèse (CGI, 3D) ou des concepts abstraits.
6. LECTURE AUDIO : N'utilise JAMAIS de chiffres romains. Écris-les obligatoirement EN TOUTES LETTRES (ex: "vingtième siècle").
7. 'stock_search' : OBLIGATOIREMENT EN ANGLAIS. Ne demande JAMAIS de lieux géographiques précis. Décris en 2 à 4 mots un OBJET ou un GESTE concret lié à la phrase (ex : "old iron key", "hands opening manuscript", "gold coins candlelight"), jamais une ambiance vague ("mystery", "history", "dark atmosphere").
8. RYTHME SHORTS : le 'text' de chaque scène fait 1 à 2 phrases courtes (15 à 22 mots, environ 7 secondes). Phrases simples, verbes forts, un fait concret par scène. Jamais de remplissage.
8b. VARIÉTÉ VISUELLE : chaque scène montre quelque chose de DIFFÉRENT. La scène 1 est toujours de type 'specific' et montre le lieu ou l'objet du sujet : c'est l'image d'ouverture. Ne répète pas le même 'location_name' plus de 2 fois : alterne lieux précis (scene_type 'specific') et ambiances (scene_type 'generic' avec un 'stock_search' évocateur : objets, mains, archives, nuit, pluie...).
9. RE-HOOK OBLIGATOIRE : La scène {rehook_scene} doit contenir une phrase de rupture qui relance la curiosité (ex: 'Mais ce n'est pas la le plus troublant...').
10. PHRASE FINALE : Génère un champ 'closing_cta' indépendant dans le JSON, une phrase courte (6-10 mots) qui pose au spectateur une question précise sur CETTE histoire, à laquelle il peut répondre en commentaire (ex : « Et vous, l'auriez-vous rendu ? »). Jamais « abonnez-vous », jamais « likez », jamais d'annonce de la prochaine vidéo.
11. Les clés 'mood' doivent être choisies parmi : "ominous", "intriguing", "tense", "awe", "scientific", "investigation".
12. Les clés 'role' doivent être choisies parmi : "hook", "tension", "context", "value", "escalation", "reveal", "cta".

FORMAT DE SORTIE ATTENDU :
Retourne un JSON avec les clés : title, on_screen_title, visual_identity, audio_profile, closing_cta, scenes.
'on_screen_title' : le bandeau affiché en gros pendant TOUTE la vidéo, et lu sur la miniature. Format obligatoire « CONSTAT | CHUTE » : deux segments séparés par une barre verticale, 2 à 4 mots et 18 caractères au plus par segment. Le premier pose le fait, le second le renverse ou le chiffre. Compréhensible sans le son et sans avoir vu la vidéo. Pas de question, pas de ponctuation finale (ex : « MONT-SAINT-MICHEL | 70 ANS DE PRISON », « CARCASSONNE | PROMISE AUX DÉMOLISSEURS », « LA JOCONDE VOLÉE | SOUS UNE BLOUSE »).
Chaque scene dans le tableau 'scenes' doit contenir : id, text, voice_direction, pause_after_ms, stock_search, image_prompt, location_name, location_country, voice_type, mood, role, scene_type, event_context.