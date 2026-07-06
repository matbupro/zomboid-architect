# Mechanic.DistanceVision — Portées de Détection et Bruit

**Type**: mechanic | **Version**: b41, b42  
**Tags**: `mechanic`, `ai`, `stealth`, `detection`

## Description

Cette mécanique définit les distances maximales de détection des zombies selon le type de stimuli : visuelle, auditive ou olfactive. Comprendre ces portées est essentiel pour survivre car elles définissent la "zone de danger" autour de chaque zombie.

Les zombies ont une vision limitée (30m) mais une ouïe très développée (jusqu'à 150m+ pour les bruits forts). La fumée, les tirs d'arme à feu et les explosifs attirent les zombies sur la plus large portée.

## Propriétés / Stats

| Propriété | Valeur | Description |
|-----------|--------|-------------|
| `vision_range` | 30.0m | Distance maximale de détection visuelle (par défaut) |
| `hearing_range` | 150.0m+ | Portée d'attirance auditive (bruits forts : tirs, explosions) |
| `speed_boost_panic` | +40% | Vitesse accrue en état de panique |

## Sources d'attirance par intensité

| Source d'attirance | Portée approximative | Fréquence de génération |
|--------------------|----------------------|--------------------------|
| **Explosifs** (C4, bombes) | ~200m+ | Faible (objets rares) |
| **Armes à feu** (mitraillette, fusil, pistolet) | 150-180m | Moyenne à élevée |
| **Fumée épaisse** (feu de bois volumineux) | 60-100m | Élevée (facile à créer) |
| **Tir d'arc / fusil à pompe** | 80-120m | Moyenne |
| **Bruit de porte cassée** | 30-50m | Fréquent |
| **Courir / marcher vite** | ~30m | Permanent si en mouvement |
| **Pas discrets (sneak)** | <15m | Minimal — quasi-invisible |

## Stratégies de furtivité

### Niveau 1 : déplacements
- Marcher > courir (la course augmente le bruit)
- Sneak mode (touche Shift par défaut) pour le mouvement ultra-discret
- Éliminer les obstacles bruyants (planches, verre) avant de traverser

### Niveau 2 : positionnement
- Toujours se placer **vent debout** (le vent emporte l'odeur derrière soi, pas devant)
- Éviter les surfaces qui amplifient le bruit (verre, gravier, eau profonde)
- Utiliser les arbres et haies comme écrans de fumée naturels

### Niveau 3 : manipulation du terrain
- Créer des "corridors furtifs" avec de la fumée pour traverser des zones hostiles
- Préférer les toits (les zombies ne montent pas aux toits facilement)
- Les fenêtres à l'étage supérieur = entrée sécurisée

## Données ingérées

| Source | Format | Chunks |
|--------|--------|--------|
| Game files PZ (base game) | structured | 2 |
