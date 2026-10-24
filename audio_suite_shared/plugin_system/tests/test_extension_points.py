"""Tests for :mod:`audio_suite_shared.plugin_system.extension_points`.

The hosts trust these helpers to turn a plugin's arbitrary return value into
something they can count and log, and to refuse a value they cannot report.
Each accepted and each refused shape therefore has a case here.

Changed in 2.1.0: new file — the extension-point contracts (Sprint 7).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from audio_suite_shared.plugin_system import extension_points as ep
from audio_suite_shared.plugin_system.models import ContributionSpec, PluginError


class TestNormaliseOutcome:
    def test_none_is_unchanged(self) -> None:
        assert ep.normalise_outcome(None) == ep.TagProcessorOutcome(changed=False)

    @pytest.mark.parametrize("value", [True, False])
    def test_bool_is_the_changed_flag(self, value: bool) -> None:
        assert ep.normalise_outcome(value).changed is value

    def test_outcome_passes_through(self) -> None:
        outcome = ep.TagProcessorOutcome(changed=True, message="rewrote genre")

        assert ep.normalise_outcome(outcome) is outcome

    def test_object_with_changed_attribute_is_accepted(self) -> None:
        class Result:
            changed = True
            message = "trimmed"

        normalised = ep.normalise_outcome(Result())

        assert normalised == ep.TagProcessorOutcome(changed=True, message="trimmed")

    def test_object_without_changed_is_refused(self) -> None:
        with pytest.raises(PluginError, match="must return None, a bool"):
            ep.normalise_outcome(object())


class TestRunTagProcessor:
    def test_dry_run_is_passed_positionally(self, tmp_path: Path) -> None:
        seen: dict[str, Any] = {}

        def hook(path: Path, dry_run: bool) -> bool:
            seen["path"] = path
            seen["dry_run"] = dry_run
            return True

        outcome = ep.run_tag_processor(hook, tmp_path / "a.mp3", dry_run=True)

        assert outcome.changed is True
        assert seen["dry_run"] is True

    def test_context_is_passed_only_when_declared(self, tmp_path: Path) -> None:
        seen: list[object] = []

        def with_context(path: Path, dry_run: bool, *, context: object) -> None:
            seen.append(context)

        def without_context(path: Path, dry_run: bool) -> None:
            seen.append("plain")

        context = ep.context_for("demo")
        ep.run_tag_processor(
            with_context, tmp_path / "a.mp3", dry_run=False, context=context
        )
        ep.run_tag_processor(
            without_context, tmp_path / "a.mp3", dry_run=False, context=context
        )

        assert seen == [context, "plain"]


class TestRunAnalysis:
    def test_scalars_are_returned(self, tmp_path: Path) -> None:
        def hook(path: Path, tags: Mapping[str, Any]) -> dict[str, Any]:
            return {"words": 3, "mean": 1.5, "state": "present"}

        assert ep.run_analysis(hook, tmp_path / "a.mp3", {"title": "a b c"}) == {
            "words": 3,
            "mean": 1.5,
            "state": "present",
        }

    def test_non_mapping_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError, match="must return a mapping"):
            ep.run_analysis(lambda path, tags: 3, tmp_path / "a.mp3", {})

    def test_bool_metric_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError, match="only int, float and str"):
            ep.run_analysis(lambda path, tags: {"ok": True}, tmp_path / "a.mp3", {})

    def test_non_scalar_metric_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError, match="only int, float and str"):
            ep.run_analysis(lambda path, tags: {"bad": ["a"]}, tmp_path / "a.mp3", {})

    def test_empty_metric_name_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError, match="non-empty strings"):
            ep.run_analysis(lambda path, tags: {"": 1}, tmp_path / "a.mp3", {})

    def test_context_is_passed_to_an_analysis_hook(self, tmp_path: Path) -> None:
        seen: list[object] = []

        def hook(
            path: Path, tags: Mapping[str, Any], *, context: object
        ) -> dict[str, int]:
            seen.append(context)
            return {"n": len(tags)}

        context = ep.context_for("demo")
        assert ep.run_analysis(
            hook, tmp_path / "a.mp3", {"title": "x"}, context=context
        ) == {"n": 1}
        assert seen == [context]


class TestAcceptsContext:
    def test_named_parameter(self) -> None:
        assert ep.accepts_context(lambda path, context: None) is True

    def test_keyword_catch_all(self) -> None:
        assert ep.accepts_context(lambda path, **kwargs: None) is True

    def test_plain_signature(self) -> None:
        assert ep.accepts_context(lambda path: None) is False


class TestPluginContext:
    def test_logger_is_named_after_the_plugin(self) -> None:
        context = ep.context_for("demo_plugin")

        assert context.plugin_id == "demo_plugin"
        assert context.logger.name == "audio_suite.plugins.demo_plugin"

    def test_read_tags_delegates_to_the_tag_layer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import audio_suite_shared.tag_helper as tag_helper

        monkeypatch.setattr(
            tag_helper,
            "read_editable_tags",
            lambda path: {"title": "T", "genre": None},
        )

        tags = ep.context_for("demo").read_tags(tmp_path / "a.mp3")

        assert tags == {"title": "T", "genre": None}

    def test_write_tag_refuses_an_unknown_field(self, tmp_path: Path) -> None:
        with pytest.raises(PluginError, match="not an editable tag field"):
            ep.context_for("demo").write_tag(tmp_path / "a.mp3", "notafield", "x")

    def test_write_tag_delegates_to_the_tag_layer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import audio_suite_shared.tag_helper as tag_helper

        written: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            tag_helper,
            "write_editable_tag",
            lambda path, field, value: written.append((path, field, value)),
        )

        ep.context_for("demo").write_tag(tmp_path / "a.mp3", "genre", "Rock")

        assert written == [(str(tmp_path / "a.mp3"), "genre", "Rock")]

    def test_editable_fields_come_from_the_tag_layer(self) -> None:
        fields = ep.context_for("demo").editable_fields

        assert "genre" in fields
        assert "title" in fields


class TestResolvedContributions:
    def test_a_failing_plugin_is_skipped_and_the_rest_load(self) -> None:
        good = ContributionSpec(
            plugin_id="good",
            kind="tag_processor",
            id="a",
            name="A",
            entry_point="g:apply",
        )
        bad = ContributionSpec(
            plugin_id="bad",
            kind="tag_processor",
            id="b",
            name="B",
            entry_point="b:apply",
        )

        def resolve(spec: ContributionSpec) -> object:
            if spec.plugin_id == "bad":
                raise PluginError("boom")
            return "hook"

        resolved = ep.resolved_contributions((good, bad), resolve)

        assert resolved == ((good, "hook"),)
