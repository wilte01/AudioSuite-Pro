---
title: Channel Tools - User Guide
subtitle: Based on the current Channel Tools implementation
---

# Channel Tools User Guide

Channel Tools applies one channel rule to a folder of audio files, in place.
It is for the jobs that sit between "the file plays" and "the file is right":
collapsing a stereo mix to mono, duplicating one good channel, flipping a phase
inversion, and widening or narrowing a stereo image.

The rule is applied to each file's samples and written back to the same path, so
the file's tags, sample rate and bit depth survive. Undo is available through
the suite's normal batch undo.

---

## Before You Start

- **Supported files.** Everything in the shared format matrix, except the
  read-only extensions (`.ape`, `.mpc`, `.dsf`), which are reported as skipped
  because they cannot be rewritten in place.
- **Bit depth.** A 24-bit source stays 24-bit; the in-place writer pins the
  source's own PCM depth.
- **Backups.** In-place means exactly that. A dry run first is free and reports
  what each file would become.
- **Mono and stereo sources.** Some rules need two channels and some need one:
  - *Mono rules* accept either layout. A file that is already mono is skipped
    as unchanged.
  - *Dual mono, phase inversion and mid/side and width* need a stereo source;
    a mono file is refused with a named reason rather than guessed at.
  - Files with more than two channels are refused. Downmixing a 5.1 file is a
    mix decision, not a channel utility.

---

## The Window

1. **Folder** — the folder to scan. Subfolders are not scanned.
2. **Rule** — one of the eight rules below.
3. **Width %** — used only by *Stereo width*. `100` leaves the image alone,
   `0` collapses it to mono, `200` doubles the side signal.
4. **Source channel** — used only by *Dual mono*.
5. **Invert** — used only by *Phase inversion*.
6. **Dry run** — report what would change and write no audio.

The rule you chose is saved as a preference, so the next launch starts where you
left off.

---

## The Rules

| Rule | What it computes |
|---|---|
| Mono, arithmetic mean | `0.5 × (L + R)`, the channel sum attenuated 6 dB |
| Mono, sum attenuated 3 dB | `(L + R) / √2`, the same sum attenuated 3 dB |
| Dual mono (left, or right) | copies the named channel to both sides |
| Phase inversion (left, right, or both) | negates the named side's samples |
| Mid/side encode | writes `M = 0.5 × (L + R)` on the left and `S = 0.5 × (L − R)` on the right |
| Mid/side decode | the inverse of encode; `decode(encode(x))` returns `x` |
| Stereo width | `M ± (width/100) × S`, i.e. scales the side signal and decodes |
| Phase inversion (both) on a stereo file | `L' = −L`, `R' = −R` |

### The two mono rules are not interchangeable

They differ by exactly **3.01 dB**, and both are offered because either can be
the right answer:

- The **mean** is the quieter of the two. A signal panned dead centre (`L = R`)
  sums to `2L`, and the mean returns it as `L` — the level one channel had on
  its own.
- The **3 dB** rule is the same sum, attenuated 3 dB instead of 6 dB, so it is
  3.01 dB louder than the mean for a correlated pair *and* for an uncorrelated
  one. Pick it when the mean leaves the result too quiet.

Both rules are measured in the suite's tests on a correlated and an
uncorrelated pair, so the 3.01 dB gap is a locked property rather than a
description.

### Width and clipping

Width is a percentage around unity, from **0** to **400**:

- `0` — side signal removed: both channels become the mid signal (mono content,
  still a stereo file).
- `100` — unchanged. The workflow recognises this and does not rewrite the
  file at all.
- `200` — side signal doubled, a wider image.
- `400` — four times the side signal, the practical maximum.

Widening can push a peak past full scale. When it does, the samples are clamped
to ±1.0 and the file's report line says `clamped to full scale`, so a clipped
result is never silent about it. A dry run reports the same line.

### Mid/side files

Encode writes the mid signal on the left channel and the side signal on the
right, so an encoded file is an ordinary stereo file whose two channels are mid
and side rather than left and right. Decode turns it back. Both steps keep the
file's length, rate and depth, and the round trip is exact.

---

## Dry Run and the Run Report

Every run writes a report beside the files it scanned:

- `channel_tools_dry_run_log.txt` for a dry run;
- `channel_tools_sync_log.txt` for a live run.

The report opens with `CHANNEL TOOLS REPORT`, names the mode, the rule with its
parameters, and one line per file with the resolved path and what happened
(`[FIXED]`, `[SKIP]`, or the error), then a `SUMMARY:` block with the counters
and the run time. The Results tab's **View Log** opens this report — not the
program's diagnostic log, which is written under `logs/` for support.

The summary also records how many files were changed, skipped and failed. A dry
run counts a file it *would* change as `[FOUND]`, so its counters read the same
way as a live run's.

---

## Undo

A live run records its writes in the suite's batch undo. Undo restores the
original bytes of every file the run rewrote, including its tags. A dry run
records nothing.

---

## Command Line

```text
audiosuite channels FOLDER [--operation ID] [--width PERCENT]
                          [--source-channel left|right]
                          [--invert left|right|both]
                          [--dry | --live] [--json]
```

- `FOLDER` — the folder to scan.
- `--operation` — the rule id: `mono_mean`, `mono_minus3db`, `dual_mono`,
  `invert_phase`, `ms_encode`, `ms_decode`, `stereo_width`.
- `--width` — the width percentage, 0 to 400; only used by `stereo_width`.
- `--source-channel` — `left` or `right`; only used by `dual_mono`.
- `--invert` — `left`, `right` or `both`; only used by `invert_phase`.
- `--dry` / `--live` — report only, or write the audio back (default: dry run).
- `--json` — print the run's machine-readable payload instead of the summary.

The same options are offered as `Channel_Tools.pyw` launcher arguments when the
Master Driver runs the tool: `[folder] [mode] [start] [end] --operation …
--width … --source-channel … --invert …`. The Master Driver emits every
parameter, so the child window shows the rule the card showed.

---

## Troubleshooting

**Every file was skipped as already mono.** The chosen mono rule has nothing to
do to a one-channel file; that is a skip, not an error.

**A stereo rule refused the folder.** *Dual mono*, *phase inversion*, *mid/side*
and *width* need two channels. A mono file is refused with
`this rule needs a stereo source`. Use a mono rule, or convert the layout first.

**More than two channels.** Surround files are refused: `expected 1 or 2
channels`. Downmixing surround is a mix decision, so Channel Tools does not
guess.

**The width run changed nothing.** `--width 100` is the identity. The file is
left byte-identical and counted as skipped.

**The widened file sounds clipped.** That is what happened: the side signal
pushed peaks past full scale and they were clamped. The report says so per file.
Use a smaller width, or normalise afterwards.

**A 24-bit file came back at a different depth.** It should not: the in-place
writer pins the source's own PCM codec. Check the report line for the file and
the diagnostic log under `logs/` for the export parameters.

**The file is read-only.** `.ape`, `.mpc` and `.dsf` cannot be rewritten in
place; they are skipped with that reason.

---

## Related Tools

- **Audio Normalizer** — loudness and peak normalisation, for level rather than
  channel layout.
- **Metadata Scrubber** — tag-only edits.
- **Restoration** — repair de-clipping, hum and clicks before widening an image.
