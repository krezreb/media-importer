"""TUI tests, driven headlessly through Textual's pilot.

These assert that the presentation layer is wired to the application services
and that a full import can be completed from the interface -- not that any
logic lives here, because none does.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from tests.conftest import FakeExtractor, make_file
from textual.widgets import Static

from media_importer.config import Config
from media_importer.models import CollisionPolicy
from media_importer.tui.app import MainScreen, MediaImporterApp, PreviewScreen, ReportScreen

DT = datetime(2025, 8, 27, 10, 53, 42)


def run(coro_factory):
    return asyncio.run(coro_factory())


def app_for(config: Config, extractor: FakeExtractor, tmp_path) -> MediaImporterApp:
    return MediaImporterApp(config, config_path=tmp_path / "config.toml", extractor=extractor)


def text_of(app, selector: str) -> str:
    return str(app.screen.query_one(selector, Static).content)


def test_main_screen_shows_current_configuration(config, extractor, tmp_path):
    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainScreen)
            shown = text_of(app, "#settings")
            assert str(config.source_path) in shown
            assert str(config.photo_library) in shown
            assert "YYYY/MM/DD" in shown

    run(go)


def test_incomplete_config_is_flagged(extractor, tmp_path):
    async def go():
        app = app_for(Config(), extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "Set all three directories" in text_of(app, "#notice")

    run(go)


def test_preview_reports_the_plan_without_copying(config, extractor, tmp_path):
    make_file(config.source_path / "IMG_1.JPG")
    make_file(config.source_path / "undated.png")
    extractor.dates["IMG_1.JPG"] = DT

    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_start_import()
            await pilot.pause()
            assert isinstance(app.screen, PreviewScreen)
            for _ in range(60):
                await pilot.pause(0.05)
                if app.screen.plan is not None:
                    break
            assert app.screen.plan is not None
            summary = text_of(app, "#summary")
            assert "Import summary" in summary
            assert "Files to import" in summary
            # Nothing has been copied at preview time.
            assert not any(config.photo_library.rglob("*.JPG"))
            # The undated file is listed by path, not merely counted.
            assert "undated.png" in text_of(app, "#details")

    run(go)


def test_full_import_through_the_interface(config, extractor, tmp_path):
    make_file(config.source_path / "a/IMG_1.JPG", b"one")
    make_file(config.source_path / "b/20250827_105030.mp4", b"two")
    extractor.dates["IMG_1.JPG"] = DT

    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_start_import()
            await pilot.pause()
            for _ in range(60):
                await pilot.pause(0.05)
                if getattr(app.screen, "plan", None) is not None:
                    break
            app.screen._proceed()
            for _ in range(80):
                await pilot.pause(0.05)
                if isinstance(app.screen, ReportScreen):
                    break
            assert isinstance(app.screen, ReportScreen)
            assert "Import complete" in text_of(app, "#report")

    run(go)

    assert (config.photo_library / "2025/08/27/IMG_1.JPG").read_bytes() == b"one"
    assert (config.video_library / "2025/08/27/20250827_105030.mp4").read_bytes() == b"two"


def test_invalid_configuration_blocks_the_import(config, extractor, tmp_path):
    config.photo_library = config.source_path / "inside"

    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.screen.action_start_import()
            await pilot.pause()
            # Rejected on the main screen; never reaches the preview.
            assert isinstance(app.screen, MainScreen)

    run(go)


def test_settings_changes_are_persisted(config, extractor, tmp_path):
    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.config.on_collision = CollisionPolicy.RENAME
            app.save_config()
            await pilot.pause()

    run(go)

    from media_importer.config import load

    assert load(tmp_path / "config.toml").on_collision is CollisionPolicy.RENAME
