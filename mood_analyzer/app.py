"""
app.py
MoodAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Everything shared with Key Detector lives in
:mod:`audio_suite_shared.analysis_app_base`; this module supplies Mood
Analyzer's literals and the one analysis call.
"""

from __future__ import annotations

from typing import Any, ClassVar

from audio_suite_shared.analysis_app_base import AnalysisAppBase
from audio_suite_shared.exceptions import handle_audio_errors

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args


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
