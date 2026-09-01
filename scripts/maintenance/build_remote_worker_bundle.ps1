[CmdletBinding()]
param([string]$ReferenceImage = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$templateRoot = Join-Path $projectRoot "deploy\remote_float_worker"
if (-not $ReferenceImage) {
    $ReferenceImage = Join-Path $projectRoot "assets\teacher\real-teacher-002.png"
}
$image = (Resolve-Path -LiteralPath $ReferenceImage).Path
if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw "Reference image is not a file." }
$bundleName = "remote_float_worker-" + (Get-Date -Format "yyyyMMdd-HHmmss") + "-" + [guid]::NewGuid().ToString("N").Substring(0, 8)
$bundleRoot = Join-Path (Join-Path $projectRoot "deploy\dist") $bundleName
# Always create a new bundle. Never delete or overwrite an existing deployment.
New-Item -ItemType Directory -Path $bundleRoot -ErrorAction Stop | Out-Null
$assetRoot = Join-Path $bundleRoot "assets"
New-Item -ItemType Directory -Path $assetRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot "float_worker\server.py") -Destination (Join-Path $bundleRoot "server.py")
Copy-Item -LiteralPath $image -Destination (Join-Path $assetRoot "teacher.png")
$templates = @("README.md", "requirements.txt", "config.sh", "worker.env.example", "run_worker.sh", "start_worker.sh", "stop_worker.sh", "check_worker.sh")
foreach ($name in $templates) {
    Copy-Item -LiteralPath (Join-Path $templateRoot $name) -Destination (Join-Path $bundleRoot $name)
}
foreach ($name in @("LICENSE", "THIRD_PARTY_NOTICES.md")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot $name) -Destination (Join-Path $bundleRoot $name)
}
Copy-Item -LiteralPath (Join-Path $projectRoot "assets\README.md") -Destination (Join-Path $assetRoot "README.md")
Write-Host "Remote FLOAT Worker bundle created: $bundleRoot"
Write-Host "No environment, weights or private worker.env included. Configure worker.env on the server."
