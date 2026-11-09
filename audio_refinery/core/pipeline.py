"""
core/pipeline.py
Single-file pipeline processor for Audio Refinery.

Decode once → declick → trim → noise reduction → enhance → encode once →
normalise (FFmpeg)

Changed in 2.1.7: the final encode goes through ``get_export_args``, which pins
a lossless source's PCM bit depth - a 24-bit WAV used to come back 16-bit
(F-10).

Changed in 2.3.1 (U-02): a file no enabled stage changed is left
byte-identical (no export, tag rewrite, snapshot or replace), the Dry Run runs
the enabled stages' detection instead of only loading the file, and a
normalise-only run applies FFmpeg loudnorm directly to the source in one pass.

Changed in 2.6.0 (U-04): the normalise stage carries the standalone Audio
Normalizer's delivery set — a true-peak ceiling, an LRA target and the
lossless MP3 ``global_gain`` path — because the standalone window that used to
offer them is gone.

Changed in 2.5.0: album mode (F-E1).  ``process_file`` takes the run's
``AlbumPlan``, and the Normalise stage applies that plan's gain for the source
instead of measuring the file it is writing; ``_run_normalise_stage``,
``_run_normalise_in_place`` and ``_preview_normalise`` each take an
``album``/``album_key`` pair.  A zero planned gain writes nothing, which keeps
the no-op rule intact.

Changed in 2.5.0: exact time-range trim (F-E3).  The Trim stage keeps the
configured millisecond span instead of detected silence when
``TrimParams.mode`` is ``"exact"``, and ``copy_mode`` cuts the source's frames
with one stream copy (no decode, no other stage) and reports the length
``ffprobe`` measures in the result rather than the length that was asked for.

All stages operate on in-memory audio; a run that changed something writes
the file once, at the end of the in-memory chain.  The normaliser needs a
file, so a mixed run writes the processed audio to a temp file and then
normalises that file; when the normaliser is the only stage with work to do,
it runs on the source directly, which is one encode instead of two.

Failure model
-------------
Any exception in any stage aborts the pipeline for that file.  A write is
always atomic and always preceded by its undo snapshot: the direct-normalise
path swaps the source only after loudnorm succeeded, and every other run
replaces the destination with the finished temp file at the very end.  If
anything fails the temp file is deleted and the original is left intact.

Tag handling
------------
Tags are read once from the original file before processing begins and
written once to the output file after all stages complete.  A direct
normalise reuses ``audio_normalizer``'s own tag preservation because FFmpeg
strips them while re-encoding.

Changed in 1.1.0: the enhance stage now runs through
apply_enhancement_chain; the preset supplies the base fields while
the Sprint 1 effect fields come from the CLI-provided params (D13).
"""

from __future__ import annotations

# ── Standard library imports ─────────────────────────────────────────────────
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

# ── Third-party imports ─────────────────────────────────────────────────────
from pydub import AudioSegment

# Changed in 2.4.3: C-I7 removed the core/convert.py re-export shim, so the
# conversion helpers come from their canonical home.
from audio_suite_shared import audio_probe
from audio_suite_shared.audio_conversion import numpy_to_segment, segment_to_numpy
from audio_suite_shared.audio_formats import (
    preserve_depth_params,
    pydub_export_for_source,
)
from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.dsp_chain import (
    apply_enhancement_chain,
    compute_rms_db,
    post_chain_clip_check,
)
from audio_suite_shared.error_recovery import RetryConfig, retry_with_backoff
from audio_suite_shared.exceptions import (
    AudioConfigurationError,
    AudioProcessingError,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.ffmpeg import FFMPEG_PATH
from audio_suite_shared.lossless_gain import apply_track_gain, is_mp3_file
from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

from .integrity import IntegrityResult, validate_file
from .models import (
    EXACT_TRIM_MODE,
    FileResult,
    FileStatus,
    StageConfig,
    StageMetrics,
)
from .trim import (
    check_copy_extension,
    check_copy_mode,
    copy_trim,
    exact_preview_message,
    exact_trim_message,
    probe_duration_ms,
    resolve_range,
    slice_segment,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from audio_normalizer.core.album import AlbumPlan

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


def _same_file(source_path: Path, output_path: Path) -> bool:
    """Return ``True`` when the run replaces *source_path* in place."""
    try:
        return os.path.normcase(str(source_path.resolve())) == os.path.normcase(
            str(output_path.resolve())
        )
    except OSError:  # pragma: no cover - defensive on odd Windows paths
        return source_path == output_path


def _has_processing_stage(config: StageConfig) -> bool:
    """Return ``True`` when a stage that writes audio is enabled."""
    return bool(config.declick or config.trim or config.reduce_noise or config.enhance)


def _no_op_reason(config: StageConfig) -> str:
    """Explain why a run wrote nothing, for the skipped-file log line."""
    if not _has_processing_stage(config) and not config.normalise:
        return "No stages enabled - file left untouched"
    return "No changes needed - file left untouched"


def _run_exact_copy_trim(
    source_path: Path,
    output_path: Path,
    config: StageConfig,
    result: FileResult,
    emit: Callable[..., Any],
    temp_path: Callable[[], Path],
) -> FileResult:
    """Cut the exact range with one stream copy and finish the file.

    A stream copy never decodes the audio, so it cannot feed the in-memory
    chain: this is the stage's whole write path for ``copy_mode``, and
    :func:`audio_refinery.core.trim.check_copy_mode` has already refused every
    stage that would need decoded samples.

    Args:
        source_path: File to read.
        output_path: Final destination (may equal the source for in-place).
        config: The run's stage configuration.
        result: The file result this path records into.
        emit: Progress callback.
        temp_path: Returns the staging file, beside ``output_path``.

    Returns:
        ``result``, DONE when the copy was written and DONE-without-writing for
        a Dry Run.
    """
    tp = config.trim_params
    check_copy_extension(source_path)
    source_ms = probe_duration_ms(source_path)
    exact_range = resolve_range(tp, int(round(source_ms)))

    if config.dry_run:
        message = exact_preview_message(exact_range)
        result.add_stage("Trim", FileStatus.DONE, message)
        result.add_stage("DryRun", FileStatus.DONE, "Nothing written")
        result.status = FileStatus.DONE
        result.was_modified = False
        emit("Trim", message)
        emit("DryRun", "Dry run complete — nothing written")
        return result

    emit("Trim", "Copying the exact range without re-encoding…")
    measured = copy_trim(source_path, temp_path(), exact_range)
    message = exact_trim_message(exact_range, measured, copy_mode=True)
    result.add_stage(
        "Trim",
        FileStatus.DONE,
        message,
        metrics=StageMetrics(
            stage="Trim",
            before_values={"duration_ms": source_ms},
            after_values={"duration_ms": measured},
        ),
    )
    record_tag_edit_snapshot(str(output_path), "refinery_edit")
    os.replace(str(temp_path()), str(output_path))
    emit("Done", "Complete ✓")
    result.status = FileStatus.DONE
    result.was_modified = True
    return result


def process_file(
    source_path: Path,
    output_path: Path,  # final destination (may equal source for in-place)
    config: StageConfig,
    on_progress: Optional[ProgressCallback] = None,
    album_plan: AlbumPlan | None = None,
) -> FileResult:
    """
    Run the full pipeline on a single file.

    A run that changed nothing leaves the destination byte-identical: no
    export, tag rewrite, undo snapshot or replace.  The exception is a
    copy-out run (``output_path`` differs from ``source_path``), which always
    produces its destination file, copying the source bytes when no stage
    modified the audio.

    Parameters
    ----------
    source_path  : Original audio file.
    output_path  : Where finished file should land.  Pass the same path
                   as source_path for in-place replacement.
    config       : Which stages are active and their parameters.
    on_progress  : Optional callback(stage, message) for real-time UI updates.
                   Called from the worker thread — caller must marshal to Tk
                   main thread via root.after(0, fn).
    album_plan   : The run's album plan, or ``None`` outside album mode.  Its
                   gain for this file replaces the per-file measurement; the
                   plan is measured once per run, never per worker (F-E1).

    Returns
    -------
    FileResult describing every stage outcome.  A no-op run is SKIPPED with
    the reason in ``error``; a Dry Run is DONE and never writes.
    """
    result = FileResult(path=source_path)

    def _emit(stage: str, msg: str) -> None:
        logger.info("[%s] %s: %s", stage, source_path.name, msg)
        if on_progress:
            on_progress(stage, msg)

    ext = source_path.suffix.lower()
    in_place = _same_file(source_path, output_path)
    # The work file must live on the same volume as output_path —
    # os.replace() cannot move a file across drives (WinError 17).  It is
    # created lazily so a Dry Run and a no-op leave no temp file at all.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Optional[Path] = None

    # Album mode keys the plan by the *source*: a staged copy lives under a
    # temp name the plan never saw.
    album_key = ""
    if album_plan is not None:
        from audio_normalizer.core.album import plan_key

        album_key = plan_key(source_path)

    def _temp_path() -> Path:
        """Create (once) and return the temp file beside the destination."""
        nonlocal tmp_path
        if tmp_path is None:
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                suffix=ext, dir=str(output_path.parent)
            )
            os.close(tmp_fd)
            tmp_path = Path(tmp_path_str)
        return tmp_path

    try:
        # Copy mode is a whole-file decision: refuse it before any file work
        # when a stage in this run would have to decode the audio.
        check_copy_mode(config)

        # ── 0. Integrity pre-flight check ──────────────────────────────────────
        integrity = _check_integrity(source_path, _emit)
        if not integrity.is_valid:
            result.status = FileStatus.ERROR
            result.error = (
                f"File integrity check failed: {'; '.join(integrity.failures)}"
            )
            return result

        # ── Exact copy trim: one stream copy, no decode ───────────────────────
        # Re-encode keeps the range inside the in-memory chain below; a stream
        # copy cannot, so it is its own write path and check_copy_mode has
        # already refused every stage that would need decoded samples.
        tp = config.trim_params
        if config.trim and tp.mode == EXACT_TRIM_MODE and tp.copy_mode:
            return _run_exact_copy_trim(
                source_path, output_path, config, result, _emit, _temp_path
            )

        # ── 0b. The Normalise stage's container capability ───────────────────
        # A container the stage has no encoder for is a known limit, not a
        # failure.  It is decided once, before any stage work, so the file
        # reports the reason and the other enabled stages still do their work.
        normalise_reason = (
            _normalise_skip_reason(source_path, config) if config.normalise else None
        )
        wants_normalise = config.normalise and normalise_reason is None
        # Enhancement suppresses its output gain for a normalise that will run;
        # a skipped normalise must not silence the gain it is not replacing.
        stage_config = replace(config, normalise=False) if normalise_reason else config

        # ── 1. Read tags and decode audio ─────────────────────────────────────
        original_tags, audio = _load_source(source_path, _emit)

        # ── 2. Dry run: detect with every enabled stage, write nothing ────────
        if config.dry_run:
            _run_dry_run(
                audio, source_path, config, result, _emit, album_plan, album_key
            )
            result.status = FileStatus.DONE
            result.was_modified = False
            return result

        # The dry run already reported the reason through ``_preview_normalise``;
        # a live run records the skipped stage once, before the other stages.
        if normalise_reason is not None:
            result.add_stage("Normalise", FileStatus.SKIPPED, normalise_reason)

        # ── 3. Pop & Click Removal ────────────────────────────────────────────
        modified = False
        if config.declick:
            audio, msg, changed = _run_declick_stage(audio, stage_config, _emit)
            modified = modified or changed
            result.add_stage("Declick", FileStatus.DONE, msg)

        # ── 4. Silence Trimming / Fading ──────────────────────────────────────
        if config.trim:
            audio, msg, changed = _run_trim_stage(audio, stage_config, _emit)
            modified = modified or changed
            result.add_stage("Trim", FileStatus.DONE, msg)

        # ── 5. Noise Reduction ────────────────────────────────────────────
        if config.reduce_noise:
            audio, msg, changed = _run_noise_reduction_stage(audio, stage_config, _emit)
            modified = modified or changed
            result.add_stage("Noise Reduction", FileStatus.DONE, msg)

        # ── 6. Audio Enhancement ──────────────────────────────────────────────
        if config.enhance:
            audio, msg, metrics = _run_enhance_stage(audio, stage_config, _emit)
            # The DSP chain always applies, so an enabled Enhance stage is a
            # change even when the level barely moves.
            modified = True
            result.add_stage("Enhance", FileStatus.DONE, msg, metrics=metrics)

        # ── 7. Nothing changed: normalise directly, or write nothing ─────────
        if not modified:
            if in_place:
                if wants_normalise:
                    msg, modified = _run_normalise_in_place(
                        source_path,
                        config,
                        _emit,
                        album=album_plan,
                        album_key=album_key,
                    )
                    result.add_stage("Normalise", FileStatus.DONE, msg)
                if not modified:
                    result.status = FileStatus.SKIPPED
                    # The container reason is the useful one: "no changes
                    # needed" would hide why the stage never ran.
                    result.error = normalise_reason or _no_op_reason(stage_config)
                    _emit("Done", result.error)
                    return result
                _emit("Done", "Complete ✓")
                result.status = FileStatus.DONE
                result.was_modified = True
                return result

            # Copy-out: the destination is the deliverable, so produce it —
            # a byte copy when nothing changed, then one loudnorm pass on it.
            _emit("Export", "Copying to output folder...")
            record_tag_edit_snapshot(str(output_path), "refinery_edit")
            shutil.copy2(source_path, output_path)
            if wants_normalise:
                msg, _applied = _run_normalise_stage(
                    output_path,
                    config,
                    _emit,
                    album=album_plan,
                    album_key=album_key,
                )
                result.add_stage("Normalise", FileStatus.DONE, msg)
            _emit("Done", "Complete ✓")
            result.status = FileStatus.DONE
            result.was_modified = True
            return result

        # ── 8. Write temp file (single encode, bitrate-aware) ─────────────────
        staged = _temp_path()
        _write_output(audio, staged, source_path, ext, _emit)

        # ── 9. Restore tags ───────────────────────────────────────────────────
        _emit("Export", "Restoring tags...")
        write_tags_raw(str(staged), original_tags, record_snapshot=False)

        # ── 10. Normalisation (FFmpeg on temp file, with retry) ────────────────
        if wants_normalise:
            msg, _applied = _run_normalise_stage(
                staged,
                config,
                _emit,
                album=album_plan,
                album_key=album_key,
            )
            result.add_stage("Normalise", FileStatus.DONE, msg)

        # ── 11. Atomic replace ────────────────────────────────────────────────
        _emit("Done", "Complete ✓")
        record_tag_edit_snapshot(str(output_path), "refinery_edit")
        os.replace(str(staged), str(output_path))
        result.status = FileStatus.DONE
        result.was_modified = True

    except AudioConfigurationError as exc:
        # A configuration refusal is the user's to fix and already states why;
        # mapping it to a generic audio error would hide the reason.
        logger.error(
            "pipeline refused %s: %s", source_path.name, exc.message, exc_info=True
        )
        result.status = FileStatus.ERROR
        result.error = exc.message
        _emit("Error", exc.message)

    except Exception as exc:
        mapped = map_to_audio_error(exc, context={"file": source_path.name})
        logger.error(
            "pipeline failed for %s: %s", source_path.name, mapped, exc_info=True
        )
        result.status = FileStatus.ERROR
        result.error = user_message_for(mapped)
        _emit("Error", user_message_for(mapped))

    finally:
        if tmp_path is not None:
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
) -> tuple[AudioSegment, str, bool]:
    """Detect and repair clicks, returning ``(audio, message, modified)``.

    ``modified`` is the engine's own verdict, which is what lets a run that
    found no clicks leave the file untouched (U-02).

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
        return dc_result.audio, msg, bool(dc_result.was_modified)
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        raise AudioProcessingError(
            f"Declick stage failed: {exc}",
            context={"stage": "declick"},
            original=exc,
        ) from exc


def _run_exact_trim_stage(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, str, bool]:
    """Keep the configured millisecond range instead of detecting silence.

    The range is validated against the decoded length, so a range that runs past
    the end is refused before anything is written.  A Dry Run reports the range
    it would keep and leaves the audio alone.

    Returns:
        ``(audio, stage_message, modified)`` - ``modified`` is false for a Dry
        Run, which writes nothing.

    Raises:
        AudioConfigurationError: The configured range is invalid or runs past
            the end of the audio.
    """
    exact_range = resolve_range(config.trim_params, len(audio))
    if config.dry_run:
        message = exact_preview_message(exact_range)
        emit("Trim", message)
        return audio, message, False

    trimmed = slice_segment(audio, exact_range)
    message = exact_trim_message(exact_range, len(trimmed), copy_mode=False)
    emit("Trim", message)
    return trimmed, message, True


def _run_trim_stage(
    audio: AudioSegment,
    config: StageConfig,
    emit: Callable[..., Any],
) -> tuple[AudioSegment, str, bool]:
    """Trim leading/trailing silence (and optionally fade).

    Returns:
        ``(audio, stage_message, modified)``; ``modified`` is false when the
        trimmer found no silence, so the file can be left byte-identical.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="trim"``.
    """
    emit("Trim", "Detecting silence…")
    try:
        if config.trim_params.mode == EXACT_TRIM_MODE:
            return _run_exact_trim_stage(audio, config, emit)

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
        return audio, msg, tr_result.trimmed is not None
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
) -> tuple[AudioSegment, str, bool]:
    """Remove hum and broadband noise, returning ``(audio, message, modified)``.

    ``modified`` is the engine's own verdict, so a file with no detectable
    noise is left byte-identical (U-02).

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
        return audio, msg, bool(nr_result.was_modified)
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
        # A lossless source's depth must survive the rewrite; FFmpeg's WAV/
        # AIFF encoders would otherwise default a 24-bit source to 16-bit.
        params = [*params, *preserve_depth_params(ext, str(source_path))]
        audio.export(str(tmp_path), format=fmt, parameters=params)


def _lossless_gain_applies(path: Path, config: StageConfig) -> bool:
    """Return whether *path* can take the lossless normalisation path.

    The path only exists for MP3: it rewrites each frame's ``global_gain`` and
    never decodes the audio.  Every other format falls back to the loudnorm
    re-encode, so the stage reports what it actually did.
    """
    return config.normalise_params.mode == "lossless" and is_mp3_file(str(path))


# ── Peak-target normalisation (F-E2) ────────────────────────────────────────

#: Full scale.  A peak gain that would push a sample past this is applied
#: through the limiter, which holds the ceiling instead of clamping the tail.
_FULL_SCALE_DBFS = 0.0


@dataclass(frozen=True)
class PeakGainPlan:
    """What the peak-target mode decided for one file.

    Attributes:
        sample_peak_dbfs: The loudest decoded sample the measurement found.
        true_peak_dbtp: The oversampled peak the measurement found.
        target_dbtp: The mode's target, in dBTP.
        gain_db: ``target_dbtp - true_peak_dbtp``, the static gain to apply.
        limited: Whether the limiter is inserted, because the gain would push a
            sample past :data:`_FULL_SCALE_DBFS`.
        ceiling_dbfs: The ceiling the limiter holds when ``limited``.
    """

    sample_peak_dbfs: float
    true_peak_dbtp: float
    target_dbtp: float
    gain_db: float
    limited: bool
    ceiling_dbfs: float


def plan_peak_gain(path: Path, config: StageConfig) -> PeakGainPlan:
    """Measure *path* and decide the static gain its peak target needs.

    The figure measured is the true peak - the oversampled one - because the
    target is a dBTP target and a sample peak can sit below an inter-sample
    overshoot.  The limiter decision therefore compares the *sample* peak,
    which is what a clamp would destroy.

    Raises:
        AudioFormatError: The file cannot be measured.
        AudioExternalToolError: FFmpeg could not be run.
    """
    n = config.normalise_params
    levels = audio_probe.measure_levels(str(path), ffmpeg=FFMPEG_PATH)
    gain_db = n.target_peak_dbtp - levels.true_peak_dbtp
    limited = levels.sample_peak_dbfs + gain_db > _FULL_SCALE_DBFS
    return PeakGainPlan(
        sample_peak_dbfs=levels.sample_peak_dbfs,
        true_peak_dbtp=levels.true_peak_dbtp,
        target_dbtp=n.target_peak_dbtp,
        gain_db=gain_db,
        limited=limited,
        ceiling_dbfs=_FULL_SCALE_DBFS,
    )


def _peak_message(
    plan: PeakGainPlan,
    *,
    applied: bool,
    verified: audio_probe.LevelMetrics | None = None,
) -> str:
    """Describe what the peak target did, naming the target that was met."""
    if not applied:
        return (
            f"Peak already within tolerance ({plan.true_peak_dbtp:.1f} dBTP) "
            "- no adjustment needed"
        )
    message = (
        f"Peak-normalised from {plan.true_peak_dbtp:.1f} to "
        f"{plan.target_dbtp:.1f} dBTP ({plan.gain_db:+.2f} dB)"
    )
    if verified is not None:
        message += (
            f"; measured {verified.true_peak_dbtp:.1f} dBTP true peak, "
            f"{verified.sample_peak_dbfs:.1f} dBFS sample peak"
        )
    if plan.limited:
        message += f", limited at {plan.ceiling_dbfs:.1f} dBFS"
    return message


def _apply_peak_plan(
    path: Path,
    plan: PeakGainPlan,
    config: StageConfig,
    emit: Callable[..., Any],
    *,
    record_snapshot: bool,
) -> tuple[str, bool]:
    """Apply one peak plan to *path* and report the measured outcome.

    The gain is applied by ``audio_normalizer.core.album.apply_static_gain`` -
    the suite's one static-gain applier, limiter and tag/depth path included -
    and the result is re-measured, so the report names what the encode
    delivered rather than what was asked for.
    """
    from audio_normalizer.core.album import apply_static_gain

    if abs(plan.gain_db) <= config.normalise_params.tolerance:
        message = _peak_message(plan, applied=False)
        emit("Normalise", message)
        return message, False

    if record_snapshot:
        record_tag_edit_snapshot(str(path), "refinery_edit")
    emit("Normalise", f"Applying the peak gain {plan.gain_db:+.2f} dB…")
    apply_static_gain(
        str(path),
        plan.gain_db,
        limit=plan.limited,
        true_peak_ceiling=plan.ceiling_dbfs,
        record_snapshot=False,
        # Peak targets are lossless-first: pass the matrix fallback so a
        # container the normaliser's tuned map lacks still resolves an encoder
        # rather than failing a write this mode is defined to make.
        lossless_output=True,
    )
    verified = audio_probe.measure_levels(str(path), ffmpeg=FFMPEG_PATH)
    message = _peak_message(plan, applied=True, verified=verified)
    emit("Normalise", message)
    return message, True


def _run_peak_normalise(
    path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
    *,
    record_snapshot: bool,
) -> tuple[str, bool]:
    """Run the peak-target stage on one file."""
    emit(
        "Normalise",
        f"Measuring peak (target {config.normalise_params.target_peak_dbtp:.1f} dBTP)…",
    )
    plan = plan_peak_gain(path, config)
    return _apply_peak_plan(path, plan, config, emit, record_snapshot=record_snapshot)


def _preview_peak_normalise(
    source_path: Path, config: StageConfig, emit: Callable[..., Any]
) -> str:
    """Report the gain and the ceiling a peak-target run would apply."""
    n = config.normalise_params
    emit("Normalise", f"Measuring peak (target {n.target_peak_dbtp:.1f} dBTP)…")
    try:
        plan = plan_peak_gain(source_path, config)
    except Exception as exc:  # preview must not abort the dry run
        logger.error("Dry-run peak measurement failed: %s", exc, exc_info=True)
        message = "Peak measurement failed - peak normalisation would be skipped"
        emit("Normalise", message)
        return message
    if abs(plan.gain_db) <= n.tolerance:
        message = (
            f"Peak already within tolerance ({plan.true_peak_dbtp:.1f} dBTP) "
            "- no change"
        )
    else:
        message = (
            f"Would apply {plan.gain_db:+.1f} dB to reach {plan.target_dbtp:.1f} "
            f"dBTP (ceiling {plan.ceiling_dbfs:.1f} dBFS)"
        )
        if plan.limited:
            message += ", limiting"
    emit("Normalise", message)
    return message


def _normalise_message(
    loudness_data: dict[str, float] | None,
    config: StageConfig,
    applied: bool,
    lossless: bool = False,
) -> str:
    """Build the Normalise stage message for one measurement outcome.

    ``lossless`` names the strategy that actually ran: the MP3 ``global_gain``
    rewrite (which re-encodes nothing) rather than the loudnorm pass.
    """
    target_lufs = config.normalise_params.target_lufs
    if loudness_data:
        before_lufs = float(loudness_data.get("input_i", 0.0))
        if applied:
            how = " (lossless MP3 gain)" if lossless else ""
            return (
                f"Adjusted loudness from {before_lufs:.1f} to {target_lufs:.1f} "
                f"LUFS for playlist consistency{how}"
            )
        return (
            f"Loudness already within tolerance ({before_lufs:.1f} LUFS) "
            f"\u2014 no adjustment needed"
        )
    if applied:
        return f"Adjusted loudness to {target_lufs} LUFS for playlist consistency"
    return "Loudness measurement failed — normalization skipped"


def _normalise_skip_reason(path: Path, config: StageConfig) -> str | None:
    """Return why the Normalise stage cannot write *path*, or ``None``.

    The stage's encoder set is the normaliser's own (``NORMALISE_EXTENSIONS``),
    and a container outside it is a known limit rather than a failure: the file
    reports the reason and every other enabled stage still runs.  A peak target
    writes through the shared format matrix, so it has no such limit.

    Args:
        path: The file the run is about to process.
        config: The run's stage configuration.

    Returns:
        The skip message, or ``None`` when the stage can write the container.
    """
    if config.normalise_params.target_mode == "peak":
        return None
    from audio_normalizer.core.normalizer import (
        NORMALISE_EXTENSIONS,
        normalise_format_display,
    )

    ext = path.suffix.lower()
    if ext in NORMALISE_EXTENSIONS:
        return None
    return (
        f"the Normalise stage has no encoder for {ext or path.name}; "
        f"it writes {normalise_format_display()}"
    )


def _normalise_stage_error(exc: Exception) -> AudioProcessingError:
    """Wrap a normalise failure with the stage context and original cause."""
    mapped = map_to_audio_error(exc)
    logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
    return AudioProcessingError(
        f"Normalise stage failed: {exc}",
        context={"stage": "normalise"},
        original=exc,
    )


#: A gain this small is not a change: the file must stay byte-identical, which
#: is the pipeline's no-op rule.
_ALBUM_GAIN_EPSILON_DB = 0.01


def _album_gain(album: AlbumPlan | None, album_key: str) -> float:
    """Return the plan's gain for one file, or 0.0 outside album mode.

    Raises:
        AudioProcessingError: The plan carries no entry for the file, which
            means it was measured from a different set of paths.
    """
    if album is None:
        return 0.0
    try:
        return album.gains[album_key]
    except KeyError as exc:
        raise AudioProcessingError(
            f"The album plan has no gain for '{os.path.basename(album_key)}'.",
            context={"stage": "normalise", "file": album_key},
        ) from exc


def _album_stage_message(album: AlbumPlan, gain_db: float, limited: bool) -> str:
    """Describe what album mode did to one file."""
    if abs(gain_db) < _ALBUM_GAIN_EPSILON_DB:
        return (
            f"Album loudness already within tolerance ({album.album_lufs:.1f} LUFS)"
            " - no adjustment needed"
        )
    message = (
        f"Applied album gain {gain_db:+.1f} dB"
        f" (album {album.album_lufs:.1f} LUFS -> {album.target_lufs:.1f} LUFS)"
    )
    if limited:
        message += f", limited to the {album.true_peak_ceiling:g} dBTP ceiling"
    return message


def _apply_album_stage(
    path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
    album: AlbumPlan,
    gain_db: float,
    limited: bool,
    *,
    record_snapshot: bool,
) -> tuple[str, bool]:
    """Apply one planned gain to *path* and report what actually ran."""
    from audio_normalizer.core.album import apply_album_gain

    n = config.normalise_params
    if abs(gain_db) < _ALBUM_GAIN_EPSILON_DB:
        message = _album_stage_message(album, gain_db, limited)
        emit("Normalise", message)
        return message, False

    emit("Normalise", f"Applying the album gain {gain_db:+.2f} dB…")
    lossless = _lossless_gain_applies(path, config)
    if lossless and not limited:
        apply_track_gain(str(path), gain_db)
    else:
        apply_album_gain(
            str(path),
            gain_db,
            limit=limited,
            true_peak_ceiling=n.true_peak,
            record_snapshot=record_snapshot,
        )
    message = _album_stage_message(album, gain_db, limited)
    if lossless and limited:
        # The MP3 global-gain rewrite cannot hold a ceiling, so this track was
        # re-encoded; saying so is the only honest report.
        message += "; re-encoded because the lossless MP3 path cannot limit"
    emit("Normalise", message)
    return message, True


def _run_normalise_stage(
    tmp_path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
    *,
    album: AlbumPlan | None = None,
    album_key: str = "",
) -> tuple[str, bool]:
    """Measure loudness and run FFmpeg normalisation with retry.

    Returns:
        ``(stage_message, applied)`` — ``applied`` is false when the file was
        already within tolerance or the measurement failed.

    Raises:
        AudioProcessingError: If the stage fails; preserves the original
            exception with context ``stage="normalise"``.
    """
    reason = _normalise_skip_reason(tmp_path, config)
    if reason is not None:
        emit("Normalise", reason)
        return reason, False

    # A peak target is per file and needs no loudness measurement at all
    # (F-E2); it runs before the album branch, which is a LUFS-only plan.
    if config.normalise_params.target_mode == "peak":
        try:
            return _run_peak_normalise(tmp_path, config, emit, record_snapshot=False)
        except Exception as exc:
            raise _normalise_stage_error(exc) from exc

    if album is not None:
        try:
            return _apply_album_stage(
                tmp_path,
                config,
                emit,
                album,
                _album_gain(album, album_key),
                bool(album.limited.get(album_key, False)),
                record_snapshot=False,
            )
        except Exception as exc:
            raise _normalise_stage_error(exc) from exc

    emit("Normalise", "Measuring loudness…")
    try:
        # Measure loudness BEFORE normalization.  The ceiling and LRA reach the
        # analysis pass too: loudnorm's target offset depends on both.
        from audio_normalizer.core.loudness import measure

        n = config.normalise_params
        loudness_data = measure(str(tmp_path), n.target_lufs, n.true_peak, n.lra)

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

        msg = _normalise_message(
            loudness_data,
            config,
            normalization_applied,
            lossless=_lossless_gain_applies(tmp_path, config),
        )
        emit("Normalise", msg)
        return msg, normalization_applied
    except Exception as exc:
        raise _normalise_stage_error(exc) from exc


def _run_normalise_in_place(
    source_path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
    *,
    album: AlbumPlan | None = None,
    album_key: str = "",
) -> tuple[str, bool]:
    """Normalise the source directly — one FFmpeg pass, no staging encode.

    Used when no in-memory stage has audio to write (U-02): exporting first
    would encode the file a second time.  The undo snapshot is taken only
    once the measurement says an adjustment is needed, so a no-op run leaves
    no undo record behind.

    Returns:
        ``(stage_message, applied)``.

    Raises:
        AudioProcessingError: If measuring or applying fails.
    """
    reason = _normalise_skip_reason(source_path, config)
    if reason is not None:
        emit("Normalise", reason)
        return reason, False

    if config.normalise_params.target_mode == "peak":
        try:
            return _run_peak_normalise(source_path, config, emit, record_snapshot=True)
        except Exception as exc:
            raise _normalise_stage_error(exc) from exc

    if album is not None:
        try:
            gain = _album_gain(album, album_key)
            if abs(gain) >= _ALBUM_GAIN_EPSILON_DB:
                # Snapshot before the swap replaces the source bytes.
                record_tag_edit_snapshot(str(source_path), "refinery_edit")
            return _apply_album_stage(
                source_path,
                config,
                emit,
                album,
                gain,
                bool(album.limited.get(album_key, False)),
                record_snapshot=False,
            )
        except Exception as exc:
            raise _normalise_stage_error(exc) from exc

    emit("Normalise", "Measuring loudness…")
    try:
        from audio_normalizer.core.loudness import measure

        n = config.normalise_params
        loudness_data = measure(str(source_path), n.target_lufs, n.true_peak, n.lra)
        applied = False
        lossless = _lossless_gain_applies(source_path, config)
        if loudness_data:
            current = float(loudness_data.get("input_i", 0.0))
            target = n.target_lufs
            tolerance = n.tolerance
            if abs(current - target) > tolerance:
                # Snapshot before the swap replaces the source bytes.
                record_tag_edit_snapshot(str(source_path), "refinery_edit")
                if lossless:
                    emit(
                        "Normalise",
                        f"Applying {target - current:+.2f} dB to MP3 global gain "
                        "(lossless)…",
                    )
                    apply_track_gain(str(source_path), target - current)
                    applied = True
                else:
                    applied = retry_with_backoff(
                        _run_normalise,
                        _DEFAULT_RETRY,
                        "normalise",
                        source_path,
                        config,
                        emit,
                        loudness_data,
                    )

        msg = _normalise_message(loudness_data, config, applied, lossless=lossless)
        emit("Normalise", msg)
        return msg, applied
    except Exception as exc:
        raise _normalise_stage_error(exc) from exc


def _preview_normalise(
    source_path: Path,
    config: StageConfig,
    emit: Callable[..., Any],
    *,
    album: AlbumPlan | None = None,
    album_key: str = "",
) -> str:
    """Report what the Normalise stage would do, without writing anything.

    Measures the source (never a staging copy) and names the projected
    outcome, matching the preview the standalone normalizer gives.
    """
    reason = _normalise_skip_reason(source_path, config)
    if reason is not None:
        emit("Normalise", reason)
        return reason

    if config.normalise_params.target_mode == "peak":
        return _preview_peak_normalise(source_path, config, emit)

    if album is not None:
        gain = _album_gain(album, album_key)
        if abs(gain) < _ALBUM_GAIN_EPSILON_DB:
            message = (
                f"Album loudness already within tolerance ({album.album_lufs:.1f} "
                "LUFS) - no change"
            )
        else:
            message = (
                f"Would apply album gain {gain:+.1f} dB"
                f" (album {album.album_lufs:.1f} LUFS -> {album.target_lufs:.1f} LUFS)"
            )
            if album.limited.get(album_key, False):
                message += f", limited to the {album.true_peak_ceiling:g} dBTP ceiling"
        emit("Normalise", message)
        return message

    target = config.normalise_params.target_lufs
    emit("Normalise", f"Measuring loudness (target {target} LUFS)…")
    try:
        from audio_normalizer.core.loudness import measure

        n = config.normalise_params
        loudness_data = measure(str(source_path), target, n.true_peak, n.lra)
    except Exception as exc:  # preview must not abort the dry run
        logger.error("Dry-run loudness measurement failed: %s", exc, exc_info=True)
        loudness_data = None

    if not loudness_data:
        msg = "Loudness measurement failed — normalisation would be skipped"
    else:
        current = float(loudness_data.get("input_i", 0.0))
        if abs(current - target) <= config.normalise_params.tolerance:
            msg = f"Loudness already within tolerance ({current:.1f} LUFS) — no change"
        else:
            how = (
                " (lossless MP3 gain)"
                if _lossless_gain_applies(source_path, config)
                else ""
            )
            msg = f"Would adjust loudness from {current:.1f} to {target:.1f} LUFS{how}"
    emit("Normalise", msg)
    return msg


def _run_dry_run(
    audio: AudioSegment,
    source_path: Path,
    config: StageConfig,
    result: FileResult,
    emit: Callable[..., Any],
    album: AlbumPlan | None = None,
    album_key: str = "",
) -> None:
    """Run the enabled stages' detection and record what they found.

    Nothing is written: the stages work on the decoded audio in memory, the
    normalise stage measures the source, and the temp file is never created.
    """
    rms_before = compute_rms_db(segment_to_numpy(audio)[0])
    result.add_stage(
        "DryRun",
        FileStatus.DONE,
        f"Loaded OK (RMS: {rms_before:.1f} dBFS, {len(audio)}ms, {audio.channels}ch)",
    )
    emit("DryRun", f"Detecting enabled stages (dry run). RMS={rms_before:.1f} dBFS")

    if config.declick:
        audio, msg, _changed = _run_declick_stage(audio, config, emit)
        result.add_stage("Declick", FileStatus.DONE, msg)
    if config.trim:
        audio, msg, _changed = _run_trim_stage(audio, config, emit)
        result.add_stage("Trim", FileStatus.DONE, msg)
    if config.reduce_noise:
        audio, msg, _changed = _run_noise_reduction_stage(audio, config, emit)
        result.add_stage("Noise Reduction", FileStatus.DONE, msg)
    if config.enhance:
        audio, msg, metrics = _run_enhance_stage(audio, config, emit)
        result.add_stage("Enhance", FileStatus.DONE, msg, metrics=metrics)
    if config.normalise:
        msg = _preview_normalise(
            source_path, config, emit, album=album, album_key=album_key
        )
        result.add_stage("Normalise", FileStatus.DONE, msg)

    emit("DryRun", "Dry run complete — nothing written")


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

    n = config.normalise_params
    target = n.target_lufs

    if loudness_data is None:
        emit("Normalise", f"Measuring loudness (target {target} LUFS)…")
        loudness_data = measure(str(tmp_path), target, n.true_peak, n.lra)
    if loudness_data is None:
        # FFmpeg returned no usable data (e.g. very quiet or unusual encoding).
        # Warn and skip rather than aborting the whole file.
        emit("Normalise", "⚠ Loudness measurement failed — Normalise stage skipped")
        logger.info("Normalise skipped for %s: measure() returned None", tmp_path.name)
        return False

    current_i = loudness_data.get("input_i", 0.0)
    tolerance = n.tolerance
    if abs(current_i - target) <= tolerance:
        emit("Normalise", f"Already within tolerance ({current_i:.1f} LUFS) — skipped")
        return False

    if _lossless_gain_applies(tmp_path, config):
        # An MP3's global_gain is a per-frame field: rewriting it changes the
        # level without decoding, so nothing is re-encoded here.
        emit(
            "Normalise",
            f"Applying {target - current_i:+.2f} dB to MP3 global gain (lossless)…",
        )
        apply_track_gain(str(tmp_path), target - current_i)
        emit("Normalise", "Normalisation complete (lossless)")
        return True

    emit("Normalise", f"Normalising {current_i:.1f} → {target} LUFS…")
    # apply() handles its own temp-file swap and tag restoration internally.
    # The pipeline records the undo snapshot itself, so apply() must not.
    apply(
        str(tmp_path),
        target,
        loudness_data,
        record_snapshot=False,
        true_peak=n.true_peak,
        lra=n.lra,
    )
    emit("Normalise", "Normalisation complete")
    return True
