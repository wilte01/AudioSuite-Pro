"""The one seam through which a duplicate reaches the operating system Trash.

Delete and ASX-stub both remove the duplicate, and both route here.  There is
deliberately no ``unlink`` fallback: a permanent delete is unrecoverable and
would make the tool's safety statement false.  When ``send2trash`` is missing,
the run installs it into the interpreter that is actually running the tool,
before it touches a file; only a failed install refuses the run.

Keeping the import and the call in one module is also what lets a test assert
the exact paths a run would trash without sending the fixture to the real
Recycle Bin.

Changed in 2.4.0: new module (PLAN_duplicate_disposition_2026-11-02.md DD-2).
"""

from __future__ import annotations

import importlib
import os
from collections.abc import Callable
from pathlib import Path

from audio_suite_shared.optional_deps import InstallOutcome, Requirement, ensure

#: The runtime dependency, installed on first use into ``sys.executable``.
#: It is a base dependency because both Delete and ASX-stub need it, but the
#: launcher can start under an environment that predates the sync, so the
#: first run that needs it installs it rather than sending the user to pip.
SEND2TRASH_REQUIREMENT = Requirement(
    module="send2trash",
    packages=("send2trash",),
    label="Recycle Bin support",
    download_mb=1,
    minimum_version="1.8.0",
    extra="",
)

_send2trash: Callable[[str], None] | None = None
SEND2TRASH_AVAILABLE = False


def _load_backend() -> None:
    """Import ``send2trash`` into this process, if it is installed."""
    global SEND2TRASH_AVAILABLE, _send2trash
    importlib.invalidate_caches()
    try:
        from send2trash import send2trash as backend
    except ImportError:
        _send2trash = None
        SEND2TRASH_AVAILABLE = False
    else:
        _send2trash = backend
        SEND2TRASH_AVAILABLE = True


_load_backend()


class TrashUnavailableError(RuntimeError):
    """The Trash backend is not installed, so nothing may be removed."""


def available() -> bool:
    """Return whether a duplicate can be moved to the Recycle Bin.

    Returns:
        True when ``send2trash`` imported successfully.
    """
    return SEND2TRASH_AVAILABLE and _send2trash is not None


def ensure_available(
    *,
    installer: Callable[[Requirement], InstallOutcome] | None = None,
    reload_backend: Callable[[], None] | None = None,
) -> InstallOutcome:
    """Make the Trash backend importable, installing it when necessary.

    The install goes into the interpreter running this process — the project's
    ``.venv`` when a launcher re-executed there, not the system Python whose
    copy the user may already have found.  A tool must not tell a
    non-technical user to run pip, and an install into another interpreter is
    the same as no install at all.

    Args:
        installer: Test seam, defaulting to :func:`optional_deps.ensure`.
        reload_backend: Test seam for re-importing the package in this
            process after the install; defaults to :func:`_load_backend`.

    Returns:
        The install outcome.  ``ok`` is True only when the backend is
        importable here after the attempt.
    """
    if available():
        return InstallOutcome(True, "Recycle Bin support is ready.")

    outcome = (installer or ensure)(SEND2TRASH_REQUIREMENT)
    if not outcome.ok:
        return outcome

    (reload_backend or _load_backend)()
    if not available():
        return InstallOutcome(
            False,
            "Recycle Bin support was installed but could not be loaded.",
            detail=outcome.detail,
        )
    return outcome


def move_to_trash(path: str | os.PathLike[str]) -> None:
    """Move *path* to the operating system's Recycle Bin.

    Args:
        path: The file to remove from the library.

    Raises:
        TrashUnavailableError: If the backend is missing.  The caller reports
            this as a fatal run error before any file is touched.
        OSError: If the backend refuses the move; the caller counts it as a
            per-file error and the file remains in place.
    """
    if _send2trash is None:
        raise TrashUnavailableError(
            "The send2trash package is required to delete or replace duplicates"
        )
    target = str(Path(path).resolve())
    try:
        _send2trash(target)
    except OSError as exc:
        raise OSError(f"Could not move {target} to the Recycle Bin: {exc}") from exc
