# Follow-Ups Plan — Iteration 6 — AudioSuite-Pro

**Source:** opened at the close of `PLAN_iteration5_remediation.md`
(2026-09-28) to satisfy its Plan Close-Out Checklist item "Any **new** plan
opened for the deliberately-excluded work, so nothing is silently dropped".
Every item below carries its provenance — the iteration-5 roadmap sentence
or Decision Log / Completion Log row it comes from.
**Status:** Active (backlog) — **no item is authorized for implementation until
the maintainer schedules it.** No audit drives these items. When an item is
picked up, it receives the full six-field treatment (priority / effort / risk,
scope checkboxes, lockstep tests, acceptance, risks) here before any code
changes. Scheduled so far: A1 (withdrawn, no code).
**Last Updated:** 2026-09-29 (A1 withdrawn by maintainer decision)
**Governing plan:** this file, once scheduled. `PLAN_iteration5_remediation.md`
is a completed record; this file is its supersession entry in plan form.
The iteration-5 roadmap's "each belongs in its own plan with the user's
approval" rule applies to the Section C items: this file is the backlog
index, and each Section C item is expanded into its own dedicated plan when
the maintainer schedules it.

**Scope:** two groups. Section A/B items are evidence-debt and behaviour
decisions recorded during iteration 5 but out of that plan's own scope
rules; Section C is the iteration-5 roadmap's deliberately-excluded work,
preserved here verbatim so nothing is silently dropped.

---

## How to read this plan

- Items in **Section A** are small and mechanical; they can be picked up
  individually.
- Items in **Section B** need a maintainer decision before any code is
  written — the decision is part of the item.
- Items in **Section C** are large standalone efforts; scheduling one opens
  its own dedicated plan.
- All of them inherit the iteration-5 hard rules: minimal diff, lockstep
  tests, the six-command Phase Gate per item (compile, ruff check + format
  check, `mypy .`, bandit with `-c pyproject.toml -x ./.venv`, bare
  full-suite `pytest`, coverage ≥ 75 per decision D3, staged secret scans),
  and audio-write items validated by decoding and measuring, never by
  reading back written state.

---

## Phase Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]`  | Not started (unscheduled) |
| `[-]`  | In progress |
| `[x]`  | Completed |
| `[~]`  | Partially completed |
| `[!]` | Blocked — needs a maintainer decision |
| ~~ | Withdrawn — the maintainer decided the item is not required |

---

## Section A — Evidence-debt items (small, mechanical)

### A1 `~~` — Record A4's first CI run evidence — **WITHDRAWN, not required**

**Provenance:** iteration-5 A4 Completion Log row + close-out decision
(2026-09-28, maintainer Wilte).

**Problem:** A4's acceptance requires the first post-merge CI run URL and
the Linux leg's passed-test count, appended to the iteration-5 Completion
Log. The repository has no git remote, so the evidence cannot exist yet;
the plan closed with the condition *named*, not silent.

**Decision (2026-09-29, maintainer Wilte): the item is not required and is
withdrawn.** There is no UNIX/Linux environment available to this project, so
the Linux CI leg is never executed and the required evidence can never be
produced. The A4 CI configuration (matrix 3.11 / 3.12 / 3.14, the Linux
`xvfb` + `python3-tk` + `ffmpeg` steps) stays in the workflow unchanged — it
is correct if a remote and a Linux runner ever appear — but no further work
is owed on collecting its evidence, and iteration-5's audit-index finding #4
is **not** re-opened by this item.

**Voided on withdrawal:** the push/run/append/triage scope below is not
performed; finding #4 is not flipped to `[x]`, because it is closed as *not
applicable* rather than as *verified*.

**Supersession note:** iteration-5's finding #4 stays `[~]` in
`PLAN_iteration5_remediation.md` (a completed historical record). Its named
re-open condition now points at an item that will never be worked; the
withdrawal is recorded here, the single place the plan designated for it.

**Original scope (superseded, kept for provenance):**

- Push to the remote and let CI run the matrix (3.11 / 3.12 / 3.14,
  Windows + Linux with the A4 `xvfb` + `python3-tk` + `ffmpeg` steps).
- Append the run URL + Linux passed count to the iteration-5 A4 row.
- Flip the audit-index finding #4 tick `[~]` → `[x]` in
  `PLAN_iteration5_remediation.md`.
- Triage any latent Linux failure per A4's own risk note: a genuine
  platform bug is fixed with a regression test; a genuine limitation gets
  an explicit, reviewed skip. The B4 blanket skip is **not** reinstated.

**Acceptance:** none — withdrawn by maintainer decision (2026-09-29).

### A2 `[ ]` — Delete the provably dead pool-loop lines

**Provenance:** iteration-5 B1 Completion Log row (its own rule: structural
cleanup is a separate item, not smuggled into a coverage fix).

**Problem:** `mood_analysis_batch_tagger/core/batch_analysis_engine.py:624`
(`if not pending: break`) is dead code — the outer `while index <
len(pending_list) or pending` at `:607` guarantees `pending` is non-empty on
entry and nothing between `:607` and `:623` removes from it — and the
`-1` fallback in `_WorkerSlotTracker.acquire` (`:104`) is unreachable from
the pool path, whose inner `while` bounds `len(pending) < slots._count`
before each submit.

**Scope:**

- Delete line 624 and the unreachable `return -1` fallback, or restructure
  the outer loop so the invariant is stated once.
- Keep B1's regression tests green **unchanged** — they are the behaviour
  lock for the pool path.

**Acceptance:** Phase Gate; B1's pool tests pass unedited; the dead lines
gone.

### A3 `[ ]` — Gate `ffmpeg_finder` source 2 on a real executable file

**Provenance:** iteration-5 B3 Completion Log row + Decision Log.

**Problem:** the finder's source 2 accepts anything `os.path.exists`
returns true for — a *directory* named `ffmpeg(.exe)` beside the module
resolves as the binary, and every ffmpeg-backed tool then fails at exec
time with an opaque error. `test_a_directory_named_like_the_binary_is_accepted`
currently pins the defect as the shipped behaviour.

**Scope:**

- `os.path.isfile(...) and os.access(..., os.X_OK)` in the source-2 gate.
- **Invert, never delete,** the pinning tests: the directory-acceptance
  test becomes a directory-*rejection* test, and
  `test_os_access_is_never_consulted` is removed only because its subject
  line now exists in production.

**Acceptance:** Phase Gate; the finder tests updated in lockstep, none
weakened; a directory named like the binary no longer resolves.

---

## Section B — Behaviour-decision items (decision first, then code)

### B1 `[!]` — Make noise dry-run reports honest

**Provenance:** iteration-5 C2 Decision Log row — "dry-run divergence
between the twins is a product defect", preserved byte-for-byte by the C2
behaviour-preservation refactor.

**Problem:** `reduce_noise()` short-circuits on `params.dry_run` and
returns `was_modified=False`, so a noise dry run reports `SKIP ("Clean")`
even on a file it *would* repair, while pop dry runs correctly report
`FOUND`. The C2 outcome tests pin the divergence (0 dry / 1 live exports on
both sides).

**Decision needed:** should a noise dry run decode + analyse and report
honestly (matching pop's semantics), or is the current short-circuit
intended behaviour?

**Scope (option A — match pop):** move the `dry_run` check after
decode + analysis so the report reflects what a live run would do; keep
the write path gated exactly as the "mode flags must be traced end-to-end
to the write site" rule requires.

**Acceptance:** the C2 dry-run lock updated in lockstep (SHA-256 + mtime
unchanged, no output file, no export call) with the honest `FOUND` report
asserted on a repairable file.

### B2 `[!]` — Settle the undo contract (tag-only vs byte-level)

**Provenance:** iteration-5 C2 Decision Log row — the plan's "restored to
the original bytes" was unimplementable as written; only a tag-payload
round-trip exists in the suite.

**Problem:** the suite's undo (`record_tag_edit_snapshot()` +
`_revert_tag_edit()`) is tag-only; no byte-level undo exists anywhere. The
C2 tests assert the shipped contract and the gap is reported, not papered
over.

**Decision needed:** declare tag-only undo as the contract (and state it
in the affected user guides), or build byte-level restore (file
backup/restore entries in `BatchUndoLog`).

**Acceptance:** whichever is chosen, a regression test that exercises it
on a real audio file (for byte-level: modify, undo, assert the file hashes
equal the original), plus the documentation stating the contract.

### B3 `[!]` — Decide the low-confidence KEY-tag policy

**Provenance:** iteration-5 F2 Decision Log row (scope, known gap).

**Problem:** `key_detector.core.file_processor` writes `detect_key`'s
result straight to a file's KEY tag, so untuned material is now tagged
`"Unknown"` after F2. F2's scope kept `file_processor` untouched, so the
documented `'Unknown'` fallback flows into real tags today — the behaviour
is stated in `key_engine`'s module docstring but never decided for the
*tag* surface.

**Decision needed (the F2 row's own three options):** leave untagged (skip
the write), tag `'Unknown'`, or report as skipped.

**Acceptance:** a real-tag regression test for the chosen behaviour —
write to a real file, read the tag back through the tag reader — plus the
module docstring updated to state the decided policy.

### B4 `[ ]` — De-in-place `set_active_palette()`

**Provenance:** the intermittent `test_styles.py` Decision Log row (Stage
5) — fixed test-side there; the production mutation was out of scope and
recorded as a follow-up.

**Problem:** `set_active_palette()` mutates the module-level `PALETTES`
dict in place, so any `importlib.reload()`-based restore silently does not
restore — the coupling wart that made two tests order-dependent.

**Scope:**

- Replace, don't mutate: rebuild `PALETTES` on change, or make the active
  palette a separate resolution step.
- Keep every styles test green; no caller-visible behaviour change.

**Acceptance:** Phase Gate; the deterministic pollution regression
(`test_fallback_survives_a_palette_polluted_by_an_earlier_test`) still
passes; no styles consumer changes behaviour.

---

## Section C — Deliberately-excluded work (iteration-5 roadmap, verbatim scope)

Each item here is quoted from the iteration-5 roadmap's "Deliberately not
in this plan" list. Each is real work with real value; scheduling one opens
its own dedicated plan with the maintainer's approval — this section is
the index that guarantees none is silently dropped.

### C1 `[ ]` — macOS parity pass

Extend the G1 platform matrix to macOS: every subprocess site, every
`sys.platform` branch classified "Unverified", the D5 declared-matrix
method applied to a third tier. Multi-week; touches every subprocess site.

### C2 `[ ]` — Real plugin architecture

A true plugin ABI for tool registration (the C3 split made the registry
declarative; a plugin system makes it externally extensible). Scope
includes the card/CLI/guide/arg-builder/batch/state surfaces of the
AGENTS.md "Registering a New Tool" checklist.

### C3 `[ ]` — Per-tool GUI test coverage across all 27 tools

The `gui` marker and the bounded skip (B4) made GUI tests *possible*; this
item makes them *present* — extending the C1 `analysis_app_base` pattern's
test coverage to every tool's `app.py`/`ui/` surface.

### C4 `[ ]` — Key-detection profile tuning against a labelled corpus

F2's own circularity rule: tuning the K-S profiles on the F1 vectors and
then citing those vectors as validation is forbidden. The honest path is a
labelled, human-annotated corpus (redistributable under GPL-3.0-or-later),
with the F1 vectors kept as the regression lock, not the tuning set.

### C5 `[ ]` — Master Driver / batch orchestrator refactor

Any refactor of the Master Driver or batch orchestrator — explicitly out
of iteration-5's scope by its own roadmap sentence.

---

## Completion Log

Fill one row per **item**, with the same per-item Gate Evidence rule as
iteration 5 (date + the six commands + pass/coverage counts — a row without
Gate Evidence is incomplete by definition).

| Item | Section | Completed | Gate Evidence | Notes |
|------|---------|-----------|---------------|-------|
| A1 | A | **Withdrawn 2026-09-29** | n/a — no code change | Maintainer Wilte: no UNIX/Linux environment exists for this project, so the Linux CI leg is never run and the A4 run-URL/passed-count evidence can never be produced. Item closed as not required, not as verified; A4's CI configuration is left in place unchanged. Iteration-5 finding #4 stays `[~]` in that closed plan (historical record) and is not re-opened. |
