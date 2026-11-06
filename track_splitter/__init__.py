"""track_splitter — split one long recording into tracks at its silent gaps.

The package is a batch tool: it scans a folder, detects the silent runs inside
each file, cuts each file at those runs and (optionally) writes a CUE sheet
beside the outputs.

Changed in 2.5.0: new package (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""
