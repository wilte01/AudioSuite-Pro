"""
tests/test_file_processor.py
Regression tests for key_detector.core.file_processor.process_single_file.

Covers:
  - Sample-rate bug regression: the sr passed to detect_key() must be the
    rate librosa.load() actually resampled to, never the file's native
    on-disk rate. (Bug: code previously called librosa.get_samplerate()
    separately, which returns the native rate -- not the rate of the
    array that librosa.load() produced -- silently corrupting chroma_cqt's
    frequency-bin mapping for any file not natively at 22050 Hz.)

Changed in 1.1.0: retargeted the librosa patch points to the shared helper.
Changed in 1.4.0: the mocked processor carries a real `max_workers` so the
slot-grid cap has a number to compare (D66).
Changed in 1.4.0: mocked decodes are one second long so they satisfy the
shared 0.5 s minimum-duration guard; a dedicated regression asserts a shorter
signal is reported as an error instead of being tagged.
"""

import threading
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from key_detector.core.file_processor import process_single_file

MODULE = "key_detector.core.file_processor"


def _make_call_args(
    name: str = "track.mp3",
    dir_path: str = "/music",
    is_dry_run: bool = True,
    analysis_duration: int = 90,
):
    """Build the boilerplate args process_single_file needs."""
    from key_detector.core.file_processor import KeyDetectorProcessor

    slot_vars = [MagicMock()]
    lock = threading.Lock()
    on_progress = MagicMock()
    return {
        "processor": KeyDetectorProcessor(),
        "name": name,
        "dir_path": dir_path,
        "is_dry_run": is_dry_run,
        "analysis_duration": analysis_duration,
        "slot_vars": slot_vars,
        "slot_idx": 0,
        "lock": lock,
        "on_progress": on_progress,
    }


def _audible(sr: int = 22050, seconds: float = 1.0) -> np.ndarray:
    """A 440 Hz tone that passes the shared duration and silence guards.

    Mocked decodes must be audible: an all-zero array is rejected as
    effectively silent, so using one would exercise the failure path in tests
    that mean to exercise the normal one.
    """
    t = np.arange(int(sr * seconds)) / sr
    return (0.4 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


class TestSampleRatePassedToDetectKey:
    """detect_key must receive the sr that librosa.load() actually returned."""

    @pytest.mark.parametrize(
        "native_sr,loaded_sr", [(44100, 22050), (48000, 22050), (96000, 22050)]
    )
    def test_detect_key_receives_loaded_sr_not_native_sr(
        self, native_sr: int, loaded_sr: int
    ) -> None:
        """
        Simulate a file whose native on-disk rate differs from the rate
        librosa.load() resamples to (librosa.load defaults to sr=22050).
        detect_key must be called with the LOADED rate, never the native one.
        """
        fake_audio = _audible()
        args = _make_call_args()

        with (
            patch(f"{MODULE}.read_key", return_value=None),
            patch(f"{MODULE}.write_key"),
            patch("librosa.load", return_value=(fake_audio, loaded_sr)) as mock_load,
            patch("librosa.get_samplerate", return_value=native_sr),
            patch(f"{MODULE}.detect_key", return_value="C") as mock_detect_key,
        ):
            process_single_file(**args)

            assert mock_load.called, "librosa.load was never called"
            assert mock_detect_key.called, "detect_key was never called"

            called_y, called_sr = mock_detect_key.call_args[0]
            assert called_sr == loaded_sr, (
                f"detect_key was called with sr={called_sr}, but librosa.load() "
                f"actually resampled to {loaded_sr}. Native file rate was "
                f"{native_sr}. If this assertion fails with called_sr == "
                f"{native_sr}, the sample-rate mismatch bug has regressed: "
                f"the native on-disk rate was used instead of the array's "
                f"actual rate, corrupting chroma_cqt's frequency mapping."
            )
            # Confirm the bug's old behavior (native sr) is NOT what happened,
            # whenever native and loaded rates actually differ.
            if native_sr != loaded_sr:
                assert called_sr != native_sr

    def test_detect_key_receives_native_sr_when_already_matching(self) -> None:
        """
        Sanity check: when the file IS already natively at the loaded rate
        (e.g. a 22050 Hz source file), native_sr == loaded_sr, so this case
        can't distinguish correct from buggy behavior on its own -- covered
        by the mismatch cases above. This just confirms no crash in that path.
        """
        fake_audio = _audible()
        args = _make_call_args()

        with (
            patch(f"{MODULE}.read_key", return_value=None),
            patch(f"{MODULE}.write_key"),
            patch("librosa.load", return_value=(fake_audio, 22050)),
            patch("librosa.get_samplerate", return_value=22050),
            patch(f"{MODULE}.detect_key", return_value="C") as mock_detect_key,
        ):
            process_single_file(**args)

            called_y, called_sr = mock_detect_key.call_args[0]
            assert called_sr == 22050

    def test_get_samplerate_no_longer_called(self) -> None:
        """
        librosa.get_samplerate() queries the file's native rate, which is
        the wrong value to pass to detect_key(). After the fix, the
        production code path must not call it at all.
        """
        fake_audio = _audible()
        args = _make_call_args()

        with (
            patch(f"{MODULE}.read_key", return_value=None),
            patch(f"{MODULE}.write_key"),
            patch("librosa.load", return_value=(fake_audio, 22050)),
            patch("librosa.get_samplerate") as mock_native_sr,
            patch(f"{MODULE}.detect_key", return_value="C") as mock_detect_key,
        ):
            process_single_file(**args)

            mock_native_sr.assert_not_called()
            mock_detect_key.assert_called_once()


class TestRunAnalysisParallelMode:
    """Test that run_analysis with parallel_mode=True routes to
    run_cpu_bound_processing."""

    def test_parallel_mode_routes_to_cpu_bound_processing(self):
        from key_detector.core.file_processor import run_analysis

        mock_processor = MagicMock()
        with patch(
            f"{MODULE}.KeyDetectorProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                analysis_duration=30,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
                parallel_mode=True,
            )

        mock_processor.run_cpu_bound_processing.assert_called_once()

    def test_parallel_mode_with_custom_workers(self):
        from key_detector.core.file_processor import run_analysis

        mock_processor = MagicMock()
        with patch(
            f"{MODULE}.KeyDetectorProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
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

    def test_parallel_mode_skips_legacy_path(self):
        from key_detector.core.file_processor import run_analysis

        mock_processor = MagicMock()
        with patch(
            f"{MODULE}.KeyDetectorProcessor",
            return_value=mock_processor,
        ):
            run_analysis(
                dir_path="/music",
                is_dry_run=True,
                analysis_duration=30,
                slot_vars=[],
                slot_queue=MagicMock(),
                on_progress=MagicMock(),
                on_complete=MagicMock(),
                on_error=MagicMock(),
                parallel_mode=True,
            )

        mock_processor.run_cpu_bound_processing.assert_called_once()
        mock_processor.discover_audio_files.assert_not_called()
        mock_processor.process_batch.assert_not_called()


class TestDetectKeyCpu:
    def test_returns_ok_on_success(self):
        from key_detector.core.file_processor import _detect_key_cpu

        fake_audio = _audible()
        with (
            patch("librosa.load", return_value=(fake_audio, 22050)),
            patch(f"{MODULE}.detect_key", return_value="C"),
        ):
            result = _detect_key_cpu(
                file_path="/music/track.mp3",
                analysis_duration=30,
            )
        assert result["status"] == "ok"
        assert result["key"] == "C"

    def test_returns_error_on_exception(self):
        from key_detector.core.file_processor import _detect_key_cpu

        with patch("librosa.load", side_effect=ValueError("corrupt")):
            result = _detect_key_cpu(
                file_path="/music/bad.mp3",
                analysis_duration=30,
            )
        assert result["status"] == "error"

    def test_short_decode_is_reported_not_analysed(self):
        """A 0.2 s decode must not reach detect_key and must say why.

        Regression: key detection decodes through the fallback helper
        directly, bypassing the shared loader's too-short guard, so a blip
        was chroma-analysed and its fabricated key written as a tag.
        """
        from key_detector.core.file_processor import _detect_key_cpu

        short = _audible(seconds=0.2)
        with (
            patch("librosa.load", return_value=(short, 22050)),
            patch(f"{MODULE}.detect_key") as mock_detect_key,
        ):
            result = _detect_key_cpu(
                file_path="/music/blip.mp3",
                analysis_duration=30,
            )

        assert result["status"] == "error"
        assert "too short" in str(result["error"]).lower()
        mock_detect_key.assert_not_called()

    def test_silent_decode_is_reported_not_analysed(self):
        """A one-second silent decode must not reach detect_key.

        Silence is long enough to satisfy the duration guard, and chroma
        correlation on a flat spectrum returns a confident-looking key, so the
        silence half of the shared guard is what stops the fabricated tag.
        """
        from key_detector.core.file_processor import _detect_key_cpu

        with (
            patch("librosa.load", return_value=(np.zeros(22050, np.float32), 22050)),
            patch(f"{MODULE}.detect_key") as mock_detect_key,
        ):
            result = _detect_key_cpu(
                file_path="/music/silence.mp3",
                analysis_duration=30,
            )

        assert result["status"] == "error"
        assert "silent" in str(result["error"]).lower()
        mock_detect_key.assert_not_called()

    def test_quiet_decode_is_still_analysed(self):
        """The guard rejects silence, not quiet music."""
        from key_detector.core.file_processor import _detect_key_cpu

        quiet = (_audible() * 0.02).astype(np.float32)
        with (
            patch("librosa.load", return_value=(quiet, 22050)),
            patch(f"{MODULE}.detect_key", return_value="C") as mock_detect_key,
        ):
            result = _detect_key_cpu(
                file_path="/music/quiet.mp3",
                analysis_duration=30,
            )

        assert result["status"] == "ok"
        mock_detect_key.assert_called_once()


class TestHandleKeyResult:
    def test_ok_dry_skip_existing_key(self):
        from key_detector.core.file_processor import _handle_key_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        with patch(f"{MODULE}.read_key", return_value="Am"):
            _handle_key_result(
                filename="track.mp3",
                dir_path="/music",
                result={"status": "ok", "key": "C"},
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                is_dry_run=True,
                slot_vars=slot_vars,
            )

        on_progress.assert_called_once()
        call_kwargs = on_progress.call_args[1]
        assert call_kwargs["n_skipped"] == 1
        assert "SKIP" in call_kwargs["display_text"]

    def test_ok_live_writes_tag(self):
        import os as _os

        from key_detector.core.file_processor import _handle_key_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        with (
            patch(f"{MODULE}.read_key", return_value=None),
            patch(f"{MODULE}.write_key") as mock_write,
        ):
            _handle_key_result(
                filename="track.mp3",
                dir_path="/music",
                result={"status": "ok", "key": "C"},
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                is_dry_run=False,
                slot_vars=slot_vars,
            )

        mock_write.assert_called_once_with(_os.path.join("/music", "track.mp3"), "C")

    def test_error_reported(self):
        from key_detector.core.file_processor import _handle_key_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        _handle_key_result(
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

    def test_was_previous_displayed_for_changed_key(self):
        """When the existing tag differs from the detected key, the display
        must note '(was X)' and the log 'Previous: X'."""
        from key_detector.core.file_processor import _handle_key_result

        lock = threading.Lock()
        on_progress = MagicMock()
        slot_vars = [MagicMock()]

        with (
            patch(f"{MODULE}.read_key", return_value="Am"),
            patch(f"{MODULE}.write_key"),
        ):
            _handle_key_result(
                filename="track.mp3",
                dir_path="/music",
                result={"status": "ok", "key": "C"},
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                is_dry_run=False,
                slot_vars=slot_vars,
            )

        call_kwargs = on_progress.call_args[1]
        assert "(was Am)" in call_kwargs["display_text"]
        assert "Previous: Am" in call_kwargs["log_text"]


class TestProcessSingleFileBranches:
    def test_dry_run_with_existing_key_skips(self):
        """In dry-run mode an already-tagged file must be skipped without
        loading the audio for analysis."""
        args = _make_call_args(is_dry_run=True)
        with (
            patch(f"{MODULE}.read_key", return_value="Am"),
            patch("librosa.load") as mock_load,
        ):
            process_single_file(**args)
        mock_load.assert_not_called()
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_skipped"] == 1
        assert "Already has key: Am" in call_kwargs["display_text"]

    def test_live_mode_writes_key(self):
        """In live mode the detected key must be written and reported as
        TAGGED."""
        fake_audio = _audible()
        args = _make_call_args(is_dry_run=False)
        with (
            patch(f"{MODULE}.read_key", return_value=None),
            patch("librosa.load", return_value=(fake_audio, 22050)),
            patch(f"{MODULE}.detect_key", return_value="C"),
            patch(f"{MODULE}.write_key") as mock_write,
        ):
            process_single_file(**args)
        assert mock_write.called
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_skipped"] == 0
        assert "[TAGGED]" in call_kwargs["display_text"]

    def test_live_mode_changed_key_shows_previous(self):
        """In live mode a changed key must produce '(was X)' in the display
        and 'Previous: X' in the log."""
        fake_audio = _audible()
        args = _make_call_args(is_dry_run=False)
        with (
            patch(f"{MODULE}.read_key", return_value="Am"),
            patch("librosa.load", return_value=(fake_audio, 22050)),
            patch(f"{MODULE}.detect_key", return_value="C"),
            patch(f"{MODULE}.write_key"),
        ):
            process_single_file(**args)
        call_kwargs = args["on_progress"].call_args[1]
        assert "(was Am)" in call_kwargs["display_text"]
        assert "Previous: Am" in call_kwargs["log_text"]

    def test_recovery_skip_reports_skipped(self):
        """A non-retryable error (ValueError) that resolves to
        RecoveryAction.SKIP must be reported as a skip, not an error."""
        from audio_suite_shared.error_recovery import RecoveryAction

        args = _make_call_args()
        args["processor"] = MagicMock()
        args["processor"].run_with_retry.side_effect = ValueError("corrupt file")
        with patch(f"{MODULE}.get_recovery_action", return_value=RecoveryAction.SKIP):
            process_single_file(**args)
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_skipped"] == 1
        assert "[SKIP]" in call_kwargs["display_text"]

    def test_recovery_abort_reports_error(self):
        """A non-retryable error that resolves to a non-SKIP action must be
        reported as an error."""
        from audio_suite_shared.error_recovery import RecoveryAction

        args = _make_call_args()
        args["processor"] = MagicMock()
        args["processor"].run_with_retry.side_effect = ValueError("corrupt file")
        with patch(f"{MODULE}.get_recovery_action", return_value=RecoveryAction.ABORT):
            process_single_file(**args)
        call_kwargs = args["on_progress"].call_args[1]
        assert call_kwargs["n_errors"] == 1
        assert "[ERROR]" in call_kwargs["display_text"]


class TestRunAnalysisNonParallel:
    def test_scan_failure_calls_on_error(self):
        import queue

        from key_detector.core.file_processor import run_analysis

        mock_processor = MagicMock()
        mock_processor.discover_audio_files.side_effect = OSError("scan failed")
        on_error = MagicMock()
        with patch(f"{MODULE}.KeyDetectorProcessor", return_value=mock_processor):
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

    def test_no_files_calls_on_error(self):
        import queue

        from key_detector.core.file_processor import run_analysis

        mock_processor = MagicMock()
        mock_processor.discover_audio_files.return_value = []
        on_error = MagicMock()
        with patch(f"{MODULE}.KeyDetectorProcessor", return_value=mock_processor):
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

    def test_happy_path_calls_on_complete(self):
        import queue

        from key_detector.core.file_processor import run_analysis

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
        with patch(f"{MODULE}.KeyDetectorProcessor", return_value=mock_processor):
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


class TestUndoBatchRecording:
    """Phase 2: worker threads must join the orchestrator's active undo
    batch so tag snapshots are recorded against it (batch_undo.use_batch)."""

    def _run(self, tmp_path, is_dry_run):
        from queue import Queue

        from audio_suite_shared.batch_undo import active_batch, list_recent_batches
        from key_detector.core.file_processor import run_analysis

        undo_db = tmp_path / "undo_log.db"
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "b.mp3").write_bytes(b"")
        slot_vars = [MagicMock() for _ in range(4)]
        slot_queue = Queue()
        for i in range(4):
            slot_queue.put(i)

        fake_audio = _audible()
        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TKEY": "C"}
        handler.read_key.return_value = None
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        with (
            patch(f"{MODULE}.detect_key", return_value="C"),
            patch("librosa.load", return_value=(fake_audio, 22050)),
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
            with active_batch("key_detector", "tag_edit", db_path=undo_db):
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
        assert batches[0].tool_name == "key_detector"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_dry_run_prunes_empty_batch(self, tmp_path):
        assert self._run(tmp_path, is_dry_run=True) == []


# ── Iteration-6 B3: the low-confidence KEY policy ──────────────────────────────
# The maintainer's decision is that UNKNOWN_KEY means "no vote", not a key: it
# is reported and never written. These tests use REAL files and the REAL tag
# reader, because a test that mocks `write_key` cannot tell a policy that
# refuses to write from one that writes the wrong value -- it would pass
# identically. Both tag paths are covered, since the serial and parallel
# processors are separate code with the same contract.

_SR = 22050


def _make_real_wav(path, seconds: float = 1.0, silent: bool = False):
    """Write a real mono 16-bit WAV so the real tag reader/writer can work.

    With ``silent=True`` the PCM is digital silence, which is long enough for
    the duration guard but must be refused by the silence guard.
    """
    import numpy as np
    from pydub import AudioSegment

    n = int(_SR * seconds)
    t = np.arange(n) / _SR
    signal = np.zeros(n) if silent else 0.4 * np.sin(2 * np.pi * 440.0 * t)
    pcm = (signal * 32767).astype(np.int16)
    segment = AudioSegment(pcm.tobytes(), frame_rate=_SR, sample_width=2, channels=1)
    segment.export(str(path), format="wav")
    return path


class TestUnknownKeyIsNeverTagged:
    """B3: UNKNOWN_KEY is detected and reported, but not written to a tag."""

    def test_serial_path_leaves_a_real_file_untagged(self, tmp_path):
        from audio_suite_shared.tag_helper import read_key

        path = _make_real_wav(tmp_path / "untuned.wav")
        assert read_key(str(path)) is None

        args = _make_call_args(
            name="untuned.wav", dir_path=str(tmp_path), is_dry_run=False
        )
        with patch(f"{MODULE}.detect_key", return_value="Unknown"):
            process_single_file(**args)

        # The real tag surface is unchanged -- no KEY="Unknown" written.
        assert read_key(str(path)) is None
        shown = args["on_progress"].call_args[1]["display_text"]
        assert "Unknown" in shown
        assert "not tagged" in shown
        assert "[TAGGED]" not in shown

    def test_serial_path_preserves_a_pre_existing_real_key(self, tmp_path):
        """A file that already has a KEY keeps it; the undecidable result must
        not overwrite a value the user (or a previous good run) supplied."""
        from audio_suite_shared.tag_helper import read_key, write_key

        path = _make_real_wav(tmp_path / "tagged.wav")
        write_key(str(path), "Am")
        assert read_key(str(path)) == "Am"

        args = _make_call_args(
            name="tagged.wav", dir_path=str(tmp_path), is_dry_run=False
        )
        with patch(f"{MODULE}.detect_key", return_value="Unknown"):
            process_single_file(**args)

        assert read_key(str(path)) == "Am"

    def test_parallel_path_leaves_a_real_file_untagged(self, tmp_path):
        """The parallel handler is separate code and must obey the same policy."""
        from audio_suite_shared.tag_helper import read_key
        from key_detector.core.file_processor import _handle_key_result

        path = _make_real_wav(tmp_path / "untuned2.wav")
        on_progress = MagicMock()

        _handle_key_result(
            filename="untuned2.wav",
            dir_path=str(tmp_path),
            result={"status": "ok", "key": "Unknown"},
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            is_dry_run=False,
            slot_vars=[MagicMock()],
        )

        assert read_key(str(path)) is None
        shown = on_progress.call_args[1]["display_text"]
        assert "not tagged" in shown
        assert "[TAGGED]" not in shown

    def test_a_defensible_key_is_still_written(self, tmp_path):
        """The control: the policy must not have become 'never tag'.

        Without this, a regression that made every run a no-op would satisfy
        every test above.
        """
        from audio_suite_shared.tag_helper import read_key

        path = _make_real_wav(tmp_path / "tuned.wav")

        args = _make_call_args(
            name="tuned.wav", dir_path=str(tmp_path), is_dry_run=False
        )
        with patch(f"{MODULE}.detect_key", return_value="C"):
            process_single_file(**args)

        assert read_key(str(path)) == "C"
        assert "[TAGGED]" in args["on_progress"].call_args[1]["display_text"]

    def test_dry_run_reports_unknown_without_a_write_attempt(self, tmp_path):
        """Dry run never writes, and its status stays the plain DETECTED one."""
        from audio_suite_shared.tag_helper import read_key

        path = _make_real_wav(tmp_path / "dry.wav")
        args = _make_call_args(name="dry.wav", dir_path=str(tmp_path), is_dry_run=True)
        with patch(f"{MODULE}.detect_key", return_value="Unknown"):
            process_single_file(**args)

        assert read_key(str(path)) is None
        assert "[DETECTED]" in args["on_progress"].call_args[1]["display_text"]


class TestSilentFileIsNeverTagged:
    """A silent file gets an error line, no key tag, and unchanged bytes.

    Outcome-level: the real loader decodes a real silent WAV, and the real tag
    reader confirms nothing was written. A mocked `write_key` could not tell a
    refused write from a wrong one.
    """

    def test_serial_path_reports_silence_and_leaves_file_untagged(self, tmp_path):
        from audio_suite_shared.tag_helper import read_key

        path = _make_real_wav(tmp_path / "silence.wav", seconds=1.0, silent=True)
        original = path.read_bytes()
        args = _make_call_args(
            name="silence.wav", dir_path=str(tmp_path), is_dry_run=False
        )
        with patch(f"{MODULE}.detect_key") as mock_detect_key:
            process_single_file(**args)

        mock_detect_key.assert_not_called()
        assert read_key(str(path)) is None
        assert path.read_bytes() == original
        shown = args["on_progress"].call_args[1]["display_text"]
        assert "silent" in shown.lower()
        assert "[TAGGED]" not in shown


class TestRealFileUndoRoundTrip:
    """The byte-level undo contract (iteration-6 B2) extended to the key
    tool (mirror of iteration-7 B5's mood_analyzer lock): a live run that
    tags a real file, reverted via the real undo log, returns the file to
    byte-identical original content."""

    def test_undo_restores_the_original_tag_bytes(self, tmp_path):
        import hashlib

        from audio_suite_shared.batch_undo import (
            active_batch,
            list_recent_batches,
            revert_batch_by_id,
        )
        from audio_suite_shared.tag_helper import read_key

        path = _make_real_wav(tmp_path / "key_undo.wav")
        original = path.read_bytes()
        original_sha = hashlib.sha256()
        original_sha.update(original)

        undo_db = tmp_path / "undo_log.db"
        args = _make_call_args(
            name="key_undo.wav", dir_path=str(tmp_path), is_dry_run=False
        )
        with (
            patch(f"{MODULE}.detect_key", return_value="C"),
            patch(
                "librosa.load",
                return_value=(_audible(_SR), _SR),
            ),
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            with active_batch("key_detector", "tag_edit", db_path=undo_db):
                process_single_file(**args)

        assert read_key(str(path)) == "C"

        batches = list_recent_batches(limit=5, db_path=undo_db)
        assert len(batches) == 1
        result = revert_batch_by_id(batches[0].batch_id, db_path=undo_db)
        assert result.reverted >= 1
        assert path.read_bytes() == original
        assert hashlib.sha256(path.read_bytes()).hexdigest() == original_sha.hexdigest()
