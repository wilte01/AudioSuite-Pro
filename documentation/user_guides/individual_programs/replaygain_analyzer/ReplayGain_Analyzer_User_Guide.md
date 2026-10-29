---
title: ReplayGain Analyzer - User Guide
subtitle: Based on the current ReplayGain Analyzer implementation
---

## Overview

ReplayGain Analyzer measures integrated loudness and true peak for supported audio files, calculates track and folder-level ReplayGain values, and can write the results to metadata. Files are grouped by their containing folder: each folder receives its own album gain and album peak based on the files measured there.

The tool can optionally apply the measured track gain losslessly to MP3 files after writing the tags. This changes MP3 frame gain without re-encoding the audio.

## Supported Files

The analyzer uses the shared Audio Suite supported formats, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV, and AIFF variants. The selected directory is scanned recursively and folders are processed independently.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open ReplayGain_Analyzer.pyw.
1. Select a music directory.
1. Choose a valid target LUFS value.
1. Leave Dry Run selected for the first pass.
1. Enable Apply Lossless Gain only when you explicitly want MP3 audio gain adjusted.
1. Click the analysis start button and review the folder/file results.
1. Run again in Live Update when the calculated values are acceptable.

## Setup

Setup contains the directory picker, target LUFS, run mode, optional MP3 lossless gain, presets, and shared run controls. The application validates the directory and target before starting. Target LUFS uses the suite's permitted target values.

- **Target LUFS: **Desired integrated loudness target. Track gain is target LUFS minus measured LUFS; album gain uses the folder's combined loudness, weighted by each file's duration.
- **Dry Run / Live Update: **Dry Run measures and previews values without tag writes. Live Update writes ReplayGain tags.
- **Apply Lossless Gain: **After tagging, bakes track gain into MP3 files losslessly. It applies only to MP3 files and is not a re-encode.
- **Presets: **Save and restore target LUFS and run mode through shared suite presets.

## Two-Phase Processing

1. Recursively discover supported audio files and group them by containing folder.
1. Phase 1 measures each file's integrated LUFS and true peak in parallel, with retry handling.
1. For each folder, calculate album gain as target LUFS minus the combined loudness of its files: each file's energy is weighted by its duration, so a long quiet track counts less than a short loud one.
1. Calculate album peak as the maximum true peak among files in that folder.
1. In Dry Run, report the track and album values without writing.
1. In Live Update, write track gain, album gain, track peak, and album peak tags.
1. Optionally apply lossless MP3 gain after successful tagging.

## ReplayGain Values and Tags

- **Track Gain: **The per-file gain required to reach the target, formatted such as +2.34 dB.
- **Album Gain: **The folder-level gain derived from the duration-weighted combined loudness of that folder, which is what a player applies to the album as a whole.
- **Track Peak: **The measured true-peak value for the file, converted from dBFS to the linear amplitude (0.0–1.0) ReplayGain peak tags use.
- **Album Peak: **The highest true peak measured among files in the folder (the loudest linear amplitude, not the largest dBFS), in the same linear form.

The shared tag writer stores REPLAYGAIN_TRACK_GAIN, REPLAYGAIN_ALBUM_GAIN, REPLAYGAIN_TRACK_PEAK, and REPLAYGAIN_ALBUM_PEAK using format-appropriate metadata representations. Live writes participate in the suite's tag-edit undo batch.

## Dry Run and Live Update

- **Dry Run: **Measures values and displays folder/file results but never writes tags or applies MP3 gain.
- **Live Update: **Writes all four ReplayGain fields for each measured file, then optionally applies MP3 lossless gain.
- **Measurement failure: **A file with unavailable LUFS metrics is reported as an error and excluded from the folder calculation.
- **Lossless gain failure: **Tagging may succeed while the optional post-tag gain reports an error status; review the per-file result and log.

## Processing and Results

Processing shows four worker slots and a progress count. Folder completion updates the file tree with file name, measured LUFS, track gain, album gain, and status. Results reports total files, successfully processed files, errors, and elapsed time.

## Logs

- **Dry Run log: **replaygain_dry_run_log.txt in the selected directory.
- **Live log: **replaygain_sync_log.txt in the selected directory.
- **Contents: **Mode, target LUFS, folder album statistics, track LUFS/gain/peak values, statuses, errors, and summary.

## Command Line

The registered command is replaygain. Examples:

python -m audio_suite_shared.cli_app replaygain <folder> --dry\
python -m audio_suite_shared.cli_app replaygain <folder> --target-lufs -16 --live\
python -m audio_suite_shared.cli_app replaygain <folder> --apply-gain --live\
python -m audio_suite_shared.cli_app replaygain <folder> --target-lufs -14 --json

The CLI accepts --target-lufs, --apply-gain/--no-apply-gain, the shared dry-run/live option, and --json. Target LUFS is validated by the shared suite rules. The text summary reports files and errors; JSON contains the structured result.

## Master Driver Use

From the Master Driver, open ENRICH and select ReplayGain Analyzer. The driver passes the directory, target LUFS, run mode, start/end behavior, and inherited orchestration controls.

## Troubleshooting

- **No audio files found: **Select a directory containing supported audio files or check that the files are accessible.
- **A folder's album gain looks unexpected: **Album gain is calculated per folder from the duration-weighted loudness of only the files that measured successfully. A file whose duration cannot be read is reported as an error rather than counted as zero, so check the folder's error count before judging the album value.
- **Tags did not change: **Confirm Live Update was selected. Dry Run never writes ReplayGain metadata.
- **MP3 loudness changed unexpectedly: **Apply Lossless Gain explicitly changes MP3 frame gain after tagging; disable it to write tags only.
- **A file errors: **Review the per-file status and replaygain log for FFmpeg measurement, tag-writing, or gain-application details.
- **Target rejected: **Use one of the suite's permitted target LUFS values.

## Safety and Recovery

Run Dry Run first and inspect track and album values. Live Update changes metadata in place; optional MP3 gain also changes the encoded track's playback gain. Keep backups and use the suite's Undo Tag Edits workflow for available metadata snapshots.
