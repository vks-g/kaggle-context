from __future__ import annotations

import pytest
from conftest import SLUG, FakeClient
from mcp.server.mcpserver.exceptions import ToolError

from kaggle_context.core.cache import get_bundle
from kaggle_context.core.fetch import FetchOptions
from kaggle_context.mcp_server import build_server


def text(result) -> str:
    return "\n".join(c.text for c in result.content)


@pytest.fixture
def server(cache, client: FakeClient):
    # Save only a few topics so some have to be fetched live.
    bundle = get_bundle(client, SLUG, FetchOptions(discussions=2))
    assert 6 not in {t.id for t in bundle.topics}
    return build_server(SLUG, client_factory=lambda: client)


async def test_tools_are_listed(server) -> None:
    names = {t.name for t in await server.list_tools()}
    assert names >= {
        "list_competitions",
        "fetch_competition",
        "get_brief",
        "get_section",
        "list_discussions",
        "search_discussions",
        "get_discussion",
        "list_top_notebooks",
        "get_notebook",
        "get_whats_new",
    }


async def test_brief_and_sections(server) -> None:
    brief = text(await server.call_tool("get_brief", {}))
    assert "Demo Competition" in brief and "AUC" in brief
    rules = text(await server.call_tool("get_section", {"section": "rules"}))
    assert "External Data" in rules
    evaluation = text(await server.call_tool("get_section", {"section": "evaluation"}))
    assert "id,target" in evaluation


async def test_missing_page_is_a_clean_tool_error(server) -> None:
    # ToolError reaches the model as an is_error result with this message
    with pytest.raises(ToolError, match="Available pages"):
        await server.call_tool("get_section", {"section": "prizes"})


async def test_discussions(server) -> None:
    listing = text(await server.call_tool("list_discussions", {"solutions_only": True}))
    assert "1st Place Solution" in listing and "Great EDA" not in listing
    hits = text(await server.call_tool("search_discussions", {"query": "GroupKFold"}))
    assert "GroupKFold" in hits
    title_only = text(await server.call_tool("search_discussions", {"query": "leak"}))
    assert "title match only" in title_only
    topic = text(await server.call_tool("get_discussion", {"topic_id": 3}))
    assert "Carol" in topic


async def test_unsaved_discussion_is_fetched_live(server, client: FakeClient) -> None:
    client.calls.clear()
    topic = text(await server.call_tool("get_discussion", {"topic_id": 6}))
    assert "Data leak?" in topic and "topic" in client.calls


async def test_notebooks(server) -> None:
    listing = text(await server.call_tool("list_top_notebooks", {}))
    assert "alice/strong-baseline" in listing and "exercise" not in listing
    nb = text(
        await server.call_tool(
            "get_notebook", {"ref": "https://www.kaggle.com/code/alice/strong-baseline"}
        )
    )
    assert "import pandas" in nb and "Apache 2.0" in nb


async def test_whats_new_is_live(server, client: FakeClient) -> None:
    client.new_topics = [
        {
            "id": 77,
            "title": "Host update: new test set",
            "postDate": "2999-01-01T00:00:00Z",
            "lastCommentPostDate": "2999-01-01T00:00:00Z",
            "commentCount": 0,
            "votes": 9,
        }
    ]
    out = text(await server.call_tool("get_whats_new", {}))
    assert "Host update" in out


async def test_competition_argument_accepts_urls(server) -> None:
    out = text(
        await server.call_tool(
            "get_brief", {"competition": f"https://www.kaggle.com/competitions/{SLUG}/data"}
        )
    )
    assert "Demo Competition" in out


async def test_resource_and_prompt(server) -> None:
    contents = list(await server.read_resource(f"kaggle://{SLUG}/rules"))
    assert "External Data" in contents[0].content
    prompt = await server.get_prompt("start-competition", {"competition": SLUG})
    assert "validation strategy" in str(prompt)
