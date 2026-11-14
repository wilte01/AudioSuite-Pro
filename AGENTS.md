# AGENTS.md — AudioSuite-Pro Project Conventions

## Scope & Authority

This file is the repo-local instruction set for AudioSuite-Pro and is
**self-contained for repo-local rules**: every repo-local rule is stated in
full here, so nobody has to find another document to act on it. It is not
self-contained for cross-project rules — the user-global baseline at
`%USERPROFILE%\.config\opencode\AGENTS.md` applies in this repo as it does
everywhere else, and *which file wins on what* is decided in exactly one
place: that file's **Instruction Precedence** rule (its §1). Nothing here
restates or overrides it. Read this file as *rules first*; the evidence behind
a rule lives in the `PLAN_*.md` decision logs, and each rule points there.

- **Legacy `§N` citations.** Older plans and `AUDIT_2026-10-06_suite_report.md`
  cite the *user-global* instruction file by number. It lives at
  `%USERPROFILE%\.config\opencode\AGENTS.md` and is shared by the `opencode` and
  `kilo` harnesses (those two paths are one hardlink, so editing either edits
  both). It is not in this repository and is not versioned with it. Its sections
  are: **`§2` Scope Control**, **`§3` Zero-Assumption & Communication**, **`§4`
  Environment, Security & Dependencies**, **`§5` Code Quality & Standards** (the one
  that owns the SQLite/`auto_vacuum` lesson), **`§6` Verification Tooling Pipeline**
  (`§6.9` owns line endings/encoding; SHA-256-verified restores are also `§6`),
  **`§7` Test-Driven & Continuous Testing**, **`§8` Documentation**, **`§9`
  Troubleshooting & Loop Prevention**. The plans cite `§5` loosely: "§5" for
  SHA-256 restores or for file encoding is mis-numbered (both are `§6`), and the
  global `§7` defect rule is *this* file's "Defects and failing checks" as well —
  where the two differ, that file's **Instruction Precedence** rule (its §1)
  decides. Cite this file by section name from now on, never by number.
- **The `PLAN_*.md` files are the decision record, not instructions.** A plan
  whose items are all COMPLETE/DONE is a *historical record*: add follow-on work
  to it only as a clearly-labelled decision-log/supersession entry (with user
  approval) or as a new plan.

## The Gate — run before marking anything done

Four checks, in this order. Anything short of all four green is not done.

0. **Compile** — `python -m compileall -q -f .`
1. **Lint & format** — `ruff check .` and `ruff format --check .`
2. **Types** — bare `python -m mypy .` (see *Bare `mypy .` is the gate*)
3. **Security** — `bandit -r . -x ./.venv -c pyproject.toml`, expecting
   **0 High / 0 Medium**
4. **Tests** — bare `pytest`, so the configured `testpaths` apply (CI adds
   `--cov-fail-under=75`)

The gate reads code, not prose. User-facing documentation is a separate
precondition of "done": see *User Guides Follow the Change*.

Windows shell note: items 1–3 are usually run in PowerShell. This repository is
also driven from Git Bash, where the equivalents are `ruff check .`,
`python -m mypy .` and
`PYTHONUTF8=1 python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`.
Pick the dialect that matches the shell you are actually in; the *flags* above
are the contract.

### Defects and failing checks

- **Failing tests must be resolved — never shipped.** A red suite is silently
  ignored and masks real regressions. Do not delete, skip, `xfail`, or add
  `# type: ignore` to make a failure go away; fix the cause. If a test or check
  is genuinely wrong, fix it in lockstep with the code and update the gotchas
  here so the mistake is not repeated.
- **Defects are fixed when discovered — never deferred.** A bug found during
  development, review, an audit or a test run is resolved in the same change
  that found it, with a regression test in lockstep. Deferral is acceptable only
  for new-feature backlog items, never for defects in working code. Record it in
  the governing plan's `## Decision Log`.
- **Audio correctness is release-blocking.** Any defect that could corrupt,
  mis-normalize, mis-tag or wrongly convert audio (global-gain rewrites, LUFS
  normalization, sample-rate/bit-depth conversion, analysis, tag writes) is the
  highest-priority fix class. Its test must verify the **actual audio outcome** —
  decode the result and measure per-channel RMS/loudness — never read back the
  same internal state the code just wrote. Self-consistent field read-back cannot
  detect corruption (see the lossless_gain stereo-offset bug, iterations 1–2 in
  `PLAN_audit_remediation.md` and `PLAN_iteration2_remediation.md`).
- **Trace mode flags to the write site.** A mode the app computes and passes
  (`is_dry_run=is_dry_run` into `run_enhancement`) does nothing if any layer of
  the chain lacks the parameter or ignores it — the processor keeps writing and
  an "in-place Dry Run" rewrites the source files. mypy's `Unexpected keyword
  argument` on the call site is the canary. Thread the flag through **every**
  signature and add a regression test asserting the real outcome on a temp file
  (no output file, no write call, no tag copy, DONE with measurements) — not
  merely that the flag arrived.
- **A verification harness that cannot fail is worse than none.** Type array
  arguments `[string[]]` in PowerShell (a `[string]` annotation collapses the
  array and pytest receives a single character); key break-and-restore verdicts
  on a `FAILED`/`ERROR` **test** line, never on the literal word appearing
  anywhere in the output; confirm the summary shows tests actually ran; and
  SHA-256-verify every restore so the harness cannot leave a mutated file behind.
- **A dependency's version can change which branch runs.** Do not pin one
  version's branch message at a consumer boundary. Iteration-5 B1's corrupt-file
  pool test pinned the empty-decode branch's "too short" message at the batch
  level, but `uv.lock` resolves librosa 1.0 on py≥3.12 (which removed the
  audioread fallback), so the same container took the decoder-raised branch and
  the test failed at HEAD. Assert the neutral contract (status=error, non-empty
  message, batch completes) at the consumer, and pin each branch text in the
  loader's own tests.

### The Python floor must honour its lockfile

`requires-python` is only honest if the committed `uv.lock` honours it. When the
floor or a heavy dependency moves, audit the lock's per-interpreter markers: if
the oldest leg resolves older wheels than the interpreter the suite is actually
developed on, raise the floor or accept the split knowingly. `3.10` once let the
lock resolve a second stale numeric stack (numpy 2.2.6 / scipy 1.15.3) behind
`python_full_version < '3.11'` markers while 3.12+ got numpy 2.5.2 / scipy
1.18.0 — and the dev host (3.14.7) had no CI leg at all, so the green 3.10 leg
certified a graph nobody shipped against. 2026-09-28: floor raised to 3.11, CI
matrix `["3.11", "3.12", "3.14"]`, and the 3.10-only pins fell out of the lock by
themselves. 2026-10-28: that matrix cost 160.9 of a 168.0-billable-minute push
and spent the account's monthly Actions minutes mid-session, so the suite now
runs **once, on the floor** - the leg whose resolution below 3.12 is the graph
nobody develops on - and `tests/test_ci_cost.py` prices every job against a
100-minute budget. Since 2.3.0 a **documentation-only** change set (Markdown, or
anything under `documentation/` except Sphinx's `conf.py`) runs the other jobs
and skips that leg: the `changes` job classifies the pushed range and gates it.
Any code, test, config, workflow or fixture path still runs the suite, and any
range the classifier cannot read falls back to running it, so a green docs-only
run proves the locks, not the product.
Never discover this through a broken `tomllib` import two
floors up.

## Repository & Version Control

The tree is a git repository on `main` (initialised in audit P1). Each
remediation item lands as one or more reviewable commits, and the gate runs
against the state after each commit.

- `uv.lock` is committed — it pins the graph CI's `uv sync` consumes. Do not
  re-ignore it.
- `fpcalc.exe` is committed (~4 MB) — the Fingerprinter needs it out of the box.
- Runtime config and API-key files are intentionally gitignored
  (`audio_suite_config.json`/`.key`, `album_art_config.json`/`.key`). Never
  `git add -f` them: a live Fanart.tv key was caught inline during P1, staged,
  then reverted (`PLAN_audit_priority_actions.md` D11).

## Plan Governance

- At session start, state the **governing plan** from the user's instruction; if
  the brief is silent, ask before making plan-anchored commits.
- A mechanism-name grep picks *reference code*, never authority. The governing
  plan is the one that **owns the modules/tools being touched** (four orphan DSP
  tools → `PLAN_audit_priority_actions.md` P6, not the completed
  `PLAN_basesetupframe_refactor.md`).
- Defects found during any session are handled per *Defects and failing checks*
  and recorded in the governing plan's `## Decision Log`.

## Bug-Hunt Triage Discipline

For a batch of unverified leads (e.g. a report's "not independently re-verified"
list) the task is **bounded reproduction, not innocence proof**:

- **Read the candidate's existing tests first.** They encode the intended
  contract (e.g. `library_stats/tests/test_library_cache.py` settles cached-vs-
  full-scan behaviour) and reach a verdict faster than hand-built fixtures. A
  suite that already passes is strong disconfirming evidence.
- **Timebox each candidate to ~15 minutes.** Reproduce once through the real
  entry point; if it does not reproduce after 2–3 representative cases, record
  "no repro under <cases tried>; package tests green" and move on.
- **Write the probe as a file, not a shell one-liner** (`repro_<item>.py`, all
  cases in one script) — shell quoting on Windows silently mangles patterns (see
  *Shell quoting*). Then **delete it**: evidence belongs in the plan's decision
  log, and scratch artefacts (`repro_*.py`, `pytest_*.txt`) must not be committed
  or left in the tree.
- **Record the disconfirming evidence.** Never silently drop a lead — a closed
  non-defect and a fixed defect are both valid outcomes.
- **Read the working sibling before designing the fix.** When the defect is a
  cross-cutting convention — a log button, a progress line, a preset, a status
  string — the failing tool says what is broken and the tool that already does
  it right says what "fixed" means. Diff against that one first. Inventing a
  mechanism from the failing code is how a defect turns into a convention:
  WP-8's View Log was "repaired" by aiming it at the diagnostic log, which
  silenced the complaint and left the run report still unbuilt, until a
  comparison with BPM Analyzer showed the intended shape (D-16 in
  `PLAN_2026-11-03_2.4.3_structure.md`).
- **A fallback that makes the symptom disappear is not a fix.** Making a button
  open *some* file removes the complaint and hides the gap. Ask what the button
  is *for*: View Log exists to show the run's own record, so a path to a
  different file is the defect wearing the fix's clothes.
- **A test that passes on the unfixed tree does not lock the defect.** Run every
  new lock against the pre-fix code before claiming it holds. The first View Log
  test asserted `_log_path == logs/<tool>.log` and passed while the real defect
  (a finished run with no report) was present. Assert the product artefact the
  user opens — a file and its contents — not the internal pointer that may aim
  at the wrong file.

## Test File Naming

New test files live in `<package>/tests/` and are named `test_<module>.py` for the module under test:
`metadata_scrubber/core/scrubber.py` → `metadata_scrubber/tests/test_scrubber.py`. Do not use compound names
(`test_app_audio_detection.py`); put the specific test class inside
`test_app.py`. Do not add a suffix like `_core` unless the source module itself
ends in `_core`.

| Source module | Test file |
|---|---|
| `metadata_scrubber/core/scrubber.py` | `metadata_scrubber/tests/test_scrubber.py` |
| `audio_fingerprinter/core/file_processor.py` | `audio_fingerprinter/tests/test_file_processor.py` |
| `tempo_analyzer/app.py` | `tempo_analyzer/tests/test_app.py` |
| `album_art_sync/utils/cli_args.py` | `album_art_sync/tests/test_cli_args.py` |

**The enforcement is the arbiter, not this table.** `tests/test_test_file_naming.py`
derives the rule from the tree and is the authority on exceptions:

- root `tests/` is **exempt by scope** (its files are cross-cutting by design),
  and so is `utilities/tests` (that package has no `__init__.py`);
- everything else must mirror, *or* appear in that file's frozen `ALLOWLIST` of
  deliberate composites/contract locks (31 entries, length asserted).

So "there is one exception" is wrong: there are two blanket exemptions plus a
frozen allowlist. To add a legitimate exception, add it to `ALLOWLIST` with a
reason — do not widen this section.

## Shared Implementations First

The suite is built from **one implementation of each capability**, and a second
copy is a defect rather than a convenience. Before writing a helper — a
character set, a format list, a subprocess call, an FFmpeg lookup, a config
file, a user-facing message, a path builder — search `audio_suite_shared/` for
the capability. If it is there, import it.

| Capability | The one implementation |
|---|---|
| Filename characters | `audio_suite_shared/security/input_validator.py` — `InputValidator.sanitize_filename`, `validate_filename`; the illegal set is declared once |
| Audio formats and extensions | `audio_formats.py` — `FORMAT_MATRIX`, `SUPPORTED_EXTENSIONS`, `is_supported_format` |
| Running a process | `secure_subprocess.run_secure_subprocess` (locked by `tests/test_subprocess_boundary.py`) |
| FFmpeg and FFprobe binaries | `ffmpeg.py` — `FFMPEG_PATH`, `FFPROBE_PATH`, `find_ffmpeg()`, `require_ffmpeg()`; `search_binary(name)` for any other executable the suite ships |
| A native library the suite ships | `native_library.py` — `load_shipped_library(filename)`; locates through `suite_paths` |
| A launcher's error dialog | `launch_failure.show_error_dialog` |
| Preferences | `suite_config.load_value` / `save_value` (see *Shared Config Pattern*) |
| The installation root | `suite_paths.py` — `suite_root()`, `suite_path()`; a file inside one tool's package is `suite_path("<tool>", "<name>")` |
| A file inside the calling module's own package | `suite_paths.py` — `package_path(__file__, ...)`; never a hand-built `Path(__file__).parent` |
| Decoding for analysis | `analysis_loader.load_analysis_audio` / `check_analysable` |
| User-facing error text | `exceptions.USER_MESSAGES` |
| Logging setup | `app_bootstrap.configure_logging` |
| Undo of a tag batch | `batch_undo` |

Rules:

- **A private copy of a shared set is a bug, not a local variant.** 2.5.0 found
the illegal-filename set written three times — in `InputValidator`, in the Track
Splitter's `naming.py` and in `cue_split.py` — with the shared copy also
stricter than the filesystem; a legal `1-03 Johnny, Don't Do It.mp3` was usable
in one tool and refused in another. The fix is the import, never a fourth copy.
- **If the shared helper lacks the case you need, extend the shared helper** so
every caller gains it; do not fork a near-identical private one. A helper that
lives in a tool package but is used by two tools belongs in
`audio_suite_shared`, and moving it is the fix: `FFMPEG_PATH` lived inside the
Audio Normalizer's package while three other tools imported it from there and
three more re-implemented the lookup, so 2.5.0 moved the resolver to
`audio_suite_shared/ffmpeg.py` (plan D-38) and every tool now imports one
`FFMPEG_PATH`.
- **A tool-specific *subset* is fine only when it is declared as one** — the
Audio Refinery's copy-capable containers are a writable subset of the format
matrix, and the metadata scrubber's per-family extension sets route a file to
the tag block that can hold it. Say so in a comment and list it in the lock.
- **The arbiter is `tests/test_shared_code_reuse.py`.** It fails when a shipped
module declares its own audio-extension list, chooses the FFmpeg binary
itself (a `shutil.which` lookup, or a hand-built path to a binary it ships —
`ffmpeg.exe`, `fpcalc.exe`, `discid.dll`), reads
`sys._MEIPASS` to find a packaged file, builds a Tk root to show a launcher's
error dialog, finds the installation root by matching a directory's name,
derives a path from its own `__file__` instead of `package_path`, climbs from
`__file__` to reach the installation root instead of calling `suite_root`, or
writes `audio_suite_config.json` directly. Existing copies are
frozen in its allowlist **with a reason and a plan entry**; a new copy fails,
and every entry is load-bearing — it must still trip its own rule, or it is dead
weight that pre-approves the next copy (the registry in that file fails a rule
whose allowlist skipped the sweep).
Its sweep reads `*.pyw` as well as `*.py`, because the launchers are the one
kind of shipped code no other gate parses.
Adding an allowlist entry is a deliberate, reviewable decision, not the way to
make a red test green. `tests/test_filename_safety.py` holds the filename set
the same way.

## Shared Config Pattern

Simple key-value preferences **must** live in the shared
`audio_suite_config.json` via `audio_suite_shared.suite_config` —
`suite_config.load_value(key, default)` and `suite_config.save_value(key, value)`. New tools must not
create tool-local JSON files.

The former offenders are migrated: `mood_batch_config.json` and
`tempo_config.json` no longer exist. The migration patterns to copy are
`tempo_analyzer/utils/config.py` and
`mood_analysis_batch_tagger/utils/config.py`.

Tool-local files remain acceptable only for:

- API keys or secrets (`album_art_config.json`),
- complex nested pipeline settings (`refinery_settings.json`),
- domain-specific lists too structured for flat key-value. No shipped file
  needs this today: `metadata_scrubber`'s former `tag_prefs.json` held one flat
  list, so 2.5.0 moved it to the shared key `metadata_scrubber_kept_tags`.

**Resolve key files to one canonical directory.** Key-file code resolves one
canonical directory for the tool, never the calling module's location, and takes
no path argument a caller could vary. `album_art_sync` is the worked example:
`album_art_sync/config/settings.py` owns `CONFIG_DIR` and `config_path()`,
`load_config()` and `save_config()` take no arguments, and both the GUI
(`album_art_sync/app.py`) and the batch pipeline
(`album_art_sync/core/pipeline.py`) call them — before 2.1.3 each passed its own
`__file__`, so the GUI read `album_art_sync/album_art_config.json` while the CLI
read `album_art_sync/core/album_art_config.json` and one source of Fanart.tv keys
was silently empty. A legacy pair at either old location is copied — JSON *and*
its sibling `.key`, because the JSON alone is undecryptable — into the canonical
directory on first load, with the legacy files left in place for manual
recovery. Those files are gitignored, so review cannot see the split: a test
must assert the single path. Evidence: `PLAN_audit_2026-10-24_remediation.md`
B1/D17.

## GUI (Tkinter) Testing

GUI `app.py` modules must be testable without a real display, using
`object.__new__` + `MagicMock`:

```python
app = object.__new__(MyApp)
app.root = MagicMock()
app.some_var = MagicMock()
app.some_var.get.return_value = "expected"
```

Never instantiate `tk.Tk()` in tests except through the session-scoped hidden
root in `conftest.py`.

**A widget's construction-time default is what the user sees whenever its update
path never runs — and every programmatic pre-fill bypasses the widget events
that would have run it.** A `readonly` Combobox seeded in `build()` with
`values = ALL_FORMATS` is narrowed only by the handler bound to the source
widget's `<FocusOut>`/`<Return>`, and none of those fire when the value is set in
Python instead of typed: Master Driver argv (`master_driver/runner/arg_builder.py` passes the
shared directory positionally), a `--flag`-parsed value, or a restored
`suite_config.load_last_directory()`. The tool then launches showing every option
— in `music_format_converter` the mp3-only folder kept `mp3` *and* every lossless
target selectable, and a dry run skipped 10/10 files as same-format. Rule: any
variable written outside a widget edit must route through the **same** update
function the edit handler calls (schedule it, don't duplicate the logic); audit
all pre-fill routes together (Driver argv, CLI flags, restored config); and every
pre-fill route needs a test asserting the **narrowed** state.

## GUI Callback Contract (progress, complete, error)

Every GUI tool starts its processor through a `run_*` entry point that takes
three callbacks: `on_progress`, `on_complete` and `on_error`. The processor owns
each payload and the `app.py` handler mirrors it by hand, so the two drift
independently — and only the gate notices, after the audio work is already done.
Two shipped defects were exactly this: `BPMAnalyzerApp._on_complete` declared
its own keyword list while `run_analysis` grew `skipped_files` (D112), and
`AudioEnhancerApp._on_complete` declared five fields while `run_enhancement`
also publishes `processed`/`skipped` (D113). Each raised `TypeError: … got an
unexpected keyword argument …` *inside the callback*, so a run that had finished
its DSP wrote no report. Evidence: `PLAN_feature_expansion.md` D112, D113.

Rules:

- **Open payloads absorb extras; they never require them.** `on_complete` and
  every `on_*progress` handler declares a catch-all (`**_extra: Any`) *and*
  still declares every field it reads. A field it declares stays *required*:
  a default on one is how a dropped field turns into a plausible zero, and
  `tests/test_completion_seam.py` fails when one appears. The payload varies
  by publisher: the shared runner sends
  `processed/total/skipped/errors/display_text`, the
  in-place DSP runner adds `succeeded`, and tools add `converted`, `updated`,
  `no_genre`, `done`, `result`. A handler bound to one publisher must not raise
  when its tool switches to the other.
- **`on_error` keeps its single `message` parameter.** That seam is closed by
  contract: every tool-side `on_error(...)` call in the tree passes exactly one
  positional message. The parameter is the contract, not wiring noise — do not
  replace it with a catch-all. (The Master Driver's runner callbacks are a
  separate two-argument contract and are not part of this wiring.)
- **Fix the handler, never the publisher.** Removing a field from a payload to
  satisfy one narrow handler breaks every other consumer of that payload.
- **Handlers run off the Tk thread.** Do the file I/O in the handler body, then
  marshal each widget update with `self.root.after(0, ...)`. Never call a widget
  inline from a callback.
- **A raw `threading.Thread` worker must not call `root.after` at all.** The
  rule above is safe only because `on_*` handlers are *invoked* on the Tk
  thread by the runner, so their `root.after` is a same-thread call; a worker
  thread of your own calling `after` (or any widget method) raises
  `RuntimeError: main thread is not in main loop` on 3.14, the thread dies with
  the exception, and the window waits for a result that never comes. Hand the
  result over with a `queue.SimpleQueue` and let a poller the Tk thread started
  (`root.after(_POLL_MS, self._poll)`, re-scheduled on every empty read) collect
  it and do the widget writes. Evidence: `plugins/example_plugin/window.py`,
  `PLAN_feature_expansion.md` D136 — the first version of that window marshalled
  from the worker and hung on a real launch.

`tests/test_callback_payload_contract.py` enforces the rules. It parses (never
imports) every first-party module, resolves each `on_complete=` /
`on_*progress=` / `on_error=` keyword to the handler it reaches — following both
wiring styles (direct binding, and `lambda **kw: self._on_...(..., **kw)`) and
inherited handlers such as `LyricsManagerApp`'s — and checks the rule for that
seam. `EXPECTED_TOOLS` × `EXPECTED_SEAMS` is frozen at 15 tools and three
seams, so a new GUI tool must be registered there deliberately, every tool must
wire all three, and a broken discovery pass fails instead of passing vacuously.
Non-GUI wirings (the Master Driver's `lambda executed:`, CLI wrappers) are not
matched. A required field that goes missing is a `TypeError` naming it, never
a silent default: `tests/test_completion_seam.py` freezes each handler's
required parameters in `EXPECTED_REQUIRED` and asserts that dropping any one
of them raises. Neither lock can prove the processor still *sends* every
field; only a test driving the real `run_*` into the bound handler does, and
it asserts the written outcome — the pattern is
`audio_refinery/tests/test_app.py::TestCompletionSeam`.

## Run Reports vs Program Logs

Every GUI tool writes two logs for two audiences, and the Results tab's **View
Log** opens exactly one of them: the run report.

- **`<scanned folder>/<prefix>_{dry_run,sync}_log.txt` is the run report**, and
  it is what `_log_path` must point at. A tool with no dry/live split uses its
  own run word instead of that pair — the read-only Library Statistics scanner
  writes `library_stats_scan_log.txt`. It records the run the user started:
  `<TOOL> REPORT`, `Mode: DRY RUN` / `LIVE UPDATE`, that run's settings, a
  `=`×60 rule, one line per file (resolved path, `SKIPPED (...)`, error), then
  `SUMMARY:` with the counters and `Time: MM:SS`. The reference implementation
  is BPM Analyzer's `_run_analysis` plus the shared
  `AnalysisAppBase`/`ToolAppBase` `_on_complete`; `file_reorganizer/app.py`
  carries the standalone version (`_begin_run`/`_write_run_log`).
- **`logs/<program>.log` is the diagnostic log** `configure_logging` writes for
  triage. It is never what View Log opens.
- **`_log_path` is empty until a run names its report.** View Log therefore
  answers "No log file available yet" before the first run in a window. That is
  correct behaviour, not a defect — do not "fix" it by pointing the button at
  the diagnostic log (a dry run and a live run write different files, so a
  preview beside the last live run cannot be mistaken for it).
- **A failed report write is logged, never raised.** By the time the report is
  serialised the audio work has already happened.

A tool satisfies the contract in three steps: name `_log_path` when a run starts
(never in a constructor), serialise the report at completion, and prove it with
a test that reads the written file rather than the field the writer just set.
`audio_suite_shared/suite_app.py::SuiteApp` is the window every shell adopter
composes, and `tests/test_suite_app_contract.py` holds each adopter to that
artefact by driving its completion and reading the report back from disk. The
rule exists because WP-8's reorganiser migration dropped the report entirely,
so a finished live copy left the button claiming no log existed (D-16).

## Run From the Project's `.venv`

`uv sync --extra ml` installs into `<root>/.venv`, but a double-clicked
`<Tool>.pyw` runs under whichever interpreter Windows associates with the
extension — the system Python, which has none of the extras. The tool then
cannot see an extra that *is* installed, and the on-demand installer
(`audio_suite_shared.optional_deps`) writes a second copy into the system
interpreter (`sys.executable`).

So **every** top-level `<Tool>.pyw` calls
`audio_suite_shared.venv_bootstrap.ensure_venv_interpreter(root)` with its own
directory, before the pre-flight guard and before any tool import. When
`<root>/.venv` holds an interpreter and this process is not already running from
it, the launcher re-executes itself under that interpreter with the same
arguments. `os.execv` replaces the process, so no parent process lingers and the
window's lifetime is unchanged. No `.venv` (a plain `pip install` into the
system interpreter still works), an already-active venv, a pytest run and a
frozen build are all left alone; a failed `exec` logs and continues in the
current interpreter, so a broken venv surfaces as the normal import error.

Rules:

- Pass the launcher's own directory (`_script_dir`), never `os.getcwd()` — the
  `.venv` belongs to the suite root, whichever folder the icon was clicked from.
- Nothing from a tool package may be imported above the call; it must run before
  the process is replaced.
- This is locked by
  `tests/test_pyw_launchers.py::TestEveryLauncherRunsFromTheProjectVenv` — fix
  the launcher, never the test.

## Startup Pre-Flight Guard (Do Not Disable)

**Every** top-level `<Tool>.pyw` launcher must call
`audio_suite_shared.preflight.guard_or_exit(root: Path) -> bool` **before
importing any tool module**:

```python
import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter
ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("<program_name>")

from <tool>.app import main
```

The guard byte-compiles every first-party source file so a syntax/indentation
error or a missing module in the import chain blocks launch with a clear dialog
instead of an opaque log traceback. `compileall` runs with `force=False`, so
repeat launches are incremental and cheap.

Rules:

- This is **mandatory, not optional** — the "optional guard" wording that once
  appeared in the new-tool checklist was wrong, and 24 of 28 launchers shipped
  without it. It is now locked by
  `tests/test_pyw_launchers.py::TestEveryLauncherRunsThePreflightGuard`.
- Never bypass, weaken, skip, or comment out the guard to "get things working" —
  that is what let broken imports ship previously.
- Keep the guard pure (no Tk side effects) and unit-tested in
  `audio_suite_shared/tests/test_preflight.py`.
- Adding a tool import *above* the guard reintroduces the original bug; the lock
  test asserts the ordering, so this fails loudly rather than silently.


## Launchers Are Linted

The `*.pyw` launchers once sat outside every gate: Ruff's default include is
`*.py`, so a launcher's unsorted imports and blind catches were only ever
reported to a user. `[tool.ruff] extend-include = ["*.pyw"]` now puts every
launcher in front of `ruff check` and `ruff format`.

- **The only exemption is the launch order.**
  `[tool.ruff.lint.per-file-ignores]` relaxes `E402` for `*.pyw` and nothing
  else, because the re-exec, the guard and the logging setup *must* run
  between imports (*Run From the Project's `.venv`*, *Startup Pre-Flight
  Guard*). Every other rule applies, so a new launcher gets sorted imports, a
  final newline and a named boundary for any broad `except`, like any module.
- **Do not hoist the shared imports to satisfy the linter.** Importing
  `app_bootstrap`, or anything that pulls a tool's dependencies, before
  `ensure_venv_interpreter` would run it under the system interpreter the
  launcher exists to escape.
- **Let `ruff format` own the layout.** A launcher left unformatted fails
  `ruff format --check .`; never hand-wrap one to keep a line short.
- **The file set itself is locked.**
  `tests/test_tooling_targets.py::TestRuffReadsEveryLauncher` asks Ruff which
  files it checks (`--show-files`) and fails if any `.pyw` is missing from
  that set, so dropping `extend-include`, or adding a launcher under an
  excluded directory, fails the suite instead of silently unlinting it.

## Byte-level Safety

Two failure classes damage bytes that no content-level gate reports: the compile
gate, ruff, mypy and the suite all stay green while the file on disk is wrong.

- **Scripted edits must pass `encoding="utf-8"` on both read and write.** On
  Windows `open(path)` decodes as cp1252, so an em dash read as `â€”` and
  re-emitted as UTF-8 becomes three *different* characters; it compiled, passed
  ruff/mypy, and broke six display tests that read as logic errors, and the same
  mechanism committed a BEL character into `CHANGELOG.md` (evidence:
  `PLAN_iteration8_remediation.md` E3). After any scripted edit, assert the text
  is control-character clean
  (`[c for c in text if ord(c) < 32 and c not in "\r\n\t"]` is empty) **and**
  preserve each file's existing line endings (`\r\n` vs `\n`) rather than
  normalising them — a line-ending flip turns a 6-line change into a whole-file
  rewrite.
- **`ruff format` must never format Markdown.** `[tool.ruff.format] exclude =
  ["*.md"]` in `pyproject.toml` keeps the completed `PLAN_*.md` records out of the
  project-wide format gate; it must stay a `format.exclude` entry and **not** the
  CLI form `--exclude "*.md"`, because the CLI form *replaces* Ruff's built-in
  exclusions instead of adding to them and re-admits `.venv` (ruff 0.15.22). This
  repo sets no `ruff format` `line-ending` override, so the old "global §5"
  line-ending half is inert here; the `.md` exclusion is not.

## Never Lose a Rule to a Scripted Edit

A bulk edit that moves code between indentation levels produces
**valid-Python-wrong code** and the compile gate cannot catch it: iteration-5
C2's extraction script de-indented the tail of an inherited `process_batch()`
(the `results.append`/progress block slipped out of the `for f in futures:`
loop) and only four pre-existing behaviour tests caught it (a 3-file batch
asserting `len(results) == 1`), and a scripted re-export later landed *inside* an
existing parenthesized `from … import (…)` block (P5). Evidence:
`PLAN_iteration5_remediation.md` C2, `PLAN_audit_priority_actions.md` P5.

After **any** scripted edit: re-diff the touched lines by eye, assert the
resulting set is non-empty, and rely on behaviour-lock tests — never on the
compile gate alone. A scan that reuses an opposite-purpose exclusion set is the
same trap in reverse: iteration-5 G1's walk reused `_EXCLUDED_DIRS` (which
contains `tests`) while needing the exact opposite, so every candidate was
dropped before matching and it would have passed vacuously forever. **Assert the
result set is non-empty so an empty scan fails loudly.** Evidence:
`PLAN_iteration5_remediation.md` G1.

## Domain Correctness Traps

- **Mutagen FLAC: rebinding `.tags` never persists — mutate in place.** mutagen's
  `FLAC` serialises the Vorbis comment dict captured into `metadata_blocks` at
  load time, so `audio.tags = other_tags` followed by `audio.save()` silently
  writes the *stale* block: the incoming tags vanish on disk with no error. The
  classic trap is `delete()` + `save()` to wipe a file, then restoring a
  different loaded tags dict (scrubber undo-restore). OGG/MP4 are unaffected
  (they serialise `self.tags` directly). `VorbisHandler.set_raw_tags` must
  `clear()` + `update()` the handler's own loaded dict, never rebind. Regression
  tests must round-trip through a real FLAC file (pydub export), not fakes, and
  ideally erase the file first.
- **AcoustID near-ties: score rank is NOT decisive within ~0.10 — resolve with
  the file's existing tags.** Distinct recordings built from the same underlying
  audio (an original and a remix/radio edit that reuses the recording) can both
  score 0.95+ against the same fingerprint, and because their durations agree the
  duration guard cannot separate them; AcoustID's own database can rank the
  *wrong* one first, so trusting `recordings[0]` ships a false positive. When the
  score gap is below 0.10, prefer the candidate whose artist/title match the
  file's ID3/Vorbis/MP4 tags (normalise case and punctuation — MusicBrainz
  "Don't" uses a curly quote against the file's ASCII apostrophe). Implemented in
  `audio_fingerprinter.core.acoustid_client.resolve_best_match` (shared
  `read_artist_title`); any future AcoustID tool must apply the same tie-break.
  When no candidate matches the tags, keep rank order and surface the ambiguity
  with the runner-up in the message. Evidence: `PLAN_audit_priority_actions.md`
  P7 §7b, D22.
- **A `str`-mixin enum renders as `Enum.MEMBER` in an f-string**, so a
  "typing-only" enum refactor silently rewrites every display string.
  `class FingerprintStatus(str, Enum)` makes `status == "MATCHED"`,
  `status in {...}` and `json.dumps(status)` behave as the plain string, while
  `f"{status}"` / `str(status)` / `format(status)` produce
  `"FingerprintStatus.MATCHED"` (on 3.14 only `StrEnum` or a `__format__` fix
  restores value formatting). The breakage lives in *interpolation sites*, which
  are usually outside the refactored module: replacing the status literals in
  `audio_fingerprinter/core/file_processor.py` left
  `f"[{result.status}] {result.filename}"` in `app.py` one step from shipping
  `FingerprintStatus.MATCHED` to the UI (evidence:
  `PLAN_iteration8_remediation.md` E3). When a string-valued field becomes an
  enum: (a) grep every interpolation of that field **across the whole package**,
  not just the edited module; (b) route every display through one `.value`-
  returning helper (`models.status_text()`) and serialise dict/JSON payloads
  through it too; (c) keep member values byte-identical to the strings they
  replace and pin the rendered line for **every** member in a test.
- **Logs are split by audience.** A single log file serving both administrator
  failure-triage and per-file processing detail serves neither:
  `logs/audio_suite.log` dominated by DEBUG/INFO makes spot-the-failure
  impossible. Keep the admin suite log to the lifecycle line plus WARNING and
  above, and send each program's full detail to `logs/<program>.log` (unfiltered,
  bounded only by that program's level). Redirect tests away from the shipped log
  with the `AUDIOSUITE_LOG_DIR` env override (session-autouse `conftest.py`
  fixture) and prove isolation **empirically** by the shipped file's
  `LastWriteTime` after the full run — not by trusting the fixture. When a logger
  intentionally gains a second handler, select "the" handler **by filename, never
  by count**: a once-correct `handlers[0]` / `len(handlers) == 1` assertion
  silently targets the wrong file.

- **Degenerate audio is refused by one composed guard, not two optional
  checks.** `audio_suite_shared.analysis_loader.check_analysable()` is the
  single entry point every analysis tool must call after decoding: it applies
  the duration check (`MIN_ANALYSIS_SECONDS`) *and* the silence check
  (`SILENCE_RMS_THRESHOLD`, ~ -60 dBFS global RMS). Calling only
  `check_min_duration` re-admits silence, which beat tracking reports as tempo
  0 (clamped to the floor), chroma correlation turns into a confident key and
  mood heuristics turn into a mood with a confidence score — all fabricated
  values the tools then tag. A tool that decodes through
  `librosa_load_with_fallback` directly (BPM, Key) must call `check_analysable`
  itself; `load_analysis_audio` applies it for callers that use that seam.
  Evidence: `PLAN_feature_expansion.md` D74 (duration half) and D75 (silence
  half). A non-positive tempo estimate is its own outcome, not a low one:
  `NoTempoDetectedError` is reported as a skip (`No tempo detected — the audio
  has no discernible beat.`) and never clamped to the BPM floor (D76). A
  positive estimate needs evidence too: noise is fitted to a tempo grid, so
  BPM reports no tempo unless the onset envelope's harmonic-comb score at that
  period reaches `MIN_ONSET_PERIODICITY` (0.10) — a floor calibrated on the
  committed CC0 real-music corpus (0.154-0.595) with seeded white, pink and
  brown noise at most 0.080 (D77, D79); the skip line and the per-file log
  carry the measured score and the minimum, so a refusal is auditable. The
  CLI's `--json` summary builds `skipped_files` and `error_files` from the
  exceptions' structured context, never by parsing the display sentence, so
  a wording change cannot silently empty a field (D80, D81). When precomputing an
  onset envelope for `beat_track`, aggregate with `np.median` to match its
  internal call; the default mean changes the estimate (a slow pad returned
  107.67 BPM with mean aggregation and 0.0 with median).

- **The analysis grid is part of the calibration, not an implementation
  detail.** `_ONSET_HOP_LENGTH` is a fixed 512 *frames*, so the onset
  envelope's time resolution follows whatever rate the file was decoded at. A
  44.1 kHz album therefore ran on 11.6 ms frames where every calibration clip
  used 23.2 ms, the harmonic-comb score moved with the rate, and two genuine
  tracks were refused as beatless (`No tempo detected — ... (onset periodicity
  0.10, minimum 0.10)`) while six others on the same album were tagged. The
  same defect moved the *reported* tempo, not only the verdict:
  `hiphop_86.ogg` measured 86 BPM at 22 050 Hz and 161 at 44.1 kHz, so the tag
  depended on the container. `detect_bpm` now decodes at the shared
  `ANALYSIS_SAMPLE_RATE` (22 050 Hz), and Key Detector and Mood Analyzer decode
  through the same constant: `load_analysis_audio` defaults to it, and a caller
  that wants a file's native rate asks for `sr=None` explicitly. Key and mood
  were not safe by accident either — on that same album "After Forever" read G
  at 22 050 Hz and Gm at 44.1 kHz, "Into the Void" read C#m against F#, and in
  the corpus `krautrock_152.ogg` read `Playful;Energetic;Hopeful` against
  `Hopeful;Warm;Playful`. So any tool whose threshold was calibrated on
  fixtures at one rate must analyse at that rate or re-calibrate, and a
  regression fixture that changes sample rate must be written from a single
  decode, because a re-encoded copy moves a knife-edge clip by itself.
  Evidence: `PLAN_feature_expansion.md` D137, D138.

- **The analysis window is part of the calibration too - one value, at the
  length the floor was measured.** `MIN_ONSET_PERIODICITY` is a 30 s number:
  the comb tests stationarity, so it loses score as the window grows (two
  library tracks 0.159/0.222 at 20 s, 0.139/0.194 at 30 s, 0.094/0.071 at
  90 s), and a 90 s window refused 10% of a 120-track sample that 30 s
  analyses. Seeded noise peaks at 0.067 over 30 s (0.090 at 20 s), the
  weakest corpus clip is 0.124 and the weakest real library groove 0.120, so
  0.10 keeps a measured margin on both sides at 30 s only.
  `DEFAULT_BPM_ANALYSIS_SECONDS` in `audio_suite_shared.constants` is the one
  value the core default, `BPMArgs`, the CLI, the GUI and the Master Driver
  read; `tests/test_bpm_analysis_duration.py` fails if they diverge.
  Evidence: `PLAN_feature_expansion.md` D139.

- **A refused window is not a refused track — the sampled window is part of the
  measurement.** `detect_bpm` decodes `DEFAULT_BPM_ANALYSIS_SECONDS` from the
  *start* of the file, and on real material that is often an intro: three of 37
  tracks in one album folder scored 0.063-0.098 in the head window while their
  bodies scored 0.466-0.556, so rhythmic tracks were skipped as beatless
  (`[SKIP] ... no discernible beat (onset periodicity 0.080, minimum 0.10)`).
  A file at least `SECOND_WINDOW_MIN_WINDOWS` windows long is measured again
  from the middle, at the same length, and the better-evidenced window decides.
  Key Detector shares the rule and the helpers (`file_duration_seconds`,
  `second_window_offset` in `audio_suite_shared/analysis_loader.py`): a refused
  head window is re-sampled from the middle there too, and because the retry
  runs only behind a refusal it can add a key but never change one (D156).
  The floor does not move: the second sample changes *which* audio is judged,
  not how much evidence is demanded. Two traps. Never lengthen the second
  window — the floor is a 30 s number (D139) — and never re-sample the head at
  another nearby offset, because the intro is precisely what just failed.
  Seeded white/pink/brown noise peaks at 0.056 in the midpoint window against
  the 0.10 floor, so a beatless file that offers a second window is still
  skipped, and a corpus clip shorter than two windows keeps its recorded
  verdict. Evidence: `PLAN_feature_expansion.md` D144.

- **A configured band chooses between octave readings; it never edits a
  measured tempo.** `detect_bpm`'s `min_bpm`/`max_bpm` doubled any estimate
  below the floor and clamped whatever was left outside it, so a genuine 60 BPM
  drone was reported *and tagged* as 120 — the same fabricated-value class as
  the old clamp floor, one release later. The band now folds only when the
  folded level's harmonic-comb score reaches `_FOLD_EVIDENCE_RATIO` (0.75) of
  the level it replaces, and there is no clamp: an out-of-band tempo is returned
  as measured and the per-file line says `(outside 75-175)`. Two traps. "The
  strongest metrical level wins" is **not** a substitute for this rule —
  measured, half-time levels outscore the true tempo on real recordings
  (`hiphop_86` 0.492 at 43 BPM against 0.366 at 86), so that rule walks every
  tempo down an octave; the tracker's own level stays the default and only a
  comparably strong fold may replace it. And a range that differs between entry
  points (the CLI's `--bpm-min 60` against the GUI's 75) silently tags the same
  file two ways, so a range default is one value wherever it is declared.
  Evidence: `PLAN_feature_expansion.md` D108.

## Verification Tooling Traps

- **Bare `mypy .` is the gate.** Per-file invocations (`mypy pkg/x.py
  pkg/tests/test_y.py`) drop `pyproject.toml`'s `[tool.mypy] exclude` context, so
  test files get re-checked with no per-module overrides applied — in practice
  dozens of false `no-untyped-def`/`type-arg` errors on files the bare gate
  passes clean, plus `untyped_calls_exclude` gaps tripping `no-untyped-call`.
  Never "fix" code or add `# type: ignore` to satisfy a per-file run; use
  targeted mypy only for debugging, with the bare run as arbiter.
- **mypy override globs `X.*` do NOT match the bare module `X`.**
  `module = ["mutagen.*"]` covers `mutagen.aiff` but not `from mutagen import
  File`, and `module = ["mutagen.id3.*"]` does not cover `from mutagen.id3 import
  TXXX`. List each bare package/subpackage name alongside the glob.
- **A restrictive `__all__` needs `implicit_reexport = true`.** mutagen ships
  `py.typed` but `mutagen.id3.__all__` lists only
  `['ID3', 'ID3FileType', 'Frames', 'Open', 'delete']`, so every frame class
  (`APIC`, `TXXX`, `TCON`, …) and error (`ID3NoHeaderError`, `MutagenError`,
  `File`) fails `--strict` with "does not explicitly export attribute". Set
  `implicit_reexport = true` in the overrides block (with bare module names per
  the previous rule), then delete the now-stale per-import
  `# type: ignore[attr-defined]` comments that mypy reports as `unused-ignore`.
  This also un-types the symbols, so cascading errors like `"APIC" has no
  attribute "data"` disappear.
- **`# noqa: F401` on a re-export is a ruff-only fix — mypy still fails on the
  importing module.** A `from audio_suite_shared.cli_helpers import
  was_launched_from_driver  # noqa: F401` passes ruff but makes every call site
  fail `--strict` with `Module "…utils.cli_args" does not explicitly export
  attribute "was_launched_from_driver" [attr-defined]`. The redundant-alias form
  is the canonical marker mypy accepts (and ruff treats as a re-export, so no
  `noqa`):

  ```python
  from audio_suite_shared.cli_helpers import (
      was_launched_from_driver as was_launched_from_driver,
  )
  ```

- **mypy numpy `Any`-return trap.** Under `ignore_missing_imports` + the
  `numpy.*` override, numpy ufuncs/`astype`/`tobytes` return `Any`, and returning
  one from a function declared to return an `NDArray` fails `--strict` with
  `no-any-return`. Bind to an explicitly-typed local first:

  ```python
  clipped: npt.NDArray[np.floating[Any]] = np.clip(audio, -1.0, 1.0).astype(
      audio.dtype, copy=True
  )
  return clipped
  ```

- **Bandit needs `-c pyproject.toml`, UTF-8, and `-x ./.venv`.** Plain
  `bandit -r <dirs>` does not auto-load `[tool.bandit]`, so it ignores
  `skips = ["B404", "B101"]` and `exclude_dirs = ["tests", "packaging"]` and
  floods the report
  with hundreds of out-of-scope test-file `assert` (B101) and `/tmp` mock (B108)
  findings, while a bare `bandit -r .` descends into `.venv` and buries the 0/0
  gate. On Windows the report crashes with
  `UnicodeEncodeError: 'charmap' codec` when a path contains `→`, hence
  `-X utf8` with `PYTHONUTF8=1`. A healthy result is 0 High / 0 Medium; the
  remaining Low subprocess findings (B603/B606/B607) are the documented
  first-party call sites routed through `run_secure_subprocess()`, and B404/B101
  are skipped by policy. `bandit -f json` prints a `Working...` progress line on
  stdout ahead of the payload — slice to the first `{` before `json.loads`.
- **Bandit B310 fires on any first-party `urllib.request.urlopen`** and breaks
  the 0-medium gate. Use the already-declared `requests` dependency for HTTP (as
  `album_art_sync`, the acoustid client and the lyrics LRCLIB provider do) rather
  than suppressing with `# nosec`.
- **Bare `pytest` — not `pytest tests/`.** `pytest tests/ -v` runs only the root
  `tests/` directory and silently skips every per-package `<package>/tests/`
  suite, so run bare `pytest` (or the affected packages) and let `testpaths`
  apply.
- **Every new package needs `__init__.py`.** If `<pkg>/tests/__init__.py` exists
  but `<pkg>/__init__.py` is missing, pytest maps the new test modules to the
  top-level package name `tests` (inserting `<pkg>/` on `sys.path`), which
  collides with the repo-root `tests` package: depending on import order you get
  `ModuleNotFoundError: No module named 'tests.<x>'` for either the new package's
  files or the unrelated root ones. Package-scoped runs and the shared/master_driver
  suites all pass green while the bare full-suite run fails at collection — so the
  final gate MUST be a bare full-suite `pytest` run. The same shadowing produces
  mypy "Source file found twice under different module names" collisions; confirm
  the package resolves as a regular package (`__file__` points at
  `<pkg>/__init__.py`, not a namespace path).
- **Pre-flight import checks need a Tk root.** Do not call
  `preflight.guard_or_exit()` bare: its single parameter is a `Path` (the suite
  root to scan), from which it builds the failure dialog. For a non-GUI import
  sanity check use a direct package import (`python -c "import <pkg>.<mod>"`) or
  the compile gate (`python -m compileall -q -f .`).
- **`compileall -x '(^|/)(\.venv|\.git)/'` does not exclude `.venv` on Windows** —
  the `-x` regexp uses forward-slash separators while Windows paths use `\`, so
  the exclusion silently fails and third-party `site-packages` modules get
  byte-compiled (harmless pre-existing `SyntaxWarning`s, e.g. pydub). Keep the
  documented command as-is; the warnings are noise, not failures.
- **A verification harness that cannot fail is worse than none** — see
  *Defects and failing checks*.
- **A same-length edit inside one mtime tick leaves a stale `.pyc`.** P4's
  break-and-restore check rewrote `_CALIBRATED_FLOOR = 0.10` to `0.09` and back
  within the same second. The file's size and mtime were therefore unchanged and
  Python kept loading the mutated bytecode, so the corpus suite failed with
  "MIN_ONSET_PERIODICITY is 0.1, not the calibrated 0.09" against a source file
  that visibly said `0.10`. Clear `__pycache__` (or run `python -B`) after any
  break-and-restore before believing the result.
- **`importlib.reload()` does not undo in-place mutations of module-level
  dicts.** `set_active_palette()` mutates the module-level `PALETTES` dict in
  place, so a test's reload-based "restore" silently did not restore and the pair
  became order-dependent, surfacing only on the *second* full-suite run. Never
  rely on reload to restore state another test mutates in place: capture expected
  state before any test can pollute it, and add a deterministic pollution
  regression when a test mutates module-level globals. Evidence:
  `PLAN_iteration5_remediation.md` Stage 5.
- **A skip is a pass, so it needs a budget.** `pytest` reports `N skipped` as a
  green result, so a test that stops verifying anything — a package missing on
  the runner, an ffmpeg build without a resampler — costs coverage silently:
  the 2.6.0 floor leg carried six `importorskip("setuptools")` skips while
  nothing installed setuptools there, and a green CI certified a wheel nobody
  had inspected. `tests/data/skip_budget.json` records each permitted reason
  with a count and a reason, plus a run total; `conftest.py` fails the session
  on anything outside it, and `tests/skip_budget.py` holds the rule so it is
  tested against fixtures. Add an entry deliberately, with the reason text the
  failure printed — never to turn a red run green.
- **Simulate platforms by patching `sys.platform` only — never `os.name`.** The
  declared platform branches key on `sys.platform`; patching `os.name` instead
  makes `pathlib.Path()` construct a `PosixPath` on a Windows host, so the test
  measures a Windows/POSIX hybrid that exists on no real system. Pin the
  distinction via the `PosixPath` consequence, not by asserting the patch target.

## Shell Quoting (PowerShell)

PowerShell only honours backtick escapes, so `\"` does **not** escape a quote
inside a double-quoted string: any pattern containing `["']` or a bare `\"` is a
`ParserError` and the command never runs. Build patterns in **single-quoted**
variables (doubling any inner single quote as `''`), or split a `["']` class into
separate double-quote and single-quote greps. There is also no heredoc —
`git commit -F - <<'MSG'` dies with "Missing file specification after
redirection operator"; write the message to a file and use
`git commit -F "<path>"`, then delete the scratch file. (In Git Bash a heredoc
works; match the dialect you are actually in.)

## Secret Scanning

After `git add -A`, scan the **index** — it is exactly the tree the next commit
will create — with `git grep --cached -n -i -E -I -e '<pattern>'` rather than
`rg` (which may not be installed).

- The scan is **not scoped to the diff**: hits also surface pre-existing
  committed content (e.g. `album_art_sync/api/fanart.py`'s
  `params={"api_key": app_key, ...}`), which is expected noise rather than a new
  leak. When the question is specifically "does *this* change introduce a
  secret", append `-- <staged files>` pathspecs. This is what caught and excluded
  the live Fanart.tv keys in P1 (`PLAN_audit_priority_actions.md` D11).
- **A scan is only as good as its alternation.** Match `*_key`/`*_secret`
  suffixes, 32-hex literals and 44+-char base64 — not just
  `api[_-]?key|secret|passwd|password|token`. The audit regex sailed past
  `album_art_sync/*/album_art_config.json`'s `"app_key"`/`"client_key"` Fanart.tv
  keys because neither token is in the alternation and a 32-hex value is not
  matched. Supplemental scans that caught them:

  ```
  git grep --cached -n -i -E -I -e '[-_](key|secret|token|password|passwd|client)[^ ]*[=:][^A-Za-z0-9_][A-Za-z0-9+/=_-]{10,}'
  git grep --cached -n -i -E -I -e '"[a-f0-9]{32}"'
  git grep --cached -n -E -I -e '"[A-Za-z0-9+/]{44,}={0,2}"'
  git grep --cached -n -E -I -e '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  ```

  The PEM pattern must be passed with `-e` because it starts with `-`. Files
  named `*_config.json`/`.key` belong in `.gitignore` before any commit.

## Utility Script Markers

All `utilities/*.py` CLI scripts must use ASCII-only status markers in square
brackets (`[OK]`, `[ERROR]`, `[INFO]`, `[DONE]`, `[START]`). No emoji or Unicode
symbols — Windows `cmd.exe` cannot render them.

## Master Driver Card Naming

`enrich_tab.py` and `utilities_window.py` lazy-import each tool's card as
`master_driver.ui.cards.{tool_id}_card` and call `build(parent, state)`, where
`tool_id` is the manifest `id` in `audio_suite_shared/tool_plugin.py`. Name the
file exactly `{tool_id}_card.py` (e.g. `fingerprinter_card.py` for id
`fingerprinter`).

- `utilities_window.py` has `_CARD_MODULE_OVERRIDES` for the one documented
  exception (`{"asx_extractor": "asx_card"}`); `enrich_tab.py` has **no**
  override map, so an enrich tool must follow the convention exactly or add a map
  there too.
- A file whose name merely *resembles* the id is silently never found — the only
  symptom is a `No card UI for tool '<id>'` warning in the console. Verify the
  card file name against the manifest id before creating it.

## Tab Grouping (UTIL and ENRICH)

The UTIL tab renders `tool_plugin.utility_sections()`: one full-width caption
per `UTILITY_GROUPS` entry, in workflow order (convert/import, tags and
artwork, analysis, repair, organise), the cards alphabetical inside a group,
then a `Plugins` section last that a plugin can neither rename nor join. A
caption is a `tk.Label`, not a `Frame`, so the grid's card cells stay the
host's only `Frame` children and card discovery cannot mistake a caption for a
card.

- **`order` is the display order *and* the sequential batch order.** The tab
  renders the registry list and `arg_builder.build_utility_args` walks the same
  list, so a reorder moves both. Groups are contiguous blocks of ten in
  `order`, and
  `master_driver/tests/test_utilities_window.py::TestGroupedSections` freezes
  the rendered sequence, so a manifest edit that silently reorders the tab (and
  the run) fails the suite instead of shipping.
- **Do not group the tab by filtering the registry in the window.** Sections
  come from the manifest, so the CLI, the README index, the docs index and the
  batch all keep seeing the one order.
- **One splitter, two tabs.** `grouped_sections(manifests, groups)` in
  `audio_suite_shared/tool_plugin.py` is the only implementation; the tab's
  `utility_sections()` / `enrich_sections()` wrappers differ only in the
  `UTILITY_GROUPS` / `ENRICH_GROUPS` declaration passed. Plugin-last and the
  trailing "Other Tools" fallback live there, and the caption widget is one
  shared `GroupCaption` (`master_driver/ui/group_caption.py`), so the two tabs
  cannot drift apart in wording, style or fallback behaviour.
- **ENRICH groups keep the dependency-vetted order; they do not alphabetise.**
  The enrich sequence says which tool supports which (Tempo Analyzer reads the
  BPM tag BPM Analyzer writes; Album Art Sync runs after the tag rewrites), and
  it is the sequential batch order, so an alphabetical re-sort would silently
  reorder a run. Each section is therefore a contiguous run of that order -
  renumbering into blocks of ten changes nothing - and
  `audio_suite_shared/tests/test_tool_plugin.py::TestEnrichGrouping` fails if a
  group moves a tool past another. A tab that genuinely owns no dependency may alphabetise (UTIL
  does); that is a decision per tab, not a house style.

## Plugin System

The suite has one extension mechanism: `audio_suite_shared/plugin_system/`
discovers `plugins/*/MANIFEST.toml` and validates it, and `tool_plugin` adds the
enabled plugins' tools to the registry it freezes. The development guide is
[documentation/docs/plugins.md](documentation/docs/plugins.md); the bundled example is
`plugins/example_plugin/`. Evidence: `PLAN_feature_expansion.md` D130-D133.

- **Discovery is data; code loads only when enabled.** The manifest is parsed
  and refused or accepted at import time of `cli_app`, with no plugin module
  imported, so `doctor` and `plugins list` can report a plugin that will not
  load. Never import plugin code during discovery: a broken third-party plugin
  would then take down `audiosuite --help`.
- **Enablement is a suite preference, never a manifest field.** The map lives in
  `audio_suite_config.json` under `plugins_enabled`; a plugin missing from it
  falls back to `loader.BUNDLED_DEFAULT_ENABLED`, which is first-party code. A
  manifest must not be able to opt itself in.
- **Four extension points, one real host each** — `tool` (`tool_plugin`,
  `cli_app`, the Master Driver's toggle/card/arguments/launcher), `tool.ui`
  (`utilities_window` / `enrich_tab` calling the plugin's card builder),
  `tag_processor` (`TagProcessor`), `analysis` (library_stats
  `scan_directory`). A new extension point is not shipped until a first-party
  host calls it and a test reads the artefact back from disk.
- **A plugin failure is counted, never fatal.** A contribution that raises or
  returns the wrong shape is logged against its plugin and counted
  (`plugin_errors`, `plugin_analysis_errors`); the file and the run continue.
  The one defect the host cannot undo is a tag processor that writes during a
  dry run — test that outcome on a real file.
- **Every host keeps an off switch.** `tag-update` has `--no-plugin-tags`,
  `stats` has `--no-plugin-analysis`, and both default to on. Without the
  switch, a difference between two runs cannot be attributed to a plugin.
- **Pre-flight deliberately skips `plugins/`.** A third-party syntax error must
  block that plugin, not every tool's launch.
- **Tests isolate discovery.** Point `AUDIOSUITE_PLUGIN_DIR` at a temp tree and
  call `reset_plugins_for_tests()` (it also removes the roots it added to
  `sys.path`). `tag_field_updater/tests` and `library_stats/tests` do this in an
  autouse fixture; a test that wants a contribution installs its own throwaway
  plugin. Fixed names collide through `sys.modules`, so purge the probe module
  before importing a rewritten one.

## Registering a New Tool (Checklist)

Every new tool must be wired into ALL of the following before it is complete.
Missing any one produces a silent runtime degradation (a missing card only logs;
a broken Help button warns):

1. **Tool manifest** — `audio_suite_shared/tool_plugin.py`: `ToolManifest`
   entry. Its `id` is the single source of truth used everywhere below. A
   **utility** tool also names its `group` (a `UTILITY_GROUPS` key) and takes
   the next free `order` in that group's block of ten, with its name
   alphabetical among the group's siblings —
   `audio_suite_shared/tests/test_tool_plugin.py` refuses a utility that names
   neither, or that breaks either rule.
2. **Master Driver card** — `master_driver/ui/cards/{tool_id}_card.py`, named
   exactly per the section above.
3. **CLI command** — the tool's `click` command plus its import in
   `audio_suite_shared/cli_app.py`. Verify flag names against the CLI, never an
   assumed design; decide the GUI grammar by launching the tool, not by reading
   the click CLI.
4. **Arg builder** — `master_driver/runner/arg_builder.py`: one entry per tool.
   Enrich tools MUST emit `[path, mode_flag, start_flag, end_flag]` —
   `test_runner.py`'s `TestBuildEnrichArgs` asserts it for every enrich entry.
   `lambda: []` breaks those tests; fix the builder, never weaken the tests.
5. **Batch orchestration** — `master_driver/batch_orchestrator.py`
   `DEPENDENCY_GRAPH` ordering.
6. **Driver state** — a module toggle key in `master_driver/state/app_state.py`,
   plus `master_driver/tests/test_app_state.py`'s expected keys.
7. **Pyw launcher** — a top-level `<Tool_Name>.pyw` calling the pre-flight guard
   (mandatory — see *Startup Pre-Flight Guard*), and linted and formatted like
   any module (see *Launchers Are Linted*).
8. **User guide** — a Markdown source
   `documentation/user_guides/individual_programs/<module_dir>/<Guide>_User_Guide.md`,
   rendered by `python utilities/build_user_guides.py <module_dir>`; the `.docx` beside it
   is a build artefact, never hand-edited (the renderer is the one shared
   implementation, and `tests/test_user_guide_hygiene.py` fails on a stale
   artefact). Plus the filename → folder registration in
   `audio_suite_shared/platform_utils.py`'s `guide_to_program`.
   `tests/test_guide_resolution.py` locks that map against the manifest, so a
   tool whose guide is unregistered fails the suite.
9. **Test registration** — `pyproject.toml`: `<module>/tests` in `testpaths` plus
   the package in coverage `source`; unique test-dir basename or `__init__.py`.
10. **Tests** — a new `<module>/tests/` suite, and update the expected-set tests
    in lockstep (`test_tool_plugin.py`, `test_app_state.py`, `test_runner.py`).

11. **Callback contract** — the tool's `app.py` handlers follow the *GUI
    Callback Contract* (catch-all on `on_complete`/`on_*progress`, one `message` on
    `on_error`) and the tool is added to
    `tests/test_callback_payload_contract.py`'s `EXPECTED_TOOLS`.

12. **Run report** — the tool writes a report beside the files it scanned
    (`<prefix>_{dry_run,sync}_log.txt`) in the shape *Run Reports vs Program
    Logs* describes, names it in `_log_path` when a run starts, and has a test
    that reads the written file back. Its View Log must open that report, never
    `logs/<program>.log`.

**Verification:** a per-package `pytest <pkg>/tests` is NOT sufficient proof —
the integration tests in `master_driver/tests/` and `audio_suite_shared/tests/`
catch registration mistakes a package's own tests cannot see. The final gate MUST
be a bare full-suite `pytest` run.

## Documentation Formats

**There is one documentation tree: `documentation/`.** Nothing a reader is meant
to read lives anywhere else, so "which documents does this affect?" is answered by
one directory walk rather than by remembering a list of folders.

```text
documentation/
    docs/          the Sphinx site (README, changelog and API links point out of it)
    user_guides/   the guides the Help button opens, and their Markdown sources
```

**One authored format: Markdown.** Everything else under `documentation/` is
generated, and no generated file is hand-edited.

- `documentation/docs/**/*.md` are Sphinx pages rendered by MyST
  (`myst-parser` in the `dev` extra). `tests/test_docs_build.py` fails on any
  parser warning; CI publishes the built HTML as the `docs-html` artifact.
  Cross-page links inside `documentation/docs/` use the `{doc}` role; links to
  repository files outside it stay plain relative URLs
  (`myst_all_links_external`), because Sphinx only resolves documents inside its
  source directory. That exemption is why a wrong relative link is silent: a
  page sits two levels down, so a repository-root file is `../../README.md`, and
  `tests/test_docs_build.py::TestPublishedTreeIsSelfContained` is what proves
  every such href resolves in the staged tree.
- `documentation/user_guides/individual_programs/<tool>/<Guide>_User_Guide.md` is a guide's
  source. The `.docx` beside it is rendered by
  `utilities/build_user_guides.py` and is what the Help button opens: edit the
  Markdown, then run `python utilities/build_user_guides.py <module_dir>`.
  `--check` proves every artefact is current and reports drift as a differing
  zip entry. Suite-wide reference pages ride the same path:
  `documentation/user_guides/reference/*.md` (the CLI commands reference) is
  rendered by the same script
  (`python utilities/build_user_guides.py reference`) into the `.docx` beside
  it, and is drift-checked identically even though no Help button opens it.
  The renderer's dialect is small: a list, table, fence or callout needs a blank
  line before it, or it is absorbed into the preceding paragraph as plain text.
- Both HTML tables are generated: `utilities/generate_docs_index.py` writes the
  docs index (from the tool manifest, validated against `guide_to_program`) and
  `utilities/generate_readme_tool_index.py` writes the README's. Never edit
  either by hand — re-run the script.
- Two artefacts keep a committed generator instead of a Markdown source: the
  new-user `.pptx` (a slide layout is code, not prose) and the logging guide
  (its sample log lines are rendered from the live formatter).
  `tests/test_user_guide_hygiene.py` accepts exactly those two; any other
  unreproducible binary fails, and a parked one is a test failure by design.
- User-facing error wording lives once, in `audio_suite_shared/exceptions.py`'s
  `USER_MESSAGES`. `documentation/docs/user/messages.md` renders that table and
  `audio_suite_shared/tests/test_exceptions.py` fails when the two disagree, so
  a message cannot change meaning in one place only.
- `tests/test_docs_formats.py` is the arbiter for formats: its whitelist
  governs **every** tracked file under `documentation/`, so a new subdirectory
  there is covered without editing the test. A new `.rst`/`.txt` page fails until
  the approved set is edited deliberately, and a machine-specific absolute path
  in doc tooling fails the scan.
- **Do not reintroduce a second documentation root.** A new folder beside
  `documentation/` (an `api_docs/`, a `manuals/`) splits the walk that the review
  rules below rely on; put the pages in `documentation/docs/` and the shipped
  guides in `documentation/user_guides/`.

## Change History Follows Its Audience

The change history is two files, and a bullet's **subject** decides which one it
sits in — not its wording and not its size:

- `CHANGELOG.md` records what a user can run or observe: a tool's behaviour, a
  flag or default, a supported format, an error message, a workflow step, or a
  measured speed or size difference. It is the file the in-app *What's New*
  panel renders (`audio_suite_shared/whats_new.py`), so something a user cannot
  observe does not belong in it.
- `TECHNICAL_CHANGELOG.md` carries everything else: the gate, CI, the tests,
  tooling, behaviour-neutral refactors and dependency bumps. It sits beside
  `CHANGELOG.md` as shipped release data and is not a second documentation root
  (`tests/test_docs_formats.py`'s walk covers `documentation/` only).
- `utilities/release.py` promotes **both** in one cut. The user-facing file must
  hold an entry; the technical one may hold none, and a release with no
  developer-facing change adds no heading there rather than an empty one.
- `tests/test_changelog_format.py` holds the boundary mechanically: a bullet's
  bold lead-in may not name developer work (`test`, `pytest`, `gate`, `CI`,
  `workflow`, `ruff`, `mypy`, `coverage`, `benchmark`, `lint`), and every
  allowlist entry records its reason. A bullet that mixes the two is **split**:
  the user-observable statement stays, its evidence moves.
- **A user-facing bullet is written for the person who uses the suite.** The
  file is rendered by the in-app *What's New* panel, so its reader may not know
  what a callback, a muxer or a resolution is. Lead with what the user can now
  do or will now see; explain a technical term the first time it appears (LUFS,
  true peak, dry run, container); keep a number only where it changes the
  decision to upgrade; and leave module paths, class names and helper names out
  - they tell the reader nothing they can act on, and they are what
  `TECHNICAL_CHANGELOG.md` exists for. Evidence: the 2026-11-13 user report that
  the file was "often not understandable by a non-technical user", which led to
  the whole file being rewritten in plain English.
- **User-facing prose uses British English.** Verbs take `-ise` (normalise,
  organise, recognise, analyse, serialise, prioritise), nouns take `-our`
  (behaviour, colour, favour) and `-re` (centre, metre), and the spellings are
  `licence` as a noun with `license` as a verb, `catalogue`, `grey`, `artefact`,
  `judgement`, `cancelled`, `labelled`, `modelled`, `fulfil`, `enrol`,
  `defence`, `sceptical`. Three cases are not spelling choices: a product name
  keeps its shipped spelling (`File Reorganizer`, `Audio Normalizer`, `Album Art
  Normalizer`), so does a command-line option (`--normalize-mp3`), and so does a
  file name or a quoted message (`LICENSE`, the `licenses/` folder, an FFmpeg
  error text) - renaming any of them is a product change, not a correction.
  The rule governs both change-history files, the guides and the Sphinx pages
  under `documentation/docs`, and every corpus is enforced: one table in
  `tests/spelling.py` serves `test_changelog_format.py::TestChangelogSpelling`
  for the two change-history files, `test_guide_spelling.py::TestGuideSpelling`
  for the guides' prose and `test_docs_spelling.py::TestDocsSpelling` for the
  Sphinx pages.
  Every allowance carries a reason and must still match a real line. A fenced
  block and an inline code span are code rather than prose, so a command or a
  value keeps the spelling the program accepts - `--normalize-mp3` and the
  colormap `gray` are not offences, and a new one belongs in code, not prose.
- **Every released section is grouped under the six Keep a Changelog
  categories**, in this order: `### Added`, `### Changed`, `### Deprecated`,
  `### Removed`, `### Fixed`, `### Security`. The vocabulary is closed - a
  section may not invent `### Deleted`, `### Notes` or a typo - every bullet
  sits under one, no category heading is empty, and only `[Unreleased]` may hold
  no bullets at all ("Nothing yet."); a released version with none is a bug.
  **The bold lead-in decides the category**, as it decides the audience: a
  bullet that adds a report *and* repairs a missing one is `Fixed`, because its
  subject is the repaired contract. `tests/test_changelog_format.py`'s
  `TestChangelogCategories` is the arbiter, and `utilities/release.py` runs the
  gate in the same cut, so a flat section cannot ship.
- Evidence: `PLAN_functional_backlog.md` U2 and D29. The 2.2.0 and 2.1.7 sections
  each carried a bullet for the release gate or a test's skip condition between
  bullets a user cares about, and nothing separated the two audiences.
- Evidence: `PLAN_2026-11-08_changelog_categories.md`. The five sections from
  2.4.1 forward - 70 bullets - were promoted flat because `promote_changelog`
  copies the `[Unreleased]` body verbatim and nothing asked for a category.

## User Guides Follow the Change

**A change is not done until the guides for what it touches have been read
against it.** Guides are the product's only description of behaviour, and they go
stale silently: nothing compiles them, no test asserts what they claim, and the
tool keeps working while the document lies about it. A1 is the worked example —
the album-gain arithmetic was replaced and `ReplayGain_Analyzer_User_Guide.md`
still described the old duration-weighted formula in four places (Setup, the
processing steps, the values table and Troubleshooting); it was found only when a
reviewer asked (`PLAN_functional_backlog.md` D17).

- **Review the guides of every tool the change touches** whenever it alters an
  option or flag, a default, a supported container or extension, a calculation,
  a status or log line a user reads, or a workflow step. Update the Markdown,
  then re-render: `python utilities/build_user_guides.py <module_dir>`, or
  `python utilities/build_user_guides.py reference` for
  `documentation/user_guides/reference/`. Authored
  `documentation/docs/**/*.md` pages count as guides too;
  `documentation/docs/_build/` is generated output and is never edited.
- **The sweep is one directory, not a list of files.** Because every document
  lives under `documentation/`, "check the guides" means reading every entry
  under `documentation/` that describes what the change touched — the tool's
  guide, the site pages that name the tool, the CLI reference, and the suite
  overview whose tool count or table may quote it. Enumerate the directory
  (`git grep -l <the option, flag, default or count> -- documentation/`) rather
  than recalling which folders used to hold prose. `tests/test_guide_claims.py`
  mechanically holds the claim classes it can (format counts, worker counts,
  quoted flags, status tokens, artifact names) against the code; everything else
  is read.
- **Record the outcome even when nothing changes.** "No guide describes this
  behaviour" is a valid answer and must be stated — in the governing plan's
  verification line, the commit message, or the change's description — so a
  skipped review is visible instead of indistinguishable from a completed one.
- **`--check` is the mechanical proof.**
  `python utilities/build_user_guides.py --check` compares zip entry *data*, so
  it catches a `.docx` left behind an edited `.md` (see *User-Guide Regeneration
  Diffs*), and `tests/test_user_guide_hygiene.py`,
  `tests/test_cli_reference_hygiene.py` and `tests/test_docs_build.py` fail on a
  stale or unrenderable artefact. Editing the Markdown alone is an incomplete
  change, not a smaller one.
- **A user-visible change with no guide passage deserves a second look.** If
  nothing in the guide describes it, say which case it is: a fix or detail no
  user needs to know about, or a gap where the guide should have said something
  and now must (a new format, a changed default, a new failure message).

### Guide Figures Come From the Live Window

Every guide figure is a grab of the running tool taken by
`utilities/capture_guide_shots.py`, committed beside the guide with a sidecar and
embedded by `![caption](images/<name>.png)`; no figure is hand-drawn or edited.
Five rules matter beyond the obvious:

- **The capture must be DPI-aware before `tk.Tk()` exists.** A DPI-unaware
  process makes Tk report *logical* pixels while `ImageGrab` copies *physical*
  ones, so on a 125% display the grab rectangle covers only the top four fifths
  of the window, and whatever is packed along the bottom edge — BPM Analyzer's
  `BEGIN BPM ANALYSIS`, for one — is missing from a figure no other check can
  fail. The harness therefore calls `_enable_dpi_awareness()`, requests each
  plan's geometry scaled by `dpi / 96`, and scales the grabbed frame back to the
  pinned size, so a figure keeps the layout its plan describes at 100%. The old
  docstring claims that a window paints "30 px from where it was placed" and
  that `overrideredirect` made a start button stop painting were this artifact,
  not separate findings: awareness removed both.
- **The lock reads the committed PNG and measures colour, not palette state.**
  `tests/test_user_guide_hygiene.py` opens the artefact and asserts what a
  reader sees — the BPM setup figure's lower third is more than 10% coloured —
  so a figure cropped above its bottom row fails. Do not key such a lock on
  `styles.get_main()`: the palette is module state another test mutates in
  place, and the first version of that lock failed on the full suite for exactly
  that reason while the picture was correct.
- **A capture is a desktop step; its output is committed.** The harness refuses
  a non-96 dpi display unless `--force-dpi` is passed (the committed figures
  came from a 125% host, requested at `dpi / 96` and downscaled). Rendering
  stays reproducible, which is why `--check` still catches an edited guide
  without re-capturing anything.
- **Every figure shows its own tool's run, from a declared sample run.** The
  filler once pushed BPM Analyzer's nine-track lines into every Processing
  figure, so Genre Sync's picture carried `[DRY RUN] ... 128 BPM` and worker
  counters that tool never writes. Each tool now declares its run in
  `SAMPLE_RUNS` — status line, per-file lines, counters — and a plan that
  declares none starts no run rather than inheriting one. A pane with no
  per-file list gets an honest equivalent instead (ASX Playlist Extractor
  animates its six steps; ReplayGain Analyzer's tree stays empty mid-run) or its
  opening state. A new tool must declare its own lines: `DECLARED_LINES` and
  `TOKEN_OWNERS` are derived from those declarations, so an undeclared tool
  fails the lock instead of passing quietly.
- **The capture reads the filled tab back and refuses a figure that is not that
  tool's run.** The failure this catches is silent: the window is real, the grab
  succeeds, and the guide ships an idle tab under a "part-way through a run"
  caption. After filling, `_check_sample_content` requires a non-empty display,
  rejects a line another tool declares, rejects a status token only another
  tool publishes (`[FINGERPRINT]` is Duplicate Finder's), and requires the
  display to end with the declared run.
  `utilities/tests/test_capture_guide_shots.py` holds that for every tool that
  declares a run, so a registry that loses one tool's lines fails rather than
  quietly shrinking the check.

Evidence: the 2.5.0 guide-figure work (`TECHNICAL_CHANGELOG.md`, commit
`e798436`), where a green gate, a passing renderer check and a 78-figure capture
run all coexisted with two dozen figures that had quietly lost their bottom
fifth.  The same release also shipped figures whose status lines belonged to
another tool — a Genre Sync picture showing BPM Analyzer's run — which no gate
could see until a reviewer read the caption against the picture; the per-tool
sample runs and the read-back lock above are that fix (commit `17d4b92`).

## User-Guide Regeneration Diffs

Regenerating `documentation/user_guides/**/*.docx` / `.pptx` is **content-stable but never
byte-stable**: python-docx/pptx rebuild the zip container and every entry's
local-header mtime changes, so `git status` reports all artifacts modified even
when no text moved. This is why `build_user_guides.py --check` — and the release
cut's triage — compares **zip entry data**, not the file hash or `git diff`:

- every entry's compressed data byte-identical to HEAD → timestamp-only diff →
  `git restore` it (minimal-diff rule);
- an entry's data differs → investigate before keeping it.

**The renderer's fresh output is the source of truth.** A committed artifact
re-saved by an external editor is external-tool drift, not renderer drift:
LibreOffice rewrites `docProps/app.xml`'s `Application` field, adds
`docProps/custom.xml`, and drops
`thumbnail.jpeg`/`stylesWithEffects.xml`/`webSettings.xml`. When the text is
byte-identical, keeping the regenerated file restores it.

Run the generators with the interpreter that carries the dev extras
(`python-docx`/`python-pptx`): `python` on PATH may be a system interpreter
without them, while `generate_presentation.py` needs `python-pptx` from `.venv`.
Verify with `pytest tests/test_user_guide_hygiene.py tests/test_docs_formats.py`.

## Refactor Safety

- **Signatures before casts.** Fix a call chain's signatures/argument order first;
  a mypy cast can mask a runtime construction failure that the real-app tests
  would have caught.
- **UI builder signatures are the source of truth.** When tab builders have
  specific parameter orders/types (`results_tab.build(parent, on_open_log,
  on_open_folder, on_play_original=None, on_play_result=None)`,
  `processing_tab.build(parent, slot_vars=None)`), never infer extra args from a
  sibling builder — read the target module and mirror it exactly. Mismatched
  positional args raise `AttributeError`/arg-type errors in real-app construction
  tests.
- **Unused scaffold must not remain.** A shared base with zero production
  references and incomplete integration must be integrated properly or removed
  (minimal scope); leaving it is dead code.
- **Lock deleted public APIs with an AST test.** When deleting a subsystem that
  exposed public names, add an AST-based test asserting those names are absent, so
  they cannot be reintroduced by accident.
- **Clean up alongside deletion.** Removing dead code also removes the orphaned
  type aliases and docstrings in the same change scope.
