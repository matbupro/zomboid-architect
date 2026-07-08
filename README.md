# Zomboid Knowledge Engine

**Moteur de connaissance local, déterministe et sans hallucination sur Project Zomboid.**

Sert deux buts : **stratégie de survie** (conseils précis) et **développement de mods** (doc Lua/Java). Exposé via un bot Discord + serveur MCP.

## Version

`0.4.1-alpha` — PostgreSQL/pgvector uniquement (SQLite supprimé), S9 migration complète

**Nouveau depuis v0.3.0 :**
- **Phases 7–9** : Ingestion multi-format (PDF, images, vidéo, audio, docx, epub, web) + crawler DuckDuckGo/Playwright
- **Bot Discord** : /help, /survie, /recipe, /moddoc, /search, /modgen — mode DM automatique
- **Phase 12** : Génération de mods PZ valides (32+15 tests)
- **Stockage** : PostgreSQL/pgvector (vecteurs + texte) — zéro dépendance externe SQLite
- **Phase 10** : Infrastructure Docker ingstor, quarantine manager, circuit breaker

Voir [VERSION](VERSION) et [CHANGELOG.md](CHANGELOG.md) pour l'historique complet.

## Architecture

```
Zomboid_Architect/
├── agent/                 # Mémoire interne de l'agent (GOAL, rules, todo, etc.)
├── bot/                   # Bot Discord — /stats, /survie, /recipe, /search
│   ├── main.py            # Point d'entrée
│   ├── engine_client.py   # Client StorageBackend (PostgreSQL/pgvector) + fallback local
│   ├── llm_adapter.py     # Ollama (local) → Claude API (fallback)
│   ├── pipeline.py        # message → search → prompt → LLM → réponse
│   ├── config.py          # Settings depuis .env
│   └── requirements.txt
├── src/                   # Code partagé transversal
│   ├── governance/        # parser, game_version, logger, lock, worker
│   ├── modgen/            # Moteur de génération de mods PZ (Phase 12)
│   │   ├── generator.py   # ModGenerator class — crée des mods valides
│   │   ├── schema.py      # Dataclasses: ModSpec, GeneratedModManifest
│   │   ├── config.py      # Config modgen
│   │   └── templates/     # 7 templates Jinja2 (mod.info, init.lua, etc.)
│   └── retrieval/         # Interface de retrieval (query_staging, query_production)
├── ingestor/              # Moteur d'ingestion multi-format (PDF, images, web…)
│   ├── engine.py          # Router détection MIME → processeur
│   ├── cli.py             # CLI : --search, --file, --crawl, --ingest-status, --validate-collections
│   ├── processors/        # text, pdf, image, video, audio, docx, epub, web
│   ├── storage/           # storage_writer (écrivain StorageBackend) + pz_storage (supervision pipeline)
│   ├── monitoring.py      # Dashboard, coverage drop detection, disk alerts (S7)
│   ├── search/            # DuckDuckGo + Brave Search
│   ├── promote.py         # Gate promotion staging → production
│   └── requirements.txt
├── data/                  # Données du moteur RAG
│   ├── staging/           # Zone de travail (données en test)
│   ├── production/        # Base validée (serveur MCP / bot) — jamais édité à la main
│   ├── quarantine/        # Fichiers en erreur de parsing
│   └── raw/               # Sources brutes ingérées
├── db/                    # Bases persistantes (PostgreSQL)
│   ├── staging/           # données staging
│   └── production/        # données validées
├── backups/               # Snapshots horodatés (.tar.gz)
│   ├── pg_snapshots/      # snapshots PostgreSQL de promote.py
│   ├── manual/            # Backups manuels nommés
│   └── scheduled/         # Backups cron planifiés
├── logs/                  # project.log (rotatif) + audit.json (JSONL)
├── tests/                 # Tests pytest + golden set Q/R
│   ├── conftest.py        # Fixtures partagées
│   └── golden_set/
│       └── golden.json    # 28 questions (15 B41 + 13 B42)
├── docs/                  # Documentation gouvernance
│   ├── VERSIONING.md      # Règles SemVer + cycle alpha→release
├── mods/                  # Mods générés par src/modgen/ (Phase 12)
├── migrations/            # Schéma PostgreSQL complet (migrations versionnées)
│   └── 001_initial_schema.sql  # 17 tables, 7 ENUMs, 3 vues, triggers
├── .github/workflows/     # CI pipeline : lint → test → security gate → e2e
├── VERSION                # Source unique de vérité (majeur.minor.patch[-pre])
├── CHANGELOG.md           # Keep a Changelog format
├── .env.unified           # Source de vérité unique pour TOUTES les variables (jamais commité)
├── requirements.txt       # Dépendances unifiées (bot + ingestor + governance)
├── pyproject.toml         # ruff linter + pytest markers
├── docker-compose.yml     # Orchestre bot + ollama (ingestor à la demande)
├── docker-compose.pz-agent.yml  # Stack complète : PG + Qdrant + MinIO + Gitea + Redis
├── ARCHITECTURE.md        # Diagramme complet du pipeline et mapping collections
├── SETUP.md               # Bootstrap infra en 5 min (docker-compose + psql migration)
└── Makefile               # 13 cibles : install-hooks, ingest, test, promote, backup…
```

## Stack infrastructure complète

| Service | Docker | Port | Usage dans le pipeline |
|---------|--------|------|----------------------|
| **PostgreSQL 16** | `docker-compose.pz-agent.yml` | 5432 | Storage backend principal (PG/pgvector) |
| **pg_trgm** | intégré PG | — | Recherche texte fuzzy sur PG |
| **pgvector** | intégré PG | — | Cosine similarity sur embeddings vectoriels |
| **Qdrant** | `docker-compose.pz-agent.yml` | 6333 | Alternative backend vectoriel (optionnel) |
| **MinIO** | `docker-compose.pz-agent.yml` | 9000/9001 | Object storage S3 pour raw artifacts |
| **Gitea** | `docker-compose.pz-agent.yml` | 3000 | Git server pour mod management |
| **Redis** | `docker-compose.pz-agent.yml` | 6379 | Cache layer + pub/sub pour notifications |
| **Ollama** | `docker-compose.yml` | 11434 | Embedding (nomic-embed-text) + LLM local |

> **Pour commencer avec PostgreSQL natif Windows :** `STORAGE_BACKEND=postgres` (par défaut) + PG 16 installé. Le bot Discord démarre directement sans Docker.


## Démarrage rapide

### 1. Configuration

```powershell
# Utiliser ou créer .env.unified à la racine (déjà un template)
# Éditer .env.unified : DISCORD_TOKEN est OBLIGATOIRE (le bot ne démarre pas sans)
```

Ou via Make (Linux/macOS/WSL) :
```bash
make env-init
```

#### Variables d'environnement (résumé)

| Variable | Requis ? | Défaut | Utilisé par | Description |
|----------|----------|--------|-------------|-------------|
| `DISCORD_TOKEN` | **OUI** | — | bot | Token du bot Discord. Sans ce .env → `sys.exit(1)`. |
| `OLLAMA_BASE_URL` | non | `http://host.docker.internal:11434` | bot, ingestor | Serveur Ollama pour LLM local. |
| `OLLAMA_MODEL` | non | `llama3.2` (→ `qwen3.6:35b-a3b` en prod) | bot | Modèle par défaut du LLM. |
| `LLM_TEMPERATURE` | non | `0.7` | bot | Température [0.0-1.0]. 0 = déterministe. |
| `ZOMBOID_EMBEDDING_MODEL` | non | `nomic-embed-text` | ingestor | Modèle d'embedding pour l'index vectoriel (PostgreSQL/pgvector). |
| `STORAGE_BACKEND` | non | `postgres` | bot, ingestor | Type de stockage (postgres par défaut, optionnel : `qdrant`). |
| `STORAGE_PG_HOST` | non | `localhost` | ingestor | Hôte PostgreSQL. |
| `CLAUDE_API_KEY` | **optionnel** | — (fallback activé si défini) | bot, ingestor | Fallback LLM si Ollama indisponible. |
| `CLAUDE_MODEL` | non | `claude-sonnet-4-20250514` | bot | Modèle Claude en fallback. |
| `DATA_ROOT` | non | `data/` | ingestor | Racine des données brutes/staging/production. |
| `CHUNK_SIZE` | non | `512` | ingestor | Taille des chunks de texte. |
| `CHUNK_OVERLAP` | non | `64` | ingestor | Chevauchement entre chunks. |
| `MAX_WEB_DEPTH` | non | `5` | ingestor | Profondeur max du crawl web. |
| `MAX_WEB_PAGES` | non | `50` | ingestor | Pages max par seed URL. |
| `WEB_RATE_LIMIT` | non | `30` (ms) | ingestor | Délai entre requêtes web. |
| `OCR_LANG` | non | `fra+eng` | ingestor | Langues OCR. |
| `WORKSPACE_CHANNEL_NAME` | non | `💻 WORKSPACE Z-ARCHITECT` | bot | Nom du canal workspace Discord. |
| `WORKSPACE_CHANNEL_ID` | **optionnel** | résolu auto | bot | Override de l'ID (si le nom ne match pas). |
| `DISCORD_GUILD_ID` | **optionnel** | — | bot | ID du serveur (aide la recherche de canal). |
| `SYNC_HOOK_URL` | **optionnel** | — | bot | Webhook pour poster le workspace report. |
| `MAX_RESPONSE_LENGTH` | non | `4000` | bot | Limite de caractères des réponses. |

> Tous les credentials (Steam, Notion, Discord, etc.) sont centralisés dans `.env.unified` à la racine.

### 2. Dépendances

```powershell
pip install -r requirements.txt          # toutes les dépendances
# ou uniquement le bot :
pip install -r bot/requirements.txt
```

### 3. Lancement du bot (sans Docker)

```powershell
cd bot && python main.py
```

Ou avec PowerShell direct : `.\run-bot.ps1` (à la racine).

### 4. Lancement avec Docker

```bash
docker compose up bot ollama
```

### 5. Ingestion de données

```bash
make ingest                           # Pipeline complet
python -m ingestor.cli --file "chemin/fichier.pdf"   # Fichier unique
python -m ingestor.cli --search "Project Zomboid tips"  # Web search + crawl
```

### 6. Promotion staging → production (avec golden set gate)

```bash
make promote                           # Teste le golden set avant de promouvoir
make promote-force                     # Force sans test (urgence)
python ingestor/promote.py --dry-run   # Simule sans écrire
```

### 7. Rollback

```bash
python restore.py list                 # Liste les snapshots
python restore.py restore <backup_id>  # Restaure un snapshot
make rollback-latest                   # Rollback au dernier backup
```

## Gouvernance (4 piliers)

| Pilier | Implémentation |
|--------|---------------|
| **Versioning** | `VERSION` + `VERSIONING.md` — SemVer B41/B42 |
| **Backup** | promote.py auto-backup tar.gz + `restore.py` CLI |
| **Isolation** | `FileLock` (lock.py) + `WorkerContext` avec cleanup @exit |
| **Logging** | Multi-output : console colorisée + RotatingFileHandler + JSON audit |

## Règles d'or

- Rien ne passe de `staging/` → `production/` sans passer le golden set.
- `production/` n'est jamais édité à la main.
- Double versioning : SemVer (moteur) + B41/B42 (données du jeu).
- Conventional Commits forcés via `.git/hooks/commit-msg`.

## Génération de mods (Phase 12)

Le moteur `src/modgen/` génère des mods Project Zomboid valides à partir d'une description textuelle. Il crée la structure complète du mod (mod.info, init.lua, scripts Lua, descriptors Steam Workshop) et compresse en ZIP prêts pour l'installation.

### Configuration

Variables d'environnement (dans `.env`) :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `MOD_OUTPUT_PATH` | `mods/` | Dossier où les mods générés sont écrits |
| `MOD_TEMPLATES_PATH` | `src/modgen/templates/` | Chemin des templates Jinja2 (rarement nécessaire de changer) |

Types de mods supportés : `item` (arme/objet), `feature` (mécanique), `ui` (interface), `script`, `zombie`, `vehicle`.

### Workflow typique

```powershell
# 1. Générer un mod depuis une description textuelle
python -m src.modgen generate "Une épée en acier avec 45 dégâts de dégâts" --name "SteelSword" --type item

# → crée mods/modgen_steel_sword_<uuid>/
#    ├── mod.info
#    ├── ZomboidModDescriptor.txt
#    ├── README.md
#    └── media/lua/client/scripts/
#        ├── init.lua
#        └── SteelSword.lua

# 2. Compiler le mod en ZIP (packaging)
make mod-build MOD_NAME=modgen_steel_sword_<uuid>
# → mods/modgen_steel_sword_<uuid>.zip

# 3. Valider la structure du mod
python -m src.modgen validate mods/modgen_steel_sword_<uuid>/

# 4. Installer le mod dans PZ (manuellement ou via SteamCMD)
#    Copier le ZIP dans C:/Steam/steamapps/workshop/content/1042170/
```

### Bot Discord — commande `/modgen`

```
/modgen "Ajouter une épée furtive silencieuse avec 50 dégâts"
```

Le bot :
1. Parse la description → crée un `ModSpec` structuré
2. Génère le dossier mod complet (mod.info + init.lua + scripts Lua)
3. Retourne les fichiers générés dans la réponse Discord
4. Les fichiers sont sauvegardés dans le dossier `mods/`

### CLI Reference

| Commande | Description |
|----------|-----------|
| `python -m src.modgen generate <desc> --name <nom> [--type item\|feature\|ui\|script\|zombie\|vehicle]` | Générer un mod depuis une description textuelle |
| `python -m src.modgen list-templates` | Afficher les templates Jinja2 disponibles (7 fichiers) |
| `python -m src.modgen validate <dossier/mod/>` | Vérifier la structure et le contenu de mod.info + descriptors |

### Structure d'un mod généré

```
mon_mod/
├── mod.info                    # Manifest JSON — lu par PZ au chargement
│   { "name": "...", "author": "...", "type": "item",
│     "description": "...", "scriptDir": "scripts/",
│     "minGameVersion": "Build42", "singleplayer": true,
│     "multiplayer": true }
├── ZomboidModDescriptor.txt    # Metadata pour Steam Workshop upload
├── README.md                   # Documentation auto-générée
└── media/lua/
    ├── client/scripts/         # Scripts client (hooks PZ, events)
    │   ├── init.lua            # Point d'entrée — hooks OnGameInit, Tick
    │   └── <nom_mod>.lua       # Scripts spécifiques au type de mod
    ├── shared/scripts/         # Code partagé client→serveur
    └── server/scripts/         # Scripts serveur (physique, damage, networking)
```

### Templates Jinja2 (7 fichiers)

| Template | Rôle |
|----------|------|
| `mod.info.j2` | Manifest JSON PZ — name, author, type, tags, scriptDir |
| `init.lua.j2` | Point d'entrée — hooks OnGameInit, OnJoinGame, Tick |
| `ZomboidModDescriptor.txt.j2` | Descriptor Steam Workshop (nom, desc, tags, fichiers) |
| `README.md.j2` | Documentation auto-générée (description, type, scripts) |
| `client_script.lua.j2` | Scripts clients spécifiques (events, UI, combat) |
| `shared_script.lua.j2` | Code partagé entre client et serveur |
| `server_script.lua.j2` | Logique serveur (physique, damage, networking) |

## Structure des commits

```
feat(parser): ajout du support XML récursif
fix(engine): correction checksum sur Windows
docs(changelog): entrée pour la 0.1.0-beta
refactor(lock): timeout 24h au lieu de 3600s
test(golden): +5 questions recette B42
chore(deps): upgrade httpx à 0.27
ci: ajout target promote-force au Makefile
```

## Phases de développement (TODO)

Voir [agent/todo.md](agent/todo.md) pour la roadmap complète.
