"""Tests for the duplicate scan: walk, cache reuse, and the quarantine move.

The outcome that matters is on disk, not in the counters: a dry run must leave
the library exactly as it was, and a live run must move the duplicates while
leaving the keeper byte-identical -- which the tests check by hashing it, because
"the code never writes the keeper" is a claim about code, not about the file.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from duplicate_finder.core import file_processor
from duplicate_finder.core.file_processor import (
    STATUS_CACHED,
    STATUS_DUPLICATE,
    STATUS_ERROR,
    STATUS_KEEP,
    STATUS_MOVED,
    STATUS_NO_FINGERPRINT,
    UNDO_OPERATION,
    default_quarantine_dir,
    discover_files,
    quarantine_file,
    run_duplicate_scan,
)
from duplicate_finder.core.models import ScanSettings


def sha256(path: Path) -> str:
    """Return the file's hex digest.

    Args:
        path: File to hash.

    Returns:
        The SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Recorder:
    """Collect the callbacks a run makes."""

    def __init__(self) -> None:
        """Create an empty recorder."""
        self.progress: list[dict[str, Any]] = []
        self.completions: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def on_progress(self, **kwargs: Any) -> None:
        """Record one progress call."""
        self.progress.append(kwargs)

    def on_complete(self, **kwargs: Any) -> None:
        """Record the completion call."""
        self.completions.append(kwargs)

    def on_error(self, message: str) -> None:
        """Record a fatal-error call."""
        self.errors.append(message)

    @property
    def completion(self) -> dict[str, Any]:
        """Return the single completion payload, failing when there was none."""
        assert len(self.completions) == 1, self.completions
        return self.completions[0]


class TestDiscoverFiles:
    """The walk, and what it must never pick up."""

    def test_supported_audio_is_found_recursively_and_sorted(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "sub").mkdir()
        (tmp_path / "b.mp3").write_bytes(b"x")
        (tmp_path / "sub" / "a.flac").write_bytes(b"x")

        found = discover_files(str(tmp_path))

        assert [Path(path).name for path in found] == ["b.mp3", "a.flac"]

    def test_unsupported_files_are_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_bytes(b"x")
        (tmp_path / "cover.jpg").write_bytes(b"x")

        assert discover_files(str(tmp_path)) == []

    def test_a_hidden_directory_is_not_walked(self, tmp_path: Path) -> None:
        (tmp_path / ".trash").mkdir()
        (tmp_path / ".trash" / "a.mp3").write_bytes(b"x")

        assert discover_files(str(tmp_path)) == []

    def test_the_quarantine_folder_is_skipped_entirely(self, tmp_path: Path) -> None:
        quarantine = tmp_path / "quarantine"
        quarantine.mkdir()
        (quarantine / "moved.mp3").write_bytes(b"x")
        (tmp_path / "kept.mp3").write_bytes(b"x")

        found = discover_files(str(tmp_path), str(quarantine))

        assert [Path(path).name for path in found] == ["kept.mp3"]

    def test_case_differences_do_not_defeat_the_quarantine_skip(
        self, tmp_path: Path
    ) -> None:
        quarantine = tmp_path / "Quarantine"
        quarantine.mkdir()
        (quarantine / "moved.mp3").write_bytes(b"x")

        assert discover_files(str(tmp_path), str(quarantine)) == []


class TestQuarantineLocation:
    """Where a live run puts what it moves."""

    def test_the_default_sits_inside_the_scanned_folder(self, tmp_path: Path) -> None:
        assert default_quarantine_dir(str(tmp_path)) == str(
            tmp_path / file_processor.QUARANTINE_DIRNAME
        )

    def test_the_default_is_outside_the_walk(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        quarantine = default_quarantine_dir(str(tmp_path))

        moved = discover_files(str(tmp_path), quarantine)

        assert [Path(path).name for path in moved] == ["a.mp3"]


class TestQuarantineFile:
    """The move itself: no overwrites, and recorded for undo."""

    def test_a_file_is_moved_into_a_folder_that_is_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        source = tmp_path / "song.mp3"
        source.write_bytes(b"audio")
        destination_dir = tmp_path / "quarantine"
        recorded: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            file_processor,
            "record_file_reorg_snapshot",
            lambda src, dst, action: recorded.append((src, dst, action)),
        )

        destination = quarantine_file(str(source), str(destination_dir))

        assert Path(destination).read_bytes() == b"audio"
        assert not source.exists()
        assert recorded == [(str(source), destination, "move")]

    def test_a_name_collision_gains_a_suffix_instead_of_overwriting(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            file_processor, "record_file_reorg_snapshot", lambda *_args: None
        )
        destination_dir = tmp_path / "quarantine"
        destination_dir.mkdir()
        (destination_dir / "song.mp3").write_bytes(b"first")
        source = tmp_path / "song.mp3"
        source.write_bytes(b"second")

        destination = quarantine_file(str(source), str(destination_dir))

        assert Path(destination).name == "song (2).mp3"
        assert (destination_dir / "song.mp3").read_bytes() == b"first"
        assert Path(destination).read_bytes() == b"second"

    def test_the_undo_operation_is_the_file_move(self) -> None:
        assert UNDO_OPERATION == "file_reorg"


class TestRunErrors:
    """A run that cannot start says so once, through ``on_error``."""

    def test_a_missing_directory_is_reported(self, tmp_path: Path) -> None:
        recorder = Recorder()

        run_duplicate_scan(
            str(tmp_path / "nope"),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == [f"Not a directory: {tmp_path / 'nope'}"]
        assert recorder.completions == []

    def test_a_folder_without_audio_is_reported(self, tmp_path: Path) -> None:
        recorder = Recorder()

        run_duplicate_scan(
            str(tmp_path),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == [
            "No supported audio files found in the selected directory."
        ]

    def test_the_quarantine_folder_cannot_be_the_scanned_folder(
        self, library: Path
    ) -> None:
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(quarantine_dir=str(library)),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == [
            "The quarantine folder cannot be the folder being scanned."
        ]
        assert len(list(library.iterdir())) == 7


class TestDryRun:
    """A dry run reports the duplicates and changes nothing."""

    @pytest.mark.integration
    def test_nothing_is_moved_and_the_keeper_is_byte_identical(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            file_processor, "record_file_reorg_snapshot", lambda *_args: object()
        )
        before = {path.name: sha256(path) for path in library.iterdir()}
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(quarantine_dir=str(tmp_path / "quarantine")),
            on_complete=recorder.on_complete,
            on_progress=recorder.on_progress,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert recorder.completion["quarantined"] == 0
        assert recorder.completion["duplicates"] == 3
        assert recorder.completion["groups"] == 1
        assert not (tmp_path / "quarantine").exists()
        assert {path.name: sha256(path) for path in library.iterdir()} == before

    @pytest.mark.integration
    def test_the_report_names_the_keeper_and_every_duplicate(
        self, library: Path, tmp_path: Path
    ) -> None:
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(quarantine_dir=str(tmp_path / "quarantine")),
            on_complete=recorder.on_complete,
        )

        entries = recorder.completion["log_entries"]
        KEEP = STATUS_KEEP
        DUPLICATE = STATUS_DUPLICATE
        assert any(line.startswith(KEEP) and "song.flac" in line for line in entries)
        duplicates = [line for line in entries if line.startswith(DUPLICATE)]
        assert len(duplicates) == 3
        assert all("distance " in line and "from keeper" in line for line in duplicates)
        assert not any(line.startswith(STATUS_MOVED) for line in entries)

    @pytest.mark.integration
    def test_the_header_states_the_mode_the_folder_and_the_threshold(
        self, library: Path, tmp_path: Path
    ) -> None:
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(threshold=0.12, quarantine_dir=str(tmp_path / "q")),
            on_complete=recorder.on_complete,
        )

        header = "".join(recorder.completion["header"])
        assert "DUPLICATE REPORT" in header
        assert "Mode: DRY RUN" in header
        assert "Threshold: 0.12 bit-error rate" in header
        assert str(library.resolve()) in header

    @pytest.mark.integration
    def test_progress_is_reported_once_per_file(self, library: Path) -> None:
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            on_progress=recorder.on_progress,
            on_complete=recorder.on_complete,
        )

        assert [call["processed"] for call in recorder.progress] == list(range(1, 8))
        assert {call["total"] for call in recorder.progress} == {7}


class TestLiveRun:
    """A live run moves the duplicates and leaves the keeper alone."""

    @pytest.mark.integration
    def test_the_duplicates_are_quarantined_and_the_keeper_survives(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            file_processor,
            "record_file_reorg_snapshot",
            lambda src, dst, action: recorded.append((src, dst, action)),
        )
        keeper = library / "song.flac"
        before = sha256(keeper)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(quarantine_dir=str(tmp_path / "quarantine")),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert recorder.completion["quarantined"] == 3
        assert sha256(keeper) == before
        assert sorted(path.name for path in library.iterdir()) == [
            "shared_a.mp3",
            "shared_b.mp3",
            "song.flac",
            "take2.mp3",
        ]
        assert sorted(path.name for path in (tmp_path / "quarantine").iterdir()) == [
            "song_128.mp3",
            "song_320.mp3",
            "song_96.mp3",
        ]
        assert len(recorded) == 3
        assert {action for _src, _dst, action in recorded} == {"move"}

    @pytest.mark.integration
    def test_a_second_run_does_not_re_find_the_quarantine(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            file_processor, "record_file_reorg_snapshot", lambda *_args: None
        )
        quarantine = str(tmp_path / "quarantine")
        first, second = Recorder(), Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(quarantine_dir=quarantine),
            on_complete=first.on_complete,
        )
        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(quarantine_dir=quarantine),
            on_complete=second.on_complete,
        )

        assert first.completion["quarantined"] == 3
        assert second.completion["total"] == 4
        assert second.completion["groups"] == 0
        assert "No duplicate recordings found.\n" in second.completion["log_entries"]

    @pytest.mark.integration
    def test_the_default_quarantine_folder_is_used_when_none_is_chosen(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            file_processor, "record_file_reorg_snapshot", lambda *_args: None
        )
        recorder = Recorder()

        run_duplicate_scan(str(library), False, on_complete=recorder.on_complete)

        assert (library / file_processor.QUARANTINE_DIRNAME).is_dir()
        assert recorder.completion["quarantined"] == 3


class TestTheCacheIsUsed:
    """A second run reuses stored fingerprints instead of re-running fpcalc."""

    @pytest.mark.integration
    def test_a_second_run_reads_every_file_from_the_cache(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first, second = Recorder(), Recorder()
        run_duplicate_scan(str(library), True, on_complete=first.on_complete)

        def _must_not_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("a fresh file was re-fingerprinted")

        monkeypatch.setattr(file_processor, "build_record", _must_not_run)
        run_duplicate_scan(
            str(library),
            True,
            on_progress=second.on_progress,
            on_complete=second.on_complete,
        )

        assert second.progress, "the run reported no file at all"
        assert all(
            call["display_text"].startswith(STATUS_CACHED) for call in second.progress
        )
        assert second.completion["groups"] == 1

    @pytest.mark.integration
    def test_a_changed_file_is_fingerprinted_again(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        run_duplicate_scan(str(library), True, on_complete=Recorder().on_complete)
        rewritten = library / "take2.mp3"
        rewritten.write_bytes(rewritten.read_bytes() + b"\0")
        os.utime(rewritten, (1_700_000_000, 1_700_000_000))
        seen: list[str] = []
        real_build = file_processor.build_record

        def _spy(path: str, mtime: float, size: int) -> object:
            seen.append(Path(path).name)
            return real_build(path, mtime, size)

        monkeypatch.setattr(file_processor, "build_record", _spy)

        run_duplicate_scan(str(library), True, on_complete=Recorder().on_complete)

        assert seen == ["take2.mp3"]


class TestPerFileFailures:
    """One unreadable file is a skip, never a failed run."""

    @pytest.mark.integration
    def test_a_file_without_a_fingerprint_is_counted_and_reported(
        self, library: Path
    ) -> None:
        broken = library / "broken.mp3"
        broken.write_bytes(b"not audio at all")
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert recorder.completion["skipped"] == 1
        assert any(
            line.startswith(STATUS_NO_FINGERPRINT) and "broken.mp3" in line
            for line in recorder.completion["log_entries"]
        )
        assert recorder.completion["groups"] == 1

    @pytest.mark.integration
    def test_a_failed_move_is_an_error_but_the_run_finishes(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(*_args: object, **_kwargs: object) -> str:
            raise OSError("destination is read-only")

        monkeypatch.setattr(file_processor, "quarantine_file", _fail)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(quarantine_dir=str(tmp_path / "quarantine")),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert recorder.completion["errors"] == 3
        assert recorder.completion["quarantined"] == 0
        assert any(
            line.startswith(STATUS_ERROR) for line in recorder.completion["log_entries"]
        )


class TestCompletionPayload:
    """The fields the window's handler reads are the ones the run publishes."""

    def test_every_published_field_is_present_in_a_clean_scan(
        self, tmp_path: Path
    ) -> None:
        recorder = Recorder()
        (tmp_path / "a.flac").write_bytes(b"x")

        run_duplicate_scan(
            str(tmp_path),
            True,
            on_complete=recorder.on_complete,
            on_progress=recorder.on_progress,
            on_error=recorder.on_error,
            slot_vars=[],
            slot_queue=None,
        )

        # The single file cannot be fingerprinted, so this is the skip path --
        # which is also the only path that must still publish a completion.
        payload = recorder.completion
        assert {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
            "groups",
            "duplicates",
            "quarantined",
        } <= set(payload)
        assert payload["total"] == 1
        assert payload["skipped"] == 1
        assert payload["groups"] == 0
