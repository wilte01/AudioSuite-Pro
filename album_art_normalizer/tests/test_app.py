"""Tests for album_art_normalizer.app.

Changed in 1.0.1: adds ``--size``-to-resolution pre-fill tests.
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_normalization`` into the completion handler (PLAN D117).
"""

import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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


# ── G2.5: --size pre-fills resolution ─────────────────────────────────────


class TestSizePreFill:
    """G2.5: the driver's ``--size`` arg must pre-fill the resolution widget."""

    def test_size_1000_sets_1000x1000(self, app_root, monkeypatch, tmp_path):
        import sys

        from album_art_normalizer.app import ArtNormalizerApp

        monkeypatch.setattr(
            "album_art_normalizer.app.suite_config.load_last_directory", lambda: ""
        )
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "album_art_normalizer",
                str(tmp_path),
                "0",
                "--live",
                "--start",
                "--end",
                "--size",
                "1000",
            ],
        )
        app = ArtNormalizerApp(app_root)
        assert app.resolution.get() == "1000\u00d71000"

    def test_size_with_bare_launch(self, app_root, monkeypatch):
        import sys

        from album_art_normalizer.app import ArtNormalizerApp

        monkeypatch.setattr(
            "album_art_normalizer.app.suite_config.load_last_directory", lambda: ""
        )
        monkeypatch.setattr(sys, "argv", ["album_art_normalizer"])
        app = ArtNormalizerApp(app_root)
        # Default resolution when no --size is 800×800 (the constructor default).
        assert app.resolution.get() == "800\u00d7800"

    def test_size_to_resolution_helper(self):
        from album_art_normalizer.app import _size_to_resolution

        assert _size_to_resolution("800") == "800\u00d7800"
        assert _size_to_resolution("600") == "600\u00d7600"
        assert _size_to_resolution("1200") == "1200\u00d71200"
        assert _size_to_resolution("999") == ""
        assert _size_to_resolution("abc") == ""
        assert _size_to_resolution("") == ""


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler app.py binds
# and land in the report the run writes.
# ---------------------------------------------------------------------------


def _completion_shell(directory: Path) -> ArtNormalizerApp:
    """Shell with only what the completion path touches."""
    root = MagicMock()
    scheduled: list[Any] = []
    root.after.side_effect = lambda delay, fn, *args: scheduled.append((fn, args))

    app = object.__new__(ArtNormalizerApp)
    app.root = root
    app._dir_path = str(directory)
    app._log_path = ""
    app._log_entries = []
    app.progress = MagicMock()
    app.stats_label = MagicMock()
    app.file_listbox = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app._tab_results = MagicMock()
    app.start_btn = MagicMock()
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app._scheduled = scheduled
    return app


def _flush(app: ArtNormalizerApp) -> None:
    """Run every widget update the handler marshalled through ``root.after``."""
    for fn, args in list(app._scheduled):
        fn(*args)
    app._scheduled.clear()


class TestCompletionSeam:
    """``run_normalization`` publishes into the handler ``app.py`` binds."""

    @staticmethod
    def _fake_normalize_single_file(**kwargs: Any) -> None:
        """Stand in for the per-file worker, reporting one of three outcomes."""
        outcomes = {
            "a.wav": {"n_skipped": 0, "n_errors": 0},
            "b.wav": {"n_skipped": 1, "n_errors": 0},
            "c.wav": {"n_skipped": 0, "n_errors": 1},
        }
        progress = kwargs["on_progress"]
        outcome = outcomes[kwargs["name"]]
        progress(
            n_skipped=outcome["n_skipped"],
            n_errors=outcome["n_errors"],
            display_text=f"[OK] {kwargs['name']}",
            log_text=f"{kwargs['name']}\n",
        )

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the report and the log this run writes."""
        from album_art_normalizer.core import file_processor

        for name in ("a.wav", "b.wav", "c.wav"):
            (tmp_path / name).write_bytes(b"")
        app = _completion_shell(tmp_path)

        with patch.object(
            file_processor,
            "_normalize_single_file",
            side_effect=self._fake_normalize_single_file,
        ):
            file_processor.run_normalization(
                dir_path=str(tmp_path),
                target_size=(800, 800),
                on_progress=app._on_progress,
                on_complete=app._on_complete,
                on_error=MagicMock(),
                is_dry_run=True,
            )

        _flush(app)

        # ``processed - skipped - errors``: the panel must not repeat a total.
        app.summary_label.config.assert_called_with(
            text=("Files examined: 3\nImages updated: 1\nSkipped: 1\nErrors: 1")
        )
        report = (tmp_path / "art_normalize_log.txt").read_text(encoding="utf-8")
        for name in ("a.wav", "b.wav", "c.wav"):
            assert f"[OK] {name}" in report

    @pytest.mark.parametrize(
        "field",
        ["total", "processed", "skipped", "errors", "duration_secs", "log_entries"],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        """A dropped field names itself instead of rendering a plausible zero.

        Regression: this app's ``on_complete`` used to read each field with
        ``kw.get(field, 0)``, so a renamed or dropped key wrote ``Errors: 0``
        and ``Images updated: 3`` into a finished report.
        """
        app = _completion_shell(tmp_path)
        payload: dict[str, Any] = {
            "total": 3,
            "processed": 3,
            "skipped": 1,
            "errors": 1,
            "duration_secs": 1.0,
            "log_entries": ["line\n"],
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            app._on_complete(**payload)

        assert field in str(caught.value)
        assert not (tmp_path / "art_normalize_log.txt").exists()
