"""audio_joiner — join recordings end to end, with optional gaps or crossfades.

The package holds one join engine (:mod:`audio_joiner.core.join`), its plan
(:mod:`audio_joiner.core.models`), the compatibility probe
(:mod:`audio_joiner.core.compat`) and the equal-power overlap
(:mod:`audio_joiner.core.crossfade`).  ``audio_joiner.app`` is the window;
``audiosuite join`` is the command.

Changed in 2.5.0: new package (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""
