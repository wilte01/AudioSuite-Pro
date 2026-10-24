"""cli_base.py — Shared CLI infrastructure for audiosuite click commands.

Houses the click Group, shared options, the _Result collector, and the
_run_tool helper that every tool CLI handler uses.

Changed in 1.4.0: the headless slot shims are sized from
``default_max_workers()``.  They defaulted to a fixed 4 while the worker
default became the CPU-derived count (PLAN D56), so a CLI run on five or more
files handed a worker ``slot_idx`` 4 and the shim list raised ``IndexError`` —
the file was reported as an unexplained error.  They also grow to an explicit
``--workers`` value above the default, so the count a user asks for always has
a shim for every index (D66).

Changed in 1.0.1: fixes ``_run_tool``'s ``on_progress`` to accept the positional call
form the analysis workflow uses.
Changed in 1.4.0: the console handler now honours ``--log-level`` too, so a
WARNING run no longer prints the DEBUG processing detail and its stack traces.
Changed in 1.4.0: ``_Result.to_payload()`` is the single JSON exit point for
every tool, so all commands publish the core keys defined in
``audio_suite_shared.cli_schema`` (PLAN D82).
Changed in 1.4.0: every command warns once when the installed package
version differs from the checkout, pointing at ``uv run audiosuite``.
Changed in 1.4.1: the JSON contract covers failures too.  A group-level
``main()`` override publishes a schema-valid payload for a usage error
(exit 2) and for any other ``ClickException`` (its exit code), so a
consumer never has to parse stderr; the human line still goes to stderr,
text mode is unchanged, and ``RunFailure(already_reported=True)`` lets a
command that printed its own document exit non-zero without a second one
(PLAN D91).
Changed in 1.4.1: ``--json-schema`` prints the committed document file rather
than regenerating it, so a consumer receives the shipped artifact including
its per-command example payloads and fatal-error documents (PLAN D104, D105).
Changed in 1.4.1: ``finish_run`` gives a *fatal* run exit 1 after its payload
is printed, while a run whose only losses were per-file keeps its command's
exit status (PLAN D92).

Changed in 2.1.0: ``_command_path`` takes any grouped command the schema declares
(``plugins list``), not only ``cue``'s subcommands.
"""

from __future__ import annotations

import errno
import json
import logging
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from queue import Queue
from typing import Any, Callable

import click

from audio_suite_shared.cli_schema import TOOL_IDS, error_payload
from audio_suite_shared.constants import default_max_workers
from audio_suite_shared.logging_setup import configure_logging as configure_logging
from audio_suite_shared.project_version import declared_version

logger = logging.getLogger(f"audio_suite.{__name__}")


# ── tkinter-free shims ────────────────────────────────────────────────────


class _NullStringVar:
    """Drop-in for tk.StringVar that discards all values."""

    def set(self, value: Any) -> None:
        pass

    def get(self) -> str:
        return ""


def _make_slot_vars(n: int | None = None) -> list[_NullStringVar]:
    """Return *n* headless slot variables (default: the worker default).

    The count must cover every ``slot_idx`` a default-sized pool can hand out:
    processors derive indices from ``range(max_workers)``, so a shorter list is
    an IndexError waiting for the fifth file.
    """
    count = default_max_workers() if n is None else n
    return [_NullStringVar() for _ in range(count)]


def _make_slot_queue(n: int | None = None) -> Queue[Any]:
    """Return a preloaded slot-id queue (default: the worker default)."""
    count = default_max_workers() if n is None else n
    q: Queue[Any] = Queue()
    for i in range(count):
        q.put(i)
    return q


# ── Result collector ──────────────────────────────────────────────────────


@dataclass
class _Result:
    """Collects the on_complete summary from a tool run."""

    total: int = 0
    processed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_secs: float = 0.0
    log_entries: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    #: The run crashed instead of finishing (``_run_tool`` caught an exception).
    #: Kept apart from ``errors`` so the counts stay reportable - a negative
    #: sentinel in ``errors`` reached the text summary as "-1 errors", and the
    #: JSON schema's ``minimum: 0`` could not express it (PLAN D92).
    fatal: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["duration_str"] = f"{self.duration_secs:.1f}s"
        d.pop("fatal")
        return d

    def to_payload(
        self, command: str, *, dry_run: bool = False, **overrides: Any
    ) -> dict[str, Any]:
        """Serialise this run to its command's locked JSON schema.

        Tool-specific completion fields (BPM's ``skipped_files``, the
        fingerprinter's ``results``) arrive in ``extra`` and are published at
        the top level, next to the core keys.  Building the payload here — not
        in each CLI — is what keeps the core key names identical everywhere.

        Args:
            command:   CLI path, a key of ``cli_schema.TOOL_IDS``.
            dry_run:   Whether the run's ``--dry`` flag was in effect.
            **overrides: Tool-specific fields that must be serialised rather
                       than passed through (the fingerprinter's result objects
                       become dicts), replacing the same key in ``extra``.

        Returns:
            The payload, ready for ``json.dumps``.
        """
        from audio_suite_shared.cli_schema import build_payload, extras_for

        # Only the fields the schema declares are public.  Completion callbacks
        # also carry internal detail (enhancer result objects, log-line lists);
        # publishing it would make every new internal field a JSON change, so it
        # stays out and is noted at DEBUG for anyone debugging a missing field.
        declared = set(extras_for(command)) | {"error"}
        ignored = sorted(set(self.extra) - declared)
        if ignored:
            logger.debug(
                "%s JSON payload omits undeclared completion field(s) %s",
                command,
                ignored,
            )
        fields: dict[str, Any] = {
            key: value for key, value in self.extra.items() if key in declared
        }
        fields.update(overrides)
        return build_payload(
            command,
            dry_run=dry_run,
            total=self.total,
            processed=self.processed,
            skipped=self.skipped,
            errors=self.errors,
            duration_secs=self.duration_secs,
            log_entries=self.log_entries,
            **fields,
        )


# ── Run helper ────────────────────────────────────────────────────────────


def _run_tool(
    tool_name: str,
    run_fn: Callable[..., None],
    **kwargs: Any,
) -> _Result:
    """Execute a tool's run_* function with terminal callbacks."""
    result = _Result()
    # An explicit --workers above the suite default must get shims for every
    # index the pool will hand out, not just the default count (D66).
    requested_workers = kwargs.get("max_workers")
    slot_count = default_max_workers()
    if isinstance(requested_workers, int) and requested_workers > slot_count:
        slot_count = requested_workers
    slot_vars = _make_slot_vars(slot_count)
    slot_queue = _make_slot_queue(slot_count)
    error_msg: list[str] = []

    def on_progress(
        processed: int = 0,
        total: int = 0,
        skipped: int = 0,
        errors: int = 0,
        display_text: str = "",
        **_ignored: Any,
    ) -> None:
        # The documented ProgressCallback contract is
        # ``(processed, total, skipped, errors, display_text)`` and two call
        # styles reach this callback: ``run_parallel_processing`` passes it
        # straight to ``create_progress_tracker`` (keyword call), while
        # ``run_analysis_workflow`` wraps it in a positional lambda.  A
        # positional-or-keyword signature satisfies both; a ``**kwargs``-only
        # signature silently rejected the positional form and crashed every
        # CLI run on the first file.  ``**_ignored`` absorbs the tool-specific
        # counters a callback may also send (the enhancer's ``done=``): a
        # missing parameter made every file fail with "Worker error" in JSON
        # and text mode alike.
        if display_text:
            click.echo(f"  {display_text}", err=True)
        elif total:
            click.echo(f"  [{processed}/{total}]", err=True)

    def on_complete(**cb_kwargs: Any) -> None:
        result.total = cb_kwargs.get("total", 0)
        result.processed = cb_kwargs.get("processed", 0)
        result.skipped = cb_kwargs.get("skipped", 0)
        result.errors = cb_kwargs.get("errors", 0)
        result.duration_secs = cb_kwargs.get("duration_secs", 0.0)
        result.log_entries = cb_kwargs.get("log_entries", [])
        for k, v in cb_kwargs.items():
            if k not in (
                "total",
                "processed",
                "skipped",
                "errors",
                "duration_secs",
                "log_entries",
            ):
                result.extra[k] = v

    def on_error(msg: str) -> None:
        error_msg.append(msg)
        click.echo(f"  ERROR: {msg}", err=True)

    kwargs.setdefault("slot_vars", slot_vars)
    kwargs.setdefault("slot_queue", slot_queue)
    kwargs.setdefault("on_progress", on_progress)
    kwargs.setdefault("on_complete", on_complete)
    kwargs.setdefault("on_error", on_error)

    click.echo(f"Starting {tool_name}...", err=True)
    start = time.monotonic()
    try:
        run_fn(**kwargs)
    except Exception as exc:
        logger.error("FATAL error in %s: %s", tool_name, exc, exc_info=True)
        click.echo(f"  FATAL: {exc}", err=True)
        # The crash left one run unfinished, so it counts as one failed item:
        # the payload stays schema-valid and the text summary cannot print a
        # negative count.  ``fatal`` is what ``finish_run`` turns into exit 1.
        result.errors = 1
        result.fatal = True
        # The JSON payload must say why the run failed; ``error`` is the one
        # field every command may carry (cli_schema.error_payload), so a
        # consumer needs no separate failure shape.
        result.extra["error"] = str(exc)
        result.duration_secs = time.monotonic() - start
        return result

    result.duration_secs = time.monotonic() - start
    if error_msg:
        click.echo(f"Finished with errors: {', '.join(error_msg)}", err=True)
    else:
        click.echo(f"Finished in {result.duration_secs:.1f}s.", err=True)
    return result


def finish_run(result: _Result) -> None:
    """Exit 1 when a run crashed instead of finishing, after its payload.

    ``_run_tool`` flags a caught exception with ``fatal`` because the tool never
    produced a completion summary.  Every command calls this *after* it has
    printed its JSON or text payload, so a caller sees the reason and the
    non-zero status together - before this, a run that died on its first file
    exited 0 and only the payload said anything was wrong (PLAN D92).

    A run whose failures were per-file keeps whatever exit status the command
    already has: the suite has never had a single policy for "finished with
    failures", and imposing one here would silently change every batch tool's
    shell contract.

    Args:
        result: The collector ``_run_tool`` returned.

    Raises:
        SystemExit: With status 1 when the run failed fatally.
    """
    if result.fatal:
        raise SystemExit(1)


# ── Shared CLI options ────────────────────────────────────────────────────


_opt_dry_run = click.option(
    "--dry/--live", "dry_run", default=False, help="Analyse only, do not write tags."
)
_opt_json = click.option("--json/--text", default=False, help="Output results as JSON.")
_opt_parallel = click.option(
    "--parallel/--no-parallel",
    default=False,
    help="Use process-level parallelism for CPU-bound stages (bypasses GIL).",
)
_opt_workers = click.option(
    "--workers",
    default=None,
    type=int,
    help=f"Number of parallel workers (default: {default_max_workers()}).",
)
_opt_dir = click.argument("directory", type=click.Path(exists=True, file_okay=False))


# ── Grouped help rendering (plan G2) ────────────────────────────────────

#: Human-readable headings for the manifest's ``category`` values.  The
#: grouping itself is *not* re-declared here: the categories come from
#: ``tool_plugin`` (the single source of truth) and only the wording is
#: local.  Order here is the order the sections appear in ``--help``.
_CATEGORY_HEADINGS: tuple[tuple[str, str], ...] = (
    ("enrich", "Analysis and tag enrichment"),
    ("refinery", "Multi-stage DSP pipeline"),
    ("utility", "Library and conversion utilities"),
)

_OTHER_HEADING = "Other commands"


def _command_groups(
    group: click.Group, ctx: click.Context
) -> list[tuple[str, list[str]]]:
    """Bucket the group's commands into the sections of ``--help``.

    Args:
        group: The Click group whose commands should be bucketed.
        ctx: The active context, which Click's ``list_commands`` requires.

    Returns:
        ``(heading, commands)`` pairs in display order.  Commands with no
        manifest entry land in a trailing "Other commands" section, so a
        newly registered command can never be silently dropped from the help
        (the contract test asserts every command appears in exactly one
        bucket).
    """
    from audio_suite_shared.tool_plugin import get_registry

    buckets: dict[str, list[str]] = {key: [] for key, _ in _CATEGORY_HEADINGS}
    claimed: set[str] = set()
    for manifest in get_registry().all:
        if not manifest.cli_command:
            continue
        claimed.add(manifest.cli_command)
        buckets.setdefault(manifest.category, []).append(manifest.cli_command)

    sections: list[tuple[str, list[str]]] = []
    for category, heading in _CATEGORY_HEADINGS:
        commands = sorted(set(buckets.pop(category, [])))
        if commands:
            sections.append((heading, commands))

    remaining = sorted(set(group.list_commands(ctx)) - claimed)
    if remaining:
        sections.append((_OTHER_HEADING, remaining))
    return sections


# ── Failure reporting (S5-1 / D91) ────────────────────────────────────────


class RunFailure(click.ClickException):
    """A run failure whose JSON document the command already printed.

    ``_run_tool``-based commands publish their summary and return, so they
    never raise.  The few commands that must print a failure document *and*
    exit non-zero (cd-rip's drive and session failures) raise this with
    ``already_reported=True``: the group handler still shows the human line
    and exits 1, but does not publish a second document.
    """

    def __init__(self, message: str, *, already_reported: bool = False) -> None:
        super().__init__(message)
        self.already_reported = already_reported


_JSON_ON = "--json"
_JSON_OFF = "--text"
_DRY_ON = "--dry"
_DRY_OFF = "--live"


def _last_flag(argv: Sequence[str], *, on: str, off: str) -> bool:
    """Return the effective value of an ``--on/--off`` pair.

    Click applies the last occurrence, so ``--json --text`` is text.
    """
    value = False
    for token in argv:
        if token == on:
            value = True
        elif token == off:
            value = False
    return value


def _argv_wants_json(argv: Sequence[str]) -> bool:
    """Return whether this invocation asked for JSON output."""
    return _last_flag(argv, on=_JSON_ON, off=_JSON_OFF)


def _argv_is_dry_run(argv: Sequence[str]) -> bool:
    """Return whether this invocation asked for a dry run."""
    return _last_flag(argv, on=_DRY_ON, off=_DRY_OFF)


def _command_path(argv: Sequence[str]) -> str | None:
    """Return the command path named in *argv* (``bpm``, ``cue parse``).

    Group options come before the command: ``--log-level`` takes a value in
    either spelling and the remaining flags are boolean.  A command that lives
    in a group (``cue parse``, ``plugins list``) needs its subcommand because
    the schema keys the payload by the full path: the pair is taken only when
    it is itself a declared command, so a group's own arguments are not
    mistaken for a subcommand.
    """
    tokens = list(argv)
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "--log-level":
            index += 2
            continue
        if token.startswith("--log-level=") or token.startswith("-"):
            index += 1
            continue
        command = token
        if index + 1 < len(tokens):
            subcommand = tokens[index + 1]
            nested = f"{command} {subcommand}"
            if not subcommand.startswith("-") and nested in TOOL_IDS:
                command = nested
        return command
    return None


def _failure_document(
    argv: Sequence[str], exc: click.ClickException
) -> dict[str, Any] | None:
    """Return the payload to publish for *exc*, or None for text behaviour.

    A document is published only when the invocation asked for JSON, named a
    command the schema knows, and the failing command has not already printed
    its own (``RunFailure(already_reported=True)``).
    """
    if isinstance(exc, RunFailure) and exc.already_reported:
        return None
    if not _argv_wants_json(argv):
        return None
    command = _command_path(argv)
    if command is None or command not in TOOL_IDS:
        return None
    return error_payload(
        command,
        exc.format_message(),
        dry_run=_argv_is_dry_run(argv),
    )


class GroupedHelpGroup(click.Group):
    """A ``click.Group`` whose help lists commands under functional headings.

    ``list_commands()`` is deliberately left as Click's flat, sorted default:
    the flat list stays available to any caller (and any existing test) that
    depends on ordering, and only the *rendering* is grouped (plan G2).
    """

    def format_commands(
        self, ctx: click.Context, formatter: click.HelpFormatter
    ) -> None:
        """Render one sub-command table per functional section."""
        for heading, commands in _command_groups(self, ctx):
            rows: list[tuple[str, str]] = []
            for name in commands:
                command = self.get_command(ctx, name)
                if command is None or command.hidden:
                    continue
                rows.append((name, command.get_short_help_str(limit=90)))
            if not rows:
                continue
            with formatter.section(heading):
                formatter.write_dl(rows)

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: Any,
    ) -> Any:
        """Run the CLI, publishing a JSON document when a run fails.

        Click's standalone mode prints a usage error and exits before any
        command code can see it, which left ``--json`` consumers with an empty
        stdout.  This override runs the group non-standalone and reproduces
        Click's own presentation: a failing invocation keeps its exit status
        and its human stderr line, and gains the schema's error document on
        stdout when JSON was requested.  A non-standalone caller (a test, an
        embedder) is delegated unchanged.
        """
        if not standalone_mode:
            return super().main(args, prog_name, complete_var, standalone_mode, **extra)
        argv = list(sys.argv[1:] if args is None else args)
        try:
            try:
                return super().main(
                    argv, prog_name, complete_var, standalone_mode=False, **extra
                )
            except (EOFError, KeyboardInterrupt) as exc:
                click.echo(file=sys.stderr)
                raise click.Abort() from exc
            except click.ClickException as exc:
                document = _failure_document(argv, exc)
                if document is not None:
                    click.echo(json.dumps(document, indent=2))
                exc.show()
                sys.exit(2 if isinstance(exc, click.UsageError) else exc.exit_code)
            except OSError as exc:
                if exc.errno != errno.EPIPE:
                    raise
                sys.exit(1)
        except click.exceptions.Exit as exc:
            sys.exit(exc.exit_code)
        except click.Abort:
            click.echo("Aborted!", err=True)
            sys.exit(1)


def _configure_console_logging(level: int) -> None:
    """Send console records at *level* to stderr, and nothing below it.

    ``logging.basicConfig`` sets only the *root logger* level.  The tool
    package loggers carry an explicit level from ``configure_logging``, so
    their DEBUG and INFO records bypass the root level and still reach the
    console handler, which is created with ``NOTSET``.  Without the handler
    level, ``--log-level WARNING`` printed every processing detail — and the
    stack traces logged at DEBUG — while the file logs obeyed the requested
    level.

    Args:
        level: Minimum level the console should show.
    """
    logging.basicConfig(
        level=level,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    for handler in logging.getLogger().handlers:
        handler.setLevel(level)


@click.group(
    cls=GroupedHelpGroup,
    # ``--json-schema`` is a flag, not a subcommand: the group callback must run
    # and may exit before Click insists on a command.  ``no_args_is_help``
    # keeps a bare invocation showing help exactly as before.
    invoke_without_command=True,
    no_args_is_help=True,
)
@click.option(
    "--log-level",
    default="WARNING",
    help="Logging level (DEBUG, INFO, WARNING, ERROR).",
)
@click.option(
    "--json-schema",
    "show_json_schema",
    is_flag=True,
    default=False,
    help=(
        "Print the locked JSON output schema (schema v1), with a recorded "
        "payload and fatal-error document per command, and exit."
    ),
)
# Plan G2: the version is read from [project] version in pyproject.toml, so
# it lives in exactly one place.  Resolved once here (not per --help render)
# because a release bump must never require a second edit.
@click.version_option(version=declared_version(), prog_name="audiosuite")
@click.pass_context
def cli(ctx: click.Context, log_level: str, show_json_schema: bool) -> None:
    """AudioSuite-Pro — headless audio processing toolkit."""
    if show_json_schema:
        # The committed document is the contract, examples included, so it is a
        # group option: an external consumer fetches the artifact itself without
        # importing Python, and what is printed is the shipped document rather
        # than one regenerated from the imported version.
        from audio_suite_shared.cli_schema import committed_schema_text

        try:
            document = committed_schema_text()
        except OSError as exc:
            raise click.ClickException(
                "The committed JSON Schema (cli_schema.json) is missing from "
                f"this install: {exc}. Reinstall the package."
            ) from exc
        click.echo(document, nl=False)
        ctx.exit(0)
    level = getattr(logging, log_level.upper(), logging.WARNING)
    _configure_console_logging(level)
    # Also route first-party tool-package records to the suite log file;
    # min_level mirrors the console level so --log-level still governs what
    # is emitted (plan iteration-9 G4.3).
    configure_logging("audiosuite_cli", min_level=level)
    # A global `pip install -e .` from an earlier release keeps the command
    # list it was built with; a bare `audiosuite` then dies on a tool import.
    # Warn when the installed version disagrees with this checkout, or when it
    # matches but packages import from another tree, and name the locked
    # runtime rather than letting the mismatch stay hidden.  ``runtime_check``
    # emits it once per process, so this per-command callback cannot repeat it.
    from audio_suite_shared.runtime_check import stale_install_warning

    warning = stale_install_warning()
    if warning:
        click.echo(warning, err=True)
