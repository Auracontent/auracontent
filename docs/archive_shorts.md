# Shorts d'archives réalisés (« C'est arrivé ici »)

Un short d'archives est **réalisé**, pas assemblé : une histoire forte, une archive choisie pour chaque phrase,
une caméra qui va vers ce dont parle la voix, des tampons posés sur le mot, une voix dirigée avec de vrais silences.
Le réalisateur (Claude, dans la tâche `direct` du workflow `generator_video.yml`) écrit `plan.json` ; le moteur `auracontent/archive` fait le reste.

```
episodes/archive/<AAAA-MM-JJ>-<slug>/
  plan.json            écrit par le réalisateur (versionné)
  img/<clé>.jpg        archives Commons (téléchargées, non versionnées) + img/credits.json (versionné)
  voice/voice.wav      voix recomposée (non versionnée) + voice/timing.json (versionné)
  stills.jpg           planche de contrôle (versionnée)
  out/<slug>.mp4       vidéo finale (non versionnée, envoyée sur Hugging Face)
```

Commandes (depuis la racine) :

```bash
uv run python -m auracontent.archive.cli episodes/archive/<épisode> fetch    # archives
uv run python -m auracontent.archive.cli episodes/archive/<épisode> voice    # voix Gemini dirigée
uv run python -m auracontent.archive.cli episodes/archive/<épisode> stills   # planche stills.jpg
uv run python -m auracontent.archive.cli episodes/archive/<épisode> render   # vidéo
uv run python -m auracontent.archive.cli episodes/archive/<épisode> upload   # Hugging Face -> publisher
```

Modèle complet : `episodes/archive/_exemple/plan.json`.

---

## 1. Choisir l'affaire

- Ligne de la chaîne : un **lieu ou un objet du patrimoine français** réel, nommable et montrable (trésor perdu, monument à
  l'histoire cachée, édifice au destin improbable, loi absurde liée à un lieu, découverte archéologique, disparition,
  exploit oublié). Outre-mer compris. Pas de fait divers criminel, pas de science générale.
- Il faut une **vraie histoire** : un paradoxe ou un retournement qu'on peut dire en une phrase
  (« La France a fêté une victoire qui n'a jamais eu lieu »). Une simple curiosité ne suffit pas.
- Il faut **au moins 6 archives libres** sur Wikimedia Commons : photos anciennes, cartes postales, gravures, unes de journaux,
  plans, cartes. Vérifie-le AVANT d'écrire (recherche Commons). Sans archives, change de sujet : pas d'image IA, pas de banque d'images.
- Pas de doublon : lis les `plan.json` de `episodes/archive/` (titres et sources) et évite le même sujet, le même lieu
  ou la même époque que les 3 derniers épisodes.

## 2. Vérifier les faits

- Source principale : l'article Wikipédia FR, plus au moins une autre source (Wikipédia EN, musée, archives, presse).
- Chaque date, chiffre, nom et lieu de la voix est vérifié dans une source. Une légende se dit « on raconte que ».
- Les URL vont dans `"sources"`.

## 3. Écrire la voix (`"lines"`)

- **130 à 160 mots**, 45 à 60 s. Une entrée de `lines` = une phrase de 6 à 15 mots (une phrase très courte est permise :
  « Rien. », « Sauf que… »).
- Structure : **accroche** paradoxale (phrase 0) → 2 ou 3 détails qui montent → **retournement** sur sa propre ligne
  (« Sauf que… », « Mais… ») → conséquence → **chute** courte au dernier mot.
- Dates et nombres en chiffres dans `text` (« le 10 mai 1927 ») : les sous-titres les montrent en jaune. Si la lecture peut
  hésiter (« 25 000 $ », « 5 h 17 », chiffres romains, sigles), écris aussi `"say"` : la phrase telle qu'elle doit être
  prononcée (« vingt-cinq mille dollars »). `say` sert à la voix, `text` aux sous-titres.
- Aucune phrase ne décrit ce qu'on voit déjà. Pas d'adjectifs creux (majestueux, fascinant, emblématique…).
- `"pause"` : silence après la phrase (défaut `voice.pause`, 0,35 s). 0,6 à 0,9 s avant le retournement et après une
  révélation. C'est ce qui fait le ton documentaire.
- `"direction"` : seulement sur 1 à 3 phrases clés (« Almost whispered, one word, final. »).

## 4. Diriger la voix (`"voice"`)

- `"name"` : la voix maison est **Charon** (grave, posée). Autres voix Gemini possibles si l'histoire l'exige :
  Orus (ferme), Iapetus (claire), Algenib (rauque), Kore (féminine, ferme), Gacrux (féminine, mûre), Sulafat (féminine, chaude).
- `"style"` : une consigne en anglais **propre à l'histoire** : ton (grave pour une disparition, amusé pour une loi absurde,
  admiratif pour un exploit), rythme, où ralentir. Jamais la même consigne d'un épisode à l'autre.
- `"tempo"` (facultatif, 0,9 à 1,05) : ralentit ou accélère la voix sans changer sa hauteur.
- Si Gemini échoue, l'étape échoue : aucune voix de secours robotique n'est publiée.

## 5. Choisir et cadrer les archives

- `"images"` : `{"<clé>": "File:<nom exact sur Commons>"}`. Licences libres uniquement (le téléchargement vérifie).
- Après `fetch`, **regarde chaque image** (Read sur `img/<clé>.jpg`) et note où sont les visages, l'objet, le détail utile :
  ces coordonnées (0 à 1) servent aux cadrages.
- Une archive par idée : chaque phrase montre ce qu'elle dit. Une étiquette ne nomme que ce qui est vraiment sur la photo
  (si la photo montre le fils, l'étiquette ne dit pas « sa mère »).

## 6. Les plans (`"shots"`)

Bornes en références de temps : `0`, `"L3"`, `"L3@0.5"`, `"L3.end"`, `"w:mot@L3"`, `"end"`, `"fin"`, avec décalage `"L3+0.4"`.
Les plans se suivent sans trou, du `0` à `"fin"` (carton final compris).

| Type | Usage |
|---|---|
| `image` | `keys: [[u, cx, cy, h], ...]` : la caméra va vers le sujet de la phrase. `h` 1,0 = image entière, 0,35 = détail. `fx`: `gray` (le faux, le passé), `dark`, `shake` (décollage, explosion) |
| `split` | deux personnes ou avant/après : `top`, `bottom`, `labels` |
| `map` | carte ancienne : `bbox`, `cam`, `pins` (apparaissent sur un mot), `route` (trajet, croix à l'arrivée), `names`, `fog` |
| `fog` | brouillard : disparition, océan, ellipse |
| `sign` | plaque de rue ou inscription : `lines` |
| `card` | carton daté : `title`, `sub` |

Règles :
- Un plan par phrase en général, deux pour une phrase longue. Jamais plus de 4 s d'image sans mouvement.
- Le premier plan est l'archive la plus forte, sous l'accroche.
- Une image ne revient pas deux fois de suite. Une même image peut revenir plus tard avec un autre cadrage.
- Les cadrages extrêmes (`h` < 0,35) floutent les petites images : vérifie sur la planche.

## 7. L'habillage

- `"hook"` : 2 ou 3 lignes de 22 caractères au plus, affichées 3,6 s ; la dernière (en jaune) est le retournement.
- `"header"` : le sujet et l'année (« L'OISEAU BLANC · 1927 »), affiché ensuite en haut.
- `"stamps"` : 1 à 3 tampons rouges au plus (`FAUX`, `DISPARUS`, `43 VICTOIRES`), posés sur le mot (`"at": "w:Rien@L6"`),
  jamais sur un visage : `"y"` (défaut 1060) se règle d'après la planche.
- `"labels"` : noms, lieux, dates (30 caractères au plus), le temps du plan.
- `"flash"` : flash blanc sur le retournement (`["L5"]`).
- `"keywords"` : noms propres et mots forts, en jaune dans les sous-titres (les chiffres le sont d'office).
- `"end_title"` : le nom de l'affaire sur le carton final (« le documentaire complet sur la chaîne »).
- Zones sûres de la chaîne : rien d'important au-dessus de y = 200, sous y = 1440 ni à droite de x = 930. Le moteur les respecte
  (filigrane en haut à gauche, sous-titres à y = 1344).

## 8. La musique (`"music"`)

`sections` (nappes + piano : `Dm` grave, `Am` mystère, `Dmaj` résolution), `pulse` (battement pendant la tension),
`rise` (montée jusqu'au choc), `drone` (bourdon après un choc), `hits` (impacts : retournement, révélation).
Le moteur ajoute un impact sur chaque tampon, un souffle à chaque coupe et un impact final, puis mixe à -14 LUFS.

## 9. Contrôle de la planche (obligatoire)

Après `stills`, lis `stills.jpg` (temps des images dans `stills_times.json`) et corrige le plan puis recommence, tant qu'il reste :
- un tampon, une étiquette ou un sous-titre sur un visage ;
- une étiquette qui ne correspond pas à la photo ;
- une image floue (cadrage trop serré sur une petite image) ou sans rapport avec la phrase ;
- un texte coupé au bord, une carte dont le repère sort de l'écran ;
- deux images de suite presque identiques.

## 10. Légende et métadonnées

- `"title"` : 70 caractères au plus, la promesse de l'accroche.
- `"caption"` : 1 ou 2 phrases qui donnent envie, puis 4 à 6 hashtags (`#histoire #france` + le sujet). Le hashtag de marque
  `#cestarriveici` est ajouté à l'upload.
