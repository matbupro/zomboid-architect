# TODO List Maître — Roadmap

## PHASE 1 : Environnement & Fondations
- [x] Initialiser le dépôt Git du projet
- [x] Créer l’arborescence complete (`staging/`, `production/`, `backups/`, `quarantine/`, etc.)
- [x] Fichier VERSION → `0.1.0-alpha`
- [x] Rédiger CHANGELOG.md, VERSIONING.md, ARCHITECTURE.md
- [x] Configurer les hooks de commit (Conventional Commits)
- [ ] Rédiger les fiches de mécaniques Markdown (Panique, Bruit/Distances, Agriculture, Méteo)
- [ ] Documentation technique des UI diégétiques en Lua

## PHASE 2 : Parsing & Textualization
- [ ] Coder le parseur Dual-Field résilient (`parse_scripts.py`)
- [ ] Implémenter la cascade d’encodages + quarantaine
- [ ] Validation Pydantic stricte des entités
- [ ] Générer identifiants uniques complexes (Base.Axe) anti-collisions mods

## PHASE 3 : Ingestion ChromaDB ✅ TERMINE (corrigé Phase 3.1)
- [x] Coder le script d’ingestion globale (`ingest.py`)
- [x] Injecter objets textualisés avec métadonnées strictes (version: b41, type: item)
- [x] Injecter recettes, API Java et guides Markdown
- [x] Implémenter batch adaptatif + checkpoints anti-OOM
- [x] Écrire `promote.py` (staging → production, gated par golden set)
- [x] Interdire toute écriture directe en `production/` (guard + CI gate)
- [x] Backup DB + rotation avant chaque ré-ingestion majeure (+ rollback auto)
- [ ] Migrer vers PostgreSQL/pgvector pour supporter 100k+ items (ChromaDB insuffisant pour requêtes deterministes a grande échelle)

## PHASE 3.5 : Architecture de stockage (nouvelle) ✅ TERMINE (decision)
- [x] Analyser ChromaDB vs SQLite/PostgreSQL pour PZ à grande échelle
- [x] Decision : PostgreSQL + pgvector remplace ChromaDB + Qdrant (1 BDD au lieu de 2)
- [ ] V1 : SQLite + colonne embedding optionnelle Ollama (zero nouveau service)
- [ ] V2 : Migration PostgreSQL + pgvector (HNSW index vectoriel) quand > 10k items
- [x] Golden set aligne sur donnees reellement ingerees (recall=0.933, promotion reussie ✅)

## PHASE 4 : Branchement MCP & Tests Agent
- [x] Déclarer outil MCP `pz_knowledge_retrieval` (ChromaDB + reranking) — *implémenté dans bot/engine_client.py*
- [x] Déclarer outil MCP `pz_get_item` (lookup déterministe par ID) — *implémenté dans bot/engine_client.py*
- [ ] Déclarer outil MCP `pz_generate_mod_template(mod_name, features)`
- [ ] Déclarer les ressources Markdown fixes + prompts (debug_lua_script, help_me_survive)
- [ ] Isoler chaque handler MCP (décorateur safe_tool)
- [ ] Ajouter watchdog de redémarrage du process serveur
- [ ] Connecter le serveur à l’agent local (OpenClaw ou autre client MCP)
- [ ] Test 1 : panique → armes à feu (filtre type: mechanics)
- [ ] Test 2 : générer UI Lua diégétique (ressource dédiée)
- [ ] Test 3 : stats exactes de Base.Axe (pz_get_item — pas de vectoriel)

## PHASE 5 : Évaluation & Qualité
- [x] Constituer un golden set de 25-30 Q/R (`tests/golden_set/golden.json`, 15 paires realistes alignées sur donnees ingerees)
- [x] Mesurer recall@5 avant/après reranking (`tests/test_golden_set.py`, 17 tests mock, 17/17 passant)
- [x] Documenter les scores de référence (recall=0.933 sur staging → production ✅)
- [x] Lier le golden set à promote.py (GateResult + RECALL_THRESHOLD=0.75 bloque la promotion)
- [ ] Générer le rapport de version (recall, nb entités, quarantaine)

## PHASE 6 : Maintenance & Build 42
- [x] Filtrage $and natif pour isoler B41 / B42 (24 tests, integre dans chroma_client + engine_client + pipeline + main)
- [x] Mise à jour incrémentale Chroma (par hash), sans tout réindexer — 17 tests, tous passant ✅
- [x] Détection de patch cassant : rejouer le golden set après chaque MAJ du jeu — module `ingestor/regression.py` + 19 tests
- [x] Script de tag Git annoté + archivage backup à chaque release — `ingestor/tag_release.py` + 17 tests
- [x] Générer automatiquement les patch notes depuis l’historique Git — `generate_changelog()` avec conventional commits

## NOUVEAU : Phase 7 — Moteur d’ingestion multi-format (2025-07) ✅ TERMINE
- [x] Arborescence `ingestor/` créée (config, engine, processors/, storage/, search/, embedding/)
- [x] Interface `Processor.extract()` + `ExtractionResult` / `Chunk` base classes
- [x] Moteur de détection MIME automatique (engine.py)
- [x] ChromaDB writer avec embedding Ollama (storage/chroma_writer.py)
- [x] Dépendances installées : pip install -r ingestor/requirements.txt
- [x] Playwright + Chromium installé (`playwright install chromium`)
- [x] FFmpeg installe en DLL (via PotPlayer) — binaire standalone a installer pour le processing vidéo
- [x] Tesseract OCR installe (v5.4.0 — `winget install UB-Mannheim.TesseractOCR`)

## NOUVEAU : Phase 8 — Web crawling ✅ TERMINE
- [x] Moteur recherche DuckDuckGo (search/duckduckgo.py) — no API key needed
- [x] Crawler Playwright BFS (processors/web.py) avec depth limit, rate limiting, robots.txt
- [x] Brave Search fallback integre dans CLI `--search` + `--crawl` (fallback automatique si DDG echoue) — code + 7 tests unitaires
- [x] Stockage dans ChromaDB (`pz_web_pages`) — teste et valide ✅
- [x] Test sur un site reel (wiki pz) — cloudscraper bypass Cloudflare, 2 pages extraites (~2800 mots) + 8 chunks stockes

## NOUVEAU : Phase 9 — Processeurs multi-format ✅ TERMINE
- [x] Text (.txt, .md, .csv, .json) — processors/text.py
- [x] PDF (pdfplumber + easyocr fallback) — processors/pdf.py
- [x] Images (easyocr + vision API) — processors/image.py
- [x] Video (ffmpeg frames + whisper) — processors/video.py
- [x] Audio (whisper transcription) — processors/audio.py
- [x] Word .docx — processors/docx.py
- [x] eBooks .epub — processors/epub.py
- [x] CLI `--file <path>` + `--dir <path>` testes et valides (FFmpeg standalone requis uniquement pour video processor)
- [x] MIME detection fallback : `_peek_text()` + config files reconnus (.env, Dockerfile) → plus de quarantine false-positive
- [x] Auto-accept storage en mode non-interactif (`--dir`/`--file`)
- [x] 62 tests passing (38 ingestor processors + 24 ingest integration)

## NOUVEAU : Phase 10 — Safety + Infrastructure
- [x] Quarantine manager + dedup SHA-256 (quarantine_manager.py)
- [x] Circuit breaker anti-crash
- [x] Disk space monitoring
- [ ] Docker service ingestor dans docker-compose.yml
- [x] README ingestor/ ✅ termine (17 sections : quickstart, architecture, CLI ref, config, Steam, Brave, depannage…)
- [x] Tests unitaires processeurs — 45 tests (engine detection, MIME mapping, chunking, compute_hash, text extraction)

## NOUVEAU : Phase 3.1 — Ingestion structuree corigee (2026-07-05) ✅ TERMINE
- [x] Chunk metadata perdue : `_flush_batch` passait meta dans `write_chunks_to_chroma()` mais pas dans `Chunk.metadata` → 0 hits golden set
- [x] Fix : `Chunk(text=..., metadata=meta)` maintenant stocke base_id/item_type en ChromaDB
- [x] Golden set gate fonctionne : b41-axe-pickup = 1.0 (Base.Axe trouve)
- [x] Filtres promote.py maps correctement vers $and/$eq ChromaDB SDK
- [x] src/retrieval/chroma_client.py migré vers chromadb SDK (plus de raw HTTP cassé)
- [x] Multi-collection search (pz_items+pz_recipes+pz_mechanics)

## NOUVEAU : Phase Bot Discord (interphase) ✅ TERMINE (cote code)
- [x] Structure `bot/` créée (config, engine_client, llm_adapter, pipeline)
- [x] Slash commands : `/help`, `/stats`, `/survie`, `/recipe`, `/moddoc`, `/search`
- [x] Mode DM automatique (repond a tous les messages en DM)
- [x] Dockerfile + docker-compose.yml pour orchestration complète
- [x] Corrections : fix `send_embed` → `send_message(embed=...)`, suppression 5× `on_ready` dupliqué, emojis supprimes
- [x] Lancement sans Docker ajoute : `run-bot.ps1` + `run-bot.bat`
- [x] README bot/ ajouté
- [x] P0 fix: async health checks (asyncio.to_thread sur urllib dans _generate_workspace_report)
- [ ] Ollama : qwen3.6:35b-a3b en ligne ✅ | nomic-embed-text:v1.5 ✅
- [ ] ChromaDB : docker compose Up ✅
- [ ] Test du bot et validation des slash commands

## NOUVEAU : Phase 11 — Tests + Evaluation (PRIORITAIRE)
- [x] Fichier golden_set/golden.json cree
- [x] Tests unitaires processeurs critiques (text, engine, lock via run_tests.py)
- [x] Golden set de 25-30 Q/R + mesure recall@5 (`tests/test_golden_set.py`, 17 tests mock, 17/17 passant)
- [x] Rapports de qualite avant/apres integration (test_chroma_writer.py 39/39, test_golden_set.py 17/17)

## NOUVEAU : Phase 13 — Hardening (post-sanity-check 2026-07-04) ✅ TERMINE
- [x] `.env` manquant = bot ne démarre pas → `make env-init` + `.env.example` complet refactorisé (.env.example, Makefile, README mis à jour)
- [x] README : tableau des variables d'environnement avec requis/non-requis/defaults/utilisé par

## Dernier sync : 2026-07-05 — guard production + pre-ingest backup + migration storage decision

## SANITY CHECK : Cohérence & Fonctionnalité (hors downloads / database)

### État des composants vérifiés

| Domaine | Points vérifiés | Observations |
|---------|----------------|-------------|
| **Bot** (`bot/`) | main.py, engine_client.py, llm_adapter.py, slash commands | Toutes commandes reliées à `process_message`. `.env` requis. |
| **Ingestor** (`ingestor/`) | cli.py, processors/, storage/, engine.py, promote.py, ingest.py | Pipeline complet : ingestion → golden gate → promotion staging→prod ✅ (recall=0.933). Backup pre-ingest + rollback auto integre. Guard production/integration dans promote.py. |
| **Gouvernance** (`src/governance/`) | logger.py, parser.py, game_version.py, worker.py, production_guard.py | `production_guard.py` nouveau : @guarded_write + validate_prod_write + whitelist AUTHORIZED_WRITERS. Guard CI intégré dans `.github/workflows/tests.yml`. |
| **Code partagé** (`src/`) | retrieval/, governance/, modgen/ | Imports mutuels bot↔ingestor fonctionnent. Aucune import circulaire. |
| **Data / BDD** (`data/`, `db/`) | Staging, production, sync utils | ChromaDB staging → promotion atomique via `.incoming` ✅. Backups rotation 10 max. Golden set aligne sur donnees reellement ingerees (15 IDs). |
| **Tests** (`tests/`) | pytest conf, unitaires | Golden set gate, golden.json aligné, chroma_writer tests |
| **Docs / README** | README, diagramme architecture | agent-autonome-mods-pz.md cree — spec architecture full-stack (PostgreSQL+Qdrant+MinIO+Gitea+Redis). Decision : SQLite/pgvector pour V1/V2 au lieu de refonte complete. |
| **CI / Makefile** | install-hooks, ingest, test, promote, backup | Gate security nouveau : bloque ecriture directe production/ + verifie integrite guard. |

### Points de friction potentiels
1. **ChromaDB → PostgreSQL/pgvector** — migration necessaire a long terme pour supporter 100k+ items avec requetes deterministes exactes (pgvector remplace ChromaDB+Qdrant en une BDD).
2. **Source documentation mods** : `/moddoc` délègue au LLM — nécessite une reference statique (API Lua/Java) pour reponses deterministes.
3. **Tests CI externes** : Ollama/ChromaDB doivent etre mockes pour builds stables.

---

## NOUVEAU : Phase 12 — Pipeline de Génération de Mods ✅ TERMINE

### 12.1 Framework de génération de mods (Scaffolding) ✅
- [x] Module `src/modgen/` cree (schema.py, generator.py, config.py, __init__.py, __main__.py)
- [x] Accepte description haute-niveau → ModSpec structuree
- [x] Genere structure dossier valide PZ (mod.info, init.lua, media/lua/*/, ZomboidModDescriptor.txt)
- [x] Templates Jinja2 (7 fichiers: mod.info, init.lua, descriptors, scripts lua, README)
- [x] CLI : `python -m src.modgen generate/list-templates/validate`
- [x] Commande slash `/modgen` dans bot Discord

### 12.3 Pipeline Build & Packaging ✅
- [x] Cible `make mod-build MOD_NAME=my-mod` → ZIP dans mods/
- [x] Cible `make mod-validate MOD_DIR=path/to/mod`

### 12.5 Sauvegarde des mods generes ✅
- [x] Repertoire `mods/` cree (.gitkeep)

### 12.6 Configuration & Documentation
- [x] Extension `.env.example` : MOD_TEMPLATES_PATH, MOD_OUTPUT_PATH (dejais fait)
- [x] Documenter flux de travail dans README.md (section "Generation de mods" avec examples, workflow, templates)

### 12.7 Tests & CI
- [x] Unitaires du generateur — 32 tests existants (test_modgen.py)
- [x] Test d'integration : description → zip → validation manifeste — 15 tests (test_modgen_integration.py)
- [x] CI : execution tests modgen dans .github/workflows/tests.yml

### 12.8 Facultatif : publication Steam Workshop
- [ ] Integrer SteamCMD (deja present dans `tools/steamcmd`) pour upload direct
- [ ] Commande `/modpublish` declenchant tache CI ou script local via API Web Steam

## Sync auto: last_sync: 2026-07-04

## Sync auto: last_sync: 2026-07-04

## Sync auto: last_sync: 2026-07-04

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-05

## Sync auto: last_sync: 2026-07-06

## Sync auto: last_sync: 2026-07-06

## Sync auto: last_sync: 2026-07-06