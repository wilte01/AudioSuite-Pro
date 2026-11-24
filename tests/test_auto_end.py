"""Lock the one Auto End spelling and the windows that use it.

``tests/test_suite_app_contract.py`` drives every adopter's completion, but it
cannot see this: a window that spells the Auto End sentence for itself, or
schedules its own ``root.destroy``, differs only in a report written by a run
with Auto End armed - and the contract's drives leave it clear. So this lock is
that view:

* the sentence exists once, in the shell, plus the one allowlisted module whose
  UI log line carries the close delay (the entry is load-bearing: it must still
  spell the sentence, or it stops excusing anything);
* every window that closes itself for Auto End calls
  ``SuiteApp.close_for_auto_end``, so the marker, the status sentence and the
  2000 ms delay cannot drift window by window;
* the marker's bytes and the close delay are pinned.

Changed in 2.9.0: new file.  D56 put the marker on the shell for two windows;
the five others and their condition moved onto it in D60.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from audio_suite_shared.suite_app import SuiteApp

#: The one sentence; the report marker brackets it and ends it with a newline.
SENTENCE = "Auto End enabled - closing in"

#: Modules that still spell the sentence themselves, with the reason.
OWN_SENTENCE = {
    "album_art_sync/app.py": (
        "its UI log line carries the delay (2 s, or 3 s on the error path) and "
        "is not the report marker"
    ),
}

#: Every window that closes itself when Auto End is armed.
ADOPTERS = {
    "album_genre_tagger/app.py": "GenreConsolidatorApp",
    "genre_sync/app.py": "GenreSetterApp",
    "key_detector/app.py": "KeyDetectorApp",
    "metadata_scrubber/app.py": "MetadataScrubberApp",
    "mood_analyzer/app.py": "MoodAnalyzerApp",
    "replaygain_analyzer/app.py": "ReplayGainAnalyzerApp",
    "tempo_analyzer/app.py": "TempoAnalyzerApp",
}

_SHELL = "audio_suite_shared/suite_app.py"


def _first_party_modules() -> list[Path]:
    """Return shipped modules, without the tests that assert the sentence."""
    return [
        path
        for path in sorted(Path(".").rglob("*.py"))
        if not path.as_posix().startswith(".venv/")
        and "/tests/" not in f"/{path.as_posix()}"
    ]


def _window_modules() -> list[Path]:
    return [
        *sorted(Path(".").glob("*/app.py")),
        *sorted(Path(".").glob("*/ui/app.py")),
    ]


def _calls_close_for_auto_end(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close_for_auto_end"
        for node in ast.walk(tree)
    )


def test_only_the_shell_spells_the_auto_end_sentence() -> None:
    offenders = {
        path.as_posix()
        for path in _first_party_modules()
        if SENTENCE in path.read_text(encoding="utf-8")
    }
    assert offenders, "the scan found no Auto End sentence at all"
    assert offenders - set(OWN_SENTENCE) == {_SHELL}
    for path, reason in OWN_SENTENCE.items():
        assert SENTENCE in Path(path).read_text(encoding="utf-8"), (
            f"{path} no longer spells the sentence, so its entry excuses nothing"
            f" ({reason})"
        )


def test_every_self_closing_window_uses_the_shell_close() -> None:
    discovered = {
        path.as_posix() for path in _window_modules() if _calls_close_for_auto_end(path)
    }
    assert discovered == set(ADOPTERS)
    for path, class_name in ADOPTERS.items():
        text = Path(path).read_text(encoding="utf-8")
        assert f"class {class_name}(" in text, f"{path} no longer declares {class_name}"


def test_the_marker_and_its_close_are_pinned(tmp_path: Path) -> None:
    app = object.__new__(SuiteApp)
    app.root = MagicMock()
    app._log_path = str(tmp_path / "probe_log.txt")
    Path(app._log_path).write_text("PROBE REPORT\n", encoding="utf-8")
    status = MagicMock()

    app.close_for_auto_end(status=status)

    assert Path(app._log_path).read_text(encoding="utf-8") == (
        "PROBE REPORT\n\n[Auto End enabled - closing in 2 seconds...]\n"
    )
    status.set.assert_called_once_with("Auto End enabled - closing in 2 seconds...")
    app.root.after.assert_called_once_with(2000, app.root.destroy)
