---
title: Audio Refinery - User Guide
subtitle: Based on the current Audio Refinery implementation
---

## Overview

Audio Refinery is a single-pass audio processing pipeline. It loads each source file once, runs the selected stages in memory, exports the result, restores the original tags, and optionally applies loudness normalization. The final file is placed in a separate output folder or atomically replaces the source when running in place.

The window has three tabs in the order a run happens: **1. Setup**, **2. Processing**, **3. Results**. Inside Setup the controls read top to bottom: Presets, the run controls, the output folder, then the six stage panels in the order the pipeline runs them - Pop & Click Remover, Silence Trimmer / Fader, Noise Reduction, Parametric EQ, Audio Enhancer, Audio Normaliser - and finally Reset Progress and BEGIN REFINERY. The subtitle under the window title names that same order: **Declick -> Trim -> Noise Reduction -> EQ -> Enhance -> Normalise**. This guide follows the window in that order.

The pipeline is designed to combine several suite tools without repeatedly decoding and encoding the same file. It validates file integrity before expensive DSP work, sizes its worker slots from the CPU count (at most eight), retries transient failures, and records completed files in a hash-based registry.

## Supported Audio

The refinery discovers the shared Audio Suite audio extensions, including MP3, FLAC, OGG, M4A, Opus, and WAV. The pipeline uses pydub/FFmpeg-backed decoding and format-aware export. Files must pass existence, readability, size, container-header, decode, sample-rate, duration, and channel checks before processing.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Open Audio_Refinery.pyw.
1. On the Setup tab, select a source folder containing supported audio files.
1. Optionally choose an output folder; leave it blank for in-place replacement.
1. Pick a saved Preset, or start from the stage selection the window opens with: Pop & Click Remover, Silence Trimmer / Fader, Audio Enhancer and Audio Normaliser are enabled, while Noise Reduction and Parametric EQ are off until you tick them.
1. Open each stage's Settings to adjust it, and add Parametric EQ bands if you want to shape the tone.
1. Leave Mode set to Dry Run for the first pass.
1. Click BEGIN REFINERY.
1. Follow the run on the Processing tab, then review the Results tab's counters, refinery_log.txt and audition controls.
1. Switch Mode to Live Update only after confirming the intended stages and output.

## The Setup Tab

![The Setup tab with the six stage panels, in the order the pipeline runs them](images/setup.png)

The Setup tab holds everything a run needs, in the order you work through it.

### Presets

The Presets row saves, loads, and deletes the complete stage configuration, including stage toggles and stage parameters. Loading a preset restores the stage panels you see - including the Parametric EQ band table and its curve - so the window always shows the settings the next run will use.

### Run Controls

- **Source Music Directory: **Required directory containing supported audio files. The application validates the directory and checks for audio before starting.
- **Mode: **Dry Run (the default) or Live Update. Dry Run validates and decodes each file and runs the enabled stages' detection without writing anything; Live Update runs the selected stages and writes the results.
- **Auto Start, Auto End, Clear Logs, Parallel: **These mirror the Master Driver's control strip and are marked "(driver only)". Run the tool standalone and Auto Start, Clear Logs and Parallel are greyed out, while Auto End is editable but has nothing to end. They take effect only when the Master Driver launches the Refinery.

### Output Folder

Optional. Blank means in-place replacement; a selected existing directory receives results with the source filenames. The directory must already exist.

### Stage Controls

The six collapsible stage panels sit below the paths, in the order the pipeline applies them. Each panel has a checkbox that enables the stage for the run, and a **Settings** expander that reveals that stage's controls. Tick a stage and open its Settings to change anything; the values you see are the values the run uses.

At least one stage must be enabled. The window opens with Pop & Click Remover, Silence Trimmer / Fader, Audio Enhancer and Audio Normaliser enabled, and Noise Reduction and Parametric EQ disabled; enable the two optional stages when a file needs them.

#### Pop & Click Remover

- **Click sensitivity: **Default 0.31; controls click detection. Lower values are more aggressive according to the stage model.
- **Maximum defect width: **Default 2 ms; limits the click width repaired.

#### Silence Trimmer / Fader

- **Trim threshold: **Default -50 dBFS; defines silence for trimming.
- **Fades: **Optional fade-in default 500 ms and fade-out default 1000 ms after trimming.
- **Trim by: **Silence (the default) trims detected leading and trailing silence. Exact range keeps the millisecond span you enter instead: set Start (default 0) plus either End or Duration, never both. The range is checked against each file's own length before anything is written, so a range past the end of a file fails that file with both lengths in the message.
- **Exact trim accuracy: **Without Stream copy the range is cut from the decoded audio, so it is sample-accurate to the millisecond, and the file is written once through the normal export path with its bit depth preserved. With Stream copy on, the source's own frames are copied, so nothing is re-encoded but the cut lands on the container's frame boundary: an MP3 frame is about 26 ms, and the run log reports the length the copy actually produced and how far it moved. Stream copy cannot run beside the Declick, Noise Reduction, EQ, Enhance or Normalise stage, because those need the decoded audio; the run refuses that combination before touching a file rather than quietly re-encoding and calling it a copy. It supports MP3, FLAC, M4A/MP4, OGG and Opus; other containers are refused with a message that names the container.

#### Noise Reduction

Off until you tick the stage. Two independent halves:

- **Enable Hum Removal: **removes mains hum at **50 Hz** or **60 Hz**, with **Harmonics (1-20)** default 8 and **Q Factor (1-100)** default 30.
- **Enable Broadband Noise Reduction: **uses a noise profile taken from **Noise Start (ms)** to **Noise End (ms)** - defaults 0 to 500 ms - and a **Gate Threshold (dB)** default 3.

#### Parametric EQ

Off until you tick the stage. Parametric EQ shapes tone with up to eight bands instead of the three fixed shelves the enhancement preset carries. Tick **Parametric EQ** and open its **Settings** to add a band:

- **Kind: **low shelf, high shelf, peaking, high-pass or low-pass.
- **Hz, dB and Q: **type the frequency in Hz, the gain in dB and the Q, then press **Add / Update**.
- **Editing a band: **selecting a row loads it back into those fields, so Add / Update replaces that band rather than adding a second copy of it, and **Remove** deletes the selected band.
- **The curve: **drawn under the table from the same filters the run applies, by measuring their impulse response, so it shows the shape the file will have. The panel writes each edit straight into the run's configuration, which is why the curve and the audio cannot disagree.
- **Bypass: **keeps the bands in the panel and in a saved preset while leaving the signal untouched, and an empty rack does the same.

High-pass and low-pass bands are first-order in the installed engine, so their gain and Q boxes are disabled while one is selected: a control that cannot apply is not offered. A band outside 20 Hz to 20 kHz, a gain past +/-24 dB, a Q outside 0.1 to 18, or a high-pass/low-pass band carrying a gain or a non-default Q is reported in the panel and never enters the rack, and a band at or above the file's Nyquist frequency is refused by the run rather than moved.

A preset stores the EQ stage's toggle and every band, and loading one restores the table and the curve. The stage runs after Noise Reduction and before Audio Enhancement, so the preset's compressor and limiter act on the shaped signal, and it cannot run beside Stream copy, which writes the source's own frames without decoding them.

#### Audio Enhancer

- **Preset: **Mild, Moderate, Aggressive, or Custom. Selecting Custom shows a Configure Custom DSP button that opens the stage's own non-modal editor, so the stage itself stays compact and every control is reachable; changes apply to the run as you make them. When Audio Normaliser is active, the refinery suppresses enhancement output gain so final loudness is controlled by the normalizer, and the Output Gain control is hidden because it has no effect.
- **Enhancement effects: **Relevant to the Custom preset: Reverse audio, Karaoke (centre-vocal removal with a 0.0-1.0 strength), Phaser, Flanger, and Chorus. Each is off by default, and the built-in Mild, Moderate, and Aggressive presets leave them off.

#### Audio Normaliser

- **Target: **Playlist loudness (the default) targets integrated loudness in LUFS. Peak targets the file's true peak in dBTP instead, with one static gain, so the track keeps its own dynamics and only its level moves. Peak mode and Album loudness cannot be combined: choosing one clears the other, and the command line refuses the pair.
- **Target LUFS: **Permitted targets are -12, -14, -16, -18, and -23 LUFS; default -14.0.
- **Tolerance: **Default 0.5 LUFS; used by the normalization stage to avoid unnecessary adjustment when loudness is already close to target.
- **True peak target: **Default -1.0 dBTP; used by the Peak target. A gain that would push the sample peak past full scale is held by the limiter instead of being clamped, and the stage reports the sample peak and the true peak it measured after the write. A file already within the tolerance is left byte-identical.
- **Strategy: **Normalise (the default) re-encodes through FFmpeg loudnorm. Lossless rewrites an MP3's global gain and re-encodes nothing; other formats fall back to the loudnorm re-encode.
- **Album loudness: **Off by default. When on, the folder is measured once as one album, and every track moves by that single gain, so the album's relative levels survive instead of each track being pushed to the target. A track whose peak plus that gain would exceed the True Peak ceiling is limited on its own: only that track's gain is reduced, and the run log names it. An album already within tolerance plans no gain at all and every file is left byte-identical. A Dry Run reports the planned gain per file and writes nothing. Album mode writes through the same encoders as per-file normalisation (MP3, FLAC, OGG, M4A, Opus, WavPack, Speex, WAV and AIFF), so a container with no normalise encoder is refused with the same message a per-file run gives. A lossless WAV or AIFF source keeps its own bit depth, so a 24-bit master is not reduced to 16 bits by the rewrite. Tracks already recorded in the completion registry are not rewritten, so their level will not match a freshly normalised album: use Reset Progress for a whole-album run.

### Reset Progress and BEGIN REFINERY

- **Reset Progress: **Clears the source folder's completion registry so every file can be processed again.
- **BEGIN REFINERY: **Starts the run with the stage selection and settings currently shown.

## Pipeline Stages

When enabled, stages run in this implementation order:

1. Integrity validation: checks existence, readability, file size, magic bytes, decoding, sample rate, duration, and channels.
1. Load: reads original tags and decodes the source audio.
1. Pop & Click Remover: detects and repairs clicks using sensitivity and maximum defect width.
1. Silence Trimming / Fading: removes silence using a dBFS threshold and can apply fade-in and fade-out. In Exact range mode it keeps the millisecond range you enter instead of detecting silence; with Stream copy on, the range is cut with one stream copy and no re-encode.
1. Noise Reduction: optionally removes mains hum and/or broadband noise using its noise profile and gate settings.
1. Parametric EQ: applies the band rack - up to eight low-shelf, high-shelf, peaking, high-pass or low-pass bands - to shape tone before any dynamics processing. A bypassed stage, or one with no bands, leaves the signal untouched.
1. Audio Enhancement: applies the Mild, Moderate, Aggressive, or Custom DSP preset; Custom adds per-effect toggles (reverse, karaoke, phaser, flanger, chorus).
1. Export: writes the processed audio once using format-appropriate encoding settings - only when a stage changed the audio.
1. Normalise: optionally measures loudness and applies the configured target and tolerance - either the LUFS playlist target, or a true-peak target in dBTP. When no earlier stage changed the audio, FFmpeg normalises the source directly in one pass. In album mode the whole folder is measured once, before any file is processed, and every track moves by that single gain.
1. Finish: restores tags, records an undo snapshot, and atomically replaces or creates the output file. A file no stage changed is left byte-identical and reported SKIPPED.

## Dry Run and Output Safety

In Dry Run, each valid file is loaded and the enabled stages run their detection on the decoded audio without writing anything: the click, silence, noise, EQ, and enhancement stages report what they found, and Normalise measures the source and reports the loudness it would apply. No output is written, no temp file is left behind, and no completion record is created. Results include a DryRun stage with RMS, duration, and channel information, plus one entry per stage detection.

A live run that changes nothing is reported SKIPPED and leaves the file byte-identical: no re-encode, tag rewrite, undo snapshot, or replace. A lossy source is therefore not re-encoded just because a stage was enabled. A file that does change is written to a temporary file in the output directory, tagged, and only then atomically moved into the final output path. If a stage or export fails, the temporary file is removed and the original remains intact.

## Completion Registry

The refinery stores successful completion records in _refinery_completed.log in the source folder. Each record contains a SHA-256 hash and filename. A file is skipped only when both its name and pre-processing hash match a recorded completion, so a renamed or modified file is eligible for processing again. Only a run that wrote the file records a completion: a file left unchanged or seen in a Dry Run is not recorded, so a later run with different settings still processes it. Use Reset Progress to clear all records for the selected source folder.

## The Processing Tab

![The Processing tab part-way through a run](images/processing.png)

Processing shows one worker slot per logical CPU (at most eight), progress, and per-file DONE, SKIP, or ERROR entries. Each completed file's entry includes stage messages and metrics. The run cannot be edited from here: the stage selection is fixed when BEGIN REFINERY is pressed.

## The Results Tab

![The Results tab after a finished run](images/results.png)

Results reports processed, succeeded, skipped, errors, and elapsed time. It can compare the original and result audio when a suitable pair exists; Dry Run has no result audio to play. **View Log** opens the run report described below, and **Open Folder** opens the folder the run wrote to.

## Logs and Recovery

The pipeline writes refinery_log.txt in the resolved output directory. It includes per-file stage output - including the EQ stage's band message - and a final total, processed, succeeded, skipped, error, and time summary. This is the run report **View Log** opens. The diagnostic log that configure_logging writes in logs/ is separate, and is for troubleshooting rather than for reviewing a run.

Tag edits are recorded in the suite batch undo system. Keep independent backups before in-place processing even though failures are protected by temporary output and atomic replacement.

## Command Line

The registered command is refine. Examples:

python -m audio_suite_shared.cli_app refine <folder> --dry\
python -m audio_suite_shared.cli_app refine <folder> --output <output> --stages declick,trim,enhance,normalise\
python -m audio_suite_shared.cli_app refine <folder> --stages declick,enhance --preset Mild\
python -m audio_suite_shared.cli_app refine <folder> --reduce-hum --hum-frequency 60 --json\
python -m audio_suite_shared.cli_app refine <folder> --stages trim --trim-mode exact --trim-start 12000 --trim-end 30000\
python -m audio_suite_shared.cli_app refine <folder> --stages eq --eq-band "peaking,1000,2.5,1.0" --eq-band "highpass,40"

CLI options cover output directory, dry run, stages, declick sensitivity and width, trim threshold and fades, the exact trim range (--trim-mode, --trim-start, --trim-end, --trim-duration, --trim-copy/--no-trim-copy), hum and broadband reduction, enhancement preset, the parametric EQ rack (--eq-band, one "kind,freq,gain,q" band per flag, up to eight; giving one implies the eq stage), the enhancement effect flags (--reverse, --karaoke/--no-karaoke, --karaoke-strength, --phaser, --flanger, --chorus), target LUFS, tolerance, true peak, LRA, the normalise strategy (--normalise-mode), the normalise target (--target-mode lufs|peak with --target-peak in dBTP), album mode (--album-mode/--no-album-mode), and JSON output. If --output is omitted, results are written in place.

The eq stage runs after noise reduction and before enhancement, so the preset's compressor and limiter act on the shaped tone. Its band kinds are lowshelf, highshelf, peaking, highpass and lowpass; a highpass or lowpass band is first-order, so it takes no gain and no Q. A band at or above the file's Nyquist frequency is refused rather than moved, and a rack with no bands or with bypass on leaves the signal untouched.

## Master Driver Use

Audio Refinery is the Master Driver's REFINE pipeline. The driver embeds the Refinery Setup controls, passes source and output folders, and supplies inherited Auto Start, Auto End, Clear Logs, and mode values. The driver uses its own batch orchestration; the Refinery's Parallel control is not an independent pipeline switch.

## Troubleshooting

- **No audio files found: **Select a source folder containing supported files directly discoverable by the processor.
- **Integrity check failed: **The file may be empty, unreadable, malformed, undecodable, outside size/duration/sample-rate/channel limits, or have invalid container headers.
- **Files are skipped on a later run: **They match the completion registry by filename and SHA-256. Use Reset Progress when a full rerun is intended.
- **The Parametric EQ is ticked but nothing changes: **Check Bypass in the EQ panel and check that the rack holds at least one band; either one leaves the signal untouched. A band at or above the file's Nyquist frequency is refused by the stage, and the message gives the band and the limit it needed.
- **An EQ band will not enter the rack: **The panel reports the reason: the frequency must be 20 Hz to 20 kHz, the gain within +/-24 dB, the Q within 0.1 to 18, and a high-pass or low-pass band takes no gain and the default Q.
- **The Normalise stage skips a container: **The stage writes MP3, FLAC, OGG, M4A, Opus, WavPack, Speex, WAV, AIFF and AIF, and keeps a lossless source's bit depth. A container with no encoder (for example MP4, WMA or AAC) is reported as a skipped file naming that reason and the formats the stage writes, the file is left untouched, and every other enabled stage still runs. Convert it to one of those formats if you want it normalised.
- **The exact trim refused the run: **Stream copy cannot share a run with a stage that decodes the audio (declick, noise reduction, eq, enhance, normalise). Turn Stream copy off to trim with a re-encode, or disable those stages. A range flag without Exact range mode is refused at the command line rather than silently ignored.
- **The stream copy is a few milliseconds longer or shorter: **That is the frame boundary, not a defect: a copy keeps whole frames, and the run log reports the measured length with the offset. Turn Stream copy off when the exact millisecond matters.
- **Output directory error: **The selected output directory must already exist and be a directory; leave it blank for in-place mode.
- **Normalization behaves unexpectedly: **Remember that the normalizer controls final level when active, and enhancement output gain is suppressed in that case.
- **A stage fails: **Review refinery_log.txt for the stage-specific error. The original source is protected if the final replacement is not reached.

## Safety Recommendations

Run Dry Run first, prefer a separate output folder while tuning stages, and listen to the original/result audition pair. Use in-place mode only with backups. Reset the completion registry when configuration changes require already completed files to be processed again.
