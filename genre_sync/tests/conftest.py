"""
Pytest fixtures for genre_sync tests.

``make_mocked_app`` builds a ``GenreSetterApp`` with every tkinter module in its
cascade replaced by a MagicMock; ``mock_tk_app`` is that app with the defaults.
The session-scoped hidden Tk root (and the ``root`` / ``tk_root`` fixtures plus
the headless skip behaviour) come from the repo-root ``conftest.py`` — this
package deliberately owns no Tk bootstrap of its own.
See PLAN_iteration5_remediation.md item A3: the private ``pytest_configure``
that called ``pytest.skip()`` on ``tk.TclError`` raised ``INTERNALERROR``
(pytest exit code 3) during ``config._do_configure()``, which takes down the
whole session on a headless host — not just genre_sync.

Changed in 2.4.3: the fixture also patches ``audio_suite_shared.ui_tabs``,
because the WP-9 split moved the Results/Processing tab builders there and
patching ``ui_common.tk`` alone no longer reached the widgets they build.

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2), so the shell's own
module joins the patched cascade and the two delegate tab modules are gone. The
factory form lets a test build the app with a folder restored from config, and
the mocked root runs ``after`` callbacks inline so the handlers' marshalled
widget writes are observable.
"""

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest


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


@contextmanager
def _mocked_app(last_directory: str = "") -> Iterator[Any]:
    """Yield a ``GenreSetterApp`` built with its whole Tk cascade mocked.

    Args:
        last_directory: What the shared config restores as the last folder.

    Yields:
        The constructed application, with the folder helpers stubbed.
    """
    # The cascade: genre_sync.app -> audio_suite_shared.suite_app ->
    # audio_suite_shared.ui_common (which re-exports the tab builders).
    import audio_suite_shared.suite_app
    import audio_suite_shared.ui_common
    import audio_suite_shared.ui_tabs
    import genre_sync.app
    import genre_sync.ui.setup_tab

    # Save originals keyed by module
    to_patch = [
        genre_sync.app,
        genre_sync.ui.setup_tab,
        audio_suite_shared.suite_app,
        audio_suite_shared.ui_tabs,
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
            patch("audio_suite_shared.suite_app.bootstrap_tool_app") as mock_bootstrap,
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
            mock_config.load_last_directory.return_value = last_directory
            mock_cli.parse.return_value = _fake_parsed_args()
            mock_cli.was_launched_from_driver.return_value = False
            mock_panel.return_value = MagicMock()

            from genre_sync.app import GenreSetterApp

            root = MagicMock()
            root.withdraw = MagicMock()
            # The handlers marshal their widget writes with after(0, ...): run
            # them inline so a test sees the write the Tk thread would make.
            root.after.side_effect = lambda delay, func, *args: func(*args)
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


@pytest.fixture
def make_mocked_app():
    """Return the factory that builds a fully-mocked ``GenreSetterApp``."""
    return _mocked_app


@pytest.fixture
def mock_tk_app(make_mocked_app):
    """Build a ``GenreSetterApp`` with all GUI dependencies fully mocked."""
    with make_mocked_app() as app:
        yield app
