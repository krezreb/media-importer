"""Capture-date resolution.

Answers only "when was this captured?".  It knows nothing about libraries,
schemes, or destination paths -- that separation is what lets the destination
layout be reconfigured without touching how dates are determined.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from . import filename_dates, fs_time
from .metadata import MetadataCandidate, MetadataExtractor
from .models import DateSource, MediaItem, MediaType, ResolvedDate

log = logging.getLogger(__name__)

FLOOR = datetime(1990, 1, 1)
"""Nothing plausible predates this. Catches 1904 (QuickTime) and 1970 (Unix)."""

CEILING_SLACK = timedelta(days=730)
"""How far past mtime a capture date may sit before it is disbelieved."""


def is_plausible(candidate: datetime, mtime: datetime) -> bool:
    """Whether a *metadata* date is believable for a file with this mtime.

    Deliberately asymmetric.  A capture date older than mtime is completely
    normal -- copying a file updates mtime while the capture date stays put, so
    an archival import of genuinely old media must keep its real dates.  A
    capture date meaningfully newer than mtime is physically impossible.
    """
    return FLOOR <= candidate <= mtime + CEILING_SLACK


class DateResolver:
    def __init__(self, extractor: MetadataExtractor) -> None:
        self.extractor = extractor

    def prefetch(self, items: list[MediaItem]) -> None:
        photos = [i.source_path for i in items if i.media_type is MediaType.PHOTO]
        if photos:
            self.extractor.prefetch(photos)

    def resolve(self, item: MediaItem) -> ResolvedDate | None:
        if item.media_type is MediaType.PHOTO:
            return self.resolve_photo(item.source_path)
        if item.media_type is MediaType.VIDEO:
            return self.resolve_video(item.source_path)
        return None

    # -- photos -----------------------------------------------------------

    def resolve_photo(self, path: Path) -> ResolvedDate | None:
        """EXIF, in a fixed order, or undated.

        Photos never fall back to the filename or to a filesystem timestamp.
        Unlike video containers, EXIF is consistent enough to rely on, and this
        restriction is a product decision rather than a gap.
        """
        mtime = _safe_mtime(path)
        for candidate in self.extractor.candidates(path, MediaType.PHOTO):
            if _accept(path, candidate, mtime):
                return ResolvedDate(candidate.value, candidate.source, candidate.detail)
        return None

    # -- videos -----------------------------------------------------------

    def resolve_video(self, path: Path) -> ResolvedDate | None:
        """Metadata, then filename, then birth time, then mtime, then undated."""
        mtime = _safe_mtime(path)

        for candidate in self.extractor.candidates(path, MediaType.VIDEO):
            if _accept(path, candidate, mtime):
                return ResolvedDate(candidate.value, candidate.source, candidate.detail)

        from_name = filename_dates.parse(path.name)
        if from_name is not None:
            return ResolvedDate(from_name, DateSource.FILENAME)

        birth = fs_time.birth_time(path)
        if birth.available and birth.value is not None:
            return ResolvedDate(birth.value, DateSource.FS_BIRTH_TIME)
        log.debug("No birth time for %s: %s", path, birth.unavailable_reason)

        if mtime is not None:
            return ResolvedDate(mtime, DateSource.FS_MTIME)

        return None


def _accept(path: Path, candidate: MetadataCandidate, mtime: datetime | None) -> bool:
    if mtime is None:
        return candidate.value >= FLOOR
    if is_plausible(candidate.value, mtime):
        return True
    log.debug(
        "Rejecting implausible %s for %s: %s (mtime %s)",
        candidate.detail,
        path,
        candidate.value,
        mtime,
    )
    return False


def _safe_mtime(path: Path) -> datetime | None:
    try:
        return fs_time.mtime(path)
    except OSError as exc:  # pragma: no cover - transient fs errors
        log.warning("Could not stat %s: %s", path, exc)
        return None
