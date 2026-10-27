# PLAN — Audit 2026-10-24 deferred register (P2/P3): CI policy, a POSIX leg, tooling targets, docs truth

**Status:** `[~]` in progress — drafted 2026-10-27. **R-15 is complete and
runner-verified** (record in §5): the code commit `5298301` (run `40563584800`)
and this plan's own record commit `61a19dd` (run `40568799837`) are each **green
in all nine jobs**, `Type Check` and `Lint & Format` included, after the first
push's `Type Check` failure was fixed; R-16's verification row is written, R-11
and R-12 are open.
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
count). Nothing else.
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
| D17 | `[tool.bandit] exclude_dirs` gains `"packaging"`, and the entries are asserted **narrow** by a lock. | DECIDED | The security gate walks `.`, so with the installer built the documented command reported **3 690 HIGH** findings drawn from CPython's own stdlib inside the staged runtime — the gate could not pass in a state a normal developer reaches, while CI (which never builds the installer) stayed green. Bandit matches each entry as a path **substring**, which is why the entry is asserted by its consequence: a new `tests/test_tooling_targets.py` class scans the tree for a production module whose path matches any entry and fails if one exists, so widening an entry into a silent blind spot is red, not allowed. Nothing is lost today: `packaging/` ships no `.py` file (its inputs are `.iss`, `.ps1` and `.md`), and `packaging` appears in no other tracked path. The exclusion also prunes the walk: the gate went from minutes to **11 s**. |

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

---

## 4. Traceability

| Finding | Sev | Item | Acceptance evidence (audit §9.1) | Release |
|---|---|---|---|---|
| R-11 — dependency audit non-blocking | P2 | §3 R-11 | CI failure on a new advisory | 2.1.7 |
| R-12 — POSIX untested | P2 | §3 R-12 | green Ubuntu CLI/shared smoke run | 2.1.7 |
| R-15 — Ruff/mypy targets below floor | P2 | §3 R-15 | 3.11 typecheck leg green | 2.1.6 |
| R-16 — README count stale | P3 | §3 R-16 | README assertion matches `len(first_party())` | none (closed in 2.1.5) |

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

**The tip is green as well — run `40568799837` at `61a19dd`.** That is the
documentation-only commit carrying this record, pushed after the one above, and
it completed `success` at 19:54:11Z with all nine jobs green. The `Test` legs
finished last (3.14 23:19, 3.12 27:06, 3.11 27:14) and each reported the same
**11 154 passed, 6 skipped, 35 deselected** at 90.87–90.88 % coverage;
`Type Check` and `Lint & Format` were green again in 42 s and 20 s. Two
consecutive runs of this window are therefore green with the floor leg in them,
so the state is a property of the commits rather than of one lucky run.

**Where the chasing stops, said out loud.** The paragraph above is itself a
documentation-only commit, and *its* run is not awaited — recording the record
would otherwise move the subject every time it is written. What this record
establishes is concrete and two-part: `5298301` (code, run `40563584800`) and
`61a19dd` (this record, run `40568799837`) are both green in all nine jobs. The
next *code* change is the next thing whose run belongs here.

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
it). R-16 gets **no bullet**: it was closed by the 2.1.5 docs work this plan
merely records.

---

## 8. Risks and rollback

| Risk | Mitigation | Rollback |
|---|---|---|
| Making the audit blocking reds `main` the day an advisory is published against a dependency nobody can upgrade yet. | The allowlist is the escape valve, with a reason and an expiry; the checker's message names the id, the fix versions and where to record the entry. | Restoring `continue-on-error` is legitimate if it is a recorded decision row in this plan — never a silent revert. The lock fails on a silent revert, because it asserts the flag is absent. |
| The `posix-smoke` leg's first run fails on real POSIX defects, or worse, passes because it collected almost nothing. | The selection is declared and locked; the job asserts a passed count and prints the display summary; skips are bounded and pinned. | Narrow the selection or remove the job **in the same change** that restores the caveat. A job removed while the caveat still claims it is the exact defect R-12 exists to remove. |
| `target-version = "py311"` surfaces more than the 12 measured findings, or `mypy` at 3.11 more than the 1. | Both were measured before the plan was written, so the size is known; anything further is fixed in the change or recorded here as a decision, never ignored. | Revert the target alone and record why — but the lock in `tests/test_tooling_targets.py` then has to be changed deliberately, which is the point. |
| The floor environment resolves different numpy/scipy legs below 3.12 than the 3.14 host does. | X1 names it; the acceptance evidence is the 3.11 leg's verdict, not the local proxy. | None needed: this is a measurement limitation, not a defect. |
| An allowlist entry is added to silence an advisory instead of fixing it. | Entries expire, staling is a failure, and the weekly run makes an expired entry red on a day nobody committed. | Remove the entry and upgrade, or renew it with a new reason and date — the renewal is a visible diff in review. |
