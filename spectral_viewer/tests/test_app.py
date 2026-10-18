"""Tests for the Spectral Viewer window.

Built on a withdrawn ``Toplevel`` off the shared hidden Tk root (never a real
``tk.Tk()``), so the real widgets, the real matplotlib canvas and the real
spectrogram computation all run. Only the dialogs are stubbed.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

import tkinter
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import spectral_viewer.app as app_module
from spectral_viewer.tests.audio_fixtures import write_tone_wav


@pytest.fixture()
def app_root(root: tkinter.Tk) -> Generator[tkinter.Toplevel, None, None]:
    """A fresh withdrawn ``Toplevel`` off the shared hidden Tk root."""
    top = tkinter.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture()
def fake_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the suite-config directory memory during the test."""
    monkeypatch.setattr(app_module.suite_config, "load_last_directory", lambda: "")
    monkeypatch.setattr(app_module.suite_config, "save_last_directory", MagicMock())


@pytest.fixture()
def app(app_root: tkinter.Toplevel, fake_config: None) -> app_module.SpectralViewerApp:
    return app_module.SpectralViewerApp(app_root)


@pytest.fixture()
def music_dir(tmp_path: Path) -> Path:
    """A folder with two short tones."""
    write_tone_wav(tmp_path / "alpha.wav", seconds=0.5)
    write_tone_wav(tmp_path / "beta.wav", frequency=880.0, seconds=0.5)
    return tmp_path


@pytest.fixture()
def stubbed_dialogs(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock]:
    messagebox = MagicMock()
    filedialog = MagicMock()
    monkeypatch.setattr(app_module, "messagebox", messagebox)
    monkeypatch.setattr(app_module, "filedialog", filedialog)
    return messagebox, filedialog


class TestInitialState:
    def test_window_and_controls(self, app: app_module.SpectralViewerApp) -> None:
        assert str(app.root.title()) == "Spectral Viewer"
        assert app.path_var.get() == ""
        assert app._controls.file_list.size() == 0
        assert app._selected is None
        assert app._canvas is None
        assert str(app._controls.export_button.cget("state")) == "disabled"
        assert "Select an audio file" in app.status_var.get()

    def test_defaults_match_the_core(self, app: app_module.SpectralViewerApp) -> None:
        assert app.n_fft_var.get() == "2048"
        assert app.db_range_var.get() == "80"
        assert app.start_var.get() == "0"
        assert app.end_var.get() == "0"
        assert app.max_freq_var.get() == "0"
        assert app.cmap_var.get() == "magma"

    def test_prefilled_options_are_used(
        self, app_root: tkinter.Toplevel, fake_config: None
    ) -> None:
        window = app_module.SpectralViewerApp(
            app_root, n_fft=4096, db_range=60.0, output_dir="C:/images"
        )

        assert window.n_fft_var.get() == "4096"
        assert window.db_range_var.get() == "60"
        assert window._output_dir == "C:/images"


class TestScanning:
    def test_scan_lists_files_and_renders_the_first(
        self, app: app_module.SpectralViewerApp, music_dir: Path
    ) -> None:
        app.path_var.set(str(music_dir))

        app._scan_path()

        assert app._controls.file_list.size() == 2
        assert app._controls.file_list.curselection() == (0,)
        assert app._selected == str(music_dir / "alpha.wav")
        assert app._canvas is not None
        assert app._figure is not None
        assert str(app._controls.export_button.cget("state")) == "normal"
        assert "bins x" in app.status_var.get()
        assert "peak" in app.status_var.get()

    def test_scan_of_a_single_file(
        self, app: app_module.SpectralViewerApp, music_dir: Path
    ) -> None:
        app.path_var.set(str(music_dir / "beta.wav"))

        app._scan_path()

        assert app._controls.file_list.size() == 1
        assert app._selected == str(music_dir / "beta.wav")

    def test_selecting_the_second_file_renders_it(
        self, app: app_module.SpectralViewerApp, music_dir: Path
    ) -> None:
        app.path_var.set(str(music_dir))
        app._scan_path()

        app._controls.file_list.selection_clear(0, tkinter.END)
        app._controls.file_list.selection_set(1)
        app._on_select(None)

        assert app._selected == str(music_dir / "beta.wav")
        assert "beta.wav" in app.status_var.get()

    def test_empty_folder_reports_it(
        self, app: app_module.SpectralViewerApp, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        app.path_var.set(str(empty))

        app._scan_path()

        assert app._controls.file_list.size() == 0
        assert app._selected is None
        assert "No supported audio files found" in app.status_var.get()

    def test_no_path_warns(
        self,
        app: app_module.SpectralViewerApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs

        app._scan_path()

        messagebox.showwarning.assert_called_once()

    def test_browse_loads_the_folder(
        self,
        app: app_module.SpectralViewerApp,
        music_dir: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.askdirectory.return_value = str(music_dir)

        app._browse()

        assert app.path_var.get() == str(music_dir)
        assert app._controls.file_list.size() == 2

    def test_out_of_range_selection_is_ignored(
        self, app: app_module.SpectralViewerApp, music_dir: Path
    ) -> None:
        app.path_var.set(str(music_dir))
        app._scan_path()
        before = app._selected

        app._select_index(99)
        app._select_index(-1)

        assert app._selected == before


class TestRenderingSettings:
    def test_time_window_reaches_the_figure(
        self, app: app_module.SpectralViewerApp, music_dir: Path
    ) -> None:
        app.path_var.set(str(music_dir))
        app._scan_path()
        app.start_var.set("0.1")
        app.end_var.set("0.4")

        app._render_selected()

        axes = app._figure.axes[0]
        left, right = axes.get_xlim()
        assert left == pytest.approx(0.1, abs=0.01)
        assert 0.3 <= right <= 0.4

    def test_max_frequency_and_range_reach_the_image(
        self, app: app_module.SpectralViewerApp, music_dir: Path
    ) -> None:
        app.path_var.set(str(music_dir))
        app._scan_path()
        app.max_freq_var.set("2000")
        app.db_range_var.set("60")

        app._render_selected()

        image = app._figure.axes[0].images[0]
        assert image.get_clim() == (-60.0, 0.0)
        top = app._figure.axes[0].get_ylim()[1]
        assert top <= 2000.0

    def test_bad_number_warns_and_keeps_the_previous_figure(
        self,
        app: app_module.SpectralViewerApp,
        music_dir: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app.path_var.set(str(music_dir))
        app._scan_path()
        previous = app._figure
        app.db_range_var.set("loud")

        app._render_selected()

        messagebox.showwarning.assert_called_once()
        assert app._figure is previous

    def test_render_without_a_file_warns(
        self,
        app: app_module.SpectralViewerApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs

        app._render_selected()

        messagebox.showwarning.assert_called_once()

    def test_number_helper_names_the_field(
        self, app: app_module.SpectralViewerApp
    ) -> None:
        app.start_var.set("later")

        with pytest.raises(ValueError, match="Start must be a number"):
            app._number(app.start_var, "Start")


class TestExport:
    def test_export_writes_a_png(
        self,
        app: app_module.SpectralViewerApp,
        music_dir: Path,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        _, filedialog = stubbed_dialogs
        destination = tmp_path / "out" / "alpha.png"
        filedialog.asksaveasfilename.return_value = str(destination)
        app.path_var.set(str(music_dir))
        app._scan_path()

        app._export()

        assert destination.exists()
        assert destination.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
        assert app.status_var.get().startswith("Exported")

    def test_cancelled_export_writes_nothing(
        self,
        app: app_module.SpectralViewerApp,
        music_dir: Path,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.asksaveasfilename.return_value = ""
        app.path_var.set(str(music_dir))
        app._scan_path()

        app._export()

        assert list(tmp_path.glob("**/*.png")) == []

    def test_export_before_render_warns(
        self,
        app: app_module.SpectralViewerApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs

        app._export()

        messagebox.showwarning.assert_called_once()

    def test_export_suggestion_uses_the_output_dir(
        self,
        app_root: tkinter.Toplevel,
        fake_config: None,
        music_dir: Path,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.asksaveasfilename.return_value = ""
        window = app_module.SpectralViewerApp(
            app_root, output_dir=str(tmp_path / "images")
        )
        window.path_var.set(str(music_dir))
        window._scan_path()

        window._export()

        kwargs = filedialog.asksaveasfilename.call_args.kwargs
        assert Path(kwargs["initialdir"]) == tmp_path / "images"
        assert kwargs["initialfile"] == "alpha_spectrogram.png"


class TestGuide:
    def test_help_guide_is_shipped(self, app: app_module.SpectralViewerApp) -> None:
        """The Help button's guide exists where ``platform_utils`` looks for it.

        Registration (the ``guide_to_program`` entry that maps this filename to
        ``spectral_viewer``) is locked centrally by
        ``tests/test_user_guide_hygiene.py::TestGuideRegistration``; asserting it
        again here would duplicate an AST parse for no extra protection.
        """
        repo_root = Path(__file__).resolve().parents[2]
        guide = (
            repo_root
            / "user_guides"
            / "individual_programs"
            / "spectral_viewer"
            / app.HELP_GUIDE
        )

        assert guide.is_file(), f"{guide} is missing"
