# Refonte V2 de Capital Simple – Étape 3 : branchement dans le pipeline

Direction retenue : B (objets et personnages) avec les zooms de C sur les chiffres clés.

## Activation

`config/channels/finance.yaml` :

```yaml
visuals:
  linework:
    engine: v2          # absent ou « v1 » : rendu actuel
video_composer:
  transitions: ["fade", "slideleft", "slideup", "circleopen", "wipeleft", "smoothleft"]
  transition_duration: 0.3
```

`FinanceBrain.build_visuals` appelle `v2.scenes.render_scenes` quand `engine: v2`. Le contrat est le même que le
rendu actuel (un clip par scène, effets dans `scene["sfx_cues"]`) : la voix, le bandeau, les sous-titres et les
transitions restent au compositeur partagé, qui n'est pas modifié. Mystery n'a ni l'option ni les transitions.

## Ce que fait la V2 par gabarit

| Gabarit | Rendu V2 |
|---|---|
| barres (accroche) | Résultat principal de calc.py en gros sur un éclat, objets du sujet qui tombent |
| barres (autres rôles) | Étiquettes de prix qui glissent et s'empilent, la ligne du résultat principal surlignée |
| personnages | Scène actuelle + objets du sujet autour du personnage |
| deux_courbes, deux_arbres, curseur_temps, carte_fin, jauge | Rendu actuel |
| toutes | Caméra : léger travelling ; zoom avec élan sur le chiffre clé des révélations |

Règle de fond : le chiffre mis en avant est toujours le résultat principal de calc.py (`headline`), jamais le plus
grand montant (qui peut être l'idée fausse que la vidéo corrige, comme la « remise crue »).

Sécurité : une scène V2 refusée par le contrôle de mise en page bloquant retombe sur le rendu actuel.
Banc d'essai : les 105 scènes des 17 calculs passent en V2 sans repli (42 scènes V2, 63 en rendu actuel).

## Objets du quotidien

Pièce, applis génériques, étiquette de prix, téléphone, tirelire, calendrier, ticket de caisse, éclat, tasse,
carte bancaire, voiture, caddie, billet. Chaque calcul a ses objets (`props.CONCEPT_PROPS`).

## Son

Uniquement les effets de `assets/finance/sfx`. Pas de musique de fond (choix de la chaîne : `music_gain: 0`).

## Reste à faire

- Sous-titres mot par mot dans le compositeur (aujourd'hui dans le pilote seulement), en option propre à finance.
- Mises en scène V2 pour les courbes et les deux montants (objets plutôt que graphiques), si les premiers runs le
  justifient.
