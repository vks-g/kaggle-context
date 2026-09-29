"""Convert a pulled Kaggle notebook/script into compact markdown for an LLM.

Outputs are dropped (plots, huge tables and logs add tokens but little signal);
code and markdown cells are kept in order.
"""

from __future__ import annotations

import json
from pathlib import Path

_LANG_BY_SUFFIX = {".py": "python", ".r": "r", ".rmd": "r", ".jl": "julia", ".sql": "sql"}


def notebook_to_markdown(path: Path) -> str:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".ipynb":
        return ipynb_to_markdown(text)
    if suffix == ".rmd":
        return text.strip()
    lang = _LANG_BY_SUFFIX.get(suffix, "")
    return f"```{lang}\n{text.rstrip()}\n```"


def ipynb_to_markdown(raw: str) -> str:
    try:
        nb = json.loads(raw)
    except json.JSONDecodeError:
        return f"```\n{raw.strip()}\n```"

    meta = nb.get("metadata", {})
    lang = (
        meta.get("language_info", {}).get("name")
        or meta.get("kernelspec", {}).get("language")
        or "python"
    )
    parts: list[str] = []
    for cell in nb.get("cells", []):
        source = cell.get("source", "")
        if isinstance(source, list):
            source = "".join(source)
        source = source.strip()
        if not source:
            continue
        kind = cell.get("cell_type")
        if kind == "markdown":
            parts.append(source)
        elif kind == "code":
            parts.append(f"```{lang}\n{source}\n```")
    return "\n\n".join(parts)
