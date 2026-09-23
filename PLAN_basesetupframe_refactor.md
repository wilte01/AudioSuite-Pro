# PLAN — Extract Reusable `BaseSetupFrame` in `audio_suite_shared.ui_common`

**Status legend:** `[ ]` pending · `[~]` in progress · `[x]` done
**Working directory:** `D:\Users\wilte\Desktop\AudioSuite-Pro`
**Test runner:** `.venv\Scripts\python.exe -m pytest` (repo root)
**Rule:** every phase updates its tests in lockstep; zero test failures before a phase is marked done.
**Compile gate (mandatory after ANY import-chain edit, never bypass):** `python -m compileall -q -f .`

---

## Background (current-state inventory)

Every tool uses a notebook UI: tabs `1. Setup`, `2. Processing`, `3. Results`. The Results and
Processing tabs already live in shared builders (`audio_suite_shared/ui_common.py`:
`build_results_tab`, `build_processing_tab`, plus `path_row`, `slider_row`,
`discrete_slider_row`). The Setup tab is the **last** per-tool UI layer that has not been
extracted. **No `BaseSetupFrame` exists anywhere** (repo-wide grep returned zero matches).

Of 24 `.pyw` launchers, 19 tools have `ui/setup_tab.py` (~117–647 lines each). They repeat a
near-identical skeleton, with the preset-management block (~90–120 lines) being the largest
verbatim duplication:

| Boilerplate block | Occurrence | Notes |
|---|---|---|
| Root frame `tk.Frame(padx=30, pady=30, bg=BG_WHITE)` + `.pack(expand, fill)` | 19/19 | asx uses `padx=40`; refinery `24/16` |
| Title label (`FONT_TITLE`, `pady=(0, 20)`) | 19/19 | asx uses `FONT_TITLE_L`, `pady=(0,25)` |
| `DriverControlsPanel` assembly + `.set_driven()` | 16/19 | missing only in enhancer/normalizer/cd_ripper |
| Preset row (combo + Save/Delete + dialog + refresh) | 17/19 | ~90–120 lines duplicated verbatim |
| Start button `BEGIN …` (`side=BOTTOM, fill=x, pady=10, height=2`) | 18/19 | asx packs `fill="x"` (no side) |
| Parallel/Workers row | bpm, key_detector, silence_trimmer | identical ~35-line block |
| `" Configuration "` LabelFrame | ~9 tools | part of `build_config_panel` exports |

`audio_enhancer` and `audio_refinery` already factored the preset dialog into module-level
`_save_preset_dialog` / `_delete_preset_action` helpers — duplicated between the two modules.
That duplication must be promoted into the shared module and re-imported.

### Cross-tool imports that MUST NOT break (constraint list)

`audio_refinery/ui/setup_tab.py` imports these module-level builders from tool setup tabs —
**their current signatures must remain byte-identical** after migration:

- `audio_normalizer.ui.setup_tab.build_config_panel(parent, run_mode, target_lufs, tolerance)`
- `silence_trimmer.ui.setup_tab.build_config_panel(parent, run_mode, threshold, fade_var, fade_in_duration, fade_out_duration, parallel_mode=None, max_workers=None)`
- `pop_click_remover.ui.setup_tab.build_config_panel(...)` (signature to be recorded during Phase 0 audit)
- `audio_enhancer.ui.setup_tab.build_dsp_sliders(parent, params) -> (dict, dict)`

**Phase 0 audit step:** run `rg "setup_tab" -l` (or grep) across the repo and record EVERY
external importer of any tool's `ui/setup_tab.py` before editing anything. Do not rely on the
four above alone.

---

## Design — new shared code in `audio_suite_shared/ui_common.py`

### 1. Module-level preset helpers (replace all duplicated copies)

```python
def save_preset_dialog(combo: ttk.Combobox, on_save: Callable[[str], None]) -> None:
    """Shared "Save Preset" modal (Toplevel 350x150, Return-to-save)."""


def delete_preset_action(
    combo: ttk.Combobox, on_delete: Callable[[str], None] | None
) -> None:
    """Shared confirm-and-delete for the currently selected preset."""
```

Both are exact ports of the bodies already copied into `audio_enhancer` / `audio_refinery`
(and inline in ~13 other tools). Note the two source variants differ subtly on parent wiring:
- inline copies use `tk.Toplevel(frame)` + `transient(frame.winfo_toplevel())`
- enhancer/refinery copies use `tk.Toplevel()` + `transient()`

Use the inline variant (`Toplevel(combo.winfo_toplevel())`-style parented to the combo's
toplevel) so the dialog stays parented correctly in both standalone and embedded contexts.
Mirrors existing behavior; no visual change.

### 2. `class BaseSetupFrame(tk.Frame)` API

Constructor signature (all shared state injected; end result: `self.pack(expand=True,
fill="both")` in `__init__`):

```python
def __init__(
    self,
    parent: tk.Frame,
    *,
    title: str,  # tool title label text
    start_text: str,  # e.g. "BEGIN BPM ANALYSIS"
    on_start: Callable[[], None],
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    on_browse: Callable[[], None] | None = None,
    driver_locked: bool = False,
    preset_names: list[str] | None = None,
    preset_loader: Callable[[], list[str]] | None = None,  # bpm pattern
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    browse_text: str = "Browse...",  # metadata_scrubber uses "Browse & Scan" (tier 3)
    modes: tuple[str, str] | None = None,  # asx custom mode labels
    include_controls_panel: bool = True,  # False for enhancer/normalizer
    padx: int = 30,
    pady: int = 30,
    title_font: object = styles.FONT_TITLE,  # asx uses FONT_TITLE_L
    title_pady: tuple[int, int] = (0, 20),  # asx uses (0, 25)
) -> None: ...
```

`__init__` ends with `self.pack(padx=0, pady=0)` adjusting via the padx/pady params baked into
the `super().__init__(parent, padx=padx, pady=pady, bg=styles.BG_WHITE)`, then calls
`self._layout()`.

Template methods / public attributes (fully typed for `mypy --strict`):

```python
def _layout(self) -> None:
    """Standard skeleton ordering. Override to reorder additive methods."""
    self._add_title()
    if self._include_controls_panel:
        self._add_controls_panel()
    self._add_preset_row()
    self._build_options()  # subclass hook
    self._add_start_button()


def _build_options(self) -> None:
    """Per-tool hook. Subclass emits its tool-specific widgets here."""


def _add_title(self) -> None: ...
def _add_controls_panel(self) -> None: ...  # wraps DriverControlsPanel + set_driven
def _add_preset_row(
    self,
) -> None: ...  # gated: renders only when on_save_preset is not None
def _add_start_button(
    self,
) -> None: ...  # text=self._start_text, side=BOTTOM, fill=x, pady=10, height=2


def add_config_group(self, text: str) -> tk.LabelFrame:
    """Standard ' Configuration ' LabelFrame: bg=BG_WHITE, fg=FG_MAIN, padx=15, pady=15,
    packed fill='x', pady=20."""


def add_parallel_row(
    self, parallel_mode: tk.BooleanVar, max_workers: tk.IntVar, caption: str
) -> None:
    """Checkbutton 'Parallel Processing' + 'Workers:' entry + caption, filled x."""


# Public handles:
#   self.start_btn: tk.Button
#   self.controls_panel: DriverControlsPanel | None
#   self.preset_combo: ttk.Combobox | None
#   self.refresh_preset_list(names: list[str] | None = None) -> None
```

`refresh_preset_list` semantics (covers all three existing call patterns):
1. `names` not None → set combo values = `names`.
2. `names` is None and `preset_loader` set → set combo values = `preset_loader()`.
3. otherwise → set combo values = `preset_names`.
4. Always: if the current combo selection is not in the new values, clear it (`combo.set("")`).

`get_widgets() -> dict[str, Any]` convenience returning the common dict:
`{"start_btn", "controls_panel", "preset_combo", "refresh_preset_list"}` (omit keys for widgets
that were not built, e.g. `preset_combo` when the preset row is hidden).
**Each tool's `build()` SHOULD assemble its own exact return** (dict keys or tuple) so the
existing contract is preserved byte-for-byte — do NOT rely on `get_widgets()` to normalize
differing key names (e.g. silence_trimmer uses `"refresh_presets"`).

### 3. Preset row gating — intentional normalization (flagged)

Today enhancer/refinery/scrubber hide the preset row when `on_save_preset is None`, while
bpm/mood_tagger/silence_trimmer render it (inert) regardless. Base rule: **render only when
`on_save_preset is not None`.** All 16 target tools pass `on_save_preset` from their apps, so
this does not change any real build path. Flagged here so the executor is not surprised.

---

## Phase 0 — Shared base + shared tests  [x] DONE

**File: `audio_suite_shared/ui_common.py`** (also satisfies AGENTS.md one-file-per-module
mapping: tests go in `audio_suite_shared/tests/test_ui_common.py`).

1. `save_preset_dialog` / `delete_preset_action` module-level helpers (§Design.1).
2. `BaseSetupFrame` class (§Design.2), fully annotated for `mypy --strict`.

**Tests: `audio_suite_shared/tests/test_ui_common.py`** (uses session-scoped hidden Tk root
from `conftest.py`; follow the `object.__new__` + `MagicMock` convention in AGENTS.md where a
full Tk is not desired).
- [x] `TestBaseSetupFrameLayout`: subclass with empty `_build_options`; assert title text,
  `controls_panel` is `DriverControlsPanel`, `start_btn` is `tk.Button`, `get_widgets()` keys.
- [x] `TestSetDriven`: `driver_locked=True` locks controls_panel (`source_entry` disabled);
  `False` → editable; Auto Start always disabled.
- [x] `TestPresetRow`: visible only when `on_save_preset` set; combo values seeded from
  `preset_names`; `refresh_preset_list(["A","B"])` updates values; stale selection cleared;
  loader path (`preset_loader`) honored on no-arg call.
- [x] `TestConfigGroup` / `TestParallelRow`: `add_config_group` returns LabelFrame with text;
  `add_parallel_row` yields "Parallel Processing" and "Workers:" descendant texts.
- [x] `TestOrderingOverride`: subclass overriding `_layout()` puts presets before controls.
- [x] `TestPresetHelpers`: `save_preset_dialog` shows dialog + invokes `on_save` with the
  typed name (drive via `MagicMock`); `delete_preset_action` asks `askyesno` (patch
  `tkinter.messagebox`) and calls `on_delete` only on confirm.
  (Implemented as `TestSavePresetDialog` / `TestDeletePresetAction` in
   `test_ui_common.py`.)

**Gate:** full verification pipeline (§Verification). Mark Phase 0 done only on zero failures.

---

## Phase 1 — Pilot migration (2 tools)  [x] DONE

Prove the pattern on one pristine tool + one variation tool before scaling.

### 1a. `mood_tagger/ui/setup_tab.py` (196 lines, standard shape)  [x] DONE

Current contract (verified): title → controls → presets → info LabelFrame → start; returns
`{"start_btn", "refresh_preset_list", "preset_combo", "controls_panel"}`.

Rewrite:
```python
def build(parent, folder_path, run_mode, auto_start_var, auto_end_var,
          clear_logs_var, parallel_var, on_browse, on_start,
          driver_locked=False, preset_names=None,
          on_save_preset=None, on_delete_preset=None, on_preset_selected=None):
    frame = _SetupFrame(parent, title="Mood Analyzer",
                        start_text="BEGIN MOOD ANALYSIS", on_start=on_start, ...)
    return frame.get_widgets()

class _SetupFrame(BaseSetupFrame):
    def _build_options(self):
        # Move the existing 'How Mood Is Determined' info_frame block here,
        # now packing into self (the base frame) via `tk.LabelFrame(self, ...)`.
```

### 1b. `silence_trimmer/ui/setup_tab.py` (283 lines, ordering + export variation)  [x] DONE

Current contract (verified): title → **presets** → controls → Configuration LabelFrame
(`build_config_panel(...)`) → start; returns
`{"start_btn", "refresh_presets", "preset_combo", "controls_panel"}` (note key
`refresh_presets`, not `refresh_preset_list`). Also exports module-level
`build_config_panel(parent, run_mode, threshold, fade_var, fade_in_duration,
fade_out_duration, parallel_mode=None, max_workers=None)` used by Audio Refinery.

Rewrite:
- `class _SetupFrame(BaseSetupFrame)` overriding `_layout()` to order presets BEFORE the
  controls panel, matching today's visual order:
  ```python
  def _layout(self):
      self._add_title()
      self._add_preset_row()
      self._add_controls_panel()
      self._build_options()
      self._add_start_button()
  ```
- `_build_options()` creates the `" Configuration "` LabelFrame via `add_config_group` and
  calls `build_config_panel(cfg, None, threshold, fade_var, fade_in_duration,
  fade_out_duration, parallel_mode=parallel_mode, max_workers=max_workers)` (same call as
  today; `run_mode=None` keeps the parallel row inside the panel as today).
- Keep **`build_config_panel` byte-identical** at module level (refinery import).
- `build()` returns the dict with key `refresh_presets` mapped to the frame's
  `refresh_preset_list` attribute.

**Tests:** both tools' existing `tests/test_setup_tab.py` must pass **unchanged**
(they assert `start_btn`/`preset_combo`/`refresh_preset*` types and descendant texts).

- [x] silence_trimmer/tests/test_setup_tab.py passes unchanged (13/13).
- [x] build_config_panel export verified byte-identical; audio_refinery call site
      (`trim_ui.build_config_panel(body, run_mode, ...)` positional) unchanged.
- [x] `app.py` consumes `refresh_presets` key; `_layout` override puts presets above
      controls; tool option state bound before `super().__init__` (base calls
      `_layout()` during construction).
- [x] Full verification pipeline passed (compile, ruff, mypy --strict, pytest 5423
      passed / 75.89% cov). silence_trimmer/ui/setup_tab.py now 100% covered.

**Gate:** full verification pipeline. Both apps still launch; silence_trimmer visual order
preserves presets-above-controls.

---

## Phase 1.5 — Lessons learned from the pilot (apply before Phase 2)  [x] RECORDED

Empirically surfaced while executing 1b. Each item below must be resolved or
honoured by Phase 2 executors before editing each Tier-1 tool.

### 1. Subclass option state MUST be bound before `super().__init__()` (crash trap)

`BaseSetupFrame.__init__` calls `self._layout()` → `_build_options()` **during**
construction. Any `tk.Variable` / state the subclass needs in `_build_options`
that arrives via the subclass constructor must be assigned to `self` **before**
`super().__init__(parent, **kwargs)`. Doing it after caused
`AttributeError: '_SetupFrame' object has no attribute '_threshold'`.

Canonical recipe (mirrors `silence_trimmer._SetupFrame`):
```python
def __init__(self, parent, *, <tool vars...>, **kwargs):
    self._my_var = my_var           # bind BEFORE super()
    super().__init__(parent, **kwargs)
```
Affects every Phase-2/3 tool whose `_build_options` reads tool vars (key_detector,
music_format_converter, bpm, enhancer, normalizer, …).

### 2. `**kwargs: Any` subclass forwarding — accepted, with a known edge

`**kwargs: Any` passes `mypy --strict`, but a typo in a forwarded key is invisible
to mypy; it fails at runtime as a `TypeError` from the base's keyword-only
signature (fast-fail, so acceptable). Do NOT add `# type: ignore` for this.
Alternative (explicit forwarding of all ~20 base params) buys full type-checking
at significant verbosity — only worth it if a tool needs conditional base also.

### 3. asx start button packs `fill="x"` with NO `side` — base hardcodes `BOTTOM`

`BaseSetupFrame._add_start_button()` always packs `side=tk.BOTTOM`. asx's
`start_btn.pack(fill="x")` (asx_extractor/ui/setup_tab.py:178) cannot be expressed
by the base as built. Resolve BEFORE asx migration, one of:
- (recommended) **additive base param** `start_side: str | None = "bottom"`;
  `_add_start_button` omits `side` when None. Backward compatible — no existing
  tool changes; add base test coverage for `start_side=None`.
- asx-local `_add_start_button()` override (zero base diff, duplicates the button
  block — not preferred since 18 others share the base).

**RESOLVED during Phase 2:** added `start_side: str | None = "bottom"` to the base
constructor (omits the pack `side` when None) with base-test coverage
(`test_start_btn_omits_side_when_none`). asx_extractor and music_format_converter
pass `start_side=None`. asx's FONT_TITLE start font and missing pady normalized to
the base canonical (flagged minor).

### 4. Minor spacing/palette normalizations are now FLAGGED, not silent

Base canonical values: preset row & controls panel `pady=(0, 15)`, config group
`pady=20` / `fg=styles.FG_MAIN`. Some tools differ: silence_trimmer &
pop_click_remover controls `pady=(0, 10)`; pop_click_remover's " Configuration "
uses `fg=styles.FG_SUB`; silence_trimmer preset row `pady=(0, 10)`. Tests do NOT
assert spacing/colors, so these deltas are invisible to CI — accept the base
canonical values (same "intentional normalization" policy as preset-row gating).
Phase 4 visual spot-check is the mitigation.

### 5. pop_click_remover `build_config_panel` signature — now recorded (was "during audit")

`build_config_panel(parent, run_mode, sensitivity: tk.DoubleVar, max_width: tk.IntVar)`
packs directly into `parent` (NO internal LabelFrame) — so wrapping it in
`add_config_group` is correct (same pattern as silence_trimmer; no LabelFrame
nesting trap). Refinery imports it. Keep byte-identical; `run_mode=None` when
embedded.

### 6. Verification-gate `bandit -r src/` is WRONG — no `src/` exists

Corrected command in §Verification below. Also `bandit -r .` scans `.venv`
(1.39M LOC) unless a target is given, and a Windows-cp1252 console crashes the
txt formatter unless `PYTHONIOENCODING=utf-8`. Scan only the touched tool trees:
`python -m bandit -r <touched> <audio_suite_shared>` with `PYTHONIOENCODING=utf-8`;
expect pre-existing B101 `assert_used` findings in `tests/` (they are not
excluded when explicit dirs are passed) — informational, do NOT "fix" asserts.

---

## Phase 2 — Tier 1: remaining 10 standard tools  [x] COMPLETE

Same pattern as mood_tagger: title → controls → presets → `_build_options()` → start; each
tool's `build()` returns its current dict verbatim (verify each file's exact return-key names
before editing — do not assume; see Phase 0 audit). Delete the inline preset-row block, the
inline `_save_preset_dialog`/`_delete_preset` closures, and the folder/mode duplication in each.

**Phase 2 audit (recorded before editing):** external importers of Tier-1 setup_tab modules
are each tool's own `app.py` + `tests/` only, EXCEPT `pop_click_remover.ui.setup_tab`
(imported by `audio_refinery.ui.setup_tab` as `declick_ui` → keep `build_config_panel`
byte-identical) and `audio_refinery/tests/test_setup_tab.py`. Per-app build-call kwargs match
the existing build signatures verbatim — build() signatures stay byte-identical, only the
frame internals migrate to `_SetupFrame(BaseSetupFrame)`.

| Tool | File | Specific custom bits to preserve |
|---|---|---|
| album_art_normalizer | `album_art_normalizer/ui/setup_tab.py` | **no preset params** in build/app → `on_save_preset=None` hides the row; returns `{"start_btn","controls_panel"}`; tool options = resolution combo |
| album_genre_tagger | `album_genre_tagger/ui/setup_tab.py` | standard; options = min-coverage entry + info box |
| asx_extractor | `asx_extractor/ui/setup_tab.py` | `modes=("Dry Run (Simulated)","Execute Extraction (Permanent)")`, `padx=40`, `title_font=styles.FONT_TITLE_L`, `title_pady=(0,25)`, `start_text="START EXTRACTION"`, `start_side=None` |
| genre_sync | `genre_sync/ui/setup_tab.py` | standard; options = description text |
| key_detector | `key_detector/ui/setup_tab.py` | parallel row → use `add_parallel_row(..., "(ProcessPoolExecutor bypasses GIL for chroma CQT)")`; options = duration entry |
| mood_batch_tagger | `mood_batch_tagger/ui/setup_tab.py` | standard; options = "How It Works" LabelFrame |
| music_format_converter | `music_format_converter/ui/setup_tab.py` | presets BEFORE controls (`_layout` override); FFmpeg warning rendered in an `_add_controls_panel` override (stays above controls); start `start_side=None`; 7-key return incl. update_detected_label / update_format_menu / update_format_info |
| noise_reduction | `noise_reduction/ui/setup_tab.py` | presets BEFORE controls (`_layout` override); hum/broadband LabelFrames + sliders |
| pop_click_remover | `pop_click_remover/ui/setup_tab.py` | **module-level `build_config_panel` export used by refinery — keep byte-identical**; presets BEFORE controls; config group via `add_config_group` |
| replaygain_analyzer | `replaygain_analyzer/ui/setup_tab.py` | `presets=` param name; **override `refresh_preset_list` to select-first**; save via shared dialog (simpledialog normalized away) |
| tempo_analyzer | `tempo_analyzer/ui/setup_tab.py` | `on_preset_select=` param name (app contract); **override `refresh_preset_list` to select-first**; `update_reference` closure kept; scheme trace + reference table in `_build_options` |

Per tool:
- [x] After editing, run that tool's `tests/test_setup_tab.py` in isolation.
- [x] Confirm the tool's `app.py` consumes the returned dict keys exactly as before (grep
  `setup_tab.build(` in the tool's `app.py`).

**Additional requirements discovered during migration (not in the audit table):**
- `genre_sync` ALSO renders the preset row unconditionally — its `tests/test_ui.py` builds
  without any preset callbacks yet expects `preset_combo`/`refresh_preset_list`. Pass
  `preset_row_always=True` (replaygain is not the only tool needing it).
- `genre_sync/tests/conftest.py:132` patches `genre_sync.ui.setup_tab.DriverControlsPanel`
  exactly like replaygain's `test_app.py` — the module needs the same
  `from audio_suite_shared.ui_driver_controls import DriverControlsPanel as
  DriverControlsPanel` re-export. Scan each tool's `tests/conftest.py` for such patches
  BEFORE editing, not just `tests/test_app.py`.

**Gate:** full verification pipeline.

**Phase 2 complete (all 11 Tier-1 tools, incl. pilot-adjacent album_art_normalizer).** All
`build()` signatures and return dict keys preserved; per-tool notes above honoured. Full
verification pipeline passed: `compileall` clean; `ruff check --fix` applied 13 auto-fixes
(re-strip unused imports) and `format` reformatted 1 file (all suites re-run green after);
`mypy . --strict` clean on 383 source files; bandit showed only the pre-existing baseline
(no new findings — migrated `setup_tab.py` files have zero findings); full `pytest` 5515
passed, 6 skipped (env-gated), 76.57% coverage (≥ 75% gate). Tool suites: all 11 migrated
tools + audio_refinery + audio_suite_shared = 3411 passed in the consolidated run.

---

## Phase 3 — Tier 2: variation tools (4)  [x] COMPLETE

### 3a. `bpm_analyzer/ui/setup_tab.py` (249 lines)

Current contract (verified): title → controls → presets → BPM range → duration → parallel
row → start; returns the standard dict. `refresh_preset_list` closure **loads from
`suite_config.load_value("bpm_presets_list", …)`** (app calls it with NO args).

- Subclass passes `preset_loader=lambda: json.loads(suite_config.load_value(
  "bpm_presets_list", None) or "[]")`; `_build_options()` recreates the BPM range, duration,
  and parallel rows (`add_parallel_row(..., "(ProcessPoolExecutor bypasses GIL for CPU-bound
  FFT)")`).
- Keep `import json` and the existing imports (`styles`, `suite_config`,
  `DriverControlsPanel` now comes via the base).

### 3b. `audio_enhancer/ui/setup_tab.py` (254 lines)

Current contract (verified): no `DriverControlsPanel`; **tuple return
`(start_btn, refresh_preset_list_or_None, param_values)`**; preset row gated on
`on_save_preset`; exports `build_dsp_sliders(parent, params) -> (dict, dict)` (refinery).

- `class _SetupFrame(BaseSetupFrame)` with `include_controls_panel=False`; `_build_options()`
  adds `ui_common.path_row` source/output, the `" Configuration "` LabelFrame with the preset
  selector + Custom DSP LabelFrame using the untouched `build_dsp_sliders`.
- Replace local `_save_preset_dialog`/`_delete_preset_action` with the shared helpers (they
  now delegate via `save_preset_dialog(self.preset_combo, on_save_preset)`).
- `build()` returns the tuple; `refresh` element is `None` when the preset row is absent
  (i.e. `frame.preset_combo is None` → `None`, else `frame.refresh_preset_list`).
- Keep `build_dsp_sliders` **byte-identical**.

### 3c. `audio_normalizer/ui/setup_tab.py` (267 lines)

Current contract (verified): no `DriverControlsPanel`; **tuple return
`(start_btn, refresh_preset_list, preset_combo)`**; presets → `path_row` (folder) →
Configuration LabelFrame via `build_config_panel`; exports `build_config_panel` (refinery).

- `class _SetupFrame(BaseSetupFrame)` with `include_controls_panel=False`; `_build_options()`
  adds `path_row(frame, "Music Directory:", folder_path, on_browse)` + `add_config_group`
  calling the untouched module-level `build_config_panel(cfg, run_mode, target_lufs, tolerance)`.
- `build()` returns the 3-tuple from `frame`.
- Keep `build_config_panel` **byte-identical**.

### 3d. Refinery export regression check

- [x] `audio_refinery` imports at module import time, so any signature drift breaks the whole
  app at launch (and the Master Driver preflight). After Phases 2–3, run:
  `python -c "import audio_refinery.ui.setup_tab"` plus the four source modules.
- [x] Run `plans/phase` note: `audio_refinery/ui/setup_tab.py` is NOT migrated in this plan
  (tier 3). Its local `_save_preset_dialog`/`_delete_preset_action` can be swapped for the
  shared imports as an isolated low-risk cleanup if desired — record as follow-up, not here.

**Gate:** full verification pipeline, then app-launch smoke test for bpm, enhancer, normalizer.

**Phase 3 complete (all 3 Tier-2 variation tools).** Per-tool contracts preserved:
- `bpm_analyzer/ui/setup_tab.py`: standard dict return via `get_widgets()`; the app's
  zero-argument Save/Delete callbacks (simpledialog-based) are captured as explicit subclass
  params — the only tool that cannot use the base's shared preset dialog, so `_add_preset_row`
  is overridden verbatim; `preset_loader` reproduces the `suite_config.load_value("bpm_presets_list")`
  refresh path (app calls it with no args).
- `audio_enhancer/ui/setup_tab.py`: `include_controls_panel=False`; tuple return
  `(start_btn, refresh_or_None, param_values)`; `build_dsp_sliders` byte-identical (refinery
  consumes it at import time); local preset helpers deleted — base shared dialog used;
  placeholders injected for the base's required panel vars; `ui_common` remains a module
  attribute (test_processor imports it).
- `audio_normalizer/ui/setup_tab.py`: `include_controls_panel=False`; tuple return
  `(start_btn, refresh_preset_list, preset_combo)`; `build_config_panel` + `_closest_lufs_index`
  byte-identical (refinery + tests consume them).
- `include_controls_panel=False` required dummy `auto_start_var`/`auto_end_var` (and for
  enhancer a `folder_path`/`run_mode`) placeholders — base requires the panel vars even when
  the panel is not built; noted as a base-contract quirk.

**Superseded (driver-parity follow-up):** the enhancer and normalizer exclusions above were
later reverted deliberately. Both now use `include_controls_panel=True` with the full shared
`DriverControlsPanel` (Source bar, 3-way Mode, Auto Start/End, Clear Logs, Parallel), with the
driver vars threaded through `setup_tab.build()` and the apps' `_apply_cli_args`. The
`include_controls_panel=False` + dummy-placeholder quirk therefore remains only for the
migrated tools that never adopted the panel (bpm, refinery, asx, cd_ripper…).
- Refinery import gate passed for all six source modules; full verification pipeline passed:
  `compileall` clean; `ruff check --fix` / `format` clean; `mypy . --strict` clean (381 source
  files); bandit zero findings on all three migrated setup_tab files (asserts replaced with
  `cast` narrowing to keep parity with the Phase-2 "zero findings" bar); full `pytest` 5426
  passed, 6 skipped (env-gated), 76.86% coverage (≥ 75% gate). App-boot smoke test launched
  all three apps headlessly (start buttons rendered `BEGIN BPM ANALYSIS` / `BEGIN ENHANCEMENT`
  / `BEGIN NORMALIZATION`).

---

## Phase 4 — Final sweep  [x] COMPLETE

1. `rg -l "setup_tab"` re-audit: confirm no external file imports anything that changed
   besides the four recorded exports.
2. Manual visual spot-check (standalone launch): at least one Tier-1 tool, plus
   silence_trimmer (ordered presets), plus audio_enhancer (no controls panel). Verify the
   Master Driver launch path of one tool too.
3. Run the complete verification pipeline one final time (§below).

**Phase 4 complete (final sweep).** All four recorded export signatures re-verified
byte-identical (`normalise_ui.build_config_panel`, `trim_ui.build_config_panel`,
`declick_ui.build_config_panel`, `enhancer_ui.build_dsp_sliders` at
`audio_refinery/ui/setup_tab.py`); the re-audit found NO external cross-tool importer beyond
those four (remaining hits are per-tool self-references or Tier-3 modules importing their
own unchanged files). Launch-path smoke test (real Tk, `.pyw`-identical boot sequence):
mood_tagger (title → controls → presets → options → start; `BEGIN MOOD TAGGING`),
silence_trimmer (`BEGIN SILENCE TRIMMING`, presets row ordered ABOVE the controls panel,
`" Configuration "` LabelFrame), audio_enhancer (`BEGIN ENHANCEMENT`, `controls_panel is
None`, no `DriverControlsPanel` descendant, tuple-return refresh callable), and the Master
Driver path (`guard_or_exit()` compiles clean, `AudioSuiteDriver` builds, `mood_tagger`
manifest resolves to `Mood_Tagger.pyw` and launches through the driver's subprocess
launcher to an existing suite-root path) — all PASS. Full verification pipeline green:
`compileall` clean; `ruff check --fix` clean / `format` 624 files unchanged; `mypy . --strict`
clean (381 source files); bandit on the 16 migrated trees + `audio_suite_shared` shows only
the pre-existing baseline (B101 `assert_used` in `tests/`, informational; 4 pre-existing
`_default_open_log` subprocess hits in `ui_common.py` — none in migrated `setup_tab.py` files
or new `BaseSetupFrame`/preset-helper code); full `pytest` 5426 passed, 6 skipped
(env-gated), 76.86% coverage (≥ 75% gate) — identical to the Phase 3 tail. Remaining for the
user: a final on-screen glance at `Mood_Tagger.pyw` / `Silence_Trimmer.pyw` /
`Audio_Enhancer.pyw` / `Master_Driver.pyw` (structural verification is programmatic here).

---

## Verification gate (each phase, in this order)

```bash
python -m compileall -q -f .            # mandatory import gate — never bypass
.venv\Scripts\python.exe -m ruff check --fix .
.venv\Scripts\python.exe -m ruff format .
.venv\Scripts\python.exe -m mypy . --strict
$env:PYTHONIOENCODING='utf-8'           # Windows cp1252 console crashes bandit txt formatter
.venv\Scripts\python.exe -m bandit -r silence_trimmer audio_suite_shared
.venv\Scripts\python.exe -m pytest      # runs configured testpaths + 75% cov gate
```

(`bandit -r src/` is invalid here — no `src/` exists, and `-r .` drags in `.venv`
(~1.39M LOC). Scan the touched tool trees only, as shown. Pre-existing B101
`assert_used` findings in `tests/` are expected with explicit-dir scans —
informational, do not "fix" asserts.)

---

## Out of scope (tier 3, this plan explicitly does NOT touch)

- `audio_refinery/ui/setup_tab.py` — composite collapsible stage panels; adopt shared preset
  helpers only as a follow-up.
- `metadata_scrubber/ui/setup_tab.py` — class-based with dynamic tag canvas.
- `album_art_sync/ui/main_tabs.py` (`build_setup_tab`) — LabelFrame-variant preset row.
- `cd_ripper/ui/setup_tab.py` — sub-panel architecture, "PROCEED TO RIP".
- `file_reorganizer`, `library_stats`, `tag_field_updater`, `master_driver` — no setup tab.

## Risks & guardrails

- **Return-contract drift:** each `build()` must reproduce its exact current dict keys /
  tuple shape. Verify per tool against the source before editing (the per-tool Existing
  Contract checks above).
- **Refinery import coupling:** `build_config_panel`/`build_dsp_sliders` must stay
  byte-identical in signature and behavior. Guard with Phase 3d.
- **`refresh_preset_list` no-arg calls:** bpm's app calls the refresh with no arguments — the
  `preset_loader` path covers it; do not regress to a names-only signature.
- **Do NOT weaken the preflight guard** (`audio_suite_shared/preflight.py`,
  `Master_Driver.pyw`) — the compileall Step 0 is the mitigation for syntax regressions.

## Follow-ups (post-plan, not executed here)

- [ ] Swap `audio_refinery` + `audio_enhancer` local preset helpers for shared imports.
- [ ] Migrate `album_art_sync` preset row + `metadata_scrubber` preset row onto shared helpers.
- [ ] Decide whether `get_widgets()` should become the single canonical return path on a
  future app.py standardization pass (requires updating all app consumers — deferred by design).