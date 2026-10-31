---
title: CLI Commands Reference
subtitle: Every audiosuite command, its flags, and the headless scripting contract
---

All CLI commands are accessed via the `audiosuite` entry point:

```bash
audiosuite <command> <directory> [options]
```

## ENRICH commands

The eleven tagging and analysis tools. Run them in this order for complete
results: **Metadata Scrubber**, **Audio Fingerprinter**, **ReplayGain
Analyzer**, **Album Genre Tagger**, **Genre Sync**, **BPM Analyzer**, **Tempo
Analyzer**, **Key Detector**, **Mood Analyzer**, **Album Art Sync**, **Lyrics
Manager**. The order matters in two places only: Tempo Analyzer reads the BPM
tag that BPM Analyzer writes, and Album Genre Tagger writes the album-level
genre (`ALBUMGENRE`) before Genre Sync derives each file's `Genre` from that
hierarchy.

Every command that changes a file accepts `--dry` / `--live` (analyse only, or
write) and `--json` / `--text` (one JSON document on stdout, or the report);
the complete shared set is in *Options every command accepts*. Each section
below lists its own flags and repeats the mode flag wherever the command's
two modes do something different.

### Metadata Scrubber

Strip tag clutter from MP3 files - comment spam, foreign frames, and the
tools that wrote them - while keeping what makes the file usable.

```bash
audiosuite scrub <directory> [--preserve-lyrics/--no-preserve-lyrics] [OPTIONS]
```

**Options:**

- `--preserve-lyrics` / `--no-preserve-lyrics` — Keep the lyrics frames (default: preserve)
- `--preserve-album-artist` / `--no-preserve-album-artist` — Keep the album-artist frame (default: preserve)
- `--preserve-embedded-art` / `--no-preserve-embedded-art` — Keep embedded artwork (default: preserve)

**Examples:**

```bash
audiosuite scrub "D:\Music\Downloads" --dry
audiosuite scrub "D:\Music\Downloads" --no-preserve-embedded-art
```

### Audio Fingerprinter

Generate a Chromaprint fingerprint for every audio file and identify it
through AcoustID, optionally enriching the match from the MusicBrainz
database. `--musicbrainz` costs one MusicBrainz request per unique recording
(plus one per unique release) at MusicBrainz's documented one request per
second, so it is off by default.

```bash
audiosuite fingerprint <directory> [--lookup/--no-lookup]
    [--write-tags/--no-write-tags] [--threshold N] [--max-length N]
    [--album-mode/--no-album-mode] [--album-min N] [--mbid-region CC]
    [--musicbrainz/--no-musicbrainz] [--write-mbids/--no-write-mbids]
    [--write-isrc/--no-write-isrc] [--submit-isrc/--no-submit-isrc]
    [--mb-auth oauth|app-token] [--mb-user USER] [--fpcalc PATH]
    [--api-key KEY] [--json] [--dry]
```

- `--lookup` (default: on) — query AcoustID for each fingerprint. Without an API key the command exits instead of silently fingerprinting only.
- `--write-tags` (default: off) — write the AcoustID fingerprint/id tags. Requires live mode.
- `--threshold N` — minimum AcoustID score, 0.0-1.0 (default: 0.5).
- `--max-length N` — seconds of audio passed to `fpcalc` (default: 120).
- `--fpcalc PATH` — path to the bundled `fpcalc` executable, when it is not found on `PATH`.
- `--api-key KEY` — AcoustID key for this run only, overriding the stored or environment key. Prefer the stored key: argv is visible in process listings and shell history.
- `--album-mode` (default: off) — cluster a folder's lookups by release group and tag only when the album is decided; ambiguous albums stay untagged.
- `--album-min N` — votes needed to form an album cluster (default: 3).
- `--mbid-region CC` — preferred release country (ISO 3166-1 alpha-2) used only to break a tie between otherwise identical releases.
- `--musicbrainz` (default: off) — look the matched recording up in MusicBrainz: retrieve its ISRCs and release facts (date, label, country), and let MusicBrainz break an AcoustID near-tie the file's own tags could not settle. A lookup failure never fails a file; it degrades to the AcoustID-only result and says so in the message.
- `--write-mbids` (default: off) — also write `MUSICBRAINZ_TRACKID` / `ARTISTID` / `ALBUMID`. Requires `--write-tags` and live mode.
- `--write-isrc` (default: off) — write the retrieved ISRCs, in the format's native convention (`TSRC` for MP3/WAV/AIFF/DSF, `----:com.apple.iTunes:ISRC` for M4A/MP4, an `ISRC` comment/item for FLAC/OGG/Opus/WV/APE/MPC). Requires `--musicbrainz`, `--write-tags` and live mode.
- `--submit-isrc` (default: off) — submit the ISRCs the files' own tags carry to MusicBrainz for their matched recording, skipping codes already registered. Requires `--musicbrainz` (the recording lookup is what identifies the known codes). In dry mode the exact XML payload is printed and nothing is posted; live mode needs a token from `MUSICBRAINZ_TOKEN` or the encrypted store. The token is never accepted as a flag: argv is visible in process listings and shell history.
- `--mb-auth oauth|app-token` (default: `oauth`) — how the submission is authenticated. `oauth` sends the token as a bearer token (scope `submit_isrc`); `app-token` uses a legacy application token over HTTP Digest, which MusicBrainz has deprecated.
- `--mb-user USER` — MusicBrainz account name, required only by `--mb-auth app-token` (digest sends both a username and the token).

**Examples:**

```bash
audiosuite fingerprint "D:\Music\Unknown-Arm" --dry
audiosuite fingerprint "D:\Music\Unknown-Arm" --live --write-tags --musicbrainz
audiosuite fingerprint "D:\Music\Unknown-Arm" --live --write-tags --musicbrainz --write-isrc --json
audiosuite fingerprint "D:\Music\Ripped-CD" --musicbrainz --submit-isrc --dry
audiosuite fingerprint "D:\Music\Ripped-CD" --musicbrainz --submit-isrc --live
```

### ReplayGain Analyzer

Measure perceived loudness and write the standard ReplayGain tags. The
measurement is metadata only and reversible by deleting the tags; `--apply-gain`
is the one mode that changes the audio, and only for MP3.

```bash
audiosuite replaygain <directory> [--target-lufs LUFS] [--apply-gain/--no-apply-gain] [OPTIONS]
```

**Options:**

- `--target-lufs LUFS` — reference loudness the gain is measured against; one of `-12`, `-14`, `-16`, `-18`, `-23` (default: -16)
- `--apply-gain` / `--no-apply-gain` — after tagging, bake the track gain into MP3 files losslessly by adjusting the global-gain header (default: off)

**Examples:**

```bash
audiosuite replaygain "D:\Music\Album" --dry
audiosuite replaygain "D:\Music\Album" --apply-gain --json
```

### Album Genre Tagger

Consolidate album-level genre tags from the file's custom-field hierarchy,
writing `ALBUMGENRE` only once the album's tracks agree.

```bash
audiosuite album-genre <directory> [--dry] [--json] [--coverage N]
```

**Options:**

- `--coverage N` — Minimum coverage percentage 0–100 before writing (default: 50)

**Examples:**

```bash
audiosuite album-genre "D:\Music\Various" --dry
audiosuite album-genre "D:\Music\Various" --json
audiosuite album-genre "D:\Music\Various" --coverage 75
```

### Genre Sync

Derive the standard genre tag from the custom genre fields already stored in
each file - `TITLEGENRE`, `ARTISTGENRE`, `ALBUMGENRE` and `ALBUMARTISTGENRE` -
through a deterministic priority tree, so the standard field matches the
hierarchy the rest of the library uses.

```bash
audiosuite genre-sync <directory> [--dry] [--json]
```

**Examples:**

```bash
audiosuite genre-sync "D:\Music\Library" --dry
audiosuite genre-sync "D:\Music\Library"
```

### BPM Analyzer

Detect tempo and write the BPM tag. A positive estimate needs evidence: noise
fits a tempo grid, so a file whose onset envelope has no periodicity at the
detected tempo is reported as a skip instead of being tagged with a fabricated
number. `--bpm-min` / `--bpm-max` choose between octave readings - they never
edit a measured tempo, and an out-of-band tempo is reported as measured.

```bash
audiosuite bpm <directory> [--bpm-min N] [--bpm-max N] [--duration SEC] [OPTIONS]
```

**Options:**

- `--bpm-min N` — lower bound for choosing between octave readings (default: 75)
- `--bpm-max N` — upper bound for choosing between octave readings (default: 175)
- `--duration SEC` — seconds of audio analysed (default: 30)

**Examples:**

```bash
audiosuite bpm "D:\Music\Library" --dry --json
audiosuite bpm "D:\Music\Library" --bpm-min 60 --bpm-max 200
```

### Tempo Analyzer

Derive a human-readable tempo marking from the BPM tag that BPM Analyzer
wrote. It performs no analysis of its own: with no BPM tag there is nothing to
convert, and the file is skipped.

```bash
audiosuite tempo <directory> [--scheme NAME] [--dry] [--json]
```

**Options:**

- `--scheme NAME` — tempo naming scheme, e.g. `Italian`, `House`, `Fast Run` (default: Italian)

**Examples:**

```bash
audiosuite tempo "D:\Music\Library" --dry
audiosuite tempo "D:\Music\Library" --scheme Italian --live --json
```

### Key Detector

Detect musical key from a chromagram and write it in each format's native tag
(`TKEY` for MP3/WAV/AIFF, `initialkey` for FLAC/OGG/Opus, the `initialkey`
atom for M4A/MP4).

```bash
audiosuite key <directory> [--duration SEC] [OPTIONS]
```

**Options:**

- `--duration SEC` — seconds of audio analysed (default: 30)

**Examples:**

```bash
audiosuite key "D:\Music\Library" --dry --json
audiosuite key "D:\Music\Library" --live --duration 60
```

### Mood Analyzer

Estimate mood from the audio signal itself - valence and arousal - and tag it.
Nothing is read from other tags, so this runs independently of the rest of the
chain.

```bash
audiosuite mood-analyzer <directory> [--duration SEC] [OPTIONS]
```

**Options:**

- `--duration SEC` — seconds of audio analysed (default: 90)

**Examples:**

```bash
audiosuite mood-analyzer "D:\Music\Album" --dry
audiosuite mood-analyzer "D:\Music\Album" --live --json
```

### Album Art Sync

Fetch and embed album artwork from multiple sources (MusicBrainz, Fanart.tv,
Deezer, iTunes). Candidates are filtered by album-name fuzzy matching and
quality-ranked by resolution, and the best match is embedded without user
interaction.

```bash
audiosuite album-art <directory> [--embed-size N] [--min-dimension N]
    [--match-threshold F] [--purge/--no-purge] [OPTIONS]
```

**Options:**

- `--embed-size N` — Embedded resolution in pixels (default: 800)
- `--min-dimension N` — smallest acceptable candidate dimension in pixels; smaller images are rejected (default: 500)
- `--match-threshold F` — album-name fuzzy-match threshold, 0.0–1.0 (default: 0.85)
- `--purge` / `--no-purge` — Purge hidden thumbnail files (default: purge)

**Examples:**

```bash
audiosuite album-art "D:\Music\Beatles" --embed-size 1200 --no-purge
audiosuite album-art "D:\Music\Beatles" --dry
```

### Lyrics Manager

Fetch synced lyrics from a remote source and embed them into audio files.
Files are matched to the lyric source by their artist and title tags; files
whose tags are missing or contain "Unknown" are skipped.

```bash
audiosuite lyrics <directory> [--provider NAME] [--request-timeout SEC]
                   [--skip-existing/--no-skip-existing]
                   [--plain-fallback/--no-plain-fallback] [OPTIONS]
```

**Options:**

- `--provider NAME` — lyric source: `lrclib` or `sidecar` (default: lrclib)
- `--request-timeout SEC` — per-request timeout in seconds (default: 10.0)
- `--skip-existing` / `--no-skip-existing` — Skip files that already contain lyrics (default: skip-existing)
- `--plain-fallback` / `--no-plain-fallback` — Store unsynced lyrics when no synced lyrics are available (default: plain-fallback)

Synced lyrics are embedded as an ID3 `SYLT` frame for MP3/WAV/AIFF and in the
`SYNCEDLYRICS` Vorbis comment for FLAC/OGG/Opus. Unsynced lyrics (the fallback)
use `USLT` for MP3/WAV/AIFF, `LYRICS` for FLAC/OGG/Opus and `©lyr` for
M4A/MP4. Each run records a batch in the undo log so tags can be reverted.

**Examples:**

```bash
audiosuite lyrics "D:\Music\Unknown-Arm"
audiosuite lyrics "D:\Music\Unknown-Arm" --live --parallel --workers 8
audiosuite lyrics "D:\Music\Unknown-Arm" --provider sidecar --json
```

## REFINERY command

### Audio Refinery

Run the single-pass Refinery pipeline. Stages are selected with the
`--stages` comma-separated list (order is fixed), and each stage's own tool is
also available standalone - `declick`, `silence-trim`, `reduce`, `enhance` and
`normalise` below run exactly the same processors.

```bash
audiosuite refine <directory> [--stages LIST] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Simulate the selected stages and report, or write the results (default: live)
- `--stages LIST` — Comma-separated stages to run: `declick`, `trim`, `reduce_noise`, `enhance`, `normalise` (default: declick,trim,enhance,normalise)
- `--output DIR` — Output directory (default: source dir)
- `--sensitivity F` — Declick sensitivity (default: 0.31)
- `--width N` — Declick max defect width in ms (default: 2)
- `--threshold DB` — Trim silence threshold dBFS (default: -50)
- `--fade` / `--no-fade` — Apply fade in/out during the trim stage (default: no-fade)
- `--fade-in MS` — Fade-in length (default: 500)
- `--fade-out MS` — Fade-out length (default: 1000)
- `--reduce-hum` — Enable hum removal via notch filtering
- `--hum-frequency [50|60]` — Mains frequency in Hz (default: 60)
- `--hum-harmonics N` — Harmonics to filter, 1–20 (default: 8)
- `--hum-quality Q` — Notch Q factor, 1–100 (default: 30)
- `--reduce-broadband` — Enable broadband noise reduction
- `--noise-start MS` — Noise profile start in ms (default: 0)
- `--noise-end MS` — Noise profile end in ms (default: 500)
- `--gate-threshold DB` — Gate threshold above the noise floor in dB (default: 3.0)
- `--preset NAME` — Enhancement preset: Mild, Moderate, Aggressive, Custom (default: Moderate)
- `--karaoke` / `--no-karaoke` — Remove centre-panned content (lead vocals) (default: no-karaoke)
- `--karaoke-strength F` — Karaoke removal strength, 0.0–1.0 (default: 1.0)
- `--reverse` — Reverse the audio (default: off)
- `--phaser` — Apply a phaser effect (default: off)
- `--flanger` — Apply a flanger effect (default: off)
- `--chorus` — Apply a chorus effect (default: off)
- `--target-lufs LUFS` — Normalisation target, one of `-12`, `-14`, `-16`, `-18`, `-23` (default: -16.0)
- `--tolerance DB` — Normalisation tolerance (default: 0.5)

**Examples:**

```bash
audiosuite refine "D:\Music" --stages declick,trim,reduce_noise,enhance,normalise
audiosuite refine "D:\Music" --stages reduce_noise --reduce-hum --hum-frequency 50 --dry
audiosuite refine "D:\Music" --stages trim,normalise --fade --fade-in 250
```

## UTIL commands

Conversion, extraction, ripping, single-purpose audio processing and library
maintenance. The audio-altering commands here are the standalone forms of the
Refinery stages, plus tools the pipeline does not contain.

### Music Format Converter

Convert audio files between formats, with format-specific quality, sample rate
and bit depth.

```bash
audiosuite convert <directory> [--format FMT] [--quality Q] [--sample-rate HZ]
    [--bit-depth BITS] [--output-dir DIR] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — List the files that would be converted, or convert them (default: live)
- `--format FMT` — output format (default: flac)
- `--quality Q` — `highest`, `high`, `medium`, `low`, or a numeric 0–10 (default: highest)
- `--sample-rate [source|44100|48000|88200|96000|176400|192000]` — output sample rate; `source` keeps the input's rate (default: source)
- `--bit-depth [auto|16|24|32|float]` — bit depth for WAV output; `auto` preserves the source depth (default: auto)
- `--output-dir DIR` — output directory
- `--normalize-mp3` / `--no-normalize-mp3` — losslessly adjust MP3 output to a target loudness (default: off)
- `--target-lufs LUFS` — target integrated loudness when `--normalize-mp3` is set (default: -16.0)
- `--delete-originals` / `--keep-originals` — remove the source file after a successful conversion (default: keep)
- `--dither` / `--no-dither` — TPDF dither when the output depth is lower than the source, WAV/AIFF only (default: on)
- `--preset NAME` — load settings from a saved preset

**Examples:**

```bash
audiosuite convert "D:\Music\WAV" --format flac --output-dir "D:\Music\FLAC" --dry
audiosuite convert "D:\Music\FLAC" --format mp3 --quality high --normalize-mp3
audiosuite convert "D:\Music\WAV" --format flac --bit-depth 24 --sample-rate 96000 --json
```

### ASX Playlist Extractor

Extract audio files from ASX playlists.

```bash
audiosuite asx-extract <directory> [--dry] [--json]
```

**Examples:**

```bash
audiosuite asx-extract "D:\Playlists" --dry
audiosuite asx-extract "D:\Playlists" --json
```

### Album Art Normalizer

Normalise embedded album artwork - resize it to one consistent dimension - in
MP3, FLAC, OGG, Opus, M4A, MP4, WAV, AIFF and AIF files.

```bash
audiosuite artnormalize <directory> [--size N] [--dry] [--json]
```

**Options:**

- `--size N` — embedded image size in pixels (default: 800)

**Examples:**

```bash
audiosuite artnormalize "D:\Music\Library" --size 1000 --dry
audiosuite artnormalize "D:\Music\Library" --json
```

### CD Ripper

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
- `--verify [off|twice|accuraterip]` — Track verification: `twice` re-reads each track and compares, `accuraterip` additionally cross-checks against the AccurateRip database, `off` disables verification (default: twice). Per-track outcomes are reported with EAC's wording - `Accurate (confidence N)` for a database match, `Rip-twice verified` for the local check, `Not in database`, `Unavailable (offline)`, or `Not accurate` (which is never written). A failed track can be re-ripped from the Results tab; nothing is retried automatically
- `--detect-read-offset` — Measure the drive's read offset against the AccurateRip database using the inserted CD and persist it for the drive; applied automatically to future rips. Needs a multi-track disc present in the database and network access; exits non-zero and persists nothing on failure

**Examples:**

```bash
audiosuite cd-rip D: --output-dir /output/flac --format flac
audiosuite cd-rip D: --output-dir /output/mp3 --format mp3 --tracks 1,2,3
audiosuite cd-rip D: --output-dir /output/flac --cue
audiosuite cd-rip D: --output-dir /output/flac --verify accuraterip
audiosuite cd-rip D: --detect-read-offset
```

### Mood Analysis Batch Tagger

Recursively analyse and tag mood from the audio signal itself, for a whole
library tree rather than one album. The same analysis as Mood Analyzer, with
the recursion and batch reporting the batch tools share.

```bash
audiosuite mood-analysis-batch <directory> [--duration SEC] [OPTIONS]
```

**Options:**

- `--duration SEC` — seconds of audio analysed per file (default: 90)

**Examples:**

```bash
audiosuite mood-analysis-batch "D:\Music" --dry --json
audiosuite mood-analysis-batch "D:\Music" --parallel --workers 8
```

### Noise Reduction

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
- `--gate-threshold DB` — Gate threshold above the noise floor in dB (default: 3.0)

**Examples:**

```bash
audiosuite reduce "D:\Music" --reduce-hum --hum-frequency 50
audiosuite reduce "D:\Music" --reduce-broadband --dry --json
```

### Audio Enhancer

Improve dynamic range and clarity with the seven-stage DSP chain (noise gate,
EQ, presence peak, output gain and more), either from a preset or the Custom
settings the GUI editor stores.

```bash
audiosuite enhance <directory> --output-dir DIR [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Analyse the files and report, or write the enhanced copies (default: live)
- `--output-dir DIR` — Destination folder (required: the enhancer writes a new file rather than overwriting the source)
- `--preset NAME` — Enhancement preset: Mild, Moderate, Aggressive, Custom (default: Moderate)
- `--karaoke` / `--no-karaoke` — Remove centre-panned content (lead vocals) (default: no-karaoke)
- `--karaoke-strength F` — Karaoke removal strength, 0.0–1.0 (default: 1.0)
- `--reverse` — Reverse the audio (default: off)
- `--phaser` — Apply a phaser effect (default: off)
- `--flanger` — Apply a flanger effect (default: off)
- `--chorus` — Apply a chorus effect (default: off)

**Examples:**

```bash
audiosuite enhance "D:\Music\Dull" --output-dir "D:\Music\Enhanced" --preset Moderate --dry
audiosuite enhance "D:\Music\Dull" --output-dir "D:\Music\Enhanced" --preset Aggressive --json
```

### Audio Normalizer

Normalise audio loudness to a target LUFS level.

```bash
audiosuite normalise <directory> [--target-lufs LUFS] [--tolerance DB] [--tp DBTP] [--lra LU] [--mode MODE] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Measure and report only, or rewrite the audio at the target loudness (default: live)
- `--target-lufs LUFS` — target loudness, one of `-12`, `-14`, `-16`, `-18`, `-23` (default: -14)
- `--tolerance DB` — acceptable deviation in LUFS (default: 0.5)
- `--tp DBTP` — true-peak ceiling for the loudnorm filter, from -9.0 to 0.0 (default: -1.5); a ceiling above -1.0 can clip on a lossy re-encode
- `--lra LU` — target loudness range for the loudnorm filter, from 1 to 20 (default: 11)
- `--mode [normalise|lossless]` — `normalise` re-encodes through FFmpeg's loudnorm filter; `lossless` adjusts an MP3's global-gain header in place and falls back to `normalise` for other formats (default: normalise)

**Examples:**

```bash
audiosuite normalise "D:\Music\Album" --target-lufs -16 --dry
audiosuite normalise "D:\Music\Album" --mode lossless --json
```

### Pop & Click Remover

Remove clicks and pops from audio files with the same windowed detector the
Refinery's declick stage uses.

```bash
audiosuite declick <directory> [--sensitivity F] [--max-width MS] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Report the detected clicks only, or repair the audio (default: live)
- `--sensitivity F` — click detection sensitivity (default: 0.25)
- `--max-width MS` — maximum click width in milliseconds (default: 5)

**Examples:**

```bash
audiosuite declick "D:\Music\Vinyl" --dry
audiosuite declick "D:\Music\Vinyl" --sensitivity 0.31 --max-width 2
```

### Restoration (Declip)

Reconstruct the flat-topped peaks a clipped recording lost, by interpolating
through the clean samples either side of each plateau. A file with nothing to
repair is skipped and not rewritten.

```bash
audiosuite declip <directory> [--threshold F] [--max-run-ms MS] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Report the files that would be repaired only, or write the repairs (default: live)
- `--threshold F` — fraction of the file's own peak that counts as clipped, 0.0-1.0 (default: 0.98)
- `--max-run-ms MS` — longest flat top to reconstruct, in milliseconds (default: 50)

A threshold outside 0-1 or a width below 1 ms is refused as a usage error. A
threshold close to 1.0 only considers samples at the very top of the file, which
is how a limiter ceiling below full scale is still found.

**Examples:**

```bash
audiosuite declip "D:\Music\Loud" --dry
audiosuite declip "D:\Music\Loud" --live --threshold 0.95 --max-run-ms 20
```

### Duplicate Finder

Find the files that are the same recording by comparing audio fingerprints, and
move the extra copies into a quarantine folder. Nothing is deleted, and the
kept copy is never written.

```bash
audiosuite duplicates <directory> [--threshold F] [--quarantine-dir DIR] [--cache PATH] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Report the duplicate groups only, or move the extra copies (default: live)
- `--threshold F` — maximum bit-error rate for two fingerprints to count as one recording (default: 0.1)
- `--quarantine-dir DIR` — where a live run moves duplicates; defaults to a `duplicate_quarantine` folder inside the scanned directory
- `--cache PATH` — the fingerprint cache file; defaults to `duplicate_cache.db` in the suite's cache directory

Nothing is deleted: a live run moves the non-keepers and records each move in the
suite's undo history, so the whole run is reversible. The JSON payload adds
`groups`, `duplicates` and `quarantined` to the shared counters.

**Examples:**

```bash
audiosuite duplicates "D:\Music" --dry
audiosuite duplicates "D:\Music" --live --quarantine-dir "D:\Quarantine"
audiosuite duplicates "D:\Music" --dry --threshold 0.08 --json
```

### Tag Field Updater

Scan and update tag fields - by default replacing a bare `/` in a tag value
with `; ` - and record an undo batch so the whole run can be reverted.

```bash
audiosuite tag-update <directory> [--no-plugin-tags] [--dry] [--json] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Compute and report the rewrites only, or write them (default: live)
- `--no-plugin-tags` — skip tag processors contributed by enabled plugins (default: plugins run)
- `--pattern TEXT` — filename pattern tried in order, repeatable; using one switches to the filename source
- `--action-group NAME` — load a named pattern set saved in the suite config
- `--save-action-group NAME` — save this run's patterns under this name
- `--list-action-groups` — list the saved action groups and exit
- `--only-fill-blanks` / `--overwrite` — keep a tag that already has a value (default), or replace it

With `--dry` the rewrites are computed and reported but nothing is written: no
file is saved and no undo record is created. With a filename pattern the run is
a dry run unless `--live` is passed, and it prints the parsed fields for every
file so a mis-parse is visible before it is written.

**Examples:**

```bash
audiosuite tag-update "D:\Music" --dry
audiosuite tag-update "D:\Music" --live
audiosuite tag-update "D:\Music" --no-plugin-tags --json
audiosuite tag-update "D:\Music" --pattern "%track%. %artist% - %title%" --dry
audiosuite tag-update "D:\Music" --pattern "%artist% - %title%" --live
audiosuite tag-update "D:\Music" --action-group Bandcamp --live
audiosuite tag-update "D:\Music" --list-action-groups
```

### Silence Trimmer

Trim leading and trailing silence, optionally applying fades.

```bash
audiosuite silence-trim <directory> [--threshold DB] [--fade/--no-fade] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — Report what would be trimmed, or write the trimmed audio (default: live)
- `--threshold DB` — silence threshold in dBFS (default: -50)
- `--fade` / `--no-fade` — apply fade in/out (default: no-fade)
- `--fade-in MS` — fade-in length (default: 25)
- `--fade-out MS` — fade-out length (default: 25)

**Examples:**

```bash
audiosuite silence-trim "D:\Music\Album" --dry
audiosuite silence-trim "D:\Music\Album" --fade --fade-in 100 --fade-out 250
```

### Tag Editor

Edit common tag fields, or import a CSV of per-file edits. Single-file mode
writes one field; CSV mode takes a library directory and applies the edits the
CSV records.

```bash
audiosuite tag-edit PATH --field FIELD --value TEXT [--dry] [--json]
audiosuite tag-edit DIRECTORY --csv EDITS.csv [--dry] [--json]
```

**Options:**

- `--dry` / `--live` — Preview the edit, or write it (default: live)
- `--field [title|artist|album|album_artist|track|year|genre|comment]` — field to write in single-file mode
- `--value TEXT` — new field value
- `--clear` — remove the field instead of setting it
- `--csv PATH` — import a CSV of per-file edits; the command's path argument must then be a library directory

**Examples:**

```bash
audiosuite tag-edit /Music/track.mp3 --field title --value "New Title"
audiosuite tag-edit /Music/track.mp3 --field comment --clear --dry
audiosuite tag-edit /Music --csv /Music/edits.csv --dry
```

### Stem Separator

Separate audio files into vocals, drums, bass and other stems with Demucs, an
optional extra installed by `uv sync --extra ml`.

```bash
audiosuite stems <directory> --output-dir DIR [--model NAME] [--stems LIST] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — List the stems that would be written, or run the separation (default: live)
- `--output-dir DIR` — directory the per-track stem folders are written into
- `--model [htdemucs|htdemucs_ft]` — Demucs model (default: htdemucs)
- `--stems LIST` — comma-separated stems to export (default: vocals,drums,bass,other)
- `--mix` / `--no-mix` — also write `mix.wav`, the sum of the exported stems (default: no-mix)
- `--device [auto|cpu|cuda]` — compute device; `auto` uses CUDA when torch reports it usable (default: auto)

**Examples:**

```bash
audiosuite stems "D:\Music\Album" --output-dir "D:\Music\Stems" --dry
audiosuite stems "D:\Music\Album" --output-dir "D:\Music\Stems" --model htdemucs_ft --mix
```

### Library Statistics Dashboard

Scan a library and report aggregate tag statistics. Read-only: no tag and no
audio byte is ever written.

```bash
audiosuite stats <directory> [--incremental/--full] [--refresh] [OPTIONS]
```

**Options:**

- `--incremental` / `--full` — incremental scan using the SQLite cache, which re-reads only changed files (default: full walk)
- `--refresh` — full re-scan that rebuilds the cache from scratch
- `--export-csv PATH` — write per-file metadata as a CSV spreadsheet
- `--export-json PATH` — write the full report as a JSON file
- `--export [m3u|csv|html]` — export the scan as a playlist, a column-aware CSV, or a self-contained HTML page (default: no export)
- `--export-path PATH` — where `--export` writes; defaults to `<folder>_library.<ext>` beside the scanned folder
- `--export-columns NAMES` — comma-separated columns for a csv/html export (path, format, artist, title, album, album_artist, track, disc, year, genre, bpm, key, camelot, mood, tempo_marking, duration)
- `--camelot` — add the Camelot key column to the CSV/HTML export (appends to the original CSV columns; not valid with m3u)
- `--completeness` — also report tag completeness for BPM, key, genre, mood, artwork and ReplayGain
- `--detail [title|artist|album|track_number|year|bpm|key|genre|mood|tempo_marking|album_art|replaygain]` — with `--completeness`, list the files missing the given tag
- `--trend` — show the recorded completeness trend for this directory
- `--history-limit N` — snapshots to show with `--trend` (default: 12)
- `--no-history` — do not record this run's completeness snapshot
- `--no-plugin-analysis` — skip analysis contributions from enabled plugins

**Examples:**

```bash
audiosuite stats "D:\Music" --completeness
audiosuite stats "D:\Music" --incremental --completeness --detail bpm --json
audiosuite stats "D:\Music" --trend --history-limit 6
audiosuite stats "D:\Music" --export-csv "D:\Reports\library.csv" --json
audiosuite stats "D:\Music" --export m3u --export-path "D:\Music\mix.m3u"
audiosuite stats "D:\Music" --export csv --export-columns path,artist,title,camelot
audiosuite stats "D:\Music" --export html --camelot
```

### Spectral Viewer

Render FFT spectrograms for one file or a whole directory. Read-only with
respect to the audio: nothing is retagged or re-encoded, and the only files
written are PNG images. `--dry` lists the images it would write and writes
none of them.

```bash
audiosuite spectrogram PATH [--output-dir DIR] [OPTIONS]
```

**Options:**

- `--dry` / `--live` — List the images that would be written, or render them (default: live)
- `--output-dir DIR` — directory for the PNGs (default: beside each source file)
- `--n-fft N` — FFT window size in samples (default: 2048)
- `--hop-length N` — samples between successive frames (default: 512)
- `--start SEC` — window start in seconds (default: 0.0)
- `--end SEC` — window end in seconds; `0` runs to the end, capped at 600 seconds (default: 0.0)
- `--max-freq HZ` — highest frequency to show; `0` is Nyquist (default: 0.0)
- `--db-range DB` — colour floor in dB below the peak (default: 80.0)
- `--cmap NAME` — matplotlib colour map (default: magma)

**Examples:**

```bash
audiosuite spectrogram "D:\Music\Album\01 Track.flac" --dry
audiosuite spectrogram "D:\Music\Album" --output-dir "D:\Spectrograms"
audiosuite spectrogram "D:\Music\Album" --start 30 --end 60 --max-freq 12000 --cmap viridis
```

### ML Denoiser

Neural noise reduction with RNNoise, an optional extra installed by
`uv sync --extra ml`. The model is trained on speech, so for music
`--amount` blends the source back in rather than replacing it.

```bash
audiosuite denoise <directory> [--amount PCT] [--dry] [--json]
```

**Options:**

- `--dry` / `--live` — Report the measured levels only, or write the processed audio (default: live)
- `--amount PCT` — how much of the model's output to keep, 1–100 %; lower values blend the source back in, which suits music (default: 100.0)

**Examples:**

```bash
audiosuite denoise "D:\Music\Interviews" --dry
audiosuite denoise "D:\Music\Live" --amount 40 --json
```

### Tag-Based File Reorganizer

Move or copy audio files into a folder hierarchy built from their tags.

```bash
audiosuite reorganize <directory> --output-dir DIR [--action copy|move] [OPTIONS]
```

**Options:**

- `--output-dir DIR` — destination directory
- `--action [copy|move]` — defaults to the saved configuration, or `copy` when none is saved
- `--specific-pattern PATTERN` — folder pattern for specific-artist albums
- `--various-pattern PATTERN` — folder pattern for Various Artists albums

**Examples:**

```bash
audiosuite reorganize "D:\Music\Unsorted" --output-dir "D:\Music\Sorted" --dry
audiosuite reorganize "D:\Music\Unsorted" --output-dir "D:\Music\Sorted" --action move --json
```

### Undo Tag Edits

Undo Tag Edits restores the tags a batch run changed. It has its own window
(`Undo_Tag_Edits.pyw`) and a CLI in `utilities/undo.py`, not an `audiosuite`
sub-command, because it operates on the shared undo database rather than on a
directory of audio:

```bash
python utilities/undo.py list [--limit N]
python utilities/undo.py show <batch_id>
python utilities/undo.py undo <batch_id>
```

See *Undo Batch* at the end of this reference for the batch model and the
`--db` option.

## Suite commands

### doctor

Check that the installation maps every package in the checkout. It reports the
installed and checkout versions, how many first-party packages resolve from
this checkout, every CLI command a stale install would take down, the
interpreter a launcher would run under, and whether each optional extra
(Demucs, RNNoise) imports there. It takes no directory and exits 1 when the
install is wrong.

```bash
audiosuite doctor [--json]
```

**Examples:**

```bash
audiosuite doctor
audiosuite doctor --json
```

### plugins

Inspect and enable third-party plugins discovered under `plugins/`. Discovery
reads each `MANIFEST.toml` without importing plugin code, so a broken plugin
cannot take down `audiosuite --help`; enablement is stored in the shared
`audio_suite_config.json`.

```bash
audiosuite plugins list [--json]
audiosuite plugins enable PLUGIN_ID [--json]
audiosuite plugins disable PLUGIN_ID [--json]
```

**Examples:**

```bash
audiosuite plugins list
audiosuite plugins enable example_plugin
audiosuite plugins disable example_plugin --json
```

`audiosuite example` is the bundled example plugin's own command (count the
audio files in a folder and report the tags they carry); it exists only while
that plugin is enabled.

## CUE sheet commands

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

## All Commands

Every command the CLI ships, including the suite commands that operate on the
installation rather than on a folder of audio. Each of the 32 tools appears
here, and each tool's own section above documents its flags.

| Command | Tool | Category |
|---|---|---|
| `album-art` | Album Art Sync | Enrich |
| `album-genre` | Album Genre Tagger | Enrich |
| `artnormalize` | Album Art Normalizer | Util |
| `asx-extract` | ASX Playlist Extractor | Util |
| `declip` | Restoration (Declip) | Util |
| `duplicates` | Duplicate Finder | Util |
| `bpm` | BPM Analyzer | Enrich |
| `cd-rip` | CD Ripper | Util |
| `convert` | Music Format Converter | Util |
| `cue generate` | CUE sheet generator | Suite |
| `cue parse` | CUE sheet parser | Suite |
| `cue split` | CUE sheet splitter | Suite |
| `declick` | Pop & Click Remover | Util |
| `denoise` | ML Denoiser | Util |
| `doctor` | Install check | Suite |
| `enhance` | Audio Enhancer | Util |
| `example` | Example Tool (plugin) | Plugin |
| `fingerprint` | Audio Fingerprinter | Enrich |
| `genre-sync` | Genre Sync | Enrich |
| `key` | Key Detector | Enrich |
| `lyrics` | Lyrics Manager | Enrich |
| `mood-analysis-batch` | Mood Analysis Batch Tagger | Util |
| `mood-analyzer` | Mood Analyzer | Enrich |
| `normalise` | Audio Normalizer | Util |
| `plugins disable` | Plugin manager | Suite |
| `plugins enable` | Plugin manager | Suite |
| `plugins list` | Plugin manager | Suite |
| `reduce` | Noise Reduction | Util |
| `refine` | Audio Refinery | Refinery |
| `reorganize` | Tag-Based File Reorganizer | Util |
| `replaygain` | ReplayGain Analyzer | Enrich |
| `scrub` | Metadata Scrubber | Enrich |
| `silence-trim` | Silence Trimmer | Util |
| `spectrogram` | Spectral Viewer | Util |
| `stats` | Library Statistics Dashboard | Util |
| `stems` | Stem Separator | Util |
| `tag-edit` | Tag Editor | Util |
| `tag-update` | Tag Field Updater | Util |
| `tempo` | Tempo Analyzer | Enrich |

Undo Tag Edits is the one tool without a row: it operates on the shared undo
database through `utilities/undo.py`, documented under *Undo Batch*.

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
