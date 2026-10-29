---
title: Music Format Converter - User Guide
subtitle: Based on the current Music Format Converter implementation
---

## Overview

Music Format Converter converts a directory of audio files to another format with FFmpeg. It preserves metadata through the conversion path, supports format-specific quality controls, can resample audio, can choose WAV bit depth, dithers bit-depth reductions with TPDF noise, and optionally applies lossless MP3 loudness gain after conversion.

The converter is designed for a single input format per folder. It scans the input directory before processing and filters the valid output formats for that input.

## Requirements

- **FFmpeg: **Required for conversion. The GUI checks availability before starting.
- **Input directory: **Scanned recursively — every subfolder is included automatically.
- **Mixed input formats: **Supported. Each file is converted from its own format to the target, and the detected files are listed per format.
- **Output structure: **Subfolders are mirrored in the output directory, so tracks with the same filename in different subfolders stay separate.

## Supported Formats

- **Lossy: **MP3, AAC, M4A, OGG, Opus, MP4, WMA, and SPX are recognized as lossy formats.
- **Lossless/uncompressed: **FLAC, WAV, ALAC (M4A container), APE, AIFF, AIF, WV, MPC, and DSF are recognized as lossless input categories.
- **ALAC output: **ALAC is written inside an M4A container, so the output file is named with the .m4a extension, not .alac. ALAC and AAC-M4A share that extension, so a later run to either format replaces the earlier .m4a file with the same name.
- **Unsupported output: **APE, MPC, and DSF can be detected as input but are excluded as outputs because the converter has no supported encoder for them.
- **Conversion restrictions: **Same-format conversion is prohibited, and lossy input cannot be converted to a lossless output because quality cannot be recovered.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Music_Format_Converter.pyw.
1. Select an input directory containing one audio format.
1. Select an output format from the formats allowed for that input.
1. Choose quality, sample rate, bit depth where applicable, and an output folder.
1. Leave Delete Originals disabled and review the Dry Run preview first.
1. Click the conversion start button and monitor Processing.
1. Review Results and the conversion log before using deletion or a large batch.

## Setup

Setup contains the input directory, output format, quality, sample rate, WAV bit depth, MP3 normalization, target LUFS, output directory, presets, and run controls. Changing the input folder triggers a scan and updates the detected-format label and output-format choices.

- **Input Directory: **The source folder to scan. The converter processes supported files in that directory.
- **Output Format: **The selected target extension. The menu excludes the detected input format, invalid lossy-to-lossless targets, and unsupported APE, MPC, and DSF output.
- **Quality: **Format-specific codec quality or bitrate selection.
- **Sample Rate: **Keep source or choose a supported rate such as 44100, 48000, 88200, 96000, 176400, or 192000 Hz.
- **Bit Depth: **Relevant to WAV output: Auto, 16, 24, 32, or float, with source-preserving behavior where supported.
- **Dither (TPDF): **On by default. Applies triangular-PDF dither whenever the output depth is lower than the source, for WAV and AIFF alike. This removes the tonal quantization distortion that a bare depth reduction produces; leave it on unless you specifically need bit-identical legacy output.
- **Resampling: **Whenever a sample rate other than Source is chosen, the conversion uses the SoX resampler for a steep, alias-free anti-alias filter.
- **Output Directory: **Optional separate destination. If blank, output defaults to the input directory.
- **Delete Originals: **Deletes the source only after a successful converted output exists, with confirmation in the GUI.
- **Normalize MP3: **Optionally measures the converted MP3 and applies lossless track gain toward the target LUFS, default -16 LUFS.

## Quality Options

- **MP3: **VBR V0 (highest), VBR V2 (high), or CBR 192 kbps (medium).
- **AAC: **AAC at 320, 256, or 192 kbps (same tiers as M4A).
- **FLAC: **Always compression level 8; no quality tiers apply.
- **WV (WavPack): **Always lossless; no quality tiers apply.
- **OGG: **Vorbis quality 10, 8, or 6.
- **M4A: **AAC at 320, 256, or 192 kbps.
- **MP4: **AAC at 320, 256, or 192 kbps (same tiers as M4A).
- **Opus: **256, 192, or 128 kbps.
- **ALAC: **Always lossless; no quality tiers apply. Output is an M4A-container file.
- **AIFF / AIF: **24-bit PCM at highest/high, 16-bit PCM at medium. Because the quality preset alone selects the depth, the dither option applies to the 16-bit tiers as well.
- **WMA: **320, 256, or 192 kbps.
- **SPX (Speex): **Speex quality 8, the codec's top tier (a single fixed tier).

## Conversion Behavior

1. Discover supported files in the input directory.
1. Validate that input and output formats are compatible.
1. Build FFmpeg parameters for the selected format, quality, sample rate, and bit depth.
1. Apply the dither and resampler filter: TPDF dither on a depth reduction, and the SoX resampler on any sample-rate conversion.
1. Convert each file with retry handling and write the output filename with the target extension.
1. Preserve metadata through the conversion path.
1. Optionally measure and losslessly adjust MP3 output toward the target LUFS.
1. Optionally delete the original after output success and record the deletion snapshot.

## Dry Run and Live Update

- **Dry Run: **Simulates each valid conversion, estimates input/output size, reports deletion and MP3-normalization actions, and writes no audio files.
- **Live Update: **Runs FFmpeg conversion and writes outputs to the destination or input directory.
- **Skipped: **Same-format conversions, lossy-to-lossless conversions, unsupported output targets, and configured recovery skips are reported as skipped.
- **Errors: **FFmpeg failures, timeouts, permissions, and unexpected failures are reported as errors.
- **Undo: **Original deletion is recorded in the suite file-delete undo context; conversion itself does not alter the source unless Delete Originals is enabled.

## Processing and Results

Processing shows one worker slot per logical CPU (at most eight), progress, converted/skipped/error counts, and per-file status lines. Results reports totals and elapsed time. Converted lines include source and output sizes, optional loudness-gain status, and original-deletion status.

## Logs

The converter writes its processing log in the resolved output directory. The log contains per-file conversion status, format transition, size information, the Dither (TPDF) ON/OFF setting, skipped reasons, errors, and summary counts.

## Command Line

The registered command is convert. Examples:

python -m audio_suite_shared.cli_app convert <folder> --format flac --dry\
python -m audio_suite_shared.cli_app convert <folder> --format mp3 --quality highest --output-dir <out>\
python -m audio_suite_shared.cli_app convert <folder> --format mp3 --normalize-mp3 --target-lufs -16\
python -m audio_suite_shared.cli_app convert <folder> --format m4a --delete-originals --live --json\
python -m audio_suite_shared.cli_app convert <folder> --format wav --bit-depth 16 --no-dither

CLI options include --format, --quality, --sample-rate, --bit-depth, --output-dir, --dither/--no-dither, --normalize-mp3, --target-lufs, --delete-originals/--keep-originals, --dry/--live, --preset, and --json. Saved presets can supply output and quality settings.

## Master Driver Use

From the Master Driver, open UTIL and select Music Format Converter. The card detects input formats from the shared directory, passes the shared mode and orchestration state, and launches the converter workflow. Use the standalone Setup controls for quality, output, and deletion choices.

## Troubleshooting

- **No output format available: **The input may have no supported files, may contain only APE, MPC, or DSF files, or every valid output may be prohibited by conversion rules.
- **Some files skipped in a mixed run: **Files already in the target format, and lossy files targeted at a lossless format, are skipped per file — the rest still convert.
- **Two sources produced the same output name: **When two files in one folder share a stem but differ in extension (for example song.flac and song.wav both targeting song.mp3), only the first is converted; the other is reported as skipped rather than overwriting the first output.
- **FFmpeg required: **Install FFmpeg and ensure the application can find it before starting.
- **Conversion skipped: **Check whether input and output are the same format or whether a lossy-to-lossless conversion was requested.
- **Originals were not deleted: **Deletion occurs only after output success and may fail separately; review the status and log.
- **MP3 normalization failed: **Conversion can still succeed while gain status reports measurement or gain failure. Review the log and output file.

## Safety and Recovery

Use Dry Run first and choose a separate output directory while testing. Keep Delete Originals disabled until outputs are verified. Live deletion is recorded for undo support, but independent backups remain the safest recovery method.
