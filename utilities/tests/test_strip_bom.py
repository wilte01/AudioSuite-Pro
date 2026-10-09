"""Tests for ``utilities/strip_bom.py`` — iteration-8 C6 (audit M16).

``_cleanup`` removed the temp file that only exists because a write had
already failed, and swallowed the removal ``OSError`` with a bare ``pass``.
Per the suite's no-silent-swallow standard (A3), the failure is now logged
with the traceback instead of vanishing: a stuck temp file must be
diagnosable.

The strip behaviour itself is also locked here — the file had no tests at
all (utilities/tests covered only 2 of the 7 scripts).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import strip_bom  # noqa: E402


class TestCleanupFailureIsWitnessed:
    """The swallowed ``OSError`` must surface (audit M16)."""

    def test_cleanup_failure_logs_warning_with_traceback(
        self, tmp_path: Path, caplog
    ) -> None:
        leftover = tmp_path / ".bom_strip_stuck"
        leftover.write_bytes(b"temp")

        with patch.object(strip_bom.os, "remove", side_effect=OSError("file locked")):
            strip_bom._cleanup(leftover)

        records = [r for r in caplog.records if r.name == "utilities.strip_bom"]
        assert records, "the cleanup failure was swallowed silently"
        assert records[0].levelno == logging.WARNING
        assert str(leftover) in records[0].getMessage()
        assert records[0].exc_info is not None, (
            "the record must carry the underlying OSError traceback"
        )

    def test_cleanup_success_is_silent_and_removes_the_file(
        self, tmp_path: Path, caplog
    ) -> None:
        leftover = tmp_path / ".bom_strip_ok"
        leftover.write_bytes(b"temp")

        strip_bom._cleanup(leftover)

        assert not leftover.exists()
        assert not [r for r in caplog.records if r.name == "utilities.strip_bom"]

    def test_cleanup_of_nonexistent_path_is_silent(
        self, tmp_path: Path, caplog
    ) -> None:
        strip_bom._cleanup(tmp_path / "never-existed.tmp")

        assert not [r for r in caplog.records if r.name == "utilities.strip_bom"]


class TestStripBehaviour:
    """Outcome correctness: measure the bytes actually left on disk."""

    def test_bom_is_stripped_in_place(self, tmp_path: Path) -> None:
        target = tmp_path / "bommed.py"
        target.write_bytes(strip_bom.UTF8_BOM + b"print('ok')\n")

        status, detail = strip_bom.strip_bom_from_file(str(target))

        assert status == "modified"
        assert target.read_bytes() == b"print('ok')\n"

    def test_bom_free_file_is_skipped_untouched(self, tmp_path: Path) -> None:
        target = tmp_path / "clean.py"
        original = b"print('ok')\n"
        target.write_bytes(original)

        status, _detail = strip_bom.strip_bom_from_file(str(target))

        assert status == "skipped"
        assert target.read_bytes() == original

    def test_dry_run_reports_but_does_not_write(self, tmp_path: Path) -> None:
        target = tmp_path / "bommed.py"
        original = strip_bom.UTF8_BOM + b"x = 1\n"
        target.write_bytes(original)

        status, _detail = strip_bom.strip_bom_from_file(str(target), dry_run=True)

        assert status == "modified"
        assert target.read_bytes() == original

    def test_invalid_utf8_after_bom_is_error_and_untouched(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "binary.py"
        original = strip_bom.UTF8_BOM + b"\xff\xfe\x00corrupt"
        target.write_bytes(original)

        status, _detail = strip_bom.strip_bom_from_file(str(target))

        assert status == "error"
        assert target.read_bytes() == original


class TestFindTargetFiles:
    """The walker yields files only, matching extensions case-insensitively."""

    def test_yields_matching_files_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.PY").write_text("x", encoding="utf-8")
        (sub / "nested").mkdir()

        found = set(strip_bom.find_target_files(str(tmp_path), {".py"}))

        assert found == {str(tmp_path / "a.py"), str(sub / "b.PY")}


class TestReadErrors:
    """A file that cannot be read is an error, never a crash."""

    def test_permission_error_on_read(self, tmp_path: Path) -> None:
        target = tmp_path / "x.py"
        target.write_bytes(b"x")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            status, detail = strip_bom.strip_bom_from_file(str(target))
        assert status == "error"
        assert "permission denied reading" in detail

    def test_os_error_on_read(self, tmp_path: Path) -> None:
        target = tmp_path / "x.py"
        target.write_bytes(b"x")
        with patch("builtins.open", side_effect=OSError("boom")):
            status, detail = strip_bom.strip_bom_from_file(str(target))
        assert status == "error"
        assert "OS error reading" in detail


class TestWriteErrorBranches:
    """A failed atomic replace is reported and the temp file cleaned up."""

    def test_permission_error_on_write(self, tmp_path: Path) -> None:
        target = tmp_path / "bommed.py"
        target.write_bytes(strip_bom.UTF8_BOM + b"print('ok')\n")

        with patch.object(
            strip_bom.os, "replace", side_effect=PermissionError("denied")
        ):
            status, detail = strip_bom.strip_bom_from_file(str(target))

        assert status == "error"
        assert "permission denied writing" in detail
        assert not list(tmp_path.glob(".bom_strip_*"))

    def test_os_error_on_write(self, tmp_path: Path) -> None:
        target = tmp_path / "bommed.py"
        target.write_bytes(strip_bom.UTF8_BOM + b"print('ok')\n")

        with patch.object(strip_bom.os, "replace", side_effect=OSError("boom")):
            status, detail = strip_bom.strip_bom_from_file(str(target))

        assert status == "error"
        assert "OS error writing" in detail
        assert not list(tmp_path.glob(".bom_strip_*"))


class TestMain:
    """The CLI body: extension handling, dry-run and exit codes."""

    def test_main_strips_and_summarises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bommed = tmp_path / "bommed.py"
        bommed.write_bytes(strip_bom.UTF8_BOM + b"print('ok')\n")
        (tmp_path / "clean.py").write_bytes(b"print('clean')\n")

        with patch.object(strip_bom.sys, "argv", ["strip_bom.py", str(tmp_path)]):
            strip_bom.main()

        out = capsys.readouterr().out
        assert "1 modified" in out
        assert bommed.read_bytes() == b"print('ok')\n"

    def test_main_rejects_a_non_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            strip_bom.sys, "argv", ["strip_bom.py", str(tmp_path / "nope")]
        ):
            with pytest.raises(SystemExit) as exc:
                strip_bom.main()

        assert exc.value.code == 1
        assert "not a directory" in capsys.readouterr().err

    def test_main_exits_two_when_a_file_errors(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "x.py").write_bytes(b"x")
        with (
            patch.object(
                strip_bom, "strip_bom_from_file", return_value=("error", "boom")
            ),
            patch.object(strip_bom.sys, "argv", ["strip_bom.py", str(tmp_path)]),
        ):
            with pytest.raises(SystemExit) as exc:
                strip_bom.main()

        assert exc.value.code == 2
        assert "Files with errors" in capsys.readouterr().out

    def test_main_dry_run_reports_but_does_not_write(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        bommed = tmp_path / "bommed.py"
        original = strip_bom.UTF8_BOM + b"x = 1\n"
        bommed.write_bytes(original)

        with patch.object(
            strip_bom.sys, "argv", ["strip_bom.py", str(tmp_path), "--dry-run"]
        ):
            strip_bom.main()

        assert "DRY RUN" in capsys.readouterr().out
        assert bommed.read_bytes() == original

    def test_main_accepts_custom_extensions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        data = tmp_path / "data.json"
        data.write_bytes(strip_bom.UTF8_BOM + b"{}")
        script = tmp_path / "script.py"
        script.write_bytes(strip_bom.UTF8_BOM + b"x = 1\n")

        with patch.object(
            strip_bom.sys, "argv", ["strip_bom.py", str(tmp_path), "--ext", ".json"]
        ):
            strip_bom.main()

        assert data.read_bytes() == b"{}"
        assert script.read_bytes() == strip_bom.UTF8_BOM + b"x = 1\n"
