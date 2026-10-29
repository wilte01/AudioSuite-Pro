---
title: Key Detector - User Guide
subtitle: Based on the current Key Detector implementation
---

## Overview

Key Detector estimates the musical key of audio files from their signal using librosa chroma analysis and Krumhansl-Schmuckler key profiles. It can report the detected key without changing files or write the result to the standard musical key metadata field.

The tool scans supported audio files in a selected directory, analyzes a configurable leading duration, and processes files with configurable worker parallelism.

## Supported Audio

The detector uses the shared Audio Suite supported-extension list, including MP3, FLAC, OGG, M4A, Opus, WAV, and AIFF variants. The selected directory must contain supported audio files.

## Quick Start

1. Open Key_Detector.pyw.
1. Select the music directory.
1. Choose an analysis duration and optional parallel processing settings.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN KEY DETECTION.
1. Review detected keys, skipped files, errors, and the log.
1. Run again in Live Update when you want the key tags written.

## Setup

Setup contains the directory picker, run mode, analysis duration, parallel worker controls, presets, and the start button. The last-used directory and parallel settings are restored through shared suite configuration.

- **Analysis Duration: **The GUI defaults to 90 seconds. Shorter analysis is faster but may provide less musical context.
- **Parallel Processing: **When enabled, CPU-bound librosa chroma work uses ProcessPoolExecutor to bypass the Python GIL. When disabled, the thread-based path is used.
- **Workers: **Controls the maximum worker count; the default is one worker per logical CPU, capped at 8.
- **Presets: **Save and restore directory, mode, duration, parallel mode, and worker-count settings.
- **Dry Run / Live Update: **Dry Run detects without writing. Live Update writes the detected key metadata.

## Detection Algorithm

1. Load up to the configured duration of audio with librosa.
1. Convert the signal to mono analysis data and promote it to float64 for internal processing.
1. Build a constant-Q chromagram and average it over time into a 12-element pitch-class profile.
1. Correlate the profile against all rotations of the 12-note major and minor Krumhansl-Schmuckler templates.
1. Select the strongest major or minor correlation and convert it to conventional display notation.

Major keys are displayed without a suffix, while minor keys end in m. Common flat spellings are used for Eb, Ab, Bb, and their supported minor equivalents; C# and F# remain sharp-spelled in the display conventions.

## Silent and Existing-Key Behavior

- **Silent audio: **Zero-energy audio cannot produce a meaningful chromagram correlation and is reported as an error.
- **Dry Run with existing key: **A file that already has a key tag is skipped rather than re-analyzed in Dry Run.
- **Live Update with existing key: **The file is analyzed and the tag is rewritten; the status includes the previous key when it differs.
- **Detection failure: **The file is reported as an error or recoverable skip while other files continue.
- **Material with no defensible key: **When the winning correlation does not lead the runner-up by a decisive margin -- broadband noise, percussive material, atonal music -- the file is reported as DETECTED (not tagged) and no key is written, even in Live Update. A file that already has a key tag keeps it. This is deliberate: Key Detector never writes the literal value "Unknown" into your library, because that reads as a musical fact it cannot support and would block a better result on a later run.

## Dry Run and Live Update

- **Dry Run: **Reports detected keys and skips files that already contain a key tag. No metadata is written.
- **Live Update: **Writes the detected key to the standard key metadata field, including format-appropriate representations through the shared tag helper. Files whose key could not be determined are reported instead of written.
- **Undo: **Live tag changes participate in the suite's batch undo context.

## Processing and Results

Processing shows a worker-slot status per logical CPU (at most eight), a progress bar, processed/skipped/error counts, and per-file messages. Results reports total files, analyzed files, skipped files, errors, and elapsed time. The completion label distinguishes Analysis Complete from Key Tagging Complete.

## Logs

- **Dry Run log: **key_dry_run_log.txt in the selected directory.
- **Live log: **key_sync_log.txt in the selected directory.
- **Contents: **Mode, analysis duration, parallel settings, per-file detected/existing keys, skips, errors, counts, and elapsed time.

## Command Line

The registered command is key. Examples:

python -m audio_suite_shared.cli_app key <folder> --dry\
python -m audio_suite_shared.cli_app key <folder> --duration 120\
python -m audio_suite_shared.cli_app key <folder> --parallel --workers 4\
python -m audio_suite_shared.cli_app key <folder> --live --json

The CLI defaults to a 30-second analysis duration, unlike the GUI's 90-second default. It accepts --duration, --parallel/--no-parallel, --workers, the shared dry-run/live option, and --json. The duration is validated from 10 through 600 seconds.

## Master Driver Use

From the Master Driver, open ENRICH and select Key Detector. The driver passes the directory, run mode, duration, worker settings, start/end behavior, and orchestration flags through the launch handshake. A driven launch can auto-start and displays inherited controls.

## Troubleshooting

- **No audio files found: **Select a directory containing supported audio files.
- **Keys are skipped: **In Dry Run, files that already have a key tag are intentionally skipped. Use Live Update to refresh them.
- **Results are uncertain: **Increase analysis duration to provide more musical context, especially for tracks with long intros or varied sections.
- **Silent file error: **Pure silence has no usable pitch-class profile and cannot yield a meaningful key.
- **Parallel processing fails: **Disable parallel mode or reduce worker count if process startup or system resources are constrained.
- **Tags did not change: **Confirm Live Update was selected; Dry Run never writes metadata.

## Safety and Recovery

Run Dry Run first and review the detected keys. Live Update modifies metadata in place, so keep backups of important files. Use the suite's Undo Tag Edits workflow for available tag snapshots.
