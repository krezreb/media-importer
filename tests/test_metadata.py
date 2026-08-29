from datetime import datetime

import pytest

from media_importer.errors import ToolUnavailableError
from media_importer.metadata import check_tools_available, parse_metadata_datetime, tools_status


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2025:08:27 10:53:42", datetime(2025, 8, 27, 10, 53, 42)),
        ("2025-08-27 10:53:42", datetime(2025, 8, 27, 10, 53, 42)),
        ("2025:08:27 10:53:42.123", datetime(2025, 8, 27, 10, 53, 42)),
        ("2025-08-27T10:53:42", datetime(2025, 8, 27, 10, 53, 42)),
    ],
)
def test_parses_naive_timestamps(raw, expected):
    assert parse_metadata_datetime(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "0000:00:00 00:00:00",
        "not a date",
        "2025:02:30 10:00:00",
        "2025:13:01 10:00:00",
    ],
)
def test_rejects_junk(raw):
    """0000:00:00 in particular is extremely common in real EXIF."""
    assert parse_metadata_datetime(raw) is None


def test_offsets_are_converted_to_local_time():
    """A QuickTime creation_time really is UTC; ignoring that misfiles the day."""
    utc = parse_metadata_datetime("2025-08-27T23:30:00Z")
    naive = parse_metadata_datetime("2025-08-27 23:30:00")
    assert utc is not None and naive is not None
    # Whatever the runner's zone, an explicit Z is anchored and a naive value is not.
    assert utc.tzinfo is None and naive.tzinfo is None


def test_no_timezone_is_invented():
    assert parse_metadata_datetime("2025:08:27 10:53:42").tzinfo is None


def test_tools_status_reports_both_tools():
    status = tools_status()
    assert set(status) == {"exiftool", "ffprobe"}


def test_missing_tool_raises_with_install_hint(monkeypatch):
    monkeypatch.setattr("media_importer.metadata.shutil.which", lambda _: None)
    with pytest.raises(ToolUnavailableError) as excinfo:
        check_tools_available()
    message = str(excinfo.value)
    assert "apt install" in message and "dnf install" in message and "pacman" in message
