"""
normalizer.py
FFmpeg loudnorm processing pass — applies two-pass normalisation to an
audio file in-place, preserving all original tags.

Pure function: no tkinter imports, no global state.

Supports: MP3, FLAC, OGG, M4A, Opus, WavPack, Speex

Changed in 1.1.0: the normalizer codec map now covers seven formats, adding WavPack
(.wv) and Ogg Speex (.spx); read-only APE/MPC/DSF keep the clear reject path.
"""

import os
from typing import Any

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
        (
            f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11"
            f":measured_I={loudness_data['input_i']}"
            f":measured_TP={loudness_data['input_tp']}"
            f":measured_LRA={loudness_data['input_lra']}"
            f":measured_thresh={loudness_data['input_thresh']}"
            f":offset={loudness_data['target_offset']}"
            f":linear=true:print_format=summary"
        ),
        "-c:a",
        codec,
        *extra,
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
