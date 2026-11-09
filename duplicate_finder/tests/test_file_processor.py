# Changed in 2.6.0: exact matching (F-E9) and the exact/perceptual merge rule.
# Changed in 2.4.0: duplicate dispositions and ASX stubs.
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
import shutil
from pathlib import Path
from typing import Any

import pytest

from audio_suite_shared.asx_stub import read_stub
from audio_suite_shared.optional_deps import InstallOutcome
from audio_suite_shared.tag_helper_reader import (
    read_editable_tags,
    read_isrcs,
    read_lyrics_tags,
    read_musicbrainz_ids,
)
from audio_suite_shared.tag_helper_writer import (
    write_editable_tag,
    write_isrc,
    write_musicbrainz_ids,
    write_plain_lyrics,
)
from duplicate_finder.core import file_processor
from duplicate_finder.core.clustering import cluster_records
from duplicate_finder.core.exact import build_exact_groups
from duplicate_finder.core.file_processor import (
    STATUS_CACHED,
    STATUS_DELETED,
    STATUS_DUPLICATE,
    STATUS_ERROR,
    STATUS_EXACT,
    STATUS_EXACT_PCM,
    STATUS_KEEP,
    STATUS_MOVED,
    STATUS_NO_FINGERPRINT,
    STATUS_STUBBED,
    UNDO_OPERATION,
    default_quarantine_dir,
    discover_files,
    quarantine_file,
    run_duplicate_scan,
)
from duplicate_finder.core.models import FingerprintRecord, ScanSettings


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


class TestExactMode:
    """The exact-matching halves of a run (F-E9)."""

    @staticmethod
    def _with_identical_copy(library: Path) -> Path:
        """Add a byte-identical, differently named copy of the FLAC fixture."""
        # Sorts after ``song.flac``, so the fixture original stays the keeper
        # and the copy is the member the report names.
        copy = library / "song_zz_copy.flac"
        shutil.copy2(library / "song.flac", copy)
        return copy

    @pytest.mark.integration
    def test_exact_only_hashes_every_file_and_never_fingerprints(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_identical_copy(library)
        recorder = Recorder()

        def _must_not_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("an exact-only run called the fingerprinter")

        monkeypatch.setattr(file_processor, "build_record", _must_not_run)

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(exact_mode="only"),
            on_progress=recorder.on_progress,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        payload = recorder.completion
        assert recorder.errors == []
        assert payload["total"] == 8
        assert payload["hashed"] == 8
        assert payload["exact_groups"] == 1
        assert payload["exact_duplicates"] == 1
        assert all(
            call["display_text"].startswith(STATUS_EXACT) for call in recorder.progress
        )

    @pytest.mark.integration
    def test_exact_only_reuses_the_cached_digests(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._with_identical_copy(library)
        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(exact_mode="only"),
            on_complete=Recorder().on_complete,
        )
        second = Recorder()

        def _must_not_run(*_args: object, **_kwargs: object) -> str:
            raise AssertionError("a cached file was hashed again")

        monkeypatch.setattr(file_processor, "attach_hashes", _must_not_run)

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(exact_mode="only"),
            on_progress=second.on_progress,
            on_complete=second.on_complete,
        )

        assert second.completion["hashed"] == 0
        assert all(
            call["display_text"].startswith(STATUS_CACHED) for call in second.progress
        )

    @pytest.mark.integration
    def test_also_reports_both_kinds_and_names_each_file_once(
        self, library: Path
    ) -> None:
        self._with_identical_copy(library)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(exact_mode="also"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        payload = recorder.completion
        assert recorder.errors == []
        assert payload["exact_groups"] == 1
        assert payload["groups"] >= 2
        entries = payload["log_entries"]
        assert any(
            line.startswith(STATUS_EXACT) and "song_zz_copy.flac" in line
            for line in entries
        )
        assert any(line.startswith(STATUS_DUPLICATE) for line in entries)
        assert sum("song_zz_copy.flac" in line for line in entries) == 1

    def test_a_file_an_exact_group_keeps_is_never_a_perceptual_duplicate(
        self,
    ) -> None:
        """An ``also`` report must never name one file in two roles.

        The perceptual keeper can itself be an exact duplicate, and what is
        left beside it can be the exact group's *keeper*.  Claiming only the
        exact duplicates leaves that file printed as ``[KEEP]`` by one group
        and ``[DUPLICATE]`` by the other -- and a live run would then move a
        file the report tells the reader to keep.
        """
        words = (1, 2, 3, 4, 5, 6, 7, 8)

        def _record(path: str, bitrate: float, digest: str) -> FingerprintRecord:
            return FingerprintRecord(
                path=path,
                duration=30.0,
                words=words,
                size=1000,
                mtime=1.0,
                sample_rate=44100,
                channels=2,
                bitrate_kbps=bitrate,
                file_sha256=digest,
                pcm_sha256=digest,
            )

        records = [
            _record("a.flac", 128.0, "same"),
            _record("b.flac", 128.0, "same"),
            _record("c.flac", 320.0, "other"),
            _record("d.flac", 320.0, "third"),
        ]
        settings = ScanSettings(exact_mode="also")
        exact = build_exact_groups(records)
        perceptual = cluster_records(records, settings)

        merged = file_processor._merge_exact_and_perceptual(perceptual, exact, settings)

        keepers = {group.keeper.path for group in [*exact, *merged]}
        duplicates = {
            member.record.path
            for group in [*exact, *merged]
            for member in group.duplicates
        }
        assert exact and perceptual, "the fixture did not produce both kinds"
        assert keepers & duplicates == set(), "one file is named in two roles"
        assert "a.flac" not in duplicates
        assert [
            member.record.path for group in merged for member in group.duplicates
        ] == ["d.flac"]

    @pytest.mark.integration
    def test_a_tag_edit_is_grouped_by_pcm(self, library: Path) -> None:
        tagged = library / "tagged.flac"
        shutil.copy2(library / "song.flac", tagged)
        write_editable_tag(str(tagged), "title", "Another title")
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(exact_mode="only"),
            on_complete=recorder.on_complete,
        )

        payload = recorder.completion
        assert payload["exact_groups"] == 1
        assert any(
            line.startswith(STATUS_EXACT_PCM) and "tagged.flac" in line
            for line in payload["log_entries"]
        )

    @pytest.mark.integration
    def test_a_byte_copy_beside_a_retagged_copy_keeps_its_own_label(
        self, library: Path
    ) -> None:
        """Each member is labelled from its own digest, not the group's kind.

        One component can hold both a byte-for-byte copy and a retagged one;
        the group is then a PCM group, but the byte copy's line must not claim
        "different bytes" -- that sentence was the defect this test locks.
        """
        self._with_identical_copy(library)
        tagged = library / "song_zz_tagged.flac"
        shutil.copy2(library / "song.flac", tagged)
        write_editable_tag(str(tagged), "title", "Another title")
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(exact_mode="only"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        entries = recorder.completion["log_entries"]
        byte_line = next(line for line in entries if "song_zz_copy.flac" in line)
        pcm_line = next(line for line in entries if "song_zz_tagged.flac" in line)
        assert byte_line.startswith(STATUS_EXACT), byte_line
        assert "byte-identical" in byte_line
        assert pcm_line.startswith(STATUS_EXACT_PCM), pcm_line
        assert "different bytes" in pcm_line

    @pytest.mark.integration
    def test_exact_off_hashes_nothing(self, library: Path) -> None:
        recorder = Recorder()

        run_duplicate_scan(str(library), True, on_complete=recorder.on_complete)

        payload = recorder.completion
        assert payload["hashed"] == 0
        assert payload["exact_groups"] == 0


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


class _TrashRecorder:
    """Stand in for the Recycle Bin: record the path and remove the file."""

    def __init__(self) -> None:
        """Create an empty recorder."""
        self.paths: list[str] = []

    def __call__(self, path: str) -> None:
        """Record one path and remove it, as a successful Trash would."""
        self.paths.append(path)
        Path(path).unlink()


def _install_trash(
    monkeypatch: pytest.MonkeyPatch,
) -> _TrashRecorder:
    """Make the Trash seam available and record its calls.

    Args:
        monkeypatch: The test's patcher.

    Returns:
        The recorder holding every path the run trashed.
    """
    recorder = _TrashRecorder()
    monkeypatch.setattr(file_processor, "trash_available", lambda: True)
    monkeypatch.setattr(file_processor, "move_to_trash", recorder)
    return recorder


class TestDeleteDisposition:
    """Delete removes every duplicate through the Trash seam and nothing else."""

    @pytest.mark.integration
    def test_the_duplicates_are_trashed_and_the_keeper_survives(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trashed = _install_trash(monkeypatch)
        keeper = library / "song.flac"
        before = sha256(keeper)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="delete"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        payload = recorder.completion
        assert payload["deleted"] == 3
        assert payload["quarantined"] == 0
        assert payload["duplicates"] == 3
        assert payload["errors"] == 0
        assert sha256(keeper) == before
        assert sorted(path.name for path in library.iterdir()) == [
            "shared_a.mp3",
            "shared_b.mp3",
            "song.flac",
            "take2.mp3",
        ]
        assert sorted(Path(path).name for path in trashed.paths) == [
            "song_128.mp3",
            "song_320.mp3",
            "song_96.mp3",
        ]
        assert not any(Path(path).name == "song.flac" for path in trashed.paths)
        assert not (library / file_processor.QUARANTINE_DIRNAME).exists()
        deleted = [
            line for line in payload["log_entries"] if line.startswith(STATUS_DELETED)
        ]
        assert len(deleted) == 3

    @pytest.mark.integration
    def test_a_dry_run_reports_the_delete_and_trashes_nothing(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trashed = _install_trash(monkeypatch)
        before = {path.name: sha256(path) for path in library.iterdir()}
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(disposition="delete"),
            on_complete=recorder.on_complete,
        )

        assert trashed.paths == []
        assert recorder.completion["deleted"] == 0
        assert {path.name: sha256(path) for path in library.iterdir()} == before
        assert any(
            line.startswith(STATUS_DELETED) and "(dry run)" in line
            for line in recorder.completion["log_entries"]
        )

    @pytest.mark.integration
    def test_a_backend_that_cannot_be_installed_refuses_before_any_file_is_touched(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = {path.name: sha256(path) for path in library.iterdir()}
        monkeypatch.setattr(file_processor, "trash_available", lambda: False)
        monkeypatch.setattr(
            file_processor,
            "ensure_trash_available",
            lambda: InstallOutcome(
                False, "Recycle Bin support could not be installed."
            ),
        )
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="delete"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert len(recorder.errors) == 1
        assert "could not be prepared automatically" in recorder.errors[0]
        assert "no files were changed" in recorder.errors[0]
        assert "send2trash" not in recorder.errors[0]
        assert "Install it" not in recorder.errors[0]
        assert recorder.completions == []
        assert {path.name: sha256(path) for path in library.iterdir()} == before

    @pytest.mark.integration
    def test_a_missing_backend_is_installed_before_the_first_file(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        available = {"value": False}
        trashed = _TrashRecorder()
        installs: list[bool] = []
        monkeypatch.setattr(file_processor, "move_to_trash", trashed)
        monkeypatch.setattr(
            file_processor, "trash_available", lambda: available["value"]
        )

        def _install() -> InstallOutcome:
            installs.append(True)
            available["value"] = True
            return InstallOutcome(True, "Recycle Bin support is ready.")

        monkeypatch.setattr(file_processor, "ensure_trash_available", _install)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="delete"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert installs == [True]
        assert recorder.completion["deleted"] == 3
        assert len(trashed.paths) == 3


class TestStubDisposition:
    """A stub is written and verified before the duplicate reaches the Trash."""

    @pytest.mark.integration
    def test_every_duplicate_becomes_a_verified_stub(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trashed = _install_trash(monkeypatch)
        duplicate = library / "song_128.mp3"
        write_editable_tag(str(duplicate), "title", "Test Title")
        write_editable_tag(str(duplicate), "artist", "Test Artist")
        write_editable_tag(str(duplicate), "album", "Test Album")
        write_editable_tag(str(duplicate), "comment", "line one\nline two")
        write_musicbrainz_ids(
            str(duplicate),
            {"MUSICBRAINZ_TRACKID": "00000000-0000-0000-0000-000000000001"},
        )
        write_isrc(str(duplicate), ["GBAYE1234567"])
        write_plain_lyrics(str(duplicate), "first line\nsecond line")
        expected_fields = read_editable_tags(str(duplicate))
        expected_mbids = read_musicbrainz_ids(str(duplicate))
        expected_isrcs = read_isrcs(str(duplicate))
        expected_lyrics = read_lyrics_tags(str(duplicate))

        keeper = library / "song.flac"
        before = sha256(keeper)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="asx-stub"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        payload = recorder.completion
        assert payload["stubbed"] == 3
        assert payload["deleted"] == 0
        assert payload["quarantined"] == 0
        assert payload["errors"] == 0
        assert sha256(keeper) == before
        assert sorted(Path(path).name for path in trashed.paths) == [
            "song_128.mp3",
            "song_320.mp3",
            "song_96.mp3",
        ]
        assert not any(Path(path).name == "song.flac" for path in trashed.paths)

        stubs = sorted(library.glob("song_*.asx"))
        assert [path.name for path in stubs] == [
            "song_128.asx",
            "song_320.asx",
            "song_96.asx",
        ]
        for stub in stubs:
            metadata = read_stub(stub)
            assert metadata.stub_version == 1
            assert metadata.original_name == f"{stub.stem}.mp3"
            assert metadata.keeper_name == "song.flac"
            href = Path(metadata.reference)
            resolved = href if href.is_absolute() else stub.parent / href
            assert resolved.resolve() == keeper.resolve()

        tagged = read_stub(library / "song_128.asx")
        assert tagged.fields == {
            name: value or "" for name, value in expected_fields.items()
        }
        assert tagged.mbids == expected_mbids
        assert tagged.isrcs == expected_isrcs
        assert tagged.lyrics_plain == expected_lyrics.plain
        assert tagged.lyrics_synced == expected_lyrics.synced

    @pytest.mark.integration
    def test_a_stub_write_failure_leaves_the_audio_alone(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trashed = _install_trash(monkeypatch)

        def _fail(*_args: object, **_kwargs: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(file_processor, "write_stub", _fail)
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="asx-stub"),
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert trashed.paths == []
        assert sorted(path.name for path in library.iterdir()) == sorted(
            [
                "song.flac",
                "song_96.mp3",
                "song_128.mp3",
                "song_320.mp3",
                "take2.mp3",
                "shared_a.mp3",
                "shared_b.mp3",
            ]
        )
        assert recorder.completion["stubbed"] == 0
        assert recorder.completion["errors"] == 3
        assert list(library.glob("*.asx")) == []

    @pytest.mark.integration
    def test_an_existing_stub_name_is_never_overwritten(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_trash(monkeypatch)
        existing = library / "song_96.asx"
        existing.write_text("keep me", encoding="utf-8")
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="asx-stub"),
            on_complete=recorder.on_complete,
        )

        assert existing.read_text(encoding="utf-8") == "keep me"
        assert (library / "song_96 (2).asx").exists()
        assert recorder.completion["stubbed"] == 3

    @pytest.mark.integration
    def test_a_dry_run_writes_no_stub_and_trashes_nothing(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        trashed = _install_trash(monkeypatch)
        before = {path.name: sha256(path) for path in library.iterdir()}
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(disposition="asx-stub"),
            on_complete=recorder.on_complete,
        )

        assert trashed.paths == []
        assert list(library.glob("*.asx")) == []
        assert recorder.completion["stubbed"] == 0
        assert {path.name: sha256(path) for path in library.iterdir()} == before
        assert any(
            line.startswith(STATUS_STUBBED) and "(dry run)" in line
            for line in recorder.completion["log_entries"]
        )

    @pytest.mark.integration
    def test_a_second_scan_ignores_the_stubs(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_trash(monkeypatch)
        run_duplicate_scan(
            str(library),
            False,
            ScanSettings(disposition="asx-stub"),
            on_complete=Recorder().on_complete,
        )
        recorder = Recorder()

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(disposition="asx-stub"),
            on_complete=recorder.on_complete,
        )

        assert recorder.completion["groups"] == 0
        assert recorder.completion["duplicates"] == 0
