"""Locks: the documentation index cannot lie.

PLAN_docs_consolidation P1.6. Before this file, the suite had no single front
door: ``docs/index.rst``'s toctree listed the API reference and the plugin guide
only, and the nominal hub (``user_guides/README.md``) had rotted — it named two
files that do not exist, advertised per-tool logging guides a lock forbids, and
omitted about a third of the tools.

Four locks, each catching a different way an index goes wrong:

1. *Freshness* - the tool table is byte-identical to a fresh render from the
   manifest, so a tool cannot ship without appearing (and a hand edit is
   reverted by re-running the generator).
2. *Path truth* - every repository-relative path the page names exists. A bare
   filename in prose is a name, not a claim about a path, so only tokens
   containing ``/`` are checked; this is the rule that would have caught the
   hub's two ghost files.
3. *Reachability* - every page in ``docs/`` is named by the index, so a page
   cannot be added and then be unfindable.
4. *Non-vacuity* - the row and page sets must be non-empty, because an empty
   scan passes every assertion above while proving nothing.

Changed in 2.1.0: new file - the index freshness and reachability locks
(PLAN_docs_consolidation P1.6).
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "docs" / "index.rst"
DOCS = REPO_ROOT / "docs"
GENERATOR = REPO_ROOT / "utilities" / "generate_docs_index.py"

#: The manifest ships 30 first-party tools; a table that loses rows fails here.
REQUIRED_TOOL_ROWS = 30

#: A backticked token that is a repository-relative path (it contains a slash).
_PATH_TOKEN = re.compile(r"``([A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+)``")

#: An inline RST link target: ``text <target>``_.
_LINK_TARGET = re.compile(r"`[^`<]*<([^>`]+)>`_")

_EXCLUDED_PARTS = frozenset({"__pycache__", "_build", ".ipynb_checkpoints"})


def _load_generator() -> Any:
    """Load the docs-index generator as a module.

    Returns:
        The loaded module (``Any``: a dynamically loaded script has no static
        surface mypy can see, and the alternative is duplicating its render).

    Raises:
        AssertionError: If the generator file is missing, which would make the
            freshness lock pass vacuously.
    """
    assert GENERATOR.is_file(), f"docs-index generator missing: {GENERATOR}"
    spec = importlib.util.spec_from_file_location("_docs_index_generator", GENERATOR)
    assert spec is not None and spec.loader is not None, f"cannot load {GENERATOR}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestToolTableFreshness:
    """The rendered table is exactly what the manifest produces."""

    def test_the_committed_table_matches_a_fresh_render(self) -> None:
        """A stale table (or a hand edit) fails until regenerated."""
        generator = _load_generator()
        text = INDEX.read_text(encoding="utf-8")
        committed = generator.block_from_index(text).replace("\r\n", "\n")
        fresh = generator.render_tool_table().replace("\r\n", "\n")
        assert committed == fresh, (
            "docs/index.rst's tool table is stale. Re-run "
            "`python utilities/generate_docs_index.py` (the table is generated "
            "from audio_suite_shared/tool_plugin.py; do not hand-edit it)."
        )

    def test_the_table_has_every_tool(self) -> None:
        """The table carries one row per first-party tool, no more, no fewer."""
        text = INDEX.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if line.startswith("   * - ")]
        # One header row (Tool/Launcher/User guide) plus one row per tool.
        assert len(rows) == REQUIRED_TOOL_ROWS + 1, (
            f"expected {REQUIRED_TOOL_ROWS} tool rows plus a header, found "
            f"{len(rows) - 1} tool rows"
        )


class TestPathsResolve:
    """Every path the index names exists on disk."""

    def test_every_repository_path_exists(self) -> None:
        """Backticked repo-relative paths must resolve from the repository root."""
        text = INDEX.read_text(encoding="utf-8")
        tokens = sorted({m.group(1) for m in _PATH_TOKEN.finditer(text)})
        assert tokens, "no repository-relative paths found - the scan is vacuous"
        missing = [token for token in tokens if not (REPO_ROOT / token).exists()]
        assert not missing, (
            "docs/index.rst names paths that do not exist:\n  " + "\n  ".join(missing)
        )

    def test_every_link_target_exists(self) -> None:
        """Inline link targets resolve relative to docs/ (external URLs aside)."""
        text = INDEX.read_text(encoding="utf-8")
        targets = [
            m.group(1).strip()
            for m in _LINK_TARGET.finditer(text)
            if not m.group(1).startswith(("http://", "https://", "mailto:"))
        ]
        assert targets, "no link targets found - the scan is vacuous"
        missing = [target for target in targets if not (DOCS / target).exists()]
        assert not missing, (
            "docs/index.rst links to targets that do not exist:\n  "
            + "\n  ".join(missing)
        )


class TestEveryDocsPageIsReachable:
    """No page under docs/ is orphaned from the front door."""

    def _docs_pages(self) -> list[Path]:
        """Return every documentation page under docs/ (not the index itself).

        Returns:
            Page paths, sorted.
        """
        pages = [
            path
            for path in sorted(DOCS.rglob("*"))
            if path.is_file()
            and path.suffix in {".rst", ".md"}
            and path != INDEX
            and not _EXCLUDED_PARTS.intersection(path.relative_to(DOCS).parts)
        ]
        return pages

    def test_every_page_is_named_by_the_index(self) -> None:
        """Each page appears either as a toctree entry or as a link."""
        text = INDEX.read_text(encoding="utf-8")
        pages = self._docs_pages()
        assert len(pages) >= 3, (
            f"only {len(pages)} docs pages found - the walk is broken, so this "
            "lock would pass vacuously"
        )
        unreachable = []
        for page in pages:
            relative = page.relative_to(DOCS)
            # A toctree entry uses the stem without a suffix ("api"); a link
            # uses the path as written ("user/security.md").
            stem = relative.with_suffix("").as_posix()
            if relative.as_posix() in text or stem in text:
                continue
            unreachable.append(relative.as_posix())
        assert not unreachable, (
            "pages under docs/ are not named by docs/index.rst (add them to its "
            "toctree or link them):\n  " + "\n  ".join(unreachable)
        )
