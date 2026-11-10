---
title: Artwork Extractor - User Guide
subtitle: Based on the current Artwork Extractor implementation
---

## Overview

Artwork Extractor writes each file's embedded cover beside it as a sidecar
image — `cover.jpg` or `cover.png`. A player, a phone or a folder view that
ignores embedded pictures then still shows the album's art, and the album folder
gains a cover it did not have to be given.

Nothing else changes: no tag is rewritten and no audio byte is touched. The
picture is read through the suite's one artwork reader and written through the
suite's one sidecar writer, so the window and `audiosuite artwork extract`
cannot disagree about which image a file carries, what its format is, or what
the sidecar should be called.

The window has three tabs: Setup holds the folder, the sidecar options and the
action; Processing shows the run; and Results appears when the run finishes,
with the counts and the run report.

## Quick Start

1. Open Artwork_Extractor.pyw.
1. On the Setup tab, select the folder holding the album or the library.
1. Leave **Sidecar name** at `cover` unless you want a different stem.
1. Tick **Replace an existing sidecar** only if the existing covers should be overwritten.
1. Click **Extract Artwork**.
1. Check the Results tab for the counts, then open the folder to see the sidecars.

A Dry Run writes the report and no sidecar, so you can see exactly what a live
run would write — and what it would keep — before anything on disk changes.

## Setup Tab

- **Source folder:** The folder to read. It is scanned one level deep unless **Also read sub-folders** is ticked.
- **Sidecar name:** The base name of the written file. The extension is chosen from the image's own bytes, so `cover` produces `cover.jpg` for a JPEG and `cover.png` for a PNG. A name carrying a path is refused: a sidecar must land in the album folder it belongs to.
- **Replace an existing sidecar:** Off by default. An existing `cover.jpg` is reported as kept and is left exactly as it is, bytes and timestamp alike — overwriting a curated cover destroys the better copy. Tick this to replace it.
- **Also read sub-folders:** Off by default, because each folder is its own album. Tick it to extract across a library tree; each picture is still written beside the file it came from.
- **Dry Run / Live:** Live writes the sidecars; Dry Run writes only the report.

## What Gets Written

For each supported audio file:

- **A picture the suite can name** is written beside the file as `<name>.jpg` or `<name>.png`. The extension and the reported mime come from the image's own bytes, never from the mime the container claims, so a file storing PNG data under an `image/jpeg` label becomes `cover.png`.
- **A picture the suite cannot name** is reported as an error rather than written under a made-up extension. GIF album art is the common case; the suite does not silently turn it into a JPEG.
- **No embedded picture** is reported as `[NO ART]` and is not a failure. A WAV or AIFF rip whose container holds no artwork scans cleanly.
- **An existing sidecar** is `[KEPT]` unless **Replace an existing sidecar** is ticked, in which case it is `[EXTRACTED]` again.

One file's failure never stops the run: a corrupt file is counted as an error
and the next file is read.

## Results Tab

The Results tab shows the completion heading, the total time, and the summary:

- **Files:** how many supported audio files the run read.
- **Extracted:** sidecars written (a Dry Run counts what it would write).
- **Kept:** existing sidecars left untouched.
- **Without art:** files with no embedded picture.
- **Mode:** Written or Dry run.
- **Errors:** files whose picture could not be read or written.

View Log opens this run's report, and Open Folder opens the scanned folder.

## The Run Report

Every run writes its report beside the files it read:

- `artwork_extractor_sync_log.txt` for a live run.
- `artwork_extractor_dry_run_log.txt` for a dry run.

The report opens with `ARTWORK EXTRACTOR` and the mode, then the source folder,
the sidecar name, whether existing sidecars were replaced and whether
sub-folders were read, one line per file (`[EXTRACTED]`, `[KEPT]`, `[NO ART]`
or `[ERROR]` with its reason), and a `SUMMARY:` block with the file and outcome
counts and the elapsed time. A dry run and a live run write different files, so
the report you open is always the run you started.

## Master Driver and Batch Runs

The window is on the Master Driver's UTIL tab, in the **Tags & Artwork**
section. Tick its card and the batch schedules it as its own step: the step
hands the window the folder the driver is pointed at, the driver's Live/Dry
choice, its **Auto Start** / **Auto End** pair, the sidecar name and the two
switches shown on the card. A batch run therefore starts on its own, writes the
sidecars and the report, and closes.

The step is a leaf: it reads embedded art and writes sidecars, so no other step
has to run before it. If **Replace an existing sidecar** is off — the card's
default — a batch leaves every cover that is already there alone and reports it
as kept.

There is no second command behind the batch step: it is the same window, and
the window writes through the same helpers `audiosuite artwork extract` calls.

## Command Line

The window and the command line do the same job:

```text
audiosuite artwork extract "D:\Music\Album"
audiosuite artwork extract "D:\Music" --recursive --name folder
audiosuite artwork extract "D:\Music\Album" --force --json
```

`audiosuite artwork report` is the read-only companion: it names the files with
no artwork and the ones whose picture is larger than a size or dimension you
consider too big, and writes nothing.

`--json` reports `extracted`, `kept`, `no_art` and `sidecar_name` beside the
shared counters, so a script can tell a written sidecar from a kept one.

## Troubleshooting

- **Results says 0 extracted and every file kept:** a sidecar already exists in the folder and **Replace an existing sidecar** is off. That is the safe default; tick it to replace.
- **A file reports `[NO ART]`:** that container holds no embedded picture. Extract nothing from it, or embed art with Album Art Sync first.
- **A file reports an error about the image format:** the embedded picture is not JPEG or PNG, so the suite will not name a sidecar for it.
- **The sidecar is named `.png` but the tags say JPEG:** the tags are wrong; the bytes are PNG, and the sidecar follows the bytes so a player can decode it.
- **Sub-folders were not read:** **Also read sub-folders** is off. Tick it and run again; nothing already written is disturbed.
