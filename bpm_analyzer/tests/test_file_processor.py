"""
tests/test_file_processor.py
pytest suite for bpm_analyzer.core.file_processor

Covers:
  • process_single_file — happy paths (dry run, live)
  • process_single_file — BPMDetectionError surfaced to on_progress as ERROR
  • process_single_file — out-of-range detect_bpm return is tagged, not
    skipped (regression test: the dead SKIP branch was removed since
    detect_bpm always clamps into [min_bpm, max_bpm] in real usage)
  • run_analysis — delegates to BaseFileProcessor.run_parallel_processing
  • Logging output verified via caplog
  • run_analysis — a typed worker count above the slot grid still finishes
    every file (D66)

Changed in 1.4.0: adds the slot-grid cap regression for a typed worker count.

Changed in 1.4.1: asserts the kernel warm-up runs before the pool is built,
not merely that it runs (backlog P6).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audio_suite_shared.exceptions import failure_reason
from bpm_analyzer.core.bpm_detector import (
    MIN_ONSET_PERIODICITY,
    BPMDetectionError,
    NoTempoDetectedError,
)
from bpm_analyzer.core.file_processor import (
    ProcessingStatus,
    _detect_bpm_cpu,
    _handle_bpm_result,
    process_single_file,
    run_analysis,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def lock() -> threading.Lock:
    return threading.Lock()


@pytest.fixture()
def progress_calls() -> list[dict[str, Any]]:
    """Collects keyword arguments from each on_progress call."""
    calls: list[dict[str, Any]] = []
    return calls


@pytest.fixture()
def on_progress(progress_calls):
    def _cb(**kwargs):
        progress_calls.append(kwargs)

    return _cb


@pytest.fixture()
def slot_vars():
    class FakeVar:
        def __init__(self):
            self.value = ""

        def set(self, v):
            self.value = v

    return [FakeVar() for _ in range(4)]


# ---------------------------------------------------------------------------
# 1. process_single_file — dry run happy path
# ---------------------------------------------------------------------------


class TestProcessSingleFileDryRun:
    def test_progress_called_once(self, lock, on_progress, progress_calls, slot_vars):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            process_single_file(
                name="track.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        assert len(progress_calls) == 1

    def test_no_skipped_no_errors(self, lock, on_progress, progress_calls, slot_vars):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            process_single_file(
                name="track.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        c = progress_calls[0]
        assert c["n_skipped"] == 0
        assert c["n_errors"] == 0

    def test_display_text_contains_dry_run(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            process_single_file(
                name="track.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        assert "DRY RUN" in progress_calls[0]["display_text"]

    def test_write_bpm_not_called_in_dry_run(self, lock, on_progress, slot_vars):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm", return_value=128
        ) as mock_detect:
            with patch("bpm_analyzer.core.file_processor.write_bpm") as mock_write:
                process_single_file(
                    name="track.mp3",
                    dir_path="/music",
                    is_dry_run=True,
                    min_bpm=75,
                    max_bpm=175,
                    analysis_duration=90,
                    slot_idx=0,
                    lock=lock,
                    on_progress=on_progress,
                    slot_vars=slot_vars,
                )
        mock_detect.assert_called_once()
        mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# 2. process_single_file — live update happy path
# ---------------------------------------------------------------------------


class TestProcessSingleFileLive:
    def test_write_bpm_called(self, lock, on_progress, slot_vars):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            with patch("bpm_analyzer.core.file_processor.read_bpm", return_value=None):
                with patch("bpm_analyzer.core.file_processor.write_bpm") as mock_write:
                    process_single_file(
                        name="track.mp3",
                        dir_path="/music",
                        is_dry_run=False,
                        min_bpm=75,
                        max_bpm=175,
                        analysis_duration=90,
                        slot_idx=0,
                        lock=lock,
                        on_progress=on_progress,
                        slot_vars=slot_vars,
                    )
        import os

        mock_write.assert_called_once_with(os.path.join("/music", "track.mp3"), 128)

    def test_display_text_contains_tagged(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            with patch("bpm_analyzer.core.file_processor.read_bpm", return_value=None):
                with patch("bpm_analyzer.core.file_processor.write_bpm"):
                    process_single_file(
                        name="track.mp3",
                        dir_path="/music",
                        is_dry_run=False,
                        min_bpm=75,
                        max_bpm=175,
                        analysis_duration=90,
                        slot_idx=0,
                        lock=lock,
                        on_progress=on_progress,
                        slot_vars=slot_vars,
                    )
        assert "TAGGED" in progress_calls[0]["display_text"]

    def test_existing_bpm_shown_in_display(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            with patch("bpm_analyzer.core.file_processor.read_bpm", return_value=100):
                with patch("bpm_analyzer.core.file_processor.write_bpm"):
                    process_single_file(
                        name="track.mp3",
                        dir_path="/music",
                        is_dry_run=False,
                        min_bpm=75,
                        max_bpm=175,
                        analysis_duration=90,
                        slot_idx=0,
                        lock=lock,
                        on_progress=on_progress,
                        slot_vars=slot_vars,
                    )
        assert "was 100" in progress_calls[0]["display_text"]


# ---------------------------------------------------------------------------
# 3. process_single_file — out-of-range detect_bpm return is no longer
#    skipped (regression test for removal of dead SKIP branch)
# ---------------------------------------------------------------------------


def _write_noise_wav(
    path: Path, seconds: float = 10.0, sr: int = 22050, seed: int = 99
) -> Path:
    """Write seeded broadband noise: audible, long enough, and beatless."""
    from pydub import AudioSegment

    rng = np.random.default_rng(seed)
    samples = np.clip(0.3 * rng.standard_normal(int(sr * seconds)), -1.0, 1.0)
    pcm = (samples * 32767).astype(np.int16)
    segment = AudioSegment(pcm.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    segment.export(str(path), format="wav")
    return path


def _write_tone_wav(path: Path, seconds: float = 10.0, sr: int = 22050) -> Path:
    """Write a real 440 Hz tone: audible, long enough, and beatless."""
    from pydub import AudioSegment

    t = np.arange(int(sr * seconds)) / sr
    pcm = (0.4 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
    segment = AudioSegment(pcm.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    segment.export(str(path), format="wav")
    return path


def _write_click_wav(
    path: Path, bpm: float = 120.0, seconds: float = 8.0, sr: int = 22050
) -> Path:
    """Write a real periodic click train: audible and beat-trackable."""
    from pydub import AudioSegment

    n = int(sr * seconds)
    signal = np.zeros(n)
    click_len = max(4, int(0.004 * sr))
    decay = np.exp(-np.linspace(0.0, 8.0, click_len))
    carrier = np.sin(2 * np.pi * 1000.0 * np.arange(click_len) / sr)
    for start in (np.arange(int(bpm / 60.0 * seconds) + 1) / (bpm / 60.0) * sr).astype(
        int
    ):
        end = min(start + click_len, n)
        signal[start:end] += carrier[: end - start] * decay[: end - start]
    signal = 0.9 * signal / float(np.max(np.abs(signal)))
    pcm = (signal * 32767).astype(np.int16)
    segment = AudioSegment(pcm.tobytes(), frame_rate=sr, sample_width=2, channels=1)
    segment.export(str(path), format="wav")
    return path


class TestNoTempoIsSkipped:
    """Beatless audio is reported as a skip, never as a clamped number.

    Regression: a non-positive tempo estimate was clamped to ``min_bpm`` and
    tagged, so a tone or a drone carried a BPM that looked measured.
    """

    def test_serial_path_reports_skip(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=NoTempoDetectedError(
                "No tempo detected — the audio has no discernible beat."
            ),
        ):
            process_single_file(
                name="drone.flac",
                dir_path="/music",
                is_dry_run=False,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        c = progress_calls[0]
        assert c["n_skipped"] == 1
        assert c["n_errors"] == 0
        assert "[SKIP]" in c["display_text"]
        assert "No tempo detected" in c["display_text"]

    def test_serial_skip_records_reason_and_score(
        self, lock, on_progress, slot_vars
    ) -> None:
        """--json needs the score as a number, not only inside the sentence."""
        exc = NoTempoDetectedError(
            "No tempo detected — the audio has no discernible beat "
            "(onset periodicity 0.04, minimum 0.10).",
            context={"tempo_estimate": 129.2, "onset_periodicity": 0.043},
        )
        skipped: list[dict[str, object]] = []
        with patch("bpm_analyzer.core.file_processor.detect_bpm", side_effect=exc):
            process_single_file(
                name="noise.wav",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
                skipped_files=skipped,
            )
        assert skipped == [
            {
                "filename": "noise.wav",
                "reason": failure_reason(exc),
                "onset_periodicity": 0.043,
            }
        ]

    def test_unmeasured_skip_records_a_null_score(self, lock, on_progress, slot_vars):
        """A non-positive tempo never reached the periodicity check."""
        exc = NoTempoDetectedError(
            "No tempo detected — the audio has no discernible beat.",
            context={"tempo_estimate": 0.0},
        )
        skipped: list[dict[str, object]] = []
        with patch("bpm_analyzer.core.file_processor.detect_bpm", side_effect=exc):
            process_single_file(
                name="drone.flac",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
                skipped_files=skipped,
            )
        assert skipped[0]["onset_periodicity"] is None

    def test_cpu_worker_reports_no_tempo(self):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=NoTempoDetectedError(
                "No tempo detected — the audio has no discernible beat."
            ),
        ):
            result = _detect_bpm_cpu(
                file_path="/music/drone.flac",
                analysis_duration=30,
                min_bpm=60,
                max_bpm=200,
            )
        assert result["status"] == "no_tempo"
        assert "No tempo detected" in str(result["error"])
        # No context means no score was measured; the record must not invent one.
        assert result["onset_periodicity"] is None

    def test_serial_error_records_reason_and_type(
        self, lock, on_progress, slot_vars
    ) -> None:
        """Errors are a separate list, with a machine-readable type."""
        exc = BPMDetectionError("The file may be corrupt or unreadable.")
        errors: list[dict[str, object]] = []
        with patch("bpm_analyzer.core.file_processor.detect_bpm", side_effect=exc):
            process_single_file(
                name="corrupt.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
                error_files=errors,
            )
        assert errors == [
            {
                "filename": "corrupt.mp3",
                "reason": failure_reason(exc),
                "error_type": "BPMDetectionError",
            }
        ]

    def test_cpu_worker_carries_the_measured_score(self):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=NoTempoDetectedError(
                "No tempo detected — the audio has no discernible beat "
                "(onset periodicity 0.04, minimum 0.10).",
                context={"onset_periodicity": 0.043},
            ),
        ):
            result = _detect_bpm_cpu(
                file_path="/music/noise.wav",
                analysis_duration=30,
                min_bpm=60,
                max_bpm=200,
            )
        assert result["onset_periodicity"] == 0.043

    def test_handler_reports_skip(self, lock, on_progress, progress_calls, slot_vars):
        _handle_bpm_result(
            filename="drone.flac",
            dir_path="/music",
            result={
                "status": "no_tempo",
                "error": "No tempo detected — the audio has no discernible beat.",
            },
            slot_idx=0,
            lock=lock,
            on_progress=on_progress,
            is_dry_run=False,
            slot_vars=slot_vars,
        )
        c = progress_calls[0]
        assert c["n_skipped"] == 1
        assert c["n_errors"] == 0
        assert "[SKIP]" in c["display_text"]
        assert "No tempo detected" in c["display_text"]

    def test_handler_appends_a_structured_record(
        self, lock, on_progress, slot_vars
    ) -> None:
        skipped: list[dict[str, object]] = []
        _handle_bpm_result(
            filename="noise.wav",
            dir_path="/music",
            result={
                "status": "no_tempo",
                "error": "No tempo detected — the audio has no discernible beat "
                "(onset periodicity 0.04, minimum 0.10).",
                "onset_periodicity": 0.043,
            },
            slot_idx=0,
            lock=lock,
            on_progress=on_progress,
            is_dry_run=False,
            slot_vars=slot_vars,
            skipped_files=skipped,
        )
        assert skipped == [
            {
                "filename": "noise.wav",
                "reason": "No tempo detected — the audio has no discernible beat "
                "(onset periodicity 0.04, minimum 0.10).",
                "onset_periodicity": 0.043,
            }
        ]

    def test_live_run_leaves_a_beatless_file_untagged(
        self, tmp_path: Path, lock, slot_vars
    ) -> None:
        """Outcome-level: a real tone is decoded, refused, and left untouched.

        A mocked write would not prove that the fabricated floor never reached
        the tag, so this reads the real tag back and compares the bytes.
        """
        from audio_suite_shared.tag_helper import read_bpm

        path = _write_tone_wav(tmp_path / "tone.wav")
        original = path.read_bytes()
        calls: list[dict[str, Any]] = []

        process_single_file(
            name="tone.wav",
            dir_path=str(tmp_path),
            is_dry_run=False,
            min_bpm=75,
            max_bpm=175,
            analysis_duration=90,
            slot_idx=0,
            lock=lock,
            on_progress=lambda **kwargs: calls.append(kwargs),
            slot_vars=slot_vars,
        )

        assert read_bpm(str(path)) is None
        assert path.read_bytes() == original
        assert calls[0]["n_skipped"] == 1
        assert "No tempo detected" in calls[0]["display_text"]

    def test_live_run_leaves_a_noise_only_file_untagged(
        self, tmp_path: Path, lock, slot_vars
    ) -> None:
        """The periodicity guard stops the spurious noise estimate from tagging.

        Random onsets fit a tempo grid, so this file reaches the tracker and
        gets a positive estimate; only the onset-autocorrelation check can
        refuse it.  The real tag reader and file bytes are the outcome.
        """
        from audio_suite_shared.tag_helper import read_bpm

        path = _write_noise_wav(tmp_path / "noise.wav")
        original = path.read_bytes()
        calls: list[dict[str, Any]] = []

        process_single_file(
            name="noise.wav",
            dir_path=str(tmp_path),
            is_dry_run=False,
            min_bpm=75,
            max_bpm=175,
            analysis_duration=90,
            slot_idx=0,
            lock=lock,
            on_progress=lambda **kwargs: calls.append(kwargs),
            slot_vars=slot_vars,
        )

        assert read_bpm(str(path)) is None
        assert path.read_bytes() == original
        assert calls[0]["n_skipped"] == 1
        assert "No tempo detected" in calls[0]["display_text"]
        # The per-file log carries the evidence, not just the verdict.
        assert "onset periodicity" in calls[0]["log_text"]
        assert f"minimum {MIN_ONSET_PERIODICITY:.2f}" in calls[0]["log_text"]
        assert "onset periodicity" in calls[0]["display_text"]


class TestProcessSingleFileOutOfRangeRegression:
    """detect_bpm() always clamps its return value into [min_bpm, max_bpm]
    (see bpm_detector tests), so process_single_file no longer has a
    reachable SKIP-on-range path. These tests mock an out-of-range return
    purely to confirm the removed branch stays removed — such a value
    should now be treated like any other detection result and tagged,
    never skipped.
    """

    def test_out_of_range_value_is_not_skipped(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=50):
            process_single_file(
                name="slow.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        c = progress_calls[0]
        assert c["n_skipped"] == 0
        assert "SKIP" not in c["display_text"]
        assert "DRY RUN" in c["display_text"]

    def test_out_of_range_value_above_max_is_not_skipped(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=200):
            process_single_file(
                name="fast.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        c = progress_calls[0]
        assert c["n_skipped"] == 0
        assert "SKIP" not in c["display_text"]


# ---------------------------------------------------------------------------
# 4. process_single_file — BPMDetectionError → ERROR reported to on_progress
# ---------------------------------------------------------------------------


class TestProcessSingleFileError:
    def test_detection_error_increments_error_count(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=BPMDetectionError("librosa failed"),
        ):
            process_single_file(
                name="corrupt.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        c = progress_calls[0]
        assert c["n_errors"] == 1
        assert c["n_skipped"] == 0

    def test_detection_error_does_not_raise(self, lock, on_progress, slot_vars):
        """A BPMDetectionError must be caught; process_single_file must not
        propagate it."""
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=BPMDetectionError("librosa failed"),
        ):
            # Should complete without raising
            process_single_file(
                name="corrupt.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )

    def test_error_display_text_contains_error_label(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=BPMDetectionError("bad"),
        ):
            process_single_file(
                name="bad.mp3",
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
        assert "ERROR" in progress_calls[0]["display_text"]


# ---------------------------------------------------------------------------
# 5. run_analysis — delegates to BaseFileProcessor
# ---------------------------------------------------------------------------


class TestRunAnalysis:
    def test_delegates_to_base_processor(self):
        """run_analysis must call BaseFileProcessor.run_parallel_processing
        exactly once."""
        mock_processor = MagicMock()
        on_progress = MagicMock()
        on_complete = MagicMock()
        on_error = MagicMock()

        with patch(
            "bpm_analyzer.core.file_processor.BPMAnalyzerProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=on_progress,
                on_complete=on_complete,
                on_error=on_error,
            )

        mock_processor.run_parallel_processing.assert_called_once()

    def test_correct_dir_path_forwarded(self):
        mock_processor = MagicMock()
        with patch(
            "bpm_analyzer.core.file_processor.BPMAnalyzerProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/my/music",
                is_dry_run=False,
                min_bpm=80,
                max_bpm=160,
                analysis_duration=60,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
            )
        call_kwargs = mock_processor.run_parallel_processing.call_args.kwargs
        assert call_kwargs["dir_path"] == "/my/music"

    def test_warms_the_analysis_stack_before_the_pool_starts(self):
        """P6: the warm-up must run before any worker thread can compile.

        A warm-up that runs *inside* the pool is the defect it exists to fix:
        every worker would still compile its own copy and contend for the lock.
        """
        order: list[str] = []
        processor = MagicMock()
        processor.run_parallel_processing.side_effect = lambda **_kw: order.append(
            "pool"
        )

        with (
            patch(
                "bpm_analyzer.core.file_processor.warm_analysis_stack",
                side_effect=lambda: order.append("warm"),
            ),
            patch(
                "bpm_analyzer.core.file_processor.BPMAnalyzerProcessor",
                return_value=processor,
            ),
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=90,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
            )

        assert order == ["warm", "pool"]


# ---------------------------------------------------------------------------
# 7. run_analysis — parallel_mode=True path
# ---------------------------------------------------------------------------


class TestRunAnalysisParallelMode:
    """Test that run_analysis with parallel_mode=True routes to
    run_cpu_bound_processing."""

    def test_parallel_mode_routes_to_cpu_bound_processing(self):
        """When parallel_mode=True, must call run_cpu_bound_processing, not
        run_parallel_processing."""
        mock_processor = MagicMock()
        with patch(
            "bpm_analyzer.core.file_processor.BPMAnalyzerProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
                parallel_mode=True,
            )

        mock_processor.run_cpu_bound_processing.assert_called_once()
        mock_processor.run_parallel_processing.assert_not_called()

    def test_parallel_mode_forwards_correct_cpu_worker(self):
        """Verify cpu_worker and result_handler are the top-level module functions."""
        mock_processor = MagicMock()
        with patch(
            "bpm_analyzer.core.file_processor.BPMAnalyzerProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
                parallel_mode=True,
            )

        call_kwargs = mock_processor.run_cpu_bound_processing.call_args.kwargs
        assert call_kwargs["cpu_worker"] is not None
        assert callable(call_kwargs["cpu_worker"])
        assert call_kwargs["result_handler"] is not None
        assert callable(call_kwargs["result_handler"])
        assert call_kwargs["max_workers"] is None
        # The result handler must receive the shared record list, and the
        # completion callback is wrapped so it can attach the collected list.
        assert call_kwargs["skipped_files"] == []
        assert callable(call_kwargs["on_complete"])

    def test_parallel_mode_with_custom_workers(self):
        """Custom max_workers must be forwarded to run_cpu_bound_processing."""
        mock_processor = MagicMock()
        with patch(
            "bpm_analyzer.core.file_processor.BPMAnalyzerProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
                parallel_mode=True,
                max_workers=8,
            )

        call_kwargs = mock_processor.run_cpu_bound_processing.call_args.kwargs
        assert call_kwargs["max_workers"] == 8


# ---------------------------------------------------------------------------
# 8. _detect_bpm_cpu — CPU worker function
# ---------------------------------------------------------------------------


class TestDetectBpmCpu:
    def test_returns_ok_on_success(self):
        with patch("bpm_analyzer.core.file_processor.detect_bpm", return_value=128):
            result = _detect_bpm_cpu(
                file_path="/music/track.mp3",
                analysis_duration=30,
                min_bpm=60,
                max_bpm=200,
            )
        assert result["status"] == "ok"
        assert result["bpm"] == 128

    def test_returns_error_on_detection_failure(self):
        from bpm_analyzer.core.bpm_detector import BPMDetectionError

        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=BPMDetectionError("bad file"),
        ):
            result = _detect_bpm_cpu(
                file_path="/music/corrupt.mp3",
                analysis_duration=30,
                min_bpm=60,
                max_bpm=200,
            )
        assert result["status"] == "error"
        assert "bad file" in str(result["error"])
        assert result["error_type"] == "BPMDetectionError"

    def test_returns_error_on_unexpected_exception(self):
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            side_effect=ValueError("unexpected"),
        ):
            result = _detect_bpm_cpu(
                file_path="/music/corrupt.mp3",
                analysis_duration=30,
                min_bpm=60,
                max_bpm=200,
            )
        assert result["status"] == "error"
        assert result["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# 9. _handle_bpm_result — result handler
# ---------------------------------------------------------------------------


class TestHandleBpmResult:
    def test_ok_result_calls_on_progress(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        _handle_bpm_result(
            filename="track.mp3",
            dir_path="/music",
            result={"status": "ok", "bpm": 128},
            slot_idx=0,
            lock=lock,
            on_progress=on_progress,
            is_dry_run=True,
            slot_vars=slot_vars,
        )
        assert len(progress_calls) == 1
        assert "DRY RUN" in progress_calls[0]["display_text"]

    def test_error_result_calls_on_progress_with_error(
        self, lock, on_progress, progress_calls, slot_vars
    ):
        _handle_bpm_result(
            filename="bad.mp3",
            dir_path="/music",
            result={"status": "error", "error": "detection failed"},
            slot_idx=0,
            lock=lock,
            on_progress=on_progress,
            is_dry_run=True,
            slot_vars=slot_vars,
        )
        assert len(progress_calls) == 1
        assert progress_calls[0]["n_errors"] == 1

    def test_handler_appends_a_structured_error_record(
        self, lock, on_progress, slot_vars
    ) -> None:
        errors: list[dict[str, object]] = []
        _handle_bpm_result(
            filename="corrupt.mp3",
            dir_path="/music",
            result={
                "status": "error",
                "error": "The file may be corrupt or unreadable.",
                "error_type": "BPMDetectionError",
            },
            slot_idx=0,
            lock=lock,
            on_progress=on_progress,
            is_dry_run=True,
            slot_vars=slot_vars,
            error_files=errors,
        )
        assert errors == [
            {
                "filename": "corrupt.mp3",
                "reason": "The file may be corrupt or unreadable.",
                "error_type": "BPMDetectionError",
            }
        ]

    def test_live_mode_writes_tag(self, lock, slot_vars):
        import os as _os

        on_progress = MagicMock()
        with patch("bpm_analyzer.core.file_processor.read_bpm", return_value=None):
            with patch("bpm_analyzer.core.file_processor.write_bpm") as mock_write:
                _handle_bpm_result(
                    filename="track.mp3",
                    dir_path="/music",
                    result={"status": "ok", "bpm": 128},
                    slot_idx=0,
                    lock=lock,
                    on_progress=on_progress,
                    is_dry_run=False,
                    slot_vars=slot_vars,
                )
        mock_write.assert_called_once_with(_os.path.join("/music", "track.mp3"), 128)


# ---------------------------------------------------------------------------
# 10. Undo-batch recording (record side of undo feature)
# ---------------------------------------------------------------------------


class TestUndoBatchRecording:
    def test_thread_mode_records_snapshots_from_worker_threads(
        self, tmp_path: Path
    ) -> None:
        """run_analysis in thread mode must record tag snapshots from its
        worker threads into the active undo batch (via use_batch)."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "track1.mp3").write_bytes(b"")
        (tmp_path / "track2.mp3").write_bytes(b"")

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TBPM": "100"}
        handler.read_bpm.return_value = 100
        slot_vars = [MagicMock() for _ in range(4)]

        on_progress = MagicMock()
        on_complete = MagicMock()
        on_error = MagicMock()

        # TagHandlerFactory is imported into the reader/writer/base modules at
        # module load; patch every namespace that resolves it so the snapshot,
        # reads, and writes all hit the mock handler (real mutagen would reject
        # the zero-byte fixture files).
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler
        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            return_value=120,
        ):
            with (
                patch(
                    "audio_suite_shared.tag_helper_base.TagHandlerFactory",
                    shared_factory,
                ),
                patch(
                    "audio_suite_shared.tag_helper_reader.TagHandlerFactory",
                    shared_factory,
                ),
                patch(
                    "audio_suite_shared.tag_helper_writer.TagHandlerFactory",
                    shared_factory,
                ),
            ):
                with active_batch("bpm_analyzer", "tag_edit", db_path=undo_db):
                    run_analysis(
                        dir_path=str(tmp_path),
                        is_dry_run=False,
                        min_bpm=60,
                        max_bpm=200,
                        analysis_duration=30,
                        slot_vars=slot_vars,
                        slot_queue=MagicMock(),
                        on_progress=on_progress,
                        on_complete=on_complete,
                        on_error=on_error,
                    )

        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "bpm_analyzer"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_dry_run_creates_no_batch_records(self, tmp_path: Path) -> None:
        """A dry run performs no writes, so the batch is pruned on exit."""
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "track1.mp3").write_bytes(b"")

        with patch(
            "bpm_analyzer.core.file_processor.detect_bpm",
            return_value=120,
        ):
            with active_batch("bpm_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    is_dry_run=True,
                    min_bpm=60,
                    max_bpm=200,
                    analysis_duration=30,
                    slot_vars=[MagicMock() for _ in range(4)],
                    slot_queue=MagicMock(),
                    on_progress=MagicMock(),
                    on_complete=MagicMock(),
                    on_error=MagicMock(),
                )

        assert list_recent_batches(limit=10, db_path=undo_db) == []


class TestWorkersAboveTheSlotGrid:
    """A typed count above the grid must still finish every file (D66).

    Regression: the thread path sized its slot queue from the requested count
    while the display grid stayed fixed, so the surplus files wrote
    ``slot_vars[slot_idx]`` past the end and were reported as errors.
    """

    def test_run_analysis_caps_a_typed_count_at_the_grid(self, tmp_path: Path):
        from bpm_analyzer.core import file_processor as core

        for i in range(6):
            (tmp_path / f"track{i}.mp3").write_bytes(b"")

        handler = MagicMock()
        handler.get_raw_tags.return_value = {}
        handler.read_bpm.return_value = 120
        factory = MagicMock()
        factory.get_handler.return_value = handler
        summary: dict[str, object] = {}

        with (
            patch.object(core, "detect_bpm", return_value=120),
            patch("audio_suite_shared.tag_helper_base.TagHandlerFactory", factory),
            patch("audio_suite_shared.tag_helper_reader.TagHandlerFactory", factory),
            patch("audio_suite_shared.tag_helper_writer.TagHandlerFactory", factory),
        ):
            core.run_analysis(
                dir_path=str(tmp_path),
                is_dry_run=True,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_vars=[MagicMock(), MagicMock()],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=lambda **kw: summary.update(kw),
                on_error=MagicMock(),
                max_workers=12,
            )

        assert summary["total"] == 6
        assert summary["processed"] == 6
        assert summary["errors"] == 0


# ---------------------------------------------------------------------------
# 6. ProcessingStatus enum completeness
# ---------------------------------------------------------------------------


class TestSkippedRecordsThroughRunAnalysis:
    """Outcome-level: the thread run hands structured skips to on_complete."""

    def test_a_real_noise_file_is_reported_with_its_score(self, tmp_path: Path):
        _write_noise_wav(tmp_path / "noise.wav", seconds=8.0)
        _write_click_wav(tmp_path / "beat.wav", bpm=120.0, seconds=8.0)
        summary: dict[str, object] = {}

        run_analysis(
            dir_path=str(tmp_path),
            is_dry_run=True,
            min_bpm=60,
            max_bpm=200,
            analysis_duration=10,
            slot_vars=[MagicMock()],
            slot_queue=MagicMock(),
            on_progress=MagicMock(),
            on_complete=lambda **kw: summary.update(kw),
            on_error=MagicMock(),
        )

        assert summary["processed"] == 2
        assert summary["skipped"] == 1
        assert summary["errors"] == 0
        records = summary["skipped_files"]
        assert isinstance(records, list)
        assert len(records) == 1
        record = records[0]
        assert isinstance(record, dict)
        assert record["filename"] == "noise.wav"
        assert "No tempo detected" in str(record["reason"])
        score = record["onset_periodicity"]
        assert isinstance(score, float)
        assert 0.0 <= score < MIN_ONSET_PERIODICITY

    def test_a_clean_run_reports_an_empty_list(self, tmp_path: Path):
        """The key is always present, so scripts do not special-case its absence."""
        _write_click_wav(tmp_path / "beat.wav", bpm=120.0, seconds=8.0)
        summary: dict[str, object] = {}

        run_analysis(
            dir_path=str(tmp_path),
            is_dry_run=True,
            min_bpm=60,
            max_bpm=200,
            analysis_duration=10,
            slot_vars=[MagicMock()],
            slot_queue=MagicMock(),
            on_progress=MagicMock(),
            on_complete=lambda **kw: summary.update(kw),
            on_error=MagicMock(),
        )

        assert summary["skipped"] == 0
        assert summary["skipped_files"] == []
        assert summary["error_files"] == []

    def test_a_corrupt_file_is_reported_separately(self, tmp_path: Path):
        """A failed decode belongs in error_files, never in skipped_files."""
        (tmp_path / "corrupt.mp3").write_bytes(b"not audio")
        summary: dict[str, object] = {}

        run_analysis(
            dir_path=str(tmp_path),
            is_dry_run=True,
            min_bpm=60,
            max_bpm=200,
            analysis_duration=8,
            slot_vars=[MagicMock()],
            slot_queue=MagicMock(),
            on_progress=MagicMock(),
            on_complete=lambda **kw: summary.update(kw),
            on_error=MagicMock(),
        )

        assert summary["processed"] == 1
        assert summary["errors"] == 1
        assert summary["skipped"] == 0
        assert summary["skipped_files"] == []
        records = summary["error_files"]
        assert isinstance(records, list)
        assert len(records) == 1
        record = records[0]
        assert isinstance(record, dict)
        assert record["filename"] == "corrupt.mp3"
        assert record["reason"]
        assert record["error_type"] == "BPMDetectionError"


class TestProcessingStatusEnum:
    def test_all_expected_members_present(self):
        expected = {"DRY_RUN", "TAGGED", "SKIPPED", "ERROR"}
        actual = {m.name for m in ProcessingStatus}
        assert expected == actual

    def test_name_replace_produces_readable_label(self):
        assert ProcessingStatus.DRY_RUN.name.replace("_", " ") == "DRY RUN"
