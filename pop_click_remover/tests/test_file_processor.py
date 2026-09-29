"""
test_file_processor.py
Pytest suite for pop_click_remover.core.file_processor.

All filesystem I/O, pydub, and audio_suite_shared calls are mocked so
that no real audio files, network access, or Tk display is required.

Coverage
--------
* run_declicking: directory scan failure → on_error called
* run_declicking: empty directory → on_error called
* run_declicking: successful dry-run batch — on_progress and on_complete
  called with correct aggregated counters
* run_declicking: successful live-run batch — FIXED status path exercised
* run_declicking: worker exception → ERROR counter incremented, on_complete
  still called (no hang)
* process_single_file: slot pool bookkeeping — slot always returned on
  exception (finally block)
* _export_args: known and unknown extension mapping
"""

from __future__ import annotations

import hashlib
import os
import threading
from contextlib import nullcontext
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
from mutagen.id3 import TPE1
from mutagen.wave import WAVE
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import segment_to_numpy
from audio_suite_shared.audio_formats import get_export_args as _export_args
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from pop_click_remover.core.file_processor import (
    process_single_file,
    run_declicking,
)

_SAMPLE_RATE = 44100
_TONE_HZ = 1000
_QUIET_AMP = 0.002
_TONE_AMP = 0.5
_CLICK_AMP = 0.9
_TONE_SAMPLES = 22050  # exactly 0.5 s == 500 cycles of 1 kHz
_CLICK_OFFSETS = (26460, 33075, 39690)  # 0.60 s, 0.75 s, 0.90 s

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_slot_vars(n: int = DEFAULT_MAX_WORKERS) -> list[MagicMock]:
    """Return a list of mock StringVar objects."""
    return [MagicMock() for _ in range(n)]


def _make_slot_queue(n: int = DEFAULT_MAX_WORKERS) -> Queue[int]:
    q: Queue[int] = Queue()
    for i in range(n):
        q.put(i)
    return q


# ── _export_args ──────────────────────────────────────────────────────────────


class TestExportArgs:
    def test_known_extensions(self):
        assert _export_args(".mp3") == ("mp3", ["-q:a", "0"])
        assert _export_args(".flac") == ("flac", ["-compression_level", "8"])
        assert _export_args(".ogg") == ("ogg", ["-q:a", "6"])
        assert _export_args(".m4a") == ("mp4", ["-b:a", "256k"])
        assert _export_args(".opus") == ("opus", ["-b:a", "192k"])

    def test_uncompressed_pcm_extensions(self):
        """WAV and AIFF are uncompressed PCM; no bitrate/quality params apply."""
        assert _export_args(".wav") == ("wav", [])
        assert _export_args(".aiff") == ("aiff", [])
        assert _export_args(".aif") == ("aiff", [])

    def test_case_insensitive(self):
        assert _export_args(".MP3") == _export_args(".mp3")
        assert _export_args(".FLAC") == _export_args(".flac")
        assert _export_args(".WAV") == _export_args(".wav")

    def test_unknown_extension_defaults_to_mp3(self):
        """An extension outside SUPPORTED_EXTENSIONS should never reach this
        function in practice (run_declicking filters by SUPPORTED_EXTENSIONS
        first), but the fallback is exercised directly here for safety."""
        fmt, params = _export_args(".xyz")
        assert fmt == "mp3"
        assert params == ["-q:a", "0"]


# ── run_declicking ────────────────────────────────────────────────────────────

_SHARED_PATCH_BASE = "pop_click_remover.core.file_processor"
_WORKFLOW_PATCH_BASE = "audio_suite_shared.file_processor_base"
_TAG_PATCH_BASE = "audio_suite_shared.tag_helper"


class TestRunDeclicking:
    def _run(
        self,
        dir_path,
        files=None,
        scan_exc=None,
        declick_result=None,
        is_dry_run=True,
        sensitivity=0.1,
        max_width=2,
        batch=None,
    ):
        """
        Helper: run run_declicking with mocked filesystem and audio stack.
        Returns (progress_calls, complete_kwargs, error_calls).
        """
        progress_calls: list = []
        complete_kwargs: dict = {}
        error_calls: list = []

        def on_progress(**kw):
            progress_calls.append(kw)

        def on_complete(**kw):
            complete_kwargs.update(kw)

        def on_error(msg: str):
            error_calls.append(msg)

        slot_vars = _make_slot_vars()
        slot_queue = _make_slot_queue()

        # Build scandir entries
        if files is not None:
            entries = []
            for name in files:
                e = MagicMock()
                e.name = name
                e.is_file.return_value = True
                entries.append(e)
        else:
            entries = []

        mock_declick = declick_result or MagicMock(was_modified=False, clicks_found=0)

        with (
            patch(f"{_WORKFLOW_PATCH_BASE}.os.scandir") as mock_scan,
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.copy2"),
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.rmtree"),
            patch(f"{_WORKFLOW_PATCH_BASE}.tempfile.mkdtemp", return_value="/tmp/fake"),
            patch(f"{_TAG_PATCH_BASE}.read_tags_raw", return_value={}),
            patch(f"{_TAG_PATCH_BASE}.write_tags_raw"),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.AudioSegment.from_file",
                return_value=MagicMock(),
            ),
            patch(f"{_SHARED_PATCH_BASE}.declick_audio", return_value=mock_declick),
            patch(f"{_SHARED_PATCH_BASE}.SUPPORTED_EXTENSIONS", (".mp3", ".flac")),
        ):
            if scan_exc is not None:
                mock_scan.side_effect = scan_exc
            else:
                mock_scan.return_value.__iter__ = lambda s: iter(entries)

            with batch if batch is not None else nullcontext():
                run_declicking(
                    dir_path=dir_path,
                    is_dry_run=is_dry_run,
                    sensitivity=sensitivity,
                    max_width=max_width,
                    slot_vars=slot_vars,
                    slot_queue=slot_queue,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    on_error=on_error,
                )

        return progress_calls, complete_kwargs, error_calls

    def test_scan_oserror_calls_on_error(self, tmp_path):
        _, _, errors = self._run(str(tmp_path), scan_exc=OSError("permission denied"))
        assert len(errors) == 1

    def test_empty_directory_calls_on_error(self, tmp_path):
        _, _, errors = self._run(str(tmp_path), files=[])
        assert errors == ["No supported audio files found in the selected directory."]

    def test_dry_run_clean_files_skipped(self, tmp_path):
        clean_result = MagicMock(was_modified=False, clicks_found=0)
        progress, complete, errors = self._run(
            str(tmp_path),
            files=["a.mp3", "b.flac"],
            declick_result=clean_result,
            is_dry_run=True,
        )
        assert not errors
        assert complete["total"] == 2
        assert complete["skipped"] == 2
        assert complete["succeeded"] == 0
        assert complete["errors"] == 0
        assert len(progress) == 2

    def test_dry_run_clicks_found_increments_succeeded(self, tmp_path):
        found_result = MagicMock(was_modified=True, clicks_found=3)
        progress, complete, errors = self._run(
            str(tmp_path),
            files=["a.mp3"],
            declick_result=found_result,
            is_dry_run=True,
        )
        assert not errors
        assert complete["succeeded"] == 1
        assert complete["skipped"] == 0

    def test_live_run_modified_increments_succeeded(self, tmp_path):
        fixed_result = MagicMock(was_modified=True, clicks_found=2)
        fixed_result.audio = MagicMock()
        fixed_result.audio.export = MagicMock()
        progress, complete, errors = self._run(
            str(tmp_path),
            files=["a.mp3"],
            declick_result=fixed_result,
            is_dry_run=False,
        )
        assert not errors
        assert complete["succeeded"] == 1

    def test_live_run_records_single_real_path_snapshot_under_batch(
        self,
        tmp_path,
    ):
        """A live run records exactly one undo entry pointing at the real
        file path (never the temp staging path)."""
        from audio_suite_shared.batch_undo import BatchUndoLog, active_batch

        undo_db = tmp_path / "undo.db"
        fixed_result = MagicMock(was_modified=True, clicks_found=2)
        fixed_result.audio = MagicMock()
        fixed_result.audio.export = MagicMock()

        handler = MagicMock()
        handler.get_raw_tags.return_value = {}
        instance = MagicMock()
        instance.get_handler.return_value = handler
        factory = MagicMock()
        factory.get_handler.return_value = handler
        factory.return_value = instance

        with patch("audio_suite_shared.tag_helper_base.TagHandlerFactory", factory):
            _, complete, errors = self._run(
                str(tmp_path),
                files=["a.mp3"],
                declick_result=fixed_result,
                is_dry_run=False,
                batch=active_batch(
                    "pop_click_remover", "tag_edit", db_path=str(undo_db)
                ),
            )

        assert not errors
        assert complete["succeeded"] == 1

        with BatchUndoLog(db_path=str(undo_db)) as log:
            batches = log.list_batches(limit=10)
            assert len(batches) == 1
            records = log.get_batch_records(batches[0].batch_id)
            assert len(records) == 1
            assert records[0].file_path == os.path.join(str(tmp_path), "a.mp3")
            assert records[0].operation == "declick_edit"

    def test_on_complete_receives_log_entries(self, tmp_path):
        clean = MagicMock(was_modified=False, clicks_found=0)
        _, complete, _ = self._run(
            str(tmp_path), files=["a.mp3", "b.flac"], declick_result=clean
        )
        assert "log_entries" in complete
        assert len(complete["log_entries"]) == 2

    def test_progress_counter_increments_per_file(self, tmp_path):
        clean = MagicMock(was_modified=False, clicks_found=0)
        progress, _, _ = self._run(
            str(tmp_path), files=["a.mp3", "b.flac", "c.flac"], declick_result=clean
        )
        processed_values = [p["processed"] for p in progress]
        assert processed_values == [1, 2, 3]

    def test_mixed_batch_counter_aggregation(self, tmp_path):
        """A mix of clean, modified, and error files produces correct
        aggregated counters (succeeded, skipped, errors).  DEFAULT_MAX_WORKERS
        is patched to 1 so file order is deterministic."""
        clean = MagicMock(was_modified=False, clicks_found=0)
        modified = MagicMock(was_modified=True, clicks_found=3)
        modified.audio = MagicMock()
        modified.audio.export = MagicMock()

        with (
            patch(f"{_SHARED_PATCH_BASE}.DEFAULT_MAX_WORKERS", 1),
            patch(f"{_WORKFLOW_PATCH_BASE}.os.scandir") as mock_scan,
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.rmtree"),
            patch(f"{_WORKFLOW_PATCH_BASE}.tempfile.mkdtemp", return_value="/tmp/fake"),
            patch(f"{_TAG_PATCH_BASE}.read_tags_raw", return_value={}),
            patch(f"{_TAG_PATCH_BASE}.write_tags_raw"),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.AudioSegment.from_file",
                return_value=MagicMock(),
            ),
            patch(f"{_SHARED_PATCH_BASE}.SUPPORTED_EXTENSIONS", (".mp3",)),
        ):
            entries = []
            for name in ["clean.mp3", "mod.mp3", "err.mp3"]:
                e = MagicMock()
                e.name = name
                e.is_file.return_value = True
                entries.append(e)
            mock_scan.return_value.__iter__ = lambda s: iter(entries)

            # Sequential (1 worker): clean→SKIP (1 copy2), mod→FIXED (2 copy2: in+out),
            # err (copy-to-temp fails → ERROR)
            copy2_results = [None, None, None, OSError("disk full")]

            with (
                patch(
                    f"{_SHARED_PATCH_BASE}.declick_audio", side_effect=[clean, modified]
                ),
                patch(
                    f"{_WORKFLOW_PATCH_BASE}.shutil.copy2", side_effect=copy2_results
                ),
                patch(
                    f"{_WORKFLOW_PATCH_BASE}.map_to_audio_error",
                    side_effect=lambda e: e,
                ),
            ):
                complete_result: dict = {}
                run_declicking(
                    dir_path=str(tmp_path),
                    is_dry_run=False,
                    sensitivity=0.1,
                    max_width=2,
                    slot_vars=_make_slot_vars(),
                    slot_queue=_make_slot_queue(),
                    on_progress=lambda **kw: None,
                    on_complete=lambda **kw: complete_result.update(kw),
                    on_error=lambda m: None,
                )

        assert complete_result["total"] == 3
        assert complete_result["skipped"] == 1  # clean.mp3
        assert complete_result["succeeded"] == 1  # mod.mp3
        assert complete_result["errors"] == 1  # err.mp3

    def test_worker_exception_increments_error_counter(self, tmp_path):
        """An exception in a worker should increment errors and not stall
        on_complete."""
        with (
            patch(f"{_WORKFLOW_PATCH_BASE}.os.scandir") as mock_scan,
            patch(
                f"{_WORKFLOW_PATCH_BASE}.shutil.copy2", side_effect=OSError("disk full")
            ),
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.rmtree"),
            patch(f"{_WORKFLOW_PATCH_BASE}.tempfile.mkdtemp", return_value="/tmp/fake"),
            patch(f"{_TAG_PATCH_BASE}.read_tags_raw", return_value={}),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.AudioSegment.from_file",
                return_value=MagicMock(),
            ),
            patch(f"{_SHARED_PATCH_BASE}.declick_audio"),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.map_to_audio_error", side_effect=lambda e: e
            ),
            patch(f"{_SHARED_PATCH_BASE}.SUPPORTED_EXTENSIONS", (".mp3",)),
        ):
            entry = MagicMock()
            entry.name = "bad.mp3"
            entry.is_file.return_value = True
            mock_scan.return_value.__iter__ = lambda s: iter([entry])

            complete_result: dict = {}
            error_result: list = []

            run_declicking(
                dir_path=str(tmp_path),
                is_dry_run=True,
                sensitivity=0.1,
                max_width=2,
                slot_vars=_make_slot_vars(),
                slot_queue=_make_slot_queue(),
                on_progress=lambda **kw: None,
                on_complete=lambda **kw: complete_result.update(kw),
                on_error=lambda m: error_result.append(m),
            )

        assert not error_result  # on_error is for fatal pre-processing errors only
        assert complete_result["errors"] == 1
        assert complete_result["total"] == 1

    def test_no_retry_wrapper_single_attempt_per_file(self, tmp_path):
        """
        Regression test for the removed dead-retry path.

        Previously, run_declicking wrapped every worker call in
        recovery_manager.retry_with_backoff(process_single_file, retry_config, ...)
        configured for 3 retries on OSError/IOError/PermissionError. But
        process_single_file already caught Exception internally and never
        re-raised, so the retry wrapper could never see a failure to retry on
        — it was fully wired up but functionally inert. This test confirms a
        worker-level OSError now results in exactly ONE call to the failing
        operation (shutil.copy2), proving no hidden retry layer exists.
        """
        copy2_calls: list = []

        def _failing_copy2(*args, **kwargs):
            copy2_calls.append(args)
            raise OSError("disk full")

        with (
            patch(f"{_WORKFLOW_PATCH_BASE}.os.scandir") as mock_scan,
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.copy2", side_effect=_failing_copy2),
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.rmtree"),
            patch(f"{_WORKFLOW_PATCH_BASE}.tempfile.mkdtemp", return_value="/tmp/fake"),
            patch(f"{_TAG_PATCH_BASE}.read_tags_raw", return_value={}),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.AudioSegment.from_file",
                return_value=MagicMock(),
            ),
            patch(f"{_SHARED_PATCH_BASE}.declick_audio"),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.map_to_audio_error", side_effect=lambda e: e
            ),
            patch(f"{_SHARED_PATCH_BASE}.SUPPORTED_EXTENSIONS", (".mp3",)),
        ):
            entry = MagicMock()
            entry.name = "bad.mp3"
            entry.is_file.return_value = True
            mock_scan.return_value.__iter__ = lambda s: iter([entry])

            complete_result: dict = {}

            run_declicking(
                dir_path=str(tmp_path),
                is_dry_run=True,
                sensitivity=0.1,
                max_width=2,
                slot_vars=_make_slot_vars(),
                slot_queue=_make_slot_queue(),
                on_progress=lambda **kw: None,
                on_complete=lambda **kw: complete_result.update(kw),
                on_error=lambda m: None,
            )

        # Exactly one attempt — no retry loop fired (even though the old
        # RetryConfig was configured for max_retries=3).
        assert len(copy2_calls) == 1
        assert complete_result["errors"] == 1

    def test_run_declicking_no_longer_imports_recovery_manager(self):
        """
        Regression test: confirm get_recovery_manager is no longer imported.
        """
        import pop_click_remover.core.file_processor as fp_module

        assert not hasattr(fp_module, "get_recovery_manager")


# ── process_single_file slot bookkeeping ──────────────────────────────────────


class TestProcessSingleFileSlotBookkeeping:
    def test_slot_always_returned_on_exception(self, tmp_path):
        """
        Even when an exception occurs, the slot index must be put back into
        slot_queue so no slot is permanently leaked.
        """
        slot_vars = _make_slot_vars()
        slot_queue = _make_slot_queue()
        lock = threading.Lock()
        progress_calls: list = []

        def on_progress(**kw):
            progress_calls.append(kw)

        with (
            patch(
                f"{_WORKFLOW_PATCH_BASE}.shutil.copy2", side_effect=RuntimeError("boom")
            ),
            patch(f"{_WORKFLOW_PATCH_BASE}.shutil.rmtree"),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.tempfile.mkdtemp", return_value=str(tmp_path)
            ),
            patch(f"{_TAG_PATCH_BASE}.read_tags_raw", side_effect=RuntimeError("boom")),
            patch(
                f"{_WORKFLOW_PATCH_BASE}.map_to_audio_error", side_effect=lambda e: e
            ),
        ):
            initial_size = slot_queue.qsize()

            process_single_file(
                name="bad.mp3",
                dir_path=str(tmp_path),
                is_dry_run=True,
                sensitivity=0.1,
                max_width=2,
                temp_dir=str(tmp_path),
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                lock=lock,
                on_progress=on_progress,
            )

        # Slot must be back — queue size unchanged from before the call
        assert slot_queue.qsize() == initial_size
        # Error path must have called on_progress with ERROR status
        assert any(c.get("status") == "ERROR" for c in progress_calls)


# ── Outcome-level locks (C2) ──────────────────────────────────────────────────


def _make_tone_with_clicks_file(path: Path) -> np.ndarray:
    """Write a 1 kHz tone with three single-sample clicks.

    Layout (1 s, mono, 16-bit, 44.1 kHz):
      0.000-0.500 s  1 kHz tone at 0.5 amplitude  — legitimate content
      0.500-0.505 s  raised-cosine fade down to the quiet bed (no step edge,
                    which would itself look like a click to the detector)
      0.505-1.000 s  1 kHz tone at 0.002 amplitude — near-silent bed
      0.600/0.750/0.900 s  single-sample clicks at +/-0.9

    The clicks sit in the quiet bed on purpose: the declicker detects a spike
    relative to the *local* first-difference MAD, so a full-scale click on top
    of a loud tone is below its detection floor by design.

    Returns the int16 sample array that was written.
    """
    t = np.arange(_SAMPLE_RATE) / _SAMPLE_RATE
    tone = _TONE_AMP * np.sin(2 * np.pi * _TONE_HZ * t)
    fade_start, fade_end = _TONE_SAMPLES, _TONE_SAMPLES + 220
    ramp = np.linspace(0.0, 1.0, fade_end - fade_start)
    fade = _TONE_AMP + (_QUIET_AMP - _TONE_AMP) * (0.5 - 0.5 * np.cos(np.pi * ramp))
    tone[fade_start:fade_end] = fade * np.sin(
        2 * np.pi * _TONE_HZ * t[fade_start:fade_end]
    )
    signal = tone.copy()
    signal[fade_end:] = _QUIET_AMP * np.sin(2 * np.pi * _TONE_HZ * t[fade_end:])
    for offset, sign in zip(_CLICK_OFFSETS, (1.0, -1.0, 1.0)):
        signal[offset] += sign * _CLICK_AMP

    pcm = np.round(np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
    segment = AudioSegment(
        pcm.tobytes(), frame_rate=_SAMPLE_RATE, sample_width=2, channels=1
    )
    segment.export(str(path), format="wav")
    return pcm


def _read_mono(path: Path) -> tuple[np.ndarray, int]:
    """Decode *path* and return ``(mono float64 samples, frame_rate)``."""
    samples, sample_rate = segment_to_numpy(AudioSegment.from_file(str(path)))
    return samples.mean(axis=0).astype(np.float64), sample_rate


def _tone_bin_db(samples: np.ndarray) -> float:
    """Amplitude (dBFS) of the 1 kHz component of *samples*."""
    spectrum = np.fft.rfft(samples)
    k = int(round(_TONE_HZ * len(samples) / _SAMPLE_RATE))
    return float(20 * np.log10(max(2 * abs(spectrum[k]) / len(samples), 1e-12)))


def _max_abs_diff(samples: np.ndarray) -> float:
    return float(np.abs(np.diff(samples)).max())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_declicking_live(dir_path: Path, *, dry_run: bool) -> tuple[dict, list[str]]:
    """Drive ``run_declicking`` with recording callbacks.

    Returns the ``on_complete`` keyword arguments and the per-file
    ``display_text`` values.  A fatal ``on_error`` is raised here rather than
    inside the callback because ``handle_audio_errors`` swallows exceptions
    raised by the callback itself.
    """
    complete: dict = {}
    display: list[str] = []
    errors: list[str] = []

    run_declicking(
        dir_path=str(dir_path),
        is_dry_run=dry_run,
        sensitivity=0.31,
        max_width=2,
        slot_vars=_make_slot_vars(),
        slot_queue=_make_slot_queue(),
        on_progress=lambda **kw: display.append(kw["display_text"]),
        on_complete=lambda **kw: complete.update(kw),
        on_error=errors.append,
    )
    if errors:
        raise AssertionError(f"run_declicking reported a fatal error: {errors}")
    return complete, display


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


class TestDeclickOutcome:
    """Outcome-level locks for C2 (audio write path).

    Every assertion decodes the file that was actually written and measures it.
    The expected values were recorded by running this suite against the
    pre-refactor twin and re-measuring after the workflow was consolidated
    into ``BaseFileProcessor``.
    """

    def test_clicks_are_attenuated_and_tone_is_intact(self, tmp_path):
        audio_file = tmp_path / "clicks.wav"
        before_pcm = _make_tone_with_clicks_file(audio_file)
        before, _rate = _read_mono(audio_file)
        assert _max_abs_diff(before) >= 0.8  # the clicks are really in the input

        complete, display = _run_declicking_live(tmp_path, dry_run=False)

        assert complete["succeeded"] == 1
        assert display == [f"[FIXED] {audio_file.name} → Found 3 click(s) — Repaired"]

        after, rate = _read_mono(audio_file)
        # Pre-refactor measurements:
        #   frame count 44100 -> 44100, rate 44100 -> 44100 (length invariant)
        #   max |first difference| 0.9002 -> 0.0712
        #   1 kHz bin (0-0.5 s) -6.0209 dBFS -> -6.0209 dBFS
        assert len(after) == len(before) == 44100
        assert rate == _SAMPLE_RATE
        assert _max_abs_diff(after) <= 0.15
        # The untouched tone section survives bit-for-bit: WAV is lossless PCM
        # and the repair only rewrites the three click samples.
        assert np.array_equal(after[:_TONE_SAMPLES], before[:_TONE_SAMPLES])
        assert (
            abs(
                _tone_bin_db(after[:_TONE_SAMPLES])
                - _tone_bin_db(before[:_TONE_SAMPLES])
            )
            <= 0.25
        )
        # The clicks themselves are gone, not merely quieter.
        assert np.abs(after[list(_CLICK_OFFSETS)]).max() <= 0.01
        assert np.abs(before[list(_CLICK_OFFSETS)]).max() >= 0.8
        assert not np.array_equal(after, before_pcm.astype(np.float64) / 32767.0)

    def test_dry_run_writes_nothing(self, tmp_path):
        audio_file = tmp_path / "clicks.wav"
        _make_tone_with_clicks_file(audio_file)
        digest_before = _sha256(audio_file)
        mtime_before = audio_file.stat().st_mtime_ns

        complete, display = _run_declicking_live(tmp_path, dry_run=True)

        # FOUND, not SKIP — the detector ran, so this test cannot pass
        # vacuously by the file being untouched for lack of detected defects.
        assert complete["succeeded"] == 1
        assert complete["skipped"] == 0
        assert display == [f"[FOUND] {audio_file.name} → Found 3 click(s)"]
        assert _sha256(audio_file) == digest_before
        assert audio_file.stat().st_mtime_ns == mtime_before
        assert [p.name for p in tmp_path.iterdir()] == ["clicks.wav"]

    def test_export_call_count_differs_between_dry_run_and_live(self, tmp_path):
        """The dry-run flag must be traced all the way to the write site."""
        dry_dir = tmp_path / "dry"
        live_dir = tmp_path / "live"
        dry_dir.mkdir()
        live_dir.mkdir()
        _make_tone_with_clicks_file(dry_dir / "clicks.wav")
        _make_tone_with_clicks_file(live_dir / "clicks.wav")

        real_export = AudioSegment.export
        exported: list[str] = []

        def _tracking_export(self, *args, **kwargs):
            exported.append(str(args[0]) if args else "")
            return real_export(self, *args, **kwargs)

        with patch.object(AudioSegment, "export", _tracking_export):
            _run_declicking_live(dry_dir, dry_run=True)
        assert exported == []

        with patch.object(AudioSegment, "export", _tracking_export):
            _run_declicking_live(live_dir, dry_run=False)
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
        from audio_suite_shared.batch_undo import BatchUndoLog, active_batch

        audio_file = tmp_path / "clicks.wav"
        _make_tone_with_clicks_file(audio_file)
        _write_artist(audio_file, "Original Artist")
        original_digest = _sha256(audio_file)
        original_bytes = audio_file.read_bytes()

        undo_db = tmp_path / "undo.db"
        with active_batch("pop_click_remover", "tag_edit", db_path=str(undo_db)):
            complete, _ = _run_declicking_live(tmp_path, dry_run=False)
        assert complete["succeeded"] == 1

        with BatchUndoLog(db_path=str(undo_db)) as log:
            batches = log.list_batches(limit=10)
            records = log.get_batch_records(batches[0].batch_id)
            assert len(records) == 1
            assert records[0].file_path == os.path.join(str(tmp_path), "clicks.wav")
            assert records[0].operation == "declick_edit"
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
