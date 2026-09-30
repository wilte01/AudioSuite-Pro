"""Tests for audio_enhancer/cli.py — the ``audiosuite enhance`` command.

Audit A1 (iteration 7, Stage 0) recorded the defect this module locks:
``audio_suite_shared/cli_app.py``'s usage docstring advertised

    audiosuite enhance /path/to/dir --output-dir ... [--preset Moderate] [--dry]

while ``audio_enhancer/cli.py`` declared no ``--dry`` at all, so the documented
command exited 2 with ``Error: No such option: '--dry'``.  The capability
existed everywhere else — ``is_dry_run`` is a real parameter of
``core/file_processor.py`` and is honoured by ``core/processor.py``'s
``process_file`` — so the CLI was the only surface missing it.

Two things are pinned here, and the second is the one that matters:

1. *The seam* — ``--dry`` resolves and reaches ``run_enhancement`` as
   ``is_dry_run=True``.  Asserting only that the flag parses would pass against
   a CLI that accepted the flag and dropped it, which is the
   "mode flags must be traced end-to-end to the write site" trap.
2. *The outcome* — a real MP3 is enhanced through the real chain in Dry Run:
   no output file appears, the source's SHA-256 and mtime are unchanged, and
   the run still reports DONE with measurements.  A control run of the same
   fixture in Live mode does write, so the dry-run assertion is a real
   difference rather than a vacuous pass.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from audio_suite_shared.cli_app import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def music_dir(tmp_path: Path) -> Path:
    """A directory holding one real, decodable MP3."""
    d = tmp_path / "music"
    d.mkdir()
    _write_mp3(d / "track.mp3")
    return d


def _write_mp3(path: Path, duration_s: float = 2.0) -> None:
    """Export a real MP3 so the enhancer's own decode path is exercised.

    A 440 Hz tone, not digital silence: a silent file measures as -inf dBFS and
    the chain's own gating could legitimately skip the measurement, which
    would make the "reports measurements" assertion pass for the wrong reason.
    """
    import numpy as np
    from pydub import AudioSegment

    n = int(44100 * duration_s)
    t = np.arange(n, dtype=np.float64) / 44100.0
    mono = (0.5 * np.sin(2.0 * np.pi * 440.0 * t) * 32767.0).astype("<i2")
    stereo = np.repeat(mono[:, None], 2, axis=1).tobytes()
    AudioSegment(stereo, frame_rate=44100, sample_width=2, channels=2).export(
        str(path), format="mp3", bitrate="192k"
    )


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(path: Path) -> tuple[str, float]:
    """SHA-256 and mtime, the two properties a write would disturb."""
    return _digest(path), path.stat().st_mtime


# ── The CLI → core seam ───────────────────────────────────────────────────────


class TestDryFlagReachesCore:
    """``--dry`` must resolve *and* arrive at ``run_enhancement``."""

    @staticmethod
    def _run(runner: CliRunner, music_dir: Path, out: Path, *extra: str) -> object:
        from audio_enhancer.core import file_processor

        # The CLI imports the name inside the function body, so the patch
        # target is the defining module (AGENTS.md, "Mock patch target follows
        # the import, not the caller").
        with patch.object(file_processor, "run_enhancement") as mock_run:
            result = runner.invoke(
                cli,
                ["enhance", str(music_dir), "--output-dir", str(out), *extra],
            )
        assert mock_run.call_count == 1, (
            f"run_enhancement was called {mock_run.call_count} times: {result.output}"
        )
        return mock_run.call_args.kwargs

    def test_dry_flag_resolves_and_exits_zero(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        """The audit's exact repro: exit 0, not exit 2 / 'No such option'."""
        from audio_enhancer.core import file_processor

        with patch.object(file_processor, "run_enhancement"):
            result = runner.invoke(
                cli,
                [
                    "enhance",
                    str(music_dir),
                    "--output-dir",
                    str(tmp_path / "out"),
                    "--dry",
                ],
            )
        assert result.exit_code == 0, result.output
        assert "No such option" not in result.output

    def test_dry_reaches_the_core_as_is_dry_run(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        kwargs = self._run(runner, music_dir, tmp_path / "out", "--dry")
        assert kwargs["is_dry_run"] is True

    def test_live_reaches_the_core_as_is_dry_run_false(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        kwargs = self._run(runner, music_dir, tmp_path / "out", "--live")
        assert kwargs["is_dry_run"] is False

    def test_default_is_live(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        """Omitting the flag must keep today's write behaviour."""
        kwargs = self._run(runner, music_dir, tmp_path / "out")
        assert kwargs["is_dry_run"] is False


# ── The real outcome ─────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDryRunRealOutcome:
    """A real MP3 through the real chain: measure the outcome, not the flag."""

    def test_dry_run_writes_nothing_and_reports_measurements(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        source = music_dir / "track.mp3"
        out = tmp_path / "out"
        before = _fingerprint(source)

        result = runner.invoke(
            cli, ["enhance", str(music_dir), "--output-dir", str(out), "--dry"]
        )

        assert result.exit_code == 0, result.output
        # Nothing written: no output directory content at all.
        written = list(out.iterdir()) if out.exists() else []
        assert written == [], f"a dry run created output files: {written}"
        # Source untouched — both content and mtime.
        assert _fingerprint(source) == before, (
            "a dry run modified the source file (SHA-256 or mtime changed)"
        )
        # It still measured and reported: the summary counts an enhancement.
        assert "1 enhanced" in result.output, (
            f"a dry run must still report measurements; got: {result.output}"
        )
        assert "0 errors" in result.output, result.output

    def test_live_run_writes_the_output_file(
        self, runner: CliRunner, music_dir: Path, tmp_path: Path
    ) -> None:
        """The control: without this, the dry-run assertion could pass
        vacuously because the tool never writes anything at all."""
        out = tmp_path / "out"
        result = runner.invoke(
            cli, ["enhance", str(music_dir), "--output-dir", str(out)]
        )
        assert result.exit_code == 0, result.output
        assert out.exists(), "a live run must create the output directory"
        written = list(out.iterdir())
        assert written, "a live run must write the enhanced file"
        assert written[0].stat().st_size > 0
