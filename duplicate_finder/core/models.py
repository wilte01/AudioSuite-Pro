"""Model types for the duplicate finder.

A *fingerprint record* is everything one file contributes to the decision:
the Chromaprint sub-fingerprints, the measurable qualities a keeper is chosen
by, and the tags the report prints.  It is deliberately plain data — the
clustering and the cache both take and return these, so a decision made from a
cached record and one made from a freshly fingerprinted file cannot differ.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Default bit-error-rate threshold for "the same recording".
#:
#: Measured on the declared fixture set (see
#: ``duplicate_finder/tests/test_clustering.py``): the same recording encoded as
#: FLAC and as MP3 96/128/320 kbit/s measures **0.0000-0.0002**, while the
#: nearest pair that must not cluster (two arrangements that share a 10 s intro)
#: measures **0.1580**.  ``0.10`` sits between them with a ~490x margin below and
#: a 1.58x margin above, which is the recorded justification rather than a picked
#: number (AGENTS.md, *Defects and failing checks*: a measurement is not a
#: guess).
DEFAULT_THRESHOLD: float = 0.10

#: Two fingerprints are only comparable when their durations agree this closely.
#: MP3 encoding adds up to ~0.05 s of padding, so a same-recording pair differs
#: by well under a second; a conversation-length difference is a different file.
DEFAULT_DURATION_TOLERANCE_S: float = 2.0

#: Fraction of the longer fingerprint both sequences must cover for a
#: comparison to mean anything.  A 4-minute track against a 30 s clip is not a
#: duplicate even when the 30 s is embedded in it.
DEFAULT_MIN_OVERLAP_RATIO: float = 0.6

#: How far one fingerprint may be shifted against the other, in sub-fingerprint
#: words, when looking for the alignment with the lowest bit-error rate.  One
#: word covers ~0.12 s of audio, so 32 words is ~4 s — far more than encoder
#: delay, far less than a different performance.
DEFAULT_MAX_SHIFT_WORDS: int = 32


@dataclass(frozen=True)
class ScanSettings:
    """What counts as a duplicate, and how the comparison is bounded.

    Attributes:
        threshold: Maximum bit-error rate for two fingerprints to be the same
            recording.  See :data:`DEFAULT_THRESHOLD` for the measurement.
        duration_tolerance_s: Maximum duration difference, in seconds, for two
            files to be compared at all.
        min_overlap_ratio: Fraction of the longer fingerprint the aligned
            overlap must cover.
        max_shift_words: Alignment search width, in sub-fingerprint words.
        quarantine_dir: Where a live run moves the duplicates it found.  An
            empty value means this run only reports.
    """

    threshold: float = DEFAULT_THRESHOLD
    duration_tolerance_s: float = DEFAULT_DURATION_TOLERANCE_S
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO
    max_shift_words: int = DEFAULT_MAX_SHIFT_WORDS
    quarantine_dir: str = ""

    def __post_init__(self) -> None:
        """Reject values the distance and clustering code cannot honour.

        Raises:
            ValueError: If the threshold is outside ``(0.0, 1.0]``, a tolerance
                is negative, the overlap ratio is outside ``(0.0, 1.0]``, or the
                shift width is negative.
        """
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError(f"threshold must be in (0.0, 1.0], got {self.threshold}")
        if self.duration_tolerance_s < 0:
            raise ValueError(
                f"duration_tolerance_s must be >= 0, got {self.duration_tolerance_s}"
            )
        if not 0.0 < self.min_overlap_ratio <= 1.0:
            raise ValueError(
                f"min_overlap_ratio must be in (0.0, 1.0], got {self.min_overlap_ratio}"
            )
        if self.max_shift_words < 0:
            raise ValueError(
                f"max_shift_words must be >= 0, got {self.max_shift_words}"
            )


@dataclass(frozen=True)
class FingerprintRecord:
    """One file's fingerprint and the qualities a keeper is chosen by.

    Attributes:
        path: Absolute path to the audio file.
        duration: Decoded duration in seconds, as reported by fpcalc.
        words: Chromaprint sub-fingerprints, one ``uint32`` per word.
        size: File size in bytes, also the cache freshness stamp's second half.
        mtime: Last modification time, the stamp's first half.
        sample_rate: Sample rate in Hz, from the file's own stream info.
        channels: Channel count.
        bitrate_kbps: The file's audio bitrate, in kbit/s.
        lossless: Whether the container is a lossless one.
        artist: Artist tag, or an empty string when there is no readable tag.
        title: Title tag, or an empty string.
    """

    path: str
    duration: float
    words: tuple[int, ...]
    size: int
    mtime: float
    sample_rate: int = 0
    channels: int = 0
    bitrate_kbps: float = 0.0
    lossless: bool = False
    artist: str = ""
    title: str = ""

    @property
    def quality_key(self) -> tuple[int, float, int, float]:
        """Return the ordering a keeper is chosen by, best last.

        Lossless first, then bitrate, then sample rate, then duration: the
        first three are the properties a listener means by "the better copy",
        and duration last makes a truncated duplicate lose to a complete one at
        equal quality.  Every element is a measured file property, never a
        guess about the tags.
        """
        return (
            1 if self.lossless else 0,
            round(self.bitrate_kbps, 3),
            self.sample_rate,
            self.duration,
        )

    @property
    def label(self) -> str:
        """Return the ``Artist - Title (bitrate)`` line the report prints."""
        who = self.artist.strip() or "Unknown artist"
        what = self.title.strip() or "Unknown title"
        kind = "lossless" if self.lossless else f"{self.bitrate_kbps:.0f} kbit/s"
        return f"{who} - {what} ({kind}, {self.sample_rate} Hz, {self.channels} ch)"


@dataclass(frozen=True)
class DuplicateMember:
    """One duplicate file and how far its fingerprint sits from the keeper.

    Attributes:
        record: The duplicate itself.
        distance: Bit-error rate against the keeper, in ``0.0-1.0``.
    """

    record: FingerprintRecord
    distance: float


@dataclass(frozen=True)
class DuplicateGroup:
    """One set of files that are the same recording.

    Attributes:
        keeper: The copy the run proposes to keep — the highest
            :attr:`FingerprintRecord.quality_key`, ties broken by the
            lexicographically smallest path so two runs on the same library
            always agree.
        duplicates: The other copies, each with its distance to *keeper*.
    """

    keeper: FingerprintRecord
    duplicates: tuple[DuplicateMember, ...]

    @property
    def files(self) -> tuple[FingerprintRecord, ...]:
        """Return every file in the group, keeper first."""
        return (self.keeper, *(member.record for member in self.duplicates))

    @property
    def worst_distance(self) -> float:
        """Return the largest distance in the group, or ``0.0`` when it is one file."""
        return max((member.distance for member in self.duplicates), default=0.0)


@dataclass
class ScanOutcome:
    """The counted result of one duplicate scan.

    Attributes:
        groups: The duplicate groups found.
        duplicates: Files identified as duplicates (not counting keepers).
        quarantined: Files actually moved (always ``0`` in a dry run).
        missing_fingerprint: Files fpcalc could not fingerprint.
        log_entries: One line per file, in run order.
    """

    groups: list[DuplicateGroup] = field(default_factory=list)
    duplicates: int = 0
    quarantined: int = 0
    missing_fingerprint: int = 0
    log_entries: list[str] = field(default_factory=list)
