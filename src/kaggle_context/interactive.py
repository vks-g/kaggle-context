"""`kctx` with no arguments: a few questions asked inline in the terminal, then fetch + export.

Prompts go through a small ``Prompter`` interface so tests can script the answers;
the real one uses questionary (arrow keys, space to toggle, enter to confirm).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rich.console import Console
from rich.markup import escape

from kaggle_context import __version__
from kaggle_context.core.cache import get_bundle
from kaggle_context.core.client import (
    AuthError,
    KaggleClient,
    KaggleError,
    credentials_present,
    save_access_token,
)
from kaggle_context.core.fetch import FetchOptions, meta_from_api
from kaggle_context.core.models import CompetitionMeta
from kaggle_context.core.slug import competition_url, parse_competition
from kaggle_context.pipeline import ExportPlan, ExportResult, run_exports
from kaggle_context.ui import competition_card, print_result, progress_printer


class Cancelled(Exception):
    """The user pressed Ctrl-C or chose Quit."""


@dataclass
class Choice:
    label: str
    value: Any
    checked: bool = False
    hint: str = ""


Validator = Callable[[str], str | None]  # returns an error message, or None when valid


class Prompter(Protocol):
    def text(self, message: str, default: str = "", validate: Validator | None = None) -> str: ...
    def password(self, message: str) -> str: ...
    def select(self, message: str, choices: list[Choice]) -> Any: ...
    def checkbox(self, message: str, choices: list[Choice]) -> list[Any]: ...
    def confirm(self, message: str, default: bool = False) -> bool: ...


class QuestionaryPrompter:
    """Arrow-key prompts. ``kwargs`` (input/output) are passed to prompt_toolkit, for tests."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    @staticmethod
    def _ask(question: Any) -> Any:
        try:
            answer = question.unsafe_ask()
        except (KeyboardInterrupt, EOFError) as exc:
            raise Cancelled from exc
        if answer is None:
            raise Cancelled
        return answer

    def text(self, message: str, default: str = "", validate: Validator | None = None) -> str:
        import questionary

        check = (lambda v: validate(v) or True) if validate else None
        return self._ask(questionary.text(message, default=default, validate=check, **self.kwargs))

    def password(self, message: str) -> str:
        import questionary

        return self._ask(questionary.password(message, **self.kwargs))

    def select(self, message: str, choices: list[Choice]) -> Any:
        import questionary

        options = [questionary.Choice(c.label, c.value) for c in choices]
        return self._ask(
            questionary.select(message, choices=options, instruction="(↑/↓, enter)", **self.kwargs)
        )

    def checkbox(self, message: str, choices: list[Choice]) -> list[Any]:
        # Our own prompt: questionary's checkbox submits on Enter, so people who press
        # Enter on each option end up with only one of them.
        from kaggle_context.multiselect import multiselect

        try:
            return multiselect(
                message,
                [(c.label, c.value, c.hint) for c in choices],
                [c.checked for c in choices],
                **self.kwargs,
            )
        except (KeyboardInterrupt, EOFError) as exc:
            raise Cancelled from exc

    def confirm(self, message: str, default: bool = False) -> bool:
        import questionary

        return self._ask(questionary.confirm(message, default=default, **self.kwargs))


def use_real_tty_for_stdin() -> None:
    """On macOS, swap a ``/dev/tty`` stdin for the terminal's real device.

    ``curl … | sh`` gives us the keyboard via ``</dev/tty``, but macOS kqueue can't poll
    that alias device, which breaks the prompt library (and any Bun/Node child such as
    the ``claude`` CLI). The real device (``/dev/ttys003``…) works everywhere.
    """
    if sys.platform != "darwin":
        return
    try:
        if not os.isatty(0) or os.ttyname(0) != "/dev/tty":
            return
    except OSError:
        return
    device = None
    for fd in (1, 2):
        try:
            name = os.ttyname(fd)
        except OSError:
            continue
        if name != "/dev/tty":
            device = name
            break
    if device is None:
        out = subprocess.run(
            ["ps", "-o", "tty=", "-p", str(os.getpid())],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        ).stdout.strip()
        device = f"/dev/{out}" if out and out not in ("?", "??") else None
    if device is None:
        return
    try:
        fd = os.open(device, os.O_RDWR | os.O_NOCTTY)
    except OSError:
        return
    os.dup2(fd, 0)
    os.close(fd)


# -- steps -----------------------------------------------------------------------------------


def _int_validator(value: str) -> str | None:
    return None if value.strip().isdigit() else "Enter a whole number"


def _url_validator(value: str) -> str | None:
    try:
        parse_competition(value)
    except ValueError as exc:
        return str(exc)
    return None


class Session:
    def __init__(
        self,
        prompter: Prompter,
        console: Console,
        client_factory: Callable[[], Any] = KaggleClient,
        has_credentials: Callable[[], bool] = credentials_present,
        cwd: Path | None = None,
    ) -> None:
        self.ask = prompter
        self.console = console
        self.client_factory = client_factory
        self.client: Any = client_factory()
        self.has_credentials = has_credentials
        self.cwd = cwd or Path.cwd()

    # 1. account
    def login(self) -> str | None:
        while True:
            reason = "No Kaggle credentials found on this machine."
            if self.has_credentials():
                try:
                    with self.console.status("Checking your Kaggle account…"):
                        user = self.client.whoami()
                    self.console.print(
                        f"[green]✓[/] Kaggle: signed in as [bold]{escape(user or '?')}[/]"
                    )
                    return user
                except AuthError as exc:
                    reason = str(exc)
            self.console.print(f"[yellow]![/] {escape(reason)}")
            how = self.ask.select(
                "Connect your Kaggle account:",
                [
                    Choice("Log in with your browser (recommended)", "browser"),
                    Choice("Paste an API token from https://www.kaggle.com/settings/api", "token"),
                    Choice("Quit", "quit"),
                ],
            )
            if how == "quit":
                raise Cancelled
            if how == "browser":
                self.console.print("Opening Kaggle in your browser. Finish the login there.")
                try:
                    self.client.login_with_browser()
                except (Exception, SystemExit) as exc:  # the SDK exits on some failures
                    self.console.print(f"[red]✗[/] Login did not complete: {escape(str(exc))}")
            else:
                token = self.ask.password("API token:")
                try:
                    path = save_access_token(token)
                    self.console.print(f"[green]✓[/] Saved token to {path}")
                except ValueError as exc:
                    self.console.print(f"[red]✗[/] {escape(str(exc))}")
            self.client = self.client_factory()

    # 2. competition
    def competition(self, initial: str | None) -> CompetitionMeta:
        value = initial
        while True:
            if value is None:
                value = self.ask.text("Competition URL:", validate=_url_validator)
            try:
                slug = parse_competition(value)
            except ValueError as exc:
                self.console.print(f"[red]✗[/] {escape(str(exc))}")
                value = None
                continue
            try:
                with self.console.status(f"Looking up {slug}…"):
                    meta, entered = self._lookup(slug)
            except KaggleError as exc:
                self.console.print(f"[red]✗[/] Couldn't find '{escape(slug)}': {escape(str(exc))}")
                value = None
                continue
            self.console.print(competition_card(meta, entered))
            return meta

    def _lookup(self, slug: str) -> tuple[CompetitionMeta, bool | None]:
        comp = self.client.competition(slug)
        if comp is None:
            self.client.pages(slug)  # raises NotFoundError for unknown slugs
            meta = CompetitionMeta(slug=slug, title=slug, url=competition_url(slug))
        else:
            meta = meta_from_api(slug, comp)
        try:
            entered = self.client.has_entered(slug)
        except KaggleError:
            entered = None
        return meta, entered

    # 3. delivery
    def delivery(self) -> tuple[ExportPlan, FetchOptions, bool]:
        cwd = str(self.cwd)
        # Nothing is pre-ticked: Enter ticks, so a pre-ticked option would get unticked.
        modes = self.ask.checkbox(
            "How should Claude get the context?",
            [
                Choice(
                    "Workspace folder",
                    "folder",
                    hint="CLAUDE.md + overview, rules, data, discussions, code",
                ),
                Choice(
                    "Claude skill",
                    "skill",
                    hint="loads automatically when you work on this competition",
                ),
                Choice(
                    "MCP server",
                    "mcp",
                    hint="Claude calls tools for rules, discussions, notebooks, what's new",
                ),
            ],
        )
        plan = ExportPlan(modes=tuple(modes), out_dir=self.cwd)
        if "folder" in modes:
            out = self.ask.text("Create the workspace folder in:", default=cwd)
            plan.out_dir = Path(out or cwd).expanduser().resolve()
        if "skill" in modes:
            plan.skill_scope = self.ask.select(
                "Install the skill for:",
                [
                    Choice("All my projects (~/.claude/skills)", "user"),
                    Choice("One project (<project>/.claude/skills)", "project"),
                    Choice("claude.ai / Claude Desktop (makes a .zip you upload)", "zip"),
                ],
            )
            if plan.skill_scope == "project":
                folder = self.ask.text("Project folder:", default=cwd)
                plan.project_dir = Path(folder or cwd).expanduser().resolve()
        if "mcp" in modes:
            has_claude = shutil.which("claude") is not None
            targets = [
                Choice(
                    "Claude Code",
                    "claude-code",
                    hint="recommended" if has_claude else "claude CLI not found",
                ),
                Choice("Claude Desktop", "claude-desktop"),
            ]
            if "folder" in modes:
                targets.append(
                    Choice(".mcp.json in the workspace folder", "project", hint="that project only")
                )
            targets.append(Choice("Just print the config", "print"))
            plan.mcp_targets = tuple(self.ask.checkbox("Register the MCP server with:", targets))

        options = FetchOptions()
        refresh = False
        if self.ask.confirm("Change advanced settings (discussions, notebooks, token budget)?"):
            options.discussions = int(
                self.ask.text("Discussion topics to save:", "15", _int_validator)
            )
            options.comments = int(self.ask.text("Top comments per topic:", "10", _int_validator))
            options.notebooks = int(self.ask.text("Top notebooks to save:", "5", _int_validator))
            plan.budget = int(
                self.ask.text("Token budget for CONTEXT.md:", "50000", _int_validator)
            )
            refresh = self.ask.confirm("Ignore the cache and fetch fresh?")
        return plan, options, refresh

    # 4. run
    def run(
        self, meta: CompetitionMeta, plan: ExportPlan, options: FetchOptions, refresh: bool
    ) -> ExportResult:
        self.console.print(f"\nFetching [bold]{escape(meta.title)}[/]")
        with self.console.status("Fetching…") as status:
            bundle = get_bundle(
                self.client,
                meta.slug,
                options,
                refresh=refresh,
                progress=progress_printer(self.console, status),
            )
            status.update("Writing files…")
            result = run_exports(bundle, plan)
        self.console.print()
        print_result(self.console, result)
        return result


def run_interactive(
    initial: str | None = None,
    prompter: Prompter | None = None,
    console: Console | None = None,
    **session_kwargs: Any,
) -> ExportResult | None:
    console = console or Console(soft_wrap=True)
    prompter = prompter or QuestionaryPrompter()
    console.print(
        f"[bold]kaggle-context[/] {__version__} [dim]· Kaggle competition → Claude context[/]\n"
    )
    try:
        session = Session(prompter, console, **session_kwargs)
        session.login()
        meta = session.competition(initial)
        plan, options, refresh = session.delivery()
        return session.run(meta, plan, options, refresh)
    except Cancelled:
        console.print("[dim]Cancelled.[/]")
        return None
    except KaggleError as exc:
        console.print(f"[red]✗[/] {escape(str(exc))}")
        return None


def main(initial: str | None = None) -> int:
    use_real_tty_for_stdin()
    result = run_interactive(initial)
    return 0 if result is not None and (result.done or not result.failed) else 1
