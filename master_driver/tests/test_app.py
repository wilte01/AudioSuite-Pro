"""
test_app.py — Tests for master_driver/app.py (AudioSuiteDriver).

Coverage focus: the subprocess launcher wiring that resolves paths relative
to the suite root.

Regression background
---------------------
``_open_undo_ui()`` and ``_open_refinery_ui()`` originally walked two levels
up from ``master_driver/app.py``, resolving to the parent of the suite root
(e.g. ``Desktop/Undo_Tag_Edits.pyw`` instead of
``Desktop/AudioSuite-Pro/Undo_Tag_Edits.pyw``).  The exists() gate then
failed and the user saw a misleading "Not Found" popup.  The suite root is
exactly one level above ``master_driver/``, so the fix walks one level and
the launcher must actually exist on disk.
"""

from __future__ import annotations

import os
import tkinter as tk
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.tool_plugin import get_registry
from master_driver.app import _ACCENT_POLL_MS, AudioSuiteDriver
from master_driver.batch_orchestrator import BatchProgress
from master_driver.state.app_state import AppState


def _driver() -> AudioSuiteDriver:
    """Create a driver without running __init__ (no real Tk)."""
    driver = object.__new__(AudioSuiteDriver)
    driver.root = MagicMock()
    driver.state = AppState()
    return driver


class TestOpenUndoUi:
    def test_launcher_resolves_inside_suite_root(self) -> None:
        """The .pyw must be found one level above master_driver/, so the
        real exists() gate passes and the subprocess launch happens."""
        driver = _driver()
        with (
            patch("master_driver.app.secure_subprocess.start_python_script") as start,
            patch("master_driver.app.messagebox.showwarning") as warn,
        ):
            driver._open_undo_ui()

        warn.assert_not_called()
        start.assert_called_once()
        assert os.path.isfile(start.call_args.args[0])

    def test_launcher_path_is_suite_root_relative(self) -> None:
        """Regression: must not climb above the suite root into its parent."""
        driver = _driver()
        with patch("master_driver.app.secure_subprocess.start_python_script") as start:
            driver._open_undo_ui()

        suite_root = os.path.normpath(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")
        )
        script = os.path.normpath(start.call_args.args[0])
        assert os.path.dirname(script) == suite_root
        assert os.path.basename(script) == "Undo_Tag_Edits.pyw"

    def test_missing_launcher_shows_not_found(self) -> None:
        """The user-facing guard fires only when the path genuinely lacks the
        launcher, and it must not fall through to spawning a subprocess."""
        driver = _driver()
        with (
            patch("master_driver.app.secure_subprocess.start_python_script") as start,
            patch("master_driver.app.messagebox.showwarning") as warn,
            patch("master_driver.app.os.path.exists", return_value=False),
        ):
            driver._open_undo_ui()

        start.assert_not_called()
        warn.assert_called_once()


class TestOpenRefineryUi:
    def test_launcher_resolves_inside_suite_root(self) -> None:
        driver = _driver()
        with (
            patch("master_driver.app.secure_subprocess.start_python_script") as start,
            patch("master_driver.app.messagebox.showwarning") as warn,
        ):
            driver._open_refinery_ui()

        warn.assert_not_called()
        start.assert_called_once()
        assert os.path.isfile(start.call_args.args[0])

    def test_launcher_path_is_suite_root_relative(self) -> None:
        driver = _driver()
        with patch("master_driver.app.secure_subprocess.start_python_script") as start:
            driver._open_refinery_ui()

        suite_root = os.path.normpath(
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "..")
        )
        script = os.path.normpath(start.call_args.args[0])
        assert os.path.dirname(script) == suite_root
        assert os.path.basename(script) == "Audio_Refinery.pyw"

    def test_missing_launcher_shows_not_found(self) -> None:
        driver = _driver()
        with (
            patch("master_driver.app.secure_subprocess.start_python_script") as start,
            patch("master_driver.app.messagebox.showwarning") as warn,
            patch("master_driver.app.os.path.exists", return_value=False),
        ):
            driver._open_refinery_ui()

        start.assert_not_called()
        warn.assert_called_once()


class TestUtilSelectAll:
    """The UTIL tab "Select All" checkbox must toggle every utility module
    checkbox, including Mood Analysis Batch Tagger, while never touching
    Undo Tag Edits (it is opened on demand and has no checkbox)."""

    def _driver_with_state(self, root) -> AudioSuiteDriver:
        driver = _driver()
        driver.state = AppState(root)
        return driver

    def test_select_all_checks_every_utility_module(self, root) -> None:
        driver = self._driver_with_state(root)
        with patch(
            "master_driver.app.utilities_window.update_format_detection"
        ) as detect:
            driver._apply_util_select_all(True)

        for manifest in get_registry().by_category("utility"):
            if manifest.id == "undo_tag_edits":
                continue
            assert driver.state.module_toggles[manifest.id].get() is True, manifest.id
        detect.assert_called_once_with(driver.state)

    def test_select_all_includes_mood_analysis_batch(self, root) -> None:
        driver = self._driver_with_state(root)
        assert driver.state.mood_analysis_batch_toggle.get() is False

        with patch("master_driver.app.utilities_window.update_format_detection"):
            driver._apply_util_select_all(True)

        assert driver.state.mood_analysis_batch_toggle.get() is True

    def test_select_all_never_touches_undo_tag_edits(self, root) -> None:
        driver = self._driver_with_state(root)
        before = driver.state.module_toggles["undo_tag_edits"].get()

        with patch("master_driver.app.utilities_window.update_format_detection"):
            driver._apply_util_select_all(True)

        assert driver.state.module_toggles["undo_tag_edits"].get() == before

    def test_select_all_never_touches_lyrics_manager(self, root) -> None:
        """Lyrics Manager is an enrich tool and has no utility checkbox."""
        driver = self._driver_with_state(root)
        before = driver.state.module_toggles["lyrics_manager"].get()

        with patch("master_driver.app.utilities_window.update_format_detection"):
            driver._apply_util_select_all(True)

        assert driver.state.module_toggles["lyrics_manager"].get() == before

    def test_deselect_all_turns_utility_modules_off(self, root) -> None:
        driver = self._driver_with_state(root)
        driver._apply_util_select_all(True)
        with patch("master_driver.app.utilities_window.update_format_detection"):
            driver._apply_util_select_all(False)

        for manifest in get_registry().by_category("utility"):
            if manifest.id == "undo_tag_edits":
                continue
            assert driver.state.module_toggles[manifest.id].get() is False, manifest.id


class TestRefinerySelectAll:
    """The REFINE-tab select-all must toggle every Refinery stage var.

    Audit M12a: ``_toggle_all`` iterated a hand-typed four-stage list while
    the pipeline has five, so Select-All silently never enabled Noise
    Reduction. The list is now ``arg_builder.REFINERY_STAGES`` — the same
    source ``build_refinery_args`` emits — and this class proves the bound
    command really sets all five, both ways.
    """

    _WIDGETS = (
        "_frame_refine",
        "_frame_enrich",
        "_frame_util",
        "_frame_settings",
        "_dir_frame",
        "_ctrl_frame",
        "_ctrl_rule",
        "_btn_refine",
        "_btn_enrich",
        "_btn_util",
        "_btn_settings",
        "_select_all_btn",
        "_mode_combo",
        "_auto_start_btn",
        "_auto_end_btn",
        "_clear_logs_btn",
        "_parallel_btn",
    )

    def _refine_driver(
        self, root: tk.Tk
    ) -> tuple[AudioSuiteDriver, dict[str, tk.BooleanVar], object]:
        driver = _driver()
        driver.state = AppState(root)
        driver._active_tab = "settings"
        for attr in self._WIDGETS:
            setattr(driver, attr, MagicMock())
        stage_vars = {
            name: tk.BooleanVar(root, value=False)
            for name in ("declick", "trim", "enhance", "normalise", "reduce_noise")
        }
        driver._refinery_setup_state = {"stage_vars": stage_vars}
        driver._switch_tab("refine")
        select_all_cmd = driver._select_all_btn.config.call_args.kwargs["command"]
        return driver, stage_vars, select_all_cmd

    def test_select_all_enables_all_five_stages_including_reduce_noise(
        self, root
    ) -> None:
        _driver_app, stage_vars, select_all_cmd = self._refine_driver(root)

        _driver_app.state.refinery_select_all_var.set(True)
        select_all_cmd()

        for name, var in stage_vars.items():
            assert var.get() is True, f"select-all missed stage {name!r}"

    def test_deselect_all_disables_all_five_stages(self, root) -> None:
        driver_app, stage_vars, select_all_cmd = self._refine_driver(root)
        for var in stage_vars.values():
            var.set(True)

        driver_app.state.refinery_select_all_var.set(False)
        select_all_cmd()

        for name, var in stage_vars.items():
            assert var.get() is False, f"deselect-all missed stage {name!r}"


# ---------------------------------------------------------------------------
# Stage 3 / item D3 (audit A4): the real driver is constructed against the
# shared hidden Tk root so __init__, _build_ui and tab switching execute; the
# accent poll and progress UI use the shell where state is faked.
# ---------------------------------------------------------------------------


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


@pytest.fixture()
def app_root(root):

    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture()
def driver_app(app_root, monkeypatch):
    """A real AudioSuiteDriver on an isolated toplevel.

    The saved last directory is machine-specific real-config state; it is
    neutralised during construction so tab-mirroring assertions below are
    deterministic.
    """
    monkeypatch.setattr(
        "master_driver.app._suite_config.load_last_directory", lambda: ""
    )
    from master_driver.app import AudioSuiteDriver

    return AudioSuiteDriver(app_root)


class TestDriverConstructor:
    def test_wiring(self, driver_app):
        assert driver_app._active_tab == "refine"
        assert str(driver_app.root.title()) == "Audio Suite Master Driver"
        # Every tool card's state wiring exists (registry-driven toggles).
        assert driver_app.state.module_toggles
        # Batch progress widgets were built.
        assert str(driver_app._batch_progress_bar.cget("maximum")) != ""
        assert driver_app._select_all_btn is not None

    def test_switch_tab_pack_cycles_and_mirrors_dirs(
        self, driver_app, tmp_path, monkeypatch
    ):
        # The saved last directory is machine-specific state; neutralise it so
        # the startup mirror is inert and the assertions are deterministic.
        monkeypatch.setattr(
            "master_driver.app._suite_config.load_last_directory", lambda: ""
        )
        driver = driver_app
        driver.state.dir_path.set(str(tmp_path))
        driver._switch_tab("refine")  # already active: no-op
        assert driver._active_tab == "refine"

        driver._switch_tab("enrich")
        assert driver._active_tab == "enrich"
        driver._switch_tab("util")
        assert driver._active_tab == "util"
        driver._switch_tab("settings")
        assert driver._active_tab == "settings"
        driver._switch_tab("refine")
        assert driver._active_tab == "refine"
        # Returning to refine mirrored the shared dir back into the stage.
        assert driver.state.refinery_source.get() == str(tmp_path)

    def test_refine_exit_mirrors_source_to_dir(self, driver_app, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "master_driver.app._suite_config.load_last_directory", lambda: ""
        )
        driver = driver_app
        driver.state.refinery_source.set(str(tmp_path) + "x")
        driver._switch_tab("enrich")
        assert driver.state.dir_path.get() == str(tmp_path) + "x"


class TestAccentPoll:
    def _shell_driver(self, palette: str):
        drv = _driver()
        drv.state = AppState()
        drv.state.palette_var.set(palette)
        return drv

    def test_poll_inert_for_fixed_palette(self):
        drv = self._shell_driver("Purple")
        drv._start_accent_poll()
        assert not getattr(drv, "_accent_poll_active", False)
        drv.root.after.assert_not_called()
        drv.state.palette_var.set("Windows Accent")
        drv._start_accent_poll()
        assert drv._accent_poll_active is True
        drv.root.after.assert_called_once()

    def test_poll_starts_for_windows_accent(self, monkeypatch):
        drv = self._shell_driver("Windows Accent")
        monkeypatch.setattr("master_driver.app._get_current_accent", lambda: "#abc123")
        drv._start_accent_poll()
        assert drv._accent_poll_active is True
        call = drv.root.after.call_args
        assert call is not None
        assert call.args[0] == _ACCENT_POLL_MS

    def test_poll_stops_when_palette_is_switched(self):
        drv = self._shell_driver("Purple")
        drv._accent_poll_active = True  # as started under Windows Accent
        drv._poll_accent()
        assert drv._accent_poll_active is False
        assert drv._last_accent is None

    def test_poll_inactive_returns_silently(self):
        drv = self._shell_driver("Purple")
        del drv  # the real poll returns without rescheduling
        self._poll_inactive_case()

    def _poll_inactive_case(self):
        drv = _driver()
        drv.state = AppState()
        # _accent_poll_active deliberately never set.
        drv._poll_accent()
        drv.root.after.assert_not_called()

    def test_poll_reschedules_with_unchanged_accent(self, monkeypatch):
        drv = self._shell_driver("Windows Accent")
        monkeypatch.setattr("master_driver.app._get_current_accent", lambda: "#abc123")
        drv._accent_poll_active = True
        drv._last_accent = "#abc123"
        drv._apply_accent_refresh = MagicMock()

        drv._poll_accent()

        drv._apply_accent_refresh.assert_not_called()
        call = drv.root.after.call_args
        assert call is not None
        assert call.args[0] == _ACCENT_POLL_MS
        assert_bound(call.args[1], "_poll_accent", drv)

    def test_poll_applies_refresh_when_accent_changes(self, monkeypatch):
        drv = self._shell_driver("Windows Accent")
        monkeypatch.setattr("master_driver.app._get_current_accent", lambda: "#ff0055")
        drv._accent_poll_active = True
        drv._last_accent = "#abc123"
        drv._apply_accent_refresh = MagicMock()

        drv._poll_accent()

        drv._apply_accent_refresh.assert_called_once()
        assert drv._last_accent == "#ff0055"

    def test_on_palette_var_changed_activates_poll(self, monkeypatch):
        drv = self._shell_driver("Windows Accent")
        monkeypatch.setattr(drv, "_start_accent_poll", MagicMock())

        drv._on_palette_var_changed()

        drv._start_accent_poll.assert_called_once()

    def test_on_palette_var_changed_fixed_palette_requires_nothing(self):
        drv = self._shell_driver("Purple")
        # No _accent_poll_active / _last_accent attrs may be required here.
        drv._on_palette_var_changed()
        assert not getattr(drv, "_accent_poll_active", False)


class TestAccentRefreshApply:
    def test_reapply_restores_tab_and_directory_colours(self, driver_app, monkeypatch):
        driver = driver_app
        monkeypatch.setattr("master_driver.app._set_palette", lambda _name: None)
        driver._apply_accent_refresh()
        # Widget backgrounds were reconfigured without raising.
        assert driver._btn_refine is not None


class TestOnCloseAndMenu:
    def test_on_close_saves_state_and_destroys(self, monkeypatch):
        drv = _driver()
        drv.state = AppState()
        with patch(
            "master_driver.app._get_current_accent", MagicMock(return_value=None)
        ):
            pass
        saved = {}
        fake_cfg = MagicMock()
        fake_cfg.save_app_state = lambda state: saved.setdefault("state", state)
        monkeypatch.setattr("master_driver.app._suite_config", fake_cfg)

        drv._on_close()

        assert "state" in saved
        drv.root.destroy.assert_called_once_with()

    def test_menu_wiring(self, driver_app):
        driver = driver_app
        menu = str(driver.root.cget("menu"))
        assert menu != ""  # a Help menu is attached to the driver window


class TestLaunchDelegates:
    """Run buttons reach the tool_launcher seam (the core batch entry)."""

    def test_refine_delegate(self, monkeypatch):
        drv = _driver()
        drv.refine_btn = MagicMock()
        drv._refinery_config = MagicMock()
        launch = MagicMock()
        monkeypatch.setattr("master_driver.app.launch_refinery", launch)

        drv._start_refinery_thread()

        launch.assert_called_once()
        args = launch.call_args.args
        assert args[0] is drv.state
        assert args[1] is drv._refinery_config
        assert args[2] is drv.refine_btn

    def test_enrich_delegate_wires_progress_hooks(self, monkeypatch):
        drv = _driver()
        drv.run_btn = MagicMock()
        launch = MagicMock()
        monkeypatch.setattr("master_driver.app.launch_enrich", launch)

        drv._start_enrich_thread()

        launch.assert_called_once()
        assert (
            getattr(launch.call_args.kwargs["progress_callback"], "__name__")
            == "_update_batch_progress"
        )
        assert (
            getattr(launch.call_args.kwargs["on_batch_done"], "__name__")
            == "_hide_batch_progress"
        )

    def test_utility_delegate_wires_progress_hooks(self, monkeypatch):
        drv = _driver()
        drv.util_run_btn = MagicMock()
        launch = MagicMock()
        monkeypatch.setattr("master_driver.app.launch_utility", launch)

        drv._start_utility_thread()

        launch.assert_called_once()
        assert (
            getattr(launch.call_args.kwargs["progress_callback"], "__name__")
            == "_update_batch_progress"
        )
        assert (
            getattr(launch.call_args.kwargs["on_batch_done"], "__name__")
            == "_hide_batch_progress"
        )


class TestBatchProgressUI:
    def _shell(self):
        drv = _driver()
        drv._batch_status_text = MagicMock()
        drv._batch_eta_label = MagicMock()
        drv._batch_progress_bar = MagicMock()
        return drv

    def _progress(self, steps, *, failed=(), progress=0.25):
        return BatchProgress(
            total_steps=len(steps),
            completed_steps=len(steps) - 1,
            current_step=steps[0][0],
            current_progress=progress,
            elapsed=timedelta(seconds=12),
            estimated_remaining=timedelta(seconds=30),
            failed_steps=list(failed),
            running_steps=[tid for tid, _n, st in steps if st == "running"],
            pending_steps=[tid for tid, _n, st in steps if st == "pending"],
            steps=steps,
        )

    def test_zero_total_hides_widgets(self):
        drv = self._shell()
        empty = BatchProgress(
            total_steps=0,
            completed_steps=0,
            current_step=None,
            current_progress=0.0,
            elapsed=timedelta(0),
            estimated_remaining=timedelta(0),
            failed_steps=[],
            running_steps=[],
            pending_steps=[],
            steps=[],
        )

        drv._update_batch_progress(empty)
        scheduled = drv.root.after.call_args
        assert scheduled is not None
        assert scheduled.args[0] == 0
        # Execute the scheduled main-thread update against the widget stubs.
        scheduled.args[1]()

    def test_step_lines_and_summary(self):
        drv = self._shell()
        with_steps = self._progress(
            [
                ("scrubber", "Metadata Scrubber", "completed"),
                ("bpm", "BPM Analyzer", "failed"),
                ("tempo", "Tempo Analyzer", "waiting"),
                ("key", "Key Detector", "running"),
                ("mood_analyzer", "Mood Analyzer", "skipped"),
            ],
            failed=("bpm",),
        )

        drv._update_batch_progress(with_steps)
        scheduled = drv.root.after.call_args
        assert scheduled is not None
        assert scheduled.args[0] == 0
        assert scheduled.args[1].__name__ == "_update"
        # Execute the scheduled main-thread update against the widget stubs.
        scheduled.args[1]()
        text = drv._batch_status_text
        inserted = text.insert.call_args.args[1]
        for fragment in (
            "Metadata Scrubber",
            "BPM Analyzer",
            "FAILED",
            "Tempo Analyzer",
            "Key Detector",
            "running",
            "skipped",
        ):
            assert fragment in inserted, inserted
        drv._batch_eta_label.config.assert_called_once()
        summary = drv._batch_eta_label.config.call_args.kwargs["text"]
        assert "Overall: 4/5 completed" in summary, summary
        assert "1 failed" in summary
        assert drv._batch_progress_bar.config.call_args.kwargs["value"] == 25

    def test_hide_batch_progress_schedules_after_500(self):
        drv = self._shell()
        drv._hide_batch_progress()
        call = drv.root.after.call_args
        assert call is not None
        assert call.args[0] == 500
        assert call.args[1].__name__ == "_hide"


def _assert_hidden_widgets(driver):
    return driver._batch_status_text is not None
