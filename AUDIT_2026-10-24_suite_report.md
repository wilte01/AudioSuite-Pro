# AudioSuite-Pro — Suite Audit Report

**Date:** 2026-10-24
**Commit audited:** `dfb5c48` (`Docs: stop shipping AGENTS.md in the documentation artifact`, 2026-10-24 21:02 +0100)
**Auditor:** Buffy (static review + targeted reproduction; see *Method and limits*)
**Baseline:** previous suite audit `AUDIT_2026-10-06_suite_report.md`
**Purpose:** a factual basis for the next remediation/feature plan. No source file was
modified during this audit; every claim below is either a measured result or a
code reference, and every reproduced defect carries its reproduction.

**Contents:** [§0 verdict](#0-verdict-at-a-glance) · [§1 method](#1-method-and-limits) ·
[§2 architecture](#2-repository-and-architecture) · [§3 gate and tests](#3-gate-and-test-health-at-head) ·
[§4 quality](#4-code-quality-readability-and-maintainability) · [§5 gold standards](#5-python-gold-standards-adherence) ·
[§6 findings R-01–R-16](#6-detailed-findings-and-reproductions) · [§7 non-findings](#7-verified-non-findings-do-not-fix-these) ·
[§8 market](#8-market-comparison) · [§9 register](#9-plan-ready-findings-register) ·
[§10 onboarding](#10-what-a-new-maintainer-will-struggle-with) · [§11–13 appendices](#11-appendix-a--measured-metrics)

---

## 0. Verdict at a glance

AudioSuite-Pro is an unusually well-engineered Python desktop audio suite for its size:
thirty first-party tools, a shared 28 kLOC core, a green five-stage gate, 10,915 passing
tests at 90.5 % statement coverage, strict mypy over 549 files, and a documented
decision record for nearly every non-obvious choice. Its architecture, error taxonomy,
undo model, logging split and test discipline are well above the norm for Tk-based
audio tooling.

It is **not** yet at the level of the specialist leaders in any single category, and
this audit found **three P0 issues** that the repository's own rules treat as
release-blocking — two audio-correctness defects and one security defect:

1. **ReplayGain album gain is mathematically wrong** for albums whose tracks differ in
   duration (the code averages per-track LUFS instead of computing album loudness).
2. **ALAC output cannot be produced at all** — the converter writes to a `.alac`
   filename, which FFmpeg has no muxer for, so every ALAC conversion fails.
3. **Tag-Based File Reorganizer is path-traversal vulnerable** — a crafted tag value
   containing `..` writes outside the chosen destination directory.

Two further high-severity functional defects should ship in the same sprint, because
each is a one-day fix whose blast radius is a whole tool:

4. **The Metadata Scrubber discovers formats it cannot open** (`.wv`, `.ape`, `.mpc`,
   `.spx`, `.dsf`) and reports valid files as unreadable (false errors, not
   mis-tagging, hence High rather than P0).
5. **The GUI and the CLI read two different Fanart.tv key files**, so a key entered in
   the GUI is invisible to the CLI and to the batch pipeline.

Beyond defects, the suite's market gaps are clear and mostly deliberate: no tag
action groups or tag-from-filename, no duplicate detection, no watch folders, no
playlist/DJ export, limited restoration depth (no de-reverb, declip, spectral repair
or dialogue isolation), and no verified POSIX runtime despite a documented "portable
core" claim. Those are feature-plan candidates, not defects.

### Top findings

| # | Severity | Finding | Class |
|---|---|---|---|
| R-01 | **Blocker** | ReplayGain album gain uses the mean of track LUFS (duration-unweighted) | Audio correctness |
| R-02 | **Blocker** | ALAC is offered as an output format but every conversion fails | Audio conversion |
| R-03 | **High** | File Reorganizer accepts `..` path components from untrusted tags | Security |
| R-04 | **High** | Album-art GUI and CLI read different config files | Functional/config |
| R-05 | **High** | Metadata Scrubber advertises formats its loader cannot open | Functional |
| R-06 | **Medium** | `audiosuite` exits 0 when a batch reports errors | Automation contract |
| R-07 | **Medium** | APEv2/WavPack tag writes are effectively untested (39.6 % coverage) | Test gap |
| R-08 | **Medium** | Two tool packages bypass the documented `secure_subprocess` boundary | Security policy |
| R-09 | **Medium** | Audio Enhancer dry run applies a different DSP chain than live | Correctness/UX |
| R-10 | **Medium** | A failed batch step still satisfies its dependants in parallel mode | Orchestration |
| R-11 | **Medium** | Dependency audit is non-blocking in CI (`continue-on-error: true`) | Supply chain |
| R-12 | **Medium** | "Portable core" is claimed but only Windows is tested | Verification |

---

## 1. Method and limits

### What was done

- Read the project's instruction set (`AGENTS.md`), the prior audit, README,
  CONTRIBUTING, SECURITY, CHANGELOG, `pyproject.toml`, CI definitions and plan index.
- Measured the tree: file/LOC counts, function/class sizes, cyclomatic-complexity
  proxy, `Any`/`Optional`/`os.path`/broad-except counts, non-ASCII inventory.
- Ran the full gate at HEAD: compile, Ruff check, Ruff format check, bare mypy,
  Bandit with the project config, bare pytest with coverage.
- Read the core shared modules (`file_processor_base`, `tag_helper*`, `batch_undo`,
  `suite_config`, `logging_setup`, `secure_subprocess`, `analysis_loader`,
  `tool_app_base`, `exceptions`, `cli_base`, `plugin_system`) and the high-risk
  per-tool paths (conversion, ReplayGain, scrubber, organizer, enhancer, CD ripper,
  album art, lyrics, fingerprinter, library cache, Refinery, Master Driver).
- Reproduced candidate defects through the real entry points on disposable files:
  ALAC conversion, scrubber format discovery, FLAC artwork/lyrics preservation,
  ReplayGain arithmetic demonstration, organizer path resolution, config-file
  resolution, APEv2 tag round-trip, CLI exit status, and direct handler imports.
- Delegated three source-backed market surveys (tagging, restoration, conversion/
  ripping/DJ) and cross-checked the suite's own capabilities in code.

### What was not done

- No physical CD drive was available: the `hardware` tests (part of the 35
deselected) were not run, so the ripping hardware path was reviewed statically only.
- The `real_ml` tests (Demucs/RNNoise real models) were not run; the ML tools were
  reviewed through their code and mocked test doubles.
- No live-network calls were made; provider integrations were reviewed statically
  and through their tests. Market claims come from vendor documentation (sources in
  §8.1), not from hands-on trials.
- No macOS/Linux host was used, so the "portable core" claim is reviewed, not
  executed. This is itself a finding (R-12).
- This is a risk-weighted review, not a line-by-line reading of all 108 kLOC. The
  shared core, every high-risk audio path, the registration seams and the test locks
  were read; peripheral UI layout code was sampled.
- No performance benchmark was run beyond the test suite; the report treats
  performance work as unverified unless a measurement is cited.

### Environment

| Component | Version |
|---|---|
| OS | Windows 11 (10.0.26200) |
| Python | CPython 3.14.9 |
| FFmpeg / ffprobe | 8.0.1-full_build (gyan.dev) |
| mutagen | 1.48.1 |
| librosa | 1.0.0 |
| numpy / scipy | 2.5.4 / 1.18.1 |
| pedalboard | 0.9.26 |
| pydub | 0.25.1 (no `__version__`) |

---

## 2. Repository and architecture

### 2.1 Size and shape

| Area | Production files | Production LOC | Test files | Test LOC |
|---|---:|---:|---:|---:|
| `audio_suite_shared` | 75 | 28,116 | — | 30,832 |
| `master_driver` | 51 | 7,713 | — | 9,038 |
| Root `tests/` (cross-cutting) | 0 | 0 | — | 15,052 |
| 29 tool packages + Undo Tag Edits in shared | ~400 | 63,676 | — | ~95,000 |
| `utilities` | 14 | 4,608 | — | 2,674 |
| Guide generators | 2 | 2,778 | — | — |
| **Total** | **550** | **107,910** | **379*** | **150,009** |

\*Test-tree files; 312 of them contain test functions, the rest are `conftest.py`
(28) and helpers.

Production SLOC (excluding blanks and comments): **88,345**; comment lines: **3,783**
(4.1 % of non-blank lines, before docstrings). Test code is **1.39×** production code.
There are 3,049 production functions and methods (median 16 lines, mean 26.9) and
363 classes.

### 2.2 Layers

```
Top-level <Tool>.pyw (31 launchers)
  └─ audio_suite_shared.venv_bootstrap.ensure_venv_interpreter()
  └─ audio_suite_shared.preflight.guard_or_exit()
  └─ audio_suite_shared.app_bootstrap.configure_logging()
  └─ <tool>.app.main()

GUI:  app.py ──> ui/* tabs ──> core/file_processor.py ──> shared helpers
CLI:  audio_suite_shared.cli_app ──> <tool>.cli ──> the same core
Driver: master_driver ──> arg_builder + batch_orchestrator ──> .pyw or CLI
Shared: tag_helper / batch_undo / file_processor_base / analysis_loader /
        secure_subprocess / suite_config / logging_setup / plugin_system
```

The layering is mostly respected. GUI modules do not contain DSP; core modules do
not import Tk (with the expected exception of the shared `tool_app_base` scaffolding);
CLI commands are thin wrappers over the same processor entry points as the GUI. This
is the single biggest maintainability strength: a fix in a core module reaches GUI,
CLI and Master Driver together.

### 2.3 The thirty tools

| Group | Tools |
|---|---|
| **Enrich (11)** | Metadata Scrubber, Audio Fingerprinter, ReplayGain Analyzer, Album Genre Tagger, Genre Sync, BPM Analyzer, Tempo Analyzer, Key Detector, Mood Analyzer, Album Art Sync, Lyrics Manager |
| **Refinery (1)** | Audio Refinery (multi-stage DSP pipeline) |
| **Utility (18)** | Music Format Converter, ASX Playlist Extractor, Album Art Normalizer, CD Ripper, Mood Analysis Batch Tagger, Noise Reduction, Audio Enhancer, Audio Normalizer, Pop & Click Remover, Tag Field Updater, Silence Trimmer, Tag Editor, Stem Separator, Library Statistics Dashboard, Spectral Viewer, ML Denoiser, Tag-Based File Reorganizer, Undo Tag Edits |
| **Plugin** | `example_tool` (bundled, enabled by default) |

The manifest in `audio_suite_shared/tool_plugin.py` is the single source of truth for
the tool id, category, CLI name, launcher and default toggle. There are 29 tool
packages; Undo Tag Edits lives in `audio_suite_shared` rather than its own package.
`README.md` still says "27 first-party tools" (line 3) while the registry reports
**30** first-party tools and 31 driver manifests. This is documentation drift, not a
registration failure.

### 2.4 Shared infrastructure worth knowing

| Module | What it solves | Assessment |
|---|---|---|
| `file_processor_base.py` | discovery, thread-pool dispatch, progress, retries, in-place DSP with temp copy + copy-back + undo | Strong single implementation; four executor loops intentionally remain (documented `KEEP-IN-SYNC`) |
| `tag_helper_base.py` + per-format modules | one tag API over ID3, Vorbis, MP4, APEv2, DSF | Deep and correct, but the facade has an import cycle (§4.2 C-03) |
| `batch_undo.py` | SQLite undo log with tag snapshots, overwrite bytes, deletes, reorg records, batch pruning | Excellent differentiator; cap/prune semantics documented and tested |
| `suite_config.py` | shared key-value config, cross-process file lock, atomic replace | Strong; the prior lost-update bug is fixed (cache invalidated inside the lock) |
| `logging_setup.py` | admin log + per-program log, crash hooks, env override | Strong; fixes the old "tool loggers never reach the suite log" defect |
| `secure_subprocess.py` | executable allowlist, no `shell=True`, argument/path checks | Good design; not universally used (R-08) |
| `analysis_loader.py` | decode fallbacks and the composed analysable guard | Strong: duration **and** silence are refused together, preventing fabricated BPM/key/mood |
| `plugin_system/` | manifest discovery, validation, enablement, four hosts | Strongest plugin story of any comparable free suite; Python-only and unsandboxed by design |
| `tool_app_base.py` | shared GUI scaffolds for two tool families | Good pattern, but only 5 of 28 apps use it |

### 2.5 Format support is not one matrix

The canonical `audio_suite_shared/audio_formats.py` list has 14 extensions
(`.mp3 .flac .ogg .m4a .mp4 .opus .wav .aiff .aif .wv .ape .mpc .spx .dsf`) and marks
`.ape/.mpc/.dsf` as audio-write read-only. Per-tool reality differs:

| Tool | Discovery/accepts | Actual capability |
|---|---|---|
| Tag helper | 14 canonical | full read/write per handler |
| Metadata Scrubber | 14 canonical (the `.wma` exclusion is stale) | **8** — mp3/flac/ogg/opus/m4a/mp4/wav/aiff; the rest always error (R-05) |
| Tag Field Updater | 10, including **`.wma`**, excluding `.wv/.spx/.dsf/.ape/.mpc` | own mutagen layer, not the shared tag helper |
| Music Format Converter | 17, including `.wma` and `.aac` | 14 outputs (`.ape/.mpc/.dsf` excluded); **ALAC output broken** (R-02) |
| Tag Editor / art tools / analysis tools | 14 canonical | tag writes through the shared handlers |

This is a user-visible inconsistency: the same folder yields different file counts per
tool, and `.wma` is processed by Tag Field Updater and the Converter but skipped by
everything that uses the canonical list. A single declared support matrix, enforced by
a test, would remove a whole class of surprises.

---

## 3. Gate and test health at HEAD

### 3.1 The four-stage gate (plus tests)

| Check | Command | Result |
|---|---|---|
| Compile | `python -m compileall -q -f .` | **PASS** (exit 0; only `.venv` third-party `SyntaxWarning`s, documented) |
| Lint | `ruff check .` | **PASS** — "All checks passed!" |
| Format | `ruff format --check .` | **PASS** — 930 files already formatted |
| Types | `python -m mypy .` | **PASS** — no issues in 549 source files |
| Security | `bandit -r . -x ./.venv -c pyproject.toml` | **0 High / 0 Medium**, 47 Low (exit 1 because Low findings exist, as expected) |
| Tests | bare `pytest` | **10,915 passed, 3 skipped, 35 deselected**, 90.50 % coverage, 1,179.62 s (19:39) |

Bandit scanned 88,732 lines. The 47 Low findings are the documented subprocess
(B603/B606/B607), XML import (B405), pickle import (B403), a false-positive hardcoded
"password" (`--log-level`), and one example-plugin `try/except/continue` (B112).
The gate's security verdict (0/0) is honestly met.

### 3.2 Test suite shape

| Metric | Value |
|---|---:|
| Test modules (contain test functions) | 312 (of 379 test-tree files) |
| Test functions | 9,335 (10,915 cases after parametrisation) |
| Production statements (coverage) | 35,954 |
| Missed statements | 3,417 |
| Coverage | **90.50 %** (floor 75 %) |
| Suite runtime | 19 min 40 s |
| Warnings | 1,362, of which 1,361 are one Sphinx `RemovedInSphinx11Warning` from `test_docs_build.py`; 1 is a Click deprecation in a test |
| Markers deselected by default | `hardware`, `real_ml`, `worker_memory` |
| Tests skipped | 3 (symlink unavailable, Unix-only permission check, one broken Tcl/Tk slider) |

### 3.3 Coverage is bimodal

The aggregate is real, but it hides the weak spots. Files with ≥60 statements,
lowest coverage first:

| Coverage | Missed / statements | Module |
|---:|---:|---|
| 0.0 % | 132 / 132 | `utilities/benchmark_library_stats.py` (developer script, not in any test) |
| **39.6 %** | **113 / 187** | **`audio_suite_shared/tag_helper_apev2.py`** |
| 39.7 % | 85 / 141 | `cd_ripper/core/drive_handler.py` (hardware-dependent; acceptable) |
| 55.7 % | 39 / 88 | `cd_ripper/ui/setup_tab.py` |
| 58.0 % | 86 / 205 | `stem_separator/app.py` |
| 60.0 % | 68 / 170 | `utilities/resize_music_recursive.py` |
| 62.5 % | 66 / 176 | `utilities/measure_worker_memory.py` |
| 64.5–77 % | — | most GUI `app.py` modules (`audio_normalizer` 64.5, `replaygain_analyzer` 64.8, `tempo_analyzer` 65.8, `tag_editor/ui/app` 67.3, `music_format_converter` 68.1, `audio_enhancer` 69.1, `asx_extractor` 70.8, `mood_analysis_batch_tagger` 70.9, `cd_ripper/ui/rip_tab` 71.5, `noise_reduction` 72.8, `album_genre_tagger` 73.9, `cd_ripper/track_processor` 74.9) |

The APEv2 gap is the one that matters: `.wv` is a writable format and the BPM, key,
ReplayGain, genre and mood tools may write to it, yet only its ISRC path is tested
(R-07). The GUI gaps are mostly event wiring and layout, lower risk, but they are
exactly where the callback-payload defects D112/D113 historically lived.

### 3.4 Test design: real strengths

- **Behaviour locks are everywhere.** `tests/test_callback_payload_contract.py`
  resolves 14 GUI tools × 3 callback seams by parsing (not importing) the tree and
  fails if a tool stops wiring `on_error`. `tests/test_completion_seam.py` freezes
  required handler parameters and proves dropping one raises `TypeError`.
- **Anti-vacuity is explicit.** `tests/test_vacuous_asserts.py` rejects
  `assert x or True`, bare-tuple assertions and similar shapes via AST, with a
  self-check that each matcher can match. This is rare and valuable.
- **Registration is locked.** Tool manifests, Master Driver state keys, arg builders,
  card names, launcher guards, guide resolution, README tool rows, CLI schema and
  payload conformance all have dedicated locks.
- **Real audio is used where it counts.** `lossless_gain` tests decode the resulting
  MP3 and measure per-channel RMS; FLAC/MP3/MP4/OGG/Opus/WV/APE/MPC/DSF handlers are
  round-tripped through committed fixtures; the BPM/key corpus is committed.
- **Documentation locks are real.** User-guide `.docx` freshness is compared by zip
  entry data, not timestamps; docs build fails on a parser warning; `docstring_coverage`
  locks the shared API surface.
- **CI runs the locks early** (docs locks in a separate job) so a stale artifact does
  not wait 20 minutes to fail.

### 3.5 Test design: concerns

- **Mock-heavy at the top.** 242 of 312 test files reference `MagicMock`/`patch(`;
  only 66 reference `AudioSegment`/`mutagen`. UI tests are necessarily mock-based,
  but the ratio means a lot of tests assert wiring, not audible outcomes.
- **A 20-minute default suite** with `--cov` always on is too slow for a tight edit
  loop. There is no documented "fast" marker/subset; `--no-cov` and `-m` help, but a
  named `unit`/`smoke` profile would make the local loop practical.
- **Negative-contract tests still exist.** The prior audit's M5 pattern (assert a
  side effect did *not* happen, with no positive counterpart) is reduced but not
  structurally eliminated.
- **No fuzzing/property tests for parsers.** The suite treats audio and playlists as
  untrusted (SECURITY.md), but the pattern language, CUE parser, ASX parser and tag
  payloads have no hypothesis/fuzz harness.

---

## 4. Code quality, readability and maintainability

### 4.1 Strengths

| # | Strength | Evidence |
|---|---|---|
| S-01 | **Clear layering and a genuinely shared core.** | 28 kLOC in `audio_suite_shared`, used by all 30 tools; GUI/CLI/driver share processors rather than reimplementing DSP. |
| S-02 | **Consistent naming and module purpose.** | 542/550 modules have a module docstring; only seven empty `__init__.py` files and one utility lack one. Functions are verb-based and predictable (`process_*`, `write_*`, `read_*`, `run_*`). |
| S-03 | **Structured exception taxonomy with user-facing wording.** | `AudioSuiteError` subclasses, `map_to_audio_error`, `user_message_for`, and `USER_MESSAGES` rendered into `docs/user/messages.md` with a test that keeps them in sync. |
| S-04 | **Logging is split by audience.** | `logs/audio_suite.log` is lifecycle + WARNING+; per-program logs carry full detail; `AUDIOSUITE_LOG_DIR` isolates tests; uncaught and worker-thread hooks write crash traces. |
| S-05 | **Undo is a first-class product feature.** | 1,198-line `batch_undo` with tag snapshots, file overwrites, deletes, reorg records, cross-thread batch joining, and documented pruning. Almost no competitor offers this. |
| S-06 | **Dry-run is threaded through most destructive paths.** | Tag updater gates both snapshot and save; Tag Editor gates the writer; scrubber/converters/repair tools pass `is_dry_run` into the worker; `run_inplace_dsp_batch` copies to temp and only copies back on live runs. |
| S-07 | **Configuration is centralized (mostly).** | `suite_config` with cross-process lock, atomic replace, cache invalidation and preset helpers; tool-local JSON is limited to secrets/structured data. The album-art exception is a defect (R-04), not the pattern. |
| S-08 | **The CLI is a real interface, not an afterthought.** | 30 commands, JSON payload schema with recorded examples, `--json-schema`, group-level logging, schema-conformance CI, and CLI/driver flag parity tests. |
| S-09 | **The plugin system is well designed.** | Manifest-as-data discovery, closed key sets, id/CLI/launcher validation, four hosted extension points, per-plugin enable map, errors counted per plugin, no plugin import during discovery. |
| S-10 | **Documentation is unusually strong.** | 32 user guides rendered from Markdown, generated docs index/README table, Sphinx+MyST with warning-as-error, 20 plan files plus prior audit reports (17.5 kLOC), and CHANGELOG discipline. |
| S-11 | **Registration mistakes fail loudly.** | Pre-flight guard, launcher lock, card-name lock, arg-builder tests, manifest/state/README/guide locks. The tool checklist is not just prose. |
| S-12 | **Security basics are present and tested.** | Encrypted key storage with Windows ACL restriction, key backup on replacement, secret scanning instructions, subprocess allowlist, Bandit 0/0, dependency floors for known advisories. |

### 4.2 Concerns

#### C-01 — GUI scaffolding is still duplicated across most tools (medium)

`audio_suite_shared/tool_app_base.py` extracts two families, but only five tools use
them (`bpm_analyzer`, `lyrics_manager`, `noise_reduction`, `pop_click_remover`,
`ml_denoiser`). Across 28 `app.py` files:

| Repeated method | Files defining it |
|---|---:|
| `_build_ui` | 22 |
| `_apply_cli_args` | 20 |
| `_collect_settings` / `_apply_preset` | 19 each |
| `_on_complete` | 15 |
| `_on_preset_selected` | 13 |
| `_open_help` / `_open_log` | 16 / 13 |
| `_browse_folder` / `_open_folder` | 12 each |
| `_save_current_as_preset` / `_delete_preset` | 12 each |

Six apps are 600–830 lines (`library_stats` 827, `audio_refinery` 687,
`file_reorganizer` 664, `master_driver` 634, `audio_fingerprinter` 622,
`music_format_converter` 608). This is exactly the divergence surface that produced
the D112/D113 callback defects. The shared scaffold's catch-all rule is good; the
problem is that most tools do not use it.

**Plan action:** extend `tool_app_base` to the remaining preset/CLI/progress tools,
or extract a `PresetController` + `RunControls` mixin. Do it tool-family by tool-family
with the callback contract test as the acceptance gate.

#### C-02 — `tag_field_updater` is a second tag layer, duplicated eight times (medium)

`tag_field_updater/core/transformation_rules.py` contains eight near-identical
`process_*_file` functions (643 lines total: 111/66/66/66/66/101/101/66) that each
open a mutagen object, walk `TAG_MAPPINGS`, rewrite fields and save. Consequences:

- New tag fields and formats must be implemented up to eight times.
- `.wma` is supported here but not by the canonical format list; `.wv/.spx/.dsf`
  are not supported here though the rest of the suite reads them.
- The shared `tag_helper` undo/snapshot and format semantics are bypassed (this layer
  does its own snapshots, correctly, but separately).
- The same genre mapping is expressed in `TAG_MAPPINGS` and again in the tag handlers.

**Plan action:** introduce a format-agnostic mapping engine over the existing
`TagHandler` interface, with a small per-format adapter only where a container needs
special handling (ID3 frame vs Vorbis comment vs MP4 atom). Keep the current functions
as thin adapters until parity tests pass, then delete them.

#### C-03 — The tag-helper facade has an import cycle and an import-order landmine (medium)

`tag_helper_base.py` defines `BaseTagHandler` and then imports every handler at the
bottom (`lines 454–459`, all `# noqa: E402`) so the factory can reference them. Each
handler imports the base at its top. The result:

```
python -c "import audio_suite_shared.tag_helper_apev2"
ImportError: cannot import name 'APEv2Handler' from partially initialized module
  ... (most likely due to a circular import)
```

The same failure occurs for `tag_helper_mp3` and `tag_helper_dsf`. Normal suite code
works because it always enters through `tag_helper_base`/`tag_helper`, but a plugin
author, a test, or a future tool that imports a handler directly hits an error that
looks like a broken installation. The module docstrings warn about it; a warning is
not a design.

**Plan action:** move `BaseTagHandler`/`LyricsTags` into a leaf module that imports
nothing from the handler package (`tag_helper_protocol.py`), have handlers import
that, and move the factory/registry into `tag_helper_factory.py` importing the leaf
and the handlers. Re-export from `tag_helper_base` for compatibility. Add a test that
imports each handler module in a fresh subprocess.

#### C-04 — Large classes/functions concentrate risk (medium)

| Entity | Size |
|---|---:|
| `LibraryStatsApp` | 827 lines |
| `BaseFileProcessor` | 784 |
| `MP3Handler` | 688 |
| `AudioRefineryApp` | 687 |
| `BatchUndoLog` | 685 |
| `FileReorganizerApp` | 664 |
| `LibraryCache` | 644 |
| `AudioSuiteDriver` | 634 |
| `FingerprinterApp` | 622 |
| `MusicFormatConverterApp` | 608 |

Functions: 123 exceed 100 lines, 8 exceed 200. Highest complexity (branch proxy):
`_collect_tags_to_preserve` (CC 58, 106 lines), `parse_guide` (CC 40),
`library_stats/cli.stats` (CC 39), `audio_fingerprinter/utils/cli_args.parse` (CC 39),
`audio_refinery/app._apply_preset` (CC 38). 31 of 3,049 functions have CC ≥ 20.

Some size is inherent (per-format handlers); the scrubber's preserve collector is the
clearest split candidate: one function per container family would remove a 58-branch
decision tree and make the FLAC/MP3/MP4 rules independently testable.

#### C-05 — Broad exception handling is common and unlinted (medium)

181 production `except Exception` handlers (51 in `audio_suite_shared`, 16 in
`audio_refinery`, 13 in `tag_field_updater`, 12 in `metadata_scrubber`). Many are
deliberate and commented (mutagen internals, best-effort measurement, undo snapshot
must not block a write), but Ruff's `BLE001` is not enabled, so a new blind catch is
invisible to the gate. Some fallbacks fabricate plausible measurements: refinery
`measure_*` returns `peak_db=0.0`, `rms_db=-60.0`, `dynamic_range_db=0.0` on any
failure. Those values are reported as measurements, not as "unavailable", which is
the same fabricated-value class the suite rightly refuses for BPM/key.

**Plan action:** enable `BLE001` with a `per-file-ignores`/inline `# noqa: BLE001 —
reason` policy, and change best-effort measurement returns to `None`/`{"error": ...}`
rather than plausible numbers.

#### C-06 — Version-history prose lives in module docstrings and comments (low)

437 occurrences of "Changed in …" in production modules, often as a multi-paragraph
preamble (`tag_helper_apev2.py`, `batch_orchestrator.py`, `pyproject.toml`). It is
excellent traceability, but it bloats the API reference (Sphinx renders it), goes stale
(the "new APEv2 handler" note is from 1.1.0), and duplicates CHANGELOG. Plan-ID
comments (`D112`, `P6`, `§7`) are opaque without the plans.

**Plan action:** keep one-line "why this shape" comments where the code is
non-obvious; move release history to CHANGELOG/plan logs. Do not mass-delete—this is
a style rule for new code plus a cleanup when a module is next touched.

#### C-07 — Typing/style is strong but not uniform (low)

- 1,098 uses of `Any` in production, some at real boundaries (`dsp_chain` params,
  duck-typed Tk objects, mutagen tags). Protocols are used only 8 times and
  `TypedDict` twice; several `dict[str, Any]` payloads could be `TypedDict`.
- `Optional[...]` (135) and `X | None` coexist; `os.path` appears 375 times while
  `pathlib` is used 100 times. Neither is wrong, but the mix slows reading.
- 34 `# type: ignore` and 69 `# noqa` in production — low for 108 kLOC, and most are
  documented third-party stub gaps.

**Plan action:** add `UP`, `SIM`, `RUF` (or a curated subset) to Ruff; adopt
`pathlib` for new code; replace `Any` payloads with `TypedDict`/Protocols when the
module is next touched. Do not attempt a tree-wide style rewrite. §5.2 measures the
same gaps and adds two that are not visible from counts alone: module-level palette
globals in `styles.py`, and `str`-mixin enums compared by `.value` string in
`audio_enhancer/app.py`.

#### C-08 — Documentation is deep but narrow and sometimes stale (low)

Seven prose pages under `docs/` for 30 tools; the API reference is docstring-derived
and the user guides are complete (32 `.docx`). The README intro is stale (27 vs 30
tools). The docs locks validate generated artefacts but not hand-written prose claims.

**Plan action:** add a short architecture page (the §2.2 diagram and shared-module
table), and generate the tool count in the README intro from the registry so it
cannot drift.

#### C-09 — Non-ASCII status glyphs leak into console-facing output (low)

357 of 550 production files contain non-ASCII characters: 30,197 box-drawing `─`
(comment separators), 1,085 em dashes, 143 `→`, 37 `✗`, 24 `✓`, plus `⚠`, `📊`.
Most are comments and harmless, but some are user-facing log/CLI strings. During this
audit a simple print of the inventory failed with
`UnicodeEncodeError: 'charmap' codec can't encode character '\u2500'` under the
default cp1252 console, and pytest displays a skip reason as
`Slider update failed � broken Tcl/Tk environment`. The utilities rule already
requires ASCII markers; GUI/CLI status lines should follow it too.

**Plan action:** ASCII markers (`[OK]`, `[WARN]`, `[ERROR]`) for CLI/log output;
keep typography in docs/comments; add a test that subprocess CLI output is
cp1252-encodable.

#### C-10 — Packaging metadata is minimal (low)

`pyproject.toml` declares name/version/readme/license/dependencies/scripts, but no
`authors`, `description`, `classifiers`, `keywords` or `[project.urls]`. No package
ships `py.typed`, so the strict internal typing is invisible to downstream type
checkers. There is no pre-commit config mirroring the gate; contributors rely on
remembering the commands.

**Plan action:** add PEP 621 metadata, `py.typed` to public packages if the CLI is
meant to be importable, and a pre-commit config running Ruff/mypy on changed files
(full gate still in CI).

---

## 5. Python gold-standards adherence

"Gold standard" here means the practices a reviewer would apply to a modern typed
Python application: PEP 8/257/484 conventions, stdlib logging and exception guidance,
dataclasses and enums over ad-hoc tuples/strings, `pathlib` and context managers for
resources, lazy evaluation where it matters, a rule set that encodes the house style,
and test design that can fail. The measurements below come from the same AST/text
sweep as Appendix A (550 production modules, tests and `conftest.py` excluded).

### 5.1 Idiomatic strengths, measured

| Practice | Measurement | Assessment |
|---|---|---|
| **Complete annotations** | 0 of 3,049 production functions/methods lack a return annotation (excluding `__init__`); `mypy` runs `strict = true` clean over 549 files | Most "typed" codebases are partially typed; here the gate enforces it, including private helpers |
| **Lazy logging** | 537 logger calls; 506 use `%`-style placeholders; exactly **1** f-string logger call (0.2 %) | Matches stdlib guidance: no message formatting when the level is disabled |
| **Exception chaining** | 453 `raise` statements, 41 with `raise … from …`, and only **1** raise inside an `except` block that omits `from` in the whole tree | Near-perfect context preservation; tracebacks name the real cause |
| **Immutable value objects** | 158 dataclasses, **109** `frozen=True` | Results, batch progress and DSP parameters are snapshots; shared mutation is rare by design |
| **Documented surface** | 543/551 modules have a module docstring (the 8 gaps are 7 empty `__init__.py` and one utility); 844 Google-style `Args:` sections; `__all__` in 54 modules | The shared API's docstrings are additionally locked by `tests/test_docstring_coverage.py` |
| **Resource handling** | 63 of 65 `open()` calls are inside `with`; SQLite connections, locks and temp files use context managers; config/undo writes are atomic `os.replace` | No leak-prone handle idiom found in the audited paths |
| **No dynamic-language abuse** | 0 star-imports, 0 bare `except:`, 0 `eval`/`exec` in first-party code, no monkey-patching outside tests, `__slots__` only where useful (2) | The suite is debuggable and greppable |
| **Small global footprint** | 26 `global` statements across 550 modules, confined to five infrastructure modules (config cache, plugin registry, theme palette, playback, warning latch) | Low for 108 kLOC, and each has a reset hook for tests |
| **Deliberate concurrency** | 27 `Lock()`/`RLock()` sites; a cross-process file lock for shared config; a documented Tk-thread hand-off (`SimpleQueue` + poller) | Threading is explicit rather than incidental, and the one forbidden pattern is written down |
| **State as enums** | 13 enums for status/verdict/recovery/step state, with a `status_text()` helper written specifically to avoid the `str`-mixin formatting trap | Magic strings are the exception, not the rule |
| **Small suppression budget** | 34 `# type: ignore`, 69 `# noqa` in 108 kLOC, nearly all documented third-party stub gaps | Suppressions are visible and justified |
| **Honest toolchain** | Committed `uv.lock`, `requires-python >=3.11` matched by the lock, CI matrix 3.11/3.12/3.14; tool config annotated with the reason for each exclusion/marker | The earlier lock-vs-floor split is closed, and the configuration is reviewable rather than folklore |
| **Consistent synchronous design** | 0 `async def`, 0 `yield` in production; blocking DSP runs on bounded thread pools, progress is callback-based | Coherent for a Tk desktop app; no half-adopted async model to reason about |

Two choices are neutral rather than good or bad and are recorded so a plan does not
"fix" them: the suite uses no `match` statements (0) despite the 3.10+ floor, and it
uses composition plus plain functions where a class hierarchy would also work.

### 5.2 Idiomatic gaps

| Gap | Evidence | Consequence | First step |
|---|---|---|---|
| **The lint rule set is narrower than the house standards** | `select = [E, W, F, I]` plus 15 `B`/`PLW` codes. No `UP`, `SIM`, `BLE`, `PTH`, `T20`, `ARG`, `RUF`, `TRY`, `PLW0603` | Idiom drift is invisible to the gate: 181 broad excepts, 167 `print()` calls, 375 `os.path` sites, 6 `str`-mixin enums | Adopt the rules warn-only, then ratchet per directory; `BLE001` first (C-05) |
| **Two path idioms** | `os.path` 375 occurrences vs `pathlib` 100 | Stringly paths invite Windows edge cases; the traversal defect (R-03) is written in `os.path.join` terms | One `contained_path()` helper returning `Path`; `PTH` for new code |
| **Mixed optional syntax** | 135 `Optional[...]` alongside `X \| None` | Cosmetic, but it hides the modern idiom and reads inconsistently across modules | `UP007` once the Ruff target is corrected (R-15) |
| **`Any` where a shape is known** | 1,098 `Any`; `Protocol` 8 occurrences in 4 modules; `TypedDict` 2 occurrences in 1 module | Callback payloads are the D112/D113 defect class, yet their shapes are enforced by parsing tests, not by mypy | `TypedDict` for `on_complete`/progress payloads and CLI JSON; `Protocol` for the handler/processor seams |
| **Mutable module globals in the UI layer** | `styles.py` rebinds ~20 palette/font globals on theme switch (lines 99-108, 206-207, 258) | Theme state is global by construction, and `importlib.reload` cannot restore it (the documented order-dependent-test trap) | A `Palette` object returned by `apply_theme()` and injected into widgets, or an explicit snapshot/restore |
| **`str`-mixin enums instead of `StrEnum`** | 6 of 13 enums mix in `str`; on this host (3.14.9) `f"{FingerprintStatus.MATCHED}"` renders `FingerprintStatus.MATCHED`. The suite works around it via `status_text()`, but `audio_enhancer/app.py:475,522` compare `r.status.value == "Done"` | One new interpolation or string comparison reintroduces the display defect AGENTS.md records as shipped once already | `StrEnum` (3.11+) or a shared `__str__ = str.__str__` base; compare members, never `.value` strings |
| **Release history in docstrings** | 437 "Changed in …" preambles | PEP 257 describes current behaviour; Sphinx renders stale history as API documentation | Style rule for new code; clean on touch (C-06) |
| **Console idioms in scripts** | 159 `print()` under `utilities/`, 3 in the shared package | Bypasses the log split and carries non-ASCII glyphs (C-09) | `[OK]`/`[ERROR]` markers and `logging` for anything long-running |
| **Whole-file materialisation, no streaming** | `yield` count 0; every tool decodes a complete track; the in-memory DSP chain multiplies it by two or three copies | Peak memory is file size × channels × depth × copies × workers, bounded only by the worker cap; fine at album scale, unmeasured at DSD/long-recording scale | Document a memory budget per worker; consider a chunked path only if a real workload demands it |
| **No fast feedback profile** | 19:39 default suite with coverage always on | The feedback loop is the main daily cost for a contributor | A `smoke`/`unit` marker subset documented in CONTRIBUTING (Q-09) |

### 5.3 Scorecard

| Dimension | Rating | Basis |
|---|---|---|
| Readability & naming | **A−** | consistent modules, docstrings, lazy `%` logging, descriptive names; large functions and docstring history reduce it |
| Type safety | **A−** | strict mypy, 549 files clean, typed generics/dataclasses; `Any` at boundaries, no `py.typed` |
| Lint/format | **B+** | Ruff clean and formatted; narrow rule set, `py310` target under a 3.11 floor, no `BLE`/`UP`/`SIM` |
| Testing | **A−** | 10,915 tests, 90.5 %, real-audio outcome tests, anti-vacuity/contract locks; bimodal coverage, mock-heavy, 20 min |
| Error handling | **B+** | rich hierarchy, mapping, sanitised messages, chaining; 181 broad catches and fabricated measurement defaults |
| Security | **B** | allowlist, no shell, Bandit 0/0, ACLs, secret scan; two bypasses, path traversal, non-blocking dep audit |
| Configuration | **A−** | shared store with cross-process lock/atomic write; one split config source |
| Logging/observability | **A** | audience split, rotating handlers, crash hooks, test isolation, no f-string logging |
| Documentation | **A−** | guides, Sphinx, generated indexes, decision logs; thin architecture prose and stale README intro |
| Packaging/release | **B−** | committed lock, version single-source, installer; minimal metadata, no `py.typed`, Windows-only package |
| Performance | **B+** | library cache with batching/WAL, capped workers, in-memory DSP chain; no measured budgets, all-futures dispatch |
| Python 3.11–3.14 compatibility | **B** | CI matrix 3.11/3.12/3.14; Ruff targets 3.10, mypy targets 3.12, only Windows exercised |

**Overall:** comfortably above the "script suite" baseline and close to library-grade
in the shared core; held back by duplicated UI/tag layers and a few correctness gaps,
not by everyday code hygiene. The strongest idiomatic signals are the complete
annotations, lazy logging, exception chaining and immutable models; the weakest are
the permissive lint selection (which lets idiom drift accumulate unseen), the partial
`TypedDict`/`Protocol` coverage of payload seams, and global theme state in the UI layer.

---

## 6. Detailed findings and reproductions

Severity follows the repository's own rule: anything that can corrupt, mis-normalise,
mis-tag or wrongly convert audio is release-blocking regardless of how small the code
change is.

### R-01 — ReplayGain album gain is duration-unweighted (Blocker, audio correctness)

**Where:** `replaygain_analyzer/core/gain_calculator.py:72`

```python
album_gain: float = target_lufs - statistics.mean(lufs_values)
```

**Why it is wrong:** album loudness is the loudness of the album's combined signal, not
the arithmetic mean of each track's integrated loudness. A ten-second loud track and a
three-minute quiet track contribute in proportion to their duration (and, for EBU R128,
to their gated mean-square energy). Averaging per-track LUFS gives every track equal
weight regardless of length.

**Measured example** (arithmetic, conservative):

| Track | Duration | Integrated | Code's contribution | True energy contribution |
|---|---:|---:|---:|---:|
| A | 10 s | −10 LUFS | equal weight | 10 s of 0.1 mean-square |
| B | 30 s | −30 LUFS | equal weight | 30 s of 0.001 mean-square |

- Code: mean = −20 LUFS → at target −16 LUFS, album gain = **+4.0 dB**.
- Energy-weighted album loudness = `10·log10((10·0.1 + 30·0.001)/40)` ≈ **−15.9 LUFS**
  → album gain ≈ **−0.1 dB**.
- Error: **≈4.1 dB**, on a tag every ReplayGain-aware player applies to the whole album.

The existing test `test_gain_calculation_multiple_files_uses_mean` locks the wrong
behaviour, and the previous audit's "verified non-finding: true album-mode gain" was
incorrect. This is not a rounding issue.

**Impact:** albums with mixed track lengths/levels get a wrong `REPLAYGAIN_ALBUM_GAIN`;
quiet tracks can be boosted 4 dB too far and loud ones attenuated too far, with
clipping risk on the boost side (track peak is stored separately, but players may not
honour it).

**Fix shape:** compute album loudness from per-track duration + integrated loudness by
summing mean-square energy (`10**(LUFS/10) * duration`) and converting back; or run
EBU R128 over the concatenated album in one pass (the correct but slower route).
Store each track's duration during measurement (ffprobe already provides it for
other tools). Document which ReplayGain flavour is written.

**Acceptance test:** two synthetic tones of different lengths/levels; write tags with
the real pipeline; independently concatenate the decoded tracks and measure with
`ffmpeg -af ebur128`; assert the album gain differs from `target − measured_album` by
≤0.2 dB for both a length-skewed and a level-skewed pair.

### R-02 — ALAC output always fails (Blocker, audio conversion)

**Where:** `music_format_converter/core/formats.py:28` lists `alac` as a lossless
format; `ffmpeg_params.py:264` emits `-codec:a alac`; `file_processor.py:447` names the
output `f"{base_name}.{output_format}"`, i.e. `song.alac`.

**Reproduction:**

```
$ python -m audio_suite_shared.cli_app convert <dir> --format alac --output-dir <out> --live
...
ERROR [AudioExternalToolError] Conversion failed:
  [out#0] Error initializing the muxer for ...\a.alac: Invalid argument
...
[ERROR] a.wav: An external tool (e.g. ffmpeg) failed...
Summary: 1 files, 0 converted, 0 skipped, 1 errors
$ echo $?
0
```

FFmpeg 8.0.1 cannot choose a muxer for the `.alac` extension; ALAC is normally carried
in an MP4/M4A container. Every ALAC conversion fails, and the user is told only that an
external tool failed. The unit tests assert the codec argument but never run a real
ALAC conversion.

**Impact:** an advertised lossless target is 100 % broken; the failure consumes the
run, and (R-06) the process still exits 0.

**Fix shape:** either (a) map ALAC to an `.m4a`/`.mp4` container and set the codec to
`alac` (label it "ALAC (M4A)" in the UI), taking care not to collide with AAC `.m4a`
outputs, or (b) remove ALAC from the selectable outputs until implemented. Do not leave
the current "codec known, container unknown" state.

**Acceptance test:** convert a real WAV to ALAC through the CLI; `ffprobe` must report
`codec_name=alac` in a `mov,mp4,m4a` container; decode and compare per-channel RMS
against the source; `can_convert` must keep rejecting invalid targets.

### R-03 — File Reorganizer path traversal via tag values (High, security)

**Where:** `file_reorganizer/core/pattern.py:295` `resolve_path`; `engine.py:261`
resolves the pattern and `engine.py:274` joins the result to `base_dir` with no
containment check.

**Reproduction:**

```
>>> resolve_path("../../evil", {})
'..\\..\\evil'
>>> os.path.abspath(os.path.join(base, resolve_path("../../evil", {})))
'D:\\...\\AudioSuite-Pro\\evil'   # outside the chosen sandbox
```

Sanitisation replaces `<>:"|?*` and control characters and collapses separators, but
never rejects `..` components or verifies the result stays under `base_dir`. Tags are
explicitly untrusted input in `SECURITY.md`; a downloaded file whose album/title tags
contain traversal sequences can make a batch "move/copy" write outside the destination.
The destination-exists check does not help—it only prevents overwriting a specific path.

**Impact:** arbitrary file copy/move outside the user-selected tree, with the user's
permissions. This is the highest-severity security finding in the suite.

**Fix shape:** after building the path, resolve both `base_dir` and the candidate and
reject unless `candidate.is_relative_to(base_dir.resolve())`; additionally reject any
component equal to `..` (and Windows drive/UNC prefixes). Apply the same guard to the
CUE/filename-derived paths in the CD ripper. Add a regression with tags
`["../../evil", "..\\..\\evil", "C:\\Windows\\x"]`.

**Acceptance test:** a dry run and a live run on a file tagged with traversal values
must report a skip/error and create nothing outside the destination; the resolved path
must remain under `base_dir`.

### R-04 — Album-art GUI and CLI read different key files (High, functional/config)

**Where:** `album_art_sync/app.py:78` calls `load_config(__file__)` →
`album_art_sync/album_art_config.json`; `album_art_sync/core/pipeline.py:213` calls
`load_config(__file__)` → `album_art_sync/core/album_art_config.json`. The CLI delegates
to `resolve_and_apply`, so it takes the `core/` path.

**Observed on this install:** the GUI-side file has the Fanart.tv `app_key`/`client_key`
set; the `core/` file is blank. The GUI therefore finds artwork from Fanart.tv, while a
CLI run uses an empty key and silently loses that source. Both files are gitignored, so
the split is invisible in review.

**Impact:** source availability depends on entry point; batch runs quietly do less than
interactive runs; a user who configured keys in the GUI cannot reproduce the result
from the CLI.

**Fix shape:** one `config_path()` in `album_art_sync/config/settings.py` resolving a
canonical directory (the suite's config directory, or `album_art_sync/config/`), and
every loader/saver uses it. Migrate an existing legacy file on first read, log which
path was used at DEBUG, and delete the duplicate. A test must assert that the GUI loader
and the pipeline loader resolve the same path and see the same key.

### R-05 — Metadata Scrubber discovers formats it cannot load (High, functional)

**Where:** `metadata_scrubber/core/scrubber.py:46`

```python
SUPPORTED_EXTENSIONS = {ext for ext in _CANONICAL_EXTENSIONS if ext not in (".wma",)}
```

`_CANONICAL_EXTENSIONS` is the 14-extension suite list, which now includes
`.wv/.ape/.mpc/.spx/.dsf`. `_load_audio` (line 71) handles only MP3, FLAC, OGG, OPUS,
M4A/MP4, WAV, AIFF/AIF and raises `ValueError("Unsupported audio format: .wv")` for the
rest.

**Reproduction:** put a `.wv` file in a folder and run the scrubber; it is discovered,
then reported as `[UNREADABLE]` and counted as an error, although the format is
perfectly valid and supported by the rest of the suite.

**Impact:** false errors on mixed libraries; users conclude their WavPack/DSD/Speex
files are corrupt. The comment above the filter still refers to `.wma`, which is no
longer in the canonical list—evidence the filter was not revisited when the format list
widened.

**Fix shape:** derive the scrubber's discoverable set from the formats `_load_audio`
actually supports (a single mapping keyed by extension), or route loading through
`TagHandlerFactory` so the scrubber inherits every handler. Add a parameterised test
that every advertised extension loads a real fixture.

### R-06 — CLI exits 0 when a batch reports errors (Medium, automation contract)

**Where:** the `convert` command (and, by inspection, the other batch commands) print a
summary with `errors` but return normally; Click therefore exits 0.

**Reproduction:** the ALAC run above printed `1 errors` and `$?` was `0`.

**Impact:** shell scripts, schedulers and CI cannot tell success from failure; a batch
that converted 0 of N files looks successful. It also weakens the otherwise excellent
JSON contract, where `errors` is visible but the process status says "fine".

**Fix shape:** set a non-zero exit code when `error_files`/`errors > 0` (usually 1, with
a documented distinction from usage errors), across all batch commands; keep `--json`
payloads unchanged. Add `CliRunner` tests asserting `exit_code != 0` for a failing file
and `0` for an all-skipped-but-clean run (decide and document that case).

### R-07 — APEv2/WavPack tag writes are effectively untested (Medium, test gap)

**Where:** `audio_suite_shared/tag_helper_apev2.py` — 39.6 % coverage, 113 of 187
statements missed.

The handler surface (BPM, key, tempo marking, genre, mood, energy, artwork, editable
tags, `set_raw_tags`, `delete_tags`, custom genre fields, replaygain reads) is exercised
only through the ISRC round-trip tests. There is no `TestAPEv2Handler` class, unlike
MP3/IFF/Vorbis/MP4. A manual round-trip of BPM/key/genre on the committed
`silence-44-s.wv` works today, so this is a verification gap rather than a known bug.

**Why it matters:** `.wv` is writable, and BPM/Key/ReplayGain/Mood/Genre tools can write
it. A regression could corrupt WavPack tags while the suite stays green, and `.ape/.mpc`
(which the handler also serves) are read paths users rely on.

**Fix shape:** mirror the MP3/Vorbis handler test classes for APEv2 using the committed
`silence-44-s.wv`, `mac-399.ape` and `click.mpc` fixtures; assert read-back through a
fresh handler, artwork bytes, multi-value/`\x00` semantics, and `delete_tags` behaviour.
Add `.wv` to at least one end-to-end analysis-tool test (BPM or Key) that writes a tag.

### R-08 — Two packages bypass the documented subprocess boundary (Medium, security policy)

**Where:**

- `audio_enhancer/core/ffmpeg_io.py:123,186,280` call `subprocess.run` directly for
  ffprobe/ffmpeg decode and encode.
- `cd_ripper/ui/results_tab.py:199,209,221` call `subprocess.Popen` for `powershell`
  (drive eject), `eject`, and `explorer /select`.

`SECURITY.md` states that all first-party subprocess invocations go through
`audio_suite_shared/secure_subprocess.py`, which enforces the executable allowlist and
refuses `shell=True`; it explicitly calls a raw call "a review finding, not a pattern".
The FFmpeg calls resolve via `shutil.which` (absolute path), which limits PATH hijack,
but the CD-ripper PowerShell call builds a command string with an f-string, and none of
these calls pass through argument validation or the central allowlist.

**Impact:** the security model's stated invariant is false; a future edit to the drive
string or an added command could become injection. Bandit reports them as Low
(B603/B606/B607), which the gate accepts, so the drift is invisible.

**Fix shape:** route the enhancer calls through `run_secure_subprocess`; replace the
PowerShell one-liner with a fixed argv/COM helper behind `platform_utils` (or add
`powershell`/`explorer`/`eject` to the allowlist only with fixed, non-interpolated
arguments and a documented exception). Add a test that a non-allowlisted executable is
refused.

### R-09 — Enhance dry run does not preview the live chain (Medium, correctness/UX)

**Where:** `audio_enhancer/core/processor.py:130`

```python
enhanced = apply_enhancement_chain(audio, sample_rate, params, apply_effects=not dry_run)
```

The module docstring says Sprint 1 effects are bypassed under dry run "so a dry run
still measures the base-chain level only". But the dry run still decodes and processes
audio, so there is no cost saving; the only effect is that the reported RMS/gain and
level preview correspond to a **different signal chain** than the live run when any
effect (reverse/karaoke/phaser/flanger/chorus/extra gain) is enabled.

**Impact:** a user tuning effects sees numbers that will not match the written file;
the dry run's core promise ("preview what will happen") is broken for the effect-
enabled configuration.

**Fix shape:** run the same chain in both modes and skip only the export/write; or, if
the base-chain-only preview is intentional, label it explicitly in the UI and hide the
effect-dependent gain/RMS, so no one mistakes it for the live result. Add a test that
dry-run and live-run measured arrays are identical (only disk writes differ).

### R-10 — A failed step satisfies dependencies in parallel batches (Medium, orchestration)

**Where:** `master_driver/batch_orchestrator.py:547/553` — both the success and the
failure branches execute `completed.add(tid)`; `_can_run` treats `completed` as the
dependency-satisfaction set.

**Impact:** if `bpm` fails, `tempo` (whose `DEPENDENCY_GRAPH` entry is `["bpm"]`) still
runs in parallel mode, against files that have no BPM tags. Sequential mode does not
consult the graph at all and relies on manifest order. A user sees a "completed" tempo
step that did nothing, or worse, a step operating on half-written output.

**Fix shape:** track `succeeded` separately from `finished`; when a dependency fails,
mark dependants `SKIPPED` with a reason (or gate them behind an explicit
"continue on error" setting). Add a parallel test where `bpm` fails and `tempo` must not
be submitted; keep the existing success-path test.

### R-11 — Dependency audit is advisory only (Medium, supply chain)

**Where:** `.github/workflows/ci.yml:174` — `continue-on-error: true` on the exported
lock `pip-audit` step, with a comment that it is "on probation for two sprints".

**Impact:** a new advisory against a shipped dependency turns the step orange but does
not fail the job; the suite can ship a known-vulnerable graph. This is a real gap for a
project that otherwise gates security tightly.

**Fix shape:** make the step blocking, with a small documented allowlist for accepted
advisories (and a date/reason); schedule a weekly audit so the allowlist ages visibly.

### R-12 — "Portable core" is not executed anywhere (Medium, verification)

`README.md` claims 29 of 30 tools have "no platform-conditional code" and a portable
CLI path, and there is a generated platform matrix with 31 branches. CI, however, runs
the test suite only on `windows-latest`; the docs locks and compile run on Ubuntu but do
not import/execute the tools. `msvcrt` locking, `fcntl`, `xdg-open`, path separators and
the `os.name` branches have unit tests with patched platforms, but no real POSIX run.

**Impact:** a portability regression can ship green. This is a claim-vs-evidence gap,
not a known failure.

**Fix shape:** add an Ubuntu (and ideally macOS) smoke job that installs the base + dev
extras, runs the shared and CLI tests plus a few tool suites, and asserts `audiosuite
doctor` / `--help` work; alternatively narrow the README claim to "Windows-first with a
portable core that is unit-tested, not CI-tested".

### R-13 — Library cache key is path + mtime only (Low, staleness)

`library_stats/library_cache.py:476` treats a file as cached when path and mtime match.
Some tag writers preserve mtime, backups restored with `copy2` preserve it, and
filesystems with coarse timestamps can miss two edits in the same tick. The cache is a
performance feature, but stale stats are presented as current.

**Fix shape:** add size (and optionally `mtime_ns`) to the identity, or invalidate a
directory when a scan detects any tag-write tool ran. Document the assumption.

### R-14 — Non-ASCII console output (Low, usability)

See C-09. Reproduced by the audit's own cp1252 print failure and the pytest skip line
with `�`. Fix user-facing status strings first; keep decorative characters in comments.

### R-15 — Tooling-version mismatch (Low, verification)

- `requires-python = ">=3.11"`, CI tests 3.11/3.12/3.14.
- Ruff `target-version = "py310"` — it permits only 3.10 syntax and never enforces
  3.11-only constructs; it also suppresses 3.11+ modernisations.
- mypy `python_version = "3.12"` — 3.12-only syntax (e.g. PEP 695) would type-check
  while failing on the 3.11 leg. The typecheck job runs only 3.12.

**Fix shape:** set Ruff to `py311` and mypy to `3.11` (or run mypy in the 3.11/3.14
matrix legs); add `UP` rules after the target is corrected.

### R-16 — README tool count is stale (Low, docs)

`README.md:3` says "27 first-party tools"; the registry reports 30 and the README's own
generated table has 30 rows. `README.md:66` says "the other 29 of 30 tools", which is
consistent with 30. The `test_readme` lock validates the generated table but not the
intro sentence.

**Fix shape:** render the count from `get_registry()` in the intro, or update the
sentence and add an assertion that the number matches `len(first_party())`.

---

## 7. Verified non-findings (do not "fix" these)

These were checked because they look suspicious or because the prior audit raised them;
they are working as intended.

| Check | Result |
|---|---|
| **FLAC artwork/lyrics survive a scrub** | Real FLAC with an embedded `Picture`, `LYRICS`, `ALBUMARTIST`, and an unrelated tag: after a live scrub, the picture remains, lyrics and album artist remain, the unrelated tag is gone. The FLAC handler mutates its loaded comment dict in place (the documented mutagen trap) and the scrubber re-reads the file before restoring. |
| **`suite_config` lost-update race** | The cache is invalidated inside `_file_lock()`; the prior H2 is fixed. Cross-process locking still works. |
| **Dry-run writes in tag tools** | Tag Field Updater gates snapshot + save on `dry_run`; Tag Editor gates the writer; the scrubber/converters short-circuit before write. No live write found in a dry run. |
| **ASX XML injection** | `asx_parser` rejects any `<!DOCTYPE`/`<!ENTITY` payload before `ET.fromstring`; it is a textual guard, but it closes the billion-laughs/XXE path for the supported format. Bandit B405 is the import, not an exploitable call. |
| **Undo pickle** | `pickle.loads` is limited to the user-local undo DB written by the suite; legacy payloads are migrated. Documented `# nosec`, acceptable threat model. |
| **APEv2 ISRC round-trip** | Manual BPM/key/genre write-read on `silence-44-s.wv` works; the gap is test coverage, not behaviour. |
| **CUE support** | `audiosuite cue parse/generate/split` exists; the CD ripper writes CUE sheets. |
| **Album-level fingerprint matching** | `audio_fingerprinter/core/album_cluster.py` implements Picard-style cross-file release-group consensus (with a decision margin and fallback), not merely per-file matching. |
| **Resampling/dither quality** | SoXR (`RESAMPLER = "soxr"`) and TPDF (`dither_method=triangular`) are used; this is a genuine quality choice. |
| **True peak in normalization** | `loudnorm=I=…:TP=-1.5:LRA=11` two-pass; the ceiling is hardcoded but applied. |
| **AccurateRip/offset** | The CD ripper implements AccurateRip v1/v2 checksums, disc IDs, offset detection and re-rip paths. |
| **Logging split** | Admin and per-program logs are separate, with test isolation via `AUDIOSUITE_LOG_DIR`; the prior M1 defect is fixed. |
| **Enum formatted into a message** | `audio_fingerprinter/core/file_processor.py:372` formats `result.status`, but that field is `MBStatus = Literal["ok", …]` — a plain `str` — not the `str`-mixin `FingerprintStatus`; member display goes through `status_text()`. Safe as written, and §5.2 records why the helper must stay. |

---

## 8. Market comparison

### 8.1 Method and sources

Comparisons use each vendor's 2025–26 documentation, not hands-on trials. Sources:

- **Mp3tag:** <https://www.mp3tag.de/en/> · <https://docs.mp3tag.de/>
- **MusicBrainz Picard:** <https://picard-docs.musicbrainz.org/en/v2.13/faq/faq_file_formats.html> · tag mapping and cover providers in the same docs tree · <https://picard.musicbrainz.org/downloads/>
- **beets:** <https://beets.io/> · <https://beets.readthedocs.io/en/stable/plugins/index.html> · duplicates and export plugins
- **TagScanner:** <https://www.xdlab.ru/en/>
- **Kid3:** <https://kid3.kde.org/> · <https://docs.kde.org/trunk_kf6/en/kid3/kid3/>
- **dBpoweramp:** <https://dbpoweramp.com/dmc> · <https://www.dbpoweramp.com/cd-ripper> · <https://dbpoweramp.com/developer-scripting-dmc>
- **EZ CD Audio Converter:** <https://www.poikosoft.com/> · Microsoft Store listing
- **Exact Audio Copy:** <https://www.exactaudiocopy.de/accurate-rip/> · FAQ
- **fre:ac:** <https://www.freac.org/> · <https://github.com/enzo1982/freac>
- **XLD:** <https://tmkk.undo.jp/xld/index_e.html>
- **iZotope RX 12:** <https://www.izotope.com/products/rx-advanced>
- **Adobe Audition:** <https://www.adobe.com/products/audition.html>
- **Audacity:** <https://manual.audacityteam.org/man/index_of_effects_generators_and_analyzers.html>
- **Acon Acoustica 8:** <https://acondigital.com/products/acoustica>
- **Steinberg SpectraLayers 12:** <https://download.steinberg.net/downloads_software/SpectraLayers_12/help/Pro/_spectralayers_12.html>
- **Mixed In Key:** <https://mixedinkey.com/features/> · <https://mixedinkey.com/learn-more/>
- **rekordbox:** <https://rekordbox.com/en/plan/>
- **Demucs:** <https://github.com/facebookresearch/demucs> · **ffmpeg-normalize:** <https://github.com/slhck/ffmpeg-normalize> · **loudgain:** <https://github.com/Moonbase59/loudgain>

Vendor feature lists are marketing material; version scope is noted where it matters
(e.g. Picard 2.13, RX 12, SpectraLayers 12).

### 8.2 Where AudioSuite-Pro is genuinely competitive

| Dimension | AudioSuite-Pro | Market context |
|---|---|---|
| **Breadth in one process** | 30 tools: analysis, tagging, art, lyrics, fingerprinting, conversion, ripping, repair, library stats | No single competitor covers all of these. dBpoweramp/EZ CD are converter/ripper-centric; Mp3tag/Picard/beets are taggers; RX is restoration. |
| **Batch orchestration** | Master Driver dependency graph, per-step retries, notes/verdict, GUI+CLI handshake | Most competitors offer batch conversion or action groups, not a multi-tool dependency-aware run. |
| **Undo** | SQLite undo of tags, overwrites, deletes, reorg moves | Rare in this class; Mp3tag/Picard/beets rely on backups or re-import. |
| **CD integrity** | AccurateRip v1/v2, disc IDs, offset detection, CUE generate/split | Matches EAC/dBpoweramp at the algorithmic tier; stronger than most free tools. |
| **Conversion DSP** | SoXR resampling, TPDF dither, sample-rate/bit-depth controls, lossless gain for MP3 | In the same conversation as dBpoweramp/EZ CD for core quality; weaker on output-format completeness and shell integration. |
| **Loudness** | Two-pass `loudnorm` (TP −1.5), ReplayGain track/album tags | Feature-equivalent to ffmpeg-normalize/loudgain for the core task; behind on watch folders, configurable ceilings and reports. |
| **Analysis** | BPM (with onset-periodicity evidence), key (with confidence, unknown refusal), mood/energy, spectral viewer, library trends | Mixed In Key/rekordbox are DJ-workflow leaders; AudioSuite's analysis is credible for tagging and library insight, not certified for DJ use. |
| **Extensibility** | Four hosted plugin surfaces, manifest validation, per-plugin enablement | beets has a richer plugin ecosystem; AudioSuite's is newer but better governed and integrated with a GUI. |
| **Engineering rigor** | 10,915 tests, 90.5 %, strict mypy, Bandit 0/0, docs locks, decision records | No comparable open-source audio desktop suite publishes this level of verification. |

### 8.3 Where the suite is behind

| Area | Leaders | AudioSuite-Pro gap |
|---|---|---|
| **Tag editor depth** | Mp3tag: arbitrary frames/fields, action groups, regex, tag↔filename, templates, filters; Picard: full release metadata; beets: fromfilename, flexible fields | Tag Editor exposes 8 fields plus bulk set/case/swap; no arbitrary frame editor, no tag-from-filename, no reusable multi-step actions, no regex replace, no sort names/composer/conductor/disc subtitles. |
| **Metadata sources** | Mp3tag: Discogs/MusicBrainz/freedb; Picard: MusicBrainz + AcoustID + CAA; beets: Discogs/Deezer/Spotify/Tidal plugins | AcoustID/MusicBrainz + CAA/Fanart/Deezer/iTunes for art; no Discogs, no Spotify/Tidal, no freedb/gnudb tag lookup, no full release tracklist completion (track numbers/titles/dates/labels). |
| **Duplicate detection** | beets duplicates plugin; PerfectTUNES De-Dup; rekordbox duplicate merge | None. The fingerprinter identifies recordings but does not compare files or report duplicates. |
| **Automation** | beets CLI/plugins, Picard command processing, Mp3tag CLI/action groups, Kid3 QML/D-Bus, dBpoweramp CLI/COM | Strong CLI + JSON, but no watch folders, no user scripting/action DSL, no shell integration. Plugins require Python development. |
| **Playlists/exports** | Mp3tag HTML/RTF/CSV; TagScanner XML/CSV/Excel; beets M3U/JSON/CSV/XML; rekordbox XML | No M3U/CSV/HTML export or smart playlists; CUE generate/split is present, ASX import is present. |
| **Restoration depth** | RX: de-hum, de-click, de-clip, de-reverb, spectral repair, dialogue isolate, music rebalance; Acoustica: DeVerberate/DeClip/DeHum/DeNoise, Remix; SpectraLayers: many unmix/repair modules | Noise reduction, pop/click, silence trim, hum removal in Refinery, normalization, enhancement; no de-reverb, declip, spectral repair, dialogue isolation, spectral editing (viewer only). |
| **DJ workflow** | Mixed In Key: Camelot keys, energy, cue points, DJ exports; rekordbox: collection, playlists, cue/beat grid, XML | BPM/key/mood/energy tags, but no Camelot notation, no cue points, no rekordbox XML/M3U export, no independently verified key/BPM accuracy report. |
| **CD metadata** | dBpoweramp: PerfectMeta (AccurateRip Meta, GD3, Discogs, MusicBrainz, freedb); EAC: CD-Text/gnudb workflows | MusicBrainz only (plus AccurateRip checksums); no CD-Text/gnudb fallback, no image+cue ripping workflow parity (CUE tools exist separately). |
| **Format output** | dBpoweramp/EZ CD: DSD, APE/MPC decode, broad containers, shell integration | APE/MPC/DSD are deliberately read-only (FFmpeg has no encoders); **ALAC output is broken**; no shell integration; no watch folders; no audio-CRC verification outside the ripper. |
| **Platform reach** | fre:ac (Win/mac/Linux/BSD), XLD (macOS), Mp3tag (Win/mac), Picard/beets (all) | Windows-first; portable core claimed but not CI-tested; installer is Windows-only. |
| **True-peak workflow** | LUFSNormalizer: configurable ceiling, needs-limiting reports, watch folders; RX Loudness Control | Hardcoded −1.5 dBTP, no user ceiling, no post-limit verification report. |
| **Lyrics** | Picard/beets lyrics plugins, dedicated lyric apps, Genius/Musixmatch ecosystems | LRCLIB + local `.lrc` sidecar only; no Genius/Musixmatch/lyrics.ovh. |

### 8.4 Feature matrix (condensed)

Legend: **Yes** = implemented and exercised; **Partial** = exists with a meaningful
limitation; **No** = absent.

| Capability | AudioSuite-Pro | Best-in-class reference |
|---|---|---|
| Batch tag edit | **Yes** (8 fields + bulk) | Mp3tag, Picard, Kid3 |
| Arbitrary frames/fields | **No** | Mp3tag, Kid3 |
| Tag from filename | **No** | Mp3tag, Picard, beets, Kid3 |
| Filename from tags | **Yes** | Mp3tag, beets, file_reorganizer |
| Reusable action groups/regex | **Partial** (fixed TXXX rules, case/swap) | Mp3tag action groups |
| MusicBrainz/AcoustID identity | **Yes** | Picard, beets |
| Album-level matching | **Partial** (AcoustID cluster consensus; no tracklist completion) | Picard |
| Artwork multi-source | **Yes** | Picard, Mp3tag, dBpoweramp |
| Lyrics | **Partial** (LRCLIB/sidecar) | Picard/beets plugins |
| Duplicate detection | **No** | beets, PerfectTUNES |
| Playlist/M3U/CSV export | **No** (CUE/ASX only) | Mp3tag, beets, TagScanner |
| Watch folders | **No** | LUFSNormalizer, some converters |
| CLI automation | **Yes** (+ JSON schema) | beets, dBpoweramp |
| Plugin/scripting | **Partial** (Python plugins) | beets |
| Conversion breadth | **Yes** (ALAC broken) | dBpoweramp, EZ CD, fre:ac |
| SoXR/dither | **Yes** | dBpoweramp, EZ CD |
| CD AccurateRip/offset | **Yes** | EAC, dBpoweramp, XLD |
| CD metadata breadth | **Partial** (MusicBrainz) | dBpoweramp PerfectMeta |
| CUE parse/generate/split | **Yes** | EAC, XLD, fre:ac |
| Loudness normalization | **Yes** (fixed TP) | RX, Acoustica, ffmpeg-normalize |
| ReplayGain | **Yes** (album math flawed) | loudgain |
| De-hum | **Yes** (Refinery) | RX, Acoustica, Audition |
| De-click/de-clip | **Partial** (declick; no declip) | RX, Acoustica, Audition |
| De-reverb | **No** | RX, Acoustica, SpectraLayers |
| Spectral repair/edit | **No** (viewer only) | RX, SpectraLayers, Audition |
| Dialogue isolation | **No** | RX |
| Stem separation | **Yes** (optional Demucs) | RX Music Rebalance, SpectraLayers Unmix |
| BPM/key/mood/energy | **Yes** | Mixed In Key, rekordbox (DJ workflow) |
| Camelot/DJ export/cues | **No** | Mixed In Key, rekordbox |
| Library analytics | **Yes** (distinctive) | foobar2000, beets (less visual) |
| Undo | **Yes** (distinctive) | rare |
| Cross-platform runtime | **Partial** (Windows-first, unverified POSIX) | fre:ac, Picard, beets |

### 8.5 Positioning

AudioSuite is best understood as an **integrated batch enrichment and repair workbench**
for a Windows music library, not as a replacement for Mp3tag/Picard (tagging depth), RX
(restoration depth), or Mixed In Key/rekordbox (DJ workflow). Its defensible advantages
are breadth, batch orchestration, undo, analysis, and engineering quality. The most
valuable feature work is therefore not "more DSP modules" but the workflow gaps that
make the existing breadth usable at library scale: tag automation, duplicate finding,
watch folders, export, and a small set of workflow-parity items (Camelot/M3U, lyrics
providers, true-peak ceiling).

---

## 9. Plan-ready findings register

Severity: **P0** release-blocking (audio/security), **P1** next sprint, **P2** next
quarter, **P3** opportunistic. Effort is rough engineering time (S ≤ 1 day, M 2–4 days,
L 1–2 weeks, XL multi-sprint).

### 9.1 Defects/remediation

| ID | Sev | Finding | Fix shape | Effort | Acceptance evidence |
|---|---|---|---|---|---|
| R-01 | P0 | ReplayGain album gain = mean of track LUFS | energy/duration-weighted album loudness, or one-pass album measure | M | concatenated-audio `ebur128` comparison within ±0.2 dB |
| R-02 | P0 | ALAC output always fails | write ALAC into `.m4a`, or remove the option | S | real WAV→ALAC, ffprobe `codec_name=alac`, decoded RMS match |
| R-03 | P0 | Organizer `..` traversal | reject `..`, resolve and contain under base dir | S–M | traversal-tag test creates nothing outside; dry/live both skip |
| R-04 | P1 | GUI/CLI read two art config files | one canonical `config_path()`, migrate legacy, test both | S | both loaders resolve the same path/key |
| R-05 | P1 | Scrubber advertises unloadable formats | derive discovery from loader/`TagHandlerFactory` | S | every advertised extension loads a real fixture; `.wv` not an error |
| R-06 | P1 | CLI exit 0 on batch errors | nonzero exit when errors > 0, documented | S | `CliRunner` failing-file test; JSON unchanged |
| R-07 | P1 | APEv2 writes untested | mirror handler suite on `.wv/.ape/.mpc` fixtures | M | BPM/key/genre/mood/art/delete read-back through fresh handlers |
| R-08 | P1 | Raw subprocess in enhancer/CD UI | route through secure wrapper/fixed argv | S | policy test; Bandit still 0/0; eject/Explorer still work |
| R-09 | P1 | Dry run uses a different DSP chain | same chain, skip only writes (or label/limit preview) | S | dry vs live measured arrays identical |
| R-10 | P1 | Failed deps still satisfy graph | separate succeeded/finished, skip dependants | S | failing-bpm batch does not run tempo |
| R-11 | P2 | Dependency audit non-blocking | make blocking with dated allowlist | S | CI failure on a new advisory |
| R-12 | P2 | POSIX untested | Ubuntu smoke job or narrow claim | M | green Ubuntu CLI/shared smoke run |
| R-13 | P3 | Cache key path+mtime | add size/mtime_ns or invalidate on writes | S | changed-size same-mtime test refreshes |
| R-14 | P3 | Non-ASCII console output | ASCII status markers for CLI/logs | S | cp1252-encodable CLI output test |
| R-15 | P2 | Ruff/mypy targets below floor | py311 target, mypy 3.11 or matrix | S | 3.11 typecheck leg green |
| R-16 | P3 | README count stale | generate count from registry | S | README assertion matches `len(first_party())` |

### 9.2 Maintainability/quality

| ID | Sev | Finding | First step | Effort |
|---|---|---|---|---|
| Q-01 | P2 | 23 apps duplicate GUI scaffolding | extend `tool_app_base` family by family | L |
| Q-02 | P2 | 8 `process_*` tag functions duplicate logic | mapping engine over `TagHandler` | L |
| Q-03 | P2 | Tag-helper import cycle | leaf protocol + factory module; fresh-import test | M |
| Q-04 | P2 | 181 broad excepts, unlinted | enable BLE001 with justified noqa; fix top offenders | M |
| Q-05 | P3 | 1,098 `Any`, mixed `Optional`/`os.path` | Protocols/TypedDict and pathlib for touched modules | L (incremental) |
| Q-06 | P3 | 123 functions >100 lines | split high-CC functions when touched | L |
| Q-07 | P3 | Changelog-in-docstrings/plan IDs | style rule for new code; clean on touch | S |
| Q-08 | P3 | Minimal packaging metadata/no `py.typed` | PEP 621 metadata; add `py.typed` if public | S |
| Q-09 | P3 | 20-minute suite, no fast profile | add `smoke` marker / documented `--no-cov` subset | M |
| Q-10 | P3 | Thin architecture docs | one architecture page from §2 | S |

### 9.3 Feature backlog (market parity)

| ID | Feature | Why it matters | Reference | Effort |
|---|---|---|---|---|
| F-01 | Tag-from-filename + action groups/regex | The single biggest tagging-workflow gap; unlocks library-wide cleanup without CSV | Mp3tag action groups, beets `fromfilename`, Picard scripts | L |
| F-02 | Duplicate detection/merge | Library hygiene; fingerprinting already provides the identifier | beets `duplicates`, PerfectTUNES De-Dup | M |
| F-03 | Watch folders / headless daemon | Turns the CLI into an ingest pipeline; competitors and LUFSNormalizer have it | LUFSNormalizer, beets | M |
| F-04 | Extended tag fields/arbitrary frames | Album artist sort, composer, conductor, disc subtitle, ISRC, BPM/key in the editor | Mp3tag, Kid3 | M |
| F-05 | Playlist/M3U + CSV/HTML export | Users cannot move a curated selection into players/DJ tools | Mp3tag, beets, TagScanner | S |
| F-06 | Camelot notation + DJ exports (M3U/rekordbox XML) | Makes key/BPM analysis usable in DJ workflows | Mixed In Key, rekordbox | S–M |
| F-07 | More lyric providers (Genius/lyrics.ovh) behind the existing registry | LRCLIB alone leaves gaps; the provider seam is already clean | Picard/beets plugins | S |
| F-08 | De-reverb, declip, spectral repair, dialogue isolation | Closes the restoration gap to RX/Acoustica/SpectraLayers | RX, Acoustica, SpectraLayers | XL |
| F-09 | Configurable true-peak ceiling + limiting report | Current −1.5 dBTP is fixed; delivery workflows need a choice | LUFSNormalizer, RX | S |
| F-10 | CD metadata breadth (gnudb/CD-Text) | MusicBrainz-only misses niche/classical discs | dBpoweramp PerfectMeta, EAC | M |
| F-11 | Full release/tracklist completion | Album clustering exists; filling missing tracks/numbers/dates is the Picard difference | Picard | L |
| F-12 | POSIX packaging/runtime | Makes the "portable core" claim real | fre:ac, Picard | L |

### 9.4 Suggested sequencing

**Sprint A — correctness and containment (1 week).**
R-01, R-02, R-03 are the P0 set; do not ship the release until they are closed
(audio/security rule). R-04 and R-05 ride in the same sprint because each is a one-day
fix with a tool-wide blast radius. Add the regression test named by each finding and
re-run the full gate.

**Sprint B — automation and test truth (1–2 weeks).**
R-06, R-07, R-08, R-09, R-10, R-11, R-15. Add the fresh-import test (Q-03) while the
tag layer is in scope. This sprint makes failures visible: exit codes, failing
dependants, APEv2 coverage, dependency advisories.

**Sprint C — maintainability and workflow parity (2–3 weeks).**
Q-01/Q-02 in one tool family, then F-01, F-05, F-06, F-07, F-09. These are the
highest value-per-effort market gaps; they reuse the existing tag/AI/analysis seams.

**Later.** F-02/F-03 (library-scale automation), F-04/F-10 (metadata depth), F-08 (RX
class, separate roadmap), F-11/F-12 (platform and release parity).

---

## 10. What a new maintainer will struggle with

1. **Breadth.** 108 kLOC, 30 tools, 20 plan files and prior audits (17.5 kLOC), and comments
   keyed to plan IDs (`D112`, `P6`). The decision record is a strength, but onboarding
   requires learning the ID vocabulary. A one-page "how a run flows" architecture note
   would pay for itself.
2. **Duplication at the edges.** Changing a preset handler, progress callback or tag
   field can require edits in 8–22 files; the shared scaffolds exist but are not used
   widely enough.
3. **Two tag layers and two config files.** A new format or field must be considered in
   both `tag_helper` and `tag_field_updater`; a new album-art setting must be considered
   in both config paths. These are the two most likely places for a future "works in the
   GUI, not the CLI" bug.
4. **A 20-minute full suite.** It is thorough, but the feedback loop is long; a fast
   smoke profile would improve iteration without weakening the gate.
5. **Strict/lint settings that do not match the floor.** Ruff says 3.10, mypy says 3.12,
   CI tests 3.11/3.12/3.14. A contributor cannot tell which version is authoritative.

---

## 11. Appendix A — measured metrics

| Metric | Value |
|---|---:|
| Production `.py` files | 550 |
| Production physical lines | 107,910 |
| Production code lines (excl. blank/comment) | 88,345 |
| Production comment lines | 3,783 (4.1 %) |
| Test files / lines | 379 / 150,009 |
| Production functions and methods / classes | 3,049 / 363 |
| Functions >100 lines | 123 |
| Functions >200 lines | 8 |
| Functions with CC ≥ 20 | 31 (of 3,049) |
| Dataclass mentions | 311 |
| `Any` occurrences (production) | 1,098 |
| `Optional[...]` (production) | 135 |
| `os.path.` (production) | 375 |
| `except Exception` (production) | 181 |
| `# type: ignore` (production) | 34 |
| `# noqa` (production) | 69 |
| Functions without a return annotation | 0 (of 3,049; `__init__` excluded) |
| Lazy (`%`-style) logger calls | 506 / 537 |
| f-string logger calls | 1 |
| Raises inside `except` without `from` | 1 (of 453 raises) |
| Dataclasses / frozen dataclasses | 158 / 109 |
| Modules with a module docstring | 543 / 551 |
| Google-style `Args:` sections | 844 |
| Modules declaring `__all__` | 54 |
| `global` statements (production) | 26 |
| `open()` inside `with` | 63 / 65 |
| `print()` calls (production) | 167 (159 of them under `utilities/`) |
| Enums / `str`-mixin enums | 13 / 6 |
| "Changed in …" (production) | 437 |
| Non-ASCII files | 357 / 550 |
| Tools / driver manifests | 30 / 31 |
| Test cases / coverage | 10,915 / 90.50 % |
| Test runtime | 1,179.62 s |
| Ruff / format | clean / 930 formatted |
| mypy | clean / 549 files |
| Bandit | 0 High, 0 Medium, 47 Low |

## 12. Appendix B — high-risk files inspected

`audio_suite_shared/file_processor_base.py`, `tag_helper_base.py`,
`tag_helper_apev2.py`, `tag_helper_vorbis.py`, `tag_helper_writer.py`,
`tag_helper_art.py`, `batch_undo.py`, `suite_config.py`, `logging_setup.py`,
`secure_subprocess.py`, `security/key_manager.py`, `analysis_loader.py`,
`audio_formats.py`, `exceptions.py`, `tool_app_base.py`, `tool_plugin.py`,
`music_format_converter/core/{formats,file_processor,ffmpeg_params}.py`,
`replaygain_analyzer/core/{gain_calculator,tag_writer,ffmpeg_metrics,file_processor}.py`,
`metadata_scrubber/core/scrubber.py`,
`file_reorganizer/core/{pattern,engine}.py`,
`audio_enhancer/core/{ffmpeg_io,processor,file_processor}.py`,
`master_driver/{batch_orchestrator.py,runner/arg_builder.py,state/app_state.py}`,
`album_art_sync/{app.py,config/settings.py,core/pipeline.py,api/*.py}`,
`library_stats/{app.py,library_cache.py}`, `cd_ripper/core/{accuraterip,disc,metadata_resolver}.py`,
`audio_fingerprinter/core/{album_cluster,acoustid_client,musicbrainz_client}.py`,
`key_detector/core/key_engine.py`, `bpm_analyzer/core/bpm_detector.py`,
`tag_editor/core/processor.py`, `tag_field_updater/core/{processor,transformation_rules}.py`,
`audio_refinery/core/{pipeline,measure}.py`, `lyrics_manager/core/providers/*`,
`audio_suite_shared/plugin_system/*`, `pyproject.toml`, `.github/workflows/ci.yml`.

## 13. Appendix C — gate command transcript (abridged)

```
$ python -m compileall -q -f .
# exit 0; only third-party SyntaxWarnings from .venv (pydub, sympy), documented

$ ruff check .
All checks passed!

$ ruff format --check .
930 files already formatted

$ python -m mypy .
Success: no issues found in 549 source files

$ bandit -r . -x ./.venv -c pyproject.toml
Total lines of code: 88732
  High: 0   Medium: 0   Low: 47

$ pytest
10915 passed, 3 skipped, 35 deselected, 1362 warnings in 1179.62s (0:19:39)
TOTAL 35954 3417 90%
Required test coverage of 75.0% reached. Total coverage: 90.50%
```

**Audit artefacts.** Scratch probes (`repro_*`, coverage/parse scripts, generated ALAC
and FLAC fixtures) were deleted after use, per the repository's bug-hunt discipline.
The only new file is this report.
