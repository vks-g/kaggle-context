"""Local stdio MCP server exposing competition context as tools, resources and a prompt.

Reads from the on-disk cache (filled by ``kctx`` / ``kctx fetch``) and fetches on demand
for competitions it hasn't seen. Everything runs on the user's machine with their own
Kaggle credentials, so there is nothing to host.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Callable
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from kaggle_context import __version__
from kaggle_context.core.budget import paginate
from kaggle_context.core.cache import bundle_dir, get_bundle, iter_cached, load_bundle
from kaggle_context.core.client import KaggleClient, KaggleError, KaggleSource
from kaggle_context.core.fetch import fetch_notebook, fetch_topic, topic_ref, whats_new
from kaggle_context.core.models import Bundle, Topic
from kaggle_context.core.slug import competition_url, parse_competition
from kaggle_context.render import sections as r
from kaggle_context.render.facts import format_date

PART_TOKENS = 12_000  # keep single tool results well under Claude Code's MCP output limit

Section = Literal["overview", "evaluation", "rules", "data", "leaderboard", "timeline", "prizes"]

INSTRUCTIONS = """\
Context for Kaggle competitions: overview, evaluation, rules, data description, top
discussions (including winning solution write-ups) and top public notebooks.
Start with get_brief. Quote rules from get_section('rules') instead of guessing.
Long results come in parts: call again with part=2, 3, …
"""


def build_server(
    default_competition: str | None = None,
    client_factory: Callable[[], KaggleSource] = KaggleClient,
) -> MCPServer:
    server = MCPServer(name="kaggle-context", instructions=INSTRUCTIONS, version=__version__)
    clients: list[KaggleSource] = []

    def client() -> KaggleSource:
        if not clients:
            clients.append(client_factory())
        return clients[0]

    def slug_for(competition: str | None) -> str:
        if competition:
            try:
                return parse_competition(competition)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
        if default_competition:
            return default_competition
        cached = sorted(iter_cached(), key=lambda b: b.fetched_at, reverse=True)
        if cached:
            return cached[0].slug
        raise ToolError(
            "No competition given and none fetched yet. Pass competition='<Kaggle URL or slug>'."
        )

    def bundle_for(competition: str | None) -> Bundle:
        slug = slug_for(competition)
        bundle = load_bundle(slug)
        if bundle is None:
            try:
                bundle = get_bundle(client(), slug)
            except KaggleError as exc:
                raise ToolError(f"Could not fetch '{slug}' from Kaggle: {exc}") from exc
        return bundle

    # -- tools ------------------------------------------------------------------------------

    @server.tool()
    def list_competitions() -> str:
        """List competitions already fetched on this machine (the default is marked)."""
        rows = ["| Competition | Slug | Fetched |", "|---|---|---|"]
        for b in sorted(iter_cached(), key=lambda b: b.fetched_at, reverse=True):
            mark = " (default)" if b.slug == default_competition else ""
            rows.append(
                f"| {b.meta.title}{mark} | `{b.slug}` | {format_date(b.fetched_at, relative=False)} |"
            )
        if len(rows) == 2:
            return "Nothing fetched yet. Call fetch_competition with a Kaggle competition URL."
        return "\n".join(rows)

    @server.tool()
    def fetch_competition(competition: str, refresh: bool = False) -> str:
        """Fetch (or refresh) a competition from Kaggle by URL or slug, then return its brief."""
        slug = slug_for(competition)
        try:
            bundle = get_bundle(client(), slug, refresh=refresh)
        except KaggleError as exc:
            raise ToolError(str(exc)) from exc
        return brief(bundle)

    @server.tool()
    def get_brief(competition: str | None = None) -> str:
        """Key facts (metric, deadlines, limits, submission format, external-data rule) and what else is available."""
        return brief(bundle_for(competition))

    @server.tool()
    def get_section(section: Section, competition: str | None = None, part: int = 1) -> str:
        """Full text of one section: overview, evaluation, rules, data, leaderboard, timeline or prizes."""
        bundle = bundle_for(competition)
        if section == "overview":
            text = r.render_overview(bundle)
        elif section == "rules":
            text = r.render_rules(bundle)
        elif section == "data":
            text = r.render_data(bundle)
        elif section == "leaderboard":
            text = r.render_leaderboard(bundle)
        else:
            page = bundle.page(section) or next(
                (p for p in bundle.pages if section in p.name.lower()), None
            )
            if page is None:
                names = ", ".join(p.name for p in bundle.pages)
                raise ToolError(f"No '{section}' page. Available pages: {names}")
            text = r.render_page(bundle, page)
        return paginate(text, part, PART_TOKENS)

    @server.tool()
    def list_discussions(competition: str | None = None, solutions_only: bool = False) -> str:
        """Saved discussion topics (solution write-ups first) with ids for get_discussion."""
        bundle = bundle_for(competition)
        topics = [t for t in bundle.topics if t.is_solution or not solutions_only]
        if not topics:
            return "No solution write-ups found." if solutions_only else "No discussions saved."
        rows = ["| id | Topic | ▲ | Comments | Date |", "|---|---|---|---|---|"]
        for t in topics:
            tag = " 🏆" if t.is_solution else ""
            rows.append(
                f"| {t.id} | {t.title}{tag} | {t.votes} | {t.comment_count} | {t.date[:10]} |"
            )
        more = len(bundle.topic_index) - len(topics)
        tail = (
            f"\n\n{more} more topics are listed on Kaggle; search_discussions searches titles too."
            if more > 0
            else ""
        )
        return "\n".join(rows) + tail

    @server.tool()
    def search_discussions(query: str, competition: str | None = None, limit: int = 10) -> str:
        """Keyword search over saved topics and comments, plus titles of other topics."""
        bundle = bundle_for(competition)
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 1]
        if not terms:
            raise ToolError("Give at least one search word.")
        hits: list[tuple[int, str]] = []
        saved = set()
        for t in bundle.topics:
            saved.add(t.id)
            text = _topic_text(t).lower()
            score = sum(text.count(term) for term in terms) + 5 * sum(
                term in t.title.lower() for term in terms
            )
            if score:
                hits.append(
                    (
                        score,
                        f"- **{t.title}** (id {t.id}, ▲{t.votes}): {_snippet(_topic_text(t), terms)}",
                    )
                )
        for ref in bundle.topic_index:
            if ref.id not in saved and (score := sum(term in ref.title.lower() for term in terms)):
                hits.append((score, f"- {ref.title} (id {ref.id}, ▲{ref.votes}, title match only)"))
        if not hits:
            return f"No matches for {query!r}."
        hits.sort(key=lambda h: h[0], reverse=True)
        return "\n".join(h for _, h in hits[:limit])

    @server.tool()
    def get_discussion(topic_id: int, competition: str | None = None, part: int = 1) -> str:
        """One topic with its opening post and top comments. Fetches live if not saved."""
        bundle = bundle_for(competition)
        topic = next((t for t in bundle.topics if t.id == topic_id), None)
        if topic is None:
            ref = next((x for x in bundle.topic_index if x.id == topic_id), None)
            ref = ref or topic_ref({"id": topic_id}, bundle.slug)
            try:
                topic = fetch_topic(client(), ref, max_comments=15)
            except KaggleError as exc:
                raise ToolError(f"Could not fetch topic {topic_id}: {exc}") from exc
        return paginate(r.render_topic(topic), part, PART_TOKENS)

    @server.tool()
    def list_top_notebooks(competition: str | None = None) -> str:
        """Top public notebooks by votes, with refs for get_notebook."""
        bundle = bundle_for(competition)
        if not bundle.notebooks:
            return "No notebooks saved."
        rows = ["| ref | Title | Author | ▲ | Notes |", "|---|---|---|---|---|"]
        for nb in bundle.notebooks:
            notes = ", ".join(x for x in (nb.language, "GPU" if nb.enable_gpu else "") if x)
            rows.append(f"| `{nb.ref}` | {nb.title} | {nb.author} | {nb.votes} | {notes} |")
        return "\n".join(rows)

    @server.tool()
    def get_notebook(ref: str, competition: str | None = None, part: int = 1) -> str:
        """A notebook's code and markdown (outputs stripped), with attribution. ref = owner/notebook."""
        bundle = bundle_for(competition)
        ref = ref.strip().removeprefix("https://www.kaggle.com/code/").strip("/")
        nb = next((n for n in bundle.notebooks if n.ref == ref), None)
        if nb is None:
            try:
                nb = fetch_notebook(client(), {"ref": ref}, bundle_dir(bundle.slug) / "notebooks")
            except KaggleError as exc:
                raise ToolError(f"Could not fetch notebook {ref}: {exc}") from exc
        return paginate(r.render_notebook(nb), part, PART_TOKENS)

    @server.tool()
    def get_whats_new(competition: str | None = None, since: str | None = None) -> str:
        """Live: topics created or commented on since `since` (ISO date). Defaults to the last fetch."""
        bundle = bundle_for(competition)
        cutoff = since or bundle.fetched_at
        try:
            changes = whats_new(client(), bundle.slug, cutoff)
        except KaggleError as exc:
            raise ToolError(str(exc)) from exc
        lines = [f"Since {format_date(cutoff, relative=False)}:"]
        for label, key in (
            ("New topics", "new_topics"),
            ("Topics with new comments", "active_topics"),
        ):
            refs = changes[key]
            lines.append(f"\n**{label}** ({len(refs)})")
            lines += [
                f"- {x.title} (id {x.id}, ▲{x.votes}, {x.comment_count} comments)"
                for x in refs[:25]
            ]
        return "\n".join(lines)

    # -- resources & prompt -------------------------------------------------------------------

    @server.resource(
        "kaggle://{competition}/{section}",
        name="competition-section",
        description="overview | rules | data | discussions | code | leaderboard | context",
        mime_type="text/markdown",
    )
    def section_resource(competition: str, section: str) -> str:
        bundle = load_bundle(competition)
        if bundle is None:
            raise ResourceError(f"'{competition}' has not been fetched yet.")
        renderers: dict[str, Callable[[Bundle], str]] = {
            "overview": r.render_overview,
            "rules": r.render_rules,
            "data": r.render_data,
            "discussions": r.render_discussions_index,
            "code": r.render_code_index,
            "leaderboard": r.render_leaderboard,
            "context": lambda b: r.render_context(b, 30_000),
        }
        if section not in renderers:
            raise ResourceError(f"Unknown section {section!r}; use one of {', '.join(renderers)}")
        return renderers[section](bundle)

    @server.prompt(
        name="start-competition",
        description="Load a Kaggle competition's key facts and plan the work.",
    )
    def start_competition(competition: str) -> str:
        bundle = bundle_for(competition)
        return (
            f"We're working on the Kaggle competition {bundle.meta.title} ({bundle.meta.url}).\n\n"
            f"{brief(bundle)}\n\n"
            "Using the kaggle-context tools, read the rules and any solution write-ups, then propose a "
            "validation strategy and a first baseline that fits the constraints above."
        )

    return server


def brief(bundle: Bundle) -> str:
    counts = (
        f"{len(bundle.pages)} pages, {len(bundle.files)} data files, {len(bundle.topics)} discussions "
        f"({sum(t.is_solution for t in bundle.topics)} solution write-ups), {len(bundle.notebooks)} notebooks"
    )
    errors = "".join(f"\n- {k}: {v}" for k, v in bundle.errors.items())
    return "\n\n".join(
        x
        for x in [
            f"# {bundle.meta.title}",
            f"Snapshot {format_date(bundle.fetched_at, relative=False)} · {counts}. Rules: {competition_url(bundle.slug, 'rules')}",
            r.render_facts(bundle),
            "Next: get_section('rules' | 'evaluation' | 'data'), list_discussions, list_top_notebooks, get_whats_new.",
            f"Sections that failed to fetch:{errors}" if errors else "",
        ]
        if x
    )


def _topic_text(t: Topic) -> str:
    parts = [t.title, t.content]
    for c in t.comments:
        parts.append(c.content)
        parts += [rep.content for rep in c.replies]
    return "\n".join(parts)


def _snippet(text: str, terms: list[str], width: int = 160) -> str:
    flat = re.sub(r"\s+", " ", text)
    low = flat.lower()
    pos = min((low.find(t) for t in terms if t in low), default=0)
    start = max(0, pos - width // 3)
    return ("…" if start else "") + flat[start : start + width].strip() + "…"


def run(default_competition: str | None = None) -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    slug = parse_competition(default_competition) if default_competition else None
    build_server(slug).run("stdio")
