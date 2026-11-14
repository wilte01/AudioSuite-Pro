"""pitch_time — batch tempo and pitch transforms.

The package holds one engine (:mod:`pitch_time.core.engine`), its settings
(:mod:`pitch_time.core.models`), the window (:mod:`pitch_time.app`) and the
launcher's argument parser (:mod:`pitch_time.utils.cli_args`).  The transforms
themselves live in :mod:`audio_suite_shared.dsp_time_pitch`, because a second
tool that stretches or shifts audio must import them rather than grow a copy.

Changed in 2.7.0: new package (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""
