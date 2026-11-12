# System
Tu produis uniquement du JSON valide, sans texte autour. Ne montre jamais ton raisonnement.

# User
ANECDOTE (rubrique « Le saviez-vous ? » de Wikipédia) : « {anecdote} »
LÉGENDE DE SON ILLUSTRATION : « {caption} »
ARTICLE CIBLE : {target}

De quoi parle précisément l'anecdote ?
- "objet" : l'objet, l'œuvre ou le monument précis dont elle parle (une statue, un vitrail, une cloche, un pont...), nommé avec ses noms propres comme dans l'anecdote ou la légende (ex. « statue de saint Martin »).
- "edifice" : l'édifice qui contient cet objet, avec son nom complet (ex. « église Saint-Martin »), ou null.
Si l'anecdote parle de l'article cible lui-même (le monument entier, et non un objet qu'il contient), réponds "objet": "{target}" et "edifice": null.
N'invente aucun nom : chaque nom doit se lire dans l'anecdote, la légende ou le titre de l'article.

Retourne : {"objet": "...", "edifice": "..." ou null}
