# kaggle-context

[![CI](https://github.com/vks-g/kaggle-context/actions/workflows/ci.yml/badge.svg)](https://github.com/vks-g/kaggle-context/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**Give Claude the full context of any Kaggle competition in one command:** the overview, evaluation metric, rules, data description, top discussions (winning solution write-ups first) and top public notebooks.

```bash
curl -fsSL https://raw.githubusercontent.com/vks-g/kaggle-context/main/install.sh | sh
```

That command installs `kctx` and opens a terminal UI:

1. **Account.** It connects to your Kaggle account (browser login, or paste an API token).
2. **Competition.** You paste a competition URL, e.g. `https://www.kaggle.com/competitions/titanic`.
3. **Delivery.** You choose how Claude should get the context. Pick any combination:
   - **Workspace folder**: `CLAUDE.md` + overview / rules / data / discussions / code, ready for `claude`
   - **Claude skill**: loads automatically whenever you work on that competition
   - **MCP server**: Claude calls tools for rules, discussions, notebooks and *what's new*
4. **Done.** It fetches everything and tells you the next command to run.

Skip the prompt by passing the URL: `curl … | sh -s -- https://www.kaggle.com/competitions/titanic`. After the first run, just type `kctx`.

## Which mode should I pick?

| | Workspace folder | Claude skill | MCP server |
|---|---|---|---|
| Best for | Actually competing: code lives next to the context | Asking Claude about the competition from any project | Live questions ("anything new in the forum?") |
| Works in | Claude Code, Codex, Cursor… (`CLAUDE.md` + `AGENTS.md`) | Claude Code, claude.ai / Desktop (zip upload) | Claude Code, Claude Desktop |
| Freshness | Snapshot, `kctx refresh` | Snapshot, re-run to update | Cached + live `get_whats_new` |
| Context cost | `CLAUDE.md` only (~1–2k tokens); files read on demand | ~100 tokens until relevant | Tool results on demand |

The modes combine well. A typical setup is the workspace folder (for your code) plus the MCP server (to keep up with the forum).

### 1 · Workspace folder

```
titanic/
├── CLAUDE.md / AGENTS.md   key facts + a map of everything below (auto-loaded by Claude Code)
├── CONTEXT.md              everything in one token-budgeted file (default 50k tokens)
├── overview/               description, evaluation, timeline, prizes, FAQ, leaderboard, metadata.json
├── rules/rules.md
├── data/
│   ├── README.md           data description + file list + how to get it
│   ├── download.sh         you run this after accepting the rules; data lands in data/raw/
│   └── raw/                (empty, git-ignored)
├── discussions/            INDEX.md, solutions/ (winning write-ups), topics/ (top comments by votes)
└── code/                   INDEX.md, one .md per notebook (outputs stripped, attributed), notebooks/*.ipynb
```

**The data is never downloaded for you.** Competition rules usually forbid redistributing it, and it can be many GB. `data/download.sh` fetches it with your own account once you've accepted the rules.

### 2 · Claude skill

The TUI generates a per-competition skill, `kaggle-<slug>`, laid out for progressive disclosure:

```
kaggle-titanic/
├── SKILL.md       frontmatter (the ~100 tokens Claude always sees) + key facts + a file map
└── references/    overview/, rules/, data/, discussions/, code/ (read one file at a time)
```

Only the name and description sit in context until the skill is relevant, so dozens of discussions and notebooks cost nothing until Claude needs them. You choose where it goes:

- `~/.claude/skills/`: every project (default)
- `<project>/.claude/skills/`: one project, can be committed and shared with teammates
- **zip**: upload at claude.ai → Settings → Capabilities → Skills, to use it in the web app or Desktop

### 3 · MCP server: no infrastructure needed

`kctx mcp` is a **local stdio server**. Claude Code or Claude Desktop starts it on your machine when needed. It uses your own `~/.kaggle` credentials and a disk cache (`~/.cache/kaggle-context`). There is **no hosted server, no database and no cost**.

| Tool | What it returns |
|---|---|
| `get_brief` | Key facts: metric, deadlines, limits, submission format, the external-data rule (quoted) |
| `get_section` | `overview`, `evaluation`, `rules`, `data`, `leaderboard`, `timeline`, `prizes` |
| `list_discussions` / `search_discussions` / `get_discussion` | Topics (solution write-ups first), keyword search, one topic with its top comments |
| `list_top_notebooks` / `get_notebook` | Top notebooks by votes; code + markdown, outputs stripped |
| `get_whats_new` | **Live**: topics created or commented on since the last fetch |
| `fetch_competition` / `list_competitions` | Add another competition; see what's cached |

It also exposes a `kaggle://{competition}/{section}` resource and a `start-competition` prompt. The TUI registers the server for you. To do it by hand:

```bash
claude mcp add --scope user kaggle-context -- kctx mcp
```

For Claude Desktop, add this to `claude_desktop_config.json`, using the absolute path to `kctx` because Desktop doesn't see your shell `PATH`:

```json
{ "mcpServers": { "kaggle-context": { "command": "/Users/you/.local/bin/kctx", "args": ["mcp"] } } }
```

A *hosted* MCP (for claude.ai on the web or mobile) would need a server and safe handling of each user's Kaggle token. It's on the roadmap, but you don't need it for Claude Code or Desktop.

### Claude Code plugin

To get the generic `kaggle-context` skill and the MCP server in one step:

```
/plugin marketplace add vks-g/kaggle-context
/plugin install kaggle-context@kaggle-context
```

## Headless CLI

Everything the TUI does is also a command, for scripts, CI and agents:

```bash
kctx fetch <url|slug> --mode folder,skill,mcp [--out DIR] [--skill-scope user|project|zip]
                      [--mcp-target claude-code,claude-desktop,project,print]
                      [--discussions 15] [--comments 10] [--notebooks 5] [--budget 50000] [--refresh]
kctx refresh [workspace-folder|slug]   # re-fetch; writes WHATS_NEW.md
kctx search "llm"                      # find competitions
kctx login [--token …]                 # connect your Kaggle account
kctx mcp [--competition <slug>]        # run the MCP server (Claude does this for you)
```

## What gets fetched, and how

Everything comes from the **official Kaggle API** (the same one the `kaggle` CLI uses), called with your own credentials. There is no HTML scraping.

- **Overview**: metadata (metric, deadlines, team and submission limits, code-competition flag) plus every competition page.
- **Rules**: the full rules page. The key-facts card quotes the external-data clause word for word, never paraphrased.
- **Data**: the data-description page plus the file list with sizes.
- **Discussions**: the top topics. "Nth place solution" write-ups come first, then pinned host posts. Each topic keeps its top comments by votes (low-signal "great work!" replies are dropped).
- **Code**: the top public notebooks by votes, with Kaggle Learn exercises filtered out. Outputs are stripped and every notebook is attributed; public Kaggle notebooks are Apache 2.0 by default.
- **Leaderboard**: the top 20 on the public leaderboard.

kaggle-context is not affiliated with Kaggle. Follow each competition's rules, especially on sharing data and code.

## Development

```bash
git clone https://github.com/vks-g/kaggle-context && cd kaggle-context
uv sync
uv run pytest            # offline: synthetic fixtures, no Kaggle calls
uv run ruff check src tests && uv run ruff format --check src tests
uv run kctx              # the TUI, from your checkout
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Roadmap

- [x] Engine + headless CLI
- [x] TUI launched by `curl … | sh`
- [x] Workspace folder, Claude skill, local MCP server
- [x] Claude Code plugin
- [ ] PyPI release (`uvx kaggle-context`)
- [ ] Website with docs and a short install URL
- [ ] Windows installer (`install.ps1`), a competition browser in the TUI, an optional hosted MCP

## License

MIT
