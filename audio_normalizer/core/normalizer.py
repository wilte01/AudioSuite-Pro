"""
normalizer.py
FFmpeg loudnorm processing pass — applies two-pass normalisation to an
audio file in-place, preserving all original tags.

Pure function: no tkinter imports, no global state.

Supports: MP3, FLAC, OGG, M4A, Opus, WavPack, Speex, WAV, AIFF, AIF

Changed in 1.1.0: the normalizer codec map now covers seven formats, adding WavPack
(.wv) and Ogg Speex (.spx); read-only APE/MPC/DSF keep the clear reject path.

Changed in 2.1.7: the output's sample rate (and FLAC's bit depth) is pinned to
the source's, and FLAC frames are capped, so normalising no longer resamples to
loudnorm's 192 kHz or fails on FFmpeg builds newer than 8.0. See
``_preserve_args``.

Changed in 2.6.0: WAV/AIFF join the encoder set, closing the follow-on the album

mode plan recorded (D-8).  They are lossless, so their encoder comes from the
shared format matrix rather than a tuned entry, and the source's depth is
re-pinned before the encode: FFmpeg's WAV/AIFF muxers write 16-bit PCM whatever
came in, so an unpinned 24-bit master would be truncated by the pass meant to
preserve it.
"""

import os
from typing import Any

from mutagen import File as MutagenFile
from mutagen import MutagenError

from audio_suite_shared import audio_formats
from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.exceptions import AudioFormatError

# Changed in 2.5.0: the resolver moved to audio_suite_shared.ffmpeg (D-38).
from audio_suite_shared.ffmpeg import FFMPEG_PATH
from audio_suite_shared.secure_subprocess import run_secure_subprocess
from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

from .loudness import parse_output_true_peak

# ── Format → FFmpeg codec + quality args ─────────────────────────────────────
# Each entry: (codec, extra_args)
# extra_args are appended after "-c:a codec" to control quality/bitrate.
# APE/MPC/DSF are deliberately absent: no ffmpeg encoder exists for them
# (READ_ONLY_EXTENSIONS in audio_suite_shared.audio_formats), so they take
# the clear AudioFormatError reject path below.

_FORMAT_CODEC = {
    ".mp3": ("libmp3lame", ["-q:a", "0"]),  # VBR best quality
    ".flac": ("flac", ["-compression_level", "8"]),
    ".ogg": ("libvorbis", ["-q:a", "6"]),  # ~192 kbps
    ".m4a": ("aac", ["-b:a", "256k"]),
    ".opus": ("libopus", ["-b:a", "192k"]),
    ".wv": ("wavpack", []),
    ".spx": ("libspeex", ["-q:a", "8"]),
}


#: Integer-PCM containers the Normalise stage writes.  They are lossless, so the
#: gain is applied by re-encoding samples, and the encoder comes from the shared
#: format matrix rather than a tuned entry.  FFmpeg's WAV/AIFF muxers write
#: 16-bit PCM whatever came in, so the source's own depth is re-pinned before the
#: encode (``_depth_args``) - without that, a 24-bit master would be truncated by
#: the very pass that is meant to preserve it (the F-10 class, in the normaliser).
_PCM_EXTENSIONS: tuple[str, ...] = tuple(
    ext
    for ext, capability in audio_formats.FORMAT_MATRIX.items()
    if capability.depth_codecs
)

#: Every extension the Normalise stage can write: the tuned map above plus the
#: integer-PCM containers the matrix supplies.
NORMALISE_EXTENSIONS: frozenset[str] = frozenset(_FORMAT_CODEC) | frozenset(
    _PCM_EXTENSIONS
)


def normalise_format_display() -> str:
    """Return the containers the Normalise stage writes, for a message.

    Derived from the two sources that decide it, so a refusal can never name a
    format the stage does not write, or omit one it does.

    Returns:
        The matrix's display names, in the map's own order, comma-separated.
    """
    names = []
    for ext in (*_FORMAT_CODEC, *_PCM_EXTENSIONS):
        capability = audio_formats.FORMAT_MATRIX.get(ext)
        names.append(capability.display_name if capability else ext.lstrip(".").upper())
    return ", ".join(names)


# ── Source parameters that must survive the re-encode ────────────────────────
#
# Two defects came from leaving FFmpeg free to choose the output's audio
# parameters (PLAN_audit_2026-10-24_deferred_p2p3.md, X12 closure).
#
# * ``loudnorm`` computes at 192 kHz and hands its frames on at that rate, and
#   nothing here used to pin the output rate, so EVERY normalised file was
#   silently resampled to 192 kHz - a 2 s 16-bit 44.1 kHz FLAC became a 192 kHz
#   24-bit one at ~10x the size, with the shift invisible to the user.
# * The FLAC encoder derives its block size from the rate, so at 192 kHz it
#   asked for 384000-sample blocks. FFmpeg 8.0.1 accepted that; current builds
#   (Lavf63, and the Windows runner's Chocolatey ffmpeg) reject it with
#   ``invalid block size: 384000``, which made the whole normalise stage fail.
#
# So the rate is pinned to the source's own, the FLAC frame size is capped, and
# FLAC's integer depth is pinned to the source's. All three are needed: pinning
# the rate alone still left ``invalid block size: 88184`` (44100 x 2 s).

#: Sample rates each encoder accepts, for the codecs whose set is fixed. Passing
#: ``-ar`` for a rate the encoder cannot take is an error AND suppresses the
#: automatic resampler FFmpeg otherwise inserts, so opus (8/12/16/24/48 kHz)
#: broke the moment its 44.1 kHz input was pinned. Codecs absent from this map
#: accept any rate the format can hold. Because the normaliser re-encodes a file
#: in place, the source rate is by construction one its own format supports; the
#: lookup only matters for a source that does not match its extension.
_ENCODER_RATES: dict[str, tuple[int, ...]] = {
    ".mp3": (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000),
    ".opus": (8000, 12000, 16000, 24000, 48000),
    ".spx": (8000, 16000, 32000),
}

#: Codecs whose stream stores an integer bit depth. ``loudnorm`` emits doubles,
#: so the FLAC encoder widens a 16-bit source to 24 bits unless told otherwise.
#: WavPack is deliberately absent: its encoder rejects ``-sample_fmt s16``.
_DEPTH_CODECS = frozenset({"flac"})

#: FLAC's own limit is 65535 samples per block; 4096 is the conventional frame
#: size and leaves the encoder a legal block whichever rate reaches it. ``p=0``
#: keeps the last frame short instead of padding it with silence, so the
#: duration is unchanged.
_FLAC_FRAME_SAMPLES = 4096


def _source_parameters(file_path: str) -> tuple[int | None, int | None]:
    """Return the file's own (sample_rate, bits_per_sample).

    Read with mutagen rather than a subprocess: it already parses exactly these
    two fields for every format ``_FORMAT_CODEC`` accepts. Anything unreadable
    or absent yields ``None``, and the caller then omits that pin instead of
    guessing a value.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        Tuple of (sample_rate, bits_per_sample), each ``None`` when unknown.
    """
    try:
        audio = MutagenFile(file_path)
    # Changed in 2.4.1: BLE001 triage (WP-7 of
    # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
    except (OSError, MutagenError):
        return (None, None)
    info = getattr(audio, "info", None)
    if info is None:
        return (None, None)
    rate = getattr(info, "sample_rate", None)
    bits = getattr(info, "bits_per_sample", None)
    return (
        rate if isinstance(rate, int) and rate > 0 else None,
        bits if isinstance(bits, int) and bits > 0 else None,
    )


def _preserve_args(file_path: str, codec: str) -> list[str]:
    """FFmpeg output arguments that keep the source's audio parameters.

    Args:
        file_path: Absolute path to the input file.
        codec: FFmpeg codec name chosen by ``_codec_args``.

    Returns:
        Arguments to place before the output path; empty when nothing is known
        about the source, which is the pre-fix behaviour rather than a guess.
    """
    rate, bits = _source_parameters(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    args: list[str] = []
    allowed = _ENCODER_RATES.get(ext)
    if rate is not None and (allowed is None or rate in allowed):
        args += ["-ar", str(rate)]
    if codec in _DEPTH_CODECS and bits is not None:
        args += ["-sample_fmt", "s16" if bits <= 16 else "s32"]
    return args


def _filters(
    target_lufs: float,
    loudness_data: dict[str, Any],
    codec: str,
    true_peak: float = -1.5,
    lra: float = 11,
) -> str:
    """The ``-af`` chain: loudnorm, plus FLAC's frame cap.

    Args:
        target_lufs: Target integrated loudness.
        loudness_data: Measurements from ``loudness.measure()``.
        codec: FFmpeg codec name chosen by ``_codec_args``.
        true_peak: True-peak ceiling in dBTP (default -1.5, the pre-2.1.7
            hard-coded value).
        lra: Target loudness range in LU (default 11, likewise unchanged).

    Returns:
        The filtergraph string.
    """
    chain = (
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}"
        f":measured_I={loudness_data['input_i']}"
        f":measured_TP={loudness_data['input_tp']}"
        f":measured_LRA={loudness_data['input_lra']}"
        f":measured_thresh={loudness_data['input_thresh']}"
        f":offset={loudness_data['target_offset']}"
        f":linear=true:print_format=summary"
    )
    if codec == "flac":
        chain += f",asetnsamples=n={_FLAC_FRAME_SAMPLES}:p=0"
    return chain


def _depth_args(file_path: str) -> list[str]:
    """FFmpeg arguments that keep an integer-PCM source's bit depth.

    WAV/AIFF only: their muxers default to 16-bit PCM and ``loudnorm`` emits
    doubles, so an unpinned 24-bit source would come back at 16 bits.  FLAC's
    depth is pinned by ``_preserve_args`` instead, and a lossy container has no
    depth to preserve.

    Args:
        file_path: Absolute path to the input file.

    Returns:
        Arguments to place before the output path; empty when no pin applies.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _PCM_EXTENSIONS:
        return []
    return audio_formats.preserve_depth_params(ext, file_path)


def _codec_args(file_path: str) -> tuple[str, list[str]]:
    """Return (codec_name, extra_args) for the file's extension.

    Extensions with no encoder are rejected rather than silently re-encoded as
    MP3, which would damage quality while keeping the original extension (e.g.
    a ``.mp4`` would hold MP3 data).

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        Tuple of FFmpeg codec name and quality argument list.

    Raises:
        AudioFormatError: If the file extension has no configured codec.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in _FORMAT_CODEC:
        return _FORMAT_CODEC[ext]
    if ext in _PCM_EXTENSIONS:
        # Lossless PCM: the container's own encoder from the shared matrix, with
        # the source's depth re-pinned by ``_depth_args`` before the encode.
        return audio_formats.ffmpeg_encoder_args(ext)
    raise AudioFormatError(
        f"Unsupported audio format for normalisation: '{ext or file_path}'. "
        f"Supported formats: {normalise_format_display()}.",
        context={"file": file_path, "extension": ext or None},
    )


def apply(
    file_path: str,
    target_lufs: float,
    loudness_data: dict[str, Any],
    skip_tag_handling: bool = False,
    record_snapshot: bool = True,
    true_peak: float = -1.5,
    lra: float = 11,
) -> float | None:
    """
    Normalise a single audio file using a two-pass loudnorm approach.

    The file is written to a temporary path first, then atomically replaces
    the original, so a crash or error during encoding leaves the original intact.

    The source's own sample rate is pinned on the output, so normalising never
    resamples to ``loudnorm``'s internal 192 kHz.  A lossless source also keeps
    its integer bit depth - FLAC through ``_preserve_args``, WAV/AIFF through
    ``_depth_args`` - so widening 16-bit audio and truncating a 24-bit master
    both stay impossible.

    Original tags are preserved by re-applying them to the re-encoded file
    using the format-aware tag_helper, unless *skip_tag_handling* is True
    (used by the Audio Refinery pipeline which manages tags centrally).

    Args:
        file_path:          Absolute path to the audio file.
        target_lufs:        Target integrated loudness.
        loudness_data:      Measurements from loudness.measure() for this file.
        skip_tag_handling:  If True, skip reading and writing tags (the caller
                            manages tags externally).
        record_snapshot:    Whether to record an undo snapshot against the real
                            output file before re-encoding.  Set to False when
                            the caller (e.g. the Audio Refinery pipeline)
                            records the snapshot itself.
        true_peak:          True-peak ceiling in dBTP (default -1.5).
        lra:                Target loudness range in LU (default 11).

    Returns:
        The true peak the encode actually achieved, in dBTP, or ``None`` when
        FFmpeg did not print a loudnorm summary.

    Raises:
        AudioFormatError: If the file extension has no configured codec.
        subprocess.CalledProcessError: If FFmpeg returns a non-zero exit code.
        Exception: Any other IO or mutagen error.
    """
    ext = os.path.splitext(file_path)[1].lower()
    codec, extra = _codec_args(file_path)
    temp_out = file_path + f".tmp{ext}"

    # Preserve original tags before re-encoding strips them
    if not skip_tag_handling:
        original_tags = read_tags_raw(file_path)
        if record_snapshot:
            record_tag_edit_snapshot(file_path, "write_normalise")

    required_keys = (
        "input_i",
        "input_tp",
        "input_lra",
        "input_thresh",
        "target_offset",
    )
    for key in required_keys:
        if key not in loudness_data:
            raise ValueError(
                f"loudness_data missing required key '{key}'; "
                "ensure loudness measurement completed successfully."
            )

    cmd = [
        FFMPEG_PATH,
        "-hide_banner",
        "-y",
        "-i",
        file_path,
        "-af",
        _filters(target_lufs, loudness_data, codec, true_peak, lra),
        "-c:a",
        codec,
        *extra,
        *_preserve_args(file_path, codec),
        *_depth_args(file_path),
        temp_out,
    ]

    try:
        encode = run_secure_subprocess(cmd[0], cmd[1:], capture_output=True, check=True)
    except Exception:
        if os.path.exists(temp_out):
            os.remove(temp_out)
        raise

    achieved_peak = parse_output_true_peak(getattr(encode, "stderr", "") or "")

    try:
        # Restore original tags to the freshly encoded file
        if not skip_tag_handling:
            write_tags_raw(temp_out, original_tags, record_snapshot=False)

        # Atomic replace — only reached if encoding succeeded
        os.replace(temp_out, file_path)
    except Exception:
        if os.path.exists(temp_out):
            os.remove(temp_out)
        raise
    return achieved_peak
