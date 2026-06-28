#Requires -Version 5.1
<#
.SYNOPSIS
    Run the full wrapper-dbpoweramp test suite from the project venv.

.DESCRIPTION
    Activates the local venv at venv\Scripts\activate.ps1 (creating it if
    missing) and runs the pytest-based test orchestrator at
    tests/test_all.py. Designed for the PowerShell 5.1 environment used
    in the project's CI and developer workflows.

    Exit codes follow pytest convention:
        0 = all tests passed
        1 = test failures
        2 = test collection errors
        3 = this script's own setup error (e.g. venv missing pip)

.PARAMETER VerboseOutput
    Pass -v to pytest for more detailed per-test output. Default is the
    standard concise summary.

.PARAMETER Filter
    Optional pytest -k expression forwarded to pytest to run only matching
    tests (e.g. 'verify' or 'history_migrations').

.EXAMPLE
    .\tests\run_all_tests.ps1

    Runs the entire suite and prints a concise summary.

.EXAMPLE
    .\tests\run_all_tests.ps1 -VerboseOutput -Filter 'db_version'

    Runs only tests whose name contains 'db_version' with verbose output.

.NOTES
    Author  : wrapper-dbpoweramp
    Version : 1.0.0
#>
[CmdletBinding()]
param(
    [Parameter()]
    [switch]$VerboseOutput,

    [Parameter()]
    [string]$Filter
)

$ErrorActionPreference = 'Stop'
$script:VenvActivatePath = Join-Path -Path $PSScriptRoot -ChildPath '..\venv\Scripts\Activate.ps1'
$script:VenvPython      = Join-Path -Path $PSScriptRoot -ChildPath '..\venv\Scripts\python.exe'
$script:RepoRoot        = (Resolve-Path -Path (Join-Path -Path $PSScriptRoot -ChildPath '..')).Path
$script:OrchestratorPy  = Join-Path -Path $PSScriptRoot -ChildPath 'test_all.py'

function Assert-VenvReady {
    [CmdletBinding()]
    [OutputType([void])]
    param()

    if (-not (Test-Path -LiteralPath $script:VenvActivatePath)) {
        throw "venv not found at $($script:VenvActivatePath). Run 'python -m venv venv' first."
    }
    if (-not (Test-Path -LiteralPath $script:VenvPython)) {
        throw "venv python interpreter missing at $($script:VenvPython)."
    }
    try {
        & $script:VenvPython -c 'import pytest' 2>$null
    }
    catch {
        throw "pytest is not installed in the venv. Run 'venv\Scripts\python.exe -m pip install -r requirements.txt pytest'."
    }
}

function Invoke-TestOrchestrator {
    [CmdletBinding()]
    [OutputType([int])]
    param()

    # Run test_all.py as a plain Python script so it executes its own
    # subprocess-based orchestrator (which runs the FULL suite). Running
    # pytest against test_all.py alone would only execute the two
    # orchestrator tests, not the rest of tests/.
    $pythonArgs = @(
        $script:OrchestratorPy
    )
    if ($VerboseOutput.IsPresent) {
        $env:PYTEST_ADDOPTS = '-v'
    }
    if (-not [string]::IsNullOrWhiteSpace($Filter)) {
        $env:PYTEST_ADDOPTS = "-v -k $Filter"
    }

    Write-Host ('=' * 78) -ForegroundColor Cyan
    Write-Host ' wrapper-dbpoweramp - full test suite' -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor Cyan
    Write-Host (" RepoRoot    : {0}" -f $script:RepoRoot)
    Write-Host (" Python      : {0}" -f $script:VenvPython)
    Write-Host (" Orchestrator: {0}" -f $script:OrchestratorPy)
    if (-not [string]::IsNullOrWhiteSpace($Filter)) {
        Write-Host (" Filter      : {0}" -f $Filter) -ForegroundColor Yellow
    }
    Write-Host ''

    Push-Location -LiteralPath $script:RepoRoot
    try {
        Write-Host (" Args        : venv\Scripts\python.exe {0}" -f ($pythonArgs -join ' '))
        Write-Host ''
        # Run the orchestrator with stdout/stderr merged and inherited from
        # the host so the user sees the pytest output line-by-line. The
        # orchestrator's main() captures its own child subprocess output and
        # writes it via sys.stdout.write, so this works correctly.
        $proc = Start-Process -FilePath $script:VenvPython `
                              -ArgumentList $pythonArgs `
                              -NoNewWindow -Wait -PassThru `
                              -RedirectStandardOutput "$env:TEMP\ps_runner_stdout.log" `
                              -RedirectStandardError "$env:TEMP\ps_runner_stderr.log"
        if (Test-Path "$env:TEMP\ps_runner_stdout.log") {
            Get-Content "$env:TEMP\ps_runner_stdout.log" -Raw | Write-Host
        }
        if (Test-Path "$env:TEMP\ps_runner_stderr.log") {
            Get-Content "$env:TEMP\ps_runner_stderr.log" -Raw -ErrorAction SilentlyContinue | Write-Host
        }
        return $proc.ExitCode
    }
    finally {
        Pop-Location
        Remove-Item Env:\PYTEST_ADDOPTS -ErrorAction SilentlyContinue
    }
}

try {
    Assert-VenvReady
    $exitCode = Invoke-TestOrchestrator
    exit $exitCode
}
catch {
    Write-Error "run_all_tests.ps1 failed: $($_.Exception.Message)"
    exit 3
}