"""
tests/test_providers.py — provider base, registry, and LRCLIB client tests.

LRCLIB transport behaviour is exercised through mocked ``requests.get``
responses so the suite never touches the network.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import requests

from audio_suite_shared.exceptions import AudioSuiteError
from lyrics_manager.core.providers import (
    LyricProvider,
    LyricProviderError,
    LyricResult,
    get_provider,
    get_provider_names,
    register_provider,
)
from lyrics_manager.core.providers.lrclib import LRCLIBProvider
from lyrics_manager.core.providers.registry import _registry


class _FakeProvider(LyricProvider):
    name = "fake_test_provider"

    def search(self, artist, title, *, timeout=10.0):
        return LyricResult(provider_name=self.name, plain_lyrics="text")


@pytest.fixture
def fresh_registry():
    """Provide a clean registry and restore the original after the test."""
    snapshot = dict(_registry)
    _registry.clear()
    _registry.update(snapshot)
    try:
        yield _registry
    finally:
        _registry.clear()
        _registry.update(snapshot)


class TestLyricResult:
    def test_has_lyrics_synced(self):
        assert LyricResult(provider_name="x", synced_lyrics="[00:01.00]a").has_lyrics

    def test_has_lyrics_plain(self):
        assert LyricResult(provider_name="x", plain_lyrics="a\n").has_lyrics

    def test_has_lyrics_false_when_both_none(self):
        assert not LyricResult(provider_name="x").has_lyrics

    def test_frozen(self):
        result = LyricResult(provider_name="x")
        with pytest.raises(AttributeError):
            result.provider_name = "y"

    def test_appends_to_audio_suite_error_hierarchy(self):
        assert issubclass(LyricProviderError, AudioSuiteError)


@pytest.mark.usefixtures("fresh_registry")
class TestRegistry:
    def test_lrclib_registered_by_default(self):
        assert "lrclib" in get_provider_names()

    def test_get_provider_returns_fresh_instance(self):
        p1 = get_provider("lrclib")
        p2 = get_provider("lrclib")
        assert isinstance(p1, LRCLIBProvider)
        assert p1 is not p2

    def test_get_provider_unknown_raises(self):
        with pytest.raises(LyricProviderError, match="Unknown lyric provider"):
            get_provider("nope")

    def test_names_sorted(self):
        register_provider(_FakeProvider)
        assert get_provider_names() == sorted(get_provider_names())

    def test_register_duplicate_raises(self):
        with pytest.raises(ValueError, match="already registered"):
            register_provider(LRCLIBProvider)

    def test_register_empty_name_raises(self):
        class _NoName(LyricProvider):
            pass

        with pytest.raises(ValueError, match="no name"):
            register_provider(_NoName)

    def test_registered_provider_instantiated_on_get(self):
        register_provider(_FakeProvider)
        provider = get_provider("fake_test_provider")
        assert provider.name == "fake_test_provider"
        result = provider.search("Artist", "Title")
        assert result is not None
        assert result.has_lyrics
        assert result.plain_lyrics == "text"


class _FakeResponse:
    """Minimal requests response: status_code, content, and json()."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body

    @property
    def content(self) -> bytes:
        return self._body

    def json(self) -> object:
        return json.loads(self._body.decode("utf-8"))


class TestLRCLIBProvider:
    def _provider(self):
        return LRCLIBProvider(base_url="https://lrclib.test/api/get")

    def test_synced_and_plain_parsed(self):
        payload = {
            "trackName": "Song",
            "artistName": "Artist",
            "syncedLyrics": "[00:01.00]line\n",
            "plainLyrics": "line\n",
        }
        response = _FakeResponse(200, json.dumps(payload).encode("utf-8"))
        with patch("requests.get", return_value=response) as get:
            result = self._provider().search("Artist", "Song", timeout=3.0)
        get.assert_called_once()
        assert get.call_args.kwargs["timeout"] == 3.0
        assert result is not None
        assert result.synced_lyrics == "[00:01.00]line"
        assert result.plain_lyrics == "line"
        assert result.provider_name == "lrclib"

    def test_plain_only_payload(self):
        payload = {"plainLyrics": "just words\n"}
        with patch(
            "requests.get",
            return_value=_FakeResponse(200, json.dumps(payload).encode("utf-8")),
        ):
            result = self._provider().search("A", "T")
        assert result is not None
        assert result.synced_lyrics is None
        assert result.has_lyrics

    def test_404_returns_none(self):
        with patch("requests.get", return_value=_FakeResponse(404, b"{}")) as get:
            result = self._provider().search("A", "T")
        assert result is None
        get.assert_called_once()

    def test_permanent_status_raises_without_retry(self):
        with patch("requests.get", return_value=_FakeResponse(400, b"{}")) as get:
            with pytest.raises(LyricProviderError, match="HTTP 400"):
                self._provider().search("A", "T")
        get.assert_called_once()

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_transient_status_recovers_on_retry(self, status: int) -> None:
        body = json.dumps({"plainLyrics": "x"}).encode("utf-8")
        with (
            patch(
                "requests.get",
                side_effect=[_FakeResponse(status, b"{}"), _FakeResponse(200, body)],
            ) as get,
            patch("time.sleep") as sleep,
        ):
            result = self._provider().search("A", "T")
        assert result is not None
        assert result.has_lyrics
        assert get.call_count == 2
        assert sleep.call_count == 1
        assert sleep.call_args.args[0] == 1.0

    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    def test_transient_status_exhausts_retries(self, status: int) -> None:
        with (
            patch(
                "requests.get",
                return_value=_FakeResponse(status, b"{}"),
            ) as get,
            patch("time.sleep") as sleep,
        ):
            with pytest.raises(
                LyricProviderError,
                match=f"LRCLIB is busy \\(HTTP {status}\\).*after 3 attempts",
            ):
                self._provider().search("A", "T")
        assert get.call_count == 3
        assert [c.args[0] for c in sleep.call_args_list] == [1.0, 2.0]

    def test_transport_error_raises(self):
        with patch(
            "requests.get", side_effect=requests.exceptions.ConnectionError("refused")
        ):
            with pytest.raises(LyricProviderError, match="Could not reach LRCLIB"):
                self._provider().search("A", "T")

    def test_timeout_raises(self):
        with patch(
            "requests.get", side_effect=requests.exceptions.Timeout("timed out")
        ):
            with pytest.raises(LyricProviderError, match="Could not reach LRCLIB"):
                self._provider().search("A", "T")

    def test_malformed_json_raises(self):
        with patch("requests.get", return_value=_FakeResponse(200, b"not json")):
            with pytest.raises(LyricProviderError, match="unparseable"):
                self._provider().search("A", "T")

    def test_payload_without_text_returns_none(self):
        with patch(
            "requests.get",
            return_value=_FakeResponse(
                200, json.dumps({"trackName": "x"}).encode("utf-8")
            ),
        ):
            result = self._provider().search("A", "T")
        assert result is None

    def test_encoded_query(self):
        body = json.dumps({"plainLyrics": "x"}).encode("utf-8")
        with patch("requests.get", return_value=_FakeResponse(200, body)) as get:
            self._provider().search("AC/DC", "Highway to Hell & Back")
        params = get.call_args.kwargs["params"]
        assert params == {
            "artist_name": "AC/DC",
            "track_name": "Highway to Hell & Back",
        }
        assert get.call_args.kwargs["headers"]["User-Agent"].startswith(
            "AudioSuite-Pro"
        )
