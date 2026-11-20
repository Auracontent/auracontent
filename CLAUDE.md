# AuraContent : consignes pour Claude

Pipeline de Shorts / TikTok sans visage, en français. Deux chaînes : `mystery` (« C'est arrivé ici », patrimoine français)
et `finance` (« Capital Simple »). Voir README.md pour l'architecture.

## Règles du dépôt
- Messages de commit au format **conventional commits** (`feat(mystery): …`, `fix(finance): …`, `chore: …`, `docs: …`) :
  semantic-release s'en sert pour les versions. Description en français ou en anglais, courte.
- Avant de pousser : `uv run ruff check --select F821,F811,F823 .` et `uv run pytest -q`.
- Les YAML de `config/channels/` ne contiennent que des NOMS de variables d'environnement, jamais de secret.
- Ne jamais lancer `auracontent.cli.publish` hors du workflow `publisher.yml` : il publie publiquement.

## Shorts d'archives réalisés (chaîne mystery)
Quand on te demande de réaliser un short (workflow `director.yml` ou à la main), suis **docs/archive_shorts.md** à la lettre :
choix de l'affaire, vérification des faits, voix dirigée, archives Commons, plans, habillage, musique, contrôle de la planche.
Modèle : `episodes/archive/_exemple/plan.json`. Moteur : `auracontent/archive/` (CLI `python -m auracontent.archive.cli`).

- Tout fait (date, chiffre, nom, lieu) est vérifié dans une source citée dans `plan.json` ; une légende est dite « on raconte que ».
- Uniquement des archives libres de Wikimedia Commons : jamais d'image générée par IA ni de banque d'images dans ce format.
- Le contrôle de la planche `stills.jpg` est obligatoire : lis-la, corrige le plan, recommence jusqu'à ce qu'elle soit propre.
- Si quelque chose bloque (pas assez d'archives, voix Gemini indisponible, faits invérifiables), écris le problème dans
  `PROBLEME.md` dans le dossier de l'épisode, commite et arrête-toi : ne publie jamais un short au rabais.
