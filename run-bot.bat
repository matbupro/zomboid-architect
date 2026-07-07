@echo off
REM run-bot.bat — Lance le bot en local sans Docker (Windows, cmd)
setlocal

REM Charger .env.unified a la racine du projet
if not exist ".env.unified" (
    echo ERREUR: .env.unified introuvable a la racine du projet
    exit /b 1
)
for /f "usebackq tokens=1* delims==" %%A in (".env.unified") do set "%%A=%%B"

if "%DISCORD_TOKEN%"=="" (
    echo ERREUR: DISCORD_TOKEN non defini dans .env.unified
    exit /b 1
)

echo === Zomboid Knowledge Engine - Bot Discord ===
echo [OK] .env.unified charge
cd /d "%~dp0"
python -m bot.main
