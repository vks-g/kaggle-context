"""On-disk cache of fetched bundles: ``<cache>/<slug>/bundle.json`` + ``notebooks/``.

The prompts, the CLI exporters and the MCP server all read from here, so a competition
is fetched from Kaggle once and reused.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from kctx.core.client import KaggleSource
from kctx.core.fetch import FetchOptions, Progress, _noop, fetch_bundle, whats_new
from kctx.core.models import Bundle

BUNDLE_FILE = "bundle.json"


def cache_root() -> Path:
    if env := os.environ.get("KCTX_CACHE"):
        return Path(env).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "kctx"


def bundle_dir(slug: str) -> Path:
    return cache_root() / slug


def load_bundle(slug: str) -> Bundle | None:
    path = bundle_dir(slug) / BUNDLE_FILE
    if not path.exists():
        return None
    try:
        return Bundle.from_dict(json.loads(path.read_text()))
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_bundle(bundle: Bundle, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / BUNDLE_FILE).write_text(json.dumps(bundle.to_dict(), indent=1, ensure_ascii=False))


def iter_cached() -> Iterator[Bundle]:
    root = cache_root()
    if not root.exists():
        return
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.endswith(".staging"):
            bundle = load_bundle(child.name)
            if bundle:
                yield bundle


def is_fresh(bundle: Bundle, max_age: timedelta) -> bool:
    try:
        fetched = datetime.fromisoformat(bundle.fetched_at)
    except ValueError:
        return False
    return datetime.now(UTC) - fetched < max_age


def get_bundle(
    client: KaggleSource,
    slug: str,
    options: FetchOptions | None = None,
    *,
    refresh: bool = False,
    max_age: timedelta = timedelta(hours=24),
    progress: Progress = _noop,
) -> Bundle:
    """Return a cached bundle if it is fresh enough, otherwise fetch and cache a new one."""
    previous = load_bundle(slug)
    if previous and not refresh and is_fresh(previous, max_age):
        for section in ("overview", "rules", "data", "discussions", "code", "leaderboard"):
            progress(section, "done", "cached")
        return previous

    final = bundle_dir(slug)
    staging = final.with_name(slug + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    bundle = fetch_bundle(client, slug, staging, options, progress)

    if previous:
        try:
            changes = whats_new(client, slug, previous.fetched_at)
            bundle.changes_since = previous.fetched_at
            bundle.changes = changes
        except Exception:  # what's-new is a bonus; never fail the refresh over it
            pass

    save_bundle(bundle, staging)
    shutil.rmtree(final, ignore_errors=True)
    staging.rename(final)
    return bundle


def notebook_path(bundle: Bundle, source_file: str) -> Path:
    return bundle_dir(bundle.slug) / "notebooks" / source_file
