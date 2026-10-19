"""
shell_action.py — the argv entry point Explorer invokes for a right-click verb.

Explorer runs::

    "<python>" -m audio_suite_shared.shell_action <verb> "%1" [--dry]

One file is processed, never its whole folder: the conversion and analysis
workers that a batch run discovers and fans out are called directly for the
selected file, so a right-click cannot silently convert or tag an album.

Safety contract (PLAN D60):

* a conversion never overwrites an existing sibling output — it reports the
  collision and exits non-zero;
* tag-writing analysis runs inside an undo batch, so ``undo_tag_edits`` can
  revert what a right-click wrote;
* ``--dry`` writes nothing at all;
* failures exit non-zero and, when run in a console, wait for Enter so the
  message is readable (``AUDIOSUITE_NO_PAUSE=1`` suppresses the wait).

Changed in 1.4.0: new module (Sprint 4 Item 4.1, PLAN D57/D58/D60).
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from collections.abc import Sequence
from queue import Queue
from typing import Any

from .audio_formats import SUPPORTED_EXTENSIONS
from .batch_undo import active_batch
from .shell_integration import VERB_BY_ID, ShellVerb


class _ConsoleSlot:
    """Minimal ``StringVar`` stand-in that prints worker-slot text."""

    def set(self, value: str) -> None:
        if value and value != "IDLE":
            print(f"  {value}")


def _check_path(path: str) -> str | None:
    """Return an error message when *path* is not a supported audio file."""
    if not os.path.isfile(path):
        return f"Not a file: {path}"
    if not path.lower().endswith(SUPPORTED_EXTENSIONS):
        return f"Unsupported audio file: {path}"
    return None


def _run_convert(verb: ShellVerb, path: str, *, dry_run: bool) -> int:
    """Convert the selected file to the verb's format, refusing overwrites."""
    from music_format_converter.core.file_processor import (
        MusicFormatConverterProcessor,
        process_single_file,
    )
    from music_format_converter.core.formats import LOSSY_FORMATS

    output_format = "mp3" if verb.id == "convert_mp3" else "flac"
    directory, filename = os.path.dirname(path), os.path.basename(path)
    output_path = os.path.splitext(path)[0] + f".{output_format}"

    if os.path.exists(output_path):
        print(
            f"[ERROR] Refusing to overwrite the existing file: {output_path}",
            file=sys.stderr,
        )
        return 2

    errors = [0]
    lock = threading.Lock()

    def on_progress(**kwargs: Any) -> None:
        if kwargs.get("n_errors"):
            errors[0] += int(kwargs["n_errors"])
        text = kwargs.get("display_text")
        if text:
            print(text)

    slot_vars: list[Any] = [_ConsoleSlot()]
    slot_queue: Queue[int] = Queue()
    slot_queue.put(0)

    with active_batch("music_format_converter", "file_delete"):
        process_single_file(
            filename,
            directory,
            directory,
            output_format,
            "highest",
            False,
            dry_run,
            LOSSY_FORMATS,
            slot_vars,
            slot_queue,
            lock,
            on_progress,
            processor=MusicFormatConverterProcessor(),
        )

    if dry_run:
        print(f"[DRY RUN] Would write {output_path}")
    return 1 if errors[0] else 0


def _run_analysis(verb: ShellVerb, path: str, *, dry_run: bool) -> int:
    """Analyse (and, when live, tag) the selected file inside an undo batch."""
    directory, name = os.path.dirname(path), os.path.basename(path)
    errors = [0]
    lock = threading.Lock()

    def on_progress(**kwargs: Any) -> None:
        if kwargs.get("n_errors"):
            errors[0] += int(kwargs["n_errors"])
        text = kwargs.get("display_text")
        if text:
            print(text)

    slot_vars = [_ConsoleSlot()]

    if verb.id == "analyze_bpm":
        from bpm_analyzer.core.file_processor import (
            process_single_file as process_bpm_file,
        )

        with active_batch("bpm_analyzer", "tag_edit"):
            process_bpm_file(
                name=name,
                dir_path=directory,
                is_dry_run=dry_run,
                min_bpm=60,
                max_bpm=200,
                analysis_duration=30,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )
    elif verb.id == "analyze_key":
        from key_detector.core.file_processor import (
            KeyDetectorProcessor,
        )
        from key_detector.core.file_processor import (
            process_single_file as process_key_file,
        )

        with active_batch("key_detector", "tag_edit"):
            process_key_file(
                KeyDetectorProcessor(max_workers=1),
                name=name,
                dir_path=directory,
                is_dry_run=dry_run,
                analysis_duration=30,
                slot_vars=slot_vars,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
            )
    else:
        from mood_analyzer.core.file_processor import (
            MoodAnalyzerProcessor,
        )
        from mood_analyzer.core.file_processor import (
            process_single_file as process_mood_file,
        )

        with active_batch("mood_analyzer", "tag_edit"):
            process_mood_file(
                MoodAnalyzerProcessor(max_workers=1),
                name=name,
                dir_path=directory,
                is_dry_run=dry_run,
                analysis_duration=90,
                slot_vars=slot_vars,
                slot_idx=0,
                lock=lock,
                on_progress=on_progress,
            )

    return 1 if errors[0] else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run one shell verb and return a process exit code.

    Args:
        argv: Arguments after ``-m audio_suite_shared.shell_action``;
            defaults to ``sys.argv[1:]``.

    Returns:
        ``0`` on success, ``1`` when the file could not be processed, and
        ``2`` when the requested output already exists (never overwritten).
    """
    parser = argparse.ArgumentParser(
        prog="audiosuite-shell",
        description="Run one AudioSuite-Pro action for a file Explorer selected.",
    )
    parser.add_argument("verb", choices=sorted(VERB_BY_ID))
    parser.add_argument("path", help="The audio file Explorer selected.")
    parser.add_argument(
        "--dry",
        action="store_true",
        help="Analyse/report without writing tags or conversion output.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    problem = _check_path(args.path)
    if problem:
        print(f"[ERROR] {problem}", file=sys.stderr)
        return 1

    verb = VERB_BY_ID[args.verb]
    if verb.id.startswith("convert_"):
        return _run_convert(verb, args.path, dry_run=args.dry)
    return _run_analysis(verb, args.path, dry_run=args.dry)


def _pause_before_close() -> None:
    """Keep a console window open after a failure so the message is readable."""
    if os.environ.get("AUDIOSUITE_NO_PAUSE"):
        return
    try:
        input("Press Enter to close...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        _pause_before_close()
    raise SystemExit(exit_code)
