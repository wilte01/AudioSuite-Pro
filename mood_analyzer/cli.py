"""CLI command for Mood Analyzer.

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: a fatal run now exits 1 instead of 0 (``finish_run``), while a
run whose only failures were per-file keeps its exit status (PLAN D92).
Changed in 2.6.0: ``--duration`` defaults to ``DEFAULT_ANALYSIS_SECONDS``, the
window the GUI and the Master Driver use (D140).

Changed in 2.9.0: the command is built by analysis_cli.analysis_command (B3).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from audio_suite_shared.analysis_cli import analysis_command


def _processor() -> Callable[..., Any]:
    """Return this tool's batch processor, imported on first use."""
    from mood_analyzer.core.file_processor import run_analysis

    return run_analysis


mood_analyzer = analysis_command(
    name="mood-analyzer",
    tool_title="Mood Analyzer",
    payload_tag="mood-analyzer",
    batch_tool="mood_analyzer",
    summary="Detect and tag mood from the audio signal itself.",
    processor=_processor,
)
