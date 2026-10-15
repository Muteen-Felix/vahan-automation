$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $repoRoot
try {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 scripts/run-docker.py @args
    } else {
        & python scripts/run-docker.py @args
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
