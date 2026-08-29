"""Entry-point behaviour.

v1 takes no command-line arguments, so the main assertion here is that argv is
irrelevant: nothing on the command line may stop the application from starting.
"""

from __future__ import annotations

import os
import stat
import sys

import pytest

from media_importer import cli


@pytest.fixture
def stubbed_tools(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("exiftool", "ffprobe"):
        script = bindir / name
        script.write_text("#!/bin/sh\necho '[]'\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    return bindir


def test_missing_tools_exit_with_code_2(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert cli.main() == 2
    assert "exiftool" in capsys.readouterr().err


def test_install_hint_names_every_distribution(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    cli.main()
    err = capsys.readouterr().err
    assert "apt install" in err and "dnf install" in err and "pacman" in err


def test_launches_the_tui_when_tools_are_present(stubbed_tools, monkeypatch):
    launched = {}

    class FakeApp:
        def __init__(self, config):
            launched["config"] = config

        def run(self):
            launched["ran"] = True

    monkeypatch.setattr("media_importer.tui.app.MediaImporterApp", FakeApp)
    assert cli.main() == 0
    assert launched["ran"] is True


@pytest.mark.parametrize(
    "argv",
    [
        ["media-importer"],
        ["media-importer", "--help"],
        ["media-importer", "--version"],
        ["media-importer", "--dry-run", "/some/path"],
        ["media-importer", "nonsense", "-x", "-y"],
    ],
)
def test_arguments_are_ignored_rather_than_rejected(stubbed_tools, monkeypatch, argv):
    """There is no argument parser, so argv must never prevent startup."""
    monkeypatch.setattr(sys, "argv", argv)

    class FakeApp:
        def __init__(self, config):
            pass

        def run(self):
            pass

    monkeypatch.setattr("media_importer.tui.app.MediaImporterApp", FakeApp)
    assert cli.main() == 0


def test_config_is_created_on_first_run(stubbed_tools, monkeypatch, tmp_path):
    class FakeApp:
        def __init__(self, config):
            pass

        def run(self):
            pass

    monkeypatch.setattr("media_importer.tui.app.MediaImporterApp", FakeApp)
    cli.main()
    assert (tmp_path / "config" / "media-importer" / "config.toml").exists()


def test_module_entry_point_exists():
    import media_importer.__main__ as entry

    assert entry.main is cli.main
