from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import SLUG, FakeClient

from kaggle_context.core.budget import allocate, estimate_tokens, paginate, truncate
from kaggle_context.core.cache import get_bundle, load_bundle
from kaggle_context.core.client import ForbiddenError, NotFoundError
from kaggle_context.core.fetch import (
    CompetitionNotFound,
    FetchOptions,
    fetch_bundle,
    is_solution_title,
)
from kaggle_context.core.models import Bundle
from kaggle_context.core.slug import parse_competition
from kaggle_context.render.html2md import nest_headings, to_markdown
from kaggle_context.render.notebook import ipynb_to_markdown

# -- slug ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "titanic",
        "https://www.kaggle.com/competitions/titanic",
        "https://www.kaggle.com/competitions/titanic/overview",
        "https://www.kaggle.com/competitions/titanic/discussion/123?sort=hotness",
        "www.kaggle.com/competitions/titanic",
        "kaggle.com/c/titanic/data",
        "  'Titanic'  ",
    ],
)
def test_parse_competition_accepts_urls_and_slugs(value: str) -> None:
    assert parse_competition(value) == "titanic"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "https://example.com/competitions/titanic",
        "https://www.kaggle.com/datasets/foo/bar",
        "bad slug!",
    ],
)
def test_parse_competition_rejects_garbage(value: str) -> None:
    with pytest.raises(ValueError):
        parse_competition(value)


# -- markdown ------------------------------------------------------------------------------


def test_to_markdown_converts_html_and_keeps_markdown() -> None:
    assert to_markdown("<p>Hello <strong>world</strong></p><p>x_y</p>") == "Hello **world**\n\nx_y"
    md = "## Title\n\nsome_var * 2"
    assert to_markdown(md) == md


def test_nest_headings_keeps_structure_and_ignores_code() -> None:
    md = "### A\ntext\n#### B\n```\n# not a heading\n```"
    assert nest_headings(md, 2) == "## A\ntext\n### B\n```\n# not a heading\n```"
    assert nest_headings("no headings", 3) == "no headings"


def test_ipynb_drops_outputs_and_empty_cells() -> None:
    nb = (
        '{"metadata":{"kernelspec":{"language":"python"}},"cells":['
        '{"cell_type":"code","source":["x = 1"],"outputs":[{"text":"SECRET"}]},'
        '{"cell_type":"markdown","source":""}]}'
    )
    out = ipynb_to_markdown(nb)
    assert out == "```python\nx = 1\n```"


# -- budget --------------------------------------------------------------------------------


def test_truncate_closes_code_fence_and_notes() -> None:
    text = "intro\n```python\n" + "x = 1\n" * 500 + "```\n"
    out = truncate(text, 50, "see file.md")
    assert estimate_tokens(out) < 80
    assert out.count("```") % 2 == 0
    assert out.endswith("…truncated — see file.md")


def test_allocate_gives_leftovers_to_hungry_sections() -> None:
    alloc = allocate({"small": 10, "big": 10_000, "empty": 0}, {"small": 0.5, "big": 0.5}, 1_000)
    assert alloc["small"] == 10
    assert alloc["big"] == 990
    assert alloc["empty"] == 0


def test_paginate_splits_and_points_to_next_part() -> None:
    text = "\n".join(f"line {i}" for i in range(2000))
    first = paginate(text, 1, 500)
    assert "call again with part=2" in first
    last = paginate(text, 99, 500)
    assert last.rstrip().endswith("]") and "call again" not in last
    assert paginate("short", 1, 500) == "short"


# -- fetch ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("1st Place Solution", True),
        ("Our 12th place write-up", True),
        ("Gold medal approach (LB 0.91)", True),
        ("Solution summary", True),
        ("Great EDA thread", False),
        ("Validation strategy?", False),
    ],
)
def test_solution_titles(title: str, expected: bool) -> None:
    assert is_solution_title(title) is expected


def test_fetch_bundle_collects_every_section(tmp_path, client: FakeClient) -> None:
    b = fetch_bundle(client, SLUG, tmp_path, FetchOptions(discussions=3, notebooks=2))
    assert b.meta.title == "Demo Competition"
    assert b.meta.team_count == 1234 and b.meta.is_code_competition
    assert {p.name for p in b.pages} >= {"Description", "Evaluation", "rules", "data-description"}
    assert "Empty page" not in {p.name for p in b.pages}
    assert [f.size for f in b.files] == [2048000, 1024]
    # solutions first, then the sticky host post, then the rest in listing order
    assert [t.id for t in b.topics][:3] == [3, 5, 1]
    assert b.topics[0].is_solution and b.topics[0].title.startswith("1st Place")
    assert len(b.topic_index) == 6
    # the Kaggle Learn exercise is filtered; notebooks keep vote order
    assert [n.ref for n in b.notebooks] == ["alice/strong-baseline", "bob/eda"]
    assert "HUGE OUTPUT" not in b.notebooks[0].markdown
    assert [e.rank for e in b.leaderboard] == [1, 2]
    assert b.errors == {}


def test_fetch_topic_drops_fluff_and_sorts_comments(tmp_path, client: FakeClient) -> None:
    b = fetch_bundle(client, SLUG, tmp_path, FetchOptions(sections=("discussions",)))
    topic = b.topics[0]
    assert [c.author for c in topic.comments] == ["Carol"]  # "Great!" dropped
    assert topic.comments[0].votes == 25
    assert [r.author for r in topic.comments[0].replies] == ["Dan"]
    assert topic.comments[0].replies[0].replies == []  # depth capped
    assert "Opening **post** body." in topic.content


def test_section_failures_are_isolated(tmp_path, client: FakeClient) -> None:
    client.fail["leaderboard"] = ForbiddenError("private")
    client.fail["files"] = ForbiddenError("accept the rules")
    events: list[tuple[str, str]] = []
    b = fetch_bundle(client, SLUG, tmp_path, progress=lambda s, st, d: events.append((s, st)))
    assert set(b.errors) == {"leaderboard", "data"}
    assert b.topics and b.notebooks and b.pages
    assert ("leaderboard", "error") in events and ("code", "done") in events


def test_only_requested_sections_are_fetched(tmp_path, client: FakeClient) -> None:
    fetch_bundle(client, SLUG, tmp_path, FetchOptions(sections=("rules",)))
    assert "kernels" not in client.calls and "topics" not in client.calls
    assert "pages" in client.calls


def test_meta_falls_back_when_search_misses(tmp_path, client: FakeClient) -> None:
    client.search_hit = False
    b = fetch_bundle(client, SLUG, tmp_path, FetchOptions(sections=()))
    assert b.meta.title == "Demo Comp"


def test_unknown_competition_raises(tmp_path, client: FakeClient) -> None:
    with pytest.raises(CompetitionNotFound):
        fetch_bundle(client, "nope", tmp_path)


def test_notfound_is_a_kaggle_error() -> None:
    assert issubclass(NotFoundError, Exception)


# -- cache ---------------------------------------------------------------------------------


def test_bundle_roundtrips_through_json(bundle: Bundle) -> None:
    again = Bundle.from_dict(bundle.to_dict())
    assert again == bundle


def test_cache_reuses_fresh_bundle_and_refresh_records_changes(cache, client: FakeClient) -> None:
    first = get_bundle(client, SLUG)
    assert load_bundle(SLUG) == first
    client.calls.clear()
    assert get_bundle(client, SLUG) == first
    assert client.calls == []  # served from cache

    client.new_topics = [
        {
            "id": 99,
            "title": "New leak found",
            "postDate": "2999-01-01T00:00:00Z",
            "lastCommentPostDate": "2999-01-01T00:00:00Z",
            "commentCount": 1,
            "votes": 2,
        }
    ]
    second = get_bundle(client, SLUG, refresh=True)
    assert second.changes_since == first.fetched_at
    assert [r.id for r in second.changes["new_topics"]] == [99]
    assert (cache / SLUG / "notebooks").is_dir()
    assert not (cache / f"{SLUG}.staging").exists()


def test_stale_cache_is_refetched(cache, client: FakeClient) -> None:
    get_bundle(client, SLUG)
    client.calls.clear()
    get_bundle(client, SLUG, max_age=timedelta(seconds=0))
    assert "pages" in client.calls
