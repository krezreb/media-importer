"""Application exception hierarchy.

Note the deliberate absence of a class named ``ImportError``: that shadows a
builtin, and a bare ``except ImportError:`` anywhere in this codebase or in a
dependency would then swallow application errors alongside genuine module
import failures.  The equivalent here is `MediaImportError`.
"""

from __future__ import annotations

from pathlib import Path


class MediaImporterError(Exception):
    """Base class for every error raised by this application."""


class ConfigurationError(MediaImporterError):
    """Configuration is missing, malformed, or internally inconsistent."""


class MetadataError(MediaImporterError):
    """A metadata tool failed, or returned something unusable, for one file."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


class DateResolutionError(MediaImporterError):
    """A date could not be resolved for reasons other than simply being absent."""


class DestinationCollision(MediaImporterError):
    """A destination path is occupied by a different file."""


class MediaImportError(MediaImporterError):
    """A planned copy failed during execution."""

    def __init__(self, source: Path, destination: Path, message: str) -> None:
        super().__init__(f"{source} -> {destination}: {message}")
        self.source = source
        self.destination = destination
        self.message = message


class ToolUnavailableError(ConfigurationError):
    """A required external tool (exiftool / ffprobe) is not on PATH."""

    def __init__(self, tool: str) -> None:
        super().__init__(f"Required external tool {tool!r} was not found on PATH.\n{INSTALL_HINT}")
        self.tool = tool


INSTALL_HINT = """\
media-importer needs `exiftool` and `ffprobe` to read capture dates.
They are not Python packages, so pip cannot install them.

  Debian / Ubuntu / WSL:  sudo apt install libimage-exiftool-perl ffmpeg
  Fedora:                 sudo dnf install perl-Image-ExifTool ffmpeg-free
  Arch:                   sudo pacman -S perl-image-exiftool ffmpeg

(`ffprobe` ships inside the ffmpeg package.)"""
