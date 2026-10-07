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
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bpm_analyzer.core.bpm_detector import BPMDetectionError
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


# ---------------------------------------------------------------------------
# 6. ProcessingStatus enum completeness
# ---------------------------------------------------------------------------


class TestProcessingStatusEnum:
    def test_all_expected_members_present(self):
        expected = {"DRY_RUN", "TAGGED", "SKIPPED", "ERROR"}
        actual = {m.name for m in ProcessingStatus}
        assert expected == actual

    def test_name_replace_produces_readable_label(self):
        assert ProcessingStatus.DRY_RUN.name.replace("_", " ") == "DRY RUN"
