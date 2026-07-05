# Agent Autonome de Production de Mods Project Zomboid

## Architecture Technique Complete -- Production Grade

> **Stack recommande** : PostgreSQL + Qdrant + MinIO + Gitea + Redis
> **Serveur PZ** : Dedicated headless en Docker (steamcmd app 380870)
> **Linting Lua** : luacheck
> **Orchestration** : LangGraph (state machine)
> **Principe directeur** : le coeur du projet est la boucle **generate -> test-in-PZ -> fix -> version**, pas une base de connaissances geante.

---

## Table des Matieres

1. [Introduction et Vision](#introduction)
2. [A. Boucle Agentique Complete](#section-a)
3. [B. Environnement de Test PZ Headless en Docker](#section-b)
4. [C. Schema PostgreSQL Complet du Pipeline de Production de Mods](#section-c)
5. [D. Structure Type d'un Mod PZ](#section-d)
6. [Synthese et Principes Cles](#synthese)

---

## Introduction et Vision

### Contexte

Ce document decrit l'architecture technique complete d'un **agent IA autonome dedie a la production de mods Project Zomboid en environnement de production**. Il ne s'agit pas d'un simple moteur de recherche de connaissances autour de PZ, mais d'une **usine a mods pilotee par IA** capable de comprendre, concevoir, generer, tester, valider, corriger, versionner et publier des mods fonctionnels.

### Definition du probleme

Un mod Project Zomboid peut echouer de nombreuses facons :

- Erreurs de syntaxe Lua fatales au demarrage
- Conflits avec d'autres mods (ID d'item duplique, surcharge de functions)
- Incompatibilites entre build (41 vs 42)
- Repertoires mal nommes (media/ vs media/) -> le mod ne charge pas
- Fichiers de traduction absents ou corrompus
- Recipes sans ingredients valides
- Erreurs runtime qui crashent le serveur
- Mod.info malformed -> le mod n'apparait pas dans la liste

Le risque principal d'un agent de generation de mods est donc : **produire du code plausible mais dysfonctionnel**.

### Principe de conception

Le stockage (PostgreSQL, Qdrant, MinIO) est un **outil au service de la boucle agentique**, pas le coeur du systeme. Le coeur est la boucle :

```
Generation -> Test dans PZ headless -> Detection d'erreur -> Correction -> Validation -> Versioning -> Publication
```

Chaque iteration de cette boucle produit un artifact de mod testable, horodate et tracable.

### Stack technique retenu

| Composant | Role | Justification |
|-----------|------|---------------|
| **PostgreSQL 16** | Source de verite, metadonnees, pipeline | ACID, JSONB, contraintes, transactions |
| **Qdrant** | Recherche vectorielle des connaissances PZ | Embeddings semantiques pour contexte |
| **MinIO** | Stockage objet (assets, posters, zips de mods) | Compatible S3, versioning natif |
| **Gitea** | Git auto-heberge pour repos de mods | CI/CD integre, review code |
| **Redis** | Cache de session, queue de taches, state agent | Latence faible |
| **PZ Dedicated Server (Docker)** | Environnement de test headless | Isolation, reproductibilite |
| **luacheck** | Analyse statique Lua | Erreurs de syntaxe, variables non utilisees |
| **LangGraph** | Orchestration multi-agents stateful | Branching conditionnel, retry, human-in-the-loop |

---

## A. Boucle Agentique Complete {#section-a}

### A.1 Architecture Multi-Agents

Le systeme est compose de **5 agents speciaux** orchestres par une state machine LangGraph :

| Agent | Role principal | Inputs | Outputs |
|-------|---------------|--------|---------|
| **Planner** | Comprend la demande, choisit la strategie, planifie les fichiers a generer | Demande utilisateur, contexte du projet, KB PZ | Plan d'action detaille |
| **Builder** | Genere le code Lua, scripts, structures de fichiers | Plan du Planner, templates valides, contexte PZ | Fichiers mod bruts |
| **Validator** | Execute les validations niveau 1-4 dans l'ordre | Fichiers du Builder | Rapport de validation structure |
| **Fixer** | Analyse les erreurs, propose et applique des corrections | Rapport du Validator | Mod corrige |
| **Packager** | Assemble le .zip final, commit Gitea, upload MinIO, genere le rapport | Mod valide, version | Artifact livrable + commit Git |

### A.2 Diagramme d'Etat LangGraph

```text
+---------+    start    +----------+
|  START  |------------>| PLANNING |
+---------+             +----+-----+
                           |
                  +--------v--------+
                  |   BUILDING      |
                  +--------+--------+
                           |
                  +--------v--------+
         +---------|  VALIDATING    |
         |         +--------+--------+
         |                  |
         |           +------+------+
         |           |             |
     +---+---+   +---+---+    +---+---+
     | ERROR |   | FIX   |    | PACK  |
     +---+---+   +---+---+    +---+---+
         |          |             |
    retry<5?    retry<5?    +-----+------+
         |          |        | HUMAN_OK   |
    +----+----+  +---+------+ | (si RED)  |
    | ESCALATE|  |RETRY     | +-----+------+
    +---------+  +----------+         |
                               +---+---+
                               | END   |
                               +-------+
```

### A.3 Squelette LangGraph Complet

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional
from enum import Enum

class AgentStatus(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    BUILDING = "building"
    VALIDATING = "validating"
    FIXING = "fixing"
    PACKAGING = "packaging"
    ESCALATED = "escalated"
    DONE = "done"
    FAILED = "failed"

class ModAgentState(TypedDict):
    user_request: str
    project_id: Optional[str]
    build_target: str
    run_id: str
    status: AgentStatus
    retry_count: int
    max_retries: int
    plan: Optional[dict]
    generated_files: dict
    validation_results: list[dict]
    errors: list[dict]
    fixed_files: dict
    artifact_id: Optional[str]
    commit_sha: Optional[str]
    minio_url: Optional[str]
    report: Optional[dict]
    governance_tier: str

MAX_RETRIES = 5

def get_next_node(state: ModAgentState) -> str:
    if state["status"] == "ESCALATED": return END
    if state["status"] == "DONE": return END
    if state["status"] == "FAILED": return END
    if state["status"] == "VALIDATING":
        if state["errors"]:
            return "escalate_node" if state["retry_count"] >= MAX_RETRIES else "fixing_node"
        return "packaging_node"
    if state["status"] == "FIXING": return "validating_node"
    if state["status"] == "PLANNING": return "building_node"
    if state["status"] == "BUILDING": return "validating_node"
    if state["status"] == "PACKAGING": return END
    return END

graph = StateGraph(ModAgentState)
graph.add_node("planning_node", planning_agent)
graph.add_node("building_node", building_agent)
graph.add_node("validating_node", validating_agent)
graph.add_node("fixing_node", fixing_agent)
graph.add_node("packaging_node", packaging_agent)
graph.add_node("escalate_node", escalation_agent)
graph.add_edge("planning_node", "building_node")
graph.add_edge("building_node", "validating_node")
graph.add_edge("fixing_node", "validating_node")
graph.add_edge("packaging_node", END)
graph.add_edge("escalate_node", END)
graph.add_conditional_edges("validating_node", get_next_node, {
    "fixing_node": "fixing_node",
    "packaging_node": "packaging_node",
    "escalate_node": "escalate_node",
    END: END,
})
compiled_graph = graph.compile()
```

### A.4 Pseudocode de la Boucle Complete

```text
FONCTION boucle_agent_mod(request, build_target):

    run_id = generate_run_id()
    state = init_state(run_id, request, build_target)

    ETAPE 1: PLANNING
    +- Parser la demande utilisateur
    +- Interroger Qdrant pour contexte semantique
    +- Interroger PostgreSQL pour projets existants + dependances
    +- Generer plan : fichiers a creer, templates a utiliser
    +- Sauvegarder plan dans agent_runs(run_id).plan

    ETAPE 2: BUILDING
    +- Pour chaque fichier du plan :
    |   +- Charger template (items.txt, recipes, lua)
    |   +- Remplir avec donnees du plan + contexte KB
    |   +- Injecter metadonnees (auteur, version, timestamp)
    |   +- Ecrire fichier dans workspace/{run_id}/
    +- Generer arborescence complete du mod
    +- Sauvegarder fichiers dans mod_files(run_id)

    ETAPE 3: VALIDATION NIVEAU 1 (Statique)
    +- luacheck sur tous les .lua du mod
    +- Verifier arborescence (media/scripts, media/lua, mod.info)
    +- Valider mod.info schema (id, name, description, poster)
    +- Verifier absence de duplicate item names
    +- Si erreurs -> ajouter a state.errors, RETOUR a FIXING

    ETAPE 4: VALIDATION NIVEAU 2 (Boot)
    +- Demarrer container PZ headless
    +- Monter le mod dans /pz-server/mods/
    +- Lancer servertest.ini avec le mod active
    +- Capturer sortie console + logs/ et lua/
    +- Detecter erreurs Lua fatales (OnGameBoot errors)
    +- Si crash -> extraire stack trace, RETOUR a FIXING

    ETAPE 5: VALIDATION NIVEAU 3 (Runtime Headless)
    +- Demarrer serveur dedie avec le mod charge
    +- Executer script de test fonctionnel
    +- Attendre 60 secondes, capturer logs
    +- Detecter stack traces, erreurs runtime
    +- Verifier que les evenements se declenchent
    +- Si runtime error -> RETOUR a FIXING

    ETAPE 6: VALIDATION NIVEAU 4 (Fonctionnel)
    +- Connexion headless au serveur en tant que joueur test
    +- Executer scenario de test :
    |   +- Item existe-t-il en jeu ?
    |   +- Recipe apparait-il dans le menu ?
    |   +- Evenement se declenche-t-il ?
    |   +- Craft produit-il l'item attendu ?
    +- Capturer screenshots headless (optionnel)
    +- Si echec -> RETOUR a FIXING

    ETAPE 7: PACKAGING
    +- Determiner governance_tier (GREEN/ORANGE/RED)
    +- Creer archive .zip du mod
    +- Upload MinIO : mods/{project_id}/{version}.zip
    +- Commit Gitea : git add + git commit + git push
    +- Si tier = RED -> ne pas merge vers main, creer PR
    +- Si tier = ORANGE -> reviewer notifie
    +- Si tier = GREEN -> merge auto vers main

    ETAPE 8: RAPPORT
    +- Generer rapport Markdown avec resultats de validation
    +- Sauvegarder dans publish_log
    +- Envoyer notification (Discord/Slack)
    +- Retourner resume a l'utilisateur

    RETOURNER result_state
FIN FONCTION
```

### A.5 Politique de Retry et Escalade

```python
RETRY_POLICY = {
    "max_attempts": 5,
    "backoff_multiplier": 2,
    "initial_delay_seconds": 5,
    "escalation_on": [
        "syntax_error_after_5_retries",
        "runtime_crash_after_5_retries",
        "api_misuse_detected",
        "security_policy_violation",
        "dependency_conflict_unresolvable",
    ],
    "human_escalation_required_for": [
        "new_mod_requires_steam_workshop_upload",
        "mod_modifies_core_game_files",
        "external_api_key_required",
        "dependency_on_proprietary_mod",
    ],
}

def should_escalate(state: ModAgentState) -> bool:
    if state["retry_count"] >= MAX_RETRIES: return True
    for error_type in RETRY_POLICY["escalation_on"]:
        if error_type in [e["type"] for e in state["errors"]]: return True
    return False
```

### A.6 Gouvernance et Niveaux de Securite

| Niveau | Tier | Declencheur | Actions autorisees | Actions bloquees |
|--------|------|------------|--------------------|--------------------|
| GREEN | **GREEN** | Code Lua genere, lint passe, tests boot+runtime OK | Merge auto, upload MinIO, commit | Publication Steam Workshop |
| ORANGE | **ORANGE** | Mod avec nouvelles recettes, modification d'items existants | Commit vers branche PR, reviewer notifie | Merge vers main, upload MinIO |
| RED | **RED** | Mod qui modifie des fichiers core du jeu, dependence externe, >3 fixes requis | Creation de PR, alerte humain | Merge, publication, modification fichiers systeme |

---

## B. Environnement de Test PZ Headless en Docker {#section-b}

### B.1 Dockerfile du Serveur PZ Headless

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive     STEAMCMD_DIR=/steamcmd     PZ_SERVER_DIR=/pz-server     PZ_APP_ID=380870     LANG=en_US.UTF-8     LC_ALL=en_US.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends     wget gnupg curl ca-certificates lib32gcc-s1     tar xz-utils locales python3 python3-pip     lua5.3 luajit     && locale-gen en_US.UTF-8     && apt-get clean     && rm -rf /var/lib/apt/lists/*

RUN mkdir -p ${STEAMCMD_DIR}     && useradd -m -u 1000 pzuser

WORKDIR ${STEAMCMD_DIR}
RUN wget -q https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz     && tar -xzf steamcmd_linux.tar.gz     && rm steamcmd_linux.tar.gz

# Build 41 stable
RUN su pzuser -c "${STEAMCMD_DIR}/steamcmd.sh +login anonymous     +force_install_dir ${PZ_SERVER_DIR} +app_update ${PZ_APP_ID} validate +quit"

# Build 42 beta (decommenter si besoin)
# RUN su pzuser -c "${STEAMCMD_DIR}/steamcmd.sh +login anonymous #     +force_install_dir ${PZ_SERVER_DIR} +app_update ${PZ_APP_ID} -beta bleeding0 validate +quit"

RUN mkdir -p ${PZ_SERVER_DIR}/mods     ${PZ_SERVER_DIR}/logs ${PZ_SERVER_DIR}/lua ${PZ_SERVER_DIR}/servermods

COPY --chown=pzuser:pzuser entrypoint.sh ${PZ_SERVER_DIR}/entrypoint.sh
RUN chmod +x ${PZ_SERVER_DIR}/entrypoint.sh

WORKDIR ${PZ_SERVER_DIR}
USER pzuser
EXPOSE 16261/udp 16262/udp 27015/udp
ENTRYPOINT ["/pz-server/entrypoint.sh"]
```

```bash
#!/bin/bash
# entrypoint.sh -- Lance le serveur PZ en mode headless avec mod injecte

set -e
MOD_ID="${1:-testmod}"
BUILD_TARGET="${2:-41}"

echo "[PZ-HEADLESS] Starting server for mod: $MOD_ID (build: $BUILD_TARGET)"

cat > servertest.ini <<INICONF
[General]
LoadProgress=0

[Steam]
AutoLogin=1

[Server]
MaxPlayers=1
Port=16261
ResetPassword=password123
RconPassword=rcontest123
ServerName=PZ-AgentTest
PauseEmpty=true
Mods=${MOD_ID}
WorkshopItems=
INICONF

./start-server.sh servertest.ini -noSteam -noGUI > /tmp/pz_console.log 2>&1 &
PZ_PID=$!

echo "[PZ-HEADLESS] Server PID: $PZ_PID"
sleep 15

timeout 60 tail -f /pz-server/Zomboid/logs/*.lua 2>/dev/null || true
cp -r /pz-server/Zomboid/logs /tmp/pz_logs/ 2>/dev/null || true
kill $PZ_PID 2>/dev/null || true
echo "[PZ-HEADLESS] Server stopped. Logs available in /tmp/"
```

### B.2 docker-compose pour le Pipeline Complet

```yaml
version: "3.9"

services:
  postgres:
    image: postgis/postgis:16-3.4
    container_name: pz-agent-postgres
    environment:
      POSTGRES_DB: pz_agent
      POSTGRES_USER: pz_agent
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U pz_agent -d pz_agent"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant:v1.7.4
    container_name: pz-agent-qdrant
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/health"]
      interval: 15s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  minio:
    image: minio/minio:latest
    container_name: pz-agent-minio
    environment:
      MINIO_ROOT_USER: ${MINIO_USER:-pzagent}
      MINIO_ROOT_PASSWORD: ${MINIO_PASSWORD:?Set MINIO_PASSWORD}
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio_data:/data
    command: server /data --console-address ":9001"
    restart: unless-stopped

  gitea:
    image: gitea/gitea:1.21
    container_name: pz-agent-gitea
    environment:
      - USER_UID=1000
      - USER_GID=1000
      - GITEA__database__DB_TYPE=postgres
      - GITEA__database__HOST=postgres:5432
      - GITEA__database__NAME=gitea
      - GITEA__database__USER=gitea
      - GITEA__database__PASSWD=${POSTGRES_PASSWORD}
    ports:
      - "3000:3000"
      - "2222:22"
    volumes:
      - gitea_data:/data
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: pz-agent-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    restart: unless-stopped

  pz-headless:
    build:
      context: ./pz-server
      dockerfile: Dockerfile.pz-headless
    container_name: pz-agent-pzserver
    volumes:
      - ./workspace:/workspace
      - pz_mods:/pz-server/mods
      - pz_logs:/tmp/pz_logs
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - pz-agent-net
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 8G
        reservations:
          cpus: "2"
          memory: 4G
    stop_grace_period: 30s
    restart: "no"

networks:
  pz-agent-net:
    driver: bridge

volumes:
  postgres_data:
  qdrant_data:
  minio_data:
  gitea_data:
  redis_data:
  pz_mods:
  pz_logs:
```

### B.3 Injection d'un Mod dans le Serveur

```bash
#!/bin/bash
MOD_ID="MyAwesomeMod"
MOD_ZIP="/workspace/mods/${MOD_ID}.zip"
PZ_SERVER_MODS="/pz-server/mods"

echo "[INJECT] Extracting mod: $MOD_ID"

if [ ! -f "$MOD_ZIP" ]; then
    echo "[ERROR] Mod zip not found: $MOD_ZIP"
    exit 1
fi

mkdir -p "${PZ_SERVER_MODS}/${MOD_ID}"
unzip -q "$MOD_ZIP" -d "${PZ_SERVER_MODS}/${MOD_ID}"

if [ ! -f "${PZ_SERVER_MODS}/${MOD_ID}/mod.info" ]; then
    echo "[ERROR] mod.info not found in extracted mod"
    exit 1
fi

echo "[INJECT] Mod extracted successfully"
echo "[INJECT] Contents:"
ls -la "${PZ_SERVER_MODS}/${MOD_ID}/"

cat > /pz-server/servertest.ini <<INICONF
[General]
LoadProgress=0

[Steam]
AutoLogin=1

[Server]
MaxPlayers=1
Port=16261
ResetPassword=password123
RconPassword=rcontest123
ServerName=PZ-AgentValidation
PauseEmpty=true
Mods=${MOD_ID}
WorkshopItems=
INICONF

echo "[INJECT] servertest.ini configured with Mods=${MOD_ID}"
```

### B.4 Les 4 Niveaux de Validation

#### Niveau 1 -- Validation Statique

```python
import subprocess
from pathlib import Path

def validate_level1(mod_path: Path) -> dict:
    errors = []
    warnings = []

    # 1. luacheck sur tous les .lua
    lua_files = list(mod_path.rglob("*.lua"))
    for lua_file in lua_files:
        result = subprocess.run(
            ["luacheck", "--codes", str(lua_file)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            errors.append({
                "file": str(lua_file),
                "type": "lua_syntax_error",
                "output": result.stdout,
            })

    # 2. Verifier mod.info existe et est valide
    mod_info = mod_path / "mod.info"
    if not mod_info.exists():
        errors.append({"type": "missing_mod_info"})
    else:
        content = mod_info.read_text()
        required_fields = ["id", "name", "description", "poster"]
        for field in required_fields:
            if field not in content:
                errors.append({"type": "missing_field", "field": field})

    # 3. Verifier arborescence obligatoire
    required_dirs = ["media/lua/shared", "media/scripts", "media/textures"]
    for req_dir in required_dirs:
        if not (mod_path / req_dir).exists():
            warnings.append({"type": "missing_directory", "path": req_dir})

    return {
        "level": 1,
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "files_checked": len(lua_files),
    }
```

#### Niveau 2 -- Validation Boot

```python
import subprocess
import time
import re

def validate_level2(mod_id: str, mod_path: Path) -> dict:
    inject_mod(mod_id, mod_path)

    process = subprocess.Popen(
        ["./start-server.sh", "servertest.ini", "-noSteam", "-noGUI"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    boot_output = []
    start_time = time.time()
    BOOT_TIMEOUT = 120

    try:
        for line in process.stdout:
            boot_output.append(line)
            if time.time() - start_time > BOOT_TIMEOUT:
                process.kill()
                return {"level": 2, "passed": False, "error": "Boot timeout after 120s"}
            if re.search(r"Lua error|error loading|script error", line, re.I):
                return {"level": 2, "passed": False, "error": f"Lua error detected: {line}"}
            if "OnGameBoot" in line or "server started" in line.lower():
                break
    finally:
        process.kill()

    return {"level": 2, "passed": True, "boot_time_seconds": time.time() - start_time}
```

#### Niveau 3 -- Validation Runtime Headless

```python
def validate_level3(mod_id: str) -> dict:
    test_script = (
        f"Events.OnGameBoot.Add(function() "
        f'print("[TEST] OnGameBoot fired for {mod_id}"); '
        f"end)"
    )

    runtime_logs = run_pz_server_with_test_script(test_script, timeout=90)

    errors = [line for line in runtime_logs
              if re.search(r"stack trace|error:|exception", line, re.I)]

    return {
        "level": 3,
        "passed": len(errors) == 0,
        "runtime_errors": errors,
        "log_lines": len(runtime_logs),
    }
```

#### Niveau 4 -- Validation Fonctionnelle

```python
def validate_level4(mod_id: str, expected_items: list, expected_recipes: list) -> dict:
    results = {"level": 4, "passed": True, "tests": {}}

    rcon = RCONClient("localhost", 16261, "rcontest123")

    response = rcon.send("lua all print(getItemDragged('Base.%s_item') and 'EXISTS' or 'MISSING')" % mod_id)
    results["tests"]["item_exists"] = "EXISTS" in response
    if not results["tests"]["item_exists"]: results["passed"] = False

    response = rcon.send("lua all print(hasRecipe('%s_recipe') and 'EXISTS' or 'MISSING')" % mod_id)
    results["tests"]["recipe_visible"] = "EXISTS" in response
    if not results["tests"]["recipe_visible"]: results["passed"] = False

    response = rcon.send("lua all testCraft('%s_recipe')" % mod_id)
    results["tests"]["craft_works"] = "SUCCESS" in response
    if not results["tests"]["craft_works"]: results["passed"] = False

    rcon.disconnect()
    return results
```

### B.5 Build 41 vs Build 42 -- Differences Cles

| Aspect | Build 41 | Build 42 |
|--------|----------|----------|
| **Structure des dossiers** | media/scripts/, media/lua/ (flat) | media/scripts/, media/lua/shared/client/server |
| **API Lua** | Modifie progressivement | Nouvelles mecaniques (survival, competences) |
| **SteamCMD beta** | `steamcmd +app_update 380870` (stable) | `+app_update 380870 -beta bleeding0` |
| **Version min** | `versionMin=41` | `versionMin=42` |

```bash
# Build 41 stable
steamcmd.sh +login anonymous +force_install_dir /pz-server +app_update 380870 validate +quit

# Build 42 beta (bleeding edge)
steamcmd.sh +login anonymous +force_install_dir /pz-server +app_update 380870 -beta bleeding0 validate +quit
```

### B.6 Isolation et Limites de Ressources

```yaml
pz-headless:
  deploy:
    resources:
      limits:
        cpus: "4"
        memory: 8G
      reservations:
        cpus: "2"
        memory: 4G
  ulimits:
    nofile:
      soft: 65536
      hard: 65536
    nproc:
      soft: 4096
      hard: 4096
  network_mode: pz-agent-net
  stop_grace_period: 30s
  restart: "no"
```

---

## C. Schema PostgreSQL Complet du Pipeline de Production de Mods {#section-c}

### C.1 DDL Complet

```sql
-- SCHEMA : pz_agent -- Agent Autonome de Production de Mods PZ
-- PostgreSQL 16+ avec PostGIS, JSONB, UUID, Ranges

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ENUMERATIONS
CREATE TYPE agent_status AS ENUM (
    'pending', 'planning', 'building', 'validating_l1',
    'validating_l2', 'validating_l3', 'validating_l4',
    'fixing', 'packaging', 'done', 'failed', 'escalated', 'cancelled'
);

CREATE TYPE validation_level AS ENUM (
    'l1_static', 'l2_boot', 'l3_runtime', 'l4_functional'
);

CREATE TYPE validation_result AS ENUM (
    'passed', 'failed', 'warning', 'error', 'skipped'
);

CREATE TYPE governance_tier AS ENUM ('green', 'orange', 'red');
CREATE TYPE build_target AS ENUM ('build41', 'build42', 'both');
CREATE TYPE publish_status AS ENUM ('draft', 'review', 'approved', 'published', 'deprecated');
CREATE TYPE dependency_type AS ENUM ('requires', 'recommends', 'suggests', 'conflicts', 'provides');

-- TABLE : mod_projects
CREATE TABLE mod_projects (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mod_id          VARCHAR(128) NOT NULL UNIQUE,
    name            VARCHAR(256) NOT NULL,
    description     TEXT,
    author          VARCHAR(128) DEFAULT 'AgentAI',
    version         VARCHAR(32) DEFAULT '1.0.0',
    build_target    build_target DEFAULT 'build42',
    publish_status  publish_status DEFAULT 'draft',
    poster_url      VARCHAR(512),
    workshop_id     BIGINT,
    git_repo        VARCHAR(256),
    total_runs      INTEGER DEFAULT 0,
    success_count   INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    last_run_at     TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    CONSTRAINT mod_id_format CHECK (mod_id ~ '^[A-Za-z0-9_.-]+$')
);

CREATE INDEX idx_mod_projects_status ON mod_projects(publish_status);
CREATE INDEX idx_mod_projects_git_repo ON mod_projects(git_repo) WHERE git_repo IS NOT NULL;
CREATE INDEX idx_mod_projects_search ON mod_projects USING gin(name gin_trgm_ops);

-- TABLE : agent_runs
CREATE TABLE agent_runs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE SET NULL,
    run_number      SERIAL,
    run_label       VARCHAR(128),
    status          agent_status DEFAULT 'pending',
    governance_tier governance_tier DEFAULT 'green',
    plan            JSONB DEFAULT '{}',
    build_target    build_target DEFAULT 'build42',
    user_request    TEXT NOT NULL,
    context_chunks  JSONB DEFAULT '[]',
    retry_count     INTEGER DEFAULT 0,
    max_retries     INTEGER DEFAULT 5,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    errors          JSONB DEFAULT '[]',
    error_summary   TEXT,
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE SET NULL,
    assigned_to     VARCHAR(128),
    CONSTRAINT unique_run_per_project UNIQUE (project_id, run_number)
);

CREATE INDEX idx_agent_runs_project ON agent_runs(project_id);
CREATE INDEX idx_agent_runs_status ON agent_runs(status);
CREATE INDEX idx_agent_runs_started ON agent_runs(started_at DESC);
CREATE INDEX idx_agent_runs_tier ON agent_runs(governance_tier);

-- TABLE : mod_artifacts
CREATE TABLE mod_artifacts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    version         VARCHAR(32) NOT NULL,
    checksum        VARCHAR(64),
    file_count      INTEGER DEFAULT 0,
    total_size_bytes BIGINT DEFAULT 0,
    minio_path      VARCHAR(512),
    minio_url       VARCHAR(1024),
    commit_sha      VARCHAR(40),
    git_branch      VARCHAR(128),
    validation_summary JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_artifact_per_run_version UNIQUE (run_id, version)
);

CREATE INDEX idx_mod_artifacts_run ON mod_artifacts(run_id);
CREATE INDEX idx_mod_artifacts_minio ON mod_artifacts(minio_path) WHERE minio_path IS NOT NULL;
CREATE INDEX idx_mod_artifacts_git ON mod_artifacts(commit_sha) WHERE commit_sha IS NOT NULL;

-- TABLE : mod_files
CREATE TABLE mod_files (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE CASCADE,
    file_path       VARCHAR(512) NOT NULL,
    file_type       VARCHAR(32),
    file_role       VARCHAR(32),
    content_hash    VARCHAR(64),
    size_bytes      INTEGER,
    luacheck_score  INTEGER,
    luacheck_warnings INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT unique_file_per_artifact_path UNIQUE (artifact_id, file_path)
);

CREATE INDEX idx_mod_files_artifact ON mod_files(artifact_id);
CREATE INDEX idx_mod_files_type ON mod_files(file_type);
CREATE INDEX idx_mod_files_role ON mod_files(file_role);

-- TABLE : mod_dependencies
CREATE TABLE mod_dependencies (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    dependent_id    UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    dependency_type dependency_type DEFAULT 'requires',
    version_min     VARCHAR(32),
    version_max     VARCHAR(32),
    external_mod_id VARCHAR(128),
    external_url    VARCHAR(512),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT no_self_dependency CHECK (project_id != dependent_id)
);

CREATE INDEX idx_mod_deps_project ON mod_dependencies(project_id);
CREATE INDEX idx_mod_deps_dependent ON mod_dependencies(dependent_id);

-- TABLE : knowledge_chunks
CREATE TABLE knowledge_chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    category        VARCHAR(64) NOT NULL,
    subcategory     VARCHAR(128),
    content_text    TEXT NOT NULL,
    content_hash    VARCHAR(64) NOT NULL,
    source_url      VARCHAR(512),
    source_type     VARCHAR(32),
    source_date     DATE,
    source_title    VARCHAR(256),
    qdrant_point_id VARCHAR(128),
    qdrant_vector_id BIGINT,
    chunk_index     INTEGER,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ,
    tags            JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX idx_knowledge_chunks_project ON knowledge_chunks(project_id);
CREATE INDEX idx_knowledge_chunks_category ON knowledge_chunks(category);
CREATE INDEX idx_knowledge_chunks_qdrant ON knowledge_chunks(qdrant_point_id) WHERE qdrant_point_id IS NOT NULL;
CREATE INDEX idx_knowledge_chunks_search ON knowledge_chunks USING gin(content_text gin_trgm_ops);
CREATE INDEX idx_knowledge_chunks_source ON knowledge_chunks(source_type, source_date);

-- TABLE : api_reference
CREATE TABLE api_reference (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    element_name    VARCHAR(256) NOT NULL,
    element_type    VARCHAR(64) NOT NULL,
    build_target    build_target DEFAULT 'both',
    deprecated_in   VARCHAR(32),
    removed_in      VARCHAR(32),
    description     TEXT,
    syntax          TEXT,
    parameters      JSONB DEFAULT '[]',
    return_value    TEXT,
    example_code    TEXT,
    common_errors   JSONB DEFAULT '[]',
    source          VARCHAR(256),
    wiki_url        VARCHAR(512),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_api_reference_type ON api_reference(element_type);
CREATE INDEX idx_api_reference_name ON api_reference(element_name) UNIQUE;
CREATE INDEX idx_api_reference_build ON api_reference(build_target);

-- TABLE : test_scenarios
CREATE TABLE test_scenarios (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    scenario_name   VARCHAR(256) NOT NULL,
    description     TEXT,
    test_type       VARCHAR(64),
    validation_level validation_level,
    test_script     TEXT NOT NULL,
    expected_outcome TEXT,
    success_criteria JSONB DEFAULT '{}',
    last_run_at     TIMESTAMPTZ,
    last_result     validation_result,
    last_error      TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_test_scenarios_project ON test_scenarios(project_id);
CREATE INDEX idx_test_scenarios_type ON test_scenarios(test_type);

-- TABLE : fix_attempts
CREATE TABLE fix_attempts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    fix_number      INTEGER NOT NULL,
    validation_level validation_level,
    error_type      VARCHAR(128),
    error_message   TEXT,
    fix_description TEXT,
    files_modified  JSONB DEFAULT '[]',
    resolved        BOOLEAN DEFAULT FALSE,
    new_errors      JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_fix_attempts_run ON fix_attempts(run_id);

-- TABLE : validation_results
CREATE TABLE validation_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id          UUID REFERENCES agent_runs(id) ON DELETE CASCADE,
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE CASCADE,
    validation_level validation_level NOT NULL,
    result          validation_result NOT NULL,
    duration_ms     INTEGER,
    files_checked   INTEGER DEFAULT 0,
    errors_found    INTEGER DEFAULT 0,
    warnings_found  INTEGER DEFAULT 0,
    output_log      TEXT,
    error_details   JSONB DEFAULT '[]',
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ
);

CREATE INDEX idx_validation_results_run ON validation_results(run_id);
CREATE INDEX idx_validation_results_level ON validation_results(validation_level);
CREATE INDEX idx_validation_results_result ON validation_results(result);

-- TABLE : publish_log
CREATE TABLE publish_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id      UUID REFERENCES mod_projects(id) ON DELETE CASCADE,
    artifact_id     UUID REFERENCES mod_artifacts(id) ON DELETE SET NULL,
    publish_type    VARCHAR(32),
    status          VARCHAR(32) DEFAULT 'pending',
    error_message   TEXT,
    publish_url     VARCHAR(1024),
    validation_passed BOOLEAN,
    human_approved   BOOLEAN,
    approved_by      VARCHAR(128),
    requested_at    TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX idx_publish_log_project ON publish_log(project_id);
CREATE INDEX idx_publish_log_status ON publish_log(status);

-- TABLE : users
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(128) NOT NULL UNIQUE,
    email           VARCHAR(256) NOT NULL UNIQUE,
    role            VARCHAR(32) DEFAULT 'developer',
    can_publish_steam  BOOLEAN DEFAULT FALSE,
    can_merge_main     BOOLEAN DEFAULT FALSE,
    can_escalate       BOOLEAN DEFAULT FALSE,
    can_view_secrets   BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    CONSTRAINT valid_role CHECK (role IN ('admin', 'developer', 'reviewer', 'viewer'))
);

CREATE INDEX idx_users_role ON users(role);

-- VUES UTILES

CREATE VIEW v_latest_validated_artifact AS
SELECT DISTINCT ON (ma.project_id)
    p.id AS project_id, p.mod_id, p.name,
    ma.id AS artifact_id, ma.version, ma.created_at,
    ma.validation_summary, ar.status AS run_status
FROM mod_artifacts ma
JOIN agent_runs ar ON ma.run_id = ar.id
JOIN mod_projects p ON ar.project_id = p.id
WHERE ar.status = 'done'
ORDER BY p.id, ma.created_at DESC;

CREATE VIEW v_run_success_rate AS
SELECT
    p.mod_id, p.name,
    COUNT(ar.id) AS total_runs,
    COUNT(CASE WHEN ar.status = 'done' THEN 1 END) AS successful_runs,
    COUNT(CASE WHEN ar.status = 'failed' THEN 1 END) AS failed_runs,
    ROUND(
        COUNT(CASE WHEN ar.status = 'done' THEN 1 END)::NUMERIC /
        NULLIF(COUNT(ar.id), 0) * 100, 2
    ) AS success_rate_pct,
    AVG(EXTRACT(EPOCH FROM ar.ended_at - ar.started_at)) AS avg_duration_seconds
FROM mod_projects p
LEFT JOIN agent_runs ar ON p.id = ar.project_id
    AND ar.started_at > NOW() - INTERVAL '30 days'
GROUP BY p.id, p.mod_id, p.name;

CREATE VIEW v_validation_trends AS
SELECT
    DATE(started_at) AS date,
    validation_level,
    COUNT(*) AS total_runs,
    COUNT(CASE WHEN result = 'passed' THEN 1 END) AS passed,
    COUNT(CASE WHEN result = 'failed' THEN 1 END) AS failed,
    ROUND(
        COUNT(CASE WHEN result = 'passed' THEN 1 END)::NUMERIC /
        NULLIF(COUNT(*), 0) * 100, 2
    ) AS pass_rate_pct
FROM validation_results
WHERE started_at > NOW() - INTERVAL '30 days'
GROUP BY DATE(started_at), validation_level
ORDER BY date DESC, validation_level;

-- TRIGGERS

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_mod_projects_updated
    BEFORE UPDATE ON mod_projects FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_api_reference_updated
    BEFORE UPDATE ON api_reference FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE FUNCTION update_project_stats()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status = 'done' THEN
        UPDATE mod_projects SET total_runs = total_runs + 1,
            success_count = success_count + 1, last_run_at = NOW()
        WHERE id = (SELECT project_id FROM agent_runs WHERE id = NEW.id);
    ELSIF NEW.status IN ('failed', 'escalated') THEN
        UPDATE mod_projects SET total_runs = total_runs + 1, last_run_at = NOW()
        WHERE id = (SELECT project_id FROM agent_runs WHERE id = NEW.id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_run_completion_stats
    AFTER UPDATE ON agent_runs FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION update_project_stats();
```

---

## D. Structure Type d'un Mod PZ -- Genere et Valide par l'Agent {#section-d}

### D.1 Arborescence Complete -- Build 42 (Style Moderne)

```
MyAwesomeMod/                          <- Dossier racine = ID du mod
|
|-- mod.info                           <- Metadonnees du mod (OBLIGATOIRE)
|-- poster.png                         <- Affiche du mod (256x512px recommande)
|-- README.md                          <- Documentation du mod
|
|-- media/                             <- Ressources du jeu
|   |-- lua/
|   |   |-- shared/                    <- Scripts partages (client + server)
|   |   |   |-- MyAwesomeMod_Shared.lua
|   |   |   |-- MyAwesomeMod_Utils.lua
|   |   |-- client/                    <- Scripts client uniquement
|   |   |   |-- MyAwesomeMod_Client.lua
|   |   |-- server/                    <- Scripts serveur uniquement
|   |   |   |-- MyAwesomeMod_Server.lua
|   |   |-- xServer/
|   |       |-- MyAwesomeMod_ISEnv.lua
|   |
|   |-- scripts/
|   |   |-- items.txt                  <- Definition des items
|   |   |-- recipes.txt                <- Definition des recettes
|   |   |-- vehicles.txt               <- Definition des vehicules
|   |   |-- media/
|   |       |-- scripts/
|   |       |-- textures/
|   |
|   |-- textures/                      <- Textures du mod
|   |   |-- items/
|   |   |   |-- MyItem.png
|   |   |-- ui/
|   |       |-- MyIcon.png
|   |
|   |-- models/                        <- Modeles 3D (optionnel)
|       |-- MyModel.xp
|
|-- Contents/                          <- Contenu Steam Workshop (build 41)
|   |-- mods/
|       |-- MyAwesomeMod/
|
|-- workshop.txt                       <- ID Steam Workshop (si publish)
|-- .gitignore
```

### D.2 Fichier mod.info -- Format Complet

```ini
name=Mon Super Mod
id=MonSuperMod
description=Un mod qui ajoute des fonctionnalites awesome au jeu.
poster=poster.png
author=AgentAI
icon=icon.png
```

| Champ | Obligatoire | Description | Exemple |
|-------|-------------|-------------|---------|
| `id` | YES | Identifiant unique (lettres, chiffres, _, -) | `MonSuperMod` |
| `name` | YES | Nom affiche dans le menu | `Mon Super Mod` |
| `description` | YES | Description longue | `Ajoute des outils...` |
| `poster` | YES | Fichier affiche (256x512px PNG) | `poster.png` |
| `author` | YES | Nom de l'auteur | `AgentAI` |
| `icon` | OPTIONAL | Icone carree (256x256px) | `icon.png` |
| `require` | OPTIONAL | IDs des mods requis | `superiorcrafting` |
| `versionMin` | OPTIONAL | Build minimum requis | `41.78` ou `42` |
| `modversion` | OPTIONAL | Version du mod lui-meme | `1.0.0` |
| ` workshop` | OPTIONAL | ID Steam Workshop | `1234567890` |

### D.3 Fichier items.txt -- Format Complet

```ini
module Base
{
    categories: Survival,
    asset形象: MyCustomIcon,

    item MyAwesomeItem
    {
        DisplayName            = Super Hache,
        DisplayCategory        = Tool,
        Type                   = Weapon,
        Tooltip                = Une hache faite maison, robuste et efficace.,
        Icon                   = MyAxeIcon,
        Category               = Weapon,
        SubCategory            = Axe,
        WeaponSprite           = MyAxeSprite,
        AttachmentType         = LargeWeapon,
        Tags                   = Axe;Melee;HighDamage,
        Weight                 = 1.5,
        MaxRange               = 1.2,
        MinRange               = 0.5,
        BaseDamage             = 1.8,
        KnockBackOnZombieStrength = 4,
        CritChance             = 15,
        CritDamageMultiplier    = 2.5,
        DoorDamage             = 10,
        TreeDamage             = 20,
        ConditionLowerChanceOneIn = 25,
        ConditionMax           = 15,
        SwingAmount            = 0.033,
        SwingTime              = 0.5,
        SwingAngleBeforeStrike = 30,
        MinimumSwingTime       = 0.5,
        SwingRotAngle          = 1.0,
        PhysicsObject          = LightObject,
        FireResistance         = 0.3,
        MetalValue             = 40,
        CanBarricade           = true,
        RepairTool             = Hammer,
        RepairAmount           = 15,
        SplatNumber            = 3,
        PaintColor             = Brown,
        WorldObjectSprites     = WS_Axe_01;WS_Axe_02,
    }

    item MyCraftingMaterial
    {
        DisplayName            = Composant Electronique,
        DisplayCategory        = Hardware,
        Type                   = Generic,
        Icon                   = ElectronicPart,
        Weight                 = 0.3,
        Tags                   = Electronics;Crafting,
        WorldSprite            = ObjectComps,
        CanBeEquipped          = NONE,
    }
}
```

### D.4 Fichier recipes.txt -- Format Complet

```ini
module Base
{
    recipe Super Axe Crafting
    {
        name=SuperAxeCraft,
        category=Survival,
        Result:Base.MyAwesomeItem,
        Time=300.0,
        Category=Weapons,
        Prop2=Tool,
        Sound=Recipe,
        Ingredients=
        {
            Base.Hammer=1,
            Base.LongStick=2,
            Base.ScrapMetal=3,
            Base.ElectronicScrap=1,
        },
        Resultitem1=Base.MyCraftingMaterial,
        Resultitem2=Base.Hammer,
        CanBeDoneFromStep=true,
    }

    recipe Repair Super Axe
    {
        name=RepairSuperAxe,
        Result:Base.MyAwesomeItem,
        Time=120.0,
        Category=Repair,
        Prop1=Tool,
        Prop2=Tool,
        Sound=Recipe,
        Ingredients=
        {
            Base.MyAwesomeItem=1,
            Base.ScrapMetal=2,
        },
        AllowHeldItem=false,
    }
}
```

### D.5 Scripts Lua -- Partage Client/Server/Shared

**media/lua/shared/MyMod_Shared.lua**

```lua
-- MyMod_Shared.lua -- Fonctions partagees client + serveur
-- Projet: MonSuperMod Version: 1.0.0

require "ISUI/ISPanel"

MyMod = MyMod or {}
MyMod.Shared = MyMod.Shared or {}

MyMod.Config = {
    debugMode = false,
    maxItems = 100,
    version = "1.0.0",
}

function MyMod.Shared:log(msg)
    if self.Config.debugMode then
        print("[MyMod.Shared] " .. msg)
    end
end

function MyMod.Shared:formatItemName(itemName)
    return "[" .. self.Config.version .. "] " .. itemName
end

function MyMod.Shared:getEnvironment()
    if getWorld() then return "server"
    elseif getPlayer() then return "client"
    else return "unknown" end
end

MyMod.Shared.OnModLoaded = nil
```

**media/lua/server/MyMod_Server.lua**

```lua
-- MyMod_Server.lua -- Logique serveur uniquement
-- Projet: MonSuperMod

MyMod = MyMod or {}
MyMod.Server = MyMod.Server or {}

Events.OnGameBoot.Add(function()
    MyMod.Shared:log("Server: OnGameBoot fired")

    local items = getAllItems():toList()
    for i = 0, items:size() - 1 do
        local item = items:get(i)
        if string.find(item:getType(), "MyMod_") then
            MyMod.Shared:log("Found mod item: " .. item:getType())
        end
    end

    MyMod.Shared:log("MyMod Server initialized")
end)

Events.OnPlayerUpdate.Add(function(player)
    if player:getModData().myModFirstTick == nil then
        player:getModData().myModFirstTick = true
        MyMod.Shared:log("First tick for player: " .. player:getUsername())
    end
end)
```

**media/lua/client/MyMod_Client.lua**

```lua
-- MyMod_Client.lua -- Logique client uniquement
-- Projet: MonSuperMod

MyMod = MyMod or {}
MyMod.Client = MyMod.Client or {}

Events.OnGameBoot.Add(function()
    MyMod.Shared:log("Client: OnGameBoot fired")
    MyMod.Shared:log("Environment: " .. MyMod.Shared:getEnvironment())
end)

Events.OnGameStart.Add(function()
    MyMod.Shared:log("Client game started")
end)

function MyMod.Client:showInfo()
    if getPlayer() then
        local player = getPlayer()
        MyMod.Shared:log("Displaying info for: " .. player:getUsername())
    end
end
```

### D.6 Checklist d'Erreurs Lua Courantes et Corrections

| Erreur | Cause | Correction |
|--------|-------|------------|
| `attempt to index a nil value` | Variable non initialisee | Ajouter `or {}` ou verifier avec `if var then` |
| `bad argument #N to function` | Mauvais argument | Verifier la signature de la fonction PZ API |
| `attempt to call a non-existent method` | API PZ changed | Consulter `api_reference` table dans PostgreSQL |
| `Events.OnGameBoot.Add(nil)` | Callback non defini | Definir la fonction avant `Events.Add` |
| `variable X declared but not used` | luacheck warning | Utiliser `_ = X` ou supprimer |
| `module X not found` | require mal forme | `require "path/to/module"` (sans .lua) |
| `cannot use self outside a method` | Syntaxe incorrecte | `function MyMod:Method()` vs `function MyMod.Method(self)` |
| `stack overflow` | Recursion infinie | Verifier les conditions de sortie |
| `attempt to concatenate string with number` | Type mismatch | Utiliser `tostring(var)` |
| `attempt to compare table with nil` | Comparaison nil | Ajouter verification `if type(a) == "table" then` |
| `mod.info malformed` | Syntaxe ini incorrecte | Verifier les espaces autour du `=` |
| `duplicate item name X` | Items.txt double | Renommer ou supprimer le doublon |
| `media/scripts folder not found` | Chemin incorrect | Verifier `media/scripts/` (pas `media/script/`) |
| `recipe requires unknown item` | Item non defini | Ajouter l'item dans items.txt avant la recipe |

---

## Synthese et Principes Cles {#synthese}

### Resume du stack

```
PostgreSQL 16 (metadonnees, pipeline, tracabilite)
+ Qdrant (embeddings semantiques pour contexte PZ)
+ MinIO (storage objet: zips de mods, posters, assets)
+ Gitea (repos Git, CI/CD, code review)
+ Redis (cache, queue de tasks, state agent)
+ PZ Dedicated Server Docker (test headless, validation)
+ luacheck (linting Lua)
+ LangGraph (orchestration multi-agents)
```

### Principes cles

1. **La boucle generate -> test -> fix -> version est le coeur du systeme**, pas le stockage. Chaque iteration produit un artifact testable et tracable.

2. **Les 4 niveaux de validation sont non negotiables**. Un mod qui echoue au niveau 1 ne doit jamais atteindre le niveau 2. Un mod qui echoue au niveau 4 ne doit jamais etre packaging.

3. **La gouvernance a trois niveaux (GREEN/ORANGE/RED) protege l'integrite du pipeline**. GREEN = automation complete. RED = intervention humaine obligatoire.

4. **Le build cible (41 vs 42) doit etre explicite** des le planning. Un mod compile en 41 peut echouer en 42 a cause de differences d'API.

5. **Le retry counter est limite a 5**. Au-dela, le systeme escalade vers un humain. Pas de boucle infinie.

6. **La connaissance de PZ (items, recipes, events, API) est stockee dans Qdrant** pour etre recuperee semantiquement par le Planner au moment de la generation.

7. **Les artifacts de mods (.zip) sont stockes dans MinIO**, les sources dans Gitea, et les metadonnees dans PostgreSQL.

8. **L'agent ne doit jamais publier sur Steam Workshop automatiquement**. La publication requiert une double validation humaine.

---

*Document genere pour le projet Zomboid Knowledge Engine -- Agent Autonome de Production de Mods*
*Version 1.0.0*
