"""Audio Enhancer — the DSP chain and presets REFINE's Enhance stage runs.

Changed in 2.6.0 (U-04): the standalone window is gone, so this package no
longer exports an application class.  It is the pipeline's library: the shared
DSP chain reads ``audio_enhancer.core.models`` and REFINE embeds
``audio_enhancer.ui.setup_tab``.

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).
"""

from __future__ import annotations

__all__: list[str] = []
