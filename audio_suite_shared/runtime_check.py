"""runtime_check.py — warn about a stale install and name the supported runtime.

The suite is used from a source checkout, where ``uv run audiosuite`` runs the
dependency graph pinned in ``uv.lock`` against an editable install built from
this tree.  A bare ``audiosuite`` on PATH can be an older ``pip install -e .``
whose editable finder was generated before later tool packages existed; because
each tool is registered by importing its CLI module, such an install dies at the
first tool it cannot resolve with a bare ``ModuleNotFoundError``.

The helpers here turn that failure into a message that names the missing module,
compares the installed metadata version with ``[project] version`` in this
checkout, and gives the two commands that fix it.  They are diagnostic only: no
state is written and nothing is repaired implicitly.

Changed in 1.4.0: added, so the CLI explains a stale editable install and
warns when the installed package version differs from the checkout.
Changed in 1.4.1: a matching version is no longer taken as proof of a current
install - the warning also resolves every package through ``install_map`` and
names the ones that import from another tree (PLAN D94).
"""

from __future__ import annotations

import importlib.metadata as metadata
import logging
from collections.abc import Sequence

from audio_suite_shared.install_map import (
    DISTRIBUTION_NAME as DISTRIBUTION_NAME,
)
from audio_suite_shared.install_map import packages_outside_checkout
from audio_suite_shared.project_version import declared_version

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The supported way to run the CLI from this checkout.
LOCKED_RUNTIME = "uv run audiosuite"

#: Build the locked environment from the committed lockfile.
SYNC_COMMAND = "uv sync --frozen --all-extras"

#: How many package names one staleness warning lists before summarising.
_MAX_NAMED_PACKAGES = 6

#: Whether the warning has already been printed by this process.
_warning_emitted = False


def reset_warning_state() -> None:
    """Forget that a warning was already printed.

    The warning is emitted once per process, so an in-process caller (the test
    suite, or an embedded run that invokes the CLI repeatedly) does not repeat
    the same paragraph.  Tests that need to observe it again call this from a
    fixture.
    """
    global _warning_emitted
    _warning_emitted = False


def installed_version() -> str | None:
    """Return the installed distribution version, or ``None`` if absent.

    Returns:
        The version recorded in the installed ``audiosuite-pro`` metadata, or
        ``None`` when this interpreter has no such distribution (a bare
        ``PYTHONPATH`` run, for example).
    """
    try:
        return metadata.version(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return None


def checkout_version() -> str | None:
    """Return the version this checkout declares, or ``None`` if unreadable.

    A diagnostic must never raise: ``--version`` is where a broken manifest is
    allowed to fail loudly, and it calls ``declared_version()`` directly.

    Returns:
        ``[project] version`` from the nearest ``pyproject.toml``, or ``None``
        when there is no manifest (installed wheel) or it cannot be parsed.
    """
    try:
        return declared_version()
    except (OSError, RuntimeError, ValueError) as exc:
        logger.debug("Cannot read the checkout version: %s", exc)
        return None


def _version_mismatch_warning(installed: str, checkout: str) -> str:
    """Explain an install whose metadata version is not this checkout's.

    Args:
        installed: Version the installed distribution reports.
        checkout: Version ``pyproject.toml`` declares.

    Returns:
        The warning text, naming both versions and the two repair commands.
    """
    return (
        f"Warning: the installed audiosuite-pro is {installed}, but this "
        f"checkout declares {checkout}. The install is stale, so tool packages "
        f"or commands added since it was created may be missing.\n"
        f"Run the locked environment instead: {LOCKED_RUNTIME} --help "
        f"(build it with: {SYNC_COMMAND})."
    )


def _unmapped_packages_warning(version: str, names: Sequence[str]) -> str:
    """Explain a same-version install that imports packages from elsewhere.

    A rebuild from an older tree, or a non-editable install of the current
    version, compares equal on version and still runs code this checkout does
    not contain.  The names are the finding; ``doctor`` prints each origin.

    Args:
        version: The version both the install and the checkout report.
        names: Packages that resolve outside this checkout, in name order.

    Returns:
        The warning text, listing up to six packages and summarising the rest.
    """
    listed = ", ".join(names[:_MAX_NAMED_PACKAGES])
    remaining = len(names) - _MAX_NAMED_PACKAGES
    if remaining > 0:
        listed += f" and {remaining} more"
    return (
        f"Warning: the installed audiosuite-pro matches this checkout "
        f"({version}), but these packages resolve outside it: {listed}. The "
        f"install was built from a different tree, so the code being run is not "
        f"the code in this checkout.\n"
        f"Run `audiosuite doctor` to see where each one lives, or use the locked "
        f"environment: {LOCKED_RUNTIME} --help "
        f"(build it with: {SYNC_COMMAND})."
    )


def _stale_install_reason() -> str | None:
    """Return why this install disagrees with the checkout, if it does.

    The version comparison is the cheap fast path and the common failure, so a
    mismatch returns without touching the import machinery.  A match is not
    proof of a current install, so only then are the packages resolved - one
    scan per process, cached by the warning's once-per-process gate.

    Returns:
        The warning text, or ``None`` when the install matches the checkout
        (including when either version is unknown).
    """
    installed = installed_version()
    checkout = checkout_version()
    if installed is None or checkout is None:
        return None
    if installed != checkout:
        return _version_mismatch_warning(installed, checkout)
    outside = packages_outside_checkout()
    if not outside:
        return None
    return _unmapped_packages_warning(checkout, [status.name for status in outside])


def stale_install_warning() -> str | None:
    """Describe how this install disagrees with the checkout, if it does.

    Two findings count as stale: an installed metadata version that differs
    from ``[project] version``, and - only when the versions match - a package
    that resolves outside the checkout, which a same-version rebuild produces.
    The answer is returned once per process, so a caller running several
    commands does not repeat the paragraph.

    Returns:
        A warning for stderr when the install disagrees with this checkout,
        otherwise ``None`` (including when either version is unknown, and on
        every call after the first warning).
    """
    global _warning_emitted
    if _warning_emitted:
        return None
    warning = _stale_install_reason()
    if warning is None:
        return None
    _warning_emitted = True
    return warning


def missing_modules_message(missing: Sequence[str]) -> str:
    """Explain missing first-party packages without stopping the CLI.

    Args:
        missing: Top-level module names that could not be imported.

    Returns:
        A short warning naming the packages, the version pair when it disagrees,
        and the commands that repair the environment.  ``audiosuite doctor``
        prints the per-package detail and the commands that are unavailable.
    """
    listed = ", ".join(sorted(set(missing))) or "an unknown package"
    installed = installed_version()
    checkout = checkout_version()
    version_note = ""
    if installed is not None and checkout is not None and installed != checkout:
        version_note = (
            f" The installed audiosuite-pro is {installed}, but this checkout "
            f"declares {checkout}, so its editable install predates them."
        )
    return (
        f"Warning: AudioSuite-Pro started without: {listed}.{version_note}\n"
        "Run `audiosuite doctor` to see which commands are unavailable, or "
        "rebuild the locked environment:\n"
        f"    {SYNC_COMMAND}\n"
        f"    {LOCKED_RUNTIME} --help"
    )
