# System
Tu écris des accroches de vidéos courtes de pédagogie financière, en français, au tutoiement. Tu produis uniquement du JSON valide, sans texte autour.

# User
CONCEPT : {concept_label}
IDÉE À FAIRE COMPRENDRE : {idea}
SITUATION DE LA VIDÉO : {topic}
CHIFFRES AUTORISÉS (les seuls que tu peux écrire) : {allowed_numbers}

Écris {n} accroches différentes, lues dans les 3 premières secondes.
Règles :
1. {max_hook_words} mots AU PLUS.
2. Une contradiction ou une surprise, compréhensible sans contexte et sans avoir vu la vidéo (ex : « Mettre moins d'argent… et finir avec plus. »).
3. Aucun jargon : pas de « taux composé », « capitalisation », « rendement annualisé ». Des mots de tous les jours.
4. Tutoiement ou forme impersonnelle ; jamais « vous ».
5. N'écris aucun chiffre en dehors des CHIFFRES AUTORISÉS. N'annonce aucun résultat chiffré.
6. Aucun nom de produit, de banque ou de marque ; aucune promesse de gain ; aucun conseil (« investis », « achète »).
7. Une phrase complète, avec un verbe conjugué.

Pour chaque accroche, donne un 'pattern' parmi : "contradiction", "question", "chiffre", "erreur", "paradoxe", et une note 'score' de 1 à 10 (clarté sans contexte et envie de rester).

RETOURNE :
{"hooks": [{"text": "...", "pattern": "contradiction", "score": 8}]}
