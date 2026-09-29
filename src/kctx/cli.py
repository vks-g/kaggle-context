"""Command-line entry point.

``kctx`` with no arguments (or with just a competition URL) asks a few questions inline.
Subcommands do the same work headlessly, for scripts, CI, skills and agents.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console

from kctx import __version__
from kctx.core.models import SECTIONS

app = typer.Typer(
    help="Turn any Kaggle competition into Claude-ready context. Run `kctx` with no arguments to be asked step by step.",
    add_completion=False,
    no_args_is_help=False,
)
err = Console(stderr=True, soft_wrap=True)


def _split(value: str) -> tuple[str, ...]:
    return tuple(v.strip() for v in value.split(",") if v.strip())


def _fail(message: str) -> None:
    err.print(f"[red]Error:[/] {message}")
    raise typer.Exit(1)


@app.command()
def fetch(
    competition: str = typer.Argument(..., help="Competition URL or slug"),
    mode: str = typer.Option("folder", "--mode", "-m", help="Comma-separated: folder, skill, mcp"),
    out: Path = typer.Option(
        Path("."), "--out", "-o", help="Parent folder for the workspace / skill zip"
    ),
    skill_scope: str = typer.Option("user", help="user (~/.claude/skills), project, or zip"),
    project_dir: Path | None = typer.Option(None, help="Project root for --skill-scope project"),
    mcp_target: str = typer.Option(
        "claude-code", help="Comma-separated: claude-code, claude-desktop, project, print"
    ),
    discussions: int = typer.Option(
        15, help="Discussion topics to save (solution write-ups come extra)"
    ),
    comments: int = typer.Option(10, help="Top comments to keep per topic"),
    notebooks: int = typer.Option(5, help="Top public notebooks to save"),
    sort: str = typer.Option("top", help="Discussion order: top, hot, new, recent"),
    budget: int = typer.Option(50_000, help="Token budget for CONTEXT.md"),
    sections: str = typer.Option(",".join(SECTIONS), help="Comma-separated sections to fetch"),
    refresh: bool = typer.Option(False, "--refresh", help="Ignore the cache and fetch again"),
) -> None:
    """Fetch a competition and export it (the non-interactive version of `kctx`)."""
    from kctx.core.cache import get_bundle
    from kctx.core.client import KaggleClient, KaggleError
    from kctx.core.fetch import FetchOptions
    from kctx.core.slug import parse_competition
    from kctx.pipeline import MODES, ExportPlan, run_exports
    from kctx.ui import print_result, progress_printer

    try:
        slug = parse_competition(competition)
    except ValueError as exc:
        _fail(str(exc))
    modes = _split(mode)
    if bad := [m for m in modes if m not in MODES]:
        _fail(f"Unknown mode(s) {', '.join(bad)}; use {', '.join(MODES)}")

    opts = FetchOptions(
        sections=_split(sections),
        discussions=discussions,
        comments=comments,
        notebooks=notebooks,
        discussion_sort=sort,
    )
    err.print(f"Fetching [bold]{slug}[/] from Kaggle…")
    try:
        bundle = get_bundle(
            KaggleClient(), slug, opts, refresh=refresh, progress=progress_printer(err)
        )
    except KaggleError as exc:
        _fail(str(exc))

    plan = ExportPlan(
        modes=modes,
        out_dir=out.expanduser().resolve(),
        skill_scope=skill_scope,
        project_dir=project_dir,
        mcp_targets=_split(mcp_target),
        budget=budget,
    )
    result = run_exports(bundle, plan)
    print_result(err, result)
    if result.failed and not result.done:
        raise typer.Exit(1)


@app.command()
def refresh(
    target: str = typer.Argument(
        ".", help="Workspace folder (default: current) or a competition slug"
    ),
) -> None:
    """Re-fetch a competition and rewrite the workspace/skill it was exported to."""
    from kctx.core.cache import get_bundle
    from kctx.core.client import KaggleClient, KaggleError
    from kctx.core.slug import parse_competition
    from kctx.exporters.workspace import read_manifest
    from kctx.pipeline import ExportPlan, run_exports
    from kctx.ui import print_result, progress_printer

    folder = Path(target).expanduser()
    manifest = read_manifest(folder) if folder.is_dir() else None
    try:
        slug = manifest["slug"] if manifest else parse_competition(target)
    except ValueError:
        _fail(f"{target!r} is neither a kctx workspace nor a competition slug.")
    try:
        bundle = get_bundle(KaggleClient(), slug, refresh=True, progress=progress_printer(err))
    except KaggleError as exc:
        _fail(str(exc))

    if manifest:
        settings = manifest.get("settings", {})
        modes = tuple(m for m in settings.get("modes", ["folder"]) if m != "mcp")
        plan = ExportPlan(
            modes=modes or ("folder",),
            out_dir=folder.resolve(),
            skill_scope=settings.get("skill_scope", "user"),
            budget=settings.get("budget", 50_000),
        )
        print_result(err, run_exports(bundle, plan))
    new = len(bundle.changes.get("new_topics", []))
    active = len(bundle.changes.get("active_topics", []))
    if bundle.changes_since:
        err.print(f"Since the last fetch: {new} new topics, {active} topics with new comments.")


@app.command()
def search(
    query: str = typer.Argument("", help="Words to search for; empty lists active competitions"),
) -> None:
    """Search Kaggle competitions."""
    from rich.table import Table

    from kctx.core.client import KaggleClient, KaggleError, _slug_of

    try:
        comps = KaggleClient().search_competitions(query)
    except KaggleError as exc:
        _fail(str(exc))
    table = Table("slug", "title", "deadline", "metric", "teams")
    for c in comps:
        table.add_row(
            _slug_of(c),
            c.get("title", ""),
            (c.get("deadline") or "")[:10],
            c.get("evaluationMetric", ""),
            str(c.get("teamCount", "")),
        )
    Console().print(table)


@app.command()
def mcp(
    competition: str | None = typer.Option(None, "--competition", "-c", help="Default competition"),
) -> None:
    """Run the MCP server over stdio (Claude starts this for you)."""
    from kctx.mcp_server import run

    run(competition)


@app.command()
def login(
    token: str | None = typer.Option(None, help="Paste an API token instead of the browser flow"),
) -> None:
    """Connect your Kaggle account (browser OAuth, or an API token)."""
    from kctx.core.client import KaggleClient, save_access_token

    if token:
        path = save_access_token(token)
        err.print(f"[green]✓[/] Saved token to {path}")
    else:
        KaggleClient().login_with_browser()
    err.print(f"Logged in as [bold]{KaggleClient().whoami()}[/]")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


COMMANDS = {"fetch", "refresh", "search", "mcp", "login", "version"}


def main() -> None:
    args = sys.argv[1:]
    if not args or (args[0] not in COMMANDS and not args[0].startswith("-")):
        from kctx.interactive import main as interactive

        sys.exit(interactive(args[0] if args else None))
    app()
