# PLAN — Iteration 9: Go-Live Remediation

**Status:** `[ ]` open — governs all work until every item is `[x]` and the
completion log is closed.
**Base state:** HEAD `6dc03f3` (plan-only commit) plus the untracked audit
deliverable `AUDIT_2026-10-06_suite_report.md`.
**Governing scope (confirmed with the user):** remediation of the audit's
findings only — H1–H2, M1–M11, L1–L5, plus the report's §7 recommended next
actions. Enhancement suggestions (report §6, Tiers 1–3) are **out of scope**
and are listed in the deferred-backlog section. No feature work.

This plan is self-contained: every item states the exact files, the exact
change, the tests to add or update in lockstep, the guide/doc updates (where
user-visible), and the acceptance commands. Work proceeds sprint by sprint;
the full six-command gate is re-run and recorded after each sprint.

---

## 1. Decisions (decision log)

| D | Decision | Rationale |
|---|---|---|
| D1 | Scope = the 18 findings (H1–H2, M1–M11, L1–L5) + report §7 actions. | User-confirmed. §6 suggestions deferred (see backlog). |
| D2 | PyInstaller is the only dependency approved for future use; it is **not** installed or referenced by this plan (unused under findings-only scope). Demucs/torch remain deferred. | User-confirmed approval; nothing in the 18 findings needs it. |
| D3 | Verified measurement corrections to the report are adopted in preference to the report's numbers: `file_processor_base.py` = **1005 lines** (report said 1,484); M6 naming violations = **35 files** under the canonical rule (report said 43 — its count included the root `tests/` dir, which this plan exempts by scope); L4's pyproject reality = `exclude` **contains** `"^utilities/"` (`pyproject.toml:105`) and coverage `omit` contains `"utilities/*"` (`:277`) — i.e. utilities is excluded from both gates, whatever the report's prose says. | Zero-assumption rule: re-measured at HEAD by direct command. |
| D4 | M4 is extended to **all three** bypassing click CLIs, not the two the report named: `audio_normalizer/cli.py:24`, `audio_refinery/cli.py:96-101`, and `replaygain_analyzer/cli.py:25` (verified: none of the three imports `validate_target_lufs`). LUFS default alignment: `NormalizerArgs.target_lufs` `-16.0 → -14.0` (GUI var, click default and the user guide all say −14); replaygain click `default=-14.0 → -16.0` (GUI var, argparse and an existing test pin −16); refinery already consistent at −16. | Empirical: the GUI is the primary interface and the normalizer guide explicitly documents "The app default is −14.0" (`generate_guide.py:148`), so the argparse default of −16 silently rewrites the GUI's −14 whenever CLI args are applied. |
| D5 | M7 is executed as **scoped extraction only**: the shared discovery/empty-check/tracker/completion/cleanup blocks become parameterised helpers; the four executor loops stay separate with KEEP-IN-SYNC comments. The full single-runner unification (report suggestion #12) is deferred. | Minimal-diff; the executor loops differ materially (thread/process/pool/in-place) and unifying them is a redesign, not a defect fix. |
| D6 | M6 is executed as: merge/rename the 5 clear duplicates, then enforce the naming rule with a new allowlist-based lock test (the approach the report itself suggests, §6 item 11). The 30 remaining non-mirroring files are allowlisted with per-entry rationale; root `tests/` is exempt by scope (its files are cross-cutting by design). | AGENTS already tolerates deliberate composites; an enforceable lock + frozen allowlist beats a 30-file rename churn with no behaviour benefit. |
| D7 | M8 residual duplication after the shared-preset extraction (`_build_options`, scan/run flow) is documented in this plan's decision log as an accepted residual, not executed. | `_build_options` builds genuinely different widgets per tool; forcing a shared builder would trade two clear files for one flag-riddled one. |
| D8 | L4 is executed in full: remove `"^utilities/"` from mypy `exclude` and `"utilities/*"` from coverage `omit` (adding `utilities` to `source`), then annotate the 7 utility scripts to satisfy bare `mypy .` — no `# type: ignore`, no re-exclusion. | The finding exists precisely because these bulk-mutation scripts sit outside both gates; a coverage-only half-fix would leave the finding open. |
| D9 | The logging guide is delivered as a **new generator** `user_guides/suite_overview/generate_logging_system_guide.py` which regenerates the existing `LOGGING_SYSTEM_GUIDE.docx`. It is NOT registered in `guide_to_program`. | Generator-is-source-of-truth policy; the name avoids both hygiene bans (`*_Logging_Guide.docx`, `generate_logging_guide.py` — verified `tests/test_user_guide_hygiene.py:149,158`), and `test_no_logging_guide_is_registered` (`:225`) forbids any "Logging" entry in the Help registry. |
| D10 | H1 is fixed by formatting the file and **appending a dated correction note** to the I4 completion-log row (`PLAN_iteration8_remediation.md:1748`); the historical row is not rewritten. | Plan-governance convention: completion logs are append-only corrections, never retro-edited. |
| D11 | After each sprint the full gate is run via the new `utilities/run_gate.ps1` (created in S1); its output is pasted into that sprint's completion-log row. | H1's root cause was a gate result that did not reproduce; one reproducible wrapper is the process fix. |
| D12 | Bandit's verdict in both gate runners — the CI `security` job (`.github/workflows/ci.yml`) and `utilities/run_gate.ps1` step 5 — is judged by bandit's **severity block** (0 High / 0 Medium), never the raw exit code. bandit 1.9.4 exits 1 whenever ANY finding survives its default LOW/LOW filter, which the 41 documented Low findings trigger on every run; exit ≥ 2 (tool error) and an unparseable severity section always fail. The §3.1 bandit command itself stays byte-identical in both runners. | AGENTS §6.3 defines the healthy result as 0 High / 0 Medium and warns that the confidence block is a different metric; a raw-exit-code gate can never pass at HEAD (verified empirically), so the CI security job was red by construction. Both verdicts verified by controls: real output (confidence 23/18 not read) passes, injected severity High=1/Medium=2 fails, missing severity block fails loudly, tool error exit 2 fails. |
| D13 | Two defects found while executing S5 are fixed in the same change — **user-approved scope extension** ("fix both now"): (a) `audio_suite_shared/tests/test_app_bootstrap.py::_clear_audio_suite_handlers` cleared only the `audio_suite` logger's handler list, leaving G4.2's shared `RotatingFileHandler` open on every first-party package logger, so each later `configure_logging` call added a **second** open handle on `logs/audio_suite.log` — the first rollover then failed with a Windows rename PermissionError and the handler's `handleError` wrote `--- Logging error ---` tracebacks into Click's captured stderr (root cause of the 3 intermittently failing CLI tests in full-suite runs); (b) `library_stats/cli.py` never closed the `LibraryCache` it created for `--incremental`/`--refresh`, leaking a SQLite connection for the process lifetime. | AGENTS: defects are fixed when discovered, never deferred. (a) actively corrupts test evidence (order-dependent flakes that a green run cannot see); (b) is a real resource leak on a shipped CLI path. Both carry lockstep regression tests with SHA-256-verified negative controls (evidence in the G5.3 row). |
| D14 | G6.3 defect: `cd_ripper/ui/drive_config_panel.py` `_run_c2_diagnostic` except tuple was `(OSError, RuntimeError)` — `AudioIOError`'s MRO → `AudioSuiteError → Exception` meant a real `AudioIOError` escaped the except and crashed the diagnostic button. Fixed: tuple extended to `(AudioSuiteError, OSError, RuntimeError)` + `AudioSuiteError` import added. Regression test `test_audio_io_error_is_handled` asserts `showerror` fires and no exception propagates. | AGENTS: defects are fixed when discovered, never deferred. A crash on a real runtime exception is a shipped-path defect, not a test-only gap. |

---

## 2. Traceability matrix

| Report finding / §7 action | Plan item | Sprint |
|---|---|---|
| H1 — ruff format gate fails; I4 evidence not reproducible (§7.1) | G1.1, G1.2, G1.3 | S1 |
| H2 — suite_config lost-update still reproduces (§7.2) | G2.1 | S2 |
| M4 — click CLIs bypass `validate_target_lufs` (+ D4 discovery) | G2.2, G2.3 | S2 |
| M5 — metadata-scrubber live-save never tested (§7.4) | G2.4 | S2 |
| M2 — CLI reference defaults opposite of reality (§7.3) | G3.1 | S3 |
| M3 — CHANGELOG omits shipped iteration-8 functionality | G3.2 | S3 |
| M9 — README stale mypy metric | G3.3 | S3 |
| M1 — tool-package loggers never reach the suite log | G4.1–G4.5 | S4 |
| M6 — test-file naming violated in 43 files (report count; 35 in-scope under the canonical rule, per D3) | G5.1, G5.2 | S5 |
| L1 — 8 × ResourceWarning `tomllib.load(open(...))` | G5.3 | S5 |
| L5 — test-suite hygiene (warnings / skip reasons) | G5.4 | S5 |
| M11 — coverage pockets in newer tool UIs | G6.1–G6.6 | S6 |
| M7 — four copies of the batch skeleton | G7.1 | S7 |
| M8 — bpm/lyrics near-clones | G7.2 | S7 |
| L3 — long business functions | G7.3, G7.4 | S7 |
| M10 — undo dialog names ≠ manifest | G8.1, G8.2 | S8 |
| L2 — `audio_suite_config.json.lock` not gitignored | G8.3 | S8 |
| L4 — utilities outside mypy + coverage gates | G8.4 | S8 |
| §7 final — full gate + record command output | G9.1–G9.5 | S9 |

---

## 3. Global Definition of Done

### 3.1 Gate (six commands, after every sprint)

Run via the S1 wrapper (identical to the `CONTRIBUTING.md` block that
`tests/test_readme.py::gate_commands` parses — **do not add a 7th line inside
that pwsh fence**):

```powershell
utilities\run_gate.ps1
```

which executes, stopping at the first failure:

1. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'`
2. `python -m ruff check .`
3. `python -m ruff format --check .`
4. `python -m mypy .`
5. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
6. `python -m pytest -q`

Baseline at HEAD (audit §2): 8493 passed, 3 skipped, 30 deselected, 8 warnings,
coverage 89.39%, mypy 0 issues / 461 files, ruff check clean, bandit 0 High /
0 Medium. Targets for S9: pytest green with **0 warnings**, coverage ≥ 88.0
(allowing small dilution from L4's newly-measured utilities), mypy 0, bandit
0 High / 0 Medium, `ruff format --check` green.

Notes:
- Coverage numbers are only valid when captured from the bare run in the same
  shell block (AGENTS §6.10). Earlier scoped `--co` runs left `.coverage`
  showing 24.76% — always regenerate from a bare `python -m pytest -q`.
- Per-sprint targeted coverage measurements (S6) use a **separate**
  `COVERAGE_FILE` so they cannot clobber the shared data file.

### 3.2 Guide Update Protocol (applies whenever user-visible behaviour changes)

1. Edit the **generator** only — `user_guides/individual_programs/<module>/generate_guide.py`
   (or `user_guides/suite_overview/generate_presentation.py`, or the new
   `generate_logging_system_guide.py`). Never hand-edit a `.docx`/`.pptx`.
2. Run the generator from its own directory: `python generate_guide.py`
   (workdir = the generator's folder).
3. `python -m pytest tests/test_user_guide_hygiene.py -q` must stay green
   (locks: every tracked guide has a generator; no `*_Logging_Guide.docx`; no
   `generate_logging_guide.py`; `guide_to_program` entries exist and none
   contains "Logging").
4. `.md` references (`README.md`, `CONTRIBUTING.md`,
   `user_guides/reference/CLI_Commands_Reference.md`) are edited directly and
   covered by their own tests.
5. Each sprint lists its guide/doc touchpoints explicitly (or "none" with the
   reason: internal/test-only change).

### 3.3 CHANGELOG rule (M3's discipline, applied per sprint)

Every **user-visible** change gets a bullet under `## [Unreleased]` in the
matching Keep-a-Changelog subsection **in the sprint that ships it**. Test-only,
refactor-only and internal-process changes get no bullet. The hygiene lock
(`tests/test_user_guide_hygiene.py::TestChangelogHygiene`) must stay green.

### 3.4 Test conventions

- One test file per source module (`AGENTS.md` §Test File Naming); new lock
  tests live in root `tests/` and are exempt from the naming rule (see G5.2).
- Every new/changed production behaviour gets a test that asserts the
  **positive contract**, per AGENTS §7 — a negative `assert_not_called` is
  never the only assertion about a side-effecting branch (swept in G2.4).
- New root `tests/*.py` files are covered by mypy only via the bare gate's
  excludes (root `tests/` is in mypy `exclude`) — they must still pass ruff.
- Strict typing: no `# type: ignore` (carve-outs only via existing pyproject
  overrides).

---

## Sprint S1 — Gate integrity (H1)

**Findings closed:** H1. **Guides/CHANGELOG:** none (internal process change).

### G1.1 — Make the mandated format gate reproduce

- **Change:** `python -m ruff format user_guides/individual_programs/lyrics_manager/generate_guide.py`
  (diff is quote-style only: `"Unknown"` → `'Unknown'`, per report H1).
- **Tests:** none new.
- **Acceptance:** `python -m ruff format --check .` →
  `794 files already formatted` (exit 0), then steps 1–6 of the gate pass.

### G1.2 — Correct the I4 completion-log record (append, do not rewrite)

- **Change:** in `PLAN_iteration8_remediation.md`, append to the I4 row (line
  ~1748) a dated correction note: the recorded `794 files formatted` did not
  reproduce at HEAD `6dc03f3` (audit 2026-10-06: `793 already formatted + 1
  would be reformatted`, `lyrics_manager/generate_guide.py`); the file is
  re-formatted by iteration-9 G1.1 and the gate reproduces again. Keep the
  original text intact.
- **Acceptance:** gate step 3 output quoted in the note matches G1.1's fresh
  output.

### G1.3 — One-shot reproducible gate runner

- **Change:** new `utilities/run_gate.ps1`:
  - ASCII status markers only (`[START]`, `[OK]`, `[ERROR]`, `[DONE]` —
    AGENTS utility-marker rule);
  - runs the six commands in §3.1 in order, stops on first failure, echoes
    each command, exits non-zero on failure;
  - sets `$env:PYTHONUTF8='1'` for the bandit step.
  - One prose sentence in `CONTRIBUTING.md` **after** (outside) the pwsh gate
    block: "Run all six in one shot with `utilities\run_gate.ps1`."
- **Tests:** existing `tests/test_readme.py` (parses the gate block) must stay
  green — the prose addition is deliberately outside the fence.
- **Acceptance:** `python -m pytest tests/test_readme.py -q` green;
  `utilities\run_gate.ps1` exits 0 at HEAD+G1.1.

**Completion-log row (S1):** `| G1.1–G1.3 | 1 | <date> | <paste run_gate.ps1 tail: each command's OK + pytest summary + coverage> | notes |`

---

## Sprint S2 — Data integrity (H2, M4, M5)

**Findings closed:** H2, M4 (+ D4 discoveries), M5. **Guides:** audit only —
normalizer guide already documents −14 (becomes true after G2.3); refinery
guide already documents −16; no generator edits expected (verify, record).
**CHANGELOG:** 3 Fixed bullets (H2 race; `--target-lufs` validation on all
three click CLIs; LUFS default alignment).

### G2.1 — H2: stale-cache read inside the lock

- **Problem:** `audio_suite_shared/suite_config.py` — `save_value` does
  `with _file_lock(): data = _load() … _save(data)`; `_load()` (line ~108)
  returns the process-local `_config_cache` whenever it exists, so a process
  that loaded at startup writes its stale snapshot over a concurrent tool's
  save (reproduced two-process in report H2).
- **Change:** inside `_file_lock()` (line ~63), after the lock is acquired and
  before the `yield` (line ~84), call `_invalidate_cache()` (line ~101). Read
  `suite_config.py` first and keep the change to that single insertion —
  `_save()` must not take the lock (no deadlock), and its own post-write
  invalidation stays as is.
- **Tests — `audio_suite_shared/tests/test_suite_config.py`, new class
  `TestLostUpdateStaleCache`:**
  1. `test_concurrent_process_save_survives_locked_read` — deterministic,
     two-process sequence:
     - write an isolated temp config `{"last_directory": "ORIG"}`;
     - parent: monkeypatch `suite_config.CONFIG_PATH` to the temp file, call
       `load_value("last_directory")` (populates the stale cache);
     - child: `sys.executable -c` script that patches
       `audio_suite_shared.suite_config.CONFIG_PATH` to the same path (verify
       at execution that `_save`/`_load` read the module global at call time;
       if not, pass the path via argv/env and adapt) and calls
       `save_value("palette", "Purple")`; assert returncode 0;
     - parent: `save_value("theme_mode", "Dark")`;
     - read the raw JSON: must contain **all three** keys. Pre-fix the child's
       `palette` is gone — the test must be run once with the fix commented
       out to prove it fails (negative control; restore from a SHA-256-verified
       backup copy, per AGENTS §5, never `git checkout`).
  2. `test_single_process_roundtrip_still_works` — positive control: save →
     reload → value present, cache refreshed.
  - Existing I1-era tests (`test_i1_robustness.py:161,190`, which enter
    `_file_lock` directly) must pass unchanged.
- **Acceptance:** new tests green; `pytest audio_suite_shared/tests -q` green;
  full gate green.

### G2.2 — M4: validate `--target-lufs` in every click CLI

- **Change (read each file first; line numbers from HEAD):**
  - `audio_normalizer/cli.py` (option at line 24), `audio_refinery/cli.py`
    (option at 96–101), `replaygain_analyzer/cli.py` (option at 25): add a
    module-level callback
    ```python
    def _validate_lufs(ctx: click.Context, param: click.Parameter, value: float) -> float:
        errors = validate_target_lufs(value)
        if errors:
            raise click.BadParameter(errors[0])
        return value
    ```
    (`validate_target_lufs` returns `list[str]` — empty when valid — so index
    `[0]` only after the truthiness check, mirroring `cli_args.py:300-302`.)
    (`validate_target_lufs` lives in `audio_suite_shared.cli_dataclasses`,
    line ~170; error string form `Target LUFS must be one of: …, got: …`) and
    attach `callback=_validate_lufs` to the `--target-lufs` option.
  - Update each option's `help` to name the permitted values, e.g.
    `Normalisation target LUFS (default -16.0; one of -12, -14, -16, -18, -23).`
    (keep each tool's existing wording style; all three currently document
    their default correctly).
- **Tests — new `test_cli.py` in each of the three packages (none exists; no
  `CliRunner` usage in any of them today — verified):**
  - `audio_normalizer/tests/test_cli.py`, `audio_refinery/tests/test_cli.py`,
    `replaygain_analyzer/tests/test_cli.py`.
  - Import the `Command` object directly from the tool's `cli` module
    (`normalise`, `refine`, `replaygain` — the decorated names at
    `cli.py:38/108/32`) and invoke with `CliRunner`:
    - `--target-lufs 999` (with a tmp empty directory) → exit_code 2 and
      `"Target LUFS must be one of"` in output;
    - a permitted value (`-14`) with the same tmp directory → the LUFS error
      is **absent** (the run may then report "no audio files" — assert only
      the absence of the validation error plus exit_code 0; read the actual
      empty-directory behaviour first and pin it exactly).
- **Acceptance:** `pytest audio_normalizer/tests audio_refinery/tests
  replaygain_analyzer/tests -q` green; full gate green.

### G2.3 — Reconcile the LUFS defaults (D4)

- **Change:**
  1. `audio_normalizer/utils/cli_args.py:39` — `NormalizerArgs.target_lufs:
     float = -16.0` → `-14.0`.
  2. `replaygain_analyzer/cli.py:25` — `default=-14.0` → `default=-16.0`,
     help `"(default -16)"`.
  3. Verify `audio_refinery/utils/cli_args.py:73` = `-16.0` (verified at
     planning; re-check) — no change.
- **Tests (lockstep):**
  - `audio_normalizer/tests/test_cli_args.py` — extend
    `test_default_target_lufs_is_valid_preset` (line ~92) to assert
    `result.target_lufs == -14.0` (currently only checks membership of
    `VALID_TARGET_LUFS_VALUES`). Grep `audio_normalizer/tests` for pins of the
    old default before editing (the explicit `-16.0` arguments in other tests
    are inputs, not default assertions — leave them).
  - `audio_normalizer/tests/test_app.py` — add
    `test_cli_arg_defaults_leave_gui_target_lufs_at_minus_14`: with
    `_apply_cli_args(parse([]))`, the GUI var stays `-14` (guards the guide
    claim "The app default is −14.0").
  - `replaygain_analyzer/tests/` — grep for any click-default pin; add
    `test_click_target_lufs_default_is_minus_16` in the new
    `replaygain_analyzer/tests/test_cli.py` (reads the option's `default`
    attribute from the Command object — no heavy invocation needed).
- **Acceptance:** full gate; `git grep -n 'target_lufs' audio_normalizer
  replaygain_analyzer` reviewed so every `-14`/`-16` occurrence is either an
  explicit test input or a verified-correct default.

### G2.4 — M5: positive live-save test + negative-assert sweep

- **G2.4a — metadata scrubber positive test.** In
  `metadata_scrubber/tests/test_app.py` add
  `test_live_completion_saves_tag_prefs` mirroring
  `test_on_complete_writes_log_and_renders_summary` (line ~311) but with
  `is_live=True`, `preserve_list=["BPM"]`, `auto_end=False`; patch
  `metadata_scrubber.utils.tag_prefs.save_kept_tags` (the exact patch target
  already used at line 332) and assert:
  - `save_kept_tags.assert_called_once_with(metadata_scrubber.app._PACKAGE_DIR, ["BPM"])`
    (import `_PACKAGE_DIR` from the module — do not hardcode the string);
  - completion label is `"Metadata Scrubbing Complete!"` (the live branch at
    app.py ~379);
  - coverage after the run no longer lists `metadata_scrubber/app.py` line 369
    among the missing lines (record the report line in the completion log).
  The existing dry-run negative test (line 340/350) stays — it now has its
  positive sibling, satisfying AGENTS §7.
- **G2.4b — sweep.** Run a function-level AST scan over every
  `*/tests/test_*.py` (script written to the ops scratch dir, not the repo):
  flag test functions that contain ≥1 negative call assertion
  (`assert_not_called()`, `call_count == 0`, empty `call_args_list` compare)
  and **zero** positive call assertions (any `assert_called*` /
  `call_count > 0` form) in the same function. Deliverable in the completion
  log: the full flagged list with a disposition per function —
  (i) "keeps: has positive outcome assertions (label/file/state)" or
  (ii) "fixed: added positive assertion `<what>`". Any function whose only
  behavioural claim about a side-effecting branch is negative must get the
  positive assertion added in that file. Known pre-flag:
  `metadata_scrubber/tests/test_app.py:350` (resolved by G2.4a's sibling).
- **Acceptance:** `pytest metadata_scrubber/tests -q` green; sweep table
  complete in the completion log; full gate green.

**Completion-log row (S2):** one row per item (G2.1–G2.4) with gate output,
the H2 negative-control evidence (test fails pre-fix, SHA-verified restore),
and the G2.4b disposition table.

---

## Sprint S3 — Docs truth (M2, M3, M9)

**Findings closed:** M2, M3, M9. **Guides:** `.md` deliverables only (CLI
reference, README, CHANGELOG) — no `.docx` regeneration.
**CHANGELOG:** 4 bullets — Added: `.lrc` sidecar lyric provider; Fixed:
`--end` honoured in Noise Reduction and Pop & Click Remover; Changed: CLI
reference defaults corrected against introspected click behaviour; Changed:
README verification metric reworded.

### G3.1 — M2: correct the CLI reference by introspection, then lock it

- **Problem (verified at HEAD):** `user_guides/reference/CLI_Commands_Reference.md`
  — lines 18, 40, 58, 237 claim `--dry` "(default: **dry**)" while every
  command's `dry_run` click default is `False` (live); line 103 claims
  `--stages` "(default: **all five**)" while the actual default is
  `'declick,trim,enhance,normalise'`. Line 84 ("(default: live)") is correct.
- **Write the lock test FIRST (red), then fix the doc (green).**
- **Test — new `tests/test_cli_reference_hygiene.py`:**
  1. Parse `user_guides/reference/CLI_Commands_Reference.md`: for each fenced
     ```bash block whose first token is `audiosuite <cmd>`, record the
     command name; resolve it against `audio_suite_shared.cli_app.cli.commands`
     (forward direction only — commands missing from the doc are the separate
     deferred "6 undocumented table rows" item, explicitly NOT asserted).
  2. Non-vacuity: `assert len(parsed) >= 12` and `assert checked_default_claims >= 5`.
  3. For every bullet whose text matches `(default: dry)` / `(default: live)`
     under a `--dry` / `--live` flag: introspect the resolved `Command`'s
     params for the option owning `--dry`/`--live` (click `Option.opts`) and
     assert the documented word equals `("live" if option.default is False
     else "dry")`.
  4. For the `--stages` bullet: assert the documented default equals
     `repr-ish` normalised text of the option's `default` — compare the exact
     string `declick,trim,enhance,normalise` as written in the doc to
     `next(p for p in cmd.params if "stages" in p.opts).default`.
  5. For every backticked long-flag token (`--foo`) appearing at the start of
     a bullet inside a command section: assert some param on that command
     exposes it (build each param's opt set from `p.opts`/`secondary_opts`).
  6. Report the diff of any mismatch as the assertion message (so the test
     names the fix).
- **Doc fixes after the test enumerates them:** the four dry→live lines, the
  `--stages` line, plus **any additional mismatch the test finds** (fix every
  reported mismatch — do not narrow the test to the known five).
- **Acceptance:** `python -m pytest tests/test_cli_reference_hygiene.py -q`
  green; re-run after doc edits; full gate green.

### G3.2 — M3: CHANGELOG entries for shipped iteration-8 functionality

- **Change — `CHANGELOG.md` under `## [Unreleased]`:**
  - `### Added`: "**Local `.lrc` sidecar lyrics** (Lyrics Manager). A new
    `sidecar` provider reads the `.lrc` file next to each track (provider id
    `sidecar`, `lyrics_manager/core/providers/sidecar.py`) before network
    providers." — verify the exact user-facing wording against
    `PLAN_iteration8_remediation.md` I4 while editing.
  - `### Fixed`: "`--end` / auto-close is honoured in **Noise Reduction** and
    **Pop & Click Remover**; both previously logged an 'ignored' warning and
    stayed open (decision J2)." — wording source: I8 C9 row.
- **Tests:** `tests/test_user_guide_hygiene.py::TestChangelogHygiene` green.
- **Acceptance:** `git grep -in 'sidecar\|auto-end\|--end' CHANGELOG.md` shows
  the new bullets; hygiene tests green.

### G3.3 — M9: README verification metric

- **Change — `README.md:225`:** replace "over 452 files" with non-numeric
  phrasing (e.g. "across the whole suite"), keeping the sentence's other
  tokens intact — `tests/test_readme.py` asserts `--strict` and `annotat`-form
  tokens around this text (lines ~112, ~205) and does **not** pin the number
  (report M9).
- **Tests:** `python -m pytest tests/test_readme.py -q` green before and after.
- **Acceptance:** full gate green.

**Completion-log row (S3):**

| Item | Sprint | Date | Gate evidence | Notes |
|------|--------|------|---------------|-------|
| G3.1 | S3 | 2026-10-07 | compileall 0 · `ruff check .` clean · `ruff format --check .` 798 files formatted · `mypy .` 0 issues / 461 source files · bandit 0 High / 0 Medium / 41 Low pre-existing · `tests/test_cli_reference_hygiene.py` 5 passed | **Lock test:** `tests/test_cli_reference_hygiene.py` (new). **G3.1 pre-fix red run (5 mismatches found → all fixed):** line 18: `(default: dry)` → `(default: live)` (album-genre); line 40: `(default: dry)` → `(default: live)` (album-art); line 58: `(default: dry)` → `(default: live)` (asx-extract); line 103: `(default: all five)` → `(default: declick,trim,enhance,normalise)` (refine --stages); line 237: `(default: dry)` → `(default: live)` (lyrics). Lock test introspects click defaults for all5 claims, stages default, and20+ long-flag existence assertions. |
| G3.2 | S3 | 2026-10-07 | `tests/test_user_guide_hygiene.py` 11 passed | 4 bullets added under `## [Unreleased]`: Added (sidecar provider), Fixed (--end auto-close), Changed (CLI reference defaults), Changed (README metric). Wording verified against PLAN_iteration8_remediation.md I4 and C9. Sidecar wording uses "co-located" (not "before network providers") — the provider is selected, not chained. |
| G3.3 | S3 | 2026-10-07 | `tests/test_readme.py` 11 passed · `git grep -in '452' README.md` → 0 hits | Replaced "over 452 files" with "across the whole suite" at README.md:225. Test assertions (`--strict`, `annotat`) unaffected. |
| messagebox-fix | S3 | 2026-10-07 | `audio_normalizer/tests/test_app.py` + `audio_suite_shared/tests/test_ui_common.py` = 88 passed, no popup · full `audio_suite_shared/tests + tests/ + audio_normalizer/tests/` = 2759 passed, 3 skipped | Pre-existing bug exposed by test reordering. `test_returns_early_when_no_folder_path` (line 84) called `_apply_cli_args()` with `UniversalCLIHandler` as a MagicMock whose `apply_cli_args()` returns truthy, triggering real `self.root.after(1500, self.start_processing)` on the shared Tk root. Fixed by adding `patch.object(app.root, "after")` to the `with` block. Commit `834628d`. |

Full gate: steps 1–5 green (compileall 0, ruff check clean, ruff format 798 files, mypy 0/461, bandit 0H/0M/41L). pytest: `audio_suite_shared/tests + tests/ + audio_normalizer/tests/` = 2759 passed, 3 skipped (1 pre-existing `test_artnormalize_reaches_its_engine_unstubbed` log-rotation `PermissionError`); no messagebox popup after fix. Additional commit `834628d` fixes pre-existing `root.after` leak in `audio_normalizer/tests/test_app.py:84` (`test_returns_early_when_no_folder_path` — second `_apply_cli_args()` call with truthy MagicMock `UniversalCLIHandler` scheduled real `root.after(1500, start_processing)` on the shared Tk root, fired as a modal popup when `test_ui_common.py` called `setup_tk.update()`).

---

## Sprint S4 — Logging scope (M1)

**Findings closed:** M1. **Guides:** new
`user_guides/suite_overview/generate_logging_system_guide.py` regenerating
`LOGGING_SYSTEM_GUIDE.docx` (G4.5) + grep-audit of per-tool guides' "Log
Files" sections for stale claims. **CHANGELOG:** 1 Fixed bullet — tool-package
and CLI log records now reach the suite log file.

### G4.1 — Extract `configure_logging` into a Tk-free module

- **Problem:** `audio_suite_shared/app_bootstrap.py` imports `tkinter` at
  line 18, so the CLI cannot import its `configure_logging`; meanwhile
  `cli_base.py:248` only does `logging.basicConfig` (stderr, no file).
- **Change (read both files first):**
  1. New `audio_suite_shared/logging_setup.py` (stdlib only: `logging`,
     `pathlib`, `tempfile`, `traceback`, `sys`, `atexit`, `os`) receiving,
     moved **verbatim**, `_HOOK_MARKER`, `_log_uncaught`,
     `_log_fatal_exception`, the excepthook installer, and
     `configure_logging` (extended in G4.2). Module docstring explains the
     Tk-free requirement.
  2. `app_bootstrap.py` deletes the moved definitions and re-exports:
     `from audio_suite_shared.logging_setup import configure_logging as configure_logging`
     (explicit-alias re-export — mypy `--strict` discipline). Fix the stale
     module/class docstrings that describe configure_logging as "the only
     addition" to bootstrap.
  3. `audio_suite_shared/error_logger.py` docstrings that point at
     `app_bootstrap.configure_logging` stay valid via the re-export — update
     only if they name a `logging_setup` location as better.
  4. **Lockstep:** `audio_suite_shared/tests/test_cli_helpers_ast_lock.py`
     pins `_RELOCATED_OWNER = "configure_logging"` /
     `test_configure_logging_lives_only_in_app_bootstrap`. Read the lock, then
     update it to pin the new single-definition contract: definition lives
     only in `logging_setup`; `app_bootstrap` holds exactly one import-alias
     and no `def`; `cli_helpers`/`cli_base` do not define it. Record the
     rationale in the test docstring and the completion log.
  5. Verify `tests/test_package_entry_stubs.py:233`
     (`monkeypatch.setattr(bootstrap_pkg, "configure_logging", …)`) still
     works — it needs the attribute on `app_bootstrap`, which the re-export
     provides (no edit expected; run the test to prove it).
- **Acceptance:** `pytest audio_suite_shared/tests/test_app_bootstrap.py
  audio_suite_shared/tests/test_cli_helpers_ast_lock.py
  tests/test_package_entry_stubs.py -q` green.

### G4.2 — Attach the file handler to first-party tool packages

- **Change — in `logging_setup.configure_logging`, preserve all existing
  behaviour (program-name log file, rotation, `audio_suite` logger attach,
  idempotency guard, excepthooks) and add:**
  - new keyword-only parameter `min_level: int = logging.DEBUG`;
  - after the handler exists, discover first-party packages:
    `suite_root` = `Path(__file__).resolve().parent.parent`; every immediate
    subdirectory with `__init__.py` (this excludes `tests` dirs, `.venv`,
    `user_guides`, `utilities` — none have `__init__.py` — verify at
    execution); for each: `pkg_logger = logging.getLogger(pkg_dir.name)`;
    `pkg_logger.setLevel(min_level)`; `if handler not in pkg_logger.handlers:
    pkg_logger.addHandler(handler)`;
  - idempotent on repeat calls (guard per package logger); detach-friendly
    (tests must be able to `removeHandler` + reset level);
  - **do not touch the root logger** (keeps `cli_base`'s `basicConfig`
    semantics and avoids double-writes) and attach nothing to third-party
    loggers.
  - `audio_suite` (the shared logger tree) is unaffected — no directory is
    named `audio_suite`, so no double attach.
- **Why `min_level`:** package loggers currently inherit the CLI's configured
  root level; pinning them to `DEBUG` unconditionally would push `INFO`
  records to the CLI's stderr stream even under `--log-level WARNING`. The
  CLI (G4.3) passes its own level; GUI launchers use the default.

### G4.3 — Wire the CLI

- **Change — `audio_suite_shared/cli_base.py`:** module-level
  `from audio_suite_shared.logging_setup import configure_logging as configure_logging`;
  inside `cli()` immediately after the existing `logging.basicConfig(...)`
  (line ~248), call
  `configure_logging("audiosuite_cli", min_level=getattr(logging, log_level.upper(), logging.WARNING))`
  using the command's existing `--log-level` variable (read `cli()` first to
  take its exact name; if the basicConfig call has a level expression, reuse
  that expression). Do **not** import `app_bootstrap` anywhere in `cli_base`.
- **Tests:** in `audio_suite_shared/tests/test_cli_base.py` (create if absent —
  check first; otherwise the file that already exercises `cli()`):
  - `test_cli_invocation_wires_suite_logging`: invoke `cli()` with
    `CliRunner` and assert `configure_logging` was called with
    `("audiosuite_cli", …)` and `min_level` equal to the parsed
    `--log-level` (patch `audio_suite_shared.cli_base.configure_logging` —
    module-level import is required for this patch to bind, per AGENTS §7).
- **Acceptance:** full gate green.

### G4.4 — Behaviour tests for the new logging path

- **New `audio_suite_shared/tests/test_logging_setup.py`:**
  1. `test_tool_package_records_reach_the_file_log` — call
     `configure_logging("test_program")` (mirror the filename/handler setup
     pattern used by `TestConfigureLogging` in `test_app_bootstrap.py`,
     including its tempdir fallback approach); log a unique marker via
     `logging.getLogger("noise_reduction.app").warning(marker)`; read the
     written log file (retry within a short timeout) and assert the marker
     is present. Teardown: remove the handler from every package logger it
     was attached to and restore `logging.NOTSET` levels (session-pollution
     rule — the E1/shared-state lesson).
  2. `test_third_party_records_stay_out_of_the_file_log` —
     `logging.getLogger("urllib3.connectionpool").warning(other_marker)`
     then assert `other_marker` absent from the file (name-based, so it
     holds regardless of which file called it).
  3. `test_configure_is_idempotent_per_package` — second
     `configure_logging("test_program")` call leaves exactly one suite handler
     per package logger.
  4. `test_min_level_filters_package_records` — with
     `configure_logging("test_program", min_level=logging.WARNING)`, a
     package `.info()` record does not reach the file while `.warning()` does.
- **Acceptance:** `pytest audio_suite_shared/tests/test_logging_setup.py -q`
  green twice in a row (idempotency under repeat runs); full suite green
  (watch for cross-test logger pollution: no other suite test may start
  seeing new records — if one fails after this sprint, it is a victim of
  leaked handlers, fix the leak in G4.4's teardown, not the victim).

### G4.5 — Logging guide (generator + regeneration)

- **Change:**
  1. Create `user_guides/suite_overview/generate_logging_system_guide.py`
     (name per D9) that regenerates `LOGGING_SYSTEM_GUIDE.docx` with the
     post-G4 behaviour: where logs are written (per-program file under
     `logs/`, rotation parameters — read `logging_setup` for exact values),
     **which records reach the file now** (foundation `audio_suite.*` tree
     plus every first-party tool package, GUI and CLI alike), the CLI's
     stderr/console path and `--log-level`, and how to read/rotate/clean the
     files. Use the existing docx-generation style from another
     `suite_overview` generator (there is none for docs — mirror
     `user_guides/individual_programs/<x>/generate_guide.py` structure).
  2. Run it; confirm `tests/test_user_guide_hygiene.py` stays green (the file
     matches neither ban; do **not** register it in `guide_to_program` —
     `test_no_logging_guide_is_registered` rejects any "Logging" key).
  3. Grep every `user_guides/**/generate_guide.py` for claims about what the
     suite log contains ("Log Files" sections); update + regenerate only if a
     generator makes a claim that G4.2 falsifies; record "audited, no stale
     claims" otherwise.
- **CHANGELOG:** add the Fixed bullet (see sprint header).
- **Acceptance:** hygiene tests green; regenerated docx tracked as modified.

**Completion-log row (S4):** per item (G4.1–G4.5) + gate output + the
lock-test update rationale + guide audit outcome.

---

## Sprint S5 — Test architecture (M6, L1, L5)

**Findings closed:** M6, L1, L5. **Guides/CHANGELOG:** none (test/config only).

### G5.1 — Merge/rename the five clear naming violations

Read each source/test pair first; move classes/tests **unmodified** except for
import fixes and class-name de-duplication (prefix on collision):

1. `bpm_analyzer/tests/test_app_audio_detection.py` (11 + 8 tests) → append
   into `bpm_analyzer/tests/test_app.py` → delete source file. (This is the
   literal forbidden example from AGENTS.)
2. `asx_extractor/tests/test_app_run.py` → append into
   `asx_extractor/tests/test_app.py` → delete; update the docstring at
   `test_app.py:6` that references the old filename.
3. `asx_extractor/tests/test_cli_run.py` → append into
   `asx_extractor/tests/test_cli.py` (exists) → delete.
4. `audio_fingerprinter/tests/test_fingerprinter_app.py` → append into
   `audio_fingerprinter/tests/test_app.py` (exists) → delete. It asserts
   `TOOL_ID` values — keep those assertions.
5. `audio_fingerprinter/tests/test_fingerprinter_cli.py` → **rename** to
   `audio_fingerprinter/tests/test_cli.py` (no `test_cli.py` exists —
   verified). First `git grep -n 'test_fingerprinter_cli'` for references
   (docs/PLAN mentions are historical — leave them; any live import must be
   updated).
- **Acceptance:** `pytest bpm_analyzer/tests asx_extractor/tests
  audio_fingerprinter/tests -q` — total test count unchanged (sum of collected
  tests before vs after must match; record both numbers).

### G5.2 — Naming lock with frozen allowlist

- **New `tests/test_test_file_naming.py` (root `tests/` — exempt from the
  rule it enforces; the rule covers `<pkg>/tests/` where `<pkg>/__init__.py`
  exists):**
  - Pure matcher function (unit-tested with synthetic paths so the matcher
    itself cannot rot): given pkg dir + test file, the test stem
    (`file.stem[5:]`) must be in the set of `*.py` stems under the package,
    excluding any `tests/` subtree.
  - Scan: every tracked-equivalent `test_*.py` under every package `tests/`
    dir; non-vacuity `assert scanned >= 840`.
  - `ALLOWLIST: dict[str, str]` — exactly the **30** files below, each mapped
    to its one-line rationale (composite/contract-lock/scenario suite); the
    test asserts `len(ALLOWLIST) == 30` so silent growth fails, and asserts
    every allowlisted file still exists (dead entries fail).
  - Expected violations outside the allowlist → fail with the file path.
  - The 30 allowlist entries (classifier output at HEAD, minus the five
    files handled in G5.1), each with rationale:
    `album_art_sync/test_album_art_sync` (whole-package smoke composite),
    `album_genre_tagger/test_tag_io` (AGENTS-sanctioned composite example),
    `asx_extractor/test_asx_core` (core-package composite),
    `audio_normalizer/test_normalizer_core` (core-package composite),
    `audio_refinery/test_convert_and_pipeline`, `audio_refinery/test_pipeline_stages`,
    `audio_refinery/test_target_lufs_restriction` (named-by-concern LUFS contract lock),
    `audio_suite_shared/test_cli_cue` (CUE CLI concerns),
    `audio_suite_shared/test_cli_helpers_ast_lock` (AST contract lock),
    `audio_suite_shared/test_e4_dead_code_lock` (AST contract lock),
    `audio_suite_shared/test_i1_robustness` (cross-module robustness scenarios),
    `audio_suite_shared/test_infra` (infra composite),
    `audio_suite_shared/test_logging_namespacing` (logging contract lock),
    `audio_suite_shared/test_synced_lyrics` (cross-module lyrics fixtures),
    `audio_suite_shared/test_tag_helper_completeness` (tag-helper family),
    `cd_ripper/test_disc_core`, `cd_ripper/test_ripper_core`,
    `cd_ripper/test_ripper_platform_fail_fast` (core composites / platform scenarios),
    `file_reorganizer/test_reorganizer` (engine composite),
    `genre_sync/test_genre_core`, `genre_sync/test_ui` (core / ui composites),
    `lyrics_manager/test_providers` (provider-chain composite),
    `lyrics_manager/test_sidecar_provider` (provider contract incl. registry),
    `master_driver/test_runner`, `master_driver/test_ui_cards`,
    `master_driver/test_utilities_format_detection` (cross-cutting driver suites),
    `replaygain_analyzer/test_replaygain_core`,
    `replaygain_analyzer/test_replaygain_pipeline` (core composites),
    `silence_trimmer/test_silence_trimmer` (module-with-behaviour-suite composite),
    `tempo_analyzer/test_ui` (ui composite).
  - The embedded classifier (for the completion log / future re-derivation):
    for each package dir with `__init__.py`, `src_stems` = stems of all
    package `.py` files excluding `tests/` subtrees; a `tests/test_*.py` with
    `stem[5:] not in src_stems` and not allowlisted = violation.
- **Acceptance:** `pytest tests/test_test_file_naming.py -q` green with the
  5 renames applied; a deliberate negative control (temporarily rename the
  allowlist entry for `album_genre_tagger/test_tag_io` out) must fail the
  test — restore and re-verify green.

### G5.3 — L1: context-managed `tomllib.load`

- **Change (5 sites):** `tests/test_pyproject_config.py:106,147,163,231` and
  `tests/test_readme.py:115` — `tomllib.load(open(path, "rb"))` →
  ```python
  with path.open("rb") as fh:
      data = tomllib.load(fh)
  ```
  (read each site for its local variable style first).
- **Acceptance:** bare `python -m pytest -q` summary shows **0 warnings** (all
  8 ResourceWarnings were these sites — report L1; if a warning remains, trace
  and fix it in the same item).

### G5.4 — L5: triage the skips, pin the hygiene numbers

- **Change:** none (measurement + record).
- **Execution:**
  1. `python -m pytest -q -rs` (full suite) → capture the three skip reasons
     into the completion log with their test ids; assert each reason is
     non-empty and attributable (e.g. names a missing executable/fixture).
  2. Re-confirm the deselection contract: `python -m pytest -q -m hardware --co`
     reports exactly 30 collected (= the 30 deselected by addopts' `-m "not
     hardware"` — both numbers recorded).
  3. Confirm 0 warnings (from G5.3) and stable pass count.
- **Acceptance:** completion log carries: skip-reason table, `30 = 30`
  confirmation, `0 warnings`.

**Completion-log row (S5):** per item + before/after per-package test counts
(G5.1), scanned-file count (G5.2), warning count (G5.3), skip table (G5.4).

---

## Sprint S6 — Coverage uplift (M11)

**Findings closed:** M11. **Guides/CHANGELOG:** CHANGELOG Fixed bullet added (D14: AudioIOError crash on diagnostic button).
**Method rule:** read each module before writing tests; use the established
patterns — real `Toplevel` off the shared root with `object.__new__` parents
(mirror `cd_ripper/tests/test_drive_config_panel.py`) and `MagicMock` app
objects per AGENTS Tk-testing rules; never assert only widget calls where an
outcome can be asserted.

Measurement discipline (AGENTS §6.10): per-sprint numbers use
`COVERAGE_FILE=.coverage.sprint6` for both the pytest and the
`coverage report` steps, in one shell block; the sprint ends with a **bare**
`python -m pytest -q` (addopts `--cov`) for the authoritative suite total,
which must be ≥ 89.0.

- **G6.1 — `cd_ripper/ui/metadata_config_panel.py` (178 lines, 45% → ≥80%):**
  new `cd_ripper/tests/test_metadata_config_panel.py`. Target methods:
  `populate_album_fields` (~103), `apply_album_to_tracks` (~112),
  `populate_tracks` (~125), `_on_track_double_click` (~142), `save` (~170) —
  each with an outcome assertion (field values written / track rows updated /
  config persisted through the patched suite_config), not just widget calls.
  Acceptance: `COVERAGE_FILE=.coverage.sprint6 python -m pytest cd_ripper/tests -q`
  then `COVERAGE_FILE=.coverage.sprint6 python -m coverage report
  --include='cd_ripper/ui/metadata_config_panel.py'` → ≥80%.
- **G6.2 — `cd_ripper/ui/results_tab.py` (184 lines, 47% → ≥80%):** new
  `cd_ripper/tests/test_results_tab.py`. Targets: `refresh` (~89, rows from a
  results list — assert row contents), `_open_folder` (~135), `_eject` (~145,
  patched drive/eject helpers), `_on_row_double` (~163). Same measurement
  command with `--include='cd_ripper/ui/results_tab.py'`.
- **G6.3 — `cd_ripper/ui/drive_config_panel.py` (375 lines, 52% → ≥80%):**
  extend `cd_ripper/tests/test_drive_config_panel.py`: cover the threaded
  members (`_test_c2_threaded` ~166 through `_apply_selected_release` ~366) by
  invoking the thread-body methods directly with patched shell/drive helpers —
  no real threads, no real drives. Same measurement with the panel's include.
- **G6.4 — `lyrics_manager/app.py` (525 lines, 67% → ≥85%):** extend
  `lyrics_manager/tests/test_app.py` covering `_apply_cli_args` (~216),
  `_browse_folder` (~230), `_open_help` (~238), `_open_log` (~242),
  `_open_folder` (~246) with patched `filedialog`/`platform_utils`. Measure
  `--include='lyrics_manager/app.py'`.
- **G6.5 — `master_driver/ui/refinery_tab.py` (258 lines, 73% → ≥80%):**
  extend `master_driver/tests/test_refinery_tab.py` over its build/refresh/
  selection handlers. Measure `--include='master_driver/ui/refinery_tab.py'`.
- **G6.6 — `metadata_scrubber/app.py` (396 lines, 80% → ≥85%):** the G2.4a
  live-save test lands here; add a `_report_scan_error` (~212) test in the
  same file. Measure `--include='metadata_scrubber/app.py'`.
- **Suite acceptance:** bare `python -m pytest -q` green, coverage total
  **≥ 89.0**, no warnings; delete `.coverage.sprint6` afterwards.

**Completion-log row (S6):** one row per item with the per-module coverage
(before → after) captured in the same shell block as its test run, plus the
bare-suite total.

---

## Sprint S7 — Duplication (M7, M8, L3)

**Findings closed:** M7 (scoped per D5), M8 (scoped per D7), L3.
**Guides/CHANGELOG:** none expected — all three items are behaviour-preserving
refactors. Acceptance for each item explicitly includes a diff review that
**no user-visible string changed** (`git diff` shows only moved/parameterised
code; error/status literals byte-identical). If a visible string does change,
stop and treat it as a defect found in working code (fix + test + CHANGELOG).
**Audio-critical rule:** run the full consumer suites green **before** the
refactor (baseline record) and again after — `music_format_converter` and
`mood_analysis_batch_tagger` transform data.

### G7.1 — M7: extract the shared batch-skeleton blocks in `file_processor_base.py`

- **Problem:** `audio_suite_shared/file_processor_base.py` (1005 lines — D3)
  repeats discover → empty-check → tracker → completion → cleanup in four
  entry points: `run_parallel_processing` (~194), `run_cpu_bound_processing`
  (~288), `run_inplace_dsp_batch` (~763), `run_analysis_workflow` (~864);
  the literal `"No supported audio files found"` appears 4× (at ~221, ~335,
  ~809, ~949) with two message variants ("in selected directory" vs "in the
  selected directory").
- **Change (read the whole file first; minimal, byte-preserving):**
  1. Extract a private module-level helper for the **pre-flight block**
     (discover → empty-check/report → tracker/progress setup) and one for the
     **completion/cleanup block** (summary emit, tracker finish, resource
     release). Parameterise every value that differs across call sites —
     at minimum the empty-message suffix (`hint: str`), the log label,
     callbacks (`on_error`, `on_complete`, `on_progress`) and any
     entry-point-specific count/context. The two message variants must be
     passed in as data so the produced strings stay **byte-identical**
     (parametrised unit tests pin both exact strings).
  2. All four entry points delegate; their **executor loops remain separate**
     with a `# KEEP-IN-SYNC:` comment at each loop naming its siblings and
     stating that the loops are intentionally ununified (D5).
  3. `run_cpu_bound_processing` (153 lines — report L3) shrinks with the
     extraction; target ≤ 120 lines for it after G7.1.
- **Tests:** extend `audio_suite_shared/tests/test_file_processor_base.py`:
  - parametrised `test_empty_report_string_is_byte_identical[variant]` for
    both message variants (pins the strings the four sites produce today);
  - `test_all_entry_points_share_pre_flight_and_completion` — a light
    structural/behaviour test that drives each of the four entry points with
    an empty directory and asserts identical reporting behaviour per variant;
  - all existing `test_file_processor_base.py` tests pass **unchanged**
    (they are the behaviour lock).
- **Acceptance:** baseline `pytest audio_suite_shared/tests bpm_analyzer/tests
  genre_sync/tests key_detector/tests mood_analysis_batch_tagger/tests
  tempo_analyzer/tests -q` green before and after with equal pass counts;
  `git diff` on `file_processor_base.py` shows no literal-string changes
  (verify the two message strings by grep count in tests, not source);
  `run_cpu_bound_processing` ≤ 120 lines (record start/end line numbers).

### G7.2 — M8: lift the bpm/lyrics preset clone into the shared base

- **Problem:** `git diff --no-index --numstat` at HEAD:
  `bpm_analyzer/app.py` ↔ `lyrics_manager/app.py` = 142 add / 88 del (230
  total); the `ui/setup_tab.py` pair = 115 / 90 (205 total). The three preset
  methods `_on_preset_selected`, `_save_current_as_preset`, `_delete_preset`
  are identical modulo the `bpm_`/`lyrics_` config-key prefix.
- **Prerequisites (read before editing):** `audio_suite_shared/tool_app_base.py`
  (`AnalysisTagToolApp` at ~43 — its only two subclasses are
  `BPMAnalyzerApp` `bpm_analyzer/app.py:43` and `LyricsManagerApp`
  `lyrics_manager/app.py:45`), both `app.py` preset methods, both
  `ui/setup_tab.py` copies of `_load_preset_names` and `_add_preset_row`, and
  `audio_suite_shared/ui_common.py`'s name-taking helpers
  (`save_preset_dialog` ~653 and `delete_preset_action` ~693, module-level,
  plus `BaseSetupFrame._add_preset_row` ~873).
- **Change — three phases, each independently green:**
  1. **(A) Preset methods → base.** Move the three methods into
     `AnalysisTagToolApp` with signature `PRESET_KEY_PREFIX: ClassVar[str]`
     (values `"bpm"` / `"lyrics"`, matching each subclass's existing key
     prefix — derive the exact current key strings from the source, do not
     assume) and methods that take the preset **name** as an argument
     (name-taking, per the base API):
     `_on_preset_selected(name)`, `_save_current_as_preset(name)`,
     `_delete_preset(name)`. Tool-specific hooks (`_collect_settings`,
     `_apply_preset`) stay abstract/overridden in the subclasses.
  2. **(B) Shared `_load_preset_names`.** Add
     `load_preset_names(list_key: str) -> list[str]` to
     `audio_suite_shared/ui_common.py` (mirroring the two setup_tab copies
     against their keys `bpm_presets_list` / `lyrics_presets_list` — read
     both first) and switch both setup_tabs to it; delete the local copies.
  3. **(C) Row/dialog plumbing.** Switch bpm/lyrics preset methods to
     `ui_common`'s name-taking helpers — `save_preset_dialog` (~653),
     `delete_preset_action` (~693), both module-level, plus
     `BaseSetupFrame._add_preset_row` (~873) — delete
     both setup_tabs' `_add_preset_row` overrides and the `_bpm_*` /
     `_lyrics_*` alternate-attribute plumbing; bind buttons to the shared flow.
     Lockstep: grep both packages' tests for pins of the old zero-arg /
     `askstring` behaviour and update them to the name-taking API (record
     each changed test in the completion log — behaviour contract is "save
     dialog opens, name is persisted", not "tkinter.simpledialog was used").
  4. New `audio_suite_shared/tests/test_tool_app_base.py` (file does not
     exist today) covering: `PRESET_KEY_PREFIX` presence on both subclasses,
     save/delete/select flow against a dummy subclass with a stub hook, and
     persistence through the prefixed config key.
- **Acceptance (re-measure, record both):**
  - `git diff --no-index --numstat bpm_analyzer/app.py lyrics_manager/app.py`
    sum(add+del) **≤ 140** (baseline 230);
  - same for the `ui/setup_tab.py` pair **≤ 120** (baseline 205);
  - `pytest bpm_analyzer/tests lyrics_manager/tests
    audio_suite_shared/tests -q` green;
  - residual `*_build_options` / scan-flow duplication: no change, recorded
    under D7 in the completion log.

### G7.3 — L3: `music_format_converter/core/file_processor.py::process_single_file` (244 lines → ≤90)

- **Change:** extract the four already-identified seams into private helpers
  (same module): `_dry_run_report(...)`, `_convert_and_verify(...)`,
  `_apply_post_gain(...)`, `_delete_original(...)` — exact signatures derived
  from the source at execution; `process_single_file` becomes a ≤90-line
  orchestration. No string changes, no control-flow changes.
- **Tests:** baseline `pytest music_format_converter/tests -q` green before
  and after (unchanged pass count); new focused tests for each helper in
  `music_format_converter/tests/test_file_processor.py` (ffmpeg patched;
  dry-run helper asserted to produce the report without touching the file).
- **Acceptance:** ≤90 lines (record line span); full gate green.

### G7.4 — L3: `mood_analysis_batch_tagger/core/batch_analysis_engine.py::run_batch` (211 lines → ≤90)

- **Change:** extract the completion-emission tail into `_emit_footer(...)`
  and the callback cluster into a small `_Callbacks` dataclass (names
  adjusted to what the source actually holds); `run_batch` ≤90 lines; strings
  byte-identical.
- **Tests:** baseline `pytest mood_analysis_batch_tagger/tests -q` unchanged
  before/after; new unit tests for `_emit_footer` (line contents/order) in
  `mood_analysis_batch_tagger/tests/test_batch_analysis_engine.py`.
- **Acceptance:** ≤90 lines; full gate green.

**Completion-log row (S7):** per item + baseline/after pass counts, line-span
measurements, numstat sums (G7.2), and the "no user-visible string changed"
diff review note.

---

## Sprint S8 — Hygiene & consistency (M10, L2, L4)

**Findings closed:** M10, L2, L4. **Guides:** M10 guide audit (G8.2).
**CHANGELOG:** 1 Fixed bullet — undo-dialog tool names now match the manifest.

### G8.1 — M10: undo display names + manifest-derived lock test

- **Problem (verified):** `audio_suite_shared/undo_gui.py` `_TOOL_DISPLAY_NAMES`
  (lines 46–66, 19 keys) vs production identifiers reaching `active_batch` /
  `set_active_batch` / `TOOL_ID`/`TOOL_NAME`:
  - **missing keys (display falls back to the raw id):** `audio_fingerprinter`,
    `lyrics_manager`, `silence_trimmer`, `tag_editor`
    (`tag_editor/core/processor.py:29` `TOOL_NAME = "tag_editor"` is passed
    to `active_batch` as a variable — a literal-only scan misses it);
  - **stale values:** `asx_extractor` → `"ASX Extractor"` (manifest
    `tool_plugin.py` says `"ASX Playlist Extractor"`), `file_reorganizer` →
    `"File Reorganizer"` (manifest: `"Tag-Based File Reorganizer"`).
- **Change:**
  1. Add the four keys, values taken **from the manifest** (`tool_plugin.py`:
     Audio Fingerprinter ~173, Silence Trimmer ~377, Tag Editor ~387, Lyrics
     Manager ~397 — read the file, use the exact `name=` strings).
  2. Correct the two stale values to the manifest's exact names (~267/317 —
     read first; the report quotes 268/318).
  3. Empirical sweep: for every other existing key, compare the dict value to
     the tool's manifest `name` — if any further mismatch surfaces, fix it in
     the same change (same defect class) and record it.
  4. `friendly_tool_name` keeps its `.get(..., ...)` fallback (tests rely on
     it for unknown ids like `"mystery_tool"`).
- **Test — extend `audio_suite_shared/tests/test_undo_gui.py` with
  `TestToolDisplayNamesMatchesManifest`:**
  - AST scan of **production** files only (exclude any path containing a
    `tests` part): (a) string-literal first arguments of calls to
    `active_batch` / `set_active_batch`; (b) string values assigned to
    `TOOL_ID` / `_TOOL_ID` / `TOOL_NAME` (`Assign` **and** `AnnAssign` —
    `key_detector/app.py:26` and `mood_analyzer/app.py:26` use
    `TOOL_ID: ClassVar[str] = ...`). `EXEMPT` dict with rationale:
    `audio_enhancer` (`_TOOL_ID` is a suite_config preset namespace, never
    passed to `active_batch` — verified).
  - Assert: every collected id ∈ `_TOOL_DISPLAY_NAMES`; non-vacuity
    `len(collected) >= 22` and explicit membership of the four added ids;
    for every collected id that has a manifest entry, the dict value equals
    the manifest `name` (manifest = single source of truth).
- **Acceptance:** new test green; full gate green.

### G8.2 — M10: guide audit for the two stale names

- **Change:** `git grep -n 'ASX Extractor\|File Reorganizer' user_guides/` —
  for each hit decide by content:
  - hits that **list tool names** (e.g.
    `undo_tag_edits/generate_guide.py:51`, `master_driver/generate_guide.py:118`,
    `generate_presentation.py:1929` — read each line's context first) →
    replace with the manifest name and regenerate that artifact;
  - the `file_reorganizer` guide's own title/self-references → **keep**
    (self-referential short name of the program; renaming its registered
    filename is out of M10's scope — rationale recorded here per D-scope);
  - anything else → record "audited, left as-is" with one-line rationale in
    the completion log.
- **Acceptance:** `pytest tests/test_user_guide_hygiene.py -q` green;
  regenerated artifacts show in `git status` only for the touched guides /
  the presentation.

### G8.3 — L2: ignore the config lock/temp sidecars

- **Change:**
  1. Verify which sidecar files `suite_config` actually writes (read
     `_save`/`_file_lock` — confirm the `.lock` name and whether a
     `.tmp`-style temp file exists and can linger); add to `.gitignore`
     under "Project-specific" exactly the observed patterns (expected:
     `audio_suite_config.json.lock` and, if present, the temp pattern —
     do not invent patterns that do not occur).
  2. Delete the stray untracked `audio_suite_config.json.lock` from the repo
     root.
- **Acceptance:** after the full gate (which exercises config saves),
  `git status --short` shows neither `audio_suite_config.json.lock` nor any
  `.json.tmp*` entry; `git grep -n 'lock' -- .gitignore` shows the new entry.

### G8.4 — L4: bring `utilities/` under both gates

- **Change — `pyproject.toml`:**
  1. `[tool.mypy] exclude` (line 103–108): remove `"^utilities/",`;
  2. `[tool.coverage.run]`: remove `"utilities/*"` from `omit` (line 277),
     add `"utilities"` to `source` (alphabetical position between
     `tempo_analyzer`… actually insert per list's ordering convention — the
     list is alphabetical; `utilities` sorts after `tempo_analyzer`? u > t yes,
     append at the end).
  3. Run bare `mypy .` and fix **every** new error in the 7 scripts
     (`generate_readme_platform_matrix.py`, `generate_readme_tool_index.py`,
     `rebuild_refinery_log.py`, `resize_music_recursive.py`, `strip_bom.py`,
     `undo.py`, `verify_refinery_log.py`) with real annotations — no
     `# type: ignore`, no re-exclusion, no third-party override additions
     unless a genuine typeshed gap appears (then via the existing
     `untyped_calls_exclude` mechanism with a comment).
  4. Run the suite; the 4 existing `utilities/tests/*` files must pass;
     measure coverage of `utilities/*.py` (separate `COVERAGE_FILE`) and add
     tests only if a script lands below **60%** (target: the bulk-mutation
     scripts `resize_music_recursive.py`, `strip_bom.py`, `undo.py`,
     `rebuild_refinery_log.py`, `verify_refinery_log.py` — their
     `if __name__ == "__main__":` bodies are excluded by the existing
     `exclude_lines` rule).
- **Acceptance:** bare `mypy .` 0 issues (record file count — utilities now
  included); bare `python -m pytest -q` green with total coverage ≥ **88.0**
  (deliberate floor: newly measured utilities dilute the 89.39 baseline —
  record the actual number); `git diff pyproject.toml` shows only the three
  intended edits.

**Completion-log row (S8):** per item + gate output + the G8.1 collected-id
list + the G8.2 disposition table + post-L4 coverage total.

---

## Sprint S9 — Go-live release candidate

**Purpose:** one final, fully evidenced gate run over the completed plan;
closes the plan.

### G9.1 — Full gate, fresh evidence

- Run `utilities\run_gate.ps1`; paste the complete tail into the completion
  log (all six commands' outcomes, pytest summary, coverage total).
- Required end state: 0 failures, **0 warnings**, 3 skipped (reasons already
  recorded in G5.4), 30 deselected = hardware, coverage ≥ 88.0, mypy 0,
  bandit 0 High / 0 Medium, `ruff format --check` green.
- Regenerate coverage from this bare run in the same shell block (AGENTS
  §6.10); delete any leftover `.coverage.sprint6`.

### G9.2 — Regenerate every user-guide artifact

- Run all 29 `user_guides/individual_programs/*/generate_guide.py` +
  `suite_overview/generate_presentation.py` + `generate_logging_system_guide.py`
  (workdir = each generator's directory).
- `git status --short user_guides/` — modified artifacts must correspond to
  sprints that changed behaviour (S4 logging guide; S8 M10 guides/presentation)
  or to regeneration of unchanged content (byte-stable → no diff; any
  unexpected diff means a generator drifted — investigate before commit).
- `python -m pytest tests/test_user_guide_hygiene.py -q` green.

### G9.3 — CHANGELOG completeness pass

- Diff this plan's completion log against `CHANGELOG.md`: every item flagged
  user-visible in its row must have a bullet under `[Unreleased]`; expected
  bullets: sidecar Added (S3), `--end` Fixed (S3), CLI-reference + README
  Changed (S3), H2/M4/default-alignment Fixed (S2), logging Fixed (S4),
  undo names Fixed (S8). Remove any bullet for a change that did not ship.
- `python -m pytest tests/test_user_guide_hygiene.py -q` green.

### G9.4 — Secret scan + worktree review

- `git add -A` (staging only — no commit unless the user asks), then the
  AGENTS secret gates:
  - `git grep --cached -n -i -E -I -e '[-_](key|secret|token|password|passwd|client)[^ ]*[=:][^A-Za-z0-9_][A-Za-z0-9+/=_-]{10,}'`
  - `git grep --cached -n -i -E -I -e '"[a-f0-9]{32}"'`
  - `git grep --cached -n -E -I -e '"[A-Za-z0-9+/]{44,}={0,2}"'`
  - `git grep --cached -n -E -I -e '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'`
  - Confirm `audio_suite_config.json` / `.key` / `.lock` are **not** staged.
- `git status --short` + `git diff --stat` reviewed: only planned files.

### G9.5 — Close the plan

- Mark every item `[x]`, fill the completion-log rows, append the deferred-
  backlog sign-off (below), and set the plan status line to complete.
- Session retrospective: transferable lessons proposed to the user for
  AGENTS.md (per global §11 — proposed, never applied silently).

**Completion-log row (S9):** G9.1–G9.5 evidence, final suite numbers, guide
regeneration audit, secret-scan output.

---

## Completion log (filled during execution — one row per item)

Format mirrors `PLAN_iteration8_remediation.md`:
`| Item | prio | date | gate evidence (command outputs) | notes |`

| Item | prio | date | gate evidence | notes |
|---|---|---|---|---|
| G1.1–G1.3 | 1 | 2026-10-06 | `utilities\run_gate.ps1` → `[OK] compileall`, `[OK] ruff check` (All checks passed), `[OK] ruff format --check` (794 files already formatted), `[OK] mypy` (0 issues / 461 source files), `[OK] bandit` (severity 0 High / 0 Medium / 41 Low), `[OK] pytest` (8493 passed, 3 skipped, 30 deselected, 8 warnings, 6m22s; coverage 89.39% ≥ 75), `[DONE] Phase Gate passed`, exit 0 | G1.2: dated correction appended to the I4 row of PLAN_iteration8_remediation.md. Bandit's step 5 command exits 1 whenever any finding survives its default LOW/LOW filter (verified, bandit 1.9.4), so the wrapper judges step 5 by the AGENTS 0 High / 0 Medium severity block, not the raw exit code; exit 2 (tool error) and an unparseable severity section fail loudly (controls: severity 0/0/41 parsed, confidence 23/18 not read, injected High=1/Medium=2 detected, missing section → fail). CI `security` job aligned to the same severity-block verdict, verified by running the block extracted verbatim from ci.yml under `bash -eo pipefail` (exit 0) — see D12. Guide/CHANGELOG updates: none (internal process change). |
| G2.1 | 1 | 2026-10-07 | Fix: `audio_suite_shared/suite_config.py::_file_lock` now calls `_invalidate_cache()` after the lock is acquired, before the `yield` (:87) — single insertion; `_save()` untouched (no deadlock), its own post-write invalidation unchanged. New `TestLostUpdateStaleCache` in `audio_suite_shared/tests/test_suite_config.py`; `pytest audio_suite_shared/tests -q` → 87 passed. **Negative control (plan-required, SHA-verified):** fix line removed via backup-copy round trip (SHA-256 `ED4F8EB843E1B95244F223839DB5F0C771DEBFD823EB6CCE0A57701318D40FA6` identical before/after) → `test_concurrent_process_save_survives_locked_read` FAILED with `lost-update: locked read clobbered a concurrent save: {'last_directory': 'ORIG', 'theme_mode': 'Dark'}` (the child process's `palette` write clobbered) while `test_single_process_roundtrip_still_works` passed → restored from the backup copy, SHA re-verified identical, re-run → 2 passed. Full S2 gate: `python -m compileall -q -f .` exit 0 (pydub SyntaxWarnings only); `ruff check .` All checks passed; `ruff format --check .` 797 files already formatted; `mypy .` 0 issues / 461 source files; bandit severity block 0 High / 0 Medium / 41 Low (exit 1 = any Low finding survives — verdict is the severity block per D12); bare `python -m pytest -q` → 8507 passed, 3 skipped, 30 deselected, 8 warnings, 384.13s; coverage 89.45% ≥ 75 | H2 closed. I1-era `_file_lock` tests (`test_i1_robustness.py:161,190`) unchanged and green in the full-suite run. CHANGELOG Fixed bullet added (stale-cache race). |
| G2.2 | 1 | 2026-10-07 | `_validate_lufs` click callback + permitted-values help added to `audio_normalizer/cli.py`, `audio_refinery/cli.py`, `replaygain_analyzer/cli.py` — none of the three imported `validate_target_lufs` at HEAD (the audit named two, the third found at planning; D4). New `test_cli.py` in each package (none existed; no `CliRunner` usage in any of the three at HEAD): `--target-lufs 999` → exit 2 + `Target LUFS must be one of`, permitted `-14` → exit 0 with no LUFS error, plus the default-preset check → `pytest audio_normalizer/tests/test_cli.py audio_refinery/tests/test_cli.py replaygain_analyzer/tests/test_cli.py -q` → 10 passed. Full gate green (same run as the G2.1 row) | M4 closed. All three option help strings now name the permitted values (`-12, -14, -16, -18, -23`). CHANGELOG Fixed bullet added (`--target-lufs` validation). |
| G2.3 | 1 | 2026-10-07 | D4 alignment: `audio_normalizer/utils/cli_args.py:39` `NormalizerArgs.target_lufs -16.0 → -14.0`; `replaygain_analyzer/cli.py` click `default=-14.0 → -16.0` (help `(default -16)`); `audio_refinery/utils/cli_args.py:73` re-verified `-16.0` — no change. Lockstep tests: `test_default_target_lufs_is_valid_preset` now pins `-14.0`, new `test_cli_arg_defaults_leave_gui_target_lufs_at_minus_14`, new `replaygain_analyzer/tests/test_cli.py::test_click_target_lufs_default_is_minus_16` (reads the option's `default` off the Command object). `pytest audio_normalizer/tests audio_refinery/tests replaygain_analyzer/tests -q` → 708 passed, 1 skipped; `git grep -n target_lufs` reviewed — every `-14`/`-16` occurrence is an explicit test input, a docstring example, or a verified-correct default (normalizer GUI var / arg record / click = −14; replaygain GUI var / arg record / click = −16; refinery = −16). Full gate green (same run as the G2.1 row) | D4 closed. **Guide audit (Sprint-S2 header): no generator edits needed** — `audio_normalizer/generate_guide.py:148` "The app default is -14.0." now true; refinery guide −16 correct; `CLI_Commands_Reference.md:116` (refine default −16.0) correct. CHANGELOG Fixed bullet added (LUFS default alignment). |
| G2.4 | 1 | 2026-10-07 | **G2.4a:** `metadata_scrubber/tests/test_app.py::test_live_completion_saves_tag_prefs` asserts `save_kept_tags.assert_called_once_with(_PACKAGE_DIR, ["BPM"])` (imported, not hardcoded) + completion label `Metadata Scrubbing Complete!`; `pytest metadata_scrubber/tests -q` → 201 passed; full-run coverage line `metadata_scrubber\app.py 180 35 81% — missing 78-79, 167-169, 172-173, 176-177, 208-225, 228-233, 241-242, 360-363, 386-395` (line 369 no longer missing — recorded per plan). **G2.4b:** AST sweep over 234 files / 7381 test functions → 202 flagged (76 ONLY_NEG + 4 OTHER_ALL_NEG + 122 KEEPS); after the edits 132 remain flagged with an **empty fix set**: 70 no longer flagged, 8 ONLY_NEG→KEEPS, 122 KEEPS→KEEPS, and only 2 flagged functions survive — both dispositioned keeps (`metadata_scrubber/tests/test_app.py:362` plan-excused negative contract with its positive sibling; `cd_ripper/tests/test_cli.py:428` reclassified KEEPS — `result.exit_code == 0` is a positive outcome). Totals **78 fixed / 124 keeps = 202**; full disposition table below. `master_driver/tests/test_app.py::test_poll_inert_for_fixed_palette` extended with the positive phase (palette → Windows Accent → `_accent_poll_active is True`, `root.after.assert_called_once()`); `pytest master_driver/tests/test_app.py -q` → 33 passed. Bare full-suite run green: 8507 passed, 3 skipped, coverage 89.45% (full gate tuple in the G2.1 row) | M5 closed. CHANGELOG: exactly 3 Fixed bullets added per plan (H2 race, `--target-lufs` validation, LUFS default alignment); G2.4b is test-only work → no bullet. Guide generators audited — no change needed (see G2.3 row). |
| G3.1 | 1 | 2026-10-07 | New lock test: `tests/test_cli_reference_hygiene.py` (5 tests). **Pre-fix red run (5 mismatches):** line 18: `(default: dry)` → `(default: live)` (album-genre); line 40: `(default: dry)` → `(default: live)` (album-art); line 58: `(default: dry)` → `(default: live)` (asx-extract); line 103: `(default: all five)` → `(default: declick,trim,enhance,normalise)` (refine --stages); line 237: `(default: dry)` → `(default: live)` (lyrics). **Post-fix green:** 5 passed. Gate steps 1–5 green: compileall 0, ruff check clean, ruff format 798 files, mypy 0/461, bandit 0H/0M/41L. `audio_suite_shared/tests + tests/` = 2568 passed, 2 skipped. | M2 closed. Lock test introspects click defaults for all 5 dry/live claims, stages default, and 20+ long-flag existence assertions. `BaseCommand` → `Command` for Click 9.0 compatibility. |
| G3.2 | 2 | 2026-10-07 | 4 bullets added under `## [Unreleased]` in `CHANGELOG.md`: Added (local `.lrc` sidecar lyrics provider), Fixed (`--end`/auto-close honoured in Noise Reduction and Pop & Click Remover), Changed (CLI reference defaults corrected), Changed (README verification metric reworded). Wording verified against PLAN_iteration8_remediation.md I4 and C9. Sidecar wording uses "co-located" (not "before network providers") — the provider is selected, not chained (zero-assumption correction). `tests/test_user_guide_hygiene.py` 11 passed. | M3 closed. |
| G3.3 | 2 | 2026-10-07 | `README.md:225`: replaced "over 452 files" with "across the whole suite". `tests/test_readme.py` 11 passed (before and after). `git grep -in '452' README.md` → 0 hits. | M9 closed. |
| G4.1–G4.5 | 2 | 2026-10-08 | **G4.1** — new `audio_suite_shared/logging_setup.py` (stdlib-only, Tk-free, docstring states the Tk-free requirement) receiving `_HOOK_MARKER`, `_log_uncaught`, `_log_fatal_exception`, `_log_thread_exception`, `_install_excepthooks`, `configure_logging`; `app_bootstrap.py` deleted the moved block, drops the now-unused `logging.handlers`/`sys`/`tempfile`/`threading`/`Path` imports, re-exports `configure_logging as configure_logging` (plus `_log_uncaught`, used by `_log_tk_callback_exception`), and its module docstring no longer claims configure_logging is "the only addition". **Lock:** `test_cli_helpers_ast_lock.py` — `test_configure_logging_lives_only_in_app_bootstrap` replaced by `test_configure_logging_is_defined_only_in_logging_setup` (`_RELOCATED_OWNER` defined in `_RELOCATED_MODULE` only) and `test_app_bootstrap_reexports_configure_logging_without_redefining` (exactly one `as configure_logging` import-alias in `app_bootstrap`, no `def`, `definitions` lookup empty); `_BOOTSTRAP_MODULE` added. `tests/test_package_entry_stubs.py:233` (`monkeypatch.setattr(bootstrap_pkg, "configure_logging", …)`) green unchanged — the re-export keeps the attribute. **G4.2** — `configure_logging(program_name, *, min_level=logging.DEBUG)` attaches its `RotatingFileHandler` to every first-party package logger from `_first_party_package_names()` (suite-root dirs carrying `__init__.py`; `tests` excluded **by name** — see note) with a per-package membership guard, level-pinned to `min_level`; root logger and third-party loggers untouched, `audio_suite` double-attach impossible (no dir named `audio_suite`). Handler resolution is keyed on *the* `RotatingFileHandler` rather than `handlers[0]`, so a caller's in-memory handler can neither suppress file creation nor end up on the package loggers (behaviour-preserving refinement of the idempotency guard; no existing test pinned the old shape). **G4.3** — `cli_base.cli()` hoists `level = getattr(logging, log_level.upper(), logging.WARNING)` and calls `configure_logging("audiosuite_cli", min_level=level)` immediately after `logging.basicConfig`; no `app_bootstrap` import. New `TestCliSuiteLogging::test_cli_invocation_wires_suite_logging` in `test_cli_base.py` patches `cli_base.configure_logging` (module-level import, so the patch binds) and invokes `["--log-level", "INFO", "stats", "--help"]` through the real group (`cli_app.cli is cli_base.cli` asserted, since `cli_app` registers the subcommands), asserting `("audiosuite_cli",)` and `min_level == logging.INFO`. **G4.4** — new `audio_suite_shared/tests/test_logging_setup.py`, 5 tests: package record reaches the file (marker read from `_suite_file_handler().baseFilename`, 2 s retry), third-party record absent **with an in-test first-party positive control** (so a dead handler cannot make it pass vacuously), idempotent (exactly one suite handler per package logger after two calls), `min_level=logging.WARNING` blocks `.info()` but passes `.warning()`, plus a non-vacuity scan-subject assertion. Autouse fixture removes every suite `RotatingFileHandler` from all package loggers and restores `logging.NOTSET` **before and after** each test (E1/shared-state rule). `pytest audio_suite_shared/tests/test_logging_setup.py -q` → 5 passed **twice consecutively**. **G4.5** — new `user_guides/suite_overview/generate_logging_system_guide.py` (output resolved relative to `__file__`, no absolute path committed; sample log lines rendered by `example_line()` mirroring the real formatter spec so they cannot drift) regenerating `LOGGING_SYSTEM_GUIDE.docx`, which was stale (claimed `audio_suite_1.log`…`audio_suite_5.log`, `Program started:` lines, 19-program coverage, `ERROR TYPE:` blocks). Guide grep-audit (`git grep` over `user_guides/**/generate_*.py` for suite-log claims): **audited, no stale claims falsified by G4.2** — `tempo_analyzer` and `mood_analysis_batch_tagger` document their own per-tool `.txt` logs, `master_driver` only says it "configures logging", and `tag_field_updater:279`'s "unified log directory" claim is now accurate rather than aspirational. Not registered in `guide_to_program` (`test_no_logging_guide_is_registered` rejects a "Logging" key); hygiene tests green. CHANGELOG: 1 Fixed bullet under `[Unreleased]`. **Gate:** `utilities\run_gate.ps1` exit 0 → `[OK] compileall`, `[OK] ruff check` (All checks passed), `[OK] ruff format --check` (801 files already formatted), `[OK] mypy` (0 issues / 462 source files), `[OK] bandit` (severity 0 High / 0 Medium / 41 Low — verdict by severity block per D12), `[OK] pytest` (8519 passed, 3 skipped, 30 deselected, 8 warnings, 281.89s; coverage 89.45% ≥ 75), `[DONE] Phase Gate passed` | **M1 closed.** Count reconciles: 8507 (post-S2) + 5 (S3 `test_cli_reference_hygiene`) + 7 (S4: 5 `logging_setup` + 1 `cli_base` + 1 ast-lock split) = 8519. **Lock-test update rationale:** the old lock pinned *the file* `configure_logging` lived in; extraction moves that file, so the lock was rewritten to pin the new contract (exactly one definition site + one explicit-alias re-export) rather than deleted — preserving its intent that Tk and headless entry points share one implementation. **Plan discrepancy (recorded at execution):** G4.2 assumed `tests` dirs fall out via the `__init__.py` test; the repo-root `tests/` *does* carry `__init__.py`, so discovery excludes `tests` by name instead. **Stale-comment defects found during G4.1/G4.2 and fixed in the same change** (AGENTS §7): `error_logger.py` migration note claimed `getLogger(__name__)` "never reach[es] the RotatingFileHandler" (false for first-party packages since G4.2) and two `app_bootstrap`-only rotation references; `exceptions.py` module-logger comment ("never reach logs/audio_suite.log"); `test_exceptions.py::test_error_record_reaches_audio_suite_logger` docstring; `test_logging_namespacing.py` module docstring (post-G4.2 note added; the namespace lock itself is unchanged and still enforced — `_RUNTIME_NAMED_MODULES` gains `logging_setup.py` with the reason, since its non-literal `getLogger(pkg_dir.name)` is the deliberate out-of-namespace case). Guide updates: `LOGGING_SYSTEM_GUIDE.docx` only; no other user-facing guide required a change. |
| G5.1 | 2 | 2026-10-08 | 4 merges + 1 rename, sources deleted, every merge counted: (1) `bpm_analyzer/tests/test_app_audio_detection.py` (8 tests) appended into `test_app.py` (11→19) → deleted; (2) `asx_extractor/tests/test_app_run.py` (9) into `test_app.py` (24→33) → deleted, stale filename reference fixed at `test_app.py:6`; (3) `asx_extractor/tests/test_cli_run.py` (8) into `test_cli.py` (7→15) → deleted; (4) `audio_fingerprinter/tests/test_fingerprinter_app.py` (11) into `test_app.py` (10→21, `TOOL_ID` assertions kept) → deleted; (5) `audio_fingerprinter/tests/test_fingerprinter_cli.py` → `test_cli.py` pure rename (`git diff --cached` = 0; no live references — PLAN/docs mentions are historical). No class-name collisions (appended classes: `TestPreflightAudioDetectionRegression`, `TestRunCopyFailureHandling`, `TestRunDirectoryScan`, `TestRunCliExtraction`, `TestAppClassDefinition`, `TestOnProgress`, `TestStartProcessingAlbumMode`, `TestOnCompleteSummary`) so no de-duplication prefixes were needed. **Acceptance (plan: record before/after):** `pytest bpm_analyzer/tests asx_extractor/tests audio_fingerprinter/tests --co -q` → **529 collected on a clean HEAD (d98d45f) worktree before / 529 after** — per-package: bpm 19/19, asx 48/48, fp net-zero by rename. ruff check + format clean on all touched files; full gate green (tuple in the G5.4 row). | M6 execution (5 of 35 in-scope violations, the clear duplicates per D6). Classes/tests moved unmodified apart from import fixes; all five source files staged as D/R. |
| G5.2 | 2 | 2026-10-08 | New `tests/test_test_file_naming.py` — **9 tests, green**: pure matcher unit-tested with synthetic paths (the matcher itself cannot rot); scan of every package `tests/test_*.py`; frozen `ALLOWLIST` = exactly the 30 plan entries each with a one-line rationale, asserted `len(ALLOWLIST) == 30` (silent growth fails) and every entry still exists (dead entries fail); violations outside the allowlist fail naming the file. Measured: **227 scanned, 30 violations = exactly the 30 allowlisted, 0 unexpected**. **Plan deviation (recorded as briefed): the plan's `assert scanned >= 840` is unreachable** — the repo holds 243 on-disk `test_*.py` in total and 227 under package `tests/` trees (consistent with D3's re-measurement of M6 at 35 in-scope files), so the non-vacuity floor is `>= 220` with an in-file comment documenting the measured reality; 840 could only pass by counting files that do not exist. **Negative control (plan-required):** `album_genre_tagger/test_tag_io` removed from the allowlist → **2 failed** (frozen-count test + violation scan — both the expected tests) → restored from SHA-256-verified backup (`EE9D1FEB634BCB45C00EF9D01800A8F6D3E87BB2B767C7B2D9E4F9804DCAB900` before == after) → re-run **9 passed**. | M6 closed by lock. Root `tests/` exempt from the rule it enforces (its files are cross-cutting by design, D6); the classifier and floor live in the test file for future re-derivation. |
| G5.3 | 3 | 2026-10-08 | **L1's 5 sites context-managed:** `tests/test_pyproject_config.py` ×4 and `tests/test_readme.py:115` → `with <path>.open("rb") as fh: ... tomllib.load(fh)`; `git grep 'load(open('` → **0 hits** repo-wide. **Acceptance extended per plan ("if a warning remains, trace and fix it in the same item"):** the first full run still showed 8 warnings — `PYTHONTRACEMALLOC=6` proved they were **not** tomllib but 7 × `sqlite3` "unclosed database" ResourceWarnings: 6 test call-sites (one-liner `BatchUndoLog(...).get_batch_records()/list_batches()` in `audio_normalizer/tests/test_normalizer_core.py:975`, `audio_refinery/tests/test_pipeline_stages.py:358`, `replaygain_analyzer/tests/test_replaygain_pipeline.py:1084`, `lyrics_manager/tests/test_cli.py:257`, two lambdas in `audio_suite_shared/tests/test_undo_gui.py`) plus **one production leak** — `library_stats/core/file_processor.py:749 scan_directory()` creates its own `LibraryCache` and never closes it. All 7 fixed (`with BatchUndoLog(...) as opened:` / closing local helpers; production gains `owns_cache` + `try/finally: cache.close()` only when it created the cache — caller-supplied caches stay open). **Two further defects found while tracing — user-approved scope extension (D13):** (a) `test_app_bootstrap.py::_clear_audio_suite_handlers` cleared only the `audio_suite` logger, leaving G4.2's shared `RotatingFileHandler` open on every package logger, so each later `configure_logging` added a **second** open handle on `logs/audio_suite.log`; the first rollover died with a Windows rename PermissionError and `handleError` wrote `--- Logging error ---` tracebacks into CliRunner's captured stderr — the root cause of the intermittent `test_artnormalize_reaches_its_engine_unstubbed` / `test_json_output_matches_sheet` / `test_json_output` full-run failures. Fixed: the helper now removes **and closes** every suite file handler across the suite + all first-party package loggers; regression `TestClearAudioSuiteHandlers::test_clear_detaches_and_closes_the_shared_handler` asserts closure, detachment everywhere, and a single fresh shared handler on the next `configure_logging`. (b) `library_stats/cli.py` never closed the `LibraryCache` it owned → `finally: cache.close()` (`elapsed`/`cache_info` moved inside the try so the timing surface is unchanged); regression `test_incremental_run_closes_the_cache_it_created` (spy subclass; `closed[0]._conn is None`). **Negative controls — both SHA-256-verified backup-copy restores, no `git checkout`:** (a) old helper body restored (`81C3F491842CA4E099AACC80254DFD86751C0721824AF10F0614A7EC8A1C3C7E`) → test **FAILED** → restore re-verified identical → green; (b) `finally` removed (`73C2475A080D37D071E0038358475DC574C46AE6E39C20EF53B4F38571A5033B`) → test **FAILED** (`the CLI-created cache was never closed: assert 0 == 1`) → restore re-verified identical → green. **Result: full-suite warnings 8 → 0.** | L1 closed (5 tomllib sites) + 7 sqlite leaks + 2 approved defect fixes (D13), each with a lockstep regression test; no `# type: ignore`, no skips. |
| G5.4 | 3 | 2026-10-08 | **Skip-reason table** — all 3 reasons non-empty and attributable: (1) `audio_normalizer\tests\test_setup_tab.py:161` — "Slider update failed — broken Tcl/Tk environment" (documented conditional env skip); (2) `audio_suite_shared\tests\test_input_validator.py:321` — "Symlink creation unavailable on this platform"; (3) `audio_suite_shared\tests\test_key_manager.py:67` — "Unix-only permission check". **Deselection contract 30 = 30:** `python -m pytest -q -m hardware --co` → `30/8563 tests collected` — the 30 hardware-marked tests are exactly the 30 deselected by addopts' `-m "not hardware"`. **0 warnings** confirmed in the gate run (from G5.3). **Stable pass count:** total collection 8552 at clean HEAD (d98d45f) → 8563 now = **+11 exactly** (9 new G5.2 lock tests + 2 new D13 regression tests; G5.1 merges net zero per the 529/529 proof). Full gate `utilities\run_gate.ps1`: `[OK] compileall`, `[OK] ruff check` (All checks passed), `[OK] ruff format --check`, `[OK] mypy` (Success: no issues found in 462 source files), `[OK] bandit` (severity 0 High / 0 Medium / 41 Low — documented subprocess call sites), `[OK] pytest` (**8530 passed, 3 skipped, 30 deselected, 0 warnings**, 277.33s; coverage **89.46%** ≥ 75 required, S9 floor 88.0 met), `[DONE] Phase Gate passed`, exit 0 | L5 closed. Guides/CHANGELOG: none (test-only scope; the two D13 fixes are internal resource/handler leaks with no user-visible behaviour — audited, no guide text or CHANGELOG bullet covers them). |
| G6.1–G6.6 | 3 | 2026-10-08 | Per-module coverage (`COVERAGE_FILE=.coverage.sprint6`): G6.1 `cd_ripper/ui/metadata_config_panel.py` 88 stmts / 1 miss / 99% (miss line 149 = dead return), target ≥80%; G6.2 `cd_ripper/ui/results_tab.py` 87 stmts / 0 miss / 100%, target ≥80%; G6.3 `cd_ripper/ui/drive_config_panel.py` 168 stmts / 0 miss / 100%, target ≥80%; G6.4 `lyrics_manager/app.py` 229 stmts / 1 miss / 99% (miss line 120 = unreachable `raise AudioConfigurationError`), target ≥85%; G6.5 `master_driver/ui/refinery_tab.py` 101 stmts / 7 miss / 93% (miss 58-62 unreachable `_browse_out` body + 177-178 defensive `except`), target ≥80%; G6.6 `metadata_scrubber/app.py` 180 stmts / 0 miss / 100%, target ≥85%. Full gate `utilities\run_gate.ps1`: `[OK] compileall`, `[OK] ruff check` (All checks passed), `[OK] ruff format --check` (800 files already formatted), `[OK] mypy` (Success: no issues found in 462 source files), `[OK] bandit` (severity 0 High / 0 Medium / 41 Low), `[OK] pytest` (8625 passed, 3 skipped, 30 deselected, 0 warnings, 268.10s; coverage 90.56% ≥ 75), `[DONE] Phase Gate passed`, exit 0 | M11 closed. 95 new tests across 6 test files. D14: `cd_ripper/ui/drive_config_panel.py` `_run_c2_diagnostic` except tuple extended `(OSError, RuntimeError)` → `(AudioSuiteError, OSError, RuntimeError)` — regression test `test_audio_io_error_is_handled` asserts `showerror` fires and no exception propagates. `.coverage.sprint6` deleted. |
| G7.1 | 2 | | | |
| G7.2 | 2 | | | |
| G7.3 | 3 | | | |
| G7.4 | 3 | | | |
| G8.1 | 2 | 2026-10-09 | **M10 code fix:** `audio_suite_shared/undo_gui.py` `_TOOL_DISPLAY_NAMES` — added `audio_fingerprinter`→"Audio Fingerprinter", `lyrics_manager`→"Lyrics Manager", `silence_trimmer`→"Silence Trimmer", `tag_editor`→"Tag Editor" (manifest-exact); corrected `asx_extractor` "ASX Extractor"→"ASX Playlist Extractor", `file_reorganizer` "File Reorganizer"→"Tag-Based File Reorganizer". New `TestToolDisplayNamesMatchesManifest` in `audio_suite_shared/tests/test_undo_gui.py` (AST scan of production files only: literal first args of `active_batch`/`set_active_batch` + `TOOL_ID`/`_TOOL_ID`/`TOOL_NAME` on `Assign` **and** `AnnAssign`; asserts every collected id ∈ map, non-vacuity ≥22 plus the four new ids, manifest agreement; `audio_enhancer` EXEMPT — suite_config preset namespace, never passed to `active_batch`). Collected-id list (24) in the subsection below. Full gate `utilities\run_gate.ps1` (exit 0): `[OK] compileall`; `[OK] ruff check` (All checks passed); `[OK] ruff format --check` (803 files already formatted); `[OK] mypy` (Success: no issues found in **469 source files** — was 462; +7 utilities scripts now type-checked); `[OK] bandit` (severity 0 High / 0 Medium / 41 Low); `[OK] pytest` (8694 passed, 3 skipped, 30 deselected, 1 warning in 280.26s; coverage 90.43% ≥ 88.0); `[DONE] Phase Gate passed`, exit 0 | M10 closed. `friendly_tool_name` keeps its `.get(..., ...)` fallback (unknown ids such as "mystery_tool"). Empirical sweep of the other 17 pre-existing keys vs the manifest `name`: all already matched — no further mismatch. The single pytest warning is a pre-existing Tk `Variable.__del__` GC race (see note after the S8 subsections), not introduced by this item. |
| G8.2 | 2 | 2026-10-09 | `git grep -n 'ASX Extractor\|File Reorganizer' user_guides/` audited hit-by-hit (disposition table in the subsection below). Only `suite_overview/generate_presentation.py:1929` was a stale tool name in a name list → set to "Tag-Based File Reorganizer" and regenerated `AudioSuite-Pro_New_User_Presentation.pptx` (24 slides; slide 18 re-read from the artifact and verified to show "Tag-Based File Reorganizer", no bare "File Reorganizer" remains). `master_driver/generate_guide.py:118` and `undo_tag_edits/generate_guide.py:51` already read the manifest name — grep matched only the tail fragment of a name split across adjacent string literals; no edit. `file_reorganizer/generate_guide.py` title/self-refs kept per plan (D-scope); `README.md`, `asx_extractor/generate_guide.py`, `CLI_Commands_Reference.md` already manifest-exact → audited, left as-is. `pytest tests/test_user_guide_hygiene.py -q` → 11 passed; `git status --short user_guides/` → only the presentation and its generator. | M10 guide audit closed. **Blocker resolved under user decision:** `generate_presentation.py` imports `pptx`, but `python-pptx` was undeclared (only `python-docx` is a declared dev dep). To regenerate the artifact it was first installed into `.venv`; then, on the user's explicit instruction, **declared** as `python-pptx>=1.0.0` in the `dev` optional-dependency and `uv.lock` regenerated (see G8.4) — the generator's import is now backed by a declared dependency rather than an ad-hoc install. |
| G8.3 | 3 | 2026-10-09 | Inspected `audio_suite_shared/suite_config.py`: `_LOCK_PATH = CONFIG_PATH.with_suffix(".json.lock")` (`:59`) and `_save` writes `CONFIG_PATH.with_suffix(f".json.tmp.{os.getpid()}")` (`:178`) then `os.replace` — both sidecars are real (singleton lock + PID-scoped atomic-write temp). `.gitignore` "Project-specific" gained exactly `audio_suite_config.json.lock` and `audio_suite_config.json.tmp.*` (verified via `git grep -n lock -- .gitignore`). Stray root `audio_suite_config.json.lock` deleted; after the full gate (which exercises config saves and recreated it) `git status --short` shows **neither** the lock nor any `.json.tmp*` entry. | L2 closed. No `.tmp` pattern invented — both patterns match the code paths exactly. |
| G8.4 | 3 | 2026-10-09 | `pyproject.toml` — three L4 edits **plus one user-authorized addition** (full diff in the subsection below): removed `"^utilities/",` from `[tool.mypy] exclude`; removed `"utilities/*",` from `[tool.coverage.run] omit`; added `"utilities",` to `source`; and, per the user's explicit decision, added `"python-pptx>=1.0.0"` to the `dev` optional-dependency with `uv.lock` regenerated (+python-pptx 1.0.2, +xlsxwriter 3.2.9) — so `generate_presentation.py`'s `pptx` import is declared. Real annotations added to the seven scripts (no `# type: ignore`, no re-exclusion, no new third-party override). `mypy .` → 0 issues in **469 source files** (was 462). Post-L4 `utilities/*.py` coverage measured from the bare full run (`COVERAGE_FILE=.coverage.s8`): `generate_readme_platform_matrix.py` 46%→**100%**, `generate_readme_tool_index.py` 58%→**100%**, `strip_bom.py` 42%→**100%**, `verify_refinery_log.py` 0%→**98%** (3 miss: 293-294, 385); unchanged `rebuild_refinery_log.py` 86%, `undo.py` 80%, `resize_music_recursive.py` 60% (not below the 60% threshold → no tests added, per plan). Four test files added/edited; `utilities/tests` 54→**110 passed**. Total coverage **90.43%** ≥ 88.0 (S1 baseline 89.39; newly measured utilities diluted then lifted it above the floor). | L4 closed. Tests added only for scripts below 60% (platform-matrix 46%, tool-index 58%, strip-bom 42%, verify-refinery-log 0%). The `if __name__ == "__main__":` bodies stay unmeasured via the existing `exclude_lines`. **Acceptance deviation (authorized):** `git diff pyproject.toml` shows **four** edits, not the planned three — the three L4 edits are present as planned plus the user-requested `python-pptx` dev-extra declaration (and `uv.lock`); this was an explicit user decision, recorded here rather than retro-editing the acceptance text above. |
| G9.1–G9.5 | 1 | | | |

### G2.4b disposition table — 202 originally-flagged functions

Triage basis: AST sweep of `*/tests/test_*.py` — 234 files,
7381 test functions, 202 flagged (76 `ONLY_NEG`, 4 `OTHER_ALL_NEG`,
122 `KEEPS`). Post-edit re-triage: 70 no longer flagged, 8
`ONLY_NEG → KEEPS`, 122 `KEEPS → KEEPS`, 1 `ONLY_NEG →
ONLY_NEG` (dispositioned), 1 `OTHER_ALL_NEG → OTHER_ALL_NEG`
(dispositioned); totals **78 fixed / 124 keeps = 202**. Format:
`file:line:function || disposition`.

```text
album_art_normalizer/tests/test_album_art_normalizer.py:860:test_flac_dry_run_previews_without_embedding || keeps: positive outcome assertion (assert: path.read_bytes() == before | assert: "dry run" in result | assert: "saved" not in result)
album_art_normalizer/tests/test_album_art_normalizer.py:883:test_generic_dry_run_previews_without_embedding || keeps: positive outcome assertion (assert: path.read_bytes() == before | assert: "dry run" in result | assert: "saved" not in result)
album_art_normalizer/tests/test_album_art_normalizer.py:835:test_mp3_dry_run_previews_without_embedding || keeps: positive outcome assertion (assert: path.read_bytes() == before | assert: "would be resized to 800×800" in result | assert: "dry run" in result | assert: "saved" not in result)
album_art_normalizer/tests/test_art_writer.py:57:test_unsupported_extension_raises_format_error || keeps: positive outcome assertion (pytest.raises(...))
album_art_sync/tests/test_album_art_sync.py:3176:test_apply_cli_args_returns_early_when_no_folder || fixed: added positive assertion assert_called_once_with: mock_handler_cls.assert_called_once_with(app)
album_art_sync/tests/test_album_art_sync.py:3274:test_apply_preset_handles_empty_dict || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
album_art_sync/tests/test_album_art_sync.py:2570:test_directory_does_not_exist_logs_error_and_returns || keeps: positive outcome assertion (assert: "Directory does not exist" in "".join(app._log_entries))
album_art_sync/tests/test_album_art_sync.py:1499:test_embed_artwork_not_called_in_dry_run || fixed: added positive assertion assert_any_call: dry_log.assert_any_call(" [Dry Run] Would embed artwork in 1 files")
album_art_sync/tests/test_album_art_sync.py:1685:test_empty_files_list_returns_true_without_progress_calls || keeps: positive outcome assertion (assert: result is True)
album_art_sync/tests/test_album_art_sync.py:1089:test_falls_through_to_deezer_when_fanart_fails || keeps: positive outcome assertion (assert: img == b"DEEZER" | assert: source == "Deezer")
album_art_sync/tests/test_album_art_sync.py:1107:test_falls_through_to_itunes_as_last_resort || keeps: positive outcome assertion (assert: img == b"ITUNES" | assert: source == "iTunes Store")
album_art_sync/tests/test_album_art_sync.py:3523:test_maybe_auto_end_does_nothing_when_disabled || fixed: added positive assertion assert_any_call: app.root.after.assert_any_call(2000, app.root.destroy)
album_art_sync/tests/test_album_art_sync.py:2589:test_metadata_read_failure_logs_error_and_returns || keeps: positive outcome assertion (assert: "Error reading file metadata" in "".join(app._log_entries))
album_art_sync/tests/test_album_art_sync.py:1398:test_no_caa_lookup_without_a_release_id_or_mb_ids || keeps: positive outcome assertion (assert: img is None | assert: source is None)
album_art_sync/tests/test_album_art_sync.py:2580:test_no_supported_files_logs_error_and_returns || keeps: positive outcome assertion (assert: "No supported audio files found" in "".join(app._log_entries))
album_art_sync/tests/test_album_art_sync.py:3391:test_on_delete_preset_decline_is_noop || fixed: added positive assertion assert_called_once_with: mock_askyesno.assert_called_once_with( "Delete Preset", "Delete preset 'Old Preset'?", parent=app.root )
album_art_sync/tests/test_album_art_sync.py:3414:test_on_delete_preset_empty_name_is_noop || fixed: added positive assertion assert_called_once_with: app._preset_combo.get.assert_called_once_with()
album_art_sync/tests/test_album_art_sync.py:3424:test_on_delete_preset_preset_not_in_store || fixed: added positive assertion assert_called_once_with: mock_load.assert_called_once_with()
album_art_sync/tests/test_album_art_sync.py:3304:test_on_preset_selected_unknown_name_is_noop || fixed: added positive assertion assert_called_once_with: mock_load.assert_called_once_with()
album_art_sync/tests/test_album_art_sync.py:3335:test_on_save_preset_empty_name_is_cancelled || fixed: added positive assertion assert_called_once_with: mock_askstring.assert_called_once_with( "Save Preset", "Enter preset name:", parent=app.root )
album_art_sync/tests/test_album_art_sync.py:3359:test_on_save_preset_none_is_cancelled || fixed: added positive assertion assert_called_once_with: mock_askstring.assert_called_once_with( "Save Preset", "Enter preset name:", parent=app.root )
album_art_sync/tests/test_album_art_sync.py:3347:test_on_save_preset_whitespace_name_is_cancelled || fixed: added positive assertion assert_called_once_with: mock_askstring.assert_called_once_with( "Save Preset", "Enter preset name:", parent=app.root )
album_art_sync/tests/test_album_art_sync.py:1143:test_returns_none_immediately_when_cancelled_after_mb || keeps: positive outcome assertion (assert: img is None | assert: source is None)
album_art_sync/tests/test_album_art_sync.py:998:test_returns_none_on_generic_request_exception || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:670:test_returns_none_on_timeout || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:1022:test_returns_none_on_unexpected_exception || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:764:test_returns_none_when_empty_results || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:660:test_returns_none_when_no_results || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:887:test_returns_none_with_empty_mb_ids || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:871:test_returns_none_with_no_api_key || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_album_art_sync.py:1162:test_skips_fanart_and_caa_when_no_mb_ids || keeps: positive outcome assertion (assert: source == "Deezer")
album_art_sync/tests/test_album_art_sync.py:2892:test_start_thread_noop_when_no_folder_selected || fixed: added positive assertion assert_called_once_with: app.folder_path.get.assert_called_once_with()
album_art_sync/tests/test_album_art_sync.py:2907:test_worker_ui_writes_are_scheduled_on_main_thread || keeps: positive outcome assertion (assert: app._append_log_line in callbacks | assert: app._apply_status in callbacks | assert: app._apply_progress in callbacks | assert: app._apply_result in callbacks | assert: app._apply_controls in callbacks | assert: any( entry[1] == app._apply_status and entry[2] == "Searching for artwork..." for entry in | assert: any( entry[1] == app._apply_result and entry[2] == "Sync Complete via Deezer" for entry in)
album_art_sync/tests/test_caa.py:291:test_404_on_every_lookup_returns_none_and_never_offers_a_pick || keeps: positive outcome assertion (assert: result is None | assert: mock_http.get.call_count == 2)
album_art_sync/tests/test_caa.py:340:test_images_without_a_url_are_not_offered_as_candidates || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_caa.py:668:test_malformed_json_is_a_miss_not_a_crash || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_caa.py:269:test_no_ids_returns_none_without_any_request || keeps: positive outcome assertion (assert: result is None | assert: any( "no MusicBrainz ids" in call.args[0] for call in noop_log.call_args_list ))
album_art_sync/tests/test_caa.py:620:test_transport_errors_fall_through || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_caa.py:582:test_undersized_front_is_rejected_by_the_real_filter || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_caa.py:367:test_whitespace_only_mbid_is_skipped_without_a_request || keeps: positive outcome assertion (assert: result is None)
album_art_sync/tests/test_pipeline.py:456:test_caa_release_hit_short_circuits_every_other_source || keeps: positive outcome assertion (assert: report.success is True | assert: report.source == "Cover Art Archive" | assert: mock_caa.call_args.kwargs["release_mbid"] == self.RELEASE_MBID | assert: mock_caa.call_args.kwargs["mb_rg_ids"] == [])
album_genre_tagger/tests/test_app.py:371:test_empty_dict_does_nothing || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
album_genre_tagger/tests/test_app.py:245:test_every_callback_schedules_its_main_thread_helper || keeps: positive outcome assertion (assert: callbacks == [ app._update_phase1_ui, app._append_phase2_text, app._show_coverage_fail, ap | assert: zero_delay[0][2:] == (1, 3, 1, 0, "display") | assert: zero_delay[1][2:] == ("display2",) | assert: zero_delay[4][2:] == ("boom",))
album_genre_tagger/tests/test_app.py:121:test_no_handler_or_scheduling_without_folder || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
album_genre_tagger/tests/test_app.py:419:test_none_return_does_not_apply || fixed: added positive assertion assert_called_once_with: mock_sc.load_preset.assert_called_once_with( "album_genre_tagger", "Missing Preset" )
album_genre_tagger/tests/test_app.py:225:test_run_schedules_its_header_instead_of_writing_widgets || keeps: positive outcome assertion (assert: self._scheduled(app) == [(0, app._reset_progress_ui)])
album_genre_tagger/tests/test_app.py:989:test_writes_log_entries_to_file || keeps: positive outcome assertion (assert: log_file.read_text(encoding="utf-8") == "line 1\nline 2\n")
asx_extractor/tests/test_app.py:90:test_does_nothing_when_run_mode_absent || fixed: added positive assertion assert_called_once_with: tool.asx_action_mode.set.assert_called_once_with( "Execute Extraction (Permanent)" )
asx_extractor/tests/test_app.py:95:test_empty_dict_is_a_noop || fixed: added positive assertion assert_called_once_with: tool.asx_action_mode.set.assert_called_once_with( "Execute Extraction (Permanent)" )
asx_extractor/tests/test_app.py:329:test_log_write_success_does_not_show_error || fixed: added positive assertion assert_called_once: mock_log.assert_called_once()
asx_extractor/tests/test_app_run.py:118:test_copy_failure_prevents_asx_removal_and_is_logged_as_failure || keeps: positive outcome assertion (assert: "SUCCESSFUL EXTRACTIONS (0)" in log_text | assert: "FAILURES (1)" in log_text | assert: "COPY FAILED" in log_text | assert: asx.exists())
asx_extractor/tests/test_app_run.py:249:test_dry_run_never_calls_copy_or_remove || keeps: positive outcome assertion (assert: "SUCCESSFUL EXTRACTIONS (1)" in log_text)
asx_extractor/tests/test_cli_run.py:92:test_copy_failure_records_copy_failed || keeps: positive outcome assertion (assert: calls["errors"] == 1 | assert: calls["failures"] == 1)
asx_extractor/tests/test_cli_run.py:154:test_dry_run_skips_copy_and_remove || keeps: positive outcome assertion (assert: "Dry Run" in mode)
audio_enhancer/tests/test_app.py:688:test_cli_args_live_mode_none_does_not_set_run_mode || fixed: added positive assertion assert_called_with: app.run_mode.set.assert_called_with("Dry Run")
audio_enhancer/tests/test_app.py:426:test_thread_not_started_for_invalid_source || fixed: added positive assertion assert_called_once: mock_warn.assert_called_once()
audio_fingerprinter/tests/test_acoustid_client.py:696:test_empty_input_returns_empty || keeps: positive outcome assertion (assert: results == [])
audio_fingerprinter/tests/test_file_processor.py:524:test_album_mode_defers_lookup_to_cluster_phase || keeps: positive outcome assertion (assert: result.status == "ANALYSED" | assert: "album matching" in result.message)
audio_fingerprinter/tests/test_file_processor.py:1055:test_album_mode_opt_in_writes_real_mbid_tags || keeps: positive outcome assertion (assert: complete.call_args.kwargs["counts"]["tagged"] == 3 | assert: tags["MUSICBRAINZ_TRACKID"] == self.TRACK_ID | assert: tags["MUSICBRAINZ_ARTISTID"] == self.ARTIST_ID | assert: tags["MUSICBRAINZ_ALBUMID"] == f"rel-{name}")
audio_fingerprinter/tests/test_file_processor.py:788:test_album_tag_tie_break_decides_and_writes_real_tags || keeps: positive outcome assertion (assert: complete.call_args.kwargs["counts"]["tagged"] == 3 | assert: "album-tag match among 2 clusters tied at 2.70" in log_text | assert: tags["Acoustid Id"] == f"ac-mb-{name}")
audio_fingerprinter/tests/test_file_processor.py:615:test_ambiguous_album_leaves_files_untagged_with_runner_up || keeps: positive outcome assertion (assert: all(r.status == "ALBUM AMBIGUOUS" for r in kwargs["results"]) | assert: kwargs["counts"]["album_ambiguous"] == 6 | assert: any( "ambiguous" in line and "left untagged" in line for line in kwargs["log_entries"] if  | assert: "album ambiguous — The Album vs Other Album" in result.message | assert: result.tag_written is False)
audio_fingerprinter/tests/test_file_processor.py:855:test_ambiguous_album_writes_no_tags || keeps: positive outcome assertion (assert: "Acoustid Id" not in self._acoustid_tags(folder / name))
audio_fingerprinter/tests/test_file_processor.py:651:test_below_minimum_falls_back_to_per_file_matching || keeps: positive outcome assertion (assert: len(kwargs["results"]) == 2 | assert: any( "3-file minimum" in line for line in kwargs["log_entries"] if line.startswith("[ALBUM | assert: result.status == "MATCHED" | assert: "album consensus" not in result.message | assert: "(score 0.90)" in result.message)
audio_fingerprinter/tests/test_file_processor.py:766:test_decided_cluster_writes_real_tags || keeps: positive outcome assertion (assert: kwargs["counts"]["tagged"] == 3 | assert: tags["Acoustid Id"] == f"ac-mb-{name}" | assert: tags["Acoustid Fingerprint"] == f"fp-{name}")
audio_fingerprinter/tests/test_file_processor.py:838:test_dry_run_writes_no_tags || keeps: positive outcome assertion (assert: "Acoustid Id" not in self._acoustid_tags(folder / name))
audio_fingerprinter/tests/test_file_processor.py:388:test_error_flags_an_error_in_log_entries || keeps: positive outcome assertion (assert: any(t and t.startswith("[ERROR]") for t in texts))
audio_fingerprinter/tests/test_file_processor.py:1222:test_mbids_are_skipped_when_the_acoustid_write_failed || fixed: added positive assertion assert: result.status == FingerprintStatus.TAG_WRITE_FAILED
audio_fingerprinter/tests/test_file_processor.py:1238:test_mbids_are_skipped_when_the_opt_in_is_off || fixed: added positive assertion assert: result.status == FingerprintStatus.TAGGED
audio_fingerprinter/tests/test_file_processor.py:682:test_per_file_lookup_error_counts_as_error || keeps: positive outcome assertion (assert: by_name["b.mp3"].status == "ERROR" | assert: "HTTP 500" in by_name["b.mp3"].message | assert: by_name["a.mp3"].status == "MATCHED" | assert: kwargs["errors"] == 1)
audio_fingerprinter/tests/test_fingerprinter_app.py:77:test_no_display_text_skips_listbox || fixed: added positive assertion assert_any_call: app.progress.__setitem__.assert_any_call("value", 2)
audio_fingerprinter/tests/test_mbid_writer.py:264:test_empty_tags_write_nothing || keeps: positive outcome assertion (assert: ok is True | assert: "No MusicBrainz identifiers" in msg)
audio_normalizer/tests/test_app.py:84:test_returns_early_when_no_folder_path || fixed: added positive assertion assert_called_once_with: mock_cls.assert_called_once_with(app)
audio_normalizer/tests/test_normalizer_core.py:428:test_apply_unsupported_format_rejected_before_ffmpeg || keeps: positive outcome assertion (assert: f.read_bytes() == b"wav data" | pytest.raises(...))
audio_normalizer/tests/test_normalizer_core.py:519:test_dry_run_does_not_apply || fixed: added positive assertion assert: "DRY RUN" in results[-1]["display_text"]
audio_normalizer/tests/test_normalizer_core.py:573:test_exactly_at_tolerance_boundary_skips || keeps: positive outcome assertion (assert: "SKIPPED" in results[-1]["display_text"])
audio_normalizer/tests/test_normalizer_core.py:761:test_lossless_dry_run_calls_nothing || fixed: added positive assertion assert: "DRY RUN" in results[-1]["display_text"]
audio_normalizer/tests/test_normalizer_core.py:411:test_read_tags_raw_failure_propagates || keeps: positive outcome assertion (pytest.raises(...))
audio_normalizer/tests/test_normalizer_core.py:679:test_tolerance_zero_only_skips_exact_match || keeps: positive outcome assertion (assert: "SKIPPED" in results[-1]["display_text"])
audio_normalizer/tests/test_normalizer_core.py:545:test_within_tolerance_skips_dry_run || keeps: positive outcome assertion (assert: "SKIPPED" in results[-1]["display_text"])
audio_normalizer/tests/test_normalizer_core.py:555:test_within_tolerance_skips_live || keeps: positive outcome assertion (assert: "SKIPPED" in results[-1]["display_text"])
audio_refinery/tests/test_app.py:237:test_all_stages_disabled_shows_no_stages_selected || keeps: positive outcome assertion (assert: "No Stages Selected" in titles)
audio_refinery/tests/test_integrity.py:388:test_decode_failure_short_circuits || keeps: positive outcome assertion (assert: result.status == IntegrityStatus.FAIL)
audio_refinery/tests/test_pipeline_stages.py:1332:test_apply_not_called_when_within_tolerance || fixed: added positive assertion assert_called_once: mock_measure.assert_called_once()
audio_refinery/tests/test_pipeline_stages.py:266:test_original_file_not_overwritten_on_failure || fixed: added positive assertion assert: src.read_bytes() == b"\xde\xad\xbe\xef"
audio_suite_shared/tests/test_analysis_app_base.py:537:test_selecting_a_missing_preset_is_a_no_op || fixed: added positive assertion assert_called_once_with: mock_load.assert_called_once_with("fake_tool", "nope")
audio_suite_shared/tests/test_audio_playback.py:146:test_does_not_join_dead_thread || fixed: added positive assertion assert_called_once: previous.is_alive.assert_called_once()
audio_suite_shared/tests/test_audio_playback.py:191:test_empty_wav_never_opens_stream || fixed: added positive assertion assert_called_once_with: mock_read.assert_called_once_with(wav)
audio_suite_shared/tests/test_audio_playback.py:309:test_preparation_failure_is_logged_and_swallowed || keeps: positive outcome assertion (assert: result is True | assert: "Audition playback failed" in caplog.text)
audio_suite_shared/tests/test_audio_playback.py:163:test_stops_early_when_event_set || fixed: added positive assertion assert_called_once: device.OutputStream.assert_called_once()
audio_suite_shared/tests/test_batch_undo.py:1052:test_overwrite_payload_is_not_unpickled_as_tags || keeps: positive outcome assertion (assert: result.reverted == 1)
audio_suite_shared/tests/test_file_processor_base.py:1149:test_dry_run_reports_found_without_writing || keeps: positive outcome assertion (assert: progress[0]["status"] == "FOUND" | assert: progress[0]["display_text"] == "[FOUND] a.wav → Fixed 1 thing" | assert: audio_file.read_bytes() == digest)
audio_suite_shared/tests/test_key_manager.py:375:test_icacls_skipped_when_username_missing || keeps: positive outcome assertion (assert: km._fernet is not None)
audio_suite_shared/tests/test_preflight.py:133:test_all_present_emits_no_warning || keeps: positive outcome assertion (assert: report_missing_requirements(show) == [])
audio_suite_shared/tests/test_preflight.py:93:test_clean_suite_returns_true_and_does_not_exit || keeps: positive outcome assertion (assert: verify_suite(suite_root, show, exit_fn=blocker) is True)
audio_suite_shared/tests/test_preflight.py:266:test_propagates_a_blocked_compile_gate || keeps: positive outcome assertion (assert: guard_or_exit(suite_root) is False)
audio_suite_shared/tests/test_ui_audition.py:280:test_play_original_missing_path || keeps: positive outcome assertion (assert: _last_caption(app) == "Original not available.")
audio_suite_shared/tests/test_ui_audition.py:289:test_play_original_none || keeps: positive outcome assertion (assert: _last_caption(app) == "Original not available.")
audio_suite_shared/tests/test_ui_audition.py:328:test_play_result_missing_path || keeps: positive outcome assertion (assert: _last_caption(app) == "Result not available.")
audio_suite_shared/tests/test_ui_common.py:936:test_blank_name_does_not_invoke_on_save || keeps: positive outcome assertion (assert: combo.get() == "")
audio_suite_shared/tests/test_ui_common.py:976:test_cancel_does_not_delete || keeps: positive outcome assertion (assert: combo.get() == "Preset A")
audio_suite_shared/tests/test_ui_common.py:987:test_no_selection_skips_prompt || fixed: added positive assertion assert: combo.get() == ""
audio_suite_shared/tests/test_ui_helpers.py:99:test_save_last_dir_false_skips_save || fixed: added positive assertion assert_called_once: mock_ask.assert_called_once()
bpm_analyzer/tests/test_app.py:121:test_no_handler_or_scheduling_without_folder || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
bpm_analyzer/tests/test_file_processor.py:128:test_write_bpm_not_called_in_dry_run || fixed: added positive assertion assert_called_once: mock_detect.assert_called_once()
cd_ripper/tests/test_cli.py:215:test_all_invalid_tracks_aborts || keeps: positive outcome assertion (assert: "No valid track numbers" in result.output)
cd_ripper/tests/test_cli.py:53:test_dry_run_prints_settings_and_skips_rip || keeps: positive outcome assertion (assert: "DRY RUN" in result.output | assert: "Drive" in result.output)
cd_ripper/tests/test_cli.py:267:test_invalid_choice_is_rejected || keeps: positive outcome assertion (assert: result.exit_code == 2)
cd_ripper/tests/test_cli.py:345:test_missing_output_dir_on_rip_path_is_usage_error || keeps: positive outcome assertion (assert: result.exit_code == 2 | assert: "--output-dir" in result.output)
cd_ripper/tests/test_cli.py:428:test_rip_session_not_started_for_detection || keeps: positive outcome assertion (assert: result.exit_code == 0)
cd_ripper/tests/test_disc_core.py:612:test_ffprobe_failure_with_mbz_skips_lookup || keeps: positive outcome assertion (assert: info.error is not None)
cd_ripper/tests/test_disc_core.py:555:test_mbz_not_called_when_error_present || fixed: added positive assertion assert: info.error is not None
cd_ripper/tests/test_offset_detect.py:309:test_inconclusive_sweep_raises_and_persists_nothing || keeps: positive outcome assertion (pytest.raises(...))
cd_ripper/tests/test_offset_detect.py:294:test_lookup_failure_raises_and_persists_nothing || keeps: positive outcome assertion (pytest.raises(...))
cd_ripper/tests/test_ripper_core.py:2991:test_empty_toc_skips_database_lookup || keeps: positive outcome assertion (assert: plan.mode is RipVerificationMode.ACCURATERIP | assert: plan.lookup is None | assert: plan.toc == ())
cd_ripper/tests/test_ripper_core.py:2518:test_mismatched_payload_length_reports_mismatch_without_reread || keeps: positive outcome assertion (assert: status.value == "MISMATCH" | assert: "expected" in detail)
cd_ripper/tests/test_ripper_core.py:2831:test_off_mode_skips_verification_entirely || keeps: positive outcome assertion (assert: ok is True | assert: err == "")
cd_ripper/tests/test_ripper_core.py:2868:test_read_wav_failure_blocks_encode || keeps: positive outcome assertion (assert: ok is False | assert: "Verification failed" in err)
cd_ripper/tests/test_ripper_core.py:2902:test_verify_value_error_blocks_encode || keeps: positive outcome assertion (assert: ok is False | assert: "Verification failed" in err)
file_reorganizer/tests/test_app.py:109:test_browse_source_cancelled_saves_nothing || fixed: added positive assertion assert_called_once: mock_dialog.askdirectory.assert_called_once()
file_reorganizer/tests/test_app.py:79:test_destination_is_never_seeded || fixed: added positive assertion assert_called_once_with: app.source_dir.set.assert_called_once_with("/music/from/driver")
file_reorganizer/tests/test_app.py:70:test_empty_last_directory_leaves_value_untouched || fixed: added positive assertion assert_called_once: mock_config.load_last_directory.assert_called_once()
genre_sync/tests/test_app.py:450:test_no_handler_or_scheduling_without_folder || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
genre_sync/tests/test_file_processor.py:125:test_already_correct_no_write || fixed: added positive assertion assert: results[0]["n_skipped"] == 1
genre_sync/tests/test_file_processor.py:145:test_dry_run_does_not_write || fixed: added positive assertion assert: results[0]["n_updated"] == 1 | assert: "Jazz" in results[0]["display_text"]
genre_sync/tests/test_file_processor.py:104:test_no_genre_does_not_call_write || fixed: added positive assertion assert: results[0]["n_no_genre"] == 1
key_detector/tests/test_app.py:123:test_no_auto_start_no_scheduling || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
key_detector/tests/test_app.py:108:test_no_folder_path_returns_before_mirroring || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Live Update")
key_detector/tests/test_file_processor.py:342:test_dry_run_with_existing_key_skips || keeps: positive outcome assertion (assert: call_kwargs["n_skipped"] == 1 | assert: "Already has key: Am" in call_kwargs["display_text"])
key_detector/tests/test_file_processor.py:117:test_get_samplerate_no_longer_called || fixed: added positive assertion assert_called_once: mock_detect_key.assert_called_once()
key_detector/tests/test_file_processor.py:188:test_parallel_mode_skips_legacy_path || fixed: added positive assertion assert_called_once: mock_processor.run_cpu_bound_processing.assert_called_once()
library_stats/tests/test_app.py:630:test_bar_colour_boundaries_and_unmapped_canvas || keeps: positive outcome assertion (assert: app._colour_for_pct(85.0) == "#22c55e" | assert: app._colour_for_pct(80.0) == "#f59e0b" | assert: app._colour_for_pct(49.9) == "#ef4444" | assert: canvas.create_rectangle.call_count == 1)
library_stats/tests/test_app.py:614:test_cancelled_save_does_nothing || fixed: added positive assertion assert: filedialog.asksaveasfilename.call_count == 2
library_stats/tests/test_library_stats.py:582:test_cache_removes_orphans || keeps: positive outcome assertion (assert: cache.row_count(str(tmp_path)) == 2 | assert: report.total_files == 1 | assert: cache.row_count(str(tmp_path)) == 1)
library_stats/tests/test_library_stats.py:435:test_incremental_scan || keeps: positive outcome assertion (assert: report1.total_files == 1 | assert: cache.row_count(str(tmp_path)) == 1 | assert: report2.total_files == 1)
lyrics_manager/tests/test_app.py:155:test_no_handler_or_scheduling_without_folder || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
lyrics_manager/tests/test_sidecar_provider.py:251:test_integration_with_process_single_file_no_network || keeps: positive outcome assertion (assert: tags.synced is not None | assert: "Hello world" in tags.synced)
lyrics_manager/tests/test_sidecar_provider.py:236:test_search_never_touches_network || keeps: positive outcome assertion (assert: result is not None | assert: result.has_lyrics)
master_driver/tests/test_app.py:346:test_poll_inert_for_fixed_palette || fixed: added positive assertion assert: drv._accent_poll_active is True
master_driver/tests/test_app.py:380:test_poll_reschedules_with_unchanged_accent || keeps: positive outcome assertion (assert: call is not None | assert: call.args[0] == _ACCENT_POLL_MS | assert_bound: assert_bound(call.args[1], "_poll_accent", drv))
master_driver/tests/test_batch_orchestrator.py:372:test_all_standalone_parallel_batch_terminates || keeps: positive outcome assertion (assert: report.skipped == 2)
master_driver/tests/test_batch_orchestrator.py:312:test_standalone_step_is_never_submitted_to_the_pool || keeps: positive outcome assertion (assert: [call.args[0] for call in run_script.call_args_list] == [ steps[0].script_path ])
master_driver/tests/test_tool_launcher.py:156:test_enrich_nonexistent_dir_shows_directory_not_found || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "Directory Not Found")
master_driver/tests/test_tool_launcher.py:97:test_folder_tool_without_dir_shows_no_directory || keeps: positive outcome assertion (assert: state.dir_path.get() == "" | assert: launch_mocks.show_message.call_args.args[1] == "No Directory")
master_driver/tests/test_tool_launcher.py:218:test_no_active_stages_shows_message || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "No Stages Selected")
master_driver/tests/test_tool_launcher.py:257:test_no_directory_shows_message || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "No Directory")
master_driver/tests/test_tool_launcher.py:88:test_no_selection_shows_nothing_selected || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "Nothing Selected")
master_driver/tests/test_tool_launcher.py:212:test_no_source_shows_message || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "No Source Folder")
master_driver/tests/test_tool_launcher.py:176:test_refinery_nonexistent_source_shows_directory_not_found || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "Directory Not Found")
master_driver/tests/test_tool_launcher.py:145:test_utility_nonexistent_dir_shows_directory_not_found || keeps: positive outcome assertion (assert: launch_mocks.show_message.call_args.args[1] == "Directory Not Found")
metadata_scrubber/tests/test_app.py:362:test_dry_run_completion_never_saves_tag_prefs || keeps: negative contract required by plan G2.4a; behaviour covered by test_live_completion_saves_tag_prefs
metadata_scrubber/tests/test_app.py:155:test_no_handler_or_scheduling_without_folder || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
mood_analysis_batch_tagger/tests/test_app.py:161:test_ignores_missing_key || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
mood_analysis_batch_tagger/tests/test_app.py:417:test_ignores_non_int_saved_value || fixed: added positive assertion assert_called_once_with: mock_config.load_value.assert_called_once_with( "mood_analysis_batch_duration", 90 )
mood_analysis_batch_tagger/tests/test_app.py:389:test_no_folder_path_is_noop || fixed: added positive assertion assert_called_once_with: app.root_path.set.assert_called_once_with(str(tmp_path))
mood_analyzer/tests/test_app.py:123:test_no_auto_start_no_scheduling || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
mood_analyzer/tests/test_app.py:108:test_no_folder_path_returns_before_mirroring || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Live Update")
mood_analyzer/tests/test_file_processor.py:61:test_dry_run_detects_without_writing || keeps: positive outcome assertion (assert: "[DETECTED]" in call_kwargs["display_text"] | assert: "Energetic;Bright;Confident" in call_kwargs["display_text"])
mood_analyzer/tests/test_file_processor.py:221:test_ok_dry_run_skips_writes || fixed: added positive assertion assert: "[DETECTED]" in call_kwargs["display_text"]
mood_analyzer/tests/test_file_processor.py:309:test_parallel_mode_skips_legacy_path || fixed: added positive assertion assert_called_once: mock_processor.run_cpu_bound_processing.assert_called_once()
mood_analyzer/tests/test_file_processor.py:106:test_undecodable_file_reported_as_skip || keeps: positive outcome assertion (assert: call_kwargs["n_skipped"] == 1 | assert: "[SKIP]" in call_kwargs["display_text"])
music_format_converter/tests/test_file_processor.py:538:test_wav_params_auto_still_reads_config_override || keeps: positive outcome assertion (assert: kwargs == {"wav_depth": "24"})
music_format_converter/tests/test_file_processor.py:522:test_wav_params_explicit_bit_depth_wins || keeps: positive outcome assertion (assert: kwargs == {"wav_depth": "16"})
music_format_converter/tests/test_file_processor.py:511:test_wav_params_lossy_source_keeps_16_bit_default || keeps: positive outcome assertion (assert: kwargs == {} | assert: "pcm_s16le" in cmd)
music_format_converter/tests/test_file_processor.py:553:test_wav_params_override_beats_lossy_short_circuit || keeps: positive outcome assertion (assert: kwargs == {"wav_depth": "24"})
noise_reduction/tests/test_app.py:319:test_empty_preset_does_nothing || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
noise_reduction/tests/test_file_processor.py:280:test_live_run_records_single_real_path_snapshot_under_batch || keeps: positive outcome assertion (assert: len(batches) == 1 | assert: len(records) == 1 | assert: records[0].file_path == str(audio_file) | assert: records[0].operation == "noise_reduce_edit")
pop_click_remover/tests/test_app.py:292:test_empty_preset_does_nothing || fixed: added positive assertion assert_called_once_with: app.sensitivity.set.assert_called_once_with(0.6)
replaygain_analyzer/tests/test_app.py:328:test_no_handler_or_scheduling_without_folder || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
replaygain_analyzer/tests/test_replaygain_pipeline.py:741:test_apply_not_called_when_flag_false || fixed: added positive assertion assert_called: mock_write_tags.assert_called()
replaygain_analyzer/tests/test_replaygain_pipeline.py:495:test_dry_run_does_not_call_write_replaygain_tags || fixed: added positive assertion assert: all(s == "DRY RUN" for s in statuses)
replaygain_analyzer/tests/test_replaygain_pipeline.py:774:test_tag_write_failure_skips_gain_application || keeps: positive outcome assertion (assert: completions[0]["tag_results"][0][1] == "ERROR")
silence_trimmer/tests/test_app.py:357:test_empty_preset_does_nothing || fixed: added positive assertion assert_called_once_with: app.threshold.set.assert_called_once_with(-60)
tag_editor/tests/test_app.py:66:test_apply_selection_passes_clear_value || keeps: positive outcome assertion (assert: edit.path == path | assert: edit.field == "title" | assert: edit.value is None | assert: app.processor.apply_edits.call_args.kwargs["dry_run"] is False)
tag_editor/tests/test_app.py:439:test_browse_directory_does_nothing_when_cancelled || fixed: added positive assertion assert_called_once: mock_dialog.assert_called_once()
tag_editor/tests/test_app.py:385:test_export_csv_cancelled_dialog_does_nothing || fixed: added positive assertion assert_called_once: mock_dialog.assert_called_once()
tag_editor/tests/test_app.py:275:test_import_csv_applies_plan_edits || keeps: positive outcome assertion (assert: app.processor.apply_edits.call_args.kwargs["dry_run"] is True | assert: app._rows[str(path)][1]["title"] == "New")
tag_editor/tests/test_app.py:313:test_import_csv_cancelled_dialog_does_nothing || fixed: added positive assertion assert_called_once: mock_dialog.assert_called_once()
tag_editor/tests/test_app.py:474:test_on_tree_select_multiple_selections_returns_early || fixed: added positive assertion assert_called_once_with: app.tree.selection.assert_called_once_with()
tag_editor/tests/test_app.py:465:test_on_tree_select_no_selection_returns_early || fixed: added positive assertion assert_called_once_with: app.tree.selection.assert_called_once_with()
tag_editor/tests/test_app.py:485:test_on_tree_select_unknown_iid_returns_early || fixed: added positive assertion assert_called_once_with: app.tree.selection.assert_called_once_with()
tag_editor/tests/test_app.py:552:test_update_row_skips_unknown_iid || fixed: added positive assertion assert_called_once_with: app.tree.set.assert_called_once_with(str(known), "title", "New")
tag_editor/tests/test_processor.py:254:test_dry_run_compares_without_writing || keeps: positive outcome assertion (assert: results[0].changed is True | assert: results[0].written is False | assert: summarize_results(results).changed == 1)
tag_editor/tests/test_processor.py:301:test_invalid_value_raises_before_writes || keeps: positive outcome assertion (pytest.raises(...))
tag_editor/tests/test_processor.py:286:test_unchanged_value_is_not_written || keeps: positive outcome assertion (assert: results[0].changed is False)
tag_field_updater/tests/test_app.py:205:test_cancelled_picker_leaves_directory || fixed: added positive assertion assert_called_once: filedialog.askdirectory.assert_called_once()
tag_field_updater/tests/test_processor.py:549:test_process_flac_no_matching_tags || keeps: positive outcome assertion (assert: result.updated is False)
tag_field_updater/tests/test_processor.py:575:test_process_flac_value_no_slash_no_update || keeps: positive outcome assertion (assert: result.updated is False | assert: result.tags_updated == ())
tag_field_updater/tests/test_processor.py:468:test_process_mp3_no_matching_tags || keeps: positive outcome assertion (assert: result.updated is False)
tag_field_updater/tests/test_processor.py:606:test_process_mp4_no_matching_tags || keeps: positive outcome assertion (assert: result.updated is False)
tag_field_updater/tests/test_processor.py:632:test_process_mp4_value_no_slash_no_update || keeps: positive outcome assertion (assert: result.updated is False | assert: result.tags_updated == ())
tag_field_updater/tests/test_processor.py:663:test_process_ogg_no_matching_tags || keeps: positive outcome assertion (assert: result.updated is False)
tag_field_updater/tests/test_processor.py:690:test_process_ogg_value_no_slash_no_update || keeps: positive outcome assertion (assert: result.updated is False | assert: result.tags_updated == ())
tag_field_updater/tests/test_processor.py:778:test_process_opus_no_matching_tags || keeps: positive outcome assertion (assert: result.updated is False)
tag_field_updater/tests/test_processor.py:805:test_process_opus_value_no_slash_no_update || keeps: positive outcome assertion (assert: result.updated is False | assert: result.tags_updated == ())
tag_field_updater/tests/test_processor.py:721:test_process_wma_no_matching_tags || keeps: positive outcome assertion (assert: result.updated is False)
tag_field_updater/tests/test_processor.py:747:test_process_wma_value_no_slash_no_update || keeps: positive outcome assertion (assert: result.updated is False | assert: result.tags_updated == ())
tempo_analyzer/tests/test_app.py:208:test_empty_preset_does_nothing || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Dry Run")
tempo_analyzer/tests/test_app.py:244:test_ignores_unknown_scheme || keeps: positive outcome assertion (assert: app._active_markings is original)
tempo_analyzer/tests/test_app.py:355:test_no_folder_path_returns_before_mirroring || fixed: added positive assertion assert_called_once_with: app.run_mode.set.assert_called_once_with("Live Update")
tempo_analyzer/tests/test_app.py:409:test_on_preset_selected_empty_preset_does_nothing || fixed: added positive assertion assert_called_once_with: mock_cfg.load_preset.assert_called_once_with("tempo_analyzer", "empty_preset")
tempo_analyzer/tests/test_app.py:418:test_on_preset_selected_none_does_nothing || fixed: added positive assertion assert_called_once_with: mock_cfg.load_preset.assert_called_once_with("tempo_analyzer", "missing")
tempo_analyzer/tests/test_file_processor.py:244:test_dry_run_does_not_write || fixed: added positive assertion assert: "DRY RUN" in results[0]["display_text"]
```

### G8.1 collected-id list (AST scan of production files)

24 ids collected; `audio_enhancer` is exempt (suite_config preset namespace, never
passed to `active_batch`). All 23 non-exempt ids are keys of
`_TOOL_DISPLAY_NAMES` (19 pre-existing + the 4 added = 23).

```text
album_art_normalizer, album_art_sync, album_genre_tagger, asx_extractor,
audio_enhancer (EXEMPT), audio_fingerprinter, audio_normalizer, audio_refinery,
bpm_analyzer, file_reorganizer, genre_sync, key_detector, lyrics_manager,
metadata_scrubber, mood_analysis_batch_tagger, mood_analyzer,
music_format_converter, noise_reduction, pop_click_remover, replaygain_analyzer,
silence_trimmer, tag_editor, tag_field_updater, tempo_analyzer
```

### G8.2 disposition table — every `user_guides/` grep hit

| Hit | Context | Disposition |
|---|---|---|
| `suite_overview/generate_presentation.py:1929` | utility name list | **changed** → "Tag-Based File Reorganizer"; `.pptx` regenerated |
| `suite_overview/generate_presentation.py:474,547,1865` | tool name lists | already "ASX Playlist Extractor" → audited, left as-is |
| `master_driver/generate_guide.py:118` | `"…Tag-Based"` + `" File Reorganizer,"` prose list | already manifest-exact (split literal) → audited, left as-is |
| `master_driver/generate_guide.py:255,295` | tool name lists | already "ASX Playlist Extractor" / "Tag-Based File Reorganizer" → left as-is |
| `undo_tag_edits/generate_guide.py:51` | `"…the Tag-Based"` + `"File Reorganizer."` prose | already manifest-exact (split literal) → audited, left as-is |
| `file_reorganizer/generate_guide.py:1,19,21,26` | owner-guide title / subtitle / self-refs | **kept** — self-referential short name of the program (plan D-scope) |
| `file_reorganizer/generate_guide.py:232` | `"…select Tag-Based File Reorganizer"` | already manifest-exact → left as-is |
| `README.md:51` | feature list | already "ASX Playlist Extractor" → left as-is |
| `asx_extractor/generate_guide.py:1,19,22,28` | owner-guide title / self-refs | already "ASX Playlist Extractor" → left as-is |
| `reference/CLI_Commands_Reference.md:49,266,281` | command / section headers | already manifest-exact → left as-is |

### G8.4 `git diff pyproject.toml` (three L4 edits + the authorized `python-pptx` declaration)

```diff
@@ dev extra (user-authorized addition)
     "bandit[toml]>=1.7.0",
     "python-docx>=1.1.0",
+    "python-pptx>=1.0.0",
     "types-requests>=2.28.0",
 ]

exclude = [
     "^tests/",
-    "^utilities/",
     "^user_guides/",
     "/tests/",
 ]
@@
     "tempo_analyzer",
+    "utilities",
 ]
 omit = [
     "*/tests/*",
     "*/__pycache__/*",
-    "utilities/*",
 ]
```

### S8 note — the one pre-existing Tk warning (not an S8 defect)

The S8 gate run reports `1 warning` (S6/S7 gate runs reported `0`):
`PytestUnraisableExceptionWarning` from
`noise_reduction/tests/test_file_processor.py::TestNoiseReductionOutcome::test_hum_floor_drops_and_tone_survives`
— a `tkinter.Variable.__del__` finalizer raising `RuntimeError: main thread is
not in main loop` when GC runs on a worker thread during that audio-processing
test. It passes cleanly in isolation (verified), and no S8 change touches Tk, so
it is a pre-existing, timing-dependent GC race of `Variable`s created on the
shared session `root` — not caused by M10/L2/L4. S8's acceptance is "green" (met:
exit 0, 8694 passed); recorded here so G9.1's stricter **0-warning** requirement
is not surprised.

**Remediation (landed, 2026-10-09 — ahead of G9.1, which needs 0 warnings).**
Chosen approach: a session-root-level, function-scoped autouse fixture
`_collect_tk_garbage_on_main_thread` in `conftest.py` that runs a `gc.collect()`
**on the main thread** in teardown, so any `Variable` a UI test dropped is
finalized while the main thread is in the loop (no `__del__` on a worker). The
`Variable.__del__` patch approach was rejected as more invasive (it changes
tkinter semantics globally).

The collection is **scoped by `requires_display(request.node)`** — the exact
bounded predicate that drives the headless skip — so it only runs after the
display-dependent subset (the only tests that can create a `Variable`), not after
all ~8700 tests. This scoping is load-bearing, not an optimisation: the first
implementation collected after *every* test and turned the ~280 s gate into a
15-min+ crawl (full-heap GC on every one of ~8700 tests, costlier as the session
heap grew; the run was still at 68 % when killed at the 900 s timeout). Scoped,
the gate is `8697 passed, 3 skipped, 30 deselected, **0 warnings** in 401.56s`
(exit 0; coverage 90.43 %; mypy 0/469; bandit 0 High / 0 Medium / 41 Low). The
~2 min premium over the pre-fix 280 s run is the full collection after each of
the GUI tests; the 0-warning guarantee for G9.1 is worth it.

Regression coverage in `tests/test_conftest.py::TestTkGarbageCollection`:
`test_an_autouse_fixture_collects_garbage_on_the_main_thread` (AST structural
lock: the autouse fixture calls `gc.collect()`), `test_main_thread_collection_
prevents_the_off_thread_finalizer` (in-process: a dropped `Variable` in a cycle
is finalised with no unraisable warning), and
`test_the_seam_keeps_the_session_free_of_the_warning` (pytester subprocess: the
real conftest proves the warning is gone end-to-end; display-guarded). A
throwaway negative control confirmed the end-to-end test is load-bearing: with
the seam neutralized, the same child run reports `1 warning` /
`main thread is not in main loop`.

No CHANGELOG bullet: the fix is test-infrastructure, invisible to users.

---

## Deferred backlog (recorded, NOT executed in this plan)

| # | Item | Why deferred |
|---|---|---|
| B1 | Report §6 suggestions Tier 1–3 (items 1–8, 13): enhancement features (e.g. cross-platform audit) | User scoped findings-only (D1). |
| B2 | PyInstaller packaging (§6 item 10) | Approved dependency (D2) but no finding needs it. |
| B3 | CLI reference: add the 6 undocumented command table-rows (album fingerprint, artnormalize, mood-analyzer, mood-analysis-batch, tag-edit, tag-update) and a reverse "every click command is documented" lock | Documentation feature-add; the M2 lock covers the forward direction only. |
| B4 | Report §6 item 9 — *generating* the CLI reference's defaults from click (M2 implements assertion-side introspection only) | Doc-generation rewrite is a feature. |
| B5 | Full M7 single-runner unification of the four executor loops (§6 item 12) | D5: redesign, not defect. |
| B6 | bpm/lyrics residual clone (`_build_options`, scan/run flow) | D7. |
| B7 | `run_cpu_bound_processing` remaining length beyond G7.1's ≤120 target, and any further `file_processor_base` consolidation | G7.1 closes M7's defect; deeper restructuring is refactoring backlog. |
