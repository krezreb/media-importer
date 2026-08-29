"""Entry point.

v1 takes no command-line arguments: both entry points go straight to the TUI.
There is deliberately no argument parser here -- an unexpected argv must never
stop the application from starting.  A --dry-run flag would be redundant in any
case, since the import preview is already a mandatory dry run.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from . import config as config_module
from .errors import ConfigurationError, ToolUnavailableError
from .metadata import check_tools_available


def _setup_logging() -> None:
    """Log to a file: the TUI owns the terminal, so stdout is not available."""
    directory = config_module.config_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            directory / "media-importer.log", maxBytes=1_000_000, backupCount=2
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


def main() -> int:
    _setup_logging()
    log = logging.getLogger(__name__)

    try:
        check_tools_available()
    except ToolUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        config = config_module.load()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    from .tui.app import MediaImporterApp

    log.info("Starting media-importer")
    try:
        MediaImporterApp(config).run()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
