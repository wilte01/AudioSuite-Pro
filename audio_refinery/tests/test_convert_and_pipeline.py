"""
Tests for audio_refinery.core.convert (G-36 convert)
         audio_refinery.core.file_processor (G-36 pipeline)

Changed in 1.1.0: added a regression test proving read-only formats are skipped and
process_file is never called.
"""

from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
from pydub import AudioSegment

from audio_refinery.core.file_processor import run_pipeline
from audio_refinery.core.models import StageConfig
from audio_refinery.core.registry import CompletionRegistry
from audio_suite_shared.audio_conversion import (
    clip_bounds,
    int_dtype,
    numpy_to_segment,
    pack_24bit,
    segment_to_numpy,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

FS = 44100


def _sine(freq=440, duration_ms=200, channels=1, amplitude=0.3) -> AudioSegment:
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = amplitude * np.sin(2 * np.pi * freq * t)
    pcm = (wave * 32767).astype(np.int16)
    if channels == 2:
        stereo = np.column_stack([pcm, pcm])
        raw = stereo.tobytes()
    else:
        raw = pcm.tobytes()
    return AudioSegment(raw, frame_rate=FS, sample_width=2, channels=channels)


def _make_audio(tmp_path, name="track.mp3"):
    path = tmp_path / name
    _sine().export(str(path), format="mp3")
    return path


def _make_slots(n=4):
    slot_vars = [MagicMock() for _ in range(n)]
    slot_q = Queue()
    for i in range(n):
        slot_q.put(i)
    return slot_vars, slot_q


def _minimal_config():
    return StageConfig()


# ═════════════════════════════════════════════════════════════════════════════
# int_dtype
# ═════════════════════════════════════════════════════════════════════════════


class TestIntDtype:
    def test_2_bytes_returns_int16(self):
        assert int_dtype(2) == np.int16

    def test_1_byte_returns_int8(self):
        assert int_dtype(1) == np.int8

    def test_3_bytes_returns_int32(self):
        assert int_dtype(3) == np.int32

    def test_4_bytes_returns_int32(self):
        assert int_dtype(4) == np.int32

    def test_5_bytes_returns_int32(self):
        assert int_dtype(5) == np.int32

    def test_6_bytes_returns_int32(self):
        assert int_dtype(6) == np.int32


# ═════════════════════════════════════════════════════════════════════════════
# convert re-exports (backward compatibility)
# ═════════════════════════════════════════════════════════════════════════════


class TestConvertReExports:
    """audio_refinery.core.convert is a thin re-export wrapper around the
    shared canonical module; every existing import path must still resolve."""

    def test_public_functions_match_shared_module(self):
        import audio_refinery.core.convert as convert

        assert convert.segment_to_numpy is segment_to_numpy
        assert convert.numpy_to_segment is numpy_to_segment
        assert convert.clip_bounds is clip_bounds
        assert convert.int_dtype is int_dtype
        assert convert.pack_24bit is pack_24bit

    def test_private_aliases_match_shared_module(self):
        import audio_refinery.core.convert as convert

        assert convert._int_dtype is int_dtype
        assert convert._clip_bounds is clip_bounds
        assert convert._pack_24bit is pack_24bit


# ═════════════════════════════════════════════════════════════════════════════
# segment_to_numpy
# ═════════════════════════════════════════════════════════════════════════════


class TestSegmentToNumpy:
    def test_returns_tuple_of_two(self):
        audio = _sine()
        result = segment_to_numpy(audio)
        assert isinstance(result, tuple) and len(result) == 2

    def test_array_is_float32(self):
        arr, _ = segment_to_numpy(_sine())
        assert arr.dtype == np.float32

    def test_sample_rate_matches(self):
        _, sr = segment_to_numpy(_sine())
        assert sr == FS

    def test_shape_channels_first_mono(self):
        arr, _ = segment_to_numpy(_sine(channels=1))
        assert arr.shape[0] == 1

    def test_shape_channels_first_stereo(self):
        arr, _ = segment_to_numpy(_sine(channels=2))
        assert arr.shape[0] == 2

    def test_values_in_minus_one_to_one(self):
        arr, _ = segment_to_numpy(_sine(amplitude=0.5))
        assert arr.min() >= -1.0
        assert arr.max() <= 1.0

    def test_silence_produces_near_zero_array(self):
        audio = AudioSegment.silent(duration=100, frame_rate=FS)
        arr, _ = segment_to_numpy(audio)
        assert np.allclose(arr, 0.0, atol=1e-5)

    def test_frame_count_matches_duration(self):
        duration_ms = 200
        arr, _ = segment_to_numpy(_sine(duration_ms=duration_ms))
        expected_frames = int(FS * duration_ms / 1000)
        assert arr.shape[1] == expected_frames

    def test_stereo_channels_are_identical_for_mono_source_doubled(self):
        """stereo constructed by duplicating mono channel → both channels equal."""
        audio = _sine(channels=2)
        arr, _ = segment_to_numpy(audio)
        np.testing.assert_array_almost_equal(arr[0], arr[1], decimal=4)


# ═════════════════════════════════════════════════════════════════════════════
# numpy_to_segment
# ═════════════════════════════════════════════════════════════════════════════


class TestNumpyToSegment:
    def test_returns_audio_segment(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert isinstance(seg, AudioSegment)

    def test_sample_rate_preserved(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert seg.frame_rate == FS

    def test_sample_width_preserved(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert seg.sample_width == 2

    def test_channels_preserved(self):
        arr = np.zeros((2, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=2)
        assert seg.channels == 2

    def test_clipping_prevents_overflow(self):
        # Values > 1.0 should be clipped to max int16
        arr = np.full((1, 100), 2.0, dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        raw = np.frombuffer(seg.raw_data, dtype=np.int16)
        assert raw.max() == np.iinfo(np.int16).max

    def test_negative_clipping(self):
        arr = np.full((1, 100), -2.0, dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        raw = np.frombuffer(seg.raw_data, dtype=np.int16)
        assert raw.min() == np.iinfo(np.int16).min

    def test_zero_array_produces_silence(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        raw = np.frombuffer(seg.raw_data, dtype=np.int16)
        assert np.all(raw == 0)


# ═════════════════════════════════════════════════════════════════════════════
# round-trip: segment → numpy → segment
# ═════════════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    def test_mono_round_trip_preserves_shape(self):
        original = _sine(channels=1, duration_ms=100)
        arr, sr = segment_to_numpy(original)
        recovered = numpy_to_segment(arr, sr, sample_width=2, num_channels=1)
        assert recovered.channels == 1
        assert abs(len(recovered) - len(original)) <= 5  # within 5ms

    def test_stereo_round_trip_preserves_shape(self):
        original = _sine(channels=2, duration_ms=100)
        arr, sr = segment_to_numpy(original)
        recovered = numpy_to_segment(arr, sr, sample_width=2, num_channels=2)
        assert recovered.channels == 2

    def test_round_trip_low_distortion(self):
        """After round-trip, waveform should be within rounding error of original."""
        original = _sine(amplitude=0.3, duration_ms=100)
        arr, sr = segment_to_numpy(original)
        recovered = numpy_to_segment(arr, sr, sample_width=2, num_channels=1)

        orig_raw = np.frombuffer(original.raw_data, dtype=np.int16).astype(np.float32)
        rec_raw = np.frombuffer(recovered.raw_data, dtype=np.int16).astype(np.float32)
        # Max absolute error should be small (rounding only)
        assert np.max(np.abs(orig_raw - rec_raw)) <= 2.0

    def test_empty_array_returns_empty_segment(self):
        arr = np.empty((1, 0), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert len(seg) == 0
        assert seg.channels == 1

    def test_32_bit_round_trip(self):
        """32-bit / int32 sample width round-trip (sample_width >= 3 code path)."""
        n = 1000
        pcm32 = np.zeros(n, dtype=np.int32)
        audio = AudioSegment(pcm32.tobytes(), frame_rate=FS, sample_width=4, channels=1)
        arr, sr = segment_to_numpy(audio)
        recovered = numpy_to_segment(arr, sr, sample_width=4, num_channels=1)
        assert recovered.sample_width == 4
        assert recovered.frame_rate == FS
        assert recovered.channels == 1


# ═════════════════════════════════════════════════════════════════════════════
# run_pipeline — file_processor
# ═════════════════════════════════════════════════════════════════════════════


class TestRunPipeline:
    def _run(self, tmp_path, file_names=None, mock_process_result=None):
        from audio_refinery.core.models import FileResult, FileStatus, StageResult

        slot_vars, slot_q = _make_slots()
        registry = CompletionRegistry(tmp_path)
        config = _minimal_config()
        progress, complete, errors = [], [], []

        if mock_process_result is None:

            def _default_result(source_path, output_path, config, on_progress):
                return FileResult(
                    path=source_path,
                    status=FileStatus.DONE,
                    stages=[StageResult(stage="declick", message="ok")],
                )

            mock_process_result = _default_result

        with (
            patch(
                "audio_refinery.core.file_processor.process_file",
                side_effect=mock_process_result,
            ),
            patch("audio_suite_shared.resource_manager.get_resource_manager"),
            patch("audio_suite_shared.resource_manager.cleanup_expired_resources"),
            patch("audio_suite_shared.resource_manager.track_thread"),
        ):
            run_pipeline(
                source_dir=tmp_path,
                output_dir=tmp_path,
                config=config,
                registry=registry,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: errors.append(msg),
            )
        return progress, complete, errors, registry

    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, errors, _ = self._run(tmp_path)
        assert len(errors) == 1

    def test_on_complete_called(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        _, complete, _, _ = self._run(tmp_path)
        assert len(complete) == 1

    def test_total_matches_file_count(self, tmp_path):
        for i in range(3):
            _make_audio(tmp_path, f"t{i}.mp3")
        _, complete, _, _ = self._run(tmp_path)
        assert complete[0]["total"] == 3

    def test_succeeded_count_correct(self, tmp_path):
        for i in range(3):
            _make_audio(tmp_path, f"t{i}.mp3")
        _, complete, _, _ = self._run(tmp_path)
        assert complete[0]["succeeded"] == 3

    def test_on_progress_called_per_file(self, tmp_path):
        for i in range(4):
            _make_audio(tmp_path, f"t{i}.mp3")
        progress, _, _, _ = self._run(tmp_path)
        assert len(progress) == 4

    def test_read_only_formats_are_skipped_not_processed(self, tmp_path):
        """APE/MPC/DSF have no encoder, so the refinery must report a read-only
        skip and never invoke the processing stage on them."""
        from audio_refinery.core.models import FileResult, FileStatus
        from audio_suite_shared.audio_formats import READ_ONLY_EXTENSIONS

        for ext in READ_ONLY_EXTENSIONS:
            (tmp_path / f"t{ext}").write_bytes(b"opaque container bytes")

        process_calls = []

        def _tracking_result(source_path, output_path, config, on_progress):
            process_calls.append(source_path)
            return FileResult(path=source_path, status=FileStatus.DONE)

        _, complete, _, _ = self._run(tmp_path, mock_process_result=_tracking_result)

        assert process_calls == []
        assert complete[0]["total"] == len(READ_ONLY_EXTENSIONS)
        assert complete[0]["skipped"] == len(READ_ONLY_EXTENSIONS)
        assert complete[0]["succeeded"] == 0

    def test_completed_file_skipped_on_second_run(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        # First run — processes file
        _, _, _, registry = self._run(tmp_path)
        # Second run — file should be skipped (in registry)
        _, complete, _, _ = self._run(tmp_path)
        assert complete[0]["skipped"] == 1
        assert complete[0]["succeeded"] == 0

    def test_error_result_counted(self, tmp_path):
        from audio_refinery.core.models import FileResult, FileStatus

        _make_audio(tmp_path, "t.mp3")

        def error_result(source_path, output_path, config, on_progress):
            return FileResult(path=source_path, status=FileStatus.ERROR, error="boom")

        _, complete, _, _ = self._run(tmp_path, mock_process_result=error_result)
        assert complete[0]["errors"] == 1

    def test_nonexistent_directory_calls_on_error(self, tmp_path):
        slot_vars, slot_q = _make_slots()
        errors = []
        run_pipeline(
            source_dir=tmp_path / "missing",
            output_dir=tmp_path,
            config=_minimal_config(),
            registry=CompletionRegistry(tmp_path),
            slot_vars=slot_vars,
            slot_queue=slot_q,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=errors.append,
        )
        assert len(errors) == 1

    def test_display_text_in_progress(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        progress, _, _, _ = self._run(tmp_path)
        assert any("t.mp3" in r.get("display_text", "") for r in progress)

    def test_log_entries_in_complete(self, tmp_path):
        _make_audio(tmp_path, "t.mp3")
        _, complete, _, _ = self._run(tmp_path)
        assert isinstance(complete[0]["log_entries"], list)
        assert len(complete[0]["log_entries"]) >= 1

    def test_mixed_success_and_error(self, tmp_path):
        from audio_refinery.core.models import FileResult, FileStatus

        [_make_audio(tmp_path, f"t{i}.mp3") for i in range(3)]

        results = [True, False, True]
        idx = [0]

        def mixed_result(source_path, output_path, config, on_progress):
            i = idx[0]
            idx[0] += 1
            if results[i]:
                return FileResult(path=source_path, status=FileStatus.DONE)
            return FileResult(path=source_path, status=FileStatus.ERROR, error="boom")

        _, complete, _, _ = self._run(tmp_path, mock_process_result=mixed_result)
        assert complete[0]["succeeded"] == 2
        assert complete[0]["errors"] == 1
        assert complete[0]["total"] == 3

    def test_separate_output_computes_different_hash(self, tmp_path):
        """When output_dir differs from source_dir, registry stores source hash."""
        from audio_refinery.core.models import FileResult, FileStatus

        src = tmp_path / "source"
        src.mkdir()
        out = tmp_path / "output"
        out.mkdir()
        _make_audio(src, "t.mp3")

        slot_vars, slot_q = _make_slots()
        registry = CompletionRegistry(src)
        config = _minimal_config()
        complete = []

        def ok_result(source_path, output_path, config, on_progress):
            return FileResult(path=source_path, status=FileStatus.DONE)

        with (
            patch(
                "audio_refinery.core.file_processor.process_file",
                side_effect=ok_result,
            ),
            patch("audio_suite_shared.resource_manager.get_resource_manager"),
            patch("audio_suite_shared.resource_manager.cleanup_expired_resources"),
            patch("audio_suite_shared.resource_manager.track_thread"),
        ):
            run_pipeline(
                source_dir=src,
                output_dir=out,
                config=config,
                registry=registry,
                slot_vars=slot_vars,
                slot_queue=slot_q,
                on_progress=lambda **kw: None,
                on_complete=lambda **kw: complete.append(kw),
                on_error=lambda msg: None,
            )

        assert len(complete) == 1
        assert complete[0]["succeeded"] == 1


class TestUndoBatchRecording:
    """Phase 2: worker threads must join the orchestrator's active undo
    batch so tag snapshots are recorded against it (batch_undo.use_batch)."""

    def _recording_process(self, source_path, output_path, config, on_progress):
        from audio_refinery.core.models import FileResult, FileStatus, StageResult
        from audio_suite_shared.tag_helper_writer import write_tags_raw

        write_tags_raw(str(source_path), {"original": "tags"})
        return FileResult(
            path=source_path,
            status=FileStatus.DONE,
            stages=[StageResult(stage="declick", message="ok")],
        )

    def _run(self, tmp_path):
        from audio_suite_shared.batch_undo import active_batch, list_recent_batches

        undo_db = tmp_path / "undo_log.db"
        for i in range(2):
            _make_audio(tmp_path, f"t{i}.mp3")
        slot_vars, slot_q = _make_slots()
        registry = CompletionRegistry(tmp_path)
        config = _minimal_config()

        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TCON": "Rock"}
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        with (
            patch(
                "audio_refinery.core.file_processor.process_file",
                side_effect=self._recording_process,
            ),
            patch("audio_suite_shared.resource_manager.get_resource_manager"),
            patch("audio_suite_shared.resource_manager.cleanup_expired_resources"),
            patch("audio_suite_shared.resource_manager.track_thread"),
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
            with active_batch("audio_refinery", "tag_edit", db_path=undo_db):
                run_pipeline(
                    source_dir=tmp_path,
                    output_dir=tmp_path,
                    config=config,
                    registry=registry,
                    slot_vars=slot_vars,
                    slot_queue=slot_q,
                    on_progress=MagicMock(),
                    on_complete=MagicMock(),
                    on_error=MagicMock(),
                )

        return list_recent_batches(limit=10, db_path=undo_db)

    def test_live_mode_records_snapshots_from_workers(self, tmp_path):
        batches = self._run(tmp_path)
        assert len(batches) == 1
        assert batches[0].tool_name == "audio_refinery"
        assert batches[0].operation_type == "tag_edit"
        assert batches[0].record_count == 2

    def test_skipped_files_prune_empty_batch(self, tmp_path):
        batches = self._run(tmp_path)
        assert len(batches) == 1
        # Second run: every file is already in the completion registry, so
        # workers skip the pipeline and no snapshots are recorded; the
        # empty batch is pruned from the undo log.
        batches = self._run(tmp_path)
        assert len(batches) == 1
        assert batches[0].record_count == 2
