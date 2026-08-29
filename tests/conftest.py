"""Shared fixtures.

Metadata extraction sits behind an interface precisely so tests can replace it.
Nothing in this suite needs exiftool, ffprobe, or a real media file.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from media_importer.config import Config
from media_importer.metadata import MetadataCandidate
from media_importer.models import DateSource, MediaType


class FakeExtractor:
    """In-memory `MetadataExtractor`.

    Maps a filename to either a datetime, a list of candidates, or None for
    "this file carries no metadata date".
    """

    def __init__(self, dates: dict[str, object] | None = None) -> None:
        self.dates = dates or {}
        self.prefetched: list[Path] = []

    def prefetch(self, paths: list[Path]) -> None:
        self.prefetched.extend(paths)

    def candidates(self, path: Path, media_type: MediaType) -> list[MetadataCandidate]:
        raw = self.dates.get(path.name)
        if raw is None:
            return []
        if isinstance(raw, list):
            return raw
        source = (
            DateSource.EXIF_DATE_TIME_ORIGINAL
            if media_type is MediaType.PHOTO
            else DateSource.VIDEO_METADATA
        )
        return [MetadataCandidate(raw, source, "fake")]


@pytest.fixture
def extractor() -> FakeExtractor:
    return FakeExtractor()


@pytest.fixture
def libraries(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "import"
    photos = tmp_path / "photos"
    videos = tmp_path / "videos"
    for directory in (source, photos, videos):
        directory.mkdir()
    return source, photos, videos


@pytest.fixture
def config(libraries: tuple[Path, Path, Path]) -> Config:
    source, photos, videos = libraries
    return Config(source_path=source, photo_library=photos, video_library=videos)


def make_file(path: Path, content: bytes = b"data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


DT = datetime(2025, 8, 27, 10, 53, 42)
