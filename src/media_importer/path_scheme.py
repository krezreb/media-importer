"""Destination path scheme formatting and validation.

This module knows nothing about photos, videos, or libraries.  It answers only:
given a date and a scheme string, what relative path does that produce?
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path, PurePosixPath

from .errors import ConfigurationError

DEFAULT_SCHEME = "YYYY/MM/DD"

# Longest-first: YYYY must be tried before YY, or "YYYY" tokenizes as two YYs.
_TOKENS: tuple[tuple[str, str], ...] = (
    ("YYYY", "%Y"),
    ("YY", "%y"),
    ("MM", "%m"),
    ("DD", "%d"),
)

TOKEN_HELP = "YYYY (4-digit year), YY (2-digit year), MM (month), DD (day)"

# After valid tokens are removed, no bare Y/M/D may remain.  This is what
# catches typos like YYY or MMM, which would otherwise pass silently as
# literals and quietly produce a wrong directory layout.  The cost is that
# literal path segments must avoid uppercase Y, M and D -- use lowercase.
_RESERVED_LETTERS = frozenset("YMD")

_TOKEN_RE = re.compile("|".join(tok for tok, _ in _TOKENS))


def validate(scheme: str) -> None:
    """Raise `ConfigurationError` if *scheme* is not a usable path scheme."""
    if not scheme or not scheme.strip():
        raise ConfigurationError("Path scheme is empty.")

    if "\x00" in scheme:
        raise ConfigurationError("Path scheme contains a null byte.")

    if scheme.startswith("/"):
        raise ConfigurationError(
            f"Path scheme {scheme!r} is absolute. It must be relative to the library root."
        )

    for literal in _TOKEN_RE.split(scheme):
        if any(ch in _RESERVED_LETTERS for ch in literal):
            raise ConfigurationError(
                f"Path scheme {scheme!r} contains an unknown token in {literal!r}. "
                f"Supported tokens are: {TOKEN_HELP}. Literal text must not contain "
                f"an uppercase Y, M or D -- use lowercase (e.g. 'media/YYYY')."
            )

    parts = PurePosixPath(scheme).parts
    if not parts:
        raise ConfigurationError(f"Path scheme {scheme!r} produces no path.")
    for part in parts:
        if part in (".", ".."):
            raise ConfigurationError(
                f"Path scheme {scheme!r} contains a path traversal component {part!r}."
            )

    # A scheme is allowed to contain no date tokens at all (everything then
    # lands in one directory), but it must still produce a non-empty path.
    probe = format_path(datetime(2025, 8, 27), scheme, _validated=True)
    if not probe.parts:
        raise ConfigurationError(f"Path scheme {scheme!r} produces an empty path.")
    if probe.is_absolute():
        raise ConfigurationError(f"Path scheme {scheme!r} produced an absolute path.")


def format_path(date: datetime, scheme: str, *, _validated: bool = False) -> Path:
    """Render *scheme* for *date* as a relative path."""
    if not _validated:
        validate(scheme)

    out: list[str] = []
    i = 0
    while i < len(scheme):
        for token, fmt in _TOKENS:
            if scheme.startswith(token, i):
                out.append(date.strftime(fmt))
                i += len(token)
                break
        else:
            out.append(scheme[i])
            i += 1

    rendered = "".join(out)
    # Drop empty components so that a scheme like "YYYY//MM" or a trailing
    # slash does not produce a surprising path.
    parts = [p for p in PurePosixPath(rendered).parts if p not in ("", "/")]
    return Path(*parts)
