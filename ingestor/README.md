# Zomboid Knowledge Engine — Moteur d'Ingestion Multi-Format

Le moteur d'ingestion lit **tout format de fichier** et le transforme en chunks vectorisés pour StorageBackend (SQLite vectoriel). Il peut aussi **naviguer sur le web**, **scanner Steam/Workshop**, et **extraire le contenu de mods PZ**.

## Table des matières

- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Processors](#processors)
- [Flux de données](#flux-de-données)
- [Steam & Workshop](#steam--workshop)
- [Recherche Brave (fallback)](#recherche-brave-fallback)
- [Sécurité](#sécurité)
- [Dépannage](#dépannage)

---

## Quickstart

### 1. Dépendances système

```powershell
# OCR + vidéo
winget install Tesseract.Unofficial ffmpeg

# Navigateur headless (web crawling)
pip install playwright
playwright install chromium
```

### 2. Dépendances Python

```powershell
cd ingestor
pip install -r requirements.txt
```

### 3. Environnement

Utiliser `.env.unified` à la racine du projet :

```powershell
# Il est déjà fourni — remplir les valeurs nécessaires dans .env.unified
STORAGE_BACKEND=sqlite
STORAGE_PG_HOST=localhost
STORAGE_PG_PORT=5432
STORAGE_PG_DB=zomboid_storage
STORAGE_PG_USER=postgres
STORAGE_PG_PASS=
OLLAMA_BASE_URL=http://localhost:11434
EMBEDDING_MODEL=nomic-embed-text
```

> **Obligatoire** : `STORAGE_BACKEND`, `OLLAMA_BASE_URL`
> **Optionnel** : `BRAVE_API_KEY` (Brave Search fallback), `CLAUDE_API_KEY` (vision API pour images)

### 4. Premier test

```powershell
# Lister les collections StorageBackend (SQLite vectoriel)
python -m ingestor.cli --list-collections

# Recherche web simple
python -m ingestor.cli --search "Project Zomboid farming guide"

# Ingestion d'un fichier
python -m ingestor.cli --file "C:/docs/manual.pdf"
```

---

## Architecture

```
ingestor/
├── cli.py                    # Entrée CLI (--search, --file, --dir, --crawl, --steam-scan, ...)
├── engine.py                 # Router MIME → processeur + IngestionEngine orchestrateur
├── config.py                 # Settings (StorageBackend (SQLite vectoriel), Ollama, crawling, OCR, Steam)
├── processors/
│   ├── base.py               # Interface Processor + Chunk + ExtractionResult
│   ├── text.py               # .txt .md .csv .json — stdlib only
│   ├── pdf.py                # PDF → texte (pdfplumber) + OCR (easyocr fallback)
│   ├── image.py              # Images → OCR multi-langue + Claude vision optionnel
│   ├── video.py              # Vidéo → frames OCR + transcription audio
│   ├── audio.py              # Audio → transcription complète (whisper/ollama)
│   ├── docx.py               # Word .docx → texte
│   ├── epub.py               # eBooks .epub → texte
│   ├── web.py                # Crawler Playwright BFS + extraction contenu propre
│   └── pbo.py                # Archives .pbo (mods ArmA/PZ Workshop)
├── search/
│   ├── duckduckgo.py         # Moteur de recherche principal (no API key)
│   └── brave.py              # Fallback Brave Search API (2000 req/mois gratuit)
├── steam/
│   ├── path_discovery.py     # Découverte auto Steam/PZ via registry Windows
│   ├── steamcmd_client.py    # Client SteamCMD (download game, install mods)
│   ├── workshop_scanner.py   # Scanner les mods installés dans le Workshop
│   ├── mod_ingester.py       # Ingestion automatisée de mods (.pbo, lua, cfg)
│   ├── library_folders.py    # Parsing libraryfolders.vdf
│   └── qr_auth.py            # Authentification QR SteamCMD
├── storage/
│   └── storage_writer.py     # Écriture StorageBackend (SQLite vectoriel) + embedding Ollama + cross-search
├── quarantine_manager.py     # Dédup SHA-256, circuit breaker, monitoring disque
├── requirements.txt          # Dépendances Python
└── Dockerfile                # Containerisation (optionnel)
```

---

## CLI Reference

### Web & Recherche

| Commande | Description |
|----------|-------------|
| `--search "query"` | Recherche web + crawl automatique des résultats (DDG → Brave fallback) |
| `--url <url>` | Ingestion d'une seule URL (extraction du contenu propre) |
| `--crawl <seed_url>` | Crawl BFS d'un site (suit les liens internes, depth limité) |

### Fichiers & Dossiers

| Commande | Description |
|----------|-----------|
| `--file <path>` | Ingestion d'un fichier unique (auto-détection du format) |
| `--dir <path>` | Ingestion récursive de tout un dossier |

### Base de connaissances

| Commande | Description |
|----------|-----------|
| `--search-all "query"` | Recherche vectorielle sur **toutes** les collections StorageBackend (SQLite vectoriel) |
| `--list-collections` | Liste les collections disponibles + nombre de documents |

### Steam & Workshop

| Commande | Description |
|----------|-----------|
| `--steam-scan` | Détecte l'installation Steam et Project Zomboid (registry + libraryfolders) |
| `--steamcmd-download-game [DIR]` | Télécharge PZ via SteamCMD (anonyme) |
| `--steamcmd-install-mod <ID>` | Installe un mod workshop via SteamCMD |
| `--workshop-scan` | Scanne les mods installés dans le Steam Workshop |
| `--mod-ingest <DIR>` | Ingestion StorageBackend (SQLite vectoriel) de tous les mods d'un dossier (.pbo, lua, cfg) |

### Options globales

| Option | Par défaut | Description |
|--------|-----------|-------------|
| `--max-depth <n>` | 5 | Profondeur max de crawl BFS |
| `--max-pages <n>` | 20 | Pages max par search/crawl |
| `--engine auto\|ddg\|brave` | auto | Moteur de recherche (DDG prioritaire, Brave fallback) |
| `-v, --verbose` | false | Mode verbeux (logs DEBUG) |

### Exemples complets

```powershell
# 1. Chercher + crawler le PZ Wiki
python -m ingestor.cli --search "Project Zomboid carpentry guide"

# 2. Crawler un site de mods (profondeur 3, max 10 pages)
python -m ingestor.cli --crawl "https://pzmods.net" --max-depth 3 --max-pages 10

# 3. Ingestion PDF d'un manuel PZ
python -m ingestor.cli --file "C:/docs/pz_cooking.pdf"

# 4. Scanner les mods installés + ingestion dans StorageBackend (SQLite vectoriel)
python -m ingestor.cli --workshop-scan
python -m ingestor.cli --mod-ingest "C:/Steam/steamapps/workshop/content/1042170"

# 5. Recherche cross-collection
python -m ingestor.cli --search-all "comment construire un abri en bois"

# 6. Liste des collections
python -m ingestor.cli --list-collections
```

---

## Configuration

Toutes les variables se chargent depuis `.env.unified` à la racine du projet.

### Obligatoires

| Variable | Par défaut | Description |
|----------|-----------|-------------|
| `STORAGE_BACKEND` | `sqlite` | Type de stockage vectoriel (sqlite, postgres) |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | URL du serveur Ollama |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Modèle d'embedding utilisé |

### Optionnelles

| Variable | Par défaut | Description |
|----------|-----------|-------------|
| `CLAUDE_API_KEY` | — | Clé Anthropic Claude pour descriptions vision (images) |
| `CLAUDE_BASE_URL` | `https://api.anthropic.com/v1/messages` | Endpoint Claude API |
| `BRAVE_API_KEY` | — | Clé Brave Search pour fallback web (2000 req/mois gratuit) |
| `DATA_ROOT` | `data/` | Racine des dossiers staging/production |
| `CHUNK_SIZE` | 512 | Taille des chunks texte |
| `CHUNK_OVERLAP` | 64 | Chevauchement entre chunks |
| `MAX_WEB_DEPTH` | 5 | Profondeur max crawl |
| `MAX_WEB_PAGES` | 50 | Pages max par seed URL |
| `WEB_RATE_LIMIT` | 30 | Requêtes/min par domaine |
| `OCR_LANG` | `fra+eng` | Langues OCR (separées par +) |

### Steam / Workshop

| Variable | Par défaut | Description |
|----------|-----------|-------------|
| `STEAM_INSTALL_PATH` | Auto-détecté via registry Windows | Chemin Steam |
| `GAME_PATH` | Auto-détecté vers PZ install | Chemin Project Zomboid |
| `WORKSHOP_CONTENT_ROOT` | Auto-détecté | Dossier workshop content/1042170 |
| `STEAM_USER` | — | Identifiant SteamCMD (pour downloads) |
| `STEAM_PASS` | — | Mot de passe SteamCMD |
| `DEFAULT_STEAMCMD_DIR` | `steamcmd/` | Chemin relatif du client SteamCMD |

---

## Processors

Chaque processor implémente l'interface `Processor.extract()` → `ExtractionResult` (chunks + metadata).

| Format | Processeur | Dépendances Python | Notes |
|--------|-----------|-------------------|-------|
| `.txt`, `.md`, `.csv`, `.json` | `text.py` | Aucune (stdlib) | Extraction directe |
| `.pdf` | `pdf.py` | `pdfplumber` + `easyocr` | OCR fallback sur scans |
| `.png`, `.jpg`, `.webp`, ... | `image.py` | `easyocr` (+ Claude vision optionnel) | Multi-langue |
| `.mp4`, `.mkv`, ... | `video.py` | `ffmpeg` (système), OCR frames | Frames + audio transcription |
| `.mp3`, `.wav`, ... | `audio.py` | whisper (ollama ou openai-whisper) | Transcription complète |
| `.docx` | `docx.py` | `python-docx` | Extraction paragraphes/tableaux |
| `.epub` | `epub.py` | `ebooklib` | Chapitres → chunks |
| `.pbo` | `pbo.py` | stdlib + `lzma` | Archives mods PZ/ArmA |
| Web URLs | `web.py` | `playwright`, `readability` | Crawler BFS headless |

---

## Flux de données

```
source (fichier / URL / Steam Workshop)
    │
    ▼
engine.detect_type() → processeur approprié
    │
    ▼
processor.extract() → list[Chunk] + ExtractionResult
    ├── chunk.text       : contenu texte pur
    ├── chunk.index      : position dans le document
    ├── metadata         : source, type, hash, extension, etc.
    │
    ▼
storage_writer.StorageWriter.write_chunks_to_storage()
    ├── embedding via Ollama (nomic-embed-text)
    └── stockage dans collection StorageBackend (SQLite vectoriel)
        pz_items       — Entités jeu (objets, ressources)
        pz_recipes     — Recettes de craft
        pz_mechanics   — Mécaniques de jeu
        pz_lua_api     — API Lua reference
        pz_java_api    — API Java reference
        pz_web_pages   — Pages web crawlées
        pz_pdfs        — Documents PDF
        pz_images      — Images OCRées
        pz_videos      — Vidéos transcrites
        pz_audios      — Audio transcrits
        pz_mods        — Metadata des mods (nom, author, desc)
        pz_workshop_items — Registry Workshop (ID, nom, dates)
        pz_mod_lua_scripts  — Scripts Lua extraits des mods
        pz_mod_configs      — Config files (.bin, .cfg, .lua)
```

---

## Steam & Workshop

L'ingestor détecte automatiquement l'installation PZ via le registry Windows et les `libraryfolders.vdf`.

### Workflow type

```powershell
# 1. Scanner la configuration Steam
python -m ingestor.cli --steam-scan

# 2. Scanner les mods installés (affiche un résumé)
python -m ingestor.cli --workshop-scan

# 3. Ingest les mods dans StorageBackend (SQLite vectoriel) pour la recherche vectorielle
python -m ingestor.cli --mod-ingest "C:/Steam/steamapps/workshop/content/1042170"
```

### Pipeline mod ingestion

Chaque mod est traité par `mod_ingester.py` :
1. Parse `ZomboidModDescriptor.txt` → metadata (nom, description, author, fichiers)
2. Extrait chaque `.lua` / `.cfg` / `.txt` du mod → chunks
3. Extrait le contenu des `.pbo` si présents (architecture ArmA/Steam)
4. Injecte dans StorageBackend (SQLite vectoriel) (`pz_mod_lua_scripts` + `pz_mod_configs`)

---

## Recherche Brave (fallback)

Brave Search est utilisé automatiquement quand DuckDuckGo retourne 0 résultats ou échoue.

### Activation

```powershell
# Option 1: Variable d'environnement
$env:BRAVE_API_KEY = "BSA-xxxxxxxxxxxxxxxxxxxx"

# Option 2: Dans `.env.unified` à la racine
BRAVE_API_KEY=BSA-xxxxxxxxxxxxxxxxxxxx
```

Le plan gratuit donne **2000 requêtes/mois**. La fréquence de fallback est :

```
--search "query"
  → DuckDuckGo retourne des résultats ? → OK
  → DuckDuckGo échoue ou 0 résultat ?
      → Brave Search (si BRAVE_API_KEY configurée)
      → Avertissement "Aucun résultat trouvé" (sinon)
```

Force le moteur explicitement :

```powershell
python -m ingestor.cli --search "query" --engine brave
```

---

## Sécurité

| Mecanisme | Details |
|-----------|---------|
| **robots.txt** | Respecté systématiquement par le crawler web (via `urllib.robotparser`) |
| **Rate limiting** | 30 requêtes/min max par domaine (configurable via `WEB_RATE_LIMIT`) |
| **Profondeur limitée** | depth=5 par défaut pour éviter les loops infinis |
| **Circuit breaker** | Stop si >3 échecs consécutifs dans une fenêtre de 60s |
| **Monitoring disque** | Vérifie 2 GB+ libre avant chaque ingestion (configurable via `DISK_SPACE_MIN_GB`) |
| **Quarantine** | Fichiers en erreur isolés avec SHA-256 dedup + rapport d'erreur |

---

## Dépannage

### Ollama inaccessible depuis Docker
Utilise `http://host.docker.internal:11434` au lieu de `localhost:11434`.
Depuis le host Windows : `http://host.docker.internal:11434` ou `http://172.17.0.1:11434`.

### Ollama inaccessible
Vérifie que le service est running :
```powershell
curl http://localhost:11434/api/tags
```
Si non, demarrer : `ollama serve` ou redemarrer le service Windows.

### Brave Search retourne toujours vide
- Verifie que `BRAVE_API_KEY` est bien configurée (`print(os.getenv("BRAVE_API_KEY"))`)
- Le plan gratuit = 2000 req/mois, vérifie le quota sur [brave.com/search/api](https://brave.com/search/api/)

### `playwright install chromium` échoue
Depuis Windows behind proxy :
```powershell
$env:HTTPS_PROXY = "http://proxy:port"
playwright install chromium --with-deps
```

### `.pbo` extraction fails (LZMA)
Les `.pbo` signés utilisent une signature au début du fichier qui doit être ignorée. Le processeur `pbo.py` detecte et saute automatiquement la signature (header + data length). Si le .pbo est compressé avec autre chose que LZMA, l'extraction peut echouer.

### Collections StorageBackend (SQLite vectoriel) vides après ingestion
1. Verifie que StorageBackend (SQLite vectoriel) est accessible : `python -m ingestor.cli --list-collections`
2. Les chunks sont-ils generés ? Regarde les logs (`--verbose`)
3. La confirmation StorageBackend (SQLite vectoriel) a-t-elle été faite (prompt [y/N]) ?

---

## Intégration avec le Bot Discord

L'ingestor est utilisé en arrière-plan par le bot `bot/` pour :

1. **Recherche vectorielle** — Le bot interroge les collections via `src.retrieval` + `StorageBackend` (SQLite/PostgreSQL)
2. **Ingestion web automatique** — `/search "query"` dans Discord déclenche la même pipeline que `--search`
3. **Modding assisté** — Les mods ingérés via `--mod-ingest` alimentent la base de connaissances du bot

L'architecture est decouplee : le bot et l'ingestor partagent uniquement `src/retrieval/` + `src/governance/logger.py`.
