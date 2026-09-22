"""
main.py
Entry point for Audio Refinery.

    python main.py
    python main.py --source "D:/Music" --output "D:/Refined" --auto-start --auto-end
    python main.py --source "D:/Music" --stages declick,enhance --preset Mild
"""

from audio_refinery.app import main

if __name__ == "__main__":
    main()
