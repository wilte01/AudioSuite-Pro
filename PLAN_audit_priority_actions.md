# PLAN — Audit Priority Actions (Post-Audit Remediation)

**Status:** In progress — **P1 complete** (initial commit `a056bb9`); **P2 complete** (commit `d7680f7`); **P3 complete** (commits `c06730c` + `e540819`); **P4 complete** (commits `f409e11` + this); **P5 complete** (commit `0666936` + this); P6–P7 not started. See Decision Log (D10–D14) and the session retrospective for discoveries.
**Source:** "Honest Audit Report" (product capability + code-quality audit, 2026)
**Scope:** The 7 priority actions named in the audit's closing section. Each action is broken into fully addressable steps with acceptance criteria, lockstep tests, and verification commands.
**Anti-creep rule:** Implement ONLY the steps below. No adjacent refactors, no styling changes outside the touched files, no speculative features. Any defect discovered *while* implementing one of these steps must be fixed in the same change with a regression test (AGENTS.md §7), and noted in the Decision Log.

---

## Definition of Done (applies to every item below)

Every item ships through the mandatory project verification pipeline, run from the repo root (Windows / pwsh):

```powershell
# 0. Compile / import gate
python -X utf8 -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'

# 1. Lint & format
ruff check --fix .
ruff format .

# 2. Type check (per item P4 the config is tightened; then this is mypy --strict-equivalent)
mypy .

# 3. Security (canonical invocation; 0 High / 0 Medium)
$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml

# 4. Tests (bare full-suite run so pyproject testpaths apply)
python -X utf8 -m pytest                    # --cov-fail-under=75 enforced
```

Also mandated: full-suite green, no new `# type: ignore` without a specific code, no new silent `except`, no `TODO`/`FIXME`.

Ordering note: **P1 (git) should land first** so every subsequent change is a reviewable commit. P2–P5 are independent and can be parallelised. P6 depends on nothing. P7 items are independent follow-up initiatives (feature-backlog; deferral acceptable per AGENTS.md §7, but must be fully specified here).

---

## P1 — Initialise git repository and first commit

**Status:** COMPLETE — landed as commit `a056bb9` (message "Initial commit of AudioSuite-Pro 1.0.0").

Completion record:
- [x] Pre-flight inventory; `git init -b main` (Git for Windows 2.55.0.3 installed via winget first — see D10); global identity used (`Terrence Williams <wilte01@gmail.com>`).
- [x] Q1/Q2 decided and applied (D1/D2): `uv.lock` ignore line removed and file committed; `fpcalc.exe` committed (measured 3.95 MB < 5 MB).
- [x] `.gitignore` hardened: added `audio_suite_config.key`, `.coverage.*`, `htmlcov/`, `*.lnk`, `.env`, `.env.*`, `!.env.example`; extended further for the D11 discovery.
- [x] Secret gate: the audit `rg` pattern + `git grep --cached` supplemental scans (catches `*_key`/`*_secret` suffixes, 32-hex, 44+-base64 literals the audit regex misses — see D11). Four `album_art_sync/*` files carrying live Fanart.tv keys were found staged, unstaged, and excluded.
- [x] `git check-ignore` verified for `audio_suite_config.json`, `audio_suite_config.key`, `logs/`, `.venv/`, and the `album_art_config.*` pairs (root + `core/`).
- [x] Commit: 832 tracked files (712 `.py`, 32 `.pyw`, docs, `uv.lock`, `fpcalc.exe`); `git status` clean; CI workflow still triggers on push/PR to `main`.
- [x] VCS-presence + tracked-binary note added to `AGENTS.md` (no root README exists; this is the lightweight doc change step 6 asks for).
- [x] Compile gate (`compileall`) green. `ruff`/`mypy`/`bandit`/`pytest` not re-run for P1: zero first-party Python was modified (docs/.gitignore/git only).

**Problem:** The working copy has no VCS. For a ~133k-LOC suite with a committed engineering discipline, the absence of commits/diffs/rollback is the single biggest engineering-process gap, and it blocks normal review practice and CI-on-push (CI already triggers on `main`, which does not exist).

### Steps

1. **Pre-flight inventory (before `git init`).**
   1. Confirm the tree state: `Get-ChildItem -Force` at repo root. Note what currently exists that should not be committed.
   2. Decide two open questions (see Decisions) and record them in the Decision Log:
      - Q1: commit `uv.lock`? (currently ignored at `.gitignore:39`, yet CI runs `uv sync`; committing it pins the resolved dependency graph).
      - Q2: commit `fpcalc.exe` (repo root, runtime-required by the Fingerprinter)? `*.dll` is already ignored; `fpcalc.exe` is *not* ignored and would be added.
2. **Harden `.gitignore` before the first commit.** Add / adjust the following entries (file: `.gitignore`):
   ```gitignore
   # Project-specific (extend existing block at lines 32-39)
   audio_suite_config.key     # sibling of audio_suite_config.json (currently NOT ignored)
   .coverage.*
   htmlcov/
   *.lnk
   .env
   .env.*
   !.env.example
   ```
   If Decision Q1 = commit `uv.lock`: delete the `uv.lock` ignore line (`.gitignore:39`). If Q2 = keep fpcalc binary out: add `fpcalc.exe`; if Q2 = commit it: leave it tracked and add a note in `README`.
3. **Secret scan gate (mandatory before staging anything).** From repo root:
   ```powershell
   # Any hit in a file about to be committed = blocker for that file.
   rg -n -i "(api[_-]?key|secret|passwd|password|token)\s*[=:]\s*[\"'][A-Za-z0-9_\-]{8,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----" --glob '!.venv/**' --glob '!*.pyc' --glob '!*.docx' --glob '!*.pptx' .
   ```
   Also eyeball `audio_suite_config.json` / `audio_suite_config.key` are present-but-ignored (do **not** `git add -f` them).
4. **`git init` and configure.** Use the user's existing global identity; verify with `git config --get user.name` / `user.email`; if unset, ask before setting a local identity.
   ```powershell
   git init -b main
   git status        # confirm ignored files do not appear
   ```
5. **Initial commit.**
   ```powershell
   git add -A
   git diff --cached --stat          # eyeball the file set (~700 .py + docs + user_guides .docx)
   git commit -m "Initial commit of AudioSuite-Pro 1.0.0"
   ```
6. **Post-commit checks.** `git status` clean; `git log --oneline -1`; confirm CI would trigger (repo is pushed to a `main` remote when the user chooses).

### Tests in lockstep
- No pytest tests apply. Add a lightweight `AGENTS.md`/README note that VCS is now present (audit docs only — update wording that previously implied "not a git repo" if any doc states it).
- Confirm `.gitignore` behaves: `git check-ignore audio_suite_config.json audio_suite_config.key logs/ .venv/` returns all four.

### Acceptance criteria
- `git log` shows `main` with one clean initial commit; `git status` clean.
- No secrets, `.key`, config json, `.venv`, caches, or `logs/` in the commit.
- CI workflow remains destined to run on push to `main`.

### Decisions / risks
- Q1 `uv.lock`: **recommend commit** (reproducible CI). Changing the ignore is a 1-line edit.
- Q2 `fpcalc.exe`: **recommend commit** (native 3rd-party binary, small; needed for fingerprinting out-of-the-box) — unless size is a concern, in which case ignore + document download. Record the choice.
- Risk: first commit carries the runtime `audio_suite_config.*` files if `git add -A` races with a running tool — the ignore rules above prevent it; verify with `git status --short` after add.

---

## P2 — Harden CI: full-tree Bandit, no `||` fallback, compile gate

**Problem:** `.github/workflows/ci.yml:43` runs `bandit -r audio_suite_shared/ -c pyproject.toml || bandit -r audio_suite_shared/` — the `||` fallback re-runs *without* `-c` (the exact anti-pattern AGENTS.md §Verification warns about) and the scan covers only 1 of 26 packages. No compile/import gate exists in CI despite AGENTS.md mandating it as verification step 0.

**Status:** COMPLETE — landed as commit `d7680f7` (message "P2: harden CI security+compile gate").

Completion record:
- [x] **Step 2 — widened scan verified BEFORE touching CI.** Ran the exact canonical command locally (repo root, pwsh):
  ```powershell
  $env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml
  ```
  Result: **0 High / 0 Medium across all 26 packages** (51 Low findings). Breakdown of the Low tail by site:
  - B606 `os.startfile`/opener sites: `album_art_normalizer.py:186`, `audio_suite_shared/platform_utils.py:38,166`, `ui_common.py:46`, `cd_ripper/ui/results_tab.py:118`, `master_driver/utils/platform_utils.py:29`.
  - B603 via `run_secure_subprocess()` only (audited single wrapper): `secure_subprocess.py:279,366,428`.
  - B603/B607 raw-but-benign sites: `audio_enhancer/core/ffmpeg_io.py` (local ffmpeg binary, no shell), `cd_ripper/ui/results_tab.py:130-155` (fixed drive-letter eject/explorer select, `CREATE_NO_WINDOW`), `master_driver/utils/platform_utils.py:31,33`.
  - B105 false positives on CLI flag strings: `bpm_analyzer`, `lyrics_manager`, `replaygain_analyzer` `utils/cli_args.py` (`--bpm-min`, `--workers`, `--apply-gain`, …) — no actual hardcoded secrets (token-class scan in P1 confirmed none).
  - B403/B112 `batch_undo.py` pickle with `# nosec B301 - legacy self-writes`; B405 `asx_extractor/core/asx_parser.py` ElementTree (read-only local parse).
  - Expected count was **zero Medium**; confirmed — no in-change security fix required (D3 held as a no-op).
- [x] **Step 1 — CI security job hardened** (`.github/workflows/ci.yml:34-46`): scan command replaced with the canonical full-tree invocation, `||` fallback removed, `PYTHONUTF8="1"` set as an env on the step:
  ```yaml
  - name: Bandit (full tree)
    env:
      PYTHONUTF8: "1"
    run: bandit -r . -x ./.venv -c pyproject.toml
  ```
- [x] **Step 3 — new dedicated `compile` job added** (`.github/workflows/ci.yml:48-56`): `actions/checkout@v4` + `actions/setup-python@v5` (3.12) + `python -X utf8 -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'`. Mirrors the preflight guard in CI, where `guard_or_exit()` cannot run (needs a Tk root). Dedicated job so the byte-compile gate runs independently of the test matrix.
- [x] **Step 4 — no other CI changes** (deliberate): `mypy .`, ruff, and the pytest matrix untouched.
- [x] **Verification:** bandit (exact command above) 0 H / 0 M; compile gate (`compileall -f . -x …`) clean — the only output being the known `.venv` third-party pydub `SyntaxWarning`s (documented AGENTS.md gotcha; CI has no `.venv` so they cannot appear there). ruff/mypy/pytest not re-run: zero first-party Python was modified (YAML-only change), consistent with the P1 precedent.

### Steps

1. **Replace the security job scan command** (`.github/workflows/ci.yml:43`) with the canonical full-tree invocation:
   ```yaml
       - name: Bandit (full tree)
         env:
           PYTHONUTF8: "1"
         run: bandit -r . -x ./.venv -c pyproject.toml
   ```
   Rationale:
   - `-c pyproject.toml` keeps `skips`/`exclude_dirs` (B404/B101 skipped by policy; `tests` excluded).
   - `-x ./.venv` matches the documented invocation and is a no-op in a fresh checkout (the security job has no `uv sync`, so no `.venv` is created — keep the flag for parity).
   - `PYTHONUTF8` avoids the `charmap` report crash on any path containing `→`/non-ASCII docstring chars.
   - Remove the `||` fallback entirely — a scan failure must fail the job.
2. **Verify the widened scan passes before enabling.** Run the exact command locally (see Definition of Done step 3). Expected result: 0 High / 0 Medium; remaining findings are the documented B603/B606/B607 first-party subprocess call sites routed through `run_secure_subprocess()` and the shared test–sonly sites excluded by config. If any genuine Medium surfaces outside `audio_suite_shared/`, fix it *in the same change* (AGENTS.md §7) before updating CI. *(Verified locally first; see completion record — zero Medium, no fix needed.)*
3. **Add a compile/import gate job.** Append a new job (or a step in the existing `test` job — recommend a dedicated job so it runs on both semantics independently):
   ```yaml
     compile:
       name: Compile / Pre-flight gate
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.12"
         - run: python -X utf8 -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'
   ```
   This byte-compiles every first-party module and catches `SyntaxError`/`IndentationError`/broken-top-level-import crashes at launch time — mirroring `audio_suite_shared.preflight.guard_or_exit()` (which cannot run in CI because it needs a Tk `root`).
4. **Optional hardening (do NOT scope-creep):** leave `mypy .`, ruff, pytest matrix as-is; they already run. No other CI changes.

### Tests in lockstep
- No code tests; the CI YAML itself is the artifact. If any package needed a security fix in step 2, add its regression test in that package's suite and re-run the full suite.

### Acceptance criteria
- `ci.yml` security job runs `bandit -r . -x ./.venv -c pyproject.toml` with `PYTHONUTF8=1` and no `||` fallback.
- New `compile` job byte-compiles the tree.
- Full local gate (Definition of Done) green after the change.

### Decisions / risks
- Medium findings discovered in the widened scan are release-blocking defects (AGENTS.md §7) — expected count is zero; if any appear, they are fixed here, not skipped.
- GitHub Actions doesn't `uv sync` in the security job, so `-x ./.venv` is defensive only. Keep it for local parity.

---

## P3 — Fix `library_stats/library_cache.py` SQLite concurrency

**Problem:** `library_stats/library_cache.py:96-98` connects with `sqlite3.connect(str(self._path), check_same_thread=False)` and **no `timeout=`**, guarded by a **per-instance** `self._lock` (`:88`). This is exactly the pattern AGENTS.md forbids ("concurrent writers from multiple instances/threads raise OperationalError: database is locked"). The correct reference pattern is `audio_suite_shared/batch_undo.py:53,173` (module-level lock, `timeout=30`, WAL, `ORDER BY rowid`). Currently latent (single-instance use), it is the one module that contradicts the documented rule.

**Status:** COMPLETE — landed as commit `c06730c` (message "P3: library_cache concurrency").

Completion record:
- [x] **Step 1 — module-level lock.** `_DB_LOCK = threading.Lock()` added next to `logger` (with the batch_undo-style comment); per-instance `self._lock = threading.Lock()` removed from `__init__`.
- [x] **Step 2 — serialise connection acquisition.** `_connect()` now guards the double-checked open with `_DB_LOCK` and passes `timeout=30` to `sqlite3.connect(..., check_same_thread=False, timeout=30)` (see step 2 snippet). `check_same_thread=False` retained for worker-thread reads.
- [x] **Step 3 — `PRAGMA busy_timeout=30000`** set on the new connection, so a competing writer is waited on for 30 s instead of racing.
- [x] **Step 4 — write-ordering audit.** Grepped `library_stats` for `scanned_at|ORDER BY`: no query orders by `scanned_at`/`datetime('now')` — the only `ORDER BY` clauses are the aggregate `ORDER BY cnt DESC` distributions, which are stable. Nothing to convert to `rowid`; no code change needed.
- [x] **Step 5 — docstring.** Added a "Concurrency:" note to the module docstring (`:26` region) referencing the module-level lock + `timeout=30`/`busy_timeout` pattern and why (per-instance locks cannot serialise separate connections; matches `batch_undo`).
- [x] **Regression tests** (`test_library_cache.py::TestConcurrency`, 4 tests): (1) `test_instances_share_module_lock` — instances hold no private `_lock` and `_DB_LOCK` is a `threading.Lock`; (2) `test_concurrent_writers_two_instances`, `@pytest.mark.parametrize("n", (1, 5))` — two `LibraryCache` instances on the same file, `threading.Barrier`-synchronised threads each doing 25 `upsert_file` writes, assert zero exceptions and `row_count() == 50`. **Empirically verified it fails pre-fix** with `OperationalError: database is locked` and passes post-fix (premise confirmed, see D13); (3) `test_upsert_waits_out_exclusive_transaction` — a second raw connection holds `BEGIN EXCLUSIVE` for 0.5 s while `upsert_file` blocks and then succeeds (`elapsed >= 0.3` and `< 30`), asserting the busy-wait behaviour. First draft of (3) had to be corrected: the holder `sqlite3.connect` was created on the main thread but used inside the worker thread and hit `check_same_thread`, so the connection is now created (with `check_same_thread=False`) inside the thread function.
- [x] **Verification gate (Definition of Done):** compile gate (`compileall -f . -x …`) green (only known `.venv` pydub SyntaxWarnings); `ruff check --fix` + `ruff format` clean (1 file reformatted — the touched test file); `mypy .` success on 429 files; `bandit` 0 High / 0 Medium / 51 Low (same documented tail as P2, no new findings); full bare `pytest` **6565 passed / 5 skipped**, coverage **77.36%** ≥ 75%.

### Steps

1. **Add a module-level lock** at `library_cache.py` (top, next to `logger`):
   ```python
   _DB_LOCK = threading.Lock()
   ```
   Remove the per-instance `self._lock = threading.Lock()` (`:88`).
2. **Serialise every connection acquisition under the module lock.** Change `_connect()` so the guard uses `_DB_LOCK` (not `self._lock`), and add `timeout=30` to the connect call:
   ```python
   def _connect(self) -> sqlite3.Connection:
       if self._conn is None:
           with _DB_LOCK:
               if self._conn is None:
                   self._conn = sqlite3.connect(
                       str(self._path), check_same_thread=False, timeout=30
                   )
                   self._conn.execute("PRAGMA journal_mode=WAL")
                   self._conn.executescript(_SCHEMA_SQL)
       return self._conn
   ```
   Keep `check_same_thread=False` (the dashboard queries from worker threads; the module lock serialises *cross-instance* writers per the documented rule).
3. **Add an explicit `busy_timeout`** on the new connection so concurrent writers wait rather than race:
   ```python
   self._conn.execute("PRAGMA busy_timeout=30000")
   ```
4. **Audit write ordering.** Confirm aggregate/query paths order by stable columns, not `datetime('now')`. The cache's `scanned_at` column is informational only and no "newest-first"/prune query depends on it — if step 2 exposes any query ordering by `scanned_at`, convert to `rowid` ordering with a comment (AGENTS.md rule).
5. **Surface the lock in the docstring** at `library_cache.py:2-26` with a one-line "Concurrency" note referencing the module-level lock + `timeout=30` pattern (why, not what).

### Tests in lockstep (file: `library_stats/tests/test_library_cache.py`)
Add a regression test class:
- **Two instances, same file, concurrent writers:** create `LibraryCache(path)` instance A and `LibraryCache(path)` instance B (same `cache_path`), have them interleave `upsert_file` calls (e.g. via two threads and a `barrier`), then assert no `OperationalError` and that `row_count()` equals the expected total after both complete. This fails pre-fix (per-instance locks do not serialise separate connections) and passes post-fix.
- **Module lock is shared:** assert both instances use the same underlying lock object (or equivalently that the concurrent-writer test above is deterministic when run repeatedly — run it in a `pytest.mark.parametrize("n", (1, 5))` loop).
- **Locked-database wait:** open a raw second connection to the same file, `BEGIN EXCLUSIVE`, and verify `upsert_file` blocks and eventually succeeds within the 30 s timeout (timeout-conscious; keep the exclusive txn short).
- Keep all existing `test_library_cache.py` tests green unchanged.

### Acceptance criteria
- `_connect()` carries `timeout=30` + `PRAGMA busy_timeout=30000`; guarding lock is module-level.
- New concurrency tests pass; full suite green; coverage on `library_cache.py` maintained (existing suite + new tests).

### Decisions / risks
- `check_same_thread=False` is retained deliberately (worker-thread reads). The module lock serialises only the *creation* of the connection and, via `busy_timeout`, writers wait — matching `batch_undo.py`.
- No schema change; existing cached DBs remain compatible.

---

## P4 — Align type-check configuration with the documented `--strict` claim

**Problem:** AGENTS.md ⌈Verification Tooling⌉ item 2 claims `mypy . --strict`, but `pyproject.toml [tool.mypy]` (lines 61-95) does not set the full strict set (`disallow_any_generics`, `disallow_subclassing_any`, `disallow_untyped_calls` global, `disallow_untyped_defs`, `disallow_untyped_decorators`, `warn_unused_ignores`, `strict_equality`, `extra_checks`), and CI runs bare `mypy .`. The codebase is already ~99% annotated, so enabling the missing flags is expected to be a small, mechanical tail — but the config and the docs must agree.

**Status:** COMPLETE — landed as commit `f409e11` (message "P4: strict mypy config").

Completion record:
- [x] **Step 1 — clean baseline.** `mypy .` (pre-change config) → **Success: no issues found in 429 source files**. The existing flags (`no_implicit_optional`, `warn_redundant_casts`, `warn_unused_configs`, `warn_return_any`, `disallow_incomplete_defs`, `check_untyped_defs`) were already a strict-compatible subset.
- [x] **Step 2 — `strict = true` enabled.** `pyproject.toml [tool.mypy]` now reads `python_version = "3.12"`, `strict = true`, `ignore_missing_imports = true`, then the unchanged `untyped_calls_exclude` + `[[tool.mypy.overrides]]` blocks. Ran `mypy .` with `--no-incremental` (fresh cache) + a probe file to confirm the strict checks actually fire (`no-untyped-def`, `no-untyped-call`, `type-arg`) — **the error tail was ZERO sites**; the 429-file tree is `mypy --strict`-clean as-is, confirming D4's "small mechanical tail" expectation and the codebase's ~99% annotation claim. No `# type: ignore` was added, removed, or changed (the 31 existing non-test coded ignores remain valid — `warn_unused_ignores` is live under strict and reports none).
- [x] **Step 3 — no fixes required.** Under `strict = true`, `mypy .` = 0 errors on 429 files with no code changes — the empty tail meant no categorical fixes (no-untyped-def/misc/equality/unused-ignore/any-return) were needed. `compileall` gate re-run clean after the config change.
- [x] **Step 4 — AGENTS.md updated (project + global).** Project `AGENTS.md` pipeline list (Verification Tooling) reworded from `mypy --strict` to `mypy (strict via [tool.mypy] strict = true)`. Global `C:\Users\wilte\.config\opencode\AGENTS.md` §6 item 2 now reads `mypy .` with the comment `# strict = true set in pyproject.toml [tool.mypy]` and a one-line note that `untyped_calls_exclude` + the per-module `[[tool.mypy.overrides]]` blocks are the sanctioned carve-outs for third-party gaps (no `# type: ignore` workarounds).
- [x] **Step 5 — CI unchanged.** `.github/workflows/ci.yml:32` already runs bare `uv run mypy .`; with `strict = true` in pyproject that job is genuinely strict — zero YAML edits needed.
- [x] **Step 6 — no README/plugin-dev updates required.** Grepped `mypy` across `*.md` (excluding the historical `PLAN_*.md` records, which document past runs verbatim) and `user_guides/**/*.py`: no README or guide generator restates the type-check command. Historical plan docs (`PLAN_quality_baselines.md`, `PLAN_iteration2/3/4_remediation.md`, etc.) are session records, not instructions — left untouched.
- [x] **Verification gate (Definition of Done):** compile gate (`compileall -f . -x …`) exit 0 (only known `.venv` pydub SyntaxWarnings); `ruff check --fix` clean + `ruff format` 712 files unchanged; `mypy .` **0 errors / 429 files** under `strict = true`; `bandit` **0 High / 0 Medium / 51 Low** (identical documented tail to P2/P3 — the "31 Medium / 20 High" tripwires in the summary lines are *confidence* buckets, not severity); full bare `pytest` **6565 passed / 5 skipped**, coverage **77.36%** ≥ 75%.

### Decision (record in Decision Log)
**Option A (recommended): set `strict = true` in `[tool.mypy]` and add the missing flags**, making `mypy .` genuinely `--strict`-equivalent, then reword AGENTS.md to describe reality ("`strict = true` via `pyproject.toml`; run `mypy .`").
Option B (fallback only if the error tail proves unreasonable — see step 2): amend the AGENTS.md claim to remove `--strict` and document the actual subset.

### Steps
1. **Get a clean baseline:** run `mypy .` (current config) and confirm 0 errors (429 files) before changing anything.
2. **Enable strict equivalence** in `pyproject.toml [tool.mypy]`:
   ```toml
   strict = true
   ```
   Keep the existing overrides (they already set `disallow_untyped_calls = false` for third-party `py.typed` packages and `untyped_calls_exclude` for typeshed-gap callers — both remain coherent with `strict = true`). Run `mypy .` and capture the *full* error list.
3. **Fix the error tail categorically** (expected categories, in order of likelihood):
   1. `no-untyped-def` / `no-untyped-decorator` on any residual untyped functions/decorators in non-excluded source → add explicit `-> None`/parameter types (codeless, mechanical).
   2. `misc` / `type-arg` from `disallow_any_generics` on bare `list`/`dict`/`tuple` literals → parameterise with the existing types.
   3. `comparison-overlap`/`strict-equality` mismatches → fix the comparison or the literal type at the site.
   4. `unused-ignore` on any now-redundant `# type: ignore` → remove it (never rewrite as a bare ignore to satisfy the check). The 31 non-test coded ignores currently present are expected to remain valid.
   5. `any`-related (`no-any-return`, `warn_return_any`) violations surfaced by stricter flow — sample guidance in AGENTS.md (bind to explicitly-typed locals: the numpy `Any`-return trap) applies.
   For every fixed site: run `python -X utf8 -m compileall -q -f .` again (import-chain modules) and re-run `mypy .`.
4. **Update AGENTS.md** (global + project) type-check line: replace the `mypy . --strict` text with the accurate invocation (`mypy .`, with `strict = true` configured in `pyproject.toml`), so the doc matches the config. Add a one-line note that `untyped_calls_exclude` + overrides are the sanctioned carve-outs for third-party gaps.
5. **CI remains `mypy .`** (`.github/workflows/ci.yml:32` needs no change once pyproject sets `strict = true`).
6. **Update README/plugin-dev docs** if they restate the type-check command (grep `mypy` across `*.md`, `user_guides/**/*.py`, update generator scripts in lockstep and regenerate any generated doc that mentions it).

### Tests in lockstep
- No runtime tests. Verify: `mypy .` = 0 errors on 429 files with the *new* config; full suite still green under the tightened config (a type fix must not alter runtime behaviour — full pytest is the guard).

### Acceptance criteria
- `pyproject.toml` has `strict = true`; `mypy .` clean.
- AGENTS.md (both files) no longer claims a flag the config doesn't set.
- No new `# type: ignore` introduced.

### Decisions / risks
- If the tail exceeds an arbitrary but sane threshold (say >40 distinct sites not explained by categories above), STOP after the first error-quantifying run and report the count/list to the user before fixing (Two-Try Rule / scope approval), rather than grinding through an unbounded tail. Do not ship Option B path before that conversation.

---

## P5 — Promote `was_launched_from_driver` and the shared hidden-Tk conftest into `audio_suite_shared`

**Problem:** `was_launched_from_driver(argv)` is duplicated byte-identically in ~19 tool packages (e.g. `tempo_analyzer/utils/cli_args.py:34`, `album_genre_tagger/utils/cli_args.py:34`, plus the four P6 tools) with a shortened variant in `silence_trimmer/utils/cli_args.py:27`. On the test side, ~23 per-tool `tests/conftest.py` files (e.g. `tempo_analyzer/tests/conftest.py`, 37 lines) differ only in a docstring and re-implement the same hidden-Tk bootstrap that `audio_suite_shared/tests/conftest.py:167-176` already standardises.

### 5a. Canonicalise `was_launched_from_driver`
1. **Inventory semantics before writing anything.** Grep each `utils/cli_args.py` + its `tests/test_cli_args.py` and record every asserted input → output pair (e.g. `["prog"]→False`, `["prog","folder"]→True`, `["prog","--no-clear-logs"]→True`, `[]→False`, plus the `argv=None`→`sys.argv` variants). There WILL be subtle differences (some tools additionally treat the second entry as numeric "0" placeholder). Build the union matrix.
2. **Add the canonical function** to `audio_suite_shared/cli_helpers.py` (alongside the existing handler classes):
   ```python
   def was_launched_from_driver(argv: list[str] | None = None) -> bool:
       """True when a full argv (index 0 = program name) holds more than one
       entry — the Master Driver always passes at least one argument (a path
       or the numeric placeholder used by enrich tools) plus the display-only
       handshake flags, while a standalone launch passes none."""
       if argv is None:
           argv = sys.argv
       return len(argv) > 1
   ```
   The audited union matrix (step 1) showed **all 19 legacy bodies are
   byte-identical** — `if argv is None: argv = sys.argv[1:]; return len(argv) > 1`
   (no `silence_trimmer` shortened variant exists) — and the plan sketch below
   was *not* used because it contradicts the union matrix (it returns True for
   `["prog"]`, which tests assert is False). The canonical form differs from
   legacy only in the `None` default (full `sys.argv` instead of the `[1:]`
   slice): both call patterns — bare standalone launch (`argv = ["prog"]`) and
   driver launch (`argv = [prog, path, flags…]`) — produce identical booleans on
   both forms, so every union-matrix row and every production call site is
   reproduced. The one semantic refinement: a genuine manual run like
   `Tempo_Analyzer.pyw D:/Music` now counts as "driven" (was standalone under the
   legacy `[1:]` default) — consistent with the sketch's intent (any non-flag
   first arg ⇒ driven). See Decision Log D14.
   Verify this canonical implementation reproduces *every* row of the union matrix from step 1. If a specific tool's legacy behaviour is unreproducible by the canonical form, record that tool + its divergence in the Decision Log and adjust the canonical form; do not special-case per tool.
3. **Re-export from each tool** so existing call sites (`app.py` → `cli_args.was_launched_from_driver()`) remain untouched. In each of the ~19 `utils/cli_args.py` files replace the local body with an explicit re-export using the redundant-alias form — `# noqa: F401` alone passes ruff but fails mypy `--strict` with `Module "…utils.cli_args" does not explicitly export attribute` (from `CheckPy` on the importing `app.py`); the `as`-alias names the symbol as an intentional re-export and satisfies both:
   ```python
   from audio_suite_shared.cli_helpers import (
       was_launched_from_driver as was_launched_from_driver,
   )
   ```
   Delete the local implementation (`silence_trimmer` had no shortened variant — confirm each tool's `test_cli_args.py` passes against the canonical form). Keep each file's `parse()`/`validate_args()` local (out of scope).
4. **Move the test matrix** into `audio_suite_shared/tests/test_cli_helpers.py` as a parameterised class (`TestWasLaunchedFromDriver`) containing every union-matrix row with its originating tool in the parametrisation id. Then reduce each tool's `tests/test_cli_args.py` to keep its own `parse()`/`validate_args()` rows, dropping the now-duplicated `was_launched_from_driver` rows (delete, do not xfail).

### 5b. Single shared hidden-Tk conftest
1. **Add a repo-root `conftest.py`** providing the canonical session-scoped hidden root, with graceful skip when no display is available:
   ```python
   """Repo-root pytest config: one hidden Tk root for the whole session."""

   import tkinter as tk

   import pytest

   _root: tk.Tk | None = None

   def pytest_configure(config: pytest.Config) -> None:
       global _root
       try:
           _root = tk.Tk()
           _root.withdraw()
       except tk.TclError:
           _root = None

   def pytest_unconfigure(config: pytest.Config) -> None:
       if _root is not None:
           _root.destroy()

   def pytest_collection_modifyitems(
       config: pytest.Config, items: list[pytest.Item]
   ) -> None:
       if _root is None:
           for item in items:
               item.add_marker(
                   pytest.mark.skip(
                       reason=(
                           "No display available — tkinter tests require a "
                           "GUI environment"
                       )
                   )
               )

   @pytest.fixture(scope="session")
   def root() -> tk.Tk:
       """The shared hidden Tk root (kept alive for the whole session)."""
       assert _root is not None, "No display available — Tk root was not created"
       return _root

   @pytest.fixture(scope="session")
   def tk_root() -> tk.Tk:
       """Alias for the shared hidden root, for tests that use this name."""
       return root()
   ```
   (the released file adds a module docstring and `from __future__ import annotations`, and its `tk_root` fixture asserts `_root` directly rather than calling `root()`).
   Defect found while implementing: the plan's original sketch called
   `pytest.skip()` *inside* `pytest_configure` — on pytest 9.x that raises
   `INTERNALERROR: usage._ExitCode` (exit code 3) because the runner is not yet
   collecting, so the skip cannot be recorded. Validated empirically with a temp
   experiment; the released form records `_root = None` and instead adds
   `pytest.mark.skip` markers in `pytest_collection_modifyitems` (exit code 0,
   "X skipped"). The root is destroyed in `pytest_unconfigure` (safe — it runs
   once at session end, so the "never re-create after destroy" rule from the
   Python 3.14 Tcl-corruption note in `audio_suite_shared/tests/conftest.py:169-171`
   is preserved).
   Notes: the existing `audio_suite_shared/tests/conftest.py` defined `tk_root` at
   lines 167-176 — **remove that duplicate definition** from the shared-suite
   conftest and rely on the root one (the package conftest still owns its non-Tk
   fixtures: `temp_directory`, `sample_audio_files`, `mock_processor`, etc.).
2. **Inventory the per-tool conftests.** List every `tests/conftest.py` whose *only* content is the Tk bootstrap. Replace each with a zero-body file (`"""Placeholder — shared root comes from the repo-root conftest."""`). Do not delete files outright (pytest `testpaths` discovery is unaffected either way, but keeping the file avoids churn in package layouts that import fixtures from `conftest`).
3. **Keep every package conftest that carries private fixtures** untouched.
4. **Validate.** Run `pytest --collect-only` then the full suite. Confirm tests that previously required the per-package `root` fixture still resolve (repo-root conftest applies to all `testpaths` directories). Confirm headless CI behaviour: the matrix already runs on `ubuntu-latest` where `tkinter` is present but headless — the marker-skip on `TclError` fires there (all tests collected but skipped). Headless caveat: the root conftest causes a headless full-suite run to record 0% coverage of Tk-dependent code; that path already produces a `--cov-fail-under` failure today (skipped tests contribute no coverage), so it is a pre-existing limitation, not a P5 regression.

### Tests in lockstep
- `audio_suite_shared/tests/test_cli_helpers.py::TestWasLaunchedFromDriver` → full union matrix.
- Full suite must remain green; no per-tool conftest may silently lose its `root` fixture.

### Acceptance criteria
- `grep -c "def was_launched_from_driver" audio_suite_shared/cli_helpers.py` = 1; zero local definitions remain in tool packages (each `utils/cli_args.py` ships the single-line `as` re-export, which is what makes mypy `--strict` pass on the importing `app.py` call sites).
- Root `conftest.py` exists; ≤1 definition of `tk_root` across the tree (the shared-suite one removed; `audio_fingerprinter/tests/conftest.py` keeps only its private fixtures, `genre_sync/tests/conftest.py` untouched).
- Full suite green, coverage ≥75%.

### Decisions / risks
- P5a deliberately does **not** fold the per-tool `parse()`/`validate_args()` loops into the shared layer (the audit listed that as a *further* duplication cluster, not part of this action). If P5 exposes that consolidation is trivial, raise it with the user rather than doing it silently.
- Risk: the per-tool divergence matrix (5a step 1) may contain conflicting expectations; reconcile by recording and adjusting the canonical function, never by a per-tool `if`.

---

## P6 — Register the four orphan tools in the manifest registry

**Problem:** `Audio_Enhancer`, `Audio_Normalizer`, `Pop_Click_Remover`, `Silence_Trimmer` are fully built (standalone GUI `.pyw` launchers, `cli.py` commands, user guides, tests) but have **no `ToolManifest`** (`audio_suite_shared/tool_plugin.py:153-420`) and therefore **no Master Driver card** — an inconsistent product surface ("No card UI for tool '<id>'" warnings).

### Pre-checked against AGENTS.md "Registering a New Tool" checklist (already satisfied — do not redo)
- **CLI command + import** in `audio_suite_shared/cli_app.py`: present (`enhance` :36, `normalise` :38, `declick` :53, `silence-trim` :55).
- **`.pyw` launchers**: `Audio_Enhancer.pyw`, `Audio_Normalizer.pyw`, `Pop_Click_Remover.pyw`, `Silence_Trimmer.pyw` exist.
- **User guide generator + `guide_to_program` registration**: `user_guides/individual_programs/{tool}/generate_guide.py` exist for all four; `platform_utils.py guide_to_program` already lists them (lines 103/105/120/122).
- **Test paths**: all four are already in `pyproject.toml testpaths` and coverage `source`.

### Steps

1. **Add four `ToolManifest` entries** to `_build_default_registry()` in `audio_suite_shared/tool_plugin.py` (Utility category, `standalone=True` to match `noise_reduction`'s semantics — launched non-blocking, skipped from parallel batch scheduling), with the exact CLI names and launcher filenames:

   | id | name | category | pyw_filename | cli_command | standalone | order |
   |---|---|---|---|---|---|---|
   | `audio_enhancer` | Audio Enhancer | utility | `Audio_Enhancer.pyw` | `enhance` | True | 43 |
   | `audio_normalizer` | Audio Normalizer | utility | `Audio_Normalizer.pyw` | `normalise` | True | 44 |
   | `pop_click_remover` | Pop/Click Remover | utility | `Pop_Click_Remover.pyw` | `declick` | True | 45 |
   | `silence_trimmer` | Silence Trimmer | utility | `Silence_Trimmer.pyw` | `silence-trim` | True | 46 |

   Order values slot around existing utility tool `noise_reduction` (order=42). Set `default_on=False` so existing driver state is not flipped on.

2. **Add per-module option vars to `master_driver/state/app_state.py`** (the `__init__` option block after `:71`), matching each tool's own `utils/cli_args.py` + `cli.py` grammar:
   - `audio_enhancer`: `enhancer_output_dir` (StringVar ""), `enhancer_preset` (StringVar "Moderate") — CLI: `--output-dir` (required), `--preset`.
   - `audio_normalizer`: `normalizer_target_lufs` (StringVar "-14.0"), `normalizer_tolerance` (StringVar "0.5"), `normalizer_mode` (StringVar "normalise") — CLI: `--target-lufs`, `--tolerance`, `--mode normalise|lossless`.
   - `pop_click_remover`: `declick_sensitivity` (StringVar "0.25"), `declick_max_width` (StringVar "5") — CLI: `--sensitivity`, `--max-width`.
   - `silence_trimmer`: `trimmer_threshold` (StringVar "-50"), `trimmer_apply_fade` (BooleanVar False), `trimmer_fade_in_ms` (StringVar "25"), `trimmer_fade_out_ms` (StringVar "25") — CLI: `--threshold`, `--fade/--no-fade`, `--fade-in`, `--fade-out`.
3. **Create the four cards** as `master_driver/ui/cards/{tool_id}_card.py` — file names MUST equal the manifest ids exactly (card-naming AGENTS.md rule):
   - `audio_enhancer_card.py`, `audio_normalizer_card.py`, `pop_click_remover_card.py`, `silence_trimmer_card.py`, each exposing `build(parent: tk.Frame, state: "AppState") -> None`.
   - Copy the collapsible-panel structure of `master_driver/ui/cards/noise_reduction_card.py` (header Checkbutton bound to `state.module_toggles[tool_id]`, settings body toggled by the ▶/▼ button). Widgets bind to the new app_state vars from step 2.
   - `audio_enhancer_card` additionally needs an output-dir **browse** affordance (its CLI requires `--output-dir`); keep it minimal — an Entry + Browse button that writes `state.enhancer_output_dir`. If `enhancer_output_dir` is empty at run time, `arg_builder` must omit the tool from the batch (see step 5) rather than launch with a broken command.
   - No `_CARD_MODULE_OVERRIDES` entries in `utilities_window.py:26-28` required — names follow the convention.
4. **Extend `master_driver/runner/arg_builder.py` `_build_utility_tool_args`** (builders dict at `:208-282`) with four builders mirroring each tool's CLI grammar and the driver handshake (path, `mode_flag`, `start_flag`, `end_flag`, tool flags, then `_driver_display_flags`):
   ```python
   "audio_enhancer": lambda: _build_audio_enhancer_args(path, mode_flag, start_flag, end_flag, state),
   "audio_normalizer": lambda: _build_audio_normalizer_args(path, mode_flag, start_flag, end_flag, state),
   "pop_click_remover": lambda: _build_pop_click_remover_args(path, mode_flag, start_flag, end_flag, state),
   "silence_trimmer": lambda: _build_silence_trimmer_args(path, mode_flag, start_flag, end_flag, state),
   ```
   - `_build_audio_enhancer_args`: `[path, "--output-dir", out, "--preset", preset] + display flags`. If `out` empty → return `[]` (tool silently skipped; add a `_log` in `module_runner`... **no** — keep return `[]` and rely on the card's required-field label; record behaviour in the card docstring).
   - `_build_audio_normalizer_args`: `[path, target_lufs, mode_flag, start_flag, end_flag, "--tolerance", tol, "--mode", mode] + display flags` (mirrors the existing `replaygain` enrich pattern: positional target-lufs).
   - `_build_pop_click_remover_args`: `[path, mode_flag, start_flag, end_flag, "--sensitivity", sens, "--max-width", width] + display flags`.
   - `_build_silence_trimmer_args`: `[path, mode_flag, start_flag, end_flag, "--threshold", thr] + (["--fade", "--fade-in", fin, "--fade-out", fout] if apply_fade) + display flags` (add `--parallel/--workers` only if the tool's runner sync is desired — it is not part of driver orchestration; omit).
5. **Add the four ids to `master_driver/batch_orchestrator.py` `DEPENDENCY_GRAPH`** (after `:141`) with `[]` deps, so the graph mirrors the full registry (the integrity test at `test_batch_orchestrator.py:433-445` is currently advisory `assert tid in graph or True`, but the graph is the source of truth for batch ordering — keep it complete).
6. **Update lockstep tests:**
   - `audio_suite_shared/tests/test_tool_plugin.py`: expected-tool-set assertions (add the four ids; adjust `by_category("utility")` expectations if asserted).
   - `master_driver/tests/test_app_state.py`: expected-keys test — add the 8 option vars from step 2.
   - `master_driver/tests/test_runner.py`: `_make_state` (lines 75-160) — add the four `module_toggles` keys + the 8 option-var mocks; add `TestBuildUtilityArgs` rows asserting the four new arg lists (structure + flag names + a `dry`/`live` toggle case each). Extend `TestBuildEnrichArgs` **only if** any of the four were placed in enrich (they are not — utility).
   - `master_driver/ui/tests` if any asserts card-count/membership for the utility tab (verify; update the list).
7. **GUI smoke test manually** (not pytest): `Master_Driver.pyw` → UTIL tab shows the four new cards, each toggles on/off, Launch passes the expected argv (dry-run mode).

### Acceptance criteria
- Registry holds 26 manifests; Utilities tab renders four new cards with working controls.
- `ensure build_utility_args` emits `[path, mode, start, end, ...]` for the new tools (`test_runner.py` asserts it) and never emits a broken `--output-dir` for the enhancer with an empty output dir.
- Full suite + compile gate green; coverage unchanged or improved in the touched modules.

### Decisions / risks
- Placing the four under utility (not enrich) is deliberate: they are DSP-write tools, matching `noise_reduction`'s home. Enrich is reserved for tag/metadata tools.
- The `audio_enhancer` requires an output directory by design (it never writes in place); the enhancement output-dir is a *behaviour difference* vs. the other three and must be communicated in the card (label "Output folder (required)").
- Card naming rule is the known silent-failure trap — verify `importlib.import_module(f"master_driver.ui.cards.{tool_id}_card")` resolves by running the Utilities tab, not by file listing.

---

## P7 — Product-roadmap initiatives (feature backlog; fully specified)

These close the three largest market gaps named in the audit. They are independent, larger initiatives. Do NOT bundle them into P1–P6; deliver each as its own PLAN with its own gate. Specified here to the point where a future session can execute without re-research.

### 7a. Ripping verification: "Rip Twice" local verify + AccurateRip-DB cross-check

**Gap:** `cd_ripper` (`core/track_processor.py`) does repeated-read/C2 diagnostics but has no community-database cross-check (AccurateRip is the industry trust standard). Note: this is a *rebuild/backlog* item — the existing ripper is not broken.

**Design:**
1. New module `cd_ripper/core/accuraterip.py`:
   - Compute the AccurateRip Disc ID from the TOC start LSNs (first-track start + each track offset + lead-out), using the published ID formula exercised by the open-source CUERipper/CUETools (reference implementations only — clean-room client, no copied code).
   - Compute per-track CRC-32 over 16-sample-aligned frames for the "standard" and "with gap" variants, as the AccurateRip protocol expects.
   - HTTP client (via the project's `requests` dependency + the shared secure-subprocess/HTTP standards; note bandit B310 guidance — HTTP here is `requests`, not `urllib`), querying the AccurateRip DB endpoint; handle 200 with embedded CRC payload, 404/no-entry, and timeouts as three distinct results.
2. New verification stage in `track_processor`: after the raw read, re-read the track once more and compare frame CRCs (this is the always-available "rip twice" fallback — no network dependency), then optionally cross-check the resulting CRC against the AccurateRip DB.
3. CLI flag `--verify` with `Choice(["off", "twice", "accuraterip"])` (default `twice`); GUI control in `cd_ripper` setup UI; results surfaced per-track in `results_tab` (VERIFIED / MISMATCH / NO_ENTRY / OFFLINE) and aggregated in the summary.
4. **Config/settings:** none beyond the CLI flag; **undo/atomicity:** ripping writes to the output dir only after a verified read — a MISMATCH must not write the track (configurable `--force-on-mismatch` in follow-up only).

**Tests (decode-and-measure discipline):**
- Pure tests: Disc-ID from a known public TOC vector (hard-code two published release vectors with their expected IDs); CRC-32 over synthetic frames vs reference values; with/without-gap frame alignment; HTTP client mocked for 200/404/timeout/HTTP-error (`resolve_*` returning typed results).
- Integration (marker `integration`, only when a CD is mounted — keep optional): rip a track with the drive, assert VERIFIED when DRIVE is the source; run the "rip twice" path and assert CRCs equal across the two reads.
- No mocks of the CRC math; assert the actual computed value.

**Acceptance:** `cd-rip --verify twice` runs fully offline; `--verify accuraterip` degrades to VERIFIED-with-local-check when the disc is absent from the DB; a corrupted/second-read mismatch is reported and blocks the write unless overridden. Full gate green.

**Risks / notes:** AccurateRip is a proprietary-but-public community service; protocol learned from open-source implementations (CUERipper/CUETools published code). Do not wrap it in a closed abstraction that hides the network dependency; keep OFFLINE/NO_ENTRY as first-class results. Scope creep guard: no offset database UI, no per-drive offset management in this item.

### 7b. Album-level AcoustID clustering (Fingerprinter)

**Gap:** `audio_fingerprinter` resolves per-file best matches. Picard's signature power is *album-level* clustering (match a whole release at once). The existing client (`core/acoustid_client.py`) already has the tag-aware near-tie break (`resolve_best_match`, `_AMBIGUITY_SCORE_GAP` ~0.10) — build on it.

**Design:**
1. Client extension: `lookup_many(fingerprints: list[Fingerprint]) -> list[AcoustIdResponse]` — batched, rate-limited (reuse the existing sliding limiter; do NOT hammer the API — batch per request is bounded to ~5).
2. New module `audio_fingerprinter/core/album_cluster.py`:
   - Group candidate recordings by MusicBrainz **release-group** (`release-group-id`), require a minimum vote (`CLUSTER_MIN_FILES`, e.g. 3 files in the same release-group with matching per-file score ≥ `_AMBIGUITY_SCORE_GAP-adjacent` threshold).
   - Score each cluster by (files voting) × (average per-file confidence); a cluster is "decided" when it wins by a margin over the runner-up; otherwise the ambiguity is surfaced (reuse the existing runner-up-in-message convention).
   - Only write tags after a decided cluster; per-file fallback to today's `resolve_best_match` when no cluster forms.
3. CLI: `fingerprint --album-mode` (adds cluster-level tagging + a `--album-min` count, default 3); GUI: an "Album Match" mode checkbox exposing the same option. Dry-run report lists proposed cluster per album.
4. Undo: cluster tag-writes go through the existing `active_batch` snapshot path (no new undo machinery).

**Tests:** unit-test `album_cluster` with synthetic responses (decided cluster / tie → ambiguous / below-min → fallback); client `lookup_many` with mocked HTTP + limiter spacing; integration with recorded responses (no live API in tests). Assert actual tag sets written for the decided-cluster path (outcome verification), not internal state.

**Acceptance:** `--album-mode` produces consistent album tags for a multi-file album, defers to per-file when uncertain, rate-limits correctly, and leaves ambiguous files untagged with the runner-up surfaced. Full gate green.

**Risks / notes:** cluster quality depends on AcoustID result quality — the existing tag-aware tie-break remains the per-file safety net. Do not reduce per-file safeguards; clustering only *adds* cross-file evidence.

### 7c. Freeform batch Tag Editor (new tool — largest initiative)

**Gap:** the suite has powerful *transformational* taggers (field updater, scrubber, genre rules) but no interactive editable grid — Mp3tag's daily-driver surface. This is a new tool per the full "Registering a New Tool" checklist.

**Design (phased; each phase has its own gate):**
- **Phase A — read-only grid + single-field edit:** new package `tag_editor/` (utility category, id `tag_editor`, CLI `tag-edit`, `.pyw` launcher `Tag_Editor.pyw`, `generate_guide.py` + `guide_to_program` registration, testpaths/coverage entries, manifest + card + arg_builder + `DEPENDENCY_GRAPH` + app-state vars per the P6 recipe). ttk.Treeview listing files (library scan via `audio_suite_shared.audio_formats` supported extensions) × editable columns (title/artist/album/album_artist/track/year/genre/comment); edits write through first-party `tag_helper` handlers (reuse the format handler factory — do not re-implement mutagen per format). Writes run through `batch_undo` (`active_batch`).
- **Phase B — bulk ops:** multi-select rows; set-blank, clear-field, swap-two-fields, case-convert, apply-TXXX-rule reusing `tag_field_updater`'s mapping engine concepts (new code, cross-referenced, not monkey-patched).
- **Phase C — import/export:** CSV import (column→field map) and CSV export (mirrors `library_stats` CSV exporter); optional click `--csv FILE --dry`.
- **Out of scope (explicit):** tag *inference* (Picard matching) — that's 7b; scriptable regex actions beyond basic case/swap — that's an Mp3tag action-groups feature and is a *further* backlog item, not this one.

**Tests:** every phase carries decode-and-measure round-trip tests (real MP3/FLAC/OGG files via pydub export): edit → read via `mutagen` directly → assert field value; undo → assert original restored (reuse the `FLAC` mutate-in-place regression pattern from AGENTS.md — never rebind `.tags`). CSV import/export round-trip tests. GUI tests via the `object.__new__` pattern.

**Acceptance:** a user can load a folder, edit album/title/genre across selected rows, and undo the whole batch from `Undo_Tag_Edits.pyw`. Full gate green at each phase.

**Risks / notes:** the largest item — do NOT fold into P1–P6; split Phase A from the rest and gate each. Watch the freeform-editor input-validation path (use `security/input_validator.py`). Tag-editor writes must be integrity-safe for audio payloads (only tag frames change — no audio rewrite; reuse the lossless tag-write paths, never re-encode).

---

## Decision Log

| # | Item | Decision | Rationale |
|---|---|---|---|
| D1 | P1/Q1 `uv.lock` | **Applied in P1** — commit it (remove ignore line) | `uv.lock` now tracked; CI's `uv sync` graph pinned |
| D2 | P1/Q2 `fpcalc.exe` | **Applied in P1** — commit it (measured 3.95 MB < 5 MB limit) | Tracked + noted in `AGENTS.md` (no root README exists; the note substitutes) |
| D3 | P2 std Medium findings | Fix-in-change per AGENTS.md §7 | Widened scan must land at 0 H / 0 M |
| D4 | P4 mypy strict | **Applied in P4** — Option A: `strict = true` set in `[tool.mypy]`; commit `f409e11` | Aligns config with documented claim; tail was *even smaller than predicted*: **zero sites** — the 429-file tree passed `mypy --strict` as-is with the existing `untyped_calls_exclude` + overrides, and no `# type: ignore` needed touching |
| D5 | P5 is-launched-from-driver | Canonical in `cli_helpers`, per-tool re-export | Zero churn at call sites; single source of truth |
| D6 | P6 category/standalone | utility + `standalone=True` | Matches `noise_reduction` semantics; enrich stays tag/metadata-only |
| D7 | P6 enhancer output-dir | Required; missing → card omits tool from batch | Enhancer never writes in place by design |
| D8 | P7 order | 7a → 7b → 7c; each its own gate | Increasing complexity; 7c is the largest |
| D9 | Defects discovered during implementation | Fixed in the change that found them + regression test | Global AGENTS.md §7; applies to every P1–P6 step |
| D10 | P1 prerequisite: git absent from machine | Installed Git for Windows 2.55.0.3 via `winget` (user-approved) | P1 is blocked without VCS; standard supported install |
| D11 | P1 secret-gate gap + staged secrets | Subtracted the audit regex's blind spots: `\*_key`/`\*_secret`-suffixed keys, 32-hex literals, 44+-char base64 — none were flagged by the plan's `api[_-]?key|...` pattern. Found four staged `album_art_sync/{,core/}album_art_config.{json,key}` with live Fanart.tv keys: unstaged, `.gitignore` extended with `album_art_config.json` / `album_art_config.key` (matches any depth), `AGENTS.md` §Repository now names them, and the `check-ignore` lockstep list extended | AGENTS.md: never commit API keys/secrets; a live key was caught mid-stage exactly as the P1 risk block warned |
| D12 | P2 widened-scan outcome | **Applied in P2** — full-tree scan landed at 0 High / 0 Medium (51 Low, all documented categories), so D3 held as a no-op and CI was updated exactly as specced. B105 flag-string findings (`--bpm-min`, `--workers`, `--apply-gain`, …) recorded as false positives, not secrets (P1 token-class scans clean) | Widening to all 26 packages surfaced no release-blocking defect; keeping the Low tail documented avoids noise-chasing on false positives |
| D13 | P3 test premise + busy-wait test | **Premise verified empirically:** the two-instance concurrent-writer regression test written *first* failed on the pre-fix code with `OperationalError('database is locked')` exactly as the plan predicted, and passes post-fix. The `BEGIN EXCLUSIVE` busy-wait test passes both pre- and post-fix (it asserts the SQLite busy-timeout wait, which pre-fix already had at the 5 s default — it is an acceptance test for the 30 s behaviour, not a failing-pre-fix repro). Its first draft crashed with `check_same_thread` because the holder connection was opened on the main thread and used in the worker thread — fixed by creating it (with `check_same_thread=False`) inside the thread body | AGENTS.md: empirically reproduce the bug against real behaviour before asserting a test "fails pre-fix"; write-order audit confirmed no `scanned_at`-ordering exists, so step 4 was a true no-op |

---

## Execution order & sequencing

1. **P1** (foundation: VCS for reviewable commits) → commit with message `P1: initialise git repository`.
2. **P2** + **P3** + **P4** in parallel (independent; P4 rewrites no runtime code, P2/P3 are localised) → commits `P2: harden CI security+compile gate`, `P3: library_cache concurrency`, `P4: strict mypy config` (commits `d7680f7`, `c06730c`+`e540819`, `f409e11`+plan update — all DONE).
3. **P5** (largest touching change) → commit `P5: deduplicate driver-launch + Tk test root` (commit `0666936` + plan update — DONE).
4. **P6** (self-contained product-surface fix) → commit `P6: register orphan DSP tools`.
5. **P7** items: separate plans, separate gates, backlog order 7a → 7b → 7c.
6. After every commit: run the Definition of Done gate; after P4 also `mypy .` and after P6 run the Master Driver manually.

Each commit above may be split into several commits at the implementer's discretion (atomic units preferred), but the gate runs must correspond to the *state after each item*, not after P1..P6 cumulatively.

---

## Session retrospective (fill in after each item lands)

| Item | Lesson learned / gotcha | Feed into AGENTS.md? |
|---|---|---|
| P1 | (1) pwsh `\"` inside a double-quoted string is **not** an escape — it terminates the string, so any audit `rg`/`grep` pattern carrying `["']` must be rebuilt (split the quote class, or use single-quoted pattern vars with `''` doubling). (2) `rg` was also absent from the machine — `git grep --cached` over the *staged* set is the stronger gate anyway (scans only what is about to be committed). (3) The audit secret regex only matches `api[_-]?key`-families and quoted assignments — real `app_key`/`client_key` values in `album_art_sync/*.json` (an `app_key: "…"` hit is not even a `secret/password/token` token) sailed through until a supplemental `-e '[-_](key|secret|token|password|passwd|client)[^ ]*[=:][^A-Za-z0-9_][A-Za-z0-9+/=_-]{10,}'` + 32-hex + 44+-base64 scan ran. (4) `compileall -x '(^|/)(\.venv|\.git)/'` uses forward slashes; on Windows it does **not** exclude `.venv` (paths use `\`), emitting harmless third-party SyntaxWarnings — plan-wide, accepted as-is. | Yes — the pwsh secret-scan gotchas (1)/(3) are generic; propose a Windows secret-scan note for AGENTS.md ⌈Verification Tooling⌉/§6. |
| P2 | (1) The widened full-tree scan lands at 0 High / 0 Medium with zero surprises — the "26-package worry" never materialised because the suite's subprocess discipline already routes everything through `run_secure_subprocess()`; expected Medium count was zero and stayed zero. (2) The Low tail is dominated by **B105 false positives on CLI flag strings** (`--bpm-min`, `--workers`, `--apply-gain`, …) — a whole class of noise that only appears once you scan per-tool `utils/cli_args.py` files; record them as known-noise rather than editing code to appease bandit. (3) `compileall -x` on Windows does NOT exclude `.venv` (forward-slash regexp vs backslash paths) — the pydub SyntaxWarnings are expected noise; CI (Linux, no `.venv`) will not see them. | No — B105-flag noise and the `-x` Windows quirk are already covered by existing AGENTS.md notes; no new generic rule emerged. |
| P3 | (1) **Write the regression test BEFORE the fix and run it against the buggy code** — the two-instance barrier test failed pre-fix with the exact `OperationalError('database is locked')` the plan predicted, converting the plan's "fails pre-fix" claim from hearsay into a verified repro. (2) **`sqlite3` connections are thread-affine by default** — a raw holder connection created on the main thread and used inside a worker thread dies with `check_same_thread`, so test harnesses that drive SQLite from threads must create the connection in the thread (or pass `check_same_thread=False`). (3) A busy-wait acceptance test (`BEGIN EXCLUSIVE` → upsert blocks then succeeds) passes *both* before and after the fix because the pre-fix default `sqlite3` timeout is already 5 s — such tests verify the *new* 30 s contract but are not failing-pre-fix regressions; do not mislabel them. | No — (2) is a Python stdlib fact already implied by the suite's `check_same_thread=False` use; (1)/(3) are session-specific verification habits already covered by AGENTS.md §3/§9 |
| P4 | (1) `strict = true` predicts "a small, mechanical error tail" but the reality can be zero — the strict-missing-flag set was already ~99% covered by years of incremental flag promotion (`no_implicit_optional`/`warn_redundant_casts`/`warn_unused_configs`/`warn_return_any`/`disallow_incomplete_defs`/`check_untyped_defs` were already set). Always run the post-change `mypy .` *before* assuming fixes are needed. (2) Mypy's `run metrics` summary has two identical-looking blocks: "Total issues (by severity)" vs "Total issues (by confidence)" — the `31 Medium / 20 High` numbers are confidence buckets; the 0H/0M/51L gate reads the **severity** block. (3) Verify strict actually *fires* (probe file with a known `no-untyped-def`/`type-arg` violation) rather than trusting config parsing — `warn_unused_configs`' "unused section(s)" note is the smoking gun when an override block matches nothing (it appeared in my single-file probe because the probe imported none of the override modules; the full-tree run has no such note). | No — (2) is bandit-version noise, (3) is a mypy-internals curiosity; the transferable lesson (strict=true lands clean; verify with a probe) is already implied by AGENTS.md §3/§6. |
| P5 | (1) **Trust the union matrix over the sketch** — grepping the 19 legacy bodies proved they were all `sys.argv[1:]` + `len > 1`, so the plan's flag-set/first-token sketch (which misfires on `["prog"]`) was replaced with full-argv `len > 1`; write the matrix first, reconcile the implementation to it. (2) **`pytest.skip()` inside `pytest_configure` is a pytest-9 fatal** (`INTERNALERROR`, exit 3); skip markers must be added in `pytest_collection_modifyitems`. (3) **mypy `--strict` re-export discipline:** a `# noqa: F401` re-export passes ruff but fails `CheckPy` on the importing module — use the `name as name` alias; it is also self-documenting as an explicit re-export. (4) A parenthesized `from ... import (...)` is not a safe insertion point for a scripted re-export edit — `tempo_analyzer`/`replaygain_analyzer` ended up with the new import nesting inside the existing parenthesized `cli_dataclasses` import and had to be repaired by hand; scripted bulk edits must always be followed by a compile gate + a visual diff of the touched lines. (5) The per-tool list of tools that "defined" `was_launched_from_driver` was also wrong in the plan: `audio_enhancer`/`audio_normalizer` never defined it (re-export made them consistent for free); `silence_trimmer` had no shortened variant. Re-derive such lists from grep, not from the plan prose. | Yes — (3) is a generic mypy/strict-reexport rule worth an AGENTS.md note under Verification Tooling; (4) is a scripted-edit-safety habit; (1)(2)(5) are covered by the D14 decision-log row. |
| P6 | (reserved) | |
| D14 | P5 canonical form + conftest skip + tk_root strip | **Applied in P5** — (1) **Canonical form:** every legacy body was byte-identical `if argv is None: argv = sys.argv[1:]; return len(argv) > 1`, so the plan's `_DRIVER_ONLY_FLAGS`/first-token sketch was *dropped* (it would return True for `["prog"]`, which the union matrix asserts is False). Released canonical: full `sys.argv` + `len(argv) > 1`; both call patterns (standalone bare launch, driver-with-path launch) yield identical booleans on legacy and canonical, and all 20 union-matrix rows (8 false / 12 true) pass. Refinement: a manual `Tempo_Analyzer.pyw D:/Music` run now counts as driven (was standalone under the `[1:]` default). (2) **`pytest.skip()` inside `pytest_configure` is fatal:** on pytest 9.x it raises `INTERNALERROR: usage._ExitCode` (exit 3) — verified with a temp experiment; the released root conftest records `_root = None` in `pytest_configure` and adds `pytest.mark.skip` markers in `pytest_collection_modifyitems` (exit 0, "X skipped"). (3) **mypy strict vs re-export:** `# noqa: F401`-only re-exports fail `CheckPy` on the importing `app.py` ("does not explicitly export attribute"); the redundant-alias form (`was_launched_from_driver as was_launched_from_driver`) is the explicit-reexport marker mypy accepts. (4) `audio_fingerprinter/tests/conftest.py`'s `tk_root` stripped (kept its 10 private fixtures); `genre_sync`'s local `root` kept (shadows the root-conftest fixture for its package only). Headless all-skip ⇒ 0% coverage of Tk code, a pre-existing `--cov-fail-under` failure, not a P5 regression | Single source of truth (`grep -c "def was_launched_from_driver" cli_helpers.py` = 1); 23 bootstrap conftests → placeholders; full suite 6527 passed / 5 skipped, coverage 77.36% |

---

## Execution order & sequencing

1. **P1** (foundation: VCS for reviewable commits) → commit with message `P1: initialise git repository`.
2. **P2** + **P3** + **P4** in parallel (independent; P4 rewrites no runtime code, P2/P3 are localised) → commits `P2: harden CI security+compile gate`, `P3: library_cache concurrency`, `P4: strict mypy config` (commits `d7680f7`, `c06730c`+`e540819`, `f409e11`+plan update — all DONE).
3. **P5** (largest touching change) → commit `P5: deduplicate driver-launch + Tk test root` (commit `0666936` + plan update — DONE).
4. **P6** (self-contained product-surface fix) → commit `P6: register orphan DSP tools`.
5. **P7** items: separate plans, separate gates, backlog order 7a → 7b → 7c.
6. After every commit: run the Definition of Done gate; after P4 also `mypy .` and after P6 run the Master Driver manually.

Each commit above may be split into several commits at the implementer's discretion (atomic units preferred), but the gate runs must correspond to the *state after each item*, not after P1..P6 cumulatively.

---

## Session retrospective (fill in after each item lands)

| Item | Lesson learned / gotcha | Feed into AGENTS.md? |
|---|---|---|
| P1 | (1) pwsh `\"` inside a double-quoted string is **not** an escape — it terminates the string, so any audit `rg`/`grep` pattern carrying `["']` must be rebuilt (split the quote class, or use single-quoted pattern vars with `''` doubling). (2) `rg` was also absent from the machine — `git grep --cached` over the *staged* set is the stronger gate anyway (scans only what is about to be committed). (3) The audit secret regex only matches `api[_-]?key`-families and quoted assignments — real `app_key`/`client_key` values in `album_art_sync/*.json` (an `app_key: "…"` hit is not even a `secret/password/token` token) sailed through until a supplemental `-e '[-_](key|secret|token|password|passwd|client)[^ ]*[=:][^A-Za-z0-9_][A-Za-z0-9+/=_-]{10,}'` + 32-hex + 44+-base64 scan ran. (4) `compileall -x '(^|/)(\.venv|\.git)/'` uses forward slashes; on Windows it does **not** exclude `.venv` (paths use `\`), emitting harmless third-party SyntaxWarnings — plan-wide, accepted as-is. | Yes — the pwsh secret-scan gotchas (1)/(3) are generic; propose a Windows secret-scan note for AGENTS.md ⌈Verification Tooling⌉/§6. |
| P2 | (1) The widened full-tree scan lands at 0 High / 0 Medium with zero surprises — the "26-package worry" never materialised because the suite's subprocess discipline already routes everything through `run_secure_subprocess()`; expected Medium count was zero and stayed zero. (2) The Low tail is dominated by **B105 false positives on CLI flag strings** (`--bpm-min`, `--workers`, `--apply-gain`, …) — a whole class of noise that only appears once you scan per-tool `utils/cli_args.py` files; record them as known-noise rather than editing code to appease bandit. (3) `compileall -x` on Windows does NOT exclude `.venv` (forward-slash regexp vs backslash paths) — the pydub SyntaxWarnings are expected noise; CI (Linux, no `.venv`) will not see them. | No — B105-flag noise and the `-x` Windows quirk are already covered by existing AGENTS.md notes; no new generic rule emerged. |
| P3 | (1) **Write the regression test BEFORE the fix and run it against the buggy code** — the two-instance barrier test failed pre-fix with the exact `OperationalError('database is locked')` the plan predicted, converting the plan's "fails pre-fix" claim from hearsay into a verified repro. (2) **`sqlite3` connections are thread-affine by default** — a raw holder connection created on the main thread and used inside a worker thread dies with `check_same_thread`, so test harnesses that drive SQLite from threads must create the connection in the thread (or pass `check_same_thread=False`). (3) A busy-wait acceptance test (`BEGIN EXCLUSIVE` → upsert blocks then succeeds) passes *both* before and after the fix because the pre-fix default `sqlite3` timeout is already 5 s — such tests verify the *new* 30 s contract but are not failing-pre-fix regressions; do not mislabel them. | No — (2) is a Python stdlib fact already implied by the suite's `check_same_thread=False` use; (1)/(3) are session-specific verification habits already covered by AGENTS.md §3/§9 |
| P4 | (1) `strict = true` predicts "a small, mechanical error tail" but the reality can be zero — the strict-missing-flag set was already ~99% covered by years of incremental flag promotion (`no_implicit_optional`/`warn_redundant_casts`/`warn_unused_configs`/`warn_return_any`/`disallow_incomplete_defs`/`check_untyped_defs` were already set). Always run the post-change `mypy .` *before* assuming fixes are needed. (2) Mypy's `run metrics` summary has two identical-looking blocks: "Total issues (by severity)" vs "Total issues (by confidence)" — the `31 Medium / 20 High` numbers are confidence buckets; the 0H/0M/51L gate reads the **severity** block. (3) Verify strict actually *fires* (probe file with a known `no-untyped-def`/`type-arg` violation) rather than trusting config parsing — `warn_unused_configs`' "unused section(s)" note is the smoking gun when an override block matches nothing (it appeared in my single-file probe because the probe imported none of the override modules; the full-tree run has no such note). | No — (2) is bandit-version noise, (3) is a mypy-internals curiosity; the transferable lesson (strict=true lands clean; verify with a probe) is already implied by AGENTS.md §3/§6. |
| P5 | (reserved) | |
| P6 | (reserved) | |
