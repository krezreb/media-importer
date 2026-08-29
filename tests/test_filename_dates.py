from datetime import datetime

import pytest

from media_importer.filename_dates import parse


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("20250827_105030.mp4", datetime(2025, 8, 27, 10, 50, 30)),
        ("IMG_20250827_105030.jpg", datetime(2025, 8, 27, 10, 50, 30)),
        ("VID_20250827_105030.mp4", datetime(2025, 8, 27, 10, 50, 30)),
        ("PXL_20250827_105030123.jpg", datetime(2025, 8, 27, 10, 50, 30)),
        ("2025-08-27 10.50.30.mov", datetime(2025, 8, 27, 10, 50, 30)),
        ("20250827105030.mp4", datetime(2025, 8, 27, 10, 50, 30)),
        ("2025-08-27.mp4", datetime(2025, 8, 27, 0, 0, 0)),
        ("20250827.mp4", datetime(2025, 8, 27, 0, 0, 0)),
    ],
)
def test_recognized_patterns(name, expected):
    assert parse(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "IMG_1234.JPG",
        "video.mp4",
        "12345678.mp4",  # not a plausible date
        "20250230_105030.mp4",  # February 30th
        "20251345_105030.mp4",  # month 13
        "18500827.mp4",  # before the floor year
        "",
    ],
)
def test_rejects_non_dates(name):
    assert parse(name) is None


def test_does_not_slice_a_longer_digit_run():
    """An arbitrary numeric sequence must not be mistaken for a date."""
    assert parse("123456789012.mp4") is None


def test_time_is_preferred_over_bare_date():
    assert parse("20250827_105030.mp4").hour == 10
