"""
core/pipeline.py
Single-file pipeline processor for Audio Refinery.

Decode once → declick → trim → noise reduction → enhance → encode once →
normalise (FFmpeg)

All stages operate on in-memory audio; the file is only written once,
at the very end of the in-memory chain.  If the normaliser stage is
active it runs FFmpeg on the already-written temp file — this is
unavoidable given FFmpeg's architecture, but still results in only
a single encode for the lossy format portion of the chain.

Failure model
-------------
Any exception in any stage aborts the pipeline for that file.  The
original file is never touched until the final atomic os.replace().
If anything fails before that point the temp file is deleted and the
original is left completely intact.

Tag handling
------------
Tags are read once from the original file before processing begins
and written once to the output file after all stages complete.
The normaliser's own tag handling is deliberately bypassed within
the pipeline since we manage tags ourselves.

Changed in 1.1.0: the enhance stage now runs through
apply_enhancement_chain; the preset supplies the base fields while
the Sprint 1 effect fields come from the CLI-provided params (D13).
"""

from __future__ import annotations

# ── Standard library imports ─────────────────────────────────────────────────
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

# ── Third-party imports ─────────────────────────────────────────────────────
from pydub import AudioSegment

from audio_suite_shared.audio_formats import pydub_export_for_source
from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.dsp_chain import (
    apply_enhancement_chain,
    compute_rms_db,
    post_chain_clip_check,
)
from audio_suite_shared.error_recovery import RetryConfig, retry_with_backoff
from audio_suite_shared.exceptions import (
    AudioProcessingError,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

from .convert import numpy_to_segment, segment_to_numpy
from .integrity import IntegrityResult, validate_file
from .models import FileResult, FileStatus, StageConfig, StageMetrics

# ── First-party imports (setup sys path first) ───────────────────────────────
# Locate suite root so we can import shared helpers and the individual tools.
# pipeline.py lives at <suite_root>/audio_refinery/core/pipeline.py, so
# parents[2] is the suite root.  This insert is a no-op when the suite is
# launched via Master_driver.pyw (which already adds the suite root), but
# makes the module self-sufficient when audio_refinery is run standalone.


logger = logging.getLogger(__name__)

# Default retry config for transient I/O failures (e.g., FFmpeg locked files)
_DEFAULT_RETRY = RetryConfig(max_retries=2, retry_delay=0.5, backoff_factor=2.0)
# Don't create duplicate ErrorLogger - use module logger instead


def _inspect_source_bitrate(source_path: Path) -> tuple[int, bool]:
    """Return (bitrate_kbps, is_vbr) for the source file.

    Uses mutagen when available.  Returns (0, False) if inspection fails
    or mutagen is not installed — callers fall back to default export args.
    """
    try:
        from mutagen import File as MutagenFile

        mf = MutagenFile(str(source_path), easy=False)
        if mf is None:
            return 0, False

        audio_info = getattr(mf, "info", None)
        if audio_info is None:
            return 0, False

        bitrate_kbps = getattr(audio_info, "bitrate", 0) // 1000

        is_vbr = False
        if source_path.suffix.lower() == ".mp3":
            try:
                from mutagen import MutagenError
                from mutagen.mp3 import MP3, BitrateMode

                mp3 = MP3(str(source_path))
                if mp3.info is not None:
                    is_vbr = mp3.info.bitrate_mode in (
                        BitrateMode.VBR,
                        BitrateMode.ABR,
                    )
            except (MutagenError, OSError, ValueError) as exc:
                # VBR detection must stay best-effort: an unreadable or
                # invalid MP3 falls back to "not VBR" rather than failing.
                logger.debug(
                    "VBR probe failed for %s: %s", source_path, exc, exc_info=True
                )

        return bitrate_kbps, is_vbr
    except Exception as exc:
        logger.debug("Bitrate probe failed for %s: %s", source_path, exc, exc_info=True)
        return 0, False


# ── Progress callback type ────────────────────────────────────────────────────
# on_progress(stage_name: str, message: str)
ProgressCallback = Callable[[str, str], None]


def process_file(
    source_path: Path,
    output_path: Path,  # final destination (may equal source for in-place)
    config: StageConfig,
    on_progress: Optional[ProgressCallback] = None,
) -> FileResult:
    """
    Run the full pipeline on a single file.

    Parameters
    ----------
    source_path  : Original audio file.
    output_path  : Where finished file should land.  Pass the same path
                   as source_path for in-place replacement.
    config       : Which stages are active and their parameters.
    on_progress  : Optional callback(stage, message) for real-time UI updates.
                   Called from the worker thread — caller must marshal to Tk
                   main thread via root.after(0, fn).

    Returns
    -------
    FileResult describing every stage outcome.
    """
    result = FileResult(path=source_path)

    def _emit(stage: str, msg: str) -> None:
        logger.info("[%s] %s: %s", stage, source_path.name, msg)
        if on_progress:
            on_progress(stage, msg)

    ext = source_path.suffix.lower()
    # The work file must live on the same volume as output_path —
    # os.replace() cannot move a file across drives (WinError 17).
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path_str = tempfile.mkstemp(suffix=ext, dir=str(output_path.parent))
    os.close(tmp_fd)
    tmp_path = Path(tmp_path_str)

    try:
        # ── 0. Integrity pre-flight check ──────────────────────────────────────
        integrity = _check_integrity(source_path, _emit)
        if not integrity.is_valid:
            result.status = FileStatus.ERROR
            result.error = (
                f"File integrity check failed: {'; '.join(integrity.failures)}"
            )
            return result

        # ── 1. Read tags and decode audio ─────────────────────────────────────
        original_tags, audio = _load_source(source_path, _emit)

        # ── DRY RUN: measure only, skip all modification stages and export ────
        if config.dry_run:
            rms_before = compute_rms_db(segment_to_numpy(audio)[0])
            result.add_stage(
                "DryRun",
                FileStatus.DONE,
                f"Loaded OK (RMS: {rms_before:.1f} dBFS, "
                f"{len(audio)}ms, {audio.channels}ch)",
            )
            _emit("DryRun", f"Skipped all stages (dry run). RMS={rms_before:.1f} dBFS")
            return result

        # ── 2. Pop & Click Removal ────────────────────────────────────────────
        if config.declick:
            audio, msg = _run_declick_stage(audio, config, _emit)
            result.add_stage("Declick", FileStatus.DONE, msg)

        # ── 3. Silence Trimming / Fading ──────────────────────────────────────
        if config.trim:
            audio, msg = _run_trim_stage(audio, config, _emit)
            result.add_stage("Trim", FileStatus.DONE, msg)

        # ── 4. Noise Reduction ────────────────────────────────────────────
        if config.reduce_noise:
            audio, msg = _run_noise_reduction_stage(audio, config, _emit)
            result.add_stage("Noise Reduction", FileStatus.DONE, msg)

        # ── 5. Audio Enhancement ──────────────────────────────────────────────
        if config.enhance:
            audio, msg, metrics = _run_enhance_stage(audio, config, _emit)
            result.add_stage("Enhance", FileStatus.DONE, msg, metrics=metrics)

        # ── 6. Write temp file (single encode, bitrate-aware) ─────────────────
        _write_output(audio, tmp_path, source_path, ext, _emit)

        # ── 7. Restore tags ───────────────────────────────────────────────────
        _emit("Export", "Restoring tags...")
        write_tags_raw(str(tmp_path), original_tags, record_snapshot=False)

        # ── 8. Normalisation (FFmpeg on temp file, with retry) ────────────────
        if config.normalise:
            msg = _run_normalise_stage(tmp_path, config, _emit)
            result.add_stage("Normalise", FileStatus.DONE, msg)

        # ── 9. Atomic replace ─────────────────────────────────────────────────
        _emit("Done", "Complete ✓")
        record_tag_edit_snapshot(str(output_path), "refinery_edit")
        os.replace(str(tmp_path), str(output_path))
        result.status = FileStatus.DONE
        result.was_modified = True

    except Exception as exc:
        mapped = map_to_audio_error(exc, context={"file": source_path.name})
        logger.error(
            "pipeline failed for %s: %s", source_path.name, mapped, exc_info=True
        )
        result.status = FileStatus.ERROR
        result.error = user_message_for(mapped)
        _emit("Error", user_message_for(mapped))

    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug(
                "Temp cleanup could not remove %s: %s", tmp_path, exc, exc_info=True
            )

    return result


# ── Integrity / load / per-stage orchestration helpers ────────────────────────
# Each helper owns its stage's progress messages and maps a stage failure to
# the same AudioProcessingError the inline body used to raise (context names
# the stage); process_file alone touches the FileResult and performs the
# atomic replace.


def _check_integrity(source_path: Path, emit: Callable[..., Any]) -> IntegrityResult:
    """Run the integrity pre-flight for *source_path* and emit the outcome.

    Args:
        source_path: Original audio file.
        emit: Progress callback.

    Returns:
        The integrity result; callers branch on ``is_valid``.
    """
    emit("Validate", "Checking file integrity…")
    integrity = validate_file(source_path)
    if not integrity.is_valid:
        emit("Validate", f"FAILED: {integrity.summary}")
    elif integrity.warnings:
        emit("Validate", f"Warnings: {'; '.join(integrity.warnings)}")
        emit("Validate", f"OK: {integrity.summary}")
    else:
        emit("Validate", f"OK: {integrity.summary}")
    return integrity


def _load_source(
    source_path: Path, emit: Callable[..., Any]
) -> tuple[dict[str, Any], AudioSegment]:
    """Read the original tags and decode the audio into memory.

    Args:
        source_path: Original audio file.
        emit: Progress callback.

    Returns:
        ``(original_tags, audio)`` — tags are written back once, at the end.
    """
    emit("Load", "Reading tags…")
    original_tags = read_tags_raw(str(source_path))

    emit("Load", "Decoding audio…")
    audio: AudioSegment = AudioSegment.from_file(str(source_path))
    return original_tags, audio


def _run_declick_stage(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, str]:
    """Detect and repair clicks, returning ``(audio, stage_message)``.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="declick"``.
    """
    emit("Declick", "Detecting and removing clicks…")
    try:
        from pop_click_remover.core.declicker import declick_audio

        p = config.declick_params
        dc_result = declick_audio(
            audio,
            threshold=p.sensitivity,
            max_width_ms=p.max_width_ms,
        )
        if dc_result.was_modified:
            msg = (
                f"Found and repaired {dc_result.clicks_found} click(s), "
                f"audio quality improved"
            )
        else:
            msg = "No clicks found - audio already clean"
        emit("Declick", msg)
        return dc_result.audio, msg
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        raise AudioProcessingError(
            f"Declick stage failed: {exc}",
            context={"stage": "declick"},
            original=exc,
        ) from exc


def _run_trim_stage(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, str]:
    """Trim leading/trailing silence (and optionally fade).

    Returns:
        ``(audio, stage_message)``.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="trim"``.
    """
    emit("Trim", "Detecting silence…")
    try:
        from silence_trimmer.core.trimmer import trim_and_fade

        tp = config.trim_params
        tr_result = trim_and_fade(
            audio=audio,
            threshold=tp.threshold,
            is_dry_run=False,
            apply_fade=tp.apply_fade,
            fade_in_ms=tp.fade_in_ms,
            fade_out_ms=tp.fade_out_ms,
        )
        if tr_result.trimmed is not None:
            audio = tr_result.trimmed
            # Map the structured result, never `action`: it is human-readable
            # text whose wording is not a stable interface. The old substring
            # match ("trimmed"/"removed" in action) could not fire for any
            # value trim_and_fade actually produces, so a plain trim silently
            # fell through to the generic "audio structure optimized" wording.
            if tr_result.apply_fade:
                msg = f"{tr_result.action}, smooth transitions applied"
            else:
                msg = f"{tr_result.action}, improved flow between sections"
        else:
            msg = "No silence detected - original length maintained"
        emit("Trim", msg)
        return audio, msg
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        raise AudioProcessingError(
            f"Trim stage failed: {exc}",
            context={"stage": "trim"},
            original=exc,
        ) from exc


def _run_noise_reduction_stage(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, str]:
    """Remove hum and broadband noise, returning ``(audio, stage_message)``.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="noise_reduction"``.
    """
    emit("Noise Reduction", "Removing hum and noise…")
    try:
        from noise_reduction.core.noise_reducer import reduce_noise

        nr_params = config.noise_reduction_params
        nr_result = reduce_noise(audio, nr_params)
        if nr_result.was_modified:
            audio = nr_result.audio
            attenuation = nr_result.energy_before_db - nr_result.energy_after_db
            msg = (
                f"Attenuated {attenuation:.1f} dB"
                f" (hum={'on' if nr_params.reduce_hum else 'off'},"
                f" broadband="
                f"{'on' if nr_params.reduce_broadband else 'off'})"
            )
        else:
            msg = "No noise detected — audio already clean"
        emit("Noise Reduction", msg)
        return audio, msg
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        raise AudioProcessingError(
            f"Noise reduction stage failed: {exc}",
            context={"stage": "noise_reduction"},
            original=exc,
        ) from exc


def _run_enhance_stage(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, str, StageMetrics]:
    """Apply the DSP chain, returning ``(audio, stage_message, metrics)``.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="enhance"``.
    """
    emit("Enhance", "Applying DSP chain…")
    try:
        audio, rms_before, rms_after = _run_enhance(audio, config, emit)
        # Get preset name for more descriptive message
        preset_name = config.enhance_params.preset
        gain_db = rms_after - rms_before
        if preset_name == "Mild":
            msg = f"Applied 'Mild' preset ({gain_db:+.1f} dB gain)"
        elif preset_name == "Moderate":
            msg = f"Applied 'Moderate' preset ({gain_db:+.1f} dB gain)"
        elif preset_name == "Aggressive":
            msg = f"Applied 'Aggressive' preset ({gain_db:+.1f} dB gain)"
        else:
            msg = f"Applied 'Custom' preset ({gain_db:+.1f} dB gain)"
        metrics = StageMetrics(
            stage="Enhance",
            before_values={"rms_dbfs": rms_before},
            after_values={"rms_dbfs": rms_after},
        )
        emit("Enhance", msg)
        return audio, msg, metrics
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        raise AudioProcessingError(
            f"Enhance stage failed: {exc}",
            context={"stage": "enhance"},
            original=exc,
        ) from exc


def _write_output(
    audio: AudioSegment,
    tmp_path: Path,
    source_path: Path,
    ext: str,
    emit: Callable[..., Any],
) -> None:
    """Write the processed audio to the temp file (single encode, bitrate-aware).

    Args:
        audio: Processed audio segment.
        tmp_path: Destination temp file (same volume as the final output).
        source_path: Original file, inspected for the export bitrate.
        ext: Lower-case source extension, selecting the export path.
        emit: Progress callback.
    """
    emit("Export", "Writing output file...")
    src_bitrate, src_is_vbr = _inspect_source_bitrate(source_path)

    # Opus/M4A: use ffmpeg_io for format-specific encode quality
    try:
        from audio_enhancer.core.ffmpeg_io import FFMPEG_EXTENSIONS
        from audio_enhancer.core.ffmpeg_io import write_audio as ffmpeg_write

        use_ffmpeg = ext in FFMPEG_EXTENSIONS
    # audio_enhancer.ffmpeg_io is first-party, always present in a valid
    # install (its own ffmpeg-missing failure is an AudioMissingDependency
    # raised at call time, not an ImportError) — a defensive guard only
    # reachable when the suite itself is broken (plan D2).
    except ImportError:  # pragma: no cover
        use_ffmpeg = False

    if use_ffmpeg:
        audio_np, sr = segment_to_numpy(audio)
        ffmpeg_write(audio_np, sr, tmp_path, bitrate_kbps=src_bitrate)
    else:
        fmt, params = pydub_export_for_source(ext, src_bitrate, src_is_vbr)
        audio.export(str(tmp_path), format=fmt, parameters=params)


def _run_normalise_stage(
    tmp_path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
) -> str:
    """Measure loudness and run FFmpeg normalisation with retry.

    Returns:
        The human-readable stage message for the result record.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="normalise"``.
    """
    emit("Normalise", "Measuring loudness…")
    try:
        # Measure loudness BEFORE normalization
        from audio_normalizer.core.loudness import measure

        loudness_data = measure(str(tmp_path), config.normalise_params.target_lufs)

        # Run normalization with retry for transient I/O failures
        normalization_applied = retry_with_backoff(
            _run_normalise,
            _DEFAULT_RETRY,
            "normalise",
            tmp_path,
            config,
            emit,
            loudness_data,
        )

        # Create appropriate message based on whether normalization was applied
        if loudness_data:
            before_lufs = loudness_data.get("input_i", 0.0)
            target_lufs = config.normalise_params.target_lufs
            if normalization_applied:
                msg = (
                    f"Adjusted loudness from"
                    f" {before_lufs:.1f} to"
                    f" {target_lufs:.1f} "
                    f"LUFS for playlist consistency"
                )
            else:
                msg = (
                    f"Loudness already within tolerance"
                    f" ({before_lufs:.1f} LUFS) "
                    f"\u2014 no adjustment needed"
                )
        else:
            # Fallback if measurement failed
            target_lufs = config.normalise_params.target_lufs
            if normalization_applied:
                msg = (
                    f"Adjusted loudness to {target_lufs} LUFS for playlist consistency"
                )
            else:
                msg = "Loudness measurement failed — normalization skipped"
        emit("Normalise", msg)
        return msg
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        raise AudioProcessingError(
            f"Normalise stage failed: {exc}",
            context={"stage": "normalise"},
            original=exc,
        ) from exc


# ── Enhancement stage helper ──────────────────────────────────────────────────


def _run_enhance(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, float, float]:
    """
    Apply the pedalboard DSP chain to an AudioSegment.

    Converts AudioSegment → numpy → pedalboard → numpy → AudioSegment.
    The conversion is lossless (integer reinterpretation, no encode/decode).
    Output Gain is set to 0 when the normaliser stage is active, since the
    normaliser will manage the final level.

    Uses the shared ``audio_suite_shared.dsp_chain.build_enhancement_chain()``
    so the pipeline and standalone Audio Enhancer share a single source of
    truth for the DSP chain construction.

    NOTE (accepted constraint, approved in PLAN_gap_analysis 1.4a): pedalboard
    always converts its input buffer to float32 internally for processing and
    returns float32 — see the canonical note in
    audio_enhancer/core/processor.py. The DSP math (noise gate, compressor,
    EQ, limiter) therefore runs in float32 precision here too; this is a hard
    ceiling of the library and is not fixable at this call site.
    """
    from audio_enhancer.core.models import PRESETS, EnhancementParams, PresetName

    p = config.enhance_params

    # Resolve preset — if not Custom, load the preset values
    try:
        preset_enum = PresetName(p.preset)
    except ValueError:
        preset_enum = PresetName.MODERATE

    # Use preset values as the parameter source, falling back to custom (p) if CUSTOM
    source = PRESETS[preset_enum] if preset_enum != PresetName.CUSTOM else p
    # Suppress output gain when the normaliser stage will manage final level
    output_gain = 0.0 if config.normalise else source.output_gain_db
    # Sprint 1 effects always come from the refinery's EnhanceParams (never
    # from the preset table), so the driver/GUI effect toggles survive a
    # non-Custom preset selection (D13).
    ep = EnhancementParams(
        noise_gate_threshold_db=source.noise_gate_threshold_db,
        compressor_threshold_db=source.compressor_threshold_db,
        compressor_ratio=source.compressor_ratio,
        compressor_attack_ms=source.compressor_attack_ms,
        compressor_release_ms=source.compressor_release_ms,
        low_shelf_gain_db=source.low_shelf_gain_db,
        low_shelf_freq_hz=source.low_shelf_freq_hz,
        presence_gain_db=source.presence_gain_db,
        presence_freq_hz=source.presence_freq_hz,
        high_shelf_gain_db=source.high_shelf_gain_db,
        high_shelf_freq_hz=source.high_shelf_freq_hz,
        output_gain_db=output_gain,
        limiter_threshold_db=source.limiter_threshold_db,
        reverse=p.reverse,
        karaoke=p.karaoke,
        karaoke_strength=p.karaoke_strength,
        phaser=p.phaser,
        flanger=p.flanger,
        chorus=p.chorus,
    )

    emit("Enhance", "Converting to numpy…")
    audio_np, sample_rate = segment_to_numpy(audio)

    rms_before = compute_rms_db(audio_np)

    emit("Enhance", "Applying DSP…")
    enhanced_np = apply_enhancement_chain(audio_np, sample_rate, ep)
    post_chain_clip_check(enhanced_np, stage_name="Enhance")

    rms_after = compute_rms_db(enhanced_np)

    emit(
        "Enhance",
        f"Level: {rms_before:.1f} -> {rms_after:.1f}"
        f" dBFS ({rms_after - rms_before:+.1f} dB)",
    )

    emit("Enhance", "Converting back to audio…")
    enhanced_audio = numpy_to_segment(
        enhanced_np,
        sample_rate=sample_rate,
        sample_width=audio.sample_width,
        num_channels=audio.channels,
    )
    return enhanced_audio, rms_before, rms_after


# ── Normalisation stage helper ────────────────────────────────────────────────


def _run_normalise(
    tmp_path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
    loudness_data: dict[str, float] | None = None,
) -> bool:
    """
    Run FFmpeg loudnorm on the already-written temp file.
    Tags are re-read and re-written around the FFmpeg call since FFmpeg
    strips them during re-encoding.

    Args:
        tmp_path: Path to the temp audio file.
        config: Stage configuration.
        emit: Progress callback.
        loudness_data: Pre-computed loudness data from a prior measurement.
            If None, will measure internally.

    Returns
    -------
    bool: True if normalization was applied, False if skipped (already within tolerance)
    """
    from audio_normalizer.core.loudness import measure
    from audio_normalizer.core.normalizer import apply

    target = config.normalise_params.target_lufs

    if loudness_data is None:
        emit("Normalise", f"Measuring loudness (target {target} LUFS)…")
        loudness_data = measure(str(tmp_path), target)
    if loudness_data is None:
        # FFmpeg returned no usable data (e.g. very quiet or unusual encoding).
        # Warn and skip rather than aborting the whole file.
        emit("Normalise", "⚠ Loudness measurement failed — Normalise stage skipped")
        logger.info("Normalise skipped for %s: measure() returned None", tmp_path.name)
        return False

    current_i = loudness_data.get("input_i", 0.0)
    tolerance = config.normalise_params.tolerance
    if abs(current_i - target) <= tolerance:
        emit("Normalise", f"Already within tolerance ({current_i:.1f} LUFS) — skipped")
        return False

    emit("Normalise", f"Normalising {current_i:.1f} → {target} LUFS…")
    # apply() handles its own temp-file swap and tag restoration internally.
    # The pipeline records the undo snapshot itself, so apply() must not.
    apply(str(tmp_path), target, loudness_data, record_snapshot=False)
    emit("Normalise", "Normalisation complete")
    return True
