# AudioSuite-Pro — Fresh Read-Only Audit Report

**Date:** 2026-10-06
**Scope:** Full re-audit of code quality, readability, maintainability and gold standards
after the iteration-8 remediation (`PLAN_iteration8_remediation.md`, commits `7ffcf6a`..`6dc03f3`).
**Baseline:** `AUDIT_2026-10-02_suite_report.md` (4 High / 24 Medium at commit `c1daf1d`).
**Constraints:** Read-only — no code was altered. The only artifact added is this report.
**Comparison set:** Currently available *audio-manipulation* software only
(converters, CD ripper, loudness/normalisation, tag editors, restoration/repair tools).
Library managers and music players (MediaMonkey, foobar2000, iTunes…) are out of scope.

---

## 1. Method

1. Re-ran the full mandated verification gate at HEAD (`6dc03f3`) rather than trusting the
   plan's completion log.
2. Read every iteration-8 module change against the claims in its completion log.
3. Empirically reproduced suspected defects (two-process probes for config concurrency,
   in-process probes for logging and CLI contracts) instead of reasoning from source alone.
4. Cross-cutting sweeps: duplication, test quality/naming, docs accuracy, coverage pockets.
5. Market research against current (2026) offerings of comparable audio tools.

Evidence discipline: every finding below was verified directly (file:line, probe output, or
command output). Claims sourced from sub-sweeps were re-checked by hand; the one materially
wrong claim found during the sweep (a purported wrong dry-run default in
`transformation_rules.py`) was discarded after reading all eight save sites — they are
correctly gated.

---

## 2. Verification gate re-measured at HEAD

| # | Gate | Result |
|---|------|--------|
| 0 | `python -m compileall -q -f .` | **PASS** (exit 0) |
| 1 | `ruff check .` | **PASS** |
| 1 | `ruff format --check .` | **FAIL — 1 file** (`user_guides\individual_programs\lyrics_manager\generate_guide.py`) |
| 2 | `mypy .` (strict) | **PASS** — 461 source files, no issues |
| 3 | `bandit -r . -x ./.venv -c pyproject.toml` | **PASS** — 0 High / 0 Medium / 41 Low (documented B603/B606/B607 call sites) |
| 4 | `pytest` (bare, full `testpaths`) | **PASS** — 8493 passed, 3 skipped, 30 deselected, 8 warnings |
| 4 | coverage (same run) | **89.39%** (threshold 75) |

**The suite is in its strongest verified state to date** — but the format gate is red at
HEAD, which under this project's own "every tool passes 100%" rule blocks release. See H1.

---

## 3. Findings

### HIGH

#### H1 — Mandated `ruff format` gate fails at HEAD; completion log evidence not reproducible

```
$ python -m ruff format --check .
Would reformat: user_guides\individual_programs\lyrics_manager\generate_guide.py
1 file would be reformatted, 793 files already formatted
```

- Introduced by commit `de95017` (I4, the `.lrc` sidecar provider), whose completion log
  records `ruff format --check .` as "**794 files formatted**"; re-running it at HEAD
  reports **793 already formatted + 1 would be reformatted**. The gate has therefore been
  reported green for a commit that does not satisfy it — the first non-reproducible gate
  claim found in this codebase (nothing touched the file in the later `6dc03f3` plan-only
  commit).
- Diff is quote-style only (`"Unknown"` → `'Unknown'`), so the fix is mechanical, but the
  *process* defect (logging a gate result that does not reproduce) is the more important
  half of this finding.

#### H2 — The lost-update race that audit M23 / iteration-8 I1 claimed to close still reproduces

`audio_suite_shared/suite_config.py` wraps every `save_*` in `_file_lock()` (line 62) — and
the lock mechanism itself works (empirically: a contender blocks ~4 s until the holder
releases; `os.open(..., O_TRUNC)` does not fail under the Windows mandatory byte-range lock).

The defect is one layer down: `save_*` does `with _file_lock(): data = _load() … _save(data)`
(e.g. lines 235-238), but `_load()` returns the **per-process in-memory cache** whenever one
exists (line 117). The cache is populated by any earlier `load_*` and invalidated only by
that same process's `_save()` (line 193). So a process that loaded at startup still holds
its stale snapshot when it takes the lock, and writes it back over a concurrent tool's save.

**Reproduced with two real processes on an isolated temp config:**

```
A: loaded; cache keys: ['last_directory']
B: saved palette
A: saved theme_mode; on-disk: {'last_directory': 'ORIG', 'theme_mode': 'Dark'}
                                                     ← B's 'palette' is gone
```

Sequence: A `load_last_directory()` → B `save_palette("Purple")` → A `save_theme_mode("Dark")`
under the lock. A's locked read hits A's cache, so the write omits `palette`.

- **Impact:** silent loss of suite settings (window geometry, last directory, per-tool
  preferences) whenever two tools run concurrently — the exact scenario the lock exists for.
  Not audio data, but it *is* silent data loss and the plan item is recorded as complete.
- **Fix shape:** invalidate the cache (or read `CONFIG_PATH` directly) inside the lock
  immediately before the read-modify-write; add a two-process regression test.
- `_save()`'s own post-write invalidation (line 193) is why a *save-first* sequence passes —
  which is how this slipped through: the natural single-key test never loads between saves.

---

### MEDIUM

#### M1 — Tool-package loggers never reach `logs/audio_suite.log` under GUI launch

`app_bootstrap.configure_logging` attaches the file handler only to the `audio_suite`
logger. 112 production modules outside `audio_suite_shared` use `getLogger(__name__)`,
rooted at their tool package (e.g. `noise_reduction/app.py:19`), whose records propagate to
a root logger that has no file handler.

Empirical probe (handler wired exactly as bootstrap does it):

```
SUITE HANDLER SAW: ''        ← noise_reduction.app logger produced nothing
```

So the suite log records foundation events but silently omits every tool module's
`logger.warning/error` under GUI launch; CLI launch falls back to
`cli_base.py:248 logging.basicConfig(...)` (stderr only, no file). Two-tier logging by
accident, not design.

#### M2 — CLI reference documents defaults that are the opposite of actual behaviour

`user_guides/reference/CLI_Commands_Reference.md`:

| Line | Documented | Actual (click introspection) |
|------|-----------|------------------------------|
| 18, 40, 58, 237 | `--dry` "(default: **dry**)" | `dry_run=False` → **live** for `album-genre`, `album-art`, `asx-extract`, `lyrics` |
| 84 | "(default: live)" | contradicts the four lines above it |
| 103 | `--stages` "(default: **all five**)" | `'declick,trim,enhance,normalise'` (4 of 5) |

Safety-relevant: a user reading line 18 believes a bare `album-genre` run previews, when it
writes tags. Every claim in this document was generated from an assumed design rather than
introspected from the commands — the same class of defect as the `arg_builder`/CLI mismatch
recorded in the project's own AGENTS.md.

#### M3 — CHANGELOG `[Unreleased]` omits shipped iteration-8 functionality

Case-insensitive grep for `sidecar` / `auto-end` / `lrc` in `CHANGELOG.md` → **zero hits**.
Missing:
- I4: local `.lrc` sidecar lyric provider (a user-visible provider in the lyrics chain);
- C9: `--end` / auto-end window closing in the affected tools.

CHANGELOG discipline was itself the point of audit C2; it has since drifted again.

#### M4 — `validate_target_lufs` is bypassed by the click CLIs

`cli_dataclasses.validate_target_lufs` (line 170) enforces `VALID_TARGET_LUFS_VALUES`.
Production call sites: `audio_normalizer/utils/cli_args.py:61`,
`audio_refinery/utils/cli_args.py:300`, `audio_refinery/utils/settings.py:54`,
`replaygain_analyzer/utils/cli_args.py:58`, `replaygain_analyzer/app.py:280` —
i.e. argparse and GUI paths only.
`audio_refinery/cli.py:129` and `audio_normalizer/cli.py:42` accept a bare `float`, so
`refine --target-lufs 999` runs unvalidated. The suite's stated contract (validate at every
entry point) does not hold for its primary scripted interface.

#### M5 — The one branch that *saves* metadata-scrubber preferences is never tested — only a negative assertion exists

`metadata_scrubber/app.py:368-369`:

```python
if is_live:
    tag_prefs.save_kept_tags(_PACKAGE_DIR, preserve_list)
```

- `test_on_complete_writes_log_and_renders_summary` runs with `is_live=False` (line 311).
- `test_dry_run_completion_never_saves_tag_prefs` runs with `is_live=False` and asserts only
  `save_kept_tags.assert_not_called()` (line 350).
- Coverage confirms it: **line 369 is in the missing-lines list** for
  `metadata_scrubber\app.py` (80%).

Deleting the live-save line entirely would leave the suite green. This is precisely the
"a test that asserts a side effect does *not* happen is a bug in waiting" pattern named in
AGENTS §7 — and here the untested side is the one users depend on.

#### M6 — Test-file naming convention violated in 43 files (including the exact example AGENTS forbids)

Re-derived rule: `test_<module>.py` mirrors source `module.py`. 43 test files have no
source module of that name (some are legitimate composites, e.g. `test_tag_io.py`, which
AGENTS explicitly exempts). The clear violations:

- `bpm_analyzer/tests/test_app_audio_detection.py` — the literal name AGENTS lists as
  forbidden ("do not use descriptive/compound names… use `test_app.py`"), coexisting with
  `bpm_analyzer/tests/test_app.py` in the same directory (11 + 8 tests).
- `asx_extractor/tests/test_app_run.py` alongside `test_app.py`;
  `asx_extractor/tests/test_cli_run.py` alongside `test_cli.py` — two files per module,
  against the one-test-file-per-module rule.
- `audio_fingerprinter/tests/test_fingerprinter_app.py` / `test_fingerprinter_cli.py`,
  `master_driver/tests/test_utilities_format_detection.py`, several `*_core`/`*_run` names.

#### M7 — `file_processor_base.py` still contains four copies of the batch skeleton

`audio_suite_shared/file_processor_base.py` (1,484 lines) implements the same
discover → log → `on_error` → pool → `on_complete` orchestration four times:

| Entry point | Line | "No supported audio files found" |
|---|---|---|
| `run_parallel_processing` | 194 | 221 |
| `run_cpu_bound_processing` | 288 | 335 |
| `run_inplace_dsp_batch` | 763 | 809 |
| `run_analysis_workflow` | 864 | 949 |

The literal error string appears 4× here; the unification this file was created for
(M24 / I2) stopped at the helpers, not at the orchestration skeleton. Any behaviour added to
one entry point (progress reporting, cancellation, skip attribution) must now be added four
times — the historical source of this repo's iteration-5/6 defects.

#### M8 — `bpm_analyzer` and `lyrics_manager` remain near-clones

```
$ git diff --no-index --numstat bpm_analyzer/app.py lyrics_manager/app.py
142  88  {bpm_analyzer => lyrics_manager}/app.py
$ git diff --no-index --numstat bpm_analyzer/ui/setup_tab.py lyrics_manager/ui/setup_tab.py
115  90  {bpm_analyzer => lyrics_manager}/ui/setup_tab.py
```

~300 changed lines across two module pairs means the majority of both files is identical.
These are exactly the two tools whose analysis/loader structure could share a base class
(`analysis_app_base` exists in `audio_suite_shared` but is not used by both).

#### M9 — README states a stale verification metric

`README.md:225` — "mypy runs in `--strict` mode over **452 files**"; the gate reports
**461** source files. Small in itself; relevant because README metrics are re-checked by
`tests/test_readme.py`, which evidently does not cover this number.

#### M10 — Undo dialog shows tool names that no longer match the manifest

| Location | Display name |
|---|---|
| `audio_suite_shared/undo_gui.py:50` | `"ASX Extractor"` |
| `audio_suite_shared/tool_plugin.py:268` (manifest, source of truth) | `"ASX Playlist Extractor"` |
| `audio_suite_shared/undo_gui.py:54` | `"File Reorganizer"` |
| `audio_suite_shared/tool_plugin.py:318` | `"Tag-Based File Reorganizer"` |

User-visible inconsistency in the undo history; a second display-name map that should have
been derived from the manifest when C10's `__all__` mapping landed.

#### M11 — Coverage pockets remain concentrated in newer tool UIs

From the coverage run (skip-covered):

| Module | Cover |
|---|---|
| `cd_ripper/ui/metadata_config_panel.py` | **45%** |
| `cd_ripper/ui/results_tab.py` | **47%** |
| `cd_ripper/ui/drive_config_panel.py` | **52%** |
| `lyrics_manager/app.py` | 67% |
| `master_driver/ui/refinery_tab.py` | 73% |
| `metadata_scrubber/app.py` | 80% (incl. the untested branch in M5) |

Suite-wide 89.39% masks these; the two newest/most complex GUI surfaces are the weakest.

---

### LOW

- **L1 — 8 × `ResourceWarning: unclosed file`** in the suite itself: `tomllib.load(open(...))`
  at `tests/test_pyproject_config.py:106,147,163,231` and `tests/test_readme.py:115`.
  Only warnings in an otherwise silent suite.
- **L2 — `audio_suite_config.json.lock` is left in the repo root** after every tool run and
  is **not in `.gitignore`** (grep for `lock` → no match). It appears as a permanent `??` in
  `git status`. (The lock file itself is correct behaviour; the missing ignore entry is the
  defect.)
- **L3 — Long business functions:** `music_format_converter/core/file_processor.py`
  `process_single_file` = **244 lines**; `mood_analysis_batch_tagger/core/batch_analysis_engine.py`
  `run_batch` = **211 lines**; `file_processor_base.run_cpu_bound_processing` = 153 lines.
- **L4 — `utilities/` sits outside both the mypy `exclude` and the coverage `source` list**
  (`pyproject.toml`) — the scripts that perform bulk file/DB mutations are the least
  verified code in the repo.
- **L5 — Test-suite hygiene:** 30 deselected + 3 skipped tests are stable, but the 8
  warnings above are the only noise and are trivially removable.

---

### Verified non-findings (checked, not defects)

- **A1 dry-run fix is sound:** all eight `process_*_file` save sites in
  `tag_field_updater/core/transformation_rules.py` gate both `record_tag_edit_snapshot` and
  `audio.save()` on `dry_run`.
- **Config file lock works** under contention (probe: 4.02 s block, clean release).
- **Zero real TODO/FIXME markers** (the 136 grep hits are all the ID3 `TXXX` frame).
- **Resampler is SoXR** (`music_format_converter/core/ffmpeg_params.py:48`) — a genuinely
  high-quality choice; see market comparison.
- **ReplayGain analyzer implements true album-mode gain** (`calculate_album_gain`,
  `replaygain_analyzer/core/file_processor.py:41`).

---

## 4. Code quality, readability, maintainability

### Strengths (gold-standard compliance)

| Dimension | Assessment |
|---|---|
| **Type safety** | `mypy --strict` clean across **461 files**, no `# type: ignore` abuse, per-module carve-outs declared in `pyproject.toml`. This is well beyond typical Python audio tooling. |
| **Testing** | **8,493 tests / 89.39% coverage** against a 75% floor; regression tests pin real audio outcomes (decode-and-measure), per the project's release-blocking rule. |
| **Static security** | bandit 0 High / 0 Medium with a declared, audited Low set. |
| **Error handling** | Exception hierarchy + `raise … from` discipline holds; logging module used consistently. |
| **Safety design** | Dry-run/live modelling, undo log with SQLite `auto_vacuum` handling, pre-flight `guard_or_exit` byte-compile gate — all unusually defensive for this tool class. |
| **Docs coverage** | 28 generator-owned user guides + CLI reference + logging/security guides; a `test_user_guide_hygiene.py` gate exists. |
| **Consistency** | The 28 tool packages are structurally near-identical (`app.py`/`cli.py`/`core/`/`ui/`/`utils/cli_args.py`) — a new engineer who has seen one tool has seen all of them. |

### Weaknesses

1. **Claimed-complete ≠ verified-complete.** Two completion claims checked by hand did not
   reproduce: H1 (I4 logs `ruff format` green; it is red) and H2 (I1 sub-item 5 closes the
   lost-update race; it still reproduces). The gate tables in the plan are being written
   from intent rather than re-run output against the final commit.
   *Recommendation: paste command output into completion logs, and re-run the gate against
   the commit as pushed, not against the last file edited.*
2. **Duplication concentrates in the shared base.** `file_processor_base.py` (M7) and the
   bpm/lyrics clone (M8) are the two places where divergence risk is highest, precisely
   because the code is *supposed* to be shared.
3. **Negative-contract tests.** M5 is the clearest case; the pattern (assert-not-called
   without a positive counterpart) should be grepped suite-wide — `tests/test_vacuous_asserts.py`
   already exists as a lock, and it evidently does not cover this shape.
4. **Second sources of truth for display strings.** The `undo_gui` name map (M10) and the
   CLI reference's hand-written flags (M2) both duplicate the manifest/CLI and have both
   drifted. Anything derivable (names, defaults) should be introspected, not transcribed.
5. **Coverage is bimodal.** 89% suite-wide vs 45% in `cd_ripper` UI panels — aggregate
   numbers are hiding the newest code.
6. **Test naming is convention-by-best-effort** (M6) — the rule exists in AGENTS but nothing
   enforces it; a simple AST check (test stem ↔ source stem, with a declared composite
   allow-list) would lock it, in the same style as `test_tool_plugin.py` locks registrations.

---

## 5. Market comparison (audio-manipulation software only, 2026)

### Where AudioSuite-Pro is genuinely competitive

| Dimension | AudioSuite-Pro | Comparable market standard |
|---|---|---|
| **Breadth under one roof** | 28 tools, one Master Driver, shared config/undo/logging | dBpoweramp Reference (~$38) = converter + ripper + ~30 DSPs; EZ CD ($39) = rip + convert + burn. **AudioSuite spans analysis (key/BPM/mood), lyrics, art, fingerprinting, ripping, tagging and repair in one suite — no single competitor does.** |
| **CD rip integrity** | AccurateRip-style checksums, read-offset detection (`cd_ripper/core/accuraterip.py`, `read_offset.py`) | EAC / dBpoweramp invented AccurateRip; XLD on macOS. AudioSuite matches the *algorithmic* tier (offset + checksum), which is rare for a free tool. |
| **Conversion quality** | SoXR resampler (`ffmpeg_params.py:48`), dithered bit-depth reduction (TPDF, CHANGELOG line 49) | dBpoweramp markets ARDFTSRC as "best resampler on the planet" (2026 releases); EZ CD ships "professional SRC + RPDF/TPDF/noise-shaped dither". SoXR is in the same quality conversation — **but AudioSuite does not say so anywhere.** |
| **Loudness** | Two-pass ffmpeg `loudnorm` with `TP=-1.5` (`audio_normalizer/core/normalizer.py:125`); ReplayGain **album mode** | ffmpeg-normalize (presets, `--batch` album-relative mode), LUFSNormalizer (watch folder, needs-limiting reports), RX 12 Loudness Control. Feature-equivalent for the core task; behind on workflow conveniences. |
| **Fingerprinting/tags** | AcoustID + **MusicBrainz MBID writing** (I5), tag-aware near-tie breaking | Picard (MBID-native), Mp3tag v3.35/3.36 (Discogs/MusicBrainz sources, action groups, regex). AudioSuite's tie-break rule is unusually well documented for this tool class. |
| **Engineering rigor** | 8,493 tests, 89% coverage, strict mypy, bandit, pre-flight guard | Not comparable: ffmpeg-normalize has CI + a small suite; fre:ac/XLD/EZ CD are closed-source with no public test rigor. **AudioSuite's engineering process is a real differentiator.** |
| **Price / offline** | Free, offline-first, no telemetry | dBpoweramp $38, EZ CD $39, RX $99–$1,399, Mp3tag free-but-closed |

### Where AudioSuite-Pro is behind

1. **Audio restoration depth** — iZotope RX 12 ($99–$1,399) offers 50+ repair modules
   (spectral repair, de-hum, de-reverb, Dialogue Isolate, Music Rebalance/Stems, Trim
   Silence, Repair Assistant) plus a batch processor. AudioSuite's repair row is
   `noise_reduction`, `pop_click_remover`, `silence_trimmer` — competent batch DSP, but no
   spectral editing, no de-hum, no stem separation.
2. **Workflow conveniences of mature converters** — dBpoweramp: Windows Explorer right-click
   conversion, tag-based filters in Batch Converter, per-column configuration, shell
   notifications; EZ CD: cue-sheet generation/conversion, DSD, disc burning, 4K-DPI/Unicode
   UI polish. AudioSuite has no watch-folder, no shell integration, no packaging story
   (runs from source via `.pyw`; competitors ship installers/single-exe — e.g. LUFSNormalizer
   ships a PyInstaller exe).
3. **Tag-editor ergonomics** — Mp3tag's action groups (reusable multi-step recipes), regex
   find/replace across tags *and* filenames, filename↔tag conversion, playlist export, CSV
   export, custom columns/panels. AudioSuite has `tag_field_updater` (find/replace) and
   `file_reorganizer` (rename) as separate one-shot tools with no composable recipes and —
   verified — **no playlist (`.m3u`) writing anywhere in the codebase**.
4. **Duplicate detection** — PerfectTUNES De-Dup / Mp3tag duplicate reports compare audio
   content; AudioSuite's fingerprinter identifies *metadata* but does not report "these two
   files are the same recording".
5. **Platform reach** — competitors (XLD macOS, fre:ac everywhere, EZ CD/dBpoweramp Win+Mac)
   vs AudioSuite Windows-first (`msvcrt` locking, drive letter CD-ripping assumptions, Tk).
6. **True-peak workflow** — LUFSNormalizer exposes a configurable peak ceiling plus a
   `needs_limiting/` quarantine report; AudioSuite hardcodes `TP=-1.5` in the loudnorm
   filter with no user control and no post-limit verification report.

---

## 6. Functionality suggestions (prioritized)

**Tier 1 — high value, builds on existing infrastructure**

1. **Duplicate-audio detector on the fingerprinter.** Compare AccurateRip-style content
   checksums / Chromaprint hashes across a library and report same-recording duplicates.
   Reuses `cd_ripper` checksum code + `audio_fingerprinter` pipeline; is the one common
   feature (PerfectTUNES De-Dup) with no AudioSuite equivalent.
2. **Playlist export (`.m3u8`)** from any tagging/reorganising tool. Zero playlist writing
   exists today; Mp3tag treats it as core. Cheap: file listing already carries tag metadata.
3. **Configurable true-peak ceiling + post-normalisation verification report** in the
   Audio Normalizer (make `TP=-1.5` a parameter; echo measured `input_tp`/`output_tp` in the
   run log). Moves the tool from "applies loudnorm" to "proves delivery compliance".
4. **De-hum tool** (50/60 Hz + harmonics, notch/adaptive). The cheapest credible step toward
   the RX gap, and the DSP scaffolding (filters, batch, dry-run, undo) already exists.

**Tier 2 — workflow parity with mature converters**

5. **Saved multi-step "action recipes"** shared across `tag_field_updater`,
   `file_reorganizer` and `album_genre_tagger` (Mp3tag Action Groups analogue). Turns three
   one-shot tools into a composable system; the config layer (`suite_config`) can hold them.
6. **Tag-based batch filters** in the format converter (include/exclude by artist/album/
   format), which dBpoweramp's Batch Converter treats as table stakes — the recent
   mixed-format scan (C-class work) already computes most of the needed index.
7. **Watch-folder mode** for at least one processing tool (normalizer or converter):
   LUFSNormalizer's headline feature; natural fit for the existing batch orchestrator.
8. **Stem separation / dialogue isolate** as an optional backend (Demucs or similar) —
   the largest single feature-class gap vs RX 12, and the analysis-tooling pattern
   (optional dependency, batch, dry-run) already exists in the suite.

**Tier 3 — engineering & distribution**

9. **Make derived facts introspected, not transcribed:** generate the CLI reference's flag
   defaults from `click` (fixes M2 permanently and prevents recurrence), and derive
   `undo_gui` names from `tool_plugin` (fixes M10).
10. **Package a distributable build** (PyInstaller one-file/one-folder or an installer) so
    the suite can be used without a Python toolchain — every competitor ships one.
11. **Enforce the test-naming rule with an AST test** (mirror of `test_tool_plugin.py`) and
    an explicit composite allow-list — converts M6 from a convention into a gate.
12. **Unify the four `file_processor_base` skeletons** behind one parameterised runner
    (M7) — this is *maintainability* work that also removes a recurring defect class.
13. **Cross-platform seam audit** (log only, not a port): record every `msvcrt`/Windows-only
    assumption so a future port is a known quantity rather than a discovery process.

---

## 7. Recommended next actions (in order)

1. **Run `ruff format` on `lyrics_manager/generate_guide.py`** and re-run the full gate;
   record the *command output* in the I4 completion log (fixes H1, corrects the record).
2. **Fix the `suite_config` stale-cache read inside the lock** (H2) with a two-process
   regression test — this is a reopened audit item (M23), not a new backlog item.
3. Correct the CLI reference defaults (M2) by introspection; the current text can cause
   unintended writes.
4. Add the positive `is_live=True` test for `metadata_scrubber` (M5) and grep for other
   not-called-only assertions.
5. Sweep the remaining Mediums (M1 logging scope, M3 CHANGELOG, M4 LUFS validation,
   M6 naming, M7/M8 duplication) as a follow-on plan.

---

*All findings in this report were verified against HEAD `6dc03f3` by direct command,
file read, or executable probe; no source file was modified during this audit.*
