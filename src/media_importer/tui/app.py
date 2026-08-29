"""Textual TUI.

Strictly a presentation layer.  It reads no metadata, parses no configuration
file, computes no destination path and copies no file -- it calls application
services and renders what they return.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, ProgressBar, Static

from .. import config as config_module
from ..config import Config
from ..errors import ConfigurationError, MediaImporterError
from ..importer import ImportCallbacks, execute
from ..metadata import ExternalToolExtractor
from ..models import ClobberPreference, CollisionPolicy, ImportPlan, ImportReport, PlanItem
from ..planner import build_plan

log = logging.getLogger(__name__)

MAX_LISTED = 25
"""Cap on individually listed problem files, so a huge import stays readable."""


def _fmt(value: object) -> str:
    return str(value) if value else "[dim]not set[/dim]"


class EditValueScreen(ModalScreen[str | None]):
    """Prompt for a single text value."""

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
            with Horizontal(classes="buttons"):
                yield Button("Save", variant="primary", id="save")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#value", Input).focus()

    @on(Button.Pressed, "#save")
    @on(Input.Submitted, "#value")
    def _save(self) -> None:
        self.dismiss(self.query_one("#value", Input).value.strip())

    @on(Button.Pressed, "#cancel")
    def _cancel(self) -> None:
        self.dismiss(None)


class ChoiceScreen(ModalScreen[str | None]):
    """Pick one of a small set of named options."""

    def __init__(self, title: str, options: list[tuple[str, str]], current: str) -> None:
        super().__init__()
        self.title_text = title
        self.options = options
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self.title_text, classes="dialog-title")
            for value, description in self.options:
                marker = "> " if value == self.current else "  "
                yield Button(f"{marker}{value} - {description}", id=f"opt-{value}")
            yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def _pressed(self, event: Button.Pressed) -> None:
        assert event.button.id is not None
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(event.button.id.removeprefix("opt-"))


class MainScreen(Screen):
    BINDINGS: ClassVar = [("q", "quit", "Quit"), ("i", "start_import", "Import")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="main"):
            yield Static(id="settings")
            yield Static(id="notice", classes="notice")
            with Vertical(classes="buttons-column"):
                yield Button("Source directory", id="edit-source")
                yield Button("Photo library", id="edit-photos")
                yield Button("Video library", id="edit-videos")
                yield Button("Destination path scheme", id="edit-scheme")
                yield Button("Collision policy", id="edit-collision")
                yield Button("Start import", variant="primary", id="start")
                yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_settings()

    def refresh_settings(self) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        where = self.app.config_path or config_module.config_file()  # type: ignore[attr-defined]
        policy = cfg.on_collision.value
        if cfg.on_collision is CollisionPolicy.CLOBBER:
            policy += f" ({cfg.clobber_prefers.value} wins)"
        self.query_one("#settings", Static).update(
            "\n".join(
                [
                    "[bold]Current configuration[/bold]",
                    "",
                    f"  Source directory    {_fmt(cfg.source_path)}",
                    f"  Photo library       {_fmt(cfg.photo_library)}",
                    f"  Video library       {_fmt(cfg.video_library)}",
                    f"  Path scheme         {cfg.import_path}",
                    f"  On collision        {policy}",
                    "",
                    f"[dim]Config file: {where}[/dim]",
                ]
            )
        )
        self.query_one("#notice", Static).update(
            ""
            if cfg.is_complete
            else "[yellow]Set all three directories before importing.[/yellow]"
        )

    # -- settings ---------------------------------------------------------

    def _edit_path(self, title: str, attr: str, hint: str) -> None:
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        current = getattr(cfg, attr)

        def done(value: str | None) -> None:
            if value is None:
                return
            setattr(cfg, attr, Path(value).expanduser() if value else None)
            self.app.save_config()  # type: ignore[attr-defined]
            self.refresh_settings()

        self.app.push_screen(EditValueScreen(title, str(current or ""), hint), done)

    @on(Button.Pressed, "#edit-source")
    def _source(self) -> None:
        self._edit_path("Source directory", "source_path", "Scanned recursively. Never modified.")

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
        self.app.push_screen(PreviewScreen())

    @on(Button.Pressed, "#quit")
    def _quit(self) -> None:
        self.app.exit()


class PreviewScreen(Screen):
    """Builds the plan, then shows it for confirmation. Nothing is copied here."""

    BINDINGS: ClassVar = [("escape", "cancel", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="main"):
            yield Static("Scanning...", id="summary")
            yield Static(id="details")
            with Horizontal(classes="buttons", id="confirm-row"):
                yield Button("Proceed with import", variant="primary", id="proceed")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.plan: ImportPlan | None = None
        self.query_one("#confirm-row").display = False
        self.build()

    @work(thread=True, exclusive=True)
    def build(self) -> None:
        app = self.app
        try:
            plan = build_plan(
                app.config,  # type: ignore[attr-defined]
                app.extractor,  # type: ignore[attr-defined]
                on_progress=lambda msg: app.call_from_thread(self._progress, msg),
            )
        except MediaImporterError as exc:
            app.call_from_thread(self._failed, str(exc))
            return
        except Exception as exc:
            log.exception("Planning failed")
            app.call_from_thread(self._failed, str(exc))
            return
        app.call_from_thread(self._ready, plan)

    def _progress(self, message: str) -> None:
        self.query_one("#summary", Static).update(message)

    def _failed(self, message: str) -> None:
        self.query_one("#summary", Static).update(f"[red]Import cannot start[/red]\n\n{message}")
        row = self.query_one("#confirm-row")
        row.display = True
        self.query_one("#proceed", Button).display = False

    def _ready(self, plan: ImportPlan) -> None:
        self.plan = plan
        cfg: Config = self.app.config  # type: ignore[attr-defined]
        discovered = len(plan.items)

        lines = [
            "[bold]Import summary[/bold]",
            "",
            f"  Source                 {cfg.source_path}",
            f"  Discovered media       {discovered:,}",
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
            f"  [bold]Files to import      {len(plan.to_copy):,}[/bold]",
        ]
        if plan.ignored:
            lines += [
                "",
                f"[dim]  Ignored: {len(plan.unsupported):,} unsupported, "
                f"{len(plan.symlinks):,} symlinks[/dim]",
            ]
        self.query_one("#summary", Static).update("\n".join(lines))

        details: list[str] = []
        details += _list_section("Undated (will not be imported)", plan.undated)
        details += _list_section("Collisions", plan.collisions, show_collision=True)
        details += _list_section("Errors", plan.errors)
        self.query_one("#details", Static).update("\n".join(details))

        self.query_one("#confirm-row").display = True
        self.query_one("#proceed", Button).disabled = not plan.to_copy
        self.query_one("#proceed", Button).focus()

    @on(Button.Pressed, "#proceed")
    def _proceed(self) -> None:
        if self.plan is not None:
            self.app.switch_screen(ProgressScreen(self.plan))

    @on(Button.Pressed, "#cancel")
    def action_cancel(self) -> None:
        self.app.pop_screen()


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


class ProgressScreen(Screen):
    BINDINGS: ClassVar = [("escape", "stop", "Stop")]

    def __init__(self, plan: ImportPlan) -> None:
        super().__init__()
        self.plan = plan
        self._stop = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main"):
            yield Static("Importing...", id="status")
            yield ProgressBar(total=max(len(self.plan.to_copy), 1), id="bar")
            yield Static(id="current")
            yield Static(id="counts")
            yield Button("Stop", id="stop")
        yield Footer()

    def on_mount(self) -> None:
        self.copied = 0
        self.failed = 0
        self.run_import()

    @work(thread=True, exclusive=True)
    def run_import(self) -> None:
        app = self.app
        callbacks = ImportCallbacks(
            on_file_started=lambda item, i, total: app.call_from_thread(
                self._started, item, i, total
            ),
            on_file_completed=lambda item, i, total: app.call_from_thread(self._completed),
            on_file_failed=lambda item, error, i, total: app.call_from_thread(
                self._failed, item, error
            ),
        )
        report = execute(self.plan, callbacks, should_stop=lambda: self._stop)
        app.call_from_thread(self._done, report)

    def _started(self, item: PlanItem, index: int, total: int) -> None:
        self.query_one("#status", Static).update(f"Importing {index:,} of {total:,}")
        self.query_one("#current", Static).update(
            f"  {item.source_path}\n  [dim]-> {item.destination_path}[/dim]"
        )

    def _tick(self) -> None:
        self.query_one("#bar", ProgressBar).advance(1)
        self.query_one("#counts", Static).update(
            f"  copied {self.copied:,}    failed {self.failed:,}"
        )

    def _completed(self) -> None:
        self.copied += 1
        self._tick()

    def _failed(self, item: PlanItem, error: str) -> None:
        self.failed += 1
        self._tick()
        self.app.notify(f"{item.filename}: {error}", severity="error", timeout=8)

    def _done(self, report: ImportReport) -> None:
        self.app.switch_screen(ReportScreen(report))

    @on(Button.Pressed, "#stop")
    def action_stop(self) -> None:
        self._stop = True
        self.query_one("#status", Static).update("Stopping after the current file...")


class ReportScreen(Screen):
    BINDINGS: ClassVar = [("escape", "back", "Back"), ("q", "quit", "Quit")]

    def __init__(self, report: ImportReport) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="main"):
            yield Static(id="report")
            with Horizontal(classes="buttons"):
                yield Button("Back to menu", variant="primary", id="back")
                yield Button("Quit", id="quit")
        yield Footer()

    def on_mount(self) -> None:
        plan = self.report.plan
        lines = [
            "[bold]Import complete[/bold]",
            "",
            f"  Imported             {self.report.copied_count:,}",
            f"  Failed               {self.report.failed_count:,}",
        ]
        if plan is not None:
            lines += [
                f"  Already imported     {len(plan.already_imported):,}",
                f"  RAW + JPEG skipped   {len(plan.paired_jpegs):,}",
                f"  Undated              {len(plan.undated):,}",
                f"  Collisions           {len(plan.collisions):,}",
                f"  Ignored symlinks     {len(plan.symlinks):,}",
            ]
        lines.append("")
        lines.append("[dim]Source files were not modified.[/dim]")

        if self.report.failed:
            lines += ["", "[bold]Failures[/bold]"]
            for item, error in self.report.failed[:MAX_LISTED]:
                lines.append(f"  {item.source_path}\n      {error}")
            if len(self.report.failed) > MAX_LISTED:
                lines.append(f"  [dim]... and {len(self.report.failed) - MAX_LISTED} more[/dim]")

        if plan is not None:
            lines += _list_section("Undated (not imported)", plan.undated)
            lines += _list_section("Collisions", plan.collisions, show_collision=True)

        self.query_one("#report", Static).update("\n".join(lines))
        self.query_one("#back", Button).focus()

    @on(Button.Pressed, "#back")
    def action_back(self) -> None:
        self.app.pop_screen()
        main = self.app.screen
        if isinstance(main, MainScreen):
            main.refresh_settings()

    @on(Button.Pressed, "#quit")
    def action_quit(self) -> None:
        self.app.exit()


class MediaImporterApp(App):
    TITLE = "media-importer"
    SUB_TITLE = "photo and video importer"

    CSS = """
    Screen { align: center top; }
    #main { padding: 1 2; width: 100%; height: 1fr; }
    #settings { padding: 0 0 1 0; }
    .notice { padding: 0 0 1 0; }
    .buttons-column { width: 46; height: auto; }
    .buttons-column Button { width: 100%; height: 3; }
    .buttons { height: auto; padding-top: 1; }
    .buttons Button { margin-right: 2; }
    #dialog {
        width: 78; height: auto; padding: 1 2;
        border: thick $primary; background: $surface;
    }
    #dialog Button { margin-top: 1; width: 100%; }
    .dialog-title { text-style: bold; padding-bottom: 1; }
    .hint { color: $text-muted; padding-bottom: 1; }
    #details, #report { padding-top: 1; }
    ProgressBar { padding: 1 0; }
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
