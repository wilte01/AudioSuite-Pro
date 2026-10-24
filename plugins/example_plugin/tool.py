"""tool.py — the example plugin's tool contribution.

The suite calls :func:`main` from two places, and both pass a folder:

* ``audiosuite example <dir> [--dry]`` runs it headless;
* the plugin's own window (``Example_Plugin.pyw``) runs it after the user
  picks a folder, or as soon as it opens when the driver passed ``--start``.

The function reports what it found — a file count per format and how many files
carry a genre tag — and writes nothing, so it is safe to run as a template for
a read-only plugin tool.  A plugin that writes must honour ``dry_run``; this one
has nothing to skip, which is why the flag only changes the wording.

:func:`parse_launch_args` reads the grammar the Master Driver launches every
plugin tool with — ``[directory, --live|--dry, --start|--no-start,
--end|--no-end]`` — so the plugin's window opens on the folder the driver was
pointed at, in the mode the driver was set to, runs the report by itself when
asked to start, and closes when that run finishes.  A plugin never builds that
argv itself: ``master_driver.runner.arg_builder._build_plugin_tool_args`` owns
it and this function is its reader.

Changed in 2.1.0: new module — the example tool contribution (Item 7.2).
Changed in 2.1.0: adds :class:`LaunchOptions` and :func:`parse_launch_args`, so
the window honours the driver's arguments instead of ignoring all four.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.tag_helper import is_supported, read_editable_tags


@dataclass(frozen=True)
class LaunchOptions:
    """What the Master Driver's argument grammar says about one launch.

    Attributes:
        directory: The folder the driver was pointed at (``""`` for a bare
            double-click of the launcher).
        dry_run: True for ``--dry``, False for ``--live``.
        start: True for ``--start``: the window runs the report as soon as it
            opens, without waiting for the Run button.
        end: True for ``--end``: the window closes when that run finishes, so
            the Master Driver can use the tool as a batch step.  A run that
            failed leaves the window open so its message can be read.
    """

    directory: str = ""
    dry_run: bool = False
    start: bool = False
    end: bool = False


#: The run-mode flags, mapped to the mode they select.  The driver sends
#: exactly one; a repeated flag is read last-wins like any command line.
_MODE_FLAGS: dict[str, bool] = {"--dry": True, "--live": False}
_START_FLAGS: dict[str, bool] = {"--start": True, "--no-start": False}
_END_FLAGS: dict[str, bool] = {"--end": True, "--no-end": False}


def parse_launch_args(argv: Sequence[str]) -> LaunchOptions:
    """Read the driver's argument grammar into :class:`LaunchOptions`.

    The first argument that is not a flag is the directory; unknown flags are
    ignored rather than rejected, because a plugin is third-party code that
    may be launched by a newer driver than it was written for.

    Args:
        argv: The arguments after the script name.

    Returns:
        The parsed options; a bare launch is live with no folder.
    """
    directory = ""
    dry_run = False
    start = False
    end = False
    for argument in argv:
        if argument in _MODE_FLAGS:
            dry_run = _MODE_FLAGS[argument]
        elif argument in _START_FLAGS:
            start = _START_FLAGS[argument]
        elif argument in _END_FLAGS:
            end = _END_FLAGS[argument]
        elif not argument.startswith("-") and not directory:
            directory = argument
    return LaunchOptions(directory=directory, dry_run=dry_run, start=start, end=end)


def audio_files(directory: str | Path) -> list[Path]:
    """Return every supported audio file under *directory*, sorted.

    Args:
        directory: Folder to walk recursively.

    Returns:
        Sorted file paths whose extension the tag layer supports.
    """
    root = Path(directory)
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.rglob("*") if path.is_file() and is_supported(str(path))
    )


def summarise(directory: str | Path) -> list[str]:
    """Build the report lines for *directory*.

    Args:
        directory: Folder to walk recursively.

    Returns:
        One line per statistic, plus one per file that carries a genre.
    """
    files = audio_files(directory)
    formats = Counter(path.suffix.lower().lstrip(".") for path in files)
    with_genre = 0
    for path in files:
        try:
            tags = read_editable_tags(str(path))
        except Exception:  # a plugin must not die on one unreadable file
            continue
        if tags.get("genre"):
            with_genre += 1
    lines = [
        f"Files:      {len(files)}",
        f"With genre: {with_genre}",
        "Formats:    "
        + (
            ", ".join(f"{name} ({count})" for name, count in sorted(formats.items()))
            or "none"
        ),
    ]
    return lines


def main(directory: str, dry_run: bool = False) -> None:
    """Print the example tool's report for *directory*.

    Args:
        directory: Folder to inspect.
        dry_run: Unused for output, kept so the signature matches the suite's
            run-mode convention; the tool never writes.
    """
    mode = "dry run" if dry_run else "live"
    print(f"Example Tool ({mode}) — {directory}")
    for line in summarise(directory):
        print(f"  {line}")
