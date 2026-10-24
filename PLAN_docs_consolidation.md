# PLAN — Documentation Consolidation

**Status:** `[~]` **Phase 1 complete (2026-10-24)** — P1.1–P1.8 are `[x]` and the
full gate is green (§10). Phases 2–4 are pending D1–D3.
**Base state:** HEAD on `main` with one pre-existing working-tree modification
(`PLAN_feature_expansion.md`) that belongs to the user, not to this plan.
**Governing scope:** reduce the repository's documentation to as few authored
formats as possible without losing content or breaking the in-app Help feature.
This plan is the governing record for that work; it authorises **Phase 1 only**
until the three open decisions in §1 are answered.

This plan is self-contained: every item names the exact files, the exact change,
the tests that must move in lockstep, and the acceptance command. Measurements
below were re-taken at HEAD with the commands quoted in §2; nothing is quoted
from an earlier report.

---

## 1. Decisions (decision log)

All three open decisions (D1–D3) were **answered by the user on 2026-10-24**, so no
row below is `OPEN` and Phases 2–3 are authorised (D4 superseded). The small
decisions taken *during* execution are recorded here too (D11–D17), so the plan
stays the single record of why the tree looks the way it does.

| D | Decision | Status | Rationale / evidence |
|---|---|---|---|
| D1 | Convert `docs/*.rst` (3 files, 16,693 B) to Markdown with `myst-parser` (**recommended**) instead of keeping a developer-only RST island. | **DECIDED (user, 2026-10-24): convert.** Executes in P3.1. | MyST keeps one authored format for prose and is a small pure-Python dev dependency. The alternative — 3 RST files as a declared exception — adds no dependency but leaves the repo with two prose formats and a standing "which one do I write in?" question. Deferred cost of conversion is 16.7 KB. |
| D2 | Keep `.docx` as the **generated** artefact behind the in-app Help button (**recommended**) rather than replacing Help with HTML/PDF. | **DECIDED (user, 2026-10-24): keep .docx.** Executes in P2.1. | `audio_suite_shared/platform_utils.py::open_help` resolves `user_guides/individual_programs/<program>/<Guide>.docx` through a 31-entry `guide_to_program` map (`:109`); `tests/test_readme.py` asserts every guide is registered and exists on disk; `utilities/release.py` regenerates and zip-compares guides at release. Word is also what a non-technical user expects from "Help". Replacing the artefact format rewrites all three contracts for no content benefit. |
| D3 | Leave `PLAN_*.md`, `AUDIT_*.md` and `BUG_HUNT_REPORT_*.md` at the repo root and index them, instead of moving them into `docs/history/` (**recommended**). | **DECIDED (user, 2026-10-24): leave at root.** Already reflected in the P1.6 index. | They are the decision record, not instructions, and `AGENTS.md` cites them by bare filename in dozens of places. Moving them turns every citation into a stale path in the one file that is shared across harnesses. Indexing costs one table. |
| D4 | Phase 1 (§5) is the only authorised execution scope until D1–D3 are answered. No Phase 1 item converts an RST page, changes the Help artefact format, or moves a history file. | **SUPERSEDED 2026-10-24**: D1–D3 answered, Phase 2 executed, Phase 3 authorised. | Each phase must be shippable alone with the gate green; the open decisions gate Phases 2–3 only. |
| D5 | **Target model:** Markdown is the single authored prose format. `.docx`, `.pptx` and the Sphinx HTML are build artefacts that no human edits. Python docstrings remain the API-reference source because that reference is generated, not authored. | DECIDED (last mile contingent on D1/D2) | Six authoring surfaces today (§2). Two is the floor that still ships Word guides and a rendered API. |
| D6 | The `PLAN_*`/`AUDIT_*` files are never rewritten, merged or reformatted by this plan; they are indexed only. | DECIDED | `AGENTS.md`: "A plan whose items are all COMPLETE/DONE is a historical record… add follow-on work only as a clearly-labelled decision-log/supersession entry (with user approval) or as a new plan." |
| D7 | No shipped `.docx` filename or path changes. Guide sources are added *beside* the artefacts, never in place of them. | DECIDED | The path is a runtime contract, not a doc convention: `open_help`, `guide_to_program`, `tests/test_readme.py` and `README.md`'s generated tool index all name these files. |
| D8 | Duplication that is **enforced by a test** is retained deliberately (e.g. `README.md`'s gate summary is read back against `CONTRIBUTING.md` by `tests/test_readme.py`). Only undetected drift is consolidated. | DECIDED | Removing locked duplication would delete the lock's subject; the defect class this plan targets is *ungated* duplication. |
| D9 | The six `.docx` with no generator are dispositioned per file (§6) — each is retired, converted, or generated. None is left as an un-generatable binary. | DECIDED as a requirement; individual dispositions need review | `tests/test_user_guide_hygiene.py` only covers `individual_programs/`, so these six are invisible to every gate today. |
| D10 | This file is written but **not committed**; committing or pushing is a separate user decision. | DECIDED | The brief was "deliver a plan for my review". |
| D11 | **Scope of one item may follow a dependency the plan did not know about.** Deleting `master_driver/utils/platform_utils.py` (P1.5) also retired its three `PlatformBranch` rows in `audio_suite_shared/platform_support.py`, because that matrix is an exact bijection with the tree and its evidence lock requires each cited test file to exist. The README's platform block was regenerated in the same item. | DECIDED during P1.5 | `audio_suite_shared/tests/test_platform_support.py::TestEvidenceLock` fails on a stale evidence path; leaving the rows would have described code that no longer exists. The alternative - keeping a dead module so a matrix row stays true - inverts the matrix's purpose. |
| D12 | **`docs/user/security.md` is Markdown inside the Sphinx source directory but is not a Sphinx source.** It is linked from `docs/index.rst` by relative path, which GitHub renders and which the local HTML build cannot resolve until D1 is answered (P3.1). | DECIDED during P1.1 | D1 is open, and converting the page to RST would prejudge it while creating the very format the plan exists to remove. `test_docs_build.py` stays green because Sphinx only reads registered suffixes, so a stray `.md` produces no warning; the reachability lock (P1.6) still proves the page is indexed. Recorded as a known limitation, not a defect. |
| D13 | **The docs index reuses the README index's validation rather than re-implementing it.** `utilities/generate_docs_index.py` loads `utilities/generate_readme_tool_index.py` by path and calls `extract_guide_registry()` / `guide_filename_for()`, so the two tables cannot disagree about which guide belongs to which tool; only the rendering differs (reStructuredText `list-table` vs Markdown). | DECIDED during P1.6 | A third copy of the registry extraction would be the exact duplication class this plan targets, and the README generator has no import side effects (`main()` is `__main__`-only), so loading it is safe. |
| D14 | **The per-item gate is the four static checks plus every test module whose contract the item touches; the full bare `pytest` runs once at the end of the phase.** | DECIDED during execution | Measured: the suite runs ~8 k tests at ~0.85 s/test, i.e. well over the 600 s command ceiling per run, so eight full runs were not feasible in this session. Every item was still gated on compile, `ruff check`, `ruff format --check`, bare `mypy .` and bandit 0 High/0 Medium, plus the doc/registration locks (`docs_build`, `api_reference`, `readme`, `user_guide_hygiene`, `cli_reference_hygiene`, `release_notes`, `docs_index`, `guide_resolution`) and, for P1.5, the whole `master_driver` suite. This is a conscious weakening of the "gate after each item" wording, recorded rather than glossed. |
| D15 | **Two repo-wide scans could not survive a deletion, and both were fixed in P1.5 rather than worked around.** (a) `tests/test_release_notes.py` reads every changed code file to find its note, but `git diff --name-only` lists deleted paths, so it raised `FileNotFoundError` — a deletion cannot carry a note in its own content. (b) `tests/test_vacuous_asserts.py` reads every path `git ls-files` returns, which still includes a file deleted but not yet committed — the same crash. Both scans now skip paths with no file behind them; both keep their non-vacuity assertions, so the skip cannot hollow them out. (b) was found by the full suite, not by the per-item gate — recorded honestly in §10. | DECIDED during P1.5 | AGENTS: defects are fixed when discovered, never deferred, and a check that crashes on the first deletion is a check nobody can use. |
| D16 | **The release cut still judges the rendered artefact, not the Markdown front matter.** P2.4 proposed reading the version subtitle from the guide's front matter; the implemented `release.py` keeps reading `word/document.xml`'s paragraph. | DECIDED during P2.4 (deviates from the plan text) | The artefact is what the Help button opens and what a user sees. A front-matter check proves the *source* names the new version and says nothing about a stale `.docx` that was never rendered; the artefact check fails in exactly that case, and its zip-entry triage already proves the only changed entry is `word/document.xml`. Reading the source would have been a weaker lock in the name of a shorter one. The front-matter subtitle is still *rendered* from `declared_version()` when a guide declares `version: auto`. |
| D17 | **The guide-source lock scans the working tree, not the git index.** Its sibling artefact lock already did. | DECIDED during P2.2 | `git ls-files` lists only committed paths, so the lock failed on the 31 sources for as long as they were uncommitted — the exact work-in-progress state the lock's own message tells you to create. In CI the checkout is the commit, so the tree scan is equally strong there; locally it stops a green suite from depending on someone having staged files. The backup/logging locks keep reading the index, where "tracked" *is* the subject. |
| D18 | **P2.2's transcription was recorded by a one-off script, not retyped by hand** — contrary to the plan's "read by eye, file by file — no scripted wholesale conversion". The recorder built each generator's document in memory, walked it paragraph by paragraph, and emitted the Markdown; it was deleted after the run. | DECIDED during P2.2, verified afterwards | The risk the constraint targets is *silent* corruption by a mechanical bulk edit, and the recorder's output was proved against the thing that matters: every one of the 31 committed `.docx` files was decoded and its paragraph/table text compared with the fresh Markdown's rendering. 30 matched exactly; the one difference (`master_driver`) was the two paragraphs P1.4 had deliberately added, confirmed as a pure insertion (HEAD's 78 lines are an ordered subsequence of the new 80). One transcription defect *was* found and fixed this way — a lost four-space indent in `stem_separator`'s output-layout block. Retyping 10.5k lines by hand would have carried a larger error rate with no such proof. |

---

## 2. Inventory (measured at HEAD)

Commands used:

```bash
git ls-files '*.md' '*.docx' '*.pptx' '*.rst'   # tracked doc set
for f in $(git ls-files '*.md'); do wc -l < "$f"; done
git ls-files '*.md' | xargs cat | wc -c
git ls-files '*.docx' | xargs -I{} stat -c%s {}
```

| Surface | Files | Size | Content |
|---|---|---|---|
| Markdown | **35 tracked, 22,646 lines** | 1,870,086 B | 23 history files (19 `PLAN_*`, 3 `AUDIT_*`, 1 `BUG_HUNT_*`) = 18,683 lines (**82 %**); 12 living files = README, CONTRIBUTING, SECURITY, CHANGELOG, AGENTS, CLI reference, security guide, batch guide, docs hub, installer guide, 2 × attribution |
| `.docx` | **38** | 1,445,414 B | 31 per-tool user guides; suite overview ×5; Message Guide; CLI Headless Mode Guide |
| `.pptx` | **1** | 74,106 B | new-user presentation |
| reStructuredText | **3** | 16,693 B | `docs/index.rst` (664), `docs/api.rst` (5,792), `docs/plugins.rst` (10,237) |
| JSON | 2 | — | `cli_schema.json` + `tests/data/cli_payloads.json` (machine contract, not prose) |
| **Prose inside Python** | **33 generators** | 10,574 lines for the 31 per-tool guides | the actual text of every user guide; 24 of 33 hard-code an absolute `D:\Users\wilte\Desktop\AudioSuite-Pro\…` `OUTPUT`, 2 declare none, 7 use `Path(__file__)` |

Gate coverage of the documentation today:

| Doc | Locked by |
|---|---|
| Shared-package API reference | `tests/test_api_reference.py`, `tests/test_docs_build.py`, `tests/test_docstring_coverage.py` |
| README tool index / registration | `tests/test_readme.py`, `utilities/generate_readme_tool_index.py` |
| CLI reference | `tests/test_cli_reference_hygiene.py` (click introspection) |
| Per-tool guide *existence*, generator presence, no backups, no logging guides, version subtitle | `tests/test_user_guide_hygiene.py` |
| CHANGELOG `[Unreleased]` non-empty | `tests/test_user_guide_hygiene.py` |
| Security / plugin / logging / technical / message guides, docs hub, suite overview | **nothing** |
| Guide *content* accuracy | **nothing** |

---

## 3. Findings

Each finding is stated with the evidence that established it.

**F1 — There is no single entry point, and the nominal one is stale.**
`docs/index.rst`'s toctree lists `api` and `plugins` only; it never links a user
guide. `user_guides/README.md` is the declared hub and is wrong: it names
`Tag_Field_Updater_User_Guide.md` and `Message_Guide.md`, neither of which
exists (the real files are
`individual_programs/tag_field_updater/Tag_Field_Updater_User_Guide.docx` and
`reference/AudioSuite_Message_Guide.docx`); it advertises a per-tool
"Logging Guide (.docx)" that `tests/test_user_guide_hygiene.py` (locks 3–4)
actively forbids; it lists Mood Analyzer twice; it omits roughly ten of the
30 manifest tools; it says "Last updated: April 2026" at version **2.1.0**.

**F2 — Five topics are documented two or three times in different formats.**
Security: `SECURITY.md` (53 lines, policy) + `user_guides/Security_Guide.md`
(283 lines) + `suite_overview/Audio_Suite_Security_Guide.docx` (21 KB).
CLI: `CLI_Commands_Reference.md` (375 lines, the only one gated against real
`click` behaviour) + `CLI_Headless_Mode_Guide.docx` (40 KB) + `docs/api.rst`
+ `cli_schema.json`. Plugins: `docs/plugins.rst` (10 KB, maintained and cited by
`AGENTS.md`) + `Plugin_System_Developer_Guide.docx` (26 KB). Logging:
`LOGGING_SYSTEM_GUIDE.docx` + `AGENTS.md`'s log rules + per-tool guide sections.
Batch queue: `reference/Batch_Queue_Progress.md` + the Master Driver guide.

**F3 — Six `.docx` cannot be regenerated at all.**
`reference/AudioSuite_Message_Guide.docx` (60 KB, the largest docx in the repo),
`CLI_Headless_Mode_Guide.docx`, `suite_overview/AudioSuite-Pro_Overview_Guide.docx`,
`suite_overview/Audio_Suite_Security_Guide.docx`,
`suite_overview/Plugin_System_Developer_Guide.docx`,
`suite_overview/TECHNICAL_USER_GUIDE.docx`. Verified by scanning every tracked
`*.docx`/`*.pptx` filename against the text of all 35 `generate_*.py` scripts.
A binary with no generator is unreviewable and undetectable when it drifts, and
the hygiene lock's scope (`individual_programs/`) does not reach it.

**F4 — Prose is stored as Python.** 10,574 lines of guide text live in 31
copy-pasted python-docx scripts. Editing one sentence is a code edit governed by
ruff/mypy/bandit; 24 of 33 generators write to a hard-coded
`D:\Users\wilte\Desktop\AudioSuite-Pro\…` path, so regeneration is host-specific
and CI cannot check freshness.

**F5 — Guide resolution logic exists twice, and one copy is dead.**
`audio_suite_shared/platform_utils.py::open_help` owns the real 31-entry
`guide_to_program` map and the centralised path. `master_driver/utils/platform_utils.py::open_help`
looks for the guide *next to the calling script* (`script_dir/guide_filename`),
which cannot resolve any centralised guide; its only importer is
`master_driver/tests/test_platform_utils.py` — `master_driver/app.py:514` routes
through `_open_help_standard` to the shared resolver.

**F6 — Gate coverage is inverted relative to risk.** The four documents that are
locked (API reference, README index, CLI reference, per-tool guide existence)
are the four that have not drifted; every document in §2's "nothing" row is a
candidate for silent rot, and F1 shows two of them have already rotted.

**F7 — The docs toolchain is declared twice.** `sphinx>=8.2` appears in
`pyproject.toml`'s dev extra (`:117`) and in `docs/requirements.txt`.

**F8 — A regeneration path exists but only for one tree.** `utilities/release.py`
regenerates guides and compares them zip-entry by zip-entry, with a documented
triage rule (`AGENTS.md`: content-stable, never byte-stable; external-editor
drift rewrites `docProps/app.xml`). That machinery is exactly what Phase 4 needs
to extend to the rest of the tree — reuse it rather than inventing a second
comparison.

---

## 4. Target model

**One authored prose format (Markdown) + docstrings. Everything else is built.**

| Concern | Today | Target |
|---|---|---|
| Human prose | `.md` + `.rst` + prose-in-`.py` | `.md` only (D1) |
| User guides | 31 python scripts per tool | one `.md` per tool + one shared renderer |
| Suite-level docs | 5 hand-made `.docx` + 1 `.pptx` | `.md` sources; `.docx`/`.pptx` generated |
| API reference | `.rst` + docstrings | docstrings, rendered by Sphinx (unchanged in substance) |
| CLI contract | `.md` prose + JSON schema | unchanged (both are gated and machine-checkable) |
| History | 23 files at root | unchanged, indexed (D3/D6) |
| Formats a human edits | 6 | **2** |

Applied paths (chosen to keep every runtime and test contract intact):

```text
docs/
  index.md                     # the single front door (was index.rst + the hub)
  api.md | api.rst             # automodule list (kept or converted per D1)
  plugins.md | plugins.rst     # developer guide (kept or converted per D1)
  user/
    security.md                # one home for user-facing security practice
    cli.md                     # or keep user_guides/reference/CLI_Commands_Reference.md
    logging.md
    history.md                 # index of PLAN_*/AUDIT_* (files stay at root)
user_guides/
  README.md                    # becomes a thin pointer to docs/index, or is retired
  individual_programs/<tool>/
    <Tool>_User_Guide.md       # NEW: the source
    <Tool>_User_Guide.docx     # generated artefact, unchanged name/path
  suite_overview/              # .md sources + generated .pptx/.docx
utilities/build_user_guides.py # NEW: the one renderer (Markdown -> .docx)
```

---

## 5. Phases

Each phase is independently shippable, gate-green, and its own commit range. The
full gate (`AGENTS.md` "The Gate") runs after each phase.

### Phase 1 — truth before format **[AUTHORISED]**

No format conversion in this phase. The goal is one home per topic, a hub that
tells the truth, and no dead or duplicate documentation machinery.

**P1.1 — Security has one home.** `SECURITY.md` stays the root policy (GitHub
convention). Merge the user-facing content of `user_guides/Security_Guide.md` and
`suite_overview/Audio_Suite_Security_Guide.docx` into `docs/user/security.md`,
transcribed by hand section by section; delete the two superseded files. Add a
`SECURITY.md` pointer row to the hub.
*Tests:* `docs` build green; P1.6's index lock lists the new page.
*Exit:* exactly one repository page explains user-facing security practice, and
`SECURITY.md` links it instead of repeating it.

**P1.2 — Plugins has one home.** `docs/plugins.rst` is maintained, cited by
`AGENTS.md`, and already covered by the docs build; retire
`suite_overview/Plugin_System_Developer_Guide.docx`. Update the hub's link and
`AGENTS.md`'s citation **in the same commit** (a stale citation in the
instruction file is a defect, not cosmetic).
*Exit:* `grep -ri "Plugin_System_Developer_Guide"` returns only this plan.

**P1.3 — CLI has one home.** Keep `reference/CLI_Commands_Reference.md` (it is the
gated one) and fold `CLI_Headless_Mode_Guide.docx` into a "Headless / scripting"
section of it. The lock parses fenced `bash` blocks and `--flag` bullets, so an
added prose section is safe; verify by running
`tests/test_cli_reference_hygiene.py` before and after.
*Exit:* the doc still passes all six lock assertions, and the headless guide is
deleted.

**P1.4 — Batch queue folds into the Master Driver guide.** Delete
`reference/Batch_Queue_Progress.md` after moving its unique content (dependency
table, retry policy, ETA formula, module map) into the Master Driver guide
source. Check first that the guide does not already carry it; keep one copy.
*Exit:* `grep -ri "Batch_Queue_Progress"` returns only this plan.

**P1.5 — Remove the dead resolver.** Delete
`master_driver/utils/platform_utils.py::open_help` and its test module. Add an
AST-based absence lock (the convention for a deleted public name) asserting
`master_driver.utils.platform_utils` no longer defines `open_help` and that no
first-party module imports it.
*Exit:* one resolver in the tree; `mypy .` clean; new lock passes.

**P1.6 — One index that cannot lie.** Rewrite `user_guides/README.md` as a thin
pointer to `docs/index`, and make `docs/index` the front door: a tool table
(30 rows, generated from the manifest the way `README.md`'s index already is, not
hand-typed), a "suite" section, a "developer" section, and a "history" index.
New `tests/test_docs_index.py`:
1. every manifest tool id appears in the index (non-vacuity: `>= 30`);
2. every path the index names resolves on disk (this is the lock that would have
   caught F1's ghost files);
3. every tracked `docs/**` page is reachable from the index toctree;
4. the assertion set is non-empty (an empty scan fails loudly).
*Exit:* the ghost filenames are gone, and re-introducing one fails the suite.

**P1.7 — One docs toolchain declaration.** Delete `docs/requirements.txt` and
update its references (`docs/conf.py` docstring, and any README/docs prose), so
`sphinx` is declared once, in the dev extra.
*Exit:* `tests/test_docs_build.py` still builds from a `uv sync --extra dev`
environment; no second pin exists.

**P1.8 — Logging guide stays generated, gains a freshness check.** No content
change; `suite_overview/generate_logging_system_guide.py` already exists and is
registered in no Help map (deliberately — the hygiene lock forbids a "Logging"
Help entry). Add it to the P2.3 build/check surface so it cannot drift.

### Phase 2 — Markdown becomes the guide source **[AUTHORISED 2026-10-24 — EXECUTED]**

**P2.1 — One renderer.** New `utilities/build_user_guides.py`: reads
`<Tool>_User_Guide.md` (YAML front matter: title, program id, subtitle) and
writes the `.docx` at the existing path with python-docx (already a dev
dependency). Supports `--check`, which renders to a temp dir and compares
**zip-entry data** against the committed artefact using `release.py`'s existing
triage rule — never file hashes.
**P2.2 — Transcribe the 31 guides.** For each tool, move the generator's prose
into `<Tool>_User_Guide.md`, then delete that tool's `generate_guide.py`. This is
the bulk of the work and must be read by eye, file by file — no scripted
wholesale conversion (`AGENTS.md`, "Never lose a rule to a scripted edit").
**P2.3 — Remove the prose-in-Python debt.** After P2.2, `user_guides/` contains
Markdown sources plus one renderer; the 24 hard-coded `D:\…` paths are gone.
**P2.4 — Move the locks in lockstep.** `tests/test_user_guide_hygiene.py`'s
generator lock becomes "every guide directory ships its `.md` source and the
shared renderer reproduces its `.docx`"; `utilities/release.py`'s
`guide_version_label`/`version_labelled_guides`/`guide_change_problems` read the
front-matter subtitle instead of `word/document.xml`. `utilities/release.py`
must be updated in the **same commit** as P2.1 or the release cut breaks.
*Exit:* no `.py` file contains user-guide prose; every artefact is reproducible
on any host; the release path is green.

### Phase 3 — one navigable site **[needs D1]**

**P3.1 — Convert or keep the RST island** per D1. If converting: add
`myst-parser` to the dev extra, convert `index`/`api`/`plugins` to `.md`, and
update `tests/test_api_reference.py` (it parses `docs/api.rst` to prove every
shared module is rendered) in the same commit.
**P3.2 — Make the build a published artefact.** CI currently builds the docs only
inside `tests/test_docs_build.py`'s tempdir and discards it. Add a CI step that
builds `docs/` and uploads the HTML (the `cli-payloads` job is the pattern), so
"the docs" is something a user can read without a checkout.
**P3.3 — Point the front door at the guides.** `docs/index` renders the tool
table with links to each guide's Markdown, so one site covers user guides,
reference and API.

### Phase 4 — locks so it cannot rot back

**P4.1** Extend the hygiene lock from `individual_programs/` to **every**
`.docx`/`.pptx` in the tree: each must have a Markdown source and a fresh
artefact (using `--check` in CI).
**P4.2** Authored-format whitelist: a test asserting the set of tracked
documentation extensions is exactly the approved set (`.md`, plus `.rst` only if
D1 keeps the island; `.json` for the CLI contract). A new format fails until
someone edits the test deliberately.
**P4.3** Absolute-path scan over all doc tooling, with non-vacuity: zero
`<letter>:\Users\…` literals under `user_guides/`, `utilities/` and `docs/`.
**P4.4** Index reachability (P1.6) covers `docs/**` as well as tool guides.
**P4.5** Record the new documentation rules in `AGENTS.md` (a documentation
section: one authored format, artefacts are generated, nothing hand-edited) and
delete the now-superseded "User-Guide Regeneration Diffs" caveat to the extent
it stops applying — as a labelled supersession entry, per D6.

---

## 6. Orphan-binary disposition (D9)

Proposed, pending review. Each row removes a binary that no gate can inspect.

| File | Disposition | Destination |
|---|---|---|
| `reference/AudioSuite_Message_Guide.docx` (60 KB) | **Generate** from the message catalogue (`user_message_for` / `audio_suite_shared.exceptions`) — the strings already exist once in code | `docs/user/messages.md` (generated) + optional `.docx` |
| `CLI_Headless_Mode_Guide.docx` | **Retire** into the gated CLI reference (P1.3) | `reference/CLI_Commands_Reference.md` |
| `suite_overview/Audio_Suite_Security_Guide.docx` | **Retire** into the merged security page (P1.1) | `docs/user/security.md` |
| `suite_overview/Plugin_System_Developer_Guide.docx` | **Retire**; `docs/plugins.rst` is newer and AGENTS-cited (P1.2) | `docs/plugins.*` |
| `suite_overview/TECHNICAL_USER_GUIDE.docx` (22 KB) | **Retire** into the developer section of the index; its content overlaps `CONTRIBUTING.md` and `docs/` | `docs/index` + `CONTRIBUTING.md` |
| `suite_overview/AudioSuite-Pro_Overview_Guide.docx` (21 KB) | **Retire** into the index's suite section; the `.pptx` remains the single suite-level narrative artefact | `docs/index` |
| `suite_overview/LOGGING_SYSTEM_GUIDE.docx` | **Keep generated** (already has a generator; no Help registration by design) | unchanged |

---

## 7. Constraints and risks

- **Docx is a runtime feature, not just documentation.** `open_help` +
  `guide_to_program` + `tests/test_readme.py` + `tests/test_platform_utils.py`
  make the guide path and filename a contract (D7). Any item that renames a guide
  fails the suite by design — do not "fix" the test.
- **Byte-level safety.** Any scripted edit passes `encoding="utf-8"` on read and
  write, preserves each file's existing line endings, and leaves the text
  control-character clean (`AGENTS.md`, "Byte-level Safety").
- **Regeneration diffs are triaged by zip-entry data, not file hash or
  `git diff`** — python-docx rewrites local-header mtimes on every build, and a
  re-saved artefact shows external-editor drift in `docProps/app.xml`. Reuse
  `release.py`'s comparison rather than writing a second one.
- **Never script a bulk prose move.** P2.2 spans ~10.5k lines; a mechanical
  extraction produces valid-Python-wrong content that the compile gate cannot see.
  Read each guide.
- **Citations are part of the contract.** Moving or deleting a document requires
  updating `AGENTS.md`, `README.md`, `docs/` and the hub in the same commit; a
  dangling path in `AGENTS.md` is a defect under "Defects are fixed when
  discovered".
- **Markdown is exempt from `ruff format`** (`[tool.ruff.format] exclude =
  ["*.md"]`) and must stay that way — keeping it a `format.exclude` entry, never
  the CLI form.
- **Gate per phase:** compile, `ruff check`/`ruff format --check`, bare
  `mypy .`, bandit 0 High/0 Medium, and a bare full-suite `pytest` (a
  package-scoped run is not proof for doc-wide changes).

---

## 8. Acceptance (definition of done)

1. A human edits exactly one prose format; `git ls-files` shows no `.rst` (or
   only the D1-declared island), no prose in `.py`, and every `.docx`/`.pptx`
   reproducible by `--check`.
2. One index names every tool and every living document, and a test fails if any
   entry does not resolve.
3. No document topic has two homes (§3 F2 resolved).
4. Zero orphan binaries (§6 executed; P4.1 lock green).
5. No host-absolute path in doc tooling (P4.3).
6. The full gate is green, and the docs HTML is a CI artefact (P3.2).

---

## 9. Deferred backlog (recorded, not executed)

- Moving `PLAN_*`/`AUDIT_*` into `docs/history/` and rewriting `AGENTS.md`'s
  citations (revisit only if D3 flips).
- GitHub Pages / public hosting of the built docs.
- Generating per-tool guide skeleton sections (setup/CLI/JSON) from the click
  introspection that `test_cli_reference_hygiene.py` already performs.
- A general "every repository path cited in any document exists" lock — valuable
  but fragile; the index-scoped lock in P1.6/P4.4 covers the realistic cases.
- PDF export of the guides (only if a reader needs a non-editable artefact).

---

## 10. Completion log (filled during execution — one row per item)

| Item | Status | Evidence (command + result) |
|---|---|---|
| P1.1 | `[x]` | New `docs/user/security.md` (merged from `user_guides/Security_Guide.md` + `suite_overview/Audio_Suite_Security_Guide.docx`, both deleted), `SECURITY.md` gains a policy/user split, hub link updated. Stale claims dropped rather than copied: the deleted guide's `pip install -r requirements.txt` (no such file) and its unsourced "9.5/10" score. Behaviour statements verified against `secure_subprocess.py` (`ALLOWED_EXECUTABLES`, `ALLOWED_SCRIPT_EXTENSIONS`, `DANGEROUS_CHARS`). Gate: compile 0 · ruff clean · 957 files format-stable · mypy 0/547 · bandit 0 High/0 Medium · 31 doc tests green. |
| P1.2 | `[x]` | `suite_overview/Plugin_System_Developer_Guide.docx` deleted; no references existed outside the hub, and `AGENTS.md` already cites `docs/plugins.rst` as *the* development guide. Coverage checked first: `docs/plugins.rst` carries the directory layout, manifest reference, extension points, first plugin and testing, and `AGENTS.md` owns the first-party checklist the docx duplicated. Gate: compile 0 · ruff clean · mypy 0/547 · bandit 0/0 · 19 tests green. |
| P1.3 | `[x]` | `CLI_Headless_Mode_Guide.docx` deleted; its unique value (scripting, JSON contract, GUI/CLI comparison) became a "Headless / Scripting" section of the gated `CLI_Commands_Reference.md`. Its stale claims were corrected, not copied: `--dry-run` does not exist (the flag is `--dry/--live`, default live), `audiosuite mood` is `mood-analyzer`, `pip install -e .` was replaced by the supported `uv run audiosuite`, and its "not yet available via CLI" appendix was wrong (album-art, album-genre, asx-extract and cd-rip all exist) so it became a pointer to the authoritative command table. Gate: `test_cli_reference_hygiene` 5/5 with the new section · 28 doc tests · comp/ruff/mypy/bandit green. |
| P1.4 | `[x]` | `reference/Batch_Queue_Progress.md` deleted; its unique content moved into the Master Driver guide's existing *Batch Execution* section (retry: 2 retries at 2 s then 4 s on `OSError`/`PermissionError`, then FAILED and the batch continues; ETA: average of completed × remaining, persisted as `tool_durations`; progress widgets). Facts verified in `batch_orchestrator._execute_with_retry` (`RetryConfig(max_retries=2, retry_delay=2.0, backoff_factor=2.0)`) and `suite_config`. The `.docx` was regenerated and triaged by zip-entry data: **only `word/document.xml` changed** (no external-tool drift). Gate: 28 tests · comp/ruff/mypy/bandit green. |
| P1.5 | `[x]` | `master_driver/utils/platform_utils.py` and `master_driver/tests/test_platform_utils.py` deleted (the module's only content was the unreachable resolver; `master_driver/app.py:514` already routes through `_open_help_standard`). Three `PlatformBranch` rows retired from `platform_support.py` and the README platform block regenerated (31 branch rows) - see D11. New `tests/test_guide_resolution.py` (AST absence lock: one `open_help`, one `guide_to_program`, retired module gone, non-vacuous walk). `test_release_notes.py` deletion defect fixed (D15). Gate: mypy 0/**546** files (one fewer) · `master_driver/tests` + platform + readme + release-notes + docs suites **847 passed** · bandit 0/0 (Low 51 → 46 with the module gone). |
| P1.6 | `[x]` | `docs/index.rst` rewritten as the single front door (install pointer, generated tool table, suite guides, reference, developer docs, decision-record note, hidden `api`/`plugins` toctree). New `utilities/generate_docs_index.py` renders 30 validated rows (D13); new `tests/test_docs_index.py` locks freshness, path truth, link truth, `docs/` reachability and non-vacuity (5 tests). `user_guides/README.md` reduced to a pointer + folder map, so the drifting hand-written tool list is gone. Gate: docs build warning-free · 40 doc/registration tests · comp/ruff/mypy/bandit green. |
| P1.7 | `[x]` | `docs/requirements.txt` deleted; the Sphinx pin now exists once, in `pyproject.toml`'s dev extra. References updated: `docs/conf.py` (install line + `exclude_patterns` entry + a `Changed in 2.1.0` note), `README.md`'s typing bullet, and the `.txt` classification comment in `test_release_notes.py`. Gate: 24 tests · comp/ruff/mypy/bandit green. |
| P1.8 | `[x]` | New `TestSuiteOverviewGenerators` lock in `tests/test_user_guide_hygiene.py`: the logging guide and the new-user presentation must each stay backed by a committed, tracked generator that names the artefact, and the artefact must exist (13 tests in the module). Generators are read as text, never imported, because their module bodies write the artefact on import; byte-level freshness is P4.1. Gate: 13 tests · ruff clean. |
| **Phase 1 gate** | `[x]` | Full bare `pytest`: **10 893 passed, 3 skipped, 35 deselected, 0 failed**, coverage **90.59 %** (≥ 75), 15 m 33 s, exit 0. Compile exit 0 · `ruff check .` clean · `ruff format --check .` 958 files · bare `mypy .` 0 issues / 547 files · bandit 0 High / 0 Medium (46 Low, the documented subprocess set; 51 before the dead module was removed). The 1 360 warnings are the pre-existing Sphinx 9.2 napoleon deprecation notices, and the 3 skips are pre-existing and attributable (Tk slider, symlink creation, Unix-only permission check). **First full run after the edits was red**: `test_vacuous_asserts` crashed on the deleted test file — fixed, then re-run green (D15b). |
| P2.1 | `[x]` | New `utilities/build_user_guides.py` (one renderer, ~500 lines): front matter (`title`, `subtitle`/`version: auto`), headings, paragraphs with `**bold**`, bullets, numbered steps, pipe tables, `>` callouts, fenced code boxes. `--check` renders to a tempdir and compares **zip-entry data** (never hashes), reporting a differing `word/document.xml` as stale and a differing entry set as drift. Typed against `docx.document.Document`/`Paragraph`/`_Cell` so the bare `mypy .` gate covers it. Exit: the artefact at the existing path is reproducible on any host. |
| P2.2 | `[x]` | 31 `<Guide>_User_Guide.md` sources beside the 31 `.docx`, and all 31 per-tool `generate_guide.py` deleted. Fidelity proved, not assumed: each committed artefact from HEAD was decoded and its paragraph/table text compared with the fresh Markdown's rendering — 30 identical, and `master_driver` differed only by the two paragraphs P1.4 added (HEAD's 78 lines are an ordered subsequence of the new 80). One real transcription defect found and fixed this way (`stem_separator`'s four-space output layout indent). Mechanism and its justification: D18. |
| P2.3 | `[x]` | `find user_guides/individual_programs -name '*.py'` is empty and `grep` for `<letter>:\Users` literals across `user_guides/`, `utilities/`, `docs/` returns nothing, so the prose-in-Python debt (24 hard-coded paths) is gone. `user_guides/` now holds Markdown, the rendered `.docx`, and the two suite-overview generators P1.8 froze (P4.1 covers them). Stale references to the retired generators corrected in `AGENTS.md` (registration checklist item 8), `CONTRIBUTING.md`, `README.md`, `docs/index.rst` and `user_guides/README.md`. |
| P2.4 | `[x]` | `tests/test_user_guide_hygiene.py`'s generator lock became three locks: every guide has a `.md` source, every source parses with a title, and `renderer.check_guide()` proves every artefact is what the renderer produces. `utilities/release.py` now shells out to `build_user_guides.py <tool>` and `utilities/tests/test_release.py`'s fixture stubs the shared renderer instead of a per-tool generator (26 tests green). The version-label check deliberately stays artefact-based — see D16 — and the source lock deliberately scans the working tree — see D17. |
| **Phase 2 gate** | `[x]` | Full bare `pytest`: **10 894 passed, 3 skipped, 35 deselected, 0 failed**, coverage **90.54 %** (≥ 75), 15 m 55 s, exit 0. Compile exit 0 · `ruff check .` clean · `ruff format --check .` 928 files · bare `mypy .` 0 issues / 548 files · bandit 0 High / 0 Medium (46 Low — the documented subprocess set). `build_user_guides.py --check`: 31/31 artefacts current. The staleness lock was proved **able to fail**: appending one paragraph to a source made `test_artefacts_match_their_sources` fail with exit 1, and the restored source is SHA-256-identical to before. |
| P3.1–P3.3 | pending | D1 answered (convert); authorised, not started. |
| P4.1–P4.5 | pending | Phase 1 prerequisite work (the index and generator locks) is in place. |
