"""Normalise Kaggle content (a mix of HTML and markdown) to clean markdown."""

from __future__ import annotations

import re

from markdownify import markdownify

_HTML_TAG = re.compile(
    r"<(p|div|h[1-6]|ul|ol|li|br|table|span|a|strong|em|b|i|img|pre|code|blockquote|hr)\b[^>]*>",
    re.IGNORECASE,
)
_BLANK_RUNS = re.compile(r"\n{3,}")
_TRAILING_WS = re.compile(r"[ \t]+\n")


def looks_like_html(text: str) -> bool:
    return len(_HTML_TAG.findall(text)) >= 2 or text.lstrip().startswith("<")


def to_markdown(text: str | None) -> str:
    """Convert HTML to markdown; leave text that is already markdown untouched."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    if looks_like_html(text):
        text = markdownify(
            text,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "iframe"],
            escape_underscores=False,
            escape_asterisks=False,
        )
    text = _TRAILING_WS.sub("\n", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()


_ATX = re.compile(r"^(#{1,6}) ")


def _heading_lines(markdown: str) -> list[tuple[int, str, int | None]]:
    """(index, line, heading level or None), skipping fenced code blocks."""
    rows, in_fence = [], False
    for i, line in enumerate(markdown.splitlines()):
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        m = None if in_fence else _ATX.match(line)
        rows.append((i, line, len(m.group(1)) if m else None))
    return rows


def nest_headings(markdown: str, level: int) -> str:
    """Shift headings so the top-most one sits at ``level``, keeping relative structure."""
    rows = _heading_lines(markdown)
    levels = [lvl for _, _, lvl in rows if lvl]
    if not levels:
        return markdown
    shift = level - min(levels)
    out = []
    for _, line, lvl in rows:
        if lvl:
            line = "#" * max(1, min(6, lvl + shift)) + line[lvl:]
        out.append(line)
    return "\n".join(out)
