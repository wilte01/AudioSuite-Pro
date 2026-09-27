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

import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

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

    @pytest.fixture
    def app(self) -> NoiseReductionApp:
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


class TestCollectSettings:
    """_collect_settings() reads Tk variable values into a dict."""

    @pytest.fixture
    def app(self) -> NoiseReductionApp:
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

    @pytest.fixture
    def app(self) -> NoiseReductionApp:
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


class TestOnError:
    """_on_error() shows error dialog and re-enables start button."""

    @pytest.fixture
    def app(self) -> NoiseReductionApp:
        app = object.__new__(NoiseReductionApp)
        app.start_btn = MagicMock()
        return app

    def test_calls_showerror(self, app: NoiseReductionApp) -> None:
        with patch("noise_reduction.app.messagebox.showerror") as mock_err:
            app._on_error("Something broke")
            mock_err.assert_called_once_with("Noise Reduction", "Something broke")

    def test_re_enables_start_button(self, app: NoiseReductionApp) -> None:
        with patch("noise_reduction.app.messagebox.showerror"):
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
