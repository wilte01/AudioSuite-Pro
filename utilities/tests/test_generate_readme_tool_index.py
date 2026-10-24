"""Tests for ``utilities/generate_readme_tool_index.py``.

Iteration-9 S8 (G8.4, audit L4) brought ``utilities/`` under the coverage
gate.  The happy-path render is already locked by ``tests/test_readme.py``;
this file covers the validation error paths (unregistered guide, missing guide
artifact, missing launcher), the registry-extraction failure, and the
``main()`` CLI body so the script measures above the plan's 60% floor.

The ``if __name__ == "__main__":`` guard is excluded by the coverage config.

Changed in 2.1.0: the fake registry exposes ``first_party``, which the generator walks.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import generate_readme_tool_index as ti  # noqa: E402

_END_FULL = "<!-- TOOL INDEX: END -->"


def _manifest(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "id": "mystery",
        "name": "Mystery Tool",
        "description": "Does mysterious things",
        "pyw_filename": "Mystery_Tool.pyw",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _registry(*manifests: SimpleNamespace) -> SimpleNamespace:
    """Return a stand-in for the tool registry the generator reads.

    ``first_party`` is what the index renders; a plugin's tool has no guide or
    launcher row in the README, so the generator never walks ``all``.
    """
    return SimpleNamespace(all=list(manifests), first_party=list(manifests))


class TestExtractGuideRegistryFailure:
    """A changed shared-helper shape must fail loudly, not render dr(e)ift."""

    def test_missing_literal_raises_runtime_error(self) -> None:
        with patch.object(ti.ast, "parse", return_value=ast.parse("x = 1")):
            with pytest.raises(RuntimeError, match="guide_to_program"):
                ti.extract_guide_registry()


class TestRenderValidation:
    """Every row is validated before it is emitted."""

    def test_unregistered_guide_aborts_rendering(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with (
            patch.object(ti, "extract_guide_registry", return_value={}),
            patch(
                "audio_suite_shared.tool_plugin.get_registry",
                return_value=_registry(_manifest()),
            ),
        ):
            assert ti.render_tool_index() == ""
        assert "not registered" in capsys.readouterr().err

    def test_missing_guide_artifact_aborts_rendering(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        guide_name = ti.guide_filename_for("mystery", "Mystery_Tool.pyw")
        with (
            patch.object(
                ti,
                "extract_guide_registry",
                return_value={guide_name: "no_such_folder"},
            ),
            patch(
                "audio_suite_shared.tool_plugin.get_registry",
                return_value=_registry(_manifest()),
            ),
        ):
            assert ti.render_tool_index() == ""
        assert "guide artifact missing" in capsys.readouterr().err

    def test_missing_launcher_aborts_rendering(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        guide_name = ti.guide_filename_for("mystery", "Mystery_Tool.pyw")
        folder = "mystery_folder"
        guide_dir = tmp_path / "user_guides" / "individual_programs" / folder
        guide_dir.mkdir(parents=True)
        (guide_dir / guide_name).write_text("guide", encoding="utf-8")

        with (
            patch.object(ti, "REPO_ROOT", tmp_path),
            patch.object(
                ti, "extract_guide_registry", return_value={guide_name: folder}
            ),
            patch(
                "audio_suite_shared.tool_plugin.get_registry",
                return_value=_registry(_manifest()),
            ),
        ):
            assert ti.render_tool_index() == ""
        assert "launcher missing" in capsys.readouterr().err


class TestMain:
    """The CLI body: in-place splice, failure reports, marker guard."""

    def test_regenerates_in_place(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = tmp_path / "README.md"
        readme.write_text(
            "# Title\n\n"
            f"{ti.BEGIN_MARK} stale -->\n"
            "old body\n"
            f"{_END_FULL}\n\n"
            "# Trailing\n",
            encoding="utf-8",
        )

        with patch.object(ti, "README", readme):
            assert ti.main() == 0

        text = readme.read_text(encoding="utf-8")
        assert "old body" not in text
        assert "| Tool | What it does | Launcher | User guide | Platform |" in text
        assert "# Trailing" in text
        out = capsys.readouterr().out
        assert "[OK]" in out and "tool rows" in out
        assert "[DONE]" in out

    def test_registry_extraction_failure_is_reported(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch.object(
            ti,
            "extract_guide_registry",
            side_effect=RuntimeError("guide_to_program dict literal not found"),
        ):
            assert ti.main() == 1
        assert "[ERROR]" in capsys.readouterr().out

    def test_empty_render_is_reported(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch.object(ti, "render_tool_index", return_value=""):
            assert ti.main() == 1

    def test_missing_markers_are_reported(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# no markers here\n", encoding="utf-8")
        with patch.object(ti, "README", readme):
            assert ti.main() == 1
        assert "markers not found" in capsys.readouterr().out
