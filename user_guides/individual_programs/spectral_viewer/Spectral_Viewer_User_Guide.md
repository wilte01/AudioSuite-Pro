---
title: Spectral Viewer - User Guide
version: auto
---

Based on the current Spectral Viewer implementation (FFT 2048, hop 512, magma)

## Overview

Spectral Viewer draws an FFT spectrogram of an audio file: time runs left to right, frequency bottom to top, and colour is loudness in dB relative to the loudest point in the picture. It is an inspection tool. It never retags, re-encodes or moves an audio file; the only files it writes are PNG images you ask for.

The tool has two front ends over one implementation: this window, and the headless `audiosuite spectrogram` command, which renders a whole folder and writes one `<name>_spectrogram.png` per file.

## Quick Start

1. Open Spectral_Viewer.pyw.
1. Type or browse to a folder (or a single audio file).
1. Click Scan to list the folder's audio files.
1. The first file renders immediately; pick any other file in the list.
1. Adjust the time window, frequency ceiling, colour range or FFT size and click Render.
1. Use the toolbar to zoom or pan, then Export PNG to save the view.

## What You Are Looking At

- **Time axis: **seconds from the start of the file. A selected window keeps the real position, so a window starting at 60 s is labelled from 60 s.
- **Frequency axis: **Hz, linear, from 0 to Nyquist (half the sample rate) unless a ceiling is set. Set 20000 to see whether a lossy encoder has cut the top off; set 2000 to inspect bass and vocal fundamentals.
- **Colour: **dB relative to the loudest bin in the image, floored at the colour range (80 dB by default). The status bar also reports the absolute peak in dBFS, so a quiet master and a hot one are distinguishable even though both are normalised for display.
- **Bright bands: **harmonics and sustained tones. A hard horizontal edge near the top is a codec low-pass; vertical smears are transients such as drum hits.

## Settings

| Setting | Default | What it does |
| --- | --- | --- |
| Time window (start/end) | 0 / 0 | Seconds. 0 for end means the whole file, capped at 600 s. |
| Max frequency | 0 | Highest displayed frequency in Hz; 0 keeps the full Nyquist range. |
| Colour range | 80 | Floor in dB below the peak. |
| FFT size | 2048 | Samples per FFT window: larger resolves pitch better, smaller resolves time better. 256-16384. |
| Colour map | magma | magma, inferno, viridis, plasma or gray. |

## Zoom and Pan

The toolbar under the figure is matplotlib's standard navigation bar: the crosshair toggles box zoom (drag a rectangle), the arrows pan, the house restores the full view, and the disk button saves the current view. Zoom and pan change only what is displayed, not the computed spectrogram, so they never blur the data or re-decode the file.

## Exporting a PNG

- **Window: **Export PNG writes the figure exactly as displayed, including any zoom. The suggested name is the source stem plus `_spectrogram.png`.
- **Command line: **`audiosuite spectrogram <path>` writes one image per audio file, either beside the source or into `--output-dir`.
- **Dry run: **`--dry` prints every path it would write and writes nothing, so a Master Driver Dry Run leaves no images behind.

## Command Line

The command accepts a file or a directory. A directory is walked recursively and only supported audio extensions are rendered.

| Flag | Default | Meaning |
| --- | --- | --- |
| --output-dir DIR | beside source | Where the PNGs go. |
| --n-fft N | 2048 | FFT window size in samples. |
| --hop-length N | 512 | Samples between frames. |
| --start S | 0 | Window start in seconds. |
| --end S | 0 | Window end in seconds; 0 = to the end. |
| --max-freq HZ | 0 | Highest displayed frequency; 0 = Nyquist. |
| --db-range DB | 80 | Colour floor below peak. |
| --cmap NAME | magma | Matplotlib colour map. |
| --dry/--live | live | --dry lists planned images, writes none. |
| --json/--text | text | Machine-readable summary. |

Examples: render one file to a folder, and preview a whole library without writing anything:

audiosuite spectrogram "D:\Music\Album" --output-dir "D:\Spectrograms"\
audiosuite spectrogram "D:\Music" --dry

## Supported Formats

MP3, FLAC, OGG, Opus, Speex, M4A, MP4, WAV, AIFF, AIF, WavPack, Monkey's Audio, Musepack, and DSF.

Decoding uses the shared analysis loader, so the Sprint 1 containers (WavPack, Monkey's Audio, Musepack, Speex, DSF) decode through its FFmpeg fallback. If a file cannot be decoded, that file is reported and the run continues with the rest.

## Log Files

The window logs to logs/spectral_viewer.log and the suite administrator log logs/audio_suite.log carries lifecycle lines and warnings. Per-file failures are shown in the window and written to the tool log.

## Troubleshooting

- **Nothing renders: **confirm the path exists and contains supported audio; the status bar says how many files Scan found.
- **"Window is shorter than the FFT size": **lower the FFT size or widen the time window; a 2048-sample window needs about 46 ms at 44.1 kHz.
- **"Could not decode": **the file may be corrupt or a codec FFmpeg cannot read. The rest of the folder still renders.
- **Detail looks smeared: **lower the FFT size. Pitch looks imprecise: raise it. There is no single setting that is best for both.

## Read-Only Safety

Spectral Viewer opens audio files for reading only. It never writes tags, never re-encodes, and never deletes or moves a source file. Exporting writes a PNG; a dry run writes nothing at all.
