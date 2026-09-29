"""Plain data model for everything we collect about a competition.

The whole bundle round-trips through JSON so it can be cached on disk and read back
by the exporters and the MCP server without touching the Kaggle API again.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SECTIONS = ("overview", "rules", "data", "discussions", "code", "leaderboard")


@dataclass
class CompetitionMeta:
    slug: str
    title: str
    url: str
    subtitle: str = ""
    category: str = ""
    organization: str = ""
    reward: str = ""
    evaluation_metric: str = ""
    deadline: str = ""
    merger_deadline: str = ""
    enabled_date: str = ""
    team_count: int = 0
    max_daily_submissions: int = 0
    max_team_size: int = 0
    is_code_competition: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class Page:
    name: str
    content: str  # markdown


@dataclass
class DataFile:
    name: str
    size: int
    created: str = ""


@dataclass
class Comment:
    id: int
    author: str
    date: str
    votes: int
    content: str  # markdown
    replies: list[Comment] = field(default_factory=list)


@dataclass
class Topic:
    id: int
    title: str
    url: str
    author: str = ""
    date: str = ""
    votes: int = 0
    comment_count: int = 0
    is_sticky: bool = False
    is_solution: bool = False
    content: str = ""  # markdown of the opening post
    comments: list[Comment] = field(default_factory=list)


@dataclass
class TopicRef:
    """A row from the topic listing: cheap to fetch, used for indexes and 'what's new'."""

    id: int
    title: str
    url: str
    votes: int = 0
    comment_count: int = 0
    date: str = ""
    last_comment_date: str = ""
    is_sticky: bool = False


@dataclass
class Notebook:
    ref: str  # owner/kernel-slug
    title: str
    author: str
    votes: int
    url: str
    last_run: str = ""
    language: str = ""
    kernel_type: str = ""
    enable_gpu: bool = False
    enable_internet: bool = False
    source_file: str = ""  # file name of the pulled source inside the cache's notebooks/ dir
    markdown: str = ""  # cleaned, outputs stripped


@dataclass
class LeaderboardEntry:
    rank: int
    team: str
    score: str
    date: str = ""


@dataclass
class Bundle:
    meta: CompetitionMeta
    fetched_at: str
    pages: list[Page] = field(default_factory=list)
    files: list[DataFile] = field(default_factory=list)
    topics: list[Topic] = field(default_factory=list)
    topic_index: list[TopicRef] = field(default_factory=list)
    notebooks: list[Notebook] = field(default_factory=list)
    leaderboard: list[LeaderboardEntry] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    tool_version: str = ""
    # Filled on refresh: topics created / commented on since the previous fetch.
    changes_since: str = ""
    changes: dict[str, list[TopicRef]] = field(default_factory=dict)

    @property
    def slug(self) -> str:
        return self.meta.slug

    def page(self, *names: str) -> Page | None:
        """First page whose name matches any of ``names`` (case-insensitive)."""
        wanted = {n.lower() for n in names}
        return next((p for p in self.pages if p.name.lower() in wanted), None)

    def overview_pages(self) -> list[Page]:
        """Every page except the ones with a dedicated section (rules, data)."""
        return [p for p in self.pages if p.name.lower() not in RULES_PAGES | DATA_PAGES]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Bundle:
        return cls(
            meta=CompetitionMeta(**d["meta"]),
            fetched_at=d["fetched_at"],
            pages=[Page(**p) for p in d.get("pages", [])],
            files=[DataFile(**f) for f in d.get("files", [])],
            topics=[_topic_from_dict(t) for t in d.get("topics", [])],
            topic_index=[TopicRef(**t) for t in d.get("topic_index", [])],
            notebooks=[Notebook(**n) for n in d.get("notebooks", [])],
            leaderboard=[LeaderboardEntry(**e) for e in d.get("leaderboard", [])],
            errors=d.get("errors", {}),
            tool_version=d.get("tool_version", ""),
            changes_since=d.get("changes_since", ""),
            changes={k: [TopicRef(**t) for t in v] for k, v in (d.get("changes") or {}).items()},
        )


RULES_PAGES = {"rules"}
DATA_PAGES = {"data-description", "data", "data description"}


def _comment_from_dict(d: dict[str, Any]) -> Comment:
    return Comment(**{**d, "replies": [_comment_from_dict(r) for r in d.get("replies", [])]})


def _topic_from_dict(d: dict[str, Any]) -> Topic:
    return Topic(**{**d, "comments": [_comment_from_dict(c) for c in d.get("comments", [])]})
