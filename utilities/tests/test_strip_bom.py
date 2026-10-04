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
