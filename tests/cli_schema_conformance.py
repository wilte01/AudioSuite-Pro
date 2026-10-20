"""Validate the recorded CLI payloads against the committed JSON Schema.

``tests/data/cli_payloads.json`` holds one recorded payload per command, taken
from the real click commands (see :mod:`tests.cli_payloads`).  This module
checks that snapshot against ``audio_suite_shared/cli_schema.json`` - the
artifact an external consumer validates with - using a real draft 2020-12
validator, not the hand-rolled subset in ``tests/test_cli_json_schema.py``
(which exists because the suite outgrew ``jsonschema``-free validation for the
*live* drives).

Two claims, both of which can fail:

* **Coverage** — the corpus records exactly the commands the schema declares.
  A new command with no recording, or a recording for a command that no longer
  exists, is a gate failure rather than a silently narrower check.
* **Conformance** — every recorded payload validates against the committed
  document.  ``additionalProperties: false`` makes this the removal detector:
  dropping a field from a command's schema is caught here on the recorded
  bytes, because the corpus still carries the key.  A purely additive change
  leaves the corpus valid, which is correct - the key is optional.

The CI workflow runs ``python -m tests.cli_schema_conformance --check`` as its
own job, so a schema break is reported as "CLI schema conformance" instead of
being one assertion among ten thousand.  The pytest lock in
``tests/test_cli_schema_conformance.py`` makes the same claim from the suite,
and proves the check can fail by mutating a payload.

To regenerate after a deliberate schema change::

    python -m tests.cli_schema_conformance --record

Recording drives every click command, so it needs the full tool environment;
``--check`` imports no tool code and runs anywhere with ``jsonschema``.

``--export-dir DIR`` writes the validated recordings as one ``<command>.json``
file per command (spaces become dashes, so ``cue generate`` is
``cue-generate.json``).  CI's test job uploads that directory as the
``cli-payloads`` artifact, so a script author can read the real payload a
command produces without installing or running anything - and what they read is
the same bytes the gate validates.

Changed in 1.4.1: initial version, the recorded-payload gate for the CLI JSON
contract (PLAN D102).
Changed in 1.4.1: ``--export-dir`` and the ``cli-payloads`` CI artifact, so the
recordings are inspectable without a checkout (PLAN D103).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from audio_suite_shared.cli_schema import SCHEMA_VERSION, TOOL_IDS

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The committed schema document external consumers validate with.
SCHEMA_PATH = REPO_ROOT / "audio_suite_shared" / "cli_schema.json"

#: One recorded payload per command (see the module docstring).
CORPUS_PATH = REPO_ROOT / "tests" / "data" / "cli_payloads.json"

#: Keys the corpus may carry.  An unknown key is a typo or a file left by an
#: older shape, and both would silently change what the check means.
_KNOWN_KEYS = frozenset({"_comment", "_generated", "schema_version", "payloads"})

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

_COMMENT = (
    "One recorded payload per CLI command, validated against "
    "audio_suite_shared/cli_schema.json by the schema-conformance gate. "
    "Host paths appear as <run> (the scratch directory) and <repo> (the "
    "checkout), so the file is machine-independent. Do not edit by hand; run "
    "`python -m tests.cli_schema_conformance --record`."
)


class ConformanceError(Exception):
    """The corpus or the schema document is missing or malformed.

    Raised rather than warned: a file that quietly parses to something weaker
    than it claims would turn the check built on it into one that cannot fail.
    """


@dataclass(frozen=True)
class Corpus:
    """The committed recorded payloads (see the module docstring).

    Attributes:
        path: The JSON file itself, named in messages so a failure says which
            file to regenerate.
        comment: The corpus's own explanation of why it exists.
        generated: ISO date of the run that recorded the payloads.
        schema_version: The ``cli_schema`` version the payloads were recorded
            under; a mismatch means the corpus predates a breaking change.
        payloads: Command path to recorded payload.
    """

    path: Path
    comment: str
    generated: str
    schema_version: int
    payloads: Mapping[str, Mapping[str, Any]]


def _require(condition: bool, path: Path, problem: str) -> None:
    """Raise ``ConformanceError`` naming ``path`` unless ``condition`` holds."""
    if not condition:
        raise ConformanceError(f"{path}: {problem}")


def load_schema(path: Path | None = None) -> dict[str, Any]:
    """Load and self-check the committed JSON Schema document.

    Args:
        path: The document to read; defaults to ``SCHEMA_PATH``.

    Returns:
        The parsed document.

    Raises:
        ConformanceError: if the file is missing or not valid JSON, or if the
            real validator rejects the document itself - a schema a consumer's
            validator cannot load proves nothing about the payloads.
    """
    source = SCHEMA_PATH if path is None else path
    _require(source.is_file(), source, "schema document does not exist")
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConformanceError(f"{source}: not valid JSON ({exc})") from exc
    _require(isinstance(document, dict), source, "top level must be an object")
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as exc:
        raise ConformanceError(
            f"{source}: not a valid draft 2020-12 schema: {exc.message}"
        ) from exc
    return document


def load_corpus(path: Path | None = None) -> Corpus:
    """Read the corpus, refusing anything weaker than it claims to be.

    Args:
        path: The corpus to read; defaults to ``CORPUS_PATH``.

    Returns:
        The loaded corpus.

    Raises:
        ConformanceError: if the file is missing, not an object, carries an
            unknown key, lacks a valid timestamp or matching schema version,
            or holds anything but an object payload per command name.
    """
    source = CORPUS_PATH if path is None else path
    _require(source.is_file(), source, "corpus does not exist")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConformanceError(f"{source}: not valid JSON ({exc})") from exc
    _require(isinstance(payload, dict), source, "top level must be an object")

    unknown = sorted(set(payload) - _KNOWN_KEYS)
    _require(not unknown, source, f"unknown keys: {', '.join(unknown)}")

    comment = payload.get("_comment")
    _require(
        isinstance(comment, str) and bool(comment.strip()),
        source,
        "missing `_comment` explaining the file",
    )
    generated = payload.get("_generated")
    _require(
        isinstance(generated, str) and bool(_ISO_DATE.match(generated)),
        source,
        "`_generated` must be an ISO date (YYYY-MM-DD)",
    )
    version = payload.get("schema_version")
    _require(
        isinstance(version, int) and not isinstance(version, bool),
        source,
        "`schema_version` must be an integer",
    )
    _require(
        version == SCHEMA_VERSION,
        source,
        f"recorded schema_version {version} is not the current {SCHEMA_VERSION}; "
        "re-record after a breaking change",
    )

    raw_payloads = payload.get("payloads")
    _require(
        isinstance(raw_payloads, dict) and bool(raw_payloads),
        source,
        "`payloads` must be a non-empty object",
    )
    recorded: dict[str, Mapping[str, Any]] = {}
    for command, document in raw_payloads.items():
        _require(
            isinstance(command, str) and bool(command.strip()),
            source,
            f"{command!r} is not a command name",
        )
        _require(
            isinstance(document, dict) and bool(document),
            source,
            f"{command}: payload must be a non-empty object",
        )
        recorded[command] = document
    return Corpus(
        path=source,
        comment=comment,
        generated=generated,
        schema_version=version,
        payloads=recorded,
    )


def conformance_problems(
    payloads: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    *,
    expected_commands: Sequence[str] | None = None,
) -> list[str]:
    """Return every problem with *payloads* against *document* (empty is pass).

    Args:
        payloads: Command path to recorded payload.
        document: The committed JSON Schema document.
        expected_commands: Commands that must be recorded; defaults to the
            schema's own ``TOOL_IDS``.

    Returns:
        Human-readable problems: commands with no recording, recordings for
        commands the schema does not declare, and each validation error with
        the command and the failing JSON path.
    """
    expected = set(TOOL_IDS) if expected_commands is None else set(expected_commands)
    recorded = set(payloads)
    problems: list[str] = []

    missing = sorted(expected - recorded)
    if missing:
        problems.append(
            f"no recorded payload for {len(missing)} command(s): {', '.join(missing)}"
        )
    extra = sorted(recorded - expected)
    if extra:
        problems.append(
            "recorded payloads for command(s) the schema does not declare: "
            + ", ".join(extra)
        )

    # Validate each payload against its own variant, selected by the ``command``
    # constant a consumer dispatches on.  Validating against the whole document
    # would collapse every failure into one root-level "not valid under any of
    # the given schemas" message, which names neither the field nor the command.
    variants: dict[str, Mapping[str, Any]] = {}
    for variant in document.get("oneOf", ()):
        value = variant.get("properties", {}).get("command", {}).get("const")
        if isinstance(value, str):
            if value in variants:
                problems.append(f"the schema declares {value!r} more than once")
            variants[value] = variant

    for command in sorted(recorded & expected):
        variant = variants.get(command)
        if variant is None:
            problems.append(f"{command}: the schema has no variant for it")
            continue
        errors = sorted(
            Draft202012Validator(variant).iter_errors(payloads[command]),
            key=lambda error: [str(part) for part in error.absolute_path],
        )
        for error in errors:
            where = "/".join(str(part) for part in error.absolute_path) or "<root>"
            problems.append(f"{command}: {where}: {error.message}")
    return problems


def serialize_corpus(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    generated: str | None = None,
    comment: str = _COMMENT,
) -> bytes:
    """Return *payloads* as corpus JSON: UTF-8, no BOM, CRLF, trailing newline.

    One shape for the file, written here so a Windows editor cannot flip its
    line endings and turn a one-payload change into a whole-file rewrite.
    """
    payload: dict[str, Any] = {
        "_comment": comment,
        "_generated": date.today().isoformat() if generated is None else generated,
        "schema_version": SCHEMA_VERSION,
        "payloads": {command: payloads[command] for command in sorted(payloads)},
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def write_corpus(
    payloads: Mapping[str, Mapping[str, Any]],
    *,
    path: Path | None = None,
    generated: str | None = None,
) -> bytes:
    """Write the corpus and return the bytes written.

    Args:
        payloads: Command path to recorded payload.
        path: Where to write; defaults to ``CORPUS_PATH``.
        generated: ISO date to record; defaults to today.

    Returns:
        The exact bytes written, so a caller can assert on them.
    """
    destination = CORPUS_PATH if path is None else path
    data = serialize_corpus(payloads, generated=generated)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return data


def slug_for(command: str) -> str:
    """Return the file stem a command's exported payload is named after.

    Args:
        command: CLI path (``bpm``, ``cue generate``).

    Returns:
        Lower-case, dash-separated: ``cue-generate``.

    Raises:
        ConformanceError: if the command has no alphanumeric characters, which
            would export to ``.json`` and collide with nothing useful.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", command.lower()).strip("-")
    if not slug:
        raise ConformanceError(f"cannot derive an export name from {command!r}")
    return slug


def export_payloads(
    payloads: Mapping[str, Mapping[str, Any]],
    directory: Path,
) -> list[Path]:
    """Write one JSON file per command into *directory*.

    Args:
        payloads: Command path to recorded payload.
        directory: Destination; created if missing.

    Returns:
        The files written, in command order.

    Raises:
        ConformanceError: if two commands slug to the same file name, which
            would silently overwrite one payload with the other.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    written: list[Path] = []
    for command in sorted(payloads):
        stem = slug_for(command)
        if stem in stems:
            raise ConformanceError(
                f"{command!r} and {stems[stem]!r} both export to {stem}.json"
            )
        stems[stem] = command
        path = directory / f"{stem}.json"
        text = json.dumps(payloads[command], indent=2, ensure_ascii=False) + "\n"
        # UTF-8 without a BOM and LF endings, like the committed schema, so a
        # downloaded file opens cleanly in every editor and diff tool.
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written


def _check(corpus_path: Path, schema_path: Path) -> int:
    """Validate the committed corpus against the committed schema."""
    corpus = load_corpus(corpus_path)
    document = load_schema(schema_path)
    problems = conformance_problems(corpus.payloads, document)
    for problem in problems:
        print(f"gate fail: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"{len(corpus.payloads)} recorded payload(s) in {corpus_path.name} validate "
        f"against {schema_path.name} (schema v{corpus.schema_version})"
    )
    return 0


def _export(corpus_path: Path, schema_path: Path, directory: Path) -> int:
    """Validate the corpus, then write one file per command into *directory*."""
    corpus = load_corpus(corpus_path)
    document = load_schema(schema_path)
    problems = conformance_problems(corpus.payloads, document)
    if problems:
        # Never publish payloads the gate rejects: the artifact is a promise to
        # script authors, so it is written only from a conforming corpus.
        for problem in problems:
            print(f"gate fail: {problem}", file=sys.stderr)
        return 1
    written = export_payloads(corpus.payloads, directory)
    print(f"exported {len(written)} payload(s) to {directory}")
    return 0


def _record(corpus_path: Path) -> int:
    """Drive every command and rewrite the corpus."""
    from tests.cli_payloads import record_payloads

    payloads = record_payloads()
    write_corpus(payloads, path=corpus_path)
    for command in sorted(payloads):
        print(f"{command}: recorded")
    print(f"wrote {corpus_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``--check`` (default) or ``--record`` action.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit status: 0 when every recorded payload conforms or the
        corpus was written, 1 when a claim fails or the check cannot run.
    """
    parser = argparse.ArgumentParser(
        prog="python -m tests.cli_schema_conformance",
        description="Validate the recorded CLI payloads against the JSON Schema.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="validate the committed corpus"
    )
    action.add_argument(
        "--record", action="store_true", help="re-drive every command and rewrite it"
    )
    action.add_argument(
        "--export-dir",
        type=Path,
        metavar="DIR",
        help="write one JSON file per command into DIR (the CI artifact)",
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args(argv)

    try:
        if args.record:
            return _record(args.corpus)
        if args.export_dir is not None:
            return _export(args.corpus, args.schema, args.export_dir)
        return _check(args.corpus, args.schema)
    except ConformanceError as exc:
        print(f"gate fail: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
