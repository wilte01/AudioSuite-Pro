"""
Tests for audio_suite_shared.preflight.

Covers:
    - iter_source_files: finds .py/.pyw, excludes venv/cache dirs, sorts
    - find_broken_files: returns files that fail to byte-compile
    - verify_suite: clean suite returns True; broken suite logs a report,
      shows a dialog, and blocks via exit()
    - report_missing_requirements: warning-level ffmpeg/ffprobe report that
      never blocks, plus its tkinter-free (pure) contract
    - guard_or_exit: wires the real dialog + exit behaviour
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import audio_suite_shared.preflight as preflight
from audio_suite_shared.preflight import (
    BLOCKED_TITLE,
    WARNING_TITLE,
    find_broken_files,
    guard_or_exit,
    iter_source_files,
    report_missing_requirements,
    verify_suite,
)
from audio_suite_shared.system_requirements import REQUIRED_EXECUTABLES

FFMPEG_REQUIREMENT = next(r for r in REQUIRED_EXECUTABLES if r.name == "ffmpeg")
FFPROBE_REQUIREMENT = next(r for r in REQUIRED_EXECUTABLES if r.name == "ffprobe")


@pytest.fixture
def suite_root(tmp_path: Path) -> Path:
    """Build a minimal, well-formed source tree to scan."""
    pkg = tmp_path / "my_pkg"
    pkg.mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text("def f():\n    return 1\n")
    (tmp_path / ".venv" / "lib.py").write_text("VENV_FILE = True\n")
    (tmp_path / "__pycache__" / "cached.pyc").write_bytes(b"\x00")
    return tmp_path


class TestIterSourceFiles:
    def test_finds_py_and_pyw_only(self, suite_root: Path):
        (suite_root / "launcher.pyw").write_text("import sys\n")
        files = {p.name for p in iter_source_files(suite_root)}
        assert "mod.py" in files
        assert "launcher.pyw" in files
        # __init__.py and non-source files are skipped
        assert "__init__.py" not in files

    def test_excludes_venv_and_cache_dirs(self, suite_root: Path):
        files = {p.name for p in iter_source_files(suite_root)}
        assert "lib.py" not in files
        assert "cached.pyc" not in files

    def test_returns_sorted_result(self, suite_root: Path):
        names = [p.name for p in iter_source_files(suite_root)]
        assert names == sorted(names)


class TestFindBrokenFiles:
    def test_clean_tree_yields_no_broken_files(self, suite_root: Path):
        assert find_broken_files(suite_root) == []

    def test_indentation_error_is_detected(self, suite_root: Path):
        target = suite_root / "my_pkg" / "broken.py"
        target.write_text(
            'def f():\n"""wrongly unindented docstring"""\n    return 1\n'
        )
        broken = find_broken_files(suite_root)
        assert target in broken

    def test_syntax_error_is_detected(self, suite_root: Path):
        target = suite_root / "my_pkg" / "syntax.py"
        target.write_text("def broken(:\n")
        broken = find_broken_files(suite_root)
        assert target in broken


class TestVerifySuite:
    def test_clean_suite_returns_true_and_does_not_exit(self, suite_root: Path):
        show = MagicMock()
        blocker = MagicMock()
        assert verify_suite(suite_root, show, exit_fn=blocker) is True
        show.assert_not_called()
        blocker.assert_not_called()

    def test_broken_suite_logs_report(self, suite_root: Path, caplog):
        (suite_root / "my_pkg" / "broken.py").write_text("def f():\n    x = (\n")
        show = MagicMock()
        blocker = MagicMock()
        with caplog.at_level(
            logging.ERROR, logger="audio_suite.audio_suite_shared.preflight"
        ):
            verify_suite(suite_root, show, exit_fn=blocker)
        assert "broken.py" in caplog.text

    def test_broken_suite_shows_dialog_and_blocks(self, suite_root: Path):
        (suite_root / "my_pkg" / "broken.py").write_text("def f():\n    x = (\n")
        show = MagicMock()
        blocker = MagicMock()
        verify_suite(suite_root, show, exit_fn=blocker)
        show.assert_called_once()
        title, message = show.call_args[0]
        assert "Startup Blocked" in title
        assert "broken.py" in message
        blocker.assert_called_once_with(1)

    def test_default_behavior_exits_on_failure(self, suite_root: Path):
        (suite_root / "my_pkg" / "broken.py").write_text("def f():\n    x = (\n")
        show = MagicMock()
        with pytest.raises(SystemExit) as exc_info:
            verify_suite(suite_root, show, log_fn=lambda m: None)
        assert exc_info.value.code == 1
        show.assert_called_once()


class TestReportMissingRequirements:
    """The ffmpeg/ffprobe presence check added by plan item A5."""

    def test_all_present_emits_no_warning(self, monkeypatch):
        monkeypatch.setattr(preflight, "find_missing_requirements", lambda: [])
        show = MagicMock()
        assert report_missing_requirements(show) == []
        show.assert_not_called()

    def test_ffmpeg_absent_is_reported_with_install_hint(self, monkeypatch):
        monkeypatch.setattr(
            preflight, "find_missing_requirements", lambda: [FFMPEG_REQUIREMENT]
        )
        show = MagicMock()
        missing = report_missing_requirements(show)

        assert [requirement.name for requirement in missing] == ["ffmpeg"]
        show.assert_called_once()
        title, message = show.call_args[0]
        assert title == WARNING_TITLE
        assert title != BLOCKED_TITLE, "a warning must be distinguishable from a block"
        assert "ffmpeg" in message
        assert "winget install Gyan.FFmpeg" in message
        assert "sudo apt install ffmpeg" in message
        assert "brew install ffmpeg" in message
        # The message must say what it is for, not just that it is missing.
        assert FFMPEG_REQUIREMENT.purpose in message

    def test_missing_ffprobe_with_ffmpeg_present_is_reported_separately(
        self, monkeypatch
    ):
        """ffprobe installs independently of ffmpeg, so it is its own entry."""
        monkeypatch.setattr(
            preflight, "find_missing_requirements", lambda: [FFPROBE_REQUIREMENT]
        )
        show = MagicMock()
        missing = report_missing_requirements(show)

        assert [requirement.name for requirement in missing] == ["ffprobe"]
        title, message = show.call_args[0]
        assert title == WARNING_TITLE
        assert "ffprobe" in message
        assert "ffmpeg (" not in message

    def test_both_missing_reports_both(self, monkeypatch):
        monkeypatch.setattr(
            preflight,
            "find_missing_requirements",
            lambda: [FFMPEG_REQUIREMENT, FFPROBE_REQUIREMENT],
        )
        show = MagicMock()
        assert len(report_missing_requirements(show)) == 2
        assert "2 required system tool(s)" in show.call_args[0][1]

    def test_logs_the_report_at_warning_level(self, monkeypatch, caplog):
        monkeypatch.setattr(
            preflight, "find_missing_requirements", lambda: [FFMPEG_REQUIREMENT]
        )
        with caplog.at_level(
            logging.WARNING, logger="audio_suite.audio_suite_shared.preflight"
        ):
            report_missing_requirements(MagicMock())
        assert "ffmpeg" in caplog.text

    def test_injectable_log_fn_suppresses_the_logger(self, monkeypatch):
        monkeypatch.setattr(
            preflight, "find_missing_requirements", lambda: [FFMPEG_REQUIREMENT]
        )
        logged: list[str] = []
        report_missing_requirements(MagicMock(), log_fn=logged.append)
        assert len(logged) == 1
        assert "ffmpeg" in logged[0]

    def test_never_blocks_and_never_exits(self, monkeypatch):
        """Warning-level only: a missing binary must not stop a tool that does
        not need it.  The observable contract is that the check *returns* the
        missing list and leaves the launch decision to the compile gate, so
        assert both halves of that: the return value is data, and
        ``guard_or_exit`` still reports success."""
        monkeypatch.setattr(
            preflight, "find_missing_requirements", lambda: [FFMPEG_REQUIREMENT]
        )
        show = MagicMock()
        returned = report_missing_requirements(show)

        assert isinstance(returned, list), "must return data, not raise or exit"
        assert returned == [FFMPEG_REQUIREMENT]

        monkeypatch.setattr(preflight, "verify_suite", lambda root, show_fn: True)
        # Stub the requirement check: it is covered by its own tests above, and
        # leaving the real resolver in place would open a real Tk warning
        # dialog on any host without ffmpeg and hang the suite.
        monkeypatch.setattr(preflight, "report_missing_requirements", lambda _show: [])
        assert guard_or_exit(Path(".")) is True

    def test_stays_pure_and_never_imports_tkinter(self, monkeypatch):
        """Prove the purity contract in a clean interpreter.

        A same-process test cannot prove this: the root conftest has already
        imported tkinter, so an accidental ``import tkinter`` inside the check
        would be invisible.  Shadowing the module with ``None`` makes any such
        import raise, and there is no DISPLAY, so no widget can be built.
        """
        monkeypatch.delenv("DISPLAY", raising=False)
        script = (
            "import sys\n"
            "sys.modules['tkinter'] = None\n"
            "from audio_suite_shared.preflight import report_missing_requirements\n"
            "seen = []\n"
            "missing = report_missing_requirements(\n"
            "    lambda title, message: seen.append(title), log_fn=lambda m: None\n"
            ")\n"
            "assert 'tkinter' not in [m.name for m in missing]\n"
            "print('PURE_OK', len(seen))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert "PURE_OK" in result.stdout


class TestGuardOrExit:
    def test_forwards_to_verify_suite_and_returns_result(
        self, suite_root: Path, monkeypatch
    ):
        monkeypatch.setattr(preflight, "verify_suite", lambda root, show: "wired")
        # Stub the requirement check so the test is hermetic: a host without
        # ffmpeg would otherwise open a real Tk warning dialog and hang.
        monkeypatch.setattr(preflight, "report_missing_requirements", lambda _show: [])
        result = guard_or_exit(suite_root)
        assert result == "wired"

    def test_propagates_a_blocked_compile_gate(self, suite_root: Path, monkeypatch):
        monkeypatch.setattr(preflight, "verify_suite", lambda root, show: False)
        warn = MagicMock()
        monkeypatch.setattr(preflight, "report_missing_requirements", warn)
        assert guard_or_exit(suite_root) is False
        warn.assert_not_called()

    def test_runs_the_system_tool_check_after_a_clean_compile(
        self, suite_root: Path, monkeypatch
    ):
        monkeypatch.setattr(preflight, "verify_suite", lambda root, show: True)
        warn = MagicMock(return_value=[])
        monkeypatch.setattr(preflight, "report_missing_requirements", warn)
        assert guard_or_exit(suite_root) is True
        warn.assert_called_once()
