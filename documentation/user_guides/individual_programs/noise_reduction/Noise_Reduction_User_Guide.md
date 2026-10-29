---
title: Noise Reduction - User Guide
subtitle: Based on the current Noise Reduction implementation
---

## Overview

Noise Reduction removes unwanted mains hum and/or stationary broadband noise from supported audio files. Hum removal uses cascaded IIR notch filters; broadband reduction uses STFT spectral gating based on a selected noise-profile region. Both stages can be enabled independently or together, with hum removal applied first.

The tool processes files in place in Live Update, preserves existing tags, and uses temporary working files before replacing the original only after successful processing.

## Supported Files

The processor uses the shared Audio Suite supported formats, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV, and AIFF variants. The selected directory must contain at least one supported file.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Noise_Reduction.pyw.
1. Select the music directory.
1. Enable Hum Removal, Broadband Noise Reduction, or both.
1. Set the noise controls and leave Dry Run selected for the first pass.
1. Start processing and review the per-file statuses.
1. Run again in Live Update when the result is acceptable.
1. Use Results audition controls to compare an original and reduced file when available.

## Setup

Setup contains the directory picker, run mode, two reduction stage controls, presets, and shared run controls. At least one of Hum Removal or Broadband Noise Reduction must be enabled.

- **Hum Removal: **Enables mains-hum notch filtering.
- **Broadband Noise Reduction: **Enables spectral gating using a noise profile.
- **Dry Run / Live Update: **Dry Run analyzes without writing; Live Update exports and replaces files.
- **Presets: **Save and restore all reduction parameters and run mode through shared suite presets.

## Hum Removal

Hum removal designs second-order notch filters at the selected fundamental and each harmonic below the Nyquist frequency. The filters are applied per channel using numerically stable second-order sections processing. A result is considered modified only when attenuation reaches the implementation's minimum meaningful threshold of 3 dB.

- **Hum frequency: **50 or 60 Hz mains frequency.
- **Harmonics: **1 through 20 harmonic notches; default 8. More harmonics remove more of the hum series but may affect nearby musical content.
- **Quality (Q): **1 through 100; default 30. Higher Q creates narrower notches and preserves more adjacent content.

## Broadband Noise Reduction

Broadband reduction uses a short noise-only region to estimate the mean magnitude spectrum. The gate threshold is that noise profile plus configurable dB headroom; spectral bins below the threshold are zeroed, then the signal is reconstructed with inverse STFT.

- **Noise start / end: **Profile window in milliseconds; defaults 0 to 500 ms and must be at least 100 ms wide.
- **Gate threshold: **Headroom above the measured noise floor, default 3 dB. Lower values suppress more but risk removing quiet detail.
- **Profile selection: **Choose a section containing noise without desired music or speech for the most reliable gate.

## Processing Behavior

1. Discover supported files in the selected directory.
1. Read original tags and copy the source to a worker temporary directory.
1. Load the temporary audio and apply hum removal first when enabled.
1. Apply broadband spectral gating when enabled.
1. Skip clean files when no meaningful modification is detected.
1. In Live Update, export the reduced audio, restore original tags, and copy the result over the source.
1. Remove temporary worker files and report the result.

## Dry Run and Live Update

- **Dry Run: **Calculates the reduction path without exporting or changing files. Result audio is unavailable for playback because nothing was written.
- **Live Update: **Exports modified audio, restores tags, and replaces the source file after successful processing.
- **Clean files: **Files with no detectable modification are marked skipped and are not rewritten.
- **Undo: **Each live run is recorded in the suite's undo history with a full copy of every file before it was rewritten, so Undo Tag Edits restores the original audio byte for byte, along with the tags the file had at the time.

## Processing and Results

Processing displays one worker slot per logical CPU (at most eight), progress, succeeded/skipped/error counts, and per-file statuses such as FIXED, SKIP, or ERROR. Results reports total, reduced, skipped, errors, and elapsed time. The Results tab can open the log and source folder and audition before/after audio when a successful live result is available.

## Command Line

The registered command is reduce. Examples:

python -m audio_suite_shared.cli_app reduce <folder> --reduce-hum --dry\
python -m audio_suite_shared.cli_app reduce <folder> --reduce-hum --hum-frequency 50 --hum-harmonics 8\
python -m audio_suite_shared.cli_app reduce <folder> --reduce-broadband --noise-start 0 --noise-end 500\
python -m audio_suite_shared.cli_app reduce <folder> --reduce-hum --reduce-broadband --live --json

Options include --reduce-hum, --hum-frequency 50|60, --hum-harmonics, --hum-quality, --reduce-broadband, --noise-start, --noise-end, --gate-threshold, the shared dry-run/live option, and --json. At least one reduction flag should be enabled.

## Audio Refinery Use

Noise Reduction is also available as a stage in Audio Refinery. Enable its stage panel and choose hum and/or broadband reduction settings. In the Refinery, it runs after trim and before the enhancement stage, while the combined pipeline manages its own tag and output handling.

## Master Driver Use

From the Master Driver, open UTIL and select Noise Reduction. The driver passes the directory, mode, start/end behavior, stage settings, and orchestration state through the launch handshake.

## Troubleshooting

- **No files found: **Select a directory containing supported audio files.
- **Nothing changed: **A clean file may have been skipped, or both reduction stages may not have been enabled.
- **Hum remains: **Confirm the correct 50/60 Hz setting and consider increasing harmonics carefully.
- **Music sounds dull: **Increase notch Q, reduce harmonics, increase gate threshold, or improve the noise-profile region.
- **Broadband reduction is ineffective: **Choose a genuine noise-only profile region and verify the start/end window is at least 100 ms.
- **A file errors: **Check codec support, file permissions, temporary disk space, and the per-file status/log.

## Safety and Recovery

Use Dry Run first and audition representative results. Live Update replaces source files after successful temporary export, but retain backups of important audio. Use the suite's Undo Tag Edits workflow to restore the whole pre-run file.
