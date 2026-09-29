"""Command-line entry point."""

import typer

from kaggle_context import __version__

app = typer.Typer(help="Turn any Kaggle competition into Claude-ready context.")


@app.callback()
def root() -> None:
    """Turn any Kaggle competition into Claude-ready context."""


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def main() -> None:
    app()
