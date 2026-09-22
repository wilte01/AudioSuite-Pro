"""
tempo_schemes.py
All built-in tempo naming schemes and the BPM → marking lookup function.

Pure module — no tkinter, no I/O.
Each scheme is a list of (min_bpm, max_bpm, marking) tuples.
Ranges are inclusive on both ends. max_bpm is ``None`` for the open-ended
top band of a scheme — there is no upper limit on BPM, so this is an
explicit "unbounded" marker rather than a large numeric placeholder.
"""

MarkingList = list[tuple[int, int | None, str]]

# ── Scheme definitions ────────────────────────────────────────────────────────

TEMPO_SCHEMES: dict[str, MarkingList] = {
    "Italian": [
        (0, 23, "Larghissimo"),
        (24, 40, "Largo"),
        (41, 66, "Larghetto"),
        (67, 76, "Adagio"),
        (77, 98, "Andante"),
        (99, 110, "Allegretto"),
        (111, 120, "Moderato"),
        (121, 168, "Allegro"),
        (169, 177, "Vivace"),
        (178, 200, "Presto"),
        (201, None, "Prestissimo"),
    ],
    "English": [
        (0, 40, "Very Slow"),
        (41, 76, "Slow"),
        (77, 108, "Moderate"),
        (109, 140, "Fast"),
        (141, 177, "Very Fast"),
        (178, None, "Extremely Fast"),
    ],
    "Descriptive": [
        (0, 60, "Relaxed"),
        (61, 90, "Easy Pace"),
        (91, 120, "Moderate Energy"),
        (121, 140, "Energetic"),
        (141, 160, "High Energy"),
        (161, 180, "Intense"),
        (181, None, "Frantic"),
    ],
    "Numeric": [
        (0, 60, "0-60 BPM"),
        (61, 80, "61-80 BPM"),
        (81, 100, "81-100 BPM"),
        (101, 120, "101-120 BPM"),
        (121, 140, "121-140 BPM"),
        (141, 160, "141-160 BPM"),
        (161, 180, "161-180 BPM"),
        (181, 200, "181-200 BPM"),
        (201, None, "200+ BPM"),
    ],
    "Simplified": [
        (0, 90, "Slow"),
        (91, 120, "Medium"),
        (121, 150, "Fast"),
        (151, None, "Very Fast"),
    ],
    "Dance": [
        (0, 90, "Downtempo"),
        (91, 110, "Hip Hop"),
        (111, 130, "House"),
        (131, 145, "Techno"),
        (146, 170, "Drum and Bass"),
        (171, None, "Hardcore"),
    ],
    "Running": [
        (0, 120, "Walking Pace"),
        (121, 140, "Easy Run"),
        (141, 160, "Moderate Run"),
        (161, 180, "Fast Run"),
        (181, None, "Sprint"),
    ],
}

DEFAULT_SCHEME = "Italian"


# ── Lookup ────────────────────────────────────────────────────────────────────


def get_tempo_marking(bpm: int, markings: MarkingList) -> str:
    """
    Return the tempo marking string for a given BPM value.

    Args:
        bpm:      Integer BPM value (must be > 0).
        markings: The active scheme's marking list.

    Returns:
        The matching marking string, or 'Unknown' if no range matches.
        Any BPM at or above the highest band's min_bpm resolves to that
        band's marking — there is no implicit upper cutoff.
    """
    if bpm <= 0:
        return "Unknown"
    for min_bpm, max_bpm, marking in markings:
        if max_bpm is None:
            if bpm >= min_bpm:
                return marking
        elif min_bpm <= bpm <= max_bpm:
            return marking
    return "Unknown"
