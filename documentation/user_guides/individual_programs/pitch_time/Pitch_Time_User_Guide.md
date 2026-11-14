---
title: Pitch / Time - User Guide
subtitle: Based on the current Pitch / Time implementation
---

## Overview

Pitch / Time changes one thing about every file in a folder: how fast it plays,
or how high it sounds. Tempo mode keeps the pitch and changes the length; Pitch
mode keeps the length and changes the pitch. A rehearsal recording can be
slowed down to learn a part without dropping a fifth, and a song written a
semitone too high can be moved up without becoming shorter.

Both modes are whole-file transforms, so each result is written as a **new
file** beside its source, named for the setting that produced it
(`song_tempo_1.25.wav`, `song_pitch_-2st.wav`). The original is never replaced
and never modified, so a run can be repeated or undone by deleting the file it
wrote.

The window has three tabs: Setup holds the folder, the mode, its value and the
action; Processing shows the run's progress; and Results appears when the run
finishes, with the counters, the run report and the folder it wrote to.

## Quick Start

1. Open Pitch_Time.pyw.
1. On the Setup tab, select the folder holding the files, or use the restored last folder.
1. Choose **Tempo** or **Pitch**.
1. Type the value: a rate such as `1.25` for Tempo, or a shift such as `-2` for Pitch.
1. Click **Process Files**.
1. View the Results tab for the files written and the ones skipped, then open the folder to check the results.

A Dry Run on the same folder reads and measures every file, reports what each
result would be, and writes no audio, so it is the way to check a setting
before a long run.

## Setup Tab

- **Source folder:** The folder holding the files. Every supported audio file directly inside it is processed; subfolders are not searched.
- **Mode:** Tempo changes the length at the same pitch; Pitch changes the pitch at the same length. The mode and the value together are the setting, and a run uses exactly one of them.
- **Tempo rate (factor):** How many times faster the result plays. `1.25` plays a `1.000 s` file in `0.800 s`; `0.8` plays it in `1.250 s`. The accepted range is `0.25` to `4.0`.
- **Pitch shift (semitones):** How far the pitch moves. `12` is an octave up and `-12` an octave down; fractions such as `0.5` are accepted. The accepted range is `-24` to `24`.
- **Dry Run / Live:** Live writes the results; Dry Run reads, measures and reports without writing.

The setting line under the fields shows the setting the run would use, and says
so when it asks for no change. A neutral setting (rate `1.0`, or `0` semitones)
is not an error: the run completes and reports every file as skipped, because
re-encoding a file to produce the same audio would cost a generation of quality
for nothing.

## Processing Tab

The Processing tab reports the run as it happens: a progress bar over the
folder's files, a `Files: done/total | Errors: n` counter, and the name of the
file being read.

## Results Tab

The Results tab shows the completion heading, the total time, and the summary:

- **Files:** how many files the folder held.
- **Written:** how many results were written.
- **Skipped:** how many files were left alone, with the reason in the report.
- **Errors:** how many files could not be read or written.

View Log opens this run's report, and Open Folder opens the folder the results
were written to.

## The Run Report

Every run writes its report beside the files it read:

- `pitch_time_sync_log.txt` for a live run.
- `pitch_time_dry_run_log.txt` for a dry run.

The report opens with `PITCH / TIME REPORT` and the mode, then the folder, the
setting, one line per file with the measured before-and-after length and the
file written, and a `SUMMARY:` block with the counts and the elapsed time. A
file that could not be read carries its reason on its own line; a file that was
left alone says `SKIPPED` and why.

A dry run and a live run write different files, so the report you open is
always the run you started.

## Tempo Mode

Tempo mode uses a phase vocoder to change the length without moving the pitch.
Measured on the suite's acceptance fixture, a `1.000 s` 440 Hz tone at
`rate 1.25` reads back from the written file as `0.800 s` at 440.0 Hz: the
length moves exactly as the factor says, and the pitch does not move at all.

Tempo is the right choice when a part is too fast to play along with, or when a
podcast recording should be listened to faster. Very large factors (below `0.5`
or above `2.0`) stretch the material far enough that the vocoder's artefacts
become audible; the tool accepts them, and the result is worth checking by ear.

## Pitch Mode

Pitch mode shifts the pitch and leaves the length alone. Measured on the same
fixture, `+12` semitones reads back as `1.000 s` at 880.0 Hz: an octave up, with
the duration unchanged.

Pitch is the right choice when a song was recorded in the wrong key for a
singer, or when a part should be practised in another key. Shifting more than a
few semitones moves the formants with the pitch, which is what makes a large
shift sound like a different singer; the tool does not offer a formant-preserving
mode, so a large shift is a deliberate, audible choice.

## What Is Preserved

- **Sample rate:** the result is written at the source's own rate; nothing is resampled.
- **Channel count:** a stereo file stays stereo, and each channel is processed independently, so a wide mix keeps its image.
- **Bit depth:** a 24-bit WAV or FLAC is written at its source depth rather than FFmpeg's 16-bit default.
- **Tags:** title, artist, album, album artist, date, genre, track and disc numbers, and comment are copied onto the new file. WAV and AIFF carry no writable tag block the suite writes, so a WAV result is reported as untagged rather than silently losing its metadata.
- **The source:** never modified. A run reads it and writes a new file beside it.

## Command Line

```text
python -m audio_suite_shared.cli_app pitchtime "D:\Music\Rehearsal" --rate 1.25
python -m audio_suite_shared.cli_app pitchtime "D:\Music\Set" --semitones -2
python -m audio_suite_shared.cli_app pitchtime "D:\Music\Set" --rate 0.9 --dry
python -m audio_suite_shared.cli_app pitchtime "D:\Music\Set" --semitones 3 --json
```

Set exactly one of `--rate` (tempo) or `--semitones` (pitch); a run that names
both, or neither, is a usage error. `--dry` reads and measures without writing,
and `--json` prints the machine-readable summary. The command exits 0 for a
clean run (skips included), 1 when the run completed with errors or could not
start, and 2 for a usage error.

## Troubleshooting

- **Every file is skipped and the report says "no change requested":** the setting asks for no change. Set a rate other than `1.0`, or a number of semitones other than `0`.
- **The rate is refused:** it lies outside `0.25` to `4.0`. Pick a value inside the range; an extreme factor is audible anyway.
- **The shift is refused:** it lies outside `-24` to `24` semitones.
- **The result sounds smeared:** the factor or the shift is large. Try a smaller step, and use Tempo rather than Pitch when the pitch should not move.
- **The tags are missing:** the result is a WAV or AIFF, which carries no writable tag block, or the source had no tags to copy. The report states which case applied.
- **A file is reported as skipped for a read-only container:** the source is an `.ape`, `.mpc` or `.dsf` file, which the suite can read but has no encoder for. Convert it first, then process the result.
