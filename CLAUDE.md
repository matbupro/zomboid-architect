# CLAUDE.md — Zomboid_Architect

## Important : Dossier agent/ toujours à jour

**Le dossier `agent/` est le dossier de vérité opérationnel du projet.** Il contient la mémoire interne (GOAL, rules, todo, architecture, memories, syntax). Il DOIT refléter l'état actuel du codebase.

### Avant chaque session de travail significative
Toujours lancer en premier :
```powershell
.\agent\maintenance\sync_agent.ps1 "Description des changements attendus"
```

Cela met à jour automatiquement :
- `agent/syntax.md` → arborescence git ls-files, dernier commit, version
- `agent/README.md` → index auto-des fichiers mémoire
- `CHANGELOG.md` → dernier commit non-liste (si notes fournies)
- `agent/memories.md` → résumé de session (si notes fournies)
- **Notion DB** → sync avec `python -m notion_client --push` (toujours actif)

### Règle d'or : todo.md → Notion
**Chaque modification de `agent/todo.md` DOIT être synchronisée vers Notion.**
Le pre-commit hook le fait automatiquement quand un commit touche `todo.md`.

### Automatisation configurée

| Mécanisme | Comment ça marche | Persistance |
|-----------|-------------------|-------------|
| Cron Claude Code | Quotidien à 9h30 (outil cron) | ~7 jours, recréer si expire |
| Windows Task Scheduler | Tâche `Zomboid_Architect_sync_agent` déjà installée (23h) — vérifiable : `schtasks /query /tn "Zomboid_Architect_sync_agent"` | Permanente |
| Pre-commit hook | `.git/hooks/pre-commit` lance sync en arrière-plan | Permanent si git le détecte |

### En cas d'oubli de sync
Si l'utilisateur mentionne un changement structurel important, exécuter le sync immédiatement. Ne pas attendre.

---

## Références architecture (S9)

| Doc | Emplacement | Contenu |
|-----|-------------|---------|
| `ARCHITECTURE.md` | à la racine | Diagramme complet du pipeline : Sources → Ingestor → Storage → Bot Discord |
| `SETUP.md` | à la racine | Bootstrap infra en 5 min (docker-compose + psql migration) |
| Schema PG | `migrations/001_initial_schema.sql` | 17 tables, 7 ENUMs, 3 views, triggers — **unique source de vérité DB** |
| Collections Storage | `ingestor/storage/storage_writer.py` + `pz_storage.py` | Abstraction multi-backend (SQLite ↔ PG/pgvector) |
| Collections PG | `.github/workflows/tests.yml:89-140` | security gate bloque écriture manuelle de production/ |

### Collections PG principales (migrations/001_initial_schema.sql)
Les tables critiques référencées par le pipeline :
- **agent_runs, mod_artifacts, mod_projects** — boucle agentique
- **ingestion_runs, data_coverage, collection_health, data_links** — monitoring S7
- **validation_results, test_scenarios** — golden set & regression
- **publish_log, fix_attempts** — promote/rollback tracking

### Collections StorageBackend (vectoriel)
- `pz_items` (~350 entités PZ) — wikijson → WikiJsonProcessor
- `pz_recipes` (~250 recettes) — wikijson → WikiJsonProcessor
- `pz_mechanics` (skills/perks/weather/mobs) — wikijson + web crawl
- `pz_web_pages`, `pz_lua_api`, `pz_java_api` — documentation API
- `pz_mods` — Steam Workshop mod metadata
