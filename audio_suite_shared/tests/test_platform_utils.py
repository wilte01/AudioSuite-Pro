"""
test_platform_utils.py — Unit tests for audio_suite_shared.platform_utils

Strategy
--------
open_path and open_help call messagebox (requires Tk display) or os.startfile
(Windows-only).  Pure-logic paths are testable everywhere via mocking.

Covers:
    • open_path: non-existent path triggers showerror (mocked)
    • open_path: existing path dispatches to os.startfile / run_secure_subprocess
    • open_path: SubprocessSecurityError, PermissionError, OSError all handled
    • open_help: unknown guide name triggers showwarning (mocked)
    • open_help: known guide without file triggers showwarning (mocked)
    • setup_window: _is_on_screen helper, geometry saving, protocol registration
    • setup_window: signed (±X/±Y) geometry restore (M3 regression)

Changed in 1.0.1: added signed-geometry restore tests covering Tk's
``WxH-X-Y`` forms that previously fell through to centering.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.secure_subprocess import SubprocessSecurityError

# ---------------------------------------------------------------------------
# open_path
# ---------------------------------------------------------------------------


class TestOpenPath:
    """Tests for platform_utils.open_path."""

    def test_nonexistent_path_shows_error(self, tmp_path: Path) -> None:
        """open_path with a non-existent path must call showerror, not startfile."""
        from audio_suite_shared import platform_utils

        missing = str(tmp_path / "ghost.wav")
        with patch.object(platform_utils.messagebox, "showerror") as mock_err:
            platform_utils.open_path(missing)
            mock_err.assert_called_once()
            args = mock_err.call_args[0]
            assert "Not Found" in args[0] or "not found" in args[0].lower()

    def test_existing_path_on_win32_calls_startfile(self, tmp_path: Path) -> None:
        """On win32, open_path must delegate to os.startfile."""
        from audio_suite_shared import platform_utils

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_path(str(real_file))
            mock_start.assert_called_once_with(str(real_file))

    def test_existing_path_on_linux_calls_secure_subprocess(
        self, tmp_path: Path
    ) -> None:
        """On non-win32, open_path must call run_secure_subprocess with xdg-open."""
        from audio_suite_shared import platform_utils

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "linux"),
            patch.object(platform_utils, "run_secure_subprocess") as mock_sub,
        ):
            platform_utils.open_path(str(real_file))
            mock_sub.assert_called_once()
            assert mock_sub.call_args[0][0] == "xdg-open"

    def test_subprocess_security_error_shows_error(self, tmp_path: Path) -> None:
        """SubprocessSecurityError must be caught and shown via showerror."""
        from audio_suite_shared import platform_utils
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "linux"),
            patch.object(
                platform_utils,
                "run_secure_subprocess",
                side_effect=SubprocessSecurityError("blocked"),
            ),
            patch.object(platform_utils.messagebox, "showerror") as mock_err,
        ):
            platform_utils.open_path(str(real_file))
            mock_err.assert_called_once()
            assert "Security" in mock_err.call_args[0][0]

    def test_permission_error_shows_error(self, tmp_path: Path) -> None:
        """PermissionError must be caught and shown via showerror."""
        from audio_suite_shared import platform_utils

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.startfile", side_effect=PermissionError("denied")),
            patch.object(platform_utils.messagebox, "showerror") as mock_err,
        ):
            platform_utils.open_path(str(real_file))
            mock_err.assert_called_once()

    def test_os_error_shows_error(self, tmp_path: Path) -> None:
        """OSError must be caught and shown via showerror."""
        from audio_suite_shared import platform_utils

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "win32"),
            patch("os.startfile", side_effect=OSError("fail")),
            patch.object(platform_utils.messagebox, "showerror") as mock_err,
        ):
            platform_utils.open_path(str(real_file))
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# open_help
# ---------------------------------------------------------------------------


class TestOpenHelp:
    """Tests for platform_utils.open_help."""

    def test_unknown_guide_shows_warning(self) -> None:
        """An unrecognised guide filename must trigger showwarning."""
        from audio_suite_shared import platform_utils

        with patch.object(platform_utils.messagebox, "showwarning") as mock_warn:
            platform_utils.open_help("Unknown_Guide_That_Does_Not_Exist.docx")
            mock_warn.assert_called_once()

    def test_known_guide_missing_file_shows_warning(self, tmp_path: Path) -> None:
        """A known guide whose file doesn't exist must trigger showwarning."""
        from audio_suite_shared import platform_utils

        with (
            patch("os.getcwd", return_value=str(tmp_path)),
            patch("os.path.basename", return_value="AudioSuite-Pro"),
            patch.object(platform_utils.messagebox, "showwarning") as mock_warn,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
            # With no AudioSuite-Pro dir structure, warning is expected
            # (either "root not found" or "file not found")
            assert mock_warn.called

    def test_unknown_guide_shows_warning_with_name_in_message(self) -> None:
        """An unrecognised guide filename must include the name in the warning."""
        from audio_suite_shared import platform_utils

        with patch.object(platform_utils.messagebox, "showwarning") as mock_warn:
            platform_utils.open_help("Totally_Bogus_Guide_Name.docx")
            mock_warn.assert_called_once()
            args = mock_warn.call_args[0]
            combined = " ".join(str(a) for a in args)
            assert "Totally_Bogus_Guide_Name" in combined

    def test_existing_guide_on_win32_calls_startfile(self, tmp_path: Path) -> None:
        """When the guide file exists on win32, os.startfile must be called."""
        from audio_suite_shared import platform_utils

        # Build the expected directory structure
        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = root / "user_guides" / "individual_programs" / "bpm_analyzer"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "BPM_Analyzer_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))

    def test_existing_guide_on_macos_calls_open(self, tmp_path: Path) -> None:
        """When the guide file exists on macOS, 'open' must be used."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = root / "user_guides" / "individual_programs" / "bpm_analyzer"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "BPM_Analyzer_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "darwin"),
            patch.object(platform_utils, "run_secure_subprocess") as mock_sub,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
            mock_sub.assert_called_once()
            assert mock_sub.call_args[0][0] == "open"
            assert mock_sub.call_args[0][1] == [str(guide_file)]

    def test_undo_guide_resolves_in_new_centralized_location(
        self, tmp_path: Path
    ) -> None:
        """Regression: Undo Tag Edits in the guide map so its Help button
        opens the user guide instead of warning 'Unknown help guide'."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = root / "user_guides" / "individual_programs" / "undo_tag_edits"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "Undo_Tag_Edits_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("Undo_Tag_Edits_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))

    def test_album_art_normalizer_guide_resolves_in_new_centralized_location(
        self, tmp_path: Path
    ) -> None:
        """Regression: Album Art Normalizer in the guide map so its Help
        button opens the user guide instead of warning 'Unknown help guide'."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = (
            root / "user_guides" / "individual_programs" / "album_art_normalizer"
        )
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "Album_Art_Normalizer_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("Album_Art_Normalizer_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))

    def test_mood_analysis_batch_tagger_guide_resolves_in_centralized_location(
        self, tmp_path: Path
    ) -> None:
        """Regression: the batch tagger guide is in the map so its Help button
        opens the user guide instead of warning 'Unknown help guide'."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = (
            root / "user_guides" / "individual_programs" / "mood_analysis_batch_tagger"
        )
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "Mood_Analysis_Batch_Tagger_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("Mood_Analysis_Batch_Tagger_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))

    def test_mood_analyzer_guide_resolves_in_centralized_location(
        self, tmp_path: Path
    ) -> None:
        """Regression: the mood analyzer guide is in the map so its Help
        button opens the user guide instead of warning 'Unknown help guide'."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = root / "user_guides" / "individual_programs" / "mood_analyzer"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "Mood_Analyzer_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("Mood_Analyzer_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))

    def test_tag_field_updater_guide_resolves_in_centralized_location(
        self, tmp_path: Path
    ) -> None:
        """Regression: the tag field updater guide is in the map so its Help
        button opens the user guide instead of warning 'Unknown help guide'."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = root / "user_guides" / "individual_programs" / "tag_field_updater"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "Tag_Field_Updater_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("Tag_Field_Updater_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))

    def test_file_reorganizer_guide_resolves_in_centralized_location(
        self, tmp_path: Path
    ) -> None:
        """Regression: the file reorganizer guide is in the map so its Help
        button opens the user guide instead of warning 'Unknown help guide'."""
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        guide_dir = root / "user_guides" / "individual_programs" / "file_reorganizer"
        guide_dir.mkdir(parents=True)
        guide_file = guide_dir / "File_Reorganizer_User_Guide.docx"
        guide_file.write_bytes(b"guide content")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("File_Reorganizer_User_Guide.docx")
            mock_start.assert_called_once_with(str(guide_file))


# ---------------------------------------------------------------------------
# setup_window geometry helpers (non-GUI logic)
# ---------------------------------------------------------------------------


class TestSetupWindowGeometryParsing:
    """Tests for the geometry-parsing logic inside setup_window via a mock root."""

    def _make_mock_root(self) -> MagicMock:
        root = MagicMock()
        root.winfo_screenwidth.return_value = 1920
        root.winfo_screenheight.return_value = 1080
        return root

    def _make_mock_config(self, saved_geom: str = "") -> MagicMock:
        cfg = MagicMock()
        cfg.load_value.return_value = saved_geom
        return cfg

    def test_valid_geometry_restores_position(self) -> None:
        """When a valid geometry string is saved,
        root.geometry must be called with it."""
        from audio_suite_shared import platform_utils

        root = self._make_mock_root()
        cfg = self._make_mock_config("800x600+100+200")

        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "test_window")

        root.geometry.assert_any_call("800x600+100+200")

    def test_missing_geometry_centres_window(self) -> None:
        """When no saved geometry exists, setup_window must call root.geometry with
        a centred WxH+X+Y string."""
        from audio_suite_shared import platform_utils

        root = self._make_mock_root()
        cfg = self._make_mock_config("")

        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "test_window_new")

        # Any geometry call should have been made
        root.geometry.assert_called()

    def test_malformed_geometry_falls_back_to_centre(self) -> None:
        """Malformed geometry (no + separators) must fall through to centering."""
        from audio_suite_shared import platform_utils

        root = self._make_mock_root()
        cfg = self._make_mock_config("NOTVALID")

        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "test_bad_geom")

        root.geometry.assert_called()

    def test_configure_event_bound(self) -> None:
        """setup_window must bind <Configure> on the root for geometry persistence."""
        from audio_suite_shared import platform_utils

        root = self._make_mock_root()
        cfg = self._make_mock_config()

        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "test_bind")

        root.bind.assert_any_call("<Configure>", unittest_any_callable())


def unittest_any_callable():
    """Helper matcher — accepts any callable in assert_any_call."""

    class _AnyCallable:
        def __eq__(self, other):
            return callable(other)

    return _AnyCallable()


# ---------------------------------------------------------------------------
# additional branches: made on darwin, CalledProcessError, help fallbacks,
# setup_window win32 / save / close paths
# ---------------------------------------------------------------------------


class TestOpenPathAdditional:
    def test_existing_path_on_darwin_calls_open(self, tmp_path: Path) -> None:
        from audio_suite_shared import platform_utils

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "darwin"),
            patch.object(platform_utils, "run_secure_subprocess") as mock_sub,
        ):
            platform_utils.open_path(str(real_file))
            mock_sub.assert_called_once_with(
                "open", [str(real_file)], capture_output=True, check=False
            )

    def test_called_process_error_shows_unexpected_error(self, tmp_path: Path) -> None:
        from audio_suite_shared import platform_utils

        real_file = tmp_path / "track.mp3"
        real_file.write_bytes(b"data")

        with (
            patch.object(sys, "platform", "win32"),
            patch(
                "os.startfile",
                side_effect=subprocess.CalledProcessError(1, "startfile"),
            ),
            patch.object(platform_utils.messagebox, "showerror") as mock_err,
        ):
            platform_utils.open_path(str(real_file))
            mock_err.assert_called_once()
            assert mock_err.call_args[0][0] == "Unexpected Error"


def _build_guide_root(tmp_path: Path, program: str) -> Path:
    """Create the AudioSuite-Pro tree with the mapped new-location guide dir."""

    root = tmp_path / "AudioSuite-Pro"
    root.mkdir()
    (root / "user_guides" / "individual_programs" / program).mkdir(parents=True)
    return root


class TestOpenHelpAdditional:
    def test_fallback_to_old_location(self, tmp_path: Path) -> None:
        from audio_suite_shared import platform_utils

        root = tmp_path / "AudioSuite-Pro"
        root.mkdir()
        (root / "user_guides" / "individual_programs" / "bpm_analyzer").mkdir(
            parents=True
        )
        old = root / "bpmanalyzer"
        old.mkdir()
        guide_file = old / "BPM_Analyzer_User_Guide.docx"
        guide_file.write_bytes(b"data")

        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
        mock_start.assert_called_once_with(str(guide_file))

    def test_help_file_missing_everywhere_shows_warning(self, tmp_path: Path) -> None:
        from audio_suite_shared import platform_utils

        root = _build_guide_root(tmp_path, "bpm_analyzer")
        with (
            patch("os.getcwd", return_value=str(root)),
            patch.object(platform_utils.messagebox, "showwarning") as mock_warn,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
        mock_warn.assert_called_once()
        assert "could not be found" in " ".join(str(a) for a in mock_warn.call_args[0])

    def test_existing_guide_on_linux_calls_xdg_open(self, tmp_path: Path) -> None:
        from audio_suite_shared import platform_utils

        root = _build_guide_root(tmp_path, "bpm_analyzer")
        (
            root
            / "user_guides"
            / "individual_programs"
            / "bpm_analyzer"
            / "BPM_Analyzer_User_Guide.docx"
        ).write_bytes(b"x")
        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "linux"),
            patch.object(platform_utils, "run_secure_subprocess") as mock_sub,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
        assert mock_sub.call_args[0][0] == "xdg-open"

    @pytest.mark.parametrize(
        "exc",
        [
            SubprocessSecurityError("s"),
            PermissionError("p"),
            OSError("o"),
            subprocess.CalledProcessError(1, "open"),
        ],
    )
    def test_help_open_errors_show_dialog(self, tmp_path: Path, exc: Exception) -> None:
        from audio_suite_shared import platform_utils

        root = _build_guide_root(tmp_path, "bpm_analyzer")
        (
            root
            / "user_guides"
            / "individual_programs"
            / "bpm_analyzer"
            / "BPM_Analyzer_User_Guide.docx"
        ).write_bytes(b"x")
        with (
            patch("os.getcwd", return_value=str(root)),
            patch("sys.platform", "linux"),
            patch.object(platform_utils, "run_secure_subprocess", side_effect=exc),
            patch.object(platform_utils.messagebox, "showerror") as mock_err,
        ):
            platform_utils.open_help("BPM_Analyzer_User_Guide.docx")
        mock_err.assert_called_once()


class TestSetupWindowAdditional:
    def _mock_root(self) -> MagicMock:
        root = MagicMock()
        root.winfo_screenwidth.return_value = 1920
        root.winfo_screenheight.return_value = 1080
        return root

    def test_save_geometry_on_configure(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = ""
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "ks")
        cfg.save_value.reset_mock()
        root.bind.call_args.args[1]()
        cfg.save_value.assert_called_once()

    def test_save_geometry_oserror_swallowed(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = ""
        cfg.save_value.side_effect = OSError("no")
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "kso")
        root.bind.call_args.args[1]()  # must not raise

    def test_save_geometry_called_process_error_swallowed(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = ""
        cfg.save_value.side_effect = subprocess.CalledProcessError(1, "save")
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "ksc")
        root.bind.call_args.args[1]()  # must not raise

    def test_malformed_coords_geometry_centres(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = "800x600+abc+def"
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "kmc")
        root.geometry.assert_called()

    def test_load_value_oserror_centres(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.side_effect = OSError("no")
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "klo")
        root.geometry.assert_called()

    def test_win32_on_screen_restores(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = "800x600+100+200"
        with patch.object(sys, "platform", "win32"):
            platform_utils.setup_window(root, 800, 600, cfg, "kws")
        root.geometry.assert_called()

    def test_win32_monitor_api_failure_trusts_saved(self) -> None:
        import builtins

        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = "800x600+100+200"

        class _FakeCtypes:
            class wintypes:
                class POINT:
                    def __init__(self, x, y):
                        pass

            class windll:
                class user32:
                    @staticmethod
                    def MonitorFromPoint(pt, flags):
                        raise OSError("api fail")

        real_import = builtins.__import__

        def _import(name, *args, **kwargs):
            if name.startswith("ctypes"):
                return _FakeCtypes
            return real_import(name, *args, **kwargs)

        with (
            patch.object(sys, "platform", "win32"),
            patch("builtins.__import__", side_effect=_import),
        ):
            platform_utils.setup_window(root, 800, 600, cfg, "kwf")
        root.geometry.assert_any_call("800x600+100+200")

    def test_close_saves_and_destroys(self) -> None:
        from audio_suite_shared import platform_utils

        root = self._mock_root()
        cfg = MagicMock()
        cfg.load_value.return_value = ""
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "kcl")

        close_cb = None
        for call in root.protocol.call_args_list:
            if call.args[0] == "WM_DELETE_WINDOW":
                close_cb = call.args[1]
        assert close_cb is not None
        close_cb()
        cfg.save_value.assert_called()
        root.destroy.assert_called_once()


# ---------------------------------------------------------------------------
# M3 regression: signed (±X/±Y) window geometry must restore
# ---------------------------------------------------------------------------


class TestSignedGeometryRestore:
    """Tk emits ``WxH±X±Y``; a signed X or Y must restore, not centre (M3)."""

    def _run(self, saved: str) -> MagicMock:
        from audio_suite_shared import platform_utils

        root = MagicMock()
        root.winfo_screenwidth.return_value = 1920
        root.winfo_screenheight.return_value = 1080
        cfg = MagicMock()
        cfg.load_value.return_value = saved
        with patch.object(sys, "platform", "linux"):
            platform_utils.setup_window(root, 800, 600, cfg, "signed_geom")
        return root

    @pytest.mark.parametrize(
        "saved",
        [
            "800x600+100+200",  # +X +Y (already worked)
            "800x600-400+200",  # -X +Y (left monitor)
            "800x600+100-300",  # +X -Y (upper monitor)
            "800x600-400-300",  # -X -Y
        ],
    )
    def test_signed_geometry_restores_saved_string(self, saved: str) -> None:
        root = self._run(saved)
        root.geometry.assert_any_call(saved)

    def test_optional_equals_prefix_restores(self) -> None:
        saved = "=800x600-400+200"
        root = self._run(saved)
        root.geometry.assert_any_call(saved)

    @pytest.mark.parametrize(
        "saved",
        [
            "NOTVALID",
            "800x600",
            "800x600+100",
            "800x600+abc+def",
            "800x600++1+2",
        ],
    )
    def test_malformed_geometry_centres(self, saved: str) -> None:
        root = self._run(saved)
        root.geometry.assert_called()
        assert root.geometry.call_args.args[0] != saved

    def test_parsed_but_off_screen_geometry_centres(self) -> None:
        """A signed origin off every screen must still fall back to centering."""
        saved = "800x600-5000+40"
        root = self._run(saved)
        root.geometry.assert_called()
        assert root.geometry.call_args.args[0] != saved

    @pytest.mark.parametrize(
        ("saved", "expected"),
        [
            ("800x600+100+200", (100, 200)),
            ("800x600-1920+40", (-1920, 40)),
            ("800x600+100-200", (100, -200)),
            ("800x600-1920-200", (-1920, -200)),
            ("=800x600-1920+40", (-1920, 40)),
            ("NOTVALID", None),
            ("800x600+100", None),
            ("800x600+abc+def", None),
        ],
    )
    def test_parse_geometry_origin(
        self, saved: str, expected: tuple[int, int] | None
    ) -> None:
        from audio_suite_shared.platform_utils import _parse_geometry_origin

        assert _parse_geometry_origin(saved) == expected
