"""Tests for ``utilities/generate_readme_platform_matrix.py``.

Iteration-9 S8 (G8.4, audit L4) brought ``utilities/`` under the coverage
gate.  ``render_platform_matrix`` is already locked by
``audio_suite_shared/tests/test_platform_support.py`` (the README drift lock);
this file covers the ``main()`` CLI body and its empty-render / missing-marker
guards so the script measures above the plan's 60% floor.

The ``if __name__ == "__main__":`` guard is excluded by the coverage config.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import generate_readme_platform_matrix as pm  # noqa: E402

_END_FULL = "<!-- PLATFORM MATRIX: END -->"


def _write_readme_with_markers(path: Path) -> None:
    path.write_text(
        f"# Title\n\n{pm.BEGIN_MARK} stale -->\nold body\n{_END_FULL}\n\n# Trailing\n",
        encoding="utf-8",
    )


class TestMain:
    """``main()`` splices a fresh block, or fails loudly without touching it."""

    def test_splices_a_fresh_block_between_the_markers(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = tmp_path / "README.md"
        _write_readme_with_markers(readme)

        with patch.object(pm, "README", readme):
            assert pm.main() == 0

        text = readme.read_text(encoding="utf-8")
        assert "old body" not in text
        assert "#### Branch enumeration" in text
        assert "# Trailing" in text
        out = capsys.readouterr().out
        assert "[OK]" in out and "branch rows" in out
        assert "[DONE]" in out

    def test_empty_render_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(pm, "render_platform_matrix", return_value=""):
            assert pm.main() == 1
        assert "[ERROR]" in capsys.readouterr().out

    def test_missing_markers_are_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# no markers here\n", encoding="utf-8")
        with patch.object(pm, "README", readme):
            assert pm.main() == 1
        assert "markers not found" in capsys.readouterr().out
