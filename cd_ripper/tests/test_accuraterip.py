"""
tests/test_accuraterip.py

Tests for cd_ripper/core/accuraterip.py — the clean-room AccurateRip
Disc ID, v1/v2 checksum, ARL payload parsing, HTTP resolver and matching.

No mocks are used for the checksum/id math: every expected value here is
either a hand-derived reference or a published TOC vector.

Changed in 1.2.0: adds the ``match_track`` confidence matrix and the EAC-style
``describe_verification`` wording lock (PLAN_feature_expansion.md D30).

Run with:
    pytest tests/test_accuraterip.py -v
"""

from __future__ import annotations

import random
import struct
from unittest.mock import MagicMock

import pytest
import requests

from cd_ripper.core.accuraterip import (
    ACCURATERIP_URL,
    FRAMES_PER_SECTOR,
    AccurateRipClient,
    DBEntry,
    DBMatch,
    DBTrackEntry,
    LookupFound,
    LookupNotFound,
    LookupOffline,
    TrackChecksums,
    VerificationMethod,
    VerificationStatus,
    compute_disc_ids,
    compute_track_checksums,
    describe_verification,
    match_track,
    parse_db_entry,
    parse_db_payload,
    verify_track,
    with_gap_window,
)

# ── Published TOC vectors (whipper test data) ──────────────────────────────


CURE_STARTS = [
    0,
    28324,
    46110,
    66767,
    78047,
    88735,
    109991,
    130209,
    147045,
    162154,
    180653,
    198027,
    218771,
]
CURE_LEADOUT = 238034

BLOC_STARTS = [
    15220,
    34869,
    51382,
    69040,
    84142,
    96676,
    112377,
    132298,
    148445,
    167922,
    185389,
    203181,
    221953,
]
BLOC_LEADOUT = 243216


def _pcm(values: list[int]) -> bytes:
    return b"".join(struct.pack("<I", v) for v in values)


def _constant_pcm(frames: int, value: int) -> bytes:
    return struct.pack("<I", value) * frames


def _reference_checksums(
    pcm: bytes, track_number: int, track_count: int
) -> tuple[int, int]:
    """Independent nested-loop replica of the reference implementation.

    Structurally distinct from the production vectorised code so an
    off-by-one in the position/skip handling cannot be self-consistent.
    """
    n = len(pcm) // 4
    v1, v2 = 0, 0
    for i in range(n):
        pos = i + 1
        if track_number == 1 and pos < FRAMES_PER_SECTOR * 5:
            continue
        if track_number == track_count and pos > n - (FRAMES_PER_SECTOR * 5):
            continue
        value = int.from_bytes(pcm[i * 4 : i * 4 + 4], "little")
        product = pos * value
        v1 = (v1 + (product & 0xFFFFFFFF)) & 0xFFFFFFFF
        v2 = (v2 + (product & 0xFFFFFFFF) + (product >> 32)) & 0xFFFFFFFF
    return v1, v2


# ===========================================================================
# Disc ID
# ===========================================================================


class TestDiscIds:
    def test_cure_published_vector(self) -> None:
        ids = compute_disc_ids(CURE_STARTS, CURE_LEADOUT)
        assert ids.disc_id1 == 0x0019D4C3
        assert ids.disc_id2 == 0x00FE8924
        assert ids.cddb_id == 0xB90C650D
        assert ids.track_count == 13
        assert ids.accuraterip_path == "3/c/4/dBAR-013-0019d4c3-00fe8924-b90c650d.bin"

    def test_bloc_party_published_vector(self) -> None:
        ids = compute_disc_ids(BLOC_STARTS, BLOC_LEADOUT)
        assert ids.disc_id1 == 0x001AF2DE
        assert ids.disc_id2 == 0x0105994E
        assert ids.cddb_id == 0xAD0BE00D
        assert ids.track_count == 13
        assert ids.accuraterip_path == "e/d/2/dBAR-013-001af2de-0105994e-ad0be00d.bin"

    def test_zero_first_track_weights_as_one_in_disc_id2(self) -> None:
        # The Cure disc starts at LBA 0; the (+1) fixup must fire or disc_id2
        # is off by exactly one (0x00fe8923).
        ids = compute_disc_ids([0, 28324], 70000)
        assert ids.disc_id2 == ((1 * 1 + 28324 * 2 + 70000 * 3) & 0xFFFFFFFF)

    def test_requires_nonempty_toc(self) -> None:
        with pytest.raises(ValueError):
            compute_disc_ids([], 0)


# ===========================================================================
# Checksums — hand-derived references
# ===========================================================================


class TestChecksumsReference:
    def test_middle_track_small_window(self) -> None:
        # No edge skips: positions 1..3, values 1..3.
        sums = compute_track_checksums(_pcm([1, 2, 3]), track_number=2, track_count=3)
        assert sums == TrackChecksums(crc1=14, crc2=14)

    def test_single_track_disc_both_edge_skips(self) -> None:
        # Frames = 2940 + 3 + 2940; only positions 2940..2943 are included.
        sums = compute_track_checksums(
            _constant_pcm(FRAMES_PER_SECTOR * 5 * 2 + 3, 1),
            track_number=1,
            track_count=1,
        )
        assert sums == TrackChecksums(crc1=11766, crc2=11766)

    def test_first_track_skip_boundary(self) -> None:
        # Exactly 2940 frames: only position 2940 survives (frame index 2939).
        sums = compute_track_checksums(
            _constant_pcm(FRAMES_PER_SECTOR * 5, 1),
            track_number=1,
            track_count=2,
        )
        assert sums == TrackChecksums(crc1=2940, crc2=2940)

    def test_last_track_skip_boundary(self) -> None:
        # 2940 frames -> nothing survives; 1 extra frame -> position 1 only.
        empty = compute_track_checksums(
            _constant_pcm(FRAMES_PER_SECTOR * 5, 1),
            track_number=2,
            track_count=2,
        )
        assert empty == TrackChecksums(crc1=0, crc2=0)
        one = compute_track_checksums(
            _constant_pcm(FRAMES_PER_SECTOR * 5 + 1, 1),
            track_number=2,
            track_count=2,
        )
        assert one == TrackChecksums(crc1=1, crc2=1)

    def test_first_and_last_small_disc(self) -> None:
        none_survive = compute_track_checksums(
            _constant_pcm(FRAMES_PER_SECTOR * 5, 1),
            track_number=1,
            track_count=1,
        )
        assert none_survive == TrackChecksums(crc1=0, crc2=0)

    def test_v2_mixes_high_and_low_halves(self) -> None:
        # One non-zero frame at position 131072 (= 0x20000) with value
        # 0xFFFF: product = 0x1FFFE0000, so low32 = 0xFFFE0000 and
        # high32 = 1. v1 keeps only the low 32 bits; v2 sums hi+lo.
        frames = bytearray(131073 * 4)
        frames[131071 * 4 : 131072 * 4] = struct.pack("<I", 0xFFFF)
        sums = compute_track_checksums(bytes(frames), track_number=2, track_count=3)
        assert sums == TrackChecksums(crc1=0xFFFE0000, crc2=0xFFFE0001)

    def test_non_multiple_of_four_rejected(self) -> None:
        with pytest.raises(ValueError):
            compute_track_checksums(b"\x00\x01", track_number=1, track_count=1)


class TestChecksumsAgainstIndependentReplica:
    def test_matches_reference_loop_across_positions(self) -> None:
        rng = random.Random(7)
        pcm = b"".join(
            struct.pack("<I", rng.randrange(0x100000000)) for _ in range(7000)
        )
        for track_number, track_count in [(1, 3), (2, 3), (3, 3), (1, 1), (2, 2)]:
            expected = _reference_checksums(pcm, track_number, track_count)
            actual = compute_track_checksums(pcm, track_number, track_count)
            assert actual == TrackChecksums(crc1=expected[0], crc2=expected[1])


# ===========================================================================
# Gap window
# ===========================================================================


class TestWithGapWindow:
    def test_merges_prev_tail_track_next_head(self) -> None:
        tail = _constant_pcm(6000, 1)  # 6000 frames -> keep last 2940
        track = _constant_pcm(100, 2)
        head = _constant_pcm(6000, 3)  # keep first 2940
        merged = with_gap_window(track, tail, head)
        assert len(merged) == 4 * (FRAMES_PER_SECTOR * 5 + 100 + FRAMES_PER_SECTOR * 5)
        assert (
            merged[: 4 * FRAMES_PER_SECTOR * 5] == tail[-(4 * FRAMES_PER_SECTOR * 5) :]
        )
        assert (
            merged[-(4 * FRAMES_PER_SECTOR * 5) :] == head[: 4 * FRAMES_PER_SECTOR * 5]
        )
        assert (
            merged[4 * FRAMES_PER_SECTOR * 5 : 4 * (FRAMES_PER_SECTOR * 5 + 100)]
            == track
        )

    def test_omits_missing_neighbours(self) -> None:
        track = _constant_pcm(4, 9)
        assert with_gap_window(track, None, None) == track

    def test_short_neighbour_pcm_kept_whole(self) -> None:
        tail = _constant_pcm(10, 5)
        merged = with_gap_window(_constant_pcm(4, 9), tail, None)
        assert merged[: 4 * 10] == tail


# ===========================================================================
# ARL payload parsing
# ===========================================================================


def _fixture_payload() -> bytes:
    header = bytes([2]) + struct.pack("<III", 0x0000F21C, 0x00027EF8, 0x05021002)

    def track(confidence: int, crc1: int) -> bytes:
        return bytes([confidence]) + struct.pack("<II", crc1, 0)

    entry0 = header + track(12, 0x284FC705) + track(20, 0x9CC1F32E)
    entry1 = header + track(7, 0xDC77F9AB) + track(7, 0xDD97D2C3)
    return entry0 + entry1


class TestParseDbPayload:
    def test_parses_two_concatenated_records(self) -> None:
        entries = parse_db_payload(_fixture_payload())
        assert len(entries) == 2

        e0 = entries[0]
        assert e0.disc_id1 == 0x0000F21C
        assert e0.disc_id2 == 0x00027EF8
        assert e0.cddb_id == 0x05021002
        assert e0.tracks == (
            DBTrackEntry(confidence=12, crc1=0x284FC705, crc2=0),
            DBTrackEntry(confidence=20, crc1=0x9CC1F32E, crc2=0),
        )

        e1 = entries[1]
        assert e1.tracks == (
            DBTrackEntry(confidence=7, crc1=0xDC77F9AB, crc2=0),
            DBTrackEntry(confidence=7, crc1=0xDD97D2C3, crc2=0),
        )

    def test_parse_entry_rejects_truncation(self) -> None:
        payload = _fixture_payload()
        with pytest.raises(ValueError):
            parse_db_entry(payload[:13])  # header only, no track bytes

    def test_parse_entry_rejects_short_header(self) -> None:
        with pytest.raises(ValueError):
            parse_db_entry(b"\x02\x00")

    def test_empty_payload_yields_no_entries(self) -> None:
        assert parse_db_payload(b"") == ()

    def test_trailing_fragment_is_dropped(self) -> None:
        entries = parse_db_payload(_fixture_payload() + b"\x02\x00")
        assert len(entries) == 2


# ===========================================================================
# HTTP resolver
# ===========================================================================


class _FakeResponse:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content


def _client_with(session: MagicMock) -> AccurateRipClient:
    return AccurateRipClient(session=session)


class TestAccurateRipClientResolve:
    def test_200_returns_found_with_url(self) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(200, _fixture_payload())
        result = _client_with(session).resolve(
            "c/1/2/dBAR-002-0000f21c-00027ef8-05021002.bin"
        )
        assert isinstance(result, LookupFound)
        assert len(result.entries) == 2
        session.get.assert_called_once_with(
            ACCURATERIP_URL + "c/1/2/dBAR-002-0000f21c-00027ef8-05021002.bin",
            timeout=10.0,
        )

    def test_404_returns_not_found(self) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(404, b"")
        result = _client_with(session).resolve(
            "e/d/2/dBAR-013-001af2de-0105994e-ad0be00d.bin"
        )
        assert isinstance(result, LookupNotFound)

    def test_network_timeout_returns_offline(self) -> None:
        session = MagicMock()
        session.get.side_effect = requests.exceptions.Timeout("timed out")
        result = _client_with(session).resolve("x/y/z/dBAR.bin")
        assert isinstance(result, LookupOffline)
        assert "timed out" in result.reason

    def test_http_5xx_returns_offline(self) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(503, b"")
        result = _client_with(session).resolve("x/y/z/dBAR.bin")
        assert isinstance(result, LookupOffline)
        assert "503" in result.reason

    def test_empty_body_returns_not_found(self) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(200, b"")
        result = _client_with(session).resolve("x/y/z/dBAR.bin")
        assert isinstance(result, LookupNotFound)

    def test_malformed_payload_returns_offline(self) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(200, b"\xff\x00")
        result = _client_with(session).resolve("x/y/z/dBAR.bin")
        assert isinstance(result, LookupOffline)
        assert "Malformed" in result.reason

    def test_custom_timeout_is_propagated(self) -> None:
        session = MagicMock()
        session.get.return_value = _FakeResponse(404, b"")
        client = AccurateRipClient(request_timeout=3.5, session=session)
        client.resolve("x/y/z/dBAR.bin")
        session.get.assert_called_once_with(
            ACCURATERIP_URL + "x/y/z/dBAR.bin", timeout=3.5
        )


# ===========================================================================
# Matching
# ===========================================================================


class TestVerifyTrack:
    @staticmethod
    def _entries(
        *track_lists: list[tuple[int, int, int]],
    ) -> list[DBEntry]:
        """Build one DBEntry (disc record) per supplied track list."""
        return [
            DBEntry(
                disc_id1=0,
                disc_id2=0,
                cddb_id=0,
                tracks=tuple(
                    DBTrackEntry(confidence=c, crc1=a, crc2=b) for c, a, b in tracks
                ),
            )
            for tracks in track_lists
        ]

    def test_crc1_match_verifies(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        status = verify_track(TrackChecksums(0xAAAA, 0), entries, 0)
        assert status is VerificationStatus.VERIFIED

    def test_crc2_match_verifies(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        status = verify_track(TrackChecksums(0xCCCC, 0xBBBB), entries, 0)
        assert status is VerificationStatus.VERIFIED

    def test_no_match_is_mismatch(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        status = verify_track(TrackChecksums(0x1111, 0x2222), entries, 0)
        assert status is VerificationStatus.MISMATCH

    def test_any_record_matching_wins(self) -> None:
        entries = self._entries(
            [(3, 0x1111, 0x2222)],
            [(9, 0xAAAA, 0x3333)],
        )
        status = verify_track(TrackChecksums(0xAAAA, 0xFFFF), entries, 0)
        assert status is VerificationStatus.VERIFIED

    def test_track_beyond_entry_count_is_mismatch(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        status = verify_track(TrackChecksums(0xAAAA, 0), entries, 3)
        assert status is VerificationStatus.MISMATCH

    def test_status_values_are_stable_strings(self) -> None:
        assert [s.value for s in VerificationStatus] == [
            "VERIFIED",
            "MISMATCH",
            "NO_ENTRY",
            "OFFLINE",
        ]


class TestMatchTrack:
    """``match_track`` returns the record, not just "matched"."""

    @staticmethod
    def _entries(*track_lists: list[tuple[int, int, int]]) -> list[DBEntry]:
        """Build one DBEntry (disc record) per supplied track list."""
        return [
            DBEntry(
                disc_id1=0,
                disc_id2=0,
                cddb_id=0,
                tracks=tuple(
                    DBTrackEntry(confidence=c, crc1=a, crc2=b) for c, a, b in tracks
                ),
            )
            for tracks in track_lists
        ]

    def test_v1_match_reports_confidence_and_which_crc(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        match = match_track(TrackChecksums(0xAAAA, 0), entries, 0)
        assert match == DBMatch(confidence=5, crc="v1", entry_index=0)

    def test_v2_match_reports_which_crc(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        match = match_track(TrackChecksums(0xCCCC, 0xBBBB), entries, 0)
        assert match is not None
        assert match.crc == "v2"
        assert match.confidence == 5

    def test_no_match_is_none(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        assert match_track(TrackChecksums(0x1111, 0x2222), entries, 0) is None

    def test_highest_confidence_wins_across_records(self) -> None:
        entries = self._entries(
            [(3, 0xAAAA, 0x1111)],
            [(41, 0xAAAA, 0x2222)],
            [(12, 0xAAAA, 0x3333)],
        )
        match = match_track(TrackChecksums(0xAAAA, 0), entries, 0)
        assert match is not None
        assert match.confidence == 41
        assert match.entry_index == 1

    def test_track_beyond_a_record_is_skipped_not_fatal(self) -> None:
        # A record with fewer tracks (a short pressing) must not abort the
        # search for a later record that does describe this track.
        entries = self._entries([(9, 0x1111, 0x2222)], [(4, 0xAAAA, 0x3333)])
        match = match_track(TrackChecksums(0xAAAA, 0), entries, 0)
        assert match is not None
        assert match.confidence == 4

    def test_verify_track_remains_a_status_only_view(self) -> None:
        entries = self._entries([(5, 0xAAAA, 0xBBBB)])
        assert (
            verify_track(TrackChecksums(0xAAAA, 0), entries, 0)
            is VerificationStatus.VERIFIED
        )


class TestDescribeVerification:
    """The user-facing wording is locked, member by member (D30)."""

    def test_accuraterip_match_shows_the_confidence(self) -> None:
        assert (
            describe_verification(
                VerificationStatus.VERIFIED,
                confidence=7,
                method=VerificationMethod.ACCURATERIP_TRACK,
            )
            == "Accurate (confidence 7)"
        )

    def test_with_gap_match_uses_the_same_wording(self) -> None:
        assert (
            describe_verification(
                VerificationStatus.VERIFIED,
                confidence=1,
                method=VerificationMethod.ACCURATERIP_GAP,
            )
            == "Accurate (confidence 1)"
        )

    def test_confidence_one_is_still_accurate_not_a_warning(self) -> None:
        # No invented accurate/confident boundary: one agreeing submission is
        # a match, so it is reported as accurate with confidence 1.
        assert (
            describe_verification(
                VerificationStatus.VERIFIED,
                confidence=1,
                method=VerificationMethod.ACCURATERIP_TRACK,
            )
            == "Accurate (confidence 1)"
        )

    def test_rip_twice_has_its_own_label(self) -> None:
        assert (
            describe_verification(
                VerificationStatus.VERIFIED, method=VerificationMethod.RIP_TWICE
            )
            == "Rip-twice verified"
        )

    def test_mismatch_says_not_accurate(self) -> None:
        assert (
            describe_verification(
                VerificationStatus.MISMATCH,
                method=VerificationMethod.ACCURATERIP_TRACK,
            )
            == "Not accurate"
        )

    def test_no_entry_says_not_in_database(self) -> None:
        assert describe_verification(VerificationStatus.NO_ENTRY) == "Not in database"

    def test_offline_says_unavailable(self) -> None:
        assert (
            describe_verification(VerificationStatus.OFFLINE) == "Unavailable (offline)"
        )

    def test_cancelled_outcome_has_no_label(self) -> None:
        assert describe_verification(None) == ""

    def test_method_values_are_stable_strings(self) -> None:
        assert [m.value for m in VerificationMethod] == [
            "none",
            "rip-twice",
            "accuraterip-track",
            "accuraterip-gap",
        ]
