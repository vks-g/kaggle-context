# Changelog

## Unreleased

- `install.sh` and the Claude Code plugin now install kctx from PyPI instead of from the GitHub repo.
- README: an Install section with `pip install kctx`, `uv tool install kctx`, `pipx install kctx` and `uvx kctx`.

## 0.1.0 (2026-09-30)

- Renamed from kaggle-context to **kctx**: repo `vks-g/kctx`, package `kctx`, MCP server `kctx`, cache `~/.cache/kctx`. Skills and workspaces made under the old name are still recognised and updated in place.
- Fetch engine on the official Kaggle API: overview, rules, data description and file list, discussions (solution write-ups first), top notebooks, leaderboard; on-disk cache; "what's new" on refresh.
- Key-facts card: metric, deadlines, limits, submission format, code-competition notebook limits, external-data rule quoted verbatim.
- Workspace folder export with `CLAUDE.md`, `AGENTS.md`, token-budgeted `CONTEXT.md` and `data/download.sh`.
- Per-competition Claude skill export (user, project, or zip for claude.ai).
- Local stdio MCP server with tools, a resource template and a prompt; registration for Claude Code, Claude Desktop and project `.mcp.json`.
- Step-by-step terminal prompts (arrow keys, space to select) behind plain `kctx`, and a `curl | sh` installer.
- Multi-choice questions: enter or space ticks an option, number keys tick option N, and a final "Continue" row submits. Nothing is pre-ticked. (With the previous checkbox, pressing enter submitted after the first choice.)
- Fix: registering the MCP server with Claude Code no longer crashes the `claude` CLI (`EINVAL … kqueue`) when started through `curl | sh` on macOS; failures now show one line plus the command to run yourself.
- Claude Code plugin with a generic `kctx` skill.
