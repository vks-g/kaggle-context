# Contributing

Thanks for helping! Bug reports that name the competition are the most useful kind: they let us reproduce what you saw.

## Setup

```bash
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format src tests
```

Python ≥ 3.11. CI runs Linux and macOS on 3.11–3.14, plus `shellcheck install.sh`.

## Layout

| Path | What |
|---|---|
| `src/kaggle_context/core/` | Kaggle client wrapper, data model, fetch pipeline, cache, token budget |
| `src/kaggle_context/render/` | HTML→markdown, notebooks→markdown, key-facts card, section renderers |
| `src/kaggle_context/exporters/` | Workspace folder, Claude skill, MCP registration |
| `src/kaggle_context/mcp_server.py` | The local stdio MCP server |
| `src/kaggle_context/tui/` | The Textual wizard |
| `install.sh` | The `curl \| sh` installer |
| `skills/`, `.claude-plugin/` | The generic skill and Claude Code plugin manifests |

## Ground rules

- **Only the official Kaggle API.** No HTML scraping and no private endpoints.
- **Never commit Kaggle content.** Test fixtures in `tests/conftest.py` are synthetic but mirror the real API's shapes. If you find a new quirk (a field that's sometimes a string, a missing author…), reproduce it there.
- **Never download competition data** on the user's behalf. Point them to `data/download.sh`.
- **Stdout is sacred.** The MCP server speaks JSON-RPC over stdout, and the TUI owns the terminal. Log to stderr.
- Keep `CLAUDE.md` and `SKILL.md` output short: they cost context on every turn.

## Pull requests

Branch off `main`, keep PRs focused, and make sure `pytest`, `ruff check` and `ruff format --check` pass.
