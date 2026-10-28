# PLAN — Audit 2026-10-24 deferred register (P2/P3): CI policy, a POSIX leg, tooling targets, docs truth

**Status:** `[~]` in progress — drafted 2026-10-27. **R-15 is complete and
runner-verified** (record in §5): the code commit `5298301` (run `40563584800`)
and this plan's own record commits `61a19dd` (run `40568799837`) and `1ab0e39`
(run `40573946202`) are each **green in all nine jobs**, `Type Check` and
`Lint & Format` included, after the first push's `Type Check` failure was fixed;
R-16's verification row is written; **R-12 is complete and runner-verified** — run
`40663662748` at `b7ee2f9` prints `POSIX smoke pass: 1756 passed, 1 skipped` (§5);
**R-11 is delivered and locally verified** (§5), but its runner verdict is
**blocked** — at `d1027ad` and again at `d459fb0` no job started at all, for an
account-level reason now measured at **2 651.6 billable Actions minutes consumed
in October** (~170 a push), so the audit step is not runner-verified (X9).
**R-17 is delivered and locally verified** (§5), and its runner verdict is
pending for the same reason: it is the owner's response to X9, and it brings a
push from **168.0 to a projected 68.7 billable minutes** by running the full
suite once, on the 3.11 floor.
**Status legend:** `[ ]` pending · `[~]` in progress · `[x]` done.
**Base state:** `main` at `85046ef` ("Record the 2.1.6 CI remediation decisions
(2026-10-27)"), working tree clean. `v2.1.5` is the repository's only tag (at
`942c183`). `tests/test_release_notes.py` is re-baselined to `5cbe83d` with
`NOTE_MARKER = "Changed in 2.1.6"`, so this window's per-file notes are 2.1.6's
and `[Unreleased]` is the 2.1.6 narrative.
**Source:** [AUDIT_2026-10-24_suite_report.md](AUDIT_2026-10-24_suite_report.md)
§6 (findings R-11, R-12, R-15, R-16) and §9.1 (plan-ready register, including
each finding's acceptance evidence).
**Predecessor:** `PLAN_audit_2026-10-24_remediation.md` — closed 2026-10-26 with
2.1.4; its §8 defers the audit's P2/P3 findings ("they need their own plan"),
and its D13 rules them out of that plan's scope. This is that plan.
`PLAN_ci_2026-10-27_remediation.md` (C1–C8 complete at `f273729`) is the
predecessor *record* for the `.github/workflows/ci.yml` window this plan edits
next; its X2 and X3 carry forward here.
**Governing scope:** four findings — R-11 (dependency audit non-blocking), R-12
(POSIX untested), R-15 (Ruff/mypy targets below the floor), R-16 (README tool
count) — plus **R-17**, added 2026-10-28 on the owner's instruction ("design a
cheaper CI matrix … well under 100 billable minutes") once X9 measured the
allowance ceiling. R-17 is numbered after the register's last finding because it
is not one: it is a cost decision the audit did not contain, and D23 records
that distinction. Nothing else.
**Not in scope, and why:** R-13 (library cache key) and R-14 (non-ASCII console
output) are the register's remaining P3 defects and are **not** in this brief —
they stay deferred in the predecessor's §8 and need their own plan. The
maintainability register Q-01–Q-10 and the market-parity backlog F-01–F-12 are
untouched. See §6 for the deferrals this plan creates.
**Versioning:** this plan adds no tool, flag, JSON key or output format, so
every item is MAINTENANCE-class. R-15 lands under `[Unreleased]` (2.1.6); R-11
and R-12 are targeted at 2.1.7 because they change what CI runs rather than what
ships. The 2.1.6 cut is **not** authorised here — that is X3 of the CI plan, and
the per-sprint cut procedure is §2.5 of the audit-remediation plan.
**Anti-creep rule:** implement only the items below. No adjacent refactors, no
new runtime dependency, no styling changes outside touched files, and no
`AGENTS.md` rule addition (which would mean editing the frozen `RULE_INVENTORY`
deliberately). A defect discovered *while* implementing an item is fixed in the
same change with a regression test and recorded in §2 (AGENTS.md, *Defects and
failing checks*).

---

## 1. What is actually true today (measured at `85046ef`)

Every number below was measured on this host (Windows, Python 3.14, ruff 0.17.1,
mypy 2.4.0, pip-audit 2.10.1) before writing the plan, because the audit's
findings are three days old and one of the four is already closed. Numbers taken
from earlier records are marked as such.

| Finding | State now | Evidence |
|---|---|---|
| **R-11** | **Live.** The `security` job's `Dependency audit (exported lock)` step still carries `continue-on-error: true`, and its comment still says the audit is "on probation for two sprints". | `tests/ci_workflow.py::step(job("security"), …)` slices the step; `tests/test_ci_security_audit.py::test_the_step_is_on_probation` asserts `continue-on-error: true` **and** the word `probation`, so the probation cannot end by editing the workflow alone. The same module's docstring already names "kept forever without a recorded decision" as one of the four ways the audit can be quietly undone. |
| **R-12** | **Live.** No job executes a tool package on a POSIX host. `lint`, `security`, `compile` and `schema-conformance` run on `ubuntu-latest`; `docs-locks`, `typecheck` and `test` run on `windows-latest`. | `ci.yml`. The `docs-locks` job's own comment says why it is on Windows: "these locks read the real registry (`test_readme` imports every tool surface), so they exercise Windows-only code and a Linux leg would be a platform nothing else in this repo runs on." The `typecheck` job's comment records the opposite constraint: on `ubuntu-latest` typeshed has no `ctypes.windll`, `os.startfile`, `msvcrt`, `winaccent`, so bare `mypy .` reports ~35 false `attr-defined` errors (CI run 38548380226). |
| **R-15** | **Live, and the green suite depends on it.** `[tool.ruff] target-version = "py310"` and `[tool.mypy] python_version = "3.12"` sit either side of `requires-python = ">=3.11"`. | Measured: `ruff check .` → *All checks passed*; `ruff check . --target-version py311` → **12 errors, all `I001`**, because at a py310 target `tomllib` (3.11 stdlib) is classified third-party, so imports are mis-sorted. `mypy .` → *no issues found in 550 source files*; `mypy . --python-version 3.11` → **1 error**: `spectral_viewer/core/spectrogram.py:211: All overload variants of "max" of "ndarray" require at least one argument [call-overload]`. |
| **R-16** | **Closed in 2.1.5.** `README.md` line 3 reads "30 first-party tools" and the platform section reads "the other 29 of 30 tools" — both correct for a 30-tool registry. | `tests/test_suite_docs_tool_coverage.py::TestToolCountClaims` parses every count claim in `README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/**` and `user_guides/**`, asserts the scan found ≥5 claims (non-vacuous), and compares each with what the manifest implies (total, Windows-only remainder, subset, and per-category rows). `tests/test_readme.py::TestMetadataLock` pins `len(get_registry().first_party) == 30`. The mechanism the audit asked for (render the intro count from the registry) was superseded by a lock over the prose, which is what §2/D7 records. |

Two further measurements the items depend on:

* **Deferred `UP` rule set** (R-15's "add `UP` rules after the target is
  corrected"): `ruff check . --select UP --statistics` → **317 findings, 314
  fixable** — `UP045` 139, `UP035` 80, `UP037` 57, `UP024` 21, `UP015` 10,
  `UP033` 6, `UP007` 1 (not auto-fixable), `UP031` 1, `UP012` 1, `UP009` 1.
  `UP042` (`str`-mixin enum → `StrEnum`) currently reports nothing.
* **pip-audit capability**: the installed 2.10.1 supports `-f json`, `-o FILE`,
  `--no-deps` and `--ignore-vuln ID`, so the audit's verdict can be read from a
  structured payload rather than from prose.

---

## 2. Decision log

| D | Decision | Status | Rationale / evidence |
|---|---|---|---|
| D1 | Record this work in a **new plan**; do not append it to `PLAN_audit_2026-10-24_remediation.md` or `PLAN_ci_2026-10-27_remediation.md`. | DECIDED | AGENTS.md, *Plan Governance*: a completed plan is a historical record, and the predecessor's §8 defers exactly these four findings to a plan of their own. |
| D2 | R-11 ends the probation **by policy**, and the recurring audit gets its **own workflow file** rather than a `schedule:` trigger on `ci.yml`. | DECIDED | A `schedule:` on `ci.yml` re-runs the 25-minute three-interpreter test job weekly to audit a file that takes seconds. A second workflow with `schedule:` + `workflow_dispatch` runs the same checker and nothing else. The probation has run since 1.4.1 — seven release cuts past the "two sprints" it was granted (1.4.1 was the last cut before 2.0.0, and 2.1.6 is in flight). |
| D3 | The audit's verdict comes from **pip-audit's JSON**, never from a substring of its prose, and `--ignore-vuln` stays **off** so the raw finding is always printed. A first-party, stdlib-only `utilities/check_dependency_audit.py` applies the allowlist and returns the exit status. | DECIDED | AGENTS.md, *A verification harness that cannot fail*: a verdict keyed on a word appearing anywhere in output is not a verdict. Keeping `--ignore-vuln` off leaves one place where an advisory can be accepted — the committed allowlist — instead of two. |
| D4 | Allowlist entries carry `id`, `reason` and an **expiry date**, and an entry whose advisory no longer appears is a **failure** (stale), as is an expired one. | DECIDED | The audit asks for "a small documented allowlist … (and a date/reason)" plus a weekly audit "so the allowlist ages visibly". Expiry makes the age fail the build; staleness stops the list growing into a permanent suppression. |
| D5 | R-12 adds an **explicitly declared selection** on `ubuntu-latest`, not the full suite — and a lock that pins the selection. | DECIDED | The suite is Windows-first and ~25 minutes; the typecheck job cannot run there at all (~35 false errors), and the registry-reading doc locks are deliberately on Windows. A selection that can silently shrink is the failure mode, so it is declared and locked. |
| D6 | The POSIX leg runs **without a virtual display**; GUI-dependent tests skip with `NO_DISPLAY_REASON`, bounded to `requires_display` by the root `conftest.py`. | DECIDED | B4 replaced the blanket headless skip precisely so a display-less host reports *which* Tk-dependent tests it could not run rather than skipping everything. Installing `xvfb` would let the leg claim GUI verification it did not perform — an over-claim of the same class R-12 exists to remove. |
| D7 | R-16 is closed **by verification, not by work**, and the README's intro count stays hand-written prose under `TestToolCountClaims`. | DECIDED | The count is a phrase inside sentences in five document families (`README.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/**`, `user_guides/**`) and in the deck; a generator would have to own the sentences, while `generate_readme_tool_index.py` already owns the table and the lock already owns the prose. |
| D8 | R-15 fixes the targets **down to the floor** (`ruff` `py311`, `mypy` `python_version = "3.11"`) and keeps **one** typecheck job instead of matrixing it. | DECIDED | The floor is the binding contract (`requires-python = ">=3.11"`); the audit's own acceptance evidence is "3.11 typecheck leg green". A 3.12 pin certifies a target nothing runs on the oldest supported leg, and it hid a real error (measured: 1). Matrixing would double a multi-minute job to test an upper bound nothing claims to be the constraint. |
| D9 | The lint job installs ruff **from `uv.lock`** instead of `pip install ruff`. | DECIDED | The same argument the `docs-locks` job already makes for its renderer: an unpinned tool can red the gate for a reason that has nothing to do with the change under test. The dev venv carries ruff 0.17.1 while the `lint` job installs whatever is newest that day, so a new default rule is a red gate with no repository change. This is in R-15's title ("tooling-version mismatch"), so it is in scope rather than a drive-by. |
| D10 | A new `tests/test_tooling_targets.py` holds the interpreter-target lock. | DECIDED | Nothing in the tree pins either target today: a search of `tests/` for `py310`, `py311`, `target-version`, `python_version` and `requires-python` returns **no matches**. That is how they drifted below the floor in the first place. Root `tests/` is exempt from the test-file naming map, and artifact-locking modules there are the established shape (`test_ci_security_audit.py`, `test_readme.py`). |
| D11 | The deferred `UP` rule set is **not** enabled here; it is recorded as a follow-on with its measured counts (§6). | DECIDED | 317 findings would swamp the review of a config correction, and the audit's own fix shape orders it *after* the target is corrected. Two traps stay on the record: `UP007` (1) is not auto-fixable, and if a later `UP042` fix is taken, AGENTS.md's `str`-mixin enum trap applies to every interpolation of that field package-wide. |
| D12 | The POSIX leg is **Ubuntu only**; no macOS leg is added. | DECIDED | The audit says "Ubuntu (and ideally macOS)". Nothing in the tree claims macOS support, and macOS runners bill at a multiple of Linux minutes for a claim nobody makes. Revisit only with a support decision (recorded in §6). |
| D13 | `platform_support.py` stays the **single source** for the caveat; the README block is regenerated, never hand-edited. | DECIDED | `MATRIX_CAVEAT` is asserted verbatim against the README by `test_platform_support.py::TestReadmeDriftLock::test_readme_states_the_caveat_verbatim`, and the generated block is compared against a fresh render. The same lock forbids the phrasings `cross-platform`, `fully cross-platform` and `works on linux and macos`, so the new wording must be narrower, not larger. |
| D14 | The R-15 lock reads the lint job's **executed** lines, not its raw text. | DECIDED | The job's comment explains why it takes ruff from the lock and quotes `pip install ruff` while doing so, so a raw-text match failed on the explanation instead of on the wiring — the lock caught this on its first run. Stripping comment lines is the same distinction `tests/test_ci_security_audit.py` draws when it proves the audit never points at `.venv` ("a comment cannot point the audit at a directory"). Every CI-text lock added later starts from this shape. |
| D15 | The typecheck job **stays on the 3.11 floor** after its first run failed there, and the failure is fixed in the code rather than by moving the job back to 3.12. | DECIDED | The floor leg is what the audit asked to be verified, and it caught what 3.12 could not: the lock resolves numpy 1.26.4 / scipy 1.17.1 below 3.12 and numpy 2.5.4 / scipy 1.18.1 above it, and 1.26's stubs leave ``ndarray`` generic with no defaults, so thirteen bare ``ndarray`` annotations failed ``--strict``'s ``disallow_any_generics`` *only* on the floor. Reverting the job would have kept a gate that cannot see the stack a 3.11 user installs. Confirmed by the runner at `5298301` (run `40563584800`): the 3.11 leg is green, so the job is deliberately the one that found this. |
| D16 | The installer's build output (`packaging/build`, `packaging/dist`) stops being read as source: **five** tree-walking locks and mypy. | DECIDED | `tests/test_packaging.py` stages a payload there (gitignored) carrying every tool module *and* a bundled interpreter, whose own `Lib/test` corpus is deliberately not UTF-8. `test_e4_dead_code_lock.py` read it and died with `UnicodeDecodeError` (34 errors), `test_undo_gui.py`'s display-name scan failed three tests, and mypy aborted with "This file shadows library module 'typing' ... errors prevented further checking". A full `bare pytest` then found **three more of the same** — `tests/test_test_file_naming.py` and `tests/test_external_records.py` (both `UnicodeDecodeError` on the corpus) and `audio_suite_shared/tests/test_cli_helpers_ast_lock.py` (24 errors) — 26 failures/errors in total, all from one gitignored tree no lock has business judging. All are local-only: CI checks out a clean tree, so a developer who had built the installer could not run the gate the suite documents. Found while verifying R-15 and fixed in the same change. The locks' existing `tests` skip does **not** cover the corpus: its path part is `test`, singular. |
| D17 | `[tool.bandit] exclude_dirs` gains `"packaging"`, and the entries are asserted **narrow** by a lock. | DECIDED | The security gate walks `.`, so with the installer built the documented command reported **3 690 HIGH** findings drawn from CPython's own stdlib inside the staged runtime — the gate could not pass in a state a normal developer reaches, while CI (which never builds the installer) stayed green. Bandit matches each entry as a path **substring**, which is why the entry is asserted by its consequence: a new `tests/test_tooling_targets.py` class scans the tree for a production module whose path matches any entry and fails if one exists, so widening an entry into a silent blind spot is red, not allowed. Nothing is lost today: `packaging/` ships no `.py` file (its inputs are `.iss`, `.ps1` and `.md`), and  `packaging` appears in no other tracked path. The exclusion also prunes the walk: the gate went from minutes to **11 s**.
| D18 | R-12's selection is derived on a **native Linux filesystem**, with a **static ffmpeg on PATH** and **no display** — not on the development host, and not over the `/mnt/d` 9p mount. | DECIDED | Measured: over 9p the tree-scanning modules cost 150 s each and the sweep died on timeouts, which is a property of the mount rather than of POSIX; and a host without ffmpeg reports 15 fixture errors that say nothing about portability. The accepted shape is CPython 3.12.16 (the build family `actions/setup-python` uses), ffmpeg/ffprobe 7.0.2 static, and `DISPLAY`/`WAYLAND_DISPLAY` unset — which is also how the display branch was proved: `tk.Tk()` raises `TclError` and the conftest prints **NOT VERIFIED** with *0 of 1757* display skips, so this selection costs no GUI coverage (the earlier WSLg-backed run printed VERIFIED, which would have hidden that). |
| D19 | The five failures that derivation surfaced are **fixed in the same change**, not excluded from the selection. | DECIDED | Two are defects in shipped code: `suite_config._save` promised to swallow a failed write but let a `PermissionError` escape from an unguarded directory `glob`, and again from `tmp.exists()` in its `finally` (3.12's `exists()` ignores only `ENOENT`/`ENOTDIR`, so `EACCES` re-raises; `_try_unlink` already swallows it, making the probe redundant). The other three tests encoded Windows-only assumptions and passed vacuously on Windows: a path that is absolute only there, a read-only-file cleanup that assumes Windows refuses the unlink, and two launcher tests whose Windows-shaped launch read the real `sys.platform`. Excluding the modules would have hidden a real POSIX defect in shared config persistence — the exact over-claim R-12 exists to remove. |
| D20 | The lock asserts the **comparison** (`-lt 1756`, `-gt 1`) and not the bare number, and both bounds are measured values rather than the pre-derivation guesses (470/85). | DECIDED | Break-and-restore proved the trap on the padded bounds: lowering `-lt 1750` to `-lt 10` and raising `-gt 10` to `-gt 9000` both left the lock **green**, because each step's failure message quotes the same number — D14 in a new shape.  Asserting the operator plus value makes both mutations red. |
| D22 | The weekly workflow **duplicates** the export, payload and checker commands instead of calling `ci.yml` as a reusable workflow, and the checker's exit codes are a three-state contract (`0` pass, `1` policy, `2` unusable). | DECIDED | A reusable workflow would hide the export flags and the checker invocation behind a `uses:` line, so both locks would be reading a reference rather than the commands; two short duplicated blocks keep each file legible to `tests/ci_workflow.py` and to a reader. The third exit state is the one that matters: the probation era turned every unreadable payload into a pass, and "cannot judge" must not share a code with "judged clean". The tests hold each branch able to fail by break-and-restore, which is the only proof that a green suite means something here. |
| D23 | R-17 reduces the test matrix to **one leg, on the 3.11 floor**, instead of 3.11 / 3.12 / 3.14 — and it is a *designed* reduction, distinct from the panic-cut X9 forbids. | DECIDED | Measured from the jobs' own timings (run `40668603600`): the three legs were **160.9 of a 168.0-minute push**, the other seven jobs 7.1 together, and the account's monthly allowance therefore bought about a dozen pushes — which is how X9 happened. The floor keeps the full suite because `uv.lock` resolves a *different* graph below 3.12 (numpy 1.26.4 / scipy 1.17.1 / sphinx 9.0.4 against 2.5.4 / 1.18.1 / 9.x), the development host runs 3.14 under the mandatory local gate, and 3.12 takes the same resolution branch as 3.14. So the legs that went were the two re-testing a graph in daily use, not the one nothing else executes. This is D15's argument applied to the suite. |
| D24 | The budget is held by a **lock over the committed workflow** (`tests/test_ci_cost.py`) with a measured per-job ledger, not by a comment or a wiki page. | DECIDED | A cost decision written only in prose is undone by the next person who adds a leg in good faith. The ledger makes every job's price explicit (a new job without one is red), asserts one interpreter on the floor with no matrix, and proves the arithmetic rejects the doubled-leg shape — while leaving 31 minutes of headroom so ordinary suite growth does not trip it. `tests/ci_workflow.py` gained `job_names()` so the lock enumerates the real jobs instead of a remembered list. |
| D21 | The bounds are the **runner's own** numbers — 1756 passed, 1 skipped — not the derivation's ten-point padding (1750/10). | DECIDED | The leg's first run (D20's window) reported exactly the numbers the local derivation produced, and the split is pinned three ways: `uv.lock` fixes the dependency graph, `setup-python` fixes the interpreter line, and the ffmpeg step fixes the binaries. A deviation is therefore a real change — a lock upgrade, a new Python patch that skips something — and the leg should say so instead of absorbing it. Widening a bound again is legitimate only as a deliberate edit with a sentence here naming what moved, and the lock's comparison assertion means a silent widening is red. |

---

## 3. Items

Each item names the files, the defect, the change and the evidence that the
change is real. "Break-and-restore" means the lock was proven able to fail by
mutating the code under a SHA-256-verified restore, with `__pycache__` cleared
before the verdict is believed (AGENTS.md, *Verification Tooling Traps*).

### R-15 — the tooling targets must name the floor

*Files:* `pyproject.toml` (`[tool.ruff] target-version`, `[tool.mypy]
python_version`, `[tool.mypy] exclude` for the installer's build output, and
`[tool.bandit] exclude_dirs`), the modules ruff re-sorts at a py311 target (12
`I001` findings),
`spectral_viewer/core/spectrogram.py` (line 211), the thirteen bare `ndarray`
annotations the floor's numpy stubs reject (D15),
`.github/workflows/ci.yml` (`lint` and `typecheck` jobs), the five tree-walking
locks that must not read `packaging/build` (D16), new
`tests/test_tooling_targets.py`.

*Defect:* three declarations disagree about which interpreter this project
supports. `requires-python = ">=3.11"` and the test matrix (`3.11`, `3.12`,
`3.14`) say 3.11 is the floor; ruff's target says 3.10, so 3.11's standard
library is misclassified and the modernisations 3.11 unlocks are suppressed;
mypy's target says 3.12, so the type gate certifies syntax and stdlib members
the floor leg cannot run. Measured today: at the declared 3.10 target ruff is
green, and at the *correct* 3.11 target it reports 12 errors — the green was an
artefact of the wrong target. Symmetrically, mypy is clean at 3.12 and reports
1 error at 3.11, in a module whose arithmetic is one line from the audio path.

*Change:*
1. `target-version = "py311"`, matching `requires-python`.
2. Fix the 12 `I001` findings the corrected target exposes. Applied with
   `ruff check --fix` **and reviewed as a diff** — the audit plan's *Never lose a
   rule to a scripted edit* rule applies to import-block rewrites too.
3. `python_version = "3.11"` in `[tool.mypy]`.
4. Fix `spectral_viewer/core/spectrogram.py:211`: `magnitude.max()` with no
   argument has no valid overload against 3.11's numpy stubs; `np.max(magnitude)`
   is the same call with a signature that type-checks. The `if magnitude.size`
   guard above it stays — the empty case still must not produce `-inf`.
5. The `typecheck` job installs and runs on the **floor**: `python-version:
   "3.11"` so the installed stubs and the declared `python_version` agree,
   instead of checking a 3.12 environment against a 3.11 declaration.
6. The `lint` job takes ruff from `uv.lock` (`pip install uv` →
   `uv sync --extra dev` → `uv run ruff check .` / `uv run ruff format --check
   .`), so the tool that defines "clean" is the one the lock names.

*Evidence:*
* `ruff check .` and `ruff format --check .` clean with the target declared in
  pyproject, i.e. **without** the `--target-version py311` flag.
* `mypy .` clean (550 files) with `python_version = "3.11"`.
* `tests/test_tooling_targets.py` fails when any of the three declarations is
  moved out of agreement with the others: the ruff target's minor, mypy's
  `python_version` minor and the lowest minor in `requires-python` (3.11), plus
  the `typecheck` job's `python-version` and the presence of a lock-sourced ruff
  install in `lint`. Each assertion is proved able to fail by editing the value
  in a scratch copy.
* The 3.11 mypy leg is green **in CI**. The local `--python-version 3.11` run is
  a proxy on a host whose environment is 3.14, so it starts the item, it does
  not close it — see X1.

**Delivered (2026-10-27).** `target-version = "py311"`; the 12 `I001` findings
that exposed are fixed and reviewed hunk by hunk — every one is `tomllib` moving
out of the third-party block into the standard-library block, with no logic
touched. `python_version = "3.11"`, and
`spectral_viewer/core/spectrogram.py` now takes its peak with `np.max(magnitude)`
(the no-argument method form has no valid overload under the 3.11 stubs; the
`magnitude.size` guard is kept, so an empty window still gets the 0.0 sentinel).
The `typecheck` job installs `python-version: "3.11"`; the `lint` job installs
the dev extra from `uv.lock` and runs `uv run ruff`. Fifteen files carry this
window's `Changed in 2.1.6` note, as `tests/test_release_notes.py` requires. New
lock `tests/test_tooling_targets.py` (11 tests, the last two added for the
security gate's exclusions under D17). Two traps: D14 — a CI-text
assertion must read executed lines, because the job's comment quotes the command
it replaced; and D17 — a deselection entry in a gate's config must be asserted by
what it can *match*, because bandit reads each entry as a substring and `build`
alone would have silently deselected `utilities/build_user_guides.py`.

### R-16 — README tool count: verification only (already closed in 2.1.5)

*Files:* none.

*Defect:* the audit found `README.md` claiming "27 first-party tools" against a
30-tool registry. **It no longer does.** `README.md` line 3 reads "30
first-party tools"; the platform section reads "the other 29 of 30 tools"; and
the lock the audit asked for turns out to exist in a stronger form than
requested: `TestToolCountClaims` checks *every* count claim in the shipped prose
(not just the one the audit found) against the manifest, with a non-vacuity
floor of five claims and explicit assertions that the README and the deck were
read.

*Change:* none. This item closes the audit row with evidence, records the
mechanism that superseded the audit's suggested fix (D7), and names the two
locks that keep it closed.

*Evidence:* `tests/test_suite_docs_tool_coverage.py::TestToolCountClaims` (all
five cases, including `test_every_count_claim_matches_the_manifest` and
`test_the_scan_reads_the_readme_and_the_deck`) and
`tests/test_readme.py::TestMetadataLock::test_pyproject_ships_the_readme_and_30_tool_rows`
pass on the base commit. No production or documentation change is part of this
item, and `CHANGELOG.md` gets no bullet for it (§7).

### R-11 — the dependency audit must be blocking, with a dated allowlist

*Files:* `.github/workflows/ci.yml` (the audit step), new
`.github/workflows/dependency-audit.yml`, new `security/pip_audit_allowlist.toml`,
new `utilities/check_dependency_audit.py`, `CONTRIBUTING.md`
(*Dependency security scanning*), `tests/test_ci_security_audit.py`, plus the
checker's own tests.

*Defect:* the security job's audit reports but cannot fail. `continue-on-error:
true` was added in 1.4.1 "on probation for two sprints"; the probation has
outlived its two sprints by seven release cuts, and the project otherwise gates
security tightly (bandit 0 High / 0 Medium is a hard gate, secrets are scanned
against the index). A newly published advisory against a shipped dependency
therefore turns one step orange and the suite ships the graph anyway. The
finding's blast radius is the shipped lock: `uv.lock` is what users install.

*Change:*
1. `continue-on-error` is removed from the step; the checker's exit status is
   the step's verdict.
2. `utilities/check_dependency_audit.py` (stdlib only) reads a pip-audit JSON
   payload, applies the allowlist, prints one line per finding, and exits
   non-zero for: an advisory with no allowlist entry; an entry that has expired;
   an entry whose advisory is no longer reported (stale); an unparsable, empty
   or unexpectedly shaped payload (fail loudly, never pass vacuously).
3. `security/pip_audit_allowlist.toml` starts **empty**, with the schema and the
   expiry rule documented in its header. An empty list is the honest starting
   state: today's exported graph audits clean, and an entry is added only when a
   real advisory cannot be upgraded away — with its id, reason and expiry.
4. The allowlist's entries are the only suppression: the step keeps pip-audit's
   raw output in the log, and no `--ignore-vuln` is passed.
5. `.github/workflows/dependency-audit.yml` runs the same checker weekly
   (`schedule:`) and on demand (`workflow_dispatch:`) against `main`, so an
   advisory published between commits surfaces without waiting for a pull
   request, and so an expiry date can be exceeded on a week nobody commits.
6. `CONTRIBUTING.md`'s probation paragraph is replaced by the new contract
   (blocking, allowlist with expiry, weekly job, what to do when a finding
   appears).
7. `tests/test_ci_security_audit.py::test_the_step_is_on_probation` is replaced
   by the new contract — the module's docstring already treats the flag as
   something that must not be "kept forever without a recorded decision", so
   this is the deliberate edit it was built for, not a locked assertion being
   weakened.

*Evidence:*
* Checker tests, offline, over synthetic pip-audit JSON: unlisted advisory →
  non-zero; listed and unexpired → zero; expired → non-zero and the message
  names the date; stale entry → non-zero; empty payload and malformed payload →
  non-zero. Break-and-restore: removing the expiry comparison must fail the
  suite.
* `tests/test_ci_security_audit.py` asserts the step no longer carries
  `continue-on-error`, that it invokes the checker, that the weekly workflow
  exists with a `schedule:` trigger and invokes the **same** script, and that
  the allowlist file is present and parses. Non-vacuity: each slice is asserted
  non-empty, the pattern the existing module uses.
* The real-world proof of the audit's acceptance column ("CI failure on a new
  advisory") cannot be manufactured by publishing an advisory, so it is
  demonstrated on a synthetic payload in the checker's own tests and named as
  such in the verification record.

**Delivered (2026-10-28).** The step is blocking: no `continue-on-error`, no
`--ignore-vuln`, and its verdict is `utilities/check_dependency_audit.py` run
over `pip-audit -f json -o pip-audit.json` (pip-audit's payload is catted to the
log, so the raw advisory is always visible). The checker is stdlib-only —
`tomllib` is 3.11 standard library, so the floor already carries it — and
returns `0` pass, `1` policy failure, `2` no computable verdict. `1` covers an
unlisted finding, an expired entry, a stale entry, and an entry that names a
different package than the finding; `2` covers a missing/unparsable/empty
payload and a malformed allowlist, so a gate that cannot judge never reads as
green. `security/pip_audit_allowlist.toml` starts empty with its schema in the
header. `.github/workflows/dependency-audit.yml` runs the same export, payload
and checker weekly (`cron: "17 6 * * 1"`) and on `workflow_dispatch`.
`tests/test_ci_security_audit.py` drops `test_the_step_is_on_probation` for the
succeeding contract — blocking, checker-driven, weekly workflow present, no
`--ignore-vuln` in either file, allowlist parses and documents its schema — and
the checker's own 23 tests live in `utilities/tests/test_check_dependency_audit.py`
(that directory is already in `testpaths` and `utilities` in the coverage
source, so nothing needed registering).

### R-12 — a POSIX leg that runs the portable core, and a caveat that matches it

*Files:* `.github/workflows/ci.yml` (new `posix-smoke` job),
`audio_suite_shared/platform_support.py` (`MATRIX_CAVEAT` and the module
docstring's "the Linux CI leg added by plan item A4 is still `[~]` with no
recorded run"), the regenerated README platform block
(`utilities/generate_readme_platform_matrix.py`), any staged copy under `docs/`
(whichever generator owns it), and a new lock beside the existing CI locks.

*Defect:* the repository makes a portability claim it does not test, and the
claim is currently in a contradictory state. `README.md`'s Prerequisites say
"CI verifies 3.11, 3.12 and 3.14" — true — while the platform section says "**no
tool in this suite has been executed on a real Linux or macOS host**" and names
a "Linux CI leg added by plan item A4 [that] is still unrecorded". A4 is the CI
ffmpeg install — the marker description in `pyproject.toml` reads "CI installs
ffmpeg, plan A4", and `ci.yml`'s test job runs `choco install ffmpeg` — so the
caveat cites a deliverable that never existed. Meanwhile the only Ubuntu jobs
that import first-party code are the compile, lint, security and schema jobs;
nothing runs a tool package. The portable-core tier therefore rests entirely on
unit tests that simulate a platform value.

*Change:*
1. A `posix-smoke` job on `ubuntu-latest` that installs the base + dev extras
   **from the lock** (`uv sync --extra dev`), installs ffmpeg via apt, and then
   (a) smoke-checks the CLI surface — `audiosuite --help` and `audiosuite
   doctor` — and (b) runs an **explicitly declared** module selection of the
   portable core: the shared package's non-GUI modules
   (`audio_suite_shared/tests/test_cli_app.py` and its `test_cli_*` siblings
   among them), and the tool suites whose tests do not require Windows.
2. The selection is derived by **running it**, not by guessing from the README's
   tiers: the job's first landing records, in this plan, exactly which modules
   run and which are excluded with a reason (Windows-only imports, GUI
   dependencies, the registry-reading doc locks, `mypy` itself). A module whose
   test fails on POSIX is either fixed in this change (it is a real portability
   defect, and the finding exists to surface it) or excluded with the reason
   recorded here — never left in the selection to fail quietly.
3. The job's verdict is non-vacuous and attributable, in the shape the
   `docs-locks` step already uses: capture the log, fail on the real exit code,
   `grep -qE "[0-9]+ passed"`, and print the root `conftest.py`'s display
   summary — which states plainly whether GUI behaviour was verified and how
   many tests the absence of a display cost. The skip count is pinned, so a
   blanket skip cannot masquerade as a passing leg (D6).
4. The selection is pinned by a lock (new module, in the shape of
   `tests/test_ci_security_audit.py`): the job exists, the selection is
   non-empty, the job's module list and the lock's list are the same set, and a
   module cannot be dropped from the job without editing the lock.
5. `MATRIX_CAVEAT` is rewritten to say what is now true — a named selection runs
   on a real Ubuntu host on every push, and the *tier definitions are
   unchanged*: `portable-core` still means "the non-Windows arm is implemented
   and a test exercises it under a simulated platform value", and `unverified`
   still means "no test runs it under any platform value". Running a real host
   does not reclassify a tier, so the README is regenerated rather than
   re-argued, and the sentence citing plan item A4 is replaced by one naming
   this plan and the job.
6. The README's generated block is regenerated with
   `utilities/generate_readme_platform_matrix.py`; the file is never hand-edited
   (D13), and no other paragraph may grow a portability claim — the anti
   over-claim lock forbids `cross-platform`, `fully cross-platform` and `works
   on linux and macos`.

*Evidence:*
* A green `posix-smoke` run whose log carries a passed count and a bounded,
  attributable skip list; the run is the acceptance evidence in the audit's own
  terms ("green Ubuntu CLI/shared smoke run").
* `test_platform_support.py::TestReadmeDriftLock` green after the regeneration,
  including the verbatim-caveat case, and the tool-index platform column
  unchanged (the tiers did not move).
* The new CI lock fails when the job is deleted, when a module is removed from
  its selection, and when the selection is emptied — each proved by mutating a
  scratch copy.
* The CLI smoke commands are the two the finding names and both exist today:
  `doctor` is registered by `audio_suite_shared/cli_app.py` even when a tool
  package fails to import, which is why it is the right smoke for a host nobody
  has run before.

**Delivered (2026-10-28).** `posix-smoke` runs between `compile` and `test`:
`ubuntu-latest`, Python 3.12, `uv sync --extra dev` from the lock, ffmpeg via
apt, the two CLI smokes, then the declared **37-module** selection with
`--no-cov -q -rf`. The verdict is the real exit code *plus* a passed floor of
1756 and a skip ceiling of 1, and the step cats the log so the conftest's
display report reaches CI. `tests/test_ci_posix_leg.py` (17 tests) pins the job,
the selection set-equality in both directions, the absence of `xvfb`/`DISPLAY`,
the `continue-on-error` absence, both comparisons, and that the caveat names the
job; `tests/ci_workflow.py` supplies the slicing, and every slice is asserted
non-empty first.

The measured derivation (D18) is **1757 collected, 1756 passed, 1 skipped, 0
failed** — the skip is `tag_editor/tests/test_csv_io.py`'s Windows
drive-relative case. Getting there fixed five things the leg exposed (D19):

1. `suite_config._cleanup_stale_tmps` globbed the config directory outside any
   handler, so on a POSIX host with an unlistable directory a `PermissionError`
   escaped `_save`, which documents itself as swallowing write failures.
2. `suite_config._save`'s `finally` probed `tmp.exists()` before unlinking;
   3.12's `exists()` ignores only `ENOENT`/`ENOTDIR`, so `EACCES` re-raised.
   `_try_unlink` already swallows every `OSError`, so the probe is gone.
3. `test_secure_subprocess` passed `C:/evil` as an "absolute" path, which is
   relative on POSIX, so the resolve guard never ran.
4. `test_suite_config`'s read-only-tmp cleanup assumed Windows refuses the
   unlink; POSIX unlinks it, so its restore now checks first.
5. Two `test_venv_bootstrap` re-exec tests are Windows-shaped by design but read
   the real `sys.platform`; `ensure_venv_interpreter` now takes the tests-only
   `platform` override `find_venv_interpreter` already had.

`test_reorganizer.py`'s four FLAC-fixture classes also gained the `integration`
marker, the same defect class the silence-trim smoke had: pydub's export shells
out to ffmpeg, so a host without it went red instead of skipping.

`MATRIX_CAVEAT` now says a named selection runs on a real Ubuntu host on every
push, that nothing else has been executed on a foreign platform, and that no
tool has been driven end to end on Linux; the README block is regenerated by
`utilities/generate_readme_platform_matrix.py` and the stale "Linux CI leg added
by plan item A4" sentence is gone — `test_platform_support.py` now asserts its
absence. **Two traps, both caught by breaking the lock on purpose (D20):** a
CI-text assertion must name the *comparison*, because the step's own failure
message quotes the bound and a substring match survives a lowered floor; and a
derivation host with WSLg is **not** headless, so the display branch has to be
forced (`DISPLAY` unset) before the "NOT VERIFIED" claim means anything.

### R-17 — one full-suite leg, because three spent the month (added 2026-10-28)

*Files:* `.github/workflows/ci.yml` (the `test` job, the header comment, and two
comments that named the matrix in the present tense), `tests/ci_workflow.py`
(new `job_names()`), new `tests/test_ci_cost.py`,
`tests/test_cli_schema_conformance.py` (the publishing-leg lock replaces the
matrix-gate one), `README.md` (prerequisites), `CONTRIBUTING.md` (`docs-locks`),
`AGENTS.md` (*The Python floor must honour its lockfile*), `CHANGELOG.md`.

*Why it exists:* X9 measured an account-level block, not a defect, and its
numbers name the cause — three full legs at **160.9 of a 168.0-minute push**
while every other job costs **7.1** together. The suite is not what got cheaper;
the number of times it runs on a push is. The audit's register stops at R-16, so
this item is numbered after it and marked as a cost decision rather than a
finding (D23).

*Change:* the matrix is **one leg, on 3.11**, and it keeps everything the three
legs did between them: the suite with `--cov-fail-under=75`, the recorded CLI
payloads and their artifact, the documentation site build and its artifact, and
the instruction locks. The artifact and documentation steps' own comment already
said the files come from committed sources and are identical on every
interpreter, which is why they move to the floor leg rather than being dropped —
and `uv.lock` locks sphinx **9.0.4 for this interpreter**, so the floor can build
the docs it publishes.

*Why the floor keeps the full suite:* `uv.lock` resolves **two** dependency
graphs — numpy 1.26.4 / scipy 1.17.1 / sphinx 9.0.4 below 3.12 against 2.5.4 /
1.18.1 / 9.x above it — and the development host (3.14.7) runs the second one
every day under the mandatory local gate. 3.12 resolves that same branch, so
3.12 and 3.14 were re-testing the graph in daily use while 3.11 is the only place
the floor's stack, and the promise `requires-python` makes, is executed at all.
This is D15's argument for `typecheck`, applied to the suite. X9's rule stands:
the reduction keeps the floor leg and the Windows OS sweep, so it is a recorded
decision, not a green bought under duress.

*What it costs, and what it no longer covers:* a push projects **68.7** billable
minutes — 61.4 for the leg (its worst measured 60.4 plus ≤1.0 for the publishing
steps, measured at 0.1-0.2 minutes each) and 7.3 for the rest — down from 168.0.
CI no longer runs the full suite on 3.12 or 3.14; **X10** names exactly what that
leaves to the local gate and the three ways to buy it back.

*Evidence:* `tests/test_ci_cost.py` prices every job, asserts one interpreter on
the floor, asserts no matrix, asserts the projection and its headroom, and
proves the arithmetic rejects a doubled leg; it fails on a job added without a
price, a job renamed out of the ledger, an unpriced runner (macOS bills at 10x)
and a widened matrix. `tests/test_cli_schema_conformance.py` now asserts the
publishing steps are **unconditional**, which is the state that replaces "gated
to one leg". `README.md`, `CONTRIBUTING.md` and `AGENTS.md` no longer claim CI
verifies three interpreters.

---

## 4. Traceability

| Finding | Sev | Item | Acceptance evidence (audit §9.1) | Release |
|---|---|---|---|---|
| R-11 — dependency audit non-blocking | P2 | §3 R-11 | CI failure on a new advisory | 2.1.7 |
| R-12 — POSIX untested | P2 | §3 R-12 | green Ubuntu CLI/shared smoke run | 2.1.7 |
| R-15 — Ruff/mypy targets below floor | P2 | §3 R-15 | 3.11 typecheck leg green | 2.1.6 |
| R-16 — README count stale | P3 | §3 R-16 | README assertion matches `len(first_party())` | none (closed in 2.1.5) |
| R-17 — three suite legs per push (cost) | — (not in the audit's register) | §3 R-17 | projected push ≤ 100 billable minutes, priced by a lock | 2.1.6 |

---

## 5. Verification record

Filled per item as it lands, under AGENTS.md's gate — compile, `ruff check` /
`ruff format --check`, bare `mypy .`, `bandit -r . -x ./.venv -c pyproject.toml`
(0 High / 0 Medium), bare `pytest` — plus, for the CI items, the runner's own
verdict. The last complete record is `PLAN_ci_2026-10-27_remediation.md` §4 at
`f273729` (all nine jobs green); nothing in this plan inherits its numbers.

Three claims in this plan cannot be closed on the development host and must be
recorded as runner-verified when they are: the 3.11 mypy leg (R-15), the
`posix-smoke` leg itself (R-12), and the weekly workflow's first scheduled run
(R-11). Each is named in §6 as an open verification rather than asserted here.

### R-15 — measured 2026-10-27 (development host: Windows, Python 3.14)

* `python -m compileall -q -f .` — exit 0 (only the pre-existing third-party
  pydub `SyntaxWarning` noise).
* `ruff check .` — clean **with `target-version = "py311"` declared in
  pyproject**, i.e. without passing the flag that produced the failing run.
* `ruff format --check .` — clean, 938 files.
* `python -m mypy .` — clean, **550 source files**, with
  `python_version = "3.11"`.
* `bandit -r . -x ./.venv -c pyproject.toml` — **0 High / 0 Medium** (38 Low, the
  documented tail), 11.5 s. With the installer's tree readable it reported
  **3 690 High** from the staged CPython stdlib, so this number is only
  reproducible *because* D17's exclusion is in place; the count is asserted, not
  observed once, by `tests/test_tooling_targets.py` (below).
* bare `pytest` — **11 155 passed, 3 skipped, 35 deselected, 905 s**, coverage
  **90.89 %**, floor 75 % reached. The 11 146 of the CI plan's record plus the
  nine new tests in `tests/test_tooling_targets.py`. That measurement predates
  `packaging/build`, i.e. it is the number CI reproduces.
* bare `pytest` again, **with the installer's build tree present and D16/D17
  applied** — **11 157 passed, 3 skipped, 35 deselected, exit 0**, coverage
  **90.89 %**, 2 400 s. The eleven tests of `tests/test_tooling_targets.py`, the
  five repaired walks and none of the 26 failures/errors of the run before it.
  Two things to read honestly: the delta is that run's 11 155 plus the two tests
  added under D17, and the wall time is much higher than the 905 s above — this
  record does not explain why, and it is stated rather than attributed, because
  a 40-minute suite that used to take 15 is worth a look before it is blamed on
  a build tree in one working copy.

**Break-and-restore.** `ci.yml` was mutated to the pre-R-15 values in two
passes — the typecheck job back to `python-version: "3.12"`, then
`uv run ruff check .` back to `ruff check .` — and each mutation failed exactly
the one lock that owns it (verdicts keyed on `FAILED` lines, never on a word
appearing in the output) while the restored file passed both again; restores
were SHA-256-verified, and the mutated file is data rather than an imported
module, so no stale bytecode could have carried a verdict. The pyproject half is
proved inside the lock: a py310 Ruff target, a 3.12 mypy target and a raised
floor are each applied to an edited copy of the real file and must be reported.

**The first push failed `Type Check` — and that was the floor leg doing its job.**
`71b260c` reported 13 errors, all `[type-arg]`: the lock resolves **numpy 1.26.4 /
scipy 1.17.1 for `python_full_version < '3.12'`** against numpy 2.5.4 / scipy
1.18.1 above it, and numpy 1.26's stubs leave ``ndarray`` generic with no
defaults, so ``--strict``'s ``disallow_any_generics`` rejected bare
``np.ndarray`` annotations that 2.5.4's stubs accept. Thirteen sites across three
modules: four in `audio_suite_shared/audio_conversion.py`, four in
`pop_click_remover/core/declicker.py`, five in
`noise_reduction/core/noise_reducer.py`. Each is now parameterised from its
callers' actual dtypes — `float32` at the decode/encode boundary, `float64` on
the scipy DSP paths, `integer[Any]` for sample indices, and `floating[Any]` where
the value arrives as `clip_to_range`'s declared return — never a blanket `Any`.

**Reproduced and verified locally.** `uv python install 3.11` plus
`uv sync --frozen` with the job's extras gives the runner's interpreter and
numeric stack (3.11.16, numpy 1.26.4, scipy 1.17.1). `mypy .` is clean there and
in the 3.14 development environment, 550 files each — the floor environment is
where the thirteen `type-arg` errors reproduce, and it is the only environment
in which "fixed" is a measurement rather than an inference.

**Verifying it also exposed D16 and D17.** Neither is an R-15 defect and neither
reproduces in CI (a clean checkout has no `packaging/build`) — but both are
*local* gate failures a developer can reach by running the installer, which is
what "the gate can be run" means. D16's five locks and mypy's `exclude` are
fixes to the walks; D17 is a fix to a gate *command's* scope, and it was found
last because bandit is the final step of the gate and the first run of it in
this state took minutes. The three locks found after the first full-suite run
(`test_test_file_naming`, `test_external_records`,
`test_cli_helpers_ast_lock`) were fixed with the same two-part change — skip
`build`/`dist` parts, keep the existing `tests` skip — and the five pass in
**127 tests / 15.9 s** with the tree still present.

**The runner settled it — run `40563584800` at `5298301` (2026-10-27).**
`Type Check` is **green** (18:49:52 → 18:51:18): the job installed Python 3.11,
ran `uv sync --extra dev --extra analysis --extra cd-ripping`, then
`uv run mypy .` — every step success. That is R-15's acceptance evidence (audit
§9.1's "3.11 typecheck leg green"), and it is the one job the previous commit
failed: in `40547259435` the failing step was `Run uv run mypy .` while every
other job, all three `Test` legs included, was green — so the 13 `type-arg`
errors were the whole failure, not one symptom of several.
`Lint & Format` is **green** in the same run (18:49:51 → 18:50:04), having run
`pip install uv` → `uv sync --extra dev` → `uv run ruff check .` →
`uv run ruff format --check .`: the lock-sourced install that replaced an
unpinned `pip install ruff`, and the one step of R-15 this host could not
exercise. `Compile / Pre-flight gate`, `CLI schema conformance`,
`Security Scan` and `Docs locks (freshness & formats)` are green too, each in
under a minute except the security job's 38 s.

**The run as a whole is `success`** — completed 19:19:15Z with all nine jobs
green. The three `Test` legs finished last: 3.14 at 19:15:54Z, 3.11 at
19:17:14Z, 3.12 at 19:19:14Z (24:09 / 25:46 / 27:21). Each leg's own line reads
**11 154 passed, 6 skipped, 35 deselected**, coverage 90.88 %.

That count is the same 11 160 selected tests this host runs (11 157 passed + 3
skipped), with three more skipped on the runner, and the difference is fully
named rather than inferred: four ffmpeg-dependent tests skip there
(`tests/test_refinery_pipeline.py` ×2 and
`music_format_converter/tests/test_file_processor.py` ×2 — ffmpeg is installed on
this host), while this host's `Symlink creation unavailable on this platform`
skip passes there — a net of three, 11157 - 11154. The Tk slider and Unix-only
permission skips are common to both. So the runner and this host agree on the
suite, and the agreement is legible in the skipped set rather than assumed from
the totals.

None of the numbers above came from a local proxy: they are the runner's own
verdicts, read from the Actions API at run `40563584800`
(https://github.com/wilte01/AudioSuite-Pro/actions/runs/40563584800).

**The tip has been green twice since — runs `40568799837` at `61a19dd` and
`40573946202` at `1ab0e39`.** Both are documentation-only commits carrying this
record (`git show --stat` lists one file for each, this plan), and both
completed `success` with every job green and **no failed step**. Job wall-clock
durations, which is the measure these bullets use throughout:

* `61a19dd` (19:24:21Z → 19:53:26Z): `Type Check` 01:10, `Lint & Format` 00:17,
  `Docs locks (freshness & formats)` 01:08, `Security Scan` 00:33,
  `Compile / Pre-flight gate` and `CLI schema conformance` 00:09, `Test` 3.14
  25:14 → 3.12 28:54 → 3.11 28:59; each leg **11 154 passed, 6 skipped,
  35 deselected** at 90.87–90.88 % coverage.
* `1ab0e39` (19:59:01Z → 20:28:43Z): `Type Check` 01:14, `Lint & Format` 00:14,
  `Docs locks (freshness & formats)` 01:16, `Security Scan` 00:31,
  `Compile / Pre-flight gate` and `CLI schema conformance` 00:09, `Test` 3.14
  25:27 → 3.12 28:20 → 3.11 29:39; the pytest line again reads **11 154 passed,
  6 skipped, 35 deselected**, at 90.87 % coverage on 3.14 and 90.88 % on 3.11
  and 3.12.

Three consecutive runs of this window are therefore green with the floor leg in
them, and the 3.11 leg's verdict is identical in all three, so the state is a
property of the commits rather than of one lucky run.

**One measured consequence for R-12.** Each leg's coverage header names its own
interpreter and platform — `platform win32, python 3.11.9-final-0`,
`… 3.12.10-final-0`, `… 3.14.9-final-0` — so an all-green run here says nothing
whatsoever about POSIX. That is R-12's premise, read out of the runner's own
output rather than inferred from `ci.yml`.

**Where the chasing stops, said out loud.** This note is itself a
documentation-only commit, and its run is not awaited: recording the record
would otherwise move the subject every time it is written, so the chain could
never close. What the record establishes is concrete and bounded — `5298301`
(code, run `40563584800`), `61a19dd` (run `40568799837`) and `1ab0e39`
(run `40573946202`,
https://github.com/wilte01/AudioSuite-Pro/actions/runs/40573946202) — each green
in all nine jobs. The next *code* change is the next thing whose run belongs
here; a fourth docs-only round would add nothing about the tests, since the last
two runs already exercised byte-identical source and the same nine jobs passed
twice over it.

### R-12 — measured 2026-10-28 (two hosts, then the runner; X8 closed)

*Development host (Windows, Python 3.14):*
* `python -m compileall -q -f` over the 938 tracked first-party `.py` files —
exit 0. Bare `compileall .` exits non-zero on this host only because it walks
`packaging/build`'s staged CPython `Lib/test` corpus, whose bad-syntax fixtures
are deliberate (D16); CI checks out a clean tree.
* `ruff check .` — clean; `ruff format --check .` — 939 files formatted.
* `python -m mypy .` — clean, 550 source files.
* `bandit -r . -x ./.venv -c pyproject.toml` — **0 High / 0 Medium** (38 Low,
the documented first-party `subprocess` tail).
* bare `pytest` at the state committed here — **11 174 passed, 3 skipped, 35
deselected, 0 failed**, coverage 90.88% against the 75% floor, 17 m 49 s. (A
first attempt was discarded rather than reported: it ran while the caveat was
being rewritten and regenerated, and its two README-drift failures were that
race, not the tree — the module passed standalone before and after.)
* `tests/test_ci_posix_leg.py` — 17 passed; the platform, release-notes,
changelog and docs-format locks pass alongside it (93 in the batch).
* The five repaired tests and their modules — 177 passed on Windows, so the
marker and platform changes did not weaken anything the Windows gate covers.

*Linux derivation host (WSL Ubuntu, CPython 3.12.16, ffmpeg 7.0.2 static, no
display — D18), running the job's own 37 modules in one invocation:*
* **1757 collected: 1756 passed, 1 skipped, 0 failed**, exit 0. The skip is
`tag_editor/tests/test_csv_io.py:253` — "Windows drive-relative paths".
* Repeated with the interpreter `uv sync --extra dev` builds inside the checkout
— the job's own install command, so nothing from the `analysis` or `ml` extra
leaks in and confirms base dependencies rather than my test venv: same 1757 /
1756 / 1, exit 0.
* The conftest report reads `Tk display available : NO — tk.Tk() raised
TclError`, `Tests skipped for display reasons : 0 of 1757 collected`, `GUI
behaviour : NOT VERIFIED in this run`. The selection therefore costs no GUI
coverage, which is the honest reason the caveat does not mention a cost.
* Before the fixes the same run said 1751 passed / 5 failed; with ffmpeg absent
it also said 39 failed (the ffmpeg-fixture classes), which is what drove the
`integration` markers rather than a selection change. The bounds landed padded
(1750/10) and were tightened to these measured values once the runner
reproduced them (D21).

*Break-and-restore (the lock must be able to fail):* four `ci.yml` mutations —
job renamed (11 tests red), one module removed (`test_the_job_runs_exactly_the_
declared_modules` red), floor lowered (`test_a_passed_count_is_required` red),
skip ceiling raised (`test_the_skip_count_is_capped` red) — each from a byte
copy restored under a SHA-256 check that reported `restored: True`. The first
attempt of that harness **passed while proving nothing**: it swallowed its own
assertion inside the restore's `finally`, and the second attempt showed two of
the four mutations were green — D20.

*Runner (2026-10-28, run
[`40663662748`](https://github.com/wilte01/AudioSuite-Pro/actions/runs/40663662748)
at `b7ee2f9`):* `POSIX smoke (Ubuntu)` — **success**, and its log reproduces the
derivation **exactly**: `1756 passed, 1 skipped` of 1757 collected, `Tk display
available : NO`, `Tests skipped for display reasons : 0 of 1757`, `GUI behaviour
: NOT VERIFIED`, then `POSIX smoke pass: 1756 passed, 1 skipped`. That run was
still under the derivation's padded bounds (1750/10); because it reported
exactly the measured 1756 / 1, D21 tightens the lock to those values, so the leg
now fails on drift in either direction instead of absorbing ten. Ubuntu's apt
ffmpeg also behaved like the static 7.0.2 build the selection was measured
with — same passed count, same single skip. The job ran in 1 m 2 s, which is
what makes a per-push platform check affordable. The rest of that run is green
too — **all ten jobs**, the 3.11 / 3.12 / 3.14 test legs included, which is the
evidence that the `suite_config` and `venv_bootstrap` changes hold on the floor
interpreter and not only on this host. The tightened bounds were then exercised
rather than assumed: `1aceef1` (run
[`40668180562`](https://github.com/wilte01/AudioSuite-Pro/actions/runs/40668180562))
runs the step with `if [ "$passed" -lt 1756 ]` and `if [ "$skipped" -gt 1 ]` in
force — visible in its log — and passes with `POSIX smoke pass: 1756 passed, 1
skipped`, so equality holds on the runner and not just in the lock. This record
is itself documentation-only, so its own run is not awaited (the predecessor record's convention): the
verdicts above belong to `b7ee2f9`, and `df69bf9`'s `posix-smoke` is green as
well.

### R-11 — measured 2026-10-28 (development host; runner verdict in X9)

*Checker tests* — 23 passed in `utilities/tests/test_check_dependency_audit.py`:
a clean audit passes; an unlisted advisory fails; a listed and unexpired entry
passes; an expired entry fails and names `2000-01-01`; a stale entry fails; an
entry naming another package fails; a bare-list payload and a dependency with no
`vulns` key are accepted; a missing, unparsable, empty or mis-shaped payload and
a missing, incomplete or unparsable allowlist all exit `2`; and the expiry
boundary accepts *on* the date and fails the day after.

*Break-and-restore* — three mutations of the shipped checker, each red: the
expiry comparison removed (2 tests), the staleness check removed (1), the empty
payload accepted (1). Source restored under a SHA-256 check with `__pycache__`
cleared before every verdict, so a stale `.pyc` could not produce the result.

*A real audit, end to end on this host* — `uv export --frozen --all-extras
--no-emit-project …` produced a 490-line requirements file, `uvx pip-audit -r …
--no-deps -f json -o …` audited **130 packages with 0 advisories** ("No known
vulnerabilities found"), and the checker printed `[OK] dependency audit: 0
advisory finding(s), all allowlisted and unexpired; allowlist entries: 0` with
exit 0. That is the premise the empty allowlist rests on, measured rather than
assumed.

*Locks and gate* — `tests/test_ci_security_audit.py` green with the two new
classes (blocking contract, weekly workflow, allowlist), `ruff check` and `ruff
format --check` clean (941 files), `mypy .` clean (551 source files), bandit 0
High / 0 Medium. Both workflow files parse as YAML, and the parsed audit step
has no `continue-on-error` key and does invoke the checker.

*Not demonstrated* — a genuinely new advisory failing the build. That half of
the audit's acceptance column cannot be manufactured without publishing an
advisory, so it is proved on a synthetic payload and named as such.

**The runner verdict is blocked, and this is not a green (X9).** The push of
`d1027ad` created run `40673801647` and every one of its ten jobs - the
compile-only job included, and the POSIX leg that has been green all day -
concluded `failure` with `steps: []`, an empty `runner_name`, and no log blob at
all (`BlobNotFound`), i.e. no step ever began. A `rerun-failed-jobs` reproduced
it identically on attempt 2. Three diagnostics narrow it down: the workflow's
jobs were **created**, so the file parses (a corrupt workflow creates none);
`/actions/permissions` reports `enabled: true`, `allowed_actions: all`;
and githubstatus.com reports Actions operational with no incident today, while
the previous run (`40668603600` at `8229b05`, 10:00Z) is green - so the block
started between 10:00 and 10:39Z. The remaining explanation is account-level
Actions minutes or a spending limit on this private repository, which only the
owner can see (the available token carries no billing scope). **R-11 is
therefore delivered and locally verified but not runner-verified**, and no
reviewer should read the failed run as a defect in the audit step.

*Re-checked at 11:19Z on 2026-10-28: still blocked, and the cause is now measured
rather than inferred.* Run `40674405486` at `d459fb0` (the record commit, 10:43Z)
again created ten jobs and every one of them concluded `failure` with
`steps: []` and an empty `runner_name`. Summing each job's `started_at` to
`completed_at` for every October run at the multipliers GitHub bills (Linux 1×,
Windows 2×) gives **2 651.6 billable minutes across 20 runs**, and the ten green
runs immediately before the block cost **166–193 minutes each** — the eight
Windows jobs bill at double, which is where most of it goes. The running total
was **2 647 minutes** when `d1027ad` was pushed at 10:39Z, and the block begins
exactly there: `8229b05` (ending 10:05Z, total 2 647) is green, `d1027ad` is not.
The sum under-counts, because GitHub rounds each job *up* to the minute and this
one does not, so the true figure is higher — consistent with a private-repo
monthly allowance (2 000 free / 3 000 Pro minutes) rather than with a per-run
quota, a concurrency limit or a code defect. Nothing in the workflow changed
between the green and the blocked run, and no platform incident is reported.
The implication for the rest of this plan is a budget one: at ~170 billable
minutes per push, a 3 000-minute allowance funds roughly **seventeen pushes a
month**, so runner verification has to be batched deliberately rather than
assumed on every commit.
### R-17 — measured 2026-10-28 (development host; runner verdict pending, X9)

*The price, measured rather than estimated.* Every job's `started_at` to
`completed_at` from run `40668603600` (`8229b05`, the last green run before the
block), at GitHub's documented multipliers:

| Job | Wall | × | Billable |
|---|---|---|---|
| Test (Python 3.11) | 28.3 min | 2 | 56.5 |
| Test (Python 3.12) | 27.7 min | 2 | 55.4 |
| Test (Python 3.14) | 24.5 min | 2 | 49.0 |
| Docs locks (freshness & formats) | 1.4 min | 2 | 2.7 |
| Type Check | 1.1 min | 2 | 2.1 |
| POSIX smoke (Ubuntu) | 1.2 min | 1 | 1.2 |
| Security Scan | 0.6 min | 1 | 0.6 |
| Lint & Format | 0.3 min | 1 | 0.3 |
| Compile / Pre-flight gate | 0.1 min | 1 | 0.1 |
| CLI schema conformance | 0.1 min | 1 | 0.1 |
| **Total** | | | **168.0** |

The same sum for run `40579580275` is **172.5**, and its 3.11 leg is 30.2 min
(**60.4** billable) — the worst observed, which is the figure the ledger keeps.
So the three legs were **160.9 of 168.0**, and the other seven jobs **7.1**
together: the matrix was 96% of a push, and nothing else was worth touching.

*The steps the floor leg inherits.* Per-step timings on the retired 3.14 leg:
export 0.0 min, `cli-payloads` upload 0.0, documentation build 0.1, its upload
0.0 — so moving them to the floor leg costs **≤ 0.4** billable minutes, and the
projection is 61.4 + 7.3 = **68.7** against the 100-minute budget (31.3 of
headroom, so ordinary suite growth does not trip the lock; a second leg at 56.5
would reach 125.2 and does).

*Locks.* `tests/test_ci_cost.py` — 13 passed. With
`tests/test_cli_schema_conformance.py`, `tests/test_ci_security_audit.py`,
`tests/test_ci_posix_leg.py` and `tests/test_tooling_targets.py` the batch is
**142 passed, 0 failed**. `job_names()` is exercised through the ledger's two
directions, so a job added *and* a ledger entry gone stale are both red.

*Break-and-restore (the lock must be able to fail).* Three mutations of the
committed workflow, each from the byte copy restored under a SHA-256 check that
reported `restored: True` before the next ran, and each verdict keyed on
pytest's own `FAILED tests/test_ci_cost.py::<id>` line rather than on a word in
the output:

* a second `python-version` inside the suite leg (a matrix by another name) —
  `TestTheSuiteRunsOnce::test_the_suite_leg_runs_on_one_interpreter` **1 failed**;
* an `extra-leg` job added and left unpriced —
  `TestTheLedgerCoversTheWorkflow::test_every_job_is_in_the_ledger` **1 failed**;
* the suite leg moved to 3.14 —
  `TestTheSuiteRunsOnce::test_the_suite_leg_installs_the_floor` **1 failed**.

The first attempt of the harness **passed while proving nothing**: its anchors
were written with `\n` while the working tree is CRLF, so all three mutations
reported `anchor matched 0 times` and the run still exited 0. The fix was to
express every anchor with the file's own terminator and to scope the
`python-version` anchors to the `test` job, because `3.11` also appears in
`typecheck` — D14's class of mistake in a third shape, and the reason the
harness now exits non-zero when a mutation stays green.

*Gate.* `compileall` exit 0 over the tracked `.py` files (bare `compileall .`
walks the gitignored `packaging/build` corpus, which is D16's subject and not
this one); `ruff check .` / `ruff format --check .` clean (**942** files); bare
`mypy .` clean (**551** source files); bandit `-r . -x ./.venv -c pyproject.toml`
**0 High / 0 Medium** (38 Low, the documented first-party `subprocess` tail; its
exit 1 is the any-finding behaviour §3 explains). Bare `pytest` first reported
**11 219 passed, 3 skipped, 35 deselected, 1 failed** in 39 m 20 s — see the
defect below — and after the repair **11 220 passed, 3 skipped, 35 deselected,
0 failed** in 32 m 14 s.

*A defect the gate found, fixed in this change.* The full suite failed
`tests/test_release_notes.py::TestPerFileChangeNote::
test_every_changed_code_file_carries_the_note`, naming two files without the
`Changed in 2.1.6` note every changed code/config file must carry:
`security/pip_audit_allowlist.toml` — **from R-11's commit `d1027ad`, not from
this one**, which is why it survived that item's gate: the note lock reads
every file changed since the baseline, so a note missing from one earlier
commit surfaces on the next full run — and `tests/test_cli_schema_conformance.py`
from this change. Both gained the note; the affected lock then reported **95
passed** with `tests/test_ci_cost.py` and the conformance suite, and the second
bare run above is the whole suite on the repaired tree.

*Not demonstrated, and deliberately so.* **No runner has executed this
workflow.** The account's Actions minutes are still exhausted, so the first
verdict on the new shape is unpaid-for until the spending limit is raised or the
cycle resets (X9). The change is committed on `main` ("Run the suite once, on the
floor, and price every CI job") and **not pushed**: a push right now would only
add another zero-step failed run to X9's tally, so the first verdict on the new
shape waits for the limit to move. The ledger is a measurement of the *shape* —
one leg, on the floor, priced per job — not a promise about the runner's clock
on the day.

---

## 6. Open items, and deferrals this plan creates

* **X1 — CLOSED as a claim; what remains is a measurement gap, not an open
  question.** The two runner-only claims are settled: `Type Check` and
  `Lint & Format` are green at `5298301`, and so is the rest of run
  `40563584800` — the window's CI state is now known rather than inferred. R-15
  is therefore complete *and* runner-verified, and the Linux
  `uv sync --extra dev` that replaced a single-package `pip install` has run. What stays true is narrower:
  this development host is 3.14, so the 3.11 reproduction is an environment
  built from the lock (3.11.16 / numpy 1.26.4) rather than the runner's own, and
  a defect that needs a 3.12-only wheel would still be runner-only. Carry the
  measurement trap rather than the claim: the lock resolves *different* numpy and
  scipy legs below 3.12 (AGENTS.md, *A dependency's version can change which
  branch runs*), which is exactly how the thirteen `type-arg` errors passed this
  host's own `mypy .` and only appeared on the floor leg.
* **X2 — the `UP` rule set** (D11). Measured at `85046ef`: 317 findings, 314
  fixable — `UP045` 139, `UP035` 80, `UP037` 57, `UP024` 21, `UP015` 10,
  `UP033` 6, `UP007` 1, `UP031` 1, `UP012` 1, `UP009` 1. Its own change, with
  `ruff check --diff --select UP` reviewed by hand rather than applied blind.
  `UP007` is the audit's "135 `Optional[...]` alongside `X | None`" observation
  and is not auto-fixable. `UP042` reports nothing today; if it is ever taken,
  AGENTS.md's `str`-mixin enum trap governs every interpolation site in the
  package, not just the refactored module.
* **X3 — the 2.1.6 cut** (CI plan X3). `[Unreleased]` is written but unreleased,
  and this plan does not authorise the cut. R-15 lands in the window either way;
  whether R-11/R-12 ride 2.1.6 or their own 2.1.7 is a release decision, not an
  item.
* **X9 — OPEN: the audit step has no runner verdict yet, because no job starts,
  and the reason is now measured: the account's Actions minutes are exhausted.**
  Attempted at `d1027ad` (run `40673801647`) and re-checked at `d459fb0` (run
  `40674405486`, 10:43Z): all ten jobs, in both runs, concluded `failure` with
  `steps: []`, an empty `runner_name` and no log blob — no step ever began — and a
  `rerun-failed-jobs` reproduced it. That is not the step: the jobs are *created*
  from a workflow that parses, `/actions/permissions` reports `enabled: true`,
  no platform incident is open, and the run twelve minutes earlier was green.
  The block lands on the bank balance rather than on a defect: October usage is
  **2 651.6 billable minutes across 20 runs**, the green runs immediately before
  the block cost 166–193 each, and the total stood at 2 647 when the blocked push
  happened (see §5 for the per-run table; the figure is a floor, since GitHub
  rounds each job up to the minute). At ~170 minutes a push, this suite can be
  runner-verified roughly seventeen times a month on a 3 000-minute allowance.
  The owner's levers, none of them a code change: raise the spending limit
  (Settings → Billing → Actions), wait for the cycle reset on the 1st, or make
  the repository public, which removes the private-repo minute charge entirely.
  Once jobs start again, **any** run at or after `d1027ad` settles this, and the
  `Security Scan` log should print `[OK] dependency audit: 0 advisory finding(s)
  … allowlist entries: 0`. A *new* advisory failing the build stays
  unmanufacturable, as §3 says. Do not close this by reading a failed
  pre-execution run as a pass; do not weaken the step to make the job start —
  the two are unrelated. The rule against cutting the matrix to make a run
  affordable still holds as written: a green bought by dropping the OS legs and
  the floor leg certifies less than the suite does today. **R-17 is that rule's
  lawful shape, not an exception to it** — the Windows OS sweep and the 3.11
  floor leg both survive with the full suite, the two legs that went were
  re-testing the graph the development host runs daily, and the reduction is
  D23 with a measured bill beside it. Any *later* narrowing starts from X10.
* **X10 — the newest interpreter no longer has a CI leg; here is what that costs
  and how to buy it back.** R-17 runs the full suite on **3.11 only**, so a
  push no longer verifies 3.12 or 3.14 on a runner. Deliberate, for the reasons
  D23 records (3.12 resolves the same graph as 3.14; the development host runs
  3.14 under the mandatory local gate), but it is a real narrowing and it is not
  left implicit: a regression that only 3.14 shows is now caught by the
  developer's own gate rather than by CI. Three remedies, cheapest first —
  restore the leg on a throwaway branch and run it through `workflow_dispatch`
  when a 3.14 question needs a runner (~49 minutes, no per-push cost); add a
  weekly scheduled run of the same leg (~56 a week, ~240 a month, which a
  3 000-minute allowance absorbs); or halve the suite's wall time with
  `pytest-xdist` so the second leg fits inside the 100-minute budget. None is
  authorised here; `tests/test_ci_cost.py` is what stops the third being
  skipped quietly.
* **X8 — CLOSED: the first `posix-smoke` run is green.** Run `40663662748` at
  `b7ee2f9` reports success with `1756 passed, 1 skipped` and the display report
  §5 quotes, so the bounds now equal what the runner reported (D21) and no POSIX
  defect survived the fixes. What the closure does *not* claim: the leg covers 37 declared modules
  of 1 110 collected suite-wide, and no tool has been driven end to end on
  Linux — the caveat says both. The rule that governed it still stands for
  later edits: a red leg is a POSIX defect to fix, never a selection to narrow
  quietly, and narrowing it is only legitimate together with a sentence here
  saying which module and why.
* **X4 — R-13 and R-14 remain deferred.** The cache key's path+mtime identity
  and the non-ASCII console output are the register's remaining P3 defects; they
  are outside this brief and stay in the predecessor's §8.
* **X5 — no macOS leg** (D12). Recorded as a decision, not an omission: revisit
  only with a supporting claim to make.
* **X6 — no `smoke` marker / fast profile** (audit Q-09). The POSIX leg uses an
  explicit declared selection instead of a new marker, so the two do not
  compete for the same problem.
* **X7 — one quoted value in `AGENTS.md` is now behind the config it illustrates.**
  The *Bandit needs `-c pyproject.toml`* rule explains the trap by quoting
  `exclude_dirs = ["tests"]`; the real value is now
  `["tests", "packaging"]` (D17). The rule's point is unchanged and the fix is
  one word, but `AGENTS.md` is the frozen rule set (`tests/test_agents_md.py`
  holds `RULE_INVENTORY`), so it belongs in a deliberate `AGENTS.md` change
  rather than a drive-by inside an R-15 diff — the same call
  `PLAN_ci_2026-10-27_remediation.md` D12 made. Recorded, not fixed, and not
  silent: the value a reader greps for is the one in `pyproject.toml`.

---

## 7. Changelog mapping

When the items land, `CHANGELOG.md`'s `[Unreleased]` carries: R-15 under
**Changed** (the tooling now targets the interpreter the project declares, and
one real type error the old target hid is fixed); R-11 under **Changed** (the
dependency audit is blocking, with a dated allowlist and a weekly run); R-12
under **Added** (a POSIX smoke leg, and the platform caveat rewritten to match
it) and under **Fixed** (the shared-config save that could raise where it
promised not to, and the four Windows-only test assumptions the leg exposed).
R-16 gets **no bullet**: it was closed by the 2.1.5 docs work this plan merely
records. R-17 goes under **Changed** (the suite runs once, on the floor, so a
push projects 68.7 billable minutes instead of 168.0; the artifact and
documentation steps moved to that leg, and a new cost lock prices every job
against a 100-minute budget).

---

## 8. Risks and rollback

| Risk | Mitigation | Rollback |
|---|---|---|
| Making the audit blocking reds `main` the day an advisory is published against a dependency nobody can upgrade yet. | The allowlist is the escape valve, with a reason and an expiry; the checker's message names the id, the fix versions and where to record the entry. | Restoring `continue-on-error` is legitimate if it is a recorded decision row in this plan — never a silent revert. The lock fails on a silent revert, because it asserts the flag is absent. |
| The `posix-smoke` leg's first run fails on real POSIX defects, or worse, passes because it collected almost nothing. | The selection is declared and locked; the job asserts a passed count and prints the display summary; skips are bounded and pinned. | Narrow the selection or remove the job **in the same change** that restores the caveat. A job removed while the caveat still claims it is the exact defect R-12 exists to remove. |
| `target-version = "py311"` surfaces more than the 12 measured findings, or `mypy` at 3.11 more than the 1. | Both were measured before the plan was written, so the size is known; anything further is fixed in the change or recorded here as a decision, never ignored. | Revert the target alone and record why — but the lock in `tests/test_tooling_targets.py` then has to be changed deliberately, which is the point. |
| The floor environment resolves different numpy/scipy legs below 3.12 than the 3.14 host does. | X1 names it; the acceptance evidence is the 3.11 leg's verdict, not the local proxy. | None needed: this is a measurement limitation, not a defect. |
| R-17's single leg lets a 3.12- or 3.14-only regression reach `main` without a runner verdict, since neither interpreter runs the suite in CI any more. | The floor leg keeps the full suite, the mandatory local gate runs 3.14 before anything is called done, and X10 names the three ways to buy the leg back; the ledger prices a second leg at 125.2 minutes, so it is a decision with a number, not an oversight. | Restore the leg and record it in the ledger with its measured cost — the lock makes that a deliberate edit rather than a quiet one. If a 3.14-only defect escapes, the fix is `pytest-xdist` (to make two legs fit the budget), not a wider budget. |
| An allowlist entry is added to silence an advisory instead of fixing it. | Entries expire, staling is a failure, and the weekly run makes an expired entry red on a day nobody committed. | Remove the entry and upgrade, or renew it with a new reason and date — the renewal is a visible diff in review. |
