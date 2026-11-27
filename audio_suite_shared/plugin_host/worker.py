"""worker.py — the subprocess entry that renders one file through a chain.

Run as ``python -m audio_suite_shared.plugin_host.worker <request.json>``.  The
process reads one request, renders one file and exits, because a third-party
plugin is the one thing in the suite that can kill its host: one worker per file
means a plugin that segfaults costs one file, not the batch (F-M1 D-1).

The request is a small JSON document::

    {"version": 1, "input": "in.wav", "output": "out.wav",
     "chain": {"version": 1, "slots": [...]}}

The output is always a 32-bit float WAV, whatever the input format was.  That
is the lossless intermediate the chain works on: a float WAV round-trips every
sample bit-for-bit, which is what lets a bypassed chain be proven to change
nothing.  Writing the user's own format is the caller's job.

The child reports through one JSON line on stdout and its exit code:

=====  ========================================================================
0      ``{"status": "ok", ...}`` — the output file was written
2      ``{"status": "plugin", "plugin": ..., "reason": ...}`` — a plugin failed
3      ``{"status": "usage", "reason": ...}`` — the request or its audio is bad
=====  ========================================================================

No status document carries a filesystem path: the parent already knows the
file, and a status line can reach a log.

Nothing here imports ``pedalboard`` at module import: the plugin host is
imported by tools that only describe a chain, and the render worker is a
separate process that pays that cost for itself.

Changed in 3.0.0: new module — the render worker entry point (F-M1
order-of-work #2).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_suite_shared.plugin_host.chain import (
    ChainPresetError,
    PluginChain,
    PluginSlot,
)
from audio_suite_shared.plugin_host.render import (
    PluginLoadError,
    PluginRenderError,
    SlotEffect,
    render_buffer,
)

#: Schema version of the worker's request document.
REQUEST_VERSION = 1

#: Exit status: the output file was written.
EXIT_OK = 0

#: Exit status: a plugin could not be loaded or applied.
EXIT_PLUGIN = 2

#: Exit status: the request, or the audio it names, could not be read.
EXIT_USAGE = 3

#: Keys one request may carry.  An unknown key is a typo, and ignoring it would
#: silently drop what the writer meant to say.
_REQUEST_KEYS = frozenset({"version", "input", "output", "chain"})


class WorkerRequestError(ValueError):
    """A render request is not this worker's request format."""


@dataclass(frozen=True)
class RenderRequest:
    """One file to render through one chain.

    Attributes
    ----------
    input_path : Path
        The file to decode.
    output_path : Path
        Where the 32-bit float WAV goes.
    chain : PluginChain
        The chain to apply.
    """

    input_path: Path
    output_path: Path
    chain: PluginChain


def read_request(path: Path) -> RenderRequest:
    """Read and validate one render request.

    Parameters
    ----------
    path : Path
        The request JSON file.

    Returns
    -------
    RenderRequest
        The decoded request.

    Raises
    ------
    WorkerRequestError
        The file is missing or unreadable, is not this schema version, names a
        non-WAV output, or holds a chain the preset codec cannot read.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerRequestError("the render request could not be read") from exc
    if not isinstance(document, dict):
        raise WorkerRequestError("a render request must be an object")
    unknown = sorted(set(document) - _REQUEST_KEYS)
    if unknown:
        raise WorkerRequestError(
            f"the render request declares unknown key(s) {unknown}"
        )
    version = document.get("version")
    if version != REQUEST_VERSION:
        raise WorkerRequestError(
            f"the render request uses version {version!r}; this worker reads "
            f"version {REQUEST_VERSION}"
        )
    source = _request_path(document, "input")
    destination = _request_path(document, "output")
    if destination.suffix.lower() != ".wav":
        raise WorkerRequestError(
            "the render worker writes a 32-bit float WAV; the request's output "
            "must end in .wav"
        )
    payload = document.get("chain")
    if not isinstance(payload, dict):
        raise WorkerRequestError("the render request's chain is not an object")
    try:
        chain = PluginChain.from_preset(payload)
    except ChainPresetError as exc:
        raise WorkerRequestError(
            f"the render request's plugin chain is unreadable: {exc}"
        ) from exc
    return RenderRequest(source, destination, chain)


def _request_path(document: dict[str, Any], key: str) -> Path:
    """Return one required path field of a request.

    Parameters
    ----------
    document : dict[str, Any]
        The decoded request.
    key : str
        Field name.

    Returns
    -------
    Path
        The field's value.

    Raises
    ------
    WorkerRequestError
        The field is missing or not text.
    """
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise WorkerRequestError(f"the render request's {key!r} is not a path")
    return Path(value)


def pedalboard_effect(slot: PluginSlot) -> SlotEffect:
    """Load one slot's bundle into its effect.

    Parameters
    ----------
    slot : PluginSlot
        The slot to load.  Its state, when present, is applied to the plugin,
        and so are its parameter overrides.

    Returns
    -------
    SlotEffect
        A callable applying the loaded plugin to a buffer.

    Raises
    ------
    PluginLoadError
        The slot does not name a bundle, or names a parameter the plugin does
        not have.
    Exception
        Whatever ``pedalboard`` raises for a bundle it cannot load; the render
        layer turns that into a slot failure by exception type.
    """
    from audio_suite_shared.plugin_host.scan import _bundle_kind, _plugin_class

    kind = _bundle_kind(Path(slot.plugin_path))
    if kind is None:
        raise PluginLoadError("the slot does not name a .vst3 or .component bundle")
    plugin = _plugin_class(kind)(slot.plugin_path)
    if slot.state is not None:
        plugin.raw_state = slot.state.payload
    for name, value in slot.parameter_overrides.items():
        if name not in plugin.parameters:
            raise PluginLoadError(f"it has no parameter named {name!r}")
        plugin.parameters[name] = value

    def apply(audio: Any, sample_rate: float) -> Any:
        return plugin(audio, sample_rate)

    return apply


def render_request(request: RenderRequest) -> dict[str, object]:
    """Render one request and write its output.

    Parameters
    ----------
    request : RenderRequest
        The file, the destination and the chain.

    Returns
    -------
    dict[str, object]
        The ``{"status": "ok", ...}`` document, with the frame and channel
        counts the write produced.

    Raises
    ------
    PluginRenderError
        A slot's plugin could not be loaded or applied.
    OSError
        The input could not be read or the output could not be written.
    """
    from pedalboard.io import AudioFile

    with AudioFile(str(request.input_path), "r") as source:
        audio = source.read(source.frames)
        sample_rate = source.samplerate
    rendered = render_buffer(request.chain, audio, sample_rate, pedalboard_effect)
    with AudioFile(
        str(request.output_path),
        "w",
        sample_rate,
        rendered.shape[0],
        bit_depth=32,
    ) as sink:
        sink.write(rendered)
    return {
        "status": "ok",
        "frames": int(rendered.shape[1]),
        "channels": int(rendered.shape[0]),
        "sample_rate": int(sample_rate),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Render the request named on the command line.

    Parameters
    ----------
    argv : Sequence[str] | None
        Arguments after the module name; ``None`` reads :data:`sys.argv`.

    Returns
    -------
    int
        An :data:`EXIT_OK`, :data:`EXIT_PLUGIN` or :data:`EXIT_USAGE` status.
    """
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1:
        return _report(
            EXIT_USAGE,
            {"status": "usage", "reason": "the render worker takes one request file"},
        )
    try:
        request = read_request(Path(arguments[0]))
    except WorkerRequestError as exc:
        return _report(EXIT_USAGE, {"status": "usage", "reason": str(exc)})
    try:
        return _report(EXIT_OK, render_request(request))
    except PluginRenderError as exc:
        return _report(
            EXIT_PLUGIN,
            {
                "status": "plugin",
                "plugin": exc.plugin,
                "slot": exc.slot_index,
                "reason": exc.reason,
            },
        )
    except Exception as exc:  # noqa: BLE001 - the child must report, never traceback
        # A decode or write failure: the request named a file the plugin host
        # cannot use.  The type is the whole message because an OSError's text
        # carries the path, and a status line may reach a log (F-M1 D-11).
        return _report(EXIT_USAGE, {"status": "usage", "reason": type(exc).__name__})


def _report(exit_code: int, document: dict[str, object]) -> int:
    """Print one status document and return *exit_code*.

    Parameters
    ----------
    exit_code : int
        The process status.
    document : dict[str, object]
        The status document.  It carries no filesystem path.

    Returns
    -------
    int
        *exit_code*, so the caller can ``return _report(...)``.
    """
    print(json.dumps(document))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
