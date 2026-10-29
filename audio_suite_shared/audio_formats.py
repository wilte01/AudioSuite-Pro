"""
audio_formats.py — Standardized audio format definitions for Audio Suite.

Provides consistent audio file extension constants across all applications,
eliminating scattered definitions and ensuring format compatibility.

Changed in 1.1.0: widened SUPPORTED_EXTENSIONS with .wv/.ape/.mpc/.spx/.dsf and added
READ_ONLY_EXTENSIONS plus is_read_only_extension().
Changed in 2.1.7: adds ``preserve_depth_params``, so a writer that re-encodes a
lossless file pins the source's integer bit depth instead of leaving it to
FFmpeg's encoder default (a 24-bit WAV came back as 16-bit). F-10's sweep locks
the outcome on decoded files.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(f"audio_suite.{__name__}")

# Standard audio file extensions supported across the suite
SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    ".mp3",  # MPEG-1 Audio Layer 3
    ".flac",  # Free Lossless Audio Codec
    ".ogg",  # Ogg Vorbis
    ".m4a",  # MPEG-4 Audio
    ".mp4",  # MPEG-4 Container (AAC audio)
    ".opus",  # Opus Audio Codec
    ".wav",  # Waveform Audio File Format
    ".aiff",  # Audio Interchange File Format
    ".aif",  # Audio Interchange File Format (short extension)
    ".wv",  # WavPack (decode + encode — ffmpeg wavpack encoder)
    ".ape",  # Monkey's Audio (decode only — no ffmpeg encoder/muxer)
    ".mpc",  # Musepack (decode only — no ffmpeg encoder/muxer)
    ".spx",  # Speex in Ogg (decode + encode — ffmpeg libspeex encoder)
    ".dsf",  # DSD Store (decode only — DSD->PCM via ffmpeg dsd2pcm)
)

# Extensions that may be read/converted *from* but never written in place or
# converted *to*: ffmpeg has no encoder and no muxer for these containers, so
# any same-ext write would silently fall through get_export_args()'s MP3
# fallback and corrupt the file (see get_export_args below).
READ_ONLY_EXTENSIONS: tuple[str, ...] = (".ape", ".mpc", ".dsf")

# Lossless audio formats
LOSSLESS_EXTENSIONS: tuple[str, ...] = (
    ".flac",
    ".wav",
    ".aiff",
    ".aif",
    ".wv",
    ".ape",
    ".mpc",
    ".dsf",
)

# Compressed/lossy audio formats
COMPRESSED_EXTENSIONS: tuple[str, ...] = (
    ".mp3",
    ".ogg",
    ".m4a",
    ".mp4",
    ".opus",
    ".spx",
)

# pydub export format string + ffmpeg quality params per extension.
# WAV and AIFF are uncompressed PCM containers; no bitrate/quality params apply.
# Read-only extensions (.ape/.mpc/.dsf) are deliberately absent — see
# READ_ONLY_EXTENSIONS above.
PYDUB_FORMAT: dict[str, tuple[str, list[str]]] = {
    ".mp3": ("mp3", ["-q:a", "0"]),
    ".flac": ("flac", ["-compression_level", "8"]),
    ".ogg": ("ogg", ["-q:a", "6"]),
    ".m4a": ("mp4", ["-b:a", "256k"]),
    ".mp4": ("mp4", ["-b:a", "256k"]),
    ".opus": ("opus", ["-b:a", "192k"]),
    ".wav": ("wav", []),
    ".aiff": ("aiff", []),
    ".aif": ("aiff", []),
    ".wv": ("wv", []),
    ".spx": ("spx", ["-c:a", "libspeex", "-q:a", "8"]),
}


def is_read_only_extension(filename: str) -> bool:
    """
    Check if a filename has a read-only audio extension (ape/mpc/dsf).

    These containers have no ffmpeg encoder or muxer: they may be read and
    converted *from*, but must never be written in place or converted *to*.

    Args:
        filename: Name of file to check

    Returns:
        True if file has a read-only extension, False otherwise
    """
    return filename.lower().endswith(READ_ONLY_EXTENSIONS)


def is_supported_format(filename: str) -> bool:
    """
    Check if a filename has a supported audio extension.

    Args:
        filename: Name of file to check

    Returns:
        True if file has supported extension, False otherwise
    """
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


def is_lossless_extension(filename: str) -> bool:
    """
    Check if a filename has a lossless audio extension.

    Note: this is an extension-based check only — it does not inspect the
    file's actual contents. A .wav containing MP3 data will still return True.

    Args:
        filename: Name of file to check

    Returns:
        True if file has lossless extension, False otherwise
    """
    return filename.lower().endswith(LOSSLESS_EXTENSIONS)


def is_compressed_extension(filename: str) -> bool:
    """
    Check if a filename has a compressed/lossy audio extension.

    Note: this is an extension-based check only — it does not inspect the
    file's actual contents. An .m4a containing ALAC data will still return True.

    Args:
        filename: Name of file to check

    Returns:
        True if file has compressed extension, False otherwise
    """
    return filename.lower().endswith(COMPRESSED_EXTENSIONS)


def get_format_type(filename: str) -> str:
    """
    Determine the format type of an audio file.

    Args:
        filename: Name of file to check

    Returns:
        'lossless', 'compressed', or 'unsupported'
    """
    if is_lossless_extension(filename):
        return "lossless"
    elif is_compressed_extension(filename):
        return "compressed"
    else:
        return "unsupported"


def get_export_args(ext: str) -> tuple[str, list[str]]:
    """Return the pydub format name and ffmpeg quality params for *ext*.

    This is the single source of truth for export parameters used across
    the suite (pipeline, pop-click remover, silence trimmer).

    Args:
        ext: File extension including the leading dot (e.g. '.mp3').

    Returns:
        Tuple of pydub format string and ffmpeg parameter list.
    """
    return PYDUB_FORMAT.get(ext.lower(), ("mp3", ["-q:a", "0"]))


#: Lossless extensions whose stream stores an integer bit depth, mapped to the
#: FFmpeg PCM codec for each source depth in bytes.  FFmpeg's WAV/AIFF muxers
#: default to 16-bit PCM, so without this pin a 24-bit source was silently
#: truncated to 16 bits on every in-place rewrite (F-10).
_DEPTH_CODECS: dict[str, dict[int, str]] = {
    ".wav": {2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"},
    ".aiff": {2: "pcm_s16be", 3: "pcm_s24be", 4: "pcm_s32be"},
    ".aif": {2: "pcm_s16be", 3: "pcm_s24be", 4: "pcm_s32be"},
}


def source_bit_depth(file_path: str) -> int | None:
    """Return a lossless file's declared integer bit depth, if readable.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        ``info.bits_per_sample`` for the containers that declare one, or
        ``None`` when mutagen cannot read the file or the format does not
        carry a depth.
    """
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(file_path)
    except Exception:
        return None
    info = getattr(audio, "info", None)
    bits = getattr(info, "bits_per_sample", None)
    return bits if isinstance(bits, int) and bits > 0 else None


def preserve_depth_params(ext: str, file_path: str) -> list[str]:
    """FFmpeg arguments that keep a lossless source's integer bit depth.

    A pydub export passes no sample-format argument, so FFmpeg picks its
    encoder default: the WAV/AIFF muxers write 16-bit PCM whatever came in.
    This returns the codec that matches the source file's declared depth, so an
    in-place rewrite does not reduce it.  Lossy containers carry no meaningful
    depth and return an empty list, as does a source whose depth cannot be
    read (the pre-pin behaviour rather than a guess).

    Args:
        ext: File extension including the leading dot (e.g. '.wav').
        file_path: Absolute path to the source file being rewritten.

    Returns:
        Arguments to append to the export parameters; empty when no pin applies.
    """
    ext = ext.lower()
    if ext not in _DEPTH_CODECS and ext != ".flac":
        return []
    bits = source_bit_depth(file_path)
    if bits is None or bits <= 16:
        return []
    if ext == ".flac":
        # FLAC stores at most 24 bits; s32 is FFmpeg's 24-bit sample format.
        return ["-sample_fmt", "s32"]
    codec = _DEPTH_CODECS[ext].get((bits + 7) // 8)
    return ["-c:a", codec] if codec else []


# ── Bitrate constants for MP3 VBR/CBR ────────────────────────────────────────
# Moved from audio_enhancer/core/processor.py to eliminate duplication.

CBR_BITRATES: list[int] = [
    32,
    40,
    48,
    56,
    64,
    80,
    96,
    112,
    128,
    160,
    192,
    224,
    256,
    320,
]

VBR_QUALITY_MAP: list[tuple[int, str]] = [
    (245, "V0"),
    (225, "V1"),
    (190, "V2"),
    (175, "V3"),
    (165, "V4"),
    (130, "V5"),
    (115, "V6"),
    (100, "V7"),
]


def pydub_export_for_source(
    ext: str,
    source_bitrate_kbps: int = 0,
    is_vbr: bool = False,
) -> tuple[str, list[str]]:
    """Return (pydub_format, ffmpeg_params) preserving source bitrate.

    When the source bitrate is known, this produces export parameters that
    closely match the original quality settings.  For lossless formats no
    bitrate parameters are needed.  Falls back to ``get_export_args()``
    defaults when the source bitrate is unavailable (0) or the format is
    not MP3.

    Args:
        ext:                File extension including the leading dot.
        source_bitrate_kbps: Source file's bitrate in kbps (0 = unknown).
        is_vbr:             True if the source uses VBR encoding.

    Returns:
        Tuple of pydub format string and ffmpeg parameter list.
    """
    if ext.lower() == ".mp3" and source_bitrate_kbps > 0:
        fmt = "mp3"
        if is_vbr:
            best = min(VBR_QUALITY_MAP, key=lambda x: abs(x[0] - source_bitrate_kbps))
            params = ["-q:a", best[1].replace("V", "")]
        else:
            closest = min(CBR_BITRATES, key=lambda x: abs(x - source_bitrate_kbps))
            params = ["-b:a", f"{closest}k"]
        return fmt, params

    return get_export_args(ext)
