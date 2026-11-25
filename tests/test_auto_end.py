"""Lock the one Auto End spelling and the windows that use it.

``tests/test_suite_app_contract.py`` drives every adopter's completion, but it
cannot see this: a window that spells the Auto End sentence for itself, or
schedules its own ``root.destroy``, differs only in a report written by a run
with Auto End armed - and the contract's drives leave it clear. So this lock is
that view:

* the sentence exists once, in the shell, and every window that closes itself
  for Auto End calls ``SuiteApp.close_for_auto_end``, so the text, the marker
  and the close delay cannot drift window by window;
* the time the sentence states is the time the shell waits, at both the 2 s
  default and Album Art Sync's 3 s after a failure;
* a run that wrote no report is marked nowhere, not in the previous run's.

Changed in 2.9.0: new file.  D56 put the marker on the shell for two windows;
the five others and their condition moved onto it in D60; Album Art Sync, the
last module that spelled the sentence itself, moved onto it in D61.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.suite_app import SuiteApp

#: The one sentence, as the closing time it states varies.
SENTENCE = "Auto End enabled - closing in"

#: Every window that closes itself when Auto End is armed.
ADOPTERS = {
    "album_art_sync/app.py": "AudioSuiteV6",
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
    assert offenders == {_SHELL}


def test_every_self_closing_window_uses_the_shell_close() -> None:
    discovered = {
        path.as_posix() for path in _window_modules() if _calls_close_for_auto_end(path)
    }
    assert discovered == set(ADOPTERS)
    for path, class_name in ADOPTERS.items():
        text = Path(path).read_text(encoding="utf-8")
        assert f"class {class_name}(" in text, f"{path} no longer declares {class_name}"


def _probe(tmp_path: Path) -> SuiteApp:
    app = object.__new__(SuiteApp)
    app.root = MagicMock()
    app._log_path = str(tmp_path / "probe_log.txt")
    Path(app._log_path).write_text("PROBE REPORT\n", encoding="utf-8")
    return app


def test_the_marker_and_its_close_are_pinned(tmp_path: Path) -> None:
    app = _probe(tmp_path)
    status = MagicMock()

    app.close_for_auto_end(status=status)

    assert Path(app._log_path).read_text(encoding="utf-8") == (
        "PROBE REPORT\n\n[Auto End enabled - closing in 2 seconds...]\n"
    )
    status.set.assert_called_once_with("Auto End enabled - closing in 2 seconds...")
    app.root.after.assert_called_once_with(2000, app.root.destroy)


def test_the_sentence_states_the_delay_the_shell_waits(tmp_path: Path) -> None:
    """Album Art Sync waits 3 s after a failure, so its line must say three."""
    app = _probe(tmp_path)
    status = MagicMock()

    app.close_for_auto_end(status=status, delay_ms=3000)

    assert (
        Path(app._log_path)
        .read_text(encoding="utf-8")
        .endswith("\n[Auto End enabled - closing in 3 seconds...]\n")
    )
    status.set.assert_called_once_with("Auto End enabled - closing in 3 seconds...")
    app.root.after.assert_called_once_with(3000, app.root.destroy)


def test_a_run_without_a_report_is_marked_nowhere(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A cancelled or failed run has no report to mark, and does not invent one."""
    app = object.__new__(SuiteApp)
    app.root = MagicMock()
    app._log_path = ""

    with caplog.at_level(logging.WARNING):
        app.close_for_auto_end()

    app.root.after.assert_called_once_with(2000, app.root.destroy)
    assert not [r for r in caplog.records if "Auto End" in r.getMessage()]
    assert list(tmp_path.iterdir()) == []
