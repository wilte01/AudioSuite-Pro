"""Tests for ``utilities/verify_refinery_log.py``.

Iteration-9 S8 (G8.4, audit L4) brought ``utilities/`` under the coverage
gate.  ``verify_refinery_log.py`` had no tests at all (0%): it is a
bulk-mutation script — ``--fix`` rewrites ``_refinery_completed.log`` in
place — so its hash/parse/prune contract is locked here by measuring the
bytes actually written to disk, not by trusting the reported summary.

The ``if __name__ == "__main__":`` guard is excluded by the coverage config;
``main()`` itself is exercised through a patched ``sys.argv``.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import verify_refinery_log as rl  # noqa: E402


class TestSha256:
    """The digest must equal the stdlib's for the same real bytes."""

    def test_digest_matches_hashlib(self, tmp_path: Path) -> None:
        blob = tmp_path / "blob.bin"
        blob.write_bytes(b"payload")
        assert rl._sha256(blob) == hashlib.sha256(b"payload").hexdigest()

    def test_digest_crosses_the_block_boundary(self, tmp_path: Path) -> None:
        data = b"A" * (rl._BLOCK * 2 + 7)
        blob = tmp_path / "big.bin"
        blob.write_bytes(data)
        assert rl._sha256(blob) == hashlib.sha256(data).hexdigest()


class TestResolveSupportedExtensions:
    """The live registry wins; the fallback is only for an import failure."""

    def test_uses_the_live_supported_extensions(self) -> None:
        from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

        extensions, used_fallback = rl._resolve_supported_extensions()
        assert used_fallback is False
        assert extensions == set(SUPPORTED_EXTENSIONS)

    def test_falls_back_when_the_import_fails(self) -> None:
        with patch.dict(sys.modules, {"audio_suite_shared.tag_helper": None}):
            extensions, used_fallback = rl._resolve_supported_extensions()
        assert used_fallback is True
        assert extensions == rl._FALLBACK_EXTENSIONS


class TestParseLog:
    """Parsing tolerates the canonical header, blanks and malformed lines."""

    def test_missing_log_is_empty(self, tmp_path: Path) -> None:
        assert rl._parse_log(tmp_path / rl.LOG_FILENAME) == {}

    def test_parses_entries_and_ignores_comments_and_junk(self, tmp_path: Path) -> None:
        log = tmp_path / rl.LOG_FILENAME
        log.write_text(
            "# Audio Refinery — completion registry\n"
            "# Format: <sha256>  <filename>\n"
            "\n"
            "  \n"
            "aaaa  track one.mp3\n"
            "malformed-line-without-separator\n",
            encoding="utf-8",
        )
        assert rl._parse_log(log) == {"track one.mp3": "aaaa"}

    def test_unreadable_log_reports_error_and_is_empty(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        log = tmp_path / rl.LOG_FILENAME
        log.write_text("aaaa  a.mp3\n", encoding="utf-8")
        with patch("builtins.open", side_effect=OSError("locked")):
            entries = rl._parse_log(log)
        assert entries == {}
        assert "[ERROR]" in capsys.readouterr().err


class TestWriteLog:
    """The written log carries the registry's exact three-header format."""

    def test_writes_headers_and_sorted_entries(self, tmp_path: Path) -> None:
        log = tmp_path / rl.LOG_FILENAME
        rl._write_log(log, {"b.mp3": "bbbb", "a.mp3": "aaaa"})
        lines = log.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "# Audio Refinery — completion registry"
        assert lines[1] == "# Format: <sha256>  <filename>"
        assert lines[2].startswith("# Delete this file")
        assert lines[3:] == ["aaaa  a.mp3", "bbbb  b.mp3"]

    def test_write_failure_reports_and_raises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("builtins.open", side_effect=OSError("read-only")):
            with pytest.raises(OSError):
                rl._write_log(tmp_path / rl.LOG_FILENAME, {"a.mp3": "aaaa"})
        assert "[ERROR]" in capsys.readouterr().err


class TestFindAudioFiles:
    """Only files (not dirs) with a matching suffix are returned."""

    def test_filters_by_extension_case_insensitively(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.MP3").write_bytes(b"x")
        (tmp_path / "c.txt").write_text("x", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        found = rl._find_audio_files(tmp_path, {".mp3"})
        assert found == {"a.mp3", "b.MP3"}


class TestFixLog:
    """``--fix`` updates CHANGED hashes and prunes ORPHAN entries."""

    def test_updates_changed_hash_and_prunes_orphan(self, tmp_path: Path) -> None:
        track = tmp_path / "track.mp3"
        track.write_bytes(b"new content")
        log = tmp_path / rl.LOG_FILENAME
        log.write_text(
            f"{'0' * 64}  track.mp3\n{'1' * 64}  gone.mp3\n", encoding="utf-8"
        )

        modified = rl._fix_log(
            tmp_path,
            {"track.mp3": "0" * 64, "gone.mp3": "1" * 64},
            {"track.mp3"},
            {".mp3"},
            dry_run=False,
        )

        assert modified is True
        text = log.read_text(encoding="utf-8")
        assert "gone.mp3" not in text
        assert rl._sha256(track) in text

    def test_no_changes_returns_false(self, tmp_path: Path) -> None:
        track = tmp_path / "track.mp3"
        track.write_bytes(b"x")
        assert (
            rl._fix_log(
                tmp_path,
                {"track.mp3": rl._sha256(track)},
                {"track.mp3"},
                {".mp3"},
                dry_run=False,
            )
            is False
        )

    def test_dry_run_reports_but_does_not_write(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "track.mp3").write_bytes(b"new")
        log = tmp_path / rl.LOG_FILENAME
        sentinel = "sentinel\n"
        log.write_text(sentinel, encoding="utf-8")

        modified = rl._fix_log(
            tmp_path,
            {"track.mp3": "0" * 64},
            {"track.mp3"},
            {".mp3"},
            dry_run=True,
        )

        assert modified is True
        assert log.read_text(encoding="utf-8") == sentinel
        assert "[DRY RUN]" in capsys.readouterr().out

    def test_quiet_suppresses_fix_messages(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "track.mp3").write_bytes(b"new")
        rl._fix_log(
            tmp_path,
            {"track.mp3": "0" * 64},
            {"track.mp3"},
            {".mp3"},
            dry_run=False,
            quiet=True,
        )
        out = capsys.readouterr().out
        assert "[FIX HASH]" not in out
        assert "[FIXED]" not in out

    def test_unreadable_file_is_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "track.mp3").write_bytes(b"x")
        with patch.object(rl, "_sha256", side_effect=OSError("locked")):
            modified = rl._fix_log(
                tmp_path,
                {"track.mp3": "0" * 64},
                {"track.mp3"},
                {".mp3"},
                dry_run=False,
            )
        assert modified is False
        assert "[ERROR]" in capsys.readouterr().err


class TestVerifyDirectory:
    """One directory's report and return code."""

    def test_empty_directory_is_clean(self, tmp_path: Path) -> None:
        assert (
            rl.verify_directory(
                tmp_path,
                extensions={".mp3"},
                verbose=False,
                report_orphans=True,
                check_hashes=False,
            )
            == 0
        )

    def test_verbose_empty_directory_reports_info(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=True,
            report_orphans=True,
            check_hashes=False,
        )
        assert code == 0
        assert "[INFO]" in capsys.readouterr().out

    def test_missing_log_with_audio_reports_missing_log(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=True,
            report_orphans=True,
            check_hashes=False,
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "[MISSING LOG]" in out
        assert "a.mp3" in out and "b.mp3" in out

    def test_all_accounted_for_is_clean(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        track = tmp_path / "a.mp3"
        track.write_bytes(b"x")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{rl._sha256(track)}  a.mp3\n", encoding="utf-8"
        )
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=False,
            report_orphans=True,
            check_hashes=False,
        )
        assert code == 0
        assert "all accounted for" in capsys.readouterr().out

    def test_file_on_disk_but_not_in_log_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'0' * 64}  other.mp3\n", encoding="utf-8"
        )
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=False,
            report_orphans=True,
            check_hashes=False,
        )
        assert code == 1
        assert "[MISSING] a.mp3" in capsys.readouterr().out

    def test_check_hashes_detects_a_changed_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.mp3").write_bytes(b"new")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'0' * 64}  a.mp3\n", encoding="utf-8"
        )
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=False,
            report_orphans=True,
            check_hashes=True,
        )
        assert code == 1
        assert "[CHANGED] a.mp3" in capsys.readouterr().out

    def test_orphan_entry_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        track = tmp_path / "present.mp3"
        track.write_bytes(b"x")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{rl._sha256(track)}  present.mp3\n{'1' * 64}  gone.mp3\n",
            encoding="utf-8",
        )
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=False,
            report_orphans=True,
            check_hashes=False,
        )
        assert code == 1
        assert "[ORPHAN] gone.mp3" in capsys.readouterr().out

    def test_orphan_suppressed_when_report_orphans_false(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'1' * 64}  gone.mp3\n", encoding="utf-8"
        )
        code = rl.verify_directory(
            tmp_path,
            extensions={".mp3"},
            verbose=False,
            report_orphans=False,
            check_hashes=False,
        )
        assert code == 0
        assert "[ORPHAN]" not in capsys.readouterr().out

    def test_hash_error_is_reported_and_skipped(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'0' * 64}  a.mp3\n", encoding="utf-8"
        )
        with patch.object(rl, "_sha256", side_effect=OSError("locked")):
            code = rl.verify_directory(
                tmp_path,
                extensions={".mp3"},
                verbose=False,
                report_orphans=False,
                check_hashes=True,
            )
        assert code == 0
        assert "[ERROR]" in capsys.readouterr().err


class TestCollectDirectories:
    """Recursive walk includes subdirs but never hidden directories."""

    def test_non_recursive_returns_only_root(self, tmp_path: Path) -> None:
        (tmp_path / "sub").mkdir()
        assert rl._collect_directories(tmp_path, recursive=False) == [tmp_path]

    def test_recursive_collects_subdirs_and_skips_dot_dirs(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / ".hidden").mkdir()
        dirs = set(rl._collect_directories(tmp_path, recursive=True))
        assert tmp_path in dirs
        assert (tmp_path / "sub") in dirs
        assert (tmp_path / ".hidden") not in dirs


class TestMain:
    """The CLI body: argument handling, reports and summary lines."""

    def test_non_directory_argument_is_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            rl.sys, "argv", ["verify_refinery_log.py", str(tmp_path / "nope")]
        ):
            rl.main()
        assert "[ERROR] Not a directory" in capsys.readouterr().err

    def test_verifies_a_clean_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        track = tmp_path / "a.mp3"
        track.write_bytes(b"x")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{rl._sha256(track)}  a.mp3\n", encoding="utf-8"
        )
        with patch.object(rl.sys, "argv", ["verify_refinery_log.py", str(tmp_path)]):
            rl.main()
        out = capsys.readouterr().out
        assert "Scanning:" in out
        assert "all accounted for" in out

    def test_fix_updates_changed_and_prunes_orphan(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        track = tmp_path / "a.mp3"
        track.write_bytes(b"new content")
        log = tmp_path / rl.LOG_FILENAME
        log.write_text(f"{'0' * 64}  a.mp3\n{'1' * 64}  gone.mp3\n", encoding="utf-8")
        with patch.object(
            rl.sys, "argv", ["verify_refinery_log.py", "--fix", str(tmp_path)]
        ):
            rl.main()
        text = log.read_text(encoding="utf-8")
        assert "gone.mp3" not in text
        assert rl._sha256(track) in text
        assert "Fixed 1 director" in capsys.readouterr().out

    def test_dry_run_without_fix_notes_then_verifies(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            rl.sys, "argv", ["verify_refinery_log.py", "--dry-run", str(tmp_path)]
        ):
            rl.main()
        assert "only applies to --fix" in capsys.readouterr().err

    def test_check_hashes_reports_changed_and_summarises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.mp3").write_bytes(b"new")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'0' * 64}  a.mp3\n", encoding="utf-8"
        )
        with patch.object(
            rl.sys, "argv", ["verify_refinery_log.py", "--check-hashes", str(tmp_path)]
        ):
            rl.main()
        out = capsys.readouterr().out
        assert "[CHANGED]" in out
        assert "have remaining issues" in out

    def test_recursive_default_descends_into_subdirs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        track = sub / "a.mp3"
        track.write_bytes(b"x")
        (sub / rl.LOG_FILENAME).write_text(
            f"{rl._sha256(track)}  a.mp3\n", encoding="utf-8"
        )
        with patch.object(rl.sys, "argv", ["verify_refinery_log.py", str(tmp_path)]):
            rl.main()
        assert str(sub) in capsys.readouterr().out

    def test_no_recursive_skips_subdirs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "a.mp3").write_bytes(b"x")
        with patch.object(
            rl.sys, "argv", ["verify_refinery_log.py", "--no-recursive", str(tmp_path)]
        ):
            rl.main()
        assert str(sub) not in capsys.readouterr().out

    def test_quiet_suppresses_fix_detail(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.mp3").write_bytes(b"new")
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'0' * 64}  a.mp3\n", encoding="utf-8"
        )
        with patch.object(
            rl.sys,
            "argv",
            ["verify_refinery_log.py", "--fix", "--quiet", str(tmp_path)],
        ):
            rl.main()
        out = capsys.readouterr().out
        assert "[FIX HASH]" not in out
        assert "[FIXED]" not in out

    def test_no_orphans_suppresses_orphan_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / rl.LOG_FILENAME).write_text(
            f"{'1' * 64}  gone.mp3\n", encoding="utf-8"
        )
        with patch.object(
            rl.sys, "argv", ["verify_refinery_log.py", "--no-orphans", str(tmp_path)]
        ):
            rl.main()
        assert "[ORPHAN]" not in capsys.readouterr().out
