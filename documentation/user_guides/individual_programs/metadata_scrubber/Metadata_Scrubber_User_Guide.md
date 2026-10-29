---
title: Metadata Scrubber - User Guide
subtitle: Based on the current Metadata Scrubber implementation
---

## Overview

Metadata Scrubber removes metadata from supported audio files and restores only the fields you choose to keep. Artist, album, and title are always preserved as essential identity tags. The scrubber can also preserve selected custom fields, lyrics, Album Artist, and embedded artwork.

Dry Run reports what would be scrubbed without changing files. Live Update performs a tag wipe followed by restoration and records tag-edit snapshots for undo support.

## Supported Files

The scrubber works with nine containers: MP3, FLAC, OGG, Opus, M4A, MP4, WAV, AIFF, and AIF. Those are the only files it lists, samples, or processes.

Other formats the suite can convert are deliberately not offered here: WavPack (.wv), Monkey's Audio (.ape), Musepack (.mpc), Speex (.spx), DSD (.dsf), and WMA. WMA is excluded because mutagen has no ASF tag handler at all. The remaining five can be decoded for conversion, but the scrubber wipes a file's tags and then restores individual tag frames, and no frame-level tag handler exists for those containers yet — listing them would mean reporting a valid file as unreadable. A folder holding only such files reports "No supported audio files found" rather than an error per file.

The GUI discovers custom tags by sampling up to 100 supported audio files in the selected directory. Processing then scans the supported files in that directory.

- **Always preserved: **Artist, album, and title, using format-specific tag representations.
- **Optional lyrics: **MP3 USLT/SYLT, Vorbis lyrics/syncedlyrics, and the M4A/MP4 lyrics atom where supported.
- **Optional Album Artist: **MP3 TPE2 and corresponding Album Artist fields in supported containers.
- **Optional artwork: **MP3 APIC, Vorbis metadata block picture, and MP4/M4A cover art.
- **Custom tags: **Discovered custom fields are selectable and restored through the shared format-aware tag handler.

## Quick Start

1. Open Metadata_Scrubber.pyw.
1. Use Browse & Scan to select the directory.
1. Review the discovered custom tags and choose which to preserve.
1. Set Lyrics, Album Artist, and Embedded Art preservation as needed.
1. Leave Dry Run selected for the first pass.
1. Click BEGIN SCRUBBING and review Processing and Results.
1. Run again in Live Update only after confirming the preservation choices.

## Setup

Setup contains the directory/run-controls panel, presets, preservation toggles, custom-tag checklist, and start button. Browse & Scan both selects the folder and discovers custom tags. Previously preserved custom-tag choices are marked saved and automatically ticked when they are found again.

- **Preserve Lyrics (USLT/SYLT): **Keeps lyrics frames or equivalent format-specific lyrics fields.
- **Preserve Album Artist (TPE2): **Keeps the Album Artist field; enabled by default.
- **Preserve Embedded Art (APIC): **Keeps embedded cover art; enabled by default.
- **Custom tag checklist: **Select discovered TXXX descriptions or equivalent custom fields to restore after scrubbing.
- **Presets: **Save and restore mode plus the three preservation toggles. Dynamic custom-tag selections are persisted separately as last-used preferences after Live Update.

## Tag Discovery

The GUI scans up to 100 supported audio files for custom tag descriptions: TXXX descriptions for ID3-based formats (MP3, WAV, AIFF, AIF), Vorbis comment keys for FLAC/OGG/Opus, and MP4 freeform tag names for M4A/MP4. It excludes known system or technical descriptions containing terms such as ReplayGain, BPM, Tempo, Initial Key, MusicBrainz, AcousticID, Barcode, MediaType, or OriginalDate. This keeps the checklist focused on user-defined metadata rather than fields managed by other suite tools.

If no custom tags are found, the checklist displays No custom tags found, while the always-preserved identity tags and optional standard controls remain available.

## Scrubbing Workflow

1. Load the file with its format-specific mutagen handler.
1. Verify that tags exist; files without tags report NO TAGS.
1. Collect essential tags and the selected optional/custom fields.
1. Record a tag-edit undo snapshot and delete all tags in Live Update.
1. Save the wiped file.
1. Reload it, recreate tags if needed, restore the preserved fields, and save the result.

The operation keeps audio content unchanged; it changes metadata containers and fields. The processing uses four worker threads and reports each file independently.

## Dry Run and Live Update

- **Dry Run: **Reports Would scrub metadata for each discovered file and performs no tag deletion or restoration. It does not update saved tag preferences.
- **Live Update: **Wipes and restores metadata according to the selected preservation settings, then saves tag preferences for the selected custom fields.
- **No tags: **Files without tags are reported as errors rather than modified.
- **Unreadable file: **Files that cannot be opened are reported as UNREADABLE.
- **Corrupt tags: **A failed wipe is reported as CORRUPT TAGS; a failed restoration is reported as WRITE FAILED.

## Processing and Results

Processing shows four worker slots, processed/skipped/error counts, and per-file status messages. Results reports total files, successfully processed files, skipped files, errors, and elapsed time. The results tab can open the log and source folder.

## Logs

- **Dry Run log: **metadata_dry_run_log.txt in the selected directory.
- **Live log: **metadata_scrubbing_log.txt in the selected directory.
- **Contents: **Mode, preservation choices, per-file statuses, preserved-tag counts, errors, totals, and elapsed time.

## Command Line

The registered command is scrub. Examples:

python -m audio_suite_shared.cli_app scrub <folder> --dry\
python -m audio_suite_shared.cli_app scrub <folder> --live\
python -m audio_suite_shared.cli_app scrub <folder> --no-preserve-lyrics --json

Options include --preserve-lyrics/--no-preserve-lyrics, --preserve-album-artist/--no-preserve-album-artist, --preserve-embedded-art/--no-preserve-embedded-art, the shared dry-run/live option, and --json. All three preservation options default to enabled.

## Master Driver Use

From the Master Driver, open ENRICH and select Metadata Scrubber. The driver passes the directory, mode, start/end behavior, preservation flags, and orchestration state through the launch handshake. A driven launch can auto-start and locks inherited run controls.

## Troubleshooting

- **No custom tags found: **The scanner samples up to 100 supported audio files and filters known system tags. Custom fields in files beyond the sample limit may not appear in the dynamic checklist.
- **Metadata disappeared: **Confirm the intended fields were checked and that the run was Live Update. Unchecked custom tags are intentionally removed.
- **Artwork was removed: **Enable Preserve Embedded Art before a live run; APIC/cover-art preservation is independent of custom-tag selection.
- **Lyrics were removed: **Enable Preserve Lyrics (USLT/SYLT) before a live run.
- **A file errors: **Review the per-file status and metadata_scrubbing_log.txt for unreadable files, missing tags, corrupt tags, or restoration failures.
- **Preferences look stale: **Custom-tag preferences are updated after Live Update, not Dry Run. New tags are unticked until reviewed.

## Safety and Recovery

Run Dry Run first and verify the preservation checklist. Live Update rewrites metadata in place. Keep backups of important files and use the suite's Undo Tag Edits workflow for available tag-edit snapshots.
