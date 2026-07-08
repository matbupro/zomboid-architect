# =============================================================================
# generate_secrets.ps1 — Generate strong passwords for first docker-compose up (S10-b/c)
# =============================================================================
# Usage: .\scripts\generate_secrets.ps1
#   Genere des passwords forts si non-definis deja dans .env.pz-agent.
#   NE MODIFIE PAS les valeurs deja remplies (non-change-me).

$ScriptDir = $PSScriptRoot
$RepoRoot = if ($ScriptDir) { git rev-parse --show-toplevel 2>$null } else { git rev-parse --show-toplevel 2>$null }

if (-not $RepoRoot) { Write-Host "[ERR] not a git repo" -ForegroundColor Red; exit 1 }

$EnvFile = Join-Path $RepoRoot ".env.pz-agent"
$template = Join-Path $RepoRoot ".env.pz-agent.example"

function Get-RandPass([int]$Length=32) {
    $cs = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%&*?'
    $bytes = New-Object byte[] $Length
    [Security.Cryptography.RandomNumberGenerator]::GetBytes($bytes)
    -join ($bytes | ForEach-Object { $cs[$_%$cs.Length] })
}

Write-Host "=== Secret Generation (S10-b/c) ===" -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path $EnvFile)) {
    if (Test-Path $template) {
        Copy-Item $template $EnvFile -Force
        Write-Host "[CREATE] .env.pz-agent cree depuis template" -ForegroundColor Cyan
    } else {
        New-Item -ItemType File $EnvFile -Force | Out-Null
        Write-Host "[CREATE] .env.pz-agent cree (vide — remplir manuellement)" -ForegroundColor Cyan
    }
}

$content = Get-Content $EnvFile -Raw -Encoding utf8
$changed = $false

if ($content -match 'PG_PASSWORD=change-me') {
    $newPW = Get-RandPass 32
    $content = $content -replace '(?<=PG_PASSWORD=)change-me[^\\r\\n]*', $newPW
    Write-Host "  [GEN]  PG_PASSWORD → $newPW" -ForegroundColor Green
    $changed = $true
} else {
    Write-Host "  [SKIP] PG_PASSWORD deja defini" -ForegroundColor Gray
}

if ($content -match 'MINIO_PASSWORD=change-me') {
    $newPW = Get-RandPass 32
    $content = $content -replace '(?<=MINIO_PASSWORD=)change-me[^\\r\\n]*', $newPW
    Write-Host "  [GEN]  MINIO_PASSWORD → $newPW" -ForegroundColor Green
    $changed = $true
} else {
    Write-Host "  [SKIP] MINIO_PASSWORD deja defini" -ForegroundColor Gray
}

if ($changed) {
    Set-Content $EnvFile $content -NoNewline -Encoding utf8
    Write-Host ""
    Write-Host "[OK] .env.pz-agent mis a jour. Relancer docker-compose up." -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[OK] Tous les passwords sont deja definis." -ForegroundColor Gray
}

# Rotation reminder
$lastGen = $null
if (Test-Path "$EnvFile.rotation") {
    $lastGen = Get-Content "$EnvFile.rotation" -ErrorAction SilentlyContinue
}
Write-Host ""
Write-Host "S10-c: Penser a rotation mensuelle des passwords." -ForegroundColor Yellow
if ($lastGen) { Write-Host "   Derniere generation: $lastGen" -ForegroundColor Gray }
Write-Host "   → Exécuter ce script de nouveau pour regénérer." -ForegroundColor Gray
