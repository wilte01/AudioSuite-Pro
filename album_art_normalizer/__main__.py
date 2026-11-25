"""Entry point for ``python -m album_art_normalizer``.

Changed in 2.9.0: calls ``configure_logging`` before building the window, the
shared seam that installs the pydub no-window proxy.
"""

import sys
from pathlib import Path

# Changed in 2.5.0: the one module that must derive its own root. This insert is
# what makes ``audio_suite_shared`` importable, so ``suite_paths.suite_root`` -
# which lives inside it - cannot answer here (D-44).
_proj = Path(__file__).resolve().parents[1]
if str(_proj) not in sys.path:
    sys.path.insert(0, str(_proj))

import tkinter as tk  # noqa: E402

from album_art_normalizer.app import ArtNormalizerApp  # noqa: E402
from audio_suite_shared.app_bootstrap import configure_logging  # noqa: E402

if __name__ == "__main__":
    configure_logging("album_art_normalizer")
    root = tk.Tk()
    ArtNormalizerApp(root)
    root.mainloop()
