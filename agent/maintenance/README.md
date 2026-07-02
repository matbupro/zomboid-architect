# Agent/ Maintenance Kit

Ce dossier contient les outils qui maintiennent le dossier `agent/` a jour automatiquement.

## sync_agent.ps1

Script PowerShell 5.1 compatible qui synchronise **tout** le contenu de `agent/` depuis le code source (source of truth) :

### Ce qu'il met à jour

| Fichier | Ce qu'il fait |
|---------|---------------|
| `agent/syntax.md` | Arborescence git ls-files, dernier commit, version courante |
| `agent/README.md` | Index des fichiers memoire (auto-genere depuis les .md presentes) |
| `agent/memories.md` | Ajoute un resume de session si notes fournies |
| `agent/todo.md` | Marqueur de dernière synchro |
| `CHANGELOG.md` (racine) | Ajoute le dernier commit non-liste |

### Usage

**Manuel :**
```powershell
.\agent\maintenance\sync_agent.ps1 "Description des changements de la session"
```

**Sans notes (structure uniquement) :**
```powershell
.\agent\maintenance\sync_agent.ps1
```

### Automatisation actuelle

- **Cron quotidien** : 9h30 via Claude Code cron tool
- **Pre-commit hook** : en cours de configuration dans `.git/hooks/pre-commit`
- **Instruction session** : a toujours executer au debut de chaque session de travail significatif

### Emplacements des hooks

| Mecanisme | Etat | Persistance |
|-----------|------|-------------|
| Cron Claude | Actif (9h30) | 7 jours max, a recreer si besoin |
| Windows Task Scheduler | A configurer | Permanente (admin requis) |
| Pre-commit git | Non installe | Per-commit |

### Architecture auto-sync

```
session de travail significant
    └──> sync_agent.ps1 "notes"   ← mettre a jour agent/ immediatement

chacune des 24h
    └──> cron task scheduler       ← mise a jour structure automatique

commit sur fichiers structurel
    └──> pre-commit hook           ← mise a jour silencieuse (prochainement)
```

### Avertissements

- Le script utilise `git ls-files` → il doit etre lance depuis la racine du repo ou un sous-dossier. Il se resout automatiquement.
- L'ecriture est en UTF-8 BOM (standard Windows) → compatible tous les EDI.
- Le script est non-destructif : il **met a jour** les fichiers existants, jamais les supprime.
