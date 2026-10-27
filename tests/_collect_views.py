"""Collect the whole tree under each marker view, one process per view.

``tests/test_pyproject_config.py`` needs a collection of the real tree for the
default selection and for each opt-in marker.  Running each of those as its own
``python -m pytest --collect-only`` pays interpreter startup and the import of
every test module once per view, so 2.1.0 moved all five into a single
interpreter with an in-process ``pytest.main``.

That failed intermittently and silently.  A wedged in-process collection
prints nothing: the Python 3.14 CI leg spent forty minutes at 6% on it and had
to be cancelled, a local 3.14 run parked in the same place, and the guard added
in 2.1.6 later caught a third occurrence with the stack parked inside pytest's
own ``_do_configure`` hook chain.  So the saving is not worth it: each view now
runs in a child of this module, which is the shape that never wedged, keeps
four of the five imports shared through the filesystem cache, and cannot take
the suite with it - a child that stalls hits its deadline, dumps every thread's
stack and exits non-zero, and the caller reports that view by name.

Run as ``python tests/_collect_views.py <output.json>``.  The payload maps each
view to ``{"returncode": int, "stdout": str}``: a failing collection is data,
not an exception, so the caller can quote pytest's own output in its failure
message.

Changed in 2.1.0: initial version - four whole-tree collect-only subprocesses
in ``tests/test_pyproject_config.py`` became one interpreter (~35 s -> ~22 s),
and the ``worker_memory`` view joined the three that were already there.
Changed in 2.1.6: one child process per view, each with a faulthandler deadline
and a parent-side timeout. The single-interpreter version wedged three times in
its in-process ``pytest.main``, once costing a forty-minute cancelled CI leg,
and reported nothing when it did.
"""

from __future__ import annotations

import contextlib
import faulthandler
import io
import json
import subprocess
import sys
from pathlib import Path

#: The marker views to collect, in the order the pytest plugin state settles
#: best: the unfiltered collection first, then each opt-in marker on its own.
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

#: The flag that puts this module into single-view child mode.
_CHILD_FLAG = "--collect-view"

#: A view takes a few seconds; this is the point at which it is wedged, not
#: slow. A child that reaches it dumps every thread's stack and exits non-zero.
_VIEW_DEADLINE_SECONDS = 120

#: The parent's own bound, above five child deadlines, so an unkillable child
#: still fails the caller instead of the runner.
_TOTAL_DEADLINE_SECONDS = 900


def collect_view(name: str) -> dict[str, object]:
    """Collect one marker view in this process.

    Args:
        name: A view name from :data:`VIEWS`.

    Returns:
        ``{"returncode": int, "stdout": str}`` - pytest's exit code and output.
    """
    import pytest

    extra = dict(VIEWS)[name]
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = pytest.main([*_BASE_ARGS, *extra])
    return {"returncode": int(code), "stdout": buffer.getvalue()}


def _collect_view_in_child(name: str) -> dict[str, object]:
    """Run one view in a child process, so a wedge cannot reach this one.

    Args:
        name: A view name from :data:`VIEWS`.

    Returns:
        The child's payload, or a payload carrying its failure - a timeout or
        an unparseable answer is data the caller's assertion can quote.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), _CHILD_FLAG, name],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_VIEW_DEADLINE_SECONDS + 30,
        )
    except subprocess.TimeoutExpired:
        # Nothing to quote: the child's own deadline fires 30 s earlier and
        # its stack dump comes back through the branch below, so reaching this
        # one means the child could not answer even that.
        return {
            "returncode": -1,
            "stdout": (
                f"the {name} view did not answer within {_VIEW_DEADLINE_SECONDS + 30}s"
            ),
        }

    if result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            return payload

    return {
        "returncode": result.returncode,
        "stdout": (
            f"the {name} view's child exited {result.returncode}\n"
            f"{result.stdout}\n{result.stderr}"
        ),
    }


def collect_views() -> dict[str, dict[str, object]]:
    """Collect every view, each in its own child process.

    Returns:
        ``{view: {"returncode": int, "stdout": str}}``, in :data:`VIEWS` order.
    """
    return {name: _collect_view_in_child(name) for name, _ in VIEWS}


def _emit_view(name: str) -> int:
    """Child mode: collect one view and write its payload to stdout.

    Exits 0 whenever it produced a payload - pytest's own exit code rides in
    that payload, so the parent reports one shape for "collected, with a
    non-zero code" and reserves a non-zero exit for "did not answer".
    """
    faulthandler.enable()
    faulthandler.dump_traceback_later(_VIEW_DEADLINE_SECONDS, exit=True)
    try:
        payload = collect_view(name)
    finally:
        faulthandler.cancel_dump_traceback_later()
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def main(argv: list[str]) -> int:
    """Write the collected views to ``argv[1]``, or collect one view for a caller."""
    if len(argv) == 3 and argv[1] == _CHILD_FLAG:
        return _emit_view(argv[2])
    if len(argv) != 2:
        print("usage: python tests/_collect_views.py <output.json>", file=sys.stderr)
        return 2

    faulthandler.enable()
    faulthandler.dump_traceback_later(_TOTAL_DEADLINE_SECONDS, exit=True)
    try:
        payload = collect_views()
    finally:
        faulthandler.cancel_dump_traceback_later()
    Path(argv[1]).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
