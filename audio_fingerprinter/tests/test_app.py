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
    monkeypatch.setattr(
        "audio_fingerprinter.app.suite_config.load_value",
        lambda key, default=None: default,
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
        app.write_mbids = MagicMock()
        app.write_mbids.get.return_value = False
        app.mbid_region = MagicMock()
        app.mbid_region.get.return_value = ""
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
        saved: dict[str, Any] = {}
        monkeypatch.setattr(
            "audio_fingerprinter.app.suite_config.save_value",
            lambda key, value: saved.update({key: value}),
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
        assert built["write_mbids"] is False
        assert built["mbid_region"] == ""
        thread = fake_threading.Thread.call_args
        assert thread.kwargs["target"].__name__ == "_run"
        # An empty region clears any stale stored value rather than
        # writing a blank preference.
        assert saved.get("mbid_region") == ""

    def test_valid_start_threads_mbid_preferences(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.threading", fake_threading)
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", MagicMock())
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        saved: dict[str, Any] = {}
        monkeypatch.setattr(
            "audio_fingerprinter.app.suite_config.save_value",
            lambda key, value: saved.update({key: value}),
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
        app.write_tags.get.return_value = True
        app.write_mbids.get.return_value = True
        app.mbid_region.get.return_value = "gb"
        app.threshold.get.return_value = "0.5"
        app.max_length.get.return_value = "120"
        app.run_mode.get.return_value = "Live Update"
        app.album_mode.get.return_value = False

        app.start_processing()

        assert built["write_mbids"] is True
        # The region reaches the run normalised to the ISO code's
        # canonical upper case, and is persisted for the next launch.
        assert built["mbid_region"] == "GB"
        assert saved.get("mbid_region") == "GB"

    def test_invalid_mbid_region_is_cleared_not_stored(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fake_threading = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.threading", fake_threading)
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", MagicMock())
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        saved: dict[str, Any] = {}
        monkeypatch.setattr(
            "audio_fingerprinter.app.suite_config.save_value",
            lambda key, value: saved.update({key: value}),
        )
        monkeypatch.setattr("audio_fingerprinter.app.FingerprintParams", dict)
        app = self._shell()
        app.folder_path.get.return_value = str(tmp_path)
        app.fpcalc_path.get.return_value = ""
        app.lookup_enabled.get.return_value = False
        app.write_tags.get.return_value = True
        app.mbid_region.get.return_value = "Europe"

        app.start_processing()

        assert saved.get("mbid_region") == ""


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


# ---------------------------------------------------------------------------
# Moved from test_fingerprinter_app.py (iteration-9 G5.1): app class
# definition/TOOL_ID contract, _on_progress listbox streaming, Album Match
# checkbox plumbing into FingerprintParams, and the completion summary.
#
# (The source module's `from __future__ import annotations` import could not
# be carried over — it must remain the first statement of a module — and no
# moved annotation depends on it.)
# ---------------------------------------------------------------------------


class TestAppClassDefinition:
    def test_class_exists(self):
        from audio_fingerprinter.app import FingerprinterApp

        assert FingerprinterApp.__name__ == "FingerprinterApp"

    def test_mixin_and_props(self):
        from audio_fingerprinter import app as app_mod
        from audio_fingerprinter.app import FingerprinterApp
        from audio_suite_shared.ui_helpers import UIHelperMixin

        assert issubclass(FingerprinterApp, UIHelperMixin)
        # TOOL_ID is a module-level constant in app.py, not a class
        # attribute; the previous `... or True` masked that distinction.
        assert app_mod.TOOL_ID == "audio_fingerprinter"
        assert FingerprinterApp.HELP_GUIDE == "Audio_Fingerprinter_User_Guide.docx"

    def test_module_constants(self):
        from audio_fingerprinter.app import DEFAULT_MAX_WORKERS, TOOL_ID
        from audio_suite_shared.constants import DEFAULT_MAX_WORKERS as SHARED_WORKERS

        assert TOOL_ID == "audio_fingerprinter"
        assert DEFAULT_MAX_WORKERS == SHARED_WORKERS

    def test_core_modules_exist(self):
        assert (Path(__file__).parent.parent / "core" / "models.py").is_file()
        assert (Path(__file__).parent.parent / "core" / "fingerprinter.py").is_file()
        assert (Path(__file__).parent.parent / "core" / "acoustid_client.py").is_file()
        assert (Path(__file__).parent.parent / "utils" / "cli_args.py").is_file()

    def test_core_imports(self):
        from audio_fingerprinter.core.models import (
            Fingerprint,
            FingerprintFileResult,
            FingerprintParams,
        )

        params = FingerprintParams()
        assert params.is_dry_run is True
        fp = Fingerprint(duration=1, fingerprint="x")
        assert fp.fingerprint == "x"
        result = FingerprintFileResult("a", "b", "MATCHED")
        assert result.status == "MATCHED"


class TestOnProgress:
    """The Processing-tab log list is populated live via root.after()."""

    def _make_app(self) -> MagicMock:
        from audio_fingerprinter.app import FingerprinterApp

        app = object.__new__(FingerprinterApp)
        app.root = MagicMock()
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()
        app.root.after.side_effect = lambda _ms, fn, *_a: fn()
        return app

    def test_streams_display_text_into_listbox(self):
        app = self._make_app()
        app._on_progress(2, 5, 1, display_text="[MATCHED] track.mp3")
        app.progress.__setitem__.assert_any_call("value", 2)
        app.progress.__setitem__.assert_any_call("maximum", 5)
        app.stats_label.config.assert_called_once()
        app.file_listbox.insert.assert_called_once_with("end", "[MATCHED] track.mp3")
        app.file_listbox.see.assert_called_once()

    def test_no_display_text_skips_listbox(self):
        app = self._make_app()
        app._on_progress(2, 5, 0)
        app.progress.__setitem__.assert_any_call("value", 2)
        app.stats_label.config.assert_called_once()
        app.file_listbox.insert.assert_not_called()
        app.file_listbox.see.assert_not_called()


class TestStartProcessingAlbumMode:
    """The Album Match checkbox must reach FingerprintParams."""

    @staticmethod
    def _make_startable_app(tmp_path) -> MagicMock:
        from audio_fingerprinter.app import FingerprinterApp

        app = object.__new__(FingerprinterApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app.lookup_enabled = MagicMock()
        app.lookup_enabled.get.return_value = True
        app.write_tags = MagicMock()
        app.write_tags.get.return_value = False
        app.write_mbids = MagicMock()
        app.write_mbids.get.return_value = False
        app.mbid_region = MagicMock()
        app.mbid_region.get.return_value = ""
        app.album_mode = MagicMock()
        app.threshold = MagicMock()
        app.threshold.get.return_value = "0.5"
        app.max_length = MagicMock()
        app.max_length.get.return_value = "120"
        app.fpcalc_path = MagicMock()
        app.fpcalc_path.get.return_value = ""
        app.start_btn = MagicMock()
        app.file_listbox = MagicMock()
        app.notebook = MagicMock()
        app._tab_processing = MagicMock()
        app.overall_status = MagicMock()
        return app

    def _start(self, tmp_path, album_mode: bool):
        from unittest.mock import patch

        app = self._make_startable_app(tmp_path)
        app.album_mode.get.return_value = album_mode
        with (
            patch("audio_fingerprinter.app.resolve_fpcalc", return_value="fpcalc"),
            patch.object(type(app), "_resolve_run_api_key", return_value="key"),
            # start_processing persists the MBID region preference; patch
            # so the run never writes to the host's real suite config.
            patch("audio_fingerprinter.app.suite_config.save_value"),
            patch("audio_fingerprinter.app.threading.Thread") as mock_thread,
        ):
            app.start_processing()
        return mock_thread

    def test_album_mode_true_reaches_params(self, tmp_path):
        mock_thread = self._start(tmp_path, album_mode=True)
        mock_thread.assert_called_once()
        params = mock_thread.call_args.kwargs["args"][0]
        assert params.album_mode is True
        assert params.album_min == 3

    def test_album_mode_false_reaches_params(self, tmp_path):
        mock_thread = self._start(tmp_path, album_mode=False)
        params = mock_thread.call_args.kwargs["args"][0]
        assert params.album_mode is False


class TestOnCompleteSummary:
    @staticmethod
    def _make_app(tmp_path) -> MagicMock:
        from audio_fingerprinter.app import FingerprinterApp

        app = object.__new__(FingerprinterApp)
        app.root = MagicMock()
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.file_listbox = MagicMock()
        app.notebook = MagicMock()
        app._tab_results = MagicMock()
        app.start_btn = MagicMock()
        app._log_path = str(tmp_path / "fingerprint_dry_run_log.txt")
        return app

    @staticmethod
    def _counts(album_ambiguous: int = 0) -> dict:
        return {
            "identified": 1,
            "no_match": 0,
            "tagged": 0,
            "lookup_skipped": 0,
            "album_ambiguous": album_ambiguous,
            "errors": 0,
        }

    def _complete(self, tmp_path, counts: dict) -> MagicMock:
        app = self._make_app(tmp_path)
        app._on_complete(
            header=[],
            total=3,
            processed=3,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            results=[],
            counts=counts,
        )
        return app

    def test_album_ambiguous_surfaced_in_summary_and_log(self, tmp_path):
        app = self._complete(tmp_path, self._counts(album_ambiguous=2))
        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Album Ambiguous: 2" in summary_text
        log_text = (tmp_path / "fingerprint_dry_run_log.txt").read_text(
            encoding="utf-8"
        )
        assert "Album ambiguous: 2" in log_text

    def test_zero_album_ambiguous_omits_the_line(self, tmp_path):
        app = self._complete(tmp_path, self._counts(album_ambiguous=0))
        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Album Ambiguous" not in summary_text
        log_text = (tmp_path / "fingerprint_dry_run_log.txt").read_text(
            encoding="utf-8"
        )
        assert "Album ambiguous" not in log_text


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
