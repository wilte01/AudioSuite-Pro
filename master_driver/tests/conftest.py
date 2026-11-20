"""conftest.py for master_driver tests.

The shared hidden Tk root and the `root`/`tk_root` fixtures live in the
repo-root conftest.py.

Changed in 2.9.0: every test in this package points ``suite_config`` at a
scratch file.  ``BatchOrchestrator.run`` records each completed step's duration
through ``save_batch_durations``, so a test that runs a batch would otherwise
aim that save at the developer's real ``audio_suite_config.json``, where the
session guard turns it into a failure.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scratch_suite_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Redirect the shared config's read and write path for this test.

    The orchestrator's duration history is read by the ETA and written when a
    batch finishes, so both sides must land in the scratch file.  A test that
    needs a specific document writes it there itself.
    """
    from audio_suite_shared import suite_config

    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", config_file)
    monkeypatch.setattr(
        suite_config, "_LOCK_PATH", config_file.with_suffix(".json.lock")
    )
    suite_config._invalidate_cache()
    yield
    suite_config._invalidate_cache()
