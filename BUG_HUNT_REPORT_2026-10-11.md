# AudioSuite-Pro — Bug Hunt Report (2026-10-11)

Read-only investigation. No source files were modified. Every finding below was
independently verified by reading the cited code paths (subagent leads were
re-checked and, where wrong, corrected — see "Corrections to leads").

Severity: **HIGH** = data loss/corruption or a documented feature that silently
does nothing; **MEDIUM** = wrong result/UX or a contract violation under common
conditions; **LOW** = edge case, misleading message, or cosmetic.

---

## HIGH

### H1 — ReplayGain peak tags written in dBFS instead of linear amplitude
- Evidence:
  - `replaygain_analyzer/core/ffmpeg_metrics.py:108` parses true peak as
    `Peak: <x> dBFS` and returns it as a plain float (`:111,122`).
  - `replaygain_analyzer/core/file_processor.py:176`
    `track_peak_str = f"{file_data['peak']:.6f}"` — formats the **dBFS** value.
  - `replaygain_analyzer/core/gain_calculator.py:23,42` album peak = `max(...)`
    of the same dBFS values; `file_processor.py:157-163` formats it the same way.
  - `replaygain_analyzer/core/tag_writer.py:59,61` docstrings state the contract
    is linear (`'0.912345'`), and `:73-74` write `REPLAYGAIN_TRACK_PEAK` /
    `REPLAYGAIN_ALBUM_PEAK` from those strings.
- Wrong outcome: a peak of `-0.5 dBFS` is written as `"-0.500000"`; the
  ReplayGain convention (foobar2000, loudgain, metaflac / `--replay-gain`) is a
  linear sample value in `0.0–1.0` (here ≈ `0.944`). ReplayGain-aware players
  will apply an incorrect clipping guard; some will reject/ignore the field.
- Impact: tag-level interoperability corruption on every run (audio bytes
  untouched).

### H2 — `silence_trimmer` overwrites a fully-silent file with an empty file
- Evidence:
  - `silence_trimmer/core/trimmer.py:67-95`: for a wholly silent file
    `start_trim == end_trim == len(audio)`, so `total_trim == 2*len(audio)`
    (passes the `total_trim == 0` guard at `:73`), then
    `trimmed = audio[start_trim : len(audio) - end_trim]` = `audio[len:0]` → an
    **empty** `AudioSegment` (pydub returns an empty segment, not `None`).
  - `silence_trimmer/core/file_processor.py:138`
    `if not is_dry_run and result.has_silence and result.trimmed is not None:`
    → true for the empty segment, so it exports an empty file and
    `shutil.copy2(temp_output, full_path)` at `:146` replaces the original.
- Wrong outcome: the source audio is destroyed (silence replaced by empty),
  with a `trim_edit` undo snapshot recorded as if a real trim happened.
- Impact: irreversible-looking data loss (only recoverable via undo log).

### H3 — Master-Driver argv is silently ignored by four GUI tools
- Evidence (driver side, all verified):
  - `master_driver/runner/arg_builder.py` builds real argv for each tool — e.g.
    `file_reorganizer` (`_build_utility_tool_args`, plus `--output-dir`,
    `--action`, `--specific-pattern`, `--various-pattern`),
    `tag_field_updater` (`[path, mode_flag, start_flag, end_flag]`),
    `library_stats`, `cd_ripper`.
  - `master_driver/batch_orchestrator.py:517-519` →
    `_launch_standalone` → `start_python_script(script_path, args)` (`:227`);
    `BatchStep.from_spec` sets `script_path = manifest.pyw_filename` (`:86-87`).
  - The receiving launchers drop argv:
    - `File_Reorganizer.pyw` → `file_reorganizer/__init__.py::main()` →
      `file_reorganizer/app.py::main()` (`:644-647`, takes **no** parameters,
      parses no argv; app reads `suite_config.load_last_directory()` /
      `load_settings` instead).
    - `Tag_Field_Updater.pyw` → `tag_field_updater/ui/app.py::main(directory=None)`
      (`:289-309`, no argv parse).
    - `Library_Stats.pyw` and `CD_Ripper.pyw` construct their app object with no
      arguments (`CD_RipperApp(root)`, `LibraryStatsApp(root)`).
  - Control: `Tag_Editor.pyw` and the tool-local `utils/cli_args.py` parsers DO
    consume argv, proving the convention is "consume", not "ignore".
- Wrong outcome: driver card settings for these four tools (target directory,
  action, output dir, patterns, mode) never reach the launched app. In
  sequential batch mode the user must re-enter everything by hand after launch.
- Impact: batch orchestration is a no-op for a quarter of the utility tab.
- Note: `album_art_sync`'s `--size` variant is tracked separately as M3, and
  `album_art_normalizer` as M3 below.

---

## MEDIUM

### M1 — `album_art_sync.resolve_and_apply` can return `None` (violates its return type)
- Evidence: `album_art_sync/core/pipeline.py:88` is decorated
  `@handle_audio_errors(reraise=False, context=...)`; the decorator returns
  `return_on_error` (default `None`) on **any** exception
  (`audio_suite_shared/exceptions.py:489-497`). The function is annotated
  `-> ArtSyncReport`. `album_art_sync/cli.py:82` then reads
  `report.total_files` → `AttributeError: 'NoneType' object has no attribute
  'total_files'` when any error escaped the body.
- Wrong outcome: instead of a clean error report, the CLI/headless caller
  crashes with an unrelated `AttributeError`.
- Impact: driver headless runs and `--json` output fail opaquely on any internal
  error.

### M2 — `album_art_normalizer` driver `--size` is never consumed
- Evidence: `arg_builder.py:224-232` emits
  `[path, "0", mode_flag, start_flag, end_flag, "--size", state.art_normalizer_size.get()]`.
  `album_art_normalizer/utils/cli_args.py:32-45` `ACCEPTED_HANDSHAKE` contains no
  `--size`, and `apply_handshake_segment` (`:142`) only consumes accepted tokens;
  `AlbumArtNormalizerArgs` has no size field. `app.py:144-164` `_apply_cli_args`
  never sets `self.resolution`.
- Wrong outcome: the driver's "Art Normalizer size" setting has no effect; the
  app always uses its own default resolution.
- Impact: silently wrong output dimensions in batch runs.

### M3 — Saved window geometry with negative coordinates never restores
- Evidence: `audio_suite_shared/platform_utils.py:267`
  `parts = saved.split("+")`. Tk emits `WxH±X±Y`, using a literal `-` for
  negative X/Y (e.g. `800x600-1920+40`). For any saved string with a negative
  X or Y, `split("+")` yields < 3 parts (or a non-numeric middle), so the
  `len(parts) >= 3` gate at `:268` fails and the window falls back to
  `_center()` (`:284-285`). The in-code comment's example `"800x600+-1920+40"`
  is not a format Tk produces.
- Wrong outcome: position is never restored on a left-side (negative X) or
  top-side (negative Y) monitor.
- Impact: UX only; no data loss. (Lead rated HIGH — downgraded.)

### M4 — `music_format_converter` collides same-stem files and overwrites with `-y`
- Evidence:
  - `core/file_processor.py:386-388`: `base_name = os.path.splitext(filename)[0]`,
    `output_name = f"{base_name}.{output_format}"`, output path joined onto
    `output_dir`. Subdirectories ARE preserved (discovery keeps the relative
    path, `core/formats.py:220-263`; `_convert_and_verify` creates the parent
    subdir, `:247-249`) — so the collision requires two files with the same
    stem and **different extensions in the same folder** (e.g. `song.flac` +
    `song.wav` in one directory), both targeting `song.mp3`.
  - `core/ffmpeg_params.py:177` passes `-y`, so the second run silently
    overwrites the first's output; `_convert_and_verify` only checks
    returncode/existence (`:280`), never pre-existence.
- Wrong outcome: one converted output is lost with no warning; with
  `delete_originals=True` both sources are deleted.
- Impact: silent data loss in a mixed-format folder.

### M5 — `file_reorganizer` overwrites an existing destination without warning
- Evidence: `file_reorganizer/core/engine.py:294-307` `_perform_action` calls
  `shutil.copy2` / `shutil.move` to `target` with no `os.path.exists(target)`
  check. `record_file_reorg_snapshot(source, target, action)` (`:300`) is taken
  before the write; it is not evident that the pre-existing target's content is
  captured (undo recoverability **not** independently verified here).
- Wrong outcome: an existing file at the resolved destination is silently
  replaced (and, if the snapshot only captures the source, cannot be restored).
- Impact: potential data loss during tag-driven reorganization.

### M6 — `lossless_gain` reports a valid, gain-saturated MP3 as "no valid frames"
- Evidence: `audio_suite_shared/lossless_gain.py:606-631` `_modify_mp3_gains`
  counts a frame as modified only if a gain field actually changed; fields are
  clamped to `[_MIN_GLOBAL_GAIN, _MAX_GLOBAL_GAIN]` (`:618`). A valid MP3 whose
  every frame is already at the clamp bound yields `modified == 0`, which
  `apply_track_gain:329-333` / `apply_album_gain:372-376` raise as
  `AudioFormatError("No valid MPEG Layer III frames found in: ...")`.
- Wrong outcome: a valid file is reported as unreadable instead of
  "no change / already at limit".
- Impact: misleading failure; batch marks a good file as errored.

---

## LOW

### L1 — Unreachable `FileNotFoundError` arm in the driver retry logic
- `master_driver/batch_orchestrator.py:489` catches `(PermissionError, OSError)`
  and `raise`s **before** the `except FileNotFoundError:` arm at `:495`. Since
  `FileNotFoundError` is an `OSError` subclass, `:495` is dead for the
  `run_python_script` path. A missing script is instead retried twice (2 s/4 s
  backoff, `retry_cfg:499-504`) and logged as "failed after retries" rather than
  "Script not found".
- Impact: wasted retries and a misleading log only.

### L2 — `library_stats` cache DB has no `auto_vacuum`
- `library_stats/library_cache.py:107-112` sets `journal_mode=WAL` and
  `busy_timeout` but never `PRAGMA auto_vacuum`. The cache issues `DELETE`s
  (`remove_orphans:238`, `clear_dir:251`, `clear_all:259`) and `INSERT OR REPLACE`
  (`:201`); freed pages are never returned to the OS, so a scan/re-scan workload
  grows the file monotonically (the documented suite-wide pattern).
- Impact: unbounded cache-file growth; no correctness impact.

### L3 — `resolve_and_apply` per-file embed catch is too narrow
- `album_art_sync/core/artwork_applier.py:100,119` catch only
  `(OSError, ValueError)`, but the shared `embed_artwork` is wrapped by
  `handle_audio_errors(reraise=True)`, which raises `AudioSuiteError` (a direct
  `Exception` subclass). A tag-embed failure therefore escapes the per-file try
  and (with M1) can abort the whole run.
- Impact: one bad file can fail an entire album (subject to M1's masking).

---

## Corrections to subagent leads (leads that did NOT hold up)
- **MFC "flattened output tree" collision** — not accurate: relative subfolders
  ARE preserved (`formats.py:220-263`, `file_processor.py:386-388`). The real
  collision is same-folder/same-stem/different-extension (M4).
- **`file_processor_base.run_parallel_processing` "timeout double-count"** —
  `future.result(timeout=...)` at `:389` runs on futures already yielded by
  `as_completed`, so the timeout cannot fire; no bug found.
- **`platform_utils` geometry "HIGH"** — real, but UX-only; downgraded to M3.

## Additional candidates NOT independently re-verified (from subagent passes)
Listed for follow-up; treat as unconfirmed:
- `library_stats`: cached-scan vs full-scan `total_files` disagree;
  `query_aggregate` docstring omits `bpm_distribution`; JSON payload lacking an
  `isinstance` guard.
- `music_format_converter`: delete-before-snapshot ordering;
  `_wav_params_for` "auto" docstring vs behavior.
- `cd_ripper`: partial-output left after failure; AccurateRip last-track window.
- `audio_suite_shared/logging_setup`: admin-filter re-apply guard.
- `audio_suite_shared/process_audio_file_inplace`: raw `str(exc)` propagation.

## Suggested priority
1. H1 (peak units), H2 (fully-silent overwrite), H3 (ignored driver argv).
2. M1 (None return), M2 (`--size`), M4/M5 (overwrite collisions).
3. M3, M6, L1-L3.
