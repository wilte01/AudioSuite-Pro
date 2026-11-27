"""A worker stub that dies without a status line, for the crash lock.

The real worker's structured failures go through its exit codes; this stub is
the other case, where an operating-system fault takes the child mid-render and
the parent has to turn a non-zero exit into one failed file.

Changed in 3.0.0: new file — the abort half of the crash-isolation lock.
"""

from __future__ import annotations

import os

os.abort()
