"""Example_Plugin.pyw — the example plugin's window.

This is what ``[tool].launcher`` in the manifest points the Master Driver at,
and it is also what a user can double-click.  It follows the same launch
sequence as every first-party tool (AGENTS: *Run From the Project's .venv* and
*Startup Pre-Flight Guard*), with one difference: the plugin lives one level
below the suite root, at ``<suite>/plugins/<plugin>/``, so the two directories
that matter are not ``__file__``'s own.

Changed in 2.1.0: new launcher — the example plugin's window (Item 7.2).
Changed in 2.1.0: both roots were off by one level (``parents[1]`` where the
import root is ``parent``), so ``sys.path`` held the suite root, the import of
``example_plugin.tool`` raised ``ModuleNotFoundError``, and the driver reported
the opaque "Module failed: Example Tool".  The pre-flight guard also scanned
the suite root's parent, not the suite.  A launcher named by a manifest is now
locked by ``tests/test_pyw_launchers.py``.
Changed in 2.1.0: forwards the driver's arguments to the window, which moved to
``example_plugin.window`` so the pre-fill is testable, and reads them with
``parse_launch_args`` — the folder and the run mode now arrive pre-filled.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_script_dir = os.path.dirname(os.path.abspath(__file__))
#: The directory holding the ``example_plugin`` package, i.e. ``<suite>/plugins``.
#: It is the launcher's own parent, so ``example_plugin.*`` resolves once it is
#: on ``sys.path``.
_plugin_root = Path(_script_dir).resolve().parent
#: The suite root — the plugin directory's grandparent, which owns ``.venv``.
_suite_root = _plugin_root.parent

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(str(_suite_root))

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(str(_suite_root))

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("Example_Plugin")

if str(_plugin_root) not in sys.path:
    sys.path.insert(0, str(_plugin_root))

from example_plugin.window import main

if __name__ == "__main__":
    main(sys.argv[1:])
