"""
Tests for audio_suite_shared.tool_plugin (G-NEW — Plugin System).

Verifies ToolManifest, ToolRegistry construction, and the first-party
manifest definitions.

Changed in 1.3.0: the expected sets add the ``spectral_viewer`` manifest
(Sprint 3, D42).
Changed in 2.0.0: the expected sets add the ``stem_separator`` manifest and
its ``stems`` command (Sprint 6, Item 6.1).
"""

from audio_suite_shared.exceptions import AudioConfigurationError
from audio_suite_shared.tool_plugin import (
    ToolManifest,
    ToolRegistry,
    get_registry,
)


class TestToolManifest:
    def test_minimal_construction(self):
        m = ToolManifest(
            id="test", name="Test", category="enrich", pyw_filename="test.pyw"
        )
        assert m.id == "test"
        assert m.name == "Test"
        assert m.category == "enrich"
        assert m.pyw_filename == "test.pyw"

    def test_frozen(self):
        m = ToolManifest(id="a", name="A", category="b", pyw_filename="c")
        import dataclasses

        assert dataclasses.is_dataclass(m)
        assert m.id == "a"


class TestToolRegistry:
    def test_empty_registry(self):
        r = ToolRegistry()
        assert len(r) == 0
        assert r.all == []
        assert r.by_category("enrich") == []
        assert r.get("nonexistent") is None

    def test_register_and_get(self):
        r = ToolRegistry()
        m = ToolManifest(
            id="foo", name="Foo", category="enrich", pyw_filename="foo.pyw"
        )
        r.register(m)
        assert r.get("foo") is m
        assert "foo" in r

    def test_register_duplicate_raises(self):
        r = ToolRegistry()
        r.register(ToolManifest(id="dup", name="A", category="e", pyw_filename="a.pyw"))
        import pytest

        with pytest.raises(AudioConfigurationError, match="dup"):
            r.register(
                ToolManifest(id="dup", name="B", category="u", pyw_filename="b.pyw")
            )

    def test_by_category_filters(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="a", name="A", category="enrich", pyw_filename="a.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="b", name="B", category="utility", pyw_filename="b.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="c", name="C", category="enrich", pyw_filename="c.pyw", order=20
            )
        )

        enrich = r.by_category("enrich")
        assert len(enrich) == 2
        assert all(m.category == "enrich" for m in enrich)

        utility = r.by_category("utility")
        assert len(utility) == 1
        assert utility[0].id == "b"

    def test_by_category_sorted_by_order(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="z", name="Z", category="enrich", pyw_filename="z.pyw", order=50
            )
        )
        r.register(
            ToolManifest(
                id="a", name="A", category="enrich", pyw_filename="a.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="m", name="M", category="enrich", pyw_filename="m.pyw", order=30
            )
        )

        ids = [m.id for m in r.by_category("enrich")]
        assert ids == ["a", "m", "z"]

    def test_all_sorted(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="b", name="B", category="utility", pyw_filename="b.pyw", order=20
            )
        )
        r.register(
            ToolManifest(
                id="a", name="A", category="enrich", pyw_filename="a.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="c", name="C", category="refinery", pyw_filename="c.pyw", order=30
            )
        )

        all_m = r.all
        assert len(all_m) == 3
        # Sorted by (category, order)
        assert all_m[0].id == "a"  # enrich, 10
        assert all_m[1].id == "c"  # refinery, 30
        assert all_m[2].id == "b"  # utility, 20

    def test_by_cli(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="a", name="A", category="e", pyw_filename="a.pyw", cli_command="alfa"
            )
        )
        r.register(ToolManifest(id="b", name="B", category="e", pyw_filename="b.pyw"))
        r.register(
            ToolManifest(
                id="c",
                name="C",
                category="e",
                pyw_filename="c.pyw",
                cli_command="charlie",
            )
        )

        cli_cmds = r.by_cli()
        assert len(cli_cmds) == 2
        assert [m.cli_command for m in cli_cmds] == ["alfa", "charlie"]


class TestDefaultRegistry:
    def test_get_registry_is_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_registry_is_populated(self):
        r = get_registry()
        assert len(r) >= 16  # all first-party tools
        assert len(r) == 29  # 11 enrich + 17 utility + 1 refinery

    def test_has_all_enrich_tools(self):
        r = get_registry()
        ids = {m.id for m in r.by_category("enrich")}
        expected = {
            "scrubber",
            "replaygain",
            "fingerprinter",
            "album_genre",
            "genre_sync",
            "bpm",
            "tempo",
            "key",
            "mood_analyzer",
            "art",
            "lyrics_manager",
        }
        assert ids == expected

    def test_has_all_utility_tools(self):
        r = get_registry()
        ids = {m.id for m in r.by_category("utility")}
        expected = {
            "converter",
            "asx_extractor",
            "album_art_normalizer",
            "cd_ripper",
            "mood_analysis_batch",
            "library_stats",
            "file_reorganizer",
            "tag_field_updater",
            "tag_editor",
            "noise_reduction",
            "undo_tag_edits",
            "audio_enhancer",
            "audio_normalizer",
            "pop_click_remover",
            "silence_trimmer",
            "spectral_viewer",
            "stem_separator",
        }
        assert ids == expected

    def test_has_refinery(self):
        r = get_registry()
        ids = {m.id for m in r.by_category("refinery")}
        assert "audio_refinery" in ids

    def test_cli_commands_match_expected(self):
        r = get_registry()
        commands = {m.cli_command for m in r.by_cli()}
        expected = {
            "scrub",
            "fingerprint",
            "replaygain",
            "genre-sync",
            "bpm",
            "tempo",
            "key",
            "mood-analyzer",
            "convert",
            "stats",
            "reorganize",
            "album-genre",
            "album-art",
            "asx-extract",
            "artnormalize",
            "cd-rip",
            "mood-analysis-batch",
            "tag-update",
            "tag-edit",
            "reduce",
            "lyrics",
            "enhance",
            "normalise",
            "declick",
            "silence-trim",
            "spectrogram",
            "stems",
            # Plan G2: the CLI subcommand is `refine`, and the manifest now
            # says so instead of leaving audio_refinery CLI-less by omission.
            "refine",
        }
        assert commands == expected

    def test_standalone_tools(self):
        r = get_registry()
        standalone = {m.id for m in r.all if m.standalone}
        expected = {
            "cd_ripper",
            "mood_analysis_batch",
            "library_stats",
            "fingerprinter",
            "audio_refinery",
            "file_reorganizer",
            "tag_field_updater",
            "tag_editor",
            "noise_reduction",
            "undo_tag_edits",
            "audio_enhancer",
            "audio_normalizer",
            "pop_click_remover",
            "silence_trimmer",
            "spectral_viewer",
            "stem_separator",
        }
        assert standalone == expected

    def test_undo_tool_appears_last_in_utility_category(self):
        """The Undo Tag Edits card must sit at the bottom of the UTIL tab."""
        r = get_registry()
        utility_ids = [m.id for m in r.by_category("utility")]
        assert utility_ids[-1] == "undo_tag_edits"

    def test_registry_is_frozen(self):
        r = get_registry()
        import pytest

        m = ToolManifest(id="late", name="Late", category="e", pyw_filename="late.pyw")
        with pytest.raises(AudioConfigurationError):
            r.register(m)

    def test_all_returns_a_copy_not_a_live_view(self):
        """Mutating a returned list must not touch the shared registry."""
        r = get_registry()
        before = len(r.all)
        r.all.clear()
        assert len(r.all) == before
        assert len(r) == before

    def test_by_category_returns_a_copy_not_a_live_view(self):
        r = get_registry()
        before = len(r.by_category("utility"))
        r.by_category("utility").clear()
        assert len(r.by_category("utility")) == before

    def test_all_manifests_are_frozen_dataclasses(self):
        """The registry's manifest data itself must resist in-place edits."""
        import dataclasses

        import pytest

        for m in get_registry().all:
            assert dataclasses.is_dataclass(m)
            with pytest.raises(dataclasses.FrozenInstanceError):
                m.name = "tampered"  # type: ignore[misc]
