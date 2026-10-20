"""Lock the ``--json`` contract for every CLI command (schema v1).

Three layers of protection, because a schema is only stable if something fails
when it drifts:

1. **Coverage** — every command with a ``--json`` flag has a schema entry, and
   every entry belongs to a real command.  A new command cannot ship JSON that
   no consumer was promised.
2. **Shape** — :func:`audio_suite_shared.cli_schema.build_payload` refuses an
   undeclared field, and :func:`validate_payload` catches a renamed, missing or
   wrong-typed core key.
3. **Reality** — each command is invoked for real on a temporary library (with
   the hardware/network paths patched out where necessary) and its stdout is
   parsed and validated.  A payload that only conforms in a unit test does not
   count.

``cd-rip`` is the one command whose real run needs an audio CD drive; its two
payload builders are locked directly instead (see :class:`TestCdRipPayloads`).
``doctor`` inspects the running install rather than a library, so it needs no
arguments - and its exit status is allowed to be 0 or 1, because a stale
install is a valid report (its broken-install shape is locked in
``audio_suite_shared/tests/test_doctor_cli.py``).

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).
Changed in 1.4.1: ``doctor`` joins the driven set (PLAN D93).
Changed in 1.4.1: ``cue generate`` joins the driven set too, leaving
``NO_JSON_COMMANDS`` empty (PLAN D95).
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from audio_suite_shared import cli_schema
from audio_suite_shared.cli_app import cli
from audio_suite_shared.cli_schema import (
    CORE_TYPES,
    NO_JSON_COMMANDS,
    SCHEMA_VERSION,
    TOOL_IDS,
    build_payload,
    error_payload,
    extras_for,
    schema_json,
    validate_payload,
)
from audio_suite_shared.tool_plugin import get_registry


def _walk_commands(group: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Return ``(command path, click command)`` for every leaf command."""
    found: list[tuple[str, Any]] = []
    for name in group.list_commands(None):
        command = group.get_command(None, name)
        path = f"{prefix}{name}"
        if hasattr(command, "commands"):
            found.extend(_walk_commands(command, f"{path} "))
        else:
            found.append((path, command))
    return found


def _option_names(command: Any) -> set[str]:
    """Return every option/flag spelling a command accepts."""
    return {opt for param in command.params for opt in getattr(param, "opts", ())}


def _committed_schema() -> dict[str, Any]:
    """Load the committed schema document external consumers validate with."""
    path = (
        Path(__file__).resolve().parents[1] / "audio_suite_shared" / "cli_schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_variant(document: dict[str, Any], command: str) -> dict[str, Any]:
    """Return the document's variant for *command*."""
    for variant in document["oneOf"]:
        if variant["properties"]["command"].get("const") == command:
            return dict(variant)
    raise AssertionError(f"the schema has no variant for {command!r}")


def _is_json_type(value: Any, name: str) -> bool:
    """Type check matching JSON Schema's semantics (bool is not an integer)."""
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    raise AssertionError(f"the test validator does not know {name!r}")


def _accepts(schema: dict[str, Any], value: Any) -> bool:
    """Validate *value* against the subset of JSON Schema this file uses.

    The project does not depend on ``jsonschema``, and adding it just to lock a
    document generated from the same table would test the library, not the
    contract.  This covers exactly the keywords :func:`json_schema` emits.
    """
    if "const" in schema and value != schema["const"]:
        return False
    declared = schema.get("type")
    if declared is not None:
        names = [declared] if isinstance(declared, str) else declared
        if not any(_is_json_type(value, name) for name in names):
            return False
    if "properties" in schema:
        if not isinstance(value, dict):
            return False
        if any(key not in value for key in schema.get("required", ())):
            return False
        properties = schema["properties"]
        if schema.get("additionalProperties") is False and any(
            key not in properties for key in value
        ):
            return False
        return all(
            _accepts(properties[key], item)
            for key, item in value.items()
            if key in properties
        )
    if declared == "array":
        return all(_accepts(schema.get("items", {}), item) for item in value)
    return True


def _write_wav(path: Path) -> Path:
    """Write a short silent WAV the scanners will accept as a file."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 400)
    return path


def _write_cue(path: Path) -> Path:
    """Write a minimal two-track CUE sheet."""
    path.write_text(
        'PERFORMER "Artist"\n'
        'TITLE "Album"\n'
        'FILE "image.wav" WAVE\n'
        "  TRACK 01 AUDIO\n"
        '    TITLE "One"\n'
        '    PERFORMER "Artist"\n'
        "    INDEX 01 00:00:00\n"
        "  TRACK 02 AUDIO\n"
        '    TITLE "Two"\n'
        "    INDEX 01 00:03:00\n",
        encoding="utf-8",
    )
    return path


#: Commands whose real run is not a plain "scan this folder" call.  Each entry
#: says why, so an exclusion cannot become a silent hole.
_RUN_NOTES: dict[str, str] = {
    "cd-rip": "needs an audio CD drive; its payload builders are locked below",
}

#: Commands that would query a web service if given an audio file.  Their
#: schema is proved on an empty directory instead of in a network test.
_EMPTY_LIBRARY = frozenset({"album-art", "lyrics"})


def _argv_for(command: str, work: Path) -> list[str]:
    """Build the CLI arguments for one command's integration run."""
    library = work / "library"
    library.mkdir(exist_ok=True)
    wav = library / "track.wav"
    if not wav.exists():
        _write_wav(wav)
    out = work / "out"
    out.mkdir(exist_ok=True)

    # ``doctor`` inspects the install, not a library: it takes no arguments,
    # and its payload is valid whether this checkout is healthy or not.
    if command == "doctor":
        return []

    # These commands reach a web service when a file is present.  The schema
    # does not need a lookup to be proved, so they scan an empty directory.
    if command in _EMPTY_LIBRARY:
        empty = work / "empty"
        empty.mkdir(exist_ok=True)
        return [str(empty), "--dry"]

    if command == "stats":
        return [str(library)]
    if command == "tag-edit":
        return [str(wav), "--field", "genre", "--value", "Rock", "--dry"]
    if command == "spectrogram":
        return [str(library), "--dry"]
    if command == "cue parse":
        return [str(_write_cue(work / "album.cue"))]
    if command == "cue generate":
        # No dry mode: the run writes a sheet, so point it at the temp tree
        # instead of letting the default put ``album.cue`` in the library.
        return [
            str(library),
            "--output",
            str(out / "album.cue"),
            "--title",
            "Album",
        ]
    if command == "cue split":
        return [str(_write_cue(work / "album.cue")), "--output-dir", str(out)]
    if command in {"enhance", "reorganize"}:
        return [str(library), "--dry", "--output-dir", str(out)]
    if command == "fingerprint":
        # A lookup without an API key is a usage error, not a payload.
        return [str(library), "--dry", "--no-lookup"]
    return [str(library), "--dry"]


class TestRegistryCoverage:
    """Every CLI command's JSON behaviour is declared, none silently added."""

    def test_every_json_command_has_a_schema(self) -> None:
        missing = [
            path
            for path, command in _walk_commands(cli)
            if "--json" in _option_names(command) and path not in TOOL_IDS
        ]
        assert not missing, (
            "these commands emit JSON without a schema in "
            f"audio_suite_shared/cli_schema.py: {missing}"
        )

    def test_no_schema_is_stale(self) -> None:
        registered = {path for path, _command in _walk_commands(cli)}
        stale = sorted(set(TOOL_IDS) - registered)
        assert not stale, f"schemas for commands that do not exist: {stale}"

    def test_commands_without_json_are_declared(self) -> None:
        without_json = {
            path
            for path, command in _walk_commands(cli)
            if "--json" not in _option_names(command)
        }
        assert without_json == set(NO_JSON_COMMANDS), (
            "a command gained or lost --json without updating "
            f"NO_JSON_COMMANDS: {sorted(without_json)}"
        )

    def test_the_no_json_exception_list_is_empty(self) -> None:
        """Every registered command publishes JSON; an exception is an edit.

        ``cue generate`` was the last entry (PLAN D95).  Asserting emptiness
        separately from the coverage equality above keeps the intent explicit:
        adding a declared exception has to break a test whose name says so.
        """
        assert NO_JSON_COMMANDS == {}, (
            "NO_JSON_COMMANDS is no longer empty; a command without --json is "
            f"a deliberate decision, not a gap: {dict(NO_JSON_COMMANDS)}"
        )

    def test_tool_ids_match_the_manifest(self) -> None:
        for manifest in get_registry().all:
            if not manifest.cli_command:
                continue
            assert TOOL_IDS[manifest.cli_command] == manifest.id, (
                f"{manifest.cli_command!r} must publish tool id {manifest.id!r}"
            )

    def test_schema_version_is_pinned(self) -> None:
        assert SCHEMA_VERSION == 1


class TestBuildPayload:
    """The builder, not each tool, decides what the core payload looks like."""

    def test_core_keys_are_complete_and_ordered(self) -> None:
        payload = build_payload("bpm", dry_run=True, total=3, processed=2)

        assert list(payload) == list(CORE_TYPES)

    def test_succeeded_is_derived_from_the_other_counts(self) -> None:
        """The one number scripts need is computed once, not per tool."""
        payload = build_payload(
            "bpm", dry_run=False, total=5, processed=4, skipped=1, errors=1
        )

        assert payload["succeeded"] == 2

    def test_succeeded_never_goes_negative(self) -> None:
        payload = build_payload("bpm", dry_run=False, processed=0, errors=1)

        assert payload["succeeded"] == 0

    def test_duration_is_rounded_and_formatted(self) -> None:
        payload = build_payload("bpm", dry_run=False, duration_secs=12.4449)

        assert payload["duration_secs"] == 12.445
        assert payload["duration_str"] == "12.4s"

    def test_tool_specific_fields_are_published_at_the_top_level(self) -> None:
        payload = build_payload(
            "bpm",
            dry_run=False,
            skipped_files=[{"filename": "noise.wav"}],
        )

        assert payload["skipped_files"] == [{"filename": "noise.wav"}]
        assert "extra" not in payload

    def test_undeclared_field_is_refused(self) -> None:
        """A new field must be declared before it can reach a consumer."""
        with pytest.raises(ValueError, match="undeclared JSON field"):
            build_payload("bpm", dry_run=False, made_up=True)

    def test_unknown_command_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no JSON schema"):
            build_payload("not-a-command", dry_run=False)

    def test_error_payload_keeps_the_core_shape(self) -> None:
        payload = error_payload("stats", "scan failed")

        assert payload["errors"] == 1
        assert payload["error"] == "scan failed"
        assert validate_payload("stats", payload) == []

    @pytest.mark.parametrize(
        "mutation",
        [
            {"processed": "2"},
            {"total": True},
            {"log_entries": "one line"},
            {"tool": "not_the_tool"},
            {"command": "key"},
            {"schema_version": 99},
            {"error": 1},
            {"made_up": 1},
        ],
    )
    def test_validation_catches_drift(self, mutation: dict[str, Any]) -> None:
        payload = build_payload("bpm", dry_run=False)
        payload.update(mutation)

        assert validate_payload("bpm", payload), f"{mutation} passed validation"

    def test_missing_core_key_is_reported(self) -> None:
        payload = build_payload("bpm", dry_run=False)
        del payload["processed"]

        problems = validate_payload("bpm", payload)

        assert any("processed" in problem for problem in problems)

    def test_every_command_accepts_the_universal_error_field(self) -> None:
        for command in cli_schema.commands():
            payload = error_payload(command, "boom")
            assert validate_payload(command, payload) == [], command


class TestJsonSchemaDocument:
    """The committed artifact external validators read is generated, not typed."""

    def _document(self) -> dict[str, Any]:
        return _committed_schema()

    def test_committed_file_matches_the_generator(self) -> None:
        committed = (
            Path(__file__).resolve().parents[1]
            / "audio_suite_shared"
            / "cli_schema.json"
        ).read_text(encoding="utf-8")

        assert committed == schema_json(), (
            "audio_suite_shared/cli_schema.json is stale; regenerate it from "
            "audio_suite_shared.cli_schema.schema_json()"
        )

    def test_one_variant_per_command(self) -> None:
        document = self._document()

        assert document["$schema"].endswith("draft/2020-12/schema")
        assert len(document["oneOf"]) == len(TOOL_IDS)
        commands = {
            variant["properties"]["command"]["const"] for variant in document["oneOf"]
        }
        assert commands == set(TOOL_IDS)

    def test_every_variant_requires_the_core_keys_and_carries_error(self) -> None:
        document = self._document()

        for command in TOOL_IDS:
            variant = _schema_variant(document, command)
            assert variant["required"] == list(CORE_TYPES)
            assert variant["additionalProperties"] is False
            error_types = variant["properties"]["error"]["type"]
            declared = [error_types] if isinstance(error_types, str) else error_types
            assert "string" in declared, command

    def test_the_flag_prints_the_committed_document(self) -> None:
        result = CliRunner().invoke(cli, ["--json-schema"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout) == self._document()
        assert "--json-schema" in CliRunner().invoke(cli, ["--help"]).output


class TestCdRipPayloads:
    """cd-rip cannot run without a drive; lock its payloads directly."""

    def test_rip_payload_reports_attempts_and_failures(self) -> None:
        from cd_ripper.cli import _rip_payload

        payload = _rip_payload(
            drive="D:",
            output_dir="/out",
            fmt="flac",
            tracks="all",
            verify_mode="twice",
            dry_run=False,
            log_entries=["track 1 done\n"],
            succeeded=2,
            failed=1,
            duration_secs=9.5,
        )

        assert validate_payload("cd-rip", payload) == []
        assert payload["total"] == payload["processed"] == 3
        assert payload["errors"] == 1
        assert payload["read_offset_frames"] is None

    def test_offset_payload_is_the_same_shape(self) -> None:
        from cd_ripper.cli import _offset_payload

        payload = _offset_payload(drive="D:", offset=6)

        assert validate_payload("cd-rip", payload) == []
        assert payload["read_offset_frames"] == 6


class TestEveryCommandEmitsTheSchema:
    """Drive each command for real and validate the bytes on stdout."""

    @pytest.fixture()
    def work(self, tmp_path: Path) -> Path:
        work = tmp_path / "run"
        work.mkdir()
        return work

    def _invoke(
        self,
        command: str,
        argv: list[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[int, str]:
        if command == "mood-analysis-batch":
            from mood_analysis_batch_tagger.core import batch_analysis_engine

            def fake_run_batch(**_kwargs: Any) -> None:
                _kwargs["out_queue"].put(("done", 2, 1, 0, 1, "runs/fake.log"))

            monkeypatch.setattr(batch_analysis_engine, "run_batch", fake_run_batch)
        if command == "cue split":
            import audio_suite_shared.cue_cli as cue_cli

            monkeypatch.setattr(cue_cli, "split_cue_file", lambda *_a, **_k: [])

        # A nested path (``cue parse``) is two argv tokens, not one name.
        result = CliRunner().invoke(cli, [*command.split(), *argv, "--json"])
        return result.exit_code, result.stdout

    @pytest.mark.parametrize(
        "command",
        sorted(set(TOOL_IDS) - set(_RUN_NOTES)),
    )
    def test_payload_matches_the_declared_schema(
        self,
        command: str,
        work: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        argv = _argv_for(command, work)
        exit_code, stdout = self._invoke(command, argv, monkeypatch)

        assert exit_code in (0, 1), f"{command} exited {exit_code}"
        assert stdout.strip(), f"{command} wrote no JSON to stdout"
        payload = json.loads(stdout)

        assert validate_payload(command, payload) == [], (
            f"{command} payload drifted from schema v{SCHEMA_VERSION}"
        )
        assert payload["command"] == command
        assert payload["tool"] == TOOL_IDS[command]
        assert payload["dry_run"] is ("--dry" in argv)
        # The committed JSON Schema must accept the same bytes a script sees;
        # validating only against validate_payload could leave the artifact
        # stale in exactly the way an external consumer would notice.
        variant = _schema_variant(_committed_schema(), command)
        assert _accepts(variant, payload), (
            f"{command} payload is rejected by its committed JSON Schema variant"
        )
        # Every declared tool-specific field is optional, but the ones a run
        # does publish must be declared (build_payload already refuses the
        # rest); assert the extras set is a subset for a readable failure.
        assert set(payload) - set(CORE_TYPES) <= set(extras_for(command)) | {"error"}
