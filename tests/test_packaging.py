"""Contract locks for the Windows installer scaffolding (Route A).

The installer is not built in CI (Inno Setup is a Windows tool), so these
tests are the only thing that keeps ``packaging/build_installer.ps1`` and
``packaging/audiosuite.iss`` honest. They work at two layers:

1. *Static contract* — the two build files carry the documented parameters,
   exclusions and Inno Setup directives. A silent drift here would only
   surface as a broken installer on someone else's machine.
2. *PowerShell behaviour* — the real ``build_installer.ps1`` is dot-sourced
   (so ``Main`` must NOT run) and its functions are exercised against
   synthetic trees: the relocatable CLI shim, the generated shortcut
   include, the bundled-binary assertion, the venv rejection and the
   pyproject version reader.

The end-to-end staging run copies the real repository tree and asserts the
payload a user would actually receive: tool launchers present, secrets
absent, binaries staged.

Skipped (attributably) where ``pwsh`` is not on PATH, so a Linux collector
still gathers the static layer.

Changed in 2.1.6: the PowerShell runs carry deadlines. ``subprocess.run`` with
no ``timeout`` means a script waiting on something - a prompt, a locked file -
hangs the suite until GitHub's six-hour cap, and the first 3.14 CI leg was
cancelled at 6% in exactly this stretch of the collection order. A timeout
fails the test with the captured output instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING = REPO_ROOT / "packaging"
BUILD_PS1 = PACKAGING / "build_installer.ps1"
ISS = PACKAGING / "audiosuite.iss"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


#: The runtime secret/config files the installer must never ship. Mirrors
#: ``build_installer.ps1``'s ``ExcludeFiles``; asserted there and here so the
#: list cannot quietly lose an entry.
SECRET_FILES = (
    "audio_suite_config.json",
    "audio_suite_config.json.lock",
    "audio_suite_config.key",
    "album_art_config.json",
    "album_art_config.key",
)

#: Binaries the suite needs out of the box (Chromaprint runtime + CD Ripper).
REQUIRED_BINARIES = ("fpcalc.exe", "discid.dll")

MASTER_DRIVER = "Master_Driver.pyw"

_PWSH = shutil.which("pwsh")

requires_pwsh = pytest.mark.skipif(
    _PWSH is None, reason="pwsh is not on PATH; PowerShell layer cannot run"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_harness(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    """Run a PowerShell snippet that dot-sources the real build script.

    Args:
        tmp_path: pytest temp directory for the harness file.
        body: PowerShell statements placed after the dot-source.

    Returns:
        The completed process (stdout/stderr captured, UTF-8).
    """
    assert _PWSH is not None
    harness = tmp_path / "harness.ps1"
    script = (
        f"$ErrorActionPreference = 'Stop'\n. '{BUILD_PS1.as_posix()}'\n" + body + "\n"
    )
    harness.write_text(script, encoding="utf-8")
    return subprocess.run(
        [_PWSH, "-NoProfile", "-File", str(harness)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )


# ---------------------------------------------------------------------------
# Layer 1 — static contract of build_installer.ps1
# ---------------------------------------------------------------------------


class TestBuildScriptParameters:
    """Every documented switch must exist and be typed as documented."""

    def test_both_build_files_exist(self) -> None:
        assert BUILD_PS1.is_file()
        assert ISS.is_file()

    def test_all_documented_parameters_are_declared(self) -> None:
        text = _read(BUILD_PS1)
        for name in (
            "$Version",
            "$PythonExe",
            "$RuntimeSource",
            "$BundleFFmpeg",
            "$OutputDir",
            "$WorkDir",
            "$IscC",
            "$SkipDeps",
            "$SkipRuntime",
            "$NoCompile",
        ):
            assert name in text, f"{name} missing from the param block"

    def test_the_script_only_runs_main_when_invoked(self) -> None:
        """The dot-source guard is what makes the PowerShell tests possible,
        and what stops a stray call from building a whole installer."""
        text = _read(BUILD_PS1)
        assert "if ($MyInvocation.InvocationName -ne '.')" in text
        assert "Main" in text
        guard_at = text.index("if ($MyInvocation.InvocationName -ne '.')")
        assert "Main" in text[guard_at:]


class TestStagingExclusions:
    """Secrets, caches and build tooling must never reach the payload."""

    def test_every_secret_file_is_excluded(self) -> None:
        text = _read(BUILD_PS1)
        for name in SECRET_FILES:
            assert f"'{name}'" in text, f"{name} is not excluded from staging"

    def test_key_material_is_excluded_by_pattern(self) -> None:
        text = _read(BUILD_PS1)
        assert "'*.key'" in text
        assert "'*.key.bak'" in text

    def test_build_and_cache_directories_are_excluded(self) -> None:
        text = _read(BUILD_PS1)
        for name in (".git", ".venv", "packaging", "dist", "logs", "tests"):
            assert f"'{name}'" in text, f"{name} is not excluded from staging"

    def test_the_required_binaries_are_asserted(self) -> None:
        text = _read(BUILD_PS1)
        for name in REQUIRED_BINARIES:
            assert f"'{name}'" in text, f"{name} is not asserted after staging"
        assert "Assert-BundledBinaries" in text


class TestCliShimContract:
    """The CLI entry point must survive relocation to any install path."""

    def test_the_shim_resolves_the_runtime_relative_to_itself(self) -> None:
        text = _read(BUILD_PS1)
        assert "%~dp0" in text
        assert "..\\runtime\\python.exe" in text

    def test_the_shim_uses_the_console_interpreter(self) -> None:
        """pythonw.exe would swallow stdout, breaking CLI/headless output."""
        text = _read(BUILD_PS1)
        assert "-m audio_suite_shared.cli_app" in text
        shim_block = text[
            text.index("$shim = @'") : text.index("'@", text.index("$shim = @'"))
        ]
        assert "pythonw" not in shim_block


class TestShortcutGeneration:
    """Start Menu entries come from the staged launchers, not a hand list."""

    def test_master_driver_is_excluded_from_the_generated_include(self) -> None:
        text = _read(BUILD_PS1)
        assert "$_.Name -ne 'Master_Driver.pyw'" in text

    def test_generated_include_uses_semicolon_comments(self) -> None:
        """'#' is an ISPP directive; a '#' comment would break compilation."""
        text = _read(BUILD_PS1)
        assert "'; Generated by build_installer.ps1" in text
        marker = text.index("$lines.Add('; Generated by build_installer.ps1")
        tail = text[marker : text.index("\nfunction", marker)]
        assert "# " not in tail

    def test_an_empty_launcher_scan_is_refused_loudly(self) -> None:
        text = _read(BUILD_PS1)
        assert "refusing to write an empty shortcuts include" in text

    def test_display_names_are_spaced_from_the_file_stem(self) -> None:
        assert "-replace '_', ' '" in _read(BUILD_PS1)


class TestRuntimeSourceContract:
    """A virtualenv cannot be relocated, so it must be rejected up front."""

    def test_a_pyvenv_cfg_is_rejected(self) -> None:
        text = _read(BUILD_PS1)
        assert "pyvenv.cfg" in text
        assert "not relocatable" in text

    def test_both_interpreters_are_required(self) -> None:
        text = _read(BUILD_PS1)
        assert "python.exe" in text
        assert "pythonw.exe" in text
        assert "no pythonw.exe" in text


# ---------------------------------------------------------------------------
# Layer 1 — static contract of audiosuite.iss
# ---------------------------------------------------------------------------


class TestInnoSetupContract:
    def test_the_install_is_per_user_and_writable(self) -> None:
        """The suite writes config/logs next to its own source tree, so the
        install location must be user-writable without elevation."""
        text = _read(ISS)
        assert "PrivilegesRequired=lowest" in text
        assert "DefaultDirName={localappdata}\\AudioSuite-Pro" in text

    def test_the_appid_is_stable(self) -> None:
        text = _read(ISS)
        assert "AppId={{B7F2C1E4-5A3D-4E9B-8C6F-1D2E3F4A5B6C}" in text

    def test_the_version_is_injected_with_a_compile_time_fallback(self) -> None:
        text = _read(ISS)
        assert "#ifndef AppVersion" in text
        assert "#define AppVersion" in text
        assert "AppVersion={#AppVersion}" in text

    def test_the_staged_payload_is_installed_recursively(self) -> None:
        text = _read(ISS)
        assert 'Source: "{#StagingDir}\\*"' in text
        assert "recursesubdirs" in text
        assert "createallsubdirs" in text

    def test_master_driver_icon_and_generated_shortcuts_are_declared(self) -> None:
        text = _read(ISS)
        assert 'Parameters: """{app}\\{#MasterLauncher}"""' in text
        assert "#include ShortcutsFile" in text

    def test_the_cli_shim_is_put_on_the_user_path(self) -> None:
        text = _read(ISS)
        assert 'Root: HKCU; Subkey: "Environment"' in text
        assert 'ValueName: "Path"' in text
        assert "{app}\\bin" in text
        assert "NeedsAddPath" in text

    def test_a_postinstall_launch_is_offered(self) -> None:
        text = _read(ISS)
        assert "[Run]" in text
        assert "postinstall" in text
        assert "skipifsilent" in text

    def test_the_licence_is_read_from_the_staged_payload(self) -> None:
        text = _read(ISS)
        assert "LicenseFile={#StagingDir}\\LICENSE" in text
        assert "FileExists(AddBackslash(StagingDir)" in text


# ---------------------------------------------------------------------------
# Layer 2 — PowerShell behaviour (real script, dot-sourced)
# ---------------------------------------------------------------------------


@requires_pwsh
class TestPowerShellFunctions:
    def test_dot_sourcing_does_not_build_an_installer(self, tmp_path: Path) -> None:
        result = _run_harness(tmp_path, 'Write-Output "DOT-SOURCED-OK"')
        assert result.returncode == 0, result.stderr
        assert "DOT-SOURCED-OK" in result.stdout
        assert "[START] Building" not in result.stdout

    def test_get_project_version_reads_pyproject(self, tmp_path: Path) -> None:
        with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
            expected = tomllib.load(handle)["project"]["version"]
        body = (
            "$v = Get-ProjectVersion -PythonExe "
            f"'{sys.executable}' "
            f"-PyProject '{(REPO_ROOT / 'pyproject.toml').as_posix()}'\n"
            'Write-Output "VERSION=$v"'
        )
        result = _run_harness(tmp_path, body)
        assert result.returncode == 0, result.stderr
        assert f"VERSION={expected}" in result.stdout

    def test_cli_shim_is_relocatable(self, tmp_path: Path) -> None:
        bin_dir = tmp_path / "bin"
        body = (
            f"$shim = New-CliShim -BinDir '{bin_dir.as_posix()}'\n"
            'Write-Output "SHIM=$shim"'
        )
        result = _run_harness(tmp_path, body)
        assert result.returncode == 0, result.stderr
        shim = tmp_path / "bin" / "audiosuite.cmd"
        assert shim.is_file()
        content = shim.read_text(encoding="ascii")
        assert "%~dp0" in content
        assert "..\\runtime\\python.exe" in content
        assert "-m audio_suite_shared.cli_app" in content
        assert "pythonw" not in content

    def test_shortcut_include_lists_launchers_but_not_master_driver(
        self, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        for name in (MASTER_DRIVER, "Audio_Refinery.pyw", "Tag_Editor.pyw"):
            (app_dir / name).write_text("", encoding="utf-8")
        (app_dir / "not_a_launcher.txt").write_text("", encoding="utf-8")
        shortcuts = tmp_path / "shortcuts.iss"
        body = (
            f"New-InstallerShortcutsInclude -AppDir '{app_dir.as_posix()}' "
            f"-ShortcutsPath '{shortcuts.as_posix()}' | Out-Null"
        )
        result = _run_harness(tmp_path, body)
        assert result.returncode == 0, result.stderr
        text = shortcuts.read_text(encoding="ascii")
        assert "Audio Refinery" in text
        assert "Tag Editor" in text
        assert "Master_Driver.pyw" not in text
        assert "not_a_launcher" not in text
        assert text.startswith("; Generated by build_installer.ps1")
        for line in text.splitlines():
            assert not line.startswith("#"), f"ISPP directive leaked: {line!r}"

    def test_shortcut_include_refuses_an_empty_launcher_set(
        self, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        (app_dir / MASTER_DRIVER).write_text("", encoding="utf-8")
        shortcuts = tmp_path / "shortcuts.iss"
        body = (
            f"New-InstallerShortcutsInclude -AppDir '{app_dir.as_posix()}' "
            f"-ShortcutsPath '{shortcuts.as_posix()}'"
        )
        result = _run_harness(tmp_path, body)
        assert result.returncode != 0
        clean_stderr = _strip_ansi(result.stderr)
        assert "empty shortcuts include" in clean_stderr
        assert not shortcuts.exists()

    def test_assert_bundled_binaries_passes_then_names_the_missing_one(
        self, tmp_path: Path
    ) -> None:
        app_dir = tmp_path / "app"
        app_dir.mkdir()
        for name in REQUIRED_BINARIES:
            (app_dir / name).write_bytes(b"stub")
        app_posix = app_dir.as_posix()
        body = (
            f"Assert-BundledBinaries -AppDir '{app_posix}'\n"
            'Write-Output "ALL-PRESENT"\n'
            f"Remove-Item -LiteralPath (Join-Path '{app_posix}' 'discid.dll')\n"
            f"Assert-BundledBinaries -AppDir '{app_posix}'"
        )
        result = _run_harness(tmp_path, body)
        assert "ALL-PRESENT" in result.stdout
        assert result.returncode != 0
        clean = _strip_ansi(result.stderr)
        assert "discid.dll" in clean
        assert "missing" in clean.lower()

    def test_resolve_runtime_source_rejects_a_venv(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "python.exe").write_bytes(b"stub")
        (venv / "pythonw.exe").write_bytes(b"stub")
        (venv / "pyvenv.cfg").write_text("home = C:\\Python\n", encoding="utf-8")
        body = f"Resolve-RuntimeSource -Explicit '{venv.as_posix()}'"
        result = _run_harness(tmp_path, body)
        assert result.returncode != 0
        assert "not relocatable" in _strip_ansi(result.stderr)

    def test_resolve_runtime_source_rejects_venv_pyvenv_in_parent(
        self, tmp_path: Path
    ) -> None:
        venv = tmp_path / ".venv"
        scripts = venv / "Scripts"
        scripts.mkdir(parents=True)
        (scripts / "python.exe").write_bytes(b"stub")
        (scripts / "pythonw.exe").write_bytes(b"stub")
        (venv / "pyvenv.cfg").write_text("home = C:\\Python\n", encoding="utf-8")
        body = f"Resolve-RuntimeSource -Explicit '{scripts.as_posix()}'"
        result = _run_harness(tmp_path, body)
        assert result.returncode != 0
        assert "not relocatable" in _strip_ansi(result.stderr)

    def test_resolve_runtime_source_accepts_a_plain_runtime(
        self, tmp_path: Path
    ) -> None:
        runtime = tmp_path / "runtime"
        runtime.mkdir()
        (runtime / "python.exe").write_bytes(b"stub")
        (runtime / "pythonw.exe").write_bytes(b"stub")
        body = (
            f"$src = Resolve-RuntimeSource -Explicit '{runtime.as_posix()}'\n"
            'Write-Output "SRC=$src"'
        )
        result = _run_harness(tmp_path, body)
        assert result.returncode == 0, result.stderr
        resolved = result.stdout.split("SRC=", 1)[1].strip().replace("\\", "/")
        assert resolved == runtime.as_posix()


# ---------------------------------------------------------------------------
# Layer 3 — end-to-end staging of the real tree
# ---------------------------------------------------------------------------


@requires_pwsh
class TestFullStaging:
    """What an installed user would actually receive, minus the runtime."""

    def test_the_payload_carries_everything_the_suite_needs(
        self, tmp_path: Path
    ) -> None:
        work = tmp_path / "work"
        out = tmp_path / "dist"
        # A relocatable runtime needs python.exe + pythonw.exe stubs and no
        # pyvenv.cfg.  The real tree is too expensive, but a two-file stub
        # exercises the full staging path including Copy-RuntimeTree.
        runtime_src = tmp_path / "runtime_src"
        runtime_src.mkdir()
        (runtime_src / "python.exe").write_bytes(b"stub")
        (runtime_src / "pythonw.exe").write_bytes(b"stub")
        result = subprocess.run(
            [
                _PWSH,
                "-NoProfile",
                "-File",
                str(BUILD_PS1),
                "-SkipDeps",
                "-NoCompile",
                "-RuntimeSource",
                str(runtime_src),
                "-PythonExe",
                sys.executable,
                "-WorkDir",
                str(work),
                "-OutputDir",
                str(out),
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            cwd=REPO_ROOT,
            timeout=900,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        app = work / "app"
        assert (app / MASTER_DRIVER).is_file()
        assert (app / "pyproject.toml").is_file()
        assert (app / "LICENSE").is_file()
        for name in REQUIRED_BINARIES:
            assert (app / name).is_file(), f"{name} missing from the staged payload"

        assert (app / "runtime" / "python.exe").is_file()
        assert (app / "runtime" / "pythonw.exe").is_file()

        shim = app / "bin" / "audiosuite.cmd"
        assert shim.is_file()
        assert "%~dp0" in shim.read_text(encoding="ascii")

        shortcuts = work / "shortcuts.iss"
        assert shortcuts.is_file()
        shortcut_text = shortcuts.read_text(encoding="ascii")
        assert "Audio Refinery" in shortcut_text
        assert MASTER_DRIVER not in shortcut_text

        # No secret or cache payload may ship to a user's machine.
        shipped = {p.name for p in app.rglob("*") if p.is_file()}
        for name in SECRET_FILES:
            assert name not in shipped, f"secret {name} reached the staged payload"
        assert not any(name.endswith(".key") for name in shipped)
        assert not any("__pycache__" in p.parts for p in app.rglob("*"))
        assert not any("packaging" in p.parts for p in app.rglob("*"))
