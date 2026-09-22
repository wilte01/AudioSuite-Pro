"""Tests for audio_fingerprinter.core.acoustid_client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from audio_fingerprinter.core.acoustid_client import (
    ACOUSTID_LOOKUP_URL,
    AcoustidClient,
    resolve_best_match,
)
from audio_fingerprinter.core.exceptions import AcoustidApiError, AcoustidAuthError
from audio_fingerprinter.core.models import AcoustidRecording, LookupResult


def _make_response(status_code: int = 200, payload: dict | None = None) -> MagicMock:
    """Return a mock requests.Response with the given JSON payload."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    if payload is not None:
        resp.json.return_value = payload
    else:
        resp.json.return_value = {"status": "ok", "results": []}
    return resp


def _rec(
    title: str,
    artist: str = "Artist",
    score: float = 0.9,
    recording_id: str = "mb-1",
) -> AcoustidRecording:
    return AcoustidRecording(
        acoustid_id="a1",
        recording_id=recording_id,
        title=title,
        artist=artist,
        score=score,
        duration=218,
    )


class TestResolveBestMatch:
    def test_empty_recordings(self) -> None:
        best, ambiguous, tag_resolved = resolve_best_match((), "10cc", "Johnny")
        assert best is None
        assert ambiguous is False
        assert tag_resolved is False

    def test_single_candidate_is_not_ambiguous(self) -> None:
        rec = _rec("Song")
        best, ambiguous, tag_resolved = resolve_best_match((rec,), "", "")
        assert best == rec
        assert ambiguous is False
        assert tag_resolved is False

    def test_clearly_dominant_top_keeps_rank_order(self) -> None:
        top = _rec("Song", score=0.98)
        runner_up = _rec("Other", score=0.60)
        best, ambiguous, tag_resolved = resolve_best_match(
            (top, runner_up), "Other", "Other"
        )
        assert best == top
        assert ambiguous is False
        assert tag_resolved is False

    def test_near_tie_prefers_tag_consistent_runner_up(self) -> None:
        # Mirrors the real 10cc case: a remix built on the same recording
        # out-scores the original by a hair (0.984 vs 0.947).
        remix = _rec(
            "Ich geh in Flammen auf",
            artist="Rosenstolz",
            score=0.984,
            recording_id="mb-remix",
        )
        original = _rec(
            "Johnny, Don't Do It",
            artist="10cc",
            score=0.947,
            recording_id="mb-orig",
        )
        best, ambiguous, tag_resolved = resolve_best_match(
            (remix, original), "10cc", "Johnny, Don't Do It"
        )
        assert best == original
        assert ambiguous is True
        assert tag_resolved is True

    def test_near_tie_without_tag_match_keeps_top(self) -> None:
        top = _rec("Song", score=0.98)
        runner_up = _rec("Other", score=0.96)
        best, ambiguous, tag_resolved = resolve_best_match(
            (top, runner_up), "Unrelated", "Unrelated"
        )
        assert best == top
        assert ambiguous is True
        assert tag_resolved is False

    def test_near_tie_with_unknown_tags_keeps_top(self) -> None:
        top = _rec("Song", score=0.98)
        runner_up = _rec("Other", score=0.96)
        best, ambiguous, tag_resolved = resolve_best_match(
            (top, runner_up), "Unknown", "Unknown"
        )
        assert best == top
        assert ambiguous is True
        assert tag_resolved is False

    def test_tag_match_ignores_punctuation_and_case(self) -> None:
        top = _rec("Song", artist="X", score=0.98)
        runner_up = _rec("Johnny, Don\u2019t Do It", artist="10CC", score=0.96)
        best, ambiguous, tag_resolved = resolve_best_match(
            (top, runner_up), "10cc", "Johnny, Don't Do It"
        )
        assert best == runner_up
        assert tag_resolved is True

    def test_tag_match_outside_gap_is_not_considered(self) -> None:
        top = _rec("Song", score=0.98)
        far = _rec("Far", artist="10cc", score=0.8, recording_id="mb-far")
        best, ambiguous, tag_resolved = resolve_best_match((top, far), "10cc", "Far")
        assert best == top
        assert ambiguous is False
        assert tag_resolved is False


class TestAcoustidClientInit:
    def test_construction(self):
        client = AcoustidClient("my_api_key", min_score=0.6, requests_per_second=2.0)
        assert client._api_key == "my_api_key"
        assert client._min_score == 0.6


class TestAcostidClientLookup:
    def test_empty_results_returns_no_match(self):
        client = AcoustidClient("key")
        resp = _make_response(200, {"status": "ok", "results": []})
        with patch.object(client._session, "post", return_value=resp):
            result = client.lookup("abc123", 60)
        assert isinstance(result, LookupResult)
        assert result.status == "no results"
        assert result.best_match is None

    def test_match_above_threshold(self):
        resp_payload = {
            "status": "ok",
            "results": [
                {
                    "id": "acoustid_1",
                    "score": 0.95,
                    "recordings": [
                        {
                            "id": "mb_rec_1",
                            "title": "Song A",
                            "artists": [{"name": "Artist X", "joinphrase": ""}],
                            "duration": 60,
                        }
                    ],
                }
            ],
        }
        client = AcoustidClient("key", min_score=0.5)
        resp = _make_response(200, resp_payload)
        with patch.object(client._session, "post", return_value=resp):
            result = client.lookup("fingerprint", 60)
        assert result.status == "ok"
        best = result.best_match
        assert best is not None
        assert best.title == "Song A"
        assert best.artist == "Artist X"
        assert best.acoustid_id == "acoustid_1"
        assert best.recording_id == "mb_rec_1"
        assert best.score == 0.95

    def test_score_below_threshold_filtered(self):
        resp_payload = {
            "status": "ok",
            "results": [
                {
                    "id": "acoustid_1",
                    "score": 0.3,
                    "recordings": [
                        {"id": "mb_rec_1", "title": "Song", "duration": 200}
                    ],
                }
            ],
        }
        client = AcoustidClient("key", min_score=0.5)
        resp = _make_response(200, resp_payload)
        with patch.object(client._session, "post", return_value=resp):
            result = client.lookup("fp", 60)
        assert result.status == "no results"

    def test_401_raises_auth_error(self):
        client = AcoustidClient("key")
        resp = _make_response(401)
        with patch.object(client._session, "post", return_value=resp):
            with pytest.raises(AcoustidAuthError, match="HTTP 401"):
                client.lookup("fp", 60)

    def test_500_raises_api_error(self):
        client = AcoustidClient("key")
        resp = _make_response(500)
        with patch.object(client._session, "post", return_value=resp):
            with pytest.raises(AcoustidApiError, match="HTTP 500"):
                client.lookup("fp", 60)

    def test_400_surfaces_service_message(self):
        payload = {"status": "error", "error": {"message": "invalid fingerprint"}}
        client = AcoustidClient("key")
        resp = _make_response(400, payload)
        with patch.object(client._session, "post", return_value=resp):
            with pytest.raises(AcoustidApiError) as excinfo:
                client.lookup("fp", 60)
        assert "HTTP 400" in str(excinfo.value)
        assert "invalid fingerprint" in str(excinfo.value)
        assert excinfo.value.context["service_message"] == "invalid fingerprint"

    def test_400_non_json_body_bare_message(self):
        client = AcoustidClient("key")
        resp = _make_response(400, {"status": "error", "error": "bad stuff"})
        with patch.object(client._session, "post", return_value=resp):
            with pytest.raises(AcoustidApiError) as excinfo:
                client.lookup("fp", 60)
        assert "bad stuff" in str(excinfo.value)

    def test_400_invalid_api_key_raises_auth_error(self):
        payload = {
            "status": "error",
            "error": {"message": "invalid API key"},
        }
        client = AcoustidClient("key")
        resp = _make_response(400, payload)
        with patch.object(client._session, "post", return_value=resp):
            with pytest.raises(AcoustidAuthError) as excinfo:
                client.lookup("fp", 60)
        text = str(excinfo.value)
        assert "HTTP 400" in text
        assert "my-applications" in text
        assert excinfo.value.context["service_message"] == "invalid API key"

    def test_network_error_raises_api_error(self):
        client = AcoustidClient("key")
        with patch.object(
            client._session,
            "post",
            side_effect=requests.ConnectionError("network down"),
        ):
            with pytest.raises(AcoustidApiError, match="request failed"):
                client.lookup("fp", 60)

    def test_non_json_response_raises_api_error(self):
        client = AcoustidClient("key")
        resp = _make_response(200)
        resp.json.side_effect = ValueError("not json")
        with patch.object(client._session, "post", return_value=resp):
            with pytest.raises(AcoustidApiError, match="non-JSON"):
                client.lookup("fp", 60)

    def test_api_error_status_in_payload(self):
        resp_payload = {"status": "error", "error": "invalid api key"}
        client = AcoustidClient("key")
        resp = _make_response(200, resp_payload)
        with patch.object(client._session, "post", return_value=resp):
            result = client.lookup("fp", 60)
        assert result.status == "error"
        assert "invalid" in result.error.lower()

    def test_request_url_and_params(self):
        client = AcoustidClient("my_key", min_score=0.5)
        resp = _make_response(200, {"status": "ok", "results": []})
        with patch.object(client._session, "post", return_value=resp) as mock_post:
            client.lookup("fingerprint_str", 90)
        mock_post.assert_called_once_with(
            ACOUSTID_LOOKUP_URL,
            data={
                "client": "my_key",
                "format": "json",
                "fingerprint": "fingerprint_str",
                "duration": 90,
                "meta": "recordings releases releasegroups compress sources",
            },
            timeout=30,
        )

    def test_artists_joinphrase_concatenated(self):
        resp_payload = {
            "status": "ok",
            "results": [
                {
                    "id": "a1",
                    "score": 0.8,
                    "recordings": [
                        {
                            "id": "r1",
                            "title": "Feat",
                            "artists": [
                                {"name": "Band A", "joinphrase": " feat. "},
                                {"name": "Band B", "joinphrase": ""},
                            ],
                            "duration": 60,
                        }
                    ],
                }
            ],
        }
        client = AcoustidClient("key", min_score=0.5)
        resp = _make_response(200, resp_payload)
        with patch.object(client._session, "post", return_value=resp):
            result = client.lookup("fp", 60)
        best = result.best_match
        assert best is not None
        assert best.artist == "Band A feat. Band B"


class TestDurationConsistency:
    """Candidates whose length disagrees with the file are dropped."""

    def _lookup(self, recording_duration, file_duration=60, score=0.9):
        payload = {
            "status": "ok",
            "results": [
                {
                    "id": "a1",
                    "score": score,
                    "recordings": [
                        {
                            "id": "r1",
                            "title": "Candidate",
                            "duration": recording_duration,
                        }
                    ],
                }
            ],
        }
        client = AcoustidClient("key", min_score=0.5)
        resp = _make_response(200, payload)
        with patch.object(client._session, "post", return_value=resp):
            return client.lookup("fp", file_duration)

    def test_grossly_mismatched_duration_filtered(self):
        result = self._lookup(recording_duration=200, file_duration=60)
        assert result.status == "no results"
        assert result.best_match is None

    def test_close_duration_allowed(self):
        result = self._lookup(recording_duration=63, file_duration=60)
        assert result.status == "ok"
        assert result.best_match.score == 0.9

    def test_missing_recording_duration_allowed(self):
        result = self._lookup(recording_duration=None, file_duration=60)
        assert result.status == "ok"

    def test_tolerance_scales_for_long_tracks(self):
        result = self._lookup(recording_duration=520, file_duration=500)
        assert result.status == "ok"

    def test_long_track_gross_mismatch_filtered(self):
        result = self._lookup(recording_duration=560, file_duration=500)
        assert result.status == "no results"
