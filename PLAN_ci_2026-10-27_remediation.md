# PLAN — 2.1.6 CI remediation (the first run of the published workflow)

**Status:** `[x]` **C1–C8 complete (2026-10-27)** — every item is in the tree at
`f273729`, the gate is green locally, and the three-interpreter matrix is green
at that commit (run #4, all nine jobs). X1–X3 are open and recorded in §5; none
of them blocks 2.1.5, which is already published and tagged.
**Base state:** `main` at `f273729`, in sync with
`https://github.com/wilte01/AudioSuite-Pro.git` (`origin/main` == `HEAD`). The
release commit is `942c183`, carrying annotated tag `v2.1.5`; the four commits
after it (`5cbe83d`, `5b1e7ee`, `90b1a22`, `f273729`) are this window and their
notes are the `[Unreleased]` section of `CHANGELOG.md`.
**Governing scope:** the defects the *first* run of the new CI workflow exposed,
plus the one hang that run could not report. This plan is their decision record.
It does not re-open `PLAN_docs_consolidation.md` (all four phases complete) and
it does not authorise the 2.1.6 cut (X3).

Why this is a separate plan rather than an appendix: `AGENTS.md`, *Plan
Governance* — a plan whose items are complete is a historical record, and
follow-on work opens a new one. `PLAN_docs_consolidation.md` stays closed.

---

## 1. What the first published run actually said

The remote existed but was empty, so the first push published the whole history
(307 commits) plus the `v2.1.5` tag. Nothing in the tree had been exercised on
GitHub's runners before, so run #1 was the first evidence about the *floor* —
and the floor had never run anywhere but a 3.14 host.

| Run | Commit | Test (3.11) | Test (3.12) | Test (3.14) |
|---|---|---|---|---|
| #1 | `5cbe83d` | ❌ 7 failed | ❌ 5 failed | ❌ wedged at 6%, cancelled after ~40 min |
| #2 | `5b1e7ee` | ❌ 1 failed (rate limiter) | ✅ | ✅ |
| #3 | `90b1a22` | ✅ | ❌ helper deadline fired (stack dump) | ✅ |
| #4 | `f273729` | ✅ | ✅ | ✅ |

Every failure was real. None was a flaky rerun, and none was fixed by weakening
a lock — the one test that *was* a timing artefact (C5) kept its end-to-end
assertion and gained a deterministic one beside it.

---

## 2. Decision log

| D | Decision | Status | Rationale / evidence |
|---|---|---|---|
| D1 | Record this work in a **new** plan; do not append it to `PLAN_docs_consolidation.md`. | DECIDED | `AGENTS.md`, *Plan Governance*: a complete plan is history. The modules touched here (CI config, test harness, two product modules) are not that plan's subject either. |
| D2 | The window starts at `5cbe83d`, so `tests/test_release_notes.py` re-baselines `BASE_COMMIT` to it and `NOTE_MARKER` to `Changed in 2.1.6`. | DECIDED | 2.1.5's notes are written and shipped; leaving them as each file's own history is that lock's documented pattern (§2.5 of the audit-remediation plan). |
| D3 | A *test* may be fixed for the declared floor; production code may not raise its requirement. `os.listdrives()` becomes an `os.path.exists` probe, and the `os.name` trap lock accepts 3.11's louder failure. | DECIDED | `requires-python = 3.11` is the contract. A 3.12+-only API in a test fails the floor leg and hides the behaviour the test exists to lock. |
| D4 | The release-note lock drops its `core.autocrlf=false` override instead of normalising paths or hashing contents. | DECIDED | Forcing the override on a checkout that converts line endings makes every LF-stored file look modified: 3.11/3.12 reported hundreds of unannotated files nobody had touched, while 3.14 read the same commit as clean. Plain `git diff` reports what `git status` reports on the machine the check runs on. |
| D5 | Refinery existence is one guarded `Path.stat()`, not `Path.exists()`/`is_file()`. | DECIDED | 3.13+ swallow a stat failure and report `False`; 3.11/3.12 re-raise anything that is not `ENOENT`/`ENOTDIR`. The same unreadable file crashed the check on the older legs and was merely "absent" on the newer one — two verdicts from one input. |
| D6 | The 2.1.0 single-interpreter collection helper is **reverted** to one child process per view, at ~20 s of suite time. | DECIDED | It wedged three times with no output (twice at 6% on 3.14, once locally) and the third occurrence returned a stack inside pytest's own `_do_configure` hook chain. The optimisation saved 35 s → 22 s; a silent hang costs a runner and a cancelling operator. |
| D7 | Deadlines are set 3–10× above observed times: 120 s per view, 900 s for the helper, 150 s per-child from the parent, 600 s per nested `runpytest_subprocess`, 300/900 s for the PowerShell staging runs, `timeout-minutes: 60` on the test job. | DECIDED | A view takes ~5 s and the suite ~25 min, so a loaded runner still passes. A wedge fails with its captured output instead of at GitHub's six-hour cap. |
| D8 | The collection wedge's root cause is recorded as **unidentified**, not as fixed. | OPEN (X1) | Standalone, the helper completes in 20 s; the in-process failure only appears inside a live session. Bounding it (D6/D7) is a mitigation with evidence, not a diagnosis. |
| D9 | The rate limiter keeps a real-time end-to-end assertion **and** gains a driven-clock test of its arithmetic. | DECIDED | The end-to-end check proves the limiter is wired into `lookup_many`; only the arithmetic is deterministic. Windows' `time.monotonic` ticks every ~15.6 ms, so a 20 ms spacing with a 40 ms budget is unmeasurable — 31 ms on a loaded runner. |
| D10 | The post-2.1.5 fixes do not move the `v2.1.5` tag; they accumulate under `[Unreleased]`. | DECIDED | The tag names a shipped artefact and its notes are already published with it. It moves only at a cut (X3). Post-release commits sit *after* the tagged commit, which is the normal shape. |
| D11 | 3.11/3.12 verification is delegated to CI. | ACCEPTED LIMITATION (X2) | The development host has only 3.14, and every defect here was version-specific by construction, so the runner is the only arbiter for those legs. |
| D12 | No `AGENTS.md` rule is added in this change. | DEFERRED | The lesson ("a nested subprocess with no timeout is a hang waiting for a reason") is in the helper's own docstring and in `tests/test_packaging.py`'s. Promoting it to a rule means editing the frozen 35-entry `RULE_INVENTORY` in `tests/test_agents_md.py` deliberately — its own change, not a drive-by edit while fixing CI. |

---

## 3. Items

Each item names the files, the defect, the change and the evidence that the
change is real. "Break-and-restore" means the lock was proven able to fail by
mutating the code under a SHA-256-verified restore.

### C0 — Coverage lock in the fast docs job (precedes this investigation)

Landed as `5cbe83d`, listed here so the window is contiguous.
`tests/test_suite_docs_tool_coverage.py` was absent from the `docs-locks` job,
and `tests/test_docs_formats.py`'s classification walk never matched its name,
so the lock could sit outside the job forever while every listed module passed.
The walk now recognises the `test_suite_docs*` family, the module joins the job,
and the coverage walk itself reads *tracked* documents so a staged
`docs/_build/` copy of `CHANGELOG.md` cannot be judged as shipped prose.

### C1 — The release-note lock read a line-ending conversion as a change

*Files:* `tests/test_release_notes.py`
*Defect:* the lock ran `git -c core.autocrlf=false diff --name-only <base>`.
GitHub's Windows runners set `core.autocrlf=true`, so the working tree holds
CRLF while the index holds LF — and disabling the conversion made every stored
file look modified. Run #1 reported ~487 files "without a `Changed in 2.1.5`
note" that no author had touched.
*Change:* the override is gone. The lock sees the same diff `git status` sees.
*Evidence:* reproduced in a throwaway CRLF clone: with the stat cache
invalidated, the old form reported phantom modifications and the new form
reported none, while a genuine edit in the same clone was still caught. The lock
was not simply relaxed.

### C2 — The refinery's integrity check crashed on 3.11/3.12

*Files:* `audio_refinery/core/integrity.py`, `audio_refinery/tests/test_integrity.py`
*Defect:* `Path.exists()` and `Path.is_file()` swallow a stat `OSError` only on
3.13+. A locked or permission-denied input raised out of `validate_file` on the
older legs instead of failing that file with a reason.
*Change:* one `Path.stat()` in a `try`, `FileNotFoundError` → "does not exist",
any other `OSError` → "Cannot stat: …", regular-file-ness via
`stat.S_ISREG(st_mode)`, and the size reused from the same stat.
*Evidence:* the module's tests cover an unreadable path and a directory through
the real function, so all three legs now give one verdict.

### C3 — The Master Driver menubar grew a tear-off row on Tk 8.6

*Files:* `master_driver/app.py`, `master_driver/tests/test_app.py`
*Defect:* `tk.Menu` defaults to a tear-off entry. Tk 8.6 (the 3.11/3.12 legs)
draws it as a dashed row at index 0 and shifts every entry down; Tk 9 defaults
to none. The Help-menu test also filtered to cascades and then reused that
filtered position, so on 8.6 it read the *Profile* menu instead of Help.
*Change:* the menubar is built with `tearoff=0`; the helper resolves Help by
scanning the menubar for the cascade whose label is `Help`, and fails loudly if
there is none. New `TestHelpMenuConstruction::test_menubar_has_no_tear_off_entry`
pins the entry kinds.
*Evidence:* the new test fails on a menubar without `tearoff=0` and on any
regression that reintroduces one; the helper's assertion is now positional-safe
rather than index-dependent.

### C4 — Two tests used APIs below the floor (3.12+) or above it

*Files:* `cd_ripper/tests/test_ripper_core.py`,
`audio_suite_shared/tests/test_platform_support.py`
*Defect:* `os.listdrives()` is 3.12+; on 3.11 the failed-open test raised
`AttributeError` before reaching the message it locks. Separately, the `os.name`
trap lock asserted a hybrid `PosixPath` that 3.12+ builds but 3.11 refuses to
build at all (`NotImplementedError`, because the flavour's support flag is read
at import).
*Change:* drive letters are probed with `os.path.exists`; the trap lock accepts
3.11's `NotImplementedError` form of the same trap and asserts the message names
`PosixPath`, so neither version passes vacuously.

### C5 — A wall-clock rate-limiter assertion that the platform clock cannot resolve

*Files:* `audio_fingerprinter/tests/test_acoustid_client.py`
*Defect:* `test_requests_are_rate_limited_in_time` enforced 20 ms spacing over
three requests and asserted ≥40 ms. Windows' `time.monotonic` has ~15.6 ms
granularity, so a loaded 3.11 runner measured 31 ms — a red leg — while 3.12 and
3.14 read the same commit as clean.
*Change:* the end-to-end check uses 100 ms spacing and a ≥150 ms budget, which
still proves `lookup_many` goes through the limiter. New `TestRateLimiter` pins
the arithmetic against a clock the test drives: the first request does not wait,
each later one sleeps the whole interval when nothing moved, and only the
remainder when work happened in between; `interval=0` never sleeps. The fake
clock starts above zero because `RateLimiter` treats `0.0` as "no request yet".
*Evidence:* break-and-restore — replacing the limiter's `sleep` with `pass` made
3 of the new tests fail; the file was restored byte-identically after a SHA-256
check and the 50 tests in the module pass.

### C6 — The whole-tree collection helper could wedge the suite silently

*Files:* `tests/_collect_views.py`, `tests/test_pyproject_config.py`
*Defect:* 2.1.0 collected all five marker views through one in-process
`pytest.main`. It wedged three times (twice at 6% on 3.14, once locally), and a
wedged in-process collection prints nothing — the first occurrence cost a
forty-minute cancelled leg.
*Change:* one child process per view, each arming
`faulthandler.dump_traceback_later(120, exit=True)`; the parent bounds each
child at 150 s and the helper at 900 s. A child exits 0 whenever it produced a
payload (pytest's own code rides inside it) and non-zero only when it could not
answer, so the caller reports *which view* failed. The caller's failure message
quotes the **head** of the child's stderr, where `faulthandler` prints the
innermost frame. `TestCollectHelperIsBounded` is an AST lock: an edit that
removes the deadline fails the gate.
*Evidence:* the guard fired in run #3 and returned a stack parked in pytest's
`_do_configure` hook chain instead of holding the runner; all five child views
exit 0 in 43 s on a healthy tree, and the module's 26 tests pass.

### C7 — Nested subprocesses with no deadline

*Files:* `tests/test_pyproject_config.py`, `tests/test_packaging.py`
*Defect:* `pytester.runpytest_subprocess` defaults to `timeout=None`, and the
PowerShell staging harness ran under a bare `subprocess.run`. Both sat in the
6% region of the collection order, so a wedge there produced no output and no
failure until GitHub's six-hour cap.
*Change:* `timeout=600` on each of the three nested pytest runs, `timeout=300`
on the harness helper and `timeout=900` on the full staging run. A timeout now
fails the test with the captured output.

### C8 — The test job had no deadline of its own

*Files:* `.github/workflows/ci.yml`
*Defect:* a stuck leg held a runner for up to six hours, and the run list showed
it as "in progress" rather than failed.
*Change:* `timeout-minutes: 60` on the `test` job. The suite takes ~25 minutes
there; a leg still running at 60 is stuck, and the run list says so.

---

## 4. Verification record

At `f273729`, on the development host (3.14):

* `python -m compileall -q -f .` — clean.
* `ruff check .` and `ruff format --check .` — clean.
* `python -m mypy .` — clean, 550 source files.
* `bandit -r . -x ./.venv -c pyproject.toml` — **0 High / 0 Medium**.
* `pytest` (bare) — **11146 passed, 3 skipped**, coverage **90.89%**
  (CI adds `--cov-fail-under=75`).

On GitHub Actions, run #4 at `f273729`: **all nine jobs green**, including
`Test (Python 3.11)`, `Test (Python 3.12)` and `Test (Python 3.14)` — the three
legs that were red or hung in run #1. The matrix now certifies the floor it
declares.

`v2.1.5` still peels to `942c183` and `origin/main` equals `HEAD`; no commit in
this window was force-pushed, amended or reordered.

---

## 5. Open items (deliberately not closed here)

* **X1 — the collection wedge's root cause.** Three occurrences, two with no
  stack and one inside pytest's `_do_configure` chain; standalone reproduction
  completes in 20 s. Mitigated (C6, C7, C8) and now self-reporting, but not
  diagnosed. If a child hits its deadline, its stderr head is the evidence to
  start from.
* **X2 — local interpreters for 3.11 and 3.12.** The host has 3.14 only. Every
  claim about the older legs in this plan comes from the runner; a defect that
  only manifests when a developer reproduces locally cannot be seen here.
* **X3 — the 2.1.6 cut.** The notes are written but `[Unreleased]` is not
  released: cutting it is `utilities/release.py` (per the release utility) plus
  a tag, and moves `v2.1.5`'s successor into place. Not authorised by this
  plan.

---

## 6. Changelog mapping

Every item above has a user-visible bullet in `[Unreleased]`: C1/C2/C3/C4/C5
under **Fixed**, C6 under **Fixed**, C7 and C8 under **Changed**, C0 under
**Fixed**. `CHANGELOG.md` is the shipped narrative; this file is the reasoning
behind it, including the dead ends (the 2.1.0 performance change that had to be
undone) that the changelog has no place for.
