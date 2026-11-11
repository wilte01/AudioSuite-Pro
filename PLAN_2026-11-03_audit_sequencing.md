# PLAN — Audit 2026-11-03 sequencing: the plan set

**Status:** `[ ]` **PLANNING ONLY.** Eight execution plans exist; no production
code, test, config or document has been changed by this planning pass.

**Base state:** `main` at `c124142` ("Refresh uv.lock for the 2.4.0 release"),
tag `v2.4.0`, working tree clean before the audit file was added. Every fact in
the eight plans is read from that tree; where the audit report and the code
disagree, the plan states the code's version and records the difference.

**Source:** `AUDIT_2026-11-03_suite_report.md` §11.2 ("Suggested sequencing").
This file maps each of its eight numbered items to one execution plan, records
the dependencies between them, and states the cross-cutting mechanics that all
eight share so no plan has to repeat them.

**Governing scope:** the eight items of §11.2 and nothing else. Work packages
and feature items named *outside* §11.2 are listed in §3 as unassigned, because
the audit's own sequencing leaves them without a release. Selecting a home for
them is a product decision, not an implementation detail, and must not be
smuggled into one of these plans.

---

## 1. The plan set

| §11.2 item | Version | Plan file | Type | Contents | Effort |
|---|---|---|---|---|---|
| 1 | `2.4.1` | `PLAN_2026-11-03_2.4.1_stop_the_drift.md` | patch | WP-0, WP-1, WP-2, WP-3, WP-4, WP-7 | 2 weeks, 6 work packages |
| 2 | `2.4.2` | `PLAN_2026-11-03_2.4.2_audio_foundation.md` | patch | WP-5 (probe + ReplayGain first), WP-6 | 4 weeks |
| 3 | `2.4.3` | `PLAN_2026-11-03_2.4.3_structure.md` | patch | WP-8 (shell + 3 tools), WP-9 (5 module splits) | 6 weeks |
| 4 | `2.5.0` | `PLAN_2026-11-03_2.5.0_feature_wave_1.md` | minor | F-E1, F-E3, F-E4, F-E5, F-E6 | 6-8 weeks |
| 5 | `2.6.0` | `PLAN_2026-11-03_2.6.0_feature_wave_2.md` | minor | F-E2, F-E7, F-E8, F-E9, F-E10 | 8-10 weeks |
| 6 | `2.7.0` | `PLAN_2026-11-03_2.7.0_feature_wave_3.md` | minor | F-S1, F-S2, F-S4, F-S5, F-S7, F-S9 | 14-18 weeks |
| 7 | `3.0.0` | `PLAN_2026-11-03_3.0.0_feature_wave_4_core.md` | major | F-M1, F-M2, F-M4 | 4-6 months |
| 8 | `3.1.0` | `PLAN_2026-11-03_3.1.0_feature_wave_4_optional.md` | minor | F-M3, F-M5, F-M6 | 3-5 months, decision-gated |
| 9 | `3.2.0` | `PLAN_2026-11-11_3.2.0_recursive_scanning.md` | minor | REC-1 … REC-7 (no `F-*` number: this set is closed at `3.1.0`, see that plan's item-ID note) | 9-10 days, strictly additive, every item independently cuttable |

The audit's week numbers are elapsed-time labels, not commitments. The plans
keep the labels so the mapping back to §11.2 is exact, and each plan states its
own real effort and the point at which it can be cut without stranding a
documented promise.

## 2. Dependency graph

```
WP-0 (models) ──┬──────────────────────────────► WF-1 (F-E1 … F-E6)
WP-1 (matrix) ──┼──► WP-2 (tag factory) ──► WP-6 (one tag layer)
                └──► WP-5 (audio_probe) ──► WP-9 (module splits) ──► WF-3 (F-S7)
WP-3 (dead code)   WP-4 (handshake)   WP-7 (exceptions)
WP-8 (GUI shell) ──► WF-1 tools' windows, WF-2/3 surfaces
F-E1 ──► F-S5 (album gain staging with per-track report)
WP-5 ──► F-S7 (QC report)
```

Hard ordering rules, each with a reason:

1. **WP-1 before WP-2.** The tag factory's extension table should be the format
   matrix's projection, not a second hand-written list. Doing WP-2 first creates
   a third taxonomy for one release.
2. **WP-1 before WP-5.** `audio_probe` must refuse read-only containers
   (`.ape`, `.mpc`, `.dsf`) consistently; refusal is a matrix property.
3. **WP-0 and WP-5 before WP-9.** Modules being split include the preset and
   measurement code; splitting first would move the divergence around instead of
   removing it.
4. **WP-2 before WP-6.** The tag engine consumes a factory that can be imported
   in isolation; WP-6 on the current cycle-order factory inherits the same
   fragility.
5. **WP-9 before WP-10's `ui_common` slice** (C-I1 god-package split), because
   moving a package whose largest module is already being split doubles the
   churn.

## 3. Work the sequencing does not assign

`§11.2` names WP-0 … WP-9 and features F-E1 … F-E6, F-S1, F-S2, F-S4, F-S5,
F-S7, F-S9, F-M1 … F-M6. Four audit items have **no release**:

| Item | Audit status | Why it matters | Recommendation |
|---|---|---|---|
| WP-10 (`C-I1` … `C-I9` hygiene) | Depends on WP-9, never scheduled | `py.typed` (C-I6), the `Changed in` budget (C-I2), shim removal (C-I7) and per-package coverage (C-I9) are cheap and stop drift | Split it. Land C-I6/C-I7/C-I9 + the C-I2 budget as the tail of `2.4.3`; defer C-I1 (package split, 2-3 weeks) and C-I3 (renaming) to their own patch after `2.7.0` |
| F-S3 (de-esser) | Priority 5, no wave | Specialist DSP, no consumer yet | Bundle with F-S2 in `2.7.0` if the dynamics stage lands early; otherwise `2.8.0` |
| F-S6 (multichannel phase 1) | Priority 5, no wave | Prerequisite for F-M3 | `2.8.0`, immediately before `3.1.0`'s F-M3 |
| F-S8 (peak/waveform cache) | Omitted from wave 3 although F-S7/F-S9 are named | Spectral Viewer recomputes on open | `2.7.0` as a fourth item, or `2.8.0`; it shares `audio_probe` with F-S7 |

Decisions on these belong in the governing plan of whichever release adopts
them, not here.

## 4. Mechanics shared by every plan

### 4.1 The gate (from `AGENTS.md`, unchanged)

```text
python -m compileall -q -f .
ruff check .
ruff format --check .
python -m mypy .
bandit -r . -x ./.venv -c pyproject.toml      # 0 High / 0 Medium
pytest                                        # bare; testpaths applies
```

`pytest tests/` is not the gate and never was. Full-suite wall time at HEAD was
20m56s; `tests/test_ci_cost.py` prices every CI job against a 100-minute budget,
so test additions are a budget item, not free.

### 4.2 Release cut

`python utilities/release.py <version>` promotes `CHANGELOG.md` and
`TECHNICAL_CHANGELOG.md` together. A bullet's subject decides its file: a user
can run or observe it (tool behaviour, flag, default, format, error message,
workflow step, measured difference) it goes in `CHANGELOG.md`; otherwise it goes
in `TECHNICAL_CHANGELOG.md`. `tests/test_changelog_format.py` fails a
user-facing file whose bold lead-in names developer work (`test`, `gate`, `CI`,
`ruff`, `mypy`, `coverage`, `lint`, `workflow`, `benchmark`).

### 4.3 Guides

Every release reviews the guides for what it touches, edits the Markdown source
under `documentation/user_guides/individual_programs/<tool>/`, re-renders with
`python utilities/build_user_guides.py <module_dir>`, and proves it with
`python utilities/build_user_guides.py --check`. Suite-wide pages ride
`python utilities/build_user_guides.py reference`. Generated artefacts are never
hand-edited; a timestamp-only `.docx` diff is `git restore`d.

`tests/test_guide_claims.py` mechanically holds format counts, worker counts,
quoted flags and status tokens against the code, so a format or flag change that
skips the guide fails there rather than in a user's hands.

### 4.4 Registering a new tool (only waves 1-4 need this)

Each new tool costs all eleven steps, and missing one is silent:

1. `ToolManifest` entry in `audio_suite_shared/tool_plugin.py` (`_DEFAULT_MANIFESTS`).
2. `master_driver/ui/cards/{tool_id}_card.py`, named exactly for the id.
3. Click command in the tool's `cli.py` plus its import in `audio_suite_shared/cli_app.py`.
4. `master_driver/runner/arg_builder.py` entry (enrich tools emit `[path, mode, start, end]`).
5. `master_driver/batch_orchestrator.py` `DEPENDENCY_GRAPH`.
6. `master_driver/state/app_state.py` toggle key + `master_driver/tests/test_app_state.py`.
7. Top-level `<Tool_Name>.pyw` with `ensure_venv_interpreter` then `guard_or_exit`.
8. Guide Markdown + rendered `.docx` + `audio_suite_shared/platform_utils.py::guide_to_program`.
9. `pyproject.toml`: `testpaths` and coverage `source`.
10. `<module>/tests/` suite with `__init__.py` in the package.
11. `on_progress`/`on_complete`/`on_error` contract + `tests/test_callback_payload_contract.py`'s `EXPECTED_TOOLS`.

Shipped-artefact locks that move with a new tool: `tests/test_completion_payload_published.py`,
`tests/test_cli_schema_conformance.py` and `audio_suite_shared/cli_schema.json`,
`tests/data/cli_payloads.json`, `tests/test_pyw_launchers.py`,
`tests/test_docs_index.py` and `utilities/generate_docs_index.py`,
`tests/test_readme.py` and `utilities/generate_readme_tool_index.py`,
`tests/test_suite_docs_tool_coverage.py`, `tests/test_guide_claims.py`,
`tests/test_test_file_naming.py` (frozen `ALLOWLIST`), `tests/test_lock_counts.py`,
`tests/test_pyproject_config.py`, `tests/test_ci_cost.py`.

### 4.5 Verification standard

The audit's §11.3 is adopted verbatim: audio changes are proven by decoding the
output and measuring per-channel RMS, integrated loudness, true peak, sample
rate, channel count and bit depth; tag changes by reloading from disk with
mutagen and comparing every field plus the undo snapshot; CLI changes by running
the real argv through `parse()`; UI changes by a widget-contract test plus one
hidden-root smoke test; refactors by keeping every existing behaviour test.

Two additions the audit's list implies but does not state:

- **A test that cannot fail is a defect.** New scans assert their result set is
  non-empty; a break-and-restore check keys on a `FAILED`/`ERROR` line and
  clears `__pycache__` between runs.
- **Every plan records what it did *not* verify**, including checks blocked by a
  missing binary, account or display.

## 5. Assumptions that need a product decision before execution

| # | Assumption | Plans affected | If wrong |
|---|---|---|---|
| A1 | `.wma` support is *completed* (ASF tag handler + discovery), not removed | 2.4.1, 2.4.2 | Removing a working converter input is a behaviour change and cannot ship in a patch; move it to `2.5.0` |
| A2 | The canonical `EnhancementParams` default is `output_gain_db=4.0` (what the applied path uses) | 2.4.1 | Adopting `0.0` changes rendered output for Custom-preset runs and needs a CHANGELOG bullet plus a re-baseline of gain tests |
| A3 | Wave 1's three new batch operations ship as three new tools (Splitter, Joiner, Channel Tools) rather than CLI-only | 2.5.0 | CLI-only removes six registration steps per tool but breaks the GUI-first workflow every other batch tool has |
| A4 | `F-S8` joins `2.7.0` | 2.7.0 | It moves to `2.8.0` with F-S3/F-S6 |
| A5 | `3.1.0` is decision-gated, not committed | 3.1.0 | The plan is scoped so each of the three items can be dropped independently |

## 6. How to start any one of these plans

1. State the governing plan by filename in the first commit message.
2. Re-measure the baseline the plan quotes (`pytest --collect-only -q`, the four
   gate commands) and record the numbers, because every plan's "no test-count
   drop" check compares against them.
3. Work item by item, one reviewable commit per item, running the gate against
   the state after each commit.
4. Record every deviation and every discovered defect in that plan's
   `## Decision Log`, with the measured evidence. A defect found while
   implementing is fixed in the same change with a regression test.
5. At the end, update this index only if a plan moved release or an unassigned
   item found a home.

## 7. The execution prompt

Paste the block below as the whole opening message of any session that executes
part of this plan set. It is deliberately standalone: it names the files it
needs, carries the release order and the hard prerequisites, the per-item loop,
the evidence standard and the stop conditions, so it can be reused release after
release without editing.

````text
EXECUTION SESSION — AudioSuite-Pro, audit 2026-11-03 plan set

You are executing work that is already planned. The planning pass is finished:
nine execution plans plus one index sit in the repository root, the first eight
all dated 2026-11-03. Your job is to carry out the next eligible item correctly, in order,
with evidence — not to re-plan, re-audit or improve the plans.

0. BEFORE ANY EDIT
   1. Read AGENTS.md. It governs the gate, the changelog split, the guide rule,
      test-file naming, the new-tool checklist and byte-level safety.
   2. Read PLAN_2026-11-03_audit_sequencing.md sections 1 (plan set), 2
      (dependency rules), 4 (shared mechanics) and 5 (assumptions A1-A5).
   3. Read the governing plan for the item, end to end, including its Decision
      Log and every "verify first" note.
   4. Then state, before touching anything: the governing plan filename, the item
      ID, its acceptance test, its prerequisites and whether each is green, and
      the gate baseline you are about to measure. If no item was named, propose
      the next eligible one and wait for confirmation.

1. THE ORDER — never reorder without asking
   Releases: 2.4.1 -> 2.4.2 -> 2.4.3 -> 2.5.0 -> 2.6.0 -> 2.7.0 -> 3.0.0 -> 3.1.0 -> 3.2.0
   Inside a release, follow the item order its plan gives.
   Hard prerequisites:
     WP-1 before WP-2 and before WP-5
     WP-0 and WP-5 before WP-9
     WP-2 before WP-6
     WP-9 before WP-10's ui_common slice (C-I1)
     F-E1 before F-S5; WP-5 before F-S7; F-S6 before F-M3
   A prerequisite is green only when its item is committed AND the gate passed
   on that commit. "It looks done" is not green.

2. ONE ITEM = ONE COMMIT
   A work package (WP-n) or feature (F-x) lands as one reviewable commit, or a
   short series only if one commit is genuinely impossible. The first line names
   the plan file and the item ID. Never bundle two items.

3. THE LOOP FOR EACH ITEM — no step skipped
   a. Baseline. Re-measure what the plan quotes: the collected test count
      (pytest --collect-only -q) and the five gate commands. Record a
      difference in the plan's Decision Log.
   b. Verify first. Check every "verify first" claim against the code and record
      the answer; the plan may be wrong about the tree.
   c. Test first. For a behaviour change, write the failing test that states the
      contract, watch it fail for the right reason, then implement.
   d. Implement the item only. No drive-by refactors or renames outside the
      item's file list.
   e. Gate, in this order, and paste the summary lines:
        python -m compileall -q -f .
        ruff check .
        ruff format --check .
        python -m mypy .
        bandit -r . -x ./.venv -c pyproject.toml       (expect 0 High / 0 Medium)
        pytest                                          (bare; never pytest tests/)
      A red gate stops the item. Fix the cause, never the check.
   f. Changelog split. User-observable behaviour (tool behaviour, flag, default,
      format, error message, workflow step, measured difference) goes to
      CHANGELOG.md under [Unreleased]; gate, CI, tests, tooling,
      behaviour-neutral refactors and dependency bumps go to
      TECHNICAL_CHANGELOG.md. A mixed bullet is split, not reworded.
   g. Guides. Enumerate what describes what you touched:
        git grep -l -E '<the flag|default|format|message|count>' -- documentation/
      Edit the Markdown source, then render and prove it:
        python utilities/build_user_guides.py <module_dir>
        python utilities/build_user_guides.py --check
      If nothing describes the change, say so explicitly — a skipped review must
      be visible, not silent.
   h. Plan record. Tick the item; add a Decision Log row with the measured
      evidence and anything you did not verify. Follow-on work is a
      supersession entry, never a rewrite of a completed item.
   i. Commit, then do not re-run checks that already passed on unchanged files.

4. WHAT COUNTS AS EVIDENCE
   - Audio: decode the written file and measure per-channel RMS, integrated
     loudness, true peak, sample rate, channel count and bit depth. Reading back
     the value your own code just wrote proves nothing.
   - Tags: reload from disk with mutagen and compare every field plus the undo
     snapshot; FLAC tags are mutated in place, never rebound.
   - CLI: run the real argv through the real parser and assert the batch result.
   - GUI: widget contract (object.__new__ + MagicMock) plus the callback seams
     the payload-contract lock enforces.
   - Refactor: every pre-existing behaviour test still passes; a deleted public
     API gets an AST test that it is gone.
   - A harness that cannot fail is a defect: a scan asserts a non-empty result
     set, and break-and-restore keys on a FAILED/ERROR line with __pycache__
     cleared between runs.

5. STOP AND ASK — do not improvise past these
   - An assumption A1-A5 (index section 5) does not hold for the code.
   - The fix a defect needs lies outside the item's file list.
   - A dependency must be added or bumped.
   - A version number, tag, release cut (utilities/release.py) or push is
     involved.
   - A shipped lock must move beyond what the plan lists: test counts, CLI
     schema, generated docs/README tables, the naming ALLOWLIST, the CI cost
     budget, the callback EXPECTED_TOOLS set.
   - The only way to pass is to change a test's expectation.
   - Anything would touch a gitignored config or key file.

6. NEVER
   - Create a new PLAN_*.md; the plans exist. Extend them per 3h.
   - Skip, weaken, xfail or type-ignore a check to manufacture green.
   - Hand-edit a generated artefact (.docx, .pptx, README tool table, docs
     index, cli_schema.json).
   - Leave scratch files (repro_*.py, pytest_*.txt) in the tree or commit
     anything the item did not create.
   - Skip the gate because a change is "only docs" or "only tests".
   - Report a check as passing when it errored, was skipped or never ran.

7. REPORT AFTER EVERY ITEM — this shape, nothing longer
   ITEM:          <plan file> / <WP-n or F-x>
   CHANGED:       <files>
   TESTS:         <added/changed> — <n> passed
   GATE:          compile OK | ruff OK | format OK | mypy OK | bandit 0H/0M | pytest <n> passed, <n> skipped
   GUIDES:        <guides updated and re-rendered> | no guide describes this
   NOT VERIFIED:  <blocked checks and why>
   COMMIT:        <hash> <subject>
   NEXT:          <next eligible item>

8. SESSION END
   State what is done, what is not, and the next eligible item. Leave no
   uncommitted change and no scratch file. If the item is unfinished, name the
   step of section 3 where it stopped and why.
````

Change the release and item names in §1 only when a plan actually moves; the
prompt should not need editing between sessions.

## 8. Decision Log

| # | Date | Decision | Evidence |
|---|---|---|---|
| P-1 | 2026-11-03 | One execution plan per §11.2 item, plus this index, instead of one 40-page plan | Each item is independently schedulable and has a different gate profile |
| P-2 | 2026-11-03 | WP-10 is not silently folded into `2.4.3`; it is recommended there and recorded as unassigned | §11.2 omits it, and `C-I1` alone is larger than the rest of that release |
| P-3 | 2026-11-03 | The execution prompt lives in §7 of this index, not in a ninth file | It is a reusable operating instruction for these plans, so its single home is the file that already owns the shared mechanics (§4) |
