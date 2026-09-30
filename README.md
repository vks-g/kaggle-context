# kctx

[![CI](https://github.com/vks-g/kctx/actions/workflows/ci.yml/badge.svg)](https://github.com/vks-g/kctx/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/kctx.svg)](https://pypi.org/project/kctx/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/vks-g/kctx/blob/main/LICENSE)

**Give Claude the full context of any Kaggle competition in one command:** the overview, evaluation metric, rules, data description, top discussions (winning solution write-ups first) and top public notebooks.

## Install

kctx is on [PyPI](https://pypi.org/project/kctx/). Pick any one of these; each gives you the `kctx` command (Python 3.11+):

```bash
pip install kctx                 # plain pip (inside a virtualenv is best)
uv tool install kctx             # uv: isolated install, recommended
pipx install kctx                # pipx: isolated install
uvx kctx                         # uv: run it once without installing
```

No Python or uv yet? This one-liner installs uv (which fetches Python), installs kctx and starts it:

```bash
curl -fsSL https://raw.githubusercontent.com/vks-g/kctx/main/install.sh | sh
```

To upgrade later: `pip install -U kctx`, `uv tool upgrade kctx` or `pipx upgrade kctx`.

## Quick start

Run `kctx`. It asks you a few questions right in your terminal. Move with the arrow keys; in multi-choice questions, **enter (or space) ticks an option** and you finish by picking **Continue**:

```
✓ Kaggle: signed in as you
? Competition URL or search: titanic
  Titanic - Machine Learning from Disaster
  Metric: Categorization Accuracy  ·  Deadline: 2030-01-01 00:00 UTC  ·  Teams: 10,307
? How should Claude get the context? (↑/↓ move · enter or space to tick · then pick Continue)
   [x] Workspace folder  CLAUDE.md + overview, rules, data, discussions, code
   [x] Claude skill  loads automatically when you work on this competition
   [ ] MCP server  Claude calls tools for rules, discussions, notebooks, what's new
 ❯ Continue →
? Create the workspace folder in: /Users/you/kaggle
Fetching Titanic - Machine Learning from Disaster
  ✓ overview     5 pages
  ✓ rules        found
  ✓ data files   3 files
  ✓ discussions  16 topics (1 solution write-ups)
  ✓ notebooks    5 notebooks
  ✓ leaderboard  top 20
✓ Workspace folder: /Users/you/kaggle/titanic
```

If you have no Kaggle credentials yet, it first offers a browser login or lets you paste an API token.

You can paste a competition URL or slug, or type a few words to search Kaggle and choose a match from the arrow-key list.

Skip the URL question by passing it: `kctx https://www.kaggle.com/competitions/titanic` (or `curl … | sh -s -- <url>` with the one-liner).

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

`kctx` generates a per-competition skill, `kaggle-<slug>`, laid out for progressive disclosure:

```
kaggle-titanic/
├── SKILL.md       frontmatter (the ~100 tokens Claude always sees) + key facts + a file map
└── references/    overview/, rules/, data/, discussions/, code/ (read one file at a time)
```

Only the name and description sit in context until the skill is relevant, so dozens of discussions and notebooks cost nothing until Claude needs them. You choose where it goes:

- `~/.claude/skills/`: every project (default)
- `<project>/.claude/skills/`: one project, can be committed and shared with teammates
- **zip**: upload at claude.ai → Settings → Capabilities → Skills, to use it in the web app or Desktop

To use it in Claude Code, type `/kaggle` and pick `/kaggle-<slug>`, or just ask about the competition ("are external models allowed?") and Claude loads it on its own.

### 3 · MCP server: no infrastructure needed

`kctx mcp` is a **local stdio server**. Claude Code or Claude Desktop starts it on your machine when needed. It uses your own `~/.kaggle` credentials and a disk cache (`~/.cache/kctx`). There is **no hosted server, no database and no cost**.

| Tool | What it returns |
|---|---|
| `get_brief` | Key facts: metric, deadlines, limits, submission format, the external-data rule (quoted) |
| `get_section` | `overview`, `evaluation`, `rules`, `data`, `leaderboard`, `timeline`, `prizes` |
| `list_discussions` / `search_discussions` / `get_discussion` | Topics (solution write-ups first), keyword search, one topic with its top comments |
| `list_top_notebooks` / `get_notebook` | Top notebooks by votes; code + markdown, outputs stripped |
| `get_whats_new` | **Live**: topics created or commented on since the last fetch |
| `fetch_competition` / `list_competitions` | Add another competition; see what's cached |

It also exposes a `kaggle://{competition}/{section}` resource and a `start-competition` prompt. `kctx` registers the server for you (Claude Code, Claude Desktop, or a project `.mcp.json`; check it with `/mcp` in Claude Code). To do it by hand:

```bash
claude mcp add --scope user kctx -- kctx mcp
```

For Claude Desktop, add this to `claude_desktop_config.json`, using the absolute path to `kctx` because Desktop doesn't see your shell `PATH`:

```json
{ "mcpServers": { "kctx": { "command": "/Users/you/.local/bin/kctx", "args": ["mcp"] } } }
```

A *hosted* MCP (for claude.ai on the web or mobile) would need a server and safe handling of each user's Kaggle token. It's on the roadmap, but you don't need it for Claude Code or Desktop.

### Claude Code plugin

To get the generic `kctx` skill and the MCP server in one step:

```
/plugin marketplace add vks-g/kctx
/plugin install kctx@kctx
```

## Headless CLI

Everything the prompts do is also a command, for scripts, CI and agents:

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

kctx is not affiliated with Kaggle. Follow each competition's rules, especially on sharing data and code.

## Contributing

Contributions are welcome, from bug reports to new features. To get started:

- Read [CONTRIBUTING.md](https://github.com/vks-g/kctx/blob/main/CONTRIBUTING.md). It covers dev setup, the ground rules and how PRs are reviewed.
- Look for issues labelled [good first issue](https://github.com/vks-g/kctx/labels/good%20first%20issue) or [help wanted](https://github.com/vks-g/kctx/labels/help%20wanted).
- Ask questions and float ideas in [Discussions](https://github.com/vks-g/kctx/discussions).
- Report security problems privately (see [SECURITY.md](https://github.com/vks-g/kctx/blob/main/SECURITY.md)).

Everyone taking part follows the [Code of Conduct](https://github.com/vks-g/kctx/blob/main/CODE_OF_CONDUCT.md).

```bash
git clone https://github.com/vks-g/kctx && cd kctx
uv sync
uv run pytest            # offline: synthetic fixtures, no Kaggle calls
uv run ruff check src tests && uv run ruff format --check src tests
uv run kctx              # the step-by-step prompts, from your checkout
```

## Roadmap

- [x] Engine + headless CLI
- [x] Step-by-step terminal prompts launched by `curl … | sh`
- [x] Workspace folder, Claude skill, local MCP server
- [x] Claude Code plugin
- [x] PyPI release (`uvx kctx`)
- [ ] Website with docs and a short install URL
- [ ] Windows installer (`install.ps1`), competition search inside the prompts, an optional hosted MCP

## License

MIT
