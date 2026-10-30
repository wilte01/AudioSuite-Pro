# PLAN — functional backlog (B2, A1, F-01, F-02, F-05/F-06, F-09, F-08, F-10)

**Status:** **Wave 1 complete** — F-10 `5d4ab22`, F-09 `6642d41`, B2 `8890b73`,
A1 `c6f54dc` and the guide sweep `6a4be7a` on `main`; see §6. Waves 2-3 remain
`[ ]` planned and unstarted.
**Base state:** `main` at `9790778`, with `v2.1.6` published at `0556069`.
The suite is green (11 236 passed locally; the floor leg 11 235 passed, 4 skipped
on the runner, runs `40874653524` and `40878665883`), the dependency audit
blocks, and the four remaining register defects (R-13, R-14, X12, X7) are fixed
on `adec3b9`. The normalise defect that X12's un-skipping exposed is fixed on
`dc1b3c5` — it is why **F-10** exists.
**Governing scope:** capability work — the seven items the audit's §9.3 market
backlog and the remediation plan's §8 carried as deferred. It does **not**
re-open the defect register (closed by its D31) and it authorises no release cut.

Why a new plan: `AGENTS.md`, *Plan Governance* — follow-on work opens its own
plan, and these items are capability, not defects. The defect register had begun
absorbing polish (X2, X7) while this list sat untouched, which made a green
register read as a green product. Separating them is what let that file end.

---

## 1. What this plan is not

- **Not a defect list.** No item here fixes wrong output. Every item adds a
  capability the suite does not have, or measures an existing approximation.
  One deliberate exception: **F-10** is a sweep, admitted to *lock* a defect
  class rather than to list defects (D12), and if it finds nothing it changes
  nothing.
- **Not a rewrite.** Each item names the module it extends, and the smallest
  version that delivers the capability.
- **Not a release plan.** A cut is a separate decision with its own gate; this
  plan only says which version each item would ride.

---

## 2. How "done" is judged here

The suite's own rules apply unchanged, and three of them decide most of the work:

1. **Audio correctness is release-blocking, and its evidence is the audio.**
   Every item that writes audio (B2, F-08, F-09) must decode the result and
   measure it — per-channel RMS, integrated loudness, true peak — never read back
   the field it just wrote. `AGENTS.md`, *Defects and failing checks*.
2. **A measurement is not a guess.** A1 exists because the shipped album-gain
   arithmetic is an approximation; the first deliverable there is the
   measurement, not a code change.
3. **No item is done until its user-facing documentation has been read against
   the change.** The rule and its procedure live once, in `AGENTS.md`,
   *User Guides Follow the Change*; this plan only adds that it binds **per
   item** — §6 records each wave's outcome, including "no guide describes this
   behaviour" when that is the answer. **A1 is the evidence for enforcing it at
   this granularity**: its arithmetic changed and the ReplayGain guide still
   described the replaced formula in four places, because nothing in the item
   said to look (D17).

Each item also carries the registration cost `AGENTS.md` names: a new *tool* is
eleven steps (manifest, card, CLI, arg builder, dependency graph, driver state,
`.pyw` launcher with the pre-flight guard, user guide plus rendered `.docx`,
`testpaths`/coverage registration, tests, callback contract). That cost is why
the items below prefer extending a tool unless the workflow is genuinely
different — and where a new tool is chosen, the eleven steps are budgeted, not
discovered.

---

## 3. Decision log

| D | Decision | Status | Rationale / evidence |
|---|---|---|---|
| D1 | This work lives in a **new plan**, and the defect register is closed rather than extended. | DECIDED | `AGENTS.md`, *Plan Governance*. The register's own D31 records that it stops accepting items; mixing capability work into it is what made a tooling tail look like a roadmap. |
| D2 | Sequencing is **three waves by risk-to-value**, not by item number: correctness-adjacent and small first, then the tagging/export features, then the two large ones. | DECIDED | B2, F-09 and A1 are bounded and each produces evidence a reviewer can check in one sitting; F-02 and F-08 are large and need the earlier items' test scaffolding (fingerprint clustering, measured DSP) to be worth starting. Starting with F-08 risks an unfinishable first item. |
| D3 | **B2 supports APEv2 containers (.wv/.ape/.mpc) first**, then Speex, then DSF — in that order, as separate steps. | DECIDED | `audio_suite_shared/tag_helper_apev2.py` already implements `APEv2Handler`, and `TagHandlerFactory` already maps `.wv`/`.ape`/`.mpc` to it (registered in 1.1.0). What is missing is the **scrubber's** raw-frame preserve/restore path, not a handler. This is materially smaller than the register's phrasing ("needs frame-level APEv2 handling") implied, and the three formats share one code path. |
| D4 | **F-01 extends `tag_field_updater`, and does not become a 31st tool.** | DECIDED | Its `core/mapping_engine.py` is already the suite's tag-value transformation host (`should_update_value`, `update_value`); a filename source is a new *input* to the same engine, not a new workflow. A new tool would cost the eleven registration steps for a mode. |
| D5 | **F-05/F-06 extend `library_stats`, and do not become a new tool.** | DECIDED | `library_stats/core/file_processor.py` already exports CSV (`export_csv`) from a scan that reads exactly the fields a playlist needs (path, BPM, key). Adding `m3u`/`html` and a Camelot column is a format addition to an existing report; the scanning, caching and reporting already exist. |
| D6 | **F-02 becomes a new tool** (`duplicate_finder`), with the full registration checklist budgeted. | DECIDED | It is a distinct workflow: fingerprint every file, cluster by distance, report and optionally quarantine — it never writes audio, and it needs fpcalc, which `library_stats` does not use. Burying it in the statistics tool would couple two different failure modes (a scan error vs a fingerprint error). The eleven steps are listed as a first-day deliverable so the cost is visible. |
| D7 | **F-08 is split into three sub-items and starts with declip.** | DECIDED | Declip has an objective target — reconstruct peaks and measure the distortion floor against a known-clipped reference — while de-reverb has no reference metric the suite could assert on, and spectral repair needs an interactive surface the suite does not have. Shipping the one that can be measured first keeps the item honest. |
| D8 | **A1's first deliverable is the measurement**, and the shipped arithmetic changes only if it fails. | DECIDED | `replaygain_analyzer/core/gain_calculator.py` uses duration-weighted energy (`10·log10(Σ 10^(Lᵢ/10)·dᵢ / Σ dᵢ)`), which is exact for equal gating and approximate otherwise. Writing a concatenated measurement and finding the approximation acceptable is a **valid outcome** and must be recorded as one. |
| D9 | **Items do not ride each other's release.** Each gets its own `CHANGELOG` entry under the version it ships in. | DECIDED | The 2.1.6 cut accumulated fifteen bullets across six items and became a release nobody had read as a whole — the risk D30 named. Grouping is what made that happen; per-item releases keep each one reviewable. |
| D10 | Feature work targets **2.2.0**; narrow extensions may ship as 2.1.x. | PROPOSED | F-01, F-02, F-05/F-06 and F-08 add capability (minor). B2, F-09 and A1 are bounded extensions or measurements and can ride a patch if their surface stays additive. |
| D12 | **F-10 (the audio-writer sweep) is admitted** into a capability plan, and its deliverable is a **lock**, not a bug list. | DECIDED | The normalise defect fixed on `dc1b3c5` was found by un-skipping a test, not by a sweep, and no test in the tree asserts any writer's output format — the case passed for a release because its test measured loudness only. It sits in Wave 1 because every later audio item (F-08, F-09) is safer behind it, and it is expected to end with **no code change**, which is A1's shape (D8) rather than a defect register's. |
| D11 | No item changes a **tag format** or a **file extension** the suite already writes without a migration note. | DECIDED | B2 adds containers the scrubber can *scrub*, not a new output format; F-09 changes a normalisation target, which is audio output — its bullet must say what a re-run does to an already-normalised file. |
| D13 | **F-10's sweep found one offender**, so it did not end as the no-code-change lock D12 expected. | DECIDED | Seven writers, seven decoded rows (44.1 kHz / stereo / 24-bit fixtures, deliberately none of the defaults). Six preserved the format; the shared pydub export path did not — pydub passes no sample-format argument, so FFmpeg's WAV/AIFF muxer wrote **16-bit PCM from a 24-bit source** while rate and channels survived. Fixed in `audio_suite_shared/audio_formats.py` (`source_bit_depth` / `preserve_depth_params`, applied by `get_export_args`), so `file_processor_base.py` and `audio_refinery/core/pipeline.py` inherit the pin. The lock's failure self-check reverts the normalise pin and requires the 192 kHz assertion to go red. |
| D14 | **F-09 exposes the ceiling as `--tp`/`--lra`** (GUI spinboxes beside them), defaults unchanged at −1.5 dBTP / 11 LU, and reports the **achieved** peak per file. | DECIDED | The default path is locked byte-identical by comparing the decoded output of an unset-parameter run against an explicit `-1.5/11` run — not by reading back the argument. The achieved peak comes from loudnorm's measured output, so a ceiling the encode could not reach is visible instead of assumed; the GUI warns above −1.0 dBTP rather than silently allowing a lossy re-encode to clip. A re-run to the same target stays inside the existing tolerance check and is **skipped**, so an already-normalised file is not re-encoded. |
| D15 | **B2 landed as three deliberate steps** (APEv2 `.wv/.ape/.mpc`, then `.spx`, then `.dsf`), with APEv2 values kept as the container's own objects and restored in place. | DECIDED | `_UNSUPPORTED_CONTAINERS` shrank from five extensions to `(".wma",)` and the test still asserts it is non-empty, so the remaining gap stays visible. The undo round trip is proved on a real `.wv`: tags restored through the preserved dict, and the decoded duration + per-channel RMS identical to before the scrub (a metadata-only operation must not touch samples). Restore mutates the loaded tags (`clear()` + `update()`) instead of rebinding, the same rule `AGENTS.md` records for FLAC. |
| D16 | **A1 adopted the one-pass concatenated album measure**; the duration-weighted formula remains only as the fallback. | DECIDED | The approximation failed D8's test. A 20 s −10 dBFS + 20 s −35 dBFS FLAC album measures **3.00 dB** apart (weighted +2.70 dB vs combined −0.30 dB), and a mostly-silent-tail album **2.33 dB** apart; both exceed ReplayGain's ±0.5 dB expectation, because the quiet track falls under the combined signal's relative gate. Cost is one extra full decode per album (the combined signal's length), run in the existing Phase-2 folder pass. `TestAlbumGainBenchmark` pins 3.00 ± 0.3 dB and asserts the tag on disk carries the combined value; the fallback path is separately asserted. |
| D17 | **Guide review is part of every item's definition of done**, and its outcome is recorded even when the answer is "unchanged". | DECIDED | Wave 1's first pass updated the normalizer, scrubber and CLI-reference guides with their items, but left `ReplayGain_Analyzer_User_Guide.md` describing the duration-weighted album gain A1 had just replaced — in four places (Setup, Two-Phase Processing, the values table, Troubleshooting) — and `docs/index.md` still listing this plan as unstarted. Both surfaced only when the question was asked, which is the exact silent drift this row closes: §2 rule 3 makes the review mandatory before "done", §6 gains a Guides line per wave, and "no guide describes this behaviour" must be written down rather than assumed. That pass also proved the check is mechanical: `utilities/build_user_guides.py --check` reports 32/32 artefacts current after the regeneration, so a stale `.docx` cannot hide behind an edited Markdown source. The rule itself now lives in `AGENTS.md`, *User Guides Follow the Change*, so it binds work outside this plan too; §2 rule 3 keeps only the per-item recording requirement. |
| D18 | **Every guide was swept against the code**, and a lock now ties a stated format count to the shared set. | DECIDED | Method, in this order: every guide's `--flags` checked against the live click commands (136 options; no guide names a flag the CLI lacks); every guide default stated beside a flag compared with click's own default (no disagreement); all 51 quoted `[STATUS]` tokens checked for existence in first-party Python; every extension enumeration compared with the tool's own supported set; and the prose of the recently touched tools read for claims none of those checks measure. **Four guides carried drift**, three of them since 1.1.0 widened `SUPPORTED_EXTENSIONS` to fourteen: `Album_Art_Normalizer` and `AlbumGenre_Tagger` still said "nine" audio formats (three passages), `ASX_Playlist_Extractor` said nine extensions, and `Lyrics_Manager` documented status labels `[LIKE]`/`[ALREADY]`/`[NO MATCH]`/`[PLAIN]` that the code never emits — it emits `[TAGGED]`/`[SKIPPED]`/`[DRY RUN]`/`[ERROR]`. Before either tool's guide claimed the five new containers, artwork embedding and album-genre writes were proved on real `.wv`/`.ape`/`.mpc`/`.spx`/`.dsf` fixtures and read back through mutagen. `tests/test_guide_format_counts.py` then holds any "N suite formats/containers/extensions" claim against `len(SUPPORTED_EXTENSIONS)`, with an explicit two-entry exemption list for the deliberate subset counts (the normaliser's seven encoders, the scrubber's five added containers); it fails when a count regresses, when an exemption goes stale, and when the walk finds no claim at all. |
| D19 | **The sweep was extended to GUI defaults and behaviour claims**, and its mechanical classes are now one lock. | DECIDED | GUI defaults exist only in the Tk declarations for half the tools, so they were read from `tk.*Var(value=...)`, the DSP slider specs and the settings models rather than from CLI options. Every claim checked **matched**: album-art sync 500 px / 0.85 / 800 / 10 s, art normaliser 800×800, Refinery declick 0.31 / width 2 ms / trim −50 dBFS / fades 500-1000 ms / target −16 / tolerance 0.5, noise reduction harmonics 1-20 / Q 1-100 / gate 3 dB, pop/click 0.01-0.40 / 1-10 ms, silence trimmer −50 dB / 500-1000 ms, the enhancer's thirteen DSP slider ranges, converter −16 LUFS, fingerprinter 30 s / 0.5 / 120 s, BPM's 40-300 and 60-400 bounds, lyrics timeout 10 s and undo retention 50. Quoted artifact names (logs, sidecars, configs, the CLI schema) all exist in code. The drift was **worker counts**: fourteen guides said "four worker slots" (or "four workers by default"), while every tool's grid is `DEFAULT_MAX_WORKERS` — one per logical CPU, capped at eight — which is **8 on this host**, so the claim was false on any machine with more than four CPUs. The guides now state the rule instead of a number. `tests/test_guide_claims.py` (the format-count lock, renamed) holds all five mechanical classes — format counts, worker counts, flags, status tokens, artifact names — each with a non-vacuity floor and exemption lists that must still match a real claim; reintroducing "four worker slots" was verified to turn it red naming the file and line. |
| D20 | **The repository has one documentation tree**, `documentation/`, holding `documentation/docs/` (the Sphinx site) and `documentation/user_guides/` (the shipped guides and their Markdown sources). "Which documents does this change touch?" is answered by walking that directory instead of remembering two roots. | DECIDED (user, 2026-10-29) | 315 path references in 53 files named `user_guides/` and 232 in 35 named `docs/`; the historical `PLAN_*`/`AUDIT_*`/`CHANGELOG.md` records were left untouched, because they describe the tree as it was (a plan is a record, not an instruction). The move is not a rename: **the depth is load-bearing.** The pages sat one level from the root and now sit two, so every link to a repository-root file gained a `../` (`documentation/docs/index.md` → `../../README.md`), and because `myst_all_links_external` suppresses the warning a wrong one would otherwise be silent. The publish root therefore mirrors the checkout too - pages at `<out>/documentation/docs/`, guides at `<out>/documentation/user_guides/`, root documents at `<out>/` - or every such href would escape the artifact; `tests/test_docs_build.py`'s ~240-link self-containment walk is what proves it, and it passed unchanged apart from its paths. Three further contracts moved with it: `conf.py`'s `ROOT` is `parents[2]` (a `parent.parent` would point at `documentation/` and break autodoc for every documented module), `open_help` resolves `documentation/user_guides/individual_programs/<tool>/` at runtime for the Help button, and mypy's exclusion stayed **narrow** (`^documentation/user_guides/` + `^documentation/docs/_build/`) because excluding the whole tree silently dropped `conf.py` from the gate - 551 files became 550, which is how it was caught. The two generator-backed artefacts were re-rendered and triaged by zip entry: exactly `word/document.xml` (the logging guide's footer) and `ppt/slides/slide25.xml` (the closing slide's paths) changed, so no external-editor drift. **Supersedes** the applied-path model in `PLAN_docs_consolidation.md` §4/§5; that plan is complete and is not edited. `AGENTS.md` now states the rule as one directory walk, and `tests/test_docs_formats.py`'s format whitelist governs every tracked file under `documentation/`, so a new subdirectory there is covered without editing the test. A follow-up, `30c9ba2`, renamed the five walk-exclusion sets that still named the retired roots — a set naming a directory that no longer exists excludes nothing — and `audio_suite_shared/tests/test_platform_support.py` now records why its entry exists. |
| D21 | **Wave 1 ships as 2.1.7, and the cut carries two bullets that belong to no item.** | DECIDED | This settles §7's version question in D10's favour: F-10, B2, F-09 and A1 all ride one patch, because each is bounded, additive and already gated. B2's objection (it changes what a tool advertises, which some would call minor) does not survive the alternative: a five-container discovery change alone would leave the scrubber's other two items unreleased for no gain. Two bullets are release-level rather than item-level and are recorded as such - the guide-drift corrections D17-D19 found, and the single documentation tree D20 - since D9's per-item rule governs items, not corrections to documents. The gate ran on the bumped tree and is recorded in §6, so the cut is not a claim: `release.py` promotes the changelog, re-locks, re-renders the seven version-labelled guides (each verified by zip entry, `word/document.xml` only - the subtitle, not external-tool drift) and fails on any gate step. |
| D22 | **The gate's log is readable while it runs**: every progress line is flushed and every gate child runs with `PYTHONUNBUFFERED=1`. | DECIDED | The 2.1.7 cut was launched from a background shell into a log, and Python block-buffers a redirected stdout, so the run arrived in a few 8 KiB chunks: the log read as stuck at 14% for most of its 21 minutes, and `[START]` lines surfaced *after* the output they announced. Flushing the parent alone is not enough (a buffered marker still misreports the order) and unbuffering the children alone is not either (their output overtakes the marker), so both halves are pinned in `TestTheGateStreamsItsProgress`: every gate child receives the variable, and `[START] pytest` is readable from a second handle *while pytest runs* - asserted against a real redirected file, because `capsys` captures regardless of flushing and would pass either way. This lands after the tag, so `tests/test_release_notes.py` re-baselines to `534fb86` with `Changed in 2.2.0` (D10's next release) rather than filing the work under a release it is not in. |

---


## 4. Items

Sizes follow the audit's scale: **S** ≤ a day, **M** a few days, **L** a week or
more, **XL** open-ended.

Each item's *Files* list is a starting point, not a limit. By §2 rule 3 the
user guide(s) of every tool the item touches are in scope even when the list does
not name them, and the rendered `.docx` is regenerated rather than hand-edited.

### Wave 1 — bounded, evidence in one sitting

#### F-10 — no audio writer may leave the output format to a default (S)

**Status:** DONE — `tests/test_audio_writer_format.py`; found and fixed the
shared pydub depth loss (D13).

*Current state.* `audio_normalizer` handed the output's sample rate, channel
count and bit depth to FFmpeg's defaults, so every normalised file was resampled
to `loudnorm`'s internal 192 kHz and 16-bit audio was widened to 24 bits — and on
FFmpeg builds after 8.0 the same defaults made the stage **fail**
(`invalid block size: 384000`). Fixed on `dc1b3c5` by pinning the source's rate
and FLAC's depth and capping FLAC frames. Nothing stops the next writer from
making the same choice, and no test asserts any writer's output format: the
normalise case passed for a release precisely because its test measured loudness
and nothing else.

The other writers, as read at `9790778` rather than assumed:

| Writer | How it encodes | Output format today |
|---|---|---|
| `audio_normalizer/core/normalizer.py` | FFmpeg argv | pinned on `dc1b3c5` |
| `audio_enhancer/core/ffmpeg_io.py` | FFmpeg argv | already passes `-ar`/`-ac` on decode (:206) and encode (:294) |
| `audio_suite_shared/cue_split.py` | `-c copy` (:147) | no re-encode; preserved by construction |
| `audio_suite_shared/audio_conversion.py` | NumPy, `sample_width` = "keep source depth" | preserved by construction |
| `pop_click_remover/core/declicker.py` | pydub segment built from `audio.frame_rate`/`sample_width` | preserved by construction |
| `noise_reduction/core/noise_reducer.py` | ditto (:207, :237, :292, :325) | preserved by construction |
| `audio_refinery/core/pipeline.py` | `audio.export` / `ffmpeg_write` on the decoded segment (:507-:510) | carried rate and channels, **lost a 24-bit source's depth** through the shared pydub exporter — pinned in F-10 (`get_export_args` now emits the source's PCM codec) |

So the expected result is **no further offenders**, and that is a valid outcome
(D8): the deliverable is the lock. A writer whose output legitimately differs —
a conversion target, a deliberate depth reduction — declares the difference in
this table with its reason instead of being exempted silently.

*Change.* One test module that takes every writer above and writes a real file
whose rate, channel count and bit depth are deliberately **not** the values a
tool would otherwise pick (44.1 kHz / stereo / 16-bit), decodes the result, and
asserts all three are unchanged — plus the measured loudness where the writer
normalises. The writer list is pinned and asserted non-empty, so a new writer
cannot appear without a line here (`AGENTS.md`, "a verification harness that
cannot fail").

*Acceptance.*
- Every row of the table has a test that **decodes** the written file and
  compares rate, channels and sample width with the source, not a field the
  writer just set.
- The lock proves it can fail: reverting the normalise pin (`_preserve_args`
  returning `[]`) turns it red on the 192 kHz assertion.
- Each row is accounted for: either asserted unchanged, or listed with the
  reason its format intentionally differs.

*Files:* one test module beside the existing writer suites (root `tests/` is
allowed to be cross-cutting); `audio_normalizer/core/normalizer.py` only if the
sweep finds something.
*Risk:* the lock is only as good as its fixtures — a source already at 48 kHz
/24-bit would pass whichever choice the tool made, which is why the fixtures are
deliberately not the defaults.

#### B2 — the scrubber cannot see APEv2 containers (M)

**Status:** DONE — `.wv/.ape/.mpc` (APEv2), `.spx`, `.dsf`; evidence in D15
and §6.

*Current state.* `metadata_scrubber/core/scrubber.py`'s `_LOADERS` table is the
only source of truth for both discovery (`SUPPORTED_EXTENSIONS`) and loading, and
it lists nine containers — no `.wv`, `.ape`, `.mpc`, `.spx`, `.dsf`. The comment
above it is explicit that they stay out until "a frame-level APEv2 handler exists
for that restore logic", because `_collect_tags_to_preserve` captures actual
`APIC`/`SYLT`/`USLT`/`TPE2`/`TXXX` frames and `_restore_tags` puts those same
objects back. A WavPack or APE library is therefore invisible to the scrubber:
not scrubbed, and — since 2.1.6's R-05 fix — not reported as unreadable either.
Fixtures already exist: `tests/data/{silence-44-s.wv, mac-390-hdr.ape,
mac-396.ape, mac-399.ape, click.mpc, empty.spx, with-id3.dsf, without-id3.dsf}`.

*Change.* Extend the preserve/restore path to be container-aware: for APEv2,
preserve the item dictionaries that carry our tags (replaygain, key, BPM,
artwork) and re-apply them after the scrub, mirroring the FLAC rule in
`AGENTS.md` — mutate the loaded tags in place, never rebind, because a rebind is
silently discarded by some containers. Add `.wv`/`.ape`/`.mpc` to `_LOADERS`
with the same loader `TagHandlerFactory` uses (`APEv2Handler`'s underlying
`mutagen` class), then `.spx` and `.dsf` as separate steps.

*Acceptance.*
- A real `.wv` file with tags is discovered, scrubbed, and its tags are gone when
  re-read through a **fresh** handler — and the audio decodes to the same
  duration and per-channel RMS as before the scrub (a metadata-only operation
  must not touch samples).
- The exclusion test at `metadata_scrubber/tests/test_scrubber.py:2071`
  (`_UNSUPPORTED_CONTAINERS`) shrinks deliberately, one format per step, so the
  remaining gap stays visible instead of becoming an empty tuple nobody notices.
- A scrub-and-undo round trip on `.wv` restores every preserved tag (the
  `AGENTS.md` FLAC trap, verified on a real file rather than a fake).

*Files:* `metadata_scrubber/core/scrubber.py`, `metadata_scrubber/tests/test_scrubber.py`.

*Risk:* APEv2 items are byte-limited (a huge embedded cover may be refused);
splitting the artwork item is the fallback, and the test must assert what
happens rather than assuming success.

#### F-09 — the true-peak ceiling is hard-coded at −1.5 dBTP (S)

**Status:** DONE — `--tp`/`--lra` in CLI and GUI; evidence in D14 and §6.

*Current state.* `audio_normalizer/core/loudness.py:55` and
`audio_normalizer/core/normalizer.py:133` both interpolate the literal
`TP=-1.5` into the `loudnorm` filter, so every delivery target gets the same
ceiling. `LRA=11` is fixed the same way.

*Change.* One configurable ceiling (and LRA), defaulting to the current −1.5 so
existing behaviour is unchanged unless asked, surfaced in the CLI, the GUI and
(reportedly, for review) the true-peak headroom actually achieved per file.

*Acceptance.*
- A file normalised with `--tp -1.0` decodes with a measured true peak ≤ −1.0 dBTP
  and > −1.5 dBTP on a fixture that the old ceiling limited (the difference must
  be audible in the measurement, not asserted from the argument).
- The default path is byte-identical to today's output on the same fixture
  (a regression lock, not a description).

*Files:* `audio_normalizer/core/loudness.py`, `normalizer.py`,
`audio_normalizer/app.py`, `audio_normalizer/cli.py`, tests beside each.
*Risk:* a ceiling above −1.0 can clip on lossy re-encode; the GUI must warn
rather than silently allow it.

#### A1 — album gain is an approximation nothing has measured (M)

**Status:** DONE — benchmark measured, concatenated measure adopted; evidence in
D16 and §6.

*Current state.* `replaygain_analyzer/core/gain_calculator.py:41` computes album
loudness as duration-weighted energy. The plan that shipped it
(`PLAN_audit_2026-10-24_remediation.md` D1) states outright that this is exact
for equal gating and an approximation otherwise, and defers "the one-pass
concatenated album measure" as an accuracy benchmark. The existing test
`test_album_tag_matches_concatenated_measurement` compares against a
concatenated measurement for one fixture, which is the right shape but not a
study.

*Change.* Build the benchmark first: a fixture set with deliberately uneven
gating (quiet intro, loud chorus, a silent tail, a track whose gating differs
from its neighbours), measure each album both ways, and record the delta in dB.
Then decide: keep the approximation (with the measured bound documented and
asserted), or adopt the concatenated route (at the cost of a second full decode
per album).

*Acceptance.* A test that states the measured worst-case delta for the fixture
set and fails if it grows; if the arithmetic changes, the old and new values for
every fixture are in the plan's record, and the change is justified by that
table rather than by preference.

*Files:* `replaygain_analyzer/core/gain_calculator.py`,
`replaygain_analyzer/tests/`, new fixtures under `tests/data/`.
*Risk:* none to audio if the approximation is kept; if it is replaced, the cost
is a full extra decode per album — measured before adoption, per
`AGENTS.md`'s no-unmeasured-speedup rule inverted.

### Wave 2 — tagging and export features

#### F-01 — tag from filename, with action groups (L)

*Current state.* `tag_field_updater` transforms field *values*
(`core/mapping_engine.py`: `should_update_value`, `update_value`) but nothing
parses a filename into fields. The audit calls this "the single biggest
tagging-workflow gap" (§9.3, F-01), because a library whose only metadata is in
its filenames cannot be cleaned without a spreadsheet.

*Change.* Add a filename **source** to the existing engine: an ordered list of
patterns (`%artist% - %title%`, `%track%. %artist% - %title%`, with a
disc/track prefix variant), tried in order, each capturing named fields; then
the existing transformation rules apply, then the existing writer. A dry run
must print the parsed result per file. Action groups (a named set of
pattern + rules) are what make this repeatable, and they belong in
`audio_suite_config.json` via `suite_config` — **not** a new JSON file
(`AGENTS.md`, *Shared Config Pattern*).

*Acceptance.*
- Pattern parsing is a pure function with a table of realistic filenames,
  including the ones that must **not** match (a title containing " - " must not
  be split into artist and title when the pattern's field order says otherwise).
- End-to-end through the real writer on a real file: a dry run writes nothing
  (bytes unchanged, verified by hash) and a live run writes exactly the parsed
  values, read back through a fresh handler.
- A pattern that would overwrite a non-empty tag requires the existing
  "only fill blanks" switch to be off explicitly.

*Files:* `tag_field_updater/core/mapping_engine.py` (new parsing module beside it),
`tag_field_updater/app.py`, `tag_field_updater/cli.py`, `suite_config` keys, tests.
*Risk:* silent mis-parses are the failure mode — a wrong split writes wrong tags
and the file looks tagged afterwards. Hence the dry-run default and the
negative-case table.

#### F-05 / F-06 — playlist, CSV/HTML export and Camelot notation (M)

*Current state.* `library_stats/core/file_processor.py:772` exports CSV from a
`StatsReport`; that is the report's aggregates, not a per-file export a player
could read. There is no M3U, no HTML, and no Camelot mapping anywhere in the
tree (`grep -i camelot` finds nothing), although `key_detector` already emits
conventional key names ("C", "Am") from `key_engine.py`.

*Change.* One export surface on the scan: `--export {m3u,csv,html}` with a column
set, plus a Camelot column option. Camelot is a pure mapping from the existing
key spelling (8A/8B style, with enharmonic handling for the flatter spellings
`key_engine.py` deliberately prefers).

*Acceptance.*
- Camelot mapping is a table test over every key the detector can emit, both
  spellings, including the enharmonic pairs (G#/Ab, D#/Eb, A#/Bb) — the
  `key_engine.py` comment says major and minor are intentionally mapped
  differently, so a single chromatic table is wrong.
- An exported M3U opens with the right `#EXTM3U` header and one absolute path
  per file, in playlist order; the HTML file is self-contained (no external
  assets) and escapes a filename containing `<`, `&` and a non-ASCII character.
- The CSV path keeps `export_csv`'s existing contract (the current tests must
  pass unchanged) — the new columns are additive.

*Files:* `library_stats/core/file_processor.py`, a new
`library_stats/core/playlist_export.py`, `library_stats/cli.py`, `app.py`, tests.
*Risk:* path encoding in M3U on Windows (a playlist written with `\` is rejected
by some players); the test must assert the separator deliberately rather than
inherit whatever the host does.

### Wave 3 — large

#### F-02 — duplicate detection and merge (L)

*Current state.* `audio_fingerprinter` already computes Chromaprint
fingerprints through the committed `fpcalc.exe`, and
`audio_fingerprinter.core.acoustid_client.resolve_best_match` already contains
the near-tie rule from `AGENTS.md`. Nothing clusters a *local* library by
fingerprint; the suite can say "these two files are the same recording
according to AcoustID", not "these 40 files are 12 recordings".

*Change.* A new `duplicate_finder` tool: fingerprint (or reuse cached
fingerprints — a cache is needed or a large library re-runs fpcalc every time),
cluster by fingerprint distance with a threshold that is **measured on fixtures**
rather than picked, and report clusters with quality discriminator (bitrate,
sample rate, duration, tags). Merge is **not** in the first version: the tool
reports and can move duplicates to a quarantine folder, and deleting audio is
never automatic.

*Acceptance.*
- A fixture set with known duplicates — the same recording at two bitrates, an
  edited version that must **not** cluster, two different recordings that share
  a fingerprint prefix — clusters exactly as declared, with the threshold and
  the measured distances recorded.
- Quarantine moves a file and leaves the original byte-identical (hash-checked);
  a dry run moves nothing.
- The registration checklist is complete: manifest, card, CLI, arg builder,
  dependency graph, driver state, launcher with the pre-flight guard, user guide
  plus rendered `.docx`, `testpaths`/coverage, tests, callback contract.

*Files:* new `duplicate_finder/` package, `audio_suite_shared/tool_plugin.py`,
`master_driver/` (four registration points), `pyproject.toml`, user guide.
*Risk:* the expensive one is the **cache** — without it the tool is unusable on
a real library, and with it the tool inherits the staleness question R-13 just
answered for `library_stats`. Reuse the stamp rule; do not invent a second one.

#### F-08 — restoration: declip first, then de-reverb, then spectral repair (XL)

*Current state.* `noise_reduction` and `pop_click_remover` cover noise and
clicks; there is no declipper, no de-reverb and no spectral repair. The audit
rates this XL and calls it the gap to RX/Acoustica/SpectraLayers.

*Change, split into three sub-items, shipped separately:*

1. **F-08a — declip (M).** Reconstruct clipped peaks; measure THD and peak
   level against a known-clipped reference. Acceptance is the measurement: a
   clipped sine at −0.1 dBFS must come back with its harmonics reduced and its
   peak restored, and a clean file must be returned **unmodified** (hash-equal
   when the detector finds no clipping — a false positive that processes clean
   audio is the defect to avoid).
2. **F-08b — de-reverb (L).** No reference metric exists, so the acceptance is a
   synthetic room impulse response: convolve a dry signal, attempt removal, and
   assert that the measured DRR (direct-to-reverberant ratio) improves by a
   stated margin while the dry file returns unchanged.
3. **F-08c — spectral repair (XL).** Needs an interactive surface (select a
   time/frequency region); the GUI contract applies — off-thread work, results
   marshalled with `root.after`, and no `after` from a raw worker thread
   (`AGENTS.md`, *GUI Callback Contract*). Not started until a/b have a measured
   baseline to compare against.

*Files:* new `restoration/` package (a/b), GUI surface for c.
*Risk:* these algorithms can make audio **worse** while looking successful, which
is why every sub-item's acceptance decodes the output and measures it, and why a
no-op on clean input is an assertion rather than a nicety.

---

## 5. Sequencing and release map

| Wave | Items | Ships as | Why this order |
|---|---|---|---|
| 1 | F-10, B2, F-09, A1 | 2.1.7 patch (F-10 first; B2 needs a deliberate version note; A1 is a measurement) | Each is bounded, each produces one checkable artefact, and B2 closes a capability gap in a tool users already run. F-10 goes first because F-09 edits the same filter string and would otherwise be verified against an unlocked parameter set. |
| 2 | F-01, F-05/F-06 | 2.2.0 | User-visible features; F-01 needs a dry-run default that deserves its own release note and guide. |
| 3 | F-02, F-08a → b → c | 2.2.x, one per sub-item | Large; each needs the scaffolding the earlier waves produce. |

`F-05`/`F-06` are grouped because they share the export surface; everything else
is deliberately one item per release (D9).

---

## 6. Verification record

**Wave 1 — F-10, F-09, B2, A1.** Commits `5d4ab22` (F-10), `6642d41` (F-09),
`8890b73` (B2), `c6f54dc` (A1) and `6a4be7a` (guides) on `main`, based on
`9790778` (after the 2.1.6 cut `0556069`) and following the documentation move's
walk fix `30c9ba2`. The gate ran with the project's own
`.venv` interpreter (`.venv/Scripts/python.exe`, Python 3.14): the system Python
carries click 8.3.2, whose `No such option` wording differs from the 8.5.0 in
`uv.lock`, so `tests/test_cli_json_schema.py::…[doctor]` fails there against an
example that is correct for the pinned graph. That is the *Run From the
Project's `.venv`* rule, not a defect.

| Check | Result |
|---|---|
| compile | every tracked `.py` compiles (`git ls-files -z '*.py'` piped to `py_compile` — 946 files, exit 0). Plain `compileall -q -f .` exits 1 **only** on the untracked, stale PyInstaller runtime at `packaging/build/app/runtime/Lib/test/tokenizedata/`, whose files are deliberately invalid fixtures; no first-party file is involved. |
| ruff | `ruff check .` clean; `ruff format --check .` — 946 files already formatted. |
| mypy | bare `mypy .` — no issues in 551 source files. |
| bandit | 0 High / 0 Medium; 41 Low, all the documented `run_secure_subprocess` call sites. |
| pytest | bare `pytest` — **11 324 passed, 3 skipped, 35 deselected** in 23:05, exit 0, coverage 90.93%. |

Item evidence:

- **F-10** (`tests/test_audio_writer_format.py`): seven pinned writer rows, each
  writing a 32 kHz / mono / 24-bit source and **decoding** the output. Six
  preserved the format; the shared pydub exporter returned 16-bit WAV/AIFF, now
  pinned in `audio_suite_shared.audio_formats.get_export_args` (D13). The lock's
  failure check reverts the normalise rate pin in-process and requires the
  decoded rate to be 192 kHz.
- **F-09** (`TestDeliveryTargets`, `TestTruePeakCeilingOutcome`,
  `TestDeliveryTargetsApp`, `TestDeliveryTargetOptions`): a loud fixture
  normalised at −1.0 dBTP decodes at ≤ −1.0 and > −1.5 dBTP, at least 0.1 dB
  above the −1.5 run, and the reported peak matches the decoded one within
  0.1 dB. The omitted-target run is byte-identical to an explicit −1.5/11 run
  while a −1.0 run differs — that inequality is what gives the equality teeth;
  the first version of the test compared two explicit calls and could not fail,
  and was corrected in this change.
- **B2** (`TestAPEv2Scrub`, `TestDSFScrub`, the `.spx` scanner cases): a real
  `.wv` is discovered, scrubbed and re-read through a fresh handler; undo
  restores every preserved item; the decoded duration and per-channel RMS are
  unchanged; `_UNSUPPORTED_CONTAINERS` is `(".wma",)` and still asserted
  non-empty.
- **A1** (`TestAlbumGainBenchmark`): combined vs weighted album gain is 3.00 dB
  apart on the loud + quiet fixture (pinned ± 0.3 dB) and 2.33 dB on the
  silent-tail probe; the tag on disk carries the combined value, and the
  fallback route is asserted separately (D16).
- **Guides** (§2 rule 3): the normalizer, scrubber and CLI-reference guides were
  updated with their items; the ReplayGain guide (four passages describing the
  replaced duration-weighted album gain) and `docs/index.md` (this plan listed
  as unstarted) were corrected afterwards (D17). `build_user_guides.py --check`
  reports **32/32 artefacts current**, and `test_user_guide_hygiene`,
  `test_docs_build`, `test_docs_formats` and `test_cli_reference_hygiene` pass
  (47 tests). F-10's behaviour change has no guide passage describing bit depth,
  which is recorded here rather than left unstated. A later sweep of **all 32**
  guides against the code (D18) found four with pre-existing drift — three stale
  "nine formats" counts and one set of status labels the code never emits — and
  corrected them. A second pass (D19) read the GUI-side defaults from the Tk
  declarations and found fourteen guides stating "four worker slots" against a
  grid sized from the CPU count, which is eight on this host; those now state the
  rule. `tests/test_guide_claims.py` locks all five mechanical claim classes —
  format counts, worker counts, flags, status tokens and artifact names.
- **Misses the gate found, fixed in this change:** the guide lock's module
  carried no release note. The first full-suite run after the work was committed
  failed in `tests/test_release_notes.py`, which had been blind to the file
  while it was untracked; the note is in `6a4be7a`, and the scan now unions
  untracked files (`1510247`) - verified by an untracked probe module, which the
  test names and fails on.

**Documentation layout — the one tree (D20).** Commits `ad15a51`, `f3ee8b9`,
`1ce857c`, `efabe0f`, `82ce8c3` and the walk fix `30c9ba2` on `main`.

| Check | Result |
|---|---|
| compile | `compileall -q -f -x '(packaging|\.venv)' .` exit 0 (the unfiltered form still exits 1 only on the stale PyInstaller runtime's deliberately invalid fixtures, as recorded above). |
| ruff | `ruff check .` clean; `ruff format --check .` — 946 files already formatted. |
| mypy | bare `mypy .` — no issues in **551** source files, the same count as before the move (the exclusion was narrowed to keep `conf.py` in the gate). |
| pytest | bare `pytest` — **11 324 passed, 3 skipped, 35 deselected**, exit 0, coverage 90.93%; the ten document locks separately **83 passed**, and `test_docs_build` **9 passed** including the staged-tree link walk. That run covers the whole tree, so it is the same one the Wave-1 table above records. |

Evidence for the specific contracts this move could break:

- **Relative depth.** `documentation/docs/index.md` now links `../../README.md`,
  `../../CHANGELOG.md`, `../../CONTRIBUTING.md` and `../../packaging/…`;
  `documentation/docs/user/security.md` links `../../../SECURITY.md`. The docs
  build stays **warning-free** (`myst_all_links_external` means a wrong href is
  *not* a warning), so the proof is `TestPublishedTreeIsSelfContained`, which
  rebuilt the staged tree and resolved every internal link with nothing missing
  and nothing escaping.
- **Runtime.** `open_help` resolves the guide under
  `documentation/user_guides/individual_programs/<tool>/`;
  `audio_suite_shared/tests/test_platform_utils.py` (fixture roots updated) and
  `spectral_viewer/tests/test_app.py::TestGuide::test_help_guide_is_shipped` both
  pass against the real tree, so the Help button's path is not merely renamed in
  the message.
- **Artefacts.** `build_user_guides.py --check` — **32/32 current**, unchanged by
  the move because only paths moved. The one generator-backed artefact this change
  needs is the deck: it was regenerated and triaged by zip entry, and only
  `ppt/slides/slide25.xml` (the closing slide's paths) differs, with an identical
  entry set — content change, no external-tool drift. `LOGGING_SYSTEM_GUIDE.docx`
  is the other: its footer names its own generator, so it ships regenerated with
  the move (a separate commit), and its only differing paragraph is that footer.
- **Guides reviewed:** the pages that describe the layout itself were updated
  (`documentation/docs/index.md`, `documentation/user_guides/README.md`, README,
  CONTRIBUTING, SECURITY, AGENTS) plus the deck's closing slide. No per-tool
  guide claims a path under the old roots, so "no guide describes this change"
  applied to none of the 32; `tests/test_suite_docs_tool_coverage.py` walks the
  shipped tree and still resolves every artefact name the guides quote.
- **Self-inflicted defects, fixed in this change:** the bulk path substitution
  split four expressions across a newline (`ruff` refused to parse them — the
  *Never Lose a Rule to a Scripted Edit* failure mode, caught before any test
  ran); the first mypy exclusion dropped `conf.py`, caught by the file count; and
  `test_docs_index`'s guide check compared repository-relative paths against a
  page that must link `../user_guides/…`, so it now compares the href the reader
  actually gets.

**Release — the 2.1.7 cut (D21).** Commit `a6bf049` ("Cut 2.1.7") on `main`:
`pyproject.toml` and `uv.lock` at 2.1.7, `[Unreleased]` reopened with "Nothing
yet.", the promoted `## [2.1.7] - 2026-10-29` section, and the seven
version-labelled guides re-rendered. The gate below is the release script's own
(`uv run python utilities/release.py 2.1.7 --date 2026-10-29`), run against the
bumped tree rather than assembled from earlier runs.

| Check | Result |
|---|---|
| compile | `compileall` over the tracked tree, exit 0. |
| ruff | `ruff check .` clean; 946 files already formatted. |
| mypy | bare `mypy .` - no issues in 551 source files. |
| bandit | 0 High / 0 Medium, 41 Low (the documented `run_secure_subprocess` sites). |
| pytest | bare `pytest` - **11 324 passed, 3 skipped, 35 deselected** in 21:02, exit 0, coverage 90.93%. The same count as the pre-bump run, so the version bump changed no test's outcome. |

- **The two bullets that belong to no item** are in the section: the guide-drift
  corrections from D18/D19 (fourteen guides' worker count, three guides' format
  count, the Lyrics Manager's status labels) under *Fixed*, and the single
  `documentation/` tree from D20 under *Changed*. D9's one-bullet-per-item rule
  governs items; a document correction is recorded where a reader meets it.
- **The seven regenerated guides** were compared by zip entry against `HEAD`:
  identical entry sets and exactly `word/document.xml` differing, which is the
  subtitle "Version 2.1.7 - October 2026". No external-editor drift, so all
  seven are kept. `build_user_guides.py --check` had already reported 32/32
  current before the cut.
- **The cut was interrupted and resumed.** The first scripted run was killed
  mid-gate (14%), so no file had been verified; the second run reported `[SKIP]`
  for every file step - each is idempotent - and ran the gate from scratch. The
  one thing the interruption cost is that the guide verification above was
  repeated by hand against `HEAD` rather than trusted from the killed run.
- **Tag.** `v2.1.7` is annotated on the record commit that follows `a6bf049`,
  matching `v2.1.6`'s shape (tag on the record, not the cut).

**Post-release — the gate's log is readable while it runs (D22).** One commit on
`main` after `534fb86` (the `v2.1.7` tag): `utilities/release.py` flushes every
progress line and runs every gate child with `PYTHONUNBUFFERED=1`. The gate below
is `release.run_gate` itself, launched from a backgrounded shell with its output
redirected to a log - the exact arrangement whose buffering it fixes - under the
project's `.venv` interpreter.

| Check | Result |
|---|---|
| compile | `compileall` over the tracked tree, exit 0. |
| ruff | `ruff check .` clean; 946 files already formatted. |
| mypy | bare `mypy .` - no issues in 551 source files. |
| bandit | 0 High / 0 Medium, 41 Low (the documented `run_secure_subprocess` sites). |
| pytest | bare `pytest` - **11 326 passed, 3 skipped, 35 deselected** in 16:23, exit 0, coverage 91.01%. The two above 2.1.7's 11 324 are the new tests. The 1370 warnings are pre-existing third-party ones (1369 Sphinx `napoleon` `RemovedInSphinx11Warning` inside `test_docs_build`, 1 Click `isolated_filesystem` deprecation), not this change's. |

- **The gate was run twice, and the recorded one is the second.** The first run
  passed, then the compile step's batches were given the same environment so
  "every gate child" is literally true rather than an overstatement; the gate was
  re-run on the final tree instead of letting the record describe a state one
  keyword away from the commit. Both runs reported 11 326 passed / 91.01%.
- **Both halves verified, not just the mechanism.** The negative control removed
  one `flush=True` (`[START] pytest`) and the new test went **red**, reporting the
  marker absent while every earlier flushed line was present; the file was then
  restored and `sha256sum -c` confirmed it byte-identical, `__pycache__` cleared
  first so a stale `.pyc` could not vouch for the restored source. The positive
  control is the run above: the log carried `[START] ruff check`, `[START] mypy`,
  `[START] bandit` and its verdict line, and `[START] pytest` while the suite was
  still running, where the 2.1.7 run delivered the same text in a few 8 KiB
  bursts at the end.
- **Why `capsys` could not have proved it.** `capsys` captures whatever is
  written regardless of flushing, so a `capsys`-based assertion passes with or
  without the fix. The test therefore redirects `sys.stdout` to a real text file
  and reads it from a second handle *from inside the fake pytest call* - only
  bytes already flushed are visible there.
- **Guides reviewed:** no user-facing guide describes the release tool, and the
  gate's `[START]`/`[OK]` markers are not documented in the CLI reference (it
  documents the `audiosuite` commands, not `utilities/` scripts), so no guide
  changes. The change is recorded in `CHANGELOG.md` under `[Unreleased]` because
  it alters how a cut behaves for anyone running one; the file's own docstring
  carries the rationale.

---

## 7. Open questions

- *(Resolved by the 2.1.7 cut - D21.)* **Which version do the Wave-1 items
  actually ride?** D10 proposed 2.1.7 for all of them; B2 changes what a tool
  advertises, which some would call minor. Answered as 2.1.7 for all four.
- **Does F-02 need a shared fingerprint cache in `audio_suite_shared`, or its own
  SQLite file?** Its own file repeats R-13's stamp question; a shared cache is a
  bigger change but one rule. Decide at the start of that item, with the R-13
  stamp as the default.
- **Is de-reverb (F-08b) worth the cost?** The measured-improvement acceptance is
  achievable, but the fidelity bar for music (as opposed to dialogue) is high
  enough that a poor result may be worse than shipping nothing. Re-evaluate after
  declip's measurements.

---

## 8. Changelog mapping

One bullet per item, under the version it ships in — never a grouped block
(D9). Each audio-affecting bullet names the measurable change: F-09 states the
ceiling and what a re-run does to an already-normalised file; B2 states which
containers became scrubable and that a scrub remains metadata-only; F-08a states
the measured distortion improvement and that clean files are returned untouched.
F-10 has **no bullet unless it changes a writer's output**; if it does, the
bullet names the writer and the measured before/after format rather than saying
"fixed a resampling issue".

---

## 9. Risks and rollback

| Risk | Mitigation | Rollback |
|---|---|---|
| A capability that writes audio makes it worse and still reports success (F-08, F-09). | Acceptance decodes and measures the output; a no-op on clean input is asserted, not assumed. | Remove the stage from the pipeline; the file-level tests already prove the chain without it. |
| B2 widens discovery to containers the restore path handles badly, so a scrub loses tags on `.wv` rather than not seeing the file. | One format per step, each with a scrub-and-undo round trip on a real file; the exclusion list shrinks deliberately. | Drop that format's `_LOADERS` entry and restore its line in `_UNSUPPORTED_CONTAINERS` — the test makes the reversal explicit. |
| F-01 writes wrong tags from a mis-parse and the file looks tagged afterwards. | Dry run is the default; a negative-case table for filenames that must not match; "only fill blanks" is the default for non-empty tags. | The undo journal already exists for tag writes (`batch_undo`); the dry-run path means the blast radius is one explicit run. |
| F-02's threshold is picked to make the fixture set pass. | The threshold is measured on declared distances and recorded in the plan; the fixture set includes a near-duplicate that must **not** cluster. | Raise the threshold and re-record; the table shows what moved. |
| F-10's sweep passes because every fixture sits at the same defaults the tools would have picked anyway, so the lock certifies nothing. | Fixtures are deliberately 44.1 kHz/stereo/16-bit, the writer list is pinned, and the lock is proved able to fail by reverting the normalise pin. | No rollback: a test-only change. |
| A new tool ships through half the eleven registration steps (a missing card only logs, a broken Help button only warns). | The checklist is a first-day deliverable for F-02, and the full-suite gate is the arbiter — per-package runs cannot see registration mistakes. | Complete the missing steps; there is no "temporary" exception, because the failure is silent by design. |
