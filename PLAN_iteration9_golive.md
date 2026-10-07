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
| D12 | Bandit's verdict in both gate runners — the CI `security` job (`.github/workflows/ci.yml`) and `utilities/run_gate.ps1` step 5 — is judged by bandit's **severity block** (0 High / 0 Medium), never the raw exit code. bandit 1.9.4 exits 1 whenever ANY finding survives its default LOW/LOW filter, which the 41 documented Low findings trigger on every run; exit ≥ 2 (tool error) and an unparseable severity block always fail. The §3.1 bandit command itself stays byte-identical in both runners. | AGENTS §6.3 defines the healthy result as 0 High / 0 Medium and warns that the confidence block is a different metric; a raw-exit-code gate can never pass at HEAD (verified empirically), so the CI security job was red by construction. Both verdicts verified by controls: real output (confidence 23/18 not read) passes, injected severity High=1/Medium=2 fails, missing severity block fails loudly, tool error exit 2 fails. |

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

**Completion-log row (S3):** per item + the G3.1 mismatch list (found → fixed)
and the pre-fix red run of the lock test.

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

**Findings closed:** M11. **Guides/CHANGELOG:** none (tests only).
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
| G2.1 | 1 | | | |
| G2.2 | 1 | | | |
| G2.3 | 1 | | | |
| G2.4 | 1 | | | |
| G3.1 | 1 | | | |
| G3.2 | 2 | | | |
| G3.3 | 2 | | | |
| G4.1–G4.5 | 2 | | | |
| G5.1 | 2 | | | |
| G5.2 | 2 | | | |
| G5.3 | 3 | | | |
| G5.4 | 3 | | | |
| G6.1–G6.6 | 3 | | | |
| G7.1 | 2 | | | |
| G7.2 | 2 | | | |
| G7.3 | 3 | | | |
| G7.4 | 3 | | | |
| G8.1 | 2 | | | |
| G8.2 | 2 | | | |
| G8.3 | 3 | | | |
| G8.4 | 3 | | | |
| G9.1–G9.5 | 1 | | | |

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
