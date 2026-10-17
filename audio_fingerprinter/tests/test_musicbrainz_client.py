"""Tests for audio_fingerprinter.core.musicbrainz_client.

Every HTTP interaction is mocked — the real service is never called — so the
tests pin the request shape (URL, ``fmt=json``, includes, User-Agent), the
typed failure statuses, the per-run caches, and the three tie-break rules.

Changed in 1.2.0: new suite for the Sprint 2 Item 2.1 MusicBrainz client.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
import requests

from audio_fingerprinter.core.models import AcoustidRecording
from audio_fingerprinter.core.musicbrainz_client import (
    MBResult,
    MusicBrainzClient,
    is_valid_mbid,
    parse_artist,
    parse_recording,
    parse_release,
    resolve_ambiguous_with_mb,
)

REC_ID = "b0f1c1c8-3a4d-4c1b-9d1e-1a2b3c4d5e6f"
OTHER_ID = "c1d2e3f4-a5b6-4c7d-8e9f-0a1b2c3d4e5f"
REL_ID = "d2e3f4a5-b6c7-4d8e-9f0a-1b2c3d4e5f60"
ART_ID = "e3f4a5b6-c7d8-4e9f-8a0b-2c3d4e5f6071"


def _response(status_code: int = 200, payload: object = None) -> MagicMock:
    """Return a mock ``requests.Response`` carrying *payload* as JSON."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    if payload is None:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = payload
    return resp


def _client(responses: list[MagicMock]) -> MusicBrainzClient:
    """Return a client whose session replays *responses* in order.

    ``requests_per_second`` is raised so the shared rate limiter never makes a
    test wait the documented one second.
    """
    session = MagicMock(spec=requests.Session)
    session.headers = MagicMock()
    session.get.side_effect = responses
    return MusicBrainzClient(requests_per_second=1000.0, session=session)


def _recording(**overrides: object) -> AcoustidRecording:
    """Return an AcoustID candidate with MusicBrainz-shaped defaults."""
    values: dict[str, object] = {
        "acoustid_id": "a1",
        "recording_id": REC_ID,
        "title": "Song",
        "artist": "Artist",
        "score": 0.95,
        "duration": 218,
    }
    values.update(overrides)
    return AcoustidRecording(**values)  # type: ignore[arg-type]


# ── MBID validation ───────────────────────────────────────────────────────────


class TestIsValidMbid:
    def test_accepts_canonical_uuid(self) -> None:
        assert is_valid_mbid(REC_ID) is True

    def test_accepts_surrounding_whitespace(self) -> None:
        assert is_valid_mbid(f"  {REC_ID}\n") is True

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "not-an-mbid",
            REC_ID[:-1],
            f"{REC_ID}0",
            "b0f1c1c83a4d4c1b9d1e1a2b3c4d5e6f",
        ],
    )
    def test_rejects_malformed_values(self, value: str) -> None:
        assert is_valid_mbid(value) is False

    def test_uuid4_string_is_accepted(self) -> None:
        assert is_valid_mbid(str(uuid.uuid4())) is True


# ── Parsers ───────────────────────────────────────────────────────────────────


class TestParseRecording:
    def test_isrcs_as_plain_strings(self) -> None:
        parsed = parse_recording(
            {"id": REC_ID, "isrcs": ["GBAYE0601498", "USRC17607839"]}
        )
        assert parsed.isrcs == ("GBAYE0601498", "USRC17607839")

    def test_isrcs_as_objects(self) -> None:
        parsed = parse_recording(
            {
                "id": REC_ID,
                "isrcs": [{"id": "GBAYE0601498"}, {"id": ""}, "USRC17607839"],
            }
        )
        assert parsed.isrcs == ("GBAYE0601498", "USRC17607839")

    def test_isrcs_missing(self) -> None:
        assert parse_recording({"id": REC_ID}).isrcs == ()

    def test_artist_credit_keeps_joinphrase(self) -> None:
        parsed = parse_recording(
            {
                "id": REC_ID,
                "artist-credit": [
                    {"name": "10cc", "joinphrase": " & "},
                    {"name": "Guest", "joinphrase": ""},
                ],
            }
        )
        assert parsed.artist == "10cc & Guest"

    def test_artist_ids_are_collected_once(self) -> None:
        parsed = parse_recording(
            {
                "id": REC_ID,
                "artist-credit": [
                    {"artist": {"id": ART_ID}},
                    {"artist": {"id": ART_ID}},
                ],
            }
        )
        assert parsed.artist_ids == (ART_ID,)

    def test_releases_and_groups(self) -> None:
        parsed = parse_recording(
            {
                "id": REC_ID,
                "isrcs": ["GBAYE0601498"],
                "releases": [
                    {
                        "id": REL_ID,
                        "title": "Sheet Music",
                        "date": "1974-03-01",
                        "country": "GB",
                        "track-count": 10,
                        "media": [{"track-count": 10}],
                        "release-group": {"id": "f4a5b6c7-d8e9-4f0a-9b1c-3d4e5f607182"},
                    }
                ],
            }
        )
        assert parsed.releases[0].release_id == REL_ID
        assert parsed.releases[0].year == 1974
        assert parsed.releases[0].countries == ("GB",)
        assert parsed.release_group_ids == ("f4a5b6c7-d8e9-4f0a-9b1c-3d4e5f607182",)

    def test_empty_payload_does_not_raise(self) -> None:
        parsed = parse_recording({})
        assert parsed.recording_id == ""
        assert parsed.isrcs == ()
        assert parsed.releases == ()


class TestParseRelease:
    def test_release_events_and_labels(self) -> None:
        parsed = parse_release(
            {
                "id": REL_ID,
                "title": "Sheet Music",
                "date": "1974-03-01",
                "release-events": [
                    {"area": {"iso-3166-1-code": "GB"}},
                    {"area": {"iso-3166-1-code": "gb"}},
                    {"area": {"iso-3166-1-code": "US"}},
                ],
                "label-info": [
                    {"label": {"name": "UK Records"}},
                    {"label": {"name": "UK Records"}},
                    {"label": {}},
                ],
                "media": [{"track-count": 10}, {"track-count": 3}, {}],
                "release-group": {"id": "f4a5b6c7", "primary-type": "Album"},
            }
        )
        assert parsed.countries == ("GB", "US")
        assert parsed.labels == ("UK Records",)
        assert parsed.track_count == 13
        assert parsed.medium_count == 3
        assert parsed.release_group_type == "Album"

    def test_flat_country_is_read(self) -> None:
        parsed = parse_release({"id": REL_ID, "country": "de"})
        assert parsed.countries == ("DE",)

    def test_no_media_reports_no_medium_count(self) -> None:
        parsed = parse_release({"id": REL_ID})
        assert parsed.medium_count is None
        assert parsed.track_count is None


class TestParseArtist:
    def test_area_country(self) -> None:
        parsed = parse_artist(
            {
                "id": ART_ID,
                "name": "10cc",
                "sort-name": "10cc",
                "area": {"iso-3166-1-code": "gb"},
                "type": "Group",
                "disambiguation": "UK rock band",
            }
        )
        assert parsed.country == "GB"
        assert parsed.artist_type == "Group"
        assert parsed.disambiguation == "UK rock band"


# ── Client behaviour ──────────────────────────────────────────────────────────


class TestClientRequestShape:
    def test_recording_request_carries_includes_and_json(self) -> None:
        client = _client([_response(200, {"id": REC_ID, "isrcs": ["GBAYE0601498"]})])
        result = client.get_recording(REC_ID)

        assert result.ok is True
        assert result.value is not None
        assert result.value.isrcs == ("GBAYE0601498",)

        _url = client._session.get.call_args
        assert _url.args[0].endswith(f"/recording/{REC_ID}")
        params = _url.kwargs["params"]
        assert params["fmt"] == "json"
        assert "isrcs" in params["inc"]
        assert "releases" in params["inc"]
        assert client.requests_issued == 1

    def test_user_agent_is_set_on_the_session(self) -> None:
        session = MagicMock(spec=requests.Session)
        session.headers = MagicMock()
        MusicBrainzClient(requests_per_second=1000.0, session=session)
        headers = session.headers.update.call_args.args[0]
        assert headers["User-Agent"].startswith("AudioSuite-Pro/")


class TestClientFailures:
    def test_invalid_mbid_never_reaches_the_network(self) -> None:
        client = _client([_response(200, {"id": REC_ID})])
        result = client.get_recording("not-an-mbid")
        assert result.status == "invalid id"
        assert result.ok is False
        assert "36-character UUID" in result.reason
        assert client.requests_issued == 0

    def test_404_is_not_found(self) -> None:
        client = _client([_response(404)])
        assert client.get_recording(REC_ID).status == "not found"

    def test_500_is_offline(self) -> None:
        client = _client([_response(500, {"error": "boom"})])
        assert client.get_recording(REC_ID).status == "offline"

    def test_403_explains_anonymous_lookup_rejection(self) -> None:
        client = _client([_response(403)])
        result = client.get_recording(REC_ID)
        assert result.status == "offline"
        assert "HTTP 403" in result.reason

    def test_network_error_is_offline(self) -> None:
        client = _client([requests.ConnectionError("no route")])
        result = client.get_recording(REC_ID)
        assert result.status == "offline"
        assert result.value is None

    def test_non_json_body_is_offline(self) -> None:
        client = _client([_response(200, None)])
        assert client.get_release(REL_ID).status == "offline"

    def test_non_dict_payload_is_offline(self) -> None:
        client = _client([_response(200, [1, 2, 3])])
        assert client.get_release(REL_ID).status == "offline"


class TestClientCaching:
    def test_repeat_lookup_uses_one_request(self) -> None:
        client = _client([_response(200, {"id": REC_ID, "isrcs": ["A"]})])
        first = client.get_recording(REC_ID)
        second = client.get_recording(REC_ID.upper())
        assert first is second
        assert client.requests_issued == 1

    def test_failure_is_cached_too(self) -> None:
        client = _client([_response(404)])
        client.get_recording(REC_ID)
        client.get_recording(REC_ID)
        assert client.requests_issued == 1

    def test_release_and_recording_caches_are_separate(self) -> None:
        client = _client(
            [
                _response(200, {"id": REC_ID, "isrcs": []}),
                _response(200, {"id": REL_ID, "title": "Sheet Music"}),
            ]
        )
        client.get_recording(REC_ID)
        client.get_release(REL_ID)
        assert client.requests_issued == 2
        assert isinstance(client.get_release(REL_ID), MBResult)


# ── Near-tie break ────────────────────────────────────────────────────────────


def _mb_body(
    recording_id: str,
    *,
    title: str,
    artist: str = "Artist",
    isrcs: list[str] | None = None,
    album: str = "",
) -> dict[str, object]:
    """Build a minimal recording-lookup body for the tie-break tests."""
    body: dict[str, object] = {
        "id": recording_id,
        "title": title,
        "artist-credit": [{"name": artist, "joinphrase": ""}],
        "isrcs": isrcs or [],
    }
    if album:
        body["releases"] = [{"id": REL_ID, "title": album}]
    return body


class TestResolveAmbiguousWithMb:
    def test_recording_title_and_artist_resolve_the_tie(self) -> None:
        top = _recording(title="Remix", score=0.95)
        other = _recording(title="Radio Edit", recording_id=OTHER_ID, score=0.94)
        client = _client(
            [
                _response(200, _mb_body(REC_ID, title="Remix")),
                _response(200, _mb_body(OTHER_ID, title="Radio Edit")),
            ]
        )

        result = resolve_ambiguous_with_mb(
            (top, other), client, title_tag="Radio Edit", artist_tag="Artist"
        )

        assert result.recording is other
        assert result.resolved is True
        assert "file tags" in result.evidence

    def test_album_tag_resolves_when_titles_do_not(self) -> None:
        top = _recording(title="Same", score=0.95)
        other = _recording(title="Same", recording_id=OTHER_ID, score=0.94)
        client = _client(
            [
                _response(200, _mb_body(REC_ID, title="Same")),
                _response(200, _mb_body(OTHER_ID, title="Same", album="Sheet Music")),
            ]
        )

        result = resolve_ambiguous_with_mb(
            (top, other), client, album_tag="Sheet Music"
        )

        assert result.recording is other
        assert "album tag" in result.evidence

    def test_isrc_presence_resolves_as_last_resort(self) -> None:
        top = _recording(title="Same", score=0.95)
        other = _recording(title="Same", recording_id=OTHER_ID, score=0.94)
        client = _client(
            [
                _response(200, _mb_body(REC_ID, title="Same")),
                _response(
                    200, _mb_body(OTHER_ID, title="Same", isrcs=["GBAYE0601498"])
                ),
            ]
        )

        result = resolve_ambiguous_with_mb((top, other), client)

        assert result.recording is other
        assert "ISRCs" in result.evidence

    def test_indistinguishable_candidates_keep_rank_order(self) -> None:
        top = _recording(title="Same", score=0.95)
        other = _recording(title="Same", recording_id=OTHER_ID, score=0.94)
        client = _client(
            [
                _response(200, _mb_body(REC_ID, title="Same")),
                _response(200, _mb_body(OTHER_ID, title="Same")),
            ]
        )

        result = resolve_ambiguous_with_mb((top, other), client)

        assert result.recording is top
        assert result.resolved is False
        assert result.evidence == ""

    def test_offline_service_keeps_rank_order(self) -> None:
        top = _recording(title="Same", score=0.95)
        other = _recording(title="Same", recording_id=OTHER_ID, score=0.94)
        client = _client([_response(500), _response(500)])

        result = resolve_ambiguous_with_mb((top, other), client)

        assert result.recording is top
        assert result.resolved is False

    def test_single_candidate_never_queries(self) -> None:
        top = _recording(title="Only", score=0.99)
        client = _client([])
        result = resolve_ambiguous_with_mb((top,), client)
        assert result.recording is top
        assert client.requests_issued == 0

    def test_only_the_two_top_candidates_are_queried(self) -> None:
        top = _recording(title="Same", score=0.95)
        second = _recording(title="Same", recording_id=OTHER_ID, score=0.94)
        third = _recording(
            title="Same",
            recording_id="f4a5b6c7-d8e9-4f0a-9b1c-3d4e5f607182",
            score=0.93,
        )
        client = _client(
            [
                _response(200, _mb_body(REC_ID, title="Same")),
                _response(200, _mb_body(OTHER_ID, title="Same")),
            ]
        )

        resolve_ambiguous_with_mb((top, second, third), client)

        assert client.requests_issued == 2
