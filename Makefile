# Makefile — Orchestrateur complet du projet RAG Zomboid
# NOTE: nécessite Git Bash ou WSL2 (bash). Pas compatible CMD/PowerShell natif.
#
# Usage principal :
#   make install-hooks   # une fois, au premier clone
#   make ingest          # peuple db/staging/ depuis les sources
#   make test            # valide le golden set en dry-run
#   make promote         # gate staging → production (sans --force)
#   make promote-force   # gate avec --force (⚠)
#   make backup          # snapshot manuel de production
#   make restore         # restaure interactif
#   make rollback-latest # urgence
#   make tag             # git tag depuis VERSION
#   make serve           # lance le serveur MCP
#   make version         # affiche le contenu de VERSION

SHELL := /usr/bin/env bash
PYTHON := python3
.PHONY: help install-hooks ingest test promote promote-force backup restore rollback-latest tag serve version clean logs env-init mod-build mod-validate

# ── Variables ──────────────────────────────────────────────────────────────────
ROOT        := $(shell pwd)
VERSION     := $(shell cat $(ROOT)/VERSION 2>/dev/null || echo "0.0.0-unknown")
GIT_HOOKS   := $(ROOT)/.git/hooks
HOOK_SRC    := $(ROOT)/scripts/hooks/commit-msg

# Version par défaut pour ingest / promote
GAME_VERSION ?= b42

# ID de backup pour restore (surchargeable: make restore BACKUP_ID=...)
BACKUP_ID ?=

# ── Cibles ────────────────────────────────────────────────────────────────────

help:
	@echo "  =====  Projet RAG Zomboid — Makefile  ====="
	@echo ""
	@echo "  env-init        Initialise .env.unified (créé si absent)"
	@echo "  install-hooks   Copie commit-msg hook → .git/hooks/"
	@echo "  ingest          Lance ingestor/engine.py ingest"
	@echo "  test            python -m ingestor.promote --dry-run"
	@echo "  promote         Gate staging → production (recall ≥ 90 %)"
	@echo "  promote-force   Promouvoir même si recall < 90 % (⚠ WARN)"
	@echo "  backup          Snapshot manuel de db/production/"
	@echo "  restore         Restaurer un snapshot (BACKUP_ID=...)"
	@echo "  rollback-latest Restaurer le snapshot production le plus récent"
	@echo "  tag             Créer un git tag signé depuis VERSION"
	@echo "  serve           Lancer le serveur MCP"
	@echo "  version         Afficher le contenu de VERSION"
	@echo "  clean           Supprimer db/staging/ et logs/"
	@echo ""
	@echo "  ===== Variables d'environnement (voir .env.unified) ====="
	@echo "  [REQUIS]        DISCORD_TOKEN — sans ce .env, le bot ne démarre pas"
	@echo "  [DEFAUT]        OLLAMA_BASE_URL=http://host.docker.internal:11434"
	@echo "  [DEFAUT]        STORAGE_BACKEND=sqlite"
	@echo "  [OPTIONNEL]     CLAUDE_API_KEY — fallback LLM si Ollama indisponible"
	@echo "  [OPTIONNEL]     WORKSPACE_CHANNEL_ID — résolu auto si absent"
	@echo ""

env-init:
	@echo "  → Vérification de l'environnement..."
	@if [ ! -f "$(ROOT)/.env.unified" ]; then \
		echo "  📋 .env.unified inexistant → création avec valeurs par defaut"; \
		cat <<'EOF' > "$(ROOT)/.env.unified"
# .env.unified — toutes les variables du projet
DISCORD_TOKEN=ton_token_discord_ici
OLLAMA_BASE_URL=http://host.docker.internal:11434
STORAGE_BACKEND=postgresql
NOTION_API_KEY=ntn_XXXX
STEAM_USER=ranger_fleo
EOF
	else \
		echo "  ✅ .env.unified déjà présent"; \
	fi
	@echo ""
	@echo "  📌 Voir .env.unified pour la liste complète des variables."
	@echo "  📌 DISCORD_TOKEN est REQUIS — sans lui, le bot ne démarre pas."

install-hooks:
	@echo "  → Installation des git hooks..."
	@mkdir -p "$(GIT_HOOKS)"
	@cp "$(HOOK_SRC)" "$(GIT_HOOKS)/commit-msg"
	@chmod +x "$(GIT_HOOKS)/commit-msg"
	@echo "  ✅ commit-msg hook installé."

ingest:
	@echo "  → Ingestion des données (game_version=$(GAME_VERSION))..."
	@$(PYTHON) -m ingestor.engine ingest --game-version $(GAME_VERSION)

test:
	@echo "  → Test golden set (dry-run)..."
	@$(PYTHON) -m ingestor.promote --dry-run

promote:
	@echo "  → Gate de promotion staging → production..."
	@$(PYTHON) -m ingestor.promote

promote-force:
	@echo "  ⚠  Promotion FORCÉE (recall < 90 % autorisé)..."
	@$(PYTHON) -m ingestor.promote --force

backup:
	@echo "  → Snapshot manuel de production..."
	@$(PYTHON) -m ingestor.promote --dry-run 2>/dev/null || true
	@# Crée un backup brut (copie directe)
	@mkdir -p "$(ROOT)/backups"
	@TS=$(shell date +%Y%m%d-%H%M%S) && \
	  $(PYTHON) -c "\
import shutil, sys; \
from pathlib import Path; \
src=Path('$(ROOT)')/'db'/'production'; \
dst=Path('$(ROOT)')/'backups'/f'{sys.argv[1]}_manual_prod'; \
if src.exists(): shutil.copytree(src, dst, symlinks=True); \
print(f'  💾 Snapshot créé: {sys.argv[1]}_manual_prod')" "$$TS"

restore:
ifndef BACKUP_ID
	@$(PYTHON) -m backups.restore list
	@echo "  ℹ  Syntaxe: make restore BACKUP_ID=<id>"
	@exit 1
endif
	@echo "  → Restauration depuis $(BACKUP_ID)..."
	@$(PYTHON) -m backups.restore restore $(BACKUP_ID)

rollback-latest:
	@echo "  ⚡ Rollback vers le dernier snapshot production..."
	@$(PYTHON) -m backups.restore rollback-latest

tag:
	@echo "  → Création du git tag v$(VERSION)..."
	@git tag -a "v$(VERSION)" -m "Release v$(VERSION)" && \
	  echo "  ✅ Tag v$(VERSION) créé." || \
	  echo "  ❌ Échec (pas de repo git ou tag existant)."

serve:
	@echo "  → Lancement du serveur MCP..."
	@$(PYTHON) -m ingestor.mcp_server

version:
	@echo "  $(VERSION)"

clean:
	@echo "  → Nettoyage..."
	@rm -rf "$(ROOT)/db/staging" "$(ROOT)/logs"
	@echo "  ✅ db/staging/ et logs/ supprimés."

logs:
.PHONY: mod-build mod-validate

# ── Packaging de mods (Phase 12) ────────────────────────────────────────────

mod-build:
	@if [ -z "$(MOD_NAME)" ]; then echo "  Usage: make mod-build MOD_NAME=my-mod"; exit 1; fi
	@echo "  → Packaging du mod $(MOD_NAME) en ZIP..."
	@cd $(MOD_NAME) && zip -r ../mods/$(MOD_NAME).zip . && cd ..
	@echo "  ✅ ZIP cree: mods/$(MOD_NAME).zip"

mod-validate:
	@if [ -z "$(MOD_DIR)" ]; then echo "  Usage: make mod-validate MOD_DIR=path/to/mod"; exit 1; fi
	@python -m src.modgen validate $(MOD_DIR)
	@echo "  ===== Logs ====="
	@echo "  promote:"
	@tail -30 "$(ROOT)/logs/promote.log" 2>/dev/null || echo "  (vide)"
	@echo ""
	@echo "  restore:"
	@tail -30 "$(ROOT)/logs/restore.log" 2>/dev/null || echo "  (vide)"

