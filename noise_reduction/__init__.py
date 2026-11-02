"""Noise Reduction — the hum/broadband reducer REFINE's Reduce Noise stage runs.

Changed in 2.6.0 (U-04): the standalone window is gone, so this package no
longer exports an application class.  It is the pipeline's library:
``noise_reduction.core.noise_reducer`` does the repair and REFINE binds
``noise_reduction.core.models.NoiseReductionParams`` for its own panel.

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).
"""

from __future__ import annotations

__all__: list[str] = []
