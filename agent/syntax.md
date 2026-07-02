# État Actuel du Projet

## Statut
**Phase 1 complétée.** **Phase Bot Discord complétée.** Projet passe de l'état zéro à un bot Discord fonctionnel.

Dernière mise à jour : 2026-07-01 — Bot Discord codé, Dockerisé, prêt au déploiement.

## Structure du projet (à jour)

```
Zomboid_Architect/
├── agent/                    # Ma mémoire interne (inviolée)
│   ├── README.md             ← index des fichiers de mémoire
│   ├── GOAL.md               ← objectif + créateur
│   ├── rules.md              ← 12 commandements + règles d'or
│   ├── todo.md               ← TODO list complète (mise à jour continue)
│   ├── architecture.md       ← stack technique du knowledge engine
│   ├── memories.md           ← souvenirs + astuces
│   └── syntax.md             ← état actuel (ce fichier)
├── bot/                      # Bot Discord Zomboid — NOUVEAU
│   ├── main.py               ← point d'entrée, slash commands, DM handler
│   ├── config.py             ← chargement .env + Settings dataclass
│   ├── engine_client.py      ← client ChromaDB + fallback local (pz_get_item)
│   ├── llm_adapter.py        ← adapter Ollama + Claude API (fallback)
│   ├── pipeline.py           ← pipeline: message → route → engine → LLM → réponse
│   ├── requirements.txt      ← dépendances Python
│   ├── Dockerfile            ← image du bot
│   └── .env.example          ← variables d'environnement à configurer
├── docs/
│   └── roadmap.md            # Roadmap maître (inviolée)
├── docker-compose.yml        # Orchestration : bot + ollama + chromadb
└── Zomboid_Architect.code-workspace
```

## Fichiers Mémoire Actifs

| Fichier | Rôle |
|---------|------|
| [GOAL.md](agent/GOAL.md) | Objectif principal du projet + créateur |
| [rules.md](agent/rules.md) | 12 commandements + règles d'or |
| [todo.md](agent/todo.md) | TODO list complète (mise à jour continue) |
| [architecture.md](agent/architecture.md) | Stack technique, arborescence, flux, MCP |
| [memories.md](agent/memories.md) | Souvenirs, infos utilisateur, astuces trouvées |
| [syntax.md](agent/syntax.md) | État actuel du projet (ce fichier) |

## Contexte Technique

- **Projet :** `f:\Antigravity DEV\Zomboid_Architect`
- **Créateur :** ElChibros
- **Clé du dossier mémoire :** `agent/` — accès libre pour organisation interne de l'agent
- **Mémoire Claude Code native :** `~/.claude/projects/f--Antigravity-DEV-Zomboid-Architect/memory/` (chargement automatique)
