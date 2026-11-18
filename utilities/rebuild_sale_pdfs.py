"""Rebuild the two sale-pack PDFs from their sources.

The metrics sheet is Markdown printed to a single A4 page by headless Chrome;
the deck is a PowerPoint export done with LibreOffice.  Both were originally
built by hand at a shell prompt, so this script pins the two details that are
easy to lose: the one-page print CSS (6.5 pt body, 7 mm margins) and the exact
converter invocations.

Usage (from anywhere, under the project .venv):

    python utilities/rebuild_sale_pdfs.py                # both PDFs
    python utilities/rebuild_sale_pdfs.py --only sheet   # just the metrics sheet
    python utilities/rebuild_sale_pdfs.py --only deck    # just the deck

Both converters are located automatically on Windows and can be overridden with
--chrome / --soffice or the CHROME_PATH / SOFFICE_PATH environment variables.

Exit status is 0 only if every requested PDF was rebuilt and passed its check:
the metrics sheet must come out as exactly one page (a longer sheet means the
content grew and the print CSS needs re-tuning), and the deck PDF must have one
page per slide.
"""

# Changed in 2.8.0: added as the reproducible builder for the two sale-pack
# PDFs, which were previously rendered by hand at a shell prompt.

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Sequence

#: The pack this script rebuilds, which sits beside the repository root.
SALE_DIR = Path(__file__).resolve().parent.parent / "sale"
SHEET_MD = SALE_DIR / "AudioSuite-Pro_Metrics_Sheet.md"
SHEET_PDF = SALE_DIR / "AudioSuite-Pro_Metrics_Sheet.pdf"
DECK_PPTX = SALE_DIR / "AudioSuite-Pro_Buyer_Presentation.pptx"
DECK_PDF = SALE_DIR / "AudioSuite-Pro_Buyer_Presentation.pdf"

#: Body size that fills exactly one A4 page.  Raising it spills a whole table
#: row onto page 2 (Chrome will not split rows), so this value is load-bearing.
SHEET_PT = 6.5

_PAGE_RE = re.compile(rb"/Type\s*/Page[^s]")


def _program_roots() -> list[Path]:
    """The Windows installation roots a converter is normally found under.

    Read from the environment rather than written as literals: a hard-coded
    drive path names one machine, and ``tests/test_docs_formats.py`` fails any
    documentation tooling that does it.  These variables are what Windows
    guarantees, so the lookup is both portable and testable.
    """
    roots: list[Path] = []
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(name)
        if value:
            roots.append(Path(value))
    return roots


def _installed(*relative: str) -> tuple[Path, ...]:
    """Every install root's candidate for one program, in preference order."""
    return tuple(root.joinpath(*relative) for root in _program_roots())


_CHROME_CANDIDATES = (
    *_installed("Google", "Chrome", "Application", "chrome.exe"),
    *_installed("Microsoft", "Edge", "Application", "msedge.exe"),
)

_SOFFICE_CANDIDATES = _installed("LibreOffice", "program", "soffice.exe")


def _log(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def _locate(
    explicit: str | None,
    env_var: str,
    names: Sequence[str],
    candidates: Sequence[Path],
    what: str,
) -> Path:
    """Find a converter binary: flag, then environment, then PATH, then defaults."""
    for given in (explicit, os.environ.get(env_var)):
        if given:
            path = Path(given)
            if path.is_file():
                return path
            raise SystemExit(f"[ERROR] {what} not found at {path}")
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise SystemExit(
        f"[ERROR] {what} not found. Pass it with {env_var.replace('_PATH', '').lower()}"
        f" or set {env_var}."
    )


def _sheet_css(size: float) -> str:
    """The one-page print stylesheet for the metrics sheet.

    Declarations are split one per line so the source stays inside the line
    limit; CSS does not care where the whitespace falls inside a rule.
    """
    rules = [
        "@page { size: A4; margin: 7mm 7mm; }",
        "html, body { margin: 0; padding: 0; }",
        "body {",
        '  font-family: "Segoe UI", Arial, sans-serif;',
        f"  font-size: {size}pt;",
        "  line-height: 1.14;",
        "  color: #1b1b1b;",
        "}",
        f"h1 {{ font-size: {size + 3}pt; margin: 0 0 1pt 0; }}",
        "h2 {",
        f"  font-size: {size + 0.8}pt;",
        "  margin: 5pt 0 1pt 0;",
        "  padding-bottom: 1pt;",
        "  border-bottom: 1px solid #ccc;",
        "}",
        "p { margin: 1pt 0; }",
        "table {",
        "  width: 100%;",
        "  border-collapse: collapse;",
        "  table-layout: fixed;",
        "  margin: 1pt 0 3pt 0;",
        f"  font-size: {size - 0.4}pt;",
        "  line-height: 1.1;",
        "}",
        "th, td {",
        "  border: 1px solid #c8c8c8;",
        "  padding: 0.6pt 2.5pt;",
        "  text-align: left;",
        "  vertical-align: top;",
        "  overflow-wrap: anywhere;",
        "}",
        "th { background: #efefef; }",
        "td:nth-child(1), th:nth-child(1) { width: 25%; }",
        "td:nth-child(2), th:nth-child(2) { width: 20%; }",
        "code {",
        '  font-family: Consolas, "Courier New", monospace;',
        f"  font-size: {size - 0.7}pt;",
        "}",
        "hr { border: 0; border-top: 1px solid #ccc; margin: 4pt 0; }",
        "ul { margin: 1pt 0; padding-left: 11pt; }",
    ]
    return "\n".join(rules)


def _page_count(pdf: Path) -> int:
    return len(_PAGE_RE.findall(pdf.read_bytes()))


def _build_sheet(chrome: Path, workdir: Path) -> None:
    try:
        from markdown_it import MarkdownIt
    except ImportError:  # pragma: no cover - dev/documentation dependency
        raise SystemExit(
            "[ERROR] markdown-it-py is required to render the metrics sheet "
            "(uv sync --extra dev)."
        ) from None

    if not SHEET_MD.is_file():
        raise SystemExit(f"[ERROR] missing source: {SHEET_MD}")

    body = (
        MarkdownIt("commonmark")
        .enable("table")
        .render(SHEET_MD.read_text(encoding="utf-8"))
    )
    html_path = workdir / "sheet.html"
    pdf_path = workdir / "sheet.pdf"
    html_path.write_text(
        "<html><head><meta charset='utf-8'><style>"
        f"{_sheet_css(SHEET_PT)}</style></head><body>{body}</body></html>",
        encoding="utf-8",
    )
    _log("INFO", f"printing sheet at {SHEET_PT} pt with {chrome.name}")
    subprocess.run(
        [
            str(chrome),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    pages = _page_count(pdf_path)
    if pages != 1:
        raise SystemExit(
            f"[ERROR] metrics sheet came out as {pages} pages, not 1. Content has "
            "grown: reduce SHEET_PT or condense the sheet."
        )
    shutil.copyfile(pdf_path, SHEET_PDF)
    _log("OK", f"metrics sheet: 1 page, {SHEET_PDF.stat().st_size:,} bytes")


def _build_deck(soffice: Path, workdir: Path) -> None:
    from pptx import Presentation

    if not DECK_PPTX.is_file():
        raise SystemExit(f"[ERROR] missing source: {DECK_PPTX}")
    slides = len(Presentation(str(DECK_PPTX)).slides)

    _log("INFO", f"exporting deck with {soffice.name}")
    subprocess.run(
        [
            str(soffice),
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(workdir),
            str(DECK_PPTX),
        ],
        check=True,
        capture_output=True,
    )
    exported = workdir / f"{DECK_PPTX.stem}.pdf"
    if not exported.is_file():
        raise SystemExit(f"[ERROR] LibreOffice produced no PDF for {DECK_PPTX.name}")
    pages = _page_count(exported)
    if pages != slides:
        raise SystemExit(
            f"[ERROR] deck PDF has {pages} pages but the deck has {slides} slides."
        )
    shutil.copyfile(exported, DECK_PDF)
    _log("OK", f"deck: {pages} pages, {DECK_PDF.stat().st_size:,} bytes")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        choices=("sheet", "deck", "all"),
        default="all",
        help="which PDF to rebuild (default: both)",
    )
    parser.add_argument("--chrome", help="path to chrome.exe / msedge.exe")
    parser.add_argument("--soffice", help="path to soffice.exe")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="sale_pdfs_") as tmp:
        workdir = Path(tmp)
        if args.only in ("sheet", "all"):
            chrome = _locate(
                args.chrome,
                "CHROME_PATH",
                ("chrome", "google-chrome", "chromium"),
                _CHROME_CANDIDATES,
                "a Chromium browser",
            )
            _build_sheet(chrome, workdir)
        if args.only in ("deck", "all"):
            soffice = _locate(
                args.soffice,
                "SOFFICE_PATH",
                ("soffice",),
                _SOFFICE_CANDIDATES,
                "LibreOffice",
            )
            _build_deck(soffice, workdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
