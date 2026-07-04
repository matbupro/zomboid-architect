# Zomboid Knowledge Engine

**Moteur de connaissance local, déterministe et sans hallucination sur Project Zomboid.**

Serve un deux buts : **stratégie de survie** (conseils précis) et **développement de mods** (doc Lua/Java). Exposé via un bot Discord + serveur MCP.

## Version

`0.3.0-alpha` — Phase B42 + mod generation engine

Voir [VERSION](VERSION) et [CHANGELOG.md](CHANGELOG.md) pour l'historique complet.

## Architecture

```
Zomboid_Architect/
├── agent/                 # Mémoire interne de l'agent (GOAL, rules, todo, etc.)
├── bot/                   # Bot Discord — /stats, /survie, /recipe, /search
│   ├── main.py            # Point d'entrée
│   ├── engine_client.py   # Client ChromaDB + fallback local
│   ├── llm_adapter.py     # Ollama (local) → Claude API (fallback)
│   ├── pipeline.py        # message → search → prompt → LLM → réponse
│   ├── config.py          # Settings depuis .env
│   └── requirements.txt
├── src/                   # Code partagé transversal
│   ├── governance/        # parser, game_version, logger, lock, worker
│   ├── modgen/            # Moteur de generation de mods PZ (Phase 12)
│   │   ├── generator.py   # ModGenerator class — cree des mods valides
│   │   ├── schema.py      # Dataclasses: ModSpec, GeneratedModManifest
│   │   ├── config.py      # Config modgen
│   │   └── templates/     # 7 templates Jinja2 (mod.info, init.lua, etc.)
│   └── retrieval/         # Interface ChromaDB (query_staging, query_production)
├── ingestor/              # Moteur d'ingestion multi-format (PDF, images, web…)
│   ├── engine.py          # Router détection MIME → processeur
│   ├── cli.py             # CLI : --search, --file, --crawl, --dir
│   ├── processors/        # text, pdf, image, video, audio, docx, epub, web
│   ├── storage/           # chroma_writer (écrivain ChromaDB)
│   ├── search/            # DuckDuckGo + Brave Search
│   ├── promote.py         # Gate promotion staging → production
│   └── requirements.txt
├── data/                  # Données du moteur RAG
│   ├── staging/           # Zone de travail (ChromaDB test)
│   ├── production/        # Base validée (serveur MCP / bot)
│   ├── quarantine/        # Fichiers en erreur de parsing
│   └── raw/               # Sources brutes ingérées
├── db/                    # Bases ChromaDB persistantes
│   ├── staging/           # chromadb → data/staging/chromadb/ (symlink ou copy)
│   └── production/        # chromadb → data/production/chromadb/
├── backups/               # Snapshots horodatés (.tar.gz)
│   ├── chromadb/          # promote.py écrit ici automatiquement
│   ├── manual/            # Backups manuels nommés
│   └── scheduled/         # Backups cron planifiés
├── logs/                  # project.log (rotatif) + audit.json (JSONL)
├── tests/                 # Tests pytest + golden set Q/R
│   ├── conftest.py        # Fixtures partagées
│   └── golden_set/
│       └── golden.json    # 28 questions (15 B41 + 13 B42)
├── docs/                  # Documentation gouvernance
│   ├── VERSIONING.md      # Règles SemVer + cycle alpha→release
├── mods/                  # Mods generes par src/modgen/ (Phase 12)
├── VERSION                # Source unique de vérité (majeur.minor.patch[-pre])
├── CHANGELOG.md           # Keep a Changelog format
├── .env.example           # Variables d'environnement (copier en .env)
├── requirements.txt       # Dépendances unifiées (bot + ingestor + governance)
├── docker-compose.yml     # Orchestre bot + ollama + chromadb + ingestor
└── Makefile               # 13 cibles : install-hooks, ingest, test, promote, backup…
```

## Démarrage rapide

### 1. Configuration

```powershell
# Copier le .env exemple et remplir les valeurs obligatoires
Copy-Item .env.example .env
# Éditer .env : DISCORD_TOKEN est OBLIGATOIRE (le bot ne démarre pas sans)
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
| `ZOMBOID_EMBEDDING_MODEL` | non | `nomic-embed-text` | ingestor | Modèle d'embedding pour ChromaDB. |
| `CHROMA_HOST` | non | `http://host.docker.internal:8000` | bot, ingestor | Serveur ChromaDB. |
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

> Les credentials Steam (ingestor/.env) et Notion (notion_client/.env.notion) sont gérés séparément. Voir les fichiers `.example` associés dans chaque sous-projet.

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
docker compose up bot ollama chromadb
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

Le moteur `src/modgen/` genere des mods Project Zomboid valides a partir d'une description textuelle. Il cree la structure complete du mod (mod.info, init.lua, scripts Lua, descriptors Steam Workshop) et compresse en ZIP prets pour l'installation.

### Configuration

Variables d'environnement (dans `.env`) :

| Variable | Défaut | Description |
|----------|--------|-------------|
| `MOD_OUTPUT_PATH` | `mods/` | Dossier où les mods generes sont ecrits |
| `MOD_TEMPLATES_PATH` | `src/modgen/templates/` | Chemin des templates Jinja2 (rarement necessaire de changer) |

Types de mods supportes : `item` (arme/objet), `feature` (mecanique), `ui` (interface), `script`, `zombie`, `vehicle`.

### Workflow typique

```powershell
# 1. Generer un mod depuis une description textuelle
python -m src.modgen generate "Une epée en acier avec 45 degats de dégâts" --name "SteelSword" --type item

# → cree mods/modgen_steel_sword_<uuid>/
#    ├── mod.info
#    ├── ZomboidModDescriptor.txt
#    ├── README.md
#    └── media/lua/client/scripts/
#        ├── init.lua
#        └── SteelSword.lua

# 2. Compiler le mod en ZIP (packaging)
make mod-build MOD_NAME=modgen_steel_sward_<uuid>
# → mods/modgen_steel_sword_<uuid>.zip

# 3. Valider la structure du mod
python -m src.modgen validate mods/modgen_steel_sword_<uuid>/

# 4. Installer le mod dans PZ (manuellement ou via SteamCMD)
#    Copier le ZIP dans C:/Steam/steamapps/workshop/content/1042170/
```

### Bot Discord — commande `/modgen`

```
/modgen "Ajouter une epée furtive silencieuse avec 50 degâts"
```

Le bot :
1. Parse la description → cree un `ModSpec` structuré
2. Generer le dossier mod complet (mod.info + init.lua + scripts Lua)
3. Retourne les fichiers generes dans la reponse Discord
4. Les fichiers sont sauvegardes dans le dossier `mods/`

### CLI Reference

| Commande | Description |
|----------|-----------|
| `python -m src.modgen generate <desc> --name <nom> [--type item\|feature\|ui\|script\|zombie\|vehicle]` | Generer un mod depuis une description textuelle |
| `python -m src.modgen list-templates` | Afficher les templates Jinja2 disponibles (7 fichiers) |
| `python -m src.modgen validate <dossier/mod/>` | Verifier la structure et le contenu de mod.info + descriptors |

### Structure d'un mod genere

```
mon_mod/
├── mod.info                    # Manifest JSON — lu par PZ au chargement
│   { "name": "...", "author": "...", "type": "item",
│     "description": "...", "scriptDir": "scripts/",
│     "minGameVersion": "Build42", "singleplayer": true,
│     "multiplayer": true }
├── ZomboidModDescriptor.txt    # Metadata pour Steam Workshop upload
├── README.md                   # Documentation auto-generée
└── media/lua/
    ├── client/scripts/         # Scripts client (hooks PZ, events)
    │   ├── init.lua            # Point d'entree — hooks OnGameInit, Tick
    │   └── <nom_mod>.lua       # Scripts specifiques au type de mod
    ├── shared/scripts/         # Code partagé client<→serveur
    └── server/scripts/         # Scripts serveur (physique, damage, networking)
```

### Templates Jinja2 (7 fichiers)

| Template | Role |
|----------|------|
| `mod.info.j2` | Manifest JSON PZ — name, author, type, tags, scriptDir |
| `init.lua.j2` | Point d'entree — hooks OnGameInit, OnJoinGame, Tick |
| `ZomboidModDescriptor.txt.j2` | Descriptor Steam Workshop (nom, desc, tags, fichiers) |
| `README.md.j2` | Documentation auto-generée (description, type, scripts) |
| `client_script.lua.j2` | Scripts clients specifiques (events, UI, combat) |
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
