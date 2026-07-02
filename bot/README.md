# Zomboid Knowledge Engine — Bot Discord

## Lancement

### Locale (sans Docker) — recommandé pour le dev
```powershell
cd "f:\Antigravity DEV\Zomboid_Architect"
.\run-bot.ps1          # PowerShell (recommande)
:: ou
run-bot.bat            # cmd.exe
```

Le bot lit automatiquement `bot/.env` au démarrage.

### Docker (production)
```powershell
cd "f:\Antigravity DEV\Zomboid_Architect"
docker compose up -d
```

## Variables d'environnement

| Variable | Obligatoire | Défaut | Description |
|---|---|---|---|
| `DISCORD_TOKEN` | oui | — | Token du bot Discord |
| `OLLAMA_BASE_URL` | non | `http://host.docker.internal:11434` | URL du serveur Ollama |
| `OLLAMA_MODEL` | non | `llama3.2` | Modèle LLM local par défaut |
| `CLAUDE_API_KEY` | non | — | Clé API Anthropic (fallback) |
| `CHROMA_HOST` | non | `http://host.docker.internal:8000` | URL du serveur ChromaDB |

## Structure

```
bot/
├── main.py           # Entrée, slash commands, events DM
├── config.py         # chargement .env + dataclass Settings
├── engine_client.py  # KnowledgeEngineClient (ChromaDB HTTP + local fallback)
├── llm_adapter.py    # OllamaProvider / ClaudeProvider
├── pipeline.py       # message → detect_intent → enrich_context → build_prompt → LLM
├── .env.example      # template
└── Dockerfile        # image Python 3.12 multi-stage
```

## Slash commands

| Commande | Description |
|---|---|
| `/help` | Liste des commandes |
| `/stats <item>` | Stats exactes d'un objet Zomboid (lookup déterministe) |
| `/survie <scenario>` | Conseil de survie hardcore |
| `/recipe <ingredient>` | Recettes d'artisanat |
| `/moddoc <api>` | Documentation modding Lua/Java |
| `/search <query>` | Recherche sémantique libre |

## DM automatique

Envoyez un message en DM au bot — il répond automatiquement avec le pipeline complet :
recherche ChromaDB → construction du prompt → LLM local (Ollama) ou Claude API.
