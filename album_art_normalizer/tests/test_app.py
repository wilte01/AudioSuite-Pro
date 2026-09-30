import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from album_art_normalizer.app import ArtNormalizerApp


@pytest.fixture()
def app_root(root: tk.Tk) -> Any:
    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


def _pinned_app(app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Real app with the Master-Driver CLI handshake neutralised."""
    monkeypatch.setattr(
        "album_art_normalizer.app.suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(sys, "argv", ["album_art_normalizer"])
    return ArtNormalizerApp(app_root)


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


def _shell() -> Any:
    app = object.__new__(ArtNormalizerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.resolution = MagicMock()
    app.run_mode = MagicMock()
    app.overall_status = MagicMock()
    app.notebook = MagicMock()
    app.start_btn = MagicMock()
    app._tab_processing = MagicMock()
    return app


class TestRealAppConstructionD3:
    def test_full_ui_builds(
        self, app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _pinned_app(app_root, monkeypatch)
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() in {"Dry Run", "Live Update"}


class TestStartProcessingD3:
    def _shell(self) -> Any:
        app = object.__new__(ArtNormalizerApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.resolution = MagicMock()
        app.run_mode = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        return app

    def test_missing_folder_warns(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("album_art_normalizer.app.messagebox", dialogs)
        app.folder_path.get.return_value = "  "

        app.start_processing()

        dialogs.showwarning.assert_called_once()

    def test_invalid_resolution_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("album_art_normalizer.app.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path)
        app.resolution.get.return_value = "not-a-resolution"

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_valid_start_threads_with_dry_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        import album_art_normalizer.app as app_mod
        from album_art_normalizer.core.art_processor import RESOLUTION_MAP

        app = self._shell()
        fake_threading = MagicMock()
        monkeypatch.setattr(app_mod, "threading", fake_threading)
        monkeypatch.setattr("album_art_normalizer.app.messagebox", MagicMock())
        app.folder_path.get.return_value = str(tmp_path)
        app.resolution.get.return_value = next(iter(RESOLUTION_MAP))
        app.run_mode.get.return_value = "Dry Run"

        app.start_processing()

        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_run_normalization", app)
        args = thread.kwargs["args"]
        assert args[0] == str(tmp_path)
        assert args[1] == RESOLUTION_MAP[next(iter(RESOLUTION_MAP))]
        assert args[2] is True  # dry run flag reached the worker


class TestRunNormalizationD3:
    def test_worker_calls_core_with_dry_flag_and_logs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:

        app = globals()["_shell"]()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()
        calls: dict[str, Any] = {}
        folder_jpg_calls: list[tuple[Path, bool]] = []

        def fake_process_folder_jpg(directory: Path, dry_run: bool) -> str | None:
            folder_jpg_calls.append((directory, dry_run))
            return "kept"

        monkeypatch.setattr(
            "album_art_normalizer.app.process_folder_jpg",
            fake_process_folder_jpg,
        )

        def fake_run_normalization(**kwargs: Any) -> None:
            calls.update(kwargs)

        monkeypatch.setattr(
            "album_art_normalizer.core.file_processor.run_normalization",
            fake_run_normalization,
        )

        app._run_normalization(str(tmp_path), (800, 800), False)

        assert folder_jpg_calls[0] == (tmp_path, False)
        assert calls["dir_path"] == str(tmp_path)
        assert calls["is_dry_run"] is False
        assert calls["target_size"] == (800, 800)
        assert app._log_entries, "the live session opened its log"
        assert "Embedded target: 800\u00d7800" in app._log_entries[3]
