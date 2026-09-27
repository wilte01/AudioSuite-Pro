"""
app.py
KeyDetectorApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Everything shared with Mood Analyzer lives in
:mod:`audio_suite_shared.analysis_app_base`; this module supplies Key
Detector's literals and the one analysis call.
"""

from __future__ import annotations

from typing import Any, ClassVar

from audio_suite_shared.analysis_app_base import AnalysisAppBase
from audio_suite_shared.exceptions import handle_audio_errors

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args


class KeyDetectorApp(AnalysisAppBase):
    """Key Detector application GUI."""

    TOOL_ID: ClassVar[str] = "key_detector"
    APP_TITLE: ClassVar[str] = "Key Detector & Tagger"
    WINDOW_NAME: ClassVar[str] = "key_detector_window"
    HELP_GUIDE: ClassVar[str] = "Key_Detector_User_Guide.docx"

    SETTINGS_PREFIX: ClassVar[str] = "key"
    STARTING_STATUS: ClassVar[str] = "Detecting musical keys..."
    REPORT_HEADER: ClassVar[str] = "KEY DETECTION REPORT"
    SKIPPED_SUMMARY_LABEL: ClassVar[str] = "Skipped (already tagged)"
    LIVE_COMPLETION_TEXT: ClassVar[str] = "Key Tagging Complete!"

    SETUP_TAB: ClassVar[Any] = setup_tab
    PROCESSING_TAB: ClassVar[Any] = processing_tab
    RESULTS_TAB: ClassVar[Any] = results_tab
    CLI_ARGS: ClassVar[Any] = cli_args

    def _run_analysis(self, run_kwargs: dict[str, Any]) -> None:
        file_processor.run_analysis(**run_kwargs)

    # The ``handle_audio_errors`` context string is bound at decoration time,
    # so this thin override cannot be shared with Mood Analyzer.
    @handle_audio_errors(reraise=False, context="key_detector_app_run")
    def _run(self) -> None:
        self._run_batch()
