---
title: Stem Separator — User Guide
version: auto
---

## Overview

Stem Separator splits a mixed track into its component parts with Demucs, an open-source source-separation model: vocals, drums, bass and everything else. It writes each part as its own file in an output folder and can also write a mix of the parts you selected.

The source files are never modified. Every run produces new files, so there is nothing to undo: keep the originals where they are and delete the output folder if a separation is not useful.

Separation is computationally expensive. A five-minute stereo track takes roughly one to two minutes on a modern CPU, and considerably less on a CUDA GPU. Demucs downloads its model weights on first use (about 80 MB, cached afterwards), so the first run of a session needs a network connection.

## Supported Files

The processor reads the shared Audio Suite supported formats, including MP3, FLAC, OGG, M4A, MP4, Opus, WAV and AIFF variants. Files are resampled to 44.1 kHz stereo before separation, because that is the shape Demucs' model accepts; a mono source is duplicated to two channels.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

Demucs and torch are an optional dependency. The first live run that needs them offers a one-time download (about 2.5 GB); accepting it installs them where the tool can use them, checks that Demucs loads, and then continues the run by itself. A dry run never needs them. A headless run installs the suite's 'ml' extra instead (uv sync --extra ml).

The PyPI torch wheel for Windows is a CPU build. A machine with a NVIDIA card therefore still reports CPU unless a CUDA build of torch is installed; the Device line on the Setup tab states exactly what torch measured.

## Quick Start

1. Open Stem_Separator.pyw.
1. Select the music directory that holds the files to split.
1. Choose an output folder for the stems.
1. Leave all four stems ticked, or clear the ones you do not need.
1. Leave Dry Run selected and start: the report lists what would be written.
1. Switch to Live Update and start again to write the stems.
1. Open the Results tab to read the counts and the log.

## Setup

Setup contains the source and output directory pickers, the stem selection, the model and device controls, the run mode and the shared run controls.

- **Stem output folder: **Required. Each track gets its own subfolder inside it. The folder is remembered between runs.
- **Stems: **Vocals, drums, bass and other. At least one must be ticked; only ticked stems are separated, which shortens a run that needs one part.
- **Also write mix.wav: **Writes the sum of the ticked stems next to them. A mix of all four reconstructs the original track as closely as the model can.
- **Demucs model: **htdemucs is the default. htdemucs_ft is the fine-tuned variant: better stems, roughly four times slower because it runs one model per stem.
- **Device: **auto uses CUDA when torch reports it usable and CPU otherwise. cpu and cuda force one; forcing cuda when it is not usable stops the run with a message that says why.
- **Dry Run / Live Update: **Dry Run reports the plan and writes nothing. Live Update separates and writes the stems.

## How Separation Works

1. Discover the supported audio files in the selected directory.
1. Decode the next file once, resampling it to 44.1 kHz stereo.
1. Run the Demucs model on it to produce the four stems.
1. Keep the stems you selected and write each one as a 16-bit WAV.
1. Write mix.wav when a mix was requested.
1. Report the file and move on to the next one.

Several files are separated in parallel by the shared worker pool. The model is loaded once per run and reused, so the loading cost is paid once rather than per file.

## Output Layout

Each source file writes into its own folder:

    <output>/<track>/vocals.wav\
    <output>/<track>/drums.wav\
    <output>/<track>/bass.wav\
    <output>/<track>/other.wav\
    <output>/<track>/mix.wav        (only when a mix is requested)

Two sources with the same name but different extensions (song.flac and song.wav) would target the same folder. The first one is separated and the second is reported as skipped, so one file never overwrites another's stems.

## Dry Run and Live Update

- **Dry Run: **Lists each file and the stems that would be written. It does not load the model, download weights or create the per-track folder, and it works without the 'ml' extra.
- **Live Update: **Separates each file and writes the stems. The source file is not touched.
- **Disk space: **Each stem is a full-length file, so a four-stem separation of a lossless album needs several times the album's size. WAV stems are uncompressed.

## Processing and Results

Processing shows the worker slots, progress, processed/separated/skipped/error counts and a line per file, such as [SEPARATED], [SKIPPED] or [ERROR]. Results reports the files examined, how many were separated, how many stem files were written, the device used, the elapsed time and the output folder, and can open the log and the output folder.

## Command Line

The registered command is stems. Examples:

audiosuite stems <folder> --output-dir <stems> --dry\
audiosuite stems <folder> --output-dir <stems> --stems vocals,bass\
audiosuite stems <folder> --output-dir <stems> --model htdemucs_ft --mix\
audiosuite stems <folder> --output-dir <stems> --device cpu --live --json

Options include --output-dir (required), --model htdemucs|htdemucs_ft, --stems (comma-separated), --mix/--no-mix, --device auto|cpu|cuda, the shared --dry/--live option and --json. A live run without the 'ml' extra exits non-zero with a message naming the missing dependency.

## Master Driver Use

From the Master Driver, open UTIL and select Stem Separator. The card takes the output folder, model, device and stem selection. The driver passes the directory, mode, start/end behaviour and those settings through the launch handshake. With no output folder the card shows a required-field hint instead of launching a run that could not write anything.

## Troubleshooting

- **A dialog about installing Demucs: **The first live run offers the one-time download. Accept it and the run continues once the install verifies; a failed download says why, and a dry run works without it.
- **Device says CPU on a machine with a GPU: **The installed torch is a CPU build. Install a CUDA build of torch; the reason line names which case applies.
- **No files found: **Select a directory containing supported audio files; subfolders are not scanned.
- **A file errors: **Check codec support, file permissions, free temporary disk space and the per-file log line.
- **The first run pauses: **Demucs is downloading its model weights. Later runs use the cache.
- **A track was skipped as a duplicate: **Another source with the same name already produced that output folder in the same run. Separate them in separate runs.

## Safety and Recovery

Use Dry Run first to confirm the file list and the destination, then audition the stems before deleting anything. Separated stems are never a perfect reconstruction; keep the original files, and keep a backup of anything irreplaceable.
