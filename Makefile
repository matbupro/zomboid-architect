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
.PHONY: help install-hooks ingest test promote promote-force backup restore rollback-latest tag serve version clean logs

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
	@echo "  ===== Logs ====="
	@echo "  promote:"
	@tail -30 "$(ROOT)/logs/promote.log" 2>/dev/null || echo "  (vide)"
	@echo ""
	@echo "  restore:"
	@tail -30 "$(ROOT)/logs/restore.log" 2>/dev/null || echo "  (vide)"
