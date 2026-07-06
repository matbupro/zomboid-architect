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

## Session du 2026-07-02
continuation priorite - verification etat

## Session du 2026-07-02
Golden set recall@5 test suite (17 tests) + lock.py import fix + notion scripts cleanup

## Session du 2026-07-02
Phase 5+11 tests : golden set recall@5 (17/17) + chroma_writer unitaires (39/39), commit 1298527

## Session du 2026-07-02
Phase Steam + workshop + .pbo : nouveau module steam/ (path_discovery, library_folders, workshop_scanner, steamcmd_client), processeur .pbo, mod_ingester, 4 nouvelles collections ChromaDB, commandes CLI --steam-scan/--workshop-scan/--mod-ingest, tests 12/12

## Session du 2026-07-04
Phase 12 ajoutée : pipeline de génération de mods + sanity check cohérence projet

## Session du 2026-07-04
Phase 6: Filtrage B41/B42 natif — game_version filtering avec ChromaDB , integre dans chroma_client, engine_client, pipeline, et bot main.py. 24 nouveaux tests, 84 tests total.

## Session du 2026-07-04
feat: incremental ingestion via SHA-256 hash index — 17 tests, tous passant. FIX test isolation : _quarantine_patch pour patcher get_quarantine_path() directement (monkeypatch.setenv ignoré car la fonction ne lit PAS les env vars).

## Session du 2026-07-05
Phase 6 complet: regression tester + release tagging, 36 nouveaux tests

## Session du 2026-07-05
Phase 3: ingest.py global ingestion script, 8 objects B41, recipes, mechanics, strict metadata validation, batch anti-OOM, 24 tests

## Session du 2026-07-05
Phase 3.1: ingest.py metadata fix + promote.py golden set gate + chroma_client SDK migration

## Session du 2026-07-05
guard production + pre-ingest backup + rollback + CI security gate

## Session du 2026-07-05
golden set aligné + promote.py passe a 0.933 recall (promotion reussie) + guard production + backup pre-ingest

## Session du 2026-07-05
todo update: architecture decision SQLite/pgvector + guard/backup complete + golden set 0.933 recall

## Session du 2026-07-05
Correction bugs syntaxe + sécurité/config + gouvernance + 67 tests unitaires

## Session du 2026-07-05
Correction bugs syntaxe + sécurité/config + gouvernance + 67 tests unitaires + rate limiting

## Session du 2026-07-05
Fuzzy matching sync : normalisation accents/apostrophes/tirets + Levenshtein + _fuzzy_match() + 24 nouveaux tests

## Session du 2026-07-05
todo.md sync Notion automatique

## Session du 2026-07-05
doctor repair mode + setup fresh machine install

## Session du 2026-07-06
Phase 8 Web crawling termine : cloudscraper CF bypass, PZ wiki extraction 2 pages + ChromaDB storage, cross-collection search verified. Test file cleanup.

## Session du 2026-07-06
Phase 9 CLI validatee : --file + --dir testés sur .env/Dockerfile/py/md. MIME detection fix: _peek_text fallback, config file recognition. Auto-accept storage en non-TTY. 62 tests passing.

## Session du 2026-07-06
A-D: Docker ingestor fix, golden report CLI, parser B42 validation

## Session du 2026-07-06
Sync post-commit: ingestor hardening + bot Docker/config + parser restructure + 27 files changed