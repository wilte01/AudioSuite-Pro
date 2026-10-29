---
title: Metadata Scrubber - User Guide
subtitle: Based on the current Metadata Scrubber implementation
---

## Overview

Metadata Scrubber removes metadata from supported audio files and restores only the fields you choose to keep. Artist, album, and title are always preserved as essential identity tags. The scrubber can also preserve selected custom fields, lyrics, Album Artist, and embedded artwork.

Dry Run reports what would be scrubbed without changing files. Live Update performs a tag wipe followed by restoration and records tag-edit snapshots for undo support.

## Supported Files

The scrubber works with fourteen containers: MP3, FLAC, OGG, Opus, M4A, MP4, WAV, AIFF, AIF, WavPack (.wv), Monkey's Audio (.ape), Musepack (.mpc), Speex (.spx), and DSD (.dsf). Those are the only files it lists, samples, or processes.

WMA is the one format the suite can read that the scrubber still refuses: mutagen has no ASF tag handler at all, so the file could not be read or rewritten. A folder holding only WMA files reports "No supported audio files found" rather than an error per file.

The five containers added in 2.1.7 keep their own tag model through the wipe-and-restore cycle: WavPack, Monkey's Audio and Musepack preserve raw APEv2 items (so multi-value text stays multi-value and cover art stays binary), Speex preserves Vorbis comments like OGG does, and DSF preserves ID3 frames like WAV does. A scrub is metadata-only: the audio samples are not re-encoded.

The GUI discovers custom tags by sampling up to 100 supported audio files in the selected directory. Processing then scans the supported files in that directory.

- **Always preserved: **Artist, album, and title, using format-specific tag representations.
- **Optional lyrics: **MP3 USLT/SYLT, Vorbis lyrics/syncedlyrics (including OGG Speex), APEv2 lyrics/syncedlyrics, and the M4A/MP4 lyrics atom where supported.
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

The GUI scans up to 100 supported audio files for custom tag descriptions: TXXX descriptions for ID3-based formats (MP3, WAV, AIFF, AIF, DSF), Vorbis comment keys for FLAC/OGG/Opus/Speex, APEv2 item keys for WavPack/Monkey's Audio/Musepack, and MP4 freeform tag names for M4A/MP4. It excludes known system or technical descriptions containing terms such as ReplayGain, BPM, Tempo, Initial Key, MusicBrainz, AcousticID, Barcode, MediaType, or OriginalDate. This keeps the checklist focused on user-defined metadata rather than fields managed by other suite tools.

If no custom tags are found, the checklist displays No custom tags found, while the always-preserved identity tags and optional standard controls remain available.

## Scrubbing Workflow

1. Load the file with its format-specific mutagen handler.
1. Verify that tags exist; files without tags report NO TAGS.
1. Collect essential tags and the selected optional/custom fields.
1. Record a tag-edit undo snapshot and delete all tags in Live Update.
1. Save the wiped file.
1. Reload it, recreate tags if needed, restore the preserved fields, and save the result.

The operation keeps audio content unchanged; it changes metadata containers and fields. The processing uses one worker thread per logical CPU (at most eight) and reports each file independently.

## Dry Run and Live Update

- **Dry Run: **Reports Would scrub metadata for each discovered file and performs no tag deletion or restoration. It does not update saved tag preferences.
- **Live Update: **Wipes and restores metadata according to the selected preservation settings, then saves tag preferences for the selected custom fields.
- **No tags: **Files without tags are reported as errors rather than modified.
- **Unreadable file: **Files that cannot be opened are reported as UNREADABLE.
- **Corrupt tags: **A failed wipe is reported as CORRUPT TAGS; a failed restoration is reported as WRITE FAILED.

## Processing and Results

Processing shows one worker slot per logical CPU (at most eight), processed/skipped/error counts, and per-file status messages. Results reports total files, successfully processed files, skipped files, errors, and elapsed time. The results tab can open the log and source folder.

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
