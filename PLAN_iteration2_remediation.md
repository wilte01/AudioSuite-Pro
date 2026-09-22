# Audit Remediation Plan — Iteration 2 — AudioSuite-Pro

**Source:** Updated Audit (2026-09-18)
**Status:** Active
**Last Updated:** 2026-09-18
**Scope:** Fixes and polish identified by the re-audit of Iteration 1
(PLAN_audit_remediation.md, all 5 sprints complete). About 1.5–2 weeks of
incremental, independently shippable work.

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

## Sprint 0 — Critical: Lossless-Gain Correctness (Phase A)

> **Context.** The Iteration-1 re-audit (2026-09-18) empirically reproduced a
> correctness failure in `audio_suite_shared/lossless_gain.py`, the module
> behind `audio_normalizer --mode lossless`,
> `replaygain_analyzer --apply-gain`, and
> `music_format_converter --normalize-mp3`.
>
> Applying +6 dB to a LAME-192k **stereo** MP3 produced:
>
> ```
> DELTA:   L = −0.28 dB   R = −2.20 dB     (expected ≈ +6.0 dB on BOTH)
> ```
>
> Two independent bugs:
> 1. **Wrong side-info offsets for stereo.** `_global_gain_bit_offset`
>    (`lossless_gain.py:292`) returns bit 35 for MPEG-1 stereo and 37 for
>    MPEG-2/2.5 stereo; the correct values are **39** and **33**. Root cause:
>    MPEG-1 stereo's `scfsi` block is **8** bits (4 per granule × 2), not the
>    4 the code assumes, and MPEG-2/2.5 has **no scfsi at all** — the code
>    counts a spurious 4. Only the mono offsets (35/31) are correct.
> 2. **Only one of the frame's `global_gain` fields is modified** (`_modify`
>    in `_modify_mp3_gains`, `lossless_gain.py:465`). MPEG-1 stereo frames
>    carry **4** fields (2 channels × 2 granules), MPEG-1 mono **2**, LSF
>    stereo **2**. Only LSF mono (1 field, offset 31) is handled fully.
>
> The 37 existing tests never detect this: they read back the *same single
> field at the same wrong offset* the code writes (self-consistent), never
> test stereo vs mono, and never decode the output audio.
>
> **Sprint 0 complete (2026-09-18).** During validation two further latent
> bugs were found in the same module and fixed: `_side_info_size` was wrong
> for MPEG-1 mono and all LSF modes (Xing/Info skipping), and `_frame_size`
> used the MPEG-1 bitrate/sample-rate tables and 144-sample coefficient for
> MPEG-2 (the walker silently skipped every other frame in every LSF file).
> The planned A1 offset values (39/35/33/31) were also corrected during
> validation — see A1 below.

### A1 — Correct global_gain byte/bit offsets

**Priority:** Critical | **Effort:** 0.5 day | **Risk:** Low (once validated)

**Status:** Complete (2026-09-18) — with an important correction: the offsets
in the table below *replace* the ones this sprint originally planned
(39/35/33/31). The planned values were derived from the spec from memory and
were themselves wrong (they assumed private_bits=1 for MPEG-1 stereo, no
scfsi for MPEG-1 mono, and a 4-bit LSF scalefac_compress). Differential
decode probing (bump each side-info bit position ±1, decode with ffmpeg,
measure per-channel RMS) proved the real layout; every row also satisfies an
exact-fill identity (fields consume the side info exactly).

**Scope:**

- [x] Rewrite the offset logic (`_side_info_layout`,
      `audio_suite_shared/lossless_gain.py`) to match the real
      ISO 11172-3 / ISO 13818-3 Layer III side-info layout. Per-block fields:
      part2_3_length 12 + big_values 9 + global_gain 8 + scalefac_compress
      (4 MPEG-1 / **9 LSF**) + window_switching_flag 1 + branch (22 bits both
      variants) + preflag (1, MPEG-1 only) + scalefac_scale 1 +
      count1table_select 1 → constant block width 59 (MPEG-1) / 63 (LSF):

      | Frame type | main_data_begin | private | scfsi | first gg bit | stride | fields | exact fill |
      |---|---|---|---|---|---|---|---|
      | MPEG-1 stereo / joint / dual | 9 | 3 | 8 | **41** | 59 | 4 | 20+4×59=256 ✓ |
      | MPEG-1 mono | 9 | 5 | **4** | **39** | 59 | 2 | 18+2×59=136 ✓ |
      | MPEG-2 / 2.5 stereo / joint / dual | 8 | **2** | 0 | **31** | 63 | 2 | 10+2×63=136 ✓ |
      | MPEG-2 / 2.5 mono | 8 | **1** | 0 | **30** | 63 | 1 | 9+63=72 ✓ |

      Empirical validation: the all-frames ±1 bump at these offsets produces
      a clean ≈+1.505 dB lift on the expected channel in 100% of decoded
      windows (MPEG-1 stereo/mono on steady and transient-heavy content with
      window-switching frames; LSF/MPEG-2.5 stereo/mono at 22050/8000 Hz).
- [x] Unit-test the layout function directly for all 4 combinations
      (+joint/dual variants) with the validated values.

**Deliverables:**
- `_side_info_layout` (+`_side_info_size` corrected to 32/17 and 17/9) with a
  documented layout table; direct unit tests.

**Success criteria:**
- `_side_info_layout(0b11, 0b00) == (41, 59, 4)`, `(0b11, 0b11) == (39, 59, 2)`,
  `(0b10, 0b00) == (31, 63, 2)`, `(0b10, 0b11) == (30, 63, 1)`.
- Additional latent bugs found during validation and fixed in the same module:
  `_side_info_size` was wrong for MPEG-1 mono and all LSF modes (broke
  Xing/Info skipping); `_frame_size` used the 144-sample coefficient and the
  MPEG-1 bitrate/sample-rate tables for MPEG-2 (frame sizes ~2× too large —
  the walker skipped every other frame in every LSF file). VBRI is now
  checked at its fixed 32-byte offset instead of the Xing offset.

---

### A2 — Modify ALL global_gain fields per frame

**Priority:** Critical | **Effort:** 1–1.5 days | **Risk:** Medium

**Status:** Complete (2026-09-18).

**Scope:**

- [x] Replace the single-field `_modify` callback with a walker that visits
      **every** (granule, channel) block in each frame and adjusts that
      block's `global_gain`.
- [x] Resolved more favourably than the planned branch-parsing walker: the
      two window-switching branches are both exactly 22 bits wide, so the
      per-block stride is **constant** (59/63 bits) and no post-`global_gain`
      parsing is needed — `_walk_frames` now hands the callback the full list
      of `global_gain` bit offsets per frame (4/2/2/1 by frame type). Verified
      on transient-heavy content with wsf=1 frames: 0 failing decoded windows.
- [x] Decision: hand-rolled walker (see Decision Log) — no external code used.
- [x] Xing/Info/VBRI skipping kept (and fixed for mono/LSF via the corrected
      `_side_info_size` + dedicated VBRI offset).
- [x] 0–255 clamp and the shared `record_tag_edit_snapshot` undo call kept
      unchanged. `read_mp3_global_gains` now returns one value **per field**
      (all granules/channels) and `get_frame_count` counts frames directly;
      both are test-only APIs (consumers only use `apply_track_gain`).

**Deliverables:**
- `_walk_frames` yields every `global_gain` bit offset per frame;
  `_modify_mp3_gains` applies the delta to every field (counting a frame as
  modified when at least one field changed).

**Success criteria:**
- Frame fields visited per frame type: MPEG-1 stereo = 4, MPEG-1 mono = 2,
  LSF stereo = 2, LSF mono = 1. Verified by unit tests and by the decoded
  +6.02 dB per-channel result on every frame type.

---

### A3 — Decode-based regression tests

**Priority:** Critical | **Effort:** 1 day | **Risk:** Low

**Status:** Complete (2026-09-18).

**Scope:**

- [x] New decode-based test classes in `audio_suite_shared/tests/`
      `test_lossless_gain.py` that **decode output audio**, not just re-read
      fields (helpers `_make_tone_mp3` / `_decode_rms_db` drive ffmpeg):
  - [x] **Stereo symmetric**: dual-sine L/R MPEG-1 stereo, apply +6 dB,
        decode both channels, assert both RMS ≈ +6.0 ± 0.5 dB.
  - [x] **Joint stereo**: same assertion in joint-stereo mode.
  - [x] **Mono**: MPEG-1 mono and MPEG-2 22050 Hz LSF mono.
  - [x] **Both-channel balance**: |ΔL − ΔR| < 0.5 dB.
  - [x] **MPEG-2**: 22050 Hz stereo, equal per-channel gain.
  - [x] **Clamp**: +1000 dB saturates every field at 255 and the output still
        decodes without exceptions.
  - [x] **Idempotence / no re-encode**: file size unchanged after gain write;
        every field moves by exactly the same delta.
  - [x] Negative-gain symmetric check; Xing/Info skip check.
- [x] Explicit `stereo`/`mono`/`joint`/`mpeg2` words in test names.

**Deliverables:**
- 12 decode-based regression tests (70 tests total in the module's suite).

**Success criteria:**
- Every test passes with the corrected walker.
- Run the pre-fix implementation against the same checks: confirmed FAIL
  (per-channel deltas −0.37 / −1.98 / +0.85 dB instead of +6.0 across
  MPEG-1 stereo/mono and LSF — "test the tests" documented).

---

### A4 — Downstream validation & release gate

**Priority:** High | **Effort:** 0.5 day | **Risk:** Low

**Status:** Complete (2026-09-18).

**Scope:**

- [x] Manual end-to-end sanity check of all three consumers on real files
      (generated sine WAV → LAME MP3, run through the unified
      `audiosuite` CLI, decoded RMS/LUFS measured with ffmpeg):
  - [x] `audiosuite normalise --mode lossless --target-lufs -14` on a quiet
        stereo MP3: per-channel RMS change +9.03 dB on BOTH channels
        (|ΔL−ΔR| = 0.00 dB). The requested +9.15 dB quantizes to 6
        global_gain units = 9.03 dB — inherent to the lossless approach.
  - [x] `audiosuite replaygain --apply-gain`: applied per-channel change
        +9.03 dB; ReplayGain track-gain tag written (+9.10 dB, the analyzed
        pre-quantization value — tag holds the analysis, the baked global_gain
        is quantized; by design).
  - [x] `audiosuite convert --normalize-mp3 --target-lufs -16`: output
        integrated loudness −16.40 LUFS (within 0.5 tolerance + 0.75 dB
        quantization of target); with the target set to the output's natural
        loudness the gain step is a confirmed no-op.
- [x] No user-guide changes needed: behaviour is corrected to match the
      documented promise; no consumer wording changed.
- [x] No consumer tests relied on the buggy behaviour — full suite passed
      without lockstep changes outside the shared test module.

**Deliverables:**
- Documented manual verification results (this section + Completion Log).

**Success criteria:**
- Manual end-to-end check confirms expected gain on both channels for each
  consumer. Full-suite verification gate green (see "Phase Gate" below).

---

## Sprint 1 — Tooling Cleanup (Phase B)

> Minor findings from the Iteration-1 re-audit. No behavioural change to
> shipped features.

### B1 — Fingerprinter single-source-of-truth

**Priority:** Medium | **Effort:** 0.5 day | **Risk:** Low

**Scope:**

- [x] Replace `NUM_WORKERS: int = 4` at
      `audio_fingerprinter/core/file_processor.py:42` with
      `from audio_suite_shared.constants import DEFAULT_MAX_WORKERS`; update
      the module, `app.py:30/81/84`, and the tests that currently assert
      *value equality* (`test_file_processor.py:268` `NUM_WORKERS ==
      DEFAULT_MAX_WORKERS` — a tautology that should be re-pointed at the
      import or dropped).
- [x] Investigate the `# type: ignore[arg-type]` at
      `audio_fingerprinter/core/file_processor.py:416`. Root cause:
      `process_batch`'s `files: list[Path] | list[str]` (shared,
      `file_processor_base.py:496`) is being handed
      `list[_FingerprintJob]`. Resolve one of:
      - generalize `process_batch` to `list[T]` with
        `Callable[[T], object]` (shared change, benefits all tools), **or**
      - have the fingerprinter subclass/adapt its job list.
      Remove the suppression either way — project rules forbid shipping
      suppressions to "make it pass".

**Deliverables:**
- `NUM_WORKERS` gone; `DEFAULT_MAX_WORKERS` imported.
- No `type: ignore[arg-type]` in `file_processor.py`.

**Success criteria:**
- `grep -rn 'NUM_WORKERS' audio_fingerprinter/` → zero matches.
- `mypy . --strict` clean without the suppression.

---

### B2 — Lyrics manager slot-var reuse

**Priority:** Low | **Effort:** 0.25 day | **Risk:** Very low

**Scope:**

- [x] Replace the local `_ThreadSafeSlotVar` clone at
      `lyrics_manager/app.py:37-49` with the shared
      `make_safe_slot_vars(root, slot_vars)` from
      `audio_suite_shared/thread_safe_slot_var.py` (same helper
      `audio_fingerprinter` already uses at `app.py:26,82`).

**Deliverables:**
- `lyrics_manager/app.py` uses the shared helper.

**Success criteria:**
- `grep -rn 'class _ThreadSafeSlotVar' lyrics_manager/` → zero matches.
- lyrics_manager GUI tests pass unchanged.

---

### B3 — Constants test coverage

**Priority:** Low | **Effort:** 0.25 day | **Risk:** Very low

**Scope:**

- [x] Add `audio_suite_shared/tests/test_constants.py` exercising
      `audio_suite_shared/constants.py`: presence and value of the 8 named
      constants, type correctness (`int`/`str`), and that
      `DEFAULT_WINDOW_GEOMETRY` parses to an X11 geometry tuple.
- [x] Optionally assert the two other magic-number constants
      (`MAX_DURATION_HISTORY`, `JPEG_QUALITY`) are referenced by their
      consumers (import-level assertion).

**Deliverables:**
- `test_constants.py` (small).

**Success criteria:**
- New test file passes; constants coverage > 90%.

---

### B4 — ReplayGain undo-batch audit finding (resolved: no defect)

**Priority:** Low | **Effort:** 0.1 day | **Risk:** None

**Status:** Complete (2026-09-18).

**Outcome:** Follow-up from the Sprint-0 lossless-gain work. An undo-DB
roster audit appeared to show that `replaygain_analyzer --apply-gain` bakes
left no undo record. Investigation proved the report wrong:

- `run_analysis` captures the active batch id (`file_processor.py:333`) and
  the Phase-2 `_write_worker` joins it via `use_batch`; both the CLI and GUI
  entry points wrap the call in `active_batch(...)`.
- The undo DB contains a restorable pre-run tag snapshot for every RG run,
  including all `--apply-gain` bakes.
- The bake's own `lossless_gain_track` snapshot deduplicates into the
  `write_replaygain` record (`record_tag_edit` keeps the first snapshot per
  batch+file — the pre-run tag state, which is what restore needs). Auditing
  the DB by operation name `lossless_gain%` therefore misses RG-baked files;
  audit by file presence instead.

**Deliverables:**
- Regression test `TestUndoBatchRecording.
  test_apply_lossless_gain_bake_is_undo_recorded` pinning that a bake under
  an active batch leaves the file in the undo log with a snapshot.
- Call-site comment in `_write_worker` documenting the dedup semantics.

**Success criteria:**
- New test passes; no production code change required.

---

## Sprint 2 — Error-Handling Stragglers (Phase C)

### C1 — Narrow remaining library_stats broad catches

**Priority:** Medium | **Effort:** 0.5–1 day | **Risk:** Low

**Status:** Complete (2026-09-18).

**Scope:**

- [x] `library_stats/app.py:411,430,546` and `cli.py:110,163,170`:
      `except Exception as exc:` → narrow to the genuinely expected
      exception types at each site (`OSError`, `ValueError`,
      `json.JSONDecodeError`, `MutagenError`, `sqlite3.Error`, etc.), keep
      `exc_info=True` / the existing warning path, and add a comment where a
      deliberately broad safety net must remain.
- [x] `library_stats/core/completeness.py:168`: bare `except Exception:`
      → `except Exception as exc:` with a logged reason (never a silent
      bare handler).
- [x] Verify no behavioural change: the same error paths still produce the
      same user-facing messages.

**Deliverables:**
- 7 narrowed or documented catches (+1). ~1-2 additional test tweaks only if
  tests relied on `RuntimeError` (mirror the Iteration-1 1.3 lesson of
  raising realistic exception types).

**Success criteria:**
- `grep -rn 'except Exception' library_stats/` → zero bare handlers; every
  remaining one has an explicit type-list and a logged reason.
- Ruff, mypy, bandit, pytest green.

---

## Sprint 3 — Deferred Market-Gap Backlog (Phase D)

> Optional differentiators, not defects. Only schedule once A–C are done.
> Each item is a standalone mini-project with its own scope and guide.

| ID | Item | Gap it closes | Effort | Notes / prerequisites |
|----|------|---------------|--------|-----------------------|
| D1 | Dedicated LRC editor (single-file import/export GUI) | The 2026-09-16 rework moved `lyrics_manager` to batch fetch+embed and removed the single-file import/export UI | 2–3 days | Re-use `audio_suite_shared/lrc_handler.py` for parse/generate and the tag facades; a small `BaseSuiteApp` window. |
| D2 | Online tag lookup (Discogs / freedb / MusicBrainz via existing pattern) | Mp3tag/Kid3 owned this | 4–5 days | Re-use `album_art_sync`'s provider-fallback pattern + rate limiting; needs discogs token config (secrets → `KeyManager`). |
| D3 | AccurateRip verification in CD Ripper | dBpoweramp/XLD | Large (5–7 days) | Requires AccurateRip DB client + drive-offset tables; network + licensing review first. |
| D4 | Stem separation (HTDemucs/Spleeter) | EXTRAKT/TuneForge | Large (5–7 days) + heavy deps | Contradicts "dependency minimization" — explicit user approval and a model-size/packaging decision required. |
| D5 | Second lyric provider (Genius/Musixmatch) | provider-registry extensibility | 0.5–1 day | Pure addition: new class in `lyrics_manager/core/providers/` + registration. |

**Phase gate for D1–D5:** open a new decision before starting any item;
none are prerequisites for A/B/C.

---

## Phase Gate (every sprint, before marking complete)

0. `python -m compileall -q -f .` — exit 0
1. `ruff check .` and `ruff format --check .` — clean
2. `mypy . --strict` — 0 issues
3. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r audio_suite_shared -c pyproject.toml` — 0 High / 0 Medium severity (Low = documented subprocess wrappers)
4. Full-suite bare `pytest` — 100% pass (no `xfail`, no `# type: ignore`,
   no deleted-to-hide tests); Sprint 0 gate run 2026-09-18: 6353 passed /
   5 skipped, coverage 77.27%. Sprint 1 gate run 2026-09-18: 6367 passed /
   5 skipped, coverage 77.32%. Sprint 2 gate run 2026-09-18: 6369 passed /
   5 skipped, coverage 77.35%.
5. User guides: audit & update only when user-facing behaviour changed
   (A4 is expected to be "behaviour corrected to match the documented
   promise", so likely no guide change).

---

## Implementation Roadmap

| Sprint | Content | Phases | Days | Dependency |
|--------|---------|--------|------|------------|
| 0 | Lossless-gain correctness | A1→A2→A3→A4 | 3–3.5 | — |
| 1 | Tooling cleanup | B1, B2, B3 | 1 | — |
| 2 | Error-handling stragglers | C1 | 0.5–1 | — |
| 3* | Market-gap backlog (optional) | D1–D5 | varies | A + B complete |

\* Schedule per item individually and only after Sprint 0–2, or raise to the
user before starting.

Recommended conservative estimate: **Sprints 0–2 = ~1.5 weeks.**

---

## Completion Log

| Phase | Completed | Notes |
|-------|-----------|-------|
| A1 | 2026-09-18 | Validated layout replaces planned offsets: first gg bit 41/39 (MPEG-1 stereo/mono), 31/30 (LSF), strides 59/63, fields 4/2/2/1. Exact-fill identities hold. Extra bugs fixed: `_side_info_size` (mono/LSF), `_frame_size` LSF coefficient + LSF bitrate/sample-rate tables (walker skipped every other LSF frame), VBRI at fixed 32-byte offset. |
| A2 | 2026-09-18 | Hand-rolled constant-stride walker (both wsf branches are 22 bits → no per-block parsing). `_walk_frames` yields all gg offsets; `_modify_mp3_gains` updates every field. No external/licensed code. |
| A3 | 2026-09-18 | 12 decode-based tests added (stereo/joint/mono/MPEG-2, balance, clamp, size, all-fields). Pre-fix implementation confirmed failing those checks (−0.37/−1.98/+0.85 dB instead of +6.0). |
| A4 | 2026-09-18 | All 3 consumers validated through the `audiosuite` CLI: normalise lossless +9.03 dB both channels (Δbalance 0.00), replaygain bake + tag (+9.10 dB), convert normalize −16.40 LUFS @ target −16 + confirmed tolerance no-op. No guide changes. |
| B1 | 2026-09-18 | `NUM_WORKERS` gone from audio_fingerprinter (zero grep matches). `process_batch` generalized to `list[_T]` / `Callable[[_T], object]` (shared) — resolves the `# type: ignore[arg-type]` at file_processor.py:416 without suppression; replaygain's two now-stale ignores removed and audio_enhancer `_worker` annotated `Path` (loose `str` was exposed by the strict callback type). Fingerprinter app + both test modules re-pointed at `DEFAULT_MAX_WORKERS`. |
| B2 | 2026-09-18 | Local `_ThreadSafeSlotVar` clone replaced with shared `make_safe_slot_vars(root, slot_vars)`; lyrics_manager GUI tests pass unchanged (they mock `app._safe_slot_vars`). Zero `class _ThreadSafeSlotVar` matches. |
| B3 | 2026-09-18 | `test_constants.py` added: 14 new cases covering presence/value/type for all 7 constants that actually exist in `constants.py` (the plan says "8 named constants" but the module defines 7 — `DEFAULT_MAX_WORKERS`, `WORKER_TIMEOUT_SECS`, `CPU_WORKER_TIMEOUT_SECS`, `JPEG_QUALITY`, `MAX_DURATION_HISTORY`, `DEFAULT_WINDOW_GEOMETRY`, `VARIOUS_ARTISTS_ALIASES`), X11 geometry parse, plus import-level consumer references for `MAX_DURATION_HISTORY` (suite_config) and `JPEG_QUALITY` (album_art_normalizer art_processor). Constants coverage 100%. |
| C1 | 2026-09-18 | app.py 411/430 → `(OSError, ValueError)`; app.py 546 → `(AudioSuiteError, OSError, ValueError)` (export_csv raises `AudioFileNotFoundError`); cli.py 110 → `(OSError, ValueError, sqlite3.Error, AudioSuiteError)` (LibraryCache sqlite ops escape the scan); cli.py 163 → `(AudioSuiteError, OSError, ValueError)`; cli.py 170 → `(OSError, ValueError)`; completeness.py 168 → named `as exc` broad net with reason logged and a comment (per-file parse hardening must stay broad — kept `except Exception as exc:` consistently with the plan's "never a silent bare handler"). 2 behavior-lock CLI tests added (FATAL OSError → exit 1 + message; CSV export OSError → reported, non-fatal). `grep 'except Exception'` over library_stats/ → single documented handler with reason. Gate: compile ✓, ruff ✓, mypy --strict ✓ (429 files), bandit 0H/0M ✓, full pytest 6369 passed / 5 skipped, coverage 77.35%. |
| B4 | 2026-09-18 | No defect: RG CLI/GUI open `active_batch`, `_write_worker` joins via `use_batch`, and the DB held restorable snapshots for every `--apply-gain` bake. The bake's `lossless_gain_track` snapshot dedupes into the `write_replaygain` record (first-snapshot-per-batch+file), so operation-name audits miss it — audit by file presence. Pinned by regression test + call-site comment; no production code change. Gate: compile ✓, ruff ✓, mypy --strict ✓, full pytest 6388 passed / 5 skipped. |
| D1–D5 | | |

---

## Decision Log

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-09-18 | A1 | Replaced the planned offset values (39/35/33/31) with empirically validated ones (41/39/31/30, strides 59/63) | The planned table was spec-from-memory and wrong (private/scfsi/LSF-scalefac_compress widths). Decode-based differential probing + exact-fill identities prove the shipped values; documented in lossless_gain.py module docstring. |
| 2026-09-18 | A2 | Hand-rolled constant-stride walker; no port from mp3gain or any reference implementation | Both window-switching branches are 22 bits wide → block size constant (59/63) → no per-branch parsing needed. Zero licence risk; layout verified empirically incl. window-switching frames. |
| 2026-09-18 | B1 | Chose to generalize `process_batch` (shared) over adapting the fingerprinter job list | Three existing callers already hand `process_batch` typed job objects (fingerprinter `list[_FingerprintJob]`, replaygain `measure_jobs`/`write_jobs`) and all worker callables are single-positional-arg (verified across the 7 consumers incl. `functools.partial` in audio_refinery). `list[T]` benefits every tool; adapting just the fingerprinter would leave the shared API wrong for the others. |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Side-info walker regressions in rare frame variants (block_type 2 / mixed_block), VBR grgranule aliasing | Medium | High | A3 decode-based stereo+mono+LSF tests exercise LAME VBR & CBR; keep Xing/Info/VBRI skip tests from Iteration-1 |
| Fixing gain breaks previously "passing" normalizer/replaygain/converter tests that encoded the buggy single-field behaviour | Medium | Low | A4 lockstep test updates; assert the documented promise (both channels gain), not the old internal read-back |
| mp3gain referenced implementation licence incompatible | Low | Medium | Decision gate at A2 start; hand-rolled walker fallback requires no external code |
| Localized changes mask a remaining global_gain path (e.g. dual-channel frames with intensity stereo) | Low | Medium | A3 includes a complaint-free decode of a joint-stereo LAME file (typical default), asserting both channels |
---

## Decision Log — D-series twin-consolidation (lockstep, delivered)

- **D1·twins — `audio_normalizer/utils/ffmpeg_finder.py` (twin-A) + `audio_normalizer/tests/test_ffmpeg_finder.py` (lockstep twin-A):** COMPLETE. Canonical import `from audio_suite_shared.subprocess_utils import get_startupinfo` (+ re-export), local twin `get_startupinfo` def deleted ("def get_startupinfo" byte-count = 0), dead STARTUPINFO singleton removed. Lockstep twin-A test points at the canonical site `audio_suite_shared.subprocess_utils.os.name` ONLY (posix-gate), canonical single-backslash fixtures (`r"C:\tools\ffmpeg.exe"`), `from unittest.mock import patch` present, zero doubled-backslash remnants. Gate: `python -m pytest audio_normalizer/tests/test_ffmpeg_finder.py` → 2 passed.
- **D2·twins — `replaygain_analyzer/core/ffmpeg_metrics.py` (twin-B) + `replaygain_analyzer/tests/test_replaygain_pipeline.py` (lockstep twin-B):** COMPLETE. Canonical import + alias `_get_startupinfo = get_startupinfo` (local twin def deleted, byte-count 0). Lockstep twin-B test canonical-only patch site (`audio_suite_shared.subprocess_utils.os.name`, posix-gate), patch-import present, zero doubled remnants. Gate: `python -m pytest replaygain_analyzer/tests/test_replaygain_pipeline.py` → 71 passed.
- **Holistic verification (all 4/5/6 gates, exit 0):** compileall whole-tree → 0; ruff (4 lockstep+canonical files) → 0; mypy --strict (both twin modules + shared subprocess_utils) → Success; bandit (3 modules, pyproject config) → 0 High/0 Medium; bare whole-repo pytest → **6387 passed / 5 skipped / exit 0**; bare twin-lockstep gate (Twin-A+Twin-B real suites, coverage-neutralized) → **73 passed / exit 0**.
