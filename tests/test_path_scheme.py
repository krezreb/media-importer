from datetime import datetime

import pytest

from media_importer.errors import ConfigurationError
from media_importer.path_scheme import format_path, validate

DATE = datetime(2025, 8, 27, 10, 53, 42)


@pytest.mark.parametrize(
    ("scheme", "expected"),
    [
        ("YYYY/MM/DD", "2025/08/27"),
        ("YYYY-MM-DD", "2025-08-27"),
        ("YYYY/MM", "2025/08"),
        ("YYYY", "2025"),
        ("YY/MM/DD", "25/08/27"),
        ("YYYY/YYYY-MM-DD", "2025/2025-08-27"),
        ("YYYY/MM/YYYY-MM-DD", "2025/08/2025-08-27"),
        ("photos/YYYY", "photos/2025"),
        ("archive", "archive"),
    ],
)
def test_supported_schemes(scheme, expected):
    assert format_path(DATE, scheme).as_posix() == expected


def test_yyyy_wins_over_yy():
    """Longest-match-first: YYYY must not tokenize as two YYs."""
    assert format_path(DATE, "YYYY").as_posix() == "2025"


def test_literals_are_preserved():
    assert format_path(DATE, "YYYY_shoot/MM").as_posix() == "2025_shoot/08"


@pytest.mark.parametrize(
    "scheme",
    ["", "   ", "/absolute/YYYY", "YYYY/../etc", "../YYYY", "YYY/MM", "YYYY/MMM", "YYYY/DDD"],
)
def test_rejected_schemes(scheme):
    with pytest.raises(ConfigurationError):
        validate(scheme)


def test_uppercase_token_letters_rejected_in_literals():
    """This is what turns a typo into an error instead of a silent directory name."""
    with pytest.raises(ConfigurationError):
        validate("MEDIA/YYYY")


def test_lowercase_literals_are_fine():
    validate("media/YYYY/MM")
    assert format_path(DATE, "media/YYYY/MM").as_posix() == "media/2025/08"


def test_result_is_always_relative():
    for scheme in ("YYYY/MM/DD", "YYYY", "photos/YYYY"):
        assert not format_path(DATE, scheme).is_absolute()


def test_extra_separators_collapse():
    assert format_path(DATE, "YYYY//MM/").as_posix() == "2025/08"
