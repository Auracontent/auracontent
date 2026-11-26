# Shorts « expliqué par un bonhomme » réalisés (Capital Simple)

Format inspiré des chaînes d'explication à bonhomme : **un problème d'argent du quotidien que tout le monde vit,
expliqué par un bonhomme blanc sur fond noir**, avec une accroche qui pique, le mécanisme (souvent psychologique)
et une astuce concrète. 45 à 60 s en Short vertical ; le même plan peut sortir en vidéo longue 16:9 (`"format": "paysage"`).

Le personnage est **original** : bonhomme blanc à tête ronde, **écharpe verte** (couleur de Capital Simple). Ne jamais
reprendre le personnage, les miniatures ni les titres d'une autre chaîne : on reprend un format, pas une identité.

Le réalisateur (Claude, dans la tâche `direct_bonhomme` du workflow `generator_video.yml`) choisit le sujet, vérifie
les faits et écrit `plan.json` ; le moteur `auracontent/bonhomme` fait le reste (voix de Rémy, dessin, musique).

```
episodes/bonhomme/<AAAA-MM-JJ>-<slug>/
  plan.json            écrit par le réalisateur (versionné)
  voice/timing.json    minutage de la voix (versionné) ; voice/voice.wav non versionné
  stills.jpg           planche de contrôle (versionnée)
  out/<slug>.mp4       vidéo finale (non versionnée, envoyée sur Hugging Face)
```

Commandes (depuis la racine) :

```bash
uv run python -m auracontent.bonhomme.cli episodes/bonhomme/<épisode> check     # contrôle bloquant (plan + repères)
uv run python -m auracontent.bonhomme.cli episodes/bonhomme/<épisode> voice     # voix de Rémy (Edge TTS)
uv run python -m auracontent.bonhomme.cli episodes/bonhomme/<épisode> stills    # planche stills.jpg
uv run python -m auracontent.bonhomme.cli episodes/bonhomme/<épisode> render    # vidéo
uv run python -m auracontent.bonhomme.cli episodes/bonhomme/<épisode> upload    # Hugging Face -> publisher
```

`voice --preview` donne un minutage estimé sans réseau ; une vidéo faite ainsi n'a pas de voix et `upload` la refuse.
Une voix enregistrée à la main remplace Rémy : `voice/lines/00.wav`, `01.wav`... (une par phrase).
Modèle complet : `episodes/bonhomme/_exemple/plan.json`.

---

## 1. Choisir le sujet

- **Un problème d'argent que le spectateur vit lui-même** : être à découvert, ne pas arriver à épargner, les
  abonnements oubliés, les achats d'impulsion, le paiement en plusieurs fois, les soldes, la carte sans contact,
  le crédit renouvelable, la comparaison aux autres, l'argent et le stress, les frais bancaires...
- Le cœur de la vidéo est **un mécanisme** qu'on peut dessiner : un biais (biais du présent, ancrage, aversion
  à la perte, effet de dotation...), une technique commerciale, un calcul qui surprend.
- Pas de doublon : lis les `plan.json` de `episodes/bonhomme/` et évite le même sujet que les 10 derniers.

## 2. Vérifier les faits

- Un fait (une étude, un biais, une loi, un taux, un frais bancaire) est vérifié dans une source fiable :
  Banque de France, AMF, Insee, INC / 60 Millions de consommateurs, service-public.fr, institut de la finance
  comportementale, articles scientifiques (HAL, revues). Chaque source va dans `"sources"` (`name` + `url`).
- **Chaque phrase qui contient un chiffre porte `source`, `calc` ou `exemple`** :
  - `source` : la clé d'une source (fait réel) ;
  - `calc` : un calcul fait à partir de chiffres sourcés ;
  - `exemple: true` : un **montant fictif présenté comme un exemple** (« Imagine : ton salaire de 1 850 € »).
    La phrase doit le faire comprendre (« imagine », « disons », « par exemple »).
- `check` refuse un plan qui ne le fait pas, et tout chiffre sans `say`.

## 3. Règles de la chaîne

- On explique et on donne des **habitudes** de budget (mettre de côté le jour de la paie, attendre 48 h avant un achat,
  couper les abonnements inutiles). **Jamais de produit financier recommandé, jamais d'ordre d'investir**
  (achète, investis, place, vends, emprunte, souscris...), jamais de promesse (rendement garanti, sans risque, devenir
  riche) : `check` les refuse.
- Pas de moquerie du spectateur : le bonhomme vit le problème avec lui (« t'es à découvert » est un constat, pas un reproche).
- **Pas d'« abonne-toi »** ni à l'écran ni dans la voix : la fin annonce le prochain sujet, c'est elle qui donne
  envie de revenir. `check` refuse « abonne » dans un titre ou une carte de fin.
- La carte de fin affiche d'office « Contenu pédagogique, pas un conseil en investissement. »

## 4. Écrire la voix (`"lines"`)

- **Short vertical : 110 à 150 mots prononcés** (le contrôle accepte 90 à 165), soit 45 à 60 s.
  Vidéo longue (`paysage`) : 400 à 1 700 mots.
- Une entrée = une phrase de 3 à 15 mots, tutoiement, ton de grand frère, un peu d'humour, aucun jargon.
- Structure :
  1. **accroche** (phrase 0) : un constat qui pique, adressé au spectateur (« T'es à découvert, et pourtant tu gagnes ta vie. ») ;
  2. **la situation** en 3 à 5 phrases, avec un exemple chiffré qu'on voit (salaire, dépenses) ;
  3. **le retournement** : « Le problème, ce n'est pas X. C'est Y. » puis le mécanisme en 2 ou 3 phrases ;
  4. **l'astuce** : une habitude concrète, montrée ;
  5. **la suite** : le sujet du prochain épisode (« La suite : comment tenir jusqu'au 30 sans te priver. »).
- Chiffres en chiffres dans `text`, **`say` obligatoire dès qu'il y a un chiffre** (la phrase telle que Rémy la lit).
- `"pause"` : silence après la phrase (défaut 0,3 s) ; 0,5 à 0,6 s après l'accroche, avant le retournement et avant la suite.

## 5. Les scènes (`"scenes"`)

Chaque scène commence à `"from"` (références de temps : `0`, `"L3"`, `"L3@0.5"`, `"L3.end"`, `"w:mot@L3"`, `"L3+0.4"`)
et dure jusqu'à la suivante. La première est une `accroche` à `0`, la dernière une `fin`.

Champs communs :
- `title` : la phrase clé écrite à la main en haut (60 caractères au plus ; c'est aussi ce que lit un spectateur sans
  le son, donc elle résume la voix) ; `title_color` (`blanc`, `rouge`, `jaune`, `vert`, `or`, `gris`) ; `title_at`.
- `title2` : une 2e ligne qui arrive plus tard (jaune par défaut), `title2_at`, `title2_color`.
- `bonhomme` : `expr` (`neutre`, `content`, `triste`, `choc`, `stresse`, `pense`, `fier`), `arms` (`bas`, `haut`,
  `tete`, `montre`, `pouce`, `salut`, `menton`), `pos` (`gauche`, `centre`, `droite` ; vertical seulement), `cache`,
  et **`reactions`** : `[{"at": "L5", "expr": "stresse"}, {"at": "L6@0.5", "arms": "tete", "hop": true}]`.
  `stresse` ajoute une goutte de sueur ; `hop` le fait sauter (avec un bruitage).
- `pluie` : pluie grise sur toute l'image (coup dur).

| Type | Champs | Usage |
|---|---|---|
| `accroche` | `title` (en rouge, énorme), `carte` (« -312 € » sur une carte bancaire), `carte_at`, `sous_titre`, `sous_titre_at` | la 1re image : le problème |
| `compteur` | `value`, `start`, `format` (« {n} € »), `count_at`, `count_seconds`, `color`, `legende`, `pieces` (`pile` ou `fuite`) | un montant qui monte ou qui fond |
| `notifications` | `items` (1 à 5, « Livraison -24 € »), `at` (une référence par notification), `compteur` {`start`, `value`, `format`, `fuite`} | les petites dépenses qui s'accumulent |
| `choix` | `left` / `right` {`label`, `value`, `at`, `couleur`}, `cerveau` (bulle avec un cerveau, oui par défaut), `pick` (0 ou 1), `pick_at`, `pick_label` | deux options, le cerveau choisit |
| `repartition` | `source_label` (« salaire »), `parts` (1 à 3) {`label`, `at`, `couleur`, `bocal`, `fill`} | où part l'argent (épargne d'abord) |
| `liste` | `items` (1 à 3 phrases courtes), `at` | 2 ou 3 conseils ou conséquences |
| `fin` | `kicker` (« la suite : »), `next` (le prochain sujet) | carte de fin, le bonhomme salue |

- **Une scène par idée, 4 à 12 s**, et l'image suit la voix : chaque élément arrive quand la voix le dit (`at`, `count_at`,
  `pick_at` sur le mot exact avec `w:mot@Lx`). Le bonhomme **réagit** au moins une fois par scène.
- Un montant affiché (carte, compteur, notifications, boîtes) est le même que celui dit dans la voix.
- `"mood"` : `calme` ou `tension` (musique) ; `"format"` : `vertical` (défaut) ou `paysage`.

## 6. Contrôle de la planche (obligatoire)

Après `voice` puis `stills`, lis `stills.jpg` (temps dans `stills_times.json`), corrige le plan et relance `stills` tant qu'il reste :
- un texte coupé, trop petit pour un téléphone, ou qui chevauche le bonhomme ou un autre texte ;
- un élément qui arrive avant ou après ce que dit la voix ;
- un montant affiché différent du montant dit ;
- une scène où le bonhomme ne réagit pas, ou qui ne montre pas ce que dit la voix.

`check` puis `stills` doivent passer sans erreur. Ne relance `voice` que si tu as changé le texte d'une phrase.

## 7. Légende et métadonnées

- `"title"` : 70 caractères au plus, au format « Pourquoi t'es toujours à découvert (expliqué par un bonhomme) ».
- `"caption"` : 1 ou 2 phrases, puis 4 à 6 hashtags (`#finance #argent` + le sujet). Les sources, la mention
  « pas un conseil » et `#capitalsimple` sont ajoutées à l'upload.
