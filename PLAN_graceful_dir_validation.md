# PLAN — Graceful Directory-Validation Failure Across AudioSuite-Pro

**Status legend:** `[ ]` pending · `[~]` in progress · `[x]` done
**Working directory:** `D:\Users\wilte\Desktop\AudioSuite-Pro`
**Test runner:** `.venv\Scripts\python.exe -m pytest` (repo root)
**Rule:** every phase updates its tests in lockstep; zero test failures before a phase is marked done.

---

## Background (root-cause chain of the reported failure)

Dry run of Metadata Scrubber via Master Driver with non-existent dir `D:/test` produced:

1. `master_driver/tool_launcher.py:149 / :249 / :53` — launch gates only check the directory
   field is **non-empty**, never that it exists.
2. Child `Metadata_Scrubber.pyw` → `metadata_scrubber/utils/cli_args.py:70-72` — validation
   detects the bad folder and builds error strings, then **discards them**, raising bare
   `SystemExit(1)`.
3. `audio_suite_shared/launcher.py:31-32` — catches SystemExit, logs
   `"CLI argument parsing failed: %s"` → prints useless `1`.
4. `audio_suite_shared/secure_subprocess.py` (`run_secure_subprocess`, default `check=True`)
   logs full traceback via `exc_info=True`, re-raises `CalledProcessError`.
5. `master_driver/runner/module_runner.py:226-255` (`_run_modules_sequential`) does **not**
   catch `CalledProcessError` (only SubprocessSecurityError/PermissionError/FileNotFoundError/
   OSError) → daemon thread dies → raw traceback, no dialog, Run button stuck on "PROCESSING…".
   Parallel path is protected by broad `except Exception` at `batch_orchestrator.py:421`;
   **sequential is the default** (`state/app_state.py:29`: `parallel_var = tk.BooleanVar(value=False)`).

Graceful per-module handling already exists at `module_runner.py:236-241`
("Module exited with error code N" dialog) but is bypassed because the exception raises first.

---

## Phase 1 — Master Driver preventive validation  **[x] DONE**

**File: `master_driver/tool_launcher.py`**

1. Add `import os` (between `import logging` and `import threading`).
2. `launch_refinery` — immediately after the "No Source Folder" empty-check, before
   `stages_active`:
   ```python
   if not os.path.isdir(source):
       ui_common.show_message(
           root,
           "Directory Not Found",
           f"The selected folder does not exist:\n\n{source}\n\n"
           "Please select a valid source folder.",
           icon="\u26a0",
           icon_color="#d97706",
       )
       return
   ```
3. `launch_enrich` — after the "No Directory" empty-check:
   ```python
   if not os.path.isdir(state.dir_path.get()):
       ui_common.show_message(
           root,
           "Directory Not Found",
           f"The selected directory does not exist:\n\n{state.dir_path.get()}\n\n"
           "Please select a valid directory.",
           icon="\u26a0",
           icon_color="#d97706",
       )
       return
   ```
4. `launch_utility` — after the existing "No Directory" / "Nothing Selected" blocks:
   same popup as enrich, guarded by `if needs_dir and not os.path.isdir(state.dir_path.get()):`.

**Tests: `master_driver/tests/test_tool_launcher.py`** (conventions: real `AppState()` on
session hidden Tk root from conftest; `launch_mocks` fixture patches threading.Thread,
`suite_config.save_last_directory`, `ui_common.show_message`)

- [x] FIX EXISTING BREAKAGE: `test_folder_tool_with_dir_launches` sets `dir_path` to fake
  `"D:/Music"` → switched to `str(tmp_path)`.
- [x] Add class `TestDirectoryExistenceValidation`:
  - utility: converter toggle on + nonexistent dir → title "Directory Not Found", no thread.
  - enrich: nonexistent dir → same; valid `tmp_path` → thread called once, no popup.
  - refinery: `state.refinery_source` = nonexistent path → popup, no thread
    (pass `MagicMock()` as config — safe, gate returns before stages check).
- [x] Imports added: `launch_enrich`, `launch_refinery` from `master_driver.tool_launcher`.

**Verify:** ruff check+format on both files; pytest `master_driver/tests/test_tool_launcher.py`;
then broader suite.

**Phase 1 verification results (2026-08-22):** ruff clean · targeted 11/11 passed ·
full suite **4228 passed / 5 skipped / 0 failures** · mypy clean on both files.
Note: repo-wide coverage gate reports 65.49% < fail-under=75 — pre-existing baseline
shortfall across UI modules (not a test failure; unchanged by this phase).

---

## Phase 2 — Defensive subprocess handling  **[x] DONE**

**File: `audio_suite_shared/secure_subprocess.py`**
- [x] `run_python_script` (~line 400): delegate with `kwargs.setdefault("check", False)` so
  failures return a `CompletedProcess` instead of raising.
  - DO NOT change `run_secure_subprocess`'s own default (`cd_ripper/core/disc.py:85`,
    `metadata_resolver.py:115`, `platform_utils.py` depend on current behaviour). ✓ respected
  - Use `setdefault` so an explicit `check=True` caller (e.g.
    `tests/test_secure_subprocess.py:316`) still works without duplicate-kwarg TypeError. ✓
- [x] Docstring Returns section updated accordingly.

**File: `master_driver/runner/module_runner.py`**
- [x] Added `import subprocess`; narrow `except subprocess.CalledProcessError` branch in
  `_run_modules_sequential` → on_error("Module Error", ...) + failed_steps.append(tool_id).

**Tests:**
- [x] `audio_suite_shared/tests/test_secure_subprocess.py`: run_python_script returns
  CompletedProcess(returncode=3) on child failure; explicit check=True still raises.
- [x] `master_driver/tests/test_runner.py`: CalledProcessError → on_error called;
  batch continues (second module runs, on_complete fires with executed=1).

**Phase 2 verification results (2026-08-22):** ruff clean · targeted 181/181 passed ·
full suite **4232 passed / 5 skipped / 0 failures** · mypy clean.

---

## Phase 3 — Child tools: stop discarding validation messages (10 files)  **[x] DONE**

Replicate `mood_tagger/utils/cli_args.py:52-55` pattern in each `parse()`:
```python
errors = validate_args(args)
if errors:
    for error in errors:
        print(f"<Display Name>: {error}", file=sys.stderr)
    raise SystemExit(1)
```

| # | File (all `<pkg>/utils/cli_args.py`) | errors→SystemExit line | Display name |
|---|---|---|---|
| 1 | metadata_scrubber | 70 | Metadata Scrubber |
| 2 | genre_sync | 50 | Genre Sync |
| 3 | key_detector | 80 | Key Detector |
| 4 | album_art_sync | 95 | Album Art Sync |
| 5 | asx_extractor | 97 | ASX Playlist Extractor |
| 6 | album_genre_tagger | 103 | Album Genre Tagger |
| 7 | audio_normalizer | 96 | Audio Normalizer |
| 8 | replaygain_analyzer | 83 | ReplayGain Analyzer |
| 9 | music_format_converter | 102 | Music Format Converter |
| 10 | silence_trimmer | 154 | Silence Trimmer |

Notes: add `import sys` where missing; verify display names for audio_normalizer /
silence_trimmer against registry manifests during execution; asx_extractor uses
`args.directory`; music_format_converter also validates `output_dir` (same loop covers it).

**Tests (lockstep):**
- [x] Update existing: metadata_scrubber, genre_sync, album_genre_tagger, asx_extractor,
  audio_normalizer, music_format_converter tests/test_cli_args.py — added
  `TestParseInvalidFolderPath` mirroring mood_tagger's (SystemExit raised; stderr contains
  reason + path + tool prefix; stdout empty). music_format_converter also covers
  invalid `--output-dir` on stderr.
- [x] Created new `<pkg>/tests/test_cli_args.py`: key_detector, album_art_sync,
  replaygain_analyzer, silence_trimmer (all four already had tests/ with `__init__.py`
  + conftest.py — no scaffolding needed). Each includes validate_args coverage,
  parse happy-path coverage, and the regression class.
- Execution notes: key_detector uses positional handshake slots (argv[3]/[4]/[5]) and
  default duration 90 (not flag-scan / 120); album_art_sync requires folder strictly at
  argv[1]. Tests written against actual behavior.

---

## Phase 4 — Tempo Analyzer escaping exception + launcher hardening  **[x] DONE**

- Move `CLIValidationError(ValueError)` into `audio_suite_shared/cli_dataclasses.py`;
  `tempo_analyzer/utils/cli_args.py:22` imports/re-exports it (existing imports/tests keep working).
- `audio_suite_shared/launcher.py parse_cli_args`: add
  `except CLIValidationError as exc:` → print reason to stderr, log via logger.error,
  `sys.exit(1)` (keep existing SystemExit branch).
- Tests: new `audio_suite_shared/tests/test_launcher.py` (passthrough success;
  SystemExit → exit 1; CLIValidationError → stderr message + exit 1);
  update `tempo_analyzer/tests/test_cli_args.py` if exception identity assertions exist.
- [x] All done. CLIValidationError moved to cli_dataclasses (tempo_analyzer re-imports it,
  identity test added); launcher catches CLIValidationError → stderr + logger.error +
  exit(1) while letting generic ValueError escape; test_launcher.py has 12 tests incl.
  tempo_analyzer end-to-end via launcher; test_cli_dataclasses.py gained
  TestCLIValidationError. ruff/mypy clean; full suite 4380 passed / 5 skipped / 0 failed.

---

## Phase 5 — Add missing folder validation (3 tools)  **[x] DONE**

Use shared `validate_folder_path()` from `audio_suite_shared/cli_dataclasses.py:69`
(empty string stays legal → returns []):

- `bpm_analyzer/utils/cli_args.py` — call in parse(), print+SystemExit(1) pattern.
- `album_art_normalizer/utils/cli_args.py` — same.
- `pop_click_remover/utils/cli_args.py` — fold folder errors into its existing post-parse
  `errors` list → `parser.error("\n".join(errors))` (argparse prints + exits 2 gracefully).
- Tests: update bpm_analyzer & pop_click_remover tests/test_cli_args.py; create
  album_art_normalizer tests/test_cli_args.py.
- [x] All done. bpm_analyzer + album_art_normalizer use shared validate_folder_path with
  "BPM Analyzer:"/"Album Art Normalizer:" stderr prefix + SystemExit(1); pop_click_remover
  folds folder errors into its existing errors list → parser.error() (exit 2). Fake-path
  tests in bpm_analyzer (/my/music etc.) and pop_click_remover (/music/albums) replaced
  with tmp_path; pop_click_remover's unknown-args test updated (argparse captures a bare
  injected token as folder_path, now correctly rejected). New album_art_normalizer tests/
  __init__.py + test_cli_args.py. ruff/mypy clean; full suite 4405 passed / 5 skipped /
  0 failed. bandit: 0 HIGH, all 17 MEDIUM pre-existing (none in touched files).

---

## Gotchas / decisions log

- Launcher currently only catches `SystemExit` — CLIValidationError escapes as ValueError.
- Sequential runner is the DEFAULT path (parallel_var=False); it is the unprotected one.
- Existing test `test_folder_tool_with_dir_launches` uses fake `"D:/Music"` (Phase 1 fix).
- Empty folder_path must remain legal everywhere (double-click GUI-only launches).
- Do not change `run_secure_subprocess(check=True)` global default — targeted callers only.

## Final verification pipeline (after last phase)

```
.venv\Scripts\python.exe -m ruff check --fix .
.venv\Scripts\python.exe -m ruff format .
.venv\Scripts\python.exe -m mypy . --strict   (scoped fallback if repo-wide too noisy)
.venv\Scripts\python.exe -m pytest -q         (full suite, zero failures)
bandit on touched packages if available
```

Docs audit: changes are error-messaging only — confirm user guides make no claims about raw
tracebacks/exit codes before finishing.

## Progress log

| Date | Phase | Note |
|---|---|---|
| 2026-08-22 | — | Plan created after full codebase survey. |
| 2026-08-22 | 1 | DONE: isdir gates in launch_refinery/enrich/utility; test fix + 4 new tests; ruff/mypy clean; full suite 4228 passed / 0 failed. Next: Phase 2. |
| 2026-08-22 | 2 | DONE: run_python_script check=False default (setdefault); CalledProcessError branch in module_runner; 4 new tests; ruff/mypy clean; full suite 4232 passed / 0 failed. Next: Phase 3. |
| 2026-08-22 | 3 | DONE: all 10 cli_args.py print prefixed errors to stderr before SystemExit(1); TestParseInvalidFolderPath added/created across 10 test files; ruff/mypy clean; targeted 291 passed; full suite 4365 passed / 5 skipped / 0 failed. Next: Phase 4. |
| 2026-08-22 | 4 | DONE: CLIValidationError relocated to cli_dataclasses (tempo_analyzer re-imports, identity test); launcher catches it → stderr + log + exit(1); generic ValueError still escapes; test_launcher.py (12 tests) + TestCLIValidationError; ruff/mypy clean; full suite 4380 passed / 5 skipped / 0 failed. Next: Phase 5. |
| 2026-08-22 | 5 | DONE: folder validation added to bpm_analyzer, album_art_normalizer (print+exit 1) and pop_click_remover (parser.error, exit 2); tests updated/created; ruff clean, scoped mypy clean, bandit no new findings; final pipeline run; full suite 4405 passed / 5 skipped / 0 failed. Docs audited — guides make no claims about launch failures/tracebacks/exit codes → no updates required. ALL PHASES COMPLETE. |
