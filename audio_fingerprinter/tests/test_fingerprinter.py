"""Tests for audio_fingerprinter.core.fingerprinter.

Changed in 1.4.0: locks the shipped-fpcalc fallback and its precedence below
--fpcalc, FPCALC and PATH.
"""

from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

import audio_fingerprinter.core.fingerprinter as fingerprinter
from audio_fingerprinter.core.exceptions import FingerprintToolError
from audio_fingerprinter.core.fingerprinter import (
    FPCALC_ENV_VAR,
    SHIPPED_FPCALC,
    FpcalcOutput,
    _parse_fpcalc_output,
    generate_fingerprint,
    resolve_fpcalc,
)


class TestParseFpcalcOutput:
    def test_valid_output(self):
        raw = "FILE=/music/track.mp3\nDURATION=120.5\nFINGERPRINT=ABC123\n"
        result = _parse_fpcalc_output(raw)
        assert isinstance(result, FpcalcOutput)
        assert result.duration == 120.5
        assert result.fingerprint == "ABC123"

    def test_missing_duration_raises(self):
        raw = "FINGERPRINT=ABC123\n"
        with pytest.raises(FingerprintToolError, match="no usable fingerprint"):
            _parse_fpcalc_output(raw)

    def test_missing_fingerprint_raises(self):
        raw = "DURATION=120.5\n"
        with pytest.raises(FingerprintToolError, match="no usable fingerprint"):
            _parse_fpcalc_output(raw)

    def test_empty_output_raises(self):
        with pytest.raises(FingerprintToolError, match="no usable fingerprint"):
            _parse_fpcalc_output("")

    def test_malformed_duration_raises(self):
        raw = "DURATION=not_a_number\nFINGERPRINT=ABC\n"
        with pytest.raises(FingerprintToolError, match="malformed DURATION"):
            _parse_fpcalc_output(raw)


class TestResolveFpcalc:
    def test_explicit_path_returned(self, fake_fpcalc: os.PathLike[str]) -> None:
        result = resolve_fpcalc(str(fake_fpcalc))
        assert os.path.isabs(result)

    def test_env_var_used(self, fake_fpcalc: os.PathLike[str], monkeypatch) -> None:
        monkeypatch.setenv(FPCALC_ENV_VAR, str(fake_fpcalc))
        result = resolve_fpcalc(None)
        assert os.path.isabs(result)

    def test_explicit_takes_priority_over_env(self, tmp_path, monkeypatch) -> None:
        exe_a = tmp_path / "a.exe"
        exe_b = tmp_path / "b.exe"
        exe_a.write_bytes(b"\x00")
        exe_b.write_bytes(b"\x00")
        monkeypatch.setenv(FPCALC_ENV_VAR, str(exe_b))
        result = resolve_fpcalc(str(exe_a))
        assert result == str(exe_a)

    def test_missing_raises(self, monkeypatch, tmp_path) -> None:
        monkeypatch.delenv(FPCALC_ENV_VAR, raising=False)
        monkeypatch.setattr(
            fingerprinter, "SHIPPED_FPCALC", tmp_path / "absent-fpcalc.exe"
        )
        with patch("shutil.which", return_value=None):
            with pytest.raises(FingerprintToolError, match="fpcalc was not found"):
                resolve_fpcalc(None)

    def test_explicit_nonexistent_checked_in_candidates(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.delenv(FPCALC_ENV_VAR, raising=False)
        monkeypatch.setattr(
            fingerprinter, "SHIPPED_FPCALC", tmp_path / "absent-fpcalc.exe"
        )
        with patch("shutil.which", return_value=None):
            with pytest.raises(FingerprintToolError):
                resolve_fpcalc("/nonexistent/fpcalc.exe")

    def test_the_checkout_ships_fpcalc(self) -> None:
        """The committed binary is what the fallback below relies on."""
        assert SHIPPED_FPCALC.is_file(), f"missing committed {SHIPPED_FPCALC}"

    def test_shipped_binary_used_when_path_and_env_are_empty(self, monkeypatch) -> None:
        """A plain checkout fingerprints without --fpcalc or a PATH entry."""
        monkeypatch.delenv(FPCALC_ENV_VAR, raising=False)
        with patch("shutil.which", return_value=None):
            assert resolve_fpcalc(None) == str(SHIPPED_FPCALC)

    def test_path_wins_over_the_shipped_copy(self, monkeypatch, tmp_path) -> None:
        """An intentional PATH install is still preferred to the bundled copy."""
        on_path = tmp_path / "fpcalc.exe"
        on_path.write_bytes(b"\x00")
        monkeypatch.delenv(FPCALC_ENV_VAR, raising=False)
        with patch("shutil.which", return_value=str(on_path)):
            assert resolve_fpcalc(None) == str(on_path)


class TestGenerateFingerprint:
    def test_calls_subprocess_correctly(self, fake_fpcalc: os.PathLike[str]) -> None:
        fake_stdout = "FILE=/music/track.mp3\nDURATION=90.0\nFINGERPRINT=FAKEFP\n"
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=fake_stdout, stderr=""
        )
        with patch(
            "audio_fingerprinter.core.fingerprinter.run_secure_subprocess",
            return_value=fake_result,
        ) as mock_run:
            fp = generate_fingerprint(
                "/music/track.mp3",
                fpcalc_path=str(fake_fpcalc),
                max_length=120,
            )
            assert fp.duration == 90.0
            assert fp.fingerprint == "FAKEFP"
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args.kwargs.get("capture_output") is True
            assert args.kwargs.get("check") is False
            assert args.kwargs.get("timeout") == 300

    def test_nonzero_exit_raises(self, fake_fpcalc: os.PathLike[str]) -> None:
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="bad file"
        )
        with patch(
            "audio_fingerprinter.core.fingerprinter.run_secure_subprocess",
            return_value=fake_result,
        ):
            with pytest.raises(FingerprintToolError, match="exit code 1"):
                generate_fingerprint("/bad/file.mp3", fpcalc_path=str(fake_fpcalc))

    def test_missing_output_fields_raises(self, fake_fpcalc: os.PathLike[str]) -> None:
        fake_result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="FILE=/x.mp3\n", stderr=""
        )
        with patch(
            "audio_fingerprinter.core.fingerprinter.run_secure_subprocess",
            return_value=fake_result,
        ):
            with pytest.raises(FingerprintToolError, match="no usable fingerprint"):
                generate_fingerprint("/x.mp3", fpcalc_path=str(fake_fpcalc))

    def test_timeout_passed_through(self, fake_fpcalc: os.PathLike[str]) -> None:
        with patch(
            "audio_fingerprinter.core.fingerprinter.run_secure_subprocess",
            side_effect=subprocess.TimeoutExpired(cmd="fpcalc", timeout=500),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                generate_fingerprint(
                    "/x.mp3", fpcalc_path=str(fake_fpcalc), max_length=500
                )
