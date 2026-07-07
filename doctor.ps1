#requires -Version 5.1
<#
.SYNOPSIS
    Diagnostic complet du projet Zomboid_Architect (inspiré d'OpenClaw doctor).

.DESCRIPTION
    Verifie l'etat de TOUS les composants et rapporte avec une interface violet/jaune.
    Mode --repair : tente de réparer automatiquement ce qui est cassé.
    Similaire a `openclaw doctor` mais sur mesure pour notre project.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File doctor.ps1
    .\doctor.ps1 --repair
#>

param(
    [switch]$Repair
)

$ErrorActionPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Palette : violet/jaune
$Purple   = "Magenta"
$Yellow   = "Yellow"
$DarkGray = "DarkGray"

# Mode réparation ?
if($Repair){
    Write-Host "`n+------------------------------------------------------+" -ForegroundColor $Yellow
    Write-Host "|  Zomboid_Architect -- Repair (reparateur auto)       |" -ForegroundColor $Yellow
    Write-Host "|  Tentative de correction des problemes detectés        |" -ForegroundColor $DarkGray
    Write-Host "+------------------------------------------------------+" -ForegroundColor $Yellow

    $repairs = @{ ok=0; fail=0; total=0 }
    function AddRepair{ param($s){ $script:repairs.$s++; $script:repairs.total++ } }

    # 1. Python
    if(-not (Get-Command python -ErrorAction SilentlyContinue)){
        Write-Host "`n  [!!] Python manquant -- tentative d'installation..." -ForegroundColor $Yellow
        try{
            & winget install Python.Python.3.14 --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            if(Test-Command python){ Write-Host "  [OK] Python installe" -ForegroundColor Green; AddRepair ok }
            else{ Write-Host "  [XX] winget echoue -- installer manuellement: https://python.org/downloads/" -ForegroundColor Red; AddRepair fail }
        }catch{
            Write-Host "  [XX] winget introuvable -- https://python.org/downloads/" -ForegroundColor Red; AddRepair fail
        }
    }else{
        $ver = & python --version 2>&1 | Out-String | ForEach-Object { $_.Trim() }
        Write-Host "  [OK] Python: $ver" -ForegroundColor Green; AddRepair ok
    }

    # 2. Git
    if(-not (Get-Command git -ErrorAction SilentlyContinue)){
        Write-Host "`n  [!!] Git manquant -- tentative d'installation..." -ForegroundColor $Yellow
        try{
            & winget install Git.Git --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
            if(Get-Command git){ Write-Host "  [OK] Git installe" -ForegroundColor Green; AddRepair ok }
            else{ Write-Host "  [XX] winget echoue -- https://git-scm.com/downloads/win" -ForegroundColor Red; AddRepair fail }
        }catch{ Write-Host "  [XX] winget introuvable" -ForegroundColor Red; AddRepair fail }
    }else{
        $ver = & git --version 2>&1 | Out-String | ForEach-Object { $_.Trim() }
        Write-Host "  [OK] Git: $ver" -ForegroundColor Green; AddRepair ok
    }

    # 3. Deps Python
    $deps = @(
        @{ name="notion_client"; req="notion_client/pyproject.toml" },
        @{ name="ingestor";      req="ingestor/requirements.txt" },
        @{ name="bot";           req="bot/requirements.txt" }
    )
    foreach($d in $deps){
        if(Test-Path $d.req){
            try{
                Write-Host "`n  [!!] pip install $($d.name)..." -ForegroundColor $Yellow
                & pip install -r $d.req 2>&1 | Out-Null
                $mod = switch($d.name){ "notion_client"{"notion_client.api"}; "ingestor"{"ingestor.engine"}; "bot"{"bot.config"} }
                & python -c "import $($mod)" 2>&1 | Out-Null
                if($?){ Write-Host "  [OK] $($d.name) installe" -ForegroundColor Green; AddRepair ok }
                else{ Write-Host "  [XX] $($d.name) introuvable apres pip" -ForegroundColor Red; AddRepair fail }
            }catch{ Write-Host "  [XX] pip install $( $d.req ) echoue: $_" -ForegroundColor Red; AddRepair fail }
        }else{
            Write-Host "`n  [XX] $($d.req) absent -- impossible de reparer" -ForegroundColor Red; AddRepair fail
        }
    }

    # 4. Docker containers
    if(Test-Command docker){
        if($? -and (docker ps --format "{{.Names}}:{{.Status}}" 2>&1 | Where-Object { $_ -match "Exited" })){
            Write-Host "`n  [!!] Containers éteints detected -- docker compose up -d..." -ForegroundColor $Yellow
            & docker compose up -d 2>&1 | Out-Null
            if($?){ Write-Host "  [OK] docker compose up reussi" -ForegroundColor Green; AddRepair ok }
            else{ Write-Host "  [XX] docker compose up echoue -- verifier le daemon" -ForegroundColor Red; AddRepair fail }
        }else{
            # Verifier si containers manquant (pas encore lance)
            if(-not (docker ps --format "{{.Names}}" 2>&1)){
                Write-Host "`n  [!!] Aucun container lance -- tentative docker compose up -d..." -ForegroundColor $Yellow
                & docker compose up -d 2>&1 | Out-Null
                if($?){ Write-Host "  [OK] docker compose up reussi (nouveau)" -ForegroundColor Green; AddRepair ok }
                else{ Write-Host "  [XX] docker compose echoue" -ForegroundColor Red; AddRepair fail }
            }else{
                Write-Host "  [OK] Docker: tout en cours" -ForegroundColor Green; AddRepair ok
            }
        }
    }

    # 5. Ollama models
    if(Test-Command ollama){
        $ollamaList = ollama list 2>&1
        foreach($m in @("qwen3.6:35b-a3b", "nomic-embed-text")){
            if(-not ($ollamaList -match [regex]::Escape($m))){
                Write-Host "`n  [!!] model $m manquant -- ollama pull..." -ForegroundColor $Yellow
                & ollama pull $m 2>&1 | Out-Null
                if($?){ Write-Host "  [OK] $m installe" -ForegroundColor Green; AddRepair ok }
                else{ Write-Host "  [XX] ollama pull $( $m ) echoue" -ForegroundColor Red; AddRepair fail }
            }else{
                Write-Host "  [OK] model: $m (déjà installé)" -ForegroundColor Green; AddRepair ok
            }
        }
    }

    # 6. .env.unified (unique source de config)
    if(-not (Test-Path ".env.unified")){
        Write-Host "`n  [!!] .env.unified manquant -- créer manuellement dans la racine" -ForegroundColor $Yellow
        AddRepair fail
    }else{
        Write-Host "  [OK] .env.unified existe" -ForegroundColor Green; AddRepair ok
    }

    # 7. Git hooks (copier depuis le template -- evite parsing batch en PS)
    if(Test-Command git){
        $hooksDir = Join-Path $PSScriptRoot ".git\hooks"
        if(-not (Test-Path (Join-Path $hooksDir "pre-commit.cmd"))){
            Write-Host "`n  [!!] Pre-commit hook manquant -- copie du template..." -ForegroundColor $Yellow
            if(-not (Test-Path $hooksDir)){ New-Item -ItemType Directory -Force $hooksDir | Out-Null }
            Copy-Item (Join-Path $PSScriptRoot ".git/hooks/pre-commit.template.cmd") (Join-Path $hooksDir "pre-commit.cmd") -Force
            Write-Host "  [OK] pre-commit.cmd cree depuis template" -ForegroundColor Green; AddRepair ok
        }else{
            Write-Host "  [OK] Pre-commit hook existe" -ForegroundColor Green; AddRepair ok
        }
    }

    # Resume
    $repPct = if($repairs.total -gt 0){ [math]::Round(($repairs.ok / $repairs.total) * 100) } else { 0 }
    Write-Host "`n+------------------------------------------------------+" -ForegroundColor $Purple
    Write-Host "|                                                      |" -ForegroundColor $DarkGray
    $barLen = [math]::Floor($repPct / 5); $barEmpty = 20 - $barLen
    Write-Host "  | Repairs reussies: " -NoNewline -ForegroundColor $DarkGray
    Write-Host ("#" * $barLen) -NoNewline -ForegroundColor $Purple
    Write-Host ("." * $barEmpty) -ForegroundColor $DarkGray -NoNewline
    Write-Host " $($repPct)%   |" -ForegroundColor $Yellow
    Write-Host "  | $($repairs.ok) ok | $($repairs.fail) echecs                       |" -ForegroundColor $(if($repairs.fail -eq 0){ "Green"} else { "Red" })
    Write-Host "|                                                      |" -ForegroundColor $DarkGray
    Write-Host "+------------------------------------------------------+" -ForegroundColor $Purple
    Write-Host ""
    exit
}

# ====== MODE DIAGNOSTIC (defaut) ======================================

Write-Host ""
Write-Host "+------------------------------------------------------+" -ForegroundColor $Purple
Write-Host "|  Zomboid_Architect -- Doctor                         |" -ForegroundColor $Purple
Write-Host "|  Diagnostic du Knowledge Engine                       |" -ForegroundColor $DarkGray
Write-Host "+------------------------------------------------------+" -ForegroundColor $Purple

# ---- Helpers --------------------------------------------------------
# Test-Cmd : verifie qu'une commande CLI existe dans le PATH (wrapper propre de Get-Command)
function Test-Cmd { param($Name) return (Get-Command $Name -ErrorAction SilentlyContinue) }

# $checks : accumulateur de resultats [ok, warn, fail, total] utilise pour le pourcentage final
$checks = @{ ok=0; warn=0; fail=0; total=0 }

# AddCheck : incrémente un compteur de resultat et le global total (script-scoped)
function AddCheck {
    param($status)
    $script:checks.$status++
    $script:checks.total++
}

# Write-Row : affiche une ligne formatée [OK|!!|XX] name -- detail optionnel sur la ligne suivante.
#             Utilise l'icone et la couleur correspondant au status pour le rendu visuel.
function Write-Row {
    param($name, $status, $detail = "")

    $icons = @{ ok="[OK]"; warn="[!!]"; fail="[XX]" }
    $icon  = $icons[$status]
    $color = switch($status){ "ok"{"Green"}; "warn"{$Yellow}; "fail"{"Red"}; default{$DarkGray} }

    Write-Host "  |  " -NoNewline
    Write-Host "$icon" -ForegroundColor $color -BackgroundColor Black -NoNewline
    Write-Host "  " -NoNewline
    Write-Host ("-" * ($name.Length + 4)) -NoNewline -ForegroundColor $Purple
    Write-Host " $name |" -ForegroundColor $color

    if($detail){
        Write-Host "     -> $detail" -ForegroundColor $DarkGray
    }
}

# ---- Sections -------------------------------------------------------
# DrawSectionHeader : affiche un separateur de section dans la palette violet du projet.
function DrawSectionHeader { param($name) Write-Host "`n  --- $($name)" -ForegroundColor $Purple }

DrawSectionHeader "Systeme"
# Verifier que les dependances CLI de base sont disponibles (Python 3.14, Git)
if(Test-Cmd python){
    $ver = & python --version 2>&1 | Out-String | ForEach-Object { $_.Trim() }
    Write-Row "Python" "ok" $ver; AddCheck "ok"
}else{ Write-Row "Python" "fail"; AddCheck "fail" }

if(Test-Cmd git){
    $ver = & git --version 2>&1 | Out-String | ForEach-Object { $_.Trim() }
    Write-Row "Git" "ok" $ver; AddCheck "ok"
}else{ Write-Row "Git" "fail"; AddCheck "fail" }

DrawSectionHeader "Deps Python"
# Verifier que chaque sous-module a ses dependances Python installees (import testable)
$deps = @(
    @{ name="notion_client"; mod="notion_client.api";  req="notion_client/pyproject.toml" },
    @{ name="ingestor";      mod="ingestor.engine";    req="ingestor/requirements.txt" },
    @{ name="bot";           mod="bot.config";         req="bot/requirements.txt" }
)

foreach($d in $deps){
    $status = "fail"; $detail = ""
    if(Test-Path $d.req){
        try{
            & python -c "import $($d.mod)" 2>&1 | Out-Null
            $status = "ok"; $detail = "module importable"
        }catch{ $status = "warn"; $detail = "pip install -r necessaire" }
    }else{ $detail = "$($d.req) absent" }
    Write-Row $d.name $status $detail; AddCheck $status
}

DrawSectionHeader "Services Docker"
# Verifier que Docker daemon tourne et chaque container (postgres, storage vectoriel) est Up/Exited/Dead
if(Test-Cmd docker){
    try{
        $ver = (docker --version 2>&1 | Out-String).Trim()
        Write-Row "Docker" "ok" $ver

        $containersRaw = docker ps --format "{{.Names}}:{{.Status}}" 2>&1
        if($? -and $containersRaw){
            foreach($c in $containersRaw){
                $colonIdx = $c.IndexOf(":")
                if($colonIdx -lt 0){ continue }
                $cname = $c.Substring(0, $colonIdx).Trim()
                $cstatText = $c.Substring($colonIdx + 1).Trim()

                $cstat = "warn"
                if($cstatText -match "^Up"){ $cstat = "ok" }
                elseif($cstatText -match "^Exited|^Dead"){ $cstat = "fail" }

                Write-Row "  container: $cname" $cstat $cstatText; AddCheck $cstat
            }
        }else{
            Write-Row "  containers" "warn" "injoignables ou aucun lance"; AddCheck "warn"
        }
    }catch{ Write-Row "Docker Daemon" "warn" $_; AddCheck "warn" }
}else{
    Write-Row "Docker" "warn"; AddCheck "warn"
}

DrawSectionHeader "LLM / Embedding"

if(Test-Cmd ollama){
    try{
        $ollamaList = ollama list 2>&1
        if($?){
            $ver = (ollama --version | Out-String).Trim()
            Write-Row "Ollama" "ok" $ver; AddCheck "ok"

            foreach($m in @("qwen3.6:35b-a3b", "nomic-embed-text")){
                if($ollamaList -match [regex]::Escape($m)){
                    Write-Row "  model: $m" "ok"; AddCheck "ok"
                }else{
                    Write-Row "  model: $m" "warn"; AddCheck "warn"
                }
            }
        }else{ Write-Row "Ollama Daemon" "warn"; AddCheck "warn" }
    }catch{ Write-Row "Ollama" "fail"; AddCheck "fail" }
}else{
    Write-Row "Ollama" "warn"; AddCheck "warn"
}

DrawSectionHeader "Database"

$storageUrl = "http://localhost:8000"
try{
    $resp = Invoke-WebRequest -Uri "$storageUrl/health" -TimeoutSec 3 -UseBasicParsing
    if($resp.StatusCode -eq 200){ Write-Row "Storage (SQLite)" "ok"; AddCheck "ok" }
    else{ Write-Row "Storage (SQLite)" "warn"; AddCheck "warn" }
}catch{
    Write-Row "Storage (SQLite)" "warn"; AddCheck "warn"
}

DrawSectionHeader ".env Configurations"

$envFiles = @(
    @{ path=".env.unified"; desc="Toutes les variables du projet (Discord, Ollama, Notion, Steam...)"; crit=$true }
)

foreach($ef in $envFiles){
    if(Test-Path $ef.path){
        $content = Get-Content $ef.path -Raw
        $hasReal = $content -match "=[^$]"
        if($hasReal){ Write-Row ".env $($ef.desc)" "ok"; AddCheck "ok" }
        else{ Write-Row ".env $($ef.desc)" "warn"; AddCheck "warn" }
    }else{
        $label = if($ef.crit){ "[CRITIQUE] .env $($ef.desc)" } else { ".env $($ef.desc) (optionnel)" }
        Write-Row $label "fail"; AddCheck $(if($ef.crit){ "fail" } else { "warn" })
    }
}

DrawSectionHeader "Automatisation"

if(Test-Cmd git){
    $hooksDir = Join-Path $PSScriptRoot ".git\hooks"
    if(Test-Path (Join-Path $hooksDir "pre-commit.cmd")){
        Write-Row "Pre-commit hook" "ok"; AddCheck "ok"
    }else{ Write-Row "Pre-commit hook" "warn"; AddCheck "warn" }
}else{
    Write-Row "Git hooks" "fail"; AddCheck "fail"
}

# ---- Summary ------------------------------------------------------
$pct = if($checks.total -gt 0){ [math]::Round(($checks.ok / $checks.total) * 100) } else { 0 }
$barLen = [math]::Floor($pct / 5); $barEmpty = 20 - $barLen

Write-Host ""
Write-Host "+------------------------------------------------------+" -ForegroundColor $Purple
Write-Host "|                                                      |" -ForegroundColor $DarkGray
Write-Host "  | Sante du projet: " -NoNewline -ForegroundColor $DarkGray
$barOk = ("#" * $barLen); $barEmptyStr = ("." * $barEmpty)
Write-Host "$barOk$barEmptyStr" -ForegroundColor $Purple -NoNewline
Write-Host " $($pct)%" -ForegroundColor $Yellow

$statText = "$($checks.ok) OK | $($checks.warn) warnings | $($checks.fail) critiques"
$statColor = if($checks.fail -eq 0){ "Green" } elseif($checks.warn -eq 0){ "Yellow" } else { "Red" }
Write-Host "  $statText" -ForegroundColor $statColor
Write-Host "|                                                      |" -ForegroundColor $DarkGray
Write-Host "+------------------------------------------------------+" -ForegroundColor $Purple

if($checks.fail -gt 0){
    Write-Host ""
    Write-Host "  Resolution rapide :" -ForegroundColor $Yellow
    Write-Host "    .\doctor.ps1 --repair   -- réparer automatiquement" -ForegroundColor $DarkGray
    Write-Host "    .\setup.ps1             -- installation complète" -ForegroundColor $DarkGray
}

Write-Host ""
