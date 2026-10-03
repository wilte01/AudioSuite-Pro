# Independent Suite Audit — 2026-10-02 — AudioSuite-Pro

**Auditor:** independent re-audit, no prior-audit authorship
**Commit audited:** `c1daf1d` ("E5: close the second-lyrics-provider item as a recorded policy decision"), 2026-10-02
**Prior audit:** `AUDIT_2026-09-29_suite_report.md`, remediated by `PLAN_iteration7_remediation.md`
**Scope:** all first-party code (496 production files / 78,463 LOC; 287 test files), the verification gate, documentation hygiene, and a capability comparison against market leaders
**Changes made to the tree:** none — this is a read-only audit. All findings below are reproducible from the committed state.

---

## 1. Verdict

The suite is in genuinely excellent shape *for the properties the previous audits optimised*, and it keeps every one of them: six-command gate green, `mypy --strict` clean, 8,091 tests, 88% coverage, zero silent exception swallows, zero 0%-coverage modules, and a typing discipline that is genuinely rare.

The findings this audit raises are **not** regressions of the remediated classes. They are what is left after three remediation iterations: two **High** data-correctness defects that a green suite cannot see (one empirically reproduced below), three **High** threading violations in three separate apps, and a set of **Medium** items that are mostly *registry/contract drift* — places where a stated contract and the code disagree, which no compile or type gate can detect.

Two of the High findings were found by reading, and the third reproduced end-to-end. **The green suite is not evidence these do not exist** — that is the audit's central finding.

---

## 2. Gate results (re-measured, not inherited)

Commands per the documented Phase Gate, run on this commit from the suite root.

| # | Gate | Result |
|---|------|--------|
| 0 | `python -m compileall -q -f .` | exit 0 |
| 1 | `python -m ruff check .` | **All checks passed!** (783 files) |
| 1 | `python -m ruff format --check .` | 783 files already formatted |
| 2 | `python -m mypy .` | **Success: no issues found in 460 source files** |
| 3 | `bandit -r . -x ./.venv -c pyproject.toml` | **0 High / 0 Medium** (41 Low — the documented subprocess findings) |
| 4 | `python -m pytest -q` (bare) | **8091 passed, 3 skipped, 30 deselected in 210.20s** |
| 5 | `coverage report` (same command block) | **88%** — 28,174 statements, 3,415 missed (`fail_under = 75`) |

Structural measures also re-measured:

- **0** production modules at 0% coverage (iteration-7 D3 gate holds)
- **0** bare `except:`, **0** `contextlib.suppress` — the silent-swallow class is genuinely closed
- Exception handlers: 423 specific / 143 broad (`except Exception`); no unlogged, unraised, non-surfacing handler found outside documented best-effort sites
- `@dataclass(frozen=True)`: **74 / 114** (65%; was 55% pre-C1). `slots=True`: 0/114 (deliberately out of scope)
- Functions > 80 lines: **160** of 2,256 (GUI builders and CLI parsers dominate; the audio-write god-function class was closed by C3)
- Test hygiene: **123 class-scoped fixtures defined as instance methods across 30 test files**, and unclosed `sqlite3.Connection` warnings — see M9

---

## 3. Findings

Severity: **High** = incorrect output, data-integrity, or thread-safety defect in shipping code. **Medium** = stated contract contradicts the code, or a maintainability/dead-code class a maintainer would be surprised by. **Low** = hygiene.

Every High finding was verified by direct code reading, and three were additionally reproduced by execution.

---

### HIGH-1 — `audiosuite tag-update --dry` writes tags anyway (reproduced end-to-end)

**Class:** mode-flag contract violation — the exact defect class `AGENTS.md` ranks as release-blocking.
**Severity:** High

**The defect.** `tag_field_updater/cli.py:22` accepts `dry_run` and never passes it into the processor chain:

- `:35` calls `processor.scan_directory(directory)` — the signature (`tag_field_updater/core/processor.py:130-134`) has **no** dry-run parameter at all.
- `:48-49` sets `processor.stop_flag = True` **after** the scan has already completed. `stop_flag` is only consulted *during* the scan (`processor.py:157,161`) and is reset to `False` at the start of every call (`processor.py:151`) — so this is dead code that cannot affect the run.
- The write site is unconditional: `transformation_rules.py:117-119` — `record_tag_edit_snapshot(...)` followed by `audio.save()`. There is no dry-run gate anywhere in the seven transformation paths that call `.save()` (`:184, 243, 302, 361, 449, 543, 608`).
- The contract being violated is documented in the suite itself: `audio_suite_shared/cli_app.py` states *"`--dry` analyses and reports without writing."*
- The command even **reports** `dry_run: true` in its own JSON payload (`cli.py:41`) while having written.

**Reproduction (real MP3, real CLI):**

```
CLI exit: 0
stdout:   Files processed: 1 / Files updated: 1 / Errors: 0
tag before: 'Rock/Pop'
tag after:  'Rock; Pop'
WROTE IN DRY RUN: True
```

A `TCON` value containing `/` was rewritten on disk *and* an undo snapshot was recorded, under `--dry`.

**Compounding defect — the help text advertises a flag that does not exist.** `cli.py:27` documents `audiosuite tag-update /Music --dry-run`. Click registers only `--dry`/`--live`. Verified:

```
$ audiosuite tag-update C:/tmp --dry-run
Error: No such option '--dry-run'. Did you mean '--dry'?   (exit 2)
```

**Meta-finding — why the A1 gate did not catch either one.** `TestDocumentedFlagParity` (`audio_suite_shared/tests/test_cli_app.py:701-734`) enforces docstring↔flag parity by extracting bracketed `[--flag]` tokens (`:712`) and **skipping any block with none** (`:713-714`). This command's docstring carries only a plain-text `Examples:` block, so the whole command escapes the parity gate. The gate has a structural blind spot for command *examples* — and this defect shipped after A1.

**Why this class escaped the previous three iterations:** the per-tool CLI is the only writer path here (the GUI app has its own working dry-run flow), and `tag_field_updater/cli.py` sits at **48% coverage** — the 2nd-lowest CLI in the suite. The one surface that would have exercised it is the one surface with almost no tests.

**Recommendation:** thread `dry_run` through `scan_directory` → `process_file` → every `process_*_file` save site (the suite already has this exact pattern in `metadata_scrubber`, whose "dry run never persists tag_prefs" is a regression test); fix the help example; extend the parity test to parse `Examples:` lines. Add a real-file outcome test (no `.save()` call, source bytes unchanged, no undo row).

---

### HIGH-2 — `cd_ripper` writes a structurally wrong CUE sheet (audio artifact incorrect)

**Class:** output-artifact correctness. **Severity:** High

`cd_ripper/core/ripper.py:403-418`. The ripper produces **one output file per track**, then groups the finished paths by directory and builds the sheet:

```python
specs: list[TrackSpec] = []
for num, _path in entries:
    ...
    specs.append(TrackSpec(number=num, title=title, performer=artist))
cue_text = build_cue(
    ...,
    files=(
        CueFileSpec(
            filename=os.path.basename(_path),   # ← consumed AFTER the loop
            tracks=tuple(specs),
        ),
    ),
)
```

Three compounding errors:

1. **`_path` is read after the loop.** The underscore prefix marks it "unused" (`R10`) — the convention itself is what hid this. At `:414` it holds the **last** entry's path, so the sheet names one `FILE` (the last track's file) for the whole album.
2. **All tracks go inside that one `FILE` block.** For a track-per-file rip the sheet must carry one `CueFileSpec` per track.
3. **`TrackSpec.start_ms` defaults to `0`** (`audio_suite_shared/cue_generator.py:58`) and the ripper never sets it — so every track renders `INDEX 01 00:00:00`.

Net result: an N-track rip yields a sheet describing N tracks inside the last track's file, all at offset zero. Any cue-aware player or splitter (the suite's own `cue_cli.py`/`cue_split.py` resolves a sheet's `FILE` to an on-disk image) will treat the last track's file as the source for the entire album. The docstring at `ripper.py:374-379` asserts the opposite — *"the generated sheet always matches the audio on disk"* — so the code documents a guarantee it breaks.

**Why the suite is green:** the existing test (`cd_ripper/tests/test_ripper_core.py:1187-1188`) asserts only `"FILE " in text` and `count("INDEX 01") == 2`. It never pins the per-file structure or the filenames, so a sheet with 1 `FILE` line and 2 `INDEX` lines passes. This is the `AGENTS.md` "a test that asserts a side effect does not happen is a bug in waiting" pattern inverted: the test asserts a *substring* rather than the structure the artifact must have.

**Recommendation:** build one `CueFileSpec` per entry (filename from that entry's path); strengthen the test to assert `FILE` count == track count and that each `FILE` names a file that exists on disk; re-check `cd_ripper`'s guide for a claim about single-image sheets.

---

### HIGH-3 — Tk widgets mutated from worker threads in two tools; one carries a false safety claim

**Class:** thread safety. **Severity:** High

`AGENTS.md` and the suite's own `file_processor_base` contract state that progress/complete callbacks fire on worker threads and **must** be marshalled to the Tk main thread. Most tools do. Two do not, in ways that are structurally invisible to the test suite because Tk is mocked.

**`album_genre_tagger/app.py`** — `:256` spawns `threading.Thread(target=self._run)`. Inside `_run`, from the worker:

- `:267` `self.progress["value"] = 0`
- `:268` `self.file_listbox.insert(...)`
- `:293-301` `_on_phase1_progress` mutates `self.progress` — under the comment *"# ── Callbacks (called from background thread) ──"* (`:282`) — with no `root.after` anywhere in the class
- `:312-329` `_on_coverage_fail`, `:331-334` `_on_phase2_progress`, `:349-375` `_on_complete` — same violation, plus `self.run_mode.get()` read from the worker (`:263`, `:352`)
- `:377-379` `_on_error` calls `messagebox.showerror` **directly** — a modal dialog raised on a non-main thread

Sibling tools (tempo, noise_reduction, audio_enhancer, replaygain) all marshal correctly; this module's docstring simply omits the thread-safety statement its siblings carry.

**`album_art_sync/app.py`** — `:311` `threading.Thread(target=self._run_logic, daemon=False)` (every other app uses `daemon=True`; here a window closed mid-run leaves the process alive while the worker blocks on the art picker). From the worker: `_add_log` (`:315-320`) does `log_list.insert` / `see` / `update_idletasks`; plus `status_txt.set` (`:385,427`), `progress.config` (`:429,433`), `res_msg.config` (`:412,422,450,453`), `notebook.select` (`:413,423,464`), `start_btn.config` (`:344,354,372,416,468`), and Tk var reads (`:337,442-443`).

The section header at `:313` reads:

```
# ── Logging (thread-safe via update_idletasks) ─────
```

`update_idletasks()` does **not** make cross-thread Tk access safe. The claim is false, and it is worse than the omission would be — it tells the next reader the hazard was considered. Tellingly, the *same file* already contains the correct pattern: `_on_pick` (`:324-329`) documents and uses `PickerDialog.show_threadsafe()`, which schedules onto the main thread and blocks the worker until the user responds. The correct seam is three functions away.

**Practical severity note (honest scoping):** CPython's `_tkinter` serialises most Tcl calls, so these usually manifest as interleaving and re-entrancy rather than an immediate crash — but Tkinter is officially not thread-safe, the modal-from-worker case can deadlock against the main loop, and both are the class of bug that is trivial to fix now and expensive to diagnose from a user's crash report later.

**Recommendation:** marshal through `root.after(0, …)` as the sibling tools do; give both modules the thread-safety docstring section the rest of the suite carries; delete the false claim; align `daemon=True`. Add a regression test that asserts the callbacks *schedule* rather than execute (positive assertion — "the deferred callback is scheduled", not "no call happened").

---

### HIGH-4 — Master Driver re-reads ~40 live Tk variables on the launch thread, contradicting its own snapshot policy

**Class:** dry-run/live correctness (release-blocking class per `AGENTS.md`). **Severity:** High

`master_driver/tool_launcher.py:95-97` states the intent plainly:

```python
# Snapshot tkinter variables on main thread before spawning daemon thread
snapshot_clear_logs = state.clear_logs_var.get()
snapshot_source = state.refinery_source.get().strip()
```

Only two variables are snapshotted. The thread target (`_run_refinery`, `:117-126`) then calls `arg_builder.build_refinery_args(state, config)` **on the daemon thread**, and the arg builder reads the live widget state directly — `state.dir_path`, `state.global_mode`, `state.module_toggles[...]`, and every per-tool control (`arg_builder.py:52-55, 60, 191-194, 374-375`). The same pattern repeats for the enrich and utility launchers (`:222`, `:342`), and `module_runner.py:104` calls `toggle.get()` on the worker too.

The snapshot parameters feed **only** the log-clear path. The emitted argv — including the `--live`/`--dry` token — is re-derived from live variables after the thread starts. An edit made while a batch is launching can flip the mode of the run in flight. This is precisely the failure `AGENTS.md` ranks highest: *"a mode the app computes and passes … silently does nothing"* and its mirror, *a mode that can be changed after it was computed*.

**Why the suite is green:** the existing tests call `build_*_args` directly with a stub state. Nothing exercises the *thread boundary*, because nothing asserts that the boundary exists.

**Recommendation:** build the argv on the main thread and pass the finished list into the thread — the snapshot already exists, it is simply two variables wide instead of the whole set. Add a test that mutates a state variable between snapshot and thread start and asserts the emitted argv is unchanged (positive contract: "the argv emitted from the snapshot").

---

### MEDIUM findings

#### M1 — The production-dead legacy argparse subsystem in `cli_helpers.py` (~300 lines, ~40% of the file)

`cli_helpers.py:239-535` — `create_standard_parser`, `parse_cli_args`, `validate_cli_args`, `apply_stage_args`, `StandardCLIHandler`, `SourceOutputCLIHandler` have **zero production call sites**. Every `.pyw` launcher imports `audio_suite_shared.launcher.parse_cli_args` instead; every per-tool `utils/cli_args.py` uses only the handshake helpers plus `UniversalCLIHandler`. Only `audio_suite_shared/tests/test_cli_helpers.py` exercises them.

Two consequences: (a) ~300 lines of first-party code is maintained, reviewed and type-checked for nothing; (b) **a name collision** — `cli_helpers.py:468` and `launcher.py:21` both define `parse_cli_args` with different semantics (argparse-based vs. launcher-wrapping). An import from the wrong module compiles cleanly and does the wrong thing.

Its defaults have also drifted from reality (`--sensitivity` default 5.0 at `:291-295` while the declick engine's domain is 0.0–0.4 — `audio_refinery/cli.py:36-40`; `--threshold` −40.0 vs −50; `--fade-in` 100 vs 500; `--tolerance` 1.0 vs 0.5). Dead code that has drifted is worse than no code, because it reads as authoritative.

*Recommendation: delete the subsystem and its tests; keep `UniversalCLIHandler`. Rename one of the two `parse_cli_args` regardless, while both exist.*

#### M2 — Dead symlink-detection branch, and a docstring documenting a security control that cannot run

`audio_suite_shared/security/input_validator.py:167` computes `resolved = declared.resolve()`; `:175` tests `resolved != declared.resolve(strict=False)`. `Path.resolve()` defaults to `strict=False`, so **both sides are the identical computation** — the condition is always `False` and the `logger.warning` at `:185-189` is unreachable.

The docstring at `:149-155` documents behaviour that does not exist: *"detects symlinks that resolve to locations outside the user's home directory … permitted with a logged warning."* A documented security control that silently never runs is worse than an absent one, because a reader trusts it.

*Recommendation: decide the intent. Either compare against the *unresolved* path (`Path(dir_path)` vs `resolved`) to make the branch real, or delete the branch and the docstring paragraph.*

#### M3 — Two sources of truth for supported extensions, already drifted

`input_validator.py:270-279` hardcodes `{.mp3, .flac, .wav, .ogg, .m4a, .aiff, .aif, .wma}`. The suite's declared set is `audio_formats.SUPPORTED_EXTENSIONS` = `(.mp3, .flac, .ogg, .m4a, .mp4, .opus, .wav, .aiff, .aif)`.

The security list **rejects `.mp4` and `.opus`** (formats the suite supports and converts) and **accepts `.wma`** (which the suite does not support). `validate_audio_file_path` is the gate the subprocess launchers consult.

*Recommendation: import `SUPPORTED_EXTENSIONS`; add a test asserting the validator's set equals the suite's set, so the next format addition cannot drift.*

#### M4 — `CHANGELOG.md` `[Unreleased]` is empty after a release-sized iteration

The file declares Keep-a-Changelog + SemVer compliance, yet `[Unreleased]` (line 10) contains nothing while the tree has gained: always-on TPDF dither + `soxr` resampling with a `--no-dither` opt-out (E1), MusicBrainz identifier writing (E2), Cover Art Archive as first art source (E3), recursive mixed-format conversion (E4), the tag-helper split (C2), the `process_file` decomposition (C3), and the whole duplication class (B1–B5). Every one of those changes user-visible behaviour — and the converter's change to dither alters **every converted file's bytes**.

*Recommendation: write the entries. The dither change in particular deserves a `### Changed` note with the migration advice (re-run undo-aware workflows; output bytes changed).*

#### M5 — `noise_reduction` ↔ `pop_click_remover` duplication is still open (~0.79)

Iteration-7 item B4 consolidated `bpm_analyzer` ↔ `lyrics_manager` behind `tool_app_base.AnalysisTagToolApp` and explicitly deferred this pair to "this item's named follow-up." It was never scheduled. `tool_app_base.py:5-6` documents the exact pattern to follow.

Measured on the current tree: 449 vs 406 lines; `git diff --no-index` = 64 insertions / 107 deletions, i.e. **~342 lines common in place** (~0.76–0.84 depending on metric — consistent with the prior audit's 0.788). Verbatim-identical blocks include the imports, the driver-mirrored var block, the worker slot pool, last-directory restore, the `_build_ui` skeleton, the preset handlers, the `_apply_cli_args` skeleton, browse, `_on_progress`, `_update_progress_ui`, `_on_complete` (differing only in "Reduced" vs "Succeeded"), `_on_error`/`_open_help`/`_open_log`/`_open_folder`, and `main()`.

*Recommendation: second customer of `AnalysisTagToolApp`, following B4's own playbook — lock first, extract in one commit, delete duplicates in the next. This is the last named duplication follow-up in the plan; closing it retires the class.*

#### M6 — Two parallel batch engines with duplicated helpers

`batch_orchestrator.py:5-6` claims it *"Replaces the simple sequential loop in module_runner.py."* It did not: `module_runner.py:173-282` still carries its own sequential loop, its own `_emit_progress` (`:332-382`) and its own `_launch_standalone` (`:398-447`), duplicating `batch_orchestrator.py:449-516` and `:431-447`. Two implementations of progress semantics and standalone launching must be kept in sync.

#### M7 — Parallel mode reports never-run tools as "completed"

`batch_orchestrator.py:298-307`: the comment says *"Mark audio_refinery as standalone; skip parallel execution"*, but the code skips **every** `manifest.standalone` step, adds it to `completed`, and increments `completed_count` — a tool that never ran is reported complete. `skipped_count` (`:299,307`) is incremented and never read. Sequential mode behaves differently (it launches standalone tools and waits, `_launch_standalone`), so the two modes disagree on what a batch does.

#### M8 — A not-found module displays as "completed"

`module_runner.py:213-221`: the not-found branch calls `on_error(...)` and `continue`s without appending to `failed_steps` and without emitting the post-step status line. The index-based status mapping at `:358-368` (`elif i < completed_steps: "completed"`) then mislabels it: specs `[A not-found, B ok]` renders A as **completed** once B finishes.

#### M9 — Test-hygiene debt that will break on the next pytest major

**123 class-scoped fixtures defined as instance methods across 30 test files.** pytest already emits `PytestRemovedIn10Warning` on every affected class (46 warnings in the bare run); under `-W error::pytest.PytestRemovedIn10Warning` the suite errors out immediately. Concentrated in `master_driver/tests/test_ui_cards.py` (26 `_import` fixtures), `audio_suite_shared/tests/test_ui_common.py` (14 `setup_tk`), `tempo_analyzer/tests/test_tempo_schemes.py` (8), plus `audio_refinery`, `noise_reduction`, `silence_trimmer`, `pop_click_remover`, `replaygain_analyzer`, `audio_enhancer` and others.

Also in the warning stream: unclosed `sqlite3.Connection` `ResourceWarning`s from tests that call `log._connect()` / `cache._connect()` without closing (`audio_suite_shared/tests/test_batch_undo.py:183-192`, `library_stats/tests/test_library_cache.py`), plus two `librosa` warnings from short analysis fixtures. Production SQLite handling is exemplary; this is test-side only.

*Recommendation: mechanical migration (move the fixture to module scope or make it a `@staticmethod`), tracked as its own item before the next dependency bump. The unclosed connections should close in a fixture finaliser.*

#### M10 — Coverage floors: six GUI `app.py` modules remain below 60%

No module is at 0% (D3's gate holds) and no GUI `app.py` is below 40% (also D3's gate). But the band below 60% is wide, and the ordering is worth recording: `tempo_analyzer/app.py` **44%** (119 missed), `album_genre_tagger/app.py` **45%** (104), `audio_enhancer/app.py` **47%** (122), `asx_extractor/app.py` **52%** (78), `album_art_sync/app.py` **53%** (129), `tag_editor/ui/app.py` **57%** (91). Non-GUI modules sit at 93–99% for the same code paths.

Two of these six — `album_genre_tagger` and `album_art_sync` — are the two apps carrying High-3. Their coverage is low *because* the offending worker-thread code is the part the tests skip, which links the coverage gap directly to the defect: a test that drove `_on_complete` from a worker would have to marshal it, and would have surfaced the violation.

Also low: `cd_ripper/core/drive_handler.py` 40% and `cd_ripper/ui/rip_tab.py` 41% (hardware-gated — expected, and the `pytest -m hardware` opt-in is documented), `asx_extractor/ui/processing_tab.py` 29%, `tag_field_updater/cli.py` 48% (the surface carrying High-1), `genre_sync/cli.py` 56%, `noise_reduction/cli.py` 67%.

#### M11 — Registry drift: three manifest ids absent from the declared dependency graph

`tool_plugin.py:155-158` designates `batch_orchestrator.DEPENDENCY_GRAPH` as an agreement point every id must appear in. `master_driver/batch_orchestrator.py:123-147` lists 23 ids, missing **`mood_analyzer`**, **`noise_reduction`** and **`tag_field_updater`**. They still run (`_collect_deps` defaults to `[]`), so this is a contract-completeness gap rather than a live failure — but the graph is the thing that keeps enrich→utility ordering correct as tools are added.

*Recommendation: an AST/registry test asserting `set(manifest ids) ⊆ set(DEPENDENCY_GRAPH keys ∪ {intentionally excluded})`, with the exclusions named.*

#### M12 — Refinery driver: select-all misses a stage; display flags read the wrong tab's variables

- `master_driver/app.py:362-366`: refine `_toggle_all` iterates `["declick","trim","enhance","normalise"]`, while `arg_builder.py:377-383` and `audio_refinery/ui/setup_tab.py:267` include **`reduce_noise`**. Select-All on the REFINE tab never enables Noise Reduction.
- `arg_builder.py:445` emits `_driver_display_flags(state.util_clear_logs_var, state.parallel_var)`, but the refine tab binds `state.clear_logs_var` (`app.py:354`) and `launch_refinery` snapshots `state.clear_logs_var` (`tool_launcher.py:96`). The child's inert Run Controls panel therefore displays the **utility** tab's Clear Logs state.
- The refine tab hides the parallel checkbox (`app.py:387-391`) while `--parallel-run/--no-parallel-run` is still emitted.

#### M13 — `build_refinery_args` silently re-enables every stage when the user disabled them all

`arg_builder.py:384-386`: `if not active_stages: active_stages = "declick,trim,enhance,normalise"`. A user who turns off all stages gets the full default chain. Currently unreachable via `launch_refinery` (which blocks no-stages first at `tool_launcher.py:76-93`), so it is dead code *and* a surprising contract — if the guard is ever relaxed, the surprise ships.

#### M14 — Fingerprinter: loose status strings and a duplicated tag-write block

Statuses are bare strings (`"ERROR"`, `"MATCHED"`, `"TAGGED"`, `"NO MATCH"`, `"LOOKUP SKIPPED"`, `"ANALYSED"`, `"ALBUM AMBIGUOUS"`, `"TAG WRITE FAILED"`) scattered across `_result_display` (`:76-84`), `_summarise_results` (`:349-377`), `_run_album_phase` (`:583-641`) and log building (`:786-802`). `cd_ripper` by contrast uses a `VerificationStatus` enum — the suite already knows the better pattern. Additionally `:305-339` (`_process_file`) and `:419-460` (`_finalize_album_file`) are near-identical write-acoustid-tags + write-MBIDs + result-construction blocks.

#### M15 — Dead code still shipped in production paths

- `audio_refinery/ui/setup_tab.py:38-84` — `_ENHANCE_PRESETS`, 47 lines, **never used** (the file uses the shared `PRESETS` from `audio_suite_shared.dsp_models` at `:614`): duplication *and* dead.
- `audio_refinery/ui/setup_tab.py:386-388` — `_sync` defined, never bound (it would create unparented Tk vars if it ever ran).
- `audio_refinery/core/file_processor.py:41-76` — `check_integrity_batch` has no production caller.
- `audio_fingerprinter/core/file_processor.py:756` — `slot_idx = i % processor.max_workers` and the `_FingerprintJob.processor` field are dead; `_fingerprint_worker` re-derives the slot from `job.slot_queue` (`:114`).
- `master_driver/runner/module_runner.py:110-133` — legacy str-spec path, `_SENTINEL_MAP` built **inside** the loop (`:112`); no production caller builds str specs.
- Write-only attributes: `_dir_path` in four apps (`tempo_analyzer:79,331`, `album_genre_tagger:66,264`, `lyrics_manager:100,405`, `replaygain_analyzer:68,312`), `_output_dir_final` (`music_format_converter:81,565`), `_reset_ui` (`music_format_converter/app.py:344-349`), and `self.style` stored-but-unused in eight `app.py` files.
- `cli_helpers.py:661-662` — `hasattr(self.app, "scheme")` can never be true for `TempoAnalyzerApp` (its attribute is `tempo_scheme`, `tempo_analyzer/app.py:61`); `auto_start_func` (`:607-608, 744-745`) is dead in every handler pattern while four callers still pass it.

#### M16 — `utilities/`: stale docstring, exception mismatch, and a format misroute

`utilities/` is outside both `ruff`'s default globs and `mypy`'s `exclude`, and `utilities/tests/` covers only 2 of the 7 scripts — so defects here are invisible to every gate.

- `rebuild_refinery_log.py:18-20` — the docstring claims the script *"imports `_sha256` directly from the real registry module (falling back to an equivalent local implementation … with a loud warning)"*. There is no such import; `_sha256` is purely local (`:84-95`). For a **hash-compatibility** tool, the docstring is the trusted spec.
- `rebuild_refinery_log.py:163` raises `AudioFileNotFoundError` (→ `AudioIOError` → `AudioSuiteError` → `Exception`) while the caller catches `except FileNotFoundError` (`:256`). The handler can never match — the user gets a raw traceback instead of `[ERROR]`.
- `resize_music_recursive.py:172` — `if isinstance(audio, MP3) or hasattr(audio.tags, "add")`. mutagen's `VorbisComment` (FLAC) and `MP4Tags` both implement `.add`, so this first branch captures FLAC and MP4; the `elif isinstance(audio, FLAC)` branch that handles `audio.pictures` (`:207`) and the `elif isinstance(audio, MP4)` branch that handles `covr` (`:234`) are **unreachable**. FLAC/MP4 embedded art is silently never resized. (Verified by reading the branch structure; a real-file run would confirm the symptom.)
- `utilities/undo.py:163-169` — the per-subparser `--db` is shadowed by the top-level `--db` (`:144-148`) under argparse's subparser-defaults semantics, so `undo --db X show ID` loses `X` while the help text implies it works.
- `strip_bom.py:96-100` — `_cleanup` swallows `OSError` with a bare `pass`.

#### M17 — Key regeneration silently orphans previously encrypted config values

`security/key_manager.py:71-83`: a corrupt or unreadable key file triggers `_generate_and_save_key` — a **new** key — and every value encrypted under the old key becomes permanently undecryptable (`decrypt_string` then raises at `:200-205`). Compounded at `:143-146`: on a key-file *write* failure an ephemeral key is returned without being persisted, so the next launch generates yet another. Neither consequence is surfaced to the user beyond a warning. The encrypted config silently becomes unreadable.

*Recommendation: surface the consequence before overwriting a key file (and keep a `.bak` of the previous key).*

#### M18 — ~13 foundation modules' log records never reach the suite log file under GUI launches

`app_bootstrap.configure_logging` attaches the `RotatingFileHandler` to the **`audio_suite`** logger only (`app_bootstrap.py:123-139`). Those modules use `logging.getLogger(__name__)`, which produces `audio_suite_shared.*` records — those propagate to the **root** logger, not the sibling `audio_suite` branch. Under a GUI launch there is no root handler, and under `pythonw` the `lastResort` stderr path is discarded, so WARNING+ records go nowhere:

`batch_undo.py:73` · `file_processor_base.py:55` · `ui_common.py:36` · `resource_manager.py:22` · `secure_subprocess.py:19` · `error_recovery.py:17` · `lossless_gain.py:92` · `tool_app_base.py:39` · `suite_config.py:44` · `undo_gui.py:44` · `security/error_handler.py:23` · `security/input_validator.py:15` · `security/key_manager.py:18`

The pitfall is **already documented inside the codebase** — `exceptions.py:41-46` explains exactly why a plain `getLogger(__name__)` "would hang off the root logger and never reach `logs/audio_suite.log`" — and the modules that need it still do it. The consequence is that the subprocess **audit trail** (`secure_subprocess.py:271-275`) and undo INFO records (`batch_undo.py:600-606`) are not durably recorded in a normal GUI run.

*Recommendation: one-line change per module — `logging.getLogger(f"audio_suite.{__name__}")` — plus a test asserting every module logger is a descendant of `audio_suite`.*

#### M19 — `show_message` is a 107-line god function with a one-line docstring

`ui_common.py:498-604` — geometry calculation, header, content, action row, hover bindings and event bindings are all built inline. Its docstring (`:506`) has no `Args:` section despite four parameters. Two smaller items in the same file: `:508` `import threading` is function-local with no circular-import justification; `:542` logs "Could not restore dialog geometry" during the *initial* centring; `:524` retains commented-out code (`# dialog.overrideredirect(True)`) under a "keeping it for now" note.

#### M20 — `--end` is write-only in two tools; CLI parse patterns drift across the suite

- `noise_reduction/app.py:253-254` and `pop_click_remover/app.py:222-223` set `self.auto_end_var` from the handshake and **never read it** — no `.get()` anywhere, and no window `destroy` in either file. The Master's `--end` flag is silently inert in exactly those two tools, while tempo, album_genre, album_art_sync, asx and audio_enhancer all honour it.
- Two incompatible GUI-arg parse patterns coexist: dataclass + `CLIValidationError` (tempo, album_art_sync, audio_enhancer, lyrics, asx, album_genre, replaygain) versus `argparse.Namespace` + `parser.error()` (noise_reduction) — plus `parse_known_args()` in noise_reduction (documented as silently discarding extras) against strict `parse_args()` in audio_enhancer, so the Driver launching the enhancer with any extra token hard-exits while noise_reduction discards it.

#### M21 — `audio_refinery` pipeline documentation omits a stage that actually runs

`pipeline.py:5-11` documents "Decode once → declick → trim → enhance → encode once → normalise" — the noise-reduction stage runs **between trim and enhance** (`:196-204`). The step comments number "5" twice (`:202`, `:206`) and drop the box style at 6. `ui/setup_tab.py:157`'s subtitle ("Declick → Trim → Enhance → Normalise") has the same omission — and for a DSP chain the stage order is exactly the thing a user reasons about. Also: `_run_trim_stage` (`:363-370`) derives its user-facing message by **substring-matching** `silence_trimmer`'s human action text (`"trimmed" in action.lower() or "removed" in action.lower()`), coupling the refinery's display to another tool's wording — the branch-message-pinning anti-pattern the project's own `AGENTS.md` warns about.

#### M22 — Remaining duplication classes (below the 0.60 threshold but real)

- `file_processor_base.py` — the discover → log → `on_error` → empty-check → tracker → pool → `on_complete` → cleanup skeleton appears **four times** (`:211-226/:255-262`, `:304-319/:410-419`, `:778-789/:832-840`, `:919-938/:974-983`); the discovery try/except is verbatim three times. `:458-478` and `:480-501` are ~22-line near-duplicate except blocks differing only in exception type.
- `master_driver/ui/cards/` — `build_simple_card` (`_card_base.py:118`) serves 8 cards, but **20 cards** still hand-roll a verbatim ~30-line shell copy (identical `expanded = [False]` blocks across converter, pop_click_remover, fingerprinter, replaygain, cd_ripper, audio_normalizer, palette, bpm, lyrics_manager, audio_enhancer, silence_trimmer, scrubber, file_reorganizer, theme, typography, art, album_genre, library_stats, noise_reduction, tempo). B2 consolidated the *spec* family; the shell family was out of its scope and was never scheduled.
- `master_driver/runner/arg_builder.py` — five near-identical `(path, "0", mode, start, end, --duration, --parallel, --workers)` builders (`:451-476`, `:509-530`, `:533-554`, `:641-661`, `:479-506`).
- `batch_undo.py:1155-1171` vs `:1174-1190` — `_load_max_entries` and `_load_max_bytes` are the same ~16-line function differing only in key name and default.
- `security/key_manager.py:207-238` vs `:240-271` — near-identical encrypt/decrypt bodies, both hardcoding the `"fanart"` section and `app_key`/`client_key` fields. The docstring claims a generic "sensitive fields in a configuration dictionary"; any other sensitive field is stored in plaintext.
- `asx_extractor` — copy/reclassify business logic duplicated between `app.py:265-304` and `cli.py:101-132`.
- `music_format_converter/app.py` — the sorted format-counts breakdown is rendered three times (`:491-498`, `:578-585`, `:608-615`).
- `undo_gui.py:46-66` — 19 hard-coded tool-id → display-name entries duplicating the `ToolManifest.name` field (the `.get(tool_name, tool_name)` fallback at `:85` hides the drift; a newly added tool shows its raw internal id).
- `audio_enhancer/app.py:184-186` — the file's own comment records that `core.models.EnhancementParams` and the shared `dsp_models.EnhancementParams` are field-identical duplicates, "fixed" with a `cast` at `:192`.

#### M23 — Lower-severity quality items worth recording

- `MutagenError = Exception  # type: ignore[misc,assignment]` in four files (`replaygain_analyzer/core/file_processor.py:40`, `file_reorganizer/core/engine.py:26`, `audio_enhancer/core/inspector.py:16`, `audio_enhancer/core/tags.py:25`). When mutagen is unavailable, every `except MutagenError` degrades to `except Exception` in those paths.
- `SubprocessSecurityError` (`secure_subprocess.py:64`) subclasses bare `Exception`, outside the `AudioSuiteError` hierarchy every other error type in the suite uses.
- `file_processor_base.py:252-255` — `run_parallel_processing` does not catch the future `TimeoutError`, so `on_complete` is **never called** and the GUI progress state goes stale; `process_batch` (`:584-604`) catches it explicitly and continues. Five production tools use the former.
- `secure_subprocess.py:437-443` — `run_python_script`'s `timeout` bounds only the final `wait()`; the line-iterating read over `proc.stdout` is unbounded, so a silent child blocks the caller indefinitely.
- `suite_config.py:190-192` — no cross-process lock around load→mutate→save, so two tools launching simultaneously can lose one update (last writer wins). The module comment acknowledges Windows rename locks but not this race.
- `batch_undo.py` read paths (`:562-568`, `:708-718`, `:739-745`) execute without `self._lock` while all writes hold it; mitigated by WAL (`:224`) but undocumented.
- `error_handler.py:36-40` — `_DEBUG` is evaluated at import time while `exceptions.user_message_for` (`:508`) reads the env var per call; the two disagree when the environment changes post-import.
- `key_manager.py:283-291` — `is_encrypted_value` treats any base64-decodable string ≥44 bytes as a Fernet token; a plaintext key of ~60+ base64 chars is misdetected and then raises on decrypt.
- `master_driver/app.py:141` — `except tk.TclError: pass`, silent (the last such site in the driver).
- `lyrics_manager/app.py:118` — a production `assert self._refresh_preset_list is not None`; `[tool.bandit]` policy states production paths raise explicitly, and `python -O` strips it into an `AttributeError`.
- `arg_builder.py:158-162` — the AcoustID API key is passed to the child as a `--api-key` **command-line argument**, exposing it to local process listing (`GetCommandLine`), while the suite otherwise treats it as secret-class (`key_manager`, the gitignored `*.key` files).
- `time.time()` for durations in the fingerprinter (`:745`, `:810`) while the driver runner uses `time.monotonic()`.

#### M24 — Readability items

- `app_bootstrap.py:145-147` — a history-marker comment ("Everything below is the original file — unchanged") documents the VCS, not the behaviour; `:123` names the `audio_suite` logger `root_logger`, which actively misleads (and is what made M18 easy to miss).
- Stale comments describing removed or unrelated behaviour: `audio_enhancer/app.py:329` ("Pop-up confirmation removed per request."), `replaygain_analyzer/app.py:345,402,419` ("Fix #3"/"Fix #15" with no pointer to a fix list), `tempo_analyzer/app.py:41-42` (a dangling "Locate suite root" with no code beneath), `audio_refinery/ui/setup_tab.py:609-629` (stream-of-consciousness over a genuinely incomplete behaviour — a named preset's DSP sliders are `pack_forget()`-hidden, so the user cannot see the values just applied), `_card_base.py:13` (`:func:` reference to `build_card_shell`, which does not exist anywhere in the tree).
- `tool_plugin.py:59` documents "multiples of 10 to leave gaps" while the data uses 41–47 (with **45 twice**: `tag_field_updater:335`, `pop_click_remover:375`); `:159-160` claims declaration order is "load-bearing … drives the Master Driver's tool listing", which is false — the listing sorts by `(category, order, name)` (`:117-130`).
- `ui_common.py:308-309` documents `Raises: ValueError`; the code raises `AudioConfigurationError` (`:311-312`), which does **not** subclass `ValueError` (`exceptions.py:225-226`).
- `cli_helpers.py:543-546` class docstring and the per-pattern docstrings disagree with each other on how many apps use each pattern (6/5, 13/12, 3/2), and omit the fourth (directory) pattern the code handles.
- `models.py:60-61` — a comment reading "# output_gain_db intentionally omitted" immediately above the declared field.
- Naming drift: `GenreConsolidatorApp` for "Album Genre Tagger" (`album_genre_tagger/app.py:32`); `AudioSuiteV6` with a "v6.0 (Optimized)" display name (`album_art_sync/app.py:43,52`); `TOOL_ID` vs `_TOOL_ID`; `start_processing` / `start_extraction` / `start_thread` for the same role.
- Style inconsistency: three module-logger names (`logger` / `_log` / `_logger`); `Optional[...]` and `X | None` mixed *within the same files* (`ui_common.py:62-67`, `album_art_sync/app.py:13`); absolute and relative imports mixed per-file.
- `cli_dataclasses.py:116-145` — `validate_source_output_paths` is literally `validate_folder_path` applied twice; `:88-91` `LyricsArgs` duplicates `BPMArgs`'s four parallel fields with no shared mixin, and `parallel_mode`/`parallel_run` coexist under similar names.

---

## 4. Strengths (recorded so they are not regressed away)

The previous three audits optimised real properties. These hold and should be treated as the floor, not the ceiling.

1. **The gate is real and enforced.** Six commands, all green, re-measured here. `mypy --strict` clean over 460 files with zero ignores added to silence it. `ruff` clean on 783 files including the format check.
2. **The silent-swallow class is genuinely closed.** 0 bare `except:`, 0 `contextlib.suppress`, and no handler found that neither logs, raises, nor surfaces to the user outside two documented best-effort sites (`suite_config` temp-file cleanup, `master_driver` widget recolouring). A3's work held.
3. **Audio-correctness testing is at the standard the standard demands.** E1's dither golden test pins a *measured spectrum* (whole-cycle window, `SEG_N = 28224`), not a flag name; E4's conversion tests decode with pydub **and** `ffprobe` and compare lossless RMS within 1%; C3's `process_file` outcome suite measures per-channel RMS and loudness on real audio. This is the differentiator — and it is why the dither change (E1) required no existing test to be weakened.
4. **`batch_undo.py`'s SQLite discipline is exemplary** and encodes the `AGENTS.md` rule as code: module-level shared lock, WAL + `timeout=30`, `auto_vacuum = FULL` with a one-time legacy conversion whose read-check makes later connects O(1), `user_version`-gated one-shot migration, rowid-ordered pruning *with the reason documented*, and atomic temp-then-`os.replace` restores. This is the 5.5 GB free-page-bloat fix, correctly generalised.
5. **`lossless_gain.py` refuses rather than risks**: CRC-protected and free-format frames are rejected outright, and the bit-level side-info derivation carries its verification provenance in the module docstring.
6. **`exceptions.py`** — a single documented mapping table with first-match-wins ordering, no double-wrapping, an always-logging decorator, and a `user_message_for` escape hatch.
7. **`secure_subprocess.py`** — an allowlisted executable set with per-entry rationale, every dangerous-character decision documented with platform reasoning, and an audit record for *every* invocation.
8. **`acoustid_client.py` / `mbid_writer.py`** — the AcoustID near-tie problem is handled the way the `AGENTS.md` contract demands (tag-aware tie-break, never rank-trusting), and the release-MBID policy is a genuinely conservative "only when exactly one survives, otherwise omit" with documented limits. Most competitors ship the guess.
9. **`accuraterip.py` + `track_processor.py`** — clean-room protocol documentation, and the checksum-window/trim interaction is handled with the exact-length gate plus tail padding, which is precisely the mitigation `AGENTS.md` prescribes for that bug class.
10. **Consolidation was done properly.** B1 retired the CLI flag ladder to **0** production sites behind an AST lock; C2 split the 2,151-line `tag_helper_base.py` behind a facade with an import-contract test; C3 took `process_file` from 319 to 120 lines behind a pre-locked real-audio outcome suite. Each used the lock-first / extract / delete discipline the plan required.
11. **Zero modules at 0% coverage** — D1's stage gate genuinely holds, including the census *correction* (nine small modules the original audit's table had missed).
12. **Documentation hygiene is enforced, not aspirational.** `tests/test_user_guide_hygiene.py` locks generator-per-tool-folder, no tracked `.bak`, and `guide_to_program` resolvability — each with a non-vacuity assertion, which is the pattern that keeps such locks honest. Tempo's scheme tables are *imported* from the code, so the published BPM ranges cannot drift.

---

## 5. Comparison with market leaders

Judged against the tools a serious library-curator would actually choose: **dbPowerAMP / EZ CD Audio Converter** (conversion & ripping), **foobar2000** (playback & conversion), **beets** (automated library curation), **MusicBrainz Picard** (fingerprinting & tagging), **MusicBee** (library management), **Mp3tag** (tagging).

### Where AudioSuite-Pro is now at or above parity

| Capability | Leader benchmark | Suite status |
|---|---|---|
| Dithered bit-depth reduction | dbPowerAMP, foobar2000 — on by default | **Met** (E1): TPDF always-on, `--no-dither` opt-out, measured golden test |
| High-quality resampling | soxr-class quality | **Met** (E1): `soxr` on every rate change, alias measured at −59 dB |
| AccurateRip verification + read offsets | dbPowerAMP, EAC | **Met**, with the checksum-window mitigation in place |
| Acoustic fingerprinting + MBID tagging | Picard | **Met**, and the tie-break discipline is better than Picard's |
| Cover art sourcing | Picard (CAA-first) | **Met** (E3): CAA → MusicBrainz → Fanart → Deezer → iTunes |
| Recursive / mixed-format conversion | dbPowerAMP | **Met** (E4), with the output tree mirrored |
| Batch undo across the suite | beets' `storage` plugin | **Met** — arguably ahead; no leader ships per-file undo snapshots for tag writes in a GUI |
| ReplayGain / LUFS normalisation | foobar2000, beets | **Met** |
| Dry-run discipline | beets (dry-run plugin) | **Met** on 26 of 28 write tools — and the two exceptions are exactly High-1 and M20 |
| Per-file error isolation, never abort a batch | beets | **Met** (`BaseFileProcessor` contract) |

The audio-correctness *engineering* — decode-and-measure tests, tolerance declared from probes, audio-output byte changes gated behind a maintainer decision — is **above** anything the commercial leaders publish, because they don't publish their tests at all.

### Where the suite trails

| Gap | Leader | Assessment |
|---|---|---|
| **Duplicate finder / library database** | beets `duplicates` + library DB; MusicBee | **Absent** (E6, parked). The single largest functional gap. Multi-week, needs its own plan. |
| **DSD support** (`.dff`/`.dsf`) | dbPowerAMP, EZ CD | **Absent** (E7, parked). Real but niche; a project, not a flag. |
| **Plugin / extension architecture** | foobar2000 SDK, beets plugins, Picard plugins | **Absent** (iteration-6 §C2 backlog). This is the leaders' actual moat — it lets *users* extend the tool. Worth a decision, not just an item. |
| **Multiple lyrics providers** | beets (`lyrics` plugin, several providers) | **Closed by policy** (E5). The Musixmatch disqualification (clauses 2.2.12/2.2.13 prohibit writing lyrics *into* audio works — exactly this tool's function) is a correct and well-evidenced call. The named next candidate is local `.lrc` sidecars, which is the right cheap answer. Residual risk recorded: LRCLIB grants no licence, so lyrics can vanish via the community flag queue. |
| **Auto-ingest / folder monitoring** | MusicBee, beets | **Absent.** Watch-folder processing is the main workflow difference versus beets' import command. |
| **Scripting** (Mp3tag, foobar2000) | Mp3tag | **Absent.** Lower value here, where the suite ships 27 purpose-built tools instead. |
| **Non-Windows GUI** | all leaders are cross-platform | **GUI is Windows-only** (iteration-6 §C1); the CLI is portable (there is a test for the non-Windows path). Acceptable given `winaccent`/`ctypes` drive dependencies, but a stated limitation, not an oversight. |

### Assessment

Functionally the suite now sits **at parity with dbPowerAMP/foobar2000 for conversion and ripping, and above both for batch undo and for verifiable audio-correctness engineering**. It is **behind beets/MusicBee on library-scale curation** (duplicates, library DB, monitoring) — which is exactly where E6 sits, parked, correctly, because it needs its own plan. The product-level conclusion from three iterations of audit work: **capability work has converged; what remains is contract hygiene.**

---

## 6. Recommendations, in priority order

Each item is independently shippable. P0 items are the ones where the suite's own standards say the defect is release-blocking.

### P0 — correctness defects (fix before the next release)

1. **HIGH-1** — thread `dry_run` to every `tag_field_updater` save site; fix the `--dry-run` help example; extend `TestDocumentedFlagParity` to parse `Examples:` lines (the blind spot that let this ship); add a real-file outcome test (no write, bytes unchanged, no undo row).
2. **HIGH-2** — one `CueFileSpec` per track in `_write_rip_cue`; strengthen `test_ripper_core.py` to assert `FILE` count == track count and that each named file exists.
3. **HIGH-3** — marshal `album_genre_tagger` and `album_art_sync` worker callbacks through `root.after(0, …)`; delete the false `update_idletasks` claim; align `daemon=True`; add scheduling-regression tests (positive assertions).
4. **HIGH-4** — build the driver argv on the main thread and pass the finished list to the thread; add a test that mutates state after the snapshot and asserts the emitted argv is unchanged.
5. **M20 (first half)** — make `--end` functional (or explicitly ignored-with-a-warning) in `noise_reduction` and `pop_click_remover`.

### P1 — contract and security correctness

6. **M2/M3** — fix or delete the dead symlink branch; point `validate_audio_file_path` at `SUPPORTED_EXTENSIONS` and add a set-equality test.
7. **M18** — re-parent the 13 foundation loggers under `audio_suite.*`; add a test asserting every module logger descends from `audio_suite`. One line each, and it restores the subprocess audit trail.
8. **M11/M12/M13** — registry completeness test for `DEPENDENCY_GRAPH`; refinery select-all must include `reduce_noise`; correct the display-flag variables; delete the "no stages → re-enable all" fallback.
9. **M7/M8** — report skipped standalone tools as skipped, not completed; record not-found modules in `failed_steps`.
10. **M4** — write the `[Unreleased]` changelog entries, with a `### Changed` note for E1's byte-level output change.

### P2 — maintainability debt with a plan already written

11. **M1** — delete the production-dead legacy argparse subsystem (~300 lines) and rename the colliding `parse_cli_args`.
12. **M5** — extract `noise_reduction` ↔ `pop_click_remover` behind `tool_app_base` (B4's named follow-up; closes the duplication class).
13. **M15** — dead-code sweep: `_ENHANCE_PRESETS`, `_sync`, `check_integrity_batch`, the dead `slot_idx`/`_FingerprintJob.processor`, the legacy str-spec path, write-only attributes, dead `auto_start_func` and the dead `scheme` branch.
14. **M22** — the remaining duplication: the 20-copy card shell, five arg-builder bodies, the four-fold batch skeleton in `file_processor_base`, `_load_max_*`, `key_manager` encrypt/decrypt.
15. **M9** — migrate the 123 instance-method class-scoped fixtures before the next pytest major; close the unclosed SQLite connections in test teardown.
16. **M10** — raise the six sub-60% GUI `app.py` modules; the two `app.py` files carrying HIGH-3 should be first, since the uncovered code *is* the defect.

### P3 — lower-severity hygiene

17. **M16** — fix the three `utilities/` defects (stale `_sha256` docstring, `FileNotFoundError` mismatch, FLAC/MP4 misroute), the `undo.py --db` shadowing, and the `strip_bom.py` silent pass. **Extend `utilities/tests/` beyond its current 2-of-7 scripts** — that directory is outside both the ruff and mypy gates, so a test is the only thing that will keep it honest.
18. **M17** — surface key-regeneration consequences and back up the old key.
19. **M23/M24** — the `MutagenError = Exception` aliases, the exception-hierarchy outliers, the uncaught parallel timeout, the unbounded subprocess read loop, the suite_config lost-update race, `SubprocessSecurityError`'s base class, the production `assert`, and the API key on the child command line (move to an env var or a file reference).
20. **M21/M24** — correct the refinery stage-order documentation and the substring-matched trim message; remove history-marker and stale-fix-number comments; fix the `tool_plugin.py` order docstring and the `ui_common.py` wrong `Raises:` type.

### P4 — capability (decisions, not defects)

21. **E6** duplicate finder / library database — open its own plan; the ten-point registration checklist is already specified.
22. **E7** DSD — same disposition; touches the shared format table, the converter, the refinery encode stage and ffmpeg probing.
23. **Plugin architecture** — the leaders' actual differentiator; worth a maintainer decision on whether AudioSuite-Pro wants to be extensible-by-users or fixed-tool-suite.
24. **Folder monitoring / auto-ingest** — the cheapest remaining parity item with MusicBee/beets.
25. **macOS parity** — decide explicitly: commit to it, or document Windows-GUI as a standing limitation in the README (currently neither).

---

## 7. Closing note

Three iterations of audit and remediation have moved this suite from "needs a plan" to "needs a smaller plan." The gate is green and honest, the audio-write paths are tested by measurement rather than read-back, and the shared layer is genuinely well-factored.

What this audit found is instructive about the limit of that success: **every High finding survived a fully green suite.** Two were in code paths no test executed (the tag-update CLI at 48% coverage; the CUE sheet, whose test asserts a substring rather than a structure), and two were threading violations hidden behind mocked Tk. The mechanical gates — types, lint, coverage, security scan — are at their ceiling and cannot see any of them. What catches this class is specific, human-authored, structure-asserting tests plus a review that traces a contract end to end, which is exactly what `AGENTS.md` already insists on and what the P0 items above are written to reinforce.

Suggested file name for the remediation plan that follows this report: `PLAN_iteration8_remediation.md`, staged as P0 → P4, with the same per-item Gate Evidence rule iteration 7 established.