# build_installer.ps1 - AudioSuite-Pro Windows installer build (Route A).
#
# Route A ships a relocatable CPython runtime beside the first-party source
# tree and wraps both with Inno Setup.  It preserves the suite's launch model
# (`sys.executable <Tool>.pyw`, see audio_suite_shared/secure_subprocess.py and
# master_driver/batch_orchestrator.py), so every entry point keeps working from
# the installed copy with no code change:
#
#   * Master Driver      -> {app}\runtime\pythonw.exe {app}\Master_Driver.pyw
#   * Standalone tool    -> {app}\runtime\pythonw.exe {app}\<Tool>.pyw
#   * CLI / headless     -> {app}\bin\audiosuite.cmd (relocatable shim on PATH)
#
# The runtime is a python-build-standalone interpreter (the builds `uv`
# manages).  By default `uv python find` picks whatever version is
# available; pass -RuntimeSource to override.  A virtualenv is deliberately
# rejected: its pyvenv.cfg and script launchers bake in absolute paths, so
# it is not relocatable.
#
# Usage (from the repository root):
#   pwsh -File packaging\build_installer.ps1
#   pwsh -File packaging\build_installer.ps1 -RuntimeSource C:\py\cpython-3.14
#   pwsh -File packaging\build_installer.ps1 -BundleFFmpeg C:\ffmpeg\bin
#   pwsh -File packaging\build_installer.ps1 -NoCompile   # stage only
#
# ASCII-only status markers per AGENTS.md ('[OK]', '[START]', '[INFO]',
# '[ERROR]'); no Unicode symbols.

param(
    [string]$Version = "",
    [string]$PythonExe = "",
    [string]$RuntimeSource = "",
    [string]$BundleFFmpeg = "",
    [string]$OutputDir = "",
    [string]$WorkDir = "",
    [string]$IscC = "",
    [switch]$SkipDeps,
    [switch]$SkipRuntime,
    [switch]$NoCompile
)

$ErrorActionPreference = 'Stop'

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$script:AppDir = ""
$script:RuntimeDir = ""

#: Extract [project].version from pyproject.toml using the build interpreter.
$script:VersionScript = 'import sys, tomllib; print(tomllib.load(open(sys.argv[1], "rb"))["project"]["version"])'

#: Extract the runtime dependency list (main + analysis + cd-ripping extras)
#: from pyproject.toml, so the dependency source stays single-sourced.
$script:DepsScript = @'
import sys, tomllib
project = tomllib.load(open(sys.argv[1], "rb"))["project"]
optional = project.get("optional-dependencies", {})
deps = list(project.get("dependencies", []))
deps += optional.get("analysis", [])
deps += optional.get("cd-ripping", [])
print("\n".join(deps))
'@

#: Directories excluded from the staged application payload.  Excluded by
#: name so a per-package `tests/` tree is dropped too.  Secrets/config, caches
#: and build tooling never ship.
$script:ExcludeDirs = @(
    '.git', '.venv', '.mypy_cache', '.pytest_cache', '.ruff_cache',
    '.idea', '.junie', '.github', '__pycache__', 'packaging', 'build',
    'dist', 'logs', 'tests', 'audiosuite_pro.egg-info', 'htmlcov'
)

#: Files excluded from the staged application payload.  The `*_config.*` and
#: `*.key` entries are the runtime secret/config files (gitignored): the
#: installer must never ship them; the suite creates them on first run.
$script:ExcludeFiles = @(
    'audio_suite_config.json', 'audio_suite_config.json.lock',
    'audio_suite_config.key', 'album_art_config.json',
    'album_art_config.key', '*.key', '*.key.bak', '.coverage',
    '.coverage.*', '*.log', '*.spec', 'Thumbs.db', 'PLAN_*.md', 'AUDIT_*.md'
)

#: Binaries the suite needs out of the box.  Both are committed at the suite
#: root (fpcalc.exe is the Chromaprint runtime; discid.dll backs CD Ripper).
#: Staging asserts they survived robocopy, because a missing binary here is a
#: silent runtime failure on the user's machine.
$script:RequiredBinaries = @('fpcalc.exe', 'discid.dll')


function Write-Step {
    param([string]$Message)
    Write-Host "[START] $Message"
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message"
}

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message"
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message"
}

function Resolve-PythonExe {
    param([string]$Explicit)
    if ($Explicit) {
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $venv = Join-Path $script:RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $venv) {
        return $venv
    }
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    throw 'No Python interpreter found; pass -PythonExe or create .venv.'
}

function Get-ProjectVersion {
    param([string]$PythonExe, [string]$PyProject)
    $v = (& $PythonExe -c $script:VersionScript $PyProject).Trim()
    if (-not $v) {
        throw "Could not read [project].version from $PyProject."
    }
    return $v
}

function _Is-VenvPath {
    param([string]$Dir)
    if (Test-Path -LiteralPath (Join-Path $Dir 'pyvenv.cfg')) {
        return $true
    }
    $parent = Split-Path -Parent $Dir
    if ($parent -and (Test-Path -LiteralPath (Join-Path $parent 'pyvenv.cfg'))) {
        return $true
    }
    return $false
}

function _Find-StandaloneRuntime {
    param([string]$UvExe)
    $lines = @(& $UvExe python list --only-installed 2>&1)
    foreach ($line in $lines) {
        if ($line -notmatch '\S') { continue }
        if ($line -match '<download') { continue }
        # Format: "cpython-3.14.8-windows-x86_64-none    C:\...\python.exe"
        $parts = $line -split '\s{2,}'
        if ($parts.Count -lt 2) { continue }
        $exe = $parts[-1].Trim()
        if (-not (Test-Path -LiteralPath $exe)) { continue }
        $dir = Split-Path -Parent $exe
        if (-not (_Is-VenvPath $dir)) {
            return $dir
        }
    }
    throw (
        'No standalone Python runtime found. Run "uv python install" to ' +
        'fetch a relocatable CPython, or pass -RuntimeSource.'
    )
}

function Resolve-RuntimeSource {
    param([string]$Explicit)
    if ($Explicit) {
        $item = Get-Item -LiteralPath $Explicit
        $src = if ($item.PSIsContainer) {
            $item.FullName
        }
        else {
            Split-Path -Parent $item.FullName
        }
    }
    else {
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if (-not $uv) {
            throw 'uv was not found and no -RuntimeSource was supplied.'
        }
        $raw = (& uv python find 2>&1)
        if ($LASTEXITCODE -ne 0) {
            $msg = ($raw | Out-String).Trim()
            throw "uv could not locate a Python interpreter: $msg. Run 'uv python install' or pass -RuntimeSource."
        }
        $found = $raw.Trim()
        if (-not $found) {
            throw 'uv returned an empty path; pass -RuntimeSource explicitly.'
        }
        $src = Split-Path -Parent $found
        if (_Is-VenvPath $src) {
            Write-Info "uv python find returned a virtualenv ($found); searching for a standalone runtime."
            $src = _Find-StandaloneRuntime $uv.Source
        }
    }

    $py = Join-Path $src 'python.exe'
    $pyw = Join-Path $src 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $py)) {
        throw "Runtime source has no python.exe: $src"
    }
    if (-not (Test-Path -LiteralPath $pyw)) {
        throw "Runtime source has no pythonw.exe (needed for the GUI launchers): $src"
    }
    if (_Is-VenvPath $src) {
        throw "Runtime source is a virtualenv (pyvenv.cfg present) and is not relocatable: $src. Use a python-build-standalone install."
    }
    return $src
}

function Invoke-Robocopy {
    param([string[]]$Arguments, [string]$Label)
    & robocopy @Arguments | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed while $Label (exit $LASTEXITCODE)."
    }
}

function Copy-SuiteTree {
    param([string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $robocopyArgs = @(
        $script:RepoRoot, $Destination, '/MIR', '/NFL', '/NDL', '/NJH',
        '/NJS', '/NC', '/NS', '/NP', '/R:1', '/W:1'
    )
    foreach ($dir in $script:ExcludeDirs) {
        $robocopyArgs += '/XD'
        $robocopyArgs += $dir
    }
    foreach ($file in $script:ExcludeFiles) {
        $robocopyArgs += '/XF'
        $robocopyArgs += $file
    }
    Invoke-Robocopy -Arguments $robocopyArgs -Label 'staging the suite tree'
}

function Copy-RuntimeTree {
    param([string]$Source, [string]$Destination)
    $robocopyArgs = @(
        $Source, $Destination, '/MIR', '/NFL', '/NDL', '/NJH', '/NJS',
        '/NC', '/NS', '/NP', '/R:1', '/W:1'
    )
    Invoke-Robocopy -Arguments $robocopyArgs -Label 'staging the Python runtime'
}

function Install-RuntimeDependencies {
    param([string]$RuntimeDir, [string]$PythonExe, [string]$PyProject)
    $runtimePy = Join-Path $RuntimeDir 'python.exe'
    & $runtimePy -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Info 'pip missing from the bundled runtime; bootstrapping with ensurepip.'
        & $runtimePy -m ensurepip --upgrade | Out-Null
    }
    $deps = @(
        & $PythonExe -c $script:DepsScript $PyProject |
            Where-Object { $_ -and $_.Trim() -ne '' }
    )
    if ($deps.Count -eq 0) {
        throw "No runtime dependencies were read from $PyProject."
    }
    Write-Info ("Installing {0} runtime dependencies into the bundled runtime." -f $deps.Count)
    & $runtimePy -m pip install --no-warn-script-location --disable-pip-version-check @deps
    if ($LASTEXITCODE -ne 0) {
        throw "pip install into the bundled runtime failed (exit $LASTEXITCODE)."
    }
}

function New-CliShim {
    param([Parameter(Mandatory = $true)][string]$BinDir)
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    $shimPath = Join-Path $BinDir 'audiosuite.cmd'
    # %~dp0 is this file's folder (with trailing backslash), so the runtime is
    # located relative to the shim wherever the suite is installed.  python.exe
    # (console) is used, not pythonw.exe, or CLI/headless stdout would be lost.
    $shim = @'
@echo off
"%~dp0..\runtime\python.exe" -m audio_suite_shared.cli_app %*
'@
    Set-Content -LiteralPath $shimPath -Value $shim -Encoding ascii
    return $shimPath
}

function New-InstallerShortcutsInclude {
    param(
        [Parameter(Mandatory = $true)][string]$AppDir,
        [Parameter(Mandatory = $true)][string]$ShortcutsPath
    )
    # Master_Driver is declared explicitly in audiosuite.iss; every other
    # launcher is enumerated from the staged tree so the Start Menu cannot
    # drift from the shipped tools.  An empty result is refused loudly (a scan
    # that matches nothing must never pass vacuously).
    $pyws = @(
        Get-ChildItem -LiteralPath $AppDir -Filter '*.pyw' -File |
            Where-Object { $_.Name -ne 'Master_Driver.pyw' } |
            Sort-Object Name
    )
    if ($pyws.Count -eq 0) {
        throw "No tool launchers found under $AppDir; refusing to write an empty shortcuts include."
    }
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add('; Generated by build_installer.ps1 from the staged tool launchers - do not edit.')
    foreach ($pyw in $pyws) {
        $display = ($pyw.BaseName -replace '_', ' ')
        $line = 'Name: "{{group}}\{0}"; Filename: "{{app}}\runtime\pythonw.exe"; Parameters: """{{app}}\{1}"""; WorkingDir: "{{app}}"; IconFilename: "{{app}}\runtime\pythonw.exe"' -f $display, $pyw.Name
        $lines.Add($line)
    }
    $parent = Split-Path -Parent $ShortcutsPath
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Set-Content -LiteralPath $ShortcutsPath -Value $lines -Encoding ascii
    return $ShortcutsPath
}

function Assert-BundledBinaries {
    param([string]$AppDir)
    $missing = @(
        foreach ($binary in $script:RequiredBinaries) {
            if (-not (Test-Path -LiteralPath (Join-Path $AppDir $binary))) {
                $binary
            }
        }
    )
    if ($missing.Count -gt 0) {
        throw "Required bundled binaries are missing from the staged app: $($missing -join ', ')"
    }
}

function Resolve-IscC {
    param([string]$Explicit)
    if ($Explicit) {
        return (Resolve-Path -LiteralPath $Explicit).Path
    }
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Invoke-InstallerCompile {
    param(
        [string]$IscC, [string]$AppDir, [string]$OutputDir,
        [string]$Version, [string]$BundleFFmpeg, [string]$IssPath,
        [string]$ShortcutsPath
    )
    $defines = @(
        "/DAppVersion=$Version",
        "/DStagingDir=$AppDir",
        "/DOutputDir=$OutputDir",
        "/DShortcutsFile=$ShortcutsPath"
    )
    if ($BundleFFmpeg) {
        $defines += "/DBundleFFmpeg=$BundleFFmpeg"
    }
    & $IscC @defines $IssPath
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup compilation failed (exit $LASTEXITCODE)."
    }
}

function Main {
    $python = Resolve-PythonExe $PythonExe
    $pyproject = Join-Path $script:RepoRoot 'pyproject.toml'
    if (-not $Version) {
        $Version = Get-ProjectVersion -PythonExe $python -PyProject $pyproject
    }
    if (-not $WorkDir) {
        $WorkDir = Join-Path $PSScriptRoot 'build'
    }
    if (-not $OutputDir) {
        $OutputDir = Join-Path $PSScriptRoot 'dist'
    }
    $script:AppDir = Join-Path $WorkDir 'app'
    $script:RuntimeDir = Join-Path $script:AppDir 'runtime'
    $shortcutsPath = Join-Path $WorkDir 'shortcuts.iss'
    $issPath = Join-Path $PSScriptRoot 'audiosuite.iss'

    Write-Step "Building AudioSuite-Pro installer (version $Version)"
    New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

    Write-Step 'Staging the suite tree'
    Copy-SuiteTree -Destination $script:AppDir
    Write-Ok "Suite staged at $($script:AppDir)"

    if (-not $SkipRuntime) {
        Write-Step 'Resolving a relocatable Python runtime'
        $runtimeSource = Resolve-RuntimeSource $RuntimeSource
        Write-Info "Runtime source: $runtimeSource"
        Copy-RuntimeTree -Source $runtimeSource -Destination $script:RuntimeDir
        Write-Ok 'Runtime staged'
    }
    elseif (-not (Test-Path -LiteralPath (Join-Path $script:RuntimeDir 'python.exe'))) {
        throw "-SkipRuntime was set but no staged runtime exists at $($script:RuntimeDir)."
    }

    if (-not $SkipDeps) {
        Write-Step 'Installing runtime dependencies into the bundled runtime'
        Install-RuntimeDependencies -RuntimeDir $script:RuntimeDir -PythonExe $python -PyProject $pyproject
        Write-Ok 'Runtime dependencies installed'
    }

    Write-Step 'Writing the relocatable CLI shim'
    $shim = New-CliShim -BinDir (Join-Path $script:AppDir 'bin')
    Write-Ok "CLI shim written at $shim"

    if ($BundleFFmpeg) {
        if (-not (Test-Path -LiteralPath (Join-Path $BundleFFmpeg 'ffmpeg.exe'))) {
            throw "BundleFFmpeg does not contain ffmpeg.exe: $BundleFFmpeg"
        }
        Write-Step 'Bundling ffmpeg/ffprobe into bin\'
        Copy-Item -LiteralPath (Join-Path $BundleFFmpeg 'ffmpeg.exe') -Destination (Join-Path $script:AppDir 'bin') -Force
        Copy-Item -LiteralPath (Join-Path $BundleFFmpeg 'ffprobe.exe') -Destination (Join-Path $script:AppDir 'bin') -Force
        Write-Ok 'ffmpeg/ffprobe bundled'
    }

    Write-Step 'Verifying required bundled binaries'
    Assert-BundledBinaries -AppDir $script:AppDir
    Write-Ok 'fpcalc.exe and discid.dll are staged'

    Write-Step 'Generating Start Menu shortcut include'
    New-InstallerShortcutsInclude -AppDir $script:AppDir -ShortcutsPath $shortcutsPath | Out-Null
    Write-Ok "Shortcut include written at $shortcutsPath"

    $isc = Resolve-IscC $IscC
    if ($NoCompile -or -not $isc) {
        Write-Info 'Inno Setup (ISCC.exe) was not found; staging is complete.'
        Write-Info "Compile later with: ISCC.exe /DAppVersion=$Version /DStagingDir=`"$($script:AppDir)`" /DOutputDir=`"$OutputDir`" `"$issPath`""
        Write-Info 'Install Inno Setup 6 (winget install JRSoftware.InnoSetup) and re-run, or pass -IscC.'
        return
    }

    Write-Step 'Compiling the installer with Inno Setup'
    Invoke-InstallerCompile -IscC $isc -AppDir $script:AppDir -OutputDir $OutputDir -Version $Version -BundleFFmpeg $BundleFFmpeg -IssPath $issPath -ShortcutsPath $shortcutsPath
    Write-Ok "Installer written to $OutputDir"
}

# Execute only when run (not when dot-sourced for testing).
if ($MyInvocation.InvocationName -ne '.') {
    Main
}
