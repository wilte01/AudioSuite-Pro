"""Institutional-memory lock for ``AGENTS.md``.

Four failure modes this file exists to prevent, all seen in this repository:

1. **A rule silently disappears.** A rewrite or "tidy-up" of AGENTS.md drops a
   hard-won rule and nothing notices; the rule is then re-learned as a defect.
   ``RULE_INVENTORY`` and ``SECTION_INVENTORY`` freeze the rule set and the
   section set, and the tests fail on any removal.  *Additions* are allowed
   without touching this file - only removals (and renames, which are a removal
   plus an addition) need a deliberate update here, which is the point.

2. **A cited lock does not exist.** AGENTS.md points at enforcement tests and
   plan records by name (e.g.
   ``tests/test_pyw_launchers.py::TestEveryLauncherRunsThePreflightGuard``).
   A citation to a renamed, moved or deleted file is a dangling reference that
   reads as authority - so every cited path is asserted to resolve, and every
   ``path::Class`` citation is asserted to name a class the file defines.  This
   is the class of defect found while auditing the file: it cited a "global
   AGENTS.md" that existed nowhere, and the launcher-guard rule had no lock
   behind it at all.

3. **Both instruction files claim the other's authority.** This file and the
   user-global ``AGENTS.md`` each asserted a precedence the other did not
   grant, so an agent reading both held two contradictory verdicts and no way
   to rank them.  ``TestPrecedenceDelegation`` resolves the verdict to a single
   home - the global file's ``Instruction Precedence`` rule - and fails if this
   file starts asserting one of its own again.

4. **The file this one defers to is not versioned here, so CI cannot see it.**
   ``tests/data/external/global_agents_baseline.json`` records what the
   delegation rests on - the path, the twin, the ``Instruction Precedence``
   rule, the markers that settle the verdict, and the heading set - so
   ``TestGlobalBaselineManifest`` checks the in-repo half of the contract on
   every runner.  The live-file half reads the real baseline where one exists
   and a fixture materialized from the record (see ``baseline``) where none
   does, so no check in this file is dev-only; only the twin's *drift*
   detection still needs two real paths on disk, and the fixture says so where
   it reports.  The record, its materializer and the fixture are the generic
   machinery in ``tests/external_records.py``, which any other file this
   repository cannot version can reuse the same way.

Changed in 1.1.0: initial version, added with the AGENTS.md audit.
Changed in 1.2.0: added ``TestPrecedenceDelegation``, the lock for the
2026-10-16 precedence reconciliation against the user-global file, and
``TestGlobalBaselineManifest`` with the committed baseline record that makes
the contract checkable without that file.  The live-file checks now run
against a fixture materialized from that record where no real baseline exists,
so they execute on a CI runner instead of skipping.  The record and the
machinery behind it moved to ``tests/external_records.py``, so another external
file can be locked the same way.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from tests.external_records import (
    ExternalRecord,
    ExternalUnderTest,
    build_record,
    load_record,
    materialize,
    missing_headings,
    missing_markers,
    re_record_command,
    twin_matches,
    under_test,
    write_record,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS = REPO_ROOT / "AGENTS.md"

#: Every ``- **lead-in**`` rule bullet, frozen at 35 entries.
RULE_INVENTORY: tuple[str, ...] = (
    "Legacy `§N` citations.",
    "The `PLAN_*.md` files are the decision record, not instructions.",
    "Failing tests must be resolved — never shipped.",
    "Defects are fixed when discovered — never deferred.",
    "Audio correctness is release-blocking.",
    "Trace mode flags to the write site.",
    "A verification harness that cannot fail is worse than none.",
    "A dependency's version can change which branch runs.",
    "Read the candidate's existing tests first.",
    "Timebox each candidate to ~15 minutes.",
    "Write the probe as a file, not a shell one-liner",
    "Record the disconfirming evidence.",
    'Scripted edits must pass `encoding="utf-8"` on both read and write.',
    "`ruff format` must never format Markdown.",
    "Mutagen FLAC: rebinding `.tags` never persists — mutate in place.",
    "A `str`-mixin enum renders as `Enum.MEMBER` in an f-string",
    "Logs are split by audience.",
    "Bare `mypy .` is the gate.",
    "mypy override globs `X.*` do NOT match the bare module `X`.",
    "A restrictive `__all__` needs `implicit_reexport = true`.",
    "mypy numpy `Any`-return trap.",
    "Bandit needs `-c pyproject.toml`, UTF-8, and `-x ./.venv`.",
    "Bandit B310 fires on any first-party `urllib.request.urlopen`",
    "Bare `pytest` — not `pytest tests/`.",
    "Every new package needs `__init__.py`.",
    "Pre-flight import checks need a Tk root.",
    "`compileall -x '(^|/)(\\.venv|\\.git)/'` does not exclude `.venv` on Windows",
    "A verification harness that cannot fail is worse than none",
    "Simulate platforms by patching `sys.platform` only — never `os.name`.",
    "A scan is only as good as its alternation.",
    "Signatures before casts.",
    "UI builder signatures are the source of truth.",
    "Unused scaffold must not remain.",
    "Lock deleted public APIs with an AST test.",
    "Clean up alongside deletion.",
)

#: Every ``## `` section, frozen at 20 entries.
SECTION_INVENTORY: tuple[str, ...] = (
    "Scope & Authority",
    "The Gate — run before marking anything done",
    "Repository & Version Control",
    "Plan Governance",
    "Bug-Hunt Triage Discipline",
    "Test File Naming",
    "Shared Config Pattern",
    "GUI (Tkinter) Testing",
    "Startup Pre-Flight Guard (Do Not Disable)",
    "Byte-level Safety",
    "Never Lose a Rule to a Scripted Edit",
    "Domain Correctness Traps",
    "Verification Tooling Traps",
    "Shell Quoting (PowerShell)",
    "Secret Scanning",
    "Utility Script Markers",
    "Master Driver Card Naming",
    "Registering a New Tool (Checklist)",
    "User-Guide Regeneration Diffs",
    "Refactor Safety",
)

#: A ``path.py::ClassName`` citation: the strongest form, because it names the
#: class that does the enforcing.
_CLASS_CITE = re.compile(r"`([\w.\-]+/[\w.\-/]+\.py)::([A-Za-z_]\w*)`")
#: A bare ``path/to/test_thing.py`` citation.
_PATH_CITE = re.compile(r"`([\w.\-]+/[\w.\-/]+\.py)`")
#: Root-level records the file cites by name (plans, audits).
_RECORD_CITE = re.compile(r"`((?:PLAN_|AUDIT_)[\w.\-]+\.md)`")

#: The user-global instruction file that owns the precedence verdict.  It is
#: deliberately outside this repository (several projects and harnesses share
#: it, and it is not versioned here), so a runner without one - which is every
#: CI runner - cannot read it.  The live-file checks therefore read this file
#: where it exists and a fixture materialized from the committed record where it
#: does not (see ``baseline``); none of them skips for the file's absence.
GLOBAL_AGENTS = Path.home() / ".config" / "opencode" / "AGENTS.md"

#: The committed record of that file.  CI has no baseline to read, so this is
#: what the in-repo half of the precedence contract is checked against - and
#: what the ``baseline`` fixture builds from where the file is absent.
GLOBAL_BASELINE = (
    REPO_ROOT / "tests" / "data" / "external" / "global_agents_baseline.json"
)

#: The baseline as recorded: the two hardlinked paths AGENTS.md names, the rule
#: that owns the verdict, and the markers that prove it still settles one.  These
#: are code-owned, so the record cannot be weakened by editing the JSON.
BASELINE_SOURCE = "%USERPROFILE%\\.config\\opencode\\AGENTS.md"
BASELINE_TWIN = "%USERPROFILE%\\.config\\kilo\\AGENTS.md"
BASELINE_RULE = "Instruction Precedence"
BASELINE_MARKERS: tuple[str, ...] = (
    "single home of this rule",
    "never on a cross-project rule",
)
BASELINE_COMMENT = (
    "Recorded baseline of the user-global instruction file that AGENTS.md "
    "defers to for precedence. It is not versioned with this repository, so no "
    "CI runner has a copy: this record is what the in-repo half of the contract "
    "is checked against, and where no real baseline exists the live-file checks "
    "run against one materialized from it, so it must stay complete enough to "
    "build. Regenerate it deliberately (see RECORD_COMMAND) after an intended "
    "change to the baseline, and re-run the lock - the headings and markers "
    "recorded here are the contract, so one that disappears is drift."
)

#: Sentence lead-in for the materialized fixture's marker line.  Naming the
#: rule keeps the fixture shaped like the real file's verdict sentence, so the
#: marker scan reads the same text it reads on a developer host.
BASELINE_PREAMBLE = f"The user-global baseline. Its ``{BASELINE_RULE}`` rule states"

#: The documented one-liner for a deliberate re-record, from the repo root.
RECORD_COMMAND = re_record_command(
    "tests.test_agents_md", "GLOBAL_BASELINE", "record_global_baseline"
)

#: Verdict phrases that belong to the global file's ``Instruction Precedence``
#: rule, plus the unqualified self-containment claim.  AGENTS.md may *point* at
#: the rule - it names the path and the section - but must never state one of
#: these: a competing verdict here is precisely the contradiction that made the
#: two files unrankable, and "**self-contained**" unqualified is what let this
#: file read as a replacement for the baseline rather than a supplement to it.
FORBIDDEN_VERDICTS: tuple[str, ...] = (
    "**self-contained**",
    "binding one for this repo",
    "this file wins",
    "this file is binding",
    "this file takes precedence",
    "the global file wins",
    "supersedes the global",
    "overrides the global",
    "single home of this rule",
)

#: The user-global file AGENTS.md defers to.  A block may point at the rule only
#: if it also names this file: "that file's rule" with no path in reach is a
#: dangling reference, and a dangling reference reads as authority.
GLOBAL_AGENTS_NAME = f"`{BASELINE_SOURCE}`"

#: The rule that owns the verdict; the project file points at it by this name.
VERDICT_HOME = "**Instruction Precedence** rule"


def agents_text() -> str:
    """Return AGENTS.md's source."""
    return AGENTS.read_text(encoding="utf-8")


def agents_blocks() -> list[str]:
    """Return AGENTS.md's blank-line-separated blocks, whitespace-flattened.

    Flattening keeps the checks below rewrapped-text tolerant: a legitimate
    reflow must not fail the lock, while a dropped path must.
    """
    blocks = []
    for block in re.split(r"\n\s*\n", agents_text()):
        flat = " ".join(block.split())
        if flat:
            blocks.append(flat)
    return blocks


@pytest.fixture(scope="module")
def baseline_record() -> ExternalRecord:
    """Return the committed record of the baseline the delegation rests on."""
    return load_record(GLOBAL_BASELINE)


@pytest.fixture(scope="module")
def baseline(
    baseline_record: ExternalRecord, tmp_path_factory: pytest.TempPathFactory
) -> ExternalUnderTest:
    """Return the baseline under test: the real file, or a materialized one.

    ``under_test`` serves the real user-global file on a host that has one, so
    these checks detect real drift there, and one materialized from
    ``GLOBAL_BASELINE`` - twin included - on a host that has none, which is
    every CI runner, so the same checks execute there rather than skipping.
    ``origin`` on the result says which was served, and every failure message
    quotes it, so a synthetic finding is never mistaken for real drift.
    """
    return under_test(
        baseline_record,
        tmp_path_factory=tmp_path_factory,
        preamble=BASELINE_PREAMBLE,
    )


def record_global_baseline(
    target: Path | None = None, *, source: Path = GLOBAL_AGENTS
) -> ExternalRecord:
    """Build the baseline record from ``source``, writing it when asked.

    Re-recording is deliberate, never automatic: run ``RECORD_COMMAND`` from the
    repo root after an intended change to the baseline.  A recorded heading or
    marker that disappears without a re-record is drift, which is the point.
    ``source`` is injectable so the round trip can be exercised against the
    materialized fixture on a host with no real baseline.
    """
    record = build_record(
        source,
        record_path=target if target is not None else GLOBAL_BASELINE,
        source_template=BASELINE_SOURCE,
        twin_template=BASELINE_TWIN,
        comment=BASELINE_COMMENT,
        markers=BASELINE_MARKERS,
        extra={"rule": BASELINE_RULE},
    )
    if target is not None:
        write_record(record)
    return record


class TestRuleInventory:
    """The rules themselves cannot vanish unnoticed."""

    def test_agents_md_exists_and_is_non_trivial(self) -> None:
        assert len(agents_text().splitlines()) > 200, "AGENTS.md looks truncated"

    def test_every_frozen_rule_is_still_present(self) -> None:
        """No rule may be removed or renamed without a deliberate edit here."""
        text = agents_text()
        missing = [rule for rule in RULE_INVENTORY if "**" + rule + "**" not in text]
        assert not missing, (
            "rules disappeared from AGENTS.md (update the inventory only if the "
            "removal is deliberate):\n  " + "\n  ".join(missing)
        )

    def test_every_frozen_section_is_still_present(self) -> None:
        """No whole section may be dropped."""
        text = agents_text()
        gone = [head for head in SECTION_INVENTORY if "## " + head not in text]
        assert not gone, "sections disappeared from AGENTS.md:\n  " + "\n  ".join(gone)

    def test_the_inventories_are_not_vacuous(self) -> None:
        """A parse that found nothing would pass the two tests above."""
        assert len(RULE_INVENTORY) >= 30, len(RULE_INVENTORY)
        assert len(SECTION_INVENTORY) >= 15, len(SECTION_INVENTORY)
        assert len(set(RULE_INVENTORY)) == len(RULE_INVENTORY), "duplicate rule text"


class TestCitationsResolve:
    """Every name AGENTS.md cites must exist, or it is not authority."""

    def test_cited_paths_exist(self) -> None:
        cites = _PATH_CITE.findall(agents_text())
        assert len(cites) >= 8, (
            f"only {len(cites)} path citations parsed; the scan would pass vacuously"
        )
        missing = sorted({c for c in cites if not (REPO_ROOT / c).exists()})
        assert not missing, (
            "AGENTS.md cites paths that do not exist:\n  " + "\n  ".join(missing)
        )

    def test_cited_enforcement_classes_are_defined(self) -> None:
        cites = _CLASS_CITE.findall(agents_text())
        assert cites, "no ``path::Class`` citation parsed; the lock cannot pass"
        for rel, cls in cites:
            source = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert re.search(rf"^class {cls}\b", source, re.MULTILINE), (
                f"AGENTS.md cites {rel}::{cls}, which that file does not define"
            )

    def test_cited_plan_and_audit_records_exist(self) -> None:
        cites = _RECORD_CITE.findall(agents_text())
        assert len(cites) >= 5, f"only {len(cites)} plan citations parsed"
        missing = sorted({c for c in cites if not (REPO_ROOT / c).exists()})
        assert not missing, "AGENTS.md cites missing records:\n  " + "\n  ".join(
            missing
        )


class TestPrecedenceDelegation:
    """This file points at the global verdict rule; it states no verdict.

    Reconciled 2026-10-16: the two files each asserted an authority the other
    did not grant - "where the two differ, this file is the binding one for this
    repo" against "the project file wins only on project-specific detail, never
    on a cross-project rule" - so the contradiction survived as long as nobody
    read both.  The verdict now has one home, the global file's ``Instruction
    Precedence`` rule, and this class is what keeps it there.
    """

    def test_the_project_file_states_no_competing_verdict(self) -> None:
        """A verdict here is the contradiction; pointing at the rule is not."""
        text = agents_text()
        found = [verdict for verdict in FORBIDDEN_VERDICTS if verdict in text]
        assert not found, (
            "AGENTS.md states a precedence verdict of its own; the verdict "
            "belongs to the global Instruction Precedence rule, so point at it "
            "instead of restating it:\n  " + "\n  ".join(found)
        )

    def test_the_verdict_list_cannot_pass_vacuously(self) -> None:
        assert len(FORBIDDEN_VERDICTS) >= 8, len(FORBIDDEN_VERDICTS)
        assert len(set(FORBIDDEN_VERDICTS)) == len(FORBIDDEN_VERDICTS)

    def test_the_delegation_pointer_survives(self) -> None:
        """Dropping the pointer frees the two files to contradict again."""
        text = agents_text()
        assert GLOBAL_AGENTS_NAME in text, (
            "AGENTS.md no longer names the user-global file, so the verdict it "
            "defers to has no discoverable home"
        )
        assert VERDICT_HOME in text, (
            "AGENTS.md no longer names the global Instruction Precedence rule"
        )

    def test_the_pointer_names_the_file_it_defers_to(self) -> None:
        """A reference to the rule without the path cannot be followed."""
        pointing = [b for b in agents_blocks() if VERDICT_HOME in b]
        assert pointing, (
            "no block points at the global precedence rule at all, so the "
            "check below would pass vacuously"
        )
        dangling = [b for b in pointing if GLOBAL_AGENTS_NAME not in b]
        assert not dangling, (
            "a block points at the Instruction Precedence rule without naming "
            "the user-global file it lives in, leaving 'that file' dangling:\n  "
            + "\n  ".join(dangling)
        )

    def test_the_self_contained_claim_stays_qualified(self) -> None:
        """Self-contained for repo-local rules only: the baseline still applies."""
        flat = " ".join(agents_text().split())
        assert "**self-contained for repo-local rules**" in flat, (
            "the qualified self-containment claim was renamed or dropped"
        )
        assert "It is not self-contained for cross-project rules" in flat, (
            "the file claims cross-project self-containment again, which is what "
            "made it read as a replacement for the global baseline"
        )


class TestGlobalBaselineManifest:
    """The contract AGENTS.md defers to, recorded so CI can check it.

    The user-global baseline is not versioned with this repository and no CI
    runner has a copy.  ``GLOBAL_BASELINE`` records what the delegation rests on
    - the path, the twin, the rule, the markers that settle the verdict and the
    heading set; ``tests/external_records.py`` owns the mechanism - and the
    ``baseline`` fixture serves the checks either the real file or one
    materialized from that record, so every check here runs on every host and
    none of them skips for the file's absence.  The one thing a fixture cannot
    prove is that the real baseline is unmodified; that stays a developer-host
    finding, and ``origin`` says which side a failure came from.
    """

    def test_the_record_matches_the_code_owned_contract(
        self, baseline_record: ExternalRecord
    ) -> None:
        """The static fields are owned here, so the JSON cannot weaken them."""
        assert baseline_record.source_template == BASELINE_SOURCE
        assert baseline_record.twin_template == BASELINE_TWIN
        assert baseline_record.extra["rule"] == BASELINE_RULE
        assert baseline_record.markers == BASELINE_MARKERS

    def test_the_record_is_not_trivial(self, baseline_record: ExternalRecord) -> None:
        """A record that parsed to nothing must not satisfy the checks below."""
        sections = baseline_record.headings[2]
        assert len(sections) >= 10, sections
        assert len(set(sections)) == len(sections), "duplicate section names"
        assert baseline_record.headings[3], "no subsections recorded"
        assert baseline_record.size > 1000, baseline_record.size

    def test_the_project_file_defers_to_the_recorded_baseline(
        self, baseline_record: ExternalRecord
    ) -> None:
        """The one check that still has teeth on a host with no baseline."""
        text = agents_text()
        where = GLOBAL_BASELINE.name
        assert baseline_record.source_template in text, (
            f"AGENTS.md no longer names the baseline recorded in {where}:\n  "
            f"{baseline_record.source_template}"
        )
        rule = baseline_record.extra["rule"]
        assert f"**{rule}** rule" in text, (
            f"AGENTS.md no longer points at the rule recorded in {where}"
        )

    def test_the_documented_re_record_command_is_sound(self) -> None:
        """The affordance must keep naming things that still exist."""
        assert "from tests.test_agents_md import" in RECORD_COMMAND
        assert "record_global_baseline(GLOBAL_BASELINE)" in RECORD_COMMAND

    def test_the_live_baseline_still_carries_every_recorded_heading(
        self, baseline: ExternalUnderTest
    ) -> None:
        """A recorded heading that vanished is drift, not a free edit."""
        missing = missing_headings(baseline.record, baseline.text)
        assert not missing, (
            f"{baseline.live} ({baseline.origin}) dropped headings the record "
            "claims; re-record deliberately if that was intended:\n  "
            + "\n  ".join(missing)
        )

    def test_the_live_baseline_still_resolves_the_verdict(
        self, baseline: ExternalUnderTest
    ) -> None:
        """The markers are what prove the rule still settles who wins."""
        missing = missing_markers(baseline.record, baseline.text)
        raw = baseline.live.read_bytes()
        assert not missing, (
            f"{baseline.live} ({baseline.origin}) no longer resolves the "
            "verdict AGENTS.md defers to; missing:\n  "
            + "\n  ".join(missing)
            + f"\nrecorded {baseline.record.sha256[:16]} / "
            f"{baseline.record.size} bytes, live "
            f"{hashlib.sha256(raw).hexdigest()[:16]} / {len(raw)} bytes"
        )

    def test_the_recorded_twin_is_still_the_same_file(
        self, baseline: ExternalUnderTest
    ) -> None:
        """AGENTS.md calls those two paths one hardlink; keep it honest.

        Only a host with the real baseline can catch *drift* here - the fixture
        builds its twin beside itself, so it cannot disagree with its source
        until something in this file is broken - but the comparison runs
        everywhere, and the negative control below proves it can fail.
        """
        if baseline.twin is None:
            pytest.skip(f"no twin file to compare at {baseline.record.twin}")
        raw = baseline.live.read_bytes()
        assert twin_matches(baseline.twin, raw), (
            f"{baseline.twin} and {baseline.live} ({baseline.origin}) are no "
            "longer one hardlink, which is what AGENTS.md tells a reader to "
            "expect"
        )

    def test_a_deliberate_re_record_writes_a_usable_record(
        self, tmp_path: Path, baseline: ExternalUnderTest
    ) -> None:
        """The documented re-record path must work, in UTF-8 with CRLF."""
        target = tmp_path / "global_agents_baseline.json"
        fresh = record_global_baseline(target, source=baseline.live)
        raw = target.read_bytes()
        assert raw[:3] != b"\xef\xbb\xbf", "the record must not carry a BOM"
        assert raw.count(b"\n") == raw.count(b"\r\n"), "the record must be CRLF"
        assert load_record(target) == fresh, (
            "the record written to disk does not reload as the record built for it"
        )
        assert fresh.source_template == baseline.record.source_template
        assert set(baseline.record.headings[2]) <= set(fresh.headings[2]), (
            f"the baseline at {baseline.live} ({baseline.origin}) lost sections "
            "the record claims, so either the record is stale or the baseline "
            "was trimmed - re-record deliberately"
        )

    def test_the_live_checks_notice_a_broken_baseline(self, tmp_path: Path) -> None:
        """A fixture that cannot fail would be worse than no fixture at all.

        This is the check that makes the rest of the class meaningful on a
        runner with no baseline: it materializes the record's own baseline,
        breaks one part of the contract at a time, and requires the scan that
        owns that part to report exactly what was broken.  Without it, the
        fixture would only prove the live-file checks can *pass*.
        """
        record = load_record(GLOBAL_BASELINE)
        good = materialize(record, preamble=BASELINE_PREAMBLE)
        assert not missing_headings(record, good), "the fixture is not faithful"
        assert not missing_markers(record, good), "the fixture is not faithful"
        assert not missing_headings(record, good + "\nsome added drift\n"), (
            "an added line must not read as a removed heading"
        )

        heading = record.headings[2][0]
        stripped = good.replace(f"## {heading}\n", "")
        assert stripped != good, f"the fixture never carried {heading!r}"
        assert missing_headings(record, stripped) == [heading], (
            "a dropped section heading went unnoticed"
        )

        marker = record.markers[0]
        unmarked = good.replace(marker, "")
        assert unmarked != good, f"the fixture never carried {marker!r}"
        assert missing_markers(record, unmarked) == [marker], (
            "a dropped verdict marker went unnoticed"
        )

        live = tmp_path / "AGENTS.md"
        live.write_text(good, encoding="utf-8")
        round_trip = record_global_baseline(source=live)
        assert round_trip.headings[2] == record.headings[2], (
            "the materialized fixture does not re-record to the record's own "
            "sections, so its order or heading level is wrong"
        )
        assert round_trip.headings[3] == record.headings[3], (
            "the materialized fixture does not re-record to the record's own "
            "subsections, so a subsection is being written at the wrong level"
        )

        twin = tmp_path / "kilo" / "AGENTS.md"
        twin.parent.mkdir()
        twin.write_bytes(live.read_bytes())
        assert twin_matches(twin, live.read_bytes()), (
            "an identical twin must compare equal"
        )
        twin.write_bytes(live.read_bytes() + b"drift\n")
        assert not twin_matches(twin, live.read_bytes()), (
            "a divergent twin must compare unequal, or the comparison is inert"
        )
