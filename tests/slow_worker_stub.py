"""A worker stub that never finishes, for the runner's timeout lock.

``render_file`` documents its ``worker=`` parameter as the ``-m`` module the
child runs; pointing it here exercises the timeout path without a plugin that
genuinely hangs.

Changed in 3.0.0: new file — the timeout half of the crash-isolation lock.
"""

from __future__ import annotations

import time

time.sleep(120)
