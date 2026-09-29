"""The key-facts card: the handful of constraints that are expensive to get wrong.

Everything here is extracted deterministically (metadata fields, headings, regexes).
Rule excerpts are quoted, never paraphrased, so the card can't invent a rule.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from kaggle_context.core.models import Bundle

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BOLD_HEADING = re.compile(r"^\s*\*\*(.+?)\*\*\s*:?\s*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z(“\"])")

_NOTEBOOK_LIMIT_PATTERNS = [
    re.compile(
        r"(CPU|GPU|TPU)[^.\n]{0,40}?(<=|≤|less than|no more than|at most|maximum of)\s*\d+\s*(hours?|hrs?)",
        re.I,
    ),
    re.compile(r"internet access (is )?disabled", re.I),
    re.compile(r"submission file must be named\s+[`'\"]?[\w.-]*\w[`'\"]?", re.I),
]


def format_date(value: str, relative: bool = True) -> str:
    """``2030-01-01 00:00 UTC``, plus ``(in N days)`` / ``(passed)`` for deadlines."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    text = dt.strftime("%Y-%m-%d %H:%M UTC")
    if not relative:
        return text
    days = (dt - datetime.now(UTC)).days
    if days < 0:
        return f"{text} (passed)"
    if days < 400:
        return f"{text} (in {days} days)"
    return text


def extract_section(markdown: str, heading: re.Pattern[str], max_lines: int = 30) -> str:
    """Body under the first heading matching ``heading``, up to the next heading at the same level."""
    lines = markdown.splitlines()
    start, level = None, 7
    for i, line in enumerate(lines):
        m = _HEADING.match(line)
        bold = _BOLD_HEADING.match(line)
        title = m.group(2) if m else (bold.group(1) if bold else None)
        if title is None:
            continue
        this_level = len(m.group(1)) if m else 6
        if start is None:
            if heading.search(title):
                start, level = i + 1, this_level
        elif this_level <= level:
            return _trim(lines[start:i], max_lines)
    return _trim(lines[start:], max_lines) if start is not None else ""


def _trim(lines: list[str], max_lines: int) -> str:
    body = "\n".join(lines).strip()
    kept = body.splitlines()
    if len(kept) > max_lines:
        body = "\n".join(kept[:max_lines]).rstrip()
        if body.count("```") % 2:
            body += "\n```"
        body += "\n…"
    return body


def sentences_with(text: str, pattern: re.Pattern[str], limit: int = 2) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in _SENTENCE_SPLIT.split(flat) if pattern.search(s)][:limit]


def external_data_rule(bundle: Bundle) -> str:
    rules = bundle.page("rules")
    if not rules:
        return ""
    section = extract_section(rules.content, re.compile(r"external data", re.I), max_lines=12)
    if section:
        quotes = sentences_with(section, re.compile(r"external|data|model", re.I), limit=2)
        return " ".join(quotes)[:400]
    quotes = sentences_with(rules.content, re.compile(r"external data", re.I), limit=2)
    return " ".join(quotes)[:400]


def submission_format(bundle: Bundle) -> str:
    for page in [bundle.page("evaluation"), *bundle.overview_pages()]:
        if not page:
            continue
        body = extract_section(
            page.content, re.compile(r"submission (file|format)|submitting", re.I), max_lines=18
        )
        if body:
            return body
    return ""


def notebook_limits(bundle: Bundle) -> list[str]:
    found: list[str] = []
    for page in bundle.pages:
        flat = re.sub(r"\s+", " ", page.content)
        for pattern in _NOTEBOOK_LIMIT_PATTERNS:
            for m in pattern.finditer(flat):
                snippet = m.group(0).strip().rstrip(".")
                if snippet.lower() not in {f.lower() for f in found}:
                    found.append(snippet)
    return found[:6]


def key_facts(bundle: Bundle) -> list[tuple[str, str]]:
    m = bundle.meta
    facts: list[tuple[str, str]] = [("Competition", f"[{m.title}]({m.url})")]
    if m.subtitle:
        facts.append(("Task", m.subtitle))
    if m.evaluation_metric:
        facts.append(("Metric", m.evaluation_metric))
    if m.category or m.reward:
        facts.append(("Type / prize", " · ".join(x for x in (m.category, m.reward) if x)))
    if m.deadline:
        facts.append(("Final deadline", format_date(m.deadline)))
    if m.merger_deadline and m.merger_deadline != m.deadline:
        facts.append(("Team merger deadline", format_date(m.merger_deadline)))
    limits = []
    if m.max_team_size:
        limits.append(f"team ≤ {m.max_team_size}")
    if m.max_daily_submissions:
        limits.append(f"{m.max_daily_submissions} submissions/day")
    if limits:
        facts.append(("Limits", ", ".join(limits)))
    if m.team_count:
        facts.append(("Teams", f"{m.team_count:,}"))
    if m.is_code_competition:
        facts.append(("Submission", "Code competition: submit a Kaggle notebook, not a CSV upload"))
        if nb := notebook_limits(bundle):
            facts.append(("Notebook limits", "; ".join(nb)))
    if ext := external_data_rule(bundle):
        facts.append(("External data (quoted from rules)", f"“{ext}”"))
    if m.tags:
        facts.append(("Tags", ", ".join(m.tags[:8])))
    return facts


def render_facts(bundle: Bundle) -> str:
    rows = ["| | |", "|---|---|"]
    for label, value in key_facts(bundle):
        cell = value.replace("|", r"\|").replace("\n", " ")
        rows.append(f"| **{label}** | {cell} |")
    out = "\n".join(rows)
    if fmt := submission_format(bundle):
        out += "\n\n**Submission format** (from the evaluation page):\n\n" + fmt
    return out
