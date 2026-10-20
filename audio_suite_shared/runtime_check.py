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
"""

from __future__ import annotations

import importlib.metadata as metadata
import logging
from collections.abc import Sequence

from audio_suite_shared.project_version import declared_version

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The distribution name in ``pyproject.toml``.
DISTRIBUTION_NAME = "audiosuite-pro"

#: The supported way to run the CLI from this checkout.
LOCKED_RUNTIME = "uv run audiosuite"

#: Build the locked environment from the committed lockfile.
SYNC_COMMAND = "uv sync --frozen --all-extras"


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


def stale_install_warning() -> str | None:
    """Describe a version mismatch between the install and this checkout.

    Returns:
        A warning for stderr when the installed distribution's metadata version
        differs from ``[project] version``, otherwise ``None`` (including when
        either version is unknown).
    """
    installed = installed_version()
    checkout = checkout_version()
    if installed is None or checkout is None or installed == checkout:
        return None
    return (
        f"Warning: the installed audiosuite-pro is {installed}, but this "
        f"checkout declares {checkout}. The install is stale, so tool packages "
        f"or commands added since it was created may be missing.\n"
        f"Run the locked environment instead: {LOCKED_RUNTIME} --help "
        f"(build it with: {SYNC_COMMAND})."
    )


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
