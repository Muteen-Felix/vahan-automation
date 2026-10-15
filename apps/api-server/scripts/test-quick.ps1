[CmdletBinding()]
param(
    [string]$TestPath = 'tests/test_api_handlers.py'
)

$ErrorActionPreference = 'Stop'
$apiRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $apiRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
}
$null = Get-Command docker -ErrorAction Stop

if ($TestPath -notmatch '^(tests|verification)([/\\].*)?$') {
    throw 'TestPath must point inside tests or verification.'
}

$containerName = 'vahan-api-quick-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$containerId = $null
$image = 'docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826'
$environmentNames = @(
    'DATABASE_URL',
    'VAHAN_ALLOW_DATABASE_CLEAR',
    'VAHAN_API_RUNNER_TOKEN',
    'VAHAN_UI_AUTH_TOKEN_SECRET',
    'VAHAN_BROWSER_STATE_KEY'
)
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Invoke-PythonStep([string[]]$Arguments) {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $pythonPath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($exitCode -ne 0) {
        throw "Python command failed with exit code ${exitCode}: $($Arguments -join ' ')"
    }
}

Push-Location $apiRoot
try {
    Write-Host 'Starting an isolated PostgreSQL test container...'
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $runOutput = & docker run --detach --rm --name $containerName `
            --env POSTGRES_USER=vahan `
            --env POSTGRES_PASSWORD=platform-test-password `
            --env POSTGRES_DB=vahan_api_test `
            --publish 127.0.0.1::5432 $image 2>&1
        $runExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    if ($runExitCode -ne 0) {
        $runOutput | ForEach-Object { Write-Host $_ }
        throw 'Could not start the isolated PostgreSQL container. Check that Docker is running.'
    }
    $containerId = [string]($runOutput | Where-Object { ([string]$_).Trim() -match '^[0-9a-f]{12,64}$' } | Select-Object -First 1)
    if (-not $containerId) {
        throw 'Docker started the test container but did not return its container ID.'
    }

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & docker exec $containerId pg_isready -U vahan -d vahan_api_test *> $null
            $ready = $LASTEXITCODE -eq 0
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if ($ready) { break }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw 'The isolated PostgreSQL container did not become ready within 60 seconds.'
    }

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $portOutput = & docker port $containerId '5432/tcp' 2>&1
        $portExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
    $portMatch = [regex]::Match([string]($portOutput | Select-Object -First 1), ':(?<port>\d+)\s*$')
    if ($portExitCode -ne 0 -or -not $portMatch.Success) {
        throw 'Could not determine the isolated PostgreSQL host port.'
    }

    $testEnvironment = @{
        DATABASE_URL = "postgresql+asyncpg://vahan:platform-test-password@127.0.0.1:$($portMatch.Groups['port'].Value)/vahan_api_test"
        VAHAN_ALLOW_DATABASE_CLEAR = 'test-only'
        VAHAN_API_RUNNER_TOKEN = 'platform-test-runner-token-0123456789'
        VAHAN_UI_AUTH_TOKEN_SECRET = 'platform-test-signing-secret-0123456789-abcdefghijklmnopqrstuvwxyz'
        VAHAN_BROWSER_STATE_KEY = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='
    }
    foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $testEnvironment[$name], 'Process')
    }

    Write-Host 'Applying API migrations to the disposable *_test database...'
    Invoke-PythonStep -Arguments @('-m', 'app.migrate')
    Write-Host "Running $TestPath..."
    Invoke-PythonStep -Arguments @('-m', 'pytest', $TestPath)
    Write-Host 'API tests passed.'
}
finally {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($containerId) {
            & docker stop $containerId *> $null
        }
        else {
            & docker rm --force $containerName *> $null
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
        }
        Pop-Location
    }
}
