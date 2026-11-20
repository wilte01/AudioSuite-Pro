"""CLI command for Key Detector.

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
    from key_detector.core.file_processor import run_analysis

    return run_analysis


key = analysis_command(
    name="key",
    tool_title="Key Detector",
    payload_tag="key",
    batch_tool="key_detector",
    summary="Detect and tag musical key.",
    processor=_processor,
)
