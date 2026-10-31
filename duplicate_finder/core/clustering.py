"""Clustering: turn a pile of fingerprints into duplicate groups.

Two stages, and the split is what makes a real library affordable:

1. **Candidate pairs** — an inverted index of exact sub-fingerprint words finds
   the files that *might* be related, so the library is not compared to itself
   pair by pair.  Two encodings of one recording share almost every word, so an
   exact word at a nearby index is a cheap and very sensitive anchor; a file
   that shares no word with another cannot be its duplicate at any threshold
   this module ships.
2. **Exact distance + union-find** — each candidate pair is measured with
   :func:`~duplicate_finder.core.fingerprint_distance.bit_error_rate`, and the
   pairs at or below the threshold are joined into groups (one connected
   component per recording).

Why union-find rather than "pick the best match per file": three copies of the
same recording at 96, 192 and 320 kbit/s should be one group, and a
best-match-only rule leaves one of them attached to the wrong neighbour.

The keeper is chosen from measured file properties only — see
:attr:`~duplicate_finder.core.models.FingerprintRecord.quality_key` — never from
tags, which are exactly what is unreliable in a duplicate set.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import logging
from itertools import combinations

from .fingerprint_distance import bit_error_rate
from .models import (
    DuplicateGroup,
    DuplicateMember,
    FingerprintRecord,
    ScanSettings,
)

logger = logging.getLogger(__name__)

#: A word shared by more files than this is treated as noise rather than an
#: anchor.  A common word in a big library would otherwise make the inverted
#: index quadratic on its own, and it carries almost no matching information.
_MAX_ANCHOR_FANOUT: int = 64

#: Only every *n*-th word is indexed: enough anchors to find a relation, far
#: fewer entries to hold.  The distance pass does the precise work.
_ANCHOR_STRIDE: int = 4


def _duration_comparable(
    first: FingerprintRecord, second: FingerprintRecord, settings: ScanSettings
) -> bool:
    """Return whether two records' durations agree closely enough to compare.

    Args:
        first: One record.
        second: The other record.
        settings: The run's tolerances.

    Returns:
        True when the durations differ by no more than
        ``settings.duration_tolerance_s``.
    """
    return abs(first.duration - second.duration) <= settings.duration_tolerance_s


def candidate_pairs(
    records: list[FingerprintRecord],
) -> list[tuple[int, int]]:
    """Return index pairs that share an exact sub-fingerprint anchor.

    Args:
        records: Every fingerprinted file, in scan order.

    Returns:
        ``(i, j)`` index pairs with ``i < j``, sorted, de-duplicated.
    """
    index: dict[int, list[tuple[int, int]]] = {}
    for position, record in enumerate(records):
        for word_position in range(0, len(record.words), _ANCHOR_STRIDE):
            index.setdefault(record.words[word_position], []).append(
                (position, word_position)
            )

    found: set[tuple[int, int]] = set()
    for entries in index.values():
        if len(entries) < 2 or len(entries) > _MAX_ANCHOR_FANOUT:
            continue
        pairs = combinations(entries, 2)
        for (left_index, left_pos), (right_index, right_pos) in pairs:
            if left_index == right_index:
                continue
            found.add((min(left_index, right_index), max(left_index, right_index)))
    return sorted(found)


class _UnionFind:
    """Minimal union-find over integer ids, with path compression."""

    def __init__(self, size: int) -> None:
        """Create *size* singleton sets.

        Args:
            size: Number of elements.
        """
        self._parent = list(range(size))

    def find(self, value: int) -> int:
        """Return the representative of *value*'s set."""
        root = value
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[value] != root:
            self._parent[value], value = root, self._parent[value]
        return root

    def union(self, first: int, second: int) -> None:
        """Join the sets containing *first* and *second*."""
        first_root, second_root = self.find(first), self.find(second)
        if first_root != second_root:
            self._parent[second_root] = first_root


def cluster_records(
    records: list[FingerprintRecord], settings: ScanSettings
) -> list[DuplicateGroup]:
    """Group *records* into duplicate sets.

    Args:
        records: Every fingerprinted file.
        settings: Threshold and comparison bounds.

    Returns:
        The groups (two or more files each), largest first, then by keeper path
        so the report is stable between runs.
    """
    if len(records) < 2:
        return []

    union = _UnionFind(len(records))
    matched: set[int] = set()
    for left_index, right_index in candidate_pairs(records):
        left, right = records[left_index], records[right_index]
        if not _duration_comparable(left, right, settings):
            continue
        distance = bit_error_rate(
            left.words,
            right.words,
            max_shift_words=settings.max_shift_words,
            min_overlap_ratio=settings.min_overlap_ratio,
        )
        if distance <= settings.threshold:
            union.union(left_index, right_index)
            matched.update((left_index, right_index))

    components: dict[int, list[int]] = {}
    for index in sorted(matched):
        components.setdefault(union.find(index), []).append(index)

    groups: list[DuplicateGroup] = []
    for members in components.values():
        if len(members) < 2:
            continue
        group_records = [records[index] for index in members]
        keeper = choose_keeper(group_records)
        duplicates = tuple(
            DuplicateMember(
                record=record,
                distance=bit_error_rate(
                    keeper.words,
                    record.words,
                    max_shift_words=settings.max_shift_words,
                    min_overlap_ratio=settings.min_overlap_ratio,
                ),
            )
            for record in sorted(group_records, key=lambda item: item.path)
            if record is not keeper
        )
        groups.append(DuplicateGroup(keeper=keeper, duplicates=duplicates))

    groups.sort(key=lambda group: (-len(group.duplicates), group.keeper.path))
    return groups


def choose_keeper(records: list[FingerprintRecord]) -> FingerprintRecord:
    """Return the copy a run proposes to keep.

    The highest :attr:`FingerprintRecord.quality_key` wins.  Ties go to the
    lexicographically smallest path, by sorting the candidates before taking the
    maximum: ``max`` returns the first maximal element, so two runs on the same
    library quarantine the same files.

    Args:
        records: The group's files, at least one.

    Returns:
        The keeper.

    Raises:
        ValueError: If *records* is empty.
    """
    if not records:
        raise ValueError("choose_keeper needs at least one record")
    ordered = sorted(records, key=lambda item: item.path)
    return max(ordered, key=lambda item: item.quality_key)
