"""One BPM analysis window, read by every entry point (PLAN D139).

The core defaulted to 90 s while the ``bpm`` command defaulted to 30 s, so the
same file could be refused as beatless by one entry point and tagged by
another: the harmonic-comb gate is a stationarity test, and on real music it
loses score as the window grows (two library tracks measured 0.139/0.194 over
30 s and 0.094/0.071 over 90 s against the 0.10 floor).

This module fails if any default the user can meet drifts from the shared
constant.  The GUI's initial variable and the Master Driver's variable are
locked in their own packages' tests, where the Tk root fixtures live.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from audio_suite_shared.cli_dataclasses import BPMArgs
from audio_suite_shared.constants import DEFAULT_BPM_ANALYSIS_SECONDS
from bpm_analyzer.app import BPMAnalyzerApp
from bpm_analyzer.cli import bpm as bpm_command
from bpm_analyzer.core.bpm_detector import detect_bpm


class TestOneWindowForEveryEntryPoint:
    """Every default the user can meet is the same calibrated number."""

    def test_the_constant_itself_is_the_calibrated_window(self) -> None:
        """30 s is a measured number, not a speed preference (D139)."""
        assert DEFAULT_BPM_ANALYSIS_SECONDS == 30, (
            f"the shared window is {DEFAULT_BPM_ANALYSIS_SECONDS}s, not the "
            "calibrated 30 s: at 20 s seeded noise reaches 0.090 against the "
            "0.10 floor (1.11x) and at 90 s real music falls to 0.071-0.094 "
            "and a tenth of a real library is refused. Re-derive the window "
            "from a re-measured corpus (D139's method), never to make a run "
            "faster"
        )

    def test_the_core_default_is_the_shared_value(self) -> None:
        default = inspect.signature(detect_bpm).parameters["max_duration"].default
        assert default == DEFAULT_BPM_ANALYSIS_SECONDS, (
            f"detect_bpm defaults to {default}s, not the shared "
            f"{DEFAULT_BPM_ANALYSIS_SECONDS}s window the gate was calibrated on"
        )

    def test_the_parsed_cli_default_is_the_shared_value(self) -> None:
        assert BPMArgs().duration == DEFAULT_BPM_ANALYSIS_SECONDS

    def test_the_cli_option_default_is_the_shared_value(self) -> None:
        param = next(p for p in bpm_command.params if p.name == "duration")
        assert param.default == DEFAULT_BPM_ANALYSIS_SECONDS

    def test_the_gui_preset_fallback_is_the_shared_value(self) -> None:
        """A preset with no duration must not restore the old 90 s."""
        app = object.__new__(BPMAnalyzerApp)
        for name in (
            "bpm_range_min",
            "bpm_range_max",
            "analysis_duration",
            "parallel_mode",
            "max_workers",
            "run_mode",
        ):
            setattr(app, name, MagicMock())

        app._apply_preset({})

        app.analysis_duration.set.assert_called_once_with(DEFAULT_BPM_ANALYSIS_SECONDS)


# Changed in 2.6.0: new lock for the single BPM analysis window (D139).
