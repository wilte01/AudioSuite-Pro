"""Tests for I1 — Robustness items (audit M23).

Covers the twelve sub-items:
  1. MutagenError fallback is an AudioSuiteError subclass
  2. SubprocessSecurityError is in the AudioSuiteError hierarchy
  3. run_parallel_processing catches TimeoutError and calls on_complete
  4. run_python_script bounded stdout read loop
  5. suite_config cross-process file lock
  6. batch_undo WAL mitigation (read paths documented)
  7. error_handler._is_debug reads env per call
  8. key_manager.is_encrypted_value rejects plain base64
  9. master_driver/app.py TclError logged (covered by compile gate)
  10. lyrics_manager raises AudioConfigurationError (covered by compile gate)
  11. AcoustID API key via env var, not argv
  12. fingerprinter uses time.monotonic (covered by compile gate)
"""

from __future__ import annotations

import base64
import os
import threading
from unittest.mock import MagicMock, patch

import pytest

# ── Sub-item 1: MutagenError fallback ─────────────────────────────────────


class TestMutagenErrorFallback:
    """The fallback MutagenError must be an AudioSuiteError subclass."""

    def test_mutagen_error_is_audio_suite_error(self) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError, MutagenError

        assert issubclass(MutagenError, AudioSuiteError)

    def test_mutagen_error_catchable_as_audio_suite_error(self) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError, MutagenError

        with pytest.raises(AudioSuiteError):
            raise MutagenError("test error")

    def test_mutagen_error_is_not_bare_exception(self) -> None:
        """The fallback must NOT be Exception itself (the old bug)."""
        from audio_suite_shared.exceptions import MutagenError

        assert MutagenError is not Exception


# ── Sub-item 2: SubprocessSecurityError hierarchy ─────────────────────────


class TestSubprocessSecurityErrorHierarchy:
    """SubprocessSecurityError must be in the AudioSuiteError tree."""

    def test_is_audio_suite_error(self) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        assert issubclass(SubprocessSecurityError, AudioSuiteError)

    def test_catchable_as_audio_suite_error(self) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        with pytest.raises(AudioSuiteError):
            raise SubprocessSecurityError("blocked")

    def test_still_catchable_as_subprocess_security_error(self) -> None:
        from audio_suite_shared.secure_subprocess import SubprocessSecurityError

        with pytest.raises(SubprocessSecurityError):
            raise SubprocessSecurityError("blocked")


# ── Sub-item 3: run_parallel_processing TimeoutError ──────────────────────


class TestParallelProcessingTimeout:
    """run_parallel_processing must catch TimeoutError and call on_complete."""

    def test_on_complete_called_on_timeout(self, tmp_path: object) -> None:
        import pathlib
        import time as _time

        from audio_suite_shared.file_processor_base import BaseFileProcessor

        processor = BaseFileProcessor(max_workers=1)

        on_complete = MagicMock()
        on_error = MagicMock()
        on_progress = MagicMock()

        d = pathlib.Path(tmp_path)  # type: ignore[arg-type]
        (d / "test.mp3").touch()

        def _slow_processor(**kw: object) -> None:
            _time.sleep(5)

        # Use a very short timeout so f.result() raises TimeoutError before
        # the slow worker finishes.  The ThreadPoolExecutor will still wait
        # for the worker on exit, so keep the sleep time reasonable.
        with patch("audio_suite_shared.file_processor_base.WORKER_TIMEOUT_SECS", 0.05):
            processor.run_parallel_processing(
                str(d),
                _slow_processor,
                on_progress,
                on_complete,
                on_error,
                extensions=(".mp3",),
            )

        on_complete.assert_called_once()
        call_kw = on_complete.call_args[1]
        assert call_kw["total"] == 1
        assert call_kw["errors"] >= 1


# ── Sub-item 4: run_python_script bounded read ────────────────────────────


class TestRunPythonScriptBoundedRead:
    """run_python_script must kill a hung child within the timeout."""

    def test_timeout_kills_hung_child(self, tmp_path: object) -> None:
        import pathlib
        import subprocess

        from audio_suite_shared.secure_subprocess import run_python_script

        d = pathlib.Path(tmp_path)  # type: ignore[arg-type]
        script = d / "hang.py"
        script.write_text("import time; time.sleep(9999)\n", encoding="utf-8")

        with pytest.raises(subprocess.TimeoutExpired):
            run_python_script(
                str(script),
                [],
                timeout=2,
                line_callback=lambda _: None,
            )


# ── Sub-item 5: suite_config file lock ────────────────────────────────────


class TestSuiteConfigFileLock:
    """suite_config save functions must use a cross-process file lock."""

    def test_lock_path_exists_after_save(self, tmp_path: object) -> None:
        """The lock file is created when a save runs."""
        import pathlib

        from audio_suite_shared import suite_config

        d = pathlib.Path(tmp_path)  # type: ignore[arg-type]
        lock_path = d / "test.json.lock"

        with patch.object(suite_config, "_LOCK_PATH", lock_path):
            with suite_config._file_lock():
                pass

        assert lock_path.exists()

    def test_concurrent_saves_do_not_corrupt(self, tmp_path: object) -> None:
        """Two threads saving different keys both persist."""
        import json
        import pathlib

        from audio_suite_shared import suite_config

        d = pathlib.Path(tmp_path)  # type: ignore[arg-type]
        config_path = d / "config.json"
        lock_path = d / "config.json.lock"

        # Write initial config
        config_path.write_text("{}", encoding="utf-8")

        with (
            patch.object(suite_config, "CONFIG_PATH", config_path),
            patch.object(suite_config, "_LOCK_PATH", lock_path),
        ):
            suite_config._invalidate_cache()

            barrier = threading.Barrier(2)

            def _save_key(key: str, value: str) -> None:
                barrier.wait(timeout=5)
                with suite_config._file_lock():
                    data = suite_config._load()
                    data[key] = value
                    suite_config._save(data)

            t1 = threading.Thread(target=_save_key, args=("alpha", "1"))
            t2 = threading.Thread(target=_save_key, args=("beta", "2"))
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

            result = json.loads(config_path.read_text(encoding="utf-8"))
            assert result["alpha"] == "1"
            assert result["beta"] == "2"


# ── Sub-item 7: error_handler._is_debug ───────────────────────────────────


class TestErrorHandlerDebugPerCall:
    """SecureErrorHandler must read AUDIOSUITE_DEBUG per call, not at import."""

    def test_debug_mode_changes_at_runtime(self) -> None:
        from audio_suite_shared.security.error_handler import SecureErrorHandler

        os.environ["AUDIOSUITE_DEBUG"] = "0"
        try:
            assert SecureErrorHandler._is_debug() is False
            os.environ["AUDIOSUITE_DEBUG"] = "1"
            assert SecureErrorHandler._is_debug() is True
        finally:
            os.environ.pop("AUDIOSUITE_DEBUG", None)

    def test_set_debug_mode_reflected_immediately(self) -> None:
        from audio_suite_shared.security.error_handler import SecureErrorHandler

        try:
            SecureErrorHandler.set_debug_mode(True)
            assert os.environ["AUDIOSUITE_DEBUG"] == "1"
            assert SecureErrorHandler._is_debug() is True
            SecureErrorHandler.set_debug_mode(False)
            assert SecureErrorHandler._is_debug() is False
        finally:
            os.environ.pop("AUDIOSUITE_DEBUG", None)


# ── Sub-item 8: key_manager.is_encrypted_value ────────────────────────────


class TestIsEncryptedValueGuard:
    """is_encrypted_value must reject plain base64 strings."""

    def test_plain_base64_rejected(self) -> None:
        from audio_suite_shared.security.key_manager import KeyManager

        # A 60-char base64 string that is NOT a Fernet token
        plain = base64.b64encode(b"x" * 50).decode()
        km = KeyManager.__new__(KeyManager)
        km._encryption_enabled = True
        assert km.is_encrypted_value(plain) is False

    def test_short_string_rejected(self) -> None:
        from audio_suite_shared.security.key_manager import KeyManager

        km = KeyManager.__new__(KeyManager)
        km._encryption_enabled = True
        assert km.is_encrypted_value("short") is False

    def test_empty_string_rejected(self) -> None:
        from audio_suite_shared.security.key_manager import KeyManager

        km = KeyManager.__new__(KeyManager)
        km._encryption_enabled = True
        assert km.is_encrypted_value("") is False

    def test_non_string_rejected(self) -> None:
        from audio_suite_shared.security.key_manager import KeyManager

        km = KeyManager.__new__(KeyManager)
        km._encryption_enabled = True
        assert km.is_encrypted_value(12345) is False

    def test_fernet_token_accepted(self) -> None:
        """A value produced by encrypt_string must be detected."""
        # Simulate what encrypt_string produces: base64(fernet_token)
        from cryptography.fernet import Fernet

        from audio_suite_shared.security.key_manager import KeyManager

        key = Fernet.generate_key()
        f = Fernet(key)
        fernet_token = f.encrypt(b"test secret")  # bytes, URL-safe base64
        double_encoded = base64.b64encode(fernet_token).decode()

        km = KeyManager.__new__(KeyManager)
        km._encryption_enabled = True
        assert km.is_encrypted_value(double_encoded) is True


# ── Sub-item 11: API key not in argv ──────────────────────────────────────


class TestApiKeyNotInArgv:
    """The fingerprinter args must not contain --api-key."""

    def test_fingerprinter_args_no_api_key(self) -> None:
        from master_driver.runner.arg_builder import build_enrich_args

        state = MagicMock()
        state.dir_path.get.return_value = "/music"
        state.clear_logs_var.get.return_value = False
        state.parallel_var.get.return_value = False
        state.fingerprinter_lookup.get.return_value = True
        state.fingerprinter_write_tags.get.return_value = False
        state.fingerprinter_write_mbids.get.return_value = False
        state.fingerprinter_threshold.get.return_value = 0.5
        state.fingerprinter_max_length.get.return_value = 120
        state.fingerprinter_fpcalc.get.return_value = ""
        state.fingerprinter_mbid_region.get.return_value = ""
        state.fingerprinter_api_key.get.return_value = "my_secret_key"

        specs = build_enrich_args(state)
        fp_spec = None
        for toggle, manifest, args in specs:
            if manifest.id == "fingerprinter":
                fp_spec = args
                break

        assert fp_spec is not None, "fingerprinter spec not found"
        assert "--api-key" not in fp_spec, (
            "--api-key must not appear in argv (exposes key to process listing)"
        )

    def test_fingerprinter_api_key_in_env(self) -> None:
        from master_driver.runner.arg_builder import get_fingerprinter_api_key_env

        state = MagicMock()
        state.fingerprinter_api_key.get.return_value = "my_secret_key"

        env = get_fingerprinter_api_key_env(state)
        assert "fingerprinter" in env
        assert env["fingerprinter"]["ACOUSTID_API_KEY"] == "my_secret_key"

    def test_fingerprinter_api_key_empty_returns_empty(self) -> None:
        from master_driver.runner.arg_builder import get_fingerprinter_api_key_env

        state = MagicMock()
        state.fingerprinter_api_key.get.return_value = ""

        env = get_fingerprinter_api_key_env(state)
        assert env == {}
