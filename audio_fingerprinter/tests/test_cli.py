"""Tests for audio_fingerprinter.cli.

Changed in 1.2.0: adds the ``--musicbrainz`` / ``--write-isrc`` option tests
(Sprint 2 Item 2.1) and the ``--submit-isrc`` tests, including the dry-run
payload the command prints (Sprint 2 Item 2.3).

Changed in 1.4.0: emits and locks the shared CLI JSON schema (PLAN D82).

Changed in 1.4.1: the fake run result declares ``fatal=False`` so the
``finish_run`` exit check reads a real value instead of a truthy MagicMock
attribute (PLAN D92).
"""

from __future__ import annotations

import hashlib
import json
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

import pytest
import requests
from click.testing import CliRunner, Result
from mutagen.id3 import TSRC
from mutagen.wave import WAVE

from audio_fingerprinter.cli import fingerprint
from audio_fingerprinter.core.musicbrainz_client import (
    ISRCSubmission,
    build_isrc_submission_xml,
)
from audio_suite_shared.cli_base import _Result
from audio_suite_shared.tag_helper_reader import read_isrcs


class TestFingerprintCommand:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(fingerprint, ["--help"])
        assert result.exit_code == 0
        assert "Chromaprint" in result.output or "fingerprint" in result.output.lower()

    def test_no_directory_shows_usage(self):
        runner = CliRunner()
        result = runner.invoke(fingerprint, [])
        assert result.exit_code == 0 or "Usage" in result.output

    def test_nonexistent_directory(self):
        runner = CliRunner()
        result = runner.invoke(fingerprint, ["--dir", "/nonexistent/path_12345"])
        assert (
            result.exit_code != 0
            or "does not exist" in result.output.lower()
            or "error" in result.output.lower()
        )


class TestAlbumModeFlags:
    """--album-mode / --album-min must reach FingerprintParams."""

    def _invoke(self, args: list[str]):
        runner = CliRunner()
        # ``fatal=False`` is load-bearing: ``finish_run`` reads it, and a
        # bare MagicMock answers every attribute truthily, which would exit 1.
        tool_result = MagicMock(
            processed=0,
            errors=0,
            duration_secs=0.0,
            extra={"counts": {}},
            fatal=False,
        )
        with (
            patch(
                "audio_fingerprinter.utils.api_key.load_api_key",
                return_value="k",
            ),
            patch(
                "audio_fingerprinter.cli._run_tool", return_value=tool_result
            ) as mock_tool,
            patch("audio_fingerprinter.cli.active_batch"),
        ):
            result = runner.invoke(fingerprint, args)
        params = mock_tool.call_args.kwargs.get("params") if mock_tool.called else None
        return result, params

    def test_album_mode_off_by_default(self, tmp_path):
        result, params = self._invoke([str(tmp_path)])
        assert result.exit_code == 0
        assert params is not None
        assert params.album_mode is False
        assert params.album_min == 3

    def test_album_mode_flag_sets_params(self, tmp_path):
        result, params = self._invoke(
            [str(tmp_path), "--album-mode", "--album-min", "2"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.album_mode is True
        assert params.album_min == 2

    def test_album_min_must_be_at_least_one(self, tmp_path):
        runner = CliRunner()
        with patch("audio_fingerprinter.cli._run_tool"):
            result = runner.invoke(
                fingerprint,
                [str(tmp_path), "--album-mode", "--album-min", "0"],
            )
        assert result.exit_code != 0


class TestMbidFlags:
    """--write-mbids / --mbid-region must reach FingerprintParams, and the
    opt-in must refuse to run without the AcoustID tag write it extends."""

    def _invoke(self, args: list[str]):
        runner = CliRunner()
        # ``fatal=False`` is load-bearing: ``finish_run`` reads it, and a
        # bare MagicMock answers every attribute truthily, which would exit 1.
        tool_result = MagicMock(
            processed=0,
            errors=0,
            duration_secs=0.0,
            extra={"counts": {}},
            fatal=False,
        )
        with (
            patch(
                "audio_fingerprinter.utils.api_key.load_api_key",
                return_value="k",
            ),
            patch(
                "audio_fingerprinter.cli._run_tool", return_value=tool_result
            ) as mock_tool,
            patch("audio_fingerprinter.cli.active_batch"),
        ):
            result = runner.invoke(fingerprint, args)
        params = mock_tool.call_args.kwargs.get("params") if mock_tool.called else None
        return result, params

    def test_write_mbids_off_by_default(self, tmp_path):
        result, params = self._invoke([str(tmp_path)])
        assert result.exit_code == 0
        assert params is not None
        assert params.write_mbids is False
        assert params.mbid_region == ""

    def test_write_mbids_flag_sets_params(self, tmp_path):
        result, params = self._invoke(
            [
                str(tmp_path),
                "--write-tags",
                "--write-mbids",
                "--mbid-region",
                "gb",
            ]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.write_mbids is True
        # Region is normalised to the ISO code's canonical upper case.
        assert params.mbid_region == "GB"

    def test_write_mbids_requires_write_tags(self, tmp_path):
        result, _params = self._invoke([str(tmp_path), "--write-mbids"])
        assert result.exit_code == 1
        assert "--write-tags" in result.output

    def test_no_write_mbids_flag(self, tmp_path):
        result, params = self._invoke(
            [str(tmp_path), "--write-tags", "--no-write-mbids"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.write_mbids is False


class TestMusicBrainzFlags:
    """--musicbrainz / --write-isrc: defaults, dependencies, and params."""

    def _invoke(self, args: list[str]):
        runner = CliRunner()
        # ``fatal=False`` is load-bearing: ``finish_run`` reads it, and a
        # bare MagicMock answers every attribute truthily, which would exit 1.
        tool_result = MagicMock(
            processed=0,
            errors=0,
            duration_secs=0.0,
            extra={"counts": {}},
            fatal=False,
        )
        with (
            patch(
                "audio_fingerprinter.utils.api_key.load_api_key",
                return_value="k",
            ),
            patch(
                "audio_fingerprinter.cli._run_tool", return_value=tool_result
            ) as mock_tool,
            patch("audio_fingerprinter.cli.active_batch"),
        ):
            result = runner.invoke(fingerprint, args)
        params = mock_tool.call_args.kwargs.get("params") if mock_tool.called else None
        return result, params

    def test_enrichment_off_by_default(self, tmp_path):
        result, params = self._invoke([str(tmp_path)])
        assert result.exit_code == 0
        assert params is not None
        # Off by default: MusicBrainz allows one request per second, so an
        # album run must not incur it unless the user asked.
        assert params.musicbrainz is False
        assert params.write_isrc is False

    def test_musicbrainz_flag_sets_params(self, tmp_path):
        result, params = self._invoke([str(tmp_path), "--musicbrainz"])
        assert result.exit_code == 0
        assert params is not None
        assert params.musicbrainz is True

    def test_no_musicbrainz_flag(self, tmp_path):
        result, params = self._invoke([str(tmp_path), "--no-musicbrainz"])
        assert result.exit_code == 0
        assert params is not None
        assert params.musicbrainz is False

    def test_write_isrc_flag_sets_params(self, tmp_path):
        result, params = self._invoke(
            [str(tmp_path), "--musicbrainz", "--write-tags", "--write-isrc"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.write_isrc is True

    def test_write_isrc_requires_musicbrainz(self, tmp_path):
        result, _params = self._invoke([str(tmp_path), "--write-tags", "--write-isrc"])
        assert result.exit_code == 1
        assert "--musicbrainz" in result.output

    def test_write_isrc_requires_write_tags(self, tmp_path):
        result, _params = self._invoke([str(tmp_path), "--musicbrainz", "--write-isrc"])
        assert result.exit_code == 1
        assert "--write-tags" in result.output

    def test_help_documents_both_flags(self):
        result = CliRunner().invoke(fingerprint, ["--help"])
        assert result.exit_code == 0
        assert "--musicbrainz" in result.output
        assert "--write-isrc" in result.output


class TestSubmitIsrcFlags:
    """``--submit-isrc``: guards, credentials, and the dry-run payload."""

    PREVIEW = (
        '<metadata xmlns="http://musicbrainz.org/ns/mmd-2.0#">\n'
        "  <recording-list>\n"
        "  </recording-list>\n"
        "</metadata>"
    )

    def _invoke(
        self,
        args: list[str],
        *,
        token: str = "tok",
        submission: dict[str, object] | None = None,
    ):
        runner = CliRunner()
        # A real collector, not a MagicMock: the CLI now serialises through
        # _Result.to_payload, which a mock cannot marshal.
        tool_result = _Result(extra={"counts": {}})
        if submission is not None:
            tool_result.extra["isrc_submission"] = submission
        with (
            patch(
                "audio_fingerprinter.utils.api_key.load_api_key",
                return_value="k",
            ),
            patch(
                "audio_fingerprinter.utils.musicbrainz_token.load_token",
                return_value=token,
            ),
            patch(
                "audio_fingerprinter.cli._run_tool", return_value=tool_result
            ) as mock_tool,
            patch("audio_fingerprinter.cli.active_batch"),
        ):
            result = runner.invoke(fingerprint, args)
        kwargs = mock_tool.call_args.kwargs if mock_tool.called else {}
        return result, kwargs.get("params"), kwargs.get("mb_auth"), mock_tool

    def test_off_by_default(self, tmp_path):
        result, params, auth, _tool = self._invoke([str(tmp_path)])
        assert result.exit_code == 0
        assert params is not None
        assert params.submit_isrc is False
        assert auth is None

    def test_flag_sets_params_and_passes_credentials(self, tmp_path):
        result, params, auth, _tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--submit-isrc"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.submit_isrc is True
        assert auth is not None and auth.token == "tok"

    def test_no_submit_flag(self, tmp_path):
        result, params, _auth, _tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--no-submit-isrc"]
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.submit_isrc is False

    def test_requires_musicbrainz(self, tmp_path):
        result, _params, _auth, _tool = self._invoke([str(tmp_path), "--submit-isrc"])
        assert result.exit_code == 1
        assert "--musicbrainz" in result.output

    def test_live_run_without_a_token_fails_before_processing(self, tmp_path):
        result, _params, _auth, tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--submit-isrc", "--live"],
            token="",
        )
        assert result.exit_code == 1
        assert "MUSICBRAINZ_TOKEN" in result.output
        assert not tool.called

    def test_dry_run_without_a_token_still_previews(self, tmp_path):
        # The preview is the whole point of a dry run; it needs no credential.
        result, params, _auth, _tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--submit-isrc", "--dry"],
            token="",
        )
        assert result.exit_code == 0
        assert params is not None
        assert params.submit_isrc is True

    def test_app_token_needs_a_username(self, tmp_path):
        result, _params, _auth, _tool = self._invoke(
            [
                str(tmp_path),
                "--musicbrainz",
                "--submit-isrc",
                "--mb-auth",
                "app-token",
            ]
        )
        assert result.exit_code == 1
        assert "--mb-user" in result.output

    def test_app_token_credentials_carry_the_username(self, tmp_path):
        result, _params, auth, _tool = self._invoke(
            [
                str(tmp_path),
                "--musicbrainz",
                "--submit-isrc",
                "--mb-auth",
                "app-token",
                "--mb-user",
                "alice",
            ]
        )
        assert result.exit_code == 0
        assert auth is not None
        assert auth.method == "app-token"
        assert auth.username == "alice"

    def test_dry_run_prints_the_exact_payload(self, tmp_path):
        result, _params, _auth, _tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--submit-isrc", "--dry"],
            submission={
                "mode": "preview",
                "status": "preview",
                "recordings": 1,
                "isrcs": 1,
                "url": "u",
                "reason": "",
                "xml": self.PREVIEW,
                "notes": [],
            },
        )
        assert result.exit_code == 0
        # Printed unprefixed so it can be captured and compared as-is.
        assert self.PREVIEW in result.output

    def test_live_reports_the_submission_status(self, tmp_path):
        result, _params, _auth, _tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--submit-isrc", "--live"],
            submission={
                "mode": "live",
                "status": "no auth",
                "recordings": 1,
                "isrcs": 1,
                "url": "u",
                "reason": "No MusicBrainz token is configured.",
                "xml": self.PREVIEW,
                "notes": [],
            },
        )
        assert result.exit_code == 0
        assert "no auth" in result.output
        assert "No MusicBrainz token is configured." in result.output

    def test_json_includes_the_submission_record(self, tmp_path):
        result, _params, _auth, _tool = self._invoke(
            [str(tmp_path), "--musicbrainz", "--submit-isrc", "--json"],
            submission={
                "mode": "live",
                "status": "ok",
                "recordings": 1,
                "isrcs": 1,
                "url": "u",
                "reason": "",
                "xml": self.PREVIEW,
                "notes": [],
            },
        )
        assert result.exit_code == 0
        assert '"isrc_submission"' in result.output
        assert '"status": "ok"' in result.output


class _StubHTTP:
    """Answer the run's HTTP from fixtures and record every request.

    Installed as ``HTTPAdapter.send``, the transport both the AcoustID and the
    MusicBrainz client reach through their own sessions, so nothing about the
    application's request building is stubbed and no socket is opened.
    """

    def __init__(
        self,
        recording_id: str,
        artist_id: str,
        release_group_id: str,
        *,
        post_status: int = 200,
        post_error: requests.RequestException | None = None,
    ) -> None:
        self.recording_id = recording_id
        self.artist_id = artist_id
        self.release_group_id = release_group_id
        self.post_status = post_status
        self.post_error = post_error
        self.requests: list[requests.PreparedRequest] = []

    def handle(self, request: requests.PreparedRequest) -> requests.Response:
        """Record the request and answer it, failing the POST when asked to."""
        self.requests.append(request)
        if request.method == "POST" and "musicbrainz.org" in str(request.url):
            if self.post_error is not None:
                raise self.post_error
            return self._response(
                request, {"message": "submission outcome"}, status_code=self.post_status
            )
        return self._response(request, self._payload_for(request))

    def posts_to_musicbrainz(self) -> list[requests.PreparedRequest]:
        """Every request aimed at writing to MusicBrainz, if any."""
        return [
            request
            for request in self.requests
            if request.method == "POST" and "musicbrainz.org" in str(request.url)
        ]

    def musicbrainz_lookups(self) -> list[requests.PreparedRequest]:
        """Every read issued against the MusicBrainz web service."""
        return [
            request
            for request in self.requests
            if request.method == "GET" and "musicbrainz.org/ws/2/" in str(request.url)
        ]

    def _payload_for(self, request: requests.PreparedRequest) -> dict[str, Any]:
        """Return the JSON body the live service would answer with."""
        if "acoustid.org" in str(request.url):
            # Echo the duration the client sent: the candidate must be
            # duration-consistent, and only the request knows the file's.
            body = request.body if isinstance(request.body, str) else ""
            duration = int(parse_qs(body).get("duration", ["0"])[0] or 0)
            return {
                "status": "ok",
                "results": [
                    {
                        "id": "a1b2c3d4",
                        "score": 0.97,
                        "recordings": [
                            {
                                "id": self.recording_id,
                                "title": "Track One",
                                "duration": duration,
                                "artists": [
                                    {
                                        "id": self.artist_id,
                                        "name": "The Testers",
                                        "joinphrase": "",
                                    }
                                ],
                                "releasegroups": [
                                    {
                                        "id": self.release_group_id,
                                        "type": "Album",
                                        "title": "Test Album",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        # The MusicBrainz recording lookup: no ISRCs registered yet, which is
        # the only state in which the file's own code is worth submitting.
        return {
            "id": self.recording_id,
            "title": "Track One",
            "isrcs": [],
            "artist-credit": [
                {
                    "name": "The Testers",
                    "artist": {"id": self.artist_id, "name": "The Testers"},
                    "joinphrase": "",
                }
            ],
            "releases": [],
        }

    @staticmethod
    def _response(
        request: requests.PreparedRequest,
        payload: dict[str, Any],
        *,
        status_code: int = 200,
    ) -> requests.Response:
        """Wrap a fixture payload in the requests object the clients parse."""
        response = requests.Response()
        response.status_code = status_code
        response.headers["Content-Type"] = "application/json"
        response._content = json.dumps(payload).encode("utf-8")
        response.url = str(request.url)
        response.request = request
        response.encoding = "utf-8"
        return response


RECORDING_ID = "8f3471b5-7e6a-48da-86a9-c1c07a0f47ae"
ARTIST_ID = "c5a7f9d2-1b3e-4a6f-9c8d-2e5b7a4c1d3f"
RELEASE_GROUP_ID = "2f1d6c88-9a4b-4f6e-8d21-0b7c3e5a9d41"
ISRC = "GBAYE0601498"


def _stub_http(
    *,
    post_status: int = 200,
    post_error: requests.RequestException | None = None,
) -> _StubHTTP:
    """A transport answering the happy-path fixtures, with POST knobs."""
    return _StubHTTP(
        RECORDING_ID,
        ARTIST_ID,
        RELEASE_GROUP_ID,
        post_status=post_status,
        post_error=post_error,
    )


def _tagged_wav(folder: Path, isrc: str = ISRC) -> Path:
    """Write a short WAV whose ID3 tags carry the ISRC a rip would."""
    path = folder / "track one.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(44100)
        handle.writeframes(b"\x00\x00" * 44100 * 3)
    audio = WAVE(str(path))
    audio.add_tags()
    assert audio.tags is not None
    audio.tags.add(TSRC(encoding=3, text=[isrc]))
    audio.save()
    return path


def _invoke_fingerprint(
    folder: Path,
    stub: _StubHTTP,
    *,
    live: bool = False,
    token: str = "",
) -> tuple[Result, _StubHTTP]:
    """Run the real command with only the transport and token store stubbed."""
    fpcalc = Path(__file__).resolve().parents[2] / "fpcalc.exe"
    assert fpcalc.is_file(), "the shipped fpcalc.exe is what makes this run"

    def send(
        adapter: requests.adapters.BaseAdapter,
        request: requests.PreparedRequest,
        **kwargs: Any,
    ) -> requests.Response:
        """Stand in for ``HTTPAdapter.send``; the adapter itself is unused."""
        return stub.handle(request)

    with (
        patch.object(requests.adapters.HTTPAdapter, "send", send),
        patch(
            "audio_fingerprinter.utils.musicbrainz_token.load_token",
            return_value=token,
        ),
        patch("audio_fingerprinter.cli.active_batch"),
    ):
        result = CliRunner().invoke(
            fingerprint,
            [
                str(folder),
                "--live" if live else "--dry",
                "--musicbrainz",
                "--submit-isrc",
                "--api-key",
                "stub-key",
                "--fpcalc",
                str(fpcalc),
            ],
        )
    return result, stub


class TestSubmitIsrcDryRunThroughTheCli:
    """The dry-run preview driven through the command users actually run.

    Only the transport is stubbed: the file is a real tagged WAV, fpcalc really
    fingerprints it, and the real AcoustID/MusicBrainz clients build the
    request.  The printed XML therefore derives from the file's own tag, and a
    dry run must leave MusicBrainz untouched.
    """

    def test_previews_the_payload_from_the_files_own_tag(self, tmp_path: Path) -> None:
        folder = tmp_path / "album"
        folder.mkdir()
        _tagged_wav(folder)

        result, stub = _invoke_fingerprint(folder, _stub_http())

        assert result.exit_code == 0, result.output
        # The code came from the file's TSRC tag and the recording from the
        # AcoustID match, not from anything the test handed the command.
        assert f'<isrc id="{ISRC}"/>' in result.output
        assert f'recording id="{RECORDING_ID}"' in result.output
        expected = build_isrc_submission_xml(
            [ISRCSubmission(recording_id=RECORDING_ID, isrcs=(ISRC,))]
        )
        assert expected in result.output
        assert "1 ISRC(s) for 1 recording(s)" in result.output
        # The enrichment really happened, so the "nothing new" filter ran.
        assert stub.musicbrainz_lookups(), "no MusicBrainz recording lookup was made"

    def test_dry_run_never_posts_to_musicbrainz(self, tmp_path: Path) -> None:
        folder = tmp_path / "album"
        folder.mkdir()
        _tagged_wav(folder)

        result, stub = _invoke_fingerprint(folder, _stub_http())

        assert result.exit_code == 0, result.output
        # There was something to send and it was previewed, so the absence of
        # a POST below is a decision, not an empty payload.
        assert f'<isrc id="{ISRC}"/>' in result.output
        assert stub.posts_to_musicbrainz() == []
        assert len([r for r in stub.requests if "acoustid.org" in str(r.url)]) == 1

    def test_the_wav_tag_survives_the_run(self, tmp_path: Path) -> None:
        folder = tmp_path / "album"
        folder.mkdir()
        path = _tagged_wav(folder)

        result, _stub = _invoke_fingerprint(folder, _stub_http())

        assert result.exit_code == 0, result.output
        # A dry run must not write tags either; the ISRC is the input here, so
        # it must still be the file's only ISRC and no AcoustID tag may appear.
        assert read_isrcs(str(path)) == (ISRC,)
        tags = WAVE(str(path)).tags
        assert tags is not None
        assert not [frame for frame in tags.keys() if "AcoustID" in frame]

    def test_live_posts_exactly_the_previewed_bytes(self, tmp_path: Path) -> None:
        """The claim the preview makes, checked where it matters: the wire."""
        folder = tmp_path / "album"
        folder.mkdir()
        _tagged_wav(folder)

        dry_result, _dry_stub = _invoke_fingerprint(folder, _stub_http())
        live_result, live_stub = _invoke_fingerprint(
            folder, _stub_http(), live=True, token="tok-1"
        )

        assert dry_result.exit_code == 0, dry_result.output
        assert live_result.exit_code == 0, live_result.output
        posts = live_stub.posts_to_musicbrainz()
        assert len(posts) == 1
        body = posts[0].body
        assert isinstance(body, bytes)
        # Byte for byte: what the dry run printed is what the POST carried.
        assert body.decode("utf-8") in dry_result.output
        assert posts[0].headers["Authorization"] == "Bearer tok-1"
        assert posts[0].headers["Content-Type"].startswith("application/xml")
        assert "/ws/2/recording/?client=" in str(posts[0].url)
        assert "ISRC submission: ok" in live_result.output


class TestSubmitIsrcFailuresThroughTheCli:
    """A live submission the service refuses, through the real command.

    Only the transport is stubbed; the payload, the credentials and the file
    are real.  These runs ask for no tag writes, so a refused submission must
    report its status and reason and leave every byte of the file alone.
    """

    def _run(self, tmp_path: Path, stub: _StubHTTP) -> tuple[Result, Path, str]:
        """Fingerprint one tagged WAV live, digesting the file first."""
        folder = tmp_path / "album"
        folder.mkdir()
        path = _tagged_wav(folder)
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        result, _ = _invoke_fingerprint(folder, stub, live=True, token="tok-1")
        return result, path, before

    @staticmethod
    def _assert_untouched(path: Path, before: str) -> None:
        """A refused submission must not rewrite the file it read."""
        assert hashlib.sha256(path.read_bytes()).hexdigest() == before
        assert read_isrcs(str(path)) == (ISRC,)
        tags = WAVE(str(path)).tags
        assert tags is not None
        assert not [frame for frame in tags.keys() if "AcoustID" in frame]

    def test_rejected_submission_reports_the_invalid_payload(
        self, tmp_path: Path
    ) -> None:
        stub = _stub_http(post_status=400)

        result, path, before = self._run(tmp_path, stub)

        assert result.exit_code == 0, result.output
        assert "ISRC submission: rejected" in result.output
        assert "HTTP 400" in result.output
        assert "check the ISRCs and recording ids" in result.output
        # One attempt only: a rejected payload must not be retried.
        assert len(stub.posts_to_musicbrainz()) == 1
        assert "Summary: 1 files" in result.output
        self._assert_untouched(path, before)

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_unauthorised_submission_names_the_scope(
        self, tmp_path: Path, status_code: int
    ) -> None:
        stub = _stub_http(post_status=status_code)

        result, path, before = self._run(tmp_path, stub)

        assert result.exit_code == 0, result.output
        assert "ISRC submission: not authorised" in result.output
        assert f"HTTP {status_code}" in result.output
        assert "submit_isrc scope" in result.output
        assert len(stub.posts_to_musicbrainz()) == 1
        self._assert_untouched(path, before)

    def test_offline_submission_reports_the_network_error(self, tmp_path: Path) -> None:
        stub = _stub_http(
            post_error=requests.ConnectionError("connection reset by peer")
        )

        result, path, before = self._run(tmp_path, stub)

        assert result.exit_code == 0, result.output
        assert "ISRC submission: offline" in result.output
        assert "Network error submitting to MusicBrainz" in result.output
        assert "connection reset by peer" in result.output
        # The transport failed once; it must not be hammered on the way out.
        assert len(stub.posts_to_musicbrainz()) == 1
        assert "Summary: 1 files" in result.output
        self._assert_untouched(path, before)
