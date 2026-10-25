# PLAN — Audit 2026-10-24 Remediation: P0 and P1

**Status:** `[ ]` proposed (2026-10-25) — no item started.
**Status legend:** `[ ]` pending · `[~]` in progress · `[x]` done.
**Source:** [AUDIT_2026-10-24_suite_report.md](AUDIT_2026-10-24_suite_report.md) §6
(detailed findings) and §9.1 (plan-ready register).
**Predecessor:** `PLAN_feature_expansion.md` — closed 2026-10-24 with 2.1.1;
per its own governance note it is a historical record and this plan is its
successor for defect work.
**Target releases:** `2.1.2` (Sprint 1), `2.1.3` (Sprint 2), `2.1.4`
(Sprint 3) — three MAINTENANCE cuts; policy, history and the cut procedure are
in §2.
**Base state:** `main` at `dfb5c48`; working tree clean apart from the untracked
audit report. Baseline gate: compile clean, ruff clean (930 formatted), bare
`mypy .` clean (549 files), bandit 0 High / 0 Medium, bare `pytest` 10,915
passed / 3 skipped, coverage 90.50 %, 19:39.
**Governing scope:** the ten findings the audit graded **P0** (R-01–R-03) and
**P1** (R-04–R-10). Nothing else. The audit's P2/P3 defects (R-11–R-16), its
maintainability register (Q-01–Q-10) and its market-parity backlog
(F-01–F-12) are **out of scope** and are listed in §8 — they need their own
plan, and keeping them here would make this plan unshippable in the three
sprints it is sized for.
**Anti-creep rule:** implement only the steps below. No adjacent refactors, no
styling changes outside touched files, no new dependencies. A defect discovered
*while* implementing an item is fixed in the same change with a regression test
and recorded in the Decision Log (AGENTS.md, *Defects and failing checks*).

---

## 1. Decisions (decision log)

| D | Decision | Rationale / evidence |
|---|---|---|
| D1 | **R-01 is fixed by energy weighting, not by a one-pass concatenated album measure.** `calculate_album_gain` takes each track's duration and computes `album_lufs = 10·log10(Σ 10^(Lᵢ/10)·dᵢ / Σ dᵢ)`, then `gain = target − album_lufs`. The concatenation route is recorded as the deferred correctness benchmark, not shipped now. | The concatenation route needs every track decoded a second time through `ebur128` in one pass (roughly a second full decode per album), while Phase 1 already has integrated loudness and duration per file. The approximation is exact for the equal-gating case and is what the acceptance test measures against real concatenated audio. |
| D2 | **A missing duration is a per-file error, never an implicit weight.** `get_metrics` returns duration; `_measure_worker` treats `duration is None` exactly like `lufs is None` (count an error, do not add the file to album data). | A default of `0.0` or an arithmetic-mean fallback would reproduce the exact defect being fixed, silently. This is the "plausible zero" class AGENTS.md warns about. |
| D3 | **ALAC is written into an M4A container** (`song.m4a`, codec `alac`), labelled **"ALAC (M4A)"** in the UI, CLI help and guide. ALAC is *not* removed. | FFmpeg 8.0.1 has no muxer for the `.alac` extension, so the advertised target fails 100 % of the time. M4A is the container the format actually lives in (Apple's own convention, Mp3tag/dBpoweramp behaviour). |
| D4 | **ALAC and AAC-M4A share the `.m4a` extension knowingly.** `_claim_output_path` still prevents two same-run collisions; a later run targeting `m4a` overwrites an earlier ALAC file because the converter already passes `-y` for every format. The guide documents this. | The alternative — `<base>.alac.m4a` or `<base> (ALAC).m4a` — invents a filename no player or tagger expects. Overwrite-on-same-target-name is the suite's existing `-y` behaviour, not new ALAC behaviour. |
| D5 | **R-03 blocks traversal instead of sanitising it away.** `resolve_path` raises `PatternError` for `.`/`..` components, drive-letter prefixes and UNC prefixes; `engine.py` adds a containment check (`candidate.is_relative_to(base)`) as defence in depth. `cd_ripper.core.metadata_resolver._safe_filename` maps a bare `.`/`..` to `_`. | Silently rewriting `..` to `_` changes a user's intended folder name without telling them; refusing it surfaces in the existing "PATTERN ERROR" path and creates nothing. The CD-ripper sibling exists because `_safe_filename("..")` currently returns `".."` and `os.path.join(out_dir, "..")` escapes one level. |
| D6 | **R-04 uses one canonical key file: `album_art_sync/config/album_art_config.json`.** `load_config`/`save_config` take no path argument; `script_file` is removed. Migration copies a legacy JSON **and its sibling `.key`** (keys are derived as `<config>.key` by `KeyManager`), never deletes the legacy pair, and logs which file it used at DEBUG. | Copying only the JSON would strand the Fernet key beside the old path and make every migrated value undecryptable — the migration must move the key with the config. Removing the parameter is what stops a third caller-derived path appearing later. |
| D7 | **R-05 derives discovery from the loader table.** `_LOADERS: dict[str, Callable[[str], Any]]` is the single source; `SUPPORTED_EXTENSIONS = set(_LOADERS)`; `_load_audio` looks up the same table. WavPack/APE/MPC/Speex/DSF are *not* advertised by the scrubber until it has a loader for them. | The scrubber needs raw mutagen objects (it captures `APIC`/`SYLT`/`USLT` frames for restore), so `TagHandlerFactory` is not a drop-in substitute. Deriving both sides from one table makes the false `[UNREADABLE]` class impossible; the APEv2 gap is deferred explicitly in §8 rather than papered over. |
| D8 | **R-09 removes the `apply_effects` flag entirely.** `dsp_chain.apply_enhancement_chain` loses the parameter and the bypass branch; the processor calls the full chain in both modes and the existing dry-run early return (before export/tag copy) is the only difference. | The parameter exists solely to implement the defect; with no caller passing `False`, leaving it is dead scaffold (AGENTS.md, *Refactor Safety*). The function docstring and `process_file`'s docstring already promise that a dry run measures the real chain. |
| D9 | **R-06 exit policy is 0 = clean, 1 = completed with per-file errors or fatal, 2 = usage.** `finish_run` raises `SystemExit(1)` when `result.errors > 0` as well as when `result.fatal` is set. Skips alone stay 0. `--json` payloads are unchanged. | This supersedes the D92 policy recorded in `cli_base.py` ("a run whose only losses were per-file keeps its command's exit status"). That policy made `convert` exit 0 after converting 0 of 1 files, which is the automation contract the audit tested. Usage stays 2 because Click already owns it. |
| D10 | **R-10 gates dependants in both execution modes.** A `succeeded` set (parallel) and a per-step dependency check (sequential) mark a dependant `SKIPPED` with a note naming the failed dependency; it is never submitted. No "continue on error" switch is added. | A partial fix that only covers parallel mode would make the same batch behave differently depending on a checkbox; the note already flows into `BatchProgress.notes` and `verdict`. The switch is a feature, not a defect fix. |
| D11 | **R-08 adds only `explorer`/`explorer.exe` and `eject` to the executable allowlist; PowerShell is removed from the code path.** Windows eject moves to `ctypes` `mciSendStringW`; "reveal in Explorer" passes a fixed argv list to the secure wrapper. Enhancer FFmpeg/FFprobe calls move to `run_secure_subprocess`. | Allowing `powershell` at all would re-open the command-string surface the finding is about. MCI needs no subprocess and no allowlist entry; `explorer` and `eject` are OS utilities with fixed, non-shell argument lists. |
| D12 | **R-07 is test-only unless a test fails.** The APEv2 handler gets a mirrored handler suite; if a read-back exposes a real defect it is fixed in the same change and logged here. | A manual round-trip already works, so the finding is a verification gap. Writing production changes "just in case" would violate the anti-creep rule. |
| D13 | **No new dependency, no packaging change, no README tool-count fix.** Items stay inside the audited files. | R-15/R-16 are P2/P3; bundling them dilutes review of audio-correctness changes. |
| D14 | **This plan cuts three MAINTENANCE releases, one per sprint: 2.1.2, 2.1.3, 2.1.4.** C1's exit-status correction and A2's ALAC filename correction are classified as fixes, not MAJOR changes. | A MAJOR bump is for removing or renaming an interface. C1 removes no command, flag or JSON key and leaves every successful run at 0; it corrects a status that contradicted the summary the command had just printed. A2's old `.alac` name never produced a file, so no working output path disappears. One release after all three sprints was rejected because the P0 audio and security fixes must be shippable without waiting for C2's test work; the item order itself is set in §6. |
| D15 | **`utilities/release.py` is the only cut path, and the release-notes lock advances at sprint start.** `BASE_COMMIT`/`NOTE_MARKER` in `tests/test_release_notes.py` move before the first item commit; every touched code module carries `Changed in <version>:`; `release.py` does the bump, re-lock, changelog promotion, guide regeneration and gate. | Prior hand cuts went half-done (version bumped but `uv.lock` stale, `[Unreleased]` left blank, a LibreOffice re-save committed). The script checks each step and is idempotent. Advancing the marker at sprint *start* keeps the gate green at every item commit; advancing it at the cut would make every earlier commit fail the lock. |
| D16 | **A3 refuses `..`, drive and UNC values, but not a leading separator.** `resolve_path` checks the drive/UNC prefixes on the evaluated text *before* the illegal-character pass (that pass rewrites `:` and would erase the drive marker), refuses `.`/`..` after separator normalisation, and keeps the existing leading-separator strip. | A leading separator cannot be told apart from an empty leading tag: `%albumartist%/%album%` with no album artist resolves to `/Album`, and refusing it would break that pattern for every file missing that tag, while the value is re-rooted below `base_dir` either way and therefore cannot escape. The escape that existed was `..`, which is refused, and `_ensure_contained` is the backstop for a future resolver change. `test_empty_leading_tag_still_resolves_below_base`, `test_all_empty_pattern_still_resolves_empty` and `test_absolute_tag_value_is_re_rooted_inside` pin the policy. |

---

## 2. Versioning policy and history

### 2.1 Policy

The suite ships **one version for the whole distribution**. `[project] version`
in `pyproject.toml` is the only declaration; `audio_suite_shared.project_version.declared_version()`
reads it with `tomllib` (never a second constant), and `audiosuite --version`
reports it. Semantic versioning, as this project has applied it since 1.0.0:

| Token | Meaning | Releases in this tree |
|---|---|---|
| **MAJOR** | Breaking changes, architectural redesigns, incompatible interface changes | 2.0.0 (the ML-repair release, Sprint 6) |
| **MINOR** | New features and backward-compatible additions | 1.1.0 format/DSP expansion, 1.2.0 metadata/CD ripping, 1.3.0 Spectral Viewer, 1.4.0 What's New, 2.1.0 plugin system |
| **MAINTENANCE** | Bug fixes, performance work, documentation, technical debt | 1.0.1, 1.4.1, 2.1.1 |

A sprint concludes with a version decision based on what it delivered. All ten
items in this plan are defect fixes, containment or test-truth work: no tool,
flag, JSON key or output format is added. The plan therefore cuts three
MAINTENANCE releases (D14), each independently shippable.

### 2.2 Where the version lives, and what must agree

| Surface | Source of truth | How it is checked |
|---|---|---|
| Package version | `[project] version` in `pyproject.toml` | `utilities/release.py` reads it back; `audio_suite_shared/tests/test_project_version.py` |
| Lockfile | `uv.lock` (regenerated by `release.py`) | the new version is read back out of the lock, not assumed |
| Changelog | `CHANGELOG.md` | `[Unreleased]` is promoted to `## [x.y.z] - date`; an empty body is refused |
| User guides | `version: auto` front matter rendered by `utilities/build_user_guides.py` as `Version x.y.z — Month YYYY` | `release.py` regenerates and rejects any zip entry change other than `word/document.xml` |
| In-app What's New | parses `CHANGELOG.md` | `audio_suite_shared/tests/test_whats_new.py` asserts the shipped changelog carries the running version's notes |
| Stale-install notice | `audio_suite_shared.project_version` vs installed metadata | `audio_suite_shared/tests/test_cli_app.py` version tests |

Never edit a `.docx`, a version subtitle or a lockfile by hand. The version
number is never written into a second Python constant, a test fixture or a
guide source.

### 2.3 Version history

| Version | Date | Release theme | Decision record |
|---|---|---|---|
| 1.0.0 | 2026-09-26 | First recorded baseline (pre-release audit/iteration plans) | `PLAN_audit_remediation.md` … `PLAN_iteration4_remediation.md` |
| 1.0.1 | 2026-10-14 | Bug-hunt maintenance: tag/format correctness, per-file change notes, gate hardening | `PLAN_bughunt_remediation.md`, `PLAN_iteration5`–`9` |
| 1.1.0 | 2026-10-16 | Format & DSP expansion: wider inputs, lossless gain, normalisation | `PLAN_feature_expansion.md` S1 |
| 1.2.0 | 2026-10-17 | Metadata integration & CD ripping: ISRC submission, AccurateRip/offset work | S2 |
| 1.3.0 | 2026-10-18 | Visualisation & library: Spectral Viewer | S3 |
| 1.4.0 | 2026-10-19 | Windows integration & performance: in-app What's New | S4 |
| 1.4.1 | 2026-10-21 | Code-quality & security maintenance | S5 |
| 2.0.0 | 2026-10-23 | ML-powered repair; completion-seam fixes | S6 |
| 2.1.0 | 2026-10-23 | Plugin system | S7 |
| 2.1.1 | 2026-10-24 | Docs consolidation and launch correctness | S8 + follow-on batch |
| **2.1.2** | planned | **P0 containment: album gain, ALAC, traversal** | **this plan, Sprint 1** |
| **2.1.3** | planned | **P1 tool truth: config, scrubber discovery, dry run** | **this plan, Sprint 2** |
| **2.1.4** | planned | **P1 automation, security policy, APEv2 tests, batch gating** | **this plan, Sprint 3** |

The table is the project's release history at the plan's base commit
(`dfb5c48`, the state after the 2.1.1 cut); `CHANGELOG.md` is the authoritative
record and the table exists so a reader of this plan can see which cut
introduced what without opening ten plan files. Releases are recorded by the
dated CHANGELOG section and the `Release x.y.z` commit; this repository does
not create git tags (`git tag` is empty at the base commit).

### 2.4 This plan's releases

| Sprint | Version | Class | Contents | Cut rule |
|---|---|---|---|---|
| 1 | **2.1.2** | MAINTENANCE | A1 (R-01), A2 (R-02), A3 (R-03) plus their regressions | Cut only when all three P0 items are closed and the gate is green |
| 2 | **2.1.3** | MAINTENANCE | B1 (R-04), B2 (R-05), B3 (R-09) | Cut only when the guides are regenerated and the hygiene lock is green |
| 3 | **2.1.4** | MAINTENANCE | C1 (R-06), C2 (R-07), C3 (R-08), C4 (R-10) | Cut only when the CLI reference documents the exit contract and APEv2 coverage is recorded |

A version is not spent on a partial sprint: if an item slips, the sprint does
not cut and the next sprint does not begin. Each cut is its own commit after
the item commits, and each is recorded in the completion log with the version
that shipped it.

### 2.5 Per-sprint release cut (mandatory)

0. **Before Sprint 1 — commit the records.** This plan and
   `AUDIT_2026-10-24_suite_report.md` are untracked at the base commit. Commit
   them as a plan-only commit first: the release-notes lock requires at least
   one changed `.md` in its non-empty exception category, and the audit is the
   evidence the completion rows cite.
1. **At sprint start — advance the release-notes lock.** In
   `tests/test_release_notes.py`, set `BASE_COMMIT` to the commit the sprint
   starts from (for Sprint 1: `dfb5c48`, the state after the 2.1.1 cut) and
   `NOTE_MARKER = "Changed in 2.1.2"`; append a dated paragraph to that
   module's docstring recording the boundary **and give that module its own
   `Changed in 2.1.2:` line** — it is a `.py` file changed since the base, so
   the lock checks it too. This is a `chore` commit before the first item.
2. **Per item — carry the note.** Every touched first-party `.py` file (tests
   included: the lock scans tracked code files changed since `BASE_COMMIT`)
   gains a `Changed in 2.1.2: <what changed>` paragraph in its module docstring
   or the format's comment syntax. `.pyw` launchers, `.md`, `.json`, `.lock`
   and regenerated binaries are declared exceptions in that lock. Add the
   `[Unreleased]` bullet per §5.4 in the same commit.
3. **At sprint close — cut with the script, never by hand:**

   ```bash
   python utilities/release.py 2.1.2 --dry-run   # inspect every planned mutation
   python utilities/release.py 2.1.2             # apply, then run the six-command gate
   ```

   The script bumps `pyproject.toml` (adding its own
   `# Changed in 2.1.2:` note there, because `.toml` is in the lock's code
   set), re-locks and reads the version back from `uv.lock`, promotes the
   non-empty `[Unreleased]` body to
   `## [2.1.2] - <date>`, regenerates each guide whose subtitle does not yet
   name the new version and verifies the `.docx` changed only
   `word/document.xml`, then runs the gate. Do not pass
   `--skip-gate`; a cut that cannot pass the gate is not a cut.
4. **Verify the surfaces:** `audiosuite --version` prints `2.1.2`;
   `grep '^## \[2.1.2\]' CHANGELOG.md` matches; a guide subtitle reads
   `Version 2.1.2 — <Month YYYY>`; `uv.lock` carries the same version. Then
   `pytest audio_suite_shared/tests/test_project_version.py
   audio_suite_shared/tests/test_whats_new.py tests/test_release_notes.py
   tests/test_user_guide_hygiene.py -q`.
5. **Commit** the cut as `Release 2.1.2` — separate from every item commit.

### 2.6 Locks that fail when versioning is skipped

| Lock | What it enforces | Symptom if skipped |
|---|---|---|
| `tests/test_release_notes.py` | every tracked code file changed since `BASE_COMMIT` carries `NOTE_MARKER`; the changed set is asserted non-empty | gate fails on the first item commit (or passes vacuously if the base is stale and nothing matches) |
| `audio_suite_shared/tests/test_whats_new.py` | the shipped changelog carries the running version's notes | What's New opens empty after the update |
| `tests/test_user_guide_hygiene.py` | every `.docx` has a Markdown source and no stale artefact | the Help button opens an old version subtitle, or a hand-edited file fails |
| `audio_suite_shared/tests/test_project_version.py` + `test_cli_app.py` | one declared version, read from `pyproject.toml` | `--version` disagrees with the changelog/lock |

---

## 3. Ownership and accountability

This repository is maintained by one engineer (two human contributors in total),
so these are **accountable specialty roles**, not separate staff. Each item names
exactly one owner so a handoff or a review request is unambiguous; the owner is
also the person who records the completion-log evidence. Where no second
reviewer is available, the acceptance test is the reviewer: the completion row
must show the failing-before and passing-after output, not a claim.

| Role | Accountable for | Items |
|---|---|---|
| **Audio-correctness steward** | Album/track loudness maths, tag values written from measurements | A1 |
| **Conversion steward** | Container/codec matrix, output naming, conversion outcome tests | A2 |
| **Security steward** | Path containment, subprocess boundary, allowlist policy | A3, C3 |
| **Metadata steward** | Scrubber format discovery, tag-handler coverage | B2, C2 |
| **DSP steward** | Enhancement chain semantics, dry-run fidelity | B3 |
| **Tool-config steward** | Album-art key files, config migration | B1 |
| **CLI/automation steward** | Exit-status contract, JSON stability, guide wording | C1 |
| **Orchestration steward** | Dependency graph, batch report semantics | C4 |

Sign-off rule: the security steward cannot sign off A3/C3 on their own
assertion alone — the completion row carries the command output for the
traversal probe and the allowlist test.

---

## 4. Traceability matrix

| Audit finding | Severity | Plan item | Sprint | Release | Owner |
|---|---|---|---|---|---|
| R-01 — ReplayGain album gain is duration-unweighted | P0 | A1 | 1 | 2.1.2 | Audio-correctness steward |
| R-02 — ALAC output always fails | P0 | A2 | 1 | 2.1.2 | Conversion steward |
| R-03 — Organizer path traversal via tag values | P0 | A3 | 1 | 2.1.2 | Security steward |
| R-04 — Album-art GUI/CLI read different key files | P1 | B1 | 2 | 2.1.3 | Tool-config steward |
| R-05 — Scrubber discovers formats it cannot load | P1 | B2 | 2 | 2.1.3 | Metadata steward |
| R-09 — Enhance dry run uses a different DSP chain | P1 | B3 | 2 | 2.1.3 | DSP steward |
| R-06 — CLI exits 0 when a batch reports errors | P1 | C1 | 3 | 2.1.4 | CLI/automation steward |
| R-07 — APEv2 tag writes effectively untested | P1 | C2 | 3 | 2.1.4 | Metadata steward |
| R-08 — Two packages bypass the subprocess boundary | P1 | C3 | 3 | 2.1.4 | Security steward |
| R-10 — A failed step satisfies dependencies | P1 | C4 | 3 | 2.1.4 | Orchestration steward |

---

## 5. Global Definition of Done

### 5.1 The gate (after every item, and at the end of every sprint)

```bash
python -m compileall -q -f .
ruff check .
ruff format --check .
python -m mypy .
bandit -r . -x ./.venv -c pyproject.toml
pytest
```

Notes:

- `pytest` is **bare** — `pytest tests/` silently skips every per-package suite
  (AGENTS.md, *Verification Tooling Traps*). `mypy` is **bare** for the same
  reason; never substitute a per-file run.
- In Git Bash, bandit needs `PYTHONUTF8=1 python -X utf8 -m bandit -r . -x
  ./.venv -c pyproject.toml`. The flags are the contract, not the shell dialect.
- bandit's verdict is **0 High / 0 Medium**, never its exit code (Low findings
  are the documented first-party subprocess sites).
- A red gate blocks the next item. Do not proceed on a known failure; do not
  add `# type: ignore`, `xfail`, `skip` or a weakened assertion to get past one.

### 5.2 Audio-correctness evidence rule

Every item that changes what is written to a file (A1, A2, B2, B3, C2) proves
the **outcome on disk**, not the field the code just wrote:

- decode the produced file and measure (RMS per channel, integrated loudness,
  or `ffprobe` stream properties), or read the tag back through a **fresh**
  handler instance;
- the test must fail at the pre-fix commit (record the `FAILED` line in the
  completion log as the negative control), then pass after the fix;
- a test that asserts the same internal state the code assigned is not
  evidence and is rejected at review.

### 5.3 Documentation and guide protocol

- User-visible changes (A2 label/extension, B3 dry-run wording, C1 exit codes,
  B1 key-file location) update the **Markdown source** under
  `user_guides/individual_programs/<tool>/` and the reference page when the CLI
  is affected, then regenerate the `.docx` with
  `python utilities/build_user_guides.py <module_dir>`. Never hand-edit a
  `.docx`; regenerate it with the interpreter that has `python-docx`.
- `AGENTS.md` is updated where it documents a fixed defect: the *Shared Config
  Pattern* section currently states that `album_art_sync` resolves the key file
  from the calling module (B1 makes that false).
- Each item names its doc touchpoints explicitly, or states "none" with the
  reason (test-only/internal).

### 5.4 CHANGELOG

Every user-visible change gets a bullet under `## [Unreleased]` in the correct
Keep-a-Changelog subsection **in the sprint that ships it**: A2, B1, B3, C1 and
C4 are `Fixed`/`Changed`; A1 is `Fixed` (wrong album tags); A3 is `Security`.
C2 is test-only (no bullet). At the sprint close, `utilities/release.py`
promotes the `[Unreleased]` body to `## [x.y.z] - date`; that promotion is the
only edit the release cut makes to this file, and it refuses an empty section.

### 5.5 Commit discipline

One commit per item, message naming the audit ID (e.g.
`Fix R-01: weight album gain by track duration`). Do not batch two items into
one commit — the audit's P0 evidence is easier to review one fix at a time.
Each item commit carries its `[Unreleased]` bullet and its `Changed in <version>:`
notes (§2.5). The release cut is a separate `Release x.y.z` commit after the
items; the version is not bumped mid-sprint. `git status` is checked before
staging; unrelated working-tree changes are never swept in.

### 5.6 Completion log

Every item appends one row to §7 with: item, version, commit, date, the targeted test
command and its result, the negative-control `FAILED` line, and the final gate
tail. A row without the gate tail is incomplete.

---

## Sprint 1 — P0: correctness and containment

**Target version:** `2.1.2` (MAINTENANCE). **Exit criterion:** all three items
closed, their regression tests fail at `dfb5c48` and pass at the sprint head,
the full gate is green, and the sprint closes with the §2.5 cut. Do not cut
2.1.2 — or begin Sprint 2 — with any of these open.

### A1 — R-01: album gain must be duration-weighted

- **Owner:** Audio-correctness steward. **Effort:** M (2–4 days).
- **Problem:** `replaygain_analyzer/core/gain_calculator.py:72` computes
  `target_lufs - statistics.mean(lufs_values)`, giving a 10-second track the
  same album weight as a 30-minute one. The audit's measured pair (10 s at
  −10 LUFS, 30 s at −30 LUFS) yields **+4.0 dB** where the energy-weighted
  answer is **−0.1 dB**: a 4.1 dB error in a tag every ReplayGain-aware player
  applies to the whole album. `test_gain_calculation_multiple_files_uses_mean`
  currently locks the wrong behaviour.

**Change**

1. `replaygain_analyzer/core/ffmpeg_metrics.py`
   - `get_metrics` returns `tuple[float | None, float, float | None]`:
     `(integrated_lufs, true_peak_dbfs, duration_seconds)`.
   - Parse `Duration: HH:MM:SS.ss` from the **same** `ebur128` run's stderr
     (`re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)`), so the
     common path spawns no extra process.
   - If the line is absent, run one `ffprobe -v error -show_entries
     format=duration -of default=nw=1:nk=1` through `run_secure_subprocess`
     (already allowlisted). If that also fails, return `None` for duration —
     never `0.0`.
   - Update the module docstring and the return-tuple documentation.
2. `replaygain_analyzer/core/gain_calculator.py`
   - New signature:
     `calculate_album_gain(target_lufs: float, lufs_values: list[float], peak_values: list[float], durations_s: list[float]) -> tuple[float, float, str, str]`.
   - Compute `energy = sum(10 ** (lufs / 10) * dur for lufs, dur in zip(lufs_values, durations_s, strict=True))`
     and `album_lufs = 10 * math.log10(energy / sum(durations_s))`;
     `album_gain = target_lufs - album_lufs`.
   - Guards, each raising `AudioSuiteError` with context: empty `lufs_values`,
     empty `peak_values`, `len(durations_s) != len(lufs_values)`, any
     `duration <= 0` or non-finite. Do not require the peak list to match in
     length: peaks are aggregated by `max()` and an existing test deliberately
     passes a longer peak list. Delete the `statistics` import.
   - Docstring states the formula, the units, and that this is the
     energy-weighted ReplayGain 2.0-compatible album value (not the arithmetic
     mean of track loudness).
3. `replaygain_analyzer/core/file_processor.py`
   - `_do_measure` returns the 3-tuple; `_measure_worker` unpacks
     `lufs, peak, duration_s` and takes the existing `lufs is None` error branch
     when `duration_s is None` too (D2).
   - Store `"duration_s": duration_s` in `file_data`; `_write_worker` builds
     `durations = [f["duration_s"] for f in job.files_data]` and passes it.
   - Add a `Changed in …` docstring line describing the new weighting.

**Tests in lockstep** — `replaygain_analyzer/tests/test_replaygain_core.py`

- Update every `calculate_album_gain(...)` call with a duration list.
- Rename `test_gain_calculation_multiple_files_uses_mean` to
  `test_equal_durations_reduce_to_the_mean` (`[10.0, 10.0]`) and keep its
  expected `+4.0 dB` for `[-18, -22]`.
- New `test_album_gain_is_duration_weighted`: `target=-16`,
  `lufs=[-10.0, -30.0]`, `durations=[10.0, 30.0]` → gain ≈ **−0.11 dB**
  (assert `< 0.05` from −0.11) and `abs(gain - 4.0) > 2.0`, so the old
  behaviour cannot pass.
- New `test_album_gain_rejects_bad_durations`: empty duration list, a duration
  list shorter/longer than `lufs_values`, zero, negative, `nan`.
- New `test_metrics_returns_duration` (pipeline test): generate a 2 s WAV with
  ffmpeg, assert the third element is within 0.1 s of 2.0; skip when ffmpeg is
  absent, matching the existing ffmpeg-dependent tests.
- New outcome test
  `test_album_tag_matches_concatenated_measurement`
  (`replaygain_analyzer/tests/test_replaygain_pipeline.py`):
  1. build two FLACs with `ffmpeg -f lavfi` — 10 s at roughly −10 LUFS and 30 s
     at roughly −30 LUFS (sine + `volume`), in one temp folder;
  2. run the real `run_replaygain` live path with the default target so
     `REPLAYGAIN_ALBUM_GAIN` is written;
  3. build a concat list, decode both in one pass through
     `ffmpeg -af ebur128=peak=true -f null -`, read the final integrated value,
     and assert `target − measured` is within **±0.2 dB** of the tag;
  4. assert the value is at least 2 dB away from the arithmetic-mean answer, so
     the test distinguishes the two formulas on real files.
- Update `test_app.py:246`'s `get_metrics` mock to a 3-tuple and every other
  mock of the function (there are ~10 in `test_replaygain_pipeline.py`).

**Docs / CHANGELOG:** ReplayGain guide — replace any "mean of track loudness"
wording with the energy-weighted description; regenerate the `.docx`.
CHANGELOG `Fixed`: "Album ReplayGain is now weighted by track duration instead
of averaging per-track loudness."

**Acceptance**

- `pytest replaygain_analyzer/tests -q` green.
- The new outcome test fails at `dfb5c48` (record the failing assertion line),
  passes at the item commit.
- Full gate green; bandit still 0/0.
- A hand-run probe on two temp tones reproduces ≈ −0.1 dB (not +4.0 dB).

**Risk:** the energy-weighted value can differ from a true concatenated
measurement on material with heavy gating (silence between movements); §8 keeps
the one-pass route as a deferred accuracy improvement. Rollback is a single
revert of the item commit.

---

### A2 — R-02: ALAC must produce a playable file

- **Owner:** Conversion steward. **Effort:** S (≤1 day).
- **Problem:** `music_format_converter/core/file_processor.py:447` names every
  output `f"{base_name}.{output_format}"`, so ALAC becomes `song.alac`. FFmpeg
  8.0.1 cannot select a muxer for that extension: the audit's live run failed
  with `Error initializing the muxer ... Invalid argument` for every file, while
  the unit tests only asserted the `-codec:a alac` argument. ALAC is advertised
  in `LOSSLESS_FORMATS` and in the GUI's format list.

**Change**

1. `music_format_converter/core/formats.py`
   - Add `OUTPUT_EXTENSIONS: dict[str, str] = {"alac": "m4a"}` and
     `def output_extension(fmt: str) -> str:` returning
     `OUTPUT_EXTENSIONS.get(fmt.lower(), fmt.lower())`.
   - `format_info("alac")` gains: "ALAC is stored in an M4A container; the
     output file uses the .m4a extension."
2. `music_format_converter/core/file_processor.py`
   - `output_name = f"{base_name}.{output_extension(output_format)}"`.
   - `_dry_run_report` already receives `output_name` as an argument, so the
     single call-site change covers the dry-run preview too — verify, and do
     not add a second naming rule inside the report helper.
   - Import `output_extension` next to `detect_format`/`can_convert`.
3. `music_format_converter/core/ffmpeg_params.py`
   - Keep `-codec:a alac`; add a comment that the muxer is chosen by the `.m4a`
     output extension, and that the argument list must not gain `-f alac`.
4. Check the GUI's "changing output format" path: the ALAC label/description
   comes from `format_info`, so no separate widget change should be needed —
   verify by launching the tool and switching the format (not by reading the
   CLI).

**Tests in lockstep** — `music_format_converter/tests/test_formats.py`,
`test_file_processor.py`, `test_cli.py`

- `test_output_extension_alac_is_m4a`; `test_output_extension_is_identity_for_other_formats`
  over `ALL_OUTPUT_FORMATS`.
- `test_alac_output_name_uses_m4a`: the per-file planner/dry-run emits
  `song.m4a`, not `song.alac`.
- Real conversion, skipped when ffmpeg is absent:
  `test_alac_conversion_produces_alac_in_mp4_container` — write a 1 s stereo WAV
  (or copy a committed WAV fixture), run the live conversion with
  `--format alac`, then:
  - `ffprobe -show_entries stream=codec_name` reports `alac`;
  - `format_name` contains `mp4`/`m4a`;
  - decode source and output with `ffmpeg -f s16le` and compare per-channel RMS
    (lossless: difference < 1e-4; do **not** assert only on file existence).
- CLI: `CliRunner` live convert to ALAC returns 0 and names the `.m4a` output
  (before C1 lands; C1 must not change a successful run).
- Negative control: the new real-conversion test fails at `dfb5c48` with the
  muxer error (record it).

**Docs / CHANGELOG:** Converter guide — format list line 22 and ALAC note line
69 become "ALAC (M4A container)"; add one sentence that ALAC and AAC-M4A share
the `.m4a` extension and a later run replaces the earlier file. Regenerate the
guide. CHANGELOG `Fixed`: "ALAC conversions now write an M4A container instead
of failing with an invalid muxer."

**Acceptance:** targeted tests green; the produced file plays and probes as
ALAC; full gate green.

**Risk:** a user's downstream script expecting `.alac` changes behaviour — the
guide and CHANGELOG say so. Existing `.alac` files remain readable as input
because `detect_format` still knows the extension.

---

### A3 — R-03: tag-driven paths must stay inside the chosen tree

- **Owner:** Security steward. **Effort:** S–M (1–2 days).
- **Problem:** `file_reorganizer/core/pattern.py:295` replaces illegal
  characters but keeps `..`, and `engine.py:274` joins the result to
  `self.base_dir` with no containment check. The audit reproduced
  `resolve_path("../../evil", {}) == "..\\..\\evil"` and an absolute path
  outside the sandbox. Tags are untrusted input per `SECURITY.md`. The CD
  ripper has the same class one level down: `_safe_filename("..")` returns
  `".."`, and `encoding_pipeline.py:100-105` joins it to `out_dir`.

**Change**

1. `file_reorganizer/core/pattern.py`
   - After evaluation and control-character removal — and **before** the
     leading/trailing-separator strip, so `/etc/passwd` cannot pass as
     `etc/passwd` by accident — reject:
     - any component equal to `.` or `..`;
     - an absolute path (`raw.startswith(os.sep)` or `raw.startswith("/")`);
     - a Windows drive prefix `^[A-Za-z]:`;
     - a UNC prefix `^\\\\` or `^//`.
   - Raise `PatternError` with the offending component/value. Keep the existing
     illegal-character replacement for the remaining components.
   - Extend `resolve_path`'s docstring: the result is relative and
     traversal-free, or it raises.
2. `file_reorganizer/core/engine.py`
   - Before `_perform_action`, resolve `Path(self.base_dir)` and the candidate
     path and reject unless `candidate.is_relative_to(base)`; raise
     `PatternError` so the existing handler increments `stats.errors` and emits
     "PATTERN ERROR". Both dry and live paths go through this code.
3. `cd_ripper/core/metadata_resolver.py`
   - `_safe_filename`: after the existing substitution and strip, map `"."` and
     `".."` to `"_"`; strip trailing dots and spaces (Windows rules). Leave the
     empty string as `""` — callers already supply fallbacks (`or track_artist`,
     `"Unknown Album"`) and an existing test pins that contract.
4. `cd_ripper/core/encoding_pipeline.py`
   - Build `out_path`, resolve `self.out_dir` and `out_path`, and refuse (raise
     `AudioSuiteError` with the track number) if not contained **before**
     `os.makedirs`.
5. Do not add a silent `..` → `_` rewrite in the organizer: refusal is the
   contract (D5).

**Tests in lockstep**

- New `file_reorganizer/tests/test_pattern.py` (mirrors `core/pattern.py`):
  parametrised `["../../evil", "..\\..\\evil", "C:\\Windows\\x",
  "\\\\server\\share\\x", "..", "../x"]` → `PatternError`; and a positive case
  (`"AC/DC"`-style tag or a normal album/title) still produces the same path as
  before.
- `file_reorganizer/tests/test_reorganizer.py` (the existing engine suite): a
  temp file tagged with `album="..", title=".."` (and one with
  `album="../../evil"`); run **dry** and **live**; assert no file or directory
  exists outside `base_dir`, the step reports an error (`stats.errors >= 1`,
  "PATTERN ERROR" in the callback), and the source file is untouched. Resolve
  the candidate in the test and assert `is_relative_to(base)` for every callback
  path.
- `cd_ripper/tests/test_ripper_core.py` (where the `_safe_filename` tests
  already live): `_safe_filename("..") == "_"`, `_safe_filename(".") == "_"`,
  `_safe_filename("") == ""` still true, normal names unchanged. Add the
  `encoding_pipeline` case here too: `album=".."` refuses before creating
  anything outside `out_dir` (patch the encoder so the test stops at the path
  check).
- Negative control: the traversal test fails at `dfb5c48` (the file appears
  outside), passes after.

**Docs / CHANGELOG:** File Reorganizer guide — one sentence that a pattern
resolving to `..`, an absolute path or a drive/UNC path is refused, not
silently rewritten. CHANGELOG `Security`: "File Reorganizer and CD ripper now
refuse paths that escape the destination directory."

**Acceptance:** targeted tests green; a recorded shell probe shows the pre-fix
escape and the post-fix refusal; full gate green; bandit 0/0.

---

## Sprint 2 — P1: tool correctness and user-visible truth

**Target version:** `2.1.3` (MAINTENANCE). **Exit criterion:** the three items
are closed with their tests, the guide artifacts are regenerated,
`tests/test_user_guide_hygiene.py` is green, and the sprint closes with the
§2.5 cut.

### B1 — R-04: one canonical album-art key file

- **Owner:** Tool-config steward. **Effort:** S (≤1 day).
- **Problem:** `album_art_sync/app.py:78` calls `load_config(__file__)` →
  `album_art_sync/album_art_config.json`; `core/pipeline.py:213` calls
  `load_config(__file__)` → `album_art_sync/core/album_art_config.json`. On the
  audit install the GUI file held the Fanart.tv keys and the `core/` file was
  empty, so CLI/batch runs silently lost that source. Both files are
  gitignored, so the split is invisible in review. `KeyManager` derives the key
  file as `<config>.key`, so a JSON copied without its key is undecryptable.

**Change** — `album_art_sync/config/settings.py`

1. Replace `load_config(script_file=__file__)` / `save_config(..., script_file)`
   with argument-free functions:
   - `CONFIG_DIR: Path = Path(__file__).resolve().parent` (module-level, so tests
     can monkeypatch it);
   - `def config_path() -> Path: return CONFIG_DIR / "album_art_config.json"`;
   - `def legacy_config_paths() -> list[Path]` returning the package-root and
     `core/` locations (derived from `Path(__file__).resolve().parents[1]`).
2. `load_config()`:
   - if `config_path()` does not exist, look for a legacy JSON in order; when
     found, copy it and its sibling `.key` (if present) to the canonical
     directory with `shutil.copyfile`, never deleting or overwriting the
     legacy pair; log at DEBUG which source was used and at INFO when a
     migration happened;
   - instantiate `KeyManager(str(config_path()))` for the canonical file before
     decrypting, so its existing Windows ACL hardening applies to the migrated
     key rather than leaving it with the legacy directory's inherited ACLs;
   - then load the canonical file exactly as today (template creation with
     `encoding="utf-8-sig"`, decrypt, warning/`default` on a malformed file).
3. `save_config(config)` writes only `config_path()`; keep the atomic
   `.tmp` + `os.replace` and the existing exception handling.
4. Update the two call sites to `load_config()`; remove the now-unused
   `script_file` arguments. Grep the package for any other `load_config(`
   caller before finishing.
5. Verify `.gitignore` covers `album_art_config.json`, `album_art_config.key`
   and `*.tmp` in the new `config/` directory (`git check-ignore` each) and add
   patterns only if one is missed.

**Tests in lockstep** — `album_art_sync/tests/test_album_art_sync.py`

- Replace the `fake_script` fixtures with `monkeypatch.setattr(settings,
  "CONFIG_DIR", tmp_path)`.
- `test_gui_and_pipeline_resolve_the_same_config_file`: patch `CONFIG_DIR`,
  `save_config({"fanart": {...}})` from the settings module, then call the
  pipeline's loader and assert the same value comes back; also assert
  `settings.config_path()` is the single path both use.
- `test_load_migrates_legacy_json_and_key`: create a legacy encrypted JSON +
  `.key` in a fake package layout (monkeypatch `legacy_config_paths` to it),
  no canonical file; load; assert the canonical JSON and `.key` exist, the
  decrypted key is present, and the legacy files are untouched.
- `test_no_caller_derived_config_path_remains`: AST/grep-style assertion that no
  module in `album_art_sync` passes an argument to `load_config`/`save_config`
  (locks the third-call-site regression).
- Existing tests that assert a template is created on first load stay green.

**Docs / CHANGELOG:** `AGENTS.md` *Shared Config Pattern* — replace the
"currently derives … from the calling module's `__file__`" paragraph with the
canonical location and the migration rule. Album Art guide: state where the key
file lives. CHANGELOG `Fixed`: "Album-art API keys are now read from one
canonical file by both the GUI and the CLI."

**Acceptance:** targeted tests green; `git status` shows no new tracked config
file; full gate green.

**Risk:** a user with keys only in the legacy `core/` file gets them migrated on
first load; if the canonical file already exists it wins and the legacy key is
left in place for manual recovery. The log line says which happened.

---

### B2 — R-05: discover only what the scrubber can load

- **Owner:** Metadata steward. **Effort:** S (≤1 day).
- **Problem:** `metadata_scrubber/core/scrubber.py:46` builds
  `SUPPORTED_EXTENSIONS` from the 14-extension suite list minus `.wma`, while
  `_load_audio` (line 71) handles only MP3/FLAC/OGG/OPUS/M4A/MP4/WAV/AIFF/AIF.
  After the suite's format expansion, valid `.wv/.ape/.mpc/.spx/.dsf` files are
  discovered and then reported `[UNREADABLE]` as errors; the comment still
  refers to `.wma`.

**Change**

1. Replace the module-level branch with one table:

   ```python
   _LOADERS: dict[str, Callable[[str], Any]] = {
       ".mp3": lambda p: MP3(p, ID3=ID3),
       ".flac": FLAC,
       ".ogg": OggVorbis,
       ".opus": OggOpus,
       ".m4a": MP4,
       ".mp4": MP4,
       ".wav": WAVE,
       ".aiff": AIFF,
       ".aif": AIFF,
   }
   SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_LOADERS)
   ```

   Keep the explicit lambdas only where constructor kwargs differ; a plain
   class is a valid callable.
2. `_load_audio` looks up `_LOADERS.get(ext)` and raises
   `ValueError(f"Unsupported audio format: {ext}")` when missing — the error
   text stays, but the path is now unreachable from discovery.
3. Delete the stale `.wma` comment; add a module comment explaining that the
   scrubber works with raw mutagen objects (APIC/SYLT/USLT restore), which is
   why `TagHandlerFactory` is not used here. Link the deferred APEv2 item in §8.
4. Confirm the discovery code in `app.py` uses `SUPPORTED_EXTENSIONS` (not its
   own list); if it does, switch it to the same object.

**Tests in lockstep** — `metadata_scrubber/tests/test_scrubber.py`

- `test_supported_extensions_is_exactly_the_loader_table` — set equality, so a
  future loader/extension edit cannot drift again.
- `test_every_advertised_extension_loads` — for each extension, create a real
  file (reuse the MP3 helper; generate FLAC/OGG/OPUS/M4A/WAV/AIFF with ffmpeg)
  and assert `_load_audio` returns a mutagen object rather than raising. Skip a
  case when ffmpeg is absent **or lacks that encoder** (detect from the encode
  return code) and list the containers actually exercised in the completion
  row, so a skipped case is visible rather than silently green.
- `test_wavpack_is_not_advertised_until_it_has_a_loader` — `.wv`, `.ape`,
  `.mpc`, `.spx`, `.dsf` are absent from `SUPPORTED_EXTENSIONS`, with a comment
  naming the deferred item.
- `test_scan_reports_no_unreadable_error_for_a_wavpack_file` — a folder
  containing `silence-44-s.wv` (committed) yields zero discovered files and
  zero errors, instead of one `[UNREADABLE]`.

**Docs / CHANGELOG:** Scrubber guide — the supported-format table lists the nine
containers and says other suite formats are not currently scrubbable. CHANGELOG
`Fixed`: "The Metadata Scrubber no longer reports valid WavPack/DSD/Speex files
as unreadable."

**Acceptance:** targeted tests green; the audit's `.wv` reproduction now shows
no error; full gate green.

---

### B3 — R-09: a dry run must measure the chain that will be written

- **Owner:** DSP steward. **Effort:** S (≤1 day).
- **Problem:** `audio_enhancer/core/processor.py:130` passes
  `apply_effects=not dry_run`, so with any Sprint 1 effect enabled the dry run
  measures the *base* chain while the live run applies reverse/karaoke/phaser/
  flanger/chorus/gain. `process_file`'s own docstring and the dry-run promise
  ("preview what will happen") say the full chain runs. There is no cost saving:
  the audio is decoded and processed anyway.

**Change**

1. `audio_suite_shared/dsp_chain.py`: remove the `apply_effects` parameter and
   the `if not apply_effects:` passthrough branch; delete the paragraph that
   documents the bypass; the function always applies the full ordered chain.
2. `audio_enhancer/core/processor.py`: call
   `apply_enhancement_chain(audio, sample_rate, params)`; delete the Sprint-1
   dry-run comment and the module-docstring sentence that describes bypassing
   effects. The existing `if dry_run:` early return (before `_write_audio` and
   `copy_tags`) remains the only difference.
3. Verify no other caller passes the keyword (`grep -rn "apply_effects"`), and
   remove the flag from tests that assert it.

**Tests in lockstep** — `audio_enhancer/tests/test_processor.py`,
`audio_suite_shared/tests/test_dsp_chain.py`

- `test_dry_run_measures_the_full_chain`: build `EnhancementParams(karaoke=True)`
  and a real temp WAV whose two channels are identical (a centred source), so
  karaoke cancels it to near-silence and the level difference is unambiguous;
  call `process_file(..., dry_run=True)` and then
  `process_file(..., dry_run=False)` on the same file; assert
  `result_dry.rms_after_db == pytest.approx(result_live.rms_after_db, abs=1e-9)`,
  both `DONE`, the live output exists, and the dry run wrote nothing.
  `reverse=True` is unsuitable as the probe: it is an order reversal and leaves
  RMS unchanged, so it cannot detect the old bypass.
- `test_full_chain_differs_from_base_chain_when_an_effect_is_on`: assert the
  measured RMS with `karaoke=True` differs from
  `build_enhancement_chain(params)` alone by more than 6 dB — this proves the
  test can detect the old bypass (which measured the base chain).
- Delete `test_dsp_chain.py:287`'s `apply_effects=False` bypass test; replace it
  with a test that the full chain output equals the previous full-chain
  reference for the same params (no behaviour change when effects are off).
- Update the four `call_args.kwargs["apply_effects"]` assertions (lines ~978,
  ~1157, and neighbours) to assert the call has no such keyword.

**Docs / CHANGELOG:** Enhancer guide — dry run measures the configured chain and
writes nothing. CHANGELOG `Fixed`: "Audio Enhancer dry runs now measure the same
effect chain the live run writes."

**Acceptance:** targeted tests green; the new dry/live equality test fails at
`dfb5c48` with a level difference, passes after; full gate green.

---

## Sprint 3 — P1: automation, test truth, orchestration

**Target version:** `2.1.4` (MAINTENANCE). **Exit criterion:** the four items
are closed; the CLI reference documents the exit-status contract; APEv2
coverage is measured and recorded; and the sprint closes with the §2.5 cut.

### C1 — R-06: non-zero exit when a batch reports errors

- **Owner:** CLI/automation steward. **Effort:** S (≤1 day).
- **Problem:** the `convert` command prints `1 errors` and returns normally, so
  `$?` is 0. `finish_run` (`audio_suite_shared/cli_base.py:272`) exits 1 only
  when the run was *fatal*, and its docstring states that per-file failures
  deliberately keep the command's status (D92). Schedulers and CI therefore
  cannot distinguish a clean run from one that converted nothing.

**Change**

1. `audio_suite_shared/cli_base.py` — `finish_run`:

   ```python
   if result.fatal or result.errors > 0:
       raise SystemExit(1)
   ```

   Rewrite the docstring to state the contract explicitly: **0** clean
   (including skips), **1** completed with per-file errors or crashed, **2**
   usage (Click's own). Remove the "keeps its command's exit status" paragraph
   and record the supersession of D92 in this plan's D9.
2. Keep every `--json` payload byte-identical: the exit status is the only
   change; no field is added or removed.
3. Audit every command that calls `finish_run` (23 tool CLIs use it); confirm no
   command swallows the exit by catching `SystemExit`. If one does, fix that
   command rather than adding a local bypass.
4. Audit the six CLIs that do **not** call `finish_run` — `tag_editor`,
   `tag_field_updater`, `library_stats`, `mood_analysis_batch_tagger`,
   `spectral_viewer`, `cd_ripper` — and bring each to the same contract using
   the error count it already reports. `tag_editor` and `spectral_viewer`
   appear to exit 1 on errors already; verify that with tests instead of
   assuming, and fix `tag_field_updater` and
   `mood_analysis_batch_tagger`, which print an `Errors:` line and return
   normally. `cd_ripper` keeps its fatal-path `RunFailure` and gains a
   non-zero status for partial failures.
5. Decide and document the dry-run case: a dry run that reports errors exits 1
   too (the errors are real: unreadable/unsupported inputs).

**Tests in lockstep**

- `music_format_converter/tests/test_cli.py`
  - `test_convert_with_a_failing_file_exits_nonzero`: an unreadable/corrupt
    input in a temp dir, live run, `result.exit_code == 1`, summary still
    contains `1 errors`, and no traceback.
  - Keep `test_all_skipped_tree_exits_cleanly` at **0** (skips are not errors).
  - `test_json_payload_unchanged_on_error`: parse `result.output` as JSON and
    assert the core keys and `errors == 1`; the exit code is 1.
- `audio_suite_shared/tests/test_cli_base.py` (new or existing):
  `finish_run` unit tests — `_Result(fatal=True)` → 1; `errors=1` → 1;
  `errors=0, skipped=3` → returns normally; `fatal=True, errors=0` → 1.
- `tag_field_updater/tests/test_cli.py` and
  `mood_analysis_batch_tagger/tests/test_cli.py`: one unreadable/undeletable
  file in a temp folder makes the live command exit 1 while still printing the
  summary, and an all-skipped run stays 0.
- Add a root lock (in an existing CLI test module if possible, otherwise
  `tests/test_cli_exit_contract.py`) that enumerates **every** command in
  `audio_suite_shared.cli_app`'s registry — not only `finish_run` users — and
  fails when a command that reports `errors`/failed rows can return 0. Pair it
  with the two fixed commands' tests (`tag_field_updater`,
  `mood_analysis_batch_tagger`) so the lock is not the only evidence.

**Docs / CHANGELOG:** `user_guides/reference/CLI_Commands_Reference.md` gains an
"Exit status" section (0/1/2 and the skipped-vs-error distinction);
`docs/` CLI page gets the same paragraph if it repeats the reference. CHANGELOG
`Changed`: "CLI commands now exit 1 when a batch finishes with errors; `--json`
payloads are unchanged."

**Acceptance:** targeted tests green; a recorded shell run with one corrupt
input in a temp folder shows `$? = 1` while the summary still prints the error
count; full gate green.

**Risk:** scripts that relied on 0-after-errors start failing — which is the
point; the CHANGELOG and reference announce it as a behaviour change.

---

### C2 — R-07: APEv2 tag writes get a real handler suite

- **Owner:** Metadata steward. **Effort:** M (2–4 days).
- **Problem:** `audio_suite_shared/tag_helper_apev2.py` is at **39.6 %** line
  coverage (113 of 187 statements missed). BPM, key, tempo marking, genre, mood,
  energy, artwork, editable tags, `set_raw_tags`, `delete_tags`, custom genre
  fields and ReplayGain reads are exercised only incidentally by ISRC
  round-trips. There is no `TestAPEv2Handler`, unlike MP3/IFF/Vorbis/MP4. `.wv`
  is writable and several tools can write it, so a regression could corrupt
  WavPack tags while the suite stays green.

**Change** — tests only (D12), in `audio_suite_shared/tests/test_tag_helper.py`:

1. Add `class TestAPEv2Handler`, mirroring `TestVorbisHandlerFLAC` and
   `TestMP4Handler`:
   - `test_reads_bpm_key_genre_mood_from_wavpack` — write tags with a real
     handler, re-open with a **fresh** `APEv2Handler`, assert values.
   - `test_writes_and_reads_artwork` — embed JPEG bytes, re-open, compare bytes
     and MIME/description where the language defines them.
   - `test_editable_tags_mapping` — every key the shared editable-tag contract
     exposes round-trips.
   - `test_set_raw_tags_and_delete_tags` — set multi-value/`\x00`-separated
     values, read back the exact list; `delete_tags` removes every managed field
     and leaves the audio stream intact (assert duration/sample count unchanged
     via mutagen, not just "tags empty").
   - `test_custom_genre_field` and `test_replaygain_round_trip`.
   - `test_factory_routes_wavpack_ape_and_mpc` — `.wv`, `.ape`, `.mpc` all
     return `APEv2Handler`.
2. Copy the committed fixtures to `tmp_path` **before** writing
   (`tests/data/silence-44-s.wv`, `mac-399.ape`, `click.mpc`); never mutate a
   committed fixture in place, and assert the original's mtime/hash is
   unchanged at the end of the module.
3. End-to-end analysis write on WavPack:
  `bpm_analyzer/tests/test_file_processor.py` (or the existing end-to-end
  module) — transcode `tests/data/bpm_corpus/hiphop_86.ogg` to `.wv` with
  ffmpeg in `tmp_path` (skip without ffmpeg, or when its build lacks the
  `wavpack` encoder), run the real BPM analysis with tagging enabled, then read
  the `bpm` tag with a fresh handler and assert the same value the OGG path
  produces for that clip (tolerance from the existing corpus test).

**Verification**

- `pytest audio_suite_shared/tests/test_tag_helper.py -q --cov=audio_suite_shared.tag_helper_apev2 --cov-report=term-missing`
  → line coverage **≥ 85 %** (from 39.6 %); the remaining misses are named in
  the completion row. `addopts` already carries a bare `--cov`, so read the
  module's own row of the report rather than the project total.
- `pytest bpm_analyzer/tests -q` green.

**Docs / CHANGELOG:** none (test-only); record the coverage delta in the
completion row.

**Risk:** if a mirrored test exposes a genuine write bug, fix it in the same
change, add the regression, and log it here — do not lower the assertion to
match the bug.

---

### C3 — R-08: every subprocess goes through the secure wrapper

- **Owner:** Security steward. **Effort:** S (≤1 day).
- **Problem:** `SECURITY.md` states that all first-party subprocess calls go
  through `audio_suite_shared/secure_subprocess.py` (allowlist + no shell), but
  `audio_enhancer/core/ffmpeg_io.py:123,186,280` call `subprocess.run` for
  ffprobe/ffmpeg, and `cd_ripper/ui/results_tab.py:199,209,221` call
  `subprocess.Popen` for PowerShell (drive eject, with an f-string command),
  `eject`, and `explorer /select`. Bandit grades these Low (B603/B606/B607), so
  the gate accepts them and the drift is invisible.

**Change**

1. `audio_suite_shared/secure_subprocess.py`
   - Add a `text: bool = True` keyword to `run_secure_subprocess` and pass it to
     `subprocess.run` instead of the hardcoded `text=True`. The default
     preserves every existing caller; the enhancer's PCM decode needs
     `text=False` because its stdout is raw sample bytes, which `text=True`
     would try to decode and corrupt.
   - Document that the wrapper always supplies `startupinfo`; callers must not
     pass it (passing it would duplicate the keyword).
2. `audio_enhancer/core/ffmpeg_io.py`
   - Replace the three `subprocess.run(...)` calls with
     `run_secure_subprocess("ffprobe"/"ffmpeg", args, capture_output=...,
     check=True, ...)`; the PCM decode passes `text=False` per step 1 and
     therefore omits `encoding`/`errors`, which `subprocess.run` rejects in
     binary mode.
   - Map `SubprocessSecurityError` and `CalledProcessError` into the existing
     `AudioExternalToolError` messages so user-facing wording is unchanged.
   - Remove the now-unused `subprocess` import if nothing else needs it.
3. New `cd_ripper/core/drive_control.py` (no Tk imports):
   - `eject_drive(drive: str) -> None`: validate `drive` against
     `^[A-Za-z]:?$` (Windows) or `^/dev/` (POSIX) before using it. On Windows
     call
     `ctypes.windll.winmm.mciSendStringW(f"set {letter}: door open", None, 0, None)`
     and raise `AudioSuiteError` if the return code is non-zero; on POSIX call
     `run_secure_subprocess("eject", [drive], check=False)`.
   - `reveal_in_file_manager(path: str) -> None`: on Windows
     `run_secure_subprocess("explorer.exe", [f"/select,{path}"], check=False)`;
     on POSIX `run_secure_subprocess("xdg-open", [os.path.dirname(path)],
     check=False)`. No shell, no f-string-built command string.
4. `audio_suite_shared/secure_subprocess.py`: add `"explorer"`,
   `"explorer.exe"`, `"eject"` to `ALLOWED_EXECUTABLES` with a comment naming
   the fixed-argv call sites. Do **not** add `powershell`.
5. `cd_ripper/ui/results_tab.py`: call the two helpers; delete the PowerShell
   branch and the raw `Popen` calls. Keep the existing exception handling so a
   failed eject is reported, not silent.
6. Update `SECURITY.md` if it enumerates the allowed executables or the
   enforcement point.

**Tests in lockstep**

- `cd_ripper/tests/test_drive_control.py`
  - Windows branch: `monkeypatch.setattr(sys, "platform", "nt")` (never
    `os.name`), patch `ctypes.windll` and assert `mciSendStringW` receives
    `"set D: door open"`; a non-zero return raises `AudioSuiteError`.
  - POSIX branch: patch `run_secure_subprocess`, assert `("eject", ["/dev/sr0"])`.
  - `reveal_in_file_manager` passes a fixed list (`["/select,<path>"]`), not a
    string, and never touches a shell.
  - `test_powershell_is_not_allowlisted` — `validate_executable("powershell")`
    raises `SubprocessSecurityError`.
- `audio_enhancer/tests/test_ffmpeg_io.py` (existing or new): patch
  `run_secure_subprocess` and assert the ffprobe/ffmpeg argv (decode, encode) is
  passed through it, and that the decode call passes `text=False`; assert a
  `SubprocessSecurityError` becomes `AudioExternalToolError` with the existing
  user message.
- `audio_suite_shared/tests/test_secure_subprocess.py`: `text=False` returns
  raw bytes (`CompletedProcess.stdout` is `bytes`), and the default still
  returns `str` — the parameter must not change existing callers.
- A root policy test (in `tests/` if not already present) that AST-scans
  first-party modules for `subprocess.run`/`Popen` outside
  `secure_subprocess.py` and fails on any new hit, with the current exemptions
  listed explicitly.

**Docs / CHANGELOG:** `SECURITY.md` — the invariant is now true; note the
allowlist additions and that MCI replaces PowerShell for eject. CHANGELOG
`Fixed`: "All first-party subprocess calls now go through the secure wrapper;
the CD-ripper eject no longer builds a PowerShell command string."

**Acceptance:** targeted tests green; `grep -rn "subprocess\.\(run\|Popen\)"
audio_enhancer cd_ripper` returns only the wrapper/allowlisted helpers (or
nothing); bandit remains 0 High / 0 Medium; eject/reveal still work on a manual
check if hardware is available, otherwise the mocked argv is the evidence and
the row says "manual hardware check not performed".

---

### C4 — R-10: a failed step must not satisfy its dependants

- **Owner:** Orchestration steward. **Effort:** S (≤1 day).
- **Problem:** `master_driver/batch_orchestrator.py` adds a step to `completed`
  on **both** the success and failure branches (lines ~547/553), and `_can_run`
  treats `completed` as the dependency-satisfaction set. If `bpm` fails,
  `tempo` (graph entry `["bpm"]`) still runs in parallel mode against files with
  no BPM tags; the report shows it as completed. Sequential mode does not
  consult the graph at all, so the same false success occurs there.

**Change**

1. `_run_parallel`
   - Add `succeeded: set[str]`; keep `completed` (or rename it to `finished`)
     for termination and reporting.
   - `_can_run` requires `dep_map[tid].issubset(succeeded)`.
   - On failure, walk the still-unrun dependants (transitive closure) and mark
     each `SKIPPED`, with `step.note = f"skipped: dependency '{dep}' failed"`,
     `start_time`/`end_time` set, and add it to `skipped_ids`. Add them to the
     same set the loop uses for termination.
   - Leave the standalone-step skip semantics unchanged.
2. `_run_sequential`
   - Compute `dep_map = _resolve_dependencies([s.tool_id for s in self._steps])`.
   - Before running a step, if any dependency is in `failed_steps` or already
     `SKIPPED`, mark it `SKIPPED` with the same note and continue. Track a
     `skipped_ids` set for the report (the existing `skipped` count is derived,
     so no `BatchReport` change is needed).
3. Docs in the module docstring: one `Changed in …` line stating that a failed
   dependency now skips its dependants instead of releasing them.

**Tests in lockstep** — `master_driver/tests/test_batch_orchestrator.py`

- `test_failed_dependency_skips_dependants_parallel`: patch
  `run_python_script` with a side effect returning exit 1 for `bpm` and 0 for
  `tempo`; run parallel; assert `tempo` was **never submitted** (inspect
  `mock.call_args_list` for the script/args of `tempo`, or assert the submit
  count is 1), `statuses == {"bpm": FAILED, "tempo": SKIPPED}`, the report is
  `completed=0, failed=1, skipped=1`, and the progress notes contain
  "dependency 'bpm' failed".
- `test_failed_dependency_skips_dependants_sequential`: same side effect,
  sequential mode; same statuses and no `tempo` invocation.
- Keep `test_independent_tools_run_in_parallel` and the existing standalone
  tests green (they pin the success path).
- `test_transitive_dependant_skipped`: `bpm` fails → `tempo` skipped → a
  synthetic step depending on `tempo` is skipped too (add the edge via
  monkeypatching `DEPENDENCY_GRAPH` in the test, then restore).

**Docs / CHANGELOG:** Master Driver guide/report wording — a step whose
dependency failed is reported `SKIPPED` with the reason, not completed.
CHANGELOG `Fixed`: "Batch runs no longer start a step whose dependency failed;
it is reported as skipped with the reason."

**Acceptance:** targeted tests green; the failing-bpm batch visibly reports
`tempo` as skipped in the panel and the report; full gate green.

---

## 6. Sprint sequencing and release gate

| Sprint | Release | Items | Duration | Why this order |
|---|---|---|---|---|
| **1 — P0 containment** | **2.1.2** | A1, A2, A3 | ~1 week | Audio corruption and a path escape. The suite's own rule makes these release-blocking; nothing else ships first — and this cut goes out without waiting for Sprint 2 or 3. |
| **2 — P1 tool truth** | **2.1.3** | B1, B2, B3 | ~1 week | User-visible correctness: one config, honest format discovery, a dry run that matches the live run. Each is a one-day fix with a tool-wide blast radius. |
| **3 — P1 automation/test truth** | **2.1.4** | C1, C2, C3, C4 | ~1–2 weeks | Makes failures visible (exit codes, skipped dependants), closes the security-policy gap, and pays down the APEv2 verification debt. |

Dependencies between items:

- A2 must land before C1's CLI test writes a successful ALAC run (C1 does not
  change success paths, but the test is easier to write once A2 exists).
- B2 and C2 both touch the metadata surface but different files; they can run in
  either order. C2's end-to-end `.wv` test assumes B2's discovery rule, not its
  code.
- C3's AST policy test must be added after C3's own call sites are converted,
  otherwise it fails on the pre-existing violations by design.
- No item depends on an out-of-scope fix.

**Sprint exit:** run the full gate, paste the tail into the completion log, and
verify `git status` is clean apart from the completion-log edit. A sprint with a
red or skipped check does not close.

---

## 7. Completion log

Append one row per item. The "negative control" column records the test line
that **failed** at `dfb5c48` (or at the item's parent commit); the "gate" column
records the final six-command tail.

| Item | Release | Commit | Date | Targeted verification | Negative control | Gate |
|---|---|---|---|---|---|---|
| A1 | 2.1.2 | `9e3c00f` | 2026-10-25 | `pytest replaygain_analyzer/tests` → 197 passed; guide rebuilt, only `word/document.xml` differs | Mean formula planted: `test_album_gain_is_duration_weighted` and `TestAlbumGainOutcome` fail — tag +9.50 dB against measured +12.90 dB | compile OK; ruff clean; ruff format clean; mypy 549 files; bandit 0 High / 0 Medium (47 Low); bare `pytest` 10,929 passed, 3 skipped, 90.50 %, 18:46 |
| A2 | 2.1.2 | `94f91ae` | 2026-10-25 | `pytest music_format_converter/tests` → 503 passed; `pytest tests/test_release_notes.py tests/test_user_guide_hygiene.py tests/test_docs_formats.py` → 528 passed; guide rebuilt, only `word/document.xml` differs; `build_user_guides.py --check` current | Old `f"{base_name}.{output_format}"` planted (SHA-256-verified restore): 6 fail — `test_live_conversion_writes_m4a_and_not_alac`, `test_output_probes_as_alac_inside_an_mp4_container`, `test_output_is_bit_exact_with_the_source`, `test_dry_run_previews_the_m4a_name`, `test_alac_file_is_still_accepted_as_input`, `TestAlacEndToEnd::test_live_alac_conversion_succeeds_and_names_the_m4a`, each with `Error initializing the muxer for ...\\song.alac: Invalid argument` | compile OK; ruff clean; ruff format clean; mypy 549 files; bandit 0 High / 0 Medium (47 Low); bare `pytest` 10,947 passed, 3 skipped, 90.50 %, 14:51 |
| A3 | 2.1.2 | — | — | — | — | — |
| B1 | 2.1.3 | — | — | — | — | — |
| B2 | 2.1.3 | — | — | — | — | — |
| B3 | 2.1.3 | — | — | — | — | — |
| C1 | 2.1.4 | — | — | — | — | — |
| C2 | 2.1.4 | — | — | — | — | — |
| C3 | 2.1.4 | — | — | — | — | — |
| C4 | 2.1.4 | — | — | — | — | — |

Release-cut rows (one per sprint) are appended here as well, recording the
version, the promotion of `[Unreleased]`, the guide regeneration and the gate
output. A missing cut row means the sprint is not closed, whatever the item
rows say.

---

## 8. Out of scope (deliberately deferred)

Recorded so a later plan can pick them up without re-auditing.

| Deferred | Source | Why not here |
|---|---|---|
| R-11 dependency audit non-blocking | Audit P2 | CI policy change, not a code defect; needs a dated advisory allowlist and a weekly job. |
| R-12 POSIX untested | Audit P2 | Needs a new CI job (Ubuntu smoke) and a claim/README decision; orthogonal to the P0/P1 fixes. |
| R-13 cache key path+mtime | Audit P3 | Staleness edge case; no audio corruption. |
| R-14 non-ASCII console output | Audit P3 | Usability sweep across 159 `utilities/` prints; belongs with a utilities pass. |
| R-15 Ruff/mypy target mismatch | Audit P2 | Tooling-only, one-line config + a matrix decision; must not ride along with audio fixes. |
| R-16 README tool count | Audit P3 | Docs truth; render the count from the registry in a docs plan. |
| Q-01–Q-10 maintainability register | Audit §9.2 | Large, structural; needs its own plan with per-family scope. |
| F-01–F-12 market-parity backlog | Audit §9.3 | Feature work; the audit's §9.4 sequencing puts it after this remediation. |
| One-pass concatenated album measurement | A1 (D1) | Accuracy benchmark for material with heavy gating; energy weighting is the shipped fix. |
| APEv2/WavPack support in the scrubber | B2 (D7) | Needs frame-level APEv2 handling for the scrubber's restore logic, not just a loader entry. |
| `continue on error` batch setting | C4 (D10) | A feature; the defect fix is to refuse the dependant, not to offer an override. |
| `py.typed` / PEP 621 metadata | Audit Q-08 | Packaging, no runtime effect. |

Do **not** edit `AUDIT_2026-10-24_suite_report.md` to mark items done — it is the
evidence record. Status lives here, in §7.

---

## 9. Risks and rollback

| Risk | Mitigation |
|---|---|
| The album-gain change moves existing users' album tags on the next run. | That is the fix; the CHANGELOG names it and the wrong values are not "restored" (the old ones were mis-normalising). Track tags are unchanged. |
| ALAC's `.m4a` collides with AAC-M4A output from another run. | Documented (D4); `_claim_output_path` still guards a single run; `-y` overwrite is pre-existing behaviour. |
| A pattern that previously "worked" by resolving to `..` is now refused. | That path escaped the destination; refusal is the intended contract, surfaced as a pattern error with the offending component. |
| Config migration leaves the legacy key behind and a stale canonical key exists. | Migration never overwrites an existing canonical pair; the log line names the source; a user can delete the legacy pair once verified. |
| Exit code 1 on errors breaks a user's script/CI. | Announced in the reference and CHANGELOG; `--json` unchanged; skips remain 0. |
| APEv2 tests modify committed fixtures. | Every test copies the fixture into `tmp_path` first and asserts the source hash is unchanged. |
| Orchestrator skipping changes a batch that "worked" by accident. | The dependant genuinely ran without its input; the note names the failed dependency. |
| The release-notes lock is advanced at the cut instead of at sprint start, so every item commit fails it — or, if the base commit is stale, the scan has nothing to check. | §2.5 step 1 is done before the first item; `test_scan_is_non_vacuous` fails if the changed set is empty. |
| A version is bumped by hand, leaving `uv.lock`, the changelog or a guide subtitle stale. | Only `utilities/release.py`; it reads the version back from the lock, promotes `[Unreleased]`, regenerates `version: auto` guides and compares zip entries. |
| A guide is re-saved by LibreOffice during regeneration and drags `docProps` drift into the cut. | `release.py` accepts only a `word/document.xml` change; regenerate with the dev interpreter that has `python-docx`. |
| Any item's fix reveals a second defect. | Fixed in the same commit with a regression test and a Decision Log entry (AGENTS.md). |

Rollback for every item is a revert of its single commit; no migration is
destructive, no database schema changes, no dependency changes.
