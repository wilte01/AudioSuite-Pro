"""
optional_deps.py — install an optional extra the first time a tool needs it.

The suite's ML tools (Stem Separator, ML Denoiser) run on Demucs and RNNoise,
which live in the ``ml`` extra rather than the base dependencies: torch alone is
gigabytes, and the other tools must stay installable without it.  Asking the user
to run ``uv sync --extra ml`` makes a working run depend on a command they have
no reason to know — and it silently does nothing when the tool was started by a
different interpreter than the one ``uv`` installs into.

So the install is deferred to the first run that needs it and performed by the
application, into **the interpreter that is actually running** (``sys.executable``)
— which, because every launcher re-executes itself under ``<root>/.venv``, is the
project's own environment rather than a second copy in the system Python.  Two
properties make that trustworthy:

* the package is probed in a **subprocess**, so "did the install work" is a real
  import in a clean process — a half-installed torch cannot poison the GUI
  process, and a broken wheel is reported as a failure instead of a crash; and
* the version floor from :mod:`pyproject.toml` is re-checked afterwards, because
  installing *a* version is not the same as installing a compatible one.

This module owns no widgets and never blocks the caller's thread: the GUI layer
(:func:`audio_suite_shared.ui_common.install_optional_dependency`) runs
:func:`ensure` on a worker thread and marshals the outcome back to Tk.

Changed in 2.1.0: initial version.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final

from .secure_subprocess import run_secure_subprocess

logger = logging.getLogger(f"audio_suite.{__name__}")

#: A pip install of torch can take several minutes on a slow connection; the
#: timeout only exists so a wedged download cannot hold a worker thread forever.
INSTALL_TIMEOUT_SECONDS = 1800

#: A probe imports the package, which for torch means loading its DLLs.
PROBE_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class Requirement:
    """One optional dependency a tool can install for itself.

    Attributes:
        module: Import name to probe, e.g. ``"demucs"``.
        packages: pip requirement names, e.g. ``("demucs",)``.  Deliberately
            bare names: the version floor is checked after the install instead,
            because ``>=`` is a subprocess-security pattern and pip already
            resolves the newest compatible release.
        label: User-facing name, e.g. ``"Demucs"``.
        download_mb: Approximate download size, quoted to the user before a
            multi-gigabyte download starts.
        minimum_version: Distribution version floor, or None when any version
            is acceptable.
        extra: The ``pyproject.toml`` extra that ships the package, quoted in
            the fix command ``doctor`` prints.
    """

    module: str
    packages: tuple[str, ...]
    label: str
    download_mb: int
    minimum_version: str | None = None
    extra: str = "ml"


#: Demucs 4.1 is the release the stem-separator adapter was measured against; it
#: brings torch, which is the bulk of the download.
DEMUCS = Requirement(
    module="demucs",
    packages=("demucs",),
    label="Demucs",
    download_mb=2500,
    minimum_version="4.1.0",
)

#: RNNoise (``pyrnnoise``) is a small wheel with no torch dependency.
RNNOISE = Requirement(
    module="pyrnnoise",
    packages=("pyrnnoise",),
    label="RNNoise",
    download_mb=5,
    minimum_version="0.4.5",
)

#: Tool id (``ToolManifest.id``) -> the requirement that tool installs on first
#: use.  ``doctor`` reads this to answer "will the tool I am about to run find
#: its extra in the interpreter its launcher uses", so a new tool that needs an
#: extra must add itself here; ``tests/test_optional_deps.py`` derives the same
#: set from the tools' own call sites and fails if the two disagree.
TOOL_REQUIREMENTS: Final[Mapping[str, Requirement]] = {
    "ml_denoiser": RNNOISE,
    "stem_separator": DEMUCS,
}


@dataclass(frozen=True)
class InstallOutcome:
    """The result of :func:`ensure`, ready to show to the user.

    Attributes:
        ok: True when the requirement is importable at (or above) its floor.
        message: One or two sentences for the dialog or the report line.
        detail: Tail of the pip output, for the log and for a failure dialog —
            never the only explanation.
    """

    ok: bool
    message: str
    detail: str = ""


def _tail(text: str, *, lines: int = 12) -> str:
    """Return the last *lines* non-empty lines of *text*."""
    kept = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(kept[-lines:])


def _first_failure_line(text: str) -> str:
    """Return the most useful line of a failed import's stderr."""
    stripped = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(stripped):
        if line.startswith("ModuleNotFoundError") or line.startswith("ImportError"):
            return line
    return stripped[-1] if stripped else "the import failed"


def _python_probe(
    code: str, *, timeout: int, python: str | None = None
) -> subprocess.CompletedProcess[str]:
    """Run *code* in a fresh interpreter and return the completed process.

    *python* names the interpreter to ask; the default is the one running this
    code.  ``doctor`` passes the launcher's interpreter instead, so its report
    describes the process the tool will actually run in rather than this one.
    """
    return run_secure_subprocess(
        python or sys.executable,
        ["-c", code],
        timeout=timeout,
        capture_output=True,
        check=False,
        log_failure=False,
    )


def import_failure(
    module: str, *, timeout: int = PROBE_TIMEOUT_SECONDS, python: str | None = None
) -> str | None:
    """Return why *module* cannot be imported, or None when it can.

    The probe is a subprocess: it answers "can the interpreter that will run
    the tool import it", which is the question the user's run depends on, and
    it keeps a heavy or broken import (torch's DLL load, for instance) out of
    the GUI process.

    Args:
        module: Import name, e.g. ``"demucs"``.
        timeout: Seconds the probe may take before it is treated as failed.
        python: Interpreter to probe; defaults to the one running this code.
    """
    try:
        completed = _python_probe(f"import {module}", timeout=timeout, python=python)
    except (subprocess.SubprocessError, OSError) as exc:
        return f"the check could not be run ({exc})"
    if completed.returncode == 0:
        return None
    return _first_failure_line((completed.stderr or "") + (completed.stdout or ""))


def installed_version(
    distribution: str, *, timeout: int = PROBE_TIMEOUT_SECONDS
) -> str | None:
    """Return the installed version of *distribution*, or None when unknown."""
    code = f"import importlib.metadata as m\nprint(m.version({distribution!r}))\n"
    try:
        completed = _python_probe(code, timeout=timeout)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.debug("version probe for %s failed: %s", distribution, exc)
        return None
    if completed.returncode != 0:
        return None
    version = completed.stdout.strip().splitlines()
    return version[-1].strip() if version else None


def _numeric(version: str) -> tuple[int, ...]:
    """Return the leading numeric components of *version* (``"4.1.0rc1"`` → 4,1,0)."""
    parts: list[int] = []
    for chunk in version.replace("-", ".").split("."):
        digits = "".join(char for char in chunk if char.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def meets_floor(version: str | None, floor: str | None) -> bool:
    """Return True when *version* satisfies *floor* (``None`` floor always does)."""
    if floor is None:
        return True
    if version is None:
        return False
    have, need = _numeric(version), _numeric(floor)
    width = max(len(have), len(need))
    return have + (0,) * (width - len(have)) >= need + (0,) * (width - len(need))


def _run_pip(
    packages: tuple[str, ...], *, timeout: int = INSTALL_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """Install *packages* into the running interpreter with pip."""
    logger.info("Installing %s into %s", ", ".join(packages), sys.executable)
    return run_secure_subprocess(
        sys.executable,
        [
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--disable-pip-version-check",
            "--no-input",
            *packages,
        ],
        timeout=timeout,
        capture_output=True,
        check=False,
    )


def ensure(
    requirement: Requirement,
    *,
    pip_runner: Callable[[tuple[str, ...]], subprocess.CompletedProcess[str]]
    | None = None,
    probe: Callable[[str], str | None] | None = None,
    version_of: Callable[[str], str | None] | None = None,
) -> InstallOutcome:
    """Make *requirement* importable, installing it when it is not.

    Args:
        requirement: The dependency to provide.
        pip_runner: Test seam — a callable taking the package names and
            returning a ``CompletedProcess``.  Defaults to :func:`_run_pip`.
        probe: Test seam — a callable returning the import failure reason.
            Defaults to :func:`import_failure`.
        version_of: Test seam — a callable returning a distribution's installed
            version.  Defaults to :func:`installed_version`.

    Returns:
        An :class:`InstallOutcome`; ``ok`` is only True when the package imports
        *and* satisfies its version floor.
    """
    failure_of = probe or import_failure
    version_of = version_of or installed_version
    run_pip = pip_runner or _run_pip

    missing = failure_of(requirement.module)
    if missing is None:
        return _verified(requirement, version_of)
    logger.info(
        "%s is not importable (%s); installing %s",
        requirement.label,
        missing,
        ", ".join(requirement.packages),
    )

    try:
        completed = run_pip(requirement.packages)
    except (subprocess.SubprocessError, OSError) as exc:
        logger.error("Installing %s failed: %s", requirement.label, exc)
        return InstallOutcome(
            False,
            f"{requirement.label} could not be installed: {exc}",
            detail=str(exc),
        )

    output = (completed.stdout or "") + (completed.stderr or "")
    detail = _tail(output)
    if completed.returncode != 0:
        logger.error(
            "pip install %s exited with %s", requirement.label, completed.returncode
        )
        return InstallOutcome(
            False,
            f"{requirement.label} could not be installed (pip exited with code "
            f"{completed.returncode}). Check the internet connection and try again.",
            detail=detail,
        )

    still_missing = failure_of(requirement.module)
    if still_missing is not None:
        logger.error(
            "%s installed but still not importable: %s",
            requirement.label,
            still_missing,
        )
        return InstallOutcome(
            False,
            f"{requirement.label} was installed, but it still cannot be loaded "
            f"({still_missing}).",
            detail=detail,
        )

    logger.info("Installed %s", requirement.label)
    return _verified(requirement, version_of, detail=detail)


def _verified(
    requirement: Requirement,
    version_of: Callable[[str], str | None],
    *,
    detail: str = "",
) -> InstallOutcome:
    """Return the success/failure outcome once the import is known to work.

    The distribution is assumed to share its name with the first pip
    requirement, which holds for demucs and pyrnnoise.
    """
    version = version_of(requirement.packages[0])
    if not meets_floor(version, requirement.minimum_version):
        return InstallOutcome(
            False,
            f"{requirement.label} {version} is installed but version "
            f"{requirement.minimum_version} or newer is required.",
            detail=detail,
        )
    if version:
        return InstallOutcome(
            True, f"{requirement.label} {version} is ready.", detail=detail
        )
    return InstallOutcome(True, f"{requirement.label} is ready.", detail=detail)
