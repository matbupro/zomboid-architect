# Agent Memory - Dossier de Mémoire Interne

Ceci est **mon** espace mémoire. Le dossier agent/ contient tous mes fichiers de contexte organisés par domaine pour limiter les pertes et hallucinations.

## Index des Fichiers

| Fichier | Role |
|---------|------|
| .agent_memory.md | (non décrit)
| architecture.md | Stack technique, arborescence, flux de données, MCP
| GOAL.md | Objectif principal du projet + créateur
| memories.md | Souvenirs, infos utilisateur, astuces trouvées
| rules.md | 12 commandements + règles d'or du projet
| syntax.md | État actuel du projet (ce fichier)
| todo.md | TODO list complétée (mise à jour continue)

## Maintenance

- maintenance/sync_agent.ps1 - script de mise a jour automatique (lance manuellement ou via cron/task scheduler)
- Commande : agent\maintenance\sync_agent.ps1 "notes de session"
- S'execute automatiquement toutes les 24h via cron Windows
