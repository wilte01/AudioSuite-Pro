# Technical changelog

The developer-facing half of AudioSuite-Pro's change history: the release gate,
CI, the tests, tooling, behaviour-neutral refactors and dependency bumps -
changes a user cannot run or observe, and therefore cannot find in
[CHANGELOG.md](CHANGELOG.md).

Both files are promoted in the same cut by `utilities/release.py`. A version
heading that is absent here means that release carried no developer-facing
change, which is why a release with none adds no heading rather than an empty
one.

Each released section is grouped under `### Added`, `### Changed`,
`### Deprecated`, `### Removed`, `### Fixed` or `### Security`, in that order,
and every bullet belongs to exactly one of them.

## [Unreleased]

### Added

- **The library cache carries artwork coverage, so an incremental scan can
  report it.** `library_stats` schema version 4 adds `has_art` to `files`,
  `temp._scope_files` and both populate statements, with a one-time
  `ALTER TABLE` in `migrate`; `upsert_file` takes a `has_art` argument and
  `get_cached_art` reads the scoped map back through the same plan rule as
  `get_cached_stamps`. The cached scan reads the fact once per changed file,
  counts `missing_data["no_art"]` from `has_art == 0`, and treats a NULL as a
  miss so a pre-4 cache heals instead of undercounting - the rule a NULL
  `size` already follows. The full scanner reads the same fact with
  `_read_file_tags(art_fields=True)` and publishes the same key, so the two
  report shapes stay identical. Locks: `TestCachedArt` (round trip, NULL is
  "unknown" not "absent", `query_aggregate` counts only measured absences,
  migration leaves NULL), the cached scan's reuse-without-a-tag-read test,
  the legacy-row re-read test, and the full scan's counter. The recorded CLI
  corpus and schema examples are re-recorded, because the payload gained a
  field.
- **A finished cover pass updates the list and the figure in place.**
  `_on_covers_complete` calls `_apply_cover_run`, which drops every album whose
  *every* folder produced `extracted`/`kept` (an album spanning several folders
  is resolved only when the last one is), accumulates those files in
  `_covered_files`, and calls `_refresh_charts`. The scan's own counts are left
  untouched — a sidecar is a folder cover, not embedded artwork, so the scan
  never changes because of it — and the figure reads them net of the adjustment
  through `_chart_report`, which rebuilds the `StatsReport` with
  `dataclasses.replace` rather than mutating the scan's report. A dry run never
  applies; `_update_artwork_gaps` resets both `_covered_files` and
  `_art_scanned` when a new scan measures the library, so the adjustment cannot
  outlive the counts it was derived from. History is kept in `_chart_history`
  so the redraw does not need the cache. Locked by four app tests (live pass
  drops the album and halves the figure's `no_art`, dry run changes neither,
  a partly-covered multi-folder album stays, and a rescan clears the
  adjustment).
- **The Artwork Coverage panel is a route to the album list.**
  `build_summary_figure` publishes the panel's axis on the figure as
  `artwork_axes` (a `setattr`, because `Figure` is not ours to extend), and
  `_update_charts` binds `button_press_event` on the new Tk canvas — binding
  before the canvas exists would lose the callback, since matplotlib stores
  them per canvas instance — then compares `event.inaxes` by identity and
  selects `_artwork_frame` in the notebook. A click elsewhere, or an event
  with no axis, does nothing; the panel's x-label only advertises the route
  when some file is actually missing a cover. Locked by two app tests (a click
  on the panel lands on "8. Artwork Gaps"; clicks on another panel or outside
  any axis stay on Charts) and by the chart tests that pin `artwork_axes` and
  the label.
- **The Charts tab's summary figure gains an Artwork Coverage panel**
  (`library_stats/ui/charts.py::_add_artwork_panel`), drawn from
  `StatsReport.missing_data["no_art"]` against `total_files` — the fact the
  F-E10 scan already measured — so it re-reads nothing. Two bars (with /
  without artwork) and a percentage label; an empty scan draws the
  explanatory panel instead of an empty axis, like the trend. The trend moves
  from the spanning `(2, 3, (5, 6))` slot to `(2, 3, 6)`, so the figure is six
  equal panels and the axis index locks in `test_charts.py` and `test_app.py`
  move with it.
- **The dashboard's Artwork Gaps view is its fifth dashboard tab and the one
  write it offers.** `library_stats/core/artwork_gaps.py` selects the albums
  from `CompletenessReport.album_results` (no second library walk),
  `AlbumCompleteness` gains the `folders` its files live in so an album label
  can be turned into a place to write, and `run_cover_extraction` writes one
  sidecar per folder through
  `audio_suite_shared.tag_helper_art.extract_artwork`/`write_artwork_sidecar` —
  the same functions the Artwork Extractor and `audiosuite artwork extract` use
  — with dry-run, keep/force semantics and its own run report
  (`library_stats_artwork_log.txt`). The pass runs on the app's worker thread
  and publishes through the existing `SimpleQueue`; `_poll_events` gained the
  `covers`/`covers_error` kinds and the scan-complete handler refreshes the
  listing. Locked on real FLACs by `library_stats/tests/test_artwork_gaps.py`
  (selection, folder routing, a byte-equal sidecar, dry run, keep/force, report
  text) and `library_stats/tests/test_app.py::TestArtworkGapsView` (listing,
  guard, rendered outcomes).
- **The Artwork Extractor is a driver-schedulable window over F-E10's read
  side.** `artwork_extractor/` adds `utils/cli_args.py` (the shared handshake
  plus the tool's own `--name`, `--force|--no-force` and
  `--recursive|--no-recursive` pairs, last spelling wins),
  `core/extract.py` (one run through
  `tag_helper_art.extract_artwork`/`write_artwork_sidecar` and
  `cue_generator.scan_audio_files(recursive=...)`, with the dry run deciding the
  keep/replace outcome without writing) and `app.py` (a `SuiteApp` whose worker
  thread publishes through a `SimpleQueue`). The manifest id is `artwork` with
  `cli_command=None` — `artwork extract` belongs to the shared group — and the
  utility orders shift by ten from Tag Editor (70) through Track Splitter (200)
  so the new tool sits second in the `tags` block and the block stays
  contiguous. `arg_builder`, the driver state, `DEPENDENCY_GRAPH`,
  `HANDSHAKE_TOOLS`, `EXPECTED_TOOLS`, the utilities window order, the
  README/docs/CLI-reference/deck count claims and the regenerated guide are
  updated in the same change.
- **F-E10's read side is one artwork module, and both directions share it.**
  `audio_suite_shared/tag_helper_art.py` gains `sniff_image_format` (JPEG/PNG
  magic bytes), `image_dimensions` (PNG IHDR, first JPEG SOF marker),
  `extract_artwork` (through `TagHandlerFactory`, never a second mutagen read)
  and `write_artwork_sidecar`. The extension and mime come from the bytes
  because containers do claim `image/jpeg` over PNG data; an unnamed format
  raises rather than being mislabelled, a name carrying a path is refused so a
  write cannot leave the album folder, and `force=False` returns `None` after
  leaving an existing file's bytes and mtime untouched.
  `audio_suite_shared/artwork_cli.py` registers the `artwork` group (`extract`,
  `report`) and publishes under tool id `artwork` — a suite utility like `cue`,
  with no manifest entry, window or card. Its `--json` output is the payload
  alone, so the per-file `[NO ART]`/`[KEPT]`/`[EXTRACTED]` lines are text-mode
  only; `build_payload` derives `succeeded`, so a kept sidecar counts as handled
  and no `succeeded` extra is passed. `cue_generator.scan_audio_files` gains
  `recursive` so the extractor reuses the suite's one audio scan (album folders
  in name order, tracks naturally ordered inside each) instead of declaring a
  second extension table. In `library_stats`, `_read_file_tags` gains
  `art_fields` (presence, then size and pixel size) and `collect_export_rows`
  passes it; the default CSV appends the four art columns after every earlier
  one, and `EXPORT_COLUMNS` admits them for `--export-columns`. An incremental
  cached scan still reports no art — the cache carries no picture — while the
  export columns re-read each file at export time.
- **F-E9 answers equality, not similarity, and keeps the two claims apart.**
  `duplicate_finder/core/exact.py` owns `file_sha256`, `pcm_sha256` (an FFmpeg
  decode to `s32le` at the source's own rate and channels, hashed from a scratch
  file in 1 MiB chunks so an hour-long track costs the same memory as a short
  one), `attach_hashes` and `build_exact_groups`, which unions records sharing
  either digest — `clustering.UnionFind` became public for that second caller
  rather than being copied. `ScanSettings.exact_mode` is validated at
  construction; `fingerprinting.build_properties_record` gives `only` a record
  with no fpcalc call; the cache schema moves to version 2 and
  `FingerprintCache._migrate` adds the two columns to an existing file in place
  (literal DDL, never interpolated SQL), keeping every row. A fingerprint row
  with no words is never trusted as cached — `only` writes properties rows — and
  `also` removes exact-covered members from the perceptual groups so one file is
  named and counted once. Registration: `--exact` on the CLI and the window
  handshake, `duplicate_exact_mode` in the driver state and card, the arg builder
  emits it, and the regenerated `cli_schema.json`/`tests/data/cli_payloads.json`
  carry the new payload keys.
- **The CUE Sheet Generator is a Master Driver batch step.** `arg_builder`
  emits the four-flag handshake for `cue_sheet`, `DEPENDENCY_GRAPH` carries it as
  a dependency-free leaf, and the handshake contract now drives its `parse()`;
  no `cli_command` was added, because the sheet is still `cue generate`'s
  builder. The window's auto-start follows `--start` rather than "the driver
  launched me", so Auto Start means the same thing here as in every other tool
  and an unchecked Auto Start is respected (D-19).

- **Folder CUE export is one shared builder with a window in front of it.**
  `audio_suite_shared/cue_generator.py` gains `scan_audio_files`, `folder_specs`
  and `build_folder_cue`; `cue_cli.cue_generate_cli` and the new `cue_sheet`
  package (`core/export.py`, `utils/cli_args.py`, `app.py`) both call them, so
  the folder scan, the `NN - Title` fallback, the per-format `FILE` token and the
  duplicate-number `ValueError` exist once. The manifest entry carries no
  `cli_command`: `cue generate` is registered by the shared `cue` group, so a
  per-tool command would duplicate that registration, and the reference's
  existing `### cue generate` section stays its documentation. Utility orders
  shift by ten from Music Format Converter (40) through Track Splitter (190) to
  keep `cue_sheet` at 30 inside the `convert` block; `HANDSHAKE_TOOLS`,
  `EXPECTED_TOOLS`, the utilities window order and the README / CLI-reference /
  deck count claims are updated in the same change.
- **`audio_suite_shared/tag_templates.py` — templates and copy-from-reference.**
  `TagTemplate` (name, canonical field map, source file) is stored in
  `audio_suite_config.json` under `tag_templates`; `parse_fields` resolves every
  name through `rule_for`, so `FIELD_RULES` stays the only field table and a
  template cannot name a key no handler writes. `apply_template` diffs every
  target through `TagFieldEngine` before anything is written, runs the apply
  inside one undo batch (reusing a caller's batch when one is already open), and
  reports a failed file as that file's result. `tag-edit --copy-from/--fields`
  is the CLI surface; the Tag Editor converts a template into `FieldEdit`s so the
  window's existing dry-run diff and undo path do the work. The same change fixes
  `TagFieldEngine.write_fields`, which recorded its undo snapshot only on the
  key-rule branch: a handler's editable-field write saves immediately, so an
  editable-only write persisted with no undo entry.
- **The Utilities tab's grouping is manifest data with two locks.**
  `ToolManifest` gains `group` (a `UTILITY_GROUPS` key) and
  `tool_plugin.utility_sections()` turns the registry's utility population into
  captioned sections, falling back to a trailing "Other Tools" section rather
  than dropping a card whose group is undeclared; plugins always take the last
  section. The grid places captions and cells from one item list, so a caption
  cannot drift out of step with the cards it introduces. `tests/test_tool_plugin.py`
  locks the manifest side — every first-party utility names a declared group,
  every declared group has cards, `order` values are contiguous blocks of ten
  and the names are alphabetical inside a block — and
  `tests/test_utilities_window.py` freezes the rendered order, the caption
  geometry and the plugin section's position. The README tool index and the
  docs index were regenerated from the new order.

### Changed

- **A container the Normalise stage cannot write is a skipped stage, not a
  failed file.** `process_file` asks `_normalise_skip_reason` before any stage
  work, records `Normalise: SKIPPED` with the reason, and runs the in-memory
  stages on `dataclasses.replace(config, normalise=False)` so Enhancement's
  output gain is not suppressed for a normalisation that will not happen. The
  dry run reports the same reason through `_preview_normalise`, so it cannot
  promise a write the live run skips. The progress line now shows a skip reason
  verbatim: `reason.lower()` had mangled every acronym and format name in it
  while the run report kept the original. Locked by
  `test_convert_and_pipeline.py::TestUnencodableContainerIsSkipped` and
  `TestRunPipeline::test_the_skip_line_keeps_the_reason_verbatim`.
- **The Normalise stage's encoder set covers integer PCM.** `.wav`/`.aiff`/`.aif`
  resolve through `audio_formats.ffmpeg_encoder_args` instead of a tuned
  `_FORMAT_CODEC` entry, and `_depth_args` re-pins the source's depth with
  `preserve_depth_params` before the encode, because FFmpeg's WAV/AIFF muxers
  write 16-bit PCM whatever came in. `NORMALISE_EXTENSIONS` and
  `normalise_format_display()` derive the refusal's format list, so a stale list
  cannot ship; `apply_static_gain` pins depth for any integer-PCM destination,
  which is what lets album mode inherit the fix. Locked on decoded files
  (`test_normalizer_core.py::TestPcmContainers`, the WAV album test, and
  `test_convert_and_pipeline.py::TestPcmNormaliseThroughThePipeline`).
- **The static-gain write has one implementation and two callers.**
  `apply_static_gain` was split out of `apply_album_gain` in
  `audio_normalizer/core/album.py`: the limiter chain, the tag rewrite, the
  snapshot and the depth pin stay in one place, and the Refinery's peak target
  is the second caller rather than a second applier.
  `audio_suite_shared.audio_formats.ffmpeg_encoder_args` (new) resolves a
  container's own encoder from `FORMAT_MATRIX`, so a peak run can write WAV/AIFF
  through the normaliser's codec set — which deliberately refuses those
  containers — without a hand-written second table; the opt-in
  `lossless_output` flag keeps album mode's refusal and encoders unchanged, and
  `preserve_depth_params` pins the source depth on the rewrite. Git had no
  branch here: the peak stage is a new field pair
  (`NormaliseParams.target_mode`, `target_peak_dbtp`) and a new stage branch, and
  `audio_refinery/tests/test_peak_normalise.py` decodes the written file to
  measure sample peak, true peak, full-scale sample share and crest factor.

- **The Enrich tab's grouping reuses the Utilities splitter, not a copy.**
  `tool_plugin.grouped_sections()` is the one implementation behind both tabs;
  `utility_sections()` and `enrich_sections()` are its two call sites, differing
  only in the `UTILITY_GROUPS` / `ENRICH_GROUPS` declarations they pass. The
  plugin-last and undeclared-group rules live in the shared function, so the
  tabs cannot disagree about them. `master_driver/ui/group_caption.py` holds the
  caption widget for the same reason: `GroupCaption` is a `tk.Label` (so the
  Utilities grid can never mistake a caption for a card), and both tabs import
  it. ENRICH keeps its dependency-vetted order inside each group — the
  renumbering into blocks of ten changes no run — and
  `master_driver/tests/test_enrich_tab.py` freezes the rendered order, the
  captions with their card runs, the LAUNCH button's position after the last
  group, and the caption dropped for a group that built no card.
  `tests/test_tool_plugin.py::TestEnrichGrouping` locks the manifest side,
  including that grouping did not reorder the run. The new `Changed in 2.5.0`
  notes took 2.5.0's count from 234 to 240, so `tests/data/changed_in_baseline.json`
  was re-recorded with `utilities/changed_in_budget.py --record` (1680 lines,
  28 versions); the budget gate passes at the new ceiling.

- **Tests: the reflow locks are relative to the first card's row.** Adding a
  caption row per group shifted every absolute row index, so the four reflow
  tests now derive their expected rows from the first card instead of assuming
  row 0 — the assertion they exist for (the pair behind an open card starts a
  fresh row) is unchanged.

- **The release-note lock names 2.6.0.** `tests/test_release_notes.py`
  re-baselines `BASE_COMMIT` to `be17c9d` (the commit `v2.5.0` points at) and
  `NOTE_MARKER` to `Changed in 2.6.0`, so the Utilities/Enrich grouping's six
  notes name the release that will carry them rather than the tagged one that
  does not (`PLAN_2026-11-08_enrich_card_grouping.md` D-08). The changed-in
  baseline was re-recorded with it: 2.6.0 holds 24 note lines of the 1,683.

- **The change history is categorised again, and the categories are a lock.**
  The five sections from 2.4.1 forward - `[Unreleased]`, 2.5.0, 2.4.3, 2.4.2
  and 2.4.1 - had been promoted as flat bullet lists: `promote_changelog`
  copies the `[Unreleased]` body verbatim and nothing required a category, so
  70 bullets (20 user-facing, 50 technical) reached the files without one. They
  are now grouped under `### Added`/`### Changed`/`### Removed`/`### Fixed` by
  an explicit per-bullet map, with the bullet text byte-identical before and
  after (206 and 133 bullet texts compared, only whole blocks moved); the
  category is decided by the bold lead-in, the rule the audience lock already
  uses. `tests/test_changelog_format.py::TestChangelogCategories` closes the
  gap: a section with bullets must carry a category, every bullet must sit
  under one, the six Keep a Changelog names are the only legal headings, no
  category may be empty, an empty section must be `[Unreleased]`, and a
  non-vacuity floor plus a proof-it-fails case keep the scan honest. The
  mapping rule is in `AGENTS.md` (*Change History Follows Its Audience*),
  `documentation/docs/release.md` and both file headers; the changed-in
  baseline was re-recorded with it (2.6.0 now holds 25 note lines). The four
  release pages whose bodies had gone flat - 2.4.1, 2.4.2, 2.4.3 and 2.5.0 -
  were then republished from the grouped sections and read back equal from the
  API; the eight pages from 2.4.0 back already matched, so the check measured
  the drift instead of assuming it (`PLAN_2026-11-08_changelog_categories.md`
  D-07).

## [2.5.0] - 2026-11-08

### Added

- **The suite finds its own files from one root.** It was derived nine times -
  `Path(__file__).parent.parent` in the config and logging modules,
  `parents[2]` in the plugin loader and the Fingerprinter,
  `dirname(__file__)/..` twice in the Master Driver - and the Help button did
  not derive it at all: `open_help` walked up from `Path.cwd()` until a folder
  was named `AudioSuite-Pro`, so a renamed checkout, a shortcut started
  elsewhere or any packaged build reported "Help File Not Found" while the
  guide sat exactly where it had been installed. `suite_paths.suite_root()`
  now answers for an `AUDIOSUITE_ROOT` override, a one-file bundle's
  `_MEIPASS`, a frozen executable's directory, or the source checkout, and it
  never reads the working directory. `discid.dll` and the committed
  `fpcalc.exe` are located through it too, and the reuse lock fails on a
  module that goes back to matching a directory name.

- **One FFmpeg resolver for the suite.** `audio_suite_shared/ffmpeg.py` now
  owns the binary lookup: `FFMPEG_PATH`/`FFPROBE_PATH` for callers that need
  an argv[0], `find_ffmpeg()`/`find_ffprobe()` answering None so a caller that
  can degrade asks a question instead of parsing the bare-name sentinel, and
  `require_ffmpeg()`/`require_ffprobe()` raising `AudioMissingDependencyError`
  with a `dependency` context. The resolver moved out of the Audio
  Normalizer's package, which three tools imported from, and replaced the
  four hand-rolled lookups in the Audio Enhancer, Audio Refinery, shared
  analysis loader and the refiner's test helper - including the one that
  resolved a path and then handed the wrapper the literal `"ffmpeg"`. The
  reuse lock's allowlist shrinks to that single module, so a fifth copy
  cannot appear quietly, and `audio_suite_shared/tests/test_ffmpeg.py` (moved
  with the resolver) keeps the three discovery sources, the executable-file
  gate and the patch-leak lock, plus new FFprobe coverage.

- **One implementation per capability, and a lock that keeps it that way.**
  `tests/test_shared_code_reuse.py` reads the shipped runtime and fails when a
  module declares its own audio-extension list, looks the FFmpeg binary up via
  `shutil.which` instead of importing `FFMPEG_PATH`, or writes
  `audio_suite_config.json` itself. Today's legitimate subsets are frozen in
  the lock's allowlist with a reason each, so the set cannot grow while the
  remaining FFmpeg lookups are converged; the detectors are self-checked so a
  broken scan fails instead of passing vacuously. The filename character set is
  now declared once in `InputValidator` and imported by the Track Splitter, the
  CUE splitter and the Audio Joiner, and `validate_filename` rejects only what
  the filesystem actually refuses instead of an ASCII allowlist that called
  legal names unsafe. The rule itself is recorded in `AGENTS.md` under *Shared
  Implementations First*, with the table of where each capability lives.

- **The Track Splitter's engine is a pure parser beside one FFmpeg call.**
  `track_splitter/core/detector.py` splits into `detect_gaps` (one
  `silencedetect` run through `run_secure_subprocess`) and `parse_gaps`, a pure
  parser over the filter's report, so the boundary arithmetic is tested without
  spawning FFmpeg; `plan_tracks` in `core/models.py` is pure as well. The locks
  measure decoded audio: a tone/gap/tone fixture is split, the written tracks are
  decoded, and the test asserts the per-track head is the tone and the tail is
  the silence it should have cut, that the durations sum to the source, and that
  the written CUE re-parses to the plan's offsets within one CD frame (13 ms) -
  the format's own quantisation, not a tolerance chosen to pass.

- **Guide figures: one capture step, one renderer block, two locks.** A guide can
  embed `![caption](images/x.png)`. `utilities/build_user_guides.py` renders it
  at 6 in with the caption centred beneath, resolves the reference against the
  guide source's own folder (refusing a drive letter or `..`), and `--check` now
  compares the embedded `word/media/` entries as well as `word/document.xml`, so
  a re-captured screenshot that was not re-rendered is reported instead of
  surfacing as unexplained container drift. `utilities/capture_guide_shots.py`
  is the only writer of those PNGs: it builds the real tool window, fills it
  through the tool's own `_update_progress_ui`/`_update_ui_on_complete` with the
  sample run declared for that tool (`SAMPLE_RUNS`: the per-file status
  vocabulary, worker-slot text and counters its own processor publishes, so no
  Processing figure shows another tool's run, and a tool that declares no run
  fails the capture rather than inheriting one), answers the shared config in
  memory (palette, theme,
  typography, geometry, last directory), neutralises `sys.argv` and the What's
  New panel, and photographs the **decorated** window the tool really shows, at a
  size pinned per tool. The origin is calibrated rather than computed: a
  decorated window's requested position is never its painted one, and a
  requested `+120+120` paints lower and further right once the frame offset is
  counted. A 40 px marker block at the client's top-left is
  located in a screen grab and supplies the origin, and a window that still lands
  past the screen edge is corrected by the measured delta and re-calibrated - which
  is how the 1007 px Fingerprinter window fits above the taskbar. The declared
  size is load-bearing too: the shared run-controls panel positions part of itself
  with `place()`, so no request/extent walk can see the controls a 776 px window
  clips. The process also asks to be DPI aware before Tk starts, because a
  DPI-unaware Tk reports logical sizes while `ImageGrab` copies physical pixels:
  on a 125% display every figure was silently cropped to the window's top 80%,
  which emptied the band where the BPM Setup tab's bottom-docked start button
  sits. Each plan's window is now requested at `dpi/96` times its pinned size and
  the grab is scaled back to the pinned size, so the layout is the 100% one at
  any scaling. The capture still refuses a blank frame and a rectangle that runs
  off-screen. A tool's figures are its notebook's tabs, enumerated at
  runtime (``notebook``, or the hand-built windows' ``_notebook``); a tab the tool
  disables until a disc is present is enabled for its own figure, and a
  single-pane window is captured as ``window.png``. Each capture writes a sidecar
  with the PNG's SHA-256. `tests/test_docs_formats.py` admits `.png` deliberately, and
  `tests/test_user_guide_hygiene.py::TestGuideScreenshots` holds every committed
  PNG to its sidecar and to the guide that shows it, with a tampered copy and an
  unreferenced copy proving the lock fails rather than passing vacuously.

- **Exact-trim locks and the second write path (F-E3).** The engine is
  `audio_refinery/core/trim.py` — `resolve_range`, `slice_segment`, `copy_trim`,
  the two message builders and `check_copy_mode` — locked by
  `audio_refinery/tests/test_trim.py`, the mirrored name the plan's
  `test_exact_trim.py` could not keep without moving the frozen naming allowlist.
  The re-encode lock compares the sliced PCM with the source's own samples at the
  same offset; the copy lock measures the written file with `ffprobe` and decodes
  it again, so a copy that began at the wrong offset fails on the audio rather
  than on a flag. `process_file` gained a second write path for copy mode,
  extracted to `_run_exact_copy_trim` because the inline version pushed it past
  the 110-statement lint ceiling, and an `AudioConfigurationError` now reaches the
  user as its own message instead of `user_message_for`'s generic "A configuration
  error occurred". The driver's argument builder emits the exact-trim flags only
  when the mode is exact, so a silence-trim run's argument list is byte-identical
  to before, and the panel is re-synced after a CLI or preset load so a driven
  launch cannot display silence beside a range trim.

### Changed

- **The hand-built-path rule covers every binary the suite ships.** It named
  only `ffmpeg` and `ffprobe`, so a module could join its own path to
  `fpcalc.exe` or `discid.dll` and pass the sweep that catches exactly that
  shape one binary over. `BINARY_FILE_NAMES` gains `fpcalc`, `fpcalc.exe` and
  `discid.dll`; the two sites that legitimately name a shipped copy carry a
  reason instead of a workaround - the Fingerprinter's committed
  `fpcalc.exe` (its last resort after the shared search) and `CD_Ripper.pyw`'s
  `discid.dll` (`ctypes` needs a DLL path, which `search_binary`, answering
  executables by name, cannot supply).

- **The reuse lock reads the launchers, and the launchers lost their third
  dialog copy.** The sweep walked `*.py`, so all 31 `.pyw` launchers were
  outside every rule - as they are outside ruff, mypy and bandit, which take
  `*.py` only. It now walks `*.pyw` too, and a new rule fails on a module that
  builds a Tk root, hides it and calls `showerror`, which is how three copies
  of the launcher error dialog had accumulated. `File_Reorganizer.pyw` and
  `Tag_Field_Updater.pyw` call
  `audio_suite_shared.launch_failure.show_error_dialog` instead: it destroys
  the root it created, returns the exception when Tk itself fails so the
  caller can log the traceback, and leaves the original failure reportable.
  The existing launcher behaviour lock (dialog failure logged with a
  traceback, working dialog silent) is unchanged and still passes.

- **The other packaged binary uses the shared search, and the third reuse rule
  closed the gap that let a dead lookup survive.** `audio_suite_shared`'s
  resolver now exposes `search_binary(name)`, and the Fingerprinter's
  `resolve_fpcalc` calls it instead of asking `PATH` itself: the precedence
  (explicit path, `FPCALC`, then the search, then the committed
  `fpcalc.exe`) is unchanged, but a one-file build now finds the copy
  unpacked into `sys._MEIPASS` rather than the one beside the checkout.
  FFmpeg's own `C:\ffmpeg\bin` became a parameter, so it can never answer for
  a binary that is not FFmpeg. The ReplayGain analyzer's
  `get_resource_path` — a bundle-aware helper whose last caller converged on
  D-39 — is gone, with the test that asserted it returned a string, and the
  reuse lock now fails on any shipped module outside the resolver that reads
  `sys._MEIPASS`.

- **The reuse lock sees the second way a module can pick FFmpeg.** It only
  recognised `shutil.which("ffmpeg")`, so the ReplayGain analyzer's
  `get_resource_path("ffmpeg.exe")` plus `os.path.exists` passed the sweep that
  found every other copy. `_joins_a_binary_path` now flags a spelled-out
  binary name handed to a path builder - `os.path.join`, `Path`, a
  `get_resource_path`-style helper, `exists`/`isfile` - including the `Path /`
  division form, while deliberately leaving `run_secure_subprocess("ffmpeg",
  args)` alone: naming the binary the wrapper runs is not a lookup. The
  self-check drives the exact shape that slipped through, so the lock cannot
  pass by only knowing the form it already caught.

- **The ReplayGain analyzer runs the shared FFmpeg.** Its
  `core/ffmpeg_metrics.py` had the last hand-rolled lookup in the tree: a
  Windows-only `ffmpeg.exe` beside `core/`, the bare name everywhere else. It
  now returns `FFMPEG_PATH`, and the frozen-bundle directory that branch was
  really for (`sys._MEIPASS`) joined the shared search order instead, so a
  one-file build finds its bundled binary and every other tool gains the
  source. The platform matrix loses that branch - it no longer exists - and
  drops from 33 rows to 32.

- **`AppState.__init__` grew past ruff's statement budget (PLR0915, 116 > 110),**
  so the three tools that own option variables (Track Splitter, ASX extractor,
  restoration) moved into `_init_tool_option_vars`; behaviour is unchanged and
  nothing was suppressed.

- **Album-mode locks, and the 2.5.0 note window (F-E1).** The plan named its
  Refinery lock `test_album_mode.py`, which `tests/test_test_file_naming.py` would
  reject against its frozen allowlist; the locks therefore live in
  `audio_normalizer/tests/test_album.py` (the engine),
  `audio_refinery/tests/test_pipeline.py` (the stage, mirroring `core/pipeline.py`)
  and `audio_refinery/tests/test_file_processor.py` (the run-level pre-pass),
  mirroring the arbitration 2.4.2 D-8 recorded. `tests/test_release_notes.py` is
  re-baselined to the 2.4.3 release commit with the `Changed in 2.5.0` marker, and
  `tests/data/changed_in_baseline.json` records the window's note ceiling.

### Fixed

- **The plan no longer writes leading or trailing silence as a track.** A file
  that opens with room tone produced a first track of pure silence; the plan now
  clips to the first and last interior gap and refuses a wholly silent source
  with `AudioConfigValueError`. `SplitOutcome.discarded_ms` carries the
  difference into the run report.

## [2.4.3] - 2026-11-06

### Added

- **The per-file change notes have a recorded ceiling (WP-10 C-I2).** Every
  changed code file carries a `Changed in <version>:` note, and with the cleanup
  deferred that prose grew one line per change with nothing measuring it.
  `utilities/changed_in_budget.py` counts the notes and compares them with
  `tests/data/changed_in_baseline.json`: a version over its recorded count
  fails, and so does a version carrying notes with no recorded ceiling, so a
  release window starts from a number rather than an implied infinity.
  `--record` writes today's counts exactly, so recording still refuses the next
  line of growth. It runs in the `compile` CI job, which installs nothing.

- **The suite publishes a per-package coverage table (WP-10 C-I9).** The
  coverage verdict is a single number, so nothing said where the cold code was.
  `utilities/coverage_table.py` reads the JSON report the suite already writes,
  groups each file under its top-level package, sorts the coldest first, and
  renders a Markdown table whose total row is summed from the groups; the
  `test` job uploads it as the `coverage-table` artefact. It is not a gate - no
  threshold, and it exits `2` only when a payload cannot produce a table, so a
  missing or malformed report can never publish an empty table that reads like
  a healthy one.

- **The package-data declaration is checked against the package and the wheel
  in both directions (WP-10 C-I6a).** The wheel test hard-coded two file names,
  so a declaration naming a file that had since been renamed would ship nothing
  while every test stayed green, and a data file added to the package root
  without a declaration would never reach an install. The new lock reads
  `[tool.setuptools.package-data]`, expands each pattern against the package
  root (`fnmatch`, so a glob is not misread as a literal), fails on a stale
  entry as well as on an undeclared data file, and builds one wheel to prove
  the resolved names really ship. Subpackages are out of scope and say so: a
  data file there needs its own declaration key.

- **A suggestions list holds the ideas that are not in a plan.**
  `PLAN_suggestions.md` records the follow-ups the WP-10 tail raised (`S-1`..
  `S-5`, all from the wheel build's measurements): a declared-vs-shipped
  `package-data` check, a consumer type-checked against the installed wheel, a
  documented `typing_consumer/`, an sdist assertion, and an "assert the build's
  exclusions from the outcome" lock. Each row names the commit that produced it,
  the failure class it closes, its cost and what would own it if promoted; an
  entry is promoted or dropped explicitly and never deleted. The `2.4.3` plan
  points at the file so it is discoverable, and it adds no gate and no
  file-list entry.

- **`audio_suite_shared` ships a PEP 561 marker (WP-10 C-I6).** `py.typed` is
  declared in `[tool.setuptools.package-data]`, and `tests/test_py_typed.py`
  builds a wheel from a staging copy of the packaging inputs, asserts the file
  is inside it, and reads the shipped `cli_schema.json` back out byte for byte,
  so a wheel install no longer looks like an untyped package that a downstream
  checker skips and treats as `Any`. The
  declaration states intent rather than mechanism: setuptools already copies
  `py.typed` on its own (measured - a build with the entry removed still
  carried it), and the build test is what fails if the marker stops shipping.
  A consumer fixture outside `tests/` (`typing_consumer/consumer.py`)
  asserts the public signatures with `assert_type`, which the bare `mypy .`
  gate checks; its negative control in `tests/test_py_typed.py` mutates one
  assertion and requires mypy to reject it, so the lock cannot pass with `Any`
  standing in for the annotations. `py.typed` joins the release-note lock's
  declared exception categories: the marker has no comment syntax.

- **The run-report contract is a rule with an artefact lock.** `AGENTS.md` gains
  *Run Reports vs Program Logs* — which file View Log opens, the report's shape
  and location, why `_log_path` is empty until a run names its report, and that
  a program log is never the target — plus three bug-hunt rules drawn from the
  same defect: read the working sibling before designing a fix, a fallback that
  silences a symptom is not a fix, and a test that passes on the unfixed tree
  locks nothing. `tests/test_suite_app_contract.py` now drives each shell
  adopter's completion and reads the report back from disk, so a tool that only
  assigns `_log_path` fails instead of passing.

- **One batch-window shell.** `audio_suite_shared/suite_app.py` adds
  `SuiteApp`, which composes the window every batch transformer built by hand:
  the Help bar, the notebook, the shared Processing tab
  (`ui_common.build_processing_tab`, worker grid included) and Results tab
  (`build_results_tab`), and the progress/complete/error handlers, all obeying
  the callback contract. A tool supplies its identity (`title`, `window_key`,
  `program_name`, `guide_name`, `completion_text`), its worker slots and
  `_build_setup_tab(parent)`; it overrides a payload handler only where the
  payload is its own and calls `super()` for the shell's tail.
  `music_format_converter` is the first adopter: its own `_build_ui`, Help bar,
  notebook, three tab frames, Processing/Results wiring and its
  `_open_log`/`_open_output_folder`/`_on_error` copies and its now-unreferenced
  `ui/processing_tab.py`/`ui/results_tab.py` wrappers are gone (the shared
  builders render those tabs, so the wrappers lost every importer), while its
  report, presets, CLI handling, validation and run note are unchanged.
  `tests/test_suite_app_contract.py` builds each adopter's real window and
  locks the declared tabs, the shared Processing/Results widgets, the
  Help/View Log/Open Folder wiring (invoked, not read from `cget("command")`),
  the Mode/Auto Start/Auto End controls, the single title and the identity the
  shell receives; its `MIGRATED` table is frozen and a tool that reintroduces
  its own `_build_ui` fails it.

### Changed

- **Complexity ceiling adopted and the four worst functions restructured (WP-9
  §3.3).** `PLR0912`/`PLR0915` are selected with limits set just above the
  post-restructure maxima (37 branches, 110 statements), so a new function
  larger than today's worst fails review while the restructured four sit far
  below it. `_collect_tags_to_preserve` is now a per-container dispatcher over
  four collectors (the ID3 one shared by MP3 and WAV/AIFF/DSF);
  `audio_refinery::_apply_preset` copies preset keys from five declarative
  tables; `library_stats/cli.py::stats` is split into cache selection,
  scan/history execution and report rendering with its JSON schema and output
  order unchanged; and `asx_stub::parse_stub_bytes` accumulates one payload per
  metadata group, preserving the PARAM validation order. The restructure also
  fixed the scripted-edit trap that dropped `stats`' click decorators: the AST
  span of a decorated function begins at its first decorator, so a replacement
  must re-emit that block.

- **`library_cache` split into three modules (WP-9 #5, the last of the five).**
  1,038 lines are now 237 plus `cache_schema` (DDL, schema version, the path
  normalisers, every scope SQL string and the two connection hooks),
  `cache_store` (file rows, scope selection, aggregate queries and the key/
  decade classifiers) and `cache_prune` (whole-cache clearing and the
  completeness trend). The store and prune halves are mixins, so bodies are
  byte-identical; `LibraryCache._connect` calls the schema helpers under the
  same lock in the same order. All moved SQL names stay re-exported because the
  cache tests import them from the old path — no test or patch target changed.

- **The fingerprinter's `file_processor` split into three modules (WP-9 #4).**
  1,232 lines are now 673 plus `fingerprint_messages` (the status formatters and
  `_MESSAGE_STATUSES`), `fingerprint_tags` (the single tag-write tail) and
  `fingerprint_phases` (the album phase and the ISRC submission pair), arranged
  as a DAG so the album phase can use the tag-write tail without a cycle.
  Bodies are byte-identical and all twelve names stay re-exported. Three patch
  targets followed their call sites, and the two source locks now scan all four
  modules — the same assertions, applied to the whole pipeline.

- **`batch_undo` split into three modules (WP-9 #3).** The 1,264-line module is
  now 472 lines plus `undo_schema` (the DDL string, the `auto_vacuum` flag and
  the delete-payload migration), `undo_records` (the three record types, batch
  lifecycle, record writing and pruning) and `undo_revert` (the four revert
  paths). The schema helpers became module functions taking a connection; the
  record and revert halves are mixins, so every remaining body is byte-identical
  and `BatchUndoLog._connect` calls the helpers under the same lock in the same
  order. The thread-local API and snapshot functions never moved, so none of the
  28 test patch targets changed; moved names are re-exported and added to
  `tests/test_public_api_paths.py`.

- **`file_processor_base` split into four modules (WP-9 #2).** The 1,132-line
  module kept a 790-line class holding discovery, two executor loops, the
  in-place DSP batch and the reporting helpers. Each group is now a mixin in its
  own module — `file_discovery`, `parallel_pool`, `inplace_workflow`,
  `reporting` — cut by AST line range with decorators included, so every method
  body is byte-identical and no call site changed; `BaseFileProcessor` composes
  the four and keeps `__init__`, `process_batch` and `run_analysis_workflow`
  (314 lines). Each mixin declares the host attributes it reads, which is what
  keeps bare `mypy .` strict-clean. Six test patch targets followed the code
  (`cleanup_expired_resources` to `reporting`; `ProcessPoolExecutor`,
  `as_completed`, `WORKER_TIMEOUT_SECS`, `retry_with_backoff` to
  `parallel_pool`; `record_audio_overwrite_snapshot` and `get_active_batch_id`
  to `inplace_workflow`; `os.scandir` to `file_discovery`), with no assertion
  changed, and `tests/test_public_api_paths.py` now freezes the
  `file_processor_base` facade too.

- **`ui_common` split into four modules (WP-9 #1).** `audio_suite_shared.ui_common`
  (1,363 lines) now holds `BaseSetupFrame`, `AnalysisSetupFrame`,
  `cap_typed_workers` and `install_optional_dependency`; the Results/Processing
  tab builders moved to `ui_tabs`, the row builders to `ui_rows`, `show_message`
  and its three section builders to `ui_dialogs`, and the preset helpers to
  `ui_presets`. Every moved name is re-exported from `ui_common` in the
  redundant-alias form, so the 200-odd existing importers are unchanged, and
  `tests/test_public_api_paths.py` freezes the old paths and asserts each facade
  name *is* the new module's object (a copy would drift). Three test patch
  targets followed the code they patch (`ui_tabs.run_secure_subprocess`,
  `ui_dialogs._log`); no assertion changed. API docs gained the four modules.

- **`library_stats` adopts the shell (WP-8 order #3).** `LibraryStatsApp` now
  extends `SuiteApp`: the toolbar, status bar and hand-built four-tab notebook
  are gone, the shell supplies Help, Setup/Processing/Results and both callback
  tails, and the dashboard's four tabs arrive through a `_tab_specs` override
  (the shell documents that extension point). The Cache checkbox and Refresh
  button folded into the strip's Mode — Incremental / Full / Direct — because
  they were two controls for one decision; `_use_cache` and `_refresh_cache` are
  derived from it, and `--incremental`/`--refresh` seed it. The scan worker now
  posts `(kind, payload)` on a `queue.SimpleQueue` drained by a Tk-thread poller
  instead of calling `root.after` from the worker (the AGENTS.md D136 class), and
  a finished scan writes `library_stats_scan_log.txt` through
  `_begin_run`/`_write_run_log`. The contract test is parametrised over three
  adopters and asserts each one's completed run leaves a report on disk.

- **One implementation of the "no log yet" branch, and the checklist names it.**
  `mood_analysis_batch_tagger` kept its own copy of the View Log branch (its own
  dialog title, its own wording) beside `ui_helpers.open_log_file`, so the one
  GUI tool outside the shared handler could drift unnoticed; `_on_open_log` now
  delegates, and its two tests patch the shared helper's namespace.
  `tests/test_log_button_contract.py` scans first-party Python and fails if the
  message appears anywhere but `audio_suite_shared/ui_helpers.py`.
  *Registering a New Tool* gains item 12: write the run report, name it in
  `_log_path` when a run starts, and lock it with a test that reads the file.

- **The reorganiser adopts the shell, and its scan thread stops touching Tk.**
  `file_reorganizer/app.py` is now a `SuiteApp` adopter: the single-pane
  composer is gone, the Setup tab carries the run-controls strip, presets,
  destination, action and pattern editors, and the Processing/Results tabs come
  from `ui_common`. Its engine progress callback ran on the scan thread and
  called `root.after` from there — the `threading.Thread` + `after` defect class
  recorded in AGENTS.md (D136, which raises `main thread is not in main loop` on
  3.14) — so workers now post `_RunEvent`s to a `queue.SimpleQueue` and a
  Tk-thread poller drains them; the tests assert a worker never calls
  `root.after`. The Dry Run checkbox became the strip's Mode, with `dry_run`
  derived from it in one direction only and the legacy `dry_run` preset key
  still honoured, and the driver's `--live`/`--start`/`--end` flags — parsed
  but previously dropped — now reach the panel. The shared contract test gains
  the second adopter plus a per-tool process-edge stub table (`_STUB_EDGES`).

### Removed

- **The conversion re-export shim and two ignored `config_path` parameters are
  gone (WP-10 C-I7).** `audio_refinery/core/convert.py` re-exported
  `audio_suite_shared.audio_conversion` for backward compatibility, and
  `pipeline.py` was its only importer; the shim and its two-test lock
  (`TestConvertReExports`) are deleted together, and the pipeline imports the
  helpers from their canonical module. `tempo_analyzer.utils.config`
  (`load_scheme`/`save_scheme`) and
  `mood_analysis_batch_tagger.utils.config` (`load_run_mode`/`save_run_mode`)
  accepted a `config_path` argument they never read, so a caller could pass one
  path and have the shared suite config written instead; both signatures are
  now free of it, with every call site updated.

### Fixed

- **The reorganiser writes a run report; View Log never opens the debug log.**
  `file_reorganizer/app.py` now builds the suite's report shape —
  `FILE REORGANIZER REPORT`, `Mode: DRY RUN|LIVE UPDATE`, the run's settings, a
  60-`=` rule, the per-file lines and a `SUMMARY:` block with the counters and
  `Time: MM:SS` — into `<source>/reorganizer_{dry_run,sync}_log.txt`, and sets
  `_log_path` when a run starts. That is the convention BPM Analyzer and
  `AnalysisAppBase`/`ToolAppBase` follow, where the path is empty until the run
  names its report; the per-program log stays diagnostic. `SuiteApp` therefore
  keeps `_log_path` empty instead of seeding the debug log, and
  `logging_setup.program_log_path` is not introduced. `TestRunReport` reads the
  written file (header, per-file lines, summary), so a writer that sets fields
  without serialising them fails.

- **A refused launch explains itself (D-22).** `audio_suite_shared.launch_failure`
  now records why a launcher exited 1, keyed by the launcher's script name — the
  one name the tool and the driver both hold, so no tool must learn a manifest
  id. `parse_cli_args` captures the parse-time stderr, logs it beside the exit
  code and records it; `BatchOrchestrator` clears the record before each step,
  so a stale reason cannot explain a later failure; and
  `module_runner._failure_message` quotes it under the exit code. Locks:
  `tests/test_launch_failure.py`, `tests/test_launcher.py`
  (`TestRefusedLaunchIsExplained`, which runs the real `library_stats` parser)
  and `test_runner.py::TestRunModulesProgress`.

## [2.4.2] - 2026-11-04

### Changed

- **One tag layer.** `audio_suite_shared/tag_field_engine.py` is the
  suite's single field table — `FieldRule` + `FIELD_RULES` (the nine
  editable fields, plus the five key rules for the `TXXX`/Vorbis/
  MP4-freeform genre keys and `TCON`/`GENRE`/`©gen`/`Genre`) — and
  `TagFieldEngine`, whose `read_fields`, `diff`, `raw_updates`,
  `write_fields(dry_run)`, `delete_fields` and `has_tags` save once per
  file. `tag_helper_mp3`/`vorbis`/`mp4`/`apev2` gained `convention` and
  `read_field_key`/`set_field_key`, so container knowledge stays with the
  handler that owns it. `tag_field_updater` is a consumer:
  `mapping_engine.TAG_MAPPINGS` and the eight `process_*_file` rules
  collapse to `SLASH_FIELDS` and one `process_file`, and `tag_editor`'s
  cross-tool import became `split_slash_genre`. The mapping rules are
  locked by `tests/test_tag_equality_across_tools.py` (the same edit
  through both tools on `.mp3`/`.flac`/`.m4a`/`.wav`, compared decoded
  and atom by atom), by
  `tag_field_updater/tests/test_transformation_rules.py` (the dry-run
  gate, measured on disk) and by `metadata_scrubber`'s raw-frame lock.
  The per-format mock suites were deleted with the per-format rules they
  tested; `.wma` is refused, a user-visible change recorded in
  `CHANGELOG.md`.

- **One measurement path.** `audio_suite_shared/audio_probe.py` now owns the
  suite's FFmpeg measurement — `probe_stream`, `measure_levels`,
  `measure_loudness`, `measure_album_loudness` and `decoded_duration` — with the
  decode policy in one place: every call goes through the secure subprocess
  wrapper, `ffprobe` describes the stream, `ffmpeg -f null -` decodes it, no
  pydub sits in the path, and a non-finite reading is reported as absent rather
  than as a plausible `0.0`. ReplayGain's `ffmpeg_metrics.get_metrics` and
  `measure_album_loudness` are now thin adapters that keep their return shapes
  and failure contract. `replaygain_analyzer/tests/_legacy_metrics.py` freezes
  the 2.4.1 implementation and `test_ffmpeg_metrics.py` measures nine files
  twice — generated tones, three CC0 recordings and one read-only `.ape` —
  asserting agreement within 0.05 dB loudness, 0.05 dB peak and 1 ms duration,
  with the album rule locked the same way;
  `tests/test_loudness_agreement.py` holds the cross-tool criterion that
  `ebur128` and `loudnorm` agree within 0.1 dB on the same file. Thirteen mocks
  that patched ReplayGain's `run_secure_subprocess` were retargeted to the
  probe, because that seam moved with the implementation.

- **One loudnorm parser.** The Audio Normalizer's analysis pass now runs
  through the same probe: `audio_normalizer/core/loudness.measure` maps
  `loudnorm_inputs` onto its published five-key dict (same keys, same `-70.0`
  floor for a silent file) and `parse_output_true_peak` delegates to
  `achieved_true_peak`. The probe gained `loudnorm_inputs` — the raw input
  figures with absence reported as `None`, which is what the normaliser's
  second pass needs — and now reads `target_offset` as well, since dropping it
  would have silently removed `offset=` from the filtergraph.
  `audio_normalizer/tests/_legacy_loudness.py` freezes the 2.4.2 implementation
  and `test_normalizer_core.py` measures two tone levels, digital silence, two
  CC0 recordings and one read-only `.ape` twice, requiring the same values
  within 0.01 dB; a one-digit change to the silence floor fails that lock. Three
  mocks that patched the normaliser's `run_secure_subprocess` were retargeted to
  the probe, because that seam moved with the implementation.

## [2.4.1] - 2026-11-04

### Added

- **One driver handshake.** `audio_suite_shared/cli_helpers.py` now owns the
  grammar every child tool reads the Master Driver's argv with: a frozen
  `DriverHandshake`, one `scan_value_options` scanner, one
  `parse_driver_handshake` reader and one `looks_like_driver_argv`;
  `BaseCLIArgs` gains `apply_handshake` and `parse_driver_handshake`, and
  `apply_str_options` writes a scanned option table onto an args record. The
  nine tools that each carried a private copy (`cd_ripper`,
  `file_reorganizer`, `library_stats`, `spectral_viewer`, `album_art_sync`,
  `duplicate_finder`, `restoration`, `tag_editor`, `tag_field_updater`) now
  delegate. `looks_like_driver_argv` requires a mode flag plus an
  orchestration token, so a bare `--dry` is no longer read as a handshake.
  `tests/test_driver_handshake_contract.py` covers the first-party registry
  exactly, round-trips the real `arg_builder` argv through nine real parsers,
  runs two real `.pyw` launchers, and locks the finding that four builders
  launched no mode flag at all — fixed in the same release: every utility
  builder now emits the mode and the pair, except the ASX Extractor, whose
  argv carries it as the label its own dropdown displays.

- **One format capability matrix.** `audio_suite_shared/audio_formats.py`
  now holds a frozen `FormatCapability` row per container in
  `FORMAT_MATRIX`, and `SUPPORTED_EXTENSIONS`, `READ_ONLY_EXTENSIONS`,
  `LOSSLESS_EXTENSIONS`, `COMPRESSED_EXTENSIONS`, `PYDUB_FORMAT` and
  `_DEPTH_CODECS` are projections of it; the converter's
  `LOSSY_FORMATS`/`LOSSLESS_FORMATS`/`ALL_FORMATS`/
  `UNSUPPORTED_OUTPUT_FORMATS`/`OUTPUT_EXTENSIONS` derive from the same
  table through `CODEC_TO_EXTENSION`. ALAC is classified by
  `LOSSLESS_CODECS`, because it is a lossless codec in a lossy-capable
  container.

- **A release cut now tags the version and publishes its GitHub release page.**
  `utilities/release.py` re-run on a clean tree whose `HEAD` declares the
  version creates the annotated tag, pushes it and creates the release from the
  `CHANGELOG.md` section; `--backfill-releases` publishes the tags that already
  exist, `--no-publish` opts out and `--offline` stops at the local tag. 2.3.1
  shipped with no tag at all, and no release in this repository had ever had a
  Releases-page entry, because that step lived only in the release checklist.
  The process is also described in the docs site for the first time - nothing
  under `documentation/` had ever mentioned it.

### Changed

- **Broad catches are a triaged baseline.** Ruff's `BLE` rules are enabled, with
  test trees the only `per-file-ignores` exemption. The rule flagged 55
  production handlers that swallowed a failure with no traceback anywhere: five
  now name the exceptions their call actually raises (`source_bit_depth` in
  `audio_formats`, the mutagen source read in `audio_normalizer`, the stream
  info read in `duplicate_finder`, the AccurateRip payload parse, and the
  run-mode preference save) and the other fifty name the boundary they are.
  `tests/test_ble_baseline.py` fails if the rule is unselected, if an exemption
  ever matches a production path, or if an annotation loses its reason. Three
  fault-injection locks prove outcomes rather than handler shape: a failed
  in-place write is that file's error and the batch continues, a refused tag
  write leaves no undo snapshot, and a narrowed tuple no longer swallows an
  unexpected exception.

- **The tag-handler factory is a leaf module.** `TagHandlerFactory`
  moved out of `tag_helper_base` into
  `audio_suite_shared/tag_handler_factory.py`, which imports its six
  handler modules inside the builder that fills the table;
  `tag_helper_base` resolves the factory and the handler classes through a
  module-level `__getattr__` (PEP 562), so the cycle that made a handler
  module an invalid *first* import is gone. `tests/test_import_isolation.py`
  imports each handler module first in a fresh interpreter subprocess and
  asserts the factory alone loads no handler module; both fail on the old
  layout (the handler case dies with `ImportError: cannot import name
  'MP3Handler' from partially initialized module`).

- **The per-file change-note lock is re-baselined to the 2.4.1 window.**
  `tests/test_release_notes.py` pins `BASE_COMMIT` to `c124142` - the 2.4.0
  release commit the `v2.4.0` tag points at - and `NOTE_MARKER` to
  `Changed in 2.4.1`, following the per-release procedure its own
  docstring records, so 2.4.0's notes remain as each file's history.

- **One DSP model behind the enhancement presets.** `audio_enhancer/core/models.py`
  is now a re-export of `audio_suite_shared/dsp_models.py` instead of a second
  definition: the two copies had drifted on the class default (`output_gain_db`
  0.0 against 4.0) and on the enum base. `PresetName` is a `StrEnum` - the only
  base whose f-string, `str()`, `format()` and `json.dumps()` all render the label on
  3.11-3.14 - and `preset_text()` is the single display accessor, used by both
  preset combos, so an enum-base change cannot rewrite a label again.

- **The preset model is locked by measured audio, not field read-back.**
  `audio_enhancer/tests/test_models.py` asserts `PRESETS is` the shared table,
  compares every preset field by field, and measures the Moderate preset's
  declared 4.0 dB gain from a decoded WAV (a 0.0 dB twin differs by a measured
  4.000 dB); 22 rendering/default locks join
  `audio_suite_shared/tests/test_dsp_models.py`.

### Removed

- **Dead code removed and the last slot-var clone retired.** WP-3 deletes
  `noise_reduction/ui/setup_tab.py` (173 lines no shipped module imported
  once the tool became a Refinery stage), the root `Tag_Field_Updater.py`
  legacy shim (no `[project.scripts]` entry, no test, and only the `.pyw`
  launcher is documented), and `JobStatus`/`AudioFileInfo`/
  `ProcessingResult` from `audio_enhancer/core/models.py` (zero importers
  once the enhancer became a stage). Both remaining local
  `_ThreadSafeSlotVar` clones are retired behind `make_safe_slot_vars`.
  `tests/test_ui_module_usage.py` is the new lock: it resolves every
  import in every shipped `.py` and `.pyw` module, so a `*/ui/` module
  nothing imports fails instead of sitting dead.

### Fixed

- **`get_export_args` raises instead of writing MP3.** The MP3 fallback for
  an unknown or read-only extension encoded the source stream as MP3 into a
  file named for another container. It now raises `AudioFormatError`, and
  `audio_suite_shared/tests/test_audio_formats.py` holds the refusal, a
  measured round trip for every writable row (`ffprobe` reads the codec
  back), and the ``tag_writable``/factory agreement.

## [2.4.0] - 2026-11-02

### Added

- **`send2trash` is a declared runtime dependency.** Delete and ASX-stub route
  every removal through `duplicate_finder/core/trash.py`; the seam has no
  `unlink` fallback, and a missing backend refuses the run before fingerprinting
  starts.
- **The ASX stub schema lives in `audio_suite_shared/asx_stub.py`.** One
  versioned implementation writes and reads the nine canonical fields, MBIDs,
  ISRCs, base64 lyrics and JPEG artwork; a literal XML fixture pins the writer's
  element order, and the reader rejects an unknown version instead of guessing.

### Changed

- **The completion contract for Duplicate Finder gained `deleted` and
  `stubbed`.** `tests/test_completion_seam.py`, the publisher lock, the CLI
  schema corpus (`tests/data/cli_payloads.json`, `audio_suite_shared/
  cli_schema.json`), the driver argument expectations and the AppState/UI-card
  locks move with the CLI surface.
- **The ASX extractor's parser and restore path carry their own regression
  tests.** `asx_extractor/tests/test_file_ops.py` measures the recreated audio,
  name and tags on disk, exercises the tag-write failure and missing-keeper
  paths, and covers recursive discovery.
- **`tests/test_release_notes.py` is re-baselined to the 2.4.0 window.**
  `BASE_COMMIT` is `a9afe78` and `NOTE_MARKER` is `Changed in 2.4.0`.

## [2.3.1] - 2026-11-02

### Changed

- **The POSIX leg's test floor is re-measured at 1740 passed / 1 skipped.** The
  five retired DSP tools removed the per-subcommand cases the CLI-surface
  parametrisations generated, so `posix-smoke` refused its first run on the 2.3.1
  cut at the old 1756 floor with 1740 passing and nothing failing; the lock now
  holds the leg's own numbers (`PLAN_restoration_2026-10-31.md` D20).
- **The five retired tools are gone from the documentation too, not only from the
  code.** The manifest registers 27 first-party tools, so the CLI reference lost
  their five sections and five *All Commands* rows, the new-user deck lost their
  two slides, five format rows, three chooser rows and four pipeline labels (and
  was regenerated: 24 slides), and README, docs index and suite overview now say
  27 tools and 15 UTIL. `AGENTS.md`'s completion-seam citation points at
  `audio_refinery`, and the stale guide artefacts are deleted from the index so
  the locks that walk `git ls-files` see the tree.
- **The same pass fixed two reference errors the dead sections had masked.**
  `refine`'s `--target-lufs` claimed `-16.0` against click's `-14.0`, and
  `--true-peak`, `--lra` and `--normalise-mode` - the Audio Normalizer's controls
  REFINE absorbed - were documented nowhere. `test_cli_reference_hygiene`'s
  vacuity floors now follow the measured 27-tool surface (33 commands, 31
  sections, 29 families, 103 default claims, 159 options), so they still fail on
  a parser break or a gutted document.
- **A tool can ship without a Master Driver card, and the driver's own launch
  gate is now the tab's population.** `ToolManifest` gains `driver_card`
  (default `True`) and `is_driver_tool` requires it, so `driver_manifests`,
  `driver_by_category`, the generated toggles and the arg builder all drop a
  tool the driver does not offer. Setting it `False` on the five DSP tools
  retired under U-03 exposed a real defect: `launch_utility` classified against
  `by_category("utility")` and read `module_toggles[m.id]` for every manifest,
  which raised `KeyError` for any tool without a toggle - it now reads
  `driver_by_category`. The same population change moved
  `_BuildUtilityArgs`' graph-coverage lock, `TestUtilSelectAll` and the
  Utilities-window grid tests onto the driver's population rather than the
  registry's, and `test_tool_plugin.py` gained a lock that the driver names no
  retired id in its own source while the tool keeps its launcher, command and
  package.

- **The recorded CLI failure example no longer pins the installed Click's
  wording.** A fatal document's `error` is `ClickException.format_message()`, so
  `TestFatalErrorExamples` was comparing Click's sentence rather than the
  contract - and it went red in both directions as the floating
  `click>=8.0.0` moved (`PLAN_feature_expansion.md` D10,
  `PLAN_restoration_2026-10-31.md` D15/D16). The document is now compared field
  by field with only the reason excluded, and the reason is still checked for
  presence and for naming the value the run rejected. Two guards keep the
  exclusion honest: one asserts no other field is dropped and that a drifted
  counter still fails, the other patches Click to a wording no release prints
  and asserts the comparison still holds - both fail with the exclusion removed.

- **Theme conformance is now checked against the colour the display paints, not
  the constant the code passed.** `test_ui_cards.py`'s contrast lock builds the
  BPM Analyzer and Lyrics Manager cards in four theme states (System patched
  through `styles._get_system_theme`, never `os.name`) and asserts ≥ 4.5:1 for
  every text-bearing widget's effective pair; `test_ui_driver_controls.py` does
  the same for `DriverControlsPanel` in its driven state, including the
  `TCombobox` disabled style entries, and adds the symbolic-colour check that no
  locked surface is still `SystemButtonFace`/`SystemDisabledText`. Both were
  written before their fixes and failed against them (1.26:1; 2.04:1 and
  1.13:1), so neither can pass vacuously.

- **A documentation-only push no longer runs the full suite.** A new `changes`
  job classifies the pushed change set and the floor leg is gated on its answer,
  so a commit that touches only Markdown or the `documentation/` tree runs the
  seven cheap jobs - Docs locks included, because a guide commit is exactly when
  a stale artefact needs catching - and skips the ~61 billable minutes the suite
  costs. Any code, test, configuration, workflow or fixture path runs it, and so
  does a range git cannot diff or a classifier that fails. The 2.3.0 record
  commit `d753c6e`, six lines of a PLAN file, billed 30 m 56 s before this;
  `tests/test_ci_changed_paths.py` holds the rule and the gate.

### Fixed

- **The published CLI failure example matches the click version in use again.**
  `tests/test_cli_json_schema.py::TestFatalErrorExamples` compares a real failing
  run against the schema's published example, and the committed corpus carried
  click 8.5's `No such option '--no-such-option'.` while the suite installs click
  8.3.2, which writes `No such option: --no-such-option` - so the `doctor` case
  was red. The three occurrences in `tests/data/cli_payloads.json` and
  `audio_suite_shared/cli_schema.json` were corrected from the recorder's own
  output; `--record` was run first but also rewrites every payload's duration,
  `_generated`, and doctor's `editable`/`interpreter` fields, which describe the
  recording host rather than the contract (the same call
  `PLAN_feature_expansion.md` D10 made for these files). `click>=8.0.0` is
  floating, so the example tracks the installed version.

- **The user-guide freshness lock no longer fails on a month boundary.**
  `version: auto` renders `Version <declared> - <Month YYYY>` from
  `date.today()`, so the generation month is ambient rather than derived from the
  Markdown source - and `check_guide()` compared `word/document.xml` verbatim,
  which reported all seven such guides stale on 2026-11-01 with no unrendered
  edit in the tree (`--check` and
  `test_user_guide_hygiene.py::test_artefacts_match_their_sources` both red).
  `stable_document_xml()` masks the month on both sides before comparing and
  keeps the version number, so a real bump or a body-text edit still fails;
  `test_a_month_boundary_is_not_guide_drift` renders under a future month and
  asserts the current artefact passes, with an edited copy as the counter-case.
  No artefact changed: the seven committed October guides are current again.

- **Theme conformance is locked by a static walk and a four-state build.**
  `tests/test_theme_contrast.py` adds both halves. The AST pass asserts every
  first-party widget constructor that sets a themed `bg` also states the
  foreground, the `selectcolor` (toggles) and the `disabledforeground`
  (anything built `state="disabled"`) for a state it can be seen in, with the
  scanned-file set, the inspected-constructor count and a deliberately broken
  snippet all asserted so the scan cannot pass vacuously; the runtime pass
  builds the real `AudioSuiteDriver` window and the shared `BaseSetupFrame`
  in Light, Dark, System->Light and System->Dark and measures every text
  widget's effective pair through `winfo_rgb()`. What they locked is 48
  constructors in 27 files: ten buttons built `state="disabled"` with no
  disabled foreground, five toggles with no `selectcolor`, two labels, and 31
  toggles with no `activeforeground`. `styles.text_colors(kind,
  background=...)` is the new contract helper - one call per widget family
  returning only the keys that family accepts - and call sites write its keys
  out explicitly, because bare `mypy` rejects a `**dict` spread into a tk
  widget with eleven `arg-type` errors per call. The runtime half also
  surfaced three pre-existing contrast defects, fixed with it:
  `SETTINGS_TAB_INACTIVE` #888888 -> #666666 (3.54:1 -> 5.74:1 under white),
  `styles.AMBER` made theme-refreshed (#9a4a08 light / #d97706 dark, 3.19:1 ->
  6.2:1 on the light card) and the settings footer note moved from a hardcoded
  #999999 (2.50:1) to `FG_SUB`.

- **Two test modules regained the imports their surviving helpers use.** The
  standalone batch processor's removal (U-04) took `MagicMock` and `Queue`
  (and, in the silence trimmer's suite, `threading`) with it while helpers
  stayed behind, which left `ruff check` red on the working tree. The
  normalizer suite imports them again; the trimmer's suite drops the orphaned
  `_make_slot_deps` helper instead, so no dead scaffold remains.

## [2.3.0] - 2026-10-31

### Changed

- **The two new tools are locked by measurement, not by shape.**
  `duplicate_finder/tests` drives the real `fpcalc` path over a declared fixture
  set and asserts the recorded distances (0.0000–0.0002 inside one recording,
  0.1580 for the nearest pair that must stay apart) and that quarantine leaves
  the keeper's SHA-256 unchanged; `restoration/tests` decodes the written file
  and measures harmonic distortion and peak against a known-clipped reference
  (25.45 dB improvement, peak within 0.05 of the original), and asserts a clean
  file's bytes and mtime are untouched. 240 tests between them.

- **`duplicates` and `declip` joined the locked CLI schema**
  (`cli_schema.TOOL_IDS`/`EXTRA_TYPES`), so their `--json` payloads are part of
  the suite's contract rather than an ad-hoc dict, and both commands refuse an
  out-of-range option with Click's exit-2 usage message instead of a traceback
  from the settings object.

- **`restoration.core.file_processor` builds a headless slot pool** when no
  window supplies one. The shared in-place workflow takes its worker index from
  a queue and blocks until one is free, so an empty pool hung every caller that
  passed none instead of failing; `_resolve_pool` sizes the pool from the
  processor, and a regression test runs the batch with neither argument.

- **`duplicate_finder`'s status tokens are bracketed constants** (`"[CACHED]"`,
  `"[KEEP]"`, …) interpolated without extra brackets, because the guide-claims
  lock searches the source text for the literal a guide quotes and an f-string
  that adds the brackets itself never matches.

- **The new-user deck takes its tool count from the manifest** (the closing
  slide used a literal "30 tools"), and its format table names both new tools,
  so a new manifest entry cannot leave the deck behind.

- **The generated documentation indexes were regenerated** from the manifest:
  `documentation/docs/index.md` (32 rows) and the README tool index, plus the
  hand-written counts they sit beside in `README.md`, `suite-overview.md` and
  the CLI reference.

## [2.2.1] - 2026-10-30

### Changed

- **The Tag Field Updater runs on the shared analysis/tag scaffold.** Its window
  is an `AnalysisTagToolApp` with `ui/setup_tab.py`, `ui/processing_tab.py` and
  `ui/results_tab.py`, and its scan now starts through
  `tag_field_updater.core.processor.run_scan`, the `run_*` entry point taking
  `on_progress` / `on_complete` / `on_error` that every other GUI tool's
  processor exposes. The window therefore gains the shared progress and
  completion handlers (including Auto End) instead of its own
  `finish_scanning`, and the tool joins `EXPECTED_TOOLS` in
  `tests/test_callback_payload_contract.py`, `EXPECTED_REQUIRED` in
  `tests/test_completion_seam.py` and `EXPECTED_PUBLISHERS` in
  `tests/test_completion_payload_published.py`. The launcher argv is read
  through `read_positional_handshake` (the mode / start / end slots
  `album_genre_tagger` uses) instead of a per-token scan. Behaviour-neutral for
  the audio: no tag rule, format or write path changed.

- **The Tag Editor runs on the shared analysis/tag scaffold.** Its window is an
  `AnalysisTagToolApp` with `ui/setup_tab.py`, `ui/processing_tab.py` and
  `ui/results_tab.py`; the load walk starts through
  `tag_editor.core.processor.run_scan` and every apply through
  `run_apply`, so the window uses the shared progress/completion handlers
  (including Auto End) instead of reading return values and driving widgets
  itself. Both entry points publish the shared counters plus their own fields
  (`rows` for the walk; `results`, `changed` and `written` for an apply), and
  the tool joins `EXPECTED_TOOLS`, `EXPECTED_REQUIRED` and `EXPECTED_PUBLISHERS`
  in the three cross-tool callback locks. The launcher argv is read through
  `read_positional_handshake` at the slots `tag_field_updater` reads, and
  `arg_builder` now emits the mode / start / end triple for this utility so the
  strip's Auto Start and Auto End are not inert. The scan gained a cooperative
  `TagEditorProcessor.stop()`, honoured between files. Behaviour-neutral for the
  audio: `apply_edits`, the undo batch and the tag API are untouched, and the
  apply payload is counted per file so the shared summary keeps its unit.

## [2.2.0] - 2026-10-30

### Changed

- **The release gate reports its progress while it runs.** A cut is normally
  launched from a background shell with its output redirected to a log, where
  Python block-buffers: each step then arrives in 8 KiB bursts, so the 2.1.7
  run read as stuck at 14% for most of its 21 minutes and its `[START]` lines
  surfaced *after* the output they announced. Every progress line is flushed
  now and every gate child runs unbuffered, so the log names the step that is
  running while it runs. Developer tooling only: no analysis, tag write or
  audio output changed.

## [2.1.7] - 2026-10-29

### Fixed

- **Two Refinery tests are gated on a measured capability, not on `CI`.**
  `test_normalise_reaches_target_lufs` and `test_full_chain_all_stages` were
  skipped whenever the `CI` variable was set, with a reason claiming pydub needs
  ffmpeg - a fact nothing checked, so a runner that had ffmpeg skipped them
  anyway. They now skip only when a real pydub FLAC round trip fails, which
  means they execute on a runner that can. Un-skipping them immediately found
  the 192 kHz normalise defect recorded in `CHANGELOG.md` for this release: it
  had been invisible to CI precisely because that test never ran there.

### Changed

- **The documentation has one home: `documentation/`.** The Sphinx site and the
  shipped guides moved under it from `docs/` and `user_guides/`, so "which
  documents does this change touch?" is answered by a directory walk rather than
  a remembered list of roots. The Help button resolves the new location
  internally, so a tool run is unaffected; only a script that named the old
  paths has to be updated.
- `AGENTS.md`'s Bandit rule quoted `exclude_dirs = ["tests"]`; it now quotes the
  real value, `["tests", "packaging"]`, so the rule a reader greps matches
  `pyproject.toml`.

## [2.1.6] - 2026-10-28

### Added

- **A POSIX smoke leg, and a platform caveat that matches it.** Every
  `ubuntu-latest` job until now linted, compiled, scanned or validated
  committed files; none of them executed a tool package, so the platform
  matrix's "Portable core" tier rested entirely on unit tests that simulate a
  platform value. A new `posix-smoke` job installs from `uv.lock`, installs
  ffmpeg, smoke-checks `audiosuite --help` and `audiosuite doctor`, and runs a
  **declared** selection of the suite - the CLI surface plus the shared layer's
  non-GUI modules - on a real Ubuntu host with no display, so a Tk-dependent
  test would skip with an attributable reason and the run states what the
  missing display cost (this selection, measured on a Linux host: 1757
  collected, 1756 passed, 1 skipped - none of them for display reasons). The
  selection is pinned by a lock so a module cannot be dropped from the leg
  silently, and the verdict is non-vacuous: the job must report a passed count
  and stay under a skip ceiling, because a leg that collected nothing would
  otherwise read as green.
  The README no longer cites a "Linux CI leg" that was in fact the ffmpeg
  install, and it now states exactly what the new leg does and does not prove.

### Changed

- **The dependency audit now blocks, with a dated allowlist and a weekly run.**
  The security job's audit had been "on probation for two sprints" since 1.4.1 -
  seven release cuts ago - so a newly published advisory against `uv.lock`, the
  graph users actually install, turned one step orange and shipped anyway. The
  step no longer carries `continue-on-error`, and its verdict is a new
  stdlib-only `utilities/check_dependency_audit.py` rather than pip-audit's exit
  status: pip-audit exits 1 for any finding, which cannot express "accepted
  until a date, with a reason". The checker reads pip-audit's JSON payload and
  the committed `security/pip_audit_allowlist.toml` - empty today, because the
  exported graph audits clean - and fails on an unlisted finding, an expired
  entry, a stale entry, an entry naming a different package, and on any payload
  it cannot judge: a verdict that cannot be computed must never read as a pass.
  No `--ignore-vuln` is passed anywhere, so the allowlist is the only place an
  acceptance can live. A new `dependency-audit.yml` runs the same checker
  weekly and on demand against `main`, so an advisory published between commits
  - or an entry passing its expiry date on a week nobody commits - surfaces
  without one.
- **The lint and type gates now target the interpreter the project declares.**
  Ruff was configured for 3.10 and mypy for 3.12 while `requires-python` promised
  3.11, so `ruff check .` passed only because 3.11's `tomllib` was classified as
  third-party: correcting the target reported 12 mis-sorted import blocks, and
  the type gate certified syntax and standard-library members the oldest
  supported interpreter cannot run. Both now name the 3.11 floor, the
  `typecheck` job installs 3.11, the `lint` job takes Ruff from `uv.lock`
  instead of an unpinned `pip install ruff`, and the one real error the 3.12 pin
  hid is fixed (`ndarray.max()` with no argument has no valid overload under the
  3.11 stubs, in the spectral viewer's peak calculation). A new lock holds the
  three declarations, and the two CI jobs, to the floor.
- **A wedged test now fails the Python 3.14 CI leg instead of hanging it.** The
  first run of the new workflow stopped at 6% for forty minutes and had to be
  cancelled with no output: the tests in that stretch of the collection order
  run subprocesses with no deadline - three nested pytest runs
  (`runpytest_subprocess` defaults to `timeout=None`) and the PowerShell
  staging harness. They now carry timeouts, so a wedged child fails the test
  with its captured output. The test job also declares `timeout-minutes: 60`,
  so a stuck leg fails in the run list rather than holding a runner until
  GitHub's six-hour cap. The suite takes about 25 minutes; a leg still going at
  60 is stuck.
- **The suite now runs once, on the floor, so a push costs 64 minutes instead of
  168.** The `test` job ran the full suite on 3.11, 3.12 and 3.14; measured from
  the jobs' own start and completion times at GitHub's billing multipliers
  (Linux 1x, Windows 2x), those three legs were 160.9 of a run's 168.0 billable
  minutes while every other job cost 7.1 together - which is what exhausted this
  account's monthly Actions minutes mid-session. The matrix is now one leg, on
  3.11: the floor `requires-python` declares, and the only leg whose `uv.lock`
  resolution below 3.12 installs numpy 1.26 / scipy 1.17 / sphinx 9.0.4, i.e.
  the graph nobody develops on. 3.12 keeps running in every Ubuntu job and the
  development host runs 3.14 for the mandatory local gate. The recorded CLI
  payloads and the documentation site moved to that leg with it - their own
  comment already said the files are identical on every interpreter - and a new
  `tests/test_ci_cost.py` prices every job against a 100-minute budget, so
  widening the matrix again is a red suite rather than a bill.

### Fixed

- **A shared-config save could raise where it promised to swallow the failure.**
  `suite_config._save` is best-effort by contract: a failed write is logged and
  the caller carries on. Two sites escaped that promise when the config
  directory is unreadable, a state only POSIX reaches. The stale-temp cleanup
  globbed the directory outside any handler, so a `PermissionError` from the
  glob itself propagated; and the `finally` block probed `tmp.exists()` before
  unlinking, which re-raises `EACCES` because `exists()` only ignores
  `ENOENT`/`ENOTDIR`. `_try_unlink` already swallows every `OSError`, so the
  probe was redundant. The new POSIX smoke leg found both, and the test that
  covers them now has teeth on Linux instead of passing vacuously on Windows.
  Four tests the same leg exposed were Windows-only assumptions rather than
  code defects: a path that is absolute only on Windows, a read-only-file
  cleanup that assumes Windows refuses the unlink, and two launcher tests whose
  Windows-shaped launch read the real `sys.platform` (the module now takes the
  same tests-only `platform` override its interpreter lookup already had).
- **The gate no longer reads the installer's build output as source.**
  `packaging/build` (gitignored, written by `packaging/build_installer.ps1`)
  stages a copy of the app *and* a bundled CPython, and both were treated as
  first-party: five tree-walking locks and mypy read it, so
  `test_e4_dead_code_lock`, `test_undo_gui`, `test_test_file_naming` and
  `test_external_records` died on CPython's deliberately non-UTF-8 `Lib/test`
  corpus (26 failures and errors between them) and mypy aborted on the bundled
  `typing.py`; `bandit -r . -x ./.venv` was worse than red, reporting 3690 HIGH
  findings drawn from that same stdlib. CI checks out a clean tree, so none of it
  was visible there - but a developer who had run the installer could not run the
  documented gate at all. The walks now skip `build`/`dist`, mypy excludes the
  tree, and bandit's `exclude_dirs` names `packaging`; the last of those is
  asserted by what it can match, because each entry is a path substring and
  `build` on its own would silently have deselected `utilities/build_user_guides.py`.
  Side effect worth keeping: skipping the tree takes the security gate from
  minutes to seconds.
- **The whole-tree collection helper can no longer hang the suite, and each
  view runs in its own process.** `tests/_collect_views.py` collected every
  marker view through one in-process `pytest.main`, and it wedged there three
  times: the Python 3.14 CI leg sat at 6% for forty minutes and had to be
  cancelled, a local 3.14 run parked in the same place, and a third occurrence
  - caught by the deadline below - came back with the stack inside pytest's own
  `_do_configure` hook chain. A wedged in-process collection prints nothing at
  all, which is what made it so expensive. Each view now runs in a child
  process (the shape that never wedged) with a `faulthandler` deadline: a child
  that stalls dumps every thread's stack and exits non-zero, so the caller
  reports that view by name instead of holding a runner until GitHub's
  six-hour cap. It costs ~20 seconds of suite time to buy that. An AST lock
  keeps the deadline in place, and the caller's failure message now quotes the
  head of the child's stderr, where `faulthandler` prints the innermost frame.
- **The rate-limiter test measures a spacing the platform clock can see.**
  `test_requests_are_rate_limited_in_time` enforced 20 ms spacing over three
  requests and asserted at least 40 ms, but Windows' `time.monotonic` ticks
  every ~15.6 ms, so a loaded 3.11 runner measured 31 ms and went red while the
  3.12 and 3.14 legs read the same commit as clean. The end-to-end check now
  uses 100 ms spacing with margin, and the limiter's per-call arithmetic - the
  first request not waiting, each later one sleeping the remainder of the
  interval - is pinned by new tests against a clock the test drives, which is
  both deterministic and stronger than the timing assertion it backs.
- **The release-note lock no longer reads a line-ending conversion as a
  change.** It ran `git diff` with `core.autocrlf=false` forced, so on a
  checkout that converts line endings - GitHub's Windows runners do - every
  LF-stored file looked modified. The 3.11 and 3.12 legs therefore reported
  hundreds of files "without a `Changed in 2.1.5` note" that nobody had
  touched, while a 3.14 host read the same commit as clean. The override is
  gone, so the lock sees what `git status` reports on the machine it runs on.
- **Two tests used APIs the 3.11 floor does not have.** The CD Ripper's
  failed-open test called `os.listdrives()` (3.12+) and now probes drive
  letters with `os.path.exists`; the `os.name` trap lock accepts 3.11's louder
  outcome, where patching `os.name` raises `NotImplementedError` instead of
  building the hybrid `PosixPath` that 3.12+ builds.
- **The reference-and-deck coverage lock now runs in the quick documentation
  job.** `tests/test_suite_docs_tool_coverage.py` was not in the `docs-locks`
  CI job, so its failures surfaced only 15-20 minutes into the three-interpreter
  suite matrix. It joins the job's list, and the classification walk that keeps
  that list honest recognises its name family (`test_suite_docs*`) - the file
  was previously invisible to the walk, which is exactly how a document lock
  could sit outside the job while every listed module passed.
- **The coverage lock no longer reads the generated documentation build as
  shipped prose.** It walked `docs/` on disk, so once
  `utilities/build_docs_site.py` had staged its copies of the root documents
  under `docs/_build/` - the historical `CHANGELOG.md` among them - the lock
  reported that changelog's frozen counts ("26 separate windows", "27
  registered tools") as stale and went red against files the author had not
  touched, for anyone who had run the documented build step. The walk now
  follows tracked documents. A regression test plants an untracked file where
  the build puts them and asserts the walk ignores it.

## [2.1.5] - 2026-10-27

### Fixed

- **The reference's flag lock reads every flag a bullet names, not just the
  first.** A bullet documenting both halves of a toggle (`--dry` / `--live`) or
  a short and long form (`-o, --output`) was validated only against the flag it
  opened with, so a renamed or invented second flag passed the gate. The lock
  now checks every backticked flag in a bullet and every bracketed flag in a
  usage line against the owning command's click params, naming the line, the
  command and the flags it does accept when one does not exist.
- **Every documented default in the reference is checked against click, not
  only `--dry`/`--live` and `--stages`.** Those two were the claims that had
  bitten before, so they were the only ones locked while 120 others went
  unchecked: `--threshold` could say `0.5` with click defaulting to `0.6`, or
  `--purge` could claim `no-purge` and the gate stayed green. The lock now reads
  each `(default: …)` claim from the bullet, resolves the owning option, and
  compares - numbers numerically (`-16` against `-16.0`, `60` against the `'60'`
  a `Choice` stores), choice names as text, and a switch's prose by its
  polarity, taken from the option's own flags (`--fade`/`--no-fade`,
  `--delete-originals`/`--keep-originals`), so naming the wrong side fails. A
  phrase the lock cannot read fails too, naming the phrase and the real default,
  rather than being skipped. `--scheme`'s `(default: Italian)` is compared with
  the Tempo Analyzer's own `DEFAULT_SCHEME`, because click stores `None` there.
  The four bullets under *Options every command accepts* (a pre-command option
  included) are checked against every command that defines the flag, and any
  command that disagrees fails the run.
- **A command option the reference never documents now fails the gate.** Every
  check ran document-to-code, so a flag added to a click command and never
  written down kept the suite green - the shape that had shipped
  `--no-write-mbids` on `audiosuite fingerprint`, named by no bullet and absent
  from its usage grammar, so a reader could not learn the switch existed. The
  lock now walks every first-party command's click params and requires each flag
  (both halves of every switch pair included) to be named by that command's own
  section: in a bullet or in the fenced block that shows its grammar. Shared
  flags are exempt because *Options every command accepts* documents them once
  for the whole suite, the root group's own options must appear there, and
  plugin-provided commands are excluded because their contract lives in
  `docs/plugins.md`. The fingerprinter's syntax block gained the missing
  `[--write-mbids/--no-write-mbids]` pair.
- **A command documented only inside another tool's section now fails the
  gate.** Every command check asked whether its *flags* were documented, so a
  grammar block pasted into another tool's section satisfied it, and a command
  accepting only the shared flags was fully covered by *Options every command
  accepts* while having no section at all. A lock now reads which tool each
  section documents and requires every first-party command - a group's
  sub-commands counted under their group - to own a section that documents
  nothing else; the failure names the command and the section it is buried in.
  Command presence therefore has one owner: the option lock checks the flags of
  commands the reference documents and leaves "is it documented at all" here.
- **A section headed with the wrong tool's name now fails the gate.** One lock
  required each tool's name to appear in *some* heading, another required each
  command to own a section, but nothing paired the two: two sections could trade
  headings - every flag still documented, every command still owning a section -
  and the reference named one tool above another tool's grammar. A lock now ties
  each section's heading to what that section documents, reading the expected
  name from the tool manifest itself (`scrub` → `Metadata Scrubber`), so a
  heading copied from a sibling section, a near-miss such as `CD Rippers`, or a
  name the manifest no longer uses all fail; a compound heading that opens with
  the right name but also names a second tool fails naming it. A command with no
  manifest of its own - `doctor`, `plugins`, the three `cue` sub-commands - is
  checked against its own command name, which is what stops `cue split`'s
  section from being titled `cue parse`.
- **A tool documented under the wrong stage now fails the gate.** The reference
  files each tool's section into a stage group (`## ENRICH commands`,
  `## REFINERY command`, `## UTIL commands`) and the manifest gives every tool a
  `category`, but nothing compared the two, so a section moved into the wrong
  group - or a tool whose category changed in the manifest - stayed green. A
  lock now requires each tool's section to sit inside a stage whose heading names
  that tool's own category; `UTIL` is accepted for `utility` because either word
  may truncate the other, so the check needs no hand-listed alias table. A
  category split across two stage groups, and a tool section above every stage
  group, fail as well, while a group holding no manifest tool (`## Suite
  commands`, `## CUE sheet commands`) is left alone.

## [2.1.1] - 2026-10-24

### Changed

- **Every user guide is rendered from one shared Markdown source.** Each of the
  31 guides now has a `.md` source beside its `.docx`, rendered by
  `utilities/build_user_guides.py`, so the prose is reviewable as text and the
  Word file cannot drift from it. `--check` compares zip-entry data to prove
  every artifact is what the renderer produces today.
- **The reference is one Sphinx site built from Markdown pages.** `docs/` now
  holds the front door, the API reference generated from `audio_suite_shared`'s
  docstrings, the plugin guide, the resilience and user pages, all Markdown
  rendered by MyST from the configuration the build gate reads. A shared module
  the API page does not render fails the suite.
- **The documentation artifact no longer ships `AGENTS.md`.** The copy existed
  only because `docs/index.md` linked the repository's instruction file, and
  that link is gone: the artifact now carries what its pages reference and
  nothing else. The file is guidance for people working in the checkout, not an
  end-user document, and the zip is handed to whoever opens it. A lock fails if
  it returns to the staging list or the publish root.
- **The document locks run before the test matrix, not inside it.** A
  `docs-locks` CI job runs the seven modules whose subject is a committed
  document in a couple of minutes, so a stale guide, an unclassified binary, a
  reintroduced prose format or a hand-edited table fails early instead of
  fifteen minutes into a three-interpreter run. A lock keeps the job's file list
  honest in both directions.

### Removed

- **The documentation duplicates with no owner.** `AudioSuite_Message_Guide.docx`,
  `suite_overview/TECHNICAL_USER_GUIDE.docx` and
  `suite_overview/AudioSuite-Pro_Overview_Guide.docx` are gone; their subjects
  became `docs/user/messages.md`, `docs/resilience.md` and
  `docs/user/suite-overview.md`, each written from the code and locked against
  it rather than copied, because each file described behaviour the code does not
  have. The 31 per-tool `generate_guide.py` scripts and
  `docs/requirements.txt` went with them, and the last `.rst` page became
  Markdown.

### Fixed

- **The CLI's recorded usage-error examples match what the locked Click
  prints.** Click 8.5 says `No such option '--x'.` where the committed payload
  corpus and the published schema examples still said `No such option: --x`, so
  the test that compares a real run against the published example failed. Both
  files now carry the message the CLI actually emits.
- **The stem-separator fatal-run test exercises the branch it names.** It
  patched `file_processor.run_stem_separation` while `app.py` binds the function
  by name at import, so the real processor ran against an empty folder, returned
  normally, and the test asserted an error path nothing had entered. It now
  patches the name `app.py` reads, which also proves the handler is marshalled
  to the Tk thread rather than called from the worker.
- **The licence lock no longer depends on the checkout's line endings.** It
  hashed the bytes on disk, and `LICENSE` has no `.gitattributes` entry, so this
  host's CRLF copy passed while a clone that keeps the stored LF — every Linux
  CI leg — failed the same unedited licence with the message reserved for a
  corrupted file. The digest is now taken over the text with LF endings, the
  form the repository stores, and a bare carriage return, which no line-ending
  conversion produces, still fails.

## [2.0.0] - 2026-10-23

### Added

- **The BPM regression corpus now contains the slow ambient pulse it was
  missing.** The suite's "ambient with a slow pulse" evidence was a 92 BPM
  track, because no verified CC0 recording at 50-60 BPM had been found. One has
  now been sourced: a 60 BPM drone by John Bartmann, whose pulse holds for its
  first two minutes (score 0.746 at 60 BPM against 0.423 at 120, so the slow
  pulse is the musical one). It is also the corpus's only recording whose tempo
  falls below the default 75 BPM floor, and it is the regression evidence for
  the slow-tempo fix recorded in `CHANGELOG.md` for this release: the clip stays
  60 BPM instead of being doubled to 120.
- **The API reference now documents every shared module, and building it is a
  test.** `docs/api.rst` covered 11 of the 62 modules in `audio_suite_shared`,
  so the log handlers, the tag-helper tiers and the Tk helpers that a tool
  author actually imports were undocumented, and 51 modules were never parsed
  by a docs build at all. All 61 modules are rendered now, in 14 sections, and
  `tests/test_api_reference.py` fails when a module ships without an entry or
  when the page lists one that no longer exists. A second test builds the page
  with Sphinx and fails on any parser warning, which it immediately used to
  catch four malformed docstrings and an ambiguous cross-reference; Sphinx is
  therefore part of the `dev` extras now.

### Changed

- **The ML suite's real-model paths are opt-in tests, and CI does not install
  the extra.** `ml` is absent from CI, so the default run deselects the new
  `real_ml` marker alongside `hardware`; a real model run is `pytest -m
  real_ml` on a machine with the extra.
- **The real-music BPM corpus can no longer be made green by relaxing its own
  calibration.** The suite promises that real recordings clear the noise floor
  by 1.2x, and its hardest clip (a rubato nocturne) now has only 0.024 of
  absolute headroom — the obvious fix for a red corpus after a dependency
  upgrade is to lower the floor or the promise, which would quietly accept the
  fabricated tempos the gate exists to reject. Both numbers are now pinned: a
  test fails if either is edited and names the re-derivation procedure instead.
  A second test requires the corpus to keep a clip near the boundary, so
  dropping the hard recording cannot leave a green suite that no longer tests
  the promise.

## [1.4.1] - 2026-10-21

### Added

- **The BPM calibration corpus covers free-time, ambient, rubato and shuffle
  material.** Five more CC0 excerpts join the seven already committed, and the
  corpus's `ATTRIBUTION.md` table is now the tests' source of truth: a clip
  cannot exist without provenance and an annotated pulse, and two recordings
  the gate correctly refuses (a free-jazz passage with no sustained pulse and a
  beatless ambient piece) are recorded as `refused` rows instead of being
  deleted. Re-measuring moved the weakest accepted clip from 1.54x to 1.24x the
  onset-periodicity floor, which is the honest margin for rubato playing; the
  floor itself did not move.
- **The shared package's API reference is generated from its docstrings.**
  Every public module, class and function in `audio_suite_shared` now carries a
  docstring, audited by `utilities/docstring_report.py` and locked by
  `tests/test_docstring_coverage.py` (which also proves the audit can fail).
  `docs/` renders that surface with Sphinx for tool authors who import the
  package, and the requirements stay out of the `dev` extra so the test suite
  does not need a docs toolchain.

## [1.4.0] - 2026-10-19

### Changed

- **A new GUI tool cannot omit the typed-worker cap.** The slot-grid lock
  now finds every GUI that creates a worker-named Tk variable and requires
  the shared cap — on the main thread and before the workers setting is
  saved — so registering a tool covers it without editing the test. A worker
  field created in a UI submodule instead of the entry module is rejected, so
  it cannot escape the scan.
- **Every worker cap call now declares whether the launch is unattended.**
  The slot-grid lock requires `unattended=` on each `cap_typed_workers`
  call, so a new GUI tool cannot reintroduce a dialog that blocks a
  driver-launched batch.
- **Batch conversion stays per-file after measurement.** One FFmpeg process
  with many inputs/outputs was measured against the converter's existing
  per-file workers: 0.14 s versus 0.13 s for 8 × 20 s WAV→FLAC, and a single
  corrupt input produced 0/6 outputs instead of 5/6. Batching would have
  traded error isolation, retries and per-file undo for no speed gain, so the
  converter keeps its per-file path.

## [1.2.0] - 2026-10-17

### Added

- **Instruction locks now cover files this repository cannot version.** The
  precedence verdict `AGENTS.md` defers to lives in a user-global instruction
  file that is not in this repository, so a CI runner had no copy of it and the
  in-repo half of that contract could not be checked there. Committed *records*
  under `tests/data/external/` (one JSON per external file) now capture what the
  repository asserts about such a file — its path template, its twin, the
  provenance of the recorded bytes, and the headings and markers the claims
  rest on — and `tests/external_records.py` materializes a baseline fixture from
  the record, so the live-file checks (headings, verdict markers, the
  hardlinked twin) run on every host instead of skipping for a missing file.
  The record is the contract: a heading or marker that disappears without a
  deliberate re-record is drift, and a change to the record belongs in review.
  CI runs those locks against an empty home directory and fails if any of them
  skips, so the runner proves the materialized-fixture path itself rather than
  inheriting a developer host's real file. The count of locks each module
  collects is generated from a passing run into `tests/data/lock_counts.json`
  by `python -m tests.lock_counts --write` rather than typed into the workflow,
  and the same file is checked by the suite and the runner, so a lock file
  cannot shrink or double without a deliberate regeneration.

## [1.0.1] - 2026-10-14

Everything below landed after `1.0.0`. The items are grouped Keep-a-Changelog
style and worded against the behaviour actually shipped; the per-item evidence
lives in `PLAN_iteration5_remediation.md` through `PLAN_iteration9_golive.md`
and in `PLAN_bughunt_remediation.md`.

### Changed

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
- **README verification metric reworded.** The "over 452 files" phrasing
  was replaced with non-numeric wording so the statement cannot drift as
  modules are added or removed.

### Fixed

- The portable-core CLI test reads its JSON payload from stdout only, so the
  `audiosuite --json` contract (payload on stdout, diagnostics on stderr) is now
  pinned by the suite.
- **Audio Fingerprinter status strings are now a typed enum, and the tag-write
  step is written once.** The eight per-file outcomes (`ERROR`,
  `LOOKUP SKIPPED`, `ANALYSED`, `NO MATCH`, `MATCHED`, `TAGGED`,
  `TAG WRITE FAILED`, `ALBUM AMBIGUOUS`) are declared once as
  `FingerprintStatus` instead of being retyped as loose literals across the
  display, worker, summary, album-phase and log code, and the duplicated
  "write AcoustID tags → write MBIDs → build the result" tail shared by
  per-file and album matching is now a single helper. **No displayed byte
  changes** — the progress lines, the log file and the CLI summary are
  unchanged, which the existing display-pinning tests and the real-file
  tag-writing tests verify.
- **Dead code removed from `audio_suite_shared/cli_helpers.py`.** The unused
  argparse-based argument-parsing subsystem (source/output paths, stage
  toggles, auto-start) had no production caller; it is deleted along with the
  orphaned type aliases and its tests. Every tool's live CLI handling
  (`UniversalCLIHandler` and the per-tool handlers) is untouched.
- **Noise Reduction and Pop & Click Remover share a common GUI scaffold.**
  `NoisePopToolApp` in `tool_app_base.py` inherits from `UIHelperMixin` and
  `AuditionMixin` and carries the constructor skeleton, the notebook/tab
  layout, preset CRUD, the progress/complete/error plumbing, the CLI
  handshake, and the browse/help/log/folder actions. Each tool's `app.py`
  subclasses it with tool-specific Tk variables, setup controls, validation,
  engine call, CLI flags, and the `RESULTS_LABEL` / `COMPLETION_LABEL`
  class attributes. **No displayed byte or user-visible behaviour change** —
  every pre-existing app test passes unedited through the extraction, and
  the shared-line count between the two `app.py` files dropped from 345 to
  96 (acceptance threshold < 100).
- **`show_message` decomposed** (`audio_suite_shared/ui_common.py`). The
  107-line god function is now three focused helpers (`_build_header`,
  `_build_content`, `_build_action_row`) plus a thin orchestrator. The
  `threading` import is hoisted to module level, the commented-out
  `overrideredirect` line is removed, the "Could not restore dialog geometry"
  log message is corrected to "Could not centre dialog", and the function has
  a full Google-style docstring. **No user-visible behaviour change** — all
  68 existing `show_message` tests pass unedited.
- **Dead `self.style` attribute removed from 16 tool apps and 2 base
  classes.** The `ttk.Style` object returned by `bootstrap_tool_app()` was
  only read by `master_driver/app.py`; all other apps stored it on `self`
  but never read it. The assignment is now `self.error_logger, _ = ...`.

### Removed

- Per-tool `*_Logging_Guide.docx` files and `generate_logging_guide.py`
  (superseded — see *Changed*).
- The tracked `*.bak` guide backups (regenerate from the generator instead).
- The production-dead argparse subsystem in
  `audio_suite_shared/cli_helpers.py` (~300 lines) and its tests — every tool
  parses its live arguments through `UniversalCLIHandler` and the per-tool
  `utils/cli_args.py` modules.
- Dead code confirmed by AST scan and removed (E4 M15): `_ENHANCE_PRESETS`
  (47-line unused preset dict in `audio_refinery/ui/setup_tab.py`),
  `check_integrity_batch` (zero callers in `audio_refinery/core/file_processor.py`),
  `_FingerprintJob.processor` field (the worker re-derives the slot from the
  queue), the legacy str-spec path in `master_driver/runner/module_runner.py`
  (35 lines — no production caller passes str specs), the dead
  `hasattr(self.app, "scheme")` branch in `cli_helpers.py` (`TempoAnalyzerApp`
  uses `tempo_scheme`), and the write-only `_output_dir_final` and `_reset_ui`
  in `music_format_converter/app.py`.

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

- Baseline commit audited on 2026-09-26: 6,978 tests passing / 5 skipped,
  coverage 78.26%, `ruff` clean, `mypy --strict` clean, bandit 0 High /
  0 Medium. That audit is recorded in `PLAN_iteration5_remediation.md`, and
  its findings were remediated across that plan's staged, evidence-recorded
  work, recorded in `CHANGELOG.md` as each item landed.

### Changed

- **All DSP converts at the boundary through one clipping-protected
  normalized-float path** (`audio_suite_shared/audio_conversion.py`), with
  clip-event warnings logged and a post-chain peak warning in the Refinery
  Enhance stage.
- **Suite-wide engineering gates established:** `mypy --strict` clean,
  coverage with `fail_under = 75` enforced, measured golden-vector tests for
  the Key/BPM/Tempo/Mood analyzers, and contract locks on CLI/launcher/
  guide/card registration.

### Removed

- Legacy tool-local config files (`tempo_config.json`,
  `reorganizer_config.json`), consumed by the shared-config migration.
- Six hand-rolled thread-pool batch loops, six duplicate
  `subprocess`/`STARTUPINFO` helpers, and assorted dead constants — all
  consolidated onto the shared `process_batch` /
  `run_secure_subprocess` / `get_startupinfo` scaffolds.
