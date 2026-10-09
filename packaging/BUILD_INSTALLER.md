# Building the Windows Installer

AudioSuite-Pro ships as a self-contained Windows installer built with
[Inno Setup 6](https://jrsoftware.org/isinfo.php). The build script stages a
relocatable CPython runtime, the first-party source tree and all runtime
dependencies into a single directory, then compiles the installer from that
payload.

## Prerequisites

* **Python 3.11 or newer** with `uv` (the build script uses `uv python find` to
  locate a relocatable CPython runtime — whatever version `uv` has available).
* **Inno Setup 6.3+** — install with `winget install JRSoftware.InnoSetup`.
  The build script searches the default install paths; pass `-IscC` if you
  installed it elsewhere.
* **ffmpeg and ffprobe on PATH** (for runtime). These are NOT bundled by
  default — the installer documents them as a prerequisite. Pass
  `-BundleFFmpeg <dir>` to bundle them (see below).

## Quick start

From the repository root:

```pwsh
pwsh -File packaging\build_installer.ps1
```

This stages the suite, copies the runtime from `uv python find`,
installs dependencies into the bundled runtime, generates the Start Menu
shortcuts, and compiles the installer. The output lands in
`packaging\dist\AudioSuite-Pro-Setup-<version>.exe`.

To stage only (no Inno Setup compile):

```pwsh
pwsh -File packaging\build_installer.ps1 -NoCompile
```

The staged payload is in `packaging\build\app\` — you can inspect it before
compiling.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `-Version` | Read from `pyproject.toml` | Installer version string (e.g. `1.0.0`). |
| `-PythonExe` | `.venv\Scripts\python.exe` or `python` on PATH | Python used to read `pyproject.toml`. |
| `-RuntimeSource` | `uv python find` | Path to a relocatable CPython install (directory containing `python.exe` + `pythonw.exe`). |
| `-BundleFFmpeg` | *(none)* | Path to a directory containing `ffmpeg.exe` + `ffprobe.exe` to bundle in `bin\`. |
| `-OutputDir` | `packaging\dist` | Where the compiled `.exe` is written. |
| `-WorkDir` | `packaging\build` | Staging working directory. |
| `-IscC` | Auto-detected | Path to `ISCC.exe` if not in the default location. |
| `-SkipDeps` | `$false` | Skip `pip install` into the bundled runtime (useful for re-runs). |
| `-SkipRuntime` | `$false` | Skip copying the Python runtime (requires a previously staged runtime). |
| `-NoCompile` | `$false` | Stage the payload only; do not run Inno Setup. |

### Examples

```pwsh
# Use a specific Python runtime (not the uv-managed one)
pwsh -File packaging\build_installer.ps1 -RuntimeSource C:\python-build-standalone\cpython-3.14

# Bundle ffmpeg/ffprobe from a local install
pwsh -File packaging\build_installer.ps1 -BundleFFmpeg "C:\ffmpeg\bin"

# Stage only, then compile manually
pwsh -File packaging\build_installer.ps1 -NoCompile
ISCC.exe /DAppVersion=1.0.0 /DStagingDir="packaging\build\app" /DOutputDir="packaging\dist" packaging\audiosuite.iss
```

## What happens during a build

1. **Version resolution** — reads `[project].version` from `pyproject.toml`
   using the build interpreter.
2. **Suite staging** — copies the repository tree into `packaging\build\app\`
   via `robocopy /MIR`, excluding secrets (`audio_suite_config.json`,
   `*.key`), caches (`.venv`, `.git`, `__pycache__`), tests, and build
   tooling.
3. **Runtime staging** — copies the CPython runtime into
   `packaging\build\app\runtime\`. Virtualenvs are rejected (their
   `pyvenv.cfg` bakes in absolute paths and cannot be relocated).
4. **Dependency installation** — reads `[project].dependencies` plus the
   `analysis` and `cd-ripping` optional extras from `pyproject.toml` and
   installs them into the bundled runtime's `Lib\site-packages`.
5. **CLI shim** — writes `packaging\build\app\bin\audiosuite.cmd`, a
   relocatable batch file that resolves the runtime relative to itself
   (`%~dp0..\runtime\python.exe -m audio_suite_shared.cli_app`).
6. **Binary assertion** — verifies `fpcalc.exe` and `discid.dll` survived
   staging (both are committed at the repository root).
7. **Shortcut generation** — enumerates every `*.pyw` in the staged payload
   (except `Master_Driver.pyw`, which is defined explicitly in the Inno
   script) and writes `packaging\build\shortcuts.iss` with Start Menu
   entries.
8. **Inno Setup compile** — drives `ISCC.exe` with `/D` defines for version,
   staging directory, output directory and shortcut include path.

## What the installer does

The installer is a standard Inno Setup wizard:

* **Per-user install** at `%LOCALAPPDATA%\AudioSuite-Pro` (`PrivilegesRequired=lowest`).
  No elevation required. The suite writes its config (`audio_suite_config.json`)
  and logs next to its own source tree.
* **Start Menu** — "AudioSuite-Pro" group with Master Driver and every tool
  launcher.
* **Desktop shortcut** — optional task in the wizard.
* **CLI on PATH** — optional task appends `bin\` to the user's `PATH`
  environment variable (HKCU, `REG_EXPAND_SZ`).
* **Post-install launch** — offers to open the Master Driver after install.
* **License** — displays the GPL-3.0 `LICENSE` file from the staged payload.

### Installed layout

```
%LOCALAPPDATA%\AudioSuite-Pro\
  bin\audiosuite.cmd          CLI shim (relocatable)
  runtime\python.exe           bundled CPython (console)
  runtime\pythonw.exe          bundled CPython (GUI)
  runtime\Lib\site-packages\   all runtime dependencies
  Master_Driver.pyw            suite hub
  Audio_Refinery.pyw           refinery pipeline
  ...                          (30+ tool launchers)
  audio_suite_shared\          shared library
  fpcalc.exe                   Chromaprint runtime
  discid.dll                   CD Ripper disc identification
  LICENSE                      GPL-3.0
```

## Troubleshooting

### "uv could not locate a Python interpreter"

Run `uv python install` to fetch a relocatable CPython runtime, or pass
`-RuntimeSource` pointing to an existing python-build-standalone directory.

### "Runtime source is a virtualenv (pyvenv.cfg present) and is not relocatable"

The build script rejects virtualenvs because their `pyvenv.cfg` and script
launchers bake in absolute paths. Use a plain python-build-standalone
install instead (the kind `uv python` manages).

### "ISCC.exe was not found"

Install Inno Setup 6: `winget install JRSoftware.InnoSetup`. If installed
to a non-default location, pass `-IscC "C:\path\to\ISCC.exe"`.

### "Required bundled binaries are missing"

`fpcalc.exe` and `discid.dll` must be present at the repository root. Both
are committed — a fresh `git clone` includes them.

### CLI shim not working after install

The shim resolves the runtime relative to itself (`%~dp0`). If the `bin\`
directory is moved independently of `runtime\`, the path breaks. The shim
uses `python.exe` (console), not `pythonw.exe`, so CLI output is visible.