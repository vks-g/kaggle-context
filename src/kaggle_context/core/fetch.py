"""Fetch everything about one competition into a ``Bundle``.

Each section is fetched independently: a failure in one (say, the leaderboard is
private) is recorded in ``bundle.errors`` and the rest still come through.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaggle_context import __version__
from kaggle_context.core.client import KaggleError, KaggleSource, NotFoundError
from kaggle_context.core.models import (
    SECTIONS,
    Bundle,
    Comment,
    CompetitionMeta,
    DataFile,
    LeaderboardEntry,
    Notebook,
    Page,
    Topic,
    TopicRef,
)
from kaggle_context.core.slug import competition_url
from kaggle_context.render.html2md import to_markdown
from kaggle_context.render.notebook import notebook_to_markdown

# (section, status, detail); status is one of start | progress | done | error | skip
Progress = Callable[[str, str, str], None]

SOLUTION_RE = re.compile(
    r"(\b\d{1,4}(st|nd|rd|th)\b|\b(first|second|third|gold|silver|bronze)\b|\btop[- ]?\d+\b|#\d+)"
    r".{0,40}\b(place|solution|approach|write-?up)\b"
    r"|\bsolution\b.{0,25}\b\d{1,4}(st|nd|rd|th)\b"
    r"|\bsolution\s+(write-?up|summary|overview)\b",
    re.IGNORECASE,
)
MAX_SOLUTIONS = 10
MAX_PINNED = 3
MAX_REPLIES = 3
TOPIC_SCAN_PAGES = 3  # 20 topics per page; scanned to find solution write-ups


@dataclass
class FetchOptions:
    sections: tuple[str, ...] = SECTIONS
    discussions: int = 15
    comments: int = 10
    notebooks: int = 5
    discussion_sort: str = "top"
    leaderboard: int = 20
    workers: int = 4
    extra: dict[str, Any] = field(default_factory=dict)


class CompetitionNotFound(KaggleError):
    pass


def _noop(section: str, status: str, detail: str) -> None:
    pass


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def is_solution_title(title: str) -> bool:
    return bool(SOLUTION_RE.search(title))


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


# -- metadata ------------------------------------------------------------------------


def meta_from_api(slug: str, comp: dict[str, Any]) -> CompetitionMeta:
    return CompetitionMeta(
        slug=slug,
        title=comp.get("title") or slug,
        url=comp.get("url") or competition_url(slug),
        subtitle=comp.get("description") or "",
        category=comp.get("category") or "",
        organization=comp.get("organizationName") or comp.get("hostName") or "",
        reward=comp.get("reward") or "",
        evaluation_metric=comp.get("evaluationMetric") or "",
        deadline=comp.get("deadline") or "",
        merger_deadline=comp.get("mergerDeadline") or "",
        enabled_date=comp.get("enabledDate") or "",
        team_count=_int(comp.get("teamCount")),
        max_daily_submissions=_int(comp.get("maxDailySubmissions")),
        max_team_size=_int(comp.get("maxTeamSize")),
        is_code_competition=bool(comp.get("isKernelsSubmissionsOnly")),
        tags=[t.get("name", "") for t in comp.get("tags") or [] if t.get("name")],
    )


def fetch_meta(client: KaggleSource, slug: str) -> CompetitionMeta:
    comp = client.competition(slug)
    if comp is not None:
        return meta_from_api(slug, comp)
    # Search can miss some competitions; the pages call is the authoritative existence check.
    try:
        client.pages(slug)
    except NotFoundError as exc:
        raise CompetitionNotFound(f"No Kaggle competition named '{slug}'.") from exc
    return CompetitionMeta(
        slug=slug, title=slug.replace("-", " ").title(), url=competition_url(slug)
    )


# -- sections --------------------------------------------------------------------------


def fetch_pages(client: KaggleSource, slug: str) -> list[Page]:
    return [
        Page(name=p.get("name", ""), content=to_markdown(p.get("content")))
        for p in client.pages(slug)
        if p.get("content")
    ]


def fetch_files(client: KaggleSource, slug: str) -> list[DataFile]:
    return [
        DataFile(
            name=f.get("name", ""),
            size=_int(f.get("totalBytes") or f.get("size")),
            created=f.get("creationDate") or "",
        )
        for f in client.files(slug)
    ]


def _comment(d: dict[str, Any], with_replies: bool = True) -> Comment:
    replies = sorted(d.get("replies") or [], key=lambda r: _int(r.get("votes")), reverse=True)
    return Comment(
        id=_int(d.get("id")),
        author=d.get("authorName") or "",
        date=d.get("postDate") or "",
        votes=_int(d.get("votes")),
        content=to_markdown(d.get("rawMarkdown") or d.get("content")),
        replies=[_comment(r, with_replies=False) for r in replies[:MAX_REPLIES]]
        if with_replies
        else [],
    )


def is_substantive(comment: dict[str, Any]) -> bool:
    """Drop 'Great work!'-style comments unless people upvoted them or they have replies."""
    text = re.sub(r"<[^>]+>", "", comment.get("rawMarkdown") or comment.get("content") or "")
    return (
        len(text.strip()) >= 60 or _int(comment.get("votes")) >= 3 or bool(comment.get("replies"))
    )


def topic_ref(d: dict[str, Any], slug: str) -> TopicRef:
    tid = _int(d.get("id"))
    return TopicRef(
        id=tid,
        title=d.get("title") or "",
        url=competition_url(slug, "discussion", str(tid)),
        votes=_int(d.get("votes")),
        comment_count=_int(d.get("commentCount")),
        date=d.get("postDate") or "",
        last_comment_date=d.get("lastCommentPostDate") or d.get("lastCommentDate") or "",
        is_sticky=bool(d.get("isSticky")),
    )


def list_topics(client: KaggleSource, slug: str, sort_by: str, pages: int) -> list[TopicRef]:
    refs: list[TopicRef] = []
    seen: set[int] = set()
    for page in range(1, pages + 1):
        resp = client.topics(slug, sort_by=sort_by, page=page)
        batch = resp.get("topics") or []
        for t in batch:
            ref = topic_ref(t, slug)
            if ref.id not in seen:
                seen.add(ref.id)
                refs.append(ref)
        total = _int(resp.get("totalCount"))
        if not batch or (total and len(refs) >= total):
            break
    return refs


def select_topics(refs: list[TopicRef], limit: int) -> list[TopicRef]:
    """Solution write-ups first, then a few pinned host posts, then the rest in listing order."""
    solutions = [r for r in refs if is_solution_title(r.title)][:MAX_SOLUTIONS]
    chosen = {r.id for r in solutions}
    pinned = [r for r in refs if r.is_sticky and r.id not in chosen][:MAX_PINNED]
    chosen |= {r.id for r in pinned}
    rest = [r for r in refs if r.id not in chosen]
    return solutions + pinned + rest[: max(0, limit - len(pinned))]


def fetch_topic(client: KaggleSource, ref: TopicRef, max_comments: int) -> Topic:
    data = client.topic(ref.id, page_size=200)
    t = data["topic"]
    comments = sorted(
        (c for c in data["comments"] if is_substantive(c)),
        key=lambda c: _int(c.get("votes")),
        reverse=True,
    )
    return Topic(
        id=ref.id,
        title=t.get("title") or ref.title,
        url=ref.url,
        author=t.get("authorName") or "",
        date=t.get("postDate") or ref.date,
        votes=_int(t.get("votes")) or ref.votes,
        comment_count=_int(t.get("commentCount")) or ref.comment_count,
        is_sticky=ref.is_sticky,
        is_solution=is_solution_title(ref.title),
        content=to_markdown(t.get("content")),
        comments=[_comment(c) for c in comments[:max_comments]],
    )


def is_learn_exercise(k: dict[str, Any]) -> bool:
    """Kaggle Learn exercises attach themselves to Titanic & co. and dwarf real notebooks' votes."""
    title = (k.get("title") or "").lower()
    return title.startswith("exercise:") or "/exercise-" in (k.get("ref") or "")


def fetch_notebook(client: KaggleSource, k: dict[str, Any], dest: Path) -> Notebook:
    ref = k["ref"]
    meta = client.pull_kernel(ref, dest)
    source = dest / meta["local_file"]
    return Notebook(
        ref=ref,
        title=k.get("title") or meta.get("title") or ref,
        author=k.get("author") or ref.split("/")[0],
        votes=_int(k.get("totalVotes")),
        url=f"https://www.kaggle.com/code/{ref}",
        last_run=k.get("lastRunTime") or "",
        language=meta.get("language") or "",
        kernel_type=meta.get("kernel_type") or "",
        enable_gpu=bool(meta.get("enable_gpu")),
        enable_internet=bool(meta.get("enable_internet")),
        source_file=source.name,
        markdown=notebook_to_markdown(source),
    )


def fetch_leaderboard(client: KaggleSource, slug: str, limit: int) -> list[LeaderboardEntry]:
    return [
        LeaderboardEntry(
            rank=i,
            team=r.get("teamName") or "",
            score=str(r.get("score") or ""),
            date=r.get("submissionDate") or "",
        )
        for i, r in enumerate(client.leaderboard(slug, page_size=limit)[:limit], start=1)
    ]


# -- orchestration ---------------------------------------------------------------------


def _counter(section: str, total: int, noun: str, progress: Progress) -> Callable[[], None]:
    lock = threading.Lock()
    done = 0

    def tick() -> None:
        nonlocal done
        with lock:
            done += 1
            progress(section, "progress", f"{done}/{total} {noun}")

    return tick


def fetch_bundle(
    client: KaggleSource,
    slug: str,
    workdir: Path,
    options: FetchOptions | None = None,
    progress: Progress = _noop,
) -> Bundle:
    """Fetch every requested section. ``workdir`` receives pulled notebook sources."""
    opts = options or FetchOptions()
    progress("overview", "start", "Looking up competition")
    bundle = Bundle(meta=fetch_meta(client, slug), fetched_at=now_iso(), tool_version=__version__)
    wanted = set(opts.sections)

    def run(section: str, fn: Callable[[], str]) -> None:
        if section not in wanted:
            progress(section, "skip", "")
            return
        progress(section, "start", "")
        try:
            progress(section, "done", fn())
        except KaggleError as exc:
            bundle.errors[section] = str(exc)
            progress(section, "error", str(exc))
        except Exception as exc:  # keep going: one broken section must not sink the rest
            bundle.errors[section] = f"{type(exc).__name__}: {exc}"
            progress(section, "error", bundle.errors[section])

    def pages() -> str:
        bundle.pages = fetch_pages(client, slug)
        return f"{len(bundle.pages)} pages"

    def files() -> str:
        bundle.files = fetch_files(client, slug)
        return f"{len(bundle.files)} files"

    def discussions() -> str:
        scan = max(TOPIC_SCAN_PAGES, -(-opts.discussions // 20))
        bundle.topic_index = list_topics(client, slug, opts.discussion_sort, scan)
        chosen = select_topics(bundle.topic_index, opts.discussions)
        tick = _counter("discussions", len(chosen), "topics", progress)

        def one(ref: TopicRef) -> Topic | None:
            try:
                return fetch_topic(client, ref, opts.comments)
            except KaggleError:
                return None
            finally:
                tick()

        with ThreadPoolExecutor(max_workers=opts.workers) as pool:
            bundle.topics = [t for t in pool.map(one, chosen) if t is not None]
        solutions = sum(t.is_solution for t in bundle.topics)
        return f"{len(bundle.topics)} topics ({solutions} solution write-ups)"

    def code() -> str:
        listing = client.kernels(slug, page_size=min(100, opts.notebooks * 3 + 5))
        chosen = [k for k in listing if not is_learn_exercise(k)][: opts.notebooks]
        dest = workdir / "notebooks"
        tick = _counter("code", len(chosen), "notebooks", progress)

        def one(k: dict[str, Any]) -> Notebook | None:
            try:
                return fetch_notebook(client, k, dest)
            except KaggleError:
                return None
            finally:
                tick()

        with ThreadPoolExecutor(max_workers=opts.workers) as pool:
            bundle.notebooks = [n for n in pool.map(one, chosen) if n is not None]
        return f"{len(bundle.notebooks)} notebooks"

    def leaderboard() -> str:
        bundle.leaderboard = fetch_leaderboard(client, slug, opts.leaderboard)
        return f"top {len(bundle.leaderboard)}"

    # Overview, rules and the data description all come from one pages call.
    if wanted & {"overview", "rules", "data"}:
        wanted.add("overview")
        run("overview", pages)
    if "rules" in wanted:
        if "overview" in bundle.errors:
            bundle.errors["rules"] = bundle.errors["overview"]
            progress("rules", "error", bundle.errors["rules"])
        else:
            progress("rules", "done", "found" if bundle.page("rules") else "no rules page")
    run("data", files)
    run("discussions", discussions)
    run("code", code)
    run("leaderboard", leaderboard)
    return bundle


# -- what's new --------------------------------------------------------------------------


def whats_new(client: KaggleSource, slug: str, since: str) -> dict[str, list[TopicRef]]:
    """New topics and recently active topics since ``since`` (ISO timestamp)."""
    cutoff = _parse_time(since)
    new = [r for r in list_topics(client, slug, "new", 2) if _parse_time(r.date) > cutoff]
    new_ids = {r.id for r in new}
    active = [
        r
        for r in list_topics(client, slug, "recent", 2)
        if r.id not in new_ids and _parse_time(r.last_comment_date) > cutoff
    ]
    return {"new_topics": new, "active_topics": active}


def _parse_time(value: str) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
