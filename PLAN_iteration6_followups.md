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
changes. Scheduled so far: A1 (withdrawn, no code), A2, A3 (complete —
Section A is closed); B1, B2, B3, B4 (complete) — Section B is closed.
**Last Updated:** 2026-09-29 (A1 withdrawn by maintainer decision; A2, A3 complete — Section A closed; B1, B2, B3, B4 complete — Section B closed)
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

### A2 `[x]` — Delete the provably dead pool-loop lines

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

**Resolution (2026-09-29):** both dead lines are gone, and the ``-1``
sentinel left the type contract rather than being replaced by a
``None``.  `_WorkerSlotTracker.acquire()` is now *blocking* (``Condition``
+ ``wait``), which is what its own docstring already claimed, and releases
route through a new `release(slot)` that notifies — so the "no slot
available" case has no value to return at all.  This is safe only because
each run path already bounds its own claims by `_count`: the thread path
through `ThreadPoolExecutor(max_workers=...)` (one slot per worker thread,
released before the thread takes its next item), the pool path through the
`len(pending) < slots._count` submit bound (one slot per in-flight file).
Both bounds are now stated in `acquire()`'s docstring, and the pool loop
carries a one-line comment stating why `pending` cannot be empty at
`as_completed()` — the invariant the deleted `if not pending: break` was
redundantly re-checking.

`slot >= 0` guards were **kept**: `active_slots.pop(file_path, -1)` is
still a real `-1` source (a file submitted while the stop event is already
set never gets an `active_slots` entry).

Converting the sentinel into a wait changes the failure mode of a
bound violation from "silently unlabelled worker box" to "batch stalls",
so two new tests pin that neither path over-claims: a `_RecordingTracker`
subclass flags any `acquire()` that finds the pool empty (must stay empty
across a real 5-file/2-worker pool run and a real 7-file/2-worker thread
run), and the thread-path one drives the batch from a watchdog thread so a
stall fails the test instead of hanging the suite.  Four of the six new
tests were confirmed to fail against the pre-change source.

The `if not pending: break` at the sibling site
`audio_fingerprinter/core/file_processor.py:503` was audited and is **not**
dead — it guards a fresh list comprehension, not the pool loop.

### A3 `[x]` — Gate `ffmpeg_finder` source 2 on a real executable file

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

**Resolution (2026-09-29):** `audio_normalizer/utils/ffmpeg_finder.py`
source 2 now gates on `os.path.isfile(local) and os.access(local, os.X_OK)`.
Both pinning tests were inverted, neither dropped —
`TestNoExecutabilityCheck` is now
`TestSourceTwoAcceptsOnlyRealExecutables` and contains
`test_executability_is_consulted_for_the_local_copy` (the exact inverse of
`test_os_access_is_never_consulted`, and it asserts the probed *mode* is
`X_OK`, not merely that a probe happened) plus
`test_a_directory_named_like_the_binary_is_rejected`, now **parametrized
over win32/linux/darwin** rather than the host's own platform, with source 3
denied explicitly so the win32 leg cannot pass by finding a real ffmpeg in
`C:\ffmpeg\bin`. All 4 fail against the pre-change source (verified by
`git checkout` swap).

Two consequences of the new gate had to be absorbed in the same change, and
both are places where a test would otherwise have silently stopped testing
what it claims:

- The gate no longer consults `os.path.exists`, so every test that used to
  force "no local copy" by stubbing `exists` alone was reading the **real**
  filesystem of whichever host ran it. A `_deny_local_copy()` helper now
  denies `exists` + `isfile` + `access` together, and the two
  singleton-cache tests instead redirect `__file__` to an empty directory —
  because they assert on the resolved path's real state, which a stub would
  have made vacuous (`test_reimporting_re_resolves_a_stale_singleton`
  previously asserted `not os.path.exists(...)` while `exists` was stubbed to
  `False`; it now uses the unpatched `os.path.lexists`).
- `_make_exe` now sets `0o755`. POSIX applies the new `X_OK` check for real,
  and a default-mode file is not executable — without the chmod every positive
  test would have failed on the Linux CI leg while passing on Windows.

The execute-bit test asserts the **platform difference** instead of skipping
(`test_a_non_executable_file_follows_the_platform_rule`): POSIX rejects the
copy, Windows accepts it because `os.access(X_OK)` there only reports
existence. A `skipif` was written first and deleted — it would have added a
4th skip to a suite whose baseline is 3, and per A1 no Linux host will ever run
it, so it would have rotted silently.

Source 3 (`C:\ffmpeg\bin\ffmpeg.exe`) is deliberately left on bare
`os.path.exists`: it is a hard-coded absolute path where a directory decoy is
not a real-world scenario, and the item scoped source 2. Recorded here as a
known asymmetry, not an oversight.

---

## Section B — Behaviour-decision items (decision first, then code)

### B1 `[x]` — Make noise dry-run reports honest

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

**Decision (2026-09-29, maintainer Wilte):** option A — match pop. A noise
dry run analyses and reports honestly; the write stays suppressed at the
write site.

**Resolution (2026-09-29):** the four-line `if params.dry_run:` short-circuit
is deleted from `reduce_noise()`, which is now mode-agnostic, so
`dry_run` has exactly one consumer in this tool: the `is_dry_run` flag
already passed to the shared in-place workflow that owns the write. Two
things were verified before deleting it, because a short-circuit can have
other readers:

- the Audio Refinery calls `reduce_noise()` directly
  (`audio_refinery/core/pipeline.py:273`), but returns at `pipeline.py:195`
  on its **own** `config.dry_run` long before reaching the noise stage, and
  neither `audio_refinery/cli.py:163` nor `utils/settings.py:114` ever sets
  `noise_reduction_params.dry_run` — so the short-circuit had no live reader
  outside this tool;
- `"Clean — no noise detected"` is still the correct text for a genuinely
  clean file, because the DSP now actually ran before claiming it.

Both C2 locks were inverted rather than deleted:
`test_dry_run_no_modification` → `test_dry_run_does_not_short_circuit_the_dsp`
(asserts the dry-run result equals the live result, audio and both energies,
so the flag provably changes nothing the DSP computes), and the
`test_dry_run_writes_nothing` pair in the two tools is now symmetric — both
assert `succeeded == 1` / `skipped == 0` plus SHA-256, mtime, no temp file
and no export call. The unchanged `"Clean — no noise detected"` status is
what a genuinely clean file now reports, which the pre-existing
`test_skips_clean_file` still pins.

**Guide audit: no edit needed, and this is the load-bearing evidence for
the decision** — `user_guides/individual_programs/noise_reduction/generate_guide.py`
already documented the *honest* semantics ("Dry Run analyzes without
writing", line 88; "Calculates the reduction path without exporting or
changing files", line 166). The documentation and the pop twin both already
described the fix; only the implementation diverged, so B1 brings the code
into line with the shipped guide rather than changing the guide.

### B2 `[x]` — Settle the undo contract (tag-only vs byte-level)

**Provenance:** iteration-5 C2 Decision Log row — the plan's "restored to
the original bytes" was unimplementable as written; only a tag-payload
round-trip exists in the suite.

**Problem:** the suite's undo (`record_tag_edit_snapshot()` +
`_revert_tag_edit()`) is tag-only; no byte-level undo exists anywhere. The
C2 tests assert the shipped contract and the gap is reported, not papered
over.

**Decision (Wilte, 2026-09-29): build byte-level restore.** The iteration-5
C2 row read the shipped tag-only code as unimplementable; the missing piece was
the *record type*, not a hard limit. One snapshot per file per batch (same
rule as the existing reorg/delete records) subsumes the tag payload, so the
tag round-trip becomes a strict subset of the file round-trip.

**Resolution:**

- `BatchUndoLog.record_file_overwrite()` stores the file's raw bytes under
  `file_action = "overwrite"` in the existing `old_tags_snapshot` BLOB
  column; `_revert_file_overwrite()` writes them back through a sibling
  `*.undo-restore` temp file plus `os.replace()` (atomic, same directory).
- `record_audio_overwrite_snapshot(file_path, operation)` is the shared entry
  point. An `OSError` reading the file degrades to the old
  `record_tag_edit_snapshot()` rather than blocking the tool's write, and a DB
  failure is swallowed so undo logging can never abort a run.
- `file_processor_base.py` calls it immediately before the in-place
  `shutil.copy2()` — the one write site every in-place tool shares, so all of
  them gain the behaviour from a single change.

**Acceptance:** whichever is chosen, a regression test that exercises it
on a real audio file (for byte-level: modify, undo, assert the file hashes
equal the original), plus the documentation stating the contract.

**Continuation of the resolution — dispatch, surfaces, cap:**

- `revert_batch()` dispatches `overwrite` **before** the generic tag-snapshot
  branch. The order is load-bearing: the raw payload is not a pickle, and a
  generic-first dispatch fails the revert with `invalid load key` (proven
  below).
- `undo_gui.record_preview_line()` renders `Restore original audio: ...` for
  overwrite records, and `_TOOL_DISPLAY_NAMES` gained `noise_reduction` and
  `pop_click_remover`, which previously listed by raw id.
- `utilities/undo.py` marks the detail line `[audio-bytes]`, not
  `[snapshot]`.
- **Cap behaviour, decided rather than hidden:** the log's existing
  `_DEFAULT_MAX_ENTRIES = 50` / `_DEFAULT_MAX_BYTES = 1 GiB` budget is
  unchanged, and a byte payload counts a whole file, so one large batch can
  consume it. No per-file refusal and no silent skip: oversized batches are
  pruned oldest-first as whole batches, so their entry leaves the list. The
  undo guide documents this with a keep-your-own-backups instruction, and a
  test prunes at `max_bytes=1024` and asserts the batch is gone.
- The window title stays "Undo Tag Edits" and the manifest id is unchanged;
  renaming a utility's public identity is outside this item's scope. The
  *documented contract* inside it is now the full file.

**Inverted locks.** The iteration-5 C2 tests asserted the *limitation*
(`_sha256(audio_file) == repaired_bytes`, i.e. the audio deliberately not
restored) and put the "C2's scope forbids that" rationale in the docstring.
Both are now inverted in `noise_reduction/tests/test_file_processor.py` and
`pop_click_remover/tests/test_file_processor.py`: each records the pre-run
digest and bytes, proves the repair changed the file, corrupts the tags
afterwards, and asserts the reverted file matches the original digest *and*
the original tag.

**Proofs.**

- Reverting with the branch order deliberately inverted (generic tag branch
  first) fails with `invalid load key, 'O'` — the raw payload reached
  `pickle.loads()`. Restored from a SHA-256-verified backup;
  `test_batch_undo.py` then reported 72 passed.
- Reverting the write site to `record_tag_edit_snapshot()` fails both
  inverted round-trip tests with `file_action=None` instead of `"overwrite"`,
  then 223 passed after byte-exact restore of `file_processor_base.py`.
- New: `TestRecordFileOverwrite` (revert restores original bytes, payload is
  not unpickled, first-snapshot dedup, no temp file left) and
  `TestRecordAudioOverwriteSnapshot` (records bytes, no-op without a batch,
  `OSError` degrades to the tag snapshot, DB failure does not block, cap
  pruning).
- Updated: the three `record_tag_edit_snapshot` patch sites in
  `audio_suite_shared/tests/test_file_processor_base.py`; new
  `test_in_place_audio_revert_does_not_claim_tags` and
  `test_in_place_audio_tools_mapped` in `test_undo_gui.py`; new
  `test_shows_in_place_audio_record_as_audio_bytes` in
  `utilities/tests/test_undo.py`.

**Guide audit:** the undo guide's "What Can Be Undone", the cap section
(new), the preview examples, the confirmation text, the
"Files Changed By Another Tool" warning, the quick start and troubleshooting
were all tag-only and are now whole-file. Noise Reduction and Pop & Click
Remover guides claimed only "tag-edit undo snapshots" / asked the user to keep
backups for audio recovery; both now state the byte-for-byte restore and the
cap. All three generators were re-run, so the three DOCX files are
regenerated from the edited sources.

**Gate evidence:** compile 0 · ruff clean / 757 format-stable · mypy strict
0 issues / 452 files · bandit 0H/0M/51L · bare suite **7543 passed** / 3
skipped / 30 deselected · coverage **79.13%** ≥ 75. Net **+12 tests**
(7531 → 7543), skip count unchanged at 3.

### B3 `[x]` — Decide the low-confidence KEY-tag policy

**Provenance:** iteration-5 F2 Decision Log row (scope, known gap).

**Problem:** `key_detector.core.file_processor` writes `detect_key`'s
result straight to a file's KEY tag, so untuned material is now tagged
`"Unknown"` after F2. F2's scope kept `file_processor` untouched, so the
documented `'Unknown'` fallback flows into real tags today — the behaviour
is stated in `key_engine`'s module docstring but never decided for the
*tag* surface.

**Decision needed (the F2 row's own three options):** leave untagged (skip
the write), tag `'Unknown'`, or report as skipped.

**Decision (Wilte, 2026-09-29): leave untagged, report as detected.** Not
"skipped": the analysis did run and the user should see that the file was
examined, so the status is `DETECTED (not tagged)` rather than a skip that
implies no work happened. A `KEY="Unknown"` in a library is a claim the
analyser cannot support, and it also poisons later passes: a file tagged
`Unknown` looks "already analysed" to Dry Run, so the user is locked out of a
better result on a re-run.

**Resolution:**

- `_should_tag_key(detected_key)` in `key_detector/core/file_processor.py` is
  the single source of truth for the policy (`UNKNOWN_KEY` → do not write),
  used by **both** the serial `_detect_file()` and the parallel
  `_handle_key_result()`. Two call sites with the same contract are exactly
  the shape that drifts, so the branch is a named helper rather than a
  duplicated `!=` check.
- Status becomes `DETECTED (not tagged)` via `_TAG_STATUS_UNKNOWN`; the
  dry-run path keeps the plain `DETECTED` status it already had, since
  nothing was written either way.
- An existing KEY tag is left exactly as it is — the undecidable result never
  overwrites a value from a previous good run.
- `key_engine`'s module docstring and `detect_key`'s
  `low_confidence_threshold` note previously stated that the tag writer
  *would* write `"Unknown"`; both now state the decided policy. The engine
  still returns `UNKNOWN_KEY` — only the tag surface changed.

**Acceptance:** a real-tag regression test for the chosen behaviour —
write to a real file, read the tag back through the tag reader — plus the
module docstring updated to state the decided policy.

**Proof.** Five new tests in `TestUnknownKeyIsNeverTagged` use **real WAV
files and the real `read_key`/`write_key`**, never a mocked writer: a mocked
`write_key` passes identically whether the code writes nothing, writes
`"Unknown"`, or writes the wrong value, so it cannot witness this policy at
all. Coverage: serial path leaves an untagged file untagged; serial path
preserves a pre-existing real `Am` tag; parallel path leaves a real file
untagged; dry run reports without a write; and a control that a defensible key
*is* still written to a real file — without it, a regression that turned every
run into a no-op would satisfy all the others.

Verified against the pre-change source (policy branch reverted, SHA-256
restore): **3 of the 5 fail** — `read_key` returns `"Unknown"` instead of
`None`, and the pre-existing `Am` is overwritten. The control and the dry-run
test pass in both states, as they should. After restore: 199 passed in
`key_detector/tests`.

**Guide audit:** the key detector guide documented neither the `Unknown`
behaviour nor its absence — its "Live Update" section said the detected key
is written, unqualified. Added a "Material with no defensible key" bullet
(what triggers it, that it reports instead of writing, that an existing tag
survives, and why `Unknown` is never written) and qualified the Live Update
bullet. Generator re-run; DOCX regenerated.

### B4 `[x]` — De-in-place `set_active_palette()`

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

**Decision (Wilte, 2026-09-29): the second scope option — make the active
palette a separate resolution step, and keep the Windows Accent swatch live.**

**Resolution:**

- `_WINACCENT_LIVE` holds the accent read from the registry;
  `PALETTES["Windows Accent"]` is never written to. The first scope option
  (rebuilding the whole table) was rejected because the swatch then depends
  on a rebuild having happened, and the user asked for the swatch to keep
  showing the accent actually in force.
- `_resolve_palette(name)` is the single read path: the live accent for
  `"Windows Accent"` once probed, otherwise the table entry. It returns a
  **fresh dict** in both branches — the first version returned the table
  entry by reference, which a new test caught immediately, since a caller
  that mutates what it is handed could then write straight into `PALETTES`
  (the same bug class as the in-place update, one level down).
- `set_active_palette()` applies `_resolve_palette(resolved)` where
  `resolved` is the name, or the saved preference when a probe raises. The
  probe path clears `_WINACCENT_LIVE` first, so a failed probe can never
  inherit the previous session's accent — the concrete leak the in-place
  mutation caused.
- `set_theme_mode()` and `get_active_palette_name()` both go through the
  resolver, and `master_driver/ui/cards/palette_card.py` iterates
  `PALETTES` by key and resolves each swatch, so the picker previews the
  accent in force instead of the static placeholder.
- The live store is *not* re-probed on every read: it is replaced when a
  selection probes it and cleared when a probe fails. Re-reading the
  registry on each repaint would be slow and would turn a transient
  registry error into a visible colour change.

**Tests.** 8 new tests in `TestWindowsAccentIsNotWrittenBackIntoPalettes`
with an autouse snapshot/restore fixture — snapshot, never
`importlib.reload()`, because reload rebuilds `PALETTES` but does not undo an
in-place dict mutation, which is the whole point of this item. They cover:
PALETTES unmutated by a probe while the accent is still applied; the resolver
serving the live accent; both branches returning a copy; ordinary and unknown
names; the stale-accent leak after a failed probe; `get_active_palette_name()`
still reporting `"Windows Accent"`; and the placeholder before any probe.

A `_RaisingWinAccent` helper was needed rather than a MagicMock with
`accent_normal = OSError(...)`: the code *reads* the attribute, so storing an
exception instance silently returns the exception object and the failure path
under test never runs — the test would have passed vacuously.

Verified against the pre-change code (in-place `update()` reinstated,
SHA-256-verified restore): **2 of the 8 fail** — `PALETTES["Windows Accent"]`
differs after a probe, and `_WINACCENT_LIVE` is left holding the old accent
after a failed probe. `test_fallback_survives_a_palette_polluted_by_an_earlier_test`
(the item's named regression) passes in both states, **unedited in its
assertions**; only its docstring was corrected, since it described the
production mutation that B4 deletes. Two other docstrings that cited the same
deleted coupling were corrected in place.

**Guide audit: no guide change required** — the palette picker is a
Master Driver setting with no generated guide of its own, and no user guide
describes the Windows Accent fallback ordering.

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
| A2 | A | 2026-09-29 | compile 0 · ruff clean / 757 format-stable · mypy strict 0 issues / 452 files · bandit 0H/0M/51L · bare suite **7528 passed** / 3 skipped / 30 deselected · coverage **79.15%** ≥ 75 | Dead `if not pending: break` deleted (invariant stated in a comment); the unreachable `return -1` removed by making `acquire()` blocking + adding `release(slot)`, per the item's first scope bullet. B1's pool tests pass **unedited**. 6 new tests in `mood_analysis_batch_tagger/tests/test_batch_analysis_engine.py` (`TestWorkerSlotTracker` + two exhaustion probes); 4 of 6 verified to fail pre-change via a SHA-256-verified source swap. No user-guide impact (worker-slot labelling behaviour is unchanged). |
| A3 | A | 2026-09-29 | compile 0 · ruff clean / 757 format-stable · mypy strict 0 issues / 452 files · bandit 0H/0M/51L · bare suite **7531 passed** / 3 skipped / 30 deselected · coverage **79.11%** ≥ 75 | Source 2 gated on `isfile` + `access(X_OK)`. Both defect-pinning tests inverted (none deleted, none weakened): `test_executability_is_consulted_for_the_local_copy` asserts the probed mode, `test_a_directory_named_like_the_binary_is_rejected` parametrized win32/linux/darwin; both verified to fail pre-change. Net +3 tests. `_deny_local_copy()` + `__file__` redirection absorb the gate's move off `exists` (and de-vacuate a self-fulfilling `exists` assertion); `_make_exe` now chmods `0o755` so the Linux leg's real `X_OK` check passes. **Skip count unchanged at 3** — a `skipif` version of the execute-bit test was written and deleted in favour of asserting the platform difference. Source 3 left on `exists` by design. Guides audited: no guide documents the finder's discovery sources; A5 `TestGuideWordingLock` green. |
| B1 | B | 2026-09-29 | compile 0 · ruff clean / 757 format-stable · mypy strict 0 issues / 452 files · bandit 0H/0M/51L · bare suite **7531 passed** / 3 skipped / 30 deselected · coverage **79.11%** ≥ 75 | Maintainer Wilte chose option A (match pop). The 4-line `if params.dry_run:` short-circuit is deleted, so `reduce_noise` is mode-agnostic and `dry_run` has exactly one consumer — the `is_dry_run` flag handed to the shared write site. Verified the short-circuit had no other live reader: the Refinery returns at `pipeline.py:195` on its own `config.dry_run` and never sets `noise_reduction_params.dry_run` (`cli.py:163`, `settings.py:114`). Both C2 locks inverted, none deleted: `test_dry_run_no_modification` → `test_dry_run_does_not_short_circuit_the_dsp` (asserts the dry result equals the live result — audio plus both energies — so the flag provably changes nothing the DSP computes), and the two tools' `test_dry_run_writes_nothing` are now symmetric (`succeeded == 1` / `skipped == 0` + SHA-256 + mtime + no temp file). `test_export_call_count_differs_between_dry_run_and_live` and `test_skips_clean_file` pass **unedited** — the 0-export write gate and the honest clean verdict are both still enforced. **Guide audit: no edit** — `noise_reduction/generate_guide.py:88` and `:166` already documented "Dry Run analyzes without writing" / "Calculates the reduction path without exporting", i.e. the shipped guide and the pop twin already described the fix and only the code diverged. Net test count unchanged (one test renamed). |
| B2 | B | 2026-09-29 | compile 0 · ruff clean / 757 format-stable · mypy strict 0 issues / 452 files · bandit 0H/0M/51L · bare suite **7543 passed** / 3 skipped / 30 deselected · coverage **79.13%** ≥ 75 | Maintainer Wilte chose byte-level restore. The iteration-5 C2 row called the contract unimplementable, but the missing piece was the *record type*: `record_file_overwrite()` stores raw bytes under `file_action="overwrite"` in the existing BLOB column, and `revert_batch()` dispatches it **before** the generic tag branch (the order is load-bearing — generic-first fails with `invalid load key`, proven by a deliberate branch swap and a SHA-256-verified restore). `file_processor_base.py` swaps `record_tag_edit_snapshot` → `record_audio_overwrite_snapshot` at the one shared in-place `copy2()` write site, so every in-place tool gains it from a single change. Both C2 locks **inverted**, neither deleted: each tool test now records the pre-run digest and bytes, proves the repair changed the file, corrupts the tags afterwards, and asserts the reverted file matches the original digest and tag; verified to fail pre-change (`file_action=None`). **+12 tests**: 9 in `TestRecordFileOverwrite`/`TestRecordAudioOverwriteSnapshot`, 2 in `test_undo_gui.py`, 1 in `utilities/tests/test_undo.py`; the 3 `record_tag_edit_snapshot` patch sites in `test_file_processor_base.py` were retargeted and pass **unedited** otherwise. **Cap decided, not hidden:** 50 runs / 1 GiB unchanged, bytes count whole files, the oldest batch is pruned whole, pinned by a `max_bytes=1024` prune test and documented with a keep-your-own-backups instruction. **Guide audit: 3 guides edited and regenerated** (undo, noise, pop) — all three were tag-only. |
| B3 | B | 2026-09-29 | compile 0 · ruff clean / 757 format-stable · mypy strict 0 issues / 452 files · bandit 0H/0M/51L · bare suite **7548 passed** / 3 skipped / 30 deselected · coverage **79.14%** ≥ 75 | Maintainer Wilte chose leave-untagged, reported as detected. `_should_tag_key()` is the single source of truth and both the serial `_detect_file()` and the parallel `_handle_key_result()` consult it, so the two paths cannot drift; the status becomes `DETECTED (not tagged)`, an existing KEY survives, and the dry-run path keeps its plain `DETECTED`. Not chosen: 'skipped' (the analysis ran, and the user must see it), and `KEY="Unknown"` (a claim the analyser cannot support that also makes Dry Run treat the file as already analysed, locking out a better re-run). The engine still returns `UNKNOWN_KEY` — only the tag surface changed; `key_engine`'s module docstring and `detect_key`'s threshold note, which both said the writer *would* write `"Unknown"`, now state the policy. 5 new real-file tests (real WAV + real `read_key`/`write_key`, since a mocked writer passes whether the code writes nothing or the wrong value) covering both paths, tag preservation, dry run, and a control that a defensible key is still written; **3 of 5 verified to fail pre-change** (`read_key` returned `"Unknown"`, `Am` overwritten) via a SHA-256-verified source restore, after which `key_detector/tests` reported 199 passed. Guide edited (new "no defensible key" bullet + qualified Live Update) and regenerated. |
| B4 | B | 2026-09-29 | compile 0 · ruff clean / 757 format-stable · mypy strict 0 issues / 452 files · bandit 0H/0M/51L · bare suite **7556 passed** / 3 skipped / 30 deselected · coverage **79.17%** ≥ 75 | Maintainer Wilte chose the second scope option (separate resolution step, swatch stays live) over rebuilding `PALETTES`, which would make the swatch depend on a rebuild having happened. The live accent now lives in `_WINACCENT_LIVE` and `PALETTES["Windows Accent"]` is never written; `_resolve_palette(name)` is the single read path and returns a **fresh dict** in both branches — the first version returned the table entry by reference and a new test caught it immediately (a caller mutating what it is handed would write straight into `PALETTES`: the same bug class one level down). A failed probe clears the live store first, so it can never inherit the previous session's accent — the concrete leak the in-place mutation caused. `set_theme_mode`, `get_active_palette_name` and `palette_card` all read the resolver, so the picker previews the accent in force. The store is replaced on a successful probe and cleared on a failed one, never re-read per repaint. 8 new tests with an autouse **snapshot/restore** fixture (snapshot, never `importlib.reload()`, which rebuilds `PALETTES` but does not undo an in-place mutation — the point of this item); **2 of 8 verified to fail pre-change** (table differs after a probe; live store retains the old accent after a failed probe) via a SHA-256-verified restore. Needed a `_RaisingWinAccent` helper, not a MagicMock carrying an `OSError` instance: the code reads the attribute, so the exception object would be returned and the failure path would never run — a vacuous pass. The item's named regression `test_fallback_survives_a_palette_polluted_by_an_earlier_test` passes **unedited in its assertions**; its docstring and two others that cited the deleted production coupling were corrected. No guide change required (no generated guide covers the palette picker). |
