"""Collect the whole tree under each marker view in one interpreter.

``tests/test_pyproject_config.py`` needs four collections of the real tree —
the default selection plus one per opt-in marker — and used to run a separate
``python -m pytest --collect-only`` for each.  That pays interpreter startup
and the import of every test module four times (about 35 s of the suite for
evidence that is the same work three times over), so the four collections now
happen here, in one process, with the module imports cached after the first.

Run as ``python tests/_collect_views.py <output.json>``.  The payload maps each
view to ``{"returncode": int, "stdout": str}``: a failing collection is data,
not an exception, so the caller can quote pytest's own output in its failure
message.

Changed in 2.1.0: initial version — four whole-tree collect-only subprocesses
in ``tests/test_pyproject_config.py`` became one interpreter (~35 s → ~22 s),
and the ``worker_memory`` view joins the three that were already there.

Changed in 2.1.6: the helper arms a deadline. Twice the suite wedged here -
once on the Python 3.14 CI leg (forty minutes at 6%, cancelled) and once on a
3.14 host, where the process tree showed this helper parked inside its own
in-process collection. Standalone it takes ~20 s, so it is a race, and a
wedged in-process ``pytest.main`` reports nothing at all: the run just stops.
``faulthandler`` now dumps every thread's stack and exits non-zero after the
deadline, so the next occurrence quotes the frame it is stuck in, and the
caller's ``returncode == 0`` assertion fails with that evidence instead of
hanging the leg.
"""

from __future__ import annotations

import contextlib
import faulthandler
import io
import json
import sys
from pathlib import Path

#: How long the whole five-view collection may take before the helper dumps
#: its stacks and exits. Standalone it is ~20 s; the outer test's own
#: subprocess timeout sits above this, so the traceback is what the failure
#: reports.
_COLLECTION_DEADLINE_SECONDS = 300

#: The views collected, in the order the pytest plugin state settles best:
#: the unfiltered collection first, then each opt-in marker on its own.
VIEWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("default", ()),
    ("hardware", ("-m", "hardware")),
    ("real_ml", ("-m", "real_ml")),
    ("worker_memory", ("-m", "worker_memory")),
    ("integration", ("-m", "integration")),
)

_BASE_ARGS: tuple[str, ...] = (
    "--collect-only",
    "-q",
    "--no-cov",
    "-p",
    "no:cacheprovider",
)


def collect_views() -> dict[str, dict[str, object]]:
    """Collect every view and return the payload the caller writes out.

    Returns:
        ``{view: {"returncode": int, "stdout": str}}``.
    """
    import pytest

    payload: dict[str, dict[str, object]] = {}
    for name, extra in VIEWS:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            code = pytest.main([*_BASE_ARGS, *extra])
        payload[name] = {"returncode": int(code), "stdout": buffer.getvalue()}
    return payload


def main(argv: list[str]) -> int:
    """Write the collected views to ``argv[1]``."""
    if len(argv) != 2:
        print("usage: python tests/_collect_views.py <output.json>", file=sys.stderr)
        return 2
    faulthandler.enable()
    faulthandler.dump_traceback_later(_COLLECTION_DEADLINE_SECONDS, exit=True)
    try:
        payload = collect_views()
    finally:
        faulthandler.cancel_dump_traceback_later()
    Path(argv[1]).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
