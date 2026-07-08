# TODO : Migration SQLite → PostgreSQL-only (S9)

**Objectif :** Supprimer SQLite du runtime, PG devient le seul backend par défaut.
**Priorité :** Haute — simplifie l'archi, élimine fallback mort, default prod = postgres.
**Prérequis :** PG installé en local (winget install PostgreSQL.16), Ollama OK.

---

## Phase 1 : Nettoyage des fichiers morts (DELETE)

### [ ] P1.1 Supprimer `src/storage/sqlite_storage.py` (1234 lignes)
**Pourquoi :** Plus de raison d'être, PG est le seul backend.
**Risque :** Break toutes les imports — corrigé par P2/P3.
**Lignes clés:** class SQLiteStorage (L113-693), OllamaEmbedder (L64-106), StorageBackend wrapper (L726-1234).

### [ ] P1.2 Supprimer `tests/test_sqlite_storage.py` (436 lignes)
**Pourquoi :** Tous ces tests couvrent du code qu'on supprime.
**Action :** Tests vectoriels/redirigés vers `test_postgres_backend.py`.

### [ ] P1.3 Supprimer `tests/test_dual_backend.py` (380 lignes)
**Pourquoi :** Dual-sync périmé — SQLite n'est plus un fallback.

### [ ] P1.4 Supprimer `migrations/convert_sqlite_to_pg.py` (150+ lignes)
**Pourquoi :** Migration déjà faite en prod — script de transit mort.

---

## Phase 2 : Refactor du core storage layer

### [ ] P2.1 `src/storage/__init__.py` — PG default, imports propres
**Avant:**
```python
from .sqlite_storage import SearchResult, SQLiteStorage, StorageBackend, _load_storage_config
DEFAULT_BACKEND = "sqlite"
```
**Après:**
```python
from .postgres_backend import PostgresStorageBackend as StorageBackend, SearchResult
from .postgres_backend import _format_pgvector
__all__ = ["SearchResult", "StorageBackend", "_format_pgvector"]
# Remove: SQLiteStorage, QdrantVectorBackend (keep only if used elsewhere)
```

### [ ] P2.2 `src/storage/postgres_backend.py` — ajouter fallback storage config
- Default STORAGE_BACKEND=postgres dans `_load_storage_config()`
- Retirer dual-sync logic
- Garder SearchResult compatible

### [ ] P2.3 `src/storage/qdrant_backend.py` — vérifier références SQLite internes
**Action:** Vérifier et supprimer les imports sqlite_storage résiduels.

---

## Phase 3 : Migrer tous les callers (import → new StorageBackend)

### [ ] P3.1 `bot/engine_client.py`
- L18: `from src.storage.sqlite_storage import SearchResult` → `from src.storage import SearchResult`
- L19: `from src.storage.sqlite_storage import StorageBackend as _StorageBackend` → `from src.storage import StorageBackend as _StorageBackend`
- L20: `from src.storage.sqlite_storage import _load_storage_config` → `from src.storage import _load_storage_config`
- L7: comment STORAGE_BACKEND=sqlite → postgres

### [ ] P3.2 `src/retrieval/__init__.py`
- L29, L96, L104: `from src.storage.sqlite_storage import StorageBackend, _load_storage_config` → new path

### [ ] P3.3 `ingestor/storage/writer.py`
- L124: same import pattern update

### [ ] P3.4 `ingestor/generate_report.py`
- L31, L132, L276: same import pattern update

### [ ] P3.5 `ingestor/monitoring.py` — vérifier references SQLite health()

---

## Phase 4 : Config & environment (default → postgres)

### [ ] P4.1 `ingestor/config.py`
- STORAGE_BACKEND default: "sqlite" → "postgres"
- STORAGE_DUAL_SYNC: supprimer variable entière (3 occurences)
- STORAGE_SQLITE_DIR: supprimer (inutile)
- Ajouter STORAGE_PG_* si pas déjà dans _StorageConfig

### [ ] P4.2 `.env.example` — update defaults
- STORAGE_BACKEND=postgres
- Supprimer STORAGE_DUAL_SYNC=true
- Supprimer STORAGE_SQLITE_DIR
- Ajouté STORAGE_PG_HOST/PASS si besoin

### [ ] P4.3 `bot/main.py` — vérifier que STORAGE_BACKEND est bien résolu

### [ ] P4.4 `src/governance/game_version.py` — vérifier references SQLite dans docstrings/comments

---

## Phase 5 : Tests (adapter + valider)

### [ ] P5.1 `tests/test_postgres_backend.py` — compléter les tests manquants
- Ajouter tests qui couvraient sqlite_storage: cosine_similarity, _build_sql_where logic
- Renommer MockChunk → Chunk mock PG
- Add test for cross_collection_search
- Add test for delete_collection

### [ ] P5.2 `tests/test_auto_create_collections.py` — update imports (5 occurences)

### [ ] P5.3 `tests/test_game_version_filtering.py` — update import L200

### [ ] P5.4 `tests/test_qdrant_backend.py` — supprimer references SQLite fallback

### [ ] P5.5 `tests/test_regression_collection_extend.py` — update import (1 occurence)

### [ ] P5.6 `tests/test_wikijson_e2o.py` — update import (1 occurence)

### [ ] P5.7 Exécuter full test suite: `pytest --tb=short -v`
**Objectif:** 0 failure, max skips pour features mockées (ollama).

---

## Phase 6 : Documentation & cleanup

### [ ] P6.1 `ARCHITECTURE.md` — supprimer refs SQLite du diagramme

### [ ] P6.2 `SETUP.md` — update setup instructions (PG natif au lieu de SQLite)
- Instructions winget install PostgreSQL.16
- Supprimer sections SQLite

### [ ] P6.3 `README.md` (root) — update storage section

### [ ] P6.4 `ingestor/README.md` — update references

### [ ] P6.5 `bot/README.md` — update STORAGE_BACKEND refs

### [ ] P6.6 `CHANGELOG.md` — ajouter entry pour cette migration

### [ ] P6.7 `Makefile` — update test targets si besoin (STORAGE_BACKEND env)

### [ ] P6.8 `setup.ps1`, `doctor.ps1` — update storage config checks

### [ ] P6.9 `docker-compose.yml` + `docker-compose.pz-agent.yml`
- Garder PG service, supprimer SQLite mention
- S'assurer image pgvector/pgvector:pg16 est utilisée

---

## Phase 7 : Validation finale

### [ ] P7.1 Run: `pytest tests/ -v --tb=short` (full suite)
**Cible:** Tous passant (ou skips raisonnables pour ollama/mocked features).

### [ ] P7.2 Run: `ruff check src/ ingestor/ bot/` — lint clean

### [ ] P7.3 Verify imports: `python -c "from src.storage import StorageBackend; print(StorageBackend)"`
**Cible:** Import OK, default backend = postgresql

### [ ] P7.4 Commit avec message:
```
feat(storage): remove SQLite — PostgreSQL only backend (S9)

- Delete: sqlite_storage.py, test_sqlite_storage.py, test_dual_backend.py, convert_sqlite_to_pg.py
- Migrate all callers from sqlite_storage → storage (new unified)
- Default STORAGE_BACKEND=postgres
- Clean dual-sync legacy config
```

---

## Files to modify (full list)

| # | File | Action | Lines affected |
|---|------|--------|----------------|
| 1 | `src/storage/sqlite_storage.py` | DELETE | all 1234 |
| 2 | `tests/test_sqlite_storage.py` | DELETE | all 436 |
| 3 | `tests/test_dual_backend.py` | DELETE | all 380 |
| 4 | `migrations/convert_sqlite_to_pg.py` | DELETE | all ~150 |
| 5 | `src/storage/__init__.py` | MODIFY | ~29 |
| 6 | `src/storage/postgres_backend.py` | MODIFY | default config |
| 7 | `src/storage/qdrant_backend.py` | CHECK+FIX | ~18 refs |
| 8 | `bot/engine_client.py` | MODIFY | L7, L18-20 |
| 9 | `src/retrieval/__init__.py` | MODIFY | L29, L96, L104 |
| 10 | `ingestor/storage/writer.py` | MODIFY | ~L124 |
| 11 | `ingestor/generate_report.py` | MODIFY | L31, L132, L276 |
| 12 | `ingestor/monitoring.py` | CHECK | refs to SQLite health |
| 13 | `ingestor/config.py` | MODIFY | ~7 occ. dual-sync/sqlite |
| 14 | `.env.example` | MODIFY | STORAGE_BACKEND default, remove dual-sync |
| 15 | `bot/main.py` | CHECK | STORAGE_BACKEND ref |
| 16 | `tests/test_postgres_backend.py` | MODIFY | add coverage for removed tests |
| 17 | `tests/test_auto_create_collections.py` | MODIFY | 5 imports |
| 18 | `tests/test_game_version_filtering.py` | MODIFY | 1 import |
| 19 | `tests/test_qdrant_backend.py` | MODIFY | 7 refs |
| 20 | `tests/test_regression_collection_extend.py` | MODIFY | ~10 refs |
| 21 | `tests/test_wikijson_e2o.py` | MODIFY | 1 import |
| 22 | `ARCHITECTURE.md` | MODIFY | diagram + text |
| 23 | `SETUP.md` | MODIFY | storage instructions |
| 24 | `README.md` | MODIFY | storage section |
| 25 | `ingestor/README.md` | MODIFY | refs |
| 26 | `bot/README.md` | MODIFY | refs |
| 27 | `CHANGELOG.md` | MODIFY | new entry |
| 28 | `Makefile` | CHECK | test targets |
| 29 | `setup.ps1` | CHECK | storage config |
| 30 | `doctor.ps1` | CHECK | storage config |
| 31 | `docker-compose.yml` | CHECK | PG service |
| 32 | `docker-compose.pz-agent.yml` | CHECK | PG service |

**Total: 4 files to DELETE, ~27 files to MODIFY/CHECK**
