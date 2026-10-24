#!/usr/bin/env python3
"""
generate_docs_index.py

Regenerates the tool table in ``docs/index.md`` -- the repository's single
documentation front door -- from the tool manifest.

Why this exists
---------------
The suite ships 30 tools, each with a generated ``.docx`` user guide, and the
guides used to be discoverable only through ``README.md``'s table and a hand-
written ``user_guides/README.md`` hub. That hub drifted: it named two files that
do not exist, promised per-tool logging guides a test forbids, and omitted about
a third of the tools (PLAN_docs_consolidation F1). A hand-written list of 30
artefacts cannot stay true, so the list is rendered.

Source of truth (reused, not duplicated): the README index generator already
validates every row against the manifest, the ``guide_to_program`` registry in
``audio_suite_shared/platform_utils.py`` and the files on disk. This script
loads that module and calls its helpers, so the two indexes cannot disagree
about which guide belongs to which tool; only the rendering differs (this one
links each tool's Markdown guide source, because the docs site cannot open the
``.docx`` artefact; the README table links the ``.docx`` a user actually reads).

Usage:
    python utilities/generate_docs_index.py

Run this after adding or renaming a tool. The block between the ``DOCS TOOL
INDEX`` markers is the only part of ``docs/index.md`` this script touches.

Conventions (AGENTS.md "Utility Script Markers"): ASCII-only [START] / [OK] /
[ERROR] / [DONE] status markers on stdout/stderr.

Changed in 2.1.0: new file - the generated tool table behind the single
documentation index (PLAN_docs_consolidation P1.6).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX = REPO_ROOT / "docs" / "index.md"
README_INDEX = REPO_ROOT / "utilities" / "generate_readme_tool_index.py"

#: HTML comments, not RST comments: the page is Markdown since P3.1, and a
#: MyST comment is the only marker form that renders to nothing.
BEGIN_MARK = "<!-- DOCS TOOL INDEX: BEGIN"
END_MARK = "<!-- DOCS TOOL INDEX: END -->"


def _load_readme_tool_index() -> Any:
    """Load the README index generator as a module.

    ``utilities/`` is a directory of scripts, not an importable package, so the
    sibling module is loaded by path rather than imported. Loading it executes no
    side effects: its ``main()`` runs only under ``__main__``.

    Returns:
        The loaded module. Typed as ``Any`` because a dynamically loaded module
        has no static surface mypy can see.

    Raises:
        RuntimeError: If the module cannot be loaded from its path.
    """
    spec = importlib.util.spec_from_file_location("_readme_tool_index", README_INDEX)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {README_INDEX}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tool_rows() -> list[tuple[str, str, str]]:
    """Return one (name, launcher, guide path) tuple per first-party tool.

    Every row is validated before it is returned: the derived guide filename must
    be registered in ``guide_to_program``, its ``.docx`` must exist under
    ``user_guides/individual_programs/``, and the launcher ``.pyw`` must exist at
    the suite root.

    Returns:
        Rows in manifest order.

    Raises:
        RuntimeError: If a row cannot be validated - a dead row is a defect in
            the manifest or the guide tree, never something to render silently.
    """
    from audio_suite_shared.tool_plugin import get_registry

    readme = _load_readme_tool_index()
    guides: dict[str, str] = readme.extract_guide_registry()

    rows: list[tuple[str, str, str]] = []
    for manifest in get_registry().first_party:
        guide_name = readme.guide_filename_for(manifest.id, manifest.pyw_filename)
        folder = guides.get(guide_name)
        if not folder:
            raise RuntimeError(
                f"{manifest.id}: guide {guide_name!r} is not registered in "
                "guide_to_program (audio_suite_shared/platform_utils.py)"
            )
        guide_path = f"user_guides/individual_programs/{folder}/{guide_name}"
        if not (REPO_ROOT / guide_path).is_file():
            raise RuntimeError(f"{manifest.id}: guide artifact missing: {guide_path}")
        if not (REPO_ROOT / manifest.pyw_filename).is_file():
            raise RuntimeError(
                f"{manifest.id}: launcher missing: {manifest.pyw_filename}"
            )
        rows.append((manifest.name, manifest.pyw_filename, guide_path))
    return rows


def render_tool_table() -> str:
    """Render the marker-enclosed Markdown tool table.

    Each row links the tool's **Markdown guide source** (``../user_guides/...``),
    which is what the docs site can render; the Help button opens the ``.docx``
    beside it, and the README's own table links that artefact.

    Returns:
        The complete block, markers included, with ``\\n`` terminators.
    """
    lines: list[str] = [
        f"{BEGIN_MARK} - generated by utilities/generate_docs_index.py from",
        "     audio_suite_shared/tool_plugin.py, validated against",
        "     guide_to_program and the files on disk; re-run the script after",
        "     adding or renaming a tool; do not edit the table by hand. -->",
        "",
        "| Tool | Launcher | User guide |",
        "| --- | --- | --- |",
    ]
    for name, launcher, guide in tool_rows():
        source = str(Path(guide).with_suffix(".md")).replace("\\", "/")
        lines.append(f"| {name} | `{launcher}` | [Markdown](../{source}) |")
    lines.extend(["", END_MARK])
    return "\n".join(lines)


def block_from_index(text: str) -> str:
    """Return the committed tool-table block from an index document.

    Args:
        text: The whole ``docs/index.md`` document.

    Returns:
        The block between (and including) the markers, with ``\\n`` terminators.

    Raises:
        RuntimeError: If either marker is missing or out of order.
    """
    begin = text.find(BEGIN_MARK)
    end = text.find(END_MARK)
    if begin == -1 or end == -1 or end < begin:
        raise RuntimeError("DOCS TOOL INDEX markers not found in docs/index.md")
    return text[begin : end + len(END_MARK)].replace("\r\n", "\n")


def render_index(text: str) -> str:
    """Return *text* with its tool-table block replaced by a fresh render.

    Args:
        text: The whole ``docs/index.md`` document.

    Returns:
        The document with the regenerated block, keeping its line terminators.

    Raises:
        RuntimeError: If the markers are missing (fix the document, not the copy).
    """
    block_from_index(text)  # validates the markers and their order
    begin = text.find(BEGIN_MARK)
    end = text.find(END_MARK) + len(END_MARK)
    terminator = "\r\n" if "\r\n" in text else "\n"
    return text[:begin] + render_tool_table().replace("\n", terminator) + text[end:]


def main() -> int:
    """Regenerate the docs-index tool table in place.

    Returns:
        Process exit code: 0 on success, 1 when the document or a row is invalid.
    """
    print("[START] Regenerating the docs/index.md tool table")
    try:
        text = INDEX.read_text(encoding="utf-8")
        new_text = render_index(text)
        rows = len(tool_rows())
    except RuntimeError as exc:
        print(f"[ERROR] {exc}")
        return 1
    INDEX.write_text(new_text, encoding="utf-8", newline="")
    print(f"[OK] Tool table regenerated: {rows} tool rows")
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
