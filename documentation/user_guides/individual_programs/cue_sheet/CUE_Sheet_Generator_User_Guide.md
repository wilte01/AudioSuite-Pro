---
title: CUE Sheet Generator - User Guide
subtitle: Based on the current CUE Sheet Generator implementation
---

## Overview

CUE Sheet Generator writes one `.cue` sheet describing a folder of track files.
A downloaded album, a set ripped to separate tracks, a folder you hand-named:
the sheet lists every file as its own `FILE` block with the track's number,
title and performer, so a player that reads CUE files shows the album's
structure instead of a list of loose tracks.

The sheet is the same text `audiosuite cue generate` writes, built by the same
code, so the window and the command line cannot describe one folder two ways.
Nothing is measured or guessed: a folder of separate files needs no durations,
because each track's `INDEX 01` is `00:00:00` inside its own `FILE` block. The
single-image sheet, where offsets are cumulative, is written by the Track
Splitter for the image it split.

The window has three tabs: Setup holds the folder, the sheet target, the album
fields and the action; Processing shows the run; and Results appears when the
run finishes, with the track count, the sheet path and the run report.

## Quick Start

1. Open CUE_Sheet_Generator.pyw.
1. On the Setup tab, select the folder holding the tracks.
1. Optionally name the sheet in **Sheet file**, and fill **Album title** and **Album artist**. Empty writes `album.cue` beside the tracks and leaves the album fields out.
1. Check the **Tracks** line: it is the number of files the sheet will describe.
1. Click **Write CUE Sheet**.
1. Check the Results tab for the track count and the sheet path, then open the folder.

A Dry Run writes the report and leaves the sheet alone, so it shows exactly what
the sheet would say before it replaces an existing one.

## Setup Tab

- **Source folder:** The folder holding the tracks, read one level deep. Sub-folders are not walked, because each folder is its own album.
- **Sheet file:** Where the sheet is written. Empty means `album.cue` in the source folder. Browse opens a save dialog whose default name is an existing sheet at that path, so a re-run replaces the same file.
- **Album title:** The sheet-level `TITLE`. Empty leaves the line out.
- **Album artist:** The sheet-level `PERFORMER`. Empty leaves the line out.
- **Tracks:** How many supported audio files the sheet will describe. A folder with none cannot be described, and the window says so.
- **Dry Run / Live:** Live writes the sheet; Dry Run writes only the report.

## Track Numbers, Titles and Performers

Each `FILE` block carries one `TRACK`, numbered in this order:

1. **The file's track tag**, when it has one. The number is read through the suite's shared tag reader, so every container's field is resolved the same way the Tag Editor reads it. A `3/12` value gives `3`.
1. **A leading `NN - ` or `NN.` filename prefix**, when the tag has no number.
1. **The file's position in the folder**, sorted naturally so `...9.flac` comes before `...10.flac`.

The title is the file's title tag, then the filename without its numeric prefix.
The performer is the file's artist tag; a file with no tags at all gets an empty
performer rather than a fabricated "Unknown".

Two files that claim the same track number are **refused**: the run names both
files and writes nothing. Renumbering them silently would produce a sheet whose
tracks no longer match the album, and the sheet exists to describe the album.

## Results Tab

The Results tab shows the completion heading, the total time, and the summary:

- **Tracks:** how many files the sheet describes.
- **Sheet:** the path written (or, for a dry run, the path it would have written).
- **Mode:** Written or Dry run.
- **Errors:** the run's error count.

View Log opens this run's report, and Open Folder opens the folder holding the
sheet.

## The Run Report

Every run writes its report beside the tracks it read:

- `cue_sheet_sync_log.txt` for a live run.
- `cue_sheet_dry_run_log.txt` for a dry run.

The report opens with `CUE SHEET GENERATOR` and the mode, then the source
folder, the sheet path, the album title and artist, one line per track file,
the sheet's full text, and a `SUMMARY:` block with the track count, how many
sheets were written, the error count and the elapsed time. A dry run and a live
run write different files, so the report you open is always the run you started.

## Master Driver and Batch Runs

The window is on the Master Driver's UTIL tab, in the **Convert & Import**
section. Tick its card and the driver's batch schedules it as its own step: the
step hands the window the folder the driver is pointed at, the driver's
Live/Dry choice and its **Auto Start** / **Auto End** pair, so a batch run
starts on its own, writes `album.cue` and the run report, then closes. The
sheet target and the album fields are left at their window defaults, so a batch
writes `album.cue` beside the tracks with no album-level title or artist. The
step is a leaf: it reads tags and writes one sheet, so no other step has to run
before it and nothing it writes feeds another tool.

There is no second command behind the batch step: it is the same window, and
the window writes the sheet through the same builder `audiosuite cue generate`
calls, so a scheduled run and a manual run cannot describe one folder two ways.

## Command Line

The window and the command line write the same sheet:

```text
audiosuite cue generate "D:\Music\Album"
audiosuite cue generate "D:\Music\Album" --title "Greatest Hits" --artist "The Band"
audiosuite cue generate "D:\Music\Album" -o "D:\Music\Album\album.cue"
audiosuite cue generate "D:\Music\Album" --json
```

`cue generate` reads a folder or a single audio file and writes `album.cue`
beside it by default. `--json` reports the written path, the sheet's track count
and the album title alongside the shared counters. A duplicate track number is a
run failure with the message the window would show, and no sheet is written.

## Troubleshooting

- **The Tracks line says 0:** the folder holds no supported audio files, or it is the wrong folder. Pick the folder that contains the tracks.
- **"Track number 03 is claimed by both ...":** two files carry the same number, from tags or from their names. Fix the tag or rename one file; the sheet is refused rather than renumbered.
- **The sheet lists a filename as a title:** that file has no title tag, so the name is the title. Fill the tag with the Tag Editor and run again.
- **The player shows one long track:** the player is reading the folder as an image. A folder sheet is one `FILE` per track by design; for a single-image CUE, use the Track Splitter's sheet over the image it split.
- **A sheet I edited was replaced:** a live run writes the target path. Name a different Sheet file, or run a Dry Run first and compare its report.
