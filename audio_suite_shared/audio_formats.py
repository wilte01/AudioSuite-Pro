"""
audio_formats.py — Standardized audio format definitions for Audio Suite.

:data:`FORMAT_MATRIX` is the single source of truth: one frozen row per
container says whether it can be read, written and tagged, which FFmpeg encoder
and muxer produce it, and whether it is lossless. Every other constant in this
module is a projection of that table, so a format cannot be writable in one tool
and invisible in another — the drift that left ``.wma`` a converter input that
every ``is_supported_format`` caller ignored.

Changed in 1.1.0: widened SUPPORTED_EXTENSIONS with .wv/.ape/.mpc/.spx/.dsf and added
READ_ONLY_EXTENSIONS plus is_read_only_extension().
Changed in 2.1.7: adds ``preserve_depth_params``, so a writer that re-encodes a
lossless file pins the source's integer bit depth instead of leaving it to
FFmpeg's encoder default (a 24-bit WAV came back as 16-bit). F-10's sweep locks
the outcome on decoded files.
Changed in 2.4.1: ``FORMAT_MATRIX`` replaces the separate extension/quality
tables (WP-1 of PLAN_2026-11-03_2.4.1_stop_the_drift.md); ``.wma`` is completed
as a readable *and* writable container (measured: pydub ``asf`` + ``wmav2``
round-trips, so the old read-only absence was a gap, not a limit), ``.aac`` is
declared writable but untaggable, and :func:`get_export_args` refuses an unknown
extension instead of silently writing MP3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from audio_suite_shared.exceptions import AudioFormatError

logger = logging.getLogger(f"audio_suite.{__name__}")


@dataclass(frozen=True)
class FormatCapability:
    """Everything the suite knows about one audio container.

    Attributes:
        extension: File extension including the leading dot (``".wma"``).
        display_name: Human-readable name shown in status lines (``"WMA"``).
        pydub_format: pydub/FFmpeg muxer name used by the pydub export path, or
            ``None`` when the container has no pydub export (a read-only
            container, or one this suite writes through FFmpeg directly).
        ffmpeg_encoder: Audio encoder FFmpeg needs to produce the container.
        ffmpeg_muxer: FFmpeg muxer name for the container.
        lossless: True when the container stores lossless audio.
        readable: True when the suite can decode the container.
        writable: True when the suite can encode the container. A read-only row
            must never be passed to :func:`get_export_args`.
        tag_writable: True when ``TagHandlerFactory`` has a handler for the
            extension, so a writer can save tags to it. Declaring this honestly
            is what stops a tool from discovering a file it cannot tag.
        depth_codecs: Integer-PCM containers only: source bit depth in bytes ->
            the FFmpeg PCM codec that preserves it. Empty otherwise.
        output_extension: Extension to write for this container. Equal to
            ``extension`` for every row; a codec written *into* another
            container (ALAC into M4A) is expressed by
            :data:`CODEC_TO_EXTENSION`, not here.
        export_args: Quality arguments the pydub export path appends.
    """

    extension: str
    display_name: str
    pydub_format: str | None
    ffmpeg_encoder: str | None
    ffmpeg_muxer: str | None
    lossless: bool
    readable: bool = True
    writable: bool = True
    tag_writable: bool = True
    depth_codecs: dict[int, str] = field(default_factory=dict)
    output_extension: str = ""
    export_args: tuple[str, ...] = ()


#: The suite's format vocabulary: one row per container, in discovery order
#: (``SUPPORTED_EXTENSIONS`` keeps that order, and the ASX extractor probes
#: same-stem siblings in it).
FORMAT_MATRIX: dict[str, FormatCapability] = {
    ".mp3": FormatCapability(
        extension=".mp3",
        display_name="MP3",
        pydub_format="mp3",
        ffmpeg_encoder="libmp3lame",
        ffmpeg_muxer="mp3",
        lossless=False,
        output_extension=".mp3",
        export_args=("-q:a", "0"),
    ),
    ".flac": FormatCapability(
        extension=".flac",
        display_name="FLAC",
        pydub_format="flac",
        ffmpeg_encoder="flac",
        ffmpeg_muxer="flac",
        lossless=True,
        output_extension=".flac",
        export_args=("-compression_level", "8"),
    ),
    ".ogg": FormatCapability(
        extension=".ogg",
        display_name="OGG",
        pydub_format="ogg",
        ffmpeg_encoder="libvorbis",
        ffmpeg_muxer="ogg",
        lossless=False,
        output_extension=".ogg",
        export_args=("-q:a", "6"),
    ),
    ".m4a": FormatCapability(
        extension=".m4a",
        display_name="M4A",
        pydub_format="mp4",
        ffmpeg_encoder="aac",
        ffmpeg_muxer="mp4",
        lossless=False,
        output_extension=".m4a",
        export_args=("-b:a", "256k"),
    ),
    ".mp4": FormatCapability(
        extension=".mp4",
        display_name="MP4",
        pydub_format="mp4",
        ffmpeg_encoder="aac",
        ffmpeg_muxer="mp4",
        lossless=False,
        output_extension=".mp4",
        export_args=("-b:a", "256k"),
    ),
    ".opus": FormatCapability(
        extension=".opus",
        display_name="Opus",
        pydub_format="opus",
        ffmpeg_encoder="libopus",
        ffmpeg_muxer="opus",
        lossless=False,
        output_extension=".opus",
        export_args=("-b:a", "192k"),
    ),
    ".wav": FormatCapability(
        extension=".wav",
        display_name="WAV",
        pydub_format="wav",
        ffmpeg_encoder="pcm_s16le",
        ffmpeg_muxer="wav",
        lossless=True,
        depth_codecs={2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"},
        output_extension=".wav",
    ),
    ".aiff": FormatCapability(
        extension=".aiff",
        display_name="AIFF",
        pydub_format="aiff",
        ffmpeg_encoder="pcm_s16be",
        ffmpeg_muxer="aiff",
        lossless=True,
        depth_codecs={2: "pcm_s16be", 3: "pcm_s24be", 4: "pcm_s32be"},
        output_extension=".aiff",
    ),
    ".aif": FormatCapability(
        extension=".aif",
        display_name="AIF",
        pydub_format="aiff",
        ffmpeg_encoder="pcm_s16be",
        ffmpeg_muxer="aiff",
        lossless=True,
        depth_codecs={2: "pcm_s16be", 3: "pcm_s24be", 4: "pcm_s32be"},
        output_extension=".aif",
    ),
    ".wv": FormatCapability(
        extension=".wv",
        display_name="WavPack",
        pydub_format="wv",
        ffmpeg_encoder="wavpack",
        ffmpeg_muxer="wv",
        lossless=True,
        output_extension=".wv",
    ),
    ".ape": FormatCapability(
        extension=".ape",
        display_name="Monkey's Audio",
        pydub_format=None,
        ffmpeg_encoder=None,
        ffmpeg_muxer=None,
        lossless=True,
        writable=False,
        output_extension=".ape",
    ),
    ".mpc": FormatCapability(
        extension=".mpc",
        display_name="Musepack",
        pydub_format=None,
        ffmpeg_encoder=None,
        ffmpeg_muxer=None,
        lossless=True,
        writable=False,
        output_extension=".mpc",
    ),
    ".spx": FormatCapability(
        extension=".spx",
        display_name="Speex",
        pydub_format="spx",
        ffmpeg_encoder="libspeex",
        ffmpeg_muxer="ogg",
        lossless=False,
        output_extension=".spx",
        export_args=("-c:a", "libspeex", "-q:a", "8"),
    ),
    ".dsf": FormatCapability(
        extension=".dsf",
        display_name="DSF",
        pydub_format=None,
        ffmpeg_encoder=None,
        ffmpeg_muxer=None,
        lossless=True,
        writable=False,
        output_extension=".dsf",
    ),
    ".wma": FormatCapability(
        extension=".wma",
        display_name="WMA",
        pydub_format="asf",
        ffmpeg_encoder="wmav2",
        ffmpeg_muxer="asf",
        lossless=False,
        # Completing the container is the whole point of WP-1's D-4 decision:
        # the converter could already read it while every is_supported_format
        # caller ignored it. Measured on FFmpeg 8.0.1 (wmav2 encoder + asf
        # muxer present); the probe and the round trip live in
        # audio_suite_shared/tests/test_audio_formats.py.
        output_extension=".wma",
        export_args=("-c:a", "wmav2", "-b:a", "192k"),
        # No ASF handler in TagHandlerFactory yet, so a writer must refuse
        # rather than discover a file it cannot tag (WP-6 adds the handler).
        tag_writable=False,
    ),
    ".aac": FormatCapability(
        extension=".aac",
        display_name="AAC",
        pydub_format=None,
        ffmpeg_encoder="aac",
        ffmpeg_muxer="adts",
        lossless=False,
        output_extension=".aac",
        # Raw ADTS carries no usable tag block; write it through FFmpeg's own
        # argument table (the converter does), never the pydub export path.
        tag_writable=False,
    ),
}

#: Codec names the converter speaks that are not one-to-one with a container.
#: ALAC is a codec stored in an M4A container, so "alac" is not an extension.
CODEC_TO_EXTENSION: dict[str, str] = {
    "alac": ".m4a",
    "aac": ".aac",
}

#: Codec names that are lossless whatever container they are written into:
#: ALAC lives in an M4A container, and M4A is otherwise an AAC container, so
#: the container row cannot answer this. Codec names outside this set take
#: their classification from their container's row.
LOSSLESS_CODECS: frozenset[str] = frozenset({"alac"})

#: Every extension the suite can read, in discovery order.
SUPPORTED_EXTENSIONS: tuple[str, ...] = tuple(FORMAT_MATRIX)

#: Containers with no encoder: readable, never writable.
READ_ONLY_EXTENSIONS: tuple[str, ...] = tuple(
    ext for ext, cap in FORMAT_MATRIX.items() if not cap.writable
)

#: Lossless containers.
LOSSLESS_EXTENSIONS: tuple[str, ...] = tuple(
    ext for ext, cap in FORMAT_MATRIX.items() if cap.lossless
)

#: Compressed/lossy containers.
COMPRESSED_EXTENSIONS: tuple[str, ...] = tuple(
    ext for ext, cap in FORMAT_MATRIX.items() if not cap.lossless
)

#: pydub export format string + ffmpeg quality params per writable extension.
#: Read-only containers and the FFmpeg-direct ones (.aac) are absent: asking
#: for their export arguments raises rather than guessing.
PYDUB_FORMAT: dict[str, tuple[str, list[str]]] = {
    ext: (cap.pydub_format, list(cap.export_args))
    for ext, cap in FORMAT_MATRIX.items()
    if cap.pydub_format is not None
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

    An extension the matrix does not cover — or a read-only container — raises
    instead of falling back to MP3. The old fallback encoded the *source
    stream as MP3 into a file named for another container*, which is the
    "silently mislabelled codec" defect: the file opens in a player and is
    not what its extension says.

    Args:
        ext: File extension including the leading dot (e.g. '.mp3').

    Returns:
        Tuple of pydub format string and ffmpeg parameter list.

    Raises:
        AudioFormatError: When *ext* is unknown or read-only.
    """
    lowered = ext.lower()
    capability = FORMAT_MATRIX.get(lowered)
    if capability is None or capability.pydub_format is None:
        reason = "not a writable suite container" if capability else "unknown"
        raise AudioFormatError(
            f"No export path for {ext!r}: the extension is {reason}."
        )
    return capability.pydub_format, list(capability.export_args)


#: Lossless extensions whose stream stores an integer bit depth, mapped to the
#: FFmpeg PCM codec for each source depth in bytes.  FFmpeg's WAV/AIFF muxers
#: default to 16-bit PCM, so without this pin a 24-bit source was silently
#: truncated to 16 bits on every in-place rewrite (F-10).
_DEPTH_CODECS: dict[str, dict[int, str]] = {
    ext: dict(cap.depth_codecs)
    for ext, cap in FORMAT_MATRIX.items()
    if cap.depth_codecs
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

    Raises:
        AudioFormatError: When *ext* is unknown or read-only (see
            :func:`get_export_args`).
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
