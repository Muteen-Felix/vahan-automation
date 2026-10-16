[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$apiRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$repoRoot = (Resolve-Path (Join-Path $apiRoot '..\..')).Path
$pythonPath = Join-Path $apiRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonCommand = Get-Command python -ErrorAction Stop
    $pythonPath = $pythonCommand.Source
}
$null = Get-Command docker -ErrorAction Stop

$containerName = 'vahan-api-all-test-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$containerId = $null
$image = 'docker.io/library/postgres:17.11-bookworm@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826'
$coveragePath = Join-Path $env:TEMP ('vahan-api-coverage-' + [guid]::NewGuid().ToString('N'))
$environmentNames = @(
    'DATABASE_URL',
    'VAHAN_ALLOW_DATABASE_CLEAR',
    'VAHAN_API_RUNNER_TOKEN',
    'VAHAN_UI_AUTH_TOKEN_SECRET',
    'VAHAN_BROWSER_STATE_KEY',
    'COVERAGE_FILE',
    'PYTHONPATH',
    'VAHAN_TEST_ADMIN_URL',
    'VAHAN_TEST_DATABASE_NAMES',
    'VAHAN_ACCOUNT_TEST_DATABASE',
    'VAHAN_RESULT_TEST_DATABASE',
    'VAHAN_SESSION_TEST_DATABASE',
    'VAHAN_RETRY_TEST_DATABASE',
    'VAHAN_COVERAGE_TEST_DATABASE',
    'VAHAN_SCHEDULE_TEST_DATABASE',
    'VAHAN_QUEUE_TEST_DATABASE',
    'VAHAN_HISTORY_TEST_DATABASE',
    'VAHAN_LIFECYCLE_TEST_DATABASE',
    'VAHAN_QUEUE_MIGRATION_TEST_DATABASE',
    'VAHAN_DAILY_MIGRATION_TEST_DATABASE',
    'VAHAN_STATE_MIGRATION_TEST_DATABASE',
    'VAHAN_FIXTURE_POSTGRES_CONTAINER',
    'VAHAN_MIGRATION_SOURCE_DATABASE',
    'VAHAN_MIGRATION_TEST_DATABASE',
    'VAHAN_SHARED_TEST_DATABASE'
)
$originalEnvironment = @{}
foreach ($name in $environmentNames) {
    $originalEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}

function Set-ProcessEnvironment([hashtable]$Values) {
    foreach ($name in $Values.Keys) {
        [Environment]::SetEnvironmentVariable($name, [string]$Values[$name], 'Process')
    }
}

function Invoke-PythonStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [hashtable]$Environment = @{}
    )

    $previousEnvironment = @{}
    foreach ($key in $Environment.Keys) {
        $previousEnvironment[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], 'Process')
    }

    Write-Host "`n==> $Name"
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $pythonPath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousPreference
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previousEnvironment[$key], 'Process')
        }
    }
    if ($exitCode -ne 0) {
        throw "Failed ($exitCode): $Name"
    }
    Write-Host "<== PASS: $Name"
}

Push-Location $apiRoot
try {
    Write-Host 'Starting a disposable PostgreSQL container for API verification...'
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $runOutput = & docker run --detach --rm --name $containerName `
            --env POSTGRES_USER=vahan `
            --env POSTGRES_PASSWORD=platform-test-password `
            --env POSTGRES_DB=vahan `
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
            & docker exec $containerId pg_isready -U vahan -d vahan *> $null
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
    $hostPort = $portMatch.Groups['port'].Value
    $browserStateKey = 'MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA='
    if ([Convert]::FromBase64String($browserStateKey).Length -ne 32) {
        throw 'The test browser-state key must decode to exactly 32 bytes.'
    }

    Set-ProcessEnvironment @{
        DATABASE_URL = "postgresql+asyncpg://vahan:platform-test-password@127.0.0.1:$hostPort/vahan_api_test"
        VAHAN_ALLOW_DATABASE_CLEAR = 'test-only'
        VAHAN_API_RUNNER_TOKEN = 'platform-test-runner-token-0123456789'
        VAHAN_UI_AUTH_TOKEN_SECRET = 'platform-test-signing-secret-0123456789-abcdefghijklmnopqrstuvwxyz'
        VAHAN_BROWSER_STATE_KEY = $browserStateKey
        COVERAGE_FILE = $coveragePath
        VAHAN_TEST_ADMIN_URL = "postgresql://vahan:platform-test-password@127.0.0.1:$hostPort/vahan"
    }

    $databaseNames = @(
        'vahan_api_test',
        'vahan_results_platform_report_test',
        'vahan_results_platform_annual_test',
        'vahan_results_platform_profiles_test',
        'vahan_results_platform_contract_test',
        'vahan_results_platform_controls_test',
        'vahan_results_platform_update_test',
        'vahan_results_platform_pool_test',
        'vahan_session_platform_test',
        'vahan_retry_platform_test',
        'vahan_coverage_platform_test',
        'vahan_schedule_platform_test',
        'vahan_queue_platform_test',
        'vahan_shared_batch_platform_test',
        'vahan_account_platform_test',
        'vahan_history_platform_test',
        'vahan_lifecycle_platform_test',
        'vahan_migration_platform_test',
        'vahan_migration_daily_test',
        'vahan_results_platform_state_test',
        'vahan_results_platform_gate_test',
        'vahan_migration_platform_state_test'
    )
    $namesJson = ConvertTo-Json -InputObject $databaseNames -Compress
    $provisionDatabases = @'
import asyncio
import json
import os
import asyncpg

async def main():
    names = json.loads(os.environ['VAHAN_TEST_DATABASE_NAMES'])
    connection = await asyncpg.connect(os.environ['VAHAN_TEST_ADMIN_URL'])
    try:
        for name in names:
            await connection.execute(f'CREATE DATABASE "{name}"')
        print('Created {} disposable test databases.'.format(len(names)))
    finally:
        await connection.close()

asyncio.run(main())
'@
    Set-ProcessEnvironment @{ VAHAN_TEST_DATABASE_NAMES = $namesJson }
    Invoke-PythonStep -Name 'Create isolated test databases' -Arguments @('-c', $provisionDatabases)
    Invoke-PythonStep -Name 'Apply API schema migrations' -Arguments @('-m', 'app.migrate')

    Invoke-PythonStep -Name 'API native verification tests' -Arguments @(
        '-m', 'pytest',
        'verification/test_ocr_platform.py',
        'verification/test_captcha_ephemeral.py',
        'verification/test_captcha_refresh_race.py'
    )
    Invoke-PythonStep -Name 'API production configuration tests' -Arguments @('-m', 'pytest', 'verification/test_production_config.py')

    $scriptTests = @(
        'test_deployment_guard.py',
        'test_worker_capacity.py',
        'test_container_scan.py',
        'test_postgres_pin.py',
        'test_nginx_conf.py',
        'test_image_labels.py',
        'test_evidence_check.py',
        'test_release_smoke.py',
        'test_review_package.py',
        'test_config_template.py',
        'test_check_test_registration.py'
    )
    foreach ($testFile in $scriptTests) {
        Invoke-PythonStep -Name "Repository script tests: $testFile" -Arguments @('-m', 'unittest', 'discover', '-s', '../../scripts', '-p', $testFile)
    }
    Invoke-PythonStep -Name 'UI diagnostics contract test' -Arguments @('../../tools/ui-drift-guard/test_ui_diagnostics.py')
    Invoke-PythonStep -Name 'User state codec test' -Arguments @('scripts/test-user-state-codec.py')
    Invoke-PythonStep -Name 'Test registration check' -Arguments @('../../scripts/check-test-registration.py')
    Invoke-PythonStep -Name 'Ruff checks for API tests and supporting scripts' -Arguments @(
        '-m', 'ruff', 'check', '--config', 'pyproject.toml',
        '../../scripts', '../../tools', 'tests', 'verification', 'scripts'
    )

    Write-Host "`nRunning the PostgreSQL API verification and coverage suites..."
    Invoke-PythonStep -Name 'Core API tests with coverage' -Arguments @('-m', 'coverage', 'run', '--source=app/api', '-m', 'pytest', 'tests')
    Invoke-PythonStep -Name 'API permissions coverage tests' -Arguments @('-m', 'coverage', 'run', '--append', '--source=app/api', '-m', 'pytest', 'verification/test_permissions.py')
    Invoke-PythonStep -Name 'Runtime role lifecycle test' -Arguments @('../../scripts/test_runtime_role_lifecycle.py')
    Invoke-PythonStep -Name 'Database provisioning test' -Arguments @('../../scripts/test_provision_database.py')

    $coverageSuites = @(
        @{ Name = 'Account password'; Variable = 'VAHAN_ACCOUNT_TEST_DATABASE'; Database = 'vahan_account_platform_test'; File = 'test_account_passwords.py' },
        @{ Name = 'Report results'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_report_test'; File = 'test_report_results.py' },
        @{ Name = 'Annual reports'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_annual_test'; File = 'test_annual_reports.py' },
        @{ Name = 'Filter profiles'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_profiles_test'; File = 'test_filter_profiles.py' },
        @{ Name = 'UI contract'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_contract_test'; File = 'test_ui_contract.py' },
        @{ Name = 'Run controls'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_controls_test'; File = 'test_run_controls.py' },
        @{ Name = 'Update status'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_update_test'; File = 'test_update_status.py' },
        @{ Name = 'Worker pool'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_pool_test'; File = 'test_worker_pool.py' },
        @{ Name = 'Session limits'; Variable = 'VAHAN_SESSION_TEST_DATABASE'; Database = 'vahan_session_platform_test'; File = 'test_session_limits.py' },
        @{ Name = 'Retry sessions'; Variable = 'VAHAN_RETRY_TEST_DATABASE'; Database = 'vahan_retry_platform_test'; File = 'test_retry_sessions.py' },
        @{ Name = 'Report coverage'; Variable = 'VAHAN_COVERAGE_TEST_DATABASE'; Database = 'vahan_coverage_platform_test'; File = 'test_report_coverage.py' },
        @{ Name = 'Run schedules'; Variable = 'VAHAN_SCHEDULE_TEST_DATABASE'; Database = 'vahan_schedule_platform_test'; File = 'test_run_schedules.py' },
        @{ Name = 'Queue retry checkpoints'; Variable = 'VAHAN_QUEUE_TEST_DATABASE'; Database = 'vahan_queue_platform_test'; File = 'test_queue_retry_checkpoints.py' },
        @{ Name = 'Run history'; Variable = 'VAHAN_HISTORY_TEST_DATABASE'; Database = 'vahan_history_platform_test'; File = 'test_run_history.py' },
        @{ Name = 'Worker lifecycle'; Variable = 'VAHAN_LIFECYCLE_TEST_DATABASE'; Database = 'vahan_lifecycle_platform_test'; File = 'test_worker_lifecycle.py' },
        @{ Name = 'Queue migrations'; Variable = 'VAHAN_QUEUE_MIGRATION_TEST_DATABASE'; Database = 'vahan_migration_platform_test'; File = 'test_queue_migrations.py' },
        @{ Name = 'Daily schedule removal'; Variable = 'VAHAN_DAILY_MIGRATION_TEST_DATABASE'; Database = 'vahan_migration_daily_test'; File = 'test_daily_schedule_removal.py' },
        @{ Name = 'Runner state fencing'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_state_test'; File = 'test_runner_state_fencing.py' },
        @{ Name = 'Gate operations'; Variable = 'VAHAN_RESULT_TEST_DATABASE'; Database = 'vahan_results_platform_gate_test'; File = 'test_gate_ops.py' },
        @{ Name = 'State gate migration'; Variable = 'VAHAN_STATE_MIGRATION_TEST_DATABASE'; Database = 'vahan_migration_platform_state_test'; File = 'test_state_gate_migration.py' }
    )
    foreach ($suite in $coverageSuites) {
        Invoke-PythonStep -Name "$($suite.Name) coverage suite" `
            -Arguments @('-m', 'coverage', 'run', '--append', '--source=app/api', '-m', 'pytest', "verification/$($suite.File)") `
            -Environment @{ $suite.Variable = $suite.Database }
    }
    Invoke-PythonStep -Name 'API coverage threshold (90.1%)' -Arguments @('-m', 'coverage', 'report', '--fail-under=90.1', '--include=app/api/*')
    Invoke-PythonStep -Name 'jobs.py coverage threshold (90.1%)' -Arguments @('-m', 'coverage', 'report', '--fail-under=90.1', '--include=app/api/jobs.py')

    Invoke-PythonStep -Name 'Shared batch queue integration' `
        -Arguments @('verification/test_shared_batch_queue.py') `
        -Environment @{
            DATABASE_URL = "postgresql+asyncpg://vahan:platform-test-password@127.0.0.1:$hostPort/vahan_shared_batch_platform_test"
            PYTHONPATH = '.'
        }
    Invoke-PythonStep -Name 'Create synthetic migration fixtures' `
        -Arguments @('verification/prepare_report_test_fixtures.py') `
        -Environment @{ VAHAN_FIXTURE_POSTGRES_CONTAINER = $containerId }
    Invoke-PythonStep -Name 'Legacy report migration integration' `
        -Arguments @('verification/test_main_migration.py') `
        -Environment @{
            VAHAN_MIGRATION_SOURCE_DATABASE = 'vahan_results_round2_legacy_source_test'
            VAHAN_MIGRATION_TEST_DATABASE = 'vahan_results_round2_legacy_target_test'
        }
    Invoke-PythonStep -Name 'Shared report migration integration' `
        -Arguments @('verification/test_shared_migration.py') `
        -Environment @{ VAHAN_SHARED_TEST_DATABASE = 'vahan_results_round2_shared_target_test' }
    Invoke-PythonStep -Name 'Workbook migration integration' `
        -Arguments @('verification/test_main_live_workbook.py') `
        -Environment @{
            VAHAN_MIGRATION_SOURCE_DATABASE = 'vahan_results_round2_workbook_source_test'
            VAHAN_MIGRATION_TEST_DATABASE = 'vahan_results_round2_workbook_target_test'
        }

    Write-Host "`nAll API native, PostgreSQL integration, lint, registration, and coverage checks passed."
}
finally {
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($containerId) {
            Write-Host "Stopping isolated PostgreSQL test container $containerId..."
            & docker stop $containerId
            if ($LASTEXITCODE -ne 0) {
                & docker rm --force $containerId
            }
        }
        else {
            & docker rm --force $containerName
        }
    }
    finally {
        $ErrorActionPreference = $previousPreference
        foreach ($name in $environmentNames) {
            [Environment]::SetEnvironmentVariable($name, $originalEnvironment[$name], 'Process')
        }
        if (Test-Path -LiteralPath $coveragePath) {
            Remove-Item -LiteralPath $coveragePath -Force
        }
        Pop-Location
    }
}
