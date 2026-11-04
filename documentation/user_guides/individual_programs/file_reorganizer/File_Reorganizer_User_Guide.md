---
title: File Reorganizer - User Guide
subtitle: Based on the current File Reorganizer implementation
---

## Overview

File Reorganizer scans supported audio files recursively, reads their metadata, evaluates a user-defined path template, and copies or moves each file into the resolved destination hierarchy. It has separate templates for named album artists and Various Artists releases, selected from the album artist tag.

The window has three tabs. Setup holds the source directory and its run controls, the presets, the destination, the action choice and both pattern templates. Processing shows the planned or completed paths with a progress bar and the four counters. Results appears when a run finishes and offers the log and the destination folder.

The workflow is preview-first: Mode is set to Dry Run on launch and shows the planned paths without performing file operations.

## Quick Start

1. Open File_Reorganizer.pyw.
1. On the Setup tab, set the Source Music Directory and the Destination Directory.
1. Choose Copy or Move and leave Mode on Dry Run.
1. Click Preview and review the planned paths on the Processing tab.
1. Switch Mode to Live Update and click Execute only after checking the planned paths.
1. Open the Results tab to see the final counters; View Log opens this tool's log and Open Folder opens the destination.

## Setup and Actions

- **Source Music Directory: **Root folder to scan recursively. It sits in the Run Controls strip at the top of the Setup tab; Browse records the folder as the suite-wide last-used directory, and the last suite directory may be restored on startup.
- **Mode: **Dry Run (the default) evaluates every path without writing anything; Live Update performs the selected copy or move. The Preview button always runs a dry scan, whatever the Mode says.
- **Auto Start / Auto End: **Mirror the Master Driver's orchestration options. Auto Start is driver-only, and a launch from the driver locks the strip so the inherited values stay visible but cannot be changed inside the tool.
- **Destination Directory: **Base directory prepended to each resolved pattern path. It is required by the CLI and selected in the GUI.
- **Copy: **Copies files with shutil.copy2, preserving file metadata such as timestamps and attributes.
- **Move: **Moves files with shutil.move. Across volumes this may behave as copy followed by delete.
- **Preview: **Runs the scan and populates the planned destination paths on the Processing tab. A successful preview enables Execute.
- **Execute: **Performs the copy or move, or a dry run if Mode is still Dry Run. It is disabled until a preview has finished.
- **Stop: **Requests that the active scan stop at the next file boundary.
- **Presets: **Save and restore the source and destination paths, the action, the Mode (dry-run state) and both pattern templates through shared suite configuration.

## File Selection and Tags

The engine processes files whose extensions are in the shared supported-audio list. It reads the following lowercase pattern fields:

- %albumartist% - album artist, falling back to artist for some uses
- %artist% - track artist
- %album% - album title
- %title% - track title, with the filename stem as a fallback when raw tags are absent
- %tracknumber% and %discnumber% - track/disc positions
- %date%, %originaldate%, and %originalyear% - release/original dates
- %genre%, %bpm%, and %key% - common descriptive tags

A file with neither a usable album nor title is skipped. A missing or unreadable tag is generally represented as an empty string, allowing the pattern's fallback logic to decide the path.

## Specific Artists and Various Artists

The album artist is compared case-insensitively with the suite's Various Artists aliases. Matching files use the Various Artists template; all other files use the Specific Artists template.

The default Specific Artists structure is:

Specific Artists/<first artist character>/<artist, prefix swapped> /<year> - <album>/<disc>-<track> <title>

The default Various Artists structure is:

Various Artists/<year> - <album>/<disc>-<track> <artist> - <title>

The default templates use original year first, then original date, then release date, with 0000 as the final fallback. They also swap a leading A, An, or The to the end for sorting, zero-pad track numbers, and use Unknown Album when the album tag is empty.

## Pattern Language

Patterns use a foobar2000-like syntax:

- **%tagname%: **Expands a tag or previously assigned variable.
- **$set(name, expression): **Assigns an intermediate variable.
- **$if(condition, then, else): **Chooses a branch; empty and 0 are false.
- **$if2(a, b, ...): **Returns the first non-empty argument.
- **$eq(a, b): **Returns 1 when strings are equal, otherwise 0.
- **$swapprefix(value, A, An, The): **Moves a matching leading prefix to the end, such as The Beatles to Beatles, The.
- **$left(value, count): **Returns the first count characters.
- **$num(value, digits): **Zero-pads a numeric value, such as 1 to 01.
- **$replace(value, old, new): **Replaces text.
- **$lower(value) / $upper(value): **Changes case.

## Path Safety

After evaluation, the engine removes control characters, replaces path-illegal characters such as < > : " | ? * with underscores, normalizes separators, strips leading/trailing separators, trims components, and drops empty components. If the resolved path has no extension, the source file's extension is appended.

A pattern that resolves to a `.` or `..` path component, a drive-qualified value such as `C:\Music`, or a UNC value such as `\\server\share` is refused, not silently rewritten: the file is counted in Errors, reported as a pattern error, and nothing is written. The same refusal applies if a destination would resolve outside the chosen destination directory, so a tag value can never place a file outside the tree you selected. An absolute-looking tag value such as `/etc/passwd` is re-rooted inside the destination instead.

## Dry Run, Copy, and Move

- **Dry Run: **Logs source-to-target plans and increments scan/processed statistics without touching files. It is the default Mode.
- **Copy: **Creates destination directories as needed and copies the source file with metadata preservation.
- **Move: **Creates destination directories as needed and moves the source file.
- **Undo: **Live copy and move operations are recorded in the suite file-reorganization undo context.
- **Conflict behavior: **A copy or move whose destination path already exists is skipped and reported in the Skipped counter; the existing file is never overwritten. Review the planned paths and resolve conflicts before Execute.

## Progress and Statistics

The Processing tab reports the current file in its status line, a progress bar that fills as scanned files are processed, and four counters: Scanned, Processed, Skipped, and Errors. Each resolved destination path, skip notice or pattern error is appended to the path list below the counters. Skips include files with no usable album/title tags, files whose pattern resolves to an empty path, and files whose destination path already exists. Pattern parsing failures and operating-system/value errors increment Errors.

## Results

When an execute run finishes, the window switches to the Results tab. It shows the completion heading, the total time, the four final counters, a View Log button for this tool's log and an Open Folder button for the destination directory. A preview leaves the window on the Processing tab so its planned paths stay visible.

## Command Line

The registered command is reorganize. Examples:

python -m audio_suite_shared.cli_app reorganize <source> --output-dir <destination> --dry\
python -m audio_suite_shared.cli_app reorganize <source> --output-dir <destination> --action copy\
python -m audio_suite_shared.cli_app reorganize <source> --output-dir <destination> --action move --live\
python -m audio_suite_shared.cli_app reorganize <source> --output-dir <destination> --specific-pattern <pattern> --json

CLI options include --output-dir, --action copy|move, --dry/--live, --specific-pattern, --various-pattern, and --json. When action or patterns are omitted, saved shared configuration values are used. The command defaults to Dry Run.

## Master Driver Use

From the Master Driver, open UTIL and select Tag-Based File Reorganizer. The utility is standalone and opens its own workflow in the same three tabs. The selected directory, the Mode and the Auto Start / Auto End options are passed through the driver launch context and appear in the Run Controls strip, which is locked while the tool is driven; use the reorganizer's Destination, Action, Pattern Templates, Preview, Execute and Stop controls for the operation.

## Troubleshooting

- **Files are skipped: **Confirm that the file has usable album/title metadata, that the pattern produces a non-empty path, and that the destination file does not already exist.
- **The path is unexpected: **Preview, inspect the source tags on the Processing tab, and check whether Various Artists classification or prefix swapping selected a different branch.
- **Pattern error: **Check parentheses, commas, function names, tag references, and numeric arguments. The file is counted as an error and the scan continues.
- **Destination is empty: **Select a valid destination directory in the GUI or pass --output-dir on the CLI.
- **Files did not move: **Mode may still be Dry Run. Switch it to Live Update only after reviewing the planned paths.
- **A move needs recovery: **Use the suite's Undo Tag Edits/file-reorganization workflow when a snapshot is available, and retain backups for important libraries.

## Configuration and Recovery

Destination, action, Mode and pattern settings are persisted in the shared audio_suite_config.json. The tool can migrate an older reorganizer_config.json once, then remove the legacy file. Live operations are recorded in the suite's file-reorganization batch context.
