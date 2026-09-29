"""The interactive wizard: account → competition → modes → run → done."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.markup import escape
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Checkbox,
    Collapsible,
    Footer,
    Header,
    Input,
    Label,
    Markdown,
    RadioButton,
    RadioSet,
    Static,
)

from kaggle_context import __version__
from kaggle_context.core.cache import get_bundle
from kaggle_context.core.client import (
    KaggleClient,
    KaggleError,
    credentials_present,
    save_access_token,
)
from kaggle_context.core.fetch import FetchOptions, meta_from_api
from kaggle_context.core.models import Bundle, CompetitionMeta
from kaggle_context.core.slug import competition_url, parse_competition
from kaggle_context.exporters.mcp_register import claude_desktop_config_path
from kaggle_context.pipeline import ExportPlan, ExportResult, run_exports
from kaggle_context.render.facts import format_date

SECTION_LABELS = {
    "overview": "Overview & pages",
    "rules": "Rules",
    "data": "Data files",
    "discussions": "Discussions",
    "code": "Top notebooks",
    "leaderboard": "Leaderboard",
}
ICONS = {"wait": "[dim]○[/]", "start": "[yellow]◌[/]", "progress": "[yellow]◌[/]", "done": "[green]✓[/]",
         "error": "[red]✗[/]", "skip": "[dim]–[/]"}  # fmt: skip


@dataclass
class Wizard:
    """Everything the screens collect along the way."""

    initial: str | None = None
    username: str | None = None
    slug: str = ""
    meta: CompetitionMeta | None = None
    entered: bool | None = None
    plan: ExportPlan = field(default_factory=ExportPlan)
    options: FetchOptions = field(default_factory=FetchOptions)
    refresh: bool = False
    bundle: Bundle | None = None
    result: ExportResult | None = None


# -- step 1: account ------------------------------------------------------------------------


class AuthScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="step"):
            yield Static("Connect your Kaggle account", classes="title")
            yield Static("Checking for Kaggle credentials…", id="auth-status")
            with Vertical(id="login", classes="hidden"):
                yield Static(
                    "kaggle-context uses the official Kaggle API with [b]your[/] account. "
                    "Nothing leaves your machine except calls to Kaggle.",
                    classes="muted",
                )
                yield Button("Log in with browser", id="browser", variant="primary")
                yield Static(
                    "…or paste an API token from https://www.kaggle.com/settings/api",
                    classes="muted",
                )
                yield Input(placeholder="API token", password=True, id="token")
                yield Button("Save token", id="save-token")
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = "Step 1 of 4 · Account"
        self.check()

    @work(thread=True, exclusive=True)
    def check(self) -> None:
        app: KaggleContextApp = self.app  # type: ignore[assignment]
        if not app.skip_credential_file_check and not credentials_present():
            app.call_from_thread(self.show_login, "No Kaggle credentials found on this machine.")
            return
        try:
            user = app.client.whoami()
        except KaggleError as exc:
            app.call_from_thread(self.show_login, str(exc))
            return
        app.call_from_thread(self.signed_in, user)

    def signed_in(self, user: str | None) -> None:
        self.app.wizard.username = user  # type: ignore[attr-defined]
        self.app.switch_screen(CompetitionScreen())

    def show_login(self, reason: str) -> None:
        self.query_one("#auth-status", Static).update(f"[yellow]{escape(reason)}[/]")
        self.query_one("#login").remove_class("hidden")
        self.query_one("#browser", Button).focus()

    @on(Button.Pressed, "#browser")
    def browser_login(self) -> None:
        app: KaggleContextApp = self.app  # type: ignore[assignment]
        with app.suspend():
            print(
                "\nOpening Kaggle in your browser. Finish the login there, then come back here.\n"
            )
            try:
                app.client.login_with_browser()
            except (Exception, SystemExit) as exc:  # the SDK exits on some failures
                print(f"Login did not complete: {exc}")
        app.reset_client()
        self.query_one("#auth-status", Static).update("Checking…")
        self.check()

    @on(Button.Pressed, "#save-token")
    @on(Input.Submitted, "#token")
    def save_token(self) -> None:
        token = self.query_one("#token", Input).value
        try:
            save_access_token(token)
        except ValueError as exc:
            self.query_one("#auth-status", Static).update(f"[red]{escape(str(exc))}[/]")
            return
        self.app.reset_client()  # type: ignore[attr-defined]
        self.query_one("#auth-status", Static).update("Token saved. Checking…")
        self.check()


# -- step 2: competition --------------------------------------------------------------------


class CompetitionScreen(Screen[None]):
    BINDINGS = [Binding("escape", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="step"):
            yield Static("Which competition?", classes="title")
            yield Static("", id="who", classes="muted")
            yield Input(
                placeholder="https://www.kaggle.com/competitions/…",
                id="url",
                value=self.app.wizard.initial or "",  # type: ignore[attr-defined]
            )
            yield Static("", id="url-error", classes="error")
            yield Static("", id="card", classes="card hidden")
            with Horizontal(classes="buttons"):
                yield Button("Look up", id="lookup", variant="primary")
                yield Button("Continue", id="continue", variant="success", disabled=True)
        yield Footer()

    def on_mount(self) -> None:
        wiz: Wizard = self.app.wizard  # type: ignore[attr-defined]
        self.app.sub_title = "Step 2 of 4 · Competition"
        if wiz.username:
            self.query_one("#who", Static).update(
                f"Signed in to Kaggle as [b]{escape(wiz.username)}[/]"
            )
        self.query_one("#url", Input).focus()
        if wiz.initial:
            wiz.initial = None
            self.lookup()

    @on(Input.Submitted, "#url")
    @on(Button.Pressed, "#lookup")
    def lookup(self) -> None:
        error = self.query_one("#url-error", Static)
        try:
            slug = parse_competition(self.query_one("#url", Input).value)
        except ValueError as exc:
            error.update(escape(str(exc)))
            return
        error.update("")
        self.query_one("#continue", Button).disabled = True
        card = self.query_one("#card", Static)
        card.remove_class("hidden")
        card.update(f"Looking up [b]{slug}[/]…")
        self.fetch_meta(slug)

    @work(thread=True, exclusive=True)
    def fetch_meta(self, slug: str) -> None:
        app: KaggleContextApp = self.app  # type: ignore[assignment]
        try:
            comp = app.client.competition(slug)
            if comp is None:
                app.client.pages(slug)  # raises NotFoundError for unknown slugs
                meta = CompetitionMeta(slug=slug, title=slug, url=competition_url(slug))
            else:
                meta = meta_from_api(slug, comp)
            entered = _safe(lambda: app.client.has_entered(slug))
        except KaggleError as exc:
            app.call_from_thread(self.lookup_failed, slug, str(exc))
            return
        app.call_from_thread(self.show_card, meta, entered)

    def lookup_failed(self, slug: str, message: str) -> None:
        self.query_one("#card", Static).add_class("hidden")
        self.query_one("#url-error", Static).update(
            f"Couldn't find '{escape(slug)}': {escape(message)}"
        )

    def show_card(self, meta: CompetitionMeta, entered: bool | None) -> None:
        wiz: Wizard = self.app.wizard  # type: ignore[attr-defined]
        wiz.slug, wiz.meta, wiz.entered = meta.slug, meta, entered
        lines = [f"[b]{escape(meta.title)}[/]"]
        if meta.subtitle:
            lines.append(f"[i]{escape(meta.subtitle)}[/]")
        facts = [
            ("Metric", meta.evaluation_metric),
            ("Deadline", format_date(meta.deadline)),
            ("Teams", f"{meta.team_count:,}" if meta.team_count else ""),
            ("Prize", meta.reward),
            (
                "Type",
                "Code competition (notebook submissions)"
                if meta.is_code_competition
                else meta.category,
            ),
        ]
        lines += [f"{k}: {escape(v)}" for k, v in facts if v]
        if entered is True:
            lines.append("[green]✓ You have joined this competition[/]")
        elif entered is False:
            lines.append(
                "[yellow]! You haven't accepted the rules yet. That only matters when you download the data: "
                f"{competition_url(meta.slug, 'rules')}[/]"
            )
        self.query_one("#card", Static).update("\n".join(lines))
        button = self.query_one("#continue", Button)
        button.disabled = False
        button.focus()

    @on(Button.Pressed, "#continue")
    def next(self) -> None:
        self.app.push_screen(ModesScreen())


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except KaggleError:
        return None


# -- step 3: modes --------------------------------------------------------------------------


class ModesScreen(Screen[None]):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        cwd = str(Path.cwd())
        has_claude = shutil.which("claude") is not None
        has_desktop = claude_desktop_config_path().parent.exists()
        yield Header()
        with VerticalScroll(classes="step"):
            yield Static("How should Claude get the context?", classes="title")
            yield Static("Pick one or more. They share one download.", classes="muted")

            yield Checkbox(
                "1 · Workspace folder: CLAUDE.md + overview, rules, data, discussions, code",
                True,
                id="m-folder",
            )
            with Vertical(id="o-folder", classes="opts"):
                yield Label("Create the folder inside:")
                yield Input(cwd, id="out-dir")
                yield Static(
                    "You download the data yourself later: data/download.sh is included.",
                    classes="muted",
                )

            yield Checkbox(
                "2 · Claude skill: loads automatically when you work on this competition",
                id="m-skill",
            )
            with Vertical(id="o-skill", classes="opts hidden"):
                with RadioSet(id="skill-scope"):
                    yield RadioButton("All my projects (~/.claude/skills)", True, id="scope-user")
                    yield RadioButton("One project (<project>/.claude/skills)", id="scope-project")
                    yield RadioButton(
                        "Zip to upload at claude.ai → Settings → Capabilities → Skills",
                        id="scope-zip",
                    )
                with Vertical(id="o-project", classes="hidden"):
                    yield Label("Project folder:")
                    yield Input(cwd, id="project-dir")

            yield Checkbox(
                "3 · MCP server: Claude calls tools for rules, discussions, notebooks, what's new",
                id="m-mcp",
            )
            with Vertical(id="o-mcp", classes="opts hidden"):
                yield Static("Runs locally on your machine. No hosting, no cost.", classes="muted")
                yield Checkbox("Claude Code (user scope)", has_claude, id="t-claude-code")
                yield Checkbox("Claude Desktop", has_desktop, id="t-claude-desktop")
                yield Checkbox(".mcp.json in the workspace folder", False, id="t-project")
                yield Checkbox(
                    "Just show me the config", not (has_claude or has_desktop), id="t-print"
                )

            with Collapsible(title="Advanced", collapsed=True):
                yield Label("Discussion topics to save (solution write-ups come extra):")
                yield Input("15", id="n-discussions", type="integer")
                yield Label("Top comments per topic:")
                yield Input("10", id="n-comments", type="integer")
                yield Label("Top notebooks to save:")
                yield Input("5", id="n-notebooks", type="integer")
                yield Label("Token budget for CONTEXT.md:")
                yield Input("50000", id="budget", type="integer")
                yield Checkbox("Ignore cache and fetch fresh", id="refresh")

            yield Static("", id="modes-error", classes="error")
            with Horizontal(classes="buttons"):
                yield Button("Back", id="back")
                yield Button("Fetch & export", id="go", variant="success")
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = "Step 3 of 4 · Delivery"
        self.query_one("#m-folder", Checkbox).focus()

    @on(Checkbox.Changed, "#m-folder, #m-skill, #m-mcp")
    def toggle(self, event: Checkbox.Changed) -> None:
        mode = event.checkbox.id.removeprefix("m-")  # type: ignore[union-attr]
        self.query_one(f"#o-{mode}").set_class(not event.value, "hidden")
        if mode == "folder" and not event.value:
            self.query_one("#t-project", Checkbox).value = False

    @on(RadioSet.Changed, "#skill-scope")
    def scope_changed(self, event: RadioSet.Changed) -> None:
        self.query_one("#o-project").set_class(event.pressed.id != "scope-project", "hidden")

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#go")
    def go(self) -> None:
        wiz: Wizard = self.app.wizard  # type: ignore[attr-defined]
        checked = lambda wid: self.query_one(wid, Checkbox).value  # noqa: E731
        modes = tuple(m for m in ("folder", "skill", "mcp") if checked(f"#m-{m}"))
        error = self.query_one("#modes-error", Static)
        if not modes:
            error.update("Pick at least one option.")
            return
        targets = tuple(
            t for t in ("claude-code", "claude-desktop", "project", "print") if checked(f"#t-{t}")
        )
        if "mcp" in modes and not targets:
            error.update("Pick where to register the MCP server.")
            return
        scope_button = self.query_one("#skill-scope", RadioSet).pressed_button
        scope = (scope_button.id or "scope-user").removeprefix("scope-") if scope_button else "user"
        wiz.plan = ExportPlan(
            modes=modes,
            out_dir=Path(self.query_one("#out-dir", Input).value or ".").expanduser().resolve(),
            skill_scope=scope,
            project_dir=Path(self.query_one("#project-dir", Input).value or ".")
            .expanduser()
            .resolve(),
            mcp_targets=targets,
            budget=_int(self.query_one("#budget", Input).value, 50_000),
        )
        wiz.options = FetchOptions(
            discussions=_int(self.query_one("#n-discussions", Input).value, 15),
            comments=_int(self.query_one("#n-comments", Input).value, 10),
            notebooks=_int(self.query_one("#n-notebooks", Input).value, 5),
        )
        wiz.refresh = checked("#refresh")
        self.app.push_screen(RunScreen())


def _int(value: str, default: int) -> int:
    try:
        return max(0, int(value))
    except ValueError:
        return default


# -- step 4: run ----------------------------------------------------------------------------


class RunScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        wiz: Wizard = self.app.wizard  # type: ignore[attr-defined]
        yield Header()
        with VerticalScroll(classes="step"):
            yield Static(
                f"Fetching [b]{escape(wiz.meta.title if wiz.meta else wiz.slug)}[/]",
                classes="title",
            )
            for key, label in SECTION_LABELS.items():
                yield Static(f"{ICONS['wait']} {label}", id=f"s-{key}")
            yield Static(f"{ICONS['wait']} Export", id="s-export")
            yield Static("", id="run-error", classes="error")
            with Horizontal(classes="buttons hidden", id="run-buttons"):
                yield Button("Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = "Step 4 of 4 · Working"
        self.run_all()

    def set_status(self, section: str, status: str, detail: str) -> None:
        label = SECTION_LABELS.get(section, "Export")
        text = f"{ICONS.get(status, '')} {label}"
        if detail:
            text += f"  [dim]{escape(detail)}[/]"
        self.query_one(f"#s-{section}", Static).update(text)

    @work(thread=True, exclusive=True)
    def run_all(self) -> None:
        app: KaggleContextApp = self.app  # type: ignore[assignment]
        wiz = app.wizard

        def progress(section: str, status: str, detail: str) -> None:
            app.call_from_thread(self.set_status, section, status, detail)

        try:
            wiz.bundle = get_bundle(
                app.client, wiz.slug, wiz.options, refresh=wiz.refresh, progress=progress
            )
        except KaggleError as exc:
            app.call_from_thread(self.failed, str(exc))
            return
        progress("export", "start", ", ".join(wiz.plan.modes))
        wiz.result = run_exports(wiz.bundle, wiz.plan)
        status = "error" if wiz.result.failed and not wiz.result.done else "done"
        progress("export", status, f"{len(wiz.result.done)} done, {len(wiz.result.failed)} failed")
        app.call_from_thread(app.push_screen, DoneScreen())

    def failed(self, message: str) -> None:
        self.query_one("#run-error", Static).update(escape(message))
        self.query_one("#run-buttons").remove_class("hidden")

    @on(Button.Pressed, "#back")
    def back(self) -> None:
        self.app.pop_screen()


# -- done -----------------------------------------------------------------------------------


def summary_markdown(wiz: Wizard) -> str:
    res = wiz.result or ExportResult()
    lines = [f"# Done: {wiz.meta.title if wiz.meta else wiz.slug}", ""]
    lines += [f"- ✓ {line}" for line in res.done if "\n" not in line]
    lines += [f"- ✗ {line}" for line in res.failed]
    for block in (line for line in res.done if "\n" in line):
        head, _, body = block.partition("\n")
        lines += ["", f"**{head}**", "", "```json", body, "```"]
    if wiz.bundle and wiz.bundle.errors:
        lines += ["", "Some sections could not be fetched:"]
        lines += [f"- {k}: {v}" for k, v in wiz.bundle.errors.items()]
    if res.next_steps:
        lines += ["", "## Next", ""] + [f"1. {s}" for s in res.next_steps]
    return "\n".join(lines)


class DoneScreen(Screen[None]):
    BINDINGS = [Binding("q", "finish", "Quit"), Binding("n", "another", "Another competition")]

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(classes="step"):
            yield Markdown(summary_markdown(self.app.wizard))  # type: ignore[attr-defined]
            with Horizontal(classes="buttons"):
                yield Button("Another competition", id="another")
                yield Button("Quit", id="finish", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        self.app.sub_title = "Done"
        self.query_one("#finish", Button).focus()

    @on(Button.Pressed, "#finish")
    def action_finish(self) -> None:
        self.app.exit(self.app.wizard)  # type: ignore[attr-defined]

    @on(Button.Pressed, "#another")
    def action_another(self) -> None:
        app: KaggleContextApp = self.app  # type: ignore[assignment]
        app.wizard = Wizard(username=app.wizard.username)
        while len(app.screen_stack) > 2:  # back down to the competition step
            app.pop_screen()
        app.switch_screen(CompetitionScreen())


# -- app ------------------------------------------------------------------------------------


class KaggleContextApp(App[Wizard]):
    TITLE = "kaggle-context"
    CSS = """
    .step { padding: 1 2; }
    .title { text-style: bold; color: $accent; margin-bottom: 1; }
    .muted { color: $text-muted; margin-bottom: 1; }
    .error { color: $error; }
    .hidden { display: none; }
    .card { border: round $accent; padding: 1 2; margin: 1 0; }
    .opts { padding: 0 0 1 4; height: auto; }
    .buttons { height: auto; margin-top: 1; }
    .buttons Button { margin-right: 2; }
    Checkbox { margin-top: 1; }
    #login Button { margin-bottom: 1; }
    Collapsible { margin-top: 1; }
    """

    def __init__(
        self,
        initial: str | None = None,
        client_factory: Callable[[], Any] = KaggleClient,
        skip_credential_file_check: bool = False,
    ) -> None:
        super().__init__()
        self.wizard = Wizard(initial=initial)
        self._client_factory = client_factory
        self._client: Any = None
        self.skip_credential_file_check = skip_credential_file_check

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def reset_client(self) -> None:
        self._client = None

    def on_mount(self) -> None:
        self.title = f"kaggle-context {__version__}"
        self.push_screen(AuthScreen())


def run_tui(initial: str | None = None) -> None:
    wiz = KaggleContextApp(initial).run()
    if wiz and wiz.result:
        # The TUI clears the screen on exit; leave the essentials in the terminal.
        res = wiz.result
        for line in res.done:
            print(f"✓ {line}")
        for line in res.failed:
            print(f"✗ {line}")
        if res.next_steps:
            print("\nNext:")
            for step in res.next_steps:
                print(f"  • {step}")
