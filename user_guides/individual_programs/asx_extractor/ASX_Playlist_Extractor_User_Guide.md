---
title: ASX Playlist Extractor - User Guide
subtitle: Based on the current ASX Playlist Extractor implementation
---

## Overview

ASX Playlist Extractor processes Windows Media ASX playlist files in a selected directory. It reads each playlist's first usable ref link, resolves the linked audio file, verifies that the target exists, and optionally copies that audio file into the selected directory. In permanent mode it then removes the ASX playlist, leaving the audio file as the extracted result.

The tool is deliberately staged: it does not remove an ASX playlist when its audio copy fails. This keeps the playlist available when an extraction cannot be completed.

## Input and Output

- **Input: **Top-level files whose extension is .asx, matched case-insensitively.
- **Playlist reference: **The first <ref> XML element with a non-empty href attribute.
- **Audio result: **The referenced audio file is copied into the selected directory with metadata preserved by copy2.
- **Playlist cleanup: **In permanent mode, the ASX file is sent to the system Trash when send2trash is available; otherwise it is deleted permanently.
- **Log: **Extraction_Log.txt is written in the selected directory with failures, successful extractions, mode, date, and summary counts.

## Quick Start

1. Open ASX_Playlist_Extractor.pyw from the AudioSuite-Pro folder.
1. On Setup, select the directory containing the ASX playlists.
1. Choose Dry Run (Simulated) first to inspect playlist parsing and targets.
1. Click START EXTRACTION.
1. Review the Processing steps and then open the extraction log from Results.
1. Use Execute Extraction (Permanent) only after confirming the dry-run results.

## GUI Tabs

### Setup

Setup contains the target directory, action mode, shared run controls, presets, and the start button. The last-used directory can be restored from shared suite configuration. A Master Driver launch can provide the directory and inherited control values through the launcher handshake.

- **Dry Run (Simulated): **Parses and verifies playlists and writes the report, but does not copy audio or remove ASX files.
- **Execute Extraction (Permanent): **Copies successful audio targets into the selected directory and removes only playlists whose copies and cleanup succeed.
- **Presets: **Save, load, and delete the current action mode through the shared suite preset storage.
- **Auto Start: **Begins extraction automatically after a driven launch when enabled.
- **Auto End: **Closes the window about two seconds after the run completes when enabled.
- **Clear Logs / Parallel: **Mirror Master Driver orchestration state and are display-only for this extractor's processing path.

### Processing

The Processing tab presents six stages: scanning for ASX files, parsing ASX contents, verifying source audio and paths, copying audio, removing or trashing original ASX files, and finalizing the priority error log. Active stages show an arrow; completed stages show a check.

Each playlist is classified as a success or failure during parsing and verification. Permanent extraction may reclassify a parsed success as a failure if copying or ASX removal fails.

### Results

Results provides View Log and Open Folder. View Log becomes available after Extraction_Log.txt is written. Open Folder opens the selected source/output directory because extracted audio is copied there.

## ASX Parsing Rules

The parser reads playlist text as XML using ElementTree. An XML declaration is removed before parsing when present, which accommodates declarations whose stated encoding does not match the actual text. The first <ref> with an href is used. Playlists that declare a DTD or entity (DOCTYPE/ENTITY) are rejected outright to block XML entity-expansion attacks.

- **Relative href: **Resolved relative to the directory containing the ASX file.
- **Absolute href: **Resolved as an absolute filesystem path.
- **Alternate-extension fallback: **If the referenced audio file is missing, the parser tries the first existing same-stem sibling file in any of the nine suite supported audio extensions (.mp3, .flac, .ogg, .m4a, .mp4, .opus, .wav, .aiff, .aif), preferring the shared SUPPORTED_EXTENSIONS order.
- **Malformed XML: **Reported as INVALID XML IN ASX.
- **DTD/entity payload: **Reported as DTD-BEARING ASX REJECTED before any parsing occurs.
- **No reference: **Reported as NO REF LINK IN ASX.
- **Missing target: **Reported as FILE NOT FOUND or DIRECTORY NOT FOUND depending on the resolved path.

## Dry Run and Permanent Extraction

- **Dry Run: **Runs scan, parse, and verification, records what was found, writes the report, and leaves both source audio and ASX playlists unchanged.
- **Permanent mode: **Copies each verified audio file with metadata preserved, then removes the corresponding ASX only after the copy succeeds.
- **Copy failure: **The ASX is retained and the item is recorded as COPY FAILED.
- **Removal failure: **The audio copy remains, but the item is recorded as AUDIO COPIED BUT ASX REMOVAL FAILED.
- **Undo support: **Successful copies are recorded in the suite file-reorganization undo context. Keep independent backups when permanently changing a library.

## Extraction Log

Extraction_Log.txt contains the processed directory, timestamp, selected mode, a failures section, a successful extractions section, and a final count summary. Failure records include the ASX filename, reason, and attempted audio path. Successful records include the ASX filename and resolved audio path.

## Command Line

The registered command is asx-extract. Examples:

python -m audio_suite_shared.cli_app asx-extract <folder> --dry\
python -m audio_suite_shared.cli_app asx-extract <folder>\
python -m audio_suite_shared.cli_app asx-extract <folder> --json

The CLI accepts --dry and --json. Without --dry, extraction is permanent. The JSON option prints the structured result; normal text output reports total ASX files, extracted successes, failures, and errors. The directory must exist and be a directory.

## Master Driver Use

From the Master Driver, open UTIL and select ASX Playlist Extractor. The driver passes the shared directory, action mode, Auto Start, Auto End, Clear Logs, and Parallel handshake values. The child window displays inherited controls and can start automatically when requested.

## Troubleshooting

- **No ASX files found: **Confirm that the selected directory contains top-level .asx files; subdirectories are not scanned.
- **Invalid XML: **Open the ASX file and check that it is well-formed XML with a usable <ref href="..."> element.
- **File not found: **Check the href path relative to the playlist. The parser also tries the first same-stem sibling in a supported audio extension when applicable.
- **Copy failed: **Check destination permissions, file locks, available space, and whether the source audio is readable.
- **ASX remains after extraction: **The audio copy or playlist removal failed; review the failure entry in Extraction_Log.txt.
- **The run did not change files: **Confirm that Dry Run (Simulated) was not selected.

## Safety Recommendations

Always run Dry Run first and inspect the log. Permanent mode changes the directory by copying audio and removing ASX playlists. Although send2trash normally provides a recovery path for removed playlists, do not rely on Trash or undo records as a substitute for a backup.
