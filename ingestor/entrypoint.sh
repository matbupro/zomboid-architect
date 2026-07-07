#!/bin/bash
# =============================================================================
# entrypoint.sh — Lance le serveur PZ en mode headless avec mod injecte
# =============================================================================
# Usage: /pz-server/entrypoint.sh <MOD_ID> [BUILD_TARGET]
#   MOD_ID        — ID du mod a tester (dossier dans /workspace/mods/)
#   BUILD_TARGET  — '41' (stable) ou '42' (bleeding0), par defaut '42'
# =============================================================================

set -e

MOD_ID="${1:-testmod}"
BUILD_TARGET="${2:-42}"

# ------------------------------------------------------------------------------
# Download PZ server if not already installed
# ------------------------------------------------------------------------------
if [ ! -f /pz-server/start-server.sh ]; then
    echo "[PZ-HEADLESS] PZ server non installe — telechargement via SteamCMD..."
    /usr/local/bin/download_pz.sh || {
        echo "[PZ-HEADLESS] ERREUR: echec du telechargement de PZ"
        exit 1
    }
fi

echo "[PZ-HEADLESS] Starting server for mod: $MOD_ID (build: $BUILD_TARGET)"

# Generation du servertest.ini avec le mod active
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

echo "[PZ-HEADLESS] servertest.ini configured with Mods=${MOD_ID}"

# Demarrage du serveur headless avec capture de logs
./start-server.sh servertest.ini -noSteam -noGUI > /tmp/pz_console.log 2>&1 &
PZ_PID=$!

echo "[PZ-HEADLESS] Server PID: $PZ_PID"
sleep 15

# Surveillance des logs Lua pendant 60s — recherche d'erreurs de boot
timeout 60 tail -f /pz-server/Zomboid/logs/*.lua 2>/dev/null || true
cp -r /pz-server/Zomboid/logs /tmp/pz_logs/ 2>/dev/null || true

# Arret propre du serveur
kill $PZ_PID 2>/dev/null || true
echo "[PZ-HEADLESS] Server stopped. Logs available in /tmp/"
