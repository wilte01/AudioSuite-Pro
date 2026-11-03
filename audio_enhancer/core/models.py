"""
core/models.py
Data classes and enumerations shared across the application.

Changed in 2.4.1: ``PresetName``, ``EnhancementParams`` and ``PRESETS`` are
re-exported from ``audio_suite_shared.dsp_models`` instead of being defined
here. The two definitions had drifted — class default ``output_gain_db`` of 0.0
here against 4.0 in the shared copy, and a ``(str, Enum)`` base against a plain
``Enum`` — so the pipeline could apply a preset whose label and gain disagreed
with the table the UI displayed
(PLAN_2026-11-03_2.4.1_stop_the_drift.md WP-0).

Changed in 2.4.1: ``JobStatus``, ``AudioFileInfo`` and ``ProcessingResult``
went with WP-3 — nothing imported them once the enhancer became a Refinery
stage, so this module is now only the shared model's re-export home.
"""

from __future__ import annotations

from audio_suite_shared.dsp_models import PRESETS as PRESETS
from audio_suite_shared.dsp_models import (
    EnhancementParams as EnhancementParams,
)
from audio_suite_shared.dsp_models import PresetName as PresetName
