"""
tests/test_silence_trimmer.py
Comprehensive pytest suite for silence_trimmer.

Covers:
  - trimmer.py: TrimResult frozen dataclass, trim_and_fade() correctness
  - file_processor.py: _export_args(), run_trimming() orchestration
  - cli_args.py: parse(), validate_args() including edge cases
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import types
from dataclasses import FrozenInstanceError
from queue import Queue
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pydub import AudioSegment

# ── Stub audio_suite_shared only if the installed package is unavailable ─────


def _make_shared_stub() -> None:
    shared = types.ModuleType("audio_suite_shared")

    exceptions_mod = types.ModuleType("audio_suite_shared.exceptions")
    exceptions_mod.map_to_audio_error = lambda exc: exc
    exceptions_mod.user_message_for = lambda exc: str(exc)

    class AudioSuiteErrorStub(Exception):
        def __init__(self, *args, **kwargs):
            super().__init__(*args)
            self.message = str(*args) if args else ""
            self.original = kwargs.get("original")
            self.context = {}

    exceptions_mod.AudioSuiteError = AudioSuiteErrorStub
    exceptions_mod.AudioDirectoryError = type(
        "AudioDirectoryError", (AudioSuiteErrorStub,), {}
    )
    exceptions_mod.AudioPermissionError = type(
        "AudioPermissionError", (AudioSuiteErrorStub,), {}
    )

    cli_dc = types.ModuleType("audio_suite_shared.cli_dataclasses")

    from dataclasses import dataclass

    @dataclass
    class BaseCLIArgs:
        folder_path: str = ""
        live_mode: bool = False
        auto_start: bool = False
        auto_end: bool = False

    cli_dc.BaseCLIArgs = BaseCLIArgs

    error_rec = types.ModuleType("audio_suite_shared.error_recovery")

    class RecoveryAction:
        SKIP = "SKIP"
        RETRY = "RETRY"

    from dataclasses import dataclass as dc2
    from dataclasses import field

    @dc2
    class RetryConfig:
        max_retries: int = 3
        retry_delay: float = 0.5
        backoff_factor: float = 1.5
        retry_on_exceptions: list = field(default_factory=list)

    def retry_with_backoff(fn, cfg, op_id, *args, **kwargs):
        fn(*args, **kwargs)

    def get_recovery_action(exc, ctx, user_callback=None):
        return RecoveryAction.SKIP

    error_rec.RecoveryAction = RecoveryAction
    error_rec.RetryConfig = RetryConfig
    error_rec.retry_with_backoff = retry_with_backoff
    error_rec.get_recovery_action = get_recovery_action

    resource_mod = types.ModuleType("audio_suite_shared.resource_manager")

    import shutil
    import tempfile
    from contextlib import contextmanager

    class _ResourceManager:
        @contextmanager
        def temporary_directory(self, prefix=""):
            d = tempfile.mkdtemp(prefix=prefix)
            try:
                yield d
            finally:
                shutil.rmtree(d, ignore_errors=True)

    resource_mod.get_resource_manager = _ResourceManager
    resource_mod.cleanup_expired_resources = lambda **kw: None
    resource_mod.track_thread = lambda t, name: None

    tag_mod = types.ModuleType("audio_suite_shared.tag_helper")
    tag_mod.SUPPORTED_EXTENSIONS = (
        ".mp3",
        ".flac",
        ".ogg",
        ".m4a",
        ".mp4",
        ".opus",
        ".wav",
        ".aiff",
        ".aif",
    )
    tag_mod.read_tags_raw = lambda path: {}
    tag_mod.write_tags_raw = lambda path, tags, **kwargs: None

    batch_mod = types.ModuleType("audio_suite_shared.batch_undo")

    from contextlib import contextmanager

    @contextmanager
    def _noop_cm(*_args, **_kwargs):
        yield None

    batch_mod.get_active_batch_id = lambda: None
    batch_mod.record_tag_edit_snapshot = lambda path, op: None
    batch_mod.use_batch = _noop_cm
    batch_mod.active_batch = _noop_cm

    fp_base = types.ModuleType("audio_suite_shared.file_processor_base")

    class BaseFileProcessorStub:
        max_workers = 4
        operation_type = "silence_trimming"
        parallel_mode = False

        def __init__(
            self,
            max_workers: int = 4,
            operation_type: str = "file_processing",
            parallel_mode: bool = False,
        ):
            self.max_workers = max_workers
            self.operation_type = operation_type
            self.parallel_mode = parallel_mode

        def discover_audio_files(self, dir_path: str, extensions=None):
            import os as _os

            from audio_suite_shared.exceptions import AudioDirectoryError as _ADE

            if not _os.path.isdir(dir_path):
                raise _ADE(f"Directory not found: {dir_path}")
            return sorted(
                e.name
                for e in _os.scandir(dir_path)
                if e.is_file() and e.name.lower().endswith(extensions or ())
            )

        def create_retry_config(
            self, max_retries=3, retry_delay=0.5, backoff_factor=1.5
        ):
            from audio_suite_shared.error_recovery import RetryConfig as _RC

            return _RC(
                max_retries=max_retries,
                retry_delay=retry_delay,
                backoff_factor=backoff_factor,
                retry_on_exceptions=[],
            )

        def run_with_retry(self, func, *, max_retries=3, base_delay=1.0, label=""):
            return func()

        def process_batch(
            self,
            files,
            worker_fn,
            *,
            max_workers=None,
            future_timeout=None,
            progress_callback=None,
        ):
            results = []
            n = len(files)
            for i, f in enumerate(files):
                try:
                    results.append(worker_fn(f))
                except Exception:
                    results.append(None)
                if progress_callback:
                    progress_callback(i + 1, n)
            return results

        def create_progress_tracker(self, on_progress, total_files):
            processed = [0]
            skipped = [0]
            errors = [0]
            log_entries = []

            def _on_progress(n_skipped=0, n_errors=0, display_text="", log_text=""):
                processed[0] += 1
                skipped[0] += n_skipped
                errors[0] += n_errors
                log_entries.append(log_text)
                on_progress(
                    processed=processed[0],
                    total=total_files,
                    skipped=skipped[0],
                    errors=errors[0],
                    display_text=display_text,
                )

            return processed, skipped, errors, log_entries, _on_progress

    fp_base.BaseFileProcessor = BaseFileProcessorStub

    for name, mod in [
        ("audio_suite_shared", shared),
        ("audio_suite_shared.exceptions", exceptions_mod),
        ("audio_suite_shared.cli_dataclasses", cli_dc),
        ("audio_suite_shared.error_recovery", error_rec),
        ("audio_suite_shared.resource_manager", resource_mod),
        ("audio_suite_shared.tag_helper", tag_mod),
        ("audio_suite_shared.batch_undo", batch_mod),
        ("audio_suite_shared.file_processor_base", fp_base),
    ]:
        sys.modules[name] = mod


try:
    import audio_suite_shared  # noqa: F401
except ImportError:
    _make_shared_stub()

# ── Add silence_trimmer package to path ───────────────────────────────────────
sys.path.insert(0, "/tmp")

from silence_trimmer.core import file_processor  # noqa: E402
from silence_trimmer.core.trimmer import TrimResult, trim_and_fade  # noqa: E402
from silence_trimmer.utils.cli_args import (  # noqa: E402
    SilenceTrimmerArgs,
    parse,
    validate_args,
)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _make_audio(duration_ms: int = 2000, silence_ms: int = 300) -> "AudioSegment":
    """Return an AudioSegment with silence_ms of leading and trailing silence."""
    from pydub import AudioSegment

    silence_seg = AudioSegment.silent(duration=silence_ms)
    tone = AudioSegment.silent(duration=duration_ms)  # all-silent body for determinism
    return silence_seg + tone + silence_seg


def _make_pure_silent(duration_ms: int = 1000) -> "AudioSegment":
    from pydub import AudioSegment

    return AudioSegment.silent(duration=duration_ms)


def _make_slot_deps(n_slots: int = 4):
    """Return (slot_vars, slot_queue, lock, on_progress) for process_single_file."""
    slot_vars = [MagicMock() for _ in range(n_slots)]
    slot_queue: Queue = Queue()
    for i in range(n_slots):
        slot_queue.put(i)
    return slot_vars, slot_queue, threading.Lock(), MagicMock()


# ─────────────────────────────────────────────────────────────────────────────
# TrimResult — frozen dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimResult:
    def test_frozen_prevents_mutation(self) -> None:
        """TrimResult must be immutable per claude.md frozen dataclass mandate."""
        r = TrimResult(
            start_trim_ms=0,
            end_trim_ms=0,
            total_trim_ms=0,
            has_silence=False,
            trimmed=None,
            status="SKIP",
            action="No silence detected",
        )
        with pytest.raises((FrozenInstanceError, AttributeError)):
            r.status = "MUTATED"  # type: ignore[misc]

    def test_field_types_preserved(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="TRIMMED",
            action="ok",
        )
        assert r.start_trim_ms == 100
        assert r.end_trim_ms == 200
        assert r.total_trim_ms == 300
        assert r.has_silence is True
        assert r.status == "TRIMMED"

    def test_skip_action_string(self) -> None:
        r = TrimResult(
            start_trim_ms=0,
            end_trim_ms=0,
            total_trim_ms=0,
            has_silence=False,
            trimmed=None,
            status="SKIP",
            action="No silence detected",
        )
        assert r.action == "No silence detected"

    def test_trimmed_action_with_fades(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="TRIMMED",
            action="-100ms / -200ms + Fades",
        )
        assert "+ Fades" in r.action

    def test_trimmed_action_without_fades(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="TRIMMED",
            action="-100ms / -200ms",
        )
        assert "+ Fades" not in r.action

    def test_dry_run_action_string(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="DRY_RUN",
            action="Would trim 300ms",
        )
        assert "Would trim" in r.action


# ─────────────────────────────────────────────────────────────────────────────
# trim_and_fade — digital silence (no silence to detect)
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimAndFadeNoSilence:
    """Audio that has no detectable silence should be skipped."""

    def test_skip_status_when_no_silence(self) -> None:
        # 500 Hz sine approximation: use a non-silent segment
        # full silence returns full length — so force a "loud" segment
        import array

        from pydub import AudioSegment

        samples = array.array("h", [32000] * 8000)
        loud = AudioSegment(
            samples.tobytes(), frame_rate=8000, sample_width=2, channels=1
        )
        result = trim_and_fade(loud, threshold=-50, is_dry_run=False)
        assert result.status == "SKIP"
        assert result.has_silence is False
        assert result.trimmed is None
        assert result.total_trim_ms == 0

    def test_skip_returns_zero_trim_amounts(self) -> None:
        import array

        samples = array.array("h", [32000] * 8000)
        from pydub import AudioSegment

        loud = AudioSegment(
            samples.tobytes(), frame_rate=8000, sample_width=2, channels=1
        )
        result = trim_and_fade(loud, threshold=-50, is_dry_run=False)
        assert result.start_trim_ms == 0
        assert result.end_trim_ms == 0


# ─────────────────────────────────────────────────────────────────────────────
# trim_and_fade — silence detection
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimAndFadeWithSilence:
    def test_dry_run_does_not_produce_trimmed_audio(self) -> None:
        audio = _make_audio(duration_ms=500, silence_ms=200)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=True)
        if result.has_silence:
            assert result.trimmed is None
            assert result.status == "DRY_RUN"
            assert "Would trim" in result.action

    def test_live_run_produces_trimmed_audio(self) -> None:
        audio = _make_audio(duration_ms=500, silence_ms=200)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=False)
        if result.has_silence:
            assert result.trimmed is not None
            assert result.status == "TRIMMED"
            assert len(result.trimmed) < len(audio)

    def test_fade_applied_when_requested(self) -> None:
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        if result.has_silence:
            assert result.trimmed is not None
            assert "+ Fades" in result.action

    def test_apply_fade_field_is_true_when_requested(self) -> None:
        """`apply_fade` is the structured counterpart of the "+ Fades"
        action text, so consumers need not substring-match `action`.
        """
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        assert result.apply_fade is True

    def test_apply_fade_field_is_false_when_not_requested(self) -> None:
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=False, apply_fade=False)
        assert result.apply_fade is False

    def test_apply_fade_defaults_false_for_skipped_results(self) -> None:
        """The skip and dry-run paths leave apply_fade at its False default."""
        import array

        from pydub import AudioSegment

        loud = AudioSegment(
            array.array("h", [32000] * 8000).tobytes(),
            frame_rate=8000,
            sample_width=2,
            channels=1,
        )
        skipped = trim_and_fade(loud, threshold=-60, is_dry_run=False)
        assert skipped.status == "SKIP"
        assert skipped.apply_fade is False

        audio = _make_audio(duration_ms=500, silence_ms=200)
        dry = trim_and_fade(audio, threshold=-60, is_dry_run=True)
        assert dry.status == "DRY_RUN"
        assert dry.apply_fade is False

    def test_fade_not_applied_in_dry_run(self) -> None:
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=True,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        assert result.trimmed is None

    def test_total_trim_equals_start_plus_end(self) -> None:
        audio = _make_audio(duration_ms=500, silence_ms=200)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=True)
        assert result.total_trim_ms == result.start_trim_ms + result.end_trim_ms

    def test_pure_silence_produces_trim_covering_full_length(self) -> None:
        """All-silent audio: trim amounts sum to (at least) full duration."""
        audio = _make_pure_silent(duration_ms=500)
        result = trim_and_fade(audio, threshold=-10, is_dry_run=True)
        assert result.has_silence is True
        assert result.total_trim_ms > 0

    def test_fade_durations_longer_than_trimmed_segment_are_clamped(self) -> None:
        """Regression test: fade_in_ms/fade_out_ms exceeding the trimmed
        segment's length must be clamped to that length, not passed through
        to pydub as-is.

        pydub's AudioSegment.fade() does not clip an over-long fade — it
        computes a negative internal start offset instead, which silently
        lengthens and corrupts the output. Before the fix, applying the
        default 500ms/1000ms fades to an audio file with under ~1.5s of
        real content after trimming (e.g. short samples, podcast clips)
        would expand the exported file well beyond its correct length.
        """
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence_pad = AudioSegment.silent(duration=800)
        tone = Sine(440).to_audio_segment(duration=300)
        audio = silence_pad + tone + silence_pad

        result = trim_and_fade(
            audio,
            threshold=-50,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=500,
            fade_out_ms=1000,
        )

        assert result.status == "TRIMMED"
        assert result.trimmed is not None
        expected_len = len(audio) - result.start_trim_ms - result.end_trim_ms
        # Allow normal pydub ms-rounding slack, but the output must NOT be
        # inflated by hundreds of ms the way the unclamped bug produced.
        assert abs(len(result.trimmed) - expected_len) <= 5

    def test_fade_clamp_does_not_affect_fades_already_within_segment_length(
        self,
    ) -> None:
        """Clamping must be a no-op when the fade duration already fits —
        normal-length tracks must fade exactly as before."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence_pad = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=2000)
        audio = silence_pad + tone + silence_pad

        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        assert result.has_silence is True
        expected_len = len(audio) - result.start_trim_ms - result.end_trim_ms
        assert abs(len(result.trimmed) - expected_len) <= 5

    def test_fade_on_fully_silent_audio_does_not_raise(self) -> None:
        """Regression test: when the entire input is silence, the trimmed
        segment is zero-length. Clamping fade_in_ms/fade_out_ms to that
        length yields 0, and pydub's fade() treats duration=0 as falsy,
        raising TypeError instead of being a no-op. Fades of 0 must be
        skipped rather than passed through to pydub."""
        audio = _make_pure_silent(duration_ms=500)
        result = trim_and_fade(
            audio,
            threshold=-10,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=500,
            fade_out_ms=1000,
        )
        assert result.status == "TRIMMED"
        assert result.trimmed is not None
        assert len(result.trimmed) == 0

    def test_no_fade_action_does_not_contain_fades_string(self) -> None:
        """When apply_fade=False, action must not mention fades."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=500)
        audio = silence + tone + silence
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=False,
        )
        if result.has_silence:
            assert result.status == "TRIMMED"
            assert "+ Fades" not in result.action
            assert result.action.startswith("-")

    def test_trimmed_length_correct_without_fades(self) -> None:
        """Without fades, trimmed segment length must equal original minus
        detected trim amounts (within pydub ms-rounding slack)."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=1000)
        audio = silence + tone + silence
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=False,
        )
        if result.has_silence:
            expected = len(audio) - result.start_trim_ms - result.end_trim_ms
            assert abs(len(result.trimmed) - expected) <= 5

    def test_trimmed_length_correct_with_fades_within_bounds(self) -> None:
        """With fades that fit inside the trimmed segment, the total length
        must still match original minus trim amounts."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=2000)
        audio = silence + tone + silence
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        if result.has_silence:
            expected = len(audio) - result.start_trim_ms - result.end_trim_ms
            assert abs(len(result.trimmed) - expected) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# get_export_args (shared)
# ─────────────────────────────────────────────────────────────────────────────


class TestExportArgs:
    @pytest.mark.parametrize(
        "ext,expected_fmt",
        [
            (".mp3", "mp3"),
            (".flac", "flac"),
            (".ogg", "ogg"),
            (".m4a", "mp4"),
            (".opus", "opus"),
            (".wav", "wav"),
            (".aiff", "aiff"),
            (".aif", "aiff"),
        ],
    )
    def test_known_extensions(self, ext: str, expected_fmt: str) -> None:
        from audio_suite_shared.audio_formats import get_export_args

        fmt, params = get_export_args(ext)
        assert fmt == expected_fmt
        assert isinstance(params, list)

    def test_unknown_extension_falls_back_to_mp3(self) -> None:
        from audio_suite_shared.audio_formats import get_export_args

        fmt, params = get_export_args(".xyz")
        assert fmt == "mp3"

    def test_case_insensitive(self) -> None:
        from audio_suite_shared.audio_formats import get_export_args

        fmt_lower, _ = get_export_args(".mp3")
        fmt_upper, _ = get_export_args(".MP3")
        assert fmt_lower == fmt_upper

    def test_all_shared_supported_extensions_have_export_mapping(self) -> None:
        """Regression guard: every extension run_trimming() will scan for
        (audio_suite_shared.tag_helper.SUPPORTED_EXTENSIONS) must have a real
        pydub export mapping here — not the silent mp3 fallback. This is the
        exact gap that let WAV/AIFF files get mis-exported as MP3 data while
        keeping their original extension.
        """
        from audio_suite_shared.audio_formats import get_export_args
        from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

        for ext in SUPPORTED_EXTENSIONS:
            fmt, _ = get_export_args(ext)
            assert (ext, fmt) != (ext, "mp3") or ext == ".mp3", (
                f"{ext} has no explicit export mapping and silently "
                f"falls back to mp3 — this will corrupt the file."
            )


# ─────────────────────────────────────────────────────────────────────────────
# run_trimming — orchestration
# ─────────────────────────────────────────────────────────────────────────────


class TestRunTrimming:
    def _slot_setup(self):
        slot_vars = [MagicMock() for _ in range(4)]
        slot_queue: Queue = Queue()
        for i in range(4):
            slot_queue.put(i)
        return slot_vars, slot_queue

    def test_calls_on_error_when_no_audio_files(self, tmp_path) -> None:
        slot_vars, slot_queue = self._slot_setup()
        on_error = MagicMock()
        on_complete = MagicMock()
        on_progress = MagicMock()

        file_processor.run_trimming(
            dir_path=str(tmp_path),
            is_dry_run=True,
            threshold=-50,
            apply_fade=False,
            fade_in_ms=500,
            fade_out_ms=1000,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )
        on_error.assert_called_once()
        on_complete.assert_not_called()

    def test_calls_on_error_for_nonexistent_directory(self) -> None:
        slot_vars, slot_queue = self._slot_setup()
        on_error = MagicMock()
        on_complete = MagicMock()

        file_processor.run_trimming(
            dir_path="/nonexistent/path/xyz",
            is_dry_run=True,
            threshold=-50,
            apply_fade=False,
            fade_in_ms=500,
            fade_out_ms=1000,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=MagicMock(),
            on_complete=on_complete,
            on_error=on_error,
        )
        on_error.assert_called_once()

    def test_calls_on_complete_after_processing(self, tmp_path) -> None:
        """Create a real minimal MP3 stub and verify on_complete is invoked."""
        # Write a tiny valid-ish placeholder; process_single_file will error
        # and count as an error entry — on_complete must still be called.
        fake_mp3 = tmp_path / "track.mp3"
        fake_mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)  # plausible MP3 header bytes

        slot_vars, slot_queue = self._slot_setup()
        on_complete = MagicMock()
        on_error = MagicMock()

        with patch.object(file_processor, "process_single_file") as mock_psf:

            def _fake_worker(*args, **kwargs):
                on_progress_cb = args[
                    11
                ]  # positional: lock=args[10], on_progress=args[11]
                lock = args[10]
                with lock:
                    on_progress_cb(
                        n_skipped=0, n_errors=0, display_text="ok", log_text="ok\n"
                    )

            mock_psf.side_effect = _fake_worker

            file_processor.run_trimming(
                dir_path=str(tmp_path),
                is_dry_run=True,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                on_progress=MagicMock(),
                on_complete=on_complete,
                on_error=on_error,
            )

        on_complete.assert_called_once()
        on_error.assert_not_called()

    def test_raising_worker_logged_and_batch_completes(self, tmp_path, caplog) -> None:
        """A worker that raises out of process_single_file must be mapped and
        logged as a per-file error by process_batch instead of aborting the
        pool — the batch must still reach on_complete."""
        fake_mp3 = tmp_path / "track.mp3"
        fake_mp3.write_bytes(b"\xff\xfb\x90\x00" * 100)

        slot_vars, slot_queue = self._slot_setup()
        on_complete = MagicMock()
        on_error = MagicMock()

        with (
            patch.object(
                file_processor,
                "process_single_file",
                side_effect=RuntimeError("worker boom"),
            ),
            caplog.at_level(
                "ERROR",
                logger="audio_suite.audio_suite_shared.file_processor_base",
            ),
        ):
            file_processor.run_trimming(
                dir_path=str(tmp_path),
                is_dry_run=True,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                on_progress=MagicMock(),
                on_complete=on_complete,
                on_error=on_error,
            )

        on_complete.assert_called_once()
        on_error.assert_not_called()
        assert "worker boom" in caplog.text

    def test_live_run_records_single_real_path_snapshot_under_batch(
        self,
        tmp_path,
    ) -> None:
        """A live run records exactly one undo entry pointing at the real
        file path (never the temp staging path)."""
        from audio_suite_shared.batch_undo import BatchUndoLog, active_batch

        audio_file = tmp_path / "tone.wav"
        audio = _make_audio(duration_ms=2000, silence_ms=300)
        audio.export(str(audio_file), format="wav")

        undo_db = tmp_path / "undo.db"
        handler = MagicMock()
        handler.get_raw_tags.return_value = {}
        instance = MagicMock()
        instance.get_handler.return_value = handler
        factory = MagicMock()
        factory.get_handler.return_value = handler
        factory.return_value = instance

        slot_vars, slot_queue = self._slot_setup()
        on_error = MagicMock()
        on_complete = MagicMock()

        with (
            patch("audio_suite_shared.tag_helper_base.TagHandlerFactory", factory),
            patch("audio_suite_shared.tag_helper_reader.TagHandlerFactory", factory),
            patch("audio_suite_shared.tag_helper_writer.TagHandlerFactory", factory),
        ):
            with active_batch("silence_trimmer", "tag_edit", db_path=str(undo_db)):
                file_processor.run_trimming(
                    dir_path=str(tmp_path),
                    is_dry_run=False,
                    threshold=-50,
                    apply_fade=False,
                    fade_in_ms=25,
                    fade_out_ms=25,
                    slot_vars=slot_vars,
                    slot_queue=slot_queue,
                    on_progress=MagicMock(),
                    on_complete=on_complete,
                    on_error=on_error,
                )

        on_error.assert_not_called()
        on_complete.assert_called_once()

        with BatchUndoLog(db_path=str(undo_db)) as log:
            batches = log.list_batches(limit=10)
            assert len(batches) == 1
            records = log.get_batch_records(batches[0].batch_id)
            assert len(records) == 1
            assert records[0].file_path == str(audio_file)
            assert records[0].operation == "trim_edit"


# ─────────────────────────────────────────────────────────────────────────────
# cli_args — validate_args
# ─────────────────────────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_valid_args_produce_no_errors(self, tmp_path) -> None:
        args = SilenceTrimmerArgs(folder_path=str(tmp_path), threshold=-50)
        assert validate_args(args) == []

    def test_nonexistent_folder_produces_error(self) -> None:
        args = SilenceTrimmerArgs(folder_path="/no/such/place", threshold=-50)
        errors = validate_args(args)
        assert any("does not exist" in e for e in errors)

    def test_threshold_too_high_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-5)
        errors = validate_args(args)
        assert any("threshold" in e for e in errors)

    def test_threshold_too_low_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-85)
        errors = validate_args(args)
        assert any("threshold" in e for e in errors)

    def test_threshold_boundary_low_valid(self) -> None:
        args = SilenceTrimmerArgs(threshold=-80)
        errors = [e for e in validate_args(args) if "threshold" in e]
        assert errors == []

    def test_threshold_boundary_high_valid(self) -> None:
        args = SilenceTrimmerArgs(threshold=-20)
        errors = [e for e in validate_args(args) if "threshold" in e]
        assert errors == []

    def test_negative_fade_in_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_in_ms=-1)
        errors = validate_args(args)
        assert any("Fade-in" in e for e in errors)

    def test_excessive_fade_out_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_out_ms=20000)
        errors = validate_args(args)
        assert any("Fade-out" in e for e in errors)

    def test_none_fades_are_valid(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_in_ms=None, fade_out_ms=None)
        errors = [e for e in validate_args(args) if "fade" in e.lower()]
        assert errors == []

    # ── Regression: CLI fade-duration validation must match the GUI's actual
    # bounds (fade-in 100-3000ms, fade-out 100-5000ms), not an unrelated
    # 0-10000ms range that previously let CLI launches pass validation here
    # only to be silently rejected later by app.py's business-rule check. ──

    def test_fade_in_above_3000_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_in_ms=3001)
        errors = validate_args(args)
        assert any("Fade-in" in e for e in errors)

    def test_fade_in_below_100_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_in_ms=99)
        errors = validate_args(args)
        assert any("Fade-in" in e for e in errors)

    def test_fade_in_boundary_values_valid(self) -> None:
        for value in (100, 500, 3000):
            args = SilenceTrimmerArgs(threshold=-50, fade_in_ms=value)
            errors = [e for e in validate_args(args) if "Fade-in" in e]
            assert errors == [], f"fade_in_ms={value} should be valid"

    def test_fade_out_above_5000_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_out_ms=5001)
        errors = validate_args(args)
        assert any("Fade-out" in e for e in errors)

    def test_fade_out_below_100_produces_error(self) -> None:
        args = SilenceTrimmerArgs(threshold=-50, fade_out_ms=99)
        errors = validate_args(args)
        assert any("Fade-out" in e for e in errors)

    def test_fade_out_boundary_values_valid(self) -> None:
        for value in (100, 1000, 5000):
            args = SilenceTrimmerArgs(threshold=-50, fade_out_ms=value)
            errors = [e for e in validate_args(args) if "Fade-out" in e]
            assert errors == [], f"fade_out_ms={value} should be valid"

    def test_fade_in_value_previously_accepted_by_old_0_to_10000_range_now_rejected(
        self,
    ) -> None:
        """8000ms passed the old (buggy) 0-10000ms CLI check but would later
        fail app.py's 100-3000ms business rule, silently aborting auto-start.
        It must now be rejected at CLI-validation time instead."""
        args = SilenceTrimmerArgs(threshold=-50, fade_in_ms=8000)
        errors = validate_args(args)
        assert any("Fade-in" in e for e in errors)

    def test_path_is_file_not_directory_produces_error(self, tmp_path) -> None:
        """When folder_path points at a file (not a directory), validate_args
        must return a 'not a directory' error."""
        f = tmp_path / "not_a_dir.txt"
        f.write_text("")
        args = SilenceTrimmerArgs(folder_path=str(f), threshold=-50)
        errors = validate_args(args)
        assert any("not a directory" in e for e in errors)

    def test_threshold_error_reported_even_with_empty_folder_path(self) -> None:
        """validate_args must still check the threshold when folder_path is
        empty (the default)."""
        args = SilenceTrimmerArgs(folder_path="", threshold=-5)
        errors = validate_args(args)
        assert any("threshold" in e for e in errors)


# ─────────────────────────────────────────────────────────────────────────────
# cli_args — parse()
# ─────────────────────────────────────────────────────────────────────────────


class TestParse:
    def test_no_args_returns_defaults(self) -> None:
        args = parse(["tool"])
        assert args.folder_path == ""
        assert args.threshold == -50
        assert args.apply_fade is False

    def test_folder_path_set(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_live_flag(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_dry_flag(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--dry"])
        assert args.live_mode is False

    def test_fade_flag(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--fade"])
        assert args.apply_fade is True

    def test_no_fade_flag(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--no-fade"])
        assert args.apply_fade is False

    def test_fade_in_out_parsed(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--fade-in", "300", "--fade-out", "600"])
        assert args.fade_in_ms == 300
        assert args.fade_out_ms == 600

    def test_threshold_parsed_from_negative_int(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "-40"])
        assert args.threshold == -40

    def test_invalid_threshold_raises_system_exit(self, tmp_path) -> None:
        with pytest.raises(SystemExit):
            parse(["tool", str(tmp_path), "-5"])  # above -20 bound

    def test_auto_end_flag(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--end"])
        assert args.auto_end is True

    def test_auto_start_flag(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--start"])
        assert args.auto_start is True

    def test_unknown_flags_ignored(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--unknown-flag"])
        assert args.folder_path == str(tmp_path)
        assert args.threshold == -50

    def test_invalid_fade_in_value_ignored(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--fade-in", "not-a-number"])
        assert args.fade_in_ms is None

    def test_invalid_fade_out_value_ignored(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "--fade-out", "not-a-number"])
        assert args.fade_out_ms is None

    def test_non_integer_threshold_ignored(self, tmp_path) -> None:
        args = parse(["tool", str(tmp_path), "abc"])
        assert args.threshold == -50

    def test_mixed_flags_and_args_parse_correctly(self, tmp_path) -> None:
        args = parse(
            [
                "tool",
                str(tmp_path),
                "--live",
                "--fade",
                "--fade-in",
                "250",
                "--fade-out",
                "800",
                "--start",
                "--end",
            ]
        )
        assert args.live_mode is True
        assert args.apply_fade is True
        assert args.fade_in_ms == 250
        assert args.fade_out_ms == 800
        assert args.auto_start is True
        assert args.auto_end is True


# ─────────────────────────────────────────────────────────────────────────────
# process_single_file — direct worker tests with real WAV files
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessSingleFile:
    """Direct tests of process_single_file with real WAV files on disk.

    These tests exercise the internal _trim_file closure, temp-file lifecycle,
    tag round-trip, and error-handling paths that the orchestration-level
    tests (TestRunTrimming) intentionally mock away.
    """

    def test_dry_run_preserves_file_on_disk(self, tmp_path) -> None:
        """Dry run must not modify the original file."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)
        audio = silence + tone + silence
        file_path = tmp_path / "test.wav"
        audio.export(str(file_path), format="wav")
        original_bytes = file_path.read_bytes()

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()
        try:
            file_processor.process_single_file(
                name="test.wav",
                dir_path=str(tmp_path),
                is_dry_run=True,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                temp_dir=temp_dir_obj,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                lock=lock,
                on_progress=on_progress,
            )
        finally:
            shutil.rmtree(temp_dir_obj, ignore_errors=True)

        assert file_path.read_bytes() == original_bytes
        on_progress.assert_called_once()

    def test_live_run_with_silence_trims_file_shorter(self, tmp_path) -> None:
        """Live run: file with leading/trailing silence must be overwritten
        with a shorter trimmed version."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)
        audio = silence + tone + silence
        file_path = tmp_path / "test.wav"
        audio.export(str(file_path), format="wav")
        original_size = len(file_path.read_bytes())

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()
        try:
            file_processor.process_single_file(
                name="test.wav",
                dir_path=str(tmp_path),
                is_dry_run=False,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                temp_dir=temp_dir_obj,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                lock=lock,
                on_progress=on_progress,
            )
        finally:
            shutil.rmtree(temp_dir_obj, ignore_errors=True)

        trimmed_size = len(file_path.read_bytes())
        assert trimmed_size < original_size, (
            f"Trimmed file ({trimmed_size}B) should be smaller "
            f"than original ({original_size}B)"
        )

    def test_live_run_without_silence_skips_and_preserves_file(
        self,
        tmp_path,
    ) -> None:
        """Live run on audio with no silence: SKIP, file unchanged."""
        from pydub.generators import Sine

        tone = Sine(440).to_audio_segment(duration=800)
        file_path = tmp_path / "test.wav"
        tone.export(str(file_path), format="wav")
        original_bytes = file_path.read_bytes()

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()
        try:
            file_processor.process_single_file(
                name="test.wav",
                dir_path=str(tmp_path),
                is_dry_run=False,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                temp_dir=temp_dir_obj,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                lock=lock,
                on_progress=on_progress,
            )
        finally:
            shutil.rmtree(temp_dir_obj, ignore_errors=True)

        assert file_path.read_bytes() == original_bytes
        call_kwargs = on_progress.call_args.kwargs
        assert call_kwargs.get("n_skipped") == 1

    def test_slot_returned_to_queue_after_processing(self, tmp_path) -> None:
        """Slot must be put back in the queue when processing completes."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)
        audio = silence + tone + silence
        file_path = tmp_path / "test.wav"
        audio.export(str(file_path), format="wav")

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()
        # Drain all but one slot
        for _ in range(3):
            slot_queue.get()
        assert slot_queue.qsize() == 1
        try:
            file_processor.process_single_file(
                name="test.wav",
                dir_path=str(tmp_path),
                is_dry_run=True,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                temp_dir=temp_dir_obj,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                lock=lock,
                on_progress=on_progress,
            )
        finally:
            shutil.rmtree(temp_dir_obj, ignore_errors=True)

        # After processing, the slot must be returned
        assert slot_queue.qsize() == 1

    def test_error_during_processing_reported_as_skip(self, tmp_path) -> None:
        """When _trim_file raises, the stub recovery manager returns SKIP,
        so on_progress must be called with n_skipped=1."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)
        audio = silence + tone + silence
        file_path = tmp_path / "test.wav"
        audio.export(str(file_path), format="wav")

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()

        with patch.object(
            file_processor.AudioSegment,
            "from_file",
            side_effect=OSError("corrupted file"),
        ):
            try:
                file_processor.process_single_file(
                    name="test.wav",
                    dir_path=str(tmp_path),
                    is_dry_run=False,
                    threshold=-50,
                    apply_fade=False,
                    fade_in_ms=500,
                    fade_out_ms=1000,
                    temp_dir=temp_dir_obj,
                    slot_vars=slot_vars,
                    slot_queue=slot_queue,
                    lock=lock,
                    on_progress=on_progress,
                )
            finally:
                shutil.rmtree(temp_dir_obj, ignore_errors=True)

        on_progress.assert_called_once()
        call_kwargs = on_progress.call_args.kwargs
        # OSError is mapped to RETRY by get_recovery_action → n_errors=1
        assert call_kwargs.get("n_skipped") == 0
        assert call_kwargs.get("n_errors") == 1
        assert "corrupted" in call_kwargs.get("display_text", "")

    def test_error_with_non_skip_recovery_reports_n_errors(self, tmp_path) -> None:
        """When get_recovery_action returns RETRY, on_progress is called
        with n_errors=1 (the else branch)."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)
        audio = silence + tone + silence
        file_path = tmp_path / "test.wav"
        audio.export(str(file_path), format="wav")

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()

        with (
            patch.object(
                file_processor,
                "get_recovery_action",
                return_value="RETRY",
            ),
            patch.object(
                file_processor.AudioSegment,
                "from_file",
                side_effect=OSError("corrupted file"),
            ),
        ):
            try:
                file_processor.process_single_file(
                    name="test.wav",
                    dir_path=str(tmp_path),
                    is_dry_run=False,
                    threshold=-50,
                    apply_fade=False,
                    fade_in_ms=500,
                    fade_out_ms=1000,
                    temp_dir=temp_dir_obj,
                    slot_vars=slot_vars,
                    slot_queue=slot_queue,
                    lock=lock,
                    on_progress=on_progress,
                    retry_fn=lambda fn: fn(),
                )
            finally:
                shutil.rmtree(temp_dir_obj, ignore_errors=True)

        on_progress.assert_called_once()
        call_kwargs = on_progress.call_args.kwargs
        assert call_kwargs.get("n_errors") == 1
        assert call_kwargs.get("n_skipped") == 0


# ─────────────────────────────────────────────────────────────────────────────
# run_trimming — integration tests with real WAV files
# ─────────────────────────────────────────────────────────────────────────────


class TestRunTrimmingIntegration:
    """End-to-end tests of run_trimming driving real process_single_file
    workers with actual WAV files on disk — no mocking of the worker."""

    def test_dry_run_end_to_end_processes_all_files(self, tmp_path) -> None:
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)

        f1 = tmp_path / "track1.wav"
        f2 = tmp_path / "track2.wav"
        (silence + tone + silence).export(str(f1), format="wav")
        tone.export(str(f2), format="wav")

        slot_vars = [MagicMock() for _ in range(4)]
        slot_queue: Queue = Queue()
        for i in range(4):
            slot_queue.put(i)
        on_progress = MagicMock()
        on_complete = MagicMock()
        on_error = MagicMock()

        file_processor.run_trimming(
            dir_path=str(tmp_path),
            is_dry_run=True,
            threshold=-50,
            apply_fade=False,
            fade_in_ms=500,
            fade_out_ms=1000,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )

        on_complete.assert_called_once()
        on_error.assert_not_called()
        assert f1.exists()
        assert f2.exists()

    def test_live_run_trims_silence_from_real_files(self, tmp_path) -> None:
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=500)
        tone = Sine(440).to_audio_segment(duration=500)

        f1 = tmp_path / "with_silence.wav"
        (silence + tone + silence).export(str(f1), format="wav")
        f1_original_size = len(f1.read_bytes())

        f2 = tmp_path / "no_silence.wav"
        tone.export(str(f2), format="wav")
        f2_original_bytes = f2.read_bytes()

        slot_vars = [MagicMock() for _ in range(4)]
        slot_queue: Queue = Queue()
        for i in range(4):
            slot_queue.put(i)
        on_progress = MagicMock()
        on_complete = MagicMock()
        on_error = MagicMock()

        file_processor.run_trimming(
            dir_path=str(tmp_path),
            is_dry_run=False,
            threshold=-50,
            apply_fade=False,
            fade_in_ms=500,
            fade_out_ms=1000,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )

        on_complete.assert_called_once()
        on_error.assert_not_called()
        # File with silence must be trimmed (smaller)
        f1_trimmed_size = len(f1.read_bytes())
        assert f1_trimmed_size < f1_original_size, (
            f"Trimmed file ({f1_trimmed_size}B) should be smaller "
            f"than original ({f1_original_size}B)"
        )
        # File without silence must be unchanged
        assert f2.read_bytes() == f2_original_bytes

    def test_empty_directory_reports_error(self, tmp_path) -> None:
        slot_vars = [MagicMock() for _ in range(4)]
        slot_queue: Queue = Queue()
        for i in range(4):
            slot_queue.put(i)
        on_progress = MagicMock()
        on_complete = MagicMock()
        on_error = MagicMock()

        file_processor.run_trimming(
            dir_path=str(tmp_path),
            is_dry_run=True,
            threshold=-50,
            apply_fade=False,
            fade_in_ms=500,
            fade_out_ms=1000,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )

        on_error.assert_called_once()
        on_complete.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# process_single_file — multi-format round-trip E2E (FLAC / OGG / M4A / Opus)
# ─────────────────────────────────────────────────────────────────────────────


class TestMultiFormatRoundTrip:
    """Live-run round-trips across the non-MP3 formats the tool supports.

    Each test drives the real ``process_single_file`` path against a genuine
    file in the target format and verifies the ACTUAL transformed outcome:
    the exported result must decode back in the same format, shortened to
    roughly the tone length, and must never be silently re-encoded as MP3
    data while keeping its original extension (the WAV/AIFF corruption class
    this suite guards against).
    """

    @pytest.mark.parametrize("ext", [".flac", ".ogg", ".m4a", ".opus"])
    def test_live_run_trims_and_preserves_format(self, ext: str, tmp_path) -> None:
        from pydub import AudioSegment
        from pydub.generators import Sine

        from audio_suite_shared.audio_formats import get_export_args

        silence = AudioSegment.silent(duration=400)
        tone = Sine(440).to_audio_segment(duration=600)
        # 400ms silence + 600ms tone + 400ms silence = 1400ms total.
        source = silence + tone + silence
        # The exact export mapping the tool uses for this extension.
        fmt, params = get_export_args(ext)

        file_path = tmp_path / f"track{ext}"
        source.export(str(file_path), format=fmt, parameters=params)
        original_len = len(AudioSegment.from_file(str(file_path)))

        slot_vars, slot_queue, lock, on_progress = _make_slot_deps()
        temp_dir_obj = tempfile.mkdtemp()
        try:
            file_processor.process_single_file(
                name=f"track{ext}",
                dir_path=str(tmp_path),
                is_dry_run=False,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                temp_dir=temp_dir_obj,
                slot_vars=slot_vars,
                slot_queue=slot_queue,
                lock=lock,
                on_progress=on_progress,
            )
        finally:
            shutil.rmtree(temp_dir_obj, ignore_errors=True)

        # Decode the result and measure it — not read back internal state.
        result = AudioSegment.from_file(str(file_path))
        # Lossy codecs (AAC, Opus) add a small encoder delay on decode.
        assert abs(len(result) - 600) < 250, (
            f"{ext}: trimmed duration {len(result)}ms should be ~600ms "
            f"(source was {original_len}ms)"
        )
        assert len(result) < original_len - 200, (
            f"{ext}: output {len(result)}ms is not shorter than source {original_len}ms"
        )
        assert len(result) > 0

        call_kwargs = on_progress.call_args.kwargs
        assert call_kwargs.get("n_skipped") == 0
        assert call_kwargs.get("n_errors") == 0
        assert "TRIMMED" in call_kwargs.get("display_text", "")
