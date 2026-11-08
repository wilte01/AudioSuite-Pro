# PLAN — Group the ENRICH tab cards (Master Driver)

**Status:** COMPLETE
**Governing brief:** the maintainer's follow-on request that the ENRICH tab get
"the same captioned grouping the UTIL tab now has, using the manifest group
field".
**Supersedes nothing:** extends the mechanism established by
`PLAN_2026-11-08_util_card_grouping.md`, which stays the record of the Utilities
tab.
**Scope:** `audio_suite_shared/tool_plugin.py`, `master_driver/ui/enrich_tab.py`,
`master_driver/ui/utilities_window.py`, the new `master_driver/ui/group_caption.py`,
their tests, and the documents that describe the tab.

## What the tab was

Eleven enrich cards, one collapsible panel each, in one flat stack: scrubber,
fingerprinter, replaygain, album-genre, genre-sync, bpm, tempo, key, mood,
art, lyrics. Nothing on screen said why they sat in that order — yet that order
*is* the order a sequential batch runs (`arg_builder.build_enrich_args` walks the
registry), and it is the order the suite's own deck justifies step by step
("Tempo Analyzer ... must run after BPM Analyzer", "Runs last so artwork is not
disturbed by any later tag rewrite").

## What changed

Five captions, each a contiguous run of that same order, so no tool moved:

| Group (display order) | Cards | `order` |
|---|---|---|
| Tag Cleanup | Metadata Scrubber | 10 |
| Identification | Audio Fingerprinter | 20 |
| Loudness & Genre | ReplayGain Analyzer, Album Genre Tagger, Genre Sync | 30–50 |
| Analysis | BPM Analyzer, Tempo Analyzer, Key Detector, Mood Analyzer | 60–90 |
| Artwork & Lyrics | Album Art Sync, Lyrics Manager | 100–110 |

## Decision Log

| ID | Date | Decision | Reasoning | Evidence |
|---|---|---|---|---|
| D-01 | 2026-11-08 | **The splitter is shared, not copied.** `tool_plugin.grouped_sections(manifests, groups)` is the implementation; `utility_sections()` and `enrich_sections()` are its two call sites. | Two copies of "plugin section last" and "an undeclared group keeps its card" is exactly the drift class AGENTS.md's *Shared Implementations First* forbids — and the two tabs would have disagreed about the fallback within a release. | `audio_suite_shared/tests/test_tool_plugin.py::TestEnrichSections` |
| D-02 | 2026-11-08 | **The caption widget is shared too** (`master_driver/ui/group_caption.py::GroupCaption`), extracted from `utilities_window`. | Both tabs have to look identical, and `GroupCaption` stays a `tk.Label` so the Utilities grid's "a card is a `Frame`" assumption keeps holding. | `master_driver/ui/group_caption.py` |
| D-03 | 2026-11-08 | **ENRICH groups keep the existing order; they do not alphabetise.** Utilities alphabetise because their order carried no meaning (the old values had ties and gaps); the enrich order *is* the dependency order. | Re-sorting Analysis alphabetically would put Tempo before Key/Mood and after BPM by luck, but "Grouping must not reorder a run" is a stronger promise than "alphabetical is tidy", and the shipped deck's ENRICH table would have become false. Groups are contiguous runs; the renumbering into blocks of ten changes nothing. | `TestEnrichGrouping::test_grouping_did_not_reorder_the_run`; `documentation/user_guides/suite_overview/generate_presentation.py::ENRICH_ROWS` |
| D-04 | 2026-11-08 | **The dependency stays locked in display order.** A test asserts BPM precedes Tempo. | Tempo Analyzer reads the BPM tag BPM Analyzer writes; the graph also states it (`DEPENDENCY_GRAPH["tempo"] = ["bpm"]`), so a future group edit that separates them fails rather than shipping a batch that derives tempo from an empty tag. | `TestEnrichGrouping::test_a_dependency_still_runs_before_its_dependant` |
| D-05 | 2026-11-08 | **`_build_card` now reports whether it built anything**, and a group whose cards all failed loses its caption. | A caption over nothing reads as a broken tab; the Utilities grid already drops a caption for the same reason. Returning a bool is the honest signal — counting children only works while one card equals one widget. | `master_driver/tests/test_enrich_tab.py::TestCaptionDropping` |
| D-07 | 2026-11-08 | **The changed-in budget baseline was re-recorded, deliberately.** The new `Changed in 2.5.0` notes grew that version from 234 to 240 note lines, so `utilities/tests/test_changed_in_budget.py` refused the tree. | The notes are wanted — six modules genuinely changed in this release — so the ceiling moved with them rather than the notes being trimmed to fit. `utilities/changed_in_budget.py --record` is the file's documented update path (it says so in its own `_comment`), and the 3-line diff records 1680 lines across 28 versions. | `--check` → "1680 note line(s) ... at or under the recorded ceiling"; 17 budget tests pass |
| D-06 | 2026-11-08 | **The guide artefacts were re-checked, and only the edited guide enters the diff.** `build_user_guides.py --check` had reported eight stale artefacts after a rebuild-and-restore cycle in the Utilities change. | A full rebuild rewrote all 32; the seven besides this change re-rendered to the bytes already committed, so they were restored to HEAD and `--check` now reports all 32 current. Recording it here so the earlier stale report is not mistaken for an unrecorded documentation change. | `python utilities/build_user_guides.py --check` → "32 guide artefacts are current" |

## Acceptance

| Check | Result |
|---|---|
| Compile | `python -m compileall -q -f .` exit 0 |
| Lint & format | `ruff check .` "All checks passed!"; `ruff format --check .` "1115 files already formatted" |
| Types | `mypy .` "Success: no issues found in 616 source files" |
| Focused suites | 338 passed — enrich tab, utilities window, manifest registry, AGENTS citations, release notes, README index, guide resolution, docs tool coverage, UI module usage, UI cards, driver app, tool launcher |
| Guide artefacts | `--check` → 32 current; only `Master_Driver_User_Guide.docx` differs from HEAD |
| Security | sev Low 58 / Medium 0 / High 0, no finding in a touched file |
| Full suite | bare `pytest` — **12213 passed, 3 skipped, 35 deselected** in 21:39, with one failure: `test_changed_in_budget.py::TestTheCommittedBaselineIsCurrent` refused the new notes (`2.5.0 grew from 234 to 240`, total 1676 → 1680). Fixed by recording the baseline (D-07); `--check` passes and the 17 budget tests re-ran green. |

## Files touched

`audio_suite_shared/tool_plugin.py` (`ENRICH_GROUPS`, `grouped_sections`,
`enrich_sections`, generic section titles, enrich `group`/`order`),
`audio_suite_shared/tests/test_tool_plugin.py` (`TestEnrichGrouping`,
`TestEnrichSections`, renamed section-title constants),
`master_driver/ui/group_caption.py` (new), `master_driver/ui/enrich_tab.py`,
`master_driver/ui/utilities_window.py`,
`master_driver/tests/test_enrich_tab.py` (new),
`master_driver/tests/test_utilities_window.py` (shared caption),
`documentation/user_guides/individual_programs/master_driver/Master_Driver_User_Guide.md`
(+ its `.docx`), `CHANGELOG.md`, `TECHNICAL_CHANGELOG.md`, `AGENTS.md`, this plan.
