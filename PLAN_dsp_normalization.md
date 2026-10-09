# PLAN: Standardize DSP Pipelines on Normalized float32 with Clipping Protection

> **Status**: COMPLETE — all 9 phases verified shipped in-tree (header corrected 2026-10-09; the work landed before the 2026-09-22 initial commit and this marker was never updated)
> **Created**: 2026-09-05
> **Scope**: audio_suite_shared, audio_refinery, noise_reduction, pop_click_remover, audio_enhancer

---

## 1. Problem Statement

The AudioSuite-Pro codebase has **two incompatible audio data representations** coexisting:

| Representation | Used by | Format |
|---|---|---|
| **Normalized [-1,1] float32** | `convert.py`, `audio_playback.py`, `dsp_chain.py`, `audio_enhancer/processor.py` | `(channels, frames)` |
| **Raw integer counts** (e.g. -32768..32767) | `noise_reducer.py`, `declicker.py`, `measure.py` | `(frames, channels)` |

This causes:

- **Duplicated conversion logic** (5+ independent int→float decoders)
- **Inconsistent scale assumptions** (thresholds calibrated for integer scale fail if fed normalized floats)
- **No centralized clipping protection** (each tool reimplements `np.clip` to bit-depth bounds)
- **Silent data bugs** when tools are composed in the Refinery pipeline with mismatched scales

---

## 2. Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Canonical float dtype | **float32** | Matches pedalboard's native type, half the memory. float64 upcast only for measurement/analysis. |
| Canonical range | **[-1.0, 1.0]** | Standard audio convention, matches pedalboard/FFmpeg convention. |
| Module location | **`audio_suite_shared/audio_conversion.py`** | Clean separation: `dsp_chain` handles DSP, `audio_conversion` handles format conversions. |
| Migration strategy | **Convert to normalized at boundaries** | noise_reducer and declicker entry/exit points use shared conversion; internal DSP stays float64 for scipy precision. |
| Clipping protection | **Hard clip + peak headroom logging** | Hard clip to [-1,1] post-DSP + optional peak measurement logging. Lightweight, matches existing Limiter pattern. |

---

## 3. Architecture Overview

### Current State (Before)

```
audio_refinery/core/convert.py        ← segment_to_numpy / numpy_to_segment (canonical, but private)
audio_suite_shared/dsp_chain.py       ← compute_rms_db (operates on any float)
noise_reduction/core/noise_reducer.py ← own int→float decode, own clip-to-int
pop_click_remover/core/declicker.py   ← own int→float decode, own clip-to-int
audio_refinery/core/measure.py        ← manual /32768.0 divisions
audio_suite_shared/audio_playback.py  ← manual /32768.0 / /2147483648.0
audio_enhancer/core/processor.py      ← pedalboard float32, manual float64 upcast
```

### Target State (After)

```
audio_suite_shared/audio_conversion.py  ← SINGLE source of truth for all conversions
  ├── segment_to_numpy()                  (pydub → float32 [-1,1])
  ├── numpy_to_segment()                  (float32 [-1,1] → pydub, with clipping)
  ├── clip_to_range()                     (hard clip [-1,1])
  ├── measure_peak_db() / measure_rms_db() (dBFS on normalized arrays)
  ├── check_headroom()                    (peak vs target dBFS)
  ├── log_clip_event()                    (warning log on clip)
  ├── clip_bounds() / int_dtype()         (bit-depth helpers)
  └── pack_24bit()                        (24-bit PCM packing)

audio_refinery/core/convert.py  ← thin re-export wrapper (backward compat)
noise_reduction/core/noise_reducer.py  ← imports from shared, converts at boundaries
pop_click_remover/core/declicker.py    ← imports from shared, converts at boundaries
audio_refinery/core/measure.py         ← imports from shared, no more /32768
audio_suite_shared/audio_playback.py   ← imports from shared
audio_suite_shared/dsp_chain.py        ← adds post_chain_clip_check()
```

### Data Flow Convention

Every tool follows this pattern:

```
AudioSegment (pydub, integer PCM)
  │
  ├── segment_to_numpy() ──→ float32 (channels, frames) [-1, 1]
  │                              │
  │                         .T.astype(float64)  ← for scipy DSP precision
  │                              │
  │                         [DSP processing]
  │                              │
  │                         .T.astype(float32)  ← back to float32
  │                              │
  ├── clip_to_range() ──────────→ float32 (channels, frames) [-1, 1]
  ├── log_clip_event() ─────────→ (warning if clipped)
  │
  └── numpy_to_segment() ──→ AudioSegment (pydub, integer PCM, clipped to bit-depth)
```

---

## 4. Phase 1: Create Shared `audio_conversion.py` Module

### New File: `audio_suite_shared/audio_conversion.py`

**Purpose**: Single source of truth for all pydub↔numpy conversions, clipping protection, and dBFS measurement on normalized arrays.

#### Functions to Implement

```python
"""
audio_conversion.py — Shared audio format conversion and clipping protection.

Canonical data representation:
  - float32, range [-1.0, 1.0], shape (channels, frames)
  - Matches pedalboard and FFmpeg conventions
  - float64 used only inside scipy/numpy DSP (upcast at tool boundary)

All DSP tools should import from this module rather than implementing
their own int→float decode or clip-to-int logic.
"""
```

**Conversion functions** (lift from `audio_refinery/core/convert.py`):

| Function | Signature | Description |
|---|---|---|
| `segment_to_numpy` | `(audio: AudioSegment) → tuple[np.ndarray, int]` | pydub AudioSegment → float32 `(channels, frames)` in [-1, 1]. Returns `(audio_f32, sample_rate)`. |
| `numpy_to_segment` | `(audio_f32, sample_rate, sample_width=2, num_channels=2) → AudioSegment` | float32 `(channels, frames)` [-1, 1] → pydub AudioSegment with `np.clip` to bit-depth bounds. |
| `load_as_float32` | `(audio: AudioSegment) → tuple[np.ndarray, int]` | Alias for `segment_to_numpy` — semantically clearer for callers that don't need the segment path. |

**Clipping protection functions** (new):

| Function | Signature | Description |
|---|---|---|
| `clip_to_range` | `(audio: np.ndarray, hard_limit: float = 1.0) → np.ndarray` | Hard-clip float array to `[-hard_limit, hard_limit]`. Returns NEW array (never mutates). |
| `measure_peak_db` | `(audio: np.ndarray) → float` | Peak level in dBFS of a normalized float array. |
| `measure_rms_db` | `(audio: np.ndarray) → float` | RMS level in dBFS of a normalized float array. |
| `check_headroom` | `(audio: np.ndarray, target_db: float = -0.5) → tuple[bool, float]` | Check if peak is below `target_db`. Returns `(ok, actual_peak_db)`. |
| `log_clip_event` | `(audio: np.ndarray, stage_name: str, logger: Any) → None` | If any sample exceeds ±1.0, log a warning with peak level. Call AFTER DSP, BEFORE int conversion. |

**Bit-depth helper functions** (lift from `audio_refinery/core/convert.py`):

| Function | Signature | Description |
|---|---|---|
| `clip_bounds` | `(sample_width: int) → tuple[int, int]` | Return `(min, max)` int PCM bounds for sample_width in bytes. |
| `int_dtype` | `(sample_width: int) → type[np.integer]` | Return numpy integer dtype for a pydub sample_width. |
| `pack_24bit` | `(int32_array: np.ndarray) → bytes` | Pack int32 array to 3-bytes-per-sample little-endian PCM. |

#### Implementation Notes

- `segment_to_numpy` and `numpy_to_segment` are **moved** (not copied) from `audio_refinery/core/convert.py`
- The original `convert.py` becomes a thin re-export wrapper (Phase 6)
- `clip_to_range` uses `np.clip(audio, -limit, limit).copy()` — pure function, no mutation
- `measure_peak_db` and `measure_rms_db` operate on **normalized [-1,1]** arrays — no `/32768` magic numbers
- `log_clip_event` checks `np.any(np.abs(audio) > 1.0)` and logs peak via `measure_peak_db`

---

## 5. Phase 2: Migrate `noise_reducer.py` to Normalized float32

### File: `noise_reduction/core/noise_reducer.py`

#### Step 2.1: Add import

```python
from audio_suite_shared.audio_conversion import (
    clip_to_range,
    log_clip_event,
    numpy_to_segment,
    segment_to_numpy,
)
```

#### Step 2.2: Replace raw integer decoding

**4 duplicated decode blocks** (lines 198-201, 284-287, 342-346, 385-389) all follow this pattern:

```python
# BEFORE:
raw = np.frombuffer(audio.raw_data, dtype=np.int16 if sample_width == 2 else np.int32)
samples = raw.reshape(-1, num_channels).astype(np.float64)

# AFTER:
samples_f32, _sample_rate = segment_to_numpy(audio)  # (channels, frames) float32
samples = samples_f32.T.astype(np.float64)  # (frames, channels) float64 for scipy
```

This change applies to:
- `remove_hum()` — line 198-201
- `spectral_gate()` — line 284-287
- `reduce_noise()` dry_run path — line 342-346
- `reduce_noise()` no-modification path — line 385-389

#### Step 2.3: Fix `_rms_db()` helper

The existing helper is already correct for normalized input — the `astype(np.float64)` is a no-op since input will already be float64. **No change needed** to the function body.

```python
# Current (line 64-69) — works correctly on normalized input:
def _rms_db(audio_f64: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(audio_f64.astype(np.float64) ** 2)))
    if rms < 1e-12:
        return -120.0
    return 20.0 * math.log10(rms)
```

#### Step 2.4: Replace integer-scale clipping at output

**2 output paths** (lines 222-227, 311-316) follow this pattern:

```python
# BEFORE:
dtype = np.int16 if sample_width == 2 else np.int32
clip_min = float(np.iinfo(dtype).min)
clip_max = float(np.iinfo(dtype).max)
pcm = np.clip(samples, clip_min, clip_max).astype(dtype)
new_audio = audio._spawn(pcm.flatten().tobytes())

# AFTER:
clipped = clip_to_range(samples.T.astype(np.float32))  # back to (channels, frames)
log_clip_event(clipped, "noise_reduction", logger)
new_audio = numpy_to_segment(
    clipped,
    sample_rate,
    sample_width=audio.sample_width,
    num_channels=audio.channels,
)
```

This change applies to:
- `remove_hum()` — lines 222-227
- `spectral_gate()` — lines 311-316

#### Threshold Recalibration Analysis

**No recalibration required.** All existing thresholds are scale-invariant:

| Threshold | Why it's safe |
|---|---|
| `_MIN_ATTENUATION_DB` (3.0 dB) | Measures energy *change*, not absolute level |
| `gate_threshold_db` | Applied to magnitude spectra in dB — scale-invariant |
| IIR notch filter coefficients | `scipy.signal.iirnotch` operates on frequency/Q — scale-invariant |
| `_MIN_NOISE_REGION_MS` | Time-based — not affected by amplitude scale |

---

## 6. Phase 3: Migrate `declicker.py` to Normalized float32

### File: `pop_click_remover/core/declicker.py`

#### Step 3.1: Add import

```python
from audio_suite_shared.audio_conversion import (
    clip_to_range,
    log_clip_event,
    numpy_to_segment,
    segment_to_numpy,
)
```

#### Step 3.2: Replace integer-scale decoding in `declick_audio()`

```python
# BEFORE (lines 371-376):
dtype, clip_min, clip_max = _bit_depth_params(sample_width)
max_width_samples = max(1, int((max_width_ms / 1000.0) * sample_rate))
raw = np.array(audio.get_array_of_samples(), dtype=np.float64)
samples = raw.reshape(-1, num_channels)

# AFTER:
max_width_samples = max(1, int((max_width_ms / 1000.0) * sample_rate))
samples_f32, sr = segment_to_numpy(audio)  # (channels, frames) float32
samples = samples_f32.T.astype(np.float64)  # (frames, channels) float64
clip_max = 1.0  # normalized scale
```

#### Step 3.3: Update `_detect_and_repair_channel()` signature

The `clip_max` parameter changes from integer-count value (e.g. 32767) to `1.0`. Internal callers already pass `clip_max` through from `declick_audio()`.

#### Step 3.4: Verify `_repair_region()` guards

**Amplitude guard** (line 235): `_MIN_AMPLITUDE_FRACTION * clip_max`
- Before: `(32/32767) * 32767 = 32` (integer counts)
- After: `(32/32767) * 1.0 ≈ 0.001` (normalized)
- **Correct** — the constant is already a fraction

**Saturation guard** (line 242): `abs(val) >= 0.99 * clip_max`
- Before: `abs(val) >= 0.99 * 32767 ≈ 32439` (integer counts)
- After: `abs(val) >= 0.99 * 1.0 = 0.99` (normalized)
- **Correct** — detects clipped samples at either scale

#### Step 3.5: Replace integer-scale output clipping

```python
# BEFORE (lines 391-392):
repaired = np.clip(samples, clip_min, clip_max).astype(dtype)
new_audio = audio._spawn(repaired.flatten().tobytes())

# AFTER:
clipped = clip_to_range(samples.T.astype(np.float32))  # (channels, frames)
log_clip_event(clipped, "declick", logger)
new_audio = numpy_to_segment(
    clipped,
    sr,
    sample_width=audio.sample_width,
    num_channels=audio.channels,
)
```

#### Step 3.6: Update `_bit_depth_params()` function

This function can either be **removed** (no longer needed) or **repurposed**:

```python
# OPTION A: Remove entirely (recommended)
# All callers now use clip_max=1.0 directly

# OPTION B: Repurpose for reference
def _bit_depth_params(sample_width: int) -> tuple[type[np.signedinteger], float, float]:
    """Return (unused, unused, clip_max=1.0) for normalized scale."""
    return np.int32, -1.0, 1.0  # clip bounds now in normalized scale
```

#### Threshold Recalibration Analysis

**No recalibration required.** All detection thresholds are ratio-based:

| Threshold | Why it's safe |
|---|---|
| k-multiplier system (12-30) | `diff / local_noise` ratio — scale-invariant |
| `_MIN_AMPLITUDE_FRACTION` | Already a fraction (32/32767) — works on [-1,1] |
| `_AMP_CHECK_WINDOW_S` | Time-based — not affected |
| `_REPAIR_CONTEXT` | Sample-count-based — not affected |
| `_MAD_WINDOW_CLICK_S` | Time-based — not affected |
| Cubic spline repair | Operates on sample values — works at any scale |
| Overshoot guard (`peak_orig`) | Relative comparison — scale-invariant |

---

## 7. Phase 4: Migrate `measure.py` to Normalized float32

### File: `audio_refinery/core/measure.py`

#### Step 4.1: Add import

```python
from audio_suite_shared.audio_conversion import segment_to_numpy
```

#### Step 4.2: Replace `get_array_of_samples()` + `/32768.0` pattern

**All measurement functions** (lines 37, 52-53, 56-57, 61, 64, 71-75) currently do:

```python
# BEFORE:
samples = np.array(audio.get_array_of_samples())
peak = np.max(np.abs(samples)) / 32768.0

# AFTER:
samples_f32, _sr = segment_to_numpy(audio)
# samples_f32 is already in [-1, 1] — no division needed
peak = float(np.max(np.abs(samples_f32)))
```

#### Step 4.3: Fix `measure_click_characteristics()` (line 139)

```python
# BEFORE:
threshold = sensitivity * 32768.0

# AFTER:
threshold = sensitivity  # sensitivity is already a fraction in [0, 1]
```

**Note**: The `sensitivity` parameter default (0.1) represents a fraction of full-scale. On normalized input, the threshold is directly `0.1` (i.e. samples with diff > 0.1 are flagged). This is equivalent to the old `0.1 * 32768 = 3276.8` integer-count threshold when the input was in integer scale.

#### Step 4.4: Fix `measure_silence_characteristics()` and `measure_enhancement_metrics()`

Apply the same pattern: replace all `get_array_of_samples()` with `segment_to_numpy()` and remove all `/32768.0` divisions.

#### Step 4.5: Fix `measure_loudness_metrics()` (lines 315-403)

This function shells out to FFmpeg — no numpy conversion needed. **No changes required.**

---

## 8. Phase 5: Migrate `audio_playback.py` to Shared Module

### File: `audio_suite_shared/audio_playback.py`

#### Step 5.1: Update `_read_wav()` (lines 241-256)

The existing `_read_wav` function already correctly normalizes to [-1,1] float32. Two options:

```python
# OPTION A (recommended): Keep existing code, add reference comment
def _read_wav(wav_path: Path) -> tuple[npt.NDArray[np.float32], int]:
    """Read a PCM WAV into float32 samples scaled to [-1, 1], always 2-D.

    Uses the same normalization convention as audio_suite_shared.audio_conversion
    (canonical float32 [-1,1] format).
    """
    # ... existing implementation unchanged ...


# OPTION B: Replace with shared module call
from audio_suite_shared.audio_conversion import segment_to_numpy
# (Requires constructing an AudioSegment from the WAV, which adds overhead)
```

**Recommendation**: Option A. The `_read_wav` function reads directly from the `wave` module for efficiency (avoids pydub decode overhead for playback). The normalization math is identical and correct. Add a comment referencing the canonical convention.

---

## 9. Phase 6: Update `convert.py` to Re-export

### File: `audio_refinery/core/convert.py`

Replace the module body with thin re-exports:

```python
"""
core/convert.py — Re-exports from audio_suite_shared.audio_conversion.

The canonical implementation now lives in audio_suite_shared.audio_conversion.
This module is retained for backward compatibility; all new code should import
from audio_suite_shared.audio_conversion directly.
"""

from audio_suite_shared.audio_conversion import (  # noqa: F401
    clip_bounds,
    int_dtype,
    numpy_to_segment,
    pack_24bit,
    segment_to_numpy,
)

# Preserve internal helpers as re-exports for any direct test callers
from audio_suite_shared.audio_conversion import clip_bounds as _clip_bounds  # noqa: F401
from audio_suite_shared.audio_conversion import int_dtype as _int_dtype  # noqa: F401
from audio_suite_shared.audio_conversion import pack_24bit as _pack_24bit  # noqa: F401
```

**Backward compatibility**: All existing imports (`from audio_refinery.core.convert import segment_to_numpy`) continue to work.

---

## 10. Phase 7: Add Clipping Protection to DSP Chain Outputs

### File: `audio_suite_shared/dsp_chain.py`

Add a post-DSP clipping detection function:

```python
def post_chain_clip_check(
    audio: npt.NDArray[np.floating[Any]],
    stage_name: str = "dsp_chain",
) -> npt.NDArray[np.floating[Any]]:
    """Check for clipping after DSP processing.

    Logs a warning if peak > -0.5 dBFS (potential clipping risk).
    Does NOT mutate the array — detection only.

    Parameters
    ----------
    audio : np.ndarray
        DSP output in normalized float scale.
    stage_name : str
        Name of the calling stage for log context.

    Returns
    -------
    np.ndarray
        The input array unchanged.
    """
    from audio_suite_shared.audio_conversion import check_headroom

    ok, peak_db = check_headroom(audio, target_db=-0.5)
    if not ok:
        logger.warning(
            "[%s] Clipping risk: peak at %.1f dBFS (target: < -0.5 dBFS)",
            stage_name,
            peak_db,
        )
    return audio
```

### Integration Points

**In `audio_refinery/core/pipeline.py` → `_run_enhance()`** (after line 480):

```python
from audio_suite_shared.dsp_chain import post_chain_clip_check

enhanced_np = chain(audio_np, sample_rate)
post_chain_clip_check(enhanced_np, stage_name="Enhance")  # <-- ADD THIS
```

**In `audio_enhancer/core/processor.py` → `process_file()`** (after line 94):

```python
from audio_suite_shared.dsp_chain import post_chain_clip_check

enhanced = chain(audio, sample_rate).astype(np.float64)
post_chain_clip_check(enhanced, stage_name="Enhance")  # <-- ADD THIS
```

---

## 11. Phase 8: Update All Tests

### New Test File: `audio_suite_shared/tests/test_audio_conversion.py`

Full test coverage for the new shared module:

```python
class TestSegmentToNumpy:
    test_returns_float32_dtype
    test_values_in_minus_one_to_one
    test_channels_first_shape_mono
    test_channels_first_shape_stereo
    test_sample_rate_preserved
    test_frame_count_matches_duration
    test_silence_produces_near_zero
    test_stereo_channels_identical_for_duplicated_mono

class TestNumpyToSegment:
    test_returns_audio_segment
    test_sample_rate_preserved
    test_sample_width_preserved
    test_channels_preserved
    test_clipping_prevents_overflow (values > 1.0 → max int)
    test_negative_clipping
    test_zero_array_produces_silence
    test_24bit_packing_correct

class TestClipToRange:
    test_within_range_unchanged
    test_positive_clipped
    test_negative_clipped
    test_returns_new_array (no mutation)
    test_custom_hard_limit

class TestMeasurePeakDb:
    test_silence_very_negative
    test_sine_wave_correct
    test_full_scale_is_zero_dbfs

class TestMeasureRmsDb:
    test_silence_very_negative
    test_known_signal

class TestCheckHeadroom:
    test_within_target_returns_true
    test_above_target_returns_false
    test_returns_actual_peak

class TestLogClipEvent:
    test_no_warning_when_no_clip
    test_warning_when_clipped

class TestRoundTrip:
    test_mono_round_trip_preserves_shape
    test_stereo_round_trip_preserves_shape
    test_round_trip_low_distortion
    test_empty_array_returns_empty_segment
    test_all_bit_depths (8/16/24/32)
```

### Existing Test Files to Update

| Test file | Changes |
|---|---|
| `audio_refinery/tests/test_convert_and_pipeline.py` | Update imports to use shared module; existing tests should pass unchanged since behavior is identical |
| `noise_reduction/tests/test_noise_reducer.py` | Verify all tests pass after migration; update any fixtures constructing integer-scale arrays to use `segment_to_numpy` |
| `pop_click_remover/tests/test_declicker.py` | Verify all tests pass; `_bit_depth_params` tests may need updating if function is removed |
| `audio_refinery/tests/test_measure.py` | Update tests using `get_array_of_samples()` to use `segment_to_numpy()` |
| `audio_suite_shared/tests/test_dsp_chain.py` | Add tests for `post_chain_clip_check` |

---

## 12. Phase 9: Verification Pipeline

Run the full verification pipeline after all changes:

```bash
# Gate 0: Compile/import check (MANDATORY first step)
python -m compileall -q -f .

# Gate 1: Linting & formatting
ruff check --fix .
ruff format .

# Gate 2: Static type checking
mypy . --strict

# Gate 3: Security screening
bandit -r audio_suite_shared/ noise_reduction/ pop_click_remover/ audio_refinery/

# Gate 4: Test suite
python -m pytest tests/ -v
```

**Zero-failure enforcement**: All tests must pass before marking any phase complete.

---

## 13. File Change Summary

| File | Action | Phase | Risk |
|---|---|---|---|
| `audio_suite_shared/audio_conversion.py` | **NEW** | 1 | Low |
| `audio_suite_shared/tests/test_audio_conversion.py` | **NEW** | 8 | Low |
| `noise_reduction/core/noise_reducer.py` | **MODIFY** | 2 | Medium |
| `pop_click_remover/core/declicker.py` | **MODIFY** | 3 | Medium |
| `audio_refinery/core/measure.py` | **MODIFY** | 4 | Low |
| `audio_suite_shared/audio_playback.py` | **MODIFY** | 5 | Low |
| `audio_refinery/core/convert.py` | **MODIFY** (re-export) | 6 | Low |
| `audio_suite_shared/dsp_chain.py` | **MODIFY** (add clip check) | 7 | Low |
| `audio_refinery/core/pipeline.py` | **MODIFY** (call clip check) | 7 | Low |
| `audio_enhancer/core/processor.py` | **MODIFY** (call clip check) | 7 | Low |
| 6 test files | **MODIFY** | 8 | Low |

---

## 14. Dependency Graph & Execution Order

```
Phase 1 (shared module)
    │
    ├──→ Phase 2 (noise_reducer)  ──┐
    ├──→ Phase 3 (declicker)     ──┤
    ├──→ Phase 4 (measure.py)    ──┤   All depend on Phase 1
    ├──→ Phase 5 (playback)      ──┤   Can be done in parallel
    ├──→ Phase 6 (convert.py)    ──┤
    └──→ Phase 7 (clip check)    ──┘
                                       │
                                  Phase 8 (tests)
                                       │
                                  Phase 9 (verify)
```

**Phase 1 must complete first.** Phases 2–7 can be executed in any order or in parallel. Phase 8 should be done alongside each phase (write tests for each change). Phase 9 is the final gate.

---

## 15. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Declicker thresholds break on normalized scale | Low | High | All thresholds are ratio-based (scale-invariant). `_MIN_AMPLITUDE_FRACTION` is already a fraction. Verified by mathematical analysis. |
| Noise reducer dBFS calculations break | Low | High | `_rms_db()` computes `20*log10(sqrt(mean(x²)))` — directly gives dBFS on normalized input without `/32768`. |
| measure.py sensitivity parameter semantics change | Low | Medium | Document the new scale. The function is for internal analysis, not user-facing. Default value (0.1) works at both scales. |
| Pedalboard float32 constraint causes precision loss | None | None | Accepted constraint (documented in `processor.py`). float32 is the canonical interchange type; float64 used only for scipy measurement. |
| Backward compatibility of `convert.py` imports | Low | Medium | Re-export wrapper preserves all existing imports. Tests verify. |
| Existing tests break after migration | Medium | Medium | Run tests after each phase. All existing behavior is preserved — only the internal representation changes. |

---

## 16. Future Considerations (Out of Scope)

These are NOT part of this plan but are noted for future reference:

- **Soft-clipper / saturation**: Could be added as an optional stage in `dsp_chain.py` using `np.tanh()` for musically pleasing clipping
- **Auto-gain-reduction**: If post-DSP peak > -0.5 dBFS, automatically reduce output gain — more complex but prevents clipping without hard limits
- **Per-tool configurable precision**: Allow tools to request float64 interchange when needed for extreme-precision DSP
- **Real-time peak metering**: GUI integration for live peak/RMS display during processing

---

## 17. Acceptance Criteria

This plan is complete when:

1. `audio_suite_shared/audio_conversion.py` exists with all functions implemented and tested
2. `noise_reduction/core/noise_reducer.py` uses `segment_to_numpy` / `numpy_to_segment` at boundaries
3. `pop_click_remover/core/declicker.py` uses `segment_to_numpy` / `numpy_to_segment` at boundaries
4. `audio_refinery/core/measure.py` has zero `/32768.0` divisions
5. `audio_refinery/core/convert.py` is a thin re-export wrapper
6. `audio_suite_shared/dsp_chain.py` has `post_chain_clip_check`
7. All existing tests pass (`pytest tests/ -v`)
8. Full verification pipeline passes (compile, ruff, mypy, bandit, pytest)
9. No tool performs its own int→float decode — all use the shared module
