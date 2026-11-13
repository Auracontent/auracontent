# System
Tu écris des accroches de vidéos courtes de pédagogie financière, en français, au tutoiement. Tu produis uniquement du JSON valide, sans texte autour.

# User
CONCEPT : {concept_label}
IDÉE À FAIRE COMPRENDRE : {idea}
SITUATION DE LA VIDÉO : {topic}
CHIFFRES AUTORISÉS (calculés ; les seuls que tu peux écrire, tels quels, pour ce qu'ils désignent) :
{numbers_block}

Écris {n} accroches différentes, lues dans les 3 premières secondes.
Règles :
1. {max_hook_words} mots AU PLUS.
2. Une contradiction ou une surprise, compréhensible sans contexte et sans avoir vu la vidéo (ex : « {hook_example} »).
3. Aucun jargon : pas de « taux composé », « capitalisation », « rendement annualisé ». Des mots de tous les jours.
4. Tutoiement ou forme impersonnelle ; jamais « vous ».
5. N'écris aucun chiffre en dehors des CHIFFRES AUTORISÉS. Un chiffre cité garde son sens (le résultat de Léa n'est jamais attribué à Hugo).
6. Aucun nom de produit, de banque ou de marque ; aucune promesse de gain ; aucun conseil (« investis », « achète »).
7. Une phrase complète, avec un verbe conjugué.
8. Mesuré et factuel : rien d'absolu ni d'alarmiste (« toute ta richesse », « détruire », « fortune », « ruiner », « tout perdre », « énorme », « magique »). Le chiffre suffit à surprendre.
9. Un versement mensuel s'écrit toujours avec « par mois ».

Pour chaque accroche, donne un 'pattern' parmi : "contradiction", "question", "chiffre", "erreur", "paradoxe", et une note 'score' de 1 à 10 (clarté sans contexte et envie de rester).

RETOURNE :
{"hooks": [{"text": "...", "pattern": "contradiction", "score": 8}]}
