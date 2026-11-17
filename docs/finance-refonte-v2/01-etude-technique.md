# Refonte V2 de Capital Simple – Étape 1 : étude technique

Branche : `feat/finance-refonte-v2` (créée depuis `feat/finance-video`, commit cb2132a).
Périmètre : chaîne finance uniquement. Aucune modification de mystery.

## 1. Point de départ : le moteur actuel est déjà un moteur d'animation

Le rendu finance repose sur `auracontent/services/visuals/linework/engine.py` (Pillow + FFmpeg) :

- calques texte, image, trait, flèche, surligneur ;
- animation par images clés (x, y, largeur, hauteur, angle, opacité, progression, échelle) avec lissage « smoothstep » ;
- compteurs qui défilent (`count`) ;
- traits qui se dessinent progressivement ;
- contrôle de mise en page bloquant (zones sûres) ;
- repères d'effets sonores calés sur l'action (`sfx_cues`) ;
- fondus entre scènes dans le compositeur.

Ce qui manque pour la V2 :

| Besoin de la section 11 | État actuel |
|---|---|
| Chiffres synchronisés avec la voix | Non : la scène dure le temps de la voix, mais aucune animation n'est calée sur un mot |
| Sous-titres mot par mot | Non |
| Courbes d'accélération variées (rebond, élan) | Une seule (smoothstep) |
| Mouvements de caméra (zoom, panoramique) | Non |
| Transitions variées | Fondu uniquement |
| Objets du quotidien | Non : 16 accessoires seulement (pièces, plantes, horloge, notes) |
| Mises en scène propres à chaque sujet | Non : un storyboard générique commun aux 12 nouveaux calculs |

## 2. Mesures (machine de travail, 2 cœurs, sans GPU, comparable à un runner GitHub standard)

Scène de 6 s en 1080 × 1920, 30 images/s :

| Outil | Scène testée | Temps de rendu | Rapport au temps réel |
|---|---|---|---|
| Moteur actuel (Pillow + FFmpeg) | barres avec compteurs | 4,3 s | 0,7 × |
| Moteur actuel | courbe avec graduations | 4,8 s | 0,8 × |
| Moteur actuel | personnages | 3,4 s | 0,6 × |
| Manim Community 0.20 | 3 barres qui montent + 3 compteurs + une ligne | 9,6 s (démarrage compris) | 1,6 × |

Une vidéo de 40 s se rend donc en environ 30 s avec le moteur actuel. La marge sous la limite de 10 minutes est très grande : on peut enrichir fortement les animations.

## 3. Comparaison

| Critère | Étendre le moteur actuel | Manim Community | MoviePy |
|---|---|---|---|
| Qualité d'animation possible | Bonne, à condition d'ajouter courbes d'accélération, caméra et transitions | Excellente pour courbes, formes et chiffres | Faible : outil de montage, pas d'animation |
| Style « dessin à la main » Capital Simple | Natif (sprites, police Caveat, papier quadrillé) | À recréer : rendu vectoriel net, plus « mathématique » | Dépend des images fournies |
| Contrôle de mise en page et zones sûres | Déjà en place et testé | À réécrire | À réécrire |
| Temps de rendu | 0,6 à 0,8 × le temps réel | Environ 1,6 × | Plus lent que FFmpeg direct |
| Dépendances | Aucune nouvelle | Pango, Cairo, pkg-config (apt) + manimpango à compiler : 1 à 2 min d'installation par run | Légère |
| Intégration au pipeline | Directe | Second moteur à maintenir à côté du premier | N'apporte rien que FFmpeg ne fasse déjà |
| Tests existants | Conservés | À recréer | À recréer |

## 4. Recommandation

**Étendre le moteur actuel**, plutôt que d'ajouter Manim ou MoviePy.

Raisons :

1. Il est déjà rapide, testé, intégré et fidèle à l'identité visuelle.
2. Manim apporterait de belles courbes, mais au prix d'un second moteur, de dépendances système à chaque run et d'un style à recréer. Les animations dont on a besoin (barres, courbes, compteurs, objets qui tombent) se font très bien en procédural avec Pillow.
3. MoviePy ne fait que du montage, ce que FFmpeg fait déjà.

Manim reste une option pour plus tard, seulement si un sujet demande une animation mathématique impossible à faire proprement autrement.

## 5. Ce que la V2 ajouterait au moteur (toutes les options en opt-in pour finance)

1. **Horodatage des mots** : récupérer les événements `WordBoundary` d'Edge TTS (déjà utilisé par le pipeline) pour connaître l'instant de chaque mot.
2. **Timeline pilotée par la voix** : chaque animation peut être déclenchée « au mot X » (ex. le compteur démarre quand la voix dit « 1 768 »).
3. **Sous-titres mot par mot** avec le mot prononcé surligné, dessinés par le moteur.
4. **Bibliothèque de courbes d'accélération** : élan, rebond, ressort, linéaire, en plus de smoothstep.
5. **Caméra** : zoom et panoramique sur l'ensemble de la scène (gros plan sur un chiffre, retour au plan large).
6. **Transitions** : glissement, zoom, volet, en plus du fondu, choisies par le storyboard.
7. **Bibliothèque d'objets du quotidien**, dessinés dans le style actuel : tasse, billet, tirelire, carte bancaire, téléphone, ticket de caisse, caddie, valise, maison, voiture, calendrier, applis génériques.
8. **Systèmes d'objets** : pièces qui tombent dans une tirelire, tasses qui s'empilent, ticket qui s'allonge, avec le nombre d'objets calculé à partir des chiffres de calc.py.
9. **Mises en scène par sujet** : chaque calcul déclare ses mises en scène compatibles ; le moteur évite de reprendre celle des dernières vidéos.
10. **Boucle de fin** : la dernière image renvoie à la première.
11. **Sons** : musique et effets sous licence CC0 uniquement, licence notée pour chaque fichier.

## 6. Points à vérifier pendant l'étape 2

- Que la version d'Edge TTS utilisée fournit bien les horodatages mot par mot pour la voix Rémy.
- Le temps de rendu réel d'une vidéo pilote complète (voix, sous-titres, caméra, transitions) sur GitHub Actions.
- La lisibilité des sous-titres mot par mot et des objets sur un téléphone.

## 7. Étape suivante (après validation)

Étape 2 : composants de base + vidéo pilote « Abonnements cumulés » en 3 versions (A : style actuel animé ; B : objets et personnages, graphique minimal ; C : dynamique), avec la grille d'évaluation de la section 11.
