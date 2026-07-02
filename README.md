# Zomboid Knowledge Engine

**Moteur de connaissance local, déterministe et sans hallucination sur Project Zomboid.**

Serve un deux buts : **stratégie de survie** (conseils précis) et **développement de mods** (doc Lua/Java). Exposé via un bot Discord + serveur MCP.

## Version

`0.1.0-alpha` — Phase B41

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
# Copier le .env exemple et remplir les valeurs
Copy-Item .env.example .env
# Éditer .env avec votre token Discord, clé Claude API (optionnel), etc.
```

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
