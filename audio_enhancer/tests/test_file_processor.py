"""
tests/test_file_processor.py
Regression tests for core/file_processor.py's _after_file()/run_enhancement()
orchestration logic.

Background
----------
Prior to this fix, `_after_file` discarded the correct, pre-built
`display_text` on SKIPPED/FAILED results (e.g. "[SKIP] track.mp3: file
not found") and instead rebuilt a display string from `result.source.name`
and `result.error_message` — both of which are empty on those paths,
since only `display_text` is populated there (see ProcessingResult
docstring in core/models.py). This produced a bare "[ERROR]   " string
with no filename or message, and also counted SKIPPED results as errors.

These tests drive `run_enhancement` end-to-end with `find_audio_files`,
`inspect`, and `process_file` patched, so they exercise the real
threaded worker / lock / callback path rather than calling a private
closure directly.

Run with:
    pytest tests/test_file_processor.py -v
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from unittest.mock import patch

from audio_enhancer.core import file_processor
from audio_enhancer.core.models import (
    AudioFileInfo,
    EnhancementParams,
    JobStatus,
    ProcessingResult,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    AudioFileNotFoundError,
    AudioPermissionError,
    user_message_for,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(
    files: list[Path],
    process_file_side_effect,
    direct_retry: bool = False,
    is_dry_run: bool = False,
) -> dict:
    """Run run_enhancement synchronously and collect all callback data.

    Args:
        files: Fake list of audio file paths to "discover".
        process_file_side_effect: Callable(info, params, output_dir,
            on_progress) -> ProcessingResult, or one that raises, used as
            the mocked process_file's side_effect.
        direct_retry: When True, unwrap run_with_retry to call the worker
            once so the retry backoff sleep is skipped (deterministic tests).
        is_dry_run: Forwarded to run_enhancement's is_dry_run parameter.

    Returns:
        dict with keys: progress_calls (list of kwargs dicts from each
        on_progress call), complete_kwargs (kwargs from the on_complete
        call), error_calls (list of error message strings from on_error).
    """
    progress_calls: list[dict] = []
    complete_kwargs: dict = {}
    error_calls: list[str] = []

    def on_progress(**kwargs) -> None:
        progress_calls.append(kwargs)

    def on_complete(**kwargs) -> None:
        complete_kwargs.update(kwargs)

    def on_error(message: str) -> None:
        error_calls.append(message)

    slot_vars = [_FakeVar() for _ in range(DEFAULT_MAX_WORKERS)]
    slot_queue: Queue = Queue()
    for i in range(DEFAULT_MAX_WORKERS):
        slot_queue.put(i)

    from contextlib import ExitStack

    retry_patch = (
        patch.object(
            file_processor.AudioEnhancerProcessor,
            "run_with_retry",
            side_effect=lambda fn, **_kw: fn(),
        )
        if direct_retry
        else None
    )

    with ExitStack() as stack:
        stack.enter_context(
            patch.object(file_processor, "find_audio_files", return_value=files)
        )
        stack.enter_context(
            patch.object(
                file_processor,
                "inspect",
                side_effect=lambda p: AudioFileInfo(path=p),
            )
        )
        stack.enter_context(
            patch.object(
                file_processor, "process_file", side_effect=process_file_side_effect
            )
        )
        if retry_patch is not None:
            stack.enter_context(retry_patch)

        file_processor.run_enhancement(
            source_path=Path("/fake/source"),
            output_dir=Path("/fake/output"),
            params=EnhancementParams(),
            is_dry_run=is_dry_run,
            slot_vars=slot_vars,
            slot_queue=slot_queue,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )

    return {
        "progress_calls": progress_calls,
        "complete_kwargs": complete_kwargs,
        "error_calls": error_calls,
    }


class _FakeVar:
    """Minimal stand-in for a tk.StringVar (no real Tk needed in tests)."""

    def __init__(self) -> None:
        self._value = ""

    def set(self, value: str) -> None:
        self._value = value

    def get(self) -> str:
        return self._value


# ── Tests: the core bug ──────────────────────────────────────────────────────


def test_skipped_file_keeps_its_display_text() -> None:
    """A SKIPPED result's pre-built display_text must reach on_progress
    unmodified — not be overwritten with an empty "[ERROR]   " string."""

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        raise AudioFileNotFoundError("vanished.mp3 not found", path="vanished.mp3")

    out = _run([Path("vanished.mp3")], fake_process_file)

    assert len(out["progress_calls"]) == 1
    call = out["progress_calls"][0]
    expected = f"[SKIP] vanished.mp3: {user_message_for(AudioFileNotFoundError('x'))}"
    assert call["display_text"] == expected


def test_skipped_file_is_not_counted_as_an_error() -> None:
    """Skips must not inflate the `errors` counter — they are a distinct,
    non-fatal outcome per the user guide and ProcessingResult semantics."""

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        raise AudioFileNotFoundError("vanished.mp3 not found", path="vanished.mp3")

    out = _run([Path("vanished.mp3")], fake_process_file)

    assert out["complete_kwargs"]["errors"] == 0
    assert out["complete_kwargs"]["done"] == 0
    assert out["complete_kwargs"]["total"] == 1
    # The skipped result must still be present in `results` for the caller
    # (app.py's log writer) to render correctly.
    results = out["complete_kwargs"]["results"]
    assert len(results) == 1
    assert results[0].status == JobStatus.SKIPPED
    assert "vanished.mp3" in results[0].display_text


def test_failed_file_keeps_its_display_text_and_counts_as_error() -> None:
    """A genuinely FAILED (non-skippable) result must keep its own
    display_text and must still count toward `errors`."""

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        raise AudioPermissionError("locked.mp3 permission denied", path="locked.mp3")

    out = _run([Path("locked.mp3")], fake_process_file)

    call = out["progress_calls"][0]
    expected = f"[ERROR] locked.mp3: {user_message_for(AudioPermissionError('x'))}"
    assert call["display_text"] == expected
    assert out["complete_kwargs"]["errors"] == 1

    results = out["complete_kwargs"]["results"]
    assert results[0].status == JobStatus.FAILED


def test_done_file_display_text_built_from_result_fields() -> None:
    """A successful (DONE) result's display is built from the real
    source name / gain / tags_copied fields, as before — this path was
    not broken and must not regress."""

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        return ProcessingResult(
            source=Path("good.mp3"),
            status=JobStatus.DONE,
            rms_before_db=-20.0,
            rms_after_db=-14.0,
            tags_copied=5,
        )

    out = _run([Path("good.mp3")], fake_process_file)

    call = out["progress_calls"][0]
    assert call["display_text"] == "[DONE] good.mp3  +6.0 dB  tags:5"
    assert out["complete_kwargs"]["done"] == 1
    assert out["complete_kwargs"]["errors"] == 0


def test_run_enhancement_dry_run_flag_reaches_process_file() -> None:
    """Dry Run mode must forward is_dry_run so process_file skips writes —
    otherwise Dry Run would overwrite source files in in-place runs."""

    seen: list[bool] = []

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        seen.append(dry_run)
        return ProcessingResult(
            source=Path("good.mp3"),
            status=JobStatus.DONE,
            rms_before_db=-20.0,
            rms_after_db=-14.0,
            tags_copied=5,
        )

    _run([Path("good.mp3")], fake_process_file, is_dry_run=True)

    assert seen == [True]


def test_run_enhancement_defaults_to_write_mode() -> None:
    """is_dry_run must default to False so normal runs still write."""

    seen: list[bool] = []

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        seen.append(dry_run)
        return ProcessingResult(
            source=Path("good.mp3"),
            status=JobStatus.DONE,
            rms_before_db=-20.0,
            rms_after_db=-14.0,
            tags_copied=5,
        )

    _run([Path("good.mp3")], fake_process_file)

    assert seen == [False]


def test_mixed_batch_counts_done_skipped_and_failed_independently() -> None:
    """processed == done + errors + skipped, and skipped is excluded
    from errors, across a batch with all three outcomes."""

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        name = info.path.name
        if name == "good.mp3":
            return ProcessingResult(
                source=Path(name),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=2,
            )
        if name == "vanished.mp3":
            raise AudioFileNotFoundError(f"{name} not found", path=name)
        if name == "locked.mp3":
            raise AudioPermissionError(f"{name} permission denied", path=name)
        raise AssertionError(f"unexpected file in test: {name}")

    files = [Path("good.mp3"), Path("vanished.mp3"), Path("locked.mp3")]
    out = _run(files, fake_process_file)

    assert out["complete_kwargs"]["total"] == 3
    assert out["complete_kwargs"]["done"] == 1
    assert out["complete_kwargs"]["errors"] == 1  # only locked.mp3

    results = out["complete_kwargs"]["results"]
    statuses = {r.status for r in results}
    assert statuses == {JobStatus.DONE, JobStatus.SKIPPED, JobStatus.FAILED}

    skipped = next(r for r in results if r.status == JobStatus.SKIPPED)
    assert "vanished.mp3" in skipped.display_text
    failed = next(r for r in results if r.status == JobStatus.FAILED)
    assert "locked.mp3" in failed.display_text


# ── Tests: run_enhancement guard branches ──────────────────────────────────


def test_worker_audio_suite_error_counts_as_failure() -> None:
    """A generic AudioSuiteError escaping the worker (caught, not retried)
    must surface as a FAILED result counting toward `errors`."""

    from audio_suite_shared.exceptions import AudioSuiteError

    class _ConcreteError(AudioSuiteError):
        pass

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        raise _ConcreteError("boom")

    out = _run([Path("bad.mp3")], fake_process_file, direct_retry=True)

    call = out["progress_calls"][0]
    assert call["errors"] == 1
    assert "[ERROR] bad.mp3:" in call["display_text"]
    assert out["complete_kwargs"]["errors"] == 1
    assert out["complete_kwargs"]["results"][0].status == JobStatus.FAILED


def test_worker_oserror_maps_to_failure_after_retries() -> None:
    """An unexpected OSError during enhancement is mapped through
    map_to_audio_error and surfaced as a FAILED result (unwrapped retry so
    the backoff sleep is skipped)."""

    def fake_process_file(info, params, output_dir, on_progress=None, dry_run=False):
        raise OSError("disk io")

    out = _run([Path("io.mp3")], fake_process_file, direct_retry=True)

    call = out["progress_calls"][0]
    assert call["errors"] == 1
    assert "[ERROR] io.mp3:" in call["display_text"]
    assert out["complete_kwargs"]["errors"] == 1
    assert out["complete_kwargs"]["results"][0].status == JobStatus.FAILED


def _collect_signals() -> tuple[list[dict], dict, list[str]]:
    progress_calls: list[dict] = []
    complete_kwargs: dict = {}
    error_calls: list[str] = []

    def on_progress(**kw) -> None:
        progress_calls.append(kw)

    def on_complete(**kw) -> None:
        complete_kwargs.update(kw)

    def on_error(message: str) -> None:
        error_calls.append(message)

    return progress_calls, complete_kwargs, error_calls


def _call_run(
    files_return,
    on_error_message: str | None = None,
    find_raises: OSError | None = None,
) -> dict:
    """Invoke run_enhancement, wrapping the callback plumbing."""

    progress_calls, complete_kwargs, error_calls = _collect_signals()

    def on_progress(**kw) -> None:
        progress_calls.append(kw)

    def on_complete(**kw) -> None:
        complete_kwargs.update(kw)

    def on_error(message: str) -> None:
        error_calls.append(message)

    files = files_return

    def _find(path):
        if find_raises is not None:
            raise find_raises
        return files

    with (
        patch.object(file_processor, "find_audio_files", side_effect=_find),
        patch.object(
            file_processor, "inspect", side_effect=lambda p: AudioFileInfo(path=p)
        ),
        patch.object(
            file_processor,
            "process_file",
            return_value=ProcessingResult(source=Path("x.mp3"), status=JobStatus.DONE),
        ),
    ):
        file_processor.run_enhancement(
            source_path=Path("/fake/source"),
            output_dir=Path("/fake/output"),
            params=EnhancementParams(),
            slot_vars=[_FakeVar()],
            slot_queue=Queue(),
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )
    return {
        "progress_calls": progress_calls,
        "complete_kwargs": complete_kwargs,
        "error_calls": error_calls,
    }


def test_run_enhancement_oserror_on_discovery_calls_on_error() -> None:
    out = _call_run(files_return=[], find_raises=OSError("denied"))
    assert len(out["error_calls"]) == 1
    # Path rendering (slashes) is platform-dependent; assert the stable prefix.
    assert out["error_calls"][0].startswith("Error: Cannot access directory")
    assert out["progress_calls"] == []


def test_run_enhancement_no_files_calls_on_error() -> None:
    out = _call_run(files_return=[])
    assert out["error_calls"] == [
        "No supported audio files found at the selected path."
    ]


# ── Tests: process_single_file ──────────────────────────────────────────────


class TestProcessSingleFile:
    """Covers audio_enhancer/core/file_processor.py's process_single_file().

    Dispatches a single file through inspect -> process_file and reports the
    outcome via the standard on_progress callback.  Every branch (DONE,
    ERROR result, per-exception skip/error handling) is exercised here.
    """

    def _capture(self, name: str = "track.mp3", **process_kwargs):
        import threading
        from unittest.mock import MagicMock

        calls: list[dict] = []

        def on_progress(**kw) -> None:
            calls.append(kw)

        info = AudioFileInfo(path=Path("/base") / name)
        pf_mock = MagicMock()
        for key, value in process_kwargs.items():
            setattr(pf_mock, key, value)

        with (
            patch.object(file_processor, "inspect", return_value=info),
            patch.object(file_processor, "process_file", pf_mock),
        ):
            file_processor.process_single_file(
                name=name,
                dir_path="/base",
                params=EnhancementParams(),
                output_dir=Path("/out"),
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=on_progress,
                slot_vars=[_FakeVar(), _FakeVar()],
            )

        return calls

    def test_done_reports_display_and_no_counters(self) -> None:
        calls = self._capture(
            return_value=ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-18.0,
                rms_after_db=-12.0,
                tags_copied=4,
            )
        )
        assert len(calls) == 1
        assert calls[0]["display_text"] == "[DONE] track.mp3  +6.0 dB  tags:4"
        assert calls[0].get("n_skipped", 0) == 0
        assert calls[0].get("n_errors", 0) == 0

    def test_error_result_reports_error_text(self) -> None:
        calls = self._capture(
            return_value=ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.ERROR,
                error_message="decode failed",
            )
        )
        assert calls[0]["display_text"] == "[ERROR] track.mp3: decode failed"

    def test_other_status_uses_prebuilt_display_text(self) -> None:
        """A result whose status is neither DONE nor ERROR falls through to
        the generic branch that forwards result.display_text unchanged."""
        calls = self._capture(
            return_value=ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.SKIPPED,
                display_text="[SKIP] track.mp3: vanished",
            )
        )
        assert calls[0]["display_text"] == "[SKIP] track.mp3: vanished"
        assert calls[0].get("n_skipped", 0) == 0

    def test_not_found_increments_skipped(self) -> None:
        calls = self._capture(
            side_effect=AudioFileNotFoundError("gone", path="track.mp3")
        )
        assert calls[0]["n_skipped"] == 1
        assert "SKIP" in calls[0]["display_text"]

    def test_permission_error_increments_error(self) -> None:
        calls = self._capture(
            side_effect=AudioPermissionError("locked", path="track.mp3")
        )
        assert calls[0]["n_errors"] == 1
        assert "ERROR" in calls[0]["display_text"]

    def test_audio_suite_error_increments_error(self) -> None:
        import threading

        from audio_suite_shared.exceptions import AudioSuiteError

        calls: list[dict] = []

        def on_progress(**kw) -> None:
            calls.append(kw)

        info = AudioFileInfo(path=Path("/base/track.mp3"))

        class _ConcreteError(AudioSuiteError):
            pass

        with (
            patch.object(file_processor, "inspect", return_value=info),
            patch.object(
                file_processor, "process_file", side_effect=_ConcreteError("boom")
            ),
        ):
            file_processor.process_single_file(
                name="track.mp3",
                dir_path="/base",
                params=EnhancementParams(),
                output_dir=Path("/out"),
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=on_progress,
            )

        assert calls[0]["n_errors"] == 1
        assert "ERROR" in calls[0]["display_text"]

    def test_oserror_maps_to_error(self) -> None:
        calls = self._capture(side_effect=OSError("io"))
        assert calls[0]["n_errors"] == 1
        assert "ERROR" in calls[0]["display_text"]
