"""Markdown renderers shared by every exporter and the MCP server."""

from __future__ import annotations

import re

from kctx import __version__
from kctx.core.budget import allocate, estimate_tokens, truncate
from kctx.core.models import Bundle, Comment, Notebook, Page, Topic, TopicRef
from kctx.core.slug import competition_url
from kctx.render.facts import format_date, render_facts
from kctx.render.html2md import nest_headings

CONTEXT_SHARES = {
    "overview": 0.15,
    "rules": 0.10,
    "data": 0.10,
    "discussions": 0.30,
    "code": 0.30,
    "leaderboard": 0.05,
}


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len].rstrip("-") or "untitled"


def page_filename(page: Page) -> str:
    return slugify(page.name) + ".md"


def topic_path(topic: Topic | TopicRef, is_solution: bool | None = None) -> str:
    """Path of a topic file relative to the discussions/ folder."""
    solution = topic.is_solution if isinstance(topic, Topic) else bool(is_solution)
    folder = "solutions" if solution else "topics"
    return f"{folder}/{topic.id}-{slugify(topic.title, 50)}.md"


def notebook_filename(nb: Notebook) -> str:
    return nb.ref.replace("/", "__") + ".md"


def _date(value: str) -> str:
    return value[:10] if value else ""


def human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def header(bundle: Bundle) -> str:
    return (
        f"> Snapshot of [{bundle.meta.title}]({bundle.meta.url}) taken {format_date(bundle.fetched_at, relative=False)} "
        f"by kctx {bundle.tool_version or __version__}."
    )


# -- sections --------------------------------------------------------------------------------


def render_overview(bundle: Bundle) -> str:
    m = bundle.meta
    parts = [f"# {m.title}", header(bundle)]
    if m.subtitle:
        parts.append(f"_{m.subtitle}_")
    parts.append("## Key facts\n\n" + render_facts(bundle))
    for page in bundle.overview_pages():
        parts.append(f"## {page.name}\n\n{nest_headings(page.content, 3)}")
    return "\n\n".join(parts) + "\n"


def render_page(bundle: Bundle, page: Page) -> str:
    return f"# {page.name}\n\n{header(bundle)}\n\n{nest_headings(page.content, 2)}\n"


def render_rules(bundle: Bundle) -> str:
    rules = bundle.page("rules")
    body = nest_headings(rules.content, 2) if rules else "_No rules page was returned by Kaggle._"
    link = competition_url(bundle.slug, "rules")
    return f"# Rules: {bundle.meta.title}\n\n{header(bundle)} Source: {link}\n\n{body}\n"


def download_command(slug: str) -> str:
    return f"kaggle competitions download -c {slug} -p data/raw"


def render_data(bundle: Bundle, local_script: bool = False) -> str:
    slug = bundle.slug
    parts = [f"# Data: {bundle.meta.title}", header(bundle)]
    desc = bundle.page("data-description", "data", "data description")
    if desc:
        parts.append("## Description\n\n" + nest_headings(desc.content, 3))
    if bundle.files:
        total = sum(f.size for f in bundle.files)
        rows = ["| File | Size |", "|---|---|"]
        rows += [f"| `{f.name}` | {human_size(f.size)} |" for f in bundle.files[:200]]
        if len(bundle.files) > 200:
            rows.append(f"| … {len(bundle.files) - 200} more | |")
        parts.append(
            f"## Files ({len(bundle.files)}, {human_size(total)} total)\n\n" + "\n".join(rows)
        )
    elif "data" in bundle.errors:
        parts.append(f"## Files\n\n_Could not list files: {bundle.errors['data']}_")
    how = [
        "## Getting the data",
        "",
        "The data is **not** included here. Competition rules usually forbid redistributing it, "
        "so you download it yourself with your own Kaggle account:",
        "",
        f"1. Accept the rules: {competition_url(slug, 'rules')}",
    ]
    if local_script:
        how.append("2. Run `bash data/download.sh` (puts everything in `data/raw/`)")
    else:
        how.append(f"2. Run `{download_command(slug)}`")
    parts.append("\n".join(how))
    return "\n\n".join(parts) + "\n"


def download_script(slug: str) -> str:
    return f"""#!/bin/sh
# Download the data for the Kaggle competition '{slug}' into data/raw/.
# First accept the rules at {competition_url(slug, "rules")}
set -eu
cd "$(dirname "$0")"
mkdir -p raw
if command -v kaggle >/dev/null 2>&1; then
  kaggle competitions download -c {slug} -p raw
else
  uvx kaggle competitions download -c {slug} -p raw
fi
cd raw
for z in *.zip; do
  [ -e "$z" ] || continue
  unzip -o -q "$z" && rm "$z"
done
echo "Data is in $(pwd)"
"""


def _render_comment(c: Comment, depth: int = 0) -> str:
    who = c.author or "anonymous"
    head = f"**{who}** · ▲{c.votes} · {_date(c.date)}"
    body = nest_headings(c.content, 5)
    text = f"{head}\n\n{body}"
    if depth:
        text = "\n".join("> " + line if line else ">" for line in text.splitlines())
    for r in c.replies:
        text += "\n\n" + _render_comment(r, depth + 1)
    return text


def render_topic(topic: Topic) -> str:
    tag = " (solution write-up)" if topic.is_solution else ""
    meta = f"by **{topic.author or 'unknown'}** · ▲{topic.votes} · {topic.comment_count} comments · {_date(topic.date)} · {topic.url}"
    parts = [f"# {topic.title}{tag}", meta, nest_headings(topic.content, 3) or "_(empty post)_"]
    if topic.comments:
        parts.append(f"## Top comments ({len(topic.comments)} of {topic.comment_count}, by votes)")
        parts += [_render_comment(c) for c in topic.comments]
    return "\n\n".join(parts) + "\n"


def render_topic_table(refs: list[tuple[str, Topic | TopicRef]]) -> str:
    rows = ["| Topic | ▲ | Comments | Date |", "|---|---|---|---|"]
    for link, t in refs:
        title = t.title.replace("|", r"\|")
        rows.append(f"| [{title}]({link}) | {t.votes} | {t.comment_count} | {_date(t.date)} |")
    return "\n".join(rows)


def render_discussions_index(bundle: Bundle) -> str:
    parts = [f"# Discussions: {bundle.meta.title}", header(bundle)]
    solutions = [t for t in bundle.topics if t.is_solution]
    others = [t for t in bundle.topics if not t.is_solution]
    if solutions:
        parts.append(
            "## Solution write-ups\n\n"
            + render_topic_table([(topic_path(t), t) for t in solutions])
        )
    if others:
        parts.append(
            "## Top discussions\n\n" + render_topic_table([(topic_path(t), t) for t in others])
        )
    saved = {t.id for t in bundle.topics}
    more = [r for r in bundle.topic_index if r.id not in saved][:40]
    if more:
        parts.append(
            "## More topics (titles only, open on Kaggle)\n\n"
            + render_topic_table([(r.url, r) for r in more])
        )
    if not bundle.topics and "discussions" in bundle.errors:
        parts.append(f"_Could not fetch discussions: {bundle.errors['discussions']}_")
    return "\n\n".join(parts) + "\n"


def render_notebook(nb: Notebook) -> str:
    flags = [x for x in (nb.language, nb.kernel_type) if x]
    if nb.enable_gpu:
        flags.append("GPU")
    if nb.enable_internet:
        flags.append("internet on")
    meta = f"by **{nb.author}** · ▲{nb.votes} · last run {_date(nb.last_run)} · {' · '.join(flags)}"
    notice = (
        "> Public Kaggle notebook, shown here for reference. Kaggle releases public notebooks "
        f"under Apache 2.0 by default. Keep the attribution when reusing code. Source: {nb.url}"
    )
    return f"# {nb.title}\n\n{meta}\n\n{notice}\n\n{nest_headings(nb.markdown, 2)}\n"


def render_code_index(bundle: Bundle, with_sources: bool = False) -> str:
    parts = [f"# Top public notebooks: {bundle.meta.title}", header(bundle)]
    if bundle.notebooks:
        head = "| Notebook | Author | ▲ | Last run | Notes |"
        rows = [head, "|---|---|---|---|---|"]
        for nb in bundle.notebooks:
            notes = ", ".join(x for x in (nb.language, "GPU" if nb.enable_gpu else "") if x)
            link = notebook_filename(nb)
            src = (
                f" ([source](notebooks/{nb.source_file}))"
                if with_sources and nb.source_file
                else ""
            )
            title = nb.title.replace("|", r"\|")
            rows.append(
                f"| [{title}]({link}){src} | {nb.author} | {nb.votes} | {_date(nb.last_run)} | {notes} |"
            )
        parts.append(
            "Sorted by votes. Kaggle Learn exercises are filtered out.\n\n" + "\n".join(rows)
        )
    elif "code" in bundle.errors:
        parts.append(f"_Could not fetch notebooks: {bundle.errors['code']}_")
    else:
        parts.append("_No public notebooks yet._")
    return "\n\n".join(parts) + "\n"


def render_leaderboard(bundle: Bundle) -> str:
    parts = [f"# Public leaderboard (top {len(bundle.leaderboard)})", header(bundle)]
    if bundle.leaderboard:
        rows = ["| # | Team | Score | Submitted |", "|---|---|---|---|"]
        rows += [
            f"| {e.rank} | {e.team.replace('|', '/')} | {e.score} | {_date(e.date)} |"
            for e in bundle.leaderboard
        ]
        parts.append("\n".join(rows))
        parts.append(
            "Public LB scores are computed on part of the test set; the private LB decides."
        )
    else:
        parts.append(f"_Not available: {bundle.errors.get('leaderboard', 'no entries')}_")
    return "\n\n".join(parts) + "\n"


def render_whats_new(bundle: Bundle) -> str:
    if not bundle.changes_since:
        return ""
    parts = [f"# What's new since {format_date(bundle.changes_since, relative=False)}"]
    new = bundle.changes.get("new_topics", [])
    active = bundle.changes.get("active_topics", [])
    parts.append(
        "## New topics\n\n" + (render_topic_table([(r.url, r) for r in new]) if new else "_None._")
    )
    parts.append(
        "## Topics with new comments\n\n"
        + (render_topic_table([(r.url, r) for r in active]) if active else "_None._")
    )
    return "\n\n".join(parts) + "\n"


# -- CONTEXT.md --------------------------------------------------------------------------------


def _fit_items(items: list[tuple[str, str]], budget: int) -> str:
    """Include items (label, text) until ``budget`` tokens are used; truncate each fairly."""
    if not items:
        return ""
    per_item = max(400, budget // len(items))
    out: list[str] = []
    used = 0
    for i, (link, text) in enumerate(items):
        room = min(per_item, budget - used)
        if room < 200:
            rest = "\n".join(f"- {link}" for link, _ in items[i:])
            out.append(f"_Not inlined (budget), see:_\n{rest}")
            break
        chunk = truncate(text, room, f"full text in {link}")
        used += estimate_tokens(chunk)
        out.append(chunk)
    return "\n\n---\n\n".join(out)


def render_context(bundle: Bundle, budget: int = 50_000, prefix: str = "") -> str:
    """Everything in one markdown file, fitted to ``budget`` tokens."""
    rules = bundle.page("rules")
    overview_body = "\n\n".join(
        f"### {p.name}\n\n{nest_headings(p.content, 4)}" for p in bundle.overview_pages()
    )
    data_body = nest_headings(render_data(bundle), 3)
    topic_items = [
        (f"{prefix}discussions/{topic_path(t)}", nest_headings(render_topic(t), 3))
        for t in bundle.topics
    ]
    code_items = [
        (f"{prefix}code/{notebook_filename(nb)}", nest_headings(render_notebook(nb), 3))
        for nb in bundle.notebooks
    ]
    lb_body = nest_headings(render_leaderboard(bundle), 2) if bundle.leaderboard else ""

    texts = {
        "overview": overview_body,
        "rules": nest_headings(rules.content, 3) if rules else "",
        "data": data_body,
        "discussions": "\n\n".join(t for _, t in topic_items),
        "code": "\n\n".join(t for _, t in code_items),
        "leaderboard": lb_body,
    }
    top = "\n\n".join(
        [
            f"# {bundle.meta.title}: competition context",
            header(bundle),
            "## Key facts\n\n" + render_facts(bundle),
        ]
    )
    alloc = allocate(
        {k: estimate_tokens(v) for k, v in texts.items()},
        CONTEXT_SHARES,
        max(1000, budget - estimate_tokens(top)),
    )
    sections = [top]
    if texts["overview"]:
        sections.append(
            "## Overview\n\n"
            + truncate(texts["overview"], alloc["overview"], f"see {prefix}overview/")
        )
    if texts["rules"]:
        sections.append(
            "## Rules\n\n" + truncate(texts["rules"], alloc["rules"], f"see {prefix}rules/rules.md")
        )
    sections.append(
        "## Data\n\n" + truncate(texts["data"], alloc["data"], f"see {prefix}data/README.md")
    )
    if topic_items:
        sections.append("## Discussions\n\n" + _fit_items(topic_items, alloc["discussions"]))
    if code_items:
        sections.append("## Top public notebooks\n\n" + _fit_items(code_items, alloc["code"]))
    if lb_body:
        sections.append(truncate(lb_body, alloc["leaderboard"]))
    return "\n\n".join(sections) + "\n"


# -- agent guide (CLAUDE.md / AGENTS.md / SKILL.md body) ----------------------------------------


def render_file_map(bundle: Bundle, prefix: str = "", workspace: bool = True) -> str:
    rows = ["| When you need… | Read |", "|---|---|"]
    rows.append(f"| Goal, evaluation, timeline, prizes | `{prefix}overview/` |")
    rows.append(
        f"| Rules: external data, pretrained models, teams, submissions | `{prefix}rules/rules.md` |"
    )
    rows.append(f"| Data files, columns, how to download | `{prefix}data/README.md` |")
    if any(t.is_solution for t in bundle.topics):
        rows.append(f"| Winning / top solution write-ups | `{prefix}discussions/solutions/` |")
    rows.append(
        f"| Community discussion (top topics + comments) | `{prefix}discussions/INDEX.md` |"
    )
    rows.append(f"| Top public notebooks (code) | `{prefix}code/INDEX.md` |")
    if bundle.leaderboard:
        rows.append(f"| Public leaderboard snapshot | `{prefix}overview/leaderboard.md` |")
    if bundle.changes_since:
        rows.append(f"| What changed since the last snapshot | `{prefix}WHATS_NEW.md` |")
    if workspace:
        rows.append("| Everything in one file | `CONTEXT.md` |")
    return "\n".join(rows)


def render_agent_guide(bundle: Bundle) -> str:
    """CLAUDE.md / AGENTS.md for a workspace folder. Kept short: it is loaded on every turn."""
    slug = bundle.slug
    parts = [
        f"# {bundle.meta.title}: Kaggle competition workspace",
        header(bundle) + " Refresh with `kctx refresh` from this folder.",
        "## Key facts\n\n" + render_facts(bundle),
        "## Where things are\n\n" + render_file_map(bundle),
        "\n".join(
            [
                "## Working here",
                "",
                f"- Raw data is **not** included. Download it into `data/raw/` with `bash data/download.sh` "
                f"after accepting the rules at {competition_url(slug, 'rules')}.",
                "- Check `rules/rules.md` before suggesting external data, pretrained models or extra "
                "submissions. When a rule matters, quote it.",
                "- Code in `code/` comes from public Kaggle notebooks. Keep the author attribution "
                "when you reuse it.",
                "- Discussions and notebooks are a snapshot. Run `kctx refresh` when the competition is active.",
            ]
        ),
    ]
    return "\n\n".join(parts) + "\n"
