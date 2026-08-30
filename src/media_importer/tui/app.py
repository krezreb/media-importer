"""Textual TUI.

Strictly a presentation layer.  It reads no metadata, parses no configuration
file, computes no destination path and copies no file -- it calls application
services and renders what they return.

Mouse and keyboard both work throughout: every control is a real button, so it
can be clicked as well as tabbed to.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import ClassVar

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, ProgressBar, Static

from .. import config as config_module
from ..config import Config
from ..errors import ConfigurationError, MediaImporterError
from ..importer import ImportCallbacks, execute
from ..metadata import ExternalToolExtractor
from ..models import (
    ClobberPreference,
    CollisionPolicy,
    ImportAction,
    ImportPlan,
    ImportReport,
    PlanItem,
)
from ..planner import Step, build_plan

log = logging.getLogger(__name__)

MAX_LISTED = 25
"""Cap on individually listed problem files, so a huge import stays readable."""


# --------------------------------------------------------------------------
# Modals
# --------------------------------------------------------------------------


class EditValueScreen(ModalScreen[str | None]):
    """Prompt for a single text value."""

    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, value: str, hint: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.value = value
        self.hint = hint

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            if self.hint:
                yield Static(self.hint, classes="hint")
            yield Input(value=self.value, id="value")
            with Horizontal(classes="dialog-buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    @on(Button.Pressed, "#save")
    @on(Input.Submitted, "#value")
    def _save(self) -> None:
        self.dismiss(self.query_one("#value", Input).value.strip())

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.dismiss(None)


class ChoiceScreen(ModalScreen[str | None]):
    """Pick one of a small set of named options."""

    BINDINGS: ClassVar = [("escape", "cancel", "Cancel")]

    def __init__(
        self, title: str, options: list[tuple[str, str]], current: str, note: str = ""
    ) -> None:
        super().__init__()
        self.title_text = title
        self.options = options
        self.current = current
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            if self.note:
                yield Static(self.note, classes="hint")
            for value, description in self.options:
                marker = "●" if value == self.current else "○"
                yield Button(f"{marker}  {value} - {description}", id=f"opt-{value}")
            yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        assert event.button.id is not None
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(event.button.id.removeprefix("opt-"))

    def action_cancel(self) -> None:
        self.dismiss(None)


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------


class SettingRow(Horizontal):
    """One setting: its name, its current value, and the button that changes it.

    Keeping the three together means there is exactly one place to look for a
    setting and exactly one place to click to change it.
    """

    def __init__(self, label: str, button_id: str) -> None:
        super().__init__(classes="setting-row")
        self.label_text = label
        self.button_id = button_id
        self._value = ""

    def compose(self) -> ComposeResult:
        yield Static(self.label_text, classes="setting-label")
        yield Static(self._value, classes="setting-value")
        yield Button("Change", id=self.button_id, classes="setting-button")

    def set_value(self, value: str) -> None:
        self._value = value
        with contextlib.suppress(NoMatches):  # not yet composed
            self.query_one(".setting-value", Static).update(value)


def _fmt(value: object) -> str:
    return str(value) if value else "[dim italic]not set[/dim italic]"


class MainScreen(Screen):
    BINDINGS: ClassVar = [("q", "quit", "Quit"), ("i", "start_import", "Import")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="main"):
            yield Static("Configuration", classes="section-title")
            yield SettingRow("Source directory", "edit-source")
            yield SettingRow("Photo library", "edit-photos")
            yield SettingRow("Video library", "edit-videos")
            yield SettingRow("Path scheme", "edit-scheme")
            yield SettingRow("Import action", "edit-action")
            yield SettingRow("On collision", "edit-collision")
            yield Static(id="notice", classes="notice")
            yield Static(id="config-path", classes="dim-note")
        with Horizontal(classes="actions"):
            yield Button("Start import process", variant="primary", id="start")
            yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_settings()

    def refresh_settings(self) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        rows = {row.button_id: row for row in self.query(SettingRow)}

        rows["edit-source"].set_value(_fmt(cfg.source_path))
        rows["edit-photos"].set_value(_fmt(cfg.photo_library))
        rows["edit-videos"].set_value(_fmt(cfg.video_library))
        rows["edit-scheme"].set_value(cfg.import_path)

        if cfg.import_action is ImportAction.MOVE:
            rows["edit-action"].set_value("move [dim]- files leave the import directory[/dim]")
        else:
            rows["edit-action"].set_value("copy [dim]- originals are kept in place[/dim]")

        policy = cfg.on_collision.value
        if cfg.on_collision is CollisionPolicy.CLOBBER:
            policy += f" [dim]- {cfg.clobber_prefers.value} wins[/dim]"
        rows["edit-collision"].set_value(policy)

        missing = [
            name
            for name, value in (
                ("source directory", cfg.source_path),
                ("photo library", cfg.photo_library),
                ("video library", cfg.video_library),
            )
            if not value
        ]
        notice = self.query_one("#notice", Static)
        if missing:
            notice.update(f"[yellow]Set the {', '.join(missing)} above before importing.[/yellow]")
        elif cfg.import_action is ImportAction.MOVE:
            notice.update(
                "[dim]Imported files will no longer be present in the import directory.[/dim]"
            )
        else:
            notice.update("")

        where = self.app.config_path or config_module.config_file()  # type: ignore[attr-defined]
        self.query_one("#config-path", Static).update(f"Config file: {where}")

    # -- editing ----------------------------------------------------------

    def _edit_path(self, title: str, attr: str, hint: str) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]

        def done(value: str | None) -> None:
            if value is None:
                return
            setattr(cfg, attr, Path(value).expanduser() if value else None)
            self.app.save_config()  # type: ignore[attr-defined]
            self.refresh_settings()

        self.app.push_screen(EditValueScreen(title, str(getattr(cfg, attr) or ""), hint), done)

    @on(Button.Pressed, "#edit-source")
    def _source(self) -> None:
        self._edit_path(
            "Source directory",
            "source_path",
            "Scanned recursively. Defaults to the directory you launched from.",
        )

    @on(Button.Pressed, "#edit-photos")
    def _photos(self) -> None:
        self._edit_path("Photo library", "photo_library", "Created if it does not exist.")

    @on(Button.Pressed, "#edit-videos")
    def _videos(self) -> None:
        self._edit_path("Video library", "video_library", "Created if it does not exist.")

    @on(Button.Pressed, "#edit-scheme")
    def _scheme(self) -> None:
        from ..path_scheme import TOKEN_HELP
        from ..path_scheme import validate as validate_scheme

        cfg: Config = self.app.config  # type: ignore[attr-defined]

        def done(value: str | None) -> None:
            if value is None:
                return
            try:
                validate_scheme(value)
            except ConfigurationError as exc:
                self.notify(str(exc), severity="error", timeout=10)
                return
            cfg.import_path = value
            self.app.save_config()  # type: ignore[attr-defined]
            self.refresh_settings()

        self.app.push_screen(
            EditValueScreen(
                "Destination path scheme",
                cfg.import_path,
                f"Tokens: {TOKEN_HELP}\nExamples: YYYY/MM/DD, YYYY-MM-DD, YYYY/YYYY-MM-DD",
            ),
            done,
        )

    @on(Button.Pressed, "#edit-action")
    def _action(self) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]

        def chosen(value: str | None) -> None:
            if value is None:
                return
            cfg.import_action = ImportAction(value)
            self.app.save_config()  # type: ignore[attr-defined]
            self.refresh_settings()

        self.app.push_screen(
            ChoiceScreen(
                "What should happen to files after they are imported?",
                [
                    ("copy", "originals stay in the import directory"),
                    ("move", "imported files are no longer present in the import directory"),
                ],
                cfg.import_action.value,
                note=(
                    "With 'move', a file leaves the import directory only once it is safely "
                    "in the library. Anything skipped, undated, colliding or already present "
                    "stays where it is."
                ),
            ),
            chosen,
        )

    @on(Button.Pressed, "#edit-collision")
    def _collision(self) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]

        def chose_policy(value: str | None) -> None:
            if value is None:
                return
            cfg.on_collision = CollisionPolicy(value)
            if cfg.on_collision is CollisionPolicy.CLOBBER:
                self.app.push_screen(
                    ChoiceScreen(
                        "Which file wins?",
                        [
                            ("newest", "later capture date replaces the older file"),
                            ("oldest", "earlier capture date is kept"),
                        ],
                        cfg.clobber_prefers.value,
                    ),
                    chose_preference,
                )
                return
            self.app.save_config()  # type: ignore[attr-defined]
            self.refresh_settings()

        def chose_preference(value: str | None) -> None:
            if value is not None:
                cfg.clobber_prefers = ClobberPreference(value)
            self.app.save_config()  # type: ignore[attr-defined]
            self.refresh_settings()

        self.app.push_screen(
            ChoiceScreen(
                "When a destination file already exists and differs",
                [
                    ("skip", "do not import; nothing is ever destroyed"),
                    ("clobber", "one file replaces the other"),
                    ("rename", "keep both; incoming gets -1, -2, ..."),
                ],
                cfg.on_collision.value,
            ),
            chose_policy,
        )

    # -- actions ----------------------------------------------------------

    @on(Button.Pressed, "#start")
    def action_start_import(self) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        try:
            config_module.validate_for_import(cfg)
        except ConfigurationError as exc:
            self.notify(str(exc), severity="error", timeout=12)
            return
        self.app.push_screen(ImportScreen())

    @on(Button.Pressed, "#quit")
    def _quit(self) -> None:
        self.app.exit()


# --------------------------------------------------------------------------
# Step log
# --------------------------------------------------------------------------


class StepRow(Vertical):
    """A single named phase with its own progress bar.

    Completed rows stay on screen rather than being replaced, so the whole run
    reads as a log of what happened.
    """

    def __init__(self, step: Step) -> None:
        super().__init__(classes="step-row")
        self.step = step

    def compose(self) -> ComposeResult:
        yield Static(self._label(), classes="step-label")
        yield ProgressBar(
            total=self.step.total,
            show_eta=False,
            show_percentage=self.step.total is not None,
        )

    def on_mount(self) -> None:
        self._apply()

    def update_step(self, step: Step) -> None:
        self.step = step
        self._apply()

    def _label(self) -> str:
        mark = "[green]✔[/green]" if self.step.done else "[cyan]▶[/cyan]"
        text = f"{mark} {self.step.label}"
        if self.step.note:
            text += f"  [dim]{self.step.note}[/dim]"
        elif self.step.total:
            text += f"  [dim]{self.step.completed:,} / {self.step.total:,}[/dim]"
        return text

    def _apply(self) -> None:
        try:
            self.query_one(".step-label", Static).update(self._label())
            bar = self.query_one(ProgressBar)
        except NoMatches:  # pragma: no cover - before compose has run
            return
        if self.step.total is not None:
            bar.update(total=self.step.total, progress=self.step.completed)
        elif self.step.done:
            # An indeterminate bar has to be given a size to settle at 100%.
            bar.update(total=1, progress=1)
        self.set_class(self.step.done, "step-done")


class StepLog(Vertical):
    """An append-only list of `StepRow`s, keyed so updates land on the right one."""

    def __init__(self) -> None:
        super().__init__(id="steplog")
        self._rows: dict[str, StepRow] = {}

    def upsert(self, step: Step) -> None:
        row = self._rows.get(step.key)
        if row is None:
            row = StepRow(step)
            self._rows[step.key] = row
            self.mount(row)
        else:
            row.update_step(step)


# --------------------------------------------------------------------------
# Import
# --------------------------------------------------------------------------


class ImportScreen(Screen):
    """Planning, confirmation, execution and the final report, in one place.

    Keeping it on a single screen is what lets the step log survive the
    confirmation step: every phase stays visible above whatever comes next.
    """

    BINDINGS: ClassVar = [("escape", "back", "Back")]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="main"):
            yield Static("Import", classes="section-title")
            yield StepLog()
            yield Static(id="summary")
            yield Static(id="details")
        with Horizontal(classes="actions", id="confirm-row"):
            yield Button("Proceed with import", variant="primary", id="proceed")
            yield Button("Cancel", id="cancel")
        with Horizontal(classes="actions", id="done-row"):
            yield Button("Back to menu", variant="primary", id="back")
            yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self.plan: ImportPlan | None = None
        self.report: ImportReport | None = None
        self._stop = False
        self._copy_step: Step | None = None
        self.query_one("#confirm-row").display = False
        self.query_one("#done-row").display = False
        self.build()

    # -- planning ---------------------------------------------------------

    @work(thread=True, exclusive=True)
    def build(self) -> None:
        app = self.app
        try:
            plan = build_plan(
                app.config,  # type: ignore[attr-defined]
                app.extractor,  # type: ignore[attr-defined]
                on_progress=lambda step: app.call_from_thread(self._step, step),
            )
        except MediaImporterError as exc:
            app.call_from_thread(self._failed, str(exc))
            return
        except Exception as exc:
            log.exception("Planning failed")
            app.call_from_thread(self._failed, str(exc))
            return
        app.call_from_thread(self._planned, plan)

    def _step(self, step: Step) -> None:
        self.query_one(StepLog).upsert(step)
        # Follow the newest phase, so a long run does not scroll its own
        # progress out of sight.
        self.query_one("#main", VerticalScroll).scroll_end(animate=False)

    def _reveal_summary(self) -> None:
        """Bring the summary into view once there is something to read or act on."""
        self.query_one("#summary", Static).scroll_visible(animate=False, top=True)

    def _failed(self, message: str) -> None:
        self.query_one("#summary", Static).update(f"[red]Import cannot start[/red]\n\n{message}")
        self.query_one("#done-row").display = True
        self.call_after_refresh(self._reveal_summary)

    def _planned(self, plan: ImportPlan) -> None:
        self.plan = plan
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        verb = "move" if cfg.import_action is ImportAction.MOVE else "import"

        lines = [
            "",
            "[bold]Import summary[/bold]",
            "",
            f"  Source                 {cfg.source_path}",
            f"  Discovered media       {len(plan.items):,}",
            f"    Photos               {len(plan.photos):,}",
            f"    Videos               {len(plan.videos):,}",
            "",
            "  [bold]Not importing[/bold]",
            f"    RAW + JPEG pairs     {len(plan.paired_jpegs):,}",
            f"    Already imported     {len(plan.already_imported):,}",
            f"    Undated              {len(plan.undated):,}",
            f"    Collisions           {len(plan.collisions):,}",
            f"    Errors               {len(plan.errors):,}",
            "",
            f"  [bold]Files to {verb}{' ' * (16 - len(verb))}{len(plan.to_copy):,}[/bold]",
        ]
        if plan.ignored:
            lines.append(
                f"\n[dim]  Ignored: {len(plan.unsupported):,} unsupported, "
                f"{len(plan.symlinks):,} symlinks[/dim]"
            )
        if cfg.import_action is ImportAction.MOVE and plan.to_copy:
            lines.append(
                f"  [dim]{len(plan.to_copy):,} files will no longer be present in the "
                f"import directory afterwards.[/dim]"
            )
        self.query_one("#summary", Static).update("\n".join(lines))

        details: list[str] = []
        details += _list_section("Undated (will not be imported)", plan.undated)
        details += _list_section("Collisions", plan.collisions, show_collision=True)
        details += _list_section("Errors", plan.errors)
        self.query_one("#details", Static).update("\n".join(details))

        self.query_one("#confirm-row").display = True
        self.call_after_refresh(self._reveal_summary)
        proceed = self.query_one("#proceed", Button)
        proceed.label = f"Proceed with {verb}"
        proceed.disabled = not plan.to_copy
        (self.query_one("#cancel", Button) if not plan.to_copy else proceed).focus()

    # -- execution --------------------------------------------------------

    @on(Button.Pressed, "#proceed")
    def _proceed(self) -> None:
        if self.plan is None or not self.plan.to_copy:
            return
        self.query_one("#confirm-row").display = False
        self.query_one("#details", Static).update("")
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        self._copy_step = Step(
            "import",
            f"{cfg.import_action.verb} files",
            total=len(self.plan.to_copy),
        )
        self._step(self._copy_step)
        self.run_import()

    @work(thread=True, exclusive=True)
    def run_import(self) -> None:
        app = self.app
        assert self.plan is not None
        callbacks = ImportCallbacks(
            on_file_started=lambda item, i, total: app.call_from_thread(self._file, item, i),
            on_file_failed=lambda item, error, i, total: app.call_from_thread(
                self._file_failed, item, error
            ),
        )
        report = execute(
            self.plan,
            callbacks,
            should_stop=lambda: self._stop,
            action=app.config.import_action,  # type: ignore[attr-defined]
        )
        app.call_from_thread(self._finished, report)

    def _file(self, item: PlanItem, index: int) -> None:
        assert self._copy_step is not None
        self._copy_step.completed = index
        self._copy_step.note = item.filename
        self._step(self._copy_step)

    def _file_failed(self, item: PlanItem, error: str) -> None:
        self.app.notify(f"{item.filename}: {error}", severity="error", timeout=8)

    def _finished(self, report: ImportReport) -> None:
        self.report = report
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        if self._copy_step is not None:
            self._copy_step.note = f"{report.copied_count:,} {cfg.import_action.past}" + (
                f", {report.failed_count:,} failed" if report.failed else ""
            )
            self._copy_step.done = True
            self._step(self._copy_step)

        plan = report.plan
        lines = [
            "",
            "[bold]Import complete[/bold]",
            "",
            f"  {cfg.import_action.past.capitalize():<20} {report.copied_count:,}",
            f"  Failed               {report.failed_count:,}",
        ]
        if plan is not None:
            lines += [
                f"  Already imported     {len(plan.already_imported):,}",
                f"  RAW + JPEG skipped   {len(plan.paired_jpegs):,}",
                f"  Undated              {len(plan.undated):,}",
                f"  Collisions           {len(plan.collisions):,}",
                f"  Ignored symlinks     {len(plan.symlinks):,}",
            ]
        if cfg.import_action is ImportAction.MOVE:
            lines.append(
                "\n[dim]Imported files are no longer present in the import directory. "
                "Skipped, undated and colliding files were left in place.[/dim]"
            )
        else:
            lines.append("\n[dim]Source files were not modified.[/dim]")
        self.query_one("#summary", Static).update("\n".join(lines))

        details: list[str] = []
        if report.failed:
            details += ["", "[bold]Failures[/bold]"]
            for item, error in report.failed[:MAX_LISTED]:
                details.append(f"  {item.source_path}\n      {error}")
            if len(report.failed) > MAX_LISTED:
                details.append(f"  [dim]... and {len(report.failed) - MAX_LISTED} more[/dim]")
        if plan is not None:
            details += _list_section("Undated (not imported)", plan.undated)
            details += _list_section("Collisions", plan.collisions, show_collision=True)
        self.query_one("#details", Static).update("\n".join(details))

        self.query_one("#done-row").display = True
        self.call_after_refresh(self._reveal_summary)
        self.query_one("#back", Button).focus()

    # -- navigation -------------------------------------------------------

    @on(Button.Pressed, "#cancel")
    @on(Button.Pressed, "#back")
    def action_back(self) -> None:
        self._stop = True
        self.app.pop_screen()
        main = self.app.screen
        if isinstance(main, MainScreen):
            main.refresh_settings()

    @on(Button.Pressed, "#quit")
    def _quit(self) -> None:
        self.app.exit()


def _list_section(title: str, items: list[PlanItem], *, show_collision: bool = False) -> list[str]:
    if not items:
        return []
    out = ["", f"[bold]{title}[/bold] ({len(items)})"]
    for item in items[:MAX_LISTED]:
        line = f"  {item.source_path}"
        if show_collision and item.collided_with:
            line += f"\n      collides with {item.collided_with}"
        elif item.detail:
            line += f"\n      {item.detail}"
        out.append(line)
    if len(items) > MAX_LISTED:
        out.append(f"  [dim]... and {len(items) - MAX_LISTED} more[/dim]")
    return out


# --------------------------------------------------------------------------


class MediaImporterApp(App):
    TITLE = "media-importer"
    SUB_TITLE = "photo and video importer"

    CSS = """
    Screen { align: center top; }
    #main { padding: 1 2; width: 100%; height: 1fr; }
    .section-title { text-style: bold; padding-bottom: 1; }
    .dim-note { color: $text-muted; padding-top: 1; }

    /* One row per setting so the whole configuration fits an 80x24 terminal
       without scrolling. */
    .setting-row { height: 1; width: 100%; margin-bottom: 1; }
    .setting-label { width: 20; height: 1; }
    .setting-value { width: 1fr; height: 1; }
    .setting-button { width: 10; min-width: 10; height: 1; border: none; }

    .notice { padding: 1 0 0 0; }

    /* Docked, so the primary action is always reachable no matter how long
       the content above grows. */
    .actions {
        dock: bottom; height: auto; width: 100%;
        padding: 1 2; background: $surface;
    }
    .actions Button { margin-right: 2; }

    .step-row { height: auto; padding-bottom: 1; }
    .step-label { height: 1; }
    .step-row ProgressBar { height: 1; }
    .step-done ProgressBar { opacity: 0.5; }
    #steplog { height: auto; }

    #dialog {
        width: 78; height: auto; padding: 1 2;
        border: thick $primary; background: $surface;
    }
    #dialog Button { margin-top: 1; width: 100%; }
    .dialog-title { text-style: bold; padding-bottom: 1; }
    .dialog-buttons { height: auto; }
    .hint { color: $text-muted; padding-bottom: 1; }
    #summary, #details { height: auto; }
    """

    def __init__(
        self,
        config: Config,
        config_path: Path | None = None,
        extractor: object | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.config_path = config_path
        # Injectable so the TUI can be driven in tests without the external tools.
        self.extractor = extractor or ExternalToolExtractor()

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def save_config(self) -> None:
        try:
            config_module.save(self.config, self.config_path)
        except ConfigurationError as exc:
            self.notify(str(exc), severity="error", timeout=10)
