"""Tests for the ISRC half of audio_suite_shared.tag_helper_writer.

Every case round-trips through a *real* file: the write goes to disk and the
read re-opens the file with a fresh handler (and, for the container assertions,
with ``mutagen.File`` directly), so a write that never persists cannot pass by
reading back an in-memory tags object.

Fixtures are either generated with pydub (mp3, flac, ogg, opus, m4a, wav, aiff)
or copied from the committed mutagen fixtures under ``tests/data/`` for the
containers pydub cannot produce (wavpack, monkey's audio, musepack, dsf, speex).
Copies are used because a write mutates the file.

Changed in 1.2.0: new suite for ``write_isrc`` / ``read_isrcs``
(PLAN_feature_expansion.md D29).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import mutagen
import pytest

from audio_suite_shared.exceptions import AudioTagError
from audio_suite_shared.tag_helper import (
    APEv2Handler,
    BaseTagHandler,
    DSFID3Handler,
    IFFID3Handler,
    MP3Handler,
    MP4Handler,
    TagHandlerFactory,
    VorbisHandler,
    read_isrcs,
    write_isrc,
)

try:
    from pydub import AudioSegment

    PYDUB_AVAILABLE = True
except ImportError:  # pragma: no cover - ffmpeg/pydub absent
    PYDUB_AVAILABLE = False

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "tests" / "data"

ISRC = "GBAYE0601498"
OTHER_ISRC = "USRC17607839"


def _silent(duration_ms: int = 100) -> "AudioSegment":
    """Return a short silent segment for pydub-backed fixtures."""
    return AudioSegment.silent(duration=duration_ms)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mp3_file(tmp_path: Path) -> str:
    path = tmp_path / "test.mp3"
    _silent().export(str(path), format="mp3")
    return str(path)


@pytest.fixture
def flac_file(tmp_path: Path) -> str:
    path = tmp_path / "test.flac"
    _silent().export(str(path), format="flac")
    return str(path)


@pytest.fixture
def ogg_file(tmp_path: Path) -> str:
    path = tmp_path / "test.ogg"
    _silent().export(str(path), format="ogg")
    return str(path)


@pytest.fixture
def opus_file(tmp_path: Path) -> str:
    path = tmp_path / "test.opus"
    _silent().export(str(path), format="opus")
    return str(path)


@pytest.fixture
def m4a_file(tmp_path: Path) -> str:
    path = tmp_path / "test.m4a"
    _silent().export(str(path), format="mp4")
    return str(path)


@pytest.fixture
def wav_file(tmp_path: Path) -> str:
    path = tmp_path / "test.wav"
    _silent().export(str(path), format="wav")
    return str(path)


@pytest.fixture
def aiff_file(tmp_path: Path) -> str:
    path = tmp_path / "test.aiff"
    _silent().export(str(path), format="aiff")
    return str(path)


def _copy_fixture(tmp_path: Path, name: str) -> str:
    """Copy a committed fixture into *tmp_path* so the write is disposable."""
    source = DATA_DIR / name
    if not source.is_file():  # pragma: no cover - fixture set is committed
        pytest.skip(f"committed fixture missing: {name}")
    target = tmp_path / name
    shutil.copyfile(source, target)
    return str(target)


@pytest.fixture
def wv_file(tmp_path: Path) -> str:
    return _copy_fixture(tmp_path, "silence-44-s.wv")


@pytest.fixture
def ape_file(tmp_path: Path) -> str:
    return _copy_fixture(tmp_path, "mac-399.ape")


@pytest.fixture
def mpc_file(tmp_path: Path) -> str:
    return _copy_fixture(tmp_path, "click.mpc")


@pytest.fixture
def dsf_file(tmp_path: Path) -> str:
    return _copy_fixture(tmp_path, "with-id3.dsf")


@pytest.fixture
def spx_file(tmp_path: Path) -> str:
    return _copy_fixture(tmp_path, "empty.spx")


#: pydub format name per file extension, for the formats pydub can encode.
_PYDUB_FORMATS = {
    "mp3": "mp3",
    "flac": "flac",
    "ogg": "ogg",
    "opus": "opus",
    "m4a": "mp4",
    "wav": "wav",
    "aiff": "aiff",
}

#: Committed fixture per extension, for the formats pydub cannot encode.
_COMMITTED_FORMATS = {
    "wv": "silence-44-s.wv",
    "ape": "mac-399.ape",
    "mpc": "click.mpc",
    "dsf": "with-id3.dsf",
    "spx": "empty.spx",
}


@pytest.fixture(params=[*_PYDUB_FORMATS, *_COMMITTED_FORMATS])
def isrc_file(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    """One writable file in every container that can hold an ISRC."""
    extension = str(request.param)
    committed = _COMMITTED_FORMATS.get(extension)
    if committed is not None:
        return _copy_fixture(tmp_path, committed)
    path = tmp_path / f"test.{extension}"
    _silent().export(str(path), format=_PYDUB_FORMATS[extension])
    return str(path)


# ── Round trips ───────────────────────────────────────────────────────────────


class TestIsrcRoundTrip:
    def test_single_isrc_persists(self, isrc_file: str):
        write_isrc(isrc_file, [ISRC])

        # A brand-new handler, i.e. a fresh read of the bytes on disk.
        assert read_isrcs(isrc_file) == (ISRC,)

    def test_multiple_isrcs_persist_in_order(self, isrc_file: str):
        write_isrc(isrc_file, [ISRC, OTHER_ISRC])
        assert read_isrcs(isrc_file) == (ISRC, OTHER_ISRC)

    def test_absent_before_write(self, isrc_file: str):
        assert read_isrcs(isrc_file) == ()

    def test_rewrite_replaces_rather_than_appends(self, isrc_file: str):
        write_isrc(isrc_file, [ISRC])
        write_isrc(isrc_file, [OTHER_ISRC])
        assert read_isrcs(isrc_file) == (OTHER_ISRC,)


class TestIsrcNormalisation:
    def test_lowercase_is_upper_cased(self, mp3_file: str):
        write_isrc(mp3_file, ["gbaye0601498"])
        assert read_isrcs(mp3_file) == (ISRC,)

    def test_blank_and_duplicate_values_are_dropped(self, mp3_file: str):
        write_isrc(mp3_file, [" gbaye0601498 ", "", "   ", ISRC])
        assert read_isrcs(mp3_file) == (ISRC,)

    def test_empty_sequence_is_a_no_op(self, mp3_file: str):
        write_isrc(mp3_file, [ISRC])
        write_isrc(mp3_file, [])
        # The earlier value must survive: a lookup that returned nothing may
        # never blank a tag the file already had.
        assert read_isrcs(mp3_file) == (ISRC,)


class TestIsrcContainerConventions:
    """Each format stores the ISRC where other taggers look for it."""

    def test_mp3_uses_the_tsrc_frame(self, mp3_file: str):
        write_isrc(mp3_file, [ISRC])
        tags = mutagen.File(mp3_file).tags
        assert tags is not None
        assert tags.getall("TSRC")[0].text == [ISRC]

    def test_flac_uses_a_vorbis_comment(self, flac_file: str):
        write_isrc(flac_file, [ISRC])
        audio = mutagen.File(flac_file)
        assert audio is not None
        assert list(audio.tags["isrc"]) == ["GBAYE0601498"]

    def test_m4a_uses_the_freeform_atom(self, m4a_file: str):
        write_isrc(m4a_file, [ISRC])
        audio = mutagen.File(m4a_file)
        assert audio is not None
        assert audio.tags["----:com.apple.iTunes:ISRC"][0] == b"GBAYE0601498"

    def test_wavpack_uses_an_apev2_item(self, wv_file: str):
        write_isrc(wv_file, [ISRC])
        audio = mutagen.File(wv_file)
        assert audio is not None
        assert list(audio.tags["ISRC"]) == [ISRC]

    def test_aiff_uses_the_tsrc_frame(self, aiff_file: str):
        write_isrc(aiff_file, [ISRC])
        tags = mutagen.File(aiff_file).tags
        assert tags is not None
        assert tags.getall("TSRC")[0].text == [ISRC]


class TestIsrcFailures:
    def test_unsupported_container_raises_audio_tag_error(self, tmp_path: Path):
        path = tmp_path / "notes.txt"
        path.write_text("not audio", encoding="utf-8")

        with pytest.raises(AudioTagError):
            write_isrc(str(path), [ISRC])

    def test_read_of_unreadable_file_is_empty_not_an_error(self, tmp_path: Path):
        path = tmp_path / "broken.mp3"
        path.write_bytes(b"not really an mp3")

        assert read_isrcs(str(path)) == ()

    def test_read_of_missing_file_is_empty(self, tmp_path: Path):
        assert read_isrcs(str(tmp_path / "absent.flac")) == ()


class TestHandlerSurface:
    """Every concrete handler implements the read side, not just the base stub."""

    def test_base_handler_offers_the_hook(self):
        assert "read_isrcs" in BaseTagHandler.__dict__

    @pytest.mark.parametrize(
        "handler_cls",
        [
            MP3Handler,
            IFFID3Handler,
            VorbisHandler,
            MP4Handler,
            APEv2Handler,
            DSFID3Handler,
        ],
    )
    def test_each_handler_overrides_the_hook(self, handler_cls: type) -> None:
        # Identity, not ``__dict__`` membership: the IFF and DSF handlers
        # deliberately inherit the ID3 (TSRC) implementation from MP3Handler.
        assert handler_cls.read_isrcs is not BaseTagHandler.read_isrcs, (
            f"{handler_cls.__name__} inherits the empty base read_isrcs"
        )

    def test_facade_round_trip_through_the_factory(self, mp3_file: str):
        write_isrc(mp3_file, [ISRC])
        assert TagHandlerFactory.get_handler(mp3_file).read_isrcs() == (ISRC,)
