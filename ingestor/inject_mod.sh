#!/bin/bash
# =============================================================================
# inject_mod.sh — Injection d'un mod dans le serveur PZ headless
# =============================================================================
# Usage: /usr/local/bin/inject_mod.sh <MOD_ZIP_PATH> [MOD_ID]
#   MOD_ZIP_PATH  — chemin du mod .zip a extraire (dans le container ou monte)
#   MOD_ID        — ID du mod (repertoire cible), par defaut nom du zip sans ext.
# =============================================================================

set -e

MOD_ZIP="${1:?Usage: inject_mod.sh <MOD_ZIP_PATH> [MOD_ID]}"
MOD_ID="${2:-${MOD_ZIP%.zip}}"
PZ_SERVER_MODS=/pz-server/mods

echo "[INJECT] Extracting mod: $MOD_ID from $MOD_ZIP"

if [ ! -f "$MOD_ZIP" ]; then
    echo "[ERROR] Mod zip not found: $MOD_ZIP"
    exit 1
fi

mkdir -p "${PZ_SERVER_MODS}/${MOD_ID}"
unzip -q "$MOD_ZIP" -d "${PZ_SERVER_MODS}/${MOD_ID}"

# Verification de la structure du mod
if [ ! -f "${PZ_SERVER_MODS}/${MOD_ID}/mod.info" ]; then
    echo "[ERROR] mod.info not found in extracted mod"
    exit 1
fi

echo "[INJECT] Mod extracted successfully"
echo "[INJECT] Contents:"
ls -la "${PZ_SERVER_MODS}/${MOD_ID}/"

# Configuration automatique du servertest.ini
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
