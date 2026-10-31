"""Locks: the documentation index cannot lie.

PLAN_docs_consolidation P1.6. Before this file, the suite had no single front
door: the docs index's toctree listed the API reference and the plugin guide
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
Changed in 2.1.0: the index is Markdown (P3.1), so paths are single-backtick
spans and links are ``[text](target)``.  The tool table now links each guide's
Markdown source rather than the ``.docx`` artefact, because that is what the
rendered site can open (P3.3).
Changed in 2.1.1: the path scan no longer reads a MyST role's docname as a
repository path (PLAN_feature_expansion.md, Sprint 8).  ``{doc}`user/security```
names a document, and the page links subdirectory pages with that role because a
Markdown link to ``user/security.md`` is emitted verbatim by MyST - a dead link
in the rendered site.  The role body contains a slash, so the token regex
claimed it and the lock failed on a page that is correct; ``path_tokens`` strips
role spans first, and a lock-step test pins both halves.

Changed in 2.1.7: the index is ``documentation/docs/index.md``, and a guide's href is
its path from the page's folder.


Changed in 2.3.0: ``REQUIRED_TOOL_ROWS`` moves to 32, the regenerated table's row count.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "documentation" / "docs" / "index.md"
DOCS = REPO_ROOT / "documentation" / "docs"
GENERATOR = REPO_ROOT / "utilities" / "generate_docs_index.py"

#: The manifest ships 32 first-party tools; a table that loses rows fails here.
REQUIRED_TOOL_ROWS = 32

#: A MyST role span, e.g. ``{doc}`user/security```. Its body is a docname, not a
#: repository path, even when it contains a slash.
_MYST_ROLE = re.compile(r"\{[a-z]+\}`[^`]*`")

#: A backticked span that is a repository-relative path (it contains a slash).
_PATH_TOKEN = re.compile(r"`([A-Za-z0-9_][A-Za-z0-9_./-]*/[A-Za-z0-9_./-]+)`")


def path_tokens(text: str) -> set[str]:
    """Return the repository-relative paths a page names in backticks.

    MyST role spans are removed first: ``{doc}`user/security``` contains a slash
    but names a document, so reading it as a path would fail on a correct page
    (2.1.1).

    Args:
        text: The page source.

    Returns:
        The distinct backticked tokens that contain a slash.
    """
    return {m.group(1) for m in _PATH_TOKEN.finditer(_MYST_ROLE.sub("", text))}


#: A Markdown inline link: ``[text](target)``.
_LINK_TARGET = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

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
            "docs/index.md's tool table is stale. Re-run "
            "`python utilities/generate_docs_index.py` (the table is generated "
            "from audio_suite_shared/tool_plugin.py; do not hand-edit it)."
        )

    def test_the_table_has_every_tool(self) -> None:
        """The table carries one row per first-party tool, no more, no fewer."""
        text = INDEX.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if line.startswith("| ")]
        # One header row (Tool/Launcher/User guide), one separator, one per tool.
        assert len(rows) == REQUIRED_TOOL_ROWS + 2, (
            f"expected {REQUIRED_TOOL_ROWS} tool rows plus a header, found "
            f"{len(rows) - 1} tool rows"
        )


class TestPathsResolve:
    """Every path the index names exists on disk."""

    def test_every_repository_path_exists(self) -> None:
        """Backticked repo-relative paths must resolve from the repository root."""
        text = INDEX.read_text(encoding="utf-8")
        tokens = sorted(path_tokens(text))
        assert tokens, "no repository-relative paths found - the scan is vacuous"
        missing = [token for token in tokens if not (REPO_ROOT / token).exists()]
        assert not missing, (
            "docs/index.md names paths that do not exist:\n  " + "\n  ".join(missing)
        )

    def test_myst_role_targets_are_not_read_as_paths(self) -> None:
        """A ``{doc}`` docname is a document, not a claimed repository path."""
        sample = "See {doc}`user/security` and `audio_suite_shared/cli_app.py`."

        assert path_tokens(sample) == {"audio_suite_shared/cli_app.py"}

    def test_every_link_target_exists(self) -> None:
        """Inline link targets resolve relative to docs/ (external URLs aside)."""
        text = INDEX.read_text(encoding="utf-8")
        targets = [
            m.group(1).strip()
            for m in _LINK_TARGET.finditer(text)
            if not m.group(1).startswith(("http://", "https://", "mailto:"))
        ]
        assert targets, "no link targets found - the scan is vacuous"
        missing = [
            target
            for target in targets
            if not (DOCS / target.split("#", 1)[0]).exists()
        ]
        assert not missing, (
            "docs/index.md links to targets that do not exist:\n  "
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
            and path.suffix in {".md", ".rst"}
            and path != INDEX
            and not _EXCLUDED_PARTS.intersection(path.relative_to(DOCS).parts)
        ]
        return pages

    def test_every_tool_guide_is_named_by_the_index(self) -> None:
        """Each tool's Markdown guide appears in the generated table (P4.4)."""
        guides = sorted(
            (REPO_ROOT / "documentation" / "user_guides" / "individual_programs").glob(
                "*/*_User_Guide.md"
            )
        )
        assert len(guides) >= 30, (
            f"only {len(guides)} guide sources found - the walk is broken, so "
            "this lock would pass vacuously"
        )
        text = INDEX.read_text(encoding="utf-8")

        def as_written(guide: Path) -> str:
            """Return the href the page must carry for *guide*.

            The index is rendered as the link a reader's relative path needs, not
            as the repository-relative path: it sits in ``documentation/docs/``,
            one level below the tree both documents live in, so the href is
            ``../user_guides/...`` (AGENTS, Documentation Formats).
            """
            return Path(os.path.relpath(guide, INDEX.parent)).as_posix()

        missing = [
            as_written(guide) for guide in guides if as_written(guide) not in text
        ]
        assert not missing, (
            "tool guides are not linked from documentation/docs/index.md (re-run "
            "`python utilities/generate_docs_index.py`):\n  " + "\n  ".join(missing)
        )

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
            "pages under docs/ are not named by docs/index.md (add them to its "
            "toctree or link them):\n  " + "\n  ".join(unreachable)
        )
