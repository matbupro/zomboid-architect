# Architecture du Projet

## RAG Stack

| Composant | Choix | Pourquoi |
|-----------|-------|----------|
| Embedding | bge-m3 | Bilingue FR/EN, adapté au corpus mixte |
| Reranker | cross-encoder | Précision finale après rappel vectoriel |
| Base DB | SQLite + StorageBackend | Locale, zéro dépendance externe, vectoriel optionnel |

## 5 Collections dédiées (pas de pollution inter-domaine)

| Collection | Contenu | Type de recherche |
|------------|---------|-------------------|
| `pz_items` | Objets, armes, vêtements, nourriture | Vectoriel + lookup ID |
| `pz_recipes` | Recettes d'artisanat | Vectoriel + filtre version |
| `pz_mechanics` | Fiches mécaniques (panique, calories, bruit) | Vectoriel |
| `pz_lua_api` | Doc de modding Lua, UI diégétiques | Vectoriel |
| `pz_java_api` | Signatures de l'API moteur | Vectoriel + lookup |

## Dual-Field (obligatoire pour chaque entité)

- **Champ prose** : description en langage naturel → vectorisé pour recherche sémantique
- **Champ JSON brut** : métadonnées exactes, restituées telles quelles, jamais reformulées

## Sources de Données

| Source | Chemin | Contenu | Usage RAG |
|--------|--------|---------|-----------|
| Scripts | `/scripts/*.txt` | Définitions brutes (objets, vêtements, véhicules, recettes) | Ingestion massive automatisée |
| Lua | `/lua/` | UI, logique de jeu, hooks événements | Référence modding |
| Java décompilé | `zombie.jar` | API moteur (ItemContainer, IsoPlayer) | Signatures uniquement |

## Flux de données

```
Extraction       Validation          Promotion
┌────────┐      ┌──────────┐        ┌────────────┐
│  raw/  │─────▶│ staging/  │──────▶│ production/ │
└────────┘      └──────────┘        └────────────┘
                     │                    ▲
                     ▼                    │
               golden set ──── pass ──────┘
                     │
                   fail
                     ▼
                quarantine/ + log
```

Orchestre par `promote.py`. Refuse la promotion si recall@5 chute sous le seuil.

## Arborescence cible

```
project-zomboid-knowledge-engine/
├── src/                      # Code source (parseur, MCP, ingestion)
├── data/
│   ├── raw/                  # Extractions brutes (jamais modifiées)
│   ├── staging/              # Zone de travail temporaire
│   ├── quarantine/           # Entités rejetées
│   └── production/           # Données validées (intouchables sans process)
├── db/
│   ├── staging/              # [storage vectoriel] de test
│   └── production/           # [storage vectoriel] servi à l'agent
├── backups/                  # Snapshots horodatés + rotation
├── tests/
│   └── golden_set/           # Q/R de référence
├── docs/
│   ├── CHANGELOG.md
│   ├── ARCHITECTURE.md
│   └── VERSIONING.md
├── logs/                     # Logs JSON horodatés
├── .env.unified
├── requirements.txt
└── VERSION                   # "0.1.0-alpha"
```

## Outils MCP

| Type | Nom | Description |
|------|-----|-------------|
| Tool | `pz_knowledge_retrieval` | Recherche sémantique (vectoriel + reranking) sur les collections |
| Tool | `pz_get_item` | Lookup déterministe par ID (Base.Axe) — jamais de vectoriel |
| Tool | `pz_generate_mod_template` | Génère arborescence et fichiers de base d'un mod |
| Resource | Mécaniques Markdown | Fiches vérifiées à la main |
| Resource | UI diégétiques Lua | Doc de création d'UI diégétiques |
| Resource | Signatures Java API | `IsoPlayer`, `ItemContainer`… |
| Prompt | `help_me_survive` | Analyse de survie hardcore (calories, moodles, panique) |
| Prompt | `debug_lua_script` | Audit Lua confronté à l'API Java décompilée |

## Stratégies Anti-Crash

| Menace | Parade |
|--------|--------|
| Fichier script malformé | Parsing isolé par entité + quarantaine |
| Encodage exotique (latin-1) | Cascade d'encodages + `errors="replace"` |
| Accolades mal fermées | Regex tolérante + validation Pydantic |
| OOM à l'ingestion | Batch adaptatif + checkpoints reprenables |
| Handler MCP qui plante | Décorateur `safe_tool` (capture tout) |
| Process serveur mort | Watchdog de redémarrage |
| Corruption de DB | Backup + rotation avant ré-ingestion |

## Versioning

### SemVer adapté : MAJOR.MINOR.PATCH-stage

| Segment | Quand l'incrémenter |
|---------|---------------------|
| MAJOR | Refonte d'architecture, rupture de schéma |
| MINOR | Nouvelle collection, outil MCP, source de données |
| PATCH | Correction parsing, fix fiche, retrait quarantaine |

### Double versioning
- Version du **moteur** (logiciel) : SemVer classique
- Version des **données du jeu** (B41/B42) : portée par le tag version des chunks

### Cycle de vie

| Stage | Critère d'entrée | Ce qui est permis |
|-------|-----------------|-------------------|
| -alpha | Pipeline de bout en bout | Schémas instables, collections incomplètes |
| -beta | 5 collections peuplées + golden set passe | Gel du schéma, tests agent réels |
| -rc | Zéro bug bloquant sur 1 semaine | Uniquement fixes critiques |
| release | Golden set 100% + doc à jour | Tag Git figé, backup archivé |

Transition = tag Git annoté + entrée CHANGELOG + backup archivé.

## Convention de commits

```
feat(mcp): ajoute l'outil pz_get_item
fix(parser): gère les accolades imbriquées des recipes
docs(changelog): prépare la 1.2.0-beta
refactor(ingest): batch adaptatif anti-OOM
test(golden): +5 questions sur l'artisanat B42
chore(deps): pin sqlite-storage backend
```

Bénéfice : CHANGELOG généré automatiquement depuis l'historique Git.
