"""
ffmpeg_params.py
Build the FFmpeg command list for a given format/quality combination.

Pure function — no tkinter, no file I/O, no subprocess execution.
The caller is responsible for running the returned command.
"""

# ── Sample-rate presets ──────────────────────────────────────────────────────

SAMPLE_RATE_PRESETS: list[str] = [
    "source",
    "44100",
    "48000",
    "88200",
    "96000",
    "176400",
    "192000",
]

# ── Bit-depth presets (WAV/AIFF output) ─────────────────────────────────────

BIT_DEPTH_PRESETS: list[str] = ["auto", "16", "24", "32", "float"]

# Explicit WAV output-depth overrides. The 'auto' mode (default) derives the
# PCM codec from the probed source properties instead (see _wav_codec).
WAV_DEPTH_CODECS: dict[str, str] = {
    "16": "pcm_s16le",
    "24": "pcm_s24le",
    "32": "pcm_s32le",
    "float": "pcm_f32le",
}


def _wav_codec(
    depth: str,
    source_sample_fmt: str | None = None,
    source_bits_per_sample: int = 0,
) -> str:
    """Resolve the WAV PCM codec for a depth request.

    depth is one of '16', '24', '32', 'float' (explicit override) or 'auto'.
    In 'auto' mode the codec is derived from the source's decoded sample
    format and raw bit depth (e.g. 24-bit FLAC decodes to s32 with
    bits_per_raw_sample=24, which maps to pcm_s24le). Unknown/unprobed
    inputs fall back to pcm_s16le (the historical converter behaviour).

    Returns:
        An FFmpeg PCM codec string.
    """
    if depth in WAV_DEPTH_CODECS:
        return WAV_DEPTH_CODECS[depth]

    if depth == "auto":
        fmt = (source_sample_fmt or "").lower()
        if fmt in ("dbl", "dblp"):
            return "pcm_f64le"
        if fmt in ("flt", "fltp"):
            return "pcm_f32le"
        if fmt in ("s64", "s64p"):
            return "pcm_s64le"
        if fmt in ("s32", "s32p"):
            return "pcm_s32le" if source_bits_per_sample == 32 else "pcm_s24le"
        if source_bits_per_sample >= 25:
            return "pcm_s32le"
        if 17 <= source_bits_per_sample <= 24:
            return "pcm_s24le"

    return "pcm_s16le"


def get_ffmpeg_params(
    input_path: str,
    output_path: str,
    output_format: str,
    quality: str = "highest",
    wav_depth: str = "auto",
    source_sample_fmt: str | None = None,
    source_bits_per_sample: int = 0,
    sample_rate: str = "source",
) -> list[str]:
    """
    Return the FFmpeg command list for converting input_path to
    output_path in the given format at the given quality level.

    Args:
        input_path:           Absolute path to the source audio file.
        output_path:          Absolute path for the converted output file.
        output_format:        Target format string (e.g. 'mp3', 'flac').
        quality:              One of 'highest', 'high', 'medium'.
        wav_depth:            WAV-only: '16', '24', '32', 'float' override,
                              or 'auto' to preserve the source depth.
        source_sample_fmt:    WAV-only, auto mode: source sample format as
                              reported by ffprobe (e.g. 's32', 'flt').
        source_bits_per_sample: WAV-only, auto mode: source raw bits per
                              sample as reported by ffprobe.
        sample_rate:          Target sample rate: 'source' to keep the
                              original rate, or a numeric string (e.g.
                              '44100', '48000', '96000').

    Returns:
        List of strings ready to pass to ``run_secure_subprocess`` (the
        suite's validated subprocess wrapper).
    """
    # Base command — suppress banner, only show errors, overwrite output
    cmd: list[str] = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        input_path,
        "-y",
    ]

    # ── Per-format codec / bitrate settings ───────────────────────────────────

    if output_format == "mp3":
        if quality == "highest":
            cmd.extend(["-codec:a", "libmp3lame", "-q:a", "0"])  # VBR V0
        elif quality == "high":
            cmd.extend(["-codec:a", "libmp3lame", "-q:a", "2"])  # VBR V2
        else:
            cmd.extend(["-codec:a", "libmp3lame", "-b:a", "192k"])
        cmd.extend(["-id3v2_version", "3"])  # broad compat

    elif output_format == "aac":
        if quality == "highest":
            cmd.extend(["-codec:a", "aac", "-b:a", "320k", "-strict", "experimental"])
        elif quality == "high":
            cmd.extend(["-codec:a", "aac", "-b:a", "256k", "-strict", "experimental"])
        else:
            cmd.extend(["-codec:a", "aac", "-b:a", "192k", "-strict", "experimental"])

    elif output_format == "m4a":
        if quality == "highest":
            cmd.extend(
                ["-codec:a", "aac", "-b:a", "320k", "-vn", "-strict", "experimental"]
            )
        elif quality == "high":
            cmd.extend(
                ["-codec:a", "aac", "-b:a", "256k", "-vn", "-strict", "experimental"]
            )
        else:
            cmd.extend(
                ["-codec:a", "aac", "-b:a", "192k", "-vn", "-strict", "experimental"]
            )

    elif output_format == "ogg":
        if quality == "highest":
            cmd.extend(["-codec:a", "libvorbis", "-q:a", "10"])
        elif quality == "high":
            cmd.extend(["-codec:a", "libvorbis", "-q:a", "8"])
        else:
            cmd.extend(["-codec:a", "libvorbis", "-q:a", "6"])

    elif output_format == "mp4":
        if quality == "highest":
            cmd.extend(
                ["-codec:a", "aac", "-b:a", "320k", "-vn", "-strict", "experimental"]
            )
        elif quality == "high":
            cmd.extend(
                ["-codec:a", "aac", "-b:a", "256k", "-vn", "-strict", "experimental"]
            )
        else:
            cmd.extend(
                ["-codec:a", "aac", "-b:a", "192k", "-vn", "-strict", "experimental"]
            )

    elif output_format == "opus":
        if quality == "highest":
            cmd.extend(["-codec:a", "libopus", "-b:a", "256k"])
        elif quality == "high":
            cmd.extend(["-codec:a", "libopus", "-b:a", "192k"])
        else:
            cmd.extend(["-codec:a", "libopus", "-b:a", "128k"])

    elif output_format == "flac":
        cmd.extend(["-codec:a", "flac", "-compression_level", "8"])

    elif output_format == "wav":
        cmd.extend(
            [
                "-codec:a",
                _wav_codec(wav_depth, source_sample_fmt, source_bits_per_sample),
            ]
        )

    elif output_format in ("aiff", "aif"):
        # AIFF is big-endian PCM: pcm_s24be at the best-preset tiers,
        # pcm_s16be otherwise.
        codec = "pcm_s24be" if quality in ("highest", "high") else "pcm_s16be"
        cmd.extend(["-codec:a", codec])

    elif output_format == "alac":
        cmd.extend(["-codec:a", "alac"])

    elif output_format == "wma":
        if quality == "highest":
            cmd.extend(["-codec:a", "wmav2", "-b:a", "320k"])
        elif quality == "high":
            cmd.extend(["-codec:a", "wmav2", "-b:a", "256k"])
        else:
            cmd.extend(["-codec:a", "wmav2", "-b:a", "192k"])

    elif output_format == "wv":
        # WavPack is lossless; there is no bitrate/quality tier to set.
        cmd.extend(["-codec:a", "wavpack"])

    else:
        # Passthrough for any unknown/unhandled format. Note: "ape" is
        # deliberately NOT routed here — it is rejected upstream by
        # formats.can_convert()/available_output_formats() before this
        # function is ever called, because FFmpeg has no APE encoder.
        cmd.extend(["-codec:a", "copy"])

    # ── Sample rate override ─────────────────────────────────────────────────
    if sample_rate and sample_rate != "source":
        cmd.extend(["-ar", sample_rate])

    # Preserve all metadata and audio streams
    cmd.extend(
        [
            "-map",
            "0:a",
            "-map_metadata",
            "0",
            "-map_metadata:s:a",
            "0:s:a",
        ]
    )

    cmd.append(output_path)
    return cmd
