# AGENTS.md — AudioSuite-Pro Project Conventions

## Repository / Version Control

The tree is a git repository on `main` (initialised in audit P1). Treat it as
such: each remediation item lands as one or more reviewable commits, and the
full Definition-of-Done gate runs against the state after each commit.

- `uv.lock` is committed — it pins the resolved dependency graph consumed by CI's `uv sync`. Do not re-ignore it.
- `fpcalc.exe` is committed — a small (~4 MB) native runtime binary the
  Fingerprinter needs out-of-the-box.
- Runtime config and API-key files are intentionally gitignored
  (`audio_suite_config.json`/`.key`, `album_art_config.json`/`.key` in
  `album_art_sync`). Never `git add -f` them; a live Fanart.tv key was caught
  inline during P1 and staged, then reverted.

## Plan Governance

- At session start, confirm and state the **governing plan** from the user's
  instruction; if the brief is silent, ask before plan-anchored commits.
- A mechanism-name grep picks *reference code*, never authority — the governing
  plan is the one that **owns the modules/tools being touched** (four orphan DSP
  tools → `PLAN_audit_priority_actions.md` P6, not the completed
  `PLAN_basesetupframe_refactor.md`).
- A plan whose items are all marked COMPLETE/DONE is a **historical record**:
  add follow-on work only as a clearly-labelled decision-log/supersession entry
  (with user approval) or a new plan.
- Defects found in working code during any session → fix in the same change +
  regression test + record in the governing plan's decision log (§7).

## Test File Naming

All test files live in `<package>/tests/` and follow the standard pytest
convention: **one test file per source module**, named `test_<module>.py`.

| Source Module | Test File |
|---|---|
| `core/scrubber.py` | `tests/test_scrubber.py` |
| `core/pipeline.py` | `tests/test_pipeline.py` |
| `app.py` | `tests/test_app.py` |
| `cli.py` | `tests/test_cli.py` |
| `utils/cli_args.py` | `tests/test_cli_args.py` |
| `core/file_processor.py` | `tests/test_file_processor.py` |

Rules:
- Test file names mirror the source module name they test.
- Do **not** add suffixes like `_core` unless the source module itself ends in `_core`.
- Do **not** use descriptive/compound names like `test_app_audio_detection.py`.
  Use `test_app.py` and put the specific test class inside.
- One exception: composite test files that intentionally test multiple tightly
  coupled modules (e.g. `test_tag_io.py` for `tag_reader.py` + `tag_writer.py`)
  are acceptable when a clear single-module name does not exist.

## Shared Config Pattern

Tool-specific preferences that are simple key-value pairs **must** be stored
in the shared `audio_suite_config.json` via `audio_suite_shared.suite_config`,
not in tool-local JSON files.

Use `suite_config.load_value(key, default)` and `suite_config.save_value(key, value)`.

Tool-local config files (e.g. `mood_batch_config.json`, `tempo_config.json`)
are deprecated. New tools must not create them. Existing ones should be
migrated following the pattern in `tempo_analyzer/utils/config.py` or
`mood_analysis_batch_tagger/utils/config.py`.

Exceptions where tool-local files are acceptable:
- API keys or secrets (`album_art_config.json`)
- Complex nested pipeline settings (`refinery_settings.json`)
- Domain-specific lists too structured for flat key-value (`tag_prefs.json`)

## Tkinter GUI Testing

GUI `app.py` modules must be testable without a real display. Use the
`object.__new__` + `MagicMock` pattern:

```python
app = object.__new__(MyApp)
app.root = MagicMock()
app.some_var = MagicMock()
app.some_var.get.return_value = "expected"
```

Never instantiate the real `tk.Tk` or `tk.Tk()` in tests unless using the
session-scoped hidden root from `conftest.py`.

- **A widget's construction-time default is what the user sees whenever its
  update path never runs — and every programmatic pre-fill bypasses the widget
  events that would have run it.** A `readonly` Combobox seeded in `build()`
  with `values = ALL_FORMATS` is narrowed only by the handler bound to the
  source widget's `<FocusOut>`/`<Return>`. None of those fire when the value was
  set in Python instead of typed: the Master Driver/CLI arg
  (`runner/arg_builder.py` passes the shared directory positionally), a
  `--flag`-parsed value, or a restored `suite_config.load_last_directory()`.
  The tool then launches showing every option — in
  `music_format_converter` the mp3-only folder kept `mp3` *and* every lossless
  target selectable, and a dry run skipped 10/10 files as same-format. Rule:
  any variable written outside a widget edit must route through the **same**
  update function the edit handler calls (schedule it, don't duplicate the
  logic), and every pre-fill route needs a test asserting the *narrowed* state.
  Audit all of them together — Driver argv, CLI flags, restored config — since
  a single missed route reproduces the whole bug.

## Startup Pre-Flight Guard (Do Not Disable)

`Master_Driver.pyw` (and the pattern it establishes) runs
`audio_suite_shared.preflight.guard_or_exit()` before importing any tool
module. This byte-compiles every first-party source file so a
syntax/indentation error or a missing module in the import chain blocks
launch with a clear dialog instead of an opaque log traceback.

Rules:
- Never bypass, weaken, skip, or comment out the guard to "get things
  working" — that is what let broken imports ship previously.
- Keep the guard pure (no Tk side effects) and unit-tested in
  `audio_suite_shared/tests/test_preflight.py`.
- After ANY edit to a module in the import chain, re-run the required
  compile gate (`python -m compileall -q -f .`) before marking work done.
- When adding a new `.pyw` launcher, add the same `guard_or_exit()` call at
  the top, before the tool's app import.

## Utility Script Markers

All `utilities/*.py` CLI scripts must use ASCII-only status markers in
square brackets: `[OK]`, `[ERROR]`, `[INFO]`, `[DONE]`, `[START]`, etc.
No emoji or Unicode symbols — Windows `cmd.exe` cannot render them.

## Verification Tooling (Windows-specific invocations)

These gotchas were hit empirically during the DSP normalization Phase 9 gate.
Follow them or the "passing" run is misleading.

- **Failing tests must be resolved — never shipped.** "Tests that fail are
  worse than no tests": a red suite is silently ignored and masks real
  regressions, so every tool in the pipeline (`pytest`, `ruff`, `mypy`
  (strict via `[tool.mypy] strict = true`), `bandit`) must pass 100% before
  work is marked complete. Do not
  delete, skip, `xfail`, or add `# type: ignore` to make a failure go away —
  resolve the underlying cause. If a test or check is genuinely wrong, fix
  the test/check itself in lockstep with the code, and update the relevant
  AGENTS.md gotchas so the mistake is not repeated.

- **Defects are fixed when discovered — never deferred.** A bug found during
  development, review, an audit, or a test run must be resolved in the same
  change that found it, with a regression test in lockstep. Deferral to a
  later phase or a "ticket" is only acceptable for new-feature backlog items —
  never for defects in working code.

- **Audio correctness is release-blocking.** This suite manipulates audio
  data: any defect that could corrupt, mis-normalize, mis-tag, or incorrectly
  convert audio (global_gain rewrites, LUFS normalization,
  sample-rate/bit-depth conversion, analysis, tag writes) is the
  highest-priority fix class. Validating such fixes requires tests that
  verify the **actual audio outcome** — decode the result and measure
  per-channel RMS/loudness — not tests that read back the same internal state
  the code just wrote. Self-consistent field read-back cannot detect
  corruption (see the lossless_gain stereo-offset bug, iterations 1–2 in
  `PLAN_audit_remediation.md` / `PLAN_iteration2_remediation.md`).

- **A `requires-python` floor is only honest if the committed lockfile honours
  it.** `>=3.10` let `uv.lock` resolve a second, stale numeric stack for the
  oldest leg (numpy 2.2.6 / scipy 1.15.3 behind `python_full_version < '3.11'`
  markers) while 3.12+ got numpy 2.5.2 / scipy 1.18.0 — and the dev host
  (3.14.7) had no CI leg at all, so the green 3.10 leg certified a dependency
  graph nobody developed or shipped against. Whenever the floor or a heavy
  dependency moves, audit the lock's per-interpreter markers: if the oldest
  leg resolves older wheels than the interpreter the suite is actually
  developed on, raise the floor or accept the split knowingly — never discover
  it through a broken `tomllib` import two floors up. (2026-09-28: floor raised
  to 3.11; CI matrix `["3.11", "3.12", "3.14"]`; the 3.10-only pins — numpy
  2.2.6, scipy 1.15.3, exceptiongroup 1.3.1, scikit-learn 1.7.2 — fell out of
  the lock by themselves, and the `tomllib` guards that existed only for 3.10
  were deleted, not maintained.)

- **GUI Dry Run / mode flags must be traced end-to-end to the write site.**
  A mode the app computes and passes (e.g. `is_dry_run=is_dry_run` into
  `run_enhancement`) silently does nothing if any layer of the chain lacks
  the parameter or ignores it — the processor keeps writing, and an
  "in-place Dry Run" rewrites the source files. mypy's `Unexpected keyword
  argument` on the call site is the canary. When threading a dry-run/mode
  flag, add it to every signature in the chain and add a regression test
  asserting the **real outcome** on a temp file: no output file created, no
  write call, no tag copy, DONE status with measurements — not merely that
  the flag value arrived (see the enhancer `is_dry_run` fix).

- **mypy per-file invocations bypass pyproject's module excludes — the gate**
  **is always the bare `mypy .`.** Passing explicit paths
  (`mypy audio_suite_shared/x.py pkg/tests/test_y.py`) drops the
  `[tool.mypy] exclude = ["^tests/", ..., "/tests/"]` filtering
  context, so test files get re-checked with no per-module overrides applied
  (empirically: 89 false `no-untyped-def`/`type-arg` errors on test files the
  bare gate passes clean, plus `untyped_calls_exclude` gaps tripping
  `no-untyped-call`). Do not "fix" code or add `# type: ignore` to satisfy a
  per-file run; run `python -m mypy .` — that is the gate — and use targeted
  mypy only for debugging with the bare-run result as the arbiter.

- **Bandit must be run with `-c pyproject.toml` and UTF-8 enabled.**
  Plain `bandit -r <dirs>` does NOT auto-load `[tool.bandit]` from
  pyproject.toml, so it ignores `skips = ["B404", "B101"]` and
  `exclude_dirs = ["tests"]` — it then floods the report with hundreds of
  test-file `assert` (B101) findings and a few `/tmp` mocks (B108) that are
  out of scope. Additionally, on Windows the report crashes with
  `UnicodeEncodeError: 'charmap' codec` when a path contains a `→` character
  (e.g. any docstring arrow). Correct invocation:
  ```
  $env:PYTHONUTF8='1'; <python> -X utf8 -m bandit -r <dirs> -c pyproject.toml
  ```
  (`.github/workflows/ci.yml` already uses `bandit -r ... -c pyproject.toml` —
  mirror that.) A healthy result is 0 High / 0 Medium; the remaining Low
  subprocess findings (B603/B606/B607) are the documented first-party call
  sites routed through `run_secure_subprocess()`, and B404/B101 are skipped
  by policy.

- **`bandit -r .` scans `.venv` — always pass `-x ./.venv` (or scope to the
  first-party packages).** A bare `bandit -r .` descends into the virtual
  environment (~1.4M LOC of third-party `site-packages`) and reports hundreds
  of out-of-scope High/Medium findings, burying the 0-High/0-Medium gate.
  First-party invocation:
  ```
  $env:PYTHONUTF8='1'; <python> -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml
  ```

- **Bandit B310 fires on any first-party `urllib.request.urlopen`** and breaks
  the 0-medium gate. The suite standard is to use the already-declared
  `requests` dependency for HTTP (album_art_sync, the acoustid client, and
  the lyrics LRCLIB provider all follow it) rather than suppressing with
  `# nosec`. Also: `bandit -f json` prints its `Working...` progress line on
  stdout ahead of the JSON payload — slice to the first `{` before
  `json.loads`.

- **mypy numpy `Any`-return trap.** Under the project's `ignore_missing_imports`
  + `numpy.*` override, numpy ufuncs/`astype`/`tobytes` return `Any`. Returning
  one directly from a function declared to return an `NDArray` fails
  `--strict` with `no-any-return`. Fix by binding to an explicitly-typed local
  first:
  ```python
  clipped: npt.NDArray[np.floating[Any]] = np.clip(audio, -1.0, 1.0).astype(
      audio.dtype, copy=True
  )
  return clipped
  ```

- **mypy override module globs `X.*` do NOT match the bare module `X`.**
  An override `module = ["mutagen.*"]` covers `mutagen.aiff` but not
  `from mutagen import File`, and `module = ["mutagen.id3.*"]` does not cover
  `from mutagen.id3 import TXXX`. List each bare package/subpackage name
  (`"mutagen"`, `"mutagen.id3"`, …) alongside the glob, or the import stays
  untyped/`attr-defined`.

- **Packages with a restrictive `__all__` need `implicit_reexport = true`.**
  mutagen ships `py.typed` but `mutagen.id3.__all__` only lists
  `['ID3', 'ID3FileType', 'Frames', 'Open', 'delete']`, so every frame class
  (`APIC`, `TXXX`, `TCON`, …) and error (`ID3NoHeaderError`,
  `MutagenError`, `File`) fails `--strict` with "does not explicitly export
  attribute". Fix in the overrides block with `implicit_reexport = true`
  (and add bare module names per the previous bullet), then delete the now
  stale per-import `# type: ignore[attr-defined]` comments — mypy flags them
  as `unused-ignore`. This also un-types the symbols, so cascading errors
  like `"APIC" has no attribute "data"` disappear.

- **mypy `--strict` re-export discipline: `# noqa: F401` on a re-export is a**
  **ruff-only fix — mypy still fails on the importing module.** A
  `from audio_suite_shared.cli_helpers import was_launched_from_driver  # noqa: F401`
  in a tool's `utils/cli_args.py` passes ruff but makes every call site
  (`app.py` → `cli_args.was_launched_from_driver()`) fail `--strict` with
  `Module "…utils.cli_args" does not explicitly export attribute
  "was_launched_from_driver" [attr-defined]`. The redundant-alias form is the
  canonical explicit-reexport marker mypy accepts (and ruff treats as intention
  to re-export, so no `noqa`):
  ```python
  from audio_suite_shared.cli_helpers import (
      was_launched_from_driver as was_launched_from_driver,
  )
  ```
  If running a scripted bulk edit that inserts a re-export line, a
  parenthesized `from … import (…)` block is not a safe insertion point — the
  new import can land nested inside the existing parentheses (`tempo_analyzer` /
  `replaygain_analyzer` ships exactly this during P5 and had to be repaired by
  hand). Always re-run the compile gate and eyeball a diff of the touched lines.

- **Mutagen FLAC: rebinding `.tags` never persists — mutate in place.**
  mutagen's `FLAC` serializes the Vorbis comment dict captured into
  `metadata_blocks` at load time, so `audio.tags = other_tags` followed by
  `audio.save()` silently writes the *stale* block: the incoming tags vanish
  on disk with no error. Classic trap: `delete()` + `save()` to wipe a file,
  then restoring a different loaded tags dict (scrubber undo-restore).
  OGG/MP4 are unaffected (they serialize `self.tags` directly).
  `VorbisHandler.set_raw_tags` must `clear()` + `update()` the handler's own
  loaded dict, never rebind. Regression tests must round-trip through a real
  FLAC file (pydub export), not fakes, and ideally erase the file first.

- **AcoustID near-ties: score rank is NOT decisive when the top two
  candidates are within ~0.10 — resolve with the file's existing tags.**
  Distinct recordings built from the same underlying audio (an original and a
  remix/radio edit that reuses the recording) can both score 0.95+ against
  the same fingerprint: empirically `1-03 Johnny, Don't Do It.mp3` returned
  10cc "Johnny, Don't Do It" at 0.947 *and* Rosenstolz "Ich geh in Flammen
  auf (Full Vox Radio Edit)" at 0.984 — same ~218 s length, inseparable in the
  120 s fpcalc window. The duration guard cannot separate them (durations
  agree), and AcoustID's own database ranks the *wrong* one first, so blindly
  trusting `recordings[0]` ships a false positive. When the score gap is
  below 0.10, prefer the candidate whose artist/title match the file's ID3/
  Vorbis/MP4 tags (normalize case and punctuation — MusicBrainz "Don't" uses
  a curly quote vs the file's ASCII apostrophe). Implemented in
  `audio_fingerprinter.core.acoustid_client.resolve_best_match` (shared
  `read_artist_title`); any future AcoustID tool must apply the same
  tag-aware tie-break. When no candidate matches the tags, keep rank order
  and surface the ambiguity with the runner-up in the message.

- **pytest should run the full configured `testpaths`, not `tests/`.**
  `pytest tests/ -v` only runs the root `tests/` directory and silently skips
  every per-package `<package>/tests/` suite. Run bare `pytest` (or the
  affected packages) so `pyproject.toml` testpaths apply. CI runs bare
  `pytest --cov-fail-under=75`.
- **Every new package needs `__init__.py`, or full-suite collection breaks
  with a shadowed top-level `tests` package.** If `<pkg>/tests/__init__.py`
  exists but `<pkg>/__init__.py` is missing, pytest maps the new test modules
  to the top-level package name `tests` (inserting `<pkg>/` on `sys.path`),
  which collides with the repo-root `tests` package. Depending on import
  order you get `ModuleNotFoundError: No module named 'tests.<x>'` for either
  the new package's files or the unrelated root `tests/` files.
  Package-scoped runs (`pytest <pkg>/tests`) and the shared/master_driver
  suites all pass green while the bare full-suite run fails at collection, so
  the final gate MUST be a bare full-suite `pytest` run. The same shadowing
  also produces mypy "Source file found twice under different module names"
  collisions; verify the package resolves as a regular package (it imports
  with `__file__` pointing at `<pkg>/__init__.py`, not a namespace path).

- **Pre-flight import check needs a Tk root.** Do not call
  `preflight.guard_or_exit()` bare — it requires a `root` positional argument
  for the dialog. For a non-GUI import sanity check use a direct package
  import (`python -c "import <pkg>.<mod>"`) or the compile gate
  (`python -m compileall -q -f .`).

- **pwsh: `\"` is not an escape inside double-quoted strings — and `rg` may
  not be installed; run secret scans as `git grep --cached`.** Any pattern
  containing `["']` or a bare `\"` is a ParserError in a PS double-quoted
  string (PowerShell only honours backtick escapes, so the quote *terminates*
  the string and the scan never runs). Build patterns in single-quoted
  variables (double any inner single quote as `''`), or split the `["']`
  class into separate double-quote and single-quote greps. After
  `git add -A`, prefer `git grep --cached -n -i -E -I -e '<pattern>'` over
  `rg` — it scans exactly the files about to be committed, the precise
  "blocker" gate. This is what caught and excluded the live Fanart.tv keys in
  P1 (`PLAN_audit_priority_actions.md`, Decision D11).

- **pwsh has no heredoc: long commit messages need `git commit -F <file>`.**
  `git commit -F - <<'MSG'` is bash-only and dies with `ParserError: Missing
  file specification after redirection operator`, wasting a round trip on a
  message this repo's style expects to be long (every audit item records a
  multi-paragraph body). Write the message to a file with the write tool, then
  `git commit -F "<path>"`, and delete the scratch file afterwards.

- **A secret scan is only as good as its alternation: match `*_key`/`*_secret`
  suffixes, 32-hex literals and 44+-char base64, not just
  `api[_-]?key|secret|passwd|password|token`.** The audit regex sailed past
  `album_art_sync/*/album_art_config.json`'s `"app_key"`/`"client_key"`
  Fanart.tv keys — neither token is in the alternation and a 32-hex value is
  not matched. Supplemental scans that caught them:
  ```
  git grep --cached -n -i -E -I -e '[-_](key|secret|token|password|passwd|client)[^ ]*[=:][^A-Za-z0-9_][A-Za-z0-9+/=_-]{10,}'
  git grep --cached -n -i -E -I -e '"[a-f0-9]{32}"'
  git grep --cached -n -E -I -e '"[A-Za-z0-9+/]{44,}={0,2}"'
  git grep --cached -n -E -I -e '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
  ```
  The PEM pattern must be passed with `-e` (it starts with `-`). Files named
  `*_config.json`/`.key` siblings belong in `.gitignore` before any commit.

- **`compileall -x '(^|/)(\.venv|\.git)/'` does not exclude `.venv` on
  Windows.** The `-x` regexp uses forward-slash separators but Windows paths
  use `\`, so the exclusion silently fails and third-party `site-packages`
  modules get byte-compiled (harmless pre-existing `SyntaxWarning`s, e.g.
  pydub). Keep the documented command as-is; the warnings are noise, not
  failures.

- **A scripted bulk edit that moves code between indentation levels produces
  valid-Python-wrong code — the compile gate cannot catch it.** Iteration-5
  C2's extraction script de-indented the tail of the inherited
  `process_batch()` (the `results.append`/progress block slipped out of the
  `for f in futures:` loop) while compile/ruff/mypy all stayed green; only
  four pre-existing `TestProcessBatch` behaviour tests caught it
  (`len(results) == 1` for a 3-file batch). After any scripted edit, re-diff
  the touched lines and rely on behaviour-lock tests — never on the compile
  gate alone. (Second scripted-edit regression after the P5
  parenthesized-import insertion.)

- **A scripted edit that reads with the platform default encoding and writes
  UTF-8 silently mangles every non-ASCII byte it touched.** On Windows
  `open(path)` decodes as cp1252, so an em dash read as three characters
  (`â€”`) and re-emitted as UTF-8 was a *different* three characters; the
  result compiled, passed ruff/mypy, and broke six display tests that read as
  logic errors (iteration-8 E3). The same mechanism ate `` `a `` as `\x07`
  (BEL) inside `CHANGELOG.md`, committing an invisible control character into
  the docs. Always pass `encoding="utf-8"` on **both** the read and the write,
  and after any scripted edit assert the file is control-character clean
  (`[c for c in text if ord(c) < 32 and c not in "\r\n\t"]` is empty) before
  running the gates. This is the encoding sibling of the `ruff format`
  `line-ending = "auto"` rule in the global §5: both are byte-level damage
  that no content-level gate reports.

- **A scan reusing an opposite-purpose exclusion set silently scans zero
  files and passes vacuously.** Iteration-5 G1's skip-attribution walk
  reused `_EXCLUDED_DIRS` (which contains `tests`) while needing the exact
  opposite, so every candidate was dropped before matching — it would have
  passed vacuously forever. When a scan reuses a shared exclusion list,
  assert the result set is non-empty so the empty scan fails loudly.

- **Simulate platforms by patching `sys.platform` only — never `os.name`.**
  The declared platform branches key on `sys.platform`; patching `os.name`
  instead (iteration-5 G1) makes `pathlib.Path()` construct a `PosixPath` on
  a Windows host, so the test measures a Windows/POSIX hybrid that exists on
  no real system. The distinction is pinned by regression test via the
  `PosixPath` consequence, not by assertion on the patch target.

- **A verification harness that cannot fail is worse than none.** Iteration-5
  G2's break-and-restore scratch check typed its pytest argument `[string]`
  in PowerShell, so the array collapsed and pytest received a single
  character; the usage message's `ERROR` line then matched the verdict
  predicate and reported "LOCK FIRED" for a run that executed no test. Type
  array arguments `[string[]]`, key break-and-restore verdicts on a
  `FAILED`/`ERROR` *test* line (never on the literal word in any output),
  confirm the summary line shows tests actually ran, and SHA-256-verify
  every restore so the harness cannot leave a mutated file behind.

- **`importlib.reload()` does not undo in-place mutations of module-level
  dicts.** `set_active_palette()` mutates the module-level `PALETTES` dict in
  place, so a test's reload-based "restore" silently did not restore and the
  pair became order-dependent — surfacing only on the *second* full-suite
  run (iteration-5 Stage 5). Never rely on reload to restore state another
  test mutates in place: capture expected state before any test can pollute
  it, and add a deterministic pollution regression when a test mutates
  module-level globals.

- **Do not pin one dependency version's branch message at a consumer
  boundary.** Iteration-5 B1's corrupt-file pool test pinned the
  empty-decode branch's "too short" message at the batch level; uv.lock
  resolves librosa 1.0 on py≥3.12 (which removed the audioread fallback), so
  the same corrupt container took the decoder-raised branch and the test
  failed at HEAD. Where a dependency's version changes which branch runs,
  assert the neutral contract (status=error, non-empty message, batch
  completes) at the consumer, and pin each branch text in the loader's own
  tests instead.

- **A `str`-mixin enum renders as `Enum.MEMBER` in an f-string, so a
  "typing-only" enum refactor silently rewrites every display string.**
  `class FingerprintStatus(str, Enum)` makes `status == "MATCHED"`,
  `status in {...}` and `json.dumps(status)` all behave as the plain string,
  while `f"{status}"` / `str(status)` / `format(status)` produce
  `"FingerprintStatus.MATCHED"` (verified on 3.14: only `StrEnum` and the
  `__format__` fix restore value formatting). The breakage is confined to
  *interpolation sites*, and they live outside the refactored module —
  iteration-8 E3 replaced eight status literals in
  `audio_fingerprinter/core/file_processor.py` while
  `audio_fingerprinter/app.py` was still doing
  `f"[{result.status}] {result.filename}"` into the results listbox, which
  would have shipped `FingerprintStatus.MATCHED` to the UI. Rule: when a
  string-valued field becomes an enum, (a) `grep` every interpolation of that
  field **across the whole package**, not just the edited module; (b) route
  each display through one `.value`-returning helper (`models.status_text()`)
  and serialise dict/JSON payloads through it too; (c) keep the member values
  byte-identical to the strings they replace, and pin that with a test
  asserting the rendered line for *every* member — the existing
  display-string tests pin only the members they happened to cover.

## Master Driver Card Naming (Mandatory Convention)

`enrich_tab.py` and `utilities_window.py` lazy-import each tool's card as
`importlib.import_module(f"master_driver.ui.cards.{tool_id}_card")` and call
`build(parent, state)`. The card file name MUST be exactly `{tool_id}_card.py`
matching the tool's registered `id` in `audio_suite_shared/tool_plugin.py`.

A file whose name merely *resembles* the id (e.g. `fingerprint_card.py` for
id `fingerprinter`) is silently never found — the only symptom is a
`No card UI for tool '<id>'` warning in the console. Verify the card file
name against the manifest id before creating it.

## Registering a New Tool (Checklist)

Every new tool must be wired into ALL of the following before it is complete.
Missing any one produces a silent runtime degradation (a missing card only
logs; a broken Help button warns):

1. **Tool manifest** — `audio_suite_shared/tool_plugin.py`: `ToolManifest`
   entry.
   The `id` is the single source of truth used everywhere below.
2. **Master Driver card** — `master_driver/ui/cards/{tool_id}_card.py` named
   exactly `{tool_id}_card.py` (see "Master Driver Card Naming" above).
3. **CLI command** — tool's `click` command + import in
   `audio_suite_shared/cli_app.py` (verify flag names against the CLI, not
   an assumed design).
4. **Arg builder** — `master_driver/runner/arg_builder.py`: entry per tool.
   Enrich tools MUST emit `[path, mode_flag, start_flag, end_flag]` —
   `test_runner.py` `TestBuildEnrichArgs` asserts it for EVERY enrich entry.
   `lambda: []` breaks those tests; fix the builder, never weaken the tests.
5. **Batch orchestration** — `master_driver/batch_orchestrator.py`
   `DEPENDENCY_GRAPH` ordering.
6. **Driver state** — `master_driver/state/app_state.py` module toggle key
   (+ `master_driver/tests/test_app_state.py` expected keys).
7. **Pyw launcher** — top-level `<Tool_Name>.pyw` with the optional pre-flight
   guard call.
8. **User guide** — generator in
   `user_guides/individual_programs/<module_dir>/generate_guide.py`, run to
   produce the `.docx`, and register the filename → folder in
   `audio_suite_shared/platform_utils.py` `guide_to_program`.
9. **Test registration** — `pyproject.toml`: `<module>/tests` in `testpaths`
   + package in coverage `source`; unique test-dir basename or `__init__.py`
   (see the "Every new package needs `__init__.py`" gotcha).
10. **Tests** — new `<module>/tests/` suite; update expected-set tests
    (`test_tool_plugin.py`, `test_app_state.py`, `test_runner.py`) in lockstep.

Verification: a per-package `pytest <pkg>/tests` is NOT sufficient proof —
integration tests in `master_driver/tests/` and `audio_suite_shared/tests/`
catch registration mistakes a package's own tests cannot see. The final gate
MUST be a bare full-suite `pytest` run.

## Sprint 2 (Iteration 8) lessons learned

- **UI builder signatures are the source of truth.** When tab builders have specific parameter orders/types (e.g. results_tab.build(parent, on_open_log, on_open_folder, on_play_original=None, on_play_result=None); processing_tab.build(parent, slot_vars=None)), never infer extra args (e.g. _select_tab_setup or slot_vars into results builder). Mismatched positional args cause AttributeError/arg-type in real-app construction tests; read the target UI module signature and mirror it exactly.
- **Fix signatures before adding casts.** If introducing mypy casts, ensure call chains are correct first; casts can mask runtime construction failures.
- **Unused scaffold must not remain.** If a shared base has 0 production references and integration is incomplete, either integrate properly or remove it (minimal scope). Leaving unused scaffold adds dead code.
- **AST lock for deleted public APIs.** When deleting a subsystem with public names, add an AST-based test asserting those names are absent to prevent accidental reintroduction.
- **Clean up alongside deletion.** Removing dead code should also remove orphaned type aliases/docstrings in the same change scope.
