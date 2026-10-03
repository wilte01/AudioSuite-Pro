# Changelog

All notable changes to AudioSuite-Pro are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions of the tools are released together with the suite (the single
`version` in `pyproject.toml` covers the whole distribution).

## [Unreleased]

Everything below landed after `1.0.0` and is not yet versioned. The items are
grouped Keep-a-Changelog style and worded against the behaviour actually
shipped; the per-item evidence lives in `PLAN_iteration7_remediation.md` (the
bulk of the work) and `PLAN_iteration8_remediation.md`.

### Added

- **MusicBrainz identifier writing** (Audio Fingerprinter, opt-in). Selected
  AcoustID candidates can now have their MusicBrainz IDs written to the file:
  `TRACKID`/`ARTISTID` whenever a candidate reports them, and `ALBUMID` only
  when exactly one release survives the release-criteria filter. The writer
  refuses to guess — a criterion that would empty the set is ignored rather
  than fabricated. Enable with `--write-mbids` on the CLI, the Fingerprinter's
  toggle in the GUI, or the Master Driver card; `--write-mbids` is refused
  unless tag writing itself is enabled. Values are written as ID3 `TXXX`,
  Vorbis comment, and `----:com.apple.iTunes:`, so Picard round-trips them.
- **Cover Art Archive as the first album-art source** (Album Art Sync). The
  chain is now Cover Art Archive → MusicBrainz → Fanart.tv → Deezer → iTunes
  Store. CAA is queried on the file's release MBID first, then on its release
  group. Because the MBID *is* the trust evidence for CAA, album-name fuzzy
  matching is skipped for it exactly as for Fanart.tv, while dimension and
  threshold settings still forward. A CAA outage degrades to the previous chain
  rather than failing a run.
- **Recursive, mixed-format conversion** (Music Format Converter). The input
  scan now walks subdirectories and reports a per-format breakdown, and the
  output format list is the union of the targets reachable from every format
  actually found. An unreadable subdirectory is logged and skipped so its
  siblings still convert; only an unreadable *root* is fatal. Relative paths are
  mirrored under the output root, and output subdirectories are created only on
  a live write — a dry run leaves no directories behind.
- **Read-side MusicBrainz tag helpers.** `read_musicbrainz_ids` and
  `read_disc_number` let other tools consume the identifiers the writer produces
  across MP3, FLAC/Vorbis, MP4 and IFF-ID3.

### Changed

- **Bit-depth reduction is dithered by default, and sample-rate conversion uses
  `soxr`** (Music Format Converter). Any conversion that reduces integer PCM
  depth (wav/aiff/aif) now applies TPDF *triangular* dither automatically, and
  every sample-rate conversion uses the `soxr` resampler. **This changes the bytes
  of every converted file**, so previously converted output is not
  byte-reproducible by the new code path.
  *Migration:* if a workflow depends on the exact previous output — an existing
  undo snapshot compared against a fresh conversion, or a checksum over
  converted files — re-run the workflow from the pre-conversion originals
  rather than from a previously converted copy. The run log records the dither
  decision on every batch.
  *Opt-out:* `--no-dither` on the CLI, or unchecking "Apply TPDF dither when
  reducing bit depth (WAV/AIFF)" in the GUI (checked by default). The setting is
  saved with conversion presets. With dither off, the command line is reproduced
  byte-for-byte at source rate, matching pre-change behaviour.
- **User-guide tree is generator-only.** Every shipped
  `*_User_Guide.docx` is now reproducible from a committed `generate_guide.py`,
  and the superseded per-tool logging guides (with their generator) are gone —
  the per-tool "Log Files" section of each user guide and the in-app log files
  replace them. `README.md` gains an "Engineering standards" section.
- **Shared GUI and CLI scaffolding.** The analysis setup frame, the tag-tool
  application base, the Master Driver card shell and the CLI argument ladder are
  single shared implementations, so eight analysis/tag tools and eight driver
  cards are now shell-identical and their option labels, help text and button
  captions are generated from one declaration each. No user-facing option,
  caption or shortcut changed.

### Fixed

- **`tag_field_updater --dry` wrote tags anyway.** The flag was accepted and
  displayed but the write site was not gated on it, so a Dry Run silently
  modified files. Tag writes are now genuinely withheld in Dry Run.
  `--dry-run` was never a real spelling and remains undocumented; the supported
  spelling is `--dry`.
- **CD ripper CUE sheets named one file for the whole album.** `_write_rip_cue`
  emitted a single `FILE` entry covering every track, so a cue sheet pointed at
  the wrong audio after ripping. Each track now gets its own `FILE` entry, with
  correct per-track offsets.
- **Album Art Sync and Album Genre Tagger touched Tk from worker threads.** Both
  apps mutated widgets off the main thread, which Tk does not support. All such
  calls are now marshalled onto the main thread with `after(0, ...)`.
- **Master Driver read live Tk variables on the launcher thread.** The emitted
  command line — including the Live/Dry token — was re-derived from widget state
  *after* the worker thread started, so an edit made while a batch was launching
  could change the mode of the run in flight. The full argument vector is now
  built on the main thread before the thread starts.
- **`audiosuite artnormalize` raised `TypeError` and did nothing.** The unified
  CLI's `slot_queue` argument was not absorbed by the normalization entry point.
- **Several swallowed errors are now recorded.** A failed error dialog in the
  File Reorganizer / Tag Field Updater launchers, a corrupt embedded cover-art
  frame in the recursive resize utility, and an undecodable legacy row in the
  undo history were each skipped with no diagnostic. The behaviour in those
  cases is unchanged — a corrupt frame is still resized, a legacy row is still
  skipped — but each now leaves a log record naming what was skipped and why.
- The portable-core CLI test reads its JSON payload from stdout only, so the
  `audiosuite --json` contract (payload on stdout, diagnostics on stderr) is now
  pinned by the suite.

### Removed

- Per-tool `*_Logging_Guide.docx` files and `generate_logging_guide.py`
  (superseded — see *Changed*).
- The tracked `*.bak` guide backups (regenerate from the generator instead).

## [1.0.0] - 2026-09-26

First recorded baseline. Package metadata, releases, and this changelog start
here; earlier history is in the repository's `PLAN_*.md` audit records.

### Added

- Initial distribution baseline: 27 registered tools across the Enrich /
  Utility / Refinery categories, the Master Driver control panel, the
  shared `audiosuite` CLI, and the `audio_suite_shared` foundation layer.
- Baseline commit audited on 2026-09-26: 6,978 tests passing / 5 skipped,
  coverage 78.26%, `ruff` clean, `mypy --strict` clean, bandit 0 High /
  0 Medium. That audit is recorded in `PLAN_iteration5_remediation.md`, and
  its findings are remediated across that plan's staged, evidence-recorded
  work (starting with this changelog's next entries).
