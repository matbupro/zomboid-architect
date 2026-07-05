#requires -Version 5.1
<#
.SYNOPSIS
    Installation COMPLETE — fonctionne depuis un ordinateur totalement neuf (rien installe).

.DESCRIPTION
    Ce script detecte et installe automatiquement TOUT ce qui est necessaire :
    1. Python ≥ 3.10 (via winget si absent)
    2. Git (via winget si absent)
    3. Deps Python du projet (pip install -r ...)
    4. Docker Desktop (via winget si absent)
    5. Ollama + modele qwen3.6:35b-a3b (via winget + ollama pull si absent)
    6. Playwright Chromium (via pip + playwright install)
    7. Git hooks pre-commit (sync auto Notion)
    8. .env files from templates (.gitignore)
    9. Docker compose up (ChromaDB + Bot)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup.ps1
#>

$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = $PSScriptRoot
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  Zomboid_Architect — Installation COMPLETE (machine neuve)" -ForegroundColor Cyan
Write-Host "  Repertoire : $ProjectRoot" -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Cyan

# Helpers
function Write-Step { param($Msg) Write-Host "[setup] $Msg" -ForegroundColor Cyan }
function Write-Ok   { param($Msg) Write-Host "[ok]   $Msg" -ForegroundColor Green }
function Write-Warn { param($Msg) Write-Host "[warn] $Msg" -ForegroundColor Yellow }
function Write-Fail { param($Msg) Write-Host "[fail] $Msg" -ForegroundColor Red }

# ---- Helper: installer via winget si absent ----------------------------------
function Install-WithWinget {
    param($PackageId, $DisplayName)

    # Verifier si deja installe (plusieurs methodes de detection)
    if (Get-Command $PackageId -ErrorAction SilentlyContinue) { return $true }
    $wingetList = winget list "$PackageId" --max-info 2>&1
    if ($wingetList -and $wingetList -match "Installed") { return $true }

    Write-Step "Installation de $DisplayName via winget..."
    try {
        $result = Start-Process -FilePath winget `
            -ArgumentList "install", "$PackageId", "--accept-package-agreements", "--accept-source-agreements", "-s", "winget" `
            -Wait -PassThru -NoNewWindow

        if ($result.ExitCode -eq 0 -or $null -eq $result.ExitCode) {
            Write-Ok "  $DisplayName installe (redemarrer le terminal pour que PATH soit mis a jour)"
            return $true
        } else {
            Write-Warn "  winget install $PackageId -> code $($result.ExitCode). Essayer manuellement : winget install $PackageId"
            return $false
        }
    } catch {
        Write-Fail "  Impossible d'installer $DisplayName via winget: $_"
        Write-Host "      Manuellement: https://winget.run/pkg/$($PackageId -replace '\.','')" -ForegroundColor Yellow
        return $false
    }
}

# ============================================================
# ETAPE 0 : Outils systeme
# ============================================================

Write-Host "`n--- Etape 0 : Outils systeme ---`n" -ForegroundColor Magenta

# Python
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonVersion = & python --version 2>&1
    Write-Ok "  Python trouve : $pythonVersion"
} else {
    Install-WithWinget "Python.Python.3.14" "Python 3.14" | Out-Null
    # Essayer a nouveau
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonVersion = & python --version 2>&1
        Write-Ok "  Python installe : $pythonVersion"
    } else {
        Write-Warn "  Python non installe et winget echoue. Installer manuellement: https://python.org/downloads/"
    }
}

# Git
if (Get-Command git -ErrorAction SilentlyContinue) {
    $gitVersion = & git --version 2>&1
    Write-Ok "  Git trouve : $gitVersion"
} else {
    Install-WithWinget "Git.Git" "Git" | Out-Null
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Ok "  Git installe"
    } else {
        Write-Warn "  Git non installe. Installer manuellement: https://git-scm.com/downloads/win"
    }
}

# ============================================================
# ETAPE 1 : Deps Python du projet
# ============================================================

Write-Host "`n--- Etape 1 : Dependances Python ---`n" -ForegroundColor Magenta

$requirementsFiles = @(
    @{ path = Join-Path "notion_client" "pyproject.toml";  label = "notion_client" },
    @{ path = Join-Path "ingestor"          "requirements.txt"; label = "ingestor" },
    @{ path = Join-Path "bot"               "requirements.txt"; label = "bot" },
)

foreach ($req in $requirementsFiles) {
    $fullPath = Join-Path $ProjectRoot $req.path
    if (Test-Path $fullPath) {
        Write-Step "  pip install $($req.label)..."
        try {
            & pip install -r $fullPath 2>&1 | Out-Null
            Write-Ok "  $($req.label) installe"
        } catch {
            Write-Warn "  $($req.label) — verifier : pip install -r $($req.path)"
        }
    } else {
        Write-Warn "  $($req.path) inexistant (skip)"
    }
}

# ============================================================
# ETAPE 2 : Docker Desktop
# ============================================================

Write-Host "`n--- Etape 2 : Docker ---`n" -ForegroundColor Magenta

try {
    $dockerVersion = docker --version 2>&1
    if ($?) {
        Write-Ok "  Docker trouve : $dockerVersion"
    } else {
        throw "Docker not running"
    }
} catch {
    Install-WithWinget "Docker.DockerDesktop" "Docker Desktop" | Out-Null
    Write-Warn "  Docker installe — REDEMARRER le PC pour que le service démarre."
    Write-Host "      Puis relancer : docker compose up -d`n" -ForegroundColor Yellow
}

# ============================================================
# ETAPE 3 : Ollama + modele LLM
# ============================================================

Write-Host "`n--- Etape 3 : Ollama + LLM ---`n" -ForegroundColor Magenta

try {
    $ollamaInfo = ollama list 2>&1
    if ($?) {
        Write-Ok "  Ollama trouve"
        if ($ollamaInfo -match "qwen3\.6") {
            Write-Ok "  qwen3.6:35b-a3b installe"
        } else {
            Write-Step "  ollama pull qwen3.6:35b-a3b (cela peut prendre 10 min)..."
            & ollama pull qwen3.6:35b-a3b 2>&1 | Out-Null
            if ($?) {
                Write-Ok "  modele installe"
            } else {
                Write-Warn "  ollama pull a echoue — verifier : ollama pull qwen3.6:35b-a3b"
            }
        }
    } else {
        throw "Ollama not running"
    }
} catch {
    Install-WithWinget "Ollama.Ollama" "Ollama" | Out-Null
    Write-Warn "  Ollama installe. Redemarrer le terminal, puis:"
    Write-Host "      ollama pull qwen3.6:35b-a3b`n" -ForegroundColor Yellow
}

# ============================================================
# ETAPE 4 : Playwright Chromium
# ============================================================

Write-Host "`n--- Etape 4 : Playwright Chromium ---`n" -ForegroundColor Magenta

try {
    & playwright install chromium 2>&1 | Out-Null
    if ($?) {
        Write-Ok "  Chromium installe pour Playwright"
    } else {
        throw "Install failed"
    }
} catch {
    try {
        & python -m playwright install chromium 2>&1 | Out-Null
        if ($?) {
            Write-Ok "  Chromium installe (via python)"
        } else {
            throw "Python install failed"
        }
    } catch {
        Write-Warn "  Playwright — verifier : pip install playwright && playwright install chromium"
    }
}

# ============================================================
# ETAPE 5 : Git hooks pre-commit
# ============================================================

Write-Host "`n--- Etape 5 : Git hooks ---`n" -ForegroundColor Magenta

$hooksDir = Join-Path $ProjectRoot ".git\hooks"
if (-not (Test-Path $hooksDir)) {
    New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
}

$preCommitTarget = Join-Path $hooksDir "pre-commit.cmd"
if (Test-Path $preCommitTarget) {
    Write-Ok "  pre-commit.cmd existe deja"
} else {
    # Verifier si .git existe (le repo a ete clone correctement)
    if (-not (Test-Path (Join-Path $ProjectRoot ".git"))) {
        Write-Warn "  Pas de .git — le repo n'a pas été cloné. Executer: git clone <repo>"
    } else {
        $hookContent = @"
:: Pre-commit hook — sync agent/ + Notion si todo.md change.
:: Ne bloque JAMAIS le commit (execute en arriere-plan).
@echo off
setlocal

for /f "tokens=*" %%r in ('git rev-parse --show-toplevel 2^>nul') do set "REPO_ROOT=%%r"
if not defined REPO_ROOT exit /b 0

set "SYNC_SCRIPT=%REPO_ROOT%\agent\maintenance\sync_agent.ps1"
if not exist "%SYNC_SCRIPT%" exit /b 0

git diff --cached --name-only --diff-filter=ACMRT 2>nul ^| findstr "agent\\\\todo.md" >nul 2>&1
if errorlevel 1 exit /b 0

powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%SYNC_SCRIPT%" "sync pre-commit auto" >nul 2>&1 &

exit /b 0
"@
        [System.IO.File]::WriteAllText($preCommitTarget, $hookContent, [System.Text.Encoding]::UTF8)
        Write-Ok "  pre-commit.cmd cree"
    }
}

# ============================================================
# ETAPE 6 : .env from templates
# ============================================================

Write-Host "`n--- Etape 6 : Variables d'environnement ---`n" -ForegroundColor Magenta

$envTemplates = @(
    @{ src='notion_client/.env.notion.example'; dest='notion_client/.env.notion'; desc='Clé API Notion + DB ID' },
    @{ src='bot/.env.example';                  dest='bot/.env';                   desc='Config bot Discord' },
    @{ src='ingestor/.env.example';             dest='ingestor/.env';              desc='Config ingestor Steam' }
)

foreach ($t in $envTemplates) {
    $srcPath = Join-Path $ProjectRoot $t.src
    $destPath = Join-Path $ProjectRoot $t.dest
    if (Test-Path $srcPath -and -not (Test-Path $destPath)) {
        Copy-Item $srcPath $destPath -Force
        Write-Ok "  $($t.desc) : .env cree"
    } elseif (Test-Path $destPath) {
        Write-Ok "  $($t.dest) existe deja (skip)"
    } else {
        Write-Warn "  $($t.src) inexistant"
    }
}

# ============================================================
# ETAPE 7 : Docker compose up (ChromaDB + Bot)
# ============================================================

Write-Host "`n--- Etape 7 : Services Docker ---`n" -ForegroundColor Magenta

if (Test-Path (Join-Path $ProjectRoot "docker-compose.yml")) {
    try {
        & docker compose up -d 2>&1 | Out-Null
        if ($?) {
            Write-Ok "  docker compose up -d reussi"
        } else {
            Write-Warn "  docker compose up echoue — verifier Docker Desktop est demarre"
        }
    } catch {
        Write-Warn "  Docker pas disponible — services non demarres manuellement : docker compose up -d"
    }
} else {
    Write-Warn "  docker-compose.yml inexistant (skip)"
}

# ============================================================
# SUMMARY
# ============================================================
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  Installation terminee !`n" -ForegroundColor Green

Write-Host "  Redemander le terminal si des depôts ont été installes." -ForegroundColor DarkGray
Write-Host "  Pour verifier : pytest tests/ --tb=short" -ForegroundColor DarkGray
Write-Host "  Pour un sync manuel : .\agent\maintenance\sync_agent.ps1" -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Cyan
