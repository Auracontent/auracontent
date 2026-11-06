# System
Tu produis uniquement du JSON valide avec exactement {n} hooks, sans aucun texte en dehors du JSON.

# User
SUJET :
{topic}

{grounding_block}

Génère {n} hooks viraux en français : courts (12 mots maximum), qui donnent envie de regarder la suite.
Varie les patterns : question, affirmation choc, paradoxe, chiffre précis, anecdote ciblée.
Chaque hook doit rester fidèle aux faits connus, sans rien inventer.

{stats_block}

Retourne ce JSON :
{"hooks": [{"text": "...", "pattern": "question|affirmation|paradoxe|chiffre|anecdote", "raison": "..."}]}