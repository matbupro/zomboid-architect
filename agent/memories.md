# Souvenirs & Astuces

## Créateur
- **ElChibros** — enregistré aussi dans la mémoire Claude Code native (`memory/creator.md`)

## Persistance Mémoire (double couche)
1. **`agent/`** — mémoire opérationnelle, mise à jour en temps réel pendant qu'on travaille ensemble
2. **Mémoire Claude Code native** (`~/.claude/projects/.../memory/`) — chargée automatiquement chaque session, contient les faits stables (project-context.md, creator.md)

## Notes Techniques

### Architecture Bot Discord
- Le bot utilise discord.py avec intents message_content + messages + guilds + members
- Pipeline : message → detect_intent → enrich_context (ChromaDB / fallback local) → build_prompt → LLM.complete
- LLM par défaut : Ollama local (`:11434`), fallback Claude API si clé configurée
- Les réponses > 2000 chars sont découpées en messages successifs via `_trunc_string`
- Slash commands avec slash prefix explicite ET détection implicite (regex patterns)
- Mode DM automatique intercepté via `on_message` — ignore les channels publics

### Docker
- docker-compose.yml orchestre 3 services : bot, ollama, chromadb
- Ollama sur la machine hôte → `host.docker.internal:11434`
- Pour Windows : préférer Ollama installé en natif + `host.docker.internal` plutôt que le conteneur ollama intégré

### Lancement sans Docker (dev)
- Utiliser `run-bot.ps1` à la racine du projet ou `run-bot.bat` pour cmd
- Le bot lit `bot/.env` automatiquement via `_load_env()` dans config.py
- Commande directe : `cd bot && python main.py`

### Règles de l'agent
- Quand l'utilisateur dit "fais ça", ne pas demander d'autorisation supplémentaire — agir directement.
- Le fichier `.agent_memory.md` a été déplacé dans `agent/` puis découpé en fichiers spécialisés pour limiter les pertes et hallucinations de données.
- La mémoire est divisée en 6 fichiers indépendants dans `agent/` : GOAL, rules, todo, architecture, memories, syntax.

## Session du 2026-07-02
P0 audit remediation: fixed collection mapping in engine.py, async health checks in bot/main.py, DRY imports via _import_compat.py, heartbeat + stale lock recovery in governance/lock.py