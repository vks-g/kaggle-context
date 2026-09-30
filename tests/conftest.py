"""Synthetic Kaggle API responses shaped like the real ones (see ``core/client.py``).

We don't commit recorded Kaggle content to a public repo, so the fixtures below are
hand-written but mirror the quirks seen live: int64 fields as strings, HTML content with
``rawMarkdown`` alongside, sticky topics, Kaggle Learn exercises in the kernel list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kctx.core.client import ForbiddenError, NotFoundError

SLUG = "demo-comp"

RULES_MD = """### One account per participant
You cannot sign up to Kaggle from multiple accounts.

### External Data and Tools
C. *External Data*. You may use data other than the Competition Data ("External Data") to develop and test your Submissions. However, you will ensure the External Data is publicly available and equally accessible to use by all participants.

### Winner obligations
Winners must deliver code.
"""

EVALUATION_HTML = """<h2>Goal</h2>
<p>Predict the <strong>target</strong> for each row.</p>
<h2>Submission File</h2>
<p>For each <code>id</code> in the test set, predict a probability.</p>
<pre><code>id,target
1,0.5
2,0.1</code></pre>
<h2>Timeline</h2>
<p>See the timeline page.</p>"""

CODE_REQ_MD = """## Code Requirements
Submissions must be made through Notebooks.
- CPU Notebook <= 9 hours run-time
- GPU Notebook <= 9 hours run-time
- Internet access disabled
- Submission file must be named submission.csv
"""


def _topic_list(page: int) -> list[dict[str, Any]]:
    if page == 1:
        return [
            {
                "id": 1,
                "title": "Official Discord",
                "commentCount": 3,
                "votes": 50,
                "postDate": "2026-01-01T00:00:00Z",
                "isSticky": True,
            },
            {
                "id": 2,
                "title": "Great EDA thread",
                "commentCount": 12,
                "votes": 40,
                "postDate": "2026-01-02T00:00:00Z",
                "lastCommentPostDate": "2026-02-01T00:00:00Z",
            },
            {
                "id": 3,
                "title": "1st Place Solution - stacking + pseudo labels",
                "commentCount": 30,
                "votes": 300,
                "postDate": "2026-03-01T00:00:00Z",
            },
            {
                "id": 4,
                "title": "Validation strategy?",
                "commentCount": 5,
                "votes": 20,
                "postDate": "2026-01-03T00:00:00Z",
            },
        ]
    if page == 2:
        return [
            {
                "id": 5,
                "title": "Our 12th place write-up",
                "commentCount": 2,
                "votes": 15,
                "postDate": "2026-03-02T00:00:00Z",
            },
            {
                "id": 6,
                "title": "Data leak?",
                "commentCount": 1,
                "votes": 5,
                "postDate": "2026-01-05T00:00:00Z",
            },
        ]
    return []


class FakeClient:
    """Implements the ``KaggleSource`` protocol from canned data."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.search_queries: list[str] = []
        self.search_results: list[dict[str, Any]] = []
        self.search_hit = True
        self.fail: dict[str, Exception] = {}
        self.new_topics: list[dict[str, Any]] = []

    def _maybe_fail(self, name: str) -> None:
        self.calls.append(name)
        if name in self.fail:
            raise self.fail[name]

    def search_competitions(
        self, query: str = "", group: str | None = None
    ) -> list[dict[str, Any]]:
        self._maybe_fail("search_competitions")
        self.search_queries.append(query)
        return self.search_results

    def competition(self, slug: str) -> dict[str, Any] | None:
        self._maybe_fail("competition")
        if slug != SLUG or not self.search_hit:
            return None
        return {
            "ref": f"https://www.kaggle.com/competitions/{SLUG}",
            "title": "Demo Competition",
            "url": f"https://www.kaggle.com/competitions/{SLUG}",
            "description": "Predict the target",
            "category": "Featured",
            "reward": "$10,000",
            "evaluationMetric": "AUC",
            "deadline": "2099-01-01T23:59:00Z",
            "mergerDeadline": "2098-12-25T23:59:00Z",
            "teamCount": "1234",
            "maxDailySubmissions": 5,
            "maxTeamSize": 5,
            "isKernelsSubmissionsOnly": True,
            "tags": [{"name": "tabular"}, {"name": "binary classification"}],
        }

    def pages(self, slug: str) -> list[dict[str, Any]]:
        self._maybe_fail("pages")
        if slug != SLUG:
            raise NotFoundError("Not found on Kaggle.")
        return [
            {"name": "Description", "content": "## Overview\nA **demo** competition."},
            {"name": "Evaluation", "content": EVALUATION_HTML},
            {"name": "rules", "content": RULES_MD},
            {
                "name": "data-description",
                "content": "<h3>Files</h3><p><b>train.csv</b> - training set</p>",
            },
            {"name": "Code Requirements", "content": CODE_REQ_MD},
            {"name": "Empty page", "content": ""},
        ]

    def files(self, slug: str) -> list[dict[str, Any]]:
        self._maybe_fail("files")
        return [
            {"name": "train.csv", "totalBytes": "2048000", "creationDate": "2026-01-01T00:00:00Z"},
            {"name": "test.csv", "totalBytes": 1024, "creationDate": "2026-01-01T00:00:00Z"},
        ]

    def topics(self, slug: str, sort_by: str = "top", page: int = 1) -> dict[str, Any]:
        self._maybe_fail("topics")
        if sort_by in ("new", "recent"):
            return {
                "topics": self.new_topics if page == 1 else [],
                "totalCount": len(self.new_topics),
            }
        return {"topics": _topic_list(page), "totalCount": 6}

    def topic(self, topic_id: int, page_size: int = 200) -> dict[str, Any]:
        self._maybe_fail("topic")
        listed = {t["id"]: t["title"] for t in _topic_list(1) + _topic_list(2)}
        return {
            "topic": {
                "id": topic_id,
                "title": listed.get(topic_id, f"Topic {topic_id}"),
                "authorName": "Alice",
                "votes": 10,
                "commentCount": 3,
                "postDate": "2026-01-02T00:00:00Z",
                "content": "<p>Opening <b>post</b> body.</p><p>Second paragraph.</p>",
            },
            "comments": [
                {
                    "id": "11",
                    "authorName": "Bob",
                    "votes": "1",
                    "postDate": "2026-01-03T00:00:00Z",
                    "content": "<p>Great!</p>",
                },
                {
                    "id": "12",
                    "authorName": "Carol",
                    "votes": "25",
                    "postDate": "2026-01-04T00:00:00Z",
                    "content": "<p>Use GroupKFold on user_id; random KFold leaks across users and inflates CV.</p>",
                    "replies": [
                        {
                            "id": "13",
                            "authorName": "Dan",
                            "votes": "4",
                            "postDate": "2026-01-05T00:00:00Z",
                            "content": "<p>Confirmed, CV now matches the LB.</p>",
                            "replies": [
                                {"id": "14", "authorName": "Eve", "votes": "1", "content": "deep"}
                            ],
                        },
                    ],
                },
            ],
        }

    def kernels(self, slug: str, page_size: int = 20) -> list[dict[str, Any]]:
        self._maybe_fail("kernels")
        return [
            {
                "ref": "learn/exercise-arithmetic",
                "title": "Exercise: Arithmetic",
                "author": "Kaggle Learn",
                "totalVotes": 999999,
            },
            {
                "ref": "alice/strong-baseline",
                "title": "Strong baseline",
                "author": "Alice",
                "totalVotes": 500,
                "lastRunTime": "2026-02-01T00:00:00Z",
            },
            {"ref": "bob/eda", "title": "EDA", "author": "Bob", "totalVotes": 300},
            {"ref": "carol/r-script", "title": "R script", "author": "Carol", "totalVotes": 100},
        ][:page_size]

    def pull_kernel(self, ref: str, dest: Path) -> dict[str, Any]:
        self._maybe_fail("pull_kernel")
        dest.mkdir(parents=True, exist_ok=True)
        if ref.endswith("r-script"):
            name = ref.replace("/", "__") + ".r"
            (dest / name).write_text("library(data.table)\nx <- fread('train.csv')\n")
            lang, ktype = "r", "script"
        else:
            name = ref.replace("/", "__") + ".ipynb"
            nb = {
                "metadata": {"language_info": {"name": "python"}},
                "cells": [
                    {"cell_type": "markdown", "source": ["# Baseline\n", "Simple model."]},
                    {
                        "cell_type": "code",
                        "source": "import pandas as pd\ndf = pd.read_csv('train.csv')",
                        "outputs": [{"output_type": "stream", "text": "HUGE OUTPUT"}],
                    },
                    {"cell_type": "code", "source": ""},
                ],
            }
            (dest / name).write_text(json.dumps(nb))
            lang, ktype = "python", "notebook"
        return {
            "id": ref,
            "title": ref,
            "language": lang,
            "kernel_type": ktype,
            "enable_gpu": True,
            "enable_internet": False,
            "competition_sources": [SLUG],
            "local_file": name,
        }

    def leaderboard(self, slug: str, page_size: int = 20) -> list[dict[str, Any]]:
        self._maybe_fail("leaderboard")
        return [
            {"teamName": "Team A", "score": "0.91", "submissionDate": "2026-02-01T00:00:00Z"},
            {"teamName": "Team B", "score": "0.90", "submissionDate": "2026-02-02T00:00:00Z"},
        ]


@pytest.fixture
def cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "cache"
    monkeypatch.setenv("KCTX_CACHE", str(root))
    return root


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def bundle(cache: Path, client: FakeClient):
    from kctx.core.cache import get_bundle

    return get_bundle(client, SLUG)


__all__ = ["SLUG", "FakeClient", "ForbiddenError"]
