"""Tests for audio_refinery.app — driver-mirror variable presence and audition."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_refinery.app import AudioRefineryApp
from audio_refinery.core.models import StageConfig


def _make_app_stub() -> object:
    """Build a minimal AudioRefineryApp-like stub for testing."""
    app = object.__new__(type("Stub", (), {}))
    app.root = MagicMock(spec=tk.Tk)
    app.source_path = tk.StringVar()
    app.output_path = tk.StringVar()
    app.run_mode = tk.StringVar(value="Dry Run")
    app.auto_start_var = tk.BooleanVar(value=False)
    app.auto_end_var = tk.BooleanVar(value=False)
    app.clear_logs_var = tk.BooleanVar(value=False)
    app.parallel_var = tk.BooleanVar(value=False)
    app._launched_from_driver = False
    return app


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestDriverMirrorVars:
    """Tests that the app exposes driver-mirror BooleanVars."""

    def test_has_auto_start_var(self) -> None:
        app = _make_app_stub()
        assert hasattr(app, "auto_start_var")
        assert isinstance(app.auto_start_var, tk.BooleanVar)
        assert app.auto_start_var.get() is False

    def test_has_auto_end_var(self) -> None:
        app = _make_app_stub()
        assert hasattr(app, "auto_end_var")
        assert isinstance(app.auto_end_var, tk.BooleanVar)
        assert app.auto_end_var.get() is False

    def test_has_clear_logs_var(self) -> None:
        app = _make_app_stub()
        assert hasattr(app, "clear_logs_var")
        assert isinstance(app.clear_logs_var, tk.BooleanVar)
        assert app.clear_logs_var.get() is False

    def test_has_parallel_var(self) -> None:
        app = _make_app_stub()
        assert hasattr(app, "parallel_var")
        assert isinstance(app.parallel_var, tk.BooleanVar)
        assert app.parallel_var.get() is False

    def test_has_run_mode(self) -> None:
        app = _make_app_stub()
        assert hasattr(app, "run_mode")
        assert isinstance(app.run_mode, tk.StringVar)
        assert app.run_mode.get() == "Dry Run"

    def test_has_launched_from_driver(self) -> None:
        app = _make_app_stub()
        assert hasattr(app, "_launched_from_driver")
        assert app._launched_from_driver is False

    def test_auto_end_var_settable(self) -> None:
        app = _make_app_stub()
        app.auto_end_var.set(True)
        assert app.auto_end_var.get() is True

    def test_clear_logs_var_settable(self) -> None:
        app = _make_app_stub()
        app.clear_logs_var.set(True)
        assert app.clear_logs_var.get() is True

    def test_parallel_var_settable(self) -> None:
        app = _make_app_stub()
        app.parallel_var.set(True)
        assert app.parallel_var.get() is True

    def test_run_mode_settable(self) -> None:
        app = _make_app_stub()
        app.run_mode.set("Live Update")
        assert app.run_mode.get() == "Live Update"


class TestEntryPoint:
    """The `python main.py` entry point must stay importable."""

    def test_entry_point_importable(self) -> None:
        import audio_refinery.main

        assert callable(audio_refinery.main.main)


def _audition_caption(root: Any) -> str:
    """Latest caption scheduled by _on_complete through root.after."""
    for call in root.after.call_args_list:
        args = call[0]
        if len(args) == 3 and args[0] == 0 and isinstance(args[2], str):
            return args[2]
    return ""


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestAuditionOnComplete:
    """_on_complete() drives the shared audition state machine."""

    @pytest.fixture(autouse=True)
    def _patch_messagebox(self) -> None:
        with patch("audio_refinery.app.messagebox"):
            yield

    @pytest.fixture
    def app(self, tmp_path: Path) -> AudioRefineryApp:
        root = MagicMock()
        app = object.__new__(AudioRefineryApp)
        app.root = root
        app._log_path = str(tmp_path / "refinery_log.txt")
        app._completion_label = MagicMock()
        app._time_label = MagicMock()
        app.notebook = MagicMock()
        app._tab_results = MagicMock()
        app.start_btn = MagicMock()
        app.overall_status = MagicMock()
        app.auto_end_var = tk.BooleanVar(value=False)
        app._run_was_dry_run = False
        app._audition_original = None
        app._audition_result = None
        return app

    def _complete(self, app: AudioRefineryApp) -> None:
        scheduled: list[Any] = []
        app.root.after.side_effect = lambda delay, fn, *a: scheduled.append(fn)
        app._on_complete(
            total=1,
            processed=1,
            succeeded=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        if scheduled:
            scheduled[0]()

    def test_dry_run_schedules_result_disabled(self, app: AudioRefineryApp) -> None:
        app._run_was_dry_run = True
        app._audition_original = Path("track_orig.mp3")
        self._complete(app)
        assert app._audition_result is None
        assert "Dry Run" in _audition_caption(app.root)

    def test_live_pair_schedules_ready_caption(self, app: AudioRefineryApp) -> None:
        app._audition_original = Path("track_orig.mp3")
        app._audition_result = Path("track.mp3")
        self._complete(app)
        assert (
            _audition_caption(app.root)
            == "Audition ready — track.mp3 (original vs result)"
        )

    def test_no_source_schedules_message(self, app: AudioRefineryApp) -> None:
        self._complete(app)
        assert (
            _audition_caption(app.root) == "No supported audio file found for audition."
        )


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestStartProcessingStageValidation:
    """Regression: reduce_noise alone must satisfy the no-stage check."""

    @pytest.fixture
    def app(self, tmp_path: Path) -> AudioRefineryApp:
        app = object.__new__(AudioRefineryApp)
        app.root = MagicMock()
        app.source_path = tk.StringVar(value=str(tmp_path))
        app.output_path = tk.StringVar(value="")
        app.run_mode = tk.StringVar(value="Dry Run")
        app._registry = MagicMock()
        app._last_source_dir = str(tmp_path)
        app.start_btn = MagicMock()
        app._file_listbox = MagicMock()
        app._progress_bar = MagicMock()
        app.notebook = MagicMock()
        app._tab_processing = MagicMock()
        app.overall_status = MagicMock()
        return app

    @pytest.fixture
    def audio_dir(self, tmp_path: Path) -> Path:
        (tmp_path / "song.mp3").write_bytes(b"")
        return tmp_path

    def _start(self, app: AudioRefineryApp, config: StageConfig) -> MagicMock:
        app.config = config
        with (
            patch("audio_refinery.app.messagebox") as mb,
            patch("audio_refinery.app.save_settings"),
            patch("audio_refinery.app.suite_config.save_last_directory"),
            patch.object(AudioRefineryApp, "prepare_in_place_audition"),
            patch("audio_refinery.app.threading.Thread") as thread_cls,
        ):
            app.start_processing()
        mb._thread_cls = thread_cls
        return mb

    def test_reduce_noise_only_passes_stage_validation(
        self, app: AudioRefineryApp, audio_dir: Path
    ) -> None:
        mb = self._start(
            app,
            StageConfig(
                declick=False,
                trim=False,
                enhance=False,
                normalise=False,
                reduce_noise=True,
            ),
        )
        titles = [c.args[0] for c in mb.showerror.call_args_list]
        assert "No Stages Selected" not in titles
        mb._thread_cls.assert_called_once()
        mb._thread_cls.return_value.start.assert_called_once()

    def test_all_stages_disabled_shows_no_stages_selected(
        self, app: AudioRefineryApp, audio_dir: Path
    ) -> None:
        mb = self._start(
            app,
            StageConfig(
                declick=False,
                trim=False,
                enhance=False,
                normalise=False,
                reduce_noise=False,
            ),
        )
        titles = [c.args[0] for c in mb.showerror.call_args_list]
        assert "No Stages Selected" in titles
        mb._thread_cls.assert_not_called()
