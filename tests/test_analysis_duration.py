"""One analysis window for Key Detector and Mood Analyzer (PLAN D140).

Key Detector's ``--duration`` defaulted to 30 s while the GUI widget, its
argument dataclass, the Master Driver's ``key_duration`` and the shared decode
cap all said 90 s, so the same folder analysed three times more audio from the
window than from the command line and the two could disagree about a track.  An
entry point that meets the user gets its default from one constant.

The value is 90 s, not the BPM Analyzer's calibrated 30 s: key and mood have no
window-calibrated refusal gate, and both engines' features gain context from
more of the track (D140).  BPM's 20/30/90 s measurements are D139's.

Changed in 2.6.0: new lock for the single key/mood analysis window (D140).
Changed in 2.9.0: Key Detector owns its duration widget, so the lock follows the
widget onto the window (C1, D53).
Changed in 2.9.0: Mood Analyzer follows it off the shared base, so both windows
are checked the same way (C1 stage 3, D54).
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from audio_suite_shared.constants import (
    DEFAULT_ANALYSIS_SECONDS,
    DEFAULT_BPM_ANALYSIS_SECONDS,
)
from key_detector.cli import key as key_command
from key_detector.utils.cli_args import KeyDetectorArgs
from master_driver.state.app_state import AppState
from mood_analyzer.cli import mood_analyzer as mood_command
from mood_analyzer.utils.cli_args import MoodAnalyzerArgs


def _duration_param(command: object) -> object:
    """Return the ``--duration`` option of a click command."""
    params = getattr(command, "params")
    found: object = next(p for p in params if getattr(p, "name", None) == "duration")
    return found


class TestTheSharedWindow:
    """The value itself, and why it is not BPM's."""

    def test_the_constant_is_ninety_seconds(self) -> None:
        assert DEFAULT_ANALYSIS_SECONDS == 90, (
            f"the key/mood window is {DEFAULT_ANALYSIS_SECONDS}s, not the 90 s "
            "every entry point was unified on; change it only with measurements "
            "that show the analysis verdict is unchanged (D140)"
        )

    def test_it_is_not_the_bpm_window(self) -> None:
        """BPM's 30 s is measured against its periodicity floor (D139)."""
        assert DEFAULT_ANALYSIS_SECONDS != DEFAULT_BPM_ANALYSIS_SECONDS


class TestEveryEntryPointUsesIt:
    """Each default the user can meet resolves to the shared constant."""

    def test_the_parsed_defaults_are_the_shared_value(self) -> None:
        assert KeyDetectorArgs().analysis_duration == DEFAULT_ANALYSIS_SECONDS
        assert MoodAnalyzerArgs().analysis_duration == DEFAULT_ANALYSIS_SECONDS

    def test_the_key_cli_default_is_the_shared_value(self) -> None:
        param = _duration_param(key_command)
        default = getattr(param, "default")
        assert default == DEFAULT_ANALYSIS_SECONDS, (
            f"the key command defaults to {default}s while the GUI and the "
            f"Master Driver use {DEFAULT_ANALYSIS_SECONDS}s"
        )

    def test_the_mood_cli_default_is_the_shared_value(self) -> None:
        param = _duration_param(mood_command)
        default = getattr(param, "default")
        assert default == DEFAULT_ANALYSIS_SECONDS

    def test_both_help_texts_name_the_shared_value(self) -> None:
        for command in (key_command, mood_command):
            param = _duration_param(command)
            help_text = getattr(param, "help")
            assert f"default {DEFAULT_ANALYSIS_SECONDS}" in help_text, (
                f"{getattr(command, 'name')} --help advertises a different "
                f"default than it applies: {help_text!r}"
            )

    @pytest.mark.parametrize(
        ("module", "window"),
        [
            ("key_detector.app", "KeyDetectorApp"),
            ("mood_analyzer.app", "MoodAnalyzerApp"),
        ],
    )
    def test_each_window_owns_its_duration_widget(
        self, module: str, window: str
    ) -> None:
        """No tool is on the scaffold now, so each window is checked."""
        app_module = importlib.import_module(module)
        cls = getattr(app_module, window)

        source = inspect.getsource(cls.__init__)
        assert "DEFAULT_ANALYSIS_SECONDS" in source, (
            f"the {window} duration widget no longer reads the shared constant"
        )
        assert "value=90" not in source, (
            f"the {window} duration widget is a bare 90 again instead of "
            "the shared constant"
        )

    def test_the_driver_variables_start_at_the_shared_value(self) -> None:
        source = inspect.getsource(AppState.__init__)
        for name in ("key_duration", "mood_duration"):
            lines = [
                line
                for line in source.splitlines()
                if name in line and "StringVar" in line
            ]
            assert lines, f"{name} is no longer created in AppState.__init__"
            assert "DEFAULT_ANALYSIS_SECONDS" in lines[0], (
                f"AppState.{name} is a literal again: {lines[0].strip()}"
            )
