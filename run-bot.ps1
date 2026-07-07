# =============================================================================
# run-bot.ps1 - Lance le bot Zomboid Knowledge Engine en local (sans Docker)
# =============================================================================

$ErrorActionPreference = "Stop"

# Chemin du projet
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile     = Join-Path $ProjectRoot ".env.unified"

Write-Host "=== Zomboid Knowledge Engine -- Bot Discord ===" -ForegroundColor Cyan
Write-Host ""

# --- Vérifier .env -----------------------------------------------------------
if (-not (Test-Path $EnvFile)) {
    Write-Host "ERREUR : $EnvFile introuvable." -ForegroundColor Red
    Write-Host "Utiliser ou créer .env.unified à la racine du projet." -ForegroundColor Yellow
    exit 1
}

# --- Charger les vars du .env dans le process PowerShell ----------------------
Get-Content $EnvFile | Where-Object { $_ -and (-not $_.Trim().StartsWith("#")) } | ForEach-Object {
    $key, $value = $_ -split "=", 2
    if ($key -and $value) {
        [Environment]::SetEnvironmentVariable($key.Trim(), $value.Trim())
    }
}

# --- Vérifier DISCORD_TOKEN --------------------------------------------------
if (-not $env:DISCORD_TOKEN) {
    Write-Host "ERREUR : DISCORD_TOKEN n'est pas défini dans .env.unified" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] .env.unified chargé depuis $EnvFile" -ForegroundColor Green
Write-Host "[OK] DISCORD_TOKEN présent" -ForegroundColor Green
Write-Host ""

# --- Lancer le bot (python -m pour imports relatifs) -------------------------
Write-Host "Démarrage du bot..." -ForegroundColor Yellow
try {
    Push-Location $ProjectRoot
    python -m bot.main
} finally {
    Pop-Location
}
