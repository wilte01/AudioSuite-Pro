"""conftest.py for cd_ripper tests.

The shared hidden Tk root and the `root`/`tk_root` fixtures live in the
repo-root conftest.py.

``RipSession`` resolves the per-drive read offset from the shared suite
config at construction time, so every test in this package runs with the
suite config redirected to a temp file — the developer machine's real
``audio_suite_config.json`` must never leak stored offsets into tests.
"""

from __future__ import annotations

import pytest

import audio_suite_shared.suite_config as _suite_config


@pytest.fixture(autouse=True)
def isolated_suite_config(tmp_path, monkeypatch):
    """Redirect suite_config.CONFIG_PATH to a temp file for every test."""
    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(_suite_config, "CONFIG_PATH", config_file)
    _suite_config._invalidate_cache()
    yield config_file
    _suite_config._invalidate_cache()
