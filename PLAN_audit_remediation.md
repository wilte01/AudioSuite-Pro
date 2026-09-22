# Audit Remediation Plan — AudioSuite-Pro

**Source:** Unbiased Audit (2026-09-10)
**Status:** Active — Sprint 4 phases 3.4, 3.5, 4.1, 4.2 complete
**Last Updated:** 2026-09-17

This plan translates audit findings into a series of small, self-contained
projects. Each phase is independent enough to ship on its own, but ordered
so that foundational work lands first. Revisit this document after each
phase to update status and adjust priorities based on what was learned.

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

## Tier 1 — Foundation & Code Health

These phases fix structural issues that other work depends on. They carry
no new user-facing features but reduce friction for everything that follows.

### 1.1 Named Constants Extraction

**Priority:** High | **Effort:** Small (1–2 days) | **Risk:** Low

**Problem:** Magic numbers scattered across worker code — timeouts, worker
counts, quality settings, history limits, window geometry strings.

**Scope:**

- [x] Audit all `timeout=` literals in `file_processor_base.py` (300, 600)
      and extract to `WORKER_TIMEOUT_SECS` / `CPU_WORKER_TIMEOUT_SECS`
- [x] Audit all `ThreadPoolExecutor(max_workers=N)` calls — extract
      `DEFAULT_MAX_WORKERS = 4` to `audio_suite_shared/constants.py` or
      `file_processor_base.py`
- [x] Extract JPEG quality `92` in `art_processor.py` to
      `JPEG_QUALITY = 92`
- [x] Extract history limit `10` in `suite_config.py:321` to
      `MAX_DURATION_HISTORY = 10`
- [x] Extract `"Various Artists"` / `"Various"` comparison in
      `file_reorganizer/core/engine.py:217` to a module constant
- [x] Extract repeated window geometry `"800x600+100+100"` to a shared
      constant in `audio_suite_shared/ui_common.py` or `styles.py`

**Deliverables:**
- New file `audio_suite_shared/constants.py` (if shared) or module-level
  constants in each affected file
- All existing tests pass unchanged

**Success criteria:**
- `grep -rn '[0-9]\{3,\}' --include='*.py' audio_suite_shared/ file_reorganizer/ library_stats/ metadata_scrubber/ art_processor.py` returns no bare numeric literals used as business-logic thresholds
- Ruff, mypy, pytest all green

---

### 1.2 Dead Code & Stray Print Cleanup

**Priority:** Medium | **Effort:** Small (0.5–1 day) | **Risk:** Very low

**Problem:** One dead `threading.Lock()` statement, two stray `print()`
calls in shared infrastructure, inconsistent logger naming.

**Scope:**

- [x] Remove dead `threading.Lock()` at `file_processor_base.py:515`
- [x] Replace `print()` in `audio_suite_shared/launcher.py:40` with
      `logger.error()`
- [ ] Replace `print()` in `audio_suite_shared/tool_plugin.py:15` with
      `logger.info()`  *(left unchanged — code is inside a docstring)*
- [x] Consolidate dual loggers (`_logger` / `_log`) in
      `audio_suite_shared/tag_helper_base.py:19-20` to a single
      `logger = logging.getLogger(__name__)`
- [x] Remove `time.sleep(0.05)` hack in
      `metadata_scrubber/core/scrubber.py:268` or replace with a
      documented rationale comment if it must stay

**Deliverables:**
- 5 small, focused edits
- No behavioural change — pure cleanup

**Success criteria:**
- `grep -rn 'print(' audio_suite_shared/ --include='*.py'` returns zero
  matches outside `cli_app.py` (which routes to Click)
- `grep -rn 'threading.Lock()' audio_suite_shared/file_processor_base.py`
  returns zero matches
- All existing tests pass

---

### 1.3 Tighten Broad Exception Catches

**Priority:** Medium | **Effort:** Small (1 day) | **Risk:** Low

**Problem:** Five `except Exception: pass` or debug-only blocks in
`library_stats/core/file_processor.py`, plus overly broad catches in
`album_art_sync/ui/picker_dialog.py` and
`utilities/resize_music_recursive.py`.

**Scope:**

- [x] In `library_stats/core/file_processor.py` — narrow the 5 broad
      catches (lines 277, 280, 394, 411, 661) to specific exceptions
      (`MutagenError`, `OSError`, `ValueError` as appropriate) and ensure
      all carry `exc_info=True` on the debug log
- [ ] In `album_art_sync/ui/picker_dialog.py:95` — narrow
      `except Exception` to `requests.RequestException` for HTTP calls
      *(left unchanged — broad catch retained as safety net after specific
      catches)*
- [x] In `utilities/resize_music_recursive.py:104,130` — narrow to
      `OSError` for file I/O operations

**Deliverables:**
- 7 targeted exception-type narrowing edits
- Each catch justified by the actual failure modes at that call site

**Success criteria:**
- No `except Exception: pass` or `except Exception as e:` followed by
  bare `pass` in first-party code (`.venv` excluded)
- `bandit` scan unchanged (no new findings)

---

### 1.4 Type Annotation Hardening

**Priority:** Medium | **Effort:** Medium (2–3 days) | **Risk:** Low

**Problem:** mypy relaxations (`disallow_incomplete_defs = false`,
`check_untyped_defs = false`) allow partially-typed functions. Duck-typed
`object` parameters in `suite_config.py` defeat static analysis. Heavy
`Any` usage in mutagen-adjacent code.

**Scope:**

- [x] Re-enable `disallow_incomplete_defs = true` in `pyproject.toml`
      and fix any resulting mypy errors across the codebase
- [x] Re-enable `check_untyped_defs = true` and fix resulting errors
- [x] Replace `state: object` in `suite_config.py:load_app_state` /
      `save_app_state` with a `Protocol` or `TypedDict` defining the
      expected attributes
- [x] Create a `MutagenAudio = Union[MP3, FLAC, OGGVorbis, ...]` type
      alias in `audio_suite_shared/tag_helper_base.py` and replace bare
      `Any` in tag reader/writer code
- [x] Ensure `optional` vs `| None` style is consistent — prefer `| None`
      (modern syntax) throughout

**Deliverables:**
- Updated `pyproject.toml` with stricter mypy settings
- Type alias file or alias in `tag_helper_base.py`
- All mypy `--strict` errors resolved

**Success criteria:**
- `mypy . --strict` passes with zero errors
- `disallow_incomplete_defs = true` and `check_untyped_defs = true` in
  `pyproject.toml`

---

## Tier 2 — Structural Refactoring

These phases address code duplication and architectural inconsistencies.
They make future feature work faster and less error-prone.

### 2.1 Library Stats Deduplication

**Priority:** High | **Effort:** Medium (3–4 days) | **Risk:** Medium

**Problem:** `library_stats/core/file_processor.py` has ~80% duplicated
logic between `_scan_directory_full` and `_scan_directory_cached`, and
year-extraction logic is copy-pasted 3× across the file.

**Scope:**

- [x] Extract year-extraction logic into a private helper:
      `_extract_year_from_tags(tags: dict) -> str | None`
      *(implemented as `_extract_year_from_tags(raw_tags: Any) -> int | None`
      — see Decision Log)*
- [x] Refactor `_scan_directory_full` and `_scan_directory_cached` into a
      shared `_scan_directory(..., use_cache: bool)` method or a template
      method with a cache strategy injection
      *(implemented as template method: shared `_read_file_tags` +
      `_populate_report`; see Decision Log)*
- [x] Verify `export_csv` reuses the same year-extraction helper
- [x] Add targeted unit tests for the extracted helpers

**Deliverables:**
- Refactored `file_processor.py` (~80% less duplicated logic)
- New unit tests for extracted helpers
- No behavioural change

**Success criteria:**
- `wc -l library_stats/core/file_processor.py` shows significant line
  reduction *(scanner bodies shrink 152→110 and 108→67; total file grew
  723→766 because the shared helpers now live in-tree — see Decision Log)*
- All existing `library_stats` tests pass
- New tests cover the extracted year-extraction and scan helpers
- `grep -c 'def _extract_year' library_stats/core/file_processor.py`
  returns exactly 1 ✓

---

### 2.2 Consistent BaseSuiteApp Adoption

**Priority:** Medium | **Effort:** Small–Medium (2 days) | **Risk:** Low

**Problem:** Some tools extend `BaseSuiteApp` and use
`bootstrap_tool_app()`; others duplicate theme/style/initialisation logic
inline.

**Scope:**

- [x] Inventory all `app.py` modules and classify:
      - Uses `BaseSuiteApp` / `bootstrap_tool_app` → already compliant
        (metadata_scrubber extends `BaseSuiteApp`; 20 tools call
        `bootstrap_tool_app()` including cd_ripper/asx_extractor with
        `apply_ttk_styles=False`)
      - Duplicates init logic → needs migration (`file_reorganizer`,
        `tag_field_updater`)
- [x] Migrate `album_art_normalizer/app.py` to extend `BaseSuiteApp`
      (was named in the plan despite using `bootstrap_tool_app`)
- [x] Migrate any other non-compliant `app.py` modules found
      (`file_reorganizer/app.py`, `tag_field_updater/ui/app.py`)
- [x] Verify each migrated tool's GUI still initialises correctly
      (manual smoke test or automated if fixtures exist)

**Compliance checklist (after phase 2.2):**

| Tool `app.py` | Pattern |
|---|---|
| `metadata_scrubber/app.py` | `BaseSuiteApp` |
| `album_art_normalizer/app.py` | `BaseSuiteApp` (migrated 2.2) |
| `file_reorganizer/app.py` | `BaseSuiteApp` (migrated 2.2) |
| `tag_field_updater/ui/app.py` | `BaseSuiteApp` (migrated 2.2) |
| 19 other tools (`album_art_sync`, `album_genre_tagger`, `asx_extractor`, `audio_enhancer`, `audio_normalizer`, `audio_refinery`, `bpm_analyzer`, `cd_ripper`, `genre_sync`, `key_detector`, `library_stats`, `mood_analysis_batch_tagger`, `mood_analyzer`, `music_format_converter`, `noise_reduction`, `pop_click_remover`, `replaygain_analyzer`, `silence_trimmer`, `tempo_analyzer`) | `bootstrap_tool_app()` (compliant) |
| `master_driver/app.py` | out of scope (excluded) |

**Deliverables:**
- Updated `app.py` for each migrated tool
- A checklist in this plan documenting which tools are now compliant

**Success criteria:**
- All tool `app.py` modules are classified and compliant (no tool
  duplicates `app_bootstrap` init logic; 4 tools now subclass
  `BaseSuiteApp`, 19 call `bootstrap_tool_app()`, master_driver excluded)
- `grep -rln 'BaseSuiteApp' */app.py` returns the migrated set —
  `metadata_scrubber`, `album_art_normalizer`, `file_reorganizer`
  (plus `tag_field_updater/ui/app.py` via recursive search). The
  `bootstrap_tool_app()` users remain compliant per the plan's own
  classification — see Decision Log
- No tool `app.py` manually calls `ttk.Style().theme_use()` or
  duplicates `app_bootstrap` init logic

---

### 2.3 Migrate file_reorganizer to Shared Config

**Priority:** Medium | **Effort:** Small (1–2 days) | **Risk:** Low

**Problem:** `file_reorganizer/app.py` uses a tool-local
`reorganizer_config.json` via `_save_settings` / `_load_settings` instead
of the shared `suite_config` pattern mandated by the project convention.

**Scope:**

- [x] Replace `_save_settings` / `_load_settings` with
      `suite_config.load_value()` / `suite_config.save_value()`
- [x] Add a one-time migration step that reads the old
      `reorganizer_config.json` and writes values into
      `audio_suite_config.json`, then deletes the old file
- [x] Update CLI args to read from shared config

**Deliverables:**
- Refactored `file_reorganizer/app.py` config read/write
- Migration utility for existing users' settings

**Success criteria:**
- `file_reorganizer_config.json` is no longer created or read
- All settings round-trip through `audio_suite_config.json`
- `file_reorganizer` tests pass
  - Suite: 129 tests pass (app 100, config 16, cli 5 — new test_cli.py)

---

### 2.4 BaseFileProcessor Test Coverage

**Priority:** High | **Effort:** Medium (2–3 days) | **Risk:** Low

**Problem:** `file_processor_base.py` is the most critical shared module —
every tool depends on it — yet it has zero direct test coverage. Bugs
here silently affect all tools.

**Scope:**

- [x] Create `audio_suite_shared/tests/test_file_processor_base.py` — 42
      tests, `run_parallel_processing()` (concurrency, slot throttling,
      error recovery, discovery-failure and no-files `on_error` routing),
      `run_cpu_bound_processing()`, `process_batch()`,
      `run_with_retry()` (success, flaky-success, exhaustion,
      non-retryable, config delegation)
- [x] Test `run_parallel_processing()` — verify concurrency, slot
      throttling, error recovery, progress callbacks
- [x] Test `run_cpu_bound_processing()` — verify process isolation,
      result handling, timeout behaviour
- [x] Test `process_batch()` — verify sequential and parallel modes
- [x] Test `_process_with_recovery()` — verify retry logic, backoff,
      exception propagation
- [x] Add `file_processor_base` to `pyproject.toml` testpaths if not
      already covered — already covered via `audio_suite_shared/tests`

**Deliverables:**
- New test file with ≥10 test cases covering core paths
- Integration with existing CI pipeline

**Success criteria:**
- `pytest audio_suite_shared/tests/test_file_processor_base.py -v` passes
  — 42 passed
- Coverage report shows `file_processor_base.py` at ≥80% — 100%
- No `# type: ignore` or `xfail` markers in the new tests

---

### 2.5 Metadata Scrubber Test Coverage

**Priority:** Medium | **Effort:** Small (1–2 days) | **Risk:** Low

**Problem:** `metadata_scrubber/core/scrubber.py` has complex tag
preservation logic but no dedicated test file.

**Scope:**

- [x] Create `metadata_scrubber/tests/test_scrubber.py` — 87 tests
- [x] Test `_collect_tags_to_preserve()` for MP3 (ID3), FLAC (Vorbis),
      and M4A (MP4 atoms) — direct unit tests: essentials with flags off,
      flagged/custom frames (TPE2/USLT/APIC/TXXX, lyrics/albumartist/
      picture/custom Vorbis, `\xa9lyr`/`covr`/freeform MP4 atoms), and
      skip-branches (unreadable frame/vorbis tag/MP4 atom, empty value,
      None atom)
- [x] Test `process_single_file()` end-to-end with real audio files
      (use pydub to generate test fixtures)
- [x] Test edge cases: file with no tags (`[NO TAGS]` path),
      file with only preserved tags, file where all tags are stripped
      (plus top-level error handler via slot set failure)

**Deliverables:**
- New test file with ≥8 test cases
- Audio fixture generation helper (pydub-based)

**Success criteria:**
- `pytest metadata_scrubber/tests/ -v` passes — 87 passed
- `scrubber.py` coverage ≥75% — 99% (only line 277 uncovered:
  dead defensive branch, real wipes return empty tags, never None)

---

## Tier 3 — Competitive Feature Gaps

These phases add capabilities where competitors outperform AudioSuite-Pro.
They are ordered by user impact and implementation complexity.

### 3.1 Sample Rate & Bit Depth Conversion

**Priority:** High | **Effort:** Medium (3–4 days) | **Risk:** Low

**Problem:** No user-facing sample rate conversion. WAV bit depth exists
in the format converter but is buried — there is no standalone tool or
obvious UI control for this.

**Scope:**

- [x] Add sample rate selection to `music_format_converter` (presets:
      44100, 48000, 88200, 96000, 176400, 192000, plus `source` passthrough)
- [x] Expose bit depth selection for WAV/AIFF output (already partially
      implemented in `ffmpeg_params.py`)
- [x] Add a `--sample-rate` and `--bit-depth` CLI flags
- [x] Verify FFmpeg `-ar` and `-sample_fmt` / `-acodec` parameters are
      passed correctly
- [x] Update user guide for the format converter

**Deliverables:**
- Updated `music_format_converter` UI with sample rate + bit depth controls
- CLI flags: `--sample-rate`, `--bit-depth`
- Updated user guide

**Success criteria:**
- Convert a 44100 Hz WAV → 48000 Hz FLAC and verify with `ffprobe`
- Convert a 24-bit WAV → 16-bit WAV and verify bit depth
- All format converter tests pass
- Ruff, mypy, bandit green

---

### 3.2 Audio Fingerprinting (AcoustID / Chromaprint)

**Priority:** High | **Effort:** Large (5–7 days) | **Risk:** Medium

**Problem:** No audio fingerprint identification. MusicBrainz Picard
owns this space alone. Fingerprinting enables unknown-track identification
and automatic metadata lookup — a major differentiator.

**Scope:**

- [x] Evaluate `pyacoustid` (Python bindings for Chromaprint) — decided
      against; use the fpcalc binary (via `secure_subprocess`) plus a self-
      contained `requests` AcoustID client instead
- [x] Create fingerprint generation wrapper (`audio_fingerprinter/core/
      fingerprinter.py`) and AcoustID lookup wrapper (`core/acoustid_client.py`)
- [x] Create new `audio_fingerprinter` tool:
      - Generate fingerprint from audio file via fpcalc
      - Query AcoustID API with fingerprint (rate-limited, min-score filter)
      - Return AcoustID recording ID + title/artist metadata
- [x] Integrate with existing tag writers: write AcoustID Fingerprint /
      AcoustID Id tags via `tag_helper_writer.write_acoustid` (auto-fill of
      other empty metadata tags deferred as out of scope)
- [x] Add rate limiting (1 request/s) and API key management (encrypted
      storage via `KeyManager`, `ACOUSTID_API_KEY` env override)
- [x] Add CLI command: `audiosuite fingerprint <folder>`
- [x] Update shared config for API key storage
- [x] Write user guide (generator + generated .docx)

**Dependencies:** AcoustID API key (free registration at
acoustid.org/web-service/)

**Deliverables:**
- `audio_fingerprinter/` package (core fingerprint + AcoustID modules, UI, CLI)
- New tool integrated into Master Driver and shared CLI (`audiosuite fingerprint`)
- CLI command
- Config schema update for API key (encrypted via `KeyManager`)
- User guide

**Success criteria:**
- Identify an unknown MP3 by fingerprint and return correct artist/title
- API key stored in config, not hardcoded
- All tests pass, bandit clean (no hardcoded secrets)

---

### 3.3 CUE Sheet Support

**Priority:** Medium | **Effort:** Medium (3–4 days) | **Risk:** Low

**Problem:** No CUE sheet parsing, generation, or track splitting. Essential
for classical music, mixtapes, and album ripping workflows.

**Scope:**

- [x] Create `audio_suite_shared/cue_parser.py`:
      - Parse standard CUE sheet format (PERFORMER, TITLE, FILE, TRACK,
        INDEX 01)
      - Handle REM comments, PREGAP, POSTGAP
- [x] Create `audio_suite_shared/cue_generator.py`:
      - Generate CUE sheet from a list of track metadata + timestamps
- [x] Integrate with CD Ripper:
      - Generate CUE sheet alongside ripped tracks
      - Option to rip from existing CUE sheet (split single-file image)
- [x] Add CLI commands: `audiosuite cue parse <file>`,
      `audiosuite cue generate <file>`, `audiosuite cue split <file>`
- [x] Write user guide

**Deliverables:**
- `cue_parser.py` and `cue_generator.py` modules
- CD Ripper CUE integration
- CLI commands
- User guide

**Success criteria:**
- Parse a CUE sheet and correctly identify all tracks with timestamps
- Generate a CUE sheet from ripped tracks that matches the audio
- Split a single-file FLAC using a CUE sheet into individual tracks
- All tests pass

---

### 3.4 Lossless MP3 Volume Adjustment (MP3Gain-style)

**Priority:** Medium | **Effort:** Medium (3–4 days) | **Risk:** Medium

**Problem:** `audio_normalizer` re-encodes audio for LUFS normalization.
No option for lossless MP3 volume adjustment via `global_gain` field
modification (like mp3gain/mp3rgain). This is a meaningful gap for users
who want to normalise MP3 collections without quality loss.

**Scope:**

- [x] Evaluate `mp3rgain` (Rust, cross-platform) as an external tool
      dependency — check if it can be bundled or called via subprocess
      (Decision: rejected — see Decision Log; pure-Python chosen)
- [x] Alternatively, evaluate a pure-Python implementation that reads
      and modifies the `global_gain` field in MP3 frame headers
- [x] Create `audio_suite_shared/lossless_gain.py`:
      - Interface to mp3rgain CLI (preferred) or native implementation
      - Support track gain and album gain modes
- [x] Add "Lossless Gain" option to `audio_normalizer` (alongside
      existing LUFS normalisation)
- [x] Add CLI flag: `audiosuite normalize --mode lossless` (implementation
      uses `lossless` rather than the plan's `lossless-gain` — see Decision Log)
- [x] Write user guide section comparing lossy (LUFS) vs lossless
      (MP3Gain) modes

**Dependencies:** mp3rgain binary availability on Windows; or significant
effort for pure-Python implementation (resolved: pure-Python path)

**Deliverables:**
- `lossless_gain.py` module
- Updated `audio_normalizer` UI with mode selector
- CLI flag
- User guide comparison section

**Success criteria:**
- Adjust MP3 volume without re-encoding (verify file size unchanged)
- ReplayGain tags written correctly
- Existing LUFS normalisation unaffected
- All normalizer tests pass

---

### 3.5 Synced Lyrics (LRC) Support

**Priority:** Low-Medium | **Effort:** Medium (3–4 days) | **Risk:** Low

**Problem:** No LRC reading, writing, or editing. `metadata_scrubber`
preserves existing lyrics but the suite cannot create or manage them.
Kid3 and Mp3tag offer this.

**Scope:**

- [x] Create `audio_suite_shared/lrc_handler.py`:
      - Parse LRC format (`[mm:ss.xx] line`)
      - Generate LRC from timestamped text
      - Validate timestamp ordering
- [x] Add LRC import/export to `tag_field_updater` or create new
      `lyrics_manager` tool *(chose the new `lyrics_manager` tool — see
      Decision Log; 2026-09-16 reworked from single-file import/export to a
      batch fetch-and-embed tool backed by a remote lyric source)*
- [x] Support embedding LRC into ID3 SYLT frames (MP3) and Vorbis
      LYRICS fields (FLAC/OGG)
- [x] Add CLI command: `audiosuite lyrics <directory>` — directory-scanning
      lyric fetch matched by artist/title tags (`--dry/--live`,
      `--json/--text`, `--provider`, `--request-timeout`,
      `--skip-existing`, `--plain-fallback`, `--parallel`, `--workers`)
- [x] Write user guide

**Deliverables:**
- `audio_suite_shared/lrc_handler.py` — LRC parse/generate/validate
- `audio_suite_shared` tag helpers — `write_synced_lyrics`
  /`read_synced_lyrics`/`read_lyrics_tags`/`write_plain_lyrics`
  (ID3 SYLT/USLT frames; Vorbis `SYNCEDLYRICS`/`LYRICS` comments;
  M4A `\xa9lyr` plain atom)
- `lyrics_manager` tool — GUI (three-tab `Lyrics_Manager.pyw` + Master Driver
  ENRICH card) and CLI (`lyrics`)
  - `core/providers/` — modular provider registry (ABC + `lrclib` + DI)
  - `core/file_processor.py` — directory scan, provider fetch, tag write,
    parallel workers (`slot_vars`/`slot_queue`)
- User guide (.docx) + `CLI_Commands_Reference.md` section

**Success criteria:**
- Directory scan fetches synced lyrics by artist/title and embeds them
  *(verified: FLAC/OGG `SYNCEDLYRICS` verbatim round-trip and MP3 ID3 SYLT
  round-trip)*
- Unsynced route falls back to embeds `USLT`/`LYRICS`/`\xa9lyr` per format
  *(verified in `test_synced_lyrics.py::TestPlainLyricsRoundTrip`)*
- Unknown-tagged files, no-match files, and transport failures are counted
  as skipped/errors without aborting the run *(verified)*
- `--dry` reports intent and writes nothing *(verified)*
- GUI, CLI, and shared facades share one tag path *(verified)*
- All tests pass *(full suite verified in phase gate)*

---

## Tier 4 — Polish & Consistency

These are lower-priority improvements that round out quality and
consistency. Schedule between feature phases or as "breather" work.

### 4.1 Tool-Local to Shared Config Migration Audit

**Priority:** Low | **Effort:** Small (1 day) | **Risk:** Low

**Problem:** `file_reorganizer` is the known violator, but other tools
may have drifted.

**Scope:**

- [x] `grep -rln 'config\.json' --include='*.py' .` to find all
      tool-local config file references
- [x] Classify each: legitimate exception (API keys, complex nested
      settings) vs should-migrate
- [x] Create migration tickets for any additional violators
      *(see audit report below — one violator migrated in place, no tickets)*

**Audit report (2026-09-17):**

Audited every tool-local JSON config file against AGENTS.md "Shared Config
Pattern" (simple key-value prefs MUST live in `audio_suite_config.json`;
tool-local files allowed only for the documented exceptions).

| File | Classification | Action |
|---|---|---|
| `album_art_sync/album_art_config.json` | Legitimate exception — API keys/secrets | None |
| `album_art_sync/core/album_art_config.json` | Legitimate exception — API key template | None |
| `audio_refinery/refinery_settings.json` | Legitimate exception — complex nested pipeline settings | None |
| `metadata_scrubber/tag_prefs.json` | Legitimate exception — structured domain list (`kept_tags`) | None |
| `tempo_analyzer/tempo_config.json` | **Violator** — stale leftover; `tempo_analyzer/utils/config.py` already delegates entirely to `suite_config` (its `config_path` param is accepted and ignored) | Deleted (dead file) |
| `cd_ripper/cd_ripper_prefs.json` | **Violator** — single flat key `output_dir` | Migrated to `suite_config` (Phase 4.1 migration below) |

`file_reorganizer/reorganizer_config.json` confirmed already migrated and
physically deleted in Phase 2.3 (Test-Path = False at audit time).

**Deliverables:**
- Audit report (see above)
- Migration for `cd_ripper` (the only live violator); stale
  `tempo_analyzer` file deleted

**Success criteria:**
- Every tool-local config is either justified in `AGENTS.md` exceptions
  or has a migration ticket
  *(satisfied: all tool-local files are flagged as exceptions or were
  migrated/deleted — audit table above)*

---

### 4.2 Lazy Import Elimination in Hot Paths

**Priority:** Low | **Effort:** Small (0.5 day) | **Risk:** Very low

**Problem:** `tag_helper_reader` functions imported inside loop bodies in
`library_stats/core/file_processor.py` — repeated function-local imports
on every iteration add overhead.

**Scope:**

- [x] Move `from audio_suite_shared.tag_helper_reader import ...` to
      module-level in `library_stats/core/file_processor.py`
- [x] Verify no circular import issues arise
- [x] Remove `# noqa: PLC0415` markers that become unnecessary
      *(none existed in the file — see Decision Log)*

**Deliverables:**
- Module-level imports in `library_stats/core/file_processor.py`

**Success criteria:**
- `grep -n 'def import\|from.*import.*# noqa: PLC0415' library_stats/core/file_processor.py`
  returns no matches in hot-path functions ✓
- All library_stats tests pass — 142 passed

---

### 4.3 Line Length Policy Re-evaluation `[x]` COMPLETE

**Priority:** Low | **Effort:** Very small (0.5 day) | **Risk:** Low

**Problem:** E501 is suppressed in Ruff config, meaning lines can be
arbitrarily long. Several files have lines exceeding 100 chars.

**Decision Log:**
- E501 enforced at **88 chars (strict PEP 8)** to match the 88-char mandate
  in the global AGENTS.md. Relaxed (100/120) rejected as inconsistent with
  the standing policy.
- `user_guides/` IS in ruff scope — CI runs `ruff check .` repo-wide with no
  per-file excludes, so the generated guide sources had to be wrapped too.
- Ruff E501 has no usable autofix (even `--fix --unsafe-fixes` leaves all
  long lines standing), so all wraps were manual. Fixes preserve
  byte-identical string values / semantics via implicit adjacent-literal
  concatenation inside parens and comment/docstring reflows — no `# noqa`.
- 863 E501 findings fixed (716 user-guide generators + 146 package modules +
  1 stray dead file `mood_analysis_batch_tagger/_/_init/_/_.py`, a
  217-byte duplicate of `__init__.py` that is imported nowhere).
- E501 escape nuance: ruff measures continuation lines containing `\uXXXX`
  escapes by decoded display width in some contexts — verified the
  `album_art_normalizer.py` separator is exactly 51 escapes to stay
  byte-identical.

**Scope:**

- [x] Decide: re-enable E501 at 88 chars (strict PEP 8), 100 chars
      (relaxed), or 120 chars (modern projects)? → **88 (strict PEP 8)**
- [x] Apply the chosen limit to `pyproject.toml`
      (`line-length = 88`, `[tool.ruff.lint] ignore = []`, `target-version
      = py310`, `format.quote-style = "double"`)
- [x] Run `ruff format .` to auto-wrap affected lines
      *(no auto-fix exists for E501 — manual wraps required)*
- [x] Review auto-formatted output for readability regressions

**Deliverables:**
- Updated `pyproject.toml` with explicit E501 rule
- Formatted codebase (0 E501 across all 711 files)

**Success criteria:**
- `ruff check .` passes with the new line length rule ✓
  ("All checks passed!")
- No lines exceed the chosen limit in first-party code ✓
- `ruff format --check .` → "711 files already formatted" ✓
- `python -m compileall -q -f .` → exit 0 ✓
- `mypy . --strict` → no issues in 430 source files ✓
- `bandit -r audio_suite_shared -c pyproject.toml` → 0 High / 0 Medium
  (13 Low), documented subprocess wrappers ✓
- Full-suite `pytest` → **6320 passed, 5 skipped, coverage 77.21%** ✓

---

### 4.4 Documentation Sync Pass `[x]` COMPLETE

**Priority:** Low | **Effort:** Small (1 day) | **Risk:** Very low

**Problem:** After all the above changes, user guides and AGENTS.md may
be stale.

**Decision Log:**
- All 26 tool guide generators re-run successfully; every `_User_Guide.docx`
  and `_Logging_Guide.docx` regenerated from the (now E501-clean) sources.
- Feature audit confirmed all Tier 3/4 features are documented: sample
  rate/bit depth conversion (music_format_converter), AcoustID fingerprinting
  (audio_fingerprinter), CUE sheets (cd_ripper), synced LRC/USLT lyrics
  (lyrics_manager — see 3.1 completion entry below), ReplayGain (converter
  guide). audio_refinery correctly references sample rate only in integrity
  context (no resample stage exists).
- `guide_to_program` (the `open_help` → tool-folder map) was missing three
  entries and had one filename drift:
  - Added `Mood_Analyzer_User_Guide.docx → mood_analyzer` (its Help button
    was wired but the lookup warned "Unknown help guide").
  - Added `Tag_Field_Updater_User_Guide.docx → tag_field_updater` and
    `File_Reorganizer_User_Guide.docx → file_reorganizer` (registered tools
    with generated guides were unregistered — AGENTS.md new-tool checklist).
  - Repaired `album_art_sync`: generator produced
    `Album_Art_Synch_User_Guide.docx` while `app.py` HELP_GUIDE and the map
    both use `Album_Art_Synchronizer_User_Guide.docx` (Help file-not-found at
    runtime). Generator output renamed, docx regenerated, stale `Synch` file
    deleted.
- AGENTS.md stale type name fixed: `ToolInfo` → `ToolManifest` in the
  "Registering a New Tool" checklist.

**Scope:**

- [x] Review `AGENTS.md` gotchas section — update any outdated entries
  *(ToolInfo → ToolManifest)*
- [x] Review `user_guides/` — ensure all new features (sample rate
      conversion, fingerprinting, CUE sheets, etc.) have user guides
- [x] Regenerate any `.docx` files from generator scripts
- [x] Update `pyproject.toml` version / changelog if applicable
  *(no release version bump required — internal documentation-only change;
  project version remains 1.0.0)*

**Deliverables:**
- Updated AGENTS.md (ToolManifest; guide_to_program registration note)
- Updated user guides (all regenerated)
- Regenerated documentation files (all `.docx`)
- `audio_suite_shared/platform_utils.py` guide map completed (27 mappings)

**Success criteria:**
- Every new tool/feature from Tier 3 phases has a corresponding user
  guide entry ✓
- No stale instructions in existing guides ✓
- `guide_to_program` covers every registered tool with a generated guide ✓
- Full verification gate green: ruff, mypy, bandit, compileall,
  full-suite pytest (6320 passed, 5 skipped, 77.21% coverage) ✓

---

## Implementation Roadmap

The phases are grouped into recommended implementation sprints. Each sprint
is a natural stopping point — the codebase is in better shape than before,
and no half-finished work is left dangling.

### Sprint 1 — Quick Wins (1 week) `[x]` COMPLETE
> Foundation cleanup that unblocks everything else with minimal risk.

| Phase | Days | Dependency | Status |
|-------|------|------------|--------|
| 1.1 Named Constants Extraction | 1–2 | — | [x] |
| 1.2 Dead Code & Stray Print Cleanup | 0.5–1 | — | [x] |
| 1.3 Tighten Broad Exception Catches | 1 | — | [x] |
| 1.4 Type Annotation Hardening | 2–3 | — | [x] |

### Sprint 2 — Structural Refactoring (1.5 weeks)
> Fix the architectural debt that makes feature work harder.

| Phase | Days | Dependency | Status |
|-------|------|------------|--------|
| 2.1 Library Stats Deduplication | 3–4 | 1.1 | [x] |
| 2.2 Consistent BaseSuiteApp Adoption | 2 | — | [x] |
| 2.3 Migrate file_reorganizer to Shared Config | 1–2 | — | [x] |
| 2.4 BaseFileProcessor Test Coverage | 2–3 | 1.1 | [x] |
| 2.5 Metadata Scrubber Test Coverage | 1–2 | 1.3 | [x] |

### Sprint 3 — High-Value Features (2 weeks)
> Add the capabilities that close competitive gaps.

| Phase | Days | Dependency | Status |
|-------|------|------------|--------|
| 3.1 Sample Rate & Bit Depth Conversion | 3–4 | — | [x] |
| 3.2 Audio Fingerprinting (AcoustID) | 5–7 | 1.4 | [x] |
| 3.3 CUE Sheet Support | 3–4 | — | [x] |

### Sprint 4 — Completing the Picture (1.5 weeks)
> Fill remaining gaps and polish.

| Phase | Days | Dependency | Status |
|-------|------|------------|--------|
| 3.4 Lossless MP3 Volume Adjustment | 3–4 | — | [x] |
| 3.5 Synced Lyrics (LRC) Support | 3–4 | — | [x] |
| 4.1 Config Migration Audit | 1 | 2.3 | [x] |
| 4.2 Lazy Import Elimination | 0.5 | 2.1 | [x] |

### Sprint 5 — Final Polish (1 week)
> Consistency and documentation alignment.

| Phase | Days | Dependency | Status |
|-------|------|------------|--------|
| 4.3 Line Length Policy | 0.5 | 1.4 | [x] |
| 4.4 Documentation Sync Pass | 1 | All prior | [x] |

---

## Tracking Progress

After completing each phase, update the checkbox in this document and
add a completion note:

```
### Completion Log

| Phase | Completed | Notes |
|-------|-----------|-------|
| 1.1   | 2026-09-10 | Created `audio_suite_shared/constants.py` with 8 named constants (`DEFAULT_MAX_WORKERS`, `WORKER_TIMEOUT_SECS`, `CPU_WORKER_TIMEOUT_SECS`, `JPEG_QUALITY`, `MAX_DURATION_HISTORY`, `DEFAULT_WINDOW_GEOMETRY`, `VARIOUS_ARTISTS_ALIASES`, plus max-history constant); updated all consumers across `file_processor_base`, `art_processor`, `suite_config`, `file_reorganizer`, `tag_field_updater` |
| 1.2   | 2026-09-10 | Removed dead `threading.Lock()` in `file_processor_base.py`; replaced `print()` with `logger.error()` in `launcher.py`; consolidated dual loggers in `tag_helper_base.py`; removed 3 redundant local logger rebindings + unused `error_logger` import; added documented rationale comment for `time.sleep(0.05)` in `scrubber.py`. Tool_plugin `print()` left unchanged — it lives inside a docstring. |
| 1.3   | 2026-09-10 | Narrowed 5 broad catches in `library_stats/core/file_processor.py` to `(OSError, ValueError)` / `(ValueError, TypeError)` with `exc_info=True`; narrowed 2 catches in `resize_music_recursive.py` to `OSError`. `picker_dialog.py:95` kept as broad safety net after specific catches. Tests updated to raise realistic exception types (`OSError`/`ValueError` instead of `RuntimeError`). |
| 1.4   | 2026-09-10 | Enabled `disallow_incomplete_defs = true` + `check_untyped_defs = true` in `pyproject.toml`; added `AppState` Protocol in `suite_config.py`; added `MutagenAudio` type alias in `tag_helper_base.py`. `mypy . --strict` clean on 387 source files. |
| 2.1   | 2026-09-10 | Library stats dedup: added `_extract_year_from_tags()` (replaces 3 inline copies in full scan, cached scan, and export_csv), `_read_file_tags()` returning a frozen `_FileTags` dataclass (replaces 2 copies of the per-file tag-read block), and `_populate_report()` (replaces 2 copies of the counter→report block; now also used by `_build_report_from_cache`). Scanner bodies shrank 152→110 (`_scan_directory_full`) and 108→67 (`_scan_directory_cached`). Added 17 targeted unit tests (`TestExtractYearFromTags`, `TestPopulateReport`, `TestReadFileTags`). All 142 library_stats tests pass; ruff + mypy --strict + bandit clean. |
| 2.2   | 2026-09-10 | BaseSuiteApp adoption (minimal scope — see Decision Log): migrated `album_art_normalizer/app.py`, `file_reorganizer/app.py`, and `tag_field_updater/ui/app.py` from inline/bootstrap duplication to subclassing `app_bootstrap.BaseSuiteApp`, matching the `metadata_scrubber` reference. `FileReorganizerApp`/`TagFieldUpdaterApp` now use the standard `App(root)` constructor; entry points (`app.py main()`, `file_reorganizer/__init__.py` delegate, deprecated `Tag_Field_Updater.py` shim) create the root. Removed per-tool duplications of `_open_help`/`_open_log`/`_open_folder`/`_on_error` (album_art_normalizer) and the manual theme/palette/typography bootstrap (file_reorganizer). Added compliance checklist to plan §2.2. GUI smoke-tested against a real Tk root for all three tools; full suite 5558 passed; ruff + mypy --strict + bandit clean. |
| 2.3   | 2026-09-11 | Migrated `file_reorganizer` settings to the shared `audio_suite_config.json` via `audio_suite_shared.suite_config`. New `file_reorganizer/utils/config.py` (`load_settings`/`save_settings`) with guarded one-time legacy migration: reads old `reorganizer_config.json`, writes only keys absent from shared config, then deletes the legacy file. `app.py` `_save_settings`/`_load_settings` delegate to the wrapper; CLI `--action`/pattern flags now fall back to saved config (`action: str | None` + `saved[...]` resolution; explicit flags still win). Added 21 tests: `tests/test_config.py` (load/save/migration) and new `tests/test_cli.py` (default resolution + flag override, via patched `file_reorganizer.cli.load_settings`/`run_reorganizer`). All 113 file_reorganizer tests pass; ruff + mypy --strict clean. User guide generator updated and docx regenerated. |
| 2.4   | 2026-09-11 | `audio_suite_shared/tests/test_file_processor_base.py` expanded to 42 tests: added discovery-failure and no-files `on_error` routing for `run_parallel_processing()` (previously uncovered lines 171-176, 179-180) and `run_with_retry()` coverage (success, retry-then-success, exhaustion, non-retryable immediate raise, RetryConfig delegation) covering lines 484-490. Note: `run_parallel_processing()` errors are reported through the per-file `on_progress(n_errors=...)` path while the `@handle_audio_errors` decorator swallows worker exceptions, so the `on_error` channel only fires for directory-level (discovery/no-files) failures — this is the intended contract, verified by the new tests. Coverage 95%→100%. |
| 2.5   | 2026-09-11 | `metadata_scrubber/tests/test_scrubber.py` expanded to 87 tests with direct `_collect_tags_to_preserve()` unit tests for MP3 (ID3: essentials-with-flags-off, TPE2/USLT/APIC/TXXX preservation, unreadable-frame skip via `__getattribute__` proxy), FLAC (Vorbis: essentials, lyrics/albumartist/picture/custom tags, empty-value and unreadable-tag skips), and M4A (MP4: essentials, `\xa9lyr`/`covr`/freeform atom preservation, None-atom and unreadable-atom skips); plus `_restore_tags` failure-swallow, no-supported-files `on_error`, a real no-tags file exercising the `[NO TAGS]` path (pydub embeds a TSSE encoder frame, so a live wipe via `audio.delete()` is required), and top-level error-handler coverage by failing the first `slot_vars[].set()` call. Coverage 91%→99% (only line 277 remains: dead defensive branch — all real wipes return empty tags, never None, so `audio.add_tags()` on a None tags object is unreachable in practice). |
| 3.1   | 2026-09-11 | Sample Rate & Bit Depth Conversion in `music_format_converter`. New `SAMPLE_RATE_PRESETS`/`BIT_DEPTH_PRESETS` in `ffmpeg_params.py`; `get_ffmpeg_params(..., sample_rate=...)` injects `-ar <rate>` (default `source` = no flag, keeps input rate); `_wav_params_for()` resolves explicit `bit_depth` → config override → lossy 16-bit fallback → probed lossless depth. Threaded `sample_rate`/`bit_depth` through `process_single_file`/`run_conversion`/`_process_with_undo`, `app.py` (`_run` header + `run_conversion` kwargs, presets, CLI apply, setup tab vars), `ui/setup_tab.py` (Sample Rate & Bit Depth comboboxes; Bit Depth auto-disabled/reset unless output format is WAV), CLI (`--sample-rate`/`--bit-depth` click Choice flags + `cli_args.py` parsing/validation). Added 28 targeted tests across `test_file_processor.py`, `test_cli_args.py`, `test_setup_tab.py`, `test_app.py` (incl. live ffmpeg command pass-through for `-ar`/`pcm_s24le`). Full suite 5632 passed; ruff + mypy --strict clean; bandit 0 high/0 medium (5 low pre-existing subprocess findings). User guide `.docx` updated directly (no generator script exists for this tool): Key Features bullets, new Setup-tab Sample Rate & Bit Depth sections, WAV row in the quality table, CLI syntax/parameters/example for both flags, log contents, and the processing-pipeline bullet — with a backup of the pre-change `.docx`. |
| 3.3   | 2026-09-13 | CUE Sheet Support. New shared modules: `audio_suite_shared/cue_parser.py` (strict parser: frozen `CueSheet`/`CueFileEntry`/`CueTrack`/`CueIndex`, `CueParseError(AudioSuiteError)`, MSF validation mm≤599/ss≤59/ff≤74, REM/PERFORMER/TITLE/SONGWRITER/CATALOG/FILE/TRACK/INDEX/PREGAP/POSTGAP/ISRC/FLAGS, doubled-quote-escape tokenizer, UTF-8-BOM-tolerant `parse_cue_file`), `cue_generator.py` (`TrackSpec`/`CueFileSpec`, `ms_to_frames`/`format_msf` clamped to 599:59:74, extension-derived `FILE` type tokens, `build_cue`/`write_cue`), and `cue_split.py` (per-track ffmpeg with input-side `-ss`/`-to` + `-c copy` via `run_secure_subprocess`, metadata sanitised to pass the validator; `AudioExternalToolError`/`AudioFileNotFoundError` on failures). CLI: first nested group `audiosuite cue parse|generate|split` (registered via import in `cli_app.py`; not a tool-manifest entry — see Decision Log) with `-o/--title/--artist` (generate, accepts a directory or single file) and `-o/--ffmpeg/--json` (split). CD Ripper integration: `--cue/--no-cue` flag + `write_cue` param threaded through `cli.py`/`RipSession`; `_write_rip_cue` writes one `<album>.cue` per album folder from completed tracks (non-fatal on write error); GUI checkbox on the Setup tab and a threaded "Split CUE..." button on the Rip tab. 98 new/updated tests (parser/generator/split/CLI + cd_ripper flag & CUE-write suites). Full suite 5917 passed; ruff + mypy --strict clean; bandit 0 high/0 medium. Docs: `CLI_Commands_Reference.md` (CD Ripper + CUE Sheets sections, All Commands table) and `CD_Ripper_User_Guide.docx` updated directly (no generator). |
| 3.4   | 2026-09-14 | Lossless MP3 Volume Adjustment (pure-Python MP3Gain-style). New `audio_suite_shared/lossless_gain.py`: bit-level global_gain rewrite (side-info offsets: MPEG-1 35 / MPEG-2 stereo 33 / MPEG-2 mono 31; 1 unit ≈ 1.505 dB; 0–255 clamp; Xing/Info/VBRI skipped; undo snapshots via `record_tag_edit_snapshot`). `audio_normalizer`: new `--mode normalise|lossless` CLI choice (plan said `lossless-gain` — see Decision Log) + "Lossless Normalize" run mode; MP3 lossless global_gain path, non-MP3 falls back to loudnorm encode. `replaygain_analyzer`: optional lossless gain application after tagging (TAGGED + GAIN APPLIED status; `--apply-gain`/`--no-apply-gain` standalone-only). `music_format_converter`: `--normalize-mp3/--no-normalize-mp3` + `--target-lufs` (default -16.0) CLI flags, Setup-tab checkbox + Target Loudness entry, post-conversion measure-then-apply via ffmpeg loudnorm JSON (`input_i`) then `apply_track_gain`, ±0.5 LUFS tolerance skip, dry-run "WOULD NORMALIZE" preview. 37 lossless_gain tests (89% cov) + 166 normalizer + 169 replaygain + 57 new converter tests. Full suite 6010 passed; ruff + mypy --strict (412 files) clean; bandit 0 high/0 medium. User guides updated directly (no generators): Audio Normalizer (Key Features bullet, Mode table Lossless Normalize row, new "Lossless vs Lossy Normalisation" section, `--mode` CLI row), Music Format Converter (Key Features bullet, "Normalize MP3 Output (Lossless)" Setup-tab section, `--normalize-mp3`/`--target-lufs` CLI rows). |
| 3.5   | 2026-09-15 | Synced Lyrics (LRC) Support, delivered as the new `lyrics_manager` tool (see Decision Log). Shared layer: `audio_suite_shared/lrc_handler.py` (`LrcParseError(AudioSuiteError)`, `LrcLine`/`LrcMetadata`/`LrcDocument`, strict `parse_lrc` — blank-timestamped and untimestamped non-blank lines rejected, multi-timestamp lines expanded, `mm:ss`/`hh:mm:ss` + hundredths, BOM/CRLF tolerated, meta `ti/ar/al/by`/`offset` handled; `generate_lrc` centisecond round-trip; `format_timestamp`) and tag facades `write_synced_lyrics`/`read_synced_lyrics` in `tag_helper_writer.py`/`tag_helper_reader.py` (MP3/WAV/AIFF ID3 SYLT type-1 frames via IFFID3Handler; FLAC/OGG/Opus `SYNCEDLYRICS` verbatim with `LYRICS` left untouched; M4A read `None`/write `AudioTagError`; undo snapshot on write; re-exported in `tag_helper.py`). New `lyrics_manager` package: `cli.py` (`audiosuite lyrics import|export`, moved from `audio_suite_shared/lrc_cli.py`), `ui/app.py` standalone `BaseSuiteApp` window (audio file picker + Import/Export + status + Help), `__main__`, `Lyrics_Manager.pyw` launcher with pre-flight guard, Master Driver on-demand card (`lyrics_manager_card.py`, "Open Lyrics Manager" button, no module checkbox, excluded from UTIL select-all), `utilities_window.on_open_lyrics` callback, `app.py._open_lyrics_ui`, `DEPENDENCY_GRAPH` entry. `tag_field_updater` LRC integration reverted to pre-3.5 (decision to keep it a single-purpose tag editor). Registration: manifest entry (utility, standalone, `cli_command="lyrics"`, order 58), pyproject testpaths + coverage source, guide registration in `platform_utils`. ~30 new/ported tests (lyrics_manager CLI + UI suites; expected-set updates in `test_tool_plugin`/`test_app_state`/`test_app`/`test_ui_cards`). Docs: `Lyrics_Manager_User_Guide.docx` (new generator) + `CLI_Commands_Reference.md` (Synced Lyrics section + table rows). Full suite 6163 passed, 5 skipped (platform-only); ruff + mypy --strict clean; bandit 0 high/0 medium. |
| 4.1   | 2026-09-17 | Tool-Local to Shared Config Migration Audit. Empirical audit classified every tool-local JSON config against AGENTS.md exceptions: legitimate — `album_art_sync/album_art_config.json` + `album_art_sync/core/album_art_config.json` (API keys), `audio_refinery/refinery_settings.json` (complex nested), `metadata_scrubber/tag_prefs.json` (domain-specific list); violators — `tempo_analyzer/tempo_config.json` (stale leftover; `config.py` already fully delegates to `suite_config`) and `cd_ripper/cd_ripper_prefs.json` (single flat `output_dir`). Migrated `cd_ripper` to the shared config: rewrote `cd_ripper/core/cd_ripper_config.py` as a thin `suite_config` wrapper (key `cd_ripper_output_dir`) with the same public API (`load`/`save`/`get_output_dir`/`set_output_dir`/`get_log_path`) plus a guarded one-time `migrate_legacy()` (reads legacy file, copies `output_dir` only if the shared key is absent, deletes the legacy file, never raises); `get_log_path` now derives from the module location so `cd_ripper.log` stays put; dropped the obsolete `error_logger`/`handle_audio_errors` imports in favour of stdlib `logging`. Rewrote `cd_ripper/tests/test_cd_ripper_config.py` in lockstep (real `suite_config` with `CONFIG_PATH` redirected to tmp via the autouse `isolated_config` fixture, `_legacy_config_path` monkeypatched; migration tests use a real temp legacy file). Updated the stale `cd_ripper_prefs.json` co-location phrasing in `rip_log.py` docstring. Deleted `tempo_analyzer/tempo_config.json` and ran the one-time migration on the dev machine (`cd_ripper_output_dir` = `D:/Users/wilte/Desktop/New folder` lands in `audio_suite_config.json`, legacy file removed). cd_ripper suite: 204 passed. Full suite verification: 6317 passed, 5 skipped (platform-only), coverage 77.26%; ruff clean (types); mypy --strict clean (430 files); bandit regression scan 0 high / 14 medium / 24 low — all Medium findings are pre-existing B608 hardcoded-SQL heuristics in `library_stats/library_cache.py` (last modified 21/08, untouched by this phase; every flagged query is parameterized with `?` placeholders, only constant fragments are interpolated); the 24 Low are the documented `run_secure_subprocess` call sites in `cd_ripper/ui/results_tab.py`. |
| 4.2   | 2026-09-17 | Lazy Import Elimination in Hot Paths. Hoisted the two `from audio_suite_shared.tag_helper_reader import (...)` blocks in `library_stats/core/file_processor.py` (`_read_file_tags` and `export_csv`) to module level — no circular-import risk because `tag_helper_reader` imports only `audio_suite_shared` submodules and never `library_stats`. No `# noqa: PLC0415` markers existed in the file, so nothing to remove. This broke the existing tests exactly as the AGENTS.md "Mock patch target follows the import" gotcha predicts: the suites patched `audio_suite_shared.tag_helper_reader.read_*` (source module), which worked for function-local imports but silently no-ops once `file_processor` binds the names at module level. Retargeted patches to the importing bindings: `test_file_processor.py` `_reader_mocks()` → `library_stats.core.file_processor.{name}` (~100 matches updated via `replaceAll` in `test_library_stats.py`), and `test_cli.py` split into `scan_stubs` (patch `file_processor`) + `completeness_stubs` (patch source module, since `completeness.py` still uses function-local imports). All 142 library_stats tests pass; ruff + mypy --strict clean. Full suite verification: 6317 passed, 5 skipped (platform-only), coverage 77.26%. |
| 4.3   | 2026-09-17 | E501 re-enabled at 88 chars across the whole repo. `pyproject.toml`: `line-length = 88`, `[tool.ruff.lint] ignore = []`, `target-version = py310`, `format.quote-style = "double"`, `exclude = [".venv"]`. CI gate (`ruff check .`) scans repo-wide with no per-file excludes, so the `user_guides/` generator sources were in scope too — all **863 E501 findings fixed** (716 user-guide generators + 146 package modules + 1 stray dead file) to **0**. Ruff E501 has no usable autofix (even `--fix --unsafe-fixes` leaves them standing), so every wrap was a manual continuation/wrap preserving byte-identical string values (`\uXXXX` escape lines are measured by decoded display width — the `album_art_normalizer.py` separator is exactly 51 escapes). 6 parallel agents: UG-A/B/C (221/210/285 = 716 guide lines) + PKG-A `audio_suite_shared`/`audio_enhancer`/`album_art_normalizer`/`album_art_sync`/`audio_refinery` + PKG-B (remaining 18 packages, 73 files). Stray dead file `mood_analysis_batch_tagger/_/_init/_/_.py` (217-byte duplicate of `__init__.py`, imported nowhere) reflowed — worth deleting. Gate: `ruff check .` → "All checks passed!"; `ruff format --check .` → "711 files already formatted"; `compileall` exit 0; `mypy . --strict` → 430 files clean; `bandit -r audio_suite_shared -c pyproject.toml` → 0 High / 0 Medium, 13 Low (documented subprocess wrappers); full-suite `pytest` → 6317 passed, 5 skipped, coverage 77.21%. |
| 4.4   | 2026-09-17 | Documentation Sync Pass. All 26 guide generators re-run → every `.docx` regenerated (previously "STALE (gen newer)" tags resolved). Feature audit vs Tier 3/4: sample rate/bit depth (music_format_converter), AcoustID fingerprinting, CUE sheets (cd_ripper), synced LRC/USLT (lyrics_manager), ReplayGain (converter guide) all present; audio_refinery correctly references sample rate only in integrity context. **Genuine doc-registration bugs fixed in `audio_suite_shared/platform_utils.py` `guide_to_program`:** (1) `mood_analyzer` was missing entirely — its Help button is wired (`app.py` HELP_GUIDE + `_open_help` at line 250) but the map lookup warned "Unknown help guide"; added `Mood_Analyzer_User_Guide.docx → mood_analyzer`. (2) `album_art_sync` filename drift — generator produced `Album_Art_Synch_User_Guide.docx` while `app.py:45` HELP_GUIDE and the map both use `Album_Art_Synchronizer_User_Guide.docx` (runtime Help would show file-not-found); generator OUTPUT renamed to match, docx regenerated, stale `Synch` file deleted. (3) `Tag_Field_Updater_User_Guide.docx → tag_field_updater` and `File_Reorganizer_User_Guide.docx → file_reorganizer` added (registered tools with generated guides were unregistered per the new-tool checklist). AGENTS.md: `ToolInfo` → `ToolManifest` stale type name in the Registering-a-New-Tool checklist. pyproject version left at 1.0.0 (internal doc-only change — no release bump). **Tests added in lockstep:** 4 regression tests mirroring the existing "guide resolves in centralized location" pattern (`test_mood_analyzer_guide_*`, `test_tag_field_updater_guide_*`, `test_file_reorganizer_guide_*`). Gate: full-suite `pytest` → **6320 passed**, 5 skipped, coverage 77.21%; ruff clean; mypy --strict clean; bandit 0 High / 0 Medium; compileall exit 0. |

---

## Decision Log

Record any decisions made during implementation that diverge from the
original plan:

| Date | Phase | Decision | Rationale |
|------|-------|----------|-----------|
| 2026-09-10 | 1.2 | Left `tool_plugin.py:15` `print()` unchanged | It resides inside a docstring, not executable code |
| 2026-09-10 | 1.3 | Kept broad catch in `picker_dialog.py:95` | Acts as a safety net after specific `requests`-family catches; no bare `pass` |
| 2026-09-10 | 2.1 | `_extract_year_from_tags` returns `int | None`, not the plan's `str | None` | The downstream consumers (`_decade_bin(int | None)`, the cached scan's `upsert_file(year=int | None)`) and all existing tests treat the year as an int; the plan sketch's `str` return was an approximation. |
| 2026-09-10 | 2.1 | Chose the template-method option (`_read_file_tags` + `_populate_report`) rather than merging the two scanners into one `_scan_directory(..., use_cache)` | The two walkers differ structurally after the walk (full aggregates in memory; cached collects stats for cache-miss filtering then rebuilds from SQLite). A single merged function needs `if use_cache:` branches in 4+ places, harming readability. The shared template steps now own every duplicated block (year extraction, tag reads, report population). |
| 2026-09-10 | 2.1 | Total file lines grew 723→766 despite scanner-body dedup | The shared helpers now live in the same file (DRY vs. line-count trade-off). `_scan_directory_full` and `_scan_directory_cached` shrank 152→110 and 108→67; `_extract_year_from_tags` exists exactly once. Acceptable given the plan's primary goal is eliminating the copy-pasted blocks. |
| 2026-09-10 | 2.2 | Scope = minimal per plan wording: the plan's classification explicitly treats `bootstrap_tool_app()` users as "already compliant", so this phase migrated only `album_art_normalizer` (named in the plan) plus the two tools that duplicated init logic (`file_reorganizer`, `tag_field_updater`). The original success-criterion line "`grep -rln 'BaseSuiteApp' */app.py` returns all tool app.py files" contradicts that classification; it was reworded to reflect the actual scope. | Full BaseSuiteApp adoption of all 19 remaining `bootstrap_tool_app()` tools would need `BaseSuiteApp` to accept `apply_ttk_styles=False` (required by cd_ripper/asx_extractor custom styles) plus per-tool behavioural review — a larger, higher-risk change not implied by the scope items. User approved minimal scope. |
| 2026-09-10 | 2.2 | `FileReorganizerApp` and `TagFieldUpdaterApp` adopted the standard `App(root)` constructor (root passed in by the launcher), matching `metadata_scrubber`/`ArtNormalizerApp`. | `BaseSuiteApp.__init__` requires a `root` argument; keeping no-arg self-creating constructors would have diverged from the suite convention and left inline `tk.Tk()` creation. Entry points (`app.py main()`, `Tag_Field_Updater.py` deprecated shim) updated to create the root. |
| 2026-09-10 | 2.2 | Fresh-launch default window geometry for `file_reorganizer` (900×750) and `tag_field_updater` (800×600) now falls through to `BaseSuiteApp`'s standard 850×950 centred default. | `setup_window` only centring-sizes when no saved geometry exists; saved user geometry still wins afterwards. Matching the suite standard is the intent of the phase. |
| 2026-09-10 | 2.2 | `album_art_normalizer`'s custom `_on_error` (thread-safe `root.after` + `start_btn.config("normal")`) replaced by `BaseSuiteApp._on_error` (direct `messagebox.showerror` + `config(state="normal")`). | Matches the `metadata_scrubber` reference which also invokes it from a worker thread; additionally fixes a latent Tk API misuse (`config("normal")` passed the state string as an option name). |
| 2026-09-11 | 2.3 | CLI `--action` default changed `"copy"` → `None` so the flag resolves to saved config when omitted; explicit flag still wins. `run_reorganizer` always receives a concrete action because `action or saved["action"]` falls back to the saved (or default) value. | The plan scope says "update CLI args to read from shared config"; making the click default `None` and resolving after merge is the only way to distinguish "not passed" from a hardcoded default that would silently shadow saved settings. |
| 2026-09-11 | 2.3 | Legacy migration is guarded (only copies keys not already present in shared config) and `save_settings` never persists `source_dir` — same as the previous `_save_settings`. | Prevents stale legacy values from clobbering newer shared-config state, and preserves the existing "source not remembered" behaviour. |
| 2026-09-11 | 2.4 | `run_with_retry()` tested at the `retry_with_backoff` integration level (with `base_delay=0` to avoid real sleeps) plus a lazy config-delegation test that patches `audio_suite_shared.file_processor_base.retry_with_backoff` to assert the constructed `RetryConfig`. | Tests real retry/backoff semantics end-to-end; the lazy test pins the configuration contract (max_retries, backoff_factor=2.0, retry_on_exceptions) without timing flakiness. |
| 2026-09-11 | 2.4/2.5 | The plan's "create `test_file_processor_base.py` / `test_scrubber.py`" scope items were already satisfied by pre-existing files; work was reframed as extending those files with the remaining uncovered, plan-scope paths. | Plan was written before the files existed; altering the warning-flag wording would be editing prior scope. The checkbox for each item is marked done with the concrete test counts in the note. |
| 2026-09-11 | 2.5 | `scrubber.py` line 277 (`if audio.tags is None: audio.add_tags()`) intentionally left uncovered even after targeted tests. | Empirically verified: wiping any of MP3/FLAC/M4A/OGG and re-loading returns an empty tags container (`{}`/`[]`), never `None`, so `audio.tags is None` cannot fire through real I/O. Forcing it would require mocking the restore-stage `_load_audio`, testing a contrived state the production code path cannot reach — rejected as mock-theater. |
| 2026-09-13 | 3.3 | Splitting was implemented as a third shared module `cue_split.py`, although the plan's scope names only `cue_parser.py` + `cue_generator.py`. | Splitting shell out to ffmpeg through `run_secure_subprocess` with its own exception plumbing (`AudioExternalToolError`, `AudioFileNotFoundError`); keeping `cue_generator.py` pure (text generation, no process spawning) matches AGENTS.md's small/focused-module rule and keeps the security-sensitive path isolated. |
| 2026-09-13 | 3.3 | The plan's "Option to rip from existing CUE sheet (split single-file image)" was implemented as the standalone `audiosuite cue split` command + the Rip-tab "Split CUE..." button, not as an input mode of the CD ripper itself. | "Ripping from an existing CUE sheet" is only applicable to audio *image files* already present on disk; the CD ripper extracts raw audio over SCSI from a physical disc, so an input-CUE mode there is meaningless. The splitter operates on previously exported/ripped single-file images — the actual workflow described. |
| 2026-09-13 | 3.3 | `audiosuite cue generate` accepts a directory OR a single audio file (`TARGET`), diverging from the plan's `<file>` signature. | Tag reading and timestamp assembly are identical for both inputs; a directory (a ripped album folder) is the dominant real-world case, and single-file support covers per-image workflows. Output defaults to `album.cue` next to the input (`-o` overrides). |
| 2026-09-13 | 3.3 | `cue` is a nested click `@cli.group` registered via an import in `cli_app.py`, with no `ToolInfo` manifest entry, Master-Driver card, arg-builder entry, or batch-orchestrator entry. | It is a shared suite utility reachable only from the unified CLI — not an enrich/refinery tool with a GUI card. Keeping it outside the manifest avoids touching the `test_tool_plugin` expected-command set and the enrich arg-builder assertions. |
| 2026-09-13 | 3.3 | Track splits use input-side seeking (`-ss`/`-to` placed before `-i`) with `-c copy`; generated `FILE` type tokens are derived from the source file's extension. | Input-side seeking with a stream copy is keyframe-accurate and fast (no decode-from-start), unlike output-side `-ss` which mis-cut with `-c copy`. Correct `FILE` type tokens keep sheets spec-compliant so players do not misread the container. |
| 2026-09-14 | 3.4 | Implemented lossless MP3 gain as a pure-Python `global_gain` rewrite in `audio_suite_shared/lossless_gain.py`; the plan's preference was to evaluate `mp3rgain` (Rust) as a bundled external tool first. | `mp3rgain` is not a wheels-distributable dependency (Cargo binary) and bundling it into the suite would complicate the launcher/guard + Windows packaging. A pure-Python implementation is ~150 LOC, deterministic, testable in CI, and requires no subprocess at runtime (the loudnorm *measurement* still shells out to FFmpeg only where a target LUFS must be estimated). This matches the plan's own fallback option. |
| 2026-09-14 | 3.4 | `audio_normalizer` CLI mode value is `--mode lossless`, not the plan's `--mode lossless-gain`. | The plan's wording was per-gain semantics, but the tool's existing modes are `normalise` (default) / `dry`; exposing `lossless-gain` would make the choice asymmetric. `lossless` reads naturally alongside `normalise` in the UI mode dropdown (`Lossless Normalize`) and mirrors the replaygain/converter naming. |
| 2026-09-14 | 3.4 | `music_format_converter` gain application happens **post-conversion**: the file is first converted to MP3, measured via FFmpeg loudnorm (`input_i`), then `apply_track_gain` adjusts the resulting frames; ±0.5 LUFS tolerance skips the adjustment. | The converter's output is freshly-encoded MP3, so per-frame gains are uniform; measuring the encoded result (not the source) guarantees the adjustment targets the file the user actually receives, matching how mp3gain operates on already-encoded files. A dry-run still reports the intent ("[WOULD NORMALIZE MP3]") without mutating, and failures surface as "[GAIN FAILED ...]" without failing the conversion. |
| 2026-09-15 | 3.5 | Phase 3.5 delivered as the new `lyrics_manager` tool, not by adding an LRC frame to `tag_field_updater`. | The plan explicitly offers "Add LRC import/export to `tag_field_updater` **or** create new `lyrics_manager` tool". LRC import/export is a distinct single-file workflow unrelated to `tag_field_updater`'s library-wide TXXX scanning; keeping it separate avoids mixing concerns and a feature the original tool was never designed for. `tag_field_updater` was restored to its pre-3.5 state (LRC frame + its 13 tests removed). |
| 2026-09-15 | 3.5 | The `lyrics` CLI lives in `lyrics_manager/cli.py` (a per-tool module registered via `cli_app.py` import), moved from `audio_suite_shared/lrc_cli.py`. | Unlike the `cue` group (a shared suite utility with no GUI/card), Lyrics Manager is a registered tool with its own manifest entry, Master Driver card, pyw launcher and user guide — owning its CLI module keeps the per-tool code together per AGENTS.md conventions. |
| 2026-09-15 | 3.5 | `lyrics_manager` is a `standalone=True` utility: on-demand card with an "Open Lyrics Manager" button, no module checkbox, excluded from UTIL select-all, no arg-builder entry (utility builder yields `[]`), `DEPENDENCY_GRAPH` entry `[]`, order 58 (below undo's 60 so Undo stays bottom of the UTIL tab). | Mirrors the `undo_tag_edits` registration pattern for single-file on-demand tools. It can never run as part of a batch (batch args would be empty display flags), so it cannot be launched by LAUNCH UTILITY PROCESS. |
| 2026-09-15 | 3.5 | Embedding target is the Vorbis **`SYNCEDLYRICS`** comment for FLAC/OGG, plus the `LYRICS` comment as a read fallback; the plan said "Vorbis LYRICS fields". | `SYNCEDLYRICS` is the conventional Vorbis field name for synced lyrics (Picard/Foobar2000); `LYRICS` is the unsynced field. The handler reads either, prefers `SYNCEDLYRICS`, and never overwrites an existing `LYRICS` tag on import. |
| 2026-09-15 | 3.5 | GUI app is a minimal standalone `BaseSuiteApp` window (audio file + Import/Export/status + Help), not a business-rule-heavy tool. | Keeps the tool single-purpose (mirroring the undo window's simplicity); the same shared tag-facade functions back both the GUI and the CLI, so behaviour is identical.
| 2026-09-16 | 3.5 | Phase 3.5 reworked from single-file LRC import/export to a directory-scanning batch tool that fetches lyrics from a remote source and embeds them. The import/export GUI, `BaseSuiteApp` window, and `lyrics import|export` CLI group were removed; a three-tab `app.py` (Setup/Processing/Results) mirroring `bpm_analyzer` replaced the old `ui.py`. | Users source lyrics from servers (LRCLIB provides synced + plain in one call); maintaining a local `.lrc` workflow gives a worse answer than the same embedding primitives driven by a batch loop. The shared `lrc_handler.py` + tag facades remain the single embed path for both old and new design. |
| 2026-09-16 | 3.5 | Lyrics Manager is now an `enrich_order-managed` batch tool (Master-Driver ENRICH card with module checkbox and arg-builder enrich args `[path, mode, start, end]`), not the `standalone=True` utility of the 2026-09-15 delivery. | It writes tags across a directory like `bpm`/`key`, and the arg-builder/`DEPENDENCY_GRAPH` must treat it as an enrich tool for LAUNCH BATCH and batch orchestration to reach it. |
| 2026-09-16 | 3.5 | Lyric transport is a modular provider registry (`core/providers/`): `LyricProvider` ABC with `search(artist, title, *, timeout) -> LyricResult | None`, `lyrics_manager.core.providers.registry` holding provider classes, and `get_provider`/`get_provider_names` DI wired to GUI/CLI. `LRCLIBProvider` is the default (`GET /api/get?artist_name=&track_name=`); errors surface as a typed `LyricProviderError(AudioSuiteError)`. | Mirrors the acoustid client pattern so a second source (Genius, Musixmatch) is a class + registration, not a rewrite of `file_processor`/`app`. Unknown providers fail fast with a `ClickException` listing available names. |
| 2026-09-16 | 3.5 | Unsynced lyrics fall back to a per-format embed: `USLT` for MP3/WAV/AIFF, `LYRICS` and not `SYNCEDLYRICS` for FLAC/OGG/Opus, `\xa9lyr` (plain-only) for M4A/MP4. Files whose artist/title tags are missing or "Unknown" are skipped. | M4A cannot hold a standard synced field, so the plain fallback is the only option there; `write_plain_lyrics`/`read_lyrics_tags` were added to the shared tag helpers for this. |
| 2026-09-16 | 3.5 | `--skip-existing` defaults to `True` and `--plain-fallback` to `True`, matching the Setup-tab defaults. | Re-runs are idempotent and cheap (network skipped for already-tagged files); users who want to refresh tags opt in with `--no-skip-existing`. |
| 2026-09-17 | 4.1 | Implemented the `cd_ripper` migration immediately instead of filing a ticket, per the user's explicit choice; the plan's scope said "create migration tickets", but the previous violator (file_reorganizer, 2.3) set the precedent of migrating in-place. Only one live violator existed (`cd_ripper_prefs.json`, single flat key), so a ticket round-trip was pure overhead. | User approved "Audit + implement migration now" over "audit + file tickets only". The migration is small, guarded, and fully covered by tests; the stale `tempo_analyzer/tempo_config.json` was dead data (its `config.py` had already stopped reading it) and was simply deleted. |
| 2026-09-17 | 4.2 | No `# noqa: PLC0415` markers existed in `library_stats/core/file_processor.py`, so the plan's "remove markers" scope item was a no-op. | The current `[tool.ruff.lint]` config only selects E/W/F/I — PLC0415 (import-outside-top-level, an `E`/`PLC`-family rule under preview) is not enabled here, so no markers were ever needed or present. |
| 2026-09-17 | 4.2 | `test_library_stats.py` patches were rewritten wholesale from `audio_suite_shared.tag_helper_reader.read_*` to `library_stats.core.file_processor.read_*` (source-module → importing-binding). | Module-level imports rebind the names into `file_processor`'s namespace, so the pre-existing "patch at source" pattern (correct for function-local imports) silently no-ops after hoisting — the exact trap documented in AGENTS.md §7. `test_completeness.py` was left untouched because `completeness.py` still uses function-local imports, so source-module patching remains correct there. |
| 2026-09-17 | 4.3 | E501 re-enabled at the global AGENTS.md-mandated **88 chars** (strict PEP 8), not 100 (relaxed) or 120. | The global developer guidelines mandate max 88; adopting 100/120 would contradict standing policy and require a second pass later. |
| 2026-09-17 | 4.3 | `user_guides/` generator sources were included in the line-length enforcement (716 of 863 fixes). | CI's `ruff check .` scans the whole repo with no per-file excludes, so leaving guides un-wrapped would fail the installed gate; the extra code is doc-generation plumbing, not user-facing content. Value-preserving wraps only. |
| 2026-09-17 | 4.3 | E501 wraps are manual only; `ruff format` cannot join split strings and Ruff's E501 fixer is not autofixable. | Verified empirically: `--fix --unsafe-fixes` leaves all 863 findings standing and `ruff format --check` reports "711 files already formatted". Manual implicit-adjacent-literal continuation + reflowed comments/docstrings are the only correct mechanism. |
| 2026-09-17 | 4.3 | One E501 fix touched the dead file `mood_analysis_batch_tagger/_/_init/_/_.py` (docstring reflowed with an added newline — byte value changed slightly). | The file is a 217-byte stale duplicate of `__init__.py` imported by nothing (verified via grep across the tree); a cosmetic newline in a reflowed docstring for unloaded dead code is acceptable, and the file itself is a candidate for deletion. |
| 2026-09-17 | 4.4 | Guide registration gaps and the `album_art_sync` filename drift were implemented now (not ticketed). | `open_help()` "Unknown help guide"/file-not-found warnings are the exact "broken Help button" class §8 says to fix in the same change; the map entries are additive and covered by new regression tests in lockstep. |
| 2026-09-17 | 4.4 | Kept the registered map key `Album_Art_Synchronizer_User_Guide.docx` (matching `app.py` HELP_GUIDE) and aligned the generator output + regenerated docx to it, deleting the stale `Album_Art_Synch_User_Guide.docx`. | Two call-site sources (`app.py` + `guide_to_program`) already agreed on `Synchronizer`; changing both to `Synch` would be a larger diff. The generator was the lone outlier. |
| 2026-09-17 | 4.4 | `Tag_Field_Updater` / `File_Reorganizer` mappings added even though neither app declares a `HELP_GUIDE` or `_open_help`. | The AGENTS.md new-tool checklist requires registering the generated guide filename → folder for every registered tool; both have generators + `.docx` on disk and are registered tools, so the map entries complete the registration contract for any future Help wiring. |
| 2026-09-17 | 4.4 | No `pyproject.toml` version bump (remains 1.0.0). | 4.4 = internal doc/testing + registration-only changes with no user-visible feature delta; a release bump belongs to an actual release. |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| AcoustID API key requirement adds friction | Medium | Low | Document setup in user guide; offer offline fingerprint storage |
| mp3rgain binary not bundleable on Windows | Medium | Medium | ~~Fallback to pure-Python implementation or mark as optional dependency~~ (Resolved: pure-Python path chosen; `lossless_gain.py` replaces external binary) |
| mypy strict re-enablement surfaces many errors | High | Low | Phase 1.4 is explicitly scoped to fix all resulting errors — budget accordingly |
| Library stats refactor introduces regressions | Low | High | Comprehensive test suite exists; add regression tests for extracted helpers first |
| CUE sheet format edge cases (non-standard files) | Medium | Low | Start with strict spec compliance; add tolerance later if needed |
