"""
test_transformation_rules.py — the ``dry_run`` gate on every format rule.

Audit H1 (plan A1) found that all eight ``process_*_file`` rules in
:mod:`tag_field_updater.core.transformation_rules` called
``record_tag_edit_snapshot(...)`` and ``audio.save()`` unconditionally: the
``dry_run`` argument the CLI accepted never reached them.  The rule was the
*only* place the write could be withheld, so a future ninth rule that forgot
the gate would ship the same defect invisibly.

These tests therefore sweep **every** rule twice over:

* against **real encoded files** for every format pydub can produce, asserting
  the outcome on disk — SHA-256, mtime, and the re-read tag;
* against a **marker-writing stand-in** for the remaining two formats (``.mp4``
  needs an AAC encoder this suite does not require, ``.wma`` is not encodable
  at all), where the stand-in's ``save()`` leaves a marker file.  The marker's
  presence or absence is then an artifact-level statement about the gate rather
  than a mock's call log, and it works uniformly across all eight rules.

Each sweep is paired with its **live** counterpart on the same fixture.  The
contrast is what makes the dry-run half meaningful: without it, "the marker
file does not exist" would also hold if the write path were simply broken.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any

import pytest
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TCON, TXXX
from mutagen.mp3 import MP3
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from pydub import AudioSegment

from tag_field_updater.core import processor
from tag_field_updater.core import transformation_rules as rules
from tag_field_updater.core.mapping_engine import TAG_MAPPINGS

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

ORIGINAL_VALUE = "Rock/Pop"
REWRITTEN_VALUE = "Rock; Pop"

#: Bytes the stand-in audio objects write from ``save()``.  Its presence is the
#: proof that a rule reached its write site.
_SAVE_MARKER = b"saved-by-transformation-rule"


def digest(path: Path) -> str:
    """SHA-256 of the file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# The rule table — the sweep's single index
# ---------------------------------------------------------------------------

#: ``(rule name, mutagen attribute on the processor module, format key, kind)``.
#: ``kind`` selects the tag container shape the rule drives: ``"id3"`` for the
#: three rules that go through ``audio.tags``, ``"mapping"`` for the five that
#: treat the mutagen object itself as a mapping.
RULE_TABLE: list[tuple[str, str, str, str]] = [
    ("process_mp3_file", "MP3", "mp3", "id3"),
    ("process_flac_file", "FLAC", "flac", "mapping"),
    ("process_mp4_file", "MP4", "mp4", "mapping"),
    ("process_ogg_file", "OggVorbis", "ogg", "mapping"),
    ("process_opus_file", "OggOpus", "opus", "mapping"),
    ("process_wav_file", "WAVE", "wav", "id3"),
    ("process_aiff_file", "AIFF", "aiff", "id3"),
    ("process_wma_file", "ASF", "wma", "mapping"),
]

RULE_IDS = [name for name, _attr, _fmt, _kind in RULE_TABLE]

#: Mutagen opener per format key, for the real-file sweep.
_OPENERS: dict[str, Any] = {
    "mp3": MP3,
    "flac": FLAC,
    "mp4": None,  # not encodable here — marker sweep only
    "ogg": OggVorbis,
    "opus": OggOpus,
    "wav": WAVE,
    "aiff": AIFF,
    "wma": None,  # not encodable at all — marker sweep only
}

#: Formats the real-file sweep can build: the two whose encoder is absent are
#: covered by the marker sweep instead.
REAL_FORMATS = ["mp3", "flac", "ogg", "opus", "wav", "aiff"]


def _rule_params() -> list[pytest.Param]:
    """One parametrised case per rule in :data:`RULE_TABLE`."""
    return [
        pytest.param(name, attr, fmt, kind, id=name)
        for name, attr, fmt, kind in RULE_TABLE
    ]


# ---------------------------------------------------------------------------
# Marker-writing stand-ins for the two formats the suite cannot encode
# ---------------------------------------------------------------------------


class _MarkerMappingAudio(dict[str, str]):
    """A Vorbis/MP4/ASF-shaped tag mapping whose ``save`` writes a marker.

    The five mapping-backed rules (``flac``, ``mp4``, ``ogg``, ``opus``,
    ``wma``) only use ``key in audio``, ``audio[key] = value`` and
    ``audio.save()``, so a ``dict`` subclass carrying a ``save`` reproduces
    their whole interaction with mutagen.
    """

    def __init__(self, values: dict[str, str], marker: Path) -> None:
        super().__init__(values)
        self._marker = marker

    def save(self) -> None:
        """Stand in for mutagen's container rewrite."""
        self._marker.write_bytes(_SAVE_MARKER)


class _MarkerID3Audio:
    """An ID3-shaped mutagen object whose ``save`` writes a marker.

    The ``mp3``/``wav``/``aiff`` rules read ``audio.tags`` and drive a real
    :class:`mutagen.id3.ID3` container, so this hands them a genuine one.
    """

    def __init__(self, tags: ID3, marker: Path) -> None:
        self.tags = tags
        self._marker = marker

    def save(self) -> None:
        """Stand in for mutagen's container rewrite."""
        self._marker.write_bytes(_SAVE_MARKER)


def _build_fake_audio(kind: str, fmt: str, marker: Path) -> Any:
    """Build the tag payload a rule of *kind* will drive for *fmt*."""
    if kind == "id3":
        tags = ID3()
        tags.add(TCON(encoding=3, text=ORIGINAL_VALUE))
        tags.add(TXXX(encoding=3, desc="ALBUMGENRE", text=ORIGINAL_VALUE))
        return _MarkerID3Audio(tags, marker)

    mapping = TAG_MAPPINGS[fmt]
    keys = [*mapping["txxx"], *mapping["standard"]]
    return _MarkerMappingAudio(dict.fromkeys(keys, ORIGINAL_VALUE), marker)


@pytest.fixture()
def fake_source(tmp_path: Path) -> Path:
    """A stand-in container file with known pre-run bytes."""
    source = tmp_path / "source.bin"
    source.write_bytes(b"original container bytes")
    return source


# ---------------------------------------------------------------------------
# Sweep 1 — every rule honours the gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule_name", "attr", "fmt", "kind"), _rule_params(), ids=lambda v: str(v)
)
class TestEveryRuleGatesItsWrite:
    """No rule may reach ``save()`` — the sweep a future ninth rule joins."""

    @staticmethod
    def _patch(
        monkeypatch: pytest.MonkeyPatch, attr: str, fmt: str, kind: str, marker: Path
    ) -> Any:
        audio = _build_fake_audio(kind, fmt, marker)
        # The rules resolve ``MP3``/``FLAC``/… with a *function-local* import out
        # of the processor module, so that module is where the name must be
        # rebound (AGENTS.md: patch the module named in the ``from … import``).
        monkeypatch.setattr(processor, attr, lambda _path, bound=audio: bound)
        return audio

    def test_dry_run_reports_the_rewrite_without_writing(
        self,
        rule_name: str,
        attr: str,
        fmt: str,
        kind: str,
        fake_source: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        marker = tmp_path / f"{fmt}.marker"
        self._patch(monkeypatch, attr, fmt, kind, marker)

        result = getattr(rules, rule_name)(fake_source, dry_run=True)

        assert result.error is None, f"{rule_name} failed on a valid fixture"
        assert result.updated is True
        assert result.tags_updated, f"{rule_name} found no tag to rewrite"
        assert not marker.exists(), (
            f"{rule_name} reached save() in dry-run mode — this rule has no gate"
        )

    def test_live_run_writes_through_the_same_gate(
        self,
        rule_name: str,
        attr: str,
        fmt: str,
        kind: str,
        fake_source: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The contrast half: without it the dry-run half proves nothing."""
        marker = tmp_path / f"{fmt}.marker"
        self._patch(monkeypatch, attr, fmt, kind, marker)

        result = getattr(rules, rule_name)(fake_source)

        assert result.error is None
        assert result.updated is True
        assert marker.read_bytes() == _SAVE_MARKER

    def test_dry_run_records_no_undo_snapshot(
        self,
        rule_name: str,
        attr: str,
        fmt: str,
        kind: str,
        fake_source: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A snapshot for a change that never happened is an undo that lies."""
        marker = tmp_path / f"{fmt}.marker"
        recorded: list[str] = []
        monkeypatch.setattr(
            rules,
            "record_tag_edit_snapshot",
            lambda path, operation: recorded.append(path),
        )
        rule = getattr(rules, rule_name)

        # A fresh stand-in per half: the dry run rewrites the payload in memory,
        # so reusing it would leave the live half nothing left to change.
        self._patch(monkeypatch, attr, fmt, kind, marker)
        rule(fake_source, dry_run=True)
        assert recorded == []

        self._patch(monkeypatch, attr, fmt, kind, marker)
        rule(fake_source)
        assert recorded == [str(fake_source)]


def test_the_sweep_covers_every_exported_rule() -> None:
    """Non-vacuity: the table above must not drift away from the module.

    ``processor.__all__`` re-exports every rule, so it is the authoritative
    list of write sites.  If a rule is added and not added to
    :data:`RULE_TABLE`, this fails instead of the sweep silently narrowing.
    """
    exported = {
        name
        for name in processor.__all__
        if name.startswith("process_") and name.endswith("_file")
    }
    assert exported == set(RULE_IDS), (
        "the dry-run sweep does not cover every exported rule — "
        f"uncovered {sorted(exported - set(RULE_IDS))}, "
        f"stale {sorted(set(RULE_IDS) - exported)}"
    )


@pytest.mark.parametrize("rule_name", RULE_IDS)
def test_every_rule_declares_the_dry_run_parameter(rule_name: str) -> None:
    """The gate is only reachable if every rule accepts ``dry_run`` at all."""
    signature = inspect.signature(getattr(rules, rule_name))
    assert "dry_run" in signature.parameters, (
        f"{rule_name} has no dry_run parameter, so the CLI flag cannot reach it"
    )
    assert signature.parameters["dry_run"].default is False, (
        f"{rule_name}'s dry_run does not default to False — a caller that "
        f"forgot the flag would silently stop writing"
    )


# ---------------------------------------------------------------------------
# Sweep 2 — real encoded files, outcome on disk
# ---------------------------------------------------------------------------


def _make_real(path: Path, fmt: str) -> Path:
    """Export a real audio file of *fmt* and give it slash-bearing tags.

    Raises the exporter's own error when the host lacks the encoder; callers
    turn that into an attributable skip.
    """
    AudioSegment.silent(duration=20).export(str(path), format=fmt)
    opener = _OPENERS[fmt]
    audio = opener(str(path))
    if audio.tags is None:
        audio.add_tags()
    if fmt in ("mp3", "wav", "aiff"):
        audio.tags.add(TCON(encoding=3, text=ORIGINAL_VALUE))
        audio.tags.add(TXXX(encoding=3, desc="ALBUMGENRE", text=ORIGINAL_VALUE))
    else:
        for key in TAG_MAPPINGS[fmt]["standard"] + TAG_MAPPINGS[fmt]["txxx"]:
            audio[key] = ORIGINAL_VALUE
    audio.save()
    return path


def _read_value(path: Path, fmt: str) -> str:
    """Re-read one rewritten value from disk with a fresh mutagen handle.

    Mutagen is inconsistent about list-valued tags: Vorbis comments return a
    one-element list, an MP4 atom returns a scalar, and an ID3 frame exposes a
    ``text`` list.  This normalises all three to the single string the suite's
    own ``update_value`` operates on, so a comparison never depends on which
    container happens to wrap the value.
    """
    audio = _OPENERS[fmt](str(path))
    if fmt in ("mp3", "wav", "aiff"):
        assert audio.tags is not None
        raw = audio.tags["TCON"]
        text = getattr(raw, "text", None)
        if text is not None:
            return str(text[0])
        return str(raw)
    raw = audio[TAG_MAPPINGS[fmt]["standard"][-1]]
    return str(raw[0]) if isinstance(raw, list) and raw else str(raw)


def _build_real(tmp_path: Path, fmt: str, name: str) -> Path:
    """Build the real-file fixture, skipping with a reason if unencodable."""
    path = tmp_path / name
    try:
        return _make_real(path, fmt)
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(
            f"this host cannot encode {fmt} for the real-file dry-run check "
            f"({type(exc).__name__}) — the marker sweep still covers the rule"
        )


@pytest.mark.parametrize("fmt", REAL_FORMATS)
class TestDryRunLeavesRealFilesUntouched:
    """The outcome-correctness evidence: nothing on disk moved."""

    def test_the_fixture_really_carries_a_slash(self, tmp_path: Path, fmt: str) -> None:
        """Guard the guard: a fixture with nothing to rewrite proves nothing."""
        path = _build_real(tmp_path, fmt, f"fixture.{fmt}")
        assert "/" in _read_value(path, fmt)

    def test_dry_run_preserves_bytes_and_mtime(self, tmp_path: Path, fmt: str) -> None:
        rule = getattr(rules, f"process_{fmt}_file")
        path = _build_real(tmp_path, fmt, f"real.{fmt}")

        before_digest = digest(path)
        before_mtime = path.stat().st_mtime_ns

        result = rule(path, dry_run=True)

        assert result.error is None
        assert result.updated is True
        assert result.tags_updated
        assert digest(path) == before_digest
        assert path.stat().st_mtime_ns == before_mtime
        assert _read_value(path, fmt) == ORIGINAL_VALUE

    def test_live_run_rewrites_the_real_file(self, tmp_path: Path, fmt: str) -> None:
        """The contrast half on real audio."""
        rule = getattr(rules, f"process_{fmt}_file")
        path = _build_real(tmp_path, fmt, f"live.{fmt}")
        before_digest = digest(path)

        result = rule(path)

        assert result.updated is True
        assert digest(path) != before_digest
        assert REWRITTEN_VALUE in _read_value(path, fmt)


@pytest.mark.parametrize("fmt", REAL_FORMATS)
def test_dry_run_then_live_leaves_the_file_actionable(tmp_path: Path, fmt: str) -> None:
    """A dry run must leave the file in a state a later live run can act on."""
    rule = getattr(rules, f"process_{fmt}_file")
    path = _build_real(tmp_path, fmt, f"sequence.{fmt}")

    rule(path, dry_run=True)
    assert _read_value(path, fmt) == ORIGINAL_VALUE

    rule(path)
    assert REWRITTEN_VALUE in _read_value(path, fmt)


def test_a_rule_with_no_pending_change_is_unaffected_by_the_flag(
    tmp_path: Path,
) -> None:
    """The gate must not turn a no-op file into an error or a phantom update."""
    path = _build_real(tmp_path, "mp3", "clean.mp3")
    tags = ID3()
    tags.add(TCON(encoding=3, text="Rock"))
    tags.save(str(path))

    for dry_run in (True, False):
        result = rules.process_mp3_file(path, dry_run=dry_run)
        assert result.updated is False
        assert result.tags_updated == ()
        assert result.error is None
        assert _read_value(path, "mp3") == "Rock"
