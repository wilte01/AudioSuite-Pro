"""
normalizer.py
FFmpeg loudnorm processing pass — applies two-pass normalisation to an
audio file in-place, preserving all original tags.

Pure function: no tkinter imports, no global state.

Supports: MP3, FLAC, OGG, M4A, Opus, WavPack, Speex

Changed in 1.1.0: the normalizer codec map now covers seven formats, adding WavPack
(.wv) and Ogg Speex (.spx); read-only APE/MPC/DSF keep the clear reject path.

Changed in 2.1.7: the output's sample rate (and FLAC's bit depth) is pinned to
the source's, and FLAC frames are capped, so normalising no longer resamples to
loudnorm's 192 kHz or fails on FFmpeg builds newer than 8.0. See
``_preserve_args``.
"""

import os
from typing import Any

from mutagen import File as MutagenFile

from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.exceptions import AudioFormatError
from audio_suite_shared.secure_subprocess import run_secure_subprocess
from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

from ..utils.ffmpeg_finder import FFMPEG_PATH

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
    except Exception:
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


def _filters(target_lufs: float, loudness_data: dict[str, Any], codec: str) -> str:
    """The ``-af`` chain: loudnorm, plus FLAC's frame cap.

    Args:
        target_lufs: Target integrated loudness.
        loudness_data: Measurements from ``loudness.measure()``.
        codec: FFmpeg codec name chosen by ``_codec_args``.

    Returns:
        The filtergraph string.
    """
    chain = (
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
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


def _codec_args(file_path: str) -> tuple[str, list[str]]:
    """Return (codec_name, extra_args) for the file's extension.

    Extensions outside ``_FORMAT_CODEC`` are rejected rather than silently
    re-encoded as MP3, which would damage quality while keeping the original
    extension (e.g. a ``.wav`` would become MP3 data in a WAV container).

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        Tuple of FFmpeg codec name and quality argument list.

    Raises:
        AudioFormatError: If the file extension has no configured codec.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in _FORMAT_CODEC:
        raise AudioFormatError(
            f"Unsupported audio format for normalisation: '{ext or file_path}'. "
            "Supported formats: MP3, FLAC, OGG, M4A, Opus, WavPack, Speex.",
            context={"file": file_path, "extension": ext or None},
        )
    return _FORMAT_CODEC[ext]


def apply(
    file_path: str,
    target_lufs: float,
    loudness_data: dict[str, Any],
    skip_tag_handling: bool = False,
    record_snapshot: bool = True,
) -> None:
    """
    Normalise a single audio file using a two-pass loudnorm approach.

    The file is written to a temporary path first, then atomically replaces
    the original, so a crash or error during encoding leaves the original intact.

    The source's own sample rate (and, for FLAC, its bit depth) is pinned on the
    output, so normalising never resamples to ``loudnorm``'s internal 192 kHz or
    silently widens 16-bit audio; see ``_preserve_args``.

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
        _filters(target_lufs, loudness_data, codec),
        "-c:a",
        codec,
        *extra,
        *_preserve_args(file_path, codec),
        temp_out,
    ]

    try:
        run_secure_subprocess(cmd[0], cmd[1:], capture_output=True, check=True)
    except Exception:
        if os.path.exists(temp_out):
            os.remove(temp_out)
        raise

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
