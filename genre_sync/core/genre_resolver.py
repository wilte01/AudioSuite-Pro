"""
genre_resolver.py
Pure genre-selection decision tree for Genre Sync.

Encapsulates the priority rules:
  1. TITLEGENRE always wins if present
  2. Various Artists albums: ARTISTGENRE > ALBUMGENRE
  3. Regular albums:         ALBUMGENRE  > ALBUMARTISTGENRE

No file I/O, no tkinter. Fully unit-testable in isolation.
"""

from typing import Optional

# Unicode whitespace characters not stripped by str.strip()
# (non-breaking space, zero-width space, zero-width non-joiner,
#  zero-width joiner, BOM, ideographic space)
_UNICODE_BLANKS = str.maketrans("", "", "\u00a0\u200b\u200c\u200d\ufeff\u3000")

# ── Resolution result ─────────────────────────────────────────────────────────


class GenreResolution:
    """
    Result of applying the priority rules to one file's tag values.

    Attributes:
        selected_genre:    The genre string to write to TCON, or None.
        selection_reason:  Human-readable label of which field won.
        derived_value:     Value to write to TXXX:GENREDERIVED.
        status:            One of 'resolved' | 'no_genre'
    """

    __slots__ = ("selected_genre", "selection_reason", "derived_value", "status")

    def __init__(
        self,
        selected_genre: Optional[str],
        selection_reason: Optional[str],
        derived_value: Optional[str],
        status: str,
    ) -> None:
        self.selected_genre = selected_genre
        self.selection_reason = selection_reason
        self.derived_value = derived_value
        self.status = status


# ── Core resolver ─────────────────────────────────────────────────────────────


def _has_value(value: Optional[str]) -> bool:
    """Return True if `value` is a non-empty string with non-whitespace content.

    A custom genre tag can be technically present (the TXXX/Vorbis-comment/
    freeform-atom frame exists) yet hold an empty or whitespace-only string,
    e.g. left behind by a tag editor that clears a field without removing it.
    Plain truthiness (`if value:`) treats such a string as present, which
    would resolve and write a blank genre. This guards against that case
    without altering how non-blank values (including ones with incidental
    leading/trailing whitespace) are used.

    Also strips Unicode whitespace characters that Python's built-in
    str.strip() does not handle (non-breaking space, zero-width space,
    ideographic space, etc.) to avoid accepting visually-blank tags that
    tag editors may inject.

    Args:
        value: The raw tag value to check, or None.

    Returns:
        True if value is a string containing at least one non-whitespace
        character.
    """
    return value is not None and value.translate(_UNICODE_BLANKS).strip() != ""


def resolve_genre(
    title_genre: Optional[str],
    artist_genre: Optional[str],
    album_genre: Optional[str],
    album_artist_genre: Optional[str],
    album_artist: Optional[str],
) -> GenreResolution:
    """
    Apply the Genre Sync priority rules and return a GenreResolution.

    Args:
        title_genre:        TXXX:TITLEGENRE value
        artist_genre:       TXXX:ARTISTGENRE value
        album_genre:        TXXX:ALBUMGENRE value
        album_artist_genre: TXXX:ALBUMARTISTGENRE value
        album_artist:       TPE2 (Album Artist) value

    Returns:
        GenreResolution with the winning genre and metadata.
    """
    # Rule 1: Title Genre always takes priority
    if _has_value(title_genre):
        return GenreResolution(
            selected_genre=title_genre,
            selection_reason="TITLE GENRE",
            derived_value="Title",
            status="resolved",
        )

    is_various = (
        album_artist is not None and album_artist.strip().lower() == "various artists"
    )

    if is_various:
        # Rule 2a: Various Artists — Artist Genre preferred, Album Genre fallback
        if _has_value(artist_genre):
            return GenreResolution(
                selected_genre=artist_genre,
                selection_reason="ARTIST GENRE (VA)",
                derived_value="Artist",
                status="resolved",
            )
        if _has_value(album_genre):
            return GenreResolution(
                selected_genre=album_genre,
                selection_reason="ALBUM GENRE (VA)",
                derived_value="Album",
                status="resolved",
            )
    else:
        # Rule 2b: Regular album — Album Genre preferred, Album Artist Genre fallback
        if _has_value(album_genre):
            return GenreResolution(
                selected_genre=album_genre,
                selection_reason="ALBUM GENRE",
                derived_value="Album",
                status="resolved",
            )
        if _has_value(album_artist_genre):
            return GenreResolution(
                selected_genre=album_artist_genre,
                selection_reason="ALBUM ARTIST GENRE",
                derived_value="Album Artist",
                status="resolved",
            )

    # No usable genre field found
    return GenreResolution(
        selected_genre=None,
        selection_reason=None,
        derived_value=None,
        status="no_genre",
    )
