# Refonte V2 de Capital Simple – Étape 2 : composants et vidéo pilote

Sujet du pilote : « Abonnements cumulés » (13,49 € + 9,99 € + 5,99 € par mois, sur 5 ans), chiffres de calc.py :
29,47 € par mois, 354 € par an, 1 768 € en 5 ans.

Commande : `python -m auracontent.channels.finance.v2.pilot --out output/pilote_v2 --versions A,B,C`

## Ce qui a été construit (`auracontent/channels/finance/v2/`, finance uniquement)

| Module | Rôle |
|---|---|
| `easing.py` | 6 courbes d'accélération (smooth, linear, out, back, bounce, spring), choisies par image clé |
| `director.py` | Peintre V2 (easing + caméra : zoom et cadrage animés), rendu d'un plan, enchaînement des plans avec 8 transitions FFmpeg (fondu, glissements, cercle, volet, zoom, radial), mixage des effets sonores calés sur l'action, limiteur |
| `captions.py` | Minutage des mots (événements WordBoundary d'Edge TTS, ou estimation sans voix), calage d'une animation sur un mot (`find`), sous-titres mot par mot (mot prononcé en turquoise, légèrement agrandi) et bandeau, en ASS brûlé par FFmpeg |
| `props.py` | Objets du quotidien dessinés par le code dans le style trait à la main : pièce, applis génériques, étiquette de prix, téléphone, tirelire, calendrier, ticket de caisse, éclat |
| `pilot.py` | Les 3 versions du pilote |

Le moteur partagé `services/visuals/linework` n'est pas modifié (un test le vérifie).

## Mesures

Machine de travail, 2 cœurs, sans GPU (comparable à un runner GitHub standard) :

| Version | Durée | Temps de rendu | Taille | Plans |
|---|---|---|---|---|
| A – style actuel animé | 30,8 s | 68 s | 2,9 Mo | 6 |
| B – objets et personnages | 30,8 s | 49 s | 2,5 Mo | 6 |
| C – dynamique | 28,9 s | 47 s | 2,3 Mo | 6 |

Toutes les versions restent très loin de la limite de 10 minutes.

## Grille d'évaluation

| Critère | A | B | C |
|---|---|---|---|
| Compréhension du concept en un visionnage | Moyenne : barres et courbe à lire | Bonne : les étiquettes s'additionnent, le calendrier défile, le ticket totalise | Bonne |
| Lisibilité sur téléphone | Moyenne : petits textes manuscrits | Bonne : gros chiffres, objets grands | Bonne |
| Accroche des 2 premières secondes | Faible : un texte seul | Forte : applis qui tombent, gros chiffre sur un éclat | Forte, avec zoom |
| Rythme | Lent | Régulier | Rapide, peut fatiguer sur un sujet chargé en chiffres |
| Cohérence avec l'identité | Très bonne | Très bonne | Bonne |
| Complexité de maintenance | Faible (gabarits existants) | Moyenne : une mise en scène par calcul | Moyenne, plus de réglages |

## Recommandation

**Retenir B comme base, avec les gros plans de C sur les chiffres clés** (zoom avec élan au moment de la révélation). B fait comprendre le mécanisme par des objets, ce qui répond directement au constat « trop de graphiques ». C apporte de l'énergie, mais tout le rythme de C sur chaque plan risque de nuire à la compréhension.

## Limites de ce pilote

- **Pas de voix** : la synthèse Edge TTS n'est pas joignable depuis l'environnement de développement. Le minutage des mots est estimé ; sur GitHub Actions, il viendra des événements WordBoundary de la vraie voix.
- **Pas de musique** : le dépôt ne contient aucune musique sous licence libre. À ajouter (CC0) avec sa licence.
- **Mise en scène écrite à la main pour ce sujet** : la généralisation aux 17 calculs (une ou plusieurs mises en scène déclarées par calcul, choisies sans répétition) est l'étape 3.

## Étape 3 (après choix de la direction)

1. Brancher la V2 dans le pipeline finance derrière une option du YAML (`video_engine: v2`), avec les horodatages réels d'Edge TTS.
2. Écrire une mise en scène par calcul (objets et personnages, un graphique seulement si indispensable).
3. Ajouter une musique CC0 et sa licence.
4. Tests, CI verte, 3 runs GitHub réussis, puis validation avant tout merge vers main.
