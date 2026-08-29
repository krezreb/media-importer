"""Typed models shared across the application.

Everything that crosses a module boundary is a dataclass or an enum; no
loosely-structured dicts or magic strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class MediaType(Enum):
    PHOTO = "photo"
    VIDEO = "video"
    UNKNOWN = "unknown"


class DateSource(Enum):
    """Where a resolved date came from.

    The filesystem variants are kept distinct on purpose: a birth time and an
    mtime carry very different confidence, and the user must be able to see
    which one dated a file rather than being shown an undifferentiated
    "filesystem" label.
    """

    EXIF_DATE_TIME_ORIGINAL = "EXIF DateTimeOriginal"
    EXIF_CREATE_DATE = "EXIF CreateDate"
    EXIF_DATE_TIME = "EXIF DateTime"
    VIDEO_METADATA = "video metadata"
    FILENAME = "filename"
    FS_BIRTH_TIME = "filesystem birth time"
    FS_MTIME = "filesystem mtime"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ResolvedDate:
    value: datetime
    source: DateSource
    detail: str | None = None
    """Tag name for metadata sources, e.g. ``QuickTime:CreateDate``."""

    @property
    def description(self) -> str:
        if self.detail:
            return f"{self.source} ({self.detail})"
        return str(self.source)


class Action(Enum):
    COPY = "copy"
    SKIP = "skip"
    COLLISION = "collision"
    UNDATED = "undated"
    ERROR = "error"


class Reason(Enum):
    ALREADY_IMPORTED = "already imported"
    JPEG_PAIRED_WITH_RAW = "JPEG paired with RAW"
    COLLISION_SKIPPED = "destination occupied by a different file"
    DESTINATION_IS_SYMLINK = "destination exists and is a symlink"
    NO_USABLE_DATE = "no usable capture date"
    METADATA_FAILED = "metadata could not be read"

    def __str__(self) -> str:
        return self.value


class CollisionResolution(Enum):
    """How a detected collision was resolved by the configured policy."""

    SKIPPED = "skipped"
    CLOBBERED = "clobbered"
    RENAMED = "renamed"


class IgnoreReason(Enum):
    SYMLINK = "symlink"
    UNSUPPORTED_EXTENSION = "unsupported extension"


class CollisionPolicy(Enum):
    SKIP = "skip"
    CLOBBER = "clobber"
    RENAME = "rename"


class ClobberPreference(Enum):
    NEWEST = "newest"
    OLDEST = "oldest"


@dataclass
class MediaItem:
    """A discovered, classified source file."""

    source_path: Path
    media_type: MediaType
    resolved: ResolvedDate | None = None
    error: str | None = None

    @property
    def filename(self) -> str:
        return self.source_path.name

    @property
    def extension(self) -> str:
        return self.source_path.suffix.lower()

    @property
    def stem(self) -> str:
        return self.source_path.stem

    @property
    def is_dated(self) -> bool:
        return self.resolved is not None


@dataclass
class IgnoredFile:
    path: Path
    reason: IgnoreReason


@dataclass
class PlanItem:
    """One planned operation.  Produced by the planner, consumed by the importer."""

    item: MediaItem
    action: Action
    destination_path: Path | None = None
    reason: Reason | None = None
    collision: CollisionResolution | None = None
    collided_with: Path | None = None
    detail: str | None = None

    @property
    def source_path(self) -> Path:
        return self.item.source_path

    @property
    def media_type(self) -> MediaType:
        return self.item.media_type

    @property
    def filename(self) -> str:
        return self.item.filename

    @property
    def resolved_datetime(self) -> datetime | None:
        return self.item.resolved.value if self.item.resolved else None

    @property
    def date_source(self) -> DateSource | None:
        return self.item.resolved.source if self.item.resolved else None


@dataclass
class ImportPlan:
    items: list[PlanItem] = field(default_factory=list)
    ignored: list[IgnoredFile] = field(default_factory=list)

    def _with_action(self, action: Action) -> list[PlanItem]:
        return [i for i in self.items if i.action is action]

    def _with_reason(self, reason: Reason) -> list[PlanItem]:
        return [i for i in self.items if i.reason is reason]

    @property
    def to_copy(self) -> list[PlanItem]:
        return self._with_action(Action.COPY)

    @property
    def already_imported(self) -> list[PlanItem]:
        return self._with_reason(Reason.ALREADY_IMPORTED)

    @property
    def paired_jpegs(self) -> list[PlanItem]:
        return self._with_reason(Reason.JPEG_PAIRED_WITH_RAW)

    @property
    def undated(self) -> list[PlanItem]:
        return self._with_action(Action.UNDATED)

    @property
    def collisions(self) -> list[PlanItem]:
        return self._with_action(Action.COLLISION)

    @property
    def errors(self) -> list[PlanItem]:
        return self._with_action(Action.ERROR)

    @property
    def photos(self) -> list[PlanItem]:
        return [i for i in self.items if i.media_type is MediaType.PHOTO]

    @property
    def videos(self) -> list[PlanItem]:
        return [i for i in self.items if i.media_type is MediaType.VIDEO]

    @property
    def symlinks(self) -> list[IgnoredFile]:
        return [f for f in self.ignored if f.reason is IgnoreReason.SYMLINK]

    @property
    def unsupported(self) -> list[IgnoredFile]:
        return [f for f in self.ignored if f.reason is IgnoreReason.UNSUPPORTED_EXTENSION]

    def check_partition(self) -> None:
        """The reported categories must account for every discovered item exactly once.

        A miscount here means the preview would mislead the user about what is
        about to happen, so it is an internal invariant rather than a display
        detail.
        """
        counted = (
            len(self.to_copy)
            + len(self.already_imported)
            + len(self.paired_jpegs)
            + len(self.undated)
            + len(self.collisions)
            + len(self.errors)
        )
        if counted != len(self.items):
            raise AssertionError(
                f"plan categories cover {counted} items but plan holds {len(self.items)}"
            )


@dataclass
class ImportReport:
    copied: list[PlanItem] = field(default_factory=list)
    failed: list[tuple[PlanItem, str]] = field(default_factory=list)
    plan: ImportPlan | None = None

    @property
    def copied_count(self) -> int:
        return len(self.copied)

    @property
    def failed_count(self) -> int:
        return len(self.failed)
