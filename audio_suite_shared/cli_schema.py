"""cli_schema.py — the locked JSON contract for ``audiosuite … --json``.

Every command that can emit JSON emits it through :func:`build_payload`, so one
script can read every tool's summary without per-tool key mapping:

    audiosuite bpm  ~/Music --json | jq '.processed, .skipped, .errors'
    audiosuite key  ~/Music --json | jq '.processed, .skipped, .errors'

Schema version 1 guarantees these keys, with these names and types, in every
payload:

====================  ==========================================================
Key                   Contract
====================  ==========================================================
``schema_version``    ``1`` — bumped only for a breaking change to this table.
``tool``              The tool's manifest id (``bpm``, ``library_stats``); ``cue``
                      for the CUE commands and ``doctor`` for the install check,
                      which have no manifest entry of their own.
``command``           The CLI path as invoked: ``bpm``, ``cue parse``.
``dry_run``           ``True`` when the run's ``--dry`` flag was in effect. A
                      command with no dry mode (``stats``, ``cue parse``) reports
                      ``False``; read-only behaviour is part of the command's
                      description, not of this flag.
``total``             Items the run set out to handle (files, edits, tracks).
``processed``         Items it finished attempting; a dry run still counts what
                      it evaluated.  This includes the skipped and failed items.
``succeeded``         ``processed - skipped - errors`` (never negative): the items
                      that actually produced a result.  Published so a script
                      does not have to know which tools count attempts.
``skipped``           Items deliberately not handled (no beat, no lyrics, …).
``errors``            Items that failed.
``duration_secs``     Wall-clock run time, rounded to milliseconds.
``duration_str``      The same value for display (``"12.4s"``).
``log_entries``       The run's log lines, newline-terminated, as text.
====================  ==========================================================

Tool-specific keys are allowed **at the top level** next to the core keys, and
each command declares its own in :data:`EXTRA_TYPES`.  Two consequences matter
to a consumer:

* An undeclared key is a bug: :func:`build_payload` refuses it.  Tools reach
  JSON through ``_Result.to_payload``, which publishes only the declared
  completion fields and leaves internal detail out, so a new internal field is
  never a JSON change.  The lock test drives every command and validates the
  real payload.
* A declared key may be absent when the run has nothing to say about it (for
  example ``isrc_submission`` on a run that submitted nothing).  Present keys
  always have the declared type.
* ``error`` is accepted on every command without declaration: a fatal run says
  why it stopped and still carries the core keys.

Two names intentionally do **not** mean different things across tools: the core
``duration_secs``/``duration_str`` are the run's wall-clock time in every
payload.  ``stats`` reports the library's audio duration separately as
``library_duration_secs``/``library_duration_str``, precisely so the shared name
keeps one meaning.

Each variant in the committed document also carries ``examples``: the payload
recorded from that command, followed by the command's **fatal-error document**
(counters at zero, ``errors`` at 1, the reason in ``error``).  Both are recorded
from real invocations, so a reader can see the success shape *and* the failure
shape without running the tool.  In JSON Schema terms examples are annotations -
they constrain nothing - but the schema-conformance gate validates every one of
them against its own variant, so a published example is always a payload the
contract accepts.  ``--json-schema`` prints the committed file itself (via
:func:`committed_schema_text`), examples included.

Changed in 1.4.0: initial version (PLAN D82), replacing per-tool ad-hoc
payloads: ``extra`` nesting, ``tagged``/``updated`` in place of counters, and
``log`` in place of ``log_entries`` were all inconsistent between commands.
Changed in 1.4.1: ``doctor`` joins the contract, so an install check is as
machine-readable as the runs it gates (PLAN D93).
Changed in 1.4.1: ``cue generate`` joins the contract, so the declared no-JSON
exception list is empty (PLAN D95).
Changed in 1.4.1: the committed document and a recorded payload per command
(``tests/data/cli_payloads.json``) are validated together by
``python -m tests.cli_schema_conformance``, the CI schema-conformance gate
(PLAN D102).
Changed in 1.4.1: every variant carries an ``examples`` array with the recorded
payload for that command, and ``--json-schema`` prints that committed file, so
a script author can see real output without running the tool (PLAN D104).
Changed in 1.4.1: each variant's ``examples`` also publishes the command's
fatal-error document, recorded from a real failing invocation, so the failure
shape is visible without triggering one (PLAN D105).
Changed in 1.4.1: records why there is no streaming mode (PLAN D101).
Changed in 1.4.1: BPM publishes ``outside_range_files`` - the tempos it
measured outside the configured band and tagged as measured - so a run
summary can count them without parsing the log (D109).
Changed in 2.0.0: ``stems`` joins the contract with the separator's
``separated``/``files_written``/``output_dir``/``device`` fields, so a script
can tell how many tracks were split and where the stems landed
(PLAN_feature_expansion.md Item 6.1).

One document per run, deliberately
----------------------------------

``--json`` prints **one** document, when the run ends: the summary above.
There is no ``--json-lines`` and no per-file record stream (S5-8).  An
hour-long batch therefore shows nothing machine-readable until it finishes.

That is a decision, not an omission.  A per-file stream has to come from each
processor's progress callback, so it is a 28-command retrofit whose records
would vary in shape per tool, while the summary is what scripts consume today;
progress already goes to stderr and to the log for a human watching.  The
behaviour is locked rather than merely documented:
``tests/test_cli_json_schema.py::TestSingleDocument`` asserts the document
starts at byte 0 of stdout and nothing follows it, for every run it drives.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Any, Final

#: Bumped only when a core key is renamed, removed or changes meaning.
SCHEMA_VERSION: Final[int] = 1

#: The keys every payload carries, in output order, with their JSON types.
#: ``bool`` is checked before ``int`` because ``isinstance(True, int)``.
CORE_TYPES: Final[Mapping[str, Any]] = {
    "schema_version": int,
    "tool": str,
    "command": str,
    "dry_run": bool,
    "total": int,
    "processed": int,
    "succeeded": int,
    "skipped": int,
    "errors": int,
    "duration_secs": float,
    "duration_str": str,
    "log_entries": list,
}

#: Command path -> tool id.  The command path is how the payload is reached;
#: the tool id matches ``ToolManifest.id`` so a consumer can join JSON output
#: with the Master Driver's per-tool records.
TOOL_IDS: Final[Mapping[str, str]] = {
    "album-art": "art",
    "album-genre": "album_genre",
    "artnormalize": "album_art_normalizer",
    "asx-extract": "asx_extractor",
    "bpm": "bpm",
    "cd-rip": "cd_ripper",
    "convert": "converter",
    "cue generate": "cue",
    "cue parse": "cue",
    "cue split": "cue",
    "declick": "pop_click_remover",
    # ``doctor`` is the install check rather than a tool, so its id has no
    # ``ToolManifest`` entry; it is declared here the way ``cue`` is.
    "doctor": "doctor",
    "enhance": "audio_enhancer",
    "fingerprint": "fingerprinter",
    "genre-sync": "genre_sync",
    "key": "key",
    "lyrics": "lyrics_manager",
    "mood-analysis-batch": "mood_analysis_batch",
    "mood-analyzer": "mood_analyzer",
    "normalise": "audio_normalizer",
    "reduce": "noise_reduction",
    "refine": "audio_refinery",
    "reorganize": "file_reorganizer",
    "replaygain": "replaygain",
    "scrub": "scrubber",
    "silence-trim": "silence_trimmer",
    "spectrogram": "spectral_viewer",
    "stats": "library_stats",
    "stems": "stem_separator",
    "tag-edit": "tag_editor",
    "tag-update": "tag_field_updater",
    "tempo": "tempo",
}

#: Commands registered on the CLI that have no ``--json`` payload.  Declared
#: so the coverage test can prove the exclusion is deliberate: a new command
#: either gains a schema or is listed here with a reason.  It is **empty** since
#: ``cue generate`` gained a payload (PLAN D95), and the lock asserts emptiness:
#: an entry reappearing is a deliberate release decision, not a silent gap.
NO_JSON_COMMANDS: Final[Mapping[str, str]] = {}

#: Tool-specific top-level keys each command may add.  A value is the accepted
#: type or tuple of types; ``type(None)`` marks an optional null.
EXTRA_TYPES: Final[Mapping[str, Mapping[str, Any]]] = {
    "bpm": {
        "skipped_files": list,
        "error_files": list,
        # Tempos measured outside the configured band: tagged as measured, so
        # neither skipped nor failed, and published for the same reason the
        # per-file line says "(outside 75-175)" (D108, D109).
        "outside_range_files": list,
    },
    "album-art": {
        "source": str,
        "selection_audit": (str, type(None)),
    },
    "album-genre": {
        "files_with_genre": int,
        "coverage_pct": float,
        "unique_genres": int,
        "album_genre_string": str,
        "write_count": int,
        "write_errors": int,
        "read_errors": int,
    },
    "asx-extract": {
        "successes": int,
        "failures": int,
    },
    "enhance": {
        "done": int,
    },
    "genre-sync": {
        "updated": int,
        "no_genre": int,
    },
    "convert": {
        "converted": int,
        "output_dir": str,
        "format_counts": dict,
    },
    "fingerprint": {
        "counts": dict,
        "results": list,
        "isrc_submission": dict,
    },
    "mood-analysis-batch": {
        "directory": str,
        "duration": int,
        "parallel": bool,
        # null means the machine default (the option was not passed).
        "workers": (int, type(None)),
        "tagged": int,
        "folders": int,
        "log_path": str,
    },
    "tag-edit": {
        "path": (str, type(None)),
        "field": (str, type(None)),
        "old_value": (str, type(None)),
        "new_value": (str, type(None)),
        # Single-file mode reports a flag, CSV mode a count of files: the two
        # modes share one shape, so both types are valid for these keys.
        "changed": (int, bool),
        "written": (int, bool),
        "error": (str, type(None)),
        "csv": (str, type(None)),
        "rows_read": int,
        "edits_planned": int,
        "unchanged": int,
        "row_errors": list,
        "ignored_columns": list,
    },
    "tag-update": {
        "directory": str,
        "updated": int,
    },
    "stats": {
        "scan_path": str,
        "total_files": int,
        "total_albums": int,
        "total_artists": int,
        "total_track_artists": int,
        "library_duration_secs": float,
        "library_duration_str": str,
        "format_breakdown": dict,
        "bpm_distribution": dict,
        "key_distribution": dict,
        "key_mode_distribution": dict,
        "mood_distribution": dict,
        "genre_distribution": dict,
        "tempo_marking_distribution": dict,
        "year_distribution": dict,
        "missing_data": dict,
        "top_artists": list,
        "top_genres": list,
        "completeness": dict,
        "trend": list,
    },
    "spectrogram": {
        "path": str,
        "written": int,
        "images": list,
        "error_messages": list,
    },
    "stems": {
        "separated": int,
        "files_written": int,
        "output_dir": str,
        "device": str,
    },
    "cd-rip": {
        "drive": str,
        "output_dir": (str, type(None)),
        "format": (str, type(None)),
        "tracks": (str, type(None)),
        "verify": (str, type(None)),
        "read_offset_frames": (int, type(None)),
    },
    "cue generate": {
        "cue_path": str,
        # The sheet's track count, not the written-path list ``cue split``
        # publishes: a caller needs the count before splitting.
        "tracks": int,
        "title": str,
    },
    "cue parse": {
        "catalog": (str, type(None)),
        "performer": (str, type(None)),
        "title": (str, type(None)),
        "rem": list,
        "files": list,
    },
    "cue split": {
        "cue_file": str,
        "output_dir": str,
        "tracks": list,
    },
    "doctor": {
        "healthy": bool,
        "checkout_version": (str, type(None)),
        "installed_version": (str, type(None)),
        "editable": bool,
        "mapped": int,
        # One object per first-party package: name, status, origin, commands.
        "packages": list,
        # One object per manifest command that failed to register: tool, command.
        "missing_commands": list,
        "problems": list,
    },
}


def commands() -> frozenset[str]:
    """Return every command path that publishes a JSON payload."""
    return frozenset(TOOL_IDS)


def extras_for(command: str) -> Mapping[str, Any]:
    """Return the declared tool-specific keys for *command* (possibly empty)."""
    return EXTRA_TYPES.get(command, {})


def build_payload(
    command: str,
    *,
    dry_run: bool,
    total: int = 0,
    processed: int = 0,
    skipped: int = 0,
    errors: int = 0,
    duration_secs: float = 0.0,
    log_entries: Sequence[str] = (),
    **extras: Any,
) -> dict[str, Any]:
    """Build one command's payload in schema order.

    Args:
        command:        CLI path (a key of :data:`TOOL_IDS`).
        dry_run:        Whether the run's ``--dry`` flag was in effect.
        total:          Items the run set out to handle.
        processed:      Items finished attempting (includes skipped/errors).
        skipped:        Items deliberately not handled.
        errors:         Items that failed.
        duration_secs:  Wall-clock run time in seconds.
        log_entries:    The run's log lines.
        **extras:       Tool-specific fields declared in :data:`EXTRA_TYPES`.

    Returns:
        A JSON-serialisable dict whose core keys always appear, in schema
        order, followed by the declared extras.

    Raises:
        ValueError: The command has no schema, or an extra is not declared.
            That is a wiring bug in the tool, caught here rather than by a
            consumer silently reading a field nobody promised.
    """
    tool = TOOL_IDS.get(command)
    if tool is None:
        raise ValueError(f"no JSON schema for command {command!r}")

    # ``error`` is universal: a fatal run must be able to say why it failed
    # without every command declaring a field it only uses on failure.
    undeclared = sorted(set(extras) - set(extras_for(command)) - {"error"})
    if undeclared:
        raise ValueError(
            f"{command!r} emits undeclared JSON field(s) {undeclared}; "
            "declare them in audio_suite_shared.cli_schema.EXTRA_TYPES"
        )

    seconds = round(float(duration_secs), 3)
    attempted = int(processed)
    failures = int(errors)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "command": command,
        "dry_run": bool(dry_run),
        "total": int(total),
        "processed": attempted,
        "succeeded": max(attempted - int(skipped) - failures, 0),
        "skipped": int(skipped),
        "errors": failures,
        "duration_secs": seconds,
        "duration_str": f"{seconds:.1f}s",
        "log_entries": list(log_entries),
    }
    payload.update(extras)
    return payload


def error_payload(
    command: str,
    message: str,
    *,
    dry_run: bool = False,
    log_entries: Sequence[str] = (),
) -> dict[str, Any]:
    """Build the payload for a command that failed before doing any work.

    A script should not need a second code path for a fatal error: the payload
    still carries the core keys, with ``errors`` at 1 and the reason in
    ``error``.  ``error`` is therefore accepted on every command, even those
    that do not otherwise declare it.
    """
    payload = build_payload(
        command,
        dry_run=dry_run,
        errors=1,
        log_entries=log_entries,
    )
    payload["error"] = message
    return payload


def validate_payload(command: str, payload: Mapping[str, Any]) -> list[str]:
    """Return the schema violations in *payload* (empty when it conforms).

    This is the contract the lock test asserts for every command's real
    ``--json`` output; tools do not call it at runtime, because a consumer
    needs a payload even when a field is missing.

    Args:
        command: CLI path the payload claims to come from.
        payload: Parsed JSON object.

    Returns:
        Human-readable problems: missing/wrong-typed core keys, a core value
        with the wrong meaning, or an undeclared/mistyped extra.
    """
    problems: list[str] = []
    if command not in TOOL_IDS:
        return [f"no JSON schema for command {command!r}"]

    allowed = set(CORE_TYPES) | set(extras_for(command)) | {"error"}

    for key, expected in CORE_TYPES.items():
        if key not in payload:
            problems.append(f"missing core field {key!r}")
            continue
        if not _matches(payload[key], expected):
            problems.append(
                f"core field {key!r} is {type(payload[key]).__name__}, "
                f"expected {_type_name(expected)}"
            )

    for key, value in payload.items():
        if key in CORE_TYPES:
            continue
        if key not in allowed:
            problems.append(f"undeclared field {key!r}")
            continue
        expected = extras_for(command).get(key)
        if expected is not None and not _matches(value, expected):
            problems.append(
                f"field {key!r} is {type(value).__name__}, "
                f"expected {_type_name(expected)}"
            )

    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append(
            f"schema_version is {payload.get('schema_version')!r}, "
            f"expected {SCHEMA_VERSION}"
        )
    if payload.get("command") != command:
        problems.append(f"command is {payload.get('command')!r}, expected {command!r}")
    if payload.get("tool") != TOOL_IDS[command]:
        problems.append(
            f"tool is {payload.get('tool')!r}, expected {TOOL_IDS[command]!r}"
        )

    log_entries = payload.get("log_entries")
    if isinstance(log_entries, list) and any(
        not isinstance(entry, str) for entry in log_entries
    ):
        problems.append("log_entries must contain only strings")

    if payload.get("error") is not None and not isinstance(payload["error"], str):
        problems.append("error must be a string when present")

    return problems


def json_schema(
    examples: Mapping[str, Mapping[str, Any]] | None = None,
    errors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the JSON Schema (draft 2020-12) for every command's payload.

    The document has one variant per command under ``oneOf``, discriminated by
    the ``command`` constant, so a consumer can validate exactly what that
    command promises without knowing which tool wrote it.  It is generated
    from :data:`CORE_TYPES` and :data:`EXTRA_TYPES` — never hand-maintained —
    and ``audio_suite_shared/cli_schema.json`` is the committed copy; the lock
    test fails when the two disagree.

    Args:
        examples: Command path to a real payload, published as that variant's
            first example.  The committed document is built with the recorded
            payloads, so a reader can see the shape without running the tool.
            ``examples`` is an annotation: it does not constrain validation
            (payloads still only need the core keys and declared extras),
            which is why the gate validates every example itself.
        errors: Command path to that command's fatal-error document, published
            after the recorded payload in the same ``examples`` array.  It is
            a real failure payload (``errors`` at 1, the message in ``error``),
            so a script author sees the failure shape - no run required, and
            no guess at whether a failed run still carries the core keys.

    Returns:
        A JSON-serialisable schema document.
    """
    variants = [
        _command_schema(
            command,
            tool,
            None if examples is None else examples.get(command),
            None if errors is None else errors.get(command),
        )
        for command, tool in TOOL_IDS.items()
    ]
    described = (
        "One variant per command, discriminated by the constant 'command'. "
        "Every payload carries the shared counters and an 'error' string "
        "only when the run failed."
    )
    if examples is not None or errors is not None:
        described += (
            " Each variant's 'examples' array holds the payload recorded from "
            "that command followed by that command's fatal-error document "
            "(errors: 1 with the reason in 'error') - illustrative only, not "
            "part of validation."
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://audiosuite-pro/schemas/cli-json-v1.json",
        "title": f"AudioSuite-Pro CLI JSON output (schema v{SCHEMA_VERSION})",
        "description": described,
        "oneOf": variants,
    }


def schema_json(
    examples: Mapping[str, Mapping[str, Any]] | None = None,
    errors: Mapping[str, Mapping[str, Any]] | None = None,
) -> str:
    """Return the schema document as pretty-printed JSON text.

    Args:
        examples: Command path to a real payload, as :func:`json_schema` takes
            them.  The committed document is generated with the recorded
            payloads; omitting them yields the structural schema alone.
        errors: Command path to that command's fatal-error document, published
            after the payload in the same ``examples`` array.
    """
    return json.dumps(json_schema(examples, errors), indent=2) + "\n"


def committed_schema_text() -> str:
    """Return the committed schema document exactly as it ships.

    ``--json-schema`` prints this document, so a consumer sees the artifact
    including its example payloads rather than a document regenerated on the
    fly from whatever version is imported.  (The CLI writes it as text, so the
    console's platform line endings apply; the JSON is unchanged.)

    Returns:
        The file's text, UTF-8.

    Raises:
        FileNotFoundError: if the install is missing the package data.
    """
    return (
        resources.files("audio_suite_shared")
        .joinpath("cli_schema.json")
        .read_text(encoding="utf-8")
    )


def _command_schema(
    command: str,
    tool: str,
    example: Mapping[str, Any] | None = None,
    error_example: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one command's variant of the schema document.

    ``examples`` keeps a fixed order - the recorded payload first, the fatal
    document second - because a consumer that reads ``examples[0]`` must get the
    same kind of document every time.
    """
    properties: dict[str, Any] = {
        "schema_version": {"const": SCHEMA_VERSION},
        "tool": {"const": tool},
        "command": {"const": command},
        "dry_run": {"type": "boolean"},
        "total": {"type": "integer", "minimum": 0},
        "processed": {"type": "integer", "minimum": 0},
        "succeeded": {"type": "integer", "minimum": 0},
        "skipped": {"type": "integer", "minimum": 0},
        "errors": {"type": "integer", "minimum": 0},
        "duration_secs": {"type": "number", "minimum": 0},
        "duration_str": {"type": "string"},
        "log_entries": {"type": "array", "items": {"type": "string"}},
    }
    for key, expected in extras_for(command).items():
        properties[key] = {"type": _schema_types(expected)}
    properties.setdefault("error", {"type": "string"})
    variant: dict[str, Any] = {
        "title": f"audiosuite {command} --json",
        "type": "object",
        "properties": properties,
        "required": list(CORE_TYPES),
        "additionalProperties": False,
    }
    published = [item for item in (example, error_example) if item is not None]
    if published:
        variant["examples"] = published
    return variant


def _schema_types(expected: Any) -> str | list[str]:
    """Translate a declared Python type (or tuple) to JSON Schema ``type``."""
    if isinstance(expected, tuple):
        return [_json_type_name(option) for option in expected]
    return _json_type_name(expected)


def _json_type_name(expected: Any) -> str:
    """Name one Python type in JSON Schema's vocabulary."""
    name: str = {
        bool: "boolean",
        int: "integer",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
        type(None): "null",
    }[expected]
    return name


def _matches(value: Any, expected: Any) -> bool:
    """Return whether *value* has one of the *expected* JSON types."""
    if isinstance(expected, tuple):
        return any(_matches(value, option) for option in expected)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, expected)


def _type_name(expected: Any) -> str:
    """Render an accepted type (or tuple of them) for a message."""
    if isinstance(expected, tuple):
        return " or ".join(_type_name(option) for option in expected)
    name: str = expected.__name__
    return name
