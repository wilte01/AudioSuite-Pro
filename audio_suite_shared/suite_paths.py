"""
suite_paths.py — Locates the installation root that owns the suite's own files.

Every module that needs a file the suite ships *beside itself* asks the same
question: where is this installation's root? The config JSON, ``logs/``,
``plugins/``, the user guides, the committed ``fpcalc.exe``, ``discid.dll``
and the launcher scripts all live there, and so does ``pyproject.toml`` and
``CHANGELOG.md`` when the source tree is present.

It used to be answered nine times: ``Path(__file__).resolve().parent.parent``
in the config and logging modules, ``parents[2]`` in the plugin loader and the
Fingerprinter, ``dirname(__file__)/..`` twice in the Master Driver, and — for
the Help button — walking up from ``Path.cwd()`` until a directory was named
``AudioSuite-Pro``. That last one is the defect the others only risk: it
depends on the working directory and on the folder's *name*, so a renamed
checkout, a shortcut started in another folder, or any packaged build answered
"Help File Not Found" while the guide sat exactly where it was installed
(plan D-44).

Search order:

  1. ``AUDIOSUITE_ROOT``, which names the root outright - a portable or moved
     installation, and the seam the tests drive instead of monkeypatching
     ``__file__``
  2. ``sys._MEIPASS``, where a one-file build unpacks the data it ships
  3. the frozen executable's own directory, which is the root of a one-folder
     build
  4. walking up from this module: ``<root>/audio_suite_shared/suite_paths.py``

Nothing here reads the working directory, so a caller's ``cwd`` cannot change
which installation answers.

A file that lives inside one tool's package is ``suite_path("<tool>", "<name>")``:
still one derivation, with the package named outright instead of counted from
the caller's own position in the tree.

Changed in 2.5.0: :func:`suite_root_source` reports which rule answered, so
``doctor`` prints the root beside its provenance instead of a bare path.
Changed in 2.5.0: new module. The suite root had no shared implementation, so
every caller derived it itself; :func:`suite_root` and :func:`suite_path` are
now the only derivation, and the reuse lock's ``_hunts_the_suite_root_by_name``
fails on a module that goes back to matching a directory name (plan D-44).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = [
    "ROOT_SOURCE_BUNDLE",
    "ROOT_SOURCE_CHECKOUT",
    "ROOT_SOURCE_ENV",
    "ROOT_SOURCE_FROZEN",
    "SUITE_ROOT_ENV",
    "suite_path",
    "suite_root",
    "suite_root_source",
]

#: Environment variable that names the installation root outright.
SUITE_ROOT_ENV = "AUDIOSUITE_ROOT"

#: The four answers :func:`suite_root_source` can give, as a user-facing
#: label for the rule that won.  ``doctor`` prints this so an unexpected
#: root can be traced to the rule that produced it.
ROOT_SOURCE_ENV = """AUDIOSUITE_ROOT override"""
ROOT_SOURCE_BUNDLE = """sys._MEIPASS (one-file build)"""
ROOT_SOURCE_FROZEN = """the frozen executable's directory"""
ROOT_SOURCE_CHECKOUT = """the source checkout"""

#: This module's directory: ``<root>/audio_suite_shared/``.
_SHARED_DIR = Path(__file__).resolve().parent


def suite_root_source() -> tuple[Path, str]:
    """Return the installation root and the rule that answered it.

    Callers that only need the path want :func:`suite_root`; this exists for
    a diagnostic that has to explain *why* it got that root.  ``doctor``
    prints it, because the rule that won says where to look when the answer
    is wrong: an inherited ``AUDIOSUITE_ROOT`` points at the shell rather
    than at this installation.

    Returns:
        ``(root, source)``.  *source* is one of :data:`ROOT_SOURCE_ENV`,
        :data:`ROOT_SOURCE_BUNDLE`, :data:`ROOT_SOURCE_FROZEN` or
        :data:`ROOT_SOURCE_CHECKOUT`.
    """
    override = os.environ.get(SUITE_ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve(), ROOT_SOURCE_ENV

    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(str(bundle)).resolve(), ROOT_SOURCE_BUNDLE

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent, ROOT_SOURCE_FROZEN

    return _SHARED_DIR.parent, ROOT_SOURCE_CHECKOUT


def suite_root() -> Path:
    """Return the installation root that owns the suite's own files.

    Returns:
        The root directory: the ``AUDIOSUITE_ROOT`` override, the directory a
        one-file build unpacked into, the frozen executable's directory, or
        this module's parent.  The working directory is never consulted, so
        the answer does not change with the folder a tool was started from.
        :func:`suite_root_source` answers the same question with the rule
        that produced this root.
    """
    return suite_root_source()[0]
    override = os.environ.get(SUITE_ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()

    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(str(bundle)).resolve()

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return _SHARED_DIR.parent


def suite_path(*parts: str) -> Path:
    """Return the path of a suite-owned file, relative to :func:`suite_root`.

    Args:
        *parts: Path components below the root, e.g. ``"fpcalc.exe"`` or
            ``"documentation", "user_guides"``.

    Returns:
        The joined path.  It is not required to exist: a caller that ships the
        file optionally decides that for itself, exactly as it would with any
        other path.
    """
    return suite_root().joinpath(*parts)
