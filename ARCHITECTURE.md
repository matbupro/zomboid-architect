# ARCHITECTURE.md — Architecture complète du Pipeline Zomboid Knowledge Engine

**Version : v0.4.0** — Moteur RAG multi-modal + bot Discord + ingestion PZ automatisée.

---

## 1. Vue d'ensemble

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Zomboid Knowledge Engine                     │
│                                                                    │
│   Sources de données ──→ Ingestor ──→ Storage ──→ Bot Discord      │
│         │                   │             │           │             │
│    Wiki.json,Mods,PZWiki  PDF/Video/Web  PG+Qdrant  /survie,/moddoc│
│    Steam Workshop          ClassZ/GitHub   MinIO       MCP Server   │
│    PZForge Loot Tables     Lua/Java API   PG/pgvector  Claude/API  │
└─────────────────────────────────────────────────────────────────────┘
```

### Principes architecturaux

| Principe | Implémentation |
|----------|---------------|
| **Zero hallucination** | Retrieval-only (RAG), pas de génération sans contexte |
| **PostgreSQL par défaut** | Storage unique : PostgreSQL + pgvector. Optionnel : Qdrant comme backend alternatif. |
| **Multi-modal** | Un seul `engine.py` routeur vers 10+ processeurs spécialisés |
| **Promotion gateée** | golden set → validate → promote → production (jamais d'édition manuelle) |
| **Observabilité** | Monitoring dashboard, coverage tracking, disk alerts, critical collection alerts |

---

## 2. Pipeline de données complet

```
Sources externes                    Ingestion                          Storage
─────────────                     ──────────                           ───────

Wiki.json ─┐                      engine.py ──→ WikiJsonProcessor ──→
PZWiki    ├─→ crawl/playwright   Engine.route() → Processor.process()  StorageWriter
Lua API   │                      MIME detection + chunking             PG/pgvector
ClassZ    │                      chunk_size=512                        pg_trgm search
Mods      │                       ↓                                    MinIO (raw artifacts)
PZForge   │                    embeddings                               Redis (cache)
Steam     │                       ↓                                     |
Workshop  └── mod_ingester.py ──→ ingest_pz_full.py ──→ promote.py ──→ production/ (validée)

                    Pipeline orchestrator (ingestor.cli)
                    ├── --ingest-pz-full      : pipeline complet automatisé
                    ├── --coverage-report     : % coverage par category
                    ├── --ingest-status       : monitoring dashboard S7
                    ├── --validate-collections: integrity checks S8-b
                    └── --search-all <q>      : cross-collection search
```

---

## 3. Composants détaillés

### 3.1 Engine Router (`ingestor/engine.py`)

```
Engine.route(file_path / url / crawl_seed)
    │
    ├── MIME detection → routing table
    ├── text   → TextProcessor (split → chunks → embeddings)
    ├── pdf    → PDFProcessor (PyMuPDF/fitz extraction)
    ├── image  → ImageProcessor (OCR → text)
    ├── audio  → AudioProcessor (whisper → transcript)
    ├── video  → VideoProcessor (frame + audio extraction)
    ├── docx   → DocxProcessor (zip → xml → text)
    ├── epub   → EpubProcessor (zip → html → text)
    ├── web    → WebProcessor (crawl BFS, depth limit)
    ├── pbo    → PBOProcessor (PZ mod format extraction)
    └── wikijson→ WikiJsonProcessor (PZ items/recipes/mobs/poi)
```

### 3.2 Storage Layer (`ingestor/storage/`)

```
StorageWriter (abstraction multi-backend : PG + optionnel Qdrant)
    ├── PostgreSQL/pgvector Backend (default)
    │   ├── pz_agent DB → 17 tables (schema migrations/001_initial_schema.sql)
    │   ├── pg_trgm for fuzzy text search
    │   └── pgvector HNSW index pour cosine similarity sur embeddings
    │   ├── pz_agent DB → 17 tables (schema migrations/001_initial_schema.sql)
    │   ├── pg_trgm for fuzzy text search
    │   └── pgvector for cosine similarity on embeddings
    │
    ├── Qdrant Backend (optionnel, STORAGE_BACKEND=qdrant)
    │   └── Vector store alternatif pour embeddings
    │
    └── Extension PZStorageExt (supervision pipeline)
        ├── ingestion_runs  : cycle tracking (run_id, source_type, status, chunks)
        ├── data_coverage   : % coverage par category PZ (items/recipes/mobs/skills)
        ├── collection_health: quality monitoring (chunk_count, vector_dim, is_healthy)
        └── data_links      : cross-reference graph (item ↔ recipe ↔ mob links)
```

### 3.3 Bot Discord (`bot/`)

```
main.py (discord.py client)
    │
    ├── /help      → commande générale du bot
    ├── /survie    → RAG search → conseils survie PZ
    ├── /recipe    → recherche recette crafting dans pz_recipes
    ├── /moddoc    → documentation mod Lua/Java
    ├── /search    → cross-collection search (tous backends)
    ├── /modgen    → génération de mod PZ valide
    └── /stats     → stats pipeline (coverage, ingestion status)
    │
    engine_client.py : StorageBackend query client
        ├── query_storage(collection, query_text, n_results=5)
        ├── cross_collection_search(query, n_results=10)
        └── ensure_collection(name) → lazy creation
    │
    llm_adapter.py : LLM fallback chain
        ├── Ollama (local, default) → embedding + generation
        └── Claude API (fallback)   → generation only
    │
    pipeline.py : message processing pipeline
        ├── command detection (/survie, /search, etc.)
        ├── context window management
        ├── retrieval augmentation (RAG)
        └── LLM call with system prompt + retrieved context
```

### 3.4 Mod Generator (`src/modgen/`)

```
ModGenerator.generate(description: str)
    │
    ├── parse → ModSpec (name, type, author, scripts...)
    ├── render Jinja2 templates (7 fichiers)
    │   ├── mod.info.j2       → manifest JSON PZ
    │   ├── init.lua.j2       → client hooks entry point
    │   ├── ZomboidModDescriptor.txt.j2 → Steam Workshop desc
    │   ├── README.md.j2      → auto-doc
    │   ├── client_script.lua.j2
    │   ├── shared_script.lua.j2
    │   └── server_script.lua.j2
    └── package → ZIP ready for Steam Workshop upload
```

---

## 4. Infrastructure (Docker)

```yaml
# docker-compose.yml — stack minimale (bot + ollama)
services:
  bot:          # Zomboid_Architect Discord bot
  ollama:       # Local LLM (nomic-embed-text, llama3.2)

# docker-compose.pz-agent.yml — stack complète
services:
  postgres:    # PG 16 + pgvector (schema migrations/001_initial_schema.sql)
  qdrant:      # Qdrant vector store alternative/backend optionnel
  minio:       # S3-compatible object storage (raw artifacts, backups)
  gitea:       # Git server for mod management
  redis:       # Cache layer + session storage
```

### Ports exposés

| Service | Port | Usage |
|---------|------|-------|
| PostgreSQL | 5432 | Storage backend principal |
| pgvector | 5432 (same) | Cosine similarity queries |
| Qdrant | 6333 | Alternative vector store |
| MinIO | 9000, 9001 | Object storage API/Console |
| Gitea | 3000 | Git HTTP server |
| Redis | 6379 | Cache / pub-sub |
| Ollama | 11434 | Embedding + LLM local |

---

## 5. Governance & Promotion Pipeline

```
staging/ (zone de travail)
    │
    ├── golden_set test (28 questions — tests/golden_set.py)
    ├── regression check (tests/test_regression.py)
    └── validate_level1..4 (quand implémenté — S3)
    │
    ▼
promote.py --dry-run   : simule, affiche diff
promote.py             : exécute la promotion
    │
    ├── auto backup → backups/production/<timestamp>/
    ├── copy staging/ → production/ (with lock)
    └── golden set final gate
    │
    ▼
production/ (base validée — bot + MCP server read-only)

Règles :
- [REDFLAG] Aucun edit manuel de production/ autorisé
- [RED] Promotion obligatoire via promote.py ou tag_release.py
- [GREEN] Staging/ → toutes modifications OK
```

---

## 6. Monitoring & Observability (S7)

```
IngestMonitor (ingestor/monitoring.py)
    │
    ├── dashboard_status()       : terminal UI (5 sections: cycles, coverage, health, disk, alerts)
    ├── ingest_status_short()    : CI one-liner ("last_run=done chunks=12500 | avg_cov=95%")
    ├── check_critical()         : alerts empty/stale/low-coverage collections
    ├── detect_coverage_drop()   : coverage drift between 2 consecutive runs
    └── disk_monitor()           : multi-backend (PG, Qdrant) free space

CLI access:
    python -m ingestor.cli --ingest-status        # full dashboard
    python -m ingestor.cli --ingest-status --short # CI mode
    python -m ingestor.cli --coverage-report       % coverage par category
```

---

## 7. Security Architecture (S10)

```
Secrets management:
├── .env.unified          : centralized variables (never committed — in .gitignore)
├── STORAGE_PG_PASS       : env var or .env for PG password
├── STEAM_USER/STEAM_PASS : steam credentials (.env.pz-agent)
└── MINIO_ROOT_PASSWORD   : rotate monthly (manual)

Pre-commit protections:
├── pre-commit.cmd        : auto-sync agent/ on todo.md changes
├── pre-validate-ddl.ps1  : scan breaking DDL in migrations staged
└── pre-validate-collections.ps1: validate collections integrity

CI Gate:
├── security job          : block direct production/ writes (except promote.py)
├── lint job              : ruff check + isort on every PR
└── test matrix           : ubuntu+windows × py310-312
```

---

## 8. Fichiers de configuration

| Fichier | Rôle |
|---------|------|
| `.env.unified` | Variables d'environnement centralisées (jamais commité) |
| `pyproject.toml` | ruff + pytest config |
| `docker-compose.yml` | Stack bot + ollama |
| `docker-compose.pz-agent.yml` | Stack complète PG+Qdrant+MinIO+Gitea+Redis |
| `requirements.txt` | Dépendances unifiées |
| `ingestor/requirements.txt` | Dépendances ingestor spécifiques |
| `bot/requirements.txt` | Dépendances bot spécifiques |
| `migrations/001_initial_schema.sql` | Schéma PG complet (17 tables + views + triggers) |

---

## 9. Mapping Données → Collections

| Source PZ | Collection StorageBackend | Type |
|-----------|--------------------------|------|
| Wiki.json items | `pz_items` (pgvector/text) | ~350 entités |
| Wiki.json recipes | `pz_recipes` (pgvector/text) | ~250 recettes |
| Wiki.json mobs | `pz_mechanics` (category=mob) | ~30 types |
| Wiki.json skills/perks | `pz_mechanics` (category=skill) | 14 skills + 28 perks |
| PZWiki pages | `pz_web_pages` (web crawl) | articles complets |
| Lua API docs | `pz_lua_api` (API reference) | fonctions/classes natives |
| Java Class Z | `pz_java_api` (decompilation doc) | ~500+ méthodes |
| PZForge loot tables | `pz_loot_tables` (community data) | spawn rates par POI |
| Steam Workshop mods | `pz_mods` (mod metadata + files) | tous les mods installés |
| Server ini params | `pz_mechanics` (category=server) | ~200+ server options |

---

*Document auto-généré le 2026-07-07 — mise à jour avec chaque changement structurel majeur.*
