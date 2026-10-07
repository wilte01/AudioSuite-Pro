"""Tests for audio_fingerprinter.app."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


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
