# Ingestor — Tâches d'Absorption de Données PZ (Complet)

## Sources de données connues

| Source | Type | Accesseur | État |
|--------|------|-----------|------|
| **Wiki.json** (TheIndoor/PZ Data Drive) | JSON brut ~60 Mo | Parsing JSON | Pas ingéré |
| **pzwiki.wiki** (fandom) | Web HTML | Crawl Playwright | Pas ingéré |
| **Lua API docs** (wiki.pzwiki.net/lua) | Web HTML/JS | Crawl Playwright | Partiellement ingéré |
| **Class Z decompilation** (GitHub: TheIndoor/PZ Java) | ~500+ classes .java | Parsing + grep | Pas ingéré |
| **PZ Forge / loot tables** | Web/API communautaire | Crawl API | Pas ingéré |
| **Server ini** (in-game servert.ini) | Config INI | Reading local file | Partiellement connu |
| **Mods installés** (Steam Workshop) | .pbo + lua + cfg | mod_ingester.py | Non exhaustif |
| **agent-autonome-mods-pz.md** | Doc architecture | Parsing text | Sources partielles |
| **GitHub: TheIndoor/projectzomboid** | Code source C++/Java/Lua | Crawl/Grep | Pas ingéré |

---

## P0 — Absorption IMMÉDIATE depuis le Data Drive (Wiki.json)

> Wiki.json est LA source de vérité. Il contient les items, recipes, crops, mobs, skills, maps. Doit être parsed et injecté dans les collections correspondantes.

### 0a. Items — ~350+ entités
- [ ] **0a-i** Armes (melee) — machette, hache, barre de fer, masse, couteau de chasse, baton de baseball, etc. (display name, weight, damage, speed, condition max, categories)
- [ ] **0a-ii** Armes (firearms) — pistolets, revolvers, fusils, shotguns, mitrailleuses, arbalète (dammage, portée, cadence, ammunition type, clip size, accuracy)
- [ ] **0a-iii** Munitions — 9mm, .45, .38, .22lr, .308, .45-70, arrows, bolts, spikes (damage modifier, velocity, penetration)
- [ ] **0a-iv** Outils de survie — pelle, pioche, scie à main, cloueur, marteau, tournevis, pinces, fil de fer, barre à mine (usage, durability, categories)
- [ ] **0a-v** Nourriture — conserves (toutes marques), fruits, legumes, plats cuisinés (nutrition: calories, protein, vitamin, mineral, water; spoil time)
- [ ] **0a-vi** Médicaments — pansements, bandages, herbes médicinales, antibiotiques, alcool, seringues de stimulant/somnifère (heal amount, type: cut/scrape/fracture/toxicity/poison)
- [ ] **0a-vii** Vêtements & Protection — t-shirts, jeans, vestes, bottes, gants, casques, lunettes de soleil, manteaux (warmth, damage resistance layers: blunt/cut/scratch/tear, speed penalty, waterproof)
- [ ] **0a-viii** Conteneurs — sacs à dos, sacs d'homedepot, tiroirs, caisses, armoires (capacity slots, durability)
- [ ] **0a-ix** Matériaux de construction — planches metaliques, clous, ciment, béton, vitres, portes, barbelé, piquets, panneaux (usage building recipes, weight per unit)
- [ ] **0a-x** Electronique & Tech — radio, pile AAA/AA/crystal, chargeur solaire, drone d'exploration, téléphone cellulaire, walkie-talkie, lampe de poche, bougie (battery drain rate, functions)
- [ ] **0a-xi** Objets de farming — graines (tomate, maïs, fraise, blé, arachide, etc.), terre fertile, engrais, eau (growing time, yield per plant, composting requirements)
- [ ] **0a-xii** VEHICULES & pièces — voitures list complète (engine block, transmission, tire, battery, alternator, radiator, fuel tank, door panels, glass)
- [ ] **0a-xiii** Meubles & Décoration — lits, tables, chaises, étagères, buffets, tableaux, lampes (comfort bonus, capacity, weight)

### 0b. Recipes — ~250+ recettes
- [ ] **0b-i** Crafting basique — bandages, pansements, barricades (porte renforcée, porte en metal, mur renforcé, sol renforcé), clous, planches, bouclier de jardin
- [ ] **0b-ii** Cuisson au feu de camp — steak medium-rare/medium/well-done, poisson cuit, fruits grillés, ragoûts, soupe au poulet, hot-dog, corn on the cob (conditions: rare, uncommon, common; cooking time)
- [ ] **0b-iii** Four de brique — cakes complets (chocolate cake), pizzas, plats avec cuisson croûte dorée, bacon, poisson fumé (cross-cook progressions from campfire)
- [ ] **0b-iv** Cuisine au poêle à gaz — stroganoff complet, chicken stew, mac and cheese, soup du jour, pot pie, chili con carne (meals complets)
- [ ] **0b-v** Cuisson au four à micro-ondes — microwave dinners (chicken fried rice, tuna noodle casserole, fish sticks with fries, etc.)
- [ ] **0b-vi** Menu d'animal — pet food recipes (dog food, cat food, chicken feed, horse feed)
- [ ] **0b-vii** Modification d'objets — modify bedroll → sleepingbag, modify sleeping mat → bedroll, modify wooden door → metal door, etc.
- [ ] **0b-viii** Recettes médicales — homemade antibiotics, saline solution, herbal poultice, adrenaline syringe (ingredient lists)

### 0c. Skills & Perks — 14 skills, ~28 perks
- [ ] **0c-i** Woodworking I/II — axe efficiency, tree fall direction, log salvage bonus
- [ ] **0c-II** Carpentry I/II — structure types unlock (wooden door, reinforced wall), tool requirements
- [ ] **0c-iii** Farming I/II/III — crop types unlock, composting, tilling speed, pest resistance
- [ ] **0c-iv** Cooking I/II — fire cooking quality tiers, oven recipes unlocked
- [ ] **0c-v** Melee Combat I/II/III — damage bonus against zombies (tree/hedge/bush), critical chance
- [ ] **0c-vi** Sharpshooter I/II/III — gun accuracy (standing/walking/crouching), reload speed, critical hit chance
- [ ] **0c-vii** Weightlifter I/II/III — carry weight bonus, stamina regeneration
- [ ] **0c-viii** Strength I/II/III — swing speed, door/window damage multiplier, item throw distance
- [ ] **0c-ix** Lockout/I/II — lock picking success rate, lockout time reduction, skill xp gain
- [ ] **0c-x** Lockpicking I/II — (same as above if different)
- [ ] **0c-xi** Handgunner I/II/III — handgun accuracy bonus
- [ ] **0c-xii** Rifleman I/II/III — rifle accuracy bonus, suppressor compatibility xp boost
- [ ] **0c-xiii** Heavy Weapons I/II — shotgun/repeater handling
- [ ] **0c-xiv** Marksman I/II — precision with scopes

### 0d. Mobs & Infected — ~30+ types
- [ ] **0d-i** Zombies de base (walkers) — standard walker, slow walker, normal walker (speed, HP, damage profile)
- [ ] **0d-II** Zombies spéciaux — bloater, lunge, crawler, spitter, hulk, leecher, creeper, sprinter (behavior pattern, attack type: cut/scratch/blunt, poison type if applicable, speed tier, detection radius)
- [ ] **0d-iii** Infected par biome — arroyo (desert): bloater, crawler; jonesport: normal; new tonbridge: diverse mix (spawn rates par biome map)
- [ ] **0d-iv** Animaux sauvages — wolf (pack behavior, attack type), wild boar (charge damage), bear (black/brown, massive HP)
- [ ] **0d-v** Drops par zombie type — xp gained, rare drops (bloater: bandage+; leecher: poison resistance item; spitter: acidic vomit effect details)

### 0e. Weather & Seasons — systèmes complets
- [ ] **0e-i** Spring (21 jours) — mild temps (5-20C), moderate rain, low humidity effects on zombies, day length
- [ ] **0e-II** Summer (28 jours) — hot temps (up to 42C+), heat stroke risk, dehydration rate, bugs/biting flies
- [ ] **0e-iii** Autumn (21 jours) — cooling temps, first frost events, leaf litter visibility, fog density
- [ ] **0e-iv** Winter (21 jours) — cold temps (down to -17C), snow depth, hypothermia risk, black ice on roads, blizzard events
- [ ] **0e-v** Humidité système — rain weight on clothing, wet speed penalty, cold exposure multiplier with wind chill
- [ ] **0e-vi** Température mécanique — body temp tracking, core temp vs skin temp, layers warmth ratings

### 0f. World Generation & Biomes
- [ ] **0f-i** Maps disponibles — Clover Ridge, Arroyo Grande, Downes Creek, Fox Mountain, Harris Lake, Jonesport, Lost Lake, New Lancy, New Tonbridge, Royston Valley, Salem Woods, Wisteria (size, terrain type, zombie density tier, loot distribution)
- [ ] **0f-II** Biome types — forest, desert, grassland, mountain, mixed (vegetation spawn rates, building styles par biome, POI types per biome)
- [ ] **0f-iii** World gen options — map seed, town count, town size distribution, farm count, garage density, hospital rarity

### 0g. Building System — toute la carpentry
- [ ] **0g-i** Types de base — wooden wall (light/heavy), reinforced wall, metal wall (light/heavy), concrete wall
- [ ] **0h-ii** Toits et étages — wooden roof (light/heavy/gable), reinforced roof, metal roof (light/heavy)
- [ ] **0g-iii** Sols — light floor, reinforced floor
- [ ] **0g-iv** Portes & Fenêtres — wooden door (standard/wooden reinforced/metal reinforced/barricaded), glass door, barred window, regular window, reinforced window, boarded up window
- [ ] **0g-v** Barricading — 3 levels of barricading per surface type (time/cost/HP per level)
- [ ] **0g-vi** Stairs & Ramps — wooden stairs (single/double), wooden ramp, metal ramp
- [ ] **0g-vii** Décoration — bookshelf (1/2/3 layer), dresser, table (6x4/7x4/9x6/12x6), bed, shelf unit, painting frames, lamp posts
- [ ] **0g-viii** Matériaux par structure type — planches count per wall level (0-5), clous count per surface, cement pour concrete walls

### 0h. Poison & Wood Toxicity System
- [ ] **0h-i** Types de poison — pine (itchy), oak (nausea), spruce (dizzy), beech (confused) — symptoms, duration, cure method (herbs needed)
- [ ] **0h-II** Réduction du poison — how to reduce toxicity (waiting, herbs, crafting anti-toxin)
- [ ] **0h-iii** XP Poisonous Woodworking — skill requirement to work with each wood type safely
- [ ] **0h-iv** Drop de bois par arbre — pine → planches pin; oak → planches chêne (chêne = poison); spruce → planches épicéa (épicéa = poison); beech → planches hêtre (hêtre = poison); birch, maple, redwood, walnut → safe woods

### 0i. Health & Injury System
- [ ] **0i-i** Types de blessures — cut, scrape, puncture, bite (zombie), scratch (zombie), fracture, poisoning (bois toxique)
- [ ] **0i-II** Symptomes de chaque blessure — blood loss rate per wound type, infection risk %, pain level
- [ ] **0i-iii** Traitements par blessure — bandage vs pansement (efficacité différente), herbes médicinales (réduction symptômes), antibiotiques (infection)
- [ ] **0i-iv** Maladies — flu season effects, food poisoning from spoiled food

### 0j. Moods & Music
- [ ] **0j-i** Day moods — dawn, morning, noon, afternoon, dusk, night (audio ambience, weather overlays, fog density)
- [ ] **0j-II** Special weather moods — rain mood, snow mood, fog mood, storm mood, heat haze mood
- [ ] **0j-iii** Music types — ambient tracks, zombie groans layering, wildlife sounds

### 0k. Trainer Mode & Sandbox Settings
- [ ] **0k-i** Toutes les options sandbox — spawn rate zombies, speed zombies, food spoil, water spoil, temperature effect, hunger/ thirst rates, crafting xp rates, combat damage, stamina drain, blood loss rate
- [ ] **0k-II** World gen sandbox — tree density, garage loot tier, hospital rarity, farm type, map size multiplier

### 0l. Traps & Defenses
- [ ] **0l-i** Spike traps — floor spikes, wall spikes (damage tiers: light/heavy/wooden reinforced/metal reinforced)
- [ ] **0l-II** Barbed wire — placement on surfaces, zombie damage per step
- [ ] **0l-iii** Fire traps — campfire trap setup (candle + cloth), fire spread mechanics

### 0m. Achievements (~75 achievements)
- [ ] **0m-i** Liste complète avec conditions d'obtention — par catégorie (survival, combat, exploration, crafting, farming, building)

---

## P1 — Sources EXTERNES & WEB

### 1a. PZ Wiki (pzwiki.wiki / fandom)
- [ ] **1a-i** Crawl complet de la catégorie Items/Weapons avec toutes les stats détaillées
- [ ] **1a-II** Crawl de la catégorie Recipes avec ingredients complets et conditions de cuisson
- [ ] **1a-iii** Crawl des guides par compétence (wiki pages pour chaque skill tree)
- [ ] **1a-iv** Crawl des POI lists (tous les points d'intérêt par map)
- [ ] **1a-v** Crawl du guide de modding complet (lua events, API reference détaillée)

### 1b. Class Z decompilation
- [ ] **1b-i** GitHub: `TheIndoor/projectzomboid` — parser Java classes → collections `pz_java_api`
  - Clazz.ZombieStats (HP, speed, damage par zombie type)
  -Clazz.ItemType / Base.IngredientItem
  - Items.SpoilerItem (nutrition stats)
  - WeatherManager (temperature/humidity/rainfall logic)
  - WorldOccupancyTable (POI occupancy data)
  - ServerOptions (tous les servert.ini params + defaults)
- [ ] **1b-II** Mapper chaque classe → documentation de méthode avec params et types de retour

### 1c. PZ Forge / Community Data Drives
- [ ] **1c-i** pzforge.net — loot tables par POI type
  - Tous les objets possibles par POI (grocery, garage, house, hospital, school, police station, etc.)
  - Probabilités de spawn par rareté (common/uncommon/rare)
  - Par niveau de quartier (low/medium/high income)
- [ ] **1c-II** Community data drives GitHub — fichiers JSON structurés
  - `items.json` ou équivalent avec toutes les définitions d'items PZ
  - `recipes.json` avec full definitions
  - `mobs.json` avec stats par zombie type

### 1d. Server Configuration Complete
- [ ] **1d-i** Parsing du servert.ini complet (tous les paramètres ~200+)
  - Général: servername, maxplayers, save slot, difficulty
  - Combat: bloodsplat chance, crit dmg multiplier, zombie crit chance
  - Zombies: spawn rate tier, movement speed modifier, damage modifier
  - Weather: temperature minimum/maximum, humidity min/max
  - Farming: crop growth speed, water quality impact
  - Survival: hunger scale, thirst scale, sleep exhaustion modifier
  - Building: reinforce time modifier, carpentry xp multiplier
  - World gen: map seed (str), town count, town size, farm count
  - Advanced: tick rate, lag compensation settings

### 1e. Multiplayer Mechanics Deep Dive
- [ ] **1e-i** Host-client model — authority server vs peer-to-peer
- [ ] **1a-II** Sync mechanics — what gets synced (player pos, inventory changes, building actions, zombie state)
- [ ] **1e-iii** Lag compensation algorithm — head prediction, interpolation buffer
- [ ] **1e-iv** Tick rate — server tick rate, client tick rate, max supported players per map

### 1f. Vehicle System Complet
- [ ] **1f-i** Liste de toutes les voitures spawnaibles (make/model/color variantes)
- [ ] **1f-II** Système de crash damage — body part HP, deformation levels, parts dropping at each level
- [ ] **1f-iii** Pièces par système — engine block variants, transmission types, alternator types, battery types
- [ ] **1f-iv** Fuel system — fuel type (gasoline/diesel), tank capacity, consumption rate par vehicle type
- [ ] **1f-v** Clé de voiture — randomization algorithm, key spawn locations

---

## P2 — Automatisation du Pipeline

### 2a. Script d'ingestion complet
- [ ] **2a-i** `ingestor/ingest_pz_full.py` — ingestion complète
  - Parse Wiki.json → toutes les collections natives (pz_items, pz_recipes, pz_mechanics, etc.)
  - Crawl PZWiki automatique avec Playwright (rate limiting inclus)
  - Extraction des mods installés via mod_ingester.py sur tout le workshop content root
  - Parsing de Class Z GitHub → documentation Java API
  - Génération de rapports par collection
- [ ] **2a-II** `ingestor/ingest_pz_full.ps1` — wrapper PowerShell pour Windows

### 2b. Coverage tracking
- [ ] **2b-i** Script de rapport de couverture hebdomadaire
  - % items PZ couverts dans la DB vs ~350 total
  - % recipes couvertes vs ~250 total
  - % skills/perks documentés vs 14/28 total
  - % mobs couverts vs ~30 total
  - % POI types listés vs coverage loot tables
  - % API methods doc vs ~500 total Java + ~200 Lua
- [ ] **2b-II** Alertes pour données manquantes (items non documentés, recipes sans ingredients complets)

### 2c. Watchdog auto-ingestion
- [ ] **2c-i** File watcher sur `steamapps/workshop/content/1042170/`
  - Detecter nouveaux mods installes en temps réel
  - Auto-ingester les .lua/.cfg des nouveaux mods
  - Notifier via Discord bot
- [ ] **2c-II** Detection de mises à jour du Wiki.json
  - Monitoring du data drive pour changements
  - Re-ingestion incremental (par SHA-256 diff)

---

## P3 — Multimédia & Communauté

### 3a. Contenu vidéo
- [ ] **3a-i** YouTube tutorials PZ modding — transcription de videos populaires
  - Tutoriels Lua scripting
  - Guides creation items custom
  - Tutos building/carpenetry avancé
- [ ] **3a-II** Game guides vidéos — strategies farming, combat tips
- [ ] **3a-iii** Developer streams/logs — devlog PZ, changelog details

### 3b. Communauté structurée
- [ ] **3b-i** Discord PZ official server — channels pertinents
  - Modding channel (questions frecuentes, code snippets)
  - Farming channel (strategies de crop)
  - Building tips shared par la communauté
- [ ] **3b-II** Reddit r/projectzomboid — guides et astuces
  - Mega threads de craft strategies
  - Building showcases avec materials lists
  - Farm layouts optimisées

### 3c. Données complémentaires
- [ ] **3c-i** PZ Workshop API — scraping des 500+ mods publies
  - Titre, description, author, date, downloads, subscribers
  - Tags de chaque mod (pour categorization)
- [ ] **3c-II** Speedrunning data — routes optimales, item priorities par speedrun category
- [ ] **3c-iii** Community maps / savegames analyses — loot optimization strategies

---

## P4 — Architecture & Cross-References

### 4a. Graph de connaissances croisées
- [ ] **4a-i** Items → Recipes (quels items sont ingredients vs results)
- [ ] **4a-II** Mobs → Drops → Items (chefs zombies × quels items droppe)
- [ ] **4a-iii** Skills → Perks → Unlocks (skill I unlocks carpentry, skill II unlocks more recipes)
- [ ] **4a-iv** Weather → Temperature → Hypothermia → Remedies
- [ ] **4a-v** Farming → Crops → Seasons → Harvest timing
- [ ] **4a-vi** POI types → Loot tables → Item rarity distribution

### 4b. Validation des données ingérées
- [ ] **4b-i** Cross-reference validation — chaque recipe a-t-elle ses ingredients valides (items existants) ?
- [ ] **4b-II** Consistency check — les items references dans les recipes existent-ils dans pz_items ?
- [ ] **4b-iii** Completeness scoring — par category: % coverage atteint vs source

---

---

# STRUCTURE — Ce que ton doc décrit et qu'IL FAUT IMPLÉMENTER

Ton document [agent-autonome-mods-pz.md](../agent-autonome-mods-pz.md) décrit une architecture complète de **usine à mods PZ**. Cette section liste tout ce qui est nécessaire pour tenir debout, en dehors des données PZ. Chaque tâche est mappée sur la section correspondante de ton doc.

---

## S1 — Infrastructure (Section A + B du doc)

> Ton doc recommande: PostgreSQL 16 + Qdrant + MinIO + Gitea + Redis + PZ Headless Docker

### S1-i. docker-compose complet
- [ ] **S1-a** Créer `docker-compose.pz-agent.yml` — tous les services de ton doc section B.2
  - postgres (postgis:16-3.4, port 5432)
  - qdrant (v1.7.4, ports 6333/6334)
  - minio (ports 9000/9001, console UI)
  - gitea:1.21 (port 3000/2222)
  - redis:7-alpine (port 6379, --maxmemory 512mb)
  - pz-headless (build depuis Dockerfile.pz-headless)
- [ ] **S1-b** Healthchecks pour chaque service (déjà définis dans ton doc — à implémenter)
- [ ] **S1-c** Volumes persistants — postgres_data, qdrant_data, minio_data, gitea_data, redis_data, pz_mods, pz_logs
- [ ] **S1-d** Réseau bridge `pz-agent-net`

### S1-II. PZ Headless Server (Section B du doc)
- [ ] **S1-e** Générer le Dockerfile.pz-headless (section B.1 de ton doc) — Ubuntu 22.04 + steamcmd + PZ app 380870 + luacheck
- [ ] **S1-f** entrypoint.sh — lance server headless avec mod injecte + servertest.ini auto-configuré
- [ ] **S1-g** Script d'injection de mod dans le conteneur (section B.3) — unzip mod → /pz-server/mods/ + configure servert.ini
- [ ] **S1-h** Resource limits: cpus 4, memory 8G (limits), 2 cores/4G (reservations)

### S1-iii. Variables d'environnement & secrets
- [ ] **S1-i** `.env.pz-agent` — POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD, STEAM_USER/PASS (jamais commités)
- [ ] **S1-II** Pré-commit hook pour verifier que les secrets ne sont pas dans le repo

---

## S2 — Schéma PostgreSQL (Section C du doc)

> Ton doc donne le DDL complet en section C.1: 17+ tables avec types ENUM, indexes, triggers, vues.

### S2-i. Migration DDL initiale
- [ ] **S2-a** Créer `migrations/001_initial_schema.sql` — toutes les tables de ta section C (DDL literal copié du doc)
  - Extensions: uuid-ossp, pg_trgm
  - Enums: agent_status, validation_level, validation_result, governance_tier, build_target, publish_status, dependency_type
  - Tables: mod_projects, agent_runs, mod_artifacts, mod_files, mod_dependencies, knowledge_chunks, api_reference, test_scenarios, fix_attempts, validation_results, publish_log, users
- [ ] **S2-b** Triggers: trg_mod_projects_updated, trg_api_reference_updated, trg_run_completion_stats (update_project_stats)
- [ ] **S2-c** Vues: v_latest_validated_artifact, v_run_success_rate, v_validation_trends
- [ ] **S2-d** Index sur toutes les tables (déjà définis dans le doc — à appliquer)

### S2-II. Collections StorageBackend mapping
- [ ] **S2-e** Vérifier que les 13 collections existantes correspondent au schéma DB:
  - `pz_items` → knowledge_chunks(category='item') ? Ou table dédiée ?
  - `pz_recipes` → knowledge_chunks(category='recipe') ?
  - `pz_lua_api` → api_reference + knowledge_chunks(subcategory='lua') ?
  - `pz_java_api` → api_reference(subcategory='java') ?
  - `pz_mechanics` → knowledge_chunks(category='mechanic') ?
  - `pz_web_pages` → knowledge_chunks(category='web_page') ?
  - `pz_pdfs` / `pz_images` / `pz_videos` / `pz_audios` → type mapping
  - `pz_mods` → mod_projects + knowledge_chunks(category='mod_metadata') ?
  - `pz_workshop_items` → workshop items registry (nouvelle table nécessaire ?)
  - `pz_mod_lua_scripts` / `pz_mod_configs` → mod_files ou knowledge_chunks
- [ ] **S2-f** Créer des tables dédiées si le mapping knowledge_chunks unique est insuffisant pour les requêtes croisées

### S2-iii. Schema extensions spécifiques ingestion
- [ ] **S2-g** Table `ingestion_runs` (nouvelle) — suivre chaque cycle d'ingestion PZ: source, status, chunks_processed, errors, duration_ms, started_at, ended_at
- [ ] **S2-h** Table `data_coverage` (nouvelle) — tracking % coverage par category vs total connu
  - item_name, category, is_documented, data_completeness_score, last_ingested_at
- [ ] **S2-i** IndexGIN sur content_text de knowledge_chunks pour recherche full-text (trigramme déjà configuré)

---

## S3 — Boucle Agentique LangGraph (Section A du doc)

> Ton doc section A.3 donne le squelette LangGraph complet avec state machine, 5 agents + escalade, MAX_RETRIES=5, policy d'escalade.

### S3-i. Implémentation LangGraph
- [ ] **S3-a** Créer `agent_core/` directory (ou `ingestor/agent_core/`) — le code LangGraph n'existe PAS encore
  - State: ModAgentState (TypedDict de ta section A.3)
  - Agents nodes: planning_agent, building_agent, validating_agent, fixing_agent, packaging_agent, escalation_agent
  - get_next_node() conditional edges (state machine de ton doc)
- [ ] **S3-b** Validation Level 1 — implémenter validate_level1(): luacheck + mod.info schema + required dirs check (section B.4 Niveau 1)
- [ ] **S3-c** Validation Level 2 — implémenter validate_level2(): PZ headless container boot test, OnGameBoot errors detection (section B.4 Niveau 2)
- [ ] **S3-d** Validation Level 3 — implémenter validate_level3(): runtime headless avec test scripts (section B.4 Niveau 3)
- [ ] **S3-e** Validation Level 4 — implémenter validate_level4(): RCON connection, item existence, recipe visibility, craft success (section B.4 Niveau 4)

### S3-II. Policy d'escalade & retry
- [ ] **S3-f** Implémenter RETRY_POLICY (section A.5): max_attempts=5, backoff_multiplier=2, initial_delay=5s
- [ ] **S3-g** should_escalate() — les 6 conditions d'escalade + human escalation requirements
- [ ] **S3-h** Governance tier system (section A.6): GREEN/ORANGE/RED avec actions autorisées/bloquées

---

## S4 — Processor Wiki.json (Ingestor core)

> L'ingestor a 9 processors actuels (text, pdf, image, video, audio, docx, epub, web, pbo). Aucun ne parse Wiki.json.

### S4-i. Nouveau processor `wikijson.py`
- [ ] **S4-a** Créer `ingestor/processors/wikijson.py` — implémente l'interface Processor.extract()
  - Parse le JSON brut (~60 Mo) de PZ Data Drive (TheIndoor/PZ-wiki-data)
  - Extrait items, recipes, mobs, crops, weather par category
  - Retourne: list[Chunk] + ExtractionResult avec metadata (source='wikidrive', type='json')
- [ ] **S4-b** Gérer les fields imbriqués (ex: chaque item a ~50+ fields — damage tiers, categories, subcategories, tags)
- [ ] **S4-c** Chunking optimal — Wiki.json est un gros JSON monolithique. Faut-il split par entity type avant chunking ?

### S4-II. Extensions CLI
- [ ] **S4-d** `--ingest-wikidrive <path>` — ingérer Wiki.json dans les collections correspondantes
- [ ] **S4-e** `--ingest-pz-full` — run tous les ingestion sources en sequence (wiki + web + mods + class z)
- [ ] **S4-f** `--coverage-report` — query data_coverage table → afficher % par category
- [ ] **S4-g** `--ingest-classz <github-repo-path>` — parser le code Java decompilé

### S4-iii. Adaptation StorageWriter pour données PZ massives
- [ ] **S4-h** Optimiser storage_writer.py pour bulk insert (Wiki.json = ~350 items + ~250 recipes en un coup → ~10k+ chunks)
  - Batch embeddings via Ollama (endpoint /api/embedding par batch)
  - Retry avec exponential backoff si endpoint rate-limited
- [ ] **S4-i** Gérer les collections qui n'existent pas encore — auto-create au premier write

---

## S5 — Migration de la BDD existante

> Actuellement: data/storage/zomboid.db (SQLite unique). Le doc vise PostgreSQL + Qdrant + MinIO.

### S5-i. Migration SQLite → PostgreSQL
- [ ] **S5-a** Script `migrations/convert_sqlite_to_pg.py` — lit zomboid.db, réinjecte dans PostgreSQL via StorageBackend switch
  - Sauvegarder les embeddings existants (s'il y en a)
  - Migrer les collections SQLite → knowledge_chunks en PG
- [ ] **S5-b** Configurer dual-backend pendant la transition: STORAGE_BACKEND=sqlite + fallback_pg=true

### S5-II. Migration vers Qdrant vector store
- [ ] **S5-c** Remplacer SQLite vectoriel par Qdrant pour les embeddings (Qdrant est recommandé dans ton doc section A)
  - Créer collection Qdrant pour chaque category PZ (items, recipes, mechanics, api_ref, etc.)
  - Migrate existing embeddings → Qdrant points
- [ ] **S5-d** Cross-search entre SQLite local et Qdrant distant (si dual-mode nécessaire pendant migration)

---

## S6 — Tests & Validation

### S6-i. Tests des nouveaux processors
- [ ] **S6-a** Test unitaire `tests/test_wikijson_processor.py` — validation parse du JSON structure, fields manquants handling
- [ ] **S6-b** Test d'intégration end-to-end: ingest Wikidrive → storage_writer → query → vérifier items count
- [ ] **S6-c** Regression tests existants à étendre pour les nouvelles collections (S4-f ci-dessus)

### S6-II. Validation des données ingérées
- [ ] **S6-d** Validator cross-reference: chaque recipe ingredient → existe dans pz_items ?
- [ ] **S6-e** Validator completeness: % fields remplis par item vs ~50+ fields totaux
- [ ] **S6-f** Validator schema: le JSON Wiki.json match-il les types PG attendus (JSONB columns) ?

---

## S7. Monitoring & Observability

### S7-i. Progress tracking
- [ ] **S7-a** Dashboard ingestion — combien de chunks ingérés par cycle, erreurs, temps total
  - Table ingestion_runs + vues AGGREGEE pour monitoring
  - CLI command `--ingest-status` pour query en live
- [ ] **S7-b** Disk space monitor (déjà partiellement dans config.py avec DISK_SPACE_MIN_GB) — étendre au multi-collection

### S7-II. Alerts
- [ ] **S7-c** Alerte si ingestion échoue sur une collection critique (pz_items vide = tout le reste non fiable)
- [ ] **S7-d** Alerte si coverage drop >10% entre deux cycles (data corruption?)

---

## S8 — CI/CD & Pre-commit

### S8-i. Hooks additionnels
- [ ] **S8-a** Pre-commit hook pour valider le DDL: `psql -f migrations/*.sql` sur schema vide avant commit
  - Vérifier qu'aucun ALTER TABLE cassant est dans les migrations
- [ ] **S8-b** Hook de validation des collections StorageBackend: `python -m ingestor.cli --validate-collections` avant push
- [ ] **S8-c** Garder le hook sync_agent existant (déjà configuré, fonctionne)

### S8-II. CI Pipeline (GitHub Actions / GitLab CI)
- [ ] **S8-d** Workflow CI: lint → tests unitaires → test d'intégration → deployment docker-compose staging
- [ ] **S8-e** Run les validation levels 1-4 sur un mod de test à chaque PR

---

## S9 — Documentation & Onboarding

### S9-i. Mise à jour du CLAUDE.md
- [ ] **S9-a** Ajouter une référence au schema PG et aux collections dans CLAUDE.md
- [ ] **S9-b** Ajouter la stack architecture complète (PostgreSQL+Qdrant+MinIO+Gitea+Redis) dans le README projet

### S9-II. Onboarding docs
- [ ] **S9-c** `SETUP.md` — comment bootstrapper l'infra complète en 5 minutes (docker-compose up + psql migration)
- [ ] **S9-d** `ARCHITECTURE.md` — diagramme complet du pipeline, liens entre ingestor → storage → bot → agent_core

---

## S10 — Sécurité

### S10-i. Protection des secrets
- [ ] **S10-a** STEAM_USER/STEAM_PASS dans `.env.pz-agent` (jamais dans git) + verifier via pre-commit hook
- [ ] **S10-b** POSTGRES_PASSWORD généré au premier docker-compose up → sauvegardé dans env file
- [ ] **S10-c** MINIO_ROOT_PASSWORD — idem, rotate mensuelle

### S10-II. Rate limiting & politesse web crawling
- [ ] **S10-d** Respecter robots.txt du Wiki/PZForge (déjà dans config.py mais vérifier implémentation)
- [ ] **S10-e** User-Agent identifié (`Zomboid Knowledge Engine`) avec contact email en cas de abuse report

---

## Mapping Résumé: Sections du doc → Tâches structurelles

| Section du doc | Correspondance tâches S | État actuel |
|---------------|----------------------|-------------|
| **A. Boucle Agentique** (state machine, 5 agents) | S3 — LangGraph implémentation | N'existe PAS |
| **B. Environnement PZ Headless Docker** (Dockerfile + entrypoint + docker-compose) | S1 — infrastructure complète | N'existe PAS |
| **C. Schéma PostgreSQL** (17+ tables DDL) | S2 — schema DB complet | Schema défini mais pas en fichiers SQL séparés |
| **D. Structure Type Mod PZ** | S4 — structure de base déjà existe (ingestor/) | Partiellement implémenté |
| **A.6 Gouvernance tiers GREEN/ORANGE/RED** | S3-g — tier system | N'existe PAS |
| **A.5 Retry policy + escalation** | S3-f/h — retry+escalade | N'existe PAS |
| **B.4 4 niveaux de validation** | S3-b/c/d/e — validate_level1..4 | N'existe PAS |
| **D.2 mod.info schema** | S4-h — parsing mod.info dans processor | Partiellement (pbo.py fait extraction) |
| **D.6 Checklist erreurs Lua** | À absorber dans `pz_mod_architecture` collection | Tâche 0a-xiii dans la liste données |

---

*Section structure générée le 2026-07-07 — toutes les tâches sont nécessaires pour que l'architecture du doc tienne debout.*
*Mettre à jour chaque checkbox [x] quand la tâche est complétée.*

| Catégorie | Estimation données PZ | Collection cible | Priorité |
|-----------|---------------------|-----------------|----------|
| Items complets | ~350+ items (13 sous-catégories) | `pz_items` | **P0** |
| Recipes completes | ~250+ recettes (8 categories de cuisson) | `pz_recipes` | **P0** |
| Skills & Perks | 14 skills, ~28 perks, 4 niveaux max | `pz_mechanics` | **P0** |
| Mobs & Infected | ~30+ types (zombies speciaux + animaux) | `pz_mechanics` / `pz_mods` | **P0** |
| Weather & Seasons | 4 saisons × conditions multiples | `pz_mechanics` | **P0** |
| World Gen & Maps | 12 maps × biome par POI type | `pz_mechanics` / `pz_web_pages` | **P0** |
| Building System | ~50+ types de structures + barricading | `pz_items` / `pz_recipes` | **P0** |
| Poison & Wood | 4 types de poison + wood drops mapping | `pz_mechanics` | **P0** |
| Health & Injury | 6 types de blessures + maladies | `pz_mechanics` | **P0** |
| Moods & Music | ~15 moods ambians | `pz_mechanics` | **P0** |
| Trainer/Sandbox | ~200+ options config | `pz_mod_configs` / `pz_web_pages` | **P0** |
| Traps & Defenses | 3 types de trapes avec variations | `pz_items` / `pz_recipes` | **P0** |
| Achievements | ~75 achievements | `pz_mechanics` | **P0** |
| Lua API complete | ~200+ classes, ~1500+ methods | `pz_lua_api` | P1 |
| Java API (Class Z) | ~500+ classes decompilées | `pz_java_api` | P1 |
| Loot tables par POI | 20+ POI types × items x rareté | `pz_web_pages` | P1 |
| Server Config | ~200+ servert.ini params | `pz_mod_configs` | P1 |
| Multiplayer model | Architecture réseau complète | `pz_mechanics` | P1 |
| Vehicle system | 30+ vehicules × 6 sous-systems | `pz_items` / `pz_mechanics` | P1 |
| Data Drive parsing | Wiki.json ~60 Mo complet | → toutes les collections | **P0** |

---

*Liste générée le 2026-07-07 — exhaustive, basée sur la connaissance complète de Project Zomboid v41.78 + bleeding0 (42)*
*Mettre à jour chaque checkbox [x] quand la tâche est complétée*