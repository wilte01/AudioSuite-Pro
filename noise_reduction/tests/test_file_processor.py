"""
test_file_processor.py
Pytest suite for noise_reduction.core.file_processor.
"""

from __future__ import annotations

import sys
import threading
from queue import Queue
from unittest.mock import MagicMock, patch

from pydub.generators import Sine

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from noise_reduction.core.file_processor import (
    process_single_file,
    run_noise_reduction,
)
from noise_reduction.core.models import NoiseReductionParams


def _parse(*args: str):
    with patch.object(sys, "argv", ["app.py", *args]):
        from noise_reduction.utils.cli_args import parse

        return parse()


def _make_audio_file(path, freq_hz=60.0, duration_ms=500) -> None:
    seg = Sine(freq_hz).to_audio_segment(duration=duration_ms).set_channels(1)
    seg.export(str(path), format="wav")


def _make_params() -> NoiseReductionParams:
    return NoiseReductionParams(reduce_hum=True, hum_frequency=60)


class TestConstants:
    def test_default_max_workers_positive(self):
        assert DEFAULT_MAX_WORKERS >= 1


class TestProcessSingleFile:
    def test_modifies_hum_file(self, tmp_path):
        audio_file = tmp_path / "hum.wav"
        _make_audio_file(audio_file)

        slot_vars = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_queue.put(i)
        lock = threading.Lock()
        callbacks: dict[str, str] = {}

        def on_progress(status, display_text, log_text):
            callbacks["status"] = status
            callbacks["display"] = display_text
            callbacks["log"] = log_text

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        process_single_file(
            audio_file.name,
            str(tmp_path),
            _make_params(),
            str(temp_dir),
            slot_vars,
            slot_queue,
            lock,
            on_progress,
        )

        assert callbacks["status"] in ("FIXED", "FOUND")

    def test_skips_clean_file(self, tmp_path):
        clean_file = tmp_path / "clean.wav"
        audio = Sine(1000.0).to_audio_segment(duration=500).set_channels(1)
        audio.export(str(clean_file), format="wav")

        slot_vars = [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)]
        slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_queue.put(i)
        lock = threading.Lock()
        callbacks: dict[str, str] = {}

        def on_progress(status, display_text, log_text):
            callbacks["status"] = status

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        process_single_file(
            clean_file.name,
            str(tmp_path),
            _make_params(),
            str(temp_dir),
            slot_vars,
            slot_queue,
            lock,
            on_progress,
        )

        assert callbacks["status"] == "SKIP"

    def test_error_on_invalid_file(self, tmp_path):
        bad_file = tmp_path / "bad.wav"
        bad_file.write_bytes(b"this is not a wav file")

        slot_vars = [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)]
        slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_queue.put(i)
        lock = threading.Lock()
        callbacks: dict[str, str] = {}

        def on_progress(status, display_text, log_text):
            callbacks["status"] = status

        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        process_single_file(
            bad_file.name,
            str(tmp_path),
            _make_params(),
            str(temp_dir),
            slot_vars,
            slot_queue,
            lock,
            on_progress,
        )

        assert callbacks["status"] == "ERROR"


class TestRunNoiseReduction:
    def test_no_files_error(self, tmp_path):
        callbacks = {"error": ""}

        def on_error(msg):
            callbacks["error"] = msg

        run_noise_reduction(
            str(tmp_path),
            _make_params(),
            [],
            Queue(),
            lambda **kw: None,
            lambda **kw: None,
            on_error,
        )

        assert "No supported audio files" in callbacks["error"]

    def test_processes_files(self, tmp_path):
        audio_file = tmp_path / "hum.wav"
        _make_audio_file(audio_file)

        slot_vars = [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)]
        slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_queue.put(i)

        completed: dict[str, object] = {}

        def on_complete(**kw):
            completed.update(kw)

        run_noise_reduction(
            str(tmp_path),
            _make_params(),
            slot_vars,
            slot_queue,
            lambda **kw: None,
            on_complete,
            lambda msg: None,
        )

        assert completed["total"] == 1
        assert completed["processed"] == 1

    def test_live_run_records_single_real_path_snapshot_under_batch(
        self,
        tmp_path,
    ):
        """A live run records exactly one undo entry pointing at the real
        file path (never the temp staging path)."""
        from audio_suite_shared.batch_undo import BatchUndoLog, active_batch

        audio_file = tmp_path / "hum.wav"
        _make_audio_file(audio_file)

        undo_db = tmp_path / "undo.db"
        handler = MagicMock()
        handler.get_raw_tags.return_value = {}
        instance = MagicMock()
        instance.get_handler.return_value = handler
        factory = MagicMock()
        factory.get_handler.return_value = handler
        factory.return_value = instance

        slot_vars = [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)]
        slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            slot_queue.put(i)

        on_error = MagicMock()

        with (
            patch("audio_suite_shared.tag_helper_base.TagHandlerFactory", factory),
            patch("audio_suite_shared.tag_helper_reader.TagHandlerFactory", factory),
            patch("audio_suite_shared.tag_helper_writer.TagHandlerFactory", factory),
        ):
            with active_batch("noise_reduction", "tag_edit", db_path=str(undo_db)):
                run_noise_reduction(
                    str(tmp_path),
                    _make_params(),
                    slot_vars,
                    slot_queue,
                    lambda **kw: None,
                    lambda **kw: None,
                    on_error,
                )

        on_error.assert_not_called()

        with BatchUndoLog(db_path=str(undo_db)) as log:
            batches = log.list_batches(limit=10)
            assert len(batches) == 1
            records = log.get_batch_records(batches[0].batch_id)
            assert len(records) == 1
            assert records[0].file_path == str(audio_file)
            assert records[0].operation == "noise_reduce_edit"


class TestCliArgsIntegration:
    def test_cli_args_produce_valid_params(self):
        ns = _parse(
            "--reduce-hum",
            "--hum-frequency",
            "50",
            "--reduce-broadband",
            "--noise-start",
            "100",
            "--noise-end",
            "800",
            "--gate-threshold",
            "5.0",
        )
        params = NoiseReductionParams(
            reduce_hum=ns.reduce_hum,
            hum_frequency=ns.hum_frequency,
            hum_harmonics=ns.hum_harmonics,
            hum_quality=ns.hum_quality,
            reduce_broadband=ns.reduce_broadband,
            noise_start_ms=ns.noise_start_ms,
            noise_end_ms=ns.noise_end_ms,
            gate_threshold_db=ns.gate_threshold_db,
        )
        assert params.reduce_hum is True
        assert params.hum_frequency == 50
        assert params.reduce_broadband is True
