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
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

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
    Path(argv[1]).write_text(
        json.dumps(collect_views(), ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
