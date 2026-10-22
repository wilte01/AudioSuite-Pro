"""
tests/test_package_entry_stubs.py - smoke tests for the package-level entry
points (Stage 3, item D1 / audit A4).

The audit's 0% census missed these tiny modules (5 ``main.pyw`` stubs, three
``__main__``/``main`` bootstrap modules and one ``ui/__init__`` re-export),
but the stage gate is "zero production modules at 0% coverage", so each one
must execute in the suite:

- ``main.pyw`` stubs are import-only bootstrap files: their only measurable
  statements are the two import lines, then the ``if __name__ == "__main__"``
  guard (coverage-excluded). The test executes each shipped file under a
  non-``__main__`` name, so no GUI is built.
- ``lyrics_manager/__main__.py`` and ``audio_enhancer/main.py`` launch a real
  Tk root, so the launcher's real path is executed with ``tk.Tk`` and the app
  class mocked - the same ``exec``-the-shipped-source pattern
  ``tests/test_pyw_launchers.py`` established. (The plan D1 sketch proposed
  ``python -m lyrics_manager --help``; that is invalid for this suite: the
  module ignores argv and opens a real GUI, which would hang a headless run.
  The exec form exercises the exact same launch path with no hang risk.)
- ``tag_field_updater/__main__.py`` *does* parse argv (argparse
  ``--directory``), so its ``--help``/default/``--directory`` contracts are
  tested directly.

Changed in 2.0.0: adds ``stem_separator`` to the first-party module set the
exec probe restores (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The five bare ``main.pyw`` stubs: two import lines, then the guard.
PYW_STUBS: tuple[str, ...] = (
    "master_driver",
    "bpm_analyzer",
    "metadata_scrubber",
    "album_art_sync",
    "album_art_normalizer",
)


def _exec_entry(path: Path, name: str, package: str | None = None) -> dict[str, Any]:
    """Exec an entry file under ``__name__`` set to *name*.

    Args:
        path: Absolute path of the entry file to execute.
        name: Value for the ``__name__`` global - ``"__main__"`` runs the
            launch guard, any other name executes the top level only.
        package: Value for ``__package__`` - required for entries that use
            relative imports (``from .app import ...``).

    Returns:
        The exec namespace, for assertions on what the file defined.

    Raises:
        Nothing by design; any escaping exception fails the calling test.
    """
    namespace: dict[str, Any] = {"__name__": name, "__file__": str(path)}
    if package is not None:
        namespace["__package__"] = package
    try:
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    except (SystemExit, ImportError):
        # Handled at the call site (SystemExit from argparse --help, imports
        # failing); leaving the exec'd file's own namespace untouched.
        raise
    return namespace


#: First-party top-level packages whose modules must NOT be left cached by an
#: exec probe. Third-party entries (e.g. numpy's C extensions) must never be
#: deleted - they refuse to load twice per process.
_FIRST_PARTY: tuple[str, ...] = (
    "audio_suite_shared",
    "album_art_normalizer",
    "album_art_sync",
    "album_genre_tagger",
    "asx_extractor",
    "audio_enhancer",
    "audio_fingerprinter",
    "audio_normalizer",
    "audio_refinery",
    "bpm_analyzer",
    "cd_ripper",
    "file_reorganizer",
    "genre_sync",
    "key_detector",
    "library_stats",
    "lyrics_manager",
    "master_driver",
    "metadata_scrubber",
    "mood_analyzer",
    "mood_analysis_batch_tagger",
    "noise_reduction",
    "music_format_converter",
    "pop_click_remover",
    "replaygain_analyzer",
    "silence_trimmer",
    "stem_separator",
    "tag_editor",
    "tag_field_updater",
    "tempo_analyzer",
)


@pytest.fixture()
def pristine_modules():
    """Snapshot ``sys.modules`` around a test and undo first-party imports.

    The ``exec`` tests below import package modules as a side effect. Without
    cleanup those cached entries change which branch other tests exercise:
    ``TestGenericStartupFailureIsWitnessed[Tag_Field_Updater.pyw-tag_field_updater]``
    relies on ``tag_field_updater.ui`` NOT being resolvable through its
    stubbed parent. Restoring first-party names to the pre-test set keeps the
    launchers' earlier test contract intact while leaving third-party
    extension modules alone.
    """
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        before = frozenset(sys.modules)
        try:
            yield
        finally:
            added = [
                name
                for name in sys.modules
                if name not in before
                and any(
                    name == pkg or name.startswith(pkg + ".") for pkg in _FIRST_PARTY
                )
            ]
            for name in added:
                module = sys.modules.get(name)
                if module is None:
                    continue
                # Deleting a child from sys.modules leaves its attribute bound
                # on the parent package; a later ``from parent import child``
                # would then bind the stale module object. Scrub it too.
                parent_name, _, attr = name.rpartition(".")
                if parent_name:
                    parent = sys.modules.get(parent_name)
                    if parent is not None and getattr(parent, attr, None) is module:
                        delattr(parent, attr)
                del sys.modules[name]

    return _scope


@pytest.fixture(autouse=True)
def _pristine_modules(pristine_modules):
    """Apply the module-set restoration to every test in this module."""
    with pristine_modules():
        yield


@pytest.mark.parametrize("tool_id", PYW_STUBS)
class TestPywStubsImportCleanly:
    """Each package-level ``main.pyw`` must import its app entry cleanly."""

    def test_stub_executes_without_building_a_gui(self, tool_id: str) -> None:
        path = REPO_ROOT / tool_id / "main.pyw"
        namespace = _exec_entry(path, "aos_entry_probe")
        # The guard block is the launch path; under a non-main name the stub
        # only binds its imports. Any import failure surfaces here.
        assert "tk" in namespace
        assert any(k for k in namespace if k not in {"__name__", "__file__", "tk"})


def test_pyw_stub_census_found_every_stub() -> None:
    """Non-vacuity: the table matches the shipped ``*/main.pyw`` files."""
    found = sorted(str(p.relative_to(REPO_ROOT)) for p in REPO_ROOT.glob("*/main.pyw"))
    assert len(found) == len(PYW_STUBS), (found, PYW_STUBS)


class TestAlbumArtNormalizerMainStub:
    """``python -m album_art_normalizer``: module bootstrap without argparse."""

    def test_top_level_executes(self) -> None:
        path = REPO_ROOT / "album_art_normalizer" / "__main__.py"
        namespace = _exec_entry(path, "aos_entry_probe")
        assert "ArtNormalizerApp" in namespace


class TestAudioEnhancerMainBootstrap:
    """``audio_enhancer/main.py`` builds the app and enters the loop."""

    def test_main_builds_app_and_mainloops(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tkinter

        import audio_enhancer.app as app_pkg

        fake_root = MagicMock()
        fake_app = MagicMock()
        monkeypatch.setattr(tkinter, "Tk", lambda: fake_root)
        monkeypatch.setattr(app_pkg, "AudioEnhancerApp", fake_app)

        namespace = _exec_entry(REPO_ROOT / "audio_enhancer" / "main.py", "__main__")

        fake_app.assert_called_once_with(fake_root)
        fake_root.mainloop.assert_called_once_with()
        assert "main" in namespace


class TestLyricsManagerMainBootstrap:
    """``python -m lyrics_manager``: logging, theme, app, mainloop, in order."""

    def test_main_call_sequence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import tkinter

        import audio_suite_shared.app_bootstrap as bootstrap_pkg
        import audio_suite_shared.styles as styles_pkg
        import lyrics_manager.app as app_pkg

        fake_root = MagicMock()
        fake_app = MagicMock()
        calls: list[str] = []

        def _configure(program_name: str) -> None:
            calls.append(f"log:{program_name}")

        def _theme() -> None:
            calls.append("theme")

        monkeypatch.setattr(tkinter, "Tk", lambda: fake_root)
        monkeypatch.setattr(bootstrap_pkg, "configure_logging", _configure)
        monkeypatch.setattr(styles_pkg, "bootstrap_theme", _theme)
        monkeypatch.setattr(app_pkg, "LyricsManagerApp", fake_app)

        _exec_entry(
            REPO_ROOT / "lyrics_manager" / "__main__.py", "__main__", "lyrics_manager"
        )

        assert calls == ["log:lyrics_manager", "theme"]
        fake_app.assert_called_once_with(fake_root)
        fake_root.mainloop.assert_called_once_with()


class TestTagFieldUpdaterCliEntry:
    """``python -m tag_field_updater`` parses --directory via argparse."""

    def _exec_main(self) -> None:
        _exec_entry(
            REPO_ROOT / "tag_field_updater" / "__main__.py",
            "__main__",
            "tag_field_updater",
        )

    def test_help_lists_directory_and_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import tag_field_updater.ui.app as app_pkg

        monkeypatch.setattr(app_pkg, "main", MagicMock())
        monkeypatch.setattr(sys, "argv", ["tag_field_updater", "--help"])

        with pytest.raises(SystemExit) as exit_exc:
            self._exec_main()

        assert exit_exc.value.code == 0
        assert "--directory" in capsys.readouterr().out

    def test_no_args_starts_without_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import tag_field_updater.ui.app as app_pkg

        main = MagicMock()
        monkeypatch.setattr(app_pkg, "main", main)
        monkeypatch.setattr(sys, "argv", ["tag_field_updater"])

        self._exec_main()

        main.assert_called_once_with(directory=None)

    def test_directory_flag_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import tag_field_updater.ui.app as app_pkg

        main = MagicMock()
        monkeypatch.setattr(app_pkg, "main", main)
        monkeypatch.setattr(
            sys, "argv", ["tag_field_updater", "--directory", str(tmp_path)]
        )

        self._exec_main()

        main.assert_called_once_with(directory=str(tmp_path))


class TestTagFieldUpdaterUiExports:
    """``tag_field_updater/ui/__init__.py`` re-exports the app class."""

    def test_public_surface(self) -> None:
        from tag_field_updater import ui
        from tag_field_updater.ui.app import TagFieldUpdaterApp as real_app

        assert ui.__all__ == ["TagFieldUpdaterApp"]
        assert ui.TagFieldUpdaterApp is real_app
