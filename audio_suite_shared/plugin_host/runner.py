"""runner.py — the parent side of the render worker.

Rendering a file is: build one request, run one
:mod:`~audio_suite_shared.plugin_host.worker` process with a wall-clock limit,
and map how it ended to one outcome.  The parent never loads a plugin, so
nothing a plugin does can take the batch down.

Three endings are outcomes here, never exceptions:

* the worker wrote the file — ``"rendered"``;
* the worker reported a plugin failure, could not read its input, or overran
  its timeout — ``"failed"``, with a reason that names the plugin or the file's
  base name but no path;
* the worker died without a status line — ``"failed"``, with the exit code and
  one plain sentence.

:func:`render_files` runs one worker per file and keeps going: a file that
fails costs its own outcome, which is the whole point of moving the plugin out
of process (F-M1 D-1).  The batch-level caveat a run report carries once a
plugin has proven unstable belongs to the Refinery stage (F-M1 order #3), which
owns ``run_outcome``.

Changed in 3.0.0: new module — the render worker's parent side (F-M1
order-of-work #2).
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_suite_shared.plugin_host.chain import PluginChain
from audio_suite_shared.plugin_host.worker import EXIT_OK, REQUEST_VERSION
from audio_suite_shared.secure_subprocess import run_secure_subprocess
from audio_suite_shared.suite_paths import suite_root

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The module the child runs.  It is fixed for every shipped caller; the
#: ``worker=`` parameter exists so a test can drive the timeout and crash paths
#: with a stub that hangs or aborts on demand.
WORKER_MODULE = "audio_suite_shared.plugin_host.worker"

#: Per-file wall clock, the plan's default.  A plugin that overruns it is
#: treated as a crash: the file fails and the batch continues.
DEFAULT_TIMEOUT_SECONDS = 120

#: A file the worker rendered.
RENDERED = "rendered"

#: A file that did not render.
FAILED = "failed"


@dataclass(frozen=True)
class RenderOutcome:
    """How one file's render ended.

    Attributes
    ----------
    input_path : str
        The file that was to be rendered, as the caller named it.
    output_path : str | None
        The file written, or None when nothing was written.
    status : str
        :data:`RENDERED` or :data:`FAILED`.
    reason : str
        One clause naming the failure, empty on success.  It names the plugin
        or the file's base name, never a path.
    plugin : str | None
        The plugin that failed, when the worker identified one.
    exit_code : int | None
        The worker's status, when it ended on its own.
    """

    input_path: str
    output_path: str | None
    status: str
    reason: str = ""
    plugin: str | None = None
    exit_code: int | None = None

    @property
    def ok(self) -> bool:
        """Return whether the file rendered."""
        return self.status == RENDERED


def render_file(
    chain: PluginChain,
    input_path: str | Path,
    output_path: str | Path,
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    worker: str = WORKER_MODULE,
) -> RenderOutcome:
    """Render one file through *chain* in a worker process.

    Parameters
    ----------
    chain : PluginChain
        The chain to apply.
    input_path : str | Path
        The file to decode.
    output_path : str | Path
        Where the 32-bit float WAV goes.
    timeout : int
        Per-file wall clock; a worker still running at the limit is stopped and
        the file fails.
    worker : str
        The ``-m`` module the child runs.  Shipped callers leave it alone.

    Returns
    -------
    RenderOutcome
        The result.  Every failure mode is an outcome, not an exception.
    """
    source = Path(input_path)
    destination = Path(output_path)
    request_path = _write_request(chain, source, destination)
    try:
        try:
            completed = run_secure_subprocess(
                sys.executable,
                ["-m", worker, str(request_path)],
                cwd=str(suite_root()),
                timeout=timeout,
                capture_output=True,
                check=False,
                log_failure=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "plugin render timed out after %s s for %s", timeout, source.name
            )
            return RenderOutcome(
                str(source),
                None,
                FAILED,
                f"the plugin host did not finish within {timeout} s",
            )
    finally:
        request_path.unlink(missing_ok=True)

    document = _status_document(completed.stdout)
    if completed.returncode == EXIT_OK and document.get("status") == "ok":
        if not destination.is_file():
            return RenderOutcome(
                str(source),
                None,
                FAILED,
                "the plugin host reported success but wrote no file",
                exit_code=completed.returncode,
            )
        return RenderOutcome(str(source), str(destination), RENDERED)

    return _failure_outcome(source, document, completed.returncode)


def render_files(
    chain: PluginChain,
    jobs: Sequence[tuple[str | Path, str | Path]],
    *,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    worker: str = WORKER_MODULE,
) -> tuple[RenderOutcome, ...]:
    """Render every job, one worker per file, and keep going after a failure.

    Parameters
    ----------
    chain : PluginChain
        The chain every file renders through.
    jobs : Sequence[tuple[str | Path, str | Path]]
        ``(input, output)`` pairs, in order.
    timeout : int
        Per-file wall clock.
    worker : str
        The ``-m`` module the child runs.

    Returns
    -------
    tuple[RenderOutcome, ...]
        One outcome per job, in job order.  A failed file never stops the rest.
    """
    outcomes: list[RenderOutcome] = []
    for source, destination in jobs:
        outcome = render_file(
            chain, source, destination, timeout=timeout, worker=worker
        )
        if not outcome.ok:
            logger.warning(
                "plugin render failed for %s: %s", Path(source).name, outcome.reason
            )
        outcomes.append(outcome)
    return tuple(outcomes)


def _write_request(chain: PluginChain, source: Path, destination: Path) -> Path:
    """Write one request document to a scratch file beside the output.

    Parameters
    ----------
    chain : PluginChain
        The chain to send.
    source : Path
        The file to decode.
    destination : Path
        The WAV to write.

    Returns
    -------
    Path
        The request file.  The caller deletes it.
    """
    document = {
        "version": REQUEST_VERSION,
        "input": str(source),
        "output": str(destination),
        "chain": chain.to_preset(),
    }
    descriptor, name = tempfile.mkstemp(
        prefix=f"{destination.name}.", suffix=".request.json", dir=destination.parent
    )
    try:
        with open(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def _status_document(stdout: str | bytes | None) -> dict[str, Any]:
    """Return the worker's status document, or an empty mapping.

    Parameters
    ----------
    stdout : str | bytes | None
        The child's captured standard output.

    Returns
    -------
    dict[str, Any]
        The last JSON object the child printed, or ``{}`` when it printed none.
    """
    if isinstance(stdout, bytes):
        stdout = stdout.decode("utf-8", "replace")
    if not stdout:
        return {}
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            document = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(document, dict):
            return document
    return {}


def _failure_outcome(
    source: Path, document: dict[str, Any], returncode: int
) -> RenderOutcome:
    """Map a non-zero worker exit to its outcome.

    Parameters
    ----------
    source : Path
        The file that was to be rendered.
    document : dict[str, Any]
        The worker's status document, empty when it printed none.
    returncode : int
        The worker's exit status.

    Returns
    -------
    RenderOutcome
        A ``"failed"`` outcome naming the plugin, the file's base name or the
        crash, never a path.
    """
    status = document.get("status")
    if status == "plugin":
        plugin = document.get("plugin")
        name = plugin if isinstance(plugin, str) else "a plugin"
        detail = document.get("reason")
        clause = detail if isinstance(detail, str) and detail else "it failed to load"
        return RenderOutcome(
            str(source),
            None,
            FAILED,
            f"plugin {name!r} failed: {clause}",
            plugin=name,
            exit_code=returncode,
        )
    if status == "usage":
        detail = document.get("reason")
        clause = detail if isinstance(detail, str) and detail else "unreadable request"
        return RenderOutcome(
            str(source),
            None,
            FAILED,
            f"{source.name}: {clause}",
            exit_code=returncode,
        )
    return RenderOutcome(
        str(source),
        None,
        FAILED,
        f"the plugin host stopped unexpectedly (exit code {returncode})",
        exit_code=returncode,
    )
