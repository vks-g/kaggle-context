"""Mode 1: a workspace folder you open Claude Code (or any agent) in.

Generated files are rewritten on every export; anything else in the folder
(your code, ``data/raw/``) is left alone.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from kctx.core.cache import notebook_path
from kctx.core.models import Bundle
from kctx.render import sections as r

MANIFEST = ".kctx/manifest.json"
LEGACY_MANIFEST = ".kaggle-context/manifest.json"  # workspaces made before the rename to kctx


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_reference_tree(bundle: Bundle, root: Path, copy_sources: bool) -> list[Path]:
    """The overview/rules/data/discussions/code tree shared by the workspace and the skill."""
    written: list[Path] = []

    def put(rel: str, text: str) -> None:
        write(root / rel, text)
        written.append(root / rel)

    for sub in ("overview", "discussions/solutions", "discussions/topics", "code"):
        shutil.rmtree(root / sub, ignore_errors=True)

    put("overview/README.md", r.render_overview(bundle))
    for page in bundle.overview_pages():
        put(f"overview/{r.page_filename(page)}", r.render_page(bundle, page))
    if bundle.leaderboard or "leaderboard" in bundle.errors:
        put("overview/leaderboard.md", r.render_leaderboard(bundle))
    write(root / "overview/metadata.json", json.dumps(bundle.meta.__dict__, indent=2))

    put("rules/rules.md", r.render_rules(bundle))
    put("data/README.md", r.render_data(bundle, local_script=copy_sources))

    put("discussions/INDEX.md", r.render_discussions_index(bundle))
    for topic in bundle.topics:
        put(f"discussions/{r.topic_path(topic)}", r.render_topic(topic))

    put("code/INDEX.md", r.render_code_index(bundle, with_sources=copy_sources))
    for nb in bundle.notebooks:
        put(f"code/{r.notebook_filename(nb)}", r.render_notebook(nb))
        if copy_sources and nb.source_file:
            src = notebook_path(bundle, nb.source_file)
            if src.exists():
                (root / "code/notebooks").mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, root / "code/notebooks" / nb.source_file)

    whats_new = r.render_whats_new(bundle)
    if whats_new:
        put("WHATS_NEW.md", whats_new)
    return written


def export_workspace(
    bundle: Bundle, parent: Path, budget: int = 50_000, settings: dict[str, Any] | None = None
) -> Path:
    root = parent / bundle.slug if parent.name != bundle.slug else parent
    root.mkdir(parents=True, exist_ok=True)

    write_reference_tree(bundle, root, copy_sources=True)
    guide = r.render_agent_guide(bundle)
    write(root / "CLAUDE.md", guide)
    write(root / "AGENTS.md", guide)
    write(root / "CONTEXT.md", r.render_context(bundle, budget))

    script = root / "data/download.sh"
    write(script, r.download_script(bundle.slug))
    script.chmod(0o755)
    (root / "data/raw").mkdir(parents=True, exist_ok=True)
    (root / "data/raw/.gitkeep").touch()

    gitignore = root / ".gitignore"
    if not gitignore.exists():
        write(gitignore, "# Competition data must not be committed or shared\ndata/raw/\n")

    write(
        root / MANIFEST,
        json.dumps(
            {
                "slug": bundle.slug,
                "fetched_at": bundle.fetched_at,
                "tool_version": bundle.tool_version,
                "settings": settings or {},
            },
            indent=2,
        ),
    )
    shutil.rmtree(root / Path(LEGACY_MANIFEST).parent, ignore_errors=True)
    return root


def read_manifest(folder: Path) -> dict[str, Any] | None:
    path = folder / MANIFEST
    if not path.exists():
        path = folder / LEGACY_MANIFEST
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None
