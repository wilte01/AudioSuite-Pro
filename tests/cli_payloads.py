"""Drive every CLI command once, for the recorded payload corpus.

``tests/data/cli_payloads.json`` is the committed snapshot that
:mod:`tests.cli_schema_conformance` validates against
``audio_suite_shared/cli_schema.json``.  A snapshot is only worth validating if
it came from the real commands, so recording goes through the same click group
a user invokes - with the two hardware/network paths patched the way the
integration lock in ``tests/test_cli_json_schema.py`` patches them - rather than
being hand-written.

Importing this module imports every tool's CLI.  The conformance *check* needs
none of that, so only ``--record`` imports this module, and lazily.

Changed in 1.4.1: initial version, extracted from
``tests/test_cli_json_schema.py`` so the recorder and the integration lock build
argv and invoke commands the same way instead of drifting apart.
Changed in 1.4.1: also records each command's fatal-error document by driving
it with a missing input path, so the published failure shape is a real one
(PLAN D105).
"""

from __future__ import annotations

import json
import tempfile
import wave
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

from click.testing import CliRunner

from audio_suite_shared.cli_app import cli
from audio_suite_shared.cli_schema import TOOL_IDS

#: The checkout root, normalised to ``<repo>`` in a recorded payload.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: Commands that would need hardware or network to complete.  ``cd-rip`` is
#: recorded from its own payload builder instead of a run; everything else is
#: driven for real.
BUILDER_RECORDED: frozenset[str] = frozenset({"cd-rip"})

#: Commands that would query a web service if given an audio file.  Their
#: payload shape is proved on an empty directory instead of in a network call.
EMPTY_LIBRARY: frozenset[str] = frozenset({"album-art", "lyrics"})

#: Commands with no validated input path to point at a missing one: ``doctor``
#: takes no arguments, and ``cd-rip``'s DRIVE is a device rather than a path.
#: Their failure document is recorded from an unknown option instead.
NO_INPUT_PATH: frozenset[str] = frozenset({"cd-rip", "doctor"})

#: The unknown option that makes a command fail while Click parses its argv,
#: before any tool code runs.  It has to be an option no command declares.
UNKNOWN_OPTION: str = "--no-such-option"

#: The missing path a command is pointed at to record its failure document.  It
#: is relative on purpose: Click quotes the value it rejected ("Directory
#: 'no-such-input' does not exist."), so a relative name keeps the committed
#: message byte-identical on every host instead of baking a checkout path in.
MISSING_INPUT: str = "no-such-input"


def write_wav(path: Path) -> Path:
    """Write a short silent WAV the scanners accept as an audio file."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 400)
    return path


def write_cue(path: Path) -> Path:
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


def argv_for(command: str, work: Path) -> list[str]:
    """Build the CLI arguments for one command's recording run.

    Args:
        command: The command path, a key of ``cli_schema.TOOL_IDS``.
        work: An empty scratch directory this call may populate.

    Returns:
        The argv (without ``--json``) that drives *command* to a payload.
    """
    library = work / "library"
    library.mkdir(exist_ok=True)
    wav = library / "track.wav"
    if not wav.exists():
        write_wav(wav)
    out = work / "out"
    out.mkdir(exist_ok=True)

    # ``doctor`` inspects the install, not a library: it takes no arguments,
    # and its payload is valid whether this checkout is healthy or not.
    if command == "doctor":
        return []

    # These commands reach a web service when a file is present.  The schema
    # does not need a lookup to be proved, so they scan an empty directory.
    if command in EMPTY_LIBRARY:
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
        return [str(write_cue(work / "album.cue"))]
    if command == "cue generate":
        # No dry mode: the run writes a sheet, so point it at the scratch tree
        # instead of letting the default put ``album.cue`` in the library.
        return [
            str(library),
            "--output",
            str(out / "album.cue"),
            "--title",
            "Album",
        ]
    if command == "cue split":
        return [str(write_cue(work / "album.cue")), "--output-dir", str(out)]
    if command in {"enhance", "reorganize"}:
        return [str(library), "--dry", "--output-dir", str(out)]
    if command == "fingerprint":
        # A lookup without an API key is a usage error, not a payload.
        return [str(library), "--dry", "--no-lookup"]
    return [str(library), "--dry"]


@contextmanager
def _patched(command: str) -> Iterator[None]:
    """Patch the paths that would batch-run, split audio or touch the network."""
    if command == "mood-analysis-batch":
        from mood_analysis_batch_tagger.core import batch_analysis_engine

        def fake_run_batch(**_kwargs: Any) -> None:
            _kwargs["out_queue"].put(("done", 2, 1, 0, 1, "runs/fake.log"))

        with mock.patch.object(batch_analysis_engine, "run_batch", fake_run_batch):
            yield
        return
    if command == "cue split":
        import audio_suite_shared.cue_cli as cue_cli

        with mock.patch.object(cue_cli, "split_cue_file", lambda *_a, **_k: []):
            yield
        return
    yield


def error_argv_for(command: str, work: Path) -> list[str]:
    """Build argv that makes *command* fail before it does any work.

    The failure a script author is most likely to hit is a mistyped input path,
    so that is what each command is driven with: its normal recording argv with
    the first (path) argument replaced by one that does not exist.  Click
    rejects it while parsing, which is exactly the path that publishes the
    fatal-error document.  The substitute is relative (``MISSING_INPUT``), so
    the message the command prints carries no host path.

    Args:
        command: The command path, a key of ``cli_schema.TOOL_IDS``.
        work: An empty scratch directory, as :func:`argv_for` takes.

    Returns:
        The argv (without ``--json``) that provokes the failure.
    """
    argv = argv_for(command, work)
    if command in NO_INPUT_PATH or not argv:
        return [UNKNOWN_OPTION]
    return [MISSING_INPUT, *argv[1:]]


def capture(command: str, argv: list[str]) -> tuple[int, str, str]:
    """Invoke *command* in JSON mode and return ``(exit_code, stdout, stderr)``."""
    with _patched(command):
        # A nested path (``cue parse``) is two argv tokens, not one name.
        result = CliRunner().invoke(cli, [*command.split(), *argv, "--json"])
    return result.exit_code, result.stdout, result.stderr


def _normalize(value: Any, replacements: Sequence[tuple[str, str]]) -> Any:
    """Return *value* with absolute path prefixes replaced by placeholders.

    A recorded ``scan_path`` or ``cue_path`` is an absolute path on whichever
    machine recorded it.  Committing that would bake a local checkout and
    username into the repository and make a diff depend on the host, so the
    scratch directory becomes ``<run>`` and the checkout ``<repo>``.  The
    conformance gate checks the document's shape, not those literals.
    """
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_normalize(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item, replacements) for key, item in value.items()}
    return value


def _cd_rip_payload() -> dict[str, Any]:
    """Return cd-rip's payload from its own builder (no drive on this host)."""
    from cd_ripper.cli import _rip_payload

    return _rip_payload(
        drive="D:",
        output_dir="out",
        fmt="flac",
        tracks="all",
        verify_mode="twice",
        dry_run=False,
        log_entries=["track 1 done\n"],
        succeeded=2,
        failed=1,
        duration_secs=9.5,
    )


def record_payloads() -> dict[str, dict[str, Any]]:
    """Drive every command in ``TOOL_IDS`` and return its parsed payload.

    Returns:
        Command path to payload, for every command the schema declares.  Host
        paths are normalised to ``<run>``/``<repo>`` so the committed corpus is
        machine-independent.

    Raises:
        RuntimeError: if a command exits unexpectedly or writes no document,
            because a silently empty recording would weaken the corpus.
    """
    recorded: dict[str, dict[str, Any]] = {}
    for command in sorted(TOOL_IDS):
        if command in BUILDER_RECORDED:
            recorded[command] = _cd_rip_payload()
            continue
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "run"
            work.mkdir()
            argv = argv_for(command, work)
            exit_code, stdout, stderr = capture(command, argv)
            if exit_code not in (0, 1) or not stdout.strip():
                raise RuntimeError(
                    f"{command}: exit {exit_code}, stdout={stdout!r}, stderr={stderr!r}"
                )
            replacements = ((str(work), "<run>"), (str(REPO_ROOT), "<repo>"))
            recorded[command] = _normalize(json.loads(stdout), replacements)
    return recorded


def record_error_payloads() -> dict[str, dict[str, Any]]:
    """Drive every command into a fatal error, capturing what it printed.

    The published failure shape is the document the CLI really writes when an
    invocation dies before doing any work - not a hand-built sketch of one.
    Each run must exit with Click's usage-error status and print a document
    whose counters are zero, ``errors`` is 1 and ``error`` is a non-empty
    string; anything else means the recording measured the wrong thing.

    Returns:
        Command path to its fatal-error document, for every command the schema
        declares.  The rejected value is relative (``no-such-input``), so the
        recorded message mentions no host path at all.

    Raises:
        RuntimeError: if a command exits with an unexpected status, prints no
            document, or prints something that is not a fatal document.
    """
    recorded: dict[str, dict[str, Any]] = {}
    for command in sorted(TOOL_IDS):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "run"
            work.mkdir()
            argv = error_argv_for(command, work)
            exit_code, stdout, stderr = capture(command, argv)
            if exit_code != 2 or not stdout.strip():
                raise RuntimeError(
                    f"{command}: expected a usage error (exit 2) with a JSON "
                    f"document, got exit {exit_code}, stdout={stdout!r}, "
                    f"stderr={stderr!r}"
                )
            payload = json.loads(stdout)
            message = payload.get("error")
            if (
                payload.get("errors") != 1
                or not isinstance(message, str)
                or not message
            ):
                raise RuntimeError(
                    f"{command}: printed a document that is not a fatal error: "
                    f"{payload!r}"
                )
            recorded[command] = _normalize(payload, ((str(REPO_ROOT), "<repo>"),))
    return recorded
