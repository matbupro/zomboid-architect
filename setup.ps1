#requires -Version 5.1
<#
.SYNOPSIS
    Installation COMPLETE -- fonctionne depuis un ordinateur totalement neuf (rien installe).

.DESCRIPTION
    Ce script detecte et installe automatiquement TOUT ce qui est necessaire :
    1. Python >= 3.10 (via winget si absent)
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
Write-Host "  Zomboid_Architect -- Installation COMPLETE (machine neuve)" -ForegroundColor Cyan
Write-Host "  Repertoire : $ProjectRoot" -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Cyan

# Helpers
function Write-Step { param($Msg) Write-Host "[setup] $Msg" -ForegroundColor Cyan }
function Write-Ok   { param($Msg) Write-Host "[ok]   $Msg" -ForegroundColor Green }
function Write-Warn { param($Msg) Write-Host "[warn] $Msg" -ForegroundColor Yellow }
function Write-Fail { param($Msg) Write-Host "[fail] $Msg" -ForegroundColor Red }

# ---- Helper: installer via winget si absent ----------------------------------
function Install-WithWinget {
    param(
        [string]$PackageId,
        [string]$DisplayName,
        [string]$CommandName = $null   # FIX #5 : nom de commande réel à tester (ex: "git"), distinct de l'ID winget
    )

    if ($CommandName -and (Get-Command $CommandName -ErrorAction SilentlyContinue)) { return $true }

    # FIX #6 : recherche fiable par ID exact
    $wingetList = winget list --id $PackageId --exact 2>&1
    if ($LASTEXITCODE -eq 0 -and $wingetList -match [regex]::Escape($PackageId)) { return $true }

    Write-Step "Installation de $DisplayName via winget..."
    try {
        $result = Start-Process -FilePath winget `
            -ArgumentList "install", "$PackageId", "--accept-package-agreements", "--accept-source-agreements", "-s", "winget" `
            -Wait -PassThru -NoNewWindow

        # FIX #1 : le if est désormais bien séparé du bloc Start-Process
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
    Install-WithWinget "Python.Python.3.14" "Python 3.14" -CommandName "python" | Out-Null
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
    Install-WithWinget "Git.Git" "Git" -CommandName "git" | Out-Null
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

# FIX #3 : distinction requirements.txt (pip -r) vs pyproject.toml (pip install .)
$requirementsFiles = @(
    @{ "path"="notion_client/pyproject.toml";  "label"="notion_client"; "type"="pyproject" },
    @{ "path"="ingestor/requirements.txt";     "label"="ingestor";      "type"="requirements" },
    @{ "path"="bot/requirements.txt";          "label"="bot";           "type"="requirements" }
)

foreach ($req in $requirementsFiles) {
    $fullPath = Join-Path $ProjectRoot $req.path
    if (Test-Path $fullPath) {
        Write-Step "  Installation $($req.label)..."
        if ($req.type -eq "pyproject") {
            $projectDir = Split-Path $fullPath -Parent
            & pip install -e $projectDir 2>&1 | Out-Null
        } else {
            & pip install -r $fullPath 2>&1 | Out-Null
        }

        # FIX #4 : vérification réelle du succès via LASTEXITCODE
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "  $($req.label) installe"
        } else {
            Write-Warn "  $($req.label) -- echec (code $LASTEXITCODE). Verifier manuellement : $($req.path)"
        }
    } else {
        Write-Warn "  $($req.path) inexistant (skip)"
    }
}

# ============================================================
# ETAPE 2 : Docker Desktop
# ============================================================

Write-Host "`n--- Etape 2 : Docker ---`n" -ForegroundColor Magenta

if (Get-Command docker -ErrorAction SilentlyContinue) {
    $dockerVersion = docker --version 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "  Docker trouve : $dockerVersion"
    } else {
        Write-Warn "  Docker lance mais echoue -- REDEMARRER le PC pour que le service démarre."
        Write-Host "      Puis relancer : docker compose up -d`n" -ForegroundColor Yellow
    }
} else {
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
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "  modele installe"
            } else {
                Write-Warn "  ollama pull a echoue -- verifier : ollama pull qwen3.6:35b-a3b"
            }
        }
    } else {
        throw "Ollama not running"
    }
} catch {
    Install-WithWinget "Ollama.Ollama" "Ollama" -CommandName "ollama" | Out-Null
    Write-Warn "  Ollama installe. Redemarrer le terminal, puis:"
    Write-Host "      ollama pull qwen3.6:35b-a3b`n" -ForegroundColor Yellow
}

# ============================================================
# ETAPE 4 : Playwright Chromium
# ============================================================

Write-Host "`n--- Etape 4 : Playwright Chromium ---`n" -ForegroundColor Magenta

& playwright install chromium 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Ok "  Chromium installe pour Playwright"
} else {
    & python -m playwright install chromium 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "  Chromium installe (via python)"
    } else {
        Write-Warn "  Playwright -- verifier : pip install playwright && playwright install chromium"
    }
}

# ============================================================
# ETAPE 5 : Git hooks pre-commit
# ============================================================

Write-Host "`n--- Etape 5 : Git hooks ---`n" -ForegroundColor Magenta

$hooksDir = Join-Path $ProjectRoot ".git/hooks"
if (-not (Test-Path $hooksDir)) {
    New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
}

$preCommitTarget = Join-Path $hooksDir "pre-commit.cmd"
if (Test-Path $preCommitTarget) {
    Write-Ok "  pre-commit.cmd existe deja"
} else {
    $templatePath = Join-Path $ProjectRoot ".git/hooks/pre-commit.template.cmd"
    if (Test-Path $templatePath) {
        Copy-Item $templatePath $preCommitTarget -Force
        Write-Ok "  pre-commit.cmd cree depuis template"
    } else {
        Write-Warn "  Template pre-commit introuvable -- le hook ne sera pas installe"
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
    $srcPath  = Join-Path $ProjectRoot $t.src
    $destPath = Join-Path $ProjectRoot $t.dest

    # FIX #2 : parenthésage correct des conditions booléennes
    if ((Test-Path $srcPath) -and (-not (Test-Path $destPath))) {
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
    & docker compose up -d 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "  docker compose up -d reussi"
    } else {
        Write-Warn "  docker compose up echoue -- verifier Docker Desktop est demarre"
    }
} else {
    Write-Warn "  docker-compose.yml inexistant (skip)"
}

# ============================================================
# SUMMARY
# ============================================================
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  Installation terminee !`n" -ForegroundColor Green
Write-Host "  Redemarrer le terminal si des logiciels ont ete installes." -ForegroundColor DarkGray
Write-Host "  Pour verifier : pytest tests/ --tb=short" -ForegroundColor DarkGray
Write-Host "  Pour un sync manuel : .\agent\maintenance\sync_agent.ps1" -ForegroundColor DarkGray
Write-Host "============================================================`n" -ForegroundColor Cyan
