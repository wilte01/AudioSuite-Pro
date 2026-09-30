"""Tests for audio_suite_shared.cli_app — unified Click CLI."""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from audio_suite_shared import cli_app as cli_app_module
from audio_suite_shared.cli_app import _run_tool, cli
from audio_suite_shared.tool_plugin import get_registry

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _introspection_context() -> click.Context:
    """A context for reading command metadata *without* invoking the group.

    ``cli`` sets ``no_args_is_help=True``, so ``cli.make_context("audiosuite",
    [])`` renders the help and raises, and ``["--help"]`` raises
    ``click.exceptions.Exit`` for the same reason.  ``resilient_parsing`` is
    the supported way to introspect a group without running it.
    """
    return click.Context(cli, info_name="audiosuite", resilient_parsing=True)


@pytest.fixture
def temp_music_dir(tmp_path: pytest.TempPathFactory) -> str:
    d = tmp_path / "music"
    d.mkdir()
    (d / "track1.mp3").write_bytes(b"fake")
    (d / "track2.flac").write_bytes(b"fake")
    return str(d)


# ── CLI registration ──────────────────────────────────────────────────────────


class TestCliRegistration:
    def test_cli_group_exists(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "AudioSuite-Pro" in result.output

    def test_version(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.startswith("audiosuite, version")

    def test_log_level(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--log-level", "DEBUG", "stats", "--help"])
        assert result.exit_code == 0

    def test_unknown_command(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["nonexistent"])
        assert result.exit_code != 0
        assert "No such command" in result.output


# ── All subcommands: help text and basic parsing ──────────────────────────────


HELP_FLAGS: list[tuple[str, str]] = [
    ("bpm", "Detect and tag BPM"),
    ("key", "Detect and tag musical key"),
    ("tempo", "Derive tempo markings"),
    ("replaygain", "write ReplayGain tags"),
    ("genre-sync", "Sync genre tags"),
    ("normalise", "Normalise audio loudness"),
    ("scrub", "Scrub metadata"),
    ("convert", "Convert audio files"),
    ("silence-trim", "Trim silence"),
    ("declick", "Remove pops and clicks"),
    ("enhance", "Enhance audio"),
    ("stats", "aggregate tag statistics"),
]


class TestSubcommandHelp:
    @pytest.mark.parametrize("command,help_text", HELP_FLAGS)
    def test_subcommand_help(
        self, runner: CliRunner, command: str, help_text: str
    ) -> None:
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0, f"'{command}' --help failed: {result.output}"
        assert help_text.lower() in result.output.lower()

    @pytest.mark.parametrize("command,help_text", HELP_FLAGS)
    def test_subcommand_accepts_directory_argument(
        self,
        runner: CliRunner,
        command: str,
        help_text: str,
        tmp_path: pytest.TempPathFactory,
    ) -> None:
        d = tmp_path / "m"
        d.mkdir()
        # These commands require a directory argument — verify the parser accepts it
        result = runner.invoke(cli, [command, str(d), "--help"])
        assert result.exit_code == 0, (
            f"'{command} <dir> --help' failed: {result.output}"
        )


# ── Dry-run invocations (no actual processing) ────────────────────────────────


class TestDryRunInvocations:
    def test_bpm_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli,
            [
                "bpm",
                temp_music_dir,
                "--dry",
                "--bpm-min",
                "60",
                "--bpm-max",
                "180",
                "--duration",
                "5",
            ],
        )
        # Should complete without error (exit 0 or non-zero depending on mock)
        assert result.exit_code == 0

    def test_key_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["key", temp_music_dir, "--dry", "--duration", "5"])
        assert result.exit_code == 0

    def test_tempo_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli, ["tempo", temp_music_dir, "--dry", "--scheme", "Italian"]
        )
        assert result.exit_code == 0

    def test_replaygain_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli, ["replaygain", temp_music_dir, "--dry", "--target-lufs", "-14"]
        )
        assert result.exit_code == 0

    def test_normalise_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["normalise", temp_music_dir, "--dry"])
        assert result.exit_code == 0

    def test_normalise_json_flag(self, runner: CliRunner, temp_music_dir: str) -> None:
        """--json must emit a JSON summary without failing."""
        result = runner.invoke(cli, ["normalise", temp_music_dir, "--dry", "--json"])
        assert result.exit_code == 0

    def test_scrub_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["scrub", temp_music_dir, "--dry"])
        assert result.exit_code == 0

    def test_declick_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli,
            [
                "declick",
                temp_music_dir,
                "--dry",
                "--sensitivity",
                "0.3",
                "--max-width",
                "5",
            ],
        )
        assert result.exit_code == 0

    def test_silence_trim_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(cli, ["silence-trim", temp_music_dir, "--dry"])
        assert result.exit_code == 0


# ── convert subcommand ────────────────────────────────────────────────────────


class TestConvert:
    def test_convert_dry_run(self, runner: CliRunner, temp_music_dir: str) -> None:
        result = runner.invoke(
            cli, ["convert", temp_music_dir, "--format", "flac", "--dry"]
        )
        assert result.exit_code == 0

    def test_convert_unknown_format(
        self, runner: CliRunner, temp_music_dir: str
    ) -> None:
        result = runner.invoke(
            cli, ["convert", temp_music_dir, "--format", "xyz", "--dry"]
        )
        assert result.exit_code != 0
        assert "Unsupported format" in result.output


# ── enhance subcommand ────────────────────────────────────────────────────────


class TestEnhance:
    def test_enhance_requires_output_dir(
        self, runner: CliRunner, temp_music_dir: str
    ) -> None:
        result = runner.invoke(cli, ["enhance", temp_music_dir])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output

    def test_enhance_unknown_preset(
        self, runner: CliRunner, temp_music_dir: str, tmp_path: pytest.TempPathFactory
    ) -> None:
        out = tmp_path / "out"
        out.mkdir()
        result = runner.invoke(
            cli,
            [
                "enhance",
                temp_music_dir,
                "--output-dir",
                str(out),
                "--preset",
                "Unknown",
            ],
        )
        assert result.exit_code != 0
        assert "Unknown preset" in result.output


# ── stats subcommand ──────────────────────────────────────────────────────────


class TestStats:
    def test_stats_empty_dir(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        result = runner.invoke(cli, ["stats", str(d)])
        assert result.exit_code == 0
        assert "Total files scanned" in result.output

    def test_stats_json_flag(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "empty"
        d.mkdir()
        result = runner.invoke(cli, ["stats", str(d), "--json"])
        assert result.exit_code == 0
        # Output includes a status line on stderr mixed in; extract JSON portion
        import json

        json_start = result.output.index("{")
        data = json.loads(result.output[json_start:])
        assert data["total_files"] == 0
        assert data["scan_path"] == str(d)

    def test_stats_with_audio_files(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "music"
        d.mkdir()
        (d / "a.mp3").write_bytes(b"fake mp3")
        (d / "b.flac").write_bytes(b"fake flac")
        result = runner.invoke(cli, ["stats", str(d)])
        assert result.exit_code == 0
        assert "Total files scanned" in result.output

    def test_stats_non_existent_dir(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["stats", "C:\\nonexistent_path_xyz"])
        assert result.exit_code != 0
        assert "does not exist" in result.output or "Error" in result.output


# ── _run_tool helper ──────────────────────────────────────────────────────────


class TestRunTool:
    def test_run_tool_success(self) -> None:
        def dummy_run(**kwargs: object) -> None:
            cb = kwargs.get("on_progress")
            if cb:
                cb(processed=5, total=10)
            cb2 = kwargs.get("on_complete")
            if cb2:
                cb2(
                    total=10,
                    processed=5,
                    skipped=2,
                    errors=1,
                    duration_secs=2.5,
                    log_entries=[],
                )

        result = _run_tool("test", dummy_run, some_arg="value")
        assert result.total == 10
        assert result.processed == 5
        assert result.skipped == 2
        assert result.errors == 1

    def test_run_tool_error_callback(self) -> None:

        def dummy_run(**kwargs: object) -> None:
            cb = kwargs.get("on_error")
            if cb:
                cb("Something broke")

        result = _run_tool("test", dummy_run)
        # on_error only prints to stderr; it does not modify result.errors
        assert result.errors == 0

    def test_run_tool_exception(self) -> None:
        def dummy_run(**kwargs: object) -> None:
            raise RuntimeError("catastrophe")

        result = _run_tool("test", dummy_run)
        assert result.errors == -1

    def test_run_tool_json_output(self, runner: CliRunner) -> None:
        import json

        def dummy_run(**kwargs: object) -> None:
            cb = kwargs.get("on_complete")
            if cb:
                cb(
                    total=5,
                    processed=3,
                    skipped=1,
                    errors=1,
                    duration_secs=1.0,
                    log_entries=[],
                )

        result = _run_tool("test", dummy_run)
        d = result.to_dict()
        assert d["total"] == 5
        assert d["processed"] == 3
        assert isinstance(d["duration_str"], str)
        # Verify JSON serializable
        json.dumps(d)


# ── G2: the discoverability contract (plan iteration 5, audit #21) ─────────────
#
# The manifest is the single source of truth for "which tool is which".  These
# tests are the enforceable half of the AGENTS.md "Registering a New Tool"
# checklist: a tool that is missing its CLI subcommand, its discoverable help,
# or its group in `audiosuite --help` fails here.
#
# Split of responsibility (recorded as a Stage 6 decision):
#   * this module owns the *runtime* CLI surface — the subcommand resolves,
#     `--help` renders, the command is grouped in the top-level help, and
#     `--version` agrees with pyproject.toml.
#   * tests/test_readme.py (item E1) owns the *static* surfaces — launcher
#     .pyw, Master Driver card module (including the embedded-tab exception),
#     and the guide_to_program entry plus the .docx artifact.
# E1's card-overrides registry is deliberately not duplicated here, so there
# is still only one source for the card naming rule.


class TestDiscoverabilityContract:
    """Manifest ↔ CLI, declared once and checked in one loop."""

    #: Tools with no CLI subcommand, each with the reason it is acceptable.
    #: This is the "existing gaps are listed, not silently grandfathered"
    #: rule from plan G2: a *new* tool without a subcommand fails the
    #: test_no_undeclared_gap_below test.
    NO_CLI_TOOLS: dict[str, str] = {
        "undo_tag_edits": (
            "GUI-only tool (Undo_Tag_Edits.pyw); it restores a backup "
            "written by a prior batch run and has no headless equivalent."
        ),
    }

    @pytest.mark.parametrize(
        "manifest_id,command",
        [
            (manifest.id, manifest.cli_command)
            for manifest in get_registry().all
            if manifest.cli_command
        ],
        ids=lambda value: value if isinstance(value, str) else value[0],
    )
    def test_tool_subcommand_exists_and_its_help_resolves(
        self, runner: CliRunner, manifest_id: str, command: str
    ) -> None:
        assert command in cli.commands, (
            f"{manifest_id}: manifest declares subcommand {command!r} but it is "
            "not registered in audio_suite_shared.cli_app"
        )
        result = runner.invoke(cli, [command, "--help"])
        assert result.exit_code == 0, (
            f"{manifest_id}: '{command} --help' must resolve: {result.output}"
        )
        assert "Usage:" in result.output

    def test_no_undeclared_gap_below(self) -> None:
        """A tool without a subcommand must be a declared, justified gap."""
        without = {m.id for m in get_registry().all if not m.cli_command}
        assert without == set(self.NO_CLI_TOOLS), (
            "tools without a CLI subcommand changed. Add a subcommand, or add "
            "an entry to NO_CLI_TOOLS with its reason — a new gap must not "
            "appear silently. "
            f"undeclared={sorted(without - set(self.NO_CLI_TOOLS))} "
            f"stale={sorted(set(self.NO_CLI_TOOLS) - without)}"
        )
        assert all(reason.strip() for reason in self.NO_CLI_TOOLS.values()), (
            "every declared gap must state why it is acceptable"
        )

    def test_top_level_help_lists_every_registered_command(
        self, runner: CliRunner
    ) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        for command in cli.commands:
            assert command in result.output, (
                f"'{command}' is registered but absent from 'audiosuite --help'"
            )

    def test_top_level_help_lists_every_tool_that_has_a_subcommand(
        self, runner: CliRunner
    ) -> None:
        """The acceptance criterion, stated without inventing a feature.

        Plan G2 asks that ``--help`` list all 27 tools.  26 of them have a
        subcommand and so are listed; the 27th (``undo_tag_edits``) is a
        declared GUI-only gap, and listing it would mean building the CLI
        command the plan explicitly does not ask for.  It is therefore
        covered by ``test_no_undeclared_gap_below`` instead of by help text.
        """
        tools = get_registry().all
        assert len(tools) == 27
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        with_subcommand = [m for m in tools if m.cli_command]
        assert len(with_subcommand) == 26
        for manifest in with_subcommand:
            assert manifest.cli_command in result.output, (
                f"{manifest.id}: '{manifest.cli_command}' is not listed in "
                "'audiosuite --help'"
            )
        # The GUI-only tool is exactly the declared gap, not a surprise.
        assert [m.id for m in tools if not m.cli_command] == ["undo_tag_edits"]

    def test_commands_are_grouped_by_function(self, runner: CliRunner) -> None:
        """Sections must render, and every command must sit under one."""
        from audio_suite_shared.cli_base import _CATEGORY_HEADINGS, _command_groups

        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        with _introspection_context() as context:
            groups = _command_groups(cli, context)

        # A flat alphabetical dump is the failure mode this replaces: with 27
        # commands and no headings, the reader gets one undifferentiated wall.
        # Require real functional sections, not a decorative one.
        assert len(groups) >= 3, (
            "top-level help must group 27 commands into functional sections; "
            f"got {len(groups)}"
        )
        for _category, heading in _CATEGORY_HEADINGS:
            assert heading in result.output, (
                f"top-level help is missing the {heading!r} section"
            )
        # Each section's own commands must render *inside* that section, so
        # slice the output between consecutive headings rather than searching
        # the whole page (a bare "in output" check passes even if a command is
        # dumped in the wrong section).
        for index, (heading, commands) in enumerate(groups):
            start = result.output.index(heading)
            end = (
                result.output.index(groups[index + 1][0])
                if index + 1 < len(groups)
                else len(result.output)
            )
            section_text = result.output[start:end]
            for name in commands:
                assert name in section_text, (
                    f"'{name}' does not render under its section {heading!r}"
                )

    def test_every_command_appears_in_exactly_one_help_group(
        self, runner: CliRunner
    ) -> None:
        """No command may be silently dropped from the grouped help."""
        from audio_suite_shared.cli_base import _command_groups

        with _introspection_context() as context:
            groups = _command_groups(cli, context)
        grouped = [name for _, names in groups for name in names]
        assert sorted(grouped) == sorted(cli.commands), (
            "grouped help does not cover the registered commands exactly: "
            f"grouped={sorted(grouped)} registered={sorted(cli.commands)}"
        )
        assert len(grouped) == len(set(grouped)), (
            "a command appears in more than one help group"
        )

    def test_flat_command_list_remains_available(self, runner: CliRunner) -> None:
        """Grouping is a rendering change only; the flat list still works."""
        context = _introspection_context()
        try:
            flat = cli.list_commands(context)
        finally:
            context.close()
        assert flat == sorted(flat)
        assert set(flat) == set(cli.commands)

    def test_version_matches_the_pyproject_declaration(self, runner: CliRunner) -> None:
        from audio_suite_shared.project_version import declared_version

        expected = declared_version()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert result.output.strip() == f"audiosuite, version {expected}"

    def test_version_comes_from_pyproject_not_a_second_constant(
        self, runner: CliRunner
    ) -> None:
        """Guard the 'lives in exactly one place' requirement."""
        from pathlib import Path

        import tomllib

        pyproject = tomllib.load(
            (Path(__file__).resolve().parents[2] / "pyproject.toml").open("rb")
        )
        declared = pyproject["project"]["version"]
        from audio_suite_shared.project_version import declared_version

        assert declared_version() == declared
        # And the old distribution-metadata indirection is gone.
        source = (Path(__file__).resolve().parents[1] / "cli_base.py").read_text(
            encoding="utf-8"
        )
        assert "package_name=" not in source, (
            "cli_base must not read the version from installed distribution "
            "metadata; pyproject.toml is the single source"
        )

    def test_static_surfaces_are_covered_by_the_e1_test(self) -> None:
        """The other half of this contract must not quietly disappear."""
        import importlib

        readme_tests = importlib.import_module("tests.test_readme")
        names = {
            name
            for name in dir(readme_tests.TestRegistrationLock)
            if name.startswith("test_")
        }
        assert names, "E1's registration lock is gone; this contract is now half"
        assert hasattr(readme_tests, "_EMBEDDED_TAB_TOOLS")
        assert "audio_refinery" in readme_tests._EMBEDDED_TAB_TOOLS


# ── Edge cases ────────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_bpm_max_min_same(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        d = tmp_path / "m"
        d.mkdir()
        result = runner.invoke(
            cli, ["bpm", str(d), "--bpm-min", "120", "--bpm-max", "120", "--dry"]
        )
        # Parser accepts this; runtime may handle it
        assert result.exit_code == 0

    def test_directory_does_not_exist(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["bpm", "C:\\nonexistent"])
        assert result.exit_code != 0
        assert "does not exist" in result.output

    def test_directory_is_file(
        self, runner: CliRunner, tmp_path: pytest.TempPathFactory
    ) -> None:
        f = tmp_path / "afile.txt"
        f.write_text("hello")
        result = runner.invoke(cli, ["bpm", str(f)])
        assert result.exit_code != 0


# ── A1 (audit #A1): the docstring is the documented contract ──────────────────
#
# ``audio_suite_shared/cli_app.py``'s module docstring advertises a usage line
# per command.  That block is the *only* place a user learns the flag spelling
# without running ``--help``, so a flag that appears there but not on the
# command is a documented-but-false contract -- the exact defect the audit
# reproduced with ``enhance ... --dry`` (exit 2, "No such option: --dry").
#
# This class makes the docstring executable documentation: every ``[--flag]``
# token on a documented line must resolve against that command's real parser.
# Removing a flag now fails the suite instead of silently shipping a lie.


class TestDocumentedFlagParity:
    """Every flag the docstring advertises must resolve on its command."""

    #: Conventional, non-tool flags.  These are Click/click-suite conventions
    #: rather than tool options, so their absence from a command's own option
    #: list is not drift.  Every entry must state why it is exempt.
    ALLOWED_ABSENT: dict[str, str] = {
        "--help": "Click supplies --help on every command implicitly.",
        "--json": (
            "Output-format switch of the shared --json/--text pair; a command "
            "that does not emit a summary has no use for it."
        ),
        "--text": "Counterpart of the shared --json/--text output switch.",
    }

    @staticmethod
    def _docstring() -> str:
        return inspect.getdoc(cli_app_module) or ""

    @classmethod
    def _usage_blocks(cls, docstring: str) -> list[tuple[str, str | None, str]]:
        """Join the docstring's wrapped usage lines into one block per command.

        A command's usage spans several indented lines, so a line-by-line parse
        would attribute each continuation line's flags to whichever command
        happened to be printed on it.  Blocks are therefore split on every
        ``audiosuite <token>`` start, and the continuation lines are appended to
        the block they belong to.  The block ends at the first blank line after
        the usage section begins.

        Args:
            docstring: The ``cli_app`` module docstring.

        Returns:
            ``(command, subcommand, text)`` triples, one per documented
            command.  ``subcommand`` is set only for the ``cue`` group, whose
            options live one level down.
        """
        start = docstring.find("Usage:")
        if start == -1:
            return []
        lines: list[str] = []
        for raw in docstring[start:].splitlines()[1:]:
            if not raw.strip():
                if lines:
                    break  # end of the usage section
                continue
            lines.append(raw)

        blocks: list[tuple[str, str | None, str]] = []
        command: str | None = None
        subcommand: str | None = None
        buffered: list[str] = []
        for raw in lines:
            tokens = raw.split()
            if len(tokens) >= 2 and tokens[0] == "audiosuite":
                if command is not None:
                    blocks.append((command, subcommand, "\n".join(buffered)))
                command = tokens[1]
                # ``cue parse`` / ``cue generate`` / ``cue split``: the real
                # target is the subcommand, not the group.
                subcommand = tokens[2] if command == "cue" and len(tokens) > 2 else None
                buffered = [raw]
            elif command is not None:
                buffered.append(raw)
        if command is not None:
            blocks.append((command, subcommand, "\n".join(buffered)))
        return blocks

    def test_documented_commands_exist(self) -> None:
        """Each documented ``audiosuite <command>`` must be a real command."""
        blocks = self._usage_blocks(self._docstring())
        assert blocks, "the usage block documented no commands at all"

        ctx = _introspection_context()
        try:
            registered = set(cli.list_commands(ctx))
            for command, subcommand, _ in blocks:
                assert command in registered, (
                    f"cli_app.py's docstring documents 'audiosuite {command}', "
                    f"which is not a registered command "
                    f"(registered: {sorted(registered)})"
                )
                if subcommand is None:
                    continue
                group = cli.get_command(ctx, command)
                assert (
                    isinstance(group, click.Group) and subcommand in group.commands
                ), (
                    f"cli_app.py's docstring documents 'audiosuite {command} "
                    f"{subcommand}', which is not a {command} subcommand"
                )
        finally:
            ctx.close()

    def test_every_documented_flag_resolves(self) -> None:
        """The parity assertion: documented ``[--flag]`` tokens must be real."""
        blocks = self._usage_blocks(self._docstring())
        assert blocks, (
            "no usage lines parsed from cli_app.py's docstring — the parser or "
            "the docstring changed shape"
        )

        failures: list[str] = []
        checked = 0
        for command, subcommand, text in blocks:
            documented = re.findall(r"\[(--[a-z0-9-]+)", text)
            if not documented:
                continue
            ctx = _introspection_context()
            try:
                target = cli.get_command(ctx, command)
                if subcommand is not None and isinstance(target, click.Group):
                    target = target.get_command(ctx, subcommand)
            finally:
                ctx.close()
            assert target is not None, f"command {command!r} did not resolve"
            real: set[str] = set()
            for param in target.params:
                if isinstance(param, click.Option):
                    real.update(param.opts)
                    real.update(param.secondary_opts)
            for flag in documented:
                checked += 1
                if flag in real or flag in self.ALLOWED_ABSENT:
                    continue
                failures.append(
                    f"audiosuite {command}"
                    + (f" {subcommand}" if subcommand else "")
                    + f": documented {flag} but the command accepts "
                    f"{sorted(real)}"
                )

        assert checked, "no documented flags were checked — parse produced none"
        assert not failures, (
            "cli_app.py's docstring advertises flags its commands do not "
            "accept (audit A1, 'No such option'):\n  " + "\n  ".join(failures)
        )

    def test_the_known_missing_dry_flags_are_real(self) -> None:
        """The audit's exact repro must now resolve, exit 0, and write nothing."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(
                cli, ["enhance", ".", "--output-dir", "out", "--dry"]
            )
            assert result.exit_code == 0, result.output
            assert not (Path("out").exists() and any(Path("out").iterdir())), (
                "a dry run must not write output files"
            )


# ── Every _run_tool target must actually accept _run_tool's kwargs ───────────


def _resolve(dotted: str) -> object:
    """Import and return the object named by a dotted path."""
    module_name, _, attr = dotted.rpartition(".")
    return getattr(importlib.import_module(module_name), attr)


class TestRunToolTargetsAcceptItsKwargs:
    """``_run_tool`` injects ``slot_vars`` and ``slot_queue`` into every call.

    ``run_normalization`` (album_art_normalizer) was the one target that
    declared neither a ``**kwargs`` catch-all nor those two names, so the CLI's
    ``run_fn(**kwargs)`` raised ``TypeError``, the tool's own
    ``@handle_audio_errors(reraise=False)`` downgraded it to a log line, and the
    command reported "0 files, 0 skipped, 0 errors" — a clean-looking success
    that had processed nothing.  Every test that mocked the engine stayed
    green.  This locks the class of defect, not just the one instance.
    """

    #: command name -> dotted path of the callable it hands to _run_tool
    TARGETS = {
        "album-art": "album_art_sync.cli.run_cli_art_sync",
        "album-genre": "album_genre_tagger.cli.run_cli_analysis",
        "artnormalize": ("album_art_normalizer.core.file_processor.run_normalization"),
        "asx-extract": "asx_extractor.cli.run_cli_extraction",
        "bpm": "bpm_analyzer.core.file_processor.run_analysis",
        "convert": "music_format_converter.core.file_processor.run_conversion",
        "declick": "pop_click_remover.core.file_processor.run_declicking",
        "enhance": "audio_enhancer.core.file_processor.run_enhancement",
        "fingerprint": "audio_fingerprinter.core.file_processor.run_fingerprinting",
        "key": "key_detector.core.file_processor.run_analysis",
        "lyrics": "lyrics_manager.core.file_processor.run_fetch",
        "mood-analyzer": "mood_analyzer.core.file_processor.run_analysis",
        "normalise": "audio_normalizer.core.file_processor.run_parallel_process",
        "replaygain": "replaygain_analyzer.core.file_processor.run_analysis",
        "scrub": "metadata_scrubber.core.scrubber.run_scrubbing",
        "silence-trim": "silence_trimmer.core.file_processor.run_trimming",
        "tempo": "tempo_analyzer.core.file_processor.run_analysis",
    }

    @pytest.mark.parametrize("command", sorted(TARGETS))
    def test_target_accepts_slot_vars_and_slot_queue(self, command: str) -> None:
        dotted = self.TARGETS[command]
        run_fn = _resolve(dotted)
        params = inspect.signature(run_fn).parameters
        accepts_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        missing = [n for n in ("slot_vars", "slot_queue") if n not in params]
        assert accepts_kwargs or not missing, (
            f"{dotted} accepts neither **kwargs nor {missing}, but "
            "cli_base._run_tool passes both on every call — the command would "
            "raise TypeError and report a clean '0 files, 0 errors'"
        )

    def test_the_inventory_is_not_silently_empty(self) -> None:
        """A scan that resolves nothing passes vacuously; assert the count."""
        resolved = sum(1 for d in self.TARGETS.values() if _resolve(d) is not None)
        assert resolved == len(self.TARGETS)

    def test_artnormalize_reaches_its_engine_unstubbed(self, tmp_path: Path) -> None:
        """End-to-end: the real command, real engine, empty directory.

        Pre-fix this printed a TypeError traceback for
        ``run_normalization() got an unexpected keyword argument 'slot_queue'``
        while still summarising "0 files, 0 skipped, 0 errors".
        """
        runner = CliRunner()
        result = runner.invoke(cli, ["artnormalize", str(tmp_path)])

        assert "unexpected keyword argument" not in result.output
        assert "Traceback" not in result.output
        assert "No supported audio files found" in result.output, (
            "the command must reach the engine and report the empty directory; "
            f"got: {result.output}"
        )
