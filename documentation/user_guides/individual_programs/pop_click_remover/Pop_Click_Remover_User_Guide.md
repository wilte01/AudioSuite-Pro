---
title: Pop & Click Remover - User Guide
subtitle: Based on the current Pop & Click Remover implementation
---

## Overview

Pop & Click Remover detects short discontinuities in audio and repairs them with interpolation. It uses a local noise-floor detector on the first-difference signal, merges neighboring spike samples into defect regions, and repairs eligible regions with cubic-spline interpolation or a linear fallback near file boundaries.

The tool processes supported audio files in a selected directory, preserves existing metadata, and can preview or commit repairs.

## Supported Files

The processor uses the shared Audio Suite supported formats, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV, and AIFF variants. The directory must contain at least one supported file.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Pop_Click_Remover.pyw.
1. Select the music directory.
1. Choose a sensitivity and maximum click width.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN POP & CLICK REMOVAL.
1. Review detected/clean/error statuses and audition the result when available.
1. Run again in Live Update when the repairs are acceptable.

## Setup

Setup contains the directory picker, execution mode, sensitivity slider, maximum click width, presets, and shared run controls. The last-used directory is restored from shared suite configuration.

- **Click Sensitivity: **Range 0.01 through 0.40. Lower values are more aggressive and detect quieter clicks; the default is 0.31.
- **Max Click Width: **Range 1 through 10 ms. Defect regions wider than this are left untouched to avoid altering legitimate transients; the default is 2 ms.
- **Dry Run / Live Update: **Dry Run detects without writing. Live Update exports repaired audio and replaces the source.
- **Presets: **Save and restore sensitivity, maximum width, and run mode.

## Detection and Repair

1. Copy each source file into a per-worker temporary directory and preserve its tags.
1. Decode the audio and calculate first-order sample differences.
1. Estimate a local noise floor with a 20 ms windowed mean absolute deviation.
1. Flag differences above the sensitivity-derived threshold and merge nearby spike samples.
1. Reject regions wider than Max Click Width, near-silent artifacts, or saturated-neighbor cases.
1. Repair accepted regions with cubic-spline interpolation over clean neighboring samples, using linear interpolation near boundaries.
1. Apply clipping protection and report whether any click regions were repaired.

The repair includes an overshoot guard and is designed to be idempotent: a second pass on already repaired audio should find no new defects.

## Sensitivity Semantics

Sensitivity maps to an internal detector multiplier. Lower slider values produce a lower threshold multiplier and therefore more aggressive detection. Higher values are gentler. The detector is calibrated to avoid ordinary music transients, but review aggressive settings with auditioning before applying them to a large library.

## Dry Run and Live Update

- **Dry Run: **Detects and counts clicks without exporting repaired audio or changing source files. Result playback is unavailable because nothing was written.
- **Live Update: **Exports repaired audio to a temporary file, restores original tags, then copies the result over the source.
- **Clean files: **Files with no eligible defects are skipped and not rewritten.
- **Undo: **Each live run is recorded in the suite's undo history with a full copy of every file before it was rewritten, so Undo Tag Edits restores the original audio byte for byte, along with the tags the file had at the time. Undo history is capped, so keep your own backups of masters you care about.

## Processing and Results

Processing displays one worker slot per logical CPU (at most eight), progress, succeeded/skipped/error counts, and per-file messages. Results reports total, succeeded, skipped, errors, and elapsed time. The Results tab can open the log and source folder and audition original versus repaired audio for a successful live run.

## Command Line

The registered command is declick. Examples:

python -m audio_suite_shared.cli_app declick <folder> --dry\
python -m audio_suite_shared.cli_app declick <folder> --sensitivity 0.05 --width 3\
python -m audio_suite_shared.cli_app declick <folder> --live --json

Options include --sensitivity, --max-width, the shared dry-run/live option, and --json. CLI defaults are sensitivity 0.25 and width 5 ms, while the GUI defaults are 0.31 and 2 ms.

## Audio Refinery and Master Driver

Pop & Click Remover is available as the declick stage in Audio Refinery, where the pipeline can combine it with trimming, noise reduction, enhancement, and normalization. From the Master Driver, it is available through the Refinery workflow and receives inherited run controls.

## Troubleshooting

- **No files found: **Select a directory containing supported audio files.
- **Everything is clean: **The detector found no eligible regions; this is expected for files without short discontinuities.
- **Too many repairs: **Increase sensitivity value, reduce maximum width, or review the output with auditioning.
- **A real transient was untouched: **It may exceed Max Click Width, be near silence, or be rejected by saturation guards. Adjust width cautiously.
- **A file errors: **Check codec support, file permissions, temporary disk space, and the per-file processing message.
- **Tags changed unexpectedly: **Confirm Live Update was selected and use the suite's undo workflow or backups for recovery.

## Safety and Recovery

Run Dry Run first and audition representative repairs. Live Update replaces source files only after temporary export succeeds, but keep backups of important audio. Undo Tag Edits restores the pre-run file in full while the run is still in its capped history.
