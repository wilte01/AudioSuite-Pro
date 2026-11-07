"""concat.py — the stream-copy writer: FFmpeg's concat demuxer, no re-encode.

Copying is offered only when every input carries the first file's côdec and
parameters and the run asks for no boundary processing, because the demuxer
joins the streams as they are: it cannot insert silence or overlap frames.
A file whose container differs from the inputs is refused by the caller rather
than written with a mismatched codec.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

from __future__ import annotations

import tempfile
from collections.abc import Sequence
from pathlib import Path

# Changed in 2.5.0: the resolver moved to audio_suite_shared.ffmpeg (D-38).
from audio_suite_shared.ffmpeg import FFMPEG_PATH
from audio_suite_shared.secure_subprocess import run_secure_subprocess


def escape_concat_path(path: Path | str) -> str:
    """Quote *path* for an FFmpeg ``concat`` list file.

    The demuxer's list format is one ``file '...'`` line per input, and a
    single quote inside a path is written as ``'\\''`` - the same escaping the
    shell uses, which the demuxer's own parser accepts.

    Args:
        path: The file to quote.

    Returns:
        The quoted token, single quotes included.
    """
    text = str(path).replace("\\", "/")
    return "'" + text.replace("'", "'\\''") + "'"


def concat_list_text(sources: Sequence[Path]) -> str:
    """Return the demuxer list that joins *sources* in order.

    Args:
        sources: Files to join, in order.

    Returns:
        One ``file '<path>'`` line per source, newline terminated.
    """
    return "".join(f"file {escape_concat_path(source)}\n" for source in sources)


def write_copy(sources: Sequence[Path], output: Path) -> None:
    """Join *sources* into *output* with a stream copy.

    Args:
        sources: Files to join, in order; every one must already share the
            codec and stream parameters (the caller proves it).
        output: File to write.

    Raises:
        ValueError: Fewer than two sources were given.
        subprocess.CalledProcessError: FFmpeg refused the join.
    """
    if len(sources) < 2:
        raise ValueError("A stream copy needs at least two files to join.")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="audio_joiner_") as folder:
        list_path = Path(folder) / "concat.txt"
        list_path.write_text(concat_list_text(sources), encoding="utf-8")
        run_secure_subprocess(
            FFMPEG_PATH,
            [
                "-hide_banner",
                "-nostdin",
                "-nostats",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                "-c",
                "copy",
                str(output),
            ],
            capture_output=True,
            check=True,
        )
