---
title: Audio Enhancer - User Guide
subtitle: Based on the current Audio Enhancer implementation
---

## Overview

Audio Enhancer applies a configurable DSP chain to audio files and writes enhanced copies to an output folder. It measures the source and processed RMS levels, reports the gain change, writes the audio in its original format family, and copies source metadata tags to the result.

The application accepts either one audio file or a folder of supported audio files. Leave the output folder blank to replace files in place, or select a different output folder to preserve the originals.

## Supported Audio

The processor uses the shared Audio Suite format list. Supported extensions are .mp3, .flac, .ogg, .m4a, .mp4, .opus, .wav, .aiff, and .aif. A single selected file is processed directly; a selected directory is scanned for supported files in that directory.

- **MP3 output: **Preserves the source CBR/VBR quality selection when writing the enhanced file.
- **FFmpeg-backed formats: **Formats such as M4A, MP4, Opus, and other configured formats use the tool's FFmpeg I/O path when required.
- **Formats skipped: **The shared Audio Suite format list also includes .wv, .spx, .ape, .mpc, and .dsf. The enhancer cannot re-encode these (WavPack and Speex have no encoder on this path, and Monkey's Audio, Musepack, and DSD are read-only), so such files are reported as skipped rather than processed.
- **Metadata: **Tags are copied after the audio output is written, including ID3, Vorbis-style, MP4, and available WAV metadata through the shared tag implementation.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Audio_Enhancer.pyw from the AudioSuite-Pro folder.
1. Choose a source file or folder.
1. Leave Output folder blank for in-place replacement, or select a separate output folder.
1. Select Mild, Moderate, Aggressive, or Custom.
1. For a first pass, use a separate output folder and the Moderate preset.
1. Click BEGIN ENHANCEMENT.
1. Review the Processing and Results tabs, then audition the original and result when available.

## GUI Tabs

### Setup

Setup contains the source path, output folder, the Preset selector, and the Custom DSP summary row. Browse for a folder or a single audio file. If the output folder is blank, the application uses the source directory and overwrites the source filename with the enhanced output. The last source location is remembered in shared suite configuration.

- **Preset: **One selector for both kinds of preset. The built-in presets (Mild, Moderate, Aggressive, Custom) change DSP values only. Saved presets appear below a divider and also restore the source and output paths stored with them. The caption under the selector states which kind is active and, for a saved preset, names the built-in preset it carries. Save stores the current settings under a new name; Delete removes the selected saved preset and is greyed out while a built-in preset is selected.
- **Custom: **Selecting it shows a Configure Custom DSP button and opens the parameter editor in its own non-modal window, which stays open while you start a run and applies changes immediately. The Setup tab keeps only the summary row, so the BEGIN ENHANCEMENT button is always visible.
- **BEGIN ENHANCEMENT: **Validates the source path, resolves the output directory, then starts background processing.

### Processing

Processing shows an overall progress bar, processed/enhanced/error counts, and per-file status lines. Four worker slots are used by default. Each worker may retry a processing operation up to three times with backoff before reporting an error. A file that disappears during processing is reported as skipped; permission and other processing failures are reported as errors.

### Results

Results shows total time, total files, enhanced files, and errors. The log is written as enhancement_log.txt in the output directory. When a successful result is available, the Results tab exposes original and enhanced audition controls. For an in-place run, the app preserves an audition copy of the original before replacement; for a separate output run, it compares the source file with the new output file.

## DSP Presets

Preset values are defined in code and configure the complete enhancement pass. The presets are starting points, not loudness guarantees; always listen to a representative result before processing a large library.

- **Mild: **Noise gate -70 dB, compression threshold -18 dB at 2.5:1, gentle low/presence/high-shelf boosts, +2 dB output gain, -1 dB limiter.
- **Moderate: **Noise gate -65 dB, compression threshold -22 dB at 3.5:1, stronger EQ shaping, +4 dB output gain, -0.5 dB limiter. This is the default.
- **Aggressive: **Noise gate -60 dB, compression threshold -26 dB at 5:1, stronger EQ and +6 dB output gain, -0.3 dB limiter.
- **Custom: **Opens the Custom DSP editor; its current values are used for the enhancement pass.

## Custom DSP Controls

- **Noise Gate Threshold (dB): **Sets the threshold for quiet-signal gating; range -90 to -40 dB.
- **Compressor Threshold (dB): **Sets the level where compression begins; range -40 to -6 dB.
- **Compressor Ratio: **Sets compression strength; range 1:1 to 10:1.
- **Compressor Attack / Release: **Controls compressor response timing; attack range 1 to 50 ms and release range 20 to 500 ms.
- **Low Shelf Gain / Frequency: **Shapes low frequencies with gain from -6 to +12 dB and frequency from 40 to 400 Hz.
- **Presence Gain / Frequency: **Shapes the presence band with gain from -6 to +12 dB and frequency from 500 to 8000 Hz.
- **High Shelf Gain / Frequency: **Shapes high frequencies with gain from -6 to +12 dB and frequency from 2000 to 16000 Hz.
- **Output Gain: **Applies final gain from -6 to +18 dB before limiting.
- **Limiter Threshold: **Sets the final ceiling; the value must be at or below 0 dB and the UI range is -12 to -0.1 dB.

## Effects

The Custom DSP editor also exposes five optional effects, and the command line can enable the same effects through flags. All five default to off, so a preset run or an untouched Custom run produces exactly the same output as before the effects existed. Applying a preset resets only the numeric DSP values; it never changes the effect toggles. Reverse and karaoke are applied before the main chain, while the phaser, flanger, and chorus run after the EQ shaping. Dry Run applies the same chain as a live run — effects included — and only skips writing the file and copying tags, so the level it reports is the level you would get. A cancelling effect therefore shows as the drop it really is: karaoke on a centred mix reports near-silence in a dry run, exactly as the written file would.

- **Reverse: **Reverses the audio playback direction.
- **Karaoke: **Removes centre-panned content (typically lead vocals) by subtracting one channel from the other. Karaoke Strength, 0 to 1, blends between the original and the fully removed signal. Mono input is returned unchanged.
- **Phaser: **A sweeping phase effect applied after the EQ shaping.
- **Flanger: **A short modulated delay mixed with the dry signal.
- **Chorus: **Multiple slightly detuned copies added after the flanger.

## Processing Pipeline

1. Inspect the source for format, sample rate, channels, duration, bitrate, VBR state, and tag count.
1. Read audio through pedalboard I/O or the FFmpeg-backed path for formats that need it.
1. Apply any enabled effects, then the enhancement chain: reverse and karaoke first, then gate/compression, EQ shaping, phaser, flanger, and chorus, followed by output gain and limiting.
1. Measure RMS before and after processing and run the post-chain clip check.
1. Write the enhanced audio to the output path, preserving the source extension and relevant quality settings.
1. Copy tags from source to output and report the number of copied tag frames or fields.

## In-Place versus Separate Output

- **Separate output: **Recommended for review. The source remains available and the result is written to the chosen output directory with the same filename.
- **In-place output: **The source directory is used as output, so the original file is replaced. The app prepares an audition copy for the first result when possible.
- **Output creation: **The output directory is created when needed. A log is always associated with the resolved output directory.

## Command Line

The registered command is enhance. It requires an output directory and uses a named preset. Examples:

python -m audio_suite_shared.cli_app enhance <folder> --output-dir <output>\
python -m audio_suite_shared.cli_app enhance <folder> --output-dir <output> --preset mild\
python -m audio_suite_shared.cli_app enhance <folder> --output-dir <output> --preset aggressive --json

The CLI accepts Mild, Moderate, Aggressive, or Custom presets case-insensitively. Custom uses the neutral default DSP values, since the CLI has no per-slider options. Use --json for structured output; normal output reports files, enhanced count, errors, and elapsed time.

The effects are available as flags: --reverse, --phaser, --flanger, --chorus, and --karaoke (or --no-karaoke to leave it off), plus --karaoke-strength with a value from 0.0 to 1.0. For example:\
python -m audio_suite_shared.cli_app enhance <folder> --output-dir <output> --karaoke --karaoke-strength 0.8

## Master Driver Use

Audio Enhancer is reachable three ways: its own window, the Audio Enhancer stage of the Master Driver's REFINE tab, and the Audio Enhancer card on the Master Driver's UTIL tab. The UTIL card requires an output folder and pre-fills the preset with Mild, Moderate, Aggressive, or Custom; Custom starts the tool with the DSP values it currently has loaded, because the card has no sliders. From the REFINE tab the driver supplies the source, stage configuration, output, and inherited orchestration settings. Direct launch is useful when you need the full Audio Enhancer Setup controls and audition view.

## Troubleshooting

- **No supported audio files found: **Select a supported file or a folder containing supported extensions directly inside it.
- **The result sounds too strong: **Use Mild or reduce Custom output gain, EQ gains, compression ratio, or compression threshold strength.
- **Tags are missing: **Review the result log. Tag copying depends on readable source tags and supported destination metadata.
- **A file reports an error: **Check codec support, file permissions, locks, available disk space, and the detailed enhancement_log.txt entry.
- **The output overwrote the source: **The Output folder was blank or resolved to the source directory. Use a separate output folder for review runs.
- **Audition is unavailable: **No successful output or no usable original/result pair was available for the selected run.

## Logs and Recovery

The enhancement_log.txt report records each completed, skipped, or failed file, the measured RMS gain for successful files, copied tag counts, and the final summary. In-place enhancement changes source audio files, so use a separate output directory or maintain an independent backup before processing important material.
