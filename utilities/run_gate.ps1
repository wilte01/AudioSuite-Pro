$ErrorActionPreference = 'Continue'

$gateRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $gateRoot

function Invoke-GateStep {
    param(
        [string]$Label,
        [string]$Command
    )
    Write-Host "[START] $Label"
    Write-Host "        $Command"
    Invoke-Expression $Command
    $stepOk = $?
    $stepCode = $LASTEXITCODE
    if ($stepCode -ne 0 -or -not $stepOk) {
        if ($stepCode -eq 0) {
            $stepCode = 1
        }
        Write-Host "[ERROR] $Label (exit code $stepCode)"
        exit $stepCode
    }
    Write-Host "[OK] $Label"
}

Write-Host '[START] Phase Gate (six commands, stop at first failure)'

Invoke-GateStep -Label 'compileall' -Command "python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'"
Invoke-GateStep -Label 'ruff check' -Command 'python -m ruff check .'
Invoke-GateStep -Label 'ruff format --check' -Command 'python -m ruff format --check .'
Invoke-GateStep -Label 'mypy' -Command 'python -m mypy .'

$env:PYTHONUTF8 = '1'
Write-Host '[START] bandit'
Write-Host '        python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml'
# bandit exits 1 whenever ANY finding survives its default LOW/LOW filter, so
# the exit code alone cannot express this project's gate.  AGENTS defines a
# healthy result as 0 High / 0 Medium (the SEVERITY block; the confidence
# block is a different metric and must not be read here).  Exit 2 (tool
# error) and an unparseable severity section fail loudly, never vacuously.
$banditLines = @(& python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml 2>&1 |
    ForEach-Object { "$_" })
$banditCode = $LASTEXITCODE
foreach ($banditLine in $banditLines) {
    Write-Host $banditLine
}
$banditText = $banditLines | Out-String
$sevIdx = $banditText.IndexOf('Total issues (by severity):')
$confIdx = $banditText.IndexOf('Total issues (by confidence):')
$banditHigh = $null
$banditMedium = $null
$banditLow = $null
if ($sevIdx -ge 0 -and $confIdx -gt $sevIdx) {
    $sevSection = $banditText.Substring($sevIdx, $confIdx - $sevIdx)
    $mHigh = [regex]::Match($sevSection, '(?m)^\s*High:\s*(\d+)')
    $mMedium = [regex]::Match($sevSection, '(?m)^\s*Medium:\s*(\d+)')
    $mLow = [regex]::Match($sevSection, '(?m)^\s*Low:\s*(\d+)')
    if ($mHigh.Success) { $banditHigh = [int]$mHigh.Groups[1].Value }
    if ($mMedium.Success) { $banditMedium = [int]$mMedium.Groups[1].Value }
    if ($mLow.Success) { $banditLow = [int]$mLow.Groups[1].Value }
}
# $null -eq 0 is False, so a failed parse fails the step.
$banditOk = ($banditCode -eq 0) -or
    ($banditCode -eq 1 -and $banditHigh -eq 0 -and $banditMedium -eq 0)
if (-not $banditOk) {
    $banditExit = $banditCode
    if ($banditExit -eq 0) { $banditExit = 1 }
    Write-Host "[ERROR] bandit (exit $banditCode; severity High=$banditHigh Medium=$banditMedium Low=$banditLow)"
    exit $banditExit
}
Write-Host "[OK] bandit (severity 0 High / 0 Medium / $banditLow Low - Low findings are the documented subprocess call sites)"

Invoke-GateStep -Label 'pytest' -Command 'python -m pytest -q'

Write-Host '[DONE] Phase Gate passed'
exit 0
