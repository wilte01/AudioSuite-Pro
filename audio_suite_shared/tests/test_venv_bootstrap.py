"""Tests for ``audio_suite_shared.venv_bootstrap``.

The launchers are started by whatever interpreter the OS associates with
``.pyw``, which is the system Python, while ``uv sync --extra ml`` writes the
extras into ``<root>/.venv``.  The bootstrap closes that gap by re-executing the
launcher under the venv interpreter, so the properties worth locking down are:

* a venv interpreter is only re-executed *into*, never guessed (the window mode
  is kept, a missing ``pythonw.exe`` falls back to ``python.exe``);
* a process already inside the venv, a re-executed launch, a pytest run and a
  frozen build are all left alone — a wrong ``exec`` here replaces the process;
* the script and its arguments are forwarded, so a Master Driver launch arrives
  with its parameters intact; and
* a failing ``exec`` leaves a running interpreter instead of a window that
  closes.

Changed in 2.1.0: initial version.
Changed in 2.1.6: the two re-exec tests pass ``platform="win32"``. Their argv,
executable and ``.venv/Scripts`` fixture are Windows-shaped by design, but the
branch that found the interpreter read the real ``sys.platform``, so on a POSIX
host they returned None and failed their assertions - a defect the POSIX smoke
leg surfaced (R-12, PLAN_audit_2026-10-24_deferred_p2p3.md). The module's
existing tests-only ``platform`` seam now reaches ``ensure_venv_interpreter``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import venv_bootstrap
from audio_suite_shared.venv_bootstrap import (
    ENV_SENTINEL,
    ensure_venv_interpreter,
    find_venv_interpreter,
    under_test,
)


def _make_venv(root: Path, *, bin_dir: str, names: tuple[str, ...]) -> Path:
    """Create ``root/.venv/<bin_dir>`` holding the named interpreter files."""
    directory = root / ".venv" / bin_dir
    directory.mkdir(parents=True)
    for name in names:
        (directory / name).write_bytes(b"")
    return directory


class TestFindVenvInterpreter:
    def test_no_venv_means_no_re_exec(self, tmp_path: Path) -> None:
        assert find_venv_interpreter(tmp_path) is None

    def test_a_windowed_launch_prefers_the_windowed_interpreter(
        self, tmp_path: Path
    ) -> None:
        _make_venv(tmp_path, bin_dir="Scripts", names=("python.exe", "pythonw.exe"))

        found = find_venv_interpreter(
            tmp_path, executable=r"C:\Python\pythonw.exe", platform="win32"
        )

        assert found == tmp_path / ".venv" / "Scripts" / "pythonw.exe"

    def test_a_console_launch_prefers_the_console_interpreter(
        self, tmp_path: Path
    ) -> None:
        _make_venv(tmp_path, bin_dir="Scripts", names=("python.exe", "pythonw.exe"))

        found = find_venv_interpreter(
            tmp_path, executable=r"C:\Python\python.exe", platform="win32"
        )

        assert found == tmp_path / ".venv" / "Scripts" / "python.exe"

    def test_a_venv_without_pythonw_falls_back_to_python(self, tmp_path: Path) -> None:
        _make_venv(tmp_path, bin_dir="Scripts", names=("python.exe",))

        found = find_venv_interpreter(
            tmp_path, executable=r"C:\Python\pythonw.exe", platform="win32"
        )

        assert found == tmp_path / ".venv" / "Scripts" / "python.exe"

    def test_posix_layout_uses_bin_python(self, tmp_path: Path) -> None:
        _make_venv(tmp_path, bin_dir="bin", names=("python",))

        found = find_venv_interpreter(
            tmp_path, executable="/usr/bin/python3", platform="linux"
        )

        assert found == tmp_path / ".venv" / "bin" / "python"

    def test_posix_falls_back_to_python3(self, tmp_path: Path) -> None:
        _make_venv(tmp_path, bin_dir="bin", names=("python3",))

        found = find_venv_interpreter(
            tmp_path, executable="/usr/bin/python3", platform="darwin"
        )

        assert found == tmp_path / ".venv" / "bin" / "python3"


@pytest.fixture()
def venv_root(tmp_path: Path) -> Path:
    """A suite root whose ``.venv`` carries both Windows interpreters."""
    _make_venv(tmp_path, bin_dir="Scripts", names=("python.exe", "pythonw.exe"))
    return tmp_path


@pytest.fixture()
def re_exec_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear the pytest guard for the tests that must reach the exec seam."""
    monkeypatch.setattr(venv_bootstrap, "under_test", lambda environ=None: False)


class TestEnsureVenvInterpreter:
    def test_a_launch_outside_the_venv_re_executes_with_its_arguments(
        self, venv_root: Path, re_exec_allowed: None
    ) -> None:
        calls: list[tuple[str, list[str]]] = []

        def fake_exec(path: str, argv: list[str]) -> None:
            calls.append((path, argv))

        environ: dict[str, str] = {}
        target = ensure_venv_interpreter(
            venv_root,
            argv=[r"C:\suite\Stem_Separator.pyw", "--live", "--output", r"D:\stems"],
            executable=r"C:\Python\python.exe",
            prefix=r"C:\Python",
            environ=environ,
            exec_fn=fake_exec,
            platform="win32",
        )

        assert target == venv_root / ".venv" / "Scripts" / "python.exe"
        assert calls == [
            (
                str(target),
                [
                    str(target),
                    r"C:\suite\Stem_Separator.pyw",
                    "--live",
                    "--output",
                    r"D:\stems",
                ],
            )
        ]
        assert environ[ENV_SENTINEL] == "1", (
            "the sentinel must ride along, or a venv reporting an unexpected "
            "prefix would be re-executed forever"
        )

    def test_a_launch_without_a_venv_is_untouched(
        self, tmp_path: Path, re_exec_allowed: None
    ) -> None:
        exec_fn = MagicMock()

        result = ensure_venv_interpreter(
            tmp_path,
            argv=["launcher.pyw"],
            executable=r"C:\Python\python.exe",
            prefix=r"C:\Python",
            environ={},
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()

    def test_a_process_already_inside_the_venv_is_untouched(
        self, venv_root: Path, re_exec_allowed: None
    ) -> None:
        exec_fn = MagicMock()
        environ: dict[str, str] = {}

        result = ensure_venv_interpreter(
            venv_root,
            argv=["launcher.pyw"],
            executable=str(venv_root / ".venv" / "Scripts" / "pythonw.exe"),
            prefix=venv_root / ".venv",
            environ=environ,
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()
        assert ENV_SENTINEL not in environ

    def test_the_venv_prefix_is_enough_even_when_the_executable_is_elsewhere(
        self, venv_root: Path, re_exec_allowed: None
    ) -> None:
        """A POSIX venv interpreter is a symlink, so ``sys.prefix`` decides."""
        exec_fn = MagicMock()

        result = ensure_venv_interpreter(
            venv_root,
            argv=["launcher.pyw"],
            executable=r"C:\Python\python.exe",
            prefix=venv_root / ".venv",
            environ={},
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()

    def test_a_re_executed_launch_is_not_re_executed_again(
        self, venv_root: Path, re_exec_allowed: None
    ) -> None:
        exec_fn = MagicMock()

        result = ensure_venv_interpreter(
            venv_root,
            argv=["launcher.pyw"],
            executable=r"C:\Python\python.exe",
            prefix=r"C:\Python",
            environ={ENV_SENTINEL: "1"},
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()

    def test_a_failing_exec_continues_in_this_interpreter(
        self,
        venv_root: Path,
        re_exec_allowed: None,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        environ: dict[str, str] = {}

        def explosion(path: str, argv: list[str]) -> None:
            raise OSError("the venv interpreter is not executable")

        with caplog.at_level(logging.WARNING):
            result = ensure_venv_interpreter(
                venv_root,
                argv=["launcher.pyw"],
                executable=r"C:\Python\python.exe",
                prefix=r"C:\Python",
                environ=environ,
                exec_fn=explosion,
                platform="win32",
            )

        assert result is None
        assert ENV_SENTINEL not in environ, "the failed attempt must not look done"
        assert any(
            "not executable" in record.getMessage()
            for record in caplog.records
            if record.levelno >= logging.WARNING
        ), [record.getMessage() for record in caplog.records]

    def test_a_pytest_run_is_never_replaced(
        self, venv_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``tests/test_pyw_launchers.py`` executes launchers in-process."""
        exec_fn = MagicMock()
        monkeypatch.setattr(venv_bootstrap, "under_test", lambda environ=None: True)

        result = ensure_venv_interpreter(
            venv_root,
            argv=["launcher.pyw"],
            executable=r"C:\Python\python.exe",
            prefix=r"C:\Python",
            environ={},
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()

    def test_a_process_without_a_script_is_left_alone(
        self, venv_root: Path, re_exec_allowed: None
    ) -> None:
        exec_fn = MagicMock()

        result = ensure_venv_interpreter(
            venv_root,
            argv=[],
            executable=r"C:\Python\python.exe",
            prefix=r"C:\Python",
            environ={},
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()

    def test_a_frozen_build_is_left_alone(
        self,
        venv_root: Path,
        re_exec_allowed: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The packaged build has no ``.venv`` to run from."""
        exec_fn = MagicMock()
        monkeypatch.setattr(venv_bootstrap.sys, "frozen", True, raising=False)

        result = ensure_venv_interpreter(
            venv_root,
            argv=["launcher.pyw"],
            executable=r"AudioSuite.exe",
            prefix=r"C:\Python",
            environ={},
            exec_fn=exec_fn,
        )

        assert result is None
        exec_fn.assert_not_called()


class TestUnderTest:
    def test_the_running_suite_counts_as_a_test_process(self) -> None:
        assert under_test() is True

    def test_pytests_current_test_variable_counts(self) -> None:
        environ: dict[str, Any] = {"PYTEST_CURRENT_TEST": "tests/x.py::t (call)"}

        assert under_test(environ) is True
