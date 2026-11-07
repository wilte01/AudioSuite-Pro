"""join.py — join a folder's segments into one file.

One call does the whole job: probe every input, decide between a stream copy
and a re-encode, plan the length, write the file and the run report, and
publish the three callbacks the window and the command share.  The length the
report states is the same arithmetic the window previews (:func:`plan_duration_ms`),
so a run's result can be checked against its plan rather than against itself.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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
from audio_suite_shared.audio_probe import probe_stream
from audio_suite_shared.exceptions import AudioConfigValueError, AudioSuiteError

from .compat import CompatibilityReport, probe_inputs
from .concat import write_copy
from .crossfade import equal_power_mix
from .models import (
    JoinSettings,
    output_name,
    plan_duration_ms,
    validate_output_name,
    validate_overlap,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Extensions the joiner accepts as segments: every format the suite can read.
INPUT_EXTENSIONS: tuple[str, ...] = tuple(SUPPORTED_EXTENSIONS)

#: The run report's names, one per mode: the file a run names is the one its
#: View Log opens, and a dry run and a live run must not overwrite each other.
REPORT_NAMES: dict[bool, str] = {
    True: "audio_joiner_dry_run_log.txt",
    False: "audio_joiner_sync_log.txt",
}

#: Containers mutagen can write; a joined WAV or AIFF is reported instead of
#: tagged, because the format carries no tag block at all.
TAGGABLE_EXTENSIONS: frozenset[str] = frozenset(
    {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus"}
)

#: The easy-tag fields copied from the first segment.
EASY_TAG_FIELDS: tuple[str, ...] = (
    "title",
    "artist",
    "album",
    "albumartist",
    "date",
    "genre",
    "tracknumber",
    "discnumber",
    "comment",
)


@dataclass(frozen=True)
class JoinOutcome:
    """What one join produced.

    Attributes:
        sources: The segments, in join order.
        output: The file the join is written to.
        durations_ms: Each segment's measured length.
        planned_ms: The length the plan states (``sum + gaps - overlaps``).
        written: The file written (``None`` for a dry run).
        copy_used: True when the join was a stream copy, not a re-encode.
        tags_copied: True when the first segment's tags reached the output.
        sample_rate: The output's sample rate.
        channels: The output's channel count.
        notes: The report's per-run notes (compatibility, tagging, copy).
    """

    sources: tuple[Path, ...]
    output: Path
    durations_ms: tuple[int, ...]
    planned_ms: int
    written: Path | None = None
    copy_used: bool = False
    tags_copied: bool = False
    sample_rate: int = 0
    channels: int = 0
    notes: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        """One line describing the join, for a progress list."""
        mode = "stream copy" if self.copy_used else "re-encoded"
        return (
            f"[{self.output.name}] {len(self.sources)} segments, "
            f"{_clock(self.planned_ms)}, {mode}"
        )


def _clock(ms: int) -> str:
    """Render milliseconds as ``MM:SS.mmm``."""
    minutes, rest = divmod(max(ms, 0), 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def measure_durations(sources: Sequence[Path]) -> tuple[int, ...]:
    """Return each source's length in milliseconds without decoding it.

    Args:
        sources: Files to measure.

    Returns:
        One length per source, rounded to the millisecond.

    Raises:
        AudioConfigValueError: A source reports no measurable length.
    """
    durations: list[int] = []
    for source in sources:
        stream = probe_stream(str(source))
        if stream.duration_sec <= 0:
            raise AudioConfigValueError(
                f"{source.name} reports no measurable length, so it cannot be "
                "joined predictably.",
                context={"file": str(source)},
            )
        durations.append(int(round(stream.duration_sec * 1000)))
    return tuple(durations)


def copy_tags(source: Path, destination: Path) -> bool:
    """Copy *source*'s tags onto *destination*.

    Only the easy-tag fields are written, through the destination's own loaded
    object, so a FLAC file's Vorbis block is updated in place: rebinding
    ``FLAC.tags`` would save the stale block and lose the writing silently.

    Args:
        source: The segment whose tags are the template.
        destination: The joined file to tag.

    Returns:
        True when the tags were written; False when the container holds no tag
        block the suite can write, or the write failed.
    """
    if destination.suffix.lower() not in TAGGABLE_EXTENSIONS:
        return False
    try:
        origin = MutagenFile(str(source), easy=True)
        target = MutagenFile(str(destination), easy=True)
        if origin is None or target is None or origin.tags is None:
            return False
        if target.tags is None:
            target.add_tags()
        for field in EASY_TAG_FIELDS:
            if field in origin:
                target[field] = origin[field]
        target.save()
    except (MutagenError, OSError, ValueError) as exc:
        logger.warning("Could not copy tags onto %s: %s", destination, exc)
        return False
    return True


def _load(source: Path, report: CompatibilityReport) -> AudioSegment:
    """Decode *source* at the join's target rate and channel count."""
    audio = AudioSegment.from_file(str(source))
    if audio.frame_rate != report.sample_rate:
        audio = audio.set_frame_rate(report.sample_rate)
    if audio.channels != report.channels:
        audio = audio.set_channels(report.channels)
    return audio


def combine(segments: Sequence[AudioSegment], settings: JoinSettings) -> AudioSegment:
    """Join decoded *segments* at their boundaries.

    Args:
        segments: Decoded audio, in order; each already at the same rate and
            channel count.
        settings: The boundary settings.

    Returns:
        The joined audio.

    Raises:
        ValueError: Fewer than one segment, or a crossfade that does not fit.
    """
    if not segments:
        raise ValueError("A join needs at least one segment.")
    combined = segments[0]
    for segment in segments[1:]:
        if settings.crossfade_ms:
            combined = equal_power_mix(combined, segment, settings.crossfade_ms)
        elif settings.gap_ms:
            gap = AudioSegment.silent(
                duration=settings.gap_ms, frame_rate=combined.frame_rate
            ).set_channels(combined.channels)
            combined = combined + gap + segment
        else:
            combined = combined + segment
    return combined


def _export(audio: AudioSegment, destination: Path, template: Path) -> None:
    """Encode *audio* to *destination*, pinning a lossless template's depth."""
    extension = destination.suffix.lower()
    pydub_format, params = get_export_args(extension)
    depth = preserve_depth_params(extension, str(template))
    audio.export(str(destination), format=pydub_format, parameters=[*params, *depth])


def join_files(
    sources: Sequence[Path],
    output: Path,
    settings: JoinSettings,
    *,
    dry_run: bool = False,
    on_step: Callable[[int, int, str], None] | None = None,
) -> JoinOutcome:
    """Join *sources* into *output*.

    Args:
        sources: The segments, in join order.
        output: File to write.
        settings: The boundary settings.
        dry_run: Plan and report, but write no audio.
        on_step: Called after each segment is read, with ``(processed, total,
            name)`` so a long join shows progress.

    Returns:
        The outcome, including the plan and the file written.

    Raises:
        AudioConfigValueError: Fewer than two segments, a crossfade that does
            not fit, or an output that would overwrite a segment.
        AudioFormatError: A container has no writable export path.
        OSError: A file cannot be read or written.
        subprocess.SubprocessError: A stream copy was refused by FFmpeg.
    """
    if len(sources) < 2:
        raise AudioConfigValueError(
            "A join needs at least two files; "
            f"{len(sources)} would have nothing to join.",
            context={"segments": len(sources)},
        )
    if output.resolve() in {source.resolve() for source in sources}:
        raise AudioConfigValueError(
            "The output would replace one of the segments it joins. Choose "
            "another output file.",
            context={"file": str(output)},
        )
    report = probe_inputs(sources)
    durations = tuple(measure_durations(sources))
    validate_overlap(durations, settings.crossfade_ms)
    planned = plan_duration_ms(durations, settings)

    notes: list[str] = []
    copy_used = (
        settings.copy_when_compatible
        and report.identical
        and not settings.processes_boundaries
        and output.suffix.lower() == sources[0].suffix.lower()
    )
    if report.identical:
        notes.append("Compatibility: every segment matches the first file's stream")
    else:
        notes.append(f"Compatibility: re-encoded - {report.mismatch}")
    if copy_used:
        notes.append("Writer: stream copy (no re-encode)")
    else:
        notes.append("Writer: re-encode")

    if on_step is not None:
        for index, source in enumerate(sources, start=1):
            # The line a reader sees per segment: its name and its measured
            # length, the two facts the join order is chosen on.
            on_step(
                index,
                len(sources),
                f"{source.name}  {_clock(durations[index - 1])}",
            )

    if dry_run:
        return JoinOutcome(
            sources=tuple(sources),
            output=output,
            durations_ms=durations,
            planned_ms=planned,
            copy_used=copy_used,
            sample_rate=report.sample_rate,
            channels=report.channels,
            notes=tuple(notes),
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    if copy_used:
        write_copy(sources, output)
    else:
        segments = [_load(source, report) for source in sources]
        _export(combine(segments, settings), output, sources[0])

    tags_copied = copy_tags(sources[0], output)
    notes.append(
        "Tags: copied from the first segment"
        if tags_copied
        else "Tags: not written (the container has no writable tag block)"
    )
    return JoinOutcome(
        sources=tuple(sources),
        output=output,
        durations_ms=durations,
        planned_ms=planned,
        written=output,
        copy_used=copy_used,
        tags_copied=tags_copied,
        sample_rate=report.sample_rate,
        channels=report.channels,
        notes=tuple(notes),
    )


def _normalise_entry(text: str) -> str:
    """Return a comparable key for one order entry.

    The spacing around a comma is not significant: the window joins names with
    ``","`` while a person types ``", "``, and both name the same file.

    Args:
        text: One entry, or a run of comma-separated pieces.

    Returns:
        The text with whitespace runs collapsed and commas unspaced, casefolded.
    """
    collapsed = " ".join(text.split())
    return collapsed.replace(" ,", ",").replace(", ", ",").casefold()


def _named_file(candidate: str, directory: Path, known: dict[str, Path]) -> Path | None:
    """Return the file *candidate* names, or None when it names nothing.

    Args:
        candidate: A file name inside *directory*, or an absolute path.
        directory: The folder relative names are resolved against.
        known: The folder's files, keyed by :func:`_normalise_entry`.

    Returns:
        The file, or None.
    """
    path = Path(candidate)
    if not path.is_absolute():
        path = directory / candidate
    if path.is_file():
        return path
    return known.get(_normalise_entry(candidate))


def split_order(order: str, directory: Path) -> list[str]:
    """Split an order string into its entries, keeping commas inside a name.

    The separator is a comma, but a comma is a legal character in a file name --
    ``1-03 Johnny, Don't Do It.mp3`` -- so a comma separates two entries only
    when what precedes it names no file.  The split therefore reads the folder:
    the longest run of comma-separated pieces that names a real file is one
    entry, and a run that names nothing is handed back as the single piece it
    started from so the caller's message can name it.

    Args:
        order: The comma-separated order string.
        directory: Folder the names are relative to.

    Returns:
        The entries, in the order they were given; an entry that names a file
        is reported in the folder's own spelling, so a name the driver wrote
        without a space after its comma reads the way it is on disk.
    """
    return [
        path.name if path is not None else text
        for text, path in _resolved_entries(order, directory)
    ]


def preferred_order(directory: Path, order: str) -> list[Path]:
    """Return the files *order* names, ignoring any it does not name.

    The window uses this to lay its list out in the launched order; the run
    resolves strictly, so a name that matches nothing is still reported.

    Args:
        directory: Folder the names are relative to.
        order: The comma-separated order string.

    Returns:
        The matching files, in the order they were named.
    """
    return [
        path for _text, path in _resolved_entries(order, directory) if path is not None
    ]


def _resolved_entries(order: str, directory: Path) -> list[tuple[str, Path | None]]:
    """Split *order* into ``(entry, file)`` pairs, resolving what it can.

    Args:
        order: The comma-separated order string.
        directory: Folder the names are relative to.

    Returns:
        One pair per entry; the path is None when the entry names no file.
    """
    pieces = [piece.strip() for piece in order.split(",")]
    known = (
        {
            _normalise_entry(path.name): path
            for path in directory.iterdir()
            if path.is_file()
        }
        if directory.is_dir()
        else {}
    )
    resolved: list[tuple[str, Path | None]] = []
    index = 0
    while index < len(pieces):
        if not pieces[index]:
            index += 1
            continue
        for end in range(len(pieces) - 1, index - 1, -1):
            candidate = ",".join(pieces[index : end + 1])
            path = _named_file(candidate, directory, known)
            if path is not None:
                resolved.append((candidate, path))
                index = end + 1
                break
        else:
            resolved.append((pieces[index], None))
            index += 1
    return resolved


def resolve_order(directory: Path, order: str) -> list[Path]:
    """Return the segments to join, in the order asked for.

    Args:
        directory: Folder the order's names are relative to.
        order: Comma-separated names (or absolute paths); empty means every
            supported file in the folder, sorted by name.  A name may contain a
            comma: the split is confirmed against the folder's own files.

    Returns:
        The segment paths, in join order.

    Raises:
        AudioConfigValueError: An entry names no file, or the folder holds
            fewer than two supported files.
    """
    if not order.strip():
        found = sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in INPUT_EXTENSIONS
        )
        if len(found) < 2:
            raise AudioConfigValueError(
                f"{directory} holds {len(found)} supported audio file(s); a join "
                "needs at least two. Add files or name them with --order.",
                context={"folder": str(directory), "files": len(found)},
            )
        return found
    chosen: list[Path] = []
    for entry, path in _resolved_entries(order, directory):
        if path is None:
            raise AudioConfigValueError(
                f"{entry!r} names no file in {directory}.",
                context={"entry": entry, "folder": str(directory)},
            )
        chosen.append(path)
    if len(chosen) < 2:
        raise AudioConfigValueError(
            f"A join needs at least two files; --order named {len(chosen)}.",
            context={"segments": len(chosen)},
        )
    return chosen


def _report_lines(
    folder: Path,
    outcome: JoinOutcome,
    settings: JoinSettings,
    *,
    dry_run: bool,
    elapsed: float,
) -> list[str]:
    """Build the run report's lines, in the suite's documented shape."""
    header = [
        "AUDIO JOINER REPORT\n",
        f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}\n",
        f"Folder: {folder}\n",
        f"Output: {outcome.output}\n",
        f"Segments: {len(outcome.sources)}\n",
        f"Gap: {settings.gap_ms} ms\n",
        f"Crossfade: {settings.crossfade_ms} ms\n",
        *[f"{note}\n" for note in outcome.notes],
        "=" * 60 + "\n",
    ]
    body = [
        f"{source.name}  {_clock(duration)}\n"
        for source, duration in zip(outcome.sources, outcome.durations_ms)
    ]
    summary = [
        "\n" + "=" * 60 + "\n",
        "SUMMARY:\n",
        f"Planned length: {_clock(outcome.planned_ms)}\n",
        f"Written: {1 if outcome.written is not None else 0}\n",
        f"Writer: {'stream copy' if outcome.copy_used else 're-encode'}\n",
        f"Tags copied: {'yes' if outcome.tags_copied else 'no'}\n",
        "Errors: 0\n",
        f"Time: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}\n",
    ]
    return [*header, *body, *summary]


def run_join(
    directory: str,
    *,
    order: str = "",
    output: str = "",
    settings: JoinSettings | None = None,
    dry_run: bool = False,
    on_progress: Any = None,
    on_complete: Any = None,
    on_error: Any = None,
    **_ignored: Any,
) -> None:
    """Join one folder's segments into a single file.

    Args:
        directory: Folder the segments live in.
        order: Comma-separated names in join order; empty joins every
            supported file in the folder, sorted by name.
        output: File to write; defaults to the first segment's stem plus
            ``_joined`` beside it.
        settings: Boundary settings; the defaults when omitted.
        dry_run: Plan and report only; write no audio.
        on_progress: Called per segment with ``processed``/``total``/``errors``/
            ``display_text``.
        on_complete: Called once with the run's counters, the output path and
            the log lines.
        on_error: Called with one message when the run cannot start at all.

    The report is written beside the segments and a failed write is logged,
    never raised: by then the audio work has already happened.
    """
    folder = Path(directory)
    active = settings or JoinSettings()
    started = time.monotonic()
    if on_error is None:
        on_error = lambda _message: None  # noqa: E731 - a no-op default seam
    if not folder.is_dir():
        on_error(f"The folder {directory!r} does not exist.")
        return

    try:
        sources = resolve_order(folder, order)
    except (AudioConfigValueError, AudioSuiteError) as exc:
        on_error(getattr(exc, "message", None) or str(exc))
        return

    target = (
        Path(output)
        if output
        else folder / output_name(sources[0].name, sources[0].suffix)
    )
    try:
        validate_output_name(str(target))
    except AudioConfigValueError as exc:
        on_error(exc.message)
        return
    logged: list[str] = []

    def step(processed: int, total: int, text: str) -> None:
        if on_progress is not None:
            on_progress(
                processed=processed,
                total=total,
                skipped=0,
                errors=0,
                display_text=text,
            )

    try:
        outcome = join_files(sources, target, active, dry_run=dry_run, on_step=step)
    except (AudioSuiteError, OSError, ValueError, subprocess.SubprocessError) as exc:
        message = getattr(exc, "message", None) or str(exc)
        logged.append(f"{target}  ERROR  {message}\n")
        on_error(message)
        return

    elapsed = time.monotonic() - started
    lines = _report_lines(folder, outcome, active, dry_run=dry_run, elapsed=elapsed)
    report_path = folder / REPORT_NAMES[dry_run]
    report_written = True
    try:
        report_path.write_text("".join(lines), encoding="utf-8")
    except OSError as exc:  # pragma: no cover - depends on the folder's permissions
        report_written = False
        logger.error("Could not write the run report: %s", exc, exc_info=True)

    logged.append(f"{outcome.summary}\n")
    if on_complete is not None:
        on_complete(
            total=len(sources),
            processed=len(sources),
            skipped=0,
            errors=0,
            duration_secs=elapsed,
            log_entries=[*logged],
            output=str(target),
            duration_ms=outcome.planned_ms,
            segments=len(sources),
            reencoded=not outcome.copy_used,
            tags_copied=outcome.tags_copied,
            report=str(report_path),
        )
        _ = report_written
