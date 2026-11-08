"""channel_tools — apply one channel operation to a folder of audio files.

The tool is a thin consumer of the suite's shared pieces: the channel maths is
``audio_suite_shared.channel_ops``, the per-file batch is
``BaseFileProcessor.run_inplace_dsp_batch``, the CLI is ``cli_base`` and the
window is ``SuiteApp``.

Changed in 2.5.0: new package (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

__all__ = ["core", "utils"]
