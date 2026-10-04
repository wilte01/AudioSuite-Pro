"""Tests for ``utilities/rebuild_refinery_log.py``.

Audit M16 (iteration-8 C6) found two defects here:

1. The module docstring claimed the script "imports ``_sha256`` directly
   from the real registry module" with a fallback and a loud warning. No such
   import exists — ``_sha256`` is purely local. For a hash-compatibility
   tool the docstring is the trusted spec, so the false claim is itself the
   defect.
2. ``build_log_for_directory`` raises ``AudioFileNotFoundError`` while the
   caller caught ``except FileNotFoundError`` — an unrelated builtin branch
   of OSError — so the handler could never match and the user got a raw
   traceback instead of ``[ERROR]``.

These tests lock the fixes:

* the local ``_sha256`` produces the SAME digest as the live
  ``audio_refinery.core.registry._sha256`` for a real file (the tool's
  whole contract is "reproduce the value the program stored");
* the exception the function raises is caught by the caller — no traceback
  escapes ``main()``;
* the written log carries the registry's exact line format;
* the docstring no longer asserts the nonexistent import.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audio_suite_shared.exceptions import AudioFileNotFoundError  # noqa: E402
from utilities import rebuild_refinery_log as rrl  # noqa: E402


def _make_audio_file(directory: Path, name: str = "track.mp3") -> Path:
    """Write a real audio file to ``directory`` and return its path."""
    from pydub import AudioSegment

    path = directory / name
    AudioSegment.silent(duration=200, frame_rate=44100).export(
        str(path), format="mp3", bitrate="192k"
    )
    return path


class TestSha256Compatibility:
    """The local digest must equal the registry's for the same real file."""

    def test_local_sha256_matches_registry_sha256(self, tmp_path: Path) -> None:
        from audio_refinery.core.registry import _sha256 as registry_sha256

        path = _make_audio_file(tmp_path)
        assert rrl._sha256(path) == registry_sha256(path)

    def test_local_sha256_matches_registry_sha256_large_file(
        self, tmp_path: Path
    ) -> None:
        """Cross the 64 KiB block boundary so the block loop is exercised."""
        from audio_refinery.core.registry import _sha256 as registry_sha256

        path = tmp_path / "blob.bin"
        path.write_bytes(b"A" * (rrl._BLOCK * 3 + 17))
        assert rrl._sha256(path) == registry_sha256(path)


class TestWrittenLogFormat:
    """The log must carry the registry's exact line format and hash."""

    def test_written_log_lines_match_registry_digest(self, tmp_path: Path) -> None:
        from audio_refinery.core.registry import _sha256 as registry_sha256

        track = _make_audio_file(tmp_path)
        rrl.build_log_for_directory(tmp_path, dry_run=False, extensions={".mp3"})

        log_path = tmp_path / rrl.LOG_FILENAME
        assert log_path.exists()

        content_lines = log_path.read_text(encoding="utf-8").splitlines()
        entry_lines = [ln for ln in content_lines if not ln.startswith("#")]
        assert len(entry_lines) == 1

        digest, _, name = entry_lines[0].partition("  ")
        assert name == track.name
        assert digest == registry_sha256(track)

    def test_existing_log_is_not_overwritten(self, tmp_path: Path) -> None:
        _make_audio_file(tmp_path)
        log_path = tmp_path / rrl.LOG_FILENAME
        log_path.write_text("sentinel\n", encoding="utf-8")

        assert (
            rrl.build_log_for_directory(tmp_path, dry_run=False, extensions={".mp3"})
            == 0
        )
        assert log_path.read_text(encoding="utf-8") == "sentinel\n"

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        _make_audio_file(tmp_path)

        count = rrl.build_log_for_directory(tmp_path, dry_run=True, extensions={".mp3"})

        assert count == 1
        assert not (tmp_path / rrl.LOG_FILENAME).exists()

    def test_no_audio_files_reports_zero(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")

        assert (
            rrl.build_log_for_directory(tmp_path, dry_run=False, extensions={".mp3"})
            == 0
        )
        assert not (tmp_path / rrl.LOG_FILENAME).exists()


class TestExceptionContract:
    """The caller must catch what the function raises (audit M16)."""

    def test_non_directory_raises_audio_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(AudioFileNotFoundError):
            rrl.build_log_for_directory(
                tmp_path / "missing", dry_run=False, extensions={".mp3"}
            )

    def test_main_catches_the_raised_suite_exception(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A raised AudioFileNotFoundError becomes [ERROR], never a traceback.

        Pre-fix the caller caught the unrelated builtin FileNotFoundError, so
        this exception escaped as a raw traceback instead of a status line.
        """
        with (
            patch.object(
                rrl,
                "build_log_for_directory",
                side_effect=AudioFileNotFoundError("Not a directory: x"),
            ),
            patch.object(rrl.sys, "argv", ["rebuild_refinery_log.py", str(tmp_path)]),
        ):
            rrl.main()  # must not raise

        err = capsys.readouterr().err
        assert "[ERROR]" in err
        assert "Not a directory" in err

    def test_main_continues_after_a_failed_directory(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """One failing directory must not abort the remaining ones.

        main() pre-checks each top-level argument with is_dir() before
        iterating, so the raise is simulated on an existing directory —
        the mid-run race the handler actually guards against.
        """
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        _make_audio_file(second)

        original = rrl.build_log_for_directory
        calls: list[Path] = []

        def flaky(directory: Path, dry_run: bool, extensions: set) -> int:
            calls.append(directory)
            if directory == first:
                raise AudioFileNotFoundError(f"race: {directory} vanished")
            return original(directory, dry_run=dry_run, extensions=extensions)

        with (
            patch.object(rrl, "build_log_for_directory", side_effect=flaky),
            patch.object(
                rrl.sys,
                "argv",
                ["rebuild_refinery_log.py", str(first), str(second)],
            ),
        ):
            rrl.main()

        out = capsys.readouterr().out
        assert calls == [first, second]
        assert "1 file(s) registered" in out
        assert (second / rrl.LOG_FILENAME).exists()


class TestDocstringHonesty:
    """The docstring is the trusted spec for a hash-compatibility tool."""

    def test_docstring_no_longer_claims_the_registry_import(self) -> None:
        doc = rrl.__doc__ or ""
        assert "imports `_sha256` directly" not in doc, (
            "the docstring still claims a registry import that does not exist"
        )

    def test_docstring_documents_the_local_mirror_contract(self) -> None:
        doc = rrl.__doc__ or ""
        assert "local `_sha256`" in doc
        assert "mirrors" in doc

    def test_raises_clause_names_the_actual_exception(self) -> None:
        doc = rrl.build_log_for_directory.__doc__ or ""
        assert "AudioFileNotFoundError: If directory" in doc
        # Line-precise: a *bare* "FileNotFoundError:" Raises entry must be
        # gone. A plain `not in` can never pass because the bare name is a
        # substring of the correct one.
        assert not [
            line
            for line in doc.splitlines()
            if line.strip().startswith("FileNotFoundError:")
        ]
