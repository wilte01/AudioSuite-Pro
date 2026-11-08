"""core/models.py — the channel tool's settings and the rule it states.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

from dataclasses import dataclass

from audio_suite_shared import channel_ops


@dataclass(frozen=True)
class ChannelSettings:
    """One channel operation, with the parameters it reads.

    The validation and the wording live in :mod:`audio_suite_shared.channel_ops`
    (the one implementation of the rules); this record only carries the
    request, so the CLI, the window and the processor cannot disagree about
    what a setting means.

    Attributes:
        operation: An id from ``channel_ops.OPERATIONS``.
        width_percent: Side gain for the width operation; 100 is unity.
        source_channel: Channel the dual-mono operation copies.
        invert_target: Side the invert operation negates.
    """

    operation: str = channel_ops.DEFAULT_OPERATION
    width_percent: float = channel_ops.DEFAULT_WIDTH_PERCENT
    source_channel: str = "left"
    invert_target: str = "both"

    def __post_init__(self) -> None:
        """Refuse a request no operation could honour.

        Raises:
            AudioConfigValueError: The operation or a parameter is unknown or
                out of range.
        """
        channel_ops.validate_operation(
            self.operation,
            width_percent=self.width_percent,
            source_channel=self.source_channel,
            invert_target=self.invert_target,
        )

    @property
    def rule(self) -> str:
        """Return the sentence describing the rule this run applies."""
        return channel_ops.rule_for(
            self.operation,
            width_percent=self.width_percent,
            source_channel=self.source_channel,
            invert_target=self.invert_target,
        )

    @property
    def needs_stereo(self) -> bool:
        """Return whether the operation refuses a mono source."""
        return channel_ops.OPERATIONS[self.operation].needs_stereo
