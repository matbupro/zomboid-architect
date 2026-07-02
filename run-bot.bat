@echo off
REM run-bot.bat — Lance le bot en local sans Docker (Windows, cmd)
setlocal

REM Charger .env manuellement pour cmd
if not exist "bot\.env" (
    echo ERREUR: bot/.env introuvable
    exit /b 1
)
for /f "usebackq tokens=1* delims==" %%A in ("bot\.env") do set "%%A=%%B"

if "%DISCORD_TOKEN%"=="" (
    echo ERREUR: DISCORD_TOKEN non defini dans bot/.env
    exit /b 1
)

echo === Zomboid Knowledge Engine - Bot Discord ===
echo [OK] .env charge
cd /d "%~dp0"
python -m bot.main
