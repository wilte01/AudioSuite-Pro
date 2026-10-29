---
title: Album Art Normalizer - User Guide
subtitle: Based on the current Album Art Normalizer implementation
---

## Overview

Album Art Normalizer standardizes embedded artwork in every supported audio format. It reads the first embedded image, center-crops non-square artwork, resizes it to a selected square resolution, encodes it as an optimized JPEG, and writes the updated artwork while preserving the other audio metadata.

The GUI also checks for folder.jpg directly inside the selected directory. When present, it is independently normalized to exactly 1000 x 1000 pixels.

## Supported Input

- **Embedded artwork: **Read and written format-aware: ID3 APIC frames for MP3/WAV/AIFF/AIF/DSF, Vorbis Picture blocks for FLAC/OGG/Opus/Speex, APEv2 Cover Art (Front) items for WavPack/Monkey's Audio/Musepack, and MP4 covr atoms for M4A/MP4. A DSF file with no ID3 chunk gets one created.
- **Audio files: **All fourteen suite audio formats are processed by the embedded-art pipeline: .mp3, .flac, .ogg, .m4a, .mp4, .opus, .wav, .aiff, .aif, .wv, .ape, .mpc, .spx, and .dsf.
- **Images: **Embedded data and folder.jpg must be readable by Pillow.

## Quick Start

1. Open Album_Art_Normalizer.pyw from the AudioSuite-Pro folder.
1. On Setup, select the directory containing the music files.
1. Choose 600 x 600, 800 x 800, 1000 x 1000, or 1200 x 1200.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN ARTWORK NORMALIZATION.
1. Review Processing and Results, then use Live Update when ready.

## GUI Tabs

### Setup

Setup contains the folder picker, embedded resolution selector, run mode, and shared controls. The folder must exist and be a directory. The default embedded target is 800 x 800. The last-used directory can be restored from the shared suite configuration.

- **Dry Run: **Use for a preview pass before writing artwork changes.
- **Live Update: **Permits resized embedded artwork to be saved to audio files.
- **Auto Start: **Starts processing automatically when inherited from the Master Driver.
- **Auto End: **Closes the application about two seconds after completion when enabled.
- **Clear Logs and Parallel: **Mirror Master Driver state and are display-only for this tool's standalone processing path.

### Processing

Processing shows a progress bar, live file outcomes, and counts for files examined, images updated, and errors. Work runs in background workers; the normalizer uses one worker per logical CPU by default (at most eight).

### Results

Results shows total time, files examined, images updated, skipped files, and errors. View Log and Open Folder are available. The GUI writes art_normalize_log.txt in the selected directory.

## Image Processing Rules

Artwork is converted to RGB, center-cropped to the largest possible square, resized with Lanczos resampling, and encoded as an optimized JPEG using the suite JPEG quality setting. The crop avoids stretching but removes pixels from the longer dimension of a non-square image.

- **Already at target size: **Skipped without rewriting.
- **No embedded artwork: **Skipped because there is no artwork to update.
- **Unreadable image or tag data: **Reported as an error while other files continue.

## folder.jpg

The GUI checks only the selected directory itself for folder.jpg. If found, it is read as RGB, center-cropped if needed, resized to 1000 x 1000, and saved in place as an optimized JPEG. A missing or already-correct folder.jpg is skipped. The CLI does not run this GUI-only step.

## Command Line

The registered command is artnormalize. It processes embedded artwork in every supported audio format. Examples:

python -m audio_suite_shared.cli_app artnormalize <folder>\
python -m audio_suite_shared.cli_app artnormalize <folder> --size 1000\
python -m audio_suite_shared.cli_app artnormalize <folder> --size 1200 --json

The --size option is an integer square dimension and defaults to 800. The --json option prints the result as formatted JSON; otherwise the command prints processed, skipped, error, and elapsed-time values.

## Master Driver

In the Master Driver, open UTIL and select Album Art Normalizer. The card uses the shared directory and run controls and launches the tool with the selected path. The standalone GUI exposes all four resolution choices. A driver launch can inherit control values and auto-start behavior.

## Safety and Recovery

Use Dry Run before a live run and keep backups of important audio files. Artwork is written back into the original audio files, while folder.jpg is written back as the directory image. The tool participates in the suite's batch undo mechanism for recorded tag edits; this does not replace backups.

## Troubleshooting

- **The run will not start: **Choose an existing directory and a valid resolution.
- **Everything is skipped: **Files may already match the target or have no embedded artwork.
- **The image is cropped: **Center-cropping is intentional for square output without distortion.
- **A file errors: **Check whether its tags, artwork bytes, or file permissions allow reading and writing.
- **folder.jpg is unchanged: **It may be missing, outside the selected directory, or already 1000 x 1000.
- **The CLI rejects the folder: **Correct the path; CLI argument validation requires an existing directory.
