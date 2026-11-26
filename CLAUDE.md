# AuraContent : consignes pour Claude

Pipeline de Shorts / TikTok sans visage, en français. Deux chaînes : `mystery` (« C'est arrivé ici », patrimoine français)
et `finance` (« Le Fric en Clair », ex-« Capital Simple »). Voir README.md pour l'architecture.

## Règles du dépôt
- Messages de commit au format **conventional commits** (`feat(mystery): …`, `fix(finance): …`, `chore: …`, `docs: …`) :
  semantic-release s'en sert pour les versions. Description en français ou en anglais, courte.
- Avant de pousser : `uv run ruff check --select F821,F811,F823 .` et `uv run pytest -q`.
- Les YAML de `config/channels/` ne contiennent que des NOMS de variables d'environnement, jamais de secret.
- Ne jamais lancer `auracontent.cli.publish` hors du workflow `publisher.yml` : il publie publiquement.

## Shorts d'archives réalisés (chaîne mystery)
Quand on te demande de réaliser un short (tâche `direct` du workflow `generator_video.yml`, ou à la main), suis **docs/archive_shorts.md** à la lettre :
choix de l'affaire, vérification des faits, voix dirigée, archives Commons, plans, habillage, musique, contrôle de la planche.
Modèle : `episodes/archive/_exemple/plan.json`. Moteur : `auracontent/archive/` (CLI `python -m auracontent.archive.cli`).

- Tout fait (date, chiffre, nom, lieu) est vérifié dans une source citée dans `plan.json` ; une légende est dite « on raconte que ».
- Uniquement des archives libres de Wikimedia Commons : jamais d'image générée par IA ni de banque d'images dans ce format.
- Le contrôle de la planche `stills.jpg` est obligatoire : lis-la, corrige le plan, recommence jusqu'à ce qu'elle soit propre.
- Si quelque chose bloque (pas assez d'archives, voix Gemini indisponible, faits invérifiables), écris le problème dans
  `PROBLEME.md` dans le dossier de l'épisode, commite et arrête-toi : ne publie jamais un short au rabais.

## Shorts « expliqué par un bonhomme » (chaîne finance)
Quand on te demande un short « bonhomme » pour Le Fric en Clair (tâche `direct_bonhomme` du workflow `generator_video.yml`,
variable `FINANCE_MODE=bonhomme` ou case « finance_bonhomme », ou à la main), suis **docs/finance_bonhomme.md** à la lettre.
Modèle : `episodes/bonhomme/_exemple/plan.json`. Moteur : `auracontent/bonhomme/` (CLI `python -m auracontent.bonhomme.cli`).

- Chaque chiffre de la voix porte `source`, `calc` ou `exemple` (montant fictif dit comme un exemple) ; jamais d'ordre
  d'investir, de produit recommandé ni d'« abonne-toi ».
- Chaque épisode tient la suite annoncée par le précédent (`cli episodes/bonhomme suite`, champ `suite_de`) ;
  un sujet imposé est `hors_suite` et réannonce la même suite.
- Le bonhomme est celui du logo de Le Fric en Clair (blanc, corps plein, pièce d'or, « ?! ») ; ton franc, « sans langue
  de bois ». Ne copie jamais le personnage d'une autre chaîne.
- Le contrôle de la planche `stills.jpg` est obligatoire, comme pour les autres formats réalisés.
- Ce format ne touche à rien de la chaîne mystery (ni `auracontent/archive/`, ni `episodes/archive/`, ni `config/channels/mystery.yaml`).
