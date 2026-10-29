---
title: Tag Editor — User Guide
version: auto
---

## Overview

The Tag Editor is an interactive grid for common audio metadata fields. It recursively loads supported audio files, displays their tag values in an editable table, and applies validated single-field edits, bulk transformations, and CSV imports to the selected files. Every live write is recorded as one undoable batch, so an entire apply run can be restored from Undo Tag Edits.

## Quick Start

\1. Launch Tag_Editor.pyw.\
2. Click Browse... and choose your music library folder.\
3. Click Load Grid.\
4. Select one or more file rows.\
5. Choose a field, type a value, and click Apply to Selection.\
6. Keep Dry Run checked to preview changes, or clear it to write tags.\
7. Use Export CSV... / Import CSV... to work on the grid in a spreadsheet.

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

The File column shows each filename; the remaining columns show the current editable values. Rows can be selected individually or with the keyboard and mouse. Selecting one row loads its current value into the edit form.

Apply to Selection sends the same field edit to every highlighted file. Files whose current value already matches the requested value are reported as unchanged and are not rewritten.

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

Empty cells mean leave unchanged, so re-importing an exported grid never clears a tag. Unrecognised columns are ignored and listed in the status bar. Rows naming a missing or unsupported file, and cells that fail validation, are reported per row and do not stop the remaining rows from applying. Import honours the Dry Run state and records one undo batch for the whole file.

## Dry Run and Live Update

Dry Run is selected by default. A dry run reads current values and reports the proposed old/new comparison, but never writes tags. Clear Dry Run to write changes. When launched from the Master Driver, the utility mode selection chooses the initial Dry Run / Live Update state.

## Undo

Every live Apply to Selection, Apply Bulk, or Import CSV run creates one tag_editor undo batch. Open Undo_Tag_Edits.pyw and revert that batch to restore every file changed by the run. Files that had no tags before the run are restored to their tagless state.

## Command Line

The headless command edits one field in one audio file, or imports a CSV of per-file edits for a library directory. It defaults to live mode; add --dry to preview the change without writing.

audiosuite tag-edit PATH --field title --value "New Title"

audiosuite tag-edit PATH --field comment --clear --dry

audiosuite tag-edit /Music --csv /Music/edits.csv --dry

With --csv, PATH is the library directory used to resolve relative file values, and it is also the boundary those values may not escape; --field, --value, and --clear cannot be combined with it. Use --json for machine-readable output, including the parsed row count, planned edits, per-row errors, and ignored columns. The command exits with a nonzero status when validation, a row, or a tag write fails.

## Master Driver

The Tag Editor card appears on the Utilities tab. Selecting the card and starting the selected utility opens the editor with the driver's music directory preloaded. The driver's Dry Run / Live Update mode is passed to the editor; Clear Logs and Parallel Run remain driver-owned controls.
