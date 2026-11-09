# PLAN — Categorise the change history, and lock the categories

**Status:** COMPLETE
**Governing brief:** the maintainer's report (2026-11-08) that since release
2.4.1 neither `CHANGELOG.md` nor `TECHNICAL_CHANGELOG.md` has shown which items
were Added, Changed or Deleted — "instead the items are just listed" — with two
questions: can the headings be added retrospectively, and can the omission be
prevented in future releases.
**Scope:** `CHANGELOG.md`, `TECHNICAL_CHANGELOG.md`,
`tests/test_changelog_format.py`, `AGENTS.md`,
`documentation/docs/release.md`, and this record.

## What was wrong

2.4.0 is the last section grouped under `### Added` / `### Changed` /
`### Fixed`. The five sections after it — `[Unreleased]`, 2.5.0, 2.4.3, 2.4.2
and 2.4.1 — are flat bullet lists in both files: **70 bullets**, 20 user-facing
and 50 technical.

Nothing caught it, and three separate things explain why:

- `utilities/release.py::promote_changelog` copies the `[Unreleased]` body
  verbatim under the new version heading, so the cut preserves a category — it
  never requires one. Its only emptiness test is `_is_meaningful`, which asks
  for a line starting `- `.
- `tests/test_changelog_format.py` held the wrapping, the two-space indent and
  the user/technical boundary, so an uncategorised section was structurally
  valid to every lock in the tree.
- `audio_suite_shared/whats_new.py::parse_blocks` already renders `### ` as a
  heading block, so the in-app panel and the release page render a flat section
  perfectly well — the omission changed emphasis, not legibility, and no
  rendering test had a reason to complain.

The headings are a reader's index: a release is read to learn whether something
is a new capability, a behaviour change or a repaired defect, and a flat list
makes that reader infer it from each sentence.

## The classification rule

| Category | What it means |
|---|---|
| **Added** | A capability, tool, flag, report, file or document that did not exist. |
| **Changed** | Existing behaviour, layout, default, format support or wording behaves differently. |
| **Deprecated** | Still works, being withdrawn. Unused today. |
| **Removed** | A capability, option, module or file that is gone. |
| **Fixed** | A defect repaired: wrong, refused, fabricated, or missing where the suite's own contract required it. |
| **Security** | A vulnerability or unsafe behaviour closed. |

**The bold lead-in decides**, exactly as it decides the audience (U2/D29). A
bullet that adds a report *and* repairs a missing one — "Every scan writes a
report, and View Log opens it." — is **Fixed**, because its subject is the
repaired contract. A bullet that introduces a shared implementation where five
copies stood is **Added** when it leads with the new module ("One FFmpeg
resolver for the suite.") and **Changed** when it leads with the rule that
found them ("The hand-built-path rule covers every binary the suite ships.").

The word is **Removed**, not *Deleted*: Keep a Changelog's vocabulary — which
this changelog's own header claims — has no `Deleted`, and the closed vocabulary
below refuses one.

## The retrospective pass

Inserted headings only: every bullet's lines were copied verbatim and whole
blocks moved, so the bullet text is byte-identical before and after (206
`CHANGELOG.md` bullet texts and 133 `TECHNICAL_CHANGELOG.md` ones compared, all
equal). Categories are written in canonical order and bullets keep their
relative order inside a category. Sections 2.4.0 and older are untouched — their
subsections already exist, and reordering released blocks is churn with no
reader benefit.

Totals: **Added 24, Changed 32, Removed 2, Fixed 12** (70).

### `CHANGELOG.md` (20)

| Section | Category | Bullet |
|---|---|---|
| Unreleased | Changed | The Utilities tab is grouped, and it is alphabetical inside each group. |
| Unreleased | Changed | The Enrich tab is grouped too. |
| Unreleased | Fixed | The Master Driver guide lists every utility. |
| 2.5.0 | Added | Join recordings into one file, with a crossfade or a gap between them. |
| 2.5.0 | Added | Split recordings into tracks at their silent gaps. |
| 2.5.0 | Added | Every tool's guide shows the windows it describes. |
| 2.5.0 | Added | Album loudness normalisation in Audio Refinery. |
| 2.5.0 | Added | Exact time-range trimming in Audio Refinery. |
| 2.5.0 | Fixed | Every legal file name is a legal input, everywhere. |
| 2.5.0 | Fixed | Guides show emphasis instead of asterisks. |
| 2.4.3 | Changed | Library Statistics Dashboard works in one window of seven tabs. |
| 2.4.3 | Changed | File Reorganizer works in one window of three tabs. |
| 2.4.3 | Fixed | Every scan writes a report, and View Log opens it. |
| 2.4.3 | Fixed | File Reorganizer writes a run report, and View Log opens it. |
| 2.4.3 | Fixed | The Master Driver's failure dialog says why a tool did not start. |
| 2.4.2 | Changed | WMA files are reported as unsupported by Tag Field Updater. |
| 2.4.1 | Added | WMA is now a first-class format, not a converter-only one. |
| 2.4.1 | Added | Raw AAC (`.aac`) is recognised as an input. |
| 2.4.1 | Fixed | Undo no longer lists a file whose tag write failed. |
| 2.4.1 | Fixed | An unsupported target extension is refused. |

### `TECHNICAL_CHANGELOG.md` (50)

| Section | Category | Bullet |
|---|---|---|
| Unreleased | Added | The Utilities tab's grouping is manifest data with two locks. |
| Unreleased | Changed | The Enrich tab's grouping reuses the Utilities splitter, not a copy. |
| Unreleased | Changed | Tests: the reflow locks are relative to the first card's row. |
| Unreleased | Changed | The release-note lock names 2.6.0. |
| 2.5.0 | Added | The suite finds its own files from one root. |
| 2.5.0 | Added | One FFmpeg resolver for the suite. |
| 2.5.0 | Added | One implementation per capability, and a lock that keeps it that way. |
| 2.5.0 | Added | The Track Splitter's engine is a pure parser beside one FFmpeg call. |
| 2.5.0 | Added | Guide figures: one capture step, one renderer block, two locks. |
| 2.5.0 | Added | Exact-trim locks and the second write path (F-E3). |
| 2.5.0 | Changed | The hand-built-path rule covers every binary the suite ships. |
| 2.5.0 | Changed | The reuse lock reads the launchers, and the launchers lost their third dialog copy. |
| 2.5.0 | Changed | The other packaged binary uses the shared search, and the third reuse rule closed the gap. |
| 2.5.0 | Changed | The reuse lock sees the second way a module can pick FFmpeg. |
| 2.5.0 | Changed | The ReplayGain analyzer runs the shared FFmpeg. |
| 2.5.0 | Changed | `AppState.__init__` grew past ruff's statement budget. |
| 2.5.0 | Changed | Album-mode locks, and the 2.5.0 note window (F-E1). |
| 2.5.0 | Fixed | The plan no longer writes leading or trailing silence as a track. |
| 2.4.3 | Added | The per-file change notes have a recorded ceiling (WP-10 C-I2). |
| 2.4.3 | Added | The suite publishes a per-package coverage table (WP-10 C-I9). |
| 2.4.3 | Added | The package-data declaration is checked in both directions (C-I6a). |
| 2.4.3 | Added | A suggestions list holds the ideas that are not in a plan. |
| 2.4.3 | Added | `audio_suite_shared` ships a PEP 561 marker (WP-10 C-I6). |
| 2.4.3 | Added | The run-report contract is a rule with an artefact lock. |
| 2.4.3 | Added | One batch-window shell. |
| 2.4.3 | Changed | Complexity ceiling adopted and the four worst functions restructured. |
| 2.4.3 | Changed | `library_cache` split into three modules (WP-9 #5). |
| 2.4.3 | Changed | The fingerprinter's `file_processor` split into three modules (WP-9 #4). |
| 2.4.3 | Changed | `batch_undo` split into three modules (WP-9 #3). |
| 2.4.3 | Changed | `file_processor_base` split into four modules (WP-9 #2). |
| 2.4.3 | Changed | `ui_common` split into four modules (WP-9 #1). |
| 2.4.3 | Changed | `library_stats` adopts the shell (WP-8 order #3). |
| 2.4.3 | Changed | One implementation of the "no log yet" branch. |
| 2.4.3 | Changed | The reorganiser adopts the shell, and its scan thread stops touching Tk. |
| 2.4.3 | Removed | The conversion re-export shim and two ignored `config_path` parameters are gone. |
| 2.4.3 | Fixed | The reorganiser writes a run report; View Log never opens the debug log. |
| 2.4.3 | Fixed | A refused launch explains itself (D-22). |
| 2.4.2 | Changed | One tag layer. |
| 2.4.2 | Changed | One measurement path. |
| 2.4.2 | Changed | One loudnorm parser. |
| 2.4.1 | Added | One driver handshake. |
| 2.4.1 | Added | One format capability matrix. |
| 2.4.1 | Added | A release cut now tags the version and publishes its GitHub release page. |
| 2.4.1 | Changed | Broad catches are a triaged baseline. |
| 2.4.1 | Changed | The tag-handler factory is a leaf module. |
| 2.4.1 | Changed | The per-file change-note lock is re-baselined to the 2.4.1 window. |
| 2.4.1 | Changed | One DSP model behind the enhancement presets. |
| 2.4.1 | Changed | The preset model is locked by measured audio, not field read-back. |
| 2.4.1 | Removed | Dead code removed and the last slot-var clone retired. |
| 2.4.1 | Fixed | `get_export_args` raises instead of writing MP3. |

## What changed

1. **The five sections are categorised** in both files, by the table above.
2. **The categories are a lock.** `tests/test_changelog_format.py` gains
   `TestChangelogCategories`, parameterised over both files like the format
   half: a section with bullets must carry a category heading; every bullet must
   sit under one; the six names are the only legal `###` headings; no category
   heading may be empty; an empty section must be `[Unreleased]`; and a
   non-vacuity floor (18 sections, 100 bullets) fails a collapsed walk instead
   of passing over nothing. `test_the_lock_rejects_a_flat_section` feeds the
   checkers 2.4.2's real flat body, an unknown `### Deleted` and an empty
   `### Added`, so the lock is proved able to fail where the defect lived.
3. **The rule is written where it is acted on:** `AGENTS.md` (*Change History
   Follows Its Audience*), `documentation/docs/release.md` (*Writing the
   entries*), and both changelog headers, so a contributor sees the vocabulary
   in the file they are editing.
4. **The cut needs no change.** `promote_changelog` already carries the
   headings through verbatim, and `release.tag_message` already builds the tag
   message and release page from that section, so a categorised `[Unreleased]`
   reaches all three surfaces unchanged.

## Decision log

| ID | Decision | Status | Rationale |
|---|---|---|---|
| D-01 | **The bold lead-in decides the category**, as it decides the audience. | DECIDED | One rule for both locks, and it is the sentence's subject rather than its tail that says what changed. Every call is recorded in the tables above, so a reclassification is a one-line diff here. |
| D-02 | **The retrospective pass moves whole blocks and rewrites no sentence.** | DECIDED | Verified by comparing all 206 and 133 bullet texts before and after: identical. Canonical category order, relative order kept inside a category; 2.4.0 and older untouched. |
| D-03 | **Only structure is enforced, not judgement.** | DECIDED | A test can prove a section is grouped and that a heading is one of the six; it cannot prove a bullet is really a fix. The rule is stated in AGENTS.md and the lead-in convention is what a reviewer checks. |
| D-04 | **`Removed`, never `Deleted`.** | DECIDED | The maintainer's wording was "Added, Changed or Deleted"; this changelog's header claims Keep a Changelog, whose vocabulary has no `Deleted`. The closed vocabulary refuses it, so the two spellings cannot drift. |
| D-05 | **The technical file may still omit a version heading entirely.** | DECIDED | `release.py` promotes it with `require_entries=False` (U2/D29). This plan adds no empty-section rule beyond "an existing section must hold bullets", so a release with no developer-facing change stays legal. |
| D-06 | **Published release pages keep their flat text.** | DECIDED | A GitHub release page is a snapshot taken at the cut; `--backfill-releases` only fills gaps. Refreshing an existing page is an external, authorised action and out of scope. Superseded by D-07, which the maintainer authorised on 2026-11-08. |
| D-07 | **The four drifted release pages were republished once, from the grouped sections, and verified by reading them back from the API.** | DONE (user, 2026-11-08) | `v2.4.1`-`v2.5.0` still served the flat text their cut published; the eight pages from `v2.4.0` back already matched their sections, so the comparison **measured** the drift rather than assuming it. Each body came from `utilities/release.changelog_section()` - the function a cut itself uses - and was refused unless it carried a `### ` heading; each edit was then confirmed with `gh release view --json body`, not by trusting the file that was written. A second run reports `[SKIP]` for all four. Deliberately not a `release.py` flag: a page is a snapshot, so rewriting published history stays a reviewed, authorised act rather than a switch. Tags, titles, assets, draft state and every page older than 2.4.1 were left untouched. |

## Verification

- `pytest tests/test_changelog_format.py` — the new class and the existing
  format/audience locks.
- `utilities/tests/test_release.py` and
  `audio_suite_shared/tests/test_whats_new.py` — the cut promotes a
  categorised body unchanged, and the panel renders headings.
- `utilities/changed_in_budget.py --record` — this file's own `Changed in
  2.6.0` note moves the 2.6.0 ceiling from 24 to 25 lines.
- The full project gate: compile, `ruff check`, `ruff format --check`, bare
  `mypy .`, bandit (0 High / 0 Medium), bare `pytest`.
