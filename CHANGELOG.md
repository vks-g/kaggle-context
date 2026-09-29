# Changelog

## 0.1.0 (unreleased)

- Fetch engine on the official Kaggle API: overview, rules, data description and file list, discussions (solution write-ups first), top notebooks, leaderboard; on-disk cache; "what's new" on refresh.
- Key-facts card: metric, deadlines, limits, submission format, code-competition notebook limits, external-data rule quoted verbatim.
- Workspace folder export with `CLAUDE.md`, `AGENTS.md`, token-budgeted `CONTEXT.md` and `data/download.sh`.
- Per-competition Claude skill export (user, project, or zip for claude.ai).
- Local stdio MCP server with tools, a resource template and a prompt; registration for Claude Code, Claude Desktop and project `.mcp.json`.
- Step-by-step terminal prompts (arrow keys, space to select) behind plain `kctx`, and a `curl | sh` installer.
- Fix: registering the MCP server with Claude Code no longer crashes the `claude` CLI (`EINVAL … kqueue`) when started through `curl | sh` on macOS; failures now show one line plus the command to run yourself.
- Claude Code plugin with a generic `kaggle-context` skill.
