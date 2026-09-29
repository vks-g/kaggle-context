"""Terminal output shared by the interactive flow and the headless commands."""

from __future__ import annotations

import threading

from rich.console import Console
from rich.markup import escape
from rich.status import Status

from kctx.core.fetch import Progress
from kctx.core.models import CompetitionMeta
from kctx.core.slug import competition_url
from kctx.pipeline import ExportResult
from kctx.render.facts import format_date

SECTION_LABELS = {
    "overview": "overview",
    "rules": "rules",
    "data": "data files",
    "discussions": "discussions",
    "code": "notebooks",
    "leaderboard": "leaderboard",
}


def progress_printer(console: Console, status: Status | None = None) -> Progress:
    """One line per finished section; the spinner (if any) shows what's in flight."""
    lock = threading.Lock()

    def progress(section: str, state: str, detail: str) -> None:
        label = SECTION_LABELS.get(section, section)
        with lock:
            if state == "done":
                console.print(f"  [green]✓[/] {label:<12} [dim]{escape(detail)}[/]")
            elif state == "error":
                console.print(f"  [red]✗[/] {label:<12} {escape(detail)}")
            elif status is not None and state in ("start", "progress"):
                status.update(f"Fetching {label} {escape(detail)}".rstrip())

    return progress


def competition_card(meta: CompetitionMeta, entered: bool | None) -> str:
    lines = [f"  [bold]{escape(meta.title)}[/]"]
    if meta.subtitle:
        lines.append(f"  [dim]{escape(meta.subtitle)}[/]")
    facts = [
        ("Metric", meta.evaluation_metric),
        ("Deadline", format_date(meta.deadline)),
        ("Teams", f"{meta.team_count:,}" if meta.team_count else ""),
        ("Prize", meta.reward),
    ]
    row = "  ·  ".join(f"{k}: {escape(v)}" for k, v in facts if v)
    if row:
        lines.append(f"  {row}")
    if meta.is_code_competition:
        lines.append("  Code competition: you submit a Kaggle notebook, not a CSV")
    if entered is True:
        lines.append("  [green]✓ You have joined this competition[/]")
    elif entered is False:
        lines.append(
            "  [yellow]! You haven't accepted the rules yet. That's only needed to download the data:[/] "
            + competition_url(meta.slug, "rules")
        )
    return "\n".join(lines)


def print_result(console: Console, result: ExportResult) -> None:
    for line in result.done:
        head, _, body = line.partition("\n")
        console.print(f"[green]✓[/] {escape(head)}")
        if body:
            console.print(body, markup=False, highlight=False)
    for line in result.failed:
        console.print(f"[red]✗[/] {escape(line)}")
    if result.next_steps:
        console.print("\n[bold]Next:[/]")
        for step in result.next_steps:
            console.print(f"  • {escape(step)}")
