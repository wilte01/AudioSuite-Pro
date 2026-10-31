"""Tests for the declip batch, measured on the files it writes.

The workflow is the shared in-place one, so the guarantees under test are the
ones this tool inherits *and* the one it depends on: a file with nothing to
repair is skipped and never rewritten (its bytes and mtime are unchanged), while
a repaired file comes back with the harmonics reduced, the peak restored, its
tags, and its bit depth.

The measurement is taken from the written file, decoded -- never from the
counters the run published (``AGENTS.md``, *Defects and failing checks*).

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from mutagen import File as MutagenFile
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import segment_to_numpy
from audio_suite_shared.batch_undo import active_batch
from restoration.core import file_processor as file_processor_module
from restoration.core.declipper import (
    DEFAULT_MAX_RUN_MS,
    DEFAULT_THRESHOLD,
    declip_segment,
)
from restoration.core.file_processor import (
    DSP_LABEL,
    TAG_OPERATION,
    run_declipping,
)

from .conftest import channel, peak, sine, thd_db, to_segment

#: Same floor as the DSP suite: the measured improvement is 25 dB.
REQUIRED_THD_IMPROVEMENT_DB = 15.0

#: The original tone's peak, which a repair must approach again.
ORIGINAL_PEAK = 0.9886


def sha256(path: Path) -> str:
    """Return the file's hex digest.

    Args:
        path: File to hash.

    Returns:
        The SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_flac(path: Path, sample_width: int = 2) -> Path:
    """Write the clipped reference as a FLAC at *path*.

    Args:
        path: Destination path.
        sample_width: Source bit depth in bytes.

    Returns:
        *path*.
    """
    clipped = np.clip(sine(ORIGINAL_PEAK), -0.8, 0.8)
    segment = to_segment(clipped, sample_width=sample_width)
    parameters = ["-sample_fmt", "s32"] if sample_width == 3 else None
    if parameters is None:
        segment.export(str(path), format="flac")
    else:
        segment.export(str(path), format="flac", parameters=parameters)
    return path


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

    @property
    def lines(self) -> list[str]:
        """Return the run's report lines."""
        entries: list[str] = self.completion["log_entries"]
        return entries


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    """Return a folder with one clipped file and one clean file.

    Args:
        tmp_path: The test's own directory.

    Returns:
        The folder.
    """
    folder = tmp_path / "music"
    folder.mkdir()
    write_flac(folder / "clipped.flac")
    to_segment(sine(0.95)).export(str(folder / "clean.flac"), format="flac")
    return folder


class TestConstants:
    """The labels the guide and the undo journal quote."""

    def test_the_progress_label_names_the_work(self) -> None:
        assert DSP_LABEL == "Reconstructing peaks"

    def test_the_undo_operation_is_the_tool_s_own(self) -> None:
        assert TAG_OPERATION == "declip_edit"


class TestLiveRun:
    """What a live run changes, and what it leaves alone."""

    def test_the_clipped_file_is_repaired_and_measured(self, library: Path) -> None:
        before = channel(AudioSegment.from_file(str(library / "clipped.flac")))
        before_thd = thd_db(before)
        recorder = Recorder()

        run_declipping(
            str(library),
            False,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        after = channel(AudioSegment.from_file(str(library / "clipped.flac")))
        assert recorder.errors == []
        improvement = before_thd - thd_db(after)
        assert improvement >= REQUIRED_THD_IMPROVEMENT_DB, (
            f"THD improved {improvement:.2f} dB "
            f"({before_thd:.2f} -> {thd_db(after):.2f})"
        )
        assert peak(after) > peak(before)
        assert abs(peak(after) - ORIGINAL_PEAK) < 0.05

    def test_the_clean_file_is_not_rewritten(self, library: Path) -> None:
        clean = library / "clean.flac"
        before = (sha256(clean), clean.stat().st_mtime_ns)

        run_declipping(str(library), False, on_complete=Recorder().on_complete)

        assert (sha256(clean), clean.stat().st_mtime_ns) == before

    def test_the_counts_name_one_repaired_and_one_clean(self, library: Path) -> None:
        recorder = Recorder()

        run_declipping(str(library), False, on_complete=recorder.on_complete)

        payload = recorder.completion
        assert payload["total"] == 2
        assert payload["succeeded"] == 1
        assert payload["skipped"] == 1
        assert payload["errors"] == 0
        lines = recorder.lines
        assert any(line.startswith("[FIXED] clipped.flac") for line in lines)
        assert any(line.startswith("[SKIP] clean.flac") for line in lines)

    def test_the_duration_sample_rate_and_channels_survive(self, library: Path) -> None:
        before = AudioSegment.from_file(str(library / "clipped.flac"))

        run_declipping(str(library), False, on_complete=Recorder().on_complete)

        after = AudioSegment.from_file(str(library / "clipped.flac"))
        assert after.frame_rate == before.frame_rate
        assert after.channels == before.channels
        assert abs(after.duration_seconds - before.duration_seconds) < 0.05

    def test_the_tags_are_carried_over(self, library: Path) -> None:
        target = library / "clipped.flac"
        audio = MutagenFile(str(target))
        assert audio is not None
        audio["title"] = ["Kept Title"]
        audio["artist"] = ["Kept Artist"]
        audio.save()

        run_declipping(str(library), False, on_complete=Recorder().on_complete)

        after = MutagenFile(str(target))
        assert after is not None
        assert after["title"] == ["Kept Title"]
        assert after["artist"] == ["Kept Artist"]

    def test_a_24_bit_source_stays_24_bit(self, tmp_path: Path) -> None:
        folder = tmp_path / "wide"
        folder.mkdir()
        target = write_flac(folder / "wide.flac", sample_width=3)
        before = MutagenFile(str(target))
        assert before is not None
        assert before.info.bits_per_sample == 24

        run_declipping(str(folder), False, on_complete=Recorder().on_complete)

        after = MutagenFile(str(target))
        assert after is not None
        assert after.info.bits_per_sample == 24


class TestDryRun:
    """A dry run reports what it would repair and writes nothing."""

    def test_no_file_is_touched(self, library: Path) -> None:
        before = {
            path.name: (sha256(path), path.stat().st_mtime_ns)
            for path in library.iterdir()
        }
        recorder = Recorder()

        run_declipping(
            str(library),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert {
            path.name: (sha256(path), path.stat().st_mtime_ns)
            for path in library.iterdir()
        } == before
        assert any(line.startswith("[FOUND] clipped.flac") for line in recorder.lines)

    def test_the_detected_file_is_counted_not_repaired(self, library: Path) -> None:
        recorder = Recorder()

        run_declipping(str(library), True, on_complete=recorder.on_complete)

        payload = recorder.completion
        assert payload["succeeded"] == 1
        assert payload["skipped"] == 1


class TestParameterPlumbing:
    """The settings the window sends reach the DSP.

    A spy rather than a behavioural assertion: a 1 kHz plateau is only ~9
    samples, so no plausible width limit would actually reject it, and a test
    that picked one anyway would pass while proving nothing about the plumbing.
    """

    def test_the_threshold_and_width_reach_the_dsp(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[float, int]] = []
        real = declip_segment

        def _spy(audio: AudioSegment, threshold: float, max_run_ms: int) -> Any:
            seen.append((threshold, max_run_ms))
            return real(audio, threshold=threshold, max_run_ms=max_run_ms)

        monkeypatch.setattr(file_processor_module, "declip_segment", _spy)

        run_declipping(
            str(library),
            True,
            threshold=0.71,
            max_run_ms=7,
            on_complete=Recorder().on_complete,
        )

        assert seen == [(0.71, 7), (0.71, 7)]

    def test_the_shipped_defaults_are_sent_when_none_are_passed(
        self, library: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[float, int]] = []
        real = declip_segment

        def _spy(audio: AudioSegment, threshold: float, max_run_ms: int) -> Any:
            seen.append((threshold, max_run_ms))
            return real(audio, threshold=threshold, max_run_ms=max_run_ms)

        monkeypatch.setattr(file_processor_module, "declip_segment", _spy)

        run_declipping(str(library), True, on_complete=Recorder().on_complete)

        assert seen == [(DEFAULT_THRESHOLD, DEFAULT_MAX_RUN_MS)] * 2

    def test_a_headless_run_needs_no_slot_pool(self, library: Path) -> None:
        # Regression: an empty slot queue blocked the first worker forever
        # rather than failing, so every no-window caller hung.
        recorder = Recorder()

        run_declipping(
            str(library),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors == []
        assert recorder.completion["total"] == 2


class TestEmptyFolder:
    """Nothing to do is reported, not crashed."""

    def test_an_empty_folder_reports_an_error(self, tmp_path: Path) -> None:
        recorder = Recorder()

        run_declipping(
            str(tmp_path),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors, "an empty folder must report why it did nothing"

    def test_a_missing_folder_reports_an_error(self, tmp_path: Path) -> None:
        recorder = Recorder()

        run_declipping(
            str(tmp_path / "nope"),
            True,
            on_complete=recorder.on_complete,
            on_error=recorder.on_error,
        )

        assert recorder.errors

    def test_the_undo_database_records_the_overwrite(
        self, library: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        database = tmp_path / "undo.db"
        monkeypatch.setenv("AUDIOSUITE_UNDO_DB", str(database))

        # The window and the CLI both open the undo batch; without one the
        # snapshot has nowhere to go and the write would not be reversible.
        with active_batch("restoration", TAG_OPERATION):
            run_declipping(str(library), False, on_complete=Recorder().on_complete)

        assert database.exists(), "a live write must be reversible"
        assert os.path.getsize(database) > 0


class TestChannels:
    """The repair is not a mono operation applied to a stereo file."""

    def test_both_channels_are_reconstructed(self, tmp_path: Path) -> None:
        folder = tmp_path / "stereo"
        folder.mkdir()
        write_flac(folder / "clipped.flac")

        run_declipping(str(folder), False, on_complete=Recorder().on_complete)

        decoded, rate = segment_to_numpy(
            AudioSegment.from_file(str(folder / "clipped.flac"))
        )
        assert rate == 44100
        assert decoded.shape[0] == 2
        assert all(peak(decoded[index].astype(np.float64)) > 0.8 for index in range(2))
