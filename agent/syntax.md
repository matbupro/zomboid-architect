# Etat Actuel du Projet

## Status
**Derniere MAJ agent/ : 2026-07-03 par sync_agent.ps1 automatique.**

Dernier commit : 1298527
Version moteur : 0.1.0-alpha (b41)

## Arborescence (git ls-files, mise a jour auto)

`
  |-- .claude/settings.local.json
  |-- .env.example
  |-- .gitignore
  |-- agent/.agent_memory.md
  |-- agent/architecture.md
  |-- agent/GOAL.md
  |-- agent/maintenance/README.md
  |-- agent/maintenance/sync_agent.ps1
  |-- agent/memories.md
  |-- agent/README.md
  |-- agent/rules.md
  |-- agent/syntax.md
  |-- agent/todo.md
  |-- bot/__init__.py
  |-- bot/cleanup_channels.py
  |-- bot/config.py
  |-- bot/Dockerfile
  |-- bot/engine_client.py
  |-- bot/llm_adapter.py
  |-- bot/main.py
  |-- bot/pipeline.py
  |-- bot/README.md
  |-- bot/requirements.txt
  |-- CHANGELOG.md
  |-- CLAUDE.md
  |-- docker-compose.yml
  |-- ingestor/__init__.py
  |-- ingestor/cli.py
  |-- ingestor/config.py
  |-- ingestor/Dockerfile
  |-- ingestor/engine.py
  |-- ingestor/processors/__init__.py
  |-- ingestor/processors/audio.py
  |-- ingestor/processors/base.py
  |-- ingestor/processors/docx.py
  |-- ingestor/processors/epub.py
  |-- ingestor/processors/image.py
  |-- ingestor/processors/pbo.py
  |-- ingestor/processors/pdf.py
  |-- ingestor/processors/text.py
  |-- ingestor/processors/video.py
  |-- ingestor/processors/web.py
  |-- ingestor/promote.py
  |-- ingestor/quarantine_manager.py
  |-- ingestor/README.md
  |-- ingestor/requirements.txt
  |-- ingestor/search/__init__.py
  |-- ingestor/search/brave.py
  |-- ingestor/search/duckduckgo.py
  |-- ingestor/steam/__init__.py
  |-- ingestor/steam/library_folders.py
  |-- ingestor/steam/mod_ingester.py
  |-- ingestor/steam/path_discovery.py
  |-- ingestor/steam/steamcmd_client.py
  |-- ingestor/steam/workshop_scanner.py
  |-- ingestor/storage/chroma_writer.py
  |-- Makefile
  |-- notion_clean_priority.py
  |-- notion_clean_remaining.py
  |-- notion_cleanup.py
  |-- notion_cleanup2.py
  |-- notion_client/.env.notion.example
  |-- notion_client/__init__.py
  |-- notion_client/api.py
  |-- notion_client/parser.py
  |-- notion_client/sync.py
  |-- notion_db_check.py
  |-- notion_db_check2.py
  |-- notion_diagnose.py
  |-- notion_fix_p10_items.py
  |-- notion_force_fix.py
  |-- notion_ids_check.py
  |-- notion_priority_check.py
  |-- notion_redistribute_p20.py
  |-- notion_resync_priorities.py
  |-- notion_sync.py
  |-- notion_update_schema.py
  |-- notion_verify_clean.py
  |-- README.md
  |-- requirements.txt
  |-- restore.py
  |-- run-bot.bat
  |-- run-bot.ps1
  |-- src/__init__.py
  |-- src/governance/__init__.py
  |-- src/governance/_import_compat.py
  |-- src/governance/game_version.py
  |-- src/governance/lock.py
  |-- src/governance/logger.py
  |-- src/governance/parser.py
  |-- src/governance/worker.py
  |-- src/retrieval/__init__.py
  |-- src/retrieval/chroma_client.py
  |-- tests/golden_set/golden.json
  |-- tests/run_tests.py
  |-- tests/test_chroma_writer.py
  |-- tests/test_golden_set.py
  |-- tests/test_steam_integration.py
  |-- VERSION
  |-- VERSIONING.md
  |-- Zomboid_Architect.code-workspace
`

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
| 2026-07-03 | sync_agent.ps1 | MAJ auto - tree, last commit, version |
