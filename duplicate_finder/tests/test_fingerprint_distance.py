"""Tests for fingerprint decoding and the bit-error distance.

The alignment rules are the ones a wrong answer hides behind: an unaligned
comparison reports a large distance for two encodings of one recording, and an
under-covered comparison reports a small one for a 30 s clip against a
four-minute track.  Both directions are pinned here.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import base64

import pytest

from duplicate_finder.core.fingerprint_distance import (
    FingerprintFormatError,
    anchors,
    as_log_fields,
    bit_error_rate,
    decode_words,
)

#: Four words used as a fixture; the values are arbitrary but distinct.
SAMPLE = (0x0000000F, 0x00FF00FF, 0xFFFFFFFF, 0x12345678)


class TestDecodeWords:
    """fpcalc's two output shapes, and the one that must be refused."""

    def test_comma_separated_words_are_read_in_order(self) -> None:
        assert decode_words("1,2,3,4") == (1, 2, 3, 4)

    def test_surrounding_whitespace_is_ignored(self) -> None:
        assert decode_words("  5, 6 ,7  ") == (5, 6, 7)

    def test_trailing_comma_does_not_add_a_word(self) -> None:
        assert decode_words("1,2,") == (1, 2)

    def test_url_safe_base64_of_whole_words_is_decoded(self) -> None:
        payload = b"".join(word.to_bytes(4, "little") for word in SAMPLE)
        encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")

        assert decode_words(encoded) == SAMPLE

    def test_a_compressed_payload_is_refused_rather_than_compared(self) -> None:
        # Chromaprint's default compression is variable-length, so its byte
        # count is not a whole number of words.  Comparing it as a word array
        # would silently measure garbage.
        with pytest.raises(FingerprintFormatError, match="compressed"):
            decode_words(base64.urlsafe_b64encode(b"\x01\x02\x03").decode("ascii"))

    def test_an_empty_fingerprint_is_refused(self) -> None:
        with pytest.raises(FingerprintFormatError, match="empty"):
            decode_words("   ")

    def test_a_non_numeric_word_is_refused(self) -> None:
        with pytest.raises(FingerprintFormatError, match="non-numeric"):
            decode_words("1,two,3")

    def test_undecodable_base64_is_refused(self) -> None:
        with pytest.raises(FingerprintFormatError):
            decode_words("!!!!")


class TestBitErrorRate:
    """The distance itself: exactness, alignment, and the coverage rule."""

    def test_identical_fingerprints_are_zero(self) -> None:
        assert bit_error_rate(SAMPLE, SAMPLE) == 0.0

    def test_one_differing_bit_is_one_over_32_per_word(self) -> None:
        other = (SAMPLE[0] ^ 0b1, *SAMPLE[1:])

        assert bit_error_rate(SAMPLE, other) == pytest.approx(1 / (32 * len(SAMPLE)))

    def test_the_same_alignment_with_every_bit_different_is_one(self) -> None:
        other = tuple(word ^ 0xFFFFFFFF for word in SAMPLE)

        # Alignment is disabled so the assertion measures the distance at the
        # position the two fingerprints are compared from; a shift can always
        # find a partially matching offset in random data.
        assert bit_error_rate(SAMPLE, other, max_shift_words=0) == 1.0

    def test_encoder_delay_is_absorbed_by_the_shift_search(self) -> None:
        # An MP3 gains a few tens of milliseconds of padding, so the same audio
        # sits a word or two later in one of the two sequences.
        words = (5, 6, 7, 8, 9, 10, 11, 12)
        delayed = (7, 8, 9, 10, 11, 12, 99, 99)
        advanced = (99, 99, 5, 6, 7, 8, 9, 10)

        assert bit_error_rate(words, delayed) == 0.0
        assert bit_error_rate(words, advanced) == 0.0

    def test_a_shift_beyond_the_search_width_is_not_aligned(self) -> None:
        words = (5, 6, 7, 8, 9, 10, 11, 12)
        delayed = (7, 8, 9, 10, 11, 12, 99, 99)

        assert bit_error_rate(words, delayed) == 0.0
        assert bit_error_rate(words, delayed, max_shift_words=1) > 0.0

    def test_a_short_clip_inside_a_long_track_is_not_a_duplicate(self) -> None:
        clip = SAMPLE
        track = (*SAMPLE, *(word for word in range(1, 60)))

        assert bit_error_rate(clip, track) == 1.0

    def test_the_overlap_ratio_is_what_decides_that(self) -> None:
        clip = SAMPLE
        track = (*SAMPLE, *(word for word in range(1, 60)))

        # With a tiny overlap requirement the same pair *is* comparable, which
        # proves the refusal above came from the coverage rule and not from a
        # decode failure.
        assert bit_error_rate(clip, track, min_overlap_ratio=0.01) == 0.0

    def test_an_empty_fingerprint_cannot_match(self) -> None:
        assert bit_error_rate((), SAMPLE) == 1.0
        assert bit_error_rate(SAMPLE, ()) == 1.0

    def test_the_order_of_the_arguments_does_not_matter(self) -> None:
        other = (SAMPLE[0] ^ 0b11, *SAMPLE[1:])

        assert bit_error_rate(SAMPLE, other) == bit_error_rate(other, SAMPLE)


class TestAnchors:
    """The candidate-pair sampler."""

    def test_every_word_is_an_anchor_at_stride_one(self) -> None:
        assert anchors((7, 8, 9)) == [(0, 7), (1, 8), (2, 9)]

    def test_a_stride_samples_positions_not_values(self) -> None:
        assert anchors((7, 8, 9, 10, 11), stride=2) == [(0, 7), (2, 9), (4, 11)]

    def test_a_non_positive_stride_is_treated_as_one(self) -> None:
        assert anchors((7, 8), stride=0) == [(0, 7), (1, 8)]


class TestLogFields:
    """The printed distance is rounded once, here."""

    def test_distance_is_rounded_to_four_decimals(self) -> None:
        assert as_log_fields(0.123456789) == {"distance": 0.1235}

    def test_a_zero_distance_prints_as_zero(self) -> None:
        assert as_log_fields(0.0) == {"distance": 0.0}
