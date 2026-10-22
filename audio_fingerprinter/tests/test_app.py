"""Tests for audio_fingerprinter.app.

Changed in 1.2.0: covers the MusicBrainz / ISRC toggles reaching
``FingerprintParams``.
Changed in 1.2.0: covers the ISRC submission outcome on the Results tab and
its record for the Master Driver batch report (``_surface_isrc_outcome``),
including the manifest-id lock the driver's lookup depends on.
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_fingerprinting`` into the completion handler (PLAN D117).
"""

import sys
import tkinter as tk
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

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
        app.musicbrainz = MagicMock()
        app.musicbrainz.get.return_value = False
        app.write_isrc = MagicMock()
        app.write_isrc.get.return_value = False
        app.submit_isrc = MagicMock()
        app.submit_isrc.get.return_value = False
        app.mb_token = MagicMock()
        app.mb_token_status = MagicMock()
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
        params.submit_isrc = False

        app._run(params)

        assert calls["dir_path"] == str(tmp_path)
        assert calls["api_key"] == "stored-key"
        assert calls["params"] is params
        # No submission, so no credential is built or handed over.
        assert calls["mb_auth"] is None

    def test_run_thread_hands_over_credentials_only_when_submitting(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from audio_fingerprinter.core.musicbrainz_client import MBAuth

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

        import audio_fingerprinter.core.file_processor as core

        monkeypatch.setattr(core, "run_fingerprinting", lambda **kw: calls.update(kw))
        monkeypatch.setattr(
            "audio_fingerprinter.app.mb_token_store.build_auth",
            lambda: MBAuth(token="tok"),
        )
        params = MagicMock()
        params.is_dry_run = False
        params.submit_isrc = True
        params.musicbrainz = True
        params.lookup_enabled = True
        params.write_tags = False
        params.album_mode = False
        params.threshold = 0.5
        params.max_length = 120

        app._run(params)

        assert calls["mb_auth"].token == "tok"


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
        app.musicbrainz = MagicMock()
        app.musicbrainz.get.return_value = False
        app.write_isrc = MagicMock()
        app.write_isrc.get.return_value = False
        app.submit_isrc = MagicMock()
        app.submit_isrc.get.return_value = False
        app.mb_token = MagicMock()
        app.mb_token_status = MagicMock()
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
        app.isrc_label = MagicMock()
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

    def test_isrc_submission_is_recorded_in_the_log(self, tmp_path):
        app = self._make_app(tmp_path)
        app._on_complete(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            results=[],
            counts=self._counts(),
            isrc_submission={
                "mode": "live",
                "status": "no auth",
                "recordings": 1,
                "isrcs": 2,
                "reason": "No MusicBrainz token is configured.",
            },
        )
        log_text = (tmp_path / "fingerprint_dry_run_log.txt").read_text(
            encoding="utf-8"
        )
        assert "ISRC submission: no auth (2 ISRC(s), 1 recording(s))" in log_text
        assert "No MusicBrainz token is configured." in log_text


class TestIsrcOutcomeOnTheResultsTab:
    """A refused submission is visible on the Results tab, not only in the log."""

    @staticmethod
    def _app(tmp_path: Path) -> Any:
        app = TestOnCompleteSummary._make_app(tmp_path)
        return app

    def _complete(self, tmp_path: Path, submission: dict[str, Any] | None) -> Any:
        app = self._app(tmp_path)
        app._on_complete(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            results=[],
            counts=TestOnCompleteSummary._counts(),
            isrc_submission=submission,
        )
        return app

    def test_rejected_submission_is_shown_with_its_reason(self, tmp_path: Path):
        app = self._complete(
            tmp_path,
            {
                "mode": "live",
                "status": "rejected",
                "recordings": 1,
                "isrcs": 2,
                "reason": "HTTP 400: the recording id was not accepted",
            },
        )

        text = app.isrc_label.config.call_args.kwargs["text"]
        assert "ISRC submission: rejected (2 ISRC(s), 1 recording(s))" in text
        assert "HTTP 400: the recording id was not accepted" in text
        assert app.isrc_label.config.call_args.kwargs["fg"] == fp_mod.styles.COLOR_ERROR

    def test_offline_submission_is_shown_as_a_problem(self, tmp_path: Path):
        app = self._complete(
            tmp_path,
            {
                "mode": "live",
                "status": "offline",
                "recordings": 1,
                "isrcs": 1,
                "reason": "Network error submitting to MusicBrainz: timed out",
            },
        )

        text = app.isrc_label.config.call_args.kwargs["text"]
        assert "ISRC submission: offline" in text
        assert "timed out" in text
        assert app.isrc_label.config.call_args.kwargs["fg"] == fp_mod.styles.COLOR_ERROR

    def test_accepted_submission_is_shown_without_alarm(self, tmp_path: Path):
        app = self._complete(
            tmp_path,
            {
                "mode": "live",
                "status": "ok",
                "recordings": 1,
                "isrcs": 2,
                "reason": "",
            },
        )

        text = app.isrc_label.config.call_args.kwargs["text"]
        assert "ISRC submission: ok (2 ISRC(s), 1 recording(s))" in text
        assert app.isrc_label.config.call_args.kwargs["fg"] == (
            fp_mod.styles.COLOR_SUCCESS
        )

    def test_no_submission_leaves_the_label_empty(self, tmp_path: Path):
        app = self._complete(tmp_path, None)

        app.isrc_label.config.assert_called_once_with(text="", fg=fp_mod.styles.FG_MAIN)


class TestIsrcOutcomeReachesTheDriver:
    """The run note the Master Driver reads must be keyed by the manifest id."""

    def test_recorded_note_carries_the_status_and_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[tuple[str, str]] = []
        monkeypatch.setattr(
            fp_mod,
            "record_outcome",
            lambda tool_id, note: recorded.append((tool_id, note)),
        )
        app = TestOnCompleteSummary._make_app(tmp_path)

        app._on_complete(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            results=[],
            counts=TestOnCompleteSummary._counts(),
            isrc_submission={
                "mode": "live",
                "status": "not authorised",
                "recordings": 1,
                "isrcs": 1,
                "reason": "HTTP 403: the token lacks the submit_isrc scope",
            },
        )

        assert len(recorded) == 1
        tool_id, note = recorded[0]
        assert tool_id == fp_mod.DRIVER_TOOL_ID
        assert "ISRC submission: not authorised" in note
        assert "submit_isrc scope" in note

    def test_the_note_is_readable_by_the_driver(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real write, read back the way the driver reads it."""
        from audio_suite_shared.run_outcome import read_outcome

        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = TestOnCompleteSummary._make_app(tmp_path)

        app._on_complete(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            results=[],
            counts=TestOnCompleteSummary._counts(),
            isrc_submission={
                "mode": "live",
                "status": "rejected",
                "recordings": 1,
                "isrcs": 2,
                "reason": "HTTP 400: the recording id was not accepted",
            },
        )

        note = read_outcome(fp_mod.DRIVER_TOOL_ID)
        assert "ISRC submission: rejected (2 ISRC(s), 1 recording(s))" in note
        assert "HTTP 400: the recording id was not accepted" in note

    def test_driver_tool_id_is_the_manifest_id(self):
        """A renamed manifest must fail here, not silently lose the note."""
        from audio_suite_shared.tool_plugin import get_registry

        manifest_ids = {m.id for m in get_registry().all}

        assert fp_mod.DRIVER_TOOL_ID in manifest_ids


class TestStartGuardsIsrcSubmission:
    """Pre-flight: submission needs the lookup, and a live run needs a token."""

    def _shell(self) -> Any:
        app = TestStartGuardsD3()._shell()
        app.submit_isrc.get.return_value = True
        app.musicbrainz.get.return_value = False
        app.lookup_enabled.get.return_value = False
        return app

    def test_submission_without_musicbrainz_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        dialogs.showerror.assert_called_once()
        assert "MusicBrainz" in dialogs.showerror.call_args.args[1]

    def test_live_submission_without_a_token_shows_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from audio_fingerprinter.core.musicbrainz_client import MBAuth

        app = self._shell()
        app.musicbrainz.get.return_value = True
        app.run_mode.get.return_value = "Live Update"
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        monkeypatch.setattr(
            "audio_fingerprinter.app.mb_token_store.build_auth", lambda: MBAuth()
        )
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        dialogs.showerror.assert_called_once()
        assert "MUSICBRAINZ_TOKEN" in dialogs.showerror.call_args.args[1]

    def test_dry_run_submission_needs_no_token(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from audio_fingerprinter.core.musicbrainz_client import MBAuth

        fake_threading = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.threading", fake_threading)
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", MagicMock())
        monkeypatch.setattr(
            "audio_fingerprinter.app.resolve_fpcalc", lambda _p: Path("fpcalc.exe")
        )
        monkeypatch.setattr(
            "audio_fingerprinter.app.mb_token_store.build_auth", lambda: MBAuth()
        )
        built: dict[str, Any] = {}

        class FakeParams:
            def __init__(self, **kwargs: Any) -> None:
                built.update(kwargs)

        monkeypatch.setattr("audio_fingerprinter.app.FingerprintParams", FakeParams)
        app = self._shell()
        app.musicbrainz.get.return_value = True
        app.run_mode.get.return_value = "Dry Run"
        app.folder_path.get.return_value = str(tmp_path)
        app.fpcalc_path.get.return_value = ""
        app.threshold.get.return_value = "0.5"
        app.max_length.get.return_value = "120"

        app.start_processing()

        assert built["submit_isrc"] is True
        assert built["is_dry_run"] is True
        fake_threading.Thread.assert_called_once()


class TestMusicBrainzTokenActions:
    """The Setup tab's token controls must reach the encrypted store."""

    def test_save_stores_the_token_and_clears_the_entry(self, monkeypatch):
        saved: dict[str, str] = {}
        monkeypatch.setattr(
            "audio_fingerprinter.app.mb_token_store.save_token",
            lambda value: saved.update(value=value),
        )
        monkeypatch.setattr(
            "audio_fingerprinter.app.mb_token_store.describe_source",
            lambda: "stored",
        )
        app = TestStartGuardsD3()._shell()
        app.mb_token.get.return_value = "  tok  "

        app._save_mb_token()

        assert saved["value"] == "tok"
        app.mb_token.set.assert_called_once_with("")
        app.mb_token_status.set.assert_called_once_with("stored")

    def test_empty_token_warns_and_stores_nothing(self, monkeypatch):
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        store = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.mb_token_store", store)
        app = TestStartGuardsD3()._shell()
        app.mb_token.get.return_value = "   "

        app._save_mb_token()

        dialogs.showwarning.assert_called_once()
        store.save_token.assert_not_called()

    def test_save_failure_reports_and_keeps_the_entry(self, monkeypatch):
        dialogs = MagicMock()
        monkeypatch.setattr("audio_fingerprinter.app.messagebox", dialogs)
        store = MagicMock()
        store.save_token.side_effect = OSError("disk full")
        monkeypatch.setattr("audio_fingerprinter.app.mb_token_store", store)
        app = TestStartGuardsD3()._shell()
        app.mb_token.get.return_value = "tok"

        app._save_mb_token()

        dialogs.showerror.assert_called_once()
        app.mb_token.set.assert_not_called()

    def test_clear_removes_the_stored_token(self, monkeypatch):
        store = MagicMock()
        store.describe_source.return_value = "none"
        monkeypatch.setattr("audio_fingerprinter.app.mb_token_store", store)
        app = TestStartGuardsD3()._shell()

        app._clear_mb_token()

        store.clear_token.assert_called_once()
        app.mb_token.set.assert_called_once_with("")
        app.mb_token_status.set.assert_called_once_with("none")


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


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run binds and
# land in the report the run writes.
# ---------------------------------------------------------------------------

_HEADER = ["FINGERPRINT REPORT\n"]


class TestCompletionSeam:
    """``run_fingerprinting`` publishes into the handler ``_run`` binds."""

    @staticmethod
    def _wire(app: FingerprinterApp):
        """Return the completion callable ``_run`` hands to the processor."""
        return lambda **kw: app._on_complete(header=_HEADER, **kw)

    @staticmethod
    def _fake_worker(job) -> None:
        """Stand in for the fpcalc+lookup worker, one outcome per file."""
        from audio_fingerprinter.core.models import (
            FingerprintFileResult,
            FingerprintStatus,
        )

        outcomes = {
            "a.mp3": FingerprintStatus.TAGGED,
            "b.mp3": FingerprintStatus.NO_MATCH,
            "c.mp3": FingerprintStatus.ERROR,
        }
        status = outcomes[job.filename]
        job.results.append(
            FingerprintFileResult(
                file_path=job.filename,
                filename=job.filename,
                status=status,
                message="detail" if status != FingerprintStatus.ERROR else "boom",
            )
        )
        job.on_progress(1 if status == FingerprintStatus.ERROR else 0, f"[{status}]")

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the report the handler writes."""
        from audio_fingerprinter.core import file_processor
        from audio_fingerprinter.core.models import FingerprintParams

        for name in ("a.mp3", "b.mp3", "c.mp3"):
            (tmp_path / name).write_bytes(b"")
        app = TestOnCompleteSummary._make_app(tmp_path)

        with (
            patch.object(file_processor, "resolve_fpcalc", return_value="fpcalc"),
            patch.object(file_processor, "_fingerprint_worker", self._fake_worker),
        ):
            file_processor.run_fingerprinting(
                dir_path=str(tmp_path),
                api_key="",
                params=FingerprintParams(lookup_enabled=False, is_dry_run=True),
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=self._wire(app),
                on_error=MagicMock(),
            )

        report = (tmp_path / "fingerprint_dry_run_log.txt").read_text(encoding="utf-8")
        assert "Total files: 3" in report
        assert "Identified: 1" in report
        assert "No match: 1" in report
        assert "Tags written: 1" in report
        assert "Lookup skipped: 0" in report
        assert "Errors: 1" in report

    @pytest.mark.parametrize(
        "field",
        [
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
            "results",
            "counts",
        ],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        """A dropped field names itself and leaves no log behind."""
        app = TestOnCompleteSummary._make_app(tmp_path)
        payload: dict[str, Any] = {
            "total": 3,
            "processed": 2,
            "skipped": 0,
            "errors": 1,
            "duration_secs": 1.0,
            "log_entries": ["line\n"],
            "results": [],
            "counts": {
                "identified": 1,
                "no_match": 1,
                "tagged": 1,
                "lookup_skipped": 0,
                "album_ambiguous": 0,
                "errors": 1,
            },
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            self._wire(app)(**payload)

        assert field in str(caught.value)
        assert not (tmp_path / "fingerprint_dry_run_log.txt").exists()
