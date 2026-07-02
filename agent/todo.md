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
- [ ] Constituer un golden set de 25-30 Q/R
- [ ] Mesurer recall@5 avant/après reranking
- [ ] Documenter les scores de référence
- [ ] Lier le golden set à promote.py (blocage si régression)
- [ ] Générer le rapport de version (recall, nb entités, quarantaine)

## PHASE 6 : Maintenance & Build 42
- [ ] Filtrage $and natif pour isoler B41 / B42
- [ ] Mise à jour incrémentale Chroma (par hash), sans tout réindexer
- [ ] Détection de patch cassant : rejouer le golden set après chaque MAJ du jeu
- [ ] Script de tag Git annoté + archivage backup à chaque release
- [ ] Générer automatiquement les patch notes depuis l’historique Git

## NOUVEAU : Phase 7 — Moteur d'ingestion multi-format (2025-07)
- [x] Arborescence `ingestor/` créée (config, engine, processors/, storage/, search/, embedding/)
- [x] Interface `Processor.extract()` + `ExtractionResult` / `Chunk` base classes
- [x] Moteur de détection MIME automatique (engine.py)
- [x] ChromaDB writer avec embedding Ollama (storage/chroma_writer.py)
- [ ] Dépendances installées : pip install -r ingestor/requirements.txt
- [ ] Playwright + Chromium installé : playwright install chromium
- [ ] FFmpeg installé (winget install ffmpeg ou téléchargement manuel)
- [ ] Tesseract OCR installé (winget install Tesseract)

## NOUVEAU : Phase 8 — Web crawling (prioritaire n°1)
- [x] Moteur recherche DuckDuckGo (search/duckduckgo.py) — no API key needed
- [x] Crawler Playwright BFS (processors/web.py) avec depth limit, rate limiting, robots.txt
- [ ] Brave Search en fallback (search/brave.py)
- [ ] CLI `--search "query"` + `--crawl <seed>` fonctionnels
- [ ] Stockage automatique dans ChromaDB (`pz_web_pages`)
- [ ] Test sur un site réel (wiki, documentation)

## NOUVEAU : Phase 9 — Processeurs multi-format
- [x] Text (.txt, .md, .csv, .json) — processors/text.py
- [x] PDF (pdfplumber + easyocr fallback) — processors/pdf.py
- [x] Images (easyocr + vision API) — processors/image.py
- [x] Vidéo (ffmpeg frames + whisper) — processors/video.py
- [x] Audio (whisper transcription) — processors/audio.py
- [x] Word .docx — processors/docx.py
- [x] eBooks .epub — processors/epub.py
- [ ] CLI `--file <path>` auto-détection fonctionnelle
- [ ] CLI `--dir <path>` batch ingestion

## NOUVEAU : Phase 10 — Safety + Infrastructure
- [x] Quarantine manager + dedup SHA-256 (quarantine_manager.py)
- [x] Circuit breaker anti-crash
- [x] Disk space monitoring
- [ ] Docker service ingestor dans docker-compose.yml
- [ ] README ingestor/
- [ ] Tests unitaires processeurs

## NOUVEAU : Phase Bot Discord (interphase)
- [x] Structure `bot/` créée (config, engine_client, llm_adapter, pipeline)
- [x] Slash commands : `/help`, `/stats`, `/survie`, `/recipe`, `/moddoc`, `/search`
- [x] Mode DM automatique (répond à tous les messages en DM)
- [x] Dockerfile + docker-compose.yml pour orchestration complète
- [x] Corrections : fix `send_embed` → `send_message(embed=...)`, suppression 5× `on_ready` dupliqué, emojis supprimés (crash CP1252)
- [x] Lancement sans Docker ajouté : `run-bot.ps1` + `run-bot.bat`
- [x] README bot/ ajouté
- [ ] Lancer le bot et tester dans Discord
