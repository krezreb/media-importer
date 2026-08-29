"""Filename date/time parsing.

A collection of named patterns rather than one expression buried in the video
resolver, so new camera and phone conventions can be added without touching
resolution logic.

Patterns are tried in order, most specific first.  Every candidate must parse
as a real calendar date inside a plausible year range, so that an arbitrary
numeric run is not mistaken for a date.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

MIN_YEAR = 1990
MAX_YEAR = datetime.now().year + 1


@dataclass(frozen=True)
class FilenamePattern:
    name: str
    regex: re.Pattern[str]
    example: str

    def match(self, name: str) -> datetime | None:
        for m in self.regex.finditer(name):
            parsed = _build(m.groupdict())
            if parsed is not None:
                return parsed
        return None


def _build(g: dict[str, str]) -> datetime | None:
    try:
        year = int(g["Y"])
        if not MIN_YEAR <= year <= MAX_YEAR:
            return None
        return datetime(
            year,
            int(g["M"]),
            int(g["D"]),
            int(g.get("h") or 0),
            int(g.get("m") or 0),
            int(g.get("s") or 0),
        )
    except (ValueError, TypeError, KeyError):
        # ValueError also covers impossible calendar dates such as 20250230.
        return None


# (?<!\d) / (?!\d) keep a pattern from biting a slice out of a longer digit run.
PATTERNS: tuple[FilenamePattern, ...] = (
    FilenamePattern(
        "YYYYMMDD_HHMMSSmmm",
        re.compile(
            r"(?<!\d)(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})"
            r"[_\-T](?P<h>\d{2})(?P<m>\d{2})(?P<s>\d{2})\d{3}(?!\d)"
        ),
        "PXL_20250827_105030123.jpg",
    ),
    FilenamePattern(
        "YYYYMMDD_HHMMSS",
        re.compile(
            r"(?<!\d)(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})"
            r"[_\-T](?P<h>\d{2})(?P<m>\d{2})(?P<s>\d{2})(?!\d)"
        ),
        "20250827_105030.mp4",
    ),
    FilenamePattern(
        "YYYY-MM-DD_HH-MM-SS",
        re.compile(
            r"(?<!\d)(?P<Y>\d{4})[-.](?P<M>\d{2})[-.](?P<D>\d{2})"
            r"[ _T](?P<h>\d{2})[-.:](?P<m>\d{2})[-.:](?P<s>\d{2})(?!\d)"
        ),
        "2025-08-27 10.50.30.mov",
    ),
    FilenamePattern(
        "YYYYMMDDHHMMSS",
        re.compile(
            r"(?<!\d)(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})"
            r"(?P<h>\d{2})(?P<m>\d{2})(?P<s>\d{2})(?!\d)"
        ),
        "20250827105030.mp4",
    ),
    FilenamePattern(
        "YYYY-MM-DD",
        re.compile(r"(?<!\d)(?P<Y>\d{4})[-_.](?P<M>\d{2})[-_.](?P<D>\d{2})(?!\d)"),
        "2025-08-27.mp4",
    ),
    FilenamePattern(
        "YYYYMMDD",
        re.compile(r"(?<!\d)(?P<Y>\d{4})(?P<M>\d{2})(?P<D>\d{2})(?!\d)"),
        "20250827.mp4",
    ),
)


def parse(filename: str) -> datetime | None:
    """Return the date encoded in *filename*, or None if no pattern matches."""
    for pattern in PATTERNS:
        found = pattern.match(filename)
        if found is not None:
            return found
    return None
