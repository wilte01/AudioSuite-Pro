# Changed in 2.6.0: new module — exact-duplicate detection (F-E9).
"""Two hashes, two questions: byte identity and decoded-PCM identity.

The fingerprint pass answers "is this the same *recording*".  These two hashes
answer the narrower, cheaper questions a library owner asks first:

* :func:`file_sha256` — the raw bytes.  A renamed or copied file matches exactly;
  a single retagged byte does not.
* :func:`pcm_sha256` — the decoded samples, packed as ``s32le`` at the source's
  own sample rate and channel count.  A tag edit, an ID3 rewrite or a container
  remux does not change it, because none of those touch the decoded audio; a
  re-encode, a resample, a depth change or different mastering does change it,
  because each changes the samples themselves.

That asymmetry is the deliberate policy: a metadata-only edit must not defeat an
exact match, and "the same master at another bit depth" is *not* claimed to be
byte- or PCM-identical, because its samples are scaled.  ``--exact-ignore-depth``
does not exist for that reason — nothing in this release needs the softer claim,
and offering it would mean a second definition of "exact" in the report.

Cost
----
Hashing decodes the whole file, so it is not free: a five-minute stereo file is
~100 MB of ``s32le``.  The decode is written to a temporary file and hashed in
1 MiB chunks rather than held in memory, so an hour-long file costs the same
memory as a short one; the temporary file never lands in the music folder and is
removed in a ``finally`` block.  Callers hash only the files a run asked for
(``ScanSettings.exact_mode``), and a fingerprint-only run hashes nothing.

The one ffmpeg path is the suite's: :func:`audio_suite_shared.ffmpeg.require_ffmpeg`
resolves the binary and :func:`run_secure_subprocess` runs it, so this module
carries no PATH search of its own (AGENTS.md, *Shared Implementations First*).
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from dataclasses import replace

from audio_suite_shared.ffmpeg import require_ffmpeg
from audio_suite_shared.secure_subprocess import run_secure_subprocess

from .clustering import UnionFind, choose_keeper
from .models import DuplicateGroup, DuplicateMember, FingerprintRecord

logger = logging.getLogger(__name__)

#: Read size for both hashes: large enough that a library's I/O is dominated by
#: the file, small enough that the digest never holds a whole track.
CHUNK_BYTES = 1024 * 1024

#: The group kinds :func:`build_exact_groups` produces.  ``"exact"`` means every
#: member's bytes are identical; ``"exact-pcm"`` means the decoded samples are
#: identical while at least one file's bytes differ.
KIND_BYTES = "exact"
KIND_PCM = "exact-pcm"


def file_sha256(path: str) -> str:
    """Return the SHA-256 of *path*'s raw bytes.

    Args:
        path: File to hash.

    Returns:
        The hex digest.

    Raises:
        OSError: If the file cannot be opened or read.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pcm_sha256(path: str, *, sample_rate: int = 0, channels: int = 0) -> str:
    """Return the SHA-256 of *path*'s decoded samples.

    The samples are decoded to signed 32-bit little-endian PCM at the rate and
    channel count the file already has, so a container remux or a tag edit
    cannot change the digest and a different master cannot keep it.

    Args:
        path: File to decode.
        sample_rate: The file's own rate; ``0`` lets FFmpeg choose.
        channels: The file's own channel count; ``0`` lets FFmpeg choose.

    Returns:
        The hex digest.

    Raises:
        AudioMissingDependencyError: If FFmpeg is not installed.
        subprocess.CalledProcessError: If FFmpeg cannot decode the file.
        OSError: If the temporary file cannot be written or read.
    """
    ffmpeg = require_ffmpeg()
    handle = tempfile.NamedTemporaryFile(
        prefix="audiosuite_pcm_", suffix=".s32le", delete=False
    )
    decoded = handle.name
    handle.close()
    args = [
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        path,
        "-vn",
        "-f",
        "s32le",
        "-acodec",
        "pcm_s32le",
    ]
    if sample_rate > 0:
        args += ["-ar", str(int(sample_rate))]
    if channels > 0:
        args += ["-ac", str(int(channels))]
    args.append(decoded)
    try:
        run_secure_subprocess(
            ffmpeg, args, capture_output=True, check=True, log_failure=False
        )
        return file_sha256(decoded)
    finally:
        try:
            os.unlink(decoded)
        except OSError as exc:
            logger.debug("Could not remove the PCM scratch file %s: %s", decoded, exc)


def attach_hashes(record: FingerprintRecord) -> FingerprintRecord:
    """Return *record* with both hashes filled in.

    A record that already carries both digests is returned unchanged, which is
    what makes a cached row free and a stale one recomputed exactly once.

    Args:
        record: The record to complete.

    Returns:
        The record with ``file_sha256`` and ``pcm_sha256`` set.
    """
    if record.file_sha256 and record.pcm_sha256:
        return record
    byte_digest = record.file_sha256 or file_sha256(record.path)
    pcm_digest = record.pcm_sha256 or pcm_sha256(
        record.path, sample_rate=record.sample_rate, channels=record.channels
    )
    return replace(record, file_sha256=byte_digest, pcm_sha256=pcm_digest)


def _union_matching(records: list[FingerprintRecord]) -> dict[int, list[int]]:
    """Return the components of files that share a byte or PCM digest.

    Args:
        records: The records to group.

    Returns:
        ``{representative index: sorted member indexes}``, single-member
        components included so the caller can decide what to report.
    """
    union = UnionFind(len(records))
    buckets: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        for digest in (record.file_sha256, record.pcm_sha256):
            if digest:
                buckets.setdefault(digest, []).append(index)
    for members in buckets.values():
        for other in members[1:]:
            union.union(members[0], other)

    components: dict[int, list[int]] = {}
    for index in range(len(records)):
        components.setdefault(union.find(index), []).append(index)
    return components


def build_exact_groups(records: list[FingerprintRecord]) -> list[DuplicateGroup]:
    """Group *records* by identical bytes or identical PCM.

    Args:
        records: Records that carry at least one digest (a record without one
            is simply never grouped).

    Returns:
        Groups of two or more files, keeper first.  A group whose members all
        share the byte digest has kind :data:`KIND_BYTES`; a group joined only
        by the PCM digest has kind :data:`KIND_PCM`.  Every member's distance is
        ``0.0`` — these are equalities, not measurements.
    """
    if len(records) < 2:
        return []

    groups: list[DuplicateGroup] = []
    for members in _union_matching(records).values():
        if len(members) < 2:
            continue
        group_records = [records[index] for index in members]
        keeper = choose_keeper(group_records)
        byte_identical = len({record.file_sha256 for record in group_records}) == 1
        duplicates = tuple(
            DuplicateMember(record=record, distance=0.0)
            for record in sorted(group_records, key=lambda item: item.path)
            if record is not keeper
        )
        groups.append(
            DuplicateGroup(
                keeper=keeper,
                duplicates=duplicates,
                kind=KIND_BYTES if byte_identical else KIND_PCM,
            )
        )

    groups.sort(key=lambda group: (-len(group.duplicates), group.keeper.path))
    return groups
