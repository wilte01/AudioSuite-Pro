"""Tests for the user-guide renderer's command line.

The renderer's exit status is what the gate and CI read, so a rebuild that
cannot draw a guide must fail rather than print ``[DONE]``: the first version of
this script collected the error, printed nothing, and exited 0, and the missing
figure only surfaced later as an ``[ERROR] ... guide artifact missing`` from the
docs-index generator.

Changed in 2.5.0: initial version, locking both exit statuses of the renderer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from utilities import build_user_guides


@pytest.fixture(name="source")
def fixture_source(tmp_path: Path) -> Path:
    """Return one guide source whose figure was never captured.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The path of a Markdown source that references a missing image.
    """
    guide_dir = tmp_path / "audio_joiner"
    guide_dir.mkdir()
    source = guide_dir / "Audio_Joiner_User_Guide.md"
    source.write_text(
        "---\ntitle: Audio Joiner - User Guide\nsubtitle: Test source\n---\n\n"
        "## Setup Tab\n\n"
        "![The Setup tab](images/setup.png)\n",
        encoding="utf-8",
    )
    return source


class TestMainExitStatus:
    """A failed render is a failure of the command, not a silent no-op."""

    def test_a_missing_figure_fails_the_rebuild(
        self,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The error names the guide and the script exits non-zero."""
        monkeypatch.setattr(build_user_guides, "guide_sources", lambda: [source])

        code = build_user_guides.main([])

        captured = capsys.readouterr()
        assert code == 1
        assert "some guides could not be rebuilt" in captured.err
        assert "setup.png" in captured.err
        assert "audio_joiner" in captured.err
        assert "[OK] Audio_Joiner_User_Guide.docx" not in captured.out

    def test_a_produced_guide_exits_zero(
        self,
        source: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A render that returns reports its artefact and succeeds."""
        monkeypatch.setattr(build_user_guides, "guide_sources", lambda: [source])
        monkeypatch.setattr(build_user_guides, "rebuild", lambda _source: None)

        code = build_user_guides.main([])

        captured = capsys.readouterr()
        assert code == 0
        assert "[OK] Audio_Joiner_User_Guide.docx" in captured.out
        assert captured.err == ""
