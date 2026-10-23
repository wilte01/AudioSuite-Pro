"""Tests for ``ml_denoiser.app`` without a real display.

The completion seam is the important one: it drives the tool's real
``run_ml_denoise`` into the handler ``app.py`` binds and asserts the *written*
file and the *rendered* summary, so a processor that renames or stops publishing
a field fails here instead of at the end of a run that already rewrote the
library.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from ml_denoiser.app import MlDenoiserApp
from ml_denoiser.core import file_processor
from ml_denoiser.core.models import FRAME_SIZE, DenoiseParams

SR = 44100


def _tone(path: Path) -> Path:
    """Write a mono 440 Hz tone at -6 dBFS."""
    tone = Sine(440).to_audio_segment(duration=400, volume=-6)
    tone.set_channels(1).export(str(path), format="wav")
    return path


def _install_fake_rnnoise(
    monkeypatch: pytest.MonkeyPatch, *, gain: float = 0.5
) -> None:
    """Register a fake model that multiplies every sample by *gain*."""
    module = types.ModuleType("pyrnnoise")

    class _FakeRNNoise:
        def __init__(self, sample_rate: int) -> None:
            self.sample_rate = sample_rate

        def denoise_chunk(self, chunk: Any, partial: bool = False) -> Any:
            array = np.atleast_2d(np.asarray(chunk, dtype=np.int16))
            processed = np.rint(array.astype(np.float64) * gain).astype(np.int16)
            for start in range(0, processed.shape[1], FRAME_SIZE):
                yield (
                    np.zeros((array.shape[0], 1), dtype=np.float32),
                    processed[:, start : start + FRAME_SIZE],
                )

    module.RNNoise = _FakeRNNoise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyrnnoise", module)


def _slots() -> tuple[list[MagicMock], Queue[int]]:
    """Return one worker slot per pool worker and a full index queue."""
    slots = [MagicMock() for _ in range(DEFAULT_MAX_WORKERS)]
    queue: Queue[int] = Queue()
    for index in range(DEFAULT_MAX_WORKERS):
        queue.put(index)
    return slots, queue


def _shell() -> MlDenoiserApp:
    """Build the app shell with only what the paths under test touch.

    ``root.after`` runs its callback immediately: that is how a test observes
    the widget update the worker thread scheduled, on the thread that owns Tk.
    """
    app = object.__new__(MlDenoiserApp)
    app.root = MagicMock()
    app.root.after.side_effect = lambda _delay, fn, *args: fn(*args)
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app._tab_results = MagicMock()
    app.start_btn = MagicMock()
    app.progress = MagicMock()
    app.overall_status = MagicMock()
    app.stats_label = MagicMock()
    app.file_listbox = MagicMock()
    app._run_was_dry_run = False
    app._audition_original = None
    app._audition_result = None
    app.set_audition_state = MagicMock()
    return app


class TestValidateStart:
    """The pre-flight check that keeps a missing extra out of the batch."""

    def _app_with_amount(self, percent: int) -> MlDenoiserApp:
        app = _shell()
        app.denoise_amount = MagicMock()
        app.denoise_amount.get.return_value = percent
        return app

    def test_zero_percent_is_refused(self) -> None:
        app = self._app_with_amount(0)

        message = app._validate_start()

        assert message is not None
        assert "above 0%" in message

    def test_a_missing_extra_names_the_install(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)
        app = self._app_with_amount(100)

        message = app._validate_start()

        assert message is not None
        assert "RNNoise" in message
        assert "ml" in message

    def test_a_healthy_install_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_rnnoise(monkeypatch)
        app = self._app_with_amount(100)

        assert app._validate_start() is None


class TestCompletionSeam:
    """``run_ml_denoise`` publishes into the handler ``app.py`` binds."""

    @staticmethod
    def _drive(app: MlDenoiserApp, directory: Path, params: DenoiseParams) -> None:
        """Call the real entry point with the handlers ``app.py`` binds."""
        slots, queue = _slots()
        file_processor.run_ml_denoise(
            str(directory),
            params,
            slots,
            queue,
            app._on_progress,
            app._on_complete,
            MagicMock(),
        )

    def test_the_written_file_and_the_summary_carry_the_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        source = _tone(tmp_path / "tone.wav")
        before = AudioSegment.from_wav(str(source)).rms
        app = _shell()

        self._drive(app, tmp_path, DenoiseParams())

        after = AudioSegment.from_wav(str(source)).rms
        assert after == pytest.approx(before / 2, rel=0.02)

        summary = app.summary_label.config.call_args.kwargs["text"]
        assert "Total: 1 files" in summary
        assert "Denoised: 1" in summary
        assert "Skipped: 0" in summary
        assert "Errors: 0" in summary
        assert app.stats_label.config.call_args.kwargs["text"].startswith(
            "Processed: 1 | Denoised: 1"
        )
        assert app.completion_label.config.call_args.kwargs["text"] == (
            "ML Denoising Complete!"
        )

    def test_distinct_counts_are_not_swapped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One skip and one error, each counted once, in their own field."""
        _install_fake_rnnoise(monkeypatch, gain=1.0)
        _tone(tmp_path / "clean.wav")
        (tmp_path / "bad.wav").write_bytes(b"not audio")
        app = _shell()

        self._drive(app, tmp_path, DenoiseParams())

        summary = app.summary_label.config.call_args.kwargs["text"]
        assert "Total: 2 files" in summary
        assert "Denoised: 0" in summary
        assert "Skipped: 1" in summary
        assert "Errors: 1" in summary

    def test_a_dry_run_writes_nothing_but_still_reports(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        source = _tone(tmp_path / "tone.wav")
        before = source.read_bytes()
        app = _shell()

        self._drive(app, tmp_path, DenoiseParams(dry_run=True))

        assert source.read_bytes() == before
        summary = app.summary_label.config.call_args.kwargs["text"]
        assert "Denoised: 1" in summary
        assert "Errors: 0" in summary

    @pytest.mark.parametrize(
        "field",
        [
            "total",
            "succeeded",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        ],
    )
    def test_a_missing_field_raises_and_renders_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
    ) -> None:
        """The required set is the contract: a dropped field names itself."""
        payload = {
            "total": 3,
            "succeeded": 2,
            "skipped": 1,
            "errors": 0,
            "duration_secs": 1.5,
            "log_entries": ["line\n"],
        }
        payload.pop(field)
        app = _shell()

        with pytest.raises(TypeError) as caught:
            app._on_complete(**payload)

        assert field in str(caught.value)
        app.summary_label.config.assert_not_called()


class TestCliOptions:
    """Driver flags land on the controls the run reads."""

    def test_live_amount_and_auto_end_are_applied(self) -> None:
        app = _shell()
        app.run_mode = MagicMock()
        app.denoise_amount = MagicMock()
        app.auto_end_var = MagicMock()
        parsed = MagicMock()
        parsed.live_mode = True
        parsed.amount = 0.4
        parsed.auto_end = True

        app._apply_tool_cli_options(parsed)

        app.run_mode.set.assert_called_once_with("Live Update")
        app.denoise_amount.set.assert_called_once_with(40)
        app.auto_end_var.set.assert_called_once_with(True)

    def test_presets_round_trip_the_amount(self) -> None:
        app = _shell()
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app.denoise_amount = MagicMock()
        app.denoise_amount.get.return_value = 75

        settings = app._collect_settings()

        assert settings == {"denoise_amount": 75, "run_mode": "Dry Run"}

        app._apply_preset({"denoise_amount": 25, "run_mode": "Live Update"})

        app.denoise_amount.set.assert_called_once_with(25)
        app.run_mode.set.assert_called_once_with("Live Update")
