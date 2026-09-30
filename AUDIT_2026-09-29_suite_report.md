# Independent Re-Audit Report — AudioSuite-Pro

**Date:** 2026-09-29
**Subject commit:** `cfe9e79` ("B4: stop writing the live Windows Accent back
into the PALETTES table")
**Audit type:** Independent re-audit, using the **same criteria and the same
21-finding rubric** as the original engineering audit of `e729626`
(2026-09-26), whose findings were remediated by
`PLAN_iteration5_remediation.md` (closed 2026-09-28) with follow-on work in
`PLAN_iteration6_followups.md` (Sections A and B closed 2026-09-29).
**Criteria applied:** gate integrity and measurement honesty; code quality,
readability and maintainability; test depth and correctness; documentation,
packaging and dependency hygiene; platform reach; CLI discoverability; and
market-leader capability comparison.
**Status:** Report only. No code was changed; no remediation plan is attached
here. The remediation plan derived from this report lives in
`PLAN_iteration7_remediation.md` (same date).

---

## 1. Executive summary

The suite is in a **materially different and substantially better state** than
when the original audit was written. All six Phase Gate commands pass. All 21
original findings are closed, 20 of them verified closed and one (the Linux CI
leg) formally closed as *not applicable* by maintainer decision. The two
highest-risk classes the original audit surfaced — silent measurement lies, and
tests that assert shape instead of outcome — have been genuinely eliminated
rather than papered over.

The dominant finding of this re-audit is a **structural one**: the original
audit fixed the two *instances* of near-verbatim duplication it named
(`key_detector`/`mood_analyzer` apps, and the two file-processor twins) but not
the *class*. Independent measurement confirms both named pairs were fixed
(0.942 → 0.515 and 0.709 → 0.609) while three adjacent families that were
correctly out of the sanctioned blast radius (`AGENTS.md` §2) remain at
0.79–0.93 similarity, the largest sharing ~395 significant lines. The same is
true of the CLI contract: `G2` established a golden registration test but did
not extend it to flag-level parity, and a flag advertised in the CLI's own
docstring does not exist.

Nothing found in this re-audit is a *gate* defect. Every remaining item is a
quality, coverage-of-surface, or capability gap, and none of them invalidates
the suite's claim to be honestly measured.

**Headline numbers**

| Metric | Audit baseline (`e729626`) | Now (`cfe9e79`) | Direction |
|---|---|---|---|
| Phase Gate — all six commands | failing on 2 of 6 | **all 6 pass** | fixed |
| Test suite | 6,978 passed / 5 skipped | **7,556 passed / 3 skipped / 30 deselected** | +578 net, skips −2 |
| Coverage (honest denominator) | 78.26% (package omitted) | **79.20%** (`fail_under=75`, held) | honest, not fitted |
| `mypy --strict` | clean / 448 files | **clean / 452 files** | held |
| `bandit` | 0 High / 0 Medium / 51 Low | **0 High / 0 Medium / 51 Low** | held |
| Typing density | not measured | **99.5% of 2,215 defs fully annotated** | strong |
| Production duplication (≥12-line blocks) | 70.9% and 94.2% pairs named | **2.18% of significant lines** | fixed at the named sites |
| Tool count | 27 | **27** | held |
| Licence / README / CHANGELOG / CONTRIBUTING / SECURITY | **none existed** | **all present** | fixed |

---

## 2. Phase Gate — full results

Every command in `PLAN_iteration5_remediation.md` §"Phase Gate" was run from a
clean tree on the audit host (Windows, Python 3.14.7).

| # | Command | Result | Verdict |
|---|---|---|---|
| 0 | `python -m compileall -q -f . -x '(^\|/)(\.venv\|\.git)/'` | exit 0 | **pass** |
| 1a | `python -m ruff check .` | `All checks passed!` | **pass** |
| 1b | `python -m ruff format --check .` | `757 files already formatted` | **pass** |
| 2 | `python -m mypy .` | `Success: no issues found in 452 source files` | **pass** |
| 3 | `bandit -r . -x ./.venv -c pyproject.toml` | **0 High / 0 Medium / 51 Low**, 74,072 LOC | **pass** |
| 4 | bare `python -m pytest -q` | **7556 passed, 3 skipped, 30 deselected**, 43 warnings, 180.57s | **pass** |
| 5 | Coverage gate | `Required test coverage of 75.0% reached. Total coverage: 79.20%` | **pass** |
| 6 | Staged secret scan (5 patterns, incl. `*_key` suffix / 32-hex / 44+ base64 / PEM) | no secrets; hits are documentation prose, the GPL-3.0 licence SHA-256 lock, and a test fixture | **pass** |

The three remaining skips are individually attributable and each names its
platform constraint — they are not the mass-skip the original audit's finding
#18 described:

- `tests/security/test_input_validator.py:143` — symlinks unsupported on this
  filesystem
- `audio_normalizer/tests/test_setup_tab.py:158` — broken Tcl/Tk slider update
- `audio_suite_shared/tests/test_key_manager.py:64` — Unix-only permission check

**Verdict: the gate is trustworthy.** This is the single most important thing
the remediation achieved, because every other claim in this report is produced
by these commands.

---

## 3. Verification of the 21 original findings

Each finding was re-checked against the current tree. The "Verified by"
column is the evidence this audit relied on, not the plan's own assertion.

| # | Finding (abridged) | Original severity | Closed | Verified by |
|---|---|---|---|---|
| 1 | `ruff format` fails on tracked Markdown | Medium | `[x]` | `pyproject.toml:265` `exclude = ["*.md"]`; gate 1b passes on 757 files |
| 2 | `noise_reduction` absent from `testpaths` / coverage `source` | High | `[x]` | `pyproject.toml:178` + `:224`; full run collects 7,589 (7,556 + 30 + 3) |
| 3 | `pytest.skip()` inside `pytest_configure` | High | `[x]` | `genre_sync/tests/conftest.py` has no `pytest_configure`; the only remaining `pytest.skip` in any conftest is in a fixture (`conftest.py:207`) |
| 4 | Linux CI leg proves nothing | High | `[~]` N/A | Withdrawn 2026-09-29 by maintainer: no UNIX/Linux host exists for this project, so the evidence can never be produced. **Deliberately not flipped to `[x]`** — closed as *not applicable*, not as *verified*. CI config left intact |
| 5 | Process-pool path untested | High | `[x]` | `mood_analysis_batch_tagger/tests/test_batch_analysis_engine.py`: `TestProcessPoolExecution`, `TestProcessPoolErrorMapping`, `TestProcessPoolWorkerPicklability`, `TestWorkerSlotTracker` |
| 6 | `ffmpeg` undeclared hard dependency | High | `[x]` | `audio_suite_shared/system_requirements.py`; documented block `pyproject.toml:41-46`; `preflight` warns (warning-level, not blocking) |
| 7 | Key detection locked to static K-S profiles | Medium | `[x]` | `key_detector/core/key_engine.py`: parameterised method, `confidence` (`:16-23`), `DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.25` (`:134`), `UNKNOWN_KEY` fallback (`:111`) |
| 8 | Near-verbatim `app.py` scaffolds (94.2%) | Medium | `[x]` | **Independently measured 0.942 → 0.515**; both files now 33 significant lines over a 526-line `analysis_app_base.py` |
| 9 | Near-verbatim file-processor twins (70.9%) | Medium | `[x]` | **Independently measured 0.709 → 0.609**; shared workflow in the 840-line `file_processor_base.py` |
| 10 | No README / quick start / architecture | Medium | `[x]` | `README.md` (20,691 bytes), `readme = "README.md"` at `pyproject.toml:12`, generated 27-row tool index + platform matrix, drift-locked by `tests/test_readme.py` |
| 11 | No LICENSE / no `license` metadata | High | `[x]` | `LICENSE` (verbatim GPL-3.0), PEP 639 `license = "GPL-3.0-or-later"` + `license-files` (`pyproject.toml:18-19`), `setuptools>=77` build floor |
| 12 | Phase gate skipped after a "complete" item | High | `[x]` | Per-item `Gate Evidence` column present in both plans' Completion Logs |
| 13 | `_build_default_registry()` is a ~300-line literal | Medium | `[x]` | `tool_plugin.py` is 453 lines; `_build_default_registry()` is now a short assembly function at `:433` over a declarative frozen-dataclass table |
| 14 | `integration` / `hardware` markers never deselected | Medium | `[x]` | `pyproject.toml:193` `addopts` carries `-m "not hardware"`; 30 deselected; marker descriptions at `:189-191` state the contract |
| 15 | `analysis_loader` at 34.3% | High | `[x]` | **Measured 100%** (36 stmts) |
| 16 | `ffmpeg_finder` fallbacks untested | Medium | `[x]` | `test_ffmpeg_finder.py` 21,468 bytes, 7 test classes incl. `TestSourceTwoAcceptsOnlyRealExecutables`; tightened again by iteration-6 A3 |
| 17 | Coverage `exclude_lines` hides branches | Medium | `[x]` | `pyproject.toml:242-254` — the two broad patterns are gone; only universal pragmas remain; locked by a config test |
| 18 | Blanket session-wide GUI skip can zero the suite | High | `[x]` | `conftest.py` documents the replacement (`:14-27`): `gui` marker, `requires_display` skipif, `GuiDisplayUnavailableWarning`, `SUMMARY_HEADING = "GUI / display report"`, and a bounded `BLANKET_REASON` retained only as a safety net |
| 19 | Analysis family has no measured-outcome tests | High | `[x]` | `TestGoldenVectorPositive`/`Negative` (key), `TestGoldenVectorMeasuredBpm`, `TestGoldenVectorExhaustiveSchemeCoverage` (tempo), `TestGoldenVectorMeasuredValence`/`Arousal`/`Reproducibility` (mood), `TestGoldenVectorMeasuredLevelFidelity` (analysis_loader), plus `TestRealMaterialBeforeAfter` |
| 20 | Platform paths with no support matrix | Medium | `[x]` | `audio_suite_shared/platform_support.py` AST-classifies the branches; README carries a generated 3-tier matrix and states plainly at `README.md:61` that **no tool has been executed on a real Linux or macOS host** |
| 21 | No changelog, no `audiosuite --help` contract | Low | `[x]` | `CHANGELOG.md`; `audiosuite --version` single-sourced via `project_version.py`; golden registration contract tests for manifest ↔ card ↔ CLI ↔ guide ↔ launcher |

**Result: 21/21 closed. 20 verified closed, 1 closed as not-applicable by
explicit maintainer decision with the reason recorded in two places.** No
finding regressed.

---

## 4. New findings

Eight new findings. None is a gate defect. Two are contract/doc defects that a
user can hit today.

---

### A1 — The CLI advertises a `--dry` flag that does not exist `[Medium]`

**Class:** the same class as original finding #21 (discoverability contract),
not fully closed because G2's golden test was scoped to *registration*
(does a subcommand exist) and never to *flag parity*.

`audio_suite_shared/cli_app.py:22` — the CLI entry point's own usage docstring —
advertises:

```
audiosuite enhance /path/to/dir --output-dir ... [--preset Moderate] [--dry]
```

`audio_enhancer/cli.py:33` declares no such option. **Reproduced:**

```
$ audiosuite enhance . --output-dir x --dry
exit code: 2
Error: No such option '--dry'.

$ audiosuite enhance --help
Options:
  --json / --text    Output results as JSON.
  --output-dir PATH  Output directory (required).  [required]
  --preset TEXT      Enhancement preset (Mild, Moderate, Aggressive, Custom).
  --help             Show this message and exit.
```

The capability already exists everywhere else: `is_dry_run` is a real parameter
of the core entry point (`audio_enhancer/core/file_processor.py:180`, threaded
to `process_file(..., dry_run=is_dry_run)` at `:270`), and the GUI wires it
(`audio_enhancer/app.py:365`). The **CLI is the only surface missing it**, which
is the exact "mode flags must be traced end-to-end" trap `AGENTS.md` records —
traced in one direction, not the other.

Scope measured across all 26 tool CLIs: **22 declare a dry-run flag; 4 do not** —
`audio_enhancer`, `album_art_normalizer`, `cd_ripper`, and `library_stats`. The
last two are correct by design: `library_stats` is read-only
(`core/completeness.py:5`, "All data is read-only - no analysis or tag
writing"), and `cd_ripper` creates new files rather than modifying existing
ones, so there is nothing for a dry run to withhold. The first two are gaps, and
`audio_enhancer` additionally has a docstring that claims the missing flag
exists.

**The same defect, opposite direction, in `album_art_normalizer`:** the module
docstring (`__init__.py:5`) and CLI help (`cli.py:20`) say the tool handles
"MP3 and FLAC files", but `core/file_processor.py:69-79` dispatches all nine
shared extensions (`.ogg`, `.opus`, `.m4a`, `.mp4`, `.wav`, `.aiff`, `.aif` all
route to `process_audio_artwork`). The documentation **understates** the
capability, so this one misleads in the safe direction — but it is still drift
between a documented contract and shipped behaviour.

**Recommended fix (small):** add `--dry` to `audio_enhancer/cli.py` passing the
existing `is_dry_run`; add it to `album_art_normalizer/cli.py`; correct both
docstrings; and extend the G2 contract test from "the subcommand exists" to
"every flag the entry point documents resolves" — the latter is the general
form and would have caught this.

---

### A2 — `tempo_analyzer` ships two generated guides and no generator `[Medium]`

**Class:** documentation-hygiene; a direct violation of the `AGENTS.md` §8 rule
that "the generator is the source of truth for generated docs."

Every one of the 27 tool folders under `user_guides/individual_programs/` has a
`generate_guide.py` **except `tempo_analyzer`**, which has none — and no
generator anywhere in the tree references `tempo_analyzer` (verified by content
search across all `generate_guide.py` files).

The tracked artifacts are:

```
user_guides/individual_programs/tempo_analyzer/Tempo_Analyzer_Logging_Guide.docx
user_guides/individual_programs/tempo_analyzer/Tempo_Analyzer_User_Guide.docx
user_guides/individual_programs/tempo_analyzer/Tempo_Analyzer_User_Guide.docx.bak
```

Two consequences. First, the guide is an **orphaned artifact**: it cannot be
regenerated, so it cannot be verified against the code and it will drift
silently. Second, **stray `.docx.bak` backup files are committed to the
repository — 12 of them across 10 tool folders, one folder even containing a
`.bak2` and a `.bak_lossless`.** They are hand-edit remnants — exactly the
workflow `AGENTS.md` §8 prohibits —
and they are not unique to `tempo_analyzer`; the generator-missing condition is.

The guide is registered correctly in `audio_suite_shared/platform_utils.py:125`
(`"Tempo_Analyzer_User_Guide.docx": "tempo_analyzer"`), so registration is not
the problem — provenance is.

**Recommended fix (small):** write `tempo_analyzer/generate_guide.py` to
reproduce the two `.docx` files from source of truth, verify the regenerated
output matches, then remove the `.bak`·`.bak2`·`.bak_lossless` files from the
working tree and untrack them — sweep all 12 across the 10 folders while there,
and add a repo-lock test so none can be staged again.

---

### A3 — The duplication *class* was fixed at two instances, not across the class `[Medium]`

**Class:** the direct successor of original findings #8 and #9.

**The two named pairs are genuinely fixed — independently measured by this
audit** (`difflib.SequenceMatcher` over significant lines, blanks and
boilerplate stripped):

| Pair | Original | Now | Shared significant lines |
|---|---|---|---|
| `key_detector/app.py` ↔ `mood_analyzer/app.py` | 0.942 | **0.515** | 17 of 33 |
| `noise_reduction/core/file_processor.py` ↔ `pop_click_remover/core/file_processor.py` | 0.709 | **0.609** | 103 of 156 |

**But three adjacent families were outside the sanctioned blast radius and
remain near-verbatim.** Measured by this audit:

| Pair | Ratio | Shared sig. lines | Note |
|---|---|---|---|
| `master_driver/ui/cards/key_card.py` ↔ `mood_analyzer_card.py` | **0.933** | 84 of 90 | identical except the docstring line and one dict key |
| `master_driver/ui/cards/asx_card.py` ↔ `tag_editor_card.py` | **0.903** | 51 of 55 | |
| `mood_analyzer/ui/setup_tab.py` ↔ `mood_analysis_batch_tagger/ui/setup_tab.py` | **0.895** | 107 | |
| `key_detector/ui/setup_tab.py` ↔ `mood_analyzer/ui/setup_tab.py` | **0.837** | 87 | |
| `bpm_analyzer/app.py` ↔ `lyrics_manager/app.py` | **0.796** | **395** | **largest clone in the repo by volume** |
| `noise_reduction/app.py` ↔ `pop_click_remover/app.py` | **0.788** | 254 | |
| `key_detector/core/file_processor.py` ↔ `mood_analyzer/core/file_processor.py` | **0.683** | 191 | |
| `audio_normalizer/app.py` ↔ `genre_sync/app.py` | **0.638** | 186 | |

Two systematic copy-paste families account for most of it:

1. **Per-tool `utils/cli_args.py`.** 22 files, 72–330 lines each, each
   hand-rolling an `argparse` flag ladder. One **30-line ladder is
   byte-identical across 6 tools** (`tempo_analyzer`, `album_art_normalizer`,
   `audio_fingerprinter`, `audio_normalizer`, `music_format_converter`,
   `silence_trimmer`). A shared parser already exists at
   `audio_suite_shared/cli_helpers.py::create_standard_parser` and is bypassed
   by these copies. Per-file duplication reaches **36.5%**
   (`key_detector/utils/cli_args.py`, `mood_analyzer/utils/cli_args.py`).
2. **Per-tool `ui/setup_tab.py`.** Worst three by share of the file duplicated:
   `mood_analyzer/ui/setup_tab.py` **64.6%**, `key_detector/ui/setup_tab.py`
   **64.0%**, `mood_analysis_batch_tagger/ui/setup_tab.py` **56.7%** — all three
   bypass the `analysis_app_base`/`ui_common` shared base that finding #8
   created.

**This is not a regression and not a criticism of the remediation's scoping.**
`AGENTS.md` §2 forbids widening a change beyond the stated blast radius, and
C1's plan text explicitly sanctioned "exactly these two apps plus the shared
base". The consequence of doing that correctly is simply that the class remains
— which is what a follow-on plan is for. Aggregate duplication is now **2.18%
of production significant lines** at a 12-line block threshold (4.53% at 8
lines), so the *volume* problem is genuinely much smaller than it was; what
remains is concentrated and mechanical.

**Recommended fix (medium effort, staged):** extract the shared flag ladder onto
the existing `cli_helpers.create_standard_parser` seam first (highest fan-out,
lowest risk, no GUI), then a card-builder seam for
`master_driver/ui/cards/*_card.py` (13 near-identical `build()` functions), then
the `setup_tab` widget builders.

---

### A4 — GUI surfaces are the only structural coverage gap `[Low]`

Coverage is **bimodal, and the split is cleanly along GUI/non-GUI lines.** From
the authoritative full-suite run (455 production modules, 27,869 statements,
79.17% by per-file summation; the gate reports 79.20%):

| Band | Modules | Statements | Missed | % of missed |
|---|---|---|---|---|
| 90–100% | 305 | 15,951 | 456 | 7.9% |
| 80–89% | 62 | 3,455 | 495 | 8.5% |
| 70–79% | 23 | 1,360 | 363 | 6.3% |
| 50–69% | 17 | 2,087 | 804 | 13.8% |
| 30–49% | 16 | 2,411 | 1,504 | 25.9% |
| **0–29%** | **32** | **2,605** | **2,184** | **37.6%** |

Decomposed:

- **Non-GUI production code: 93.7% covered** (301 modules, 18,699 statements,
  1,181 missed).
- **GUI surfaces (`app.py` + `ui/` + `*_tab.py`): 49.6% covered** (154 modules,
  9,170 statements, 4,625 missed).
- **48 modules below 50% hold 63.5% of every uncovered statement in the
  project.**

Eight modules sit at **exactly 0%** (368 statements):

| Module | Statements | Note |
|---|---|---|
| `tag_field_updater/ui/app.py` | 121 | the only non-card production module at 0% |
| `master_driver/ui/cards/noise_reduction_card.py` | 48 | |
| `master_driver/ui/cards/library_stats_card.py` | 45 | |
| `master_driver/ui/cards/fingerprinter_card.py` | 44 | |
| `master_driver/ui/cards/file_reorganizer_card.py` | 39 | |
| `master_driver/ui/cards/mood_analysis_batch_card.py` | 31 | |
| `master_driver/ui/cards/album_art_normalizer_card.py` | 30 | |
| `lyrics_manager/__main__.py` | 10 | |

The seven cards are covered by original finding #21's contract test, which
verifies the card **file exists** for each manifest id — not that `build()` runs.
That is the correct scope for a *registration* test, but it means a card whose
`build()` raises at runtime still satisfies it. The near-identical
`key_card.py`/`mood_analyzer_card.py` pair from finding A3 is exactly the
configuration where one card works and its twin does not.

This is the already-tracked `PLAN_iteration6_followups.md` §C3 item
("Per-tool GUI test coverage across all 27 tools"), now quantified. No new
decision is needed; the useful addition is the 93.7% / 49.6% split, which shows
where the remaining headroom actually is.

---

### A5 — Five silent exception swallows remain `[Low]`

Exception hygiene is otherwise strong, and this is reported as such: of 588
`except` handlers in production code, **0 are bare `except:`, 0 use
`contextlib.suppress`, 434 catch a specific type, and 147 of the 154
`except Exception:` handlers surface the error to the user** (messagebox,
`map_to_audio_error`, `user_message_for`, `add_failure`, or a status string).
Both broad handlers with no diagnostic at all
(`audio_normalizer/core/normalizer.py:141,153`) are correct cleanup-and-re-raise
shapes.

The five genuine silent swallows:

| Location | Body | Assessment |
|---|---|---|
| `File_Reorganizer.pyw:26` | `pass` | launcher boilerplate, wraps the Tk error dialog |
| `File_Reorganizer.pyw:40` | `pass` | same file, outer startup handler |
| `Tag_Field_Updater.pyw:27` | `pass` | same copy-pasted launcher pattern |
| `utilities/resize_music_recursive.py:177` | `pass` | **real defect surface** — a failing `Image.open()` is indistinguishable from "not already at target size", so a corrupt embedded `APIC` frame is silently re-processed |
| `audio_suite_shared/batch_undo.py:269` | `continue` | **real defect surface** — a `pickle.loads` failure on a legacy blob silently skips the row, which is then never migrated |

The first three are the same 30-line launcher boilerplate, so one fix closes
three. The last two are single-line fixes with real diagnostic value.

Related, low-severity: 92 `print(` calls in production, of which **73 are the
sanctioned `utilities/` CLI scripts** and 19 are one duplicated stderr line
repeated across 17 `cli_args.py` files (e.g.
`album_art_normalizer/utils/cli_args.py:97`). These are pre-`configure_logging`
CLI diagnostics, not logging violations, but they are the same 19-way
duplication as A3.

---

### A6 — `tag_helper_base.py` and eight god-functions dominate the complexity budget `[Low]`

- `audio_suite_shared/tag_helper_base.py` — **2,151 lines**, 142 defs; 2.7× the
  next-largest file. Highly repetitive per-format tag I/O, which is the
  duplication problem in its most concentrated form.
- 58 production files exceed 400 lines; 167 functions exceed 80 lines; 8 exceed
  200.

Worst functions by length (AST-measured):

| Lines | Function | Location |
|---|---|---|
| **319** | `process_file` | `audio_refinery/core/pipeline.py:123` |
| 302 | `setup_ui` | `file_reorganizer/app.py:65` |
| 255 | `_build_options` | `music_format_converter/ui/setup_tab.py:173` |
| 254 | `parse` | `audio_refinery/utils/cli_args.py:77` |
| 236 | `build` | `audio_refinery/ui/setup_tab.py:87` |
| 235 | `process_single_file` | `music_format_converter/core/file_processor.py:183` |
| 211 | `run_batch` | `mood_analysis_batch_tagger/core/batch_analysis_engine.py:233` |
| 191 | `build` | `master_driver/ui/cards/noise_reduction_card.py:16` |

The notable pattern is not any single function but the fact that **the same
god-function shape is re-implemented per tool**: `build()` in 13
`master_driver/ui/cards/*_card.py` files, `parse()` in 9
`utils/cli_args.py` files, `process_single_file()` in 4 processors,
`start_processing()` in 4 apps. This is A3 seen from the function-body side.

`audio_refinery/core/pipeline.py` is the one to watch: a 319-line
`process_file` in the tool that **writes audio** (a 5-stage chain ending in
loudness normalisation), with the module at 86% (35 of 243 statements missed)
and its owning `audio_refinery/app.py` at 31%. `AGENTS.md` ranks
audio-correctness defects as release-blocking, so this is the highest-value
single target in the list — not because it is known-buggy, but because it is
the longest single function across an audio write path: behaviour-locking its
exact current output, then decomposing it, is the safe order.

---

### A7 — `dataclass(frozen=True)` adoption is 55%; `slots=True` is never used `[Low]`

109 `@dataclass` declarations in production; **60 use `frozen=True`**, and
**0 use `slots=True`**. `AGENTS.md` §5 asks for `dataclass(frozen=True)` "for
clean, immutable data containers", so roughly half the data containers are
mutable when the project convention says they should not be. This is a
consistency finding, not a defect — nothing is currently broken by it.

Class-level typing is 89.5% annotated (693 of 774); the 81 unannotated are
plain `Assign` in class bodies without `__init__`.

---

### A8 — Typing discipline is excellent and should be recorded as a strength

This was not an original finding but it is the single clearest quality
achievement of the remediation programme, and an audit that reported only
problems would misrepresent the suite.

| Metric | Result |
|---|---|
| Production defs considered | 2,215 |
| **Fully annotated (all params + return)** | **2,203 — 99.5%** |
| Parameters annotated (excl. `self`/`cls`) | 4,190 / 4,195 — **99.9%** |
| `*args` / `**kwargs` annotated | 13/13 and 75/75 — 100% |
| `mypy --strict` | 0 issues / 452 files |

The only 5 unannotated parameters and 12 missing return types in the whole
production tree are in `utilities/strip_bom.py` and 8 `__init__` methods.
**No file with ≥5 defs falls below 75% annotation.** The `__all__` /
`implicit_reexport` discipline, the redundant-alias re-export form, and the
`untyped_calls_exclude` carve-out list are all maintained deliberately.

---

## 5. Market-leader capability comparison

Re-derived from source for all 27 tools, against the capabilities a user would
compare against Audio Explorer, Mp3tag, foobar2000, dbPowerAMP, iZotope RX,
MusicBee, beets and MusicBrainz Picard.

### 5a. Verified capability gaps

| # | Gap | Evidence | Market leader |
|---|---|---|---|
| 1 | **No dither and no high-quality resampler.** The converter applies plain `-ar` and PCM codec swaps for bit depth; zero occurrences of `dither`, `soxr`, `aresample`, `swrresample` in `music_format_converter/core/`. | `ffmpeg_params.py:218-220`, `:27-32` | dbPowerAMP and foobar2000 dither on every down-conversion |
| 2 | **No MusicBrainz identifier (MBID) writing.** No `MUSICBRAINZ_ALBUMID` / `MusicBrainz Release Group Id` / etc. anywhere in first-party code. | `git grep` over `*.py`: no matches | Picard writes these by default; Mp3tag supports them as custom fields |
| 3 | **No DSD support.** No `.dff` / `.dsf` / `DSD` handling; the shared format set is 9 extensions ending at AIFF. | `audio_suite_shared/audio_formats.py:14-31` | dbPowerAMP, foobar2000 handle DSD natively |
| 4 | **Converter is flat and refuses mixed input.** `os.scandir` (no recursion) and `ok=False` when the directory holds more than one source format. | `music_format_converter/core/formats.py:173`, `:190-191` | dbPowerAMP converts mixed-format trees recursively |
| 5 | **Tag Editor is limited to 8 fields** — title, artist, album, album_artist, track, year, genre, comment. No disc, composer, ISRC, MBIDs, ReplayGain, or per-field multi-value editing. | `tag_editor/core/processor.py:31-40` | Mp3tag, Audio Explorer |
| 6 | **No duplicate finder and no library database.** Content-hash duplicate detection with a persistent store does not exist. | verified absent | beets, MusicBee, Audio Explorer |
| 7 | **No plugin / provider extensibility.** The lyrics registry is the right shape (class registration, one registration line per source) but ships one provider. | `lyrics_manager/core/providers/registry.py` (63 lines, ends `register_provider(LRCLIBProvider)`) | Picard, Mp3tag, foobar2000 |
| 8 | **No Cover Art Archive or Spotify art source.** The chain is MusicBrainz → Fanart → Deezer → iTunes. | `album_art_sync/api/source_resolver.py:1-102` | Picard fetches CAA covers by MBID |
| 9 | **Lyrics: single provider.** LRCLIB only. | `lyrics_manager/core/providers/registry.py` — the registry holds exactly one registration | — |

Gap 1 is the one to treat as an **audio-correctness** item rather than a
feature gap: a 24→16-bit down-conversion without dither is measurably lossy,
and `AGENTS.md` ranks conversion defects as release-blocking. Gaps 2 and 8 are
compounding — an MBID is what makes Cover Art Archive lookup possible, so
neither exists without the other.

### 5b. Documented design decisions that look like gaps but are not

Two inconsistencies were checked and found to be **deliberate and correct**, and
are recorded here so a future audit does not re-raise them:

- `audio_normalizer` supports 5 formats, not the shared 9
  (`core/normalizer.py:25-31`). The module documents the reason at `:37-39`:
  writing a `.wav` extension with an MP3 codec would produce MP3 data inside a
  WAV container, so unsupported extensions are **rejected** rather than
  silently mislabelled. That is the correct call, and the explicit
  `AudioFormatError` (`:51-52`) is the right failure mode. It is still a user-
  visible inconsistency with sibling tools, and worth a mention in the guide.
- `library_stats` has no dry-run flag — correct, it is read-only
  (`core/completeness.py`).

### 5c. Genuine strengths ahead of typical market leaders

1. **Suite-wide byte-level undo in one history.** The standout capability.
   `audio_suite_shared/batch_undo.py` (1,176 lines) records tag snapshots,
   **byte-level audio overwrite snapshots**, file-delete snapshots and reorg
   snapshots into a single SQLite log, wired at the shared write sites
   (`file_processor_base.py:717`, `music_format_converter/core/file_processor.py:337`,
   `file_reorganizer/core/engine.py:303`, `asx_extractor/core/file_ops.py:56`).
   Competitors generally offer in-session undo or a single "revert tag write";
   none give suite-wide byte-level audio + tag + move/delete revert. The
   cap behaviour (50 runs / 1 GiB, oldest batch pruned whole) is documented
   with a keep-your-own-backups instruction rather than hidden.
2. **Integrated multi-stage refinery.** `audio_refinery/core/pipeline.py:1-25`
   chains declick → silence-trim → enhance → encode → loudness-normalise as one
   auditable pipeline with atomic replacement. No single competitor tool does
   this exact sequence.
3. **CD ripping with two independent verification layers.** AccurateRip
   cross-check (`cd_ripper/core/accuraterip.py:1-7`) *plus* MusicBrainz disc-ID
   with `discid` fallback (`core/discid.py:1-12`), plus per-drive read-offset
   detection and CUE output. This rivals EAC/lame-class rippers.
4. **Fingerprinting with tag-aware tie-breaking.** When the top two AcoustID
   candidates are within `_AMBIGUITY_SCORE_GAP = 0.10`, the file's existing
   artist/title tags break the tie (`acoustid_client.py:41-43`, applied by
   `resolve_best_match` at `:397`) rather than trusting database rank. Also
   guarded by a 7-second duration window (`:33-35`). A documented hard-won
   correctness behaviour most fingerprint tools get wrong.
5. **Signal-based mood tagging** writing real valence/arousal tags
   (`tool_plugin.py:243`), plus a batch variant. Rare in mainstream taggers.
6. **Uniform 9-format metadata and undo behaviour across all 27 tools** via one
   `tag_helper`/writer and one snapshot system, with conversion re-preserving
   metadata through `-map_metadata` (`ffmpeg_params.py:222-232`).

---

## 6. Summary of findings

| ID | Finding | Severity | Class | Status |
|---|---|---|---|---|
| A1 | CLI docstring advertises `enhance --dry`, which does not exist | Medium | Contract / docs | **New, open** |
| A2 | `tempo_analyzer` has 2 generated guides, no generator, and 12 tracked `.docx.bak` files across 10 tool folders | Medium | Docs hygiene | **New, open** |
| A3 | Duplication class unfixed in 3 adjacent families (0.64–0.93); largest clone ~395 lines | Medium | Maintainability | **New, open** (correctly out of C1/C2 scope) |
| A4 | GUI surfaces at 49.6% vs 93.7% non-GUI; 8 modules at exactly 0% | Low | Test depth | **New, quantified** — maps to iteration-6 §C3 |
| A5 | 5 silent exception swallows (3 launcher boilerplate, 2 with real defect surface) | Low | Code quality | **New, open** |
| A6 | `tag_helper_base.py` 2,151 lines; 8 functions >200 lines incl. a 319-line audio-write function (module 86% covered, its GUI at 31%) | Low | Maintainability | **New, open** |
| A7 | 55% `frozen=True` adoption; 0 `slots=True` | Low | Consistency | **New, open** |
| A8 | Typing discipline excellent (99.5% defs, 99.9% params, mypy --strict clean) | — | **Strength** | Record it |
| 1–21 | Original audit findings | — | — | **21/21 closed**, no regressions |

### Capability gaps carried forward (not defects — product decisions)

Dither/resampling · MBIDs · DSD · recursive mixed-format conversion · tag-editor
field breadth · duplicate finder / library database · plugin extensibility ·
Cover Art Archive · additional lyrics providers.

---

## 7. Assessment against the original criteria

| Criterion | Verdict | Basis |
|---|---|---|
| **Gate integrity / measurement honesty** | **Strong** | All six commands pass; the two original measurement lies (an omitted package, hidden coverage exclusions) are gone; `fail_under` held at 75 against an honest 79.20%; per-item gate evidence is mandatory; the secret scan is clean. One residual scope gap: G2's contract test covers registration, not flag parity (A1). |
| **Code quality** | **Good** | 0 bare `except:`, 0 `contextlib.suppress`, 434/588 specific-type handlers, 147/154 broad handlers surface to the user. Deductions: 5 silent swallows (A5); 2.18% residual duplication concentrated in three families (A3). |
| **Readability** | **Good** | Consistent per-tool layout, `AGENTS.md` conventions followed, comments explain *why*, `argparse` ladders uniform even where duplicated. Deductions: the two 2,000+ line files and 8 god-functions (A6). |
| **Maintainability** | **Good, with one concentrated weakness** | Declarative tool registry, 26 of 27 tools on a shared format table, a shared `BaseFileProcessor` write path, one undo system, one CLI contract. The weakness is the un-extended duplication class (A3) — the same defect class the original audit found, at lower severity and in different files. |
| **Test depth & correctness** | **Strong on logic, weak on GUI** | 93.7% non-GUI coverage; measured-outcome golden vectors across key/BPM/tempo/mood/level; real-file tag round-trips; the outcome-not-read-back rule is genuinely honoured. 49.6% on GUI surfaces (A4) is the one soft spot, and it is already tracked as iteration-6 §C3. |
| **Type safety** | **Excellent** | 99.5% / 99.9% / `mypy --strict` clean (A8). |
| **Documentation & discoverability** | **Good** | README with generated, drift-locked tool index and platform matrix; GPL-3.0 with PEP 639 metadata; CHANGELOG, CONTRIBUTING (with the `hardware` opt-in), SECURITY with an honest no-SLA channel. Deductions: A1 (a documented flag that fails) and A2 (an un-regenerable guide). |
| **Platform reach** | **Honest** | A declared, AST-derived 3-tier matrix, and `README.md:61` states plainly that no tool has been run on a real non-Windows host. That honesty is the finding being closed, not a gap in it. |
| **Market-leader capability** | **Competitive, with a clear standout** | Uniquely strong on suite-wide byte-level undo, the refinery pipeline, and two-layer CD-rip verification. Behind on dithering, MBIDs, DSD, library management, and extensibility — all product-scope decisions rather than quality defects, except dithering (audio correctness). |

---

## 8. Method and reproducibility

**Environment:** Windows host, Python 3.14.7, `uv`-managed `.venv` at the
audit baseline commit `cfe9e79`.

**Phase Gate:** run exactly as specified in `PLAN_iteration5_remediation.md`
§"Phase Gate", including the mandatory `-c pyproject.toml` and `-x ./.venv` on
bandit and the bare (not package-scoped) pytest run.

**Independent measurements** (throwaway scripts written to a scratch
directory outside the repository; no repository file was modified):

- *Duplication* — `difflib.SequenceMatcher` over "significant" lines (blanks,
  lone brackets, `else:`/`try:`/`return`/`pass` and comments stripped), plus
  ≥12-line block detection with a >40%-distinct-lines filter to reject repeated
  counter ladders.
- *Complexity* — `ast` module walk for file/function length and for
  `except`-handler bodies.
- *Coverage distribution* — parsed from `coverage report --show-missing`
  immediately after the full-suite run.

**One measurement error was caught and corrected during this audit, and is
recorded here because it nearly produced a false High finding:** an initial
coverage-distribution analysis reported ~59 modules at exactly 0%, including
`master_driver/runner/arg_builder.py`. A scoped run of
`master_driver/tests` showed `arg_builder.py` at 96%, `module_runner.py` at
100%, `batch_orchestrator.py` at 98% and `app_state.py` at 96% — so the `.coverage`
data file being parsed had been left by an **earlier scoped run** with a
restricted `--cov` target, not by the full suite. Every module outside a scoped
run's measurement scope reports 0% in `coverage report`. The distribution above
was recomputed from data captured directly after a fresh bare full-suite run and
the false finding was discarded. *Lesson worth carrying: a coverage number is
only valid if the data file that produced it came from the run being reported —
which is precisely the class of defect original finding #2 was about, re-encountered
from the other direction.*

**Not verified in this audit:** behaviour on any non-Windows host (none exists
for this project, per the 2026-09-29 maintainer decision); the `hardware`-marked
CD-drive tests (deselected by design, opt-in via `pytest -m hardware`); and
`.docx` guide *contents* (generators were read; binaries were not).
