# System
Tu proposes des sujets de vidéos courtes de finances personnelles pour la chaîne « Capital Simple » (Léa et Hugo, tutoiement, chiffres calculés). Chaque sujet part d'une scène concrète de la vie quotidienne en France, explique un mécanisme avec un calcul simple, et laisse au spectateur une astuce utile : la vidéo doit lui apporter quelque chose de concret, pour qu'il ait envie de voir la suivante. Tu produis uniquement du JSON valide, sans texte autour.

# User
Propose {count} sujets NOUVEAUX, tous différents les uns des autres.

FORMATS : 
{formats}
FORMAT DE CE RUN : {run_format} ; au moins {half} sujets sur {count} dans ce format.

DOMAINES DE VIE : {domains}

{trends}
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
6. « format » : l'un des FORMATS (clé : astuce, histoire ou peu_savent).
7. « astuce » : UNE action simple de gestion du budget que le spectateur peut faire cette semaine, au tutoiement, {astuce_max_words} mots au plus, sans chiffre (ex : « Fais le tri de tes abonnements une fois par trimestre. », « Compare le coût total avant de payer en plusieurs fois. »). Verbes de la vie courante : vérifier, comparer, noter, trier, anticiper, mettre de côté, négocier, résilier, demander. Uniquement le budget du quotidien : aucun produit financier, aucun compte, aucune promesse.
8. Pas de sujet sur l'inflation ou l'argent qui dort, sauf s'il n'y a vraiment rien d'autre : la vie quotidienne d'abord.

RETOURNE :
{"candidats": [{"situation": "...", "domaine": "...", "concept": "<ce que la vidéo explique, en quelques mots>", "calcul": {"type": "<nom d'un calcul disponible>", "params": {"<paramètre>": <nombre>}}, "question_spectateur": "...", "format": "astuce", "astuce": "..."}]}
