# PLAN — functional backlog (B2, A1, F-01, F-02, F-05/F-06, F-09, F-08, F-10, U1, U2, U3, U4, U5)

**Status:** **Waves 1, 2 and 3 complete** — Wave 1: F-10 `5d4ab22`, F-09 `6642d41`,
B2 `8890b73`, A1 `c6f54dc` and the guide sweep `6a4be7a`; Wave 2: F-01 and
F-05/F-06 in `da30298`, released as **2.2.0** (`00238e1`), pushed at
`3a32185` with the floor leg green (CI run `41060921137`); Wave 3: F-02
(Duplicate Finder) and F-08a (Restoration / Declip), cut as the **2.3.0** minor
off `0b83b3e` — the tip of the 2.2.1 window —
with the items' measured evidence, the guide sweep, the artefact triage and the
gate in §6. The work landed as two reviewable commits - the callback fix
`a93d11b` and the 2.3.0 feature release `adbd38d` - and was tagged `v2.3.0`
and pushed at `2403e2a`, with the floor leg green (CI run `41213423144`,
§6). The re-baselined
`tests/test_release_notes.py` (`Changed in 2.3.0`) is satisfied by those commits.
The maintenance cycle's **five** items are
**complete** and **released as 2.2.1** (`05edc6d`): **U1** (the Tag Field
Updater window, D28), **U2** (the change history split by audience, D29),
**U3** (that window's Run Controls strip and driver handshake, D33), **U4**
(conformance to the shared scaffold, its browse dialog and its run report,
D34) and **U5** (the Tag Editor window to the same standard, D35), with the
gate and item evidence recorded in §6.
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
| D10 | Feature work targets **2.2.0**; narrow extensions may ship as 2.1.x. | DECIDED — settled by the 2.2.0 cut (D27) | F-01, F-02, F-05/F-06 and F-08 add capability (minor). B2, F-09 and A1 are bounded extensions or measurements and can ride a patch if their surface stays additive. |
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
| D23 | **F-01 is a second *source* in `tag_field_updater`, and its parser types its fields instead of trusting the separators.** | DECIDED | As D4 planned, the filename source is a new input to the existing engine (`core/filename_patterns.py` parses, `core/filename_tags.py` writes through the shared editable-tag API), not a 31st tool. Three rules make a mis-parse impossible rather than merely unlikely, and the first two were forced by watching the first implementation fail: **numeric fields match digits only** (`track`/`disc`/`year`), because with text-typed fields `05 - Artist - Title` parsed as `disc="05", track="-"` under the space-separated disc/track pattern; **only the last placeholder is greedy**, so `AC - DC - Song` keeps `DC - Song` whole; and **an ambiguous pattern is refused at validation** (adjacent placeholders, a repeated field, an unknown name, a stray `%`), checked for the whole list before any file is touched, so a typo is a usage error instead of a plausible half-tagged library. The extension is stripped before matching, so `Pt. 2` is a title and not a suffix. |
| D24 | **Filename mode defaults to dry through click's parameter source, and `disc` joined the shared editable fields.** | DECIDED | The shared `--dry/--live` pair defaults to live and the slash mode depends on that, so "filename mode is dry by default" cannot be a second default on the same option: the command reads `ctx.get_parameter_source("dry_run")` and only switches to dry when the user passed neither side, printing why. The GUI reaches the same place differently — enabling the mode ticks Dry Run — because there the checkbox *is* the explicit choice. `disc` joined `EDITABLE_FIELDS` (with `TPOS`/`discnumber`/`disk`/`DISCNUMBER` mappings and one shared `_parse_number_pair`) so a parsed `%disc%` is not silently dropped; every format already had a disc *read*, only the write was missing, and the Tag Editor's UI and CLI keep their own field list, so nothing there changes. A parsed value goes through the existing slash rule for **genre only**: applying it to artist or title would rewrite `AC/DC` as `AC; DC`. Action groups live in `audio_suite_config.json` under `tag_field_updater_action_groups` (`utils/config.py`), never a tool-local file. The CLI JSON payload is unchanged — the per-file parse is text/log output, and the schema is locked, so a field is added only when a consumer asks for it. |
| D25 | **F-05/F-06 is one export surface on the existing scan, and its CSV is additive.** | DECIDED | `--export {m3u,csv,html}` plus `--export-path`, `--export-columns` and `--camelot`, all served by `library_stats/core/playlist_export.py`; `--export-csv`/`--export-json` keep working. `export_csv` **without** a column set still writes the original ten columns in the original order — pinned by `test_default_columns_are_unchanged` — and `--camelot` alone *appends* one column to that set rather than switching formats, which is what "the new columns are additive" has to mean for an existing consumer. Camelot maps major and minor separately over every emitted spelling and both enharmonics, passes an already-Camelot value through, and leaves `UNKNOWN_KEY` empty rather than inventing a wheel position. Playlist order is album artist → album → track → filename (a walk order shuffles an album; a missing track number sorts last because "unknown" is not "track 0"), paths are absolute with forward slashes on every host, and an unknown duration is `-1`. The HTML page is self-contained and escapes every cell. `--export-columns`/`--camelot` with `m3u` is a usage error rather than a silently ignored flag. The reader's `"Unknown"` sentinel is rendered as an empty *export* cell only — the aggregates keep the bucket they have always counted. |
| D26 | **The Tag Field Updater window's divergence from the suite layout is a queued maintenance item (U1), not part of Wave 2.** | QUEUED (user, 2026-10-30) | Wave 2 changes what the tool *does*; its window has not been revisited since 1.0.1 except for the filename section F-01 just added, so a layout rebuild shipped beside that change would be reviewed as part of it. Recorded now because the gap is invisible to the gate: nothing asserts a window's shape, `BaseSuiteApp` accepts an empty `help_guide` silently (the inherited `_open_help()` simply returns), and the guide's *Using the GUI* section describes the flat layout as though it were the design. Evidence: `tag_field_updater/ui/app.py` references `styles.` zero times and `ttk.Notebook` zero times, while `ui_common.build_processing_tab`/`build_results_tab` and the `AnalysisAppBase`/`NoisePopToolApp` scaffolds supply both to every peer; `root.rowconfigure`/`columnconfigure` are absent, so the 850×950 default window cannot reflow and the content stays pinned top-left. The item carries the guide rewrite with it, because that section describes the layout being replaced panel by panel. |
| D27 | **Wave 2 ships as 2.2.0, and the cut is the release script's own run rather than a hand-edited bump.** | DECIDED (user, 2026-10-30) | Settles D10: both Wave 2 items add capability, and neither changes a tag format nor an output extension the suite already writes (D11), so a minor is the honest label; D22's gate-progress fix rides the same section as a *Changed* bullet because it landed after the 2.1.7 tag. `utilities/release.py 2.2.0 --date 2026-10-30` did the work: bumped `pyproject.toml`, re-locked `uv.lock` and read 2.2.0 back out of it, promoted `[Unreleased]` to `## [2.2.0] - 2026-10-30` and reopened it with "Nothing yet.", then regenerated the seven version-labelled guides. Those seven were judged the way the rule requires - identical zip entry sets, only `word/document.xml` differing, and its paragraph text moving from "Version 2.1.7 — October 2026" to "Version 2.2.0 — October 2026": a subtitle, not external-editor drift, so all seven ship as rendered. The script's gate on the bumped tree found 11 485 passed, 3 skipped, exit 0, coverage 91.08% - the same count as the pre-cut run, so the bump changed no test's outcome. |
| D28 | **U1 rebuilt the window on the shared pieces, and the guide's GUI section with it.** | DECIDED | The trap the item named was kept: `_on_filename_mode_toggled` is still the **only** place that checks Dry Run, so a setup/processing split cannot turn the default into a coin toss. The window is now a palette Help bar plus a three-tab notebook built by `ui_common.build_processing_tab` / `build_results_tab`, and `HELP_GUIDE` reaches `BaseSuiteApp`, so the inherited `_open_help` opens the guide `guide_to_program` maps. Rebuilding the result surface retired four Tk variables bound to no widget (`current_file`, `processed_count`, `updated_count`, `error_count`) in favour of the shared status line, stats label and per-file list; the completion summary moved from a modal to the Results tab, still naming the skipped and failed files, and `_record_run_note` still runs before any Tk update so the driver note cannot depend on a widget. The progress bar needed a total the scan does not publish, so `_count_audio_files` counts supported files first — a metadata-only second walk, cheap next to tagging, and no progress bar at all would have left the item's "no completion state" in place. `_log_path` now names this program's log (one literal, `PROGRAM_LOG_NAME`, with `PROGRAM_NAME` derived from it) so View Log opens something, and `_out_dir` is the folder scanned so Open Folder is not `Target folder not available`. The rules panel is the field list plus a pointer at the guide, which already carries those rules; the guide's *Using the GUI* section was rewritten tab by tab and re-rendered. Evidence: `TestSharedLayout` (three tabs, shared widgets, the Help button opening the registered guide, the entry and pattern box expanding and the box scrolling), the unchanged `TestFilenameModeDefaultsToDry`, and `tests/test_guide_claims.py`, which found `tag_field_updater.log` documented but never written until the name became a code literal. |
| D29 | **U2 splits the change history by audience, and the boundary is a lock rather than taste.** | DECIDED | The 227 bullets in 18 released sections were reclassified by **subject**, not wording: 169 stay in `CHANGELOG.md` (a tool's behaviour, a flag or default, a supported format, an error message, a workflow step, a measured speed or size difference, or a released document's content) and 58 move to `TECHNICAL_CHANGELOG.md` (the gate, CI, tests, tooling, behaviour-neutral refactors, dependency bumps and documentation tooling). The move was scripted, not retyped, so no sentence differs; the three cross-references that pointed at a moved bullet now name the file it lives in. Two bullets that genuinely mixed the audiences were **split rather than moved**: the ML extra's lead-in states the opt-in install a user sees while the `real_ml` marker detail became a technical bullet, and the BPM noise guard now opens on its user outcome ("no longer refuses genuine music as noise") with the calibration below it. `tests/test_changelog_format.py` parameterises the existing format lock over both files and adds `TestChangelogAudience`: a bullet's bold lead-in may not use a developer stem (test, pytest, gate, workflow, ruff, mypy, coverage, benchmark, lint) or `CI`, with one reason-carrying allowlist entry — Audio Refinery's *integrity gate*, which is a stage name and not the release gate. The lock is proved able to fail by a **test** that feeds it the two bullets the split exists for (2.2.0's release-gate bullet and 2.1.7's Refinery-tests bullet), not by a one-off run. `utilities/release.py` promotes both files in one cut and treats the technical one as optional (`promote_changelog(..., require_entries=False)`), so a release with no developer-facing change adds no heading there instead of failing the cut, while `CHANGELOG.md` still refuses an empty section. Both files are staged by `utilities/build_docs_site.py` so `documentation/docs/index.md`'s link resolves in the published artifact, and the mapping rule lives in `AGENTS.md`, *Change History Follows Its Audience*. |
| D30 | **The U1 review found the progress bar measured two different things, and the unit was fixed at the denominator.** | DECIDED (review, 2026-10-30) | D28 sized the bar with `_count_audio_files`, which counted only the extensions `TagProcessor` supports, while the value fed to it was `ProcessingStats.processed_files` — incremented for **every** file the walk visits, including the ones `process_file` skips for an unsupported extension. A folder holding cover art, notes or cue files beside a few tracks therefore read as complete while most of it was still unvisited, and the bar could not report the run's own count. The count is now `_count_scanned_files`: every file the walk will visit, the same unit the scan reports. `test_the_total_is_the_unit_the_scan_counts` pins the two numbers to each other on a real walk (2 audio + 2 non-audio files, `total == processed_files == 4`), which the old count would have failed 4 ≠ 2; the guide's Processing-tab sentence now names files rather than supported audio files and its `.docx` was re-rendered. Evidence: `tag_field_updater/tests/test_app.py` (277 passed for the package), `build_user_guides.py --check` 32/32 current, bare `ruff check .`/`ruff format --check .` and bare `mypy .` clean. |
| D31 | **The U1 review's remaining gaps are design work, and U1 is not closed by them.** | RECORDED (review, 2026-10-30) | Read against the suite rather than by impression, the rebuilt window still differs from its peers in one structural place and three smaller ones, and none is a defect, so this pass neither fixes them nor restates U1 as done. **(a) No Run Controls strip.** `DriverControlsPanel` is on 18 of the 19 tools the basesetupframe refactor counted, `cd_ripper` being the last (`PLAN_basesetupframe_refactor.md` Phase 0); Tag Field Updater was never in that count, which is the gap, and it instead hand-builds `path_row` plus a Dry Run checkbox, so the driver's mode is shown as a different control, the orchestration states are invisible, and `set_driven(True)` never runs — a driven run leaves the directory and mode editable while the batch blocks on this window's exit (`BatchOrchestrator._launch_standalone` → `process.wait()`). **(b) The driver's start/end flags are accepted and ignored.** `utils/cli_args.py` parses `--start/--no-start/--end/--no-end`, `master_driver/runner/arg_builder.py` never emits them for this tool (`["tag_field_updater"]` is `[path, mode_flag]`), and `main()` auto-starts whenever it has a directory and never sets `auto_end`, so the Utility tab's Auto Start is not honoured and Auto End cannot close the window (peers do `root.after(2000, root.destroy)`). **(c) Setup-tab conventions.** It is not a `BaseSetupFrame` (or the peer `SetupTab` shape): accent-coloured title against the suite's `FG_MAIN`, a mid-tab Start beside Stop rather than the full-width `height=2` primary button, no `Configuration` group, and a bespoke action-group row with `ttk.Button`/`simpledialog` instead of the shared preset row and `save_preset_dialog`. **(d) Browse is the raw dialog.** `browse_directory()` calls `filedialog.askdirectory()` directly, so no initial directory, no `load_last_directory()` restore and no `save_last_directory()`, unlike `UIHelperMixin._browse_folder_standard`. Also recorded: the worker thread calls `root.after` from a raw `threading.Thread`, which `AGENTS.md` (*GUI Callback Contract*) prohibits; the app is outside the shared `run_*` callback contract (`tests/test_callback_payload_contract.py` does not list it), so no lock would catch a payload drift, and `self.stats`/`self.scanning` are dead state. Evidence: `audio_suite_shared/ui_driver_controls.py`, `audio_suite_shared/ui_common.py` (`BaseSetupFrame`), `metadata_scrubber/ui/setup_tab.py` (nearest peer), `master_driver/runner/arg_builder.py` (`tag_field_updater`/`tag_editor`), `master_driver/batch_orchestrator.py::_launch_standalone`, `documentation/user_guides/individual_programs/tag_field_updater/Tag_Field_Updater_User_Guide.md` (Quick Start still names Browse...; *Using the GUI* has no Run Controls paragraph because there is no strip). |
| D33 | **U3 adopts the Run Controls strip and makes the driver's start/end flags real, with the strip's Mode as the only dry/live writer.** | DECIDED (user, 2026-10-30) | Supersedes D31 (a) and (b) and the Setup-tab half of (c); D31 (d) still stands. The tab is now a `_SetupFrame(BaseSetupFrame)`, so the title, the source row, the Mode combobox, the inert Clear Logs/Parallel display and the full-width start button come from the same code every peer uses. `dry_run` was a second variable for the same decision, so it is gone: `run_mode` ("Dry Run"/"Live Update", the driver's own strings) is the single value, the mode combobox is its only widget, and `_on_filename_mode_toggled` remains the only place that forces Dry Run — `main()`'s argv pre-fill writes the mode the driver passed, which is not a second rule. `driver_locked` is `was_launched_from_driver()` when argv was parsed, so a driven window's source/Mode/Browse are disabled and the run uses the arguments the driver sent. The flags were already parsed and never used, so the strip would have been a display that lied: `arg_builder.py` now emits `[path, mode_flag, start_flag, end_flag]` (the Utility tab's Auto Start/Auto End), `main()` starts only when `--start` was passed, and `finish_scanning` closes the window with `after(2000, destroy)` when `--end` is set — the batch's `_launch_standalone` blocks on this process, so that is the difference between an unattended batch completing and waiting forever. The window now opens in Dry Run, matching the strip's first mode and every peer, instead of standalone live. Evidence: `TestRunControlsStrip` (real window: `DriverControlsPanel`, mode values, shared source var, standalone editable, driven locked), `TestDriverHandshake` (argv fills the strip; `--start` starts once, `--no-start` starts nothing), `test_auto_end_closes_the_window`, `TestFilenameModeDefaultsToDry` (the dry rule, unchanged in intent, now on the mode value), and `test_runner`'s two new flag pairs. Guide's Quick Start and Setup sections rewritten, `.docx` re-rendered. |
| D34 | **U4 conforms the Tag Field Updater to the shared scaffold, and the run leaves a report in the scanned folder.** | DECIDED (user, 2026-10-30) | Supersedes D31 (d) and closes D31's callback-contract note: U3 made the strip real but left every other seam the tool's own, and the gap the user saw was the run log — peers write `<prefix>_dry_run_log.txt` / `<prefix>_sync_log.txt` into the folder they scanned and View Log opens it, while this tool wrote no per-file record at all, so the detail existed only in `logs/tag_field_updater.log` and the Results tab pointed there. The window is now an `AnalysisTagToolApp` with `ui/setup_tab.py` / `ui/processing_tab.py` / `ui/results_tab.py` (the layout 25 of 30 packages use), the browse button is `_browse_folder` (initial directory from the field, `save_last_directory`, restore on launch), and `cli_args.parse` reads the positional handshake (`mode_idx=2, start_idx=3, end_idx=4` — this enrich tool's `[path, mode, start, end]` prefix, the slots `album_genre_tagger` reads) instead of scanning tokens, so a shifted argv fails like its peers instead of reading as `--dry`. The scan starts through `core.processor.run_scan`, the `run_*` entry point taking the three callbacks, which sizes the progress bar from the file count, builds the per-file lines (`[UPDATED]` / `[WOULD UPDATE]` / `[UNCHANGED]` / `[SKIP]` / `[NO MATCH]` / `[ERROR]`) and publishes `updated` / `audio_files` beside the shared counters; the shared completion handler writes the report to `tag_field_updater_dry_run_log.txt` or `tag_field_updater_sync_log.txt` in the scanned folder and View Log opens that path. Three deliberate deviations. (1) The completion handler is `_finish_run`, not an override of `_on_complete`, because this tool's payload carries two counts the base never learns and a required field added to the supertype's signature is a type error — the wiring lambda binds it and the cross-tool locks still resolve it; (2) `main()` applies the handshake only when `argv[2]` holds a driver mode token, so any other argv (a test runner's) is not validated as a folder and exited 1. (3) The strip's preset row is not wired: action groups (F-01) already are this tool's saved settings — a pattern list plus its write mode in `audio_suite_config.json` — so a second saved-settings row would duplicate the concept rather than adopt the convention. D31 (c)'s remaining point stands on that one row and nothing else: the action-group widgets are still the tool's own row, beside the shared skeleton rather than inside a preset row. The tool is now registered in `tests/test_callback_payload_contract.py` (`EXPECTED_TOOLS`), `tests/test_completion_seam.py` (`EXPECTED_REQUIRED`) and `tests/test_completion_payload_published.py` (`EXPECTED_PUBLISHERS`); `tests/test_pyw_launchers.py::_run_launcher` now purges cached tool modules and lands its stub on the module the launcher statically imports, because the payload locks import every GUI app in-process and the cached `tag_field_updater.ui.app` made the launcher test exercise the real window instead of its stub. Evidence: `TestRunReport` (both report names, `View Log` opens the path the run wrote), `TestCompletionSeam::test_the_real_run_drives_the_bound_handler` (the real `run_scan` into the bound handler, asserting the written report), `TestRunScan`/`TestLogLine`/`TestCountScannedFiles` in `test_processor.py`, `TestBrowseUsesTheSharedDialog`, `TestDriverHandshake`, and 405 passed across the package plus the three locks and the launcher suite. |
| D35 | **U5 brings the Tag Editor to the same standard: shared strip, shared tabs, positional argv, and a report per run.** | DECIDED (user, 2026-10-30) | The user asked for the same conformance the Tag Field Updater just received (D34), and the Tag Editor is the last window with the old shape: `grid()` into one frame, no notebook, no progress surface, `filedialog.askdirectory()` directly, and a processor the window called and read back instead of a `run_*` entry point. It is now an `AnalysisTagToolApp` with `ui/setup_tab.py` / `ui/processing_tab.py` / `ui/results_tab.py`, and its Setup tab is a `BaseSetupFrame`, so the Run Controls strip supplies the source row, the shared browse dialog, the Mode combobox and the driver's orchestration display; the grid (the tool's editing surface) is that tab's `_build_options`. Both run kinds go through the processor: `run_scan` for the load walk the START button starts, `run_apply` for Apply to Selection, Apply Bulk and Import CSV, each publishing the shared counters plus its own fields (`rows`; `results` / `changed` / `written`). Three decisions worth naming. (1) A load walk is not a dry run of an edit, so it writes `tag_editor_scan_log.txt` rather than posing as `tag_editor_dry_run_log.txt`; an apply writes the mode-named report, both into the folder the tool read, and View Log opens the latest. (2) An apply is a run, not a silent in-grid update: it moves to Processing, finishes on Results and writes its report, because that is the feedback loop every peer has and the alternative was the modal-and-status-line shape the rebuild removed. Its payload is counted per *file* (the unit the shared summary and progress bar use) while the report carries one line per *edit*. (3) `arg_builder` now emits `[path, mode, start, end]` for `tag_editor`, the contract `tag_field_updater` already had: with `[path, mode]` alone the strip's Auto Start and Auto End could never be true, which is the same inert-option class as a flag that reaches no write site. The completion handler is `_finish_scan` / `_finish_apply` bound by the wiring lambda, not `_on_complete` overrides, for D34's reason: their payloads carry fields the base never learns. The CSV row-error lines and summary rows are captured in `_pending_*` before the thread starts, so the completion signature stays the processor payload plus the report header rather than growing wiring-only parameters. Evidence: `tag_editor/tests/test_app.py` (constructor wiring, strip, load run through the real `run_scan` into the bound handler, apply runs through `run_apply`, CSV import/export, grid interaction, `TestCompletionSeam`), `TestRunScan`/`TestRunApply`/`TestStop` in `test_processor.py`, `test_cli_args.py`'s slot cases, and the three cross-tool locks at 18 tools. |
| D36 | **F-02 ships as the `duplicate_finder` tool: fingerprints clustered at a *measured* 0.10 threshold, keepers chosen by measured quality, and quarantine-with-undo instead of any delete.** | DECIDED | The threshold is a measurement, not a pick: on the declared fixture set the same recording as FLAC and as MP3 96/128/320 kbit/s measures **0.0000-0.0002**, while the nearest pair that must stay apart - two arrangements that share a 10 s intro - measures **0.1580**, so 0.10 sits between them with a ~490x margin below and 1.58x above. A pair is only compared when the durations agree within 2 s and the aligned overlap covers 0.6 of the longer fingerprint, and the alignment is searched over ±32 sub-fingerprint words (~4 s), because a four-minute track and a 30 s clip of it are not duplicates however close the bits are. The keeper is chosen by **measured quality** - lossless before bitrate, then sample rate, then length - and never by tags, which are exactly what a bad rip gets wrong. A live run *moves* the non-keepers into `duplicate_quarantine/` and records every move in `batch_undo`, so the operation is reversible; the kept copy is hash-checked byte-identical, a dry run moves nothing, and the walk skips the quarantine folder so a second scan cannot re-find what the first moved. Merge and deletion are **not** in this version (the item's own scope), so no run can lose audio outright. `audiosuite duplicates` publishes `groups`/`duplicates`/`quarantined` in its `--json` payload, declared in `audio_suite_shared/cli_schema.py`. Evidence: `test_clustering.py` (the declared fixture set and its negative pair), `test_file_processor.py` (quarantine, undo, keeper SHA-256, dry run, second scan), `test_fingerprint_cache.py` (the stamp), `test_app.py` (the window) and `test_cli.py` (payload and schema). |
| D37 | **F-08a ships as `restoration`'s declip: detection against the file's *own* peak, a plateau rule that rejects a merely curved peak, and spline reconstruction that is refused when it cannot beat the original.** | DECIDED | Measuring the ceiling against the file's own peak - not full scale - is what lets the tool find a limiter set at -1.9 dBFS without the user naming the number. Three checks keep a false positive out of a repair that would make clean audio worse: only samples at or above `0.98` x the file's peak are candidates; inside a candidate region only samples within 1e-4 of the region's highest magnitude form the plateau, so a curved peak (one sample at that height) yields a one-sample plateau and is rejected; and a run needs eight clean samples of context either side plus a reconstruction that rises above the plateau by 1e-3 and stays inside full scale. The plateau is rebuilt by cubic-spline interpolation through that clean context, whose natural overshoot *is* the restoration. **Measured** on a 1 kHz tone mastered to -0.1 dBFS and hard-clipped at 0.8 (a limiter ceiling): harmonic distortion falls from **-21.38 dB to -46.82 dB** and the peak returns from **-1.938 dBFS to -0.188 dBFS** against the original's -0.100. A run that cannot improve is counted skipped and left **byte-identical**, a square wave (flat by nature) is refused rather than rounded, a 0 dBFS hard clip whose true peak is unrepresentable is reported and left alone, and a second pass finds nothing because the result is capped at full scale. A clean file is not rewritten at all (hash and mtime asserted), the source's tags, rate and channels survive, and a 24-bit source stays 24-bit. Defaults **0.98 / 50 ms**, exposed as `--threshold`/`--max-run-ms`. Evidence: `test_declipper.py` (the THD and peak measurements, the skipped and refused runs, idempotency, 24-bit), `test_file_processor.py` (clean file untouched, tags, counts), `test_app.py` and `test_cli.py`. |
| D38 | **Wave 3 ships as 2.3.0, a minor, not the 2.2.x patch §5 predicted.** | DECIDED (user, 2026-10-31) | Both items add capability a user can run - two tools, two commands, two windows - so a patch number would misdescribe the release; the brief was explicit that this is new functionality rather than a fix, and Semantic Versioning agrees. `utilities/release.py 2.3.0 --date 2026-10-31` performed the cut on the tree: `pyproject.toml` bumped, `uv.lock` re-locked and read back (2.2.1 → 2.3.0), `[Unreleased]` promoted to `## [2.3.0] - 2026-10-31` in **both** changelogs and reopened with "Nothing yet.", and the seven version-labelled guides re-rendered. Those seven were triaged by zip entry the way the rule requires - identical entry sets, one differing entry (`word/document.xml`) and one changed paragraph in each, the subtitle "Version 2.2.1 - October 2026" becoming "Version 2.3.0 - October 2026" - so they ship as rendered rather than as external-tool drift. `CHANGELOG.md` carries the three user bullets (§8) and `TECHNICAL_CHANGELOG.md` the three developer ones (the two tools' measurement locks, the CLI-schema registration, the headless slot pool). The cut is committed as `adbd38d`, the 2.3.0 feature release, tagged `v2.3.0` (annotated; tag object `2c39b10` dereferencing to `2403e2a`) and pushed with `main`; §6's post-release block records the floor leg's verdict. |
| D39 | **F-02's fingerprint cache is its own SQLite file, with the R-13 ``(mtime, size)`` stamp rather than a second freshness rule.** | DECIDED | §7 asked the question and the answer is the item's own file: the fingerprint payload is ~700 bytes per file and grows with a library, while `library_stats`' cache is a tag-metadata store with its own schema and migration history - one table for both would make one tool's migration edit the other's. What must not fork is the **stamp**: mtime alone answers "cached" for a file replaced by a copy that preserved its timestamps, which is exactly R-13, so the cache compares ``(mtime, size)`` and fingerprints again when either disagrees. Connection creation is serialised by a module-level lock shared by every instance (a per-instance lock cannot serialise two connections to one file), a competing writer is waited out rather than raising `database is locked`, and `auto_vacuum=FULL` keeps a delete-heavy cache from growing for ever - the pattern `batch_undo` and `library_cache` already use. `AUDIOSUITE_DUPLICATE_CACHE` overrides the default path, so tests do not write the user's cache. Evidence: `test_fingerprint_cache.py` pins the stamp's negative case (same mtime, different size ⇒ fingerprint again), the round trip of every record field, and the environment override. |
| D40 | **A defect found while wiring F-02's window is fixed in two shipped tools: `root.after(0, fn, **kw)` raises inside the completion call.** | DECIDED (defect, fixed in this change) | `NoiseReductionApp` and `PopClickRemoverApp` forwarded the published completion payload as ``self.root.after(0, cast(Any, self._on_complete), **kw)``. `tkinter.Misc.after` takes positional arguments only, so the call raised `TypeError: after() got an unexpected keyword argument` **inside** the callback and a finished batch reported nothing - the same silent-report class as D112/D113 one layer lower. Both now bind the payload with `functools.partial`, and `tests/test_callback_payload_contract.py` gained `_after_calls_with_keywords`, which walks every first-party module for an `after(...)` call carrying keywords, plus `test_the_after_scan_flags_a_keyword_call`, which feeds it a keyword call and requires it to fail - a scan that cannot fail is worse than none (`AGENTS.md`, *Defects and failing checks*). The class is recorded here because nothing else would have caught it: the payload locks check the handler's signature, not how the payload reaches it. |

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

**Status:** DONE — the filename source in `tag_field_updater`
(`core/filename_patterns.py`, `core/filename_tags.py`, `utils/config.py`);
evidence in D23/D24 and §6.

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

**Status:** DONE — `library_stats/core/playlist_export.py`, the `--export`
surface, the GUI export dialog and the Camelot column; evidence in D25 and §6.

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

**Status:** DONE — `duplicate_finder/` with the measured 0.10 threshold, the
measured-quality keeper, quarantine + undo and its own stamp-checked cache;
evidence in D36 and D39, §6.

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

**Status:** **F-08a DONE**; F-08b and F-08c not started. Declip ships as
`restoration/`, with its THD and peak measurements in D37 and §6.

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

### Maintenance cycle — queued for the next one

Not capability work, and not a defect in a working feature: it is the window
itself, and the change history a user reads. Queued here so the gap is recorded
rather than rediscovered, and deliberately kept out of Wave 2, whose items are
about what the tool *does*.

#### U1 — the Tag Field Updater window does not use the suite's shared layout (M)

**Status:** DONE — rebuilt on the shared pieces, with its guide section rewritten;
evidence in D28 and §6.

*Current state.* `tag_field_updater/ui/app.py` builds its whole window by hand,
as one flat column of `ttk.LabelFrame`s, and it shares nothing with the other
tool windows:

- **No tabs.** Nearly every peer is either a `ttk.Notebook` with
  `" 1. Setup "` / `" 2. Processing "` / `" 3. Results "` — `metadata_scrubber`,
  `audio_normalizer`, `library_stats` and the rest via
  `audio_suite_shared.ui_common.build_processing_tab` / `build_results_tab` — or
  a subclass of the shared `AnalysisAppBase` / `NoisePopToolApp`, which build
  that same notebook for the tool. Tag Field Updater is neither: `setup_ui()`
  grids *Music Library Directory*, *Tag Fields to Update*, *Tag from Filenames*,
  *Progress*, *Statistics* and the buttons into one frame, so setup and result
  share a surface.
- **No progress surface.** There is no `ttk.Progressbar` and no per-file list,
  only three counters, so a scan of a large library shows no completion state
  and a file that fails is visible only in the modal shown at the end.
- **No Help, View Log or Open Folder button.** `BaseSuiteApp` is constructed
  without `help_guide=`, so the inherited `_open_help()` is a no-op even though
  `Tag_Field_Updater_User_Guide.docx` exists and is registered in
  `audio_suite_shared/platform_utils.guide_to_program`; the guide is reachable
  only from outside the tool.
- **Not resizable in practice.** `self.root` never gets
  `rowconfigure(0, weight=1)` / `columnconfigure(0, weight=1)`, so the 850×950
  default window opens with the content pinned top-left and empty space below and
  beside it; the directory `Entry(width=60)` and the pattern `Text(width=70)` never
  grow, so a deep library path is truncated rather than scrolled. The status line
  is a bespoke `ttk.Label` at the root's row 1 instead of the shared one the
  other windows drive.
- **No palette.** The module references `audio_suite_shared.styles` nowhere, so
  the accent-coloured Help bar and the `BG_LIGHT` tab frames every peer has are
  absent. The *Tag Fields to Update* panel is a static paragraph of rules that
  restates the guide — the document the Help button exists to open.

*Change.* Rebuild the window on the shared pieces rather than restyling it: a
`ttk.Notebook` with the three standard tabs, `ui_common.build_processing_tab`
(progress bar, per-file list, current-file line) and `build_results_tab`
(completion heading, View Log, Open Folder), the palette Help bar with
`HELP_GUIDE = "Tag_Field_Updater_User_Guide.docx"` passed to `BaseSuiteApp`,
grid weights so the window grows, and a scrollbar on the pattern box. The rules
panel shrinks to a short pointer at the Help guide instead of duplicating it.

*Acceptance.*
- The window is a three-tab notebook built through the shared builders, and a
  test asserts the tabs, the progress bar and that `help_guide` names the guide
  `guide_to_program` maps — so the Help button cannot become a silent no-op
  again.
- Existing behaviour is unchanged and still locked: filename mode still ticks
  Dry Run through `_on_filename_mode_toggled`, action groups still load and save
  through `suite_config`, the driver caveat note is still recorded, and the
  completion summary still names skipped files.
- A long path and a long pattern list are usable in the window (the entry and the
  box expand; the box scrolls) instead of being cut at a fixed width.
- `Tag_Field_Updater_User_Guide.md`'s *Using the GUI* section is rewritten to the
  tabs the window now has, and the `.docx` re-rendered — that section describes
  the flat layout section by section, so it goes stale the moment the window
  changes.

*Files:* `tag_field_updater/ui/app.py`, `tag_field_updater/tests/test_app.py`, the
user guide and its rendered `.docx`.
*Risk:* the one real trap is F-01's dry-run default. It is currently applied in
`_on_filename_mode_toggled`, and the rebuild must keep that the **only** place
that sets it — a setup/processing split invites re-running the check in the start
handler "for safety", and two places deciding the mode is how the default becomes
a coin toss (`AGENTS.md`, *GUI (Tkinter) Testing*, the construction-time-default
rule).
*Scope note:* `tag_editor/ui/app.py` is the other hand-rolled window: same flat
shape, and it too has no Help button (it does pass `help_guide`). It is **not** in
this item — the report is about Tag Field Updater, and widening a maintenance
cycle to two windows is a scheduling decision, not a detail of this one.

#### U2 — the changelog reports the suite, not the build (M)

**Status:** DONE — split into `CHANGELOG.md` and `TECHNICAL_CHANGELOG.md`, with a
lock on the boundary and both files promoted by the release tooling; evidence in
D29 and §6.

*Current state.* `CHANGELOG.md` is the suite's only change history, and it is
read by two audiences at once: someone deciding whether to upgrade a tool, and
someone asking what happened to the build. Both are handed the same list, and
the second audience's bullets sit between the first's. Two of them are in the
last two releases alone:

- *"The release gate reports its progress while it runs."* (2.2.0, *Changed*)
  ends by admitting it: "Developer tooling only: no analysis, tag write or audio
  output changed." A release note that has to say nothing changed for the user
  is a note for somebody else.
- *"Two Refinery tests are gated on a measured capability, not on `CI`."*
  (2.1.7, *Fixed*) changes how two tests decide to skip. It names the defect
  they went on to expose, which is worth telling, but no shipped behaviour
  moved — the user-visible half of that story is the 192 kHz bullet above it.

That matters because the same file is where a user looks up the defect they
just hit: a technical bullet between two they care about costs them a paragraph
of noise at exactly the wrong moment, and a reader scanning headings for "did
the thing I hit get fixed" cannot tell which sections apply to them. Nothing in
the tree separates the two audiences today. The header follows Keep a
Changelog, which has no notion of one, and the cut promotes whatever the
`[Unreleased]` section holds.

*Change.* Split by audience rather than by dropping detail. `CHANGELOG.md`
keeps only what a user can observe — a tool's behaviour, a flag or default, a
supported format, an error message, a measured speed or size difference — and a
new `TECHNICAL_CHANGELOG.md` beside it carries the rest: the gate, CI, tests,
tooling, behaviour-neutral refactors, and dependency bumps no output sees.
`CHANGELOG.md` gains one line pointing at the technical file, so the detail is
moved rather than lost, and §8's mapping rule states which file a bullet goes
to.

*Acceptance.*
- Every bullet in `CHANGELOG.md` names something a user can run or observe, and
a lock holds the boundary instead of taste. The proposed mechanism is a
developer-noun denylist over that file's bullets (test, pytest, gate, CI,
workflow, ruff, mypy, coverage, benchmark) plus a narrow allowlist for each
word that is legitimately user-facing. The lock must **fail on the two bullets
above before they move** — that is its proof it can see them — and pass once
they have.
- `utilities/release.py` promotes **both** files in one cut. It raises today
when `[Unreleased]` holds no entry (`_is_meaningful`), which would make a
release with no technical work *fail*; the technical file's empty section has
to be legal while its heading still reopens with the placeholder.
- `tests/test_changelog_format.py` locks the new file too — 88 columns, the
two-space hanging indent, no tabs, and a scan that asserts it saw the file and
its `[Unreleased]` heading. Parameterised over both files, not copied.
- The published site stays self-contained: `build_docs_site.py` stages
`CHANGELOG.md` through `STAGED_FILES` and `documentation/docs/index.md` links it
twice, so either the new file is staged beside it or it is deliberately left
out of the site — and if it goes under `documentation/docs/` instead it needs a
toctree entry, because the build fails on a page outside every toctree.

*Files:* `CHANGELOG.md`, a new `TECHNICAL_CHANGELOG.md`, `utilities/release.py`,
`utilities/tests/test_release.py`, `tests/test_changelog_format.py`,
`utilities/build_docs_site.py`, `documentation/docs/index.md`, `README.md`,
`AGENTS.md` if the mapping rule lands there too.
*Risk:* the rule is the easy half. The split needs a **reclassification pass
over the 216 bullets in 18 released sections**, or every release before the
next one still mixes the two audiences and the boundary stays invisible to
whoever reads 2.1.7 next — the same shape as a lock that cannot fail. The
judgement is the work; the denylist only stops it drifting back. The denylist
will also produce false positives in prose, so each allowlist entry needs its
reason recorded in the test, the way `test_test_file_naming.py`'s does.
*Scope note:* this governs the change history, not `AGENTS.md`'s "one
documentation tree" rule. A root-level `TECHNICAL_CHANGELOG.md` sits beside
`CHANGELOG.md` as shipped release data, which is not a second root of pages a
reader is meant to read; putting it under `documentation/` instead would keep
the tree's single root and change only the toctree and staging details.

#### U3 — the Setup tab adopts the shared Run Controls strip (S)

**Status:** DONE — the tab is a `BaseSetupFrame`, the strip owns the mode, and
the driver's start/end flags reach the run; evidence in D33 and §6.

*Current state.* U1 gave the tool the suite's tabs but not its control surface:
the source was a `path_row` and the mode a Dry Run checkbox, so a driven run
could not be locked, the driver's Auto Start/Auto End had no control to show, and
neither was honoured. `cli_args.py` already parsed `--start/--no-start` and
`--end/--no-end`, and the driver never sent them (`arg_builder.py` emitted
`[path, mode_flag]`), while `main()` started on any directory and never closed —
so the Utility tab's Auto Start was inert and an Auto End batch waited on a
window that would not close.

*Change.* `_SetupFrame(BaseSetupFrame)` supplies the title, the strip and the
full-width start button; `run_mode` is a `StringVar` bound to the strip's Mode
combobox and `_on_filename_mode_toggled` is still the only place that forces Dry
Run; the four handshake flags are emitted, displayed and honoured (Auto Start
gates the first scan, Auto End closes the window two seconds after the summary);
a driver launch locks the panel; the window opens in Dry Run.

*Acceptance.*
- A real window's Setup tab contains a `DriverControlsPanel` whose Mode values
  are the driver's own strings, and the start button is the suite's full-width
  one instead of a mid-tab button beside Stop.
- `driver_locked=True` disables the source entry, the Mode and Browse.
- `main()` with `--live --no-start --end --clear-logs --parallel-run` fills the
  strip and starts nothing; with `--start` it starts exactly once.
- `build_utility_args` emits the four flags, and `test_runner` pins both the
  false and true start/end pairs.
- Filename mode still forces Dry Run, through the same single site.
- The guide's Quick Start and Setup sections name the strip and the Mode, and
  the `.docx` is re-rendered.

*Files:* `tag_field_updater/ui/app.py`, `tag_field_updater/tests/test_app.py`,
`master_driver/runner/arg_builder.py`, `master_driver/tests/test_runner.py`, the
user guide and its rendered `.docx`, `CHANGELOG.md`.
*Risk:* the F-01 dry-run rule again — the mode moved from a checkbox to a
combobox, so the single writer becomes the mode variable, and the argv pre-fill
in `main()` must not be mistaken for a second decision point.
*Scope note:* `tag_editor` shares the old argument pair (`[path, mode_flag]`) and
its window still ignores the flags; it is not in this item.

#### U4 — the Tag Field Updater conforms in *all* respects, including its run log (M)

**Status:** DONE — the window is an `AnalysisTagToolApp`, the scan runs through
`run_scan`, and the run report is written into the scanned folder; evidence in
D34 and §6.

*Current state.* U1 and U3 gave the tool the suite's tabs and strip, and left
every other seam its own: the app derived from `BaseSuiteApp` rather than the
analysis/tag scaffold, `browse_directory()` called `filedialog.askdirectory()`
directly (no initial directory, no `load_last_directory()` restore, no
`save_last_directory()`), `cli_args.parse` scanned tokens instead of reading the
positional handshake every folder tool reads, and the scan was driven by the
window's own `_scan_thread`/`finish_scanning` rather than a `run_*` entry point.
The consequence the user hit: **no run log.** Peers write
`<prefix>_dry_run_log.txt` / `<prefix>_sync_log.txt` into the folder they scanned
and View Log opens it; this tool wrote no per-file record at all, so
`logs/tag_field_updater.log` (the diagnostic log) was the only place the detail
existed and the Results tab's View Log pointed at it.

*Change.* Move the window onto the pieces the majority of the suite uses: the
app is an `AnalysisTagToolApp` with `ui/setup_tab.py` + `ui/processing_tab.py` +
`ui/results_tab.py` (the layout 25 of 30 packages have), the browse button is
the shared dialog, the argv is read with `read_positional_handshake` at this
tool's own slots, and `core/processor.run_scan` is the entry point
(`on_progress` / `on_complete` / `on_error`) that builds the per-file report
lines and publishes the counts. The shared completion handler writes the report
to `tag_field_updater_dry_run_log.txt` or `tag_field_updater_sync_log.txt` in
the scanned folder, View Log opens that file, and the Results tab reports the
shared counters plus *Audio files* and *Files updated*.

*Acceptance.*
- A run leaves the report in the scanned folder, named for the mode, containing
the header, one line per file and the SUMMARY block; View Log opens that path
  on a real run.
- The window is registered in `tests/test_callback_payload_contract.py`
  (`EXPECTED_TOOLS`), `tests/test_completion_seam.py` (`EXPECTED_REQUIRED`) and
  `tests/test_completion_payload_published.py` (`EXPECTED_PUBLISHERS`), so a
  payload drift fails a lock instead of a finished run.
- Browse passes the current path as the initial directory and asks the shared
  helper to remember the folder.
- `main()` applies the handshake only when the argv has the driver's shape, so
  a stray argv (a test runner's own switches) is not read as a folder path.
- The guide's Processing, Results, Logging and Troubleshooting sections describe
  the shared surfaces and the run report, and the `.docx` is re-rendered.

*Files:* `tag_field_updater/ui/app.py`, `ui/setup_tab.py`,
`ui/processing_tab.py`, `ui/results_tab.py`, `core/processor.py`,
`utils/cli_args.py`, `tag_field_updater/tests/test_app.py`,
`tag_field_updater/tests/test_processor.py`, the three cross-tool locks,
`tests/test_pyw_launchers.py` (stub landing), the user guide and its `.docx`,
both changelogs.
*Risk:* the `run_*` seam is where the suite's two shipped callback defects came
from (D112/D113), so the handler signs the payload it is handed rather than a
subset; and the completion handler is **not** an override of `_on_complete` —
this tool's payload carries two counts the base never learns, and a required
field added to the supertype's signature is a type error (`_finish_run` is bound
by the wiring lambda instead).
*Scope note:* `tag_editor` had the same flat window and the same
`[path, mode_flag]` pair; it is U5, below.

#### U5 — the Tag Editor window conforms to the suite standard (M)

**Status:** DONE — the window is an `AnalysisTagToolApp` on the shared three
tabs and strip, both of its run kinds go through a `run_*` entry point, and each
run writes its report into the scanned folder; evidence in D35 and §6.

*Current state.* `tag_editor/ui/app.py` built its whole window with `grid()` in
one frame: no notebook, no progress surface, no Results tab, and a raw
`filedialog.askdirectory()`. The processor exposed `scan_directory` /
`apply_edits` as plain calls, so the window read their return values and drove
its own widgets, and no run left a record: a live apply's per-file outcome
existed only in `logs/tag_editor.log`. Its `cli_args.parse` scanned tokens, and
`arg_builder` emitted only `[path, mode_flag]`, so the strip's Auto Start and
Auto End could never be anything but off.

*Change.* Rebuild the window on the pieces the majority of the suite uses: an
`AnalysisTagToolApp` with `ui/setup_tab.py` + `ui/processing_tab.py` +
`ui/results_tab.py`, a `BaseSetupFrame` Setup tab whose Run Controls strip
supplies the source row, the shared browse dialog, the Mode combobox and the
driver's orchestration display, and the grid as that tab's tool-specific
options. The load walk starts through `core.processor.run_scan` and every apply
(selection, bulk, CSV) through `run_apply`, so both share the progress and
completion handlers; each writes its report where the tool read
(`tag_editor_scan_log.txt`, `tag_editor_dry_run_log.txt`,
`tag_editor_sync_log.txt`) and View Log opens the latest. The argv is read with
`read_positional_handshake` at `tag_field_updater`'s slots, and `arg_builder`
emits `[path, mode, start, end]` for this utility so Auto Start/Auto End are
honoured.

*Acceptance.*
- A load walk fills the grid and leaves `tag_editor_scan_log.txt` with the
  header, one `[READ]` / `[ERROR]` line per file and the SUMMARY block; an
  apply leaves the mode-named report with `[WRITTEN]` / `[WOULD WRITE]` /
  `[UNCHANGED]` / `[FAILED]` lines. View Log opens the file the last run wrote.
- The grid keeps its behaviour: a single-field edit, a bulk operation and a CSV
  import each reach the tag API, update the row and record one undo batch.
- Stop ends a walk after the file it is reading.
- The tool is registered in all three cross-tool callback locks.
- The guide's Quick Start, window, grid, Mode, run-report and Master Driver
  sections describe the rebuilt window, and the `.docx` is re-rendered.

*Files:* `tag_editor/ui/app.py`, `ui/setup_tab.py`, `ui/processing_tab.py`,
`ui/results_tab.py`, `core/processor.py`, `utils/cli_args.py`, `Tag_Editor.pyw`,
`master_driver/runner/arg_builder.py`, `tag_editor/tests/test_app.py`,
`test_processor.py`, `test_cli_args.py`, the three cross-tool locks, the user
guide and its `.docx`, both changelogs.
*Risk:* an interactive editor is not a scan-and-write pass, so the mapping is
deliberate — the load walk is the run the START button starts, and an apply run
reports the same way (Processing, then Results) rather than updating the grid
silently. The apply payload is counted per *file* while its report carries one
line per *edit*, because the shared summary and progress bar are file-based.

---

## 5. Sequencing and release map

| Wave | Items | Ships as | Why this order |
|---|---|---|---|
| 1 | F-10, B2, F-09, A1 | 2.1.7 patch (F-10 first; B2 needs a deliberate version note; A1 is a measurement) | Each is bounded, each produces one checkable artefact, and B2 closes a capability gap in a tool users already run. F-10 goes first because F-09 edits the same filter string and would otherwise be verified against an unlocked parameter set. |
| 2 | F-01, F-05/F-06 | 2.2.0 | User-visible features; F-01 needs a dry-run default that deserves its own release note and guide. |
| 3 | F-02, F-08a → b → c | **2.3.0**, a minor, carrying F-02 and F-08a together (D38); b and c remain unstarted | Large; each needs the scaffolding the earlier waves produce. |
| M | U1, U2, U3, U4, U5 | **2.2.1**, all in one patch — U1, U3, U4 and U5 are window-only, U2 changes the changelogs and the release tooling; none touches a tag or audio (D28/D29/D33/D34/D35) | Neither changes how the suite runs, so either can ride any 2.2.x slot. U1 rebuilds a window F-01 has just extended, so it is cheaper to review once that has settled. U2 is cheapest *before* the next cut: every release that ships while the two audiences are mixed adds more technical bullets to the file users read, and under U2's own rule the split is itself a technical change, so the release that lands it says nothing in `CHANGELOG.md`. |

`F-05`/`F-06` are grouped because they share the export surface; everything else
is deliberately one item per release (D9). U1–U3 share the `M` row because all
three are maintenance, **not** a version: U3 depends on U1's setup/processing
split and rides the same patch, while U2 is independent of both.

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

**Wave 2 — F-01, F-05/F-06.** Commit `da30298` on `main`, based on `1e999f2`
(D22's release-note baseline) and reviewed as one change. The gate below was run
on that tree with the project's own `.venv` interpreter (Python 3.14) and then
re-run once more on the exact tree the commit captures, after the guide and
reference edits it also carries:

| Check | Result |
|---|---|
| compile | `.venv/Scripts/python.exe -m compileall -q -f -x '(packaging|\.venv)' .` exit 0, no `Error compiling` line.  The bare form still exits 1 on the untracked PyInstaller runtime's deliberately invalid fixtures, so the exclusion has to be the unanchored `packaging|\.venv` alternation: the anchored `(^|/)(\.venv|…)/` form does **not** exclude a Windows path and re-admits the whole runtime. |
| ruff | `ruff check .` clean; `ruff format --check .` — 954 files already formatted. |
| mypy | bare `mypy .` — no issues in **555** source files (551 before; the four new modules are `core/filename_patterns.py`, `core/filename_tags.py`, `utils/config.py` and `library_stats/core/playlist_export.py`). |
| bandit | 0 High / 0 Medium; 41 Low, the same documented `run_secure_subprocess` call sites. |
| pytest | bare `pytest` — **11 485 passed, 3 skipped, 35 deselected** in 16:46, exit 0, coverage 91.08% (the floor leg adds `--cov-fail-under=75`, which the configured run already exceeds). The two packages the change touches alone are **606 passed**. |

Item evidence:

- **F-01** (`tag_field_updater/tests/test_filename_patterns.py`,
  `test_filename_tags.py`, `test_config.py`, the new classes in `test_app.py`
  and the CLI cases in `test_cli.py`): the parser's contract is a name table
  with its negative side - `AC - DC - Song` keeps `DC - Song` as the title
  (only the last placeholder is greedy), `Artist - Pt. 2.mp3` keeps `Pt. 2`
  (the extension is stripped before matching), and `05 - Artist - Title` cannot
  be read as `disc="05", track="-"` because numeric fields match digits only.
  An ambiguous pattern list (adjacent placeholders, a repeated field, an
  unknown name, a stray `%`) is refused for the **whole** list before any file
  is opened.  The writer is proved on a real `.flac`: a dry run leaves the
  file's bytes and mtime untouched and the live run that follows writes the
  parsed values, read back through a fresh handler; an existing value is kept
  by default, replaced only with `--overwrite`, and never rewritten when it
  already matches.  A parsed genre goes through the existing slash rule while
  `AC/DC` does not.  Action groups round-trip through
  `audio_suite_config.json` (save, load, replace, delete, and a malformed entry
  is skipped rather than guessed at), and the GUI tests assert that enabling
  the mode ticks Dry Run and that a start with an invalid pattern is refused
  before the scan.
- **F-05/F-06** (`library_stats/tests/test_playlist_export.py` and
  `TestExport` in `library_stats/tests/test_app.py`): all **24** Camelot
  positions are reachable, both spellings of each enharmonic pair agree, an
  already-Camelot value survives a second pass, and `UNKNOWN_KEY` stays empty
  rather than being given a wheel position.  The M3U carries `#EXTM3U`, one
  `#EXTINF` per file with an honest `-1` duration for an untagged file, and
  absolute forward-slash paths in album artist → album → track → filename
  order; the HTML page is self-contained (no `http`, `src=` or external asset),
  UTF-8, and escapes a tag value's markup and ampersands.  The CSV keeps its
  original ten columns in the original order unless a column set is asked for,
  and `--camelot` alone **appends** one column.  The GUI dispatches on the
  chosen extension - a `.m3u` target writes a playlist rather than a renamed
  CSV, which the dialog alone cannot guarantee because the name stays
  editable - and the Camelot checkbox reaches the HTML export in both
  directions.
- **Guides** (§2 rule 3): both tools' guides were read against the code and
  extended - a *Tagging from Filenames* section (patterns, what makes a name
  match, the dry-run default, only-fill-blanks, action groups, the genre-only
  slash rule) and, in Library Statistics, the four export shapes, playlist
  order, the Camelot table and column selection - plus the CLI reference's
  `tag-update`/`stats` sections and `documentation/docs/index.md`'s plan
  summary.  The filename-mode sample output was **replaced with the CLI's own
  output**, run against two real MP3s, after the first version of the guide
  showed `would write: … title` and `kept existing: title` on the same file -
  a state the code cannot produce.  `build_user_guides.py --check` reports
  **32/32 artefacts current** and the four document locks pass (46 tests).
- **Misses the gate found, fixed in this change:** `disc` joining
  `EDITABLE_FIELDS` (D24) turned two frozen locks red -
  `TestEditableTagFields::test_field_set_is_stable` and the APEv2
  `test_editable_tags_mapping` round trip - which is what those locks are for,
  so both were extended in lockstep rather than worked around.  The new HTML
  test asserted an escaped artist cell for a column set it had not requested:
  it proved escaping of a cell that was never written, and the fix was to
  request `artist` (the assertion now covers a rendered value).
  `tests/test_release_notes.py` named `tests/test_cli_reference_hygiene.py` as
  changed without a note, so the null-default phrase table's new entry is
  recorded in a `Changed in 2.2.0` paragraph, and ruff caught a duplicated
  `from __future__ import annotations` left by the rewrite of
  `tag_field_updater/cli.py`.  The full suite is what found the first three;
  the package runs were green throughout.

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

**Release — the 2.2.0 cut (D27).** Commit `00238e1` ("Cut 2.2.0") on `main`,
produced by `utilities/release.py 2.2.0 --date 2026-10-30` and not assembled by
hand: `pyproject.toml` and `uv.lock` at 2.2.0, `[Unreleased]` reopened with
"Nothing yet.", the promoted `## [2.2.0] - 2026-10-30` section, and the seven
version-labelled guides re-rendered. The gate below is that run, on the bumped
tree.

| Check | Result |
|---|---|
| compile | `compileall` over the tracked files, exit 0. |
| ruff | `ruff check .` clean; `ruff format --check .` - 954 files already formatted. |
| mypy | bare `mypy .` - no issues in 555 source files. |
| bandit | 0 High / 0 Medium, 41 Low (the documented `run_secure_subprocess` sites). |
| pytest | bare `pytest` - **11 485 passed, 3 skipped, 35 deselected** in 17:02, exit 0, coverage 91.08%. |

- **The seven regenerated guides** were compared by zip entry against `HEAD`:
  identical entry sets, and only `word/document.xml` differing - the subtitle
  "Version 2.1.7 — October 2026" becoming "Version 2.2.0 — October 2026" in each.
  No external-tool drift, so all seven are kept as rendered, and
  `build_user_guides.py --check` reports **32/32 current** afterwards.
- **The section's three bullets** are D9's per-item shape: one per Wave 2 item
  under *Added*, and D22's gate-progress fix under *Changed*. Nothing else was
  promoted, which is what "cut from the Unreleased section" has to mean - a
  bullet that was not there did not ship.
- **Tag:** `v2.2.0` is annotated on the record commit that follows `00238e1`, the
  shape `v2.1.7` set (tag on the record, not the cut).

**Post-release — the floor leg on the pushed tree (CI run `41060921137`).**
`main` was pushed at `3a32185`, the 2.2.0 record commit, together with the
annotated `v2.2.0` tag; `git ls-remote` reports `refs/tags/v2.2.0` as tag object
`093ce9c` dereferencing to `3a32185`, so the workflow ran on the tree the
release notes actually name, not on `00238e1`, the cut alone. All eight jobs
succeeded and the run completed in 31:26.

| Job | Result | Duration |
|---|---|---|
| Lint & Format | success | 9 s |
| Compile / Pre-flight gate | success | 9 s |
| CLI schema conformance | success | 7 s |
| Type Check | success | 58 s |
| Security Scan | success | 33 s |
| Docs locks (freshness & formats) | success | 1 m 4 s |
| POSIX smoke (Ubuntu) | success | 1 m 12 s |
| **Test (Python 3.11, the floor)** | **success** | **29 m 20 s** |

- **What this verdict rests on, and what it does not.** GitHub serves a run's job
  list and check-run conclusions without a session but gates the log text behind
  one, so this record rests on the floor leg's `conclusion: success` plus the
  artifacts it published - `cli-payloads`, and `docs-html` at 1.8 MB, both
  produced by steps that would be absent had their predecessors failed or been
  skipped. It does **not** quote the leg's own "N passed" line. That count is
  not missing from the record: the local run in the table above holds it
  (11 485 passed, 91.08%), and this leg's job is the interpreter graph below the
  dev host's 3.14, not the number. Stated plainly so a later reader does not
  mistake the absence for an unchecked step.
- **The only annotations are workflow-level.** Two Node.js 20 deprecation
  warnings name `actions/checkout@v4`, `actions/setup-python@v5` and
  `actions/upload-artifact@v4`. No test, step or first-party file is implicated,
  and they pre-date this release.
- **The cost budget is untouched.** `tests/test_ci_cost.py` prices a job against
  100 minutes; the floor leg used 29:20 and the whole push 31:26, against the
  160.9 billable minutes the three-leg matrix cost on the 2026-10-28 push
  (`AGENTS.md`, *The Python floor must honour its lockfile*). No `concurrency` or
  matrix change was needed to fit, which is what the once-on-the-floor decision
  bought.

**Maintenance cycle — U1 and U2.** The gate below ran on the tree this record
describes, with the project's own `.venv` interpreter (Python 3.14), after the
last edit to it.

| Check | Result |
|---|---|
| compile | `compileall -q -f -x '(packaging|\\.venv)' .` exit 0 (the unanchored alternation, because the anchored form does not exclude a Windows path). |
| ruff | `ruff check .` clean; `ruff format --check .` — 954 files already formatted. |
| mypy | bare `mypy .` — no issues in **555** source files. |
| bandit | 0 High / 0 Medium, 41 Low (the documented `run_secure_subprocess` sites). |
| pytest | bare `pytest` — **11 507 passed, 3 skipped, 35 deselected** in 36:00, coverage 91.10%. The one failure on the first run was the note lock reading this run's own log file — a scratch `pytest_*.txt`, which `.txt` classifies as code — so it was removed and `tests/test_release_notes.py` re-run green. The `docs-locks` set was also run on its own (41 passed, including the staged-tree link walk) before the full suite. |

Item evidence:

- **U1** (`tag_field_updater/tests/test_app.py`): `TestSharedLayout` asserts a
  real `ttk.Notebook` with the three standard tabs, that the Processing and
  Results tabs are the shared builders' widgets (`ttk.Progressbar`,
  `tk.Listbox`, the three labels), that the palette **Help** button opens a guide
  that exists at the path `open_help_guide` resolves AND equals `HELP_GUIDE`
  (so it cannot become a silent no-op again), and that the directory entry and
  pattern box expand with the window while the box scrolls. The locked behaviour
  is unchanged: `TestFilenameModeDefaultsToDry` passes untouched,
  `TestActionGroupsInTheGui` still round-trips through `suite_config`,
  `TestRunNote` still records the skipped and failed files for the driver, and
  the new completion path is asserted to name `Files skipped` with the counts on
  the Results tab. `_count_scanned_files` is tested for the nested/unsupported
  cases — and, after the U1 review (D30), asserted equal to the
  `processed_files` count a real scan produces, so the bar's maximum and its
  value cannot be measured in different units. Its total is asserted to be
  marshalled before the scan, so the progress bar's maximum is measured rather
  than invented.
- **U2** (`tests/test_changelog_format.py`, `utilities/tests/test_release.py`):
  the format lock runs over **both** files (column limit, tabs, trailing
  whitespace, hanging indent, non-vacuity), and `TestChangelogAudience` rejects
  a developer word in any user bullet's lead-in, checks that its single
  allowlist entry still matches a real bullet, and feeds itself the two bullets
  the split was made for. The release tooling is tested in both directions: both
  files promoted in one cut, a technical file with nothing to promote cuts
  successfully and is left byte-identical, and a user file with nothing to
  promote is still refused. `TestEndToEnd`'s second-run count moved from four
  `[SKIP]` lines to five **because** the technical file is now skipped too —
  the assertion records the new truth rather than being relaxed.
- **Guides** (§2 rule 3): U1 rewrote `Tag_Field_Updater_User_Guide.md`'s *Using
  the GUI* section tab by tab (setup, processing with the progress bar and file
  list, results with View Log / Open Folder) and re-rendered the `.docx`
  (`build_user_guides.py --check` reports **32/32 current**; the regenerated
  artefact differs from `HEAD` in `word/document.xml` only, with an identical
  zip-entry set, so it is a content change and not external-tool drift). U2 changes
  the change history itself: no per-tool guide describes it, so "no guide
  describes this behaviour" is the recorded answer, and the documents that do
  mention the changelog were updated — `README.md`, `documentation/docs/index.md`
  (both links), `AGENTS.md`'s new mapping rule, and the site's staged files —
  with `tests/test_docs_build.py`'s self-containment walk proving the new link
  resolves in the published tree.
- **Misses the gate found, fixed in this change:** `tests/test_guide_claims.py`
  was red on `tag_field_updater.log` — the guide names the log, the code built
  the name from an f-string, and the lock requires the literal — so the name
  became one code constant rather than the guide losing a useful line. The
  audience lock caught its own first draft too: a preamble sentence that began
  with `-` rendered as a list item and failed the hanging-indent lock, and one
  bullet whose lead-in ended in "opt-in tests" was split rather than
  allowlisted. `ruff format` reflowed four of the changed files; nothing else
  moved.

**Maintenance cycle — U3.** `pytest tests/ tag_field_updater/tests
master_driver/tests` (no coverage) reported **2 050 passed, 1 failed**: the
per-file note lock named `master_driver/runner/arg_builder.py` and
`master_driver/tests/test_runner.py`, both changed without a `Changed in 2.2.1`
note. Both notes were added (the code change itself was correct) and the lock plus
the affected suites then ran green — **1 095 passed** across
`test_release_notes`, the package, `master_driver` and the four
documentation/changelog locks. `ruff check .` clean, `ruff format --check .` 954
files formatted, bare `mypy .` no issues in 555 files, `bandit` 0 High / 0 Medium
/ 41 Low, `build_user_guides.py --check` 32/32 current with the `.docx` differing
from `HEAD` only in `word/document.xml` (identical zip-entry set).

**Maintenance cycle — U4 and U5.** The gate below ran on the tree this record
describes, with the project's own `.venv` interpreter (Python 3.14), after the
last edit to it.

| Check | Result |
|---|---|
| compile | `compileall -q -f .` exits 1 **only** on the untracked PyInstaller
runtime at `packaging/build/app/runtime/Lib/test/tokenizedata/` (deliberately
invalid fixtures, as recorded for Wave 1); the first-party tree compiles clean —
`compileall -q -f -x '(^|\)(\.venv|packaging|__pycache__)' .` exit 0. |
| ruff | `ruff check .` clean; `ruff format --check .` — 960 files already formatted. |
| mypy | bare `mypy .` — no issues in **561** source files. |
| bandit | 0 High / 0 Medium, 41 Low (the documented `run_secure_subprocess` sites);
the `Total issues (by confidence)` table reads 23 Medium / 18 High and is not the
severity gate. |
| pytest | bare `pytest` — **11 561 passed, 3 skipped, 35 deselected** in 18:24,
exit 0, coverage 91.29%. |

Item evidence:

- **U5 load walk** (`tag_editor/tests/test_app.py`,
  `test_processor.py::TestRunScan`): `start_processing` sets
  `tag_editor_scan_log.txt` and starts the worker; driving the real `run_scan`
  through `_run_scan` writes the report (`[READ]      a.mp3 (title='One')`,
  `SUMMARY:`, `Audio files: 1 of 2 files`) and schedules the grid fill, which
  then populates `_rows`.
- **U5 apply runs** (`TestApplySelection`, `TestApplyBulk`, `TestCsvImportExport`,
  `TestRunApply`): a selection becomes `FieldEdit`s (Clear sends `None`), the
  strip's Mode decides the report name, the worker writes through the tag API and
  the report carries `[WRITTEN] track.mp3: title 'Old' -> 'New'`; a refused write
  logs `[FAILED]` and leaves the row alone. Bulk counts are per file while the
  report is per edit.
- **U5 stop** (`TestStop`, `test_the_walk_fills_the_grid_and_writes_the_report`):
  a stop ends the walk after the file being read and a new scan clears the flag.
- **U5 argv** (`TestPositionalSlots`, `TestLooksLikeDriverArgv`,
  `master_driver/tests/test_runner.py::test_tag_editor_entry_present`): the
  parser reads `mode_idx=2, start_idx=3, end_idx=4` and the display pair from 5;
  a shifted argv fails the folder check instead of reading as a mode. The
  builder now emits `[path, mode, start, end]`, which its `[:2]` / `[-2:]`
  assertions still hold.
- **U5 locks**: the tool is in `EXPECTED_TOOLS`, `EXPECTED_REQUIRED` and
  `EXPECTED_PUBLISHERS` (18 tools), and `TestCompletionSeam` drives the real
  `run_apply` into the bound handler, asserting the written report.
- **Guides** (AGENTS.md *User Guides Follow the Change*): the Tag Editor guide's
  Overview, Quick Start, new *The Window* and *Run Reports* sections, the grid,
  Mode, CSV and Master Driver passages were read against the rebuilt window and
  rewritten; `build_user_guides.py --check` reports **32/32 artefacts current**.
  The Tag Field Updater's guide was reviewed too — no passage describes anything
  U5 touched, so it is unchanged apart from its U4 edit.
- **Misses the gate found, fixed in this change:** `tag_editor/tests/test_processor.py`
  carried no `Changed in 2.2.1` note, which `tests/test_release_notes.py` flagged
  once the full suite ran; the note was added and the lock re-run green. Two
  unused imports in the rewritten `test_app.py` were caught by `ruff check .`.

**Release — the 2.2.1 cut.** Commit `05edc6d` ("Cut 2.2.1") on `main`, produced
by `utilities/release.py 2.2.1 --date 2026-10-30` and not assembled by hand:
`pyproject.toml` and `uv.lock` at 2.2.1, `[Unreleased]` reopened with "Nothing
yet." in both change-history files, the promoted `## [2.2.1] - 2026-10-30`
sections, and the seven version-labelled guides re-rendered. The gate below is
that run, on the bumped tree.

| Check | Result |
|---|---|
| compile | `compileall` over the tracked files, exit 0. |
| ruff | `ruff check .` clean; `ruff format --check .` clean. |
| mypy | bare `mypy .` — no issues in 561 source files. |
| bandit | 0 High / 0 Medium, 41 Low (the documented `run_secure_subprocess` sites). |
| pytest | bare `pytest` — **11 561 passed, 3 skipped, 35 deselected** in 17:09, exit 0. |

- **The first cut the audience split ran through.** `TECHNICAL_CHANGELOG.md` was
  promoted in the same run and took its own `## [2.2.1]` heading, holding the two
  scaffold bullets that would have made the user file five bullets long before
  D29 — so this release is the split's own evidence, not only its description.
- **The seven regenerated guides** were compared by zip entry against `HEAD`:
  identical entry sets, and only `word/document.xml` differing — the subtitle
  "Version 2.2.0 — October 2026" becoming "Version 2.2.1 — October 2026" in
  each. No external-tool drift, so all seven are kept as rendered.
- **The section's four bullets** are the two windows' behaviour (D28/D33/D34 for
  the Tag Field Updater, D35 for the Tag Editor), which is what `CHANGELOG.md`
  records by subject; the two developer-facing statements behind them are the
  technical file's.
- **Tag:** `v2.2.1` follows the shape `v2.1.7` and `v2.2.0` set — annotated on
  the record commit that follows `05edc6d`, not on the cut itself. It was
  created on that commit and pushed with `main`; the post-release block below
  records the run it triggered.

**Post-release — the floor leg on the pushed tree (CI run `41136522813`).**
`main` was pushed at `27e6e84`, the 2.2.1 record commit, together with the
annotated `v2.2.1` tag; `git ls-remote` reports `refs/tags/v2.2.1` as tag object
`118a793` dereferencing to `27e6e84`, so the workflow ran on the tree the release
notes name, not on `05edc6d`, the cut alone. All eight jobs succeeded and the run
completed in 28:11.

| Job | Result | Duration |
|---|---|---|
| Lint & Format | success | 9 s |
| Compile / Pre-flight gate | success | 8 s |
| CLI schema conformance | success | 9 s |
| Type Check | success | 59 s |
| Security Scan | success | 36 s |
| Docs locks (freshness & formats) | success | 1 m 4 s |
| POSIX smoke (Ubuntu) | success | 1 m 16 s |
| **Test (Python 3.11, the floor)** | **success** | **28 m 8 s** |

- **What this verdict rests on, and what it does not.** GitHub serves the job
  list and check-run conclusions without a session but gates the log text behind
  one, so this record rests on the floor leg's `conclusion: success` plus the
  artifacts it published — `cli-payloads` (25 KB) and `docs-html` (1.8 MB), both
  live and both produced by steps that would be absent had their predecessors
  failed or been skipped. It does **not** quote the leg's own "N passed" line;
  that count is the local run in the cut table above (11 561 passed, 91.29%),
  and this leg's job is the interpreter graph below the dev host's 3.14.
- **The only annotations are workflow-level.** The Node.js 20 deprecation
  warnings name the same three actions (`actions/checkout@v4`,
  `actions/setup-python@v5`, `actions/upload-artifact@v4`) as last release and
  pre-date this one. The new entry is a **notice**, not a failure: the
  `ubuntu-latest` label is scheduled to migrate to Ubuntu 26 from 2026-10-19,
  and nothing in this release pins that image.
- **The cost budget is untouched.** `tests/test_ci_cost.py` prices a job against
  100 minutes; the floor leg used 28:08 and the whole push 28:11, against the
  160.9 billable minutes the three-leg matrix cost on the 2026-10-28 push
  (`AGENTS.md`, *The Python floor must honour its lockfile*).

**Wave 3 — F-02, F-08a.** One 2.3.0 minor (D38) on `main`, based on `0b83b3e`
(the tip of the 2.2.1 window), committed in two steps: the callback defect
`a93d11b` and the release itself `adbd38d`, with this record after them. It was tagged `v2.3.0` and pushed at `2403e2a`,
so the evidence is the gate below on that tree **and** the floor leg's
verdict in the post-release block at the end of this section.
`tests/test_release_notes.py` is re-baselined to
`0b83b3e` with `Changed in 2.3.0`, and the release commit carries the
**72** per-file notes the window already holds - every changed or added `.py`
and `.toml` in it. The gate below ran on that tree with the
project's own `.venv` interpreter (Python 3.14), on the second full-suite run:
the first one found 33 registration gaps, they were fixed, and the run was
repeated rather than assumed.

| Check | Result |
|---|---|
| compile | `.venv/Scripts/python.exe -m compileall -q -f -x '(packaging|\.venv)' .` exit 0, no `Error compiling` line. The bare form still exits 1 on the untracked PyInstaller runtime's deliberately invalid fixtures, and the anchored `-x '(^|/)(\.venv|\.git)/'` form does not exclude a Windows path - the unanchored alternation is the one that works (Wave 2's row already records this). |
| ruff | `ruff check .` clean; `ruff format --check .` - 1008 files already formatted. |
| mypy | bare `mypy .` - no issues in **591** source files (561 before the two packages). |
| bandit | 0 High / 0 Medium; 43 Low, against 41 before. The two new ones are `B105` on the `--threshold` option string in each new `utils/cli_args.py`, the class `bpm_analyzer`, `lyrics_manager` and `replaygain_analyzer` already carry; `run_gate.ps1` and `AGENTS.md` both define the bar as 0 High / 0 Medium. |
| pytest | bare `pytest` - **11 826 passed, 3 skipped, 35 deselected** in 18:03, exit 0, coverage **91.23%**. The two new packages alone are **240 passed**. |

Item evidence:

- **F-02** (`duplicate_finder/tests`, `master_driver/tests`, the cross-tool
  locks): `test_clustering.py` declares the fixture set and asserts the measured
  distances rather than a count of groups - the same recording as FLAC and as
  MP3 96/128/320 kbit/s clusters at 0.0000-0.0002, the two arrangements that
  share a 10 s intro stay apart at 0.1580, the 30 s clip of a track is not a
  duplicate of it (overlap gate), and a 4 s length difference is not compared
  (duration gate). `test_file_processor.py` proves the outcome on a real tree: a
  live run moves the extra copies into `duplicate_quarantine/` and leaves the
  keeper's SHA-256 **unchanged**, the undo journal restores every moved file, a
  dry run moves nothing, and a second scan does not re-find what the first moved.
  `test_fingerprint_cache.py` pins the `(mtime, size)` stamp (same mtime,
  different size ⇒ fingerprint again), the round trip of every record field and
  the `AUDIOSUITE_DUPLICATE_CACHE` override. `test_cli_args.py` reads the driver's
  option pairs and refuses an out-of-range threshold, `test_app.py` drives the
  window (strip, three tabs, probe, dry/live, the report it writes),
  `test_cli.py` locks the `--json` payload and the schema,
  `TestBuildUtilityArgs`/`TestDependencyGraph`/`test_app_state.py` cover the four
  driver registration points, and the launcher, card, guide and
  `testpaths`/coverage entries are all in place (the eleven-step checklist).
- **F-08a** (`restoration/tests`): `test_declipper.py` measures the audio, not a
  field - a known-clipped tone's THD falls 25.4 dB and its peak returns to
  -0.188 dBFS against the original's -0.100, a clean file's bytes **and mtime**
  are untouched, a square wave and an unrepresentable 0 dBFS clip are reported
  and left alone, a long flat top is skipped, a second pass changes nothing, and
  a 24-bit source stays 24-bit. `test_file_processor.py` runs the shared in-place
  workflow over a real folder (one repaired, one clean, tags and format kept,
  counts named) and covers the headless slot pool the technical changelog
  records. `test_cli_args.py`, `test_cli.py`, `test_app.py` and the four driver
  registration locks mirror F-02's.
- **D40's defect** was found here and fixed here: two shipped windows forwarded
  the completion payload through `root.after(..., **kw)`, which raises inside
  the callback; `tests/test_callback_payload_contract.py` now scans for that
  shape across the tree and has a test that proves the scan can fail.
- **Guides and generated artefacts** (§2 rule 3): two new guides
  (`Duplicate_Finder_User_Guide.md`, `Restoration_User_Guide.md`) were written
  and rendered, the CLI reference gained both commands' sections and was
  re-rendered, and the README, `documentation/docs/index.md` and the suite
  overview/deck were taken from the **manifest** - 32 tool rows, 33 registered
  guides - instead of being edited by hand. `build_user_guides.py --check`
  reports **34/34 artefacts current**. The deck was triaged by zip entry: four
  slides, all semantic (the count 30 → 32 on three of them and the two new rows
  on the feature slide), no external-tool drift.
- **The cut's seven version-labelled guides** were compared entry by entry with
  their `HEAD` blobs: identical entry sets, one differing entry
  (`word/document.xml`) each, and its only changed text the subtitle
  "Version 2.2.1 - October 2026" → "Version 2.3.0 - October 2026". Kept as
  rendered (D38).
- **Misses the first gate run found, fixed in this change:** 33 failures, all of
  them registration or derived-artefact gaps the new tools exposed - the README
  and docs-index row counts (regenerated from the manifest, then the two locks
  moved 30 → 32), `undo_gui._TOOL_DISPLAY_NAMES` missing both ids, the platform
  tier counts (30/29/28 → 32/31/30), the `--help` discoverability count, the
  usage-error table (both commands added), the CLI schema corpus and the
  committed `cli_schema.json` (re-recorded with
  `python -m tests.cli_schema_conformance --record`, not hand-patched), the
  doctor's healthy-install check (the editable distribution still said 2.2.1
  after the bump; `uv sync --all-extras` re-installed it as 2.3.0), and one mypy
  error - `duplicate_finder` declared `PRESET_KEY_PREFIX` as an instance
  variable over a `ClassVar` on the base. Every lock was updated in lockstep
  rather than relaxed; nothing was skipped, xfailed or suppressed.

**Post-release - the floor leg on the pushed tree (CI run `41213423144`).**
`main` was pushed at `2403e2a`, the Wave 3 record commit, together with the
annotated `v2.3.0` tag; `git ls-remote` reports `refs/tags/v2.3.0` as tag object
`2c39b10` dereferencing to `2403e2a`, so the workflow ran on the tree the release
notes name, not on `adbd38d`, the feature commit alone. All eight jobs succeeded
and the run completed in 30:16.

| Job | Result | Duration |
|---|---|---|
| Lint & Format | success | 10 s |
| Compile / Pre-flight gate | success | 7 s |
| CLI schema conformance | success | 8 s |
| Type Check | success | 56 s |
| Security Scan | success | 40 s |
| Docs locks (freshness & formats) | success | 1 m 6 s |
| POSIX smoke (Ubuntu) | success | 56 s |
| **Test (Python 3.11, the floor)** | **success** | **30 m 13 s** |

- **What this verdict rests on, and what it does not.** GitHub serves the job
  list and check-run conclusions without a session but gates the log text behind
  one, so this record rests on the floor leg's `conclusion: success` plus the
  artifacts it published - `cli-payloads` (26.3 KB) and `docs-html` (1.8 MB),
  both live and both produced by steps that would be absent had their
  predecessors failed or been skipped. It does **not** quote the leg's own
  "N passed" line; that count is the local run in the cut table above (11 826
  passed, 91.23%), and this leg's job is the interpreter graph below the dev
  host's 3.14.
- **The only annotations are workflow-level.** The Node.js 20 deprecation
  warnings name the same three actions (`actions/checkout@v4`,
  `actions/setup-python@v5`, `actions/upload-artifact@v4`) as last release, plus
  the `ubuntu-latest` -> Ubuntu 26 migration **notice**. Nine check-runs
  reported `success` and none carried an error.
- **The cost budget is untouched.** `tests/test_ci_cost.py` prices a job against
  100 minutes; the floor leg used 30:13 and the whole push 30:16, against the
  160.9 billable minutes the three-leg matrix cost on the 2026-10-28 push
  (`AGENTS.md`, *The Python floor must honour its lockfile*). That is 2:05
  longer than 2.2.1's 28:08 - the shape the two new packages' 240 tests predict,
  not a runner regression.

---

## 7. Open questions

- *(Resolved by the 2.1.7 cut - D21.)* **Which version do the Wave-1 items
  actually ride?** D10 proposed 2.1.7 for all of them; B2 changes what a tool
  advertises, which some would call minor. Answered as 2.1.7 for all four.
- *(Resolved at F-02 - D39.)* **Does F-02 need a shared fingerprint cache in
  `audio_suite_shared`, or its own SQLite file?** Its own file, with the R-13
  `(mtime, size)` stamp: the payload is ~700 bytes per file and grows with the
  library, while `library_stats`' cache is a tag-metadata store with its own
  schema and migration history, so one table for both would make one tool's
  migration edit the other's.
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

**Which file the bullet goes in is decided by its subject (D29).**
`CHANGELOG.md` records what a user can run or observe; `TECHNICAL_CHANGELOG.md`
carries the gate, CI, tests, tooling, behaviour-neutral refactors, dependency
bumps and documentation tooling. The rule and its lock live in `AGENTS.md`,
*Change History Follows Its Audience*, and in `tests/test_changelog_format.py`.
Applied to this plan's own items: U1 and U3 change a window a user sees, so their
bullet is user-facing (one bullet covers both, since they ship in the same
patch); U2 changes the changelogs and the release tooling, so its bullet is
technical. A bullet that genuinely mixes the two is split rather than filed
whichever way reads better — the user-observable statement stays, its evidence
moves.

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
