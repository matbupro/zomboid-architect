# Mechanic.Weather — Mécanique Météo et Conditions Climatiques

**Type**: mechanic | **Version**: b41, b42  
**Tags**: `mechanic`, `weather`, `survival`, `environment`

## Description

Le système météorologique de Project Zomboid est l'un des mécanismes de survie les plus complexes. Il combine température, humidité, précipitations et vent pour créer un environnement changeant qui impacte directement la santé, le confort et la stratégie du joueur. La météo n'est pas cosmétique — elle affecte les statistiques de vie quotidiennes.

Les principales variables sont :
- **Température** : déterminée par saison + heure du jour + météo
- **Humidité** : accumulée par pluie, neige, brouillard, et vêtements mouillés
- **Vent** : amplifie la sensation de froid (wind chill)
- **Précipitations** : pluie, neige, orage — impactent visibilité et mobilité

## Propriétés / Stats

| Propriété | Plage | Impact principal |
|-----------|-------|-----------------|
| `temperature` | -15°C à 40°C | Hypothermie / hyperthermie |
| `humidity` | 0% à 100% | Vitesse de refroidissement, moisissure |
| `wind_speed` | 0 à 80 km/h | Wind chill amplification |
| `visibility` | 5m à 200m+ | Détection zombies, navigation |
| `precipitation_type` | none / rain / snow / storm | Mobilité, visibilité, température |

## Saisons et températures moyennes

| Saison | Temp. jour | Temp. nuit | Pluie | Neige | Risque principal |
|--------|-----------|-----------|-------|------|-----------------|
| **Printemps** (Avr-Mai) | 10-20°C | 2-8°C | Fréquent | Rare | Inondations soudaines |
| **Été** (Jun-Août) | 25-35°C | 15-22°C | Occasionnel (orages) | Non | Hyperthermie, déshydratation |
| **Automne** (Sep-Nov) | 8-20°C | -2 à 5°C | Fréquent | Début novembre | Hypothermie progressive |
| **Hiver** (Déc-Mar) | 0-8°C | -10 à -3°C | Neige dominante | Oui | Hypothermie mortelle, visibilité nulle |

## Conditions météo détaillées

### Pluie (Rain)
| Intensité | Impact | Protection requise |
|-----------|--------|--------------------|
| **Légère** | Humidité progressive | Aucune |
| **Moyenne** | Vêtements trempés rapidement | Impermeable ou abri |
| **Lourde** | Saturation immédiate, mobilité réduite | Shelter obligatoirement |

**Effets secondaires** :
- Les vêtements mouillés abaissent la température corporelle de 5°C équivalent
- Risque de refroidissement après 30 min en extérieur sous pluie forte
- Feu de camp inextinguible (eau nécessaire pour éteindre)

### Neige (Snow)
| Intensité | Impact | Protection requise |
|-----------|--------|--------------------|
| **Légère** | Visibilité réduite, glissade | Vêtements chauds |
| **Moyenne** | Accumulation 5-10cm/jour | Impermeable + vêtements épais |
| **Tempête** | Visibilité ~5m, movement ralenti | Shelter obligatoire |

**Effets secondaires** :
- Le vent + neige = wind chill extrême (-30°C ressenti possible)
- La neige fond sur les vêtements mouillés → refroidissement accéléré
- Les routes enneigées = accès difficile aux lootables

### Orage (Thunderstorm)
| Intensité | Impact | Protection requise |
|-----------|--------|--------------------|
| **Orage lointain** | Tonnerre attire les zombies | Aucun |
| **Orage proche** | Foudre possible, visibilité nulle | Shelter impératif |
| **Tempête violente** | Éclairs au sol, vents >60km/h | Abri profond (sous-sol recommandé) |

**Effets secondaires critiques** :
- Le tonnerre attire les zombies comme un tir d'arme à feu
- La foudre peut mettre le feu aux bâtiments (dangereux en zone zombie)
- Les éclairs tuent instantanément tout ce qu'ils touchent (rare mais possible)

### Brouillard (Fog)
| Intensité | Impact | Protection requise |
|-----------|--------|--------------------|
| **Léger** | Visibilité réduite à ~50m | Aucune |
| **Épais** | Visibilité <20m, zombies détectés moins vite | Prudence accrue |

**Effets secondaires** :
- Les zombies sont moins visibles (avantage tactique) mais vous êtes moins visible aussi
- Impossible de naviguer sans GPS ou points de repère mémorisés
- L'humidité élevée + brouillard = refroidissement rapide

## Stratégies météo par situation

### Survivre à l'hiver (le tueur principal)
1. **Avant l'hiver** : stocker 50+ calories/jour en conserves + bois pour chauffage
2. **Vêtements stratifiés** : coton (mouillé = froid) → laine (reste chaud même humide)
3. **Chaleur corporelle** : manger > boire > se couvrir (l'ordre de priorité)
4. **Réchauffeurs artisanaux** : bouilloire sur feu + isolation avec duvet

### Survivre à l'été
1. **Hydratation** : boire 4+ verres d'eau par heure en plein soleil
2. **Chapeau impératif** : sans chapeau, le joueur perd de la santé au-dessus de 30°C
3. **Activité aux heures fraîches** : matin tôt (5-8h) ou soir tard (18-21h)
4. **Ombre permanente** : construire un abri avec toit + murs latéraux

### En temps d'orage
1. **Jamais sous un arbre isolé** (cible de foudre privilégiée)
2. **Sous-sol ou cave** : abris les meilleurs pendant la tempête
3. **Pas de métal en main** : outils métalliques → ramasser après l'orage
4. **Éloigner du feu** : si un feu est allumé, éteindre avant l'orage (danger double)

## Données ingérées

| Source | Format | Chunks |
|--------|--------|--------|
| Game files PZ (base game) | structured | 2 |
| Wiki PZ documentation | web crawl | multiple |
