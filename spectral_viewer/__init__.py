"""Spectral Viewer — FFT spectrogram inspection and PNG export.

The package root deliberately re-exports only the GUI-free core. Importing
``spectral_viewer`` must not drag in tkinter or matplotlib, because the CLI
command that renders a batch of spectrograms never builds a window; the app is
imported explicitly by the launcher and the GUI tests.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

from .core.spectrogram import (
    DEFAULT_CMAP,
    DEFAULT_DB_RANGE,
    DEFAULT_HOP_LENGTH,
    DEFAULT_N_FFT,
    SpectrogramData,
    build_figure,
    compute_spectrogram,
    export_image,
    iter_audio_files,
    output_path_for,
    render_spectrogram,
)

__all__ = [
    "DEFAULT_CMAP",
    "DEFAULT_DB_RANGE",
    "DEFAULT_HOP_LENGTH",
    "DEFAULT_N_FFT",
    "SpectrogramData",
    "build_figure",
    "compute_spectrogram",
    "export_image",
    "iter_audio_files",
    "output_path_for",
    "render_spectrogram",
]
