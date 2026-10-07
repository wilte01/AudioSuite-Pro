"""
tests/test_app.py
Tests for app.py — NoiseReductionApp orchestration logic.

Coverage
--------
_on_complete
  * UI labels updated with correct counts
  * Time label formatted correctly
  * Completion label set
  * Start button re-enabled
  * Notebook switches to Results tab

_collect_settings
  * Returns dict with all hum + broadband + run_mode keys

_apply_preset
  * Sets all variables from preset dict
  * Partial preset only sets provided keys

_on_error
  * Calls messagebox.showerror with message
  * Re-enables start button

Driver-mirror variables
  * auto_start_var, auto_end_var, clear_logs_var, parallel_var present
  * _launched_from_driver flag present
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from noise_reduction.app import NoiseReductionApp

_SETTINGS_KEYS = (
    "reduce_hum",
    "hum_frequency",
    "hum_harmonics",
    "hum_quality",
    "reduce_broadband",
    "noise_start_ms",
    "noise_end_ms",
    "gate_threshold_db",
    "run_mode",
)


def _audition_caption(root: Any) -> str:
    """Latest caption scheduled by _on_complete through root.after."""
    for call in root.after.call_args_list:
        args = call[0]
        if len(args) == 3 and args[0] == 0 and isinstance(args[2], str):
            return args[2]
    return ""


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestOnComplete:
    """_on_complete() updates UI labels, time, and switches to Results tab."""

    @staticmethod
    @pytest.fixture
    def app() -> NoiseReductionApp:
        root = MagicMock()
        app = object.__new__(NoiseReductionApp)
        app.root = root
        app._run_was_dry_run = False
        app._audition_original = None
        app._audition_result = None
        app.progress = MagicMock()
        app.overall_status = MagicMock()
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_results = MagicMock()
        app.auto_start_var = tk.BooleanVar(value=False)
        app.auto_end_var = tk.BooleanVar(value=False)
        app.clear_logs_var = tk.BooleanVar(value=False)
        app.parallel_var = tk.BooleanVar(value=False)
        app._launched_from_driver = False
        return app

    def test_sets_progress_to_100(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=5,
            succeeded=4,
            skipped=1,
            errors=0,
            duration_secs=30.0,
            log_entries=[],
        )
        app.progress.__setitem__.assert_any_call("value", 100)

    def test_sets_overall_status(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=5,
            succeeded=4,
            skipped=1,
            errors=0,
            duration_secs=30.0,
            log_entries=[],
        )
        app.overall_status.set.assert_called_once_with("Complete.")

    def test_time_label_zero_seconds(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=0.0, log_entries=[]
        )
        app.time_label.config.assert_called_once_with(text="Total Time: 00:00")

    def test_time_label_minutes_and_seconds(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=1,
            succeeded=1,
            skipped=0,
            errors=0,
            duration_secs=125.0,
            log_entries=[],
        )
        app.time_label.config.assert_called_once_with(text="Total Time: 02:05")

    def test_summary_label_text(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=10,
            succeeded=7,
            skipped=2,
            errors=1,
            duration_secs=60.0,
            log_entries=[],
        )
        app.summary_label.config.assert_called_once()
        text = app.summary_label.config.call_args[1]["text"]
        assert "Total: 10 files" in text
        assert "Reduced: 7" in text
        assert "Skipped: 2" in text
        assert "Errors: 1" in text

    def test_completion_label_text(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.completion_label.config.assert_called_once_with(
            text="Noise Reduction Complete!"
        )

    def test_switches_to_results_tab(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.notebook.select.assert_called_once_with(app._tab_results)

    def test_re_enables_start_button(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_audition_dry_run_schedules_result_disabled(
        self, app: NoiseReductionApp
    ) -> None:
        app._run_was_dry_run = True
        app._audition_original = Path("track_orig.mp3")
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        assert app._audition_result is None
        assert "Dry Run" in _audition_caption(app.root)

    def test_audition_live_pair_schedules_ready_caption(
        self, app: NoiseReductionApp
    ) -> None:
        app._audition_original = Path("track_orig.mp3")
        app._audition_result = Path("track.mp3")
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        assert (
            _audition_caption(app.root)
            == "Audition ready — track.mp3 (original vs result)"
        )

    def test_audition_no_source_schedules_message(self, app: NoiseReductionApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        assert (
            _audition_caption(app.root) == "No supported audio file found for audition."
        )

    def test_auto_end_schedules_root_destroy(self, app: NoiseReductionApp) -> None:
        """The driver's ``--end`` must close the window once work completes.

        Positive contract: the destroy is what has to be *scheduled*. Asserting
        "nothing was scheduled" instead would pass forever against the inert
        ``--end`` this test exists to pin.
        """
        app.auto_end_var.set(True)
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.root.after.assert_any_call(2000, app.root.destroy)

    def test_auto_end_schedules_destroy_after_the_audition_state(
        self, app: NoiseReductionApp
    ) -> None:
        """The close is scheduled *after* the audition caption is written.

        Destroying first would tear the window down before the results tab is
        populated, so the ordering is part of the contract, not incidental.
        """
        app.auto_end_var.set(True)
        app._audition_original = Path("track_orig.mp3")
        app._audition_result = Path("track.mp3")
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        assert _audition_caption(app.root).startswith("Audition ready")
        assert any(
            call_.args[0] == 2000 and call_.args[1] is app.root.destroy
            for call_ in app.root.after.call_args_list
        )


class TestCollectSettings:
    """_collect_settings() reads Tk variable values into a dict."""

    @staticmethod
    @pytest.fixture
    def app() -> NoiseReductionApp:
        app = object.__new__(NoiseReductionApp)
        for key in _SETTINGS_KEYS:
            setattr(app, key, MagicMock())
        app.reduce_hum.get.return_value = True
        app.hum_frequency.get.return_value = 60
        app.hum_harmonics.get.return_value = 8
        app.hum_quality.get.return_value = 30.0
        app.reduce_broadband.get.return_value = False
        app.noise_start_ms.get.return_value = 0
        app.noise_end_ms.get.return_value = 500
        app.gate_threshold_db.get.return_value = 3.0
        app.run_mode.get.return_value = "Dry Run"
        return app

    def test_returns_all_settings(self, app: NoiseReductionApp) -> None:
        settings = app._collect_settings()
        assert settings == {
            "reduce_hum": True,
            "hum_frequency": 60,
            "hum_harmonics": 8,
            "hum_quality": 30.0,
            "reduce_broadband": False,
            "noise_start_ms": 0,
            "noise_end_ms": 500,
            "gate_threshold_db": 3.0,
            "run_mode": "Dry Run",
        }

    def test_reflects_live_mode(self, app: NoiseReductionApp) -> None:
        app.run_mode.get.return_value = "Live Update"
        assert app._collect_settings()["run_mode"] == "Live Update"

    def test_reflects_reduce_hum(self, app: NoiseReductionApp) -> None:
        app.reduce_hum.get.return_value = False
        assert app._collect_settings()["reduce_hum"] is False


class TestApplyPreset:
    """_apply_preset() writes preset values back to Tk variables."""

    @staticmethod
    @pytest.fixture
    def app() -> NoiseReductionApp:
        app = object.__new__(NoiseReductionApp)
        for key in _SETTINGS_KEYS:
            setattr(app, key, MagicMock())
        return app

    def test_sets_all(self, app: NoiseReductionApp) -> None:
        app._apply_preset(
            {
                "reduce_hum": True,
                "hum_frequency": 50,
                "hum_harmonics": 10,
                "hum_quality": 20.0,
                "reduce_broadband": True,
                "noise_start_ms": 100,
                "noise_end_ms": 900,
                "gate_threshold_db": 6.0,
                "run_mode": "Live Update",
            }
        )
        app.reduce_hum.set.assert_called_once_with(True)
        app.hum_frequency.set.assert_called_once_with(50)
        app.hum_harmonics.set.assert_called_once_with(10)
        app.hum_quality.set.assert_called_once_with(20.0)
        app.reduce_broadband.set.assert_called_once_with(True)
        app.noise_start_ms.set.assert_called_once_with(100)
        app.noise_end_ms.set.assert_called_once_with(900)
        app.gate_threshold_db.set.assert_called_once_with(6.0)
        app.run_mode.set.assert_called_once_with("Live Update")

    def test_partial_preset_only_sets_provided(self, app: NoiseReductionApp) -> None:
        app._apply_preset({"hum_frequency": 60})
        app.hum_frequency.set.assert_called_once_with(60)
        app.reduce_hum.set.assert_not_called()
        app.run_mode.set.assert_not_called()

    def test_empty_preset_does_nothing(self, app: NoiseReductionApp) -> None:
        app._apply_preset({})
        for key in _SETTINGS_KEYS:
            getattr(app, key).set.assert_not_called()

        app._apply_preset({"run_mode": "Dry Run"})

        app.run_mode.set.assert_called_once_with("Dry Run")


class TestOnError:
    """_on_error() shows error dialog and re-enables start button."""

    @staticmethod
    @pytest.fixture
    def app() -> NoiseReductionApp:
        app = object.__new__(NoiseReductionApp)
        app.start_btn = MagicMock()
        return app

    def test_calls_showerror(self, app: NoiseReductionApp) -> None:
        with patch("audio_suite_shared.tool_app_base.messagebox.showerror") as mock_err:
            app._on_error("Something broke")
            mock_err.assert_called_once_with("Noise Reduction", "Something broke")

    def test_re_enables_start_button(self, app: NoiseReductionApp) -> None:
        with patch("audio_suite_shared.tool_app_base.messagebox.showerror"):
            app._on_error("fail")
        app.start_btn.config.assert_called_once_with(state="normal")


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestDriverMirrorVars:
    """Driver-mirror BooleanVars and _launched_from_driver flag."""

    def test_has_auto_start_var(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.auto_start_var = tk.BooleanVar(value=False)
        assert isinstance(app.auto_start_var, tk.BooleanVar)
        assert app.auto_start_var.get() is False

    def test_has_auto_end_var(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.auto_end_var = tk.BooleanVar(value=False)
        assert isinstance(app.auto_end_var, tk.BooleanVar)
        assert app.auto_end_var.get() is False

    def test_has_clear_logs_var(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.clear_logs_var = tk.BooleanVar(value=False)
        assert isinstance(app.clear_logs_var, tk.BooleanVar)
        assert app.clear_logs_var.get() is False

    def test_has_parallel_var(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.parallel_var = tk.BooleanVar(value=False)
        assert isinstance(app.parallel_var, tk.BooleanVar)
        assert app.parallel_var.get() is False

    def test_has_launched_from_driver(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app._launched_from_driver = False
        assert hasattr(app, "_launched_from_driver")

    def test_auto_end_var_settable(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.auto_end_var = tk.BooleanVar(value=False)
        app.auto_end_var.set(True)
        assert app.auto_end_var.get() is True

    def test_clear_logs_var_settable(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.clear_logs_var = tk.BooleanVar(value=False)
        app.clear_logs_var.set(True)
        assert app.clear_logs_var.get() is True

    def test_parallel_var_settable(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.parallel_var = tk.BooleanVar(value=False)
        app.parallel_var.set(True)
        assert app.parallel_var.get() is True


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
        "audio_suite_shared.suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(sys, "argv", ["noise_reduction"])
    return NoiseReductionApp(app_root)


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(self, real_app: Any) -> None:
        app = real_app
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() == "Dry Run"
        assert app.reduce_hum.get() is False
        assert app.noise_end_ms.get() == 500

    def test_worker_slot_pool_starts_full(self, real_app: Any) -> None:
        drained = []
        while True:
            try:
                drained.append(real_app.slot_queue.get_nowait())
            except Exception:
                break
        assert drained == list(range(DEFAULT_MAX_WORKERS))


class TestStartGuardsD3:
    def _shell(self) -> Any:
        app = object.__new__(NoiseReductionApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.run_mode = MagicMock()
        app.reduce_hum = MagicMock()
        app.reduce_broadband = MagicMock()
        app.hum_frequency = MagicMock()
        app.hum_harmonics = MagicMock()
        app.hum_quality = MagicMock()
        app.noise_start_ms = MagicMock()
        app.noise_end_ms = MagicMock()
        app.gate_threshold_db = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app.file_listbox = MagicMock()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        return app

    def test_missing_folder_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_suite_shared.tool_app_base.messagebox", dialogs)
        app.folder_path.get.return_value = ""

        app._on_start()

        dialogs.showwarning.assert_called_once()

    def test_nonexistent_folder_shows_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_suite_shared.tool_app_base.messagebox", dialogs)
        app.folder_path.get.return_value = "D:/definitely_missing_dir"

        app._on_start()

        dialogs.showerror.assert_called_once()

    def test_no_stage_selected_warns(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_suite_shared.tool_app_base.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path)
        app.reduce_hum.get.return_value = False
        app.reduce_broadband.get.return_value = False

        app._on_start()

        dialogs.showwarning.assert_called_once()

    def test_valid_start_builds_params_and_thread(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr(
            "audio_suite_shared.tool_app_base.threading", fake_threading
        )
        monkeypatch.setattr("audio_suite_shared.tool_app_base.messagebox", MagicMock())
        monkeypatch.setattr(
            "audio_suite_shared.suite_config.save_last_directory", MagicMock()
        )
        built: dict[str, Any] = {}

        class FakeParams:
            def __init__(self, **kwargs: Any) -> None:
                built.update(kwargs)

        monkeypatch.setattr("noise_reduction.app.NoiseReductionParams", FakeParams)
        monkeypatch.setattr(
            "noise_reduction.app.run_noise_reduction", lambda *a, **k: None
        )
        app = self._shell()
        app.prepare_in_place_audition = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        app.reduce_hum.get.return_value = True
        app.hum_frequency.get.return_value = 60
        app.hum_harmonics.get.return_value = 8
        app.hum_quality.get.return_value = 30.0
        app.noise_start_ms.get.return_value = 0
        app.noise_end_ms.get.return_value = 500
        app.gate_threshold_db.get.return_value = 3.0
        app.run_mode.get.return_value = "Live Update"

        app._on_start()

        # Params are now built inside the background thread; invoke the
        # thread target directly to capture them.
        thread_target = fake_threading.Thread.call_args.kwargs["target"]
        thread_target(str(tmp_path), False)

        assert built["dry_run"] is False
        assert built["reduce_hum"] is True
        assert built["gate_threshold_db"] == 3.0
        assert thread_target.__name__ == "_run_with_undo"
        app.prepare_in_place_audition.assert_called_once_with(
            str(tmp_path), SUPPORTED_EXTENSIONS
        )


class TestProgressUIAndErrorsD3:
    def test_on_progress_marshals_onto_main_thread(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.root = MagicMock()

        app._on_progress(3, 10, 2, 1, 1, "song.mp3")

        assert app.root.after.call_args.args[0] == 0
        assert getattr(app.root.after.call_args.args[1], "__name__") == (
            "_update_progress_ui"
        )

    def test_update_progress_ui_sets_all_widgets(self) -> None:
        app = object.__new__(NoiseReductionApp)
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()

        app._update_progress_ui(3, 10, 2, 1, 1, "song.mp3")

        assert app.stats_label.config.call_args.kwargs["text"].startswith(
            "Processed: 3"
        )
        assert app.file_listbox.insert.call_args.args[1] == "song.mp3"

    def test_on_error_restores_start_button(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = object.__new__(NoiseReductionApp)
        app.start_btn = MagicMock()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_suite_shared.tool_app_base.messagebox", dialogs)

        app._on_error("boom")

        dialogs.showerror.assert_called_once()
        app.start_btn.config.assert_called_once_with(state="normal")


class TestRegistrationAndBaseClass:
    """Lock: class identity, base class, and tool-specific attributes."""

    def test_main_is_importable(self) -> None:
        from noise_reduction.app import main

        assert callable(main)

    def test_main_creates_root_and_enters_mainloop(self) -> None:
        root = MagicMock()
        with (
            patch("noise_reduction.app.tk.Tk", return_value=root),
            patch("noise_reduction.app.NoiseReductionApp") as app_cls,
        ):
            from noise_reduction.app import main

            main()

        app_cls.assert_called_once_with(root)
        root.mainloop.assert_called_once_with()

    def test_inherits_from_noise_pop_base(self) -> None:
        from audio_suite_shared.tool_app_base import NoisePopToolApp

        assert issubclass(NoiseReductionApp, NoisePopToolApp)

    def test_help_guide_value(self) -> None:
        assert NoiseReductionApp.HELP_GUIDE == "Noise_Reduction_User_Guide.docx"

    def test_results_label_value(self) -> None:
        assert NoiseReductionApp.RESULTS_LABEL == "Reduced"
