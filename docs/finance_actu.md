# Shorts « L'éco du jour » réalisés (Capital Simple)

Format inspiré des grandes chaînes d'explication économique : **une actualité économique du jour, expliquée avec de
vrais chiffres sourcés et de vrais graphiques**, en 45 à 60 s. Pas de calcul théorique (c'est le format automatique),
pas de conseil : on explique ce qui se passe et ce que ça change pour le spectateur.

Le réalisateur (Claude, dans la tâche `direct_finance` du workflow `generator_video.yml`) cherche l'actualité, vérifie
chaque chiffre et écrit `plan.json` ; le moteur `auracontent/actu` fait le reste (voix de Rémy, images, musique).

```
episodes/finance/<AAAA-MM-JJ>-<slug>/
  plan.json            écrit par le réalisateur (versionné)
  voice/timing.json    minutage de la voix (versionné) ; voice/voice.wav non versionné
  stills.jpg           planche de contrôle (versionnée)
  out/<slug>.mp4       vidéo finale (non versionnée, envoyée sur Hugging Face)
```

Commandes (depuis la racine) :

```bash
uv run python -m auracontent.actu.cli episodes/finance/<épisode> check     # contrôle bloquant du plan
uv run python -m auracontent.actu.cli episodes/finance/<épisode> voice     # voix de Rémy (Edge TTS)
uv run python -m auracontent.actu.cli episodes/finance/<épisode> stills    # planche stills.jpg
uv run python -m auracontent.actu.cli episodes/finance/<épisode> render    # vidéo
uv run python -m auracontent.actu.cli episodes/finance/<épisode> upload    # Hugging Face -> publisher
```

`voice --preview` donne un minutage estimé sans réseau (pour régler la planche) ; une vidéo faite ainsi est muette et
`upload` la refuse. Modèle complet : `episodes/finance/_exemple/plan.json`.

---

## 1. Choisir l'actualité

- **Une info économique publiée dans les 7 derniers jours** (idéalement aujourd'hui ou hier), qui touche le portefeuille
  ou la vie d'un Français : inflation, taux d'intérêt (BCE, crédit immobilier, Livret A), dette et budget, chômage,
  salaires, prix de l'énergie ou du carburant, immobilier, retraites, impôts, croissance, faillites, prix alimentaires,
  marchés quand ils font la une. France d'abord ; une info mondiale si elle a un effet concret en France.
- Cherche avec WebSearch (« Insee publication aujourd'hui », « Banque de France », « BCE décision taux », « inflation
  France novembre 2026 »...) et lis les articles avec WebFetch.
- Il faut **un chiffre fort et une série ou une comparaison montrable** (courbe sur plusieurs années, avant/après).
  Sans données à montrer, change de sujet.
- Pas de doublon : lis les `plan.json` de `episodes/finance/` et évite le même sujet que les 5 derniers épisodes
  (sauf chiffre nouveau qui change l'histoire).

## 2. Vérifier les chiffres (règle d'or : aucun chiffre sans source)

- **Source primaire d'abord** : Insee, Banque de France, BCE, Eurostat, ministère de l'Économie, Cour des comptes,
  Assemblée nationale ou Sénat, Dares, Drees, OCDE, FMI, CRE (énergie), entreprises (communiqués officiels).
  La presse (AFP, Les Échos, Le Monde, Le Figaro, Reuters...) sert à trouver l'info et à la dater ; le chiffre affiché
  vient de la source primaire dès qu'elle existe.
- Chaque source va dans `"sources"` : `{"cle": {"name": "Insee, dette trimestrielle T2 2026 (29/09/2026)", "url": "https://..."}}`.
  `name` dit qui et quand : il est affiché sous le graphique et repris dans la légende.
- **Chaque phrase qui contient un chiffre porte `"source": "<clé>"`** ; un chiffre calculé par toi porte `"calc"` avec le
  calcul et les clés des chiffres utilisés (« 3 595,5 Md€ (insee_t2) / 69 082 000 habitants (insee_pop) = 52 047 € »).
  `check` refuse un plan qui ne le fait pas.
- Les points d'une courbe sont **recopiés d'un tableau de la source**, jamais lus à l'œil sur un graphique ni inventés.
  Une prévision se dit « prévu », « selon le gouvernement ».
- Arrondis honnêtes : « près de 65 » pour 64,7 ; « presque le double » pour 1,98 fois ; jamais l'inverse.

## 3. Neutralité et règles de la chaîne

- On explique, on ne juge pas : aucun parti, aucun responsable politique désigné comme coupable. Une opinion est
  attribuée (« selon le gouvernement », « pour la Cour des comptes »).
- Aucun conseil ni ordre (achète, investis, place, vends, emprunte, souscris...), aucune promesse (rendement garanti,
  sans risque, devenir riche) : `check` les refuse. Aucun produit financier recommandé.
- Pas de ton catastrophiste : les faits suffisent (« jamais vu depuis 1978 » si la source le dit).
- La carte de fin affiche d'office « Contenu pédagogique, pas un conseil en investissement. »

## 4. Écrire la voix (`"lines"`)

- **120 à 150 mots prononcés** (montants comptés en toutes lettres), 45 à 60 s. Une entrée = une phrase de 3 à 15 mots.
- Structure : **accroche chiffrée** (phrase 0 : le chiffre choc de l'actu) → contexte en 2 ou 3 phrases (d'où ça vient,
  la courbe) → **le vrai problème / le retournement** (« Mais le vrai problème… ») → **ce que ça change pour toi**
  (2 ou 3 conséquences concrètes) → **chute** : la question du prochain épisode (« Demain : … »).
- Tutoiement, phrases courtes, aucun jargon sans explication (« le PIB, tout ce que le pays produit en un an »).
- Chiffres en chiffres dans `text` (sous-titres en or), espace insécable entre milliers (« 52 000 ») ; **`say`
  obligatoire dès qu'il y a un chiffre** : la phrase telle que Rémy doit la lire (« cinquante-deux mille euros »,
  « deux mille vingt-six », « cent vingt et un virgule sept pour cent »).
- `"pause"` : silence après la phrase (défaut 0,3 s) ; 0,5 à 0,7 s avant le retournement et après un chiffre choc.

## 5. Les scènes (`"scenes"`)

Chaque scène commence à `"from"` (références de temps des shorts d'archives : `0`, `"L3"`, `"L3@0.5"`, `"L3.end"`,
`"w:mot@L3"`) et dure jusqu'à la suivante ; la première commence à `0`, la dernière est la carte de fin.
Un `"title"` (serif, 6 à 8 mots) s'affiche en haut de chaque scène. Les scènes de données exigent `"source"`.

| Type | Champs | Usage |
|---|---|---|
| `titre` | `title`, `number` (« 3 595 MD€ »), `sub`, `pose` | l'accroche : le chiffre choc en énorme |
| `courbe` | `chart_title`, `points` [[x, y]...], `unit`, `y_range`, `highlight_from`, `annotations` [{x, label, dx, dy}], `ref_line` {y, label}, `end_label`, `x_ticks`, `sync` | une série dans le temps |
| `barres` | `chart_title`, `bars` [{label, value, text}] (2 à 5), `highlight`, `delta` (« +46 % ») | comparaison avant/après |
| `chiffre` | `value`, `format` (« ≈ {n} € »), `calc`, `caption`, `count_at`, `pose` | un compteur qui monte |
| `points` | `items` (1 à 3 phrases courtes), `at` (une référence par carte) | conséquences pour le spectateur |
| `fin` | `kicker` (« DEMAIN »), `next` (sujet du prochain épisode), `promise` | carte de fin |

- **`sync` des courbes** : la courbe arrive à chaque `x` quand la voix le dit
  (`[{"x": 2009, "at": "L2.end"}, {"x": 2020, "at": "L3"}]`). Toujours synchroniser la crise ou l'année citée.
- `pose` du bonhomme : `choc`, `montre`, `content`, `pense`.
- Une scène par idée, 3 à 12 s. Au moins une `courbe` ou des `barres` par épisode : c'est la marque du format.
- `"header"` : la pastille du haut (« DETTE PUBLIQUE · NOV. 2026 ») ; `"keywords"` : mots en or dans les sous-titres ;
  `"mood"` : `calme` ou `tension` (musique).

## 6. Contrôle de la planche (obligatoire)

Après `voice` puis `stills`, lis `stills.jpg` (temps dans `stills_times.json`) et corrige le plan, puis relance `stills`,
tant qu'il reste :
- un texte coupé, trop petit pour un téléphone ou qui en chevauche un autre ;
- un graphique dont la courbe arrive avant ou après ce que dit la voix (règle `sync`) ;
- un chiffre affiché différent du chiffre dit ou de la source ;
- une scène vide ou qui ne montre pas ce que dit la voix.

`check` puis `stills` doivent passer sans erreur. Ne relance `voice` que si tu as changé le texte d'une phrase.

## 7. Légende et métadonnées

- `"title"` : 70 caractères au plus, la promesse de l'accroche (« La dette française a doublé en 25 ans : ce que ça change pour toi »).
- `"caption"` : 1 ou 2 phrases, puis 4 à 6 hashtags (`#economie #finance` + le sujet). Les sources et la mention
  « pas un conseil » sont ajoutées à l'upload ; `#capitalsimple` aussi.
- `"date"` : la date de l'épisode (AAAA-MM-JJ).
