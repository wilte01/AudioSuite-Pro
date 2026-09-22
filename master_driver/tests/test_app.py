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
from unittest.mock import MagicMock, patch

from audio_suite_shared.tool_plugin import get_registry
from master_driver.app import AudioSuiteDriver
from master_driver.state.app_state import AppState


def _driver() -> AudioSuiteDriver:
    """Create a driver without running __init__ (no real Tk)."""
    driver = object.__new__(AudioSuiteDriver)
    driver.root = MagicMock()
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
