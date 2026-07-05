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

## PHASE 3 : Ingestion ChromaDB
- [ ] Coder le script d’ingestion globale (`ingest.py`)
- [ ] Injecter objets textualisés avec métadonnées strictes (version: b41, type: item)
- [ ] Injecter recettes, API Java et guides Markdown
- [ ] Implémenter batch adaptatif + checkpoints anti-OOM
- [ ] Écrire `promote.py` (staging → production, gated par golden set)
- [ ] Interdire toute écriture directe en `production/`
- [ ] Backup DB + rotation avant chaque ré-ingestion majeure

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
- [x] Constituer un golden set de 25-30 Q/R (`tests/golden_set/golden.json`, 28 paires Q/R B41+B42)
- [x] Mesurer recall@5 avant/après reranking (`tests/test_golden_set.py`, 17 tests mock, 17/17 passant)
- [ ] Documenter les scores de référence (contre ChromaDB reel avec donnees ingestees)
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

## NOUVEAU : Phase 8 — Web crawling
- [x] Moteur recherche DuckDuckGo (search/duckduckgo.py) — no API key needed
- [x] Crawler Playwright BFS (processors/web.py) avec depth limit, rate limiting, robots.txt
- [x] Brave Search fallback integre dans CLI `--search` + `--crawl` (fallback automatique si DDG echoue) — code + 7 tests unitaires
- [x] Stockage dans ChromaDB (`pz_web_pages`) — code ecrit mais pas teste
- [ ] Test sur un site reel (wiki pz, documentation)

## NOUVEAU : Phase 9 — Processeurs multi-format ✅ TERMINE
- [x] Text (.txt, .md, .csv, .json) — processors/text.py
- [x] PDF (pdfplumber + easyocr fallback) — processors/pdf.py
- [x] Images (easyocr + vision API) — processors/image.py
- [x] Video (ffmpeg frames + whisper) — processors/video.py
- [x] Audio (whisper transcription) — processors/audio.py
- [x] Word .docx — processors/docx.py
- [x] eBooks .epub — processors/epub.py
- [ ] CLI `--file <path>` + `--dir <path>` testes et valides (deppr FFmpeg standalone)

## NOUVEAU : Phase 10 — Safety + Infrastructure
- [x] Quarantine manager + dedup SHA-256 (quarantine_manager.py)
- [x] Circuit breaker anti-crash
- [x] Disk space monitoring
- [ ] Docker service ingestor dans docker-compose.yml
- [x] README ingestor/ ✅ termine (17 sections : quickstart, architecture, CLI ref, config, Steam, Brave, depannage…)
- [x] Tests unitaires processeurs — 45 tests (engine detection, MIME mapping, chunking, compute_hash, text extraction)

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

## Dernier sync : 2026-07-04 — hardening post-sanity-check (Phase 13) ✅ TERMINE

## SANITY CHECK : Cohérence & Fonctionnalité (hors downloads / database)

### État des composants vérifiés

| Domaine | Points vérifiés | Observations |
|---------|----------------|-------------|
| **Bot** (`bot/`) | main.py, engine_client.py, llm_adapter.py, slash commands | Toutes commandes (/stats, /survie, /recipe, /moddoc, /search, /workspace) reliées à `process_message`. `.env` requis (DISCORD_TOKEN, OLLAMA_BASE_URL, etc.). |
| **Ingestor** (`ingestor/`) | cli.py, processors/, storage/, engine.py | CLI (`--file`, `--search`, `--crawl`, `--dir`) partage le meme pipeline que le bot. Verrou `src/governance/lock.py` — répertoire de verrouillage à créer (`src/governance/data/workspace/`). |
| **Gouvernance** (`src/governance/`) | logger.py, parser.py, game_version.py, worker.py | Rotation fichiers + audit JSON. `parser.py` lit `agent/todo.md`. Pas d'erreur d'importation. |
| **Code partagé** (`src/`) | retrieval/, governance/ | Imports mutuels bot↔ingestor fonctionnent. Aucune import circulaire. |
| **Data / BDD** (`data/`, `db/`) | Staging, production, sync utils | Workspace report interroge santé ChromaDB + Ollama avec fallbacks élégants. |
| **Tests** (`tests/`) | pytest conf, unitaires | Ingestion, PBO parsing, SteamCMD, golden set — `make test` devrait passer (Ollama accessible requis). |
| **Docs / README** | README, diagramme architecture | Clair, mais source docs pour `/moddoc` (API Lua/Java) non incluse. |
| **CI / Makefile** | install-hooks, ingest, test, promote, backup | Toutes cibles présentes. |

### Points de friction potentiels
1. **Répertoire de verrouillage manquant** : `src/governance/data/workspace/` — à créer ou droits écriture vérifiés.
2. **Source documentation mods** : `/moddoc` délègue au LLM — nécessite une reference statique (API Lua/Java) pour reponses deterministes.
3. **Variables d'environnement** : nombreuses clés optionnelles (WORKSPACE_CHANNEL_ID, CLAUDE_API_KEY...) — absentes = warnings (acceptable mais à clarifier dans README).
4. **Tests CI externes** : Ollama/ChromaDB doivent être mockés pour builds stables.

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