---
title: Album Art Sync - User Guide
subtitle: Based on the current Album Art Sync implementation
---

## Overview

Album Art Sync finds album artwork online from the album and artist metadata already present in a music directory, lets you review or automatically select a candidate, and embeds the selected image into every supported audio file in that directory. In Live Update mode it also writes a folder.jpg copy.

The tool is designed for album-level synchronization: it reads artist, album, and Album Artist metadata from the first supported file and uses that lookup identity for the directory. Make sure the first file has accurate tags before starting a search.

## Source Lookup Order

Sources are queried in this order, stopping when a usable image is selected:

1. Cover Art Archive: queried first. When the first file carries a MusicBrainz release ID (written by the Audio Fingerprinter's identifier write), the exact release is looked up; otherwise the release-group IDs are used.
1. MusicBrainz: identifies the release and supplies the IDs needed by Cover Art Archive and Fanart.tv.
1. Fanart.tv: queried when MusicBrainz returns release or recording-group IDs.
1. Deezer: used as the next artwork source.
1. iTunes Store: used as the final fallback source.

The search logs the sources queried and records the source ultimately selected. Network requests use the suite request timeout, which is 10 seconds by default.

## Candidate Filtering and Ranking

- **Minimum dimensions: **Candidates smaller than the configured minimum on either axis are rejected. The default is 500 pixels.
- **Album matching: **Deezer and iTunes candidates must pass fuzzy album-name matching. The default threshold is 0.85.
- **Trusted source: **Cover Art Archive and Fanart.tv candidates skip album-name filtering because the MusicBrainz identity has already been used.
- **Quality order: **Candidates that pass guardrails are ranked by album match score first, then image area. The picker displays the ranked list.
- **Audit trail: **The log records candidate dimensions, match results, rejections, and the selected source.

## Quick Start: GUI

1. Open Album_Art_Synch.pyw from the AudioSuite-Pro folder.
1. On Setup, select the directory containing the album's MP3, FLAC, OGG, M4A, MP4, or Opus files.
1. Choose Dry Run for a preview or Live Update to write tags.
1. Choose an embedded resolution: 600, 800, 1000, or 1200 pixels.
1. Decide whether to purge hidden system artwork files.
1. Click BEGIN ALBUM ART SYNCH.
1. In interactive mode, review candidates with the previous and next buttons, then ACCEPT or REJECT.
1. Review the Results tab and art_sync_log.txt after completion.

## GUI Tabs

### Setup

Setup contains the directory control, run mode, embedded resolution, purge option, presets, and the start button. The application validates that the directory exists and contains supported audio files before searching. The last directory can be restored through shared suite configuration.

- **Embedded Res: **Select 600, 800, 1000, or 1200 pixels. The default is 800.
- **Purge Hidden System Art: **When enabled, removes albumartsmall.jpg, folder.jpg, cover.jpg, and files beginning with albumart_ before writing artwork.
- **Presets: **Save execution mode, embedded resolution, and purge choice under a name, load a saved preset, or delete a preset.
- **Auto Start / Auto End: **Auto Start begins a driven launch automatically. Auto End closes the window after successful completion, cancellation, or an error after a short delay.
- **Clear Logs / Parallel: **These values mirror Master Driver orchestration state and are display-only for this tool's own processing logic.

### Processing

Processing shows the current search or embedding status, a progress bar, a live log, and Cancel. Cancellation is checked during lookup and while embedding files. A cancellation request stops further work and marks the operation as cancelled in the Results view.

### Results

Results reports completion, cancellation, no artwork found, or partial success. View Log opens art_sync_log.txt in the source directory. Open Folder opens the source directory because synchronization modifies files in place.

## Interactive Artwork Picker

When the GUI receives candidates, it opens a modal picker on the main UI thread. The picker shows a preview, source, candidate title, dimensions, and position in the ranked list. Use < and > to browse. ACCEPT returns the displayed image to the synchronizer; REJECT or closing the picker returns no image and prevents an artwork update.

## Dry Run and Live Update

- **Dry Run: **Performs metadata lookup, filtering, ranking, and image selection, then logs what would be embedded without changing audio files or writing folder.jpg.
- **Live Update: **Embeds the selected artwork into every supported file and writes folder.jpg at the configured folder-image size of 1000 pixels.
- **In-place operation: **The selected directory's files are updated in place. Keep a backup of important files before a live run.
- **Undo support: **The operation participates in the suite batch undo mechanism for recorded tag edits. This does not replace independent backups.

## Artwork Output

The applier downloads the selected image, creates a folder.jpg copy at up to 1000 x 1000 pixels, and prepares embedded JPEG bytes at the selected embedded size. It then calls the shared artwork tag helper for each supported file. A file-level embedding warning is logged while processing continues with other files; a fatal preparation error produces a failed result.

The supported directory extensions are MP3, FLAC, OGG, M4A, MP4, and Opus. The source lookup identity is taken from the first supported file, while the selected image is applied across all supported files in the directory.

## Configuration

Fanart.tv credentials are loaded from album_art_config.json next to the tool and are encrypted through the suite KeyManager. The configuration loader can create a default template when the file is missing. Do not place credentials in the guide, source code, or command line.

- **Request timeout: **10 seconds by default.
- **Minimum candidate dimension: **500 pixels by default; CLI range is 200 through 2000.
- **Album match threshold: **0.85 by default; CLI range is greater than 0.0 through 1.0.
- **Folder image size: **1000 pixels.

## Command Line

The registered command is album-art. It automatically selects the top-ranked candidate and is useful for unattended runs. Examples:

python -m audio_suite_shared.cli_app album-art <folder> --dry\
python -m audio_suite_shared.cli_app album-art <folder> --embed-size 1000\
python -m audio_suite_shared.cli_app album-art <folder> --no-purge --min-dimension 700\
python -m audio_suite_shared.cli_app album-art <folder> --match-threshold 0.90 --json

CLI options include --embed-size, --purge/--no-purge, --min-dimension, --match-threshold, --dry, and --json. The CLI does not show the interactive picker; it downloads the highest-ranked candidate automatically.

## Master Driver Use

From the Master Driver, open ENRICH and select Album Art Sync. The driver passes the shared directory, mode, start and end behavior, embedded size, purge choice, minimum dimension, and match threshold through the launch handshake. A driven launch can auto-start, and the child window shows inherited orchestration values.

## Troubleshooting

- **No supported audio files found: **Check the selected directory and confirm it contains MP3, FLAC, OGG, M4A, MP4, or Opus files.
- **No artwork found: **The APIs returned no usable candidates, every candidate failed the dimension or album-match guardrails, or the picker was rejected.
- **Wrong album candidates: **Use accurate Album and Album Artist tags, increase the match threshold, or reject the candidate in the picker.
- **Fanart.tv is unavailable: **The resolver falls through to Deezer and then iTunes. Check encrypted Fanart configuration and network access if the fallback sources are insufficient.
- **Partial success: **Review art_sync_log.txt for per-file embedding warnings and check whether files are writable.
- **Purge removed an image: **Disable Purge Hidden System Art when existing folder.jpg, cover.jpg, albumartsmall.jpg, or albumart_ files must be retained.

## Logs and Recovery

The GUI writes art_sync_log.txt in the source directory after a non-cancelled run. Logs include the lookup identity, queried sources, candidate audit, selected source, purge activity, embedding progress, warnings, and final status. Use the suite's Undo Tag Edits workflow for available tag snapshots, and maintain an independent backup for reliable recovery.
