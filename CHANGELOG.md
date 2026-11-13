# Changelog

All notable changes to AudioSuite-Pro are documented in this file.

This file records what a **user** can observe: a tool's behaviour, a flag or a
default, a supported format, an error message, a workflow step, or a measured
speed or size difference. Entries are written in plain English, with British
spelling, so that someone who uses the suite can follow them without reading
the code. Developer-facing changes — the release gate, CI, the tests, tooling,
behaviour-neutral refactors and dependency bumps no output sees — are recorded
in [TECHNICAL_CHANGELOG.md](TECHNICAL_CHANGELOG.md) instead, so a reader
deciding whether to upgrade is not handed them in between.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions of the tools are released together with the suite (the single
`version` in `pyproject.toml` covers the whole distribution).

Each released section is grouped under `### Added`, `### Changed`,
`### Deprecated`, `### Removed`, `### Fixed` or `### Security`, in that order,
and every bullet belongs to exactly one of them.

## [Unreleased]

### Added

- **The Audio Refinery's Dynamics stage has its own Setup panel.** Tick the
  stage, open Settings, and you can set the compressor (threshold, ratio,
  attack, release and makeup gain) and the limiter (ceiling, lookahead and
  release). The range each control accepts is printed beside it, and a value
  outside that range is reported in the panel and kept out of the run. Loading a
  preset or launching from the Master Driver shows the settings the run will
  use, and SELECT ALL includes the stage.

- **The Audio Refinery can now even out a track's dynamics.** A new Dynamics
  stage adds a compressor, which turns down the loudest passages so the quieter
  ones can be heard, and a true-peak limiter, which stops the output going
  above a ceiling you set. It runs after Parametric EQ and before Audio
  Enhancement. On the command line, `refine --stages dynamics` runs it, and any
  one of `--comp-threshold`, `--comp-ratio`, `--comp-attack`, `--comp-release`,
  `--comp-makeup`, `--limiter-ceiling`, `--limiter-lookahead` or
  `--limiter-release` selects it as well. The run log reports the measured
  maximum and average gain reduction plus the output's loudness and true peak. A
  setting outside its range is refused before any file is opened, a bypassed
  stage leaves the file byte-identical, and copy mode refuses the stage, because
  a stream copy cannot decode the audio.

- **The Parametric EQ has its own panel and a live response curve.** Pick a
  kind of band, type its frequency, gain and Q (how wide the band is), then
  press Add or Update to put it into the run. Selecting a row loads it back for
  editing, and Remove deletes it. The curve under the table is drawn from the
  same filters the run applies, so it shows the shape the file will get, and
  Bypass keeps the bands while leaving the sound alone. High-pass and low-pass
  bands grey out the gain and Q boxes, because the installed engine's
  first-order filters take neither. The stage is included in SELECT ALL on the
  Refine tab.

- **The Audio Refinery can shape tone with a parametric EQ.** A run may now
  stack up to eight bands - low shelf, high shelf, peaking, high-pass or
  low-pass - each with its own frequency, gain and Q, where the enhancement
  presets offer only three fixed shelves. On the command line,
  `refine --eq-band "peaking,1000,2.5,1.0"` adds a band (repeat the flag for
  each one), and `--stages eq` runs the rack; giving a band selects the stage,
  so a flag and a stage list cannot disagree. The rack runs after noise
  reduction and before enhancement, so the preset's compressor and limiter act
  on the shaped signal, and it is saved with the rest of the settings. A band
  at or above the file's Nyquist frequency (half its sample rate) is refused
  rather than moved, and a bypassed or empty rack leaves the signal
  bit-identical. High-pass and low-pass bands are first-order in the installed
  engine: they take no gain and no Q, and one that carries either is refused
  instead of ignored. The Setup tab shows the bands in a table with a live
  response curve, drawn by measuring the filters the run applies.

- **Help > Licences shows the licence texts that ship with your copy.** The
  Master Driver's Help menu has a new **Licences** entry. It opens a read-only
  window listing the suite's own GPL-3.0 licence, the third-party notices, and
  the two bundled programs' LGPL texts together with a record of the upstream
  release each came from. The texts are read from your installation
  (`%LOCALAPPDATA%\AudioSuite-Pro\licenses\`) and fall back to
  `packaging/licenses/` in a source checkout, so the entry works before an
  installer has been built. **Open in default app** hands the selected file to
  your usual viewer, and a copy that ships no texts says so instead of opening
  an empty window.

- **`audiosuite licences` prints the same texts in a terminal.** The command
  prints each document's title and full text, and `--json` publishes the
  inventory: the folder this copy reads from plus each document's title, file
  name and character count. A packaging script or a licence audit can therefore
  read what a build carries without a display. Both views read one source, so
  the command and Help > Licences cannot disagree about what a copy ships. The
  exit status distinguishes a build with no texts (0) from one whose texts
  cannot be read (1).

### Changed

- **The guides spell English the same way throughout.** Every guide's prose now
  uses British spelling - normalised, analyser, behaviour, centre - instead of
  the mix of two that had built up, including in two section headings. The words
  the suite itself ships keep their own spelling: a button caption, an
  operation name, a command name and a folder name are quoted as they appear on
  screen and in a terminal. No instruction, measured figure or setting changed.

- **What's New now reads in plain English.** Every entry in this file says what
  you can do or will see, instead of naming the function, test or module behind
  it, and a term such as LUFS, true peak or dry run is explained the first time
  it appears. Entries that carried a number keep it where the number changes the
  decision to upgrade, and entries were restated in British spelling. Nothing
  about how the suite behaves has changed, and no release has been renumbered:
  this is the same history, written for someone who does not read the code.

- **The Audio Refinery guide explains tone and dynamics in depth.** The guide
  now covers every Parametric EQ band kind, with measured Q width, shelf
  behaviour, a table of fixes by frequency and command-line examples. It also
  covers every Dynamics control, with measured reduction figures, how to read
  the run's maximum and average reduction and output levels, starting points
  for four kinds of job, and what the stage cannot do. A new section, How the
  Stages Work Together, explains the fixed order - why EQ runs before Dynamics,
  and Dynamics before the enhancer and normaliser - and walks an over-bright CD
  rip through the whole chain. Both panels are pictured with Settings open, and
  the chain's complete Dry Run report is reproduced line by line, beside the
  report the same chain writes on a live run, so a reader knows what each stage
  will say before running anything. It also explains what a Dry Run reports in
  Peak target mode.

### Fixed

- **A Dry Run's Normalise line quotes the audio the run will normalise.** The
  preview measured the source file, so with EQ or Dynamics enabled it named a
  starting level and a planned gain the live run would never use: the same
  reference track read -15.9 LUFS in a Dry Run and -20.8 LUFS in the run that
  wrote it. The preview now measures the audio the stages produced, through a
  temporary file it removes before returning, so a Dry Run's Normalise figure
  matches the live report and no file is touched.

- **A Dry Run no longer rewrites files in the Audio Refinery.** The window's
  mode only reached its own display, and the command line only reached the JSON
  summary, so a Dry Run processed and overwrote every file while reporting
  itself as a dry run - including a run started from the Master Driver with Dry
  Run ticked. The mode now reaches the settings the pipeline reads: a Dry Run
  decodes, measures and reports what each enabled stage would do, and leaves
  every file byte-identical.

- **Channel Tools waits when the Master Driver's Auto Start is off.** A launch
  that supplied a folder applied the channel setting immediately and rewrote
  the files, even though Auto Start had not been ticked. Auto Start now decides:
  with it off the window opens with the folder and rule ready and waits for
  Apply Channels, and with it on the batch starts as before.

- **The Audio Refinery accepts a run whose only stage is Parametric EQ.** Both
  the standalone window and the Master Driver's LAUNCH REFINERY answered
  "Please enable at least one Refinery stage" for an EQ-only selection, because
  their check still listed the five stages that came before the EQ stage.

## [2.6.0] - 2026-11-11

### Added

- **A new artwork command: save embedded covers out, or report where they are
  missing.** `audiosuite artwork extract <folder>` writes each file's cover
  beside it as `cover.jpg` or `cover.png`, choosing the extension from the
  image's own bytes so PNG data stored under a JPEG label is not written as
  `.jpg`. An existing cover file is kept untouched, bytes and timestamp
  included, unless you pass `--force`, and `--recursive` covers a whole library
  tree. `audiosuite artwork report <folder>` lists the files with no embedded
  artwork and, with `--min-bytes` or `--min-dimension`, the artwork larger than
  a size you set; it changes nothing on disk. Both commands can publish JSON,
  and a format that cannot hold artwork (a WAV or AIFF rip, say) is reported as
  an outcome rather than a failure. Library Statistics' CSV and HTML exports
  gain `has_art`, `art_bytes`, `art_width` and `art_height` columns, added after
  the existing ones, so a spreadsheet shows which albums still need a cover.

- **Library Statistics reports missing artwork, including on a repeat scan.**
  The Missing Data tab, the console report and the `stats --json` payload now
  say how many files have no embedded artwork, and the run report prints the
  same number. An incremental scan still answers for a library it did not
  reopen, so a repeat scan stays as fast as before; a cache written by an
  earlier version is read once more to fill the fact in, rather than reporting
  a guess.

- **An album view that fills in missing covers.** The new Artwork Gaps tab
  lists every album with files that have no embedded artwork, worst covered
  first. Its Extract Covers button writes a `cover.jpg` (or `cover.png`) beside
  each listed album, taken from a picture a file in that album already has, so
  a player shows a cover without any file being retagged. Dry Run reports the
  same outcome without writing, an existing cover file is kept unless the run
  replaces it, and an album with no artwork anywhere is reported rather than
  changed. The pass writes `library_stats_artwork_log.txt` into the scanned
  folder, and the tab's View Artwork Log opens it.

- **A picture of how much of the library has covers.** The Charts tab now shows
  an Artwork Coverage panel beside its tag charts. It counts the files that
  embed a cover against the rest of the library and prints the percentage, from
  the counts the scan already took. Clicking the panel opens the Artwork Gaps
  tab, so the figure leads straight to the albums it counted.

- **The artwork list and chart keep up with covers you have just written.**
  After a live cover pass, the albums it covered leave the Artwork Gaps list and
  the Artwork Coverage figure counts their files as covered, so the dashboard
  shows the finished work without another scan. A dry run changes nothing, an
  album whose folders were only partly covered stays listed, and the next scan
  measures the files again.

- **Artwork Extractor: a window, and a Master Driver batch step.** Extracting
  covers now has its own window (`Artwork_Extractor.pyw`): pick a folder, set
  the name for the cover file, choose whether an existing one may be replaced
  and whether sub-folders are read, then run live or as a dry run that writes
  only the report. Every run writes `artwork_extractor_sync_log.txt` or
  `artwork_extractor_dry_run_log.txt` beside the files it read, and View Log
  opens it. On the Master Driver's UTIL tab, in the Tags & Artwork section, the
  card carries the same three options, and a batch schedules the window as its
  own step, passing the driver's folder, mode and Auto Start/Auto End settings.
  The step depends on no other step.

- **Exact duplicate matching, by bytes or by decoded audio.** The Duplicate
  Finder can now answer a narrower question beside its fingerprint scan.
  `--exact only` groups files whose bytes are identical - a renamed copy, a
  backup - or whose samples decode identically even when their tags differ, and
  skips fingerprinting entirely; `--exact also` reports both kinds in one run.
  The report labels a byte-identical copy `[EXACT]` and a decoded match
  `[EXACT PCM]`, so the two claims stay distinguishable, and a file an exact
  group already names is not counted again in a fingerprint group. Matching is
  off by default, so an existing scan behaves exactly as before. Hashing
  decodes each file, so the exact modes take longer than a fingerprint scan;
  both hashes are cached beside the fingerprint. The window's **Exact
  matching** control, the Master Driver card and the batch pass the choice
  through, and the JSON payload adds `exact_groups`, `exact_duplicates` and
  `hashed`.

- **A CUE sheet for a folder of tracks, from a window or the command line.**
  CUE Sheet Generator (`CUE_Sheet_Generator.pyw`) describes every file in a
  folder as its own track and writes `album.cue` beside them. A track number
  comes from the file's track tag, then from an `NN - Title` file name, then
  from its position; titles and performers come from the same tags, and you can
  set an album title and artist. A folder where two files claim one track
  number is refused with both file names named, rather than written as a sheet
  a player cannot read. A dry run writes the run report and leaves an existing
  sheet alone. The window is on the Master Driver's UTIL tab and can run as a
  batch step, which uses the driver's folder and mode through the same shared
  builder as `cue generate`.

- **Copy tag fields from a reference file, or from a saved template.** The Tag
  Editor's Setup tab has two new buttons. **Copy Fields…** lets you choose a
  reference track and the fields to take from it, review a per-field comparison
  in a dry run, then apply. **Templates…** saves the selected row's values under
  a name and applies one to a selection. The command line does the same without
  a window: `tag-edit TARGET --copy-from REF --fields title,artist`, where
  TARGET is a file or a folder. Fields the reference does not carry are left
  alone and named in the status line, a file whose format cannot take a field
  is reported with that format's reason instead of being skipped silently, and
  one undo batch covers the whole apply.

- **A peak target beside the loudness target.** The Refinery's Normalise stage
  can now move a file by the difference between its true peak (the highest
  level it reaches between samples) and a target you choose, instead of pushing
  loudness to a LUFS figure: use `--target-mode peak --target-peak -1.0`, or
  the new Target row on the Setup tab. One fixed gain is applied, so a track
  keeps its own dynamics and only its level moves. A file already inside the
  tolerance is left byte-identical, and the stage reports both the sample peak
  and the true peak it measured after writing. A gain that would pass full
  scale is held by the limiter rather than clamped. Peak mode works for WAV and
  AIFF as well as the normalise encoders, keeps a 24-bit source at 24 bits, and
  cannot be combined with Album loudness: choosing one clears the other, and
  the command line refuses the pair.

- **The Normalise stage now writes WAV and AIFF.** Loudness and album mode no
  longer refuse a PCM container: a WAV or AIFF file is normalised in place,
  keeps its own bit depth (a 24-bit master stays 24-bit) and its sample rate,
  and album mode measures a PCM album like any other. A format the stage still
  cannot write is refused with a message whose format list comes from the same
  table that decides it, so the message cannot go stale.

### Changed

- **Key Detector's command line analyses the same 90 seconds as its window.**
  `audiosuite key` defaulted to a 30-second analysis while the window, the
  Master Driver and the argument parser used 90, so a folder read from the
  command line was analysed over a third of the audio the same run would read
  from the window. All of them now read one setting, and Mood Analyzer - already
  at 90 seconds - reads it too; `--duration` still overrides it. BPM Analyzer
  keeps its separately calibrated 30-second window.

- **BPM Analyzer analyses 30 seconds by default everywhere.** The window and the
  Master Driver used to start at 90 seconds while the `bpm` command used 30, so
  the same track could be tagged by one entry point and reported as having no
  discernible beat by another. The window is now one value, and it is the length
  the beat-detection floor was calibrated on: on a 120-track sample of a
  44.1/48 kHz MP3 library, the 90-second window refused 10% of tracks that 30
  seconds analyses. A shorter window is also faster. 90 seconds and any other
  value from 10 to 300 remain available in the window, in the Master Driver and
  as `--duration` on the command line.

- **The Utilities tab is grouped, and alphabetical inside each group.** Nineteen
  cards sat in one flat list whose order was the history of the tool list - ties
  broken by name, each new tool dropped wherever a number was free - so the last
  cards moved without anyone deciding to. The tab now shows six captioned
  sections in workflow order: Convert & Import, Tags & Artwork, Analysis &
  Inspection, Repair & Processing, Organise & File Handling, then Plugins last
  (the bundled Example Tool is the plugin card). Cards are alphabetical inside a
  group, a caption always starts a fresh row, and a card whose Settings are open
  still spans the full width. The order on screen is still the order a
  sequential batch runs its steps in, so a run now follows the grouped list:
  ASX Playlist Extractor and CD Ripper before Music Format Converter, and
  Album Art Normalizer ahead of the tag tools.

- **The Enrich tab is grouped too.** Eleven cards now sit under five captions -
  Tag Cleanup, Identification, Loudness & Genre, Analysis, Artwork & Lyrics -
  instead of one flat stack. Unlike the Utilities groups, these keep their
  existing order: the enrich sequence is the order in which the tools support
  each other (Tempo Analyzer reads the BPM tag BPM Analyzer writes, Album Art
  Sync runs after the tag rewrites), so grouping only adds headings and never
  moves a tool. A sequential batch therefore runs exactly what it ran before.

### Fixed

- **Re-encoding a WAV folder at a new bit depth or sample rate.**
  `convert --format wav --bit-depth 16`, and the window's WAV bit-depth and
  sample-rate controls, used to skip every WAV file as "same format". A
  same-format WAV job is now rendered when it asks for a depth or rate change:
  with a separate output folder the new file is written there, and with the
  default output folder (the input folder) the file is re-rendered in place
  through a temporary file, so the original is only replaced by a complete
  render. A same-format job with no depth or rate change still skips, and WAV
  stays selectable as an output for a WAV folder.

- **Spectrograms report levels below -80 dB instead of stopping there.** The
  Spectral Viewer's colour range can be set up to 140 dB, but every bin quieter
  than -80 dB used to be stored as -80, so a wider range drew a flat floor
  instead of the quiet detail it promised. A -100 dB tone now measures -98.8 dB
  (rounding and windowing account for the rest); the default 80 dB view is
  unchanged, and digital silence still sits at the bottom of the range.

- **BPM Analyzer's verdict no longer depends on a file's sample rate.** Audio
  was analysed at whatever rate the file was stored at, but the beat analysis
  works in fixed-size steps and the "no discernible beat" floor was calibrated
  on 22 050 Hz clips, so a 44.1 or 48 kHz file was effectively scored on
  half-length steps. Genuine music fell under the floor because of that alone:
  two tracks on one album were reported `[SKIP] ... no discernible beat` while
  the other six were tagged, and the same recording could be refused or tagged
  differently depending on how it was stored - `chopin_rubato_74.ogg` was
  refused at 44.1 kHz although it measures 0.124 against the 0.10 floor at
  22 050 Hz. Analysis now converts every file to 22 050 Hz first, so a
  recording's own rate no longer moves its verdict or its BPM: `hiphop_86.ogg`
  reports 86 BPM whether it is stored at 22.05, 44.1 or 48 kHz, instead of 161
  at the higher rates. Tempos from 44.1 and 48 kHz files can therefore differ by
  a beat level from what earlier versions tagged. Skip lines also print the
  measured score to three decimals, so a near miss can no longer read
  `onset periodicity 0.10, minimum 0.10` as though it had passed.

- **Key Detector and Mood Analyzer report the same result whatever a file's
  sample rate.** Both tools analysed at the rate the file was stored at, and
  both of the features they judge depend on that: the key comes from a
  chromagram whose bins follow the decode rate, and the mood engine's beat
  tracking uses the same fixed step as BPM Analyzer. The same recording could
  therefore be tagged two ways - on one album "After Forever" read G at
  22 050 Hz and Gm at 44.1 kHz, and "Into the Void" read C#m against F#, while
  in the test corpus `krautrock_152.ogg` read `Playful;Energetic;Hopeful`
  against `Hopeful;Warm;Playful`. Both now analyse at 22 050 Hz, the rate their
  thresholds were calibrated on. Keys and moods from 44.1 and 48 kHz files can
  therefore differ from what earlier versions tagged, so re-analysing a folder
  is worthwhile if its key tags look inconsistent.

- **`cue generate` numbers tracks the way it always said it did.** The
  reference and the command's own help stated that track numbers come from the
  files' tags, but only an `NN - Title` file name was read, so a folder whose
  names carry no number got one sheet and a tagged album got another. The
  number is now taken from the track tag first, then from the name, then from
  the file's position, and a folder where two files claim the same number is
  refused with both file names named instead of being written as a sheet a
  player cannot follow. `--json` still reports the same fields.

- **A format the Normalise stage cannot write is skipped, not failed.** An MP4,
  WMA or AAC file in a run that included Normalise used to report `Normalise
  stage failed:` with the encoder message, and the work the other stages had
  already done was thrown away with it. The file now reports a skipped stage
  naming the reason and the formats the stage writes, is left untouched, and
  every other enabled stage still runs. A Dry Run predicts the same skip
  instead of promising a normalisation the live run would refuse. The `[SKIP]`
  line shows the reason exactly as written, so format names keep their capital
  letters.

- **The Master Driver guide lists every utility.** Its Utility Tools section
  named ten of the eighteen, and filed Lyrics Manager under Utility although
  the tool belongs to Enrich. The section is now one list per group covering
  all eighteen, and Lyrics Manager appears with the Enrich tools.
## [2.5.0] - 2026-11-08

### Added

- **Join recordings into one file, with a crossfade or a gap between them.** The
  new Audio Joiner (`Audio_Joiner.pyw`, `audiosuite join`) writes a folder's
  files into one output in the order you set, and the Setup tab shows that order
  as a list you can rearrange, with the planned length of the result underneath.
  A crossfade blends each join over the length you give, equal-power so the
  middle of the fade does not dip the way a straight line does; a gap instead
  inserts silence of that length, and asking for both at once is refused with
  both settings named rather than silently picking one. The joined length is the
  segments plus the gaps minus the overlaps, and it is shown before the run
  starts. When every segment already matches the first file's format, sample
  rate and channel count and no crossfade or gap is asked for, the join copies
  the audio instead of re-encoding it, and the run report says so; otherwise every
  segment is re-encoded to the first file's rate and channels. The output keeps
  the first segment's tags. A file name that itself contains a comma - `1-03
  Johnny, Don't Do It.mp3`, say - is still one entry: the split is confirmed
  against the folder's own files, so the order is honoured instead of the name
  being cut at its comma. `--order` names the join order, `--output` names the
  file, and `--gap-ms` / `--crossfade-ms` / `--copy` / `--no-copy` set the
  rest; an empty `--order` joins every supported file in the folder in sorted
  order. A Dry Run reports the plan and the resulting length and writes
  nothing, and each run writes a report beside the folder it read.

- **Split recordings into tracks at their silent gaps.** The new Track Splitter
  (`Track_Splitter.pyw`, `audiosuite split`) finds the silences in a folder's
  recordings with FFmpeg's own silence detector and cuts each one into numbered
  tracks in a `split/` folder beside it, at the source's own bit depth. Three
  settings decide what counts as a gap - the shortest silence, the level that
  counts as silence, and the shortest track worth writing - and a fragment
  below that length merges into its neighbour instead of becoming a stray file.
  The cut lands halfway through the gap by default; `--boundary start` and
  `--boundary end` give the silence to the track before or after it. Leading
  and trailing silence is discarded rather than written as a track, the run
  report says how much, and a wholly silent file is refused with that reason.
  Each run also writes a CUE sheet describing the source image, so the split
  can be re-created or burned with track marks; `--no-cue` turns it off. A Dry
  Run reports the plan per file and writes nothing.

- **Every tool's guide shows the windows it describes.** All 29 tool guides now
  carry pictures taken from the running program: their Setup, Processing and
  Results tabs, the CD Ripper's Rip tab, and the Spectral Viewer, Master Driver
  and Undo Tag Edits windows. Each Processing picture shows that
  tool's own run - its per-file status lines, worker slots and counters - so
  the Metadata Scrubber guide shows a scrub run and the Genre Sync guide a genre
  resolution, never another tool's output.

- **Album loudness normalisation in the Audio Refinery.** The Normalise stage
  gains an **Album loudness** option and a `--album-mode` flag. When it is on,
  the folder is measured once as a single album - ReplayGain's own definition of
  album loudness - and every track moves by that one gain, so the album's
  relative levels survive instead of each file being pushed to the target. A
  track whose peak plus that gain would exceed the true-peak ceiling is limited
  on its own: only that track's gain is reduced, and the run log names it. An
  album already within tolerance plans no gain and leaves every file
  byte-identical; a Dry Run reports the planned gain per file and writes
  nothing. Album mode uses the same encoders as per-file normalisation, so a
  format with no normalise encoder is refused with the same message. The
  Refinery guide also states the shipped target default (-14 LUFS) instead of
  the retired -16.

- **Exact time-range trimming in the Audio Refinery.** The Trim stage gains a
  **Trim by** choice: Silence (the existing behaviour) or **Exact range**, with
  Start, End and Duration fields and matching `--trim-mode exact`,
  `--trim-start`, `--trim-end` and `--trim-duration` options. An exact range is
  cut from the decoded audio, so it is accurate to the millisecond and the file
  is still written once, with its bit depth preserved. **Stream copy**
  (`--trim-copy`) keeps the source's own frames instead: nothing is re-encoded,
  the cut lands on the container's frame boundary, and the run log reports the
  length the copy actually produced together with the offset - an MP3 frame is
  about 26 ms, which is more than the range asked for. Copy mode covers MP3,
  FLAC, M4A/MP4, OGG and Opus and refuses other formats by name; it also
  refuses a run that enables a stage needing the decoded audio (declick, noise
  reduction, enhance or normalise) before the first file is opened, rather than
  quietly re-encoding. A range past a file's end fails that file with both
  lengths in the message, and a range flag without `--trim-mode exact` is
  refused instead of ignored.

### Fixed

- **Every legal file name is a legal input, everywhere.** The suite's file name
  check accepted only letters, digits, `_`, `-`, `.` and spaces, so it called
  names like `1-03 Johnny, Don't Do It.mp3` or `Ships Don't Disappear (Do
  They_).mp3` unsafe - names every supported operating system accepts - while
  the Track Splitter and the CUE splitter each kept their own copy of the
  character rules. There is now one declaration of the characters no file
  system can hold (the Windows-forbidden set plus control characters and
  reserved device names), and the splitter, the CUE splitter and the Audio
  Joiner all use it. Everything else survives: commas, apostrophes, brackets,
  `&`, `#`, `@`, `;`, `=` and non-Latin script. A splitter naming pattern and a
  joiner output name keep their punctuation, and a name the file system
  genuinely cannot hold is refused with the name in the message rather than
  failing at the write.

- **Guides show emphasis instead of asterisks.** Section references written in
  italics used to reach the Word copies as literal `*text*`; they now appear as
  bold text. The Duplicate Finder, Restoration, Tag Editor, Tag Field Updater
  and CLI reference pages are the ones that carried them. A guide the Help
  button opens therefore shows the controls, the worker slots, the per-file
  status lines and the finished summary it describes, with a caption beneath
  each picture, and the same picture renders in the Word copy as in the
  Markdown source. Each picture shows the whole window, so a control docked
  along the bottom edge - BPM Analyzer's Begin button, for one - is in the
  picture rather than cropped away.

## [2.4.3] - 2026-11-06

### Changed

- **Library Statistics Dashboard works in one window of seven tabs.** Setup
  holds the folder, the scan mode and the actions; Processing shows a scan's
  progress and status; Results appears when a scan finishes with the counters,
  the total time, View Log and Open Folder; and Summary, Charts, Missing Data
  and Completeness keep their existing content. The old Cache checkbox and
  Refresh button are now one **Mode**: Incremental Scan (the default), Full
  Scan, or Direct Scan for no cache, with Refresh still starting a full scan in
  one click. The window's title bar and the tab strip match the rest of the
  suite.

- **File Reorganizer works in one window of three tabs.** Setup holds the source
  directory with its Mode / Auto Start / Auto End strip, the presets, the
  destination, the Copy/Move choice and both pattern templates; the planned
  paths, a progress bar and the four counters are on Processing; a Results tab
  replaces the old completion dialog and adds View Log and Open Folder. Dry Run
  is now the Mode selector and still starts selected, so Execute stays read-only
  until you switch to Live Update. Launching it from the Master Driver now fills
  in the `--live`, `--start` and `--end` options instead of ignoring them, and
  saved presets - including ones saved before this change - still restore the
  dry-run state.

### Fixed

- **Every scan writes a report, and View Log opens it.** A scan now writes
  `library_stats_scan_log.txt` into the folder it scanned: the mode and cache
  settings, the format breakdown, the missing-tag counts, and a SUMMARY block
  with the counters and timings. Before this, the dashboard kept its results on
  screen and wrote no run record.

- **File Reorganizer writes a run report, and View Log opens it.** Every run now
  writes `reorganizer_dry_run_log.txt` (Preview, or Execute while Mode is Dry
  Run) or `reorganizer_sync_log.txt` (Execute in Live Update) into the scanned
  Source Music Directory: the run's settings, one line for every resolved path,
  skip or pattern error, and a SUMMARY block with the four counters and the
  elapsed time. The Results tab's View Log opens that report. Before this, the
  tool wrote no run record at all - the per-file detail only reached
  `logs/file_reorganizer.log`, the program's diagnostic log - so View Log
  answered "No log file available yet" even after a live copy.

- **The Master Driver's failure dialog says why a tool did not start.** A tool
  that refused its arguments - a source folder that no longer exists, for
  example - used to reach you as `Module failed: Library Statistics Dashboard
  (exit code 1)`, with the reason visible nowhere: the tool's own sentence went
  to a console a launched window does not have. The dialog now quotes that
  reason under the exit code (for example `Folder path does not exist:
  D:/Music/10cc`), and the tool's log records the same sentence.

## [2.4.2] - 2026-11-04

### Changed

- **Tag Field Updater reports WMA files as unsupported.** Rewriting a `.wma`
  file's genre fields needed a tag writer the suite's shared tag layer does not
  have, so the tool now leaves the file untouched and reports `Unsupported
  format: .wma (WMA carries no tag writer)` instead of changing tags. WMA files
  stay readable and convertible, and no other tool's behaviour changes.

## [2.4.1] - 2026-11-04

### Added

- **WMA is now a first-class format, not a converter-only one.** Every tool that
  lists the suite's formats now finds and converts `.wma` files, which until now
  were visible only inside the Music Format Converter. Writing one produces a
  real Windows Media Audio file (wmav2 audio in an ASF container); tag writing
  is not offered yet, so a tagging tool reports the file as skipped rather than
  damaging it.

- **Raw AAC (`.aac`) is recognised as an input.** Such files are listed and
  converted; tags are not written, because raw AAC carries no usable tag block.
  Use `.m4a` when tags matter.

### Fixed

- **Undo no longer lists a file whose tag write failed.** A tagging tool that
  could not write a file still added it to the run's undo list, so Undo offered
  a file it could do nothing for - and reverting it only rewrote the tags the
  file already had. The failed file is now reported as an error and left out of
  the undo list; files the same run did change are unaffected.

- **An unsupported target extension is refused.** Previously the shared export
  path silently wrote MP3 audio into a file named for the other extension, so a
  file could open fine while its name and its audio disagreed. It now reports an
  error instead.

## [2.4.0] - 2026-11-02

### Added

- **The Duplicate Finder can now delete duplicates or replace them with a
  restorable stub.** The new **On duplicate** control offers **Move to
  quarantine** (the default, unchanged), **Delete (Recycle Bin)**, and **Replace
  with an ASX stub**. Delete and stub both send the duplicate to the operating
  system's Recycle Bin - there is no permanent-delete path - and an interactive
  live run asks for confirmation first. The stub is written beside the duplicate
  and points at the kept file, carrying the duplicate's title, artist, album,
  album artist, track, disc, year, genre and comment plus its MusicBrainz IDs,
  ISRCs, lyrics and JPEG cover art. A dry run reports what it would do and
  changes nothing. The command line gains `--on-duplicate`, and the summary adds
  `deleted` and `stubbed`.

- **Delete and stub runs install Recycle Bin support automatically.** If the
  interpreter running the tool does not have `send2trash` yet, the first such
  run installs it into that interpreter, so you are not asked to run a package
  command. If the install cannot be completed, the run stops before touching a
  file and says so.

- **ASX Playlist Extractor restores a stub's original name and tags.** Run it on
  a folder containing a suite stub and it recreates the removed file from the
  kept audio: the stub's name with the kept file's extension, and the
  duplicate's tag snapshot applied after clearing the tags the copy inherited.
  The restore is built at a temporary path and renamed into place only after its
  tags are written and its audio is checked against the kept file, so a failure
  leaves no half-restored file and keeps the stub. ReplayGain, custom frames,
  chapters and PNG cover art are not carried; the guide records why.

### Changed

- **The ASX Playlist Extractor can include subfolders.** **Include subfolders**
  (or `--recursive` on the command line) finds `.asx` files below the selected
  folder as well as in it; it is off by default, so the existing top-level
  behaviour is unchanged.

### Fixed

- **An ASX playlist written with an uppercase `<REF HREF="...">` is now read.**
  The parser matched only the lowercase element name, so a valid playlist from a
  Windows Media-era writer was reported `NO REF LINK IN ASX`. Element and
  attribute names are now matched regardless of case, and a reference must
  resolve to a regular file with a supported audio extension.
## [2.3.1] - 2026-11-02

### Changed

- **The Utilities tab no longer offers five audio-processing cards, and REFINE
  runs that work instead.** Pop & Click Remover, Silence Trimmer, Noise
  Reduction, Audio Enhancer, and Audio Normalizer have moved out of the tab to
  REFINE's matching stages - declick, trim, reduce noise, enhance, and
  normalise - so one pipeline run covers them, with REFINE's Dry Run reporting
  what each enabled stage would detect. The five are no longer shipped
  separately: their standalone windows, their launchers and their own commands
  (declick, silence-trim, reduce, enhance, normalise) are gone, and REFINE's
  stages carry their full option sets - including the normalise stage's
  true-peak ceiling, loudness-range limit and lossless mode - so nothing needs a
  second window to be reached.

### Fixed

- **Card text and every tool's Run Controls now follow the chosen theme.** With
  Theme Mode set to Dark, or to System on a dark operating system, the Parallel
  Processing checkbox in the Master Driver's BPM Analyzer card and the three
  option checkboxes in its Lyrics Manager card were black on the dark card body
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

- **A REFINE run that changes nothing now leaves the file byte-identical.**
  When no enabled stage finds anything to repair - no clicks, no silence, no
  noise, and loudness already inside tolerance - the file is reported SKIPPED
  instead of being re-encoded, re-tagged and replaced, and it is not counted as
  a completed file. A file that does need work is still written as before. Dry Run
  now reports what the enabled stages would detect (clicks, trimmed silence,
  noise, the enhancement's projected gain, and the loudness Normalise would
  apply) instead of only loading the file, and a normalise-only run makes one
  FFmpeg pass instead of two.

- **Text follows the chosen theme in the states the theme used to miss.** Dark -
  or System on a dark operating system - no longer leaves text black on a dark
  box: the CD Ripper's "Rip Complete!" heading and its CD-insert instructions,
  the Master Driver's caveat notes and its settings footer, the SETTINGS strip
  button, and a checkbox's label while the pointer is over it all now use the
  suite's colours. Buttons that are unavailable until a run starts show readable
  text instead of Tk's own grey, and a checkbox's indicator box is drawn in the
  colour of the card it sits on rather than a fixed white square.

## [2.3.0] - 2026-10-31

### Added

- **The Duplicate Finder finds files that are the same recording, and deletes
  nothing.** A new utility tool fingerprints every file in a folder, groups the
  ones that are the same recording, and reports each group with the copy it
  proposes to keep - chosen by measured quality (lossless first, then bitrate,
  then sample rate, then length), never by tags. The default similarity
  threshold of 0.10 is the measured one: four encodings of one recording scored
  0.0000-0.0002 on the reference set, while the closest pair that must stay
  apart scored 0.1580. A live run **moves** the extra copies into a quarantine
  folder and records every move for undo; the kept copy is left byte-identical,
  a dry run moves nothing, and a second scan skips the quarantine folder so it
  cannot re-find what it moved. Fingerprints are cached, so a rescan of an
  unchanged library does not repeat the work.

- **Restoration (Declip) rebuilds the peaks a clipped recording lost.** A new
  utility tool finds the flat-topped runs a ceiling left behind - measured
  against the file's own peak, so a limiter set below full scale is found as
  readily as a 0 dBFS master - and reconstructs each one by drawing a curve
  through the clean samples either side. On the reference tone the measured
  distortion falls from -21.38 dB to -46.82 dB and the peak returns from
  -1.938 dBFS to -0.188 dBFS against the original's -0.100. A file with nothing
  to repair is **skipped and not rewritten**, a square wave (whose waveform is
  itself flat) is refused rather than rounded, and a repair keeps the source's
  tags, sample rate, channel count and bit depth - a 24-bit source stays
  24-bit.

- **Two new commands and two new windows.** `audiosuite duplicates` reports
  duplicate groups (its JSON payload adds `groups`, `duplicates` and
  `quarantined`) and `audiosuite declip` repairs clipping. Both are in the
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
  files), **View Log** and **Open Folder**, so the old dialog is gone. Setup
  opens with the suite's **Run Controls** strip - **Browse & Scan**, a **Mode**
  dropdown (**Dry Run** / **Live Update**), and the driver's **Auto Start**,
  **Auto End**, **Clear Logs** and **Parallel** settings - and the window now
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
  strip - **Browse & Scan**, the **Mode** dropdown (**Dry Run** / **Live
  Update**), and the driver's **Auto Start**, **Auto End**, **Clear Logs** and
  **Parallel** settings - and keeps the edit controls and the grid below it;
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
  it - so what a run did to which file no longer exists only in `logs/`.

## [2.2.0] - 2026-10-30

### Added

- **The Tag Field Updater can tag from file names.** A library whose only
  information is in its file names could not be cleaned in this suite at all;
  the new source reads a name into tag fields with an ordered list of patterns
  and writes them (`audiosuite tag-update D:/Music --pattern "%track%. %artist%
  - %title%"`). Placeholders are the fields the Tag Editor already writes
  (artist, title, album, album artist, track, disc, year, genre, comment), and
  a pattern that would split a name ambiguously is refused rather than guessed
  at: number fields match digits only, so `05 - Artist - Title` cannot read the
  dash as a track. The mode runs as a **dry run** unless `--live` is passed, and
  prints the parsed fields per file, because a wrong split writes tags the file
  then looks authoritative with. `--only-fill-blanks` (the default) leaves a tag
  that already carries a value alone; `--overwrite` replaces it. Pattern sets
  are saved by name in the shared `audio_suite_config.json`, and a parsed genre
  still goes through the existing slash rule while an artist such as `AC/DC`
  does not.

- **Playlist, HTML and Camelot exports in the Library Statistics Dashboard.**
  The dashboard already read every tag a playlist needs and could only hand
  them out as CSV or JSON. `audiosuite stats --export m3u` now writes an
  extended M3U (an `#EXTM3U` header, one `#EXTINF` line and one absolute
  forward-slash path per file, in album-then-track order, with `-1` for an
  unknown duration), `--export html` writes a self-contained page with no
  external assets, and `--export-columns` picks the columns while `--camelot`
  adds the harmonic-mixing key code. The CSV export keeps its original columns
  and order unless a column set is asked for, so existing users are unaffected.
  The window's Export dialog gained M3U and HTML beside CSV/JSON and a Camelot
  column checkbox. Camelot is a pure mapping from the key the Key Detector
  already wrote, maps both spellings of each enharmonic pair to the same code,
  and leaves a file with no key empty rather than guessing.

## [2.1.7] - 2026-10-29

### Added

- **The Audio Normalizer's true-peak ceiling and loudness range are
  configurable.** `--tp` (default -1.5 dBTP) and `--lra` (default 11 LU) reach
  both loudnorm passes from the command line and from the Setup tab's sliders,
  and each processed file now reports the true peak the re-encode **achieved**,
  so a ceiling the encoder could not hold is visible instead of assumed. A
  ceiling above -1.0 dBTP asks for confirmation first, because a lossy re-encode
  can clip there. The defaults are unchanged, and a re-run at the same target
  stays inside the existing tolerance and is skipped, so no file is encoded
  twice.

- **The metadata scrubber can see WavPack, Monkey's Audio, Musepack, Ogg Speex
  and DSF files.** `.wv`/`.ape`/`.mpc` scrub through their APEv2 items, `.spx`
  through its Vorbis comments and `.dsf` through its ID3 tag; artist, album,
  title and the flagged lyrics, album-artist and artwork items are preserved and
  restored on undo. A scrub stays metadata-only: the decoded duration and
  per-channel RMS are identical before and after, and the undo round trip is
  proved on a real `.wv`. `.wma` is now the only format the scrubber reports as
  unsupported.

### Changed

- **ReplayGain album gain comes from the album's combined signal.** Album
  loudness was a duration-weighted average of each track's loudness, which is
  exact only when every track is measured the same way. Measured on a 20 s
  -10 dBFS plus 20 s -35 dBFS pair, the weighting is 3.00 dB below the combined
  signal's loudness (+2.70 dB against -0.30 dB album gain), and 2.33 dB below on
  an album with a mostly silent tail - both outside ReplayGain's 0.5 dB
  expectation, because the quiet track falls under the combined signal's own
  gate. The folder is now measured once as one continuous stream; the weighted
  formula remains only as the fallback for a folder whose combined signal cannot
  be read, and the folder log says which route was used. The cost is one extra
  read of the album.

### Fixed

- **Normalising no longer resamples every file to 192 kHz - and works again on
  current FFmpeg.** The loudness filter computes at 192 kHz and hands its audio
  on at that rate, and the normalise command never fixed the output rate, so a
  2 s 16-bit 44.1 kHz FLAC came back as a 192 kHz 24-bit file at about ten times
  the size: a silent change of sample rate and bit depth on every normalise
  pass. The same freedom broke the stage outright on FFmpeg builds after 8.0,
  whose FLAC encoder rejects the 384 000-sample block that rate implies
  (`invalid block size: 384000`), so the stage failed on every file. The command
  now fixes the source's own rate (and FLAC's bit depth), skips the fix for
  encoders whose rate set cannot hold it - `opus` takes 8/12/16/24/48 kHz only,
  and an explicit `-ar` also suppresses FFmpeg's own resampler - and caps FLAC
  frames at 4096 samples without padding the last one. Verified on a 2 s,
  44.1 kHz, 16-bit source: -30.95 to -15.95 LUFS, 44 100 Hz and 16-bit on the
  way out, on both FFmpeg 8.0.1 and a current development build.

- **The library cache no longer trusts a modification time alone.** A file
  replaced by one that keeps its timestamp - `cp -p`, a backup restore, a
  same-second rewrite - kept its cached row, so the statistics report served the
  tags of the file that no longer existed. A cached row is now matched on
  modification time *and* size; a row written before the size was filled never
  matches, so it is read once more and heals.

- **Console and log output is ASCII-only.** A cp1252 console - Windows' default
  - cannot encode an em dash, a tick, a ballot X or an arrow, so the affected
  tool raised `UnicodeEncodeError` mid-run instead of printing its status line.
  92 symbols across 25 files were rewritten to their ASCII forms (typography
  stays in comments and documentation, which no console renders), and a check
  now scans every message the programs print so the problem cannot drift back.

- **A 24-bit WAV or AIFF rewritten in place came back 16-bit.** The shared
  export path passed no sample-format argument, so FFmpeg's WAV/AIFF writers
  used their 16-bit default while the rate and channel count survived - a silent
  loss of precision on every in-place rewrite. The exporter now pins the
  source's PCM format (`pcm_s24le` from a 24-bit source, `pcm_s16le`/`pcm_s32le`
  for 16/32-bit) and leaves lossy targets alone. Verified by decoding the output
  of all seven writers: 32 kHz, mono, 24-bit in is 32 kHz, mono, 24-bit out.

- **The guides quoted the wrong worker and format counts.** Every tool sizes its
  worker grid from the logical processor count (capped at eight), not the four
  slots those guides claimed - so on any machine with more than four processors
  the guide disagreed with the window beside it - and the shared format set has
  held fourteen containers since 1.1.0, not nine. The Lyrics Manager guide also
  named status labels (`[LIKE]`, `[ALREADY]`, `[NO MATCH]`, `[PLAIN]`) the tool
  never prints. All 32 guides were read against the code and corrected, and the
  claims of this kind - format counts, worker counts, flags, status labels and
  file names - are now checked against the code, so the next drift is caught
  before a release instead of shipping.
## [2.1.6] - 2026-10-28

### Fixed

- **The Refinery reports a file it cannot read instead of crashing on it.** Its
  file check asked the operating system whether a path existed and was a
  regular file, and on Python 3.11 and 3.12 a locked or permission-denied path
  made that question itself fail - so the whole check ended instead of failing
  that one file with a reason. It now asks once, in a way that always answers,
  and all three answers (does it exist, is it a file, how big is it) come from
  that one look.

- **The Master Driver's menu bar no longer shows a tear-off row above Help.**
  Tk menus carry an optional tear-off entry by default; on some Tk versions it
  is drawn as a dashed line that shifts every entry down by one. The menu bar is
  now built without it, so the entries you see are the entries that act.

## [2.1.5] - 2026-10-27

### Added

- **The What's New panel can open the complete changelog.** The panel only shows
  the releases since the last one you saw, so the rest of the history was
  unreachable from inside the app. A **Full Changelog** button now opens a
  scrollable window listing every released section of this file, newest first -
  version headings, entries and bold lead-ins, drawn by the same reader as the
  panel. Closing it records nothing as seen, so browsing the archive never hides
  the pending notes the panel was opened to show.

- **The full changelog is also on the Help menu.** A **Full Changelog** entry
  opens the same history window straight from the Master Driver, so the archive
  no longer requires opening the What's New panel first. A copy whose changelog
  has no released sections says so instead of opening an empty window.

### Fixed

- **The command reference and the new-user presentation cover all 30 tools.**
  The CLI reference documented the flags of only eight tools and listed 24 of
  the 37 commands in its *All Commands* table; the presentation named 26 of the
  30 tools, and its opening slides claimed "26 Windows desktop tools" and "26
  separate windows" while the suite shipped 30; the README's table listed all
  30, but its opening line still said 27. From the reference or the presentation
  a reader could not learn that Tag Editor, Stem Separator, Spectral Viewer or
  ML Denoiser existed. The reference is now grouped by stage with a section per
  tool, every flag taken from the command line itself; the presentation gains
  two slides plus format-matrix and task-chooser rows, and reads its tool count
  from the tool list instead of quoting a number. Every quoted tool count in the
  README, the contributor and security notes, the documentation pages and the
  guides is now checked against that list, so a stale number fails before a
  release.

## [2.1.4] - 2026-10-26

### Added

- **The CLI commands reference has a Word copy, built like every user guide.**
  `user_guides/reference/CLI_Commands_Reference.md` is now rendered to
  `CLI_Commands_Reference.docx` by the same script that turns each tool's
  Markdown guide into the Word file its Help button opens, so the reference has
  a regeneration path and can no longer be a hand-maintained binary. The source
  gained the same front matter the tool guides use, and its wrapped option
  bullets were joined into one line each, because the renderer ends a bullet at
  the first line that is not indented. `--check` and the guide checks now cover
  the `reference/` folder alongside the per-tool guides.

### Changed

- **CLI commands exit 1 when a batch finishes with errors.** A run that reported
  `1 errors` in its summary and its `--json` payload still returned status 0, so
  a scheduler or script could not tell a clean run from one that converted,
  tagged or normalised nothing. The status now follows the count the run
  printed: **0** clean (including skipped files), **1** completed with per-file
  errors or crashed, **2** a usage error. Only the status changed - `--json`
  documents are byte-identical - and an all-skipped folder still exits 0.
  `audiosuite plugins list` follows the same rule, exiting 1 when it reports a
  rejected plugin. Scripts that relied on 0 after errors will now see the
  failure, which is the point of the change.

### Fixed

- **Tag Field Updater counts a failed file once.** The per-file scan and the
  per-format handlers both added to the error tally, so one corrupt file was
  reported as two errors in the summary and the `--json` payload. The count is
  now taken once, where the failure is classified.

- **Every audio-tool subprocess call goes through the shared secure wrapper.**
  The Audio Enhancer's FFmpeg decode and encode started programs directly, and
  the CD Ripper's Eject button built a PowerShell command string by
  interpolation; both bypassed the allowlist of programs the suite is allowed to
  run. The enhancer now uses the shared wrapper - the raw-audio decode passes a
  new option so its binary output is no longer decoded as text - and drive
  eject/reveal moved into a Tk-free helper: the Windows tray opens through MCI
  from a validated single drive letter (no process, no shell), while other
  systems' eject and the Explorer reveal pass fixed argument lists. A tray that
  refuses to open now says so in a dialog instead of looking like a no-op.

- **A batch no longer starts a step whose dependency failed.** The Master Driver
  added a failed step to the same set that releases its dependants, so a failed
  BPM analysis still let Tempo run - writing tempo markings derived from files
  that were never tagged - and the report counted that step as completed.
  Sequential mode consulted no dependency graph at all and did the same. Both
  modes now mark the dependant **skipped** with the reason on its line
  (`skipped: dependency 'bpm' failed`, or `did not run` when the dependency was
  itself skipped), including every step above it in the chain.

## [2.1.3] - 2026-10-25

### Fixed

- **Album Art Sync reads one configuration file in every run mode.** The window
  and the command-line/batch pipeline worked out the configuration location from
  their own place in the program, so the window read
  `album_art_sync/album_art_config.json` while the pipeline read
  `album_art_sync/core/album_art_config.json`. On an installation where the
  Fanart.tv keys were entered in the window, batch runs found an empty file and
  silently lost that source. Both now read
  `album_art_sync/config/album_art_config.json`. A copy left at either old
  location is moved on first load together with its `.key` - a settings file
  copied without its key cannot be decrypted - and the originals are left in
  place.

- **The Metadata Scrubber no longer offers formats it cannot open.** Its file
  discovery used the suite-wide extension list while the loader handled nine
  formats, so a valid WavPack, Monkey's Audio, Musepack, Speex or DSD file in a
  chosen folder was listed and then reported `[UNREADABLE]` with an error count
  - a failure against a file that is perfectly fine. Discovery and the loader
  now come from one table, so the scrubber offers, samples and processes exactly
  the nine it can scrub: MP3, FLAC, OGG, Opus, M4A, MP4, WAV, AIFF and AIF. Tag
  sampling for the preserve list uses the same table, so it no longer spends its
  100-file budget on files that will not be processed.

- **Audio Enhancer dry runs measure the chain the live run writes.** Dry Run
  bypassed the five effects, so a preview with karaoke, phaser, flanger, chorus,
  reverse or the output gain enabled reported the level of a *different* signal:
  karaoke on a centred mix showed -9.9 dBFS where the written file measures near
  silence. The bypass is gone and both modes run the settings you chose; the
  only remaining difference is that a dry run writes no file and copies no tags.

## [2.1.2] - 2026-10-25

### Security

- **File Reorganizer and CD Ripper refuse paths that escape the destination.**
  Tag values are untrusted input, and the Reorganizer's path resolver kept `..`,
  so a file tagged `album="../../evil"` was copied above the chosen
  destination (the resolver returned `..\..\evil`). The resolver now refuses a
  `.`/`..` component, a drive-qualified value (`C:\Music`) and a
  `\\server\share` value instead of rewriting them, and every destination is
  checked to be inside the chosen folder before anything is written. The CD
  Ripper's file name cleaning no longer returns a bare `.` or `..`, and its
  per-track output path is checked the same way before any folder is created.
  Refusals surface as a pattern error (File Reorganizer) or a failed track (CD
  Ripper) and write nothing.

### Fixed

- **Album ReplayGain is weighted by track duration.** A folder's album gain used
  the plain average of its tracks' loudness, so a ten-second track counted as
  much as a thirty-minute one. The audited pair (10 s at -10 LUFS against 30 s
  at -30 LUFS) was tagged as +4.0 dB where the combined signal needs about
  -0.1 dB. Album loudness is now the duration-weighted mean-square energy of the
  measured files (ReplayGain 2.0-compatible): the same pair is tagged at about
  -0.1 dB, and a real measurement of the folder agrees within 0.2 dB. A file
  whose duration cannot be read is reported as a per-file error instead of
  being counted as zero.

- **ALAC conversions now write an M4A file instead of failing.** Every ALAC run
  failed with `Error initializing the muxer ... Invalid argument`, because the
  output was named `song.alac` and FFmpeg picks its output format from the file
  extension; `.alac` names a codec, not a file format. The converter now names
  each output for its container, so ALAC is written as `song.m4a` and the audio
  decodes identically to the source. ALAC and AAC-M4A share the `.m4a`
  extension, so a later run to either format replaces the earlier file with the
  same name.

## [2.1.1] - 2026-10-24

### Added

- **The example plugin's window opens on the folder and run mode the Master
  Driver was set to.** A launcher receives the same arguments as every tool
  (`<directory> --live|--dry --start|--no-start --end|--no-end`); the example
  ignored all four, so it opened empty and always said live. Its window now
  lives in `example_plugin/window.py` (a `.pyw` launcher cannot be imported, so
  nothing in it could be exercised), reads those arguments with the shared
  parser, and fills the folder and mode through the same path Browse uses. It
  also honours `--start` and `--end`: the report runs as soon as the window
  opens, and the window closes when it finishes, so the Master Driver can launch
  it as a batch step. The folder walk runs on a worker thread and reaches the
  window through a queue the window polls, because a worker thread may not touch
  the window directly. A run that failed stays open so its message can be read
  instead of vanishing with the process.

- **The documentation download is self-contained.** The `docs-html` bundle
  now carries every file its pages link to - `README.md`, `CHANGELOG.md`,
  `CONTRIBUTING.md`, `SECURITY.md`, `packaging/` and the guide sources - plus a
  root `index.html`, so a downloaded copy opens on the front door and its links
  resolve without a source checkout. Twelve links were dangling before: six
  targets the build never published, two links written one directory too
  shallow, and four links to Markdown files that the site publishes as pages.
  Publication to GitHub Pages is not part of this release: Pages cannot be
  enabled for a private repository on the free plan, so the bundle is the
  delivery and every link in it is checked.

### Fixed

- **The bundled example plugin's launcher now opens.** Launching `Example Tool`
  from the Master Driver reported only `Module Error — Module failed: Example
  Tool`: the launcher worked out both directories one level too high, so it put
  the suite root where `plugins/` belonged, importing the plugin failed, and the
  pre-flight check scanned the folder above the suite rather than the suite. A
  failed step's dialog now also names the launcher's exit code, since that is
  the only evidence left once its output is gone.

## [2.1.0] - 2026-10-23

### Added

- **A plugin system: third-party tools and analysis in `plugins/`, enabled one
  by one.** A folder under `plugins/` holding a `MANIFEST.toml` can add a tool
  (command, Master Driver toggle and card, optional launcher), a Master Driver
  card body, a tag processor that runs during `tag-update`, and an analysis
  contribution that runs during `stats`. Manifests are read and validated at
  startup without loading any plugin code, so `audiosuite doctor` and the new
  `audiosuite plugins list` can report a plugin that will not load; a plugin's
  code is loaded only once you enable it (`audiosuite plugins enable <id>`,
  stored with every other preference in `audio_suite_config.json`). A refused
  manifest is listed with the key to fix rather than silently skipped: unknown
  keys, duplicate ids, a command that would shadow a suite command, an
  `api_version` this suite does not understand, a launcher outside the plugin
  folder, and an entry point that escapes the plugin's own package are all
  refusals. Plugin tag edits and plugin analysis figures are counted apart from
  the tool's own (`plugin_updates` / `plugin_errors`, `plugin_analysis` /
  `plugin_analysis_errors`), and `--no-plugin-tags` / `--no-plugin-analysis` run
  a tool without them, so a difference between two runs stays attributable.
  `plugins/example_plugin/` demonstrates all four extension points and is the
  template to copy; the development guide documents the manifest. Plugin code
  runs inside the suite's own process - enabling one is a trust decision, and
  the guide says so.

- **`audiosuite doctor` reports the interpreter a tool will run in, and whether
  its optional engine can be found there.** A stale installation and a launch by
  the system Python look the same from the outside: the package is present, the
  tool still cannot load it. The report now names this process's interpreter and
  the one a `.pyw` launcher would use (the project's `.venv` when it exists),
  then checks the AI tools in *that* interpreter - not in the process running
  doctor - and lists each tool with the command that fixes it. A missing extra
  is reported without failing the check, because the first run that needs it
  installs it.

- **The launchers run from the project's `.venv`.** `uv sync --extra ml`
  installs the AI engines into `.venv`, but a double-clicked `.pyw` is started
  by the system Python - so the tool could not see the extra that *was*
  installed, and the first-run installer wrote a second copy into the system
  interpreter. Every launcher now restarts itself under `.venv` when one is
  present, with the same script and arguments and keeping `pythonw.exe` for a
  windowed launch, before the pre-flight check runs. A checkout without a
  `.venv` behaves exactly as before, and a failed restart continues in the
  current interpreter instead of closing the window.

- **The Master Driver's Stem Separator card can browse for its output folder.**
  The Output Folder setting on the UTIL tab was a plain text box, so the stem
  destination had to be typed even though the tool's own Setup tab has always
  offered a Browse button. The card row now carries that button, opening the
  folder dialog at the current value and leaving the box untouched when the
  dialog is cancelled.

- **The AI tools install their own optional engine on first use.** Demucs (Stem
  Separator) and RNNoise (ML Denoiser) live in an optional `ml` package, and a
  run that needed one stopped with "Demucs is not installed ... uv sync --extra
  ml". That instruction is a dead end for a non-technical user, and it installed
  nothing at all when the window had been started by a different interpreter
  than the one the package was installed into - which is exactly what a
  double-clicked `.pyw` does. The first run that needs one now offers a one-time
  download, installs it into the interpreter that is actually running the tool,
  verifies it by loading it in a fresh process and checking the required
  version, then continues the run by itself. A declined or failed install
  reports why and starts nothing; the Stem Separator's dry run never touches it,
  while the ML Denoiser installs for both modes because a dry run measures with
  the model.

### Fixed

- **A launched Stem Separator opens in the mode the Master Driver shows.** The
  run mode was applied *after* an early return on a missing source folder, and a
  standalone utility launch passes an empty folder slot (the tool opens its own
  window and picks its folder itself). The driver's `--live` therefore arrived
  and was read, then dropped: the separator opened in Dry Run while the toolbar
  showed Live Update. The run mode is a setting of its own and is now applied
  before the folder-gated handshake, the order every other tool already uses;
  the Auto Start / Auto End / Clear Logs / Parallel settings stay behind that
  gate because they describe a run an empty launch cannot target.

- **A module whose required settings are still empty is reported instead of
  launched.** The Stem Separator with no output folder (or no stem ticked) made
  the argument builder return an empty list, and the launcher turned that into a
  launch with no arguments: the tool opened as a bare standalone window with no
  source folder and every setting at its own default, so the Master Driver's
  Live Update never arrived and the separator came up in Dry Run. LAUNCH now
  names the modules that still need settings and starts nothing, and the Stem
  Separator card states the rule (an output folder, at least one stem) so the
  reason is visible before the click. The Audio Enhancer's empty output folder
  takes the same check.

- **One Mode selection now applies to every batch the Master Driver launches.**
  The toolbar's Mode dropdown is one control, but ENRICH/REFINE read one
  variable and UTIL another, so picking "Live Update" on ENRICH and then
  launching a utility handed the child `--dry` - the same visibly wrong mode the
  entries above describe. A change to either variable is now copied to the
  other, so the mode the toolbar shows is the mode every launch uses.
## [2.0.0] - 2026-10-23

### Added

- **Stem Separator: split a track into vocals, drums, bass and other.** A new
  tool (window `Stem_Separator.pyw`, command `audiosuite stems`, Master Driver
  UTIL card) runs Demucs on every supported audio file in a folder and writes
  the selected stems under `<output>/<track>/` as 16-bit WAV, plus an optional
  `mix.wav` of the selected stems. The source files are never modified, so the
  tool keeps no undo record. A dry run reports the plan without loading the
  model, downloading its weights or creating the per-track folder, and works on
  an installation without the AI package. Two sources with the same stem name
  (`song.flac` and `song.wav`) target one output folder, so the first is
  separated and the second is reported as skipped instead of overwriting it.
  The Setup tab states the device torch actually found and why, because the
  Windows torch package is a processor build: an explicit `--device cuda` that
  cannot be used stops the run with that reason instead of quietly using the
  processor. `--json` publishes `separated`, `files_written`, `output_dir` and
  `device`, and a user guide is shipped.

- **ML Denoiser: neural noise reduction with RNNoise.** A new tool (window
  `ML_Denoiser.pyw`, command `audiosuite denoise`, Master Driver UTIL card)
  removes broadband noise with RNNoise, a speech-trained network from the same
  optional AI package - no torch is needed, the download is 13 MB, and it
  denoised 30 s of stereo audio in 2.9 s. Files are rewritten in place with
  their tags, each live run records an undo snapshot, and a dry run reports the
  attenuation every file would receive. That report is the point: the model is
  not transparent (it attenuated a 220 Hz tone by 24 dB in the measurement), so
  each line states the before/after level (`Attenuated 6.0 dB (-18.4 -> -24.4
  dBFS)`) instead of claiming a clean denoise. An `--amount` percentage (1-100,
  the same unit the window slider and the driver use) blends the model's output
  with the source for musical material, and a file whose level does not move is
  reported clean and is not re-encoded. RNNoise works internally at 48 kHz and
  can return the wrong length - a 573-sample file came back one sample long - so
  the tool forces the source length, restoring a shortened tail from the source
  rather than fading it to silence. RNNoise has no graphics-card path, so the
  tool reports the processor honestly rather than offering a device option that
  could not change anything.

- **Graphics support is reported from what torch measured, not from the
  hardware.** A graphics card in the machine does not mean a run uses it: the
  torch package in the optional AI set is a processor build, so torch reports no
  usable card even on a machine with a discrete one. The new shared
  `audio_suite_shared.gpu_utils` therefore answers from what torch reported and
  says *why* when the answer is the processor - no torch installed, a
  processor-only build, or support with no usable card - because those have
  three different fixes. `--device auto|cpu|cuda` resolves through the same
  call, so `cpu` never loads torch and an explicit `cuda` that cannot be used
  stops the run with that reason instead of quietly falling back; the Stem
  Separator shows the line on its Setup tab, records it in the program log and
  publishes it as the `device` field in `--json`.

- **A finished batch report closes with one verdict line.** Caveats were printed
  one per step, so judging a twelve-step run meant reading twelve lines and
  working out which ones mattered. The report now ends with a single
  `Batch verdict:` line that names every tool which reported a caveat, in run
  order, and leads with the failure count when steps failed - for example
  `Batch verdict: 1 failed · 2 of 12 steps completed with caveats — BPM
  Analyzer: 2 of 12 tracks measured outside the 75-175 BPM range; CD Ripper: 1
  of 5 tracks did not rip`. It appears only once the batch has finished, so it
  never describes a run that is still going, and it is bounded: past 400
  characters whole caveats are dropped from the end and counted (`; +3 more`),
  because every note is still printed in full on its own step line.

- **The BPM run summary counts tracks whose tempo fell outside the chosen
  range.** Those files are tagged as measured rather than skipped, so the only
  trace of a range that does not suit the library was a note on each file's own
  line - a 200-track batch could hide twenty of them. The Results panel and the
  run log now carry an `Outside BPM range` row (`1 of 12 tracks (band 75-175)`),
  the command line prints the same count after its summary, `--json` publishes
  `outside_range_files` with each file's tempo and band, and the Master Driver's
  step note reads `1 of 12 tracks measured outside the 75-175 BPM range`. A file
  with no beat still counts as skipped and an unreadable one as an error; this
  count is neither.

### Changed

- **The Master Driver's UTIL tab fits the window again.** Seventeen utility
  cards in one column needed 930 pixels of content in a 778-pixel viewport at
  the saved window size, so the last four cards and the LAUNCH button sat below
  the fold, and every new tool pushed them further down. The cards now sit in
  two balanced columns - nine rows, 385 pixels of content at the same size - and
  the card whose Settings are open spans both columns while the cards after it
  reflow behind it. The LAUNCH button is pinned below the scrolling area, so the
  tab's main action no longer has to be scrolled to. Undo Tag Edits, the one
  card that was never a batch tool, was 131 pixels because its three-line
  description sat outside any collapsible body; it is now a normal collapsed
  card with that text inside its Settings.

- **The AI package is opt-in.** Demucs and its torch dependency are available
  for 3.11, 3.12 and 3.14, but the Linux torch download set is 2-3 GB and no
  other tool needs it, so Demucs and RNNoise live in an optional `ml` set.
  Without it the Stem Separator still opens, checks a run and completes a dry
  run, and a live run fails with a message naming the package to install.

- **Repeat Library Statistics scans of the same folder are faster.** Choosing
  between two ways of reading the cache costs two counts (about 16 ms on a
  200 000-row cache), and every read used to pay it, so one scan asking three
  questions about one folder paid three times. The choice is now remembered per
  folder for the life of the scan: three reads of the same folder fall from
  18.7 ms to 3.1 ms, and a stale choice is only ever slower, never wrong.

### Fixed

- **Every window's completion and progress steps survive the fields their
  processor sends.** Audio Enhancer declared only five fields while its
  processor also publishes `processed` and `skipped`, so a finished batch ended
  with an `unexpected keyword argument 'processed'` error and no report was
  written. All fourteen completion handlers and fourteen progress handlers now
  absorb fields they do not use, and a cross-tool check drives the wiring from
  the tree and fails if any handler narrows its signature again; the same check
  pins the one-message error contract every processor relies on. Each tool's
  required completion fields are frozen as well, so a handler that gives one a
  default - the way a discarded count renders as a clean zero - fails before the
  release instead of during a batch.

- **Album Art Normalizer reports what it actually processed.** Its completion
  wiring rebuilt the processor's report field by field with a zero default, so a
  field the processor renamed or stopped sending arrived as a clean `0`/`00:00`
  in the finished report. The report is now passed on as published, and a
  missing field raises with its name. A cross-tool check reads every tool's
  completion wiring and fails if one reintroduces per-field defaults.

- **ReplayGain Analyzer's summary no longer undercounts a mixed batch.** Its
  `Successfully processed` line subtracted the error count from a figure that
  already counted only successes, so two good files beside one failure read as
  1 and a single failure read as -1; the log and the summary panel now report
  the success count itself. Its skipped, error, duration and log-line figures
  are required now, so a report can no longer be written with `Errors: 0` and
  `Time: 00:00` when the numbers never arrived.

- **A slow track is no longer tagged at double its real tempo.** BPM detection
  doubled any estimate below the configured range and clamped whatever was left
  outside it, so a genuine 60 BPM drone under the default 75 BPM floor was
  reported - and written into the file's BPM tag - as 120. The range now chooses
  between octave-equivalent readings only when the doubled reading carries a
  pulse of its own: the drone's doubled grid scores 0.42 against 0.746 for its
  real pulse, under the 0.75 evidence ratio a doubling must reach, so 60 is
  kept - while a genuine half-time reading (which does have those off-beat hits)
  still lands on the faster level. A measured tempo outside the range is tagged
  as measured, and its line says `(outside 75-175)`. `--bpm-min`/`--bpm-max` now
  default to 75/175, so the command line and the window no longer answer the
  same file differently.

- **Analysis batches no longer get slower when you add worker threads.** BPM,
  Key and Mood analysis spend several seconds preparing librosa's numeric
  routines the first time a batch runs. That preparation happened once per
  worker thread instead of once per run, and the threads waited on each other
  while it did, so an eight-file batch took 12.2 s at 8 workers against 5.0 s at
  4 - more threads, less speed. The three analysis tools now prepare those
  routines once before the workers start: the same batch takes 2.8 s at either
  width, and the thread path is 2.9x faster than `--parallel` (8.1 s) on the
  same files. Peak memory is unchanged. A failed preparation never fails the
  batch; the analysis simply prepares on first use as before.

## [1.4.1] - 2026-10-21

### Added

- **The command line names the supported runtime when an installation is
  stale.** Running the `audiosuite` command from a source checkout is now
  checked against `pyproject.toml`: when the installed version differs, every
  command prints a warning naming both versions and the `uv run audiosuite
  --help` line that fixes it. A tool module that cannot be loaded no longer ends
  the process: the rest of the CLI, including `doctor`, stays usable, and the
  missing package is reported with the two commands that repair the environment.
  The README's Installation section documents the runtime and why a bare
  `audiosuite` can resolve to an older global installation.

- **`audiosuite doctor` reports whether this installation points at the
  checkout.** It resolves every first-party package, marks each as found,
  missing, or loaded from another installation, maps a broken package back to
  the commands it takes down (including a tool whose module loaded but whose
  command never registered), and prints the checkout and installed versions. It
  exits 0 only when the versions match and every package and command is present,
  so a pre-flight script can gate on it.

- **Every command's `--json` output now follows one documented schema.** A
  script can read `processed`, `succeeded`, `skipped`, `errors`, `total`,
  `dry_run`, `duration_secs` and `log_entries` from any command's report and get
  the same meaning every time; `succeeded` is `processed - skipped - errors`, so
  it no longer matters which tool counts attempts. Each report also carries
  `schema_version` (1), `tool` and `command`, and tool-specific keys are
  declared per command rather than leaking internal fields. JSON always goes to
  standard output and progress to standard error. A breaking change to a shared
  name bumps `schema_version`.

- **The JSON contract ships as a schema document.** `audio_suite_shared/
  cli_schema.json` (draft 2020-12) holds one variant per command, told apart by
  the constant `command`, and is generated from the same table that builds the
  reports. `audiosuite --json-schema` prints it and exits, so an external
  validator needs no Python import, and a check fails if the committed document
  is stale or a real report does not match its variant.

- **BPM Analyzer's `--json` output explains every refused file.** A skipped file
  used to appear only in the `skipped` count; the report now has a top-level
  `skipped_files` list with each file's `filename`, `reason` and
  `onset_periodicity` (null when the beat tracker found no tempo at all, so no
  score was measured). The records come from the error's own structured detail
  in both the threaded and the `--parallel` paths, and the list is always
  present (empty when nothing was skipped). A parallel top-level `error_files`
  list reports each failed file's `filename`, `reason` and `error_type`, so a
  corrupt or unreadable file no longer looks like a beatless skip. Both lists
  are always present and sorted by file name.

- **The Audio Refinery remembers its pipeline outside the checkout.** The
  last-used stage settings are now saved to
  `~/.audiosuite/refinery_settings.json`, so a session no longer rewrites a
  tracked file and `git status` stays clean. An existing
  `audio_refinery/refinery_settings.json` is read once (and noted in the log) so
  nobody loses their settings on upgrade; the shipped defaults now live in a
  committed `refinery_settings.default.json` generated from the program's own
  defaults, kept byte-identical by a check.

- **`--json` emits one document per run, and that is now a recorded decision.**
  A stream of per-file records was considered and rejected: it would have to
  come from every tool's progress callback, while scripts read the summary. The
  behaviour is documented and checked, so nothing can precede or follow the
  document on standard output.

- **The 8-worker default has a measured memory budget.** A measuring script runs
  a real analysis batch in a fresh process per worker count and reports peak
  memory, so the ceiling that was chosen on speed alone now has a number behind
  it: on a 20-processor machine an 8-file batch peaks at about 790 MB at 8
  workers against the documented 1 GB budget, and the `--parallel` parent stays
  near 50 MB because its children are separate processes. Neither configuration
  needed a lower ceiling, so analysis and conversion keep the same default.

### Fixed

- **`audiosuite cd-rip --json` reports a drive or disc failure in its
  report.** A session that could not open the drive exited 1 with the reason
  only on standard error, so a script saw a bare failure. The rip path and
  `--detect-read-offset` now print one valid report first (`errors: 1`, the
  reason in `error`, `read_offset_frames` null), then exit 1; standard error
  keeps the readable line, and a successful run's report is unchanged.

- **`audiosuite fingerprint` finds the fingerprinting program the repository
  ships.** A source checkout commits `fpcalc.exe`, but the search stopped at
  `--fpcalc`, `FPCALC` and the system path, so every file failed with `fpcalc
  was not found` unless the option was passed. The committed copy is now the
  final fallback (an explicit path, the environment variable and the system path
  still win), the window's status line names it instead of claiming the system
  path, and checks lock both the order and the out-of-the-box run.

- **`audiosuite cd-rip` exits with the drive error instead of hanging.**
  Reading the disc's table of contents raised an audio I/O error for an
  unavailable drive; because that is a suite error and not a system error, it
  escaped the session thread before the completion callback, and the command
  waited forever with no output. A session now always signals completion,
  records the fatal reason (the command turns it into a non-zero exit), logs a
  missing disc as a warning without a traceback, and treats a failed spin-down
  as non-fatal.

- **`audiosuite enhance` no longer reports every file as a worker error.** Its
  progress callback sends a tool-specific `done=` counter that the shared
  callback did not accept, so each file failed with `on_progress() got an
  unexpected keyword argument 'done'` - in text mode as well as JSON. The shared
  callback now absorbs tool-specific counters it does not display.

- **An unreadable file is reported in words that describe it.** BPM Analyzer,
  Key Detector, Mood Analyzer and Spectral Viewer all read audio through the
  shared loader, which now raises one plain-language error: `Could not decode
  '<name>' — the file may be corrupt, truncated, or in a format no available
  decoder can read.` A file deleted between the scan and the decode says so
  instead (`... the file was not found; it may have been moved or deleted.`)
  while keeping the error type callers already handle. Previously the decoder's
  own wording reached users - libsndfile reports an unreadable container as
  "File does not exist or is not a regular file", which told someone looking at
  the file that it had vanished - and a failed FFmpeg fallback logged its exit
  code and error output on top of it. The decoder's own error is kept in
  `logs/<tool>.log`.

- **`--log-level WARNING` now actually quiets the console.** The requested level
  was applied to the global logger only, while each tool carries its own level,
  so its detail messages bypassed that filter and the console printed every
  processing step - including stack traces - during a WARNING run. The console
  now applies the same level, so only warnings and errors reach the screen while
  the per-tool log file keeps its full detail.

- **A fatal command-line failure is now visible in the JSON report.** A failed
  run is recorded as one error (it used to say `-1`) and includes the reason in
  `error`, so a script reading `--json` can see why the run stopped instead of
  only a count it had to interpret.

- **`--json` reports no longer nest tool fields under `extra`.** Completion data
  is published at the top level only when the schema declares it, so internal
  fields cannot change the public report. `cd-rip`'s `log` is now
  `log_entries`, and `stats` reports the library's audio length as
  `library_duration_secs` / `library_duration_str`, so `duration_secs` always
  means the run's own time. `tag-edit` and `cd-rip` publish one set of keys in
  both of their modes, with nulls for the fields a mode does not use.

- **One handled failure produces one line, not a traceback.** A corrupt or
  unsupported file is an expected per-file outcome, so the shared loader logs
  its reason as an error and the full chain of causes as detail. Retries no
  longer print a traceback for each failed attempt or for an error that will not
  improve; only exhausted retries log a final error with the reason. The
  per-file outcome stays the message you read.

- **Silent files are refused instead of tagged with a made-up tempo, key or
  mood.** The shared analysis guard now rejects audio that is effectively silent
  (below about -60 dBFS average level) as well as audio shorter than half a
  second, and BPM Analyzer, Key Detector and Mood Analyzer all apply it before
  analysing. Previously a silent file produced the lowest permitted BPM, a
  confident-looking key from a flat spectrum, or a mood with a confidence score,
  and those values were written to the file as if measured. A silent file now
  reports `Audio is effectively silent (-240 dBFS); nothing to analyse.` and
  leaves its tags untouched.

- **Beatless files report "No tempo detected" instead of a made-up BPM.** When
  the beat tracker finds no beat - a sustained tone, a drone, or a pad with no
  rhythmic hits - it returns a tempo of zero. BPM Analyzer treated that as the
  lowest permitted tempo and tagged it, so a file with no rhythm carried a value
  that looked measured. The file is now left untagged and reported as `[SKIP]
  <file>: No tempo detected — the audio has no discernible beat.`, in both the
  threaded and the multi-process paths.

- **Noise-only files no longer get a made-up tempo.** A positive estimate from
  the beat tracker is not proof of a beat: random hits can be fitted to a tempo
  grid, which is how a noise recording came out as a plausible BPM. BPM Analyzer
  now measures how strongly the pattern of hits repeats at the detected tempo
  and its multiples, and reports `[SKIP] <file>: No tempo detected — the audio
  has no discernible beat.` when it does not, leaving the file untagged. Music
  over a noisy floor still passes: the threshold sits well below a beat that is
  uneven or covered in noise. The skip line and the per-file log include the
  measured score and the 0.10 minimum, so a skipped file shows the evidence
  rather than only the verdict.

- **BPM Analyzer no longer refuses genuine music as noise.** The guard that
  refuses noise-only files now scores how strongly the pattern of hits repeats
  at one, two, three and four beats, instead of at a single spacing, and the
  minimum is 0.10. A set of seven CC0 recordings pins the music side: real
  tracks score 0.154-0.595 while seeded white, pink and brown noise never
  exceeds 0.080, so BPM Analyzer no longer refuses genuine jazz, samba or
  hip-hop for want of a stricter noise margin. Provenance, licences and the
  measured calibration are recorded with the recordings.
## [1.4.0] - 2026-10-19

### Added

- **What's New after an update.** The suite now says what changed instead of
  leaving you to find the changelog: the first time it starts after an update it
  shows that version's release notes in a scrollable panel (headings, entries
  and the bold lead-in on each), and the Master Driver's Help menu can reopen
  them at any time. The panel appears once per version, tracked in the shared
  settings so it never nags, and it stays out of unattended work: a Master
  Driver batch launch never opens it, and `AUDIOSUITE_WHATS_NEW=0` disables the
  automatic panel entirely. Skipping a release does not lose its notes: the
  panel lists every release newer than the last version it showed, newest first,
  each under its own `Version x.y.z` heading.

### Removed

- **The Windows Explorer right-click integration is NOT being implemented.**
  The `shell-install` / `shell-uninstall` commands and the per-user
  `AudioSuite-Pro` context menu they registered have been withdrawn, and the
  feature is off the roadmap: it will not be implemented. It was a step too far:
  it gave Explorer a second way into the suite that users could not discover or
  configure from the app itself, and its cascading submenu did not render
  consistently across Explorer builds. The modules, the commands, the README
  section and the platform table were all removed in the same change, so nothing
  advertises a menu that cannot be installed. Use the Master Driver or each
  tool's own launcher instead.

### Changed

- **Parallel work now uses the machine it runs on.** The default worker count is
  one per logical processor, capped at 8, instead of a fixed 4 (measured: 24
  one-minute tracks from WAV to MP3 in 2.02 s at 4 workers and 1.17 s at 8).
  Every tool's worker slot grid, saved default and the Master Driver's worker
  values follow the same default; each analysis tool's *Workers* control still
  overrides it, and the cap bounds peak memory.

- **Every worker count now comes from one place, and startup logs the value it
  got.** The leftover fixed counts are gone: the Mood Analysis Batch Tagger fell
  back to 4 (instead of the machine default) when a saved worker count was
  corrupt, and the `--workers` help text and six of the generated guides still
  advertised a fixed 4.

- **The startup log says which worker count this machine resolved.** Each launch
  writes one `Workers: 8 resolved (cpu_count=16, ceiling=8)` line, so a slow
  batch can be judged against the machine instead of guessed at.

- **Each file's tags are read once per pass.** Library Statistics read each
  file's tags eight times (174 ms per 100 files) and now reads them once (23 ms
  per 100 files); the CSV export reuses the same reader. Genre Sync,
  Tempo Analyzer, Lyrics Manager, Audio Fingerprinter and Album Art Sync no
  longer load the same file twice for fields read together.

### Fixed

- **A Workers value above the slot grid no longer fails the files.** Key
  Detector, Mood Analyzer, BPM Analyzer and Lyrics Manager let you type any
  worker count into a *Workers* field, but their progress display has a fixed
  number of slots. Asking for more workers than slots handed the extra workers a
  slot that did not exist, so every file past the grid was reported as an
  unexplained per-file error (and the batch lost those files). The count is now
  capped at the number of slots - with one warning, and the capped value is what
  gets saved - and the processing layer applies the same cap for any caller that
  supplies a smaller grid, so a preset, a restored setting or a command-line
  count cannot bring the problem back.

- **A corrupt saved worker count no longer quietly becomes four.** Mood Analysis
  Batch Tagger's saved value went through a fixed fallback of 4, so a
  hand-edited or truncated setting ran at 4 workers on a machine that should
  have used its own default. The fallback now asks the shared resolver, and
  non-numeric, boolean and non-positive values all fall back safely.

- **Silence Trimmer and Mood Analysis Batch Tagger saved a worker count they did
  not run.** Both accepted any typed *Workers* value and stored it as written
  while their processing clamped the run to the progress grid, so the saved
  value disagreed with what actually happened. Both now cap before saving, with
  one warning.

- **A driver launch no longer waits on the worker-count warning.** The cap
  opened a modal dialog even when the Master Driver or `--start` launched the
  tool with nobody to dismiss it, so an unattended batch sat blocked before it
  processed a file. That launch now logs one warning and continues; clicking
  Start yourself still shows the dialog.

## [1.3.0] - 2026-10-18

### Added

- **Spectral Viewer - see what a file actually sounds like.** A new tool draws a
  spectrogram for any supported file, in a window (`Spectral_Viewer.pyw`, with
  matplotlib's own zoom and pan toolbar) or as a batch of PNGs from `audiosuite
  spectrogram <path>`. It reports the codec cut-off, the noise floor, any DC
  offset and any clipping at a glance, and it never writes audio: the only files
  it creates are images. Every image is scaled to its own peak against a stated
  floor, so a quiet master and a hot one are comparable, and the status line
  reports the absolute peak so the two are still distinguishable. `--dry` prints
  the exact image paths it would write and writes none of them.

- **Library Statistics: the Charts tab now actually draws.** matplotlib was
  never a declared dependency, so a fresh installation opened the dashboard with
  a "matplotlib not installed" message where the four charts belong. It is now
  installed with the suite, and the charts are checked against real data (one
  pie wedge per genre, the BPM bucket holding the measured files, one bar per
  key) and against a re-scan replacing the previous chart instead of stacking a
  new one.

- **Library Statistics: the completeness view shows *where* the gaps are, and
  whether they are closing.** Completeness now covers the five primary library
  fields - title, artist, album, track number and year - alongside the analysis
  tags it already tracked, and it reads each file **once** instead of twelve
  times (measured 1.5 ms to 0.16 ms per file on MP3), so the wider view is
  cheaper than the narrow one was. A missing-tags-by-album heatmap sits under
  the tag bars, worst album first, with files that carry no album grouped
  honestly as `(no album)` rather than dropped. Each scan records a completeness
  snapshot in the cache (identical consecutive snapshots are suppressed, the
  newest 100 per folder are kept) and the Charts tab plots the overall
  percentage over time; `stats --trend` prints the series, `--history-limit`
  chooses its length, and `--no-history` keeps a scan from recording anything.

### Changed

- **Library Statistics: cached scans are far faster, with the same numbers.** The
  cache now saves a scan as one transaction instead of one per file (measured on
  20 000 rows: 39.1 s to 0.24 s) and reads every cached modification time in one
  query instead of one lookup per file (113 ms to 17 ms). A report for one album
  inside a large cache no longer reads the whole cache: a small scope resolves
  through an index (0.05 ms against about 17 ms for one full pass over 20 000
  rows) and falls back to a full read when it is not small, because an index is
  slower across a whole library. The choice is made from real row counts,
  existing caches are upgraded in place on first use, and both routes are
  checked to return identical figures.

## [1.2.0] - 2026-10-17

### Added

- **Audio Fingerprinter: send a file's ISRCs to MusicBrainz.** The ISRCs a
  file's own tags carry - typically the codes a CD rip recorded - can now be
  offered back to MusicBrainz for the recording AcoustID matched, with the new
  opt-in `--submit-isrc` and its Setup-tab switch. Only codes the service does
  not already have are sent: the lookup the tool already performs supplies the
  known set, codes another file already contributed are merged, and an invalid
  ISRC is reported and skipped rather than sent. A dry run prints and logs the
  exact document it would send - built by the same code that builds the live
  request, with recordings and codes sorted, so what you review is what a live
  run posts - and a live run needs a token from `MUSICBRAINZ_TOKEN` or the
  encrypted store (with the `submit_isrc` permission; the older
  application-token route stays available on the command line via `--mb-auth
  app-token --mb-user`). The token is never accepted as a command-line argument.
  A submission is a pending public edit that MusicBrainz keeps open for review
  for seven days, so refusals are reported and never retried, and no submission
  outcome changes a file's result. The outcome is reported where you are already
  looking, not only in the run log: the Results tab shows the status and, for a
  refusal, its reason (in the error colour, so a rejected or unauthorised
  submission is not mistaken for success); the command line prints the same line
  to standard error; and a batch started from the Master Driver records it
  against the Audio Fingerprinter step, whose report stays on screen while it
  carries such a note instead of auto-hiding half a second after the batch
  finishes.

- **Batch reports carry each tool's notes.** A tool that finishes with something
  you still have to know - CD Ripper tracks that did not rip (including the ones
  verification rejected), files a tag writer skipped or could not update,
  conversions skipped or failed - now records one line that the Master Driver
  shows on that tool's step in the batch report, so a partial outcome is not
  left behind in a run log nobody opens mid-batch. The analysis tools report the
  tracks they finished without a result for: BPM Analyzer the files whose
  detection failed, Tempo Analyzer the files carrying no BPM tag to derive a
  marking from, and Mood Analyzer the files with no usable audio (undecodable or
  silent) plus any it could not analyse at all. A note never changes a step's
  status: a refused submission or a skipped file is not a failed run. The report
  stays on screen while it carries a note instead of auto-hiding when the batch
  ends, and the note is cleared before each step so a previous batch's note can
  never be attributed to a new run.

- **CD Ripper: AccurateRip confidence, and a manual re-rip of flagged tracks.**
  Every track's verification result now carries the matching database record's
  confidence - the number of other rips that submitted exactly these track
  checksums - and is displayed in EXACT Audio Copy's familiar wording: `Accurate
  (confidence N)`, `Rip-twice verified`, `Not in database`, `Unavailable
  (offline)` or `Not accurate`. There is deliberately no invented "accurate
  versus confident" threshold: one agreeing submission is a match and is shown
  as confidence 1, and when several records match a track the strongest count is
  the one reported. A failed track can now be re-ripped on demand from the
  Results tab; the action runs only the flagged track numbers and replaces their
  rows, leaving every other result untouched, and nothing is ever retried
  automatically.

- **Audio Fingerprinter: MusicBrainz detail and ISRC tags.** AcoustID matches can
  now be filled in from the MusicBrainz database itself: the matched recording's
  ISRCs and its release's date, label and country are retrieved
  (`--musicbrainz`, off by default), and the ISRCs can be written in each
  format's own convention with the new opt-in `--write-isrc` (`TSRC` for
  MP3/WAV/AIFF/DSF, the `----:com.apple.iTunes:ISRC` field for M4A/MP4, an
  `ISRC` comment for FLAC/OGG/Opus/WV/APE/MPC). MusicBrainz also settles an
  AcoustID near-tie the file's own tags could not, but only on evidence that
  separates the candidates - title and artist, then album, then whether an ISRC
  is present - and never overrides a tie it cannot resolve. One rate-limited,
  caching client serves the whole run, so an album costs one request per unique
  recording plus one per unique release at MusicBrainz's documented one request
  per second. An unavailable service leaves the file with its AcoustID-only
  result instead of failing it. The window's Setup tab, the Master Driver card
  and the CLI reference all expose the two new options.

### Changed

- **Audio Enhancer: the Custom DSP controls moved into their own window.** The
  nineteen Custom controls needed 745 pixels and pushed the Setup tab to 1274
  against 887 available at the shipped 880x980 window, so the lower controls
  could not be reached and the BEGIN ENHANCEMENT button was not drawn at all -
  maximising did not help, because the tab still needed more than the roughly
  988 pixels a 1081-pixel-tall display provides. Selecting Custom now shows a
  one-line summary with a **Configure Custom DSP…** button that opens a
  non-modal, scrollable editor; the editor writes into the same values the run
  reads, so it can stay open while a batch starts. The start button is now
  placed before the options, so no preset state can push it out of view.

### Fixed

- **The Master Driver's Audio Enhancer card could not select Custom.** The
  ENRICH card's preset dropdown was a hard-coded list of three names, and the
  standalone window's `--preset` parser declared the same three as its only
  valid choices - so Custom was offered by the tool's own selector and by the
  suite command, but rejected with an error when the driver launched the tool.
  Both lists now come from the same shared definition of the presets, so the
  card lists every preset the tool accepts and one edit keeps every entry point
  in step.

- **The REFINE tab's Audio Enhancer now uses the same Custom DSP editor as the
  standalone tool.** Selecting Custom there still expanded all 19 controls
  inline inside the stage panel (745 pixels), so the REFINE tab ran past the
  bottom of the screen and the lower controls could not be reached - the editor
  fix had only been applied to the standalone window. The stage now shows the
  same summary row and opens the same non-modal editor, which copies its values
  into the settings the pipeline reads, and it still hides Output Gain while the
  Normaliser stage owns the final level.

- **Audio Enhancer: one Preset control instead of two.** The Setup tab showed
  "Presets:" (saved suite presets) and "Enhancement Preset:" (built-in presets)
  as two near-identical dropdowns two rows apart that did different things - one
  only changed DSP values, the other also restored the saved paths. A single
  selector now lists the built-in presets first, then the saved ones below a
  divider, with a caption naming the kind and the built-in preset a saved entry
  carries. Delete is greyed out for built-in presets, and deleting the selected
  saved preset falls back to the built-in preset still in use instead of leaving
  the selector blank.

- **Audio Enhancer: a pre-filled `--preset` now applies that preset's values.**
  The selector changed but the run kept the previous preset's settings, so a
  Master Driver or scripted launch quietly enhanced with the wrong DSP values. A
  pre-filled preset now runs the same update as picking it by hand.
## [1.1.0] - 2026-10-16

### Added

- **Wider input-format support across the suite.** The shared audio-extension
  list now recognises WavPack (`.wv`), Speex (`.spx`), Monkey's Audio (`.ape`),
  Musepack (`.mpc`) and DSD (`.dsf`) alongside the existing formats, so every
  tool finds them. The Music Format Converter classes SPX as lossy and WV/MPC/DSF
  as lossless, and documents APE, MPC and DSF as inputs it can recognise but not
  write, because no encoder is available. The Audio Normalizer handles WavPack
  and Speex through FFmpeg's loudness path, and the Audio Enhancer reports the
  five formats its effects engine cannot re-encode as a clean skip instead of a
  decode error.

- **Optional effects** (Audio Enhancer, and Audio Refinery under the Custom
  enhancement preset): Reverse audio, Karaoke (removing a centred vocal, with a
  0.0-1.0 strength), Phaser, Flanger and Chorus. All are off by default, so
  output is byte-identical to 1.0.1 unless an effect is enabled. Available in
  both windows and on the command line (`--reverse`, `--karaoke/--no-karaoke`,
  `--karaoke-strength`, `--phaser`, `--flanger`, `--chorus`). A dry run never
  applies effects.

### Fixed

- **Audio Enhancer: formats it cannot read no longer look like corruption.**
  Files in the wider input set that the enhancer cannot decode (`.wv`, `.spx`,
  `.ape`, `.mpc`, `.dsf`) were reported as "The file format is invalid or
  corrupted."; they are now a clean skip that names the format.

- **Audio Enhancer: a loaded preset is now applied.** Applying a saved preset
  updated the displayed values but not the values the run actually used, so a
  saved preset had no audible effect. The run settings now carry the loaded
  preset.

- **Audio Refinery: enhancement sliders and effect switches now persist.** The
  enhance panel's sliders wrote to a discarded local copy rather than the run
  settings, so slider changes were lost when the run started; they now write
  back to the settings, and the new effect switches are wired the same way.

- **CD Ripper no longer crashes when `discid` is installed without its library.**
  The tool guarded `import discid` against a missing package only, so a machine
  carrying the Python package but not the `libdiscid` shared library aborted the
  entire tool import with a system error - taking the CD Ripper down before it
  could fall back to reading the disc with FFmpeg. The guard now catches both.

## [1.0.1] - 2026-10-14

Everything below landed after `1.0.0`. The items are grouped Keep-a-Changelog
style and worded against the behaviour actually shipped.

### Added

- **MusicBrainz identifier writing** (Audio Fingerprinter, opt-in). Selected
  AcoustID candidates can now have their MusicBrainz IDs written to the file:
  `TRACKID`/`ARTISTID` whenever a candidate reports them, and `ALBUMID` only
  when exactly one release survives the release filter. The writer refuses to
  guess - a criterion that would empty the set is ignored rather than made up.
  Enable with `--write-mbids` on the command line, the Fingerprinter's switch in
  the window, or the Master Driver card; `--write-mbids` is refused unless tag
  writing itself is enabled. Values are written as ID3 `TXXX`, Vorbis comment,
  and `----:com.apple.iTunes:` fields, so Picard recognises them.

- **Cover Art Archive as the first album-art source** (Album Art Sync). The
  chain is now Cover Art Archive, then MusicBrainz, then Fanart.tv, then Deezer,
  then the iTunes Store. Cover Art Archive is asked first for the file's release
  ID, then for its release group. Because that ID *is* the trust evidence for
  this source, album-name matching is skipped for it exactly as for Fanart.tv,
  while the size and threshold settings still apply. An outage there falls back
  to the previous chain rather than failing a run.

- **Recursive, mixed-format conversion** (Music Format Converter). The input
  scan now walks subfolders and reports a per-format breakdown, and the output
  format list is every target reachable from the formats actually found. An
  unreadable subfolder is logged and skipped so its siblings still convert; only
  an unreadable *root* stops the run. Relative paths are mirrored under the
  output folder, and output subfolders are created only on a live write - a dry
  run leaves no folders behind.

- **Reading MusicBrainz tags back.** Two shared helpers read the identifiers the
  writer produces across MP3, FLAC/Vorbis, MP4 and IFF-ID3, and read the disc
  number, so other tools can use them.

- **Local `.lrc` lyric files** (Lyrics Manager). A new `sidecar` source reads the
  `.lrc` file beside each track (same name, `.lrc` extension) with no network
  access. Choose it with `--provider sidecar` on the command line or in the
  window's source list.

- **Project documentation baseline.** A packaged `README.md` (quick start, a tool
  index of 27 entries kept in step with the tool list, an architecture overview,
  FFmpeg installation notes and a platform-support table), the GPL-3.0 `LICENSE`
  with standard licence metadata, and contributor and security notes. Each
  FFmpeg-dependent tool's guide also gains a System Requirements section with
  per-platform installation hints, worded from one shared source.

- **Key Detector reports more about what it found.** Its analysis returns the
  key, a confidence figure, the winning and runner-up correlations and a
  low-confidence flag, alongside the existing detection.

### Changed

- **Bit-depth reduction is dithered by default, and sample-rate conversion uses
  `soxr`** (Music Format Converter). Any conversion that reduces integer PCM
  depth (WAV/AIFF/AIF) now applies triangular dither automatically, and every
  sample-rate conversion uses the `soxr` resampler. **This changes the bytes of
  every converted file**, so previously converted output is not byte-identical
  to what the new code produces.
  *Moving over:* if something depends on the exact previous output - an
  existing undo snapshot compared against a fresh conversion, or a checksum over
  converted files - re-run the job from the originals rather than from a
  previously converted copy. The run log records the dither decision on every
  batch.
  *Turning it off:* `--no-dither` on the command line, or clearing "Apply TPDF
  dither when reducing bit depth (WAV/AIFF)" in the window (ticked by default).
  The setting is saved with conversion presets. With dither off, the output is
  reproduced byte-for-byte as before.
- **The CLI reference now matches the real defaults.** The `--dry`/`--live`
  default for Album Genre Tagger, Album Art Sync, ASX Playlist Extractor and
  Lyrics Manager was documented as "dry" when every command's actual default is
  live, and the Audio Refinery `--stages` default was documented as "all five"
  when it defaults to declick, trim, enhance and normalise. The reference is now
  checked against the commands themselves.
- **Key detection now uses cosine correlation by default** (Key Detector). The
  engine gained a measured low-confidence threshold (0.25) and reports
  `Unknown` for atonal or noisy material instead of confidently naming a key;
  Pearson is kept but documented as compatibility-only. *Turning it back:*
  `correlation="pearson"` still selects the old engine.
- **Low-confidence key results are no longer written to `KEY` tags.** The status
  reports `DETECTED (not tagged)`, an existing `KEY` tag is never overwritten,
  and `KEY="Unknown"` can no longer mislead a later Dry Run.
- **Python 3.10 is no longer supported; the minimum is now 3.11.** The 3.10
  installation set resolved versions of numpy and scipy that nobody developed or
  shipped against. 3.10 users must upgrade.
- **`audiosuite --help` groups commands by purpose** (Analysis, Tagging, Repair,
  Utilities), and **`--version` reads the version from the project file**, so a
  source checkout no longer reports a wrong or missing installed version.

### Fixed

- **ReplayGain peak tags were written in dBFS instead of plain amplitude.**
  `REPLAYGAIN_TRACK_PEAK` / `REPLAYGAIN_ALBUM_PEAK` carried the raw measurement
  (for example `-0.500000`) while the ReplayGain convention - and the tag
  writer's own contract - requires a value between `0.0` and `1.0`. The peak is
  now converted where the tag is written (`10 ** (peak_dbfs / 20)`, so -6 dBFS
  becomes `0.501187`), and the album peak is the largest of those values rather
  than the largest dBFS figure.

- **A fully silent file was emptied by Silence Trimmer.** Leading and trailing
  silence covered the entire file, so trimming produced an empty result that was
  exported over the original - truncating it to a few dozen bytes and destroying
  its content. Wholly silent files are now reported as a non-destructive `SKIP`
  ("Entire file is silence - skipped") and left byte-identical, in both Dry Run
  and Live Update.

- **Five standalone tools ignored every Master Driver argument.** File
  Reorganizer, Tag Field Updater, Library Statistics, CD Ripper and
  Album Art Normalizer received the driver's options (output folder, format,
  mode and so on) but never read them, so every pre-fill was lost. Each tool
  now reads its driver arguments: File Reorganizer pre-fills source,
  destination, action and
  patterns; Tag Field Updater pre-fills the folder and gains a visible Dry Run
  checkbox; Library Statistics pre-fills folder, scan mode and exports; CD
  Ripper pre-fills output folder, format and CUE, and filters the rip list by
  `--tracks`; Album Art Normalizer maps `--size <pixels>` to the resolution
  dropdown.

- **Library Statistics' Master Driver card showed two controls that did
  nothing.** The "Show tag completeness analysis" checkbox and "Detail Category"
  dropdown had no matching behaviour - the driver passed `--completeness` and
  `--detail` to a tool that ignored them. Both controls and their arguments have
  been removed.

- **The suite log was flooded with per-file detail, burying real failures.**
  `logs/audio_suite.log` held every detail message from every program - per-file
  tag fallbacks, successful program calls, per-file progress - so a
  file of 10 000+ lines made spotting a warning or error impractical. Logging is
  now two-tier: the suite log keeps the startup line plus warnings and above,
  while each program's full detail goes to `logs/<program_name>.log`.

- **The undo history dialog showed wrong tool names.** Its hard-coded list had
  drifted from the tool list: `asx_extractor` and `file_reorganizer` used short
  names that no longer matched, and `audio_fingerprinter`, `lyrics_manager`,
  `silence_trimmer` and `tag_editor` were missing entirely, so their ids appeared
  raw. The four entries were added and the two stale names corrected.

- **The CD Ripper's C2 diagnostic button crashed on a drive error.** Its handler
  caught two system error types but not the suite's own drive error, so a drive
  problem escaped and the window failed. It now catches that error too.

- **`tag_field_updater --dry` wrote tags anyway.** The option was accepted and
  displayed, but the write was not gated on it, so a Dry Run silently modified
  files. Dry Run now genuinely withholds tag writes. `--dry-run` was never a
  real spelling and remains undocumented; the supported spelling is `--dry`.

- **CD Ripper CUE sheets named one file for the whole album.** The sheet wrote a
  single `FILE` entry covering every track, so it pointed at the wrong audio
  after ripping. Each track now gets its own `FILE` entry with the correct
  offset.

- **Album Art Sync and Album Genre Tagger touched the window from worker
  threads.** Both changed widgets off the main thread, which Tk does not
  support. All such updates are now handed to the main thread.

- **The Master Driver read live settings on the launcher thread.** The command
  line it emitted - including the live/dry choice - was read from the widgets
  *after* the worker thread started, so an edit made while a batch was launching
  could change the mode of the run in flight. The full argument list is now
  built on the main thread before the worker starts.

- **`audiosuite artnormalize` raised `TypeError` and did nothing.**   The unified
  command passed an argument the normalisation entry point did not accept.

- **Several swallowed errors are now recorded.** A failed error dialog in the
  File Reorganizer / Tag Field Updater launchers, a corrupt embedded cover image
  in the recursive resize tool, and an unreadable legacy row in the undo history
  were each skipped with no record. The behaviour in those cases is unchanged -
  a corrupt image is still resized, a legacy row is still skipped - but each now
  leaves a log line naming what was skipped and why.

- **Saving suite settings could silently overwrite another tool's save.** The
  read-modify-write ran from a copy of the file taken *before* the cross-process
  lock was acquired, so two tools starting together could clobber each other's
  write. The copy is now dropped the moment the lock is acquired, so every
  locked read-modify-write starts from the file on disk.

- **`--target-lufs` was accepted unchecked by the `normalise`, `refine` and
  `replaygain` commands.** An out-of-range target (for example `999`) passed
  argument parsing and reached the loudness pipeline unchecked. All three now
  refuse it at parse time with `Target LUFS must be one of: -12, -14, -16, -18,
  -23`, and each option's help names the permitted values.

- **LUFS defaults disagreed with the windows and guides they drive.** The
  Audio Normalizer's settings defaulted to -16 LUFS while its command-line
  option, window and guide all said -14 - so a launch with arguments silently
  rewrote the window's -14 back to -16 - and the ReplayGain command defaulted
  to -14 while its window and examples use -16. Defaults now match their
  surfaces: Audio Normalizer -14, ReplayGain -16, Refinery -16 (unchanged).

- **`--end` / auto-close is now honoured in Noise Reduction and Pop & Click
  Remover.** Both logged an "ignored" warning and stayed open when the Master
  Driver asked them to close on completion.

- **Tool and command-line records now reach the suite log file.** Only the
  suite's own logger was attached to `logs/audio_suite.log`, so messages from
  the tools and from every command-line run - which configured only a console
  handler - never reached the file. The logging setup now attaches the same
  rotating handler to every first-party program, and the command line passes its
  `--log-level` through, so verbosity still follows the console setting.

- **Undo now restores whole-file bytes, not just tags.** An in-place repair
  (Noise Reduction, Pop & Click Remover, and anything routed through the shared
  in-place write) can be reverted byte-for-byte to the original file; previously
  only tag contents round-tripped and the audio stayed modified. *Moving over:*
  the undo budget is unchanged (50 entries / 1 GiB) but whole files now count
  against it, so oversized batches prune oldest-first - keep your own backups
  for large runs.

- **Noise Reduction Dry Run reports repairable files honestly.** A file that
  would be repaired now reports `FOUND` instead of `SKIP ("Clean")`, matching
  Pop & Click Remover and what the guide already documented; writes are still
  withheld.

- **A missing or fake `ffmpeg`/`ffprobe` is diagnosed at launch and by the
  finder.** Every launcher now warns at startup, with installation hints, when
  the program is absent, instead of dying with an opaque error on the first
  file, and the finder no longer accepts a *folder* named `ffmpeg(.exe)` as the
  program.

- **A corrupt file that decodes to nothing no longer crashes the analysis
  tools.** The shared "too short to analyse" check crashed on a zero sample
  rate; Key, BPM, Tempo and Mood now report a proper error for that file.

- **Music Format Converter overwrote one output when two sources mapped to the
  same name.** Two files with the same name and different extensions in one
  folder (for example `song.flac` and `song.wav` to `song.mp3`) both converted
  to the same output, so the second silently replaced the first while the run
  reported both as converted. Each output path is now claimed before conversion:
  the first source wins, and the colliding source is reported as `SKIPPED`
  ("already produced from another source") with its original left intact under
  `--delete-originals`.

- **File Reorganizer silently overwrote an existing destination file.** A
  copy or move whose target already existed (a file already there, or two
  sources whose tags resolved to the same name) replaced it with no warning -
  and the undo record stores only paths, so the overwritten bytes were
  unrecoverable. Such targets are now skipped, reported as `SKIPPED
  (destination exists): <target>`, and counted as skipped rather than processed.

- **An internal error crashed the Album Art Sync command with `AttributeError`.**
  On an unexpected error the run returned nothing while its callers assumed a
  report existed, so it ended with `FATAL: 'NoneType' object has no attribute
  'total_files'` and no usable summary. It now returns a failed report with a
  readable `Error: ...` line, and the detailed traceback is kept in the log
  file.

- **One file whose artwork could not be embedded aborted a whole Album Art Sync
  batch.** The embed step caught two error types but not the suite's own error,
  which escaped and stopped the album mid-run. The offending file is now
  reported as a skipped warning and the remaining files are still processed.

- **A valid, already-loud MP3 was reported as "no valid frames".** When every
  gain field of an MP3 already sat at its limit, a gain change that changed
  nothing was counted as "zero frames found", so a batch marked a perfectly good
  file as errored. The pass now distinguishes frames *seen* from frames
  *changed*: an already-loud file is a silent no-change success, and the error is
  raised only for a file that genuinely has no frames.

- **Music Format Converter could delete a source file with no undo record.**
  With `--delete-originals`, the source was removed *before* its undo snapshot
  was written, so a failure to record the snapshot left the file gone with
  nothing to restore it. The snapshot is now taken first, and a snapshot failure
  aborts the delete (reported as `DELETE FAILED`) so the original stays on disk.

## [1.0.0] - 2026-09-26

First recorded baseline. Package metadata, releases and this changelog start
here; this section also records the notable changes *contained* in the baseline,
which were delivered by the pre-release work.

### Added

- Initial distribution: 27 registered tools across the Enrich, Utility and
  Refinery categories, the Master Driver control panel, the shared `audiosuite`
  command line, and the shared foundation the tools are built on.

- **Audio Fingerprinter** (new tool). AcoustID/Chromaprint identification of
  unknown tracks using the bundled `fpcalc` program and the AcoustID service:
  window, Master Driver card, `audiosuite fingerprint` command, encrypted
  API-key storage, rate limiting, and tag-aware resolution of ambiguous scores.
  Album mode (`--album-mode`) groups candidates by MusicBrainz release group, so
  album agreement decides remix-versus-original near-ties.

- **Lyrics Manager** (new tool). Batch fetching and embedding of synced lyrics
  from LRCLIB, written in each format's own way (ID3 SYLT, Vorbis
  `SYNCEDLYRICS`, plain `USLT`/`LYRICS`/`©lyr` fallbacks), with a three-tab
  window, a Master Driver card and an `audiosuite lyrics` command
  (`--skip-existing` on by default).

- **Tag Editor** (new tool). Batch tag editing over an editable library grid -
  bulk set, clear, swap and case-change operations under one undo batch, plus
  CSV import/export (`tag-edit PATH --csv FILE --dry`), written as lossless tag
  edits that leave the audio alone.

- **Sample-rate and bit-depth conversion** (Music Format Converter). Presets
  from 44.1 kHz to 192 kHz plus a `source` passthrough, WAV/AIFF bit-depth
  selection, and `--sample-rate` / `--bit-depth` options.

- **Lossless MP3 volume adjustment** (Audio Normalizer `--mode lossless`,
  ReplayGain `--apply-gain`, Music Format Converter `--normalize-mp3`). A pure
  Python MP3Gain-style gain rewrite - no re-encode, file size unchanged -
  verified by decoding and measuring across MPEG-1/2/2.5, mono to joint stereo,
  and both constant and variable bitrate.

- **CD rip verification and read-offset correction** (CD Ripper).
  `--verify off|twice|accuraterip` (default `twice`) re-reads and cross-checks
  every track, and a mismatch blocks the track write so a corrupt rip is never
  silently saved. Per-drive read-offset detection (`--detect-read-offset`)
  aligns both the verification and the extracted audio for drives whose raw
  stream runs off the sector grid.

- **CUE sheet support** (shared, CD Ripper and the command line). Strict CUE
  read, generate and split (`audiosuite cue ...`), one `.cue` per ripped album,
  and a "Split CUE..." action that splits a single-file image into tracks.

- **Noise Reduction** (new tool) and a fifth Audio Refinery stage. 50/60 Hz hum
  removal with harmonic notch filtering plus broadband noise gating from a
  noise sample you select; `audiosuite reduce` command, window, Master Driver
  card, and a `--reduce-noise` pipeline stage (off by default).

- **A/B listening** (Audio Enhancer, Refinery, Audio Normalizer, Pop & Click
  Remover,
  Silence Trimmer). "Play Original" / "Play Result" buttons on every Results tab
  so before and after can be heard before committing.

- **Tag Completeness Dashboard** (Library Statistics). A colour-coded per-tag
  coverage tab with a missing-files viewer and CSV/JSON export; `audiosuite
  stats --completeness` on the command line.

- **Broader format support.** MP4 (AAC at 192/256/320 kbps) as a conversion
  target and AIFF/AIF as lossless targets; Album Genre Tagger,
  Album Art Normalizer, Metadata Scrubber and Tag Field Updater all extended
  from MP3-only handling to the suite's nine main formats; WAV added to the CD
  Ripper's output list.

- **Four DSP tools registered in the Master Driver** (Audio Enhancer,
  Audio Normalizer, Pop & Click Remover, Silence Trimmer). They previously
  existed only as standalone launchers and now work as full Driver cards in
  batch runs.

- **Audio Refinery file-integrity gate.** Corrupt, truncated or implausible
  files are rejected up front with a clear message instead of failing
  mid-chain.

### Changed

- **WAV output keeps the source's depth by default** (Music Format Converter). A
  24/32-bit or floating-point source is no longer silently reduced to 16-bit; an
  explicit 16/24/32-bit or float override remains available. *Moving over:* if
  you want 16-bit WAV, select the override.

- **Unknown extensions are rejected, not silently re-encoded**
  (Audio Normalizer). Unrecognised files were re-encoded to MP3 while keeping
  their original extension - a quality-loss path; they now fail with a clear
  error.

- **The Master Driver refuses a non-existent folder up front** and reports a
  failing module as a readable "Module Error" dialog while the batch continues,
  instead of a silent thread death that left Run stuck on "PROCESSING…". Ten
  tools' commands likewise print a tool-prefixed reason for an invalid folder.

- **Deleted-file undo storage is bounded by size as well as count**
  (`undo_max_bytes` suite setting, default 1 GiB). *Moving over:* automatic -
  older undo databases convert once on first use.

- **Tool preferences moved to the shared `audio_suite_config.json`** (File
  Reorganizer, CD Ripper), with a guarded one-time migration that retires the
  old tool-local files.

### Fixed

- **Lossless MP3 gain applied wrong, uneven gain to stereo files** (the
  headline fix). A requested +6 dB produced -0.28 dB left / -2.20 dB right,
  because of incorrect bit offsets and because only one of four gain fields per
  stereo frame was updated; low-sample-rate (MPEG-2/2.5) files were only
  half-gained. CRC-protected and free-format MP3s are now refused with a clear
  error instead of having their gain fields silently corrupted, and a failed
  file no longer leaves a phantom undo entry.

- **Audio Enhancer Dry Run overwrote source files.** The setting never reached
  the write, so an "in-place Dry Run" rewrote your originals. Writes and tag
  copies are now genuinely withheld, with measurements still reported.

- **The CD Ripper's command line crashed on every `--format` value.**
  Lowercase choices were looked up in a table keyed by display names; the lookup
  is now case-insensitive at both ends.

- **Tag Editor correctness.** Undo of newly created tags on previously tagless
  files now removes them; clearing the last tag persists again; the Vorbis
  handler creates tags on tagless FLAC/OGG/Opus files; successful rows no longer
  report "Unknown error"; and CSV import paths are confined to the chosen
  library folder instead of allowing `../..` to retag any file on the machine.

- **Concurrent Library Statistics scans raised "database is locked."** Database
  access is now serialised with a shared lock and proper busy timeouts.

- **`Pop_Click_Remover.pyw` never worked standalone** (a missing entry point).

- **A hung per-file conversion no longer stalls the whole batch** (Music Format
  Converter); it fails that file with a clear timeout error. The same per-file
  error containment was applied to crashing workers in Genre Sync, Silence
  Trimmer, Noise Reduction, Pop & Click Remover and Metadata Scrubber, and Genre
  Sync's completion totals are now accurate.

- **Broken Help buttons** (Mood Analyzer, Album Art Sync and others) now open
  their guides, and several swallowed-error paths (launchers, key-file
  permissions, legacy undo rows) now report properly.

### Removed

- `.wma` from Metadata Scrubber discovery - it was advertised but every `.wma`
  failed to load.
