# Audit Remediation Plan — Iteration 3 — AudioSuite-Pro

**Source:** Audit Report 3 (2026-09-18), Part IV code-quality findings
**Status:** Active
**Last Updated:** 2026-09-18
**Scope:** Correctness hardening, security-standard alignment, consistency,
and a governance change to AGENTS.md so working-code defects are resolved
when discovered. All Ph P?? items below map 1:1 to Part IV of Audit 3.
Sprint 4 (AGENTS.md) applies a wording **pending user confirmation**.

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

## Sprint 1 — Audio Correctness Hardening

> The audit's only residual *correctness* finding lives in
> `lossless_gain.py`. Per the governing principle (Sprint 4), these are
> resolved now, not ticket deferred.

### P1 — CRC protection bit (Part IV finding 1)

**Priority:** High | **Effort:** 0.5 day | **Risk:** Low

**Problem:** `_is_valid_mpeg_frame` (`audio_suite_shared/lossless_gain.py:420`)
validates sync/version/layer but never checks the protection bit (bit 16 of
the header). A CRC-protected MP3 inserts a 16-bit CRC after the header,
shifting every side-info offset by 16 bits — the walker would silently
mis-modify `global_gain` and corrupt the file. The module docstring promises
blanket MPEG-1/2/2.5 support with no caveat.

**Scope:**

- [x] Inspect the protection bit in `_is_valid_mpeg_frame` /
      `_walk_frames`: bit 16 == 0 ⇒ CRC block present ⇒ add 16 bits to every
      side-info offset for that frame.
- [x] If CRC frames cannot be safely supported, **reject them** with
      `AudioFormatError` (file unchanged, clear error) rather than silently
      mis-modifying. Rejecting is acceptable — LAME/FHG encoders do not emit
      CRC by default — but the docstring's support claim must be narrowed to
      match.
- [x] Generate a CRC-protected MP3 fixture (ffmpeg `-c:a libmp3lame` emits
      CRC flags when the encoder sets protection; if not obtainable via
      ffmpeg, hand-craft one frame's protection bit in a small fixture) and
      add a decode-based test asserting the file is either handled correctly
      or rejected cleanly — never silently corrupted.
- [x] Update the module docstring's support matrix to state CRC behaviour.

**Deliverables:**
- Protection-bit handling (offset-adjust **or** reject) in the walker.
- Decode-based regression test for the CRC case.
- Docstring support-matrix update.

**Success criteria:**
- A CRC-protected MP3 is either corrected with the +16-bit offset or rejected
  with `AudioFormatError`; under no circumstance is the audio silently
  corrupted.
- All existing lossless_gain tests still pass.

---

### P2 — Free-format frames: explicit handling or documented limitation

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Problem:** `bitrate_idx == 0` (free-format) makes `_frame_size` return 0,
so `_walk_frames` advances only 4 bytes and falls into random byte scanning.
Free-format MP3s are rare but the current behaviour is undefined and
silent.

**Scope:**

- [x] Detect free-format frames and raise `AudioFormatError` (preferred — a
      file we cannot scan must not be silently mis-gained), **or**
      explicitly document the limitation in the module docstring if free
      format is truly unsupported.
- [x] The walker should already have visited prior frames before encountering
      free format; the raise prevents partial modification. Confirm
      `_modify_mp3_gains` applies the delta frame-by-frame on a buffer read
      once, so a mid-file raise leaves the on-disk file untouched.

**Deliverables:**
- Clear reject-or-document behaviour for free-format frames.
- Test asserting the reject path (or documented skip).

**Success criteria:**
- A free-format fixture raises `AudioFormatError` and the file is unchanged
  on disk; or the docstring explicitly flags free format as unsupported.

---

### P3 — Undo snapshot ordering

**Priority:** Low | **Effort:** 0.1 day | **Risk:** Very low

**Problem:** `apply_track_gain` records the undo snapshot
(`lossless_gain.py:311`) *before* confirming valid frames (raise at
:315–319). Inside an active undo batch, an invalid file still gets a
snapshot row for a file that never changed.

**Scope:**

- [x] Move the `record_tag_edit_snapshot` call to after the frame-walk
      validation succeeds (or skip the snapshot when `modified == 0`).

**Deliverables:**
- Snapshot recorded only for files that were actually modified.

**Success criteria:**
- Applying gain to an invalid MP3 inside an undo batch creates no snapshot
  row for that file.

---

### P4 — MPEG-2.5 decode test + measurement hygiene

**Priority:** Low | **Effort:** 0.25 day | **Risk:** Very low

**Problem:** `test_lossless_gain.py` never *decodes* an MPEG-2.5 (8000 Hz)
file despite the docstring claiming support; `_decode_rms_db` decodes the
same audio twice per measurement (raw pipe + `AudioSegment.from_file` just to
read `.channels`).

**Scope:**

- [x] Add a decode-based MPEG-2.5 test: 8000 Hz mono + stereo, apply +1.505 dB
      (1 unit), decode, assert per-channel RMS delta ≈ expected on both
      channels.
- [x] Refactor `_decode_rms_db` to derive channel count from one ffprobe of
      the same decode instead of a second full decode.

**Deliverables:**
- MPEG-2.5 decode regression test.
- Single-decode RMS measurement helper.

**Success criteria:**
- MPEG-2.5 decode test passes; helper performs one decode per measurement.

---

## Sprint 2 — Security-Standard Alignment

> Part IV finding 2: four `audio_suite_shared`-adjacent call sites bypass
> `run_secure_subprocess` (raw `subprocess.run`/`Popen`). Low real risk
> (argv-list, `shell=False` by default) but a declared-standard
> inconsistency. Route them through the allowlisted wrapper.

### S1 — music_format_converter

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Low

**Scope:**

- [x] Replace raw `subprocess.run` at
      `music_format_converter/core/file_processor.py:63` (ffprobe probe),
      `:162`, and `:278` (ffmpeg) with `run_secure_subprocess(
      "ffprobe" | "ffmpeg", ...)` from `audio_suite_shared.secure_subprocess`
      (calls are already argv-list and `startupinfo`-safe; the wrapper adds
      the executable allowlist + argument validation that the standard
      mandates).
- [x] Check whether `ffmpeg_params.py` or other converter modules hold
      further raw calls from the same pattern (grep `subprocess.` across
      `music_format_converter/`).
- [x] Update the converter's tests if they patch `subprocess.run` directly —
      re-target to `audio_suite_shared.secure_subprocess.run_secure_subprocess`
      at the importing binding (AGENTS.md §7 rule).

**Deliverables:**
- All converter subprocess calls route through the secure wrapper.
- Tests patched in lockstep.

**Success criteria:**
- `grep -rn 'subprocess\.' music_format_converter/` → no raw runs outside
  the wrapper import.
- Full converter + shared suites pass.

---

### S2 — audio_normalizer

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Scope:**

- [x] Route `audio_normalizer/core/loudness.py:61` (ffmpeg measurement) and
      `audio_normalizer/core/normalizer.py:140` (ffmpeg encode) through
      `run_secure_subprocess`.
- [x] Update any direct `subprocess.run` patches in the normalizer suites.

**Success criteria:**
- `grep -rn 'subprocess\.' audio_normalizer/` → shared wrapper only.

---

### S3 — replaygain_analyzer

**Priority:** Medium | **Effort:** 0.25 day | **Risk:** Low

**Scope:**

- [x] Route `replaygain_analyzer/core/ffmpeg_metrics.py:101` through
      `run_secure_subprocess`.
- [x] Audit the rest of `replaygain_analyzer/` for further raw calls; update
      test patches in lockstep.

**Success criteria:**
- `grep -rn 'subprocess\.' replaygain_analyzer/` → shared wrapper only.

---

### S4 — ui_common Popen

**Priority:** Medium | **Effort:** 0.1 day | **Risk:** Very low

**Scope:**

- [x] Replace the raw `subprocess.Popen(["open"|"xdg-open", log_file])` at
      `audio_suite_shared/ui_common.py:48-50` with the existing, already-correct
      `platform_utils` open helper (`platform_utils.py:42,173` uses the secure
      wrapper) — or call `run_secure_subprocess("xdg-open"/"open", ...)` and
      drop the branch duplication.
- [x] Re-point the `ui_common` tests (`test_ui_common.py:88-105`) that patch
      `ui_common.subprocess.Popen`.

**Success criteria:**
- No raw `Popen` for `open`/`xdg-open` outside `secure_subprocess` /
  `platform_utils`.
- `ui_common` tests pass.

---

## Sprint 3 — Consistency & Single Source of Truth

> Part IV findings 3–7.

### C1 — `DEFAULT_MAX_WORKERS` adoption (finding 3)

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Low

**Problem:** Four tools re-define `NUM_WORKERS: int = 4` locally instead of
importing `DEFAULT_MAX_WORKERS` — the exact divergence `constants.py` was
built to prevent: `audio_enhancer/core/file_processor.py:56`,
`audio_refinery/core/file_processor.py:38`,
`noise_reduction/core/file_processor.py:58`,
`pop_click_remover/core/file_processor.py:61`. `replaygain_analyzer` also
hardcodes `max_workers=4` in its `process_batch` call
(`.../file_processor.py:354`-area, per the audit).

**Scope:**

- [x] Replace each local `NUM_WORKERS` with
      `from audio_suite_shared.constants import DEFAULT_MAX_WORKERS`; update
      the module and `app.py` imports that consumed the local name.
- [x] Replace the hardcoded `max_workers=4` in replaygain with
      `DEFAULT_MAX_WORKERS` (or `processor.max_workers`, consistent with the
      base class).
- [x] Widen `test_constants.py` (Part IV finding 7) so the consumer-reference
      class assert-imports **all** of the constants that have consumers —
      `DEFAULT_MAX_WORKERS` included — so a redefinition cannot silently
      regress again without failing the guard.

**Success criteria:**
- `grep -rn 'NUM_WORKERS' --include='*.py' audio_enhancer audio_refinery
  noise_reduction pop_click_remover replaygain_analyzer` → zero matches.
- `test_constants.py` consumer assertions cover `DEFAULT_MAX_WORKERS`.

---

### C2 — music_format_converter uses `process_batch` (finding 5)

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Medium

**Problem:** `music_format_converter/core/file_processor.py:528-553`
re-rolls a raw `ThreadPoolExecutor` and calls `f.result()` unguarded (no
`WORKER_TIMEOUT_SECS`), instead of the base class's `process_batch` the
sibling tools use.

**Scope:**

- [x] Convert the raw pool to
      `self.process_batch(files, worker_fn, max_workers=..., progress_callback=...)`
      — `process_batch` is now generic
      (`list[_T]` / `Callable[[_T], object]`, `file_processor_base.py:493`)
      so the converter's per-file worker slots in directly.
- [x] Preserve the converter's existing progress/undo/count semantics
      exactly; add timeout coverage via the base's error mapping.
- [x] Behaviour-lock tests: conversion pipelines and undo snapshots behave
      identically pre/post.

**Success criteria:**
- No raw `ThreadPoolExecutor` in `music_format_converter/core/file_processor.py`.
- Converter suite passes with no semantic change.

---

### C3 — audio_refinery silent handlers (finding 4 + audit context)

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Low

**Problem:** `audio_refinery/core/pipeline.py:104-105` swallows all VBR-probe
exceptions with `except Exception: pass` (no log), the outer fallback at
`:108` is also broad and un-logged, and `:427` ignores `OSError` on temp-file
unlink without logging. `audio_refinery/core/measure.py` holds five
`except Exception as e:` sites (lines 102, 170, 231, 314, 400) that need a
narrow-and-log review.

**Scope:**

- [x] `pipeline.py:104-105`: log at `debug` with `exc_info=True` and keep the
      graceful fallback (VBR detection must stay best-effort), narrowing to
      the actual mutagen/OSError types if feasible.
- [x] `pipeline.py:108`: keep as a defensive outer fallback but log the
      exception with `debug`/`exc_info=True`.
- [x] `pipeline.py:427`: log `OSError` on unlink at `debug` (intent: silent
      temp-cleanup is fine, but diagnosable).
- [x] Review all five `measure.py` catches: narrow types where the call site
      has a tight contract; where a broad net must stay, log with
      `exc_info=True` and document why (comment).
- [x] Add/update tests only where a test previously relied on a swallowed
      exception; assert the new log path via `caplog` where cheap.

**Success criteria:**
- `grep -rnE 'except Exception' audio_refinery/` → every remaining handler has
  a logged reason and either a type-list or a rationale comment; zero bare
  `pass` blocks without logging.
- Full refinery suite passes; ruff/mypy/bandit green.

---

### C4 — Magic timeout literals (finding 6)

**Priority:** Low | **Effort:** 0.25 day | **Risk:** Very low

**Problem:** Raw `timeout=` literals (30/120/300) scattered across tools
instead of `WORKER_TIMEOUT_SECS`/`CPU_WORKER_TIMEOUT_SECS`.

**Scope:**

- [x] Grep all first-party `timeout=` literals
      (`grep -rn 'timeout=' --include='*.py' audit-roots`) and map each to
      an existing named constant or a new one in `constants.py` (only add a
      constant if the value is genuinely shared; single-call-site values may
      stay inline when semantically distinct, but the choice must be
      documented in the plan's Decision Log).
- [x] Free-format/snapshot items from P2/P3 are already covered above.

**Success criteria:**
- Every shared-worthy timeout resolves to a named constant; the rest are
  justified in the Decision Log.

---

## Sprint 4 — Governance: AGENTS.md Update

### G1 — "Defects are resolved when discovered" clause

**Priority:** High (policy) | **Effort:** 0.1 day | **Risk:** None

**Context:** This iteration and the prior two shipped exactly one class of
defect the process let through: `lossless_gain` modified audio wrongly for
two release iterations because (a) fixes were scoped to plan phases rather
than resolved on discovery, and (b) tests verified internal consistency
(read-back of the same field) instead of the actual audio outcome. The
following clause prevents both failure modes.

**Proposed wording** (placed in the project `AGENTS.md`, in the "Verification
Tooling" section after the existing "Failing tests must be resolved — never
shipped" bullet, or as a new top-level section if preferred — confirm
placement with the user at execution):

```markdown
**Defects are fixed when discovered — never deferred.** A bug found during
development, review, an audit, or a test run must be resolved in the same
change that found it, with a regression test in lockstep. Deferral to a
later phase or a "ticket" is only acceptable for new-feature backlog items —
never for defects in working code.

**Audio correctness is release-blocking.** This suite manipulates audio
data: any defect that could corrupt, mis-normalize, mis-tag, or incorrectly
convert audio (global_gain rewrites, LUFS normalization, sample-rate/bit-depth
conversion, analysis, tag writes) is the highest-priority fix class. Validating
such fixes requires tests that verify the **actual audio outcome** — decode
the result and measure per-channel RMS/loudness — not tests that read back
the same internal state the code just wrote. Self-consistent field read-back
cannot detect corruption (see the lossless_gain stereo-offset bug, iterations
1–2 in PLAN_audit_remediation.md / PLAN_iteration2_remediation.md).
```

**Scope:**

- [x] Present the wording to the user, confirm section placement, then apply
      to `AGENTS.md`.
- [x] On user approval, also mirror the same principle in the global
      `C:\Users\wilte\.config\opencode\AGENTS.md` §6/§7 as a
      generally-applicable lesson (audio-outcome verification + resolve-at-
      discovery), per the session-wrap-up convention.

**Deliverables:**
- Project `AGENTS.md` updated (approved wording).
- Global `AGENTS.md` updated optionally (approved wording).

**Success criteria:**
- The clause is present in `AGENTS.md`; wording and placement confirmed by
  the user before application.

---

## Phase Gate (every sprint, before marking complete)

0. `python -m compileall -q -f .` — exit 0
1. `ruff check .` and `ruff format --check .` — clean
2. `mypy . --strict` — 0 issues (429 files baseline)
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r audio_suite_shared -c pyproject.toml` — 0 High / 0 Medium severity
4. Full-suite bare `pytest` — 100% pass; current baseline **6369 passed / 5 skipped**
5. For Sprint 1 phases: any end-to-end audio validation must route through
   the suite's own decode-and-measure path (ffmpeg), and the pre-fix code
   must be confirmed failing the new tests where the phase claims a
   correctness fix ("test the tests").

---

## Implementation Roadmap

| Sprint | Content | Phases | Days | Dependency |
|--------|---------|--------|------|------------|
| 1 | Audio correctness hardening | P1→P4 | 1–1.5 | — |
| 2 | Security-standard alignment | S1–S4 | 1 | — |
| 3 | Consistency & single source of truth | C1–C4 | 1.5 | S1 (converter touched by both C2 & S1 — do S1 first) |
| 4 | Governance (AGENTS.md) | G1 | 0.1 | user confirmation |

Estimated total: **~3.5–4 days** of incremental, independently shippable work.

---

## Completion Log

| Phase | Completed | Notes |
|-------|-----------|-------|
| P1 | | |
| P2 | | |
| P3 | | |
| P4 | | |
| S1 | | |
| S2 | | |
| S3 | | |
| S4 | | |
| C1 | | |
| C2 | | |
| C3 | | |
| C4 | | |
| G1 | 2026-09-18 | Applied to project `AGENTS.md` in the Verification Tooling section (after the "Failing tests must be resolved" bullet). Wording confirmed by user. Global AGENTS.md mirror not requested. |

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| — | P1 | REJECT CRC-protected MP3s with `AudioFormatError` (bit 16 `0x00010000`); free-format (bitrate index 0) also rejected | No trustworthy CRC fixture with the +16-bit offset-shift was obtainable, so the offset-adjust path could never be proven; rejecting with a clear, specific error is safer than silently mis-decoding. Implemented with lossless_gain decode guard + `test_decode_gain_*_rejects_crc` regression tests. |
| — | C4 | Mapped shared timeouts to named constants: `300` → `WORKER_TIMEOUT_SECS` (music_format_converter `run_conversion` ffmpeg encode, replaygain `ffmpeg_metrics`); `600` → `CPU_WORKER_TIMEOUT_SECS` (mood_analysis `ProcessPoolExecutor` per-future wait). | Three call sites shared a genuine worker-scoped timeout; a named constant now keeps them in sync. |
| — | C4 | Remaining literals kept inline (single call site, semantically distinct): `30` sqlite busy-timeout (batch_undo), `30` cd_info probe (cd_ripper/disc.py), `10` ffmpeg -version probe (metadata_resolver), `5` ffmpeg -version probe (ffmpeg_check), `5` icacls ACL helper (key_manager), `30` ffprobe sample-fmt probe (converter), `120` loudnorm dry-run measurement (converter), `30` ffmpeg loudness probe (audio_refinery measure), `5` process terminate wait (resource_manager), `2.0` thread join (file_reorganizer), `3600` orchestrator cap (batch_orchestrator), `60` queue poll (mood cli), `600` silence-trim per-file generous cap on a ThreadPool (silence_trimmer — intentionally over `WORKER_TIMEOUT_SECS=300` for long trims, and not `CPU_WORKER_TIMEOUT_SECS` which is ProcessPool-documented). | Each is a platform/specific-purpose timeout where a shared constant would obscure the distinct intent; forcing one constant would mis-name them. |
| — | G1 | Placed in project AGENTS.md "Verification Tooling" section | Approved by user on creation; wording applied verbatim. Global AGENTS.md mirrored on approval in §7 (Test-Driven & Continuous Testing Rules) after "Zero-Failure Enforcement", generalised to any data-transforming domain. |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| CRC offset-adjust is incorrect without a reliable fixture | Medium | Medium | Default to reject-with-error if the fixture test is not conclusive; never ship an unproven offset path |
| S1–S3 wrapper migration breaks converter/normalizer/replaygain pipelines | Medium | Low | argv-list calls, no shell; keep `capture_output`/`check` semantics identical; full consumer suites + end-to-end convert/normalise smoke test at the gate |
| C2 (process_batch conversion) changes converter behaviour subtly | Low | Medium | Behaviour-lock tests first; keep progress/count/undo semantics identical |
| AGENTS.md wording rejected or placement preference differs | Low | Low | Wording is a proposal; adjust at user direction before applying |