# Zomboid Knowledge Engine — Moteur d'Ingestion Multi-Format

Le moteur d'ingestion lit **tout format de fichier** et le transforme en chunks vectorisés pour ChromaDB. Il peut aussi **naviguer sur le web** pour collecter du contenu automatiquement.

## Formats supportés

| Format | Processeur | Dépendance python |
|--------|-----------|-------------------|
| `.txt`, `.md`, `.csv`, `.json` | `text.py` | Aucune (stdlib) |
| `.docx` | `docx.py` | `python-docx` |
| `.epub` | `epub.py` | `ebooklib` |
| `.pdf` | `pdf.py` | `pdfplumber` (+ `easyocr` pour scans) |
| `.png`, `.jpg`, etc. | `image.py` | `easyocr` (+ Claude vision optionnel) |
| `.mp4`, `.mkv`, etc. | `video.py` | `ffmpeg` (system), OCR frames, audio transcription |
| `.mp3`, `.wav`, etc. | `audio.py` | whisper (`ollama` ou `openai-whisper`) |
| Web URLs | `web.py` | `playwright` (+ `duckduckgo-search`) |

## Installation rapide (Windows)

### 1. Dépendances système
```powershell
winget install ffmpeg Tesseract
pip install playwright
playwright install chromium
```

### 2. Dépendances Python
```powershell
cd ingestor
pip install -r requirements.txt
```

### 3. (Optionnel) Docker
```powershell
docker compose build ingestor
```

## Utilisation CLI

```powershell
# Web search + crawl automatique
python -m ingestor.cli --search "Project Zomboid wiki guide"

# Crawl d'un site complet (depth=5 par défaut)
python -m ingestor.cli --crawl "https://pzwiki.net"

# Ingestion fichier unique (auto-détection du format)
python -m ingestor.cli --file "C:/docs/pz_manual.pdf"

# Ingestion dossier complet
python -m ingestor.cli --dir "C:/my_docs/"

# Recherche dans TOUTES les collections ChromaDB
python -m ingestor.cli --search-all "comment survivre en B42"

# Lister les collections disponibles
python -m ingestor.cli --list-collections

# Verbeux
python -m ingestor.cli --search "query" -v
```

## Architecture

```
ingestor/
├── cli.py              # Entrée CLI (--search, --file, --dir, --crawl)
├── engine.py           # Router : détecte type MIME → délègue au processeur
├── config.py           # Settings (ChromaDB, Ollama, crawling, OCR)
├── processors/
│   ├── base.py         # Interface commune Processor + Chunking
│   ├── text.py         # Textes bruts
│   ├── pdf.py          # PDF → texte direct ou OCR
│   ├── image.py        # Images → OCR + description vision API
│   ├── video.py        # Vidéo → frames OCR + audio transcription
│   ├── audio.py        # Audio → transcription complète
│   ├── docx.py         # Word documents
│   ├── epub.py         # eBooks
│   └── web.py          # Crawler Playwright BFS + extraction web
├── search/
│   ├── duckduckgo.py   # Moteur recherche DuckDuckGo (no API key)
│   └── brave.py        # Fallback Brave Search
├── storage/
│   └── chroma_writer.py  # Écriture ChromaDB + embedding Ollama + cross-search
├── quarantine_manager.py  # Dédup SHA-256, circuit breaker, espace disque
└── requirements.txt    # Dépendances Python
```

## Flux de données

```
source (fichier/URL)
    │
    ▼
engine.detect_type() → processeur approprié
    │
    ▼
processor.extract() → chunks textuels + metadata
    │
    ▼
chroma_writer.write_chunks_to_chroma()
    ├── embedding via Ollama (nomic-embed-text)
    └── stockage dans collection ChromaDB
```

## Sécurité

- **robots.txt** : respecté systématiquement par le crawler web
- **Rate limiting** : 30 requêtes/min max par domaine
- **Profondeur limitée** : depth=5 par défaut pour éviter les loops infinis
- **Circuit breaker** : arrêt automatique si >3 échecs consécutifs dans une fenêtre de 60s
- **Monitoring disque** : vérifie 2GB+ libre avant chaque ingestion
