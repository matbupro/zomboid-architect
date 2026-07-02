# Structure du projet — PZ RAG Assistant

## Racine du projet

```
pz-rag-assistant/
├── VERSION                      # Source unique de vérité pour le versioning
├── Makefile                     # Orchestration : install, ingest, test, promote, tag
├── .gitmessage                  # Conventional Commits template (commit-msg hook)
├── STRUCTURE.md                 # Ce fichier
├── README.md                    # Démarrage rapide
│
├── ingestor/                    # Moteur d'ingestion (hors ligne RAG)
│   ├── __init__.py              # Exports publics, __version__ depuis VERSION
│   ├── parser.py                # Pipeline d'extraction : XML / Markdown / Lua
│   ├── engine.py                # Orchestrateur d'ingestion → ChromaDB
│   ├── promote.py               # Gate de promotion staging → production
│   ├── logger.py                # Configuration logs JSON rotatifs + console
│   ├── lock.py                  # Verrou fichier .ingest.lock (exclusif)
│   ├── worker.py                # Worker context pour tâches asynchrones
│   └── game_version.py          # GameVersion enum + helpers (B41 / B42)
│
├── src/
│   └── retrieval/
│       └── __init__.py          # Moteur RAG : query_staging(), RetrievalResult
│
├── data/
│   ├── sources/                 # Fichiers bruts ingérés (XML, Markdown, Lua)
│   │   ├── items.xml            # Items du jeu
│   │   ├── recipes.xml          # Recettes de craft
│   │   ├── traits.xml           # Traits jouables
│   │   └── *.md / *.lua         # Mécaniques, API Lua
│   │
│   ├── staging/                 # Base ChromaDB de travail / validation
│   │   └── chromadb/            # Persistance ChromaDB (ne pas commiter)
│   │
│   ├── production/              # Base ChromaDB servie en production
│   │   └── chromadb/            # Persistance ChromaDB
│   │
│   ├── quarantine/              # Fichiers en erreur de parsing (JSONL quotidien)
│   │   └── quarantine_YYYYMMDD.jsonl
│   │
│   ├── workspace/               # Fichiers temporaires, lock, checksum
│   │   ├── .ingest.lock         # Verrou actif (généré)
│   │   └── last_ingest.sha256   # Checksum incrémental
│   │
│   └── tmp/                     # Fichiers de travail à court terme
│
├── tests/
│   ├── conftest.py              # Fixtures pytest (golden.json, tmpdir, chroma)
│   └── golden_set/
│       └── golden.json          # Jeu de référence Q/R pour recall@5
│
├── docs/
│   ├── VERSIONING.md            # Règles SemVer + cycle de vie (alpha/beta/rc)
│   ├── CHANGELOG.md             # Format Keep a Changelog (generé)
│   └── architecture.md          # Vue d'ensemble du système (optionnel)
│
├── backups/
│   ├── chromadb/                # Snapshots ChromaDB horodatés
│   │   ├── 2025-01-15_staging.tar.gz
│   │   └── 2025-01-22_production.tar.gz
│   ├── manual/                  # Backups manuels nommés
│   │   └── pre-b42-migration/   # Backup avant migration de version
│   ├── scheduled/               # Backups planifiés (cron)
│   └── restore.py               # Script de restauration depuis backup
│
├── logs/
│   ├── project.log              # Log JSON rotatif (10 MB max, 5 backups)
│   └── audit.json               # Journal quotidien des opérations sensibles
│
└── scripts/
    └── hooks/
        ├── commit-msg           # Hook Git : vérifie Conventional Commits
        └── pre-push             # Hook Git : lance make test avant push
```

## Description détaillée par composant

### `ingestor/` — Moteur d'ingestion

| Fichier | Rôle |
|---------|------|
| `parser.py` | Extrait items.xml, recipes.xml, traits.xml, .md, .lua en `ParsedChunk` |
| `engine.py` | Orchestre le pipeline : parse → valide game_version → écrit ChromaDB |
| `promote.py` | Gate de promotion avec golden set + recall@5 + backup atomique |
| `logger.py` | Logs JSON machine + console humaine, correlation_id |
| `lock.py` | Verrou `.ingest.lock` exclusif, 24h timeout |
| `game_version.py` | `GameVersion.B41` / `B42`, `get_current_game_version()` |
| `__init__.py` | Exports publics + `__version__` |

### `src/retrieval/` — Moteur RAG

| Fichier | Rôle |
|---------|------|
| `__init__.py` | `query_staging(question, k=5, filters) → RetrievalResult` |

### `data/` — Données et persistence

Les sous-répertoires `staging/` et `production/` contiennent la persistance
ChromaDB. **Ne pas les commiter** (les ajouter à `.gitignore`).

### `tests/golden_set/golden.json` — Validation

Format :
```json
[
  {
    "id": "q001",
    "question": "Question du joueur",
    "expected_ids": ["id_chunk_1", "id_chunk_2"],
    "filter": {"type": "item", "version": "b41"}
  }
]
```

### `logs/` — Observabilité

- `project.log` : JSON structuré, rotation 5 fichiers × 10 MB
- `audit.json` : opérations sensibles (promote, restore, rollback)

## Règles d'import

```
ingestor/  → peut importer ingestor/ et stdlib uniquement
           → ne pas importer src.retrieval (découplage)
src/       → peut importer src/ uniquement
           → expose query_staging() pour les clients du RAG
promote.py → importe ingestor.engine.query_staging() (réimplémentation)
           → ou src.retrieval (si disponible)
```
