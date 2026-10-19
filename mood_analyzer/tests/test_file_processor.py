"""
tests/test_file_processor.py
Tests for mood_analyzer.core.file_processor.process_single_file and
run_analysis orchestration.

Changed in 1.4.0: the mocked processor carries a real `max_workers` so the
slot-grid cap has a number to compare (D66).
"""

import queue
import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audio_suite_shared.exceptions import AudioCodecError
from mood_analyzer.core.file_processor import process_single_file
from mood_analyzer.core.signal_mood_engine import MoodAnalysis

MODULE = "mood_analyzer.core.file_processor"

_SR = 22050
_TEST_ANALYSIS = MoodAnalysis(
    valence=0.7,
    arousal=0.7,
    mood_words=("Energetic", "Bright", "Confident"),
    confidence=0.87,
    energy=5,
)


def _make_call_args(
    name: str = "track.mp3",
    dir_path: str = "/music",
    is_dry_run: bool = True,
    analysis_duration: int = 90,
):
    """Build the boilerplate args process_single_file needs."""
    from mood_analyzer.core.file_processor import MoodAnalyzerProcessor

    slot_vars = [MagicMock()]
    lock = threading.Lock()
    on_progress = MagicMock()
    return {
        "processor": MoodAnalyzerProcessor(),
        "name": name,
        "dir_path": dir_path,
        "is_dry_run": is_dry_run,
        "analysis_duration": analysis_duration,
        "slot_vars": slot_vars,
        "slot_idx": 0,
        "lock": lock,
        "on_progress": on_progress,
    }


def _fake_signal() -> np.ndarray:
    rng = np.random.default_rng(3)
    return 0.1 * rng.standard_normal(_SR).astype(np.float64)


class TestProcessSingleFileBranches:
    def test_dry_run_detects_without_writing(self) -> None:
        fake = _fake_signal()
        args = _make_call_args(is_dry_run=True)
        with (
            patch(f"{MODULE}.load_analysis_audio", return_value=(fake, _SR)),
            patch(f"{MODULE}.analyze_mood", return_value=_TEST_ANALYSIS),
            patch(f"{MODULE}.write_mood") as mock_write,
            patch(f"{MODULE}.write_mood_confidence") as mock_write_conf,
            patch(f"{MODULE}.write_energy") as mock_write_energy,
        ):
            process_single_file(**args)
        mock_write.assert_not_called()
        mock_write_conf.assert_not_called()
        mock_write_energy.assert_not_called()
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_skipped"] == 0
        assert call_kwargs["n_errors"] == 0
        assert "[DETECTED]" in call_kwargs["display_text"]
        assert "Energetic;Bright;Confident" in call_kwargs["display_text"]

    def test_live_mode_writes_mood_and_confidence(self) -> None:
        fake = _fake_signal()
        args = _make_call_args(is_dry_run=False)
        with (
            patch(f"{MODULE}.load_analysis_audio", return_value=(fake, _SR)),
            patch(f"{MODULE}.analyze_mood", return_value=_TEST_ANALYSIS),
            patch(f"{MODULE}.write_mood") as mock_write,
            patch(f"{MODULE}.write_mood_confidence") as mock_write_conf,
            patch(f"{MODULE}.write_energy") as mock_write_energy,
        ):
            process_single_file(**args)
        import os as _os

        mock_write.assert_called_once_with(
            _os.path.join("/music", "track.mp3"), "Energetic;Bright;Confident"
        )
        mock_write_conf.assert_called_once_with(
            _os.path.join("/music", "track.mp3"), "0.87"
        )
        mock_write_energy.assert_called_once_with(
            _os.path.join("/music", "track.mp3"), "5"
        )
        call_kwargs = args["on_progress"].call_args[1]
        assert "[TAGGED]" in call_kwargs["display_text"]

    def test_undecodable_file_reported_as_skip(self) -> None:
        args = _make_call_args()
        with (
            patch(
                f"{MODULE}.load_analysis_audio",
                side_effect=AudioCodecError("cannot decode"),
            ),
            patch(f"{MODULE}.analyze_mood") as mock_analyze,
        ):
            process_single_file(**args)
        mock_analyze.assert_not_called()
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_skipped"] == 1
        assert "[SKIP]" in call_kwargs["display_text"]

    def test_recovery_skip_reports_skipped(self) -> None:
        from audio_suite_shared.error_recovery import RecoveryAction

        args = _make_call_args()
        args["processor"] = MagicMock()
        args["processor"].run_with_retry.side_effect = ValueError("corrupt file")
        with patch(f"{MODULE}.get_recovery_action", return_value=RecoveryAction.SKIP):
            process_single_file(**args)
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_skipped"] == 1
        assert "[SKIP]" in call_kwargs["display_text"]

    def test_recovery_abort_reports_error(self) -> None:
        from audio_suite_shared.error_recovery import RecoveryAction

        args = _make_call_args()
        args["processor"] = MagicMock()
        args["processor"].run_with_retry.side_effect = PermissionError("locked")
        with patch(f"{MODULE}.get_recovery_action", return_value=RecoveryAction.ABORT):
            process_single_file(**args)
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_errors"] == 1
        assert "[ERROR]" in call_kwargs["display_text"]


class TestAnalyzeMoodCpu:
    def test_returns_ok_on_success(self) -> None:
        from mood_analyzer.core.file_processor import _analyze_mood_cpu

        fake = _fake_signal()
        with (
            patch(f"{MODULE}.load_analysis_audio", return_value=(fake, _SR)),
            patch(f"{MODULE}.analyze_mood", return_value=_TEST_ANALYSIS),
        ):
            result = _analyze_mood_cpu(
                file_path="/music/track.mp3",
                analysis_duration=30,
            )
        assert result["status"] == "ok"
        assert result["mood"] == "Energetic;Bright;Confident"
        assert result["confidence"] == pytest.approx(0.87)
        assert result["energy"] == 5

    def test_returns_error_on_exception(self) -> None:
        from mood_analyzer.core.file_processor import _analyze_mood_cpu

        with (
            patch(
                f"{MODULE}.load_analysis_audio",
                side_effect=ValueError("corrupt"),
            ),
        ):
            result = _analyze_mood_cpu(
                file_path="/music/bad.mp3",
                analysis_duration=30,
            )
        assert result["status"] == "error"


class TestHandleMoodResult:
    def test_ok_live_writes_mood_and_confidence(self) -> None:
        import os as _os

        from mood_analyzer.core.file_processor import _handle_mood_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        with (
            patch(f"{MODULE}.write_mood") as mock_write,
            patch(f"{MODULE}.write_mood_confidence") as mock_write_conf,
            patch(f"{MODULE}.write_energy") as mock_write_energy,
        ):
            _handle_mood_result(
                filename="track.mp3",
                dir_path="/music",
                result={
                    "status": "ok",
                    "mood": "Energetic;Bright;Confident",
                    "confidence": 0.87,
                    "energy": 5,
                },
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                is_dry_run=False,
                slot_vars=slot_vars,
            )

        mock_write.assert_called_once_with(
            _os.path.join("/music", "track.mp3"), "Energetic;Bright;Confident"
        )
        mock_write_conf.assert_called_once_with(
            _os.path.join("/music", "track.mp3"), "0.87"
        )
        mock_write_energy.assert_called_once_with(
            _os.path.join("/music", "track.mp3"), "5"
        )

    def test_ok_dry_run_skips_writes(self) -> None:
        from mood_analyzer.core.file_processor import _handle_mood_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        with (
            patch(f"{MODULE}.write_mood") as mock_write,
            patch(f"{MODULE}.write_mood_confidence") as mock_write_conf,
            patch(f"{MODULE}.write_energy") as mock_write_energy,
        ):
            _handle_mood_result(
                filename="track.mp3",
                dir_path="/music",
                result={
                    "status": "ok",
                    "mood": "Energetic;Bright;Confident",
                    "confidence": 0.87,
                    "energy": 5,
                },
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                is_dry_run=True,
                slot_vars=slot_vars,
            )

        mock_write.assert_not_called()
        mock_write_conf.assert_not_called()
        mock_write_energy.assert_not_called()
        on_progress.assert_called_once()
        call_kwargs = on_progress.call_args[1]
        assert call_kwargs["n_errors"] == 0
        assert "[DETECTED]" in call_kwargs["display_text"]

    def test_error_reported(self) -> None:
        from mood_analyzer.core.file_processor import _handle_mood_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        _handle_mood_result(
            filename="bad.mp3",
            dir_path="/music",
            result={"status": "error", "error": "failed"},
            slot_idx=0,
            lock=lock,
            on_progress=on_progress,
            is_dry_run=True,
            slot_vars=slot_vars,
        )

        on_progress.assert_called_once()
        call_kwargs = on_progress.call_args[1]
        assert call_kwargs["n_errors"] == 1
        assert "[ERROR]" in call_kwargs["display_text"]


class TestRunAnalysisParallelMode:
    """run_analysis with parallel_mode=True routes to run_cpu_bound_processing."""

    def _run(self, **overrides):
        from mood_analyzer.core.file_processor import run_analysis

        defaults = {
            "dir_path": "/music",
            "is_dry_run": True,
            "analysis_duration": 30,
            "slot_vars": [],
            "slot_queue": MagicMock(),
            "on_progress": MagicMock(),
            "on_complete": MagicMock(),
            "on_error": MagicMock(),
        }
        defaults.update(overrides)
        return run_analysis(**defaults)

    def test_parallel_mode_routes_to_cpu_bound_processing(self) -> None:
        mock_processor = MagicMock()
        with patch(f"{MODULE}.MoodAnalyzerProcessor", return_value=mock_processor):
            self._run(parallel_mode=True)
        mock_processor.run_cpu_bound_processing.assert_called_once()

    def test_parallel_mode_with_custom_workers(self) -> None:
        mock_processor = MagicMock()
        with patch(f"{MODULE}.MoodAnalyzerProcessor", return_value=mock_processor):
            self._run(parallel_mode=True, max_workers=8)
        call_kwargs = mock_processor.run_cpu_bound_processing.call_args.kwargs
        assert call_kwargs["max_workers"] == 8

    def test_parallel_mode_skips_legacy_path(self) -> None:
        mock_processor = MagicMock()
        with patch(f"{MODULE}.MoodAnalyzerProcessor", return_value=mock_processor):
            self._run(parallel_mode=True)
        mock_processor.run_cpu_bound_processing.assert_called_once()
        mock_processor.discover_audio_files.assert_not_called()
        mock_processor.process_batch.assert_not_called()


class TestRunAnalysisNonParallel:
    def test_scan_failure_calls_on_error(self) -> None:
        from mood_analyzer.core.file_processor import run_analysis

        mock_processor = MagicMock()
        mock_processor.discover_audio_files.side_effect = OSError("scan failed")
        on_error = MagicMock()
        with patch(f"{MODULE}.MoodAnalyzerProcessor", return_value=mock_processor):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                analysis_duration=30,
                slot_vars=[MagicMock()],
                slot_queue=queue.Queue(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=on_error,
            )
        on_error.assert_called_once()

    def test_no_files_calls_on_error(self) -> None:
        from mood_analyzer.core.file_processor import run_analysis

        mock_processor = MagicMock()
        mock_processor.discover_audio_files.return_value = []
        on_error = MagicMock()
        with patch(f"{MODULE}.MoodAnalyzerProcessor", return_value=mock_processor):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                analysis_duration=30,
                slot_vars=[MagicMock()],
                slot_queue=queue.Queue(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=on_error,
            )
        on_error.assert_called_once_with(
            "No supported audio files found in the selected directory."
        )

    def test_happy_path_calls_on_complete(self) -> None:
        from mood_analyzer.core.file_processor import run_analysis

        mock_processor = MagicMock()
        mock_processor.max_workers = 2
        mock_processor.discover_audio_files.return_value = ["a.mp3", "b.mp3"]
        mock_processor.create_progress_tracker.return_value = (
            [0],
            [0],
            [0],
            [],
            MagicMock(),
        )

        slot_queue = queue.Queue()
        slot_queue.put(0)
        slot_queue.put(1)
        mock_processor.process_batch.side_effect = lambda files, worker, max_workers: [
            worker(f) for f in files
        ]

        on_complete = MagicMock()
        with patch(f"{MODULE}.MoodAnalyzerProcessor", return_value=mock_processor):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                analysis_duration=30,
                slot_vars=[MagicMock(), MagicMock()],
                slot_queue=slot_queue,
                on_progress=MagicMock(),
                on_complete=on_complete,
                on_error=MagicMock(),
            )
        on_complete.assert_called_once()
        assert on_complete.call_args[1]["total"] == 2


# ── Behaviour locks (iteration-7 B5) ─────────────────────────────────────────
# The workflow extraction below must not move these outcomes: the undo batch
# wiring, the dry-run no-write contract, and the tag bytes a live run leaves
# behind (read back through the real tag reader, never by re-reading state the
# writer just set).

import hashlib  # noqa: E402

_MP3_BYTES = b""  # a zero-byte container the mocked decode path handles


class TestUndoBatchRecording:
    """Worker threads must join the orchestrator's active undo batch so tag
    snapshots are recorded against it (batch_undo.use_batch)."""

    def _run(self, tmp_path, is_dry_run):
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches
        from mood_analyzer.core.file_processor import run_analysis

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(_MP3_BYTES)
        (tmp_path / "b.mp3").write_bytes(_MP3_BYTES)
        slot_vars = [MagicMock() for _ in range(4)]
        slot_queue = queue.Queue()
        for i in range(4):
            slot_queue.put(i)

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TXXX:MOOD": "Energetic"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        with (
            patch(f"{MODULE}._analyse_file", return_value=_TEST_ANALYSIS),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_reader.TagHandlerFactory", shared_factory
            ),
            patch(
                "audio_suite_shared.tag_helper_writer.TagHandlerFactory", shared_factory
            ),
        ):
            with active_batch("mood_analyzer", "tag_edit", db_path=undo_db):
                run_analysis(
                    dir_path=str(tmp_path),
                    is_dry_run=is_dry_run,
                    analysis_duration=30,
                    slot_vars=slot_vars,
                    slot_queue=slot_queue,
                    on_progress=MagicMock(),
                    on_complete=MagicMock(),
                    on_error=MagicMock(),
                )

        return list_recent_batches(limit=10, db_path=undo_db)

    def test_thread_mode_records_snapshots_from_workers(self, tmp_path):
        batches = self._run(tmp_path, is_dry_run=False)
        assert len(batches) == 1
        assert batches[0].tool_name == "mood_analyzer"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_dry_run_prunes_empty_batch(self, tmp_path):
        assert self._run(tmp_path, is_dry_run=True) == []


def _make_real_wav(path, seconds: float = 1.0):
    """Write a real mono 16-bit WAV so the real tag reader/writer can work."""
    from pydub import AudioSegment

    n = int(_SR * seconds)
    t = np.arange(n) / _SR
    pcm = (0.4 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
    segment = AudioSegment(pcm.tobytes(), frame_rate=_SR, sample_width=2, channels=1)
    segment.export(str(path), format="wav")
    return path


class TestRealFileOutcome:
    """Outcome-level locks: the bytes a live/dry run leaves on disk, decoded
    and read back through the real tag reader."""

    def test_live_run_writes_mood_and_energy_readable_back(self, tmp_path):
        from audio_suite_shared.tag_helper import read_energy, read_mood

        path = _make_real_wav(tmp_path / "mood.wav")
        args = _make_call_args(
            name="mood.wav",
            dir_path=str(tmp_path),
            is_dry_run=False,
        )
        with patch(f"{MODULE}._analyse_file", return_value=_TEST_ANALYSIS):
            process_single_file(**args)

        assert read_mood(str(path)) == _TEST_ANALYSIS.to_tag_string()
        assert read_energy(str(path)) == str(_TEST_ANALYSIS.energy)
        assert "[TAGGED]" in args["on_progress"].call_args[1]["display_text"]

    def test_dry_run_writes_nothing_and_keeps_file_bytes(self, tmp_path):
        from audio_suite_shared.tag_helper import read_mood

        path = _make_real_wav(tmp_path / "mood_dry.wav")
        original = path.read_bytes()

        args = _make_call_args(
            name="mood_dry.wav",
            dir_path=str(tmp_path),
            is_dry_run=True,
        )
        with patch(f"{MODULE}._analyse_file", return_value=_TEST_ANALYSIS):
            process_single_file(**args)

        assert read_mood(str(path)) is None
        assert path.read_bytes() == original

    def test_undo_restores_the_original_tag_bytes(self, tmp_path):
        """The byte-level undo contract (iteration-6 B2): a live run that
        tags a real file, reverted, returns the file to byte-identical
        original content."""
        from audio_suite_shared.batch_undo import (
            active_batch,
            list_recent_batches,
            revert_batch_by_id,
        )
        from audio_suite_shared.tag_helper import read_mood

        original_sha = hashlib.sha256()

        path = _make_real_wav(tmp_path / "mood_undo.wav")
        original = path.read_bytes()
        original_sha.update(original)

        undo_db = tmp_path / "undo_log.db"
        args = _make_call_args(
            name="mood_undo.wav",
            dir_path=str(tmp_path),
            is_dry_run=False,
        )
        with (
            patch(f"{MODULE}._analyse_file", return_value=_TEST_ANALYSIS),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            with active_batch("mood_analyzer", "tag_edit", db_path=undo_db):
                process_single_file(**args)

        assert read_mood(str(path)) == _TEST_ANALYSIS.to_tag_string()

        batches = list_recent_batches(limit=5, db_path=undo_db)
        assert len(batches) == 1
        result = revert_batch_by_id(batches[0].batch_id, db_path=undo_db)
        assert result.reverted >= 1
        assert path.read_bytes() == original
        final_sha = hashlib.sha256()
        final_sha.update(path.read_bytes())
        assert final_sha.hexdigest() == original_sha.hexdigest()
