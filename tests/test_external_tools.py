"""Integration tests for `ExternalToolExtractor`.

exiftool and ffprobe are replaced by small stub executables that emit real
sample output, so the subprocess handling, JSON parsing and batching are all
exercised without requiring either tool to be installed.
"""

from __future__ import annotations

import os
import stat
from datetime import datetime
from pathlib import Path

import pytest

from media_importer.metadata import ExternalToolExtractor
from media_importer.models import DateSource, MediaType


def write_stub(directory: Path, name: str, body: str) -> Path:
    script = directory / name
    script.write_text(f"#!/usr/bin/env python3\n{body}")
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


EXIFTOOL_STUB = """
import json, sys
files = [a for a in sys.argv[1:] if not a.startswith('-')]
# -charset takes a value argument; drop it if present.
files = [f for f in files if '=' not in f]
out = []
for f in files:
    record = {"SourceFile": f}
    if "good" in f:
        record["DateTimeOriginal"] = "2025:08:27 10:53:42"
        record["CreateDate"] = "2020:01:01 00:00:00"
    elif "zeros" in f:
        record["DateTimeOriginal"] = "0000:00:00 00:00:00"
    elif "fallback" in f:
        record["DateTime"] = "2025:08:27 10:53:42"
    out.append(record)
print(json.dumps(out))
"""

FFPROBE_STUB = """
import json, sys
path = sys.argv[-1]
payload = {"streams": [], "format": {"tags": {}}}
if "meta" in path:
    payload["format"]["tags"]["creation_time"] = "2025-08-27T10:50:30.000000Z"
elif "junk" in path:
    payload["format"]["tags"]["creation_time"] = "1904-01-01T00:00:00.000000Z"
print(json.dumps(payload))
"""


@pytest.fixture
def stub_tools(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    write_stub(bindir, "exiftool", EXIFTOOL_STUB)
    write_stub(bindir, "ffprobe", FFPROBE_STUB)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    return bindir


def test_tools_are_detected(stub_tools):
    from media_importer.metadata import check_tools_available, tools_status

    check_tools_available()
    assert all(tools_status().values())


class TestExiftool:
    def test_reads_date_time_original(self, stub_tools, tmp_path):
        photo = tmp_path / "good.jpg"
        photo.write_bytes(b"x")
        candidates = ExternalToolExtractor().candidates(photo, MediaType.PHOTO)
        assert candidates[0].value == datetime(2025, 8, 27, 10, 53, 42)
        assert candidates[0].source is DateSource.EXIF_DATE_TIME_ORIGINAL

    def test_candidates_come_back_in_priority_order(self, stub_tools, tmp_path):
        photo = tmp_path / "good.jpg"
        photo.write_bytes(b"x")
        sources = [c.source for c in ExternalToolExtractor().candidates(photo, MediaType.PHOTO)]
        assert sources == [DateSource.EXIF_DATE_TIME_ORIGINAL, DateSource.EXIF_CREATE_DATE]

    def test_all_zero_exif_yields_no_candidate(self, stub_tools, tmp_path):
        photo = tmp_path / "zeros.jpg"
        photo.write_bytes(b"x")
        assert ExternalToolExtractor().candidates(photo, MediaType.PHOTO) == []

    def test_missing_fields_yield_no_candidates(self, stub_tools, tmp_path):
        photo = tmp_path / "plain.jpg"
        photo.write_bytes(b"x")
        assert ExternalToolExtractor().candidates(photo, MediaType.PHOTO) == []

    def test_batch_prefetch_covers_every_file(self, stub_tools, tmp_path):
        paths = []
        for n in range(5):
            photo = tmp_path / f"good_{n}.jpg"
            photo.write_bytes(b"x")
            paths.append(photo)

        extractor = ExternalToolExtractor()
        extractor.prefetch(paths)
        for photo in paths:
            assert extractor.candidates(photo, MediaType.PHOTO)


class TestFfprobe:
    def test_reads_container_creation_time(self, stub_tools, tmp_path):
        video = tmp_path / "meta.mp4"
        video.write_bytes(b"x")
        candidates = ExternalToolExtractor().candidates(video, MediaType.VIDEO)
        assert candidates
        assert candidates[0].source is DateSource.VIDEO_METADATA

    def test_utc_is_converted_to_local(self, stub_tools, tmp_path):
        """An explicit Z is anchored; the calendar day must follow local time."""
        video = tmp_path / "meta.mp4"
        video.write_bytes(b"x")
        value = ExternalToolExtractor().candidates(video, MediaType.VIDEO)[0].value
        expected = (
            datetime.fromisoformat("2025-08-27T10:50:30+00:00").astimezone().replace(tzinfo=None)
        )
        assert value == expected

    def test_no_tags_yields_no_candidates(self, stub_tools, tmp_path):
        video = tmp_path / "plain.mp4"
        video.write_bytes(b"x")
        assert ExternalToolExtractor().candidates(video, MediaType.VIDEO) == []

    def test_junk_epoch_is_still_returned_for_the_resolver_to_reject(self, stub_tools, tmp_path):
        """Plausibility is the resolver's job, not the extractor's."""
        video = tmp_path / "junk.mp4"
        video.write_bytes(b"x")
        candidates = ExternalToolExtractor().candidates(video, MediaType.VIDEO)
        assert candidates and candidates[0].value.year == 1904


class TestFailureModes:
    def test_unparseable_output_is_survivable(self, tmp_path, monkeypatch):
        bindir = tmp_path / "bin"
        bindir.mkdir()
        write_stub(bindir, "exiftool", "print('not json at all')")
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        photo = tmp_path / "a.jpg"
        photo.write_bytes(b"x")
        assert ExternalToolExtractor().candidates(photo, MediaType.PHOTO) == []

    def test_a_hanging_tool_times_out(self, tmp_path, monkeypatch):
        """A malformed file must not be able to stall the whole import."""
        bindir = tmp_path / "bin"
        bindir.mkdir()
        write_stub(bindir, "ffprobe", "import time\ntime.sleep(30)")
        monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
        video = tmp_path / "a.mp4"
        video.write_bytes(b"x")
        assert ExternalToolExtractor(timeout=1).candidates(video, MediaType.VIDEO) == []

    def test_missing_tool_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        photo = tmp_path / "a.jpg"
        photo.write_bytes(b"x")
        from media_importer.errors import ToolUnavailableError

        with pytest.raises(ToolUnavailableError):
            ExternalToolExtractor().candidates(photo, MediaType.PHOTO)


def test_filenames_with_spaces_and_unicode(stub_tools, tmp_path):
    """Arguments are passed as a list, never through a shell."""
    photo = tmp_path / "good photo (café) 'quoted'.jpg"
    photo.write_bytes(b"x")
    assert ExternalToolExtractor().candidates(photo, MediaType.PHOTO)
