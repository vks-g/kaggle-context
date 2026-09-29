# kaggle-context

Turn any Kaggle competition into Claude-ready context: overview, rules, data description,
top discussions and top public notebooks, delivered as a workspace folder, a Claude skill,
or a local MCP server.

> 🚧 Work in progress. See the roadmap below.

## Roadmap

- [ ] Engine + headless CLI (`kctx fetch <url>`)
- [ ] Interactive TUI launched with a single `curl … | sh`
- [ ] Mode 1: workspace folder (with `CLAUDE.md` / `AGENTS.md`)
- [ ] Mode 2: per-competition Claude skill
- [ ] Mode 3: local MCP server (no hosting needed)
- [ ] PyPI release + Claude Code plugin
- [ ] Website

Uses the official Kaggle API with your own credentials. Not affiliated with Kaggle.

## License

MIT
