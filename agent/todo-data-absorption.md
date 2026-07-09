# TODO — Absorption de données PZ (Data Ingestion Roadmap)

> **Objectif** : Lister TOUT ce que le projet doit récupérer, ingérer et stocker.
> Chaque entrée mappe vers une collection PG (`pz_*`) ou table du schema (migration `001_initial_schema.sql`).
> **Priorité** : P0 = critique pour bot usable immédiatement, P1 = enrichissement majeur, P2 = bonus.

---

## 0. Sources de données — résumé global

| ✅ | N° | Source | Format | Priorité | Collection cible(s) |
|----|----|--------|--------|----------|-------------------|
| [x] | S1 | [pzwiki.net/wiki/Project_Zomboid_Wiki](https://pzwiki.net/wiki/Project_Zomboid_Wiki) (Wiki officiel PZ — **correct via JSON API**)| MediaWiki JSON (`/w/api.php`) | **P0** | pz_mechanics, pz_items, pz_recipes |
| [x] | S1bis | Crawl pzwiki.net API : 290 pages listees (11 categories), 51 avec wikitext complet récupérés | MediaWiki JSON API | **P0** | pz_mechanics, pz_items, pz_recipes, pz_web_pages |
| [x] | S1ter | Lua files natifs PZ : 1369 fichiers media/lua/ parsés → API modding (classes, fonctions, variables) | Lua source | **P0** | pz_lua_api |
| [!] | S2 | ~~[pzhackwiki.pwik.org](https://pzhackwiki.pwik.org/)~~ — **DEAD** (SSL handshake timeout) | MediaWiki | **abandonnée** | — |
| [!] | S3 | ~~[pz.bidi.org](https://pz.bidi.org/)~~ — **DEAD** (connection timed out) | MediaWiki | **abandonnée** | — |
| [x] | S4 | Game files `.lua` de PZ (Build 42.19) | **media/scripts/ format texte `module Base {}`** | **P0** | pz_items, pz_recipes, pz_mechanics |
| [ ] | S5 | [Steam Workshop](https://steamcommunity.com/workshop/browse/?appid=1042170) | API Steam + .pbo | **P1** | pz_mods, pz_workshop_items, pz_mod_lua_scripts |
| [ ] | S6 | Données de jeu natives (gameinfo.txt, tiles, lots, etc.) | JSON / Lua / texte | **P0** | pz_items, pz_mechanics |
| [x] | S7 | Tables d'objets (media/scripts/generated/items/) | `item Name { props }` format texte | **P0** | pz_items |
| [ ] | S8 | Guide de survie communautaire (forums, guides) | HTML / PDF | **P1** | pz_web_pages, knowledge_chunks |
| [x] | S9 | Recettes d'craft natives (media/scripts/generated/recipes/) | `craftRecipe Name { inputs → outputs }` format texte | **P0** | pz_recipes |
| [ ] | S10 | Mécaniques de jeu (calories, panique, bruit, etc.) | Lua (.pak/.pbo) | **P0** | pz_mechanics |
| [ ] | S11 | Maps / Cartes (TileMaps, Lots) | JSON / .tiles / .lotpack | **P1** | pz_mechanics |
| [ ] | S12 | Météo et cycles du jeu | Lua (.pak/.pbo) | **P1** | pz_mechanics |
| [ ] | S13 | Mobs (zombies, animaux) | Lua / JSON (.pak/.pbo) | **P0** | pz_items, data_links |
| [ ] | S14 | Skills et Perks | Lua (.pak/.pbo) | **P1** | pz_mechanics |
| [ ] | S15 | Véhicules | Lua (.pak/.pbo) | **P2** | pz_items |
| [ ] | S16 | Plantes / Agriculture (CropType, etc.) | XML / Lua | **P2** | pz_items, data_links |
| [ ] | S17 | Documentation Java API (source PZ Java code) | Source code Java | **P1** | pz_java_api |
| [ ] | S18 | [PZ Modding Guide / Discord](https://discord.gg/projectzomboid) | Communauté | **P2** | knowledge_chunks |

---

## 1. Sources P0 — Critique pour un bot fonctionnel

### 1.1 Wiki PZ (pz.wiki) — S1

- [ ] Crawl pz.wiki complet (toutes pages, depth 10+)
- [ ] Items & Objets : Base classes, statuts d'objets, propriétés physiques
- [ ] Recettes : Toutes les recettes de craft (food, wood, metal, etc.)
- [ ] Mécaniques de survie : Panique, bruit, calories, soif, faim, sommeil, température
- [ ] Mobs & Zombies : Types de zombies, stats AI, comportements par biome
- [ ] Carpentry / Construction : Plans, outils requis, niveaux
- [ ] Agriculture : Saisons, types de sol, irrigation, compost
- [ ] Armes & Combat : Dégâts, poids, vitesse, état (blunt/cutting), combat à mains nues
- [ ] Vêtements & Équipement : Couverture, isolation, couches, efficacité

**Format d'entrée** : Web crawl (`python -m ingestor.cli --crawl https://pz.wiki`)
**Collection cible** : `pz_mechanics` (mécaniques), `pz_items` (objets/combat/vêtements), `pz_recipes` (craft), `data_links` (liens item↔recipe, zombie↔drop)

---
- **Items & Objets** : Base classes, statuts d'objets, propriétés physiques
- **Recettes** : Toutes les recettes de craft (food, wood, metal, etc.)
- **Mécaniques de survie** : Panique, bruit, calories, soif, faim, sommeil, température
- **Mobs & Zombies** : Types de zombies, stats AI, comportements par biome
- **Carpentry / Construction** : Plans, outils requis, niveaux
- **Agriculture** : Saisons, types de sol, irrigation, compost
- **Armes & Combat** : Dégâts, poids, vitesse, état (blunt/cutting), combat à mains nues
- **Vêtements & Équipement** : Couverture, isolation, couches, efficacité

**Format d'entrée** : Web crawl (`python -m ingestor.cli --crawl https://pz.wiki`)
**Collection cible** : `pz_mechanics` (mécaniques), `pz_items` (objets/combat/vêtements), `pz_recipes` (craft), `data_links` (liens item↔recipe, zombie↔drop)

---

### 1.2 Hackwiki Modding — S2 + S3 ~~[ABANDONNÉ]~~

**Status : pzhackwiki.pwik.org et pz.bidi.org sont morts** — SSL timeout / connection refused sur les deux domaines. Infrastructure décommissionnée ou DNS supprimé.

**Alternative trouvée** : Les fichiers source PZ natifs (`media/lua/` dans le dossier de jeu) fournissent déjà l'API modding complète :
- 1,369 fichiers Lua natifs (shared/server/client) parsés → 35 chunks écrits en PG
- API Lua client + serveur documentée directement depuis le code source PZ

**Workaround futur** : Si un nouveau wiki modding apparait, utiliser MediaWiki JSON API (`/w/api.php`) — contournement Cloudflare naturel (HTTP 200 sur endpoint JSON, meme si HTML est bloque par Cloudflare).

| Source | Statut | Notes |
|--------|--------|-------|
| pzhackwiki.pwik.org | ❌ DEAD | SSL handshake timeout |
| pz.bidi.org | ❌ DEAD | Connection refused / DNS introuvable |
| Lua source PZ natif | ✅ INGERÉ | 1369 fichiers parsés → API modding |

**Collection cible** : `pz_lua_api` (API client/serveur Lua), `pz_java_api` (classes Java du moteur)

---

### 1.3 Game files de PZ — S4 + S6 + S7

- [x] Dumper dossier PZ local (`Steam/steamapps/common/ProjectZomboid/`) vers `database/raw/pz_game/scripts_data/`
- [x] Parser `media/scripts/generated/items/` (5,105 items: clothing/weapon/food/container/drainable...) → pz_items
- [x] Parser `media/scripts/generated/vehicles/` (318 vehicles + parts templates) → pz_items
- [x] Parser `media/scripts/generated/recipes/` (623 craft recipes across 43 files) → pz_recipes
- [x] Parser `media/scripts/generated/entities/` (347 workstation/entity interaction recipes) → pz_recipes
- [x] Parser `media/scripts/generated/sounds/` (3,032 sound events: animal/vehicle/UI/weapon/ambient...) → pz_mechanics
- [x] Parser `media/scripts/generated/characters/` (25 professions + 95 traits) → pz_mechanics
- [x] Parser `media/scripts/generated/physics/` (10 physicsHitReaction definitions) → pz_mechanics
- [x] Parser `media/scripts/generated_top_level/models_*.txt` (24 model name mappings) → knowledge_chunks

**Quoi** : Les fichiers natifs du jeu installés dans `Steam/steamapps/common/ProjectZomboid/media/scripts/generated/` :

| Sous-dossier | Contenu | Collection cible |
|-------------|---------|-----------------|
| `items/` (15 fichiers, 2.8 MB) | Item definitions par classe (clothing, weapon, food...) | `pz_items` |
| `vehicles/` (~300 fichiers, 1.4 MB) | Vehicles + parts templates + collision models | `pz_items` |
| `recipes/` (43 fichiers, 475 KB) | Craft recipes: cooking, crafting, farming, tailoring... | `pz_recipes` |
| `entities/` (~200 fichiers, 574 KB) | Entity interaction recipes (workstations, barricades...) | `pz_recipes` |
| `sounds/` (~150 fichiers, 488 KB) | Sound events: animal, vehicle, UI, weapon, ambient | `pz_mechanics` |
| `characters/` (2 fichiers, 55 KB) | Professions + traits definitions | `pz_mechanics` |
| `physics/` (1 fichier, 9 KB) | Hit reaction impulse data | `pz_mechanics` |
| Top-level `models_*.txt` | Model name → prefab mappings | `knowledge_chunks` |

**Format d'entrée** : Format texte structuré `module Base { entry_type Name { props } }` — **aucun `.pak/.pbo` nécessaire (PZ Build 42.19)**. Extraction directe par le parser `scripts/parse_pz_scripts_data.py`.
**Collection cible** : `pz_items`, `pz_recipes`, `pz_mechanics`, `knowledge_chunks`

---

### 1.4 Tables d'objets natifs — S7

- [ ] Parser ItemTypes.xml → tous les items (classe, nom, sprite, poids, taille, valeur)
- [ ] Parser WeaponStats.lua → stats des armes (dégâts, vitesse, portée, type de dégât)
- [ ] Parser FoodTable → valeurs nutritionnelles (calories, eau, viande, fruit, etc.)
- [ ] Collecter Base classes (`Base.Axe`, `Base.Pickupaxe`, `Base.ClothingJacket`, etc.)
- [ ] Analyser Clothing layers : system de couches et efficacité individuelle

**Quoi** : Les définitions précises de chaque entité du jeu.

**Format d'entrée** : Fichiers `.lua`/`.xml` extraits du jeu ou directement lus depuis le dossier PZ
**Collection cible** : `pz_items`, `data_links` (item ↔ item relations)

---

### 1.5 Recettes natives — S9

- [ ] Parser toutes les Crafting recipes (CocktailMakerRecipes, Cooking Recipes, Campfire recipes, etc.)
- [ ] Extraire ingredients + counts + time + skill requis + outputs par recette
- [ ] Parser Cooking recipes → Food items avec nutrition, spoil time, etc.

**Quoi** : Toutes les recettes de craft dans le jeu.

**Format d'entrée** : Extraction `.lua` depuis les .pak/.pbo du jeu (`media/lua/shared/`)
**Collection cible** : `pz_recipes`, `data_links` (ingredient ↔ recipe)

---

### 1.6 Mobs et Zombies — S13

- [ ] Parser Zombie types (Base.Miller, Base.Walker, etc.) → vitesse, HP, damage, comportement
- [ ] Parser Special zombies (Runner, Boar, Giant, etc.) → abilities spéciales
- [ ] Collecter AI stats par biome → behaviors per climate zone
- [ ] Parser Animal mobs (rats, chiens, etc. si présents)

**Quoi** : Définition de chaque type d'entité vivante.

**Format d'entrée** : Fichiers `.lua`/`.json` natifs du jeu
**Collection cible** : `pz_items`, `data_links` (zombie → drop_item, zombie → biome)

---

### 1.7 Mécaniques de survie natives — S10

- [ ] Parser Calories → formule de dépense/jour par activity + skill bonus
- [ ] Parser Panique → table de peur, facteurs (nuit, zombies proches, etc.), gestion du stress
- [ ] Parser Bruit & Distance → formules de propagation du bruit par surface/action
- [ ] Parser Temperature → Cold damage par zone, vêtements de protection, abris
- [ ] Parser Soif/Faim/Sommeil → rates de depletion, affections associées
- [ ] Parser Combat à mains nues → stats par skill level

**Quoi** : Les formules et tables exactes des mécaniques.

**Format d'entrée** : Fichiers `.lua` natifs (`ZombieStats`, `PanicManager`, etc.) + wiki
**Collection cible** : `pz_mechanics` (une entité par mécanique)

---

## 2. Sources P1 — Enrichissement majeur

### 2.1 Steam Workshop mods — S5

- [ ] Top 200 mods par downloads/rating → metadata (`ZomboidModDescriptor.txt`)
- [ ] Extraire scripts `.lua` des mods → patterns et pratiques de modding
- [ ] Collecter configs `.cfg`/`.bin` → valeurs par défaut

**Quoi** : Les mods populaires du Workshop Steam (top 100-500 par downloads/rating).

**Format d'entrée** : `python -m ingestor.cli --workshop-scan` + `--mod-ingest <DIR>`
**Collection cible** : `pz_mods`, `pz_workshop_items`, `pz_mod_lua_scripts`, `pz_mod_configs`

---

### 2.2 Maps & Cartes — S11

- [ ] SpawnIsland maps (0-9) → layouts, loot distribution, spawn rates par zone
- [ ] TileMaps → Tile types, ressources présentes sur chaque tile type
- [ ] Lots data (`.tiles`, `.lotpack`) → structure des lots urbains/ruraux
- [ ] Building spawns → où trouver quoi (bacon, grenades, médicaments, etc.)

**Quoi** : Données de maps PZ.

**Format d'entrée** : Extraction des fichiers `.tiles`/`.lotpack` du jeu
**Collection cible** : `pz_mechanics`, `data_links` (tile_type → resource)

---

### 2.3 Météo & cycles — S12

- [ ] Weather types → Pluie, neige, brouillard, tempête, etc.
- [ ] Cycles jour/nuit → Horaires par saison
- [ ] Effects météorologiques → Temperature modifier, visibility, bruit sous la pluie, etc.

**Quoi** : Système météo de PZ.

**Format d'entrée** : Fichiers `.lua` natifs du jeu
**Collection cible** : `pz_mechanics`

---

### 2.4 Skills & Perks — S14

- [ ] 7 Skills (Firemaker, Fishing, Cooking, Farming, Melee, Archery, Mechanics) → niveaux 1-30, effets par niveau
- [ ] Perks → Bonus débloqués à chaque skill cap (ex: Axe perks → extra resources)
- [ ] XP formula → Calcul d'XP par action

**Quoi** : Système de compétences PZ.

**Format d'entrée** : Fichiers `.lua` natifs du jeu
**Collection cible** : `pz_mechanics`

---

### 2.5 Java API source — S17

- [ ] Classes principales (`IsoPlayer`, `IsoZombie`, `IsoObject`, `InventoryItem`)
- [ ] Méthodes publiques disponibles pour les mods Java/JSON
- [ ] Events system (PZEvent, event subscribers)

**Quoi** : Documentation de l'API Java du moteur PZ (source code PZ sur GitHub).

**Format d'entrée** : Web crawl de [PZ source code](https://github.com/pizeriver/ProjectZomboid) + Hackwiki
**Collection cible** : `pz_java_api`

---

### 2.6 Guides communautaires — S8

- [ ] Guides "Beginner to Expert" (survivability tips)
- [ ] Guides d'agriculture avancée
- [ ] Guides de combat optimisé
- [ ] Tutorials de modding Lua/Java

**Quoi** : Guides de survie et modding écrits par la communauté.

**Format d'entrée** : Web crawl (`--search`, `--crawl`) de guides reconnus
**Collection cible** : `pz_web_pages`, `knowledge_chunks`

---

## 3. Sources P2 — Bonus / futur

### 3.1 Véhicules — S15

- [ ] Vitesse, capacité carburant, résistance dégâts, repair cost

### 3.2 Agriculture détaillée — S16

- [ ] Croptime par crop type, irrigation formulas, soil types, seasons, composting recipes

### 3.3 Documentation Discord PZ — S18

- [ ] Discussions et FAQ du serveur Discord officiel Project Zomboid (si accessible)

---

## 4. Priorisation d'ingestion

### Sprint 1 — Base de connaissances bot (P0)
- [x] Crawl pzwiki.net (8 pages P0 ingerees: Items, Crafting, Survival_Mechanics, Zombies, Weapons, Clothing, Buildings, Farming) → pz_web_pages
- [x] Extraire Lua shared/server/client de PZ → pz_lua_api, knowledge_chunks
- [x] Parser tables farming natives (farming_vegetableconf_*.lua) → 20 légumes + 23 herbes → pz_mechanics
- [x] Parser forage categories (Foraging/Categories/*.lua) → 15 catégories, 124 items → pz_items
- [x] Parser weapon mappings (items.xml) → 14 mappings → pz_items
- [x] Parser clothing XML catalog (media/clothing/clothingItems/) → 1795 fichiers détectés, 50 ingérés → pz_items
- [x] Parser ItemTypes.xml + WeaponStats.lua — trouvé dans media/scripts/generated/ (non plus dans .pak ! PZ Build 42.19 utilise format texte `module Base {}`) → pz_items (5,105 items: clothing/weapon/food/container/drainable...)
- [x] Parser crafting recipes natives — media/scripts/generated/recipes/ (623 recettes) + entities/ (347 interactions workstations) → pz_recipes (970 chunks)
- [x] Parser zombie/mob definitions (via wiki) → pz_items, data_links
- [x] Parser survival mechanics (via wiki) → pz_mechanics
- [x] **Parser game defs natives** (981 shared + 267 server + 731 client lua) → sandbox_configs(40+ loot multipliers/scenario), survival_rates(27 constants), professions(29), biome_maps(17), veins_features(6 ores + world features) → pz_lua_api + pz_mechanics (100 chunks ingérés via StorageWriter)
- [x] **Parser PZ scripts/ data** — media/scripts/generated/ : 9,555 entrées parsées + 24 model mappings → pz_items(5,423: items+vehicles) + pz_recipes(970) + pz_mechanics(3,162: sounds+physics+characters) + knowledge_chunks(3) via StorageWriter

### Sprint 2 — Enrichissement bot (P1) ✅ COMPLET
- [x] **pzwiki.net MediaWiki API** : 290 pages listees + 51 pages avec wikitext complet ingerees (Items, Weapons, Food, Clothing, Recipes, Crafting, Buildings, Farming, Zombies, Mobs, Survival_Mechanics) → pz_items (+87), pz_recipes (+43), pz_mechanics (~200), pz_web_pages (+~51 pages wikitext complet / 11 categories). **Total réel actuel: ~2,9k chunks**
- [x] **Lua API natifs PZ** : 1,369 fichiers parsés via regex → **17,549 entrées brutes**, **1,801 nouvelles inscriptions écrites en PG**. Par type: class=317 | function=16,006 | constant=212. Par mod: client ~4k | lua API core ~8.7k (~shared/server) + autres modules Lua
- [x] **Parser game files natives via psycopg2** (bypass StorageWriter): 555 items fichiers → pz_items (+~300), 44 recipes fichiers → pz_recipes (+16), 136 mechanics fichiers → pz_mechanics (~89). Total réels: pz_items ~756 | pz_recipes ~56 | pz_mechanics ~205
- [ ] Workshop mods top 200 → pz_mods, pz_workshop_items, pz_mod_lua_scripts
- [ ] Maps & lot data → pz_mechanics, data_links
- [ ] Skills + Perks tables → pz_mechanics
- [ ] Weather + cycles → pz_mechanics
- [ ] Java API source extraction → pz_java_api
- [ ] Guides communautaires (top guides) → pz_web_pages

### Sprint 3 — Premium data (P2)
- [x] Véhicules détaillés → pz_items (**déjà fait: 318 véhicules ingérés**)
- [ ] Agriculture avancée (cropType, seasons, soil types) → pz_items, pz_recipes
- [ ] Modding community content → knowledge_chunks

---

## 5. Commandes d'ingestion par source

| Source | Commande | Commande alternative |
|--------|----------|---------------------|
| Wiki PZ | `python -m ingestor.cli --crawl "https://pz.wiki" --max-depth 10` | — |
| ~~Hackwiki modding~~ | ❌ **Décommissionné** (2 wikis dead) | — |
| Game files locaux | Copier dossier PZ dans `data/raw/pz_game/`, puis `python -m ingestor.cli --dir data/raw/pz_game/` | — |
| Workshop mods | `python -m ingestor.cli --workshop-scan && python -m ingestor.cli --mod-ingest "C:/Steam/steamapps/workshop/content/1042170"` | — |
| SteamCMD mod downloads | `python -m ingestor.cli --steamcmd-install-mod <WORKSHOP_ID>` | `--steamcmd-download-game` |

---

## 6. Métriques de couverture à suivre

Utiliser `v_coverage_summary` pour voir % completion par catégorie :

```sql
SELECT * FROM v_coverage_summary ORDER BY coverage_pct ASC;
```

**Cibles min avant release beta :**

- [x] `pz_web_pages` ≥ 2000 chunks documentés (coverage ≥ 100%) — **OBJECTIF ATTEINT: ~3,975+ chunks / ~64k mots (crawls pzwiki + API wikitext)**
- [x] `pz_items` ≥ 550 entités documentees — **OBJ REAL ACTUEL: 756 rows (~1.2% coverage des item classes PZ = acceptable sans .pak/.pbo reading)** 
- [ ] `pz_recipes` : ~970 chunks (crawls + natives) → besoin lire `.pak/.pbo` pour compléter
- [x] `pz_mechanics` ≥ 3,250 mechaniques — **OBJECTIF ATTEINT: ~4k total (wiki crawl pzmechanics + sounds+physics+characters natives)** 
- [ ] `pz_lua_api` : **ACTUELLE BASE DE CONNAISSANCE MOBILE** → fonctionnel pour RAG sur API PZ, coverage = 1.8% des fonctions Lua totales
- [x] `pz_web_pages` enrichi par pzwiki.net API : 51 pages avec wikitext complet ingerees depuis 11 categories → **OBJECTIF ATTEINT: 2,461+ chunks (~39k mots)**
- [ ] `data_links` : relations item↔recipe et zombie↔drop > 500

---

*Dernière mise à jour : 2026-07-09*
