---
title: Audio Refinery - User Guide
subtitle: Based on the current Audio Refinery implementation
---

## Overview

Audio Refinery is a single-pass audio processing pipeline. It loads each source file once, runs the selected stages in memory, exports the result, restores the original tags, and optionally applies loudness normalization. The final file is placed in a separate output folder or atomically replaces the source when running in place.

The pipeline is designed to combine several suite tools without repeatedly decoding and encoding the same file. It validates file integrity before expensive DSP work, uses four worker slots by default, retries transient failures, and records completed files in a hash-based registry.

## Supported Audio

The refinery discovers the shared Audio Suite audio extensions, including MP3, FLAC, OGG, M4A, Opus, and WAV. The pipeline uses pydub/FFmpeg-backed decoding and format-aware export. Files must pass existence, readability, size, container-header, decode, sample-rate, duration, and channel checks before processing.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Audio_Refinery.pyw.
1. Select a source folder containing supported audio files.
1. Choose an output folder, or leave it blank for in-place replacement.
1. Select the stages to run and expand their settings as needed.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN REFINERY.
1. Review the Processing statuses, refinery_log.txt, and Results audition controls.
1. Run in Live Update only after confirming the intended stages and output.

## Setup

Setup contains source and output paths, presets, the shared run controls, five stage panels, Reset Progress, and BEGIN REFINERY. The default active stages are declick, trim, enhance, and normalise; noise reduction is optional. At least one stage must be enabled.

- **Source folder: **Required directory containing supported audio files. The application validates the directory and checks for audio before starting.
- **Output folder: **Optional. Blank means in-place replacement; a selected existing directory receives results with the source filenames.
- **Dry Run: **Validates and decodes files, reports RMS and duration information, and skips all modification and export stages.
- **Live Update: **Runs the selected stages and writes results. The embedded Refinery always uses live stage processing after its driver-level dry-run decision.
- **Presets: **Save, load, and delete the complete stage configuration, including stage toggles and parameters.
- **Reset Progress: **Clears the source folder's completion registry so every file can be processed again.

## Pipeline Stages

When enabled, stages run in this implementation order:

1. Integrity validation: checks existence, readability, file size, magic bytes, decoding, sample rate, duration, and channels.
1. Load: reads original tags and decodes the source audio.
1. Pop & Click Remover: detects and repairs clicks using sensitivity and maximum defect width.
1. Silence Trimming / Fading: removes silence using a dBFS threshold and can apply fade-in and fade-out.
1. Noise Reduction: optionally removes mains hum and/or broadband noise using its noise profile and gate settings.
1. Audio Enhancement: applies the Mild, Moderate, Aggressive, or Custom DSP preset; Custom adds per-effect toggles (reverse, karaoke, phaser, flanger, chorus).
1. Export: writes the processed audio once using format-appropriate encoding settings.
1. Normalise: optionally measures loudness and applies the configured LUFS target and tolerance.
1. Finish: restores tags, records an undo snapshot, and atomically replaces or creates the output file.

## Stage Controls

- **Declick sensitivity: **Default 0.31; controls click detection. Lower values are more aggressive according to the stage model.
- **Maximum defect width: **Default 2 ms; limits the click width repaired.
- **Trim threshold: **Default -50 dBFS; defines silence for trimming.
- **Fades: **Optional fade-in default 500 ms and fade-out default 1000 ms after trimming.
- **Noise reduction: **Optional hum removal and broadband reduction. Defaults include 60 Hz hum, 8 harmonics, Q 30, a 0-500 ms noise profile, and a 3 dB gate threshold.
- **Enhancement preset: **Mild, Moderate, Aggressive, or Custom. Selecting Custom shows a Configure Custom DSP button that opens the same non-modal editor the standalone Audio Enhancer uses, so the stage itself stays compact and every control is reachable; changes apply to the run as you make them. When Normalise is active, the refinery suppresses enhancement output gain so final loudness is controlled by the normalizer.
- **Enhancement effects: **Relevant to the Custom preset: Reverse audio, Karaoke (centre-vocal removal with a 0.0-1.0 strength), Phaser, Flanger, and Chorus. Each is off by default, and the built-in Mild, Moderate, and Aggressive presets leave them off.
- **Target LUFS: **Permitted targets are -12, -14, -16, -18, and -23 LUFS; default -16.0.
- **Tolerance: **Default 0.5 LUFS; used by the normalization stage to avoid unnecessary adjustment when loudness is already close to target.

## Dry Run and Output Safety

In Dry Run, each valid file is loaded and measured, then the pipeline returns without running modification stages or writing an output. Results include a DryRun stage with RMS, duration, and channel information.

In live processing, each file is written to a temporary file in the output directory. Tags are restored to that temporary file, and only then is it atomically moved into the final output path. If a stage or export fails, the temporary file is removed and the original remains intact.

## Completion Registry

The refinery stores successful completion records in _refinery_completed.log in the source folder. Each record contains a SHA-256 hash and filename. A file is skipped only when both its name and pre-processing hash match a recorded completion, so a renamed or modified file is eligible for processing again. Use Reset Progress to clear all records for the selected source folder.

## Processing and Results

Processing shows four worker slots, progress, and per-file DONE, SKIP, or ERROR entries. Each completed file's log includes stage messages and metrics. Results reports processed, succeeded, skipped, errors, and elapsed time. The Results tab can compare the original and result audio when a suitable pair exists; Dry Run has no result audio to play.

## Logs and Recovery

The pipeline writes refinery_log.txt in the resolved output directory. It includes per-file stage output and a final total, processed, succeeded, skipped, error, and time summary. Tag edits are recorded in the suite batch undo system. Keep independent backups before in-place processing even though failures are protected by temporary output and atomic replacement.

## Command Line

The registered command is refine. Examples:

python -m audio_suite_shared.cli_app refine <folder> --dry\
python -m audio_suite_shared.cli_app refine <folder> --output <output> --stages declick,trim,enhance,normalise\
python -m audio_suite_shared.cli_app refine <folder> --stages declick,enhance --preset Mild\
python -m audio_suite_shared.cli_app refine <folder> --reduce-hum --hum-frequency 60 --json

CLI options cover output directory, dry run, stages, declick sensitivity and width, trim threshold and fades, hum and broadband reduction, enhancement preset, the enhancement effect flags (--reverse, --karaoke/--no-karaoke, --karaoke-strength, --phaser, --flanger, --chorus), target LUFS, tolerance, and JSON output. If --output is omitted, results are written in place.

## Master Driver Use

Audio Refinery is the Master Driver's REFINE pipeline. The driver embeds the Refinery Setup controls, passes source and output folders, and supplies inherited Auto Start, Auto End, Clear Logs, and mode values. The driver uses its own batch orchestration; the Refinery's Parallel control is not an independent pipeline switch.

## Troubleshooting

- **No audio files found: **Select a source folder containing supported files directly discoverable by the processor.
- **Integrity check failed: **The file may be empty, unreadable, malformed, undecodable, outside size/duration/sample-rate/channel limits, or have invalid container headers.
- **Files are skipped on a later run: **They match the completion registry by filename and SHA-256. Use Reset Progress when a full rerun is intended.
- **Output directory error: **The selected output directory must already exist and be a directory; leave it blank for in-place mode.
- **Normalization behaves unexpectedly: **Remember that the normalizer controls final level when active, and enhancement output gain is suppressed in that case.
- **A stage fails: **Review refinery_log.txt for the stage-specific error. The original source is protected if the final replacement is not reached.

## Safety Recommendations

Run Dry Run first, prefer a separate output folder while tuning stages, and listen to the original/result audition pair. Use in-place mode only with backups. Reset the completion registry when configuration changes require already completed files to be processed again.
