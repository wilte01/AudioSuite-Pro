---
title: Tag Field Updater — User Guide
version: auto
---

## Overview

The Tag Field Updater is a specialised audio metadata tool with two sources of tag values.

The first is the one it shipped with: it recursively scans your music library and normalises slash characters in custom TXXX genre-related tag fields, replacing bare / (forward-slash) characters with "; " (semicolon-space) while preserving values that use the " / " (space-slash-space) pattern. This standardises how multi-genre or genre-artist combinations are delimited in tag metadata across an entire library.

The second is the filename source: instead of reading existing tags, it parses each file's **name** into fields (artist, title, album, track and so on) using an ordered list of patterns, and writes those fields. It is for libraries whose only reliable metadata is in the filenames.

Version 2.2.0 added the filename source. Everything in the slash-replacement sections below describes the original mode and is unchanged.

## Quick Start

\1. Launch Tag_Field_Updater.pyw.\
2. Click 'Browse...' to select your music library directory.\
3. Click 'Start Scanning' to begin processing.\
4. Monitor progress in real-time as files are processed.\
5. Review the completion summary when the scan finishes.

## Supported File Formats

The tool processes the following audio formats:

| Format | Extensions | Tag Type |
| --- | --- | --- |
| MP3 | .mp3 | ID3 (v2.3 / v2.4) |
| FLAC | .flac | Vorbis Comments |
| MP4 / M4A | .mp4, .m4a | iTunes Atoms |
| OGG Vorbis | .ogg | Vorbis Comments |
| Opus | .opus | Vorbis Comments |
| WAV | .wav | ID3 (v2.4) |
| AIFF / AIF | .aiff, .aif | ID3 (v2.4) |
| WMA | .wma | ASF |
|  |  |  |

## Tag Fields Updated

The tool targets specific custom TXXX fields and standard genre-related fields. Only fields that already exist in a file are processed — no new fields are created.

### Custom TXXX Fields

**TXXX/ALBUMARTISTGENRE** — Album Artist Genre

**TXXX/ALBUMGENRE** — Album Genre

**TXXX/ARTISTGENRE** — Artist Genre

On non-ID3 formats these custom fields are stored with the format-equivalent convention: Vorbis comment keys (FLAC, OGG, Opus) and MP4 freeform tags (M4A/MP4, “----:TXXX:<name>”).

### Standard Fields by Format

| Format | Field 1 | Field 2 | Field 3 |
| --- | --- | --- | --- |
| MP3 | TIT1 (Content Group) | TCON (Genre) |  |
| FLAC | CONTENTGROUP | GENRE |  |
| MP4 / M4A | ©grp (Group) | ©gen (Genre) |  |
| OGG | CONTENTGROUP | GENRE |  |
| Opus | CONTENTGROUP | GENRE |  |
| WAV | TIT1 (Content Group) | TCON (Genre) |  |
| AIFF / AIF | TIT1 (Content Group) | TCON (Genre) |  |
| WMA | ContentGroupDescription | Genre |  |
|  |  |  |  |

## Slash Replacement Rules

The tool applies a smart slash-replacement algorithm. The rules are hardcoded and not user-configurable.

### Values That WILL Be Updated

| Before | After |
| --- | --- |
| "Rock/Pop" | "Rock; Pop" |
| "Electronic/Dance" | "Electronic; Dance" |
| "Jazz/Blues/Rock" | "Jazz; Blues; Rock" |
| "Reggae/Dancehall / Ska/Regional Music" | "Reggae; Dancehall / Ska; Regional Music" |

### Values That Will NOT Be Updated

| Value | Reason |
| --- | --- |
| "Rock / Pop" | Preserved — space-slash-space pattern |
| "Single Genre" | No slash present |
| "" | Empty value |
| "Artist / Band / Genre" | All slashes use space-slash-space |

The algorithm also handles mixed patterns. For example, "A/B / C/D" becomes "A; B / C; D" — bare slashes are replaced while space-slash-space delimiters are preserved.

## Tagging from Filenames

In filename mode the tool does not look at the existing tag values at all. It matches each file's name against a list of patterns, tries them in order, and writes the fields the matching pattern captured.

### Patterns

A pattern is literal text with `%field%` placeholders:

| Pattern | Matches |
| --- | --- |
| `%artist% - %title%` | Artist - Title.flac |
| `%track%. %artist% - %title%` | 05. Artist - Title.mp3 |
| `%track% - %artist% - %title%` | 05 - Artist - Title.mp3 |
| `%disc%-%track% %artist% - %title%` | 1-05 Artist - Title.flac |
| `%disc%-%track%. %artist% - %title%` | 1-05. Artist - Title.flac |
| `%track%_%title%` | 08_bassline.wav |

A pattern may capture any of `%artist%`, `%title%`, `%album%`, `%album_artist%`, `%track%`, `%disc%`, `%year%`, `%genre%` and `%comment%` — the same fields the Tag Editor can write. `%track%`, `%disc%` and `%year%` match digits only.

Order matters. The list is tried from the top, and the first pattern that matches wins, so the prefixed forms must come before the bare `%artist% - %title%` form: otherwise `05 - Artist - Title` would be read with the track number as the artist. The GUI's default list is already in that order. When a pattern list is tried by the command line, supply it in the same order you would supply it in the GUI.

### What Makes a Name Match

- The file extension is not part of the match, so `Artist - Pt. 2.mp3` yields the title `Pt. 2`.
- Only the last placeholder is greedy. `AC - DC - Song` under `%artist% - %title%` yields artist `AC` and title `DC - Song`: the first separator separates, and the rest of the name stays in the title.
- A placeholder must match at least one character, so `Artist - ` is not a match with an empty title.
- A file whose name matches no pattern is skipped and left exactly as it is. The tool never guesses a split.
- Surrounding spaces are trimmed, so a stray space is not written into a tag.

### Dry Run Is the Default

Filename mode runs as a **dry run** unless you pass `--live` on the command line, or untick Dry Run in the GUI after enabling the mode. The reason is the failure mode: a wrong split writes tags that look authoritative, and afterwards the file looks tagged. A dry run prints one line per file with the fields it would write, so a mis-parse is visible before it is saved:

```
Filename mode defaults to a dry run; pass --live to write the parsed values.
  [PARSED] 05. Artist - Title.mp3 -> track='05' artist='Artist' title='Title'
             would write: track, artist, title
  [PARSED] 06. Other - Song.mp3 -> track='06' artist='Other' title='Song'
             would write: track, artist
             kept existing: title
```

### Only Fill Blanks

By default (`--only-fill-blanks`, and the GUI checkbox of the same name) a field that already carries a value is left alone; the parsed value only fills empty fields. Use `--overwrite` to replace existing values. A value that already equals the parsed one is never rewritten, so re-running over an already-correct library changes nothing.

### Action Groups

An action group is a saved pattern list plus its write mode, stored in the suite's shared configuration file (`audio_suite_config.json`) under the key `tag_field_updater_action_groups`. Saving a group records your library's naming convention once; loading it by name repeats the run without retyping patterns.

- Save the patterns of the current run: `--save-action-group NAME`.
- Run a saved group: `--action-group NAME`.
- List what is saved: `--list-action-groups`.
- In the GUI, choose a group in the Action group drop-down and click Load, or click Save as... to store the patterns currently in the box.

An explicitly typed `--pattern` (and an explicitly passed `--only-fill-blanks`/`--overwrite`) wins over the group's saved values, so a group is a starting point rather than an override.

### Genre Values Still Follow the Slash Rule

A parsed genre goes through the same slash rule as the original mode, so `Rock/Pop` becomes `Rock; Pop`. Every other field is written exactly as parsed — in particular, an artist such as `AC/DC` is **not** rewritten, because the slash rule exists for genre lists and would mangle a name.

## Using the GUI

Double-click Tag_Field_Updater.pyw to launch the graphical interface. The window is divided into the following sections:

### Music Library Directory

Type or paste a directory path directly, or click Browse... to open a folder chooser dialog. This is the root directory for the recursive scan.

### Dry Run

The 'Dry Run (no changes written)' checkbox controls whether the scan writes tag changes to disk. When checked (the default when launched from the Master Driver in Dry Run mode), the tool computes and reports every rewrite but persists nothing: no file is saved and no undo record is created. Uncheck it to enable live tag writing.

### Tag Fields to Update

A read-only information panel listing all target tag fields and the replacement rules. Refer to this section during a scan to understand which fields are being modified.

### Tag from Filenames

**Tag from filenames: **Switches the run to the filename source described above. Enabling it also ticks Dry Run, so the first run only reports what it parsed; untick Dry Run deliberately when the parse is right.

**Pattern box: **One pattern per line, tried from the top. The box opens with a sensible default list.

**Only fill blank tags: **When ticked (the default), a parsed field never overwrites a tag that already has a value.

**Action group: **Pick a saved pattern set and click Load to fill the box and the write mode, or click Save as... to store the current box under a new name.

### Progress

Shows the name of the file currently being processed, updated in real-time via a background thread.

### Statistics

Three counters displayed during and after the scan:

**Files Processed: **Total number of files scanned

**Files Updated: **Files that had at least one tag field modified

**Errors: **Files that encountered processing errors

### Controls

**Start Scanning: **Begins the recursive scan. The button is disabled while scanning is in progress.

**Stop: **Requests the processor to stop after the current file completes. The scan stops cooperatively between file iterations.

### Completion Summary

When the scan finishes (or is stopped), a summary dialog appears showing Files Processed, Files Updated, Files Skipped, and Errors. The status bar at the bottom of the window changes from "Scanning..." to "Scan Complete".

## Command-Line Interface

The tool can also be run from the command line via the shared AudioSuite CLI group.

### Click CLI (Recommended)

Usage:\
\
    audiosuite tag-update <DIRECTORY> [OPTIONS]\
\
Arguments:\
    DIRECTORY          Path to the music library (required)\
\
Options:\
    --dry / --live   Run without writing changes (default: --live; with a pattern it is --dry unless you pass --live)\
    --json / --text      Output format (default: --text)\
    --no-plugin-tags     Skip tag processors contributed by enabled plugins\
    --pattern TEXT       Filename pattern, repeatable and tried in order\
    --action-group NAME  Load a saved pattern set from the suite config\
    --save-action-group NAME  Save this run's patterns under this name\
    --list-action-groups List the saved action groups and exit\
    --only-fill-blanks / --overwrite  Keep an existing tag (default) or replace it\
    --log-level LEVEL    Logging verbosity: DEBUG, INFO, WARNING, ERROR\

Examples:\
\
    audiosuite tag-update D:\Music --dry --json\
    audiosuite tag-update /home/user/music --log-level DEBUG\
    audiosuite tag-update D:\Music --pattern "%track%. %artist% - %title%" --dry\
    audiosuite tag-update D:\Music --pattern "%artist% - %title%" --live\
    audiosuite tag-update D:\Music --action-group Bandcamp --live\
    audiosuite tag-update D:\Music --list-action-groups

### Module Entry Point

Usage:\
\
    python -m tag_field_updater [--directory PATH]\
\
If --directory is provided, the GUI launches with that path pre-filled and scanning starts immediately.

## Logging

The tool uses Python's standard logging module. Log output is routed to the Audio Suite unified log directory alongside other program logs.

### What Is Logged

**INFO: **Directory scan start; per-tag update details (e.g. "Updated TIT1 in song.mp3: 'Rock/Pop' -> 'Rock; Pop'"); skip reasons; scan completion summary.

**ERROR: **Per-file processing errors with full exception details; directory walk errors; unhandled scan errors.

### Skip Logging

Files are skipped (not errored) for several reasons. The log records the specific reason for each skip:

- **Unsupported format: **File extension not in the supported list (e.g. .txt, .jpg)
- **No ID3 tags: **MP3 file with no ID3 tag header
- **No target tags found: **File has tags but none of the target fields contain a slash

Search the log file for "Skipped file" to see all skip reasons.

## Safety Features

### Minimal Modification

The tool only modifies existing tag fields — it never creates new fields. Only values containing a bare slash are changed. All other tag data, audio content, and file timestamps are preserved.

### Error Resilience

Individual file errors never halt the scan. If a file is corrupted or inaccessible, the error is logged and the tool continues to the next file. The error count is displayed in the statistics and completion summary.

### MP3 Version Preservation

For MP3 files, the tool detects the ID3 version (v2.3 vs v2.4) and preserves it when writing tags. v2.3 files use Latin-1 encoding; v2.4 files use UTF-8. No version migration is performed.

### Cooperative Stop

The Stop button requests the processor to stop after the current file completes. This ensures no file is left in a partially-written state. The scan cannot be interrupted mid-file.

## Troubleshooting

No files processed: Verify the directory contains supported audio formats (.mp3, .flac, .mp4, .m4a, .ogg, .opus, .wav, .aiff, .aif, .wma). Check directory permissions.

Files updated: 0: In the original mode this is normal if your files already use the semicolon-space delimiter or if none of the target fields contain a bare slash. In filename mode it also means every parsed value already matched the stored tag, or that no file name matched a pattern — the run prints a `[NO MATCH]` line for each of those. Check the log file for skip details.

A tag was written to the wrong field: a pattern matched a file it should not have. Run again with the pattern list narrowed, or with the specific pattern moved below a more specific one, and check the `[PARSED]` lines a dry run prints before writing. A wrong split is fixed by re-running with `--overwrite` once the patterns are right.

Permission errors: Ensure you have read/write access to the music directory. On Windows, try running as administrator if files are read-only.

Large libraries: Processing is threaded so the UI remains responsive. SSD drives provide faster file access than HDDs. Network drives may be slower.

## Technical Details

### Dependencies

- **Python 3.11+: **Core runtime
- **Mutagen: **Audio file tag reading and writing
- **Tkinter: **GUI framework (included with Python)

### Architecture

The tool is structured as a clean Python package with separated concerns:

- **core/mapping_engine.py: **Tag field mappings, supported extensions, and slash-replacement logic
- **core/transformation_rules.py: **Per-format processing functions (Mutagen I/O)
- **core/filename_patterns.py: **The filename pattern parser (pure: name in, fields out)
- **core/filename_tags.py: **Writes parsed fields through the shared editable-tag API
- **core/processor.py: **TagProcessor orchestrating directory scanning and file dispatch, and selecting the source
- **utils/config.py: **Action groups in the shared `audio_suite_config.json`
- **ui/app.py: **Tkinter GUI application
- **cli.py: **Click CLI command registered under the audiosuite group

### Performance

- **Memory: **Low — files are processed individually
- **CPU: **Moderate during tag reading/writing
- **Disk I/O: **Primary bottleneck — files are opened, read, and rewritten
- **Scalability: **Tested with libraries of 10,000+ files
