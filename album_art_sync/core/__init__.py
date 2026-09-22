"""Core processing logic for album_art_sync."""

from .candidate_filter import filter_and_rank
from .matcher import album_name_matches
from .pipeline import ArtSyncReport, resolve_and_apply
from .ranker import RankedCandidate, get_image_dimensions, rank_by_area

__all__ = [
    "RankedCandidate",
    "filter_and_rank",
    "album_name_matches",
    "ArtSyncReport",
    "resolve_and_apply",
    "get_image_dimensions",
    "rank_by_area",
]
