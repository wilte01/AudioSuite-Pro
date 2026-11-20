# PLAN 2026-11-20 — Deduplication & Simplification Wave

**Status:** `[~] IN PROGRESS`

**Change class:** behaviour-neutral. Every item is a refactor, so entries go in
`TECHNICAL_CHANGELOG.md` only — never `CHANGELOG.md`.

**Target:** a technical release. `PLAN_2026-11-18_2.9.0_best_audio.md` is
`[~] CODE COMPLETE; RELEASE RUN OUTSTANDING` and closed to new items; this plan
owns the work below.

## Why this plan exists

A read-only review of 618 shipped modules (146,602 lines) ran a structural AST
clone scan (skeleton hash, ≥6 statements, shipped modules only) and found 27
cross-file clusters. The suite is already heavily consolidated — 2.4.1 ("stop
the drift") and 2.5.0 converged the format matrix, the FFmpeg resolver, the
filename set and the config pattern, and `tests/test_shared_code_reuse.py`
guards them. What remains is two specific patterns: a handful of helpers copied
verbatim into two modules, and a GUI layer that grew *additively* — four
parallel window bases and eight hand-written Tk pollers.

## Phase A — verbatim dedupe, behaviour-neutral

| Item | Change | Status |
|---|---|---|
| A1 | `UIHelperMixin._open_source_folder_standard()` in `audio_suite_shared/ui_helpers.py`; the 8 inline source-folder `_open_folder` copies call it. `open_folder_path` gains a `missing_message` parameter so source and target keep their distinct wording. | `[x]` |
| A2 | `_validate_lufs` moves beside `validate_target_lufs` in `audio_suite_shared/cli_dataclasses.py`. | `[x]` |
| A3 | One `find_upwards(filename, start)` in `audio_suite_shared/suite_paths.py`; `project_version.find_pyproject` and `whats_new.find_changelog` become thin wrappers. | `[x]` |
| A4 | `library_stats/cache_store.py` owns the key/BPM/decade classifiers; `core/file_processor.py` re-exports them, so both public paths still resolve. | `[x]` |
| A5 | New `audio_suite_shared/sqlite_helpers.py` holding `enable_auto_vacuum`; `undo_schema`, `cache_schema` and `duplicate_finder`'s cache call it. `_AUTO_VACUUM_FULL` stays resolvable from its old homes. | `[x]` |
| A6 | One `SecretStore(config_key, env_var, label)` in `audio_suite_shared/secret_store.py`; `audio_fingerprinter`'s two credential modules become bindings. | `[x]` |
| A7 | `BatchTransactionMixin` (`batch()` + `_commit()`) in `audio_suite_shared/sqlite_helpers.py`; used by `library_stats.library_cache` and `duplicate_finder.core.fingerprint_cache`. | `[x]` |

## Phase B — shared capability, behaviour preserved

| Item | Change | Status |
|---|---|---|
| B1 | `audio_suite_shared/event_pump.py`: `EventPump` owns the queue, drain, re-arm and cancel-on-close; the 8 pollers keep only their per-kind rendering. Preserves D136 — the worker thread never touches `root`. | `[x]` |
| B2 | `audio_formats.export_segment(audio, destination, template)` for the `get_export_args` + `preserve_depth_params` + `export` triple. **Audio-correctness class**: the depth pin (F-10/D-13) becomes one implementation, with a test that decodes the output and measures sample depth. | `[x]` |
| B3 | Shared analysis-CLI parser + Click command factory; `key_detector` and `mood_analyzer` become bindings, each keeping its command name, payload tag and docstring. | `[x]` |

## Phase C — simplification, judgement calls

| Item | Change | Status |
|---|---|---|
| C1 | Converge the four parallel window bases onto `SuiteApp`, staged: first the legacy bases delegate their help/log/folder/progress seams (A1 delivers the folder half), then tools migrate one at a time with `test_suite_app_contract` green throughout. | `[~]` (stage 1 complete — seams and the eight tool renderers; stage 2 ordered in D8) |
| C2 | `_scope_prefix` / `_path_prefix` → one trailing-separator normaliser in `audio_suite_shared/sqlite_helpers.py`. | `[x]` |
| C3 | `_one_line` (`launch_failure`, `run_outcome`) → one shared truncation helper. | `[x]` |
| C4 | `missing_dependency_reason` (`rnnoise_engine`, `demucs_engine`) — share only the probe, keep the per-engine messages. | `[ ]` (optional; not touched — the shared part is one `importlib` probe, so the copy is cheaper than the indirection) |

## Explicitly out of scope

- `get_ffmpeg_params` (`music_format_converter/core/ffmpeg_params.py`) — the
  if/elif chain encodes encoder *policy*, not duplication.
- `tag_helper_apev2` / `tag_helper_vorbis` `set_raw_tags` — the Vorbis handler is
  bound by the FLAC rebind trap (*Domain Correctness Traps*).
- Analysis/DSP calibration paths (D137–D139, D144) — rate- and window-dependent
  and release-blocking.

## Locks that moved (updated deliberately)

`tests/test_public_api_paths.py`, `tests/test_shared_code_reuse.py`,
`tests/test_callback_payload_contract.py`, `tests/test_suite_app_contract.py`,
`tests/test_completion_seam.py`, plus the per-tool `_open_folder` tests whose
patch target moved from the tool module to `audio_suite_shared.ui_helpers`.

## Decision Log

| ID | Date | Decision | Evidence |
|---|---|---|---|
| D1 | 2026-11-20 | `open_folder_path` gained a `missing_message` parameter instead of a second function: the source and target variants differ only in one sentence, so one implementation with an explicit message keeps both intents while removing the copy. | `audio_suite_shared/ui_helpers.py` |
| D2 | 2026-11-20 | `SecretStore.load`/`save` take the caller's `key_manager` and config accessor rather than importing `suite_config` themselves: `audio_fingerprinter`'s tests patch those names on the *tool* module, and the resolution order is the shared part, not the accessor. | `audio_suite_shared/secret_store.py`, `audio_fingerprinter/tests/test_api_key.py` |
| D3 | 2026-11-20 | `file_processor` re-exports the classifiers from `cache_store` in the redundant-alias form, so `library_stats.library_stats`, `library_cache` and the two test modules that import them keep resolving. | `tests/test_public_api_paths.py` `CACHE_NAMES` |
| D4 | 2026-11-20 | `duplicate_finder`'s third copy of `_enable_auto_vacuum` (found during A5, beyond the two the review listed) also calls the shared helper; the review's count was two because the third is a `@staticmethod` on the cache class. | `duplicate_finder/core/fingerprint_cache.py` |
| D5 | 2026-11-20 | The Click command factory takes an explicit hyphenated command name. Click derives a command name by lower-casing the function name and turning underscores into hyphens, and an explicit `name=` bypasses that: passing `name="mood_analyzer"` registered a command the documented `mood-analyzer` invocation could not reach, and seven CLI discoverability tests failed. | `audio_suite_shared/analysis_cli.py`, `mood_analyzer/cli.py`, `audio_suite_shared/tests/test_cli_app.py` |
| D6 | 2026-11-20 | The shared usage label is `_USAGE_LABEL`, not `TOOL_NAME`. `test_undo_gui`'s undo-log scan collects any `TOOL_NAME = "..."` assignment as a tool id and requires a display name for it, so a constant by that name in a CLI module invented two phantom ids. | `audio_suite_shared/tests/test_undo_gui.py` |
| D7 | 2026-11-20 | C1's stage 1 is finished and stage 2 is not part of this wave. The four bases now share the help/log/folder and progress-tick seams (`_render_progress_standard`; `BaseSuiteApp._open_folder` through `open_folder_path`), but `SuiteApp` is a batch-transformer shell — source to output, `_out_dir`, a Results completion — and the fifteen unmigrated tools process in place, so adopting it would give each a second shell variant, which WP-8 forbade; WP-8 also scoped adoption to the three largest composers deliberately. Each remaining migration is its own commit with its own visual review, so it stays a follow-on program. | `audio_suite_shared/ui_helpers.py`, `audio_suite_shared/app_bootstrap.py`, `tests/test_suite_app_contract.py` |
| D8 | 2026-11-20 | Stage 2's order, from the shell's contract (a Setup panel, the shared Processing/Results tabs, a run report and an output target); stage 2 itself remains out of this wave per D7. Wave 1, already on `BaseSuiteApp` with all three tabs and a report: `stem_separator` (a true transformer, owns `_out_dir`), `album_art_normalizer`, `metadata_scrubber`. Wave 2, hand-built three-tab windows, closest to the shell first: `album_art_sync` (already calls the shared tab builders), `genre_sync`, `tempo_analyzer`, `replaygain_analyzer`, `bpm_analyzer`, `lyrics_manager`, `asx_extractor`, `mood_analysis_batch_tagger`, `audio_fingerprinter`. Wave 3, needs a shell capability before adoption: `album_genre_tagger` (two-phase progress and a coverage-fail completion), `audio_refinery` (its Processing tab hosts the per-worker panels and it reads `_tab_processing`/`_tab_results`), `spectral_viewer` (an image viewer, no run report), and the interactive-grid tools on a shared base (`duplicate_finder`, `tag_editor`, `tag_field_updater`, `restoration`) plus `key_detector`/`mood_analyzer` (already on `AnalysisAppBase`, so the move is lateral until the bases converge). Not candidates: `cd_ripper` (a disc source, not a folder) and `undo_tag_edits` (`audio_suite_shared/undo_gui.py`, a restore browser with no run). That is 22 off-shell tool windows; D7's "fifteen" predates later tools. | the manifest table in `audio_suite_shared/tool_plugin.py`; each window's base class and `notebook.add` tabs; `_log_path`/`_out_dir` assignments |
