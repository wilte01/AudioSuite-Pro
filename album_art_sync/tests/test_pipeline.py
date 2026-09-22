"""Tests for album_art_sync.core.pipeline — resolve_and_apply()."""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path
from typing import Any

import pytest

from album_art_sync.core.pipeline import resolve_and_apply


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "music"
    d.mkdir()
    return d


@pytest.fixture
def mp3_file(audio_dir: Path) -> Path:
    f = audio_dir / "track.mp3"
    f.write_bytes(b"fake mp3 content")
    return f


@pytest.fixture
def log_cb() -> mock.Mock:
    return mock.Mock()


def _patch_all_sources(
    fanart_return: tuple[list[dict], str] | None = None,
    deezer_return: tuple[list[dict], str] | None = None,
    itunes_return: tuple[list[dict], str] | None = None,
) -> Any:
    """Patch the three source modules *after* filter_and_rank has run.

    This patches the API module ``query`` functions directly so that
    ``source_resolver.resolve()`` receives mocked results.
    """

    def make_fanart(artist, album, mb_ids, cfg, log, cancel, on_pick, **kw):
        if fanart_return and mb_ids:
            log(f"Fanart: {fanart_return[1]}")
            return on_pick(fanart_return[0], artist, "Fanart.tv")
        return None

    def make_deezer(artist, album, log, cancel, on_pick, **kw):
        if deezer_return:
            log(f"Deezer: {deezer_return[1]}")
            return on_pick(deezer_return[0], artist, "Deezer")
        return None

    def make_itunes(artist, album, log, cancel, on_pick, **kw):
        if itunes_return:
            log(f"iTunes: {itunes_return[1]}")
            return on_pick(itunes_return[0], artist, "iTunes Store")
        return None

    return mock.patch.multiple(
        "album_art_sync.api",
        fanart=mock.DEFAULT,
        deezer=mock.DEFAULT,
        itunes=mock.DEFAULT,
    )


class TestResolveAndApply:
    """End-to-end pipeline tests with mocked API sources."""

    def test_fanart_trusted_path_selected(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        """Fanart.tv candidate should be selected when available (trusted path)."""
        from album_art_sync.core.ranker import RankedCandidate

        [
            RankedCandidate(
                0, "https://example.com/art.jpg", "Cover", 800, 800, 640000.0, 1.0
            ),
        ]

        with (
            mock.patch(
                "album_art_sync.api.musicbrainz.query", return_value=["mb-uuid"]
            ),
            mock.patch("album_art_sync.api.fanart.query") as mock_fanart,
            mock.patch("album_art_sync.api.deezer.query"),
            mock.patch("album_art_sync.api.itunes.query"),
            mock.patch(
                "album_art_sync.core.pipeline._download_image",
                return_value=b"image_data",
            ),
            mock.patch("album_art_sync.core.pipeline.apply_artwork", return_value=True),
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "audio_suite_shared.tag_helper.read_artist_album",
                return_value=("Artist", "Album"),
            ),
            mock.patch(
                "audio_suite_shared.tag_helper.read_album_artist", return_value=""
            ),
        ):
            mock_fanart.return_value = b"fanart_image"
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                dry_run=False,
                log_callback=log_cb,
            )

        assert report.success is True
        assert report.source == "Fanart.tv"
        assert report.processed == 1
        assert report.selection_audit is not None

    def test_falls_back_to_deezer_when_fanart_empty(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        from album_art_sync.core.ranker import RankedCandidate

        [
            RankedCandidate(
                0, "https://deezer.com/art.jpg", "Album Title", 800, 800, 640000.0, 1.0
            ),
        ]

        with (
            mock.patch(
                "album_art_sync.api.musicbrainz.query", return_value=["mb-uuid"]
            ),
            mock.patch("album_art_sync.api.fanart.query", return_value=None),
            mock.patch("album_art_sync.api.deezer.query") as mock_deezer,
            mock.patch("album_art_sync.api.itunes.query"),
            mock.patch(
                "album_art_sync.core.pipeline._download_image",
                return_value=b"deezer_data",
            ),
            mock.patch("album_art_sync.core.pipeline.apply_artwork", return_value=True),
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "audio_suite_shared.tag_helper.read_artist_album",
                return_value=("Artist", "Album"),
            ),
            mock.patch(
                "audio_suite_shared.tag_helper.read_album_artist", return_value=""
            ),
        ):
            mock_deezer.return_value = b"deezer_image"
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                dry_run=False,
                log_callback=log_cb,
            )

        assert report.success is True
        assert report.source == "Deezer"

    def test_falls_back_to_itunes_when_others_empty(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        with (
            mock.patch("album_art_sync.api.musicbrainz.query", return_value=[]),
            mock.patch("album_art_sync.api.fanart.query", return_value=None),
            mock.patch("album_art_sync.api.deezer.query", return_value=None),
            mock.patch("album_art_sync.api.itunes.query", return_value=b"itunes_image"),
            mock.patch(
                "album_art_sync.core.pipeline._download_image",
                return_value=b"itunes_data",
            ),
            mock.patch("album_art_sync.core.pipeline.apply_artwork", return_value=True),
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "audio_suite_shared.tag_helper.read_artist_album",
                return_value=("Artist", "Album"),
            ),
            mock.patch(
                "audio_suite_shared.tag_helper.read_album_artist", return_value=""
            ),
        ):
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                dry_run=False,
                log_callback=log_cb,
            )

        assert report.success is True
        assert report.source == "iTunes Store"

    def test_all_sources_empty_returns_no_artwork(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        with (
            mock.patch("album_art_sync.api.musicbrainz.query", return_value=[]),
            mock.patch("album_art_sync.api.fanart.query", return_value=None),
            mock.patch("album_art_sync.api.deezer.query", return_value=None),
            mock.patch("album_art_sync.api.itunes.query", return_value=None),
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "audio_suite_shared.tag_helper.read_artist_album",
                return_value=("Artist", "Album"),
            ),
            mock.patch(
                "audio_suite_shared.tag_helper.read_album_artist", return_value=""
            ),
        ):
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                dry_run=False,
                log_callback=log_cb,
            )

        assert report.success is False
        assert report.source is None
        assert report.processed == 0

    def test_dry_run_does_not_write(self, mp3_file: Path, log_cb: mock.Mock) -> None:
        with (
            mock.patch(
                "album_art_sync.api.musicbrainz.query", return_value=["mb-uuid"]
            ),
            mock.patch("album_art_sync.api.fanart.query", return_value=b"fanart_img"),
            mock.patch("album_art_sync.api.deezer.query"),
            mock.patch("album_art_sync.api.itunes.query"),
            mock.patch(
                "album_art_sync.core.pipeline._download_image", return_value=b"data"
            ),
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "audio_suite_shared.tag_helper.read_artist_album",
                return_value=("Artist", "Album"),
            ),
            mock.patch(
                "audio_suite_shared.tag_helper.read_album_artist", return_value=""
            ),
        ):
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                dry_run=True,
                log_callback=log_cb,
            )

        assert report.success is True
        assert report.source == "Fanart.tv"
        assert report.processed == 1

    def test_nonexistent_directory_returns_error(
        self, tmp_path: Path, log_cb: mock.Mock
    ) -> None:
        report = resolve_and_apply(
            str(tmp_path / "nonexistent"),
            auto_select=True,
            log_callback=log_cb,
        )
        assert report.success is False
        assert report.errors == 1

    def test_no_audio_files_returns_error(
        self, audio_dir: Path, log_cb: mock.Mock
    ) -> None:
        report = resolve_and_apply(
            str(audio_dir),
            auto_select=True,
            log_callback=log_cb,
        )
        assert report.success is False
        assert report.errors == 1

    def test_metadata_read_failure_returns_error(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        with (
            mock.patch(
                "album_art_sync.core.pipeline.read_artist_album",
                side_effect=ValueError("Corrupt file"),
            ),
        ):
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                log_callback=log_cb,
            )
        assert report.success is False
        assert report.errors == 1

    def test_selection_audit_includes_source_chain(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        with (
            mock.patch(
                "album_art_sync.api.musicbrainz.query", return_value=["mb-uuid"]
            ),
            mock.patch("album_art_sync.api.fanart.query", return_value=b"fanart_img"),
            mock.patch("album_art_sync.api.deezer.query"),
            mock.patch("album_art_sync.api.itunes.query"),
            mock.patch(
                "album_art_sync.core.pipeline._download_image", return_value=b"data"
            ),
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "album_art_sync.core.pipeline.read_artist_album",
                return_value=("Beatles", "Abbey Road"),
            ),
            mock.patch(
                "album_art_sync.core.pipeline.read_album_artist",
                return_value="",
            ),
        ):
            report = resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                dry_run=False,
                log_callback=log_cb,
            )

        assert report.selection_audit is not None
        assert 'Artist: "Beatles"' in report.selection_audit
        assert 'Album: "Abbey Road"' in report.selection_audit
        assert "MusicBrainz → Fanart.tv → Deezer → iTunes" in report.selection_audit
        assert "Selected from" in report.selection_audit


class TestResolveAndApplyConfig:
    """Configuration forwarding — min_dimension, match_threshold."""

    def test_min_dimension_passed_to_resolver(
        self, mp3_file: Path, log_cb: mock.Mock
    ) -> None:
        with (
            mock.patch("album_art_sync.api.source_resolver.resolve") as mock_resolve,
            mock.patch("album_art_sync.config.settings.load_config", return_value={}),
            mock.patch(
                "audio_suite_shared.tag_helper.read_artist_album",
                return_value=("A", "B"),
            ),
            mock.patch(
                "audio_suite_shared.tag_helper.read_album_artist", return_value=""
            ),
        ):
            mock_resolve.return_value = (None, None)
            resolve_and_apply(
                str(mp3_file.parent),
                auto_select=True,
                min_art_dimension=600,
                album_match_threshold=0.90,
                log_callback=log_cb,
            )

        _kwargs = mock_resolve.call_args[1]
        assert _kwargs["min_art_dimension"] == 600
        assert _kwargs["album_match_threshold"] == 0.90
