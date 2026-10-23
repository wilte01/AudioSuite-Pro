"""doctor_cli.py — ``audiosuite doctor``: is this install mapped to the tree?

A stale editable install keeps the finder it was generated with, so a package
that exists in the checkout can still be unimportable.  ``doctor`` answers the
question directly: walk the checkout's first-party packages, resolve each one
through the *installed* import machinery, and report every package that is
missing or resolves somewhere other than this checkout.  Each broken package is
mapped back to the CLI command it takes down, through the same table
``cli_app`` registers commands from, so the report names tools rather than
files.  It also answers the question a stale install hides behind: *which interpreter
would this tool actually run in?*  The launchers re-execute themselves under
``<root>/.venv`` when one exists (``venv_bootstrap``), so the interpreter that
runs the CLI and the one a double-clicked ``.pyw`` uses can differ.  The report
names both, then probes each tool's optional extra (Demucs, RNNoise) in the
launcher's interpreter — not in this one — because that is where the tool will
import it.  A missing extra does **not** fail the check: it is an optional
engine that the first run needing it offers to install, so it is reported with
its ``uv sync --extra`` fix and left out of the exit status.

Exit status is 0 when the install is current and complete, 1 otherwise, so a
CI job or a pre-flight script can gate on it.  The text report is written for
a person to read; ``--json`` publishes the same findings against the shared CLI
schema, so the gate that decides the exit code can also be read field by field.

Changed in 1.4.0: added, with the mapping and tool-impact checks it reports.
Changed in 1.4.1: ``--json`` publishes the report as a schema-valid payload,
with the exit status still decided by ``healthy`` (PLAN D93).
Changed in 1.4.1: the package resolver moved to ``install_map`` so the CLI's
staleness warning reads the same origins as this report (PLAN D94).
Changed in 2.1.0: reports the launcher interpreter and each tool's optional
extra, probed in that interpreter.  The launchers now run from the project's
``.venv``, which is exactly the interpreter whose imports decide whether a tool
works.
"""

from __future__ import annotations

import json as _json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import click

from audio_suite_shared import optional_deps
from audio_suite_shared.cli_base import _opt_json, cli

# Re-exported: ``PackageStatus`` is doctor's public result type, and importing
# it with the redundant alias is what tells mypy it is part of this module's
# interface rather than a private import.
from audio_suite_shared.install_map import PackageStatus as PackageStatus
from audio_suite_shared.install_map import (
    checkout_packages,
    editable_install,
    resolve_package,
)
from audio_suite_shared.project_version import find_pyproject
from audio_suite_shared.runtime_check import (
    SYNC_COMMAND,
    checkout_version,
    installed_version,
)
from audio_suite_shared.venv_bootstrap import find_venv_interpreter

Resolver = Callable[[str, Path], "PackageStatus"]

#: ``(module, interpreter) -> why it cannot be imported, or None``.
ExtraProbe = Callable[..., "str | None"]


@dataclass(frozen=True)
class ExtraStatus:
    """One tool's optional engine, as found in the launcher interpreter.

    Attributes:
        tool: Manifest id of the tool that needs it (``stem_separator``).
        label: User-facing package name (``"Demucs"``).
        module: Import name that was probed (``"demucs"``).
        importable: Whether the probe imported it in the launcher interpreter.
        reason: Why the import failed, when it did.
        extra: The ``pyproject.toml`` extra that ships it, for the fix line.
    """

    tool: str
    label: str
    module: str
    importable: bool
    reason: str | None = None
    extra: str = "ml"

    @property
    def fix(self) -> str:
        """Return the command that installs this extra."""
        return f"uv sync --extra {self.extra}"


@dataclass(frozen=True)
class DoctorReport:
    """The complete result of one doctor run.

    Attributes:
        checkout_root: Repository root, or ``None`` when no ``pyproject.toml``
            is reachable (an installed wheel).
        declared: ``[project] version`` from the checkout, if readable.
        installed: Installed ``audiosuite-pro`` metadata version, if present.
        editable: Whether the distribution was installed in editable mode.
        current_interpreter: ``sys.executable`` — the process running doctor
            and the one a ``audiosuite ...`` command uses.
        launcher_interpreter: The interpreter a ``.pyw`` launcher would use:
            the project's ``.venv`` when it has one, otherwise the current one.
        launcher_from_venv: Whether ``launcher_interpreter`` is the project
            ``.venv`` rather than a fallback to the current interpreter.
        extras: One status per tool that declares an optional engine, probed in
            ``launcher_interpreter``.  A missing extra leaves ``healthy``
            untouched: it is optional and installable on first use.
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
    current_interpreter: str
    launcher_interpreter: str
    launcher_from_venv: bool
    extras: tuple[ExtraStatus, ...]
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


def interpreter_facts(root: Path | None) -> tuple[str, str, bool]:
    """Return ``(current, launcher, launcher_from_venv)`` for *root*.

    A launcher re-executes itself under ``<root>/.venv`` when that holds an
    interpreter; without one it continues in the interpreter that started it.
    The report says which of the two happened instead of assuming a venv.

    Args:
        root: The checkout root, or ``None`` when there is no checkout.
    """
    current = sys.executable
    if root is None:
        return current, current, False
    target = find_venv_interpreter(root)
    if target is None:
        return current, current, False
    return current, str(target), True


def extra_statuses(
    interpreter: str, *, probe: ExtraProbe | None = None
) -> tuple[ExtraStatus, ...]:
    """Probe every declared tool extra in *interpreter*.

    Args:
        interpreter: The interpreter the tools will run in.
        probe: ``(module, python=...)`` import check, defaulting to
            ``optional_deps.import_failure``.  Tests inject one so the report
            is not coupled to what is installed on the host.
    """
    checker = probe or optional_deps.import_failure
    statuses: list[ExtraStatus] = []
    for tool in sorted(optional_deps.TOOL_REQUIREMENTS):
        requirement = optional_deps.TOOL_REQUIREMENTS[tool]
        reason = checker(requirement.module, python=interpreter)
        statuses.append(
            ExtraStatus(
                tool=tool,
                label=requirement.label,
                module=requirement.module,
                importable=reason is None,
                reason=reason,
                extra=requirement.extra,
            )
        )
    return tuple(statuses)


def collect_report(
    resolve: Resolver | None = None, *, extras_probe: ExtraProbe | None = None
) -> DoctorReport:
    """Build the doctor report for this interpreter and checkout.

    Args:
        resolve: Package resolver, defaulting to
            ``install_map.resolve_package``.  Tests inject a resolver to
            simulate a stale finder without touching the environment.
        extras_probe: Extra-import probe, defaulting to
            ``optional_deps.import_failure``.  Tests inject one so the report
            does not depend on what the host has installed.

    Returns:
        The report.  A checkout with no discoverable packages yields a
        structural problem rather than a passing empty scan.
    """
    declared = checkout_version()
    installed = installed_version()
    editable = editable_install()
    pyproject = find_pyproject()

    if pyproject is None:
        current, launcher, from_venv = interpreter_facts(None)
        return DoctorReport(
            checkout_root=None,
            declared=declared,
            installed=installed,
            editable=editable,
            current_interpreter=current,
            launcher_interpreter=launcher,
            launcher_from_venv=from_venv,
            extras=extra_statuses(launcher, probe=extras_probe),
            packages=(),
            problems=(
                "no pyproject.toml found, so this is not a source checkout; "
                "the package mapping cannot be checked",
            ),
        )

    root = pyproject.parent
    current, launcher, from_venv = interpreter_facts(root)
    extras = extra_statuses(launcher, probe=extras_probe)
    names = checkout_packages(root)
    if not names:
        return DoctorReport(
            checkout_root=root,
            declared=declared,
            installed=installed,
            editable=editable,
            current_interpreter=current,
            launcher_interpreter=launcher,
            launcher_from_venv=from_venv,
            extras=extras,
            packages=(),
            problems=(
                f"no first-party packages found under {root}; the scan is "
                "broken (or the checkout is empty), not necessarily the install",
            ),
        )

    resolver = resolve or resolve_package
    commands = _command_map()
    packages = tuple(
        replace(resolver(name, root), commands=commands.get(name, ())) for name in names
    )
    return DoctorReport(
        checkout_root=root,
        declared=declared,
        installed=installed,
        editable=editable,
        current_interpreter=current,
        launcher_interpreter=launcher,
        launcher_from_venv=from_venv,
        extras=extras,
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

    lines.append(f"  interpreter      {report.current_interpreter}  (this process)")
    if report.launcher_from_venv:
        lines.append(
            f"  launchers        {report.launcher_interpreter}  (project .venv)"
        )
    else:
        lines.append(
            f"  launchers        {report.launcher_interpreter}  "
            "(no .venv; they continue in this interpreter)"
        )
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

    if report.extras:
        lines.append("")
        lines.append("  extras           (probed in the launcher interpreter)")
        missing_extra = False
        for extra in report.extras:
            marker = "[OK]" if extra.importable else "[MISSING]"
            detail = "importable" if extra.importable else f"-> {extra.fix}"
            lines.append(
                f"    {marker:<10}{extra.tool:<20} {extra.label} "
                f"({extra.module}) {detail}"
            )
            if extra.reason:
                lines.append(f"              {extra.reason}")
            missing_extra = missing_extra or not extra.importable
        if missing_extra:
            lines.append(
                "    An optional engine is installed by the first run that needs "
                "it, so it does not change this check's exit status."
            )

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

    The extras are reported beside the packages: they describe the interpreter
    the launchers will use (``launcher_interpreter``), while every package
    status was resolved in this process.  An extra that cannot be imported is
    published with its reason and leaves ``healthy`` alone.

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
        interpreter=report.current_interpreter,
        launcher_interpreter=report.launcher_interpreter,
        launcher_from_venv=report.launcher_from_venv,
        extras=[
            {
                "tool": extra.tool,
                "requirement": extra.label,
                "module": extra.module,
                "extra": extra.extra,
                "importable": extra.importable,
                "reason": extra.reason,
            }
            for extra in report.extras
        ],
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
    would take down.  It also names the interpreter a launcher would run under
    and whether each tool's optional extra (Demucs, RNNoise) imports there.
    Exits 1 when the install is wrong, so a pre-flight script can gate on it; a
    missing optional extra is reported but does not fail the check.

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
