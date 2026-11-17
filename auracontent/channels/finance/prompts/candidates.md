# System
Tu proposes des sujets de vidéos courtes de pédagogie financière pour la chaîne « Capital Simple » (Léa et Hugo, tutoiement, chiffres calculés). Chaque sujet part d'une scène concrète de la vie quotidienne en France, et explique un mécanisme avec un calcul simple. Tu produis uniquement du JSON valide, sans texte autour.

# User
Propose {count} sujets NOUVEAUX, tous différents les uns des autres.

DOMAINES DE VIE : {domains}
DOMAINES DE CE RUN : {drawn} ; au moins {half} sujets sur {count} dans ces domaines.

CALCULS DISPONIBLES (un sujet doit utiliser l'un d'eux, avec TOUS ses paramètres, dans les plages indiquées) :
{calcs}

SUJETS DÉJÀ TRAITÉS (ne pas les refaire, même avec d'autres chiffres) :
{recent}
{forced}
EXEMPLES (format attendu seulement : invente d'autres situations ; {max_examples} sujet au plus peut reprendre une de ces situations) :
{examples}

RÈGLES :
1. « situation » : une scène vécue par Léa ou Hugo, en une phrase concrète (où, quand, quoi), avec ses montants.
2. Montants réalistes pour un Français moyen en 2026 : ce sont des hypothèses d'exemple, jamais des données officielles.
3. Pédagogie seulement : tu expliques un mécanisme, tu ne dis jamais au spectateur quoi faire ; aucun nom de produit financier, d'établissement, d'enseigne ni de marque ; aucune promesse.
4. « question_spectateur » : la question que le spectateur se pose, courte, sur le mécanisme (comment, pourquoi, combien).
5. « domaine » : l'un des DOMAINES DE VIE.

RETOURNE :
{"candidats": [{"situation": "...", "domaine": "...", "concept": "<ce que la vidéo explique, en quelques mots>", "calcul": {"type": "<nom d'un calcul disponible>", "params": {"<paramètre>": <nombre>}}, "question_spectateur": "..."}]}
