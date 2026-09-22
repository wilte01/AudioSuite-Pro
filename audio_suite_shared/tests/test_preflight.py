"""
Tests for audio_suite_shared.preflight.

Covers:
    - iter_source_files: finds .py/.pyw, excludes venv/cache dirs, sorts
    - find_broken_files: returns files that fail to byte-compile
    - verify_suite: clean suite returns True; broken suite logs a report,
      shows a dialog, and blocks via exit()
    - guard_or_exit: wires the real dialog + exit behaviour
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.preflight import (
    find_broken_files,
    guard_or_exit,
    iter_source_files,
    verify_suite,
)


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
        with caplog.at_level(logging.ERROR, logger="audio_suite_shared.preflight"):
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


class TestGuardOrExit:
    def test_forwards_to_verify_suite_and_returns_result(
        self, suite_root: Path, monkeypatch
    ):
        import audio_suite_shared.preflight as preflight

        monkeypatch.setattr(preflight, "verify_suite", lambda root, show: "wired")
        result = guard_or_exit(suite_root)
        assert result == "wired"
