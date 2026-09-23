"""
tests/test_app.py
Tests for app.py — PopClickRemoverApp orchestration logic.

Run with:
    pytest tests/test_app.py -v

Coverage
--------
_on_complete
  * UI labels updated with correct counts
  * Time label formatted correctly
  * Completion label set
  * Start button re-enabled
  * Notebook switches to Results tab

_collect_settings
  * Returns dict with sensitivity, max_width, run_mode

_apply_preset
  * Sets all three variables from preset dict
  * Partial preset only sets provided keys

_on_error
  * Calls messagebox.showerror with message
  * Re-enables start button

Driver-mirror variables
  * auto_start_var, auto_end_var, clear_logs_var, parallel_var present
  * _launched_from_driver flag present
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pop_click_remover.app import PopClickRemoverApp


def _audition_caption(root: Any) -> str:
    """Latest caption scheduled by _on_complete through root.after."""
    for call in root.after.call_args_list:
        args = call[0]
        if len(args) == 3 and args[0] == 0 and isinstance(args[2], str):
            return args[2]
    return ""


class TestOnComplete:
    """_on_complete() updates UI labels, time, and switches to Results tab."""

    @pytest.fixture
    def app(self) -> PopClickRemoverApp:
        root = MagicMock()
        app = object.__new__(PopClickRemoverApp)
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

    def test_sets_progress_to_100(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=5,
            succeeded=4,
            skipped=1,
            errors=0,
            duration_secs=30.0,
            log_entries=[],
        )
        app.progress.__setitem__.assert_any_call("value", 100)

    def test_sets_overall_status(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=5,
            succeeded=4,
            skipped=1,
            errors=0,
            duration_secs=30.0,
            log_entries=[],
        )
        app.overall_status.set.assert_called_once_with("Complete.")

    def test_time_label_zero_seconds(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=0.0, log_entries=[]
        )
        app.time_label.config.assert_called_once_with(text="Total Time: 00:00")

    def test_time_label_minutes_and_seconds(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=1,
            succeeded=1,
            skipped=0,
            errors=0,
            duration_secs=125.0,
            log_entries=[],
        )
        app.time_label.config.assert_called_once_with(text="Total Time: 02:05")

    def test_summary_label_text(self, app: PopClickRemoverApp) -> None:
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
        assert "Succeeded: 7" in text
        assert "Skipped: 2" in text
        assert "Errors: 1" in text

    def test_completion_label_text(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.completion_label.config.assert_called_once_with(
            text="Pop & Click Removal Complete!"
        )

    def test_switches_to_results_tab(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.notebook.select.assert_called_once_with(app._tab_results)

    def test_re_enables_start_button(self, app: PopClickRemoverApp) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_audition_dry_run_schedules_result_disabled(
        self, app: PopClickRemoverApp
    ) -> None:
        app._run_was_dry_run = True
        app._audition_original = Path("track_orig.mp3")
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        assert app._audition_result is None
        assert "Dry Run" in _audition_caption(app.root)

    def test_audition_live_pair_schedules_ready_caption(
        self, app: PopClickRemoverApp
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

    def test_audition_no_source_schedules_message(
        self, app: PopClickRemoverApp
    ) -> None:
        app._on_complete(
            total=1, succeeded=1, skipped=0, errors=0, duration_secs=1.0, log_entries=[]
        )
        assert (
            _audition_caption(app.root) == "No supported audio file found for audition."
        )


class TestCollectSettings:
    """_collect_settings() reads Tk variable values into a dict."""

    @pytest.fixture
    def app(self) -> PopClickRemoverApp:
        app = object.__new__(PopClickRemoverApp)
        app.sensitivity = MagicMock()
        app.sensitivity.get.return_value = 0.31
        app.max_width = MagicMock()
        app.max_width.get.return_value = 2
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        return app

    def test_returns_all_settings(self, app: PopClickRemoverApp) -> None:
        settings = app._collect_settings()
        assert settings == {
            "sensitivity": 0.31,
            "max_width": 2,
            "run_mode": "Dry Run",
        }

    def test_reflects_live_mode(self, app: PopClickRemoverApp) -> None:
        app.run_mode.get.return_value = "Live Update"
        settings = app._collect_settings()
        assert settings["run_mode"] == "Live Update"

    def test_reflects_sensitivity_change(self, app: PopClickRemoverApp) -> None:
        app.sensitivity.get.return_value = 0.75
        settings = app._collect_settings()
        assert settings["sensitivity"] == 0.75


class TestApplyPreset:
    """_apply_preset() writes preset values back to Tk variables."""

    @pytest.fixture
    def app(self) -> PopClickRemoverApp:
        app = object.__new__(PopClickRemoverApp)
        app.sensitivity = MagicMock()
        app.max_width = MagicMock()
        app.run_mode = MagicMock()
        return app

    def test_sets_all_three(self, app: PopClickRemoverApp) -> None:
        app._apply_preset(
            {
                "sensitivity": 0.5,
                "max_width": 4,
                "run_mode": "Live Update",
            }
        )
        app.sensitivity.set.assert_called_once_with(0.5)
        app.max_width.set.assert_called_once_with(4)
        app.run_mode.set.assert_called_once_with("Live Update")

    def test_partial_preset_only_sets_provided(self, app: PopClickRemoverApp) -> None:
        app._apply_preset({"sensitivity": 0.6})
        app.sensitivity.set.assert_called_once_with(0.6)
        app.max_width.set.assert_not_called()
        app.run_mode.set.assert_not_called()

    def test_empty_preset_does_nothing(self, app: PopClickRemoverApp) -> None:
        app._apply_preset({})
        app.sensitivity.set.assert_not_called()
        app.max_width.set.assert_not_called()
        app.run_mode.set.assert_not_called()


class TestOnError:
    """_on_error() shows error dialog and re-enables start button."""

    @pytest.fixture
    def app(self) -> PopClickRemoverApp:
        app = object.__new__(PopClickRemoverApp)
        app.start_btn = MagicMock()
        return app

    def test_calls_showerror(self, app: PopClickRemoverApp) -> None:
        with patch("pop_click_remover.app.messagebox.showerror") as mock_err:
            app._on_error("Something broke")
            mock_err.assert_called_once_with("Pop & Click Remover", "Something broke")

    def test_re_enables_start_button(self, app: PopClickRemoverApp) -> None:
        with patch("pop_click_remover.app.messagebox.showerror"):
            app._on_error("fail")
        app.start_btn.config.assert_called_once_with(state="normal")


class TestDriverMirrorVars:
    """Driver-mirror BooleanVars and _launched_from_driver flag."""

    def test_has_auto_start_var(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.auto_start_var = tk.BooleanVar(value=False)
        assert hasattr(app, "auto_start_var")
        assert isinstance(app.auto_start_var, tk.BooleanVar)
        assert app.auto_start_var.get() is False

    def test_has_auto_end_var(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.auto_end_var = tk.BooleanVar(value=False)
        assert hasattr(app, "auto_end_var")
        assert isinstance(app.auto_end_var, tk.BooleanVar)
        assert app.auto_end_var.get() is False

    def test_has_clear_logs_var(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.clear_logs_var = tk.BooleanVar(value=False)
        assert hasattr(app, "clear_logs_var")
        assert isinstance(app.clear_logs_var, tk.BooleanVar)
        assert app.clear_logs_var.get() is False

    def test_has_parallel_var(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.parallel_var = tk.BooleanVar(value=False)
        assert hasattr(app, "parallel_var")
        assert isinstance(app.parallel_var, tk.BooleanVar)
        assert app.parallel_var.get() is False

    def test_has_launched_from_driver(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app._launched_from_driver = False
        assert hasattr(app, "_launched_from_driver")
        assert app._launched_from_driver is False

    def test_auto_end_var_settable(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.auto_end_var = tk.BooleanVar(value=False)
        app.auto_end_var.set(True)
        assert app.auto_end_var.get() is True

    def test_clear_logs_var_settable(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.clear_logs_var = tk.BooleanVar(value=False)
        app.clear_logs_var.set(True)
        assert app.clear_logs_var.get() is True

    def test_parallel_var_settable(self) -> None:
        app = object.__new__(PopClickRemoverApp)
        app.parallel_var = tk.BooleanVar(value=False)
        app.parallel_var.set(True)
        assert app.parallel_var.get() is True


class TestMainEntryPoint:
    """Launcher contract: Pop_Click_Remover.pyw imports ``main`` from app."""

    def test_main_is_importable(self) -> None:
        from pop_click_remover.app import main

        assert callable(main)

    def test_main_creates_root_and_enters_mainloop(self) -> None:
        root = MagicMock()
        with (
            patch("pop_click_remover.app.tk.Tk", return_value=root),
            patch("pop_click_remover.app.PopClickRemoverApp") as app_cls,
        ):
            from pop_click_remover.app import main

            main()

        app_cls.assert_called_once_with(root)
        root.mainloop.assert_called_once_with()
