"""Tests for album_art_sync.api.caa — Cover Art Archive lookup.

The payload fixtures are verbatim shapes from live Cover Art Archive
responses (``/release/{mbid}`` and ``/release-group/{mbid}``), including
the 404 miss and an archive holding no ``images`` at all.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests

from album_art_sync.api import caa
from album_art_sync.config.settings import CONFIG
from album_art_sync.core.ranker import RankedCandidate

RELEASE_MBID = "db85c244-53e7-441c-bab0-52c9c0d27450"
RG_MBID = "ddaa2d4d-314e-3e7c-b1d0-f6d207f5aa2f"

# Verbatim live /release/ payload (one Front, one Back).
RELEASE_PAYLOAD: dict[str, Any] = {
    "images": [
        {
            "types": ["Front"],
            "front": True,
            "back": False,
            "edit": 1000000,
            "image": (
                f"https://coverartarchive.org/release/{RELEASE_MBID}/1000000-front.jpg"
            ),
            "comment": "",
            "approved": True,
            "id": 14130219496,
            "thumbnails": {
                "250": "https://coverartarchive.org/release/x/250.jpg",
                "500": "https://coverartarchive.org/release/x/500.jpg",
                "1200": "https://coverartarchive.org/release/x/1200.jpg",
                "small": "https://coverartarchive.org/release/x/small.jpg",
                "large": "https://coverartarchive.org/release/x/large.jpg",
            },
        },
        {
            "types": ["Back"],
            "front": False,
            "back": True,
            "edit": 1000000,
            "image": (
                f"https://coverartarchive.org/release/{RELEASE_MBID}/1000000-back.jpg"
            ),
            "comment": "",
            "approved": True,
            "id": 14130219497,
            "thumbnails": {
                "250": "https://coverartarchive.org/release/y/250.jpg",
                "500": "https://coverartarchive.org/release/y/500.jpg",
                "1200": "https://coverartarchive.org/release/y/1200.jpg",
                "small": "https://coverartarchive.org/release/y/small.jpg",
                "large": "https://coverartarchive.org/release/y/large.jpg",
            },
        },
    ],
    "release": f"https://musicbrainz.org/release/{RELEASE_MBID}",
}

# Verbatim live /release-group/ payload (front only).
RELEASE_GROUP_PAYLOAD: dict[str, Any] = {
    "images": [
        {
            "types": ["Front"],
            "front": True,
            "back": False,
            "edit": 7044900,
            "image": (
                f"https://coverartarchive.org/release-group/{RG_MBID}/7044900-front.jpg"
            ),
            "comment": "",
            "approved": True,
            "id": 12345678901,
            "thumbnails": {
                "250": "https://coverartarchive.org/release-group/z/250.jpg",
                "500": "https://coverartarchive.org/release-group/z/500.jpg",
                "1200": "https://coverartarchive.org/release-group/z/1200.jpg",
                "small": "https://coverartarchive.org/release-group/z/small.jpg",
                "large": "https://coverartarchive.org/release-group/z/large.jpg",
            },
        },
    ],
    "release": f"https://musicbrainz.org/release-group/{RG_MBID}",
}


def _response(status_code: int = 200, payload: Any = None) -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


@pytest.fixture
def noop_log() -> Mock:
    return Mock()


@pytest.fixture
def no_cancel() -> Mock:
    return Mock(return_value=False)


@pytest.fixture
def ranked_one() -> list[RankedCandidate]:
    return [
        RankedCandidate(
            0,
            "https://example.com/front.jpg",
            "CAA front (approved)",
            1200,
            1200,
            1440000.0,
            1.0,
        )
    ]


class TestEndpoints:
    """URL construction, precedence and the shared request policy."""

    def test_release_endpoint_used_for_the_release_mbid(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        on_pick = Mock(return_value=b"CAA_RELEASE_BYTES")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            result = caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"CAA_RELEASE_BYTES"
        url = mock_http.get.call_args.args[0]
        assert url == f"https://coverartarchive.org/release/{RELEASE_MBID}"
        assert "/release-group/" not in url
        # Shared request policy: no shell/param smuggling, explicit timeout.
        assert mock_http.get.call_args.kwargs["timeout"] == CONFIG["REQUEST_TIMEOUT"]
        assert mock_http.get.call_args.kwargs["verify"] is True
        assert on_pick.call_args.args[2] == "Cover Art Archive"

    def test_release_group_endpoint_used_when_no_release_mbid(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        on_pick = Mock(return_value=b"CAA_GROUP_BYTES")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.return_value = _response(200, RELEASE_GROUP_PAYLOAD)
            result = caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid="",
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"CAA_GROUP_BYTES"
        assert (
            mock_http.get.call_args.args[0]
            == f"https://coverartarchive.org/release-group/{RG_MBID}"
        )

    def test_release_lookup_precedes_release_group_and_wins(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        """The exact release key is tried before the group fallback, and a
        successful pick short-circuits every later lookup."""
        on_pick = Mock(return_value=b"RELEASE_HIT")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            result = caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"RELEASE_HIT"
        assert mock_http.get.call_count == 1
        assert "/release/" in mock_http.get.call_args.args[0]

    def test_falls_through_to_release_group_after_release_404(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        on_pick = Mock(return_value=b"GROUP_HIT")
        responses = [
            _response(404, {"error": "Not Found"}),
            _response(200, RELEASE_GROUP_PAYLOAD),
        ]
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.side_effect = responses
            result = caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"GROUP_HIT"
        urls = [call.args[0] for call in mock_http.get.call_args_list]
        assert urls == [
            f"https://coverartarchive.org/release/{RELEASE_MBID}",
            f"https://coverartarchive.org/release-group/{RG_MBID}",
        ]

    def test_all_release_group_ids_are_tried_in_order(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        second = "b1a9c6d2-0e11-49f0-9c22-5f0b0c6b1111"
        on_pick = Mock(return_value=b"SECOND_GROUP_HIT")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.side_effect = [
                _response(404, None),
                _response(200, RELEASE_GROUP_PAYLOAD),
            ]
            result = caa.query(
                "A",
                "B",
                release_mbid="",
                mb_rg_ids=[RG_MBID, second],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"SECOND_GROUP_HIT"
        urls = [call.args[0] for call in mock_http.get.call_args_list]
        assert urls[-1] == f"https://coverartarchive.org/release-group/{second}"


class TestMisses:
    """404s, empty payloads and unusable ids are misses, never exceptions."""

    def test_no_ids_returns_none_without_any_request(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with patch.object(caa, "http") as mock_http:
            result = caa.query(
                "A",
                "B",
                release_mbid="",
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        mock_http.get.assert_not_called()
        on_pick.assert_not_called()
        assert any(
            "no MusicBrainz ids" in call.args[0] for call in noop_log.call_args_list
        )

    def test_404_on_every_lookup_returns_none_and_never_offers_a_pick(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank") as mock_filter,
        ):
            mock_http.get.return_value = _response(404, {"error": "Not Found"})
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        assert mock_http.get.call_count == 2
        on_pick.assert_not_called()
        mock_filter.assert_not_called()

    def test_release_with_no_images_falls_through_to_group(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        """A live 200 that carries an empty ``images`` list is a miss."""
        on_pick = Mock(return_value=b"GROUP_HIT")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.side_effect = [
                _response(200, {"images": [], "release": "x"}),
                _response(200, RELEASE_GROUP_PAYLOAD),
            ]
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"GROUP_HIT"

    def test_images_without_a_url_are_not_offered_as_candidates(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        payload = {
            "images": [{"types": ["Front"], "front": True, "approved": True}],
            "release": "x",
        }
        on_pick = Mock()
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank") as mock_filter,
        ):
            mock_http.get.return_value = _response(200, payload)
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        mock_filter.assert_not_called()
        on_pick.assert_not_called()

    def test_whitespace_only_mbid_is_skipped_without_a_request(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with patch.object(caa, "http") as mock_http:
            result = caa.query(
                "A",
                "B",
                release_mbid="   ",
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        mock_http.get.assert_not_called()

    def test_cancel_flag_stops_before_the_next_lookup(
        self, noop_log: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        """Cancelling after the first id must not issue the next request."""
        cancel = Mock(side_effect=[False, True])
        on_pick = Mock(return_value=None)
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=cancel,
                on_pick=on_pick,
            )

        assert result is None
        assert mock_http.get.call_count == 1

    def test_rejected_pick_continues_to_the_next_lookup(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        """on_pick returning None (user pressed Reject) falls through."""
        on_pick = Mock(return_value=None)
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.side_effect = [
                _response(200, RELEASE_PAYLOAD),
                _response(200, RELEASE_GROUP_PAYLOAD),
            ]
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        assert on_pick.call_count == 2


class TestCandidatePolicy:
    """Front-cover preference and the trusted-source filter contract."""

    def test_front_images_win_over_back_covers(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """A back cover is never offered when a Front exists — an album-cover
        sync embeds one cover, and a larger back image must not outrank it."""
        captured: list[list[dict[str, str]]] = []

        def fake_filter(raw_items, **_kwargs):
            captured.append(raw_items)
            return []

        on_pick = Mock()
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", side_effect=fake_filter),
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert len(captured) == 1
        titles = [item["title"] for item in captured[0]]
        assert titles == ["CAA front (approved)"]
        assert "front.jpg" in captured[0][0]["url"]
        assert all("back.jpg" not in item["url"] for item in captured[0])

    def test_untyped_images_are_used_when_no_front_exists(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        payload = {
            "images": [
                {
                    "types": [],
                    "front": False,
                    "approved": False,
                    "image": "https://coverartarchive.org/release/x/untyped.jpg",
                },
                {
                    "types": ["Medium"],
                    "front": False,
                    "approved": False,
                    "image": "https://coverartarchive.org/release/x/medium.jpg",
                },
            ],
            "release": "x",
        }
        captured: list[list[dict[str, str]]] = []

        def fake_filter(raw_items, **_kwargs):
            captured.append(raw_items)
            return []

        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", side_effect=fake_filter),
        ):
            mock_http.get.return_value = _response(200, payload)
            caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=Mock(),
            )

        titles = [item["title"] for item in captured[0]]
        # No Front type anywhere -> fall back to the untagged art rather than
        # returning nothing for a release that does have images.
        assert titles == ["CAA image (unapproved)", "CAA Medium (unapproved)"]

    def test_caa_is_trusted_and_forwards_the_guardrail_settings(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        """The MBID key is the trust evidence, so album-name matching is
        skipped — but the dimension/threshold settings still forward."""
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one) as mock_f,
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=Mock(return_value=b"X"),
                min_art_dimension=640,
                album_match_threshold=0.71,
            )

        kwargs = mock_f.call_args.kwargs
        assert kwargs["is_trusted_source"] is True
        assert kwargs["source_name"] == "Cover Art Archive"
        assert kwargs["query_album"] == "The Wall"
        assert kwargs["min_dimension"] == 640
        assert kwargs["match_threshold"] == 0.71

    def test_real_filter_accepts_a_live_shaped_front(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """End-to-end through the real filter_and_rank (dimensions stubbed):
        a CAA front must survive the guardrails without any name matching."""
        seen: list[RankedCandidate] = []

        def pick(candidates, artist, engine):
            seen.extend(candidates)
            return b"REAL_FILTER_BYTES"

        with (
            patch.object(caa, "http") as mock_http,
            patch(
                "album_art_sync.core.candidate_filter.get_image_dimensions",
                return_value=(1200, 1200),
            ),
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            result = caa.query(
                "Pink Floyd",
                "The Wall",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=pick,
            )

        assert result == b"REAL_FILTER_BYTES"
        assert [c.url for c in seen] == [
            f"https://coverartarchive.org/release/{RELEASE_MBID}/1000000-front.jpg"
        ]
        assert seen[0].match_score == 1.0

    def test_undersized_front_is_rejected_by_the_real_filter(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with (
            patch.object(caa, "http") as mock_http,
            patch(
                "album_art_sync.core.candidate_filter.get_image_dimensions",
                return_value=(250, 250),
            ),
        ):
            mock_http.get.return_value = _response(200, RELEASE_PAYLOAD)
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
                min_art_dimension=500,
            )

        assert result is None
        on_pick.assert_not_called()


class TestErrorHandling:
    """Transport failures are logged and skipped, never propagated."""

    @pytest.mark.parametrize(
        "exc",
        [
            requests.exceptions.SSLError("bad ssl"),
            requests.exceptions.Timeout("slow"),
            requests.exceptions.RequestException("boom"),
        ],
    )
    def test_transport_errors_fall_through(
        self, noop_log: Mock, no_cancel: Mock, exc: Exception
    ) -> None:
        on_pick = Mock()
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank") as mock_filter,
        ):
            mock_http.get.side_effect = exc
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        on_pick.assert_not_called()
        mock_filter.assert_not_called()

    def test_non_200_status_logs_and_falls_through(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        on_pick = Mock(return_value=b"GROUP_HIT")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.side_effect = [
                _response(500, {}),
                _response(200, RELEASE_GROUP_PAYLOAD),
            ]
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"GROUP_HIT"
        assert any("HTTP 500" in call.args[0] for call in noop_log.call_args_list)

    def test_malformed_json_is_a_miss_not_a_crash(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        resp = _response(200)
        resp.json.side_effect = ValueError("Expecting value")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank") as mock_filter,
        ):
            mock_http.get.side_effect = [resp, _response(404, None)]
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result is None
        on_pick.assert_not_called()
        mock_filter.assert_not_called()

    def test_non_dict_json_body_does_not_break_the_chain(
        self, noop_log: Mock, no_cancel: Mock, ranked_one: list[RankedCandidate]
    ) -> None:
        """A bare list body must not raise AttributeError out of the chain."""
        on_pick = Mock(return_value=b"GROUP_HIT")
        with (
            patch.object(caa, "http") as mock_http,
            patch.object(caa, "filter_and_rank", return_value=ranked_one),
        ):
            mock_http.get.side_effect = [
                _response(200, ["not", "an", "object"]),
                _response(200, RELEASE_GROUP_PAYLOAD),
            ]
            result = caa.query(
                "A",
                "B",
                release_mbid=RELEASE_MBID,
                mb_rg_ids=[RG_MBID],
                log=noop_log,
                cancel_flag=no_cancel,
                on_pick=on_pick,
            )

        assert result == b"GROUP_HIT"
