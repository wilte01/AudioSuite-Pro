# Changelog

All notable changes to AudioSuite-Pro are documented in this file.

This file records what a **user** can observe: a tool's behaviour, a flag or a
default, a supported format, an error message, a workflow step, or a measured
speed or size difference. Developer-facing changes — the release gate, CI, the
tests, tooling, behaviour-neutral refactors and dependency bumps no output sees
— are recorded in [TECHNICAL_CHANGELOG.md](TECHNICAL_CHANGELOG.md) instead, so a
reader deciding whether to upgrade is not handed them in between.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions of the tools are released together with the suite (the single
`version` in `pyproject.toml` covers the whole distribution).

Each released section is grouped under `### Added`, `### Changed`,
`### Deprecated`, `### Removed`, `### Fixed` or `### Security`, in that order,
and every bullet belongs to exactly one of them.

## [Unreleased]

### Added

- **The Audio Refinery's Dynamics stage has a Setup panel.** Tick the stage,
  open Settings and set the compressor's threshold, ratio, attack, release and
  makeup gain, and the limiter's true-peak ceiling, lookahead and release. A
  value outside the range printed beside a control is reported in the panel and
  kept out of the run, and loading a preset or launching from the Master Driver
  shows the pair the run will use. SELECT ALL covers the stage.

- **The Audio Refinery has a Dynamics stage.** A controllable compressor and a
  true-peak brickwall limiter run after Parametric EQ and before Audio
  Enhancement, reachable with `refine --stages dynamics` and configured by
  `--comp-threshold`, `--comp-ratio`, `--comp-attack`, `--comp-release`,
  `--comp-makeup`, `--limiter-ceiling`, `--limiter-lookahead` and
  `--limiter-release` (any one of them selects the stage). The run log reports
  the measured maximum and mean gain reduction plus the output's integrated
  loudness and true peak. An out-of-range setting is refused before any file is
  opened, a bypassed pair leaves the file byte-identical, and copy mode refuses
  the stage because a stream copy cannot decode the audio.

- **The Refinery's EQ has its own panel and a live response curve.** The
  Parametric EQ stage opens to a band table: pick a kind, type the frequency,
  gain and Q, and Add / Update writes the band into the run; selecting a row
  loads it back for editing, and Remove deletes it. The curve under the table
  is drawn from the same filters the run renders, so it shows the shape the
  file will get, and Bypass keeps the bands while leaving the signal alone. A
  high-pass or low-pass band disables the gain and Q boxes, because the
  installed engine's first-order filters take neither, and the stage joins
  SELECT ALL on the Refine tab.

- **The Refinery can shape tone with a parametric EQ.** A run may now stack up
  to eight bands - low shelf, high shelf, peaking, high-pass or low-pass - each
  with its own frequency, gain and Q, where the enhancement presets offer only
  three fixed shelves. `refine --eq-band "peaking,1000,2.5,1.0"` (repeat the flag
  for each band) configures the rack, and `--stages eq` runs it; giving a band
  implies the stage, so a flag and a stage list cannot disagree. The rack runs
  after noise reduction and before enhancement, so the preset's compressor and
  limiter act on the shaped signal, and it round-trips through saved settings.
  A band at or above the file's Nyquist frequency is refused rather than moved,
  and a bypassed or empty rack leaves the signal bit-identical. High-pass and
  low-pass bands are first-order in the installed engine: they take no gain and
  no Q, and one that carries either is refused instead of ignored. The Setup
  tab shows the rack as a band table with a live response curve, drawn by
  measuring the filters the run applies, and a preset stores the toggle and
  every band with the rest of the settings.

- **Help ▸ Licences shows the texts that ship with the installation.** The
  Master Driver's Help menu gains a `Licences` entry that opens a read-only
  window listing the suite's own GPL-3.0 licence, the third-party notices, and
  the two bundled binaries' LGPL texts with the provenance record that says
  which upstream release each came from. The window reads them from the
  installation itself (`%LOCALAPPDATA%\AudioSuite-Pro\licenses\`) and falls
  back to `packaging/licenses/` in a source checkout, so the same entry works
  before an installer has been built. "Open in default app" hands the selected
  file to the system viewer; a copy that ships no texts says so instead of
  opening an empty window.
- **`audiosuite licences` prints the same texts headlessly.** The command prints
  each licence document with its title and its full text, and `--json`
  publishes the inventory — the folder this copy reads from plus each
  document's title, file name and character count — so a packaging script or a
  licence audit reads what a build carries without a display. Both surfaces
  read one resolver, so the CLI and Help ▸ Licences cannot disagree about what
  an installation ships. The exit status distinguishes a build that carries no
  texts (0) from one whose texts cannot be read (1).

### Changed

- **The Audio Refinery guide explains tone and dynamics in depth.** The guide
  now covers every Parametric EQ band kind, with measured Q width and shelf
  behaviour, a table of fixes by frequency, and command-line examples; and every
  Dynamics control, with measured reduction figures, how to read the run's
  max/mean reduction and output levels, starting points for four kinds of job,
  and what the stage cannot do. A new section, How the Stages Work Together,
  explains the fixed order, why EQ runs before Dynamics and Dynamics before the
  enhancer and normaliser, and walks an over-bright CD rip through the whole
  chain. Both panels are pictured opened to Settings, with the guide's example
  rack and a starting-point compressor and limiter, and the chain's complete Dry
  Run report is reproduced line by line so a reader knows what each stage will
  say before running anything, beside the report the same chain writes when run
  for real.

### Fixed

- **A Dry Run's Normalise line quotes the audio the run will normalise.** The
  preview measured the source file, so with EQ or Dynamics enabled it named a
  starting level and a planned gain the live run would never use: the same
  reference track read -15.9 LUFS in a Dry Run and -20.8 LUFS in the run that
  wrote it. The preview now measures the audio the stages produced, through a
  temporary file it removes before returning, so a Dry Run's Normalise figure
  matches the live report's and the dry run still leaves every file untouched.

- **Dry Run no longer rewrites files in the Audio Refinery.** The window's
  mode only reached its own display flag and the command line only reached the
  JSON summary, so a Dry Run processed and overwrote every file while reporting
  itself as a dry run — including a run launched from the Master Driver with Dry
  Run ticked. The mode now reaches the configuration the pipeline reads: a Dry
  Run decodes, measures and reports what each enabled stage would do, and leaves
  every file byte-identical.

- **Channel Tools waits when the Master Driver's Auto Start is off.** A launch
  that supplied a folder applied the channel rule immediately, rewriting the
  files, even though Auto Start had not been ticked. Auto Start now decides:
  with it off the window opens with the folder and rule ready and waits for
  Apply Channels, and with it on the batch starts as before.

- **The Audio Refinery accepts a run whose only stage is Parametric EQ.** Both
  the standalone window and the Master Driver's LAUNCH REFINERY answered
  "Please enable at least one Refinery stage" for an EQ-only selection,
  because their guard still listed the five stages that predate the EQ stage.

## [2.6.0] - 2026-11-11

### Added

- **Embedded artwork, extracted to a sidecar or reported missing.** A new
  `audiosuite artwork` group answers two read-side questions. `artwork extract
  <folder>` writes each file's cover beside it as `cover.jpg` or `cover.png`,
  choosing the extension from the image's own bytes so PNG data stored under an
  `image/jpeg` label is not written as a `.jpg`; an existing sidecar is kept
  untouched — bytes and timestamp — unless `--force` is passed, and
  `--recursive` covers a whole library tree. `artwork report <folder>` lists the
  files with no embedded artwork and, with `--min-bytes` or `--min-dimension`,
  the artwork larger than a threshold, changing nothing on disk. Both publish
  JSON, and a format without an artwork container (a WAV or AIFF rip, say) is a
  reported outcome rather than a failure. Library Statistics' CSV and HTML
  exports gain `has_art`, `art_bytes`, `art_width` and `art_height` columns,
  appended after the existing ones, so a spreadsheet shows which albums still
  need a cover.
- **Artwork gaps in Library Statistics, including incremental scans.** The
  Missing Data tab, the console report and the `stats --json` payload now
  report how many files have no embedded artwork, and the run report prints the
  same figure. An incremental scan answers for a library it did not reopen, so
  a repeat scan is as fast as before; a cache written by an earlier version is
  reread once to fill the fact in, rather than reporting a guess.
- **An album view that fills in missing covers.** The new Artwork Gaps tab
  lists every album with files that have no embedded artwork, worst-covered
  first. Its Extract Covers button writes a `cover.jpg` (or `cover.png`) beside
  each listed album, taken from the picture a file in that album already has,
  so a player shows a cover without any file being retagged; Dry Run reports
  the same outcome without writing, an existing sidecar is kept unless the run
  replaces it, and an album with no artwork anywhere is reported rather than
  changed. The pass writes `library_stats_artwork_log.txt` into the scanned
  folder, and the tab's View Artwork Log opens it.
- **A picture of how much of the library has covers.** The Charts tab now
  shows an Artwork Coverage panel beside its tag charts, counting the files
  that embed a cover against the rest of the library and printing the
  percentage, from the counts the scan already measured. Clicking that panel
  opens the Artwork Gaps tab, so the figure leads straight to the albums it
  counted.
- **The artwork list and chart keep up with the covers just written.** After
  a live cover pass the albums it covered leave the Artwork Gaps list and the
  Artwork Coverage figure counts their files as covered, so the dashboard
  shows the finished work without another scan; a dry run changes nothing,
  an album whose folders were only partly covered stays listed, and the next
  scan measures the files again.
- **Artwork Extractor, a window and a Master Driver batch step.** The extraction
  `audiosuite artwork extract` performs now has its own window
  (`Artwork_Extractor.pyw`): pick a folder, set the sidecar name, choose whether
  an existing sidecar may be replaced and whether sub-folders are read, then run
  live or as a dry run that writes only the report. Every run writes
  `artwork_extractor_sync_log.txt` or `artwork_extractor_dry_run_log.txt` beside
  the files it read, and View Log opens it. On the Master Driver's UTIL tab, in
  the **Tags & Artwork** section, the card carries the same three options and
  the batch schedules the window as its own step, passing the driver's folder,
  mode and Auto Start/Auto End pair; the step depends on nothing else.
- **Exact duplicate matching, by bytes or by decoded audio.** The Duplicate
  Finder answers a narrower question beside its fingerprint scan: `--exact only`
  groups files whose bytes are identical — a renamed copy, a backup — or whose
  samples decode identically even when their tags differ, and skips
  fingerprinting entirely; `--exact also` reports both kinds in one run. The
  report labels a byte-identical copy `[EXACT]` and a decoded match `[EXACT PCM]`,
  so the two claims stay distinguishable, and a file an exact group already
  names is not counted again in a fingerprint group. Matching is off by default,
  so an existing scan behaves exactly as before. Hashing decodes each file, so
  the exact modes take longer than a fingerprint scan; both hashes are cached
  beside the fingerprint. The window's **Exact matching** control, the Master
  Driver card and the batch pass the choice through, and the JSON payload adds
  `exact_groups`, `exact_duplicates` and `hashed`.
- **A CUE sheet for a folder of tracks, from a window and the command line.**
  CUE Sheet Generator (`CUE_Sheet_Generator.pyw`) describes every file in a
  folder as its own track and writes `album.cue` beside them: the track number
  comes from the file's track tag, then from a `NN - Title` filename prefix,
  then from its position; titles and performers come from the same tags, and an
  album title and artist can be set. A folder where two files claim one track
  number is refused with both filenames named, rather than written as a sheet a
  player cannot read. A dry run writes the run report and leaves an existing
  sheet alone. The window is on the Master Driver's UTIL tab and is schedulable
  as a batch step, which runs it from the driver's folder and mode through the
  same shared builder `cue generate` uses.
- **Copy tag fields from a reference file, or from a saved template.** The Tag
  Editor's Setup tab gains **Copy Fields…** (choose a reference track, say which
  fields, review the per-field diff in a dry run, then apply) and **Templates…**
  (save the selected row's values under a name, then apply one to a selection).
  The CLI does the same headlessly: `tag-edit TARGET --copy-from REF --fields
  title,artist` where `TARGET` is a file or a folder. Fields the reference does
  not carry are left alone and named in the status line; a file whose container
  cannot take a field is reported with that container's reason instead of being
  skipped silently; and one undo batch covers the whole apply.
- **A peak/true-peak target beside the loudness target.** The Refinery's
  Normalise stage can now move a file by the distance between its true peak and
  a dBTP target (`--target-mode peak --target-peak -1.0`, or the new Target row
  on the Setup tab) instead of pushing integrated loudness to a LUFS figure. One
  static gain is applied, so a track keeps its own dynamics and only its level
  moves; a file already inside the tolerance is left byte-identical, and the
  stage reports both the sample peak and the true peak it measured after the
  write. A gain that would pass full scale is held by the limiter rather than
  clamped. Peak mode reaches WAV and AIFF as well as the normalise encoders,
  keeps a 24-bit source at 24 bits, and cannot be combined with Album loudness:
  choosing one clears the other, and the command line refuses the pair.
- **The Normalise stage writes WAV and AIFF.** Loudness and album mode no longer
  refuse a PCM container: a WAV or AIFF is normalised in place, keeps its own bit
  depth (a 24-bit master stays 24-bit) and its sample rate, and album mode
  measures a PCM album like any other. A container the stage still cannot write
  is refused with a message whose format list is derived from the same table that
  decides it, so it cannot go stale.

### Changed

- **Key Detector's command line analyses the same 90 seconds as its window.**
  `audiosuite key` defaulted to a 30-second analysis while the GUI, the
  Master Driver and the argument parser used 90, so a folder read from the
  command line was analysed over a third of the audio the same run read from
  the GUI. Both now read one setting, and Mood Analyzer - already 90 - reads
  it too; `--duration` still overrides it. BPM Analyzer keeps its separately
  calibrated 30-second window.

- **BPM Analyzer analyses 30 seconds by default everywhere.** The GUI and the
  Master Driver used to start at 90 seconds while the `bpm` command used 30,
  so the same track could be tagged by one entry point and reported as having
  no discernible beat by another. The window is now one value, and it is the
  length the beat-detection floor was calibrated on: on a 120-track sample of
  a 44.1/48 kHz MP3 library, the 90-second window refused 10% of tracks that
  30 seconds analyses. A shorter window is also faster; 90 seconds and any
  other value from 10 to 300 remain available in the GUI, in the Master
  Driver and as `--duration` on the command line.

- **The Utilities tab is grouped, and it is alphabetical inside each group.**
  Nineteen cards sat in one flat list whose order was the manifest's own
  history — ties broken by name, each new tool dropped wherever a number was
  free — so the last cards moved without anyone deciding to. The tab now shows
  six captioned sections in workflow order: Convert & Import, Tags & Artwork,
  Analysis & Inspection, Repair & Processing, Organise & File Handling, then
  Plugins last (the bundled Example Tool is the plugin card). Cards are
  alphabetical inside a group, a caption always starts a fresh row, and a card
  whose Settings are open still spans the full width. The order on screen is
  still the order a sequential batch runs its steps in, so a run now follows
  the grouped list: ASX Playlist Extractor and CD Ripper before Music Format
  Converter, and Album Art Normalizer ahead of the tag tools.

- **The Enrich tab is grouped too.** Eleven cards now sit under five captions —
  Tag Cleanup, Identification, Loudness & Genre, Analysis, Artwork & Lyrics —
  instead of one flat stack. Unlike the Utilities groups, these keep their
  existing order: the enrich sequence is the order the tools support each other
  in (Tempo Analyzer reads the BPM tag BPM Analyzer writes, Album Art Sync runs
  after the tag rewrites), so grouping only adds headings and never moves a
  tool. A sequential batch therefore runs exactly what it ran before.

### Fixed

- **Re-encoding a WAV folder at a new bit depth or sample rate.**
  `convert --format wav --bit-depth 16` and the GUI's WAV bit-depth and
  sample-rate controls used to skip every WAV file as "same format". A
  same-format WAV job is now rendered when it asks for a depth or rate change:
  with a separate output folder the new file is written there, and with the
  default output folder (the input folder) the file is re-rendered in place
  through a temporary file, so the original is only replaced by a complete
  render. A same-format job with no depth or rate change still skips, and WAV
  stays selectable as an output for a WAV folder.
- **Spectrograms report levels below 80 dB instead of stopping at -80.** The
  Spectral Viewer's colour range can be set up to 140 dB, but every bin quieter
  than -80 dB used to be stored as -80, so a wider range drew a flat floor
  instead of the quiet detail it promised. A -100 dB tone now measures -98.8 dB
  (quantization and window scalloping account for the rest); the default 80 dB
  view is unchanged, and digital silence still sits at the bottom of the range.

- **BPM Analyzer's verdict no longer depends on a file's sample rate.** Audio
  was analysed at whatever rate the file was stored at, but the onset analysis
  uses a fixed hop of 512 frames and the "no discernible beat" floor was
  calibrated on 22 050 Hz clips, so a 44.1 or 48 kHz file was scored on
  half-length frames. Genuine music fell under the floor because of that alone:
  two tracks on one album were reported `[SKIP] ... no discernible beat` while
  the other six were tagged, and the same recording could be refused or tagged
  differently depending on how it was stored — `chopin_rubato_74.ogg` was
  refused at 44.1 kHz although it measures 0.124 against the 0.10 floor at
  22 050 Hz. Analysis now resamples to 22 050 Hz, so a recording's own rate no
  longer moves its verdict or its BPM: `hiphop_86.ogg` reports 86 BPM whether
  it is stored at 22.05, 44.1 or 48 kHz instead of 161 at the higher rates.
  Tempos from 44.1 and 48 kHz files can therefore differ by a beat level from
  what earlier versions tagged. Skip lines also print the measured score to
  three decimals, so a near miss can no longer read
  `onset periodicity 0.10, minimum 0.10` as though it had passed.

- **Key Detector and Mood Analyzer report the same result whatever a file's
  sample rate.** Both tools analysed at the rate the file was stored at, and
  both features they threshold depend on that grid: the key comes from a
  constant-Q chromagram whose bin mapping follows the decode rate, and the mood
  engine's beat tracking uses the same fixed 512-frame hop as BPM Analyzer. The
  same recording could therefore be tagged two ways — on one album "After
  Forever" read G at 22 050 Hz and Gm at 44.1 kHz, and "Into the Void" read C#m
  against F#, while in the test corpus `krautrock_152.ogg` read
  `Playful;Energetic;Hopeful` against `Hopeful;Warm;Playful`. Both now analyse
  at 22 050 Hz, the rate their thresholds were calibrated on. Keys and moods
  from 44.1 and 48 kHz files can therefore differ from what earlier versions
  tagged, so re-analysing a folder is worthwhile if its key tags look
  inconsistent.

- **`cue generate` numbers tracks the way it always said it did.** The
  reference and the command's own help stated that track numbers come from the
  files' tags, but only a `NN - Title` filename prefix was read, so a folder
  whose names carry no number got one sheet and a tagged album got another.
  The number is now taken from the track tag first, then from the prefix, then
  from the file's position, and a folder where two files claim the same number
  is refused with both filenames named instead of being written as a sheet a
  player cannot follow. `--json` still reports the same fields.
- **A container the Normalise stage cannot write is skipped, not failed.** An
  MP4, WMA or AAC file in a run that included Normalise used to report
  `Normalise stage failed:` with the encoder message, and the work the other
  stages had already done was thrown away with it. The file now reports a
  skipped stage naming the reason and the formats the stage writes, is left
  untouched, and every other enabled stage still runs. A Dry Run predicts the
  same skip instead of promising a normalisation the live run would refuse. The
  `[SKIP]` line also shows the reason exactly as written, so format names keep
  their capitals.
- **The Master Driver guide lists every utility.** Its Utility Tools section
  named ten of the eighteen, and filed Lyrics Manager under Utility although
  the tool belongs to Enrich. The section is now one list per group covering
  all eighteen, and Lyrics Manager appears with the Enrich tools.

## [2.5.0] - 2026-11-08

### Added

- **Join recordings into one file, with a crossfade or a gap between them.** The
  new Audio Joiner (`Audio_Joiner.pyw`, `audiosuite join`) writes a folder's
  files into one output in the order you set, and the Setup tab shows that order
  as a list you reorder, with the planned length of the result underneath. A
  crossfade blends each boundary over the length you give, equal-power so the
  middle of the fade does not dip the way a straight line does; a gap instead
  inserts silence of that length, and asking for both at once is refused with
  both settings named rather than silently picking one. The joined length is the
  segments plus the gaps minus the overlaps, and it is shown before the run
  starts. When every segment already carries the first file's codec, sample rate
  and channel count and no boundary processing is asked for, the join copies the
  audio streams instead of re-encoding it, and the run report says so; otherwise
  every segment is re-encoded to the first file's rate and channels. The output
  keeps the first segment's tags. A file name that itself contains a comma —
  `1-03 Johnny, Don't Do It.mp3`, say — is still one entry: the split is
  confirmed against the folder's own files, so the order is honoured instead of
  the name being cut at its comma. `--order` names the join order, `--output`
  names the file, and `--gap-ms` / `--crossfade-ms` / `--copy` / `--no-copy`
  set the rest; an empty `--order` joins every supported file in the folder in
  sorted order. A Dry Run reports the plan and the resulting length and writes
  nothing, and each run writes a report beside the folder it read.

- **Split recordings into tracks at their silent gaps.** The new Track Splitter
  (`Track_Splitter.pyw`, `audiosuite split`) finds the silences in a folder's
  recordings with FFmpeg's own silence detector and cuts each one into numbered
  tracks in a `split/` folder beside it, at the source's own bit depth. Three
  settings decide what counts as a gap - the shortest silence, the level that
  counts as silence, and the shortest track worth writing - and a fragment below
  that length merges into its neighbour instead of becoming a stray file. The
  cut lands halfway through the gap by default; `--boundary start` and
  `--boundary end` give the silence to the track before or after it. Leading and
  trailing silence is discarded rather than written as a track, the run report
  says how much, and a wholly silent file is refused with that reason. Each run
  also writes a CUE sheet describing the source image, so the split can be
  re-created or burned with track marks; `--no-cue` turns it off. A Dry Run
  reports the plan per file and writes nothing.

- **Every tool's guide shows the windows it describes.** All 29 tool guides
  now carry figures captured from the running program: their Setup, Processing and
  Results tabs, the CD Ripper's Rip tab, and the single-pane Spectral Viewer,
  Master Driver and Undo Tag Edits windows. Each Processing figure shows that
  tool's own run — its per-file status lines, worker slots and counters — so the
  Metadata Scrubber guide shows a scrub run and the Genre Sync guide a genre
  resolution, never another tool's output.

- **Album loudness normalisation in Audio Refinery.** The Normalise stage gains an
  **Album loudness** option and a `--album-mode` flag. When it is on the folder is
  measured once as a single album — ReplayGain's own definition of album loudness —
  and every track moves by that one gain, so the album's relative levels survive
  instead of each file being pushed to the target. A track whose peak plus that gain
  would exceed the True Peak ceiling is limited on its own: only that track's gain is
  reduced, and the run log names it. An album already within tolerance plans no gain
  and leaves every file byte-identical; a Dry Run reports the planned gain per file and
  writes nothing. Album mode uses the same encoders as per-file normalisation, so a
  container with no normalise encoder is refused with the same message. The Refinery
  guide also states the shipped target default (-14 LUFS) instead of the retired -16.

- **Exact time-range trimming in Audio Refinery.** The Trim stage gains a **Trim
  by** choice: Silence (the existing behaviour) or **Exact range**, with Start, End
  and Duration fields and matching `--trim-mode exact`, `--trim-start`,
  `--trim-end` and `--trim-duration` options. An exact range is cut from the decoded
  audio, so it is sample-accurate to the millisecond and the file is still written
  once, with its bit depth preserved. **Stream copy** (`--trim-copy`) keeps the
  source's own frames instead: nothing is re-encoded, the cut lands on the
  container's frame boundary, and the run log reports the length the copy actually
  produced together with the offset — an MP3 frame is about 26 ms, which is more
  than the range asked for. Copy mode covers MP3, FLAC, M4A/MP4, OGG and Opus and
  refuses other containers by name; it also refuses a run that enables a stage
  needing the decoded audio (declick, noise reduction, enhance or normalise)
  before the first file is opened, rather than quietly re-encoding. A range past a
  file's end fails that file with both lengths in the message, and a range flag
  without `--trim-mode exact` is refused instead of ignored.

### Fixed

- **Every legal file name is a legal input, everywhere.** The suite's filename
  check accepted only letters, digits, `_`, `-`, `.` and spaces, so it called
  names like `1-03 Johnny, Don't Do It.mp3` or `Ships Don't Disappear (Do They_).mp3`
  unsafe — names every supported operating system accepts — while the Track
  Splitter and the CUE splitter each kept their own copy of the character rules.
  There is now one declaration of the characters no filesystem can hold (the
  Windows-forbidden set plus control characters and reserved device names), and
  the splitter, the CUE splitter and the Audio Joiner all use it. Everything
  else survives: commas, apostrophes, brackets, `&`, `#`, `@`, `;`, `=` and
  non-Latin script. A splitter naming pattern and a joiner output name keep
  their punctuation, and a name the filesystem genuinely cannot hold is refused
  with the name in the message rather than failing at the write.

- **Guides show emphasis instead of asterisks.** Section references written in italics
  used to reach the Word copies as literal `*text*`; they now appear as bold text. The
  Duplicate Finder, Restoration, Tag Editor, Tag Field Updater and CLI reference pages
  are the ones that carried them.
  A guide the Help button opens therefore shows the controls, the worker slots,
  the per-file status lines and the finished summary it describes, with a
  caption beneath each figure, and the same picture renders in the Word copy as
  in the Markdown source. Each figure shows the whole window, so a control
  docked along the bottom edge — BPM Analyzer's Begin button, for one — is in
  the picture rather than cropped away.

## [2.4.3] - 2026-11-06

### Changed

- **Library Statistics Dashboard works in one window of seven tabs.** Setup
  holds the folder, the scan mode and the actions; Processing shows a scan's
  progress and status; Results appears when a scan finishes with the counters,
  the total time, View Log and Open Folder; and Summary, Charts, Missing Data
  and Completeness keep their existing content. The old Cache checkbox and
  Refresh button are now one **Mode**: Incremental Scan (the default), Full
  Scan, or Direct Scan for no cache, with Refresh still starting a full scan in
  one click. The window's title bar and the tab strip reflect the rest of the
  suite.

- **File Reorganizer works in one window of three tabs.** Setup holds the source
  directory with its Mode / Auto Start / Auto End strip, the presets, the
  destination, the Copy/Move choice and both pattern templates; the planned
  paths, a progress bar and the four counters are on Processing; a Results tab
  replaces the old completion dialog and adds View Log and Open Folder. Dry Run
  is now the Mode selector and still starts selected, so Execute stays
  read-only until you switch to Live Update. Launching it from the Master
  Driver now fills in the `--live`, `--start` and `--end` options instead of
  ignoring them, and saved presets — including ones saved before this change —
  still restore the dry-run state.

### Fixed

- **Every scan writes a report, and View Log opens it.** A scan now writes
  `library_stats_scan_log.txt` into the folder it scanned: the mode and cache
  settings, the format breakdown, the missing-tag counts and a SUMMARY block
  with the counters and timings. Before this the dashboard kept its results on
  screen and wrote no run record.

- **File Reorganizer writes a run report, and View Log opens it.** Every run
  now writes `reorganizer_dry_run_log.txt` (Preview, or Execute while Mode is
  Dry Run) or `reorganizer_sync_log.txt` (Execute in Live Update) into the
  scanned Source Music Directory: the run's settings, one line for every
  resolved path, skip or pattern error, and a SUMMARY block with the four
  counters and the elapsed time. The Results tab's View Log opens that report.
  Before this, the tool wrote no run record at all — the per-file detail only
  reached `logs/file_reorganizer.log`, the program's diagnostic log — so View
  Log answered "No log file available yet" even after a live copy.

- **The Master Driver's failure dialog says why a tool did not start.** A tool
  that refused its arguments — a source folder that no longer exists, for
  example — used to reach you as `Module failed: Library Statistics Dashboard
  (exit code 1)`, with the reason visible nowhere: the tool's own sentence went
  to a console a launched window does not have. The dialog now quotes that
  reason under the exit code (for example `Folder path does not exist:
  D:/Music/10cc`) and the tool's log records the same sentence.

## [2.4.2] - 2026-11-04

### Changed

- **WMA files are reported as unsupported by Tag Field Updater.**
  Rewriting a `.wma` file's genre fields needed an ASF tag writer the
  suite's shared tag layer does not have, so the tool now leaves the file
  untouched and reports `Unsupported format: .wma (WMA carries no tag
  writer)` instead of changing tags. WMA files stay readable and
  convertible, and no other tool's behaviour changes.

## [2.4.1] - 2026-11-04

### Added

- **WMA is now a first-class format, not a converter-only one.** Every tool
  that lists the suite's formats now finds and converts `.wma` files, which
  until now were visible only inside the Music Format Converter. Writing one
  produces a real Windows Media Audio file (wmav2 audio in an ASF container);
  tag writing is not offered yet, so a tagging tool reports the file as
  skipped rather than damaging it.

- **Raw AAC (`.aac`) is recognised as an input.** Such files are listed and
  converted; tags are not written, because raw ADTS carries no usable tag
  block. Use `.m4a` when tags matter.

### Fixed

- **Undo no longer lists a file whose tag write failed.** A tagging tool that
  could not write a file still added it to the run's undo list, so Undo offered a
  file it could do nothing for — and reverting it only rewrote the tags the file
  already had. The failed file is now reported as an error and left out of the
  undo list; files the same run did change are unaffected.

- **An unsupported target extension is refused.** Previously the shared
  export path silently wrote MP3 audio into a file named for the other
  extension, so a file could open fine while its name and its audio
  disagreed. It now reports an error instead.

## [2.4.0] - 2026-11-02

### Added

- **Duplicate Finder can now delete duplicates or replace them with a
  restorable ASX stub.** The new **On duplicate** control offers **Move to
  quarantine** (the default, unchanged), **Delete (Recycle Bin)**, and
  **Replace with an ASX stub**. Delete and stub both send the duplicate to the
  operating system's Recycle Bin - there is no permanent-delete path - and an
  interactive live run asks for confirmation first. The stub is written beside
  the duplicate, points at the kept file, and carries the duplicate's title,
  artist, album, album artist, track, disc, year, genre and comment plus its
  MusicBrainz IDs, ISRCs, lyrics and JPEG cover art. A dry run reports what it
  would do and changes nothing. The CLI gains `--on-duplicate` and the summary
  adds `deleted` and `stubbed`.

- **Delete and ASX-stub runs install Recycle Bin support automatically.** If
  the interpreter running the tool does not have `send2trash` yet, the first
  such run installs it into that interpreter, so the user is not asked to run
  a package command. If the install cannot be completed, the run stops before
  touching a file and says so.

- **ASX Playlist Extractor restores a stub's original name and tags.** Running
  it on a folder containing a suite stub recreates the removed file from the
  kept audio: the stub's stem with the keeper's extension, and the duplicate's
  tag snapshot applied after clearing the copy's inherited tags. The restore is
  built at a temporary path and renamed into place only after its tags are
  written and its audio is verified against the keeper, so a failure leaves no
  half-restored file and keeps the stub. ReplayGain, custom frames, chapters
  and PNG cover art are not carried; the guide records why.

### Changed

- **The ASX Playlist Extractor can include subfolders.** **Include subfolders**
  (or `--recursive` on the command line) finds `.asx` files below the selected
  folder as well as in it; it is off by default, so the existing top-level
  behaviour is unchanged.

### Fixed

- **An ASX playlist written with uppercase `<REF HREF="...">` is now read.**
  The parser matched only the lowercase element name, so a valid playlist from
  a Windows Media-era writer was reported `NO REF LINK IN ASX`. Element and
  attribute names are now matched case-insensitively, and a reference must
  resolve to a regular file with a supported audio extension.

## [2.3.1] - 2026-11-02

### Changed

- **The UTILITIES tab no longer offers five audio-processing cards, and REFINE
  runs that work instead.** Pop & Click Remover, Silence Trimmer, Noise
  Reduction, Audio Enhancer, and Audio Normalizer have moved out of the tab to
  REFINE's matching stages - declick, trim, reduce noise, enhance, and normalise
  - so one pipeline run covers them, with REFINE's Dry Run reporting what each
  enabled stage would detect. The five are no longer shipped separately: their
  standalone windows, their launchers and their own commands (declick,
  silence-trim, reduce, enhance, normalise) are gone, and REFINE's stages carry
  their full option sets - including the normalise stage's true-peak ceiling,
  loudness-range limit and lossless mode - so nothing needs a second window to
  be reached.

### Fixed

- **Card text and every tool's Run Controls now follow the chosen theme.** With
  Theme Mode set to Dark, or to System on a dark OS, the Parallel Processing
  checkbox in the Master Driver's BPM Analyzer card and the three option
  checkboxes in its Lyrics Manager card were black on the dark card body
  (measured 1.26:1) and are now legible. In each tool's Run Controls strip the
  driver-locked Source Music Directory value painted Tk's own light-grey box -
  light grey text on near-white, inside a dark window (2.04:1) - and a locked
  Browse button was worse still (1.13:1); a locked control now shows the suite's
  read-only surface with readable text, and a locked Mode dropdown is no longer
  drawn like an editable one. All four theme states are covered: Light, Dark,
  and System on both.

- **A card's Settings opened from the Utilities tab's right-hand column now
  fill the window.** Before, opening a card from the right column showed its
  settings across the right half only, while a card in the left column filled
  the tab; both columns now open across the window, and the remaining cards
  reflow below the open one as before.

- **A REFINE run that changes nothing now leaves the file byte-identical.** When
  no enabled stage finds anything to repair — no clicks, no silence, no noise,
  and loudness already inside tolerance — the file is reported SKIPPED instead
  of being re-encoded, re-tagged and replaced, and it is not added to the
  completion registry. A file that does need work is still written as before.
  Dry Run now reports what the enabled stages would detect (clicks, trimmed
  silence, noise, the enhancement's projected gain, and the loudness Normalise
  would apply) instead of only loading the file, and a normalise-only run makes
  one FFmpeg pass instead of two.

- **Text follows the chosen theme in the states the theme used to miss.**
  Dark - or System on a dark OS - no longer leaves text black on a dark box:
  the CD Ripper's "Rip Complete!" heading and its CD-insert instructions, the
  Master Driver's caveat notes and its settings footer, the SETTINGS strip
  button, and a checkbox's label while the pointer is over it all now use the
  suite's colours. Buttons that are unavailable until a run starts show
  readable text instead of Tk's own grey, and a checkbox's indicator box is
  drawn in the colour of the card it sits on rather than a fixed white square.

## [2.3.0] - 2026-10-31

### Added

- **Duplicate Finder finds the files that are the same recording, and deletes
  nothing.** A new utility tool fingerprints every file in a folder, groups the
  ones that are the same recording, and reports each group with the copy it
  proposes to keep — chosen by measured quality (lossless, then bitrate, then
  sample rate, then length), never by tags. The default similarity threshold of
  0.10 is the measured one: four encodings of one recording scored
  0.0000–0.0002 on the reference set, while the closest pair that must stay
  apart scored 0.1580. A live run **moves** the extra copies into a quarantine
  folder and records every move for undo; the kept copy is left byte-identical,
  a dry run moves nothing, and a second scan skips the quarantine folder so it
  cannot re-find what it moved. Fingerprints are cached, so a rescan of an
  unchanged library does not repeat the work.

- **Restoration (Declip) rebuilds the peaks a clipped recording lost.** A new
  utility tool finds the flat-topped runs a ceiling left behind — measured
  against the file's own peak, so a limiter set below full scale is found as
  readily as a 0 dBFS master — and reconstructs each one by interpolating
  through the clean samples either side. On the reference tone the measured
  harmonic distortion falls from −21.38 dB to −46.82 dB and the peak returns
  from −1.938 dBFS to −0.188 dBFS against the original's −0.100. A file with
  nothing to repair is **skipped and not rewritten**, a square wave (whose
  waveform is itself flat) is refused rather than rounded, and a repair keeps
  the source's tags, sample rate, channel count and bit depth — a 24-bit source
  stays 24-bit.

- **Two new CLI commands and two new windows.** `audiosuite duplicates` reports
  duplicate groups (its JSON payload adds `groups`, `duplicates` and
  `quarantined`) and `audiosuite declip` repairs clipping; both are in the
  Master Driver with their own cards, and both have a standalone window
  (`Duplicate_Finder.pyw`, `Restoration.pyw`) with the suite's three tabs, Run
  Controls strip and undo-backed live writes.

## [2.2.1] - 2026-10-30

### Changed

- **The Tag Field Updater window now matches the suite's layout, and a driven
  run is read-only.** Its single flat column became the standard **Setup /
  Processing / Results** tabs: Processing shows the current file, a progress
  bar, the shared `Processed / Skipped / Errors` count and one line per file,
  and Results carries the completion summary (still naming skipped and failed
  files), **View Log** and **Open Folder**, so the modal dialog is gone. Setup
  opens with the suite's **Run Controls** strip — **Browse & Scan**, a **Mode**
  dropdown (**Dry Run** / **Live Update**), and the driver's **Auto Start**,
  **Auto End**, **Clear Logs** and **Parallel** states — and the window now
  starts in **Dry Run**, so writing tags is an explicit switch to Live Update.
  A Master Driver launch locks the source and mode, and its Auto Start / Auto
  End options take effect: a scan begins only when asked, and the window closes
  itself once the batch's step is done instead of waiting to be closed by hand.

- **The Tag Field Updater writes a run report next to the music, like every
  other tool.** Each run leaves `tag_field_updater_dry_run_log.txt` (or
  `tag_field_updater_sync_log.txt` in Live Update) in the folder it scanned: the
  mode, directory, source and patterns in the header, one line per file
  (`[UPDATED]`, `[WOULD UPDATE]`, `[UNCHANGED]`, `[SKIP]`, `[NO MATCH]`,
  `[ERROR]`), then the summary the Results tab shows. **View Log** opens it, so
  the per-file detail no longer lives only in the suite log. The folder chooser
  opens where you last looked and the folder is remembered for the next launch,
  as it is in every other tool.

- **The Tag Editor window matches the suite's layout, and every edit run leaves
  a report.** The grid window's flat layout became the standard **Setup /
  Processing / Results** tabs. Setup opens with the suite's **Run Controls**
  strip — **Browse & Scan**, the **Mode** dropdown (**Dry Run** / **Live
  Update**), and the driver's **Auto Start**, **Auto End**, **Clear Logs** and
  **Parallel** states — and keeps the edit controls and the grid below it;
  **LOAD & SCAN LIBRARY** fills the grid, with a **Stop** button that ends the
  walk after the file it is reading. Processing shows the progress bar, the
  per-file lines and the shared `Processed / Skipped / Errors` counts while a
  load or an apply runs; Results shows the finished run's summary, its total
  time, **View Log** and **Open Folder**. Dry Run is still the default, and the
  strip's Mode is what every apply run reads. A Master Driver launch locks the
  source and mode, and its Auto Start / Auto End options now take effect.

- **The Tag Editor writes a run report next to the music.** A load walk leaves
  `tag_editor_scan_log.txt` in the folder it read; an apply run leaves
  `tag_editor_dry_run_log.txt` (or `tag_editor_sync_log.txt` in Live Update).
  Each has the run and mode in the header, one line per file or per edit
  (`[READ]`, `[WOULD WRITE]`, `[WRITTEN]`, `[UNCHANGED]`, `[FAILED]`,
  `[SKIPPED]`), then the summary the Results tab shows, and **View Log** opens
  it — so what a run did to which file no longer exists only in `logs/`.

## [2.2.0] - 2026-10-30

### Added

- **The Tag Field Updater can tag from filenames.** A library whose only
  metadata is in its file names could not be cleaned in this suite at all; the
  new source parses a name into tag fields with an ordered list of patterns and
  writes them (`audiosuite tag-update D:/Music --pattern "%track%. %artist% -
  %title%"`). Placeholders are the fields the Tag Editor already writes
  (artist, title, album, album artist, track, disc, year, genre, comment), and a
  pattern that would split a name ambiguously is refused rather than guessed at:
  numeric fields match digits only, so `05 - Artist - Title` cannot read the
  dash as a track. The mode runs as a **dry run** unless `--live` is passed and
  prints the parsed fields per file, because a wrong split writes tags the file
  then looks authoritative with. `--only-fill-blanks` (the default) leaves a tag
  that already carries a value alone; `--overwrite` replaces it. Pattern sets
  are saved by name as action groups in the shared
  `audio_suite_config.json`, and a parsed genre still goes through the existing
  slash rule while an artist such as `AC/DC` does not.
- **Playlist, HTML and Camelot exports in the Library Statistics Dashboard.**
  The dashboard already read every tag a playlist needs and could only hand
  them out as CSV or JSON. `audiosuite stats --export m3u` now writes an
  extended M3U (an `#EXTM3U` header, one `#EXTINF` line and one absolute
  forward-slash path per file, in album-then-track order, with `-1` for an
  unknown duration), `--export html` writes a self-contained page with no
  external assets, and `--export-columns` picks the columns while `--camelot`
  adds the harmonic-mixing key code. The CSV export keeps its original columns
  and order unless a column set is asked for, so existing consumers are
  unaffected; the GUI's Export dialog gained M3U and HTML beside CSV/JSON and a
  Camelot column checkbox. Camelot is a pure mapping from the key the Key
  Detector already wrote, maps both spellings of each enharmonic pair to the
  same code, and leaves a file with no key empty rather than guessing.

## [2.1.7] - 2026-10-29

### Fixed

- **Normalising no longer resamples every file to 192 kHz - and works again on
  current FFmpeg.** `loudnorm` computes at 192 kHz and hands its frames on at
  that rate, and the normalise command never pinned the output rate, so a 2 s
  16-bit 44.1 kHz FLAC came back as a 192 kHz 24-bit one at ~10x the size: a
  silent sample-rate and bit-depth change on every normalise pass. The same
  freedom broke the stage outright on FFmpeg builds after 8.0, whose FLAC
  encoder rejects the 384000-sample block that rate implies
  (`invalid block size: 384000`) - so the stage failed on every file. The
  command now pins the source's own rate (and FLAC's bit depth), skips the pin
  for encoders whose rate set cannot hold it - `opus` takes 8/12/16/24/48 kHz
  only, and an explicit `-ar` also suppresses FFmpeg's own resampler - and caps
  FLAC frames at 4096 samples without padding the last one. Verified on a
  2 s, 44.1 kHz, 16-bit source: -30.95 to -15.95 LUFS, 44 100 Hz and 16-bit on
  the way out, on both FFmpeg 8.0.1 and a current master build.
- **The library cache no longer trusts an mtime alone.** A file replaced by one
  that preserves its timestamp - `cp -p`, a backup restore, a same-second
  rewrite - kept its cached row, so the statistics report served the tags of
  the file that no longer existed. Freshness is now the stamp `(mtime, size)`,
  read in the same single scoped query as before; a row written before the size
  was filled never matches, so it is re-read once and heals.
- **Console and log output is ASCII-only.** A cp1252 console - Windows'
  default - cannot encode an em dash, a check mark, a ballot X or an arrow, so
  the affected tool raised `UnicodeEncodeError` mid-run instead of printing its
  status line. 92 glyphs across 25 files were rewritten to their ASCII forms
  (typography stays in comments and documentation, which no console renders),
  and a lock scans every first-party output call so it cannot drift back.
- **A 24-bit WAV or AIFF rewritten in place came back 16-bit.** The shared
  pydub export path passed no sample-format argument, so FFmpeg's WAV/AIFF
  muxers wrote their 16-bit PCM default while the rate and channel count
  survived - a silent truncation on every in-place rewrite. The exporter now
  pins the source's PCM codec (`pcm_s24le` from a 24-bit source,
  `pcm_s16le`/`pcm_s32le` for 16/32-bit) and leaves lossy targets alone.
  Verified by decoding the output of all seven writers: 32 kHz, mono, 24-bit in
  is 32 kHz, mono, 24-bit out.
- **Fourteen guides stated the wrong worker count, and three the wrong format
  count.** Every tool sizes its worker grid from the logical CPU count (capped
  at eight), not the four slots those guides claimed - so on any machine with
  more than four CPUs the guide disagreed with the window beside it - and the
  shared format set has held fourteen containers since 1.1.0, not nine. The
  Lyrics Manager guide also named status labels (`[LIKE]`, `[ALREADY]`,
  `[NO MATCH]`, `[PLAIN]`) the tool never prints. All 32 guides were read
  against the code and corrected, and the mechanical claim classes - format
  counts, worker counts, flags, status tokens and artifact names - are now
  locked by a test so the next drift fails instead of shipping.

### Added

- **The Audio Normalizer's true-peak ceiling and loudness range are
  configurable.** `--tp` (default -1.5 dBTP) and `--lra` (default 11 LU) reach
  both loudnorm passes from the CLI and from the Setup tab's sliders, and each
  processed file now reports the true peak the re-encode **achieved**, so a
  ceiling the encoder could not hold is visible instead of assumed. A ceiling
  above -1.0 dBTP asks for confirmation first, because a lossy re-encode can
  clip there. The defaults are unchanged, and a re-run at the same target stays
  inside the existing tolerance check and is skipped, so no file is encoded
  twice.
- **The metadata scrubber can see WavPack, Monkey's Audio, Musepack, Ogg Speex
  and DSF files.** `.wv`/`.ape`/`.mpc` scrub through their APEv2 items, `.spx`
  through its Vorbis comments and `.dsf` through its ID3 tag; artist, album,
  title and the flagged lyrics, album-artist and artwork items are preserved
  and restored on undo. A scrub stays metadata-only: the decoded duration and
  per-channel RMS are identical before and after, and the undo round trip is
  proved on a real `.wv`. `.wma` is the only container the discovery test now
  reports as unsupported.

### Changed

- **ReplayGain album gain comes from the album's combined signal.** Album
  loudness was a duration-weighted mean of each track's integrated loudness,
  which is exact only when every track gates the same way. Measured off a 20 s
  -10 dBFS + 20 s -35 dBFS pair, the weighting is 3.00 dB below the combined
  signal's gated loudness (+2.70 dB vs -0.30 dB album gain), and 2.33 dB below
  on a mostly-silent-tail album - both outside ReplayGain's 0.5 dB expectation,
  because the quiet track falls under the combined signal's relative gate. The
  folder is now measured once as a concatenated stream; the weighted formula
  remains only as the fallback for a folder whose combined signal cannot be
  read, and both routes are named in the folder log header. Cost is one extra
  decode of the album.

## [2.1.6] - 2026-10-28

### Fixed

- **The refinery's integrity check reports an unreadable file instead of
  crashing on it, on every supported interpreter.** `validate_file` decided
  existence and regular-file-ness through `Path.exists()` and `Path.is_file()`;
  those swallow a stat failure only on 3.13+, so a locked or permission-denied
  path raised out of the check on 3.11 and 3.12 instead of failing that file
  with a reason. One guarded `Path.stat()` now decides existence, regular-file
  status and size, so all three legs give the same verdict.
- **The Master Driver menubar no longer shows a tear-off row above Help.**
  `tk.Menu` defaults to a tear-off entry; Tk 8.6 draws it as a dashed line and
  shifts every entry index by one, while Tk 9 defaults to none - so the bug was
  invisible on the 3.14 host but present on the 3.11/3.12 legs the suite runs.
  The menubar is built with `tearoff=0`, and the Help-menu test resolves Help's
  real position instead of reusing its position among the cascade labels.

## [2.1.5] - 2026-10-27

### Added

- **The What's New panel can open the complete changelog.** The panel only
  renders the releases since the last one seen, so the rest of the history was
  unreachable from inside the app. A **Full Changelog** button now opens a
  scrollable window listing every released section of `CHANGELOG.md`, newest
  first - version headings, entries and bold lead-ins, rendered by the same
  parser and renderer as the panel. Closing it records nothing as seen, so
  browsing the archive never hides the pending notes the panel was opened to
  show.
- **The full changelog is also on the Help menu.** A **Full Changelog** entry
  opens the same history window straight from the Master Driver, so the archive
  no longer requires opening the What's New panel first. An installation whose
  changelog has no released sections says so instead of opening an empty
  window.

### Fixed

- **The reference and the new-user deck now cover all 30 tools.** The CLI
  reference documented the flags of only eight tools and listed 24 of the 37
  command entries in its *All Commands* table; the new-user presentation named
  26 of the 30 tools, and its opening slides went on to claim "26 Windows
  desktop tools" and "26 separate windows" while the suite shipped 30; the
  README's generated table listed all 30, but its opening line still claimed
  27. From the reference or the deck a reader could not learn that Tag Editor,
  Stem Separator, Spectral Viewer or ML Denoiser existed. The reference is now
  grouped by stage with a section per tool, every flag taken from the CLI
  itself; the deck gains two slides plus format-matrix and task-chooser rows,
  and reads its tool count from the manifest instead of quoting a literal.
  `tests/test_suite_docs_tool_coverage.py` derives the population from the tool
  manifest and fails when either artefact drops a tool. It also scans the
  README, `CONTRIBUTING.md`, `SECURITY.md`, every page under `docs/` and every
  guide under `user_guides/` for a quoted tool count - the total, a
  per-category count, the Windows-only remainder and the deck's window count -
  and fails on any claim the manifest does not support.

## [2.1.4] - 2026-10-26

### Added

- **The CLI commands reference has a Word copy, built like every user guide.**
  `user_guides/reference/CLI_Commands_Reference.md` is now rendered to
  `CLI_Commands_Reference.docx` by the shared `utilities/build_user_guides.py`,
  the script that already turns each tool's Markdown guide into the `.docx` its
  Help button opens, so the reference has a regeneration path and can no longer
  be a hand-maintained binary. The source gained the same YAML front matter the
  tool guides use and its wrapped option bullets were joined into one line each,
  because the renderer's dialect ends a bullet at the first unindented
  continuation. `--check` and `tests/test_user_guide_hygiene.py` now cover the
  `reference/` tree alongside `individual_programs/`.

### Changed

- **CLI commands exit 1 when a batch finishes with errors.** A run that reported
  `1 errors` in its summary and its `--json` payload still returned status 0, so
  a scheduler or CI job could not tell a clean run from one that converted,
  tagged or normalised nothing. The status now follows the count the run
  printed: **0** clean (including skipped files), **1** completed with per-file
  errors or crashed, **2** a usage error. Only the status changed — `--json`
  documents are byte-identical — and an all-skipped folder still exits 0.
  `audiosuite plugins list` follows the same rule, exiting 1 when it reports a
  rejected plugin manifest. Scripts that relied on 0-after-errors will now see
  the failure, which is the point of the change.

### Fixed

- **Tag Field Updater counts a failed file once.** The per-file scan and the
  per-format handlers both incremented the error tally, so one corrupt file was
  reported as two errors in the summary and the `--json` payload. The count is
  now taken once, in the handler that classified the failure.
- **Every audio-tool subprocess call goes through the shared secure wrapper.**
  The Audio Enhancer's ffmpeg/ffprobe decode and encode spawned processes
  directly, and the CD Ripper's Eject button built a PowerShell command string
  by interpolation; both bypassed the executable allowlist that `SECURITY.md`
  says covers all shipped code. The enhancer now calls
  `run_secure_subprocess` — the raw-PCM decode passes the new `text=False`, so
  its binary stdout is no longer decoded as text — and drive eject/reveal moved
  into a Tk-free `cd_ripper/core/drive_control.py`: the Windows tray opens
  through MCI from a validated single drive letter (no process, no shell), while
  POSIX eject and the Explorer reveal pass fixed argument lists. A tray that
  refuses to open now says so in a dialog instead of looking like a no-op, and a
  repository-wide test fails on any new direct `subprocess.run`/`Popen` in
  shipped code.
- **A batch no longer starts a step whose dependency failed.** The Master
  Driver added a failed step to the same set that releases its dependants, so a
  failed BPM analysis still let Tempo run — writing tempo markings derived from
  files that were never tagged — and the report counted that step as completed.
  Sequential mode consulted no dependency graph at all and did the same. Both
  modes now mark the dependant **skipped** with the reason on its line
  (`skipped: dependency 'bpm' failed`, or `did not run` when the dependency was
  itself skipped), including every step above it in the chain.

## [2.1.3] - 2026-10-25

### Fixed

- **Album Art Sync reads one configuration file in every run mode.** The window
  and the command-line/batch pipeline derived the config location from their own
  module path, so the window read `album_art_sync/album_art_config.json` while
  the pipeline read `album_art_sync/core/album_art_config.json`. On an install
  where the Fanart.tv keys were entered in the window, batch runs found an empty
  file and silently lost that source. Both now read
  `album_art_sync/config/album_art_config.json`. A copy left at either old
  location is migrated on first load together with its `.key` — a JSON copied
  without its key cannot be decrypted — and the originals are left in place.
- **The Metadata Scrubber no longer offers formats it cannot open.** Discovery
  used the suite-wide extension list while the loader handled nine containers,
  so a valid WavPack, Monkey's Audio, Musepack, Speex or DSD file in a chosen
  folder was listed and then reported `[UNREADABLE]` with an error count — a
  failure against a file that is perfectly fine. Extension discovery and the
  loader now derive from one table, so the scrubber offers, samples and
  processes exactly the nine it can scrub: MP3, FLAC, OGG, Opus, M4A, MP4, WAV,
  AIFF and AIF. Tag sampling for the preserve checklist uses the same table, so
  it no longer spends its 100-file budget on files that will not be processed.
- **Audio Enhancer dry runs measure the chain the live run writes.** Dry Run
  bypassed the five effects, so a preview with karaoke, phaser, flanger, chorus,
  reverse or the output gain enabled reported the level of a *different* signal:
  karaoke on a centred mix showed -9.9 dBFS where the written file measures
  near-silence. The bypass switch is gone and both modes run the configured
  chain; the only remaining difference is that a dry run writes no file and
  copies no tags.

## [2.1.2] - 2026-10-25

### Security

- **File Reorganizer and CD ripper refuse paths that escape the destination.**
  Tag values are untrusted input, and the organizer's resolver kept `..`, so a
  file tagged `album="../../evil"` was copied to a directory above the chosen
  destination (the resolver returned `..\\..\\evil`). `resolve_path` now
  refuses a `.`/`..` component, a drive-qualified value (`C:\\Music`) and a UNC
  value (`\\\\server\\share`) instead of rewriting them, and the engine checks
  every destination for containment inside the destination directory before
  writing. The CD ripper's filename sanitiser no longer returns a bare `.` or
  `..`, and its per-track output path is checked for containment before any
  folder is created. Refusals surface as a pattern error (organizer) or a
  failed track (ripper) and write nothing.

### Fixed

- **Album ReplayGain is weighted by track duration.** A folder's album gain
  used the arithmetic mean of its tracks' integrated loudness, so a ten-second
  track counted as much as a thirty-minute one. The audit's pair (10 s at
  -10 LUFS against 30 s at -30 LUFS) was tagged as +4.0 dB where the combined
  signal needs about -0.1 dB. Album loudness is now the duration-weighted
  mean-square energy of the measured files (ReplayGain 2.0-compatible): the
  same pair is tagged at about -0.1 dB, and a real concatenated measurement
  agrees within 0.2 dB. A file whose duration cannot be read is reported as a
  per-file error instead of being weighted as zero.
- **ALAC conversions now write an M4A container instead of failing.** Every
  ALAC run failed with `Error initializing the muxer ... Invalid argument`,
  because the output was named `song.alac` and FFmpeg selects its muxer from
  the file extension; `.alac` names a codec, not a container. The converter now
  names each output for its container (`formats.output_extension`), so ALAC is
  written as `song.m4a` and the audio decodes bit-identically to the source.
  ALAC and AAC-M4A share the `.m4a` extension, so a later run to either format
  replaces the earlier file with the same name.

## [2.1.1] - 2026-10-24

### Added

- **The example plugin's window opens on the folder and run mode the Master
  Driver was set to.** A launcher receives the same arguments as every tool
  (`<directory> --live|--dry --start|--no-start --end|--no-end`); the example
  ignored all four, so it opened empty and always labelled live. Its window now
  lives in `example_plugin/window.py` (a `.pyw` launcher is not importable, so
  nothing in it could be tested), parses the grammar with `parse_launch_args`,
  and fills the folder entry and mode through one write path shared with
  Browse. It also honours `--start` and `--end`: the report runs as soon as the
  window opens and the window closes when it finishes, so the Master Driver can
  launch it as a batch step. The walk runs on a worker thread and reaches the
  window through a queue the Tk thread polls — a worker calling `root.after`
  itself raises `RuntimeError: main thread is not in main loop` — and a run that
  failed stays open so its message can be read instead of vanishing with the
  process.
- **The documentation artifact is self-contained.** The `docs-html` artifact now
  carries every file its pages link to - `README.md`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `packaging/` and the guide sources - plus a
  root `index.html`, so a downloaded artifact opens on the
  front door and its links resolve without a checkout. Twelve were dangling
  before: six targets the build never published, two links in
  `docs/user/suite-overview.md` written one directory too shallow, and four
  links in `docs/index.md` written as Markdown to `.md` files that MyST emits
  verbatim. `utilities/build_docs_site.py` stages the tree for CI and for the
  lock that walks it, and keeps Sphinx's build cache out of the publish root.
  Publication to GitHub Pages is not part of this release: Pages cannot be
  enabled for a private repository on the free plan, so the artifact is the
  delivery and every link in it is checked.

### Fixed

- **The bundled example plugin's launcher now opens.** Launching `Example
  Tool` from the Master Driver reported only `Module Error — Module failed:
  Example Tool`: the launcher derived both directories one level too high, so
  it put the suite root on `sys.path` instead of `plugins/`, the import of
  `example_plugin.tool` raised `ModuleNotFoundError`, and the pre-flight guard
  scanned the suite root's parent rather than the suite. A failed step's dialog
  now also names the launcher's exit code, since that is the only evidence left
  once its output is gone.

## [2.1.0] - 2026-10-23

### Added

- **A plugin system: third-party tools and analysis in `plugins/`, enabled one
  by one.** A directory under `plugins/` holding a `MANIFEST.toml` can add a
  tool (CLI command, Master Driver toggle and card, optional launcher), a
  Master Driver card body, a tag processor that runs during `tag-update`, and an
  analysis contribution that runs during `stats`. Manifests are parsed and
  validated at startup without importing any plugin code, so `audiosuite doctor`
  and the new `audiosuite plugins list` can report a plugin that will not load;
  a plugin's code is imported only once you enable it (`audiosuite plugins
  enable <id>`, stored with every other preference in
  `audio_suite_config.json`). A refused manifest is listed with the key to fix
  rather than silently skipped — unknown keys, duplicate ids, a `cli_command`
  that would shadow a suite command, an `api_version` this suite does not
  understand, a launcher outside the plugin folder, and an entry point that
  escapes the plugin's own package are all rejections. Plugin tag edits and
  plugin analysis metrics are counted apart from the tool's own figures
  (`plugin_updates` / `plugin_errors`, `plugin_analysis` /
  `plugin_analysis_errors`), and `--no-plugin-tags` / `--no-plugin-analysis` run
  a tool without them, so a difference between two runs stays attributable.
  `plugins/example_plugin/` demonstrates all four extension points and is the
  template to copy; `docs/plugins.rst` is the development guide and manifest
  reference. Plugin code runs in the suite's own process — enabling one is a
  trust decision, and the guide says so.
- **`audiosuite doctor` reports the interpreter a tool will run in and whether
  its optional engine is importable there.** A stale install and a
  system-Python launch look the same from the outside: the package is present,
  the tool still cannot import it. The report now names this process's
  interpreter and the one a `.pyw` launcher would use (the project's `.venv`
  when it exists), then probes Demucs and RNNoise in *that* interpreter — not
  in the process running doctor — and lists each tool with its
  `uv sync --extra ml` fix. A missing extra is reported without failing the
  check, because the first run that needs it installs it.
- **The launchers run from the project's `.venv`.** `uv sync --extra ml`
  installs Demucs/RNNoise into `.venv`, but a double-clicked `.pyw` is started
  by the system Python — so the tool could not see the extra that *was*
  installed, and the first-run installer wrote a second copy into the system
  interpreter. Every launcher now re-executes itself under `.venv` when one is
  present, with the same script and arguments and keeping `pythonw.exe` for a
  windowed launch, before the pre-flight guard runs. A checkout without a
  `.venv` behaves exactly as before, and a failed re-exec continues in the
  current interpreter instead of closing the window.
- **The Master Driver's Stem Separator card can browse for its output folder.**
  The Output Folder setting on the UTIL tab was a plain entry, so the stem
  destination had to be typed even though the tool's own Setup tab has always
  offered a Browse button. The card row now carries that button, opening the
  folder dialog at the current value and leaving the entry untouched when the
  dialog is cancelled.
- **The ML tools install their own optional engine on first use.** Demucs
  (Stem Separator) and RNNoise (ML Denoiser) live in the `ml` extra, and a run
  that needed one stopped with "Demucs is not installed … uv sync --extra ml".
  That instruction is a dead end for a non-technical user, and it installed
  nothing at all when the window had been started by a different interpreter
  than the one `uv` wrote the extra into — which is exactly what a
  double-clicked `.pyw` does. The first run that needs one now offers a
  one-time download, installs it into the interpreter that is actually running
  the tool, verifies it by importing it in a fresh process and re-checking the
  version floor declared in `pyproject.toml`, then continues the run by
  itself. A declined or failed install reports why and starts nothing; the
  Stem Separator's dry run never touches it, while the ML Denoiser installs for
  both modes because a dry run measures with the model.

### Fixed

- **A launched Stem Separator opens in the mode the Master Driver shows.**
  `_apply_cli_args` applied the run mode *after* an early return on a missing
  source folder, and a standalone utility launch passes an empty positional
  slot (the tool opens its own window and picks its folder itself). The
  driver's `--live` therefore arrived and parsed, then was dropped: the
  separator opened in Dry Run while the toolbar showed Live Update. The run
  mode is a setting of its own and is now applied before the folder-gated
  handshake, the order the shared `_apply_driver_cli_args` base already uses;
  the Auto Start / Auto End / Clear Logs / Parallel mirrors stay behind the
  gate because they describe a run an empty launch cannot target. Pinned by
  three tests that drive the tool's real parser with the driver's argv.
- **A module whose required settings are still empty is reported instead of
  launched.** The Stem Separator with no output folder (or no stem ticked) made
  the arg builder return an empty list, and the launcher turned that into a
  launch with zero arguments: the tool opened as a bare standalone window with
  no source folder and every run setting at its own default, so the Master
  Driver's Live Update never arrived and the separator came up in Dry Run.
  LAUNCH now names the modules that still need settings and starts nothing, and
  the Stem Separator card states the rule (an output folder, at least one stem)
  so the reason is visible before the click. The Audio Enhancer's empty output
  directory takes the same gate.
- **One Mode selection now applies to every batch the Master Driver launches.**
  The toolbar's Mode dropdown is one control, but ENRICH/REFINE read one
  variable and UTIL another, so picking "Live Update" on ENRICH and then
  launching a utility handed the child `--dry` — the same visibly-wrong mode
  the entries above describe. A write to either variable
  is now mirrored to the other, so the mode the toolbar shows is the mode every
  launch uses.

## [2.0.0] - 2026-10-23

### Fixed

- **Every GUI tool's completion and progress steps survive the fields their
  processor sends.**
  Audio Enhancer bound its handler directly but declared only `(total, done,
  errors, duration_secs, results)` while `run_enhancement` also publishes
  `processed` and `skipped`, so a finished batch ended with `[AudioCodecError]
  ... unexpected keyword argument 'processed'` and no report was written. All
  fourteen completion handlers and fourteen progress handlers now absorb fields
  they do not use, and a new cross-tool test derives the wiring from the tree
  and fails if any handler narrows its signature again; the same lock pins the
  one-message `on_error` contract every processor relies on. Each tool's
  required completion fields are frozen in a second lock as well, so a handler
  that gives one a default — the way a discarded count renders as a clean
  zero — fails the suite instead of a batch.
- **Album Art Normalizer reports what it actually processed.** Its completion
  wiring rebuilt the processor's payload field by field with
  `kw.get(field, 0)`, so a field the processor renamed or stopped sending
  arrived as a clean `0`/`00:00` in the finished report — the silent zero the
  required-field contract exists to prevent, one layer above it. The payload is
  now forwarded as published and a missing field raises with its name. A new
  cross-tool lock reads every tool's completion wiring from the tree and fails
  if one reintroduces per-field defaults, so the contract now covers the
  publisher side that a signature test cannot see.
- **ReplayGain Analyzer's summary no longer undercounts a mixed batch.** Its
  `Successfully processed` line subtracted the error count from a figure that
  already counted only successes, so two good files beside one failure read as
  1 and a single failure read as -1; the log and the summary panel now report
  the success count itself. Its `skipped`, `errors`, `duration_secs` and
  `log_entries` are required arguments now, so a payload that omits one raises
  with the field's name instead of writing `Errors: 0` and `Time: 00:00` into a
  report that never carried the numbers.
- **A slow track is no longer tagged at double its real tempo.** BPM detection
  doubled any estimate below the configured range and clamped whatever was left
  outside it, so a genuine 60 BPM drone under the default 75 BPM floor was
  reported — and written into the file's BPM tag — as 120. The range now chooses
  between octave-equivalent readings only when the folded level carries a pulse
  of its own: the drone's doubled grid scores 0.42 against 0.746 for its real
  pulse, under the 0.75 evidence ratio a fold must reach, so 60 is kept — while
  a genuine half-time reading (which does have those off-beat hits) still lands
  on the faster level. A measured tempo outside
  the range is tagged as measured and its line says `(outside 75-175)`.
  `--bpm-min`/`--bpm-max` now default to 75/175, so the CLI and the GUI no
  longer answer the same file differently.
- **Analysis batches no longer get slower when you add worker threads.** BPM,
  Key and Mood analysis spend several seconds compiling librosa's numeric
  kernels the first time a batch runs. That compile happened once per worker
  thread instead of once per run, and the threads waited on each other while it
  did, so an eight-file batch took 12.2 s at 8 workers against 5.0 s at 4 — more
  threads, less speed. The three analysis tools now compile those kernels once
  before the worker pool starts: the same batch takes 2.8 s at either width, and
  the thread path is 2.9x faster than `--parallel` (8.1 s) on the same files.
  Peak memory is unchanged. A failed warm-up never fails the batch; the analysis
  simply compiles on first use as before.

### Added

- **Stem Separator: split a track into vocals, drums, bass and other.**
  A new tool (GUI `Stem_Separator.pyw`, CLI `audiosuite stems`, Master Driver
  UTIL card) runs Demucs on every supported audio file in a folder and writes
  the selected stems under `<output>/<track>/` as 16-bit WAV, plus an optional
  `mix.wav` of the selected stems. The source files are never modified, so the
  tool keeps no undo record; a dry run reports the plan without loading the
  model, downloading its weights or creating the per-track folder, and works
  on an install without the ML stack. Two sources with the same stem name
  (`song.flac` and `song.wav`) target one output folder, so the first is
  separated and the second is reported as skipped instead of overwriting it.
  The Setup tab states the device torch actually measured and why (see the
  device-reporting bullet below), because the PyPI Windows torch wheel is a CPU
  build: an explicit `--device cuda` that is not usable stops the run with that
  reason instead of quietly using the CPU.
  `--json` publishes `separated`, `files_written`, `output_dir` and `device`,
  the JSON schema corpus records a real run, and a user guide is shipped.
- **ML Denoiser: neural noise reduction with RNNoise.**
  A new tool (GUI `ML_Denoiser.pyw`, CLI `audiosuite denoise`, Master Driver
  UTIL card) removes broadband noise with RNNoise, a speech-trained recurrent
  network from the same optional `ml` extra — no torch is needed, the wheel is
  13 MB, and it denoised 30 s of stereo audio in 2.9 s. Files are rewritten in
  place with their tags, each live run records an undo snapshot, and a dry run
  reports the attenuation every file would receive. That report is the point:
  the model is not transparent (it attenuated a 220 Hz tone by 24 dB in the
  measurement), so each line states the before/after level (`Attenuated 6.0 dB
  (-18.4 → -24.4 dBFS)`) instead of claiming a clean denoise. A `--amount`
  percentage (1-100, the same unit the GUI slider and the driver use) blends the
  model's output with the source for musical material, and a file whose level
  does not move is reported clean and is not re-encoded. RNNoise resamples to 48 kHz
  internally and can return the wrong length — a 573-sample file came back one
  sample long — so the adapter forces the source length, restoring a shortened
  tail from the source rather than fading it to silence. RNNoise has no CUDA
  path, so the tool reports CPU honestly rather than offering a device flag
  that could not change anything.
- **GPU support is reported from what torch measured, not from the hardware.**
  A GPU in the case does not mean a run uses it: the torch wheel
  in the `ml` extra is a CPU build, so `torch.cuda.is_available()` is False even
  on a machine with a discrete card. The new shared
  `audio_suite_shared.gpu_utils` therefore answers from what torch reported and
  says *why* when the answer is the CPU — no torch installed, a CPU-only build,
  or CUDA support with no usable card — because those have three different
  fixes. `--device auto|cpu|cuda` resolves through the same call, so `cpu`
  never imports torch and an explicit `cuda` that is not usable stops the run
  with that reason instead of quietly falling back; the Stem Separator shows the
  line on its Setup tab, records it at INFO in the program log and publishes it
  as the `device` field in `--json`.
- **A finished batch report closes with one verdict line.** Caveats were
  printed one per step, so judging a twelve-step run meant scanning twelve
  lines and working out which ones mattered. The report now ends with a
  single `Batch verdict:` line that names every tool which reported a
  caveat, in run order, and leads with the failure count when steps failed
  — for example `Batch verdict: 1 failed · 2 of 12 steps completed with
  caveats — BPM Analyzer: 2 of 12 tracks measured outside the 75-175 BPM
  range; CD Ripper: 1 of 5 tracks did not rip`. It appears only once the
  batch has finished, so it never describes a run that is still going, and
  it is bounded: past 400 characters whole caveats are dropped from the end
  and counted (`; +3 more`), because every note is still printed in full on
  its own step line.
- **The BPM run summary counts tracks whose tempo fell outside the configured
  range.** Those files are tagged as measured rather than skipped, so the only
  trace of a range that does not match the library was a parenthetical on each
  file's own line — a 200-track batch could hide twenty of them. The Results
  panel and the run log now carry an `Outside BPM range` row (`1 of 12 tracks
  (band 75-175)`), the CLI prints the same count after its summary, `--json`
  publishes `outside_range_files` with each file's tempo and band, and the
  Master Driver's step note reads `1 of 12 tracks measured outside the 75-175
  BPM range`. A file with no beat still counts as skipped and an unreadable one
  as an error; this count is neither.

### Changed

- **The Master Driver's UTIL tab fits the window again.** Seventeen utility
  cards in one column needed 930 px of content in a 778 px viewport at the
  saved window size, so the last four cards and the LAUNCH button sat below the
  fold and every new tool pushed them further down. The cards now sit in two
  weighted columns — nine rows, 385 px of content at the same size — and the
  card whose Settings are open spans both columns while the cards after it
  reflow behind it. The LAUNCH button is pinned below the scrolling area, so
  the tab's primary action no longer has to be scrolled to. Undo Tag Edits, the
  one card that was never a batch tool, was 131 px because its three-line
  description sat outside any collapsible body; it is now a normal collapsed
  card with that text inside its Settings.
- **The ML stack is an opt-in `ml` extra.** Demucs and its torch dependency
  resolve for 3.11, 3.12 and 3.14, but the Linux torch wheel set is 2–3 GB and
  no other tool needs it, so `demucs>=4.1.0` and `pyrnnoise>=0.4.5` live in
  `ml`. Without the extra the Stem Separator still opens, validates a run and
  completes a dry run, and a live run fails with a message naming the extra.
- **A cached Library Statistics scan decides its query plan once per directory.**
  Choosing between the `path_fold` index and a sequential scan costs two
  `COUNT(*)` queries (about 16 ms on a 200 000-row cache), and every scoped
  read used to pay it, so one scan asking three questions about one directory
  paid three times. The decision is now remembered per directory for the life
  of the cache instance: three scoped reads of the same folder fall from
  18.7 ms to 3.1 ms, and a stale decision is only ever slower, never wrong.

## [1.4.1] - 2026-10-21

### Added

- **The CLI names the supported runtime when an install is stale.** Running the
  console script from a checkout is now checked against `pyproject.toml`: when
  the installed `audiosuite-pro` metadata version differs, every command prints
  a warning naming both versions and `uv run audiosuite --help`. A tool module
  that cannot be imported no longer kills the process: the rest of the CLI,
  including `doctor`, stays usable and the missing package is reported with the
  two commands that repair the environment (`uv sync --frozen --all-extras`,
  then `uv run audiosuite`). The README's Installation section documents the
  locked runtime and why a bare `audiosuite` can resolve to an older global
  install.
- **`audiosuite doctor` reports whether this install maps the checkout.** It
  resolves every first-party package through the installed import machinery,
  marks each as mapped, missing, or resolved from another install, maps a
  broken package back to the CLI commands it takes down (including a tool whose
  module resolved but whose command never registered), and prints the checkout
  and installed versions. It exits 0 only when the versions match and every
  package and command is present, so a pre-flight script can gate on it. The
  scan asserts it found packages, so a broken checkout scan cannot pass
  vacuously.
- **Every CLI tool's `--json` output now follows one documented schema.** A
  script can read `processed`, `succeeded`, `skipped`, `errors`, `total`,
  `dry_run`, `duration_secs` and `log_entries` from any command's payload and
  get the same meaning every time; `succeeded` is `processed - skipped -
  errors`, so it no longer matters which tool counts attempts. Each payload also
  carries `schema_version` (1), `tool` (the manifest id) and `command` (the CLI
  path), and tool-specific keys are declared per command in
  `audio_suite_shared/cli_schema.py` rather than leaking internal completion
  fields. JSON always goes to stdout and progress to stderr. A breaking change
  to a shared name bumps `schema_version`; `tests/test_cli_json_schema.py`
  invokes every command and fails on drift.
- **The CLI JSON contract ships as a JSON Schema document.**
  `audio_suite_shared/cli_schema.json` (draft 2020-12) holds one variant per
  command, discriminated by the constant `command`, and is generated from the
  same table that builds the payloads. `audiosuite --json-schema` prints it
  and exits, so an external validator needs no Python import; the lock test
  fails if the committed document is stale and validates every command's real
  payload against its committed variant.
- **BPM Analyzer's `--json` output explains every refused file.** A
  skipped file used to appear only in the `skipped` count; the JSON
  payload now has a top-level `skipped_files` list with each file's
  `filename`, `reason`, and `onset_periodicity` (null when the tracker
  found no tempo at all, so no score was measured). The records come from
  the exception's structured context in both the threaded and the
  `--parallel` process-pool paths, and the list is always present (empty
  when nothing was skipped). A parallel top-level `error_files` list reports
  each failed file's `filename`, `reason`, and `error_type` (for example
  `BPMDetectionError`), so a corrupt or unreadable file no longer looks
  like a beatless skip. Both lists are always present and sorted by
  filename. The GUI completion callback accepts such tool-specific fields, so
  the same run data can reach the CLI without breaking the report writer.
- **Audio Refinery remembers its pipeline outside the checkout.** The
  last-used stage configuration is now saved to
  `~/.audiosuite/refinery_settings.json`, so a session no longer rewrites a
  tracked file and `git status` stays clean. An existing
  `audio_refinery/refinery_settings.json` is read once (and logged) so nobody
  loses their settings on upgrade; the shipped defaults now live in a
  committed `refinery_settings.default.json` generated from the code's own
  defaults, with a test that keeps the two byte-identical.
- **`--json` emits one document per run, and that is now a recorded
  decision.** A stream of per-file records was considered and rejected: it
  would have to come from every tool's progress callback, while scripts read
  the summary. The behaviour is documented in the schema's module docs and the
  README, and locked by a test that fails if anything precedes or follows the
  document on stdout.
- **The 8-worker default has a measured memory budget.** `utilities/
  measure_worker_memory.py` runs a real analysis batch in a fresh process per
  worker count and reports peak RSS, so the ceiling that was chosen on speed
  alone now has a number behind it: on a 20-CPU host an 8-file batch peaks at
  about 790 MB at 8 workers against the documented 1 GB budget, and the
  `--parallel` parent stays near 50 MB because its children are separate
  processes. Neither configuration needed a lower ceiling, so analysis and
  conversion keep the same default.

### Fixed

- **`audiosuite cd-rip --json` reports a drive or disc failure in its payload.**
  A session that could not open the drive exited 1 with the reason only on
  stderr, so a script saw a bare failure. The rip path and
  `--detect-read-offset` now print one schema-conforming payload first
  (`errors: 1`, the reason in `error`, `read_offset_frames` null), then exit 1;
  stderr keeps the human-readable line, and a successful run's shape is
  unchanged.
- **`audiosuite fingerprint` finds the fpcalc binary the repository ships.**
  A source checkout commits `fpcalc.exe`, but resolution stopped at `--fpcalc`,
  `FPCALC` and PATH, so every file failed with `fpcalc was not found` unless the
  flag was passed. The committed copy is now the final fallback (an explicit
  path, the environment variable and PATH still win), the GUI status line names
  it instead of claiming PATH, and regression tests lock both the order and the
  out-of-box run.
- **`audiosuite cd-rip` exits with the drive error instead of hanging.**
  `read_toc` raises `AudioIOError` for an unavailable drive; because that is an
  `AudioSuiteError` and not an `OSError`, it escaped the session thread before
  `session_done_cb` and the CLI waited on `done_event.wait()` forever with no
  output. A session now always signals completion, records the fatal reason (the
  CLI turns it into a non-zero exit), logs a missing disc at WARNING without a
  traceback, and treats a failed spin-down as non-fatal.
- **`audiosuite enhance` no longer reports every file as a worker error.** Its
  progress callback sends a tool-specific `done=` counter that the shared
  `_run_tool` callback did not accept, so each file failed with `on_progress()
  got an unexpected keyword argument 'done'` — in text mode as well as JSON.
  The shared callback now absorbs tool-specific counters it does not display.
- **An unreadable file is reported in words that describe it.** BPM Analyzer,
  Key Detector, Mood Analyzer and Spectral Viewer all decode through the shared
  loader, which now raises one plain-language error:
  `Could not decode '<name>' — the file may be corrupt, truncated, or in a
  format no available decoder can read.` A file deleted between the scan and
  the decode says so instead (`... the file was not found; it may have been
  moved or deleted.`) while keeping the exception type callers already catch.
  Previously the decoder's own wording reached users — libsndfile reports an
  unreadable container as "File does not exist or is not a regular file", which
  told someone looking at the file that it had vanished — and a failed FFmpeg
  fallback logged its exit code and stderr at ERROR on top of it. The decoder's
  exception is kept as the cause in `logs/<tool>.log`.
- **`--log-level WARNING` now actually quiets the console.** The requested
  level was applied to the root logger only, while each tool package carries
  its own level, so its DEBUG and INFO records bypassed that filter and the
  console handler printed every processing detail — including stack traces
  logged at DEBUG — during a WARNING run. The console handler now sets the same
  level, so only warnings and errors reach the screen while the per-tool file
  log keeps its full detail.
- **A fatal CLI failure is now visible in the JSON payload.** `_run_tool`
  records a failed run as one error (it used to report `-1`) and includes the
  reason in `error`, so a script parsing `--json` can see why the run stopped
  instead of only a count it had to interpret.
- **`--json` payloads no longer nest tool fields under `extra`.** Completion
  data is published at the top level only when the schema declares it, so
  internal fields (enhancer result objects, per-file log-line lists) cannot
  change the public payload. `cd-rip`'s `log` is now `log_entries`, and
  `stats` reports the library's audio length as `library_duration_secs` /
  `library_duration_str` so `duration_secs` always means the run's wall-clock
  time. `tag-edit` and `cd-rip` publish one key set in both of their modes,
  with nulls for the fields a mode does not use.
- **One handled failure produces one line, not a traceback.** A corrupt or
  unsupported file is an expected per-file outcome, so the shared loader logs
  its reason at ERROR and the full causal chain at DEBUG. Retries no longer
  print a traceback for each failed attempt or for a non-retryable error; only
  exhausted retries log a final ERROR with the reason. The per-file outcome
  stays the user-facing report.
- **Silent files are refused instead of tagged with a made-up tempo, key or
  mood.** The shared analysis guard now rejects audio that is effectively
  silent (below about -60 dBFS RMS) as well as audio shorter than half a
  second, and BPM Analyzer, Key Detector and Mood Analyzer all apply it before
  feature extraction. Previously a silent file produced the clamp-floor BPM,
  a confident-looking key from a flat chroma spectrum, or a mood with a
  confidence score, and those values were written to the file as if measured.
  A silent file now reports `Audio is effectively silent (-240 dBFS); nothing
  to analyse.` and leaves its tags untouched.
- **Beatless files report "No tempo detected" instead of a made-up BPM.** When
  the beat tracker finds no beat — a sustained tone, a drone, or a pad with no
  rhythmic transients — it returns a tempo of zero. BPM Analyzer clamped that
  to the minimum BPM and tagged it, so a file with no rhythm carried a value
  that looked measured. The file is now left untagged and reported as `[SKIP]
  <file>: No tempo detected — the audio has no discernible beat.`, in both the
  threaded and the multi-process paths.
- **Noise-only files no longer get a made-up tempo.** A positive estimate from
  the beat tracker is not proof of a beat: random onsets can be fitted to a
  tempo grid, which is how a noise recording came out as a plausible BPM. BPM
  Analyzer now measures how strongly the onset pattern repeats at the detected
  tempo and its multiples, and reports `[SKIP] <file>: No tempo detected — the
  audio has no discernible beat.` when it does not, leaving the file untagged.
  Music over a noisy floor still passes: the threshold sits well below a
  jittered or noise-covered beat. The skip line and the per-file log now include the
  measured onset periodicity and the 0.10 minimum, so a skipped file shows the
  evidence rather than only the verdict.
- **BPM Analyzer no longer refuses genuine music as noise.** The guard that
  refuses noise-only files now scores a harmonic comb - how strongly the
  onset pattern repeats at one, two, three and four beats - instead of a
  single lag, and the minimum is 0.10. A corpus of seven CC0 recordings under
  `tests/data/bpm_corpus/` pins the music side: real tracks score 0.154-0.595
  while seeded white, pink and brown noise never exceeds 0.080, so BPM
  Analyzer no longer refuses genuine jazz, samba or hip-hop for want of a
  stricter noise margin. Provenance, licences and the measured calibration are
  in `tests/data/bpm_corpus/ATTRIBUTION.md`.

## [1.4.0] - 2026-10-19

### Added

- **What's New after an update.** The suite now says what changed instead of
  leaving you to find the changelog: the first time it starts after an update
  it shows that version's release notes in a scrollable panel (headings,
  entries and the bold lead-in on each), and the Master Driver's Help menu can
  reopen them at any time. The panel appears once per version, tracked in the
  shared config so it never nags, and it stays out of unattended work: a
  Master Driver batch launch never opens it, and `AUDIOSUITE_WHATS_NEW=0`
  disables the automatic panel entirely. Skipping a release does not lose its
  notes: the panel lists every release newer than the last version it showed,
  newest first, each under its own `Version x.y.z` heading.

### Removed

- **The Windows Explorer right-click integration is NOT being implemented.**
  The `shell-install` / `shell-uninstall` commands and the per-user
  `AudioSuite-Pro` context menu they registered have been withdrawn, and the
  feature is explicitly off the roadmap: it will not be implemented. It was a
  step too far: it gave Explorer a second entry point into the suite that
  users could not discover or configure from the app itself, and its cascading
  submenu did not render consistently across Explorer builds. The modules, their tests,
  the CLI commands, the README section and the platform-matrix row were all
  removed in the same change, so nothing advertises a menu that cannot be
  installed. Use the Master Driver or each tool's own launcher instead.

### Changed

- **Parallel work now uses the machine it runs on.** The default worker count
  is one per logical CPU, capped at 8, instead of a fixed 4 (measured: 24
  one-minute tracks WAV→MP3 in 2.02 s at 4 workers and 1.17 s at 8). Every
  tool's worker slot grid, saved setting default and the Master Driver's
  worker values follow the same default; each analysis tool's *Workers*
  control still overrides it, and the cap bounds peak memory.
- **Every worker count now comes from one resolver, and startup logs the value
  it got.** The leftover fixed counts in the audit are gone: the Mood Analysis
  Batch Tagger fell back to 4 (instead of the machine default) when a saved
  worker count was corrupt, and the `--workers` help text and module docstrings
  still advertised a fixed 4 — as did six of the generated user guides. A new
  lock test fails on any fixed count above one except the deliberately
  serial call site, the grid lock now derives its tool list from the tool
  manifest, so newly registered tools are covered without editing the test, and
  the affected guides were regenerated.
- **The startup log says which worker count this machine resolved.** Each launch
  writes one `Workers: 8 resolved (cpu_count=16, ceiling=8)` line at INFO, so a
  slow batch can be triaged against the host instead of guessed at.
- **Each file's tags are parsed once per pass.** Library Statistics read each
  file's tags eight times (174 ms per 100 files) and now reads them from a
  single handler load (23 ms per 100 files); the CSV export reuses the same
  reader. Genre Sync, Tempo Analyzer, Lyrics Manager, Audio Fingerprinter and
  Album Art Sync no longer load the same file twice for fields read together.

### Fixed

- **A Workers value above the slot grid no longer fails the files.** Key
  Detector, Mood Analyzer, BPM Analyzer and Lyrics Manager let you type any
  worker count into a *Workers* field, but their progress display has a fixed
  number of slots. Asking for more workers than slots handed the extra workers
  a slot index that did not exist, so every file past the grid was reported as
  an unexplained per-file error (and the batch lost those files). The count is
  now capped at the number of slots — with one warning, and the capped value is
  what gets saved — and the processing layer applies the same cap for any
  caller that supplies a smaller grid, so a preset, a restored setting or a CLI
  count cannot reintroduce it.
- **A corrupt saved worker count no longer quietly becomes four.** Mood Analysis
  Batch Tagger's saved value went through a literal-4 fallback, so a hand-edited
  or truncated setting ran at 4 workers on a machine that should have used its
  own default. The fallback now asks the shared resolver; non-numeric, boolean
  and non-positive values all fall back safely.
- **Silence Trimmer and Mood Analysis Batch Tagger saved a worker count they
  did not run.** Both accepted any typed *Workers* value and stored it
  verbatim while their processors clamped the run to the progress grid, so
  the saved value disagreed with what actually happened. Both now cap before
  saving, with one warning, and the extended lock would have caught the
  omission.
- **A driver launch no longer waits on the over-grid warning.** The worker
  cap opened a modal dialog even when the Master Driver or `--start` launched
  the tool with nobody to dismiss it, so an unattended batch sat blocked
  before it processed a file. That launch now logs one warning and continues;
  clicking Start yourself still shows the dialog.

## [1.3.0] - 2026-10-18

### Added

- **Spectral Viewer — see what a file actually sounds like.** A new tool renders
  an FFT spectrogram for any supported file, in the GUI (`Spectral_Viewer.pyw`,
  with matplotlib's own zoom/pan toolbar) or as a batch of PNGs from
  `audiosuite spectrogram <path>`. It reports the codec cut-off, the noise
  floor, DC offset and clipping at a glance, and it is strictly read-only with
  respect to audio: the only files it ever writes are images. Every image is
  normalised to its own peak at a stated dB floor, so a quiet master and a hot
  one are comparable, and the status line reports the absolute peak in dBFS so
  the two are still distinguishable. `--dry` prints the exact image paths it
  would write and writes none of them.
- **Library Statistics: the Charts tab now actually renders.** matplotlib was
  never a declared dependency, so a fresh install opened the dashboard with a
  "matplotlib not installed" message where the four charts belong — and the
  chart code was therefore never exercised by the suite. It is now a declared
  dependency and the charts are covered by tests that assert the data reaches
  the artists (one pie wedge per genre, the BPM bucket holding the measured
  files, one bar per key) and that a re-scan replaces the previous canvas
  instead of stacking a new one.
- **Library Statistics: the completeness dashboard shows *where* the gaps are,
  and whether they are closing.** Completeness now covers the five primary
  library fields — title, artist, album, track number and year — alongside the
  analysis tags it already tracked, and it reads each file **once** instead of
  twelve times (measured 1.5 ms → 0.16 ms per file on MP3), so the wider
  dashboard is cheaper than the narrow one was. A missing-tags-by-album heatmap
  sits under the tag bars, worst album first, with files that carry no album
  grouped honestly as
  `(no album)` rather than dropped. Each scan records a completeness snapshot in
  the cache (identical consecutive snapshots are suppressed, the newest 100 per
  folder are kept) and the Charts tab plots the overall percentage over time;
  `stats --trend` prints the series, `--history-limit` chooses its length, and
  `--no-history` keeps a scan from recording anything.

### Changed

- **Library Statistics: cached scans are orders of magnitude faster, with the
  same numbers.** The cache now commits a scan as one transaction instead of
  one per file (measured on 20 000 rows: 39.1 s → 0.24 s) and reads every
  cached modification time in a single query instead of one lookup per file
  (113 ms → 17 ms). A report for one album inside a large cache no longer
  scans the whole cache: its scope resolves through an indexed path range when
  the scope is a genuinely small slice (0.05 ms against ~17 ms for one
  sequential pass over 20 000 rows) and falls back to the sequential predicate
  when it is not, because an index is slower at whole-library selectivity. The
  decision is made from real row counts, existing cache databases are migrated
  in place on first connect, and both plans are asserted to return identical
  aggregates.

## [1.2.0] - 2026-10-17

### Added

- **Audio Fingerprinter: ISRC submission to MusicBrainz.** The ISRCs a file's
  own tags carry — typically the codes a CD rip recorded — can now be offered
  back to MusicBrainz for the recording AcoustID matched, with the new opt-in
  `--submit-isrc` and its Setup-tab toggle. Only codes the service does not
  already have are sent: the recording lookup that enrichment performs supplies
  the known set, codes another file already contributed are merged, and an
  invalid ISRC is reported and skipped rather than shipped. A dry run prints and
  logs the exact XML payload — generated by the same function that builds the
  live request, with recordings and their codes sorted, so the document reviewed
  is byte-for-byte what a live run posts — and a live run needs a token from
  `MUSICBRAINZ_TOKEN` or the encrypted store (OAuth with the `submit_isrc`
  scope; the deprecated application-token/Digest path stays available on the
  CLI via `--mb-auth app-token --mb-user`). The token is never accepted as a
  command-line argument. A submission is a pending public edit that MusicBrainz
  keeps open for review for seven days, so refusals are reported and never
  retried, and no submission outcome changes a file's result status. The
  outcome is reported where the user is already looking, not only in the run
  log: the Results tab shows the status and, for a refusal, its reason (in the
  error colour, so a rejected or unauthorised submission is not mistaken for
  success); the CLI prints the same line to stderr; and a batch started from
  the Master Driver records it against the Audio Fingerprinter step, whose
  report stays on screen while it carries such a note instead of auto-hiding
  half a second after the batch finishes.
- **Batch reports carry each tool's caveats.** A tool that finishes with
  something the operator still has to know — CD Ripper tracks that did not rip
  (including the ones verification rejected), files a tag writer skipped or
  could not update, conversions skipped or failed — now records one line that
  the Master Driver shows on that tool's step in the batch report, so a partial
  outcome is not left behind in a run log nobody opens mid-batch. The enrich
  analyzers report the tracks they finished without a result for: BPM Analyzer
  the files whose detection failed, Tempo Analyzer the files carrying no BPM
  tag to derive a marking from, and Mood Analyzer the files with no usable
  audio (undecodable or silent) plus any it could not analyse at all. A note
  never changes a step's status: a refused submission or a skipped file is not
  a failed run. The report stays on screen while it carries a note instead of
  auto-hiding when the batch ends, the note is cleared before each step so a
  previous batch's caveat can never be attributed to a new run, and every tool
  that records one is locked to its real manifest id by
  `tests/test_run_outcome_contract.py`, so a note can never be written under a
  key the driver does not read.
- **CD Ripper: AccurateRip confidence and a manual re-rip of flagged tracks.**
  Every track's verification result now carries the matching database record's
  confidence — the number of other rips that submitted exactly these track
  checksums — and is displayed in EXACT Audio Copy's familiar wording:
  `Accurate (confidence N)`, `Rip-twice verified`, `Not in database`,
  `Unavailable (offline)` or `Not accurate`. There is deliberately no invented
  "accurate vs confident" threshold: one agreeing submission is a match and is
  shown as confidence 1, and when several database records match a track the
  strongest count is the one reported. A failed track can now be re-ripped on
  demand from the Results tab; the action runs only the flagged track numbers
  and replaces their rows, leaving every other result untouched, and nothing is
  ever retried automatically.
- **Audio Fingerprinter: MusicBrainz enrichment and ISRC tags.** AcoustID
  matches can now be enriched from the MusicBrainz database itself: the
  matched recording's ISRCs and its release's date, label and country are
  retrieved (`--musicbrainz`, off by default), and the ISRCs can be written in
  each format's native convention with the new opt-in `--write-isrc` (`TSRC`
  for MP3/WAV/AIFF/DSF, the `----:com.apple.iTunes:ISRC` freeform atom for
  M4A/MP4, an `ISRC` comment/item for FLAC/OGG/Opus/WV/APE/MPC). MusicBrainz
  also settles an AcoustID near-tie the file's own tags could not, but only on
  evidence that separates the candidates — title+artist, then album, then ISRC
  presence — and never overrides a tie it cannot resolve. One rate-limited,
  caching client serves the whole run, so an album costs one request per
  unique recording plus one per unique release at MusicBrainz's documented one
  request per second. An unavailable service degrades the file to its
  AcoustID-only result instead of failing it. The GUI (Setup tab), the Master
  Driver card and argv builder, and the CLI reference all expose the two new
  options.

### Changed

- **Audio Enhancer: the Custom DSP controls moved into their own window.** The
  nineteen Custom controls needed 745 px and pushed the Setup tab to 1274 px
  against 887 px available at the shipped 880x980 window, so the lower controls
  could not be reached and the BEGIN ENHANCEMENT button was not drawn at all —
  maximising did not help, because the tab still needed more than the ~988 px
  a 1081 px-tall display provides. Selecting Custom now shows a one-line
  summary with a **Configure Custom DSP…** button that opens a non-modal,
  scrollable editor; the editor writes into the same values the run reads, so
  it can stay open while a batch starts. The start button is now packed before
  the options, so no preset state can clip it.

### Fixed

- **The Master Driver's Audio Enhancer card could not select Custom.** The
  ENRICH card's preset combobox was a hard-coded three-name tuple, and the
  standalone GUI's `--preset` parser declared the same three as its only valid
  choices — so Custom was offered by the tool's own selector and by the suite
  CLI, but rejected with an argparse error when the driver launched the tool.
  Both vocabularies are now read from the shared `PresetName`, so the card
  lists every preset the tool accepts and one edit keeps every entry point in
  step.
- **The REFINE tab's Audio Enhancer now uses the same Custom DSP editor as the
  standalone tool.** Selecting Custom there still expanded all 19 controls
  inline inside the stage panel (745 px), so the REFINE tab ran past the
  desktop height and the lower controls could not be reached — the editor fix
  had only been applied to the standalone window. The stage now shows the same
  summary row and opens the same non-modal editor, which mirrors its values
  into the stage config the pipeline reads, and still hides Output Gain while
  the Normaliser stage owns the final level.
- **Audio Enhancer: one Preset control instead of two.** The Setup tab showed
  "Presets:" (saved suite presets) and "Enhancement Preset:" (built-in DSP
  presets) as two near-identical comboboxes two rows apart that did different
  things — one only changed DSP values, the other also restored the saved
  paths. A single selector now lists the built-in presets first, then the
  saved ones below a display-only divider, with a caption naming the kind and
  the built-in preset a saved entry carries. Delete is greyed out for built-in
  presets, and deleting the selected saved preset falls back to the built-in
  preset still in use instead of leaving the selector blank.
- **Audio Enhancer: a pre-filled `--preset` now applies that preset's values.**
  The selector changed but the run kept the previous preset's parameters, so a
  Master Driver or scripted launch quietly enhanced with the wrong DSP
  settings. A pre-filled preset now runs the same update a combobox pick runs.

## [1.1.0] - 2026-10-16

### Added

- **Wider input-format support across the suite.** The shared audio-extension
  list now recognises WavPack (`.wv`), Speex (`.spx`), Monkey's Audio (`.ape`),
  Musepack (`.mpc`) and DSD (`.dsf`) alongside the existing formats, so every
  tool discovers them. The Music Format Converter classifies SPX as lossy and
  WV/MPC/DSF as lossless, and documents APE, MPC and DSF as detect-only inputs
  with no available encoder. The Audio Normalizer handles WavPack and Speex via
  the FFmpeg loudnorm path, and the Audio Enhancer reports the five formats its
  DSP engine cannot re-encode as a clean skip instead of a decode error.
- **Optional DSP effects** (Audio Enhancer, and Audio Refinery under the Custom
  enhancement preset): Reverse audio, Karaoke (mid/side centre-vocal removal
  with a 0.0-1.0 strength), Phaser, Flanger and Chorus. All default to off, so
  output is byte-identical to 1.0.1 unless an effect is enabled. Available in
  both GUIs and on the CLI (`--reverse`, `--karaoke/--no-karaoke`,
  `--karaoke-strength`, `--phaser`, `--flanger`, `--chorus`). A dry run never
  applies effects.

### Fixed

- **Audio Enhancer: unreadable formats no longer masquerade as corruption.**
  Files in the wider input set that the enhancer cannot decode (`.wv`, `.spx`,
  `.ape`, `.mpc`, `.dsf`) were reported as "The file format is invalid or
  corrupted."; they are now a clean skip naming the format.
- **Audio Enhancer: a loaded preset is now applied.** Applying a saved preset
  updated the displayed parameters but not the values the worker actually ran
  with, so a saved preset had no audible effect. The run parameters now carry
  the loaded preset.
- **Audio Refinery: enhancement sliders and effect toggles now persist.** The
  enhance panel's sliders wrote to a discarded local dict rather than the run
  configuration, so slider changes were lost on start; they now write back to
  the config, and the new effect toggles are wired the same way.
- **CD Ripper import crash when `discid` is installed without its native
  library.** `cd_ripper` guarded `import discid` against `ImportError` only, so
  a machine carrying the Python wheel but not the `libdiscid` shared library
  (Linux `libdiscid.so.0`, Windows `discid.dll`) aborted the entire package
  import with `OSError`/`FileNotFoundError` - taking the CD Ripper down before
  it could fall back to the FFmpeg TOC path. The guard now catches `OSError` as
  well.

## [1.0.1] - 2026-10-14

Everything below landed after `1.0.0`. The items are grouped Keep-a-Changelog
style and worded against the behaviour actually shipped; the per-item evidence
lives in `PLAN_iteration5_remediation.md` through `PLAN_iteration9_golive.md`
and in `PLAN_bughunt_remediation.md`.

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
- **Local `.lrc` sidecar lyrics** (Lyrics Manager). A new `sidecar` provider
  reads the `.lrc` file co-located with each audio track (same stem, `.lrc`
  extension) — no network access. Selectable with `--provider sidecar` on
  the CLI or in the GUI provider list.
- **Project documentation baseline.** A packaged `README.md` (quick start, a
  27-tool index drift-locked to the tool manifest, architecture overview,
  ffmpeg install instructions and an explicit platform-support matrix), the
  GPL-3.0 `LICENSE` with PEP 639 SPDX package metadata, and `CONTRIBUTING.md` /
  `SECURITY.md`. Each ffmpeg-dependent tool's generated guide also gains a
  "System Requirements" section with per-platform install hints, worded from a
  machine-readable source and locked by test.
- **Key Detector `analyze_key()`.** A richer analysis entry point returning
  `KeyAnalysis` — key, confidence, winner/runner-up correlations and a
  low-confidence flag — alongside the unchanged `detect_key`.

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
- **CLI reference defaults corrected against introspected click behaviour.**
  The `--dry`/`--live` default for Album Genre Tagger, Album Art Sync,
  ASX Playlist Extractor, and Lyrics Manager was documented as "dry" when
  every command's actual default is live; the `--stages` default for Audio
  Refinery was documented as "all five" when the click option defaults to
  `declick,trim,enhance,normalise`. A lock test now introspects every
  documented default against the live click commands.
- **Key detection now defaults to cosine correlation** (Key Detector). The
  engine gained a measured low-confidence threshold (0.25) and reports
  `Unknown` for atonal/noise material instead of fabricating a confident key;
  Pearson is retained but documented as compatibility-only.
  `detect_key_with_strength`'s second element is redefined as *confidence*
  (the Mood Analyzer's valence weighting was made self-neutralising).
  *Opt-out:* `correlation="pearson"` still selects the old engine.
- **Low-confidence key results are no longer written to `KEY` tags.** The
  status reports `DETECTED (not tagged)`, an existing `KEY` tag is never
  overwritten, and `KEY="Unknown"` can no longer poison a later Dry Run.
- **Python 3.10 support dropped; the floor is now 3.11** (breaking). The
  3.10-only lock resolved a stale numpy/scipy stack nobody developed or
  shipped against; CI now runs 3.11 / 3.12 / 3.14. 3.10 users must upgrade.
- **`audiosuite --help` groups subcommands by function** (Analysis, Tagging,
  Repair, Utilities) and **`--version` reads the version from
  `pyproject.toml`**, so a source checkout no longer reports a wrong or
  missing installed-distribution version.

### Fixed

- **ReplayGain peak tags were written in dBFS instead of linear amplitude.**
  `REPLAYGAIN_TRACK_PEAK` / `REPLAYGAIN_ALBUM_PEAK` carried the raw ffmpeg
  `Peak: <x> dBFS` measurement (e.g. `-0.500000`) while the ReplayGain
  convention — and the tag writer's own contract — requires a linear sample
  value in `0.0–1.0`. The peak is now converted at the tag-string boundary
  (`10 ** (peak_dbfs / 20)`, so −6 dBFS becomes `0.501187`), and the album
  peak is the maximum of the *linear* peaks rather than the largest dBFS
  value.
- **A fully silent source file was emptied by Silence Trimmer.** Leading plus
  trailing silence covered the entire file, so trimming produced an empty
  segment that the processor exported over the original — truncating it to a
  few dozen bytes and destroying its content. Wholly silent files are now
  reported as a non-destructive `SKIP` ("Entire file is silence - skipped")
  and left byte-identical, in both Dry Run and Live Update.
- **Five standalone tools silently ignored every Master Driver argument.**
  `File Reorganizer`, `Tag Field Updater`, `Library Statistics`, `CD Ripper`,
  and `Album Art Normalizer` received the driver's CLI argv (output dir,
  format, mode, etc.) but never parsed it — every pre-fill was lost. Each
  tool now has a `utils/cli_args.py` parser and consumes its driver argv:
  File Reorganizer pre-fills source/destination/action/patterns; Tag Field
  Updater pre-fills directory and gains a visible Dry Run checkbox; Library
  Statistics pre-fills directory/incremental/refresh/exports; CD Ripper
  pre-fills output-dir/format/cue and filters the rip list by `--tracks`;
  Album Art Normalizer maps `--size <pixels>` to the resolution combobox.
- **Library Statistics' Master Driver card showed two non-functional controls.**
  The "Show tag completeness analysis" checkbox and "Detail Category" combobox
  had no matching GUI behavior — the driver passed `--completeness`/`--detail`
  to a tool that ignored them. Both controls and their driver arguments have
  been removed.
- **The suite log was flooded with per-file processing noise, burying real
  failures.** `logs/audio_suite.log` held every DEBUG/INFO record from every
  first-party logger — per-file tag fallbacks, successful subprocess calls,
  per-file progress — so a 10,000+ line file made spotting a WARNING or ERROR
  impractical. File logging is now two-tier: the suite log keeps the startup
  lifecycle line plus WARNING and above, while each program's full diagnostic
  detail moves to `logs/<program_name>.log`. Test runs are redirected to a
  scratch directory, so they no longer write into the shipped `logs/` tree.
- **The undo history dialog showed wrong tool names.** Its hardcoded
  id-to-name table had drifted from the tool manifest: `asx_extractor` and
  `file_reorganizer` used short names that no longer matched the registry, and
  `audio_fingerprinter`, `lyrics_manager`, `silence_trimmer` and `tag_editor`
  were missing entirely (so their ids rendered raw). The four entries were
  added and the two stale names corrected to the manifest names.
- **CD ripper C2 diagnostic button crashed on `AudioIOError`.** `_run_c2_diagnostic`
  caught `(OSError, RuntimeError)` but `AudioIOError` inherits `AudioSuiteError`
  which inherits `Exception`, so an `AudioIOError` from the drive handler escaped
  the except and crashed the UI. The tuple now includes `AudioSuiteError`.
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
- **Suite-config saves could silently overwrite another tool's save.**
  `save_value` ran its read-modify-write from a process-local snapshot taken
  *before* the cross-process lock was acquired, so two tools starting
  together could clobber each other's write (reproduced with two processes).
  The cache is now dropped the moment the lock is acquired, so every locked
  read-modify-write starts from the file on disk.
- **`--target-lufs` was accepted unvalidated by the `normalise`, `refine`
  and `replaygain` CLIs.** An out-of-range target (e.g. `999`) passed
  argument parsing and reached the loudness pipeline unchecked. All three
  commands now validate at parse time and reject with
  `Target LUFS must be one of: -12, -14, -16, -18, -23`, and each option's
  help names the permitted values.
- **LUFS defaults disagreed with the interfaces and docs they drive.**
  The normalizer's argument record defaulted to −16 LUFS while its click
  option, GUI and user guide all say −14 — applying CLI arguments silently
  rewrote the GUI's −14 back to −16 — and the ReplayGain CLI defaulted to
  −14 while its GUI, argparse path and examples use −16. Defaults now match
  their surfaces: normalizer −14, ReplayGain −16, Refinery −16 (unchanged).
- **`--end` / auto-close is now honoured in Noise Reduction and Pop &
  Click Remover.** Both previously logged an 'ignored' warning and stayed
  open when the Master Driver requested auto-close on completion (decision
  J2).
- **Tool-package and CLI records now reach the suite log file.** Only the
  `audio_suite.*` logger tree was attached to `logs/audio_suite.log`, so
  `getLogger(__name__)` calls in the first-party tools and every CLI run —
  which configured only a stderr handler — wrote nothing to the file.
  `configure_logging` now lives in the Tk-free
  `audio_suite_shared/logging_setup` (re-exported from `app_bootstrap`), and
  attaches the same rotating handler to every first-party package logger;
  the CLI passes its `--log-level` as the package level so verbosity still
  follows the console setting.
- **Undo now restores whole-file bytes, not just tags.** An in-place repair
  (Noise Reduction, Pop & Click Remover, and anything routed through the
  shared in-place write site) can be reverted byte-for-byte to the original
  file; previously only tag payloads round-tripped and the audio stayed
  modified. *Migration:* the undo budget is unchanged (50 entries / 1 GiB)
  but whole files now count against it, so oversized batches prune
  oldest-first as whole batches — keep your own backups for large runs.
- **Noise Reduction Dry Run reports repairable files honestly.** A file that
  would be repaired now reports `FOUND` instead of `SKIP ("Clean")`, matching
  Pop & Click Remover's semantics and what the user guide already documented;
  writes are still withheld at the write site.
- **A missing or fake `ffmpeg`/`ffprobe` is diagnosed at launch and by the
  finder.** Every `.pyw` launcher warns at startup (with install hints) when
  the binary is absent instead of dying with an opaque error on the first
  file, and the finder no longer accepts a *directory* named `ffmpeg(.exe)`
  as the executable.
- **A corrupt file decoding to an empty array no longer crashes the analysis
  tools.** The shared "too short to analyse" check raised `ZeroDivisionError`
  on a zero sample rate; Key/BPM/Tempo/Mood now return the typed
  `AudioAnalysisError` / batch error result.
- **Music Format Converter overwrote one output when two sources mapped to the
  same name.** Two same-stem files with different extensions in one folder
  (e.g. `song.flac` + `song.wav` → `song.mp3`) both converted to the same
  output path, so the second silently replaced the first and the run still
  reported both as converted. Each computed output path is now claimed before
  conversion: the first source wins and the colliding source is reported as a
  `SKIPPED` "already produced from another source" line, with its original
  left intact under `--delete-originals`.
- **File Reorganizer silently overwrote an existing destination file.** A
  copy/move whose resolved target path already existed (a pre-existing file, or
  two sources whose tags resolved to the same name) replaced it with no
  warning — and the undo record stores only the paths, so the overwritten
  bytes were unrecoverable. The action now skips such targets, reports
  `SKIPPED (destination exists): <target>` and counts them in the skipped
  total instead of the processed total.
- **An internal error crashed the Album Art Sync CLI with `AttributeError`.**
  `resolve_and_apply` could return `None` on an unexpected error while its
  callers assumed a report object existed, so the run ended with
  `FATAL: 'NoneType' object has no attribute 'total_files'` and no usable
  summary. It now returns a `success=False` report with a readable
  `Error: ...` line, and the detailed traceback is kept in the log file.
- **One un-embeddable file aborted an entire Album Art Sync batch.** The
  per-file embed step caught only `OSError`/`ValueError`, but a corrupt or
  invalid file raises `AudioSuiteError`, which escaped the per-file handler and
  stopped the whole album mid-run. The handler now includes `AudioSuiteError`,
  so the offending file is reported as a skipped warning and the remaining
  files are still processed.
- **A valid, gain-saturated MP3 was reported as "no valid frames".** When every
  `global_gain` field of an MP3 already sat at the `0`–`255` clamp bound, a gain
  that changed nothing was counted as "zero frames found", so a batch marked a
  perfectly good file as errored with `No valid MPEG Layer III frames found`.
  The frame walk now distinguishes frames *seen* from frames *changed*: an
  already-saturated file is a silent no-change success, and the error is raised
  only for a genuinely frame-less file.
- **Music Format Converter could delete a source file with no undo record.**
  With `--delete-originals`, the source was removed *before* its undo snapshot
  was written, so a failure to record the snapshot left the file gone with
  nothing to restore it. The snapshot is now taken first, and a snapshot
  failure aborts the delete (reported as `DELETE FAILED`) so the original stays
  on disk.

## [1.0.0] - 2026-09-26

First recorded baseline. Package metadata, releases, and this changelog start
here; this section also records the notable changes *contained* in the
baseline, which were delivered by the pre-release plan set —
`PLAN_audit_remediation.md`, `PLAN_audit_priority_actions.md`,
`PLAN_iteration2_remediation.md` … `PLAN_iteration4_remediation.md`,
`PLAN_dsp_normalization.md`, `PLAN_basesetupframe_refactor.md`,
`PLAN_format_support_expansion.md`, `PLAN_graceful_dir_validation.md`,
`PLAN_quality_baselines.md`, `PLAN_phase3_implementation.md` and
`PLAN_gap_analysis.md` — with per-item evidence and gate records in those
files.

### Added

- Initial distribution baseline: 27 registered tools across the Enrich /
  Utility / Refinery categories, the Master Driver control panel, the
  shared `audiosuite` CLI, and the `audio_suite_shared` foundation layer.
- **Audio Fingerprinter** (new tool). AcoustID/Chromaprint identification of
  unknown tracks via the bundled `fpcalc` binary and the AcoustID API: GUI,
  Master Driver card, `audiosuite fingerprint` CLI, encrypted API-key
  storage, rate limiting, and tag-aware near-tie resolution for ambiguous
  scores. Album mode (`--album-mode`) groups candidates by MusicBrainz
  release group so album consensus decides remix-vs-original near-ties.
- **Lyrics Manager** (new tool). Batch synced-lyrics fetch-and-embed from
  LRCLIB with per-format embedding (ID3 SYLT, Vorbis `SYNCEDLYRICS`, plain
  `USLT`/`LYRICS`/`©lyr` fallbacks), a three-tab GUI, Master Driver card and
  `audiosuite lyrics` CLI (`--skip-existing` on by default).
- **Tag Editor** (new tool). Freeform batch tag editing over an editable
  library grid — bulk set/clear/swap/case-convert operations under one undo
  batch, plus CSV import/export (`tag-edit PATH --csv FILE --dry`), written
  as lossless tag-frame edits.
- **Sample-rate and bit-depth conversion** (Music Format Converter).
  Presets from 44.1 kHz to 192 kHz plus a `source` passthrough, WAV/AIFF
  bit-depth selection, and `--sample-rate` / `--bit-depth` CLI flags.
- **Lossless MP3 volume adjustment** (Audio Normalizer `--mode lossless`,
  ReplayGain `--apply-gain`, Format Converter `--normalize-mp3`). A pure-
  Python MP3Gain-style `global_gain` rewrite — no re-encode, file size
  unchanged — validated by decode-and-measure tests across MPEG-1/2/2.5,
  mono to joint-stereo, CBR and VBR.
- **CD rip verification and read-offset correction** (CD Ripper).
  `--verify off|twice|accuraterip` (default `twice`) re-reads and
  cross-checks every track; a MISMATCH blocks the track write so a corrupt
  rip is never silently saved. Per-drive read-offset detection
  (`--detect-read-offset`) aligns both the verification windows and the
  extracted audio for drives whose raw stream runs off the sector grid.
- **CUE sheet support** (shared + CD Ripper + CLI). Strict CUE
  parse/generate/split (`audiosuite cue ...`), one `.cue` per ripped album,
  and a "Split CUE..." action that splits single-file images into tracks.
- **Noise Reduction** (new tool) and a fifth Audio Refinery stage. 50/60 Hz
  hum removal with harmonic notch filtering plus broadband spectral gating
  from a user-selected noise-print region; `audiosuite reduce` CLI, GUI,
  Master Driver card, and `--reduce-noise` pipeline stage (off by default).
- **A/B audition** (Audio Enhancer, Refinery, Normalizer, Pop & Click
  Remover, Silence Trimmer). "Play Original" / "Play Result" buttons on
  every Results tab so before/after can be heard before committing.
- **Tag Completeness Dashboard** (Library Stats). A colour-coded per-tag
  coverage tab with a missing-files viewer and CSV/JSON export;
  `audiosuite stats --completeness` on the CLI.
- **Broader format support.** MP4 (AAC 192/256/320 kbps) as a conversion
  target and AIFF/AIF as lossless targets; Album Genre Tagger, Album Art
  Normalizer, Metadata Scrubber and Tag Field Updater all extended from
  MP3-centric handling to the suite's nine canonical formats; WAV added to
  the CD Ripper's GUI output list.
- **Four orphan DSP tools registered in the Master Driver** (Audio
  Enhancer, Audio Normalizer, Pop & Click Remover, Silence Trimmer). They
  previously existed only as standalone launchers and now work as full
  Driver cards in batch runs.
- **Audio Refinery file-integrity gate.** Corrupt, truncated or implausible
  files are rejected up front with a clear message instead of failing
  mid-chain.

### Changed

- **WAV output is depth-preserving by default** (Music Format Converter). A
  24/32-bit or float source is no longer silently reduced to 16-bit; an
  explicit 16/24/32-bit/float override remains available. *Migration:*
  users who want 16-bit WAV must select the override.
- **Unknown extensions are rejected, not silently re-encoded** (Audio
  Normalizer). Unmapped files were re-encoded to MP3 while keeping their
  original extension — a quality-corruption path; they now fail with a
  clear error.
- **Master Driver refuses a non-existent folder up front** and surfaces a
  failing module as a readable "Module Error" dialog while the batch
  continues, instead of a silent thread death that left Run stuck on
  "PROCESSING…". Ten tools' CLIs likewise print a tool-prefixed reason to
  stderr for invalid folder paths.
- **Deleted-file undo storage is bounded by size as well as count**
  (`undo_max_bytes` suite-config key, default 1 GiB). *Migration:* automatic
  — legacy undo databases convert once on first connect.
- **Tool preferences moved to the shared `audio_suite_config.json`**
  (File Reorganizer, CD Ripper), with a guarded one-time migration that
  retires the legacy tool-local files.

### Fixed

- **Lossless MP3 gain applied wrong, asymmetric gain to stereo files**
  (headline). A requested +6 dB produced −0.28 dB left / −2.20 dB right due
  to incorrect side-info bit offsets and updating only one of four
  `global_gain` fields per stereo frame; low-sample-rate (MPEG-2/2.5) files
  were only half-gained by a frame-walker skip. CRC-protected and
  free-format MP3s are now rejected with a clear error instead of having
  their gain fields silently corrupted, and failed files no longer record a
  phantom undo row.
- **Audio Enhancer Dry Run overwrote source files.** The flag never reached
  the write site; an "in-place Dry Run" rewrote the user's originals. Writes
  and tag copies are now genuinely withheld, with measurements still
  reported.
- **CD Ripper's CLI crashed on every `--format` value.** Lowercase click
  choices were looked up in a display-name-keyed table; resolution is now
  case-insensitive at both ends.
- **Tag Editor correctness:** undo of newly created tags on previously
  tagless files now removes them; clearing the last tag frame persists
  again (`is not None` save guards); the Vorbis handler creates tags on
  tagless FLAC/OGG/Opus; successful rows no longer report "Unknown error";
  and CSV import paths are contained to the chosen library root instead of
  allowing `../..` traversal to retag any file on the machine.
- **Library Stats concurrent scans raised "database is locked."** SQLite
  access is now serialised with a shared lock and proper busy timeouts.
- **`Pop_Click_Remover.pyw` never worked standalone** (missing entry point).
- **A hung per-file conversion no longer stalls the whole batch** (Music
  Format Converter); it fails that file with a mapped timeout error. The
  same per-file error containment was applied to crashing workers in Genre
  Sync, Silence Trimmer, Noise Reduction, Pop & Click Remover and Metadata
  Scrubber, and Genre Sync's completion totals are now accurate.
- **Broken Help buttons** (Mood Analyzer, Album Art Sync and others) and a
  suite of swallowed-error paths (launchers, key-file ACL hardening, legacy
  undo rows) now report properly.

### Removed

- `.wma` from Metadata Scrubber discovery — it was advertised but every
  `.wma` failed to load.
