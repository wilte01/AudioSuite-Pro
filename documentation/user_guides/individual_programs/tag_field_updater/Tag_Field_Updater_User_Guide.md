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
2. Click 'Browse & Scan' to select your music library directory.\
3. Choose the Mode (Dry Run first, then Live Update when the report looks right).\
4. Click 'START SCANNING' to begin processing.\
5. Monitor progress in real-time as files are processed.\
6. Review the completion summary when the scan finishes.

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

Filename mode runs as a **dry run** unless you pass `--live` on the command line, or choose **Live Update** in the GUI's Mode box after enabling the mode. The reason is the failure mode: a wrong split writes tags that look authoritative, and afterwards the file looks tagged. A dry run prints one line per file with the fields it would write, so a mis-parse is visible before it is saved:

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

Double-click Tag_Field_Updater.pyw to launch the graphical interface. The window has the same three tabs as every other tool in the suite — **1. Setup**, **2. Processing** and **3. Results** — with a **Help** button at the top right that opens this guide, and it grows with the window so a deep library path and a long pattern list are read in place rather than cut off.

### 1. Setup tab

The tab opens with the suite's **Run Controls** strip, in the same order and with the same labels every other tool uses:

**Source Music Directory: **Type or paste a directory path directly, or click **Browse & Scan** to open a folder chooser dialog. This is the root directory for the recursive scan, and the entry widens with the window. The chooser opens in the folder already in the box, and the folder you pick is remembered for the next launch.

**Mode: **Choose **Dry Run** or **Live Update**. Dry Run computes and reports every rewrite but persists nothing: no file is saved and no undo record is created. The window opens in Dry Run, so writing tags is a deliberate switch to Live Update.

**Auto Start / Auto End: **Mirror the Master Driver's own options. Auto Start makes a driven launch begin immediately instead of waiting for the start button; Auto End closes the window two seconds after the scan finishes, which is what lets an unattended batch move on.

**Clear Logs / Parallel (driver only): **Shown so the run's orchestration is visible, but greyed out: the Master Driver performs both, never this tool.

When Tag Field Updater is launched from the Master Driver, the source, Mode and Browse controls are locked. The driver owns that run — the values you see are exactly the arguments it passed — and the start button re-runs the same source and mode.

**Tag from Filenames: **Switches the run to the filename source described above. Enabling it also ticks Dry Run, so the first run only reports what it parsed; untick Dry Run deliberately when the parse is right.

**Pattern box: **One pattern per line, tried from the top. The box opens with a sensible default list, scrolls when the list is longer than the panel, and grows with the window.

**Only fill blank tags: **When ticked (the default), a parsed field never overwrites a tag that already has a value.

**Action group: **Pick a saved pattern set and click Load to fill the box and the write mode, or click Save as... to store the current box under a new name.

Below the pattern controls the window names the fields it writes — the custom TXXX fields ALBUMARTISTGENRE, ALBUMGENRE and ARTISTGENRE, plus the standard TIT1 (content group) and TCON (genre) — and points at this guide for the replacement rules, which are documented in full in *Tag Fields Updated* and *Slash Replacement Rules* above instead of being repeated in the window.

**START SCANNING: **Begins the recursive scan and switches to the Processing tab. The button is disabled while scanning is in progress.

**Stop: **Requests the processor to stop after the current file completes. The scan stops cooperatively between file iterations.

### 2. Processing tab

While a scan runs this tab shows the file being processed in the status line, a progress bar sized to the number of files the scan will visit (every file in the folder, since the walk reads each one to decide whether it is supported), the shared `Processed / Skipped / Errors` count, and one line per file as it is handled, updated in real-time from the background thread.

### 3. Results tab

When the scan finishes (or is stopped) the window switches to this tab, which shows the completion heading (**Scan Complete!** in a dry run, **Tag Update Complete!** in Live Update), the total time, and a summary of the files read, skipped and failed, plus how many of the audio files were updated — so a run that skipped or could not update files says so on screen.

**View Log** opens the run report the scan wrote into the folder it scanned: `tag_field_updater_dry_run_log.txt` for a dry run and `tag_field_updater_sync_log.txt` for a live one. The report carries the header (mode, directory, source and patterns), one line per file (`[UPDATED]`, `[WOULD UPDATE]`, `[UNCHANGED]`, `[SKIP]`, `[NO MATCH]` or `[ERROR]`), and the same summary the tab shows. **Open Folder** opens the folder that was scanned.

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

Two files record a run, and they answer different questions:

- The **run report** (`tag_field_updater_dry_run_log.txt` / `tag_field_updater_sync_log.txt`) is written into the scanned folder. It is the per-file record of what the run did, and it is what **View Log** opens. Each run overwrites the previous report in that folder, exactly as every other tool in the suite does.
- **`logs/tag_field_updater.log`** is this program's diagnostic log, written by the Audio Suite unified logging setup. It carries the same detail for support purposes plus tracebacks for failures.

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

Files updated: 0: In the original mode this is normal if your files already use the semicolon-space delimiter or if none of the target fields contain a bare slash. In filename mode it also means every parsed value already matched the stored tag, or that no file name matched a pattern — the run prints a `[NO MATCH]` line for each of those. Check the run report (**View Log**) for skip details.

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
- **core/processor.py: **TagProcessor orchestrating directory scanning and file dispatch, selecting the source, and `run_scan`, the GUI's entry point that publishes the progress/completion/error callbacks and builds the run report
- **utils/config.py: **Action groups in the shared `audio_suite_config.json`
- **ui/app.py: **Tkinter GUI application, on the suite's shared analysis/tag scaffold
- **ui/setup_tab.py, ui/processing_tab.py, ui/results_tab.py: **The three tabs, built from the suite's shared widgets
- **utils/cli_args.py: **The Master Driver's launcher handshake
- **cli.py: **Click CLI command registered under the audiosuite group

### Performance

- **Memory: **Low — files are processed individually
- **CPU: **Moderate during tag reading/writing
- **Disk I/O: **Primary bottleneck — files are opened, read, and rewritten
- **Scalability: **Tested with libraries of 10,000+ files
