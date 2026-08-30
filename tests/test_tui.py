"""TUI tests, driven headlessly through Textual's pilot.

These assert that the presentation layer is wired to the application services
and that a full import can be completed from the interface -- including by
mouse -- not that any logic lives here, because none does.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from tests.conftest import FakeExtractor, make_file
from textual.widgets import Button, ProgressBar, Static

from media_importer.config import Config
from media_importer.models import CollisionPolicy, ImportAction
from media_importer.tui.app import (
    ChoiceScreen,
    ImportScreen,
    MainScreen,
    MediaImporterApp,
    SettingRow,
    StepLog,
    StepRow,
)

DT = datetime(2025, 8, 27, 10, 53, 42)


def run(coro_factory):
    return asyncio.run(coro_factory())


def app_for(config: Config, extractor: FakeExtractor, tmp_path) -> MediaImporterApp:
    return MediaImporterApp(config, config_path=tmp_path / "config.toml", extractor=extractor)


def text_of(app, selector: str) -> str:
    return str(app.screen.query_one(selector, Static).content)


async def settle(app, pilot):
    """Wait for background workers, then let the resulting UI updates land."""
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def wait_until(pilot, predicate, what, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        await pilot.pause(0.02)
    raise AssertionError(f"timed out after {timeout}s waiting for {what}")


async def reach_summary(app, pilot):
    app.screen.action_start_import()
    await settle(app, pilot)
    await wait_until(pilot, lambda: getattr(app.screen, "plan", None) is not None, "the plan")


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


class TestSettings:
    def test_every_setting_has_its_value_and_button_together(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                rows = list(app.screen.query(SettingRow))
                assert [r.button_id for r in rows] == [
                    "edit-source",
                    "edit-photos",
                    "edit-videos",
                    "edit-scheme",
                    "edit-action",
                    "edit-collision",
                ]
                # Each row carries its own value and its own change button.
                for row in rows:
                    assert row.query_one(".setting-value", Static) is not None
                    assert row.query_one(Button).id == row.button_id

        run(go)

    def test_values_are_shown(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                rows = {r.button_id: r for r in app.screen.query(SettingRow)}
                assert str(config.source_path) in str(
                    rows["edit-source"].query_one(".setting-value", Static).content
                )
                assert "YYYY/MM/DD" in str(
                    rows["edit-scheme"].query_one(".setting-value", Static).content
                )
                assert "copy" in str(
                    rows["edit-action"].query_one(".setting-value", Static).content
                )

        run(go)

    def test_missing_directories_are_flagged_in_the_same_place(self, extractor, tmp_path):
        async def go():
            app = app_for(Config(), extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                notice = text_of(app, "#notice")
                assert "source directory" in notice
                assert "photo library" in notice
                assert "video library" in notice

        run(go)

    def test_move_mode_states_its_effect_on_the_main_screen(self, config, extractor, tmp_path):
        """Stated plainly, in terms of where the files end up -- not as an alarm."""
        config.import_action = ImportAction.MOVE

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                notice = text_of(app, "#notice")
                assert "no longer be present in the import directory" in notice
                assert "delet" not in notice.lower()

        run(go)

    def test_both_actions_describe_where_files_end_up(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                row = next(r for r in app.screen.query(SettingRow) if r.button_id == "edit-action")
                value = str(row.query_one(".setting-value", Static).content)
                assert "originals stay in the import directory" in value
                assert "delet" not in value.lower()

        run(go)

    def test_start_button_is_labelled_start_import_process(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                assert str(app.screen.query_one("#start", Button).label) == "Start import process"

        run(go)


# --------------------------------------------------------------------------
# Mouse
# --------------------------------------------------------------------------


class TestMouse:
    def test_clicking_a_setting_button_opens_its_editor(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#edit-scheme")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "EditValueScreen"

        run(go)

    def test_clicking_import_action_opens_the_copy_move_choice(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#edit-action")
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                ids = {b.id for b in app.screen.query(Button)}
                assert {"opt-copy", "opt-move"} <= ids

        run(go)

    def test_choosing_move_by_mouse_persists_it(self, config, extractor, tmp_path):
        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#edit-action")
                await pilot.pause()
                await pilot.click("#opt-move")
                await pilot.pause()
                assert app.config.import_action is ImportAction.MOVE

        run(go)

        from media_importer.config import load

        assert load(tmp_path / "config.toml").import_action is ImportAction.MOVE

    def test_clicking_start_begins_the_import_process(self, config, extractor, tmp_path):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await pilot.click("#start")
                await pilot.pause()
                assert isinstance(app.screen, ImportScreen)

        run(go)


# --------------------------------------------------------------------------
# Import screen
# --------------------------------------------------------------------------


class TestImportScreen:
    def test_each_phase_gets_its_own_progress_bar(self, config, extractor, tmp_path):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                rows = list(app.screen.query(StepRow))
                keys = [r.step.key for r in rows]
                assert keys == ["scan", "metadata", "dates", "pairs", "destinations"]
                for row in rows:
                    assert row.query_one(ProgressBar) is not None

        run(go)

    def test_completed_phases_stay_on_screen_as_a_log(self, config, extractor, tmp_path):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                rows = list(app.screen.query(StepRow))
                # Every planning phase is finished and none was discarded.
                assert all(r.step.done for r in rows)
                assert all(r.step.note for r in rows)

        run(go)

    def test_the_log_survives_the_confirmation_step(self, config, extractor, tmp_path):
        """The whole point of one screen: planning stays visible during the copy."""
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                before = [r.step.key for r in app.screen.query(StepRow)]

                await pilot.click("#proceed")
                await settle(app, pilot)
                await wait_until(pilot, lambda: app.screen.report is not None, "the report")

                after = [r.step.key for r in app.screen.query(StepRow)]
                assert after == [*before, "import"]

        run(go)

    def test_summary_appears_before_anything_is_copied(self, config, extractor, tmp_path):
        make_file(config.source_path / "IMG_1.JPG")
        make_file(config.source_path / "undated.png")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                assert "Import summary" in text_of(app, "#summary")
                assert not any(config.photo_library.rglob("*.JPG"))
                assert "undated.png" in text_of(app, "#details")

        run(go)

    def test_full_copy_through_the_interface(self, config, extractor, tmp_path):
        make_file(config.source_path / "a/IMG_1.JPG", b"one")
        make_file(config.source_path / "b/20250827_105030.mp4", b"two")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                assert app.screen.plan.to_copy
                await pilot.click("#proceed")
                await settle(app, pilot)
                await wait_until(pilot, lambda: app.screen.report is not None, "the report")
                assert "Import complete" in text_of(app, "#summary")

        run(go)

        assert (config.photo_library / "2025/08/27/IMG_1.JPG").read_bytes() == b"one"
        assert (config.video_library / "2025/08/27/20250827_105030.mp4").read_bytes() == b"two"
        assert (config.source_path / "a/IMG_1.JPG").exists(), "copy mode must not remove sources"

    def test_full_move_through_the_interface(self, config, extractor, tmp_path):
        source = make_file(config.source_path / "a/IMG_1.JPG", b"one")
        extractor.dates["IMG_1.JPG"] = DT
        config.import_action = ImportAction.MOVE

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                summary = text_of(app, "#summary")
                assert "no longer be present in the import directory" in summary
                assert "delet" not in summary.lower()
                await pilot.click("#proceed")
                await settle(app, pilot)
                await wait_until(pilot, lambda: app.screen.report is not None, "the report")
                assert "Moved" in text_of(app, "#summary")

        run(go)

        assert (config.photo_library / "2025/08/27/IMG_1.JPG").read_bytes() == b"one"
        assert not source.exists(), "move mode should have removed the source"

    def test_import_step_is_labelled_for_the_action(self, config, extractor, tmp_path):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT
        config.import_action = ImportAction.MOVE

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                await pilot.click("#proceed")
                await settle(app, pilot)
                await wait_until(pilot, lambda: app.screen.report is not None, "the report")
                row = next(r for r in app.screen.query(StepRow) if r.step.key == "import")
                assert row.step.label == "Moving files"

        run(go)

    def test_cancel_returns_to_the_menu_without_importing(self, config, extractor, tmp_path):
        make_file(config.source_path / "IMG_1.JPG")
        extractor.dates["IMG_1.JPG"] = DT

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                await reach_summary(app, pilot)
                await pilot.click("#cancel")
                await pilot.pause()
                assert isinstance(app.screen, MainScreen)

        run(go)

        assert not any(config.photo_library.rglob("*.JPG"))

    def test_invalid_configuration_never_reaches_the_import_screen(
        self, config, extractor, tmp_path
    ):
        config.photo_library = config.source_path / "inside"

        async def go():
            app = app_for(config, extractor, tmp_path)
            async with app.run_test() as pilot:
                await pilot.pause()
                app.screen.action_start_import()
                await pilot.pause()
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


def test_step_log_updates_rather_than_duplicating(config, extractor, tmp_path):
    from media_importer.planner import Step

    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.push_screen(ImportScreen())
            await settle(app, pilot)
            log = app.screen.query_one(StepLog)
            step = Step("x", "Doing a thing", total=10)
            log.upsert(step)
            await pilot.pause()
            step.completed = 5
            log.upsert(step)
            await pilot.pause()
            rows = [r for r in app.screen.query(StepRow) if r.step.key == "x"]
            assert len(rows) == 1
            assert rows[0].step.completed == 5

    run(go)


def test_no_move_dialogue_uses_the_word_delete(config, extractor, tmp_path):
    """Every move-related string states where files end up, not what is destroyed."""
    make_file(config.source_path / "IMG_1.JPG")
    extractor.dates["IMG_1.JPG"] = DT
    config.import_action = ImportAction.MOVE
    seen: list[str] = []

    async def go():
        app = app_for(config, extractor, tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            seen.append(text_of(app, "#notice"))
            seen.append(
                str(
                    next(r for r in app.screen.query(SettingRow) if r.button_id == "edit-action")
                    .query_one(".setting-value", Static)
                    .content
                )
            )

            # The copy/move chooser itself.
            await pilot.click("#edit-action")
            await pilot.pause()
            seen.append(str(app.screen.query_one(".hint", Static).content))
            seen.extend(str(b.label) for b in app.screen.query(Button))
            await pilot.click("#cancel")
            await pilot.pause()

            # Summary, then the final report.
            await reach_summary(app, pilot)
            seen.append(text_of(app, "#summary"))
            await pilot.click("#proceed")
            await settle(app, pilot)
            await wait_until(pilot, lambda: app.screen.report is not None, "the report")
            seen.append(text_of(app, "#summary"))

    run(go)

    offenders = [text for text in seen if "delet" in text.lower()]
    assert not offenders, f"alarmist wording still present: {offenders}"
    assert any("no longer be present in the import directory" in t for t in seen)
