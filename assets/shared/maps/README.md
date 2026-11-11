# Fonds de carte

| Fichier | Contenu | Source |
|---|---|---|
| `france_regions.geojson` | 13 régions métropolitaines et 5 DROM (départements fusionnés par région) | Natural Earth 10m *Admin 1 – States, Provinces* |
| `countries.geojson` | Pays du monde (sauf la France), pour le contexte | Natural Earth 10m *Admin 0 – Countries* |
| `france_cities.json` | 66 villes françaises de plus de 30 000 habitants (agglomération) : repère « grande ville la plus proche » | Natural Earth 10m *Populated Places (simple)* |

**Licence : domaine public.** Natural Earth : « All versions of Natural Earth raster + vector map data
found on this website are in the public domain » (<https://www.naturalearthdata.com/about/terms-of-use/>).
Aucune autorisation ni crédit n'est requis ; la vidéo affiche quand même « Carte : Natural Earth ».

Géométries simplifiées (~400 m près de la France, ~3 km ailleurs) pour rester légères.
Pour régénérer : voir `scripts/build_map_data.py`.
