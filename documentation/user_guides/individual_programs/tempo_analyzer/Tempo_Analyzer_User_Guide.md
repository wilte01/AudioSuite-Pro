---
title: Tempo Analyzer & Tagger - User Guide
subtitle: Based on the current Tempo Analyzer implementation
---

> Prerequisite - BPM tags required
> This program reads existing BPM values already present in your files' tags (the TBPM ID3 frame for MP3/WAV/AIFF, or the equivalent field for FLAC, OGG, Opus, MP4, and M4A). It does not detect or calculate BPM. Run the BPM Analyzer tool first if your files do not already carry BPM tags.

## Overview

Tempo Analyzer & Tagger reads existing BPM tags from your music files and automatically adds human-readable tempo markings. Supported formats are MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF, and AIF. Musical terms like Allegro, Andante, and Presto convey both speed and character in a way that a bare number cannot. The program offers 7 built-in naming schemes - from traditional Italian classical terms to dance music genres and running paces - and saves your preferred scheme automatically between sessions.

### What Are Tempo Markings?

Tempo markings are musical terms that describe the speed and character of a piece of music, providing more context than a bare number. Allegro (lively, fast) at 140 BPM conveys both speed and mood; "140 BPM" is purely numerical. These markings help musicians and listeners understand the intended feel of the music, and in digital libraries they provide an elegant way to browse and organise tracks by musical character.

### Key Features

- **Reads existing BPM tags: **Reads existing BPM tags from MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF, and AIF files.
- **7 built-in tempo naming schemes: **Italian, English, Descriptive, Numeric, Simplified, Dance, Running
- **Format-correct tag writing: **Writes a custom TEMPO tag to each file - TXXX:TEMPO for MP3, WAV, and AIFF/AIF; a Vorbis tempo comment for FLAC, OGG, and Opus; an iTunes-style ----:com.apple.iTunes:TEMPO atom for M4A and MP4.
- **Automatic scheme saving: **Your preferred scheme is stored in the shared suite configuration and restored automatically on the next run.
- **Re-tagging: **An existing TEMPO tag is updated when the BPM or the selected scheme has changed; the previous value is shown in the log.
- **Parallel processing: **Up to 8 concurrent worker slots show live per-file progress.
- **Dry Run mode: **Preview every assignment before writing tags.
- **In-app scheme reference: **A reference table of BPM ranges and markings updates as you switch schemes.
- **Detailed categorised logging: **See Log Files below.

## System Requirements

| Requirement | Detail |
| --- | --- |
| Python | 3.11 or higher (the suite's declared floor) |
| Operating System | Windows, macOS, or Linux |
| mutagen | Audio tag reading and writing - installed with the suite (pip install mutagen) |
| CPU | Multi-core recommended (up to 8 workers for full parallel performance) |
| RAM | Minimal - only tag metadata in memory |

## Tempo Naming Schemes

Choose the scheme that best fits your collection and use case. Your selection is saved to the shared suite configuration and restored automatically on the next run. The default is Italian.

| Scheme | Best For |
| --- | --- |
| Italian | Classical music collections, educational use, musicians |
| English | General libraries where plain language is preferred |
| Descriptive | Workout playlists, mood-based organisation, energy filtering |
| Numeric | Technical users who prefer direct BPM range labels |
| Simplified | Minimalist libraries, quick four-tier categorisation |
| Dance | EDM, DJ collections, electronic music libraries |
| Running | Fitness playlists, exercise apps, running coaching |

### Full Scheme Reference

Each scheme below uses its own BPM ranges. The ranges are not aligned across schemes - for example, the Descriptive scheme's "Easy Pace" band (61-90) does not start or end at the same BPM as any Italian band, so each scheme is listed with its own boundaries rather than sharing a single combined column. Bands are inclusive at both ends; the top band of each scheme is open-ended.

#### Italian

| BPM Range | Marking |
| --- | --- |
| 0-23 | Larghissimo |
| 24-40 | Largo |
| 41-66 | Larghetto |
| 67-76 | Adagio |
| 77-98 | Andante |
| 99-110 | Allegretto |
| 111-120 | Moderato |
| 121-168 | Allegro |
| 169-177 | Vivace |
| 178-200 | Presto |
| 201+ | Prestissimo |

#### English

| BPM Range | Marking |
| --- | --- |
| 0-40 | Very Slow |
| 41-76 | Slow |
| 77-108 | Moderate |
| 109-140 | Fast |
| 141-177 | Very Fast |
| 178+ | Extremely Fast |

#### Descriptive

| BPM Range | Marking |
| --- | --- |
| 0-60 | Relaxed |
| 61-90 | Easy Pace |
| 91-120 | Moderate Energy |
| 121-140 | Energetic |
| 141-160 | High Energy |
| 161-180 | Intense |
| 181+ | Frantic |

#### Numeric

| BPM Range | Marking |
| --- | --- |
| 0-60 | 0-60 BPM |
| 61-80 | 61-80 BPM |
| 81-100 | 81-100 BPM |
| 101-120 | 101-120 BPM |
| 121-140 | 121-140 BPM |
| 141-160 | 141-160 BPM |
| 161-180 | 161-180 BPM |
| 181-200 | 181-200 BPM |
| 201+ | 200+ BPM |

#### Simplified

| BPM Range | Marking |
| --- | --- |
| 0-90 | Slow |
| 91-120 | Medium |
| 121-150 | Fast |
| 151+ | Very Fast |

#### Dance

| BPM Range | Marking |
| --- | --- |
| 0-90 | Downtempo |
| 91-110 | Hip Hop |
| 111-130 | House |
| 131-145 | Techno |
| 146-170 | Drum and Bass |
| 171+ | Hardcore |

#### Running

| BPM Range | Marking |
| --- | --- |
| 0-120 | Walking Pace |
| 121-140 | Easy Run |
| 141-160 | Moderate Run |
| 161-180 | Fast Run |
| 181+ | Sprint |

> Note on the Allegro range
> In the Italian scheme, Allegro spans a wide range (121-168 BPM), covering light, moderate, and brisk fast tempos. This reflects traditional musical practice where Allegro is a broad category rather than a precise marking. Vivace and Presto distinguish the upper reaches.

## Getting Started

### Launching the Program

Double-click Tempo_Analyzer.pyw to launch the graphical interface. The .pyw extension runs the program without showing a console window.

## Interface Overview

The program uses a three-tab interface to guide you through configuration, tagging, and review.

### Tab 1 - Setup

Configure all parameters before starting.

#### Run Controls Panel (Master Driver Options)

The top of the Setup tab contains a Run Controls panel that mirrors the Master Driver source bar and control strip. It shows exactly the source directory and control options the Master Driver passes to this program:

- Source Music Directory - the folder containing music files with BPM tags, with a Browse button
- Mode - Dry Run or Live Update
- Auto Start - begin the tempo analysis automatically on launch
- Auto End - close the window automatically once processing finishes
- Clear Logs / Parallel - Master Driver orchestration options shown here for reference; they mirror the driver's settings but stay greyed out because only the driver executes them

When the program is launched via the Master Driver, every inherited value is displayed but locked (greyed out), because those settings are owned by the driver. When the program is launched standalone, the Source directory, Mode, and Auto End remain editable, while Auto Start stays greyed out because an automatic start-up can only be requested by the Master Driver.

#### Music Directory

- Choose the folder via the Source Music Directory field in the Run Controls panel above
- The program processes all supported audio files (MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF, and AIF) in the directory
- Does not recurse into subdirectories

#### Tempo Naming Scheme

- Choose your preferred scheme in the dropdown: Italian, English, Descriptive, Numeric, Simplified, Dance, Running
- Your selection is saved to the shared suite configuration and restored automatically on the next launch

#### Tempo Marking Reference

- A scrollable reference table showing all BPM ranges and their markings for the currently selected scheme
- Updates automatically when you change schemes - useful for reviewing ranges before processing

#### Select Mode

Choose the mode from the Mode dropdown on the Run Controls panel at the top of the tab:

| Mode | Behaviour |
| --- | --- |
| Dry Run | Reads BPM tags and shows what tempo marking would be assigned to each file, without writing anything. Always use this first. |
| Live Update | Writes a TEMPO tag to your music files (format-specific - see Tag Format in Technical Details). Only use after verifying Dry Run results. |

#### Tool Configuration Presets

Each tool supports saving and loading named configuration presets. This lets you quickly switch between different setups - for example, "Archive Quality" for final storage and "Quick Draft" for rough cuts.

- **Saving a Preset**
- Configure all settings in the Setup tab as desired.
- Type a name in the Presets field (or choose a name from the dropdown).
- Click Save to store the current settings under that name.
- The preset is saved per-tool and persists across sessions.
- **Loading a Preset**
- Choose a preset name in the dropdown to instantly restore all saved settings.
- **Deleting a Preset**
- Choose the preset name in the dropdown.
- Click Delete and confirm the deletion.
- The preset is removed permanently.

Presets are stored in the shared suite configuration file and are independent of the tool's last-used settings.

### Tab 2 - Processing

Becomes active when you click BEGIN TEMPO ANALYSIS.

Displays:

- Overall status showing the current operation phase
- Progress bar with completion percentage
- Running statistics: Processed, Skipped, Errors
- Worker status panel showing up to 8 parallel workers and the file each is currently processing
- Real-time file list showing the assigned tempo marking and BPM value for each file

```text
[DRY RUN] Track01.mp3 -> Allegro (128 BPM)
[TAGGED]  Track02.mp3 -> Andante (84 BPM)
[TAGGED]  Track03.mp3 -> House (122 BPM)
[SKIP]    Track04.mp3 (No BPM tag)
[SKIP]    Track05.mp3 (No tags found)
[ERROR]   Track06.mp3
```

### Tab 3 - Results

Displays the final summary after processing completes:

- Summary statistics - total files, tagged, skipped, errors, and processing time
- View Log - opens the detailed log file with all tempo assignments
- Open Folder - opens the source music directory in your file explorer

## Step-by-Step Guide

1. Ensure files have BPM tags. Verify your music files already have BPM tags. If not, run BPM Analyzer first.
1. Launch the program. Double-click Tempo_Analyzer.pyw.
1. Select your music folder. Click Browse and navigate to your music directory.
1. Choose your tempo scheme. Select from the dropdown. The reference table updates to show the BPM ranges for your chosen scheme. Your selection is saved automatically.
1. Run Dry Run first. Select Dry Run mode and click BEGIN TEMPO ANALYSIS. Review the assigned markings in the file list.
1. Verify results. Check that the markings look appropriate. If files are showing SKIP (No BPM tag), the file has tags but no BPM value - run BPM Analyzer on those files first. If files show SKIP (No tags found), the file has no tag block at all and also needs BPM Analyzer run on it. If the scheme doesn't feel right for your collection, try a different one.
1. Tag your files. Return to the Setup tab, change mode to Live Update, and run again. TEMPO tags will be written to all files with BPM values.
1. Check in your music player. The TEMPO custom tag field should now be visible in tag editors and players such as Foobar2000 or MusicBee (shown as a TXXX frame for MP3/WAV/AIFF/AIF, a Vorbis comment for FLAC/OGG/Opus, or an iTunes-style atom for M4A/MP4).

## Processing Status Reference

| Status | Meaning |
| --- | --- |
| [TAGGED] | Tempo marking successfully written (or would be written in Dry Run mode - see below) |
| [DRY RUN] | Dry Run mode - marking calculated and displayed but not written |
| [SKIP] No BPM tag | File has tag metadata but no BPM value set - run BPM Analyzer first |
| [SKIP] No tags found | File has no tag metadata at all - the file needs tagging before Tempo Analyzer can help |
| [ERROR] | Unexpected error during processing - check the log |

## Configuration

Tempo Analyzer stores its preferences in the suite-wide shared configuration file, alongside every other tool's preferences. It does not create a tool-local file.

| Property | Detail |
| --- | --- |
| Filename | audio_suite_config.json |
| Location | The Audio Suite root directory (shared by all tools) |
| Format | JSON - { "tempo_scheme": "Italian" } |
| Written | Whenever you change the scheme selection |
| Read | On every startup to restore the last-used scheme |

If the value is missing, unreadable, or names a scheme that no longer exists, the program falls back to Italian. If the shared configuration cannot be written, the program still runs - the choice is simply not remembered.

## Log Files

| Log File | Created When |
| --- | --- |
| tempo_dry_run_log.txt | After every Dry Run |
| tempo_analysis_log.txt | After every Live Update run |

Log contents include:

- Selected tempo scheme name and processing mode
- Tempo marking and BPM value assigned to each file
- Previous TEMPO tag value (if updating an existing tag)
- Status for each file: TAGGED, DRY RUN, SKIP, or ERROR
- Summary statistics and total processing time

## Command-Line Operation

Tempo Analyzer can be launched from the command line in two ways: the positional handshake the Master Driver uses, and the suite's unified command.

### Master Driver Handshake (.pyw)

The Master Driver launches the program with a fixed positional layout.

```text
python Tempo_Analyzer.pyw <folder> <unused>
    <--live|--dry> <--start|--no-start> <--end|--no-end>
    [--scheme <SchemeName>]
```

| Position / Flag | Value / Description |
| --- | --- |
| 1 - folder | Path to the directory containing supported audio files (required) |
| 2 - (unused) | Reserved positional slot - pass any value; ignored |
| 3 - mode | --live or --dry |
| 4 - auto_start | --start or --no-start |
| 5 - auto_end | --end or --no-end |
| --scheme <name> | Override the saved scheme: Italian, English, Descriptive, Numeric, Simplified, Dance, Running. If omitted, the saved scheme is used. |
| --clear-logs / --parallel-run | Display-only flags mirrored from the driver; they are shown in the interface but not executed by this tool |

### Unified Suite Command

```text
audiosuite tempo <directory> [--dry|--live] [--json|--text]
    [--scheme <SchemeName>]
```

| Argument / Option | Description |
| --- | --- |
| directory | Required positional path to the music directory. The directory must already exist. |
| --dry / --live | Preview only, or write TEMPO tags. Omitting the flag is equivalent to --dry. |
| --json / --text | Emit machine-readable JSON (default) or a one-line text summary. |
| --scheme <name> | Scheme to apply. Omitting the flag uses Italian. |

Examples:

```text
audiosuite tempo "C:\Music\Classical" --dry
audiosuite tempo "C:\Music\House Collection" --live --scheme Dance
audiosuite tempo "C:\Music\Classical" --live --scheme Italian --text
```

> Two different defaults
> The unified command always defaults to the Italian scheme and does not read your saved preference, because it is a batch entry point rather than an interactive launch. Pass --scheme explicitly if you want a specific scheme. The .pyw handshake is the opposite: it restores your saved preference when --scheme is omitted.

### Undo

Live Update tag changes participate in the suite's batch undo context, so they can be reverted through the Undo Tag Edits workflow using the tag snapshots taken at processing time. Dry Run never writes, so it creates no undo entry.

## Troubleshooting

### Scheme Not Remembered

- The shared audio_suite_config.json lives in the Audio Suite root directory - confirm you are running the suite from its installed location and that the directory is writable
- If the file exists but is read-only, the scheme change is not saved
- If the stored value is not a valid scheme name, the program falls back to Italian

### Wrong Tempo Scheme Applied

- Check the selected scheme in the Setup tab dropdown before processing
- Review the reference table to confirm BPM ranges match your expectations
- Run Dry Run mode first to preview assignments before committing
- Re-run with the correct scheme - existing TEMPO tags will be updated

### Files Showing SKIP Status

- The Tempo Analyzer requires an existing BPM value in the file's tags. Run the BPM Analyzer tool on these files first
- Verify BPM tags are present by opening one file in a tag editor such as Mp3tag and checking for the BPM field
- [SKIP] No tags found means the file has no tag block at all; [SKIP] No BPM tag means the file has tags but no BPM value set

### mutagen Not Found

- Install mutagen: pip install mutagen
- Verify: python -c "import mutagen; print(mutagen.version)"

## Common Use Cases

### Classical Collection Cataloguing

Apply the Italian scheme to a classical library to annotate tracks with the tempo markings that composers and performers use. Allegretto, Andante, and Vivace sit naturally alongside other classical metadata, and the TEMPO tag makes it easy to filter by tempo in Foobar2000 or MusicBee.

### DJ Library Organisation

Apply the Dance scheme to an electronic music collection to group tracks by genre-approximate tempo bands - House, Techno, Drum and Bass, and so on. Combined with BPM tags already written by BPM Analyzer, this gives DJ software an additional human-readable dimension for track selection.

### Workout and Running Playlists

Apply the Running scheme to a fitness music collection to tag tracks by exercise intensity: Walking Pace, Easy Run, Moderate Run, Fast Run, Sprint. Filter by the TEMPO tag to quickly assemble a playlist matched to a specific training zone.

### Mood-Based Library Browsing

Apply the Descriptive scheme to tag tracks by energy level: Relaxed, Easy Pace, Moderate Energy, Energetic, High Energy, Intense, Frantic. Combined with genre and rating tags, this enables fine-grained filtering for mood-based playlist creation.

## Tips and Best Practices

1. Run BPM Analyzer first. Tempo Analyzer is a downstream tool - it needs accurate BPM tags to produce useful tempo markings.
1. Always use Dry Run first. Preview assignments before writing tags, especially when switching schemes.
1. Match scheme to genre. Italian for classical; Dance for EDM; Running or Descriptive for fitness playlists; English or Simplified for general libraries.
1. Process by genre if using multiple schemes. Run Tempo Analyzer separately on each genre folder with its most appropriate scheme - the scheme can be overridden per run with --scheme.
1. Verify BPM accuracy first. Incorrect BPM values lead to incorrect tempo markings. Spot-check BPM tags before running Tempo Analyzer on a large library.
1. Re-run freely. Existing TEMPO tags are overwritten if the BPM or scheme has changed. There is no need to clear tags manually before switching schemes.
1. Review the reference table. Check the in-app reference table for the currently selected scheme before processing to confirm the BPM ranges match your expectations.
1. Check the log. The log shows both the assigned marking and the source BPM value, making it easy to spot files where the BPM tag might be wrong.

## Technical Details

### Tag Format

The tag written depends on file format. The table below covers the ID3-based formats. For FLAC, OGG, and Opus, the marking is stored in a Vorbis comment field named tempo. For M4A and MP4, it is stored in an iTunes-style freeform atom.

| Property | Value |
| --- | --- |
| Frame type (MP3/WAV/AIFF/AIF) | TXXX (User Defined Text Information) |
| Description | TEMPO |
| Value | Tempo marking text from the selected scheme (e.g. Allegro, House, Fast Run) |
| Encoding | UTF-8 (encoding=3) |
| Compatibility | ID3v2.3 and ID3v2.4 |

### Processing Pipeline

1. File scan. All supported audio files (MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF, and AIF) in the directory are queued for processing.
1. Tag reading. mutagen reads the file's tag block and locates the BPM value: the TBPM ID3 frame for MP3/WAV/AIFF/AIF, the Vorbis bpm comment for FLAC/OGG/Opus, or the tmpo atom for M4A/MP4.
1. BPM validation. If the file has no tag metadata at all, [SKIP] No tags found. If tags exist but no BPM value is set, [SKIP] No BPM tag.
1. Scheme lookup. The BPM value is matched against the selected scheme's BPM ranges to determine the marking.
1. Tag writing. In Live Update mode, the format-specific TEMPO tag is written or updated. In Dry Run mode, the result is only reported.
1. Logging. Status, marking, and BPM value are written to the log file.

### Performance Characteristics

| Metric | Detail |
| --- | --- |
| Parallel workers | Up to 8 concurrent worker slots via a thread pool |
| CPU usage | Very low - only tag read/write operations |
| Memory usage | Minimal - only tag metadata in RAM per worker |
| Processing speed | Very fast - hundreds of files per second on typical hardware |

\- End of User Guide -
