#!/usr/bin/env python3
"""
build_user_guides.py

Renders every per-tool user guide from its Markdown source.

Source of truth:  ``user_guides/individual_programs/<tool>/<Guide>_User_Guide.md``
Artefact:         ``user_guides/individual_programs/<tool>/<Guide>_User_Guide.docx``

Why this exists
---------------
Each guide used to be produced by its own copy of a python-docx script, so the
prose lived in Python: editing one sentence was a code edit policed by ruff,
mypy and bandit, 24 of the 33 generators wrote to a hard-coded absolute path
belonging to one developer's profile, and the 31 scripts shared no renderer at
all (PLAN_docs_consolidation F4). This module is the single renderer; the guides
are Markdown, which is also what the documentation index and the docs site read.

The dialect is deliberately small - only what the guides actually use:

* YAML-ish front matter with ``title``, and either ``subtitle`` or
  ``version: auto`` (renders ``Version <declared> - <Month YYYY>`` from
  ``audio_suite_shared.project_version.declared_version()``, so a release bump
  never leaves a stale label behind);
* ``##`` / ``###`` / ``####`` headings (rendered as heading levels 1 / 2 / 3,
  with the title as level 0);
* paragraphs, with ``**bold**`` spans;
* ``- `` bullets and ``1. `` numbered steps;
* ``| a | b |`` tables, the first row a bold header;
* ``> `` callouts (a shaded single-cell box);
* ``` ```text ``` fenced code boxes (Consolas, shaded).

Usage:
    python utilities/build_user_guides.py             # rebuild every guide
    python utilities/build_user_guides.py --check      # verify artefacts are current
    python utilities/build_user_guides.py bpm_analyzer # one tool

``--check`` renders into a temporary directory and compares **zip-entry data**
with the committed artefact. It never compares file hashes: python-docx rebuilds
the zip container on every save, so the local-header timestamps always differ
(AGENTS.md, "User-Guide Regeneration Diffs"). A difference outside
``word/document.xml`` is reported as drift to investigate, not as a content
failure - that is what the release cut's zip-entry triage already does.

Conventions (AGENTS.md "Utility Script Markers"): ASCII-only [START] / [OK] /
[INFO] / [ERROR] / [DONE] markers on stdout/stderr.

Changed in 2.1.0: new file - the one Markdown-to-docx renderer for every per-tool
user guide (PLAN_docs_consolidation P2.1).
"""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.table import _Cell
from docx.text.paragraph import Paragraph

REPO_ROOT = Path(__file__).resolve().parents[1]
GUIDE_ROOT = REPO_ROOT / "user_guides" / "individual_programs"

#: Colour fills, matching the helpers the retired generators used.
CALL_OUT_FILL = "FFF4CE"
CODE_FILL = "F2F2F2"
HEADER_FILL = "D9E2F3"

_HEADING = re.compile(r"^(#{2,4}) (.+)$")
_BULLET = re.compile(r"^- (.+)$")
_NUMBERED = re.compile(r"^\d+\. (.+)$")
_TABLE_ROW = re.compile(r"^\|(.*)\|$")
_BOLD_SPAN = re.compile(r"\*\*(.+?)\*\*")


@dataclass
class Guide:
    """A parsed guide: its front matter and its blocks, in order.

    Attributes:
        title: The document title (heading level 0).
        subtitle: A literal subtitle line, or an empty string.
        version: ``auto`` to render the dynamic version line, or an empty string.
        blocks: ``(kind, payload)`` pairs; kind is one of ``h``, ``p``, ``ul``,
            ``ol``, ``table``, ``callout``, ``code``.
    """

    title: str
    subtitle: str = ""
    version: str = ""
    blocks: list[tuple[str, Any]] = field(default_factory=list)


def _split_bold(text: str) -> list[tuple[str, bool]]:
    """Split *text* into ``(segment, is_bold)`` runs.

    Args:
        text: A line of prose that may contain ``**bold**`` spans.

    Returns:
        The runs in order; at least one entry unless *text* is empty.
    """
    runs: list[tuple[str, bool]] = []
    position = 0
    for match in _BOLD_SPAN.finditer(text):
        if match.start() > position:
            runs.append((text[position : match.start()], False))
        runs.append((match.group(1), True))
        position = match.end()
    if position < len(text):
        runs.append((text[position:], False))
    return runs


def parse_guide(text: str, source: Path) -> Guide:
    """Parse a guide's Markdown into a :class:`Guide`.

    Args:
        text: The whole Markdown document.
        source: The file it came from, used in error messages.

    Returns:
        The parsed guide.

    Raises:
        ValueError: If the front matter is missing or has no ``title``.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"{source}: missing front matter (must start with ---)")
    meta: dict[str, str] = {}
    index = 1
    while index < len(lines) and lines[index].strip() != "---":
        key, _, value = lines[index].partition(":")
        meta[key.strip()] = value.strip()
        index += 1
    if index >= len(lines):
        raise ValueError(f"{source}: front matter is not closed with ---")
    if not meta.get("title"):
        raise ValueError(f"{source}: front matter needs a title")

    guide = Guide(
        title=meta["title"],
        subtitle=meta.get("subtitle", ""),
        version=meta.get("version", ""),
    )

    body = lines[index + 1 :]
    position = 0
    while position < len(body):
        line = body[position]
        stripped = line.strip()

        if not stripped:
            position += 1
            continue

        heading = _HEADING.match(stripped)
        if heading:
            guide.blocks.append(("h", (len(heading.group(1)) - 1, heading.group(2))))
            position += 1
            continue

        if stripped.startswith("```"):
            code: list[str] = []
            position += 1
            while position < len(body) and not body[position].strip().startswith("```"):
                code.append(body[position])
                position += 1
            position += 1  # closing fence
            guide.blocks.append(("code", "\n".join(code)))
            continue

        if stripped.startswith(">"):
            note: list[str] = []
            while position < len(body) and body[position].strip().startswith(">"):
                note.append(body[position].strip()[1:].strip())
                position += 1
            guide.blocks.append(("callout", note))
            continue

        if _TABLE_ROW.match(stripped):
            rows: list[list[str]] = []
            while position < len(body) and _TABLE_ROW.match(body[position].strip()):
                row_text = body[position].strip().strip("|")
                cells = [cell.strip() for cell in row_text.split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    rows.append(cells)
                position += 1
            guide.blocks.append(("table", rows))
            continue

        bullet = _BULLET.match(stripped)
        if bullet:
            items: list[str] = []
            while position < len(body):
                match = _BULLET.match(body[position].strip())
                if not match:
                    break
                items.append(match.group(1))
                position += 1
            guide.blocks.append(("ul", items))
            continue

        numbered = _NUMBERED.match(stripped)
        if numbered:
            steps: list[str] = []
            while position < len(body):
                match = _NUMBERED.match(body[position].strip())
                if not match:
                    break
                steps.append(match.group(1))
                position += 1
            guide.blocks.append(("ol", steps))
            continue

        paragraph: list[str] = []
        while position < len(body):
            raw_line = body[position].rstrip()
            candidate = raw_line.strip()
            if not candidate:
                break
            # A leading backslash escapes a paragraph whose own text begins
            # with a structural marker ("- End of User Guide -").
            escaped = False
            if not paragraph and candidate.startswith("\\"):
                candidate = candidate[1:]
                raw_line = candidate
                escaped = True
            if (
                not paragraph
                and not escaped
                and (
                    _HEADING.match(candidate)
                    or candidate.startswith(("```", ">"))
                    or _TABLE_ROW.match(candidate)
                    or _BULLET.match(candidate)
                    or _NUMBERED.match(candidate)
                )
            ):
                break
            if raw_line.endswith("\\"):
                # A trailing backslash is a hard break: the word processor shows
                # these as separate lines inside one paragraph (command blocks),
                # and the original indentation is part of the text.
                paragraph.append(raw_line[:-1])
                paragraph.append("\n")
            elif paragraph and paragraph[-1] == "\n":
                paragraph.append(raw_line)
            else:
                paragraph.append(raw_line + " ")
            position += 1
        if not paragraph and position < len(body):
            # Defensive: an unhandled shape must advance, never spin.
            position += 1
            continue
        guide.blocks.append(("p", "".join(paragraph).rstrip()))

    return guide


def _shade(cell: _Cell, fill: str) -> None:
    """Apply a solid background fill to a table cell.

    Args:
        cell: The python-docx cell to fill.
        fill: A six-digit hex colour.
    """
    cell_pr = cell._tc.get_or_add_tcPr()
    element = cell_pr.makeelement(qn("w:shd"), {})
    element.set(qn("w:val"), "clear")
    element.set(qn("w:color"), "auto")
    element.set(qn("w:fill"), fill)
    cell_pr.append(element)


def _add_runs(paragraph: Paragraph, text: str) -> None:
    """Append *text* to *paragraph*, honouring ``**bold**`` spans.

    Args:
        paragraph: The python-docx paragraph to fill.
        text: The text, possibly containing bold spans.
    """
    for segment, bold in _split_bold(text):
        if not segment:
            continue
        run = paragraph.add_run(segment)
        if bold:
            run.bold = True


def _render_box(
    doc: DocxDocument, lines: list[str], fill: str, title_bold: bool
) -> None:
    """Render a callout or code box: a shaded single-cell table.

    Args:
        doc: The python-docx document.
        lines: The box's lines.
        fill: The cell fill colour.
        title_bold: Whether the first line is a bold title (callout) rather than
            monospaced code.
    """
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.cell(0, 0)
    _shade(cell, fill)
    paragraph = cell.paragraphs[0]
    if title_bold and len(lines) > 1:
        run = paragraph.add_run(f"{lines[0]}\n")
        run.bold = True
        _add_runs(paragraph, " ".join(line for line in lines[1:] if line))
    elif title_bold:
        _add_runs(paragraph, lines[0] if lines else "")
    else:
        for index, line in enumerate(lines):
            if index:
                paragraph.add_run("\n")
            run = paragraph.add_run(line)
            run.font.name = "Consolas"
            run.font.size = Pt(9)
    doc.add_paragraph()


def render_guide(guide: Guide) -> DocxDocument:
    """Build the python-docx document for *guide*.

    Args:
        guide: The parsed guide.

    Returns:
        The document, ready to save.
    """
    doc = Document()

    title = doc.add_heading(guide.title, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    if guide.version == "auto":
        from datetime import date

        from audio_suite_shared.project_version import declared_version

        line = f"Version {declared_version()} \u2014 {date.today().strftime('%B %Y')}"
        paragraph = doc.add_paragraph(line)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    elif guide.subtitle:
        paragraph = doc.add_paragraph(guide.subtitle)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for kind, payload in guide.blocks:
        if kind == "h":
            level, text = payload
            doc.add_heading(text, level=level)
        elif kind == "p":
            _add_runs(doc.add_paragraph(), str(payload))
        elif kind == "ul":
            for item in payload:
                _add_runs(doc.add_paragraph(style="List Bullet"), str(item))
        elif kind == "ol":
            for item in payload:
                _add_runs(doc.add_paragraph(style="List Number"), str(item))
        elif kind == "table":
            rows: list[list[str]] = payload
            if not rows:
                continue
            table = doc.add_table(rows=1, cols=len(rows[0]))
            table.style = "Table Grid"
            for column, header in enumerate(rows[0]):
                cell = table.cell(0, column)
                _shade(cell, HEADER_FILL)
                run = cell.paragraphs[0].add_run(header)
                run.bold = True
            for row in rows[1:]:
                cells = table.add_row().cells
                for column, value in enumerate(row[: len(cells)]):
                    cells[column].paragraphs[0].add_run(value)
            doc.add_paragraph()
        elif kind == "callout":
            _render_box(doc, [str(line) for line in payload], CALL_OUT_FILL, True)
        elif kind == "code":
            _render_box(doc, str(payload).split("\n"), CODE_FILL, False)
    return doc


def guide_sources() -> list[Path]:
    """Return every committed guide Markdown source.

    Returns:
        Source paths, sorted.
    """
    return sorted(GUIDE_ROOT.glob("*/*_User_Guide.md"))


def target_for(source: Path) -> Path:
    """Return the artefact path for a guide source.

    Args:
        source: The ``.md`` source path.

    Returns:
        The ``.docx`` path beside it (the path the Help button opens).
    """
    return source.with_suffix(".docx")


def entry_data(path: Path) -> dict[str, bytes]:
    """Return a docx container's entries mapped to their bytes.

    Args:
        path: The ``.docx`` file.

    Returns:
        Entry name to raw bytes.
    """
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def check_guide(source: Path) -> list[str]:
    """Verify that a guide's committed artefact matches its source.

    Args:
        source: The Markdown source.

    Returns:
        Human-readable problems; empty when the artefact is current.
    """
    target = target_for(source)
    if not target.is_file():
        return [f"{target.relative_to(REPO_ROOT)}: missing artefact"]
    guide = parse_guide(source.read_text(encoding="utf-8"), source)
    with tempfile.TemporaryDirectory() as scratch:
        fresh = Path(scratch) / target.name
        render_guide(guide).save(str(fresh))
        before = entry_data(target)
        after = entry_data(fresh)
    problems: list[str] = []
    if set(before) != set(after):
        problems.append(
            f"{target.relative_to(REPO_ROOT)}: container entries differ "
            f"(+{sorted(set(after) - set(before))} -{sorted(set(before) - set(after))})"
        )
    if before.get("word/document.xml") != after.get("word/document.xml"):
        problems.append(
            f"{target.relative_to(REPO_ROOT)}: word/document.xml differs from "
            f"{source.name}; run `python utilities/build_user_guides.py`"
        )
    return problems


def rebuild(source: Path) -> None:
    """Rebuild one artefact from its source, in place.

    Args:
        source: The Markdown source.
    """
    guide = parse_guide(source.read_text(encoding="utf-8"), source)
    render_guide(guide).save(str(target_for(source)))


def main(argv: list[str]) -> int:
    """Rebuild or check every guide.

    Args:
        argv: Command-line arguments after the program name.

    Returns:
        Process exit code: 0 on success, 1 on a problem.
    """
    check = "--check" in argv
    wanted = [a for a in argv if not a.startswith("--")]

    sources = guide_sources()
    if wanted:
        sources = [s for s in sources if s.parent.name in wanted]
    if not sources:
        print("[ERROR] no guide sources found under user_guides/individual_programs")
        return 1

    print(f"[START] {'Checking' if check else 'Rebuilding'} {len(sources)} user guides")
    problems: list[str] = []
    for source in sources:
        try:
            if check:
                problems.extend(check_guide(source))
            else:
                rebuild(source)
                print(f"[OK] {target_for(source).name}")
        except (ValueError, KeyError, OSError) as exc:
            problems.append(f"{source.relative_to(REPO_ROOT)}: {exc}")

    if check:
        if problems:
            print("[ERROR] guide artefacts are stale:", file=sys.stderr)
            for problem in problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        print(f"[OK] {len(sources)} guide artefacts are current")
    print("[DONE]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
