---
title: CD Ripper - User Guide
subtitle: Based on the current CD Ripper implementation
---

## Overview

CD Ripper reads an audio CD, looks up release metadata, extracts selected tracks as raw CDDA sectors, and encodes them with FFmpeg into FLAC, MP3, OGG, M4A, WAV, or Opus files. The GUI separates disc setup and metadata review from the actual rip progress and final results.

On Windows, extraction uses Win32 SCSI Pass-Through with the MMC READ CD command. Administrator rights are required for raw CD audio extraction.

## Requirements and Platform

- **Operating system: **CD extraction is implemented for Windows. The app reports that ripping is unsupported on other operating systems.
- **Drive: **A detected optical CD drive with an inserted audio CD.
- **FFmpeg: **Required for probing and encoding. The app prefers a bundled core ffmpeg executable when present, otherwise it uses ffmpeg from PATH.
- **Disc metadata: **libdiscid and musicbrainzngs are optional but provide the most accurate disc ID and MusicBrainz lookup. Without libdiscid, ffprobe supplies a TOC fallback.
- **Windows library: **The launcher attempts to preload discid.dll when it exists beside the launcher.

## System Requirements

This tool requires ffmpeg and ffprobe to be installed and on PATH. ffmpeg decodes and encodes the audio formats the suite reads and writes; ffprobe reads stream metadata (duration, codec, bitrate) for analysis tools. The suite shows a startup warning naming any missing binary and how to install it.

- Windows: winget install Gyan.FFmpeg
- macOS:   brew install ffmpeg
- Linux:   sudo apt install ffmpeg

## Quick Start

1. Insert an audio CD and open CD_Ripper.pyw.
1. Refresh drives and select the optical drive.
1. Click Read Disc to read the table of contents and query MusicBrainz.
1. Review or edit album and track metadata.
1. Choose an output directory, format, quality, and optional CUE sheet.
1. Click PROCEED TO RIP, then START RIPPING.
1. Monitor each track and review the Results tab when complete.

## Setup & Lookup

The first tab is disabled from proceeding until a disc has been read. It contains drive selection, disc reading, C2 diagnostics, MusicBrainz release candidates, album metadata, editable track rows, output configuration, and format quality settings.

- **CD Drive: **Refresh the drive list, select the optical drive, and insert the audio CD before reading.
- **Read Disc: **Reads the TOC in a worker thread, populates track numbers and durations, and attempts MusicBrainz lookup.
- **Detect Read Offset: **Measures this drive's read offset against the AccurateRip database using the inserted CD and stores it for the drive; every future rip applies the correction automatically. This reads the whole disc twice, so expect a few minutes. Do it once per drive, with a disc that is present in the AccurateRip database and the network reachable. On failure nothing is stored and the status line explains why.
- **MusicBrainz Matches: **Choose among returned releases and click Apply. If there is no match, enter metadata manually.
- **Album Metadata: **Edit Album, Album Artist, Year, and Genre, then Apply to all tracks to propagate album-level fields.
- **Track metadata: **Double-click a track Title or Artist to edit it inline. Track number and duration are not inline-editable.
- **Output Directory: **Required before proceeding; the last configured location is retained by the tool preferences.
- **Verify Rips: **Choose the per-track verification level before ripping. Twice (the default) re-reads each extracted track and compares the two independent reads. AccurateRip additionally looks up the disc's AccurateRip database records and cross-checks the rip against them over the network. Off disables verification entirely and only encodes the single extraction.

## MusicBrainz Lookup

When libdiscid is available, the reader calculates a disc ID and queries MusicBrainz by that identity, including artists, recordings, and release groups. If no disc ID is available, the fallback searches by track count and returns up to five candidates. A successful release applies album, year, album artist, track titles, and track artists.

Lookup failure is non-fatal: the track list can remain available, and you can fill in metadata manually.

## C2 Reliability Diagnostic

Test C2 Reliability reads a small region twice and compares the results. The diagnostic can report weak positive evidence that the drive populates C2 error flags, an all-zero C2 field that is inconclusive, or differing audio data that makes the test location invalid or indicates a possible read problem. The full detail is written to the CD ripper log. Treat C2 results as diagnostic evidence, not a guarantee of drive behavior.

## Output Formats and Quality

The format panel supports FLAC, MP3, OGG, M4A, WAV, and Opus. Quality choices are format-specific:

- **FLAC: **Level 8 max compression, Level 5 balanced, or Level 0 fastest.
- **MP3: **VBR V0, VBR V2, or CBR 320, 256, or 192 kbps.
- **OGG: **Quality 10, 8, 6, 5, or 3.
- **M4A: **AAC at 320, 256, 192, or 128 kbps.
- **Opus: **320, 192, 128, 96, or 64 kbps.
- **WAV: **Uncompressed 16-bit PCM; no quality tiers apply.
- **CUE sheet: **Writes a CUE sheet alongside successfully ripped tracks when enabled.

## Output Layout and Metadata

Each track is written under the selected output directory using this structure:

<output>\<album artist>\[<year>] <album>\<track number> - <title>.<extension>

Invalid filename characters are replaced with underscores, and a tag that is exactly `.` or `..` becomes an underscore so it cannot be used as a folder name. Before any folder is created, each track's output path is checked to be inside the selected output directory; a path that would land outside it fails that track and creates nothing.

The encoder writes title, artist, album artist, album, date, genre, and track metadata when values are available.

When CUE output is enabled, the generated sheet is named from the sanitized album title and includes the successfully encoded tracks and their titles and performers.

## Rip Tab

The Rip tab displays every selected track with an individual progress bar and status. START RIPPING begins the session; Cancel requests cancellation of the current extraction or encoding task. The track grid reports extraction and FFmpeg encoding progress. Split CUE Image opens a CUE sheet and uses the selected output directory to split a single-file image into tracks.

For each track, the session extracts to a temporary WAV, verifies that the extraction is non-empty, encodes to the selected format, removes the temporary WAV, and reports success or the specific failure. The drive is spun down after the session on a best-effort basis.

## Rip Verification

When verification is enabled, each track is checked after extraction and before encoding. A track that fails verification is NOT written to disk; its row reports Not accurate and the session marks the task failed.

- **Off: **No re-read or network cross-check. The single extraction is encoded as before.
- **Twice: **The track's sectors are read a second time and the two reads are compared. Identical reads report 'Rip-twice verified'. Twice requires only the local drive and works offline.
- **AccurateRip: **The disc's AccurateRip disc ID is computed from the TOC and the database is queried over the network. The rip is first checked against the database's main track-window record; if the disc was mastered with an audio offset, the candidates read adjacent TOC-gap sectors and are checked again over a wider with-gap window. A cross-check match reports 'Accurate' with the number of agreeing submissions. If the internet is unreachable the lookup degrades to the local rip-twice check and reports 'Unavailable (offline)'.
- **Outcomes: **'Accurate (confidence N)' for a database match, 'Rip-twice verified' for the local check, 'Not in database' when the disc is absent from AccurateRip (an unverified rip is still written), 'Unavailable (offline)' when the database could not be reached (degraded to rip-twice), or 'Not accurate' when the reads differ or the database checksum disagrees (the track is NOT written).

The confidence number is the count of other people whose rips produced exactly these track checksums, and it is reported rather than interpreted: AccurateRip has no separate 'confident' threshold, so one agreeing submission is a match, shown as 'Accurate (confidence 1)'. When several database records match a track, the highest count is the one shown. Confidence is only available in AccurateRip mode; the local rip-twice check has no database behind it and therefore shows no count.

Drives with an audio offset master discs with adjacent-track data at each track boundary. AccurateRip's with-gap window accounts for this, but for such drives the local rip-twice mode is the most reliable choice because both reads describe the same physical frames.

Separately from press offsets, a drive has a read offset: its raw audio stream can run a fixed number of frames early or late relative to the sector it was asked for. Without correction, every AccurateRip window shifts off the database vectors and a perfectly good rip reports MISMATCH on every track. CD Ripper measures this offset once per drive — with the Detect Read Offset button on the Setup tab, or the --detect-read-offset CLI flag — and stores it in the shared suite configuration; every rip then re-aligns the extracted audio and both verification reads automatically. For the final track of a disc, the shifted tail would need a read past the lead-out, which drives refuse, so the extracted audio is short by the offset (a few hundredths of a second) — the same compromise EAC makes for non-overreading drives, and the AccurateRip checksum is unaffected.

The result of each track's verification is appended to its status, and the Results summary aggregates the outcomes (for example '5 Accurate (confidence 12), 1 Not in database, 1 failed'), so a successful track without a verification label was ripped with verification disabled.

With AccurateRip mode the app logs the computed disc ID (ID1 / ID2 / CDDB) and whether database records were found, absent, or unavailable for the disc.

## Results

Results shows succeeded and failed counts, track titles, output filenames, and status. Open Output Folder opens the destination, Eject Disc requests an operating-system eject, and double-clicking a successful row reveals its file in Explorer.

Re-rip flagged tracks re-rips only the tracks whose rows failed and replaces those rows in place; every other track keeps its result. Nothing is retried automatically — the button is enabled only while at least one track has failed, and pressing it is the only way a re-rip happens. Re-runs use the verification level currently selected on the Setup tab, so a mismatch caused by a mis-measured read offset can be retried after Detect Read Offset has corrected it.

## Command Line

The registered command is cd-rip. Examples:

python -m audio_suite_shared.cli_app cd-rip D: --output-dir <output> --format flac\
python -m audio_suite_shared.cli_app cd-rip D: --output-dir <output> --format mp3 --tracks 1,2,3\
python -m audio_suite_shared.cli_app cd-rip D: --output-dir <output> --format flac --cue\
python -m audio_suite_shared.cli_app cd-rip D: --output-dir <output> --dry --format opus\
python -m audio_suite_shared.cli_app cd-rip D: --output-dir <output> --format flac --verify accuraterip\
python -m audio_suite_shared.cli_app cd-rip D: --output-dir <output> --format flac --verify off\
python -m audio_suite_shared.cli_app cd-rip D: --detect-read-offset

CLI options include --format, --tracks, --quality, --cue/--no-cue, --dry/--live, --verify off|twice|accuraterip (default twice), and --json/--text. Dry Run prints the selected settings (including the verification level) and does not read or write tracks. Track lists are comma-separated; invalid or empty track selections are rejected. --output-dir is required for ripping (and for a dry run) but not for --detect-read-offset.

--detect-read-offset measures the drive's read offset against the AccurateRip database using the CD currently in the drive: it reads each track once with a margin, sweeps every candidate frame shift against the database checksums, requires the winning candidate to agree across the graded tracks, re-confirms it with the production checksum pipeline on every track, and persists the result for the drive in the shared suite configuration. It needs a multi-track disc present in the AccurateRip database and a working network connection; on failure nothing is persisted and the command exits non-zero.

## Troubleshooting

- **No drive detected: **Confirm Windows sees the optical drive, refresh the drive list, and insert an audio CD.
- **Disc cannot be read: **Check administrator rights, disc condition, drive access, FFmpeg/ffprobe availability, and the CD ripper log.
- **No MusicBrainz match: **Use the fallback track data and enter album, artist, year, genre, title, and artist values manually.
- **C2 diagnostic is inconclusive: **An all-zero C2 field is not proof of either reliable or unreliable C2 support; test another track or known-problem disc.
- **Encoding failed: **Check FFmpeg availability, selected quality, output permissions, disk space, and the per-track status message.
- **Track was not written: **A failed extraction, cancellation, missing TOC entry, failed encode, or a verification failure prevents a successful output file.
- **A track reports Not accurate: **The re-read differed from the first extraction or the AccurateRip checksum disagreed. Try cleaning the disc, or press Re-rip flagged tracks on the Results tab to re-run just that track; switching to Verify Rips = Twice is the right choice for drives with an audio offset.
- **Every track reports Not accurate on a known-good disc: **The drive probably has an uncorrected read offset. Click Detect Read Offset on the Setup tab (or run cd-rip <drive> --detect-read-offset) once with a disc that is in the AccurateRip database; the measured offset is stored per drive and applied to every future rip automatically.
- **A track shows Not in database: **The disc is not (yet) in the AccurateRip database. The rip is treated as a single extraction and written anyway; the label distinguishes this from a verified rip.
- **A track shows Unavailable (offline): **The database could not be reached; the mode degraded to the local rip-twice re-read. Verify the network connection.

## Safety and Recovery

Verify metadata and output settings before ripping a full disc. The raw extraction uses low-level drive access and requires administrator rights. Keep the original CD available until all tracks and metadata have been reviewed. A failed, cancelled, or verification-mismatched track does not produce a completed output file, and temporary WAV files are cleaned up after each task.
