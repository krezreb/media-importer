"""Metadata extraction, isolated behind an abstraction.

Two external tools do the actual reading -- ``exiftool`` for photos and RAW,
``ffprobe`` for video containers.  No pip-installable library covers EXIF
across every RAW variant and container metadata across every video format well
enough to replace them.

Both emit JSON, so nothing here scrapes human-readable output.  The date
resolver sees only normalized `MetadataCandidate` values and never the shape of
either tool's response, so swapping the backend later touches only this module.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Protocol

from .errors import ToolUnavailableError
from .models import DateSource, MediaType

log = logging.getLogger(__name__)

EXIFTOOL = "exiftool"
FFPROBE = "ffprobe"

TOOL_TIMEOUT = 60
"""Seconds. A malformed file must not be able to hang the whole import."""

_BATCH_SIZE = 200
"""Files per exiftool invocation, bounded to stay well inside ARG_MAX."""

# EXIF fields, in the fixed priority order the resolver applies.  The list is
# closed rather than open-ended so photo dating stays deterministic.
_EXIF_FIELDS: tuple[tuple[str, DateSource], ...] = (
    ("DateTimeOriginal", DateSource.EXIF_DATE_TIME_ORIGINAL),
    ("CreateDate", DateSource.EXIF_CREATE_DATE),
    ("DateTime", DateSource.EXIF_DATE_TIME),
)

_EXIF_RE = re.compile(
    r"^(?P<Y>\d{4})[:\-](?P<M>\d{2})[:\-](?P<D>\d{2})"
    r"[ T](?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})"
    r"(?:\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)


@dataclass(frozen=True)
class MetadataCandidate:
    value: datetime
    source: DateSource
    detail: str


class MetadataExtractor(Protocol):
    """The surface the date resolver depends on."""

    def prefetch(self, paths: list[Path]) -> None: ...

    def candidates(self, path: Path, media_type: MediaType) -> list[MetadataCandidate]: ...


def parse_metadata_datetime(raw: str) -> datetime | None:
    """Parse an EXIF or ISO-8601 timestamp into a naive *local* datetime.

    An explicit offset is honoured and converted to local time, because a
    QuickTime ``creation_time`` really is UTC and an evening recording would
    otherwise land in the wrong day directory.  A naive value is left alone --
    no timezone is invented for it.
    """
    if not raw:
        return None
    text = raw.strip()
    # Very common EXIF placeholder for "no date recorded".
    if text.startswith("0000") or set(text) <= set("0:- .T"):
        return None

    m = _EXIF_RE.match(text)
    if not m:
        return None

    g = m.groupdict()
    try:
        value = datetime(
            int(g["Y"]),
            int(g["M"]),
            int(g["D"]),
            int(g["h"]),
            int(g["m"]),
            int(g["s"]),
        )
    except ValueError:
        return None

    tz = g.get("tz")
    if tz:
        offset = UTC if tz == "Z" else _parse_offset(tz)
        if offset is not None:
            value = value.replace(tzinfo=offset).astimezone().replace(tzinfo=None)
    return value


def _parse_offset(tz: str) -> timezone | None:
    from datetime import timedelta

    sign = 1 if tz[0] == "+" else -1
    digits = tz[1:].replace(":", "")
    try:
        hours, minutes = int(digits[:2]), int(digits[2:4])
    except ValueError:
        return None
    return timezone(sign * timedelta(hours=hours, minutes=minutes))


def check_tools_available() -> None:
    """Fail fast at startup rather than obscurely on the first file."""
    for tool in (EXIFTOOL, FFPROBE):
        if shutil.which(tool) is None:
            raise ToolUnavailableError(tool)


def tools_status() -> dict[str, str | None]:
    return {tool: shutil.which(tool) for tool in (EXIFTOOL, FFPROBE)}


class ExternalToolExtractor:
    """`MetadataExtractor` backed by exiftool and ffprobe."""

    def __init__(self, timeout: int = TOOL_TIMEOUT) -> None:
        self.timeout = timeout
        self._photo_cache: dict[Path, list[MetadataCandidate]] = {}

    # -- exiftool ---------------------------------------------------------

    def prefetch(self, paths: list[Path]) -> None:
        """Read many photos in a few exiftool calls.

        exiftool's startup cost dominates its per-file runtime, so invoking it
        once per file makes a large import needlessly slow.
        """
        pending = [p for p in paths if p not in self._photo_cache]
        for start in range(0, len(pending), _BATCH_SIZE):
            self._prefetch_batch(pending[start : start + _BATCH_SIZE])

    def _prefetch_batch(self, batch: list[Path]) -> None:
        if not batch:
            return
        argv = [EXIFTOOL, "-json", "-n", "-charset", "filename=utf8"]
        argv += [f"-{field}" for field, _ in _EXIF_FIELDS]
        argv += [str(p) for p in batch]

        payload = self._run_json(argv)
        by_path = {}
        if isinstance(payload, list):
            for record in payload:
                if not isinstance(record, dict):
                    continue
                src = record.get("SourceFile")
                if src:
                    by_path[Path(src).resolve()] = record

        for path in batch:
            record = by_path.get(path.resolve(), {})
            self._photo_cache[path] = _photo_candidates_from(record)

    # -- ffprobe ----------------------------------------------------------

    def _video_candidates(self, path: Path) -> list[MetadataCandidate]:
        argv = [
            FFPROBE,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        payload = self._run_json(argv)
        if not isinstance(payload, dict):
            return []

        out: list[MetadataCandidate] = []
        containers: list[tuple[str, dict]] = []
        fmt = payload.get("format")
        if isinstance(fmt, dict):
            containers.append(("format", fmt))
        for idx, stream in enumerate(payload.get("streams") or []):
            if isinstance(stream, dict):
                containers.append((f"stream{idx}", stream))

        for where, container in containers:
            tags = container.get("tags")
            if not isinstance(tags, dict):
                continue
            for key, raw in tags.items():
                if "creation_time" not in key.lower() and "date" not in key.lower():
                    continue
                parsed = parse_metadata_datetime(str(raw))
                if parsed is not None:
                    out.append(
                        MetadataCandidate(parsed, DateSource.VIDEO_METADATA, f"{where}:{key}")
                    )
        return out

    # -- shared -----------------------------------------------------------

    def _run_json(self, argv: list[str]):
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except FileNotFoundError:
            raise ToolUnavailableError(argv[0]) from None
        except subprocess.TimeoutExpired:
            log.warning("%s timed out after %ss", argv[0], self.timeout)
            return None

        if not proc.stdout.strip():
            return None
        try:
            return json.loads(proc.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            log.warning("%s returned unparseable JSON", argv[0])
            return None

    def candidates(self, path: Path, media_type: MediaType) -> list[MetadataCandidate]:
        if media_type is MediaType.PHOTO:
            if path not in self._photo_cache:
                self._prefetch_batch([path])
            return self._photo_cache.get(path, [])
        if media_type is MediaType.VIDEO:
            return self._video_candidates(path)
        return []


def _photo_candidates_from(record: dict) -> list[MetadataCandidate]:
    out: list[MetadataCandidate] = []
    for field, source in _EXIF_FIELDS:
        raw = record.get(field)
        if raw is None:
            continue
        parsed = parse_metadata_datetime(str(raw))
        if parsed is not None:
            out.append(MetadataCandidate(parsed, source, f"EXIF:{field}"))
    return out
