🧟 Project Zomboid Knowledge Engine — Document Maître

    Objectif : Construire un moteur de connaissance local, déterministe et sans hallucination sur Project Zomboid, exposé à un agent IA via un serveur MCP. Il sert la stratégie de survie comme le développement de mods (Lua/Java), avec versioning natif B41/B42, robustesse anti-crash et gouvernance de niveau professionnel.

1. Philosophie & Principes Directeurs

    Zéro hallucination numérique — Toute valeur chiffrée est restituée depuis une source structurée, jamais reformulée.
    Le versioning est un citoyen de première classe — Aucun chunk ne vit sans son tag de version.
    Rappel large, précision finale — Récupération vectorielle large, puis reranking. Jamais l'inverse.
    La source de vérité mathématique est humaine — Le bytecode décompilé n'est jamais une source de formule fiable.
    Déterminisme quand c'est possible, sémantique quand c'est nécessaire — Un lookup par ID n'a rien à faire dans un espace vectoriel.
    Échouer localement, jamais globalement — Isoler, journaliser, reprendre.
    Rien n'entre en production sans validation — Le golden set est le gardien du temple.

2. L'Origine des Données : Extraction & Structuration
A. Les trois sources (Steam/steamapps/common/ProjectZomboid/media/)
Source 	Chemin 	Contenu 	Usage RAG
Scripts 	/scripts/*.txt 	Définitions brutes : objets, vêtements, véhicules, recettes 	Ingestion massive automatisée
Lua 	/lua/ 	UI, logique de jeu, hooks d'événements 	Référence de modding
Java décompilé 	zombie.jar 	API moteur (ItemContainer, IsoPlayer) 	Signatures uniquement
B. La stratégie Dual-Field

Chaque entité produit deux champs :

    Champ prose (vectorisé) : description en langage naturel pour la recherche sémantique.
    Champ JSON brut (métadonnée) : valeurs exactes, restituées telles quelles, jamais reformulées.

3. Architecture RAG
A. Modèles

    Embedding : bge-m3 (bilingue FR/EN, adapté au corpus mixte).
    Reranker : cross-encoder pour la précision finale après rappel vectoriel.

B. Les 5 collections dédiées
Collection 	Contenu 	Type de recherche
pz_items 	Objets, armes, vêtements, nourriture 	Vectoriel + lookup ID
pz_recipes 	Recettes d'artisanat 	Vectoriel + filtre version
pz_mechanics 	Fiches mécaniques (panique, calories, bruit) 	Vectoriel
pz_lua_api 	Doc de modding Lua, UI diégétiques 	Vectoriel
pz_java_api 	Signatures de l'API moteur 	Vectoriel + lookup
4. Le Serveur MCP
A. Les Outils (Tools)

    pz_knowledge_retrieval : recherche sémantique (vectoriel + reranking) sur les collections.
    pz_get_item : lookup déterministe par ID (Base.Axe) — jamais de vectoriel.
    pz_generate_mod_template(mod_name, features) : génère l'arborescence et les fichiers de base d'un mod sur disque.

B. Les Ressources (Resources)

    Fiches mécaniques Markdown vérifiées à la main.
    Documentation de création d'UI diégétiques en Lua.
    Signatures de l'API Java.

C. Les Prompts (Postures)

    help_me_survive : analyse de survie hardcore (calories, moodles, panique).
    debug_lua_script : audit de code Lua confronté aux structures de l'API Java décompilée.

5. Couche de Robustesse Anti-Crash
Menace 	Parade
Fichier script malformé 	Parsing isolé par entité + quarantaine
Encodage exotique (latin-1) 	Cascade d'encodages + errors="replace"
Accolades mal fermées 	Regex tolérante + validation Pydantic
OOM à l'ingestion 	Batch adaptatif + checkpoints reprenables
Handler MCP qui plante 	Décorateur safe_tool (capture tout)
Process serveur mort 	Watchdog de redémarrage
Corruption de DB 	Backup + rotation avant ré-ingestion
6. Gouvernance, Versioning & Cycle de Vie
A. Structure de dossiers pro (séparation stricte work / prod)

project-zomboid-knowledge-engine/
├── src/                      # Code source (parseur, MCP, ingestion)
├── data/
│   ├── raw/                  # Extractions brutes du jeu (jamais modifiées à la main)
│   ├── staging/              # 🟠 ZONE DE TRAVAIL TEMPORAIRE (bac à sable)
│   ├── quarantine/           # Entités rejetées
│   └── production/           # 🟢 DONNÉES VALIDÉES (intouchables sans process)
├── db/
│   ├── staging/              # Chroma de test
│   └── production/           # Chroma servie à l'agent
├── backups/                  # Snapshots horodatés + rotation
├── tests/
│   └── golden_set/           # Q/R de référence
├── docs/
│   ├── CHANGELOG.md          # Patch notes
│   ├── ARCHITECTURE.md       # Ce document maître
│   └── VERSIONING.md         # Règles de version
├── logs/                     # Logs JSON horodatés
├── .env.example
├── requirements.txt
└── VERSION                   # Fichier unique : "0.1.0-alpha"

Règle d'or : rien ne passe de staging/ à production/ sans avoir passé le golden set. production/ n'est jamais édité à la main.
B. Le flux de promotion des données

  Extraction        Validation         Promotion
  ┌────────┐        ┌──────────┐       ┌────────────┐
  │  raw/  │──────▶│ staging/  │─────▶│ production/ │
  └────────┘        └──────────┘       └────────────┘
                         │                    ▲
                         ▼                    │
                   golden set ────pass────────┘
                         │
                       fail
                         ▼
                    quarantine/ + log

promote.py orchestre ce passage et refuse la promotion si le recall@5 chute sous le seuil de référence.
C. Versioning Sémantique (SemVer adapté)

Format : MAJOR.MINOR.PATCH-stage (ex. 1.2.0-beta)
Segment 	Quand l'incrémenter
MAJOR 	Refonte d'architecture, rupture de schéma
MINOR 	Nouvelle collection, outil MCP, source de données
PATCH 	Correction de parsing, fix de fiche, retrait quarantaine

⚠️ Double versioning :

    Version du moteur (ton logiciel) : 1.2.0
    Version des données du jeu (B41/B42) : portée par le tag version des chunks.

D. Cycle de vie : Alpha → Beta → Release
Stage 	Critère d'entrée 	Ce qui est permis
-alpha 	Pipeline de bout en bout 	Schémas instables, collections incomplètes
-beta 	5 collections peuplées + golden set passe 	Gel du schéma, tests agent réels
-rc 	Zéro bug bloquant sur 1 semaine 	Uniquement fixes critiques
release 	Golden set 100 % + doc à jour 	Tag Git figé, backup archivé

Transition = tag Git annoté + entrée CHANGELOG + backup archivé.
E. Format du CHANGELOG (Keep a Changelog)

# Changelog

## [1.2.0-beta] - 2026-07-15
### Added
- Collection `pz_java_api` avec signatures de `IsoPlayer`.
- Outil MCP `pz_get_item` (lookup déterministe).

### Changed
- Modèle d'embedding migré vers bge-m3 (recall@5 : 0.71 → 0.84).

### Fixed
- Parsing des blocs `recipe` à accolades imbriquées.

### Quarantine
- 12 items sortis de quarantaine après fix d'encodage latin-1.

F. Convention de commits (Conventional Commits)

feat(mcp): ajoute l'outil pz_get_item
fix(parser): gère les accolades imbriquées des recipes
docs(changelog): prépare la 1.2.0-beta
refactor(ingest): batch adaptatif anti-OOM
test(golden): +5 questions sur l'artisanat B42
chore(deps): pin chromadb==0.5.x

Bénéfice : CHANGELOG généré automatiquement depuis l'historique Git.
7. La To-Do List Maître (Feuille de Route)
PHASE 1 : Environnement & Fondations

    Initialiser le dépôt Git du projet.
    Créer l'arborescence complète (staging/, production/, backups/, etc.).
    Initialiser le fichier VERSION à 0.1.0-alpha.
    Créer CHANGELOG.md, VERSIONING.md, ARCHITECTURE.md.
    Configurer les hooks de commit (Conventional Commits).
    Rédiger les fiches de mécaniques en Markdown (Panique, Bruit/Distances, Agriculture, Météo).
    Rédiger la documentation technique des UI diégétiques en Lua.

PHASE 2 : Parsing & Textualisation

    Coder le parseur Dual-Field résilient (parse_scripts.py).
    Implémenter la cascade d'encodages + quarantaine.
    Validation Pydantic stricte des entités.
    Générer des identifiants uniques complexes (Base.Axe) contre les collisions de mods.

PHASE 3 : Ingestion dans ChromaDB

    Coder le script d'ingestion globale (ingest.py).
    Injecter les objets textualisés avec métadonnées strictes (version: b41, type: item).
    Injecter recettes, API Java et guides Markdown.
    Implémenter le batch adaptatif + checkpoints anti-OOM.
    Écrire promote.py (staging → production, gated par golden set).
    Interdire toute écriture directe en production/.
    Backup DB + rotation avant chaque ré-ingestion majeure.

PHASE 4 : Branchement MCP & Tests Agent

    Déclarer pz_knowledge_retrieval lié à la recherche ChromaDB.
    Déclarer pz_get_item (lookup déterministe par ID).
    Déclarer les ressources Markdown fixes + prompts (debug_lua_script, help_me_survive).
    Isoler chaque handler MCP (décorateur safe_tool).
    Ajouter un watchdog de redémarrage du process serveur.
    Connecter le serveur à l'agent local (OpenClaw ou autre client MCP).
    Test 1 : impact de la panique sur les armes à feu → filtre type: mechanics.
    Test 2 : générer une UI Lua diégétique → application de la Resource dédiée.
    Test 3 : stats exactes de Base.Axe → usage de pz_get_item (pas de vectoriel).

PHASE 5 : Évaluation & Qualité

    Constituer un golden set de 25-30 Q/R.
    Mesurer recall@5 avant/après reranking.
    Documenter les scores de référence.
    Lier le golden set au script de promotion (blocage si régression).
    Générer le rapport de version (recall, nb entités, quarantaine).

PHASE 6 : Maintenance & Build 42

    Filtrage $and natif pour isoler B41 / B42.
    Mise à jour incrémentale de Chroma (par hash), sans tout réindexer.
    Détection de patch cassant : rejouer le golden set après chaque MAJ du jeu.
    Script de tag Git annoté + archivage backup à chaque release.
    Générer automatiquement les patch notes depuis les commits.

8. Synthèse des choix d'architecture
Décision 	Raison
bge-m3 + reranker 	Corpus/requêtes bilingues + précision finale
Dual-Field (prose + JSON) 	Recherche performante et stats fidèles
5 collections dédiées 	Pas de pollution vectorielle inter-domaines
Java = signatures only 	Le bytecode décompilé ment sur les formules
pz_get_item déterministe 	Un lookup par ID n'appartient pas au vectoriel
Upsert par hash 	Patchs incrémentaux, pas de réindexation totale
Quarantaine + parsing isolé 	Une donnée cassée ≠ crash global
Checkpoints + batch adaptatif 	Survivre à l'OOM et reprendre proprement
Handlers MCP isolés + watchdog 	Le serveur stdio ne meurt jamais
Séparation staging / production 	On ne casse jamais la donnée validée
SemVer + cycle alpha→release 	Traçabilité et montée en qualité maîtrisée
Golden set = gate de promotion 	On mesure, on ne devine pas

