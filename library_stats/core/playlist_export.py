"""playlist_export.py — Playlist, HTML and column-aware CSV export for a scan.

The statistics dashboard already reads every tag a playlist needs; what was
missing was a way to hand that scan to something that *plays* the files.  This
module adds the export surface (functional backlog F-05/F-06):

* :func:`camelot_for_key` maps the key spellings ``key_detector`` writes
  ("C", "Am", "Eb", "G#m") onto the Camelot wheel ("8B", "8A", "5B", "1A"), so a
  DJ can read harmonic-mixing codes without a second tool.
* :func:`export_m3u` writes a playlist a player opens: an ``#EXTM3U`` header,
  one ``#EXTINF`` line and one absolute path per file, in playlist order.
* :func:`export_html` writes a self-contained report page (no external assets).
* :func:`collect_export_rows` is the single reader all three share, so a column
  added in one export cannot drift from another.

**Playlist order** is album-first: ``(album artist or artist, album, track
number, filename)``.  A directory walk's order is filesystem-dependent, and a
playlist whose tracks shuffle inside an album is not one.  A file with no track
number sorts after the numbered ones in its album rather than first, because
"track 0" is not what an untagged file means.

Paths are emitted with forward slashes on every platform.  Windows accepts both
separators, but some players (and every POSIX one) reject a backslash path, and
``Path.as_posix`` is the conversion that makes the choice explicit instead of
inheriting the host's.

Changed in 2.2.0: new - the export surface and Camelot mapping of F-05/F-06.
"""

from __future__ import annotations

import csv
import html
import logging
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)

# ── Camelot wheel ────────────────────────────────────────────────────────────
# The wheel has twelve positions; a major key is the "B" column, its relative
# minor the "A" column.  The number is the pitch class counted from B, which is
# why C major is 8B rather than 1B.
_CAMELOT_MAJOR: dict[str, str] = {
    "B": "1B",
    "F#": "2B",
    "Db": "3B",
    "Ab": "4B",
    "Eb": "5B",
    "Bb": "6B",
    "F": "7B",
    "C": "8B",
    "G": "9B",
    "D": "10B",
    "A": "11B",
    "E": "12B",
}

_CAMELOT_MINOR: dict[str, str] = {
    "Ab": "1A",
    "Eb": "2A",
    "Bb": "3A",
    "F": "4A",
    "C": "5A",
    "G": "6A",
    "D": "7A",
    "A": "8A",
    "E": "9A",
    "B": "10A",
    "F#": "11A",
    "C#": "12A",
}

#: Enharmonic normalisation onto the sharp spelling of each pitch class, plus
#: the theoretical spellings a hand-typed or imported tag can carry.  The
#: detector itself emits ``C, C#, D, Eb, E, F, F#, G, Ab, A, Bb, B`` (major)
#: and ``Cm, C#m, Dm, Ebm, Em, Fm, F#m, Gm, G#m, Am, Bbm, Bm`` (minor); the
#: table accepts both spellings of every pitch class so an externally tagged
#: file is not silently unmapped.
_ROOT_TO_SHARP: dict[str, str] = {
    "C": "C",
    "B#": "C",
    "C#": "C#",
    "Db": "C#",
    "D": "D",
    "D#": "D#",
    "Eb": "D#",
    "E": "E",
    "Fb": "E",
    "E#": "F",
    "F": "F",
    "F#": "F#",
    "Gb": "F#",
    "G": "G",
    "G#": "G#",
    "Ab": "G#",
    "A": "A",
    "A#": "A#",
    "Bb": "A#",
    "B": "B",
    "Cb": "B",
}

#: Sharp pitch class → Camelot major/minor code.  Major and minor are mapped
#: separately (not by one chromatic table): a minor key sits on a different
#: position from its major namesake, and Ebm is 2A while D# major is 5B.
_CAMELOT_BY_PITCH_CLASS: dict[str, tuple[str, str]] = {
    "C": ("8B", "5A"),
    "C#": ("3B", "12A"),
    "D": ("10B", "7A"),
    "D#": ("5B", "2A"),
    "E": ("12B", "9A"),
    "F": ("7B", "4A"),
    "F#": ("2B", "11A"),
    "G": ("9B", "6A"),
    "G#": ("4B", "1A"),
    "A": ("11B", "8A"),
    "A#": ("6B", "3A"),
    "B": ("1B", "10A"),
}


def camelot_for_key(key: str | None) -> str | None:
    """Return the Camelot code for a musical key, or None if it has none.

    Accepts every spelling the suite writes and the two text forms
    ``"C major"``/``"A minor"``::

        camelot_for_key("C")    -> "8B"
        camelot_for_key("Am")   -> "8A"
        camelot_for_key("Eb")   -> "5B"
        camelot_for_key("D#m")  -> "2A"   (enharmonic: D# minor is Eb minor)
        camelot_for_key("")     -> None

    Args:
        key: Key string as stored in the file's tag, or None.

    Returns:
        The Camelot code (e.g. ``"8A"``), or None when the value is absent or
        not a key this table knows — including ``key_detector``'s
        ``UNKNOWN_KEY`` sentinel, which is a deliberate "no key" answer and
        must not become a plausible wheel position.
    """
    if not key:
        return None

    text = key.strip().replace("\u266d", "b").replace("\u266f", "#")
    if not text:
        return None

    mode = "major"
    for suffix in (" major", " minor", " maj", " min"):
        if text.lower().endswith(suffix):
            mode = suffix.strip()
            text = text[: -len(suffix)].strip()
            break
    else:
        # "8A"-style input is already Camelot; leave it alone so an export of
        # an export does not lose the code.
        if len(text) >= 2 and text[-1] in "AB" and text[:-1].isdigit():
            return text
        if len(text) >= 3 and text[-2] in "AB" and text[:-2].isdigit():
            return text[-3:]
        if text.endswith("m") and len(text) > 1:
            mode = "minor"
            text = text[:-1].strip()
        elif text.endswith("M") and len(text) > 1:
            text = text[:-1].strip()

    root = text[:1].upper() + text[1:]
    pitch_class = _ROOT_TO_SHARP.get(root)
    if pitch_class is None:
        return None
    major_code, minor_code = _CAMELOT_BY_PITCH_CLASS[pitch_class]
    return major_code if mode in ("major", "maj") else minor_code


# ── Rows ─────────────────────────────────────────────────────────────────────

#: Every column an export can carry, in the order an unspecified column set
#: uses.  ``camelot`` is derived from ``key``; the rest are read from tags.
EXPORT_COLUMNS: tuple[str, ...] = (
    "path",
    "format",
    "artist",
    "title",
    "album",
    "album_artist",
    "track",
    "disc",
    "year",
    "genre",
    "bpm",
    "key",
    "camelot",
    "mood",
    "tempo_marking",
    "duration",
)

#: The column set used when a caller does not ask for one.  It is the
#: playlist-relevant subset: a spreadsheet wants the identifying fields, not
#: the whole tag payload.  ``camelot``, ``disc``, ``mood``, ``tempo_marking``
#: and ``duration`` are opt-in — asking for one is the only thing that turns it
#: on, so a default export keeps its shape across versions.
DEFAULT_EXPORT_COLUMNS: tuple[str, ...] = (
    "path",
    "format",
    "artist",
    "title",
    "album",
    "album_artist",
    "track",
    "year",
    "genre",
    "bpm",
    "key",
)


@dataclass(frozen=True)
class ExportRow:
    """One file's export values.

    Attributes:
        path: Absolute path to the audio file.
        format: Lower-case extension, e.g. ``".flac"``.
        artist: Track artist from the tags, or None.
        title: Track title from the tags, or None.
        album: Album name from the tags, or None.
        album_artist: Album artist from the tags, or None.
        track: Track-number string as stored (``"3"`` or ``"3/12"``).
        disc: Disc-number string as stored.
        year: Four-digit year as a string, or None.
        genre: Genre string, or None.
        bpm: Integer BPM, or None.
        key: Key string as stored, or None.
        mood: Mood string, or None.
        tempo_marking: Tempo marking, or None.
        duration_secs: Playing time in seconds, or None.
    """

    path: str
    format: str
    artist: str | None = None
    title: str | None = None
    album: str | None = None
    album_artist: str | None = None
    track: str | None = None
    disc: str | None = None
    year: str | None = None
    genre: str | None = None
    bpm: int | None = None
    key: str | None = None
    mood: str | None = None
    tempo_marking: str | None = None
    duration_secs: float | None = None

    @property
    def camelot(self) -> str | None:
        """Return this row's Camelot code, or None when its key has none."""
        return camelot_for_key(self.key)

    @property
    def display_name(self) -> str:
        """Return the ``Artist - Title`` label a playlist entry shows.

        Falls back to whichever half exists, then to the file's stem, so an
        untagged file still has a name in the player rather than a blank line.
        """
        artist = (self.artist or "").strip()
        title = (self.title or "").strip()
        if artist and title:
            return f"{artist} - {title}"
        if title:
            return title
        if artist:
            return artist
        return Path(self.path).stem

    def value(self, column: str) -> str:
        """Return one column as text, with an absent value as ``""``.

        Args:
            column: A member of :data:`EXPORT_COLUMNS`.

        Returns:
            The column's value rendered for CSV/HTML output.

        Raises:
            KeyError: If *column* is not an export column.
        """
        if column == "camelot":
            return self.camelot or ""
        if column == "duration":
            if self.duration_secs is None:
                return ""
            return f"{self.duration_secs:.1f}"
        if column == "bpm":
            return "" if self.bpm is None else str(self.bpm)
        if column not in EXPORT_COLUMNS:
            raise KeyError(f"unknown export column: {column}")
        raw = getattr(self, column)
        return "" if raw is None else str(raw)


def resolve_columns(
    requested: Iterable[str] | None, *, camelot: bool = False
) -> tuple[str, ...]:
    """Return the column set an export should write, validated.

    Args:
        requested: Column names from ``--export-columns``, or None for
            :data:`DEFAULT_EXPORT_COLUMNS`.
        camelot: Add the ``camelot`` column when it is not already present.

    Returns:
        The ordered column tuple.

    Raises:
        ValueError: If a requested name is not an export column.  Silently
            dropping a misspelt column would produce a file missing the data
            the caller asked for.
    """
    columns = list(DEFAULT_EXPORT_COLUMNS if requested is None else requested)
    unknown = [name for name in columns if name not in EXPORT_COLUMNS]
    if unknown:
        raise ValueError(
            f"unknown export column(s): {', '.join(sorted(unknown))}; "
            f"expected one of {', '.join(EXPORT_COLUMNS)}"
        )
    if camelot and "camelot" not in columns:
        columns.append("camelot")
    return tuple(columns)


#: The reader's absent-value default.  ``read_artist_album`` returns
#: ``("Unknown", "Unknown")`` on failure, which the aggregates treat as a
#: bucket; an export column must not claim a tag the file does not carry.
_UNKNOWN_SENTINEL = "Unknown"


def _tag_or_none(value: str | None) -> str | None:
    """Return a tag value with the reader's ``"Unknown"`` default as absent.

    Args:
        value: A value as the tag reader returns it.

    Returns:
        The stripped value, or None when it is empty or the reader's sentinel.
    """
    if value is None:
        return None
    text = value.strip()
    if not text or text == _UNKNOWN_SENTINEL:
        return None
    return text


def _track_position(row: ExportRow) -> int:
    """Return a row's numeric track position for playlist ordering.

    An untagged file sorts after its numbered siblings: a missing number is
    "unknown", not "track zero".
    """
    text = (row.track or "").split("/", 1)[0].strip()
    return int(text) if text.isdigit() else 10**6


def _order_key(row: ExportRow) -> tuple[str, str, int, str]:
    """Return the sort key that puts a library into album order."""
    album_artist = (row.album_artist or row.artist or "").casefold()
    album = (row.album or "").casefold()
    return (album_artist, album, _track_position(row), Path(row.path).name.casefold())


def collect_export_rows(scan_path: str) -> list[ExportRow]:
    """Read every supported file under *scan_path* into album-ordered rows.

    A file whose tags cannot be read is skipped with a debug log rather than
    aborting the export: one corrupt file must not cost the user their
    playlist.  The scan already skips unreadable files the same way.

    Args:
        scan_path: Root directory to walk recursively.

    Returns:
        The rows, sorted by :func:`_order_key`.

    Raises:
        FileNotFoundError: If *scan_path* is not a directory.
    """
    from library_stats.core.file_processor import _read_file_tags

    if not os.path.isdir(scan_path):
        raise FileNotFoundError(f"Scan path does not exist: {scan_path}")

    rows: list[ExportRow] = []
    for root, _dirs, files in os.walk(scan_path):
        for name in sorted(files):
            if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                continue
            full = os.path.join(root, name)
            try:
                tags = _read_file_tags(full, export_fields=True)
            except Exception:
                logger.debug(
                    "Skipping unreadable file during export: %s", full, exc_info=True
                )
                continue
            raw_artist, raw_album = tags.artist_album or (None, None)
            rows.append(
                ExportRow(
                    path=os.path.abspath(full),
                    format=os.path.splitext(name)[1].lower(),
                    artist=_tag_or_none(raw_artist),
                    title=_tag_or_none(tags.title),
                    album=_tag_or_none(raw_album),
                    album_artist=_tag_or_none(tags.album_artist),
                    track=tags.track,
                    disc=tags.disc,
                    year=str(tags.year) if tags.year is not None else None,
                    genre=tags.genre,
                    bpm=tags.bpm,
                    key=tags.key,
                    mood=tags.mood,
                    tempo_marking=tags.tempo_marking,
                    duration_secs=tags.duration_secs,
                )
            )
    rows.sort(key=_order_key)
    return rows


def playlist_path(path: str) -> str:
    """Return *path* as an absolute, forward-slash playlist entry.

    Args:
        path: Filesystem path to the audio file.

    Returns:
        Absolute path with ``/`` separators, so a playlist written on Windows
        is still readable by a POSIX player and vice versa.
    """
    return Path(os.path.abspath(path)).as_posix()


def export_m3u(scan_path: str, output_path: str) -> int:
    """Write an extended M3U playlist for every audio file under *scan_path*.

    Layout per file::

        #EXTINF:215,Artist - Title
        D:/Music/Album/01 Track.flac

    An unknown duration is written as ``-1``, which is the extension's own
    "not known" value — a plausible-looking zero would make players show a
    zero-length track.

    Args:
        scan_path: Root directory to walk recursively.
        output_path: Destination ``.m3u`` path (UTF-8).

    Returns:
        The number of entries written.

    Raises:
        FileNotFoundError: If *scan_path* is not a directory.
        OSError: If the playlist cannot be written.
    """
    rows = collect_export_rows(scan_path)
    lines = ["#EXTM3U"]
    for row in rows:
        seconds = -1 if row.duration_secs is None else int(round(row.duration_secs))
        lines.append(f"#EXTINF:{seconds},{row.display_name}")
        lines.append(playlist_path(row.path))
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def _html_page(rows: Sequence[ExportRow], columns: Sequence[str], heading: str) -> str:
    """Render the self-contained HTML document for *rows*.

    Args:
        rows: Export rows in playlist order.
        columns: Column names to render.
        heading: Page heading text.

    Returns:
        A complete HTML document with inline styling and no external assets.
    """
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
    body: list[str] = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(row.value(column))}</td>" for column in columns
        )
        body.append(f"<tr>{cells}</tr>")
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(heading)}</title>\n"
        "<style>\n"
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#222}\n"
        "table{border-collapse:collapse;width:100%}\n"
        "th,td{border:1px solid #ccc;padding:0.25rem 0.5rem;text-align:left}\n"
        "th{background:#f0f0f0}\n"
        "tr:nth-child(even){background:#fafafa}\n"
        "</style>\n</head>\n<body>\n"
        f"<h1>{html.escape(heading)}</h1>\n"
        f"<p>{len(rows)} file(s)</p>\n"
        "<table>\n"
        f"<thead><tr>{headers}</tr></thead>\n"
        "<tbody>\n" + "\n".join(body) + "\n</tbody>\n</table>\n"
        "</body>\n</html>\n"
    )


def export_html(
    scan_path: str,
    output_path: str,
    *,
    columns: Sequence[str] | None = None,
    camelot: bool = False,
    heading: str = "Library export",
) -> int:
    """Write a self-contained HTML report of the library under *scan_path*.

    Args:
        scan_path: Root directory to walk recursively.
        output_path: Destination ``.html`` path (UTF-8).
        columns: Column names to render; None uses
            :data:`DEFAULT_EXPORT_COLUMNS`.
        camelot: Add the ``camelot`` column.
        heading: Page heading and ``<title>`` text.

    Returns:
        The number of rows written.

    Raises:
        FileNotFoundError: If *scan_path* is not a directory.
        ValueError: If a requested column is unknown.
        OSError: If the page cannot be written.
    """
    resolved = resolve_columns(columns, camelot=camelot)
    rows = collect_export_rows(scan_path)
    document = _html_page(rows, resolved, heading)
    Path(output_path).write_text(document, encoding="utf-8")
    return len(rows)


def write_csv_rows(
    rows: Sequence[ExportRow], output_path: str, columns: Sequence[str]
) -> None:
    """Write *rows* to *output_path* as CSV with exactly *columns*.

    Args:
        rows: Export rows in playlist order.
        output_path: Destination CSV path (UTF-8, ``newline=""`` per the csv
            module's own requirement).
        columns: Column names to write, in order.
    """
    with open(output_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.value(column) for column in columns})
