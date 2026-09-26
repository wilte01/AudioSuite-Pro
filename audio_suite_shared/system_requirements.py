"""system_requirements.py — Declared non-Python runtime dependencies.

The suite shells out to external executables that cannot be declared in
``[project.dependencies]`` because they are not importable packages: there is
no wheel, no index, and no way for ``uv sync`` to install them.  ``ffmpeg`` and
``ffprobe`` are invoked from 35 production files, so an undeclared dependency
is not a style gap — ``uv sync`` succeeds, ``audiosuite`` imports, and the
failure only surfaces as a raw ``FileNotFoundError`` when a user processes a
file.

This module is the single machine-readable declaration of those requirements.
It is consumed by :mod:`audio_suite_shared.preflight` (which reports a missing
binary as a startup warning) and is the wording source that the user guides
quote verbatim, so the dialog a user sees and the guide they read cannot drift
apart silently.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Sequence
from dataclasses import dataclass

#: Resolves an executable name to an absolute path, or ``None`` when it is not
#: on ``PATH``.  Matches :func:`shutil.which`; injectable so callers (and tests)
#: can supply an alternative discovery mechanism without re-implementing the
#: presence check.
ExecutableResolver = Callable[[str], str | None]


@dataclass(frozen=True)
class SystemRequirement:
    """One external executable the suite requires at run time.

    Attributes:
        name: The executable name as it appears on ``PATH``.
        purpose: One sentence explaining what the suite uses it for, so a user
            can tell whether the missing binary matters to their task.
        install_hints: Plain-text install commands per platform.  Plain text
            only, never a URL, because a link in a dialog rots silently.
    """

    name: str
    purpose: str
    install_hints: tuple[str, ...]

    def render(self) -> list[str]:
        """Return this requirement as report lines.

        Returns:
            One line naming the binary and its purpose, followed by one
            indented install line per hint.
        """
        lines = [f"- {self.name} ({self.purpose})"]
        lines.extend(f"    install: {hint}" for hint in self.install_hints)
        return lines


FFMPEG_PURPOSE = "decodes and encodes the audio formats the suite reads and writes"
FFPROBE_PURPOSE = "reads stream metadata (duration, codec, bitrate) for analysis tools"

_FFMPEG_INSTALL_HINTS = (
    "Windows: winget install Gyan.FFmpeg",
    "macOS:   brew install ffmpeg",
    "Linux:   sudo apt install ffmpeg",
)

#: The external executables the suite shells out to.  ``ffprobe`` is a separate
#: entry rather than part of the ``ffmpeg`` entry because the two are installed
#: and missing independently, and the suite's ``run_secure_subprocess``
#: allowlist already treats them as a pair: a host with ``ffmpeg`` but no
#: ``ffprobe`` fails on a different code path and needs a different fix.
REQUIRED_EXECUTABLES: tuple[SystemRequirement, ...] = (
    SystemRequirement("ffmpeg", FFMPEG_PURPOSE, _FFMPEG_INSTALL_HINTS),
    SystemRequirement("ffprobe", FFPROBE_PURPOSE, _FFMPEG_INSTALL_HINTS),
)


def find_missing_requirements(
    requirements: Sequence[SystemRequirement] = REQUIRED_EXECUTABLES,
    *,
    resolver: ExecutableResolver | None = None,
) -> list[SystemRequirement]:
    """Return the declared requirements whose executable cannot be found.

    Args:
        requirements: The requirements to probe.  Defaults to
            :data:`REQUIRED_EXECUTABLES`.
        resolver: Executable lookup, defaulting to :func:`shutil.which`.

    Returns:
        The subset of *requirements* whose ``name`` does not resolve, in
        declaration order.  An empty list means every requirement is satisfied.
    """
    lookup = shutil.which if resolver is None else resolver
    return [requirement for requirement in requirements if not lookup(requirement.name)]


def format_requirement_report(missing: Sequence[SystemRequirement]) -> str:
    """Build the human-readable report for a set of missing executables.

    Args:
        missing: The requirements reported by :func:`find_missing_requirements`.

    Returns:
        A multi-line report naming each missing binary, what it is for, and how
        to install it on each supported platform.
    """
    lines = [
        f"Audio Suite could not find {len(missing)} required system tool(s):",
        "",
    ]
    for requirement in missing:
        lines.extend(requirement.render())
    lines.extend(
        [
            "",
            "Tools that shell out to these binaries will fail until they are "
            "installed.  The suite still starts so tools that do not need "
            "them remain usable.",
        ]
    )
    return "\n".join(lines)
