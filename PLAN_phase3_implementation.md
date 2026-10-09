# Phase 3 — Noise / Hum Reduction Tool: Implementation Plan

**Status:** COMPLETE — shipped and verified in-repo 2026-09-04 (recorded in `PLAN_gap_analysis.md` progress log, item 3.1; header corrected 2026-10-09 — the original "Ready for execution" marker was stale)  
**Scope:** 3.1 from `PLAN_gap_analysis.md`  
**Dependencies:** Phases 1, 2, 4.2 all completed  

---

## 1. Architecture Overview

### Two delivery modes
1. **Standalone tool** (`noise_reduction/`) — full GUI + CLI, processes a folder of files
2. **Refinery pipeline stage** — 5th optional stage (`reduce_noise`) in the Audio Refinery, with its own params, settings persistence, and UI toggle

### DSP algorithms (no new third-party deps — `scipy` only)

| Feature | Algorithm | Library |
|---|---|---|
| Hum (50/60 Hz + harmonics) | Cascaded IIR notch filters (`iirnotch` + `sosfilt`) | `scipy.signal` |
| Broadband noise / hiss | STFT-based spectral gating with user-provided noise profile | `scipy.signal.stft` / `istft` |

### File layout

```
noise_reduction/                     # NEW standalone tool
├── __init__.py                      # exports NoiseReductionApp
├── app.py                           # Tkinter GUI orchestrator
├── cli.py                           # Click "reduce-noise" command
├── core/
│   ├── __init__.py
│   ├── noise_reducer.py             # DSP engine: hum_removal(), spectral_gate()
│   ├── file_processor.py            # Multi-threaded orchestrator (ThreadPoolExecutor)
│   └── models.py                    # NoiseReductionParams, NoiseReductionResult
├── ui/
│   ├── __init__.py
│   ├── setup_tab.py                 # Setup tab with hum + broadband controls
│   ├── processing_tab.py            # Progress/slot display (reuse pattern)
│   └── results_tab.py               # Results + audition buttons
├── utils/
│   ├── __init__.py
│   └── cli_args.py                  # argparse CLI argument parser
└── tests/
    ├── __init__.py
    ├── conftest.py                  # session-scoped hidden Tk root
    ├── test_noise_reducer.py        # DSP engine unit tests
    ├── test_file_processor.py       # Orchestrator tests
    ├── test_models.py               # Data model tests
    └── test_app.py                  # GUI tests (object.__new__ + MagicMock)
```

### Modified files

| File | Change |
|---|---|
| `audio_refinery/core/models.py` | Add `NoiseReductionParams` dataclass; add `reduce_noise: bool` + `noise_reduction_params` to `StageConfig` |
| `audio_refinery/core/pipeline.py` | Add noise reduction stage between trim and enhance |
| `audio_refinery/utils/settings.py` | Persist/load `reduce_noise` toggle and `NoiseReductionParams` |
| `audio_refinery/ui/setup_tab.py` | Add `_build_noise_reduction_panel()` stage panel |
| `audio_refinery/utils/cli_args.py` | Add `--reduce-noise`, `--hum-freq`, `--hum-harmonics`, `--noise-start`, `--noise-end`, `--gate-threshold` args |
| `audio_refinery/core/file_processor.py` | Add `reduce_noise` to default stages string |
| `audio_suite_shared/tool_plugin.py` | Register `noise_reduction` manifest in `_build_default_registry()` |
| `audio_suite_shared/cli_app.py` | Import `noise_reduction.cli` to register command |
| `master_driver/ui/cards/noise_reduction_card.py` | NEW: collapsible card for UTIL tab |
| `master_driver/runner/arg_builder.py` | Add `noise_reduction` builder to `_build_utility_tool_args()` |
| `.pyw` launcher | NEW: `Noise_Reduction.pyw` |

---

## 2. Core DSP Engine: `noise_reduction/core/noise_reducer.py`

### 2a. Hum Removal

```python
def remove_hum(
    audio: AudioSegment,
    fundamental_hz: int = 60,
    harmonics: int = 8,
    quality: float = 30.0,
) -> NoiseReductionResult:
```

**Algorithm:**
1. Convert pydub `AudioSegment` → numpy float64 via `segment_to_numpy()`
2. For each channel independently:
   - Cascade `harmonics` second-order IIR notch filters at `fundamental_hz * i` for `i in 1..harmonics`
   - Each filter: `scipy.signal.iirnotch(freq, quality, fs)` → `sos` format
   - Apply: `scipy.signal.sosfilt(sos, channel_data)`
3. Measure RMS before/after
4. Convert back to pydub `AudioSegment` via `numpy_to_segment()`
5. Return `NoiseReductionResult(audio, energy_before, energy_after, was_modified)`

**Key constants:**
- `_DEFAULT_HUM_FREQUENCIES = {50, 60}` — supported fundamental frequencies
- `_MAX_HARMONICS = 20` — hard cap
- `_MIN_QUALITY = 1.0`, `_MAX_QUALITY = 100.0`

### 2b. Broadband Noise Reduction (Spectral Gating)

```python
def spectral_gate(
    audio: AudioSegment,
    noise_start_ms: int = 0,
    noise_end_ms: int = 500,
    gate_threshold_db: float = 3.0,
    n_fft: int = 2048,
    hop_length: int = 512,
) -> NoiseReductionResult:
```

**Algorithm:**
1. Convert pydub → numpy float64 via `segment_to_numpy()`
2. For each channel independently:
   - Compute STFT: `scipy.signal.stft(channel, fs, nperseg=n_fft, noverlap=n_fft - hop_length)`
   - Extract noise profile from `[noise_start_ms, noise_end_ms]` region (mean magnitude spectrum)
   - Compute magnitude gate: `noise_profile * 10^(gate_threshold_db / 20)`
   - Apply spectral mask: `np.where(mag >= gate_mask, mag, 0)` (hard gate) or soft gate with smooth transition
   - Reconstruct via `scipy.signal.istft()`
3. Measure RMS before/after
4. Convert back to pydub
5. Return result

**Key constants:**
- `_DEFAULT_GATE_THRESHOLD_DB = 3.0`
- `_DEFAULT_N_FFT = 2048`
- `_DEFAULT_HOP_LENGTH = 512`
- `_MIN_NOISE_REGION_MS = 100` — minimum noise profile length

### 2c. Combined Processing

```python
def reduce_noise(
    audio: AudioSegment,
    params: NoiseReductionParams,
) -> NoiseReductionResult:
```

This orchestrates both features based on the params flags. Both can be applied in sequence (hum removal first, then spectral gating).

---

## 3. Data Models: `noise_reduction/core/models.py`

```python
@dataclass
class NoiseReductionParams:
    # Hum removal
    reduce_hum: bool = False
    hum_frequency: int = 60  # 50 or 60 Hz
    hum_harmonics: int = 8  # number of harmonics to filter
    hum_quality: float = 30.0  # Q factor for notch filters

    # Broadband noise reduction
    reduce_broadband: bool = False
    noise_start_ms: int = 0  # start of noise profile region
    noise_end_ms: int = 500  # end of noise profile region
    gate_threshold_db: float = 3.0  # gating threshold in dB above noise floor

    # Common
    dry_run: bool = False


@dataclass
class NoiseReductionResult:
    audio: AudioSegment
    energy_before_db: float
    energy_after_db: float
    was_modified: bool
```

---

## 4. File Processor: `noise_reduction/core/file_processor.py`

Follows the `pop_click_remover/core/file_processor.py` pattern exactly:

- `NUM_WORKERS = 4`
- `process_single_file()` — single-file worker with slot queue
- `run_noise_reduction()` — `@handle_audio_errors` decorated entry point
- Uses `BaseFileProcessor.discover_audio_files()` for file discovery
- Uses `_refinery_completed.log` registry pattern (import from `audio_refinery.core.registry`)
- Dry-run support: measures and reports without writing

---

## 5. GUI: `noise_reduction/app.py`

Follows `pop_click_remover/app.py` pattern:
- `NoiseReductionApp(UIHelperMixin, AuditionMixin)`
- Three-tab notebook: Setup, Processing, Results
- `bootstrap_tool_app()` initialization
- Preset support via `suite_config`
- CLI argument bridging via `UniversalCLIHandler`
- Thread-safe slot vars, callback marshalling via `root.after(0, fn)`

### Setup Tab (`ui/setup_tab.py`)

**Controls:**
- Folder path picker
- Run mode: Dry Run / Live Update
- **Hum Removal panel** (collapsible):
  - Enable checkbox
  - Frequency selector: 50 Hz / 60 Hz (radiobuttons or dropdown)
  - Harmonics slider: 1–20 (default 8)
  - Quality slider: 1.0–100.0 (default 30.0)
- **Broadband Noise panel** (collapsible):
  - Enable checkbox
  - Noise profile start (ms): Spinbox
  - Noise profile end (ms): Spinbox
  - Gate threshold (dB): Slider 0.5–12.0
- Preset save/load/delete
- Start button

---

## 6. CLI: `noise_reduction/cli.py`

```python
@cli.command()
@_opt_dir
@_opt_dry_run
@_opt_json
@click.option("--hum", is_flag=True, help="Enable hum removal.")
@click.option("--hum-freq", type=click.Choice(["50", "60"]), default="60")
@click.option("--hum-harmonics", type=int, default=8)
@click.option("--broadband", is_flag=True, help="Enable broadband noise reduction.")
@click.option("--noise-start", type=int, default=0, help="Noise profile start (ms).")
@click.option("--noise-end", type=int, default=500, help="Noise profile end (ms).")
@click.option("--gate-threshold", type=float, default=3.0, help="Gate threshold (dB).")
def reduce_noise(directory, dry_run, json, hum, hum_freq, ...):
```

---

## 7. Refinery Integration

### 7a. Models (`audio_refinery/core/models.py`)

Add:
```python
@dataclass
class NoiseReductionParams:
    reduce_hum: bool = False
    hum_frequency: int = 60
    hum_harmonics: int = 8
    hum_quality: float = 30.0
    reduce_broadband: bool = False
    noise_start_ms: int = 0
    noise_end_ms: int = 500
    gate_threshold_db: float = 3.0
```

Add to `StageConfig`:
```python
reduce_noise: bool = False
noise_reduction_params: NoiseReductionParams = field(
    default_factory=NoiseReductionParams
)
```

### 7b. Pipeline (`audio_refinery/core/pipeline.py`)

Insert noise reduction stage after trim (stage 3) and before enhance (stage 4):
```
1. Validate → 2. Load → 3. Declick → 4. Trim → 5. **Noise Reduction** → 6. Enhance → 7. Export → 8. Normalise → 9. Atomic Replace
```

The noise reduction stage calls `noise_reduction.core.noise_reducer.reduce_noise()` directly (same composition pattern as declick/trim/enhance).

### 7c. Settings (`audio_refinery/utils/settings.py`)

Add load/save for `reduce_noise` toggle and `NoiseReductionParams` fields.

### 7d. Setup Tab (`audio_refinery/ui/setup_tab.py`)

Add `_build_noise_reduction_panel()` calling the generic `_stage_panel()` helper, with body controls for hum/broadband params.

### 7e. CLI Args (`audio_refinery/utils/cli_args.py`)

Add `--reduce-noise`, `--hum-freq`, `--hum-harmonics`, `--noise-start`, `--noise-end`, `--gate-threshold` to `RefineryArgs` and parser.

### 7f. Arg Builder (`master_driver/runner/arg_builder.py`)

Add `reduce_noise` to `stage_map` in `build_refinery_args()` and pass noise reduction params.

---

## 8. Master Driver Integration

### 8a. Tool Registration (`audio_suite_shared/tool_plugin.py`)

Register in `_build_default_registry()` under `"utility"` category:
```python
ToolManifest(
    id="noise_reduction",
    name="Noise Reduction",
    category="utility",
    pyw_filename="Noise_Reduction.pyw",
    description="Remove hum, hiss, and broadband noise from audio files.",
    standalone=True,
    default_on=False,
    cli_command="reduce-noise",
    order=50,
)
```

### 8b. CLI Registration (`audio_suite_shared/cli_app.py`)

Add: `import noise_reduction.cli  # registers "reduce-noise"`

### 8c. Master Driver Card (`master_driver/ui/cards/noise_reduction_card.py`)

Standard collapsible card with:
- Enable/disable checkbox (`module_toggles["noise_reduction"]`)
- Description label
- No tool-specific parameters (params are in the standalone app)

### 8d. Arg Builder

Add `"noise_reduction"` builder to `_build_utility_tool_args()`.

---

## 9. `.pyw` Launcher

`Noise_Reduction.pyw`:
```python
from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("noise_reduction")
from audio_suite_shared.launcher import parse_cli_args
from noise_reduction.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from noise_reduction.app import NoiseReductionApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    NoiseReductionApp(root)
    root.mainloop()
```

---

## 10. Test Plan

### `test_noise_reducer.py` (DSP engine — highest priority)

| Test | Description |
|---|---|
| `test_hum_removal_60hz` | Pure 60 Hz tone → energy drops below -60 dBFS after removal |
| `test_hum_removal_50hz` | Pure 50 Hz tone → energy drops below -60 dBFS |
| `test_hum_removal_harmonics` | 60 Hz + 120 Hz + 180 Hz → all three removed |
| `test_hum_removal_preserves_music` | 440 Hz sine → energy unchanged after hum removal |
| `test_hum_removal_stereo` | Both channels processed correctly |
| `test_spectral_gate_clean_silence` | Silence input → silence output, no modification |
| `test_spectral_gate_removes_noise` | Signal + noise, noise region provided → noise reduced |
| `test_spectral_gate_preserves_signal` | Strong signal above threshold → preserved |
| `test_combined_hum_and_gate` | Both features applied in sequence |
| `test_dry_run_no_modification` | Dry run returns original audio unchanged |
| `test_invalid_hum_frequency` | `AudioConfigurationError` on unsupported frequency |
| `test_invalid_harmonics_count` | `AudioConfigurationError` on harmonics < 1 or > 20 |
| `test_noise_region_too_short` | `AudioConfigurationError` on region < 100 ms |
| `test_corrupt_input` | Graceful error on corrupt/unreadable audio |

### `test_file_processor.py`

| Test | Description |
|---|---|
| `test_run_noise_reduction_dry` | Dry run processes files without writing |
| `test_run_noise_reduction_live` | Live mode processes and writes files |
| `test_empty_directory` | Error callback on empty directory |
| `test_error_handling` | Corrupt file triggers error callback, processing continues |

### `test_models.py`

| Test | Description |
|---|---|
| `test_defaults` | Default param values are sensible |
| `test_result_dataclass` | NoiseReductionResult fields accessible |

### `test_app.py`

| Test | Description |
|---|---|
| `test_instantiation` | `object.__new__` + MagicMock pattern |
| `test_start_button_disabled_during_run` | Button state management |
| `test_dry_run_mode` | Dry run flag passed correctly |

---

## 11. Execution Order

1. Create `noise_reduction/` package structure with `__init__.py` files
2. Implement `noise_reduction/core/models.py`
3. Implement `noise_reduction/core/noise_reducer.py` (DSP engine)
4. Write `test_noise_reducer.py` — verify DSP correctness first
5. Implement `noise_reduction/core/file_processor.py`
6. Write `test_file_processor.py`
7. Implement `noise_reduction/utils/cli_args.py`
8. Implement `noise_reduction/ui/` tabs (setup, processing, results)
9. Implement `noise_reduction/app.py`
10. Write `test_app.py`
11. Implement `noise_reduction/cli.py`
12. Register in `tool_plugin.py` and `cli_app.py`
13. Create `Noise_Reduction.pyw` launcher
14. Create `master_driver/ui/cards/noise_reduction_card.py`
15. Update `arg_builder.py`
16. **Refinery integration:** models → settings → pipeline → setup_tab → cli_args → arg_builder
17. Run full quality gate: `compileall`, `ruff`, `mypy --strict`, `bandit`, `pytest`
18. Update PLAN_gap_analysis.md progress log

---

## 12. Quality Gates

Before marking complete:
1. `python -m compileall -q -f .` — zero errors
2. `ruff check --fix . && ruff format .` — clean
3. `mypy . --strict` — zero errors
4. `bandit -r noise_reduction/` — clean
5. `pytest noise_reduction/tests/ -v` — all pass
6. `pytest audio_refinery/tests/ -v` — existing tests still pass (refinery integration)
7. Full suite `pytest` — zero regressions
