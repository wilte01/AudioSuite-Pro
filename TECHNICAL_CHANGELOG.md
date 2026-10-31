# Technical changelog

The developer-facing half of AudioSuite-Pro's change history: the release gate,
CI, the tests, tooling, behaviour-neutral refactors and dependency bumps -
changes a user cannot run or observe, and therefore cannot find in
[CHANGELOG.md](CHANGELOG.md).

Both files are promoted in the same cut by `utilities/release.py`. A version
heading that is absent here means that release carried no developer-facing
change, which is why a release with none adds no heading rather than an empty
one.

## [Unreleased]

Nothing yet.

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
