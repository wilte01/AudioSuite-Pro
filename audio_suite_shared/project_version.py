"""
project_version.py — The suite version, read from ``pyproject.toml`` (plan G2).

``[project] version`` in ``pyproject.toml`` is the single place the version
lives.  ``audiosuite --version`` reports it, so a release bump is one edit with
no second constant to forget.

Why not ``importlib.metadata``?
-------------------------------

``importlib.metadata.version()`` is derived from the installed distribution, so
it is only correct once the package is installed — a source checkout run with
``python -m audio_suite_shared.cli_app`` would raise
``PackageNotFoundError``.  It is kept as a *fallback* for an installed layout
that has no ``pyproject.toml`` beside it.

Why ``tomllib`` and not a hand-rolled parser?
---------------------------------------------

``tomllib`` is standard library on every interpreter the suite supports (the
floor is 3.11), so this module parses the file properly instead of pattern-
matching it.  An earlier revision read the one key it needed with a scoped
regular expression, because the project still declared a 3.10 floor where no
TOML parser ships in the standard library.  That floor has been raised, and
hand-matching TOML is strictly worse: it cannot see array-of-table or dotted
key syntax, and it would have to be re-audited against every TOML edge case the
standard library already handles correctly.

Changed in 2.1.6: the import block is re-sorted against the corrected ruff
target py311, so ``tomllib`` sits in the standard-library block the 3.11 floor
puts it in (R-15, PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

_PACKAGE_NAME = "audiosuite-pro"


def find_pyproject(start: Path | None = None) -> Path | None:
    """Return the nearest ``pyproject.toml`` at or above *start*.

    Args:
        start: Directory to search upwards from.  Defaults to the directory
            containing this module, which walks
            ``audio_suite_shared/`` → the repository root.

    Returns:
        The path to the nearest ``pyproject.toml``, or ``None`` when the
        package is installed without its source tree beside it.
    """
    base = (start or Path(__file__).resolve().parent).resolve()
    for directory in (base, *base.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def parse_project_version(text: str) -> str | None:
    """Extract ``[project] version`` from ``pyproject.toml`` source.

    Args:
        text: The full contents of a ``pyproject.toml``.

    Returns:
        The declared version string, or ``None`` when the ``[project]`` table
        has no string ``version`` key.

    Raises:
        tomllib.TOMLDecodeError: If *text* is not valid TOML.  A malformed
            manifest is a broken checkout, and silently reporting a different
            version would be a lie in ``--version``.
    """
    project: Any = tomllib.loads(text).get("project")
    if not isinstance(project, dict):
        return None
    version: Any = project.get("version")
    return version if isinstance(version, str) else None


@lru_cache(maxsize=1)
def declared_version() -> str:
    """Return the suite version, from ``pyproject.toml`` when available.

    The result is cached: ``--version`` and the test suite call it, and a
    file read per call would be needless work on a hot CLI path.

    Returns:
        The ``[project] version`` string, e.g. ``"1.0.0"``.

    Raises:
        tomllib.TOMLDecodeError: If the discovered ``pyproject.toml`` is not
            valid TOML.  Deliberately not swallowed: a corrupt manifest is a
            deployment fault, and reporting the installed distribution's
            version instead would hide it.
        RuntimeError: If the version is in neither ``pyproject.toml`` nor the
            installed distribution metadata.  Failing loudly beats reporting
            a wrong version, which would be a silent lie in ``--version``.
    """
    pyproject = find_pyproject()
    if pyproject is not None:
        version = parse_project_version(pyproject.read_text(encoding="utf-8"))
        if version is not None:
            return version

    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as dist_version

    try:
        return dist_version(_PACKAGE_NAME)
    except PackageNotFoundError as exc:  # pragma: no cover - defensive
        raise RuntimeError(
            f"cannot determine the {_PACKAGE_NAME} version: no [project] version "
            f"in {pyproject} and the distribution is not installed"
        ) from exc
