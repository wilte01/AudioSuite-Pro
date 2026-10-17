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
    CLIENT_PARAM,
    ISRCSubmission,
    MBAuth,
    MBResult,
    MusicBrainzClient,
    build_isrc_submission_xml,
    is_valid_isrc,
    is_valid_mbid,
    isrc_error,
    normalize_isrc,
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


# ── ISRC submission ───────────────────────────────────────────────────────


def _submit_client(status_code: int = 200) -> tuple[MusicBrainzClient, MagicMock]:
    """Return a client plus the mock session its POST would use."""
    session = MagicMock(spec=requests.Session)
    session.headers = MagicMock()
    session.post.return_value = _response(status_code)
    client = MusicBrainzClient(requests_per_second=1000.0, session=session)
    return client, session


def _posted_body(session: MagicMock) -> str:
    """Decode the body handed to ``session.post``."""
    data = session.post.call_args.kwargs["data"]
    return data.decode("utf-8")


class TestIsrcValidation:
    """The service's own rules, applied locally before any request."""

    @pytest.mark.parametrize(
        "raw",
        [
            "USRC17607839",
            "usrc17607839",
            "US-RC1-76-07839",
            "  gb-um7-24-00001  ",
        ],
    )
    def test_display_and_compact_forms_normalise(self, raw: str) -> None:
        # Tags carry whichever form the ripper wrote; the service takes the
        # compact upper-case one only.
        assert is_valid_isrc(raw)
        assert isrc_error(raw) == ""

    def test_normalize_strips_separators_and_uppercases(self) -> None:
        assert normalize_isrc(" gb-um7-24-00001 ") == "GBUM72400001"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "USRC1760783",  # 11 characters
            "USRC176078390",  # 13 characters
            "USRC17607A39",  # letter in the seven-digit designation tail
            "1SRC17607839",  # country code must be letters
            "USRC1760783X",
        ],
    )
    def test_invalid_codes_are_rejected(self, raw: str) -> None:
        assert not is_valid_isrc(raw)
        assert isrc_error(raw)

    def test_error_names_the_defect(self) -> None:
        assert "12 characters" in isrc_error("USRC1760783")
        assert "two letters" in isrc_error("1SRC17607839")
        assert "empty" in isrc_error("  ")


class TestBuildIsrcSubmissionXml:
    """The payload is a pure, deterministic MMD 2.0 document."""

    def test_one_recording_one_isrc(self) -> None:
        xml = build_isrc_submission_xml([ISRCSubmission(REC_ID, ("USRC17607839",))])
        assert xml == (
            '<metadata xmlns="http://musicbrainz.org/ns/mmd-2.0#">\n'
            "  <recording-list>\n"
            f'    <recording id="{REC_ID}">\n'
            '      <isrc-list count="1">\n'
            '        <isrc id="USRC17607839"/>\n'
            "      </isrc-list>\n"
            "    </recording>\n"
            "  </recording-list>\n"
            "</metadata>\n"
        )

    def test_count_matches_the_isrcs_listed(self) -> None:
        xml = build_isrc_submission_xml(
            [ISRCSubmission(REC_ID, ("USRC17607839", "GBUM72400001"))]
        )
        assert 'count="2"' in xml
        assert xml.count("<isrc id=") == 2

    def test_order_is_normalised_so_the_preview_is_stable(self) -> None:
        # Files finish in parallel, so anything but a sorted payload could not
        # be previewed before the run and then matched to what was sent.
        a = ISRCSubmission(REC_ID, ("USRC17607839", "GBUM72400001"))
        b = ISRCSubmission(OTHER_ID, ("FRXXX2400001",))
        assert build_isrc_submission_xml([a, b]) == build_isrc_submission_xml(
            [b, ISRCSubmission(REC_ID, ("GBUM72400001", "USRC17607839"))]
        )

    def test_same_recording_in_two_submissions_merges(self) -> None:
        xml = build_isrc_submission_xml(
            [
                ISRCSubmission(REC_ID, ("USRC17607839",)),
                ISRCSubmission(REC_ID, ("USRC17607839", "GBUM72400001")),
            ]
        )
        assert xml.count(f'<recording id="{REC_ID}"') == 1
        assert xml.count("<isrc id=") == 2

    def test_nothing_to_submit_renders_nothing(self) -> None:
        assert build_isrc_submission_xml([]) == ""
        assert build_isrc_submission_xml([ISRCSubmission(REC_ID, ())]) == ""

    def test_invalid_isrc_raises_before_the_wire(self) -> None:
        with pytest.raises(ValueError, match="not an ISRC"):
            build_isrc_submission_xml([ISRCSubmission(REC_ID, ("NOPE",))])

    def test_invalid_recording_id_raises(self) -> None:
        with pytest.raises(ValueError, match="not a MusicBrainz recording id"):
            build_isrc_submission_xml(
                [ISRCSubmission("not-an-mbid", ("USRC17607839",))]
            )


class TestSubmitIsrcs:
    """The POST: endpoint, headers, auth, and every failure status."""

    def _subs(self) -> list[ISRCSubmission]:
        return [
            ISRCSubmission(REC_ID, ("USRC17607839", "GBUM72400001")),
            ISRCSubmission(OTHER_ID, ("FRXXX2400001",)),
        ]

    def test_posts_exactly_the_previewed_payload(self) -> None:
        # The dry run's whole value: the bytes it showed are the bytes sent.
        subs = self._subs()
        preview = build_isrc_submission_xml(subs)
        client, session = _submit_client()

        result = client.submit_isrcs(subs, MBAuth(token="tok"))

        assert result.ok
        assert _posted_body(session) == preview

    def test_endpoint_carries_the_client_parameter(self) -> None:
        client, session = _submit_client()
        client.submit_isrcs(self._subs(), MBAuth(token="tok"))
        url = session.post.call_args.args[0]
        assert url.startswith("https://musicbrainz.org/ws/2/recording/?")
        assert f"client={CLIENT_PARAM}" in url

    def test_headers_declare_xml(self) -> None:
        client, session = _submit_client()
        client.submit_isrcs(self._subs(), MBAuth(token="tok"))
        headers = session.post.call_args.kwargs["headers"]
        assert headers["Content-Type"] == "application/xml; charset=UTF-8"
        assert headers["Accept"] == "application/xml"

    def test_oauth_sends_a_bearer_token(self) -> None:
        client, session = _submit_client()
        client.submit_isrcs(self._subs(), MBAuth(token="secret-token"))
        headers = session.post.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer secret-token"
        assert "auth" not in session.post.call_args.kwargs

    def test_app_token_uses_digest_with_the_username(self) -> None:
        client, session = _submit_client()
        client.submit_isrcs(
            self._subs(),
            MBAuth(token="app-token", method="app-token", username="alice"),
        )
        auth = session.post.call_args.kwargs["auth"]
        assert auth.username == "alice"
        assert auth.password == "app-token"
        assert "Authorization" not in session.post.call_args.kwargs["headers"]

    def test_result_counts_what_was_sent(self) -> None:
        client, _session = _submit_client()
        result = client.submit_isrcs(self._subs(), MBAuth(token="tok"))
        assert result.recordings == 2
        assert result.isrcs == 3
        assert client.requests_issued == 1

    def test_missing_token_makes_no_request(self) -> None:
        client, session = _submit_client()
        result = client.submit_isrcs(self._subs(), MBAuth())
        assert result.status == "no auth"
        assert "MUSICBRAINZ_TOKEN" in result.reason
        session.post.assert_not_called()
        assert client.requests_issued == 0

    def test_app_token_without_username_makes_no_request(self) -> None:
        client, session = _submit_client()
        result = client.submit_isrcs(
            self._subs(), MBAuth(token="t", method="app-token")
        )
        assert result.status == "no auth"
        assert "--mb-user" in result.reason
        session.post.assert_not_called()

    def test_nothing_to_submit_makes_no_request(self) -> None:
        client, session = _submit_client()
        result = client.submit_isrcs([ISRCSubmission(REC_ID, ())], MBAuth(token="tok"))
        assert result.status == "nothing to submit"
        session.post.assert_not_called()

    @pytest.mark.parametrize(
        ("code", "status"),
        [
            (401, "not authorised"),
            (403, "not authorised"),
            (400, "rejected"),
            (503, "offline"),
            (500, "offline"),
        ],
    )
    def test_http_failures_are_typed(self, code: int, status: str) -> None:
        client, _session = _submit_client(code)
        result = client.submit_isrcs(self._subs(), MBAuth(token="tok"))
        assert result.status == status
        assert result.reason
        assert not result.ok

    def test_network_failure_is_offline(self) -> None:
        client, session = _submit_client()
        session.post.side_effect = requests.ConnectionError("down")
        result = client.submit_isrcs(self._subs(), MBAuth(token="tok"))
        assert result.status == "offline"
        assert "down" in result.reason

    def test_token_never_appears_in_the_result(self) -> None:
        client, _session = _submit_client(401)
        result = client.submit_isrcs(self._subs(), MBAuth(token="secret-token"))
        assert "secret-token" not in result.reason
        assert "secret-token" not in result.url
