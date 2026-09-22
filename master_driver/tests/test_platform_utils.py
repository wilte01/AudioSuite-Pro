"""Tests for master_driver.utils.platform_utils.open_help."""

from __future__ import annotations

from unittest.mock import patch

from master_driver.utils.platform_utils import open_help

MODULE = "master_driver.utils.platform_utils"


class TestOpenHelp:
    def test_missing_help_file_shows_warning(self, tmp_path) -> None:
        with (
            patch(f"{MODULE}.os.path.exists", return_value=False),
            patch(f"{MODULE}.messagebox.showwarning") as warn,
        ):
            open_help(str(tmp_path / "app.pyw"), "UserGuide.txt")
        warn.assert_called_once()

    def test_windows_uses_startfile(self, tmp_path) -> None:
        script = tmp_path / "app.pyw"
        guide = tmp_path / "UserGuide.txt"
        script.write_text("pass")
        guide.write_text("guide")
        with (
            patch(f"{MODULE}.sys.platform", "win32"),
            patch(f"{MODULE}.os.startfile") as startfile,
        ):
            open_help(str(script), "UserGuide.txt")
        startfile.assert_called_once_with(str(guide))

    def test_darwin_uses_open(self, tmp_path) -> None:
        script = tmp_path / "app.pyw"
        guide = tmp_path / "UserGuide.txt"
        script.write_text("pass")
        guide.write_text("guide")
        with (
            patch(f"{MODULE}.sys.platform", "darwin"),
            patch(f"{MODULE}.subprocess.run") as run,
        ):
            open_help(str(script), "UserGuide.txt")
        run.assert_called_once()
        assert run.call_args[0][0] == ["open", str(guide)]

    def test_linux_uses_xdg_open(self, tmp_path) -> None:
        script = tmp_path / "app.pyw"
        guide = tmp_path / "UserGuide.txt"
        script.write_text("pass")
        guide.write_text("guide")
        with (
            patch(f"{MODULE}.sys.platform", "linux"),
            patch(f"{MODULE}.subprocess.run") as run,
        ):
            open_help(str(script), "UserGuide.txt")
        run.assert_called_once()
        assert run.call_args[0][0] == ["xdg-open", str(guide)]

    def test_oserror_shows_error_dialog(self, tmp_path) -> None:
        script = tmp_path / "app.pyw"
        guide = tmp_path / "UserGuide.txt"
        script.write_text("pass")
        guide.write_text("guide")
        with (
            patch(f"{MODULE}.sys.platform", "win32"),
            patch(f"{MODULE}.os.startfile", side_effect=OSError("denied")),
            patch(f"{MODULE}.messagebox.showerror") as err,
        ):
            open_help(str(script), "UserGuide.txt")
        err.assert_called_once()

    def test_subprocess_called_process_error_shows_error(self, tmp_path) -> None:
        """A failing launch helper must still produce an error dialog (G-31)."""
        import subprocess

        script = tmp_path / "app.pyw"
        guide = tmp_path / "UserGuide.txt"
        script.write_text("pass")
        guide.write_text("guide")
        with (
            patch(f"{MODULE}.sys.platform", "linux"),
            patch(
                f"{MODULE}.subprocess.run",
                side_effect=subprocess.CalledProcessError(1, ["xdg-open"]),
            ),
            patch(f"{MODULE}.messagebox.showerror") as err,
        ):
            open_help(str(script), "UserGuide.txt")
        err.assert_called_once()


class TestOpenHelpLogging:
    def test_error_is_logged_with_mapped_type(self, tmp_path) -> None:
        script = tmp_path / "app.pyw"
        guide = tmp_path / "UserGuide.txt"
        script.write_text("pass")
        guide.write_text("guide")
        with (
            patch(f"{MODULE}.sys.platform", "win32"),
            patch(f"{MODULE}.os.startfile", side_effect=OSError("denied")),
            patch(f"{MODULE}.logger") as logger,
            patch(f"{MODULE}.messagebox.showerror"),
        ):
            open_help(str(script), "UserGuide.txt")
        logger.error.assert_called_once()
