"""
stem_separator
==============
ML stem separation for AudioSuite-Pro: Demucs splits a mixed track into its
vocals, drums, bass and other components, which are written as individual
files (and optionally recombined into a mix) in an output directory.

The source file is never modified, so the tool has no undo record to keep: the
originals stay exactly as they were and the stems are new files.

Sub-modules
-----------
app
    Tkinter GUI application (thin orchestrator).
core
    Demucs adapter, result models and the batch processor.
ui
    Widget builders: setup_tab, processing_tab, results_tab.
utils
    CLI argument parsing.
"""

from __future__ import annotations

__all__ = ["StemSeparatorApp"]


def __getattr__(name: str) -> object:
    if name == "StemSeparatorApp":
        from .app import StemSeparatorApp

        return StemSeparatorApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
