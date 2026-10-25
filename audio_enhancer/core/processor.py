"""
core/processor.py
Builds and applies the pedalboard DSP chain to a single audio file.
Emits progress via an optional callback so the UI can update in real time.

Changed in 1.1.0: added a clean [SKIP] guard for formats the enhancer
cannot round-trip (.wv/.spx/.ape/.mpc/.dsf) so the widened shared format set
does not surface them as misleading decode errors.
Changed in 2.1.3: Dry Run no longer bypasses the Sprint 1 effects, so it
measures exactly the signal a live run writes (R-09).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import numpy as np
import numpy.typing as npt

from audio_suite_shared.audio_formats import CBR_BITRATES, VBR_QUALITY_MAP
from audio_suite_shared.dsp_chain import (
    apply_enhancement_chain,
    compute_rms_db,
    post_chain_clip_check,
)

from . import ffmpeg_io
from .models import AudioFileInfo, EnhancementParams, JobStatus, ProcessingResult
from .tags import copy_tags

logger = logging.getLogger(__name__)

# Extensions the enhancer discovers via the shared SUPPORTED_EXTENSIONS but
# cannot round-trip.  pedalboard writes only {.wav, .aif/.aiff, .flac, .mp3,
# .ogg} and ffmpeg_io handles {.opus, .m4a, .mp4}; the remaining five have no
# encoder (WavPack .wv, Speex .spx) or are read-only suite-wide (Monkey's Audio
# .ape, Musepack .mpc, DSD .dsf - decision D6).  Without this guard the widened
# supported set surfaces them and the pedalboard decode raises, reporting a
# misleading "invalid or corrupted" error instead of a clean skip.
ENHANCER_UNSUPPORTED_FORMATS: frozenset[str] = frozenset(
    {".wv", ".spx", ".ape", ".mpc", ".dsf"}
)

ProgressCallback = Callable[[str], None]  # receives a plain-text status message


def process_file(
    info: AudioFileInfo,
    params: EnhancementParams,
    output_dir: Path,
    on_progress: ProgressCallback | None = None,
    dry_run: bool = False,
) -> ProcessingResult:
    """
    Apply the DSP chain to one file and write the result to output_dir.

    Parameters
    ----------
    info        : Pre-inspected AudioFileInfo for the source file.
    params      : DSP parameters to apply.
    output_dir  : Directory to write the enhanced file into.
    on_progress : Optional callback(message) for real-time UI progress updates.
                  Called from the processing thread — caller must marshal to
                  the Tk main thread via root.after(0, fn).
    dry_run     : When True, the DSP chain still runs (so level / gain are
                  measured) but no output file is written and no tags are
                  copied — used by the app's "Dry Run" mode.

    Returns
    -------
    ProcessingResult with status, level measurements, and tag count.
    """
    result = ProcessingResult(source=info.path)

    def _emit(msg: str) -> None:
        logger.info("%s: %s", info.path.name, msg)
        if on_progress:
            on_progress(msg)

    suffix = info.path.suffix.lower()
    if suffix in ENHANCER_UNSUPPORTED_FORMATS:
        result.status = JobStatus.SKIPPED
        result.display_text = (
            f"[SKIP] {info.path.name} \u2192 unsupported format ({suffix}); "
            "the enhancer cannot re-encode it"
        )
        _emit(result.display_text)
        return result

    output_path = output_dir / info.path.name
    result.output = output_path

    try:
        _emit("Reading audio…")
        if info.path.suffix.lower() in ffmpeg_io.FFMPEG_EXTENSIONS:
            audio, sample_rate = ffmpeg_io.read_audio(info.path)
        else:
            from pedalboard.io import AudioFile

            with AudioFile(str(info.path)) as f:
                audio = f.read(f.frames)
                sample_rate = int(f.samplerate)

        # Upcast to float64 here for this module's own arithmetic (RMS
        # calculations below, eventual WAV/AIFF float export). NOTE: this
        # does NOT make the DSP chain itself run in float64 — see comment
        # at the chain() call below.
        audio = audio.astype(np.float64)

        _emit("Applying DSP chain…")
        # IMPORTANT: pedalboard's Pedalboard.__call__/chain() always converts
        # its input to float32 internally for processing, regardless of the
        # input array's dtype, and always returns float32
        # (confirmed against pedalboard 0.9.23: "If the provided buffer uses
        # a 64-bit datatype, it will be converted to 32-bit for processing").
        # The DSP math (compressor, EQ, limiter) therefore runs in float32
        # precision here, not float64 as claude.md §3 specifies for internal
        # processing. The .astype(np.float64) below only restores float64
        # *after* processing — it does not recover precision already lost
        # inside the chain. There is no way to make pedalboard's internal
        # processing float64; this is a hard constraint of the library, not
        # something fixable in this module. Flagged here rather than fixed
        # silently, per claude.md's bug-fixing protocol — pedalboard is a
        # core dependency and swapping it is a design decision, not a bug fix.
        #
        # Both modes apply the same chain: the only dry-run difference is the
        # early return below, which skips the write and the tag copy (R-09).
        enhanced = apply_enhancement_chain(audio, sample_rate, params).astype(
            np.float64
        )
        post_chain_clip_check(enhanced, stage_name="Enhance")

        result.rms_before_db = compute_rms_db(audio)
        result.rms_after_db = compute_rms_db(enhanced)
        _emit(
            f"Level: {result.rms_before_db:.1f} \u2192 {result.rms_after_db:.1f} dBFS "
            f"({result.gain_db:+.1f} dB)"
        )

        if dry_run:
            _emit("Dry run \u2014 nothing written")
            result.status = JobStatus.DONE
            return result

        output_dir.mkdir(parents=True, exist_ok=True)

        _emit("Writing output file…")
        _write_audio(enhanced, sample_rate, output_path, info)

        _emit("Copying tags…")
        ok, count = copy_tags(info.path, output_path)
        result.tags_copied = count
        if ok:
            _emit(f"Tags: {count} frame(s) copied (ID3v2.{info.id3_version})")
        else:
            _emit("Tags: none found or format unsupported")

        result.status = JobStatus.DONE
        _emit("Done \u2713")
    # pedalboard is a declared hard dependency (pyproject); this mapped
    # fallback exists to keep process_file's typed failure contract intact in
    # an incomplete env, so it cannot run in a correctly installed suite (D2).
    except ImportError as exc:  # pragma: no cover
        from audio_suite_shared.exceptions import AudioMissingDependencyError

        mapped = AudioMissingDependencyError(
            "pedalboard is not installed - run: pip install pedalboard",
            dependency="pedalboard",
            original=exc,
        )
        logger.error("Missing dependency: %s", mapped.message, exc_info=True)
        result.status = JobStatus.ERROR
        result.error_message = mapped.message
        _emit(f"Error: {mapped.message}")

    except (ValueError, OSError, RuntimeError) as exc:
        from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

        error = map_to_audio_error(exc, context={"file": info.path.name})
        logger.error(
            "[%s] process_file(%s): %s",
            type(error).__name__,
            info.path.name,
            error,
            exc_info=True,
        )
        result.status = JobStatus.ERROR
        result.error_message = user_message_for(error)
        _emit(f"Error: {user_message_for(error)}")

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────


def _write_audio(
    audio: npt.NDArray[np.float64],
    sample_rate: int,
    output_path: Path,
    info: AudioFileInfo,
) -> None:
    if output_path.suffix.lower() in ffmpeg_io.FFMPEG_EXTENSIONS:
        ffmpeg_io.write_audio(
            audio, sample_rate, output_path, bitrate_kbps=info.bitrate_kbps
        )
        return

    from pedalboard.io import AudioFile

    quality = _resolve_mp3_quality(info) if info.path.suffix.lower() == ".mp3" else None

    kwargs: dict[str, Any] = {"num_channels": audio.shape[0]}
    if quality is not None:
        kwargs["quality"] = quality

    with AudioFile(str(output_path), "w", sample_rate, **kwargs) as out:
        out.write(audio)


def _resolve_mp3_quality(info: AudioFileInfo) -> int | str:
    """Return the correct pedalboard quality value for MP3 output."""
    if info.is_vbr:
        return min(VBR_QUALITY_MAP, key=lambda x: abs(x[0] - info.bitrate_kbps))[1]
    return min(CBR_BITRATES, key=lambda x: abs(x - info.bitrate_kbps))
