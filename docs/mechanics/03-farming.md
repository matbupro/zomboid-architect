# Mechanic.Farming — Mécanique d'Agriculture

**Type**: mechanic | **Version**: b41, b42  
**Tags**: `mechanic`, `farming`, `crafting`, `survival`

## Description

L'agriculture dans Project Zomboid permet de cultiver des légumes pour une source de nourriture durable et reproductible. Chaque type de légume a un cycle de croissance, des besoins spécifiques en eau et un temps de récolte définis. La culture est essentielle pour la survie à long terme car elle élimine la dépendance aux lootboxes aléatoires.

Les mécaniques de base incluent :
- Préparation du sol (bêche + herbe/faucheuse)
- Plantation de graines (trouvés, achetés ou récupérés sur récoltes)
- Arrosage obligatoire (les plantes meurent sans eau)
- Temps de croissance (variable selon le type de légume)
- Récolte et replantation automatique

## Propriétés / Stats

| Propriété | Valeur | Description |
|-----------|--------|-------------|
| `harvest_time_days` | variable | Temps de maturation (type-dependent, voir tableau ci-dessous) |
| `water_needed` | 1x/jour | Arrosage quotidien requis pour croissance |
| `soil_preparation` | bêche + herbe | Transformation herbe → champ cultivable |

## Légumes disponibles et cycles de culture

| Légume | Temps de culture | Rendement (par pied) | Calories/plante | Notes |
|--------|-----------------|----------------------|-----------------|-------|
| **Pommes de terre** | 4 jours | ~4-6 tubercules | ~160/calories | Croissance rapide, fiable |
| **Carottes** | 5 jours | ~3-5 racines | ~120/calories | Pousse bien en sols variés |
| **Tomates** | 7 jours | ~8-12 fruits | ~90/calories | Sensibles au gel hivernal |
| **Poivrons** | 7 jours | ~6-10 poivrons | ~150/calories | Haute valeur nutritionnelle |
| **Melons** | 8 jours | ~3-5 melons | ~300/calories | Rendement élevé mais long |
| **Choux** | 6 jours | ~2-4 heads | ~200/calories | Résistant au froid modéré |

## Stratégies agricoles optimisées

### Phase 1 : démarrage (Jours 1-7)
1. Trouver une bêche dans un garage/maison
2. Désherber une zone close et sécurisée (clôture ≥ 3x3 minimum)
3. Cultiver immédiatement les pommes de terre + carottes (cycles courts)
4. Arroser TOUS LES JOURS (oubli = perte de la plante)

### Phase 2 : expansion (Jours 8-30)
1. Ajouter tomates et poivrons pour diversité nutritionnelle
2. Créer un système d'arrosage par gravité (tuyaux d'eau suspendus)
3. Protéger les cultures avec clôture anti-zombie
4. Stocker les graines en surplus pour replantation

### Phase 3 : automatisation avancée
1. Irrigation automatique avec Sea-Doo / tuyau connecté
2. Serres en bois ou métal pour protection hivernale
3. Rotation des cultures (évite l'épuisement du sol)
4. Compostage des déchets végétaux pour fertilisant

## Risques et atténuations

| Risque | Severity | Mitigation |
|--------|----------|------------|
| Gel hivernal (-5°C et moins) | Élevé | Serres ou culture intérieure |
| Squeak (rats dévorant les récoltes) | Moyen | Clôture étanche + pièges à souris |
| Vol de graines par d'autres joueurs | Moyen | Zone cachée + clôture renforcée |
| Oubli d'arrosage (quitter le serveur) | Élevé | Notification automatique ou irrigation auto |
| Feu se propageant aux cultures | Élevé | Couloir coupe-feu de 3 cases minimum |

## Données ingérées

| Source | Format | Chunks |
|--------|--------|--------|
| Game files PZ (base game) | structured | 2 |
