"""
test_file_processor.py
Pytest suite for noise_reduction.core.file_processor.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
from mutagen.id3 import TPE1
from mutagen.wave import WAVE
from pydub import AudioSegment
from pydub.generators import Sine

from audio_suite_shared.audio_conversion import segment_to_numpy
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from noise_reduction.core.file_processor import (
    process_single_file,
    run_noise_reduction,
)
from noise_reduction.core.models import NoiseReductionParams

_HUM_HZ = 60
_TONE_HZ = 1000
_SAMPLE_RATE = 44100


def _parse(*args: str):
    with patch.object(sys, "argv", ["app.py", *args]):
        from noise_reduction.utils.cli_args import parse

        return parse()


def _make_audio_file(path, freq_hz=60.0, duration_ms=500) -> None:
    seg = Sine(freq_hz).to_audio_segment(duration=duration_ms).set_channels(1)
    seg.export(str(path), format="wav")


def _make_params(*, dry_run: bool = False) -> NoiseReductionParams:
    return NoiseReductionParams(reduce_hum=True, hum_frequency=60, dry_run=dry_run)


def _make_tone_plus_hum_file(
    path: Path, *, tone_amp: float = 0.35, hum_amp: float = 0.6
) -> None:
    """Write a 1 kHz tone + 60 Hz hum WAV (1 s, mono, 16-bit).

    One second is a whole number of cycles for both components, so a
    rectangular-window DFT places each in a single bin with no leakage.
    """
    t = np.arange(_SAMPLE_RATE) / _SAMPLE_RATE
    signal = tone_amp * np.sin(2 * np.pi * _TONE_HZ * t) + hum_amp * np.sin(
        2 * np.pi * _HUM_HZ * t
    )
    pcm = np.round(np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
    segment = AudioSegment(
        pcm.tobytes(), frame_rate=_SAMPLE_RATE, sample_width=2, channels=1
    )
    segment.export(str(path), format="wav")


def _bin_amplitude_db(path: Path, freq_hz: float) -> float:
    """Amplitude (dBFS) of *path* at *freq_hz*, measured from the decoded file."""
    samples, _sample_rate = segment_to_numpy(AudioSegment.from_file(str(path)))
    mono = samples.mean(axis=0).astype(np.float64)
    spectrum = np.fft.rfft(mono)
    k = int(round(freq_hz * len(mono) / _SAMPLE_RATE))
    assert k < len(spectrum)
    return float(20 * np.log10(max(2 * abs(spectrum[k]) / len(mono), 1e-12)))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_noise(dir_path: str, params: NoiseReductionParams) -> tuple[dict, list[str]]:
    """Drive ``run_noise_reduction`` with recording callbacks.

    Returns the ``on_complete`` keyword arguments and the per-file
    ``display_text`` values, in completion order.  A fatal ``on_error`` is
    raised here rather than inside the callback because ``handle_audio_errors``
    swallows exceptions raised by the callback itself.
    """
    complete: dict = {}
    display: list[str] = []
    errors: list[str] = []

    run_noise_reduction(
        dir_path,
        params,
        [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)],
        _full_slot_queue(),
        lambda **kw: display.append(kw["display_text"]),
        lambda **kw: complete.update(kw),
        errors.append,
    )
    if errors:
        raise AssertionError(f"run_noise_reduction reported a fatal error: {errors}")
    return complete, display


def _full_slot_queue() -> Queue[int]:
    queue: Queue[int] = Queue()
    for i in range(DEFAULT_MAX_WORKERS):
        queue.put(i)
    return queue


def _write_artist(path: Path, artist: str) -> None:
    """Write an ID3 ``TPE1`` (artist) frame to a WAV file."""
    wave = WAVE(str(path))
    if wave.tags is None:
        wave.add_tags()
    wave["TPE1"] = TPE1(encoding=3, text=[artist])
    wave.save()


def _read_artist(path: Path) -> str | None:
    wave = WAVE(str(path))
    tags = wave.tags
    if tags is None:
        return None
    frame = tags.get("TPE1")
    return str(frame) if frame is not None else None


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


class TestNoiseReductionOutcome:
    """Outcome-level locks for C2 (audio write path).

    Every assertion here decodes the file that was actually written and
    measures it — none of them read back internal state the processor just
    wrote.  The expected values were recorded by running this suite against
    the pre-refactor twin (``noise_reduction/core/file_processor.py`` with its
    hand-rolled discover/temp/write/undo sequence) and re-measuring after the
    workflow was consolidated into ``BaseFileProcessor``.

    Signal: 1 kHz tone (tonal content) + 60 Hz mains hum (the noise floor),
    1 s, mono 16-bit WAV.  The duration is a whole number of cycles for both
    components, so a rectangular-window DFT places each in exactly one bin.
    """

    def test_hum_floor_drops_and_tone_survives(self, tmp_path):
        audio_file = tmp_path / "hum.wav"
        _make_tone_plus_hum_file(audio_file)

        hum_before = _bin_amplitude_db(audio_file, _HUM_HZ)
        tone_before = _bin_amplitude_db(audio_file, _TONE_HZ)
        assert hum_before > tone_before - 5.0  # hum is the louder component

        complete, display = _run_noise(str(tmp_path), _make_params())

        assert complete["succeeded"] == 1
        assert display[0].startswith(f"[FIXED] {audio_file.name} → Attenuated ")

        hum_after = _bin_amplitude_db(audio_file, _HUM_HZ)
        tone_after = _bin_amplitude_db(audio_file, _TONE_HZ)

        # Pre-refactor measurement: 60 Hz bin -4.44 dBFS -> -20.42 dBFS
        # (a 15.98 dB drop); 1 kHz bin -9.12 dBFS -> -9.12 dBFS (-0.005 dB).
        assert hum_after <= hum_before - 12.0
        assert abs(tone_after - tone_before) <= 0.25

    def test_dry_run_writes_nothing(self, tmp_path):
        audio_file = tmp_path / "hum.wav"
        _make_tone_plus_hum_file(audio_file)
        digest_before = _sha256(audio_file)
        mtime_before = audio_file.stat().st_mtime_ns

        complete, display = _run_noise(str(tmp_path), _make_params(dry_run=True))

        # FOUND, not SKIP - the DSP ran, so this test cannot pass
        # vacuously by the file being untouched for lack of detected
        # defects.  This mirrors ``pop_click_remover``'s twin lock exactly.
        # Pre-B1 this asserted ``skipped == 1`` and the line
        # "[SKIP] ... Clean - no noise detected" for a file carrying
        # 15.98 dB of hum, because ``reduce_noise`` short-circuited on
        # ``params.dry_run`` and returned ``was_modified=False``; the
        # divergence between the twins was recorded as a product defect
        # (iteration-5 C2) and is closed by B1.
        assert complete["succeeded"] == 1
        assert complete["skipped"] == 0
        assert len(display) == 1
        assert display[0].startswith(f"[FOUND] {audio_file.name} → Attenuated ")
        # ...while still writing nothing: no export, no tag write, no
        # temp file left behind, bytes and mtime untouched.
        assert _sha256(audio_file) == digest_before
        assert audio_file.stat().st_mtime_ns == mtime_before
        assert [p.name for p in tmp_path.iterdir()] == ["hum.wav"]

    def test_export_call_count_differs_between_dry_run_and_live(self, tmp_path):
        """The dry-run flag must be traced all the way to the write site."""
        dry_dir = tmp_path / "dry"
        live_dir = tmp_path / "live"
        dry_dir.mkdir()
        live_dir.mkdir()
        _make_tone_plus_hum_file(dry_dir / "hum.wav")
        _make_tone_plus_hum_file(live_dir / "hum.wav")

        real_export = AudioSegment.export
        exported: list[str] = []

        def _tracking_export(self, *args, **kwargs):
            exported.append(str(args[0]) if args else "")
            return real_export(self, *args, **kwargs)

        with patch.object(AudioSegment, "export", _tracking_export):
            _run_noise(str(dry_dir), _make_params(dry_run=True))
        assert exported == []

        with patch.object(AudioSegment, "export", _tracking_export):
            _run_noise(str(live_dir), _make_params())
        assert len(exported) == 1

    def test_undo_round_trip_restores_original_bytes(self, tmp_path):
        """Undo puts the file back exactly, audio and tags together.

        Inverted from the pre-B2 lock, which asserted the *documented
        limitation* that the audio bytes were NOT restored (only the tags):
        ``record_tag_edit_snapshot`` stored a tag payload and
        ``_revert_tag_edit`` only called ``set_raw_tags``.  B2 settled the
        contract the iteration-5 C2 row called unimplementable - the shared
        in-place workflow now snapshots the whole file via
        ``record_audio_overwrite_snapshot``, so the hash below returns to the
        pre-run value instead of staying at the repaired one.
        """
        audio_file = tmp_path / "hum.wav"
        _make_tone_plus_hum_file(audio_file)
        _write_artist(audio_file, "Original Artist")
        original_digest = _sha256(audio_file)
        original_bytes = audio_file.read_bytes()

        from audio_suite_shared.batch_undo import BatchUndoLog, active_batch

        undo_db = tmp_path / "undo.db"
        with active_batch("noise_reduction", "tag_edit", db_path=str(undo_db)):
            complete, _ = _run_noise(str(tmp_path), _make_params())
        assert complete["succeeded"] == 1

        with BatchUndoLog(db_path=str(undo_db)) as log:
            batches = log.list_batches(limit=10)
            records = log.get_batch_records(batches[0].batch_id)
            assert len(records) == 1
            assert records[0].file_path == str(audio_file)
            assert records[0].operation == "noise_reduce_edit"
            # A byte-level record, not a pickled tag payload.
            assert records[0].file_action == "overwrite"

        # The tool preserved the incoming tags across the audio rewrite, and
        # the repair really did change the audio.
        assert _read_artist(audio_file) == "Original Artist"
        repaired_digest = _sha256(audio_file)
        assert repaired_digest != original_digest

        # Corrupt the tags after the run, as a later tool would.
        _write_artist(audio_file, "Someone Else")
        assert _read_artist(audio_file) == "Someone Else"

        with BatchUndoLog(db_path=str(undo_db)) as log:
            result = log.revert_batch(batches[0].batch_id)

        assert result.reverted == 1
        assert result.failed == 0
        # Byte-for-byte: the audio is the pre-run audio, and the tags that
        # shipped with it come back with it.
        assert _sha256(audio_file) == original_digest
        assert audio_file.read_bytes() == original_bytes
        assert _read_artist(audio_file) == "Original Artist"


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
