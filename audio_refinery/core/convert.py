"""
core/convert.py — Re-exports from audio_suite_shared.audio_conversion.

The canonical implementation now lives in audio_suite_shared.audio_conversion.
This module is retained for backward compatibility; all new code should import
from audio_suite_shared.audio_conversion directly.
"""

__all__ = [
    "segment_to_numpy",
    "numpy_to_segment",
    "clip_bounds",
    "int_dtype",
    "pack_24bit",
    "_clip_bounds",
    "_int_dtype",
    "_pack_24bit",
]

from audio_suite_shared.audio_conversion import (  # noqa: F401
    clip_bounds,
    int_dtype,
    numpy_to_segment,
    pack_24bit,
    segment_to_numpy,
)

# Preserve internal helpers as re-exports for any direct test callers
from audio_suite_shared.audio_conversion import (
    clip_bounds as _clip_bounds,  # noqa: F401
)
from audio_suite_shared.audio_conversion import int_dtype as _int_dtype  # noqa: F401
from audio_suite_shared.audio_conversion import pack_24bit as _pack_24bit  # noqa: F401
