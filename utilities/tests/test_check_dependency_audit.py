"""Tests for ``utilities/check_dependency_audit.py`` (R-11).

The checker is now the verdict CI blocks on, so these tests are about the
*decisions* rather than the printed lines: an unlisted advisory fails, an
allowlisted and unexpired one passes, an expired or stale entry fails, and any
input that cannot produce a verdict exits ``2`` instead of ``0``. The last group
is the one that matters most - a missing, empty or malformed payload used to be
a silent pass in the probation era, and a gate that cannot compute its verdict
must never read as green.

The real-world demonstration (a genuinely new advisory failing the build) cannot
be manufactured here, so it is proved over synthetic payloads shaped like
pip-audit's ``-f json`` output and named as such in the plan's record.

Changed in 2.1.6: initial version (R-11,
PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import check_dependency_audit as checker  # noqa: E402

#: An expiry safely in the past and one safely in the future, so the tests do
#: not need to control the clock.
EXPIRED = "2000-01-01"
FUTURE = "2999-12-31"

ADVISORY = "GHSA-1234-5678-9abc"


def _payload(tmp_path: Path, dependencies: object) -> Path:
    """Write a pip-audit-shaped payload and return its path."""
    path = tmp_path / "pip-audit.json"
    path.write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")
    return path


def _allowlist(tmp_path: Path, entries: Sequence[dict[str, str]] = ()) -> Path:
    """Write an allowlist holding *entries* and return its path."""
    parts = ["# synthetic allowlist; the schema lives in the real file", ""]
    for entry in entries:
        parts.append("[[advisory]]")
        for key, value in entry.items():
            parts.append(f'{key} = "{value}"')
        parts.append("")
    path = tmp_path / "allowlist.toml"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def _advisory(
    package: str = "urllib3",
    version: str = "2.7.0",
    advisory: str = ADVISORY,
) -> list[dict[str, object]]:
    """Return a dependency list carrying one advisory."""
    return [{"name": package, "version": version, "vulns": [{"id": advisory}]}]


def _clean(name: str = "pydub", version: str = "0.25.1") -> dict[str, object]:
    """Return a dependency with nothing reported against it."""
    return {"name": name, "version": version, "vulns": []}


def _entry(**overrides: str) -> dict[str, str]:
    """Return a complete allowlist entry, with *overrides* applied."""
    entry = {
        "id": ADVISORY,
        "package": "urllib3",
        "reason": "the fix needs a coordinated upgrade",
        "expires": FUTURE,
    }
    entry.update(overrides)
    return entry


def _run(tmp_path: Path, payload: Path, entries: Sequence[dict[str, str]] = ()) -> int:
    """Run the checker's CLI over *payload* and *entries*."""
    return checker.main(
        ["--payload", str(payload), "--allowlist", str(_allowlist(tmp_path, entries))]
    )


class TestTheVerdict:
    """A finding fails unless the allowlist accepts it."""

    def test_a_clean_audit_passes(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, [_clean()])

        assert _run(tmp_path, payload) == checker.EXIT_PASS

    def test_an_unlisted_advisory_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = _payload(tmp_path, _advisory())

        assert _run(tmp_path, payload) == checker.EXIT_FINDINGS
        assert "no allowlist entry" in capsys.readouterr().err

    def test_a_listed_unexpired_advisory_passes(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, _advisory())

        assert _run(tmp_path, payload, [_entry()]) == checker.EXIT_PASS

    def test_an_expired_entry_fails_and_names_the_date(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = _payload(tmp_path, _advisory())

        assert _run(tmp_path, payload, [_entry(expires=EXPIRED)]) == (
            checker.EXIT_FINDINGS
        )
        errors = capsys.readouterr().err
        assert "expired on 2000-01-01" in errors, errors

    def test_an_entry_no_longer_reported_is_stale(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = _payload(tmp_path, [_clean()])

        assert _run(tmp_path, payload, [_entry()]) == checker.EXIT_FINDINGS
        assert "stale" in capsys.readouterr().err

    def test_an_entry_naming_another_package_fails(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, _advisory())

        assert _run(tmp_path, payload, [_entry(package="requests")]) == (
            checker.EXIT_FINDINGS
        )

    def test_a_missing_vulns_key_is_clean(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, [{"name": "pydub", "version": "0.25.1"}])

        assert _run(tmp_path, payload) == checker.EXIT_PASS

    def test_a_bare_list_payload_is_accepted(self, tmp_path: Path) -> None:
        path = tmp_path / "pip-audit.json"
        path.write_text(json.dumps([_clean()]), encoding="utf-8")

        assert _run(tmp_path, path) == checker.EXIT_PASS


class TestUnusableInputNeverPasses:
    """No computable verdict is exit 2, never a pass."""

    def test_a_missing_payload_file_fails(self, tmp_path: Path) -> None:
        assert _run(tmp_path, tmp_path / "absent.json") == checker.EXIT_UNUSABLE

    def test_unparsable_payload_fails(self, tmp_path: Path) -> None:
        path = tmp_path / "pip-audit.json"
        path.write_text("this is not json", encoding="utf-8")

        assert _run(tmp_path, path) == checker.EXIT_UNUSABLE

    def test_an_empty_payload_fails(self, tmp_path: Path) -> None:
        """An audit that covered nothing is not a clean audit."""
        payload = _payload(tmp_path, [])

        assert _run(tmp_path, payload) == checker.EXIT_UNUSABLE

    @pytest.mark.parametrize(
        "payload_json",
        ["{}", '{"dependencies": {}}', "42", '{"dependencies": [{"name": "x"}]}'],
    )
    def test_an_unexpected_shape_fails(self, tmp_path: Path, payload_json: str) -> None:
        path = tmp_path / "pip-audit.json"
        path.write_text(payload_json, encoding="utf-8")

        assert _run(tmp_path, path) == checker.EXIT_UNUSABLE

    def test_a_missing_allowlist_fails(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, [_clean()])

        code = checker.main(
            ["--payload", str(payload), "--allowlist", str(tmp_path / "absent.toml")]
        )

        assert code == checker.EXIT_UNUSABLE

    @pytest.mark.parametrize("missing_key", checker.REQUIRED_ENTRY_KEYS)
    def test_an_incomplete_entry_fails(self, tmp_path: Path, missing_key: str) -> None:
        payload = _payload(tmp_path, [_clean()])
        entry = _entry()
        del entry[missing_key]

        assert _run(tmp_path, payload, [entry]) == checker.EXIT_UNUSABLE

    def test_an_unparsable_expiry_fails(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, [_clean()])

        assert _run(tmp_path, payload, [_entry(expires="31/12/2026")]) == (
            checker.EXIT_UNUSABLE
        )


class TestTheExpiryBoundary:
    """An entry is valid *on* its expiry date and expired the day after."""

    def test_the_expiry_date_itself_still_accepts(self) -> None:
        findings = [checker.Finding("urllib3", "2.7.0", ADVISORY)]
        entries = [
            checker.AllowEntry(ADVISORY, "urllib3", "reason", date(2026, 12, 31))
        ]

        failures, _ = checker.evaluate(findings, entries, date(2026, 12, 31))

        assert failures == []

    def test_the_day_after_expiry_fails(self) -> None:
        expiry = date(2026, 12, 31)
        findings = [checker.Finding("urllib3", "2.7.0", ADVISORY)]
        entries = [checker.AllowEntry(ADVISORY, "urllib3", "reason", expiry)]

        failures, _ = checker.evaluate(findings, entries, expiry + timedelta(days=1))

        assert failures and "expired on 2026-12-31" in failures[0]
