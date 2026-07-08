# Agent Memory - Dossier de Memoire Interne

Ceci est **mon** espace memoire. Le dossier agent/ contient tous mes fichiers de contexte organises par domaine pour limiter les pertes et hallucinations.

## Index des Fichiers

| Fichier | Role |
|---------|------|
| .agent_memory.md | (non decrit)
| architecture.md | Stack technique, arborescence, flux de donnees, MCP
| GOAL.md | Objectif principal du projet + createur
| memories.md | Souvenirs, infos utilisateur, astuces trouvees
| rules.md | 12 commandements + regles d'or du projet
| syntax.md | Etat actuel du projet (ce fichier)
| todo.md | TODO list completee (mise a jour continue)
| todo_storage_migration.md | (non decrit)

## Maintenance

- maintenance/sync_agent.ps1 - script de mise a jour automatique (lance manuellement ou via cron/task scheduler)
- Commande : agent\maintenance\sync_agent.ps1 "notes de session"
- S'execute automatiquement toutes les 24h via cron Windows
