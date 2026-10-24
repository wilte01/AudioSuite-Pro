---
title: Genre Sync - User Guide
subtitle: Based on the current Genre Sync implementation
---

## Overview

Genre Sync derives the standard Genre field from custom genre metadata already stored in each audio file. It reads the file's TITLEGENRE, ARTISTGENRE, ALBUMGENRE, ALBUMARTISTGENRE, and Album Artist values, applies a deterministic priority tree, and can write the selected genre plus a derived-source marker.

The tool processes supported audio files recursively with four worker slots. Dry Run reports the decisions without changing tags; Live Update writes changes in place.

## Supported Input

Genre Sync uses the shared Audio Suite supported-extension list, including MP3, FLAC, OGG, M4A, Opus, WAV, and AIFF variants. The selected directory must contain at least one supported audio file.

## Quick Start

1. Open Genre_Sync.pyw.
1. Select the music directory.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN GENRE UPDATE.
1. Review the selected source and skipped/error entries in Processing and Results.
1. Run again in Live Update when the derived Genre values are acceptable.

## Setup

Setup contains the directory picker, mode, shared run controls, presets, a summary of the resolution rules, and the start button. The last-used directory is restored from shared suite configuration.

- **Dry Run: **Analyze and report the selected genre without writing metadata.
- **Live Update: **Write the standard Genre field and the derived marker when a usable source is resolved.
- **Presets: **Save, load, and delete the run mode through shared suite preset storage.
- **Auto Start / Auto End: **A Master Driver launch can start automatically and close the window after completion when configured.
- **Clear Logs / Parallel: **These values mirror Master Driver orchestration state; the tool's own worker processing remains managed by its processor.

## Genre Resolution Rules

For each file, the resolver applies these rules in order:

1. TITLEGENRE always wins when it contains a non-blank value.
1. For an Album Artist equal to Various Artists, use ARTISTGENRE first, then ALBUMGENRE.
1. For all other albums, use ALBUMGENRE first, then ALBUMARTISTGENRE.
1. If no usable field exists, report No genre fields available and do not update the file.

The resolver treats ordinary whitespace and several Unicode blank characters as empty. A field that exists but contains only visual whitespace cannot become the selected genre.

## Tags Written

On a Live Update when a source is resolved, Genre Sync writes the selected value to the format-appropriate standard Genre field, such as TCON for MP3, and writes the derived source marker through the shared tag helper. The marker identifies the winning source:

- **Title selection: **Derived value Title.
- **Artist selection for Various Artists: **Derived value Artist.
- **Album selection: **Derived value Album.
- **Album Artist selection: **Derived value Album Artist.
- **Undo: **Live tag writes are recorded in the suite's batch undo context.

## Status Categories

- **UPDATED: **Live Update changed the genre fields, or the corresponding dry-run entry says Would set.
- **DRY RUN: **A usable source was selected and the file would be updated in Live Update.
- **SKIPPED: **The current standard Genre already equals the resolved genre.
- **NO GENRE: **No usable custom genre field matched the rules.
- **ERROR: **Tag reading, resolution, or writing raised an error for the file.

## Processing and Results

Processing shows four worker slots, a progress bar, processed count, updated count, already-correct skips, no-genre count, errors, and per-file decision text. Work is retried through the shared processor recovery path. Results reports the same counts and elapsed time, then opens the Results tab when complete.

## Logs

- **Dry Run log: **genre_dry_run_log.txt in the selected directory.
- **Live log: **genre_sync_log.txt in the selected directory.
- **Sections: **Mode, updated or would-update files, already-correct skips, files with no genre fields, errors, and a summary with counts and elapsed time.

## Command Line

The registered command is genre-sync. Examples:

python -m audio_suite_shared.cli_app genre-sync <folder> --dry\
python -m audio_suite_shared.cli_app genre-sync <folder> --live\
python -m audio_suite_shared.cli_app genre-sync <folder> --json

The CLI accepts the shared directory, dry-run/live, and JSON options. It validates that the supplied path exists and is a directory. Text output reports files, updated, skipped, no-genre, errors, and elapsed time.

## Master Driver Use

From the Master Driver, open ENRICH and select Genre Sync. The driver passes the directory, Dry Run or Live Update mode, Auto Start, Auto End, and display-only orchestration state. A driven launch can auto-start and locks inherited controls in the child window.

## Troubleshooting

- **No supported audio files found: **Select a directory containing supported audio files.
- **No genre fields: **Check TITLEGENRE, ARTISTGENRE, ALBUMGENRE, and ALBUMARTISTGENRE values and confirm they are not blank or whitespace-only.
- **A file is already correct: **SKIPPED is expected when the standard Genre already equals the resolved value.
- **Unexpected source selected: **Check the Album Artist value: Various Artists changes precedence from Album Genre to Artist Genre.
- **Tags did not change: **Confirm Live Update was selected. Dry Run never writes metadata.
- **A file errors: **Review the per-file message and genre_sync_log.txt for tag-reader or writer details.

## Safety and Recovery

Run Dry Run first and review which field wins for each file. Live Update modifies tags in place. Keep backups of important files and use the suite's Undo Tag Edits workflow for available snapshots.
