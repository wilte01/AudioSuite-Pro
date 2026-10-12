# PLAN — Bug-Hunt Remediation (BUG_HUNT_REPORT_2026-10-11)

**Status:** `[ ]` not started — planning only (created 2026-10-11). No source
changes are made by this document.
**Base state:** HEAD `0349d06` (Route A installer scaffolding) on `main`; working
tree otherwise clean apart from `M metadata_scrubber/tag_prefs.json`.
**Source of findings:** `BUG_HUNT_REPORT_2026-10-11.md` (read-only audit).
**Governing scope (user-confirmed 2026-10-11):** remediation of the report's
**confirmed** findings — H1–H3, M1–M6, L1–L3 — plus **empirical triage** of the
report's "not independently re-verified" list. No feature work. Anything the
triage proves is *not* a defect is closed as such, not fixed.

This plan is self-contained: each item states the exact files, the exact
change, the tests to add/update in lockstep, the guide/CHANGELOG touchpoints,
and the acceptance commands. Work proceeds sprint by sprint so it can span
several sessions; the six-command gate is re-run and recorded after every
sprint (see §3.1).

---

## 1. Decisions (decision log)

Confirmed at planning time (grounded in HEAD):

| D | Decision | Rationale |
|---|---|---|
| D1 | Scope = the report's confirmed H1–H3/M1–M6/L1–L3 + triage of its unverified list. | User instruction ("resolve the bugs reported in the report"). |
| D2 | Every item begins with a **reproduction through the real entry point** (driver argv for launched tools, `.pyw` GUI path, CLI path) before any edit. | Global AGENTS §3: "the launch path is part of the state"; a fix that only reproduces in a unit test can miss the shipped trigger. |
| D3 | The four argv-ignoring tools (`file_reorganizer`, `tag_field_updater`, `library_stats`, `cd_ripper`) are the **only** tools with no `utils/cli_args.py` (verified: 22 of 26 processing tools have one) — confirming H3 is a wiring omission, not intended interactive-only behaviour. | Empirical census at HEAD. |
| D4 | H1 changes the *value* written to `REPLAYGAIN_*_PEAK` (dBFS → linear). Any existing test pinning the dBFS string is **updated in lockstep**, and the change carries a CHANGELOG Fixed bullet + guide audit. | User-visible tag output changes; lockstep rule. |
| D5 | M5 undo **cannot** restore an overwritten destination: `BatchUndoLog.record_file_reorg` (`audio_suite_shared/batch_undo.py:435-465`) records only `source_path`/`dest_path`; it stores no destination bytes. The `record_file_overwrite` path exists but is not called here. So the fix must **prevent** the overwrite (guard), not merely record it. | Verified at HEAD. |
| D6 | Collision policy for M4/M5 = **skip-and-warn** (user-confirmed 2026-10-11): when a target already exists, leave it untouched and report the collision; never silently overwrite, never auto-rename. Applied to both M4 and M5. | No silent data loss, no surprising new filenames; auto-uniquify and fail-loud were rejected by the user. |
| D7 | H3's target contract = **consume-and-pre-fill** (user-confirmed 2026-10-11): the four tools parse the driver argv and pre-fill their widgets, matching `Tag_Editor` and the other 22 tools. G2.0 still verifies each arg maps to a real widget before code is written. | The driver's per-tool settings must take effect; the census (D3) shows the omission was a wiring gap, not a design choice. |
| D8 | M1 is fixed by making `resolve_and_apply` return a **failure `ArtSyncReport`** on error (not by re-raising into every caller), preserving its `-> ArtSyncReport` contract; `reraise=True` is the fallback if a failure report proves impossible for a given error class. | Minimal blast radius; callers (`cli.py:82`) already assume the object exists. |
| D9 | L2 uses the suite's SQLite pattern: `PRAGMA auto_vacuum=FULL` at schema creation **and** one-time legacy conversion on connect (read `PRAGMA auto_vacuum`; if not FULL → set + `VACUUM`). | Global AGENTS §5 (auto_vacuum lesson). |
| D10 | Negative controls that temporarily break a fix on a file with uncommitted work restore from a **SHA-256-verified backup copy**, never `git checkout`. | Global AGENTS §5 (C2 lesson). |
| D11 | Any scripted bulk edit (unlikely here) reads with `encoding="utf-8"` and reuses each file's own line terminator; touched lines are re-read before the gate. | Global AGENTS §5 + project AGENTS (encoding / line-ending lessons). |
| D12 | **Versioning scheme (user-confirmed 2026-10-11):** `MAJOR.MINOR.MAINTENANCE` — token 1 major, token 2 minor, token 3 maintenance. This first maintenance release bumps the suite `1.0.0 → 1.0.1`. The **single source of truth is `[project] version` in `pyproject.toml`** (G8.4); `audiosuite --version` and the installer derive from it, so they need no separate edit. | User instruction + `audio_suite_shared/project_version.py` ("the single place the version lives"). |
| D13 | The unused per-package `__version__` constants (`file_reorganizer/__init__.py:10`, `tag_editor/__init__.py:5`, `tag_field_updater/__init__.py:15` = `"1.0.0"`; `audio_fingerprinter/__init__.py:9` = `"0.1.0"`) are **not** the distribution version — nothing reads them (verified: no `.__version__` consumer) and one is inconsistent. **Decision: leave them unchanged** in G8.4 and record the observation; changing them is a separate housekeeping item, not part of the release bump. | Minimal-diff; the suite version is governed solely by `pyproject.toml` (CHANGELOG.md:7-8). |
| D14 | **Per-file change note (user-confirmed 2026-10-11):** every hand-edited first-party file this plan touches carries a note naming the release (`1.0.1`) and a one-line summary of the change in that file. Python: append a final paragraph to the module docstring (no docstring → add a minimal one); comment-bearing non-Python (`.toml`/`.iss`/`.ps1`/`.md`) use the same sentence in that syntax; comment-less formats (`.json`) are listed as explicit exceptions and carry the note in the CHANGELOG only. Scope excludes regenerated binary artifacts and `CHANGELOG.md`. Formalised in §3.7; verified by G8.5. | User instruction; supersedes the "no comments unless asked" default for these specific annotations. |
| D15 | **Guide version label (user-confirmed 2026-10-11):** any guide that displays a version must show `Version <declared_version()> — <Month Year>` (centered subtitle), sourced **dynamically** from `audio_suite_shared.project_version.declared_version()` — never a literal; `<Month Year>` is the generation month. In scope: **(a)** every guide regenerated because a bug fix changed its content, **and (b)** the **four guides carrying a stale hardcoded label**, normalised to the dynamic form regardless of bug impact — `lyrics_manager` (`Version 2.0 — September 2026`), `tag_editor` (`Version 1.0 — September 2026`), `tag_field_updater` (`Version 1.0 — August 2026`), `undo_tag_edits` (`Version 1.0 — September 2026`). All other guides are untouched. Generators may import the shared helper because `audio_suite_shared` is installed in the `.venv` used to run them. | User instruction; D12 single-source version rule; removes the inconsistent `2.0` vs `1.0` labels. |

| D16 | The S3 gate exposed a **pre-existing test-harness hang** (not an M4/M5 item): `file_reorganizer/tests/test_app.py::TestExecuteFlow::test_execute_thread_runs_in_undo_batch_and_finishes` called the real `_finish` → `ui_common.show_message(MagicMock root)` → `tk.Toplevel(MagicMock)` loops forever in `BaseWidget._root` (each `.master` access on the mock yields another truthy mock). It stayed green only because a sibling test made a **bare global assignment** `ui_common.show_message = MagicMock()` that leaked for the whole session; S2 correctly converted those to `monkeypatch.setattr` (global AGENTS §7 D3), un-masking the victim. Fixed by stubbing `ui_common.show_message` in that test via `monkeypatch.setattr`. User instruction (2026-10-12): "find the problem and fix it; regardless of when it occurred." | User instruction; discovered empirically running the S3 Definition-of-Done gate (pytest hung at ~55%). |

Decisions D6/D7 were confirmed with the user on 2026-10-11; D16 was added during
execution on 2026-10-12. See §4 for the resolved list and the two items to
establish empirically during implementation.

---

## 2. Traceability matrix

| Report finding | Severity | Plan item(s) | Sprint |
|---|---|---|---|
| H1 — ReplayGain peak written in dBFS, not linear | HIGH | G1.1 | S1 |
| H2 — `silence_trimmer` empties a fully-silent source | HIGH | G1.2 | S1 |
| H3 — driver argv ignored by 4 GUI tools | HIGH | G2.1–G2.4 | S2 |
| M2 — `album_art_normalizer` `--size` never consumed | MED | G2.5 | S2 |
| M1 — `resolve_and_apply` can return `None` | MED | G4.1 | S4 |
| L3 — `album_art_sync` per-file embed catch too narrow | LOW | G4.2 | S4 |
| M4 — MFC same-stem/different-ext collision + `-y` | MED | G3.1 | S3 |
| M5 — `file_reorganizer` overwrites existing destination | MED | G3.2 | S3 |
| M3 — negative-coordinate window geometry never restores | MED | G5.1 | S5 |
| M6 — `lossless_gain` mislabels gain-saturated MP3 | MED | G5.2 | S5 |
| L1 — unreachable `FileNotFoundError` arm | LOW | G6.1 | S6 |
| L2 — `library_stats` cache DB has no `auto_vacuum` | LOW | G6.2 | S6 |
| Report "not independently re-verified" list (9 items) | ? | G7.1–G7.9 | S7 |
| Version bump 1.0.0 → 1.0.1 (first maintenance release) | — | G8.4 | S8 |
| Per-file `1.0.1` change note on every edited file (D14) | — | G8.4, G8.5 | S8 |
| Bug-affected + 4 hardcoded-label guides show version `1.0.1` (D15) | — | G8.2 | S8 |
| Full gate + guides + CHANGELOG + plan close | — | G8.1–G8.3, G8.5, G8.6 | S8 |

---

## 3. Global Definition of Done

### 3.1 Gate (six commands, after every sprint)

```powershell
utilities\run_gate.ps1
```

which executes, stopping at the first failure (identical to the `CONTRIBUTING.md`
block `tests/test_readme.py::gate_commands` parses — **do not add a 7th line**):

1. `python -m compileall -q -f . -x '(^|/)(\.venv|\.git)/'`
2. `python -m ruff check .`
3. `python -m ruff format --check .`
4. `python -m mypy .`  ← the gate is the **bare** `mypy .`, never per-file (project AGENTS)
5. `$env:PYTHONUTF8='1'; python -X utf8 -m bandit -r . -x ./.venv -c pyproject.toml`
   ← verdict = the **severity** block (0 High / 0 Medium), never the exit code
6. `python -m pytest -q`  ← bare run; coverage captured in the **same shell block** (AGENTS §6.10)

Baseline at HEAD: pytest green, 0 warnings, coverage ~90.5 %, mypy 0, bandit
0 High / 0 Medium, `ruff format --check` green. The plan holds that baseline.

### 3.2 Reproduction-first discipline (applies to every fix item)

1. Reproduce the defect through the **real entry point** (write the one-command
   probe into the completion log before editing).
2. Write the regression test; run it **red** with the fix absent (negative
   control via SHA-256-verified backup restore, D10).
3. Apply the fix; run the test green; then the full gate.

### 3.3 Outcome-correctness rule (H1, H2, any audio-path item)

Tests must assert the **actual transformed outcome** — decode the output /
read the written tag and measure it — never a round-trip of the same internal
state the code just wrote (project AGENTS "Audio correctness is release-blocking").

### 3.4 Guide Update Protocol

- Edit the **generator** (`user_guides/individual_programs/<module>/generate_guide.py`
  or a suite-overview generator), run it from its own directory, then
  `python -m pytest tests/test_user_guide_hygiene.py -q`.
- Never hand-edit a `.docx`/`.pptx`. `.md` references are edited directly.
- A sprint records its guide touchpoints explicitly, or "none — internal/test-only".
- Regeneration diffs are triaged at **zip-entry** level (project AGENTS).
- **Version label (D15):** any guide that displays a version must show
  `Version <declared_version()> — <Month Year>` (centered subtitle under the
  title), sourced **dynamically** from
  `audio_suite_shared.project_version.declared_version()` so a later bump needs
  no further generator edit. In scope: every guide regenerated because a bug fix
  changed its content, **plus** the four stale hardcoded-label guides
  (`lyrics_manager`, `tag_editor`, `tag_field_updater`, `undo_tag_edits`)
  normalised regardless of bug impact. Guides with no version label, and any
  other guide whose content did not change, are left alone.

### 3.5 CHANGELOG rule

Every **user-visible** change gets a bullet, and the release's changes are
recorded **explicitly under the versioned heading `## [1.0.1] - <date>`** in
`CHANGELOG.md` (not left only under `## [Unreleased]`), with test-only / internal
changes excluded. Because this plan *is* the 1.0.1 release, entries are written
under `## [1.0.1]` as each change ships; `## [Unreleased]` is reduced to the
explicitly-empty placeholder at G8.4.
`tests/test_user_guide_hygiene.py::TestChangelogHygiene` must stay green.

### 3.6 Test conventions

- One test file per source module (project AGENTS naming rule); lock tests may
  live in root `tests/` where cross-cutting.
- Positive contracts, not empty negative assertions, for side-effecting
  branches (project AGENTS §7).
- Strict typing: no `# type: ignore` (carve-outs only via existing overrides).

### 3.7 Per-file change note (D14)

Every hand-edited first-party file this plan touches carries a note naming the
release and a one-line summary of the change in that file.

- **Python (`.py`):** append a **final paragraph to the module docstring**:
  ```
  Changed in 1.0.1: <brief summary of this file's change>.
  ```
  If a module has no docstring, add a minimal one first. One consolidated
  sentence per file (not per hunk); if a file changes across several sprints,
  keep a single sentence covering the file's net change.
- **Comment-bearing non-Python (`.toml`, `.iss`, `.ps1`, `.ini`, `.cfg`,
  `.md`):** the same sentence in that format's comment syntax (`#`, `;`,
  `<!-- -->`).
- **Comment-less formats (`.json`):** cannot carry the note — list the file in
  the G8.5 exceptions table and record its change in the CHANGELOG only.
- **Scope:** all hand-edited first-party files — tool `*.py`,
  `audio_suite_shared/**`, `master_driver/**`, tests, and edited config
  (`pyproject.toml`, `packaging/*`). **Excludes** regenerated binary artifacts
  (`user_guides/**/*.docx|.pptx`) and `CHANGELOG.md` itself (the versioned
  record).
- Applied as each file is edited (S1–S7), not batched at the end.
- **Verified by G8.5**, not by eye.

---

## Sprint S1 — Audio data integrity (H1, H2)

**Findings closed:** H1, H2. **Guides:** audit ReplayGain + Silence Trimmer
guides. **CHANGELOG:** 2 Fixed bullets.

### G1.1 — H1: write linear peak, not dBFS

- **Problem:** `replaygain_analyzer/core/ffmpeg_metrics.py:108` parses
  `Peak: <x> dBFS`; `file_processor.py:176` (`f"{file_data['peak']:.6f}"`) and
  `gain_calculator.py:23,42`/`file_processor.py:157-163` format that dBFS value;
  `tag_writer.py:59,61,73-74` write it while their docstrings promise linear
  `'0.912345'`.
- **Change:** convert true peak from dBFS to linear amplitude
  (`10 ** (peak_dbfs / 20)`) at **one** boundary (the point the measurement is
  turned into the tag string — choose either `ffmpeg_metrics` returning both, or
  a single `_dbfs_to_linear` helper invoked in `file_processor`/`gain_calculator`
  so the album `max` is taken over linear values). Do **not** change the
  measurement API silently; if `ffmpeg_metrics` keeps dBFS, add the conversion
  where the tag string is built and document it.
- **Repro:** take a known file, run the tool live, read
  `REPLAYGAIN_TRACK_PEAK`; confirm it is ≤ 0 (dBFS) pre-fix.
- **Tests — `replaygain_analyzer/tests/` (update `test_tag_writer.py` /
  `test_replaygain_pipeline.py` and add an outcome test):**
  - A synthetic measurement with known dBFS (e.g. −6.0 dBFS) must produce
    `≈ 0.501187` (assert to 5 dp), and album max must pick the loudest **linear**
    peak, not the largest dBFS.
  - Any pre-existing test asserting the dBFS string is updated in lockstep (D4).
- **Guides/CHANGELOG:** audit `replaygain_analyzer/generate_guide.py` for any
  peak-units text; regenerate if changed; CHANGELOG Fixed bullet.
- **Acceptance:** new outcome test green; negative control red without the fix;
  ReplayGain package suite + full gate green.

### G1.2 — H2: never write an empty file over a fully-silent source

- **Problem:** `silence_trimmer/core/trimmer.py:67-95` — for a wholly silent
  file `start_trim == end_trim == len(audio)`, so `total_trim` passes the
  `== 0` guard and `trimmed = audio[len:0]` is an **empty** `AudioSegment`
  (not `None`); `core/file_processor.py:138` treats "not None" as
  "export it" and `:146` copies the empty output over the original.
- **Change (belt-and-braces):**
  1. In `trimmer.py`, when the computed trim would leave `len(trimmed) == 0`,
     return a `TrimResult` with `trimmed=None` and a non-destructive status
     (e.g. `SKIP` / "Entire file is silence — skipped"). Keep `has_silence`
     semantics explicit.
  2. In `file_processor.py:138`, additionally require `len(result.trimmed) > 0`
     before export.
- **Repro:** generate a fully-silent WAV (pydub) and run the tool live
  (non-dry-run); confirm the source is emptied pre-fix.
- **Tests — `silence_trimmer/tests/` (`test_trimmer.py` + a `test_file_processor.py`
  outcome test):**
  - `trim_and_fade` on an all-silent segment returns `trimmed is None` and a
    skip status.
  - Outcome test: process a temp fully-silent file; assert the source is
    byte-unchanged / non-zero length, no `trim_edit` undo snapshot recorded, and
    the reported status is skip.
  - Positive control: a file with real silence at the ends still trims and
    preserves the audio body.
- **Guides/CHANGELOG:** audit `silence_trimmer/generate_guide.py` for wording
  about fully-silent files; regenerate if changed; CHANGELOG Fixed bullet.
- **Acceptance:** outcome test green, negative control red without the fix;
  package suite + full gate green.

---

## Sprint S2 — Driver launch contract (H3, M2)

**Findings closed:** H3, M2. **Guides:** Master Driver guide + the four tool
guides + Album Art Normalizer guide (audit/regenerate). **CHANGELOG:** H3 + M2
Fixed bullets (if user-visible).

### G2.0 — Confirm the driver→GUI pre-fill mapping (D7)

- Contract is fixed (consume-and-pre-fill, D7). Read the Master Driver guide
  (`master_driver/generate_guide.py`), the `arg_builder` arg layouts,
  `tool_plugin.py` manifests (`standalone` flags), and each app's variable
  model; determine, per tool, which driver args have a real widget to pre-fill.
  Record the confirmed mapping in the completion log **before** writing code.
  If a tool genuinely has no consumable setting for an arg, that arg is dropped
  from `arg_builder` in the same change (so the builder does not advertise a
  no-op) — record the drop with its rationale.

### G2.1 — H3: `file_reorganizer` consumes its argv

- **Problem:** `File_Reorganizer.pyw` → `file_reorganizer/__init__.py::main()`
  → `app.py::main()` (`:644-647`, no parameters, no argv parse); the tool has no
  `utils/cli_args.py`. Driver passes `[path, --output-dir, --action,
  --specific-pattern, --various-pattern]` via `start_python_script`
  (`batch_orchestrator.py:227`).
- **Change:** add `file_reorganizer/utils/cli_args.py` (+ args dataclass) and a
  `_apply_cli_args` on the app that pre-fills the corresponding widgets/config
  keys, wired through `parse_cli_args` in the `.pyw` (mirror `Tag_Editor.pyw`).
  If a route already reads `suite_config`, keep the single update function the
  widget events use (project AGENTS pre-fill rule).
- **Tests:** new `file_reorganizer/tests/test_cli_args.py`; a captured-argv
  launcher test asserting the parsed values reach the app attributes; update
  `master_driver/tests/test_runner.py` if it pins the arg layout.
- **Acceptance:** launching via the driver's exact argv pre-fills the app;
  full gate green.

### G2.2 — H3: `tag_field_updater` consumes its argv

- **Problem:** `Tag_Field_Updater.pyw` → `ui/app.py::main(directory=None)`
  (`:289-309`, no argv parse). `tag_field_updater/__main__.py` DOES parse argv
  (verified) — the `.pyw` path does not.
- **Change:** reuse the `__main__` parser (or add `utils/cli_args.py`) and wire
  `parse_cli_args` into the `.pyw`, pre-filling the directory + mode.
- **Tests:** parser tests + a launcher test; mirror the `__main__` contract.

### G2.3 — H3: `library_stats` consumes its argv

- **Problem:** `Library_Stats.pyw` → `LibraryStatsApp(root)` (no args).
- **Change:** add a parser for `[path, --incremental, ...]` (per
  `arg_builder._build_utility_tool_args`), wire the `.pyw`, pre-fill the app.

### G2.4 — H3: `cd_ripper` consumes its argv

- **Problem:** `CD_Ripper.pyw` → `CDRipperApp(root)` (no args); driver passes
  `--output-dir --format --tracks --cue`.
- **Change:** add a parser + pre-fill; note CD ripping has no "folder" arg —
  honour the output/format/tracks settings only.

### G2.5 — M2: `album_art_normalizer` consumes `--size`

- **Problem:** `arg_builder.py:224-232` emits
  `[path, "0", mode_flag, start_flag, end_flag, "--size", value]`;
  `utils/cli_args.py:32-45` has no `--size` in `ACCEPTED_HANDSHAKE` and no
  field; `app.py:144-164` never sets `self.resolution`.
- **Change:** add a `size` field + `--size` acceptance (and consume the stray
  `"0"` positional deliberately), then map it onto `self.resolution` via the
  app's `RESOLUTION_MAP`/combobox update path. Confirm the driver's
  `state.art_normalizer_size` value format matches a real `RESOLUTION_MAP` key
  (D7); if it is a pixel dimension, translate to the nearest key.
- **Tests:** parser test for `--size`; app test asserting `self.resolution`
  ends on the expected key from the driver argv; update
  `master_driver/tests/test_runner.py` expectations if needed.
- **Guides/CHANGELOG:** if the pre-fill is user-visible, CHANGELOG Fixed bullet.

---

## Sprint S3 — Output/file collision data loss (M4, M5)

**Findings closed:** M4, M5. **Guides:** MFC + File Reorganizer guides.
**CHANGELOG:** per chosen policy (likely 2 Fixed bullets).

### G3.1 — M4: MFC must not silently overwrite a same-stem output

- **Problem:** `music_format_converter/core/file_processor.py:386-388` maps
  `song.flac` and `song.wav` (same folder) both to `song.mp3`;
  `core/ffmpeg_params.py:177` passes `-y`, so the second run overwrites the
  first with no check (`_convert_and_verify:280` only checks returncode/exists).
  (Subdirectories ARE preserved — verified — so the trigger is same-folder,
  same-stem, different-extension only.)
- **Change (D6: skip-and-warn):** track the output paths produced **in this
  run** (a set) and, when a computed output path has already been produced,
  skip with a warning instead of overwriting. Do **not** disable `-y` for
  legitimate single-file re-runs — scope the guard strictly to intra-run
  collisions (a pre-existing output from a prior run is a normal re-conversion).
- **Repro:** temp folder with `song.flac` + `song.wav`, convert to mp3 live;
  confirm one output remains pre-fix.
- **Tests — `music_format_converter/tests/test_file_processor.py`:** outcome
  test (two same-stem inputs → two distinct outputs, or one skip reported);
  positive control (distinct stems unaffected); `--delete-originals` case.
- **Guides/CHANGELOG:** MFC guide wording if behaviour is documented.

### G3.2 — M5: File Reorganizer must not overwrite an existing destination

- **Problem:** `file_reorganizer/core/engine.py:294-307` `_perform_action`
  calls `shutil.copy2`/`shutil.move` to `target` with no existence check;
  `record_file_reorg_snapshot(:300)` records only source/dest paths and stores
  no destination bytes (D5), so an overwritten pre-existing file is
  **unrecoverable**.
- **Change (D6: skip-and-warn):** before `_perform_action`, if `target` already
  exists and is not the source, skip with a warning and report it (never a
  silent overwrite). `record_file_reorg_snapshot` is taken only for the real
  move. Prevention is mandatory here because the undo record stores no
  destination bytes (D5), so an overwrite would be unrecoverable.
- **Repro:** two sources resolving to the same target; run live; confirm the
  first target's content is lost pre-fix.
- **Tests — `file_reorganizer/tests/test_engine.py`:** outcome test asserting
  the pre-existing target is preserved (or, if overwrite, restorable) and the
  skip/collision is reported; both `copy` and `move`.
- **Guides/CHANGELOG:** reorganizer guide wording if documented.

---

## Sprint S4 — Error-handling contract (M1, L3)

**Findings closed:** M1, L3. **Guides:** none expected (internal).
**CHANGELOG:** Fixed bullet for M1 if user-visible.

### G4.1 — M1: `resolve_and_apply` must honour `-> ArtSyncReport`

- **Problem:** `album_art_sync/core/pipeline.py:88`
  `@handle_audio_errors(reraise=False, ...)` returns `None` on any exception
  (`exceptions.py:489-497`), but the function is annotated `-> ArtSyncReport`;
  `cli.py:82` then reads `report.total_files` → `AttributeError`.
- **Change (D8):** remove/relax the swallow so the function returns a failure
  `ArtSyncReport` (or re-raises `AudioSuiteError` and callers handle it).
  Ensure both the CLI (`cli.py`) and GUI (`album_art_sync/app.py`) paths cope.
- **Repro:** force an internal error (e.g. monkeypatch a source call to raise)
  through the CLI; confirm the `AttributeError` pre-fix.
- **Tests — `album_art_sync/tests/`:** assert a failing run yields a
  `success=False` report whose fields are readable, and the CLI exits with a
  clean error line (not a traceback).

### G4.2 — L3: broaden the per-file embed catch

- **Problem:** `album_art_sync/core/artwork_applier.py:100,119` catch only
  `(OSError, ValueError)`, but `embed_artwork` raises `AudioSuiteError` (via
  `handle_audio_errors(reraise=True)`), so one bad file can abort the album.
- **Change:** extend the catch to include `AudioSuiteError`; keep the
  per-file warning log/UX.
- **Tests:** a batch with one un-embeddable file continues and reports the file
  as an error without aborting the rest.

---

## Sprint S5 — Correctness & UX (M3, M6)

**Findings closed:** M3, M6. **Guides:** audit only. **CHANGELOG:** M6 bullet if
user-visible.

### G5.1 — M3: restore negative-coordinate window geometry

- **Problem:** `audio_suite_shared/platform_utils.py:267` `saved.split("+")`
  cannot parse Tk's `WxH±X±Y` when X or Y is negative (e.g. `800x600-1920+40`),
  so restore always falls back to `_center()`.
- **Change:** replace the split with a parse that handles leading `+`/`-` on
  both coordinates (small regex or manual scan after the `x`); keep the
  `_is_on_screen` guard and the malformed-string fallback.
- **Repro:** write a synthetic config value `800x600-1920+40`, call
  `setup_window` with a mock root, assert `root.geometry` is called with the
  saved string (pre-fix it is not).
- **Tests — `audio_suite_shared/tests/test_platform_utils.py`:** cases for
  `+X+Y`, `-X+Y`, `+X-Y`, `-X-Y`, malformed; and an on-screen guard case.
- **Guides/CHANGELOG:** none (internal UX fix) unless documented.

### G5.2 — M6: distinguish "no change" from "no frames" in `lossless_gain`

- **Problem:** `audio_suite_shared/lossless_gain.py:606-631` counts a frame as
  modified only when a clamped gain field actually changes; a valid MP3 fully at
  the clamp bound yields `modified == 0`, which `apply_track_gain:329-333` /
  `apply_album_gain:372-376` raise as `AudioFormatError("No valid MPEG Layer III
  frames found")`.
- **Change:** have the frame walk report **frames seen** as well as frames
  modified; raise `AudioFormatError` only when **zero frames** were walked, and
  return `0` (no change) otherwise. Update the affected callers' messages.
- **Tests — `audio_suite_shared/tests/test_lossless_gain.py`:** a synthetic
  MP3 whose frames are already at the clamp bound → no exception, returns 0;
  a genuinely frame-less file → still raises.
- **Guides/CHANGELOG:** CHANGELOG Fixed bullet only if the error is user-visible.

---

## Sprint S6 — Housekeeping (L1, L2)

**Findings closed:** L1, L2. **Guides:** none. **CHANGELOG:** none (internal).

### G6.1 — L1: make the `FileNotFoundError` arm reachable

- **Problem:** `master_driver/batch_orchestrator.py:489` catches
  `(PermissionError, OSError)` and re-raises **before** the
  `except FileNotFoundError:` arm at `:495` (FileNotFoundError ⊂ OSError), so
  the missing-script path is retried pointlessly and logged as "failed after
  retries".
- **Change:** either pre-check `os.path.exists(step.script_path)` and return
  `False` with the intended message, or move the `FileNotFoundError` arm above
  the `OSError` arm (and keep it out of `retry_on_exceptions`).
- **Tests:** a step whose script path does not exist → returns `False`, no
  retries, the "Script not found" message.

### G6.2 — L2: add `auto_vacuum` to the library cache (D9)

- **Problem:** `library_stats/library_cache.py:107-112` opens the DB without
  `PRAGMA auto_vacuum`; `remove_orphans`/`clear_dir`/`clear_all`/`INSERT OR
  REPLACE` free pages that the file never returns to the OS.
- **Change:** set `PRAGMA auto_vacuum=FULL` at schema creation and add the
  one-time legacy conversion (read → if not FULL, set + `VACUUM`, with no open
  transaction) in `_connect`.
- **Tests — `library_stats/tests/test_library_cache.py`:** new DB has
  `auto_vacuum == 1`; a delete-heavy sequence leaves `PRAGMA freelist_count == 0`
  after conversion.
- **Guides/CHANGELOG:** none (internal).

---

## Sprint S7 — Triage the unverified candidates (report §"not independently re-verified")

Each item = **reproduce → fix if defective (same change, regression test) or
close as non-defect with evidence**. No item is left "unknown".

| Item | Candidate | Package |
|---|---|---|
| G7.1 | cached-scan vs full-scan `total_files` disagree | `library_stats` |
| G7.2 | `query_aggregate` docstring omits `bpm_distribution` | `library_stats` |
| G7.3 | JSON payload lacking an `isinstance` guard | `library_stats` |
| G7.4 | delete-before-snapshot ordering | `music_format_converter` |
| G7.5 | `_wav_params_for` "auto" docstring vs behaviour | `music_format_converter` |
| G7.6 | partial output left after failure | `cd_ripper` |
| G7.7 | AccurateRip last-track window | `cd_ripper` |
| G7.8 | admin-filter re-apply guard | `audio_suite_shared/logging_setup.py` |
| G7.9 | raw `str(exc)` propagation | `audio_suite_shared/process_audio_file_inplace` |

- **Method:** for each, write the reproduction command/fixture **first**; record
  the verdict in the completion log either way. If the lead is wrong, record the
  disconfirming evidence (do not silently drop it).
- **Acceptance:** every G7.x has a recorded verdict; any confirmed defect is
  fixed with a lockstep regression test; the report file gets a dated
  correction note for any lead proven false (append-only).

---

## Sprint S8 — Release close-out

**Guides:** regenerate all touched generators. **CHANGELOG:** completeness pass
under `## [1.0.1]`. **Version:** bump to `1.0.1` + per-file `1.0.1` notes (§3.7).

### G8.1 — Full gate, fresh evidence
- Run `utilities\run_gate.ps1`; paste the full tuple into the completion log.
- Zero warnings; coverage ≥ the HEAD baseline; mypy 0; bandit 0 High / 0 Medium.

### G8.2 — Regenerate every touched user guide
- Run only the generators for modules whose user-visible behaviour changed
  (S1/S2/S3/S5); triage the regeneration diff at zip-entry level; keep only
  genuine content changes (`tests/test_user_guide_hygiene.py` green).
- **Each regenerated guide whose content changed must show
  `Version <declared_version()> — <Month Year>`** (D15, §3.4). The affected
  generators import `declared_version()`; the label is dynamic, so it reads
  `1.0.1` after G8.4 and tracks future bumps automatically.
- **Normalise the four stale hardcoded labels (D15 scope b)** even where the
  guide is not bug-affected: `lyrics_manager`, `tag_editor`, `tag_field_updater`,
  `undo_tag_edits`. Edit each `generate_guide.py` to import `declared_version()`
  and render the dynamic subtitle, then regenerate. `tag_field_updater` is in
  both sets, so it is regenerated once.
- Verify by reading each regenerated `.docx` and asserting the version subtitle
  is present (a lock reads the artifact text via `python-docx`, so a
  regenerated-but-unstamped guide fails); the expected affected-guide set is
  finalised here and asserted non-empty. At minimum the bug-driven set is
  `replaygain_analyzer` (H1), `silence_trimmer` (H2), `album_art_normalizer`
  (M2), `file_reorganizer` (H3/M5), `tag_field_updater` (H3), `library_stats`
  (H3), `cd_ripper` (H3), `music_format_converter` (M4/M6), `album_art_sync`
  (M1/L3) — narrowed at this step to those with an actual content change — plus
  the four normalisation guides above.

### G8.3 — CHANGELOG completeness
- Every user-visible bullet present **under `## [1.0.1] - <date>`** (per §3.5);
  test-only/internal changes explicitly excluded.

### G8.4 — Version bump to 1.0.1 (maintenance release; D12, D13)

- **Scheme (user-confirmed):** `MAJOR.MINOR.MAINTENANCE`. `1.0.0 → **1.0.1**` —
  the first maintenance release, wrapping the fixes in S1–S7.
- **Single source of truth:** `pyproject.toml:11` `version = "1.0.0"` → `"1.0.1"`.
  Everything downstream is derived and needs no separate edit:
  `audio_suite_shared/project_version.py::declared_version()` reads it,
  `audio_suite_shared/cli_base.py:246` (`@click.version_option`) renders
  `audiosuite, version 1.0.1`, and `packaging/build_installer.ps1:48,124-128`
  reads `[project].version` via `tomllib` and passes `/DAppVersion` to Inno Setup
  (`packaging/audiosuite.iss:20-21` defaults to `0.0.0`), so the installer
  version and `AudioSuite-Pro-Setup-1.0.1.exe` name follow automatically.
- **Change — exactly these edits:**
  1. `pyproject.toml`: the one `version` field (line 11) → `"1.0.1"`.
  2. `CHANGELOG.md`: promote the accumulated `## [Unreleased]` content under a
     new `## [1.0.1] - <release date>` heading (Keep a Changelog), leaving a
     fresh, explicitly-empty `## [Unreleased]` that
     `tests/test_user_guide_hygiene.py::TestChangelogHygiene` accepts.
  3. `packaging/BUILD_INSTALLER.md`: the `1.0.0` strings on lines 46 and 68 are
     **illustrative examples** of `-Version` output, not the live version — leave
     them unless the user wants the example refreshed to `1.0.1`; record the
     choice.
  4. `pyproject.toml` and every other hand-edited first-party file touched by
     S1–S7 carries its `1.0.1` change note (§3.7, D14).
- **Do NOT touch:** the dependency pins that happen to read `1.0.0` —
  `winaccent>=1.0.0` (`pyproject.toml:34`), `mypy>=1.0.0` (`:61`),
  `python-pptx>=1.0.0` (`:64`) — these are minimum constraints, not the project
  version (`test_project_version.py::test_a_dependency_pin_is_not_mistaken_for_the_version`
  guards the parse). The unused per-package `__version__` constants stay as they
  are (D13).
- **Tests / locks:**
  - `audio_suite_shared/tests/test_project_version.py` is version-agnostic —
    `test_reports_the_declared_version` compares `declared_version()` to the real
    `pyproject.toml`, and `test_version_is_a_plausible_release_string` checks the
    shape — confirm both stay green at `1.0.1` (no hardcoded `1.0.0`).
  - Confirm `python -c "from audio_suite_shared.project_version import declared_version; print(declared_version())"`
    → `1.0.1` and `python -m audio_suite_shared.cli_app --version` (or
    `audiosuite --version`) → `audiosuite, version 1.0.1`.
  - If no lock asserts the version is a well-formed three-token
    `MAJOR.MINOR.MAINTENANCE` string, add one (guards the scheme in D12).
- **Guides:** no literal version to chase here — guides source the version
  dynamically (D15, G8.2). The four existing **hardcoded** labels
  (`lyrics_manager`, `tag_editor`, `tag_field_updater`, `undo_tag_edits`) are all
  normalised to the dynamic form in G8.2, so none is left stale.
- **Acceptance:** version reads `1.0.1` at both consumer points; changelog lock
  green; every hand-edited file notes `1.0.1` (§3.7, verified in G8.5); full gate
  green.

### G8.5 — Verify the per-file change notes (D14, §3.7)

- Confirm every hand-edited first-party file touched by S1–S7 carries the
  `Changed in 1.0.1:` note (module-docstring paragraph for `.py`; the format's
  comment syntax otherwise).
- Add a hygiene lock in root `tests/` (sibling of the changelog/guide locks)
  that enumerates the tracked first-party files changed since the plan's base
  commit (`0349d06`) and asserts each carries the `1.0.1` marker. The
  comment-less (`.json`) and regenerated-artifact exclusions are **explicit and
  asserted non-empty**, so the scan cannot pass vacuously (project AGENTS: "a
  scan reusing an exclusion set … assert the result set is non-empty"); compute
  the changed set with `git diff --name-only 0349d06 -- <first-party paths>`,
  never by hash-embedding the fixed base.
- Negative control (D10): strip the note from one changed file → the lock fails;
  restore from a SHA-256-verified backup copy.

### G8.6 — Close the plan
- Fill every completion-log row; append an entry to the relevant historical
  plans' decision logs where this plan supersedes prior assumptions (append-only);
  set this file's status to complete.

---

## 4. Decisions resolved + remaining verification

Resolved with the user (2026-10-11):

1. **Scope (→ D1):** all confirmed findings (H1–H3/M1–M6/L1–L3) **plus** empirical
   triage of the 9 unverified candidates (S7). No feature work.
2. **Collision policy (→ D6, S3):** **skip-and-warn** for both M4 and M5.
3. **Driver→GUI pre-fill contract (→ D7, S2):** **consume-and-pre-fill** the
   driver argv in all four tools.
4. **Release version (→ D12, G8.4, S8):** `MAJOR.MINOR.MAINTENANCE` scheme;
   bump `1.0.0 → 1.0.1` as the first maintenance release, sourced solely from
   `pyproject.toml`.
5. **Guide version label (→ D15, G8.2, S8):** bug-affected guides display
   `Version <declared_version()> — <Month Year>`, sourced dynamically; the four
   stale hardcoded-label guides (`lyrics_manager`, `tag_editor`,
   `tag_field_updater`, `undo_tag_edits`) are normalised too; all other guides
   are left alone.

Still to establish **empirically during planning of the named item** (not open
product decisions):

6. **M2 `--size` mapping (G2.0 → G2.5, S2):** determine whether
   `state.art_normalizer_size` is a pixel dimension or a `RESOLUTION_MAP` key,
   then map directly or to the nearest key.
7. **M6 message/behaviour (G5.2, S5):** confirm at implementation time that the
   chosen behaviour is "no-change success, return 0" for a gain-saturated but
   valid MP3 (the default in the G5.2 item), revisiting only if reproduction
   shows a distinct user-facing status is warranted.

---

## Completion log (fill during execution — one row per item)

Format: `| Item | prio | date | reproduction + gate evidence | notes |`

| Item | prio | date | reproduction + gate evidence | notes |
|---|---|---|---|---|
| H1 — ReplayGain peak tags written in dBFS | HIGH | 2026-10-11 | Reproduced via real-pipeline probe (`apply_replaygain_tags` on real MP3s → tags `TRACK_PEAK=-6.000000`/`ALBUM_PEAK=-0.500000`). Fixed by `dbfs_to_linear` in `gain_calculator` (album max over linear) + conversion at the track tag-string boundary in `file_processor`. New outcome tests read the written tags from real files (−6 dBFS → 0.501187; album 0.944061); negative control red pre-fix (tags `-0.500000`). Gate: compileall OK, ruff check OK, format OK, mypy OK, bandit 0H/0M, pytest 8745 passed/3 skipped/30 deselected/90.60%. | Guide (`ReplayGain_Analyzer_User_Guide.docx`) regenerated with linear-peak wording; 1 CHANGELOG Fixed bullet. `tag_writer` docstrings already promised linear — untouched. |
| H2 — Silence Trimmer empties a fully-silent source | HIGH | 2026-10-11 | Reproduced live: a 1 s silent WAV went `22094 → 78` bytes with a `trim_edit` snapshot. Fixed return `trimmed=None` + SKIP when trim covers the whole length (trimmer) + `len(trimmed) > 0` guard before export (file_processor, belt-and-braces). Outcome test asserts source byte-identical, no snapshot, SKIP status; negative control red pre-fix (file truncated). `_make_audio` test fixture was all-silent (it pinned the bug) — now holds a real tone body. Gate: same as H1 row. | Guide (`Silence_Trimmer_User_Guide.docx`) regenerated with "Entire file is silence - skipped" bullet; 1 CHANGELOG Fixed bullet. |
| G2.0 — confirm driver→GUI pre-fill mapping (D7/§48) | HIGH | 2026-10-11 | Mapped each tool's `arg_builder` argv to its GUI state by tracing the real launch path (`batch_orchestrator._launch_standalone` → `start_python_script` → `*.pyw`). **file_reorganizer**: `[path, --output-dir, --action, --specific-pattern?, --various-pattern?]` → all consumable (source/dest/action/patterns); no drops, no auto-run (Preview/Execute stay explicit). **tag_field_updater**: `[path, --live|--dry]` → directory consumable; mode has no GUI control → ADD a Dry Run checkbox (D7). **library_stats**: after review, `--completeness`/`--detail` have no matching GUI control → DROP both from arg_builder AND the dead card widgets (`library_stats_completeness`/`library_stats_detail` state + card rows); consume path/incremental/refresh/export-csv/export-json. **cd_ripper**: `[--output-dir, --format, --tracks?, --cue?]` (no folder) → all consumable; `--tracks` needs a post-disc-read filter. **album_art_normalizer**: `[path, 0, mode, start, end, --size, n]` → consume `--size` (pixel dim → `RESOLUTION_MAP` display key). Rationale for drops: prefer a smaller honest CLI over a non-functional flag (D7). | User-approved scope decision (this session): tag_field_updater add Dry Run box; library_stats drop completeness+detail; cd_ripper filter tracks after disc read. |
| G2.1 — file_reorganizer consumes argv | HIGH | 2026-10-11 | Added `file_reorganizer/utils/cli_args.py` (`FileReorganizerArgs`, `parse()`, `validate_args()`). App `__init__` accepts keyword-only `directory/output_dir/action/specific_pattern/various_pattern`; `_apply_cli_args` pre-fills source/dest/action/patterns. `app.py::main()` calls `parse_cli_args(cli_args.parse)` then passes parsed values to constructor (mirrors Tag_Editor.pyw). `.pyw` unchanged. Tests: `test_cli_args.py` (10 tests: defaults, positional, full driver argv, unknown flags, validation errors); `test_app.py` (1 new: captured-argv parse→construct→assert widgets). Gate: compileall OK, ruff OK, mypy OK, bandit 0H/0M, 139 passed. | `.pyw` unchanged to preserve launcher-stub contract (`tests/test_pyw_launchers.py`). |
| G2.2 — tag_field_updater consumes argv + Dry Run checkbox | HIGH | 2026-10-11 | Added `tag_field_updater/utils/__init__.py` + `cli_args.py` (`TagFieldUpdaterArgs`, `parse()`). App: added `self.dry_run = tk.BooleanVar(value=False)` + "Dry Run (no changes written)" checkbox in directory frame; `_scan_thread` now passes `dry_run` to `processor.scan_directory`; `start_scanning` reads `dry_run.get()` on main thread. `main(directory=None)`: when directory is None, parses CLI via `parse_cli_args(cli_args.parse)`, sets directory + dry_run; when directory is given (from `__main__.py` argparse), uses it directly. Existing tests updated: `_make_shell_app` adds `dry_run`, `_scan_thread` calls pass `dry_run=False`. `test_main_without_directory_starts_and_runs` pins `sys.argv`. Tests: `test_cli_args.py` (7 tests); 169 passed. | `.pyw` unchanged; `main()` handles both CLI paths. |
| G2.3 — library_stats consumes argv + drop completeness/detail | HIGH | 2026-10-11 | Added `library_stats/utils/__init__.py` + `cli_args.py` (`LibraryStatsArgs`, `parse()`). App `__init__` accepts keyword-only `directory/incremental/refresh/export_csv/export_json`; `_apply_cli_args` sets folder_path, `_use_cache` (only when incremental=True), `_cli_refresh`, `_cli_export_csv/_json`; `_build_ui` auto-scan uses `_cli_refresh` to choose `_start_refresh` vs `_start_scan`; `_on_scan_complete` calls `_apply_cli_exports` for auto-export. `main()` added; `Library_Stats.pyw` updated to call `main()`. **Dropped** `--completeness`/`--detail` from `arg_builder.py`; removed `library_stats_completeness`/`library_stats_detail` from `app_state.py`; removed card widgets from `library_stats_card.py`. Tests: `test_cli_args.py` (8 tests); `test_runner.py` removed 2 tests; `test_app_state.py` removed 4 tests; `test_ui_cards.py` updated fixture; 180+678 passed. | `_use_cache` only set when `incremental=True` to preserve existing default (True). |
| G2.4 — cd_ripper consumes argv + track filter | HIGH | 2026-10-11 | Added `cd_ripper/utils/__init__.py` + `cli_args.py` (`CdRipperArgs`, `parse()`, `parse_track_selection()`, `FORMAT_DISPLAY` map). App `__init__` accepts keyword-only `output_dir/format/tracks/cue`; `_apply_cli_args` calls `setup_tab.apply_cli_settings(...)` and stores `cli_track_filter` in `state`. `SetupTab.apply_cli_settings` pre-fills `out_var`/`fmt_var`/`cue_var` (routes through `on_out_dir_changed`/`on_fmt_changed` per AGENTS pre-fill rule). `SetupTab._proceed` filters `state["tracks"]` by `cli_track_filter` before rip. `main()` added; `CD_Ripper.pyw` updated. Tests: `test_cli_args.py` (12 tests: defaults, full driver argv, track parsing, format map); 420 passed. | `FORMAT_DISPLAY` maps lowercase driver values to GUI display names (Opus stays "Opus"). |
| G2.5 — album_art_normalizer consumes --size | HIGH | 2026-10-11 | Added `size` field + `--size` scanning to `album_art_normalizer/utils/cli_args.py::parse()`. Added `_size_to_resolution()` helper in `app.py` (maps pixel dim `"800"` → `"800×800"` key via `RESOLUTION_MAP` check). `_apply_cli_args` sets `self.resolution` from `--size` BEFORE the folder-path early return. Tests: `test_cli_args.py` (3 new: size parsed, absent default, missing value); `test_app.py` (3 new: size→resolution on real app, bare launch default, helper unit test); 29 passed. | `×` is U+00D7 (multiplication sign). |
| G3.1 — M4: MFC same-stem output collision | MED | 2026-10-12 | Reproduced via the real `run_conversion` entry point: a temp folder with `song.flac` + `song.wav` converted to mp3 gave `converted=2, skipped=0, outputs=['song.mp3']` — the second source overwrote the first with no check. Fix: a per-run `produced_outputs: set[str]` created in `run_conversion` (closure-captured by `_process_with_undo`), claimed by module helpers `_claim_output_path`/`_release_output_path` under the existing batch `lock` immediately after the dry-run return; the claim is released in both `except` arms on failure. A collision emits `[SKIPPED] … output … already produced from another source in this run` via `on_progress(n_converted=0, n_skipped=1, …)` and returns. `-y` is **not** disabled (legit single-file re-runs still overwrite — D6 scope = intra-run only). Post-fix repro: `converted=1, skipped=1`, one `song.mp3`. New tests `TestSameStemCollision` in `music_format_converter/tests/test_file_processor.py` (collision→1 convert + skip + message; positive control distinct stems→2; `--delete-originals` keeps the colliding source, deletes only the converted one). Gate: compileall OK, ruff check OK, format OK, mypy 0/476, bandit 0H/0M/41L pre-existing, pytest **8797 passed / 3 skipped / 30 deselected / 90.47%**. | D14 note added to `file_processor.py` + the test module docstring. 1 CHANGELOG Fixed bullet. Guide: added a Troubleshooting bullet ("Two sources produced the same output name") to `music_format_converter/generate_guide.py`, regenerated the `.docx` (content verified: new phrase present), `tests/test_user_guide_hygiene.py` 11 passed; generator carries a D14 note. |
| G3.2 — M5: File Reorganizer overwrites an existing destination | MED | 2026-10-12 | Reproduced via the real `FileReorganizer.run` entry point: two tagged FLACs resolving to `dst/Song.flac` with a pre-existing target gave `scanned=2, processed=2, skipped=0, existing content preserved: False` (target bytes destroyed, no undo bytes — D5). Fix: `_perform_action` now returns `bool` and skips when `target` exists and is not the source (compared via `os.path.normcase(os.path.abspath(...))`, not `os.path.samefile`, which raises when the source is absent); `run()` counts such cases in `files_skipped` and reports `SKIPPED (destination exists): <target_rel>` instead of `files_processed`; the undo snapshot is taken only for a real move. Post-fix repro: `processed=0/1, skipped=1/2`, pre-existing content preserved. New tests in `file_reorganizer/tests/test_reorganizer.py` (plan named a non-existent `test_engine.py`): `TestPerformActionCollision` (copy skip + no snapshot; move skip; missing-target positive control) and `TestEngineCollisionIntegration` (pre-existing target preserved; two-source copy collision; two-source move collision). Gate: same as G3.1 row. | D14 note added to `engine.py` + the test module docstring. 1 CHANGELOG Fixed bullet. `_perform_action` return value is additive — the only non-test caller is `run()`. Guide: **the "Conflict behavior" bullet was stale** (claimed the engine "delegates destination handling to the underlying copy/move operation") — rewritten to state existing destinations are skipped, not overwritten; the "Skips include…" sentence and the "Files are skipped" troubleshooting bullet now list destination-exists. `file_reorganizer/generate_guide.py` regenerated; `.docx` content verified; hygiene test 11 passed; generator carries a D14 note. |
| S3 gate blocker (pre-existing, discovered) — full suite hung at ~55% | HIGH | 2026-10-12 | During the S3 DoD gate, the bare suite **hung** (no timeout; last write 46 min stale) at `file_reorganizer/tests/test_app.py::TestExecuteFlow::test_execute_thread_runs_in_undo_batch_and_finishes` — reproducible in isolation. `pytest -o faulthandler_timeout=20` dumped the stack: `_finish` (app.py:684) → `ui_common.show_message` (ui_common.py:619) → `tk.Toplevel(MagicMock)` → `BaseWidget._root` (tkinter `while w.master: w = w.master`) → unbounded child-mock construction in `unittest.mock._mock_set_magics`. Root cause: the test calls the real `_finish` with the `_shell_app` MagicMock root and never stubbed the modal; it passed at the initial commit only because `TestValidationGuards` made a bare global assignment `ui_common.show_message = MagicMock()` that leaked session-wide, and S2 converted those to `monkeypatch.setattr` (correct per global AGENTS §7 D3), un-masking the victim. Fix: stub `ui_common.show_message` in that test via `monkeypatch.setattr` (sibling-test pattern), + D14 note. Recorded as decision **D16**. Gate: full bare suite now green (8797 passed), no other `_finish()` callers and no remaining bare `show_message =` leaks found. | User instruction: fix regardless of when it occurred. Not user-visible → no CHANGELOG bullet. |
| S4 — Error-handling contract (M1, L3) | MED | 2026-10-12 | Reproduced both pre-fix via CliRunner probes (D2, real `cli` entry point): **M1** — patching `source_resolver.resolve` to raise gave `ERROR … [AudioAnalysisError] art_sync_resolve_and_apply: boom …` then `FATAL error in Album Art Sync: 'NoneType' object has no attribute 'total_files'` at `cli.py:82`, exit 0, `errors=-1`; **L3** — an `AudioSuiteError` from `embed_artwork` escaped the per-file loop, batch order `['bad.mp3']` only, `good.mp3` never processed. Fixes (D8): G4.1 removed the `@handle_audio_errors(reraise=False)` swallow in `pipeline.py::resolve_and_apply` and wrapped the operational body in `try/except Exception` that maps via `map_to_audio_error`, logs a clean `logger.error` line (`logger.debug` keeps the full traceback off the console) and returns a failure `ArtSyncReport` (never `None`); G4.2 added `AudioSuiteError` to both `except (OSError, ValueError, …)` catches in `artwork_applier.py`. GUI path unaffected (`app.py` calls `resolve`/`apply_artwork` directly, already guarded) → no `cli.py`/`app.py` change. New tests: `TestResolveAndApplyErrorContract` (2) in `test_pipeline.py`, `TestAlbumArtErrorContract` (1) in `test_cli.py`, `TestArtworkApplier::test_audiosuite_error_for_one_file_does_not_abort_others` (1) in `test_album_art_sync.py`; negative control (SHA-256-backed break/restore): all 4 red pre-fix (M1 re-raise → 3 red incl. the CLI `AttributeError`; L3 narrowed tuple → batch-abort red). Gate: compileall OK, ruff check OK, format OK, mypy 0/476, bandit 0H/0M/41L pre-existing, pytest **8801 passed / 3 skipped / 30 deselected / 90.47%**. | D14 note added to `pipeline.py`, `artwork_applier.py`, and the three test modules. 2 CHANGELOG Fixed bullets (M1 + L3 — both user-visible). Guides: none (internal error handling; happy path unchanged). |
| G5.1 — M3: negative-coordinate window geometry never restores | MED | 2026-10-12 | Reproduced via the real `setup_window` entry point (mock root, `sys.platform="win32"` with the monitor probe forced to fail so `_is_on_screen` trusts the position): saved `800x600-1920+40` → `saved.split("+")` = `['800x600-1920', '40']` (<3 parts), so `root.geometry` was called with the centred `800x600+1520+240`, **not** the saved string. Fix: a new module-level `_parse_geometry_origin` (regex `^=?(\d+)x(\d+)([+-]\d+)([+-]\d+)$`) parses Tk's `WxH±X±Y` including signed X/Y and an optional `=` prefix, replacing the `split("+")`/`len>=3` gate; the `_is_on_screen` guard and the malformed→`_center()` fallback are retained. Tests: `TestSignedGeometryRestore` (all four sign combos restore, `=` prefix, malformed→centre, parsed-but-off-screen→centre, direct-parser parametrization incl. `-1920`). Negative control (SHA-256-backed break/restore): 12 platform + 3 lossless = **15 red** pre-fix; the 7 platform malformed/off-screen guards + 2 lossless "frameless still raises" stayed green (the fix narrows behaviour, does not remove guards); both files restored hash-verified. Gate: compileall OK, ruff check OK, format OK, mypy 0/476, bandit 0H/0M/41L pre-existing, pytest **8829 passed / 3 skipped / 30 deselected / 90.61%** (`platform_utils.py` 100%). | UX-only; plan G5.1 = no guide/CHANGELOG change. D14 note appended to the module + test docstrings. |
| G5.2 — M6: gain-saturated MP3 misreported as "no valid frames" | MED | 2026-10-12 | Reproduced via the real `apply_track_gain` entry point: a valid tone MP3 driven to `+1000 dB` (every `global_gain` field = 255) then re-applied `+6 dB` raised `AudioFormatError: No valid MPEG Layer III frames found` (a false failure). Fix: `_walk_frames` now returns frames *walked*; `_modify_mp3_gains` returns `(frames_seen, modified)`; `apply_track_gain`/`apply_album_gain` raise only when `frames_seen == 0`, otherwise log "already at the gain limit" and return `0`/`{path: 0}` with **no** undo snapshot. Tests: `TestGainSaturatedNoChange` (upper + lower clamp → 0 + `mock_snap.assert_not_called()`; album saturated → `{path: 0}`; frameless still raises for track and album). Negative control (SHA-256-backed break/restore): 3 red pre-fix; the two frameless-raises tests stayed green; files restored hash-verified. Gate: same tuple as G5.1 (`lossless_gain.py` 96%). | User-visible (a batch marked a good file errored) → 1 CHANGELOG Fixed bullet. Consumers `replaygain_analyzer`, `music_format_converter`, `audio_normalizer` already catch `AudioFormatError` → no change needed. D14 note in module + test docstrings. Guides: audit only — no guide documents the saturated-file error (the ReplayGain "Lossless gain failure" bullet stays accurate for genuinely frame-less files), so **no regeneration**. |

---

## Deferred backlog (recorded, NOT executed)

| # | Item | Why deferred |
|---|---|---|
| B1 | The report's core "suggested priority" ordering beyond triage | Delivered by sprint ordering; no extra code item. |
| B2 | Any G7.x candidate proven a **non-defect** | Closed with evidence, not fixed. |
| B3 | Broader cross-tool `cli_args` unification / a shared positional parser | Refactor, not a defect fix (minimal-diff). |
| B4 | Migrating `library_stats` off SQLite to another store | Redesign; out of scope. |
