"""Validate the recorded CLI payloads against the committed JSON Schema.

``tests/data/cli_payloads.json`` holds one recorded payload per command, taken
from the real click commands (see :mod:`tests.cli_payloads`).  This module
checks that snapshot against ``audio_suite_shared/cli_schema.json`` - the
artifact an external consumer validates with - using a real draft 2020-12
validator, not the hand-rolled subset in ``tests/test_cli_json_schema.py``
(which exists because the suite outgrew ``jsonschema``-free validation for the
*live* drives).

Three claims, all of which can fail:

* **Coverage** — the corpus records exactly the commands the schema declares.
  A new command with no recording, or a recording for a command that no longer
  exists, is a gate failure rather than a silently narrower check.  The same
  applies to the fatal-error documents recorded beside them.
* **Conformance** — every recorded payload validates against the committed
  document.  ``additionalProperties: false`` makes this the removal detector:
  dropping a field from a command's schema is caught here on the recorded
  bytes, because the corpus still carries the key.  A purely additive change
  leaves the corpus valid, which is correct - the key is optional.
* **Failure shape** — every recorded fatal-error document validates too, and
  is the shape a pre-run failure publishes: zero counters, ``errors`` at 1, the
  reason in ``error``, and no tool-specific fields.  A script can therefore
  parse a failed run with the same code it parses a successful one.

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
``cue-generate.json``), plus ``<command>-error.json`` holding that command's
fatal-error document.  CI's test job uploads that directory as the
``cli-payloads`` artifact, so a script author can read both the real payload a
command produces and the document it publishes when it fails, without
installing or running anything - and what they read is the same bytes the gate
validates.

Changed in 1.4.1: initial version, the recorded-payload gate for the CLI JSON
contract (PLAN D102).
Changed in 1.4.1: ``--export-dir`` and the ``cli-payloads`` CI artifact, so the
recordings are inspectable without a checkout (PLAN D103).
Changed in 1.4.1: the corpus also records each command's fatal-error document
(``errors``), validated and exported beside the payload, so the failure shape
is published rather than inferred (PLAN D105).
Changed in 2.1.0: the corpus comment names ``<python>`` — the recording
interpreter, normalised so ``doctor``'s interpreter field does not bake a host
path into the committed snapshot.
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

from audio_suite_shared.cli_schema import (
    CORE_TYPES,
    SCHEMA_VERSION,
    TOOL_IDS,
    schema_json,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The committed schema document external consumers validate with.
SCHEMA_PATH = REPO_ROOT / "audio_suite_shared" / "cli_schema.json"

#: One recorded payload per command (see the module docstring).
CORPUS_PATH = REPO_ROOT / "tests" / "data" / "cli_payloads.json"

#: Keys the corpus may carry.  An unknown key is a typo or a file left by an
#: older shape, and both would silently change what the check means.
_KNOWN_KEYS = frozenset(
    {"_comment", "_generated", "schema_version", "payloads", "errors"}
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

_COMMENT = (
    "One recorded payload and one fatal-error document per CLI command, "
    "validated against audio_suite_shared/cli_schema.json by the "
    "schema-conformance gate. Host paths appear as <run> (the scratch "
    "directory), <repo> (the checkout) and <python> (the recording interpreter, "
    "which the doctor payload reports), so the file is machine-independent. "
    "Do not edit by hand; run `python -m tests.cli_schema_conformance --record`."
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
        errors: Command path to the fatal-error document that command printed
            when it was driven with a missing input path (or an unknown option,
            for the two commands that take no path).
    """

    path: Path
    comment: str
    generated: str
    schema_version: int
    payloads: Mapping[str, Mapping[str, Any]]
    errors: Mapping[str, Mapping[str, Any]]


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
            unknown key, lacks a valid timestamp or matching schema version, or
            holds anything but an object payload per command name - for the
            payloads and for the fatal-error documents alike.
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

    recorded = _documents(payload.get("payloads"), source, "payloads")
    failures = _documents(payload.get("errors"), source, "errors")
    return Corpus(
        path=source,
        comment=comment,
        generated=generated,
        schema_version=version,
        payloads=recorded,
        errors=failures,
    )


def _documents(raw: Any, source: Path, field: str) -> dict[str, Mapping[str, Any]]:
    """Return *raw* as command -> non-empty object, or raise ``ConformanceError``.

    ``payloads`` and ``errors`` have the same shape, so they are checked by one
    function: a map that quietly accepts a non-object value would let a
    malformed recording reach the validator and fail there for the wrong reason.
    """
    _require(
        isinstance(raw, dict) and bool(raw),
        source,
        f"`{field}` must be a non-empty object",
    )
    documents: dict[str, Mapping[str, Any]] = {}
    for command, document in raw.items():
        _require(
            isinstance(command, str) and bool(command.strip()),
            source,
            f"{command!r} is not a command name",
        )
        _require(
            isinstance(document, dict) and bool(document),
            source,
            f"{command}: {field} entry must be a non-empty object",
        )
        documents[command] = document
    return documents


def conformance_problems(
    payloads: Mapping[str, Mapping[str, Any]],
    document: Mapping[str, Any],
    *,
    errors: Mapping[str, Mapping[str, Any]] | None = None,
    expected_commands: Sequence[str] | None = None,
    check_examples: bool = True,
) -> list[str]:
    """Return every problem with *payloads* against *document* (empty is pass).

    Args:
        payloads: Command path to recorded payload.
        document: The committed JSON Schema document.
        errors: Command path to that command's recorded fatal-error document.
            Required in practice: omitting the map is reported as missing
            coverage rather than silently narrowing the check.
        expected_commands: Commands that must be recorded; defaults to the
            schema's own ``TOOL_IDS``.
        check_examples: Whether to require the published examples (present,
            valid, and equal to the recorded payload).  A *fresh* recording is
            not published yet - its durations differ - so the recorder's own
            test validates shape with this off.

    Returns:
        Human-readable problems: commands with no recording, recordings for
        commands the schema does not declare, each validation error with the
        command and the failing JSON path, and every example problem.
    """
    expected = set(TOOL_IDS) if expected_commands is None else set(expected_commands)
    recorded = set(payloads)
    failures: Mapping[str, Mapping[str, Any]] = {} if errors is None else errors
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

    missing_failures = sorted(expected - set(failures))
    if missing_failures:
        problems.append(
            f"no recorded fatal-error document for {len(missing_failures)} "
            "command(s): " + ", ".join(missing_failures)
        )
    extra_failures = sorted(set(failures) - expected)
    if extra_failures:
        problems.append(
            "fatal-error documents for command(s) the schema does not declare: "
            + ", ".join(extra_failures)
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
        problems.extend(_validation_problems(command, payloads[command], variant))

    # The failure shape is part of the contract: a run that died before doing
    # any work publishes the core keys, ``errors`` at 1 and the reason, so a
    # caller parses a failed run with the code it already wrote.  That is a
    # claim about the recorded bytes, not only about the schema's types.
    for command in sorted(set(failures) & expected):
        variant = variants.get(command)
        if variant is None:
            continue
        problems.extend(
            _validation_problems(
                command, failures[command], variant, label="error document"
            )
        )
        problems.extend(_fatal_shape_problems(command, failures[command]))

    # The published examples are a promise to script authors: present for every
    # command, each a payload the variant accepts, and the recorded one.  JSON
    # Schema treats ``examples`` as an annotation, so nothing else would check
    # them - a stale or wrong example would ship silently.
    for command in sorted(expected & set(variants)) if check_examples else []:
        examples = variants[command].get("examples")
        if not isinstance(examples, list) or not examples:
            problems.append(
                f"{command}: the schema variant has no example payload "
                "(regenerate with --record)"
            )
            continue
        for index, example in enumerate(examples):
            problems.extend(
                _validation_problems(
                    command, example, variants[command], label=f"example[{index}]"
                )
            )
        if command in payloads and payloads[command] not in examples:
            problems.append(
                f"{command}: the recorded payload is not published as an example "
                "(regenerate with --record)"
            )
        if command in failures and failures[command] not in examples:
            problems.append(
                f"{command}: the recorded fatal-error document is not published "
                "as an example (regenerate with --record)"
            )
    return problems


def _validation_problems(
    command: str,
    payload: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    label: str = "",
) -> list[str]:
    """Return the validator's complaints about *payload* against *variant*.

    A payload is validated against its own variant rather than the whole
    document: the outer ``oneOf`` would report one root-level "not valid under
    any of the given schemas" that names neither the field nor the command.
    """
    prefix = f"{command}: {label}: " if label else f"{command}: "
    return [
        f"{prefix}{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: "
        f"{error.message}"
        for error in sorted(
            Draft202012Validator(variant).iter_errors(payload),
            key=lambda error: [str(part) for part in error.absolute_path],
        )
    ]


def _fatal_shape_problems(command: str, payload: Mapping[str, Any]) -> list[str]:
    """Return why *payload* is not the pre-run fatal shape (empty when it is).

    The published failure document makes promises a type check cannot: it has
    no tool-specific fields (so a caller needs only the core keys), its
    counters are zero (nothing was attempted), ``errors`` is exactly 1 (one run
    died) and ``error`` says why.
    """
    problems: list[str] = []
    undeclared = sorted(set(payload) - set(CORE_TYPES) - {"error"})
    if undeclared:
        problems.append(
            f"{command}: the error document carries tool-specific field(s) "
            f"{undeclared}; a fatal run publishes only the core keys plus 'error'"
        )
    for key in ("total", "processed", "succeeded", "skipped"):
        if payload.get(key) != 0:
            problems.append(
                f"{command}: the error document reports {key}="
                f"{payload.get(key)!r}; a run that failed before doing any work "
                "reports 0"
            )
    if payload.get("errors") != 1:
        problems.append(
            f"{command}: the error document reports errors="
            f"{payload.get('errors')!r}; a fatal run reports exactly 1"
        )
    reason = payload.get("error")
    if not isinstance(reason, str) or not reason.strip():
        problems.append(
            f"{command}: the error document has no non-empty 'error' message"
        )
    return problems


def serialize_corpus(
    payloads: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, Mapping[str, Any]],
    *,
    generated: str | None = None,
    comment: str = _COMMENT,
) -> bytes:
    """Return *payloads* and *errors* as corpus JSON.

    UTF-8, no BOM, CRLF, trailing newline: one shape for the file, written here
    so a Windows editor cannot flip its line endings and turn a one-payload
    change into a whole-file rewrite.  ``errors`` is required rather than
    defaulted: a corpus written without the failure documents would load and
    then fail coverage, which is a worse failure than an argument error.
    """
    payload: dict[str, Any] = {
        "_comment": comment,
        "_generated": date.today().isoformat() if generated is None else generated,
        "schema_version": SCHEMA_VERSION,
        "payloads": {command: payloads[command] for command in sorted(payloads)},
        "errors": {command: errors[command] for command in sorted(errors)},
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def write_corpus(
    payloads: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, Mapping[str, Any]],
    *,
    path: Path | None = None,
    generated: str | None = None,
) -> bytes:
    """Write the corpus and return the bytes written.

    Args:
        payloads: Command path to recorded payload.
        errors: Command path to its fatal-error document.
        path: Where to write; defaults to ``CORPUS_PATH``.
        generated: ISO date to record; defaults to today.

    Returns:
        The exact bytes written, so a caller can assert on them.
    """
    destination = CORPUS_PATH if path is None else path
    data = serialize_corpus(payloads, errors, generated=generated)
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
    errors: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Path]:
    """Write one JSON file per command, plus its fatal-error document.

    ``bpm`` exports ``bpm.json`` and ``bpm-error.json``, so a script author can
    read both shapes without running the tool and without guessing that a
    failed run still carries the core keys.

    Args:
        payloads: Command path to recorded payload.
        directory: Destination; created if missing.
        errors: Command path to its fatal-error document.

    Returns:
        The files written, payloads first, in command order.

    Raises:
        ConformanceError: if two documents export to the same file name, which
            would silently overwrite one with the other.
    """
    directory.mkdir(parents=True, exist_ok=True)
    entries: list[tuple[str, str, Mapping[str, Any]]] = [
        (command, "", payloads[command]) for command in sorted(payloads)
    ]
    entries.extend(
        (command, "-error", errors[command]) for command in sorted(errors or {})
    )
    owners: dict[str, str] = {}
    written: list[Path] = []
    for command, suffix, document in entries:
        name = f"{slug_for(command)}{suffix}.json"
        if name in owners:
            raise ConformanceError(
                f"{command!r} and {owners[name]!r} both export to {name}"
            )
        owners[name] = command
        path = directory / name
        text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        # UTF-8 without a BOM and LF endings, like the committed schema, so a
        # downloaded file opens cleanly in every editor and diff tool.
        path.write_bytes(text.encode("utf-8"))
        written.append(path)
    return written


def _check(corpus_path: Path, schema_path: Path) -> int:
    """Validate the committed corpus against the committed schema."""
    corpus = load_corpus(corpus_path)
    document = load_schema(schema_path)
    problems = conformance_problems(corpus.payloads, document, errors=corpus.errors)
    for problem in problems:
        print(f"gate fail: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(
        f"{len(corpus.payloads)} recorded payload(s) and {len(corpus.errors)} "
        f"fatal-error document(s) in {corpus_path.name} validate against "
        f"{schema_path.name} (schema v{corpus.schema_version})"
    )
    return 0


def serialize_schema(
    payloads: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, Mapping[str, Any]],
) -> bytes:
    """Return the schema document with both kinds of example per command.

    UTF-8 without a BOM and LF endings: the committed ``cli_schema.json`` is
    generated here, so the file's byte shape is written down in one place.
    """
    return schema_json(examples=payloads, errors=errors).encode("utf-8")


def write_schema(
    payloads: Mapping[str, Mapping[str, Any]],
    errors: Mapping[str, Mapping[str, Any]],
    *,
    path: Path | None = None,
) -> bytes:
    """Write the schema document (examples included) and return the bytes.

    Args:
        payloads: Command path to the recorded payload.
        errors: Command path to its fatal-error document.
        path: Where to write; defaults to ``SCHEMA_PATH``.

    Returns:
        The exact bytes written, so a caller can assert on them.
    """
    destination = SCHEMA_PATH if path is None else path
    data = serialize_schema(payloads, errors)
    destination.write_bytes(data)
    return data


def _export(corpus_path: Path, schema_path: Path, directory: Path) -> int:
    """Validate the corpus, then write its documents into *directory*."""
    corpus = load_corpus(corpus_path)
    document = load_schema(schema_path)
    problems = conformance_problems(corpus.payloads, document, errors=corpus.errors)
    if problems:
        # Never publish payloads the gate rejects: the artifact is a promise to
        # script authors, so it is written only from a conforming corpus.
        for problem in problems:
            print(f"gate fail: {problem}", file=sys.stderr)
        return 1
    written = export_payloads(corpus.payloads, directory, corpus.errors)
    print(f"exported {len(written)} file(s) to {directory}")
    return 0


def _record(corpus_path: Path, schema_path: Path) -> int:
    """Drive every command, rewrite the corpus, and re-render the schema."""
    from tests.cli_payloads import record_error_payloads, record_payloads

    payloads = record_payloads()
    errors = record_error_payloads()
    write_corpus(payloads, errors, path=corpus_path)
    # The document's examples come from the corpus, so they are rewritten in
    # the same action; a separate regeneration step could leave them stale.
    write_schema(payloads, errors, path=schema_path)
    for command in sorted(payloads):
        print(f"{command}: recorded (payload and fatal-error document)")
    print(f"wrote {corpus_path}")
    print(f"wrote {schema_path}")
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
        "--record",
        action="store_true",
        help="re-drive every command, rewriting the corpus and the schema's examples",
    )
    action.add_argument(
        "--export-dir",
        type=Path,
        metavar="DIR",
        help=(
            "write each command's recorded payload and fatal-error document "
            "into DIR (the CI artifact)"
        ),
    )
    parser.add_argument("--corpus", type=Path, default=CORPUS_PATH)
    parser.add_argument("--schema", type=Path, default=SCHEMA_PATH)
    args = parser.parse_args(argv)

    try:
        if args.record:
            return _record(args.corpus, args.schema)
        if args.export_dir is not None:
            return _export(args.corpus, args.schema, args.export_dir)
        return _check(args.corpus, args.schema)
    except ConformanceError as exc:
        print(f"gate fail: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
