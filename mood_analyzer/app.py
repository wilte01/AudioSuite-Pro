"""
app.py
MoodAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Everything shared with Key Detector lives in
:mod:`audio_suite_shared.analysis_app_base`; this module supplies Mood
Analyzer's literals and the one analysis call.

Changed in 1.2.0: records the tracks the run had to skip as a run note, so a
batch report says so instead of only the tool's own log.
"""

from __future__ import annotations

from typing import Any, ClassVar

from audio_suite_shared.analysis_app_base import AnalysisAppBase
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.run_outcome import record_caveats, shortfall

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

#: The Master Driver keys this tool's batch step — and therefore its run note
#: — by the manifest id.  It happens to equal the window key below, but the
#: constant is separate because the two keys are owned by different layers.
DRIVER_TOOL_ID = "mood_analyzer"


class MoodAnalyzerApp(AnalysisAppBase):
    """Mood Analyzer application GUI."""

    TOOL_ID: ClassVar[str] = "mood_analyzer"
    APP_TITLE: ClassVar[str] = "Mood Analyzer & Tagger"
    WINDOW_NAME: ClassVar[str] = "mood_analyzer_window"
    HELP_GUIDE: ClassVar[str] = "Mood_Analyzer_User_Guide.docx"

    SETTINGS_PREFIX: ClassVar[str] = "mood"
    STARTING_STATUS: ClassVar[str] = "Detecting mood from the audio signal..."
    REPORT_HEADER: ClassVar[str] = "MOOD DETECTION REPORT"
    SKIPPED_SUMMARY_LABEL: ClassVar[str] = "Skipped (undecodable/silent)"
    LIVE_COMPLETION_TEXT: ClassVar[str] = "Mood Tagging Complete!"

    SETUP_TAB: ClassVar[Any] = setup_tab
    PROCESSING_TAB: ClassVar[Any] = processing_tab
    RESULTS_TAB: ClassVar[Any] = results_tab
    CLI_ARGS: ClassVar[Any] = cli_args

    def _run_analysis(self, run_kwargs: dict[str, Any]) -> None:
        file_processor.run_analysis(**run_kwargs)

    # The ``handle_audio_errors`` context string is bound at decoration time,
    # so this thin override cannot be shared with Key Detector.
    @handle_audio_errors(reraise=False, context="mood_analyzer_app_run")
    def _run(self) -> None:
        self._run_batch()

    def _record_run_note(self, *, total: int, skipped: int, errors: int) -> None:
        """Record the tracks this run could not produce a mood for.

        Called by the shared completion path before it writes the report, so a
        damaged Tk or an unwritable log cannot suppress the note the Master
        Driver reads.  Surfacing the skipped count is the point: the Results
        summary already labels it "Skipped (undecodable/silent)", and that is
        exactly what a batch operator needs to know about a track the run
        finished without tagging.  A clean run records nothing, which clears
        any earlier note.

        Args:
            total: Files the run attempted.
            skipped: Files skipped as undecodable or near-silent.
            errors: Files whose analysis or tag write failed unexpectedly.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(
                skipped, total, "track", "had no usable audio (undecodable or silent)"
            )
            if skipped
            else "",
            shortfall(errors, total, "track", "could not be analyzed")
            if errors
            else "",
        )
