"""Persistent configuration: loading, validation, saving.

The rest of the application consumes a validated `Config` object and never
parses TOML itself.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w

from .errors import ConfigurationError
from .models import ClobberPreference, CollisionPolicy
from .path_scheme import DEFAULT_SCHEME
from .path_scheme import validate as validate_scheme

log = logging.getLogger(__name__)

APP_NAME = "media-importer"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / APP_NAME


def config_file() -> Path:
    return config_dir() / "config.toml"


@dataclass
class Config:
    source_path: Path | None = None
    photo_library: Path | None = None
    video_library: Path | None = None
    import_path: str = DEFAULT_SCHEME
    on_collision: CollisionPolicy = CollisionPolicy.SKIP
    clobber_prefers: ClobberPreference = ClobberPreference.NEWEST

    extra: dict = field(default_factory=dict, repr=False)
    """Keys written by a newer version, preserved so an older one cannot eat them."""

    @property
    def is_complete(self) -> bool:
        return all((self.source_path, self.photo_library, self.video_library))

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "source_path": str(self.source_path or ""),
            "photo_library": str(self.photo_library or ""),
            "video_library": str(self.video_library or ""),
            "import_path": self.import_path,
            "on_collision": self.on_collision.value,
            "clobber_prefers": self.clobber_prefers.value,
        }


_KNOWN_KEYS = {
    "source_path",
    "photo_library",
    "video_library",
    "import_path",
    "on_collision",
    "clobber_prefers",
}


def _as_path(raw) -> Path | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return Path(text).expanduser() if text else None


def _as_enum(raw, enum_cls, key: str, default):
    if raw is None:
        return default
    try:
        return enum_cls(str(raw).strip().lower())
    except ValueError:
        allowed = ", ".join(repr(m.value) for m in enum_cls)
        raise ConfigurationError(
            f"Invalid value {raw!r} for {key!r}. Allowed values are: {allowed}."
        ) from None


def from_dict(data: dict) -> Config:
    return Config(
        source_path=_as_path(data.get("source_path")),
        photo_library=_as_path(data.get("photo_library")),
        video_library=_as_path(data.get("video_library")),
        import_path=str(data.get("import_path") or DEFAULT_SCHEME),
        on_collision=_as_enum(
            data.get("on_collision"), CollisionPolicy, "on_collision", CollisionPolicy.SKIP
        ),
        clobber_prefers=_as_enum(
            data.get("clobber_prefers"),
            ClobberPreference,
            "clobber_prefers",
            ClobberPreference.NEWEST,
        ),
        extra={k: v for k, v in data.items() if k not in _KNOWN_KEYS},
    )


def load(path: Path | None = None) -> Config:
    """Load configuration, creating a default file on first run."""
    target = path or config_file()
    if not target.exists():
        cfg = Config()
        save(cfg, target)
        return cfg

    try:
        with target.open("rb") as fh:
            data = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigurationError(f"Could not parse {target}: {exc}") from exc
    except OSError as exc:
        raise ConfigurationError(f"Could not read {target}: {exc}") from exc

    return from_dict(data)


def save(config: Config, path: Path | None = None) -> None:
    target = path or config_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write-and-rename so an interrupted save cannot truncate the config.
        tmp = target.with_suffix(".toml.tmp")
        with tmp.open("wb") as fh:
            tomli_w.dump(config.to_dict(), fh)
        os.replace(tmp, target)
    except OSError as exc:
        raise ConfigurationError(f"Could not write {target}: {exc}") from exc


def _assert_not_nested(a: Path, label_a: str, b: Path, label_b: str) -> None:
    ra, rb = a.resolve(), b.resolve()
    if ra == rb:
        raise ConfigurationError(
            f"{label_a} and {label_b} are the same directory ({ra}). "
            f"The importer would rescan files it just wrote."
        )
    if ra.is_relative_to(rb) or rb.is_relative_to(ra):
        raise ConfigurationError(
            f"{label_a} ({ra}) and {label_b} ({rb}) are nested. "
            f"The importer would rescan files it just wrote. "
            f"Choose directories that do not contain one another."
        )


def validate_for_import(config: Config) -> None:
    """Full pre-flight validation. Raises `ConfigurationError` on any problem."""
    missing = [
        name
        for name, value in (
            ("source_path", config.source_path),
            ("photo_library", config.photo_library),
            ("video_library", config.video_library),
        )
        if value is None
    ]
    if missing:
        raise ConfigurationError(
            "Not configured yet: " + ", ".join(missing) + ". Set these before importing."
        )

    assert config.source_path and config.photo_library and config.video_library

    if not config.source_path.exists():
        raise ConfigurationError(f"Source directory does not exist: {config.source_path}")
    if not config.source_path.is_dir():
        raise ConfigurationError(f"Source path is not a directory: {config.source_path}")

    for label, lib in (
        ("photo_library", config.photo_library),
        ("video_library", config.video_library),
    ):
        if lib.exists() and not lib.is_dir():
            raise ConfigurationError(f"{label} exists but is not a directory: {lib}")
        if not lib.exists():
            try:
                lib.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ConfigurationError(f"Could not create {label} at {lib}: {exc}") from exc

    # Resolved before comparing, so symlinked indirection cannot defeat the check.
    _assert_not_nested(config.source_path, "source_path", config.photo_library, "photo_library")
    _assert_not_nested(config.source_path, "source_path", config.video_library, "video_library")

    validate_scheme(config.import_path)
