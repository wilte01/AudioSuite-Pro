"""check_dependency_audit.py — turn pip-audit's JSON into this project's verdict.

``pip-audit`` exits 1 when it finds anything, which cannot express this project's
policy: an advisory that cannot be upgraded away yet is *accepted* for a bounded
time, with a reason and an expiry date, and everything else fails the build.
This script is that policy.  It reads pip-audit's ``-f json`` payload and the
committed allowlist, prints one line per finding, and returns:

* ``0`` — every finding is allowlisted and unexpired;
* ``1`` — a finding has no entry, an entry has expired, an entry is stale (its
  advisory is no longer reported), or an entry names a different package than
  the one the advisory is reported against;
* ``2`` — the audit or its configuration is unusable: a missing or unparsable
  payload, a payload that audited nothing, or a malformed allowlist.  A verdict
  that cannot be computed must never read as a pass.

The allowlist is the **only** suppression.  The workflows never pass
``--ignore-vuln``, so the raw advisory always reaches the log; keeping one place
where an acceptance can live is the difference between a reviewed exception and
a permanent blind spot.

Usage::

    uv export --frozen --all-extras --no-emit-project \\
        --format requirements-txt --no-hashes -o requirements-audit.txt
    uvx pip-audit -r requirements-audit.txt --no-deps -f json -o pip-audit.json
    python utilities/check_dependency_audit.py --payload pip-audit.json

Changed in 2.1.6: initial version (R-11, PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Sequence

#: Everything passed: no finding, or every finding allowlisted and unexpired.
EXIT_PASS = 0

#: The policy found something: an unlisted or expired finding, or a stale entry.
EXIT_FINDINGS = 1

#: No verdict could be computed.  Never mistaken for a pass.
EXIT_UNUSABLE = 2

#: The committed allowlist, relative to this script's own location so a caller
#: cannot point the gate at a different file by accident.
DEFAULT_ALLOWLIST = (
    Path(__file__).resolve().parent.parent / "security" / "pip_audit_allowlist.toml"
)

#: Keys every allowlist entry must carry.  ``expires`` is what makes an entry
#: age visibly instead of becoming a permanent suppression.
REQUIRED_ENTRY_KEYS = ("id", "package", "reason", "expires")


class PayloadError(ValueError):
    """pip-audit's payload is missing, unparsable or shaped unexpectedly."""


class AllowlistError(ValueError):
    """The allowlist is missing, unparsable or an entry is incomplete."""


@dataclass(frozen=True)
class Finding:
    """One advisory reported against one resolved package."""

    package: str
    version: str
    advisory: str


@dataclass(frozen=True)
class AllowEntry:
    """One accepted advisory, with the date its acceptance runs out."""

    advisory: str
    package: str
    reason: str
    expires: date


def _parse_dependencies(raw: Any, source: Path) -> list[Finding]:
    """Return every advisory in a parsed payload, or raise :class:`PayloadError`.

    Args:
        raw: The payload as :func:`json.loads` returned it.
        source: The path it came from, named in any error.

    Returns:
        One :class:`Finding` per advisory; empty only if the payload reported
        dependencies with no advisories at all.

    Raises:
        PayloadError: the payload is not an object with a ``dependencies`` list
            (or a bare list of them), a dependency is not an object with a
            string ``name``/``version``, a ``vulns`` entry is not an object with
            a non-empty string ``id``, or the audit covered no dependency.
    """
    if isinstance(raw, dict):
        dependencies = raw.get("dependencies")
    elif isinstance(raw, list):
        dependencies = raw
    else:
        raise PayloadError(
            f"{source}: expected an object with a 'dependencies' list, "
            f"got {type(raw).__name__}"
        )
    if not isinstance(dependencies, list) or not dependencies:
        raise PayloadError(
            f"{source}: no dependencies were audited - an empty payload is not "
            "a clean audit"
        )

    findings: list[Finding] = []
    for index, dependency in enumerate(dependencies):
        if not isinstance(dependency, dict):
            raise PayloadError(f"{source}: dependencies[{index}] is not an object")
        name = dependency.get("name")
        version = dependency.get("version")
        if not isinstance(name, str) or not name:
            raise PayloadError(f"{source}: dependencies[{index}] has no name")
        if not isinstance(version, str) or not version:
            raise PayloadError(
                f"{source}: dependencies[{index}] ({name}) has no version"
            )
        vulns = dependency.get("vulns", [])
        if not isinstance(vulns, list):
            raise PayloadError(
                f"{source}: dependencies[{index}] ({name}) has a non-list 'vulns'"
            )
        for vuln in vulns:
            if not isinstance(vuln, dict):
                raise PayloadError(f"{source}: an advisory on {name} is not an object")
            advisory = vuln.get("id")
            if not isinstance(advisory, str) or not advisory:
                raise PayloadError(f"{source}: an advisory on {name} has no id")
            findings.append(Finding(package=name, version=version, advisory=advisory))
    return findings


def load_payload(path: Path) -> list[Finding]:
    """Read a pip-audit JSON payload and return its advisories.

    Args:
        path: The ``-o`` file pip-audit wrote.

    Returns:
        Every advisory the payload reports.

    Raises:
        PayloadError: the file is unreadable, not JSON, or shaped unexpectedly.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PayloadError(f"cannot read {path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"{path} is not JSON: {exc}") from exc
    return _parse_dependencies(raw, path)


def load_allowlist(path: Path) -> list[AllowEntry]:
    """Read the committed allowlist.

    Args:
        path: The TOML file; ``[[advisory]]`` tables, one per accepted advisory.

    Returns:
        The parsed entries in file order; empty when nothing is accepted, which
        is the honest starting state.

    Raises:
        AllowlistError: the file is missing or unreadable, is not TOML, its
            ``advisory`` key is not a list of tables, or an entry lacks a
            non-empty ``id``/``package``/``reason``/``expires`` or carries an
            ``expires`` that is not ``YYYY-MM-DD``.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AllowlistError(f"cannot read the allowlist {path}: {exc}") from exc
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise AllowlistError(f"{path} is not valid TOML: {exc}") from exc

    tables = raw.get("advisory", [])
    if not isinstance(tables, list):
        raise AllowlistError(
            f"{path}: 'advisory' must be a list of [[advisory]] tables"
        )

    entries: list[AllowEntry] = []
    for index, table in enumerate(tables):
        if not isinstance(table, dict):
            raise AllowlistError(f"{path}: advisory[{index}] is not a table")
        values: dict[str, str] = {}
        for key in REQUIRED_ENTRY_KEYS:
            value = table.get(key)
            if not isinstance(value, str) or not value.strip():
                raise AllowlistError(
                    f"{path}: advisory[{index}] needs a non-empty {key!r} "
                    f"(required: {', '.join(REQUIRED_ENTRY_KEYS)})"
                )
            values[key] = value.strip()
        try:
            expires = date.fromisoformat(values["expires"])
        except ValueError as exc:
            raise AllowlistError(
                f"{path}: advisory[{index}] ({values['id']}) has "
                f"expires={values['expires']!r}, which is not YYYY-MM-DD"
            ) from exc
        entries.append(
            AllowEntry(
                advisory=values["id"],
                package=values["package"],
                reason=values["reason"],
                expires=expires,
            )
        )
    return entries


def evaluate(
    findings: Sequence[Finding],
    entries: Sequence[AllowEntry],
    today: date,
) -> tuple[list[str], list[str]]:
    """Apply the policy to one audit.

    Args:
        findings: Every advisory the payload reported.
        entries: The allowlist.
        today: The date expiries are compared against.

    Returns:
        ``(failures, report)``.  ``failures`` are the reasons the verdict is
        :data:`EXIT_FINDINGS`; ``report`` is one line per finding, plus one per
        stale entry, for the log.
    """
    failures: list[str] = []
    report: list[str] = []
    by_advisory = {entry.advisory: entry for entry in entries}

    for entry in entries:
        if entry.expires < today:
            failures.append(
                f"allowlist entry {entry.advisory} expired on "
                f"{entry.expires.isoformat()} - upgrade the dependency, or renew "
                "the entry with a new reason and date"
            )

    reported: set[str] = set()
    for finding in findings:
        reported.add(finding.advisory)
        accepted = by_advisory.get(finding.advisory)
        if accepted is None:
            failures.append(
                f"{finding.package} {finding.version}: {finding.advisory} has no "
                "allowlist entry - fix it, or add one with a reason and an expiry"
            )
            report.append(
                f"[FAIL] {finding.package} {finding.version} {finding.advisory}"
            )
            continue
        if accepted.package != finding.package:
            failures.append(
                f"{finding.advisory} is reported against {finding.package}, but its "
                f"allowlist entry names {accepted.package} - correct the entry"
            )
        report.append(
            f"[INFO] {finding.package} {finding.version} {finding.advisory} "
            f"allowlisted until {accepted.expires.isoformat()} ({accepted.reason})"
        )

    for entry in entries:
        if entry.advisory not in reported:
            failures.append(
                f"allowlist entry {entry.advisory} is stale - pip-audit no longer "
                "reports it, so remove the entry"
            )

    return failures, report


def main(argv: Sequence[str] | None = None) -> int:
    """Run the policy over one payload and return the exit status.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        :data:`EXIT_PASS`, :data:`EXIT_FINDINGS` or :data:`EXIT_UNUSABLE`.
    """
    parser = argparse.ArgumentParser(
        description="Apply the committed allowlist to a pip-audit JSON payload."
    )
    parser.add_argument(
        "--payload",
        type=Path,
        required=True,
        help="the file pip-audit wrote with -f json -o",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=f"accepted advisories (default: {DEFAULT_ALLOWLIST})",
    )
    args = parser.parse_args(argv)

    try:
        findings = load_payload(args.payload)
        entries = load_allowlist(args.allowlist)
    except (PayloadError, AllowlistError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_UNUSABLE

    failures, report = evaluate(findings, entries, date.today())
    for line in report:
        print(line)

    if failures:
        for failure in failures:
            print(f"[ERROR] {failure}", file=sys.stderr)
        print(
            f"[ERROR] dependency audit: {len(failures)} problem(s); the policy is "
            "in CONTRIBUTING.md (Dependency security scanning)",
            file=sys.stderr,
        )
        return EXIT_FINDINGS

    print(
        f"[OK] dependency audit: {len(findings)} advisory finding(s), all "
        f"allowlisted and unexpired; allowlist entries: {len(entries)}"
    )
    return EXIT_PASS


if __name__ == "__main__":
    sys.exit(main())
