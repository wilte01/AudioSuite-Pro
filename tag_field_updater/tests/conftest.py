"""conftest.py for tag_field_updater tests.

The shared hidden Tk root and the `root`/`tk_root` fixtures live in the
repo-root conftest.py.
"""

import pytest

from audio_suite_shared.plugin_system import PLUGIN_DIR_ENV, reset_plugins_for_tests


@pytest.fixture(autouse=True)
def _isolated_plugin_root(tmp_path, monkeypatch):
    """Point plugin discovery at an empty tree for this suite.

    Changed in 2.1.0: this package now hosts a plugin extension point, so its
    unit tests must not depend on which plugins a checkout has enabled (the
    bundled example among them).  A test that wants a contribution installs one
    itself; everything else sees no plugins at all.
    """
    monkeypatch.setenv(PLUGIN_DIR_ENV, str(tmp_path / "no-plugins"))
    reset_plugins_for_tests()
    yield
    reset_plugins_for_tests()
