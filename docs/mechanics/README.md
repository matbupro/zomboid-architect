# Fiches de Mécaniques — Project Zomboid Knowledge Engine

Fiches de référence détaillées pour les mécaniques centrales du jeu. Format standardisé pour ingestion par le moteur RAG.

## Fiches disponibles

| Fiche | ID | Tags principaux |
|-------|----|----------------|
| [01-Panic](01-panic.md) | `Mechanic.Panic` | `mechanic`, `combat`, `ai`, `stealth` |
| [02-DistanceVision](02-distance-and-noise.md) | `Mechanic.DistanceVision` | `mechanic`, `ai`, `stealth`, `detection` |
| [03-Farming](03-farming.md) | `Mechanic.Farming` | `mechanic`, `farming`, `crafting`, `survival` |
| [04-Weather](04-weather.md) | `Mechanic.Weather` | `mechanic`, `weather`, `survival`, `environment` |

## Format standard

Chaque fiche suit ce schéma :
1. **Métadonnées** : ID, Type, Version, Tags
2. **Description** : explication de la mécanique
3. **Propriétés/Stats** : tableau des valeurs calculables
4. **Stratégies tactiques** : applications pratiques pour la survie
5. **Données ingérées** : source et format des chunks correspondants

## Ingestion dans ChromaDB

```bash
python -m ingestor.cli --file docs/mechanics/*.md
# → stocké dans pz_mechanics avec version: b41/b42, type: mechanic
```
