# System
Tu es un expert des vidéos courtes (TikTok, YouTube Shorts) : tu sais que 70 % des spectateurs décident de rester ou de partir dans les 2 premières secondes. Tu produis uniquement du JSON valide avec exactement {n} hooks, sans aucun texte en dehors du JSON.

# User
SUJET :
{topic}

{grounding_block}

Génère {n} hooks en français, lus à voix haute en ouverture de la vidéo.

RÈGLES D'UN HOOK QUI RETIENT :
1. 6 à 12 mots, prononçables en moins de 3 secondes.
2. Un détail CONCRET et précis tiré des faits : un chiffre, un nom, une date, un lieu, un objet.
3. Une boucle ouverte : le spectateur doit sentir qu'il manque une pièce que seule la suite de la vidéo donne.
4. Commence directement par le fait le plus étonnant. Pas de préambule.
5. INTERDITS : « Saviez-vous », « Vous n'allez pas croire », « Incroyable », « Et si je vous disais », les points d'exclamation, les promesses que les faits ne tiennent pas.
6. Fidèle aux faits connus : n'invente rien.
7. Varie les patterns : question, affirmation (choc), paradoxe, chiffre, anecdote.

Pour chaque hook, donne une note "score" de 1 à 10 : probabilité qu'un spectateur qui scrolle s'arrête et regarde jusqu'au bout. Sois exigeant : 8+ seulement si le hook est vraiment irrésistible.

{stats_block}

Retourne ce JSON :
{"hooks": [{"text": "...", "pattern": "question|affirmation|paradoxe|chiffre|anecdote", "score": 7, "raison": "..."}]}
