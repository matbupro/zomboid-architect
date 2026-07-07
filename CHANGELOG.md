# Changelog — Zomboid Knowledge Engine

Toutes les modifications notables, organisées par session de développement.

---

## [v0.4.0-alpha] — 2026-07-06

### Nouveau moteur d'ingestion multi-format (Phases 7 → 9)

Pipeline complet de lecture de **tout format** (PDF, images, vidéo, audio, docx, epub, web), extraction en texte pur, embedding via Ollama, stockage [storage vectoriel]/SQLite.  [historique]

| Fichier | Rôle |
|---------|------|
| `ingestor/cli.py` | CLI (`--search`, `--file`, `--dir`, `--crawl`, `--url`, `--list-collections`, `--search-all`) |
| `ingestor/engine.py` | Router MIME → processeur, détection URL vs fichier |
| `ingestor/config.py` | Settings centralisés ([storage vectoriel], Ollama, OCR, web) |  [historique]
| `ingestor/processors/base.py` | Interface `Processor`, dataclasses `Chunk`, `ExtractionResult` |
| `ingestor/processors/text.py` | Processeur `.txt`, `.md`, `.csv`, `.json` |
| `ingestor/processors/pdf.py` | PDF → texte (pdfplumber) + OCR fallback (easyocr) |
| `ingestor/processors/image.py` | Images → OCR multi-langue + description vision API |
| `ingestor/processors/video.py` | Vidéo → ffmpeg frames + transcription audio Whisper |
| `ingestor/processors/audio.py` | Audio → transcription complète |
| `ingestor/processors/docx.py` | Word `.docx` extraction texte |
| `ingestor/processors/epub.py` | eBook `.epub` extraction contenu |
| `ingestor/processors/web.py` | Crawler Playwright BFS + WebProcessor (readability) |
| `ingestor/search/duckduckgo.py` | Moteur recherche DuckDuckGo (ddgs v9.x, no API key) |
| `ingestor/storage/storage_writer.py [historique]` | Writer [storage vectoriel] SDK + Ollama embedding + cross-collection search |  [historique]
| `ingestor/quarantine_manager.py` | Dédup SHA-256, circuit breaker, monitoring disque |
| `ingestor/requirements.txt` | Dépendances Python du moteur d'ingestion |

#### Collections [storage vectoriel] ajoutées  [historique]
| Collection | Contenu |
|------------|---------|
| `pz_web_pages` | Pages web crawlées (DuckDuckGo + Playwright) |
| `pz_pdfs` | Documents PDF / texte ingérés |
| `pz_images` | Images → descriptions OCR/vision |
| `pz_videos` | Vidéos → transcriptions audio |
| `pz_audios` | Fichiers audio → transcriptions |

### Moteur de génération de mods (Phase 12)

Génération de mods PZ valides depuis description textuelle.

- **CLI** : `python -m src.modgen generate "Une épée" --name "MySword"`
- **Bot Discord** : `/modgen <description>` → génération auto + retour fichiers
- **Templates PZ valides** : mod.info JSON, init.lua, ZomboidModDescriptor.txt
- **Packaging** : `make mod-build MOD_NAME=MyMod` → ZIP dans `mods/`
- **Validation** : `python -m src.modgen validate /path/to/mod/`
- **Tests** : 32 unitaires + 15 integration (ZIP manifest)

### Storage layer SQLite avec embedding Ollama (Phase 3.5 V1)

Remplacement de [storage vectoriel] par SQLite local — zéro service externe requis.  [historique]

| Fichier | Rôle |
|---------|------|
| `src/storage/sqlite_storage.py` | Stockage per-collection, cosine similarity SQL, embedding optionnel Ollama |
| `src/storage/__init__.py` | Module init + exports publics |
| `tests/test_sqlite_storage.py` | **36 tests** passing (collections, CRUD, vector search, filters, getById, cross-search, embedder mock) |

- SQLite par collection (tables `z_pz_items`, `z_pz_recipes`...) avec JSON metadata
- Similarité cosinus en SQL pur + Python (pas de dépendance C extension)
- Embedding Ollama auto-généré à l'écriture
- Metadata filtering ($and / $eq / version) via JSON operators SQLite `->>`
- `StorageBackend` unifié avec fallback auto [storage vectoriel] → SQLite  [historique]

### Bot Discord complet (Phase Bot)

- Slash commands : `/help`, `/stats`, `/survie`, `/recipe`, `/moddoc`, `/search`, `/modgen`
- Mode DM automatique, Docker compose (3 services), scripts `run-bot.ps1/bat`
- Pipeline : message → detect_intent → enrich_context ([storage vectoriel]/fallback) → LLM.complete  [historique]

### Hardening + Infrastructure (Phase 10 & 13)

- Quarantine manager + dedup SHA-256, circuit breaker anti-crash, monitoring disque
- Docker service ingestor dans docker-compose.yml (on-demand `docker compose run`)
- `.env` manquant → bot ne démarre pas (guard + `.env.example` complet)
- Makefile : `make env-init`, `make ingest`, `make test`, `make promote`, `make backup`

### Corrections de bugs

9 fixes inclus (import circulaire WebProcessor, CLI bloqué input(), FileNotFoundError engine.ingest(), Chunk missing start_offset, [storage vectoriel] upsert [[...]], UnicodeEncodeError emoji Windows CMD, [storage vectoriel] query_embeddings rename, DDGS regions→region, DDGS time param removed) + MIME detection fallback `peek_text()` + 0 quarantine false-positives  [historique]

---

## [v0.3.0-alpha] — 2026-07-04

### Phase 6 : Filtrage B41/B42 natif dans le pipeline de requête

Isolement complet des données par version du jeu (B41 vs B42) via les filtres `$and` natifs de [storage vectoriel].  [historique]

#### Fichiers modifiés

| Fichier | Changement |
|---------|-----------|
| `src/governance/game_version.py` | +3 fonctions : `build_version_filter()`, `build_version_and()`, `build_version_not_filter()` |
| `[fichier supprimé — sqlite_storage.py] [historique]` | `query()` accepte `game_version` — compose automatiquement $and avec filters existants |
| `bot/engine_client.py` | `search()`, `get_by_id()`, `query_staging()` propagent tous `game_version` via $and |
| `bot/pipeline.py` | `enrich_context()` et `process_message()` passent `game_version` au moteur |
| `bot/main.py` | Résolution de PZ_GAME_VERSION au démarrage + propagation dans le pipeline bot |
| `bot/config.py` | Ajout de `PZ_GAME_VERSION` dans Settings + résolution depuis .env |

#### Fichiers testés

| Fichier | Tests |
|---------|-------|
| `tests/test_game_version_filtering.py` | 24 tests (filter builders, tag_chunk, integration [storage vectoriel] client (historique)/engine_client) |

### Moteur de génération de mods (`src/modgen/`) — nouvelle (Phase 12)

Génération de mods Project Zomboid valides à partir d'une description textuelle.

#### Fichiers créés

| Fichier | Rôle |
|---------|------|
| `src/modgen/__init__.py` | Module init + exports publics |
| `src/modgen/schema.py` | Dataclasses: ModSpec, GeneratedModManifest, ModFile, ModType |
| `src/modgen/generator.py` | Moteur principal (ModGenerator class) |
| `src/modgen/config.py` | Config du générateur (ModGenConfig + load_modgen_config) |
| `src/modgen/__main__.py` | CLI (`generate`, `list-templates`, `validate`) |
| `src/modgen/templates/*.j2` | 7 templates Jinja2 (mod.info, init.lua, descriptors, README) |
| `tests/test_modgen.py` | **32 tests unitaires** — schema, generation, validation, CLI, ZIP |

#### Fonctionnalités

- **CLI** : `python -m src.modgen generate "Une épée" --name "MySword"`
- **Bot Discord** : `/modgen "Ajouter une arme furtive"` → génération auto + retour fichiers
- **Templates PZ valides** : mod.info JSON, init.lua avec hooks, ZomboidModDescriptor.txt
- **Packaging** : `make mod-build MOD_NAME=MyMod` → ZIP dans `mods/`
- **Validation** : `python -m src.modgen validate /path/to/mod/`

#### Slash commands ajoutés

| Commande | Description |
|----------|-------------|
| `/modgen <description>` | Génère un mod PZ depuis une description textuelle |
| `/help` | Mis à jour avec /modgen dans la liste |

---

## [v0.2.0-alpha] — 2026-07-02

### Moteur d'ingestion multi-format (`ingestor/`) — nouveau

Création complète du moteur d'ingestion multi-modal : lecture de **tout format** (PDF, images, vidéo, audio, docx, epub) et du **web**, extraction en texte pur, embedding via Ollama, stockage [storage vectoriel].  [historique]

#### Nouveaux fichiers créés

| Fichier | Rôle |
|---------|------|
| `ingestor/cli.py` | Entrée CLI (`--search`, `--file`, `--dir`, `--crawl`, `--url`, `--list-collections`, `--search-all`) |
| `ingestor/engine.py` | Router MIME → processeur, détection URL vs fichier |
| `ingestor/config.py` | Settings centralisés ([storage vectoriel], Ollama, OCR, web) |  [historique]
| `ingestor/processors/base.py` | Interface `Processor`, dataclasses `Chunk`, `ExtractionResult` |
| `ingestor/processors/text.py` | Processeur `.txt`, `.md`, `.csv`, `.json` |
| `ingestor/processors/pdf.py` | PDF → texte (pdfplumber) + OCR fallback (easyocr) |
| `ingestor/processors/image.py` | Images → OCR multi-langue + description vision API |
| `ingestor/processors/video.py` | Vidéo → ffmpeg frames + transcription audio Whisper |
| `ingestor/processors/audio.py` | Audio → transcription complète |
| `ingestor/processors/docx.py` | Word `.docx` extraction texte |
| `ingestor/processors/epub.py` | eBook `.epub` extraction contenu |
| `ingestor/processors/web.py` | Crawler Playwright BFS + WebProcessor (extraction HTML/readability) |
| `ingestor/search/duckduckgo.py` | Moteur recherche DuckDuckGo (ddgs v9.x, no API key) |
| `ingestor/storage/storage_writer.py [historique]` | Writer [storage vectoriel] SDK + Ollama embedding + cross-collection search |  [historique]
| `ingestor/quarantine_manager.py` | Dédup SHA-256, circuit breaker, monitoring disque |
| `ingestor/requirements.txt` | Dépendances Python du moteur d'ingestion |
| `ingestor/README.md` | Documentation du module |

#### Collections [storage vectoriel] ajoutées  [historique]

| Collection | Contenu |
|------------|---------|
| `pz_web_pages` | Pages web crawlées (DuckDuckGo + Playwright) |
| `pz_pdfs` | Documents PDF / texte ingérés |
| `pz_images` | Images → descriptions OCR/vision |
| `pz_videos` | Vidéos → transcriptions audio |
| `pz_audios` | Fichiers audio → transcriptions |

---

### Corrections de bugs (9 fixes)

#### Bug 1 — Import circulaire WebProcessor (`duckduckgo.py`)

Le crawler `search_and_crawl()` tentait d'importer `web` depuis le package `ingestor.search/`, alors que `web.py` est dans `processors/`.

**Fix :** [ingestor/search/duckduckgo.py](ingestor/search/duckduckgo.py):
```python
# Before (broken):  from . import web as web_proc
# After:            from ..processors import web as web_proc  # lazy import
```

#### Bug 2 — CLI bloqué sur `input()` quand stdin pipé (`cli.py`)

`handle_search()` et `handle_file()` utilisaient `input()` qui bloque dans un contexte non-interactif (pipe, CI).

**Fix :** [ingestor/cli.py](ingestor/cli.py):
```python
_auto_accept = not sys.stdin.isatty()  # piped/CI → auto yes
try:
store = input("...") if _auto_accept else "y"
except EOFError:
store = "y"  # pipe fermé → auto yes
```

#### Bug 3 — `engine.ingest(query)` → `FileNotFoundError` (`cli.py`)

`handle_search()` passait la **requête de recherche** comme source au moteur d'ingestion au lieu des résultats crawlés. Le moteur tentait donc de trouver un fichier nommé "Project Zomboid survival guide tips".

**Fix :** [ingestor/cli.py](ingestor/cli.py) — utiliser directement les `SearchResult.body` du crawl :
```python
all_chunks.append(BaseChunk(text=r.body, index=i, start_offset=0))
await write_chunks_to_storage [historique](chunks=all_chunks, ...)
```

#### Bug 4 — `Chunk.__init__()` manquait `start_offset` (`cli.py`)

Le Chunk créé manuellement omettait le champ `start_offset: int` requis.

**Fix :** [ingestor/cli.py](ingestor/cli.py):
```python
BaseChunk(text=r.body, index=i, start_offset=0)  # + start_offset obligatoire
```

#### Bug 5 — Upsert [storage vectoriel] `[[...]]` imbriqué (`storage_writer.py`)  [historique]

Les listes de documents et metadatas étaient enveloppées dans une paire de crochets superflue `[docs_w]`, rendant les dimensions incompatibles.

**Fix :** [ingestor/storage/storage_writer.py [historique]](ingestor/storage/storage_writer.py [historique]):
```python
# Before: col.upsert(ids=ids, embeddings=[[...]], documents=[[...]], metadatas=[[...]])
# After:  ids_w = [x[1] for x in with_embed]; vecs_w = [...]
#         col.upsert(ids=ids_w, embeddings=vecs_w, documents=docs_w, metadatas=metas_w)
```

#### Bug 6 — `UnicodeEncodeError` emoji 🧟 sur Windows CMD (`cli.py`)

Windows CMD encode stdout en CP1252 par défaut → crash sur tout caractère non-ASCII.

**Fix :** [ingestor/cli.py](ingestor/cli.py):
```python
if hasattr(sys.stdout, "reconfigure"):
sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
sys.stderr.reconfigure(encoding="utf-8")
```

#### Bug 7 — Query [storage vectoriel] `embeddings=` invalide (`storage_writer.py`)  [historique]

Le SDK [storage vectoriel] v1.5+ a renommé `embeddings` → `query_embeddings` dans la méthode `Collection.query()`. Renvoyait `unexpected keyword argument 'embeddings'`.  [historique]

**Fix :** [ingestor/storage/storage_writer.py [historique]](ingestor/storage/storage_writer.py [historique]):
```python
# Before: kwargs["embeddings"] = [embedding]
# After:  kwargs["query_embeddings"] = [embedding]
```

#### Bug 8 — Paramètre `regions=` DDGS (`duckduckgo.py`)

ddgs v9.x a renommé `regions` → `region` (singulier).

**Fix :** [ingestor/search/duckduckgo.py](ingestor/search/duckduckgo.py):
```python
# Before: ddgs.text(query, regions=region, ...)
# After:  ddgs.text(query, region=region, ...)
```

#### Bug 9 — Paramètre `time=` supprimé DDGS v9.x (`duckduckgo.py`)

ddgs 9.x a retiré le paramètre `time` de l'API.

**Fix :** [ingestor/search/duckduckgo.py](ingestor/search/duckduckgo.py):
```python
# Before: ddgs.text(query, time=time_limit, ...)
# After:  ddgs.text(query, ...)  # time retiré
```

---

### Tests passés (chacun vérifié avec succès)

| Test | Commande | Résultat |
|------|----------|----------|
| Web search + crawl + storage | `--search "Project Zomboid survival guide tips"` | 3 résultats DDG, 2 pages crawlées, **2/2 chunks stockés** ✓ |
| Ingestion fichier texte | `--file docs/roadmap.md` | **16 chunks**, **1419 mots**, **16/16 stockés** ✓ |
| Liste collections | `--list-collections` | `pz_pdfs (16)`, `pz_web_pages (2)` ✓ |
| Cross-collection search | `--search-all "Zomboid Knowledge Engine"` | **7 résultats** triés par distance, de 2 collections ✓ |

---

### Dépendances système installées

- **FFmpeg** — `winget install ffmpeg` (Gyan.FFmpeg) + PATH persistant
- **Tesseract OCR** — `winget install Tesseract` (UB-Mannheim) + PATH persistant
- **Playwright Chromium** — `pip install playwright && playwright install chromium`

### Dépendances Python installées

- **ddgs v9.x** — successeur de `duckduckgo-search` (API breaking changes)
- **storage_vectoriel 1.5.9** — SDK officiel avec auto-détection API v2  [historique]
- **playwright** + browsers Chromium
- **easyocr**, **pdfplumber**, **python-docx**, **ebooklib**, **readability-lxml**, **httpx**, etc.

### 2026-07-02 - commit 328f113

**Changements :**
- Restructure: move ElChibros files to root, new src/governance and src/retrieval layout

### 2026-07-02 - commit f9acd93

**Changements :**
- fix: notion_client/api.py — correct API URL paths and parent type

### 2026-07-02 - commit 63ce682

**Changements :**
- feat: add notion_sync module — push agent/todo.md vers Notion

### 2026-07-02 - commit 1298527

**Changements :**
- feat: tests Phase 5+11 — golden set recall@5 (17) + storage_writer unitaires (39), 53/53 total

### 2026-07-02 - commit ba66597

**Changements :**
- feat: major restructuring — governance layer, sync automation, CLI expansion

### 2026-07-04 - commit 3c447fe

**Changements :**
- feat: mod scan (959 PZ workshop mods), steam API multiplayer detection, tests, ingestor modules

### 2026-07-04 - commit 5b27f6b

**Changements :**
- feat: incremental ingestion via SHA-256 hash index + 17 tests (Phase 6 item #2)

### 2026-07-05 - commit 9523c05

**Changements :**
- feat: golden set regression tester + release tagging (Phase 6 complet)

### 2026-07-05 - commit 2c08251

**Changements :**
- feat: script d'ingestion globale (Phase 3) — ingest.py

### 2026-07-05 - commit b37baee

**Changements :**
- fix(ingest/promote): metadata loss, filter mapping, [storage vectoriel] SDK migration  [historique]

### 2026-07-05 - commit c6fa309

**Changements :**
- feat(guard/backup): production write guard + pre-ingest backup avec rollback

### 2026-07-05 - commit ca1de16

**Changements :**
- fix(golden/set): aligner expected_ids aux données réellement ingérées (15 paires réalistes)

### 2026-07-05 - commit a4a7033

**Changements :**
- docs: update todo with architecture decision (SQLite/pgvector migration plan + guard/backup complete)

### 2026-07-05 - commit cdd4a29

**Changements :**
- chore: auto-sync agent docs (syntax, README, memories, todo, changelog)

### 2026-07-05 - commit 4ec4120

**Changements :**
- fix(notion_client): sécurité + robustesse + 67 tests unitaires

### 2026-07-05 - commit f213931

**Changements :**
- feat(sync): fuzzy matching local↔Notion (accents, apostrophes, tirets)

### 2026-07-06 - commit 0bd4ced

**Changements :**
- docs(doctor): add function/section annotations (5% -> ~8%). docs(audit): add project audit script covering parser/doc/ratios. fix(setup): Docker ETAPE 2 Install-WithWinget + FIX comment cleanup. fix(run-bot): replace dynamic variable ref with SetEnvironmentVariable

### 2026-07-06 - commit 62948e5

**Changements :**
- fix(ingestor): MIME detection fallback + CLI auto-accept (0 quarantine false-positives)

### 2026-07-06 - commit cc1dfce

**Changements :**
- chore: auto-sync Phase 8 web crawling complete + test cleanup (cloudscraper CF bypass, PZ wiki extraction verified)

### 2026-07-06 - commit a0e7ccb

**Changements :**
- feat: comprehensive ingestor + bot hardening (0 quarantine false-positives)

### 2026-07-06 - commit ee9525d

**Changements :**
- fix(ingestor): validate Docker service Phase 10 (build/run/search verified)

### 2026-07-06 - commit 060a6fc

**Changements :**
- feat(3.5-v1): SQLite storage layer with optional Ollama embedding — zero external service

### 2026-07-06 - commit b36cf9b

**Changements :**
- chore: sync version 0.4.0-alpha — release notes + version bump

### 2026-07-06 - commit e64bdb8

**Changements :**
- chore: complete version 0.4.0-alpha release (VERSION + CHANGELOG + README synced)

### 2026-07-06 - commit 6165630

**Changements :**
- chore: bump version 0.3.0-alpha to 0.4.0-alpha

### 2026-07-06 - commit 1a4cb47

**Changements :**
- chore: verify todo list checkboxes — Phase 1 Lua UI + Phase 4 MCP/watchdog + Phase 5 CI reports + Phase 12.8 steam upload

### 2026-07-07 - commit 8b7d8ee

**Changements :**
- chore(docs): correction fautes orthographe françaises — ~170 accents diacritiques (README, CHANGELOG, docs/, agent/, modgen/)

### 2026-07-07 - commit ae6317d

**Changements :**
- chore(tasks): mark completed checkboxes for S1/S2/S4 (validated against commits 15e529f + 41f250b)

### 2026-07-07 - commit 5eba12b

**Changements :**
- feat(agent_core): S3 LangGraph agent loop — complete implementation