# Installation rapide — Zomboid_Architect

## Prérequis

| Outil | Version min. | Installer via |
|-------|-------------|---------------|
| Python ≥ 3.10 | 3.14 conseillé | `winget install Python.Python.3.14` |
| Git |最新版 | `winget install Git.Git` |
| Docker Desktop |最新版 | `winget install Docker.DockerDesktop` |
| Ollama |最新版 | https://ollama.com → installer + `ollama pull qwen3.6:35b-a3b` |

## Installation en 1 clic (Windows)

```powershell
# Cloner le repo
git clone <repo-url>
cd Zomboid_Architect

# Executer le setup automatiquement
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Cela fait **tout** : deps Python, git hooks, .env, Playwright Chromium, vérification Docker/Ollama.

## Installation manuelle (étape par étape)

### 1. Deps Python
```powershell
pip install -r notion_client/pyproject.toml
pip install -r ingestor/requirements.txt
pip install -r bot/requirements.txt
```

### 2. Variables d'environnement
```powershell
# Global
copy .env.example .env   # puis editer .env

# Notion API (optionnel)
copy notion_client\.env.notion.example notion_client\.env.notion
# Remplir NOTION_API_KEY et NOTION_DATABASE_ID dans notion_client/.env.notion
```

### 3. Playwright Chromium
```powershell
pip install playwright
playwright install chromium
```

### 4. Docker (ChromaDB + Bot)
```powershell
docker compose up -d
```

## Vérifier que tout fonctionne

```powershell
# Tests unitaires
pytest tests/ --tb=short

# Sync Notion (si config OK)
python -m notion_client --push

# Bot Discord (si .env + Ollama OK)
.\run-bot.ps1
```

## Configuration du projet sur une nouvelle machine

Si tu clones le repo ailleurs, **un seul clic suffit** :
1. Installer les prérequis (Python, Git, Docker, Ollama)
2. Lancer `setup.ps1`
3. Remplir `.env` et `notion_client/.env.notion` avec tes clés

Le projet est ensuite 100% fonctionnel.

## Fichiers critiques à ne pas perdre

| Fichier | Contenu | Où le sauvegarder |
|---------|---------|-------------------|
| `.env` | Clés Discord, Ollama, etc. | Toi-même (jamais commité) |
| `notion_client/.env.notion` | Clé Notion API + DB ID | Toi-même (jamais commité) |
| `bot/.env` | Token bot Discord | Toi-même (jamais commité) |

Ces fichiers sont dans `.gitignore` — **tu es le seul à les avoir**.
