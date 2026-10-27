"""Locks for ``tests/external_records.py``: the committed-record mechanism.

The helper exists so that checks resting on a file this repository cannot
version still run, and can still fail, on a runner that has no copy of it.  A
mechanism like that has one dangerous failure mode - a record that parses to
something weaker than it claims, or a fixture that cannot fail - because it
replaces a visible failure (a skip) with an invisible one (a green run that
checked nothing).  These locks close that mode, and they do it with records
written *here*, so nothing in this file depends on the one record the
repository currently commits.

Four things are locked:

1. **The directory is honest.**  Every record under ``tests/data/external/``
   loads, is complete, builds a fixture that reproduces it heading-for-heading,
   and can fail - a dropped heading or marker is reported.  A record no test
   module names is an orphaned claim and fails too.
2. **The loader refuses.**  Every field is validated on load, with a positive
   control proving the shapes in the refusal table are refusals rather than
   normalcy, so a typo cannot silently weaken the checks that read the record.
3. **The recorder round-trips.**  A built record writes as UTF-8 without a BOM,
   CRLF, and reloads equal to itself; only the requested heading levels are
   recorded; a marker the file does not carry cannot be recorded at all.
4. **The fixture serves both sources.**  A missing external file is
   materialized with its twin, and a present one is read as-is, with ``origin``
   saying which was served.

Changed in 1.1.0: initial version.
Changed in 1.2.0: added with the generalized external-record helper - the
directory, loader, recorder and fixture contracts above, each with its own
non-vacuity control.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from tests.external_records import (
    RECORDS_DIR,
    REPO_ROOT,
    ExternalRecord,
    ExternalRecordError,
    build_record,
    headings_at,
    load_record,
    materialize,
    missing_headings,
    missing_markers,
    re_record_command,
    record_paths,
    resolve_template,
    serialize_record,
    twin_matches,
    under_test,
    write_record,
)

#: Directory parts the walk never reads.  ``build``/``dist`` are the installer's
#: gitignored output (``packaging/build``): the staged payload carries a bundled
#: CPython whose own ``Lib/test`` corpus is not UTF-8, so the owner scan raised
#: ``UnicodeDecodeError`` for any developer who had built the installer.  CI never
#: builds it, which is why it went unnoticed.
#: Changed in 2.1.6 (R-15, PLAN_audit_2026-10-24_deferred_p2p3.md): added.
_SKIP_DIRS = frozenset(
    {".git", ".venv", "__pycache__", "node_modules", "build", "dist"}
)

#: Marks a key as absent rather than set to a value, for the refusal table.
_REMOVE = object()


def _first_party_python_sources() -> list[Path]:
    """Return every first-party ``*.py`` file, pruning the trees that are not ours.

    Returns:
        The paths.  Pruning matters: a walk that descends into ``.venv`` would
        read tens of thousands of third-party files and find nothing.
    """
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = sorted(name for name in dirnames if name not in _SKIP_DIRS)
        found += [
            Path(dirpath) / name for name in sorted(filenames) if name.endswith(".py")
        ]
    return found


def _write_raw(tmp_path: Path, **overrides: Any) -> Path:
    """Write a well-formed record to ``tmp_path`` with ``overrides`` applied.

    A key mapped to ``_REMOVE`` is deleted rather than set, so the absence of
    an optional field can be exercised as well as its mis-statement.

    Args:
        tmp_path: Where to write the record.
        **overrides: Top-level keys to set, or ``_REMOVE`` to drop.

    Returns:
        The record's path.
    """
    data: dict[str, Any] = {
        "_comment": "A record written by the lock for tests/external_records.py.",
        "_recorded": "2026-10-16",
        "_source": "%USERPROFILE%/.config/example/AGENTS.md",
        "_twin": None,
        "provenance": {"sha256": "a" * 64, "bytes": 42},
        "headings": {"2": ["Alpha"], "3": ["Beta"]},
        "markers": ["must appear"],
    }
    for key, value in overrides.items():
        if value is _REMOVE:
            data.pop(key, None)
        else:
            data[key] = value
    path = tmp_path / "record.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _sample_record(
    tmp_path: Path, *, source_exists: bool, twin: bool = False
) -> ExternalRecord:
    """Build a record for a sample external file written inside ``tmp_path``.

    Args:
        tmp_path: Scratch directory.
        source_exists: Keep the external file, or delete it so the fixture path
            is the one exercised.
        twin: Record a twin path for the external file.

    Returns:
        The record, pointing at ``tmp_path`` so nothing here depends on the
        host's own files.
    """
    source = tmp_path / "live" / "AGENTS.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "# Sample\n\n## Alpha\n\n### Beta\n\nthe sample rule: must appear.\n",
        encoding="utf-8",
    )
    record = build_record(
        source,
        record_path=tmp_path / "records" / "sample.json",
        source_template=str(source),
        twin_template=str(tmp_path / "kilo" / "AGENTS.md") if twin else None,
        comment="A sample record built by the lock for tests/external_records.py.",
        markers=["must appear"],
    )
    if not source_exists:
        source.unlink()
    return record


class TestRecordDirectory:
    """Every committed record is complete, faithful, breakable and referenced."""

    def test_the_directory_holds_records(self) -> None:
        assert RECORDS_DIR.name == "external", RECORDS_DIR
        assert record_paths(), "no external-file records found"

    def test_every_record_is_named_by_a_test_module(self) -> None:
        """A record nothing references is a claim nothing checks."""
        sources = _first_party_python_sources()
        assert len(sources) > 100, f"the owner scan reached only {len(sources)} files"
        texts = [(path, path.read_text(encoding="utf-8")) for path in sources]
        orphaned = [
            path.name
            for path in record_paths()
            if not any(path.name in text for _, text in texts)
        ]
        assert not orphaned, (
            "records that no test module names, so nothing checks them:\n  "
            + "\n  ".join(orphaned)
        )

    def test_every_record_is_complete(self) -> None:
        """The loader is the authority; this asserts what it cannot know."""
        for path in record_paths():
            record = load_record(path)
            assert len(record.comment) >= 80, f"{path}: the comment says too little"
            assert resolve_template(record.source_template).is_absolute(), path
            if record.twin_template is not None:
                assert resolve_template(record.twin_template).is_absolute(), path
            assert record.headings or record.markers, path

    def test_every_record_builds_a_faithful_fixture(self) -> None:
        """The materialized body must reproduce the record exactly, level by level."""
        for path in record_paths():
            record = load_record(path)
            body = materialize(record, preamble="Materialized for the lock.")
            for level in sorted(record.headings):
                assert headings_at(body, level) == list(record.headings[level]), (
                    f"{path}: level {level} does not round-trip through materialize()"
                )
            assert not missing_headings(record, body), path
            assert not missing_markers(record, body), path

    def test_every_record_can_fail(self) -> None:
        """A fixture that cannot fail is worse than none (repository rule)."""
        for path in record_paths():
            record = load_record(path)
            body = materialize(record, preamble="Materialized for the lock.")
            level = sorted(record.headings)[0]
            dropped = record.headings[level][0]
            broken = body.replace(f"{'#' * level} {dropped}\n", "")
            assert broken != body, f"{path}: the fixture never carried {dropped!r}"
            assert missing_headings(record, broken) == [dropped], (
                f"{path}: a dropped level-{level} heading went unnoticed"
            )
            for marker in record.markers:
                unmarked = body.replace(marker, "")
                assert unmarked != body, f"{path}: the fixture never carried {marker!r}"
                assert missing_markers(record, unmarked) == [marker], (
                    f"{path}: a dropped marker went unnoticed"
                )


class TestLoaderRefuses:
    """Anything the checks read must be stated, or loading fails by name."""

    def test_the_written_record_loads(self, tmp_path: Path) -> None:
        """Positive control: the shapes below are refusals, not normalcy."""
        record = load_record(_write_raw(tmp_path))
        assert record.source_template.endswith("AGENTS.md")
        assert record.twin_template is None
        assert record.headings[2] == ("Alpha",)
        assert record.headings[3] == ("Beta",)
        assert record.markers == ("must appear",)
        assert record.extra == {}
        assert record.recorded == "2026-10-16"

    def test_headings_may_be_omitted_when_markers_are_recorded(
        self, tmp_path: Path
    ) -> None:
        """A markers-only record is a legitimate contract, not a broken one."""
        record = load_record(_write_raw(tmp_path, headings=_REMOVE))
        assert record.headings == {}
        assert record.markers == ("must appear",)

    def test_an_absent_record_is_reported_by_name(self, tmp_path: Path) -> None:
        with pytest.raises(ExternalRecordError, match="no such record"):
            load_record(tmp_path / "absent.json")

    def test_non_json_is_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "record.json"
        path.write_text("not json", encoding="utf-8")
        with pytest.raises(ExternalRecordError, match="unreadable record"):
            load_record(path)

    def test_a_non_object_is_reported(self, tmp_path: Path) -> None:
        path = tmp_path / "record.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(ExternalRecordError, match="JSON object"):
            load_record(path)

    @pytest.mark.parametrize(
        ("overrides", "match"),
        [
            ({"verdict": {"rule": "stale"}}, "unknown key"),
            ({"_comment": ""}, "_comment"),
            ({"_comment": _REMOVE}, "_comment"),
            ({"_recorded": "16-10-2026"}, "_recorded"),
            ({"_recorded": _REMOVE}, "_recorded"),
            ({"_source": "  "}, "_source"),
            ({"_source": _REMOVE}, "_source"),
            ({"_twin": 5}, "_twin"),
            ({"provenance": _REMOVE}, "provenance"),
            ({"provenance": {"sha256": "A" * 64, "bytes": 42}}, "sha256"),
            ({"provenance": {"sha256": "abc", "bytes": 42}}, "sha256"),
            ({"provenance": {"sha256": "a" * 64, "bytes": 0}}, "bytes"),
            ({"provenance": {"sha256": "a" * 64, "bytes": True}}, "bytes"),
            ({"headings": "2"}, "headings must be an object"),
            ({"headings": {"two": ["Alpha"]}}, "heading level"),
            ({"headings": {"2": []}}, "records no headings"),
            ({"headings": {"2": ["  "]}}, "empty heading"),
            ({"markers": "must appear"}, "markers must be a list"),
            ({"markers": [5]}, "non-empty strings"),
            ({"extra": []}, "extra must be an object"),
        ],
    )
    def test_a_malformed_record_is_refused(
        self, tmp_path: Path, overrides: dict[str, Any], match: str
    ) -> None:
        with pytest.raises(ExternalRecordError, match=match):
            load_record(_write_raw(tmp_path, **overrides))

    def test_a_record_that_claims_nothing_is_refused(self, tmp_path: Path) -> None:
        """Both halves dropped: every check built on it would pass vacuously."""
        with pytest.raises(ExternalRecordError, match="claims nothing"):
            load_record(_write_raw(tmp_path, headings=_REMOVE, markers=[]))


class TestRecorderRoundTrip:
    """A record written here must reload as the same record."""

    def test_a_built_record_round_trips_through_disk(self, tmp_path: Path) -> None:
        record = _sample_record(tmp_path, source_exists=True, twin=True)
        record = replace(record, extra={"rule": "the sample rule"})
        raw = write_record(record)

        assert raw[:3] != b"\xef\xbb\xbf", "a record must not carry a BOM"
        assert raw.count(b"\n") == raw.count(b"\r\n"), "a record must be CRLF"
        assert raw.endswith(b"\r\n"), "a record must end its last line"
        assert record.path.read_bytes() == raw == serialize_record(record)
        reloaded = load_record(record.path)
        assert reloaded == record
        assert reloaded.extra == {"rule": "the sample rule"}
        assert reloaded.twin_template == record.twin_template
        assert reloaded.headings == {2: ("Alpha",), 3: ("Beta",)}

    def test_only_the_requested_levels_are_recorded(self, tmp_path: Path) -> None:
        source = tmp_path / "EXTERNAL.md"
        source.write_text("# Title\n\n## Alpha\n\n### Beta\n", encoding="utf-8")
        record = build_record(
            source,
            record_path=tmp_path / "record.json",
            source_template=str(source),
            twin_template=None,
            comment="A record asking for level two only.",
            levels=(2,),
        )
        assert record.headings == {2: ("Alpha",)}

    def test_a_marker_the_file_does_not_carry_cannot_be_recorded(
        self, tmp_path: Path
    ) -> None:
        """Recording a false marker would make the live check unpassable."""
        source = tmp_path / "EXTERNAL.md"
        source.write_text("## Alpha\n\nnothing else.\n", encoding="utf-8")
        with pytest.raises(
            ExternalRecordError, match="markers the file does not carry"
        ):
            build_record(
                source,
                record_path=tmp_path / "record.json",
                source_template=str(source),
                twin_template=None,
                comment="A record with a marker the file lacks.",
                markers=["must appear"],
            )

    def test_a_missing_source_cannot_be_recorded(self, tmp_path: Path) -> None:
        with pytest.raises(ExternalRecordError, match="cannot read the external file"):
            build_record(
                tmp_path / "absent.md",
                record_path=tmp_path / "record.json",
                source_template="%USERPROFILE%/absent.md",
                twin_template=None,
                comment="A record for a file that is not there.",
            )

    def test_every_record_in_the_directory_still_names_its_owner(self) -> None:
        """The documented re-record line must keep naming things that exist."""
        command = re_record_command(
            "tests.test_agents_md", "GLOBAL_BASELINE", "record_global_baseline"
        )
        assert command.startswith('python -c "from tests.test_agents_md import ')
        assert "record_global_baseline(GLOBAL_BASELINE)" in command


class TestTemplateResolution:
    """Records are portable: the host reading one supplies its own paths."""

    def test_the_home_token_expands_to_the_reading_host(self) -> None:
        resolved = resolve_template("%USERPROFILE%/.config/example/AGENTS.md")
        assert resolved.is_absolute()
        assert str(Path.home()) in str(resolved)
        assert "%USERPROFILE%" not in str(resolved)

    def test_an_unknown_token_is_left_verbatim(self) -> None:
        """Guessing at a token would resolve to somewhere plausible and wrong."""
        assert str(resolve_template("%APPDATA%/example")) == str(
            Path("%APPDATA%/example")
        )

    def test_a_plain_path_is_unchanged(self) -> None:
        assert resolve_template("tests/data/external/x.json") == Path(
            "tests/data/external/x.json"
        )


class TestUnderTestServesBothSources:
    """The fixture is chosen by what exists, and says which it served."""

    def test_a_missing_external_file_is_materialized(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        record = _sample_record(tmp_path, source_exists=False, twin=True)
        served = under_test(
            record, tmp_path_factory=tmp_path_factory, preamble="Materialized."
        )

        assert served.synthetic is True
        assert served.origin == f"a fixture materialized from {record.name}"
        assert served.live.is_file()
        assert not missing_headings(record, served.text)
        assert not missing_markers(record, served.text)
        assert served.twin is not None and served.twin.is_file()
        assert twin_matches(served.twin, served.live.read_bytes())

        # Where the volume allowed the hardlink the fixture twin is the same
        # file, so making it disagree means breaking the link - which is how a
        # real divergent twin presents itself too.
        served.twin.unlink()
        served.twin.write_bytes(served.live.read_bytes() + b"drift\n")
        assert not twin_matches(served.twin, served.live.read_bytes()), (
            "a divergent twin must compare unequal, or the comparison is inert"
        )

    def test_a_missing_twin_is_reported_as_no_twin(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        record = _sample_record(tmp_path, source_exists=False, twin=False)
        served = under_test(record, tmp_path_factory=tmp_path_factory)
        assert served.synthetic is True
        assert served.twin is None

    def test_a_present_external_file_is_read_as_it_is(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        record = _sample_record(tmp_path, source_exists=True, twin=False)
        served = under_test(record, tmp_path_factory=tmp_path_factory)

        assert served.synthetic is False
        assert served.origin == "the real file"
        assert served.live == record.source
        assert served.text == record.source.read_text(encoding="utf-8")
        assert served.twin is None

    def test_a_present_file_without_its_twin_reports_no_twin(
        self, tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        """The twin is named but absent: the pair claim cannot be checked here."""
        record = _sample_record(tmp_path, source_exists=True, twin=True)
        assert record.twin is not None and not record.twin.is_file()
        served = under_test(record, tmp_path_factory=tmp_path_factory)
        assert served.synthetic is False
        assert served.twin is None
