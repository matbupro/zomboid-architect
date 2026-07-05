#requires -Version 5.1
<#
.SYNOPSIS
    Audit complet du projet Zomboid_Architect (code, doc, annotations).

.DESCRIPTION
    Verifie: syntaxe parser PS, complétude documentation, ratio commentaires/code, fichiers suspects.
#>

$ProjectRoot = $PSScriptRoot
$ErrorActionPreference = "SilentlyContinue"

Write-Host "`n========================================" -ForegroundColor White
Write-Host "  RAPPORT COMPLET DU PROJET" -ForegroundColor White
Write-Host "  Zomboid_Architect" -ForegroundColor White
Write-Host "========================================`n" -ForegroundColor White

# ============================================================
# PHASE 1: Audit Code (syntaxe/parser)
# ============================================================
Write-Host "--- CODE (syntaxe/parser) ---" -ForegroundColor Magenta

$psFiles = Get-ChildItem -Path $ProjectRoot -Recurse -Include *.ps1,*.psm1 -File -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -notmatch '\\\.(git|vscode)\b' } | Sort-Object FullName

$parseResults = @()
foreach ($f in $psFiles) {
    $err = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$null, [ref]$err)
    if ($err.Count -eq 0) {
        $parseResults += [PSCustomObject]@{ file=$f.FullName.Substring($ProjectRoot.Length+1); errors=0; details=@() }
    } else {
        $details = @()
        foreach ($e in $err) {
            $details += "  L$($e.Extent.StartLineNumber): $($e.Message.Substring(0, [Math]::Min(120, $e.Message.Length)))"
        }
        $parseResults += [PSCustomObject]@{ file=$f.FullName.Substring($ProjectRoot.Length+1); errors=$err.Count; details=$details }
    }
}

$passCount = ($parseResults | Where-Object { $_.errors -eq 0 }).Count
$failCount = ($parseResults | Where-Object { $_.errors -gt 0 }).Count
foreach ($r in $parseResults) {
    if ($r.errors -eq 0) {
        Write-Host "  [PASS] $($r.file)" -ForegroundColor Green
    } else {
        Write-Host "  [FAIL] $($r.file) -- $($r.errors) erreurs" -ForegroundColor Red
        foreach ($d in $r.details) { Write-Host "     $d" -ForegroundColor DarkRed }
    }
}
Write-Host "`n  Total: $($parseResults.Count) fichiers | PASS: $passCount | FAIL: $failCount`n" -ForegroundColor Cyan

# ============================================================
# PHASE 2: Audit Documentation
# ============================================================
Write-Host "--- DOCUMENTATION ---" -ForegroundColor Magenta

$docPatterns = @(
    'README.md', 'INSTALL.md', 'CHANGELOG.md', 'CONTRIBUTING.md',
    'agent/README.md', 'agent/todo.md', 'agent/architecture.md', 'agent/memories.md',
    'notion_client/README.md', 'bot/README.md', 'ingestor/README.md'
)

$docResults = @()
foreach ($dp in $docPatterns) {
    $fullDoc = Join-Path $ProjectRoot $dp
    if (Test-Path $fullDoc) {
        $content = Get-Content $fullDoc -Raw -Encoding utf8
        $lines = ($content -split "`n").Count
        $hasHeader = $content -match '^#{1,3} '
        $docResults += [PSCustomObject]@{ file=$dp; lines=$lines; chars=$content.Length; hasHeader=$hasHeader; exists=$true }
    } else {
        $docResults += [PSCustomObject]@{ file=$dp; lines=0; chars=0; hasHeader=$false; exists=$false }
    }
}

$missingDocs = $docResults | Where-Object { -not $_.exists }
foreach ($d in $docResults) {
    if ($d.exists) {
        $warn = if (-not $d.hasHeader) { " [pas de header]" } else { "" }
        Write-Host "  [OK] $($d.file): $($d.lines) lignes, $($d.chars) chars$warn" -ForegroundColor Green
    } else {
        Write-Host "  [MANQUANT] $($d.file)" -ForegroundColor Red
    }
}
Write-Host "`n  Documentation manquante: $($missingDocs.Count)/$($docResults.Count)`n" -ForegroundColor Cyan

# ============================================================
# PHASE 3: Audit Annotations/Commentaires
# ============================================================
Write-Host "--- ANNOTATIONS/COMMENTAIRES ---" -ForegroundColor Magenta

foreach ($f in $psFiles) {
    $content = Get-Content $f.FullName -Encoding utf8
    $totalLines = $content.Count
    $commentLines = 0
    $blankLines = 0
    foreach ($line in $content) {
        if ($line -match '^\s*#') { $commentLines++ }
        elseif ($line -match '^\s*$') { $blankLines++ }
    }
    $codeLines = $totalLines - $commentLines - $blankLines
    $pct = if ($totalLines -gt 3) { [math]::Round(($commentLines / $totalLines) * 100) } else { 0 }

    if ($totalLines -le 2) { continue }  # skip tiny files

    $icon = "?"
    $color = "White"
    if ($pct -ge 20) { $icon = "[OK]"; $color = "Green" }
    elseif ($pct -ge 10) { $icon = "[--]"; $color = "Yellow" }
    else { $icon = "[!!]"; $color = "Red" }

    Write-Host ("  $($icon.PadRight(5)) $($f.Name).PadLeft(25) $commentLines/$totalLines Lignes ($pct%)") -ForegroundColor $color
}

# ============================================================
# PHASE 4: Audit -- Signaux d'alerte generiques
# ============================================================
Write-Host "`n--- SIGNAUX D'ALERTE ---" -ForegroundColor Magenta

$alerts = @()

# TODOs/FIXMEs non resolves
$fixmeFiles = Get-ChildItem -Path $ProjectRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -match '\.(ps1|py|md)$' } |
    ForEach-Object {
        $content = Get-Content $_.FullName -Raw -Encoding utf8
        if ($content -match '(TODO|FIXME|HACK|XXX|BUG)') {
            [PSCustomObject]@{ file=$_.FullName.Substring($ProjectRoot.Length+1); match=$Matches[0] }
        }
    }

if ($fixmeFiles.Count -gt 0) {
    Write-Host "  [INFO] TODO/FIXME/HACK/XXX non resolves: $($fixmeFiles.Count)" -ForegroundColor Yellow
    foreach ($f in $fixmeFiles | Select-Object -First 15) {
        Write-Host "    - $($f.file): $($f.match)" -ForegroundColor DarkYellow
    }
} else {
    Write-Host "  [OK] Pas de TODO/FIXME/HACK/XXX" -ForegroundColor Green
}

# Fichiers vides ou quasi-vides
$emptyFiles = Get-ChildItem -Path $ProjectRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Length -eq 0 }
if ($emptyFiles.Count -gt 0) {
    Write-Host "  [!!] Fichiers vides: $($emptyFiles.Count)" -ForegroundColor Red
}

# .env files should NOT be committed
$envCommitted = Get-ChildItem -Path $ProjectRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^\.env$' -and $_.DirectoryName -notmatch '\.gitignore|example' }
if ($envCommitted.Count -gt 0) {
    Write-Host "  [!!] Fichiers .env potentiellement commits: $($envCommitted.Count)" -ForegroundColor Red
}

# Fichiers avec caracteres non-ASCII (peuvent casser le parser PS 5.1)
$nonAsciiFiles = @()
foreach ($f in $psFiles) {
    $content = [System.IO.File]::ReadAllText($f.FullName, [System.Text.Encoding]::UTF8)
    $hasNonAscii = $false
    for ($i = 0; $i -lt $content.Length; $i++) {
        $c = [int][char]$content[$i]
        if ($c -gt 127) { $hasNonAscii = $true; break }
    }
    if ($hasNonAscii) { $nonAsciiFiles += $f.FullName.Substring($ProjectRoot.Length+1) }
}
if ($nonAsciiFiles.Count -gt 0) {
    Write-Host "  [!!] Caractères non-ASCII (risque parser PS 5.1): $($nonAsciiFiles.Count)" -ForegroundColor Yellow
    foreach ($n in $nonAsciiFiles) { Write-Host "    - $n" -ForegroundColor DarkYellow }
} else {
    Write-Host "  [OK] Pas de caracteres non-ASCII dans .ps1" -ForegroundColor Green
}

# ============================================================
# SCORE GLOBAL
# ============================================================
Write-Host "`n========================================" -ForegroundColor White
$codeScore = if ($parseResults.Count -gt 0) { [math]::Round(($passCount / $parseResults.Count) * 100) } else { 0 }

$warnItems = @()
if ($failCount -gt 0) { $warnItems += "Code" }
if ($missingDocs.Count -gt 0) { $warnItems += "Doc manquante" }
if ($fixmeFiles.Count -gt 0) { $warnItems += "TODO/FIXME" }
if ($nonAsciiFiles.Count -gt 0) { $warnItems += "Non-ASCII" }

Write-Host "  SCORE CODE: ${codeScore}%" -ForegroundColor $(if($codeScore -eq 100){'Green'}else{'Yellow'})
Write-Host "  DOC: $((($docResults.Count - $missingDocs.Count))/${docResults.Count}) presentes" -ForegroundColor $(if($missingDocs.Count -eq 0){'Green'}else{'Yellow'})
Write-Host "  ALERTES: $($warnItems.Count) categorie(s)" -ForegroundColor $(if($warnItems.Count -eq 0){'Green'}else{'Yellow'})

if ($warnItems.Count -gt 0) {
    Write-Host "`n  Categories a verifier:" -ForegroundColor Yellow
    foreach ($w in $warnItems) { Write-Host "    - $w" -ForegroundColor DarkYellow }
} else {
    Write-Host "`n  Tout est propre !" -ForegroundColor Green
}

Write-Host "`n========================================`n" -ForegroundColor White
