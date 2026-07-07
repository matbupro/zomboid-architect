# Mechanic.Panic — Panique des Zombies

**Type**: mechanic | **Version**: b41, b42  
**Tags**: `mechanic`, `combat`, `ai`, `stealth`

## Description

La mécanique de panique détermine comment les zombies réagissent aux bruits et stimuli dans l'environnement. Lorsque des sons sont produits (tirs, objets cassés, cadavres, fumée), les zombies entendent le bruit et se regroupent autour de la source, entrant en état de "panique".

En état de panique, les zombies courent **40% plus vite** que leur vitesse normale et deviennent beaucoup plus agressifs dans leur approche. Cette mécanique est centrale pour la survie car elle crée un équilibre dynamique entre l'agressivité (attirer les zombies) et la discrétion (éviter de les attirer).

## Propriétés / Stats

| Propriété | Valeur | Description |
|-----------|--------|-------------|
| `detection_range` | 30.0m | Distance maximale de détection visuelle des zombies |
| `run_speed_boost` | 1.4x (+40%) | Facteur de vitesse en état de panique |
| `hearing_range` (bruit fort) | 150m+ | Distance d'attirance pour les tirs d'arme à feu |

## Implications tactiques

### Ce qui attire les zombies

- **Armes à feu** : portée maximale d'attirance (~150m+)
- **Explosifs** : portée maximale (équivalent ou supérieur aux armes à feu)
- **Fumée** (feu de bois, fumigènes) : portée intermédiaire
- **Bruit de pas** (courir, marcher sur verre/gravier) : portée courte (~30m)
- **Casser des objets** (portes, fenêtres) : portée moyenne
- **Cadavres** : attire lentement les zombies voisins

### Stratégies anti-panique

1. **Munitions limitées** : un tir peut attirer une horde entière — privilégier les armes silencieuses
2. **Armes blanches furtives** : dague, gourdin de bois, masse (mains nues < bâton)
3. **Brouillage auditif** : créer des feux secondaires pour tromper la localisation
4. **Fuites planifiées** : toujours avoir 2-3 routes d'évacuation connues à l'avance

## Données ingérées

| Source | Format | Chunks |
|--------|--------|--------|
| Game files PZ (base game) | structured | 2 |
