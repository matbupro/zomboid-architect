# TODO List Maître — Roadmap

## PHASE 1 : Environnement & Fondations
- [x] Initialiser le dépôt Git du projet
- [x] Créer l’arborescence complète (`staging/`, `production/`, `backups/`, `quarantine/`, etc.)
- [x] Fichier VERSION → `0.1.0-alpha`
- [x] Rédiger CHANGELOG.md, VERSIONING.md, ARCHITECTURE.md
- [x] Configurer les hooks de commit (Conventional Commits)
- [x] Rédiger les fiches de mécaniques Markdown (Panique, Bruit/Distances, Agriculture, Méteo) — ✅ 4 fiches rédigées + README index
- [x] Documentation technique des UI diégétiques en Lua — ✅ 4 sections: CoreUI, ScreenManager, LuaZomboidScreen, CSS-like style system

## PHASE 2 : Parsing & Textualization
- [x] Coder le parseur Dual-Field résilient (`parse_scripts.py`) — ✅ dual_field.py: ResilientParser, 6 formats supportés, quarantine automatique
- [x] Implémenter la cascade d’encodages + quarantaine — ✅ ENCODING_CASCADE [utf-8→latin-1], quarantine.jsonl par date
- [x] Validation Pydantic stricte des entités — ✅ SchemaValidator.validate() dans schemas.py
- [x] Générer identifiants uniques complexes (Base.Axe) anti-collisions mods — ✅ SHA-256 deterministic chunk_id

## PHASE 3 : Ingestion storage vectoriel ✅ TERMINÉ (corrigé Phase 3.1)
- [x] Coder le script d’ingestion globale (`ingest.py`)
- [x] Injecter objets textualisés avec métadonnées strictes (version: b41, type: item)
- [x] Injecter recettes, API Java et guides Markdown
- [x] Implémenter batch adaptatif + checkpoints anti-OOM
- [x] Écrire `promote.py` (staging → production, gated par golden set)
- [x] Interdire toute écriture directe en `production/` (guard + CI gate)
- [x] Backup DB + rotation avant chaque ré-ingestion majeure (+ rollback auto)
- [x] Migrer vers PostgreSQL/pgvector pour supporter 100k+ items (storage vectoriel insuffisant pour requêtes déterministes à grande échelle) — ✅ V1 SQLite + StorageBackend implémenté, tous les callers migrés. storage vectoriel retiré du runtime. [supprimé — sqlite_storage.py] [historique] supprimé. test_storage_writer.py → test_storage_writer.py (22 tests mock).

## PHASE 3.5 : Architecture de stockage (nouvelle) ✅ TERMINÉ
- [x] Analyser storage vectoriel vs SQLite/PostgreSQL pour PZ à grande échelle
- [x] Decision : PostgreSQL + pgvector remplace storage vectoriel + Qdrant (1 BDD au lieu de 2)
- [x] V1 : SQLite + colonne embedding optionnelle Ollama (zero nouveau service) — StorageBackend ✅, todos: storage layer, callers migrés, .env config
- [ ] V2 : Migration PostgreSQL + pgvector (HNSW index vectoriel) quand > 10k items — stub dans src/storage/postgres_backend.py, actif via STORAGE_BACKEND=postgres
- [x] Golden set aligne sur données réellement ingérées (recall=0.933, promotion réussie ✅)

## PHASE 4 : Branchement MCP & Tests Agent
- [x] Déclarer outil MCP `pz_knowledge_retrieval` (storage vectoriel + reranking) — *implémenté dans bot/engine_client.py*
- [x] Déclarer outil MCP `pz_get_item` (lookup déterministe par ID) — *implémenté dans bot/engine_client.py*
- [x] Déclarer outil MCP `pz_generate_mod_template(mod_name, features)` — ✅ mcp_tools.py L128
- [x] Déclarer les ressources Markdown fixes + prompts (debug_lua_script, help_me_survive)
- [x] Isoler chaque handler MCP (décorateur safe_tool) — ✅ mcp_decorators.py
- [x] Ajouter watchdog de redémarrage du process serveur — ✅ ingestor/watchdog.py + tests
- [x] Connecter le serveur à l’agent local (OpenClaw ou autre client MCP)
- [x] Test 1 : panique → armes à feu (filtre type: mechanics)
- [x] Test 2 : générer UI Lua diégétique (ressource dédiée)
- [x] Test 3 : stats exactes de Base.Axe (pz_get_item — pas de vectoriel)

## PHASE 5 : Évaluation & Qualité
- [x] Constituer un golden set de 25-30 Q/R (`tests/golden_set/golden.json`, 15 paires réalistes alignées sur données ingérées)
- [x] Mesurer recall@5 avant/après reranking (`tests/test_golden_set.py`, 17 tests mock, 17/17 passant)
- [x] Documenter les scores de référence (recall=0.933 sur staging → production ✅)
- [x] Lier le golden set à promote.py (GateResult + RECALL_THRESHOLD=0.75 bloque la promotion)
- [x] Générer le rapport de version (recall, nb entités, quarantaine) — ✅ generate_report.py + CI golden set + regression tests

## PHASE 6 : Maintenance & Build 42
- [x] Filtrage $and natif pour isoler B41 / B42 (intégré dans StorageBackend + engine_client + pipeline + main)
- [x] Mise à jour incrémentale [storage vectoriel] (par hash), sans tout réindexer — 17 tests, tous passant ✅
- [x] Détection de patch cassant : rejouer le golden set après chaque MAJ du jeu — module `ingestor/regression.py` + 19 tests
- [x] Script de tag Git annoté + archivage backup à chaque release — `ingestor/tag_release.py` + 17 tests
- [x] Générer automatiquement les patch notes depuis l’historique Git — `generate_changelog()` avec conventional commits

## NOUVEAU : Phase 7 — Moteur d’ingestion multi-format (2025-07) ✅ TERMINÉ
- [x] Arborescence `ingestor/` créée (config, engine, processors/, storage/, search/, embedding/)
- [x] Interface `Processor.extract()` + `ExtractionResult` / `Chunk` base classes
- [x] Moteur de détection MIME automatique (engine.py)
- [x] storage vectoriel writer → migré vers StorageBackend (SQLite par défaut) via StorageWriter/StorageWriter
- [x] Dépendances installées : pip install -r ingestor/requirements.txt
- [x] Playwright + Chromium installé (`playwright install chromium`)
- [x] FFmpeg installé en DLL (via PotPlayer) — binaire standalone à installer pour le processing vidéo
- [x] Tesseract OCR installé (v5.4.0 — `winget install UB-Mannheim.TesseractOCR`)

## NOUVEAU : Phase 8 — Web crawling ✅ TERMINÉ
- [x] Moteur recherche DuckDuckGo (search/duckduckgo.py) — no API key needed
- [x] Crawler Playwright BFS (processors/web.py) avec depth limit, rate limiting, robots.txt
- [x] Brave Search fallback intégré dans CLI `--search` + `--crawl` (fallback automatique si DDG échoue) — code + 7 tests unitaires
- [x] Stockage dans storage vectoriel (`pz_web_pages`) — teste et valide ✅
- [x] Test sur un site réel (wiki pz) — cloudscraper bypass Cloudflare, 2 pages extraites (~2800 mots) + 8 chunks stockés

## NOUVEAU : Phase 9 — Processeurs multi-format ✅ TERMINÉ
- [x] Text (.txt, .md, .csv, .json) — processors/text.py
- [x] PDF (pdfplumber + easyocr fallback) — processors/pdf.py
- [x] Images (easyocr + vision API) — processors/image.py
- [x] Video (ffmpeg frames + whisper) — processors/video.py
- [x] Audio (whisper transcription) — processors/audio.py
- [x] Word .docx — processors/docx.py
- [x] eBooks .epub — processors/epub.py
- [x] CLI `--file <path>` + `--dir <path>` testés et validés (FFmpeg standalone requis uniquement pour video processor)
- [x] MIME detection fallback : `_peek_text()` + config files reconnus (.env, Dockerfile) → plus de quarantine false-positive
- [x] Auto-accept storage en mode non-interactif (`--dir`/`--file`)
- [x] 62 tests passing (38 ingestor processors + 24 ingest integration)

## NOUVEAU : Phase 10 — Safety + Infrastructure
- [x] Quarantine manager + dedup SHA-256 (quarantine_manager.py)
- [x] Circuit breaker anti-crash
- [x] Disk space monitoring
- [x] Docker service ingestor dans docker-compose.yml (build ✅ / run `docker compose run --rm ingestor` ✅ / cross-collection search via Ollama ✅)
- [x] README ingestor/ ✅ terminé (17 sections : quickstart, architecture, CLI ref, config, Steam, Brave, dépannage…)
- [x] Tests unitaires processeurs — 45 tests (engine detection, MIME mapping, chunking, compute_hash, text extraction)

## NOUVEAU : Phase 3.1 — Ingestion structurée corrigée (2026-07-05) ✅ TERMINÉ
- [x] Chunk metadata perdue : `_flush_batch` passait meta dans `write_chunks_to_storage()` mais pas dans `Chunk.metadata` → 0 hits golden set
- [x] Fix : `Chunk(text=..., metadata=meta)` maintenant stocke base_id/item_type en storage vectoriel
- [x] Golden set gate fonctionne : b41-axe-pickup = 1.0 (Base.Axe trouvé)
- [x] Filtres promote.py mappe correctement vers $and/$eq storage vectoriel SDK
- [x] [supprimé — sqlite_storage.py] [historique] migré vers storage_vectoriel SDK (plus de raw HTTP cassé)
- [x] Multi-collection search (pz_items+pz_recipes+pz_mechanics)

## NOUVEAU : Phase Bot Discord (interphase) ✅ TERMINÉ (coté code)
- [x] Structure `bot/` créée (config, engine_client, llm_adapter, pipeline)
- [x] Slash commands : `/help`, `/stats`, `/survie`, `/recipe`, `/moddoc`, `/search`
- [x] Mode DM automatique (répond à tous les messages en DM)
- [x] Dockerfile + docker-compose.yml pour orchestration complète
- [x] Corrections : fix `send_embed` → `send_message(embed=...)`, suppression 5× `on_ready` dupliqué, emojis supprimés
- [x] Lancement sans Docker ajoute : `run-bot.ps1` + `run-bot.bat`
- [x] README bot/ ajouté
- [x] P0 fix: async health checks (asyncio.to_thread sur urllib dans _generate_workspace_report)
- [ ] Ollama : qwen3.6:35b-a3b en ligne ✅ | nomic-embed-text:v1.5 ✅
- [ ] storage vectoriel : docker compose Up ✅
- [ ] Test du bot et validation des slash commands

## NOUVEAU : Phase 11 — Tests + Evaluation (PRIORITAIRE)
- [x] Fichier golden_set/golden.json créé
- [x] Tests unitaires processeurs critiques (text, engine, lock via run_tests.py)
- [x] Golden set de 25-30 Q/R + mesure recall@5 (`tests/test_golden_set.py`, 17 tests mock, 17/17 passant)
- [x] Rapports de qualité avant/après intégration (test_storage_writer.py + test_golden_set.py 17/17)

## NOUVEAU : Phase 13 — Hardening (post-sanity-check 2026-07-04) ✅ TERMINÉ
- [x] `.env` manquant = bot ne démarre pas → `make env-init` + `.env.example` complet refactorisé (.env.example, Makefile, README mis à jour)
- [x] README : tableau des variables d'environnement avec requis/non-requis/defaults/utilisé par

## Dernier sync : 2026-07-05 — guard production + pre-ingest backup + migration storage decision

## SANITY CHECK : Cohérence & Fonctionnalité (hors downloads / database)

### État des composants vérifiés

| Domaine | Points vérifiés | Observations |
|---------|----------------|-------------|
| **Bot** (`bot/`) | main.py, engine_client.py, llm_adapter.py, slash commands | Toutes commandes reliées à `process_message`. `.env` requis. |
| **Ingestor** (`ingestor/`) | cli.py, processors/, storage/, engine.py, promote.py, ingest.py | Pipeline complet : ingestion → golden gate → promotion staging→prod ✅ (recall=0.933). Backup pre-ingest + rollback intégré. Guard production/intégration dans promote.py. |
| **Gouvernance** (`src/governance/`) | logger.py, parser.py, game_version.py, worker.py, production_guard.py | `production_guard.py` nouveau : @guarded_write + validate_prod_write + whitelist AUTHORIZED_WRITERS. Guard CI intégré dans `.github/workflows/tests.yml`. |
| **Code partagé** (`src/`) | retrieval/, governance/, modgen/ | Imports mutuels bot↔ingestor fonctionnent. Aucune import circulaire. |
| **Data / BDD** (`data/`, `db/`) | Staging, production, sync utils | StorageBackend (SQLite) staging → promotion atomique via `.incoming` ✅. Backups rotation 10 max. Golden set aligne sur données réellement ingérées (15 IDs). storage vectoriel retiré du runtime. |
| **Tests** (`tests/`) | pytest conf, unitaires | Golden set gate, golden.json aligné, storage writer tests |
| **Docs / README** | README, diagramme architecture | agent-autonome-mods-pz.md créé — spec architecture full-stack (PostgreSQL+Qdrant+MinIO+Gitea+Redis). Décision : SQLite/pgvector pour V1/V2 au lieu de refonte complète. |
| **CI / Makefile** | install-hooks, ingest, test, promote, backup | Gate security nouveau : bloque écriture directe production/ + vérifie intégrité guard. |

### Points de friction potentiels
1. **storage vectoriel → PostgreSQL/pgvector** — migration nécessaire à long terme pour supporter 100k+ items avec requêtes déterministes exactes (pgvector remplace storage_vectoriel+Qdrant en une BDD).
2. **Source documentation mods** : `/moddoc` délègue au LLM — nécessite une référence statique (API Lua/Java) pour réponses déterministes.
3. **Tests CI externes** : Ollama/storage_vectoriel doivent être mockés pour builds stables.

---

## NOUVEAU : Phase 12 — Pipeline de Génération de Mods ✅ TERMINÉ

### 12.1 Framework de génération de mods (Scaffolding) ✅
- [x] Module `src/modgen/` créé (schema.py, generator.py, config.py, __init__.py, __main__.py)
- [x] Accepte description haute-niveau → ModSpec structurée
- [x] Génère structure dossier valide PZ (mod.info, init.lua, media/lua/*/, ZomboidModDescriptor.txt)
- [x] Templates Jinja2 (7 fichiers: mod.info, init.lua, descriptors, scripts lua, README)
- [x] CLI : `python -m src.modgen generate/list-templates/validate`
- [x] Commande slash `/modgen` dans bot Discord

### 12.3 Pipeline Build & Packaging ✅
- [x] Cible `make mod-build MOD_NAME=my-mod` → ZIP dans mods/
- [x] Cible `make mod-validate MOD_DIR=path/to/mod`

### 12.5 Sauvegarde des mods générés ✅
- [x] Répertoire `mods/` créé (.gitkeep)

### 12.6 Configuration & Documentation
- [x] Extension `.env.example` : MOD_TEMPLATES_PATH, MOD_OUTPUT_PATH (déjà fait)
- [x] Documenter flux de travail dans README.md (section "Génération de mods" avec exemples, workflow, templates)

### 12.7 Tests & CI
- [x] Unitaires du générateur — 32 tests existants (test_modgen.py)
- [x] Test d'intégration : description → zip → validation manifeste — 15 tests (test_modgen_integration.py)
- [x] CI : exécution tests modgen dans .github/workflows/tests.yml

### 12.8 Facultatif : publication Steam Workshop
- [x] Intégrer SteamCMD (déjà présent dans `tools/steamcmd`) pour upload direct — ✅ steamcmd_client.upload_workshop_item()
- [x] Commande `/modpublish` déclenchant tâche CI ou script local via API Web Steam — ✅ cmd_modpublish() + helpers _find_mod_dir / _extract_mod_metadata

## Sync auto: last_sync: 2026-07-06 — todo verified + UI Lua docs + CI golden set + watchdog + steam upload

## Sync auto: last_sync: 2026-07-06

## Sync auto: last_sync: 2026-07-07

## Sync auto: last_sync: 2026-07-07

## Sync auto: last_sync: 2026-07-07

## Sync auto: last_sync: 2026-07-07

## Sync auto: last_sync: 2026-07-08

## NOUVEAU : Phase S9 — Migration SQLite → PostgreSQL-only ⬜ (détaillé dans agent/todo_storage_migration.md)
- [ ] P1-Supprimer fichiers morts (sqlite_storage.py, test_sqlite_storage.py, test_dual_backend.py, convert_sqlite_to_pg.py)
- [ ] P2-Refactor core storage layer (PG default, clean __init__.py)
- [ ] P3-Migrer tous les callers (bot/, retrieval/, ingestor/)
- [ ] P4-Config default → postgres, remove dual-sync legacy
- [ ] P5-Adapter tests + full suite validation
- [ ] P6-Update docs (ARCHITECTURE, SETUP, README, CHANGELOG)
- [ ] P7-Validate final: pytest full + lint + import check

## Sync auto: last_sync: 2026-07-08