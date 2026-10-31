---
title: Restoration (Declip) - User Guide
subtitle: Based on the current Restoration implementation
---

## Overview

Restoration rebuilds the peaks a recording lost to clipping. A clipped signal is not merely loud: everything above the ceiling was cut off, so the waveform's top and bottom are **flat**, and that flat edge is what the ear hears as a gritty, smeared distortion on loud passages.

The tool finds those flat tops — against the file's own peak, so a limiter ceiling below full scale is found as readily as a 0 dBFS master — and reconstructs each one by interpolating through the clean samples either side of it. A file with nothing to repair is reported as clean and **left exactly as it is**.

Only declipping is included in this version. De-reverb and spectral repair are separate sub-items and are not part of this tool yet.

## Supported Files

The processor uses the shared Audio Suite supported formats: MP3, FLAC, OGG, Opus, M4A, MP4, WAV and AIFF variants. Read-only containers are reported and skipped, because an in-place repair has to write the file back.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the formats the suite reads and writes; ffprobe reads stream metadata. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Restoration.pyw.
1. Select the folder holding the files to check.
1. Leave Dry Run selected and click RECONSTRUCT PEAKS.
1. Read the report: `[FOUND]` marks a file that would be repaired, `[SKIP]` a file that is already clean.
1. If the found count looks right, choose Live Update, run again, and audition a repaired file against your backup.

## Setup

Setup opens with the shared Run Controls strip — source folder, **Browse**, the **Mode** dropdown, the driver's Auto Start / Auto End / Clear Logs / Parallel display, and the **RECONSTRUCT PEAKS** button — followed by this tool's own **Detection** group.

- **Clipping threshold:** how close to the file's own peak a sample must be to count as a clipping candidate. The default **0.98** means "within 2 % of the loudest sample in this file", which finds a ceiling the source was limited to as well as a full-scale one. Lowering it widens the candidate search; the flat-top test below still decides what is actually repaired.
- **Maximum plateau width:** the longest flat top the repair will attempt, in milliseconds. The default is **50 ms**. A wider plateau is counted and reported but never invented, because it is more likely to be the waveform itself — a square wave, a synthesised pad, an edit — than a clipped peak.
- **Presets:** the shared preset row saves the threshold, the width limit and the run mode.

## How Detection Works

Three rules, each of which exists to keep clean audio out of the repair:

1. **Candidates** are the samples at or above the threshold fraction of the file's own peak. A file whose peak is below about −26 dBFS is not examined at all: near-silence is flat everywhere.
1. **The plateau** is only the run of samples at the *highest* magnitude inside a candidate region. A peak that merely touches the ceiling is curved — exactly one sample sits at the top — so it yields no plateau and is left alone.
1. **Clean context** must exist on both sides: the samples immediately either side have to sit below the plateau's level. Without that, the "flat top" is simply the waveform, which is why a square wave is refused rather than rounded off.

A plateau is also rejected when the reconstruction cannot rise above it by at least a small margin (about −60 dBFS). If a repair cannot beat the original, it is not a repair.

## How the Repair Works

The flat top is rebuilt with a cubic-spline interpolation through the clean samples either side of it. A flat top *under*-estimates the true peak, so the spline's natural overshoot is the restoration: for a clipped sine it returns the arc the waveform had before the ceiling cut it.

The result is capped at full scale, so the repair cannot introduce clipping of its own, and a second pass over the repaired file finds nothing to do.

## Measured Behaviour

The numbers below are the acceptance measurements recorded for this version, taken on a 1 kHz reference tone whose true peak is −0.1 dBFS and which was hard-clipped to a 0.8 ceiling:

- **Harmonic distortion:** −21.38 dB before, −46.82 dB after — a **25.45 dB** improvement.
- **Peak:** −1.938 dBFS before, −0.188 dBFS after, against the original's −0.100 dBFS.
- **Clean input:** unchanged, byte for byte, in both dry and live runs.
- **A 0 dBFS ceiling** (a source with a true peak above full scale) cannot be reconstructed inside the file's own scale, so it is reported and left alone rather than clipped further.

## Dry Run and Live Update

- **Dry Run:** detects and reports. Nothing is written; a detected file is marked `[FOUND]` and Result playback stays unavailable.
- **Live Update:** exports the repaired audio to a temporary file, restores the original tags, records the pre-run file in the suite's undo history, then copies the result over the source.
- **Clean files:** a file with nothing to repair is skipped and **not rewritten**, so its bytes are untouched.
- **Depth and rate:** the source's sample rate, channel count and bit depth are preserved — a 24-bit source stays 24-bit.
- **Undo:** each live write is reversible from Undo Tag Edits while the batch is still in its capped history.

## Processing and Results

Processing shows one worker slot per logical CPU (at most eight), a progress bar, the shared processed / succeeded / skipped / error count and one line per file: `[FIXED]` for a repair, `[FOUND]` in a dry run, `[SKIP]` for a clean file, `[ERROR]` for a file that failed.

Results reports total, repaired, skipped and errors with the elapsed time, and offers **Open Log**, **Open Folder** and — after a successful live run — the original/result audition pair.

## Command Line

The registered command is declip. Examples:

python -m audio_suite_shared.cli_app declip <folder> --dry\
python -m audio_suite_shared.cli_app declip <folder> --live --threshold 0.95 --max-run-ms 20\
python -m audio_suite_shared.cli_app declip <folder> --dry --json

Options include --threshold, --max-run-ms, the shared dry-run/live option and --json. A threshold outside 0–1 or a width below 1 ms is refused as a usage error rather than starting a run that cannot work.

## Audio Refinery and Master Driver

Restoration is available as a standalone utility tool with its own card in the Master Driver, which passes the folder, the mode, the threshold and the width limit. It is not a Refinery stage in this version.

## Troubleshooting

- **Everything is clean:** that is the expected result for a file that was never clipped. The detector reports a plateau only when the waveform has a genuinely flat top.
- **A loud master is reported clean:** the ceiling may be above the threshold fraction, or the peaks may be curved rather than flat. Try a threshold of 0.95 and check the dry-run report again.
- **A square or synth-heavy track is refused:** its waveform *is* flat, so there is no clean context to interpolate through. Leaving it alone is deliberate.
- **A file with a 0 dBFS ceiling is not repaired:** the reconstruction would have to exceed full scale. Restore that one from a higher-resolution source instead.
- **The repair changed a file you liked better:** the undo history holds the pre-run copy; Undo Tag Edits restores it byte for byte. Audition before running Live Update over a whole library.
- **A file errors:** check codec support, permissions, temporary disk space, and the per-file message in the Processing tab.

## Safety and Recovery

Run Dry Run first and audition representative files. Live Update replaces the source only after the temporary export succeeds, and every write is recorded for undo. Keep your own backups of masters you care about.
