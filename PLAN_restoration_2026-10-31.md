# PLAN — Restoration, part two (F-08b de-reverb, F-08c spectral repair)

**Status:** `[~]` **IN PROGRESS** — opened 2026-10-31 to carry the two
sub-items the functional backlog deferred rather than delivered. T-01, L-01,
T-03, T-02, U-02 and U-03 are **COMPLETE (2026-11-01)**; F-08b and F-08c are not
started.

**Base state:** `main` at `d753c6e`, with `v2.3.0` tagged at `2403e2a` and
green on the floor leg (CI run `41213423144`, `41217001751`). `restoration/`
ships declip only (F-08a, decision D37 of the closed plan). The working tree
carries one uncommitted change set — the CI documentation-only skip (that plan's
D41) — which is not part of this plan's scope.

**Governing scope:** two sub-items of F-08, no other capability. (The three
theme defects of §10 are fixes, and the Utilities/REFINE overlap review of §11
is a read-only examination; both are recorded here at the maintainer's direction
and neither adds capability.) F-08 was split three ways when it was admitted
(`PLAN_functional_backlog.md`, D7); **F-08a (declip) shipped in 2.3.0**, and
this plan owns **F-08b (de-reverb)** and **F-08c (spectral repair)**, which were
never started. The closed plan's
D42 names them as carried forward; this file is that successor.

**Why a new plan:** `AGENTS.md`, *Plan Governance* — follow-on work opens its own
plan, and the parent's own D42 says a successor owns this work. Its F-08b and
F-08c are not reopened there.

**Scope addition (2026-10-31, maintainer request):** three queued
**theme-conformance defects** — T-01, T-02, T-03 in §10 — are recorded in this
plan. They are defects, not capability: they add no tool, flag or workflow, so
they take no release slot from F-08b/F-08c (§5) and are **not started**. They
are here because they were found while the plan is the open work item, not
because F-08 covers them (D7). **Work the items easiest to hardest**, in §5's
single order (D9), which the second scope note below extends.

**Scope addition (2026-10-31, maintainer request, second):** **U-01** (§11) was
an **examination** of whether the five DSP cards in the Master Driver's UTILITIES
tab — Pop & Click Remover, Silence Trimmer, Noise Reduction, Audio Enhancer,
Audio Normalizer — still belong now that the REFINE tab offers the same five
stages. It is **COMPLETE** (2026-10-31): the study chose **option B** — retire the
five cards, keep the launchers, CLI commands, packages and guides (D11) — and it
produced two follow-on items: **U-02**, REFINE's Dry Run and no-op contract (an
audio defect found by the study), and **U-03**, the card retirement itself.
**U-02 is COMPLETE (2026-11-01)** — the no-op, Dry Run and single-pass contract
is in and its evidence is in §6, so the card retirement it gated can start;
**U-03 is not started**. Order after U-01: T-01 → L-01 → T-03 → U-02 → U-03 →
T-02 → F-08b → F-08c (D9, D14).

**Scope addition (2026-11-01, maintainer request, third):** one **layout
defect** — **L-01**, §12 — is recorded in this plan. In the Master Driver's
UTILITIES tab a card's Settings open across the window from the left column but
fill only the right half from the right column; it reproduces (274 px at x=274
against 548 px at x=0) and the cause is the card grid's relayout, which gives the
open card a two-column span without starting it on a fresh row. Recorded rather
than fixed now on the same basis as the theme class (D7, D14). It adds no
capability, so it takes the **2.3.1** patch and no new release slot.

**Versioning:** both F-08 items add capability a user can run (a new command and
a new window mode), so each is a **minor** on its own release — 2.4.0 and 2.5.0 —
never ridden together, per the parent plan's one-item-per-release rule (its D9).
U-01 was a study and takes no slot. U-02 is a defect fix and joins the **2.3.1**
patch with the theme items; U-03 is the retirement and is its own **2.6.0**
minor. Neither rides the F-08 releases.

---

## 1. The measurement each sub-item must satisfy

This section comes first, on purpose. The parent plan deferred these two items
for one reason (its D7): declip has an objective target — reconstruct a peak and
measure the distortion floor against a known-clipped reference — while de-reverb
"has no reference metric" and spectral repair "needs an interactive surface".
Half of that is wrong, and the half that is wrong is the expensive half.

**There is a reference.** Reverb is, by construction, a linear convolution: the
wet signal is the dry recording convolved with a room impulse response. So a
test can *build* the wet signal from a recording it also keeps, and then both the
input's reverb and the repair's residual are measurable against the same known
dry truth. The same holds for spectral repair: damage a known-clean file, then
measure how far the repair lands from the original. Both sub-items therefore
ship the declip shape — decode the written file, compare it to a reference,
assert a margin — and no item's acceptance is a listening impression.

### 1.1 The shared reference fixture

One fixture serves both items, declared in `restoration/tests/conftest.py`
alongside the existing `sine`/`thd_db`/`peak`/`channel` helpers:

- **`dry_reference()`** — `tests/data/bpm_corpus/blues_shuffle_152.ogg` (CC0,
  already committed for the BPM corpus, `tests/data/bpm_corpus/ATTRIBUTION.md`)
  decoded mono at 44.1 kHz, first 4 s, peak-normalised to −3 dBFS and exported
  to **FLAC**. Real music matters here: a synthetic tone has no broadband
  content for a spectral method to act on, and a repair that only survives a
  sine has proved nothing. FLAC so the worked file is lossless and the reference
  is the same decoded samples.
- **`synthetic_rir(delay_ms=5.0, t60_s=0.6, drr_db=0.0, seed=…)`** — a direct
  impulse at `delay_ms`, plus a diffuse tail of seeded noise shaped by an
  exponential decay whose Schroeder backward integral is **verified** to be
  `t60_s`, scaled so `10·log10(E_direct / E_tail) = drr_db`. Seeded and
  deterministic, so the fixture is a constant a future edit cannot drift.
- **`wet(dry, rir)`** — `scipy.signal.fftconvolve`, truncated to the dry length.
  The dry reference is one file; the wet input is a second file beside it, so a
  failure names which one it read.

Every metric below is computed on **decoded audio**: the processor's return
values are never the evidence (`AGENTS.md`, *Defects and failing checks*).

### 1.2 F-08b — de-reverb: what must be measured

Two cases, both built from the same dry reference:

| Case | RIR | Meaning |
|---|---|---|
| hard | `drr_db=0.0`, `t60_s=0.6` | direct and reverberant energy equal — a lively room |
| mild | `drr_db=6.0`, `t60_s=0.6` | a room, not a hall: what a home recording sounds like |

Four measurements, all required; the first is the verdict.

1. **ERLE — how much of the added reverb was removed.**
   `ERLE = 10·log10(Σ(wet − dry)² / Σ(out − dry)²)` after aligning `out` to
   `dry` by cross-correlation. The lag is asserted to be zero within the
   declared window, and reported in the failure message if not: a repair that
   delays the audio by a block has not removed reverb, it has shifted it.
2. **Direct-sound preservation.** `|10·log10(Σout² / Σdry²)| ≤ 0.5 dB`. A
   spectral subtraction that removes the room also removes the recording's
   level, and a level change is the cheapest way to fake an ERLE figure.
3. **It moved toward the reference, not merely away from the input.**
   Log-spectral distance `LSD(out, dry)` must be at least **6 dB lower** than
   `LSD(wet, dry)`. This is the clause that stops "output ≠ input" counting as
   success.
4. **A dry file is left byte-identical.** The unprocessed `dry_reference.flac`
   run through a live pass must keep its **SHA-256 and mtime**. A tool that
   cannot find reverberation must not rewrite the file — declip's no-op rule,
   and the one that keeps a false positive from damaging clean audio.

**Pass bars.** Hard case **ERLE ≥ 6 dB**; mild case **ERLE ≥ 3 dB**; (2)-(4) hold
in both. These are the thresholds the shipped tool must clear at default
settings, not a calibration to be lowered afterwards: if the first algorithm
cannot reach 6 dB inside the 0.5 dB level tolerance, that is a **measured
failure** and the item does not ship — the shape A1 took over the album-gain
approximation, not a bar moved to meet the result.

Two further non-negotiables, asserted on the decoded output: length identical to
the input (sample for sample), and `peak(out) ≤ peak(wet) + 0.1 dB` with no
NaN/Inf — a de-reverb may not restore the room by inventing a peak.

### 1.3 F-08c — spectral repair: what must be measured

Two damages, both applied to copies of the same `dry_reference`:

| Case | Damage | What it stands for |
|---|---|---|
| burst | 60 ms of seeded noise inserted at 1.20 s | an edit artifact, a cough, a dropped mic |
| dropout | samples 1.20-1.24 s replaced with zeros | lost content — a glitch, a bad splice |

Three measurements, all on the decoded result, and a fourth on the surface:

1. **Region error reduction.** With `dry` as the reference,
   `20·log10(‖damaged − dry‖ / ‖repaired − dry‖)` over the damaged region:
   **≥ 10 dB** for the burst, **≥ 8 dB** for the dropout. A repair that lands
   closer to the truth by a measurable margin, or it did not repair anything.
2. **Nothing outside the selection moves.** Every sample outside the selected
   region is **bit-identical** (`np.array_equal`, not "close"). This is the
   difference between an interactive repair and a filter with a GUI, and it is
   the guarantee that makes a small repair safe on a long file.
3. **Predictable content is reproduced, not invented.** A selection over a clean
   1 kHz tone (the existing `sine()` helper) must come back within **−40 dB**
   error of the original. Interpolation that can predict a tone must predict it;
   one that returns noise has shown it would invent content in a real dropout.
4. **No selection, no write.** A run with no region is a usage error — click's
   exit 2 with a message on the CLI, a refusal in the window — never a
   whole-file pass. A dry run writes nothing and says which region it would
   have repaired.

### 1.4 What these measurements deliberately do not do

- **No blind DRR or blind T60 estimate is required.** Blind reverberation
  metrics are research-grade and their own error would sit inside the
  acceptance, so the reference-based ERLE answers the question without them.
- **No listening test, and no "sounds better" acceptance.** A DSP change that
  cannot be measured here does not ship on the strength of an impression.
- **No claim about real reverberant music.** The suite owns no wet-music
  corpus, and inventing one is a licensing and curation decision this plan does
  not take (§7). The item ships on the synthetic-RIR evidence above plus the
  dry no-op guarantee, and its guide says exactly that.

---

## 2. How "done" is judged here

The suite's rules apply unchanged; three decide most of the work.

1. **Audio correctness is release-blocking, and its evidence is the audio.**
   Every acceptance in §1 decodes the written file and measures it against a
   reference. A test that reads back a threshold, a status or a returned array
   the code just produced is not evidence.
2. **A repair that cannot improve must not act.** Both items inherit declip's
   rule: the run is counted skipped and the file is left byte-identical. This is
   asserted by hash, not by a counter.
3. **No item is done until its guide describes what it now does.** Both items
   add options and a window mode, so `Restoration_User_Guide.md` and its
   rendered `.docx` move with them (`AGENTS.md`, *User Guides Follow the
   Change*; `python utilities/build_user_guides.py restoration`), and `--check`
   is the mechanical proof.

Neither item is a new tool, so the eleven-step registration checklist does not
apply. What does apply, per item, is the surface it extends: a `click` command
plus the CLI schema corpus re-record (`python -m tests.cli_schema_conformance
--record`), `tests/test_cli_usage_errors.py`'s command table, the Master Driver's
`arg_builder` mode argument if the driver must select the mode, and the tool's
own tests.

---

## 3. Decision log

| D | Decision | Status | Rationale / evidence |
|---|---|---|---|
| D1 | **Both items extend `restoration`; neither becomes a new tool.** | DECIDED | The eleven-step cost buys a registry entry, a card and a window, and neither item needs a different workflow: both are in-place DSP over the shared `run_inplace_dsp_batch`, with tags preserved, an undo snapshot on a live write and the no-op rule free. What they add is a mode, a parameter and (for c) a selection surface. |
| D2 | **The measurement comes first, and the page opens with it (§1).** | DECIDED | The parent plan deferred F-08b on the belief that de-reverb has no reference metric (its D7). It has one: reverb is a convolution, so a synthetic RIR over a known dry file supplies ground truth for both the input and the repair. Deciding that **before** writing DSP is what turns "is de-reverb worth the cost?" from an argument into a threshold — the same inversion A1 made. |
| D3 | **F-08b's first algorithm is WPE (weighted prediction error, delayed linear prediction); spectral subtraction is the fallback, not the default.** | DECIDED | WPE is numpy-only, has no trained model to license or ship, and reduces to one interpretable parameter — the filter's delay and length — whose effect the measurement can show. A spectral-subtraction subtractor needs a reverb-time estimate to work from, and that estimate is exactly the blind metric §1.4 declines to depend on. The choice is provisional in one direction only: it is revisited **if** it fails the §1.2 bars. |
| D4 | **A repair may change only the selection; every other sample stays bit-identical.** | DECIDED | The alternative — filtering the whole file to fix 40 ms — is both unverifiable and dangerous on a long recording, and it would make the window's selection decorative. Asserting sample equality is also what proves the interactive surface is wired to the DSP at all. |
| D5 | **The interactive surface is built inside `restoration`, on `spectral_viewer/core/spectrogram.py`'s STFT path, not by extending Spectral Viewer.** | DECIDED | The viewer's job is inspection; a repair surface owns a selection, a run lifecycle and an undo. Sharing the STFT/render helper keeps one implementation of the picture, and the tools stay separate in the registry. Reuse is at module level, not tool level. |
| D6 | **Each item ships as its own minor: F-08b 2.4.0, F-08c 2.5.0.** | DECIDED | The parent plan's D9: items do not ride each other's release. F-08b is a CLI-first DSP item whose whole deliverable is a measured threshold; F-08c is an XL window item. Bundling them would make one release note cover a subtraction and a new interactive surface. |
| D7 | **Three theme-conformance defects (T-01 … T-03, §10) are queued here at the maintainer's direction rather than fixed on discovery.** | RECORDED (user, 2026-10-31) | *Defects and failing checks* in `AGENTS.md` says a defect found during any session is fixed in the change that found it. The maintainer directed the opposite for this class — record only, resolve later — because the class is one sweep plus a mechanical lock (T-02) rather than two local keyword additions, and a half-fixed surface is worse than a recorded one. T-01 and T-03 are the two sightings; T-02 is the sweep. They add no capability, so they take a **patch** (first available cut: 2.3.1) and consume neither 2.4.0 nor 2.5.0. |
| D8 | **T-01's fix keeps both cards' hand-built bodies and adds the missing colour keywords, rather than moving them onto the declarative row builder.** | DECIDED (2026-11-01) | `_card_base.CardCheckEntryRow` already renders the Parallel Processing / Workers row with the full colour set (`bg`, `fg`, `selectcolor`, `activebackground`), so `bpm_card.py` and `lyrics_manager_card.py` are the only copies that get it wrong — and the only two cards of this shape that never adopted `build_simple_card`. Moving them removes the class rather than one instance; setting the missing keywords is the smaller diff. Either route is acceptable, neither may move the layout, and the choice is settled before T-01 starts. **Settled as the keyword route (2026-11-01)**: four widgets gain the missing keywords, and no pack order, label width or widget set moves — the risk clause's own requirement — while the class-wide lock stays T-02's, fed by this item's contrast helper. |
| D9 | **Work the seven remaining items easiest to hardest, and keep that order separate from the release map.** | RECORDED (user, 2026-10-31) | §5 is the order: T-01 → T-03 → U-02 → U-03 → T-02 → F-08b → F-08c; U-01 (the study) completed on 2026-10-31 and holds no position. Difficulty is the sort key (four missing keyword sets, then one shared widget, then a contract fix inside one pipeline, then the card retirement's file deletions, then a mechanical sweep, then a measured DSP pipeline, then an interactive repair surface), and it satisfies every dependency the plan has: U-02 precedes U-03 because the cards' replacement must leave a clean file untouched first, U-03 precedes T-02 so the sweep does not colour five card files the retirement deletes, and F-08c needs F-08b's measured pipeline. Release slots do not follow the work order: the theme items and U-02 are the 2.3.1 patch, F-08b is 2.4.0, F-08c is 2.5.0, U-03 is 2.6.0 (D6, D7, D11). |
| D10 | **U-01 (§11) is an examination recorded at the maintainer's direction; the removal decision was deferred to it.** | RECORDED (user, 2026-10-31) | The premise holds at the entry-point level: the five tools are `category="utility"` manifests, each with a card, a `.pyw`, a CLI command, an arg-builder entry, a graph entry, an AppState key, its own tests and its own guide, while the REFINE tab embeds the same panels (`audio_refinery/ui/setup_tab.py:30-34`) and runs a stage only when its checkbox is set (`audio_refinery/core/pipeline.py:199-229`). "Remove the tools" is therefore not an option: the packages are the refinery's libraries (`audio_refinery/core/models.py:24` imports the noise-reduction params), so the question is which **entry points** stay. Deferred to a study because the two surfaces already differ in ways a card deletion would silently remove — the normalizer's true-peak/LRA controls, the driver's output-folder requirement for the enhancer, and the in-place no-op rule — and a decision made from the reported redundancy alone would be made blind. Adds no capability, so it takes no release slot. The study ran the same day; D11 records its outcome. |
| D11 | **U-01's outcome: option B — retire the five DSP cards from the UTILITIES tab, keeping every launcher, CLI command, package and guide.** | DECIDED (study, 2026-10-31) | The duplication is at the entry points, not the DSP: REFINE already imports four tools' panels and shares the noise-reduction parameters, so the packages are the refinery's libraries and **option C cannot delete them either** — its only extra removal is five documented CLI commands, five `.pyw` launchers and five guide pages (with their generated rows), a compatibility and documentation cost with no further deduplication. **Option A** was rejected on the study's own evidence: the two surfaces already drift (REFINE has no TP/LRA/lossless normalisation and defaults to -16 LUFS against the tool's -14; a normalise-only run encodes twice; the tools' CLI defaults differ from their GUIs), so "keep both" preserves two paths that disagree. B is the smallest change that answers the report and the largest that is still reversible. It is conditional: **U-02 first**, because REFINE is what the tab falls back to and today it rewrites a file that needed nothing and its Dry Run detects nothing; then **U-03** removes the cards. The standalone windows and the five commands remain, so the normalizer's TP/LRA/lossless controls are still reachable — the guide must say where (§11, U-03). |
| D12 | **The release-note lock re-baselined to the post-2.3.0 window: `BASE_COMMIT = d753c6e`, `NOTE_MARKER = "Changed in 2.3.1"`.** | RECORDED (gate, 2026-11-01) | `tests/test_release_notes.py` requires every code file changed since the plan's base commit to carry the current window's marker, and its window ended at the 2.3.0 cut. U-02's own files therefore failed the suite as unannotated work (one of the three failures in the first full-suite run), and annotating them under the released version would file them under a release they are not in. The base is now the last commit of the 2.3.0 window — the release record `utilities/release.py` wrote for short v2.3.0 — so the retry is the work that actually lands after it. The 2.3.0 window's own notes stay as each file's history. |
| D13 | **A guide's generation month is not drift: the freshness check masks it, and the artefact is not re-rendered to chase it.** | DECIDED (gate, 2026-11-01) | `version: auto` renders `Version <declared> — <Month YYYY>` from `date.today()`, so the month is ambient — it comes from the clock, not from the Markdown source — while `build_user_guides.check_guide()` compared `word/document.xml` verbatim. On 2026-11-01 that turned seven guides with unmodified sources red in both `--check` and `test_user_guide_hygiene.py`, and re-rendering them would only move the bomb to December. `stable_document_xml()` masks the month on both sides and keeps the version number, so a body-text edit, a newly added section or a version bump still fails; `test_a_month_boundary_is_not_guide_drift` renders under a future month and asserts the current artefact passes, with an edited copy as the counter-case. Measured with the mask removed in memory: 7 stale, and 0 with it. Pre-existing defect, found by the gate — no committed artefact changed. |
| D15 | **The recorded CLI usage-error wording follows the installed click, and is corrected in place rather than regenerated wholesale.** | DECIDED (2026-11-01) | `tests/test_cli_json_schema.py::TestFatalErrorExamples` compares a real failing run against the published example, and the committed corpus carried click 8.5's `No such option '--no-such-option'.` while the suite now installs click 8.3.2, which emits `No such option: --no-such-option` — so the `doctor` case was red at HEAD, reproduced in isolation. `python -m tests.cli_schema_conformance --record` (the artefact's own instruction) was run first and rewrites every payload: ~35 `duration_secs` lines, `_generated`, and doctor's `editable: true -> false` with `interpreter` becoming `<python>`, which is this host's install state rather than the `--json` contract. Only three message strings differ for the reason at hand, so those three are what landed, in both artefacts, as byte-preserving single-line edits with the incidental churn restored. This is the same call `PLAN_feature_expansion.md` D10 made for these files in the opposite direction, and the reason it recurs is that `click>=8.0.0` is floating: the example tracks whichever click is installed. |
| D16 | **The fatal-error lock compares the document without Click's reason text, so a Click reword is a recording refresh rather than a red suite.** | DECIDED (2026-11-01) | D15 corrected the corpus to the installed click 8.3.2, but the comparison itself — `json.loads(stdout) == published` — still made Click's prose part of the contract, which is why this lock went red in *both* directions as the floating `click>=8.0.0` moved (`PLAN_feature_expansion.md` D10: 8.3 → 8.5; D15: 8.5 → 8.3). A fatal document's `error` is `ClickException.format_message()` (`audio_suite_shared/cli_base.py`), i.e. entirely Click's sentence for a parse error, so pinning it pinned a dependency version at a consumer boundary — the trap `AGENTS.md`'s *Defects and failing checks* names. `tests/test_cli_json_schema.py` now compares every field except `error` (`_without_reason`) and separately asserts the reason is present, non-empty and names the value the run rejected (`argv[0]`, i.e. `no-such-input` or `--no-such-option`) — the subject, which is why the example exists. Two guards stop the exclusion from widening or weakening: `test_the_comparison_ignores_only_the_reason` asserts no second field is dropped and that a drifted `processed` still fails the comparison, and `test_a_reworded_reason_leaves_the_lock_green` patches `NoSuchOption.format_message` to a wording no release prints and asserts the comparison still holds. With the exclusion removed both fail (2 failed, exit 1), so neither passes vacuously; restored under a SHA-256 check, the two CLI contract modules report 164 passed. Nothing is pinned by the coverage: a new Click that rephrases a usage error only makes the committed message old, which `tests/cli_payloads.record_error_payloads`' docstring says is documentation upkeep. |
| D14 | **A reported UTIL-tab card-grid symptom joins the plan as **L-01** (§12), second in the work order, and is recorded rather than fixed on discovery.** | RECORDED (user, 2026-11-01) | The report — a right-column card's Settings open across the right half only, while a left-column card opens across the window — reproduces, and the cause is the layout, not any card: `_relayout` gives the open cell `columnspan=2` but never starts it on a fresh row, so a card already at column 1 is gridded into an implicit third column the two-column host does not size (measured on a real 1200×800 root: **274 px at x=274**, against **548 px at x=0** for the left column). It is not a theme-conformance defect, so it takes its own prefix and §12 rather than joining T-01…T-03. Recorded at the maintainer's direction as D7 was — U-02 had to close first — and it earns the second slot because it is one function plus a test, the smallest fix the plan holds. A fix, so it takes the 2.3.1 patch and no new release slot; the one sequence it adds is that it lands before T-02's grid-walking runtime test. |
| D17 | **U-03 is one manifest field, `driver_card`, and the driver's launch gate moved to the driver population with it.** | DECIDED (2026-11-01) | D11 retires the five **cards**, and `is_driver_tool` was `bool(pyw_filename)` — literally "has a launcher" — which is the one property the five must keep, so a tool cannot express "launcher yes, card no" through it. A boolean field that defaults to `True` states that narrowly, needs no rename, and leaves every other manifest (plugin manifests included) unchanged. Everything the driver does with the population then follows from it: `driver_manifests` and `driver_by_category` drop the five, so the tab renders fifteen cards, the generated toggles and `build_utility_args` never see them, and the README's card lock learns the same rule. **The flag exposed a live defect in the launch gate**: `launch_utility` classified against `by_category("utility")` and indexed `state.module_toggles[m.id]` for every utility manifest, so a tool without a toggle raised `KeyError: 'noise_reduction'` on the first utility launch — reproduced by `test_tag_field_updater_alone_launches` at HEAD — and it now reads `driver_by_category`, the population the tab offers. Per *Defects and failing checks* it is fixed here rather than recorded. Three production comments and the "Settings Required" dialog also named the Audio Enhancer as the required-output example; the Stem Separator is now the only one, so they name it. |
| D18 | **T-02's lock is a static walk plus a runtime build, and the sweep writes explicit keywords because bare mypy rejects a `**dict` spread into a tk widget.** | DECIDED (2026-11-01) | The two halves answer different questions and neither covers the other: the AST walk reaches widgets no test builds (a dialog opened on demand, a tab no test constructs) and cannot see a keyword whose *value* is wrong for the theme, while the runtime build measures what the user sees and cannot see a widget behind a dialog. Both were red before the sweep — 17 violations, and ratios of 2.04:1, 2.50:1, 3.19:1 and 3.54:1 — and both are green after it, so neither passes vacuously. **`text_colors()` is the contract, not a spread**: `tk.Checkbutton(parent, **styles.text_colors("toggle"))` fails bare `mypy` with eleven `arg-type` errors, because typeshed types every tk option individually (`Literal[...]`, `Variable`, `int`) and a `dict[str, str]` matches none of them; the plan's "factor the triple into one helper" therefore became a tested, documented helper plus explicit keyword lines at the call sites, rather than a cast or a `# type: ignore` at 48 sites. **Scope held at what the plan enumerated plus what the same walk found**: the 31 `activeforeground` holes are the hover half of the reported defect (the pointer repaints the label over the themed card), so they are swept; a *Button*'s active colours are the same shape of omission but are not in the plan's set, so they are recorded in §7 rather than swept in this item. The three pre-existing contrast defects the runtime half surfaced (the ⚙ SET grey, `AMBER`, the settings footer note) are fixed here under *Defects and failing checks*. |
| D19 | **The 17 red locks the five-tool retirement left behind are one defect - the tools outlived their code in the docs - and they are reconciled against the manifest in one pass.** | DONE (2026-11-01) | The manifest registers 27 first-party tools, all with live commands except `undo_tag_edits`, so the retired five exist nowhere in code; their documentation did, in four places: `CLI_Commands_Reference.md` (five sections, five *All Commands* rows, and the sentence promising that `declick`, `silence-trim`, `reduce`, `enhance` and `normalise` "run exactly the same processors"), the new-user deck (two slides, five format rows, three chooser rows, four pipeline labels), README/docs counts (32 -> 27, UTIL 20 -> 15) and `AGENTS.md`'s completion-seam citation of a test file that removal deleted. **The `FileNotFoundError` cluster was a working-tree artefact, not a code defect**: the guide-hygiene, guide-claims and tool-coverage locks walk `git ls-files`, so 71 files deleted in the tree but still tracked read as guides nobody could open; `git add -u` on the deletion set was the root fix and weakened no assertion. **Removing the dead sections unmasked two real reference errors the old `problems` short-circuit had hidden**: `refine`'s `--target-lufs` was documented as `-16.0` against click's `-14.0`, and `--true-peak`, `--lra` and `--normalise-mode` - the Audio Normalizer's controls REFINE absorbed - were documented nowhere; all four are fixed, and the master driver and refinery guides no longer promise standalone windows that were retired. **The lock's vacuity floors moved to their measured values** (33 documented commands, 31 sections, 29 families, 26 manifest commands, 103 default claims, 159 options) rather than being left to fail on a surface that no longer ships; they still fail on a parser break or a gutted document, and the deck and three guides were regenerated rather than hand-edited. **Verified:** the full suite passes 11,129 tests (3 skipped, 35 deselected, coverage 91.18%), bare `mypy .` is clean across 553 files, ruff check and format are clean, bandit reports 0 High / 0 Medium, and `build_user_guides.py --check` reports 29/29 artefacts current. |
| D20 | **The POSIX leg's 1756-test floor was a pre-retirement measurement; the 2.3.1 cut legitimately shrank the selection to 1740, so the lock follows the leg's own numbers down and the movement is named.** | DONE (2026-11-02) | The pushed cut's first `posix-smoke` run collected 1741 and reported **1740 passed, 1 skipped, 0 failed** - nothing failed; the step refused the run at its floor, which is the lock working. The 37-module selection is unchanged and every module still exists, so the loss is inside the CLI-surface parametrisations that generated a case per subcommand: a `--co` diff between `b22abaa` (pre-retirement) and the cut puts all of it in `test_cli_app.py`, `test_cli_usage_errors.py`, `test_completion_payload_published.py`, `test_constants.py` and `test_cli_json_schema.py` (-22/-22/-9/-3/-3 on Windows; the leg's 16 is the same five modules, where platform-conditional cases differ), and no other module moved. Lowering to the runner's own measurement is the D21 rule rather than a widening: the skip count is unmoved at 1 (`tag_editor/tests/test_csv_io.py`'s Windows drive-relative case), the floor still fails on a parser break or a gutted selection, and `tests/test_ci_posix_leg.py` asserts the comparison operator alongside the value so a silent edit is red. |

---

## 4. Items

### F-08b — de-reverb (L)

**Status:** `[ ]` not started. Work order **7 of 8** (§5). Awaits the §1.2
fixture before any DSP is written.

*Current state.* `restoration/` ships declip only: `core/declipper.py` (peak
reconstruction), `core/file_processor.py` (the shared in-place batch),
`ui/app.py` on `NoisePopToolApp`, and one `click` command. Nothing in the suite
touches reverberation — `noise_reduction` removes steady noise and
`pop_click_remover` removes transients; neither estimates a room.

*Change.* Add `restoration/core/dereverb.py` with the WPE path: frame the signal
(64 ms frames, 16 ms hop, Hann), predict each frame from its *delayed* past
frames per frequency bin, subtract the prediction, overlap-add. Defaults exposed
as `--strength` (0.0-1.0, default 1.0) and `--tail-ms` (the prediction delay,
default 60 ms), plus a gate: if the estimated reverberant-to-direct energy ratio
in the file is below `MIN_REVERB_DB` the file is **skipped byte-identical**. The
batch plugs into `run_inplace_dsp_batch` through the same adapter shape declip
uses, and a new `dereverb` command joins `restoration/cli.py` with `--json`
carrying the per-file ERLE estimate it measured on the processed signal.

*Acceptance.* §1.2 in full, with the hard case's ERLE ≥ 6 dB, the mild case's
≥ 3 dB, the level/LSD bars, the dry file's SHA-256 and mtime unchanged, the
length and peak guards, and the per-channel bar: ERLE holds on **each** channel
and the inter-channel level difference moves by ≤ 0.2 dB — a repair that
collapses a stereo image is damage, not restoration. Every measurement is taken
on the decoded output against `dry_reference.flac`.

*Files:* `restoration/core/dereverb.py` (new), `restoration/core/file_processor.py`,
`restoration/cli.py`, `restoration/utils/cli_args.py`,
`master_driver/runner/arg_builder.py` (the mode argument, if the driver must
choose it), `restoration/tests/conftest.py` (the RIR and metric helpers),
`restoration/tests/test_dereverb.py` (new), `tests/data/cli_payloads.json` +
`audio_suite_shared/cli_schema.json` (re-recorded), the user guide and its
`.docx`.

*Risk.* This is the item that can make audio **worse** while looking successful:
a mis-estimated prediction removes the attack of every note and sounds like a
dull smear, which no level metric catches. That is why the direct-sound bar
(±0.5 dB) and the LSD clause sit beside the ERLE, and why the dry no-op is a
hash assertion rather than a counter.

### F-08c — spectral repair (XL)

**Status:** `[ ]` not started. Work order **8 of 8** (§5). Awaits F-08b's
measured pipeline (D6) and the selection contract in D4.

*Current state.* No tool can repair a time-frequency region. `spectral_viewer`
renders a spectrogram and lets the user *look*; nothing writes. The window
conventions a repair surface needs exist — `NoisePopToolApp`, `build_processing_tab`
and `build_results_tab` supply the tabs, the progress bar and the report
surface, and the GUI callback contract fixes how a run reports.

*Change.* A **selection mode** in the Restoration window: the spectrogram is
drawn from `spectral_viewer.core.spectrogram`'s STFT path on a matplotlib
canvas, a drag selects a time/frequency rectangle (with a keyboard-adjustable
numeric readout, so the region is not mouse-only), and *Repair Selection* runs
the DSP through a `run_*` entry point taking `on_progress`/`on_complete`/
`on_error`. The DSP models the region as sinusoidal partials plus noise
estimated from the frames either side of it, then reconstructs from the
prediction with a cross-fade at the edges; headless form is
`spectral-repair --start --end --lo-hz --hi-hz` on the same command family.

Two implementation rules are inherited, not optional: the worker hands its
result over a **`queue.SimpleQueue`** that a poller started by the Tk thread
collects, and the worker never calls `root.after` (`AGENTS.md`, *GUI Callback
Contract* — the `plugins/example_plugin/window.py` hang); and the batch writes
through the shared in-place workflow, so a live write records an undo snapshot
and a file with nothing to repair is skipped.

*Acceptance.* §1.3 in full: ≥ 10 dB region error reduction for the burst, ≥ 8 dB
for the dropout, sample-identical content outside the selection, the −40 dB
predictable-tone case, and "no selection, no write" as a usage error. Plus the
window's own: the selection survives a scroll/zoom without moving its
time/frequency bounds, a dry run writes nothing and reports the region, and the
completion report names the region and the measured error reduction. The suite's
existing locks apply: the tool's handlers are registered in
`tests/test_callback_payload_contract.py`'s seams and a real `run_*` into the
bound handler is asserted (`test_completion_seam.py`'s pattern).

*Files:* `restoration/core/spectral_repair.py` (new),
`restoration/core/file_processor.py`, `restoration/ui/app.py` +
`restoration/ui/selection_tab.py` (new), `restoration/cli.py`,
`restoration/utils/cli_args.py`, `master_driver/runner/arg_builder.py`,
`restoration/tests/test_spectral_repair.py` (new), the CLI schema corpus, the
user guide and its `.docx`.

*Risk.* The GUI is the risk, not the DSP: a selection surface invites
widget work from the worker thread, and a run that marshals from the worker
freezes the window waiting for a result that never arrives — the defect that
sank the plugin window's first version. The selection also has a habit of
drifting from the region the DSP is given (pixels to seconds/Hz is a
conversion); the lock is a numeric readout that is the *same value* the DSP
receives, asserted by a test that drives the real entry point with a selection
set by the canvas.

---

## 5. Work order and release map

**Work the items easiest to hardest** (D9). The eight items of §4, §10, §11 and
§12 in that order, with the size each carries, what the work actually is, and
the release it ships in. U-01, the study, T-01, L-01, T-03, T-02, U-02 and U-03 are complete; the
positions below are the order, and completing an item does not renumber the rest. L-01 was
added on 2026-11-01 from a reported symptom and takes the second slot (D14):

| # | Item | Size | The work | Release | Why here |
|---|---|---|---|---|---|
| **1** | T-01 — card text ignores the theme (§10) | **S** | four checkbuttons in two card files, plus its contrast test | **2.3.1** patch | The smallest real fix in the plan: a missing keyword set on four widgets whose failure is already measured (1.26:1). First because it clears the reported symptom fastest, and because the contrast helper it writes is the one T-02 generalises. |
| **2** | L-01 — an expanded right-column card keeps the right half (§12) | **S** | one wrap in the card grid's relayout, plus the test that opens a right-column card | **2.3.1** patch | As small as T-01 and the same shape of bug: one function, no new widget, and the left column already shows the intended behaviour. Second because it is the same patch surface as T-01 and neither blocks the other — but it must land before **T-02**, whose runtime test walks the card grids. |
| **3** | T-03 — locked Source Music Directory value (§10) | **S/M** | one shared widget, one new `styles` value, and the ttk map | **2.3.1** patch | One file, but the whole locked strip (six widgets, one of them accent-coloured) and a value the sweep then reuses; no dependency on T-01. Third because it is the other theme sighting, and T-01/T-03 together are the patch. |
| **4** | U-02 — REFINE's Dry Run and no-op contract (§11) | **M** | one pipeline's modification flags, a real Dry Run and a single-pass normalise | **2.3.1** patch | **COMPLETE 2026-11-01** (§6). The defect U-01 found, and the gate on U-03: the cards are being replaced by REFINE, so REFINE had to stop rewriting a file that needed nothing before the shortcut goes. |
| **5** | U-03 — retire the five Utilities cards (§11) | **M** | one manifest flag plus the deletion of five cards, their arg-builder and graph entries, state keys and card tests | **2.6.0** minor | **COMPLETE 2026-11-01** (§6). Mechanical but wide: the five ids were pinned in six test modules, and the guide describes the tab. Before T-02 because it deletes five of the files the sweep would otherwise colour. |
| **6** | T-02 — theme-conformance sweep and lock (§10) | **M** | 7 files of keyword additions, a `styles` helper, an AST lock and a four-state runtime test | **2.3.1** patch | **COMPLETE 2026-11-01** (§6). Wide but shallow: nothing here is hard to write, there is just a lot of it, and every edit is invisible to compile/ruff/mypy — the cost is review. After T-01/T-03 so the sweep fixes what is left rather than redoing them, after U-03 so it does not colour five card files the retirement deletes, and so its lock asserts an existing fix. |
| **7** | F-08b — de-reverb (§4) | **L** | new DSP module, CLI mode and gate, the §1.2 reference fixture | **2.4.0** minor | The largest item whose deliverable is a number: a predictor, a reference fixture, four measurements and a no-op hash. It also produces the fixture and metric helpers F-08c reuses, so it cannot move behind F-08c. |
| **8** | F-08c — spectral repair (§4) | **XL** | DSP plus a selection surface, a window run lifecycle and the region contract | **2.5.0** minor | Hardest by a margin: the only item that builds an interactive surface, a worker hand-off over `queue.SimpleQueue`, and a pixels-to-seconds/Hz conversion that must not drift. Last by difficulty *and* by dependency — it needs F-08b's pipeline and D4's selection contract. |

**Difficulty is the sort key; five sequences are hard.** T-02 comes after T-01
because its repo-wide lock generalises T-01's contrast helper, and F-08c comes
after F-08b because it needs the measured pipeline and the selection contract.
U-01's outcome added two more: U-02 comes before U-03 because the retirement's
replacement must leave a clean file untouched before the card shortcut is
removed, and U-03 comes before T-02 because it deletes five of the card files
the sweep would otherwise colour (D11). L-01 comes before T-02 as well, though
for a weaker reason: T-02's four-state runtime test walks the card grids, and a
layout it has to work around is a worse place to write it than a layout that is
right (D14). Every other neighbour could be swapped
if an item stalls: an individual theme item may be cut as 2.3.1 alone rather
than waiting for its siblings, and F-08b may start before the theme pass
finishes — it touches none of the same files.

**The release slots do not follow the work order.** The three theme items and
U-02 make up the **2.3.1** patch (§10, §11) — all four are fixes, and a patch
groups fixes; F-08b is **2.4.0**, F-08c **2.5.0** (D6), and U-03 is **2.6.0**.
The one-item-per-release rule governs features, and none of these is one.
Neither F-08 item is a patch: both add capability a user runs, and both change
what a re-run does to an already-processed file, which the release note must say
(`PLAN_functional_backlog.md`, D11's rule about re-run semantics).

---

## 6. Verification record

U-01, U-02, T-01, L-01, T-03, T-02 and U-03 are the completed items. U-01's
evidence is
the parity table in §11.1, and it needed no audio measurement because it changed
nothing; the others' is the entry below. Every remaining item's
entry is written at implementation, in the shape the closed plan used: the fixture's measured RIR
(its actual T60 and DRR as verified by the helper, not as requested), the ERLE
or region-error figures on both cases, the no-op hashes, the decoded-output
evidence, the gate (compile, ruff, bare mypy, bandit 0 High/0 Medium, bare
pytest with its counts and coverage), and the guide outcome including "no guide
describes this behaviour" when that is the answer.

**F-08b —** to be recorded.
**F-08c —** to be recorded.**U-01 — COMPLETE 2026-10-31.** The parity table (§11.1) was built by reading
both surfaces for each of the five tools; every row names the code it compared.
The chosen option is **B** (D11). No code changed and nothing was measured
beyond the table; its follow-ons are U-02 and U-03.
**U-02 — COMPLETE 2026-11-01.** The no-op verdict is asserted on the file, never
on the pipeline's own flag. For each pre-write stage (declick, trim,
reduce_noise) a clean file keeps its **SHA-256, `st_mtime_ns` and size**, the
staging encode (`_write_output`) and the undo snapshot are never called, and the
result is SKIPPED — and the damaged counterpart of the same stage in the same
parametrised test still writes exactly once and changes the hash, so a stuck
"nothing happened" verdict cannot pass. A normalise run already inside tolerance
is untouched the same way. A normalise run outside it is **one** FFmpeg pass:
`_write_output` is never called and loudnorm `apply` is called once with the
**source** path, asserted beside the decoded outcome — a quiet FLAC normalised
this way decodes at **-16.0 LUFS ±1.0**, its duration is within 50 ms of the
original and its title tag survives. A multi-stage run keeps the write-then-
normalise pair, and the loudnorm pass targets the staged copy, not the source.
The Dry Run fingerprints the whole directory before and after four enabled
stages and finds it unchanged: no output, no tag write, no snapshot, no leftover
temp file — while its per-stage lines report what each stage found (3 clicks
repaired, "No silence detected", "Would adjust loudness from -23.0 to -16.0
LUFS"). The registry records only a real write: a Dry Run result and a SKIPPED
no-op both leave `_refinery_completed.log` absent, and a DONE-with-
`was_modified` result **is** recorded (the counter-case that stops the check
being stuck at "never done"). Gate: `compileall` clean; `ruff check .` and
`ruff format --check .` (1011 files); bare `mypy .` 592 files, no issues; bandit
**0 High / 0 Medium**; bare `pytest` **11,876 passed, 3 skipped, 35 deselected,
exit 0, 19 m 05 s** (`audio_refinery/tests` alone: 398 passed, 15 of them the
new `test_pipeline_noop.py`). Two locks this work needed are D12 (release-note
window re-baselined to 2.3.1) and D13 (the guide freshness check no longer treats
a generation month as drift). Guides: `Audio_Refinery_User_Guide.md`'s Dry Run,
stage-order, output-safety and completion-registry sections were rewritten and
the `.docx` re-rendered — `build_user_guides.py --check` reports **34 of 34
artefacts current**, and `tests/test_guide_claims.py` is green. `CHANGELOG.md`
carries the user-facing line under `[Unreleased]`; the renderer repair is in
`TECHNICAL_CHANGELOG.md`, where a user cannot observe it.
**U-03 — COMPLETE 2026-11-01.** The UTILITIES tab renders **15** cards, not 20:
`ToolManifest.driver_card` (default `True`) is `False` on `pop_click_remover`,
`silence_trimmer`, `noise_reduction`, `audio_enhancer` and `audio_normalizer`, and
`is_driver_tool` now requires it, so `driver_manifests`, `driver_by_category`,
the generated toggles and `build_utility_args` all drop them (D17). Deleted with
the cards: the five `master_driver/ui/cards/*_card.py` modules (1151 lines), the
five arg-builder entries and their three `_build_*` helpers, the enhancer's
display-flag exception, the five `DEPENDENCY_GRAPH` nodes, and the nineteen
AppState option variables those cards owned (`nr_*` 8, `trimmer_*` 4,
`normalizer_*` 3, `declick_*` 2, `enhancer_*` 2, counted from the diff).

The five tools still ship on every other surface: `registry.all` and
`first_party` still hold all 32 manifests, `audiosuite --help` still lists
`declick`, `silence-trim`, `reduce`, `enhance` and `normalise`, and all five
`.pyw` launchers are untouched. `tests/test_readme.py` gained the lock that keeps
that honest — it exempts them from its card assertion and then asserts the
launcher and CLI command exist and the card module really is gone.

**One defect found and fixed in the same change** (D17): `launch_utility`
classified against `by_category("utility")` and indexed
`state.module_toggles[m.id]` for every manifest, so the first utility launch
raised `KeyError: 'noise_reduction'` — reproduced by
`test_tag_field_updater_alone_launches` before the fix. It reads
`driver_by_category` now. Three production comments and the "Settings Required"
dialog named the Audio Enhancer as the required-output example; the Stem
Separator is the only one left, so they name it.

*Tests, in lockstep.* `audio_suite_shared/tests/test_tool_plugin.py` gains
`TestRetiredDriverCards` (six tests): the five are absent from the driver
populations while present in the registry, the tab keeps exactly the other
fifteen (20 − 5, asserted as a set difference), each keeps its launcher and
command, the five card modules no longer import, **no production file under
`master_driver/` names a retired id** (word-boundary regex, so REFINE's own
`noise_reduction_params` is not a false hit, and the file set is asserted
non-empty so an empty walk fails), and `driver_card` defaults to `True`.
`test_app_state` drops the retired keys and option defaults, `test_runner` drops
the five tools' argument-shape tests, `test_ui_cards` drops the five card test
classes, and `test_utilities_window`, `test_app`, `test_tool_launcher` and
`test_batch_orchestrator` now count the driver population rather than the whole
registry.

*Gate.* `compileall` exit 0, no compile errors; `ruff check .` and
`ruff format --check .` (1006 files) clean; bare `mypy .` 587 files, no issues;
bandit **0 High / 0 Medium** (43 Low, the documented call sites); bare `pytest`
**11,830 passed, 3 skipped, 35 deselected, 1 failed** in 18 m 15 s — and that one
failure is the harness reading its own output:
`tests/test_release_notes.py::TestPerFileChangeNote` scans every changed code
path, including untracked ones, and the run's capture file (`_u03_gate.txt`,
pytest's own progress output in cp1252) failed its UTF-8 read. With the capture
written outside the tree that lock, `tests/test_readme.py` and the seven
driver modules it guards report **239 passed**; no source file differs between
the two runs. A clean capture would have run bare `pytest` to exit 0.

*Records and docs.* Guides: `Master_Driver_User_Guide.md`'s UTIL section now
says where the five went (REFINE's five stages; the standalone window and the
five commands for the options a stage does not carry, naming the normalizer's
true-peak, LRA and lossless controls) and its tool list no longer offers them as
cards; `.docx` re-rendered, `build_user_guides.py --check` reports **34 of 34
artefacts current**. No tool guide claims a Master Driver card, so nothing else
was touched. `CHANGELOG.md` carries the 2.6.0 bullet under `[Unreleased]` and
`TECHNICAL_CHANGELOG.md` the manifest flag, the launch-gate defect and the
population changes.

**T-02 — COMPLETE 2026-11-01.** The sweep is **48 widget constructors in 27
files**, found by running the plan's own AST walk against HEAD *after* U-03 —
which is why the count is not the 11-in-7-files tabled above: U-03 deleted five
card files and T-01 had already fixed four of the eleven. **17** were the
enumerated class: ten constructed `state="disabled"` with no
`disabledforeground` (the action buttons and library_stats' three export buttons
among them, each painting Tk's `SystemDisabledText`), five checkbuttons with a
themed `bg` and no `selectcolor` (the indicator kept the symbolic `SystemWindow`
in both themes), and two text labels (`cd_ripper`'s "Rip Complete!" and its
CD-insert info box, whose hardcoded `#e8f4f8` panel became `BG_HEADER`). The
walk's second pass found **31** themed toggles with no `activeforeground`: the
hover half of the same defect, because Tk paints the label in
`SystemButtonText` whenever the pointer is over it.

Both halves of the lock were written first and both were red against the
pre-sweep tree. `TestWidgetColourKeywords` listed all 17 with file and line; it
also parses a deliberately broken snippet and asserts five violations, asserts
the scanned-file set and the inspected-constructor count are non-empty, and
names the modules the sweep owns, so an exclusion set that swallowed them fails
instead of passing. `TestBuiltSurfacesFollowTheTheme` builds the real
`AudioSuiteDriver` window and the shared `BaseSetupFrame` (what 18 of 19 tools
embed) in Light, Dark, `System`→Light and `System`→Dark, reading every widget's
effective pair back through `winfo_rgb()`. That half found three further
pre-existing defects, all fixed here: `SETTINGS_TAB_INACTIVE` `#888888` under
the ⚙ SET button's white text (**3.54:1**), `styles.AMBER` `#d97706` on the
light card (**3.19:1**), and `settings_tab`'s hardcoded `#999999` footer note
(**2.50:1**). AMBER is now theme-refreshed (`#9a4a08` light, `#d97706` dark)
like the other foregrounds, the inactive grey is `#666666` (**5.74:1** with
white) and the note takes `FG_SUB`.

`styles.text_colors(kind, background=...)` is the contract — one call per widget
family (`label`, `toggle`, `field`, `accent`) returning only the keys that
family accepts — and the lock asserts every family's key set, so a dropped key
fails rather than silently narrowing. Production call sites write the keywords
out: `tk.Checkbutton(parent, **text_colors(...))` fails bare `mypy` with eleven
`arg-type` errors, because typeshed types every tk option individually and a
`dict[str, str]` then matches none of them (D18).

*Gate.* `compileall` exit 0; `ruff check .` clean and `ruff format --check .`
956 files; bare `mypy .` **553 files, no issues**; bandit **0 High / 0 Medium**
(43 Low, the documented call sites); `tests/test_theme_contrast.py` **13
passed**; the UI/contract set (cards, driver app, utilities window, styles, the
locked strip, cd_ripper, library_stats, three Setup tabs and the release-note
lock) **1,166 passed, 30 deselected**. Bare `pytest` **11,111 passed, 3
skipped, 35 deselected, 18 failed** in 14 m 12 s (coverage **91.18%**). Every
one of those failures is pre-existing fallout from the earlier removal of the
five standalone windows, their commands and their guides, not from this item:
11 in `tests/test_cli_reference_hygiene.py` (the CLI reference still documents
`normalise`, `declick`, `enhance`, `reduce` and `silence-trim` with their
options), 3 in `tests/test_suite_docs_tool_coverage.py` (the README's and the
deck's tool counts), 1 in `tests/test_guide_claims.py` (a stale exemption,
removed with this item and re-verified green), 1 in
`tests/test_user_guide_hygiene.py` (a guide `.docx` that is deleted in the
working tree but still tracked) and 1 in `tests/test_agents_md.py` (a citation
of `audio_enhancer/tests/test_app.py`, which that removal deleted). They are
that removal's outstanding reconciliation and are reported here rather than
concealed; `tests/test_theme_contrast.py` and every module this item touches
are green, and `build_user_guides.py --check` reports **29 of 29 artefacts
current**.

*Records and docs.* No guide describes widget colours: the only Markdown hits
for `theme|colou?r` under `documentation/` are `documentation/docs/api.md`'s
generated `styles` reference (which now lists `text_colors` from its docstring;
nothing is hand-edited) and the compiled `.docx` guides, which say what a field
does rather than how it is painted. So the answer is **"no guide describes this
behaviour"**, and `build_user_guides.py --check` cannot drift because no guide
source moved. `CHANGELOG.md` carries the user-facing bullet;
`TECHNICAL_CHANGELOG.md` the two locks and the helper.

**T-01 — COMPLETE 2026-11-01.** D8 was settled as the keyword route: four
widgets gain the missing keywords and no pack order, label width or widget set
moves. The lock is
`master_driver/tests/test_ui_cards.py::TestCardTextFollowsTheTheme` — both cards
are built in the four theme states (`System` patched through
`styles._get_system_theme`, never `os.name`) and every text-bearing widget's
**effective** pair is read back with `cget`/`winfo_rgb` (normal, active and
disabled for each Checkbutton) and asserted ≥ 4.5:1. Written before the fix it
failed in both Dark states at exactly **1.26:1** (`SystemWindowText` on
`#1e1e1e`) for all four checkbuttons, plus **3.22:1** disabled
(`SystemDisabledText`); after the fix the measured pairs are **16.67:1** (text
on the body) and **7.18:1** (disabled). The measurement pins the shipped default
palette, because a live Windows-accent palette left active by another module's
test decides `BG_LIGHT` (`#D8B496`) and made the same assertion measure a
different suite in Light — the first full-suite run found that order dependence,
and it is fixed here rather than excluded.

**L-01 — COMPLETE 2026-11-01.** Reproduced on a real 1200×800 Tk root: the open
right-column cell reported `row 0, column 1, columnspan 2` and rendered **274 px
at x=274** against the left column's **548 px at x=0**. `_relayout` now wraps an
expanded cell that is not already at column 0 onto the next row before gridding
it, so the open cell is `row 1, column 0, columnspan 2` and renders **548 px at
x=0**; a collapsed card still fills the next free column, so the pairing returns
on collapse. `TestExpansionReflow` gained four cases (the right column opens at
column 0 with span 2, `winfo_x() == 0` and a width equal to the host's; the
cards after it reflow to row 2; collapsing the right card restores the row-0
pair; two open cards both start at column 0) with the left column as the
counter-case. Proved able to fail: with the wrap removed, **2 failed** (exit 1);
restored under a SHA-256 check, 25 passed.

**T-03 — COMPLETE 2026-11-01.** Pre-fix, in the four states: the locked source
entry was `#aaaaaa` on symbolic `SystemButtonFace` = **2.04:1**, the locked
Browse button `SystemDisabledText` on the accent = **1.13:1**, and the disabled
`TCombobox` fell back to the editable surface (`#1e1e1e`/`#ffffff`). `styles`
gained `BG_READONLY` (the palette's `bg_light` in Light, `#121212` in Dark) and
`FG_ON_ACCENT_LOCKED`; `apply_styles` declares the `TEntry`/`TSpinbox`/
`TCombobox` disabled maps, and the strip passes `disabledbackground` on the
entry and `disabledforeground` on the Browse button. After: entry **8.06:1**,
Browse **4.77:1**, combobox `#aaaaaa` on `#121212` (**8.06:1**), the four
checkbuttons 7.18:1. `TestLockedStripFollowsTheTheme` builds a
`set_driven(True)` panel in the four states, reads each locked control's
effective pair plus the `TCombobox` disabled style entries, asserts ≥ 4.5:1 and
asserts no locked surface is still a symbolic `System*` colour; all **8** cases
failed before the fix (Light included — the Browse button and the symbolic
names) and pass after. The existing strip tests and
`master_driver/tests/test_refinery_tab.py` pass unedited.

**Guides (T-01, L-01, T-03).** `git grep -l -i -e 'theme\|colour\|color' --
documentation/` matches only `.docx` binaries, `documentation/docs/api.md`'s
heading, `conf.py`, the Master Driver guide's SETTINGS paragraph and the
Spectral Viewer guide's colour-map text — **no guide describes widget colours
or the card grid's geometry**, so no `.docx` was regenerated and
`build_user_guides.py --check` is unaffected. `CHANGELOG.md` carries the two
user-visible lines under `[Unreleased]`; the contrast locks are recorded in
`TECHNICAL_CHANGELOG.md`.

**Gate (T-01, L-01, T-03).** `compileall` exit 0 with no compile errors; `ruff
check .` and `ruff format --check .` (1011 files); bare `mypy .` 592 files, no
issues; bandit **0 High / 0 Medium** (44 Low, the documented B603/B606/B607
call sites); bare `pytest` **11,897 passed, 3 skipped, 35 deselected, exit 0**
in 17 m 25 s. These three items' own change set first ran **11,896 passed, 1
failed**: the red case was
`tests/test_cli_json_schema.py::TestFatalErrorExamples::
test_a_real_failure_prints_the_published_document[doctor]`, pre-existing and
untouched by this work - the committed schema corpus recorded click 8.5's
wording (`No such option '--no-such-option'.`) while the installed click 8.3.2
emits `No such option: --no-such-option`. It was fixed in a follow-on change the
same day (D15, below) rather than folded into these items.

**CLI schema corpus — the doctor usage-error wording (2026-11-01, D15).** The
recorder was run as the artefact instructs (`python -m
tests.cli_schema_conformance --record`) and its output was reviewed rather than
committed: it also rewrites ~35 `duration_secs` lines, `_generated`, and doctor's
`editable: true -> false` with `interpreter` becoming `<python>` — this host's
install state, not the `--json` contract. The three message strings that differ
for the reason at hand were kept in both artefacts
(`tests/data/cli_payloads.json`, `audio_suite_shared/cli_schema.json`), as
byte-preserving single-line edits with line endings unchanged, and every other
recorded value restored. Evidence: the three CLI contract modules
(`tests/test_cli_json_schema.py`, `tests/test_cli_schema_conformance.py`,
`tests/test_cli_usage_errors.py`) report **346 passed**, including the previously
red `[doctor]` case, and `python -m tests.cli_schema_conformance --check` reports
**38 recorded payloads and 38 fatal-error documents** valid against the schema.

**CLI failure example — the lock no longer pins Click's wording (2026-11-01,
D16).** `TestFatalErrorExamples` compares every field of a real failing run
against the published example except `error`, then checks the reason on its own:
non-empty, and naming the value the run rejected. Both new guards were proved
able to fail: with the exclusion removed from `_without_reason` (so the helper
kept every field) the reworded-reason case and the only-the-reason case both
failed (2 failed, exit 1), and the file was restored under a SHA-256 check
(`fca4db89…`). Evidence: `pytest tests/test_cli_json_schema.py
tests/test_cli_schema_conformance.py` reports **164 passed**, and
`python -m tests.cli_schema_conformance --check` is unchanged at 38 + 38
documents — the artefacts already carry the installed wording from D15, so no
re-recording was needed for this change.

**Guides (D16).** `git grep -l -e 'cli_payloads' -e 'fatal-error' -e
'--json-schema' -- documentation/` matches only `documentation/docs/index.md`
and `documentation/user_guides/reference/CLI_Commands_Reference.md`, and both
say only that `--json-schema` prints a recorded success and failure document
per command — true before and after this change, with no wording quoted. No
Markdown was edited and no `.docx` re-rendered; `python
utilities/build_user_guides.py --check` reports all **34** artefacts current.

**Gate (D16).** `compileall` exit 0; `ruff check .` clean and `ruff format
--check .` (1011 files) clean; bare `mypy .` 592 files, no issues; bandit **0
High / 0 Medium** (43 Low, the documented B603/B606/B607 call sites); bare
`pytest` **11,899 passed, 3 skipped, 35 deselected, exit 0** in 15 m 33 s — two
more tests than the previous run, which are the two new guards.

---

## 7. Open questions

- **Does the suite need a wet-music corpus?** §1.4 says no for shipping, because
  the synthetic RIR supplies ground truth the suite can assert on and any real
  corpus would need curation and licensing. The counter-argument is that a
  synthetic tail is Gaussian noise, and real rooms have discrete early
  reflections that a predictor handles differently. Revisit only with a
  licensing decision and a declared fixture set, not with a downloaded album.
- **Is a strength control worth it, or is one measured default enough?** A
  default-only tool is easier to accept (one threshold to defend); a slider
  invites "half a repair". Leaning default-only with `--strength` exposed on the
  CLI, and the measurement taken at 1.0.
- **Should F-08c model partials or interpolate the magnitude spectrogram?** Both
  satisfy §1.3; the partials model is the one that reproduces a tone to −40 dB
  by construction. Decide from the first measurement rather than in advance.
- **Does the Master Driver need a mode argument for these?** `restoration` is
  already in the driver's dependency graph with one mode; a batch that runs
  declick cannot also choose de-reverb until `arg_builder` passes a mode token.
  That is a driver-contract change with its own tests (`TestBuildEnrichArgs`
  patterns), so it is settled before F-08b's cut, not during it.
- **Should REFINE's normalise stage carry the Audio Normalizer's delivery
  targets, and which default is right?** U-01 found the stage exposes only
  target and tolerance, defaults to -16 LUFS against the tool's -14, and has no
  `lossless` mode (§11.1). Retiring the card leaves those controls in the
  standalone window and the CLI, which is enough to ship B, but a user who
  expects parity inside REFINE will not find it. Decide with F-09-style evidence
  (a measured round trip), not by copying the field names across.
- **Should a *Button*'s active colours be themed too?** T-02 swept the toggles' `activeforeground`/`activebackground` because the pointer repaints the label, and the runtime lock then showed the same omission on buttons that keep Tk's `activebackground` under a white `fg`: a hovered accent button turns `SystemButtonFace` (#f0f0f0) and its white label drops to about 1.05:1. It is roughly 100 call sites and no test builds a hovered button, so it is a sweep of its own — decide whether it joins the 2.3.1 patch or takes its own item, and add a runtime case that forces the active state before calling it fixed.

---

## 8. Changelog mapping

`CHANGELOG.md` (what a user can run or observe), one bullet per release:

- **2.4.0** — de-reverb: what it does to a reverberant recording, what the
  `--strength`/`--tail-ms` options mean, the fact that a recording the tool
  finds no reverb in is left untouched, and what a second run does.
- **2.5.0** — spectral repair: how a region is selected in the window and on the
  CLI, that only the selected region changes, and that nothing is written until
  the region is given.
- **2.3.1** (patch, §10, §11, §12) — three fix groups. (a) The card and Run
  Controls text that ignored the chosen theme now follows it, so a Dark or
  `System`(Dark) window stops showing black or washed-out grey on a dark surface,
  and a driver-locked directory field stays legible. (b) A REFINE run that
  changes nothing now leaves the file byte-identical instead of re-encoding it,
  its Dry Run reports what the enabled stages would detect, and a normalise-only
  run makes one FFmpeg pass instead of two. (c) A card's Settings in the
  Utilities tab's right-hand column now open across the window like the left
  column's, instead of filling only the right half.
- **2.6.0** (minor, §11) — the Utilities tab no longer lists the five DSP tools
  that are REFINE stages. The standalone windows and the five CLI commands still
  run them, with the options REFINE's stages do not carry.

`TECHNICAL_CHANGELOG.md` carries the measurement machinery — the RIR fixture and
its verified T60/DRR, the ERLE and region-error locks, the byte-identical no-op
assertions — because none of it is something a user runs. The audiences stay
split (`AGENTS.md`, *Change History Follows Its Audience*).

**U-01 writes no bullet of its own.** A study is not observable, so its outcome
appears only through the two items it produced: U-02's line in **2.3.1** and
U-03's line in **2.6.0**. The decision log (D11) is the study's own record.

---

## 9. Risks and rollback

- **Audio damage that looks like success** is the dominant risk in both items,
  and the mitigation is the same one declip used: every acceptance decodes the
  output and compares it to a reference, and a run that cannot improve leaves
  the file byte-identical. A measurement that fails is a finding, not a reason
  to lower the bar.
- **CPU cost.** WPE is iterative and per-channel, and the batch runs
  `DEFAULT_MAX_WORKERS` files at once. F-08b's verification records seconds per
  minute of audio on this host; if it is slower than declip by more than a
  small multiple, the worker default for the mode is lowered rather than the
  suite's global one.
- **Rollback** is the shared workflow's `batch_undo` snapshot: a live write is
  reversible per file, and the undo path is exercised by the existing in-place
  tests for every tool on that workflow. F-08c's narrower surface adds no new
  rollback obligation — only the selected region differs from the source, which
  the undo restores whole.
- **A removed driver route, not a removed capability (U-03).** Hiding the five
  cards takes away the driver's shortcut, not the tools: the `.pyw` windows and
  the five CLI commands remain, which is where the normalizer's TP/LRA/lossless
  controls still live (§11.1). The rollback is one manifest flag — the packages,
  cards' replacements and guides do not move — so a bad outcome is a revert, not
  a migration.
- **Scope.** Neither F-08 item may grow a batch editor, a spectral *eraser* or a
  preset library. The parent plan's shape holds here: the smallest version that
  delivers the capability and its measurement.

---

## 10. Theme-conformance defects (T-01 … T-03)

Three defects reported by the maintainer on 2026-10-31 against a **`System`**
theme whose OS setting is Dark. They are recorded here (D7),
and they are not F-08's work: they add no capability, change no window
structure, and take the patch slot (§8, 2.3.1) rather than 2.4.0 or 2.5.0. The
two sightings (T-01, T-03) are **fixed**, and the sweep that follows them (T-02)
is **complete**: it fixed what those two left and locked the class so it cannot
return.

**Evidence base, measured on this host (2026-10-31, Tk 9.0, `clam`).**
`styles.set_theme_mode("System")` on a Dark OS sets `BG_WHITE = #1e1e1e`,
`FG_MAIN = #ffffff`, `FG_SUB = #aaaaaa`. A `tk` widget created with
`bg=styles.BG_WHITE` and **no** `fg` keeps Tk's own default foreground
(`SystemWindowText` = black), which measures **1.26:1** against `#1e1e1e` —
unreadable, and below WCAG AA's 4.5:1 for body text. Tk's symbolic system
colours do not follow the suite theme at all: an entry's `-disabledbackground`
defaults to `SystemButtonFace`, which resolves to `#f0f0f0` in **both** themes.
The theme is applied once at launch (`master_driver/app.py:101`,
`audio_suite_shared/app_bootstrap.py:97`) and saved on close, so a live switch is
not repainted — these items are about the launch-time state only, and a live
repaint is a separate question this plan does not take.

### T-01 — Card text that ignores the theme (BPM Analyzer, Lyrics Manager) (S)

**Status:** `[x]` **COMPLETE** (2026-11-01) — evidence in §6. Work order **1 of 8** (§5), the easiest item in
the plan. **Reported:** on the Master Driver's BPM Analyzer card, "Parallel
Processing" is black on the card's dark grey body under `System`(Dark); the same
is true of the text in the Lyrics Manager card.

*Current state.* Both cards hand-build their bodies instead of using
`_card_base.build_simple_card`, and the offending widget in each is a
`tk.Checkbutton` given a background but no foreground:

- `master_driver/ui/cards/bpm_card.py:73-81` — "Parallel Processing": `font`,
  `bg`, `activebackground` only. No `fg`, `activeforeground` or `selectcolor`.
- `master_driver/ui/cards/lyrics_manager_card.py:63-108` — three checkbuttons:
  "Skip files that already have lyrics", "Store plain lyrics when no synced
  lyrics are available", "Parallel Processing". Same omission. (That card's
  labels and entries *do* pass `fg=styles.FG_MAIN` — the defect is the missing
  keyword, not the palette.)

This is the taxonomy the card layer already has and these two files skip:
`_card_base.CardCheckEntryRow` renders exactly this Parallel Processing / Workers
row with `bg`, `fg`, `selectcolor` and `activebackground`, and
`build_simple_card` passes `fg=styles.FG_MAIN` on every other row type. Neither
card calls either function, so they are the outliers rather than the palette
being wrong.

*Change.* Give those four checkbuttons the full colour set
(`fg`/`activeforeground` from `styles.FG_MAIN`, `selectcolor` from
`styles.BG_WHITE`, `disabledforeground` from `styles.FG_SUB`), **or** transcribe
both bodies onto `build_simple_card`/`CardCheckEntryRow` — the route is D8 and
the layout does not move either way.

*Acceptance.* A test builds each card in all **four** theme states — Light, Dark,
`System`→Light and `System`→Dark (the last two by patching
`styles._get_system_theme`, never `os.name`; `AGENTS.md`, *Verification Tooling
Traps*) — and asserts for every text-bearing widget the card creates that the
**effective** pair resolves to contrast ≥ **4.5:1**. Effective means read back
off the widget (`cget("fg")`, `cget("bg")`, resolved through `winfo_rgb()` when
a symbolic name such as `SystemWindowText` comes back), not the `styles`
constant the code passed: the bug is precisely a key the code did *not* pass, so
a test asserting the constants would pass on the broken build. Written before
the fix and shown to fail at 1.26:1. The existing construction tests in
`master_driver/tests/test_ui_cards.py` keep passing unedited.

*Files:* `master_driver/ui/cards/bpm_card.py`,
`master_driver/ui/cards/lyrics_manager_card.py`, and the card test module
(`test_ui_cards.py`, or a new `test_card_contrast.py` if T-02 owns the helper).

*Risk.* No audio risk; the risk is scope. "Fix the two cards" must not become a
redesign of both — the pack order and label widths stay exactly as they are and
only colour keywords (or the equivalent spec) change.

### T-02 — Theme-conformance sweep for text colour, and its lock (M)

**Status:** `[x]` **COMPLETE** (2026-11-01) — evidence in §6. Work order **6 of
8** (§5). This is the sweep the
report asked for ("a sweep of how text is displayed in connection with the
theme"), and it is the item that stops the class returning. It follows T-01 on
purpose: its repo-wide lock generalises T-01's contrast helper.

*Current state.* An AST walk of every first-party UI module (tests and
`__pycache__` excluded, 2026-10-31) finds **11 widgets that set a themed
background and no foreground at all**, in 7 files:

| File:line | Widget | Text-bearing? |
|---|---|---|
| `master_driver/ui/cards/bpm_card.py:77` | "Parallel Processing" checkbutton | yes — T-01 |
| `master_driver/ui/cards/lyrics_manager_card.py:69,78,89` | three checkbuttons | yes — T-01 |
| `cd_ripper/ui/results_tab.py:35` | "Rip Complete!" label | yes |
| `cd_ripper/ui/setup_tab.py:98` | "Insert a CD…" info label | yes |
| `audio_refinery/ui/setup_tab.py:464` | empty spacer label | no |
| `audio_refinery/ui/setup_tab.py:667` | stage enable checkbutton | indicator only |
| `album_art_sync/ui/picker_dialog.py:106` | artwork label (`bg="#eee"`, hardcoded) | image only |
| `master_driver/ui/cards/_card_base.py:173`, `:362` | card header toggle | indicator only |

The same walk sizes the **disabled** hole T-03 is one instance of: **81**
`Entry`/`Text`/`Combobox` constructors set a themed background and no
`disabledforeground`, and 19 widgets are constructed `state="disabled"` outright
— every one of them falls through to Tk's own greys. Indicator-only widgets are
not cosmetic by default: their `selectcolor` defaults to `SystemWindow`, so the
box itself ignores the palette.

*Change.* One pass over the enumerated set, plus whatever the second pass of the
same walk finds: each widget gets the shared keyword set for its type — `fg`,
`activeforeground`, `selectcolor` for `Checkbutton`/`Radiobutton`; `fg`,
`insertbackground`, `disabledforeground`, `disabledbackground` for text-bearing
`Entry`/`Text`; the `TEntry`/`TCombobox` `style.map` entries for the ttk path.
The repeated triple is factored into one helper in
`audio_suite_shared/styles.py` (e.g. `text_colors()` returning the fg/active/
disabled mapping) so the next widget cannot get it half right; the hardcoded
`bg="#eee"` in `picker_dialog.py` becomes a `styles` value in the same pass.

*Acceptance.* (a) The contrast assertion from T-01 **generalised into a
repo-wide AST test**: every first-party widget constructor that passes a
`bg`/`background` must also pass a foreground for the state it can be seen in
(an `Entry` anything in the tree disables must pass `disabledforeground`), with
the found-set asserted **non-empty** and a fresh exclusion set — not a reused
constant with the opposite purpose (`AGENTS.md`, *Never Lose a Rule to a
Scripted Edit*). (b) A runtime test that builds the Master Driver window and
each tool's Setup tab in the four theme states and asserts ≥ 4.5:1 on every
text widget it can enumerate. Both written first; both fail against today's
tree.

*Files:* the 7 files tabled above, `audio_suite_shared/styles.py` (helper),
`master_driver/ui_panels.py` and the card files the second pass reaches,
`tests/test_theme_contrast.py` (new).

*Risk.* This is the mechanical-edit class that produces
valid-Python-wrong code: every change is a keyword addition, so compile, ruff,
mypy and the suite stay green while a widget sits in the wrong container. Review
by diff, and let the AST and runtime locks be the evidence — do not "tidy" any
layout while passing through.

### T-03 — Run Controls strip: a locked Source Music Directory value (S/M)

**Status:** `[x]` **COMPLETE** (2026-11-01) — evidence in §6. Work order **3 of 8** (§5). **Reported:** on the
control strip, the Source Music Directory value reads as light grey on a white
box.

*Current state.* `audio_suite_shared/ui_driver_controls.py` is the shared strip
every tool's Setup tab embeds (`ui_common.BaseSetupFrame._add_controls_panel`,
18 of 19 tools, plus `audio_refinery`, `album_art_sync` and
`master_driver/ui/refinery_tab.py`). Its `self.source_entry` (`:86-95`) passes
`bg`, `fg`, `insertbackground` and `disabledforeground` but **not**
`disabledbackground`; `set_driven(True)` (`:196-198`) then sets
`state="disabled"`, and a disabled `tk.Entry` paints with
`-disabledbackground`, which defaults to the symbolic **`SystemButtonFace`**.
Measured here: that is `#f0f0f0` in both themes, so under `System`(Dark) the
locked value is `#aaaaaa` on `#f0f0f0` — **2.04:1** (the reported wash-out)
inside a window whose own surfaces are `#1e1e1e`. The Light branch is
`#555555` on `#f0f0f0` = 6.54:1: legible, but still not the suite's own
`BG_WHITE`, which is why the field looks like a foreign box in both modes.
`set_driven` disables six widgets in total (`source_entry`, `browse_btn`,
`mode_combo`, `auto_start`, `clear_logs`, `parallel`), so it is the whole locked
strip that has to be checked, not the one field.

*Change.* Give the field a themed `disabledbackground` (a new `styles`
read-only-field value, or `BG_ITEM` if the two are meant to agree) and keep
`disabledforeground` on `styles.FG_SUB`; theme the ttk path through
`apply_styles`'s `style.map` entries (`TEntry`/`TCombobox` have no per-widget
`disabledbackground`); and check the other five disabled widgets in the strip,
including the Browse button whose `bg` is the accent colour (it therefore also
needs its `disabledforeground` to stay legible on the accent).

*Acceptance.* A test drives `DriverControlsPanel` through `set_driven(True)` in
the four theme states, reads the **effective** colours back (`cget`, resolved
through `winfo_rgb()`) and asserts ≥ 4.5:1 for the entry, the mode combobox, the
Browse button and the four checkbuttons — and that no widget's reported
background is still a symbolic system name (`SystemButtonFace`, `SystemWindow`)
once the theme is applied. It must fail on pre-fix code at 2.04:1 in Dark. The
existing strip tests (`audio_suite_shared/tests/test_ui_driver_controls.py`,
`master_driver/tests/test_refinery_tab.py`) keep passing unedited.

*Files:* `audio_suite_shared/ui_driver_controls.py`,
`audio_suite_shared/styles.py` (the value and any `TEntry` mapping),
`audio_suite_shared/tests/test_ui_driver_controls.py`.

*Risk.* Low to the product, wide to the suite: the strip is shared by every
tool, so a wrong value is a suite-wide visual regression — that is what the
four-state assertion is for. Do **not** "fix" it by leaving the field editable:
the lock is a real contract (`set_driven` exists so a driver-launched run cannot
be changed mid-batch).

### 10.1 Guides

No generated guide describes widget colours (the user guides describe what a
field *does*, not how it is painted), so the expected outcome is **"no guide
describes this behaviour"** — recorded at implementation, in the item's
verification line, after
`git grep -l -i -e 'theme\|colour\|color' -- documentation/` is read to confirm
it (`AGENTS.md`, *User Guides Follow the Change*: a sweep is one directory walk,
and a skipped review must be visible).

---

## 11. Utilities-tab overlap with REFINE (U-01 … U-03)

**Requested by the maintainer, 2026-10-31.** The Master Driver's UTILITIES tab
carries five DSP tools — Pop & Click Remover, Silence Trimmer, Noise Reduction,
Audio Enhancer, Audio Normalizer — and the REFINE tab carries the same five as
stages. Because every REFINE stage has its own enable checkbox, each can be run
on its own, so the five utility entries may be redundant. The request was to add
the question to the plan, not to answer it. The examination is **COMPLETE**
(2026-10-31): its result is §11.1 and its decision is D11; the work it produced
is U-02 and U-03. It added no capability and moved no audio.

### U-01 — Decide whether the five DSP utility entries still belong (S)

**Status:** `[x]` **COMPLETE** (2026-10-31). The study found option B to be the
right retirement; its result is §11.1, its decision is D11, and the work it
produced is U-02 and U-03 below. No code changed.

*Current state — the duplication is at the entry points, not in the DSP.* Each
of the five is a complete tool: a `category="utility"` manifest with its own
`order` (`audio_suite_shared/tool_plugin.py:486-535`), a card in
`master_driver/ui/cards/`, a top-level `.pyw`, a CLI command, an arg-builder
entry (`master_driver/runner/arg_builder.py:358-390`), a `DEPENDENCY_GRAPH`
entry (`master_driver/batch_orchestrator.py:264-274`), an AppState toggle key,
its own test suite and its own guide. The UTILITIES tab builds its cards from
exactly that list (`master_driver/ui/utilities_window.py:159`,
`registry.driver_by_category("utility")`).

The REFINE tab, by contrast, *imports those tools*:
`audio_refinery/ui/setup_tab.py:30-34` imports the `audio_enhancer`,
`audio_normalizer`, `pop_click_remover` and `silence_trimmer` setup panels, its
five stage builders (`:221-225`) call them (and `audio_enhancer`'s shared
`CustomDspPanel`), `audio_refinery/core/models.py:24` imports
`noise_reduction.core.models.NoiseReductionParams`, and each stage runs only
when its own checkbox is set (`audio_refinery/core/pipeline.py:199-229`); a run
with none set is refused (`audio_refinery/app.py:486`). The CLI is the same
story: `refine --stages declick,trim,reduce_noise,enhance,normalise` runs any
subset (`audio_refinery/utils/cli_args.py:139-143`). So "each entry can be run
separately" is true on both surfaces — and "delete the duplicates" cannot mean
deleting the packages, because they are the refinery's libraries.

*What the examination must settle.* Which **entry points** stay, for each of the
five. The deliverable is a parity table plus one chosen option, recorded as a
decision; no code lands in this item.

1. **Parity per stage**, both surfaces read, every row naming file:line. Five
   findings are already visible and must not be assumed away:
   - **Normalise.** The standalone tool exposes a true-peak ceiling and a
     loudness range (`audio_normalizer/app.py:76-77`, `ui/setup_tab.py:265-270`)
     and `--tp` / `--lra` / `--mode lossless` on its CLI. The refinery's
     `NormaliseParams` holds only `target_lufs` and `tolerance`
     (`audio_refinery/core/models.py:77-81`), and its panel passes only those
     two (`audio_refinery/ui/setup_tab.py:618-623`), so REFINE cannot set TP or
     LRA and cannot run lossless. Retiring the utility entry would remove a
     control, not just a card.
   - **Enhancer.** The standalone tool writes a *new* file: `--output` is
     required and the source is never overwritten
     (`master_driver/runner/arg_builder.py:691-706`). REFINE writes in place
     unless an output folder is given, and runs whatever else is checked with
     it. Same DSP, different file-safety contract.
   - **Trim defaults.** The stage's 500/1000 ms fades
     (`audio_refinery/core/models.py:44-45`) match the standalone *GUI*
     (`silence_trimmer/app.py:86-87`) but not its *CLI*, whose
     `--fade-in`/`--fade-out` default to 25 (`silence_trimmer/cli.py:41-42`).
     "The same processors" is true; "the same defaults" is not, and a parity
     table that reads only one surface would miss it.
   - **Noise Reduction.** Parameter parity is literal — one shared dataclass —
     but the REFINE panel re-implements the hum/broadband controls
     (`audio_refinery/ui/setup_tab.py:394-509`) instead of calling the tool's
     panel. That is a second UI to keep in step, and a candidate to fold in
     whichever option wins.
   - **Declick.** Appears to share both the panel builder
     (`pop_click_remover/ui/setup_tab.py:142`) and the parameter shape; confirm,
     do not assume.
2. **The write contract, which is the hazard.** A standalone run through
   `run_inplace_dsp_batch` writes nothing when the processor reports
   `was_modified == False` and counts the file skipped
   (`audio_suite_shared/file_processor_base.py:754`). The refinery always
   exports a temp file, restores tags, records an undo snapshot and replaces
   the source once any stage is enabled
   (`audio_refinery/core/pipeline.py:219-233`). So "run just Noise Reduction"
   re-encodes the file through REFINE and leaves a clean file byte-identical
   through the standalone tool. If the study recommends a retirement, it must
   say whether REFINE first grows the no-op rule — and that is a separate item
   with a hash assertion, not a footnote to a UI change.
3. **Removal cost per option**, walked against the checklist rather than
   remembered. Each of the five is wired into every registration point
   *Registering a New Tool* names, and its id is pinned in at least five test
   sets (`audio_suite_shared/tests/test_tool_plugin.py:231-236` and `:302-307`,
   `master_driver/tests/test_app_state.py:706-712`,
   `master_driver/tests/test_runner.py`'s per-tool argument tests,
   `master_driver/tests/test_ui_cards.py`), in `pyproject.toml`'s `testpaths`
   and coverage `source`, and — for three of the five — in
   `tests/test_callback_payload_contract.py`'s 19-entry `EXPECTED_TOOLS`;
   `declick` and `noise_reduction` are absent there because its AST pass cannot
   resolve their `NoisePopToolApp` peer shape (`:55-56`). `README.md`,
   `documentation/docs/index.md` and the CLI reference are generated, so they
   follow only if their generators are re-run.

*Options the examination chooses between* (none is pre-selected):

| Option | What changes | What it costs or keeps |
|---|---|---|
| **A. Keep both** | nothing | no work, and the redundancy stays; the parity gaps above are already drift between two entry points |
| **B. Retire from the Utilities tab only** | the tab's card list, through a presentation field or an explicit driver-side exclusion; manifests, `.pyw` launchers, CLI commands and guides stay | one small, reversible change. `ToolManifest.is_driver_tool` (`audio_suite_shared/tool_plugin.py:119-126`) is the existing seam — `driver_by_category` already filters on it — so a `driver_visible` flag on the five manifests removes the cards without touching the commands |
| **C. Retire the standalone entry points** | manifest (and so the card, CLI command, README/docs rows), `.pyw`, arg builder, graph entry, state key, guide, and the pinned tests | the largest diff, and it breaks every script that calls `audiosuite declick` / `silence-trim` / `reduce` / `enhance` / `normalise`; the packages survive as the refinery's libraries, so the DSP and most of its tests stay |

*Acceptance.* A decision-log row (D11, appended when the study runs) carrying
(a) the parity table, one row per stage, both surfaces named, (b) the chosen
option and why, and (c) if B or C, a follow-on item with its files list, its
test updates and its release slot. The study completes with **no code change**;
concluding A is a valid, recorded outcome, not a failure. A row that says
"parity confirmed" without naming both surfaces read is not evidence.

*Risk.* Two. A silent audio-contract regression is the first: option C without
step 2 would replace "this file is clean, leave it alone" with "this file is
clean, re-encode it", which no level metric would flag — hence step 2 is a gate.
The second is scope: the study must not become the retirement. Doing both in
one change would mix a decision nobody has agreed to with the code that
implements it, and this plan's rule is that an examination records, it does not
act.

*Files:* no production file changes. The study reads the five manifests and
their five cards, `master_driver/ui/utilities_window.py`,
`master_driver/runner/arg_builder.py`, `master_driver/batch_orchestrator.py`,
`master_driver/state/app_state.py`, `audio_refinery/` (`core/models.py`,
`core/pipeline.py`, `ui/setup_tab.py`, `utils/cli_args.py`), the five tools'
`app.py`/`ui/`/`cli.py`/`core/`, and the tests and guides listed above.

### 11.1 Result — the parity table (U-01, complete)

The table compares each tool's **GUI panel and CLI** against the REFINE stage's
panel and `refine --stages`, on four questions: is the implementation shared, are
the options and defaults the same, what does a run write, and what does a Dry Run
report. No audio was processed — this is a static reading of both surfaces, and
each row names the code it compared. Engine-level DSP is not a variable: REFINE
imports the tools' cores.

| Stage (tool → REFINE) | Shared implementation | Options and defaults | Write / re-run / Dry Run |
|---|---|---|---|
| **Declick** (Pop & Click Remover → `declick`) | `declicker.declick_audio` in both; REFINE embeds the tool's own panel (`pop_click_remover/ui/setup_tab.py:142`, called from `audio_refinery/ui/setup_tab.py:332-359`) | sensitivity 0.01–0.40 and max width 1–10 in both; GUI/REFINE default 0.31 / 2 ms, the tool's **CLI** 0.25 / 5 ms (`pop_click_remover/cli.py:36-48`) | standalone: a clean file is skipped, no write (`audio_suite_shared/file_processor_base.py:754`); REFINE: always writes; Dry Run: standalone detects, REFINE only loads (`audio_refinery/core/pipeline.py:185-197`) |
| **Trim** (Silence Trimmer → `trim`) | `trimmer.trim_and_fade` in both; REFINE embeds the tool's panel (`audio_refinery/ui/setup_tab.py:362-390`) | threshold -50 dBFS, fades off, 500/1000 ms in both GUI/REFINE; the tool's CLI defaults to 25/25 (`silence_trimmer/cli.py:41-42`) | as declick: skip vs always-write, detect vs load-only |
| **Noise Reduction** (`reduce_noise`) | one `NoiseReductionParams` dataclass (`audio_refinery/core/models.py:24`) and `noise_reducer.reduce_noise`; REFINE **re-implements** the six controls (`audio_refinery/ui/setup_tab.py:394-509`) | identical in all three surfaces: hum off, 60 Hz, 8 harmonics, Q 30; broadband off, 0-500 ms, gate 3.0 dB (`noise_reduction/core/models.py:19-39`) | as declick; the duplicated panel is the only parity risk |
| **Enhance** (Audio Enhancer → `enhance`) | shared `CustomDspPanel`, `PRESETS`/`EnhancementParams` and chain (`audio_refinery/ui/setup_tab.py:511-590`) | same presets and effect toggles; REFINE hides output gain while normalise is on (`pipeline.py:622-636`). Destination: the tool writes in place when its output field is blank and copy-out when it is set (`audio_enhancer/app.py:377-395`); the **driver card** requires a folder (`master_driver/runner/arg_builder.py:691-706`); REFINE supports both | Dry Run: the tool runs the chain and reports per-file gain, REFINE only loads |
| **Normalise** (Audio Normalizer → `normalise`) | `loudness.measure` and `normalizer.apply` in both | tool: target, tolerance, true-peak ceiling, LRA (`audio_normalizer/app.py:73-78`, `ui/setup_tab.py:265-270`) and CLI `--tp`/`--lra`/`--mode lossless`; REFINE: **target and tolerance only** (`audio_refinery/core/models.py:77-81`, `ui/setup_tab.py:613-625`). Default target: tool **-14** LUFS, REFINE **-16** (`audio_normalizer/app.py:74`; `audio_refinery/utils/settings.py:77`, `utils/cli_args.py:280-287`) | tool: one FFmpeg loudnorm pass, skipped within tolerance (`audio_normalizer/core/file_processor.py:88-92`); REFINE: pydub-export the decoded audio to a temp file, then loudnorm **that** temp (`pipeline.py:219-229`) — two lossy encodes, and the export has already happened before the tolerance check, so a within-tolerance file is still re-encoded and replaced |

**Two workflow differences apply to all five.** REFINE keeps a
`_refinery_completed.log` in the source folder and skips a file whose name and
hash are already recorded, so a second run is a no-op until **Reset Progress**
(`audio_refinery/core/registry.py`); the standalone tools reprocess the folder
every time. And REFINE's completion for a no-op file is currently DONE (it wrote
anyway), which is the defect U-02 fixes.

**What the table decides.** Declick and trim are exact **option** duplicates of
their stages, noise reduction is one with a re-implemented panel, and the
enhancer is a near-duplicate whose only gaps are the driver's output-folder rule
and the dry-run preview. The normalizer is **not** a duplicate: two of its four delivery
controls are missing from REFINE, its default target differs by 2 LU, and a
REFINE normalise run encodes twice. The chosen option (B, D11) still retires all
five cards because it removes only the tab's shortcut: the tools, their windows,
their full option sets and their five commands stay, and the normalizer's
TP/LRA/lossless controls are reachable there. What B cannot do is call REFINE an
equivalent replacement while it rewrites clean files and its Dry Run detects
nothing — which is why U-02 precedes the retirement rather than following it.

### U-02 — REFINE's Dry Run and no-op contract (M)

**Status:** `[x]` **COMPLETE** (2026-11-01). Work order **4 of 8** (§5). The
defect U-01 found (D11) is fixed: a run that changes nothing leaves the file
byte-identical, Dry Run detects with the enabled stages, and a normalise-only
run is one FFmpeg pass. Evidence is in §6; the release-note re-baseline and the
guide-lock repair this work needed are D12 and D13.

*Current state.* `process_file` exports the decoded audio to a temp file,
restores tags, records the undo snapshot and replaces the source whenever any
stage is enabled, whether or not that stage changed anything
(`audio_refinery/core/pipeline.py:199-233`). The standalone workflow takes the
opposite course: `run_inplace_dsp_batch` writes nothing when the adapter reports
`was_modified == False` and counts the file skipped
(`audio_suite_shared/file_processor_base.py:754`). For a lossy source, REFINE's
behaviour is a generation of re-encode on a file that needed none. The Dry Run
branch returns after loading, before any stage (`pipeline.py:185-197`), so it
reports RMS rather than what the enabled stages would detect. And a
normalise-only run encodes twice: the decoded audio is written to the temp file,
then FFmpeg loudnorm re-encodes that temp (`pipeline.py:219-229`).

*Change.* (a) Every stage reports whether it modified the audio (declick and
noise reduction already carry `was_modified`, trim carries `trimmed is not
None`, enhance always modifies, normalise reports whether it applied); when none
did, `process_file` writes nothing, takes no snapshot and reports the file
untouched. (b) A Dry Run runs the enabled stages on the decoded audio and
reports their messages without writing — the normalise stage measures the source
and reports the projected target rather than applying it — so it matches the
preview the standalone runs give. (c) A normalise-only run measures the source
first and, when it is out of tolerance, applies loudnorm directly to the source
in **one** FFmpeg pass, instead of the export-then-normalise pair; a multi-stage
run keeps that pair, because the processed audio has to be written before
loudnorm can act on it. (d) A no-op is
reported SKIPPED and is **not** added to `_refinery_completed.log`, so a later
settings change is not masked; a real write keeps today's DONE and registry
behaviour.

*Acceptance.* Hash **and** mtime unchanged for a clean file with each single
pre-write stage enabled (declick, trim, reduce_noise) and for a normalise run
already inside tolerance; a file that needs work still changes (the counter-case
for every stage, so a broken "nothing happened" flag cannot pass); the Dry Run
writes nothing anywhere (hash every file) and its per-stage messages name the
detections; the no-op path records no undo snapshot; the normalise-only
out-of-tolerance path is one FFmpeg pass, asserted by patching `_write_output`
and asserting it is not called, **alongside** the decoded outcome (target LUFS
reached, duration and tags preserved). Tests extend
`audio_refinery/tests/test_pipeline_stages.py` and add
`audio_refinery/tests/test_pipeline_noop.py`.

*Files:* `audio_refinery/core/pipeline.py`,
`audio_refinery/core/file_processor.py` (skip reporting and the registry
decision), `audio_refinery/tests/test_pipeline_stages.py`,
`audio_refinery/tests/test_pipeline_noop.py` (new),
`documentation/user_guides/individual_programs/audio_refinery/Audio_Refinery_User_Guide.md`
and its `.docx` (Dry Run now detects; a clean file is left untouched),
`CHANGELOG.md` (2.3.1).

*Risk.* The no-op gate is where a wrong "nothing changed" verdict silently skips
a real repair, so each stage's flag is asserted in both directions and the hash
is the evidence, never the message. The normalise-only rewrite must keep the
existing snapshot and tag-preservation behaviour, and the Dry Run must not leave
a temp file behind.

### U-03 — Retire the five DSP cards from the UTILITIES tab (M)

**Status:** `[x]` **COMPLETE** (2026-11-01). Work order **5 of 8** (§5).
Implements U-01's decision (B, D11) and depends on U-02, which landed first so
the cards' replacement leaves a clean file alone before the shortcut goes.
Evidence is in §6.

*Change.* Add `driver_card: bool = True` to `ToolManifest` and make
`is_driver_tool` require it; set it `False` on the five manifests with a comment
naming REFINE and the launcher/CLI that remain. `driver_manifests` and
`driver_by_category` then drop them from the tab, the AppState toggle set,
`build_utility_args` and the launch gate without renaming anything else. Delete
what only the cards reached: the five `master_driver/ui/cards/*_card.py` modules,
the five arg-builder entries and their `_build_*` helpers, the five
`DEPENDENCY_GRAPH` nodes, and the AppState option variables those cards owned
(`declick_*`, `trimmer_*`, `nr_*`, `enhancer_*`, `normalizer_*`), each confirmed
card-and-arg-builder-only by a grep before deletion. Keep the manifests, the five
top-level `.pyw` launchers, the five CLI commands, the packages, the DSP and the
guides: the tools still exist, they are simply not offered from the driver.

*Acceptance.* The UTILITIES tab renders **15** cards (20 first-party utilities
minus 5); `driver_manifests` excludes the five while `registry.all` and
`audiosuite --help` still list them; each `.pyw` still starts; the five guides
still render and `build_user_guides.py --check` passes; no dangling reference
remains in the driver (a grep of `master_driver/` for each id is empty), while
the id still appears in the registry, its package, `pyproject.toml` and its guide
by design;
`test_tool_plugin.py`, `test_app_state.py`, `test_runner.py` and
`test_ui_cards.py` are updated in lockstep, and
`tests/test_callback_payload_contract.py` keeps the three windows it covers (they
still exist). The Master Driver guide's UTIL section and tool list say where the
five went — REFINE for a pipeline run, the launcher/CLI for their full option
set — and the change is the 2.6.0 bullet.

*Files:* `audio_suite_shared/tool_plugin.py`, the five manifests, the five card
modules (deleted), `master_driver/runner/arg_builder.py`,
`master_driver/batch_orchestrator.py`, `master_driver/state/app_state.py`,
`master_driver/ui/utilities_window.py` (its stale "seventeen" count),
`master_driver/tests/test_ui_cards.py`, `master_driver/tests/test_runner.py`,
`master_driver/tests/test_app_state.py`, `audio_suite_shared/tests/test_tool_plugin.py`,
`documentation/user_guides/individual_programs/master_driver/Master_Driver_User_Guide.md`
and its `.docx`, `CHANGELOG.md`.

*Risk.* The one real cost is the driver shortcut for the normalizer's TP/LRA
controls and its lossless mode, which REFINE's stage does not carry (§11.1); the
standalone window and `audiosuite normalise --mode lossless` still do, and the
guide must say so. A user's habit of launching these five from UTIL is broken by
design, so the 2.6.0 note has to name the replacements rather than bury them.

---

## 12. UTIL tab layout defect (L-01)

**Reported:** 2026-11-01, as a symptom rather than a plan item — in the Master
Driver's UTILITIES tab the cards sit in two columns, and "when opening settings
on any card in the left column, the settings are shown across the width of the
window; when opening a card in the right column, only the right-half of the
window opens to show the settings." Recorded rather than fixed at the
maintainer's direction, as D7 was for the theme class, and slotted second in
the work order (D14).

### L-01 — An expanded right-column card keeps the right half (S)

**Status:** `[x]` **COMPLETE** (2026-11-01) — evidence in §6. Work order **2 of 8** (§5). **Reported by the
maintainer** on 2026-11-01; the reproduction and the cause are below.

*Current state — the grid spans the card without moving it.*
`master_driver/ui/utilities_window.py` lays the cards into `_CARD_COLUMNS = 2`
weighted, uniform columns (`:88-92`) and re-places every cell on each
expand/collapse (`_relayout`, `:134-148`), giving the open cell
`columnspan = _CARD_COLUMNS`. The walk advances `column += span` and starts a new
row only when `column >= _CARD_COLUMNS`, so a card that is already in the right
column is gridded at `column=1` with a span of two: it claims columns 1 and 2,
and column 2 is an implicit third column that no `columnconfigure` ever weights.
Measured with the tab built from the registry on a real 1200×800 Tk root:

| open card | grid | rendered |
|---|---|---|
| left column (index 0) | row 0, col 0, span 2 | **548 px at x=0** |
| right column (index 1) | row 0, col **1**, span 2 | **274 px at x=274** |
| next left card (index 2) | row 1, col 0, span 2 | 548 px at x=0 |

So the right-hand card receives exactly one column's width and keeps the right
half, which is the report verbatim. Nothing in the card itself is wrong: the
shell's body packs `fill="x"` and the `on_card_expand` hook fires for both
columns (`_card_base.py:286-289`).

*Why the existing tests miss it.*
`master_driver/tests/test_utilities_window.py::TestExpansionReflow` asserts the
span and the reflow of the cards *after* the open one, but every case except the
last opens index 0 — and `test_two_cards_open_at_once_still_span` does open cells
0 and 1, yet asserts only span and row order, never the open card's **column** or
rendered width. The defect therefore passes the whole suite while being visible
on every launch.

*Change.* In `_relayout`, an expanded cell that is not at column 0 wraps first
(`row += 1; column = 0`) and is then gridded with its span, so a spanning card
always begins at the left edge; a collapsed card still fills the next free
column, so the pairing is unchanged. No card file, no `_card_base` change and
no new widget: the left column is already the reference behaviour the right
column must match (`spans both columns`, `D119` in `PLAN_feature_expansion.md`).

*Acceptance.* For the **right-column** card (index 1): `grid_info()` reports
**column 0** and columnspan `_CARD_COLUMNS`; the rendered width equals the grid
host's width and `winfo_x() == 0` (asserted with `update_idletasks`, on the
hidden root the suite already uses); the cards after it reflow onto the
following rows, and collapsing the right card restores the pairing exactly as
collapsing a left card does. The counter-case is index 0 — the left column's
numbers must not move — and the two-cards-open case must assert that **both**
open cards start at column 0. Extend `TestExpansionReflow` rather than adding a
second module (`test_utilities_window.py` is the module's test file).

*Files:* `master_driver/ui/utilities_window.py`,
`master_driver/tests/test_utilities_window.py`.

*Risk.* The wrap costs a row whenever a right-column card is open, so the scroll
region has to refresh — `_relayout` already schedules
`canvas.after_idle(_sync_scrollregion)`, and a test that reads geometry before
`update_idletasks` sees stale values. Doing this before U-03 means the test edits
are made against the seventeen-card list that U-03 then shortens; neither
touches the other's lines, so no order dependency is created.
