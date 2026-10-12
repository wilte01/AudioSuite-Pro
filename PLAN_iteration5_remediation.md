# Independent Audit Remediation Plan — Iteration 5 — AudioSuite-Pro

**Source:** Independent engineering audit of commit `e729626` (2026-09-26).
21 findings, ordered by the audit's own severity ranking. Each is reproduced
below with the evidence that justifies it and mapped to exactly one staged item.
**Status:** Complete (2026-09-28) — all seven stages implemented and
evidence-recorded (Stages 0–4 on 2026-09-26/27; Stages 5–6 on 2026-09-28).
The single externally-blocked acceptance item is A4's first-run CI evidence
(no git remote on the development host — named re-open condition in the A4
Completion Log row). All follow-on work is split to
`PLAN_iteration6_followups.md` per the Plan Close-Out Checklist.
All five open decisions (D1–D5) resolved by the maintainer (Wilte) on
2026-09-26 in favour of the recommended options — see the Decision Log.
**Last Updated:** 2026-09-28 (plan close-out — retrospective filled,
close-out checklist ticked, audit index checked off item by item)
**Scope:** All 21 audit findings, delivered as seven independently shippable
stages. Nothing in this plan is authorized for implementation until the open
decisions in the *Open Decisions* section are resolved by the maintainer.
**Baseline gate at `e729626`:** 6,978 passed / 5 skipped, coverage 78.26%,
`ruff check` clean, `mypy --strict` clean over 448 source files, bandit
0 High / 0 Medium / 51 Low.
**Governing plan:** this file. `PLAN_audit_remediation.md`,
`PLAN_iteration2/3/4_remediation.md` and `PLAN_audit_priority_actions.md` are
historical records (all items COMPLETE/DONE) and are **not** reopened by this
plan. Where this plan fixes a defect that a completed plan introduced, the
defect is recorded here, not by editing the historical file.

---

## How to read this plan

Every staged item uses the same six fields:

- **Priority / Effort / Risk** — sequencing input, not a promise.
- **Problem** — the finding, restated with a file:line or command reference.
- **Scope** — the exact edits. Checkboxes are the work units; tick on commit.
- **Tests (lockstep)** — the tests written in the *same* change, per AGENTS.md
  §7. No item ships without them.
- **Acceptance** — the command output that closes the item.
- **Risks** — what this item could break, and the guard already in place.

**Per-item gate (mandatory, item A6):** an item is complete only when its
Completion Log row carries **Gate Evidence** — the date, the six Phase Gate
commands, and their pass/coverage counts — recorded **per item, not per
stage**. A row without Gate Evidence is, by definition of the table, an
incomplete item. This rule exists because iteration 4 recorded an item as
complete without re-running its plan gate (see the Decision Log entry
"iteration-4 D1 precedent"); with six stages and 21 items, the same gap
would otherwise repeat 21 times.

**Naming convention:** plan items are `A1`–`G2`, one letter per stage. The five
open decisions are `D1`–`D5`, which collides with Stage 3's `D1`/`D2`/`D3`
item IDs. Where that happens the decision is always written in full — "decision
D1 (licence)", "decision D3 (coverage threshold)" — and a bare `D1`/`D3` in
Stage 3 always means the *item*.

**Hard rules inherited from `AGENTS.md`** and repeated here because they are
the ones most likely to be violated by a large multi-stage plan:

- Minimal diff. No refactoring outside the item's stated scope. If a
  refactor looks necessary, it is a new plan item with the user's approval.
- A defect discovered while implementing an item is fixed in the same change,
  with a regression test, and recorded in this plan's Completion Log.
- New third-party dependencies require explicit user approval (see D2).
- The final gate is a **bare full-suite** `pytest` run (package-scoped runs
  silently skip suites that are not in `pyproject.toml` `testpaths`).
- The compile/import gate is mandatory after any edit to an import chain.

---

## Phase Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]`  | Not started |
| `[-]`  | In progress |
| `[x]`  | Completed |
| `[~]`  | Partially completed |
| `[!]`  | Blocked — needs a maintainer decision |

---

## Audit Finding Index

Severity is the audit's own rating. "Stage" is where this plan places the
remediation. Every number appears exactly once across all stages. The
"Closed" column is the per-finding close-out state, checked off item by item
at plan close (2026-09-28); finding #4's `[~]` mirrors A4's pending
first-run CI evidence (named re-open condition in the A4 row).

> **Post-close supersession (2026-09-29, maintainer Wilte) — finding #4.**
> A4's re-open condition was carried as item A1 of
> `PLAN_iteration6_followups.md` and has been **withdrawn as not required**:
> there is no UNIX/Linux environment for this project, so the Linux leg is
> never executed and its run-URL/passed-count evidence can never be produced.
> Finding #4 therefore stays `[~]` in this frozen plan — closed as *not
> applicable*, deliberately **not** flipped to `[x]`, which would falsely
> claim the leg was verified. A4's CI configuration (matrix, `xvfb`,
> `python3-tk`, `ffmpeg`) is left in place unchanged. The decision is
> recorded in full at `PLAN_iteration6_followups.md` §A1; this note exists
> only so the index does not point at an item that will never be worked.

| # | Finding (abridged) | Severity | Stage | Closed |
|---|--------------------|----------|-------|--------|
| 1 | `ruff format --check .` fails on tracked Markdown | Medium | 0 | `[x]` A1 |
| 2 | `noise_reduction` absent from `testpaths` and coverage `source` | High | 0 | `[x]` A2 |
| 3 | `genre_sync/tests/conftest.py` calls `pytest.skip()` in `pytest_configure` | High | 0 | `[x]` A3 |
| 4 | Linux CI leg has no display, no Tk, no ffmpeg — the leg proves nothing | High | 0 | `[~]` A4 |
| 5 | `batch_analysis_engine._run_process_pool` multiprocessing path untested | High | 1 | `[x]` B1 |
| 6 | `ffmpeg` is an undeclared hard runtime dependency | High | 0 | `[x]` A5 |
| 7 | Key detection is locked to static Krumhansl-Schmuckler profiles | Medium | 5 | `[x]` F2 |
| 8 | Near-verbatim `app.py` GUI scaffolds (94.2% pair) | Medium | 2 | `[x]` C1 |
| 9 | Near-verbatim `core/file_processor.py` twins (70.9% pair) | Medium | 2 | `[x]` C2 |
| 10 | No README / quick start / architecture overview | Medium | 4 | `[x]` E1 |
| 11 | No LICENSE and no `license` metadata despite GPL-incompatible deps | High | 4 | `[x]` E2 |
| 12 | Phase gate skipped after a "complete" item (iteration-4 D1 precedent) | High | 0 | `[x]` A6 |
| 13 | `tool_plugin._build_default_registry()` is a ~300-line literal builder | Medium | 2 | `[x]` C3 |
| 14 | `integration` / `hardware` markers registered but never deselected | Medium | 3 | `[x]` D1 |
| 15 | `analysis_loader` — the shared decode path — at 34.3% coverage | High | 1 | `[x]` B2 |
| 16 | `ffmpeg_finder` discovery fallbacks untested | Medium | 1 | `[x]` B3 |
| 17 | Coverage `exclude_lines` hides untested optional-dependency branches | Medium | 3 | `[x]` D2 |
| 18 | Blanket session-wide GUI skip can zero the whole suite silently | High | 1 | `[x]` B4 |
| 19 | Analysis family has no measured-outcome / golden-vector tests | High | 5 | `[x]` F1 |
| 20 | Platform-specific paths with no verified support matrix | Medium | 6 | `[x]` G1 |
| 21 | No discoverability surface: no changelog, no `audiosuite --help` contract | Low | 6 | `[x]` G2 |

Stage totals: Stage 0 = 6 items, Stage 1 = 4, Stage 2 = 3, Stage 3 = 2,
Stage 4 = 2, Stage 5 = 2, Stage 6 = 2 → **21**.

---

## Open Decisions (all five resolved 2026-09-26 — recommended options accepted)

These are genuine forks, not implementation details. Each carried a
recommendation; the maintainer resolved all five on 2026-09-26 by accepting
the recommended option in each case (D1: GPL-3.0 · D2: self-contained ·
D3: hold 75 · D4: `xvfb` + real tests · D5: declared matrix + portable core).
The full rationale for each resolution is recorded in the Decision Log.
The original analyses are preserved below unchanged, as the record of what
was weighed.

### D1 — Project licence `[x]` (resolved: GPL-3.0)

**Question:** The repository has no `LICENSE` file and `[project]` in
`pyproject.toml` declares no `license`. Dependencies are GPL-incompatible in
places: `pedalboard` is GPL-3.0, `librosa`/`soundfile` and the `numba` stack
are Apache-2.0/BSD, `winaccent` is MIT, and the research for the key-detection
upgrade (D2) surfaced AGPL options. The suite currently has no stated licence,
which is a legal gap, not a style gap.

| Option | Effect |
|--------|--------|
| **A. GPL-3.0 (recommended)** | Compatible with `pedalboard`'s GPL-3.0 and with AGPL-composition needs. Matches the heaviest dependency. Requires a `LICENSE` file, `[project] license` metadata, and per-file headers only if a contributor asks. |
| B. MIT | Maximum adoption, but distributing a GPL-3.0 binary dependency (even unmodified) is not compatible. Only viable if `pedalboard` is dropped. |
| C. No licence (status quo) | Everyone downstream has no rights. Defensible only as a deliberate private-work stance. |

**Blocks:** item 11 (Stage 4), and the distribution story in Stage 6.
**Recommendation recorded in the Decision Log as provisional**; the maintainer
must confirm before Stage 4 opens.

### D2 — Key-detection engine strategy `[x]` (resolved: self-contained)

**Question:** `key_detector/core/key_engine.py` correlates chroma against
static Krumhansl-Schmuckler major/minor profiles. The audit rated this an
accuracy ceiling, and Stage 5 wants it improved.

Empirical research result (this supersedes an earlier claim in the audit
discussion that `madmom` is MIT and wheel-installable — it is not):

| Candidate | Licence | Packaging reality | Verdict |
|-----------|---------|-------------------|---------|
| **Self-contained profile-correlation upgrade (recommended)** | First-party | No new dependency; pure `numpy` | Fits the existing architecture, no licence change, testable in isolation. |
| `madmom` | BSD **plus CC BY-NC-SA models** | **sdist only — no wheel**; needs Cython at build time; failed to install on the project's Python 3.14.7 with `ModuleNotFoundError: No module named 'Cython'` | Rejected: the non-commercial model licence conflicts with a GPL-3.0 distribution, there is no wheel, and the build chain is fragile. |
| `essentia` | **AGPL** | Wheels for CPython ≤3.12 | Rejected: AGPL-3.0 cannot be linked into a GPL-3.0 (non-AGPL) distribution, and the wheel matrix does not reach the project's Python floor. |

**Blocks:** item 7 (Stage 5). Item 19 (measured-outcome tests) is *not*
blocked — it can be written against the current engine first, which also gives
the upgrade a correctness lock before it is attempted.

**Recommendation:** option A, self-contained. No new dependency, so D1 does
not have to be resolved first.

### D3 — Coverage threshold `[x]` (resolved: hold 75)

**Question:** `fail_under = 75` in `[tool.coverage.report]`. Once item 2
stops hiding a whole package and item 17 stops hiding optional-dependency
branches, the measured number will move — in which direction is not yet known,
because the exclusions were masking untested code.

| Option | Effect |
|--------|--------|
| **A. Hold 75, never lower (recommended)** | Honest. The gate may fail for a while during Stages 1–3; that is the point — the exclusions were the lie. Item 4's GUI work is what will move it. |
| B. Raise to 80 immediately | Will fail until Stages 1–3 complete; blocks independent shipping. |
| C. Lower to match the new number | Re-institutionalises exactly the finding the audit raised. |

**Blocks:** nothing structurally; Stage 0 must record whichever is chosen
*before* the first full-suite run, so the first honest number is measured
against a fixed gate.

**Recommendation:** option A.

### D4 — Linux CI strategy `[x]` (resolved: xvfb + real tests)

**Question:** Item 4's fix is `xvfb` + system packages, but the suite's GUI
tests are skipped wholesale on headless hosts (item 18), so the Linux leg can
pass while testing almost nothing.

| Option | Effect |
|--------|--------|
| **A. `xvfb` + `tk` + `ffmpeg`, and platform-skips only where genuinely inapplicable (recommended)** | The Linux leg actually exercises the ~6,978 tests, and any platform-only gap (drive letters, `icacls`) is an explicit, reviewed skip rather than a silent one. |
| B. Drop the Linux leg, keep Windows-only CI | Honest but loses the only non-Windows signal; every `sys.platform` branch stays unverified. |
| C. Keep the leg, keep the blanket skip | The current state. Rejected — it is item 4. |

**Blocks:** item 4 (Stage 0).

**Recommendation:** option A.

### D5 — Cross-platform scope `[x]` (resolved: declared matrix + portable core)

**Question:** Item 20 asks how far "cross-platform" reaches. The suite has
Windows-only subsystems (`icacls` ACL hardening, drive-letter handling in
`cd_ripper`, `STARTUPINFO` console suppression) alongside platform-neutral
DSP.

| Option | Effect |
|--------|--------|
| **A. Document + verify a support matrix; make the *core* CLI-first paths portable first (recommended)** | Bounded, testable, and delivers real value; the Windows-only subsystems are declared as such rather than silently untested. |
| B. Full macOS parity | Multi-week scope, touches every subprocess site. Not a 21-finding remediation. |
| C. Document Windows-only and stop | Cheapest, but leaves Stage 6 with no code change and the `sys.platform` branches permanently unverified. |

**Blocks:** item 20 (Stage 6).

**Recommendation:** option A.

---

---

## Stage 0 — Restore Trust in the Gates and Declare the Runtime

**Rationale:** six of the highest-severity findings are not code defects, they
are *measurement* defects — the suite reports green (or 78.26%) while omitting
a package, skipping a whole leg, and skipping itself. Nothing else in this plan
can be verified until these are fixed, and every later stage's acceptance
evidence is produced by these gates. Stage 0 therefore ships first and alone.

**Stage gate:** after this stage, `ruff format --check .` is clean,
`noise_reduction` contributes to coverage, the Linux CI leg runs real tests,
`ffmpeg`'s absence fails loudly, and a completed item cannot be recorded
without gate evidence.

---

### A1 [x] — Stop `ruff format` from linting Markdown `[audit #1]`

**Priority:** Medium | **Effort:** 0.05 day | **Risk:** Low

**Problem:** `ruff format --check .` fails on
`PLAN_audit_priority_actions.md`. Ruff formats Python code blocks it finds in
Markdown by default, and CI's lint job (`.github/workflows/ci.yml:20`) runs
`ruff format --check .` across the tree — so a *documentation* file fails the
lint gate. The consequence is worse than a red line: a project-wide gate that
is expected to fail gets ignored, and a maintainer who later "fixes" it by
running `ruff format .` will reformat the content of a completed plan's
historical record.

**Empirically verified fix.** Adding

```toml
[tool.ruff.format]
exclude = ["*.md"]
```

to `pyproject.toml` makes `ruff format --check .` pass. Do **not** use the
CLI form `--exclude "*.md"`: it *replaces* Ruff's default exclusions rather
than adding to them, so it re-admits `.venv` and the run either becomes
unusably slow or fails on third-party source.

**Scope:**

- [x] Add `exclude = ["*.md"]` under the existing `[tool.ruff.format]` block
      in `pyproject.toml` (which currently holds only `quote-style`).
- [x] Do **not** reformat any `PLAN_*.md` file, and do not touch
      `PLAN_audit_priority_actions.md` — it is a historical record.

**Tests (lockstep):** none required (configuration-only). Verification is the
acceptance command below, which must exit 0.

**Acceptance:**

- `python -m ruff format --check .` → exit 0, no files listed.
- `python -m ruff check .` → unchanged, still clean.

**Risks:** if a Python code block inside a doc is later meant to be
format-checked, it needs an explicit `ruff format <file.py>`. Documented here
so the gap is a decision, not a surprise.

---

### A2 [x] — Put `noise_reduction` back under measurement `[audit #2]`

**Priority:** High | **Effort:** 0.1 day | **Risk:** Low

**Problem:** `noise_reduction` is missing from **both**
`[tool.pytest.ini_options] testpaths` and `[tool.coverage.run] source` in
`pyproject.toml`. The package is fully git-tracked and has a real test suite —
`noise_reduction/tests` contains **88 passing tests** when invoked explicitly —
but a bare `pytest` run never collects them, and its ~1.2k lines of production
code never enter the coverage denominator. This is the single most consequential
finding in the audit: the headline 78.26% is computed over a source list that
silently omits a whole package, and `noise_reduction`'s tests are dead weight
in CI that no gate ever runs.

**Scope:**

- [x] Add `"noise_reduction/tests"` to `testpaths` (insert alphabetically,
      between `mood_analysis_batch_tagger/tests` and
      `music_format_converter/tests`).
- [x] Add `"noise_reduction"` to `[tool.coverage.run] source` (same slot).
- [x] Run the bare full suite. The 88 new tests must be collected and pass.
- [x] Record the new honest coverage number before touching D3 — the first
      post-A2 number is the baseline every later stage is judged against.
      (Recorded: 78.04%, down from 78.26% — see Completion Log.)

**Tests (lockstep):** the 88 existing tests are the lockstep check; no new
tests are needed because the change is a *measurement* change. If any of the
88 fail when finally collected, that is a **defect discovered in working
code**: fix it in this same change with a regression test and log it.

**Acceptance:**

- `python -m pytest -q --collect-only noise_reduction/tests` → 88 tests.
- Bare `python -m pytest -q` → test count increases by 88, all passing.
- `python -m pytest -q` coverage output now lists a `noise_reduction` row.

**Risks:** the newly-included package will almost certainly report below the
suite average, so the overall percentage may drop. That drop is the correct
outcome — see D3.

---

### A3 [x] — Remove the `pytest.skip()` inside `pytest_configure` `[audit #3]`

**Priority:** High | **Effort:** 0.05 day | **Risk:** Low (crashes a leg)

**Problem:** `genre_sync/tests/conftest.py:17-24` bootstraps its own hidden Tk
root and, on `tk.TclError`, calls `pytest.skip("No display available …")`
from inside `pytest_configure`. The root `conftest.py:49-66` documents exactly
why that is wrong: calling `pytest.skip()` from `pytest_configure` raises
`INTERNALERROR` and pytest exits with **code 3**. It is not a skip — it is a
crash. On a headless host (any Linux CI runner without `xvfb`) this takes the
entire session down, not just `genre_sync`.

The package-level file is also redundant: root `conftest.py` already creates
the session root and already skips when it is absent, and the session-scoped
`root` / `tk_root` fixtures are already provided there. `genre_sync`'s own
`root` fixture shadows the shared one with a module-global that only its own
`pytest_configure` ever sets.

**Scope:**

- [x] Delete `genre_sync/tests/conftest.py:14-39` — the module-global `_root`,
      its `pytest_configure`, its `pytest_unconfigure`, and its local `root`
      fixture. The shared root `conftest.py` provides both fixtures and the
      skip behaviour, so the package file becomes fixtures-only
      (`mock_tk_app` and its helpers) with no Tk bootstrap at all.
- [x] Keep `mock_tk_app` and every helper it depends on byte-identical.
- [x] Re-run the `genre_sync` suite; `mock_tk_app` must be unaffected because
      it patches `tk` module-wide and never touches the real root.

**Tests (lockstep):** no new test file is warranted — the lock is the
`genre_sync` suite itself plus the headless simulation below, which is run
manually as part of acceptance.

**Acceptance:**

- `python -m pytest -q genre_sync/tests` → all pass, exit 0.
- Headless simulation: with `tk.Tk` forced to raise `tk.TclError`, a bare
  `python -m pytest -q` exits **0** with skips, never 3.
- `grep -rn "pytest.skip" */tests/conftest.py` → no matches.

**Risks:** low. If any `genre_sync` test was relying on its private `_root`
global rather than the fixture, that test now resolves the shared root — which
is the intended consolidation, and the suite passing proves it.

---

### A4 [~] — Give the Linux CI leg a display, Tk, and ffmpeg `[audit #4]`

**Priority:** High | **Effort:** 0.2 day | **Risk:** Medium
**Blocked on:** D4 (recommendation: option A)

**Problem:** the `test` job matrix in `.github/workflows/ci.yml:58-73` runs
`ubuntu-latest` alongside `windows-latest` and does exactly one install step,
`uv sync --extra dev --extra analysis --extra cd-ripping`. On `ubuntu-latest`
that means:

- No display → root `conftest.py` sets `_root = None` → **every** collected
  test is marked skipped (except where A3 has not yet landed, in which case the
  session crashes with exit 3).
- No `python3-tk` → `tk.Tk()` fails for a second, independent reason.
- No `ffmpeg` → the 273 `integration`-marked tests would fail rather than
  skip, unless item A5's handling is also in place.

So the Linux leg either crashes, or passes while running almost nothing — and
it still enforces `--cov-fail-under=75` against a near-empty run. That is a
green check that carries no information, which is precisely the class of
defect this stage exists to remove.

**Scope:**

- [x] Add to the `test` job, before `uv sync`:
      `sudo apt-get update && sudo apt-get install -y python3-tk ffmpeg xvfb`
      (as a `runner.os == 'Linux'`-gated step, so the Windows legs are
      unaffected).
- [x] Run the suite under a virtual display. Two viable forms; pick one and
      record it in the Decision Log: **`xvfb-run -a`** chosen (see Decision
      Log) over `DISPLAY=:99` + background `Xvfb` — no process to clean up
      and the child's exit status is preserved.
- [x] Keep `--cov-fail-under=75` in the matrix step (do not relax it here —
      D3 governs).
- [x] Split the marker handling so `integration` tests run where ffmpeg exists
      and `hardware` tests skip where no optical drive exists: **deferred to
      Stage 3 item D1 by this item's own instruction** ("the exact mechanism
      is item B1 (Stage 3), and this item must not preempt it"). What A4
      contributes is the ffmpeg binary itself, now present on the Linux leg.
- [~] Verify the Linux leg locally if possible; otherwise the change is
      validated by the first CI run, and the run URL goes in the Completion
      Log before the item is marked complete. **Not locally verifiable** —
      this is a Windows host and the repository has no git remote, so no CI
      run can be triggered from here. The workflow YAML is syntax-validated
      (parsed + bash `-n` checked) and the bash branch logic reviewed, but
      the item stays `[~]` until the first CI run's URL and the Linux passed
      count are recorded in the Completion Log.

**Tests (lockstep):** none in-repo (infrastructure). The gate is the CI run.

**Acceptance:**

- First post-merge CI run: the `ubuntu-latest` legs report a passed-test count
  comparable to `windows-latest` (order 10^3, not 10^0/10^1).
- Skip reasons in the Linux log are individually attributable — no blanket
  "No display available" mass-skip.
- The Completion Log records the run URL and the Linux passed count.

**Risks:** system packages make the job slower and cache-less; acceptable. A
real risk is a *latent* platform failure surfacing for the first time — that is
the point of the item, and any genuine defect found here is fixed in this same
change with a regression test (AGENTS.md §7), or the leg is narrowed with an
explicit, reviewed skip.

---

### A5 [x] — Make the undeclared `ffmpeg` dependency real and fail-fast `[audit #6]`

**Priority:** High | **Effort:** 0.35 day | **Risk:** Medium

**Problem:** `ffmpeg` is invoked by **221 call sites across 35 production
files** and is not declared anywhere in `pyproject.toml` — the only match for
"ffmpeg" in the whole file is the `integration` marker *description*
(`pyproject.toml:170`). The suite is therefore uninstallable-but-nonfunctional
by default: `uv sync` succeeds, `audiosuite` imports, and every tool that
shells out to ffmpeg fails at first use with a raw `FileNotFoundError` or an
opaque non-zero exit. There is also no preflight check, so the failure appears
only when a user processes a file.

**Scope:**

- [x] Extend `audio_suite_shared/preflight.py` (the module the `.pyw`
      launchers already call via `guard_or_exit()`) with an
      **ffmpeg/ffprobe presence check**, reported through the existing dialog
      path. Keep the function pure (no Tk side effects) per the
      `AGENTS.md` "Startup Pre-Flight Guard" rule, and keep it
      unit-tested in `audio_suite_shared/tests/test_preflight.py`.
      (New: `report_missing_requirements()` + `WARNING_TITLE`; purity proven
      by a subprocess test that shadows `sys.modules['tkinter']`.)
- [x] Add a single machine-readable **system requirement** declaration rather
      than a Python dependency — `ffmpeg` is an external binary, so
      `[project.dependencies]` is the wrong place. Implemented as
      `audio_suite_shared/system_requirements.py` (frozen dataclass table +
      plain-text install hints), referenced from `pyproject.toml` as a
      documented block, and quoted verbatim in the user guides.
- [~] Reuse the existing discovery helper rather than re-implementing: the
      `ffmpeg_finder` module already resolves the binary. **Deviation, recorded
      in the Decision Log:** `ffmpeg_finder` was *not* reused because (a) it
      lives in a tool package (`audio_normalizer`), and importing it from
      `audio_suite_shared.preflight` — the module every `.pyw` launcher runs
      before any tool import — would invert the base→tool layering and drag a
      tool package into every launch; and (b) its contract returns the bare
      string `"ffmpeg"` on miss, so it cannot answer the presence question the
      preflight needs. Instead the presence check uses stdlib `shutil.which`
      behind an injectable `resolver` parameter (defaulting to `shutil.which`,
      asserted by test), so B3 can later point a richer discovery mechanism at
      the same seam without re-implementing the presence logic. Its untested
      fallback branches remain item B3's scope, untouched here.
- [x] Make the failure message actionable: name the binary, the platforms that
      provide it (`winget install Gyan.FFmpeg`, `apt install ffmpeg`,
      `brew install ffmpeg`), and link to nothing that could rot — plain text
      install commands only. (Enforced by test: hints must contain no `http`.)
- [x] Pair with A4: the CI `integration` tests then have a real binary to find.
      (A4 installs ffmpeg on the Linux leg. The Windows legs are unchanged:
      whether that runner image ships ffmpeg is a property of the image, and
      the first post-A4 CI run records the Windows behaviour too.)

**Tests (lockstep):**

- [x] `audio_suite_shared/tests/test_preflight.py`: ffmpeg present → no
      warning; ffmpeg absent → the report lists the missing binary and the
      install hint; a *missing* ffprobe while ffmpeg exists is reported
      separately (the suite's `run_secure_subprocess` allowlist already treats
      ffmpeg/ffprobe as a pair).
- [x] Assert the preflight stays **pure**: calling it must not construct a Tk
      widget and must not import `tkinter`'s GUI layer. (Subprocess test:
      `sys.modules['tkinter'] = None` makes any such import raise; a negative
      control proved the shadowing genuinely blocks the import.)

**Acceptance:**

- `git grep -n "ffmpeg" pyproject.toml` → the only matches are the marker
  description and the new documentation reference.
- On a machine with ffmpeg removed from `PATH`, launching a `.pyw` shows a
  clear dialog naming `ffmpeg`; with it present, nothing changes.
- `preflight` tests green; the compile gate passes.

**Risks:** a preflight failure that blocks launch is a behaviour change for
users who only want to run, say, the tag editor. The check must therefore be a
**warning-level report, not a hard exit** — only the existing compile gate
keeps its blocking semantics.

---

### A6 [x] — Make a "completed" item impossible to record without gate evidence `[audit #12]`

**Priority:** High | **Effort:** 0.1 day | **Risk:** Low

**Problem:** the Iteration-4 plan's own Decision Log records the precedent
verbatim: D1 was marked complete and the note says *"the D1 plan gate was not
re-run before marking 'complete' — that gap is exactly what the iteration-5
audit surfaced; reasserting the gate after each sprint is now mandatory."*
The remediation was written down and then not enforced, which is how the
finding became a finding. With six stages and 21 items, the same gap would be
repeated 21 times.

**Scope:**

- [x] Add a mandatory **Gate Evidence** column to this plan's Completion Log
      (template already included below): date, the six gate commands, and the
      pass counts, per item — not per stage.
- [x] Record the iteration-4 D1 precedent in this plan's Decision Log as
      context, and do **not** edit `PLAN_iteration4_remediation.md` (historical
      record).
- [x] State the per-item gate in the *How to read this plan* section, so the
      rule is visible before the first item, not discovered after the sixth.

**Tests (lockstep):** none (process). The enforcement is structural: an item
row without Gate Evidence is incomplete by definition of the table.

**Acceptance:**

- The Completion Log table has a `Gate Evidence` column and no row can be
  filled without running the gate.
- A maintainer reading only the Completion Log can see, per item, which gate
  run authorised the claim.

**Risks:** none. This is a documentation/process change and is the cheapest
item in the plan relative to its value.

**Stage 0 note:** A6 is a template change, not code, but it belongs in Stage 0
because every later stage's evidence trail depends on the rule existing first.

---

---

## Stage 1 — Cover the Untested Logic That Actually Runs

**Rationale:** Stage 0 made the numbers honest. These four items are where the
honest numbers are lowest, and three of them are on paths that run in normal
use — the mood batch tagger's process pool, the shared decode helper every
analysis tool depends on, and the ffmpeg discovery that A5 now calls. The
fourth closes the mechanism that let A3/A4 hide.

**Stage gate:** `_run_process_pool`, `analysis_loader`'s decode path, and
`ffmpeg_finder`'s fallbacks are all covered by executed tests, and the blanket
GUI skip is replaced by a loud, bounded failure mode.

---

### B1 [x] — Test the mood batch tagger's process-pool path `[audit #5]`

**Priority:** High | **Effort:** 0.5 day | **Risk:** Medium (test design)

**Problem:** `mood_analysis_batch_tagger/core/batch_analysis_engine.py:522-674`
implements `_run_process_pool` — the `multiprocessing` branch of the batch
runner, including worker dispatch, result collection, progress callbacks, and
error mapping. It is **never executed** by the suite: the tests drive the
thread-pool path only. This is the highest-risk untested region in the
codebase, because a process pool is exactly where pickling errors, spawn
method mismatches, and callback-signature mistakes hide — and a mood
tag written from a corrupted worker result is a silent data-quality defect,
not a crash.

**Scope:**

- [x] Read the full call chain first: the public entry that chooses between
      the thread and process paths, the arguments handed to the pool, and the
      worker function's picklability. A test that mocks away the chooser tests
      nothing (AGENTS.md §9).
- [x] Add `mood_analysis_batch_tagger/tests/test_batch_analysis_engine.py`
      cases that execute the real process pool on a small input set:
      - happy path — N inputs, N results, correct ordering, progress callback
        invoked once per completed item;
      - a worker that raises — assert the error is *mapped and reported*,
        not propagated, and that the remaining items still complete (the same
        contract `BaseFileProcessor.process_batch` guarantees, per the
        Iteration-4 B0 work);
      - worker picklability — assert the worker callable is a module-level
        function, not a closure, on a platform whose default start method is
        `spawn` (Windows/macOS), because a closure is unpicklable there.
- [x] Where a genuine platform constraint makes real multiprocessing
      untestable in-process, mark the skip with a reason that names the
      constraint — never a bare `@pytest.mark.skip`. **No skip was needed:**
      real `ProcessPoolExecutor` dispatch runs on this Windows host.
- [x] **Do not** refactor the engine while testing it. If the tests reveal a
      defect, fix that defect with its regression test in this same change and
      log it; any structural cleanup is a separate item with approval.

**Tests (lockstep):** the file above. Coverage for the pool branch must move
from 0% to a real number, recorded in the Completion Log.

**Acceptance:**

- `python -m pytest -q mood_analysis_batch_tagger/tests` → the process-pool
  tests execute (not skipped) on Windows and are visibly run, not collected
  and short-circuited.
- The Completion Log records the before/after coverage for
  `batch_analysis_engine.py`.
- A forced worker exception yields a logged, mapped result and the batch
  completes — proven by the regression test, not by inspection.

**Risks:** real multiprocessing tests are the flakiest thing in a suite like
this. Keep the input set tiny (2–3 items), keep timeouts generous, and prefer
`spawn`-safe module-level workers. If flakiness appears, the *test* is what
gets fixed — never weaken the assertion to make it green.

---

### B2 [x] — Cover `analysis_loader`'s decode path `[audit #15]`

**Priority:** High | **Effort:** 0.4 day | **Risk:** Low

**Problem:** `audio_suite_shared/analysis_loader.py` (112 lines) sits at
**34.3%** coverage — by far the weakest point in a module every analysis tool
depends on. It is the shared helper that loads and decodes audio for the
analysis family, so an untested branch here is an untested branch in BPM
detection, key detection, tempo analysis, and mood analysis at once. Low
coverage on a *shared seam* is worse than low coverage on a leaf: the bug
propagates.

**Scope:**

- [x] Enumerate the uncovered lines first (`pytest --cov=audio_suite_shared
      --cov-report=term-missing`) and identify which are reachable. Baseline
      missing set: `56-86, 102-103, 119-124, 140-141` — all reachable.
- [x] Add `audio_suite_shared/tests/test_analysis_loader.py` covering:
      - the nominal path for each supported input form the loader accepts;
      - the failure paths — missing file, unreadable/corrupt file, and an
        unsupported or empty stream — each asserting the *specific* exception
        type the callers already catch, not a generic `pytest.raises`;
      - any resampling/mono-downmix branch, verified on real audio.
- [x] Per AGENTS.md §7, at least one case must decode a **real** generated
      audio file and assert a measured property (sample count, channel count,
      duration) rather than only asserting that a call happened.
- [x] If an uncovered branch turns out to be dead code, say so explicitly in
      the Completion Log and propose removal as a follow-up item — do not
      delete it here.

**Tests (lockstep):** the new file above. Target: branch coverage on the
reachable paths of the loader, and the module's number materially above 34.3%.

**Acceptance:**

- `analysis_loader.py` coverage recorded before/after in the Completion Log.
- `python -m pytest -q audio_suite_shared/tests` green, and the loader's
  consumers (key/bpm/tempo/mood) still pass unchanged.

**Risks:** a shared helper is high fan-out — a test that pins behaviour
incorrectly will fight four downstream tools. This is why the tests must
assert *measured* outcomes and the *existing* exception contract, not a
re-specification of what the loader ought to do.

---

### B3 [x] — Test `ffmpeg_finder`'s discovery fallbacks `[audit #16]`

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `audio_normalizer/utils/ffmpeg_finder.py` (42 lines) is the
resolver A5's new preflight check depends on, and its fallback branches are
untested. It is the single point of failure for the newly-declared external
dependency: if discovery returns the wrong path or a stale cached path, every
ffmpeg-backed tool breaks in a way that is hard to trace back here.

**Scope:**

- [x] Add `audio_normalizer/tests/test_ffmpeg_finder.py` (extend the existing
      file if one exists — check first, and do not create a second test module
      for the same source module, per `AGENTS.md` "Test File Naming").
      **Extended, not duplicated:** the file existed but tested
      `audio_suite_shared.subprocess_utils.get_startupinfo` and **zero** lines
      of `ffmpeg_finder.py` — which is why the module sat at 44%. The existing
      `TestGetStartupinfo` class is preserved verbatim.
- [x] Cover: binary present on `PATH`; found via an explicit configured path;
      not found anywhere; a configured path that no longer exists (stale
      cache); a configured path that exists but is not executable; and the
      platform-conditional branches (`sys.platform` splits) via monkeypatched
      platform values rather than real platform differences.
      **Three of these six describe a module that does not exist — see the
      Notes column.** What the real 51-line module has is covered: all three
      discovery sources, both `sys.platform` splits of the binary name, the
      `sys.frozen` split of the base directory (with a negative control), and
      the miss.
- [x] Pin the **failure contract** the preflight (A5) and the callers rely on:
      what the finder returns when nothing is found, and whether it caches.
      If a cache exists, test that an invalidated entry is re-resolved.
- [x] Per AGENTS.md §7, follow the mock-patch rule: if the code imports the
      name inside the function body, patch the *source* module; if the import
      is module-level, patch the *importing* module's binding. Verify which
      applies before writing the patch targets. **Verified:** `os`, `shutil`
      and `sys` are all module-level imports, so every target is
      `audio_normalizer.utils.ffmpeg_finder.<name>`. Because those bindings
      *are* the real `os`/`shutil`/`sys` module objects, `monkeypatch`
      (auto-restoring, teardown-on-failure) is used throughout instead of
      `unittest.mock.patch`.

**Tests (lockstep):** the file above.

**Acceptance:**

- `python -m pytest -q audio_normalizer/tests` green.
- `ffmpeg_finder.py` coverage materially above its current level, with every
  `sys.platform` branch exercised at least once.
- A forced "not found" produces exactly the message A5's dialog expects
  (asserted against the same constant, not a re-spelled literal).

**Risks:** low. The main hazard is writing a test that asserts a *replacement*
contract for the finder; the item is a coverage fix, so the existing
behaviour is the specification.

---

### B4 [x] — Replace the blanket GUI skip with a loud, bounded failure `[audit #18]`

**Priority:** High | **Effort:** 0.3 day | **Risk:** Medium

**Problem:** root `conftest.py:49-66` handles a headless host by marking
**every collected test in the session** skipped when the Tk root could not be
created. The result is a run that can report thousands of skips and still
exit 0 — and A4 exists precisely because that mask is load-bearing on Linux
today. The failure mode is silent by construction: nothing distinguishes "this
machine has no display, so nothing was verified" from "everything passed".

The skip is *necessary* on a genuinely headless host, so the fix is not to
remove it — it is to make it bounded, attributable, and impossible to mistake
for a pass.

**Scope:**

- [x] Keep the existing behaviour as the last resort, but add an explicit,
      always-printed session summary: display availability, number of tests
      skipped for display reasons, and an explicit line stating that GUI
      behaviour was **not verified** in this run.
- [x] Make it **bounded**: skip only the tests that actually need Tk, not the
      whole session. The blanket hook is what makes the Linux leg's skip count
      meaningless (A4). Prefer marking display-dependent tests via a
      `gui` marker or a fixture-level skip, with the session-wide hook retained
      as a safety net for collection-time failures.
- [x] Add a pytest **warning** (not just a skip) when the blanket path fires,
      so it appears in `-ra` output and in CI logs as a distinct class.
- [x] Add `gui` to `markers` in `pyproject.toml` and to the CI matrix
      semantics agreed in A4/D4.
- [x] If any test genuinely requires a display and cannot use the shared root,
      it gets an explicit skip with a reason naming the requirement — never an
      inherited blanket skip.

**Tests (lockstep):**

- [x] `tests/test_conftest.py` (root): a headless simulation — monkeypatch
      `tk.Tk` to raise `tk.TclError` — asserts (a) the session still exits 0,
      (b) the skip reasons are attributable, (c) the "GUI not verified"
      summary line is emitted, and (d) a non-GUI test in the same run is
      **not** skipped, which is the actual regression this item fixes.

**Acceptance:**

- A headless run's terminal output contains an explicit
  "GUI behaviour not verified" line.
- The count of display-skipped tests is bounded by the GUI tests, not the
  whole suite.
- With a display present, skip counts drop to the genuinely platform-specific
  tests only (0 on a Windows desktop).

**Risks:** converting a blanket skip to per-test skipping will *increase* the
surface where a real GUI test fails on Linux. That is intended — but each new
failure must be triaged as either a genuine platform bug (fix it, with a
regression test) or a genuine platform limitation (explicit, reviewed skip).
Do not paper over it with the blanket hook.

---

---

## Stage 2 — Collapse Duplication and the Registry Blast Radius

**Rationale:** these items do not change behaviour. They reduce the number of
places a defect can hide and the number of files a one-line fix has to touch.
They sit after Stages 0–1 on purpose: consolidation is far riskier against a
suite that cannot yet measure itself, and every step here is gated by
behaviour-lock tests written first.

**Stage gate:** duplicate blocks are consolidated behind a single
implementation with behaviour-lock tests, and the tool registry is split so
adding a tool no longer edits a 300-line literal.

---

### C1 — Extract the shared GUI app scaffold (94.2% pair) `[audit #8]`

**Priority:** Medium | **Effort:** 0.75 day | **Risk:** Medium

**Problem:** `key_detector/app.py` and `mood_analyzer/app.py` are **94.2%
identical** by line comparison. They are the same Tk application — same
bootstrap, same driver-controls panel, same folder picker, same log/help
buttons, same start/stop wiring — differing only in the analysis the middle
calls. At 94.2%, a fix to one is silently not a fix to the other, and the
audit's whole class of "test passes while the app is broken" defects has a
preferred habitat here.

**Scope:**

- [x] Characterise the pair precisely before editing: diff them, and list the
      *behavioural* differences (not textual ones). Textual similarity
      overstates sharing; the two files may differ in a way that a naive
      extraction would flatten.
- [x] Identify the true shared shape: a base app class in
      `audio_suite_shared/` (the established home for shared UI), following the
      existing `UIHelperMixin` / `bootstrap_tool_app` pattern rather than
      inventing a new one.
- [x] Behaviour-lock **before** refactoring: `key_detector/tests` and
      `mood_analyzer/tests` must pass against the current code, and the
      per-tool differences must each have a test that fails if the difference
      is accidentally collapsed.
- [x] Extract in one commit; the follow-up commit deletes the duplicated
      bodies. Never leave a half-extracted pair.
- [x] Per AGENTS.md §2, this is the one item in the plan where a wider touch
      is *sanctioned* — but the sanctioned blast radius is exactly these two
      apps plus the shared base. No other app is touched in this item.

**Tests (lockstep):**

- [x] A test in each tool's suite proving its distinct behaviour survives
      (e.g. `mood_analyzer` still calls its own analysis, `key_detector` still
      calls key detection) — these are the tests that would catch an
      over-eager dedup.
- [x] Tests for the new shared base, in `audio_suite_shared/tests`.
- [x] The `master_driver` card for each tool still builds (the cards import
      these apps — see `AGENTS.md` "Master Driver Card Naming").

**Acceptance:**

- `key_detector/app.py` and `mood_analyzer/app.py` no longer share a
  duplicated body; the shared logic lives once.
- Both tools' suites green, unchanged in pass count, with the distinct-behaviour
  tests present.
- `python -m mypy .` clean (the extracted base is first-party, so it is fully
  `--strict`-checked).

**Risks:** GUI code has few meaningful unit tests today (see the `app.py`
coverage finding), so "the suites still pass" is weaker evidence here than
elsewhere. Mitigation: the distinct-behaviour tests must assert *the call that
differs*, not merely that the app constructs.

---

### C2 — Consolidate the near-verbatim file-processor twins (70.9% pair) `[audit #9]`

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Medium (audio write path)

**Problem:** `noise_reduction/core/file_processor.py` and
`pop_click_remover/core/file_processor.py` are **70.9% identical**. Both are
built on `BaseFileProcessor` and both hand-roll the same
discover/temp-file/write/undo/cleanup sequence with a different DSP function
in the middle. This is the highest-risk duplication in the plan, because both
write audio files: a divergence in the temp-file or undo wiring is a
**data-loss / wrong-output** defect, not a cosmetic one (AGENTS.md: "Audio
correctness is release-blocking").

Note the interaction with A2: this is the package item A2 puts back under
measurement, so the lockstep tests here land on code that is finally being
executed by the default suite.

**Scope:**

- [x] Diff the pair and classify every difference: DSP-specific (keep) versus
      workflow-identical (consolidate). Assume nothing is safe to merge.
- [x] Push the shared workflow into `BaseFileProcessor` (or its base) as a
      template method with the per-tool DSP supplied as a callable — the
      pattern the Iteration-4 sprint 2 already established for
      `process_batch`, which both tools already inherit.
- [x] **Unchanged, byte-for-byte:** the undo snapshot, the per-file error
      slot-pool, the progress-callback signature, temp-file naming, and the
      dry-run/no-write path.
- [x] Do not unify the DSP. `noise_reduction` (IIR/FFT denoise) and
      `pop_click_remover` (click interpolation) are different algorithms; the
      duplication is the *workflow*, not the *processing*.

**Tests (lockstep):**

- [x] Outcome-level tests, not read-back: generate a real input file, run each
      tool, **decode the result and measure it** — the `AGENTS.md`
      audio-correctness rule. For `noise_reduction`, assert the noise floor
      dropped and the tonal content survived; for `pop_click_remover`, assert
      the click impulses are attenuated and the surrounding signal is intact.
- [x] Undo round-trip for both tools: delete/modify, revert, and assert the
      file is restored to the **original bytes**.
- [x] Dry-run: assert no output file is created and no write call is made
      (the existing "mode flags must be traced end-to-end to the write site"
      trap).

**Acceptance:**

- The shared workflow exists once; neither tool's file contains the duplicated
      body.
- Both outcome tests pass with measured, pre-recorded expectations.
- Undo and dry-run tests pass for both tools.
- A bare full-suite `pytest` run is green (not a package-scoped run).

**Risks:** high blast radius, audio write path. The lock is the
outcome-measurement tests, written *first* and run against the pre-refactor
code. If an outcome test cannot be made stable on both tools, that instability
is itself the finding — record it, do not paper over it.

---

### C3 — Split the tool registry builder `[audit #13]`

**Priority:** Medium | **Effort:** 0.4 day | **Risk:** Low

**Problem:** `audio_suite_shared/tool_plugin.py:153` defines
`_build_default_registry()`, a single ~300-line function that constructs all
27 `ToolManifest` entries as one literal and is called from the lazy singleton
at `:492`. Consequences: adding a tool means editing a 300-line literal in the
middle of a shared module; the file is both the manifest and the builder; and
the registration is untestable except by importing the whole module. Note the
`AGENTS.md` rule that the manifest `id` is the single source of truth for the
card filename, the CLI command, the arg builder, the batch graph, the driver
state key, and the guide registry — all of which currently depend on a value
buried in that literal.

**Scope:**

- [x] Move each manifest's *data* into a small declarative table (a list of
      frozen `ToolManifest` instances, or a per-module table) and make
      `_build_default_registry()` assemble the registry from it. Keep the
      function name, the return type, and the lazy-singleton call site
      (`tool_plugin.py:492`) unchanged so nothing downstream breaks.
- [x] Preserve the exact set of 27 ids, their field values, and their
      declaration order — order affects the Master Driver's tool listing.
- [x] Prefer splitting the data *out of the function*, not splitting
      `tool_plugin.py` into many modules: the manifest is one cohesive
      contract and a cross-file split would be an anti-creep violation.
- [x] Add the missing `__init__.py`-style export discipline as mypy requires
      (this project already uses the redundant-alias re-export form for
      `mypy --strict`; follow it if the split creates one).

**Tests (lockstep):**

- [x] `audio_suite_shared/tests/test_tool_plugin.py` — the existing
      expected-set test must pass **unchanged** (27 ids, same values, same
      order). Per `AGENTS.md` "Lockstep Updates", the test is the lock; if it
      needs editing, the refactor changed behaviour and the change is wrong.
- [x] Add a test that the registry is constructible and immutable from the
      outside (a caller cannot mutate the shared registry in place).

**Acceptance:**

- `_build_default_registry()` is a short assembly function, not a 300-line
  literal.
- `test_tool_plugin.py` passes with no edits.
- `python -m mypy .` clean; `ruff check .` clean.

**Risks:** order and value drift. Both are caught by the unchanged
expected-set test, which is why that test is a hard precondition, not a
nice-to-have.

---

---

## Stage 3 — Test-Suite Depth and Measurement Honesty

**Rationale:** Stage 0 removed the two biggest measurement lies (a missing
package, a missing platform). This stage removes the two remaining ones — the
marker system that lets hardware tests run in CI, and the coverage exclusions
that hide untested branches — and then re-baselines the gate under D3.

**Stage gate:** `integration` / `hardware` are actually honoured, the coverage
exclusions no longer hide executable branches, and the coverage gate is
re-decided with real data.

---

### D1 [x] — Honour the `integration` and `hardware` markers `[audit #14]`

**Priority:** Medium | **Effort:** 0.3 day | **Risk:** Medium

**Problem:** `pyproject.toml:169-172` registers two markers —
`integration` ("requires ffmpeg and real audio files") and `hardware`
("requires physical CD drive hardware") — and `--strict-markers` keeps them
honest as *labels*. But nothing ever acts on them: **273 `integration` tests
and 30 `hardware` tests are collected and run by default**, because no
`addopts` entry deselects them. The markers document an intent that was never
implemented, which is the most misleading kind of configuration — a reader
concludes CI skips hardware tests, and it does not.

Practical effect today: the 30 `hardware` tests pass only because they mock the
drive, and they run identically on Linux and Windows. The moment a hardware
test reaches a real device, CI is unrunnable on hosted runners.

**Scope:**

- [x] Decide the contract explicitly and write it down in the marker
      descriptions themselves (the description is what a reader sees):
      - `integration` — runs by default **where ffmpeg is present** (which A4
        installs on Linux); auto-skips with an explicit reason where it is not.
      - `hardware` — never runs in CI; deselected by default and enabled only
        by an explicit opt-in flag.
- [x] Implement the split: keep `integration` in the default `addopts`, and
      deselect `hardware` by default via `-m "not hardware"`, with the opt-in
      path being a plain, documented flag/override (for example running
      `pytest -m hardware` directly). Do not invent an environment-variable
      switch that nobody can discover.
- [x] Every auto-skip must carry a reason naming the missing prerequisite.
      A bare `@pytest.mark.skip` on a marker is exactly the failure mode B4
      removes.
- [x] Update the `master_driver` / `audio_suite_shared` marker documentation
      if any README or guide text describes the current (non-existent)
      behaviour.

**Tests (lockstep):**

- [x] A test asserting the marker wiring itself: collect with the default
      `addopts` and assert the `hardware` set is excluded and the `integration`
      set is included. Without this, the contract can silently rot back to
      "everything runs".
- [x] `audio_suite_shared/tests/` (or the root `tests/`) is the right home for
      a suite-wide configuration test — follow the existing convention for
      config-locking tests rather than inventing a new location.

**Acceptance:**

- Bare `pytest` collects the 273 `integration` tests and excludes the 30
  `hardware` tests; the summary line says so.
- `pytest -m hardware` collects the hardware set locally, and each test skips
  or runs with an explicit reason.
- No test in the default run is skipped for a reason the reader cannot
  interpret.

**Risks:** deselecting `hardware` removes 30 passing tests from the default
run, which lowers the headline count. That is the honest number, and it is the
same trade A2 forces. A hardware test that *would* have caught a real defect
is the cost — mitigated by requiring the opt-in path to be documented in
`CONTRIBUTING` (item F2, Stage 4) so it is actually run before releases.

---

### D2 [x] — Stop the coverage exclusions from hiding live branches `[audit #17]`

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `[tool.coverage.report] exclude_lines` in `pyproject.toml:221-236`
contains two entries that are too broad for what they claim to exclude:

- `"except ImportError"` — excludes **every** `except ImportError` block in the
  codebase, not just optional-dependency guards. Any real error handling that
  happens to catch `ImportError` is now permanently invisible to coverage, and
  a genuine bug in such a branch can never be surfaced by a coverage report.
- `"raise AudioMissingDependencyError"` — narrower, but still an exclusion of
  a statement rather than of a *branch*, and it pairs with the above so the
  optional-dependency story is doubly hidden.

The comment above them says these are "defensive re-export guards and
optional-dependency fallbacks", which is a real pattern in this codebase — but
a *pattern-level* exclusion cannot distinguish a legitimate guard from an
untested error path. The audit's point is not that the guards are bad; it is
that the gate cannot see them, so nobody can tell whether they are exercised.

**Scope:**

- [x] Replace the two broad patterns with a **narrow, explicit** mechanism. The
      cleanest form this codebase already uses is a per-line pragma: keep
      `pragma: no cover` available and apply it at the individual guard lines
      that genuinely cannot run, instead of excluding a syntax pattern
      tree-wide. The `AGENTS.md` "Comments Policy" applies: annotate the
      legitimate guards with a *reason*.
- [x] Where a guard genuinely can be exercised, do not exclude it — write the
      test. B2 and B3 are the templates: both are exactly this situation.
- [x] Keep the genuinely universal exclusions (`if TYPE_CHECKING:`,
      `@abstractmethod`, `raise NotImplementedError`, the `...` body rule, the
      `__main__` guard) untouched.
- [x] Do not lower `fail_under` to absorb the newly-visible lines; D3 governs
      the gate, and its recommendation is to hold 75.

**Tests (lockstep):** none strictly required — the change makes existing
coverage reporting stricter. But add a **configuration-lock test** asserting
that `exclude_lines` contains no bare `except ImportError` pattern, so the
broad exclusion cannot silently return.

**Acceptance:**

- `[tool.coverage.report] exclude_lines` contains no syntax-pattern exclusion
  broad enough to hide arbitrary error handling.
- The bare full-suite coverage number is recorded before and after, and the
  delta is explained line-by-line in the Completion Log (expected: it drops).
- The configuration-lock test passes.

**Risks:** the honest number will drop, and it may fall below `fail_under`.
That is the intended sequence: D3 is decided *before* this item runs, so the
drop is measured against a gate the maintainer already chose, not discovered
mid-stage.

---

### D3 [x] — Re-baseline the coverage gate under the honest measurement `[gate — no new finding]`

**Priority:** High | **Effort:** 0.1 day | **Risk:** Low (decision-heavy)

**Problem:** `fail_under = 75` has never been evaluated against an honest
denominator, because `noise_reduction` was missing (A2) and the exclusions
(D2) hid executable branches. After A2 and D2 the number will move, and D3
requires the threshold be chosen *before* the first honest run rather than
fitted to it.

**Scope:**

- [x] Run the bare full suite and record the post-A2/post-D2 number verbatim.
- [x] Apply the D3 decision (recommendation: hold 75). If the number is below
      the gate, the correct outcome is to record the shortfall and schedule the
      specific untested regions — not to move the goalpost.
- [x] Record the number, the decision, and the resulting action in the
      Completion Log and the Decision Log.
- [x] If the maintainer chooses a *higher* gate (D3 option B), record which
      items must land first for it to be reachable.

**Tests (lockstep):** none.

**Acceptance:** a single, quoted, reproducible coverage number in the
Completion Log, with the threshold it was measured against, and no threshold
change that is not traceable to an explicit maintainer decision.

**Risks:** the temptation to re-introduce a broad exclusion to clear the gate.
That is the audit's finding recurring; the configuration-lock test in D2
exists to make it visible.

**Naming note:** this item is plan item `D3` (Stage 3) and it *executes*
**decision D3 (coverage threshold)** from the Open Decisions section. It
introduces no new audit finding — it exists so the threshold is chosen before
the first honest measurement, per that decision's own acceptance rule.

---

---

## Stage 4 — Documentation, Packaging Metadata, and Dependencies

**Rationale:** the two items here are what a new user, a new contributor, and a
lawyer each need first, and none of them is code. They are cheap, and they are
the items most likely to be deferred forever if placed after the code work.

**Blocked on:** D1 (licence) for item 11; D5 (platform matrix) for the
platform-support content in item 10.

**Stage gate:** a new user can go from clone to first working tool from the
README alone, and the distribution's licence and runtime requirements are
declared in machine-readable metadata.

---

### E1 [x] — Write the README: quick start, tool index, architecture `[audit #10]`

**Priority:** Medium | **Effort:** 0.4 day | **Risk:** Low

**Problem:** the repository has no `README.md` and `pyproject.toml` declares no
`readme`. The 27-tool suite — its install steps, its `ffmpeg` requirement (A5),
its per-tool user guides, its architecture, its licence — is discoverable only
by reading the source tree. For a project of this size that is the single
largest onboarding failure, and it is also the surface item 21's
discoverability complaint rests on.

**Scope:**

- [x] Create `README.md` with, in this order: what the suite is (one
      paragraph); **prerequisites** (Python version, `ffmpeg`/`ffprobe` via
      A5's documented install commands, platform support per D5);
      installation (`uv sync` with the extras, plus the `pip` alternative);
      a one-command smoke test; a **tool index** table (tool name → what it
      does → launcher → guide document) generated from the manifest rather
      than maintained by hand; a short architecture overview (shared
      `audio_suite_shared` layer, `BaseFileProcessor`/undo/progress model,
      Master Driver, per-tool `app.py` + `core/` + `ui/` shape); and a
      contributing pointer (item E2).
- [x] Set `readme = "README.md"` in `[project]`.
- [x] The tool index is the trap: do not hand-write 27 rows that immediately
      drift from `tool_plugin.py`. Either generate the table from the manifest
      in a tiny script under `utilities/`, or state explicitly in the README
      that the manifest is the source of truth. The `AGENTS.md`
      `guide_to_program` registry in `platform_utils.py` is the existing
      index of guides — reuse it rather than creating a third list.
      (Both: the table is *generated* by `utilities/generate_readme_tool_index.py`
      AND the README states the manifest is the source of truth.)
- [x] Do not duplicate the per-tool guides; link to the `.docx` guides already
      generated under `user_guides/individual_programs/`.
- [x] Per `AGENTS.md` §8, treat the README as a user-facing document: if a
      generator produces part of it, edit the generator, not the artifact.

**Tests (lockstep):**

- [x] A test that every manifest id appears in the README's tool index (or, if
      the index is generated, a test that the generator runs and produces a
      table matching the manifest). This converts a documentation claim into an
      enforced invariant and prevents the exact drift that
      `AGENTS.md` "Registering a New Tool" warns about.
- [x] `AGENTS.md`'s checklist already requires registering a guide filename in
      `guide_to_program`; fold that into the same test so one assertion covers
      manifest ↔ card ↔ CLI ↔ guide.

**Acceptance:**

- `README.md` exists, is linked from `pyproject.toml`, and a new user can
  install and run a first tool from it without reading source.
- The tool-index test passes and fails if a tool is added without a README row.
- The README states the same `ffmpeg` requirement A5's dialog enforces.

**Risks:** documentation drift is the only real risk, and it is mitigated by
the enforced-index test. Avoid documenting anything this plan changes in
Stages 5–6 (key-detection accuracy, platform matrix) beyond the D5 wording
agreed here.

---

### E2 [x] — Add the licence, and the contribution/security/changelog baseline `[audit #11]`

**Priority:** High | **Effort:** 0.3 day | **Risk:** Low (legal exposure if skipped)
**Blocked on:** D1 (recommendation: GPL-3.0)

**Problem:** there is no `LICENSE` file and no `license` field in
`[project]`. This is a genuine legal gap, not a documentation nit: the suite
redistributes and links `pedalboard` (GPL-3.0) and depends on an AGPL-incompatible
option surface (D2). Without a stated licence, no third party has any right to
use, modify, or redistribute the work, and the maintainer has no record of the
intent. Contributing, security, and changelog documents are absent for the same
"nothing was ever written down" reason.

**Scope:**

- [x] Add the `LICENSE` file matching the D1 decision verbatim (GPL-3.0 if the
      recommendation is accepted) and declare it in `pyproject.toml`
      (`license = "GPL-3.0-or-later"` plus a `LICENSE` file reference, in
      whichever form the pinned setuptools/PEP 621 version accepts — verify
      against the installed version, do not guess the field syntax).
      (PEP 639 form used — see the Decision Log entry.)
- [x] Add `CHANGELOG.md` in Keep-a-Changelog form, seeded with the audit-era
      baseline (`e729626`) as the first entry so the file is not empty history.
- [x] Add `CONTRIBUTING.md`: how to run the mandatory gate (the six commands
      in the Phase Gate), the test-file naming rule, the
      "register the tool in all ten places" checklist, and **how to run the
      `hardware`-marked tests** (the opt-in path from item D1 — this is the
      mitigation for losing those 30 tests from the default run).
- [x] Add `SECURITY.md`: how to report a vulnerability, with an explicit
      statement about the subprocess allowlist surface
      (`audio_suite_shared/secure_subprocess.py`) and the fact that raw audio
      and tag files are untrusted input. Keep it short and honest; do not
      promise a response time the maintainer has not agreed to.
      (Reporting channel: repository issue tracker, explicitly no SLA — see
      the Decision Log.)
- [x] Do not add `CODE_OF_CONDUCT.md` unless the maintainer wants one — it is
      the one item in this group that is a policy decision rather than a gap.
      (Deliberately not added; recorded in the Decision Log.)

**Tests (lockstep):**

- [x] A packaging test asserting `pyproject.toml` declares a licence and that
      the referenced `LICENSE` file exists on disk (a metadata-only change
      otherwise has no verification at all).
- [x] `python -m build`-level check is *not* required, but the metadata must
      not break the existing install path: `uv sync` still succeeds.

**Acceptance:**

- `LICENSE` exists and matches `[project] license`; `git grep -c "GPL-3.0"`
  shows both agree.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md` exist and are referenced
  from `README.md`.
- `uv sync` and the bare full-suite `pytest` run are unaffected.

**Risks:** writing the wrong licence text or an SPDX expression that the
pinned setuptools rejects will surface immediately at install time — verify by
installing, not by reading. The `SECURITY.md` content must not be aspirational;
over-promising a response SLA is worse than saying nothing.

---

### Stage 4 note on dependency declarations

Item A5 declares the `ffmpeg` *system* requirement. This stage's
`CONTRIBUTING`/`README` text is where that declaration becomes visible to users,
and the two must be worded identically — a mismatch between the dialog a user
sees and the README they read is a new defect. Wording is locked in A5; E1 and
E2 copy it verbatim.

---

---

## Stage 5 — Analysis Accuracy, Measured Not Asserted

**Rationale:** this is the only stage that changes what the tools *report*.
Both items are governed by the project's hardest rule — an analysis change is
validated by decoding and measuring, never by reading back the same internal
state. Item 19 lands first and deliberately: it creates the measurement harness
that makes item 7's upgrade safe to attempt.

**Stage gate:** the analysis family has measured-outcome tests, and the
key-detection engine change is gated on a correctness lock that exists *before*
the change.

---

### F1 — Build measured-outcome / golden-vector tests for the analysis family `[audit #19]`

**Priority:** High | **Effort:** 0.75 day | **Risk:** Low (additive only)

**Problem:** the analysis family — key detection, BPM, tempo, mood, and the
`analysis_loader` decode path — has extensive tests, but they overwhelmingly
assert *that a function returned a value of the right shape* rather than *that
the value is correct*. The `AGENTS.md` rule for this exact trap is explicit:
"self-consistent field read-back cannot detect corruption". An analysis tool
that returns a plausible, well-typed, wrong key passes every test it has. The
audit rated this High precisely because it is the difference between a
well-tested suite and a tested-correct suite.

**Scope:**

- [x] Do **not** start with the code. Build the reference vectors first, from
      *known ground truth*, and record them in the Completion Log with their
      provenance.
- [x] Construct synthetic-but-deterministic fixtures whose correct answer is
      knowable by construction:
      - a pure sine at a known fundamental plus its fifth → expected key
        signature;
      - a click train at a known BPM → expected tempo/BPM;
      - a chord progression built from a known pitch set → expected key;
      - a segment of white noise at a known RMS → expected energy features.
      Generate these with a helper in the tests (seeded `numpy` RNG so they
      are byte-reproducible), not from any real commercial audio, so the
      fixtures are unambiguously redistributable under the D1 licence.
- [x] Add `key_detector/tests/test_key_engine_vectors.py` and the equivalent
      for tempo/BPM/mood, following the naming convention (`test_<module>.py`
      per `AGENTS.md`, so extend the existing per-module test files where they
      exist rather than adding parallel ones).
- [x] Assert the **measured outcome**: the detected key equals the constructed
      key; the detected BPM is within a stated tolerance of the click rate.
      A tolerance is correct here — but it must be a declared, justified
      number, not whatever the current code happens to produce.
- [x] Add one **negative** case: a fixture that is deliberately ambiguous or
      noise-only, asserting the engine returns a stated "low confidence" or
      falls back, rather than inventing a confident answer.
- [x] This item is **additive only** — it must not change any production
      behaviour. If a vector test fails against the current engine, that is
      the F2 input, not an F1 defect.

**Tests (lockstep):** the vector suites above.

**Acceptance:**

- Every analysis module has at least one positive, one negative, and one
  boundary vector, with declared tolerances.
- The suites pass **unchanged** against current production code (proving they
  are measuring what the engine does today, which is the lock F2 needs).
- Fixtures are seeded and reproducible; running twice yields identical results.

**Risks:** the temptation to "fix" a failing vector inside F1. Resist it — a
failing vector is the whole point of the item, and fixing it in the same commit
destroys the before/after evidence that makes F2 verifiable.

---

### F2 — Upgrade the key-detection engine behind the F1 lock `[audit #7]`

**Priority:** Medium | **Effort:** 0.6 day | **Risk:** Medium (accuracy
regression risk)
**Blocked on:** D2 (recommendation: self-contained profile correlation — **no
new dependency**), and F1 must be complete

**Problem:** `key_detector/core/key_engine.py` (149 lines) detects key by
correlating a chroma vector against static Krumhansl-Schmuckler major and minor
profiles, rotated 24 ways (`np.corrcoef` against each `np.roll` of
`_MAJOR_PROFILE` / `_MINOR_PROFILE`). This is a well-known, purely
theoretical baseline. It has two practical weaknesses: it has **no tuning
parameter**, so it cannot be adapted to the suite's actual material, and it is
**chromatic-only**, so a passage with weak or ambiguous chroma energy (guitar,
piano pedalling, minor-key material) mis-keys more often than a user expects a
"key detector" to.

**Scope:**

- [x] Implement the D2-recommended path: a self-contained, first-party
      profile-correlation upgrade in `key_detector/core/key_engine.py`. Keep it
      pure `numpy` — **no new third-party dependency** (AGENTS.md §4; `madmom`
      and `essentia` are both rejected in D2 for recorded reasons).
- [x] The scope of "upgrade" is deliberately narrow, and must stay inside
      `key_engine.py` plus its own tests:
      - make the correlation method and any weighting an explicit, documented
        parameter (so a user or a future iteration can tune without editing
        the algorithm);
      - add a stated confidence value derived from the winning correlation's
        margin over the runner-up, and a documented low-confidence fallback —
        the F1 negative vectors then assert this instead of a fabricated key;
      - keep the public interface (`detect_key` and its callers) unchanged
        unless F1 proves an interface defect.
- [x] Do **not** re-tune the profiles against the F1 fixtures. Tuning on the
      test vectors and then reporting those vectors as validation is circular;
      if tuning is wanted, it needs a separate labelled corpus and a separate
      item.
- [x] Per `AGENTS.md` §2, this is a scoped internal change. It is not an
      invitation to restructure `key_detector`.

**Tests (lockstep):**

- [x] The F1 vectors pass **before and after** with the same declared
      tolerances — this is the regression lock. A change that improves the
      aggregate but breaks a specific constructed key must be rejected.
- [x] Add a test for the new confidence output: a clean synthetic key yields
      high confidence, the F1 negative vector yields the documented fallback,
      and a mid-confidence input is neither silently upgraded nor dropped.
- [x] A measurement test on **real** material: decode a small, redistributable
      reference excerpt and record the key before and after, with the
      confidence for each. Self-consistent read-back is explicitly not
      sufficient here (AGENTS.md).

**Acceptance:**

- `key_detector` reports a confidence value and a documented low-confidence
  behaviour.
- F1 vectors green with unchanged tolerances; the completion log shows the
  before/after on real material.
- No new entry in `[project] dependencies` — verified with `git diff pyproject.toml`.
- `python -m mypy .` clean and bandit unchanged (0 High / 0 Medium).

**Risks:** an accuracy upgrade that *regresses* the common case. Mitigation is
structural: the F1 lock runs before the change, real-material measurements are
recorded on both sides, and the change is reversible in one commit. If real
material shows a net regression, revert and record the result — a measured
revert is a valid outcome of this item.

---

---

## Stage 6 — Declared Reach: Platform Support and Discoverability

**Rationale:** the last two items are about honesty rather than capability.
The suite is Windows-first; the right outcome is a *stated* support matrix with
the platform-independent core verified, not an aspiration of universal support
and not silence. Discoverability is the same problem in user-facing form.

**Blocked on:** D5 (recommendation: declared matrix + CLI-first core)

**Stage gate:** every platform-conditional code path is either verified by a
test or carries an explicit, reviewed skip tied to the declared matrix, and
the tool surface is discoverable from the command line and the README.

---

### G1 [x] — Declare a platform support matrix and verify the portable core `[audit #20]`

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Low

**Problem:** the suite contains a large number of `sys.platform` branches and
Windows-specific subsystems — `winaccent` (declared `sys_platform == 'win32'`
only), `icacls` ACL hardening in `key_manager` (allowlisted per the Iteration-4
K1 work), `STARTUPINFO` console suppression, drive-letter handling in
`cd_ripper`, `os.startfile`-style launchers, and `.pyw` launchers that have no
POSIX equivalent. None of this is documented, and the Linux CI leg (pre-A4)
verified none of it. So the answer to "does AudioSuite-Pro run on Linux or
macOS?" is currently unknowable from the repository — a user must read the
source.

**Scope:**

- [x] Produce the support matrix as a **documented table** (README per E1),
      with three explicit tiers, and make the tiers *testable*:
      - **Portable core** — CLI-first tools whose core DSP/decode path has no
        platform-conditional code. This is the D5 option-A scope.
      - **Windows-only** — tools with a genuine platform dependency
        (`key_manager` ACL, `cd_ripper` drive handling, `.pyw` launchers).
      - **Unverified** — anything in a `sys.platform` branch that no CI leg
        exercises. Listed explicitly, with a note that it is untested rather
        than supported.
- [x] Enumerate every `sys.platform` / `os.name` / `sys.platform == "win32"`
      branch in first-party code and classify each into one of the three
      tiers. This enumeration is the deliverable; the table is its rendering.
- [x] For the portable core, add a test that exercises the core through the
      **CLI** with a monkeypatched `sys.platform` value, proving the path is
      genuinely platform-independent rather than accidentally untested on
      Windows. A mocked platform value does not prove it runs on Linux — that
      is what A4's leg is for — but it does prove the branch is deliberate.
- [x] For each Windows-only subsystem, add a skip with a reason naming the
      platform requirement, so the B4 blanket mechanism is not the thing
      hiding it.
- [x] Do not attempt to port anything. This item *declares* the current truth;
      a port is a new plan with the user's approval.
- [x] Correct the README's platform claim to match the matrix exactly — an
      over-claim here is the defect this item exists to remove.

**Tests (lockstep):**

- [x] A test asserting the documented matrix matches reality for the
      portable-core subset: each tool listed as portable has a CLI test that
      runs with a monkeypatched non-Windows `sys.platform`.
- [x] A test asserting every Windows-only tool's suite either runs or skips
      with the declared reason — no silent pass-through.

**Acceptance:**

- [x] Every platform-conditional branch in first-party code is classified into the
      three tiers; the enumeration is in the README and the count is recorded in
      the Completion Log.
- [x] The portable core has CLI tests that pass under a non-Windows `sys.platform`.
- [x] No README claim exceeds the matrix.
- [~] The Linux CI leg (A4) reports real results for the portable core.
      **Outstanding — owned by A4, not by this item:** the portable core is
      verified here against a *mocked* platform, which is the honest ceiling
      reachable from a Windows host. Real Linux results require A4's first
      post-merge run (see the Completion Log's Stage 6 gate block).

**Risks:** classification is a judgement call and can be wrong in the
permissive direction ("portable" for something that is not). Mitigation: the
portable-core test is executed, not asserted — a tool can only be called
portable if its core test actually runs under the mocked platform. When in
doubt, classify as **Unverified**, which is honest and cheap.

---

### G2 [x] — Make the tool surface discoverable from the command line `[audit #21]`

**Priority:** Low | **Effort:** 0.3 day | **Risk:** Low

**Problem:** 27 tools are registered in `audio_suite_shared/cli_app.py` behind
a single `audiosuite` entry point, with individual `.pyw` launchers, Master
Driver cards, and generated `.docx` user guides. The mappings between them live
in `audio_suite_shared/platform_utils.py` (`guide_to_program`) and in the
manifest. A user who does not already know the suite can run `audiosuite`, get a
list of subcommands, and find the *name* of a tool — but there is no stable,
tested contract that says each tool has a discoverable help entry, a guide, and
a launcher. Nothing verifies the three surfaces agree, so drift is invisible
until a user hits it.

**Scope:**

- [x] Add a **golden contract test** that asserts, for every manifest id:
      a CLI subcommand exists and its `--help` resolves; a `guide_to_program`
      entry exists; and the expected launcher exists on disk. This is the
      enforceable version of the `AGENTS.md` "Registering a New Tool" ten-point
      checklist, and it belongs with item E1's index test (decide whether they
      are one test or two, and record the choice). → **Two tests**, split by
      surface; the choice is recorded in the Decision Log.
- [x] `audiosuite --help` should group subcommands by function
      (analysis / tagging / repair / utilities) — if the current help is a flat
      alphabetical list, grouping it is a small, contained improvement to the
      same entry point. Keep the flat list behaviour available if any existing
      test depends on ordering.
- [x] Ensure the Master Driver card naming rule is enforced by the same test
      (the `AGENTS.md` "Master Driver Card Naming" failure mode — a
      near-miss filename is *silently* never found, with only a console
      warning as a symptom). A missing card must be a test failure.
- [x] Add a top-level `--version` that reports the version from
      `[project]` in `pyproject.toml`, so the version lives in exactly one place.
- [x] Do not build a new plugin/registry abstraction here; C3 has already split
      the existing one, and the discovery surface is the deliverable.

**Tests (lockstep):** the contract test above is the deliverable and must fail
loudly for a missing subcommand, guide entry, launcher, or card.

**Acceptance:**

- [x] Adding a tool without a CLI subcommand, guide entry, launcher, and card fails
      the suite — verified by temporarily removing one in a scratch check, not by
      assertion alone.
- [x] `audiosuite --version` matches `[project] version`.
- [x] `audiosuite --help` lists all 27 tools.

**Risks:** a contract test this broad can become a maintenance tax. Keep it
declarative — one table of expectations, one loop, no per-tool special cases —
and keep the same tolerance for growth the `AGENTS.md` checklist has (new tools
must satisfy it; existing gaps are listed, not silently grandfathered).

---

## Stage Dependencies (read before scheduling)

```
Stage 0  A1 A2 A3 A4 A5 A6      gate integrity   -> everything else is verified by these
   |
Stage 1  B1 B2 B3 B4            untested logic   -> needs Stage 0's honest numbers
   |
Stage 2  C1 C2 C3               duplication      -> needs Stages 0-1's behaviour locks
   |
Stage 3  D1 D2 D3               measurement      -> needs Stage 0 (A2) before re-baselining
   |
Stage 4  E1 E2                  docs/metadata    -> independent; only D1/D5 block
   |
Stage 5  F1 -> F2               analysis         -> F1 must land before F2
   |
Stage 6  G1 G2                  reach            -> independent; only D5 blocks G1
```

Two items are strictly ordered inside a stage: **F1 before F2** (the measurement
lock must exist before the algorithm changes) and **C2 after A2** (the
duplication work lands on code that the default suite finally executes). Every
other item is independently shippable, which is what keeps this a staged plan
rather than a big-bang rewrite.

---

## Phase Gate (run after **every item**, before marking it complete)

Per item — not per stage (item A6 exists because iteration 4 skipped this):

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` — exit 0
   (mandatory after **any** edit to a module in an import chain; the `.pyw`
   launchers re-run this at startup via `preflight.guard_or_exit()`)
1. `python -m ruff check .` and `python -m ruff format --check .` — clean
2. `python -m mypy .` — 0 issues (`strict = true` in `pyproject.toml`)
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv
   -c pyproject.toml` — 0 High / 0 Medium (the `-c pyproject.toml` and
   `-x ./.venv` are mandatory, or the report floods with out-of-scope findings
   and crashes on non-ASCII paths)
4. Bare `python -m pytest -q` — 100% pass, no skips added to hide a failure;
   a package-scoped run is **not** a substitute (it silently skips suites that
   are not in `testpaths`)
5. Coverage gate: `fail_under` per the D3 decision, recorded as an explicit
   number
6. No secrets staged: `git grep --cached -n -i -E -I -e '<pattern>'` over
   `api[_-]?key|secret|passwd|password|token`, plus the supplemental
   `*_key`-suffix, 32-hex and 44+-char base64 scans, per `AGENTS.md`

Item-specific extra gates:

- **Audio-write items** (C2, F2): decode the result and measure it. A test that
  reads back the same internal state the code just wrote is not evidence.
- **B1 (multiprocessing)**: the pool tests must be shown to **execute**, not
  collect-and-skip.
- **A4 (CI)**: the Linux leg's passed-test count is recorded, not assumed.

---

## Implementation Roadmap

| Stage | Content | Items | Est. days | Depends on |
|-------|---------|-------|-----------|------------|
| 0 | Gate integrity + runtime declaration | A1, A2, A3, A4, A5, A6 | 0.9 | D3, D4 decisions |
| 1 | Untested logic that runs in production | B1, B2, B3, B4 | 1.45 | Stage 0 |
| 2 | Duplication + registry blast radius | C1, C2, C3 | 1.65 | Stages 0–1 |
| 3 | Test-suite depth + honest measurement | D1, D2, D3 | 0.65 | A2 (Stage 0) |
| 4 | Docs, licence, packaging metadata | E1, E2 | 0.7 | D1, D5 decisions |
| 5 | Analysis accuracy (measured) | F1, F2 | 1.35 | D2 decision; F1 before F2 |
| 6 | Declared platform + reach | G1, G2 | 0.8 | D5 decision |

**Estimated total: ~7.5 days** of incremental, independently shippable work.
Every stage ends green against the Phase Gate, and every item lands as its own
reviewable commit (per `AGENTS.md` "Repository / Version Control").

**Deliberately not in this plan:** a macOS parity pass, a real plugin
architecture, per-tool GUI test coverage across all 27 tools, tuning the
key-detection profiles against a labelled corpus, and any refactor of the
Master Driver or batch orchestrator. Each is real work with real value and each
belongs in its own plan with the user's approval — not smuggled in here.

**Sequencing recommendation:** land Stage 0 alone first and let CI run. Stage 0
is small, it fixes the measurement instruments, and its own results (the honest
coverage number, the Linux leg's real pass count) are the input every later
decision needs.

---

## Completion Log

Fill one row per **item**. A row without Gate Evidence is, by definition, not
complete (item A6).

Per-item gate commands (run from the suite root, 2026-09-26, Windows host,
Python 3.14.7, ruff 0.15.22, mypy 1.20.0, pytest 9.0.3):

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
1. `python -m ruff check .` → clean · `python -m ruff format --check .` →
   745 files already formatted
2. `python -m mypy .` → 0 issues over 449 source files
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → 0 High / 0 Medium / 51 Low (baseline-identical)
4. bare `python -m pytest -q` → 7090 passed / 3 skipped
5. coverage → 78.07% ≥ `fail_under = 75` (D3 decision held)
6. `git grep --cached` secret scans (primary + 4 supplemental patterns) → no
   live secrets (documentation text and a pre-existing public-fingerprint test
   fixture only)

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| A1 | 0 | 2026-09-26 | `ruff format --check .`: 1 `.md` flagged under `--preview` → 0 | Full gate (commands 0–6 above) all green, 2026-09-26. Item-specific: post-fix `--preview` run has 0 `.md` matches; stable run exit 0, 745 files. | On ruff 0.15.22 stable the gate already passed — the finding reproduces under `--preview`, where `PLAN_audit_priority_actions.md` *was* flagged and is now excluded. Forward-protective, not retro-only. |
| A2 | 0 | 2026-09-26 | collected 6,983 → 7,071 (+88 exactly); coverage 78.26% → **78.04%** | Full gate all green, 2026-09-26. Item-specific: `--collect-only noise_reduction/tests` = 88; bare run count +88, all passing; coverage report gains a `noise_reduction` row. | **78.04% is the first honest (post-A2) baseline** every later stage is judged against, recorded before D3 was applied. Post-A3/A5 end-state measurement: 78.07%. |
| A3 | 0 | 2026-09-26 | headless bare run: exit 3 (INTERNALERROR) → exit 0 | Full gate all green, 2026-09-26. Item-specific: `genre_sync/tests` 177 passed; headless simulation (`tk.Tk` → `TclError`) on bare suite: 7,071 collected, exit 0, per-test attributable skips; live `pytest.skip(` call-site grep over all conftest files: 0. | Acceptance grep deviation recorded in the Decision Log (three docstring mentions of the banned pattern remain, by design, as documentation). |
| A4 | 0 | **[~] not complete** | Linux leg: no display/Tk/ffmpeg → xvfb + python3-tk + ffmpeg | **PENDING — no CI evidence available.** This host is Windows and the repository has no git remote, so the Linux leg cannot be executed or observed from here. YAML syntax-validated (parsed; `bash -n` exit 0 on the run step), but the required first post-merge CI run URL + Linux passed count are outstanding. | Item stays `[~]` per its own acceptance rule: the run URL must be recorded here *before* the item is marked complete. Marker split deliberately deferred to Stage 3 D1 by this item's own instruction. **Close-out decision (2026-09-28, maintainer Wilte): the plan closes with A4 `[~]` — a named condition, not a silent drop.** The implementation and YAML validation are complete; the first post-merge CI run URL + Linux passed count must be appended to this row as soon as the repository gains a git remote, and audit-index finding #4 flips `[~]` → `[x]` with that evidence. The condition is tracked as item A1 of `PLAN_iteration6_followups.md`. **Superseded (2026-09-29, maintainer Wilte): A1 withdrawn as not required** — there is no UNIX/Linux environment for this project, so the Linux leg is never run and the evidence can never be produced. This row and finding #4 stay `[~]` (closed as *not applicable*, not as *verified*); the CI configuration is left unchanged. See the post-close note at the Audit Finding Index and `PLAN_iteration6_followups.md` §A1. |
| A5 | 0 | 2026-09-26 | ffmpeg: undeclared + silent at launch → declared + warned at launch | Full gate all green, 2026-09-26. Item-specific: 33 tests green across the two A5 test modules; end-to-end real-launch acceptance on the real tree — ffmpeg stripped from PATH: compile gate passes, 0 blocking dialogs, exactly 1 warning naming ffmpeg + ffprobe with all three install hints; ffmpeg present: 0 dialogs, return `True`. `git grep -n "ffmpeg" pyproject.toml` → marker description + one documentation block only. | New `system_requirements.py` (machine-readable table) + `report_missing_requirements()` (pure, warning-level) + 9 dependent-tool guides regenerated (lossless: +5 paragraphs each, 0 lost) + `TestGuideWordingLock` enforcing the artifact↔module wording invariant. `ffmpeg_finder` reuse declined with rationale — Decision Log. |
| A6 | 0 | 2026-09-26 | no per-item evidence rule → mandatory Gate Evidence column + pre-item rule | Full gate all green, 2026-09-26 (this table is itself the deliverable: six commands + counts recorded per item above). | Per-item gate rule now stated in "How to read this plan" (before the first item); iteration-4 D1 precedent recorded in the Decision Log, dated; `PLAN_iteration4_remediation.md` untouched. |

**Stage 0 skip-count note:** the full-suite skip count moved 5 → 3 because the
two `test_ui_common` Scale probes (pre-existing `except AssertionError:
pytest.skip("...broken Tcl/Tk environment")` design) passed in this run.
Nothing in the Stage 0 diff touches Tk geometry or widget state; the probes
are environment-conditional by construction and both outcomes are sanctioned
by their own test code.

### Stage 1

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| B1 | 1 | 2026-09-27 | `batch_analysis_engine.py` **68% → 99%**; `_run_process_pool` branch **0% → 100%** of its reachable lines | Full gate all green, 2026-09-27 (commands 0–6 below). Item-specific: `mood_analysis_batch_tagger/tests` → 124 passed, of which `test_batch_analysis_engine.py` = **46 passed, 0 skipped** (31 test functions at HEAD → 46), so the pool tests are *executed*, not collected-and-skipped. `analysis_loader` defect fixed in the same change (Decision Log). | Real `ProcessPoolExecutor` — the chooser is **not** mocked; only the CPU worker may be substituted. Asserted: worker is a module-level function and `pickle.dumps`/`loads`-round-trips under the `spawn` start method; analysis provably runs in child PIDs (`os.getpid()` parity, not a mock); 3 real WAVs → 3 results in input order with one progress event each; live run's tag verified by reading it back with `read_mood`/`read_energy`; dry run writes nothing; a corrupt `.flac` yields a reported `error` result and the batch completes; a worker exception is mapped and reported while the other two files still complete; a tag-write failure is reported as a **skip** (not an abort) and the batch completes; slot claim/release accounting verified via the slot callback (including release of an in-flight cancelled slot); pre-set stop and mid-flight stop both report nothing/only-the-completed-item. Remaining 3 uncovered lines are **not** in the pool path: `104` (`_WorkerSlotTracker.acquire`'s `-1` fallback — provably unreachable from the pool path, whose inner `while` bounds `len(pending) < slots._count` before each submit, so ≥1 slot is always free) and `460` (thread-pool stop check) are thread-path code, and **`624` (`if not pending: break`) is dead code** — the outer `while index < len(pending_list) or pending` at `607` guarantees `pending` is non-empty on entry and nothing between `607` and `623` removes from it. **Proposed follow-up (not done here, per this item's own rule):** delete line 624 and the unreachable `return -1` fallback, or restructure the outer loop so the invariant is stated once. |
| B2 | 1 | 2026-09-27 | `analysis_loader.py` **34.3% → 100%** (36 statements, 0 missing) | Full gate all green, 2026-09-27 (same run as B1). Item-specific: `audio_suite_shared/tests` → green; the loader's four consumers (key/bpm/tempo/mood) pass unchanged; bare full suite **7140 passed / 3 skipped** vs the 7090/3 baseline = **exactly +50** new tests (15 in the B1 file, 35 in the new loader file), with **no skip added**. | Baseline missing set `56-86, 102-103, 119-124, 140-141` was **entirely reachable** — no dead code in this module. Measured, not mocked: real generated WAVs assert sample count, channel count, `float64` dtype, native sample rate, `max_duration` truncation, stereo→mono downmix, and the real decoded RMS. Failure paths assert the **specific** exception type the callers already catch (`AudioCodecError` with the original chained via `from`, `AudioAnalysisError` for short/empty/zero-rate) plus the `logger.error` with `exc_info=True`. Two corrections to the plan's scope text, for the record: the loader has **no resampling branch** (`sr=None` is passed to `librosa.load`, so the native rate is preserved by design) — the downmix is librosa's `mono=True` and is verified on real stereo audio; and the two silent-signal boundaries are asserted against `SILENCE_RMS_THRESHOLD` in **RMS** terms, scaling a sine by `√2` rather than assuming amplitude == RMS. The zero-sample-rate path found by B1 is now part of this file's contract. |
| B3 | 1 | 2026-09-27 | `ffmpeg_finder.py` **44% → 100%** (18 statements, 0 missing); `audio_normalizer/tests/test_ffmpeg_finder.py` 2 → 21 tests | Full gate all green, 2026-09-27 (see Stage 1 gate block below, B3 run). Item-specific: `audio_normalizer/tests` → **185 passed / 1 skipped** (the pre-existing `test_setup_tab` Tk probe); bare full suite **7159 passed / 3 skipped**, coverage **78.53%**, skip count **unchanged at 3**. | **Three scope bullets describe branches that do not exist** in the shipped 51-line module, verified by reading it: there is no *configured* path (no config read at all), no memoisation/cache dict, and no executability check. The finder's three sources are PATH → beside-the-module-or-frozen-exe → hard-coded `C:\ffmpeg\bin` on Windows. Tests were written against the code as shipped, per this item's own Risks note ("existing behaviour is the specification"); the mismatch is **reported, not papered over**: `test_os_access_is_never_consulted` fails the test if `os.access` is ever called, and `test_a_directory_named_like_the_binary_is_accepted` demonstrates the real consequence portably — a *directory* called `ffmpeg(.exe)` beside the module satisfies `os.path.exists`, so the finder returns a path that can never be executed. **Follow-up proposed (not done here):** `os.path.isfile(...) and os.access(..., os.X_OK)` in the source-2 gate. Also pinned, because the plan's acceptance asked for it: the module's cache behaviour (the import-time constant is the cache — asserted not to re-resolve when `PATH` later changes, and to be recomputed on re-import, with a restore-reload that cannot leak a fake singleton), the two "step 3 returns the literal while steps 1/2 `abspath`" asymmetry, the miss value `"ffmpeg"` **passing `validate_executable`** (so a user sees `FileNotFoundError`, not `SubprocessSecurityError`), and — asserted against the shared constants `FFMPEG_PURPOSE` / `REQUIRED_EXECUTABLES`, never a re-spelled literal — the A5 report line. |

| B4 | 1 | 2026-09-27 | headless run: **every** collected test skipped (7,162 skipped, exit 0, nothing verified) → **741 of 7,162** skipped, 6,398 passed, exit 0, GUI reported NOT VERIFIED | Full gate all green, 2026-09-27 (see Stage 1 gate block below, B4 run). Item-specific: `tests/test_conftest.py` → **21 passed**; display-present bare run **7180 passed / 3 skipped**, coverage **78.53%**, display skips **0**; empirical headless simulation of the real suite → **6398 passed / 764 skipped / 0 failed / 0 errors**, exit 0, skip count **bounded at 741 (10.3%)**. | The blanket hook is gone: skipping is decided per test from two declarative signals (a `root`/`tk_root` fixture request, or the `gui` marker), so a non-GUI test can no longer be skipped for display reasons. The always-printed report is the load-bearing part — it states display availability, the skip count, and `GUI behaviour: VERIFIED / NOT VERIFIED in this run`. **Empirical finding (the reason this was not a 10-minute change):** the bounded skip does not make a headless run green on its own. The first headless simulation of the real suite produced **31 failures + 63 errors (94 affected tests)** in exactly six UI test files, all the same root cause — those tests mock the *widget* but still construct real `tk.Variable` objects, which need a live interpreter. Those 17 classes now carry `@pytest.mark.gui` with a reason; that is the plan's own prescribed path for "genuinely requires a display and cannot use the shared root". **Collection evidence used to choose the signals:** 7,162 collected → 644 request `root`/`tk_root`, 682 mention those names in source, and **6,480 require neither**, so a fixture/marker rule leaves the non-GUI majority running. The pre-existing `requires_display` skipif in five modules was audited by AST and **all five already carry their own `reason=`**, so no inherited-blanket skip remains. `AUDIOSUITE_GUI_SKIP=all` is retained as an explicit, warned-about safety net and is tested: it skips everything and its report says `SAFETY NET ACTIVE ... this run proves nothing`. **CI half of the scope bullet:** the marker is registered in `pyproject.toml` (verified under `--strict-markers` in the simulation), and under D4's `xvfb` a display *is* present, so no `gui` job-level matrix flag is required; the actual Linux leg wiring stays with A4 (`[~]`, blocked — no remote). |
**Deviation recorded for B3's acceptance bullet.** The plan requires that "a
forced 'not found' produces exactly the message A5's dialog expects". It cannot
be asserted as written: A5's own Decision Log entry records the deliberate
*non*-reuse of this finder ("Its contract also returns the bare string
`"ffmpeg"` on miss, so it cannot answer the presence question"), and
`system_requirements.py` documents itself as the wording source. The two answer
different questions and are decoupled by design. The invariant that *is* real —
and is tested — is that they agree on **which executable is missing**: the
finder's miss value is the `name` of the declared `SystemRequirement`, and with
the same falsy lookup A5's report renders `ffmpeg` with the shared purpose and
install-hint constants.

**Stage 1 gate evidence (per item, 2026-09-27, Windows host, Python 3.14.7):**

B1 + B2 run:

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
1. `python -m ruff check .` → clean · `python -m ruff format --check .` →
   746 files already formatted
2. `python -m mypy .` → `Success: no issues found in 449 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → 0 High / 0 Medium / 51 Low (baseline-identical)
4. bare `python -m pytest -q` → **7140 passed / 3 skipped** (baseline 7090 / 3)
5. coverage → **78.49%** ≥ `fail_under = 75` (D3 decision held; baseline 78.07%)
6. `git grep --cached` secret scans (primary + 4 supplemental patterns) → no
   live secrets. Every hit is pre-existing and benign: documentation prose about
   the scans themselves, `album_art_sync/api/fanart.py:68` (code that *sends*
   `api_key`/`client_key` from a gitignored config, no literal), `preset_key` /
   `no_key` identifier names in existing code, and the pre-existing public
   AcoustID fingerprint fixture in `audio_fingerprinter/tests/conftest.py`. No
   32-hex, no base64-44+, no PEM. None of this change's three files appear.

B3 run (after the `ffmpeg_finder` tests were added):

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
1. `python -m ruff check .` → `All checks passed!` ·
   `python -m ruff format --check .` → 746 files already formatted
2. `python -m mypy .` → `Success: no issues found in 449 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → 0 High / 0 Medium / 51 Low (baseline-identical)
4. bare `python -m pytest -q` → **7159 passed / 3 skipped**
   (baseline 7090 / 3 → **+69** across Stage 1 so far: 15 B1 + 35 B2 + 19 B3)
5. coverage → **78.53%** ≥ `fail_under = 75`
6. `git grep --cached` over this change's files → zero hits; the only
   tree-wide base64 hit remains the pre-existing public fingerprint fixture.

B4 run (after the bounded GUI skip landed):

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
1. `python -m ruff check .` → `All checks passed!` ·
   `python -m ruff format --check .` → 746 files already formatted
2. `python -m mypy .` → `Success: no issues found in 449 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → 0 High / 0 Medium / 51 Low (baseline-identical)
4. bare `python -m pytest -q` → **7180 passed / 3 skipped** (baseline
   7090 / 3 → **+90** across Stage 1: 15 B1 + 35 B2 + 19 B3 + 21 B4), skip
   count **unchanged at 3**, and the new report prints
   `Tk display available : yes` / `Tests skipped for display reasons : 0` /
   `GUI behaviour : VERIFIED in this run`
5. coverage → **78.53%** ≥ `fail_under = 75`
6. `git grep --cached` over this change's files → zero hits.

**B4 headless acceptance evidence** (empirical, full suite, not a unit test):
with `tk.Tk` monkeypatched to raise `TclError` in a `-p` plugin, the bare suite
collects 7,162, **passes 6,398, skips 764, fails 0, errors 0, exit 0**, and
prints `Tests skipped for display reasons : 741 of 7162 collected` plus
`GUI behaviour : NOT VERIFIED in this run`. The 764 total = 741 bounded skips +
23 pre-existing explicit `requires_display` skips. The other 764 tests —
including all of B1/B2/B3's new coverage — actually execute, which is the
regression this item exists to fix.

### Stage 2

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| C1 | 2 | 2026-09-27 | `key_detector/app.py` and `mood_analyzer/app.py`: two ~431-line duplicated app bodies → thin subclasses; the scaffold lives once in `audio_suite_shared/analysis_app_base.py` | Full gate all green, 2026-09-27 (Stage 2 full-gate block below). Item-specific: targeted suites (key_detector + mood_analyzer + audio_suite_shared + master_driver) → `2994 passed, 1 skipped`; then a per-module coverage run over the three files → `333 passed`, with `analysis_app_base.py`, `key_detector/app.py` and `mood_analyzer/app.py` each at **100 %**. The Master Driver card for the Mood Analyzer now has coverage tests (`master_driver/tests/test_ui_cards.py` +42 lines). | Distinct-behaviour tests assert the call that differs (key detection vs. signal mood engine), satisfying the plan's "assert the call, not merely construction" rule. Behaviour-locked pre-refactor: both suites passed against the unmodified code before extraction. |
| C2 | 2 | 2026-09-27 | `noise_reduction/core/file_processor.py` (249 lines) and `pop_click_remover/core/file_processor.py` (272) duplicated workflow → one shared `process_audio_file_inplace()` / `run_inplace_dsp_batch()` in `audio_suite_shared/file_processor_base.py`; tool files are now thin DSP adapters (36 / 34 statements) | Full gate all green, 2026-09-27 (Stage 2 full-gate block below). Item-specific: **pre-refactor locks** run against the unmodified tool code — noise suite `12 passed`, combined tool suites `223 passed`; **post-refactor identical counts** (`12` / `223`) plus `59 passed` in the new `test_file_processor_base.py`. Outcome locks measured on real audio and asserted numerically (noise: 60 Hz hum −4.44 → −20.42 dBFS, **≥ 12 dB** drop asserted; 1 kHz tone drift **≤ 0.25 dB**; declick: first-difference 0.90 → 0.07, untouched first 0.5 s **bit-identical**, frame count/rate unchanged). Dry-run: SHA-256 + mtime unchanged, no output file, export calls 0 dry / 1 live. Undo: real WAV tag snapshot recorded and restored through a real `BatchUndoLog`. Module coverage: shared base **100 %** (266 stmts), noise adapter **100 %** (36), pop adapter **100 %** (34). | The workflow-only consolidation decision is in the Decision Log. The mock-based pop tests were migrated to their new patch homes (`audio_suite_shared.file_processor_base` / `audio_suite_shared.tag_helper`) and pass against the shared implementation. |
| C3 | 2 | 2026-09-27 | `_build_default_registry()`: ~300-line literal → 13-line assembler over the declarative `_DEFAULT_MANIFESTS` tuple; `tool_plugin.py` stayed one module | Full gate all green, 2026-09-27 (Stage 2 full-gate block below). Item-specific: the existing expected-set tests pass **unedited** (21 tests total: +3 new immutability tests, zero edits to the 18 pre-C3 tests); a programmatic HEAD-vs-post-C3 comparison asserted **27 manifests field-for-field identical in declaration order** (astuple comparison; the naive `all == all` cross-module comparison is a dataclass-identity false positive, not drift). | No re-exports were needed — the split kept every name in the same module, so the redundant-alias rule was not triggered; recorded here so its non-use is evidence of scope, not omission. |

Stage 2 gate evidence (2026-09-27, Windows host, Python 3.14.7, ruff 0.15.22,
pytest 9.0.3). Commands 0–6 are the plan-wide Phase Gate; the sub-blocks below
them are item-specific evidence run during the items:

**C2 pre-refactor locks (run before the file-processor rewrite existed):**

3. targeted suites `pop_click_remover/tests` + `noise_reduction/tests` →
   **223 passed** against the unmodified tool code

**C2 post-refactor:**

- module coverage over the three test modules with per-module `--cov=` →
  shared base **100 %**, noise adapter **100 %**, pop adapter **100 %**

**C3 regression check:**

- `_build_default_registry()` reconstructed from `git show HEAD:` and compared
  with the post-C3 registry via `dataclasses.astuple(m) for m in reg.all` →
  lists equal, 27 entries

**Stage 2 full gate (command-by-command, end-state tree):**

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
   (third-party pydub SyntaxWarnings; the Windows `-x` separator mismatch is
   the documented pre-existing behaviour)
1. `python -m ruff check .` → `All checks passed!` ·
   `python -m ruff format --check .` → **749 files already formatted**
2. `python -m mypy .` → `Success: no issues found in 450 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → **0 High / 0 Medium / 51 Low** (baseline-identical)
4. bare `python -m pytest -q` → **7332 passed / 3 skipped** (Stage 1 close
   baseline 7180 / 3 → **+152** new tests across C1–C3), coverage
   **79.56 % ≥ 75** (D3 decision held)
5. `git grep --cached` secret scans (primary + 4 supplemental patterns) over
   the 15 staged Stage 2 files → **zero hits inside the change**; the only
   tree-wide hits are the pre-existing documented/benign set (gitignored-config
   prose, `fanart.py:68` code that *sends* keys read from a gitignored config,
   `preset_key`/`no_key` identifier names, and the public AcoustID fingerprint
   fixture). No 32-hex, no base64-44+, no PEM.

## Stage 3

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| D1 | 3 | 2026-09-27 | marker contract: 273 `integration` + 30 `hardware` tests collected-and-run by every default session → **bare run summary reports 30 deselected**; `pytest -m hardware` collects the full mocked-hardware set (30) through the plain CLI override; an ffmpeg/ffprobe-missing host auto-skips **each integration test** with a reason naming the missing executables, bounded to the marker | Full gate all green, 2026-09-27 (commit `99cc90a`; end-state block below). Item-specific: `tests/test_pyproject_config.py` marker locks **10 passed** (config lock parsed with `tomllib`; full-tree subprocess contract: default-run deselect count == hardware-set size, every hardware id from `cd_ripper/tests`, integration ids ⊆ default selection; pytester runs against a byte-copy of the real conftest: ffmpeg-missing sandbox → 1 passed / 1 skipped with the single `SKIPPED` group carrying the reason "fake ffmpeg, fake ffprobe not found on PATH"; the presence sandbox **self-inverts** on a host without the binaries; the `-m hardware` CLI override runs the opt-in sample). Bare full suite **7312 passed / 3 skipped / 30 deselected**, 0 failed. | Deselect mechanism chosen **in `addopts`** (the plan's own `-m "not hardware"`) rather than a conftest item-filter: CLI args come after addopts, so the documented `pytest -m hardware` opt-in overrides cleanly, and the deselected 30 leave the collection, the summary line and the coverage denominator consistently. Marker-doc audit: the only tree text describing marker behaviour (`cd_ripper/tests/test_ripper_core.py:1209`, "Mark with ``-m 'not hardware'`` to exclude from CI") described the contract this item now implements — no stale doc to update. **Defect discovered in working code, fixed in this same change (Decision Log):** B1's corrupt-file pool test pinned one decode-failure branch; uv.lock resolves librosa 1.0.0 on py≥3.12 (0.11.0 on py<3.12) and librosa 1.0 **removed the audioread fallback**, so the corrupt container now takes the *decoder-raised* branch ("Could not decode audio file …"), not the *empty-decode* branch ("too short to analyse"). The batch test is corrected to the backend-neutral batch contract (status="error", non-empty reported message, batch completes) with both branch texts pinned where they belonged — `test_analysis_loader.py`. |
| D2 | 3 | 2026-09-27 | `[tool.coverage.report] exclude_lines` no longer carries any syntax-pattern exclusion broad enough to hide arbitrary error handling; 17 production guard sites classified line-by-line | Full gate all green, 2026-09-27 (commit `401fb3b`; end-state block below). Item-specific: config locks +3 (no `except ImportError` / `raise AudioMissingDependencyError` pattern may return; the universal exclusions untouched; `fail_under == 75` asserted — decision D3 cannot be absorbed). Per-line delta (acceptance "explained line-by-line in the Completion Log"): **(a) well hidden and executed without a pragma (7 sites)** — `album_art_normalizer/core/art_processor.py:22` (pre-existing pragma; `sys.exit` guard unexercisable in-process), `asx_extractor/core/file_ops.py:32` (send2trash not installed → branch *executes* at import), `library_stats/app.py:39` (matplotlib not declared → branch *executes*), `audio_enhancer/core/tags.py:25` (executed during the existing `TestCopyTags` module-reload test), `audio_enhancer/core/tags.py:42` (function-level, already exercised by that test), `audio_enhancer/core/ffmpeg_io.py:81,:93` (existing `TestRequireFfmpeg`/`TestRequireFfprobe` raise-path tests); **(b) genuinely unreachable in a valid install → per-line `# pragma: no cover` with reason (9 sites)** — `tag_field_updater/core/processor.py:30` (mutagen hard-dep raise), `audio_enhancer/core/processor.py:133` (pedalboard hard-dep mapped handler), `audio_refinery/core/pipeline.py:338` (first-party import guard, broken-suite-only), `audio_enhancer/core/inspector.py:13`, `file_reorganizer/core/engine.py:23`, `replaygain_analyzer/core/file_processor.py:37`, `replaygain_analyzer/core/tag_writer.py:30` (mutagen hard-dep fallbacks), `audio_suite_shared/security/key_manager.py:25` (cryptography hard-dep; the disabled-encryption behaviour itself stays exercised via `TestEncryptionDisabled`) and `cd_ripper/core/disc.py:29,:37` (declared OPTIONAL extras; every decision point they down-select already tested via `HAS_DISCID`/`HAS_MBZ` flag patches); **(c) exercisable, so tested instead of excluded (2 sites)** — `audio_suite_shared/styles.py:16` (module reload under a missing winaccent asserts the real degradation: placeholder palette holds, no accent attribute lookup) and `master_driver/ui/cards/palette_card.py:99` (function-level import under `sys.modules["winaccent"]=None`; all palette rows still build). `utilities/*.py` matches sit inside the coverage `omit`, out of scope. Measured: coverage **78.99% → 79.00%** (+5 tests). | The expected drop did not materialise because every pattern-hidden line was either already executed, honestly re-excluded per-line, or genuinely covered by this item's tests — the two newly-exercised sites are the residual honesty gain, and the denominator now includes every reachable error line. Three files re-formatted during the gate (`ruff format`). The lock class also asserts the D3 constraint, per the item's own "do not lower `fail_under`" bullet. |
| D3 | 3 | 2026-09-27 | first fully-honest post-A2/post-D1/D2 number recorded against the unadjusted gate | Full gate all green, 2026-09-27 (end-state block below). Item-specific: bare `python -m pytest -q` → **7317 passed / 3 skipped / 30 deselected**, **0 failed**; coverage **79.00%** measured against **`fail_under = 75`** (decision D3, held — never lowered). | Shortfall: none — the gate clears by 4.00 pt under the honest denominator, so no residual untested regions need scheduling *for the threshold*. The number is lower than the dishonest Stage-2 headline (79.56%) — expected and recorded: the deselected 30 hardware tests no longer execute, and the D1/deselection + the D2 line count changes are the only motions. **Comment-drift finding fixed in the D3 change:** `analysis_loader.py`'s module docstring still described the audioread fallback the py≥3.12 lock removes — corrected (comment-only; compile/ruff/mypy re-run green; loader suite 35 passed). |

Stage 3 gate evidence (2026-09-27, Windows host, Python 3.14.7, ruff 0.15.22,
mypy 1.20.0, pytest 9.0.3 — end-state commands re-run after the D3
comment-fix):

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
   (documented pre-existing third-party pydub `SyntaxWarning` noise)
1. `python -m ruff check .` → `All checks passed!` ·
   `python -m ruff format --check .` → **750 files already formatted**
2. `python -m mypy .` → `Success: no issues found in 450 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → **0 High / 0 Medium / 51 Low** (baseline-identical)
4. bare `python -m pytest -q` → **7317 passed / 3 skipped / 30 deselected**
   (accounting vs Stage 2 close 7332 / 3: −30 hardware deselected by the new
   contract, −1 corrupt-branch test re-judged then fixed, +15 across the three
   Stage 3 test files: 10 D1 marker locks + 3 D2 config locks + 2
   exercisable-guard tests), collection summary prints the deselection
   explicitly
5. coverage → **79.00% ≥ `fail_under = 75`** (D3 decision held) — measured
   with both pattern exclusions gone: the first fully-honest headline number
   of the plan
6. `git grep --cached` secret scans (primary + supplemental 32-hex and
   base64-44+ patterns) → no live secrets in any Stage 3 change; the only
   hits remain the pre-existing documented benign set (`fanart.py:68` code
   sending keys from gitignored config, `preset_key`/`no_key` identifier
   names, the public AcoustID fingerprint fixture, and `test_exceptions.py`
   test-literal strings)

Stage 3 notes:

- **D1 deselect-accounting note:** the deselected 30 hardware tests leave the
  default run the same way B4 bounded display skips — visible in the
  summary line, attributable to the marker contract, and automatically
  excludable from the coverage denominator under pytest's own deselection
  semantics. The honest headline move is a *measurement* change, not hidden
  work.
- **D2 classification note:** the audit's complaint — "a pattern-level
  exclusion cannot distinguish a legitimate guard from an untested error
  path" — is resolved by the per-site split recorded above: the gate now
  sees every error handler that can actually execute, and the two
  exercisable guards run in tests instead of hiding behind the gate.
- Deselect-vs-filter rationale is recorded in Decision Log row "D1
  (deselect mechanism)" below.

### Stage 4

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| E1 | 4 | 2026-09-27 | no README / no `readme` metadata → `README.md` shipped in `[project]`, with a generated 27-tool index and cross-surface registration locks | Full gate all green, 2026-09-27 (commit `3ec5861`; commands 0–6 below). Item-specific: `tests/test_readme.py` → **6 passed** (drift lock: the README's TOOL INDEX block byte-compared against a fresh render from the manifest; registration lock: launcher `.pyw` exists, card module exists per the `master_driver.ui.utilities_window._CARD_MODULE_OVERRIDES` registry, `cli_command` resolves in `audio_suite_shared.cli_app.cli.commands`, guide registered in `guide_to_program` + `.docx` on disk; metadata lock: `readme == "README.md"` and 27 manifests; A5 lock: the README quotes `FFMPEG_PURPOSE`/`FFPROBE_PURPOSE` and all three install hints verbatim from `system_requirements.py`). Bare full suite **7323 passed / 3 skipped / 30 deselected** (Stage 3 close 7317 → **+6**, exactly the new tests), coverage **79.00%**. | Index built with **no third list**: rows come from the manifest table; the guide filename is derived (`<pyw stem>_User_Guide.docx`) with one documented override (`art` → `Album_Art_Synchronizer_User_Guide.docx`), every guide validated against the `guide_to_program` registry (extracted from `platform_utils.py` via `ast` — it is a function-local literal; re-exporting it would have been a production refactor outside E1's scope), and every row validated for an existing `.docx` and existing launcher before it is emitted. The README smoke test is `uv run audiosuite --help` plus a real first tool (`uv run audiosuite normalise "C:\path\to\music" --dry`). Cross-item dependency: the README's contributing pointer targets `CONTRIBUTING.md`/`SECURITY.md`/`CHANGELOG.md`, which E2 creates in the following commit — deliberate, recorded here so E1's dangling links for one commit are a stated decision. |
| E2 | 4 | 2026-09-27 | no LICENSE/no `license` field, no changelog/contributing/security docs → verbatim GPL-3.0 LICENSE + PEP 639 SPDX metadata + three baseline documents | Full gate all green, 2026-09-27 (commit `ed1e67c`; commands 0–6 below). Item-specific: +3 packaging locks in `tests/test_pyproject_config.py` → **16 passed** in that file: `license == "GPL-3.0-or-later"` and `license-files == ["LICENSE"]` (decision D1); `LICENSE` is the **canonical GNU GPL v3 text**, hash-locked to the published SHA-256 `3972dc9744f6499f0f9b2dbf76696f2ae7ad8af9b23dde66d6af86c9dfb36986` (fetched verbatim from gnu.org, never hand-typed; a corrupted or silently reflowed file fails the lock); `CHANGELOG.md`/`CONTRIBUTING.md`/`SECURITY.md` exist and are referenced from `README.md`, which also states `GPL-3.0-or-later` (`git grep -c "GPL-3.0"`: README 1, CONTRIBUTING 1, pyproject 3 — they agree). **`uv sync` verified empirically, not by reading:** exit 0, and `importlib.metadata` shows `License-Expression: GPL-3.0-or-later`, `License-File: LICENSE`, Metadata-Version 2.4. Bare full suite **7326 passed / 3 skipped / 30 deselected** (+3 = the E2 locks), coverage **79.00%**, bandit **0 High / 0 Medium / 51 Low** (baseline-identical). | The field-syntax question the item flagged ("verify against the installed version, do not guess") resolved empirically: the PEP 639 SPDX string form needs **setuptools ≥ 77**, so `[build-system] requires` was raised from `>=68` to `>=77` and the install path re-run to prove it. **Finding discovered by the required `uv sync` check, recorded not deferred:** `uv.lock` was stale against already-declared `[project] dependencies` — `librosa` and `sounddevice` were missing from the base graph and `types-requests` from the dev extra; `uv sync` repaired it (35-line lock update committed in the same change). Nothing was added to declared dependencies by this item; the lock repair is bookkeeping of the *existing* declaration, and CI's `uv sync` would have failed against the stale lock otherwise. |

**Stage 4 gate evidence (2026-09-27, Windows host, Python 3.14.7,
ruff 0.15.22, mypy 1.20.0, pytest 9.0.3 — E1 run at commit `3ec5861`,
E2 run at commit `ed1e67c`):**

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
   (documented pre-existing third-party pydub `SyntaxWarning` noise)
1. `python -m ruff check .` → `All checks passed!`
   `python -m ruff format --check .` → E1: **752 files already formatted**
   (749 → 752: README excluded from formatting by the A1 `*.md` rule;
   generator + test module added). E2 end-state: 752 files (one
   self-reformat of the new E2 test module applied).
2. `python -m mypy .` → `Success: no issues found in 450 source files`
   (both runs; `utilities/` and `tests/` remain under the declared mypy
   excludes)
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → **0 High / 0 Medium / 51 Low** (baseline-identical, both runs)
4. bare `python -m pytest -q` →
   E1: **7323 passed / 3 skipped / 30 deselected** (Stage 3 close
   7317 / 3 → +6, exactly the E1 lock tests);
   E2: **7326 passed / 3 skipped / 30 deselected** (+3, the E2 packaging
   locks); skip count unchanged at the 3 pre-existing platform probes
5. coverage → **79.00% ≥ `fail_under = 75`** (D3 decision held; unchanged —
   documentation/metadata changes touch no measured source)
6. `git grep --cached` secret scans (primary + 4 supplemental patterns) →
   **zero hits inside the Stage 4 changes** (verified per-item against the
   staged file set); tree-wide hits remain the documented pre-existing
   benign set (gitignored-config prose, `fanart.py:68` code *sending* keys
   from gitignored config, `preset_key`/`no_key` identifier names, and the
   public AcoustID fingerprint fixture). No 32-hex, no base64-44+, no PEM.

Stage 4 notes:

- The Stage 4 note's own rule was obeyed: the README's ffmpeg section is
  the `system_requirements.py` wording (purpose sentences + the three
  install commands) copied verbatim and locked by
  `TestFfmpegWording` in `tests/test_readme.py` — the same invariant A5
  gave the 9 dependent tools' guides, extended to the README, so the
  dialog, the guides and the README cannot drift apart.
- `CODE_OF_CONDUCT.md` was **not** added (E2 leaves it to the maintainer's
  explicit policy decision — see Decision Log).
- The A5-not-reused seam was not reopened here: E1's lock test reuses the
  shared constants (`FFMPEG_PURPOSE`, `install_hints`), not the finder.

### Stage 5

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| F1 | 5 | 2026-09-28 | 0 measured-outcome vectors across the analysis family → **60 new vectors** in 5 existing per-module test files, no production line touched | Full gate all green, 2026-09-28 (Stage 5 gate block below). Item-specific: combined five-family run **755 passed**; `key_detector/tests` 174, `tempo_analyzer/tests` 149, `mood_analyzer/tests` 45, `bpm_analyzer/tests` 36, `test_analysis_loader.py` 44. Bare full suite **7385 passed / 3 skipped / 30 deselected** at F1 close, coverage **79.01%**. `git status` at F1 close: **7 modified files, all under `*/tests/`** — the additive-only proof. | Ground truth is constructed, never recorded: E+B dyad → E; all 12 major + 12 minor triads via the *internal* sharp `_KEYS` table (locked by `test_key_name_domain_is_the_internal_sharp_table` so a table change is loud); I-IV-V-I → C and the G pop loop → G; monophone → its own pitch class; white noise → a declared low-confidence band. BPM: 30 s seeded click trains at 90/100/120/140/165/172 BPM × 3 seeds, tolerance **±4 BPM declared** from onset-grid rounding, plus octave correction, silence clamp and repeatability. Tempo: every integer BPM 1–1000 resolves under all 7 schemes with band-count assertions. Mood: equal-weight major/minor triads, the one-semitone mode pair, C progression, RMS/arousal monotonicity and the exact silence threshold — all asserting the **valence sign**, never a self-consistent read-back. Loader: known-RMS broadband noise through a real 16-bit WAV encode/decode, tolerance derived from 16-bit quantisation rather than fitted to the output. No commercial audio, no `xfail`, no `skip` added. The F1 white-noise vector was left asserting a *band*, not a key, so it could be handed to F2. |
| F2 | 5 | 2026-09-28 | `detect_key` returned a key with no confidence and fabricated one for atonal material → `analyze_key()` returns a `KeyAnalysis` (key, confidence, winner/runner-up correlations, low-confidence flag) over an explicit `correlation` × `weighting` parameter, with a documented `'Unknown'` fallback | Full gate all green, 2026-09-28 (Stage 5 gate block below, same run as F1). Item-specific: `key_detector/tests/test_key_engine.py` **87 passed** (was 67 at F1 close, +20 F2 tests); the four F1 families re-run at **unchanged tolerances, 770 passed**; bare full suite **7406 passed / 3 skipped / 30 deselected**, coverage **79.03% ≥ 75**; `python -m mypy .` → **0 issues in 450 files**; bandit **0 High / 0 Medium / 51 Low** (baseline-identical); `git diff pyproject.toml` → **empty** (the no-new-dependency acceptance clause). | **Before/after on real material** (overtone-rich, multi-voice I-IV-V-I in C, written to a real 16-bit PCM WAV and read back through `analysis_loader` — the tool's own decode path, so the measurement is of decoded audio, not of engine state): tonal passage, key `C` under **both** paths, confidence 1.0000 under both (saturated); the informative column is the margin, pearson 0.3765 → cosine 0.0979. Atonal complement (seeded white noise, same decode path): pearson margin 0.0462 / confidence 0.2311, cosine margin 0.0015 / confidence 0.0190 — both fall back, which is why the margin comparison matters rather than the single outcome. Profiles were **not** re-tuned (the item's own circularity rule). `correlation="pearson"` is retained for compatibility and is asserted to still resolve all 24 chromatic keys; it is *not* recommended, and `test_only_cosine_reliably_refuses_to_name_a_key_for_noise` pins the reason: across 4 noise seeds Pearson fabricates a confident key for two (`'Em'` 0.8995, `'C#m'` 0.6565) where cosine falls back on all four. The threshold 0.25 is placed between the highest measured atonal confidence (DC offset, 0.180) and the lowest measured genuine one (monophone, 0.286), and deliberately leans toward the tonal side. |

**Stage 5 gate evidence (2026-09-28, Windows host, Python 3.14.7,
ruff 0.15.22, mypy 1.20.0, pytest 9.0.3 — one run covering both F1 and F2):

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
   (documented pre-existing third-party pydub `SyntaxWarning` noise)
1. `python -m ruff check .` → `All checks passed!`
   `python -m ruff format --check .` → **752 files already formatted**
   (unchanged from the Stage 4 end state: no file added, and the two F2
   files were re-formatted in place)
2. `python -m mypy .` → `Success: no issues found in 450 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → **0 High / 0 Medium / 51 Low** (baseline-identical)
4. bare `python -m pytest -q` → **7406 passed / 3 skipped / 30 deselected**
   (Stage 4 close 7326 / 3 → **+80**: +60 F1 vectors, +20 F2 confidence and
   real-material tests); the 3 skips remain the pre-existing platform probes
5. coverage → **79.03% ≥ `fail_under = 75`** (D3 decision held; +0.02 over
   the F1 close, since F2 added covered production branches, not excluded
   ones)
6. `git grep --cached` secret scans (primary + 4 supplemental patterns) →
   **zero hits inside the Stage 5 change set**; tree-wide hits are only the
   documented pre-existing benign set (`fanart.py:68` code *sending* keys
   from gitignored config, `preset_key`/`no_key` identifier names, the public
   AcoustID fingerprint fixture, the GPL-3 SHA-256 constant). No 32-hex, no
   base64-44+, no PEM.

Stage 5 notes:

- **F1 and F2 ran in one working tree but are separable**: `git status` at
  F1 close showed 7 modified files, every one under `*/tests/`, which is the
  item's own "additive only" acceptance test; the only production file F2
  touched is `key_detector/core/key_engine.py`, honouring "must stay inside
  `key_engine.py` plus its own tests".
- **An intermittent failure was found and fixed in the same change, not
  deferred** (Decision Log): `audio_suite_shared/tests/test_styles.py`
  `TestWindowsAccentFallback` was order-dependent — `set_active_palette()`
  mutates the module-level `PALETTES` in place, so a test that installed
  `"Windows Accent"` permanently replaced the placeholder an
  `importlib.reload()` was supposed to restore, and whichever of the two
  tests ran second saw an accent-coloured button. Fixed in the test (reload
  before capturing; new
  `test_fallback_survives_a_palette_polluted_by_an_earlier_test`); the
  in-place production mutation is pre-existing and left alone as out of
  scope.
- **The F1 → F2 tolerance handoff was used exactly once, and it was the case
  F1 was built to hand over**: the F1 white-noise vector asserted
  `0.10 <= strength <= 1.0` and a well-formed key; under F2 it asserts
  `'Unknown'` and `0.0 <= confidence <= 0.05`. Every other F1 vector keeps its
  F1 tolerance unchanged, and the F1 monophone vector keeps its stated
  *intent* (a bare pitch may only earn a near-floor answer) while its
  measured numbers were re-recorded, because the scoring method changed —
  that re-recording is the F2 evidence, not a loosened tolerance.
- **Five pre-existing key tests asserted a well-formed key for untuned
  material** (impulse, DC offset, near-silence, white noise, a 0.1 s tone).
  Their real contract is "does not crash and does not propagate NaN"; each
  was changed to accept the documented fallback via one named
  `_assert_key_or_fallback` helper, so the no-crash contract is still
  asserted and the fabricated-key expectation is gone. No assertion was
  deleted, skipped or loosened to anything a failing implementation would
  pass.

---

### Stage 6

| Item | Stage | Completed | Baseline → after | Gate Evidence (date + the six commands + pass/coverage counts) | Notes |
|------|-------|-----------|------------------|------------------------------------------------------|-------|
| G1 | 6 | 2026-09-28 | no declared platform support anywhere; the README's claim exceeded the code → **30 distinct branches / 36 sites across 16 modules** classified into 3 tiers (16 portable core / 5 Windows-only / 9 unverified) and rendered into the README; **26 of 27 tools portable core, `cd_ripper` the only Windows-only tool** | Full gate all green, 2026-09-28 (Stage 6 gate block below). Item-specific: `audio_suite_shared/tests/test_platform_support.py` **60 passed**; `test_platform_support.py` + `test_project_version.py` together **79 passed**, both new modules at **100% coverage** (`platform_support` 47 statements, `project_version` 35, 0 missing). | The enumeration is an **exact AST↔declaration bijection**, not a survey: `TestEnumerationLock` re-walks the tree and fails on any undeclared branch, stale declaration, or wrong `occurrences` count, so a new `sys.platform` check cannot be added without classifying it. Scratch-verified (break-and-restore, every file SHA-256-verified restored): falsifying one `occurrences` → `TestEnumerationLock` fails; flipping a tier → the tier-integrity, tool-tier and README-drift locks fail. `key_manager` is classified `tool=None` (shared) because its `icacls` ACL work is allowlisted subprocess hardening, not a *tool* platform dependency. `secure_subprocess`'s MAX_PATH ceiling was **promoted** to portable core with executable evidence (it runs on any host and only the ceiling constant is Windows-shaped). The 9 unverified branches are listed as untested, never as supported. |
| G2 | 6 | 2026-09-28 | 27 tools reachable only by an undocumented flat alphabetical `--help`; `--version` read *installed distribution metadata* (wrong or missing in a source checkout) → `--help` grouped into 3 functional sections + "Other commands"; `--version` reads `[project] version` in `pyproject.toml`; every tool's CLI surface is contract-locked | Full gate all green, 2026-09-28 (same run as G1). Item-specific: `audio_suite_shared/tests/test_cli_app.py` **87 passed** (was 45); `test_project_version.py` **19 passed**, `project_version.py` at **100% coverage**. `audiosuite --version` → `audiosuite, version 1.0.0`, equal to `[project] version` and cross-checked against `tomllib`. `audio_suite_shared/tests/test_tool_plugin.py` updated for `refine`. | `audio_refinery.cli_command` was **`None` while the `refine` subcommand existed** — the manifest was lying, not the CLI, so the manifest was corrected (the pre-existing gap table is derived from the manifest, so it had to agree). Scratch-verified (SHA-256-verified restore): commenting out `import bpm_analyzer.cli` → **4 contract tests fail** (the subcommand lock, the top-level-help lock, the grouping render lock, and the exactly-one-group lock), which is the plan's acceptance criterion demonstrated rather than asserted; hardcoding the version → **4 version tests fail**. Grouping is **rendering-only**: `list_commands()` is untouched, asserted to stay flat and sorted. `_command_groups` buckets by the manifest's own `category`, and a command with no manifest entry lands in "Other commands", so a newly registered command cannot be silently dropped. **17 of 26 subcommand help strings deliberately differ from the manifest description** (richer CLI docstrings vs UI tooltips) — measured, not assumed, and the contract asserts the *mechanism* rather than textual equality. `undo_tag_edits` is the one declared GUI-only gap with a stated reason; `test_no_undeclared_gap_below` fails if a *new* tool appears without a subcommand, and also fails on a stale entry. |

**Stage 6 gate evidence (2026-09-28, Windows host, Python 3.14.7,
ruff 0.15.22, mypy 1.20.0, pytest 9.0.3 — one run covering both G1 and G2):

0. `python -X utf8 -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
   (documented pre-existing third-party pydub `SyntaxWarning` noise)
1. `python -m ruff check .` → `All checks passed!`
   `python -m ruff format --check .` → **757 files already formatted**
   (was 752: +5 files added by Stage 6)
2. `python -m mypy .` → `Success: no issues found in 452 source files`
   (was 450: +`platform_support.py`, +`project_version.py`)
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   → **0 High / 0 Medium / 51 Low** (baseline-identical)
4. bare `python -m pytest -q` → **7520 passed / 3 skipped / 30 deselected**
   (Stage 5 close 7406 / 3 → **+114**: the G1 matrix/enumeration/portable/attribution
   tests, the 19 version tests, the G2 contract tests, and the registry assertions
   that moved with the `refine` manifest correction);
   the 3 skips remain the pre-existing platform probes
5. coverage → **79.11% ≥ `fail_under = 75`** (D3 decision held; +0.08 over the
   Stage 5 close, since both new modules are at 100% and nothing was excluded)
6. secret scans (primary + 4 supplemental patterns, over the 6 modified and 5 new
   files) → **7 hits, all benign and manually inspected**: 6 × the word "token"
   in `test_platform_support.py`, where it means a *source-code* platform token
   (`for token in ("os.name", "sys.platform", ...)`), and 1 × the tool name
   `key_manager` in the README. No 32-hex, no base64-44+, no PEM, no key value.

Stage 6 notes:

- **The two gaps found while implementing G1/G2 were fixed in this change, not
  deferred** (Decision Log). (a) The branch scan's directory exclusion list
  contains `tests`, and the *skip-attribution* walk reused it — so the
  attribution test silently scanned **zero** files and would have passed
  vacuously forever. The two walks now have separate filters, the second
  deliberately inverted (a platform token in a test is a mock, not a branch).
  (b) The skip detector read only the `reason=` keyword, so `pytest.skip("…")`
  — where the message *is* the reason and the condition lives in the enclosing
  `if` — was reported as "a platform skip with no reason". Both spellings are
  now handled, via a parent map.
- **`os.name` is not `sys.platform`, and patching the wrong one produces a
  measurement of a platform that does not exist** (Decision Log). With
  `os.name="posix"` on Windows, `pathlib.Path()` constructs a `PosixPath`, so
  a "posix" CLI test measures a Windows/POSIX hybrid. The portable-CLI tests
  patch `sys.platform` only, and a regression test locks that distinction.
- **The scratch check was itself wrong on the first run** and the fix is the
  useful part: the PowerShell helper typed its pytest argument as `[string]`,
  so the array collapsed and pytest received a single character; the harness
  then matched the string `ERROR` in pytest's usage message and reported
  "LOCK FIRED" for a run that had never executed a test. The verdict now keys
  on a `FAILED`/`ERROR` *test* line and the argument is `[string[]]`. A
  verification harness that cannot fail is worse than none.
- **A pre-existing defect found in passing, now resolved by the 3.11 floor
  decision** (see the Decision Log rows of 2026-09-28): `tests/test_readme.py`
  had a bare module-scope `import tomllib` (line 30) and could not be collected
  on 3.10 — proven by running it with `sys.modules["tomllib"] = None`, which
  failed with `ModuleNotFoundError`. `tests/test_pyproject_config.py` was
  *first* reported as affected and that was **wrong**; re-verified by AST, it
  already guarded the import and carried three `skipif`s, so the blast radius
  was **one file**. Rather than patching the import, the maintainer raised the
  suite floor to Python 3.11 (decision below), which resolved the defect at
  its root: `tomllib` is standard library on every supported interpreter, the
  `test_readme.py` import is legal as written, and the guards/`skipif`s that
  existed only for the 3.10 leg were deleted rather than left as dead code.

---


## Decision Log

| Date | Item | Decision | Rationale |
|------|------|----------|-----------|
| 2026-09-26 | (scope) | **D1 licence RESOLVED: GPL-3.0** — maintainer (Wilte) accepted the recommendation | Matches the heaviest dependency (`pedalboard`, GPL-3.0) and the AGPL-rejected research surface. Confirmed before Stage 4 opens, as the decision required. |
| 2026-09-26 | (scope) | **D2 key engine RESOLVED: self-contained profile correlation; `madmom` and `essentia` rejected** — maintainer (Wilte) accepted the recommendation | `madmom` is BSD **+ CC BY-NC-SA models**, sdist-only with no wheel, needs Cython at build time, and failed to install on Python 3.14.7 with `ModuleNotFoundError: No module named 'Cython'`. `essentia` is AGPL (incompatible with a GPL-3.0 non-AGPL distribution) and its wheels stop at CPython 3.12. An earlier draft of the audit discussion described `madmom` as MIT and wheel-ready; that claim is **superseded** by this entry. |
| 2026-09-26 | (scope) | **D3 coverage RESOLVED: hold `fail_under = 75`** — maintainer (Wilte) accepted the recommendation, chosen before the first honest run as the decision required | Lowering it to match the post-A2/post-D2 number would re-institutionalise the finding. First honest (post-A2) number: **78.04%** — above the gate; recorded in the Completion Log. |
| 2026-09-26 | (scope) | **D4 Linux CI RESOLVED: `xvfb` + `python3-tk` + `ffmpeg`, explicit platform skips only** — maintainer (Wilte) accepted the recommendation | The current leg passes while verifying almost nothing. |
| 2026-09-26 | (scope) | **D5 cross-platform RESOLVED: declared matrix + CLI-first portable core** — maintainer (Wilte) accepted the recommendation | Bounds the scope to something testable; the Windows-only subsystems are declared, not silently untested. |
| 2026-09-26 | A1 | `ruff format` exclusion set in `pyproject.toml` as `exclude = ["*.md"]`; the CLI form `--exclude "*.md"` explicitly **not** used | The CLI form *replaces* Ruff's default exclusions rather than adding to them, re-admitting `.venv`. Verified empirically before writing the item. **Implementation note:** on the installed ruff 0.15.22 the stable-mode gate already passes (Markdown code blocks are only formatted in `--preview`); the finding reproduces under `--preview` (99 files flagged incl. `PLAN_audit_priority_actions.md`), and with the exclusion the `.md` set drops out of the `--preview` run too. The exclusion is therefore forward-protective: any future ruff that promotes Markdown formatting to stable would otherwise break the gate or, worse, a `ruff format .` would rewrite a completed plan's record. |
| 2026-09-26 | A2 | `noise_reduction` added to both `testpaths` and coverage `source`; **not** git-tracked-missing | The package is fully tracked with 88 passing tests — the defect is measurement configuration, not VCS. Recorded so a future reader does not re-investigate the wrong thing. **Empirically confirmed:** bare-suite collection rose 6,983 → 7,071 (exactly +88), all pass; coverage 78.26% → **78.04%** (the drop is the honest number — the package's `app.py` 32% / `ui/setup_tab.py` 24% now count in the denominator). |
| 2026-09-26 | A3 | `genre_sync/tests/conftest.py`'s Tk bootstrap deleted entirely, not just the `pytest.skip()` call | The root `conftest.py` already provides the session root, both fixtures, and the skip behaviour. Patching only the `pytest.skip()` line would leave a redundant private root shadowing the shared one. **Empirically confirmed first:** the crash reproduced as documented — bare headless simulation (monkeypatched `tk.Tk` → `TclError`) exits `INTERNAL_ERROR: 3` from `config._do_configure()`, taking down the whole session; post-fix the same simulation exits 0 with attributable per-test skips. **Acceptance deviation:** the literal `grep "pytest.skip" */tests/conftest.py` still matches three *docstring* lines (two in the root conftest's own historical explanation, one in the rewritten `genre_sync` docstring) that document why the pattern is banned. A call-site grep (`^\s*pytest\.skip`) is clean; keeping the ban's documentation is worth more than satisfying the letter of the grep. |
| 2026-09-26 | A4 | Virtual-display form: **`xvfb-run -a --server-args="-screen 0 1920x1080x24" uv run python -m pytest …`** chosen over `DISPLAY=:99` + background `Xvfb` | No background process to clean up, no port hand-allocation, and the wrapper propagates the child's exit status. Explicit screen geometry so Tk widget geometry does not depend on the distro default. Marker `integration`/`hardware` handling deliberately **not** implemented here — the item itself defers the mechanism to Stage 3 D1. The apt step is `runner.os == 'Linux'`-gated and the run step branches on `RUNNER_OS`, so the Windows legs are byte-identical in behaviour. **Evidence status:** YAML parsed + validated, bash branch syntax-checked (`bash -n`), but no CI run exists to cite — this repository has no git remote, so the run URL + Linux passed count remain pending and the item is `[~]`, not `[x]`. |
| 2026-09-26 | A5 | The preflight ffmpeg check is **warning-level, not blocking**; implemented as `report_missing_requirements()` + `WARNING_TITLE` distinct from `BLOCKED_TITLE` | Only the compile gate keeps blocking semantics. A hard exit would break users who only run tools that never shell out to ffmpeg. Distinct titles so a user (or a bug-report screenshot) can tell a warning from a block. `guard_or_exit`'s return contract is unchanged (`verify_suite`'s result is returned verbatim) — the existing lock test passed unmodified. |
| 2026-09-26 | A5 | **Deviation: `ffmpeg_finder` not reused; `shutil.which` behind an injectable `resolver` instead** | `ffmpeg_finder` lives in a *tool* package (`audio_normalizer`); importing it from `audio_suite_shared.preflight` — which every `.pyw` launcher runs before any tool import — inverts the base→tool layering and drags a tool into every launch. Its contract also returns the bare string `"ffmpeg"` on miss, so it cannot answer the presence question. The injectable `resolver` parameter keeps one presence seam (asserted by test to default to `shutil.which`) so B3 can attach a richer discovery mechanism later without re-implementing the check. The finder's untested fallbacks remain B3's scope, untouched. |
| 2026-09-26 | A5 | Guides: System Requirements section added to the **9 ffmpeg-dependent tools'** generators (not all 27) and regenerated; wording locked by test against `system_requirements.py` | Dependent set derived by grepping first-party non-test code for ffmpeg/ffprobe/pydub/AudioSegment: audio_enhancer, audio_normalizer, audio_refinery, cd_ripper, music_format_converter, noise_reduction, pop_click_remover, replaygain_analyzer, silence_trimmer (asx_extractor's cue-split command is shared CLI, but its own tool code has no ffmpeg path). Stating the requirement in a guide for a tool that never shells out to ffmpeg would be inaccurate documentation. `test_system_requirements.py::TestGuideWordingLock` reads the generated `.docx` artifacts and asserts the canonical purpose phrases + install hints appear verbatim, with a real-data negative control (key_detector's guide has no such section), so the dialog wording and the guides cannot drift. Regeneration verified lossless against HEAD for all 9 (paragraph-diff: 0 lost, +5 added each). |
| 2026-09-26 | A6 / (context) | Iteration-4 D1 precedent recorded here, **not** by editing `PLAN_iteration4_remediation.md` | Completed plans are historical records under `AGENTS.md` "Plan Governance". The iteration-4 Decision Log itself states the gate was not re-run before marking the item complete. The per-item gate rule is now stated in "How to read this plan", before the first item. |
| 2026-09-27 | B1 (defect) | **Fixed a real defect in `audio_suite_shared.analysis_loader.check_min_duration`, not the engine.** Writing the item's first corrupt-file test produced a `ZeroDivisionError` from `f"Audio is too short to analyse ({len(y) / sr:.2f}s)"` — a file whose container is corrupt can make librosa fall back to `audioread` and return an **empty array with `sr == 0`**, so the very guard that detects the unusable decode crashed while formatting its own message. The `sr <= 0` case was already part of the guard's condition, so the *detection* was right and only the message was unsafe. | A shared loader is high fan-out, and the "too short" message is what a user sees for every one of the four analysis tools, so the branch needed a real test rather than a mocked one. The fix computes the duration only once the rate is known positive (`len(y) / sr if sr > 0 else 0.0`), leaving the detection logic, the exception type and the message text for the `sr > 0` case byte-identical — the minimal diff, with no engine refactor. Regression-test direction is the point: the guard's own condition decided the file was unusable *before* the crash, so the test asserts the typed `AudioAnalysisError` for a real corrupt `.flac` and a zero-rate signal, and B1's real-process-pool test independently asserts the batch reports that file as an `error` and still completes. Per `AGENTS.md` §7 and this plan's own B1 scope bullet, the defect is fixed in the same change with its regression test and logged here. |
| 2026-09-27 | B3 | **Test the finder as shipped and report the plan/code mismatch; do not add the three branches the plan assumed.** Six of the scope bullets describe a configured path, a cache, and an executability check. The shipped module has none of them: it reads no config, memoises nothing, and gates on `os.path.exists` alone. Fabricating tests for them would mean inventing a specification the code does not implement (and the item's own Risks note forbids exactly that: "the item is a coverage fix, so the existing behaviour is the specification"). | Writing the real tests took 21 of the module's 18 statements to 100% with zero skips, and the mismatch is now a *test* — `test_a_directory_named_like_the_binary_is_accepted` shows the real user-visible consequence of the missing `X_OK` check, and `test_os_access_is_never_consulted` fails loudly if anyone later adds one without updating the tests. That is strictly more useful than a test that asserts an imagined cache. The source-2 gate fix is proposed as a follow-up rather than smuggled in, because B3 is a coverage item and `AGENTS.md` §2 forbids unsolicited changes to working code. The A5 "not found" acceptance bullet is decoupled by A5's own recorded deviation, so the testable invariant (both mechanisms agree on *which* binary is missing) is pinned against the shared constants instead. |
| 2026-09-27 | C2 (scope) | Consolidate the shared **workflow** only; the two DSP algorithms stay separate (dated — row previously undated) | Existing decision retained; the consolidation landed exactly in this shape: `BaseFileProcessor.process_audio_file_inplace()` / `run_inplace_dsp_batch()` and thin per-tool DSP adapters. |
| 2026-09-27 | C2 (defect, scope) | **Two findings preserved, not fixed, inside the behaviour-preservation refactor.** (1) **Dry-run divergence between the twins is a product defect.** `reduce_noise()` short-circuits on `params.dry_run` and returns `was_modified=False`, so a noise dry run reports `SKIP ("Clean")` even on a file it *would* repair; `declick_audio()` always decodes+analyses, so pop dry runs correctly report `FOUND`. The consolidation keeps both behaviours byte-for-byte (the plan's demand); the outcome tests pin the divergence (0 dry / 1 live exports on both sides). (2) **The plan's "undo ... assert the file is restored to the original bytes" is unimplementable as written.** `record_tag_edit_snapshot()` + `_revert_tag_edit()` round-trip the tag payload only (ID3 `TPE1` verified restored on a real WAV); no byte-level undo exists anywhere in the suite. The tests assert the real, shipped contract — tag round-trip — and the gap is reported, not papered over. | Both are pre-existing behaviours, deliberately not "fixed" inside a behaviour-preservation refactor (`AGENTS.md` §2). A follow-up item should make both dry-run reports honest (noise dry runs are misleading today) and settle the undo contract (tag-only vs. byte-level); both change user-visible behaviour and need an owner decision. |
| 2026-09-27 | C2 (defect) | **A scripted C2 edit de-indented the tail of the inherited `process_batch()`, so only the last file of a batch was collected.** The extraction script that moved the manifest-table edit re-indented `results.append(result)` / `completed[0] += 1` / the `progress_callback` block out of the `for f in futures:` loop; four pre-existing `TestProcessBatch` tests caught it in the post-refactor run (`len(results) == 1` for a 3-file batch). Fixed by restoring the loop-level indentation; the four tests are the regression locks and pass unchanged. | Found by the gate, not by review — the existing `process_batch` tests were the designed canary for exactly this class of edit on the shared-executor code the in-place workflow sits on. Now the second time a scripted bulk edit has landed badly (P5 note 4 was the first): re-diff the touched lines after any scripted edit, always. |
| 2026-09-27 | D1 | `hardware` is deselected **by default** with an explicit opt-in (`pytest -m hardware`); `integration` runs wherever ffmpeg is present | The markers were registered but never acted on — 273 + 30 tests ran by default. The opt-in path is documented in `CONTRIBUTING.md` (E2) so it is actually run. |
| 2026-09-27 | D1 (deselect mechanism) | Deselection lives in pytest **`addopts`** (`-m "not hardware"`), not in a conftest item-filter | The plan's own text specifies the addopts form. It also has the better property set: CLI args come after addopts, so the documented `pytest -m hardware` opt-in overrides cleanly (verified by test); the deselected 30 leave collection, the summary line and the coverage denominator under pytest's own semantics (a conftest skip would instead have left 30 *dead* marks in the coverage accounting); and the wiring is testable by running pytest itself against the real config. |
| 2026-09-27 | D1 (defect) | **B1's corrupt-file pool test pinned a host-dependent decode branch; corrected to the backend-neutral batch contract.** The test asserted the corrupt `.flac` reports "too short to analyse" — the *empty-decode* branch produced by librosa ≤ 0.11's audioread fallback. uv.lock resolves librosa **1.0.0 on py≥3.12** (0.11.0 on py<3.12) and librosa 1.0 **removed the audioread fallback**, so the corrupt container now takes the *decoder-raised* branch ("Could not decode audio file …") and the B1 test failed at HEAD. Reproduced both directions empirically (with- and without-D1 tree) before editing. | The loader's contract is unchanged and correctly written for both branches (the `sr <= 0` empty-decode guard is pinned by `_fake_librosa_load`, the raise branch by the real decoder and `test_decoder_exception_raises_audio_codec_error`); what was wrong was asserting one branch's *message* at the *batch* level, where the batch contract is only "status=error, non-empty message, batch completes". Both branch texts are now pinned in `test_analysis_loader.py` (whose fixture comment documents the version split), and the batch test pins the batch outcome. Not a production defect: the engine's behaviour is correct under both library versions; the drift is a lock-version property. The corresponding stale module docstring in `analysis_loader.py` (claiming the fallback unconditionally) was corrected as a comment-only fix in the D3 change. |
| 2026-09-27 | D2 | Broad `except ImportError` coverage exclusion replaced by narrow per-line `pragma: no cover` with reasons | A pattern-level exclusion cannot distinguish a legitimate optional-dependency guard from untested error handling, so the gate cannot see either. Landed with the split recorded in the D2 Completion row: 9 unreachable guards carry pragma+reason, 2 exercisable guards are exercised by tests instead (`styles` reload, `palette_card` sys.modules patch), 7 were already executed or pragma'd, and the config-lock test forbids the broad patterns from returning. |
| 2026-09-27 | D3 (item) | Coverage gate re-baselined at **79.00%** against `fail_under = 75` — decision D3 (hold 75) applied without any threshold movement | The bare full-suite run is now fully honest: `noise_reduction` in the denominator (A2), hardware deselected by the D1 contract, and the D2 exclusions gone. The gate clears by 4.00 pt, so no untested regions need scheduling for the threshold. This is the Stage-3 baseline subsequent stages are judged against. |
| 2026-09-27 | C3 (scope, dated) | Split the manifest **data** out of `_build_default_registry()` into a module-level declarative tuple; do **not** split `tool_plugin.py` into multiple modules | Landed as decided: `_DEFAULT_MANIFESTS` + a 13-line assembler; the file stays one module (anti-creep). The expected-set test passed unedited, and a programmatic HEAD-vs-post-C3 tuple comparison confirmed 27 manifests field-for-field identical in declaration order. |
| 2026-09-27 | C1 / C3 | Module-level `TOOL_ID` aliases: **not restored — zero consumers.** C1 moved the tool ids onto the app classes as `TOOL_ID: ClassVar[str]`; a grep over the consumer surfaces (master_driver cards, CLI imports, the fingerprinter suite that once printed the old constant) shows class-level lookups are the only remaining reference. No `from <tool>.app import TOOL_ID` module-level consumer exists in-tree. | Restoring an alias with no consumer would be speculative API surface (`AGENTS.md` §2). The class-level `ClassVar` is the sanctioned lookup path; the decision is recorded so a future "where did the constant go" surprise has an owner. |
| — | F1 | Vector tests are **additive only** and must pass unchanged against current code | A vector test that "needs" fixing in the same commit destroys the before/after evidence that makes F2 verifiable. |
| — | F2 | No profile re-tuning against the F1 fixtures | Tuning on the test set and then citing it as validation is circular; a labelled corpus would be a separate item. A measured revert is an acceptable outcome. |
| 2026-09-27 | E1 | Tool index built by a generator with **no third list**: rows from the manifest, guide names derived from the launcher (one override), validated against `guide_to_program` (AST-extracted) | The plan allowed either a generated table or a source-of-truth statement; both were done. `guide_to_program` is a function-local literal in `platform_utils.py`, so it is extracted with `ast` rather than re-declared — re-exporting the constant would have been a production refactor outside E1's blast radius. The generator aborts with `[ERROR]` (never emits a dead row) if a guide is unregistered, its `.docx` is missing, or the launcher is missing, so the drift the audit feared fails loudly. The single filename deviation the derivation cannot express (`art` → `Album_Art_Synchronizer_User_Guide.docx`, launcher is `Album_Art_Synch.pyw`) is an explicit, commented override. Card lookup reuses `utilities_window._CARD_MODULE_OVERRIDES` instead of copying the mapping, and `audio_refinery`'s card-less UI (the embedded REFINE tab) is asserted as `refinery_tab.py` instead of being grandfathered silently. |
| 2026-09-27 | E2 (scope) | **Licence metadata form:** PEP 639 SPDX string (`license = "GPL-3.0-or-later"` + `license-files = ["LICENSE"]`), proven by installing, with `[build-system] requires = ["setuptools>=77", "wheel"]` | The item warned "verify against the installed version, do not guess the field syntax". Verified empirically, not by reading docs: `uv sync` (exit 0) and the installed distribution metadata (`importlib.metadata`: `License-Expression: GPL-3.0-or-later`, `License-File: LICENSE`, `Metadata-Version: 2.4`). The SPDX string form is a PEP 639 feature setuptools only parses from 77.0, so the build floor was raised from `>=68` — the same dependency, an explicit version statement, not a new dependency (AGENTS.md §4; the rationale is commented at the field). |
| 2026-09-27 | E2 (scope) | **`SECURITY.md` reporting channel: repository issue tracker, explicitly no SLA**; `CODE_OF_CONDUCT.md` deliberately not added | The plan's constraint was "short and honest; do not promise a response time the maintainer has not agreed to". The repository has no remote and no configured private channel, so the honest statement is exactly that: report via an issue titled `[security]`, no promised response time, and no aspirational SLA. The two technical statements the item required are explicit: the `audio_suite_shared/secure_subprocess.py` allowlist surface, and "raw audio and tag files are untrusted input". A code of conduct is a policy decision the maintainer has not made; the item itself says it is optional and it was left out rather than invented. |
| 2026-09-27 | E2 (finding) | **`uv sync` (the item's own acceptance check) found a stale `uv.lock`; the repaired lock is committed** | First plain `uv sync` run in the plan (earlier stages ran pytest/ruff/mypy/bandit, which do not need the lock refreshed). It repaired three entries for dependencies that were **already declared** in `[project] dependencies`/extras: `librosa` and `sounddevice` were missing from the base package graph and `types-requests` from the dev extra. No declared dependency changed in Stage 4 — the update is bookkeeping of the existing declaration, and committing the repaired lock (which CI consumed) is required by the AGENTS.md "`uv.lock` is committed" rule. Left uncommented here because a lock repair surfacing under a baseline documentation item is exactly the kind of "discovered while implementing" event the plan mandates recording. |
| 2026-09-27 | E1/E2 (order) | **README ↔ baseline docs cross-reference completes across the two item commits** | E1's README links `CONTRIBUTING.md`, `SECURITY.md` and `CHANGELOG.md` (created by E2 in the following commit), and E2's acceptance "referenced from `README.md`" is satisfied by E1's lock test. The gap is one commit wide inside the same session and is recorded on both Completion Log rows rather than silently absorbed. |
| 2026-09-28 | F1 (scope) | **F1 landed test-only: no production file was modified.** The additive-only proof is `git status` at F1 close — 7 modified files, every one under `*/tests/`. | F1's own Risks note warns that "fixing a failing vector in the same commit destroys the before/after evidence that makes F2 verifiable", so the vectors were written to *record* current behaviour (including the vectors whose measured values F2 later had to re-record) rather than to assert what the engine ought to do. The white-noise vector was deliberately left as a declared **band** rather than a key, precisely so F2 could hand it over. |
| 2026-09-28 | F2 (algorithm) | **Cosine correlation is the default; Pearson is retained and documented as compatibility-only, not recommended.** Both ship, as the item requires an explicit documented parameter — but the default is chosen by measurement, not preference. | The deciding evidence is that Pearson's winner-to-runner-up *margin* for white noise is unstable, not merely small: across 4 noise seeds it names a key for two of them and calls it confident (`'Em'` 0.8995, `'C#m'` 0.6565), and its measured noise margins span 0.029–0.180, which **overlaps** the major-triad band (0.118–0.122) — so no threshold can separate them and a fallback is unreachable on that path. Cosine separates cleanly (noise 0.0007–0.0024 vs triads 0.053–0.068, progressions 0.037–0.063). `test_only_cosine_reliably_refuses_to_name_a_key_for_noise` pins this so a future change cannot quietly move the default. STFT chroma was measured and **rejected** in favour of CQT: it mis-keyed most triads in probing, so it is not shipped and is not offered as an option. The K-S profiles themselves were **not** re-tuned, per the item's own circularity rule. |
| 2026-09-28 | F2 (threshold) | **Low-confidence threshold 0.25, placed between the highest measured atonal confidence (0.180, a DC offset) and the lowest measured genuine one (0.286, a monophone) — deliberately leaning toward the tonal side.** | The constant is chosen from a *gap between two measured classes*, not fitted to make a vector pass, and it is exposed as `low_confidence_threshold` (asserted honoured: 0.0 still names `C`, 1.0 forces the fallback without altering the underlying confidence). The lean is a stated policy choice: for a key detector, declining to name a key when the material really has one is the worse failure than reporting a low-confidence guess, so the boundary sits closer to the atonal ceiling than to the tonal floor. Consequence, accepted and tested: a bare monophone is still *named* (just above threshold, at 0.286–0.297) rather than falling back — which is what preserves F1's original intent for that vector, that a monophone may only earn a near-floor answer. |
| 2026-09-28 | F2 (interface) | **`detect_key_with_strength`'s second element is now the stated confidence.** Signature unchanged; only the meaning is redefined, and that redefinition is what makes an `'Unknown'` fallback safe for the existing consumer. | `mood_analyzer.core.signal_mood_engine` already weights a major/minor valence offset by this value, and it treats **any non-`m` key as major** — so a fallback key alone would have injected a spurious positive-valence contribution into every atonal file. Carrying the near-zero confidence alongside it makes the fallback self-neutralising, and that is asserted from the consumer's perspective (`test_fallback_confidence_is_near_zero_so_consumers_cannot_be_biased`). `analyze_key()` was **added** for the full picture rather than replacing anything, so the pre-F2 entry points and all callers keep working. |
| 2026-09-28 | F2 (scope, known gap) | **`key_detector.core.file_processor` writes `detect_key`'s result straight to a file's KEY tag, so untuned material will now be tagged `"Unknown"`. Deliberately left unfixed, and recorded here as a follow-up.** | The item's own scope says the change "must stay inside `key_engine.py` plus its own tests" and "keep the public interface and its callers unchanged", so filtering the fallback out at the tag writer is out of scope by the plan's own instruction — `AGENTS.md` §2 forbids the unrequested change. The behaviour is stated in `key_engine`'s module docstring rather than left to be discovered. A follow-up item should decide whether an untuned file is left untagged, tagged `'Unknown'`, or reported as skipped, and add a real-tag regression test for whichever is chosen. |
| 2026-09-28 | F1/F2 (material) | **The F2 "real material" measurement uses a constructed, overtone-rich, multi-voice excerpt decoded through the real `analysis_loader` path — not a commercial recording.** | No third-party audio ships in this repository, librosa bundles none, and `librosa.example()` would make the test suite depend on a network fetch, so a genuine recording was not obtainable offline. The constraint F1 already set (no commercial audio, fixtures unambiguously redistributable) is honoured by construction instead: the excerpt is synthesised from a 6-partial series with a bass voice, per-note attack/release envelopes and a musical tempo, written to a **real 16-bit PCM WAV** and read back through the tool's own decoder, so the assertion is of decoded audio rather than of engine state — which is the substance of the AGENTS.md outcome-correctness rule. The test docstring states plainly that the material is constructed, so no future reader mistakes it for a recording. A labelled human-annotated corpus remains the honest way to settle the item's "mis-keys more often than a user expects" claim, and is left as future work rather than simulated. |
| 2026-09-28 | (defect, cross-item) | **Intermittent `test_styles.py` failure found during the Stage 5 gate and fixed in the same change** — `TestWindowsAccentFallback` was order-dependent. | `set_active_palette()` mutates the module-level `PALETTES` dict **in place**, so a test installing `"Windows Accent"` permanently replaced the placeholder that the test's own `importlib.reload()` was supposed to restore; whichever of the two ran second then saw an accent-coloured button and failed. It surfaced only on the *second* full-suite run, which is why the pre-F1 baseline was re-taken. Fixed in the test — reload before capturing the placeholder — plus a new `test_fallback_survives_a_palette_polluted_by_an_earlier_test` that deterministically reproduces the pollution, so the fix is proven rather than assumed (the pre-fix body was run under the same pollution and failed). The underlying in-place production mutation is pre-existing, is a real coupling wart, and was deliberately **not** changed here: it is out of Stage 5's scope and a fix would change behaviour for every caller. Recorded as a follow-up. |
| 2026-09-28 | G1 (defect, self-inflicted) | **The skip-attribution walk scanned zero files and would have passed vacuously forever** — found and fixed in the same change. | The branch-enumeration walk excludes test directories (a platform token in a test is a mock, not a branch) via a shared `_EXCLUDED_DIRS` set that contains `"tests"`. The new *skip-attribution* walk reused that same set while needing the exact opposite, so `rel.parts` matching happened *after* the exclusion and every candidate was dropped: `test_cd_ripper_declares_its_win32_requirement` found no gated skips and failed on the first run, which is how it surfaced rather than passing silently — the "expect a non-empty set" assertion caught it. Fixed by giving the two walks separate filters (`ignored = _EXCLUDED_DIRS - {"test", "tests"}`), with a docstring stating why the inversion is deliberate. The transferable lesson: **a shared "exclude" constant reused by a scan that needs the opposite silently empties the scan, and only an assertion that the result is non-empty catches it.** |
| 2026-09-28 | G1 (defect, self-inflicted) | **The skip detector reported `pytest.skip("msg")` as a platform skip with no reason** — fixed in the same change. | It read only the `reason=` keyword, which exists for `pytest.mark.skipif(<cond>, reason=...)` but *not* for `pytest.skip("...")`, where the message **is** the reason and the platform condition lives in the enclosing `if` (e.g. `cd_ripper/tests/test_disc_core.py:666`, guarded by `if not hasattr(ctypes, "windll")`). Both spellings are now handled via an AST parent map. Consequence had it shipped: a legitimate, correctly-reasoned Windows skip would have been reported as reasonless, and the new "every platform skip names its platform requirement" lock would have pushed an author towards *removing* a correct skip to satisfy the test. |
| 2026-09-28 | G1 (method) | **`os.name` is not `sys.platform`, and simulating a platform by patching the wrong one measures a platform that does not exist.** | Discovered while writing the portable-core CLI test: `sys.platform` is what the 36 declared branches branch on, but it is tempting to patch `os.name` instead, since `os.name` is what `pathlib` and `os.path` consult. With `os.name = "posix"` on a Windows host, `pathlib.Path()` returns a **`PosixPath`** — a Windows/POSIX hybrid that exists on no real system, and a test asserting behaviour on it is measuring a fiction. The portable tests therefore patch `sys.platform` only, and a dedicated regression test pins the distinction by asserting the `PosixPath` consequence rather than merely asserting the patch target. `test_platform_support.py`'s module docstring records it so the next author does not "helpfully" add `os.name`. |
| 2026-09-28 | G1 (classification) | **`key_manager` is classified `tool=None` (shared) even though it contains the Windows-only `icacls` ACL path.** | A branch belongs to a *tool* only when it constrains that tool's usability. `key_manager`'s `icacls` work is allowlisted subprocess hardening on a POSIX-capable filesystem (Iteration-4 K1), not a Windows dependency, so counting it would have demoted a portable tool on the strength of a hardening detail. `secure_subprocess`'s MAX_PATH ceiling was treated the same way and **promoted to portable core** once an executable test showed the code runs on any host and only the ceiling *constant* is Windows-shaped. The matrix distinguishes "the code has a platform branch" from "the tool needs that platform", and `TestToolTiers` locks that `cd_ripper` is the only Windows-only tool. |
| 2026-09-28 | G2 (scope, plan's own open question) | **The golden contract is TWO tests, split by surface, not one** — answering the plan's "decide whether they are one test or two, and record the choice". | `TestRegistrationLock` (E1, `tests/test_readme.py`) owns the **static** surfaces: launcher `.pyw`, Master Driver card module with the `audio_refinery` embedded-tab exception, `guide_to_program` entry, and the `.docx` artifact. `TestDiscoverabilityContract` (G2, `audio_suite_shared/tests/test_cli_app.py`) owns the **runtime** surfaces: subcommand resolves, `--help` renders, grouped-help completeness, `--version` agreement. One test would have had to import both the filesystem and Click concerns, and the decisive reason to keep them apart is that E1's card-overrides registry is *data* the contract must not duplicate — a second copy of that list is exactly the parallel-registry failure the plan forbids. `test_static_surfaces_are_covered_by_the_e1_test` therefore asserts the *other* half still exists, so the split cannot silently lose a surface. |
| 2026-09-28 | G2 (defect, pre-existing) | **`audio_refinery.cli_command` was `None` while the `refine` subcommand existed — the manifest was corrected, not the CLI.** | The manifest is the single source of truth the new contract reads, so a missing entry would have made `audiosuite --help` grouping drop the tool into "Other commands" and left the suite's own gap table claiming a tool was CLI-less when it was not. The existing pre-G2 gap table is *derived* from the manifest, so it had to move with it, which is why the correction was not optional tidying. `test_tool_plugin.py`'s expected set gained `refine` in lockstep. |
| 2026-09-28 | G2 (measurement) | **17 of 26 subcommand help strings do not match their manifest description, and the contract does not require them to.** | Checked before asserting: 9 match verbatim, 17 differ (e.g. manifest "Fingerprint audio and identify tracks via AcoustID" vs the CLI's longer "Generate Chromaprint fingerprints and identify tracks via AcoustID."). The two are different audiences — a UI tooltip versus a CLI docstring — so requiring textual equality would have forced either 17 rewrites of correct help text or a weakened assertion. The contract instead asserts the *mechanism* (the subcommand exists, `--help` exits 0 and renders, the command is grouped and listed), which is what the audit finding is actually about. |
| 2026-09-28 | (process) | **A verification harness that cannot fail is worse than none — the G2 scratch check reported "LOCK FIRED" on a run that executed no test.** | The PowerShell helper typed its pytest argument `[string]`, so the `[string[]]` array collapsed and pytest received a single character (`ERROR: file or directory not found: a`). The verdict then matched the literal `ERROR` in pytest's usage message, so all four checks "passed" — vacuously, on a run where no test was collected. Caught because the summary line was empty and the reported failure was obviously not a test name. Fixed by typing the parameter `[string[]]` and keying the verdict on a `FAILED`/`ERROR` *test* line; all four checks were then re-run and each fired on the expected test. Every restore is SHA-256-verified, so the harness cannot leave a mutated file behind. Generalises to any break-and-restore gate. |
| 2026-09-28 | (defect, cross-item, **RESOLVED — by the 3.11 floor decision**) | **`tests/test_readme.py` could not be collected on Python 3.10** (bare module-scope `import tomllib` at line 30). **Resolved at the root, not by patching the import:** the floor decision (two rows down) makes `tomllib` standard library on every supported interpreter, so the import is legal exactly as written and is unchanged. | **Correction to an earlier finding in this session:** the same defect was *first* reported against both `tests/test_readme.py` and `tests/test_pyproject_config.py`. That was wrong, and re-verified by AST rather than grep: `test_pyproject_config.py` already guards the import (`try: import tomllib … except ModuleNotFoundError: _HAS_TOMLLIB = False`) and carries three `skipif`s naming the constraint, so it collects fine on 3.10. **Only `test_readme.py:30` is unguarded**, and that is proven, not inferred: running the file with `sys.modules["tomllib"] = None` fails with `ModuleNotFoundError: import of tomllib halted`. The blast radius is one file, not two. The genuine open question behind it is the **minimum-version decision** (next row), not the import. |
| 2026-09-28 | (packaging, **DECIDED — approved and implemented same session**) | **`requires-python = ">=3.10"` is no longer honest, and the right fix is to raise the floor to 3.11 — not to add a TOML dependency.** The argument below persuaded; the decision, the change list, and the gate evidence are in the next row. | The maintainer's question ("if `tomllib` is stdlib from 3.11, why not require 3.11?") is correct, and the evidence supports it well beyond TOML. (1) **The floor is already false in practice**: the committed `uv.lock` resolves *different* numeric libraries per Python — the `python_full_version < '3.11'` markers pin **numpy 2.2.6 + scipy 1.15.3**, while 3.12+ gets **numpy 2.5.2 + scipy 1.18.0**. Current numpy (2.3.5) and scipy (1.17.0) both declare `Requires-Python >= 3.11`, so a 3.10 user is pinned to a *stale* numeric stack. For an audio-DSP suite whose correctness claims are measured (ST 1/2), a green 3.10 leg validates a dependency graph **nobody develops or ships against** — the dev host is 3.14.7 and the `.pyw` tools launch on that global interpreter. That is a misleading safety net, not a useful one. (2) **The 3.10 leg is already known-degraded in our own docs**: `CONTRIBUTING.md:23` says "Python 3.12+ for `tomllib`-dependent locks", and `test_pyproject_config.py` carries three `skipif`s deferring its config lock to the 3.12 legs. (3) **CI never tests 3.14** — the matrix is `["3.10", "3.12"]`, so the version actually in daily use is the one version with no CI coverage. Recommended shape: `requires-python = ">=3.11"`; CI matrix `["3.11", "3.12", "3.14"]` (drop 3.10, *add* 3.14). That makes the `tomllib` guards in all three files deletable, removes the numpy/scipy split, and closes the 3.14 hole — all with **zero new dependencies**. Secondary effect to weigh at the same time: `audio_suite_shared/project_version.py` (added in G2) hand-rolls a scoped regex TOML reader *only* because of the 3.10 floor; on 3.11 it can call `tomllib` directly, and it should then be **simplified rather than kept alongside** a real parser. |
| 2026-09-28 | (packaging, DECIDED & IMPLEMENTED) | **The maintainer approved raising the floor to Python 3.11, keeping 3.14.7 as the development target: "Python 3.14.7 was used to develop AudioSuite-Pro so all libraries need to be compatible with that; if we can go back to Python 3.11 as a minimum, but still maintain compatibility that's fine." Implemented in the same session, with zero new dependencies.** | **Code and packaging:** `requires-python = ">=3.11"`; `uv lock` re-resolved — the 3.10-only pins fell out by themselves (numpy 2.2.6, scipy 1.15.3, exceptiongroup 1.3.1, scikit-learn 1.7.2) and no `python_full_version < '3.11'` marker remains, so every supported interpreter now resolves the numeric stack actually developed against; CI matrix `["3.11", "3.12", "3.14"]` — 3.10 dropped, 3.14 (the development interpreter, previously *never* tested) added; `tests/test_pyproject_config.py`'s `_HAS_TOMLLIB` try/except and three `skipif`s deleted as dead code; `audio_suite_shared/project_version.py`'s hand-rolled regex TOML reader deleted — it existed only because of the 3.10 floor — replaced by `tomllib.loads` with a loud-failure contract (malformed TOML raises `TOMLDecodeError` instead of silently falling back to stale installed metadata); its vacuous tomllib-vs-tomllib cross-check test replaced with three meaningful locks (non-string version returns `None`, malformed TOML raises, the real file reads), net +2 tests. **Docs:** README prerequisite rewritten (states 3.10 is not supported and why); CONTRIBUTING's "Python 3.12+ for `tomllib`-dependent locks" caveat removed; Security_Guide's stale "Python 3.8+" corrected to 3.11+; tag_field_updater guide generator updated and the `.docx` regenerated and verified (3.11+ present, 3.10+ absent). **Gate (2026-09-28, Windows host, Python 3.14.7):** compile exit 0; ruff clean (3 import-order auto-fixes, then 757 files format-stable); mypy strict 0 issues / 452 files; bandit 0 High / 0 Medium / 51 Low (the unchanged documented set); full-suite pytest **7522 passed, 3 skipped, 30 deselected**, coverage **79.11%** (≥ 75). || 2026-10-12 | F3 (calibration; supersedes F2's margin-only fallback) | **Recalibrated the low-confidence fallback after a real album exposed a false-negative class.** De-mean the signal before the chroma CQT; add a tonality gate alongside the margin gate so `is_low_confidence = (margin_conf < low_confidence_threshold) AND (clarity < CLARITY_FLOOR)`, with `clarity = winner − mean` of the **cosine** correlation scores and `CLARITY_FLOOR = 0.035`; a pure DC signal is short-circuited to the fallback with zero confidence and zero clarity. `KeyAnalysis` gained a `clarity` field. | **F2's threshold was provably unreachable on real material.** A real album reported 7 of 12 tracks "Detected: Unknown"; their measured margins were 0.001–0.015, while a pure DC `np.ones(3s)` scores margin-confidence **0.180** — above six of the seven — so *no* margin threshold can separate atonal truth from real music. The `winner − mean` clarity of the **cosine** scores does separate (measured: white/brown/band-limited noise, sweep, impulse, DC all ≤ 0.028; real music 0.047–0.145; monophones 0.216–0.219; triads 0.23–0.24), so 0.035 sits inside the gap. Clarity is always computed from cosine even when Pearson is the selected method, because Pearson's *noise* scores are unstable — the same property F2 used to reject it as the default. De-meaning was proven byte-stable on every F1/F2 pinned vector (the only pin that moved is Pearson WAV-noise confidence 0.2311 → 0.2293) and makes a DC offset exactly zero-energy in the chroma domain, which is why the DC short-circuit is exact rather than heuristic. End-to-end through the real `run_analysis` workflow at the album's 90 s duration, the fix takes the run to **12/12 resolved, 0 errors**, naming all seven previously-Unknown tracks (1-01 Bb, 1-03 Em, 1-04 Bb, 1-06 Bb, 1-09 E, 1-10 Dm, 1-12 Dm). The public interface is unchanged; the new clarity value is additive. The regression vector is a noise-buried major triad (margin-conf ≈0.08, clarity ≈0.08) — the profile the real tracks present. Recorded here as a clearly-labelled follow-on decision, per the plan-governance rule that a completed plan is a historical record. |
| 2026-10-12 | G2 (defect, pre-existing; found while fixing F3) | **`_run_tool.on_progress` was keyword-only and rejected the positional call `run_analysis_workflow` makes, so every `audiosuite <tool>` CLI run crashed on the first file.** Fixed the callback to the documented positional-or-keyword `(processed, total, skipped, errors, display_text)` signature; added `TestRunTool::test_progress_callback_accepts_the_positional_contract`. | The two callers disagree: `run_parallel_processing` passes the callback straight to `create_progress_tracker` (keyword call), whereas `run_analysis_workflow` wraps it in a **positional** lambda (`file_processor_base.py`). The existing `TestRunTool` tests called the callback keyword-style, so they stayed green while the real positional path raised `TypeError: _run_tool.<locals>.on_progress() takes 0 positional arguments but 5 were given` — which the CLI swallowed as per-file errors ("12 errors" on a 12-file album). Reproduced end-to-end (every CLI command affected) and proven fixed by the same parity test, broken-and-restored against the old signature (the test fails with the exact production `TypeError` pre-fix, passes post-fix); the real CLI dry run over the album now reports 0 errors. |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| A2's newly-included `noise_reduction` fails on collection, turning a config fix into a defect hunt | Medium | Medium | The 88 tests already pass when invoked explicitly, so this is a collection-wiring problem, not a logic problem. Any genuine defect found is fixed in the same change with a regression test (AGENTS.md §7). |
| A4 surfaces genuine Linux-only defects for the first time | **High** | Medium | Expected and intended. Each is triaged as a real platform bug (fix + regression test) or a genuine limitation (explicit reviewed skip). The blanket skip is *not* reinstated to make the leg green. |
| B4's move from blanket skip to per-test skipping multiplies CI failures | High | Medium | Same triage discipline. The blanket hook stays as a collection-time safety net only. |
| B1's real multiprocessing tests are flaky (the usual `spawn`/pickle/timing traps) | High | Medium | Tiny inputs, generous timeouts, module-level workers, `spawn`-safe. Fix the *test*, never weaken the assertion. |
| C2's consolidation changes audio output on a real write path | Medium | **High** | Outcome-measurement tests written and passing against the pre-refactor code first; undo byte-round-trip and dry-run-no-write locks; the item is revertable in one commit. |
| C1's GUI dedup flattens a real behavioural difference between two tools | Medium | Medium | Per-tool distinct-behaviour tests that fail if a difference collapses; text similarity is not trusted as evidence of behavioural identity. |
| F2's accuracy upgrade regresses the common case | Medium | Medium | F1 vectors green before and after with unchanged tolerances; real-material before/after recorded on both sides; revert is an accepted outcome. |
| D1's licence decision is wrong or unwritten, creating legal exposure retroactively | Medium | **High** | The absence of a licence means no third party currently has rights, so adding one is a grant, not a revocation — but it must be an explicit maintainer decision, not a default. Blocked on D1 by design. |
| The plan is executed top-to-bottom as a big bang instead of stage-by-stage | Medium | **High** | Stage 0 lands alone and CI runs; each stage is independently shippable; the roadmap names what is deliberately excluded. |
| Open decisions D1–D5 are never resolved and the plan stalls | **High** | Medium | Each decision carries a recommendation, so "no decision" defaults to the recommended option at the next gate — but the Decision Log entry must be filled with the maintainer's name, not inferred. |
| Findings 2/14/17 reveal that previously reported coverage was materially wrong across other packages too | Medium | Medium | A2/D2 are the first honest baseline; a Stage 3 re-baseline (D3) makes any residual gap visible. Additional exclusions found are logged as new items, not silently added. |

---

## Retrospective (filled at plan close, 2026-09-28)

The four questions below are the ones this section was opened with. Each is
answered from the Decision Log and Completion Log evidence, not from memory.

**1. Which stage produced findings that should have been Stage 0 (i.e.
evidence that should have existed before any code changed)?**

Three — all pre-existing measurement-integrity defects that the Stage 0
baseline certified green only because the Phase Gate itself lacked the
checks that would have caught them:

- **The stale `uv.lock` (found by E2's required `uv sync`, Stage 4).**
  `librosa` and `sounddevice` were missing from the base dependency graph
  and `types-requests` from the dev extra — the lock had drifted from
  *declared* `[project]` dependencies, and Stages 0–3 ran the whole gate for
  four stages against a dependency graph CI's own `uv sync` would have
  failed on. Gate integrity is Stage 0's scope; the transferable part is
  that any plan gate which can touch the dependency graph must include
  `uv sync`, not only pytest/ruff/mypy/bandit.
- **The `>=3.10` floor dishonesty (found during Stage 6).** The committed
  lock resolved *different* numeric stacks per interpreter
  (`python_full_version < '3.11'` → numpy 2.2.6 / scipy 1.15.3; 3.12+ →
  numpy 2.5.2 / scipy 1.18.0) and the dev host (3.14.7) had no CI leg at
  all — a green 3.10 leg validating a dependency graph nobody developed or
  shipped against. The evidence sat in the baseline's own lockfile, which
  Stage 0's "restore trust in the gates" scope should have inspected.
  Resolved the same session by the maintainer-approved floor raise to 3.11.
- **The order-dependent `test_styles.py` pair (found during the Stage 5
  gate).** `set_active_palette()` mutates module-level `PALETTES` in place,
  so an `importlib.reload()`-based restore silently did not restore;
  whichever test ran second failed, and only on the *second* full-suite
  run. A suite whose outcome depends on run order is not a trustworthy
  gate — squarely Stage 0's scope. Fixed in the same change (test-side,
  plus a deterministic pollution regression); the production in-place
  mutation is follow-up B4 of `PLAN_iteration6_followups.md`.

Also recorded: audit finding #1 reproduces only under `--preview` on the
installed ruff 0.15.22 — the stable-mode gate already passed, so the A1 fix
was forward-protective, not retroactive (the Completion Log row says so).
An audit that files a gate finding should reproduce it against the
installed toolchain first.

**2. Did any item's tests pass without actually executing the code under
scrutiny? (Compare collected count vs executed count for every new test —
this is the failure mode that made 88 `noise_reduction` tests invisible.)**

No *new* test shipped vacuously in this iteration — every
"executed, not collected-and-skipped" claim carries a pass count (B1:
46 passed / 0 skipped, with real child-PID parity; F1: 60 vectors, with
`git status` proving test-only files; B4 chose its signals from
collection-vs-execution counting: 7,162 collected, 6,480 requiring neither
`root`/`tk_root`; every coverage-target item records before/after module
coverage). But the failure mode was *encountered* three times, and each
catch is the transferable part:

- **B3 discovered it pre-existing:**
  `audio_normalizer/tests/test_ffmpeg_finder.py` tested `get_startupinfo`
  and *zero* lines of `ffmpeg_finder.py` (module at 44%) — the same shape
  as the 88 invisible `noise_reduction` tests, undetected because a test
  file *named* for a module it never touched satisfies the naming
  convention. Per-module coverage numbers, not test counts, exposed it.
- **G1 self-inflicted, caught in-change:** the skip-attribution walk
  reused `_EXCLUDED_DIRS` (which contains `tests`) and scanned **zero**
  files — it would have passed vacuously forever; the assert-non-empty
  design is what caught it.
- **G2's verification harness reported "LOCK FIRED" on a scratch run that
  executed no test** (PowerShell `[string]` collapse → pytest received one
  character → the usage message's `ERROR` matched the verdict). Fixed to
  `[string[]]` plus a verdict keyed on `FAILED`/`ERROR` *test* lines.

**3. Did any decision recorded here turn out to be wrong, and what
evidence changed it?**

- **The audit's own D2 research input was wrong** — "`madmom` is MIT and
  wheel-installable" was overturned by attempting the install on Python
  3.14.7 (BSD-licensed code but **CC BY-NC-SA models**, sdist-only,
  `ModuleNotFoundError: No module named 'Cython'`). Superseded in the
  Decision Log *before* the decision was taken — the empirical install
  attempt is what made decision D2 safe to resolve.
- **This session's own first report was wrong** — the `tomllib` collection
  defect was first reported against both `tests/test_readme.py` and
  `tests/test_pyproject_config.py`; AST re-verification proved only
  `test_readme.py:30` was unguarded (the other file already guards the
  import and carries three `skipif`s). Grep matched a guard that exists;
  AST proved it. The correction is recorded in the Decision Log.
- **B1's corrupt-file assertion was wrong at HEAD** — the test pinned the
  empty-decode branch's message at the batch level; uv.lock resolves
  librosa 1.0 on py≥3.12, which removed the audioread fallback, so the
  same corrupt container took the decoder-raised branch and the test
  failed. Reproduced both directions before editing; corrected to the
  backend-neutral batch contract.
- **The repository's implicit `>=3.10` support posture was wrong** —
  overturned by lock inspection (the per-interpreter numeric split) plus
  numpy/scipy `Requires-Python >= 3.11` metadata plus a CI matrix that
  never tested the development interpreter; resolved by the
  maintainer-approved 3.11 floor.
- **Not wrong, for the record:** decision D3 (hold 75) survived contact —
  the honest number never fell below the gate at any stage (78.04% →
  79.11%), so the "may fail for a while" contingency never fired.

**4. Which `AGENTS.md` gotcha would have prevented a mistake made in this
iteration? Propose the addition to the user — never edit `AGENTS.md`
silently.**

Two lessons were codified mid-iteration with approval, before close: the
mypy-per-file-bypass lesson (Stage 2) and the requires-python/lockfile
lesson (Stage 6). At close the maintainer (Wilte) approved six more, all
grounded in real defects this iteration produced or caught, all added to
`AGENTS.md` in the close-out change:

1. A scripted edit that moves code between indentation levels is
   valid-Python-wrong — the compile gate cannot catch it; re-diff the
   touched lines and rely on behaviour-lock tests (C2's `process_batch`
   de-indent, the second scripted-edit regression after P5 note 4).
2. A scan reusing an opposite-purpose exclusion set silently scans zero
   files and passes vacuously; assert the result set is non-empty (G1's
   skip-attribution walk).
3. Simulate platforms by patching `sys.platform` only — patching `os.name`
   on Windows constructs a `PosixPath` hybrid that exists on no real
   system (G1).
4. A verification harness that cannot fail is worse than none — type
   PowerShell array arguments `[string[]]` and key break-and-restore
   verdicts on `FAILED`/`ERROR` *test* lines (G2's scratch check).
5. `importlib.reload()` does not undo in-place mutations of module-level
   dicts; capture expected state before pollution and add a deterministic
   pollution regression (the Stage 5 `test_styles` order-dependence).
6. Do not pin one dependency version's branch message at a consumer
   boundary; assert the backend-neutral contract where versions change
   the branch (B1/D1's librosa 1.0 audioread removal).

**Close-out gate evidence (2026-09-28, Windows host, Python 3.14.7, ruff
0.15.22, mypy 1.20.0, pytest 9.0.3):** the full six-command gate was run on
the clean tree at `20e7c89` *before* the close-out edits and re-run in full
on the post-edit tree; the close-out change is Markdown-only (this file,
`PLAN_iteration6_followups.md`, `AGENTS.md`) and Markdown is excluded from
`ruff format` by the A1 rule, so the two runs agree by construction as well
as by measurement. Every number below is from the post-edit run:

0. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'` → exit 0
   (documented pre-existing third-party pydub `SyntaxWarning` noise)
1. `python -m ruff check .` → `All checks passed!` ·
   `python -m ruff format --check .` → 757 files already formatted
   (unchanged by the three edited `.md` files, per the A1 exclusion)
2. `python -m mypy .` → `Success: no issues found in 452 source files`
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv
   -c pyproject.toml` → 0 High / 0 Medium / 51 Low (baseline-identical)
4. bare `python -m pytest -q` → 7,522 passed / 3 skipped / 30 deselected
   (identical to the Stage 6 end state; the 3 skips remain the pre-existing
   platform probes)
5. coverage → 79.11% ≥ `fail_under = 75` (decision D3 held to the close)
6. `git grep --cached` secret scans (primary + 4 supplemental patterns) over
   the staged close-out change → no live secrets. Primary-pattern hits are
   documentation prose only (the plans' and `AGENTS.md`'s own descriptions
   of these scan patterns, and the word "token" meaning a *source-code*
   platform token); the supplemental key/token, 32-hex, base64-44+ and PEM
   patterns return zero hits.

Post-block verification: commands 0–1 were re-run green after this block
was written (compile exit 0; ruff check clean; `ruff format --check` 757
files), confirming the Markdown-only gate-block edit itself moved nothing
measured by the gate.

---

## Plan Close-Out Checklist

- [x] All 21 audit findings mapped, implemented, and evidence-recorded —
      20 findings closed `[x]`; finding #4 (A4) closed `[~]` per the
      maintainer's close-out decision: implementation and YAML validation
      complete, the first-run CI URL + Linux passed count to be appended
      when the repository gains a remote (named condition in the A4 row;
      tracked as item A1 of `PLAN_iteration6_followups.md`, **withdrawn
      2026-09-29 as not required — no Linux environment exists for this
      project**, so the condition is closed as not applicable and finding #4
      is deliberately not flipped to `[x]`)
- [x] All five open decisions resolved in the Decision Log with a name —
      D1–D5 attributed to the maintainer (Wilte), 2026-09-26, recommended
      options accepted
- [x] Every item carries Gate Evidence in the Completion Log — all 21 rows
      carry per-item date + the six commands + pass/coverage counts; A4's
      row carries its honest pending-evidence note per its own rule
- [x] `AGENTS.md` updated for any new transferable lesson (user-approved) —
      six iteration-5 lessons added at close (see Retrospective answer 4);
      the mypy-per-file-bypass and requires-python/lockfile lessons were
      already codified mid-iteration with approval
- [x] Any **new** plan opened for the deliberately-excluded work, so nothing
      is silently dropped — `PLAN_iteration6_followups.md` carries the
      roadmap's deliberately-excluded set plus every follow-up recorded in
      this plan's Decision Log (A4 evidence, B1 dead code, B3 finder gate,
      C2 dry-run honesty + undo contract, F2 low-confidence KEY-tag policy,
      `test_styles` in-place mutation)
- [x] This file's `Status` flipped to `Complete` and the audit index checked
      off item by item — the "Closed" column added to the Audit Finding
      Index (finding #4 `[~]`, mirroring A4's named condition, which was
      withdrawn 2026-09-29 — see the post-close note at the index)

