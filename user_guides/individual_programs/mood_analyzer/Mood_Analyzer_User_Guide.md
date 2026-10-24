---
title: Mood Analyzer - User Guide
subtitle: Based on the current Mood Analyzer implementation
---

## Overview

Mood Analyzer estimates musical mood directly from the audio signal. It analyzes a selected directory, derives arousal and valence features, maps them to three mood words, and can write mood, confidence, and energy metadata. It does not rely on pre-existing mood tags.

The standalone tool processes one directory. For recursive whole-library processing, use Mood Analysis Batch Tagger. Both tools use the same underlying mood analysis engine.

## Supported Files

The analyzer uses the shared Audio Suite supported audio extensions, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV, and AIFF variants. Subfolders are not descended into by this standalone tool.

## Quick Start

1. Open Mood_Analyzer.pyw.
1. Select the directory containing the audio files.
1. Choose an analysis duration and optional parallel settings.
1. Leave Dry Run selected for the first pass.
1. Click the analysis start button.
1. Review the per-file results and mode-specific log.
1. Run again in Live Update when you want mood tags written.

## Setup

Setup contains the directory picker, run mode, analysis duration, parallel worker controls, presets, and shared run controls. The last-used directory and parallel settings are stored in shared suite configuration.

- **Analysis Duration: **The GUI defaults to 90 seconds. The CLI accepts 10 through 600 seconds. Shorter values are faster but sample less of each track.
- **Parallel Processing: **When enabled, CPU-bound mood analysis uses ProcessPoolExecutor; otherwise the thread-based path is used.
- **Workers: **Sets the maximum worker count; the default is one worker per logical CPU, capped at 8.
- **Presets: **Save and restore directory, mode, duration, parallel mode, and worker count.
- **Dry Run / Live Update: **Dry Run reports without writing. Live Update writes the derived values to files.

## Mood Model

The signal mood engine scores two axes. Arousal represents energy versus calm and uses tempo, spectral flux, zero-crossing rate, and RMS energy. Valence represents positive versus dark character and uses musical mode, key-detection strength, spectral brightness, and low-band energy. The resulting point is mapped to three descriptive words.

- **Mood words: **Stored as a semicolon-separated string such as Energetic;Bright;Confident.
- **Confidence: **A decimal from 0 to 1 describing how strongly the analysis matched.
- **Energy: **An integer band from 1, calm, through 6, very energetic.

## Processing Behavior

1. Discover supported audio files directly inside the selected directory.
1. Load each file for the configured analysis duration.
1. Analyze the signal and derive mood, confidence, and energy.
1. In Dry Run, report the values without writing metadata.
1. In Live Update, write the mood, confidence, and energy tags.
1. Write the mode-specific report and show the final summary.

## Dry Run and Live Update

- **Dry Run: **Analyzes and reports each file without changing it.
- **Live Update: **Writes the three mood-related values through the shared tag helpers.
- **Undecodable or silent files: **They are skipped and not written; analysis failures are reflected in the summary and log.
- **Errors: **Unexpected failures are counted separately from ordinary skipped analysis files.
- **Undo: **Live tag writes run inside the suite tag-edit batch and can be reverted when snapshots are available.

## Processing and Results

Processing shows four worker slots, progress, processed/skipped/error counts, and per-file status messages. Results reports total files, analyzed/tagged files, skipped files, errors, and elapsed time. The tool can open the source folder and the generated log.

## Logs

- **Dry Run log: **mood_dry_run_log.txt in the selected directory.
- **Live log: **mood_sync_log.txt in the selected directory.
- **Contents: **Mode, analysis duration, parallel settings, per-file mood results, skips, errors, counts, and elapsed time.

## Command Line

The registered command is mood-analyzer. Examples:

python -m audio_suite_shared.cli_app mood-analyzer <folder> --dry\
python -m audio_suite_shared.cli_app mood-analyzer <folder> --duration 60\
python -m audio_suite_shared.cli_app mood-analyzer <folder> --parallel --workers 4\
python -m audio_suite_shared.cli_app mood-analyzer <folder> --live --json

The CLI accepts --duration, --parallel/--no-parallel, --workers, the shared dry-run/live option, and --json. Its text summary reports processed, skipped, errors, and elapsed time.

## Master Driver Use

From the Master Driver, open ENRICH and select Mood Analyzer. The driver passes the directory, mode, duration, worker settings, start/end behavior, and orchestration flags through the launch handshake. A driven launch can auto-start and displays inherited controls.

## Troubleshooting

- **No supported files found: **Select a directory containing supported audio files directly in that folder.
- **A file is skipped: **It may be undecodable, unsupported by the active decoder, or effectively silent.
- **The mood seems subjective: **The result is signal-derived from measurable audio features, not lyrics, genre tags, or personal judgment.
- **Results differ after changing duration: **The analyzer samples a different portion of the track; longer durations can provide more context but take longer.
- **Parallel processing fails: **Disable parallel mode or reduce worker count if process startup or resources are constrained.
- **Tags did not change: **Confirm Live Update was selected. Dry Run never writes metadata.

## Safety and Recovery

Run Dry Run first and review the log. Live Update modifies metadata in place, so keep backups of important files and use the suite's Undo Tag Edits workflow for available snapshots.
