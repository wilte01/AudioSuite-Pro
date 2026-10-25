"""Registry-wide lock: every CLI command can report a non-zero exit status.

Audit finding R-06 (``PLAN_audit_2026-10-24_remediation.md`` C1) was that
``audiosuite convert`` printed ``1 errors`` and returned normally, so a shell or
scheduler could not tell a clean run from one that converted nothing.  The
fix - ``finish_run`` / ``finish_batch`` (PLAN D9, D22) - only helps the commands
that call it, and several commands build their own payload.  A behavioural sweep
over every command with a deliberately failing input is not a unit test, so this
lock asserts the *static* half: every command reachable from the group either has
a statement that can set a non-zero status (a contract helper, an explicit
``exit``, or a raised ``ClickException``/``SystemExit``) or is listed in
:data:`EXEMPT` with a reason.

The body scan follows a call into another function **in the same module**, because
``plugins enable`` delegates to ``_run_toggle`` and the raise lives there; it does
not follow into other modules, whose status handling is that module's contract.

The exemption table is checked in both directions, so it cannot rot: a stale entry
(the command gained a status path) fails, and an unlisted command with no status
path fails.  The commands this item changed are also proven behaviourally in their
own suites - ``tag_field_updater/tests/test_cli.py``,
``mood_analysis_batch_tagger/tests/test_cli.py``, ``music_format_converter/
tests/test_cli.py`` and ``cd_ripper/tests/test_cli.py`` - so this file is the net,
not the only evidence.

Changed in 2.1.4: initial version (plan item C1, decision D22).
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from collections.abc import Iterator
from pathlib import Path

import click

# Importing cli_app registers every first-party command on the shared group.
from audio_suite_shared.cli_app import cli
from audio_suite_shared.cli_schema import TOOL_IDS

#: Calls that apply the shared exit contract.
_CONTRACT_CALLS = frozenset({"finish_run", "finish_batch"})

#: Call/raise names that set a non-zero status without the shared helper.
_EXIT_CALLS = frozenset({"exit"})
_EXCEPTION_NAMES = frozenset(
    {
        "SystemExit",
        "Abort",
        "ClickException",
        "RunFailure",
        "UsageError",
        "BadParameter",
        "MissingParameter",
        "NoSuchOption",
    }
)

#: Commands with no exit-status path, each with the reason it does not need one.
#:
#: Kept as a dict (not a set) so every entry carries its justification into
#: review; ``test_every_exemption_states_a_reason`` asserts none is blank.
EXEMPT: dict[str, str] = {}


def _commands() -> Iterator[tuple[str, click.Command]]:
    """Yield every non-group command reachable from the group, with its path.

    A group's own callback only dispatches, so the status contract lives in its
    subcommands; those are yielded as ``"cue parse"``-style paths, which is also
    how the JSON schema keys them.
    """
    for name, command in sorted(cli.commands.items()):
        if isinstance(command, click.Group):
            for sub_name, sub_command in sorted(command.commands.items()):
                yield f"{name} {sub_name}", sub_command
        else:
            yield name, command


def _same_module_functions(source_file: Path) -> dict[str, ast.AST]:
    """Return every function defined at module level in *source_file*, by name."""
    tree = ast.parse(source_file.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }


def _status_paths(command: click.Command) -> tuple[set[str], set[str]]:
    """Return the contract calls and the exit paths a command's body contains.

    Follows calls into other functions of the same module, so a command whose
    ``raise`` lives in its private helper is still credited with one.
    """
    callback = command.callback
    if callback is None:  # pragma: no cover - every command has one
        return set(), set()
    source_file = Path(inspect.getsourcefile(callback) or "")
    functions = _same_module_functions(source_file)
    start = callback.__name__
    functions.setdefault(start, ast.parse(textwrap.dedent(inspect.getsource(callback))))

    contract: set[str] = set()
    exits: set[str] = set()
    seen: set[str] = set()
    pending = [start]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        body = functions.get(name)
        if body is None:
            continue
        for node in ast.walk(body):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in _CONTRACT_CALLS:
                    contract.add(func.id)
                elif isinstance(func, ast.Name) and func.id in _EXIT_CALLS:
                    exits.add(func.id)
                elif isinstance(func, ast.Attribute) and func.attr in _EXIT_CALLS:
                    exits.add(func.attr)
                elif isinstance(func, ast.Name) and func.id in functions:
                    pending.append(func.id)
            elif isinstance(node, ast.Raise) and node.exc is not None:
                exc = node.exc
                exc = exc.func if isinstance(exc, ast.Call) else exc
                if isinstance(exc, ast.Name) and exc.id in _EXCEPTION_NAMES:
                    exits.add(f"raise {exc.id}")
                elif isinstance(exc, ast.Attribute) and exc.attr in _EXCEPTION_NAMES:
                    exits.add(f"raise {exc.attr}")
    return contract, exits


def _is_plugin_command(command: click.Command) -> bool:
    """Whether *command* is the host-generated wrapper for a plugin tool."""
    callback = command.callback
    return (
        callback is not None
        and getattr(callback, "__name__", "") == "_plugin_entry"
        and getattr(callback, "__module__", "") == "audio_suite_shared.cli_app"
    )


class TestRegistryIsEnumerated:
    """A scan that finds nothing must fail rather than pass vacuously."""

    def test_every_schema_command_is_discovered(self) -> None:
        commands = dict(_commands())

        missing = sorted(set(TOOL_IDS) - set(commands))
        assert not missing, (
            f"commands declared in the JSON schema are not reachable from the "
            f"group, so the contract scan would skip them: {missing}"
        )
        assert len(commands) >= 37, (
            f"only {len(commands)} commands discovered - cli_app's registration "
            "did not run, so the scan would pass vacuously"
        )

    def test_the_commands_this_item_changed_are_covered(self) -> None:
        commands = dict(_commands())

        assert "tag-update" in commands
        assert "mood-analysis-batch" in commands
        assert "cd-rip" in commands
        assert "plugins list" in commands


class TestEveryCommandCanFail:
    def test_a_command_without_an_exit_path_is_exempt_or_fails(self) -> None:
        missing: list[str] = []
        for name, command in _commands():
            if _is_plugin_command(command):
                continue
            contract, exits = _status_paths(command)
            if contract or exits or name in EXEMPT:
                continue
            missing.append(name)

        assert not missing, (
            "these commands cannot report a failure to the shell - call "
            "finish_run/finish_batch, exit non-zero, raise a ClickException, or "
            "add them to EXEMPT with a reason:\n  " + "\n  ".join(missing)
        )

    def test_the_scan_sees_a_status_path_in_the_commands_it_names(self) -> None:
        """A positive control: the parser finds the call in a known-good body."""
        commands = dict(_commands())

        assert _status_paths(commands["convert"])[0] == {"finish_run"}
        assert _status_paths(commands["tag-update"])[0] == {"finish_batch"}

    def test_a_raise_inside_a_private_helper_counts(self) -> None:
        """``plugins enable`` raises in ``_run_toggle``, not in its own body."""
        command = dict(_commands())["plugins enable"]

        _, exits = _status_paths(command)

        assert exits, "the helper-following scan found no exit path"

    def test_a_command_without_one_is_actually_reported(self) -> None:
        """The scan must be able to fail: a body with no status path reports none."""

        def _silent_command(directory: str) -> None:
            click.echo(directory)

        silent = click.Command("silent", callback=_silent_command)
        contract, exits = _status_paths(silent)

        assert not contract
        assert not exits


class TestExemptionsAreHonest:
    def test_every_exemption_is_a_registered_command(self) -> None:
        names = {name for name, _ in _commands()}

        stale = sorted(set(EXEMPT) - names)
        assert not stale, f"EXEMPT names commands that do not exist: {stale}"

    def test_no_exemption_claims_a_command_that_has_a_status_path(self) -> None:
        """An exempt command that grew a status path must leave the table."""
        commands = dict(_commands())
        stale: list[str] = []
        for name in EXEMPT:
            contract, exits = _status_paths(commands[name])
            if contract or exits:
                stale.append(name)

        assert not stale, (
            "these commands now have an exit-status path and are still exempt:\n  "
            + "\n  ".join(stale)
        )

    def test_every_exemption_states_a_reason(self) -> None:
        for name, reason in EXEMPT.items():
            assert reason.strip(), f"{name} is exempt with no reason"
