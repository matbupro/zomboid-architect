# Changelog — Zomboid Knowledge Engine

Toutes les modifications notables, organisées par session de développement.

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