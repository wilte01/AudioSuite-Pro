---
title: Silence Trimmer - User Guide
subtitle: Based on the current Silence Trimmer implementation
---

## Overview

Silence Trimmer detects and removes leading and trailing silence from supported audio files. It can optionally apply fades after trimming, preserves existing tags, and processes files through temporary worker copies before replacing the source in Live Update.

The tool is read-only in Dry Run and reports the detected trim amount without exporting or modifying files.

## Supported Files

The processor uses the shared Audio Suite supported extensions, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV, and AIFF variants. The selected directory must contain supported files.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Silence_Trimmer.pyw.
1. Select the music directory.
1. Set the silence threshold and decide whether to apply fades.
1. Leave Dry Run selected for the first pass.
1. Click the trimming start button.
1. Review per-file trim amounts, skips, errors, and audition the result when available.
1. Run again in Live Update when the trim plan is acceptable.

## Setup

Setup contains the directory picker, execution mode, silence threshold, fade settings, parallel controls, presets, and the start button. The last-used directory and worker settings are restored through shared suite configuration.

- **Silence Threshold: **GUI range -80 to -20 dB. Audio below this threshold is treated as silence; the default is -50 dB.
- **Apply Fades: **Adds fade-in and fade-out after trimming. Disabled by default.
- **Fade-in: **GUI range 100 to 3000 ms; default 500 ms.
- **Fade-out: **GUI range 100 to 5000 ms; default 1000 ms.
- **Parallel Processing: **The tool is already I/O-oriented and uses a thread pool; the parallel flag is accepted for consistency while worker count controls concurrency.
- **Presets: **Save and restore threshold, fade settings, parallel settings, worker count, and run mode.

## Silence Detection

The core uses pydub's leading-silence detector twice: once on the original audio for the beginning and once on a reversed copy for the ending. The detected start and end durations are reported separately and summed into the total trim.

- **No silence: **The file is marked SKIP and is not rewritten.
- **Entire file is silence: **The file is marked SKIP and left untouched - a fully silent source is never replaced with an empty file.
- **Dry Run: **The file is marked DRY_RUN with the total milliseconds that would be removed.
- **Live Update: **The detected ranges are removed and the optional fades are applied to the remaining audio.
- **Fade clamping: **Fade durations are clamped to the trimmed segment length so short audio is not extended or corrupted by an overlong fade.

## Processing Workflow

1. Discover supported files in the selected directory.
1. Copy each source into a worker temporary directory and read its original tags.
1. Load the temporary audio and detect leading and trailing silence.
1. Skip clean files or report the Dry Run trim plan.
1. In Live Update, trim, apply optional fades, export with format-appropriate settings, and restore tags.
1. Record a tag-edit snapshot and replace the original file after successful export.
1. Remove temporary worker files and report the per-file result.

## Dry Run and Live Update

- **Dry Run: **Calculates trim amounts without exporting or changing files. Result audio is unavailable for playback because nothing was written.
- **Live Update: **Exports trimmed audio, restores original tags, and replaces the source after successful processing.
- **Tag preservation: **Existing tags are read before processing and restored to the exported file.
- **Undo: **Live edits participate in the suite tag-edit batch for available recovery.

## Processing and Results

Processing displays one worker slot per logical CPU (at most eight), progress, processed/succeeded/skipped/error counts, and per-file actions such as trim durations or No silence detected. Results reports total, reduced/succeeded files, skips, errors, and elapsed time. The Results tab can open the log and source folder and audition original versus result for successful Live Update output.

## Command Line

The registered command is silence-trim. Examples:

python -m audio_suite_shared.cli_app silence-trim <folder> --dry\
python -m audio_suite_shared.cli_app silence-trim <folder> --threshold -50\
python -m audio_suite_shared.cli_app silence-trim <folder> --fade --fade-in 500 --fade-out 1000 --live\
python -m audio_suite_shared.cli_app silence-trim <folder> --parallel --workers 4 --json

Options include --threshold, --fade/--no-fade, --fade-in, --fade-out, --parallel/--no-parallel, --workers, the shared dry-run/live option, and --json. CLI defaults are threshold -50 dBFS and 25 ms fades, differing from the GUI defaults of 500/1000 ms when fades are enabled.

## Audio Refinery and Master Driver

Silence Trimmer is available as the trim stage in Audio Refinery, where it can run before noise reduction, enhancement, and normalization. From the Master Driver, use the Refinery workflow or the registered utility card as provided by the suite.

## Troubleshooting

- **No files found: **Select a directory containing supported audio files.
- **Silence was not removed: **Raise the threshold toward -20 dB if the quiet material is above the current threshold; review the resulting trim amount in Dry Run first.
- **Too much audio was removed: **Lower the threshold toward -80 dB and inspect the file before running Live Update.
- **Fades sound unexpected: **Use shorter fade values and remember that fades are applied after trimming and clamped to the remaining segment length.
- **A file errors: **Check codec support, permissions, temporary disk space, and the per-file status/log.
- **Tags changed unexpectedly: **Confirm Live Update was selected and use the suite's undo snapshots or backups for recovery.

## Safety and Recovery

Run Dry Run first and audition representative results. Live Update replaces source files only after successful temporary export, but keep backups of important audio. Use the suite's Undo Tag Edits workflow for available metadata snapshots.
