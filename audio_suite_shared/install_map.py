"""install_map.py — where each first-party package is imported from.

A source checkout and the installed distribution can disagree about the *same*
version, and comparing metadata versions cannot see it: an editable install
rebuilt from an older tree keeps the finder it was created with, and a
non-editable install of the current version puts every package in
``site-packages``.  So the question "is the code I am running the code in this
checkout?" is answered by resolving each first-party package through the
installed import machinery and comparing its origin with the checkout root.

Two consumers share this module: ``audiosuite doctor`` (a full report, one line
per package) and ``runtime_check.stale_install_warning()`` (one warning naming
the packages that resolved elsewhere).  Sharing the resolver is what keeps
their verdicts an invariant instead of a coincidence.

Changed in 1.4.1: extracted from ``doctor_cli`` so the CLI warning and
``doctor`` answer the same question with one resolver (PLAN D94).
"""

from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.project_version import find_pyproject

#: The distribution name in ``pyproject.toml``.
DISTRIBUTION_NAME = "audiosuite-pro"

#: Directory names that never hold a first-party importable package.  Only
#: directories with an ``__init__.py`` are candidates anyway; this keeps the
#: deliberately non-package trees (``utilities``, ``user_guides``) and the
#: test package out of the report.
_NOT_PACKAGES = frozenset({"__pycache__", ".venv", ".git", "build", "dist", "tests"})


@dataclass(frozen=True)
class PackageStatus:
    """One first-party package, resolved through the installed import system.

    Attributes:
        name: Top-level package name.
        state: ``"ok"``, ``"missing"`` or ``"elsewhere"``.
        location: Resolved ``__init__.py`` path, when one was found.
        commands: CLI commands this package backs (empty for GUI-only code).
    """

    name: str
    state: str
    location: str | None = None
    commands: tuple[str, ...] = ()


def checkout_root() -> Path | None:
    """Return the source-checkout root, or ``None`` when there is none.

    Returns:
        The directory holding the nearest ``pyproject.toml``, or ``None`` for
        an installed layout that ships no manifest (a built wheel).
    """
    pyproject = find_pyproject()
    return None if pyproject is None else pyproject.parent


def checkout_packages(root: Path) -> list[str]:
    """Return the top-level importable packages in *root*, sorted.

    Args:
        root: Checkout root holding ``pyproject.toml``.

    Returns:
        Directory names with an ``__init__.py``, excluding the test package and
        build/venv trees.  Empty only when the scan itself is wrong.
    """
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir()
        and entry.name not in _NOT_PACKAGES
        and not entry.name.startswith(".")
        and (entry / "__init__.py").is_file()
    )


def resolve_package(name: str, root: Path) -> PackageStatus:
    """Resolve *name* through the installed import system.

    Args:
        name: Top-level package name from the checkout.
        root: Checkout root the package must resolve inside.

    Returns:
        ``ok`` when the spec's origin lives under *root*, ``missing`` when no
        spec is found, ``elsewhere`` when a different copy wins the import.
    """
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        # A meta-path finder that raises is still "not importable from this
        # install"; the report must describe that, not crash on it.
        return PackageStatus(name=name, state="missing")
    if spec is None:
        return PackageStatus(name=name, state="missing")
    origin = spec.origin
    if origin is None:
        # Namespace package: the finder maps directories, not a module file.
        return PackageStatus(name=name, state="ok")
    path = Path(origin).resolve()
    if root not in path.parents:
        return PackageStatus(name=name, state="elsewhere", location=str(path))
    return PackageStatus(name=name, state="ok", location=str(path))


def editable_install() -> bool:
    """Return whether the installed distribution is an editable install."""
    try:
        distribution = metadata.distribution(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return False
    return any("__editable__" in str(item) for item in distribution.files or [])


def packages_outside_checkout(root: Path | None = None) -> list[PackageStatus]:
    """Return every checkout package that resolves outside *root*.

    Only ``elsewhere`` cases are returned: a package that is missing entirely is
    a different diagnosis (the CLI's registration warning names it), and an
    empty scan says nothing about the install, so neither belongs in a
    staleness warning.

    Args:
        root: Checkout root, defaulting to the discovered one.

    Returns:
        The packages whose origin is another install, in name order; empty when
        there is no checkout or every package maps to it.
    """
    resolved_root = root if root is not None else checkout_root()
    if resolved_root is None:
        return []
    names = checkout_packages(resolved_root)
    statuses = (resolve_package(name, resolved_root) for name in names)
    return sorted(
        (status for status in statuses if status.state == "elsewhere"),
        key=lambda status: status.name,
    )
