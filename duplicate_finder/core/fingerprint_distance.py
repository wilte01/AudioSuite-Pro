"""Fingerprint distance: how far apart two Chromaprint fingerprints are.

Chromaprint's sub-fingerprints are 32-bit words, one every ~0.12 s of audio, and
two encodings of the same recording differ in only a handful of bits.  The
distance used here is therefore the **bit-error rate**: the fraction of the
compared bits that differ, after aligning the two sequences.

Alignment
---------
The lowest-error shift is searched within :data:`~duplicate_finder.core.models.
DEFAULT_MAX_SHIFT_WORDS` words.  Encoder delay puts the same audio at slightly
different indices (an MP3 gains a few tens of milliseconds of padding), so an
unaligned comparison would report a large distance for identical recordings.
The search is bounded rather than open-ended: a shift wider than a few seconds
is a different edit, not an encoding artefact.

A shift only counts when the two sequences overlap enough to be comparable —
``min_overlap_ratio`` of the *longer* fingerprint.  A 30 s clip that is entirely
contained in a 4-minute track is not the same file, and honouring the overlap
rule is what makes that a distance of ``1.0`` instead of a small one.

Accepted input
--------------
``fpcalc -raw`` prints the words as comma-separated decimal integers, which is
what the tool asks for.  fpcalc's default output is URL-safe base64 of
Chromaprint's *compressed* encoding; that encoding is variable-length, so it is
only decoded here when its payload is a whole number of 32-bit words.  A
compressed payload that is not word-aligned raises
:class:`FingerprintFormatError` instead of being compared as garbage.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import numpy as np
import numpy.typing as npt

from .models import DEFAULT_MAX_SHIFT_WORDS, DEFAULT_MIN_OVERLAP_RATIO

logger = logging.getLogger(__name__)


#: The suite's exception type for a fingerprint this module cannot compare.
class FingerprintFormatError(ValueError):
    """Raised when a fingerprint string cannot be decoded into words."""


#: 8-bit population counts, indexed by byte value.  A 256-entry table means a
#: 32-bit word costs four indexed sums and no per-element Python loop, which is
#: what keeps a library-sized comparison affordable without numpy 2's
#: ``bitwise_count`` (the floor leg resolves numpy 1.26.4, which lacks it).
_POP8: npt.NDArray[np.uint8] = np.array(
    [bin(value).count("1") for value in range(256)], dtype=np.uint8
)


def decode_words(text: str) -> tuple[int, ...]:
    """Decode a fingerprint string into its ``uint32`` words.

    Args:
        text: A fingerprint as ``fpcalc -raw`` prints it (comma-separated
            decimal integers) or as fpcalc prints it by default (URL-safe
            base64, padding optional).

    Returns:
        The sub-fingerprint words, in order.

    Raises:
        FingerprintFormatError: If the text is neither form, or is a base64
            payload whose length is not a whole number of 32-bit words.
    """
    stripped = text.strip()
    if not stripped:
        raise FingerprintFormatError("empty fingerprint")
    if "," in stripped:
        try:
            return tuple(int(part) for part in stripped.split(",") if part.strip())
        except ValueError as exc:
            raise FingerprintFormatError(
                f"comma-separated fingerprint has a non-numeric word: {exc}"
            ) from exc
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        # ``validate=True`` is what makes a non-alphabet character an error.
        # The default discards it, so ``"!!!!"`` would decode to no bytes at
        # all and be answered with an empty word array instead of a refusal.
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise FingerprintFormatError(f"fingerprint is not decodable: {exc}") from exc
    if len(raw) % 4:
        raise FingerprintFormatError(
            "fingerprint is a compressed Chromaprint payload, not a word array; "
            "record it with 'fpcalc -raw' to compare it locally"
        )
    words = np.frombuffer(raw, dtype="<u4")
    return tuple(int(word) for word in words)


def _as_words(values: tuple[int, ...]) -> npt.NDArray[np.uint32]:
    """Return *values* as a ``uint32`` array.

    Args:
        values: Sub-fingerprint words.

    Returns:
        The same words as a contiguous ``uint32`` array.
    """
    array: npt.NDArray[np.uint32] = np.asarray(values, dtype=np.uint32)
    return array


def _popcount(array: npt.NDArray[np.uint32]) -> int:
    """Return the total number of set bits in *array*.

    Args:
        array: A ``uint32`` array.

    Returns:
        The summed population count.
    """
    low = _POP8[(array & np.uint32(0xFF)).astype(np.uint8)]
    byte1 = _POP8[((array >> np.uint32(8)) & np.uint32(0xFF)).astype(np.uint8)]
    byte2 = _POP8[((array >> np.uint32(16)) & np.uint32(0xFF)).astype(np.uint8)]
    byte3 = _POP8[(array >> np.uint32(24)).astype(np.uint8)]
    total: int = int(low.sum()) + int(byte1.sum()) + int(byte2.sum()) + int(byte3.sum())
    return total


def bit_error_rate(
    first: tuple[int, ...],
    second: tuple[int, ...],
    *,
    max_shift_words: int = DEFAULT_MAX_SHIFT_WORDS,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
) -> float:
    """Return the lowest bit-error rate over the allowed alignments.

    Args:
        first: One fingerprint's words.
        second: The other fingerprint's words.
        max_shift_words: How far to slide one sequence against the other, in
            words, in each direction.
        min_overlap_ratio: Fraction of the longer fingerprint the aligned
            overlap must cover for the shift to be considered.

    Returns:
        The bit-error rate in ``0.0-1.0``: ``0.0`` is bit-identical and ``1.0``
        means every compared bit differs *or* that no shift overlapped enough to
        compare, which is the honest answer for two files of very different
        lengths.
    """
    left = _as_words(first)
    right = _as_words(second)
    if left.size == 0 or right.size == 0:
        return 1.0
    required = int(min_overlap_ratio * max(left.size, right.size))
    best = 1.0
    for shift in range(-max_shift_words, max_shift_words + 1):
        if shift >= 0:
            a = left[shift:]
            b = right
        else:
            a = left
            b = right[-shift:]
        overlap = min(a.size, b.size)
        if overlap <= 0 or overlap < required:
            continue
        differing = _popcount(np.bitwise_xor(a[:overlap], b[:overlap]))
        best = min(best, differing / (32.0 * overlap))
        if best == 0.0:
            return 0.0
    return best


def anchors(words: tuple[int, ...], stride: int = 1) -> list[tuple[int, int]]:
    """Return ``(position, word)`` pairs used to find candidate pairs cheaply.

    Two files are only compared when they share an exact sub-fingerprint at a
    nearby index — the alignment search exists for the few words encoder delay
    moves, not for finding the match in the first place.  Indexing every word
    would be wasteful, so a caller may sample with *stride*.

    Args:
        words: One fingerprint's words.
        stride: Keep every *stride*-th word (``1`` keeps all of them).

    Returns:
        The sampled ``(position, word)`` pairs, in order.
    """
    step = max(1, stride)
    return [(position, words[position]) for position in range(0, len(words), step)]


def as_log_fields(distance: float) -> dict[str, Any]:
    """Return the ``distance`` field the report and the JSON payload print.

    Args:
        distance: A bit-error rate.

    Returns:
        A one-key mapping, rounded to four decimals so two runs of the same
        library print the same line.
    """
    return {"distance": round(distance, 4)}
