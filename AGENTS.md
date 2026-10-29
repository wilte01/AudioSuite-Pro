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
100-minute budget. Never discover this through a broken `tomllib` import two
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
  deliberate composites/contract locks (30 entries, length asserted).

So "there is one exception" is wrong: there are two blanket exemptions plus a
frozen allowlist. To add a legitimate exception, add it to `ALLOWLIST` with a
reason — do not widen this section.

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
- domain-specific lists too structured for flat key-value (`tag_prefs.json`).

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
seam. `EXPECTED_TOOLS` × `EXPECTED_SEAMS` is frozen at 14 tools and three
seams, so a new GUI tool must be registered there deliberately, every tool must
wire all three, and a broken discovery pass fails instead of passing vacuously.
Non-GUI wirings (the Master Driver's `lambda executed:`, CLI wrappers) are not
matched. A required field that goes missing is a `TypeError` naming it, never
a silent default: `tests/test_completion_seam.py` freezes each handler's
required parameters in `EXPECTED_REQUIRED` and asserts that dropping any one
of them raises. Neither lock can prove the processor still *sends* every
field; only a test driving the real `run_*` into the bound handler does, and
it asserts the written outcome — the pattern is
`audio_enhancer/tests/test_app.py::TestCompletionSeam`.

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
   entry. Its `id` is the single source of truth used everywhere below.
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
   (mandatory — see *Startup Pre-Flight Guard*).
8. **User guide** — a Markdown source
   `documentation/user_guides/individual_programs/<module_dir>/<Guide>_User_Guide.md`,
   rendered by `python utilities/build_user_guides.py <module_dir>`; the `.docx` beside it
   is a build artefact, never hand-edited (the renderer is the one shared
   implementation, and `tests/test_user_guide_hygiene.py` fails on a stale
   artefact). Plus the filename → folder registration in
   `audio_suite_shared/platform_utils.py`'s `guide_to_program`.
9. **Test registration** — `pyproject.toml`: `<module>/tests` in `testpaths` plus
   the package in coverage `source`; unique test-dir basename or `__init__.py`.
10. **Tests** — a new `<module>/tests/` suite, and update the expected-set tests
    in lockstep (`test_tool_plugin.py`, `test_app_state.py`, `test_runner.py`).

11. **Callback contract** — the tool's `app.py` handlers follow the *GUI
    Callback Contract* (catch-all on `on_complete`/`on_*progress`, one `message` on
    `on_error`) and the tool is added to
    `tests/test_callback_payload_contract.py`'s `EXPECTED_TOOLS`.

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
