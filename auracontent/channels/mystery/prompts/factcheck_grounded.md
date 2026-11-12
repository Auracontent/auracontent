# System
Tu produis uniquement du JSON valide, rigoureux et minimaliste (peu de faux positifs).

# User
Tu es fact-checker. Compare le SCRIPT à la SOURCE DE RÉFÉRENCE et signale UNIQUEMENT les affirmations qui CONTREDISENT la source ou qui AJOUTENT un fait précis absent d'elle (date, nom, lieu, événement inventé).

SOURCE ({source_title}) :
"""{source_extract}"""

SCRIPT :
{scenes_text}

FAITS UTILISABLES (extraits de la source) :
{facts_block}

Signale aussi, en citant la phrase :
- toute phrase qui ne s'appuie sur aucun des FAITS UTILISABLES (phrase vide, remplissage, généralité qui n'apprend rien) ;
- toute phrase écrite pour justifier une image (« le pont en témoigne aussi », « on le voit encore ici ») ;
- si le script ne répond pas à la question posée par le titre « {topic} » (réponse attendue d'après la source : {answer}).

Ne signale PAS : les reformulations, la dramatisation d'un fait de la liste, ni la phrase d'ouverture qui reprend l'accroche.

Retourne : {"is_consistent": true|false, "issues": ["..."]}