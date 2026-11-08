# PLAN — Group and order the Utilities tab cards (Master Driver)

**Status:** COMPLETE
**Governing brief:** the maintainer's report that the Master Driver's UTIL tab
listed 19 cards "apparently in random order", with a request to rationalise them,
"possibly alphabetically within related groups".
**Scope:** `audio_suite_shared/tool_plugin.py`,
`master_driver/ui/utilities_window.py`, their tests, and the documents that
describe the tab.

## What was wrong

The tab rendered `registry.driver_by_category("utility")` in manifest order,
flat, two columns, without headings. Three things made that read as random:

- the population is **18 first-party utilities plus one plugin card** — the
  bundled `example_plugin`'s "Example Tool", enabled by default — so the last
  card had no relationship to the others;
- `order` had **ties** (`file_reorganizer` 55 / `track_splitter` 55,
  `audio_joiner` 56 / `restoration` 56) which broke by name, and a **gap**
  (35–40) left by 2.5.0's additions slotted in as 41, 45, 47, 48, 50, 52, 53,
  54, 56, 57;
- `order` is not display-only: a sequential batch runs its steps in the same
  order (`BatchOrchestrator` executes the step list `arg_builder` builds from
  the registry), and the README tool index and `documentation/docs/index.md`
  derive from it.

## What changed

The single `order` list became six contiguous blocks of ten, one block per
`UTILITY_GROUPS` entry, with the tools' names alphabetical inside a block; the
tab draws a full-width caption at each block boundary.

| Group (workflow order) | Cards (alphabetical) | `order` |
|---|---|---|
| Convert & Import | ASX Playlist Extractor, CD Ripper, Music Format Converter | 10, 20, 30 |
| Tags & Artwork | Album Art Normalizer, Tag Editor, Tag Field Updater, Undo Tag Edits | 40–70 |
| Analysis & Inspection | Library Statistics Dashboard, Mood Analysis Batch Tagger, Spectral Viewer | 80–100 |
| Repair & Processing | Channel Tools, Duplicate Finder, ML Denoiser, Restoration (Declip), Stem Separator | 110–150 |
| Organise & File Handling | Audio Joiner, Tag-Based File Reorganizer, Track Splitter | 160–180 |
| Plugins | Example Tool (any plugin, always last) | plugin's own `order` |

## Decision Log

| ID | Date | Decision | Reasoning | Evidence |
|---|---|---|---|---|
| D-01 | 2026-11-08 | **One ordering source.** The grouped order is the manifest `order`, not a second display-only list. | The tab and a sequential batch must agree: the Master Driver guide states steps run in the displayed order, and the progress panel lists steps in run order. A display-only order would have made the tab and the run disagree. | `master_driver/runner/arg_builder.py::build_utility_args`; `Master_Driver_User_Guide.md` *Batch Execution* |
| D-02 | 2026-11-08 | **`group` lives on the manifest**, not in a mapping inside the window. | A second list of tool ids is the duplication class the repo already locks against; a new utility that forgot to register would land at the bottom with no failure. The manifest field makes forgetting a test failure. | `tests/test_tool_plugin.py::TestUtilityGrouping` |
| D-03 | 2026-11-08 | **A caption is a `tk.Label`, not a `Frame`.** | The grid's card cells are the host's only `Frame` children, so card discovery — the layout's own `_relayout` and every geometry helper in `test_utilities_window.py` — cannot mistake a caption for a card. | `master_driver/ui/utilities_window.py::_GroupCaption` |
| D-04 | 2026-11-08 | **Plugins always render last, in their own section; a plugin's `group` is not read.** | The plugin manifest loader does not accept a `group` key, and it must not: a third-party manifest should not be able to rename or reorder a first-party section. | `audio_suite_shared/plugin_system/loader.py`; `TestUtilitySections::test_a_plugin_always_renders_last_in_its_own_section` |
| D-05 | 2026-11-08 | **An undeclared group costs a caption, never the card.** Such a manifest falls into a trailing "Other Tools" section. | The mirror-image defect — a tool that is registered but invisible — is the silent degradation this tab has shipped before (U-03). | `utility_sections`; `test_an_undeclared_group_keeps_its_card` |
| D-06 | 2026-11-08 | **The batch order change is accepted**: the three batch-capable utilities now run ASX → Converter → Album Art Normalizer (was Converter → ASX → Album Art Normalizer). The other utilities are standalone windows. | No utility declares a dependency (`DEPENDENCY_GRAPH`), extraction feeding conversion is the sane direction, and art normalization still follows conversion. Freezing the old order was the alternative, at the cost of one non-alphabetical row. | `master_driver/batch_orchestrator.py::DEPENDENCY_GRAPH` |
| D-07 | 2026-11-08 | **The guide artefacts were rebuilt, and only the guide this change edits enters the diff.** `--check` reported eight stale artefacts (`lyrics_manager`, `master_driver`, `ml_denoiser`, `spectral_viewer`, `stem_separator`, `tag_editor`, `tag_field_updater`, `undo_tag_edits`) after a rebuild-and-restore cycle. | AGENTS.md: a `.docx` is a build artefact and `test_user_guide_hygiene` fails on a stale one, so the rebuild is part of the change rather than a follow-up. A full rebuild re-rendered the seven besides this change to the bytes already committed, so they were restored to HEAD — the diff carries only the guide whose text changed, and `--check` reports all 32 current (see PLAN_2026-11-08_enrich_card_grouping.md D-06). | `utilities/build_user_guides.py --check` → "32 guide artefacts are current" |
| D-08 | 2026-11-08 | **The Master Driver guide's tool lists were corrected**, not just regrouped. | The Utility section named ten of eighteen utilities and filed Lyrics Manager under Utility although its manifest category is Enrich; the converter's "mixed input formats are rejected" sentence contradicted the D3/E4 recursive, mixed-format scanner. | `Master_Driver_User_Guide.md`; PLAN_iteration7_remediation E4 |

## Acceptance

| Check | Result |
|---|---|
| Compile | `python -m compileall -q -f .` exit 0 |
| Lint & format | `ruff check .` "All checks passed!"; `ruff format --check .` "1113 files already formatted" |
| Types | `mypy .` "Success: no issues found in 615 source files" |
| Security | `bandit -r . -x ./.venv -c pyproject.toml` → 0 High / 0 Medium (58 Low) |
| Focused suites | 436 passed — utilities window, UI cards, manifest registry, README index, guide resolution, guide hygiene, driver app, runner |
| Full suite | bare `pytest` — **12194 passed, 3 skipped, 35 deselected** in 19:05, with three failures in the repo's own convention locks: AGENTS.md cited `tests/test_tool_plugin.py` and a constant as a `::Class`, and the two touched `utilities_window` modules carried a `Changed in 2.6.0` note where the marker is the current release (`Changed in 2.5.0`). All three were fixed and their tests re-run green; the scratch `.txt` files the run left behind were deleted (they are what the release-note lock flagged). |
| Layout (measured, not assumed) | real tab at 1250×950: content **636 px** in an **849 px** viewport (213 px headroom), 19 cards, 6 captions × 20 px, first card 43 px, LAUNCH still outside the scroll area |

## Files touched

`audio_suite_shared/tool_plugin.py`, `audio_suite_shared/tests/test_tool_plugin.py`,
`master_driver/ui/utilities_window.py`,
`master_driver/tests/test_utilities_window.py`, `README.md`,
`documentation/docs/index.md`,
`documentation/user_guides/individual_programs/master_driver/Master_Driver_User_Guide.md`
(+ its 7 sibling `.docx` artefacts), `CHANGELOG.md`, `TECHNICAL_CHANGELOG.md`,
`AGENTS.md`, this plan.
