# CLI Commands Reference

All CLI commands are accessed via the `audiosuite` entry point:

```bash
audiosuite <command> <directory> [options]
```

## Album Genre Tagger

Consolidate album-level genre tags from custom field hierarchy.

```bash
audiosuite album-genre <directory> [--dry] [--json] [--coverage N]
```

**Options:**
- `--dry` / `--live` — Analyse only, do not write tags (default: live)
- `--json` / `--text` — Output results as JSON (default: text)
- `--coverage N` — Minimum coverage percentage 0–100 before writing (default: 50)

**Examples:**
```bash
audiosuite album-genre "D:\Music\Various" --dry
audiosuite album-genre "D:\Music\Various" --json
audiosuite album-genre "D:\Music\Various" --coverage 75
```

## Album Art Sync

Fetch and embed album artwork from multiple sources (MusicBrainz, Fanart.tv, Deezer, iTunes).

```bash
audiosuite album-art <directory> [--embed-size N] [--purge/--no-purge] [--dry] [--json]
```

**Options:**
- `--embed-size N` — Embedded resolution in pixels (default: 800)
- `--purge` / `--no-purge` — Purge hidden thumbnail files (default: purge)
- `--dry` / `--live` — Analyse only, do not write tags (default: live)
- `--json` / `--text` — Output results as JSON (default: text)

**Examples:**
```bash
audiosuite album-art "D:\Music\Beatles" --embed-size 1200 --no-purge
audiosuite album-art "D:\Music\Beatles" --dry
```

## ASX Playlist Extractor

Extract audio files from ASX playlists.

```bash
audiosuite asx-extract <directory> [--dry] [--json]
```

**Options:**
- `--dry` / `--live` — Analyse only, do not copy or remove files (default: live)
- `--json` / `--text` — Output results as JSON (default: text)

**Examples:**
```bash
audiosuite asx-extract "D:\Playlists" --dry
audiosuite asx-extract "D:\Playlists" --json
```

## Noise Reduction

Remove mains-frequency hum and broadband background noise from audio files.

```bash
audiosuite reduce <directory> [--reduce-hum] [--reduce-broadband] [OPTIONS]
```

**Options:**
- `--reduce-hum` — Enable hum removal via notch filtering
- `--hum-frequency [50|60]` — Mains frequency in Hz (default: 60)
- `--hum-harmonics N` — Harmonics to filter, 1–20 (default: 8)
- `--hum-quality Q` — Notch Q factor, 1–100 (default: 30)
- `--reduce-broadband` — Enable broadband noise reduction
- `--noise-start MS` — Noise profile start in ms (default: 0)
- `--noise-end MS` — Noise profile end in ms (default: 500)
- `--gate-threshold DB` — Gate threshold in dB (default: 3)
- `--dry` / `--live` — Write results or preview only (default: live)
- `--json` / `--text` — Output results as JSON (default: text)

**Examples:**
```bash
audiosuite reduce "D:\Music" --reduce-hum --hum-frequency 50
audiosuite reduce "D:\Music" --reduce-broadband --dry --json
```

## Audio Refinery

Run the single-pass Refinery pipeline. Stages are selected with the
`--stages` comma-separated list (order is fixed).

```bash
audiosuite refine <directory> [--stages LIST] [OPTIONS]
```

**Options:**
- `--stages LIST` — Comma-separated stages to run: `declick`, `trim`, `reduce_noise`, `enhance`, `normalise` (default: declick,trim,enhance,normalise)
- `--reduce-hum` — Enable hum removal via notch filtering
- `--hum-frequency [50|60]` — Mains frequency in Hz (default: 60)
- `--hum-harmonics N` — Harmonics to filter, 1–20 (default: 8)
- `--hum-quality Q` — Notch Q factor, 1–100 (default: 30)
- `--reduce-broadband` — Enable broadband noise reduction
- `--noise-start MS` — Noise profile start in ms (default: 0)
- `--noise-end MS` — Noise profile end in ms (default: 500)
- `--gate-threshold DB` — Gate threshold in dB (default: 3)
- `--sensitivity F` — Declick sensitivity (default: 0.31)
- `--width N` — Declick max defect width in ms (default: 2)
- `--threshold DB` — Trim silence threshold dBFS (default: -50)
- `--preset NAME` — Enhancement preset: Mild, Moderate, Aggressive, Custom (default: Moderate)
- `--target-lufs LUFS` — Normalisation target (default: -16.0)
- `--tolerance DB` — Normalisation tolerance (default: 0.5)
- `--output DIR` — Output directory (default: source dir)
- `--dry` / `--live` — Simulate or write results
- `--json` / `--text` — Output results as JSON (default: text)

**Examples:**
```bash
audiosuite refine "D:\Music" --stages declick,trim,reduce_noise,enhance,normalise
audiosuite refine "D:\Music" --stages reduce_noise --reduce-hum --hum-frequency 50 --dry
```

## CD Ripper

Rip audio CD tracks to files from a command line.

```bash
audiosuite cd-rip DRIVE [--output-dir DIR] [--format FMT] [--tracks LIST] [--cue] [OPTIONS]
```

**Options:**
- `--output-dir DIR` — Destination folder (required for ripping; not needed with `--detect-read-offset`)
- `--format [wav|mp3|flac|ogg|m4a|opus]` — Output audio format (default: flac)
- `--tracks LIST` — Comma-separated track numbers to rip (default: all)
- `--quality TEXT` — Format-specific quality preset string
- `--cue` / `--no-cue` — Write a CUE sheet alongside the ripped tracks (default: no-cue)
- `--verify [off|twice|accuraterip]` — Track verification: `twice` re-reads each track and compares, `accuraterip` additionally cross-checks against the AccurateRip database, `off` disables verification (default: twice). Per-track outcomes are reported with EAC's wording — `Accurate (confidence N)` for a database match, `Rip-twice verified` for the local check, `Not in database`, `Unavailable (offline)`, or `Not accurate` (which is never written). A failed track can be re-ripped from the Results tab; nothing is retried automatically
- `--dry` / `--live` — Show what would be ripped without writing files
- `--detect-read-offset` — Measure the drive's read offset against the AccurateRip database using the inserted CD and persist it for the drive; applied automatically to future rips. Needs a multi-track disc present in the database and network access; exits non-zero and persists nothing on failure
- `--json` / `--text` — Output results as JSON

**Examples:**
```bash
audiosuite cd-rip D: --output-dir /output/flac --format flac
audiosuite cd-rip D: --output-dir /output/mp3 --format mp3 --tracks 1,2,3
audiosuite cd-rip D: --output-dir /output/flac --cue
audiosuite cd-rip D: --output-dir /output/flac --verify accuraterip
audiosuite cd-rip D: --detect-read-offset
```

## CUE Sheets

Parse, generate, and split `.cue` sheets. The `cue` group has three sub-commands:

- `parse` — Inspect an existing sheet's track layout and timestamps.
- `generate` — Build a sheet that matches the audio tracks in a folder or a single file.
- `split` — Split a single-file audio image into per-track files using a sheet (lossless `-c copy`).

### cue parse

```bash
audiosuite cue parse CUE_FILE [--json]
```

Text mode prints a compact track table. `--json` emits the full parsed
structure including REM comments, ISRC codes, PREGAP/POSTGAP and index
timestamps in milliseconds.

**Examples:**
```bash
audiosuite cue parse "D:\Music\Album\Album.cue"
audiosuite cue parse "D:\Music\Album\Album.cue" --json
```

### cue generate

```bash
audiosuite cue generate TARGET [-o FILE] [--title TEXT] [--artist TEXT] [--json]
```

`TARGET` is a directory of ripped track files or a single audio file. Track
numbers, titles and artists are read from embedded tags, falling back to the
`NN - Title.ext` filename prefix for untagged files. The sheet is written to
`album.cue` next to the input by default. `--json` reports the written path
(`cue_path`), the sheet's track count (`tracks`) and the album title (`title`)
alongside the shared counters, so a caller can split the sheet it just made
without reading it back.

**Options:**
- `-o, --output FILE` — Destination `.cue` path (default: `album.cue` next to the input)
- `--title TEXT` — Album title for the generated sheet
- `--artist TEXT` — Album artist (`PERFORMER`) for the generated sheet
- `--json` / `--text` — Emit JSON output (default: text)

**Examples:**
```bash
audiosuite cue generate "D:\Music\Album"
audiosuite cue generate "D:\Music\Album" --title "Greatest Hits" --artist "The Band"
audiosuite cue generate "D:\Music\Album\01 Song.flac" -o out.cue
audiosuite cue generate "D:\Music\Album" --json
```

### cue split

```bash
audiosuite cue split CUE_FILE [-o DIR] [--ffmpeg EXE] [--json]
```

Each track is cut losslessly from the image at its `INDEX 01` timestamp and
tagged with the sheet's title / performer.

**Options:**
- `-o, --output-dir DIR` — Destination folder (default: alongside the CUE sheet)
- `--ffmpeg TEXT` — FFmpeg executable (name on PATH or absolute path)
- `--json` / `--text` — Emit JSON output

**Examples:**
```bash
audiosuite cue split "D:\Music\Album\Album.cue"
audiosuite cue split "D:\Music\Album\Album.cue" -o "D:\Music\Album\Tracks"
```

## Lyrics Manager

Fetch synced lyrics from a remote source and embed them into audio files.
Files are matched to the lyric source by their artist and title tags; files
whose tags are missing or contain "Unknown" are skipped.

```bash
audiosuite lyrics <directory> [--dry] [--json] [--parallel] [--workers N]
                   [--provider NAME] [--request-timeout SEC]
                   [--skip-existing/--no-skip-existing]
                   [--plain-fallback/--no-plain-fallback]
```

**Options:**
- `--dry` / `--live` — Analyse only, do not write tags (default: live)
- `--json` / `--text` — Output results as JSON (default: text)
- `--parallel` / `--no-parallel` — Process files in parallel (default: off)
- `--workers N` — Parallel worker count (default: 4)
- `--provider NAME` — Lyric source provider, e.g. `lrclib` (default: lrclib)
- `--request-timeout SEC` — Per-request timeout in seconds (default: 10.0)
- `--skip-existing` / `--no-skip-existing` — Skip files that already contain
  lyrics (default: skip-existing)
- `--plain-fallback` / `--no-plain-fallback` — Store unsynced lyrics when no
  synced lyrics are available (default: plain-fallback)

Synced lyrics are embedded as an ID3 `SYLT` frame for MP3/WAV/AIFF and in the
`SYNCEDLYRICS` Vorbis comment for FLAC/OGG/Opus. Unsynced lyrics (the fallback)
use `USLT` for MP3/WAV/AIFF, `LYRICS` for FLAC/OGG/Opus and `\xa9lyr` for
M4A/MP4. Each run records a batch in the undo log so tags can be reverted.

**Examples:**
```bash
audiosuite lyrics "D:\Music\Unknown-Arm"
audiosuite lyrics "D:\Music\Unknown-Arm" --live --parallel --workers 8
audiosuite lyrics "D:\Music\Unknown-Arm" --json
```

## Audio Fingerprinter

Generate a Chromaprint fingerprint for every audio file and identify it
through AcoustID, optionally enriching the match from the MusicBrainz
database. `--musicbrainz` costs one MusicBrainz request per unique recording
(plus one per unique release) at MusicBrainz's documented one request per
second, so it is off by default.

```bash
audiosuite fingerprint <directory> [--lookup/--no-lookup]
    [--write-tags/--no-write-tags] [--threshold N] [--max-length N]
    [--album-mode/--no-album-mode] [--album-min N] [--mbid-region CC]
    [--musicbrainz/--no-musicbrainz] [--write-isrc/--no-write-isrc]
    [--submit-isrc/--no-submit-isrc] [--mb-auth oauth|app-token]
    [--mb-user USER] [--json] [--dry]
```

- `--lookup` (default: on) — query AcoustID for each fingerprint. Without an
  API key the command exits instead of silently fingerprinting only.
- `--write-tags` (default: off) — write the AcoustID fingerprint/id tags.
  Requires live mode.
- `--threshold N` — minimum AcoustID score, 0.0-1.0 (default: 0.5).
- `--max-length N` — seconds of audio passed to `fpcalc` (default: 120).
- `--album-mode` (default: off) — cluster a folder's lookups by release group
  and tag only when the album is decided; ambiguous albums stay untagged.
- `--album-min N` — votes needed to form an album cluster (default: 3).
- `--mbid-region CC` — preferred release country (ISO 3166-1 alpha-2) used
  only to break a tie between otherwise identical releases.
- `--musicbrainz` (default: off) — look the matched recording up in
  MusicBrainz: retrieve its ISRCs and release facts (date, label, country),
  and let MusicBrainz break an AcoustID near-tie the file's own tags could
  not settle. A lookup failure never fails a file; it degrades to the
  AcoustID-only result and says so in the message.
- `--write-isrc` (default: off) — write the retrieved ISRCs, in the format's
  native convention (`TSRC` for MP3/WAV/AIFF/DSF, `----:com.apple.iTunes:ISRC`
  for M4A/MP4, an `ISRC` comment/item for FLAC/OGG/Opus/WV/APE/MPC). Requires
  `--musicbrainz`, `--write-tags` and live mode.
- `--submit-isrc` (default: off) — submit the ISRCs the files' own tags carry
  to MusicBrainz for their matched recording, skipping codes already
  registered. Requires `--musicbrainz` (the recording lookup is what identifies
  the known codes). In dry mode the exact XML payload is printed and nothing is
  posted; live mode needs a token from `MUSICBRAINZ_TOKEN` or the encrypted
  store. The token is never accepted as a flag: argv is visible in process
  listings and shell history.
- `--mb-auth oauth|app-token` (default: `oauth`) — how the submission is
  authenticated. `oauth` sends the token as a bearer token (scope
  `submit_isrc`); `app-token` uses a legacy application token over HTTP Digest,
  which MusicBrainz has deprecated.
- `--mb-user USER` — MusicBrainz account name, required only by
  `--mb-auth app-token` (digest sends both a username and the token).

**Examples:**
```bash
audiosuite fingerprint "D:\Music\Unknown-Arm" --dry
audiosuite fingerprint "D:\Music\Unknown-Arm" --live --write-tags --musicbrainz
audiosuite fingerprint "D:\Music\Unknown-Arm" --live --write-tags --musicbrainz --write-isrc --json
audiosuite fingerprint "D:\Music\Ripped-CD" --musicbrainz --submit-isrc --dry
audiosuite fingerprint "D:\Music\Ripped-CD" --musicbrainz --submit-isrc --live
```

## All Commands

| Command | Tool | Category |
|---|---|---|
| `album-genre` | Album Genre Tagger | Enrich (metadata) |
| `album-art` | Album Art Sync | Enrich (metadata) |
| `asx-extract` | ASX Playlist Extractor | Utility |
| `bpm` | BPM Analyzer | Enrich |
| `cd-rip` | CD Ripper | Utility |
| `convert` | Music Format Converter | Utility |
| `cue generate` | CUE Sheet Generator | Utility |
| `cue parse` | CUE Sheet Parser | Utility |
| `cue split` | CUE Sheet Splitter | Utility |
| `declick` | Pop & Click Remover | Refinery |
| `enhance` | Audio Enhancer | Refinery |
| `fingerprint` | Audio Fingerprinter | Enrich (metadata) |
| `genre-sync` | Genre Sync | Enrich |
| `key` | Key Detector | Enrich |
| `lyrics` | Lyrics Manager | Enrich |
| `normalise` | Audio Normalizer | Refinery |
| `reduce` | Noise Reduction | Utility |
| `refine` | Audio Refinery | Refinery |
| `reorganize` | Tag-Based File Reorganizer | Utility |
| `replaygain` | ReplayGain Analyzer | Enrich |
| `scrub` | Metadata Scrubber | Enrich |
| `silence-trim` | Silence Trimmer | Refinery |
| `stats` | Library Statistics Dashboard | Utility |
| `tempo` | Tempo Analyzer | Enrich |

## Headless / Scripting

The CLI is the headless face of the suite: no window is created, and each command
imports and runs the same processor class the GUI uses, so a result does not
depend on which face you chose. This section covers what is shared by **every**
command; the per-command sections above cover each command's own flags, and the
`All Commands` table is the authoritative list — a tool that is not in it has no
CLI command yet and runs through its `.pyw` launcher or the Master Driver.

### Running it

`uv run audiosuite …` from the checkout is the supported form: it executes the
dependency graph pinned in `uv.lock` against an editable install of these
sources, so the command list always matches the tree. Without `uv`, invoke the
module directly:

```bash
python -m audio_suite_shared.cli_app --help
```

### Grammar

```
audiosuite <command> [OPTIONS] DIRECTORY
```

`DIRECTORY` is required on every command and is always the folder to scan.

### Options every command accepts

- `--dry` / `--live` — analyse and report without writing, or write the result (default: live)
- `--json` / `--text` — one JSON document on stdout, or the human-readable report (default: text)
- `--parallel` / `--no-parallel` — process-level parallelism for CPU-bound stages (default: off)
- `--workers N` — worker count for the parallel path; each command's `--help` prints its own resolved default
- `--log-level` — `DEBUG`, `INFO`, `WARNING` or `ERROR`, given **before** the command (default: `WARNING`)
- `--json-schema` — print the locked output schema with a recorded success and failure document per command, then exit (before the command)
- `--version` — print the installed suite version and exit (before the command)

`audiosuite doctor` is the install check: it reports the checkout and installed
versions, resolves every first-party package, names the CLI commands a gap would
take down, and exits 1 when anything is wrong (`doctor --json` publishes the
same findings as one document).

### Exit status

Every command reports the outcome through its exit status, and the status agrees
with the summary it printed:

| Status | Meaning |
|---|---|
| `0` | The run was clean. **Skipped files are not errors** — a folder already in the target format exits 0. |
| `1` | The run finished with at least one per-file error, or it stopped early with a fatal error. The payload's `errors` count matches. |
| `2` | Usage error: an unknown flag, a missing required argument, or a bad value. Click reports it before any work starts. |

A dry run obeys the same rule: `--dry` writes nothing, but an unreadable or
unsupported input is still a real failure, so the status is 1 there too.

```bash
audiosuite convert /Music/tmp --format flac || echo "conversion reported errors"
```

This is the one behaviour change a script may notice: before 2.1.4 a batch that
reported errors still exited 0. The JSON document is unchanged, so a script that
parsed `errors` keeps working; one that relied on the status now sees the same
signal as the summary.

### JSON output

With `--json`, stdout carries **one** document and nothing else: progress and
errors go to stderr, so the output pipes cleanly. The document is written when
the run finishes, not per file — there is deliberately no streaming mode, and
that behaviour is pinned by a test rather than left to convention.

Every document carries `schema_version`, `tool`, `command`, `dry_run`, the
counters (`total`, `processed`, `succeeded`, `skipped`, `errors`), `duration_secs`,
`duration_str`, `log_entries`, and the command's own extras. A recorded example
(`bpm --dry --json` over a one-file folder that could not be analysed):

```json
{
  "schema_version": 1,
  "tool": "bpm",
  "command": "bpm",
  "dry_run": true,
  "total": 1,
  "processed": 1,
  "succeeded": 0,
  "skipped": 0,
  "errors": 1,
  "duration_secs": 5.588,
  "duration_str": "5.6s",
  "log_entries": ["[ERROR] track.wav: BPM detection failed — Audio is too short to analyse (0.05s).\n"],
  "skipped_files": [],
  "error_files": [
    {
      "filename": "track.wav",
      "reason": "Audio is too short to analyse (0.05s).",
      "error_type": "BPMDetectionError"
    }
  ],
  "outside_range_files": []
}
```

The shape is locked by `audio_suite_shared/cli_schema.json` and validated in CI
against one recording per command, so a script written against this example
keeps working or the gate fails. `--json-schema` prints the whole contract.

### Scripting examples

Collect two analyses and compare their error counts (PowerShell):

```powershell
$bpm = audiosuite bpm "D:\Music\Library" --dry --json | ConvertFrom-Json
$key = audiosuite key "D:\Music\Library" --dry --json | ConvertFrom-Json
Write-Host "BPM errors: $($bpm.errors)  Key errors: $($key.errors)"
```

A full tag-enrichment pass, dry first and live once the report is clean:

```bash
uv run audiosuite bpm /music/library --dry --json
uv run audiosuite key /music/library --dry --json
uv run audiosuite tempo /music/library --dry --scheme Italian --json
uv run audiosuite replaygain /music/library --dry --json
```

Read one counter in a shell pipeline:

```bash
if [ "$(audiosuite bpm /music/library --json | jq '.errors')" -gt 0 ]; then
    echo "BPM analysis reported errors" >&2
fi
```

A weekly scheduled run (cron; on Windows use Task Scheduler with the same
command):

```bash
0 3 * * 0 cd /path/to/AudioSuite-Pro && uv run audiosuite replaygain /music/library --live --json >> /var/log/audiosuite.log 2>&1
```

GUI and CLI differ only in what starts them:

| | GUI (`.pyw` / Master Driver) | CLI (`audiosuite`) |
|---|---|---|
| Window | yes, one per tool or via the control panel | none |
| Batch of tools | sequenced by the Master Driver | one command per invocation; chain them in your shell |
| Mode | Dry Run / Live Update radio | `--dry` / `--live` |
| Progress | tabs, log pane, batch progress bar | stderr, plus the run log |
| Result | the report on screen | the JSON document |
| Undo history | shared batch undo | shared batch undo |

## Standalone Utility Scripts

### Undo Batch

List, inspect, and revert the undo batches written by batch tools (BPM
Analyzer, Tempo Analyzer, Mood Analysis Batch Tagger, Tag Field Updater, File
Reorganizer). A batch collects every file a single run touched; `undo`
restores the pre-run tags or reverses file copies/moves.

```bash
python utilities/undo.py list [--limit N] [--db PATH]
python utilities/undo.py show <batch_id> [--db PATH]
python utilities/undo.py undo <batch_id> [--db PATH]
```

Batches live in `~/.audiosuite/undo_log.db` by default.

`--db` may be given before or after the subcommand — both
`undo.py --db PATH list` and `undo.py list --db PATH` select the same
database, and a path given after the subcommand wins. Before iteration-8 C6
the pre-subcommand position was silently overwritten by the subcommand's
default, so the wrong database was read.
