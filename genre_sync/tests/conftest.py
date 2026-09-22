"""
Pytest fixtures for genre_sync tests.

mock_tk_app builds a fully-mocked tkinter environment for orchestrator
tests; a session-scoped hidden Tk root is also provided for tests that
exercise real widget behaviour (DriverControlsPanel etc.).
"""

import tkinter as tk
from unittest.mock import MagicMock, patch

import pytest

_root: tk.Tk | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Create the shared hidden Tk root before any test module is collected."""
    global _root
    try:
        _root = tk.Tk()
        _root.withdraw()
    except tk.TclError:
        pytest.skip("No display available — tkinter tests require a GUI environment")


def pytest_unconfigure(config: pytest.Config) -> None:
    """Destroy the shared root after the whole session finishes."""
    global _root
    if _root is not None:
        _root.destroy()
        _root = None


@pytest.fixture(scope="session")
def root() -> tk.Tk:
    """The shared hidden Tk root, for tests that want it explicitly."""
    assert _root is not None, "pytest_configure should have created the root"
    return _root


def _mock_stringvar(value=None, master=None, name=None):
    sv = MagicMock()
    sv.get.return_value = value if value is not None else ""

    def sv_setter(val):
        sv.get.return_value = val

    sv.set = sv_setter
    return sv


def _mock_boolvar(value=False, master=None, name=None):
    sv = MagicMock()
    sv.get.return_value = value

    def sv_setter(val):
        sv.get.return_value = val

    sv.set = sv_setter
    return sv


def _fake_parsed_args(folder_path=None):
    """Parsed-args stand-in with realistic defaults for CLI mirroring."""
    return MagicMock(
        folder_path=folder_path,
        live_mode=False,
        auto_start=False,
        auto_end=False,
        clear_logs=False,
        parallel_run=False,
    )


@pytest.fixture
def mock_tk_app():
    """Build a GenreSetterApp with all GUI dependencies fully mocked.

    Replaces tkinter in every genre_sync module and the shared UI module
    with a bare MagicMock so no real Tk widgets are created.
    """
    # The cascade: genre_sync.app -> genre_sync.ui.processing_tab ->
    # audio_suite_shared.ui_common (imported by processing_tab)
    import audio_suite_shared.ui_common
    import genre_sync.app
    import genre_sync.ui.processing_tab
    import genre_sync.ui.results_tab
    import genre_sync.ui.setup_tab

    # Save originals keyed by module
    to_patch = [
        genre_sync.app,
        genre_sync.ui.setup_tab,
        genre_sync.ui.results_tab,
        genre_sync.ui.processing_tab,
        audio_suite_shared.ui_common,
    ]
    saved = {}
    for mod in to_patch:
        saved[mod] = {
            "tk": getattr(mod, "tk", None),
            "ttk": getattr(mod, "ttk", None),
        }

    mock_tk = MagicMock()
    mock_tk.StringVar = _mock_stringvar
    mock_tk.BooleanVar = _mock_boolvar
    mock_tk.ttk = MagicMock()
    mock_tk.END = "end"
    mock_tk.Frame = MagicMock(return_value=MagicMock())
    mock_tk.Label = MagicMock(return_value=MagicMock())
    mock_tk.Button = MagicMock(return_value=MagicMock())
    mock_tk.Entry = MagicMock(return_value=MagicMock())
    mock_tk.Listbox = MagicMock(return_value=MagicMock())

    try:
        for mod in to_patch:
            mod.tk = mock_tk
            if hasattr(mod, "ttk"):
                mod.ttk = mock_tk.ttk

        with (
            patch("genre_sync.app.bootstrap_tool_app") as mock_bootstrap,
            patch("genre_sync.app.suite_config") as mock_config,
            patch("genre_sync.app.cli_args") as mock_cli,
            patch("genre_sync.app.messagebox"),
            patch("genre_sync.app.UniversalCLIHandler"),
            patch("genre_sync.app.logger"),
            # DriverControlsPanel builds real tkinter widgets — replace it
            # while the rest of tkinter is mocked in this fixture.
            patch("genre_sync.ui.setup_tab.DriverControlsPanel") as mock_panel,
        ):
            mock_bootstrap.return_value = (MagicMock(), MagicMock())
            mock_config.load_last_directory.return_value = ""
            mock_cli.parse.return_value = _fake_parsed_args()
            mock_cli.was_launched_from_driver.return_value = False
            mock_panel.return_value = MagicMock()

            from genre_sync.app import GenreSetterApp

            root = MagicMock()
            root.withdraw = MagicMock()
            app = GenreSetterApp(root)
            app._run = MagicMock()
            # Patch methods inherited from UIHelperMixin that access real tkinter
            app._browse_folder_standard = MagicMock()
            app._open_help_standard = MagicMock()
            app._open_log_standard = MagicMock()
            yield app
    finally:
        for mod, attrs in saved.items():
            for attr, val in attrs.items():
                setattr(mod, attr, val)
