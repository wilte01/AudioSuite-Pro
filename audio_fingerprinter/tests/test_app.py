import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import audio_fingerprinter.app as fp_mod
from audio_fingerprinter.app import FingerprinterApp


@pytest.fixture()
def app_root(root: tk.Tk) -> Any:
    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture()
def real_app(app_root: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(
        "audio_fingerprinter.app.suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(sys, "argv", ["audio_fingerprinter"])
    return FingerprinterApp(app_root)


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(self, real_app: Any) -> None:
        app = real_app
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() in {"Dry Run", "Live Update"}
        assert app.threshold.get() != ""
        assert app.lookup_enabled.get() in {True, False}

    def test_threshold_and_length_parse_clamp(self, real_app: Any) -> None:
        app = real_app
        app.threshold.set("1.5")
        assert app._parse_threshold() == 1.0
        app.threshold.set("-3")
        assert app._parse_threshold() == 0.0
        app.threshold.set("not-a-number")
        assert app._parse_threshold() == 0.5  # the documented default

        app.max_length.set("9999")
        assert app._parse_max_length() == 600
        app.max_length.set("0")
        assert app._parse_max_length() == 1
        app.max_length.set("nope")
        assert app._parse_max_length() == 120  # DEFAULT_MAX_LENGTH


class TestStartGuardsD3:
    def _shell(self) -> Any:
        app = object.__new__(FingerprinterApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.run_mode = MagicMock()
        app.threshold = MagicMock()
        app.max_length = MagicMock()
        app.fpcalc_path = MagicMock()
        app.lookup_enabled = MagicMock()
        app.write_tags = MagicMock()
        app.album_mode = MagicMock()
        app.api_key = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app.file_listbox = MagicMock()
        app.progress = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        app._cli_api_key = ""
        return app

    def test_missing_folder_shows_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        app.folder_path.get.return_value = ""

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_missing_fpcalc_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path)

        def boom(_path: Any) -> None:
            raise FileNotFoundError("fpcalc absent")

        monkeypatch.setattr(fp_mod, "resolve_fpcalc", boom)

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_lookup_without_api_key_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        app.folder_path.get.return_value = str(tmp_path)
        app.lookup_enabled.get.return_value = True
        app.api_key.get.return_value = ""
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        monkeypatch.setattr(
            "audio_fingerprinter.app.api_key_store.load_api_key", lambda: ""
        )

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_valid_start_threads_params_with_dry_flag(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.threading", fake_threading)
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", MagicMock())
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        built: dict[str, Any] = {}

        class FakeParams:
            def __init__(self, **kwargs: Any) -> None:
                built.update(kwargs)

        monkeypatch.setattr("audio_fingerprinter.app.FingerprintParams", FakeParams)
        app = self._shell()
        app.folder_path.get.return_value = str(tmp_path)
        app.fpcalc_path.get.return_value = ""
        app.lookup_enabled.get.return_value = False
        app.write_tags.get.return_value = False
        app.threshold.get.return_value = "0.5"
        app.max_length.get.return_value = "120"
        app.run_mode.get.return_value = "Dry Run"
        app.album_mode.get.return_value = True

        app.start_processing()

        assert built["is_dry_run"] is True
        assert built["album_mode"] is True
        assert built["threshold"] == 0.5
        thread = fake_threading.Thread.call_args
        assert thread.kwargs["target"].__name__ == "_run"


class TestRunThreadD3:
    def test_run_thread_passes_key_and_params_to_core(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = object.__new__(FingerprinterApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        app.progress = MagicMock()
        app.file_listbox = MagicMock()
        app.api_key = MagicMock()
        app.api_key.get.return_value = ""
        app._cli_api_key = ""
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        calls: dict[str, Any] = {}

        def fake_run_fingerprinting(**kwargs: Any) -> None:
            calls.update(kwargs)

        import audio_fingerprinter.core.file_processor as core

        monkeypatch.setattr(core, "run_fingerprinting", fake_run_fingerprinting)
        monkeypatch.setattr(
            "audio_fingerprinter.app.api_key_store.load_api_key",
            lambda: "stored-key",
        )
        params = MagicMock()
        params.is_dry_run = True
        params.lookup_enabled = True
        params.write_tags = False
        params.album_mode = False
        params.threshold = 0.5
        params.max_length = 120

        app._run(params)

        assert calls["dir_path"] == str(tmp_path)
        assert calls["api_key"] == "stored-key"
        assert calls["params"] is params


class TestProgressD3:
    def test_on_progress_updates_widgets(self) -> None:
        app = object.__new__(FingerprinterApp)
        app.root = MagicMock()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()

        app._on_progress(4, 10, 1, "song.mp3")
        assert app.root.after.call_args.args[0] == 0
        # Execute the scheduled main-thread update against widget stubs.
        update_fn = app.root.after.call_args.args[1]
        update_fn()
        assert app.stats_label.config.call_args.kwargs["text"].startswith(
            "Processed: 4"
        )
        assert app.file_listbox.insert.call_args.args[1] == "song.mp3"
