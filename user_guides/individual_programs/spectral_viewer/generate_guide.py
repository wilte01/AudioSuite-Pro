"""Generate a fresh Spectral Viewer guide from the current implementation.

Section content and the flag table come from the code, not from a hand-written
copy: the defaults are imported from ``spectral_viewer.core.spectrogram`` and
``spectral_viewer.cli``'s options, so a changed default cannot leave the guide
behind.

Run with the interpreter that carries the dev extras (python-docx):

    python user_guides/individual_programs/spectral_viewer/generate_guide.py

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from audio_suite_shared.project_version import declared_version  # noqa: E402
from spectral_viewer.core.spectrogram import (  # noqa: E402
    DEFAULT_CMAP,
    DEFAULT_DB_RANGE,
    DEFAULT_HOP_LENGTH,
    DEFAULT_N_FFT,
    MAX_ANALYSIS_SECONDS,
    OUTPUT_SUFFIX,
)

OUTPUT = Path(__file__).resolve().parent / "Spectral_Viewer_User_Guide.docx"

FORMATS = (
    "MP3, FLAC, OGG, Opus, Speex, M4A, MP4, WAV, AIFF, AIF, WavPack, "
    "Monkey's Audio, Musepack, and DSF"
)


def bullet(doc: Document, title: str, text: str) -> None:
    """Add a bulleted line with a bold lead-in."""
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


def numbered(doc: Document, steps: tuple[str, ...]) -> None:
    """Add a numbered list."""
    for step in steps:
        doc.add_paragraph(step, style="List Number")


def table(doc: Document, header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]):
    """Add a bordered table with a shaded header row."""
    from docx.oxml.ns import qn

    grid = doc.add_table(rows=1, cols=len(header))
    grid.style = "Table Grid"
    for cell, text in zip(grid.rows[0].cells, header):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
        run.font.size = Pt(9)
        element = cell._tc.get_or_add_tcPr().makeelement(qn("w:shd"), {})
        element.set(qn("w:val"), "clear")
        element.set(qn("w:fill"), "EDE9FE")
        cell._tc.get_or_add_tcPr().append(element)
    for row_values in rows:
        cells = grid.add_row().cells
        for cell, text in zip(cells, row_values):
            cell.text = ""
            run = cell.paragraphs[0].add_run(text)
            run.font.size = Pt(9)
    return grid


doc = Document()
title = doc.add_heading("Spectral Viewer - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
# Version subtitle per plan D15: rendered from the declared suite version, so a
# release bump never leaves a stale label behind (locked by
# tests/test_user_guide_hygiene.py::TestGuideVersionLabels).
subtitle = doc.add_paragraph(
    f"Version {declared_version()} \u2014 {date.today().strftime('%B %Y')}"
)
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle.runs[0].font.size = Pt(9)
subtitle = doc.add_paragraph(
    "Based on the current Spectral Viewer implementation "
    f"(FFT {DEFAULT_N_FFT}, hop {DEFAULT_HOP_LENGTH}, {DEFAULT_CMAP})"
)
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle.runs[0].font.size = Pt(9)
subtitle.runs[0].font.color.rgb = RGBColor(0x6B, 0x72, 0x80)

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Spectral Viewer draws an FFT spectrogram of an audio file: time runs left "
    "to right, frequency bottom to top, and colour is loudness in dB relative "
    "to the loudest point in the picture. It is an inspection tool. It never "
    "retags, re-encodes or moves an audio file; the only files it writes are "
    "PNG images you ask for."
)
doc.add_paragraph(
    "The tool has two front ends over one implementation: this window, and the "
    f"headless `audiosuite spectrogram` command, which renders a whole folder "
    f"and writes one `<name>{OUTPUT_SUFFIX}` per file."
)

doc.add_heading("Quick Start", level=1)
numbered(
    doc,
    (
        "Open Spectral_Viewer.pyw.",
        "Type or browse to a folder (or a single audio file).",
        "Click Scan to list the folder's audio files.",
        "The first file renders immediately; pick any other file in the list.",
        "Adjust the time window, frequency ceiling, colour range or FFT size "
        "and click Render.",
        "Use the toolbar to zoom or pan, then Export PNG to save the view.",
    ),
)

doc.add_heading("What You Are Looking At", level=1)
bullet(
    doc,
    "Time axis: ",
    "seconds from the start of the file. A selected window keeps the real "
    "position, so a window starting at 60 s is labelled from 60 s.",
)
bullet(
    doc,
    "Frequency axis: ",
    "Hz, linear, from 0 to Nyquist (half the sample rate) unless a ceiling is "
    "set. Set 20000 to see whether a lossy encoder has cut the top off; set "
    "2000 to inspect bass and vocal fundamentals.",
)
bullet(
    doc,
    "Colour: ",
    "dB relative to the loudest bin in the image, floored at the colour range "
    f"({DEFAULT_DB_RANGE:.0f} dB by default). The status bar also reports the "
    "absolute peak in dBFS, so a quiet master and a hot one are distinguishable "
    "even though both are normalised for display.",
)
bullet(
    doc,
    "Bright bands: ",
    "harmonics and sustained tones. A hard horizontal edge near the top is a "
    "codec low-pass; vertical smears are transients such as drum hits.",
)

doc.add_heading("Settings", level=1)
table(
    doc,
    ("Setting", "Default", "What it does"),
    (
        (
            "Time window (start/end)",
            "0 / 0",
            "Seconds. 0 for end means the whole file, capped at "
            f"{MAX_ANALYSIS_SECONDS} s.",
        ),
        (
            "Max frequency",
            "0",
            "Highest displayed frequency in Hz; 0 keeps the full Nyquist range.",
        ),
        ("Colour range", f"{DEFAULT_DB_RANGE:.0f}", "Floor in dB below the peak."),
        (
            "FFT size",
            str(DEFAULT_N_FFT),
            "Samples per FFT window: larger resolves pitch better, smaller "
            "resolves time better. 256-16384.",
        ),
        (
            "Colour map",
            DEFAULT_CMAP,
            "magma, inferno, viridis, plasma or gray.",
        ),
    ),
)

doc.add_heading("Zoom and Pan", level=1)
doc.add_paragraph(
    "The toolbar under the figure is matplotlib's standard navigation bar: the "
    "crosshair toggles box zoom (drag a rectangle), the arrows pan, the house "
    "restores the full view, and the disk button saves the current view. Zoom "
    "and pan change only what is displayed, not the computed spectrogram, so "
    "they never blur the data or re-decode the file."
)

doc.add_heading("Exporting a PNG", level=1)
bullet(
    doc,
    "Window: ",
    "Export PNG writes the figure exactly as displayed, including any zoom. The "
    "suggested name is the source stem plus "
    f"`{OUTPUT_SUFFIX}`.",
)
bullet(
    doc,
    "Command line: ",
    "`audiosuite spectrogram <path>` writes one image per audio file, either "
    "beside the source or into `--output-dir`.",
)
bullet(
    doc,
    "Dry run: ",
    "`--dry` prints every path it would write and writes nothing, so a Master "
    "Driver Dry Run leaves no images behind.",
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph(
    "The command accepts a file or a directory. A directory is walked "
    "recursively and only supported audio extensions are rendered."
)
table(
    doc,
    ("Flag", "Default", "Meaning"),
    (
        ("--output-dir DIR", "beside source", "Where the PNGs go."),
        ("--n-fft N", str(DEFAULT_N_FFT), "FFT window size in samples."),
        ("--hop-length N", str(DEFAULT_HOP_LENGTH), "Samples between frames."),
        ("--start S", "0", "Window start in seconds."),
        ("--end S", "0", "Window end in seconds; 0 = to the end."),
        ("--max-freq HZ", "0", "Highest displayed frequency; 0 = Nyquist."),
        ("--db-range DB", f"{DEFAULT_DB_RANGE:.0f}", "Colour floor below peak."),
        ("--cmap NAME", DEFAULT_CMAP, "Matplotlib colour map."),
        ("--dry/--live", "live", "--dry lists planned images, writes none."),
        ("--json/--text", "text", "Machine-readable summary."),
    ),
)
doc.add_paragraph(
    "Examples: render one file to a folder, and preview a whole library without "
    "writing anything:"
)
example = doc.add_paragraph()
example_run = example.add_run(
    'audiosuite spectrogram "D:\\Music\\Album" --output-dir "D:\\Spectrograms"\n'
    'audiosuite spectrogram "D:\\Music" --dry'
)
example_run.font.name = "Consolas"
example_run.font.size = Pt(9)

doc.add_heading("Supported Formats", level=1)
doc.add_paragraph(FORMATS + ".")
doc.add_paragraph(
    "Decoding uses the shared analysis loader, so the Sprint 1 containers "
    "(WavPack, Monkey's Audio, Musepack, Speex, DSF) decode through its FFmpeg "
    "fallback. If a file cannot be decoded, that file is reported and the run "
    "continues with the rest."
)

doc.add_heading("Log Files", level=1)
doc.add_paragraph(
    "The window logs to logs/spectral_viewer.log and the suite administrator "
    "log logs/audio_suite.log carries lifecycle lines and warnings. Per-file "
    "failures are shown in the window and written to the tool log."
)

doc.add_heading("Troubleshooting", level=1)
bullet(
    doc,
    "Nothing renders: ",
    "confirm the path exists and contains supported audio; the status bar says "
    "how many files Scan found.",
)
bullet(
    doc,
    '"Window is shorter than the FFT size": ',
    "lower the FFT size or widen the time window; a 2048-sample window needs "
    "about 46 ms at 44.1 kHz.",
)
bullet(
    doc,
    '"Could not decode": ',
    "the file may be corrupt or a codec FFmpeg cannot read. The rest of the "
    "folder still renders.",
)
bullet(
    doc,
    "Detail looks smeared: ",
    "lower the FFT size. Pitch looks imprecise: raise it. There is no single "
    "setting that is best for both.",
)

doc.add_heading("Read-Only Safety", level=1)
doc.add_paragraph(
    "Spectral Viewer opens audio files for reading only. It never writes tags, "
    "never re-encodes, and never deletes or moves a source file. Exporting "
    "writes a PNG; a dry run writes nothing at all."
)

doc.core_properties.title = "Spectral Viewer - User Guide"
doc.core_properties.author = "AudioSuite-Pro"
doc.save(OUTPUT)
print(f"[OK] wrote {OUTPUT.name}")
print("[DONE]")
