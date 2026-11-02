"""Audio Normalizer — loudness measurement and normalisation for REFINE.

Changed in 2.6.0 (U-04): the standalone window is gone, so this package no
longer exports an application class.  It is the pipeline's library:
``audio_normalizer.core.loudness`` measures and ``.core.normalizer`` applies
loudnorm, while REFINE embeds ``audio_normalizer.ui.setup_tab``.

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).
"""

from __future__ import annotations

__all__: list[str] = []
