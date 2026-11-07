# Contrôle complet du projet Codex, hors ligne et sans effet de bord (convention Nexus : test.ps1 à la racine).
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
Write-Host "Vérification de l'intégrité des sources Codex..." -ForegroundColor Cyan
python (Join-Path $repoRoot "tools\ci\check-source-integrity.py")
Write-Host "Contrôle réussi (code 0)." -ForegroundColor Green
