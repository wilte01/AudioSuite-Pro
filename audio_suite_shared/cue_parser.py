"""
cue_parser.py — Parse CUE sheet files into a typed, immutable model.

Scope (Sprint 3, phase 3.3): PERFORMER, TITLE, FILE, TRACK, INDEX, REM,
PREGAP and POSTGAP are fully supported.  CATALOG, SONGWRITER, ISRC and FLAGS
are also parsed so a real-world sheet never silently drops metadata.  Any
unknown or malformed command raises :class:`CueParseError`.

The parser is strict by design: structure errors (an INDEX outside a TRACK,
a TRACK outside a FILE) and out-of-range timestamps are raised rather than
tolerated, so downstream tools (splitters, generators) can rely on the model
being well-formed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_suite_shared.exceptions import AudioSuiteError

logger = logging.getLogger(__name__)

_MSF_RE = re.compile(r"^(\d{1,3}):(\d{1,2}):(\d{1,2})$", re.ASCII)

# Maximum minutes accepted for an MM:SS:FF timestamp (~10 h of audio).
_MAX_MINUTES = 599


class CueParseError(AudioSuiteError):
    """Raised when a CUE sheet is malformed or uses an unknown command."""


@dataclass(frozen=True)
class CueIndex:
    """A single INDEX MM:SS:FF line inside a track."""

    number: int
    mm: int
    ss: int
    ff: int

    def __post_init__(self) -> None:
        if not 0 <= self.number <= 99:
            raise CueParseError(f"INDEX number must be 00-99, got {self.number}")
        if not 0 <= self.ss <= 59:
            raise CueParseError(f"INDEX seconds must be 00-59, got {self.ss}")
        if not 0 <= self.ff <= 74:
            raise CueParseError(f"INDEX frames must be 00-74, got {self.ff}")

    @property
    def frames(self) -> int:
        """Position as a count of CD frames (75 per second)."""
        return self.mm * 4500 + self.ss * 75 + self.ff

    @property
    def start_ms(self) -> int:
        """Position as a millisecond offset (rounded to the nearest frame)."""
        return int(round(self.frames * 1000 / 75))


@dataclass(frozen=True)
class CueTrack:
    """One TRACK block inside a FILE entry."""

    number: int
    mode: str = "AUDIO"
    title: str | None = None
    performer: str | None = None
    songwriter: str | None = None
    isrc: str | None = None
    rem: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    pregap: str | None = None
    postgap: str | None = None
    indexes: tuple[CueIndex, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 99:
            raise CueParseError(f"TRACK number must be 01-99, got {self.number}")

    @property
    def index01(self) -> CueIndex | None:
        """The INDEX 01 marker — the definitive track start, or None."""
        for index in self.indexes:
            if index.number == 1:
                return index
        return None


@dataclass(frozen=True)
class CueFileEntry:
    """One FILE block; its tracks all reference the same audio image."""

    filename: str
    file_type: str | None = None
    title: str | None = None
    performer: str | None = None
    rem: tuple[str, ...] = ()
    tracks: tuple[CueTrack, ...] = ()


@dataclass(frozen=True)
class CueSheet:
    """The full parsed sheet: album-level metadata plus FILE/Track entries."""

    catalog: str | None = None
    performer: str | None = None
    title: str | None = None
    rem: tuple[str, ...] = ()
    files: tuple[CueFileEntry, ...] = ()


def _tokenize(line: str) -> list[str]:
    """Split a CUE line into tokens honouring double-quoted strings.

    A doubled double-quote inside a quoted token is an escaped literal quote
    (the CUE convention).  An unterminated quote raises :class:`CueParseError`.
    """
    tokens: list[str] = []
    buf: list[str] = []
    pos = 0
    n = len(line)
    in_quotes = False
    while pos < n:
        ch = line[pos]
        if in_quotes:
            if ch == '"':
                if pos + 1 < n and line[pos + 1] == '"':
                    buf.append('"')
                    pos += 2
                    continue
                in_quotes = False
            else:
                buf.append(ch)
        elif ch == '"':
            if buf:
                tokens.append("".join(buf))
                buf = []
            in_quotes = True
        elif ch.isspace():
            if buf:
                tokens.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
        pos += 1
    if in_quotes:
        raise CueParseError("Unterminated quoted string")
    if buf:
        tokens.append("".join(buf))
    return tokens


def _parse_msf(token: str, lineno: int, command: str) -> tuple[int, int, int]:
    """Validate and return an MM:SS:FF token as (minutes, seconds, frames)."""
    match = _MSF_RE.match(token)
    if match is None:
        raise CueParseError(f"Line {lineno}: {command} expects MM:SS:FF, got {token!r}")
    mm, ss, ff = (int(group) for group in match.groups())
    if mm > _MAX_MINUTES:
        raise CueParseError(
            f"Line {lineno}: minutes out of range in {token!r} (max {_MAX_MINUTES})"
        )
    if ss > 59:
        raise CueParseError(f"Line {lineno}: seconds out of range in {token!r}")
    if ff > 74:
        raise CueParseError(f"Line {lineno}: frames out of range in {token!r}")
    return mm, ss, ff


class _CueParser:
    """Single-pass parser accumulating immutable dataclasses from raw lines."""

    def __init__(self) -> None:
        self._rem: list[str] = []
        self._performer: str | None = None
        self._title: str | None = None
        self._catalog: str | None = None
        self._files: list[dict[str, Any]] = []
        self._file: dict[str, Any] | None = None
        self._track: dict[str, Any] | None = None

    # ── Line dispatch ────────────────────────────────────────────────────────

    def parse_line(self, lineno: int, line: str) -> None:
        tokens = _tokenize(line)
        if not tokens:
            return
        command = tokens[0].upper()
        handler = (
            getattr(self, _COMMANDS[command], None) if command in _COMMANDS else None
        )
        if handler is None:
            raise CueParseError(f"Line {lineno}: unknown CUE command {command!r}")
        handler(lineno, tokens[1:])

    def build(self) -> CueSheet:
        if self._file is not None:
            self._files.append(self._file)
            self._file = None
        return CueSheet(
            catalog=self._catalog,
            performer=self._performer,
            title=self._title,
            rem=tuple(self._rem),
            files=tuple(self._build_files()),
        )

    # ── Scaffolding helpers ──────────────────────────────────────────────────

    @staticmethod
    def _require_args(
        lineno: int,
        command: str,
        args: list[str],
        *,
        min_count: int | None = None,
        exact_count: int | None = None,
    ) -> None:
        if exact_count is not None and len(args) != exact_count:
            raise CueParseError(
                f"Line {lineno}: {command} expects {exact_count} "
                f"argument(s), got {len(args)}"
            )
        if min_count is not None and len(args) < min_count:
            raise CueParseError(
                f"Line {lineno}: {command} expects at least {min_count} "
                f"argument(s), got {len(args)}"
            )

    def _require_track(self, lineno: int, command: str) -> None:
        if self._track is None:
            raise CueParseError(f"Line {lineno}: {command} must appear inside a TRACK")

    def _require_file(self, lineno: int, command: str) -> None:
        if self._file is None:
            raise CueParseError(f"Line {lineno}: {command} must appear inside a FILE")

    def _target_rem(self) -> list[str]:
        if self._track is not None:
            track_rem: list[str] = self._track["rem"]
            return track_rem
        if self._file is not None:
            file_rem: list[str] = self._file["rem"]
            return file_rem
        return self._rem

    def _build_files(self) -> list[CueFileEntry]:
        result: list[CueFileEntry] = []
        for f in self._files:
            tracks = tuple(
                CueTrack(
                    number=t["number"],
                    mode=t["mode"],
                    title=t["title"],
                    performer=t["performer"],
                    songwriter=t["songwriter"],
                    isrc=t["isrc"],
                    rem=tuple(t["rem"]),
                    flags=tuple(t["flags"]),
                    pregap=t["pregap"],
                    postgap=t["postgap"],
                    indexes=tuple(t["indexes"]),
                )
                for t in f["tracks"]
            )
            result.append(
                CueFileEntry(
                    filename=f["filename"],
                    file_type=f["file_type"],
                    title=f["title"],
                    performer=f["performer"],
                    rem=tuple(f["rem"]),
                    tracks=tracks,
                )
            )
        return result

    # ── Command handlers ─────────────────────────────────────────────────────

    def _cmd_rem(self, lineno: int, args: list[str]) -> None:
        self._require_args(lineno, "REM", args, min_count=1)
        self._target_rem().extend(args)

    def _cmd_performer(self, lineno: int, args: list[str]) -> None:
        self._require_args(lineno, "PERFORMER", args, min_count=1)
        value = " ".join(args)
        if self._track is not None:
            self._track["performer"] = value
        elif self._file is not None:
            self._file["performer"] = value
        else:
            self._performer = value

    def _cmd_title(self, lineno: int, args: list[str]) -> None:
        self._require_args(lineno, "TITLE", args, min_count=1)
        value = " ".join(args)
        if self._track is not None:
            self._track["title"] = value
        elif self._file is not None:
            self._file["title"] = value
        else:
            self._title = value

    def _cmd_songwriter(self, lineno: int, args: list[str]) -> None:
        self._require_track(lineno, "SONGWRITER")
        self._require_args(lineno, "SONGWRITER", args, min_count=1)
        assert self._track is not None
        self._track["songwriter"] = " ".join(args)

    def _cmd_catalog(self, lineno: int, args: list[str]) -> None:
        if self._file is not None or self._track is not None:
            raise CueParseError(
                f"Line {lineno}: CATALOG must appear before the first FILE"
            )
        self._require_args(lineno, "CATALOG", args, exact_count=1)
        self._catalog = args[0]

    def _cmd_file(self, lineno: int, args: list[str]) -> None:
        self._require_args(lineno, "FILE", args, min_count=1)
        if self._file is not None:
            self._files.append(self._file)
        self._file = {
            "filename": args[0],
            "file_type": " ".join(args[1:]).upper() or None,
            "title": None,
            "performer": None,
            "rem": [],
            "tracks": [],
        }
        self._track = None

    def _cmd_track(self, lineno: int, args: list[str]) -> None:
        self._require_file(lineno, "TRACK")
        self._require_args(lineno, "TRACK", args, exact_count=2)
        number_token = args[0]
        if not number_token.isdigit():
            raise CueParseError(
                f"Line {lineno}: TRACK expects a track number, got {number_token!r}"
            )
        assert self._file is not None
        self._track = {
            "number": int(number_token),
            "mode": args[1].upper(),
            "title": None,
            "performer": None,
            "songwriter": None,
            "isrc": None,
            "rem": [],
            "flags": [],
            "pregap": None,
            "postgap": None,
            "indexes": [],
        }
        self._file["tracks"].append(self._track)

    def _cmd_index(self, lineno: int, args: list[str]) -> None:
        self._require_track(lineno, "INDEX")
        self._require_args(lineno, "INDEX", args, exact_count=2)
        number_token = args[0]
        if not number_token.isdigit():
            raise CueParseError(
                f"Line {lineno}: INDEX expects an index number, got {number_token!r}"
            )
        mm, ss, ff = _parse_msf(args[1], lineno, "INDEX")
        assert self._track is not None
        self._track["indexes"].append(CueIndex(int(number_token), mm, ss, ff))

    def _cmd_pregap(self, lineno: int, args: list[str]) -> None:
        self._require_track(lineno, "PREGAP")
        self._require_args(lineno, "PREGAP", args, exact_count=1)
        _parse_msf(args[0], lineno, "PREGAP")
        assert self._track is not None
        self._track["pregap"] = args[0]

    def _cmd_postgap(self, lineno: int, args: list[str]) -> None:
        self._require_track(lineno, "POSTGAP")
        self._require_args(lineno, "POSTGAP", args, exact_count=1)
        _parse_msf(args[0], lineno, "POSTGAP")
        assert self._track is not None
        self._track["postgap"] = args[0]

    def _cmd_isrc(self, lineno: int, args: list[str]) -> None:
        self._require_track(lineno, "ISRC")
        self._require_args(lineno, "ISRC", args, exact_count=1)
        assert self._track is not None
        self._track["isrc"] = args[0]

    def _cmd_flags(self, lineno: int, args: list[str]) -> None:
        self._require_track(lineno, "FLAGS")
        self._require_args(lineno, "FLAGS", args, min_count=1)
        assert self._track is not None
        self._track["flags"].extend(args)


# Command name → handler method name.  Parser-line dispatch via getattr.
_COMMANDS: dict[str, str] = {
    "REM": "_cmd_rem",
    "PERFORMER": "_cmd_performer",
    "TITLE": "_cmd_title",
    "SONGWRITER": "_cmd_songwriter",
    "CATALOG": "_cmd_catalog",
    "FILE": "_cmd_file",
    "TRACK": "_cmd_track",
    "INDEX": "_cmd_index",
    "PREGAP": "_cmd_pregap",
    "POSTGAP": "_cmd_postgap",
    "ISRC": "_cmd_isrc",
    "FLAGS": "_cmd_flags",
}


def parse_cue(text: str) -> CueSheet:
    """Parse CUE sheet *text* into an immutable :class:`CueSheet`.

    Args:
        text: The raw CUE sheet content.

    Returns:
        A fully-populated ``CueSheet``.

    Raises:
        CueParseError: If the sheet is malformed or uses an unknown command.
    """
    parser = _CueParser()
    for lineno, raw in enumerate(text.splitlines(), start=1):
        parser.parse_line(lineno, raw)
    return parser.build()


def parse_cue_file(path: str | Path) -> CueSheet:
    """Parse the CUE sheet at *path* (UTF-8, an optional BOM is tolerated).

    Args:
        path: Path to the ``.cue`` file on disk.

    Returns:
        A fully-populated ``CueSheet``.

    Raises:
        CueParseError: If the sheet is malformed or uses an unknown command.
        OSError:       If the file cannot be read.
    """
    with open(path, "r", encoding="utf-8-sig") as fh:
        return parse_cue(fh.read())
