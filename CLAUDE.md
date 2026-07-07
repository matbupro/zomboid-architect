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
