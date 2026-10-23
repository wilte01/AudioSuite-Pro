"""
ml_denoiser
===========
Neural noise reduction for AudioSuite-Pro: RNNoise (a recurrent network trained
on speech) estimates a speech probability per 10 ms frame and reconstructs each
frame with the noise-band content suppressed.

This is the ML sibling of the signal-based ``noise_reduction`` tool, kept as its
own package so the scipy/STFT path stays installable without the ``ml`` extra.
It rewrites files in place, so every live run records an undo snapshot.

Sub-modules
-----------
app
    Tkinter GUI application (in-place repair scaffold).
core
    RNNoise adapter, result models and the batch processor.
ui
    Widget builders: setup_tab, processing_tab, results_tab.
utils
    CLI argument parsing.

Changed in 2.0.0: created for the ML Denoiser (PLAN_feature_expansion.md Item 6.2).
"""

from __future__ import annotations

__all__ = ["MlDenoiserApp"]


def __getattr__(name: str) -> object:
    if name == "MlDenoiserApp":
        from .app import MlDenoiserApp

        return MlDenoiserApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
