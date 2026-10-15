$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $repoRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 scripts/backup-docker.py
    } else {
        & python scripts/backup-docker.py
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
