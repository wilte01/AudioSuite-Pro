"""splitter.py — cut one recording into tracks at its silent gaps.

Everything here is Tk-free: :func:`split_file` plans and writes one source,
:func:`run_split` walks a folder and publishes the three callbacks the GUI and
the CLI share.

The cut is sample-accurate.  The file is decoded once with pydub, each track is
sliced by millisecond offset (the unit the plan was made in) and re-encoded
through the shared export path, which pins a lossless source's bit depth
(``audio_formats.preserve_depth_params``).  The planned boundaries partition
``[0, total)``, so the tracks cover the file end to end and nothing is lost
between them: a boundary moves *where* the silence falls, never whether the
samples survive.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile
from mutagen import MutagenError
from pydub import AudioSegment

from audio_suite_shared.audio_formats import (
    SUPPORTED_EXTENSIONS,
    get_export_args,
    preserve_depth_params,
)
from audio_suite_shared.exceptions import AudioConfigValueError, AudioSuiteError

from .cue import build_track_cue, write_track_cue
from .detector import detect_gaps
from .models import Gap, SplitSettings, Track, plan_tracks
from .naming import render_name

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The run report's file name, written into the folder the run scanned.
REPORT_NAME = "track_splitter_split_log.txt"

#: Extensions the splitter accepts as input: every format the suite can read.
INPUT_EXTENSIONS: tuple[str, ...] = tuple(SUPPORTED_EXTENSIONS)


@dataclass(frozen=True)
class SplitOutcome:
    """What one source produced.

    Attributes:
        source: The file that was split.
        gaps: The silent runs the detector found.
        tracks: The plan, in track order.
        written: The files written (empty for a dry run).
        cue_path: The sheet written, when the run asked for one.
        album: Album title read from the source's tags.
        artist: Album artist read from the source's tags.
        title: Title read from the source's tags (its stem when it has none).
        discarded_ms: Leading and trailing silence no track keeps.
    """

    source: Path
    gaps: list[Gap]
    tracks: list[Track]
    written: list[Path] = field(default_factory=list)
    cue_path: Path | None = None
    album: str = ""
    artist: str = ""
    title: str = ""
    discarded_ms: int = 0

    @property
    def summary(self) -> str:
        """One line describing the split, for a progress list."""
        if len(self.tracks) == 1 and not self.gaps:
            return f"[{self.source.name}] no gap found - 1 track kept whole"
        return (
            f"[{self.source.name}] {len(self.tracks)} tracks "
            f"({len(self.written)} written)"
        )


def read_source_tags(source: Path) -> tuple[str, str, str]:
    """Return the source's ``(album, artist, title)``.

    A file with no tags, or tags this build cannot read, yields empty strings
    (and the filename stem for the title): naming is never a reason to fail a
    split.

    Args:
        source: File to read.

    Returns:
        The three tag values, stripped.
    """
    try:
        audio = MutagenFile(str(source), easy=True)
    except (MutagenError, OSError):
        return "", "", source.stem
    if audio is None or audio.tags is None:
        return "", "", source.stem

    def first(key: str) -> str:
        value = audio.tags.get(key)
        if not value:
            return ""
        return str(value[0]).strip()

    return first("album"), first("artist"), first("title") or source.stem


def _write_track(audio: AudioSegment, destination: Path, source: Path) -> None:
    """Encode one slice to *destination* at the source's own depth.

    Args:
        audio: The decoded slice.
        destination: File to write; its extension selects the encoder.
        source: The file the slice came from, whose declared depth the encoder
            pins for a lossless container.
    """
    extension = destination.suffix.lower()
    pydub_format, params = get_export_args(extension)
    depth = preserve_depth_params(extension, str(source))
    audio.export(str(destination), format=pydub_format, parameters=[*params, *depth])


def split_file(
    source: Path,
    output_dir: Path,
    settings: SplitSettings,
    *,
    dry_run: bool = False,
) -> SplitOutcome:
    """Detect, plan and write the tracks of one source.

    Args:
        source: File to split.
        output_dir: Folder the tracks are written to; created when missing.
        settings: Detection and naming settings.
        dry_run: Plan and report, but write no audio and no sheet.

    Returns:
        The outcome, including the plan and the written paths.

    Raises:
        AudioFormatError: The source cannot be decoded, or its container has no
            writable export path.
        AudioConfigValueError: A rendered filename would overwrite the source.
        OSError: A file cannot be written.
    """
    audio = AudioSegment.from_file(str(source))
    total_ms = len(audio)
    gaps = detect_gaps(source, settings, total_ms=total_ms)
    album, artist, title = read_source_tags(source)
    tracks = plan_tracks(gaps, total_ms, settings, title_prefix=title)

    discarded = total_ms - sum(track.duration_ms for track in tracks)
    if dry_run:
        return SplitOutcome(
            source=source,
            gaps=gaps,
            tracks=tracks,
            album=album,
            artist=artist,
            title=title,
            discarded_ms=discarded,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    extension = source.suffix.lower()
    written: list[Path] = []
    for track in tracks:
        name = render_name(
            settings.naming_pattern,
            number=track.number,
            title=track.title,
            extension=extension,
            album=album,
            artist=artist,
        )
        destination = output_dir / name
        if destination.resolve() == source.resolve():
            raise AudioConfigValueError(
                "The naming pattern produces the source file's own name, which "
                "would overwrite it. Change the output folder or the pattern.",
                context={"file": str(destination)},
            )
        _write_track(audio[track.start_ms : track.end_ms], destination, source)
        written.append(destination)

    cue_path: Path | None = None
    if settings.write_cue:
        sheet = build_track_cue(
            source_name=source.name, tracks=tracks, title=album, performer=artist
        )
        cue_path = write_track_cue(output_dir / f"{source.stem}.cue", sheet)

    return SplitOutcome(
        source=source,
        gaps=gaps,
        tracks=tracks,
        written=written,
        cue_path=cue_path,
        album=album,
        artist=artist,
        title=title,
        discarded_ms=discarded,
    )


def _clock(ms: int) -> str:
    """Render milliseconds as ``MM:SS.mmm``."""
    minutes, rest = divmod(max(ms, 0), 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def _report_lines(
    directory: Path,
    output_dir: Path,
    settings: SplitSettings,
    outcomes: list[SplitOutcome],
    *,
    dry_run: bool,
    errors: int,
    elapsed: float,
) -> list[str]:
    """Build the run report's lines, in the suite's documented shape."""
    threshold = f"{settings.silence_db:g} dBFS"
    header = [
        "TRACK SPLITTER REPORT\n",
        f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}\n",
        f"Source: {directory}\n",
        f"Output: {output_dir}\n",
        f"Minimum silence: {settings.min_silence_ms} ms at {threshold}\n",
        f"Minimum track: {settings.min_track_ms} ms\n",
        f"Boundary: {settings.boundary}\n",
        f"Naming: {settings.naming_pattern}\n",
        f"CUE sheet: {'yes' if settings.write_cue else 'no'}\n",
        "=" * 60 + "\n",
    ]
    body: list[str] = []
    for outcome in outcomes:
        body.append(f"{outcome.source}\n")
        body.append(f"  {len(outcome.tracks)} tracks\n")
        for track in outcome.tracks:
            body.append(
                f"    {track.number:02d}  {_clock(track.start_ms)}-"
                f"{_clock(track.end_ms)}  {track.title}\n"
            )
        if outcome.cue_path is not None:
            body.append(f"  CUE: {outcome.cue_path}\n")
    tracks = sum(len(outcome.tracks) for outcome in outcomes)
    written = sum(len(outcome.written) for outcome in outcomes)
    cues = sum(1 for outcome in outcomes if outcome.cue_path is not None)
    discarded = sum(outcome.discarded_ms for outcome in outcomes)
    summary = [
        "\n" + "=" * 60 + "\n",
        "SUMMARY:\n",
        f"Files: {len(outcomes)}\n",
        f"Tracks: {tracks}\n",
        f"Files written: {written}\n",
        f"CUE sheets: {cues}\n",
        f"Silence discarded: {discarded} ms\n",
        f"Errors: {errors}\n",
        f"Time: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}\n",
    ]
    return [*header, *body, *summary]


def _sources(directory: Path) -> list[Path]:
    """Return the splitter's inputs, in a stable order."""
    return sorted(
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in INPUT_EXTENSIONS
    )


def run_split(
    directory: str,
    *,
    output_dir: str | None = None,
    settings: SplitSettings | None = None,
    dry_run: bool = False,
    on_progress: Any = None,
    on_complete: Any = None,
    on_error: Any = None,
    **_ignored: Any,
) -> None:
    """Split every supported file in *directory*.

    Args:
        directory: Folder to scan, recursively.
        output_dir: Where the tracks go; defaults to a ``split`` folder beside
            the scanned one.
        settings: Detection and naming settings; the defaults when omitted.
        dry_run: Plan and report only; write no audio and no sheet.
        on_progress: Called per file with ``processed``/``total``/``errors``/
            ``display_text``.
        on_complete: Called once with the run's counters, the written paths and
            the log lines.
        on_error: Called with one message when the run cannot start at all.

    The report is written beside the scanned folder and a failed write is
    logged, never raised: by then the audio work has already happened.
    """
    source_root = Path(directory)
    active = settings or SplitSettings()
    target = Path(output_dir) if output_dir else source_root / "split"
    started = time.monotonic()

    if on_error is None:
        on_error = lambda _message: None  # noqa: E731 - a no-op default seam
    if not source_root.is_dir():
        on_error(f"The folder {directory!r} does not exist.")
        return

    sources = _sources(source_root)
    if not sources:
        on_error(f"No supported audio files found in {directory!r}.")
        return

    outcomes: list[SplitOutcome] = []
    logged: list[str] = []
    errors = 0
    for index, source in enumerate(sources, start=1):
        try:
            outcome = split_file(source, target, active, dry_run=dry_run)
        except (AudioSuiteError, OSError, ValueError) as exc:
            errors += 1
            message = getattr(exc, "message", None) or str(exc)
            logged.append(f"{source}  ERROR  {message}\n")
            display = f"[{source.name}] error: {message}"
        else:
            outcomes.append(outcome)
            logged.append(f"{source}  {outcome.summary}\n")
            display = outcome.summary
        if on_progress is not None:
            on_progress(
                processed=index,
                total=len(sources),
                skipped=0,
                errors=errors,
                display_text=display,
            )

    elapsed = time.monotonic() - started
    lines = _report_lines(
        source_root,
        target,
        active,
        outcomes,
        dry_run=dry_run,
        errors=errors,
        elapsed=elapsed,
    )
    report_path = source_root / REPORT_NAME
    try:
        report_path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - depends on the folder's permissions
        logger.error("Could not write the run report: %s", exc, exc_info=True)

    if on_complete is not None:
        on_complete(
            total=len(sources),
            processed=len(sources),
            skipped=0,
            errors=errors,
            duration_secs=elapsed,
            log_entries=[*logged],
            tracks=sum(len(outcome.tracks) for outcome in outcomes),
            files_written=sum(len(outcome.written) for outcome in outcomes),
            output_dir=str(target),
            cue_files=[
                os.path.basename(str(outcome.cue_path))
                for outcome in outcomes
                if outcome.cue_path is not None
            ],
        )
