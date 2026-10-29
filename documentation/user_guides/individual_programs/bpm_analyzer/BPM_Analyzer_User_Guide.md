---
title: BPM Analyzer - User Guide
subtitle: Based on the current BPM Analyzer implementation
---

## Overview

BPM Analyzer estimates the tempo of audio files with librosa beat tracking and can write the detected BPM into the file's metadata. It scans a selected directory, analyzes a configurable leading portion of each file, constrains the estimate to a chosen BPM range, and reports each result in the Processing tab and log.

Dry Run is analysis-only. Live Update writes the BPM tag and participates in the suite's tag-edit undo batch.

## Supported Audio

The analyzer uses the shared Audio Suite supported-format list, including MP3, FLAC, OGG, M4A, Opus, WAV, and AIFF variants. The selected directory must contain at least one supported audio file.

## Quick Start

1. Open BPM_Analyzer.pyw.
1. Select the music directory.
1. Set the BPM minimum and maximum and choose an analysis duration.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN BPM ANALYSIS.
1. Review the detected values and errors in Processing and Results.
1. Run again in Live Update when the detections are acceptable and you want tags written.

## Setup

Setup contains the directory picker, mode, BPM range, analysis duration, optional parallel processing, worker count, presets, and the start button. The GUI restores the last directory and saves parallel settings through shared suite configuration.

- **BPM Range: **The GUI requires minimum BPM from 40 through 300 and maximum BPM from 60 through 400, with minimum less than maximum. Defaults are 75 to 175.
- **Analysis Duration: **The GUI accepts 10 to 300 seconds. The default is 90 seconds. Shorter analysis is faster but may be less accurate.
- **Parallel Processing: **When enabled, CPU-bound detection uses ProcessPoolExecutor to bypass the GIL. When disabled, the shared thread-based processing path is used.
- **Workers: **Controls the maximum worker count and must be at least 1. The default is one worker per logical CPU, capped at 8.
- **Presets: **Save and load BPM range, duration, parallel mode, worker count, and run mode settings through shared configuration.

## Detection Behavior

For each file, librosa loads mono audio for the configured maximum duration using its beat tracker. The signal is upcast to float64 for the tool's internal processing. The raw tempo estimate is then normalized to a scalar, octave-corrected by doubling or halving only when the folded level carries a pulse of its own, and rounded to an integer.

- **Outside-range tempo: **A measured tempo outside the configured range is tagged as measured, and its line says so, for example BPM 60 (outside 75-175). The range chooses between octave-equivalent readings of the same pulse; it never moves a value to a boundary or to an octave the audio does not support.
- **No detectable beat or silence: **A file with no discernible beat, or one that is effectively silent, is reported as [SKIP] and left untagged.
- **Existing BPM: **In Live Update, the log and on-screen status include the prior BPM when it differs from the new detected value.

## Dry Run and Live Update

- **Dry Run: **Detects BPM and reports [DRY RUN] without changing metadata.
- **Live Update: **Detects BPM and writes the result with the shared BPM tag writer, reporting [TAGGED].
- **Undo: **Live tag changes are recorded in the suite's batch undo context.
- **Failure: **A detection error is reported for that file and counted as an error while other files continue.

## Processing and Results

Processing shows four worker-slot labels, a progress bar, processed/skipped/error counts, and per-file status lines. Results reports total files, analyzed or tagged files, skipped files, errors, and elapsed time. The completion label distinguishes Analysis Complete from BPM Tagging Complete.

BPM Analyzer does not treat an out-of-range detection as a skip: the value is tagged as measured and its line names the configured range. Skips are reserved for files with no discernible beat, and errors for files that could not be read.

When any file lands outside the range, the Results summary and the run log add an Outside BPM range line, for example 1 of 12 tracks (band 75-175), and the Master Driver's batch note reports the same count after the step.

## Logs

- **Dry Run log: **bpm_dry_run_log.txt in the selected directory.
- **Live log: **bpm_sync_log.txt in the selected directory.
- **Contents: **Mode, BPM range, analysis duration, parallel settings, per-file BPM results, errors, counts, and elapsed time.

## Command Line

The registered command is bpm. Its BPM range defaults to 75-175, the same as the GUI, while the analysis duration defaults to 30 seconds rather than the GUI's 90. Examples:

With --json the payload carries outside_range_files: one record per file whose tempo landed outside the range, each with the filename, the measured BPM and the band that was configured.

python -m audio_suite_shared.cli_app bpm <folder> --dry\
python -m audio_suite_shared.cli_app bpm <folder> --bpm-min 75 --bpm-max 175 --duration 90\
python -m audio_suite_shared.cli_app bpm <folder> --parallel --workers 4\
python -m audio_suite_shared.cli_app bpm <folder> --json

The command accepts --bpm-min, --bpm-max, --duration, --parallel/--no-parallel, --workers, the shared dry-run option, and --json. It reports processed, skipped, errors, and elapsed time in text mode. JSON mode returns the same counts as top-level fields plus skipped_files, one record per refused file with its filename, reason, and onset_periodicity score (null when no tempo estimate existed), and error_files, one record per failed file with its filename, reason, and error_type.

## Master Driver Use

From the Master Driver, open ENRICH and select BPM Analyzer. The driver passes the directory, mode, BPM range, duration, worker settings, and orchestration flags through the launch handshake. A driven launch can auto-start and displays inherited controls.

## Troubleshooting

- **No audio files found: **Select a directory containing supported audio files.
- **Invalid BPM range: **Ensure minimum is below maximum, minimum is 40-300, and maximum is 60-400 in the GUI.
- **Invalid duration: **Use 10-300 seconds in the GUI; shorter windows trade accuracy for speed.
- **Results seem too high or low: **The tool reports the metrical level it measures; a consistent doubling or halving across a folder is a range question, so widen the range and increase analysis duration for more context.
- **Detection error: **Check whether the file is readable and decodable; review the per-file error and log.
- **Tags did not change: **Confirm Live Update was selected. Dry Run never writes BPM metadata.
- **Parallel run fails: **Try disabling parallel mode or lowering worker count if process startup or system resources are constrained.

## Safety and Recovery

Run Dry Run first and review the detected BPM values. Live Update changes audio metadata in place, so keep backups of important files. Use the suite's Undo Tag Edits workflow for available tag snapshots.
