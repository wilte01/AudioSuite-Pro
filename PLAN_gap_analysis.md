# PLAN_gap_analysis.md — Consolidated Gap & Work Plan

**Created:** 2026-09-01 · **Status legend:** `[ ]` pending · `[~]` in progress · `[x]` done
**Nature:** Functional gap analysis vs. nearest equivalents (iZotope RX, dBpoweramp,
MusicBrainz Picard, MP3Tag), consolidated with the retained items from
`enhancements/00_roadmap.md` into a single, **audio-quality-first**, dependency-aware plan.

## Scope decisions (approved by Wilte)

| Item | Decision |
|---|---|
| Playlist Generator (#5) | **Dropped** — playlists are generated in MusicBee from the tags this suite writes. |
| Audio Fingerprinting (#1) | **Dropped** — after a suite run, AudioSuite-Pro user runs MusicBrainz Picard to gather any missing tags. |
| 2.1 A/B playback dep | **Approved** — use `sounddevice` (BSD/MIT, portable, no redistribution restriction). |
| 4.4 Completeness Dashboard | **Kept** as a low-priority roadmap entry (implemented 2026-09-04). |
| 1.4b WAV depth | **Default to depth-preserving behaviour automatically** (with configurable override). |
| Selection filter | Only items directly improving **audible audio quality**; non-qualitative roadmap items retained but low-priority. |
| Quality baselines | Folded in as a continuous foundation gate — every merged item must pass. |

---

## Track 0 — Foundation (continuous gate on every merge)

- **0.1** Finish `PLAN_quality_baselines.md` (in progress): `mypy . --strict` → **0 errors**;
  pytest coverage → **≥75 %** (currently 73.93 %, deficit 212 lines to gate). Every merge must
  pass ruff / mypy --strict / bandit / pytest (with cov gate). **[x]**
- **0.2** Confirm DSP building blocks in hand: `scipy`, `numpy`, `librosa` (analysis extra).
  No new third-party deps without approval; **approved this session: `sounddevice`** (for 2.1). **[x]**

---

## Phase 1 — Correctness & fidelity fixes (highest quality-per-effort)

### 1.1 Normalizer silent MP3 fallback **[x]**
`audio_normalizer/core/normalizer.py` + `loudness.py`: extensions outside `_FORMAT_CODEC` silently
re-encode as MP3 (`libmp3lame -q:a 0`) and keep the original extension.
**Quality impact:** a `.wav`/`.aiff`/unknown file can be lossily re-encoded as MP3 with no warning.
**Fix:** reject unmapped extensions with `AudioSuiteError`; if intended, add `.wav`/`.aiff` to the
codec map. **Tests:** unmapped extension → error path.

### 1.2 `.wma` scrubber defect **[x]**
`metadata_scrubber/core/scrubber.py` lists `.wma` in `SUPPORTED_EXTENSIONS` but `_load_audio()`
does not handle it → every `.wma` fails at load. **Fix:** remove `.wma` from discovery or implement
a real handler. **Tests:** `.wma` no longer enumerated or loads correctly.

### 1.3 Align format sets **[x]**
`audio_enhancer/core/inspector.py` `SUPPORTED_EXTENSIONS` differs from canonical
`audio_suite_shared/audio_formats.py` (adds `.aif`, omits `.mp4`). Unify to the shared tuple.
**Tests:** enhancer/refinery accept the same file set.

### 1.4 DSP fidelity **[x]**
- **1.4a Pedalboard float32:** `dsp_chain.py` / `audio_enhancer/core/processor.py` — pedalboard
  converts to float32 internally, so the enhancement chain cannot reach float64 (hard library
  ceiling affecting Enhancer + Refinery). Verify it is truly unavoidable; if so, **document as an
  accepted constraint** (approved).
- **1.4b WAV depth:** `music_format_converter/core/ffmpeg_params.py` is hardcoded `pcm_s16le`, so
  lossless 24/32-bit or float source is silently reduced to 16-bit on WAV output.
  **Fix (approved):** **default to depth-preserving behaviour automatically**, with a configurable
  override (16/24/32-bit / float). **Tests:** 24-bit FLAC → 24-bit WAV path; override respected.

---

## Phase 2 — Verification capability (enables trusting the quality pipeline)

### 2.1 A/B playback / audition in DSP GUIs **[x]**
Add before/after listening to **Audio Enhancer, Audio Refinery, Normalizer, Pop & Click Remover,
Silence Trimmer**. The suite currently has no audio auditioning in the GUI layer.
**Implementation:** handle_audio_errors decorator; a shared playback util using **`sounddevice`**
(approved; BSD/MIT, portable); export a temp `.wav` via pydub; "Play original / Play result"
buttons on the results tab. **Tests:** playback util mocked to a fake player; GUI buttons tested
via `object.__new__` + `MagicMock` pattern.

---

## Phase 3 — Restoration capability (biggest genuine functionality gap)

### 3.1 Noise / hum reduction tool **[x]**
The suite removes clicks & pops but had **no broadband-noise, hiss, or AC-hum suppression**
(a core iZotope RX feature) — now shipped as `noise_reduction/`.
**New tool:** `noise_reduction/` following the standard package layout
(`app.py`, `cli.py`, `core/`, `ui/`, `utils/`, `tests/test_<module>.py`).
- **Hum (50/60 Hz + harmonics):** comb/notch filtering in the frequency domain (`scipy.signal`).
  Deterministic, low effort.
- **Broadband noise / hiss:** spectral-gating reduction using a learned **noise print** from a
  user-selected silent region (STFT-based), then subtractive / spectral-gating (`scipy`).
- Dry-run, `BaseFileProcessor` concurrency, `_refinery_completed.log` registry pattern matching
  existing suite conventions; optional pre-flight integration in Audio Refinery.
- CLI `audiosuite reduce`; Master Driver card.
- **No new third-party deps** (scipy present). **Tests:** synthetic tonal hum removed (residual
  energy below threshold); noise-print path; dry-run; corrupt/unsupported inputs; lockstep test files.

---

## Phase 4 — Existing roadmap items (retained, prioritised by relevance)

- **4.1 Error-handling adoption (#9)** — migrate 10+ tools to `@handle_audio_errors` +
  `show_error_from_exception()`. *Reliability, not audible quality* — cheap, underpins Phase 1–3. **[x]**
- **4.2 File Integrity Checker (#4)** — protect the Refinery from corrupt/truncated files before
  expensive DSP. *Supports quality* — do before Phase 3 (guards 3.1 runs on sound files). **[x]**
- **4.3 Cover Art Enrichment Pipeline (#3)** — filter+rank artwork across GUI/CLI/Master Driver.
  *Metadata, not audible* — lowest priority. **[x]**
- **4.4 Tag Completeness Dashboard (#6)** — visibility into missing tags. *Metadata visibility, not
  audible* — **kept as low-priority entry** (per Wilte). **[x]**

---

## Recommended dependency-aware ordering

```
Phase 1 (1.1,1.2,1.3,1.4) ──► Phase 2 (2.1 A/B audition)
        │                            │
        └────────────► 4.2 (integrity)  ──► Phase 3 (3.1 noise/hum)
4.1 / 4.3 / 4.4 — parallel, low priority, non-qualitative
Track 0 (quality gates) — continuous on every merge
```

Rationale: fix active quality-damaging bugs first (Phase 1); add A/B audition (Phase 2) so any new
DSP is verifiable; add integrity pre-flight (4.2) before the new noise/hum DSP (Phase 3) so expensive
processing is never wasted on corrupt files; defer the non-qualitative roadmap items (4.1/4.3/4.4).

---

## Progress log

| Date | Item | Note |
|---|---|---|
| 2026-09-01 | — | Plan created per Wilte's scope decisions. No implementation started. |
| 2026-09-02 | 0.1 | **Coverage gate met: 75.00%** (14,928/19,903). Key deliverables — `mypy . --strict` 0 errors (363 files); full suite **5,191 passed, 6 skipped, 0 failed** (~106 s); ruff clean; bandit `-c pyproject.toml` 76 pre-existing non-test findings (unchanged — session touched only test files). Notable coverage work: `key_manager.py` and `file_processor_base.py` to 100%; `ui_common.py` to 100% except hover callbacks (unbindable via tests — Python 3.14 Tk `_bind` signature incompatibility); new `test_cli_base.py` + `test_tag_helper_art.py`. **Explicit config flag needed:** bandit must be invoked as `-m bandit -c pyproject.toml -r <packages>`; without `-c` the `[tool.bandit]` skips (B101/B404) are not auto-discovered. |
| 2026-09-02 | 2.1 | **A/B audition shipped in all 5 DSP GUIs.** Key deliverables — shared `audio_playback.py` (sounddevice playback via pydub temp-WAV; stop/interrupt-and-join so Play clicks replace — never stack — streams; stdlib `wave`+numpy `_read_wav`; snapshot helpers capturing originals before in-place overwrites) and `ui_audition.py` (`add_audition_buttons` + `AuditionMixin`; worker-thread-safe state marshalled via `root.after`). Play Original / Play Result on every Results tab; Dry Run disables Play Result; window close stops playback and clears snapshots. Gates: `mypy . --strict` 0 errors (365 files); full suite **5,268 passed, 6 skipped, 0 failed**; coverage **75%**; ruff clean; bandit pre-existing findings unchanged. New `test_audio_playback.py` + `test_ui_audition.py` + audition integration tests in all 5 tools' `test_app.py`. Guides: audition entry added to the 5 tools' DOCX user guides. Runtime: `sounddevice` 0.5.6 installed into the suite's global Python 3.14 **and** `.venv` (tools launch via the global interpreter, not the venv). Live-testing fixes, both verified on-device: phantom `sounddevice.read()` replaced with a real WAV reader (worker failures now logged — no more silent thread death under pythonw); stacked simultaneous playback eliminated (interrupt + join before each new play, join on stop). |
| 2026-09-03 | 4.2 | **File Integrity Checker shipped in Audio Refinery.** New `audio_refinery/core/integrity.py` validates files before any DSP runs: existence/readability, size bounds (100 B – 4 GB), extension check, container magic bytes (WAV/AIFF/FLAC/Ogg/MP3/MP4), pydub decode test, and audio-property bounds (sample rate 8–192 kHz, duration 10 ms–24 h, 1–8 channels). Returns an `IntegrityResult` (PASS/WARN/FAIL); corrupt/truncated files are rejected by `process_file` with a clear "File integrity check failed" error and never reach the expensive chain (dry-run included). Also adds `check_integrity_batch()` / `validate_files()` / `filter_valid()` / `filter_invalid()` helpers for a future pre-scan. Gates: `mypy --strict` clean for the new module (0 errors; repo-wide 0 errors — only pre-existing mutagen findings outside scope), `ruff` clean, bandit clean (1 `# nosec` on the PASS enum string — status value, not a credential), full suite **5,300 passed, 6 skipped, 0 failed**, coverage **75.55%** (module itself **96%**). New `test_integrity.py` (37 tests incl. pipeline integration) + autouse `validate_file` patch fixtures in `test_pipeline_stages.py` and `tests/test_refinery_pipeline.py` (existing tests use placeholder bytes with pydub mocked at the module boundary). User guides: audit — feature is a transparent reliability gate (corrupt files now get a clearer pre-flight error); no DOCX guide change required. |
| 2026-09-04 | 4.1 | **Error-handling adoption completed.** Migrated the remaining tools to `@handle_audio_errors` + `show_error_from_exception()`: `ui_helpers.show_error_from_exception` + browse-dialog migration; `error_logger.log_and_show_error` marked deprecated with legacy string→`AudioSuiteError` name mapping; adoption in asx_extractor, cd_ripper, file_reorganizer, library_stats (`_scan_worker`), bpm_analyzer. Sole remaining in-package `log_and_show_error` reference is the deprecated wrapper itself. Pure-internal reliability change — no DOCX guide updates required. |
| 2026-09-04 | 4.3 | **Cover Art sync CLI residue completed.** `album_art_sync/utils/cli_args.py`: `ArtArgs` gains `min_art_dimension` (200–2000, default `MIN_ART_DIMENSION=500`) and `album_match_threshold` (0.0–1.0, default `ALBUM_MATCH_THRESHOLD=0.85`) parsed from `--min-dimension` / `--match-threshold` (non-numeric → stderr + exit 1). `album_art_sync/app.py` forwards both to `source_resolver.resolve(...)` using pre-parsed CLI values where the Master Driver supplied them, else suite defaults. Tests added/updated in `test_cli_args.py` + `test_album_art_sync.py`. album_art_sync suite 243 passed; compile gate 0; ruff clean; no new mypy errors. No DOCX guide change required (Driver now forwards its existing slider values — user-visible behaviour unchanged). |
| 2026-09-04 | 4.4 | **Tag Completeness Dashboard shipped in Library Stats.** Core `library_stats/core/completeness.py`: `TAG_FIELDS` (bpm/key/genre/mood/tempo_marking/album_art/replaygain), frozen dataclasses `TagCompleteness` (with `.label`) + `CompletenessReport.to_dict()`, `analyse_completeness(directory, *, progress_callback=None)`, `export_completeness_csv/json` — read-only, unreadable files count every field missing (logged). Shared readers: `audio_suite_shared.tag_helper_base` gains `has_artwork()` + `read_replaygain()` for MP3/ID3 (APIC + TXXX), FLAC/Ogg/Opus (pictures / replaygain), MP4 (covr + iTunes atoms), with `tag_helper_reader` facades re-exported via `tag_helper`. GUI: 4th "Completeness" notebook tab — Canvas bars (>80% green, 50–80% amber, <50% red), overall %, Save CSV/JSON, missing-files viewer; `_scan_worker` populates it. CLI: `audiosuite stats --completeness [--detail <tag>]`, JSON payload gains `completeness` key. Tests: `test_tag_helper_completeness.py` (26), `test_completeness.py` (reports/exports/progress/error paths), `test_cli.py` (12, incl. CliRunner integration with reader patches). Gates: full suite **5,391 passed, 6 skipped, 0 failed**; coverage **75.60%**; ruff clean; compile gate 0; bandit 0 findings in 4.4 files (1 pre-existing LOW in untouched `file_processor.py`); mypy 0 new errors (14 pre-existing remain in the 4.4-touched files: mutagen attr-defined + matplotlib `dict_values/dict_keys→pie` + untyped FigureCanvasTkAgg). |
| 2026-09-04 | 3.1 | **Noise/Hum Reduction shipped** — verified in-repo (implemented in an earlier session; plan marker was stale). `noise_reduction/` full package: `core/noise_reducer.py` (hum: scipy notch comb at 50/60 Hz ± harmonics, Q 1–50; broadband: spectral-gating from a user-selected noise-print region, gate threshold 0–12 dB; stereo + silence/short-input guards), `core/models.py`, `core/file_processor.py`, GUI (`app.py` + `ui/` with dry-run/live + driver mirror vars), `utils/cli_args.py`, lockstep `tests/` (81). CLI `audiosuite reduce` (`--reduce-hum --hum-frequency 50|60 --hum-harmonics --hum-quality`, `--reduce-broadband --noise-start --noise-end --gate-threshold`, `--dry-run`); Master Driver `noise_reduction_card.py` + `_build_noise_reduction_args`; registered in shared `cli_app.py`. User guide exists at `user_guides/individual_programs/noise_reduction/` (with generator). Gates (re-run to confirm): noise_reduction suite **89 passed in 2.40s**; full suite **5,391 passed, 6 skipped, 0 failed**, coverage **75.60%**; ruff clean; bandit `-c pyproject.toml` **0 findings**; mypy strict **0 new errors** (9 pre-existing mutagen findings surfaced only via the shared-import chain). |

(End of file - total 127 lines)
