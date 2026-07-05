# Changelog — Zomboid Knowledge Engine

Toutes les modifications notables, organisées par session de développement.

---

## [v0.3.0-alpha] — 2026-07-04

### Phase 6 : Filtrage B41/B42 natif dans le pipeline de requete

Isolement complet des donnees par version du jeu (B41 vs B42) via les filtres `$and` natifs de ChromaDB.

#### Fichiers modifies

| Fichier | Changement |
|---------|-----------|
| `src/governance/game_version.py` | +3 fonctions : `build_version_filter()`, `build_version_and()`, `build_version_not_filter()` |
| `src/retrieval/chroma_client.py` | `query()` accepte `game_version` — compose automatiquement $and avec filters existants |
| `bot/engine_client.py` | `search()`, `get_by_id()`, `query_staging()` propagent tous `game_version` via $and |
| `bot/pipeline.py` | `enrich_context()` et `process_message()` passent `game_version` au moteur |
| `bot/main.py` | Resolution de PZ_GAME_VERSION au demarrage + propagation dans le pipeline bot |
| `bot/config.py` | Ajout de `PZ_GAME_VERSION` dans Settings + resolution depuis .env |

#### Fichiers testes

| Fichier | Tests |
|---------|-------|
| `tests/test_game_version_filtering.py` | 24 tests (filter builders, tag_chunk, integration chroma_client/engine_client) |

### Moteur de generation de mods (`src/modgen/`) — nouvelle (Phase 12)

Generation de mods Project Zomboid valides a partir d'une description textuelle.

#### Fichiers cres

| Fichier | Role |
|---------|------|
| `src/modgen/__init__.py` | Module init + exports publics |
| `src/modgen/schema.py` | Dataclasses: ModSpec, GeneratedModManifest, ModFile, ModType |
| `src/modgen/generator.py` | Moteur principal (ModGenerator class) |
| `src/modgen/config.py` | Config du generateur (ModGenConfig + load_modgen_config) |
| `src/modgen/__main__.py` | CLI (`generate`, `list-templates`, `validate`) |
| `src/modgen/templates/*.j2` | 7 templates Jinja2 (mod.info, init.lua, descriptors, README) |
| `tests/test_modgen.py` | **32 tests unitaires** — schema, generation, validation, CLI, ZIP |

#### Fonctionnalites

- **CLI** : `python -m src.modgen generate "Une epée" --name "MySword"`
- **Bot Discord** : `/modgen "Ajouter une arme furtive"` → generation auto + retour fichiers
- **Templates PZ valides** : mod.info JSON, init.lua avec hooks, ZomboidModDescriptor.txt
- **Packaging** : `make mod-build MOD_NAME=MyMod` → ZIP dans `mods/`
- **Validation** : `python -m src.modgen validate /path/to/mod/`

#### Slash commands ajoutes

| Commande | Description |
|----------|-------------|
| `/modgen <description>` | Genere un mod PZ depuis une description textuelle |
| `/help` | Mis a jour avec /modgen dans la liste |

---

## [v0.2.0-alpha] — 2026-07-02

### Moteur d'ingestion multi-format (`ingestor/`) — nouveau

Création complète du moteur d'ingestion multi-modal : lecture de **tout format** (PDF, images, vidéo, audio, docx, epub) et du **web**, extraction en texte pur, embedding via Ollama, stockage ChromaDB.

#### Nouveaux fichiers créés

| Fichier | Rôle |
|---------|------|
| `ingestor/cli.py` | Entrée CLI (`--search`, `--file`, `--dir`, `--crawl`, `--url`, `--list-collections`, `--search-all`) |
| `ingestor/engine.py` | Router MIME → processeur, détection URL vs fichier |
| `ingestor/config.py` | Settings centralisés (ChromaDB, Ollama, OCR, web) |
| `ingestor/processors/base.py` | Interface `Processor`, dataclasses `Chunk`, `ExtractionRe
sult` |
| `ingestor/processors/text.py` | Processeur `.txt`, `.md`, `.csv`, `.json` |
| `ingestor/processors/pdf.py` | PDF → texte (pdfplumber) + OCR fallback (easyocr) |
| `ingestor/processors/image.py` | Images → OCR multi-langue + description vision API |
| `ingestor/processors/video.py` | Vidéo → ffmpeg frames + transcription audio Whisper |
| `ingestor/processors/audio.py` | Audio → transcription complète |
| `ingestor/processors/docx.py` | Word `.docx` extraction texte |
| `ingestor/processors/epub.py` | eBook `.epub` extraction contenu |
| `ingestor/processors/web.py` | Crawler Playwright BFS + WebProcessor (extraction HTML/readability) |
| `ingestor/search/duckduckgo.py` | Moteur recherche DuckDuckGo (ddgs v9.x, no API key) |
| `ingestor/storage/chroma_writer.py` | Writer ChromaDB SDK + Ollama embedding + cross-collection search |
| `ingestor/quarantine_manager.py` | Dédup SHA-256, circuit breaker, monitoring disque |
| `ingestor/requirements.txt` | Dépendances Python du moteur d'ingestion |
| `ingestor/README.md` | Documentation du module |

#### Collections ChromaDB ajoutées

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
await write_chunks_to_chroma(chunks=all_chunks, ...)
```

#### Bug 4 — `Chunk.__init__()` manquait `start_offset` (`cli.py`)

Le Chunk créé manuellement omettait le champ `start_offset: int` requis.

**Fix :** [ingestor/cli.py](ingestor/cli.py):
```python
BaseChunk(text=r.body, index=i, start_offset=0)  # + start_offset obligatoire
```

#### Bug 5 — Upsert ChromaDB `[[...]]` imbriqué (`chroma_writer.py`)

Les listes de documents et metadatas étaient enveloppées dans une paire de crochets superflue `[docs_w]`, rendant les dimensions incompatibles.

**Fix :** [ingestor/storage/chroma_writer.py](ingestor/storage/chroma_writer.py):
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

#### Bug 7 — Query ChromaDB `embeddings=` invalide (`chroma_writer.py`)

Le SDK ChromaDB v1.5+ a renommé `embeddings` → `query_embeddings` dans la méthode `Collection.query()`. Renvoyait `unexpected keyword argument 'embeddings'`.

**Fix :** [ingestor/storage/chroma_writer.py](ingestor/storage/chroma_writer.py):
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
- **chromadb 1.5.9** — SDK officiel avec auto-détection API v2
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
- feat: tests Phase 5+11 — golden set recall@5 (17) + chroma_writer unitaires (39), 53/53 total

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
- fix(ingest/promote): metadata loss, filter mapping, ChromaDB SDK migration