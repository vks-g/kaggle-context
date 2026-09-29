"""Rough token accounting. Four characters per token is close enough for budgeting."""

from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def truncate(text: str, max_tokens: int, note: str = "") -> str:
    """Cut ``text`` to about ``max_tokens`` on a line boundary, appending ``note`` if cut."""
    limit = max(0, max_tokens) * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    cut = text.rfind("\n", 0, limit)
    if cut < limit // 2:
        cut = limit
    head = text[:cut].rstrip()
    if head.count("```") % 2:  # don't leave a code fence open
        head += "\n```"
    marker = f"\n\n…truncated{' — ' + note if note else ''}"
    return head + marker


def allocate(needs: dict[str, int], shares: dict[str, float], budget: int) -> dict[str, int]:
    """Split ``budget`` across sections by ``shares``; sections that need less give the rest back."""
    alloc: dict[str, int] = {}
    remaining = budget
    pending = {s for s, n in needs.items() if n > 0}
    while pending:
        total_share = sum(shares.get(s, 0.1) for s in pending)
        satisfied = {s for s in pending if needs[s] <= remaining * shares.get(s, 0.1) / total_share}
        if not satisfied:
            for s in pending:
                alloc[s] = int(remaining * shares.get(s, 0.1) / total_share)
            break
        for s in satisfied:
            alloc[s] = needs[s]
            remaining -= needs[s]
        pending -= satisfied
    for s in needs:
        alloc.setdefault(s, 0)
    return alloc


def paginate(text: str, part: int, part_tokens: int) -> str:
    """Return one ``part_tokens``-sized chunk of ``text`` (1-based) with a footer for the next."""
    size = part_tokens * CHARS_PER_TOKEN
    if len(text) <= size:
        return text
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            nl = text.rfind("\n", start + size // 2, end)
            end = nl if nl > start else end
        chunks.append(text[start:end])
        start = end
    part = min(max(1, part), len(chunks))
    footer = f"\n\n[part {part}/{len(chunks)}"
    footer += f" — call again with part={part + 1} for more]" if part < len(chunks) else "]"
    return chunks[part - 1] + footer
