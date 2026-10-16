"""Committed records for external files this repository depends on but cannot version.

The suite makes claims about files that live outside the repository and are not
versioned with it.  Today that is one family - the user-global instruction file
``AGENTS.md`` defers to for precedence, plus the harness twin that shares its
bytes - but the shape is general, and this module is the general shape.

A CI runner has no copy of such a file, so three things that should be
enforceable are not: the claims themselves, the checks that read the live file,
and the code paths those checks are made of.  A *record* fixes that.  One JSON
file per external file, committed under ``tests/data/external/``, captures what
the repository asserts about it:

* where it lives, as a path template so it is portable, and its twin when the
  repository claims the two paths are one file;
* the provenance of the recorded bytes (SHA-256 and size) - evidence, and
  deliberately not a gate, because any ordinary edit to the external file would
  otherwise turn a deliberate re-record into a red suite.  A drift failure
  quotes both sides instead;
* the headings it carries, per level, and the literal markers the repository's
  claims rest on.  Those two are the contract.

``materialize`` turns a record back into a file that carries every recorded
heading and marker, which is what makes the live-file checks run *everywhere*:
on a host that has the external file they read it and detect real drift; on a
runner that has none they read the fixture instead, so the same code paths
execute and can still fail.  ``under_test`` chooses, and reports which source
it used through ``origin``, so a failure never leaves that ambiguous.

What a fixture cannot prove is that the *real* file is unmodified - it is built
from the same record the checks compare against.  A change to the record is
therefore a change to the contract and has to be caught in review, exactly like
a frozen rule inventory.

Adding another external file is: record it (``build_record`` / ``write_record``,
with ``re_record_command`` producing the documented one-liner), then lock it with
``under_test`` in that file's test module.  ``record_paths`` and the locks in
``tests/test_external_records.py`` keep the directory honest, so a record cannot
be committed and never checked.

Changed in 1.1.0: initial version, extracted from ``tests/test_agents_md.py``
with the AGENTS.md audit.
Changed in 1.2.0: generalized for any external file - generic record schema
(per-level headings, markers, owner-defined extras), a loader that refuses a
record weaker than it claims to be, and the ``tests/data/external/``
convention.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: One record per external file, so the directory itself is the inventory.
RECORDS_DIR = REPO_ROOT / "tests" / "data" / "external"

#: Heading levels ``build_record`` records unless told otherwise.  Deeper
#: nesting is unusual in an instruction file, and every recorded level widens
#: the contract, so the owner opts in rather than inheriting it.
DEFAULT_LEVELS: tuple[int, ...] = (2, 3)

#: Path tokens a record may use, expanded against the host that reads it.
#: ``%USERPROFILE%`` is how the repository already cites the user-global file.
_TEMPLATE_TOKENS: tuple[tuple[str, str], ...] = (("%USERPROFILE%", "~"),)

#: Every top-level key a record may carry.  An unknown key is a typo or a
#: record left behind by an older schema, and both would silently weaken the
#: checks that read it, so the loader refuses them.
_KNOWN_KEYS = frozenset(
    {
        "_comment",
        "_recorded",
        "_source",
        "_twin",
        "provenance",
        "headings",
        "markers",
        "extra",
    }
)

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_LEVEL = re.compile(r"[1-9][0-9]*\Z")


class ExternalRecordError(Exception):
    """A record is missing, unreadable, or weaker than it claims to be.

    Raised rather than warned: a record that quietly parses to something less
    than it says turns every check built on it into a check that cannot fail.
    """


@dataclass(frozen=True)
class ExternalRecord:
    """One committed record of one external file (see the module docstring).

    Attributes:
        path: The record JSON itself - named in messages, so a failure says
            which record to re-record.
        source_template: The external file's portable path.
        twin_template: The portable twin path, or ``None``.
        comment: The record's own explanation of why it exists.
        recorded: ISO date of the deliberate re-record that produced it.
        sha256: SHA-256 of the recorded bytes (evidence, not a gate).
        size: Byte length of the recorded bytes.
        headings: Recorded heading texts per level, in file order.  A record
            may leave this empty and state only markers.
        markers: Literal strings the repository's claims rest on.  A record may
            state no markers and only headings.
        extra: Owner-defined fields (for example the name of the rule that owns
            a verdict).  This module stores them without interpreting them.
    """

    path: Path
    source_template: str
    twin_template: str | None
    comment: str
    recorded: str
    sha256: str
    size: int
    headings: Mapping[int, tuple[str, ...]]
    markers: tuple[str, ...]
    extra: Mapping[str, Any]

    @property
    def name(self) -> str:
        """The record's file name, for failure messages."""
        return self.path.name

    @property
    def source(self) -> Path:
        """The external file's live path on this host."""
        return resolve_template(self.source_template)

    @property
    def twin(self) -> Path | None:
        """The live twin path, when the record names one."""
        if self.twin_template is None:
            return None
        return resolve_template(self.twin_template)


@dataclass(frozen=True)
class ExternalUnderTest:
    """The external file a lock reads, and where that file came from.

    ``synthetic`` separates the two sources so a failure can say whether it saw
    the real external file - the only case in which the finding is real drift -
    or a fixture materialized from the record, in which case the finding means
    the checks or the materialization are broken.
    """

    record: ExternalRecord
    live: Path
    text: str
    twin: Path | None
    synthetic: bool

    @property
    def origin(self) -> str:
        """Describe the source, for failure messages."""
        if self.synthetic:
            return f"a fixture materialized from {self.record.name}"
        return "the real file"


def resolve_template(template: str) -> Path:
    """Expand a record's path template against the host reading it.

    Args:
        template: A stored path, optionally using ``%USERPROFILE%``.

    Returns:
        The live path.  An unrecognised token is left verbatim rather than
        silently guessed at, so a record written for another host fails
        visibly instead of resolving to somewhere plausible.
    """
    expanded = template
    for token, replacement in _TEMPLATE_TOKENS:
        expanded = expanded.replace(token, str(Path(replacement).expanduser()))
    return Path(expanded)


def headings_at(text: str, level: int) -> list[str]:
    """Return the heading texts at ``level`` (``## `` is 2), in file order."""
    prefix = "#" * level + " "
    return [
        line.strip()[len(prefix) :].strip()
        for line in text.splitlines()
        if line.strip().startswith(prefix)
    ]


def _require(condition: bool, path: Path, problem: str) -> None:
    """Raise ``ExternalRecordError`` naming ``path`` when ``condition`` is false."""
    if not condition:
        raise ExternalRecordError(f"{path}: {problem}")


def load_record(path: Path) -> ExternalRecord:
    """Read and validate one committed record.

    Validation lives here rather than in each consumer so a malformed record
    fails once, loudly and by name, instead of weakening several checks at once.

    Args:
        path: The record JSON.

    Returns:
        The record, with heading levels as ``int`` keys.

    Raises:
        ExternalRecordError: if the file is absent or unreadable, or is missing
            or mis-stating any field the checks read.
    """
    if not path.is_file():
        raise ExternalRecordError(f"{path}: no such record")
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExternalRecordError(f"{path}: unreadable record ({exc})") from exc
    _require(isinstance(data, dict), path, "record must be a JSON object")

    unknown = sorted(set(data) - _KNOWN_KEYS)
    _require(
        not unknown,
        path,
        f"unknown key(s) {unknown}; known keys are {sorted(_KNOWN_KEYS)}",
    )

    comment = data.get("_comment")
    _require(
        isinstance(comment, str) and bool(comment.strip()),
        path,
        "_comment must say why the record exists",
    )
    recorded = data.get("_recorded")
    _require(
        isinstance(recorded, str) and _ISO_DATE.fullmatch(recorded) is not None,
        path,
        "_recorded must be an ISO date (YYYY-MM-DD)",
    )
    source = data.get("_source")
    _require(
        isinstance(source, str) and bool(source.strip()),
        path,
        "_source must be a non-empty path template",
    )
    twin = data.get("_twin")
    _require(
        twin is None or (isinstance(twin, str) and bool(twin.strip())),
        path,
        "_twin must be a path template or null",
    )

    provenance = data.get("provenance")
    _require(isinstance(provenance, dict), path, "provenance must be an object")
    digest = provenance.get("sha256")
    size = provenance.get("bytes")
    _require(
        isinstance(digest, str) and _HASH.fullmatch(digest) is not None,
        path,
        "provenance.sha256 must be 64 lowercase hex characters",
    )
    _require(
        isinstance(size, int) and not isinstance(size, bool) and size > 0,
        path,
        "provenance.bytes must be a positive integer",
    )

    raw_headings = data.get("headings", {})
    _require(
        isinstance(raw_headings, dict),
        path,
        "headings must be an object keyed by level",
    )
    headings: dict[int, tuple[str, ...]] = {}
    for key, texts in raw_headings.items():
        _require(
            isinstance(key, str) and _LEVEL.fullmatch(key) is not None,
            path,
            f"heading level {key!r} is not a positive integer",
        )
        _require(
            isinstance(texts, list) and bool(texts),
            path,
            f"level {key} records no headings - omit the level instead",
        )
        for text in texts:
            _require(
                isinstance(text, str) and bool(text.strip()),
                path,
                f"level {key} records an empty heading",
            )
        headings[int(key)] = tuple(texts)

    raw_markers = data.get("markers", [])
    _require(isinstance(raw_markers, list), path, "markers must be a list")
    for marker in raw_markers:
        _require(
            isinstance(marker, str) and bool(marker.strip()),
            path,
            "markers must be non-empty strings",
        )
    markers = tuple(raw_markers)

    _require(
        bool(headings) or bool(markers),
        path,
        "record claims nothing: it has no headings and no markers",
    )
    extra = data.get("extra", {})
    _require(isinstance(extra, dict), path, "extra must be an object")

    return ExternalRecord(
        path=path,
        source_template=source,
        twin_template=twin,
        comment=comment,
        recorded=recorded,
        sha256=digest,
        size=size,
        headings=headings,
        markers=markers,
        extra=extra,
    )


def record_paths(directory: Path | None = None) -> list[Path]:
    """Return every committed record in ``directory``, sorted.

    Args:
        directory: Where to look; defaults to ``RECORDS_DIR``.

    Returns:
        The record paths.

    Raises:
        ExternalRecordError: if there are none - every lock built on the
            directory would otherwise pass over an empty set instead of
            failing loudly (the repository's non-vacuity rule).
    """
    root = RECORDS_DIR if directory is None else directory
    paths = sorted(root.glob("*.json")) if root.is_dir() else []
    if not paths:
        raise ExternalRecordError(f"{root}: no external-file records found")
    return paths


def missing_headings(record: ExternalRecord, text: str) -> list[str]:
    """Return the recorded headings ``text`` no longer carries.

    Levels are kept apart: a heading recorded as a level-2 section must still
    be one, so a demotion or promotion is drift rather than a reworded heading.
    """
    missing: list[str] = []
    for level in sorted(record.headings):
        present = set(headings_at(text, level))
        missing += [head for head in record.headings[level] if head not in present]
    return missing


def missing_markers(record: ExternalRecord, text: str) -> list[str]:
    """Return the recorded markers absent from flattened ``text``.

    Flattening keeps the check rewrapping-tolerant: a reflowed sentence must
    not fail the lock, while a dropped marker must.
    """
    flat = " ".join(text.split())
    return [marker for marker in record.markers if marker not in flat]


def twin_matches(twin: Path, raw: bytes) -> bool:
    """Return whether ``twin`` still holds the source's exact bytes."""
    return twin.read_bytes() == raw


def materialize(record: ExternalRecord, *, preamble: str = "") -> str:
    """Return a file body carrying every recorded heading and marker.

    The external file is not versioned here, so without this the live-file
    checks could only skip on a runner that lacks it and their code paths -
    heading parsing, marker scanning, the re-record round trip - would never
    execute off a developer host.  Levels are written in ascending order and
    the headings within a level in recorded order, so re-recording from the
    result reproduces the record's heading sets exactly.

    This is a fixture, not a copy: it proves the checks are well-formed and can
    fail, never that the real file is unmodified.

    Args:
        record: The record to build from.
        preamble: An optional sentence lead-in naming what the markers belong
            to.  It must not put a ``#`` at the start of a line, or it would
            add a heading the record never claimed.

    Returns:
        The file body, newline-separated.
    """
    lead = f"{preamble.strip()} " if preamble.strip() else ""
    body = [
        f"# {record.source.name} - materialized fixture",
        "",
        f"Materialized from {record.name}: this host has no copy of the "
        "external file. It carries every recorded heading and marker so the "
        "checks that read it run here, and can fail.",
        "",
    ]
    if record.markers:
        body += [f"{lead}{' / '.join(record.markers)}.", ""]
    for level in sorted(record.headings):
        body += [f"{'#' * level} {head}" for head in record.headings[level]]
        body += [""]
    return "\n".join(body)


def build_record(
    source: Path,
    *,
    record_path: Path,
    source_template: str,
    twin_template: str | None,
    comment: str,
    markers: Sequence[str] = (),
    extra: Mapping[str, Any] | None = None,
    levels: Sequence[int] = DEFAULT_LEVELS,
) -> ExternalRecord:
    """Build a record from the external file as it stands right now.

    Every marker is checked against ``source`` before it is recorded: recording
    one the file does not carry would make the record claim something false,
    and the live check reading it could then never pass on the real file.

    Args:
        source: The external file to record.
        record_path: Where the record is (or will be) committed, so the object
            and the materialized body can name it.
        source_template: The portable path to store (see ``resolve_template``).
        twin_template: The portable twin path, or ``None``.
        comment: The record's own explanation of why it exists.
        markers: Literal strings the repository's claims rest on.
        extra: Owner-defined fields, stored without interpretation.
        levels: Heading levels to record; a level with no headings is omitted.

    Returns:
        The record.  Nothing is written - pass it to ``write_record``.

    Raises:
        ExternalRecordError: if ``source`` cannot be read, or does not carry
            one of ``markers``.
    """
    try:
        raw = source.read_bytes()
    except OSError as exc:
        raise ExternalRecordError(
            f"{source}: cannot read the external file ({exc})"
        ) from exc
    text = raw.decode("utf-8")
    flat = " ".join(text.split())
    absent = [marker for marker in markers if marker not in flat]
    if absent:
        raise ExternalRecordError(
            f"{source}: cannot record markers the file does not carry:\n  "
            + "\n  ".join(absent)
        )
    found = {
        level: tuple(headings_at(text, level))
        for level in sorted(set(levels))
        if headings_at(text, level)
    }
    return ExternalRecord(
        path=record_path,
        source_template=source_template,
        twin_template=twin_template,
        comment=comment,
        recorded=date.today().isoformat(),
        sha256=hashlib.sha256(raw).hexdigest(),
        size=len(raw),
        headings=found,
        markers=tuple(markers),
        extra=dict(extra) if extra else {},
    )


def serialize_record(record: ExternalRecord) -> bytes:
    """Return ``record`` as JSON bytes: UTF-8, no BOM, CRLF, trailing newline.

    One shape for every record in the directory, written here so a Windows
    editor cannot quietly flip a record's line endings - a flip turns a
    one-line re-record into a whole-file rewrite.
    """
    data: dict[str, Any] = {
        "_comment": record.comment,
        "_recorded": record.recorded,
        "_source": record.source_template,
        "_twin": record.twin_template,
        "provenance": {"sha256": record.sha256, "bytes": record.size},
        "headings": {
            str(level): list(record.headings[level])
            for level in sorted(record.headings)
        },
        "markers": list(record.markers),
    }
    if record.extra:
        data["extra"] = dict(record.extra)
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def write_record(record: ExternalRecord, target: Path | None = None) -> bytes:
    """Write ``record`` as committed JSON and return the bytes written.

    Args:
        record: The record to serialize.
        target: Where to write; defaults to ``record.path``.

    Returns:
        The exact bytes written, so a caller can assert on them.
    """
    destination = record.path if target is None else target
    payload = serialize_record(record)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return payload


def re_record_command(module: str, constant: str, function: str) -> str:
    """Return the documented one-liner that regenerates one record.

    Re-recording is deliberate, never automatic: a recorded heading or marker
    that disappears without a re-record is drift, which is the point of the
    record.

    Args:
        module: The test module that owns the contract.
        constant: That module's name for the record path.
        function: That module's function that rebuilds and writes the record.
    """
    return (
        f'python -c "from {module} import {constant}, {function}; '
        f'{function}({constant})"'
    )


def under_test(
    record: ExternalRecord,
    *,
    tmp_path_factory: pytest.TempPathFactory,
    preamble: str = "",
) -> ExternalUnderTest:
    """Return the external file to test: the real one, or a materialized fixture.

    On a developer host the real file is served, so the checks detect real
    drift.  On a host without one - every CI runner - a file is written from the
    record into a temporary directory, twin included, so the same checks execute
    there rather than skipping; ``origin`` reports which was served.

    The twin beside a fixture is a hardlink for the same reason a record usually
    calls the pair one, so the comparison runs for real - only the drift it can
    catch is narrower, since a synthetic twin cannot disagree with its source
    until something here is broken.

    Args:
        record: The record describing the external file.
        tmp_path_factory: pytest's factory, for the fixture's directory.
        preamble: Passed to ``materialize`` for the synthetic body.
    """
    if record.source.is_file():
        twin = record.twin
        return ExternalUnderTest(
            record=record,
            live=record.source,
            text=record.source.read_text(encoding="utf-8"),
            twin=twin if twin is not None and twin.is_file() else None,
            synthetic=False,
        )

    root = tmp_path_factory.mktemp(record.path.stem)
    live = root / record.source.name
    live.write_text(materialize(record, preamble=preamble), encoding="utf-8")
    twin: Path | None = None
    recorded_twin = record.twin
    if recorded_twin is not None:
        twin = root / recorded_twin.parent.name / recorded_twin.name
        twin.parent.mkdir(parents=True)
        try:
            os.link(live, twin)
        except OSError:
            # Some volumes refuse a hardlink; the check compares bytes, so a
            # copy of the same bytes exercises it just the same.
            twin.write_bytes(live.read_bytes())
    return ExternalUnderTest(
        record=record,
        live=live,
        text=live.read_text(encoding="utf-8"),
        twin=twin,
        synthetic=True,
    )
