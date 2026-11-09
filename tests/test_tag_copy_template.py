"""Copy-from-reference and saved templates (plan F-E7).

Every assertion reads the file back through the tag layer, or reverts a real
undo batch and reads it again - never the dataclass the writer just built.

Changed in 2.6.0: added for plan F-E7.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydub import AudioSegment

from audio_suite_shared import tag_templates
from audio_suite_shared.batch_undo import (
    active_batch,
    get_active_batch_id,
    revert_batch_by_id,
)
from audio_suite_shared.exceptions import AudioSuiteError, AudioTagError
from audio_suite_shared.tag_field_engine import TagFieldEngine
from audio_suite_shared.tag_handler_factory import TagHandlerFactory

FORMATS = {"mp3": "mp3", "flac": "flac", "m4a": "mp4", "wav": "wav"}


def _make(path: Path, fmt: str) -> Path:
    """Write a short silent file in *fmt* and return its path."""
    AudioSegment.silent(duration=200).export(str(path), format=fmt)
    return path


def _raw(path: Path) -> dict[str, Any]:
    """Return the file's raw tag mapping, for before/after comparison."""
    raw = TagHandlerFactory.get_handler(str(path)).get_raw_tags()
    return {} if raw is None else dict(raw)


def _write(path: Path, **values: str) -> None:
    """Store canonical fields through the engine."""
    TagFieldEngine(str(path)).write_fields(values)


@pytest.mark.parametrize("extension", sorted(FORMATS))
def test_copied_fields_read_back_on_each_container(
    tmp_path: Path, extension: str
) -> None:
    if not TagHandlerFactory.is_supported(extension):
        pytest.skip(f"no tag handler for .{extension}")
    reference = _make(tmp_path / f"ref.{extension}", FORMATS[extension])
    target = _make(tmp_path / f"target.{extension}", FORMATS[extension])
    _write(reference, title="Ref Title", artist="Ref Artist", album="Ref Album")
    _write(target, title="Old Title", artist="Old Artist", album="Kept Album")

    template, results = tag_templates.copy_fields(
        reference, [target], ("title", "artist")
    )

    assert template.fields == {"title": "Ref Title", "artist": "Ref Artist"}
    assert [result.written for result in results] == [True]
    stored = TagFieldEngine(str(target)).read_fields()
    assert stored["title"] == "Ref Title"
    assert stored["artist"] == "Ref Artist"
    assert stored["album"] == "Kept Album"


@pytest.mark.parametrize("extension", sorted(FORMATS))
def test_untouched_raw_tags_are_unchanged(tmp_path: Path, extension: str) -> None:
    if not TagHandlerFactory.is_supported(extension):
        pytest.skip(f"no tag handler for .{extension}")
    reference = _make(tmp_path / f"ref.{extension}", FORMATS[extension])
    target = _make(tmp_path / f"target.{extension}", FORMATS[extension])
    _write(reference, genre="Ref Genre")
    _write(target, genre="Old Genre", album="Kept Album", comment="Kept Comment")
    before = _raw(target)
    # ``genre`` is a key rule, so the engine names the raw key a genre write
    # touches without a second table in this test.
    genre_keys = {
        key.lower()
        for key in TagFieldEngine(str(target)).raw_updates({"genre": "probe"})
    }
    assert genre_keys, "the genre rule reported no container key"

    tag_templates.copy_fields(reference, [target], ("genre",))

    after = _raw(target)
    assert after != before, "the target's tags did not change at all"
    for key, value in before.items():
        if key.lower() not in genre_keys:
            assert after.get(key) == value, key


@pytest.mark.parametrize("extension", ["mp3", "flac"])
def test_undo_restores_the_pre_edit_raw_values(
    tmp_path: Path, extension: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("audio_suite_shared.batch_undo.is_undo_enabled", lambda: True)
    reference = _make(tmp_path / f"ref.{extension}", FORMATS[extension])
    target = _make(tmp_path / f"target.{extension}", FORMATS[extension])
    _write(reference, title="Ref Title", artist="Ref Artist")
    _write(target, title="Old Title", artist="Old Artist")
    before = _raw(target)
    before_fields = TagFieldEngine(str(target)).read_fields()

    with active_batch("tag_editor", "tag_edit"):
        tag_templates.copy_fields(reference, [target], ("title", "artist"))
        batch_id = get_active_batch_id()

    assert _raw(target) != before
    assert batch_id is not None
    revert_batch_by_id(batch_id)
    assert TagFieldEngine(str(target)).read_fields() == before_fields
    assert _raw(target) == before


def test_a_dry_run_changes_nothing_and_names_the_changed_fields(
    tmp_path: Path,
) -> None:
    reference = _make(tmp_path / "ref.flac", "flac")
    target = _make(tmp_path / "target.flac", "flac")
    _write(reference, title="Ref Title", artist="Ref Artist", album="Ref Album")
    _write(target, title="Old Title", artist="Ref Artist", album="Ref Album")
    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime_ns
    before_tags = _raw(target)

    _template, results = tag_templates.copy_fields(
        reference, [target], ("title", "artist", "album"), dry_run=True
    )

    assert results[0].changes == {"title": ("Old Title", "Ref Title")}
    assert results[0].written is False
    assert target.stat().st_mtime_ns == before_mtime
    assert target.read_bytes() == before_bytes
    assert _raw(target) == before_tags


def test_a_saved_template_is_written_to_the_shared_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store: dict[str, Any] = {}
    monkeypatch.setattr(
        tag_templates.suite_config,
        "load_value",
        lambda key, default=None: store.get(key, default),
    )
    monkeypatch.setattr(
        tag_templates.suite_config,
        "save_value",
        lambda key, value: store.__setitem__(key, value),
    )

    tag_templates.save_template(
        tag_templates.TagTemplate(name="Podcast", fields={"album": "Show"})
    )

    assert tag_templates.CONFIG_KEY == "tag_templates"
    assert "tag_templates" in store
    loaded = tag_templates.load_templates()
    assert loaded["Podcast"].fields == {"album": "Show"}
    assert tag_templates.delete_template("Podcast") is True
    assert tag_templates.load_templates() == {}
    assert tag_templates.delete_template("Podcast") is False


def test_an_unknown_field_is_refused_with_the_valid_list(tmp_path: Path) -> None:
    reference = _make(tmp_path / "ref.flac", "flac")
    _write(reference, title="Ref Title")

    with pytest.raises(AudioTagError) as caught:
        tag_templates.template_from_file(reference, ("nonsense",))

    message = str(caught.value)
    assert "Unknown tag field" in message
    assert "title" in message


def test_a_container_without_a_tag_writer_is_refused(tmp_path: Path) -> None:
    reference = tmp_path / "ref.aac"
    reference.write_bytes(b"")

    with pytest.raises(AudioSuiteError) as caught:
        tag_templates.template_from_file(reference, ("title",))

    assert "Unsupported format: .aac" in str(caught.value)


def test_a_reference_with_no_requested_fields_is_refused(tmp_path: Path) -> None:
    reference = _make(tmp_path / "ref.flac", "flac")

    with pytest.raises(AudioTagError) as caught:
        tag_templates.template_from_file(reference, ("title", "artist"))

    assert "none of the requested fields set" in str(caught.value)


def test_a_broken_target_is_its_own_error_not_the_batchs(tmp_path: Path) -> None:
    reference = _make(tmp_path / "ref.flac", "flac")
    good = _make(tmp_path / "good.flac", "flac")
    broken = tmp_path / "broken.wma"
    broken.write_bytes(b"")
    _write(reference, title="Ref Title")

    _template, results = tag_templates.copy_fields(
        reference, [good, broken], ("title",)
    )

    assert results[0].written is True
    assert results[1].error
    assert results[1].changed is False
