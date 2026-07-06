# Projet Zomboid_Architect — Résumé Complet

> **Créateur** : ElChibros
> **Version courante** : alpha (voir VERSION)
> **Objectif** : Moteur de connaissance local sur Project Zomboid, sans hallucination, exposé via MCP + bot Discord.

---

## 1. Quoi ?

**Zomboid Knowledge Engine** = un moteur RAG (Retrieval-Augmented Generation) qui alimente un agent IA avec des connaissances précises, vérifiables, sur Project Zomboid. Deux usages principaux :
1. **Stratégie de survie** — conseils calibrés sur les mécaniques du jeu (calories, panique, bruit, moodles, etc.)
2. **Développement de mods** — documentation Lua/Java, génération de templates de mod

Le projet repose sur des principes stricts : zéro hallucination numérique, déterminisme quand possible, séparation stricte `staging` / `production`, et quarantaine automatique des données corrompues.

---

## 2. Architecture globale (3 composants principaux)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   ingestor   │────▶│  ChromaDB    │◀────│    bot      │
│  multi-format│     │  (vector DB) │     │  (Discord)  │
└─────────────┘     └──────────────┘     └─────────────┘
        │                                             │
        ▼                                             ▼
   data/raw/                               réponses LLM formatées
   data/staging/                           slash commands + DM
   data/quarantine/
```

### A. `ingestor/` — Moteur d'ingestion multi-format
**Rôle** : Détecter le type de fichier/URL, extraire son contenu, créer des chunks vectorisés et les envoyer à ChromaDB.

**Entrées supportées** : PDF, images (OCR), audio (transcription), vidéo (transcription), documents (.docx, .epub), texte brut, HTML (web crawling), archives PBO (mods), scripts Lua, configs de jeu (.lua, .tiles, .lotpack, etc.)

**Fichier clé** : [`ingestor/engine.py`](../ingestor/engine.py) — `IngestionEngine` avec router MIME → processeur. Mécanisme incrémental par SHA-256 (fichier `data/quarantine/.seen_hashes`).

**Processeurs** : [`ingestor/processors/`](../ingestor/processors/) — chaque sous-module gère un format :
- `text.py` → texte brut, scripts Lua, configs
- `pdf.py` → extraction PDF + OCR
- `image.py` → OCR d'images
- `audio.py` / `video.py` → transcription
- `docx.py` → documents Word
- `epub.py` → livres électroniques
- `web.py` → crawling web (avec rate limiting)
- `pbo.py` → extraction archives PBO (mods Workshop)

**Config** : [`ingestor/config.py`](../ingestor/config.py) — `IngestorConfig` dataclass, chargé depuis `.env.unified`. Variables env principales : `CHROMA_HOST`, `OLLAMA_BASE_URL`, `EMBEDDING_MODEL`, `DATA_ROOT`, `CLAUDE_API_KEY`, etc.

**CLI** : [`ingestor/cli.py`](../ingestor/cli.py) — point d'entrée en ligne de commande (`python -m ingestor.cli`).

### B. `bot/` — Bot Discord
**Rôle** : Interface conversationnelle du moteur. Reçoit les messages → cherche dans ChromaDB → construit un prompt LLM → répond via Discord.

**Fichier clé** : [`bot/main.py`](../bot/main.py) — point d'entrée (`python -m bot.main`). Slash commands + DM automatique.

**Slash commands disponibles** :
| Commande | Rôle |
|----------|------|
| `/stats <item>` | Lookup déterministe par ID (ex: `Base.Axe`) → stats exactes |
| `/survie <scenario>` | Conseil de survie hardcore basé sur les données du jeu |
| `/recipe <ingredient>` | Recettes d'artisanat |
| `/moddoc <api>` | Documentation modding Lua/Java |
| `/search <query>` | Recherche sémantique libre |
| `/modgen <desc>` | Génère un mod Zomboid depuis une description |
| `/workspace` | Rapport d'état du projet envoyé dans le canal workspace |

**Pipeline** : [`bot/pipeline.py`](../bot/pipeline.py) — chaîne complète : `message → intent detection → ChromaDB search → prompt building → LLM call → réponse`.

**Llm adapter** : [`bot/llm_adapter.py`](../bot/llm_adapter.py) — providers Ollama (priorité) + Claude API (fallback).
**Engine client** : [`bot/engine_client.py`](../bot/engine_client.py) — wrapper ChromaDB pour le bot.

### C. `src/` — Core du moteur
**Sous-modules** :
- `src/governance/` — logiques de contrôle : logger, worker, lock, game_version filter, production_guard
- `src/retrieval/` — client ChromaDB (`chroma_client.py`)
- `src/modgen/` — générateur de mods Zomboid (ModSpec, ModGenerator)

**governance/logger.py** : Logger centralisé avec logs JSON horodatés. Utilisé partout dans le code.

---

## 3. Base de données vectorielle (ChromaDB)

**5 collections principales** :
| Collection | Contenu |
|------------|---------|
| `pz_items` | Objets, armes, vêtements, nourriture |
| `pz_recipes` | Recettes d'artisanat |
| `pz_mechanics` | Fiches mécaniques (panique, calories, bruit) |
| `pz_lua_api` | Doc de modding Lua, UI diégétiques |
| `pz_java_api` | Signatures de l'API moteur |

**Collections additionnelles** (ingestor multi-format) : `pz_web_pages`, `pz_pdfs`, `pz_images`, `pz_videos`, `pz_audios`, `pz_mods`, `pz_workshop_items`, `pz_mod_lua_scripts`, `pz_mod_configs`.

---

## 4. Flux de données complet

```
1. INGESTION
   source (fichier/URL) → IngestionEngine.detect_type() → processeur spécialisé
   → chunks + embedding (Ollama nomic-embed-text) → ChromaDB

2. RECHERCHE (via bot ou MCP)
   message utilisateur → detect_intent() → enrich_context() [ChromaDB search]
   → build_prompt() [JSON brut + prose] → LLM.complete() → réponse formatée

3. PROMOTION (staging → production)
   raw/ → staging/ → golden set validation → promotion → production/
   (refusé si recall@5 < seuil, échoué → quarantine/)

4. BACKUP
   data/production/chromadb/ → backups/ avec rotation
```

---

## 5. Configuration & Environnement

### Fichiers de config
| Fichier | Rôle |
|---------|------|
| `.env.unified` | Config centralisée (CHROMA_HOST, OLLAMA_BASE_URL, EMBEDDING_MODEL, etc.) |
| `bot/config.py` | `load_settings()` pour le bot Discord |
| `ingestor/config.py` | `load_config()` pour l'ingestor |

### Services Docker (`docker-compose.yml`)
| Service | Image / Build | Port | Rôle |
|---------|---------------|------|------|
| `bot` | `./bot/` | — | Bot Discord (restart: unless-stopped) |
| `ollama` | `ollama/ollama:latest` | 11434 | LLM local + embeddings |
| `chromadb` | `chromadb/chroma:latest` | 8000 | Base vectorielle |
| `ingestor` | `./ingestor/` | — | Ingestion (launch-on-demand, memory: 4G) |

### Démarrage
```bash
# Tous les services
docker compose up -d

# Uniquement le bot + chromadb (ollama sur l'hôte Windows)
docker compose up -d bot chromadb

# Ingestion manuelle
docker compose run --rm ingestor python -m ingestor.cli
```

### Variables d'environnement critiques
| Variable | Défaut | Rôle |
|----------|--------|------|
| `DISCORD_TOKEN` | — | Token du bot Discord (obligatoire) |
| `CHROMA_HOST` | `http://host.docker.internal:8000` | URL ChromaDB |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | URL Ollama |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Modèle d'embedding |
| `CLAUDE_API_KEY` | — | Clé Claude (fallback, optionnel) |
| `DATA_ROOT` | `data/` | Racine des données |
| `STEAM_USER/PASS` | — | Auth SteamCMD pour mod downloads |

---

## 6. Structure du répertoire de données

```
data/
├── raw/              # Extractions brutes (jamais modifiées) — source of truth
├── staging/          # Zone de travail temporaire
│   └── chromadb/     # ChromaDB en test
├── production/       # Données validées (intouchables sans process)
│   └── chromadb/     # ChromaDB servi à l'agent
├── quarantine/       # Entités rejetées + .seen_hashes (incrémental)
└── backups/          # Snapshots horodatés + rotation
```

---

## 7. Architecture technique — points clés

### Dual-Field (obligatoire pour chaque entité)
Chaque chunk dans ChromaDB a **deux champs** :
- `prose` : description en langage naturel → vectorisé pour recherche sémantique
- `metadata_` : métadonnées JSON brutes → restituées telles quelles, jamais reformulées

Ceci garantit qu'un agent IA puisse fournir à la fois une réponse lisible ET des valeurs exactes vérifiables.

### Détection d'intention (bot/pipeline.py)
Le bot détecte automatiquement le type de commande dans les messages DM :
- Patterns explicites : `/stats`, `/survie`, etc.
- Regex implicites : `Base.XXX` pour items, mots-clés "recette"/"craft" pour recipes, "lua api"/"modding" pour moddoc
- Défaut : recherche libre

### Router MIME (ingestor/engine.py)
Mapping extension → MIME → processeur. Fallback : inspection du contenu (`_peek_text` → premiers 1024 octets). Supporte ~60+ extensions de fichiers.

### Ingestion incrémentale
Chaque fichier ingéré a son SHA-256 hashé dans `data/quarantine/.seen_hashes`. Au prochain cycle, les fichiers inchangés sont automatiquement ignorés → performances optimisées.

---

## 8. Tests & Golden Set

**Emplacement** : [`tests/`](../tests/)
- `test_golden_set.py` — Q/R de référence pour validation des réponses (gardien du temple)
- `test_chroma_writer.py` — écriture ChromaDB
- `test_ingest.py`, `test_ingestor_processors.py` — ingestion et processeurs
- `test_modgen.py` + `test_modgen_integration.py` — générateur de mods
- `test_cli.py` — CLI ingestor
- `test_steamcmd_client.py` — client SteamCMD
- `test_workshop_scanner.py` — scan Workshop Steam
- `test_game_version_filtering.py` — filtrage B41/B42
- `test_incremental_ingest.py` — ingestion incrémentale

**Règle d'or** : Rien ne passe de `staging/` → `production/` sans passer le golden set.

---

## 9. Notion Sync

Le projet synchronise `agent/todo.md` avec une base Notion via [`notion_client/`](../notion_client/).
- CLI : `python -m notion_client --push`
- Le pre-commit hook auto-synchronise quand un commit touche `todo.md`
- Lancement manuel du sync : `.\agent\maintenance\sync_agent.ps1 "description"`

---

## 10. Scripts & Outils spéciaux

| Script | Rôle |
|--------|------|
| `restore.py` | Restauration depuis backup |
| `notion_sync.py` | Sync Notion (ancienne interface) |
| `database/extract_pz.py` | Extraction des données PZ brutes |
| `database/extract_mods.py` | Extraction des mods |
| `downloads/Steam-QR-Code-Login/` | Auth Steam par QR code |

---

## 11. Règles opérationnelles critiques

1. **Jamais éditer `production/` à la main** — toujours passer par le pipeline de promotion
2. **Chaque modification de `todo.md` doit être sync vers Notion** (pre-commit hook auto)
3. **Lancer `sync_agent.ps1` avant chaque session importante** — met à jour syntax.md, CHANGELOG, etc.
4. **Les secrets sont jamais commités ni loggués** — toujours masquer (`***`)
5. **Le versioning est double** : SemVer (moteur) + B41/B42 (données du jeu)
6. **`source de vérité mathématique est humaine`** — le bytecode décompilé n'est JAMAIS une source fiable pour les formules

---

## 12. Cycles de version

| Stage | Critère |
|-------|---------|
| `-alpha` | Pipeline de bout en bout fonctionnel |
| `-beta` | 5 collections peuplées + golden set passe |
| `-rc` | Zéro bug bloquant sur 1 semaine |
| `release` | Golden set 100% + doc à jour |

---

## 13. Pour agir rapidement sur le code (aide-mémoire)

| Besoin | Fichiers à lire en premier |
|--------|---------------------------|
| Comprendre un flux de réponse | `bot/pipeline.py` → `bot/engine_client.py` → `src/retrieval/chroma_client.py` |
| Ajouter un processeur d'ingestion | `ingestor/processors/base.py` (base) + ajouter dans `ingestor/engine.py` |
| Modifier le bot Discord | `bot/main.py` + `bot/pipeline.py` |
| Changer les collections ChromaDB | `src/retrieval/chroma_client.py` + `ingestor/config.py` |
| Comprendre la logique de gouvernance | `src/governance/` (logger, worker, lock, production_guard) |
| Lancer l'ingestion | `ingestor/cli.py` ou `docker compose run --rm ingestor` |
| Générer un mod | `src/modgen/generator.py` + `bot/main.py:cmd_modgen` |
| Vérifier les golden tests | `tests/test_golden_set.py` |

---

*Dernière mise à jour : 2026-07-06*
