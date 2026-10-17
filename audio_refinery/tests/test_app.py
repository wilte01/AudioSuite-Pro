"""Tests for audio_refinery.app — driver-mirror variable presence and audition.
Changed in 1.1.0: added effect-field settings collect/apply coverage.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import audio_refinery.app as ar_mod
from audio_refinery.app import AudioRefineryApp, _ThreadSafeSlotVar
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

    @staticmethod
    @pytest.fixture(autouse=True)
    def _patch_messagebox() -> None:
        with patch("audio_refinery.app.messagebox"):
            yield

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioRefineryApp:
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

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioRefineryApp:
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

    @staticmethod
    @pytest.fixture
    def audio_dir(tmp_path: Path) -> Path:
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


@pytest.fixture()
def app_root(root: tk.Tk) -> Any:
    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture()
def real_app(app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        "audio_refinery.app.suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(sys, "argv", ["audio_refinery"])
    # Fresh settings so no stale stage config leaks into the assertions.
    from audio_refinery.core.models import StageConfig

    monkeypatch.setattr("audio_refinery.app.load_settings", lambda: StageConfig())
    return AudioRefineryApp(app_root)


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(self, real_app: Any) -> None:
        app = real_app
        assert app.start_btn is not None
        assert app.source_path.get() == ""
        assert app.run_mode.get() in {"Dry Run", "Live Update"}
        assert app.config is not None
        assert len(app.slot_vars) == ar_mod.DEFAULT_MAX_WORKERS
        assert app._registry is None

    def test_thread_safe_slot_var_routes_set_to_main_thread(
        self, app_root: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The wrapper schedules on a *dedicated* toplevel, never the session
        shared root: a bare ``root.after = MagicMock()`` on the shared root
        once leaked for the rest of the session and disabled every later
        tkinter timer dispatched inside another test's modal wait_window
        (TestShowMessage then blocked forever)."""
        t_var = tk.StringVar(app_root, value="IDLE")
        wrapper = _ThreadSafeSlotVar(app_root, t_var)
        after_mock = MagicMock()
        monkeypatch.setattr(app_root, "after", after_mock)

        wrapper.set("Busy")

        call = after_mock.call_args
        assert call is not None
        assert call.args[0] == 0
        assert call.args[1] == t_var.set  # scheduled with the plain var setter
        assert call.args[2] == "Busy"
        assert t_var.get() == "IDLE"  # not applied until the main loop runs it

    def test_preset_collect_and_apply_roundtrip(self, real_app: Any) -> None:
        app = real_app
        app._apply_preset(
            {
                "declick": True,
                "enhance": True,
                "threshold": -45,
                "target_lufs": -14,
                "reverse": True,
                "karaoke": True,
                "karaoke_strength": 0.4,
                "phaser": True,
                "flanger": True,
                "chorus": True,
            }
        )
        assert app.config.declick is True
        assert app.config.enhance is True
        assert app.config.trim_params.threshold == -45
        assert app.config.normalise_params.target_lufs == -14
        assert app.config.enhance_params.reverse is True
        assert app.config.enhance_params.karaoke is True
        assert app.config.enhance_params.karaoke_strength == 0.4
        assert app.config.enhance_params.phaser is True
        assert app.config.enhance_params.flanger is True
        assert app.config.enhance_params.chorus is True

    def test_collect_settings_includes_effect_fields(self, real_app: Any) -> None:
        """Sprint 1: the saved-preset payload must round-trip the effects."""
        app = real_app
        ep = app.config.enhance_params
        ep.reverse = True
        ep.karaoke = True
        ep.karaoke_strength = 0.3
        ep.phaser = True
        ep.flanger = True
        ep.chorus = True

        settings = app._collect_settings()

        assert settings["reverse"] is True
        assert settings["karaoke"] is True
        assert settings["karaoke_strength"] == 0.3
        assert settings["phaser"] is True
        assert settings["flanger"] is True
        assert settings["chorus"] is True


class TestApplyPresetRefreshesEnhancerEditor:
    """A loaded preset must move the Custom DSP editor's live controls.

    The editor's values are the source for every later edit, so a stale copy
    would rewrite the loaded preset back into the config on the next slider
    move — and the visible controls would disagree with what the pipeline runs.
    """

    def test_editor_controls_follow_a_loaded_preset(self, real_app: Any) -> None:
        app = real_app
        panel = app._setup_state["dsp_panel"]
        panel.open()
        try:
            app._apply_preset({"preset": "Custom", "compressor_ratio": 8.25})

            var = panel.variable("compressor_ratio")
            assert var is not None
            assert var.get() == pytest.approx(8.25)
            assert app._setup_state["preset_var"].get() == "Custom"
            assert app.config.enhance_params.compressor_ratio == 8.25
        finally:
            panel.close()


class TestStartGuardsD3:
    def _shell(self) -> Any:
        app = object.__new__(AudioRefineryApp)
        app.root = MagicMock()
        app.source_path = MagicMock()
        app.output_path = MagicMock()
        app.run_mode = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app._file_listbox = MagicMock()
        app._progress_bar = MagicMock()
        app._registry = None
        app._last_source_dir = ""
        app._in_place = False
        return app

    def test_missing_source_shows_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_refinery.app.messagebox", dialogs)
        app.source_path.get.return_value = ""
        app.config = MagicMock(
            declick=True, trim=True, enhance=True, normalise=True, reduce_noise=True
        )

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_nonexistent_source_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_refinery.app.messagebox", dialogs)
        app.source_path.get.return_value = "D:/definitely_not_a_dir"
        app.config = MagicMock(
            declick=True, trim=True, enhance=True, normalise=True, reduce_noise=True
        )

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_no_stage_selected_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_refinery.app.messagebox", dialogs)
        app.source_path.get.return_value = str(tmp_path)
        (tmp_path / "a.wav").write_bytes(b"\x00" * 8)
        app.config = MagicMock(
            declick=False,
            trim=False,
            enhance=False,
            normalise=False,
            reduce_noise=False,
        )

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_invalid_output_dir_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_refinery.app.messagebox", dialogs)
        app.source_path.get.return_value = str(tmp_path)
        (tmp_path / "a.wav").write_bytes(b"\x00" * 8)
        app.config = MagicMock(
            declick=True, trim=True, enhance=True, normalise=True, reduce_noise=True
        )
        app.output_path.get.return_value = "D:/no_such_output_dir"

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_valid_start_threads_pipeline_with_audition(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr("audio_refinery.app.threading", fake_threading)
        monkeypatch.setattr("audio_refinery.app.messagebox", MagicMock())
        monkeypatch.setattr(
            "audio_refinery.app.suite_config.save_last_directory", MagicMock()
        )
        monkeypatch.setattr("audio_refinery.app.save_settings", MagicMock())
        monkeypatch.setattr(
            "audio_refinery.app.audio_playback.peek_first_audio",
            lambda *_a: None,
        )
        monkeypatch.setattr("audio_refinery.app.run_pipeline", lambda **_k: None)
        app = self._shell()
        app.clear_audition = MagicMock()
        app.prepare_in_place_audition = MagicMock()
        app.folder_path = app.source_path
        out_dir = tmp_path / "out"
        out_dir.mkdir()
        (tmp_path / "a.wav").write_bytes(b"\x00" * 8)
        app.source_path.get.return_value = str(tmp_path)
        app.output_path.get.return_value = str(out_dir)
        app.run_mode.get.return_value = "Dry Run"
        app.config = MagicMock(
            declick=True, trim=True, enhance=True, normalise=True, reduce_noise=True
        )
        from audio_refinery.core.registry import CompletionRegistry

        app._registry = CompletionRegistry(tmp_path)

        app.start_processing()

        thread = fake_threading.Thread.call_args
        assert thread.kwargs["target"].__name__ == "_run"
        assert app._run_was_dry_run is True
        assert app._in_place is False, "output dir is a separate folder"
        app.clear_audition.assert_called_once_with()


class TestRunThreadD3:
    def test_run_thread_passes_registry_and_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = object.__new__(AudioRefineryApp)
        app.root = MagicMock()
        app._file_listbox = MagicMock()
        app._progress_bar = MagicMock()
        app.progress = app._progress_bar
        app.file_listbox = app._file_listbox
        calls: dict[str, Any] = {}

        def fake_run_pipeline(**kwargs: Any) -> None:
            calls.update(kwargs)

        import audio_refinery.core.file_processor as core  # noqa: F401

        # run_pipeline is imported into app.py at module level, so the
        # importing module's binding is the one to patch (AGENTS.md rule).
        monkeypatch.setattr("audio_refinery.app.run_pipeline", fake_run_pipeline)
        from audio_refinery.core.registry import CompletionRegistry

        registry = CompletionRegistry(tmp_path)
        app._registry = registry
        app.config = MagicMock()
        app._safe_slot_vars = [MagicMock()]
        app.slot_queue = MagicMock()

        app._run(tmp_path, tmp_path)

        assert calls["source_dir"] == tmp_path
        assert calls["output_dir"] == tmp_path
        assert calls["registry"] is registry
        assert calls["config"] is app.config


class TestProgressD3:
    def test_on_progress_schedules_update(self) -> None:
        app = object.__new__(AudioRefineryApp)
        app.root = MagicMock()
        app._file_listbox = MagicMock()
        app._progress_bar = MagicMock()
        app.stats_label = MagicMock()
        app.overall_status = MagicMock()

        app._on_progress(3, 10, 2, 1, 1, "song.wav", "log")

        assert app.root.after.call_args.args[0] == 0
        update_fn = app.root.after.call_args.args[1]
        update_fn()
        assert app._progress_bar.__setitem__("value", 3)
        assert app._file_listbox.insert.call_args.args[1] == "song.wav"
