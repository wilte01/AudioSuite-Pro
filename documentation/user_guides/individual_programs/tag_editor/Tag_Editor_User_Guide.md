---
title: Tag Editor — User Guide
version: auto
---

## Overview

The Tag Editor is an interactive grid for common audio metadata fields. It recursively loads supported audio files, displays their tag values in an editable table, and applies validated single-field edits, bulk transformations, and CSV imports to the selected files. Every live write is recorded as one undoable batch, so an entire apply run can be restored from Undo Tag Edits.

## Quick Start

\1. Launch Tag_Editor.pyw.\
2. Click Browse & Scan and choose your music library folder.\
3. Click LOAD & SCAN LIBRARY to fill the grid.\
4. Select one or more file rows.\
5. Choose a field, type a value, and click Apply to Selection.\
6. Keep the Mode at Dry Run to preview changes, or choose Live Update to write tags.\
7. Use Export CSV... / Import CSV... to work on the grid in a spreadsheet.

## The Window

The editor is a three-tab window, like the rest of the suite.

| Tab | What it shows |
| --- | --- |
| 1. Setup | The Run Controls strip (source folder, Browse & Scan, Mode, Auto Start, Auto End), the single-field and bulk edit controls, the CSV buttons and the Library Grid. |
| 2. Processing | The progress bar, the per-file line list and the running *Processed / Skipped / Errors* counters for the run in progress. |
| 3. Results | The finished run's summary, its total time, and the View Log and Open Folder buttons. |

The **Run Controls** strip is the suite's standard one:

- **Source Music Directory** is the folder every run reads. Browse & Scan opens the suite's folder dialog at the current folder and remembers the choice for the next launch.
- **Mode** is Dry Run or Live Update. It applies to every apply run (Apply to Selection, Apply Bulk, Import CSV), never to the load walk.
- **Auto Start** and **Auto End** are honoured when the Master Driver passes them; **Clear Logs** and **Parallel Run** are shown as the driver set them and are executed by the driver.
- The LOAD & SCAN LIBRARY button at the bottom of the tab starts the load walk. **Stop** ends it after the file being read, so no file is left half-loaded.

## Supported File Formats

The Tag Editor uses the AudioSuite shared tag handlers and supports the suite's canonical audio extensions:

| Format | Extensions | Tag Convention |
| --- | --- | --- |
| MP3 | .mp3 | ID3v2 |
| FLAC | .flac | Vorbis comments |
| Ogg Vorbis | .ogg | Vorbis comments |
| MPEG-4 Audio | .m4a, .mp4 | iTunes atoms |
| Opus | .opus | Vorbis comments |
| WAV | .wav | Embedded ID3v2 |
| AIFF | .aiff, .aif | Embedded ID3v2 |
|  |  |  |
|  |  |  |

## Editable Fields

| Field | Validation | Clear Behaviour |
| --- | --- | --- |
| Title | Free-form text up to 4096 characters | Removes the title tag |
| Artist | Free-form text up to 4096 characters | Removes the artist tag |
| Album | Free-form text up to 4096 characters | Removes the album tag |
| Album Artist | Free-form text up to 4096 characters | Removes the album-artist tag |
| Track | 'N' or 'N/M', numbers 1–9999 | Removes the track tag |
| Year | Four-digit year or ISO date | Removes the year/date tag |
| Genre | Free-form text up to 4096 characters | Removes the genre tag |
| Comment | Multiline text up to 4096 characters | Removes the comment tag |

## Using the Grid

The Library Grid sits at the bottom of the Setup tab. The File column shows each filename; the remaining columns show the current editable values. Rows can be selected individually or with the keyboard and mouse (Ctrl and Shift work as usual). Selecting one row loads its current value into the edit form.

Apply to Selection sends the same field edit to every highlighted file. Files whose current value already matches the requested value are reported as unchanged and are not rewritten.

Every apply run — Apply to Selection, Apply Bulk and Import CSV — moves to the **Processing** tab while it runs, then reports on the **Results** tab: how many files were in the batch, how many changed, how many already matched, and how many failed. The grid keeps the values the run wrote, so the next edit works from the current state.

## Bulk Operations

The Bulk Operations panel applies a transformation to every selected row in one undoable apply run.

| Operation | Effect |
| --- | --- |
| Set Blank | Stores an empty string in the selected field without removing the tag. |
| Clear Field | Removes the selected field from each highlighted file. |
| Swap Fields | Exchanges the selected field with the second field on every row. |
| Case Convert | Converts the selected field to Title Case, Upper Case, or Lower Case. |
| Normalize Slashes (TXXX Rule) | Replaces bare '/' separators with '; ' while preserving ' / ', matching the Tag Field Updater rule. |

Swap Fields uses both field selectors and ignores rows where the two values are already equal. Normalize Slashes is limited to text fields so track totals and dates cannot be corrupted.

## CSV Import and Export

Import CSV... applies a batch of per-file edits to the loaded library. The CSV needs a file column (file, filename, or path) plus one column per editable field. Column headers may use the field key (album_artist) or the display label (Album Artist). The exported layout is:

| file | title | album_artist | year |
| --- | --- | --- | --- |
| Artist/01 - One.mp3 | One | Various | 1999 |
| Artist/02 - Two.mp3 | Two | Various | 1999 |
| Artist/03 - Three.mp3 | Three | Various | 2001 |

File values may be absolute or relative to the loaded library folder, so a spreadsheet exported by Export CSV... can be edited and re-imported directly. Export CSV... writes the loaded grid as UTF-8 CSV with one row per file, using an empty cell for a tag that is not set.

Every file value must point inside the loaded library folder. A value that climbs out with a parent-directory reference (..), names a folder elsewhere on the machine, or uses a drive-relative path is reported as an error for that row and skipped, so a pasted spreadsheet can never retag files outside the folder you loaded. Import CSV... also refuses to run until a library folder is selected, because that folder is what file values are resolved against.

Empty cells mean leave unchanged, so re-importing an exported grid never clears a tag. Unrecognised columns are ignored; the Results tab names them under *Ignored columns*. Rows naming a missing or unsupported file, and cells that fail validation, are reported per row and do not stop the remaining rows from applying. Import reads the strip's Mode and records one undo batch for the whole file.

## Dry Run and Live Update

**Mode** on the Run Controls strip selects Dry Run or Live Update, and Dry Run is the default. A dry run reads current values and reports the proposed old/new comparison without writing any tag. Choose Live Update to write changes; the strip is the only place that decides, and every apply run reads it when it starts. When launched from the Master Driver, the driver's utility mode selection sets the strip's initial value.

## Run Reports

Each run writes a report into the folder it read, in the same form the suite's other tools use: a header naming the run and its mode, one line per file (or per edit), and a SUMMARY block. The report is plain text and View Log on the Results tab opens it.

| Run | Report file |
| --- | --- |
| LOAD & SCAN LIBRARY | tag_editor_scan_log.txt |
| Apply run, Mode = Dry Run | tag_editor_dry_run_log.txt |
| Apply run, Mode = Live Update | tag_editor_sync_log.txt |

A load walk lists what it read, one `[READ]` line per audio file with the tag values it found, and an `[ERROR]` line for a file whose tags could not be read. An apply run lists `[WOULD WRITE]` (dry run) or `[WRITTEN]` per changed field with its old and new value, `[UNCHANGED]` where the value already matched, and `[FAILED]` with the reason where a write was refused. CSV rows that could not be planned are listed as `[SKIPPED]` lines.

View Log opens the report of the most recent run. The diagnostic log for the program itself is `logs/tag_editor.log`; it records the same run at a lower level of detail and is not what View Log opens.

## Undo

Every live Apply to Selection, Apply Bulk, or Import CSV run creates one tag_editor undo batch. Open Undo_Tag_Edits.pyw and revert that batch to restore every file changed by the run. Files that had no tags before the run are restored to their tagless state.

## Command Line

The headless command edits one field in one audio file, or imports a CSV of per-file edits for a library directory. It defaults to live mode; add --dry to preview the change without writing.

audiosuite tag-edit PATH --field title --value "New Title"

audiosuite tag-edit PATH --field comment --clear --dry

audiosuite tag-edit /Music --csv /Music/edits.csv --dry

With --csv, PATH is the library directory used to resolve relative file values, and it is also the boundary those values may not escape; --field, --value, and --clear cannot be combined with it. Use --json for machine-readable output, including the parsed row count, planned edits, per-row errors, and ignored columns. The command exits with a nonzero status when validation, a row, or a tag write fails.

## Master Driver

The Tag Editor card appears on the Utilities tab. Selecting the card and starting the selected utility opens the editor with the driver's music directory preloaded, and the Run Controls strip is locked to what the driver passed so a batch cannot be rewritten mid-run. The driver's Dry Run / Live Update mode sets the Mode value; if the driver has **Auto Start** on, the load walk starts by itself; with **Auto End** on the window closes when that run finishes. Clear Logs and Parallel Run remain driver-owned controls.
