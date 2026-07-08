# Souvenirs & Astuces

## Créateur
- **ElChibros** — enregistré aussi dans la mémoire Claude Code native (`memory/creator.md`)

## Persistance Mémoire (double couche)
1. **`agent/`** — mémoire opérationnelle, mise à jour en temps réel pendant qu'on travaille ensemble
2. **Mémoire Claude Code native** (`~/.claude/projects/.../memory/`) — chargée automatiquement chaque session, contient les faits stables (project-context.md, creator.md)

## Notes Techniques

### Architecture Bot Discord
- Le bot utilise discord.py avec intents message_content + messages + guilds + members
- Pipeline : message → detect_intent → enrich_context (StorageBackend vectoriel / fallback local) → build_prompt → LLM.complete
- LLM par défaut : Ollama local (`:11434`), fallback Claude API si clé configurée
- Les réponses > 2000 chars sont découpées en messages successifs via `_trunc_string`
- Slash commands avec slash prefix explicite ET détection implicite (regex patterns)
- Mode DM automatique intercepté via `on_message` — ignore les channels publics

### Docker
- docker-compose.yml orchestre les services : bot, ollama (ingestor en launch-on-demand) — **pas de ChromaDB**
- Ollama sur la machine hôte → `host.docker.internal:11434`
- Pour Windows : préférer Ollama installé en natif + `host.docker.internal` plutôt que le conteneur ollama intégré

### Lancement sans Docker (dev)
- Utiliser `run-bot.ps1` à la racine du projet ou `run-bot.bat` pour cmd
- Le bot lit `.env.unified` automatiquement via `_load_env()` dans config.py
- Commande directe : `cd bot && python main.py`

### Règles de l'agent
- Quand l'utilisateur dit "fais ça", ne pas demander d'autorisation supplémentaire — agir directement.
- Le fichier `.agent_memory.md` a été déplacé dans `agent/` puis découpé en fichiers spécialisés pour limiter les pertes et hallucinations de données.
- La mémoire est divisée en 6 fichiers indépendants dans `agent/` : GOAL, rules, todo, architecture, memories, syntax.

## Historique des sessions récentes

### 2026-07-07 — Nettoyage projet
Suppression 12 golden reports obsolètes + 6 fichiers database/ superseded. Projet nettoyé de ses traces ChromaDB dead code.

### 2026-07-06 — Release v0.4.0-alpha + Phase 9 CLI
- Release v0.4.0-alpha complete : VERSION + CHANGELOG + README mis à jour
- Phase 3.5 V1 terminee: SQLite storage + Ollama embedding (zero service externe) + 36 tests passing
- Phase 10 Docker validatee: build/run/search cross-collection + mark complete
- Phase 9 CLI validatee : --file + --dir testés, MIME detection fix, auto-accept non-TTY, 62 tests passing
- Phase 8 Web crawling termine : cloudscraper CF bypass, PZ wiki extraction, cross-collection search verified
- Parser restructure + 27 files changed (sync post-commit)
- Docker ingestor fix, golden report CLI, parser B42 validation
- doctor repair mode + setup fresh machine install

### 2026-07-05 — Hardening + Phase 3.1 correction
- Correction bugs syntaxe + sécurité/config + gouvernance + 67 tests unitaires
- Golden set aligné + promote.py passe a 0.933 recall (promotion reussie)
- guard production + pre-ingest backup + rollback + CI security gate
- Phase 3.1: ingest.py metadata fix + promote.py golden set gate + SDK migration
- Fuzzy matching sync : normalisation accents/apostrophes/tirets + Levenshtein + _fuzzy_match() + 24 nouveaux tests
- todo.md sync Notion automatique

### 2026-07-04 — Phase 12 + Phase 6 + Steam module
- Phase 12 ajoutée : pipeline de génération de mods + sanity check cohérence projet
- Phase 6: Filtrage B41/B42 natif — game_version filtering, integre dans engine_client/pipeline/bot. 24 nouveaux tests, 84 total.
- Phase Steam + workshop + .pbo : nouveau module steam/ (path_discovery, library_folders, workshop_scanner, steamcmd_client), processeur .pbo, mod_ingester, 4 nouvelles collections, commandes CLI --steam-scan/--workshop-scan/--mod-ingest, tests 12/12
- Golden set recall@5 test suite (17 tests) + lock.py import fix + notion scripts cleanup

### 2026-07-02 — Foundation phases
- Phase 5+11 tests : golden set recall@5 (17/17) + StorageWriter unitaires (22/22), commit 1298527
- P0 audit remediation: fixed collection mapping in engine.py, async health checks in bot/main.py, DRY imports via _import_compat.py, heartbeat + stale lock recovery in governance/lock.py

## Session du 2026-07-07
Correction orthographe — ~170 accents diacritiques corrigés dans README, CHANGELOG, docs/, agent/, et annotations Python (modgen/)

## Session du 2026-07-07
Auto-sync: S1 infra + S2 schema commit, pz-agent Docker stack running, PostgreSQL 16+PostGIS with 16 tables + 5 views

## Session du 2026-07-07
feat: S3 LangGraph agent loop implementation — new ingestor/agent_core/ package with 6 files, state machine, validation levels, retry policy

## Session du 2026-07-07
S4-e pipeline ingest-pz-full + S4-f coverage-report — orchestrateur complet + rapport de couverture

## Session du 2026-07-08
daily auto-sync routine — post RuntimeWarning fixes, test suite analysis

## Session du 2026-07-08
S9: Migration SQLite→PostgreSQL-only — suppression sqlite_storage.py, refacto storage layer PG, migration 20+ callers, update docs