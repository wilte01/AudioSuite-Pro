"""
test_album_art_sync.py — Fully mocked pytest suite for album_art_sync.

Coverage:
    - utils/cli_args.py          : parse(), validate_args()
    - config/settings.py         : load_config(), save_config()
    - api/musicbrainz.py         : escape_lucene(), query()
    - api/deezer.py              : query()
    - api/itunes.py              : query()
    - api/fanart.py              : query() -- including SSL/timeout/generic
                                    RequestException/bare-Exception branches
    - api/source_resolver.py     : resolve() -- the CAA-first chain
                                    (release-mbid lookup, MusicBrainz id
                                    lookup, CAA release-group fallback,
                                    Fanart/Deezer/iTunes) including every
                                    cancel_flag() checkpoint in the chain
    - core/artwork_applier.py    : apply() -- including purge OSError
                                    swallowing, empty file list, and
                                    folder.jpg vs. embed-size dimensions
    - ui/picker_dialog.py        : show_threadsafe() thread bridge, AND the
                                    real _show() body: render() success/
                                    Timeout/RequestException/generic-Exception
                                    branches, </> nav clamping, ACCEPT/REJECT/
                                    close-without-choosing
    - app.py (AudioSuiteV6)      : _run_logic() end-to-end control flow
                                    (missing dir, no files, metadata failure,
                                    album-artist fallback, cancellation,
                                    Dry-Run/Update-Artwork/Live-Update mode
                                    mapping, result messages, log-file write,
                                    auto-end), plus _cancel_operation() and
                                    the start_thread() no-folder guard

All external I/O (network, filesystem, tkinter, audio tags, shared-library
functions) is mocked.  The suite is headless and requires no display.

Changed in 1.0.1: added an L3 regression asserting a per-file AudioSuiteError
from embed_artwork does not abort the album batch.
Changed in 2.1.3: the config tests patch ``settings.CONFIG_DIR`` instead of
passing a fake "script" path, and the class gains the three B1 locks: the GUI
and the pipeline resolve the same file, a legacy JSON + ``.key`` pair is
migrated without touching the originals, and no caller may pass an argument to
``load_config``/``save_config`` again (audit R-04,
``PLAN_audit_2026-10-24_remediation.md`` B1).
"""

from __future__ import annotations

import io
import sys
import threading
import types
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Path bootstrap — make the package importable without an editable install.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent.parent  # album_art_sync/../
sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Shared-library stubs — injected before any album_art_sync import so that
# missing audio_suite_shared does not block the import chain.
# ---------------------------------------------------------------------------


def _build_shared_stub() -> types.ModuleType:
    """Return a minimal audio_suite_shared stub tree."""
    shared = types.ModuleType("audio_suite_shared")

    # exceptions sub-module
    exc_mod = types.ModuleType("audio_suite_shared.exceptions")

    class AudioSuiteError(Exception):
        pass

    class AudioTagError(AudioSuiteError):
        pass

    class AudioPermissionError(AudioSuiteError):
        pass

    class AudioExternalToolError(AudioSuiteError):
        pass

    def map_to_audio_error(
        exc: Exception, context: Optional[dict] = None
    ) -> AudioSuiteError:
        return AudioSuiteError(str(exc))

    def user_message_for(exc: Exception) -> str:
        return str(exc)

    exc_mod.AudioSuiteError = AudioSuiteError
    exc_mod.AudioTagError = AudioTagError
    exc_mod.AudioPermissionError = AudioPermissionError
    exc_mod.AudioExternalToolError = AudioExternalToolError
    exc_mod.map_to_audio_error = map_to_audio_error
    exc_mod.user_message_for = user_message_for

    # security sub-modules
    security_mod = types.ModuleType("audio_suite_shared.security")
    key_mgr_mod = types.ModuleType("audio_suite_shared.security.key_manager")
    err_handler_mod = types.ModuleType("audio_suite_shared.security.error_handler")
    validator_mod = types.ModuleType("audio_suite_shared.security.input_validator")

    class KeyManager:
        def __init__(self, config_file: str) -> None:
            self._config_file = config_file

        def encrypt_config(self, cfg: dict) -> dict:
            return cfg

        def decrypt_config(self, cfg: dict) -> dict:
            return cfg

    class SecureErrorHandler:
        @staticmethod
        def handle_network_error(exc: Exception, service: str) -> str:
            return f"{service} network error: {exc}"

        @staticmethod
        def handle_api_error(exc: Exception, service: str) -> str:
            return f"{service} API error: {exc}"

        @staticmethod
        def handle_error(exc: Exception, context: str) -> str:
            return f"{context} error: {exc}"

    class InputValidator:
        @staticmethod
        def sanitize_api_input(value: str) -> str:
            # Reject empty or obviously invalid UUIDs; pass everything else.
            return value.strip() if value and value.strip() else ""

    key_mgr_mod.KeyManager = KeyManager
    err_handler_mod.SecureErrorHandler = SecureErrorHandler
    validator_mod.InputValidator = InputValidator

    # tag_helper sub-module
    tag_mod = types.ModuleType("audio_suite_shared.tag_helper")
    tag_mod.SUPPORTED_EXTENSIONS = (".mp3", ".flac", ".ogg", ".m4a", ".opus")
    tag_mod.read_artist_album = Mock(return_value=("Artist", "Album"))
    tag_mod.read_album_artist = Mock(return_value="")
    tag_mod.embed_artwork = Mock()

    # cli_dataclasses sub-module
    from dataclasses import dataclass

    cli_dc_mod = types.ModuleType("audio_suite_shared.cli_dataclasses")

    @dataclass
    class BaseCLIArgs:
        folder_path: str = ""
        live_mode: bool = False
        auto_start: bool = False
        auto_end: bool = False

    cli_dc_mod.BaseCLIArgs = BaseCLIArgs

    # Register all modules
    for name, mod in [
        ("audio_suite_shared", shared),
        ("audio_suite_shared.exceptions", exc_mod),
        ("audio_suite_shared.security", security_mod),
        ("audio_suite_shared.security.key_manager", key_mgr_mod),
        ("audio_suite_shared.security.error_handler", err_handler_mod),
        ("audio_suite_shared.security.input_validator", validator_mod),
        ("audio_suite_shared.tag_helper", tag_mod),
        ("audio_suite_shared.cli_dataclasses", cli_dc_mod),
    ]:
        sys.modules[name] = mod

    # Attach sub-modules as attributes (needed for `from audio_suite_shared import x`)
    shared.exceptions = exc_mod
    shared.security = security_mod
    return shared


def _ensure_shared_available() -> None:
    """
    Make audio_suite_shared importable for this test module.

    Tries the real package first. Only builds and installs the stub
    tree if the real audio_suite_shared is genuinely unavailable (e.g.
    an isolated CI sandbox without the editable install) -- never
    overwrites a real, already-importable audio_suite_shared with a
    stub, since that silently masks real bugs in the real package and
    poisons every test collected afterward in the same pytest session.
    """
    try:
        import audio_suite_shared  # noqa: F401

        return
    except ImportError:
        pass

    if "audio_suite_shared" in sys.modules:
        return

    _build_shared_stub()


_ensure_shared_available()

# ---------------------------------------------------------------------------
# Now safe to import album_art_sync sub-modules.
# ---------------------------------------------------------------------------
from album_art_sync.api import (  # noqa: E402
    caa,
    deezer,
    fanart,
    itunes,
    musicbrainz,
    source_resolver,
)
from album_art_sync.api.musicbrainz import escape_lucene  # noqa: E402
from album_art_sync.core import artwork_applier  # noqa: E402
from album_art_sync.core.ranker import RankedCandidate  # noqa: E402
from album_art_sync.utils.cli_args import ArtArgs, parse, validate_args  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_album_art_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Keep every test in this module away from the install's key file.

    The config path is canonical since 2.1.3, so one patch covers every caller
    in the package — ``AudioSuiteV6.__init__`` included. Without it a test that
    builds the app against a missing file would create a template (and a new
    key) inside the source tree.
    """
    from album_art_sync.config import settings

    isolated = tmp_path_factory.mktemp("album_art_config")
    monkeypatch.setattr(settings, "CONFIG_DIR", isolated, raising=False)
    monkeypatch.setattr(settings, "legacy_config_paths", lambda: [], raising=False)
    return isolated


def _make_test_candidate(
    index: int = 0,
    url: str = "",
    title: str = "",
    width: int = 600,
    height: int = 600,
) -> RankedCandidate:
    """Build a RankedCandidate for test assertions."""
    return RankedCandidate(
        index=index,
        url=url,
        title=title,
        width=width,
        height=height,
        score=float(width * height),
        match_score=1.0,
    )


# ===========================================================================
#  FIXTURES
# ===========================================================================


@pytest.fixture()
def noop_log() -> Mock:
    """A log callback that records calls but does nothing visible."""
    return Mock()


@pytest.fixture()
def no_cancel() -> Mock:
    """A cancel_flag that always returns False (operation not cancelled)."""
    return Mock(return_value=False)


@pytest.fixture()
def cancel_immediately() -> Mock:
    """A cancel_flag that returns True on the very first call."""
    return Mock(return_value=True)


@pytest.fixture()
def tiny_jpeg_bytes() -> bytes:
    """
    Minimal valid JPEG image (1×1 white pixel) as raw bytes.
    Used to exercise PIL paths in artwork_applier without network I/O.
    """
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 255, 255)).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture()
def square_jpeg_bytes() -> bytes:
    """800×800 JPEG for testing thumbnail rescaling paths."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (800, 800), color=(128, 64, 32)).save(buf, "JPEG")
    return buf.getvalue()


# ===========================================================================
#  1. cli_args — parse() and validate_args()
# ===========================================================================


class TestCliArgsParse:
    """Tests for parse() — argument extraction from sys.argv."""

    def test_no_arguments_returns_empty_args(self) -> None:
        result = parse(["script.py"])
        assert result.folder_path == ""
        assert result.live_mode is False
        assert result.auto_start is False
        assert result.auto_end is False
        assert result.embed_size == "800"
        assert result.purge is True

    def test_folder_path_captured(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path)])
        assert result.folder_path == str(tmp_path)

    def test_live_flag_sets_live_mode(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path), "--live"])
        assert result.live_mode is True

    def test_dry_flag_does_not_set_live_mode(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path), "--dry"])
        assert result.live_mode is False

    def test_start_flag_sets_auto_start(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path), "_", "--start"])
        assert result.auto_start is True

    def test_end_flag_sets_auto_end(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path), "_", "_", "_", "--end"])
        assert result.auto_end is True

    def test_no_purge_flag_disables_purge(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path), "--no-purge"])
        assert result.purge is False

    def test_custom_embed_size_captured(self, tmp_path: Path) -> None:
        result = parse(["script.py", str(tmp_path), "--embed-size", "1200"])
        assert result.embed_size == "1200"

    def test_missing_argv_falls_back_to_sys_argv(self, tmp_path: Path) -> None:
        with patch.object(sys, "argv", ["script.py", str(tmp_path)]):
            result = parse()
        assert result.folder_path == str(tmp_path)

    def test_invalid_folder_raises_system_exit(self) -> None:
        with pytest.raises(SystemExit):
            parse(["script.py", "/nonexistent/path/abc123"])

    def test_invalid_embed_size_string_raises_system_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            parse(["script.py", str(tmp_path), "--embed-size", "notanumber"])

    def test_embed_size_not_in_whitelist_raises_system_exit(
        self, tmp_path: Path
    ) -> None:
        """A numeric value that is not one of the four
        allowed sizes must be rejected."""
        with pytest.raises(SystemExit):
            parse(["script.py", str(tmp_path), "--embed-size", "700"])

    def test_embed_size_out_of_range_raises_system_exit(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            parse(["script.py", str(tmp_path), "--embed-size", "9999"])

    def test_embed_size_flag_without_value_keeps_default(self, tmp_path: Path) -> None:
        """--embed-size as the last token (no value following)
        must fall back to default."""
        result = parse(["script.py", str(tmp_path), "--embed-size"])
        assert result.embed_size == "800"


class TestValidateArgs:
    """Tests for validate_args() — error list generation."""

    def test_valid_args_returns_empty_list(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="800")
        assert validate_args(args) == []

    def test_nonexistent_folder_returns_error(self) -> None:
        args = ArtArgs(folder_path="/definitely/does/not/exist")
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_path_to_file_not_dir_returns_error(self, tmp_path: Path) -> None:
        tmp_file = tmp_path / "file.txt"
        tmp_file.write_text("x")
        args = ArtArgs(folder_path=str(tmp_file))
        errors = validate_args(args)
        assert any("not a directory" in e for e in errors)

    def test_non_numeric_embed_size_returns_error(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="abc")
        errors = validate_args(args)
        assert any("numeric" in e for e in errors)

    def test_embed_size_600_is_valid(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="600")
        assert validate_args(args) == []

    def test_embed_size_800_is_valid(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="800")
        assert validate_args(args) == []

    def test_embed_size_1000_is_valid(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="1000")
        assert validate_args(args) == []

    def test_embed_size_1200_is_valid(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="1200")
        assert validate_args(args) == []

    def test_embed_size_not_in_whitelist_returns_error(self, tmp_path: Path) -> None:
        """A numeric value outside the allowed set must produce an error."""
        args = ArtArgs(folder_path=str(tmp_path), embed_size="700")
        errors = validate_args(args)
        assert len(errors) == 1
        assert "one of" in errors[0]

    def test_embed_size_99_returns_error(self, tmp_path: Path) -> None:
        args = ArtArgs(folder_path=str(tmp_path), embed_size="99")
        errors = validate_args(args)
        assert len(errors) == 1

    def test_empty_folder_path_is_valid(self) -> None:
        """Empty folder_path means 'not provided yet' — not an error."""
        args = ArtArgs(folder_path="", embed_size="800")
        assert validate_args(args) == []


# ===========================================================================
#  2. config/settings — load_config() and save_config()
# ===========================================================================


class TestSettings:
    """Tests for load_config() and save_config() against one canonical file."""

    def _import_settings(self):
        from album_art_sync.config import settings

        return settings

    @pytest.fixture(autouse=True)
    def _isolated_config_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Point the module at a temp directory; never the live install."""
        settings = self._import_settings()
        # ``raising=False`` keeps the fixture usable against the pre-2.1.3
        # module: without it the setup error would mask whether the assertions
        # themselves can detect the split.
        monkeypatch.setattr(settings, "CONFIG_DIR", tmp_path, raising=False)
        monkeypatch.setattr(settings, "legacy_config_paths", lambda: [], raising=False)
        return tmp_path

    def test_load_config_returns_default_when_file_missing(
        self, tmp_path: Path
    ) -> None:
        settings = self._import_settings()
        result = settings.load_config()
        assert "fanart" in result
        assert "app_key" in result["fanart"]

    def test_load_config_creates_template_file_when_missing(
        self, tmp_path: Path
    ) -> None:
        settings = self._import_settings()
        settings.load_config()
        config_file = tmp_path / "album_art_config.json"
        assert config_file.exists()
        assert settings.config_path() == config_file

    def test_save_and_reload_round_trips_values(self, tmp_path: Path) -> None:
        settings = self._import_settings()
        payload = {"fanart": {"app_key": "TEST_KEY", "client_key": "TEST_CLIENT"}}
        settings.save_config(payload)
        reloaded = settings.load_config()
        assert reloaded["fanart"]["app_key"] == "TEST_KEY"
        assert reloaded["fanart"]["client_key"] == "TEST_CLIENT"

    def test_load_config_returns_default_on_corrupt_file(self, tmp_path: Path) -> None:
        settings = self._import_settings()
        config_file = tmp_path / "album_art_config.json"
        config_file.write_text("not valid json {{{")
        result = settings.load_config()
        # Should return the hardcoded default without raising
        assert "fanart" in result

    def test_gui_and_pipeline_resolve_the_same_config_file(
        self, tmp_path: Path
    ) -> None:
        """Both entry points read what one of them saved (audit R-04).

        Before 2.1.3 the GUI passed ``__file__`` from ``album_art_sync/app.py``
        and the pipeline passed ``__file__`` from ``album_art_sync/core/``, so
        this assertion failed: the pipeline read a different, empty file.
        """
        settings = self._import_settings()
        from album_art_sync import app as app_module
        from album_art_sync.core import pipeline

        payload = {"fanart": {"app_key": "GUI_KEY", "client_key": "GUI_CLIENT"}}
        settings.save_config(payload)

        # One resolver, no caller-derived path: both modules hold the same
        # function, so neither can point anywhere else.
        assert app_module.load_config is settings.load_config
        assert pipeline.load_config is settings.load_config
        assert settings.config_path() == tmp_path / "album_art_config.json"

        assert app_module.load_config() == payload
        assert pipeline.load_config() == payload

    def test_load_migrates_legacy_json_and_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A legacy pair is copied intact; the originals are left alone."""
        import json

        from audio_suite_shared.security.key_manager import KeyManager

        settings = self._import_settings()
        legacy_dir = tmp_path / "legacy_pkg"
        legacy_dir.mkdir()
        legacy = legacy_dir / "album_art_config.json"
        canonical_dir = tmp_path / "canonical"
        canonical_dir.mkdir()

        payload = {"fanart": {"app_key": "LEGACY_KEY", "client_key": "LEGACY_CLIENT"}}
        # Write a real encrypted pair, exactly as the old GUI left it behind.
        manager = KeyManager(str(legacy))
        legacy.write_text(
            json.dumps(manager.encrypt_config(payload)), encoding="utf-8-sig"
        )
        legacy_key = legacy.with_suffix(".key")
        assert legacy_key.is_file()
        legacy_before = (legacy.read_bytes(), legacy_key.read_bytes())

        monkeypatch.setattr(settings, "CONFIG_DIR", canonical_dir)
        monkeypatch.setattr(settings, "legacy_config_paths", lambda: [legacy])

        # The permission outcome below is POSIX-only (Windows hardens with
        # icacls), so the cross-platform assertion is that the migrated key
        # goes through the shared hardening. ``side_effect`` keeps the real
        # body, so both assertions describe the same run.
        with patch.object(
            KeyManager,
            "harden_key_file",
            autospec=True,
            side_effect=KeyManager.harden_key_file,
        ) as mock_harden:
            assert settings.load_config() == payload

        target = canonical_dir / "album_art_config.json"
        assert target.is_file()
        migrated_key = target.with_suffix(".key")
        assert migrated_key.is_file()
        assert mock_harden.call_count == 1
        assert mock_harden.call_args[0][0].config_path == str(target)
        # Migrating must not destroy the user's only copy.
        assert (legacy.read_bytes(), legacy_key.read_bytes()) == legacy_before

        if sys.platform != "win32":
            # copyfile does not carry permissions: without re-hardening, the
            # user-only 0600 key arrives readable by every local user.
            assert (migrated_key.stat().st_mode & 0o777) == 0o600

    def test_no_caller_derived_config_path_remains(self) -> None:
        """No module may pass a path to load_config()/save_config() again."""
        import ast

        settings = self._import_settings()
        package_root = Path(settings.__file__).resolve().parent.parent
        scanned: list[Path] = []
        offenders: list[str] = []

        for path in sorted(package_root.rglob("*.py")):
            if "tests" in path.relative_to(package_root).parts:
                continue
            scanned.append(path)
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in {"load_config", "save_config"}
                    and (node.args or node.keywords)
                ):
                    rel = path.relative_to(package_root).as_posix()
                    offenders.append(f"{rel}:{node.lineno}")

        # An empty scan would pass vacuously (plan D5): prove files were read.
        assert scanned, "no album_art_sync modules were scanned"
        assert not offenders, (
            "caller-derived config path must not return (plan B1):\n  "
            + "\n  ".join(offenders)
        )


# ===========================================================================
#  3. api/musicbrainz — escape_lucene() and query()
# ===========================================================================


class TestEscapeLucene:
    """Tests for the Lucene special-character escaper."""

    def test_plain_text_unchanged(self) -> None:
        assert escape_lucene("Pink Floyd") == "Pink Floyd"

    def test_empty_string_returns_empty(self) -> None:
        assert escape_lucene("") == ""

    def test_plus_sign_escaped(self) -> None:
        assert escape_lucene("A+B") == "A\\+B"

    def test_quote_escaped(self) -> None:
        assert escape_lucene('say "hello"') == 'say \\"hello\\"'

    def test_all_special_chars_escaped(self) -> None:
        # Every special char (except backslash, tested separately) must gain a prefix \
        specials = '+-&|!(){}[]^"~*?:/'
        result = escape_lucene(specials)
        for char in specials:
            assert f"\\{char}" in result

    def test_backslash_escaped(self) -> None:
        # Backslash must be doubled (pre-pass), not quadrupled
        assert escape_lucene("path\\to") == "path\\\\to"

    def test_colon_escaped(self) -> None:
        assert escape_lucene("key:value") == "key\\:value"

    def test_forward_slash_escaped(self) -> None:
        assert escape_lucene("AC/DC") == "AC\\/DC"

    def test_backslash_not_double_escaped(self) -> None:
        """Backslash pre-pass must not cause subsequent chars to be re-escaped."""
        result = escape_lucene("a+b\\c")
        # + should be \\+, backslash should be \\\\, no quadrupling
        assert result == "a\\+b\\\\c"


class TestMusicBrainzQuery:
    """Tests for musicbrainz.query() — network fully mocked."""

    _FAKE_RESPONSE = {
        "releases": [
            {"release-group": {"id": "uuid-1"}},
            {"release-group": {"id": "uuid-2"}},
        ]
    }

    def _make_mock_response(self, json_data: dict, status: int = 200) -> Mock:
        resp = Mock()
        resp.status_code = status
        resp.json.return_value = json_data
        resp.raise_for_status = Mock()
        return resp

    def test_returns_release_group_ids_on_success(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response(self._FAKE_RESPONSE)
            result = musicbrainz.query("Pink Floyd", "The Wall", noop_log, no_cancel)
        assert result == ["uuid-1", "uuid-2"]

    def test_returns_empty_list_when_no_releases(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response({"releases": []})
            result = musicbrainz.query("Unknown", "Unknown", noop_log, no_cancel)
        assert result == []

    def test_logs_found_count_on_success(self, noop_log: Mock, no_cancel: Mock) -> None:
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response(self._FAKE_RESPONSE)
            musicbrainz.query("Pink Floyd", "The Wall", noop_log, no_cancel)
        logged = " ".join(str(c) for c in noop_log.call_args_list)
        assert "2" in logged or "Found" in logged

    def test_returns_empty_on_timeout(self, noop_log: Mock, no_cancel: Mock) -> None:
        import requests

        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.side_effect = requests.Timeout()
            result = musicbrainz.query("X", "Y", noop_log, no_cancel)
        assert result == []

    def test_returns_empty_on_request_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        import requests

        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.side_effect = requests.RequestException("connection refused")
            result = musicbrainz.query("X", "Y", noop_log, no_cancel)
        assert result == []

    def test_returns_empty_on_unexpected_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.side_effect = ValueError("unexpected")
            result = musicbrainz.query("X", "Y", noop_log, no_cancel)
        assert result == []

    def test_respects_max_api_results_limit(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """Should cap results at CONFIG['MAX_API_RESULTS'] (default 5)."""
        many_releases = {
            "releases": [{"release-group": {"id": f"uuid-{i}"}} for i in range(20)]
        }
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response(many_releases)
            result = musicbrainz.query("X", "Y", noop_log, no_cancel)
        assert len(result) <= 5

    def test_releases_missing_release_group_key_skipped(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        data = {
            "releases": [{"title": "No RG key"}, {"release-group": {"id": "good-uuid"}}]
        }
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response(data)
            result = musicbrainz.query("X", "Y", noop_log, no_cancel)
        assert result == ["good-uuid"]

    def test_escapes_special_chars_in_query(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        with patch("album_art_sync.api.musicbrainz.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response({"releases": []})
            musicbrainz.query("AC/DC", 'Back in "Black"', noop_log, no_cancel)
        call_params = mock_http.get.call_args[1]["params"]["query"]
        # Slashes and quotes should be escaped
        assert "/" not in call_params.replace("\\/", "") or "\\/" in call_params


# ===========================================================================
#  4. api/deezer — query()
# ===========================================================================


class TestDeezerQuery:
    """Tests for deezer.query() — network fully mocked."""

    _FAKE_DATA = {
        "data": [
            {"cover_xl": "https://example.com/art1.jpg", "title": "Album One"},
            {"cover_xl": "https://example.com/art2.jpg", "title": "Album Two"},
        ]
    }

    def _make_mock_response(self, json_data: dict) -> Mock:
        resp = Mock()
        resp.json.return_value = json_data
        resp.raise_for_status = Mock()
        return resp

    def test_calls_on_pick_with_results_and_returns_bytes(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        expected_bytes = b"JPEG_DATA"
        on_pick = Mock(return_value=expected_bytes)
        with (
            patch("album_art_sync.api.deezer.http") as mock_http,
            patch(
                "album_art_sync.api.deezer.filter_and_rank",
                return_value=[
                    _make_test_candidate(
                        0, "https://example.com/art1.jpg", "Album One"
                    ),
                    _make_test_candidate(
                        1, "https://example.com/art2.jpg", "Album Two"
                    ),
                ],
            ),
        ):
            mock_http.get.return_value = self._make_mock_response(self._FAKE_DATA)
            result = deezer.query("Artist", "Album", noop_log, no_cancel, on_pick)
        assert result == expected_bytes
        on_pick.assert_called_once()
        items_arg = on_pick.call_args[0][0]
        assert len(items_arg) == 2
        assert items_arg[0].url == "https://example.com/art1.jpg"

    def test_returns_none_when_no_results(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with patch("album_art_sync.api.deezer.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response({"data": []})
            result = deezer.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None
        on_pick.assert_not_called()

    def test_returns_none_on_timeout(self, noop_log: Mock, no_cancel: Mock) -> None:
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.deezer.http") as mock_http:
            mock_http.get.side_effect = requests.Timeout()
            result = deezer.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None
        on_pick.assert_not_called()

    def test_returns_none_on_request_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.deezer.http") as mock_http:
            mock_http.get.side_effect = requests.RequestException("err")
            result = deezer.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None

    def test_returns_none_when_on_pick_returns_none(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=None)
        with (
            patch("album_art_sync.api.deezer.http") as mock_http,
            patch(
                "album_art_sync.api.deezer.filter_and_rank",
                return_value=[_make_test_candidate()],
            ),
        ):
            mock_http.get.return_value = self._make_mock_response(self._FAKE_DATA)
            result = deezer.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None

    def test_returns_none_on_unexpected_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with patch("album_art_sync.api.deezer.http") as mock_http:
            mock_http.get.side_effect = ValueError("bad json")
            result = deezer.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None


# ===========================================================================
#  5. api/itunes — query()
# ===========================================================================


class TestItunesQuery:
    """Tests for itunes.query() — network fully mocked."""

    _FAKE_DATA = {
        "results": [
            {
                "artworkUrl100": "https://is1-ssl.mzstatic.com/image/100x100bb.jpg",
                "collectionName": "Dark Side of the Moon",
            }
        ]
    }

    def _make_mock_response(self, json_data: dict) -> Mock:
        resp = Mock()
        resp.json.return_value = json_data
        resp.raise_for_status = Mock()
        return resp

    def test_calls_on_pick_with_upscaled_url(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        expected_bytes = b"ITUNES_IMG"
        on_pick = Mock(return_value=expected_bytes)
        with (
            patch("album_art_sync.api.itunes.http") as mock_http,
            patch(
                "album_art_sync.api.itunes.filter_and_rank",
                return_value=[
                    _make_test_candidate(
                        url="https://is1-ssl.mzstatic.com/image/1200x1200bb.jpg",
                        title="Dark Side of the Moon",
                    )
                ],
            ),
        ):
            mock_http.get.return_value = self._make_mock_response(self._FAKE_DATA)
            result = itunes.query(
                "Pink Floyd", "Dark Side", noop_log, no_cancel, on_pick
            )
        assert result == expected_bytes
        items_arg = on_pick.call_args[0][0]
        assert "1200x1200bb" in items_arg[0].url

    def test_returns_none_when_empty_results(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        with patch("album_art_sync.api.itunes.http") as mock_http:
            mock_http.get.return_value = self._make_mock_response({"results": []})
            result = itunes.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None
        on_pick.assert_not_called()

    def test_returns_none_on_timeout(self, noop_log: Mock, no_cancel: Mock) -> None:
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.itunes.http") as mock_http:
            mock_http.get.side_effect = requests.Timeout()
            result = itunes.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None

    def test_returns_none_on_request_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.itunes.http") as mock_http:
            mock_http.get.side_effect = requests.RequestException("network down")
            result = itunes.query("X", "Y", noop_log, no_cancel, on_pick)
        assert result is None

    def test_url_replacement_correct(self, noop_log: Mock, no_cancel: Mock) -> None:
        """100x100bb must be replaced with 1200x1200bb for high-res art."""
        on_pick = Mock(return_value=b"x")
        with (
            patch("album_art_sync.api.itunes.http") as mock_http,
            patch(
                "album_art_sync.api.itunes.filter_and_rank",
                return_value=[
                    _make_test_candidate(
                        url="https://is1-ssl.mzstatic.com/image/1200x1200bb.jpg",
                        title="Dark Side of the Moon",
                    )
                ],
            ),
        ):
            mock_http.get.return_value = self._make_mock_response(self._FAKE_DATA)
            itunes.query("X", "Y", noop_log, no_cancel, on_pick)
        url = on_pick.call_args[0][0][0].url
        assert "100x100bb" not in url
        assert "1200x1200bb" in url


# ===========================================================================
#  6. api/fanart — query()
# ===========================================================================


class TestFanartQuery:
    """Tests for fanart.query() — network fully mocked."""

    _FANART_CONFIG = {"app_key": "APP_KEY_ABC", "client_key": "CLIENT_KEY_XYZ"}
    _MB_IDS = ["rg-uuid-001", "rg-uuid-002"]

    _FAKE_DATA = {
        "albums": {
            "rg-uuid-001": {
                "albumcover": [
                    {"url": "https://fanart.tv/art1.jpg", "likes": "42"},
                    {"url": "https://fanart.tv/art2.jpg", "likes": "7"},
                ]
            }
        }
    }

    def _make_mock_response(self, json_data: dict, status: int = 200) -> Mock:
        resp = Mock()
        resp.status_code = status
        resp.json.return_value = json_data
        return resp

    def test_returns_bytes_on_success(self, noop_log: Mock, no_cancel: Mock) -> None:
        expected_bytes = b"FANART_IMG"
        on_pick = Mock(return_value=expected_bytes)
        with (
            patch("album_art_sync.api.fanart.http") as mock_http,
            patch(
                "album_art_sync.api.fanart.filter_and_rank",
                return_value=[
                    _make_test_candidate(
                        url="https://fanart.tv/art1.jpg",
                        title="Fanart (42 likes)",
                    )
                ],
            ),
        ):
            mock_http.get.return_value = self._make_mock_response(self._FAKE_DATA)
            result = fanart.query(
                "Artist",
                "Album",
                self._MB_IDS,
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        assert result == expected_bytes

    def test_returns_none_with_no_api_key(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        result = fanart.query(
            "Artist",
            "Album",
            self._MB_IDS,
            {"app_key": "", "client_key": ""},
            noop_log,
            no_cancel,
            on_pick,
        )
        assert result is None
        on_pick.assert_not_called()

    def test_returns_none_with_empty_mb_ids(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        result = fanart.query(
            "Artist", "Album", [], self._FANART_CONFIG, noop_log, no_cancel, on_pick
        )
        assert result is None
        on_pick.assert_not_called()

    def test_skips_id_with_404_status(self, noop_log: Mock, no_cancel: Mock) -> None:
        on_pick = Mock(return_value=None)
        resp_404 = self._make_mock_response({}, status=404)
        with patch("album_art_sync.api.fanart.http") as mock_http:
            mock_http.get.return_value = resp_404
            result = fanart.query(
                "Artist",
                "Album",
                self._MB_IDS,
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        assert result is None

    def test_returns_none_on_ssl_error(self, noop_log: Mock, no_cancel: Mock) -> None:
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.fanart.http") as mock_http:
            mock_http.get.side_effect = requests.exceptions.SSLError(
                "cert verify failed"
            )
            result = fanart.query(
                "Artist",
                "Album",
                self._MB_IDS,
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        assert result is None

    def test_returns_none_on_timeout(self, noop_log: Mock, no_cancel: Mock) -> None:
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.fanart.http") as mock_http:
            mock_http.get.side_effect = requests.exceptions.Timeout()
            result = fanart.query(
                "Artist",
                "Album",
                self._MB_IDS,
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        assert result is None

    def test_passes_likes_count_to_on_pick(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=b"x")
        with (
            patch("album_art_sync.api.fanart.http") as mock_http,
            patch(
                "album_art_sync.api.fanart.filter_and_rank",
                return_value=[
                    _make_test_candidate(
                        url="https://fanart.tv/art1.jpg",
                        title="Fanart (42 likes)",
                    )
                ],
            ),
        ):
            mock_http.get.return_value = self._make_mock_response(self._FAKE_DATA)
            fanart.query(
                "Artist",
                "Album",
                ["rg-uuid-001"],
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        items = on_pick.call_args[0][0]
        assert "42" in items[0].title

    def test_cancel_flag_checked_between_ids(self, noop_log: Mock) -> None:
        cancel_after_first = Mock(side_effect=[False, True])
        on_pick = Mock(return_value=None)
        resp = self._make_mock_response(
            {"albums": {"rg-uuid-001": {"albumcover": []}}}, status=200
        )
        with patch("album_art_sync.api.fanart.http") as mock_http:
            mock_http.get.return_value = resp
            fanart.query(
                "Artist",
                "Album",
                ["rg-uuid-001", "rg-uuid-002"],
                self._FANART_CONFIG,
                noop_log,
                cancel_after_first,
                on_pick,
            )
        # Should have aborted before processing second ID
        assert mock_http.get.call_count <= 1

    def test_returns_none_on_generic_request_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """Covers the plain requests.exceptions.RequestException branch,
        distinct from the SSLError/Timeout subclasses tested elsewhere."""
        import requests

        on_pick = Mock()
        with patch("album_art_sync.api.fanart.http") as mock_http:
            mock_http.get.side_effect = requests.exceptions.RequestException(
                "connection reset"
            )
            result = fanart.query(
                "Artist",
                "Album",
                self._MB_IDS,
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        assert result is None
        on_pick.assert_not_called()

    def test_returns_none_on_unexpected_exception(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """Covers the bare `except Exception` fallback (e.g. malformed JSON)."""
        on_pick = Mock()
        with patch("album_art_sync.api.fanart.http") as mock_http:
            mock_http.get.side_effect = ValueError("bad json")
            result = fanart.query(
                "Artist",
                "Album",
                self._MB_IDS,
                self._FANART_CONFIG,
                noop_log,
                no_cancel,
                on_pick,
            )
        assert result is None
        on_pick.assert_not_called()

    def test_invalid_mb_id_skipped_by_sanitizer(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock()
        result = fanart.query(
            "Artist",
            "Album",
            ["   "],  # whitespace-only → sanitized to ""
            self._FANART_CONFIG,
            noop_log,
            no_cancel,
            on_pick,
        )
        # Should log 'Invalid' and not call http at all
        assert result is None


# ===========================================================================
#  7. api/source_resolver — resolve()
# ===========================================================================


class TestSourceResolver:
    """Tests for the orchestrated fallback chain."""

    def test_returns_fanart_result_when_mb_ids_found(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=b"FANART")
        with (
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(fanart, "query", return_value=b"FANART"),
            patch.object(deezer, "query") as mock_deezer,
            patch.object(itunes, "query") as mock_itunes,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, on_pick
            )
        assert img == b"FANART"
        assert source == "Fanart.tv"
        # No release id on the files -> CAA is consulted by release group only.
        mock_caa.assert_called_once()
        assert mock_caa.call_args.kwargs["release_mbid"] == ""
        assert mock_caa.call_args.kwargs["mb_rg_ids"] == ["uuid-1"]
        mock_deezer.assert_not_called()
        mock_itunes.assert_not_called()

    def test_falls_through_to_deezer_when_fanart_fails(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=b"DEEZER")
        with (
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(caa, "query", return_value=None),
            patch.object(fanart, "query", return_value=None),
            patch.object(deezer, "query", return_value=b"DEEZER"),
            patch.object(itunes, "query") as mock_itunes,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, on_pick
            )
        assert img == b"DEEZER"
        assert source == "Deezer"
        mock_itunes.assert_not_called()

    def test_falls_through_to_itunes_as_last_resort(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=b"ITUNES")
        with (
            patch.object(musicbrainz, "query", return_value=[]),
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(fanart, "query", return_value=None),
            patch.object(deezer, "query", return_value=None),
            patch.object(itunes, "query", return_value=b"ITUNES"),
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, on_pick
            )
        assert img == b"ITUNES"
        assert source == "iTunes Store"
        # Without a release id or MB ids there is nothing CAA can key on.
        mock_caa.assert_not_called()

    def test_returns_none_none_when_all_sources_fail(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=None)
        with (
            patch.object(musicbrainz, "query", return_value=[]),
            patch.object(caa, "query", return_value=None),
            patch.object(fanart, "query", return_value=None),
            patch.object(deezer, "query", return_value=None),
            patch.object(itunes, "query", return_value=None),
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, on_pick
            )
        assert img is None
        assert source is None

    def test_returns_none_immediately_when_cancelled_after_mb(
        self, noop_log: Mock
    ) -> None:
        # cancel_flag returns True right after MB query completes
        cancel_sequence = Mock(side_effect=[True])
        on_pick = Mock()
        with (
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(fanart, "query") as mock_fanart,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, cancel_sequence, on_pick
            )
        assert img is None
        assert source is None
        mock_caa.assert_not_called()
        mock_fanart.assert_not_called()

    def test_skips_fanart_and_caa_when_no_mb_ids(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=b"DEEZER")
        with (
            patch.object(musicbrainz, "query", return_value=[]),
            patch.object(caa, "query") as mock_caa,
            patch.object(fanart, "query") as mock_fanart,
            patch.object(deezer, "query", return_value=b"DEEZER"),
            patch.object(itunes, "query", return_value=None),
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, on_pick
            )
        mock_fanart.assert_not_called()
        mock_caa.assert_not_called()
        assert source == "Deezer"

    def test_returns_none_when_cancelled_between_fanart_and_deezer(
        self, noop_log: Mock
    ) -> None:
        """The checkpoint after Fanart -- distinct from the ones after MB and
        after the CAA release-group fallback."""
        # Call order: after MB -> False, after CAA release-group -> False,
        # after Fanart -> True
        cancel_sequence = Mock(side_effect=[False, False, True])
        on_pick = Mock()
        with (
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(fanart, "query", return_value=None) as mock_fanart,
            patch.object(deezer, "query") as mock_deezer,
            patch.object(itunes, "query") as mock_itunes,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, cancel_sequence, on_pick
            )
        assert img is None
        assert source is None
        mock_caa.assert_called_once()
        mock_fanart.assert_called_once()
        mock_deezer.assert_not_called()
        mock_itunes.assert_not_called()

    def test_returns_none_when_cancelled_after_caa_release_group(
        self, noop_log: Mock
    ) -> None:
        """Cancelling on the CAA release-group checkpoint must stop the chain
        before Fanart.tv."""
        cancel_sequence = Mock(side_effect=[False, True])
        on_pick = Mock()
        with (
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(fanart, "query") as mock_fanart,
            patch.object(deezer, "query") as mock_deezer,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, cancel_sequence, on_pick
            )
        assert img is None
        assert source is None
        mock_caa.assert_called_once()
        mock_fanart.assert_not_called()
        mock_deezer.assert_not_called()

    def test_returns_none_when_cancelled_between_deezer_and_itunes(
        self, noop_log: Mock
    ) -> None:
        """The last cancel_flag() checkpoint sits after Deezer and before
        iTunes -- must be honoured even though Deezer already ran."""
        # No MB ids -> Fanart and CAA release-group branches skipped entirely.
        # Call order: after MB -> False, after Fanart block -> False,
        # after Deezer -> True
        cancel_sequence = Mock(side_effect=[False, False, True])
        on_pick = Mock()
        with (
            patch.object(musicbrainz, "query", return_value=[]),
            patch.object(caa, "query") as mock_caa,
            patch.object(fanart, "query") as mock_fanart,
            patch.object(deezer, "query", return_value=None) as mock_deezer,
            patch.object(itunes, "query") as mock_itunes,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, cancel_sequence, on_pick
            )
        assert img is None
        assert source is None
        mock_caa.assert_not_called()
        mock_fanart.assert_not_called()
        mock_deezer.assert_called_once()
        mock_itunes.assert_not_called()


class TestSourceResolverCaaFirst:
    """The Cover Art Archive lead: exact release id before any id lookup."""

    RELEASE_MBID = "db85c244-53e7-441c-bab0-52c9c0d27450"

    def test_release_mbid_hit_short_circuits_the_whole_chain(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        on_pick = Mock(return_value=b"CAA_RELEASE")
        with (
            patch.object(caa, "query", return_value=b"CAA_RELEASE") as mock_caa,
            patch.object(musicbrainz, "query") as mock_mb,
            patch.object(fanart, "query") as mock_fanart,
            patch.object(deezer, "query") as mock_deezer,
            patch.object(itunes, "query") as mock_itunes,
        ):
            img, source = source_resolver.resolve(
                "Artist",
                "Album",
                {},
                noop_log,
                no_cancel,
                on_pick,
                album_mbid=self.RELEASE_MBID,
            )
        assert img == b"CAA_RELEASE"
        assert source == "Cover Art Archive"
        mock_caa.assert_called_once()
        assert mock_caa.call_args.kwargs["release_mbid"] == self.RELEASE_MBID
        assert mock_caa.call_args.kwargs["mb_rg_ids"] == []
        mock_mb.assert_not_called()
        mock_fanart.assert_not_called()
        mock_deezer.assert_not_called()
        mock_itunes.assert_not_called()

    def test_release_group_hit_short_circuits_fanart_and_below(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """A CAA hit on the MB-derived release-group ids is a win in its own
        right -- it must stop the chain without reaching Fanart.tv."""
        on_pick = Mock(return_value=b"CAA_GROUP")
        with (
            patch.object(caa, "query", return_value=b"CAA_GROUP") as mock_caa,
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(fanart, "query") as mock_fanart,
            patch.object(deezer, "query") as mock_deezer,
            patch.object(itunes, "query") as mock_itunes,
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, on_pick
            )
        assert img == b"CAA_GROUP"
        assert source == "Cover Art Archive"
        mock_caa.assert_called_once()
        assert mock_caa.call_args.kwargs["mb_rg_ids"] == ["uuid-1"]
        mock_fanart.assert_not_called()
        mock_deezer.assert_not_called()
        mock_itunes.assert_not_called()

    def test_release_miss_falls_through_to_group_then_fanart(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """CAA is tried on the release id, then again on the MB-derived
        release-group ids, before Fanart.tv."""
        with (
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(musicbrainz, "query", return_value=["uuid-1"]),
            patch.object(fanart, "query", return_value=b"FANART") as mock_fanart,
        ):
            img, source = source_resolver.resolve(
                "Artist",
                "Album",
                {},
                noop_log,
                no_cancel,
                Mock(),
                album_mbid=self.RELEASE_MBID,
            )
        assert img == b"FANART"
        assert source == "Fanart.tv"
        assert mock_caa.call_count == 2
        assert mock_caa.call_args_list[0].kwargs["release_mbid"] == self.RELEASE_MBID
        assert mock_caa.call_args_list[1].kwargs["release_mbid"] == ""
        assert mock_caa.call_args_list[1].kwargs["mb_rg_ids"] == ["uuid-1"]
        mock_fanart.assert_called_once()

    def test_release_lookup_runs_before_the_musicbrainz_lookup(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        """With no CAA art to offer, the exact release key is still consulted
        before the MusicBrainz id lookup that feeds the group fallback."""
        order: list[str] = []

        def fake_caa(*_args: Any, **_kwargs: Any) -> None:
            order.append("caa")
            return None

        def fake_mb(*_args: Any, **_kwargs: Any) -> list[str]:
            order.append("musicbrainz")
            return []

        with (
            patch.object(caa, "query", side_effect=fake_caa),
            patch.object(musicbrainz, "query", side_effect=fake_mb),
            patch.object(deezer, "query", return_value=None),
            patch.object(itunes, "query", return_value=None),
        ):
            source_resolver.resolve(
                "Artist",
                "Album",
                {},
                noop_log,
                no_cancel,
                Mock(),
                album_mbid=self.RELEASE_MBID,
            )

        # Release lookup first; the MusicBrainz id lookup only afterwards.
        assert order == ["caa", "musicbrainz"]

    def test_cancelled_after_the_release_lookup_stops_the_chain(
        self, noop_log: Mock
    ) -> None:
        cancel_sequence = Mock(side_effect=[True])
        with (
            patch.object(caa, "query", return_value=None) as mock_caa,
            patch.object(musicbrainz, "query") as mock_mb,
        ):
            img, source = source_resolver.resolve(
                "Artist",
                "Album",
                {},
                noop_log,
                cancel_sequence,
                Mock(),
                album_mbid=self.RELEASE_MBID,
            )
        assert img is None
        assert source is None
        mock_caa.assert_called_once()
        mock_mb.assert_not_called()

    def test_no_caa_lookup_without_a_release_id_or_mb_ids(
        self, noop_log: Mock, no_cancel: Mock
    ) -> None:
        with (
            patch.object(caa, "query") as mock_caa,
            patch.object(musicbrainz, "query", return_value=[]),
            patch.object(fanart, "query") as mock_fanart,
            patch.object(deezer, "query", return_value=None),
            patch.object(itunes, "query", return_value=None),
        ):
            img, source = source_resolver.resolve(
                "Artist", "Album", {}, noop_log, no_cancel, Mock()
            )
        assert img is None
        assert source is None
        mock_caa.assert_not_called()
        mock_fanart.assert_not_called()


# ===========================================================================
#  8. core/artwork_applier — apply()
# ===========================================================================


class TestArtworkApplier:
    """Tests for apply() — PIL and embed_artwork fully mocked."""

    def _run_apply(
        self,
        *,
        tmp_path: Path,
        img_raw: bytes,
        mode: str = "Update Artwork",
        embed_size: int = 800,
        purge: bool = False,
        files: Optional[list[str]] = None,
        cancel_flag: Optional[Mock] = None,
        log: Optional[Mock] = None,
        on_file_progress: Optional[Mock] = None,
    ) -> bool:
        if files is None:
            files = ["track01.mp3", "track02.mp3"]
        if cancel_flag is None:
            cancel_flag = Mock(return_value=False)
        if log is None:
            log = Mock()
        if on_file_progress is None:
            on_file_progress = Mock()

        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            return artwork_applier.apply(
                path=str(tmp_path),
                files=files,
                img_raw=img_raw,
                mode=mode,
                embed_size=embed_size,
                purge=purge,
                log=log,
                cancel_flag=cancel_flag,
                on_file_progress=on_file_progress,
            )

    def test_returns_true_on_successful_live_update(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            result = self._run_apply(
                tmp_path=tmp_path,
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
            )
        assert result is True

    def test_returns_true_on_dry_run(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        result = self._run_apply(
            tmp_path=tmp_path,
            img_raw=square_jpeg_bytes,
            mode="Dry Run",
        )
        assert result is True

    def test_embed_artwork_called_for_each_file_in_live_mode(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        files = ["a.mp3", "b.mp3", "c.mp3"]
        with patch("album_art_sync.core.artwork_applier.embed_artwork") as mock_embed:
            artwork_applier.apply(
                path=str(tmp_path),
                files=files,
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert mock_embed.call_count == 3

    def test_embed_artwork_not_called_in_dry_run(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        dry_log = Mock()
        with patch("album_art_sync.core.artwork_applier.embed_artwork") as mock_embed:
            artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Dry Run",
                embed_size=800,
                purge=False,
                log=dry_log,
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        mock_embed.assert_not_called()
        dry_log.assert_any_call("  [Dry Run] Would embed artwork in 1 files")

    def test_folder_jpg_created_in_live_mode(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert (tmp_path / "folder.jpg").exists()

    def test_folder_jpg_not_created_in_dry_run(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        self._run_apply(
            tmp_path=tmp_path,
            img_raw=square_jpeg_bytes,
            mode="Dry Run",
        )
        assert not (tmp_path / "folder.jpg").exists()

    def test_cancel_flag_stops_processing_and_returns_false(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        # Cancel on the second file check
        cancel_sequence = Mock(side_effect=[False, True, True, True])
        with patch("album_art_sync.core.artwork_applier.embed_artwork") as mock_embed:
            result = artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3", "b.mp3", "c.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=cancel_sequence,
                on_file_progress=Mock(),
            )
        assert result is False
        assert mock_embed.call_count <= 1  # At most one file before cancel

    def test_purge_deletes_system_art_files(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        ghost = tmp_path / "albumartsmall.jpg"
        ghost.write_bytes(b"ghost")
        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=True,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert not ghost.exists()

    def test_purge_skipped_when_purge_false(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        ghost = tmp_path / "albumartsmall.jpg"
        ghost.write_bytes(b"ghost")
        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert ghost.exists()

    def test_returns_false_on_invalid_image_bytes(self, tmp_path: Path) -> None:
        result = self._run_apply(
            tmp_path=tmp_path,
            img_raw=b"NOT_VALID_IMAGE_DATA",
        )
        assert result is False

    def test_embed_failure_for_one_file_does_not_abort_others(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        """A per-file embed error must be logged and skipped, not fatal."""
        call_count = 0

        def embed_side_effect(path: str, data: bytes) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("permission denied")

        with patch(
            "album_art_sync.core.artwork_applier.embed_artwork",
            side_effect=embed_side_effect,
        ):
            result = artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3", "b.mp3", "c.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert result is True
        assert call_count == 3  # All files attempted despite first failure

    def test_audiosuite_error_for_one_file_does_not_abort_others(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        """L3 (G4.2): embed_artwork raises AudioSuiteError (via
        ``handle_audio_errors(reraise=True)``), which is neither OSError nor
        ValueError — the per-file catch must include it or one bad file aborts
        the whole album."""
        from audio_suite_shared.exceptions import AudioTagError

        attempted: list[str] = []

        def embed_side_effect(path: str, data: bytes) -> None:
            attempted.append(Path(path).name)
            if Path(path).name == "a.mp3":
                raise AudioTagError("corrupt tags")

        with patch(
            "album_art_sync.core.artwork_applier.embed_artwork",
            side_effect=embed_side_effect,
        ):
            result = artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3", "b.mp3", "c.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert result is True
        assert attempted == ["a.mp3", "b.mp3", "c.mp3"]

    def test_progress_callback_called_on_batch_boundaries(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        progress_calls: list[int] = []
        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            artwork_applier.apply(
                path=str(tmp_path),
                files=[f"track{i:02d}.mp3" for i in range(25)],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=lambda i: progress_calls.append(i),
            )
        assert len(progress_calls) > 0
        # Last call must be 25 (all files done)
        assert progress_calls[-1] == 25

    def test_purge_oserror_is_caught_logged_and_does_not_abort(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        """os.remove() failing during purge must be swallowed (logged as a
        warning) rather than propagating -- the run should still succeed."""
        ghost = tmp_path / "folder.jpg"
        ghost.write_bytes(b"ghost")
        log = Mock()
        with (
            patch("album_art_sync.core.artwork_applier.embed_artwork"),
            patch("os.remove", side_effect=OSError("permission denied")),
        ):
            result = artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=True,
                log=log,
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )
        assert result is True
        logged = " ".join(str(c) for c in log.call_args_list)
        assert "Couldn't remove" in logged

    def test_empty_files_list_returns_true_without_progress_calls(
        self, tmp_path: Path, square_jpeg_bytes: bytes
    ) -> None:
        progress = Mock()
        with patch("album_art_sync.core.artwork_applier.embed_artwork") as mock_embed:
            result = artwork_applier.apply(
                path=str(tmp_path),
                files=[],
                img_raw=square_jpeg_bytes,
                mode="Update Artwork",
                embed_size=800,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=progress,
            )
        assert result is True
        mock_embed.assert_not_called()
        progress.assert_not_called()

    def test_folder_jpg_dimension_matches_configured_folder_image_size(
        self, tmp_path: Path
    ) -> None:
        """folder.jpg must be thumbnailed to CONFIG['FOLDER_IMAGE_SIZE'],
        independent of the embed_size used for the tag image."""
        from PIL import Image

        from album_art_sync.config.settings import CONFIG

        large_img = io.BytesIO()
        Image.new("RGB", (3000, 3000), color=(5, 5, 5)).save(large_img, "JPEG")

        with patch("album_art_sync.core.artwork_applier.embed_artwork"):
            artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=large_img.getvalue(),
                mode="Update Artwork",
                embed_size=800,  # deliberately different from FOLDER_IMAGE_SIZE
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )

        saved = Image.open(tmp_path / "folder.jpg")
        folder_size = CONFIG["FOLDER_IMAGE_SIZE"]
        assert saved.width <= folder_size
        assert saved.height <= folder_size
        # Square 3000x3000 source -> thumbnail should hit the cap exactly.
        assert saved.width == folder_size
        assert saved.height == folder_size

    def test_embed_size_produces_thumbnail_at_correct_dimension(
        self, tmp_path: Path
    ) -> None:
        """Verify PIL thumbnail respects the embed_size parameter."""
        from PIL import Image

        large_img = io.BytesIO()
        Image.new("RGB", (2000, 2000), color=(10, 20, 30)).save(large_img, "JPEG")
        large_bytes = large_img.getvalue()

        saved_images: list[bytes] = []

        def capture_embed(path: str, data: bytes) -> None:
            saved_images.append(data)

        with patch(
            "album_art_sync.core.artwork_applier.embed_artwork",
            side_effect=capture_embed,
        ):
            artwork_applier.apply(
                path=str(tmp_path),
                files=["a.mp3"],
                img_raw=large_bytes,
                mode="Update Artwork",
                embed_size=300,
                purge=False,
                log=Mock(),
                cancel_flag=Mock(return_value=False),
                on_file_progress=Mock(),
            )

        assert len(saved_images) == 1
        embedded = Image.open(io.BytesIO(saved_images[0]))
        # PIL thumbnail maintains aspect ratio — both dims must be <= 300
        assert embedded.width <= 300
        assert embedded.height <= 300


# ===========================================================================
#  9. ui/picker_dialog — show_threadsafe() thread-safety contract
# ===========================================================================


class TestPickerDialogThreadSafety:
    """
    Tests for PickerDialog without a real Tk root.
    We mock root.after() and verify the threading.Event handshake.
    """

    def _make_dialog(self) -> Any:
        # Save originals for restoration in teardown_method
        self._saved_tkinter = sys.modules.get("tkinter")
        self._saved_styles = (
            sys.modules.get("audio_suite_shared.styles"),
            getattr(sys.modules.get("audio_suite_shared"), "styles", None),
        )

        # Stub tkinter, PIL.ImageTk, and shared styles before importing
        # picker_dialog — none of these exist in the headless sandbox.
        tk_stub = types.ModuleType("tkinter")
        tk_stub.Tk = MagicMock
        tk_stub.Toplevel = MagicMock
        tk_stub.Label = MagicMock
        tk_stub.Button = MagicMock
        tk_stub.Frame = MagicMock
        tk_stub.LEFT = "left"
        tk_stub.RIGHT = "right"
        tk_stub.TOP = "top"
        tk_stub.BOTTOM = "bottom"
        tk_stub.X = "x"
        tk_stub.Y = "y"
        tk_stub.BOTH = "both"
        tk_stub.NORMAL = "normal"
        tk_stub.DISABLED = "disabled"
        sys.modules["tkinter"] = tk_stub

        # Stub PIL.ImageTk (not available without a display)
        pil_mod = sys.modules.get("PIL")
        if pil_mod is None:
            pil_mod = types.ModuleType("PIL")
            sys.modules["PIL"] = pil_mod
        imagetk_mod = types.ModuleType("PIL.ImageTk")
        imagetk_mod.PhotoImage = MagicMock
        sys.modules["PIL.ImageTk"] = imagetk_mod
        pil_mod.ImageTk = imagetk_mod

        # Stub audio_suite_shared.styles
        styles_stub = types.ModuleType("audio_suite_shared.styles")
        styles_stub.BG_LIGHT = "#f0f0f0"
        styles_stub.BG_WHITE = "#ffffff"
        styles_stub.FG_MAIN = "#000000"
        styles_stub.FG_SUB = "#555555"
        styles_stub.FONT_TITLE = ("Arial", 14, "bold")
        styles_stub.FONT_LABEL = ("Arial", 10)
        styles_stub.FONT_LABEL_B = ("Arial", 10, "bold")
        styles_stub.FONT_BODY = ("Arial", 10)
        styles_stub.FONT_BUTTON = ("Arial", 10, "bold")
        styles_stub.FONT_HEADER = ("Arial", 14, "bold")
        styles_stub.FONT_MONO = ("Courier", 9)
        styles_stub.FONT_CAPTION = ("Arial", 8)
        styles_stub.COLOR_ERROR = "#cc0000"
        styles_stub.COLOR_SUCCESS = "#28a745"
        styles_stub.AMBER = "#d97706"
        styles_stub.TAB_FG = "#ffffff"
        styles_stub.SETTINGS_TAB_ACTIVE = "#444444"
        styles_stub.SETTINGS_TAB_INACTIVE = "#888888"
        styles_stub.PALETTES = {}
        styles_stub.get_main = lambda: "#0066cc"
        styles_stub.get_dark = lambda: "#5e3a8c"
        sys.modules["audio_suite_shared.styles"] = styles_stub
        sys.modules["audio_suite_shared"].styles = styles_stub

        # Force re-import with stubs in place
        for mod_name in list(sys.modules.keys()):
            if "picker_dialog" in mod_name:
                del sys.modules[mod_name]

        from album_art_sync.ui.picker_dialog import PickerDialog

        mock_root = MagicMock()
        dialog = PickerDialog(mock_root)
        return dialog, mock_root

    def teardown_method(self, method) -> None:
        """Restore stubbed modules so they don't leak to other tests."""
        if hasattr(self, "_saved_tkinter"):
            if self._saved_tkinter is not None:
                sys.modules["tkinter"] = self._saved_tkinter
            else:
                sys.modules.pop("tkinter", None)
        if hasattr(self, "_saved_styles"):
            saved_styles_mod, saved_styles_attr = self._saved_styles
            mod = sys.modules.get("audio_suite_shared")
            if saved_styles_mod is not None:
                sys.modules["audio_suite_shared.styles"] = saved_styles_mod
            else:
                sys.modules.pop("audio_suite_shared.styles", None)
            if mod is not None:
                if saved_styles_attr is not None:
                    mod.styles = saved_styles_attr
                else:
                    try:
                        delattr(mod, "styles")
                    except AttributeError:
                        pass

    def test_show_threadsafe_blocks_until_event_set(self) -> None:
        """
        show_threadsafe() must block the calling thread until _run_on_main
        completes.  We simulate this by having root.after() execute the
        callback synchronously in the mock.
        """
        dialog, mock_root = self._make_dialog()
        expected_bytes = b"CHOSEN_ART"

        def fake_after(delay: int, fn) -> None:
            # Simulate main-thread execution of the scheduled callback
            with patch.object(dialog, "_show", return_value=expected_bytes):
                fn()

        mock_root.after.side_effect = fake_after

        result = dialog.show_threadsafe(
            items=[
                _make_test_candidate(url="http://example.com/art.jpg", title="Test")
            ],
            artist="Artist",
            engine="TestEngine",
        )
        assert result == expected_bytes

    def test_show_threadsafe_returns_none_when_show_returns_none(self) -> None:
        dialog, mock_root = self._make_dialog()

        def fake_after(delay: int, fn) -> None:
            with patch.object(dialog, "_show", return_value=None):
                fn()

        mock_root.after.side_effect = fake_after

        result = dialog.show_threadsafe(
            items=[
                _make_test_candidate(url="http://example.com/art.jpg", title="Test")
            ],
            artist="Artist",
            engine="TestEngine",
        )
        assert result is None

    def test_show_threadsafe_schedules_on_main_thread(self) -> None:
        dialog, mock_root = self._make_dialog()
        done_event = threading.Event()

        def fake_after(delay: int, fn) -> None:
            with patch.object(dialog, "_show", return_value=b"x"):
                fn()
            done_event.set()

        mock_root.after.side_effect = fake_after

        thread = threading.Thread(
            target=dialog.show_threadsafe,
            kwargs={
                "items": [_make_test_candidate(url="u", title="t")],
                "artist": "A",
                "engine": "E",
            },
        )
        thread.start()
        thread.join(timeout=2.0)

        mock_root.after.assert_called_once()
        assert mock_root.after.call_args[0][0] == 0  # delay must be 0

    def test_show_threadsafe_passes_correct_args_to_show(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/img.jpg", title="Art 1")]
        captured: list = []

        def fake_after(delay: int, fn) -> None:
            with patch.object(
                dialog,
                "_show",
                side_effect=lambda i, a, e: captured.extend([i, a, e]) or b"x",
            ):
                fn()

        mock_root.after.side_effect = fake_after
        dialog.show_threadsafe(items=items, artist="Radiohead", engine="Deezer")

        assert captured[0] == items
        assert captured[1] == "Radiohead"
        assert captured[2] == "Deezer"


# ===========================================================================
#  10. ui/picker_dialog — _show() internals (render, nav, accept/reject)
# ===========================================================================


class _FakeVar:
    """Minimal stand-in for tk.BooleanVar that actually tracks state,
    unlike a bare MagicMock (whose .get() would return a truthy Mock)."""

    def __init__(self, value: Any = None) -> None:
        self._value = value

    def get(self) -> Any:
        return self._value

    def set(self, value: Any) -> None:
        self._value = value


class TestPickerDialogShowInternals:
    """
    Exercises the real body of PickerDialog._show(): image rendering via
    render(), the </>/nav index clamping, and the ACCEPT/REJECT command
    wiring -- none of which is touched by TestPickerDialogThreadSafety,
    which mocks _show() out entirely.

    Strategy: tk.Button is replaced with a factory that records each
    button's `command` callable keyed by its `text`, so we can invoke
    a "click" ourselves. `root.wait_window()` is where a real Tk event
    loop would block for a user click, so we hook its side_effect to
    fire the captured command(s) for the scenario under test -- mirroring
    the existing fake_after() pattern used for show_threadsafe() above.
    """

    def _make_dialog(self):
        # Save originals for restoration in teardown_method
        self._saved_tkinter = sys.modules.get("tkinter")
        self._saved_styles2 = (
            sys.modules.get("audio_suite_shared.styles"),
            getattr(sys.modules.get("audio_suite_shared"), "styles", None),
        )

        # ---- tkinter stub -----------------------------------------------
        tk_stub = types.ModuleType("tkinter")
        tk_stub.Tk = MagicMock
        # NB: plain `MagicMock` can't be used as a callable stub here --
        # calling it as tk.Toplevel(self._root) makes MagicMock.__init__
        # treat mock_root as a `spec` argument, which blows up because
        # you can't spec a Mock. Use a factory instead.
        tk_stub.Toplevel = lambda *a, **kw: MagicMock(name="Toplevel")
        tk_stub.Frame = lambda *a, **kw: MagicMock(name="Frame")
        tk_stub.BooleanVar = _FakeVar
        tk_stub.LEFT = "left"
        tk_stub.RIGHT = "right"
        tk_stub.TOP = "top"
        tk_stub.BOTTOM = "bottom"
        tk_stub.X = "x"
        tk_stub.Y = "y"
        tk_stub.BOTH = "both"
        tk_stub.NORMAL = "normal"
        tk_stub.DISABLED = "disabled"

        self._labels_created: list[MagicMock] = []

        def fake_label(*args, **kwargs):
            m = MagicMock(name="Label")
            self._labels_created.append(m)
            return m

        tk_stub.Label = fake_label

        self._buttons: dict[str, Any] = {}

        def fake_button(*args, **kwargs):
            m = MagicMock(name="Button")
            text = kwargs.get("text", "")
            self._buttons[text] = kwargs.get("command")
            return m

        tk_stub.Button = fake_button
        sys.modules["tkinter"] = tk_stub

        # ---- PIL.ImageTk stub ---------------------------------------------
        pil_mod = sys.modules.get("PIL")
        if pil_mod is None:
            pil_mod = types.ModuleType("PIL")
            sys.modules["PIL"] = pil_mod
        imagetk_mod = types.ModuleType("PIL.ImageTk")
        imagetk_mod.PhotoImage = MagicMock
        sys.modules["PIL.ImageTk"] = imagetk_mod
        pil_mod.ImageTk = imagetk_mod

        # ---- audio_suite_shared.styles stub --------------------------------
        styles_stub = types.ModuleType("audio_suite_shared.styles")
        styles_stub.BG_LIGHT = "#f0f0f0"
        styles_stub.BG_WHITE = "#ffffff"
        styles_stub.FG_MAIN = "#000000"
        styles_stub.FG_SUB = "#555555"
        styles_stub.FONT_TITLE = ("Arial", 14, "bold")
        styles_stub.FONT_LABEL = ("Arial", 10)
        styles_stub.FONT_LABEL_B = ("Arial", 10, "bold")
        styles_stub.FONT_BODY = ("Arial", 10)
        styles_stub.FONT_BUTTON = ("Arial", 10, "bold")
        styles_stub.FONT_HEADER = ("Arial", 14, "bold")
        styles_stub.FONT_MONO = ("Courier", 9)
        styles_stub.FONT_CAPTION = ("Arial", 8)
        styles_stub.COLOR_ERROR = "#cc0000"
        styles_stub.COLOR_SUCCESS = "#28a745"
        styles_stub.AMBER = "#d97706"
        styles_stub.TAB_FG = "#ffffff"
        styles_stub.SETTINGS_TAB_ACTIVE = "#444444"
        styles_stub.SETTINGS_TAB_INACTIVE = "#888888"
        styles_stub.PALETTES = {}
        styles_stub.get_main = lambda: "#0066cc"
        styles_stub.get_dark = lambda: "#5e3a8c"
        sys.modules["audio_suite_shared.styles"] = styles_stub
        sys.modules["audio_suite_shared"].styles = styles_stub

        for mod_name in list(sys.modules.keys()):
            if "picker_dialog" in mod_name:
                del sys.modules[mod_name]

        from album_art_sync.ui.picker_dialog import PickerDialog

        mock_root = MagicMock()
        dialog = PickerDialog(mock_root)
        return dialog, mock_root

    def teardown_method(self, method) -> None:
        """Restore stubbed modules so they don't leak to other tests."""
        if hasattr(self, "_saved_tkinter"):
            if self._saved_tkinter is not None:
                sys.modules["tkinter"] = self._saved_tkinter
            else:
                sys.modules.pop("tkinter", None)
        if hasattr(self, "_saved_styles2"):
            saved_styles_mod, saved_styles_attr = self._saved_styles2
            mod = sys.modules.get("audio_suite_shared")
            if saved_styles_mod is not None:
                sys.modules["audio_suite_shared.styles"] = saved_styles_mod
            else:
                sys.modules.pop("audio_suite_shared.styles", None)
            if mod is not None:
                if saved_styles_attr is not None:
                    mod.styles = saved_styles_attr
                else:
                    try:
                        delattr(mod, "styles")
                    except AttributeError:
                        pass

    @staticmethod
    def _jpeg_bytes(color: tuple) -> bytes:
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (10, 10), color=color).save(buf, "JPEG")
        return buf.getvalue()

    # ---- render() success / error branches --------------------------------

    def test_render_success_loads_image_and_updates_info_label(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]
        img_bytes = self._jpeg_bytes((10, 20, 30))

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.return_value = Mock(
                content=img_bytes, raise_for_status=Mock()
            )
            # wait_window fires nothing -> user closes without choosing
            mock_root.wait_window.side_effect = lambda win: None
            result = dialog._show(items, "Artist", "Deezer")

        assert result is None  # no choice made
        info_label = self._labels_created[1]
        info_text = info_label.config.call_args.kwargs["text"]
        assert "Cover A" in info_text
        assert "Deezer" in info_text
        assert "1/1" in info_text

    def test_render_timeout_shows_timeout_message(self) -> None:
        import requests

        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.side_effect = requests.Timeout()
            mock_root.wait_window.side_effect = lambda win: None
            dialog._show(items, "Artist", "Deezer")

        info_label = self._labels_created[1]
        info_text = info_label.config.call_args.kwargs["text"]
        assert "Timeout" in info_text

    def test_render_request_exception_shows_network_error(self) -> None:
        import requests

        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.side_effect = requests.RequestException("dns failure")
            mock_root.wait_window.side_effect = lambda win: None
            dialog._show(items, "Artist", "Deezer")

        info_label = self._labels_created[1]
        info_text = info_label.config.call_args.kwargs["text"]
        assert "Network error" in info_text

    def test_render_generic_exception_shows_error_message(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.return_value = Mock(
                content=b"NOT_A_REAL_IMAGE", raise_for_status=Mock()
            )
            mock_root.wait_window.side_effect = lambda win: None
            dialog._show(items, "Artist", "Deezer")

        info_label = self._labels_created[1]
        info_text = info_label.config.call_args.kwargs["text"]
        assert "Error" in info_text

    # ---- ACCEPT / REJECT / close-without-choosing --------------------------

    def test_accept_returns_currently_rendered_bytes(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]
        img_bytes = self._jpeg_bytes((1, 2, 3))

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.return_value = Mock(
                content=img_bytes, raise_for_status=Mock()
            )
            mock_root.wait_window.side_effect = lambda win: self._buttons["ACCEPT"]()
            result = dialog._show(items, "Artist", "Deezer")

        assert result == img_bytes

    def test_reject_returns_none(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]
        img_bytes = self._jpeg_bytes((1, 2, 3))

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.return_value = Mock(
                content=img_bytes, raise_for_status=Mock()
            )
            mock_root.wait_window.side_effect = lambda win: self._buttons["REJECT"]()
            result = dialog._show(items, "Artist", "Deezer")

        assert result is None

    def test_window_closed_without_choice_returns_none(self) -> None:
        """Closing the window (neither ACCEPT nor REJECT clicked) must
        behave the same as REJECT -- returns None, doesn't hang or raise."""
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]
        img_bytes = self._jpeg_bytes((1, 2, 3))

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.return_value = Mock(
                content=img_bytes, raise_for_status=Mock()
            )
            mock_root.wait_window.side_effect = lambda win: None  # window closed [X]
            result = dialog._show(items, "Artist", "Deezer")

        assert result is None

    # ---- navigation (</>) clamping and re-render ---------------------------

    def test_next_button_advances_index_and_rerenders(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [
            _make_test_candidate(url="http://x.com/a.jpg", title="Cover A"),
            _make_test_candidate(url="http://x.com/b.jpg", title="Cover B"),
        ]
        bytes_a = self._jpeg_bytes((10, 10, 10))
        bytes_b = self._jpeg_bytes((200, 200, 200))

        def fake_get(url: str, timeout: int):
            content = bytes_a if url.endswith("a.jpg") else bytes_b
            return Mock(content=content, raise_for_status=Mock())

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.side_effect = fake_get

            def on_wait(win):
                self._buttons[" > "]()  # advance to item 1 ("Cover B")
                self._buttons["ACCEPT"]()

            mock_root.wait_window.side_effect = on_wait
            result = dialog._show(items, "Artist", "Deezer")

        assert result == bytes_b
        info_label = self._labels_created[1]
        info_text = info_label.config.call_args.kwargs["text"]
        assert "Cover B" in info_text
        assert "2/2" in info_text

    def test_next_button_clamped_at_last_item(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [
            _make_test_candidate(url="http://x.com/a.jpg", title="Cover A"),
            _make_test_candidate(url="http://x.com/b.jpg", title="Cover B"),
        ]
        bytes_a = self._jpeg_bytes((10, 10, 10))
        bytes_b = self._jpeg_bytes((200, 200, 200))

        def fake_get(url: str, timeout: int):
            content = bytes_a if url.endswith("a.jpg") else bytes_b
            return Mock(content=content, raise_for_status=Mock())

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.side_effect = fake_get

            def on_wait(win):
                # Click "next" three times -- only one item to advance to.
                self._buttons[" > "]()
                self._buttons[" > "]()
                self._buttons[" > "]()
                self._buttons["ACCEPT"]()

            mock_root.wait_window.side_effect = on_wait
            result = dialog._show(items, "Artist", "Deezer")

        assert result == bytes_b  # stayed clamped on the last item, not out of range

    def test_prev_button_clamped_at_zero(self) -> None:
        dialog, mock_root = self._make_dialog()
        items = [_make_test_candidate(url="http://x.com/a.jpg", title="Cover A")]
        bytes_a = self._jpeg_bytes((10, 10, 10))

        with patch("album_art_sync.ui.picker_dialog.http") as mock_http:
            mock_http.get.return_value = Mock(content=bytes_a, raise_for_status=Mock())

            def on_wait(win):
                # Click "prev" from index 0 -- must not go negative / raise.
                self._buttons[" < "]()
                self._buttons["ACCEPT"]()

            mock_root.wait_window.side_effect = on_wait
            result = dialog._show(items, "Artist", "Deezer")

        assert result == bytes_a


# ===========================================================================
#  11. app.py — AudioSuiteV6 orchestration (_run_logic, _cancel_operation,
#      start_thread guard clause)
# ===========================================================================


def _build_full_tk_stub() -> types.ModuleType:
    """
    A tkinter stub broad enough to satisfy every eagerly-evaluated
    annotation and top-level reference across app.py, ui/main_tabs.py,
    and ui/picker_dialog.py at import time.

    None of the widget-building code (_build_ui / build_setup_tab / etc.)
    is exercised by these tests -- we bypass __init__ entirely and drive
    _run_logic() directly against a hand-built instance, so these stubs
    only need to make *importing* the modules succeed.
    """
    tk_stub = types.ModuleType("tkinter")
    tk_stub.Tk = MagicMock
    tk_stub.Toplevel = lambda *a, **kw: MagicMock(name="Toplevel")
    tk_stub.Frame = lambda *a, **kw: MagicMock(name="Frame")
    tk_stub.LabelFrame = lambda *a, **kw: MagicMock(name="LabelFrame")
    tk_stub.Label = lambda *a, **kw: MagicMock(name="Label")
    tk_stub.Button = lambda *a, **kw: MagicMock(name="Button")
    tk_stub.Entry = lambda *a, **kw: MagicMock(name="Entry")
    tk_stub.Checkbutton = lambda *a, **kw: MagicMock(name="Checkbutton")
    tk_stub.Listbox = MagicMock
    tk_stub.StringVar = MagicMock
    tk_stub.BooleanVar = MagicMock
    tk_stub.LEFT = "left"
    tk_stub.RIGHT = "right"
    tk_stub.TOP = "top"
    tk_stub.BOTTOM = "bottom"
    tk_stub.X = "x"
    tk_stub.Y = "y"
    tk_stub.BOTH = "both"
    tk_stub.SOLID = "solid"
    tk_stub.NORMAL = "normal"
    tk_stub.DISABLED = "disabled"
    tk_stub.END = "end"

    ttk_stub = types.ModuleType("tkinter.ttk")
    ttk_stub.Notebook = MagicMock
    ttk_stub.Progressbar = MagicMock
    ttk_stub.Combobox = MagicMock
    tk_stub.ttk = ttk_stub

    messagebox_stub = types.ModuleType("tkinter.messagebox")
    messagebox_stub.showinfo = Mock()
    tk_stub.messagebox = messagebox_stub

    filedialog_stub = types.ModuleType("tkinter.filedialog")
    filedialog_stub.askdirectory = Mock(return_value="")
    tk_stub.filedialog = filedialog_stub

    sys.modules["tkinter"] = tk_stub
    sys.modules["tkinter.ttk"] = ttk_stub
    sys.modules["tkinter.messagebox"] = messagebox_stub
    sys.modules["tkinter.filedialog"] = filedialog_stub
    return tk_stub


def _ensure_app_shared_stubs_available() -> None:
    """
    Extend the audio_suite_shared stub tree (built by
    _ensure_shared_available() above, or already real on a machine with
    the actual package installed) with the additional submodules app.py
    needs: platform_utils, styles, suite_config, app_bootstrap,
    cli_helpers, ui_helpers.

    Same non-clobbering discipline as _ensure_shared_available(): a
    submodule is only stubbed if it is genuinely not importable, so a
    real installed audio_suite_shared is never shadowed by a stub.
    """
    shared = sys.modules["audio_suite_shared"]

    def _stub_if_missing(dotted_name: str, build_fn) -> None:
        try:
            __import__(dotted_name)
            return
        except ImportError:
            pass
        if dotted_name in sys.modules:
            return
        mod = build_fn()
        sys.modules[dotted_name] = mod
        setattr(shared, dotted_name.rsplit(".", 1)[-1], mod)

    def _build_platform_utils() -> types.ModuleType:
        m = types.ModuleType("audio_suite_shared.platform_utils")
        m.open_path = Mock()
        return m

    def _build_styles() -> types.ModuleType:
        m = types.ModuleType("audio_suite_shared.styles")
        m.BG_LIGHT = "#f5f5f5"
        m.BG_WHITE = "#ffffff"
        m.FG_MAIN = "#000000"
        m.FONT_BODY = ("Arial", 10)
        m.FONT_BUTTON = ("Arial", 10, "bold")
        m.FONT_LABEL_B = ("Arial", 10, "bold")
        m.FONT_HEADER = ("Arial", 14, "bold")
        m.FONT_MONO = ("Courier", 10)
        m.get_main = lambda: "#0066cc"
        return m

    def _build_suite_config() -> types.ModuleType:
        m = types.ModuleType("audio_suite_shared.suite_config")
        m.load_last_directory = Mock(return_value="")
        return m

    def _build_app_bootstrap() -> types.ModuleType:
        m = types.ModuleType("audio_suite_shared.app_bootstrap")
        m.bootstrap_tool_app = Mock(return_value=(Mock(), Mock()))
        return m

    def _build_cli_helpers() -> types.ModuleType:
        m = types.ModuleType("audio_suite_shared.cli_helpers")

        class UniversalCLIHandler:
            def __init__(self, app: Any) -> None:
                self._app = app

            def apply_cli_args(
                self, parsed: Any, folder_var: Any, auto_start_func: Any
            ) -> bool:
                if parsed.folder_path:
                    folder_var.set(parsed.folder_path)
                return bool(getattr(parsed, "auto_start", False))

        m.UniversalCLIHandler = UniversalCLIHandler
        return m

    def _build_ui_helpers() -> types.ModuleType:
        m = types.ModuleType("audio_suite_shared.ui_helpers")

        class UIHelperMixin:
            def _browse_folder_standard(self, **kwargs: Any) -> None:
                pass

            def _open_help_standard(self, guide: str) -> None:
                pass

        m.UIHelperMixin = UIHelperMixin
        return m

    _stub_if_missing("audio_suite_shared.platform_utils", _build_platform_utils)
    _stub_if_missing("audio_suite_shared.styles", _build_styles)
    _stub_if_missing("audio_suite_shared.suite_config", _build_suite_config)
    _stub_if_missing("audio_suite_shared.app_bootstrap", _build_app_bootstrap)
    _stub_if_missing("audio_suite_shared.cli_helpers", _build_cli_helpers)
    _stub_if_missing("audio_suite_shared.ui_helpers", _build_ui_helpers)


class TestAppRunLogic:
    """
    Tests for AudioSuiteV6._run_logic() and two small guard-clause
    methods (_cancel_operation, start_thread).

    __init__ builds a full tkinter GUI, so instances are constructed
    via object.__new__() and populated with only the attributes
    _run_logic() actually touches -- the real, unmocked method body is
    then invoked directly. This mirrors the project's own "don't
    over-mock the thing you're testing" preference: everything that
    isn't tkinter/network/filesystem is exercised for real.
    """

    def _import_app_class(self) -> Any:
        self._saved_tkinter = sys.modules.get("tkinter")
        _build_full_tk_stub()

        pil_mod = sys.modules.get("PIL")
        if pil_mod is None:
            pil_mod = types.ModuleType("PIL")
            sys.modules["PIL"] = pil_mod
        imagetk_mod = types.ModuleType("PIL.ImageTk")
        imagetk_mod.PhotoImage = MagicMock
        sys.modules["PIL.ImageTk"] = imagetk_mod
        pil_mod.ImageTk = imagetk_mod

        _ensure_app_shared_stubs_available()

        for mod_name in list(sys.modules.keys()):
            if mod_name == "album_art_sync.app" or mod_name.startswith(
                "album_art_sync.ui"
            ):
                del sys.modules[mod_name]

        from album_art_sync.app import AudioSuiteV6

        return AudioSuiteV6

    def _make_bare_app(
        self, audio_suite_v6_cls: Any, folder: Path, mode: str = "Dry Run"
    ) -> Any:
        """Instance with __init__ skipped; only _run_logic()'s dependencies set."""
        app = object.__new__(audio_suite_v6_cls)
        # A root whose after() runs the callback immediately: the assertions
        # below then verify the main-thread helper actually performed the
        # widget write. Scheduling itself is asserted separately, with a
        # recording stub (test_worker_ui_writes_are_scheduled_on_main_thread).
        app.root = MagicMock()
        app.root.after.side_effect = lambda delay, func, *args: func(*args)
        app.folder_path = Mock()
        app.folder_path.get = Mock(return_value=str(folder))
        app.run_mode = Mock()
        app.run_mode.get = Mock(return_value=mode)
        app.size_var = Mock()
        app.size_var.get = Mock(return_value="800")
        app.purge_var = Mock()
        app.purge_var.get = Mock(return_value=True)
        app._log_entries = []
        app._cancel_requested = False
        app.auto_end = False
        app._app_config = {"fanart": {}}
        app.status_txt = Mock()
        app.progress = Mock()
        app.log_list = Mock()
        app.res_msg = Mock()
        app.notebook = Mock()
        app.start_btn = Mock()
        app.cancel_btn = Mock()
        app._tab_processing = Mock()
        app._tab_results = Mock()
        # start_thread snapshots every Tk var on the main thread before the
        # worker starts (see _run_logic's thread-safety note); mirror that so
        # _run_logic can be driven directly.
        app._run_path = app.folder_path.get()
        app._run_mode = app.run_mode.get()
        app._run_embed_size = int(app.size_var.get())
        app._run_purge = app.purge_var.get()
        return app

    def teardown_method(self, method) -> None:
        """Restore tkinter after each test so subsequent test files are not poisoned."""
        if hasattr(self, "_saved_tkinter"):
            if self._saved_tkinter is not None:
                sys.modules["tkinter"] = self._saved_tkinter
            else:
                sys.modules.pop("tkinter", None)
        # _build_full_tk_stub() also swaps these submodules in; pop them so the
        # real tkinter.messagebox/ttk/filedialog are re-imported by later suites.
        for name in ("tkinter.ttk", "tkinter.messagebox", "tkinter.filedialog"):
            sys.modules.pop(name, None)

    # ---- early-exit branches -----------------------------------------------

    def test_directory_does_not_exist_logs_error_and_returns(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path / "does_not_exist")
        with patch("album_art_sync.app.source_resolver.resolve") as mock_resolve:
            app._run_logic()
        mock_resolve.assert_not_called()
        assert "Directory does not exist" in "".join(app._log_entries)

    def test_no_supported_files_logs_error_and_returns(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "notes.txt").write_text("not audio")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with patch("album_art_sync.app.source_resolver.resolve") as mock_resolve:
            app._run_logic()
        mock_resolve.assert_not_called()
        assert "No supported audio files found" in "".join(app._log_entries)

    def test_metadata_read_failure_logs_error_and_returns(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch(
                "album_art_sync.app.read_artist_album",
                side_effect=RuntimeError("corrupt tag"),
            ),
            patch("album_art_sync.app.source_resolver.resolve") as mock_resolve,
        ):
            app._run_logic()
        mock_resolve.assert_not_called()
        assert "Error reading file metadata" in "".join(app._log_entries)

    # ---- album-artist lookup fallback --------------------------------------

    def test_uses_album_artist_when_present_for_lookup(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch(
                "album_art_sync.app.read_artist_album",
                return_value=("Track Artist", "Album X"),
            ),
            patch(
                "album_art_sync.app.read_album_artist",
                return_value="Various Artists",
            ),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ) as mock_resolve,
        ):
            app._run_logic()
        assert mock_resolve.call_args.kwargs["artist"] == "Various Artists"
        assert mock_resolve.call_args.kwargs["album"] == "Album X"

    def test_falls_back_to_track_artist_when_no_album_artist(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch(
                "album_art_sync.app.read_artist_album",
                return_value=("Track Artist", "Album X"),
            ),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ) as mock_resolve,
        ):
            app._run_logic()
        assert mock_resolve.call_args.kwargs["artist"] == "Track Artist"

    def test_forwards_suite_default_min_dim_and_threshold(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch(
                "album_art_sync.app.read_artist_album",
                return_value=("Artist", "Album X"),
            ),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ) as mock_resolve,
        ):
            app._run_logic()
        assert mock_resolve.call_args.kwargs["min_art_dimension"] == 500
        assert mock_resolve.call_args.kwargs["album_match_threshold"] == 0.85

    def test_forwards_driver_min_dim_and_threshold_when_pre_parsed(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        from album_art_sync.utils.cli_args import ArtArgs

        pre_parsed = ArtArgs(min_art_dimension=400, album_match_threshold=0.70)
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._pre_parsed_cli = pre_parsed
        with (
            patch(
                "album_art_sync.app.read_artist_album",
                return_value=("Artist", "Album X"),
            ),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ) as mock_resolve,
        ):
            app._run_logic()
        assert mock_resolve.call_args.kwargs["min_art_dimension"] == 400
        assert mock_resolve.call_args.kwargs["album_match_threshold"] == 0.70

    # ---- cancellation during artwork search --------------------------------

    def test_cancelled_during_resolve_sets_cancelled_message(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        def fake_resolve(**kwargs: Any) -> tuple:
            app._cancel_requested = True  # simulate user cancelling mid-search
            return (None, None)

        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                side_effect=fake_resolve,
            ),
            patch("album_art_sync.app.apply_artwork") as mock_apply,
        ):
            app._run_logic()
        mock_apply.assert_not_called()
        app.res_msg.config.assert_any_call(text="Operation Cancelled")

    # ---- mode -> applier_mode translation (the fragile string mapping) -----

    @pytest.mark.parametrize(
        "ui_mode,expected_applier_mode",
        [
            ("Dry Run", "Dry Run"),
            ("Update Artwork", "Update Artwork"),
            # UniversalCLIHandler can set run_mode to "Live Update" via the
            # CLI path; anything that isn't literally "Dry Run" must still
            # resolve to "Update Artwork".
            ("Live Update", "Update Artwork"),
        ],
    )
    def test_run_mode_maps_to_correct_applier_mode(
        self, tmp_path: Path, ui_mode: str, expected_applier_mode: str
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path, mode=ui_mode)
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(b"IMG", "Deezer"),
            ),
            patch("album_art_sync.app.apply_artwork", return_value=True) as mock_apply,
        ):
            app._run_logic()
        assert mock_apply.call_args.kwargs["mode"] == expected_applier_mode

    # ---- result-message branches -------------------------------------------

    def test_no_artwork_found_sets_result_message(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ),
            patch("album_art_sync.app.apply_artwork") as mock_apply,
        ):
            app._run_logic()
        mock_apply.assert_not_called()
        app.res_msg.config.assert_any_call(text="No Artwork Found")

    def test_successful_apply_sets_success_message(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(b"IMG", "Fanart.tv"),
            ),
            patch("album_art_sync.app.apply_artwork", return_value=True),
        ):
            app._run_logic()
        app.res_msg.config.assert_any_call(text="Sync Complete via Fanart.tv")

    def test_artwork_apply_wrapped_in_active_undo_batch(self, tmp_path: Path) -> None:
        """Phase 2: _run_logic must wrap apply_artwork in an active
        ``tag_edit`` undo batch so writes auto-snapshot."""
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        mock_active_batch = MagicMock()
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(b"IMG", "Fanart.tv"),
            ),
            patch("album_art_sync.app.active_batch", mock_active_batch),
            patch("album_art_sync.app.apply_artwork", return_value=True) as mock_apply,
        ):
            app._run_logic()
        mock_active_batch.assert_called_once_with("album_art_sync", "tag_edit")
        mock_apply.assert_called_once()

    def test_partial_success_sets_warning_message(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(b"IMG", "Deezer"),
            ),
            patch("album_art_sync.app.apply_artwork", return_value=False),
        ):
            app._run_logic()
        app.res_msg.config.assert_any_call(text="Partial Success - Check Log")

    def test_unhandled_exception_sets_error_message(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                side_effect=RuntimeError("network stack exploded"),
            ),
        ):
            app._run_logic()
        app.res_msg.config.assert_any_call(text="Error - See Log")
        assert "CRITICAL ERROR" in "".join(app._log_entries)

    # ---- log file + auto-end side effects ----------------------------------

    def test_log_file_written_to_disk(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ),
        ):
            app._run_logic()
        log_path = tmp_path / "art_sync_log.txt"
        assert log_path.exists()
        assert "SESSION START" in log_path.read_text()

    def test_auto_end_schedules_root_destroy_after_completion(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.auto_end = True
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(None, None),
            ),
        ):
            app._run_logic()
        # Auto End must schedule the window close at its delay; the same root
        # also carries the zero-delay UI marshalling calls, so match on the
        # scheduled delays rather than counting every after().
        destroy_calls = [
            call_
            for call_ in app.root.after.call_args_list
            if call_.args[:2] == (2000, app.root.destroy)
        ]
        assert len(destroy_calls) == 1

    # ---- small guard-clause methods ----------------------------------------

    def test_cancel_operation_sets_flag_and_disables_button(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._cancel_operation()
        assert app._cancel_requested is True
        app.cancel_btn.config.assert_called_once_with(state="disabled")
        assert "cancellation" in "".join(app._log_entries).lower()

    def test_start_thread_noop_when_no_folder_selected(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.folder_path.get = Mock(return_value="")
        app.start_thread()
        app.folder_path.get.assert_called_once_with()
        app.log_list.delete.assert_not_called()
        app.cancel_btn.config.assert_not_called()
        app.notebook.select.assert_not_called()

    # ---- worker-thread marshalling (audit H3) -------------------------------

    def _scheduled(self, app: Any) -> list[tuple[int, Any, tuple[Any, ...]]]:
        """Return (delay, callback, args) for each recorded after() call."""
        return [tuple(call_.args) for call_ in app.root.after.call_args_list]

    def test_worker_ui_writes_are_scheduled_on_main_thread(
        self, tmp_path: Path
    ) -> None:
        """Every widget write on the worker path is deferred via after(0, ...).

        The stubs record the scheduling instead of running it, so a direct
        widget call from _run_logic would leave these lists empty.
        """
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.root.after.side_effect = None  # record only, do not execute
        with (
            patch("album_art_sync.app.read_artist_album", return_value=("A", "B")),
            patch("album_art_sync.app.read_album_artist", return_value=""),
            patch(
                "album_art_sync.app.source_resolver.resolve",
                return_value=(b"IMG", "Deezer"),
            ),
            patch("album_art_sync.app.apply_artwork", return_value=True),
        ):
            app._run_logic()

        scheduled = self._scheduled(app)
        zero_delay = [entry for entry in scheduled if entry[0] == 0]
        callbacks = [entry[1] for entry in zero_delay]
        assert app._append_log_line in callbacks
        assert app._apply_status in callbacks
        assert app._apply_progress in callbacks
        assert app._apply_result in callbacks
        assert app._apply_controls in callbacks
        # The status text and the result message reached the main thread.
        # Bound methods are compared with == : each attribute access builds a
        # new method object, so an identity check would never match.
        assert any(
            entry[1] == app._apply_status and entry[2] == "Searching for artwork..."
            for entry in zero_delay
        )
        assert any(
            entry[1] == app._apply_result and entry[2] == "Sync Complete via Deezer"
            for entry in zero_delay
        )
        # No widget was written directly from the worker thread.
        app.status_txt.set.assert_not_called()
        app.res_msg.config.assert_not_called()
        app.log_list.insert.assert_not_called()
        app.start_btn.config.assert_not_called()
        app.notebook.select.assert_not_called()
        app.progress.config.assert_not_called()

    def test_start_thread_snapshots_tk_vars_and_starts_daemon_worker(
        self, tmp_path: Path
    ) -> None:
        """start_thread reads every Tk var, then starts a daemon thread.

        The worker must never call .get() on a Tk variable, so the snapshot is
        part of the thread-safety contract, not an optimisation.
        """
        AudioSuiteV6 = self._import_app_class()
        (tmp_path / "track01.mp3").write_bytes(b"fake")
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.root.after.side_effect = None
        app.run_mode.get = Mock(return_value="Update Artwork")
        app.size_var.get = Mock(return_value="1200")
        app.purge_var.get = Mock(return_value=False)

        with patch("album_art_sync.app.threading.Thread") as mock_thread:
            app.start_thread()

        assert app._run_path == str(tmp_path)
        assert app._run_mode == "Update Artwork"
        assert app._run_embed_size == 1200
        assert app._run_purge is False
        assert mock_thread.call_args.kwargs["daemon"] is True
        assert mock_thread.call_args.kwargs["target"] == app._run_logic

    def test_log_helper_updates_the_listbox_when_called_on_main_thread(
        self, tmp_path: Path
    ) -> None:
        """The marshalled helper is directly callable and does the widget write."""
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.root.after.side_effect = None

        app._append_log_line("straight from the main thread")

        app.log_list.insert.assert_called_once_with(
            "end", "straight from the main thread"
        )
        app.root.update_idletasks.assert_called_once()


class TestRealWidgetMarshalling:
    """The after(0, ...) bridge against real Tk widgets.

    A per-test withdrawn Toplevel off the session-scoped shared root is used
    so nothing lasting past the test is interned on the shared root.
    """

    def test_add_log_line_reaches_a_real_listbox(self, root: Any) -> None:
        sys.modules.pop("album_art_sync.app", None)
        import tkinter as tk

        from album_art_sync.app import AudioSuiteV6

        top = tk.Toplevel(root)
        try:
            app = object.__new__(AudioSuiteV6)
            app.root = top
            app.log_list = tk.Listbox(top)
            app._log_entries = []

            app._add_log("scheduled from a worker")
            assert app.log_list.size() == 0  # nothing yet: the bridge is deferred
            top.update()
            assert app.log_list.get(0, tk.END) == ("scheduled from a worker",)
            assert app._log_entries == ["scheduled from a worker\n"]
        finally:
            top.destroy()


class TestAppGuiMethods:
    """Tests for AudioSuiteV6 GUI helper methods: CLI arg application,
    presets, user actions, and _maybe_auto_end.

    Uses the same _make_bare_app() / _import_app_class() pattern as
    TestAppRunLogic -- __init__ is bypassed; only the attributes each
    method actually touches are set.
    """

    def _import_app_class(self) -> Any:
        self._saved_tkinter = sys.modules.get("tkinter")
        _build_full_tk_stub()

        # Add askyesno to messagebox stub so _on_delete_preset can call it
        messagebox_mod = sys.modules.get("tkinter.messagebox")
        if messagebox_mod is not None:
            messagebox_mod.askyesno = Mock()

        # Add simpledialog stub so _on_save_preset's local import works
        if "tkinter.simpledialog" not in sys.modules:
            simpledialog_mod = types.ModuleType("tkinter.simpledialog")
            simpledialog_mod.askstring = Mock()
            sys.modules["tkinter.simpledialog"] = simpledialog_mod
            tk_stub = sys.modules.get("tkinter")
            if tk_stub is not None:
                tk_stub.simpledialog = simpledialog_mod

        pil_mod = sys.modules.get("PIL")
        if pil_mod is None:
            pil_mod = types.ModuleType("PIL")
            sys.modules["PIL"] = pil_mod
        imagetk_mod = types.ModuleType("PIL.ImageTk")
        imagetk_mod.PhotoImage = MagicMock
        sys.modules["PIL.ImageTk"] = imagetk_mod
        pil_mod.ImageTk = imagetk_mod

        _ensure_app_shared_stubs_available()

        for mod_name in list(sys.modules.keys()):
            if mod_name == "album_art_sync.app" or mod_name.startswith(
                "album_art_sync.ui"
            ):
                del sys.modules[mod_name]

        from album_art_sync.app import AudioSuiteV6

        return AudioSuiteV6

    def _make_bare_app(
        self, audio_suite_v6_cls: Any, folder: Path, mode: str = "Dry Run"
    ) -> Any:
        app = object.__new__(audio_suite_v6_cls)
        app.root = MagicMock()
        app.root.after.side_effect = lambda delay, func, *args: func(*args)
        app.folder_path = Mock()
        app.folder_path.get = Mock(return_value=str(folder))
        app.folder_path.set = Mock()
        app.run_mode = Mock()
        app.run_mode.get = Mock(return_value=mode)
        app.run_mode.set = Mock()
        app.size_var = Mock()
        app.size_var.get = Mock(return_value="800")
        app.size_var.set = Mock()
        app.purge_var = Mock()
        app.purge_var.get = Mock(return_value=True)
        app.purge_var.set = Mock()
        app._log_entries = []
        app._cancel_requested = False
        app.auto_end = False
        app._app_config = {"fanart": {}}
        app.status_txt = Mock()
        app.progress = Mock()
        app.log_list = Mock()
        app.res_msg = Mock()
        app.notebook = Mock()
        app.start_btn = Mock()
        app.cancel_btn = Mock()
        app._tab_processing = Mock()
        app._tab_results = Mock()
        app._preset_combo = Mock()
        app._refresh_preset_list = Mock()
        app._pre_parsed_cli = None
        # CLI-related attributes for _apply_cli_args
        app.auto_start_var = Mock()
        app.auto_end_var = Mock()
        app.clear_logs_var = Mock()
        app.parallel_var = Mock()
        app.start_thread = Mock()
        return app

    def teardown_method(self, method) -> None:
        if hasattr(self, "_saved_tkinter"):
            if self._saved_tkinter is not None:
                sys.modules["tkinter"] = self._saved_tkinter
            else:
                sys.modules.pop("tkinter", None)
        for name in (
            "tkinter.ttk",
            "tkinter.messagebox",
            "tkinter.filedialog",
            "tkinter.simpledialog",
        ):
            sys.modules.pop(name, None)

    # ---- _apply_cli_args ----------------------------------------------------

    def test_apply_cli_args_sets_run_mode_live(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        parsed = Mock()
        parsed.folder_path = str(tmp_path)
        parsed.live_mode = True
        parsed.auto_start = False
        parsed.auto_end = False
        parsed.clear_logs = False
        parsed.parallel_run = False
        app._pre_parsed_cli = parsed

        with patch("album_art_sync.app.UniversalCLIHandler") as mock_handler_cls:
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_handler_cls.return_value = mock_handler
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Live Update")

    def test_apply_cli_args_sets_run_mode_dry(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        parsed = Mock()
        parsed.folder_path = str(tmp_path)
        parsed.live_mode = False
        parsed.auto_start = False
        parsed.auto_end = False
        parsed.clear_logs = True
        parsed.parallel_run = True
        app._pre_parsed_cli = parsed

        with patch("album_art_sync.app.UniversalCLIHandler") as mock_handler_cls:
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_handler_cls.return_value = mock_handler
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_apply_cli_args_returns_early_when_no_folder(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        parsed = Mock()
        parsed.folder_path = ""
        app._pre_parsed_cli = parsed

        with patch("album_art_sync.app.UniversalCLIHandler") as mock_handler_cls:
            app._apply_cli_args()
            mock_handler_cls.assert_not_called()
            app.run_mode.set.assert_not_called()
            parsed.folder_path = str(tmp_path)
            app._apply_cli_args()

        mock_handler_cls.assert_called_once_with(app)

    def test_apply_cli_args_auto_starts_when_flag_set(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        parsed = Mock()
        parsed.folder_path = str(tmp_path)
        parsed.live_mode = False
        parsed.auto_start = True
        parsed.auto_end = False
        parsed.clear_logs = False
        parsed.parallel_run = False
        app._pre_parsed_cli = parsed

        with patch("album_art_sync.app.UniversalCLIHandler") as mock_handler_cls:
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_handler_cls.return_value = mock_handler
            app._apply_cli_args()

        app.root.after.assert_any_call(0, app.start_thread)

    def test_apply_cli_args_passes_handler_params(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        parsed = Mock()
        parsed.folder_path = str(tmp_path)
        parsed.live_mode = False
        parsed.auto_start = False
        parsed.auto_end = False
        parsed.clear_logs = False
        parsed.parallel_run = False
        app._pre_parsed_cli = parsed

        with patch("album_art_sync.app.UniversalCLIHandler") as mock_handler_cls:
            mock_handler = MagicMock()
            mock_handler.apply_cli_args.return_value = False
            mock_handler_cls.return_value = mock_handler
            app._apply_cli_args()

        mock_handler_cls.assert_called_once_with(app)
        mock_handler.apply_cli_args.assert_called_once_with(
            parsed, folder_var=app.folder_path, auto_start_func=app.start_thread
        )

    # ---- _collect_settings / _apply_preset ----------------------------------

    def test_collect_settings_returns_dict(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path, mode="Live Update")
        app.size_var.get.return_value = "1000"
        app.purge_var.get.return_value = False

        result = app._collect_settings()

        assert result == {
            "execution_mode": "Live Update",
            "embedded_resolution": "1000",
            "purge_hidden": False,
        }

    def test_apply_preset_sets_all_vars(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        app._apply_preset(
            {
                "execution_mode": "Live Update",
                "embedded_resolution": "1200",
                "purge_hidden": False,
            }
        )

        app.run_mode.set.assert_called_once_with("Live Update")
        app.size_var.set.assert_called_once_with("1200")
        app.purge_var.set.assert_called_once_with(False)

    def test_apply_preset_ignores_missing_keys(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        app._apply_preset({"execution_mode": "Dry Run"})

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.size_var.set.assert_not_called()
        app.purge_var.set.assert_not_called()

    def test_apply_preset_handles_empty_dict(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        app._apply_preset({})

        app.run_mode.set.assert_not_called()
        app.size_var.set.assert_not_called()
        app.purge_var.set.assert_not_called()

        app._apply_preset({"execution_mode": "Dry Run"})

        app.run_mode.set.assert_called_once_with("Dry Run")

    # ---- _on_preset_selected ------------------------------------------------

    def test_on_preset_selected_applies_existing_preset(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        presets = {
            "My Preset": {
                "execution_mode": "Live Update",
                "embedded_resolution": "1200",
                "purge_hidden": False,
            }
        }

        with patch.object(app, "_load_presets", return_value=presets):
            app._on_preset_selected("My Preset")

        app.run_mode.set.assert_called_once_with("Live Update")
        app.size_var.set.assert_called_once_with("1200")
        app.purge_var.set.assert_called_once_with(False)

    def test_on_preset_selected_unknown_name_is_noop(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        with patch.object(app, "_load_presets", return_value={}) as mock_load:
            app._on_preset_selected("Nonexistent")

        mock_load.assert_called_once_with()
        app.run_mode.set.assert_not_called()

    # ---- _on_save_preset ----------------------------------------------------

    def test_on_save_preset_prompts_and_saves(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.run_mode.get.return_value = "Dry Run"
        app.size_var.get.return_value = "800"
        app.purge_var.get.return_value = True

        with (
            patch("tkinter.simpledialog.askstring", return_value="My Preset"),
            patch.object(app, "_load_presets", return_value={}),
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_save_preset()

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert "My Preset" in saved
        assert saved["My Preset"]["execution_mode"] == "Dry Run"
        app._refresh_preset_list.assert_called_once()

    def test_on_save_preset_empty_name_is_cancelled(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        with (
            patch("tkinter.simpledialog.askstring", return_value="") as mock_askstring,
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_save_preset()

        mock_askstring.assert_called_once_with(
            "Save Preset", "Enter preset name:", parent=app.root
        )
        mock_save.assert_not_called()

    def test_on_save_preset_whitespace_name_is_cancelled(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        with (
            patch(
                "tkinter.simpledialog.askstring", return_value="   "
            ) as mock_askstring,
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_save_preset()

        mock_askstring.assert_called_once_with(
            "Save Preset", "Enter preset name:", parent=app.root
        )
        mock_save.assert_not_called()

    def test_on_save_preset_none_is_cancelled(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        with (
            patch(
                "tkinter.simpledialog.askstring", return_value=None
            ) as mock_askstring,
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_save_preset()

        mock_askstring.assert_called_once_with(
            "Save Preset", "Enter preset name:", parent=app.root
        )
        mock_save.assert_not_called()

    # ---- _on_delete_preset --------------------------------------------------

    def test_on_delete_preset_confirms_and_deletes(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._preset_combo.get.return_value = "Old Preset"
        presets = {"Old Preset": {"execution_mode": "Dry Run"}}

        with (
            patch("album_art_sync.app.messagebox.askyesno", return_value=True),
            patch.object(app, "_load_presets", return_value=presets),
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_delete_preset()

        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert "Old Preset" not in saved
        app._refresh_preset_list.assert_called_once()

    def test_on_delete_preset_decline_is_noop(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._preset_combo.get.return_value = "Old Preset"
        presets = {"Old Preset": {"execution_mode": "Dry Run"}}

        with (
            patch(
                "album_art_sync.app.messagebox.askyesno", return_value=False
            ) as mock_askyesno,
            patch.object(app, "_load_presets", return_value=presets),
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_delete_preset()

        mock_askyesno.assert_called_once_with(
            "Delete Preset", "Delete preset 'Old Preset'?", parent=app.root
        )
        mock_save.assert_not_called()

    def test_on_delete_preset_no_combo_is_noop(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._preset_combo = None

        app._on_delete_preset()
        # No error, no save call

    def test_on_delete_preset_empty_name_is_noop(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._preset_combo.get.return_value = ""

        with patch.object(app, "_save_presets") as mock_save:
            app._on_delete_preset()

        app._preset_combo.get.assert_called_once_with()
        mock_save.assert_not_called()

    def test_on_delete_preset_preset_not_in_store(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app._preset_combo.get.return_value = "Ghost"

        with (
            patch.object(app, "_load_presets", return_value={}) as mock_load,
            patch.object(app, "_save_presets") as mock_save,
        ):
            app._on_delete_preset()

        mock_load.assert_called_once_with()
        mock_save.assert_not_called()

    # ---- _browse_folder -----------------------------------------------------

    def test_browse_folder_delegates_to_standard(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        with patch.object(app, "_browse_folder_standard") as mock_browse:
            app._browse_folder()

        mock_browse.assert_called_once_with(
            title="Select Music Directory",
            path_variable=app.folder_path,
            save_last_dir=True,
        )

    # ---- _open_help ---------------------------------------------------------

    def test_open_help_delegates_to_standard(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)

        with patch.object(app, "_open_help_standard") as mock_help:
            app._open_help()

        mock_help.assert_called_once_with(AudioSuiteV6.HELP_GUIDE)

    # ---- _open_folder -------------------------------------------------------

    def test_open_folder_opens_existing_path(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.folder_path.get.return_value = str(tmp_path)

        with patch("album_art_sync.app.platform_utils.open_path") as mock_open:
            app._open_folder()

        mock_open.assert_called_once_with(str(tmp_path))

    def test_open_folder_shows_info_for_empty_path(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.folder_path.get.return_value = ""

        with patch("album_art_sync.app.messagebox.showinfo") as mock_info:
            app._open_folder()

        mock_info.assert_called_once()
        assert "not available" in mock_info.call_args[0][1]

    def test_open_folder_shows_info_for_missing_path(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path / "nonexistent")

        with patch("album_art_sync.app.messagebox.showinfo") as mock_info:
            app._open_folder()

        mock_info.assert_called_once()

    # ---- _open_log ----------------------------------------------------------

    def test_open_log_opens_log_file(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.folder_path.get.return_value = str(tmp_path)

        with patch("album_art_sync.app.platform_utils.open_path") as mock_open:
            app._open_log()

        expected = str(tmp_path / "art_sync_log.txt")
        mock_open.assert_called_once_with(expected)

    # ---- _maybe_auto_end ----------------------------------------------------

    def test_maybe_auto_end_schedules_destroy_when_enabled(
        self, tmp_path: Path
    ) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.auto_end = True

        app._maybe_auto_end(delay=3000)

        # _add_log also calls root.after(0, ...) for the log line, so
        # use assert_any_call for the destroy scheduling.
        app.root.after.assert_any_call(3000, app.root.destroy)

    def test_maybe_auto_end_does_nothing_when_disabled(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.auto_end = False

        app._maybe_auto_end()

        app.root.after.assert_not_called()

        app.auto_end = True
        app._maybe_auto_end()

        app.root.after.assert_any_call(2000, app.root.destroy)

    def test_maybe_auto_end_logs_message(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.auto_end = True

        app._maybe_auto_end(delay=2000)

        log_text = "".join(app._log_entries)
        assert "Auto End" in log_text
        assert "2 seconds" in log_text

    def test_maybe_auto_end_default_delay_is_2000(self, tmp_path: Path) -> None:
        AudioSuiteV6 = self._import_app_class()
        app = self._make_bare_app(AudioSuiteV6, tmp_path)
        app.auto_end = True

        app._maybe_auto_end()

        app.root.after.assert_any_call(2000, app.root.destroy)
