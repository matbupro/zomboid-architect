#requires -Version 5.1
<#
.SYNOPSIS
    Auto-sync agent/ dossier depuis le code source et git (source of truth).

.DESCRIPTION
    Met a jour automatiquement les fichiers dans agent/.
    Peut s'executer manuellement ou via cron/task scheduler.

.PARAMETER LastSessionNotes
    Notes optionnelles sur les changements de la session.

.EXAMPLE
    .\agent\maintenance\sync_agent.ps1 "Fixed P0 bugs"
#>

param(
    [string]$LastSessionNotes = "",
    [switch]$Notion
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

# PSScriptRoot = agent/maintenance/ -> go up to project root
$ProjectRoot = ($PSScriptRoot | Split-Path -Parent) | Split-Path -Parent
$AgentDir    = Join-Path $ProjectRoot "agent"
$VERSIONFile = Join-Path $ProjectRoot "VERSION"
$Changelog   = Join-Path $ProjectRoot "CHANGELOG.md"

$today = Get-Date -Format "yyyy-MM-dd"

# Helper: UTF-8 BOM write
function Write-Utf8Bom {
    param([string]$FilePath, [string]$Text)
    $enc = [System.Text.Encoding]::UTF8
    $bytes = $enc.GetBytes($Text)
    [IO.File]::WriteAllBytes($FilePath, $bytes)
}

# Helper: git log
function GetGitLog {
    param([int]$Count = 30)
    try { return (git -C $ProjectRoot log --oneline -n $Count 2>$null).Trim() }
    catch { return "" }
}

# Helper: git tree
function GetGitTree {
    try { return (git -C $ProjectRoot ls-files).Split("`n") | Sort-Object }
    catch { return @("  (git not available)") }
}

Write-Host ""
Write-Host ">>> sync_agent.ps1 - MAJ agent/ dossier" -ForegroundColor Cyan
Write-Host "    Projet : $ProjectRoot" -ForegroundColor DarkGray

# ============ 1. syntax.md ============
$version = ""
if (Test-Path $VERSIONFile) { $version = (Get-Content $VERSIONFile -Raw).Trim() }

$logOutput = GetGitLog 10
$lastCommit = ""
if ($logOutput) { $firstLine = $logOutput.Split("`n")[0]; $lastCommit = ($firstLine -split " ")[0] }

$gitFiles = GetGitTree
$treeLines = @()
foreach ($f in $gitFiles) { $treeLines += "  |-- " + $f }
$treeStr = $treeLines -join "`r`n"

$syntaxMd = @"
# Etat Actuel du Projet

## Status
**Derniere MAJ agent/ : $today par sync_agent.ps1 automatique.**

Dernier commit : ${lastCommit}
Version moteur : ${version}

## Arborescence (git ls-files, mise a jour auto)

```
${treeStr}
```

## Fichiers Memoire Actifs

| Fichier | Role |
|---------|------|
| [GOAL.md](GOAL.md) | Objectif principal du projet + createur |
| [rules.md](rules.md) | 12 commandements + regles d'or |
| [todo.md](todo.md) | TODO list completee (mise a jour continue) |
| [architecture.md](architecture.md) | Stack technique, arborescence, flux, MCP |
| [memories.md](memories.md) | Souvenirs, infos utilisateur, astuces trouvees |
| [syntax.md](syntax.md) | Etat actuel du projet (ce fichier) |

## Contexte Technique

- **Projet :** ${ProjectRoot}
- **Createur :** ElChibros
- **Clef du dossier memoire :** agent/ - acces libre pour organisation interne de l'agent
- **Memoire Claude Code native :** ~/.claude/projects/f--Antigravity-DEV-Zomboid-Architect/memory/ (chargement automatique)

## Historique des MAJ agent/

| Date | Action | Detail |
|------|--------|--------|
| $today | sync_agent.ps1 | MAJ auto - tree, last commit, version |

"@

Write-Utf8Bom (Join-Path $AgentDir "syntax.md") $syntaxMd
Write-Host "    [OK] syntax.md" -ForegroundColor Green

# ============ 2. README.md (index) ============
$mdFiles = Get-ChildItem $AgentDir -File -Filter "*.md" | Where-Object { $_.BaseName -ne "README" } | ForEach-Object { $_.BaseName }

$descMap_GOAL = "Objectif principal du projet + createur"
$descMap_rules = "12 commandements + regles d'or du projet"
$descMap_todo = "TODO list completee (mise a jour continue)"
$descMap_architecture = "Stack technique, arborescence, flux de donnees, MCP"
$descMap_memories = "Souvenirs, infos utilisateur, astuces trouvees"
$descMap_syntax = "Etat actuel du projet (ce fichier)"

$tableRows = ""
foreach ($name in $mdFiles) {
    $d = "(non decrit)"
    if ($name -eq "GOAL") { $d = $descMap_GOAL }
    elseif ($name -eq "rules") { $d = $descMap_rules }
    elseif ($name -eq "todo") { $d = $descMap_todo }
    elseif ($name -eq "architecture") { $d = $descMap_architecture }
    elseif ($name -eq "memories") { $d = $descMap_memories }
    elseif ($name -eq "syntax") { $d = $descMap_syntax }
    $tableRows += "| " + $name + ".md | " + $d + "`r`n"
}

$readmeMd = @"
# Agent Memory - Dossier de Memoire Interne

Ceci est **mon** espace memoire. Le dossier agent/ contient tous mes fichiers de contexte organises par domaine pour limiter les pertes et hallucinations.

## Index des Fichiers

| Fichier | Role |
|---------|------|
${tableRows}
## Maintenance

- maintenance/sync_agent.ps1 - script de mise a jour automatique (lance manuellement ou via cron/task scheduler)
- Commande : agent\maintenance\sync_agent.ps1 "notes de session"
- S'execute automatiquement toutes les 24h via cron Windows

"@

Write-Utf8Bom (Join-Path $AgentDir "README.md") $readmeMd
Write-Host "    [OK] README.md (index memoires)" -ForegroundColor Green

# ============ 3. memories.md + todo.md (si notes fournies) ============
if ($LastSessionNotes) {
    $memPath = Join-Path $AgentDir "memories.md"
    if (Test-Path $memPath) {
        $oldMem = Get-Content $memPath -Raw -Encoding UTF8
        $newEntry = "`r`n## Session du ${today}`r`n${LastSessionNotes}"
        Write-Utf8Bom $memPath ($oldMem.TrimEnd() + "`r`n" + $newEntry)
        Write-Host "    [OK] memories.md (session ajoutee)" -ForegroundColor Green
    }

    $todoPath = Join-Path $AgentDir "todo.md"
    if (Test-Path $todoPath) {
        $oldTodo = Get-Content $todoPath -Raw -Encoding UTF8
        $marker = "`r`n## Sync auto: last_sync: ${today}"
        Write-Utf8Bom $todoPath ($oldTodo.TrimEnd() + "`r`n" + $marker)
        Write-Host "    [OK] todo.md (marqueur de sync)" -ForegroundColor Green
    }

    # Also update CHANGELOG
    if (Test-Path $Changelog) {
        $oldCl = Get-Content $Changelog -Raw -Encoding UTF8
        $logLines = @(GetGitLog 5).Split("`n") | Where-Object { $_ -and ($_ -notmatch "^Merge") }
        foreach ($cline in $logLines) {
            $parts = @($cline -split " ")
            $shortHash = $parts[0]
            $restMsg = ($cline.Substring($shortHash.Length + 1)).Trim()
            if ($oldCl -notlike "*$($restMsg.Substring(0, [Math]::Min(20, $restMsg.Length)))*") {
                $newEntry = "`r`n### ${today} - commit ${shortHash}`r`n`r`n**Changements :**`r`n- ${restMsg}"
                Write-Utf8Bom $Changelog ($oldCl.TrimEnd() + "`r`n" + $newEntry)
                Write-Host "    [OK] CHANGELOG.md (commit ajoute)" -ForegroundColor Green
                break
            }
        }
    }
} else {
    Write-Host "    [SKIP] todo/memories/CHANGELOG - aucune note fournies" -ForegroundColor DarkGray
}

# ============ 4. Notion sync (toujours) ============
try {
    $env:PYTHONUTF8 = '1'
    & python -m notion_client --push 2>&1 | Out-Null
    Write-Host "    [OK] Notion sync" -ForegroundColor Green
} catch {
    Write-Host "    [WARN] Notion sync echoue (clé API manquante ?) : $_" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "<<< sync termine." -ForegroundColor Cyan
