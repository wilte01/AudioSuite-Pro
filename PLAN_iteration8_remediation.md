# Independent Audit Remediation Plan — Iteration 8 — AudioSuite-Pro

**Source:** `AUDIT_2026-10-02_suite_report.md` (independent re-audit of commit
`c1daf1d`, 2026-10-02). That report raised **4 High + 24 Medium + a documented
set of Low/hygiene findings**, plus a P0–P4 recommendation list and a market
comparison. This plan remediates every finding the report marks for resolution
— H1–H4 and M1–M24 — so nothing is silently dropped.
**Status:** Staged, not authorised. **No item may be implemented until the
maintainer schedules its Sprint.** Sprints 0–2 carry no open decisions and may
be scheduled independently; Sprint 3 needs the maintainer's option pick for
item I2; Sprint 4 is capability work that expands into its own plans.
**Baseline gate at `c1daf1d` (measured by the audit, not asserted):** compile
exit 0 · `ruff check` "All checks passed!" · `ruff format --check` clean on 783
files · `mypy --strict` "Success: no issues found in 460 source files" · bandit
0 High / 0 Medium / 41 Low · bare suite **8,091 passed / 3 skipped / 30
deselected** in 210.20s · coverage **88%** (28,174 statements, 3,415 missed;
`fail_under = 75`) · 0 production modules at 0% coverage · 0 bare `except:` ·
0 `contextlib.suppress`.
**Governing plan:** this file. `PLAN_iteration7_remediation.md` is a completed
historical record; its deferred items (B4's named follow-up → **I3**, the
card-shell family → **I2**, iteration-6 §C backlog → Sprint 4) are **transferred
here with provenance noted**. E6/E7 remain parked in iteration-7 and are
restated here only as the Sprint 4 disposition.

---

## How to read this plan

Every item uses the same seven fields:

- **Priority / Effort / Risk** — sequencing input, not a promise.
- **Problem** — the finding, restated with the report's verified `file:line`
  evidence. All anchors in this plan were re-verified against `c1daf1d`.
- **Scope** — the exact edits. Checkboxes are work units; tick on commit.
- **Tests (lockstep)** — tests written in the *same* change, per `AGENTS.md`
  §7. No item ships without them.
- **Acceptance** — the command output / measurement that closes the item.
- **Negative controls** — how the item's own regression tests are *proved to
  fail* against the pre-fix behaviour, SHA-256-verified on restore.
- **Risks** — what the item could break, and the guard already in place.

**Per-item gate (mandatory, inherited):** an item is complete only when its
Completion Log row carries **Gate Evidence** — the date, the six Phase Gate
commands, and their pass/coverage counts, recorded **per item, not per sprint**.
A row without Gate Evidence is, by definition of the table, an incomplete item.

**Naming convention (avoiding the audit-ID collision).** The audit's findings
are `H1`–`H4` and `M1`–`M24`. This plan's items are also lettered by Sprint.
Where they collide, the audit finding is **always written in full as "audit H1"**
/ "audit M7", and a bare `A2`/`B3`/`C1` always means *this plan's item*.
Decisions are `decision J1`, `decision J2`, etc. This is the convention
iteration 5 and iteration 7 both used, for the same reason.

**Hard rules inherited from `AGENTS.md`** and repeated because they are the ones
a multi-stage plan most easily violates:

- Minimal diff. No refactoring outside the item's stated scope. A refactor that
  looks necessary is a new item with the user's approval.
- A defect discovered while implementing an item is fixed in the same change,
  with a regression test, and recorded in this plan's Completion Log.
- New third-party dependencies require explicit user approval.
- The final gate is a **bare full-suite** `pytest` run.
- The compile/import gate is mandatory after any edit to an import chain.
- **Audio-write and artifact-correctness changes are validated by decoding and
  measuring the result**, never by reading back written state. Two items here
  (A1, A2) are exactly this class.
- A coverage number is only valid if the `.coverage` data file came from the run
  being reported — regenerate in the same command block as the bare run
  (`AGENTS.md` §6 item 10). Any scoped `--cov` probe during an item invalidates
  the file for reporting; re-run bare before recording gate evidence.
- **A test that asserts a side effect does *not* happen is a bug in waiting**
  (`AGENTS.md` §7). Every new test in this plan asserts the positive contract.
  Audit M20's dead `--end` flag is the archetype: a test proving "nothing
  happens" would have passed forever.

---

## Phase Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]`  | Not started (unscheduled) |
| `[-]`  | In progress |
| `[x]`  | Completed |
| `[~]`  | Partially completed |
| `[!]`  | Blocked — needs a maintainer decision |

---

## Audit Finding Index

Every audit finding the report marks for resolution appears exactly once.

| Audit finding | Severity | Class | Sprint | Closed by |
|---|---|---|---|---|
| audit H1 — `tag_field_updater --dry` writes tags anyway; `--dry-run` help flag does not exist | **High** | Data integrity / contract | 0 | `[ ]` A1 |
| audit H2 — `_write_rip_cue` emits one `FILE` for all tracks, reads `_path` after the loop, all offsets 0 | **High** | Artifact correctness | 0 | `[ ]` A2 |
| audit H3 — Tk mutated from worker threads in `album_genre_tagger` + `album_art_sync`; false safety claim | **High** | Thread safety | 0 | `[ ]` A3 |
| audit H4 — Master Driver re-reads ~40 live Tk vars on the launch thread | **High** | Data integrity / thread | 0 | `[ ]` A4 |
| audit M1 — production-dead legacy argparse subsystem (~300 lines) + `parse_cli_args` name collision | Medium | Maintainability | 2 | `[ ]` E1 |
| audit M2 — dead symlink-detection branch; docstring documents a control that cannot run | Medium | Security / docs | 1 | `[ ]` C1 |
| audit M3 — two sources of truth for supported extensions, already drifted (`.mp4`/`.opus` rejected, `.wma` accepted) | Medium | Data contract | 1 | `[ ]` C1 |
| audit M4 — `CHANGELOG.md` `[Unreleased]` empty after a release-sized iteration | Medium | Docs | 1 | `[ ]` C2 |
| audit M5 — `noise_reduction` ↔ `pop_click_remover` duplication open (~0.79) | Medium | Duplication | 2 | `[ ]` E2 |
| audit M6 — two parallel batch engines; duplicated progress + standalone launcher | Medium | Duplication | 3 | `[ ]` G1 |
| audit M7 — parallel mode reports never-run standalone tools as "completed" | Medium | Correctness (report) | 1 | `[ ]` C3 |
| audit M8 — a not-found module displays as "completed" | Medium | Correctness (report) | 1 | `[ ]` C3 |
| audit M9 — 123 class-scoped instance-method fixtures across 30 files; unclosed test SQLite connections | Medium | Test hygiene | 3 | `[ ]` F2 |
| audit M10 — six GUI `app.py` modules below 60%; two of them carry H3 | Medium | Test depth | 4 | `[ ]` I5 |
| audit M11 — three manifest ids absent from `DEPENDENCY_GRAPH` | Medium | Registry contract | 1 | `[ ]` C4 |
| audit M12 — refinery select-all omits `reduce_noise`; display flags read the util tab's vars | Medium | Correctness (UI) | 1 | `[ ]` C5 |
| audit M13 — `build_refinery_args` silently re-enables all stages when none are selected | Medium | Dead code / contract | 1 | `[ ]` C5 |
| audit M14 — fingerprinter's loose status strings + duplicated tag-write block | Medium | Maintainability | 2 | `[ ]` E3 |
| audit M15 — dead code shipped in production paths (7 classes) | Medium | Dead code | 2 | `[ ]` E4 |
| audit M16 — `utilities/`: stale `_sha256` docstring, exception mismatch, FLAC/MP4 misroute, `--db` shadowing, silent pass | Medium | Correctness | 1 | `[ ]` C6 |
| audit M17 — key regeneration silently orphans encrypted config values | Medium | Data integrity | 1 | `[ ]` C7 |
| audit M18 — 13 foundation loggers never reach the log file under GUI launch | Medium | Observability | 1 | `[ ]` C8 |
| audit M19 — `show_message` is a 107-line god function with a one-line docstring | Medium | Maintainability | 2 | `[ ]` E4 |
| audit M20 — `--end` write-only in two tools; two incompatible GUI-arg parse patterns | Medium | Contract / consistency | 1 | `[ ]` C9 |
| audit M21 — `audio_refinery` pipeline docs omit the noise-reduction stage; substring-matched branch message | Medium | Docs / correctness | 1 | `[ ]` C10 |
| audit M22 — remaining duplication classes (card shell ×20, batch skeleton ×4, arg builders ×5, key_manager, asx, converter) | Medium | Duplication | 2 | `[ ]` I1, I2 |
| audit M23 — lower-severity correctness/robustness items (12 sub-items) | Low | Robustness | 4 | `[ ]` I3 |
| audit M24 — readability items (stale comments, naming drift, style, docstring errors) | Low | Readability | 4 | `[ ]` I4 |

Sprint totals: Sprint 0 = 4 · Sprint 1 = 8 · Sprint 2 = 5 · Sprint 3 = 3 ·
Sprint 4 = 5 → **25 items**.

---

## Sprint 0 — Correctness defects (release-blocking)

**Why first:** `AGENTS.md` ranks data-correctness defects highest — "any defect
that could corrupt, mis-normalize, mis-tag, or incorrectly convert data is the
highest-priority fix class." All four audit Highs are in that class, and all
four are in code the green suite cannot see.

```
Sprint 0   A1 A2 A3 A4     correctness       -> independent; A1 and A2 are
   |                                           single-file+test changes and
   |                                           may be done in any order
   |
   v
Sprint 1   C1..C10         contract + data   -> no dependency on Sprint 0
```

---

### A1 `[x]` — Make `--dry` actually withhold tag writes `[audit H1]`

**Priority:** P0 | **Effort:** 0.4 day | **Risk:** Low

**Problem.** `tag_field_updater/cli.py:22` accepts `dry_run: bool` and never
uses it as a write gate:

- `:35` calls `processor.scan_directory(directory)`. The signature
  (`tag_field_updater/core/processor.py:130-134`) accepts only `directory` and
  `progress_callback` — **no** dry-run parameter exists.
- `:48-49` sets `processor.stop_flag = True` **after** the scan has completed.
  `stop_flag` is read only *inside* the scan (`:157`, `:161`) and is reset to
  `False` at the top of every call (`:151`) — the assignment is dead code.
- The write site is unconditional: `tag_field_updater/core/transformation_rules.py:117-119`
  does `record_tag_edit_snapshot(...)` then `audio.save()` inside
  `if tags_updated:`. Seven transformation paths reach `.save()`
  (`:184, 243, 302, 361, 449, 543, 608`); none of them consult a mode flag.
- The violated contract is documented in the suite:
  `audio_suite_shared/cli_app.py` states *"`--dry` analyses and reports without
  writing."*
- The command reports `"dry_run": true` in its own JSON payload (`:41`) while
  having written.

**Audit reproduction** (real MP3, real CLI, exit 0): `TCON` `'Rock/Pop'` →
`'Rock; Pop'` on disk, one undo snapshot recorded, stdout
`Files updated: 1`.

**Compounding defect.** `cli.py:27` documents `audiosuite tag-update /Music
--dry-run`. Click registers only `--dry`/`--live`; the documented form exits 2
with `Error: No such option '--dry-run'. Did you mean '--dry'?`.

**Why the A1 gate missed both.** `TestDocumentedFlagParity`
(`audio_suite_shared/tests/test_cli_app.py:701-734`) extracts bracketed
`[--flag]` tokens (`:712`) and **skips any block containing none** (`:713-714`).
This command's docstring carries only a plain-text `Examples:` block, so the
entire command is invisible to the parity gate. `tag_field_updater/cli.py` sits
at **48% coverage** — 2nd-lowest CLI in the suite — so nothing else exercised
the path either.

**Scope:**

- [x] Add `dry_run: bool = False` to `TagProcessor.scan_directory`
      (`processor.py:130`) and to the per-file path it delegates to. Read
      `metadata_scrubber`'s dry-run threading for the established pattern —
      do **not** invent a variant.
- [x] Thread it into `tag_field_updater/core/transformation_rules.py` and gate
      **both** effects at `:117-119`: skip `record_tag_edit_snapshot(...)`
      **and** skip `audio.save()`. Gating only `.save()` would still record an
      undo row for a change that never happened.
- [x] Still compute and report: a dry run must return the same
      `ProcessingResult.updated` counts so the user sees what *would* change.
      Follow the `audio_enhancer` dry-run precedent for the result semantics.
- [x] `cli.py:35` — pass the flag through. Delete the dead `:48-49`
      `stop_flag` assignment (it cannot affect the run) and replace it with the
      real gate.
- [x] `cli.py:27` — correct the help example to `--dry`. Also update the
      `Examples:` block wording so the parity test has tokens to match.
- [x] Confirm every other transformation rule path (`:184, 243, 302, 361, 449,
      543, 608`) is reached only through the gated entry point; add the missing
      gate to any that is not.

**Tests (lockstep):**

- [x] `audio_suite_shared/tests/test_cli_app.py` — extend
      `TestDocumentedFlagParity` to also parse flag tokens out of each
      command's **`Examples:` lines** (currently only the bracketed `[--flag]`
      syntax is read). Add the same `skip`-vs-`assert` non-vacuity guard so the
      widened extraction cannot pass by matching nothing.
- [x] `tag_field_updater/tests/test_cli.py` — **real-file outcome test** (the
      `AGENTS.md` mode-flag rule): build a small MP3 with a `TCON` of
      `'Rock/Pop'`, run the CLI via `CliRunner` with `dry_run=True`, then assert
      **positive contracts**: the reported `updated` count is 1, the re-read
      tag value is unchanged, the file's SHA-256 and mtime are unchanged, and
      the undo log gained **no** row for that file.
- [x] `tag_field_updater/tests/test_transformation_rules.py` (new, one test
      file per source module per `AGENTS.md`) — a direct
      `dry_run=True` call on each of the seven rules asserting the same
      no-write contract, so a future eighth rule cannot skip the gate.
- [x] CLI smoke: `audiosuite tag-update <dir> --dry` exits 0 and the JSON's
      `dry_run` is `true`; `audiosuite tag-update <dir> --live` writes.

**Acceptance:**

- The audit's exact repro now prints `WROTE IN DRY RUN: False`, with the
  re-read tag value identical to the original.
- `--dry-run` (the previously-documented spelling) either resolves or is no
  longer documented; the parity test fails if either drifts again.
- Bare full-suite `pytest` green; `tag_field_updater/cli.py` coverage **above**
  75%; suite coverage ≥ 75.

**Negative controls:** reverting the `transformation_rules.py` gate must fail
the per-rule no-write test; reverting the `cli.py:35` threading must fail the
CLI outcome test; reverting the `cli.py:27` help fix must fail
`TestDocumentedFlagParity`. All three restores SHA-256-verified.

**Risks:** `updated_files` semantics may be asserted elsewhere as "files on
disk changed" — grep `stats.updated_files` consumers and adjust the *docstring*,
never the count, if a caller depended on the old meaning.

---

### A2 `[x]` — One `CueFileSpec` per track in `_write_rip_cue` `[audit H2]`

**Priority:** P0 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** `cd_ripper/core/ripper.py:403-418`. The ripper writes **one output
file per track**, then groups the paths by directory and builds the sheet:

```python
specs: list[TrackSpec] = []
for num, _path in entries:
    track = track_by_number.get(str(num), {})
    title = track.get("title", "") or f"Track {num:02d}"
    artist = track.get("artist", "") or ""
    specs.append(TrackSpec(number=num, title=title, performer=artist))
cue_text = build_cue(
    ...,
    files=(CueFileSpec(filename=os.path.basename(_path), tracks=tuple(specs)),),
)
```

Three compounding errors:

1. **`_path` is read after the loop.** The underscore prefix marks it "unused"
   (`R10`) — that convention is what hid this. At `:414` it holds the **last**
   entry's path.
2. **All tracks go inside one `FILE` block** (`:412-417`). For a
   track-per-file rip the sheet needs one `CueFileSpec` per entry.
3. **`TrackSpec.start_ms` defaults to `0`**
   (`audio_suite_shared/cue_generator.py:58`) and the ripper never sets it, so
   every track renders `INDEX 01 00:00:00`.

Net: an N-track rip yields **one** `FILE` line naming the last track's file,
containing all N tracks at offset zero. Any cue-aware player mis-resolves the
album. The docstring at `ripper.py:374-379` claims the opposite — *"the
generated sheet always matches the audio on disk"* — so the code documents a
guarantee it breaks.

**Why the suite is green.** `cd_ripper/tests/test_ripper_core.py:1187-1188`
asserts only `"FILE " in text` and `count("INDEX 01") == 2`. It never pins the
per-file structure or the filenames, so 1 `FILE` + 2 `INDEX` passes. This is the
`AGENTS.md` "assert the positive contract" rule inverted: the test asserts a
*substring* where the artifact requires a *structure*.

**Scope:**

- [x] Rewrite the `:403-418` block to build `files=tuple(CueFileSpec(...))`
      with **one entry per iteration**, capturing `path` **inside** the loop and
      renaming `_path` → `path` (the underscore asserted a lie).
- [x] Set each `TrackSpec`'s `start_ms` explicitly to `0` at construction
      (rather than relying on the `cue_generator.py:58` default) so the intent
      is visible at the call site and a future non-zero layout has an obvious
      place to live.
- [x] Confirm `build_cue`'s `files` parameter accepts multiple `CueFileSpec`
      entries and emits one `FILE` block each — read its signature first; if it
      does not, that is a defect found while implementing and is fixed **in this
      same change** with a test on `cue_generator`.
- [x] Check the `cd_ripper` user guide for a claim about single-image sheets;
      correct the generator (`user_guides/individual_programs/cd_ripper/generate_guide.py`)
      and regenerate the `.docx` if it repeats the wrong structure.

**Tests (lockstep):**

- [x] Rewrite `test_ripper_core.py`'s cue assertion to pin **structure**, not a
      substring: for a 3-track rip assert `text.count("FILE ") == 3`, that every
      `FILE` value names a file that **exists on disk** in the output
      directory, and that the `INDEX` count equals the track count.
- [x] Add a case asserting the `FILE` filenames are the **distinct** per-track
      paths (a 2-track rip whose names collide fails), plus a single-track case
      (the degenerate N=1 form still emits exactly one `FILE`).
- [x] `audio_suite_shared/tests/test_cue_generator.py` — if the multi-file
      emission path was previously untested, add the round-trip that resolves a
      2-file sheet back to two distinct images.

**Acceptance:**

- A 3-track rip produces a `.cue` with three `FILE` blocks, each naming a file
  that exists, each with exactly one `INDEX 01 00:00:00`.
- The suite's own `cue_split.py` / `cue_cli.py` resolves the sheet to the three
  correct on-disk images (this is the consumer the defect actually breaks).
- Bare full-suite `pytest` green; coverage ≥ 75.

**Negative controls:** restoring the single-`CueFileSpec` form must fail the
`FILE`-count test and the on-disk-name test; reverting the in-loop `path`
capture must fail the distinct-names test. SHA-256-verified on restore.

**Risks:** `build_cue`'s multi-file support is unverified — **read the
signature before editing**. If it only emits one `FILE`, the fix grows to
`cue_generator.py`, which is inside this item's stated scope and its own test
file.

---

### A3 `[x]` — Marshal worker-thread Tk in two apps; delete the false claim `[audit H3]`

**Priority:** P0 | **Effort:** 0.5 day | **Risk:** Medium

**Problem.** The suite's `file_processor_base` contract states progress/complete
callbacks fire on worker threads and **must** be marshalled to the Tk main
thread. Most tools do. Two do not — invisibly to the suite, because Tk is mocked.

**`album_genre_tagger/app.py`** — `:256` starts
`threading.Thread(target=self._run, daemon=True)`. Inside `_run`, from the
worker: `self.progress["value"] = 0` (`:267`),
`self.file_listbox.insert(...)` (`:268`), Tk var reads `self.folder_path.get()`
(`:262`) and `self.run_mode.get()` (`:263`). The section header at `:282` reads
*"Callbacks (called from background thread)"* — yet `_on_phase1_progress`
(`:284-300`) mutates `self.progress`, `self.stats_label`, and the listbox with
no `root.after` anywhere in the class. Same for `_on_coverage_fail`,
`_on_phase2_progress`, `_on_complete` (which reads `self.run_mode.get()` at
`:352`) and `_on_error`, which calls `messagebox.showerror` **directly** from
the worker.

**`album_art_sync/app.py`** — `:311` `threading.Thread(target=self._run_logic,
daemon=False)` (every other app uses `daemon=True`; here a window closed
mid-run leaves the process alive while the worker blocks on the art picker).
Worker-thread Tk calls include `_add_log` (`:315-320`: `log_list.insert`, `see`,
`update_idletasks`), `status_txt.set`, `progress.config`, `res_msg.config`,
`notebook.select`, `start_btn.config`, and Tk var reads (`:337, 442-443`).

The section header at `:313` reads:

```
# -- Logging (thread-safe via update_idletasks) --
```

**`update_idletasks()` does not make cross-thread Tk access safe.** The claim is
false, and worse than an omission would be — it tells the next reader the
hazard was considered.

**The same file already contains the correct pattern:** `_on_pick` (`:324-329`)
documents and uses `PickerDialog.show_threadsafe()`, which schedules onto the
main thread and blocks the worker until the user responds. The correct seam is
three functions away.

**Honest scoping of practical severity:** CPython's `_tkinter` serialises most
Tcl calls, so these typically manifest as interleaving and re-entrancy rather
than an immediate crash. But Tkinter is officially not thread-safe, the
modal-from-worker case can deadlock against the main loop, and this is the class
of bug that is trivial to fix now and expensive to diagnose from a user's crash
report later.

**Scope:**

- [x] **`album_genre_tagger/app.py`** — wrap every worker-side Tk mutation in
      `_run` and in all six callbacks (`_on_phase1_progress`,
      `_on_coverage_fail`, `_on_phase2_progress`, `_on_complete`, `_on_error`)
      in `self.root.after(0, ...)`, scheduling a small main-thread helper rather
      than executing inline. Per `AGENTS.md` §6 item 7, define explicitly-typed
      handler functions — do **not** use bind-style lambdas that return values.
    - Move the two Tk var **reads** (`folder_path`, `run_mode`, `:262-263`)
      into the pre-thread snapshot so no `.get()` runs off the main thread
      (this is the same defect class as audit H4/A4; keep the two fixes
      separate but consistent).
    - Replace the direct `messagebox.showerror` in `_on_error` with a scheduled
      call.
    - Add the thread-safety docstring section the sibling tools already carry,
      stating that the callbacks are invoked on a worker thread.
- [x] **`album_art_sync/app.py`** — same treatment for `_add_log`, `status_txt`,
      `progress`, `res_msg`, `notebook`, `start_btn`, and the Tk var reads.
    - **Delete the false `update_idletasks` safety claim** at `:313` and replace
      it with the accurate statement (these calls are marshalled onto the main
      thread; `update_idletasks` is retained only to force a repaint).
    - `:311` `daemon=False` → `daemon=True`, matching every other app.
    - Keep `_on_pick`'s existing `show_threadsafe()` bridge as-is — it is the
      model for the rest.

**Tests (lockstep):**

- [x] Per `AGENTS.md` §6 item 8, define locally-typed helpers — a lambda
      returning `self.root.after(...)`'s `str` after-id fails `mypy --strict`
      with `arg-type` against a `Callable[..., None]` parameter.
- [x] `album_genre_tagger/tests/test_app.py` and
      `album_art_sync/tests/test_app.py` — regression tests asserting the
      **positive** contract: after driving the worker path with a stubbed
      processor, the main-thread scheduling happened. Inspect
      `mock.root.after.call_args_list` with **`.args[0] == 0`** — per
      `AGENTS.md`, `_Call` positional inspection requires `.args`
      explicitly; `call_[0]` returns the whole args tuple and silently defeats
      the check.
- [x] Add a real-widget test on a **per-test withdrawn `Toplevel`** off the
      session-scoped shared root (never assign test doubles onto the shared
      `root` by bare attribute — see the `AGENTS.md` §7 rule that hung a full
      suite once).
- [x] Assert `_add_log` performs its listbox update when invoked **on the main
      thread** (the marshalled helper is directly callable), so the helper is
      covered without a thread.

**Acceptance:**

- No `.after`-free Tk mutation remains on any worker path — verify by
  grepping both `app.py` files for `root.after` in each callback and by
  inspection.
- The `update_idletasks` safety claim is gone; the comment states what is
  actually true.
- `daemon=True` in both.
- Bare full-suite `pytest` green; `album_genre_tagger/app.py` and
  `album_art_sync/app.py` coverage both **above** their current 45% / 53%
  (this also feeds I5).

**Negative controls:** removing the `root.after` wrapper from
`_on_phase1_progress` must fail the scheduling test; restoring `daemon=False`
must fail the daemon assertion. SHA-256-verified.

**Risks:** these are the two largest GUI modules with mocked tests; a wrong
refactor can hang the suite. Prove with a real-widget `Toplevel` test, and run
the **bare full suite** before marking complete (a package-scoped run is not
sufficient — this is the failure mode that previously hung CI).

---

### A4 `[x]` — Build the driver argv on the main thread `[audit H4]`

**Priority:** P0 | **Effort:** 0.4 day | **Risk:** Medium

**Problem.** `master_driver/tool_launcher.py:95-97` states the intent:

```python
# Snapshot tkinter variables on main thread before spawning daemon thread
snapshot_clear_logs = state.clear_logs_var.get()
snapshot_source = state.refinery_source.get().strip()
```

Only **two** variables are snapshotted. The thread target `_run_refinery`
(`:117-126`) calls `arg_builder.build_refinery_args(state, config)` **on the
daemon thread** (`:126`), and the builder reads live widget state directly —
`state.dir_path`, `state.global_mode`, `state.module_toggles[...]`, and every
per-tool control (`arg_builder.py:52-55, 60, 191-194, 374-375`). The same
pattern repeats for the enrich (`:222`) and utility (`:342`) launchers, and
`module_runner.py:104` calls `.get()` on the worker too.

The snapshot feeds **only** the log-clear path. The emitted argv — including the
`--live`/`--dry` token — is re-derived from live variables after the thread
starts, so an edit made while a batch is launching can flip the mode of the run
in flight. This is the `AGENTS.md`-ranked-highest class: *"a mode the app
computes and passes … silently does nothing"* and its mirror, *a mode that can
be changed after it was computed*.

**Why the suite is green.** Existing tests call `build_*_args` directly with a
stub state. Nothing exercises the **thread boundary**, because nothing asserts
the boundary exists.

**Scope:**

- [x] In each of the three launchers (`refinery`, enrich, utility), build the
      full argv **on the main thread**, before `threading.Thread(...)` starts,
      and pass the finished list into the thread target. Read
      `master_driver/runner/arg_builder.py`'s `build_refinery_args` /
      `build_enrich_args` / `build_utility_args` signatures first — they
      currently take `(state, config)` and return a token list; call them on the
      main thread and thread the **result list** through instead.
- [x] The existing `snapshot_clear_logs` / `snapshot_source` parameters are
      then redundant with the argv; keep them (they feed logging/persistence,
      which the audit notes is their real job) but stop treating them as the
      snapshot mechanism.
- [x] Apply the same treatment to `module_runner.py:104` — read
      `toggle.get()` on the main thread before the pool work begins.
- [x] Per `AGENTS.md` §6 item 8, keep the thread target's `on_complete` /
      `on_error` parameters correctly typed with locally-typed helpers, not
      lambdas that return `root.after`'s `str`.
- [x] **Do not change the argv the builder produces.** A1's
      `TestBuildEnrichArgs` golden shape (`[path, mode, start, end]`) and the
      enrich/compatibility tests must pass **unedited**.

**Tests (lockstep):**

- [x] `master_driver/tests/test_runner.py` — for each of the three builders, a
      test that (a) builds the argv on the "main thread", (b) then **mutates a
      state variable** between build and thread start, and (c) asserts the argv
      the thread received is **unchanged**. Positive contract: "the argv
      emitted from the snapshot equals the argv built before the thread
      started."
- [x] Retain and keep green, unedited, the existing `TestBuildEnrichArgs`
      `[path, mode, start, end]` assertion and any per-builder golden vectors —
      this item must not alter the arg builders' output.
- [x] A test that the thread receives the **list object** (not the state), so a
      later refactor cannot reintroduce live reads by passing `state` through.

**Acceptance:**

- No `.get()` call executes on a worker thread in the three launcher paths.
- The mutate-after-snapshot test passes; reverting to on-thread building fails
  it.
- Bare full-suite `pytest` green; coverage ≥ 75.

**Negative controls:** move the `build_*_args` call back inside the thread
target and the mutate test must fail. SHA-256-verified.

**Risks:** the launchers' signature changes ripple into `tool_launcher` callers.
Keep the public launcher function names/signatures stable (they are called from
`app.py`) and change only the internal thread-target plumbing.

---

## Sprint 1 — Contract, registry and data-integrity closure

**Why here:** these are Medium items, but each is a case where **a stated
contract and the code disagree** — which no compile or type gate can detect, and
which the audit found by reading. Several are one-line fixes with a lock.

```
Sprint 1   C1..C10   contract + data integrity   -> independent; no dependency
                                                     on Sprint 0
```

---

### C1 `[x]` — One extension set; make or delete the symlink branch `[audit M2, M3]`

**Priority:** P1 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** Two findings in one file,
`audio_suite_shared/security/input_validator.py`.

**M2 — dead symlink branch.** `:167` computes `resolved = declared.resolve()`;
`:175` tests `resolved != declared.resolve(strict=False)`. `Path.resolve()`
defaults to `strict=False`, so **both sides are the identical computation** — the
condition is always `False` and the `logger.warning` at `:185-189` is
unreachable. The docstring at `:149-155` documents behaviour that cannot run:
*"detects symlinks that resolve to locations outside the user's home directory …
permitted with a logged warning."* A documented security control that silently
never runs is worse than an absent one, because a reader trusts it.

**M3 — extension drift.** `:270-279` hardcodes
`{.mp3, .flac, .wav, .ogg, .m4a, .aiff, .aif, .wma}`. The suite's declared set is
`audio_suite_shared/audio_formats.py:15-25` `SUPPORTED_EXTENSIONS`
= `(.mp3, .flac, .ogg, .m4a, .mp4, .opus, .wav, .aiff, .aif)`. The validator
**rejects `.mp4` and `.opus`** (formats the suite supports and converts) and
**accepts `.wma`** (which it does not support). `validate_audio_file_path` is the
gate the subprocess launchers consult.

**Scope:**

- [x] M3: replace the hardcoded set with an import of
      `audio_suite_shared.audio_formats.SUPPORTED_EXTENSIONS`. Read that module
      first to get the exact name and any separate read-only vs. writable
      distinction — do not assume the two sets are semantically identical.
- [x] M2: resolve the intent. **Recommendation:** make the branch real by
      comparing the *unresolved* path against the resolved one, so a symlink is
      actually detected:
      `resolved != Path(dir_path)` (or `declared.absolute()`), which is a
      genuine difference when a symlink is traversed. Keep the existing
      warn-but-allow policy and its safe-roots check. If a maintainer prefers to
      drop the control instead, that is a **decision J** — but the docstring
      paragraph must then be deleted in the same change.
- [x] Grep for other `input_validator` docstrings/claims that assert behaviour
      the code does not implement (the M2 class) and correct them in this change.

**Tests (lockstep):**

- [x] `audio_suite_shared/tests/test_input_validator.py` — a test asserting the
      validator's accepted extension set **equals** `SUPPORTED_EXTENSIONS`, so
      the next format addition cannot drift. Include the `.mp4`/`.opus` accept
      and `.wma` reject cases explicitly (positive and negative).
- [x] A symlink test: create a real symlink to a temp dir (skip on Windows
      without privileges via `pytest.mark.skipif`, per the platform-gate
      precedent) and assert the validator now **logs the warning and returns
      True** for an out-of-safe-root target — i.e. the branch is reachable.
- [x] Non-vacuity: assert the warning logger was called (positive), not that
      "no error was raised" (negative).

**Acceptance:** the extension-set equality test passes; the symlink test
proves the branch is reachable; bare full suite green.

**Negative controls:** re-introduce the identical-`resolve()` comparison and the
symlink test must fail; re-add `.wma` to the set and the equality test must
fail. SHA-256-verified.

---

### C2 `[x]` — Write the `[Unreleased]` changelog `[audit M4]`

**Priority:** P1 | **Effort:** 0.2 day | **Risk:** None

**Problem.** `CHANGELOG.md` declares Keep-a-Changelog + SemVer compliance, yet
`[Unreleased]` (line 10) is empty while the tree has gained, since the last
release: always-on TPDF dither + `soxr` resampling with a `--no-dither` opt-out
(E1), MusicBrainz identifier writing (E2), Cover Art Archive as first art source
(E3), recursive mixed-format conversion (E4), the tag-helper split (C2), the
`process_file` decomposition (C3), and the duplication class (B1–B5). Every one
changes user-visible behaviour — and E1's dither alters **every converted
file's bytes**.

**Scope:**

- [x] Write `[Unreleased]` entries grouped Keep-a-Changelog style (`### Added`,
      `### Changed`, `### Fixed`) for the items above. Read
      `PLAN_iteration7_remediation.md`'s Completion Log for the exact
      user-visible wording of each so the changelog matches shipped behaviour.
- [x] E1 gets a `### Changed` note with migration advice (re-run undo-aware
      workflows; output bytes changed) and the `--no-dither` escape hatch named.
- [x] Add this item's **own** Sprint-0 findings (A1–A4) as `### Fixed` entries,
      since they are user-visible correctness fixes landing in the same window.
- [x] Do **not** invent version numbers or dates; `[Unreleased]` is the target.

**Tests (lockstep):**

- [x] `audio_suite_shared/tests/test_user_guide_hygiene.py` (the existing
      changelog/docs hygiene home) — a test that `[Unreleased]` is either
      non-empty **or** explicitly marked as a placeholder, with a non-vacuity
      guard so it cannot pass by matching nothing.

**Acceptance:** `[Unreleased]` is populated per shipped behaviour; the hygiene
test passes; bare full suite green.

---

### C3 `[x]` — Report skipped and not-found steps honestly `[audit M7, M8]`

**Priority:** P1 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** Two ways the Master Driver reports a run that did not happen as a
run that did.

**M7 — never-run tools reported "completed".**
`master_driver/batch_orchestrator.py:298-307`: the comment says *"Mark
audio_refinery as standalone; skip parallel execution"*, but the code skips
**every** `manifest.standalone` step, sets `s.status = StepStatus.SKIPPED`, then
**adds it to `completed` and increments `completed_count`** (`:305-306`). A tool
that never ran is reported complete. `skipped_count` (`:299, 307`) is
incremented and never read. Sequential mode behaves differently — it launches
standalone tools and waits (`_launch_standalone`) — so the two modes disagree on
what a batch does.

**M8 — a not-found module displays as "completed".**
`master_driver/runner/module_runner.py:213-221`: the not-found branch calls
`on_error(...)` and `continue`s **without** appending to `failed_steps` and
**without** emitting the post-step status line. The index-based status mapping at
`:358-368` (`elif i < completed_steps: "completed"`) then mislabels it: specs
`[A not-found, B ok]` renders A as **completed** once B finishes.

**Scope:**

- [x] M7: do **not** add skipped standalone steps to `completed` /
      `completed_count`. Keep `skipped_count` meaningful — surface it in the
      batch summary and/or the status line. Read `_collect_deps` and the summary
      formatting before editing so the two modes' reports read consistently;
      decide (and record in the Completion Log) whether parallel mode should
      **also** run standalone tools the way sequential does, or genuinely skip
      them and say so. **Recommendation:** skip and report as "skipped" — the
      current comment says skip, so honour it and make the report truthful.
- [x] M8: append the not-found tool to `failed_steps` (read the exact structure
      at `:213-221`) and emit its status line, so the index-based mapping at
      `:358-368` cannot label it "completed".
- [x] Both fixes must not change the *execution* of found, non-standalone steps.

**Tests (lockstep):**

- [x] `master_driver/tests/test_batch_orchestrator.py` — a parallel-mode test
      with a `standalone` step asserting the **positive** contract: the step's
      reported status is `SKIPPED` and the completed summary does **not** count
      it as completed (assert the completed list excludes it — a positive
      statement about the list, not "nothing happened").
- [x] `master_driver/tests/test_module_runner.py` — a not-found-module test
      asserting it lands in `failed_steps` and its status line reads
      "failed"/"not found", **not** "completed".

**Acceptance:** both mislabels reproduce pre-fix and are gone post-fix; the two
modes' summaries agree on skipped-vs-completed semantics; bare full suite green.

**Negative controls:** restoring `completed.add(...)` must fail the M7 test;
removing the `failed_steps` append must fail the M8 test. SHA-256-verified.

---

### C4 `[x]` — Registry completeness test for `DEPENDENCY_GRAPH` `[audit M11]`

**Priority:** P1 | **Effort:** 0.2 day | **Risk:** Low

**Problem.** `audio_suite_shared/tool_plugin.py:155-158` designates
`batch_orchestrator.DEPENDENCY_GRAPH` as an agreement point every tool id must
appear in. `master_driver/batch_orchestrator.py:123-147` lists 23 ids, missing
**`mood_analyzer`**, **`noise_reduction`**, and **`tag_field_updater`**. They
still run (`_collect_deps` defaults to `[]`), so this is contract-completeness
rather than a live failure — but the graph is what keeps enrich→utility ordering
correct as tools are added.

**Scope:**

- [x] Add the three missing ids with their correct dependencies (read each
      tool's actual pipeline: `noise_reduction` is a utility with no deps;
      `mood_analyzer`/`tag_field_updater` likewise unless a real dep exists).
- [x] Add a registry test (in `master_driver/tests/`) asserting
      `set(manifest ids) ⊆ set(DEPENDENCY_GRAPH keys ∪ EXCLUDED)`, with an
      explicit, named `EXCLUDED` allowlist so a deliberate exclusion is visible.
      This is the same "agreement point" pattern `tool_plugin.py` already
      documents.

**Tests (lockstep):** the test above **is** the lockstep test. Include a
non-vacuity assertion (`len(DEPENDENCY_GRAPH) >= len(manifest ids) - len(EXCLUDED)`)
so an empty graph cannot pass.

**Acceptance:** the three ids are present with correct deps; the test fails if
a future tool is added without a graph entry; bare full suite green.

---

### C5 `[x]` — Refinery select-all, display flags, and the silent stage fallback `[audit M12, M13]`

**Priority:** P1 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** Three linked defects in the refinery driver path.

**M12a — select-all omits a stage.** `master_driver/app.py:362-366`
`_toggle_all` iterates `["declick","trim","enhance","normalise"]`, while
`arg_builder.py:377-383` and `audio_refinery/ui/setup_tab.py:267` include
**`reduce_noise`**. Select-All on the REFINE tab never enables Noise Reduction.

**M12b — display flags read the wrong tab's variables.**
`arg_builder.py:445` emits `_driver_display_flags(state.util_clear_logs_var,
state.parallel_var)`, but the refine tab binds `state.clear_logs_var`
(`app.py:354`) and `launch_refinery` snapshots `state.clear_logs_var`
(`tool_launcher.py:96`). The child's inert Run Controls panel displays the
**utility** tab's Clear Logs state.

**M13 — silent re-enable.** `arg_builder.py:384-386`:
`if not active_stages: active_stages = "declick,trim,enhance,normalise"`. A user
who turns off all stages gets the full default chain. Currently unreachable via
`launch_refinery` (which blocks no-stages first at `tool_launcher.py:76-93`), so
it is dead code *and* a surprising contract — if the guard is ever relaxed, the
surprise ships.

**Scope:**

- [x] M12a: derive `_toggle_all`'s stage list from the **same source** the arg
      builder uses (`arg_builder.stage_map` at `:377-383`) rather than a
      duplicated literal — single source of truth, so the next stage cannot drift.
- [x] M12b: change `arg_builder.py:445` to read `state.clear_logs_var` (the
      refine tab's binding), not `util_clear_logs_var`.
- [x] M13: replace the silent fallback with an explicit contract. **Since
      `launch_refinery` already blocks no-stages, delete the dead fallback** and
      raise/return an empty stage list — do not silently re-enable. If a
      maintainer wants the fallback, that is a decision; the audit's
      recommendation is deletion.
- [x] Also note (audit M12): the refine tab hides the parallel checkbox
      (`app.py:387-391`) while `--parallel-run/--no-parallel-run` is still
      emitted — decide whether to emit or hide, and make them agree. Fold into
      this item.

**Tests (lockstep):**

- [x] `master_driver/tests/test_runner.py` — the emitted `--stages` string for a
      refinery run with all toggles off is **empty/absent** (positive: the
      fallback no longer rewrites it), and select-all sets **all five** stage
      vars including `reduce_noise`.
- [x] A test asserting the refine tab's `--clear-logs` flag tracks
      `clear_logs_var`, not `util_clear_logs_var` (set them differently and
      assert the flag follows the refine var).

**Acceptance:** the three misbehaviours reproduce pre-fix and are gone; bare
full suite green; existing `TestBuildEnrichArgs` shape assertions pass unedited.

---

### C6 `[x]` — Fix the `utilities/` defects `[audit M16]`

**Priority:** P1 | **Effort:** 0.4 day | **Risk:** Low

**Problem.** `utilities/` is outside **both** `ruff`'s default globs and
`mypy`'s `exclude`, and `utilities/tests/` covers only 2 of the 7 scripts — so
defects here are invisible to every gate. The audit found five.

- `utilities/rebuild_refinery_log.py:18-20` — the docstring claims the script
  *"imports `_sha256` directly from the real registry module (falling back to an
  equivalent local implementation … with a loud warning)"*. There is no such
  import; `_sha256` is purely local (`:84-95`). For a **hash-compatibility**
  tool, the docstring is the trusted spec.
- `rebuild_refinery_log.py:163` raises `AudioFileNotFoundError` (→
  `AudioIOError` → `AudioSuiteError` → `Exception`) while the caller catches
  `except FileNotFoundError` (`:256`). The handler can never match — the user
  gets a raw traceback instead of `[ERROR]`. **Verified.**
- `utilities/resize_music_recursive.py:172` — `if isinstance(audio, MP3) or
  hasattr(audio.tags, "add")`. mutagen's `VorbisComment` (FLAC) and `MP4Tags`
  both implement `.add`, so this first branch captures FLAC and MP4; the
  `elif isinstance(audio, FLAC)` branch that handles `audio.pictures` (`:207`)
  and the `elif isinstance(audio, MP4)` branch handling `covr` (`:234`) are
  **unreachable**. FLAC/MP4 embedded art is silently never resized.
- `utilities/undo.py:163-169` — the per-subparser `--db` is shadowed by the
  top-level `--db` (`:144-148`) under argparse subparser-defaults semantics, so
  `undo --db X show ID` loses `X` while the help text implies it works.
- `utilities/strip_bom.py:96-100` — `_cleanup` swallows `OSError` with a bare
  `pass`.

**Scope:**

- [x] `rebuild_refinery_log.py`: correct the `:18-20` docstring to describe what
      the code actually does (a purely local `_sha256`). If importing the real
      registry `_sha256` is feasible and desired, that is a decision - the audit's
      recommendation is to **correct the docstring**, since the tool's contract is
      "reproduce the value the program stored", and the local copy is the
      reproduced one.
- [x] `rebuild_refinery_log.py`: make the exception hierarchy consistent - the
      caller must catch what the function raises. Either raise `FileNotFoundError`
      or catch `AudioSuiteError` at `:256`; **read the hierarchy in
      `exceptions.py`** and choose the option matching the suite's convention
      (record which). Recommended: catch `AudioSuiteError` so future
      `AudioIOError` variants are handled too.
- [x] `resize_music_recursive.py:172`: narrow the first branch to
      `isinstance(audio, MP3)` only, so the FLAC (`:207`) and MP4 (`:234`)
      branches become reachable. Verify the FLAC/MP4 art paths handle their
      real mutagen structures.
- [x] `undo.py`: resolve the `--db` shadowing. Per `AGENTS.md` (argparse
      subcommand flags are not inherited from the parent), register `--db` once
      per subparser and remove the shadowing parent, **or** have the subparser
      default pull the parent value explicitly. Choose the option that makes
      `undo --db X show ID` honour `X`.
- [x] `strip_bom.py:96-100`: log the swallowed `OSError` (`logger.warning(...,
      exc_info=True)`) or raise - the A3 no-silent-swallow standard.
- [x] **Extend `utilities/tests/`** to cover the fixed scripts (the 5 remaining
      of 7), at minimum the three behavioural bugs above. This is the only thing
      that keeps `utilities/` honest given it is outside the ruff/mypy gates.

**Tests (lockstep):** new `utilities/tests/test_rebuild_refinery_log.py`,
`test_resize_music_recursive.py`, `test_undo.py`. Key cases:
- resize: a **real** FLAC and MP4 with embedded art enters the correct branch
  (assert `audio.pictures` / `covr` is touched) — the outcome-correctness rule.
- `rebuild_refinery_log`: the exception the function raises is caught by the
  caller (assert no traceback escapes).
- `undo`: `undo --db <path> show <id>` uses the supplied db path.
- Per `AGENTS.md` §6 item 11: assert the CLI payload on **stdout** only.

**Acceptance:** each of the five reproduces pre-fix and is gone; the three new
test files pass; bare full suite green.

**Negative controls:** restore `hasattr(audio.tags, "add")` and the FLAC art
test must fail; restore the mismatched `except FileNotFoundError` and the
exception test must fail. SHA-256-verified.

---

### C7 `[x]` — Surface key-regeneration consequences; back up the old key `[audit M17]`

**Priority:** P1 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** `audio_suite_shared/security/key_manager.py:71-83`: a corrupt or
unreadable key file triggers `_generate_and_save_key` — a **new** key — and every
value encrypted under the old key becomes permanently undecryptable
(`decrypt_string` then raises at `:200-205`). Compounded at `:143-146`: on a
key-file *write* failure an ephemeral key is returned without being persisted, so
the next launch generates yet another. Neither consequence is surfaced beyond a
warning. The encrypted config silently becomes unreadable.

**Scope:**

- [x] Before overwriting an existing-but-unreadable key file, copy it to
      `<key_file>.bak` (one-time, alongside the existing `.key` gitignore
      pattern) and log a WARNING naming the consequence.
- [x] Surface the consequence: when a key is regenerated because an existing
      file was invalid, log that previously-encrypted values (e.g. the Fanart
      `app_key`/`client_key`) will need re-entry.
- [x] `:143-146` - on write failure, do not silently return an ephemeral key;
      log an ERROR stating the key will not survive restart. Read the caller's
      expectations first (it returns bytes), so keep the signature and only
      change the logging severity/message.
- [x] The `.bak` must be added to `.gitignore` (keys are secret-class; never
      `git add -f`). Confirm the existing `*.key` ignore rule and extend it to
      `*.key.bak`.

**Tests (lockstep):** `audio_suite_shared/tests/test_key_manager.py` — corrupt
an existing key file, assert (a) a `.bak` of the original was written, (b) a
WARNING mentions re-entry, (c) `decrypt_string` on an old value raises with a
clear message rather than silently. Use temp paths (the `AGENTS.md` no-secrets
rule — never a real key).

**Acceptance:** the three assertions pass pre- and post-fix as specified;
`.gitignore` covers `*.key.bak`; bare full suite green.

---

### C8 `[x]` — Re-parent the 13 foundation loggers under `audio_suite.*` `[audit M18]`

**Priority:** P1 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** `app_bootstrap.configure_logging` attaches the
`RotatingFileHandler` to the **`audio_suite`** logger only
(`app_bootstrap.py:123-139`; note the misleading local name `root_logger` at
`:123`). Modules using `logging.getLogger(__name__)` produce
`audio_suite_shared.*` records — those propagate to the **root** logger, not the
sibling `audio_suite` branch. Under a GUI launch there is no root handler, and
under `pythonw` the `lastResort` stderr path is discarded, so WARNING+ records
go nowhere.

Affected (13): `batch_undo.py:73` · `file_processor_base.py:55` ·
`ui_common.py:36` · `resource_manager.py:22` · `secure_subprocess.py:19` ·
`error_recovery.py:17` · `lossless_gain.py:92` · `tool_app_base.py:39` ·
`suite_config.py:44` · `undo_gui.py:44` · `security/error_handler.py:23` ·
`security/input_validator.py:15` · `security/key_manager.py:18`.

The pitfall is **already documented in the codebase** — `exceptions.py:41-46`
explains exactly why a plain `getLogger(__name__)` "would hang off the root
logger and never reach `logs/audio_suite.log`" — and the modules that need it
still do it. Consequence: the subprocess **audit trail**
(`secure_subprocess.py:271-275`) and undo INFO records (`batch_undo.py:600-606`)
are not durably recorded in a normal GUI run.

**Scope:**

- [x] For each of the 13 modules, change
      `logging.getLogger(__name__)` → `logging.getLogger(f"audio_suite.{__name__}")`,
      matching the pattern already used in `exceptions.py:46`. One line each.
      *(Scope widened by maintainer approval to all 27 real call sites — see the
      Completion Log's deviation note.)*
- [x] Fix the misleading local name `root_logger` at `app_bootstrap.py:123` →
      `suite_logger` (it is not the root logger).
- [x] AST/grep-lock: add a test asserting every module in
      `audio_suite_shared` that calls `getLogger` uses the `audio_suite.` prefix
      (i.e. every module logger is a descendant of `audio_suite`). Non-vacuity:
      assert the check found ≥ 13 call sites.

**Tests (lockstep):**

- [x] `audio_suite_shared/tests/test_logging_namespacing.py` — the AST scan
      above, plus a live capture test: attach a handler to `audio_suite`, emit a
      WARNING from one of the converted modules (e.g. `secure_subprocess`), assert
      the record **arrives**. Positive contract.

**Acceptance:** the AST test passes with ≥ 13 conversions; the live capture test
proves a converted module's WARNING reaches an `audio_suite` handler; bare full
suite green.

**Negative controls:** revert one module to `getLogger(__name__)` and both the
AST test and the capture test must fail. SHA-256-verified.

---

### C9 `[x]` — Make `--end` functional (or explicitly ignored) in two tools `[audit M20]`

**Priority:** P1 | **Effort:** 0.3 day | **Risk:** Low

**Problem.** `noise_reduction/app.py:253-254` and `pop_click_remover/app.py:222-223`
set `self.auto_end_var` from the handshake and **never read it** — no `.get()`
anywhere, and no window `destroy` in either file. The Master's `--end` flag is
silently inert in exactly those two tools, while tempo, album_genre,
album_art_sync, asx and audio_enhancer all honour it.

**This is the `AGENTS.md` archetype:** a test asserting "nothing happens on
`--end`" would pass forever and lock the defect in. The fix must assert the
**positive** contract (the window closes, or an explicit "ignored" warning is
logged).

**Scope:**

- [x] Pick the behaviour per tool by reading how the six honouring tools
      implement auto-end (schedule a `root.after` destroy on success, or poll a
      flag in the completion callback). Implement the same for
      `noise_reduction` and `pop_click_remover`. **Recommendation:** honour it,
      for consistency with the other six.
- [x] If the maintainer prefers these two to remain interactive (decision J),
      then log an explicit "auto-end ignored by this tool" WARNING when
      `--end` is passed, so the flag is never *silently* inert. Either outcome
      removes the silence. *(Not the branch taken — decision J2 resolved to
      **honour** `--end`, so the close-on-completion path below was implemented
      instead of an ignored-WARNING.)*

**Tests (lockstep):**

- [x] `noise_reduction/tests/test_app.py` and
      `pop_click_remover/tests/test_app.py` — drive the completion path with
      `auto_end=True` and assert the **positive** outcome (a close/`destroy` is
      scheduled, or the explicit ignored-WARNING is logged — whichever the
      decision selected). Do **not** assert "the window did not close".

**Acceptance:** `--end` either closes the window or logs an explicit
acknowledgement in both tools; the positive test passes; bare full suite green.

---

### C10 `[x]` — Correct the `audio_refinery` pipeline docs and branch message `[audit M21]`

**Priority:** P1 | **Effort:** 0.2 day | **Risk:** Low

**Problem.** `audio_refinery/core/pipeline.py:5-11` documents "Decode once →
declick → trim → enhance → encode once → normalise" — the noise-reduction stage
runs **between trim and enhance** (`:196-204`). The step comments number "5"
twice (`:202`, `:206`) and drop the box style at 6.
`audio_refinery/ui/setup_tab.py:157`'s subtitle ("Declick → Trim → Enhance →
Normalise") has the same omission — and for a DSP chain the stage order is
exactly what a user reasons about. Also `_run_trim_stage` (`:363-370`) derives
its user-facing message by **substring-matching** `silence_trimmer`'s human
action text (`"trimmed" in action.lower() or "removed" in action.lower()`),
coupling the refinery's display to another tool's wording — the
branch-message-pinning anti-pattern `AGENTS.md` warns against (see the
"Do not pin one dependency version's branch message" gotcha).

**Scope:**

- [x] Correct the `:5` module-docstring chain and the `:157` UI subtitle to
      include noise reduction in the right position.
- [x] Renumber the step comments (fix the duplicate "5") and normalise the
      separator style.
- [x] Replace the substring match in `_run_trim_stage` (`:363-370`) with the
      tool's own structured result (an enum/status), per the branch-message rule
      - read `silence_trimmer`'s return type and map it explicitly.
- [x] Update the `audio_refinery` user-guide generator if it repeats the chain,
      and regenerate the `.docx`.

**Tests (lockstep):**

- [x] `audio_refinery/tests/test_pipeline_stages.py` - the trim-stage message is
      derived from the structured result, not the substring: a fixture whose
      action string does **not** contain "trim"/"removed" but is a trim result
      still produces the correct message. (Positive contract; pins the
      decoupling.)

**Acceptance:** docs match the executed order (verified against
`pipeline.py:196-204`); the structured-message test passes; bare full suite
green.

---

## Sprint 2 — Dead code and the deferred duplication class

**Why here:** these are maintainability items with mechanical, well-precedented
playbooks (the audit notes the exact pattern to follow for E2), but they are the
largest diffs and deserve a green baseline beneath them.

```
Sprint 2   E1..E5   dead code + duplication   -> E1 (delete) first; E2 lock-first
   |
   v
Sprint 3   F1..F3   test hygiene + consolidation
```

---

### E1 `[ ]` — Delete the production-dead legacy argparse subsystem `[audit M1]`

**Priority:** P2 | **Effort:** 0.4 day | **Risk:** Low

**Problem.** `audio_suite_shared/cli_helpers.py:239-535` —
`create_standard_parser`, `parse_cli_args`, `validate_cli_args`,
`apply_stage_args`, `StandardCLIHandler`, `SourceOutputCLIHandler` have **zero
production call sites**. Every `.pyw` launcher imports
`audio_suite_shared.launcher.parse_cli_args` instead; every per-tool
`utils/cli_args.py` uses only the handshake helpers plus `UniversalCLIHandler`.
Only `audio_suite_shared/tests/test_cli_helpers.py` exercises them.

Two consequences: (a) ~300 lines maintained/reviewed/type-checked for nothing;
(b) a **name collision** — `cli_helpers.py:468` and `launcher.py:21` both define
`parse_cli_args` with different semantics. An import from the wrong module
compiles cleanly and does the wrong thing.

Its defaults have also drifted: `--sensitivity` default 5.0 (`:291-295`) while
the declick engine's domain is 0.0–0.4 (`audio_refinery/cli.py:36-40`);
`--threshold` −40.0 vs −50; `--fade-in` 100 vs 500; `--tolerance` 1.0 vs 0.5.
Dead code that has drifted is worse than no code, because it reads as
authoritative.

**Scope:**

- [ ] Before deleting, **prove zero production callers** with an AST scan
      (mirror the iteration-7 B1 lock: scan every production `.py`, assert no
      call to the six names). If any real caller exists, this item becomes a
      migration item, not a deletion — record the finding and stop.
- [ ] Delete `cli_helpers.py:239-535` and the six names; delete the tests in
      `test_cli_helpers.py` that exercise **only** the deleted subsystem (keep
      tests for the handshake + `UniversalCLIHandler`, which are live).
- [ ] Resolve the `parse_cli_args` collision — after deletion only
      `launcher.parse_cli_args` remains, which resolves it by construction. No
      rename needed.

**Tests (lockstep):**

- [ ] An AST lock asserting none of the six deleted names exist anywhere in
      production code (prevents reintroduction), with a positive control (e.g.
      `UniversalCLIHandler` IS referenced) so it cannot pass vacuously.
- [ ] The surviving `test_cli_helpers.py` tests pass **unedited** for the live
      helpers.

**Acceptance:** the AST lock proves zero production callers pre-deletion; the
subsystem and its exclusive tests are gone; `ruff`/`mypy` still clean; bare full
suite green.

**Negative controls:** before deleting, confirm the AST scan is non-empty
(i.e. it actually found call sites to scan); the audit's §5 lesson about a
vacuous scan reusing the wrong exclusion set applies — assert the scanned set is
non-empty. Re-adding a deleted name fails the lock.

---

### E2 `[ ]` — Extract `noise_reduction` ↔ `pop_click_remover` behind `tool_app_base` `[audit M5]`

**Priority:** P2 | **Effort:** 0.8 day | **Risk:** Medium

**Provenance:** this is iteration-7 item **B4**'s explicitly named follow-up
("this item's named follow-up"), which was never scheduled. It was deferred here
from iteration-6/7.

**Problem.** 449 vs 406 lines; `git diff --no-index` = 64 insertions / 107
deletions, i.e. **~342 lines common in place** (~0.76–0.84, consistent with the
prior audit's 0.788). Verbatim-identical blocks: the imports, the
driver-mirrored var block, the worker slot pool, last-directory restore, the
`_build_ui` skeleton, the preset handlers, the `_apply_cli_args` skeleton,
browse, `_on_progress`, `_update_progress_ui`, `_on_complete` (differing only in
"Reduced" vs "Succeeded"), `_on_error`/`_open_help`/`_open_log`/`_open_folder`,
and `main()`. `tool_app_base.py:5-6` documents the exact pattern to follow — the
one iteration-7 B4 used for `bpm_analyzer`/`lyrics_manager`.

**Scope — follow the B4 playbook exactly (lock-first):**

- [ ] **Lock.** Extend each tool's existing tests to pin its current behaviour
      (progress, complete, dry-run, undo). These pass **unedited** through the
      extraction.
- [ ] **Extract.** Move the shared skeleton into a
      `tool_app_base.NoiseReductionToolApp`-style base (following
      `AnalysisTagToolApp`, `tool_app_base.py:5-6`), parameterising the two
      differences the audit names: the result noun ("Reduced" vs "Succeeded")
      and the engine call.
- [ ] **Delete** the duplicated bodies in both `app.py` files.
- [ ] Keep both tools' public entry points (`main()`, `NoiseReductionApp`,
      `PopClickRemoverApp` class names, `.pyw` launchers, CLI flags, card ids)
      **unchanged** — registration depends on them.

**Tests (lockstep):** the B4 lock, both suites unedited through the change; plus
a test that the two apps' `main()` and class names resolve (registration
integrity).

**Acceptance:** the measured shared-line count drops below a documented
threshold (e.g. < 100 common lines); both suites green unedited through the
extraction; bare full suite green; per the B4 precedent, the pre-existing
suites pass **unedited** and any edit to a behaviour-lock test is justified in
the Completion Log.

**Risks:** this is the highest-risk item in the plan (a GUI extraction). Honour
the **two-try rule**: if the first extraction draft fails more than a handful of
the lock tests, revert-to-lock and re-derive at the `tool_app_base` seam rather
than trying variations.

---

### E3 `[ ]` — Fingerprinter: enum statuses + deduplicate the tag-write block `[audit M14]`

**Priority:** P2 | **Effort:** 0.5 day | **Risk:** Low

**Problem.** Loose status strings (`"ERROR"`, `"MATCHED"`, `"TAGGED"`,
`"NO MATCH"`, `"LOOKUP SKIPPED"`, `"ANALYSED"`, `"ALBUM AMBIGUOUS"`,
`"TAG WRITE FAILED"`) are scattered across `_result_display` (`:76-84`),
`_summarise_results` (`:349-377`), `_run_album_phase` (`:583-641`) and log
building (`:786-802`). `cd_ripper` by contrast uses a `VerificationStatus` enum
— the suite already knows the better pattern. Additionally `:305-339`
(`_process_file`) and `:419-460` (`_finalize_album_file`) are near-identical
write-acoustid-tags + write-MBIDs + result-construction blocks.

**Scope:**

- [ ] Introduce a `FingerprintStatus` enum (mirroring `cd_ripper`'s
      `VerificationStatus`; read it for the exact pattern) and replace the eight
      bare strings at the four sites. Keep the **display strings identical** —
      the enum is a typing/refactor change, not a UI change.
- [ ] Extract the shared "write acoustid tags → write MBIDs → build result" tail
      from `_process_file` (`:305-339`) and `_finalize_album_file` (`:419-460`)
      into one helper, parameterised only by what genuinely differs.
- [ ] Per the `AGENTS.md` "display-name-keyed dict" and branch-message rules, the
      enum's `.value` must equal the current string exactly (no case/format
      change), so no pinned display test breaks.

**Tests (lockstep):** existing fingerprinter tests pass **unedited** (they pin
the display strings); add a test asserting the enum covers every status the
runner can emit (non-vacuity: `len(enum) == 8`).

**Acceptance:** zero bare status literals remain in the four functions; the
display strings are byte-identical pre/post; bare full suite green.

---

### E4 `[ ]` — Dead-code sweep `[audit M15, M19]`

**Priority:** P2 | **Effort:** 0.5 day | **Risk:** Low

**Problem.** Two findings grouped as mechanical removals.

**M15 — dead code in production paths:**
- `audio_refinery/ui/setup_tab.py:38-84` — `_ENHANCE_PRESETS`, 47 lines, **never
  used** (the file uses the shared `PRESETS` from `audio_suite_shared.dsp_models`
  at `:614`): duplication *and* dead. Delete.
- `setup_tab.py:386-388` — `_sync` defined, never bound (it would create
  unparented Tk vars if it ran). Delete.
- `audio_refinery/core/file_processor.py:41-76` — `check_integrity_batch` has no
  production caller. Confirm by AST scan, then delete (and its test).
- `audio_fingerprinter/core/file_processor.py:756` — `slot_idx = i %
  processor.max_workers` and the `_FingerprintJob.processor` field are dead
  (`_fingerprint_worker` re-derives the slot from `job.slot_queue` at `:114`).
  Delete both, and the field's constructor arg.
- `master_driver/runner/module_runner.py:110-133` — legacy str-spec path;
  `_SENTINEL_MAP` is built **inside** the loop (`:112`). No production caller
  builds str specs. Confirm by AST scan, then delete.
- Write-only attributes: `_dir_path` in four apps (`tempo_analyzer:79,331`,
  `album_genre_tagger:66,264`, `lyrics_manager:100,405`,
  `replaygain_analyzer:68,312`), `_output_dir_final`
  (`music_format_converter:81,565`), `_reset_ui`
  (`music_format_converter/app.py:344-349`), and `self.style` in eight `app.py`
  files. Confirm each is assigned-never-read, then remove the assignment.
- `cli_helpers.py:661-662` — `hasattr(self.app, "scheme")` can never be true
  (`TempoAnalyzerApp`'s attribute is `tempo_scheme`, `tempo_analyzer/app.py:61`).
  Remove the dead branch.
- `auto_start_func` (`cli_helpers.py:607-608, 744-745`) — dead in every handler
  pattern while four callers still pass it. Confirm zero production reads, then
  remove the parameter and the four pass-sites.

**M19 — `show_message` god function.** `ui_common.py:498-604` is 107 lines
(geometry, header, content, action row, hover bindings, event bindings all
inline) with a one-line docstring (`:506`) and no `Args:` section despite four
parameters. Its `:508` `import threading as _threading` is function-local with
no circular-import justification; `:542` logs "Could not restore dialog
geometry" during *initial* centring; `:524` retains commented-out code
(`# dialog.overrideredirect(True)`) under a "keeping it for now" note.

**Scope:**

- [ ] For **every** deletion, prove zero production callers by AST scan before
      removing (never delete on the audit's word alone). Remove the
      corresponding test if the deleted symbol had one.
- [ ] M15: execute the removals above.
- [ ] M19: split `show_message` into `_build_header`, `_build_content`,
      `_build_action_row` helpers (mirroring whatever decomposition
      `discrete_slider_row` and neighbours already use in the same file), hoist
      the `threading` import to module level **only if** there is no import
      cycle (check; if there is, keep it local with a one-line comment saying
      why), fix the `:542` log wording, and remove the commented-out `:524`
      code.
- [ ] Give `show_message` a full Google-style docstring with `Args:`.

**Tests (lockstep):** an AST lock per deleted-symbol class (as in E1);
`ui_common` tests for `show_message` continue to pass **unedited** (they pin
its behaviour).

**Acceptance:** every deletion is AST-proven; `show_message` is decomposed with
its docstring complete; bare full suite green; `mypy --strict` still clean (a
removed-attribute write would surface there).

**Negative controls:** the AST locks fail if any deleted symbol is
reintroduced; a non-vacuity assertion on each scan's result set (the §5 vacuous-
scan lesson).

---

## Sprint 3 — Test hygiene and consolidation

---

### F1 `[ ]` — Consolidate the duplicated batch engines `[audit M6]`

**Priority:** P2 | **Effort:** 0.4 day | **Risk:** Low

**Problem.** `batch_orchestrator.py:5-6` claims it *"Replaces the simple
sequential loop in module_runner.py."* It did not: `module_runner.py:173-282`
still carries its own sequential loop, its own `_emit_progress` (`:332-382`) and
its own `_launch_standalone` (`:398-447`), duplicating
`batch_orchestrator.py:449-516` and `:431-447`. Two implementations of progress
semantics and standalone launching must be kept in sync.

**Scope:** This item is **bounded to the duplication** — make one engine
authoritative for `_emit_progress` and `_launch_standalone` (have
`module_runner` import the shared versions, or vice versa per the existing
dependency direction), and either delete the superseded sequential loop or record
clearly which loop `batch_orchestrator` calls. Deleting the wrong loop breaks
sequential mode — **read the call graph first** and prove with a test which
engine sequential mode uses.

**Tests (lockstep):** a test asserting the two modules reference the *same*
`_emit_progress`/`_launch_standalone` objects (by identity), so a future
re-fork fails.

**Acceptance:** one implementation each; progress semantics identical in both
modes; bare full suite green.

---

### F2 `[ ]` — Migrate the 123 class-scoped fixtures; close the test SQLite handles `[audit M9]`

**Priority:** P2 | **Effort:** 0.6 day | **Risk:** Low

**Problem.** **123 class-scoped fixtures defined as instance methods across 30
test files** (fixture-decorated `def` taking `self`, counted at `c1daf1d`).
pytest already emits `PytestRemovedIn10Warning` on every affected class (46
warnings in the bare run); under `-W error::pytest.PytestRemovedIn10Warning` the
suite errors immediately. Concentrated in `master_driver/tests/test_ui_cards.py`
(26 `_import` fixtures), `audio_suite_shared/tests/test_ui_common.py` (14
`setup_tk`), `tempo_analyzer/tests/test_tempo_schemes.py` (8), plus
`audio_refinery`, `noise_reduction`, `silence_trimmer`, `pop_click_remover`,
`replaygain_analyzer`, `audio_enhancer` and others.

Also in the warning stream: unclosed `sqlite3.Connection` `ResourceWarning`s from
tests that call `log._connect()` / `cache._connect()` without closing
(`audio_suite_shared/tests/test_batch_undo.py:183-192`,
`library_stats/tests/test_library_cache.py`), plus two `librosa` warnings from
short analysis fixtures. Production SQLite handling is exemplary; this is
test-side only.

**Scope:**

- [ ] Migrate each instance-method class-scoped fixture to module scope or a
      `@staticmethod` (mechanical). This is deliberately **its own item** so it
      lands as one reviewable commit and can be reverted wholesale if the pytest
      major lands differently than expected. Re-run the counting probe from
      *Problem* to confirm the count reaches 0.
- [ ] Close the unclosed SQLite connections in test teardown (a finaliser in the
      affected fixtures).
- [ ] The two `librosa` warnings come from short analysis fixtures — either
      lengthen the fixture or filter the specific known-benign warning with a
      comment saying why it is benign.

**Tests (lockstep):** none needed (this item *is* test hygiene); the acceptance
is the warning count.

**Acceptance:** `pytest -q -W error::pytest.PytestRemovedIn10Warning` collects
and runs (or, if a residual instance-method fixture remains, the count drops
from 123 with the remainder listed); the `ResourceWarning` count for SQLite
drops to 0; bare full suite green.

---

### F3 `[ ]` — Card-shell and arg-builder duplication `[audit M22]`

**Priority:** P2 | **Effort:** 0.8 day | **Risk:** Medium

**Problem.** Below the 0.60 duplication threshold but real:
- **Card shells** — `master_driver/ui/cards/`: `build_simple_card`
  (`_card_base.py:118`) serves 8 cards, but **20 cards** still hand-roll a
  verbatim ~30-line shell (identical `expanded = [False]` blocks across
  converter, pop_click_remover, fingerprinter, replaygain, cd_ripper,
  audio_normalizer, palette, bpm, lyrics_manager, audio_enhancer,
  silence_trimmer, scrubber, file_reorganizer, theme, typography, art,
  album_genre, library_stats, noise_reduction, tempo). B2 consolidated the
  *spec* family; the shell family was out of its scope.
- **Arg builders** — `master_driver/runner/arg_builder.py`: five near-identical
  `(path, "0", mode, start, end, --duration, --parallel, --workers)` builders
  (`:451-476`, `:509-530`, `:533-554`, `:641-661`, `:479-506`).

**Scope:** extend `build_simple_card` (or add a `build_collapsible_card`) to
absorb the 20 shells; extract one `_base_tokens(path, mode, start, end)` helper
for the five arg builders. **Preserve every card's emitted structure and every
arg builder's exact output** — the registration tests (`test_tool_plugin`,
`test_runner`, `test_app_state`) and the golden arg vectors are the lock.

**Tests (lockstep):** the existing card and arg-builder tests pass **unedited**.
Any edit to them is a red flag requiring Completion-Log justification. Add a
consistency test that each converted card's widget tree matches its pre-refactor
shape (the spec-driven `_card_base` test pattern).

**Acceptance:** the 20 shells collapse to the shared builder; the five arg
builders share the token helper with byte-identical output; bare full suite
green.

**Risks:** card UI changes are easy to regress silently. Lock with the widget-
tree shape test, and per `AGENTS.md` prove with the full bare suite (card
rendering is mocked; only the shape test catches a mis-wired card).

---

## Sprint 4 — Lower-severity robustness, readability and capability

*This Sprint is deliberately last and lowest priority. Sprint 3 must be green
first; the two capability items (I5/I6 below) expand into their own plans per
iteration-7's E6/E7 precedent and are listed here only so the audit's capability
recommendations are not silently dropped.*

---

### I1 `[ ]` — Robustness items `[audit M23]`

**Priority:** P4 | **Effort:** 0.6 day | **Risk:** Low

**Problem.** 12 sub-items (full text in the audit):
- `MutagenError = Exception` aliases in 4 files (`replaygain_analyzer/core/file_processor.py:40`,
  `file_reorganizer/core/engine.py:26`, `audio_enhancer/core/inspector.py:16`,
  `audio_enhancer/core/tags.py:25`) — when mutagen is absent, every
  `except MutagenError` degrades to `except Exception`.
- `SubprocessSecurityError` (`secure_subprocess.py:64`) subclasses bare
  `Exception`, outside the `AudioSuiteError` hierarchy.
- `file_processor_base.py:252-255` — `run_parallel_processing` doesn't catch the
  future `TimeoutError`, so `on_complete` is **never called** and GUI progress
  goes stale (5 production tools use it); `process_batch` (`:584-604`) catches it.
- `secure_subprocess.py:437-443` — `run_python_script`'s `timeout` bounds only
  the final `wait()`; the stdout read loop is unbounded.
- `suite_config.py:190-192` — no cross-process lock around load→mutate→save
  (lost update).
- `batch_undo.py` read paths (`:562-568`, `:708-718`, `:739-745`) execute without
  `self._lock` (mitigated by WAL at `:224`, undocumented).
- `error_handler.py:36-40` — `_DEBUG` evaluated at import; `exceptions.user_message_for`
  (`:508`) reads the env var per call; they disagree.
- `key_manager.py:283-291` — `is_encrypted_value` treats any base64-decodable
  string ≥ 44 bytes as a Fernet token; a plaintext key can be misdetected.
- `master_driver/app.py:141` — `except tk.TclError: pass` (last silent site).
- `lyrics_manager/app.py:118` — a production `assert` (`[tool.bandit]` policy:
  raise explicitly; `python -O` strips it).
- `arg_builder.py:158-162` — the AcoustID API key passed to the child as a
  `--api-key` **argv** (exposed to local process listing); the suite treats it
  as secret-class elsewhere.
- fingerprinter uses `time.time()` for durations (`:745`, `:810`) while the
  driver runner uses `time.monotonic()`.

**Scope:** fix each. For the `MutagenError` aliases, define a single shared
`MutagenError` (in `audio_suite_shared/exceptions.py`) that subclasses
`AudioSuiteError` when mutagen is present, and import it in all 4 files. For the
API key, pass it via an env var or a file reference, not argv (read
`module_runner`'s subprocess construction). For the parallel timeout, mirror
`process_batch`'s handling. Log/document the WAL mitigation for the `batch_undo`
read paths.

**Tests (lockstep):** per sub-item where testable — the parallel-timeout test
asserts `on_complete` **is** called on timeout (positive); the key-registry
env-var test asserts the argv no longer contains the key (positive: the key is
in the env instead).

**Acceptance:** each sub-item fixed with a test; `mypy --strict` still clean;
bare full suite green.

---

### I2 `[ ]` — Readability items `[audit M24]`

**Priority:** P4 | **Effort:** 0.4 day | **Risk:** None

**Problem.** Stale/comments/naming/docstring items (full text in the audit):
- `app_bootstrap.py:145-147` — history-marker comment ("Everything below is the
  original file — unchanged") documents the VCS; `:123` names the `audio_suite`
  logger `root_logger` (fixed in C8 — do not duplicate here).
- Stale comments: `audio_enhancer/app.py:329`, `replaygain_analyzer/app.py:345,402,419`
  ("Fix #3"/"Fix #15"), `tempo_analyzer/app.py:41-42` (dangling "Locate suite
  root"), `audio_refinery/ui/setup_tab.py:609-629` (stream-of-consciousness
  over an incomplete preset behaviour), `_card_base.py:13` (`:func:` reference
  to `build_card_shell`, which does not exist).
- `tool_plugin.py:59` — "multiples of 10 to leave gaps" vs actual 41–47 (45
  twice: `tag_field_updater:335`, `pop_click_remover:375`); `:159-160` claims
  declaration order is "load-bearing … drives the listing" (false — sorted by
  `(category, order, name)` at `:117-130`).
- `ui_common.py:308-309` — documents `Raises: ValueError`; code raises
  `AudioConfigurationError` (`:311-312`), which does not subclass `ValueError`.
- `cli_helpers.py:543-546` — class docstring and per-pattern docstrings disagree
  on pattern counts and omit the fourth (directory) pattern.
- `models.py:60-61` — a comment "# output_gain_db intentionally omitted"
  immediately above the declared field.
- Naming drift: `GenreConsolidatorApp`, `AudioSuiteV6`/"v6.0 (Optimized)",
  `TOOL_ID`/`_TOOL_ID`, `start_processing`/`start_extraction`/`start_thread`.
- Style: three module-logger names (`logger`/`_log`/`_logger`); `Optional` vs
  `X | None` mixed within the same files; absolute/relative imports mixed
  per-file.
- `cli_dataclasses.py:116-145` — `validate_source_output_paths` is
  `validate_folder_path` twice; `:88-91` `LyricsArgs` duplicates `BPMArgs`'s
  four fields; `parallel_mode`/`parallel_run` coexist.

**Scope:** correct each comment/docstring/naming to match reality. Rename only
where the name is actively misleading (`AudioSuiteV6` → drop the version, if
the maintainer approves the card-id surface is untouched — the *display name*
may change, the `id` may not). For the style-consistency items (`Optional` vs
`|`, logger name), normalise **within each file** (the audit's actual finding) —
do not normalise across the whole suite in this item (minimal diff).

**Tests (lockstep):** the `ui_common` `Raises:` correction must keep
`discrete_slider_row`'s existing `pytest.raises` test green and update its
expected exception type if it asserted `ValueError` (the code raises
`AudioConfigurationError`, so a test pinning `ValueError` was wrong and is fixed
in lockstep). The user-guide hygiene tests must stay green if any guide repeats
a corrected claim.

**Acceptance:** every listed comment/docstring now matches the code; bare full
suite green; `mypy --strict` clean after the naming changes.

---

### I3 `[ ]` — GUI coverage floors `[audit M10]`

**Priority:** P4 | **Effort:** 0.8 day | **Risk:** Low

**Problem.** No module is at 0% (D1's gate holds) and no GUI `app.py` is below
40%, but six sit below 60%: `tempo_analyzer/app.py` **44%** (119 missed),
`album_genre_tagger/app.py` **45%** (104), `audio_enhancer/app.py` **47%** (122),
`asx_extractor/app.py` **52%** (78), `album_art_sync/app.py` **53%** (129),
`tag_editor/ui/app.py` **57%** (91). Non-GUI modules sit at 93–99% for the same
code paths. Also low: `cd_ripper/core/drive_handler.py` 40%, `cd_ripper/ui/rip_tab.py`
41% (hardware-gated — expected, `pytest -m hardware` documented),
`asx_extractor/ui/processing_tab.py` 29%, `tag_field_updater/cli.py` 48% (the
surface carrying H1), `genre_sync/cli.py` 56%, `noise_reduction/cli.py` 67%.

Two of the six — `album_genre_tagger` and `album_art_sync` — carry H3. Their
coverage is low *because* the offending worker-thread code is what the tests
skip, which links the gap directly to the defect.

**Scope:** raise the six sub-60% `app.py` modules toward 65%, prioritising the
two H3 apps (A3's new scheduling tests seed this) and `tag_field_updater/cli.py`
(A1's new tests seed it). Hardware-gated modules (`cd_ripper` drive handler/rip
tab) stay as-is — they are legitimately exercised only under `-m hardware`.
Per the `AGENTS.md` §6 item 10 coverage discipline, capture the per-module table
immediately after the bare full-suite run, in the same command block.

**Tests (lockstep):** the coverage gains come from new tests exercising the
uncovered branches (not from excluding modules). The six-module table is the
acceptance artifact.

**Acceptance:** the six `app.py` modules each reach ≥ 65% (or a documented
reason they cannot); suite coverage ≥ 75%; no module excluded to manufacture the
number.

---

### I4 `[ ]` — Lyrics `.lrc` sidecar provider (iteration-7 E5 follow-up, **decision-gated**) `[audit §5]`

**Priority:** P4 | **Effort:** 0.5 day | **Risk:** Low

**Provenance:** iteration-7 **E5** closed as "single provider by policy" (the
Musixmatch disqualification was correct); its named *next candidate* is **local
`.lrc` sidecars**. The audit's market comparison lists "local `.lrc` sidecars" as
the right cheap answer. This item is that follow-up, decision-gated (`[!]` until
the maintainer approves), because it is a **capability** addition, not a defect.

**Scope (once approved):** add a second lyrics provider behind the existing
registry that reads a local `.lrc` sidecar next to the audio file (no network,
no licence issue). Follow the existing provider interface (read
`lyrics_manager`'s provider registry — the E5 work added it). This is a small,
self-contained addition.

**Tests (lockstep):** a real `.lrc` sidecar + audio file pair; the provider
resolves and the tags are written (real-audio outcome); no-network guarantee
tested by running with network disabled/monkeypatched.

**Acceptance:** provider registered; sidecar lyrics land in the tags; bare full
suite green.

**Risks:** low. Decision-gated only because it is new capability, not because it
is risky.

---

### I5 `[ ]` — Capability disposition (E6/E7) — **decisions, not defects**

**Priority:** P4 | **Effort:** 0.1 day (disposition only) | **Risk:** None

**Problem.** The audit's market comparison lists two large capability gaps that
iteration-7 parked: **E6** duplicate finder / library database (the largest gap)
and **E7** DSD support. The audit reaffirms both are real and correctly parked,
each needing its own plan.

**Scope:** record the disposition in this plan's Completion Log — either
(a) maintainer opens `PLAN_iteration8_duplicate_finder.md` / `PLAN_iteration8_dsd.md`
now, or (b) they remain parked with a stated revisit trigger. The audit's ten-
point registration checklist (in `AGENTS.md`) is the scope for E6 when scheduled.

**Acceptance:** a recorded disposition for each; no code change.

---

## Sprint Dependencies

```
Sprint 0   A1 A2 A3 A4      correctness       -> independent; A1/A2 single-file;
   |                                          A3 is the largest (2 GUI apps)
   |
   v
Sprint 1   C1..C10          contract + data   -> independent of Sprint 0;
   |                                          several are 1-line fixes
   |
   v
Sprint 2   E1 E2 E3 E4      dead code + dup   -> E1 (delete) first; E2 lock-first;
   |                                          needs green baseline beneath
   v
Sprint 3   F1 F2 F3         test hygiene +    -> F2 (fixtures) independent;
   |                        consolidation      F1/F3 need green suite
   v
Sprint 4   I1 I2 I3 I4 I5   robustness +       -> last; I4 decision-gated;
                            capability        I5 disposition only
```

- **Everything except E2 and F3 is independently shippable**, which is what keeps
  this a staged plan rather than a big-bang rewrite.
- **Deliberate ordering:** Sprint 1 before Sprint 2 (tests lock the *current*
  behaviour before dead code is removed and the duplication is extracted);
  Sprint 3 before Sprint 4 (test hygiene lands before the coverage work that
  depends on stable tests).
- **A1 and A4 are conceptually adjacent** (both about moving Tk reads to the main
  thread) but are **separate commits**: A4 is the driver launcher, A1 is the
  tag-update CLI. Keeping them separate honours minimal diff and makes each
  independently revertible.

---

## Phase Gate (run after **every item**, before marking it complete)

Per item — not per sprint:

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` — exit 0
   (mandatory after **any** edit to a module in an import chain)
1. `python -m ruff check .` and `python -m ruff format --check .` — clean
2. `python -m mypy .` — 0 issues (`strict = true`)
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv
   -c pyproject.toml` — 0 High / 0 Medium
4. Bare `python -m pytest -q` — 100% pass; a package-scoped run is **not** a
   substitute
5. Coverage gate: `fail_under = 75`, recorded as an explicit number; the
   per-module table comes from the same command block as the run
6. No secrets staged: `git grep --cached` over the standard alternation plus the
   supplemental `*_key`-suffix / 32-hex / 44+-base64 / PEM scans

Item-specific extra gates:

- **Artifact/data-correctness items (A1, A2, A6/C6, C7, I1's key item):** prove
  the **outcome** (no write in dry run; CUE names files that exist; no exception
  escapes; old key recoverable), not a read-back of internal state.
- **Threading items (A3, A4):** the scheduling test must pass and the **bare full
  suite** must not hang (a previous GUI item hung CI on a shared-root side
  effect; use per-test withdrawn `Toplevel`s).
- **CLI items (A1, C6):** assert payloads on **stdout only** — `CliRunner`'s
  `Result.output` is stdout+stderr merged in write order and is not stable
  (`AGENTS.md` §6 item 11).
- **Deletion/lock items (E1, E4, F3):** every AST lock asserts a **non-empty
  scanned set** so it cannot pass vacuously, and every deletion is proven
  caller-free before removal.
- **Coverage items (I3):** the per-module table is captured immediately after the
  bare full-suite run.

---

## Implementation Roadmap

| Sprint | Content | Items | Est. days | Depends on |
|--------|---------|-------|-----------|------------|
| 0 | Correctness (audit Highs) | A1–A4 | 1.6 | nothing |
| 1 | Contract + data integrity | C1–C10 | 2.8 | nothing |
| 2 | Dead code + deferred duplication | E1–E4 | 2.2 | Sprint 1 green baseline |
| 3 | Test hygiene + consolidation | F1–F3 | 1.8 | Sprint 2 green baseline |
| 4 | Robustness, readability, capability | I1–I5 | 2.4 | Sprint 3 green; I4 decision |

**Estimated total: ~11 days** of incremental, independently shippable work —
comparable to iteration 7's ~10 days. Every Sprint ends green against the Phase
Gate; every item lands as its own reviewable commit.

**Deliberately not in this plan as code:** E6 duplicate finder and E7 DSD (each
expands to its own plan when scheduled — disposition recorded in I5); the
plugin architecture (iteration-6 §C2 backlog); macOS parity (iteration-6 §C1);
adopting `slots=True` (no measured benefit); re-trying the Linux CI leg (closed
as not-applicable). These are recorded so they are not silently dropped.

---

## Completion Log

Fill one row per **item**, with the per-item Gate Evidence rule: date + the six
commands + pass/coverage counts. A row without Gate Evidence is incomplete by
definition. Include **Negative-control results** (which revert broke which test)
and any **deviation** from the plan's stated scope, with justification.

| Item | Sprint | Completed | Gate Evidence | Notes |
|------|--------|-----------|---------------|-------|
| A1 | 0 | 2026-10-03 | compileall 0 · `ruff check`/`format --check` clean · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium · bare `pytest -q` 8179 passed, 3 skipped · coverage 88.08% (≥75) · secret scan clean (only docstring matches) | CLI smoke on a real MP3 (`genre=Rock/Pop`): exit 0, `{"dry_run": true, "updated": 1}`, file SHA-256 unchanged and TCON still `Rock/Pop`. **Negative control:** the CLI help/docstring spelling `--dry-run` fails all 3 dry-run tests; restoring `--dry` returns green. Targeted after A1: 271 passed (tag+shared). Deviation: the plan said the JSON's `updated` "says 'would update'"; this build reports the integer count (`updated: 1`) — the "would update" wording is in the text summary ("Files would update: 1"), so no code change was made. |
| A2 | 0 | 2026-10-03 | compileall 0 · ruff clean · `mypy .` 0 issues · targeted `pytest cd_ripper/tests + test_cue_generator.py` 373 passed, 30 deselected · full bare suite + coverage re-run after A4 (see A4 row) | Guide audit: no incorrect single-image claim in `user_guides/individual_programs/cd_ripper/` (the "single-file image" wording describes Split CUE Image), so no guide regeneration. `cue_generator.py` itself needed no change — the defect was the single `CueFileSpec` the ripper built. **Negative controls:** the original one-spec form fails 3 tests; the loop-leaked-path form fails 3 tests; restore verified SHA-256 `e8ebe41ad5c64a20a0869297ffb011132e1dcd8b264e499b439269db9da5b800`. |
| A3 | 0 | 2026-10-03 | compileall 0 · ruff clean · `mypy .` 0 issues / 460 files · `album_art_sync/tests` 279 passed · `album_genre_tagger/tests` 124 passed · full bare suite + coverage after A4 | `module_runner`-style scheduling tests run against real widgets on per-test withdrawn `Toplevel`s; the bare suite did not hang. **Negative controls (SHA-256-verified):** genre `root.after` removed → 1 failure; album-art worker set back to `daemon=False` → 1 failure; `_add_log` writing the Listbox off-thread → 1 failure. Restored SHAs `d5a16f60…6103c` (genre) / `819c5bc1…b52f8` (album art). Both apps keep `daemon=True`. |
| A4 | 0 | 2026-10-03 | compileall 0 · `ruff check .` clean · `ruff format --check .` 785 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium (41 Low pre-existing) · bare `pytest -q` **8179 passed, 3 skipped, 30 deselected**, 224.96s · coverage **88.08%** ≥ 75 · secret scan clean | The full six-command gate ran in one block at the end of Sprint 0 and re-validates A1–A3 unchanged. `build_*_args` output is byte-identical (`TestBuildEnrichArgs` `[path, mode, start, end]` kept green, unedited); only the toggle element of the spec tuple changed from a Tk var to a resolved `bool`. **Negative control:** restoring `master_driver/tool_launcher.py` to HEAD (argv built inside the thread) fails all 4 `TestArgvBuiltOnMainThread` tests; restore SHA-256 `358d4f4c1717acedc3003dddfe69d12db6675a5dc6c135c3660a9dd7515d9108`. Deviation: the argv tests live in `test_tool_launcher.py`, not `test_runner.py`, because the thread boundary is owned by `tool_launcher.py`. |
| C1 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` 785 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium / 41 Low · bare `pytest -q` **8193 passed, 3 skipped, 30 deselected**, 214.00s · coverage **88.10%** · **re-verified at HEAD `def9a5c`**: `tests/security/test_input_validator.py` 44 passed | Closes M2 and M3 under decision **J1 = "make it real"**. **M3:** the hardcoded `{mp3, flac, wav, ogg, m4a, aiff, aif, wma}` set was replaced by `InputValidator.AUDIO_EXTENSIONS`, derived from `audio_suite_shared.audio_formats.SUPPORTED_EXTENSIONS`, so the next format addition cannot drift out of the security gate; verified at HEAD as exactly `[.aif .aiff .flac .m4a .mp3 .mp4 .ogg .opus .wav]` — `.mp4`/`.opus` accepted, `.wma`/`.aac`/`.webm` rejected. **M2:** the branch compared `resolved != declared.resolve(strict=False)`, but `resolve()` already defaults to `strict=False`, so both sides were the identical computation and the condition was **always False** — the docstring's `logger.warning` was unreachable. `_traverses_symlink` now compares the filesystem-resolved path against the **lexically** normalised absolute path (`os.path.normpath(os.path.abspath(...))`), which differ only when a link was traversed; both sides go through `os.path.normcase` so a real directory whose declared casing differs from on-disk casing is not misreported on Windows. The warn-but-allow policy and its safe-roots check are unchanged. Two further docstrings in the same file claimed unimplemented behaviour (`validate_tag_value` claimed to reject control characters while permitting C1 U+0080-U+009F) and were corrected. **Tests pinned the defects and were replaced with positive contracts:** `test_all_allowed_extensions` had listed `.wma` as accepted (now derives from `SUPPORTED_EXTENSIONS` and asserts `.wma` is rejected); `test_symlink_outside_safe_root_logs_warning` patched a non-existent logger `"audio_suite.security"` and asserted only `result is True` — i.e. "nothing bad happened" — and now asserts the warning is emitted and names the resolved target; new `TestSymlinkDetection` drives the detector directly and through a simulated link so the assertion holds where symlink creation needs Windows privileges. **Negative controls (SHA-256-verified restores):** restoring the exact pre-fix line `resolved != declared.resolve(strict=False)` fails 2 tests — a *paraphrase* of the defect does not, so the control had to be the original expression; re-adding `.wma` fails 3 tests. **Recorded, not changed (out of scope):** `validate_audio_file_path` still has no production callers (only `validate_directory_path` is called from `master_driver`), so the audit's "the gate the subprocess launchers consult" framing overstates its reach; wiring new callers would exceed this item's scope. |
| C2 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` 785 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium / 41 Low · bare `pytest -q` **8196 passed, 3 skipped, 30 deselected**, 214.12s · coverage **88.10%** · secret scan clean (PEM pattern matches only the AGENTS.md/CONTRIBUTING.md scan recipes) · **re-verified at HEAD `def9a5c`**: `tests/test_user_guide_hygiene.py` 11 passed | Closes M4. `CHANGELOG.md` declares Keep-a-Changelog + SemVer compliance, yet `[Unreleased]` was empty while the tree had gained a release-sized iteration since 1.0.0. The section is now populated under `### Added` / `### Changed` / `### Fixed` / `### Removed` (6278 chars, all four sections verified present at HEAD), worded against behaviour that actually shipped rather than the plans' prose — every claim was checked against the code or a prior item's recorded gate evidence: Added = MusicBrainz identifier writing (opt-in, `--write-mbids`, refused without `--write-tags`, `audio_fingerprinter/cli.py:113`), Cover Art Archive as first art source (chain string matches `core/pipeline.py:200`), recursive mixed-format conversion, read-side MB tag helpers; Changed = always-on TPDF dither + `soxr` with `--no-dither` **including the migration advice the plan asked for** (output bytes changed; re-run undo-aware workflows from the pre-conversion originals) and the exact GUI opt-out label from `music_format_converter/ui/setup_tab.py:398`, generator-only user-guide tree, shared GUI/CLI scaffolding; Fixed = this plan's Sprint-0 items A1-A4 (`--dry` wrote tags anyway, one `FILE` per cue sheet, off-thread Tk in two apps, driver argv built on the launcher thread) plus iteration 7's `artnormalize` TypeError, the swallowed errors that now leave a log witness, and the stdout-only JSON contract test; Removed = the superseded per-tool logging guides and tracked `.bak` guide backups. **No version numbers or dates were invented** — `[Unreleased]` is the target, per the item's explicit constraint. **Deviation:** the item names `audio_suite_shared/tests/test_user_guide_hygiene.py`, which does not exist; the repo-root `tests/test_user_guide_hygiene.py` is the real hygiene home and already owns the guide generator/backup/registration locks, so the changelog lock is the fifth member of that family (its module docstring records this). **Anti-vacuity:** section extraction is bounded by the next `## ` heading and **raises if no boundary is found**, so the "non-empty" assertion cannot pass by matching nothing; two further locks assert the version headings are well formed (bracketed, dated) and that the Keep-a-Changelog/SemVer citations the lock relies on are present; an explicitly-worded "nothing yet" placeholder satisfies the lock while a bare heading does not. **Negative control:** emptying `[Unreleased]` back to a bare heading fails `test_unreleased_section_is_populated_or_explicitly_empty`; restore SHA `641cc02bd3a5a72caf69d7e85fb80ec9d045302b7308e705b8e1fe26e22126eb` verified. |
| C3 | 1 | 2026-10-04 | `python -m compileall -q -f .` exit 0 · `ruff check .` / `ruff format --check .` all checks passed, 785 files formatted · `mypy .` no issues in 460 source files · `bandit -r . -x ./.venv -c pyproject.toml` 0 High / 0 Medium / 41 Low · bare `pytest` **8203 passed, 3 skipped, 30 deselected** · coverage **88.10%** (28 239 statements / 3 361 missed), gate 75% — all captured in the same command block as the coverage table · **re-verified at HEAD `def9a5c`**: `test_batch_orchestrator.py` 62 passed, `test_runner.py` 175 passed | Closes M7 and M8. **M7:** `_run_parallel` pre-marked every standalone step `SKIPPED` **and then also** did `completed.add(s.tool_id)` + `completed_count += 1`, so `BatchReport.completed` included tools that were never launched and `skipped` came out zero — the report claimed a tool ran when it did not. The `completed` set doubles as the dependency-satisfaction set, so simply dropping skipped ids would have changed *execution*, not just reporting; a separate `skipped_ids` set keeps the concerns apart (the pool loop terminates on `len(completed) + len(skipped_ids)`, `_can_run` excludes skipped ids). No `DEPENDENCY_GRAPH` edge points at a standalone tool, so the dependency-satisfaction change is inert today. The dead `skipped_count` local became an INFO log naming the skipped tools. Verified at HEAD: the standalone skip branch adds **only** to `skipped_ids`. **M8:** the not-found branch in `_run_modules_sequential` called `on_error` then bare-`continue`d without appending to `failed_steps`, so `_emit_progress`'s index-based mapping (`i < completed_steps`) fell through to the "finished prefix" arm once a *later* step advanced `executed`, painting the missing module green — and with only that step in the batch, nothing was emitted at all. The branch now records the tool in `failed_steps`, appends its elapsed time so the ETA average is not skewed by an unmeasured step, and emits its own status line. **Test-suite defect correction:** `test_standalone_skipped_in_parallel` asserted `report.completed == 2` for a two-step batch where one step never ran — it **pinned the M7 defect** and would have kept the suite green through it; replaced with the positive contract (completed == 1, skipped == 1, per-step statuses) plus a note recording that it had pinned a bug. **New regression coverage (+7):** the skipped step is never handed to the executor; the skip is logged with the tool names; the UI progress line reads "skipped"; an all-standalone parallel batch terminates instead of spinning; and for M8 the not-found step's own status line, its absence from the "completed" set, and its emission when no other step runs. **Negative controls (exact pre-fix expressions, each reverted after firing):** re-adding `completed.add(...)` + `completed_count += 1` fails 4 tests; restoring the bare `continue` fails 3 tests with `assert 'completed' == 'failed'`. **Deviation:** the item names `master_driver/tests/test_module_runner.py`, which does not exist — the not-found-module tests went into the existing `master_driver/tests/test_runner.py`, which is where the module-runner tests actually live. **Carried forward (recorded, not fixed — out of C3 scope):** `_emit_progress`'s `i < completed_steps` mapping remains index-based and still renders a step that finishes at index ≥ `completed_steps` as "running" in its own final event when an earlier step failed; that is a separate pre-existing defect, and C3 only ensures the not-found step cannot be mislabelled. |
| C4 | 1 | 2026-10-04 | `python -m compileall -q -f .` exit 0 · `ruff check .` / `ruff format --check .` all checks passed, 785 files formatted · `mypy .` no issues in 460 source files · `bandit -r . -x ./.venv -c pyproject.toml` 0 High / 0 Medium / 41 Low · bare `pytest` **8209 passed, 3 skipped, 30 deselected** · coverage **88.10%** (28 239 statements / 3 360 missed), gate 75% · **re-verified at HEAD `def9a5c`**: the six registry tests pass, `DEPENDENCY_GRAPH` has 26 keys and `set(manifest ids) == set(DEPENDENCY_GRAPH) \| EXCLUDED` holds | Closes M11. `audio_suite_shared/tool_plugin.py:155-158` designates `batch_orchestrator.DEPENDENCY_GRAPH` as an agreement point every tool id must appear in, but nothing enforced it: the graph listed **23** ids against a **27**-tool registry, and `_collect_deps` defaults a missing id to `[]`, so newcomers ran in parallel silently — the exact failure mode the agreement point exists to prevent. Verified at HEAD: the graph now has **26** keys, and the three added ids are present with `[]` (`mood_analyzer`, `noise_reduction`, `tag_field_updater`), each confirmed against its arg-builder signature as consuming only `path` + mode/start/end + its own parameters, so none reads another tool's output. **Plan discrepancy found and resolved empirically — the registry had FOUR missing ids, not three.** The plan and audit both name `mood_analyzer`, `noise_reduction`, `tag_field_updater`; `undo_tag_edits` is absent too, and that is **not** a graph omission: it is the only manifest with `cli_command is None`, it has no arg-builder entry, both builders end in `builders.get(tool_id)` and return `[]`, so the Master Driver cannot construct a launch for it — a GUI-only undo utility, not a batch tool. **Finding worth recording:** the `EXCLUDED` allowlist is declared **in the test** (`master_driver/tests/test_batch_orchestrator.py:533`, `frozenset({"undo_tag_edits"})`) and **no `EXCLUDED` symbol exists in production code** — so the *reason* `undo_tag_edits` is absent is documented only in a test constant. This is not drift-prone in practice, because `test_excluded_matches_the_batch_ineligible_rule` pins the allowlist to the **derivable** rule "registered tools with no CLI command": if `undo_tag_edits` ever gains a CLI it automatically demands a graph entry, and a new CLI-less tool is reported there instead of passing unnoticed. That is what turns the item's "explicit, named EXCLUDED allowlist" from a hand-typed list into a checked invariant — but a future reader looking for a production declaration of the exclusion will not find one. **Test-suite defect correction:** `test_all_registered_tools_have_entry` — the only test in this area — was **vacuous**: it computed `missing = registered_ids - graph_ids` and then asserted `isinstance(DEPENDENCY_GRAPH.get(tid, []), list)` for each miss, which is trivially true for the `[]` default. It asserted the fallback behaviour rather than the contract and would have stayed green through exactly the omission it appeared to cover; replaced with the real completeness assertion, which names the offending ids in its failure message. **New registry contract (+6 net):** the agreement point; the derivable EXCLUDED rule above; an excluded id must genuinely be unschedulable (empty args from both builders); no stale ids in the graph; the plan's required non-vacuity guard `len(DEPENDENCY_GRAPH) >= len(manifest ids) - len(EXCLUDED)` so an empty or gutted graph cannot pass; and every dependency must be a graph key, since a dep naming an unregistered id can never be satisfied. **Negative control:** deleting the `noise_reduction` entry fails 3 tests with `missing from DEPENDENCY_GRAPH: ['noise_reduction']` naming the offender; reverted after firing. |
| C5 | 1 | 2026-10-04 | `python -m compileall -q -f .` exit 0 · `ruff check .` / `ruff format --check .` all checks passed, 785 files formatted · `mypy .` no issues in 460 source files · `bandit -r . -x ./.venv -c pyproject.toml` 0 High / 0 Medium / 41 Low · bare `pytest` **8214 passed, 3 skipped, 30 deselected** · coverage **88.13%** (28 239 statements / 3 353 missed), gate 75% · **re-verified at HEAD `def9a5c`**: `test_runner.py` 175 passed, `test_app.py` 26 passed, `REFINERY_STAGES` verified as the five real `StageConfig` fields | Closes M12a, M12b, M13 and the hidden-parallel-flag agreement gap. **M12a:** the Refine tab's `_toggle_all` iterated the hand-typed list `["declick", "trim", "enhance", "normalise"]` while the arg builder's stage map and the pipeline have **five** stages, so Select-All silently never enabled Noise Reduction — and the user guide *already documented* the correct contract ("SELECT ALL changes all five stage selections together"), i.e. code-vs-guide drift. The stage list is now a single source of truth, `arg_builder.REFINERY_STAGES` (StageConfig field ↔ `--stages` name pairs), which `build_refinery_args` emits and `_toggle_all` iterates; verified at HEAD as `(declick, trim, enhance, normalise, reduce_noise)` — so a new stage cannot appear in one place and not the other. **M12b:** `build_refinery_args` emitted `_driver_display_flags(state.util_clear_logs_var, state.parallel_var)` while the Refine tab binds `state.clear_logs_var`, so the child's inert Run Controls panel displayed the **Utility** tab's Clear Logs state; the flag now reads the Refine tab's own binding (verified: `util_clear_logs_var` no longer appears in the function). **Hidden parallel flags (maintainer decision):** the Refine tab hides its Parallel checkbox (`app.py` hides `_parallel_btn` when `parallel_var is None` on that tab), so emitting `--parallel-run`/`--no-parallel-run` published a state the user could neither see nor change; the driver no longer emits either flag for Refinery and the child keeps its own default. The child's parser still accepts the flags, unchanged, for any other invocation path. **M13:** `build_refinery_args` rewrote an empty stage selection to the full default chain, so a user who turned every stage off got all of them re-enabled; `launch_refinery` already blocks a no-stages run *before* the args are built, so the branch was dead code carrying a surprising contract. Deleted — an all-off selection now emits `--stages ""`. **Test-suite defect correction:** `test_all_stages_default_when_none_enabled` asserted the silent fallback verbatim and so **pinned the M13 defect**; replaced with the positive contract plus a docstring recording that it had pinned a bug. **New regression coverage (+5 net):** the M13 all-off contract; a drift guard asserting every `REFINERY_STAGES` entry pairs a real boolean `StageConfig` field with its CLI name and that the set is exactly the five stages; a M12b test with both tabs' vars set to opposite values; the no-parallel-flags test with `parallel_var` both True and False; and `TestRefinerySelectAll` in `test_app.py` (+2) driving the real `_switch_tab("refine")` → captured select-all command to prove behaviourally that all five stage vars are set on select and cleared on deselect, `reduce_noise` included. **Negative controls (exact pre-fix expressions, each reverted after firing):** restoring the four-stage literal fails both select-all tests with `select-all missed stage 'reduce_noise'`; restoring the fallback fails with `assert 'declick,trim,...,normalise' == ''`; restoring `util_clear_logs_var` fails the follows-refine-var test; restoring `_driver_display_flags(...)` fails the no-parallel test. **Guide audit:** `user_guides/individual_programs/master_driver/generate_guide.py` already documents Select-All as covering all five stages and lists Clear Logs among the Refine tab's controls — the guide described the intended behaviour and the code had drifted from it, so no guide update was required and the `.docx` was not regenerated (no documented behaviour changed). **Out-of-scope observation (not changed here):** `tool_launcher.launch_refinery`'s no-stages guard also lists the five stage flags by hand; it is currently correct but is the same drift class, noted for a future item rather than expanding this diff. |
| C6 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` clean · `mypy .` 0 issues · targeted `pytest utilities/tests` 54 passed · full bare `pytest -q` + coverage re-run at C8 (see C8 row) · secret scan clean | Commit `ffe8382`. **Audit premise corrected empirically:** on the locked mutagen **1.47.0**, `VorbisComment`/`MP4Tags` have **no** `.add` (the `VCFLACDict`/`MP4Tags` mapping API exposes it, the tag objects do not), so `hasattr(audio.tags, "add")` never captured FLAC/MP4 and the `elif` branches were already reachable - the stated defect does not exist as written. The **real** live bug found while testing that branch was `Picture.description` vs mutagen's `Picture.desc`, which raised `AttributeError` on every FLAC with embedded art. Fixed both: narrowed to `isinstance(audio, MP3)` so intent is explicit, and corrected the field name. **Deliberate decision:** narrow on `isinstance(audio, MP3)` rather than "has `.add`" because mutagen *does* expose `.add` on AIFF's `_tags`/ID3 path, so a duck-type check would keep capturing AIFF and silently skip its `pictures`; the explicit class keeps AIFF on the ID3/APIC branch. Options chosen per the item's recommendation: **docstring corrected** (local `_sha256` is the reproduced value) and **caller catches `AudioSuiteError`** (covers future `AudioIOError` variants). `undo.py` uses `argparse.SUPPRESS` for the subcommand `--db` so a before/after position is honoured and the parent value is inherited when unspecified. Guide audit: `user_guides/reference/CLI_Commands_Reference.md` documented `--db` as non-functional - updated. **Negative controls (SHA-256-verified):** four reverts each failed the expected test. Note `utilities/` remains outside ruff/mypy `exclude`, so its coverage is not in the coverage table. |
| C7 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` 787 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium / 41 Low pre-existing · bare `pytest -q` **8257 passed, 3 skipped, 30 deselected** · coverage **88.13%** ≥ 75 (28 261 statements / 3 354 missed) · secret scan clean | Commit `d1b7aa2`. `_backup_existing_key` copies the bytes about to be replaced to `<key_file>.key.bak` **before** the new key is written, and never clobbers an existing backup (the first backup is the only useful one - later ones would capture already-broken keys). Messages distinguish the two cases: a **recoverable** copy ("the previous key is preserved at ..." - the user can restore it) from a **diagnostic** one ("kept for inspection"), and both state the re-entry consequence. `_key_regenerated` records that the session's key no longer matches what earlier sessions used. `decrypt_string`'s failure message names the concrete cause instead of a bare "could not decrypt". **Plan premise corrected:** there was **no** existing `*.key` gitignore glob (only `album_art_sync/*/album_art_config.json` and friends), so `*.key.bak` was added alongside the existing `.key` pattern - "extend the existing rule" was not literally possible. Guide audit: `user_guides/Security_Guide.md` documents the backup/recovery behaviour. **Negative controls (SHA-256-verified, restore from backup copy):** four reverts - backup suppressed, WARNING text weakened, consequence sentence dropped, decrypt message reverted - each failed the expected test; all restores SHA-identical. |
| C8 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` 788 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium / 41 Low (pre-existing) · bare `pytest -q` **8266 passed, 3 skipped, 30 deselected**, 245.43s · coverage **88.13%** ≥ 75 · secret scan clean (0 hits across the 41 staged files) | **Deviation (maintainer-approved):** the item names 13 modules; the source scan found **27** real `logging.getLogger(__name__)` call sites plus a deprecated function-local alias and two textual references. The maintainer chose "convert all 30 + fix cross-refs" over the strict 13, so 14 further modules were converted rather than left in the defect the item exists to remove. **Deviation:** the four `tag_helper_*` modules deliberately share one literal logger (`"audio_suite_shared.tag_helper_base"`, pinned by caplog); it became `"audio_suite.audio_suite_shared.tag_helper_base"` — the shared-subsystem grouping is preserved, and the pin constant was updated in lockstep. Also fixed: `tag_helper_writer.py`'s function-local `import logging as _log` (misleading — it was the module, not a logger) and `error_logger.py`'s docstring, which *recommended* the banned pattern. Five lockstep test pins updated (`test_dsp_chain`, `test_launcher`, `test_preflight`, `test_key_manager`, `test_tag_helper_base`) plus `silence_trimmer/tests/test_silence_trimmer.py`. **Finding:** `test_preflight.py`/`test_launcher.py` **cannot** detect a logger-name regression — they assert only `caplog.text` and caplog's handler sits on the *root* logger, so an ERROR record is captured whatever the module logger is named (their `logger=` argument only sets a level). The new AST invariant is the effective global lock; the old tests' name pins were cosmetic. **Negative controls (SHA-256-verified, restore from backup copy):** `secure_subprocess.py` → bare `getLogger(__name__)` fails 3 tests (AST invariant, import-time name, live capture); `tag_helper_mp3.py` → old shared literal fails `test_tag_helper_base`; `preflight.py` → bare fails the AST invariant. All restores SHA-identical. Guide audit: no guide or doc references `audio_suite.log` or the logger namespace, so no guide update was required. |
| C9 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` 788 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium / 41 Low pre-existing · bare `pytest -q` **8270 passed, 3 skipped, 30 deselected**, 219.48s · coverage **88.13%** ≥ 75 (28 265 statements / 3 354 missed) · secret scan clean | Decision **J2 resolved to honour `--end`** (the item's recommendation), so both tools now close on completion instead of logging an "ignored" WARNING. Full path traced before implementing: both apps have a **bespoke** handshake (`noise_reduction/app.py:253-254`, `pop_click_remover/app.py:222-223`) that writes **only** `auto_end_var`, and they define no `auto_end` attribute at all — which also makes the generic `cli_helpers` writer dead for them (`cli_helpers.py:386/604/635/741` are all guarded by `hasattr(self.app, "auto_end")`, which is False). Reading `auto_end_var.get()` is therefore both necessary and sufficient; adding an `auto_end` bool would have created a channel nothing writes. Note this is the **mirror image** of the earlier Key Detector defect recorded in `key_detector/tests/test_app.py:331-334` (that one consulted only the bool while the tab set the var). Neither app inherits `tool_app_base`, so its working `root.after(2000, self.root.destroy)` at `:308` never applied to them — the fix mirrors that line and the six honouring tools' 2-second delay, placed at the **end** of `_on_complete` so the audition caption and results tab are populated before the destroy. `_on_error` deliberately does **not** auto-close (the error dialog must be seen). Tests assert the **positive** contract (`root.after` called with `(2000, root.destroy)`), plus an ordering test that the caption is written before the close is scheduled; `_Call.args` is inspected explicitly per the Python 3.14 `_Call` trap. **Negative controls (SHA-256-verified, restore from backup copy):** deleting the two-line block from each app fails 2 tests apiece; all restores SHA-identical. Guide audit: neither `noise_reduction` nor `pop_click_remover` guide mentions Auto End or documents any CLI flags at all (unlike `tempo_analyzer`'s, which documents both), so there was no stale claim to correct — adding a CLI section is new documentation and out of C9's scope. |
| C10 | 1 | 2026-10-04 | compileall 0 · `ruff check .` clean · `ruff format --check .` 788 files formatted · `mypy .` 0 issues / 460 files · bandit 0 High / 0 Medium / 41 Low pre-existing · bare `pytest -q` **8280 passed, 3 skipped, 30 deselected**, 238.14s · coverage **88.13%** ≥ 75 · secret scan clean (staged-file scan 0 hits) | **Premise correction:** the first branch (`"trimmed" in action.lower() or "removed" in action.lower()`) could **never** fire — `trim_and_fade` only ever returns `"No silence detected"`, `"Would trim …"` or `"-Xms / -Yms"` (± `" + Fades"`), so every plain trim silently fell through to the generic `"audio structure optimized"` wording and only the fade branch ever ran. **Maintainer decision:** `TrimResult` exposed no structured fade flag, so the mapping could not be completed from `silence_trimmer`'s return type alone; `apply_fade: bool = False` was added as a **trailing field** of the frozen dataclass (additive + defaulted — all 9 existing construction sites use keywords, so no call site breaks) and is populated from the `apply_fade` argument, with the skip/dry-run paths keeping the False default. `_run_trim_stage` now branches on `tr_result.apply_fade` alone and `action` is display text only. Docs: the `:5` docstring chain and the `:157` UI subtitle now read declick → trim → **noise reduction** → enhance, matching the executed order at `:196-204` (both rewrapped to stay ≤88 chars); steps renumbered 0–9 with the duplicate "5" removed and the two off-style separators normalised. **Deviation:** the item names `audio_refinery/tests/test_pipeline.py`, which does not exist; per the one-test-file-per-module rule the tests went into the existing `test_pipeline_stages.py`. **Positive contract:** `TestRunTrim` drives a fixture whose `action` contains none of "trimmed"/"removed"/"fade" (`"-120ms / -340ms (opaque-9f2c telemetry)"`) and asserts the trim-specific wording, so message selection can only come from the structured fields; a companion test asserts the fade wording is selected by `apply_fade=True` even when `action` never mentions fades. `TestPipelineChainDocs` pins the docstring stage order and that the step comments number 0..N without duplicates. Producer-side, three `apply_fade` field tests were added to `silence_trimmer/tests/test_silence_trimmer.py`. **Negative controls (SHA-256-verified, restore from backup copy):** reverting `_run_trim_stage` to the substring match fails `test_plain_trim_message_comes_from_status_not_action_text`; dropping "noise reduction" from the docstring fails `test_docstring_chain_matches_executed_stage_order`; restoring the duplicate "5" fails `test_numbered_step_comments_are_unique_and_increasing`. All restores SHA-identical. Guide audit: `generate_guide.py` never repeats the chain (zero `→` / "Single-pass" / "pipeline order" strings) and its "Pipeline Stages" list already names the stages in the correct executed order (Pop & Click → Silence Trim → **Noise Reduction** → Enhancement → Export → Normalise → Finish); its only order-adjacent sentence states the *default* active stages, which C5 established as accurate — so no `.docx` regeneration was required. |
| E1 | 2 | | | |
| E2 | 2 | | | |
| E3 | 2 | | | |
| E4 | 2 | | | |
| F1 | 3 | | | |
| F2 | 3 | | | |
| F3 | 3 | | | |
| I1 | 4 | | | |
| I2 | 4 | | | |
| I3 | 4 | | | |
| I4 | 4 | | | |
| I5 | 4 | | | |

---

## Open Decisions

Only **I4** is decision-gated as new capability, and **I5** records a disposition
decision. Sprints 0–3 are fully specified and may be scheduled one at a time
without waiting for any decision. Two items carry an internal either/or that the
implementer should confirm with the maintainer at execution time (both are
recommendations in the item body, neither blocks the Sprint):

- **decision J1 (C1/M2)** — make the symlink branch real (recommended) or delete
  the control and its docstring. *Recommendation: make it real.*
- **decision J2 (C9/M20)** — honour `--end` in the two tools (recommended) or
  log an explicit "ignored" acknowledgement. *Recommendation: honour it.*

- **decision J3 (I2)** — approve or decline the `AudioSuiteV6` → versionless
  display-name rename (the `id` never changes).

Each decision carries a recommendation; the maintainer resolves it before the
corresponding item opens. Until then that item is `[!]`.
