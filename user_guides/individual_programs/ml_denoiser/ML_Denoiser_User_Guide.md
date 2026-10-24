---
title: ML Denoiser — User Guide
version: auto
---

## Overview

ML Denoiser removes broadband noise with RNNoise, a small recurrent neural network trained on speech. Unlike the signal-based Noise Reduction tool, it needs no noise-profile selection: the model estimates, frame by frame, how much of the signal is speech and reconstructs each frame with the noise band suppressed.

The model is fast (measured at roughly ten times realtime on a CPU) and it is speech-oriented. That last part matters: it attenuates tonal and musical content heavily, so the tool reports the level it measured for every file and offers an amount blend instead of promising a transparent denoise.

Files are processed in place in Live Update, with existing tags preserved, and each file is written only after its processed copy has been produced in a temporary directory.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

The neural model itself is an optional dependency (approximately 13 MB, no GPU runtime). The first run installs it: the tool asks once, downloads it, checks that it loads, and then starts the batch.

A dry run needs it too, because a dry run measures with the model - that measurement is the point of it. A headless run installs the suite's 'ml' extra instead (uv sync --extra ml).

## Supported Files

The processor uses the shared Audio Suite supported formats, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV and AIFF variants. The selected directory must contain at least one supported file. Read-only formats are reported as skipped, because the tool rewrites the source file.

## Quick Start

1. Open ML_Denoiser.pyw (or launch it from the Master Driver's UTIL tab).
1. Select the music directory.
1. Leave Dry Run selected and start; the run reports the attenuation each file would receive and writes nothing.
1. Adjust the Denoise Amount if the measured attenuation is too aggressive for the material.
1. Switch to Live Update and run again.
1. Use the Results audition controls to compare an original and a denoised file when a live result is available.

## Setup

Setup contains the directory picker, the run mode, one denoise control, presets and the shared run controls.

- **Denoise Amount (%): **How much of the model's output to keep. 100 % is the model's own result and 1 % is almost the untouched source. Lower values are a blend, not a weaker model: the output is mixed with the original signal.
- **Dry Run / Live Update: **Dry Run measures and reports without writing; Live Update exports the processed audio and replaces the source file.
- **Presets: **Save and restore the amount and the run mode through the suite's shared presets.

## How the Model Is Applied

RNNoise works on 10 ms frames of 48 kHz audio. The tool feeds the decoded file to the model at its own sample rate, lets the library resample internally, and then forces the result back to the exact source length: a final frame that the resampler shortened is restored from the source, and one that overshot is trimmed. The output keeps the source's sample rate, channel count and duration.

The model's output is 16-bit, so a denoised file carries 16-bit resolution whatever the source's bit depth was. A file whose measured level does not move by at least 0.1 dB is reported as clean and is not rewritten, which makes a second pass over an already-denoised folder a no-op instead of a re-encode.

## Dry Run and Live Update

- **Dry Run: **Runs the model, reports each file's measured attenuation in dB and the before/after level, and writes no audio, no tags and no temporary file. Result playback is unavailable because nothing was written.
- **Live Update: **Exports the processed audio, restores the original tags and replaces the source file only after that export succeeded.
- **Clean files: **Files the model left alone are marked skipped and are not rewritten.
- **Undo: **Every live run records a full copy of each file before it is rewritten, so the suite's Undo Tag Edits workflow restores the original audio and tags byte for byte.

## Processing and Results

Processing shows the worker slots, a progress bar and per-file statuses: FIXED (rewritten), FOUND (a dry run measured a change), SKIP (nothing to do) and ERROR. The status line carries the measured attenuation, for example 'Attenuated 6.0 dB (-18.4 → -24.4 dBFS)'. Results reports total, denoised, skipped, errors and elapsed time, and can open the log and the source folder.

## Command Line

The registered command is denoise. The amount is a percentage here too, the same unit the GUI slider shows. Examples:

python -m audio_suite_shared.cli_app denoise <folder> --dry\
python -m audio_suite_shared.cli_app denoise <folder> --amount 50 --dry\
python -m audio_suite_shared.cli_app denoise <folder> --amount 100 --live\
python -m audio_suite_shared.cli_app denoise <folder> --live --json

Options: --amount 1-100, the shared --dry/--live pair and --json. A run without the `ml` extra exits non-zero and names what to install.

## Master Driver Use

In the Master Driver's UTIL tab, select ML Denoiser and set its Amount. The driver passes the directory, the run mode, the start/end behaviour and the amount through the launch handshake. The module toggle decides whether the tool joins a batch; its dependency-graph entry is a leaf, so it imposes no ordering on the other tools.

## Troubleshooting

- **A dialog about installing RNNoise: **The first run offers the one-time download; accepting it installs RNNoise and starts the batch. A download that fails says why in the dialog.
- **Music sounds dull or thin: **Lower the Denoise Amount. RNNoise is trained on speech and attenuates tonal content, so any single instrument or sustained note may lose energy.
- **No files found: **Select a directory containing supported audio files.
- **Every file is skipped: **The model found no measurable attenuation, which is what a dry run over an already-processed folder looks like. Check the per-file line for the measured level.
- **A file errors: **Check codec support, file permissions, free space in the temporary directory and the per-file status in the log.

## Safety and Recovery

Run Dry Run first and, for music, audition representative results: the model is not a transparent denoiser. Live Update replaces source files only after a successful temporary export, keeps the tags and records an undo snapshot. Retain backups of irreplaceable audio; the suite's Undo Tag Edits workflow restores a whole run, but no tool can recover a file deleted outside it.
