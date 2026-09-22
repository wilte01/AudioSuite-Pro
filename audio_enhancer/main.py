#!/usr/bin/env python3
"""
main.py
Audio Enhancer — entry point.

Improves dynamic range, loudness, brightness, and overall clarity of
music files. Part of the audio suite.

Requirements:
    pip install pedalboard mutagen numpy

Usage:
    python main.py
    python main.py --source "D:/Music/Albums" --preset moderate
    python main.py --source "D:/Music" --auto-start --auto-end
"""

import tkinter as tk

from audio_enhancer.app import AudioEnhancerApp


def main() -> None:
    """Main entry point for Audio Enhancer."""
    root = tk.Tk()
    AudioEnhancerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
