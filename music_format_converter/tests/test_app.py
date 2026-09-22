"""
Tests for music_format_converter.app (MusicFormatConverterApp orchestrator)

Scope: regression coverage for the "Open Output Folder" bug. The Results-tab
button is wired to UIHelperMixin._open_folder_standard(), which reads
self._out_dir (see audio_suite_shared.ui_helpers). app.py historically only
set self._output_dir_final, so the button always reported the folder as
unavailable. These tests exercise MusicFormatConverterApp._on_complete()
directly against a minimal stub, without requiring a real Tk root.
"""

import os
import threading
from pathlib import Path
from tkinter import messagebox
from unittest.mock import MagicMock

from music_format_converter import app as app_module
from music_format_converter.app import MusicFormatConverterApp
from music_format_converter.utils.cli_args import ConverterArgs

# ── Helpers ───────────────────────────────────────────────────────────────────


class _FakeVar:
    """Minimal stand-in for tk.StringVar/BooleanVar (get/set only)."""

    def __init__(self, value=""):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


def _make_cli_stub():
    """
    Build a bare object carrying only the attributes/widgets that
    _apply_cli_args() touches, without requiring a real Tk root.
    """
    stub = MagicMock()
    stub.folder_path = _FakeVar("")
    stub.output_folder = _FakeVar("")
    stub.output_format = _FakeVar("mp3")
    stub.run_mode = _FakeVar("Live Update")
    stub.quality_preset = _FakeVar("highest")
    stub.sample_rate = _FakeVar("source")
    stub.bit_depth = _FakeVar("auto")
    stub.delete_originals = _FakeVar(False)
    stub.normalize_mp3 = _FakeVar(False)
    stub.target_lufs = _FakeVar(-16.0)
    stub.auto_start_var = _FakeVar(False)
    stub.auto_end_var = _FakeVar(False)
    stub.clear_logs_var = _FakeVar(False)
    stub.parallel_var = _FakeVar(False)
    stub._scheduled = []
    stub.root = MagicMock()
    stub.root.after = lambda ms, func: stub._scheduled.append((ms, func))
    stub._on_folder_change = MagicMock()
    stub.start_processing = MagicMock()
    return stub


def _make_app_stub(tmp_path):
    """
    Build a bare object carrying only the attributes/widgets that
    _on_complete() touches, then bind the real _on_complete method to it.

    This avoids constructing a real MusicFormatConverterApp (which requires
    a live Tk root, ffmpeg probing, CLI parsing, etc.) while still exercising
    the actual production code path.
    """
    stub = MagicMock()
    stub._log_path = str(tmp_path / "conversion_live_log_mp3.txt")
    stub._output_dir_final = ""
    stub._out_dir = ""
    stub.time_label = MagicMock()
    stub.summary_label = MagicMock()
    stub.completion_label = MagicMock()
    stub.notebook = MagicMock()
    stub._tab_results = MagicMock()
    stub.start_btn = MagicMock()
    return stub


def _call_on_complete(stub, output_dir, **overrides):
    kwargs = dict(
        header=["HEADER\n"],
        delete=False,
        total=2,
        processed=2,
        converted=2,
        skipped=0,
        errors=0,
        duration_secs=1.5,
        log_entries=["[CONVERTED] a.flac -> a.mp3\n"],
        output_dir=output_dir,
    )
    kwargs.update(overrides)
    MusicFormatConverterApp._on_complete(stub, **kwargs)


# ═════════════════════════════════════════════════════════════════════════════
# _out_dir / _output_dir_final sync (regression for "Open Output Folder")
# ═════════════════════════════════════════════════════════════════════════════


class TestOnCompleteOutputDirSync:
    def test_sets_output_dir_final(self, tmp_path):
        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path))
        assert stub._output_dir_final == str(tmp_path)

    def test_sets_out_dir_to_same_value(self, tmp_path):
        """
        UIHelperMixin._open_folder_standard() reads self._out_dir, not
        self._output_dir_final. Both must end up holding the completed
        run's output directory, or "Open Output Folder" silently fails.
        """
        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path))
        assert stub._out_dir == str(tmp_path)

    def test_out_dir_matches_output_dir_final(self, tmp_path):
        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path))
        assert stub._out_dir == stub._output_dir_final

    def test_out_dir_updates_on_each_run(self, tmp_path):
        """A second conversion to a different folder must update _out_dir too,
        not just leave it pointing at the first run's directory."""
        stub = _make_app_stub(tmp_path)
        first_dir = str(tmp_path / "run1")
        second_dir = str(tmp_path / "run2")

        _call_on_complete(stub, first_dir)
        assert stub._out_dir == first_dir

        _call_on_complete(stub, second_dir)
        assert stub._out_dir == second_dir

    def test_out_dir_not_left_as_default_after_completion(self, tmp_path):
        stub = _make_app_stub(tmp_path)
        assert stub._out_dir == ""  # sanity check on initial state
        _call_on_complete(stub, str(tmp_path))
        assert stub._out_dir != ""


# ═════════════════════════════════════════════════════════════════════════════
# Integration-style check against the real UIHelperMixin helper
# ═════════════════════════════════════════════════════════════════════════════


class TestOpenOutputFolderIntegration:
    """
    Confirms the fix closes the loop: after _on_complete runs, the actual
    shared helper that the Results-tab button calls finds a non-empty
    folder path on the object, rather than falling back to "" and showing
    the "Output folder not available" dialog.
    """

    def test_open_folder_standard_reads_populated_out_dir(self, tmp_path, monkeypatch):
        from audio_suite_shared import ui_helpers

        captured = {}

        def fake_open_folder_path(folder_path):
            captured["folder_path"] = folder_path

        monkeypatch.setattr(ui_helpers, "open_folder_path", fake_open_folder_path)

        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path))

        # Bind the real mixin method (not a mock) to confirm it now sees
        # a populated _out_dir.
        from audio_suite_shared.ui_helpers import UIHelperMixin

        UIHelperMixin._open_folder_standard(stub)

        assert captured["folder_path"] == str(tmp_path)


def _make_start_stub():
    """Stub for start_processing validation gates — no Tk root needed."""
    stub = MagicMock()
    stub.folder_path = _FakeVar("")
    stub.output_folder = _FakeVar("")
    stub.output_format = _FakeVar("mp3")
    stub.run_mode = _FakeVar("Live Update")
    stub.quality_preset = _FakeVar("highest")
    stub.sample_rate = _FakeVar("source")
    stub.bit_depth = _FakeVar("auto")
    stub.delete_originals = _FakeVar(False)
    stub.normalize_mp3 = _FakeVar(False)
    stub.target_lufs = _FakeVar(-16.0)
    stub.ffmpeg_available = True
    stub._available_formats = ["mp3", "ogg", "opus"]
    stub.start_btn = MagicMock()
    stub.file_listbox = MagicMock()
    stub.notebook = MagicMock()
    stub.overall_status = MagicMock()
    stub._tab_processing = object()
    return stub


# ═════════════════════════════════════════════════════════════════════════════
# _apply_cli_args (regression for dropped folder_path / output_dir)
#
# ConverterArgs extends BaseCLIArgs (folder_path pattern), so
# UniversalCLIHandler.apply_cli_args() dispatches to _apply_folder_pattern(),
# which reads a "folder_var" kwarg and has no output handling. app.py
# previously passed "source_var"/"output_var" (the source/output pattern's
# kwarg names), so neither the folder path nor the output directory from the
# CLI ever reached the UI variables, regardless of --start.
# ═════════════════════════════════════════════════════════════════════════════


class TestApplyCliArgsFolderPathWiring:
    def test_folder_path_applied_from_cli(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path)),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.folder_path.get() == str(tmp_path)

    def test_no_args_leaves_folder_path_untouched(self, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(app_module.cli_args, "parse", lambda: ConverterArgs())
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.folder_path.get() == ""


class TestApplyCliArgsOutputDirWiring:
    def test_output_dir_applied_from_cli(self, tmp_path, monkeypatch):
        out = tmp_path / "out"
        out.mkdir()
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), output_dir=str(out)),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.output_folder.get() == str(out)

    def test_no_output_dir_leaves_output_folder_untouched(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path)),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.output_folder.get() == ""


class TestApplyCliArgsAutoStartScheduling:
    def test_auto_start_schedules_scan_and_start(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), auto_start=True),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        scheduled_funcs = [func for _, func in stub._scheduled]
        assert stub._on_folder_change in scheduled_funcs
        assert stub.start_processing in scheduled_funcs

    def test_no_auto_start_schedules_nothing(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), auto_start=False),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub._scheduled == []


class TestApplyCliArgsFormatQualityAndFlags:
    def test_output_format_applied(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), output_format="flac"),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.output_format.get() == "flac"

    def test_quality_applied(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), quality="high"),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.quality_preset.get() == "high"

    def test_delete_originals_applied(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), delete_originals=True),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.delete_originals.get() is True


class TestApplyCliArgsNormalizeMp3:
    def test_normalize_flow_set_from_cli(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(
                folder_path=str(tmp_path), normalize_mp3=True, target_lufs=-14.0
            ),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.normalize_mp3.get() is True
        assert stub.target_lufs.get() == -14.0

    def test_nothing_set_leaves_defaults(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path)),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.normalize_mp3.get() is False
        assert stub.target_lufs.get() == -16.0


class TestRunNormalizeMp3Forwarding:
    """_run() must forward normalize_mp3/target_lufs to run_conversion
    and reflect them in the log header."""

    def _make_run_stub(self, tmp_path, **var_overrides):
        stub = MagicMock()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub.output_folder = _FakeVar("")
        stub.output_format = _FakeVar("mp3")
        stub.quality_preset = _FakeVar("highest")
        stub.sample_rate = _FakeVar("source")
        stub.bit_depth = _FakeVar("auto")
        stub.delete_originals = _FakeVar(False)
        stub.normalize_mp3 = _FakeVar(var_overrides.get("normalize_mp3", True))
        stub.target_lufs = _FakeVar(var_overrides.get("target_lufs", -16.0))
        stub.run_mode = _FakeVar(var_overrides.get("run_mode", "Live Update"))
        stub._log_path = os.path.join(tmp_path, "conversion_live_log_mp3.txt")
        stub.progress = MagicMock()
        stub._safe_slot_vars = []
        stub.slot_queue = MagicMock()
        stub._on_progress = MagicMock()
        stub._on_complete = MagicMock()
        stub._on_error = MagicMock()
        return stub

    def test_forwards_normalize_flags(self, tmp_path, monkeypatch):
        kwargs_capture = {}

        def fake_run_conversion(**kw):
            kwargs_capture.update(kw)

        monkeypatch.setattr(
            app_module.file_processor, "run_conversion", fake_run_conversion
        )
        stub = self._make_run_stub(str(tmp_path), normalize_mp3=True, target_lufs=-14.0)
        MusicFormatConverterApp._run(stub)
        assert kwargs_capture["normalize_mp3"] is True
        assert kwargs_capture["target_lufs"] == -14.0

    def test_no_normalize_when_flag_off(self, tmp_path, monkeypatch):
        kwargs_capture = {}

        def fake_run_conversion(**kw):
            kwargs_capture.update(kw)

        monkeypatch.setattr(
            app_module.file_processor, "run_conversion", fake_run_conversion
        )
        stub = self._make_run_stub(str(tmp_path), normalize_mp3=False)
        MusicFormatConverterApp._run(stub)
        assert kwargs_capture["normalize_mp3"] is False

    def test_no_normalize_for_non_mp3_output(self, tmp_path, monkeypatch):
        kwargs_capture = {}

        def fake_run_conversion(**kw):
            kwargs_capture.update(kw)

        monkeypatch.setattr(
            app_module.file_processor, "run_conversion", fake_run_conversion
        )
        stub = self._make_run_stub(str(tmp_path))
        stub.output_format = _FakeVar("flac")
        MusicFormatConverterApp._run(stub)
        assert kwargs_capture["normalize_mp3"] is False

    def test_header_records_normalize(self, tmp_path, monkeypatch):
        kwargs_capture = {}

        def fake_run_conversion(**kw):
            kwargs_capture.update(kw)

        monkeypatch.setattr(
            app_module.file_processor, "run_conversion", fake_run_conversion
        )
        stub = self._make_run_stub(str(tmp_path), normalize_mp3=True, target_lufs=-14.0)
        MusicFormatConverterApp._run(stub)
        # Invoke the on_complete closure run_conversion captured; it forwards
        # header + delete into _on_complete.
        kwargs_capture["on_complete"](
            total=1,
            processed=1,
            converted=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            output_dir=str(tmp_path),
        )
        header = stub._on_complete.call_args.kwargs["header"]
        assert any("Normalize MP3 (Lossless): YES" in line for line in header)
        assert any("Target Loudness: -14.0 LUFS" in line for line in header)

    def test_header_records_no_normalize(self, tmp_path, monkeypatch):
        kwargs_capture = {}

        def fake_run_conversion(**kw):
            kwargs_capture.update(kw)

        monkeypatch.setattr(
            app_module.file_processor, "run_conversion", fake_run_conversion
        )
        stub = self._make_run_stub(str(tmp_path), normalize_mp3=False)
        MusicFormatConverterApp._run(stub)
        kwargs_capture["on_complete"](
            total=1,
            processed=1,
            converted=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            output_dir=str(tmp_path),
        )
        header = stub._on_complete.call_args.kwargs["header"]
        assert any("Normalize MP3 (Lossless): NO" in line for line in header)


class TestApplyCliArgsSampleRateAndBitDepth:
    def test_sample_rate_applied(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), sample_rate="48000"),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.sample_rate.get() == "48000"

    def test_bit_depth_applied(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path), bit_depth="24"),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.bit_depth.get() == "24"

    def test_cli_values_override_defaults(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(
                folder_path=str(tmp_path),
                sample_rate="96000",
                bit_depth="float",
            ),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.sample_rate.get() == "96000"
        assert stub.bit_depth.get() == "float"

    def test_no_cli_values_leave_defaults(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(folder_path=str(tmp_path)),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.sample_rate.get() == "source"
        assert stub.bit_depth.get() == "auto"


class TestPresetSampleRateAndBitDepth:
    def test_settings_collected(self):
        stub = MagicMock()
        stub.sample_rate = _FakeVar("48000")
        stub.bit_depth = _FakeVar("24")
        stub.output_format = _FakeVar("mp3")
        stub.quality_preset = _FakeVar("high")
        stub.delete_originals = _FakeVar(False)
        stub.normalize_mp3 = _FakeVar(True)
        stub.target_lufs = _FakeVar(-14.0)
        stub.run_mode = _FakeVar("Live Update")
        settings = MusicFormatConverterApp._collect_settings(stub)
        assert settings["sample_rate"] == "48000"
        assert settings["bit_depth"] == "24"
        assert settings["normalize_mp3"] is True
        assert settings["target_lufs"] == -14.0

    def test_preset_applied(self):
        stub = MagicMock()
        for attr in (
            "output_format",
            "quality_preset",
            "sample_rate",
            "bit_depth",
            "delete_originals",
            "normalize_mp3",
            "target_lufs",
            "run_mode",
        ):
            setattr(stub, attr, _FakeVar())
        MusicFormatConverterApp._apply_preset(
            stub,
            {
                "sample_rate": "192000",
                "bit_depth": "32",
                "output_format": "wav",
                "normalize_mp3": True,
                "target_lufs": -11.0,
            },
        )
        assert stub.sample_rate.get() == "192000"
        assert stub.bit_depth.get() == "32"
        assert stub.output_format.get() == "wav"
        assert stub.normalize_mp3.get() is True
        assert stub.target_lufs.get() == -11.0


# ═════════════════════════════════════════════════════════════════════════════
# start_processing — validation gates
# ═════════════════════════════════════════════════════════════════════════════


class TestStartProcessingValidation:
    """Exercise each early-return gate in start_processing()."""

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _patch_showerror(monkeypatch):
        errors = []
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **kw: errors.append(a))
        return errors

    @staticmethod
    def _make_audio_file(tmp_path, name="track.mp3") -> None:
        (tmp_path / name).write_bytes(b"\xff\xfb\x90\x00")

    # ── Validation gates ─────────────────────────────────────────────────

    def test_no_input_shows_error(self, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        stub = _make_start_stub()
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_nonexistent_input_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path / "nonexistent"))
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_file_as_input_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        f = tmp_path / "file.txt"
        f.write_bytes(b"x")
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(f))
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_no_audio_files_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_listdir_permission_error_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))

        def raise_permission(*_a):
            raise PermissionError("Access denied")

        monkeypatch.setattr(app_module.os, "listdir", raise_permission)
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_ffmpeg_unavailable_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        self._make_audio_file(tmp_path)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub.ffmpeg_available = False
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_no_valid_formats_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        self._make_audio_file(tmp_path)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub._available_formats = []
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_no_output_format_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        self._make_audio_file(tmp_path)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub.output_format = _FakeVar("")
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_output_dir_not_exist_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        self._make_audio_file(tmp_path)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub.output_folder = _FakeVar(str(tmp_path / "nonexistent_out"))
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_output_dir_is_file_shows_error(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        self._make_audio_file(tmp_path)
        f = tmp_path / "afile.txt"
        f.write_bytes(b"x")
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub.output_folder = _FakeVar(str(f))
        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) >= 1

    def test_delete_originals_cancelled_returns_early(self, tmp_path, monkeypatch):
        errors = self._patch_showerror(monkeypatch)
        monkeypatch.setattr(messagebox, "askyesno", lambda *a, **kw: False)
        self._make_audio_file(tmp_path)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))
        stub.delete_originals = _FakeVar(True)

        thread_starts = []
        original_thread = threading.Thread
        monkeypatch.setattr(
            threading,
            "Thread",
            lambda **kw: thread_starts.append(kw) or original_thread(**kw),
        )

        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) == 0  # no error, just cancelled
        assert len(thread_starts) == 0  # thread not started

    def test_success_starts_thread(self, tmp_path, monkeypatch):
        """All validations pass → a daemon thread is launched."""
        errors = self._patch_showerror(monkeypatch)
        self._make_audio_file(tmp_path)
        stub = _make_start_stub()
        stub.folder_path = _FakeVar(str(tmp_path))

        thread_calls = []
        mock_thread = MagicMock()
        monkeypatch.setattr(
            threading, "Thread", lambda **kw: thread_calls.append(kw) or mock_thread
        )

        MusicFormatConverterApp.start_processing(stub)
        assert len(errors) == 0
        assert len(thread_calls) == 1
        assert thread_calls[0].get("daemon") is True


# ═════════════════════════════════════════════════════════════════════════════
# _on_folder_change — scan + UI update
# ═════════════════════════════════════════════════════════════════════════════


class TestOnFolderChange:
    """scan-input-directory wiring and output-format default selection."""

    @staticmethod
    def _make_stub():
        stub = _make_cli_stub()
        stub._available_formats = []
        stub._update_detected_label = MagicMock()
        stub._update_format_menu = MagicMock()
        return stub

    def test_updates_available_formats(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=True,
                input_format="flac",
                file_count=3,
                output_formats=["mp3", "ogg"],
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        assert stub._available_formats == ["mp3", "ogg"]

    def test_calls_update_detected_label(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=True,
                input_format="flac",
                file_count=3,
                output_formats=["mp3", "ogg"],
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        stub._update_detected_label.assert_called_once()

    def test_selects_current_format_when_available(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        stub.output_format = _FakeVar("ogg")
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=True,
                input_format="flac",
                file_count=3,
                output_formats=["mp3", "ogg"],
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        stub._update_format_menu.assert_called_once_with(["mp3", "ogg"], "ogg")

    def test_defaults_to_mp3_when_current_unavailable(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        stub.output_format = _FakeVar("wav")
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=True,
                input_format="flac",
                file_count=3,
                output_formats=["mp3", "ogg"],
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        stub._update_format_menu.assert_called_once_with(["mp3", "ogg"], "mp3")

    def test_defaults_to_first_when_mp3_unavailable(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        stub.output_format = _FakeVar("wav")
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=True,
                input_format="flac",
                file_count=3,
                output_formats=["ogg", "opus"],
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        stub._update_format_menu.assert_called_once_with(["ogg", "opus"], "ogg")

    def test_selects_empty_when_no_formats(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=True, input_format="flac", file_count=3, output_formats=[]
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        stub._update_format_menu.assert_called_once_with([], "")

    def test_mixed_formats_shows_error(self, monkeypatch):
        from music_format_converter.core.formats import ScanResult

        stub = self._make_stub()
        errors = []
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **kw: errors.append(a))
        monkeypatch.setattr(
            app_module,
            "scan_input_directory",
            lambda p: ScanResult(
                ok=False, mixed_formats=["mp3", "flac"], output_formats=[]
            ),
        )
        MusicFormatConverterApp._on_folder_change(stub)
        assert len(errors) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# _on_complete — additional edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestOnCompleteEdgeCases:
    def test_delete_summary_includes_originals_deleted(self, tmp_path):
        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path), delete=True)
        text_arg = stub.summary_label.config.call_args[1]["text"]
        assert "Originals Deleted" in text_arg

    def test_log_write_failure_shows_error(self, tmp_path, monkeypatch):
        import builtins

        errors = []
        monkeypatch.setattr(messagebox, "showerror", lambda *a, **kw: errors.append(a))

        original_open = builtins.open
        # Simulate a write failure on every file-open for writing.

        def failing_open(path, mode="r", **kw):
            if "w" in mode:
                raise PermissionError("Permission denied")
            return original_open(path, mode, **kw)

        monkeypatch.setattr(builtins, "open", failing_open)

        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path))
        assert len(errors) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# _on_complete — callback contract with file_processor.run_conversion
# ═════════════════════════════════════════════════════════════════════════════


class TestOnCompleteCallbackContract:
    """
    Regression: run_conversion() invokes on_complete() with a `processed`
    keyword (file_processor.py). _on_complete must accept the exact kwarg
    set emitted by that call site, or the TypeError is swallowed by
    @handle_audio_errors and the conversion log is never written.
    """

    def test_accepts_exact_kwargs_from_run_conversion(self, tmp_path):
        stub = _make_app_stub(tmp_path)
        MusicFormatConverterApp._on_complete(
            stub,
            header=["HEADER\n"],
            delete=False,
            total=3,
            processed=3,
            converted=2,
            skipped=1,
            errors=0,
            duration_secs=4.2,
            log_entries=["[CONVERTED] a.mp3 -> a.aac\n"],
            output_dir=str(tmp_path),
        )
        assert Path(stub._log_path).exists()

    def test_log_written_when_processed_kwarg_present(self, tmp_path):
        stub = _make_app_stub(tmp_path)
        _call_on_complete(stub, str(tmp_path), processed=5)
        assert Path(stub._log_path).exists()


class TestApplyCliArgsDriverMirror:
    """Driver run controls mirrored onto the Setup tab panel."""

    def test_display_flags_mirrored(self, tmp_path, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: ConverterArgs(
                folder_path=str(tmp_path),
                auto_start=True,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
            ),
        )
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.auto_start_var.get() is True
        assert stub.auto_end_var.get() is True
        assert stub.clear_logs_var.get() is True
        assert stub.parallel_var.get() is True

    def test_no_folder_leaves_mirror_untouched(self, monkeypatch):
        stub = _make_cli_stub()
        monkeypatch.setattr(app_module.cli_args, "parse", lambda: ConverterArgs())
        MusicFormatConverterApp._apply_cli_args(stub)
        assert stub.clear_logs_var.get() is False
        assert stub.parallel_var.get() is False
