"""RAW + JPEG pair detection.

Runs *after* date resolution, not before: whether a JPEG may be suppressed
depends on whether its RAW actually resolved to a usable date.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .classifier import is_jpeg, is_raw
from .models import MediaItem


@dataclass(frozen=True)
class Pair:
    raw: MediaItem
    jpeg: MediaItem


def find_pairs(items: list[MediaItem]) -> list[Pair]:
    """Find unambiguous RAW/JPEG pairs among *items*.

    A pair needs the same parent directory, the same stem compared
    case-insensitively, exactly one camera RAW and exactly one JPEG -- and
    nothing else sharing that stem.

    Anything ambiguous (two RAWs, both .jpg and .jpeg, three or more files)
    yields no pair at all, so every member is imported normally.  Importing
    both files costs disk space; guessing wrong loses a photo.
    """
    groups: dict[tuple[str, str], list[MediaItem]] = defaultdict(list)
    for item in items:
        key = (str(item.source_path.parent), item.stem.lower())
        groups[key].append(item)

    pairs: list[Pair] = []
    for group in groups.values():
        if len(group) != 2:
            continue
        raws = [i for i in group if is_raw(i.source_path)]
        jpegs = [i for i in group if is_jpeg(i.source_path)]
        if len(raws) != 1 or len(jpegs) != 1:
            continue

        raw, jpeg = raws[0], jpegs[0]

        # The RAW has to actually be importable.  Suppressing the JPEG behind
        # an undated RAW would discard both files and import nothing, even
        # though the JPEG may carry perfectly good EXIF of its own.
        if not raw.is_dated:
            continue

        pairs.append(Pair(raw=raw, jpeg=jpeg))

    return pairs


def suppressed_jpegs(items: list[MediaItem]) -> dict[int, MediaItem]:
    """Map id(jpeg_item) -> its RAW partner, for JPEGs that must be skipped."""
    return {id(pair.jpeg): pair.raw for pair in find_pairs(items)}
