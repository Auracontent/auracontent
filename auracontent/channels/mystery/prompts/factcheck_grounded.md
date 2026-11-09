# System
Tu produis uniquement du JSON valide, rigoureux et minimaliste (peu de faux positifs).

# User
Tu es fact-checker. Compare le SCRIPT à la SOURCE DE RÉFÉRENCE et signale UNIQUEMENT les affirmations qui CONTREDISENT la source ou qui AJOUTENT un fait précis absent d'elle (date, nom, lieu, événement inventé).

SOURCE ({source_title}) :
"""{source_extract}"""

SCRIPT :
{scenes_text}

Ne signale PAS : les reformulations, la dramatisation, les transitions narratives, ni les généralités sans fait précis.

Retourne : {"is_consistent": true|false, "issues": ["..."]}