---
title: Mood Analysis Batch Tagger - User Guide
subtitle: Based on the current Mood Analysis Batch Tagger implementation
---

## Overview

Mood Analysis Batch Tagger recursively scans a root music directory and all of its subfolders, analyzes mood from the audio signal, and can write mood, confidence, and energy tags. It uses the same signal mood engine as the standalone Mood Analyzer, so the same track produces the same values in both tools.

## Supported Files

The batch engine uses the shared Audio Suite supported extensions, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV, and AIFF variants. Unsupported files are ignored.

## Quick Start

1. Open Mood_Analysis_Batch_Tagger.pyw.
1. Select the root directory containing your music library.
1. Choose an analysis duration and optional parallel processing settings.
1. Leave Dry Run selected for the first pass.
1. Click the batch analysis start button.
1. Review folders, per-file results, counts, and the log.
1. Run again in Live Update when you want mood tags written.

## Setup

Setup contains the root folder, mode, duration, worker settings, presets, and shared run controls. The root directory is scanned recursively. Duration and parallel settings are saved in shared suite configuration.

- **Analysis Duration: **The default is 90 seconds. The CLI and parser allow 10 through 600 seconds. Shorter windows are faster but sample less of each track.
- **Parallel Processing: **When enabled, CPU-bound mood analysis uses ProcessPoolExecutor to bypass the GIL. When disabled, a thread pool is used.
- **Workers: **Sets the maximum worker count; the default is one worker per logical CPU, capped at 8.
- **Presets: **Save and restore root directory, mode, duration, parallel mode, and worker count.
- **Dry Run / Live Update: **Dry Run analyzes without writing. Live Update writes the mood tags.

## Mood Analysis

The shared signal analyzer derives two axes from the audio: arousal, representing energy or calmness, and valence, representing positive or dark character. Features include tempo, spectral flux, zero-crossing rate, RMS energy, musical mode, spectral brightness, and low-frequency energy. The axes are mapped to three mood words, a confidence score from 0 to 1, and an energy band from 1 to 6.

- **Mood value: **Stored as three semicolon-separated words such as Energetic;Bright;Confident.
- **Confidence: **Stored as a decimal such as 0.87 indicating how strongly the analysis matched.
- **Energy: **Stored as an integer band from 1, calm, through 6, very energetic.

## Batch Workflow

1. Walk the root directory recursively and sort folders and filenames.
1. Enter each folder in the Processing display and count its supported files.
1. Load and analyze each file through the shared Mood Analyzer engine.
1. In Dry Run, report the values without writing tags.
1. In Live Update, record a tag snapshot and write mood, confidence, and energy fields.
1. Write mood_analysis_batch_log.txt in the root directory and report final counts.

## Dry Run and Live Update

- **Dry Run: **Reports the mood that would be written and leaves source files unchanged.
- **Live Update: **Writes the three mood-related metadata values to each successfully analyzed file.
- **Skipped files: **Files that cannot be decoded or analyzed, including unsupported/corrupt/silent audio, are counted as skipped when the failure is a known analysis or codec issue.
- **Errors: **Unexpected failures are counted separately as errors and recorded in the log.
- **Undo: **Live writes use the suite tag-edit batch and can be reverted through Undo Tag Edits when snapshots are available.

## Processing and Results

Processing shows folders as they are entered, four active worker slots, file progress, and tagged/skipped/error counts. A successful file appears as OK in Live Update or a dry-run entry describing the values that would be written.

Results reports folders scanned, files analyzed, files tagged, skipped files, and errors. Open Folder opens the root directory and View Log opens the generated batch report.

## Log File

Each completed run writes mood_analysis_batch_log.txt in the selected root directory. The log records mode, timestamp, root, file count, duration, parallel settings, folder sections, per-file mood/confidence/energy information, skips, errors, and final totals.

## Command Line

The registered command is mood-analysis-batch. Examples:

python -m audio_suite_shared.cli_app mood-analysis-batch <folder> --dry\
python -m audio_suite_shared.cli_app mood-analysis-batch <folder> --duration 60\
python -m audio_suite_shared.cli_app mood-analysis-batch <folder> --parallel --workers 4\
python -m audio_suite_shared.cli_app mood-analysis-batch <folder> --json

Options include --duration, --parallel/--no-parallel, --workers, the shared dry-run/live option, and --json. The CLI returns directory, duration, mode, worker settings, tagged, skipped, error, folder, and log-path values.

## Master Driver Use

From the Master Driver, open UTIL and select Mood Analysis Batch Tagger. The driver passes the root directory, mode, duration, worker settings, start/end behavior, and orchestration flags through the launch handshake. A driven launch can auto-start and displays inherited controls.

## Troubleshooting

- **A folder was not scanned: **Confirm it is below the selected root and contains supported audio extensions.
- **A file is skipped: **The file may be corrupt, unsupported by its decoder, or effectively silent. The log contains the reason when available.
- **The mood seems subjective: **The result is signal-derived from measurable audio features, not lyrics, genre labels, or personal listening judgment.
- **Parallel processing fails: **Disable parallel mode or reduce workers if process startup or system resources are constrained.
- **Tags did not change: **Confirm Live Update was selected. Dry Run never writes files.
- **No log is available: **A run must reach completion and be able to write to the selected root directory.

## Safety and Recovery

Run Dry Run first and review the batch log. Live Update modifies metadata throughout the library, so maintain backups of important files and use Undo Tag Edits for available tag-edit snapshots.
