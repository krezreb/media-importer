"""Import planning.

Converts discovered files into a complete plan.  The planner decides
everything; the importer only carries the decisions out.  Nothing here copies,
moves, or modifies a file.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import pairing, path_scheme
from .classifier import classify
from .config import Config
from .date_resolver import DateResolver
from .metadata import MetadataExtractor
from .models import (
    Action,
    ClobberPreference,
    CollisionPolicy,
    CollisionResolution,
    IgnoredFile,
    IgnoreReason,
    ImportPlan,
    MediaItem,
    MediaType,
    PlanItem,
    Reason,
    ResolvedDate,
)
from .scanner import scan

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


@dataclass
class _Existing:
    """What we know about a file already sitting at a destination path."""

    path: Path
    size: int
    mtime: float
    resolved: ResolvedDate | None = None


def build_plan(
    config: Config,
    extractor: MetadataExtractor,
    on_progress: ProgressFn | None = None,
) -> ImportPlan:
    resolver = DateResolver(extractor)
    plan = ImportPlan()

    def progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    # 1. Scan and classify.
    progress("Scanning source directory...")
    items: list[MediaItem] = []
    assert config.source_path is not None
    for event in scan(config.source_path):
        if event.is_ignored:
            assert event.ignore_reason is not None
            plan.ignored.append(IgnoredFile(event.path, event.ignore_reason))
            continue
        media_type = classify(event.path)
        if media_type is MediaType.UNKNOWN:
            plan.ignored.append(IgnoredFile(event.path, IgnoreReason.UNSUPPORTED_EXTENSION))
            continue
        items.append(MediaItem(event.path, media_type))

    progress(f"Found {len(items)} media files. Reading metadata...")

    # 2. Resolve dates.  Photos are prefetched in batches first, because
    #    exiftool's startup cost dwarfs its per-file cost.
    resolver.prefetch(items)
    for n, item in enumerate(items, start=1):
        if n % 50 == 0 or n == len(items):
            progress(f"Resolving dates {n}/{len(items)}...")
        try:
            item.resolved = resolver.resolve(item)
        except Exception as exc:
            log.exception("Failed to resolve date for %s", item.source_path)
            item.error = str(exc)

    # 3. Pairing, which must come after dates: a JPEG is only suppressed when
    #    its RAW actually resolved to something importable.
    progress("Detecting RAW/JPEG pairs...")
    suppressed = pairing.suppressed_jpegs(items)

    # 4-7. Destinations, destination state, collisions, actions.
    progress("Checking destinations...")
    assigned: dict[Path, PlanItem] = {}
    existing_cache: dict[Path, _Existing | None] = {}

    for item in items:
        plan.items.append(_plan_one(item, config, resolver, suppressed, assigned, existing_cache))

    plan.check_partition()
    progress("Plan ready.")
    return plan


def _plan_one(
    item: MediaItem,
    config: Config,
    resolver: DateResolver,
    suppressed: dict[int, MediaItem],
    assigned: dict[Path, PlanItem],
    existing_cache: dict[Path, _Existing | None],
) -> PlanItem:
    if item.error is not None:
        return PlanItem(item, Action.ERROR, reason=Reason.METADATA_FAILED, detail=item.error)

    raw_partner = suppressed.get(id(item))
    if raw_partner is not None:
        return PlanItem(
            item,
            Action.SKIP,
            reason=Reason.JPEG_PAIRED_WITH_RAW,
            detail=f"RAW {raw_partner.filename} is being imported instead",
        )

    if item.resolved is None:
        return PlanItem(item, Action.UNDATED, reason=Reason.NO_USABLE_DATE)

    library = config.photo_library if item.media_type is MediaType.PHOTO else config.video_library
    assert library is not None

    try:
        relative = path_scheme.format_path(item.resolved.value, config.import_path)
        destination = _safe_destination(library, relative, item.filename)
    except Exception as exc:
        return PlanItem(item, Action.ERROR, detail=str(exc))

    # A symlink in the library is never overwritten, clobbered, or renamed.
    if destination.is_symlink():
        return PlanItem(
            item,
            Action.ERROR,
            destination_path=destination,
            reason=Reason.DESTINATION_IS_SYMLINK,
        )

    in_plan = assigned.get(destination)
    existing = _stat_destination(destination, existing_cache)

    if in_plan is None and existing is None:
        planned = PlanItem(item, Action.COPY, destination_path=destination)
        assigned[destination] = planned
        return planned

    if in_plan is None and existing is not None:
        if _is_same_file(item, existing, resolver):
            return PlanItem(
                item,
                Action.SKIP,
                destination_path=destination,
                reason=Reason.ALREADY_IMPORTED,
            )
        return _resolve_collision(
            item,
            destination,
            config,
            resolver,
            assigned,
            existing_cache,
            incumbent_date=_existing_date(existing, resolver),
            collided_with=destination,
        )

    # Two source files in this same run want one destination path.  Without
    # this branch both would be planned COPY and the second would silently
    # destroy the first.
    assert in_plan is not None
    return _resolve_collision(
        item,
        destination,
        config,
        resolver,
        assigned,
        existing_cache,
        incumbent_date=in_plan.resolved_datetime,
        collided_with=in_plan.source_path,
        in_plan_rival=in_plan,
    )


def _resolve_collision(
    item: MediaItem,
    destination: Path,
    config: Config,
    resolver: DateResolver,
    assigned: dict[Path, PlanItem],
    existing_cache: dict[Path, _Existing | None],
    *,
    incumbent_date: datetime | None,
    collided_with: Path,
    in_plan_rival: PlanItem | None = None,
) -> PlanItem:
    policy = config.on_collision

    if policy is CollisionPolicy.SKIP:
        return PlanItem(
            item,
            Action.COLLISION,
            destination_path=destination,
            reason=Reason.COLLISION_SKIPPED,
            collision=CollisionResolution.SKIPPED,
            collided_with=collided_with,
        )

    if policy is CollisionPolicy.RENAME:
        renamed = _next_free_name(destination, assigned, existing_cache)
        planned = PlanItem(
            item,
            Action.COPY,
            destination_path=renamed,
            collision=CollisionResolution.RENAMED,
            collided_with=collided_with,
            detail=f"renamed to {renamed.name}",
        )
        assigned[renamed] = planned
        return planned

    # CLOBBER
    assert item.resolved is not None
    if _incoming_wins(
        item.resolved.value, incumbent_date, item.source_path, collided_with, config.clobber_prefers
    ):
        planned = PlanItem(
            item,
            Action.COPY,
            destination_path=destination,
            collision=CollisionResolution.CLOBBERED,
            collided_with=collided_with,
            detail=f"replaces {collided_with}",
        )
        if in_plan_rival is not None:
            # The rival loses its claim and becomes the skipped party.
            in_plan_rival.action = Action.COLLISION
            in_plan_rival.reason = Reason.COLLISION_SKIPPED
            in_plan_rival.collision = CollisionResolution.SKIPPED
            in_plan_rival.collided_with = item.source_path
        assigned[destination] = planned
        return planned

    return PlanItem(
        item,
        Action.COLLISION,
        destination_path=destination,
        reason=Reason.COLLISION_SKIPPED,
        collision=CollisionResolution.SKIPPED,
        collided_with=collided_with,
        detail="existing file kept",
    )


def _incoming_wins(
    incoming: datetime,
    incumbent: datetime | None,
    incoming_path: Path,
    incumbent_path: Path,
    prefers: ClobberPreference,
) -> bool:
    if incumbent is None:
        return True
    if incoming != incumbent:
        newer = incoming > incumbent
        return newer if prefers is ClobberPreference.NEWEST else not newer

    # Tie on capture date -> fall back to mtime.
    a, b = _mtime_or_none(incoming_path), _mtime_or_none(incumbent_path)
    if a is not None and b is not None and a != b:
        newer = a > b
        return newer if prefers is ClobberPreference.NEWEST else not newer

    # Still tied: the incumbent keeps the slot, so repeated runs are stable
    # instead of rewriting the same file every time.
    return False


def _mtime_or_none(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _safe_destination(library: Path, relative: Path, filename: str) -> Path:
    """Join untrusted *filename* under *library* without letting it escape.

    A single path component cannot contain a separator on Linux, so this is
    belt-and-braces -- but the filename is untrusted input and the cost of
    checking is a string comparison.
    """
    if not filename or filename in (".", "..") or "/" in filename or "\x00" in filename:
        raise ValueError(f"Unsafe filename: {filename!r}")
    candidate = library / relative / filename
    root = library.resolve()
    probe = root / relative / filename
    if not _is_within(probe, root):
        raise ValueError(f"Destination {probe} escapes library root {root}")
    return candidate


def _is_within(path: Path, root: Path) -> bool:
    try:
        return Path(os.path.normpath(str(path))).is_relative_to(root)
    except ValueError:
        return False


def _stat_destination(destination: Path, cache: dict[Path, _Existing | None]) -> _Existing | None:
    if destination in cache:
        return cache[destination]
    try:
        st = destination.stat()
        found = _Existing(destination, st.st_size, st.st_mtime)
    except (FileNotFoundError, NotADirectoryError):
        found = None
    except OSError as exc:  # pragma: no cover
        log.warning("Could not stat destination %s: %s", destination, exc)
        found = None
    cache[destination] = found
    return found


def _is_same_file(item: MediaItem, existing: _Existing, resolver: DateResolver) -> bool:
    """Whether *existing* is this importer's own earlier copy of *item*.

    Size is checked first because it is free.  Then mtime: copies are made with
    copy2, so a file we wrote carries its source's mtime and matches without
    any metadata read at all -- which is what keeps a repeat import over a
    large library cheap.  Only when mtime differs do we fall back to comparing
    resolved capture dates, and even that is a metadata read rather than a
    content hash.
    """
    try:
        source_stat = item.source_path.stat()
    except OSError:
        return False

    if source_stat.st_size != existing.size:
        return False

    if abs(source_stat.st_mtime - existing.mtime) < 1e-6:
        return True

    if item.resolved is None:
        return False
    other = _existing_date(existing, resolver)
    return other is not None and other == item.resolved.value


def _existing_date(existing: _Existing, resolver: DateResolver) -> datetime | None:
    if existing.resolved is None:
        media_type = classify(existing.path)
        try:
            existing.resolved = (
                resolver.resolve_photo(existing.path)
                if media_type is MediaType.PHOTO
                else resolver.resolve_video(existing.path)
            )
        except Exception:
            log.debug("Could not date existing file %s", existing.path)
            return None
    return existing.resolved.value if existing.resolved else None


def _next_free_name(
    destination: Path,
    assigned: dict[Path, PlanItem],
    existing_cache: dict[Path, _Existing | None],
) -> Path:
    """Lowest free ``stem-N.ext``, consulting both disk and this plan.

    Checking `assigned` matters: two collisions in one run would otherwise both
    pick ``-1``.
    """
    stem, suffix = destination.stem, destination.suffix
    for index in range(1, 10_000):
        candidate = destination.with_name(f"{stem}-{index}{suffix}")
        if candidate in assigned:
            continue
        if _stat_destination(candidate, existing_cache) is not None:
            continue
        if candidate.is_symlink():
            continue
        return candidate
    raise ValueError(f"Could not find a free name for {destination}")
