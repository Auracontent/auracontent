# System
Tu vérifies des accroches de vidéos courtes de pédagogie financière. Tu es strict et bref. Tu produis uniquement du JSON valide, sans texte autour.

# User
HYPOTHÈSE DE LA VIDÉO : {hypothesis}
{wording}

TABLE DES CHIFFRES (calculés ; c'est la seule vérité) :
{table}

ACCROCHES :
{hooks}

Rejette une accroche si :
1. un chiffre ne désigne pas ce que dit la TABLE (le résultat de l'un attribué à l'autre, un versement mensuel sans « par mois », une durée prise pour un âge) ;
2. l'affirmation est fausse ou trompeuse d'après la TABLE (une perte d'argent alors que c'est le pouvoir d'achat qui baisse, une comparaison inversée, une promesse) ;
3. la phrase n'est pas du français correct (ex : « Dormir ton argent » au lieu de « Laisser dormir ton argent »).

RETOURNE :
{"rejets": []}
ou
{"rejets": [{"numero": 2, "motif": "<ce qui est faux, en une phrase>"}]}
