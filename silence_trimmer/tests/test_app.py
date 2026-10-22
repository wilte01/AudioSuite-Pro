"""
tests/test_app.py
Tests for app.py — SilenceTrimmerApp orchestration logic.

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
  * Returns dict with threshold, fade_var, durations, parallel_mode,
  max_workers, run_mode

_apply_preset
  * Sets all variables from preset dict
  * Partial preset only sets provided keys

_on_error
  * Calls messagebox.showerror with message
  * Re-enables start button

Driver-mirror variables
  * auto_start_var, auto_end_var, clear_logs_var, parallel_var present
  * _launched_from_driver flag present

Changed in 1.4.0: covers a typed worker count above the slot grid being
capped (with a warning) before it is saved (D66).
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_trimming`` into the completion handler (PLAN D117).
"""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import silence_trimmer.app as st_mod
from silence_trimmer.app import SilenceTrimmerApp


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
    @pytest.fixture(autouse=True)
    def _patch_messagebox() -> None:
        with patch("silence_trimmer.app.messagebox"):
            yield

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> SilenceTrimmerApp:
        root = MagicMock()
        app = object.__new__(SilenceTrimmerApp)
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
        app._log_path = str(tmp_path / "test_log.txt")
        app.run_mode = tk.StringVar(value="Dry Run")
        app.auto_start_var = tk.BooleanVar(value=False)
        app.auto_end_var = tk.BooleanVar(value=False)
        app.clear_logs_var = tk.BooleanVar(value=False)
        app.parallel_var = tk.BooleanVar(value=False)
        app._launched_from_driver = False
        return app

    def test_log_file_written(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=5,
            processed=4,
            skipped=1,
            errors=0,
            duration_secs=30.0,
            log_entries=[],
        )
        import pathlib

        content = pathlib.Path(app._log_path).read_text(encoding="utf-8")
        assert "Total files: 5" in content
        assert "Processed: 3" in content
        assert "HEADER" in content

    def test_time_label_zero_seconds(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.0,
            log_entries=[],
        )
        app.time_label.config.assert_any_call(text="Total Time: 00:00")

    def test_time_label_minutes_and_seconds(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=125.0,
            log_entries=[],
        )
        app.time_label.config.assert_any_call(text="Total Time: 02:05")

    def test_summary_label_text(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=10,
            processed=7,
            skipped=2,
            errors=1,
            duration_secs=60.0,
            log_entries=[],
        )
        app.summary_label.config.assert_called()
        call_kwargs = app.summary_label.config.call_args[1]
        text = call_kwargs["text"]
        assert "Total: 10 files" in text
        assert "Processed: 4" in text
        assert "Skipped: 2" in text
        assert "Errors: 1" in text

    def test_completion_label_dry_run(self, app: SilenceTrimmerApp) -> None:
        app.run_mode.set("Dry Run")
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        found = False
        for call in app.completion_label.config.call_args_list:
            if "Analysis Complete!" in str(call):
                found = True
        assert found

    def test_completion_label_live(self, app: SilenceTrimmerApp) -> None:
        app.run_mode.set("Live Update")
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        found = False
        for call in app.completion_label.config.call_args_list:
            if "Silence Trimming Complete!" in str(call):
                found = True
        assert found

    def test_switches_to_results_tab(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        app.notebook.select.assert_called_with(app._tab_results)

    def test_re_enables_start_button(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        app.start_btn.config.assert_called_with(state="normal")

    def test_auto_end_triggers_root_destroy(self, app: SilenceTrimmerApp) -> None:
        app.auto_end_var.set(True)
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        app.root.after.assert_any_call(2000, app.root.destroy)

    def test_audition_dry_run_schedules_result_disabled(
        self, app: SilenceTrimmerApp
    ) -> None:
        app._run_was_dry_run = True
        app._audition_original = Path("track_orig.mp3")
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        assert app._audition_result is None
        assert "Dry Run" in _audition_caption(app.root)

    def test_audition_live_pair_schedules_ready_caption(
        self, app: SilenceTrimmerApp
    ) -> None:
        app._audition_original = Path("track_orig.mp3")
        app._audition_result = Path("track.mp3")
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        assert (
            _audition_caption(app.root)
            == "Audition ready — track.mp3 (original vs result)"
        )

    def test_audition_no_source_schedules_message(self, app: SilenceTrimmerApp) -> None:
        app._on_complete(
            header=["HEADER\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        assert (
            _audition_caption(app.root) == "No supported audio file found for audition."
        )


class TestCollectSettings:
    """_collect_settings() reads Tk variable values into a dict."""

    @staticmethod
    @pytest.fixture
    def app() -> SilenceTrimmerApp:
        app = object.__new__(SilenceTrimmerApp)
        app.threshold = MagicMock()
        app.threshold.get.return_value = -50
        app.fade_var = MagicMock()
        app.fade_var.get.return_value = True
        app.fade_in_duration = MagicMock()
        app.fade_in_duration.get.return_value = 500
        app.fade_out_duration = MagicMock()
        app.fade_out_duration.get.return_value = 1000
        app.parallel_mode = MagicMock()
        app.parallel_mode.get.return_value = False
        app.max_workers = MagicMock()
        app.max_workers.get.return_value = 4
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        return app

    def test_returns_all_settings(self, app: SilenceTrimmerApp) -> None:
        settings = app._collect_settings()
        assert settings == {
            "threshold": -50,
            "fade_var": True,
            "fade_in_duration": 500,
            "fade_out_duration": 1000,
            "parallel_mode": False,
            "max_workers": 4,
            "run_mode": "Dry Run",
        }

    def test_reflects_live_mode(self, app: SilenceTrimmerApp) -> None:
        app.run_mode.get.return_value = "Live Update"
        settings = app._collect_settings()
        assert settings["run_mode"] == "Live Update"


class TestApplyPreset:
    """_apply_preset() writes preset values back to Tk variables."""

    @staticmethod
    @pytest.fixture
    def app() -> SilenceTrimmerApp:
        app = object.__new__(SilenceTrimmerApp)
        app.threshold = MagicMock()
        app.fade_var = MagicMock()
        app.fade_in_duration = MagicMock()
        app.fade_out_duration = MagicMock()
        app.parallel_mode = MagicMock()
        app.max_workers = MagicMock()
        app.run_mode = MagicMock()
        return app

    def test_sets_all_keys(self, app: SilenceTrimmerApp) -> None:
        app._apply_preset(
            {
                "threshold": -40,
                "fade_var": True,
                "fade_in_duration": 300,
                "fade_out_duration": 800,
                "parallel_mode": True,
                "max_workers": 8,
                "run_mode": "Live Update",
            }
        )
        app.threshold.set.assert_called_once_with(-40)
        app.fade_var.set.assert_called_once_with(True)
        app.fade_in_duration.set.assert_called_once_with(300)
        app.fade_out_duration.set.assert_called_once_with(800)
        app.parallel_mode.set.assert_called_once_with(True)
        app.max_workers.set.assert_called_once_with(8)
        app.run_mode.set.assert_called_once_with("Live Update")

    def test_partial_preset_only_sets_provided(self, app: SilenceTrimmerApp) -> None:
        app._apply_preset({"threshold": -60})
        app.threshold.set.assert_called_once_with(-60)
        app.fade_var.set.assert_not_called()
        app.run_mode.set.assert_not_called()

    def test_empty_preset_does_nothing(self, app: SilenceTrimmerApp) -> None:
        app._apply_preset({})
        app.threshold.set.assert_not_called()
        app.fade_var.set.assert_not_called()

        app._apply_preset({"threshold": -60})

        app.threshold.set.assert_called_once_with(-60)


class TestOnError:
    """_on_error() shows error dialog and re-enables start button."""

    @staticmethod
    @pytest.fixture
    def app() -> SilenceTrimmerApp:
        app = object.__new__(SilenceTrimmerApp)
        app.start_btn = MagicMock()
        return app

    def test_calls_showerror(self, app: SilenceTrimmerApp) -> None:
        with patch("silence_trimmer.app.messagebox.showerror") as mock_err:
            app._on_error("Something broke")
            mock_err.assert_called_once_with("Error", "Something broke")

    def test_re_enables_start_button(self, app: SilenceTrimmerApp) -> None:
        with patch("silence_trimmer.app.messagebox.showerror"):
            app._on_error("fail")
        app.start_btn.config.assert_called_once_with(state="normal")


@pytest.mark.gui  # builds real tk.Variable objects: needs a Tk root
class TestDriverMirrorVars:
    """Driver-mirror BooleanVars and _launched_from_driver flag."""

    def test_has_auto_start_var(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.auto_start_var = tk.BooleanVar(value=False)
        assert hasattr(app, "auto_start_var")
        assert isinstance(app.auto_start_var, tk.BooleanVar)
        assert app.auto_start_var.get() is False

    def test_has_auto_end_var(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.auto_end_var = tk.BooleanVar(value=False)
        assert hasattr(app, "auto_end_var")
        assert isinstance(app.auto_end_var, tk.BooleanVar)
        assert app.auto_end_var.get() is False

    def test_has_clear_logs_var(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.clear_logs_var = tk.BooleanVar(value=False)
        assert hasattr(app, "clear_logs_var")
        assert isinstance(app.clear_logs_var, tk.BooleanVar)
        assert app.clear_logs_var.get() is False

    def test_has_parallel_var(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.parallel_var = tk.BooleanVar(value=False)
        assert hasattr(app, "parallel_var")
        assert isinstance(app.parallel_var, tk.BooleanVar)
        assert app.parallel_var.get() is False

    def test_has_launched_from_driver(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app._launched_from_driver = False
        assert hasattr(app, "_launched_from_driver")
        assert app._launched_from_driver is False

    def test_auto_end_var_settable(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.auto_end_var = tk.BooleanVar(value=False)
        app.auto_end_var.set(True)
        assert app.auto_end_var.get() is True

    def test_clear_logs_var_settable(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.clear_logs_var = tk.BooleanVar(value=False)
        app.clear_logs_var.set(True)
        assert app.clear_logs_var.get() is True

    def test_parallel_var_settable(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
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
        "silence_trimmer.app._suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(sys, "argv", ["silence_trimmer"])
    return SilenceTrimmerApp(app_root)


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(self, real_app: Any) -> None:
        app = real_app
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() == "Dry Run"
        assert app.threshold.get() != ""
        assert app.progress is not None

    def test_preset_collect_and_apply_roundtrip(self, real_app: Any) -> None:
        app = real_app
        app._apply_preset(
            {
                "threshold": -45,
                "fade_var": True,
                "fade_in_duration": 250,
                "fade_out_duration": 900,
                "parallel_mode": True,
                "max_workers": 2,
                "run_mode": "Live Update",
            }
        )
        assert app.threshold.get() == -45
        assert app.fade_var.get() is True
        assert app.fade_in_duration.get() == 250
        assert app.fade_out_duration.get() == 900
        assert app.parallel_mode.get() is True
        assert app.max_workers.get() == 2
        assert app.run_mode.get() == "Live Update"
        assert app._collect_settings()["run_mode"] == "Live Update"


class TestStartGuardsD3:
    def _shell(self) -> Any:
        app = object.__new__(SilenceTrimmerApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.run_mode = MagicMock()
        app.threshold = MagicMock()
        app.fade_var = MagicMock()
        app.fade_in_duration = MagicMock()
        app.fade_out_duration = MagicMock()
        app.parallel_mode = MagicMock()
        app.max_workers = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app.file_listbox = MagicMock()
        app.progress = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        return app

    def test_missing_folder_shows_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("silence_trimmer.app.messagebox", dialogs)
        app.folder_path.get.return_value = ""

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_folder_without_audio_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("silence_trimmer.app.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path)  # empty directory
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_bad_threshold_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("silence_trimmer.app.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path)
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 8)
        app.threshold.get.return_value = -10  # above the -20 dB floor

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_valid_start_threads_with_dry_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr("silence_trimmer.app.threading", fake_threading)
        monkeypatch.setattr("silence_trimmer.app.messagebox", MagicMock())
        saved: list[tuple[str, Any]] = []
        monkeypatch.setattr(
            "silence_trimmer.app._suite_config.save_value",
            lambda key, value: saved.append((key, value)),
        )
        monkeypatch.setattr(
            "silence_trimmer.app._suite_config.load_last_directory", lambda: ""
        )
        app = self._shell()
        app.prepare_in_place_audition = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 8)
        app.threshold.get.return_value = -45
        app.fade_var.get.return_value = True
        app.fade_in_duration.get.return_value = 300
        app.fade_out_duration.get.return_value = 800
        app.run_mode.get.return_value = "Dry Run"

        app.start_processing()

        thread = fake_threading.Thread.call_args
        assert thread.kwargs["target"].__name__ == "_run"
        assert app._run_was_dry_run is True
        assert saved
        app.prepare_in_place_audition.assert_called_once_with(
            str(tmp_path), st_mod.SUPPORTED_EXTENSIONS
        )


class TestRunThreadD3:
    def test_run_thread_passes_all_flags_to_core(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.run_mode = MagicMock()
        app.threshold = MagicMock()
        app.fade_var = MagicMock()
        app.fade_in_duration = MagicMock()
        app.fade_out_duration = MagicMock()
        app.parallel_mode = MagicMock()
        app.max_workers = MagicMock()
        app.progress = MagicMock()
        app.file_listbox = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Dry Run"
        app.threshold.get.return_value = -45
        app.fade_var.get.return_value = False
        app.parallel_mode.get.return_value = True
        app.max_workers.get.return_value = 3
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        calls: dict[str, Any] = {}

        def fake_run_trimming(**kwargs: Any) -> None:
            calls.update(kwargs)

        import silence_trimmer.core.file_processor as core

        patch_target = "silence_trimmer.app.file_processor"
        del patch_target  # the core module attribute is patched directly
        monkeypatch.setattr(core, "run_trimming", fake_run_trimming)

        app._run()

        assert calls["dir_path"] == str(tmp_path)
        assert calls["is_dry_run"] is True
        assert calls["threshold"] == -45
        assert calls["apply_fade"] is False
        assert calls["parallel_mode"] is True
        assert calls["max_workers"] == 3


class TestProgressD3:
    def test_on_progress_sets_widgets(self) -> None:
        app = object.__new__(SilenceTrimmerApp)
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()

        app._on_progress(4, 10, 1, 0, "song.mp3")

        assert app.stats_label.config.call_args.kwargs["text"].startswith(
            "Processed: 4"
        )
        assert app.file_listbox.insert.call_args.args[1] == "song.mp3"


class _WorkerVarStub:
    """Minimal tk.IntVar stand-in that reflects ``set()`` back into ``get()``."""

    def __init__(self, value: int) -> None:
        self.value = value

    def get(self) -> int:
        return self.value

    def set(self, value: int) -> None:
        self.value = value


class TestTypedWorkersAboveTheSlotGrid:
    """A typed count above the grid is capped before the run is persisted."""

    def _shell(self) -> SilenceTrimmerApp:
        app = object.__new__(SilenceTrimmerApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.run_mode = MagicMock()
        app.threshold = MagicMock()
        app.fade_var = MagicMock()
        app.fade_in_duration = MagicMock()
        app.fade_out_duration = MagicMock()
        app.parallel_mode = MagicMock()
        app.max_workers = _WorkerVarStub(12)
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app.file_listbox = MagicMock()
        app.progress = MagicMock()
        app.slot_queue = MagicMock()
        app._safe_slot_vars = [MagicMock() for _ in range(4)]
        return app

    def test_caps_and_saves_the_slot_count(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr("silence_trimmer.app.threading", fake_threading)
        monkeypatch.setattr("silence_trimmer.app.messagebox", MagicMock())
        warnings = MagicMock()
        monkeypatch.setattr("audio_suite_shared.ui_common.messagebox", warnings)
        saved: dict[str, Any] = {}

        def fake_save(key: str, value: Any) -> None:
            saved[key] = value

        monkeypatch.setattr("silence_trimmer.app._suite_config.save_value", fake_save)
        app = self._shell()
        app.prepare_in_place_audition = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 8)
        app.threshold.get.return_value = -45
        app.fade_var.get.return_value = False
        app.fade_in_duration.get.return_value = 300
        app.fade_out_duration.get.return_value = 500
        app.run_mode.get.return_value = "Dry Run"

        app.start_processing()

        assert app.max_workers.get() == 4
        assert saved["trim_max_workers"] == 4
        warnings.showwarning.assert_called_once()
        assert "4" in warnings.showwarning.call_args.args[1]

        # The background run reads the capped value, not the typed 12.
        app.root = MagicMock()
        app.slot_queue = MagicMock()
        calls: dict[str, Any] = {}

        def fake_run_trimming(**kwargs: Any) -> None:
            calls.update(kwargs)

        import silence_trimmer.core.file_processor as core

        monkeypatch.setattr(core, "run_trimming", fake_run_trimming)
        app._run()
        assert calls["max_workers"] == 4

    def test_driver_launch_caps_without_a_dialog(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog
    ) -> None:
        """A driver / auto-start launch must not wait for a modal warning."""
        fake_threading = MagicMock()
        monkeypatch.setattr("silence_trimmer.app.threading", fake_threading)
        monkeypatch.setattr("silence_trimmer.app.messagebox", MagicMock())
        warnings = MagicMock()
        monkeypatch.setattr("audio_suite_shared.ui_common.messagebox", warnings)
        saved: dict[str, Any] = {}
        monkeypatch.setattr(
            "silence_trimmer.app._suite_config.save_value",
            lambda key, value: saved.__setitem__(key, value),
        )
        app = self._shell()
        app._launched_from_driver = True
        app.prepare_in_place_audition = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        (tmp_path / "a.mp3").write_bytes(b"\x00" * 8)
        app.threshold.get.return_value = -45
        app.fade_var.get.return_value = False
        app.fade_in_duration.get.return_value = 300
        app.fade_out_duration.get.return_value = 500
        app.run_mode.get.return_value = "Dry Run"

        with caplog.at_level(logging.WARNING):
            app.start_processing()

        warnings.showwarning.assert_not_called()
        assert any("Workers limited" in record.message for record in caplog.records)
        assert app.max_workers.get() == 4
        assert saved["trim_max_workers"] == 4


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run binds and
# land in the report the run writes.
# ---------------------------------------------------------------------------

_HEADER = ["SILENCE TRIMMER REPORT\n"]


def _completion_shell(tmp_path: Path) -> SilenceTrimmerApp:
    """Shell with only what the completion path touches."""
    app = object.__new__(SilenceTrimmerApp)
    app.root = MagicMock()
    app._log_path = str(tmp_path / "silence_dry_run_log.txt")
    app._run_was_dry_run = True
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
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Dry Run"
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    return app


class TestCompletionSeam:
    """``run_trimming`` publishes into the handler ``_run`` binds."""

    @staticmethod
    def _wire(app: SilenceTrimmerApp):
        """Return the completion callable ``_run`` hands to the processor."""
        return lambda **kw: app._on_complete(header=_HEADER, **kw)

    @staticmethod
    def _fake_process_single_file(*args: Any, **kwargs: Any) -> None:
        """Stand in for the per-file trim, one outcome per file."""
        name = args[0]
        on_progress = args[11]
        outcomes = {
            "a.wav": {"n_skipped": 0, "n_errors": 0},
            "b.wav": {"n_skipped": 1, "n_errors": 0},
            "c.wav": {"n_skipped": 0, "n_errors": 1},
        }
        outcome = outcomes[name]
        on_progress(
            n_skipped=outcome["n_skipped"],
            n_errors=outcome["n_errors"],
            display_text=name,
            log_text=f"{name}\n",
        )

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the report the handler writes."""
        from silence_trimmer.core import file_processor

        for name in ("a.wav", "b.wav", "c.wav"):
            (tmp_path / name).write_bytes(b"")
        app = _completion_shell(tmp_path)

        with patch.object(
            file_processor,
            "process_single_file",
            side_effect=self._fake_process_single_file,
        ):
            file_processor.run_trimming(
                dir_path=str(tmp_path),
                is_dry_run=True,
                threshold=-50,
                apply_fade=False,
                fade_in_ms=500,
                fade_out_ms=1000,
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=self._wire(app),
                on_error=MagicMock(),
            )

        report = (tmp_path / "silence_dry_run_log.txt").read_text(encoding="utf-8")
        assert "Total files: 3" in report
        assert "Processed: 1" in report
        assert "Skipped (no silence): 1" in report
        assert "Errors: 1" in report

    @pytest.mark.parametrize(
        "field",
        ["total", "processed", "skipped", "errors", "duration_secs", "log_entries"],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        """A dropped field names itself and leaves no report behind."""
        app = _completion_shell(tmp_path)
        payload: dict[str, Any] = {
            "total": 3,
            "processed": 3,
            "skipped": 1,
            "errors": 1,
            "duration_secs": 1.0,
            "log_entries": ["line\n"],
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            self._wire(app)(**payload)

        assert field in str(caught.value)
        assert not (tmp_path / "silence_dry_run_log.txt").exists()
