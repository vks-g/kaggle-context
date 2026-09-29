"""Mode 2: a per-competition Claude skill.

Layout follows progressive disclosure: only the frontmatter (name + description) sits
in Claude's context until the skill is relevant; SKILL.md then gives the key facts and
a map; the long material lives in ``references/`` and is read one file at a time.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from kctx.core.models import Bundle
from kctx.exporters.workspace import write, write_reference_tree
from kctx.render import sections as r
from kctx.render.facts import render_facts

MARKER = ".kctx-skill"
LEGACY_MARKERS = (".kaggle-context-skill",)  # skills made before the rename to kctx
SCOPES = ("user", "project", "zip")


def skill_name(slug: str) -> str:
    return ("kaggle-" + slug)[:64].rstrip("-")


def user_skills_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "skills"


def skill_description(bundle: Bundle) -> str:
    m = bundle.meta
    bits = [f"Context for the Kaggle competition '{m.title}' ({m.slug})"]
    if m.evaluation_metric:
        bits.append(f"metric: {m.evaluation_metric}")
    desc = (
        "; ".join(bits)
        + ". Covers the overview, evaluation, rules, data files, top discussions"
        + (", winning solution write-ups" if any(t.is_solution for t in bundle.topics) else "")
        + " and top public notebooks. Use when working on, writing code for, or answering "
        + f"questions about the {m.title} competition."
    )
    return desc.replace("\n", " ")[:1000]


def render_skill_md(bundle: Bundle) -> str:
    name = skill_name(bundle.slug)
    desc = skill_description(bundle).replace('"', "'")
    body = [
        f"# {bundle.meta.title}",
        r.header(bundle),
        "## Key facts\n\n" + render_facts(bundle),
        "## Reference files\n\nRead only the file you need; they can be long.\n\n"
        + r.render_file_map(bundle, prefix="references/", workspace=False),
        "\n".join(
            [
                "## How to use this skill",
                "",
                "- Answer rules questions (external data, pretrained models, team size, submissions) by "
                "quoting `references/rules/rules.md`. Don't answer from memory.",
                "- For approaches, start with `references/discussions/solutions/` if it exists, then "
                "`references/discussions/INDEX.md` and `references/code/INDEX.md`.",
                "- Code in `references/code/` is from public Kaggle notebooks. Keep the attribution "
                "when you reuse it.",
                "- The data itself is not bundled. Tell the user to download it: "
                f"`{r.download_command(bundle.slug)}` after accepting the rules.",
                f"- This is a snapshot from {bundle.fetched_at[:10]}. If the competition is still running "
                f"and freshness matters, run `kctx fetch {bundle.slug} --mode skill --refresh`, or use the "
                "kctx MCP server's `get_whats_new` tool.",
            ]
        ),
    ]
    return f'---\nname: {name}\ndescription: "{desc}"\n---\n\n' + "\n\n".join(body) + "\n"


def build_skill(bundle: Bundle, target_dir: Path) -> Path:
    """Write the skill folder at ``target_dir/<skill-name>/`` and return it."""
    root = target_dir / skill_name(bundle.slug)
    if root.exists():
        if not any((root / m).exists() for m in (MARKER, *LEGACY_MARKERS)):
            raise FileExistsError(f"{root} exists and was not created by kctx; not overwriting it.")
        shutil.rmtree(root)
    root.mkdir(parents=True)
    write_reference_tree(bundle, root / "references", copy_sources=False)
    write(root / "SKILL.md", render_skill_md(bundle))
    (root / MARKER).write_text(bundle.fetched_at + "\n")
    return root


def export_skill(
    bundle: Bundle,
    scope: str = "user",
    project_dir: Path | None = None,
    zip_dir: Path | None = None,
) -> Path:
    """Install the skill. Returns the skill folder, or the .zip path for scope ``zip``."""
    if scope == "user":
        return build_skill(bundle, user_skills_dir())
    if scope == "project":
        base = project_dir or Path.cwd()
        return build_skill(bundle, base / ".claude" / "skills")
    if scope == "zip":
        out_dir = zip_dir or Path.cwd()
        staging = out_dir / f".{skill_name(bundle.slug)}.build"
        shutil.rmtree(staging, ignore_errors=True)
        folder = build_skill(bundle, staging)
        zip_path = out_dir / f"{folder.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(folder.rglob("*")):
                if path.is_file() and path.name not in (MARKER, *LEGACY_MARKERS):
                    zf.write(path, path.relative_to(staging))
        shutil.rmtree(staging, ignore_errors=True)
        return zip_path
    raise ValueError(f"Unknown skill scope {scope!r}; use one of {SCOPES}")
