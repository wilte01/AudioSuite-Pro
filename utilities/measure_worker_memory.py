#!/usr/bin/env python3
"""measure_worker_memory.py

Measure the peak memory of an analysis batch at several worker counts.

Usage:
    python utilities/measure_worker_memory.py
    python utilities/measure_worker_memory.py --files 8 --seconds 60 --json
    python utilities/measure_worker_memory.py --workers 4,8 --budget-mb 1024

Why this exists
---------------
``MAX_WORKERS_CEILING = 8`` was chosen on speed alone (D62): eight concurrent
librosa and pedalboard jobs hold large buffers, and the peak was never measured.
D100 measured it and documented a budget, and this script is how that
measurement is reproduced - *through the real path*, ``run_analysis``, not a
paraphrase of it.

Method
------
Peak RSS is monotonic within a process, so measuring 4 and then 8 workers in
one interpreter would report only the larger number twice.  The parent
therefore spawns one fresh child per configuration: the child imports the
analyzer, records its baseline, runs the batch, and reports the peak on exit.
The corpus is built by the parent, so the child's numbers cover the analysis
only.

The process (`--parallel`) path is reported as the **parent's** peak, and that
is the whole point of the row: children are separate processes, so their
memory is not the parent's.  Summing the children's peaks is a different (and
much larger) number, which this script deliberately does not invent.

Exit status: 0 when the measurement completes within budget, 1 when the widest
configuration exceeds ``--budget-mb``, 2 on bad arguments.

Changed in 1.4.1: new script - the D100 measurement and the probe that keeps
its own trap (a silently-zero `GetProcessMemoryInfo`) from coming back.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import subprocess
import sys
import sysconfig
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The documented budget for an 8-file analysis batch, from PLAN D100.
DEFAULT_BUDGET_MB = 1024.0

#: The worker counts the plan compares.
DEFAULT_WORKERS = (4, 8)

#: Sample rate and channel count appended by the corpus builder.
_CORPUS_RATE = 44_100


class _MEMORY_COUNTERS(ctypes.Structure):
    """``PROCESS_MEMORY_COUNTERS`` from psapi.h, trimmed to what is reported."""

    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_peak_bytes() -> int:
    """Return this process's peak working set on Windows.

    ``GetProcessMemoryInfo`` silently returns 0 when the argument and return
    types are left to ``ctypes``' defaults (a truncated handle, and a
    ``BOOL``-sized return), which would make every measurement 0 MB - a
    harness that cannot fail.  The declarations below are the fix, and
    ``tests/test_measure_worker_memory.py`` asserts the result is non-zero.
    """
    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")

    get_info = psapi.GetProcessMemoryInfo
    get_info.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_MEMORY_COUNTERS),
        ctypes.c_ulong,
    ]
    get_info.restype = ctypes.c_int

    get_current = kernel32.GetCurrentProcess
    get_current.restype = ctypes.c_void_p

    counters = _MEMORY_COUNTERS()
    counters.cb = ctypes.sizeof(_MEMORY_COUNTERS)
    if not get_info(get_current(), ctypes.byref(counters), counters.cb):
        raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo")
    return int(counters.PeakWorkingSetSize)


def peak_rss_bytes() -> int:
    """Return this process's peak resident set size, in bytes.

    Returns:
        The peak RSS since the process started: peak working set on Windows,
        ``ru_maxrss`` elsewhere (KiB on Linux, bytes on macOS).

    Raises:
        OSError: If the Windows counter cannot be read.
    """
    if sys.platform == "win32":
        return _windows_peak_bytes()

    import resource

    usage = resource.getrusage(resource.RUSAGE_SELF)
    kibibytes = int(usage.ru_maxrss)
    if sys.platform == "darwin":
        return kibibytes
    return kibibytes * 1024


@dataclass(frozen=True)
class Measurement:
    """One configuration's measured peak and elapsed time.

    Attributes:
        mode: ``threads`` (the GUI/CLI default path) or ``processes``
            (``--parallel``), whose peak is the parent's only.
        workers: The worker count the batch was configured with.
        files: Files in the batch.
        seconds: Length of each file.
        analysis_seconds: Seconds the detector decodes per file.
        baseline_mb: Peak RSS after imports, before the batch.
        peak_mb: Peak RSS once the batch finished.
        elapsed_s: Wall time for the batch.
        exit_status: The child's exit status; non-zero means the run failed.
    """

    mode: str
    workers: int
    files: int
    seconds: int
    analysis_seconds: int
    baseline_mb: float
    peak_mb: float
    elapsed_s: float
    exit_status: int

    @property
    def delta_mb(self) -> float:
        """Peak above the pre-batch baseline."""
        return self.peak_mb - self.baseline_mb


class _Slot:
    """Stand-in for a Tk ``StringVar`` in the worker slot grid."""

    def set(self, _value: str) -> None:
        """Accept the worker's status write and discard it."""


def build_corpus(directory: Path, files: int, seconds: int) -> list[Path]:
    """Write *files* WAV excerpts with a clear pulse into *directory*.

    Args:
        directory: Where the WAVs go.
        files: How many to write.
        seconds: Length of each, in seconds.

    Returns:
        The written paths, in name order.  The signal is a decaying click
        every 0.5 s over a quiet noise bed, which gives the tracker a real
        onset envelope to work on without making the corpus huge.
    """
    import numpy as np

    rng = np.random.default_rng(0)
    samples = _CORPUS_RATE * seconds
    t = np.arange(samples) / _CORPUS_RATE
    bed = 0.02 * rng.standard_normal(samples)
    pulse = np.zeros(samples)
    for beat in np.arange(0.0, seconds, 0.5):
        start = int(beat * _CORPUS_RATE)
        length = min(_CORPUS_RATE // 10, samples - start)
        if length <= 0:
            continue
        envelope = np.exp(-np.arange(length) / (0.01 * _CORPUS_RATE))
        pulse[start : start + length] += (
            0.5 * envelope * np.sin(2 * np.pi * 90 * t[:length])
        )
    signal = np.clip(bed + pulse, -1.0, 1.0)
    pcm = (signal * 32767).astype("<i2").tobytes()

    paths: list[Path] = []
    for index in range(files):
        path = directory / f"measure_{index:02d}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(_CORPUS_RATE)
            handle.writeframes(pcm)
        paths.append(path)
    return paths


def run_batch(
    directory: Path, workers: int, parallel: bool, analysis_seconds: int
) -> float:
    """Run one analysis batch through the real ``run_analysis`` entry point.

    Args:
        directory: Directory of WAVs to analyse.
        workers: Worker count to configure.
        parallel: ``True`` for the ``--parallel`` process path.
        analysis_seconds: Seconds of each file the detector decodes.  This is
            the app's ``--duration`` (30 s by default), not the file length:
            memory scales with what is decoded, so conflating the two doubles
            every number.

    Returns:
        Wall-clock seconds the batch took.
    """
    from bpm_analyzer.core.file_processor import run_analysis

    slots = [_Slot() for _ in range(workers)]

    def _on_event(**_kwargs: object) -> None:
        return

    def _on_error(_message: str) -> None:
        return

    started = time.perf_counter()
    run_analysis(
        dir_path=str(directory),
        is_dry_run=True,
        min_bpm=60,
        max_bpm=200,
        analysis_duration=analysis_seconds,
        slot_vars=slots,
        slot_queue=queue.Queue(),
        on_progress=_on_event,
        on_complete=_on_event,
        on_error=_on_error,
        parallel_mode=parallel,
        max_workers=workers,
    )
    return time.perf_counter() - started


def _child(args: argparse.Namespace, workers: int) -> int:
    """Run one configuration and print its measurement as JSON."""
    directory = Path(args.directory or "")
    baseline = peak_rss_bytes() / 1_048_576
    elapsed = run_batch(directory, workers, args.parallel, args.analysis_seconds)
    measurement = Measurement(
        mode="processes" if args.parallel else "threads",
        workers=workers,
        files=len(list(directory.glob("*.wav"))),
        seconds=args.seconds,
        analysis_seconds=args.analysis_seconds,
        baseline_mb=round(baseline, 1),
        peak_mb=round(peak_rss_bytes() / 1_048_576, 1),
        elapsed_s=round(elapsed, 2),
        exit_status=0,
    )
    print(json.dumps(asdict(measurement)))
    return 0


def _spawn(
    directory: Path, workers: int, parallel: bool, seconds: int, analysis_seconds: int
) -> Measurement:
    """Run one configuration in a fresh interpreter and return its measurement."""
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--child",
        "--directory",
        str(directory),
        "--workers",
        str(workers),
        "--seconds",
        str(seconds),
        "--analysis-seconds",
        str(analysis_seconds),
    ]
    if parallel:
        command.append("--parallel")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(REPO_ROOT), environment.get("PYTHONPATH", "")])
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        env=environment,
        check=False,
    )
    payload = None
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("{"):
            payload = json.loads(line)
            break
    if payload is None:
        raise RuntimeError(
            f"child for {workers} workers ({'processes' if parallel else 'threads'}) "
            f"printed no measurement: rc={result.returncode} {result.stderr[-400:]}"
        )
    payload["exit_status"] = result.returncode
    return Measurement(**payload)


def measure(
    files: int, seconds: int, analysis_seconds: int, workers: tuple[int, ...]
) -> list[Measurement]:
    """Measure every worker count on the thread path, then the widest on processes.

    Args:
        files: Files per batch.
        seconds: Length of each corpus file.
        analysis_seconds: Seconds per file the detector decodes.
        workers: Worker counts to compare.

    Returns:
        One :class:`Measurement` per configuration, thread configs first, then
        the widest count on the process path.
    """
    with tempfile.TemporaryDirectory(prefix="asuite_worker_memory_") as tmp:
        directory = Path(tmp)
        build_corpus(directory, files, seconds)
        results = [
            _spawn(directory, count, False, seconds, analysis_seconds)
            for count in workers
        ]
        results.append(_spawn(directory, max(workers), True, seconds, analysis_seconds))
    return results


def _host_line() -> str:
    """Describe the host the numbers came from.

    ``sysconfig.get_platform()`` names the build platform (``win-amd64``,
    ``linux-x86_64``) without a conditional, so this line is not a platform
    branch the matrix has to classify.
    """
    return (
        f"{sysconfig.get_platform()} | python {sys.version.split()[0]} | "
        f"{os.cpu_count()} logical CPUs"
    )


def main(argv: list[str] | None = None) -> int:
    """Measure, report, and return the exit status.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(
        prog="python utilities/measure_worker_memory.py",
        description="Measure peak RSS for an analysis batch at 4 and 8 workers.",
    )
    parser.add_argument("--files", type=int, default=8, help="files per batch (8)")
    parser.add_argument(
        "--seconds", type=int, default=60, help="length of each corpus file (60)"
    )
    parser.add_argument(
        "--analysis-seconds",
        type=int,
        default=30,
        help="seconds the detector decodes per file, i.e. the app's --duration (30)",
    )
    parser.add_argument(
        "--workers",
        default=",".join(str(count) for count in DEFAULT_WORKERS),
        help="worker counts to compare (4,8)",
    )
    parser.add_argument(
        "--budget-mb",
        type=float,
        default=DEFAULT_BUDGET_MB,
        help=f"documented budget for a batch ({DEFAULT_BUDGET_MB:.0f} MB)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON only")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--directory", help=argparse.SUPPRESS)
    parser.add_argument("--parallel", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.files < 1 or args.seconds < 1:
        print("[ERROR] --files and --seconds must be positive", file=sys.stderr)
        return 2
    try:
        workers = tuple(int(part) for part in args.workers.split(",") if part.strip())
    except ValueError:
        print(
            f"[ERROR] --workers must be a comma-separated list: {args.workers!r}",
            file=sys.stderr,
        )
        return 2
    if not workers or min(workers) < 1:
        print(
            "[ERROR] --workers must name at least one positive count", file=sys.stderr
        )
        return 2

    if args.child:
        if not args.directory:
            print("[ERROR] --child needs --directory", file=sys.stderr)
            return 2
        return _child(args, max(workers))

    results = measure(args.files, args.seconds, args.analysis_seconds, workers)
    widest = max(
        (result.peak_mb for result in results if result.mode == "threads"),
        default=0.0,
    )
    within_budget = widest <= args.budget_mb

    if args.json:
        print(
            json.dumps(
                {
                    "host": _host_line(),
                    "budget_mb": args.budget_mb,
                    "within_budget": within_budget,
                    "measurements": [asdict(result) for result in results],
                },
                indent=2,
            )
        )
    else:
        print(f"[INFO] host: {_host_line()}")
        print(
            f"[INFO] batch: {args.files} x {args.seconds} s mono "
            f"{_CORPUS_RATE} Hz, {args.analysis_seconds} s analysed per file, "
            "corpus built by the parent"
        )
        for result in results:
            print(
                f"[MEASURED] {result.mode:9s} {result.workers:2d} workers  "
                f"peak {result.peak_mb:7.1f} MB "
                f"(baseline {result.baseline_mb:6.1f}, +{result.delta_mb:7.1f})  "
                f"{result.elapsed_s:5.2f} s"
            )
        print(
            "[NOTE] the processes row is the PARENT's peak: its children are "
            "separate processes, so their peak is not included here"
        )
        print(
            f"[NOTE] per-worker cost on the thread path: {_per_worker(results):.0f} MB"
        )
        verdict = "within budget" if within_budget else "OVER BUDGET"
        print(
            f"[BUDGET] {widest:.1f} MB against {args.budget_mb:.0f} MB for a "
            f"{args.files}-file analysis batch -> {verdict}"
        )
    return 0 if within_budget else 1


def _per_worker(results: list[Measurement]) -> float:
    """Return the marginal MB per worker between the narrowest and widest runs.

    Args:
        results: Measurements to read; only thread rows are considered.

    Returns:
        ``(widest_peak - narrowest_peak) / (widest_workers - narrowest_workers)``,
        or 0.0 when there is a single thread configuration to compare.
    """
    thread = sorted(
        (result for result in results if result.mode == "threads"),
        key=lambda result: result.workers,
    )
    if len(thread) < 2:
        return 0.0
    narrow, wide = thread[0], thread[-1]
    if wide.workers == narrow.workers:
        return 0.0
    return (wide.peak_mb - narrow.peak_mb) / (wide.workers - narrow.workers)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
