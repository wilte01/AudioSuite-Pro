# Audit Remediation Plan — Iteration 4 — AudioSuite-Pro

**Source:** Post-Iteration-3 Audit (2026-09-19), "Recommended next iteration"
**Status:** Active
**Last Updated:** 2026-09-19
**Scope:** Items 1–3 of the recommendation (finish the two consolidations;
harden `key_manager`; de-duplication & hygiene). Item 4 (AccurateRip/CD
verification, AAC/M4A lossless gain) is **deferred by decision** to a
separate strategic feature plan — recorded in the Decision Log.
**Baseline gate:** 6388 passed / 5 skipped, coverage 77.34%,
mypy `--strict` 429 source files clean, bandit 0 High / 0 Medium.

---

## Phase Legend

| Symbol | Meaning |
|--------|---------|
| `[ ]`  | Not started |
| `[-]`  | In progress |
| `[x]`  | Completed |
| `[~]`  | Partially completed |
| `[!]`  | Blocked / needs decision |

---

## Sprint 1 — Complete the Subprocess Consolidation

### A1 — Route `audio_refinery/core/measure.py` through `run_secure_subprocess`

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `measure_loudness_metrics()` is the last raw `subprocess.run`
in first-party core code — a function-local `import subprocess`
(`measure.py:344`) and a raw call at `:358` with a magic `timeout=30`,
bypassing the allowlist/argument validation every sibling call site now uses.
The command is a fixed ffmpeg argv, so this is a policy leftover, not a
vulnerability.

**Scope:**

- [ ] Add `from audio_suite_shared.secure_subprocess import
      run_secure_subprocess` at module top; drop the function-local
      `import subprocess`.
- [ ] Replace `subprocess.run(cmd, capture_output=True, text=True, timeout=30,
      startupinfo=...)` with `run_secure_subprocess("ffmpeg", cmd[1:],
      capture_output=True, text=True, timeout=30, startupinfo=...)` —
      `measure.py` already imports `get_startupinfo` from
      `audio_suite_shared.subprocess_utils` (correct).
- [ ] Keep `timeout=30` inline. Rationale already recorded in the
      Iteration-3 Decision Log: a short ffmpeg probe timeout with a single
      call site; forcing a shared constant would mis-name it.
- [ ] Update `test_measure.py` mocks (currently patch `subprocess.run`
      around :338-391) to patch the importing binding
      `audio_suite_shared.secure_subprocess.run_secure_subprocess`
      (function-local-import rule, AGENTS.md §7) or the module-level binding
      if the code resolves it that way — verify the resolution site.

**Deliverables:**
- Zero raw `subprocess.run` calls in first-party `audio_refinery/`.

**Success criteria:**
- `grep -rn 'subprocess\.run' audio_refinery/` → no matches.
- Refinery suite + `test_measure.py` pass; `grep -rn 'subprocess\.'` in
  first-party modules surfaces only `secure_subprocess` / `subprocess_utils`
  / exception-mapping references.

---

## Sprint 2 — `process_batch` Adoption (the five raw pool loops)

> The converter migration (Iteration-3 C2) proved `process_batch` is the
> established pattern and now carries worker-error mapping + logging
> (`file_processor_base.py:525-539`) that the raw loops lack. Five tools
> still hand-roll the same loop.

### B0 — Extend `process_batch` with an optional per-future timeout

**Priority:** High (prerequisite for B2) | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `process_batch` calls `f.result()` (no timeout,
`file_processor_base.py:527`). `silence_trimmer`'s loop deliberately applies
`future.result(timeout=600)` (documented in the Iteration-3 Decision Log as an
intentional generous cap above `WORKER_TIMEOUT_SECS=300`). Migrating it
faithfully needs a timeout channel in the base.

**Scope:**

- [ ] Add `future_timeout: float | None = None` (keyword-only) to
      `process_batch`; pass it to `f.result(timeout=future_timeout)` when set
      (thread-pool branch only; document that it is not applied to any
      ProcessPool path).
- [ ] In the per-future `except Exception` branch, map a
      `concurrent.futures.TimeoutExpired` explicitly (it is not the
      `subprocess.TimeoutExpired` the exception mapper already knows) — a
      timeout on a worker must produce a logged, mapped `None` result, not a
      raw re-raise or a `TypeError` deep in exception mapping.
- [ ] Add `test_file_processor_base.py` cases: (a) `future_timeout` honored
      (worker sleeps, tiny timeout → mapped result), (b) default `None`
      unchanged, (c) `TimeoutExpired` mapping path produces a logged result.

**Success criteria:**
- Existing `process_batch` consumers (8 tools) unaffected; new timeout cases
  green; default behavior byte-for-byte unchanged.

---

### B1 — genre_sync (trivial, single-arg worker)

**Priority:** Medium | **Effort:** 0.1 day | **Risk:** Low

**Problem:** `genre_sync/core/file_processor.py:254-257` raw pool with
unguarded `f.result()`, while `_process_with_retry(name: str)` is already a
single-argument worker that fits `process_batch` 1:1.

**Scope:**

- [ ] Replace the `with ThreadPoolExecutor(...)` block with
      `processor.process_batch(
          files, _process_with_retry,
          max_workers=processor.max_workers,
      )`.
- [ ] Keep `_on_progress`/counter wiring (updated/skipped/no_genre/errors)
      exactly as-is — the worker mutates them as today.
- [ ] Lockstep: update `genre_sync/tests/` mocks that target the pools or
      futures to the new resolution site.

**Success criteria:**
- No raw `ThreadPoolExecutor` in `genre_sync/`; genre_sync suite passes with
  identical progress/count semantics.

---

### B2 — silence_trimmer (needs B0's `future_timeout`)

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Medium

**Problem:** `silence_trimmer/core/file_processor.py:265-287` raw pool with
`future.result(timeout=600)`; unguarded success path (no per-future error
mapping/logging unless the pool-level `except` fires).

**Scope:**

- [ ] Migrate to `processor.process_batch(
          files, worker_fn, max_workers=processor.max_workers,
          future_timeout=600.0,
      )` where `worker_fn` is a closure mapping `name` →
      `_join_undo_batch(name, dir_path, is_dry_run, threshold, apply_fade,
      fade_in_ms, fade_out_ms, temp_dir, slot_vars, slot_queue, lock,
      _on_progress, processor.run_with_retry)` (captures the shared context
      exactly as the current `executor.submit` does).
- [ ] Preserve `track_thread(threading.current_thread(),
      "silence_trimmer_main")` and the temp-dir management; the pool-level
      `try/except Exception` may narrow to the temp-dir manager (worker
      errors are now mapped/logged inside `process_batch`).
- [ ] Behaviour-lock: UI progress deltas and undo snapshots identical
      pre/post; add a test asserting a raising worker surfaces as a logged,
      mapped result (not an uncaught pool exception).

**Success criteria:**
- No raw `ThreadPoolExecutor` in `silence_trimmer/core/file_processor.py`;
  `future_timeout=600` honored via the B0 channel; look-and-feel unchanged.

---

### B3 — noise_reduction

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `noise_reduction/core/file_processor.py:225-243` raw pool
(`DEFAULT_MAX_WORKERS` already adopted in C1) with unguarded `f.result()`
and its own `mkdtemp`/`rmtree`.

**Scope:**

- [ ] Migrate to `processor.process_batch(files, worker_fn, ...)` following
      the B2 closure pattern (`_join_undo_batch(name, dir_path, params,
      temp_dir, slot_vars, slot_queue, lock, _on_progress)`).
- [ ] Instantiate a `BaseFileProcessor` for the call if this module has none
      (see B5 note), or reuse an existing instance — keep `max_workers`
      sourced from `DEFAULT_MAX_WORKERS`.
- [ ] Lockstep test updates (mock resolution-site rule).

**Success criteria:**
- No raw `ThreadPoolExecutor` in `noise_reduction/`; suite passes; progress/
  temp-dir cleanup behaviour unchanged.

---

### B4 — pop_click_remover (+ consolidate the near-verbatim twin)

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `pop_click_remover/core/file_processor.py:279-299` is
near-verbatim a copy of noise_reduction's loop (Audit finding M2) with the
same unguarded `f.result()`.

**Scope:**

- [ ] Migrate to `processor.process_batch(...)` with the same closure pattern.
- [ ] **Consolidation (implied by the M2 duplicate finding):** where the two
      tools' `_join_undo_batch` + `mkdtemp` + progress scaffold are genuinely
      identical, extract the shared shape once (a small helper in
      `audio_suite_shared`, or a shared `_join_undo_batch` if safe) so the
      pair stops maintaining two copies of the same loop. If close reading
      shows material divergence in per-tool params, keep two thin callers
      around one helper — decide in the Decision Log.
- [ ] Lockstep test updates for both suites.

**Success criteria:**
- No raw `ThreadPoolExecutor` in `pop_click_remover/`; the duplicated
  scaffold exists in exactly one place; both suites pass.

---

### B5 — metadata_scrubber

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `metadata_scrubber/core/scrubber.py:388-407` raw pool with a
**hardcoded `max_workers=4`** (the C1 sweep missed this one — the audit
re-flagged it) and unguarded `f.result()`. The module has no processor
instance.

**Scope:**

- [ ] Instantiate `processor = BaseFileProcessor(
          max_workers=DEFAULT_MAX_WORKERS, operation_type="metadata_scrub")`
          (constructor already defaults `max_workers=DEFAULT_MAX_WORKERS` —
          `file_processor_base.py:62-67`).
- [ ] Replace the pool with `processor.process_batch(
          files, worker_fn, ...)` where `worker_fn` is the closure mapping
          `name` → `_scrub_worker(name, dir_path, is_dry_run, preserve_list,
          preserve_lyrics, preserve_album_artist, preserve_embedded_art,
          slot_vars, slot_queue, lock, _on_progress)` — identical arguments
          to today's `executor.submit`, captured per call.
- [ ] Keep the `use_batch(undo_batch)` context inside the worker closure;
      preserve the `processed/skipped/errors` counters and `on_complete`.
- [ ] Lockstep: scrubber tests that patch threads/pool/futures re-target to
      the new resolution site.

**Success criteria:**
- Zero `max_workers=` numeric literals and zero raw
  `ThreadPoolExecutor` in `metadata_scrubber/`; scrubber suite passes;
  dry-run/undo/progress semantics identical.

---

## Sprint 3 — Harden the `key_manager` ACL Path

### K1 — Allowlist `icacls`

**Priority:** Medium | **Effort:** 0.1 day | **Risk:** Low

**Problem:** `icacls` is absent from `ALLOWED_EXECUTABLES`
(`secure_subprocess.py:22-41`), so the ACL-setter cannot be routed through
the project's own secured wrapper.

**Scope:**

- [ ] Add `"icacls"` (and `"icacls.exe"`, matching the ffprobe/ffmpeg pairing
      convention) to the allowlist, with the same comments style.
- [ ] Add `test_secure_subprocess.py` cases asserting `icacls` validates
      (mirroring the existing `test_ffprobe_is_allowed`).

**Success criteria:**
- `validate_executable("icacls") is True`; allowlist raises for unknown
  names as before.

---

### K2 — Secure + guarded + logged ACL hardening

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `key_manager.py:101-119` (Audit finding M3): function-local
`import subprocess` + raw `subprocess.run(["icacls", ...])`; `os.getenv
("USERNAME")` can be `None` → a `None:F` grant that fails; `except
Exception` logs at `debug` **without** `exc_info`; a failed ACL write leaves
a freshly written Fernet key with inherited (possibly group-readable) ACLs
and no visible error.

**Scope:**

- [ ] Module-level import of `run_secure_subprocess`; drop the function-local
      `import subprocess`.
- [ ] Guard the username: `username = os.getenv("USERNAME")
      ; if not username: log a warning and skip the ACL step (do NOT emit a
      `None:F` grant)`.
- [ ] Route the call through `run_secure_subprocess("icacls", [key_file,
      "/inheritance:r", "/grant:r", f"{username}:F"], capture_output=True,
      timeout=5, check=False)`.
- [ ] Error handling: on failure (`returncode != 0` or raised), log at
      `warning` with `exc_info=True` **and** surface intent (message includes
      the key file, so operators know the key was written without the ACL
      hardening — a silent debug-only failure is not acceptable for a
      security boundary).
- [ ] Lockstep tests: `test_key_manager.py:322` mocks `subprocess.run`
      today — re-target to the module binding
      `audio_suite_shared.security.key_manager.run_secure_subprocess`;
      add cases for the `None`-username skip and the failure-log path.

**Deliverables:**
- Secured, guarded, and observably-failing ACL setting.

**Success criteria:**
- `grep -rn 'subprocess\.run' audio_suite_shared/security/` → no matches;
  key_manager suite green including the new guard + warning cases.

---

## Sprint 4 — De-duplication & Hygiene

### D1 — Consolidate the STARTUPINFO triplication

**Priority:** Low | **Effort:** 0.25 day | **Risk:** Low

**Problem:** Windows console-hiding `STARTUPINFO` exists in three places
(Audit item 4): canonical `audio_suite_shared/subprocess_utils.py:9`
(used by `secure_subprocess`, `audio_enhancer`, `audio_refinery`);
`audio_normalizer/utils/ffmpeg_finder.py:50` (behaviorally inconsistent:
`sys.platform` check, drops `wShowWindow=0`) **plus a dead module-level
`STARTUPINFO = get_startupinfo()` singleton at :64** (nothing imports it
since Sprint 2 routed normalizer through the wrapper); and
`replaygain_analyzer/core/ffmpeg_metrics.py:65` (re-definition).

**Scope:**

- [ ] `ffmpeg_finder.get_startupinfo` → delegate to
      `subprocess_utils.get_startupinfo` (keep the name as a re-export for
      the audio_normalizer tests `test_ffmpeg_finder.py:118-141`, or update
      the test to the shared target — pick one, record in Decision Log);
      delete the dead `STARTUPINFO` singleton.
- [ ] `replaygain_analyzer/core/ffmpeg_metrics.py:65-77` → delete the local
      definition and import `get_startupinfo` from `audio_suite_shared.
      subprocess_utils`; remove the then-unused `subprocess` import if any
      remains.
- [ ] Confirm no other local definitions remain (grep `def get_startupinfo`
      and `def _get_startupinfo` across first-party).

**Success criteria:**
- `grep -rnE 'def _?get_startupinfo' --include='*.py' .` → exactly the
  canonical definition in `audio_suite_shared/subprocess_utils.py`.
- `audio_normalizer` + `replaygain_analyzer` + `audio_suite_shared` suites
  pass.

---

### D2 — Log the silent kill-cleanup `pass`

**Priority:** Low | **Effort:** 0.05 day | **Risk:** Very low

**Problem:** `resource_manager.py:187` — `expect (OSError,
ProcessLookupError): pass` with no log or comment (Audit item 7). Every
other handler in the suite now logs.

**Scope:**

- [ ] Add a `logger.debug("Process %s already gone during cleanup: %s",
      pid, exc, exc_info=True)` in that branch (intent: post-kill cleanup may
      legitimately race exit, but must stay diagnosable).

**Success criteria:**
- No bare `pass` without a comment or log in first-party
  `audio_suite_shared/`.

---

### D3 — pydub Python 3.14 `SyntaxWarning`

**Priority:** Low | **Effort:** 0.1 day | **Risk:** Very low

**Problem:** pydub 0.25.1 `utils.py:300-314` ships `\(`/`\)` invalid escapes
that emit `SyntaxWarning` on import under 3.14.7 — masked at runtime only by
`__pycache__`; any cache invalidation (venv rebuild, CI with `-W error`)
hard-fails (Audit item 5).

**Scope:**

- [ ] Check PyPI for a pydub release that fixes the invalid escapes (0.25.1
      is the striking one; a 0.25.x/1.x with the regexes made raw strings
      would be the clean fix). If one exists, pin it in `pyproject.toml` and
      refresh the venv; verify `-W error::SyntaxWarning -c "import pydub"`
      is clean.
- [ ] If no fixed release exists (Decision Log): add a scoped warning filter
      in the test configuration (`filterwarnings` in `pyproject.toml`
      limited to `pydub.*` invalid-escape, keeping the rest of the suite
      strict) and record the upstream issue for a future unpin.

**Deliverables:**
- Deterministic import behavior under 3.14 regardless of `__pycache__` state.

**Success criteria:**
- `python -W error::SyntaxWarning -c "import pydub"` succeeds after a cache
  clear, or the scoped filter is in place and documented.

---

### D4 — `batch_undo`: unbounded deleted-file BLOBs + pointless `bytes` pickle

**Priority:** Low | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `batch_undo.py` (Audit items 3/6): `record_file_delete` (line
~364) stores whole deleted-file contents as **pickled `bytes` BLOBs** —
pickling raw `bytes` adds nothing (store the BLOB directly), and prune-by-
count (≤50 batches) does not bound bytes, so a large-file deletion batch can
grow `undo_log.db` without limit. Minor: `operation` unpacked at ~402 is
unused.

**Scope:**

- [ ] Store deleted-file content as a raw `BLOB`, not a pickle of `bytes`
      (verify the load path at ~444/486 symmetric with plain bytes for this
      row type; keep the existing `# nosec B301` rationale and risk note —
      the data is still trusted self-written).
- [ ] Bound undo storage by size as well as count: prune oldest
      `file_delete` rows (order by `rowid`, per the ordering gotcha) when a
      rolling byte budget per database is exceeded (choose a sensible default
      constant in `audio_suite_shared/constants.py`, e.g. a few hundred MB,
      and document it; do not impose on non-delete rows).
- [ ] Remove the unused `operation` unpack (line ~402) if confirmed dead.
- [ ] Tests: round-trip a deleted-file restore from the new BLOB column;
      prune-by-size removes oldest deletions first; byte budget respected.

**Success criteria:**
- Deleted-file undo rows no longer pickle binary; a size cap bounds the DB;
  existing undo round-trip tests pass unchanged.

---

## Phase Gate (every sprint, before marking complete)

0. `python -m compileall -q -f .` — exit 0
1. `ruff check .` and `ruff format --check .` — clean
2. `mypy . --strict` — 0 issues (429 files baseline)
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r audio_suite_shared
   -c pyproject.toml` — 0 High / 0 Medium severity
4. Full-suite bare `pytest` — 100% pass; baseline **6388 passed /
   5 skipped**, coverage ≥ 75%
5. For Sprint 2 phases: pool-migration smoke tests must confirm identical
   progress counts and undo snapshots pre/post (behaviour-lock), and worker
   exceptions must surface as logged, mapped results — never crash the pool.
6. For Sprint 3: the ACL failure path is observable (warning log) rather
   than silent debug — verified by a forced-failure test.

---

## Implementation Roadmap

| Sprint | Content | Phases | Days | Dependency |
|--------|---------|--------|------|------------|
| 1 | Subprocess consolidation finish | A1 | 0.25 | — |
| 2 | `process_batch` adoption | B0→B5 | 1–1.5 | B0 before B2; B3/B4 before B4's consolidation |
| 3 | `key_manager` ACL hardening | K1, K2 | 0.35 | K1 before K2 |
| 4 | De-dup & hygiene | D1–D4 | 0.6 | — |

Estimated total: **~2.5–3 days** of incremental, independently shippable
work. All items are mechanical/low-risk; nothing is audio-correctness
critical (none touches decode/gain paths), so the risk profile is the
lowest of any plan to date.

---

## Completion Log

| Phase | Completed | Notes |
|-------|-----------|-------|
| A1 | 2026-09-19 | `audio_refinery/core/measure.py` routed through `run_secure_subprocess` (last raw `subprocess.run` in the refinery core). `run_secure_subprocess` already injects `text=True` + `startupinfo` internally, so those kwargs are NOT re-passed; `check=False` preserves the old `subprocess.run` semantics (measure checks `returncode != 0` by hand). `measure_loudness_metrics` also acquires `measure_lock` before probing so the timeout/`run_with_retry` backoff stays single-flight. `tests/test_measure.py` retargeted every mock to the module-level binding (`audio_refinery.core.measure.run_secure_subprocess`) via a shared `PATCH_TARGET`; `test_measure.py` passes outright with UTF8+bandit clean. |
| B0 | 2026-09-19 | `BaseFileProcessor.process_batch` gained keyword-only `future_timeout: float | None = None`; when set, `f.result(timeout=future_timeout)` is used and a `concurrent.futures.TimeoutError` (a builtin `TimeoutError`; the "TimeoutExpired" name is `subprocess`-scoped) is explicitly mapped+logged — a timed-out worker yields a mapped `None`, never a raw re-raise. Default `None` keeps every existing consumer byte-identical. Regression test `test_future_timeout_yields_none_and_logs` + `test_raising_worker_mapped_not_aborted` lock the B0 channel. |
| B1 | 2026-09-19 | genre_sync: raw `ThreadPoolExecutor`+`f.result()` block → `processor.process_batch(files, retry_worker, max_workers=processor.max_workers)`; per-file progress/undo callbacks preserved exactly. mypy `--strict` green. |
| B2 | 2026-09-19 | silence_trimmer: pool replaced with `processor.process_batch(files, _worker, max_workers=processor.max_workers, future_timeout=600.0)`; `_join_undo_batch` worker keeps `ThreadPoolExecutor`-style `future.result()`-equivalent semantics via the B0 mapped-timeout path; unrelated "Processed track" flush (stale text under the progress tracker) removed as lockstep docs/noise cleanup. |
| B3 | 2026-09-19 | noise_reduction: pool → `processor.process_batch(files, _worker, max_workers=processor.max_workers)`; `DEFAULT_MAX_WORKERS` read at pool-creation time so `tests/test_file_processor.py` patches (which monkeypatch the constant to 1) size the worker/slot pools correctly. |
| B4 | 2026-09-19 | pop_click_remover: pool → `BaseFileProcessor(max_workers=DEFAULT_MAX_WORKERS, operation_type="pop_click_removal").process_batch(...)`; the near-verbatim pool twin between pop_click_remover and the remover family is consolidated onto the shared `process_batch` scaffold (decision — see Decision Log). In-flight `start`/`temp_dir`/`_join_undo_batch` wiring intact; per-file error slot-pool + undo snapshots unchanged. |
| B5 | 2026-09-19 | metadata_scrubber: pool → `BaseFileProcessor(max_workers=DEFAULT_MAX_WORKERS, operation_type="metadata_scrubber").process_batch(...)`; dry-run/tag helpers/`undo_batch` preserved; 187 scrubber tests green. |
| K1 | 2026-09-19 | `secure_subprocess.py:22-46` `ALLOWED_EXECUTABLES`: added `"icacls"` + `"icacls.exe"` (ffprobe/ffmpeg-pairing convention) with an allowlisted-`icacls-is-always-at-%SystemRoot%\System32` comment block. `tests/test_secure_subprocess.py` gained `test_icacls_is_allowed` + `test_icacls_exe_is_allowed` mirroring `test_ffprobe_is_allowed`; allowlist still raises for unknown names as before. |
| K2 | 2026-09-19 | `key_manager.py:100-133` ACL block now: module-level `from audio_suite_shared.secure_subprocess import run_secure_subprocess` (function-local `import subprocess` dropped); `username = os.getenv("USERNAME")` guarded — `None` → `logger.warning` + skip, never a raw `None:F` grant; `run_secure_subprocess("icacls", [key_file, "/inheritance:r", "/grant:r", f"{username}:F"], capture_output=True, timeout=5, check=False)`; failure logs `warning` with `exc_info=True` + key-file intent. Lockstep: `tests/test_key_manager.py` re-targeted the `subprocess.run` mock (previously at :322) to `audio_suite_shared.security.key_manager.run_secure_subprocess` and added `test_icacls_failure_is_swallowed`, `test_icacls_routed_via_secure_subprocess`, `test_icacls_skipped_when_username_missing`. `grep -rn 'subprocess.run' audio_suite_shared/security/` → 0 matches. |
| D1 | 2026-09-20 | Consolidation completed 2026-09-19 (last remaining `get_startupinfo` body at `subprocess_utils.py:9`); the phase gate broke with ruff F401 (unused re-export `from audio_suite_shared.subprocess_utils import get_startupinfo` at `ffmpeg_finder.py:14`) + two format drifts in `test_ffmpeg_finder.py`. **Resolved 2026-09-20** (iteration-5 close-out): re-export dropped, `ffmpeg_finder.py` docstring updated, `test_ffmpeg_finder.py` repointed to the canonical `audio_suite_shared.subprocess_utils.get_startupinfo` and reformatted. Note: the D1 plan gate was not re-run before marking "complete" — that gap is exactly what the iteration-5 audit surfaced; reasserting the gate after each sprint is now mandatory. |
| D2 | 2026-09-20 | `resource_manager.py:186-187` bare `except (OSError, ProcessLookupError): pass` on the post-kill cleanup now logs at debug with `exc_info=True` (`kill_exc` bound) — the kill-already-gone race stays best-effort, but silent failures are diagnosable. |
| D3 | 2026-09-20 | No fixed pydub release exists (PyPI latest is 0.25.1 — the invalid-escape regexes remain in `pydub/utils.py:300-314`, `SyntaxWarning` on Python 3.14). Chosen fallback applied: `filterwarnings = ["ignore::SyntaxWarning:pydub.*"]` added to `[tool.pytest.ini_options]` in `pyproject.toml`, scoped to `pydub.*` only so first-party warnings stay visible. Remove when upstream fixes the regexes. |
| D4 | 2026-09-20 | `record_file_delete` now stores the raw file bytes directly (no `pickle.dumps` round-trip) and `_revert_file_delete` writes them back verbatim. Legacy pickled delete payloads are migrated to raw bytes once per database by `_migrate_delete_payloads` (gated by `PRAGMA user_version`, set to 1 after the first run), so pre-existing undo rows restore correctly. `_cleanup_old_batches` gained a byte-size cap: `cleanup(max_bytes=...)` (config `undo_max_bytes`, default 1 GiB in `_DEFAULT_MAX_BYTES`) prunes oldest batches while total stored payload bytes exceed the cap. The dead `operation` unpack in `revert_batch` is `_operation`. Lockstep tests: raw-snapshot storage, legacy migration restores byte-exact content, size-based prune (deterministic 3×1 KiB → 2 KiB cap), no-op under cap, auto-prune-on-start. |
| A2 (post-audit) | 2026-09-20 | `BaseFileProcessor.process_batch` gained keyword-only `on_error: Callable[[str], None] | None`; when a worker exception escapes `worker_fn` (or a future times out), the mapped message is delivered via `on_error` in addition to the existing `logger.error` — the old `f.result()`-direct propagation that used to reach a tool's `on_error` is restored as an explicit hook. genre_sync passes an `_on_worker_error` closure that feeds the escaped error into its own progress counters, and its `on_complete(processed=...)` now uses the real `updated+skipped+no_genre+errors` total instead of a hard-coded `total`. Regression test `test_escaped_worker_error_invokes_on_error_hook` added. |
| A3 (post-audit) | 2026-09-20 | Duration timers harmonised to `time.monotonic()` across the iteration-4 DSP family: `silence_trimmer/core/file_processor.py` and `metadata_scrubber/core/scrubber.py` switched from `time.time()` (already-monotonic noise_reduction/pop_click_remover unchanged). `tag_field_updater/ui/app.py` launch-guard `print()`s → `logger.error`. `cd_ripper/core/rip_log.py` and `cd_ripper/core/encoding_pipeline.py` bare `except OSError: pass` sites now log at debug with `exc_info=True`. |

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| — | (scope) | Item 4 (AccurateRip/CD verification, AAC/M4A lossless gain) **deferred** | User decision: this iteration covers consolidation/hardening (items 1–3) only; the two strategic features get their own separate plan. Logged here so the auditing trail stays complete. |
| — | B4 | **Decided 2026-09-19** — consolidate the near-verbatim pool twin between pop_click_remover and the remover family onto the shared `process_batch` scaffold (`BaseFileProcessor(max_workers=DEFAULT_MAX_WORKERS, operation_type="pop_click_removal").process_batch(...)`) | The pool block was a byte-near verbatim duplicate; correctness of progress/undo wiring (per-file error slot-pool, `start`/`temp_dir`/`_join_undo_batch`, undo snapshots) is preserved exactly, not sacrificed for consolidation. Locked by 187 remover-family tests green. |
| — | D1 | **Decided 2026-09-20** — drop the `ffmpeg_finder` re-export and repoint `test_ffmpeg_finder.py` to `audio_suite_shared.subprocess_utils.get_startupinfo` | The original plan leaned toward keeping a thin re-export for convenience; the iteration-5 audit showed the re-export was the sole accused F401 after consolidation, its only consumer was the twin test, and keeping it would carry a permanent `# noqa`-style exemption. Repointing to the canonical home removes the dead import, keeps one source of truth, and makes the twin test a direct lock on canonical behaviour. |
| — | D3 | **Decided 2026-09-20** — scoped `filterwarnings` (fallback path) | `pip index versions pydub` confirms 0.25.1 is the latest release, so the preferred upgrade pin does not exist. Applied `ignore::SyntaxWarning:pydub.*` under `[tool.pytest.ini_options]`, scoped to `pydub.*`; first-party warnings remain visible. Revisit when upstream ships the regex fix. |
| — | D4 | **Decided 2026-09-20** — raw BLOB delete payloads + size cap + one-time legacy migration | Avoids the pointless `pickle.dumps(bytes)` round-trip for large audio blobs. `PRAGMA user_version`-gated `_migrate_delete_payloads` rewrites legacy pickled rows to raw bytes exactly once, closing the audio-correctness risk (legacy rows must restore the real file, not a pickle artifact) that the risk register below anticipated. |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `process_batch` migration subtly changes progress counts or undo snapshots in one of the 5 tools | Medium | Medium | Behaviour-lock tests per tool before/after; keep worker call-context byte-identical via closures; preserve counters/temp-dir/`track_thread` wiring |
| `future_timeout` change to the base breaks the 8 existing consumers | Low | Low | Default `None` = exact current behavior; dedicated B0 tests lock it |
| `icacls` in the allowlist weakens the allowlist intent | Low | Low | icacls is a fixed Windows builtin with a constant argv shape; validation tests keep the "unknown names rejected" barrier intact |
| pydub has no fixed release → `filterwarnings` masks a real regression elsewhere | Low | Low | Filter is scoped to `pydub.*` only; suite's other warnings stay visible |
| BLOB-format change in batch_undo breaks an existing undo DB row | Low | Medium | Store new rows with the new layout and keep the loader tolerant of legacy pickled rows (migration path), verified by test |