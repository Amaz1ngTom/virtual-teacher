[CmdletBinding()]
param([string]$PythonExecutable = "python", [string]$WorkerHealthUrl = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

function Invoke-Checked {
    param([string]$Label, [scriptblock]$Command)
    Write-Host "[check] $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

Push-Location $projectRoot
try {
    Invoke-Checked "Python offline tests" { & $PythonExecutable -m unittest discover -s tests -v }
    Push-Location (Join-Path $projectRoot "frontend")
    try {
        Invoke-Checked "Frontend lint" { npm run lint }
        Invoke-Checked "Audio recorder tests" { node --experimental-strip-types --test tests/audio-recorder.test.mjs }
        Invoke-Checked "Frontend production build" { npm run build }
    }
    finally { Pop-Location }
    # Includes untracked release files; does not depend on private .git history.
    Invoke-Checked "Allowlisted release file scan" {
        & $PythonExecutable scripts/maintenance/export_github_source.py --check
    }
    if ($WorkerHealthUrl) {
        $health = Invoke-RestMethod -Uri $WorkerHealthUrl -TimeoutSec 15
        if ($health.status -ne "ready" -or -not $health.model_loaded) { throw "FLOAT Worker is not ready." }
        Write-Host "[ok] Optional Worker health check passed."
    }
    Write-Host "[ok] Existing-environment release checks passed without paid API or inference calls."
}
finally { Pop-Location }
