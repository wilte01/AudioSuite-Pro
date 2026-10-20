"""Lock the recorded CLI payloads against the committed JSON Schema.

``tests/cli_schema_conformance.py`` is the gate the CI workflow runs; this
module makes the same claim from the ordinary suite and, more importantly,
proves the gate can fail.  A conformance check whose only test is "the
committed files pass" is indistinguishable from one that validates nothing, so
every failure mode - missing recording, undeclared command, wrong type,
undeclared field, unreadable file - is mutated here and asserted.

The corpus is validated with ``jsonschema``'s draft 2020-12 validator, i.e. the
way an external consumer validates, rather than the hand-rolled subset in
``tests/test_cli_json_schema.py``.  That file still owns the *live* drives.

Changed in 1.4.1: initial version, the recorded-payload gate for the CLI JSON
contract (PLAN D102).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from audio_suite_shared.cli_schema import SCHEMA_VERSION, TOOL_IDS
from tests import cli_schema_conformance as conformance
from tests.ci_workflow import WORKFLOW as CI_WORKFLOW
from tests.ci_workflow import action as ci_action
from tests.ci_workflow import job as ci_job
from tests.ci_workflow import step as ci_step
from tests.cli_payloads import record_payloads

#: The repository root, so the CI-step lock can find the workflow.
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def corpus() -> conformance.Corpus:
    """The committed corpus, loaded once."""
    return conformance.load_corpus()


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The committed JSON Schema document, loaded once."""
    return conformance.load_schema()


def _payloads(corpus: conformance.Corpus) -> dict[str, dict[str, Any]]:
    """Return a mutable deep copy of the corpus payloads."""
    return copy.deepcopy(dict(corpus.payloads))


class TestCorpusCoverage:
    """The corpus records exactly the commands the schema declares."""

    def test_the_corpus_is_not_empty(self, corpus: conformance.Corpus) -> None:
        assert corpus.payloads, "the corpus recorded no payloads"

    def test_every_declared_command_has_a_recording(
        self, corpus: conformance.Corpus
    ) -> None:
        missing = sorted(set(TOOL_IDS) - set(corpus.payloads))
        assert not missing, (
            "these commands publish JSON but have no recorded payload; run "
            f"`python -m tests.cli_schema_conformance --record`: {missing}"
        )

    def test_no_recording_is_for_an_undeclared_command(
        self, corpus: conformance.Corpus
    ) -> None:
        extra = sorted(set(corpus.payloads) - set(TOOL_IDS))
        assert not extra, f"recorded payloads for commands without a schema: {extra}"

    def test_the_corpus_records_the_current_schema_version(
        self, corpus: conformance.Corpus
    ) -> None:
        assert corpus.schema_version == SCHEMA_VERSION

    def test_the_corpus_carries_its_own_regeneration_note(
        self, corpus: conformance.Corpus
    ) -> None:
        assert "--record" in corpus.comment


class TestConformance:
    """Every recorded payload validates against the committed document."""

    def test_the_whole_corpus_conforms(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        assert conformance.conformance_problems(corpus.payloads, document) == []

    @pytest.mark.parametrize("command", sorted(TOOL_IDS))
    def test_one_payload_conforms(
        self,
        command: str,
        corpus: conformance.Corpus,
        document: dict[str, Any],
    ) -> None:
        payloads = {command: corpus.payloads[command]}

        problems = conformance.conformance_problems(
            payloads, document, expected_commands=[command]
        )

        assert problems == [], f"{command} does not conform: {problems}"

    def test_the_committed_schema_is_a_valid_document(
        self, document: dict[str, Any]
    ) -> None:
        """The real validator must accept the artifact, not just our test code."""
        Draft202012Validator.check_schema(document)
        assert len(document["oneOf"]) == len(TOOL_IDS)


class TestTheCheckCanFail:
    """Each mutation the gate exists to catch is reported, not swallowed."""

    def test_a_missing_recording_is_reported(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        payloads = _payloads(corpus)
        payloads.pop("stats")

        problems = conformance.conformance_problems(payloads, document)

        assert any("no recorded payload" in problem for problem in problems)
        assert any("stats" in problem for problem in problems)

    def test_a_recording_for_an_undeclared_command_is_reported(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        payloads = _payloads(corpus)
        payloads["not-a-command"] = copy.deepcopy(payloads["stats"])

        problems = conformance.conformance_problems(payloads, document)

        assert any("does not declare" in problem for problem in problems)

    def test_a_wrong_typed_field_is_reported(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        payloads = _payloads(corpus)
        payloads["bpm"]["processed"] = "two"

        problems = conformance.conformance_problems(payloads, document)

        assert any(problem.startswith("bpm: processed: ") for problem in problems), (
            problems
        )

    def test_an_undeclared_field_is_reported(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        """``additionalProperties: false`` is what makes this a removal detector."""
        payloads = _payloads(corpus)
        payloads["stats"]["made_up"] = 1

        problems = conformance.conformance_problems(payloads, document)

        assert any("made_up" in problem for problem in problems), problems

    def test_a_payload_for_the_wrong_command_is_reported(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        payloads = _payloads(corpus)
        payloads["bpm"]["command"] = "key"

        problems = conformance.conformance_problems(payloads, document)

        assert any(problem.startswith("bpm: command: ") for problem in problems), (
            problems
        )

    def test_a_duplicate_variant_is_reported(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        doubled = copy.deepcopy(document)
        doubled["oneOf"].append(copy.deepcopy(doubled["oneOf"][0]))

        problems = conformance.conformance_problems(corpus.payloads, doubled)

        assert any("more than once" in problem for problem in problems), problems

    def test_a_dropped_schema_field_is_caught_on_the_recorded_bytes(
        self, corpus: conformance.Corpus, document: dict[str, Any]
    ) -> None:
        """Removing a key the commands emit fails the recorded payloads."""
        payloads = _payloads(corpus)
        # Sanity: the key really is recorded before the schema is narrowed.
        assert "scan_path" in payloads["stats"]
        narrowed = copy.deepcopy(document)
        for variant in narrowed["oneOf"]:
            if variant["properties"]["command"].get("const") == "stats":
                del variant["properties"]["scan_path"]
                break
        else:  # pragma: no cover - the schema always declares ``stats``
            pytest.fail("the schema has no stats variant")

        problems = conformance.conformance_problems(payloads, narrowed)

        assert any("scan_path" in problem for problem in problems), problems


class TestTheGateEntryPoint:
    """The command CI runs exits non-zero exactly when the corpus breaks."""

    def test_the_committed_corpus_passes(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert conformance.main(["--check"]) == 0
        assert "validate against" in capsys.readouterr().out

    def test_a_broken_corpus_fails_loudly(
        self,
        corpus: conformance.Corpus,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        payloads = _payloads(corpus)
        payloads["bpm"]["processed"] = "two"
        broken = tmp_path / "corpus.json"
        conformance.write_corpus(payloads, path=broken)

        code = conformance.main(
            [
                "--check",
                "--corpus",
                str(broken),
                "--schema",
                str(conformance.SCHEMA_PATH),
            ]
        )

        captured = capsys.readouterr()
        assert code == 1
        assert "gate fail: bpm: processed" in captured.err

    def test_a_missing_corpus_is_a_gate_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = conformance.main(["--check", "--corpus", str(tmp_path / "nope.json")])

        assert code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_a_malformed_corpus_is_a_gate_failure(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        corpus = tmp_path / "corpus.json"
        corpus.write_text(json.dumps({"payloads": {"bpm": {}}}), encoding="utf-8")

        code = conformance.main(["--check", "--corpus", str(corpus)])

        captured = capsys.readouterr()
        assert code == 1
        assert "gate fail:" in captured.err


#: The workflow that runs the gate and publishes the artifact.
WORKFLOW = CI_WORKFLOW


class TestTheCiGate:
    """CI runs the check, and never rewrites the artifact it judges."""

    def test_the_workflow_runs_the_conformance_check(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")

        assert "CLI schema conformance" in text
        assert "python -m tests.cli_schema_conformance --check" in text

    def test_the_workflow_never_records(self) -> None:
        """A gate that regenerated its own corpus could not report drift.

        The workflow may (and does) name the command in a comment, so the lock
        looks at executed lines only - a comment cannot rewrite a file.
        """
        executed = [
            line.strip()
            for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
            if "cli_schema_conformance --record" in line
            and not line.strip().startswith("#")
        ]

        assert not executed, f"CI must not record its own corpus: {executed}"

    def test_the_job_installs_the_validator(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")

        assert 'pip install "jsonschema>=4.23"' in text

    def test_the_test_job_exports_the_payloads(self) -> None:
        """The artifact step lives in the test job, per the author request."""
        test_job = ci_job("test")

        assert (
            "python -m tests.cli_schema_conformance --export-dir cli-payloads"
            in test_job
        )

    def test_the_test_job_uploads_them_as_an_artifact(self) -> None:
        test_job = ci_job("test")

        assert "actions/upload-artifact@v4" in test_job
        assert "name: cli-payloads" in test_job
        assert "path: cli-payloads/" in test_job
        # An empty artifact must fail the job, not look like a success.
        assert "if-no-files-found: error" in test_job

    def test_only_one_matrix_leg_publishes(self) -> None:
        """The files come from the committed corpus, so one leg is enough."""
        test_job = ci_job("test")
        matrix = test_job.split("matrix:", 1)[1].split("steps:", 1)[0]
        versions = re.findall(r'"(3\.\d+)"', matrix)

        assert "3.14" in versions, f"the gated version is not in the matrix: {matrix}"
        gated = [
            block
            for block in (
                ci_step(test_job, "Export the recorded CLI payloads"),
                ci_action(test_job, "actions/upload-artifact@v4"),
            )
            if "if: matrix.python-version == '3.14'" in block
        ]
        assert len(gated) == 2, "both the export and the upload must be gated"

    def test_the_artifact_is_only_published_after_a_green_suite(self) -> None:
        """A failing suite skips later steps, so a red run uploads nothing."""
        test_job = ci_job("test")

        assert (
            test_job.index("Run test suite")
            < test_job.index("Export the recorded CLI payloads")
            < test_job.index("actions/upload-artifact@v4")
        )


class TestExportPayloads:
    """The artifact a script author downloads: one file per command."""

    def test_one_file_per_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "cli-payloads"

        assert conformance.main(["--export-dir", str(out)]) == 0

        files = sorted(out.glob("*.json"))
        assert len(files) == len(TOOL_IDS)
        assert {path.stem for path in files} == {
            conformance.slug_for(command) for command in TOOL_IDS
        }
        assert "exported" in capsys.readouterr().out

    def test_each_file_is_the_recorded_payload(
        self, corpus: conformance.Corpus, tmp_path: Path
    ) -> None:
        out = tmp_path / "cli-payloads"
        conformance.main(["--export-dir", str(out)])

        for command in TOOL_IDS:
            path = out / f"{conformance.slug_for(command)}.json"
            assert json.loads(path.read_text(encoding="utf-8")) == dict(
                corpus.payloads[command]
            ), command

    def test_the_exported_files_still_conform(self, tmp_path: Path) -> None:
        out = tmp_path / "cli-payloads"
        conformance.main(["--export-dir", str(out)])
        payloads = {
            payload["command"]: payload
            for payload in (
                json.loads(path.read_text(encoding="utf-8"))
                for path in out.glob("*.json")
            )
        }

        assert (
            conformance.conformance_problems(payloads, conformance.load_schema()) == []
        )

    def test_slugs_are_stable_and_unique(self) -> None:
        slugs = [conformance.slug_for(command) for command in TOOL_IDS]

        assert conformance.slug_for("cue generate") == "cue-generate"
        assert conformance.slug_for("bpm") == "bpm"
        assert len(set(slugs)) == len(slugs), "two commands would share a file"

    def test_a_broken_corpus_is_not_exported(
        self,
        corpus: conformance.Corpus,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The artifact is a promise to consumers; never publish a red one."""
        payloads = _payloads(corpus)
        payloads["bpm"]["processed"] = "two"
        broken = tmp_path / "corpus.json"
        conformance.write_corpus(payloads, path=broken)
        out = tmp_path / "cli-payloads"

        code = conformance.main(["--export-dir", str(out), "--corpus", str(broken)])

        assert code == 1
        assert "gate fail: bpm: processed" in capsys.readouterr().err
        assert not list(out.glob("*.json"))

    def test_the_export_directory_is_gitignored(self) -> None:
        """A local export must not dirtify the tree or be committed.

        The entry itself is required, not a mention: the change note above it
        names the directory too, so a substring check would pass after the
        ignore rule was deleted.
        """
        entries = {
            line.strip()
            for line in (REPO_ROOT / ".gitignore")
            .read_text(encoding="utf-8")
            .splitlines()
        }

        assert "cli-payloads/" in entries


class TestTheRecorder:
    """The corpus is reproducible from the real commands, not hand-written."""

    def test_it_records_every_command_and_the_result_conforms(self) -> None:
        payloads = record_payloads()

        assert set(payloads) == set(TOOL_IDS)
        assert (
            conformance.conformance_problems(payloads, conformance.load_schema()) == []
        )
