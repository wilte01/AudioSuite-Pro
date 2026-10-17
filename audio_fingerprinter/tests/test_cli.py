"""Tests for audio_fingerprinter.cli.

Changed in 1.2.0: adds the ``--musicbrainz`` / ``--write-isrc`` option tests
(Sprint 2 Item 2.1) and the ``--submit-isrc`` tests, including the dry-run
payload the command prints (Sprint 2 Item 2.3).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from audio_fingerprinter.cli import fingerprint


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
        tool_result = MagicMock(
            processed=0, errors=0, duration_secs=0.0, extra={"counts": {}}
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
        tool_result = MagicMock(
            processed=0, errors=0, duration_secs=0.0, extra={"counts": {}}
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
        tool_result = MagicMock(
            processed=0, errors=0, duration_secs=0.0, extra={"counts": {}}
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
        tool_result = MagicMock(
            processed=0, errors=0, duration_secs=0.0, extra={"counts": {}}
        )
        if submission is not None:
            tool_result.extra["isrc_submission"] = submission
        # --json serialises the run summary; a MagicMock would not marshal.
        tool_result.to_dict.return_value = {}
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
        return result, kwargs.get("params"), kwargs.get("mb_auth"), tool_result

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
