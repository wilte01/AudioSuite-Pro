"""doctor_cli.py — ``audiosuite doctor``: is this install mapped to the tree?

A stale editable install keeps the finder it was generated with, so a package
that exists in the checkout can still be unimportable.  ``doctor`` answers the
question directly: walk the checkout's first-party packages, resolve each one
through the *installed* import machinery, and report every package that is
missing or resolves somewhere other than this checkout.  Each broken package is
mapped back to the CLI command it takes down, through the same table
``cli_app`` registers commands from, so the report names tools rather than
files.

Exit status is 0 when the install is current and complete, 1 otherwise, so a
CI job or a pre-flight script can gate on it.  The text report is written for a
person to read; ``--json`` publishes the same findings against the shared CLI
schema, so the gate that decides the exit code can also be read field by field.

Changed in 1.4.0: added, with the mapping and tool-impact checks it reports.
Changed in 1.4.1: ``--json`` publishes the report as a schema-valid payload,
with the exit status still decided by ``healthy`` (PLAN D93).
"""

from __future__ import annotations

import importlib.metadata as metadata
import importlib.util
import json as _json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import click

from audio_suite_shared.cli_base import _opt_json, cli
from audio_suite_shared.project_version import find_pyproject
from audio_suite_shared.runtime_check import (
    DISTRIBUTION_NAME,
    SYNC_COMMAND,
    checkout_version,
    installed_version,
)

#: Directory names that never hold a first-party importable package.  Only
#: directories with an ``__init__.py`` are candidates anyway; this keeps the
#: deliberately non-package trees (``utilities``, ``user_guides``) and the
#: test package out of the report.
_NOT_PACKAGES = frozenset({"__pycache__", ".venv", ".git", "build", "dist", "tests"})

Resolver = Callable[[str, Path], "PackageStatus"]


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


@dataclass(frozen=True)
class DoctorReport:
    """The complete result of one doctor run.

    Attributes:
        checkout_root: Repository root, or ``None`` when no ``pyproject.toml``
            is reachable (an installed wheel).
        declared: ``[project] version`` from the checkout, if readable.
        installed: Installed ``audiosuite-pro`` metadata version, if present.
        editable: Whether the distribution was installed in editable mode.
        packages: One status per first-party package found in the checkout.
        problems: Structural failures (no checkout, empty scan) that are not
            per-package findings.
        unregistered: ``(tool name, command)`` pairs whose command is absent
            from the group even though the package resolved (a partially
            broken install, for example one module failing on a dependency).
    """

    checkout_root: Path | None
    declared: str | None
    installed: str | None
    editable: bool
    packages: tuple[PackageStatus, ...]
    problems: tuple[str, ...] = ()
    unregistered: tuple[tuple[str, str], ...] = ()

    @property
    def broken_packages(self) -> list[PackageStatus]:
        """Return every package that is not resolvable from this checkout."""
        return [status for status in self.packages if status.state != "ok"]

    @property
    def healthy(self) -> bool:
        """Return whether the install is current and maps every package."""
        version_ok = self.installed is not None and (
            self.declared is None or self.declared == self.installed
        )
        return (
            not self.problems
            and version_ok
            and not self.broken_packages
            and not self.unregistered
        )


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


def _resolve_package(name: str, root: Path) -> PackageStatus:
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


def _command_map() -> dict[str, tuple[str, ...]]:
    """Return ``package -> CLI commands`` from the registration table.

    Imported lazily: ``cli_app`` imports this module to register ``doctor``, so
    a module-level import would be circular.  By the time the command runs,
    ``cli_app`` has finished loading.
    """
    from audio_suite_shared.cli_app import _TOOL_CLI_MODULES

    mapping: dict[str, list[str]] = {}
    for module_name, command in _TOOL_CLI_MODULES:
        mapping.setdefault(module_name.split(".", 1)[0], []).append(command)
    return {package: tuple(commands) for package, commands in mapping.items()}


def _unregistered_commands() -> tuple[tuple[str, str], ...]:
    """Return manifest tools whose CLI command did not register.

    A package can resolve and still fail while importing its ``cli`` module
    (a missing third-party dependency, for example), which leaves the tool
    unusable without appearing in the per-package scan.

    Returns:
        ``(tool name, command)`` pairs for every manifest command missing from
        the group, sorted by command.
    """
    from audio_suite_shared.tool_plugin import get_registry

    missing = [
        (manifest.name, manifest.cli_command)
        for manifest in get_registry().all
        if manifest.cli_command and manifest.cli_command not in cli.commands
    ]
    return tuple(sorted(missing, key=lambda item: item[1]))


def _is_editable() -> bool:
    """Return whether the installed distribution is an editable install."""
    try:
        distribution = metadata.distribution(DISTRIBUTION_NAME)
    except metadata.PackageNotFoundError:
        return False
    return any("__editable__" in str(item) for item in distribution.files or [])


def collect_report(resolve: Resolver | None = None) -> DoctorReport:
    """Build the doctor report for this interpreter and checkout.

    Args:
        resolve: Package resolver, defaulting to ``_resolve_package``.  Tests
            inject a resolver to simulate a stale finder without touching the
            environment.

    Returns:
        The report.  A checkout with no discoverable packages yields a
        structural problem rather than a passing empty scan.
    """
    declared = checkout_version()
    installed = installed_version()
    editable = _is_editable()
    pyproject = find_pyproject()
    if pyproject is None:
        return DoctorReport(
            checkout_root=None,
            declared=declared,
            installed=installed,
            editable=editable,
            packages=(),
            problems=(
                "no pyproject.toml found, so this is not a source checkout; "
                "the package mapping cannot be checked",
            ),
        )

    root = pyproject.parent
    names = checkout_packages(root)
    if not names:
        return DoctorReport(
            checkout_root=root,
            declared=declared,
            installed=installed,
            editable=editable,
            packages=(),
            problems=(
                f"no first-party packages found under {root}; the scan is "
                "broken (or the checkout is empty), not necessarily the install",
            ),
        )

    resolver = resolve or _resolve_package
    commands = _command_map()
    packages = tuple(
        replace(resolver(name, root), commands=commands.get(name, ())) for name in names
    )
    return DoctorReport(
        checkout_root=root,
        declared=declared,
        installed=installed,
        editable=editable,
        packages=packages,
        unregistered=_unregistered_commands(),
    )


def render_report(report: DoctorReport) -> str:
    """Render *report* as the text a user reads.

    Args:
        report: Result of :func:`collect_report`.

    Returns:
        A multi-line report.  Healthy runs list a count and no failures;
        failures name the package, why it failed, and the command it breaks.
    """
    lines = ["AudioSuite-Pro doctor", ""]
    root = report.checkout_root or "not found (no pyproject.toml)"
    lines.append(f"  checkout         {root}")
    lines.append(f"  checkout version {report.declared or 'unknown'}")
    installed = report.installed or "not installed"
    mode = " (editable)" if report.editable else ""
    lines.append(f"  installed        {installed}{mode}")
    if report.declared and report.installed:
        if report.declared == report.installed:
            version = "OK"
        else:
            version = f"STALE - {SYNC_COMMAND}"
    else:
        version = "UNKNOWN"
    lines.append(f"  version          {version}")
    lines.append("")

    total = len(report.packages)
    if total:
        mapped = sum(1 for status in report.packages if status.state == "ok")
        lines.append(f"  packages         {mapped}/{total} resolved from this checkout")
    for problem in report.problems:
        lines.append(f"  [ERROR] {problem}")
    for status in report.broken_packages:
        if status.state == "missing":
            detail = "not importable from this install"
        else:
            detail = f"resolves outside the checkout: {status.location}"
        suffix = (
            " -> " + ", ".join(f"`audiosuite {command}`" for command in status.commands)
            if status.commands
            else ""
        )
        lines.append(f"  [{status.state.upper()}] {status.name}: {detail}{suffix}")

    lines.append("")
    broken = report.broken_packages
    if broken or report.unregistered:
        lines.append("  Tools a stale install would break:")
        named = False
        for status in broken:
            for command in status.commands:
                lines.append(f"    - `audiosuite {command}` ({status.name})")
                named = True
        for tool_name, command in report.unregistered:
            lines.append(
                f"    - `audiosuite {command}` ({tool_name}): command did not register"
            )
            named = True
        if not named:
            lines.append(
                "    - none: the broken packages back the GUI or shared code only"
            )
    else:
        lines.append("  Tools a stale install would break: none")

    if not report.healthy:
        lines.append("")
        lines.append(f"  Fix: {SYNC_COMMAND}")
        lines.append("       then run the CLI through `uv run audiosuite ...`")
    return "\n".join(lines)


def doctor_payload(report: DoctorReport, *, duration_secs: float) -> dict[str, Any]:
    """Serialise *report* as ``doctor``'s locked JSON payload.

    The packages are the run's items, so ``total``/``processed`` are their
    count and ``skipped`` is 0: a package the checkout scanned was attempted.
    ``errors`` counts the broken packages *and* any structural problem, which
    keeps it a per-item verdict while ``problems`` still carries the wording a
    person needs.  On a broken install ``succeeded`` therefore derives to 0
    rather than going negative.

    Args:
        report: Result of :func:`collect_report`.
        duration_secs: Wall-clock time the report took to build.

    Returns:
        A payload conforming to :func:`cli_schema.validate_payload`.
    """
    from audio_suite_shared.cli_schema import build_payload

    broken = report.broken_packages
    mapped = sum(1 for status in report.packages if status.state == "ok")
    return build_payload(
        "doctor",
        dry_run=False,
        total=len(report.packages),
        processed=len(report.packages),
        skipped=0,
        errors=len(broken) + len(report.problems),
        duration_secs=duration_secs,
        log_entries=[],
        healthy=report.healthy,
        checkout_version=report.declared,
        installed_version=report.installed,
        editable=report.editable,
        mapped=mapped,
        packages=[
            {
                "name": status.name,
                "status": status.state,
                "origin": status.location,
                "commands": list(status.commands),
            }
            for status in report.packages
        ],
        missing_commands=[
            {"tool": tool_name, "command": command}
            for tool_name, command in report.unregistered
        ],
        problems=list(report.problems),
    )


@cli.command("doctor")
@_opt_json
def doctor(json: bool) -> None:
    """Check that this install maps every package in this checkout.

    \b
    Reports the installed and checkout versions, how many first-party packages
    resolve from this checkout, and every CLI command a stale or broken install
    would take down.  Exits 1 when anything is wrong, so a pre-flight script can
    gate on it.

    ``--json`` publishes the same findings as a schema-valid payload; the
    human report then goes to stderr so stdout carries one document.
    """
    started = time.monotonic()
    report = collect_report()
    duration_secs = time.monotonic() - started
    if json:
        # The diagnosis is still worth reading while a script consumes the
        # document, so the text report moves to stderr instead of vanishing.
        click.echo(render_report(report), err=True)
        payload = doctor_payload(report, duration_secs=duration_secs)
        click.echo(_json.dumps(payload, indent=2))
    else:
        click.echo(render_report(report))
    if not report.healthy:
        raise SystemExit(1)
