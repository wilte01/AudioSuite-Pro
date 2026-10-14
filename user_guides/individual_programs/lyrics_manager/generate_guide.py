"""Generate a fresh Lyrics Manager user guide from the current implementation.

Changed in 1.0.1: the version subtitle now renders the suite version from
``declared_version()`` and the generation month dynamically, instead of the
stale hardcoded ``Version 2.0 — September 2026``.
"""

from datetime import date

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

from audio_suite_shared.project_version import declared_version

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "lyrics_manager\\Lyrics_Manager_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
h = doc.add_heading("Lyrics Manager \u2014 User Guide", level=0)
h.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_paragraph(
    f"Version {declared_version()} \u2014 {date.today().strftime('%B %Y')}"
).alignment = WD_ALIGN_PARAGRAPH.CENTER

# ── Overview ──
doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Lyrics Manager scans a directory of audio files, fetches synced lyrics from "
    "a remote source or a local sidecar file, and embeds them straight into each "
    "file's tags, so lyrics travel with the file to any player or device that "
    "supports them. Files are matched to the lyric source by their artist and "
    'title tags; files whose tags are missing or contain "Unknown" are skipped.'
)
doc.add_paragraph(
    "Lyrics can be synced (timestamped lines, so a player highlights the words in "
    "time with the music) or plain (the fallback, when no synced version is "
    "available). Where the lyrics are stored depends on the file format:"
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("MP3, WAV and AIFF: ").bold = True
p.add_run("synced lyrics embedded as an ID3 SYLT frame; plain lyrics as a USLT frame.")
p = doc.add_paragraph(style="List Bullet")
p.add_run("FLAC, OGG and Opus: ").bold = True
p.add_run(
    "synced lyrics stored in the SYNCEDLYRICS Vorbis comment, plain lyrics in the "
    "LYRICS comment."
)
p = doc.add_paragraph(style="List Bullet")
p.add_run("M4A / MP4: ").bold = True
p.add_run(
    "plain lyrics only, in the \\xa9lyr atom \u2014 these containers have no standard "
    "synced-lyrics field, so the plain fallback is used."
)

# ── Quick Start ──
doc.add_heading("Quick Start", level=1)
for step in (
    "Open Lyrics_Manager.pyw (or click the Lyrics Manager card in the Master "
    "Driver ENRICH tab and Open Lyrics Manager).",
    "Select the music directory.",
    "Leave Dry Run selected for the first pass and click START.",
    "Review the results in the Processing tab and log, then in the Results tab.",
    "Run again in Live Update when the matches are acceptable so lyrics are written.",
):
    doc.add_paragraph(step, style="List Number")

# ── The Window, Explained ──
doc.add_heading("The Lyrics Manager Window", level=1)
doc.add_paragraph(
    "The window has three tabs mirroring the other batch tools in the suite."
)

doc.add_heading("Setup", level=2)
doc.add_paragraph(
    "Setup contains the directory picker, the run mode, and the tool's options. "
    "The last directory and the settings below are saved in the shared suite "
    "configuration and restored next launch."
)
bullet(
    doc,
    "Directory: ",
    "The folder to scan. Audio Suite's supported formats are scanned (MP3, FLAC, "
    "OGG, M4A, Opus, WAV, AIFF and variants).",
)
bullet(
    doc,
    "Provider: ",
    "The lyric source used for every lookup. Two providers are available: lrclib "
    "(default, queries the public LRCLIB API over the network) and sidecar "
    "(reads a local .lrc file next to each audio file \u2014 no network required).",
)
bullet(
    doc,
    "Request timeout: ",
    "Seconds to wait per lookup before the file is counted as an error. The "
    "default is 10.0 seconds.",
)
bullet(
    doc,
    "Skip existing: ",
    "When enabled (default), files that already contain lyrics are skipped, so "
    "re-runs are fast and idempotent. Disable to refresh lyrics.",
)
bullet(
    doc,
    "Plain fallback: ",
    "When enabled (default), files with no synced lyrics available get the plain "
    "unsynced text instead of being skipped.",
)
bullet(
    doc,
    "Parallel: ",
    "Process multiple files concurrently using worker threads (network-bound "
    "lookups benefit, unlike CPU-bound BPM analysis). Off by default.",
)
bullet(
    doc,
    "Workers: ",
    "Maximum number of concurrent files when Parallel is enabled. The default is 4.",
)
bullet(
    doc,
    "Mode: ",
    "Dry Run or Live Update. Auto Start / Auto End and Clear Logs control the "
    "batch lifecycle exactly as in the other batch tools.",
)

doc.add_heading("Processing", level=2)
doc.add_paragraph(
    "Shows live progress: each file is reported as it is looked up and written, "
    "with a status label such as [LIKE], [ALREADY], [NO MATCH], [PLAIN] or "
    "[ERROR]. The log keeps the full per-file history, and Live Update writes "
    "participate in the suite's tag-edit undo batch. A status bar shows overall "
    "and per-worker counts while the run is in progress."
)

doc.add_heading("Results", level=2)
doc.add_paragraph(
    "Summarises the run: total files, written, skipped and errors, with the "
    "overall status line and a final summary with duration."
)

# ── How Lookup Works ──
doc.add_heading("How Lookup Works", level=1)
doc.add_paragraph(
    "For each file, Lyrics Manager reads the artist and title tags and asks the "
    "chosen provider for a matching track. A file is skipped when:"
)
for reason in (
    "its format is not supported,",
    'its artist or title is missing or "Unknown" (a lookup would be wrong),',
    "it already contains lyrics and Skip Existing is on,",
    "the provider has no synced lyrics and Plain Fallback is off (no "
    "plain-text-only matches are stored when searching for synced lyrics only).",
):
    doc.add_paragraph(reason, style="List Bullet")
doc.add_paragraph(
    "When a synced match is found, the LRC text is embedded in the format's synced "
    "field. When only plain text is available and Plain Fallback is on, the plain "
    "field is used. Reachability or HTTP errors on a single file are counted as "
    "errors and do not abort the rest of the run."
)
doc.add_paragraph(
    "Existing unsynced LYRICS comments on lossless files are never replaced by a "
    "plain write; the plain LYRICS field is only used by this tool when it is the "
    "fallback target for a file being processed."
)

doc.add_heading("Providers", level=2)
doc.add_paragraph(
    "Lyrics Manager ships two lyric sources. The provider is chosen in the Setup "
    "tab or via the --provider CLI flag."
)
bullet(
    doc,
    "lrclib (default): ",
    "Queries the public LRCLIB API (https://lrclib.net) by artist and title. "
    "Requires an internet connection. Returns synced and plain lyrics when "
    "available. Transient HTTP errors (429, 500, 502, 503) are retried "
    "automatically up to three times.",
)
bullet(
    doc,
    "sidecar: ",
    "Reads a local .lrc file sitting next to the audio file. The sidecar must "
    "have the same filename as the audio file but with a .lrc extension (for "
    "example, Track01.mp3 looks for Track01.lrc in the same directory). No "
    "network access is needed. The .lrc file can contain standard LRC timestamps "
    "[mm:ss.xx] and optional meta tags ([ti:], [ar:], [al:], [by:]).",
)

# ── Dry Run and Live Update ──
doc.add_heading("Dry Run and Live Update", level=1)
bullet(
    doc,
    "Dry Run: ",
    "Fetches lyrics and reports what would be written, with no tag changes.",
)
bullet(
    doc,
    "Live Update: ",
    "Fetches lyrics and writes them with the shared tag writers, reporting [TAGGED].",
)
bullet(
    doc, "Undo: ", "Live tag changes are recorded in the suite's batch undo context."
)

# ── Batch Queue Integration ──
doc.add_heading("Running in a Batch", level=1)
doc.add_paragraph(
    "Lyrics Manager is registered as an enrich tool in the Master Driver, so it "
    "can be selected alongside other tools and run via LAUNCH BATCH, run "
    "concurrently in parallel mode, and appear in each run's queue progress. The "
    "batch runs it after tag-dependent tools so artist/title lookups see "
    "up-to-date metadata."
)

# ── Troubleshooting ──
doc.add_heading("Troubleshooting", level=1)
doc.add_paragraph(
    '"No supported audio files found in directory": '
    "The selected folder contains no MP3/FLAC/OGG/M4A/Opus/WAV/AIFF files. Pick "
    "the folder that holds your music."
)
doc.add_paragraph(
    "Everything is skipped: "
    "Either your files already contain lyrics (turn off Skip Existing), or their "
    'artist/title tags are missing or "Unknown". Fix the artist and title tags '
    "first \u2014 lookups are only as good as the metadata."
)
doc.add_paragraph(
    '"Could not reach provider" / request timeout errors: '
    "The lyric source was unreachable or too slow past the Request timeout. "
    "Check your connection and retry; finished files are skipped on the re-run. "
    "If you prefer to avoid network lookups entirely, switch to the sidecar "
    "provider and place .lrc files alongside your audio files."
)
doc.add_paragraph(
    "Lyrics embed but a player shows nothing: "
    "Some players ignore SYLT frames (especially on MP3) or the \\xa9lyr atom on "
    "mobile apps. Try a player known to support embedded synced lyrics."
)

# ── Note ──
doc.add_heading("A Note For Technical Users", level=1)
doc.add_paragraph(
    "The same fetch-and-embed operation is available from the command line:"
)
doc.add_paragraph(
    "audiosuite lyrics MUSIC_DIR --dry\n"
    "audiosuite lyrics MUSIC_DIR --live --parallel --workers 8\n"
    "audiosuite lyrics MUSIC_DIR --provider sidecar --live\n"
    "audiosuite lyrics MUSIC_DIR --json"
)
doc.add_paragraph(
    "Options mirror the Setup tab: --provider (lrclib or sidecar), "
    "--request-timeout, --skip-existing/--no-skip-existing, "
    "--plain-fallback/--no-plain-fallback, --parallel/--no-parallel and "
    "--workers. Runs record an undo batch so tags can be reverted with the "
    "undo utility."
)

# ── Save ──
doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
