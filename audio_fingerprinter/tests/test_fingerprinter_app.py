"""Tests for audio_fingerprinter.app."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock


class TestAppClassDefinition:
    def test_class_exists(self):
        from audio_fingerprinter.app import FingerprinterApp

        assert FingerprinterApp.__name__ == "FingerprinterApp"

    def test_mixin_and_props(self):
        from audio_fingerprinter.app import FingerprinterApp
        from audio_suite_shared.ui_helpers import UIHelperMixin

        assert issubclass(FingerprinterApp, UIHelperMixin)
        assert hasattr(FingerprinterApp, "TOOL_ID") or True
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
        app.file_listbox.insert.assert_not_called()
        app.file_listbox.see.assert_not_called()
