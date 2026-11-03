# AudioSuite-Pro — Code and Functionality Audit

**Date:** 2026-11-03
**HEAD:** `c124142` ("Refresh uv.lock for the 2.4.0 release"), tag `v2.4.0`
**Scope:** code quality (readability, maintainability, gold standards, duplicated
code and shared-module opportunities) and functionality gaps that enhance audio
manipulation. AudioSuite-Pro is treated as a batch library-processing suite, not
a player.
**Status:** audit only. No production code was changed. This file is the only
addition to the working tree.

---

## 0. Verdict at a glance

**Code.** The codebase is materially better than the average Python desktop
suite of this size. Ruff, Ruff-format, strict mypy, Bandit and the full
11,197-test suite are green at HEAD; the shared layer is real and widely adopted
(27 shared modules are imported by
three or more tools); audio-correctness rules are written down, tested and
enforced. The debt is structural rather than sloppy: three competing sources of
truth (DSP models, format taxonomy, tag layer), a GUI application layer that is
still duplicated across most tools, and a handful of oversized modules and
functions that concentrate risk. No release-blocking defect was found by static
inspection, but the duplicated model/format/tag paths are the class of defect
this repo has previously shipped (2.1.7 normaliser, 2.1.3 album-art config,
Metadata Scrubber discovery), so they belong in the "must" tier.

**Functionality.** Coverage is unusually broad for batch library work: tagging,
identity lookup, loudness, conversion, restoration, stem separation, duplicate
handling, CD ripping, spectral viewing and a five-stage repair pipeline. The gap
is DSP depth and channel/album awareness: no EQ, no controllable dynamics stage,
no pitch/time tools, no channel operations, no album-mode loudness, no generic
split/join, no multichannel authoring, no spectral repair and no plugin hosting.

### Top findings

| # | Finding | Tier | Impact |
|---|---|---|---|
| 1 | Two `EnhancementParams`/`PresetName`/`PRESETS` definitions with already-divergent defaults (`audio_suite_shared/dsp_models.py` vs `audio_enhancer/core/models.py`) | MUST | UI shows one preset table; the pipeline applies another |
| 2 | Two format taxonomies (`audio_formats.py` vs `music_format_converter/core/formats.py`); `.wma` is a converter format but invisible to every shared-discovery tool | MUST | Same class as the 2.1.3 scrubber discovery defect |
| 3 | `tag_field_updater` is a second, direct-mutagen tag layer alongside the shared `tag_helper` handlers | MUST | Tag semantics and undo can diverge per tool |
| 4 | GUI scaffolding still duplicated: 18 of 23 `app.py` files build their own notebook/help/run-controls shell; 11,104 `app.py` lines plus 6,964 `setup_tab` lines | MUST | Every cross-cutting UI change is O(n); theme defects came from this |
| 5 | Audio decode/measurement is split across seven FFmpeg paths (ReplayGain, Refinery measure, Normalizer loudness, Enhancer I/O, Converter params, lossless gain, analysis loader) | MUST | Loudness/peak/duration verdicts can disagree between tools |
| 6 | 186 broad `except Exception` sites and no `BLE` Ruff rule | MUST | A DSP or tag write failure can be swallowed as a "skip" |
| 7 | Eight modules over 1,000 lines, 122 functions over 100 lines | MUST | Review and test cost concentrate exactly where audio is written |
| 8 | `tag_helper_base` imports six handlers at the bottom with `# noqa: E402` (import cycle) | MUST | Fragile import order; a frozen-build regression waits here |
| 9 | CLI handshake parsing hand-rolled per tool (`_scan_value_options` x4, `looks_like_driver_argv` x4) | MUST | Driver flags can be silently ignored by one tool |
| 10 | No album-mode loudness, EQ, dynamics, pitch/time, channel ops, split/join, multichannel, spectral repair or plugin hosting | Feature | The genuine audio-manipulation gap versus RX/Acoustica-class tools |

---

## 1. Method and limits

### What was done

- Structural metrics over 558 non-test Python modules (AST: module/function/class
  sizes, branch counts, docstrings).
- A token-based clone detector: every file normalised to token types (names,
  strings and numbers collapsed), 60-token windows hashed, windows shared by two
  to five files reported. This finds copy-paste even after variable renames; it
  is not a semantic clone detector.
- Import-graph scan of all 23 tool packages to measure shared-module adoption.
- Manifest, CLI, GUI and DSP module reading; targeted greps for capability
  keywords (pitch, time-stretch, EQ, dither, crossfade, concat, downmix, upmix,
  gapless, chapters, VST, spectral repair).
- The repository's own gate: `ruff check .`, `ruff format --check .`,
  `python -m mypy .`, `bandit -r . -x ./.venv -c pyproject.toml`.
- Test collection (`pytest --collect-only`) and the full suite run:
  11,197 passed, 3 skipped, 35 deselected in 20m56s (exit 0).

### What was not done

- No manual GUI click-through and no listening test. Findings about UI and
  sound are structural, not perceptual.
- No new external market survey. The 2026-10-24 audit already contains one; this
  report compares capabilities, not prices.
- No profiling, so performance claims are deliberately absent.

---

## 2. Repository shape and architecture

### 2.1 Size

| Area | Files | Lines |
|---|---:|---:|
| Production Python (excludes tests) | 558 | 115,038 |
| Tests | 404 | 159,904 |
| `audio_suite_shared` | 76 | 29,437 |
| `master_driver` | 48 | 7,567 |
| `audio_fingerprinter` | 21 | 6,703 |
| `cd_ripper` | 25 | 6,188 |
| `utilities` (tooling) | 16 | 5,738 |
| `audio_refinery` | 18 | 5,110 |
| `library_stats` | 13 | 4,846 |
| `tag_field_updater` | 17 | 3,664 |
| `music_format_converter` | 14 | 2,960 |

The suite declares **27 tools** in `audio_suite_shared/tool_plugin.py`
(`ToolManifest`). `audio_suite_shared` is 26% of production code and carries
eight distinct concerns: tag I/O, DSP models, GUI builders, CLI plumbing,
platform/security, undo, plugins and documentation helpers.

### 2.2 Layers

- `app.py` + `ui/` — Tk composition and widgets.
- `core/` — processing, usually pure and GUI-free; several modules state this
  explicitly (`gain_calculator.py`, `trimmer.py`, `formats.py`, `dsp_chain.py`).
- `utils/` — CLI argument parsing, settings and config adapters.
- `cli.py` — Click command surface; `audio_suite_shared/cli_base.py` supplies the
  shared entry contract.
- `audio_suite_shared/` — cross-tool infrastructure.
- `master_driver/` — process orchestration, cards, state and batch dependencies.

This is a sound shape. The two weak seams are `app.py` (composition plus a lot
of layout) and `audio_suite_shared` (too many concerns in one flat package).

### 2.3 Shared-module adoption

Measured by AST import, not by documentation:

- 27 shared modules are imported by three or more tools.
- 22 tools use `cli_base` / `cli_dataclasses` / `cli_helpers`.
- 23 use the shared exception hierarchy; 19 use `app_bootstrap`; 18 use
  `batch_undo`; 16 use `ui_common`; 15 use `ui_helpers`; 15 use
  `file_processor_base`; 13 use `tag_helper`.
- Per-tool shared imports range from 11 (`album_genre_tagger`,
  `master_driver`, `ml_denoiser`, `stem_separator`) to 21
  (`audio_fingerprinter`, `audio_refinery`).

This is genuine reuse, not a facade. It also makes the remaining duplication
easier to fix: the target abstraction usually already exists.

---

## 3. Gate and test health at HEAD

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check .` | **Pass** — "All checks passed!" |
| Format | `ruff format --check .` | **Pass** — 962 files already formatted |
| Types | `python -m mypy .` | **Pass** — no issues in 556 source files (strict) |
| Security | `bandit -r . -x ./.venv -c pyproject.toml` | **0 High, 0 Medium, 46 Low** |
| Tests | `pytest` | **Pass** — 11,197 passed, 3 skipped, 35 deselected in 20m56s (exit 0) |
| Coverage floor | `[tool.coverage.report] fail_under` | 75 |

The 46 Low Bandit findings are the documented first-party subprocess call sites
(B603/B606/B607) and equivalent policy-accepted items; Bandit's own run reports
no Medium or High. The static gate is in good shape.

The suite is large and behaviour-oriented: 11,235 tests and 159,904 lines of
test code, with contract locks for callback payloads, launcher pre-flight,
GUI naming, docs/tool coverage, changelog split, CLI schema and test-file
naming. That is the main reason the codebase can be changed safely.

---

## 4. Code: what is GOOD

**G1 — The gate is genuinely green and strict.** Ruff, Ruff-format, mypy
`--strict` over 556 files and Bandit 0/0 are not aspirational; they pass at
HEAD. Type annotations are pervasive, not decorative.

**G2 — The shared layer is real.** 27 shared modules have three or more
consumers. `file_processor_base`, `batch_undo`, `cli_base`, `tag_helper`,
`analysis_loader`, `secure_subprocess`, `run_outcome` and `ui_common` are load-
bearing, not wrappers around nothing.

**G3 — Pure core / impure edges.** DSP and rule modules are deliberately free of
Tk and often of file I/O (`dsp_chain.py`, `gain_calculator.py`, `trimmer.py`,
`formats.py`, `loudness.py`, `declipper.py`). This is the right shape for
testing audio outcomes.

**G4 — Strong typing conventions.** Frozen dataclasses for parameters
(`EnhancementParams`, `NoiseReductionParams`, `NormaliseParams`), `Enum` for
status, `TYPE_CHECKING` guards, explicit `Any` boundaries. 31 `# type: ignore`
in 115k lines is a low count.

**G5 — Test design that measures outcomes.** The repo repeatedly asserts decoded
audio (per-channel RMS, LUFS, bit depth, sample rate), not just returned fields;
`tests/test_audio_writer_format.py` and the F-10 lossless-depth locks are the
model. The callback, launcher, naming and docs locks prevent whole classes of
regression.

**G6 — Audio-correctness rules are explicit.** The FLAC `.tags` rebinding trap,
AcoustID near-tie resolution, onset-periodicity evidence for BPM, the fold-only
tempo band, degenerate-audio refusal and the album-gain combined-signal rule are
all documented and tested. This is rare discipline.

**G7 — Security posture.** `secure_subprocess` allowlisting, path-containment
checks in the reorganiser and CD ripper, encrypted key files and a repository
test against new direct `subprocess` calls.

**G8 — Undo is first-class.** `batch_undo` records tag, audio-overwrite,
reorganisation and delete snapshots in one SQLite log, and tools open batches
through `active_batch`.

**G9 — Observability.** Logs are split by audience (suite lifecycle vs per-tool
detail), `run_outcome` carries caveats back to the driver, and error messages
are centralised in `exceptions.USER_MESSAGES`.

**G10 — Documentation is engineered.** Sphinx site, 32 rendered guides, generated
indexes, drift checks and a single source for user-facing messages.

---

## 5. Code: what can be IMPROVED (should, not must)

### C-I1 — `audio_suite_shared` is a god package

76 modules and 29,437 lines mix tagging, DSP models, GUI builders, CLI, undo,
plugins, platform and security in one flat namespace. **Proposal:** split into
`audio/`, `tagging/`, `ui/`, `cli/`, `platform/`, `security/`, `plugins/` with
re-export shims so imports keep working. **Effort:** 2-3 weeks, mechanical.
**Verification:** import-graph test that every old path still resolves; gate.

### C-I2 — Version-history prose lives in code

671 `Changed in <version>` lines across 330 files, including `pyproject.toml`
(20+ consecutive release comments) and module docstrings. It is release data,
not code documentation, and it makes modules harder to read. **Proposal:** keep
one-line "why this shape" notes only; move history to
`CHANGELOG.md`/`TECHNICAL_CHANGELOG.md`. **Verification:** grep budget in CI
(e.g. no new `Changed in` above a baseline), docs unchanged.

### C-I3 — Naming is inconsistent

`AudioSuiteV6` (album_art_sync), `GenreConsolidatorApp` (album_genre_tagger),
`ASXExtractorTool`, `ArtNormalizerApp`, `AudioSuiteDriver`; two platform modules
(`platform_support.py` vs `platform_utils.py`) and two subprocess modules
(`subprocess_utils.py` vs `secure_subprocess.py`). **Proposal:** `<Tool>App`
for windows, `platform_*` split renamed by purpose (`platform_matrix.py`), and
fold `get_startupinfo` into `secure_subprocess`. **Effort:** 3-5 days.
**Verification:** AST test for the app-class pattern; imports updated.

### C-I4 — `os.path` and `pathlib` are mixed

383 `os.path` references alongside widespread `pathlib.Path`. Not a bug, but it
splits path-safety reasoning. **Proposal:** pathlib for new code and for the
path-containment helpers; migrate opportunistically. **Verification:** Ruff
`PTH` on new/changed files only (do not enable repo-wide in one pass).

### C-I5 — Test files are monolithic

`album_art_sync/tests/test_album_art_sync.py` is 3,766 lines;
`cd_ripper/tests/test_ripper_core.py` 3,435; `metadata_scrubber/tests/
test_scrubber.py` 2,424. **Proposal:** split by behaviour class, not by source
module, keeping the naming rule. **Effort:** 3-4 days. **Verification:** same
test count and names; suite green.

### C-I6 — No `py.typed`

The package is strictly typed internally but ships no marker, so downstream
type checkers ignore it. **Proposal:** add `py.typed` to `audio_suite_shared`
(and public packages after an API audit), then run mypy against a small consumer
fixture. **Effort:** 1-2 days.

### C-I7 — Legacy shims and ignored parameters

`audio_refinery/core/convert.py` is a re-export shim; root
`Tag_Field_Updater.py` duplicates the `.pyw` entry; `tempo_analyzer/utils/
config.py` and `mood_analysis_batch_tagger/utils/config.py` accept an ignored
`config_path`. **Proposal:** deprecate in one release, remove in the next; keep
the shims only where a documented CLI contract needs them.

### C-I8 — Console/display output policy is not uniform

`print()` survives in plugin examples and two module docstrings; `format_info()`
returns emoji (`📊`, `⚠`, `✓`) that are safe in Tk but would crash a cp1252
console if reused. **Proposal:** route all user output through the shared
console helpers; keep emoji out of any string a CLI can print.

### C-I9 — Coverage blind spots are unknown

The 75% floor is aggregate; no per-package report was produced. **Proposal:**
publish a per-package coverage table in CI (not a new gate) to find cold areas
(plugin loader, rare formats, GUI paths) before refactoring them.
**Verification:** coverage JSON artifact.

---

## 6. Code: what MUST be improved

Each item below is a structural risk, not a style preference. "Must" means it
should be resolved before the next feature wave expands the affected surface.

### C-M1 — Duplicate DSP parameter models with divergent defaults

**Evidence.** `audio_suite_shared/dsp_models.py` defines `PresetName(Enum)`,
`EnhancementParams` and `PRESETS`; `audio_enhancer/core/models.py` defines its
own `PresetName(str, Enum)`, `EnhancementParams` and `PRESETS`. The two class
defaults already disagree: `output_gain_db` is `0.0` in shared and `4.0` in the
enhancer model (verified by diff). The Refinery UI reads the shared table
(`audio_refinery/ui/setup_tab.py:46`), while the Refinery pipeline resolves
presets from the enhancer table (`audio_refinery/core/pipeline.py:876`). Only
the enhancer model is imported by production code; the shared one is used by
the UI and by `dsp_chain`'s documented contract.

**Why it must change.** One feature has two preset tables and two enums. A
change to either preset's compressor/EQ values silently makes the displayed
preset differ from the applied one. This is the same shape as the album-gain
and dry-run divergences the project has already fixed.

**Proposal.** Make `audio_suite_shared.dsp_models` the only definition; have
`audio_enhancer.core.models` re-export it (no second class); delete the local
`JobStatus`/`AudioFileInfo`/`ProcessingResult` if they remain unused. Add a test
asserting the UI table and pipeline table are the same object and that every
preset renders and applies identical values.

**Verification.** A real-file enhancement run with a non-Custom preset: decoded
output RMS/gain matches the preset's declared output gain; a unit test compares
every `PRESETS` entry field-by-field against the shared definition.

**Effort/risk.** 2-3 days. Low risk; the only compatibility concern is the
`str`-enum `PresetName` (f-string rendering), so route display through `.value`.

### C-M2 — `tag_field_updater` is a second tag layer

**Evidence.** `tag_field_updater/core/processor.py:42-50` imports `AIFF`, `ASF`,
`FLAC`, `ID3` frames, `MP3`, `MP4`, `OggOpus`, `OggVorbis` and `WAVE` directly
and reimplements field mapping. The shared `tag_helper` package has handlers for
the same containers and is used by 13 tools. `metadata_scrubber` also uses
direct mutagen, but deliberately (it must preserve arbitrary frames).

**Why it must change.** Tag semantics, format coverage and undo snapshots now
have two implementations. The 2.1.3 scrubber defect (offering formats the loader
could not open) is exactly what a duplicated format/tag path produces.

**Proposal.** Introduce a format-agnostic field mapping engine over
`TagHandlerFactory`; make `tag_field_updater` a consumer. Keep the scrubber's
raw-frame path as a documented, tested exception (it needs frames the facade
does not model). Add a cross-tool test: the same edit through Tag Editor and Tag
Field Updater produces byte-identical tags on MP3/FLAC/M4A/WAV.

**Verification.** Round-trip real files of each container; compare decoded tag
values and undo records; assert unsupported formats are refused consistently.

**Effort/risk.** 2-4 weeks. Medium: field mapping rules (slash-genre, TXXX
names) are tool-specific and must be preserved exactly.

### C-M3 — Two format taxonomies

**Evidence.** `audio_suite_shared/audio_formats.py` defines 14 extensions,
`PYDUB_FORMAT` export params and read-only/lossless sets.
`music_format_converter/core/formats.py` defines 17 format *names* (including
`aac`, `alac`, `wma`), its own lossy/lossless split and conversion rules; it
scans with its own `detect_format`, so `.wma` is processed by the converter
while remaining invisible to every tool that uses `SUPPORTED_EXTENSIONS`.
`formats.py` also duplicates lossless/lossy classification and output-extension
mapping.

**Why it must change.** There is no single answer to "what formats does the
suite support, read, or write". Prior defects came from exactly this split
(scrubber discovery, ALAC `.alac` output, 24-bit WAV truncation). Every new
format currently needs edits in two places.

**Proposal.** One capability matrix keyed by extension: read, write, lossless,
pydub format, FFmpeg codec/muxer, bit-depth rules, container extension. Derive
`SUPPORTED_EXTENSIONS`, `PYDUB_FORMAT`, `ALL_FORMATS` and the converter's rules
from it. Add a test that every extension in the matrix is discoverable, and
every output format round-trips through FFmpeg.

**Verification.** Property test: for every matrix entry marked writable, encode
a 1-second tone, decode it, assert container/codec and no silent fallback;
for read-only entries, assert a clear refusal.

**Effort/risk.** 3-5 days. Medium: `.wma` support must either be completed
(tag helper + discovery) or explicitly removed from the converter list.

### C-M4 — GUI scaffolding is still duplicated

**Evidence.** 23 `app.py` files total 11,104 lines; `ui/setup_tab.py` files total
6,964 lines. 18 of 23 apps build their own `_build_ui`, notebook and help bar;
only six tools use a shared base (`AnalysisAppBase` for key/mood,
`AnalysisTagToolApp` for bpm/lyrics, `NoisePopToolApp` for ml_denoiser). The
shared `ui_common` has `build_results_tab`, `build_processing_tab`,
`BaseSetupFrame` and `AnalysisSetupFrame`, so the primitives exist; adoption is
partial. The 2.3.1 theme fixes had to touch many files for one visual rule.

**Why it must change.** Every cross-cutting change (theme, driver controls,
completion seam, audit log, accessibility) is O(tools), and drift is invisible
until a user sees a black-on-dark checkbox. This is the largest maintainability
cost in the tree.

**Proposal.** Extend one shell (`tool_app_base` or a new `suite_app`) to own the
notebook, header/help, run-controls strip, progress/status, results tab, error
dialog and log path; tools supply title, guide, tab builders and a processor
call. Migrate in waves, starting with the three largest composers
(`library_stats` 949, `file_reorganizer` 713, `music_format_converter` 668).

**Verification.** A UI-structure contract test (tabs, run controls, results
widgets present) per tool; a golden Tk smoke test under the hidden root; the
existing callback/slot locks.

**Effort/risk.** 1-2 weeks for the shell plus 3 tools; 6-8 weeks for all.
Medium risk of visual regressions; migrate behind tests, one tool per commit.

### C-M5 — Broad exception handling is unlinted

**Evidence.** 186 `except Exception` sites in production code; Ruff's `select`
does not include `BLE`. Many are legitimate boundaries (FFmpeg probe, optional
dependency), but several wrap audio writes and tag operations.

**Why it must change.** A swallowed write failure becomes a "skipped" file,
which is the failure mode the project's own rules call out. Without a lint rule,
new broad handlers are invisible in review.

**Proposal.** Enable `BLE001` with a checked baseline: triage every site into
(a) boundary handler with logging and a typed outcome, (b) narrow exception,
(c) remove. No blanket `# noqa`; each exemption names its reason. Add a test
that an injected write failure surfaces as an error, not a skip, in the shared
in-place workflow.

**Verification.** Fault-injection test on `BaseFileProcessor` and tag writes.

**Effort/risk.** 1-2 weeks. Low technical risk; the triage is judgement-heavy.

### C-M6 — Oversized modules and functions

**Evidence.** Eight modules exceed 1,000 lines (`ui_common` 1,360,
`utilities/release.py` 1,315, `audio_fingerprinter/core/file_processor.py`
1,226, `batch_undo` 1,198, `musicbrainz_client` 1,160,
`file_processor_base` 1,132, `library_cache` 1,038,
`audio_refinery/core/pipeline.py` 1,012). 122 of 3,153 functions are 100+ lines;
the worst branch counts are `_collect_tags_to_preserve` (135 lines, 75
branches), `_apply_preset` (96/40), `library_stats/cli.py::stats` (187/40),
`asx_stub.parse_stub_bytes` (111/39).

**Why it must change.** These are the files where an audio bug is hardest to
see and where a fix is most likely to introduce another. The clone scan also
shows the UI/app layer matching itself repeatedly, so the size and duplication
compound.

**Proposal.** Split by responsibility, not by line count: `ui_common` into
tab builders/presets/dialogs; `file_processor_base` into discovery, pool,
in-place workflow and reporting; `batch_undo` into schema/record/revert;
`_collect_tags_to_preserve` into per-container collectors. Add a reviewed
complexity ceiling (e.g. Ruff `PLR0912`/`PLR0915` with a baseline) so new
monsters fail review.

**Verification.** Behaviour-lock tests before the split; identical decoded
outputs and reports after; no test-count drop.

**Effort/risk.** 3-4 weeks. Medium: pure refactor, but the in-place path is
audio-critical.

### C-M7 — Tag-helper import cycle

**Evidence.** `tag_helper_base.py:478-483` imports six handlers at the bottom
with `# noqa: E402`; each handler imports `tag_helper_base`. It works because of
import order, which is exactly what breaks in a frozen build or a different
entry point.

**Why it must change.** A cycle resolved by ordering is a latent import failure,
and the base module cannot be imported in isolation for tests.

**Proposal.** Move the ABC and `TagHandlerFactory` into a leaf module with no
handler imports; register handlers explicitly (or lazily inside the factory).
Delete the bottom imports and the `noqa`.

**Verification.** `python -c "import audio_suite_shared.tag_helper_base"` in a
fresh interpreter; factory resolves every supported extension; frozen/zipimport
smoke test if packaging is in scope.

**Effort/risk.** 1-2 days. Low.

### C-M8 — CLI handshake parsing is duplicated and can drift

**Evidence.** 25 `utils/cli_args.py` modules; `_scan_value_options` is
reimplemented in `cd_ripper`, `file_reorganizer`, `library_stats` and
`spectral_viewer`; `looks_like_driver_argv` in `duplicate_finder`,
`restoration`, `tag_editor` and `tag_field_updater`; `_flag_value` in
`album_art_sync`. The Master Driver passes a fixed grammar (`path`, `--live/
--dry`, `--start/--no-start`, `--end/--no-end`).

**Why it must change.** A tool that handles one flag differently silently
ignores the driver's mode or auto-start, and the user sees a window that does
not do what the batch asked. This is a contract, so it should have one
implementation.

**Proposal.** Put the grammar in `BaseCLIArgs`/`cli_helpers`: one scanner, one
validation hook, one per-tool option table. Keep Click definitions separate
(user-facing) but derive the driver handshake from the table. Add a contract
test that runs every manifest tool's `parse()` against a canonical argv and
asserts path/mode/start/end.

**Verification.** Parametrised test over all 27 manifest ids; a launched-process
smoke test for two tools.

**Effort/risk.** 3-5 days. Low-medium.

### C-M9 — Dead code kept alive by tests

**Evidence.**
`noise_reduction/ui/setup_tab.py` (173 lines) has no production or test
importer; the Refinery builds its own noise panel. `audio_enhancer/core/
models.py` still defines `JobStatus`, `AudioFileInfo` and `ProcessingResult`,
none of which production code uses after the standalone window was retired.
`_ThreadSafeSlotVar` is redefined locally in `audio_refinery/app.py:58` and
`mood_analysis_batch_tagger/app.py:42` although
`audio_suite_shared/thread_safe_slot_var.py` exists and is used by eight tools.
The root `Tag_Field_Updater.py` is a legacy entry beside the `.pyw`.

**Why it must change.** The repo's own rule says unused scaffold must not
remain; dead modules mislead readers and keep tests green over code nobody runs.

**Proposal.** Delete the unused noise UI and the unused enhancer result models;
switch both apps to the shared slot-var wrapper; decide whether the root shim is
a supported CLI entry, and document or remove it. Add an AST/grep check for
orphan `ui/setup_tab.py` modules.

**Verification.** Import scan plus full gate; no test-count change beyond the
deleted module's own tests.

**Effort/risk.** 1 day. Very low.

### C-M10 — Audio decode and measurement are fragmented

**Evidence.** FFmpeg is referenced from 35 production files. Duration/peak/
loudness probing exists separately in
`replaygain_analyzer/core/ffmpeg_metrics.py`, `audio_refinery/core/measure.py`,
`audio_normalizer/core/loudness.py`, `audio_enhancer/core/ffmpeg_io.py`,
`music_format_converter/core/ffmpeg_params.py` and
`audio_suite_shared/lossless_gain.py`; analysis tools decode through
`analysis_loader`, while repair/convert paths decode through pydub/FFmpeg. The
shared `audio_conversion` module covers packing, not probing.

**Why it must change.** Two tools can disagree about a file's loudness, peak or
duration, and the suite's promises are measurement-based (ReplayGain, loudness
normalisation, duplicate keep-decisions, declip thresholds). A single probe
module is the only way to keep those verdicts consistent.

**Proposal.** Add `audio_suite_shared/audio_probe.py` with: stream metadata,
decoded duration, sample peak, true peak, integrated loudness/LRA (EBU R128),
and a documented resampling/decode policy. Migrate call sites one at a time,
starting with ReplayGain and Normalizer, and assert equality against the current
values on a fixture corpus before switching.

**Verification.** Golden-corpus test: every migrated call site produces the same
numbers as HEAD within a stated tolerance (e.g. 0.1 dB / 1 ms); cross-tool test
that ReplayGain, Normalizer and Library QC agree on the same file.

**Effort/risk.** 2-3 weeks. Medium-high: measurement changes are audio-critical,
so migrate behind comparisons, never by rewriting all call sites at once.

---

## 7. Duplication and shared-module register

| Pattern | Where | Shared target | Action |
|---|---|---|---|
| Enhancement models/presets | `audio_suite_shared/dsp_models.py`, `audio_enhancer/core/models.py` | `dsp_models` | C-M1 |
| Format classification | `audio_formats.py`, `music_format_converter/core/formats.py` | capability matrix | C-M3 |
| Tag read/write | `tag_helper_*`, `tag_field_updater/core/processor.py`, `metadata_scrubber` | `tag_helper` | C-M2 |
| GUI shell | 18 `app.py` files | `tool_app_base`/`ui_common` | C-M4 |
| CLI handshake | `_scan_value_options` x4, `looks_like_driver_argv` x4, `_flag_value` | `cli_helpers` | C-M8 |
| Slot-var wrapper | 2 local `_ThreadSafeSlotVar` classes | `thread_safe_slot_var` | C-M9 |
| FFmpeg probe/measure | 6+ modules | `audio_probe` | C-M10 |
| Results tab | 20 thin `results_tab.py` wrappers | `ui_common.build_results_tab` | Already good; keep |
| Config adapters | `tempo_analyzer/utils/config.py`, `mood_analysis_batch_tagger/utils/config.py` | `suite_config` | Remove ignored parameters |
| Conversion helpers | `audio_refinery/core/convert.py` shim | `audio_suite_shared.audio_conversion` | Remove shim |
| Platform helpers | `platform_support.py` / `platform_utils.py` | renamed split | C-I3 |
| Subprocess helpers | `subprocess_utils.py` / `secure_subprocess.py` | `secure_subprocess` | C-I3 |

The clone detector found 12,000+ shared 60-token windows across 549 files; the
table above lists the ones that are structural rather than incidental (shared
widget construction, test fixtures and repeated Click option blocks are
expected). The results-tab family is the positive counter-example: 20 files, but
each is a 20-40 line wrapper over one shared builder.

---

## 8. Python gold-standards scorecard

| Area | Grade | Basis |
|---|---|---|
| Typing | A- | Strict mypy, frozen models, few ignores; no `py.typed` |
| Structure | B+ | Clear core/ui/utils split; god package and giant modules |
| Duplication | C+ | 27 shared modules in use, but 10 structural duplicates remain |
| Error handling | C | Typed hierarchy and user messages, but 186 broad catches |
| Testing | A- | 11.2k tests, outcome-based audio tests, contract locks; monolithic files |
| Security | A- | Allowlist, containment, key encryption, boundary test |
| Documentation | A- | Sphinx, guides, drift locks; history prose in code |
| Performance | B (unknown) | No profiling evidence; caches and worker caps are sensible |
| Packaging | C+ | PEP 621 and extras are solid; no `py.typed`, legacy shims |
| Naming | B- | Mostly consistent; a few historical class/module names |

---

## 9. Functionality inventory (27 manifest tools)

| Tool | What it does today |
|---|---|
| Metadata Scrubber | Removes tags/artwork across 9 containers, preserve list, undo |
| Audio Fingerprinter | Chromaprint/AcoustID, MusicBrainz, ISRC submission, album mode |
| ReplayGain Analyzer | Track/album gain and peak, tag write, combined-signal album rule |
| Album Genre Tagger | MusicBrainz release-group genres |
| Genre Sync | Copies genre across an album's files |
| BPM Analyzer | Beat tracking with onset-periodicity evidence and octave-fold guard |
| Tempo Analyzer | Tempo markings from measured BPM |
| Key Detector | Krumhansl-Schmuckler key estimation |
| Mood Analyzer | Heuristic mood + confidence, silent-audio refusal |
| Mood Analysis Batch Tagger | Batch mood analysis with process pool |
| Album Art Sync | Fetches and embeds art from online sources, purge/min-size rules |
| Album Art Normalizer | Resizes/converts embedded art |
| Music Format Converter | 17 format names, resample, bit depth, dither, presets |
| ASX Playlist Extractor | Reads ASX playlists, restores suite ASX stubs |
| CD Ripper | Disc ID, MusicBrainz metadata, AccurateRip, CUE split, ISRC |
| Library Statistics | Tag scan, cache, charts, CSV/JSON/M3U/HTML, Camelot |
| Spectral Viewer | Read-only spectrogram, PNG export |
| File Reorganizer | foobar-style pattern move/rename with containment checks |
| Tag Field Updater | Bulk TXXX edits and filename-pattern tagging |
| Tag Editor | Grid editing, CSV import/export, bulk case operations |
| Undo Tag Edits | Reverts recorded batches |
| Lyrics Manager | LRCLIB and sidecar LRC, synced/plain lyrics |
| Stem Separator | Demucs stems (vocals/drums/bass/other) |
| ML Denoiser | RNNoise denoise |
| Duplicate Finder | Fingerprint clustering, quarantine/delete/ASX stub |
| Restoration | Declip with measured distortion improvement |
| Audio Refinery | Declick, trim, noise/hum, enhance, loudness normalise (5 stages) |
| Stage-only packages | Audio Normalizer, Audio Enhancer, Silence Trimmer, Pop & Click, Noise Reduction (no windows since 2.3.1) |

---

## 10. Functionality gaps (audio manipulation only)

Sizes are rough developer effort for one experienced maintainer, including tests
and a guide update. Every item must verify the decoded audio outcome, not the
flag that was set.

### 10.1 EASY (days to ~2 weeks, low risk)

**F-E1 — Album-mode loudness normalisation.** Today normalisation is per file;
ReplayGain computes an album gain but only writes it as a tag. **Shape:** measure
the folder once as a concatenated stream (the existing album rule), derive one
gain, apply it to every track with the configured true-peak ceiling, report the
applied gain per file. **Acceptance:** decoded per-track gain matches the album
gain within 0.1 dB; measured album loudness within 0.5 LU; TP ceiling held;
dry-run reports before writing. **Reuses:** `replaygain_analyzer` measurement,
`audio_normalizer`, `audio_refinery` normalise stage.

**F-E2 — Peak/true-peak normalisation mode.** Only LUFS targeting exists.
**Shape:** a second target mode (`--target-peak -1.0 dBTP`) that scans and applies
gain with a limiter, preserving relative dynamics where possible. **Acceptance:**
decoded sample peak and true peak both at/below target within 0.2 dB; no
clipping; tags preserved.

**F-E3 — Exact time-range extract/trim.** Current trimming is silence-driven.
**Shape:** start/end (or duration) fields/CLI flags; stream-copy when the
container allows, re-encode otherwise; report the actual cut points.
**Acceptance:** duration within one frame; copy mode leaves audio packets
untouched; tags and art survive.

**F-E4 — Silence-based track splitter.** `cue_split` exists but is wired only to
the CD ripper. **Shape:** detect gaps with the existing silence detector, split
at boundaries, optionally emit a CUE, name by pattern. **Acceptance:** track
count and boundaries match the detected runs; no sample loss; CUE round-trips
through `cue_parser`.

**F-E5 — Join/concat with optional crossfade.** No join path exists.
**Shape:** FFmpeg concat demuxer for same-format inputs, optional equal-power
crossfade and gap; tags from the first file or a merged template.
**Acceptance:** output duration equals the sum minus overlaps; no DC step at
joins; sample rate/channel layout consistent; tags verified after decode.

**F-E6 — Channel utilities.** No channel operations exist outside analysis.
**Shape:** mono downmix (mean or -3 dB), stereo/dual-mono conversion, phase
invert, mid/side encode/decode, stereo width. **Acceptance:** synthetic
per-channel fixtures verify gain and phase; M/S round-trip is sample-accurate;
dry-run reports the chosen rule.

**F-E7 — Tag copy/template.** Tag Editor edits in place and imports CSV, but
there is no "copy these fields from this reference file" workflow.
**Shape:** saved field templates plus copy-from-file, dry-run diff, undo batch.
**Acceptance:** written tags read back equal on MP3/FLAC/M4A/WAV; untouched
fields are byte-identical; undo restores the original snapshot.

**F-E8 — CUE export from a folder.** `cue_generator` is used only by the CD
ripper. **Shape:** build a CUE from tags + measured durations for a folder or a
split operation. **Acceptance:** generated text parses back with identical
track offsets; missing durations are refused rather than guessed.

**F-E9 — Exact-duplicate mode in Duplicate Finder.** Current grouping is
fingerprint similarity; bit-identical or renamed copies are a different question.
**Shape:** decoded-PCM SHA-256 per file, cached like the fingerprint, grouped
separately from perceptual duplicates. **Acceptance:** renamed/re-encoded-copy
fixtures behave as specified; identical files group; different masters do not.

**F-E10 — Artwork extraction and missing-art report.** Only embedding is
exposed (`tag_helper_art.embed_artwork`). **Shape:** extract embedded JPEG/PNG
to `cover.jpg`/`folder.png`, report files with no art or oversized art.
**Acceptance:** extracted bytes hash-equal the embedded stream; formats without
art report cleanly.

### 10.2 SOME EFFORT (2-6 weeks each)

**F-S1 — Parametric EQ stage.** The enhancer chain has three fixed bands
(low shelf, presence peak, high shelf) and no user-facing EQ. **Shape:** 4-8
bands with frequency/gain/Q, bypass, presets, and a response curve; as a Refinery
stage and a standalone surface. **Acceptance:** measured response against a sine
sweep/pink noise within 0.5 dB; unity bypass is bit-transparent; A/B audition.

**F-S2 — Controllable dynamics stage.** Compression exists only inside the fixed
enhance chain; there is no standalone compressor/limiter with meters.
**Shape:** threshold/ratio/attack/release/makeup, lookahead limiter, gain-
reduction meter, dry-run projection. **Acceptance:** measured gain reduction and
output LUFS/TP match the settings; no overshoot above ceiling.

**F-S3 — De-esser.** No sibilance control exists. **Shape:** split-band detector
with frequency/amount, preserving formants; report the band reduction.
**Acceptance:** measured 5-9 kHz energy reduction with minimal change below
4 kHz; a reference vocal does not lisp.

**F-S4 — Pitch/time manipulation.** No time-stretch or pitch-shift code exists.
**Shape:** tempo change without pitch, pitch shift without tempo (librosa or
pedalboard), optional formant preservation, batch mode. **Acceptance:** duration
ratio and tuning measured on a reference tone; artefact tests on speech/vocal
fixtures; original and processed durations reported.

**F-S5 — Album gain staging with per-track report.** Extends F-E1: per-track
gain plus album target, with a table of measured track loudness/peak and the
applied gain. **Acceptance:** album loudness target met; track-to-track
deviation stays inside a user-set window; report matches decoded measurements.

**F-S6 — Multichannel conversion/analysis (phase 1).** The pipeline is
stereo-centric; `measure.py` branches on `channels == 2` and there is no channel
map. **Shape:** decode/encode 5.1/7.1 without downmix, channel-map validation,
per-channel peak/RMS in reports; DSP stages refuse or explicitly downmix.
**Acceptance:** channel order and count survive a convert round-trip; per-channel
measurements match the source; unsupported stages refuse with a reason.

**F-S7 — Audio QC / forensics report.** Library Stats reports tags, not signal
quality. **Shape:** per-file integrated LUFS, true peak, LRA, crest/DR, DC
offset, phase correlation, clipped-sample and dropout counts; CSV/HTML export.
**Acceptance:** values agree with FFmpeg `ebur128`/`astats` on a fixture corpus
within stated tolerances; read-only run changes nothing.

**F-S8 — Peak/waveform cache.** The Spectral Viewer recomputes on open.
**Shape:** a peak-envelope cache keyed by `(mtime, size)` for fast overview
rendering in the viewer and Library Stats. **Acceptance:** rendered peaks match
decoded min/max within one pixel bucket; stale entries re-read once.

**F-S9 — Loudness-matched A/B audition.** `AuditionMixin` plays original/result
but does not equalise level, so louder usually "wins". **Shape:** gain-match the
two previews to the same momentary loudness, with a blind toggle.
**Acceptance:** measured difference at the output within 0.1 LU; blind mode
hides which is which.

### 10.3 MAJOR (multi-month, architectural)

**F-M1 — VST3/AU plugin hosting and offline chain.** Pedalboard can host VST3,
but there is no scanning, parameter UI, state serialisation or crash isolation.
**Shape:** plugin scan with vendor/format metadata, ordered chain, per-plugin
state saved in the preset, offline batch render, a safe-mode bypass on a plugin
crash. **Acceptance:** a known VST3 renders deterministically across runs; a
crashing plugin fails one file, not the batch; chain state round-trips.
**Why major:** UI for arbitrary parameters, persistence, licensing and
cross-platform plugin discovery are each substantial.

**F-M2 — Interactive spectral editor/repair.** The Spectral Viewer is read-only.
**Shape:** zoomable time/frequency canvas, rectangular/lasso selection,
attenuate/heal/replace from surrounding content, undo, and a measured repair
report. **Acceptance:** synthetic click/hum removal reduces the target band
without damaging neighbouring bins; before/after spectrogram and residual
metrics; undo restores the original file bytes.
**Why major:** interactive rendering performance, selection model, inverse STFT
correctness and undo all meet here.

**F-M3 — Full multichannel/immersive pipeline.** Phase 1 (F-S6) covers
pass-through; real authoring needs channel-aware DSP, downmix/upmix matrices and
BS.1770 loudness per layout. **Acceptance:** 5.1 -> stereo downmix obeys a
documented matrix and does not clip; per-layout loudness matches the reference
meter; channel order survives every stage.

**F-M4 — Restoration expansion: de-reverb, de-crackle, wow/flutter.**
Declip is the only restoration tool; the project previously deferred de-reverb
and spectral repair because no objective acceptance existed. **Shape:** start
with de-crackle (measurable impulse reduction) and wow/flutter (pitch-drift
measurement), then de-reverb with a decay-ratio target. **Acceptance:** each
sub-item has a reference metric that a blind gain change cannot pass (the rule
the earlier deferral established).

**F-M5 — Real-time monitoring chain.** Processing is batch/offline. A monitored
preview of the configured chain (with latency compensation) would let a user
hear EQ/dynamics/repair before committing. **Acceptance:** round-trip latency
reported; preview and rendered output match sample-for-sample at the same
settings; no writes during preview.

**F-M6 — Reference-matching / assisted mastering.** Measure a reference track
(loudness, spectral balance, dynamics) and propose safe corrections within
user-set limits. **Acceptance:** A/B against the reference with measured
loudness/spectral distance; never exceed the TP ceiling; every proposed move is
explainable and reversible.

### 10.4 Explicitly out of scope

Music playback, streaming, library browsing as a player, playlists for
listening, karaoke scoring, a full DAW timeline and video. The existing M3U/HTML
exports are library interchange, not player features, and should stay.

### 10.5 Priority

| Priority | Items | Rationale |
|---|---|---|
| 1 | F-E1, F-E3, F-E4, F-E5, F-E6 | High user value, reuse existing DSP, low risk |
| 2 | F-E2, F-E7, F-E8, F-E9, F-E10 | Completes batch workflows with little new DSP |
| 3 | F-S1, F-S2, F-S4 | The missing everyday manipulation controls |
| 4 | F-S5, F-S7, F-S9, F-S8 | Album/QC/audition quality-of-life |
| 5 | F-S3, F-S6 | Specialist DSP and channel phase 1 |
| 6 | F-M1, F-M2, F-M4 | Architectural/extensible depth |
| 7 | F-M3, F-M5, F-M6 | Long-horizon differentiation |

---

## 11. Plan-ready register

### 11.1 Code work packages

| ID | Package | Depends on | Verification |
|---|---|---|---|
| WP-0 | C-M1 unify DSP models | none | preset table identity + decoded gain test |
| WP-1 | C-M3 capability matrix | none | matrix round-trip over every format |
| WP-2 | C-M7 break tag-helper cycle | none | leaf import + factory test |
| WP-3 | C-M9 dead code/slot vars | none | import scan + gate |
| WP-4 | C-M8 shared CLI handshake | none | argv contract over 27 tools |
| WP-5 | C-M10 audio_probe (migrate ReplayGain first) | WP-1 | golden-corpus equality |
| WP-6 | C-M2 one tag layer | WP-2 | cross-tool tag equality on 4 containers |
| WP-7 | C-M5 exception triage | none | fault-injection tests |
| WP-8 | C-M4 GUI shell phase 1 (3 tools) | none | UI contract + smoke tests |
| WP-9 | C-M6 split top 5 modules | WP-0, WP-5 | behaviour locks, identical outputs |
| WP-10 | C-I1..C-I9 hygiene | WP-9 | gate + docs |

### 11.2 Suggested sequencing

Versions are SemVer for the single suite distribution (`pyproject.toml` currently
declares `2.4.0`). A **patch** carries work no user can observe — refactors,
tests, internal seams and defect fixes; a **minor** adds user-facing audio
capability without breaking an existing workflow; a **major** introduces a new
subsystem or an intentional behaviour change users must adapt to. Every cut runs
`python utilities/release.py <version>`, records user-visible bullets in
`CHANGELOG.md` and developer-only work in `TECHNICAL_CHANGELOG.md`.

1. **`2.4.1` — Week 0-2 (stop the drift):** WP-0, WP-1, WP-2, WP-3, WP-4. These
   are small, independent and remove the "two sources of truth" class before new
   features touch it. Add the exception baseline (WP-7) in the same window. Patch
   because the only user-visible effect is the `.wma` discovery fix from WP-1.
2. **`2.4.2` — Week 2-6 (audio foundation):** WP-5 then WP-6. Migrate
   measurement first and prove numerical equality before touching tag writes.
   Patch: intended to be behaviour-neutral; any measured difference is a defect
   fix, not a feature.
3. **`2.4.3` — Week 4-10 (structure):** WP-8 and WP-9 in parallel with feature
   Wave 1. Migrate one tool/module per commit, with behaviour locks. Patch:
   internal structure only.
4. **`2.5.0` — Feature Wave 1 (parallel, after WP-0/WP-1):** F-E1, F-E3, F-E4,
   F-E5, F-E6. Minor: each adds a user-facing manipulation control.
5. **`2.6.0` — Feature Wave 2:** F-E2, F-E7, F-E8, F-E9, F-E10. Minor: completes
   the batch workflows with no workflow removed.
6. **`2.7.0` — Feature Wave 3:** F-S1, F-S2, F-S4, then F-S5/F-S7/F-S9. Minor:
   the everyday manipulation set (EQ, dynamics, pitch/time, album/QC/audition).
7. **`3.0.0` — Feature Wave 4 (core):** F-M1, F-M2, F-M4. Major: plugin hosting,
   an interactive spectral editor and the restoration expansion are new
   subsystems, not extensions of the current pipeline.
8. **`3.1.0` — Feature Wave 4 (optional):** F-M3, F-M5, F-M6 only with a product
   decision. Minor on top of 3.0.0: further subsystems (immersive, real-time
   monitoring, reference matching) with no break to the 3.0.0 interfaces.

### 11.3 Verification standard (applies to every item)

- **Audio changes:** decode the output and measure per-channel RMS, integrated
  loudness, true peak, sample rate, channel count and bit depth. Never assert
  only the internal flag or the return object.
- **Tag changes:** write, reload from disk with mutagen, compare every field and
  the undo snapshot; verify dry-run writes nothing.
- **CLI/driver changes:** run the real argv through the tool's `parse()` and a
  launched-process smoke test.
- **UI changes:** widget-contract test plus one hidden-root smoke test per
  migrated tool; check all four theme states where the change is visual.
- **Refactors:** keep every existing behaviour test; a test-count drop is a
  failure unless the deleted test covered deleted code (then record why).
- **Docs:** update the affected guide Markdown, re-render with
  `python utilities/build_user_guides.py <module>`, and run `--check`.

### 11.4 Risks

| Risk | Mitigation |
|---|---|
| A refactor changes audio bytes | Migrate behind golden-corpus comparisons; measure decoded output, not state |
| Tag writes lose frames | Per-container round-trip tests; keep scrubber raw path separate |
| GUI migration causes visual regressions | One tool per commit, UI contract test, four theme states |
| Format matrix enables a broken output | Encode/decode every writable entry; refuse the rest explicitly |
| Scope creep into a DAW/player | Keep the out-of-scope list in the plan; every item must be batch-manipulation |
| Suite runtime grows | Keep new tests focused; reuse fixtures; do not duplicate the corpus |

---

## 12. Appendices

### A. Measured metrics

| Metric | Value |
|---|---:|
| Non-test Python modules | 558 |
| Non-test Python lines | 115,038 |
| Test files / lines | 404 / 159,904 |
| Tests collected | 11,235 (35 deselected) |
| Modules over 1,000 lines | 8 |
| Functions 100+ lines | 122 of 3,153 |
| `except Exception` sites | 186 |
| `# type: ignore` | 31 |
| `cast(...)` | 82 |
| `os.path` references | 383 |
| `Changed in` history lines | 671 across 330 files |
| `app.py` lines (23 files) | 11,104 |
| `ui/setup_tab.py` lines | 6,964 |
| Shared modules used by 3+ tools | 27 |

### B. Commands run

```text
ruff check .                                  -> All checks passed
ruff format --check .                         -> 962 files already formatted
python -m mypy .                              -> Success: no issues in 556 files
bandit -r . -x ./.venv -c pyproject.toml      -> 0 High, 0 Medium, 46 Low
pytest --collect-only -q                      -> 11,235 collected, 35 deselected
pytest                                        -> 11,197 passed, 3 skipped, 35 deselected (20m56s, exit 0)
```

The full suite passed at HEAD. The three skips are the documented platform/optional
cases, not suppressed failures.

### C. Main files inspected

`audio_suite_shared/{file_processor_base,tool_app_base,analysis_app_base,
audio_formats,tag_helper,tag_helper_base,dsp_models,thread_safe_slot_var,
ui_common,dsp_chain,run_outcome}.py`; `audio_refinery/{app,core/models,
core/pipeline,ui/setup_tab}.py`; `audio_enhancer/core/models.py`;
`tag_field_updater/core/processor.py`; `metadata_scrubber/core/scrubber.py`;
`music_format_converter/core/{formats,ffmpeg_params}.py`;
`file_reorganizer/{app,core/pattern}.py`; `library_stats/{app,core/
file_processor}.py`; `restoration/core/declipper.py`; `duplicate_finder/core/
file_processor.py`; the 27-entry manifest in `audio_suite_shared/tool_plugin.py`;
representative `utils/cli_args.py` and `ui/results_tab.py` files.

### D. Status of the previous audit's code findings

| Previous ID | Finding | Status at HEAD |
|---|---|---|
| C-01 | GUI scaffolding duplicated | **Open** (18/23 apps; see C-M4) |
| C-02 | `tag_field_updater` second tag layer | **Open** (see C-M2) |
| C-03 | Tag-helper import cycle | **Open** (see C-M7) |
| C-04 | Large classes/functions | **Open** (see C-M6) |
| C-05 | Broad exception handling | **Open** (see C-M5) |
| C-06 | Version-history prose in code | **Open** (see C-I2) |
| C-07 | Typing/style not uniform | **Improved** (strict mypy; Ruff set still narrow) |
| C-08 | Documentation gaps | **Improved** (single docs tree, drift locks) |
| C-09 | Non-ASCII console glyphs | **Improved** (console ASCII; `format_info` emoji remain GUI-only) |
| C-10 | Packaging metadata | **Partly** (PEP 621/extras; no `py.typed`) |

---

*End of report. No production code was modified; `git status` shows only this
new report file.*
