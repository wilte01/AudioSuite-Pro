"""Lock the failure contract of every ``--json`` command (S5-1, plan D91).

A script that reads stdout must not receive nothing when a command fails before
it does any work.  Before this lock every schema command exited 2 with an empty
stdout for a usage error (missing argument, missing required option, invalid
value, unknown option), so the only way to learn why was to scrape Click's
stderr - the coupling ``cli_schema`` exists to remove.

Five layers:

1. *Helpers* — the argv readers behind the group handler (``--json``/``--text``
   and ``--dry``/``--live`` are last-one-wins, the ``cue`` sub-group needs its
   subcommand) and the decision that suppresses a second document.
2. *Reality* — every command in :data:`TOOL_IDS` is invoked with a real usage
   error, in JSON mode and in text mode.  JSON mode must exit 2, parse, and
   validate against the command's schema; text mode must keep stdout empty.
3. *Run failures* — a ``ClickException`` raised by a command body keeps its
   exit, so ``cue parse`` on a corrupt sheet is machine-readable too.
4. *Body-level value guards* and *pre-payload run failures* — the six places
   that validated an option value or hit a fatal error after Click had already
   parsed the command line (D91a), which used to leave stdout empty.
5. *One document only* — a command that prints its own payload and then exits
   non-zero must not get a second one from the group handler.

The table is asserted to cover exactly ``set(TOOL_IDS)``: a command that joins
the schema without a usage case fails here, which is what kept S5-4 honest when
``cue generate`` gained ``--json``.  ``doctor`` (S5-2) brings the two usage
errors a command with no input can still raise - an unknown option and a stray
positional - because Click rejects the invocation before any body runs.

Changed in 1.4.1: added for S5-1 (PLAN D91), extended for ``doctor`` (D93) and
``cue generate`` (D95).

Changed in 2.0.0: adds the ``stems`` case with the Stem Separator's schema
entry (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import json
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from audio_suite_shared.cli_app import cli
from audio_suite_shared.cli_base import (
    RunFailure,
    _argv_is_dry_run,
    _argv_wants_json,
    _command_path,
    _failure_document,
)
from audio_suite_shared.cli_schema import TOOL_IDS, validate_payload

#: Placeholders filled per test, so no case depends on a real library.
LIBRARY = "{library}"
MISSING_PATH = "{missing_path}"

#: One usage-error invocation per schema command.  ``missing`` omits the
#: required input; ``invalid`` supplies a value Click must reject before the
#: command body runs.  ``enhance``/``reorganize`` omit their required
#: ``--output-dir``, and ``cd-rip`` omits it after the drive argument, which
#: the command raises itself (both are still usage errors, exit 2).
_USAGE_CASES: dict[str, dict[str, list[str]]] = {
    "album-art": {"missing": [], "invalid": [MISSING_PATH]},
    "album-genre": {"missing": [], "invalid": [MISSING_PATH]},
    "artnormalize": {"missing": [], "invalid": [MISSING_PATH]},
    "asx-extract": {"missing": [], "invalid": [MISSING_PATH]},
    "bpm": {"missing": [], "invalid": [MISSING_PATH]},
    "cd-rip": {"missing": ["Z:"], "invalid": ["Z:", "--verify", "bogus"]},
    "convert": {"missing": [], "invalid": [LIBRARY, "--sample-rate", "bogus"]},
    "cue generate": {"missing": [], "invalid": [MISSING_PATH]},
    "cue parse": {"missing": [], "invalid": [MISSING_PATH]},
    "cue split": {"missing": [], "invalid": [MISSING_PATH]},
    "declick": {"missing": [], "invalid": [MISSING_PATH]},
    # ``denoise`` has no required option; ``--amount`` is a bounded float, so a
    # percentage outside 1-100 is rejected before the body runs.
    "denoise": {"missing": [], "invalid": [LIBRARY, "--amount", "0"]},
    # ``doctor`` takes no input, so the two reachable usage errors are the
    # invocation itself: an option it does not know and a positional it does
    # not accept.  Both must publish a document like every other command.
    "doctor": {"missing": ["--no-such-option"], "invalid": ["stray-argument"]},
    "enhance": {"missing": [LIBRARY], "invalid": [MISSING_PATH]},
    "fingerprint": {"missing": [], "invalid": [LIBRARY, "--mb-auth", "bogus"]},
    "genre-sync": {"missing": [], "invalid": [MISSING_PATH]},
    "key": {"missing": [], "invalid": [MISSING_PATH]},
    "lyrics": {"missing": [], "invalid": [MISSING_PATH]},
    "mood-analysis-batch": {"missing": [], "invalid": [MISSING_PATH]},
    "mood-analyzer": {"missing": [], "invalid": [MISSING_PATH]},
    "normalise": {"missing": [], "invalid": [LIBRARY, "--mode", "bogus"]},
    "reduce": {"missing": [], "invalid": [LIBRARY, "--hum-frequency", "42"]},
    "refine": {"missing": [], "invalid": [MISSING_PATH]},
    "reorganize": {"missing": [LIBRARY], "invalid": [MISSING_PATH]},
    "replaygain": {"missing": [], "invalid": [MISSING_PATH]},
    "scrub": {"missing": [], "invalid": [MISSING_PATH]},
    "silence-trim": {"missing": [], "invalid": [MISSING_PATH]},
    "spectrogram": {"missing": [], "invalid": [MISSING_PATH]},
    "stats": {"missing": [], "invalid": [LIBRARY, "--detail", "bogus"]},
    # ``stems`` requires ``--output-dir``, so the bare invocation is already a
    # usage error; ``--model`` is a Choice, rejected before the body runs.
    "stems": {"missing": [], "invalid": [LIBRARY, "--model", "bogus"]},
    "tag-edit": {"missing": [], "invalid": [MISSING_PATH]},
    "tag-update": {"missing": [], "invalid": [MISSING_PATH]},
    "tempo": {"missing": [], "invalid": [MISSING_PATH]},
}


def _argv(command: str, case: str, tmp_path: Path) -> list[str]:
    """Return the real argv for one table entry, with placeholders resolved."""
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    missing = str(tmp_path / "does-not-exist.mp3")
    tokens = [
        token.replace(LIBRARY, str(library)).replace(MISSING_PATH, missing)
        for token in _USAGE_CASES[command][case]
    ]
    return [*command.split(), *tokens]


def _invoke(argv: list[str]) -> tuple[int, str, str]:
    """Run the real CLI and return ``(exit_code, stdout, stderr)``."""
    result = CliRunner().invoke(cli, argv)
    return result.exit_code, result.stdout, result.stderr


class TestArgvHelpers:
    """The group handler reads the invocation the way Click parses it."""

    def test_json_is_last_one_wins(self) -> None:
        assert _argv_wants_json(["--json"])
        assert not _argv_wants_json(["--json", "--text"])
        assert _argv_wants_json(["--text", "--json"])

    def test_dry_is_last_one_wins(self) -> None:
        assert _argv_is_dry_run(["--dry"])
        assert not _argv_is_dry_run(["--dry", "--live"])
        assert _argv_is_dry_run(["--live", "--dry"])

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["bpm", "/music", "--json"], "bpm"),
            (["--log-level", "DEBUG", "bpm", "/music"], "bpm"),
            (["--log-level=INFO", "key", "/music"], "key"),
            (["cue", "parse", "album.cue"], "cue parse"),
            (["cue", "generate", "/music"], "cue generate"),
            (["--json-schema"], None),
            (["--json"], None),
            ([], None),
        ],
    )
    def test_the_command_path_is_resolved(
        self, argv: list[str], expected: str | None
    ) -> None:
        assert _command_path(argv) == expected


class TestFailureDocument:
    """What the handler publishes, independent of the command that raised."""

    def test_a_usage_error_becomes_a_valid_payload(self) -> None:
        exc = click.UsageError("Missing argument 'DIRECTORY'.")

        document = _failure_document(["--dry", "bpm", "--json"], exc)

        assert document is not None
        assert document["dry_run"] is True
        assert document["errors"] == 1
        assert "DIRECTORY" in document["error"]
        assert validate_payload("bpm", document) == []

    def test_text_mode_publishes_nothing(self) -> None:
        assert _failure_document(["bpm"], click.UsageError("boom")) is None

    def test_a_command_outside_the_schema_publishes_nothing(self) -> None:
        exc = click.UsageError("boom")
        assert _failure_document(["not-a-command", "--json"], exc) is None

    def test_an_already_reported_failure_publishes_nothing(self) -> None:
        exc = RunFailure("already printed", already_reported=True)
        assert _failure_document(["bpm", "--json"], exc) is None

    def test_a_run_failure_publishes_its_message(self) -> None:
        exc = RunFailure("could not open the drive")

        document = _failure_document(["cd-rip", "Z:", "--json"], exc)

        assert document is not None
        assert document["error"] == "could not open the drive"
        assert validate_payload("cd-rip", document) == []


class TestEverySchemaCommand:
    """Each command's usage errors are machine-readable in JSON mode."""

    def test_the_table_covers_exactly_the_schema_commands(self) -> None:
        """A command that joins the schema must bring its usage cases."""
        assert set(_USAGE_CASES) == set(TOOL_IDS), (
            "the usage-error table and cli_schema.TOOL_IDS diverged: "
            f"missing={sorted(set(TOOL_IDS) - set(_USAGE_CASES))} "
            f"stale={sorted(set(_USAGE_CASES) - set(TOOL_IDS))}"
        )

    @pytest.mark.parametrize("command", sorted(_USAGE_CASES))
    @pytest.mark.parametrize("case", ["missing", "invalid"])
    def test_usage_error_exits_2_with_a_valid_payload(
        self, command: str, case: str, tmp_path: Path
    ) -> None:
        argv = _argv(command, case, tmp_path)

        exit_code, stdout, stderr = _invoke([*argv, "--json"])

        assert exit_code == 2, f"{argv}: exit {exit_code}, stderr={stderr!r}"
        assert stdout.strip(), f"{argv}: no JSON document on stdout"
        payload = json.loads(stdout)
        assert validate_payload(command, payload) == [], (
            f"{command} usage payload drifted: {payload}"
        )
        assert payload["command"] == command
        assert payload["tool"] == TOOL_IDS[command]
        assert payload["errors"] == 1
        assert payload["error"], "the payload must say why the run failed"
        assert stderr.strip(), "the human explanation must stay on stderr"

    @pytest.mark.parametrize("command", sorted(_USAGE_CASES))
    def test_text_mode_keeps_stdout_empty(self, command: str, tmp_path: Path) -> None:
        argv = _argv(command, "missing", tmp_path)

        exit_code, stdout, stderr = _invoke(argv)

        assert exit_code == 2
        assert stdout.strip() == "", f"{argv}: text mode wrote to stdout"
        assert stderr.strip(), "text mode must still explain the failure"

    @pytest.mark.parametrize("command", sorted(_USAGE_CASES))
    def test_json_then_text_is_text_mode(self, command: str, tmp_path: Path) -> None:
        """The last of the shared pair wins, exactly as Click parses it."""
        argv = _argv(command, "missing", tmp_path)

        exit_code, stdout, stderr = _invoke([*argv, "--json", "--text"])

        assert exit_code == 2
        assert stdout.strip() == ""
        assert stderr.strip()


class TestRunFailures:
    """A command body that raises keeps the payload and its exit status."""

    @staticmethod
    def _corrupt_cue(tmp_path: Path) -> Path:
        cue = tmp_path / "bad.cue"
        cue.write_text("TRACK 01 AUDIO\n", encoding="utf-8")
        return cue

    def test_a_click_exception_carries_the_payload(self, tmp_path: Path) -> None:
        cue = self._corrupt_cue(tmp_path)

        exit_code, stdout, stderr = _invoke(["cue", "parse", str(cue), "--json"])

        assert exit_code == 1
        payload = json.loads(stdout)
        assert validate_payload("cue parse", payload) == []
        assert payload["errors"] == 1
        assert payload["error"]
        assert "Error:" in stderr

    def test_a_click_exception_in_text_mode_writes_no_document(
        self, tmp_path: Path
    ) -> None:
        cue = self._corrupt_cue(tmp_path)

        exit_code, stdout, stderr = _invoke(["cue", "parse", str(cue)])

        assert exit_code == 1
        assert stdout.strip() == ""
        assert "Error:" in stderr

    def test_the_group_flags_are_untouched(self) -> None:
        """``--json-schema`` and ``--help`` still exit before any command."""
        schema_code, schema_out, _ = _invoke(["--json-schema"])
        assert schema_code == 0
        assert json.loads(schema_out)["oneOf"]

        help_code, help_out, _ = _invoke(["--help"])
        assert help_code == 0
        assert "Usage:" in help_out


class TestBodyUsageErrors:
    """A value guard in a command body is a usage error, not a silent exit.

    These five branches validated an option *value* after Click had already
    accepted the syntax, and each echoed a line and called ``sys.exit``: JSON
    consumers got exit 1 (or, for an all-invalid ``--tracks`` list, exit 0)
    with an empty stdout.  Raising ``click.UsageError`` routes them through the
    group handler, which exits 2 and publishes the error document.
    """

    #: (argv before ``--json``, command key, expected message fragment)
    _CASES = [
        (
            ["enhance", LIBRARY, "--output-dir", "{out}", "--preset", "Nope"],
            "enhance",
            "Unknown preset",
        ),
        (["convert", LIBRARY, "--preset", "nope"], "convert", "Unknown preset"),
        (["convert", LIBRARY, "--format", "xyz"], "convert", "Unsupported format"),
        (["tempo", LIBRARY, "--scheme", "nope"], "tempo", "Unknown scheme"),
        (
            ["cd-rip", "Z:", "--output-dir", "{out}", "--tracks", "abc,!!"],
            "cd-rip",
            "No valid track numbers",
        ),
    ]

    @staticmethod
    def _resolve(argv: list[str], tmp_path: Path) -> list[str]:
        """Fill the placeholders with directories that really exist."""
        library = tmp_path / "library"
        library.mkdir(exist_ok=True)
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        return [
            token.replace(LIBRARY, str(library)).replace("{out}", str(out))
            for token in argv
        ]

    @pytest.mark.parametrize(("argv", "command", "fragment"), _CASES)
    def test_a_bad_value_exits_2_with_a_valid_payload(
        self, argv: list[str], command: str, fragment: str, tmp_path: Path
    ) -> None:
        resolved = self._resolve(argv, tmp_path)

        exit_code, stdout, stderr = _invoke([*resolved, "--json"])

        assert exit_code == 2, f"{resolved}: exit {exit_code}, stderr={stderr!r}"
        payload = json.loads(stdout)
        assert validate_payload(command, payload) == []
        assert payload["errors"] == 1
        assert fragment in payload["error"]
        assert fragment in stderr

    @pytest.mark.parametrize(("argv", "command", "fragment"), _CASES)
    def test_a_bad_value_in_text_mode_writes_no_document(
        self, argv: list[str], command: str, fragment: str, tmp_path: Path
    ) -> None:
        resolved = self._resolve(argv, tmp_path)

        exit_code, stdout, stderr = _invoke(resolved)

        assert exit_code == 2
        assert stdout.strip() == "", f"{resolved}: text mode wrote to stdout"
        assert fragment in stderr


class TestFatalRuns:
    """A run that dies before any payload still explains itself in JSON."""

    def test_a_fatal_scan_failure_is_a_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom(*_args: object, **_kwargs: object) -> None:
            raise OSError("the drive went away")

        monkeypatch.setattr("library_stats.library_stats.scan_directory", _boom)
        library = tmp_path / "library"
        library.mkdir()

        exit_code, stdout, stderr = _invoke(["stats", str(library), "--json"])

        assert exit_code == 1
        payload = json.loads(stdout)
        assert validate_payload("stats", payload) == []
        assert payload["errors"] == 1
        assert payload["error"] == "FATAL: the drive went away"
        assert "FATAL" in stderr

    def test_an_empty_directory_is_a_document(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()

        exit_code, stdout, stderr = _invoke(["spectrogram", str(empty), "--json"])

        assert exit_code == 1
        payload = json.loads(stdout)
        assert validate_payload("spectrogram", payload) == []
        assert "No supported audio files" in payload["error"]
        assert "No supported audio files" in stderr


class TestOneDocumentOnly:
    """A body that already published a payload does not get a second one.

    ``cd-rip`` writes its own payload and then raises
    ``RunFailure(already_reported=json_output)``.  If the group handler ignored
    that flag, stdout would carry two concatenated JSON documents and every
    ``json.loads`` consumer would break on a *correct* payload - so the guard is
    locked here through the real command, not just the helper.
    """

    @staticmethod
    def _fatal_session(**_kwargs: object) -> object:
        """Stand-in for ``RipSession`` that fails before ripping anything."""

        class _FatalSession:
            fatal_error = "Cannot open the CD drive"

            def start(self) -> None:
                session_done_cb = _kwargs["session_done_cb"]
                assert callable(session_done_cb)
                session_done_cb()

        return _FatalSession()

    def test_a_fatal_rip_emits_exactly_one_document(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("cd_ripper.core.ripper.RipSession", self._fatal_session)

        exit_code, stdout, stderr = _invoke(
            ["cd-rip", "Z:", "--output-dir", str(tmp_path), "--json"]
        )

        assert exit_code == 1
        payload = json.loads(stdout)  # fails loudly if two documents were glued
        assert stdout.count('"schema_version"') == 1
        assert validate_payload("cd-rip", payload) == []
        assert payload["errors"] == 1
        # The command's own payload is the one that survives; the raise only
        # supplies the exit status and the stderr line.
        assert payload["error"] == "Cannot open the CD drive"
        assert "Error: Rip session failed: Cannot open the CD drive" in stderr
