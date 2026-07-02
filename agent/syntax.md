# Etat Actuel du Projet

## Status
**Derniere MAJ agent/ : 2026-07-02 par sync_agent.ps1 automatique.**

Dernier commit : 328f113
Version moteur : 0.1.0-alpha (b41)

## Arborescence (mise a jour auto)

```
.claude/
├── scheduled_tasks.json      ← cron tasks Claude Code (session-only)
├── scheduled_tasks.lock
└── settings.local.json       ← permissions Claude Code
.env.example                   ← template variable d'environnement
.gitignore
agent/
├── .agent_memory.md          ← memoire interne (non decrit)
├── GOAL.md                   ← objectif principal + createur
├── architecture.md            ← stack technique, flux, MCP
├── memories.md               ← souvenirs, infos utilisateur, astuces
├── README.md                 ← index auto-des fichiers memoire
├── rules.md                  ← 12 commandements + regles d'or
├── syntax.md                 ← etat actuel du projet (ce fichier)
├── todo.md                   ← TODO list completee (mise a jour continue)
└── maintenance/
    ├── README.md             ← doc infrastructure sync
    └── sync_agent.ps1        ← moteur de sync agent/
bot/                          ← Discord bot (discord.py)
├── __init__.py
├── cleanup_channels.py
├── config.py
├── Dockerfile
├── engine_client.py          ← client HTTP vers le moteur de connaissance
├── llm_adapter.py            └─ adaptation Ollama/LLM
├── main.py                   ← point d'entree du bot Discord
├── pipeline.py
├── README.md
└── requirements.txt
CHANGELOG.md                  ← historique des versions (auto-genere)
CLAUDE.md                     ← instructions persistantes Claude Code
docker-compose.yml             ← orchestrant Ollama + ChromaDB
ingestor/                     ← ingestion multi-format (text, pdf, docx, epub...)
├── __init__.py
├── cli.py                    ← interface en ligne de commande
├── config.py
├── Dockerfile
├── engine.py                 ← moteur principal d'indexation + mapping collections
├── promote.py                └─ promote des documents au statut "golden"
├── quarantine_manager.py     ← gestion du contenu suspect
├── README.md
├── requirements.txt
├── processors/               ← parseurs par format
│   ├── __init__.py
│   ├── audio.py, base.py, docx.py, epub.py
│   ├── image.py, pdf.py, text.py
│   ├── video.py, web.py
├── search/                   └─ moteurs de recherche (Brave, DuckDuckGo)
│   ├── __init__.py
│   ├── brave.py, duckduckgo.py
└── storage/
    └── chroma_writer.py      ← ecriture ChromaDB
Makefile                      ← commandes standard (build, test, lint...)
README.md                     ← documentation principale
requirements.txt              └─ dependances Python globales
restore.py                    ← outils de restauration de donnees
run-bot.bat / run-bot.ps1     ← lanceurs du bot Discord
src/                          ← code noyau du moteur (governance + retrieval)
├── __init__.py
├── governance/               ← logique metier et regles
│   ├── __init__.py
│   ├── _import_compat.py     └─ imports centralises dual-layout (src/ingestor)
│   ├── game_version.py       ← detection B41/B42
│   ├── lock.py               ← FileLock avec heartbeat + stale detection
│   ├── logger.py             ← logger centralise
│   ├── parser.py             └─ parsing de fichiers governnance
│   └── worker.py
└── retrieval/                └─ couche de requete ChromaDB (RAG)
    ├── __init__.py
    └── chroma_client.py
tests/golden_set/golden.json  ← ensemble de reference pour tests
VERSION                       ← version SemVer du moteur
VERSIONING.md                 ← politique de versioning
Zomboid_Architect.code-workspace ← config workspace VSCode
```

## Fichiers Memoire Actifs

| Fichier | Role |
|---------|------|
| [GOAL.md](GOAL.md) | Objectif principal du projet + createur |
| [rules.md](rules.md) | 12 commandements + regles d'or |
| [todo.md](todo.md) | TODO list completee (mise a jour continue) |
| [architecture.md](architecture.md) | Stack technique, arborescence, flux, MCP |
| [memories.md](memories.md) | Souvenirs, infos utilisateur, astuces trouvees |
| [syntax.md](syntax.md) | Etat actuel du projet (ce fichier) |

## Contexte Technique

- **Projet :** F:\Antigravity DEV\Zomboid_Architect
- **Createur :** ElChibros
- **Clef du dossier memoire :** agent/ - acces libre pour organisation interne de l'agent
- **Memoire Claude Code native :** ~/.claude/projects/f--Antigravity-DEV-Zomboid-Architect/memory/ (chargement automatique)

## Historique des MAJ agent/

| Date | Action | Detail |
|------|--------|--------|
| 2026-07-02 | sync_agent.ps1 | MAJ auto - tree, last commit, version |
