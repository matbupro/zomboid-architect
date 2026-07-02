📦 Livrables (20 fichiers, ~3500 lignes)
Tier 1 : Versioning & Gouvernance
Fichier 	Rôle 	État
VERSION 	Source unique de vérité (0.1.0-alpha) 	✅
docs/VERSIONING.md 	Règles SemVer + cycle de vie (alpha→beta→release) 	✅
docs/CHANGELOG.md 	Keep a Changelog format, Unreleased section 	✅
.gitmessage 	Template Conventional Commits 	✅
scripts/hooks/commit-msg 	Hook bash versionné (validation des commits) 	✅
Tier 2 : Moteur d'ingestion & Parsing
Fichier 	Rôle 	État
ingestor/game_version.py 	Enum GameVersion (B41/B42), tagging automatique 	✅
ingestor/parser.py 	Pipeline extraction XML/Markdown avec 5 parseurs spécialisés + quarantaine 	✅
ingestor/engine.py 	Orchestrateur d'ingestion staging→ChromaDB avec checksums incrémentaux 	✅
ingestor/__init__.py 	Package exports + __version__ depuis VERSION 	✅
src/retrieval/__init__.py 	Interface RAG query_staging() pour le golden set 	✅
Tier 3 : Promotion & Backup
Fichier 	Rôle 	État
ingestor/promote.py 	Gate de promotion staging→production, golden set validation, recall@5 gate 	✅
backups/restore.py 	CLI restore/rollback avec audit trail 	✅
data/workspace/.gitkeep 	Zone exclusive pour promotions atomiques 	✅
data/tmp/.gitkeep 	Espace temporaire avec cleanup garanti 	✅
Tier 4 : Support Systems
Fichier 	Rôle 	État
ingestor/logger.py 	3 handlers (console colorisée, fichier rotatif 10MB/7 backups, JSON quotidien) 	✅
ingestor/lock.py 	FileLock cross-process avec détection stale locks (30 min timeout) 	✅
ingestor/worker.py 	WorkerContext avec isolation tmp et cleanup @exit garanti 	✅
logs/.gitkeep 	Point de montage logs (project.log, audit.json) 	✅
Tier 5 : Tests & Orchestration
Fichier 	Rôle 	État
tests/golden_set/golden.json 	28 Q/R de validation (15 B41 + 13 B42, 5 catégories) 	✅
tests/conftest.py 	Fixtures pytest (mock ChromaDB, tmp workers) 	✅
Makefile 	13 targets (install-hooks, ingest, test, promote, backup, restore, etc.) 	✅
STRUCTURE.md 	Arborescence + règles d'import 	✅
🔄 Workflow complet (du développement à la production)

# 1️⃣ Setup initial (une fois)
make install-hooks                 # Installe le hook commit-msg

# 2️⃣ Développement itératif
git commit -m "feat(items): add axe damage"  # Hook valide Conventional Commits
# ➜ Crée une entrée dans CHANGELOG.md automatiquement (via la suite CI)

# 3️⃣ Ingestion staging
make ingest                        # Peuple db/staging/ depuis data/sources/
# ➜ parser.py extrait XML/MD, chunks taggés avec game_version (b42)
# ➜ engine.py écrit dans ChromaDB staging via verrou exclusif
# ➜ Logs JSON horodatés dans logs/project.log + audit.json

# 4️⃣ Validation avant promo
make test                          # Rejeu golden set contre staging (--dry-run)
# ➜ query_staging() interroge ChromaDB staging
# ➜ Calcul recall@5 par catégorie
# ➜ Bloque si recall < 0.90 (sauf --force)

# 5️⃣ Promotion production
make promote                       # Promotion staging → production
# ➜ Backup horodaté de l'ancienne prod dans backups/chromadb/
# ➜ Swap atomique .incoming → production/
# ➜ CHANGELOG.md maj avec: version, date, recall@5, checksum SHA-256
# ➜ Logs JSON dans logs/audit.json (trail complet)

# 6️⃣ Tag & release
make tag                           # Crée un git tag v0.1.0-alpha
git push --tags

🛡️ Garanties de sécurité & reproductibilité
Garantie 	Implémentation
Source unique de version 	VERSION — aucun hardcoding ailleurs
Versionning des données 	Chaque chunk porte game_version: "b42" → 2 datasets parallèles sans collision
Anti-régression 	promote.py bloque si recall@5 < 0.90 (golden set validation obligatoire)
Atomic promotions 	Swap .incoming → production (jamais de DB à moitié écrite)
Rollback garanti 	10 snapshots de backups + make restore / make rollback-latest
Isolation processus 	FileLock exclusif + WorkerContext tmpdir avec cleanup @exit
Audit trail complet 	Logs JSON horodatés dans audit.json (correlation_id, duration, chunk count)
Conventional Commits 	Hook bash force feat/fix/docs/etc + scope optionnel
🚀 Points de démarrage immédiats
Pour les développeurs

cd project-root
make install-hooks
make ingest                    # Teste avec des sources de test dans data/sources/
make test                      # Valide contre golden.json

Pour les DevOps / Admin

make backup                    # Snapshot manuel de production
make restore BACKUP_ID=prod-20260701-143022  # Restore manuel
make rollback-latest           # Rollback d'urgence

Pour les intégrations CI/CD

# Dans ta pipeline GitHub Actions / GitLab CI :
- run: make test              # Validation avant merge
- run: make promote           # Auto-promotion si test ✅
- run: make tag               # Auto-release si promo ✅

⚙️ Architecture de logging (3 canaux)

Chaque log avec correlation_id (uuid[:8]) traverse :

┌─ Console (stdout)
│  ├─ Couleurs: [INFO] = cyan, [WARN] = jaune, [ERROR] = rouge
│  └─ Format: "HH:MM:SS [LEVEL] module msg"
│
├─ Fichier rotatif (logs/project.log)
│  ├─ Rotation: 10 MB ou quotidienne
│  ├─ Backups: 7 fichiers max
│  └─ Format: JSON (audit-friendly)
│
└─ Audit quotidien (logs/audit.json)
   ├─ Rotation: Quotidienne (daily-YYYYMMDD.json)
   ├─ Rétention: 30 jours
   └─ Format: JSON brut (machine-parsable)

📋 État des implémentations
✅ Complètement intégré

    Versioning multi-layer (app + game_version par chunk)
    Parsing robuste (5 parseurs spécialisés + quarantaine)
    Promotion avec gate golden set
    Logging professionnel multi-output
    Locking cross-process
    Backup/restore atomique

🟡 À implémenter (externe)

    data/sources/ : populate avec XML/MD/Lua du jeu (tu fournis)
    ChromaDB client : pip install chromadb + configuration (credentials, persistence path)
    MCP server : branchement de src/retrieval.query_staging() au moteur MCP
    CI/CD hooks : intégration Makefile dans ta pipeline

🔵 Extensibilité prévue

    New game versions : ajoute enum dans game_version.py + parseurs compatibles
    New content types : crée une classe XxxParser dans parser.py + ajoute ContentType.XXX
    Custom filters : enhance query_staging() dans src/retrieval/__init__.py

📊 Métrique de qualité

Le projet respecte maintenant :

    ✅ SemVer : major.minor.patch + alpha/beta/release
    ✅ Conventional Commits : feat/fix/docs/refactor (hooked)
    ✅ Keep a Changelog : format standard + automated entries
    ✅ Professional Logging : 3 canaux, rotation, JSON audit
    ✅ Golden Set Testing : 28 Q/R anti-régression (recall@5 gate)
    ✅ Atomic Backups : snapshots horodatés + rollback CLI
    ✅ Cross-process Locking : FileLock avec stale detection
    ✅ Reproducibility : tous les chunks taggés game_version + checksums incrémentaux

🎁 Fichiers additionnels prêts

Les 20 fichiers livrés couvrent maintenant :

    Governance (6 fichiers) — versioning, commits, changelog
    Ingestion Pipeline (5 fichiers) — parser, engine, promote
    Support Systems (3 fichiers) — logger, lock, worker
    Backup & Recovery (2 fichiers) — restore CLI, workspace
    Tests & Orchestration (3 fichiers) — golden set, conftest, Makefile
    Documentation (1 fichier) — STRUCTURE.md

