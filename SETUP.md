# SETUP.md — Bootstrap de l'infrastructure complète

**Temps estimé : 5 minutes.** Tout le projet Zomboid_Architect sur un poste Windows avec Docker Desktop + Python 3.10+.

## Prérequis

| Outil | Version | Pourquoi |
|-------|---------|----------|
| Python | ≥ 3.10 | Codebase |
| Docker Desktop | ≥ 24 | PG, Qdrant, MinIO, Redis |
| PowerShell 5.1+ | — | Scripts Windows (.ps1) |
| `make` (WSL/Git Bash) | — | Makefile cibles |

## 1. Clone + dépendances

```powershell
cd f:\Antigravity DEV\Zomboid_Architect
pip install -r requirements.txt
# Ou le minimum :
pip install -e ingestor/ -e bot/ -e . 2>/dev/null || true
```

## 2. Variables d'environnement

Copier le template et remplir les valeurs obligatoires :

```powershell
Copy-Item .env.unified.example .env.unified 2>$null
# OU (si pas de template) :
New-Item -ItemType File .env.unified -Force
Add-Content .env.unified "DISCORD_TOKEN=votre_token_discord"
Add-Content .env.unified "STORAGE_BACKEND=postgres"  # backend par défaut (PG/pgvector)
```

| Variable | Requis ? | Défaut | Description |
|----------|----------|--------|-------------|
| `DISCORD_TOKEN` | **OUI** | — | Token bot Discord (le bot refuse de démarrer sans) |
| `STORAGE_BACKEND` | non | `postgres` | stockage vectoriel (postgres/pgvector par défaut, optionnel : `qdrant`) |
| `STORAGE_PG_PASS` | si postgres | `""` | Mot de passe PG |
| `OLLAMA_BASE_URL` | non | `http://host.docker.internal:11434` | Serveur embedding local |
| `OLLAMA_MODEL` | non | `nomic-embed-text` | Modèle d'embedding vectoriel |
| `QDRANT_URL` | si qdrant backend | `http://localhost:6333` | Serveur Qdrant vectoriel |
| `MINIO_ROOT_USER` | — | `minioadmin` | Accès MinIO object storage |
| `GITEA_URL` | — | `http://localhost:3000` | Instance Gitea pour mods |

> **Pour un premier test avec PostgreSQL natif Windows :** installer PG 16 (`winget install PostgreSQL.16`), démarrer le service, et laisser `STORAGE_BACKEND=postgres` (par défaut). Le bot Discord démarre directement.

> **Alternative légère :** `STORAGE_BACKEND=qdrant` avec un serveur Qdrant local pour testing vectoriel sans base relationnelle.

## 3. Infrastructure Docker (optionnel — requise pour STORAGE_BACKEND=postgres en mode conteneur)

```powershell
# Lancer toute la stack infra en arrière-plan
docker compose up -d ollama postgres qdrant minio redis

# Attendre que PG soit prêt
Start-Sleep -Seconds 5

# Appliquer le schéma SQL
if (Test-Path migrations\001_initial_schema.sql) {
    docker exec -i pz-agent-postgres psql -U postgres -d zomboid_storage < migrations\001_initial_schema.sql
}
```

Vérifier :

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}" | Select-String "Up"
# Devrait afficher : ollama, postgres, qdrant, minio, redis tous Up
```

## 4. Pré-hooks Git (optionnel mais recommandé)

```powershell
# Les hooks existent déjà dans .git/hooks/ — les activer :
Copy-Item agent\maintenance\sync_agent.ps1 .git\hooks\sync_agent.ps1 -Force 2>$null
```

Les hooks pre-commit exécutés automatiquement :
- **pre-commit.cmd** → sync `agent/` si todo.md change (sync_agent.ps1)
- **pre-validate-ddl.ps1** → scanne DROP TABLE / ALTER BREAKING dans migrations staged
- **pre-validate-collections.ps1** → lance `--validate-collections` sur storage files staged

## 5. Lancement rapide

```powershell
# Option A : Bot Discord (le plus simple)
cd bot && python main.py

# Option B : Ingestion complète
python -m ingestor.cli --ingest-pz-full

# Option C : Dashboard monitoring
python -m ingestor.cli --ingest-status
python -m ingestor.cli --ingest-status --short   # mode CI (une ligne)

# Option D : Validation des collections
python -m ingestor.cli --validate-collections
```

## 6. Vérification complète

```powershell
# Tests unitaires
pytest -m "not e2e and not slow" -v

# Ingestion + validation
python -m ingestor.cli --ingest-status | Select-String "OK|PASS|CRIT"
python -m ingestor.cli --validate-collections 2>&1 | Select-String "PASS|FAIL"
```

## Dépannage rapide

| Symptôme | Solution |
|----------|----------|
| `psycopg2` import error | `pip install psycopg2-binary` |
| Qdrant refusé connexion | `docker compose up -d qdrant` |
| Bot ne démarre pas | Vérifier `DISCORD_TOKEN` dans `.env.unified` |
| Ollama non accessible | `curl http://localhost:11434` → doit répondre JSON |
| PostgreSQL refusé connexion | `docker exec pz-agent-postgres pg_isready` |

## Prochaines étapes (optionnelles)

| Tâche | Commande |
|-------|----------|
| Ingestion PZ complète | `python -m ingestor.cli --ingest-pz-full` |
| Coverage report | `python -m ingestor.cli --coverage-report` |
| Monitor + alertes | `python -m ingestor.cli --ingest-status` |
| Promotion staging → prod | `make promote` ou `python ingestor/promote.py` |
| Restore backup | `python restore.py list` / `restore <id>` |

---

*Ce fichier est la source de vérité pour le bootstrapping. Mise à jour avec chaque changement structurel majeur.*
