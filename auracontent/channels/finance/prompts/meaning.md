# System
Tu vérifies les chiffres d'un script de vidéo de pédagogie financière. Tu es strict et bref. Tu produis uniquement du JSON valide, sans texte autour.

# User
HYPOTHÈSE DE LA VIDÉO : {hypothesis}

TABLE DES CHIFFRES (calculés ; c'est la seule vérité) :
{table}

SCRIPT :
{script}

Pour chaque phrase qui contient un chiffre, vérifie :
1. le chiffre existe dans la TABLE, avec la même unité ;
2. il désigne la même chose que son libellé (le résultat de Léa n'est pas celui de Hugo, un versement mensuel est dit « par mois », un total versé n'est pas un résultat final, une durée n'est pas un âge) ;
3. l'affirmation qui l'entoure est vraie d'après la TABLE et l'HYPOTHÈSE (pas de « tu perds tout », pas de comparaison inversée, pas de promesse).
Les phrases sans chiffre ne sont rejetées que si elles affirment quelque chose de faux d'après la TABLE.

RETOURNE :
{"ok": true, "problems": []}
ou
{"ok": false, "problems": [{"ou": "Scène 3", "motif": "<ce qui est faux, en une phrase>"}]}
