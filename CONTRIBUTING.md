# Contributing to kctx

Thanks for helping! All kinds of contributions are welcome: bug reports, fixes, new features, docs, and trying kctx on competitions we haven't tested.

By taking part you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md). For security problems, see [SECURITY.md](SECURITY.md) and don't open a public issue.

## Ways to help

- **Report a bug** with the [bug template](https://github.com/vks-g/kctx/issues/new?template=bug_report.yml). Bug reports that name the competition are the most useful kind, because they let us reproduce what you saw.
- **Suggest a feature** with the [feature template](https://github.com/vks-g/kctx/issues/new?template=feature_request.yml), or talk it through in [Discussions](https://github.com/vks-g/kctx/discussions) first.
- **Pick up an issue** labelled [`good first issue`](https://github.com/vks-g/kctx/labels/good%20first%20issue) or [`help wanted`](https://github.com/vks-g/kctx/labels/help%20wanted). Comment on it so nobody else starts the same work.
- **Improve the docs.** README fixes and examples are always welcome.

## Development setup

You need [uv](https://docs.astral.sh/uv/). It installs the right Python for you.

```bash
git clone https://github.com/<you>/kctx && cd kctx     # your fork
uv sync                                               # creates .venv with dev tools
uv run pytest                                         # offline: synthetic fixtures, no Kaggle calls
uv run ruff check src tests && uv run ruff format src tests
uv run kctx                                           # try your changes (needs Kaggle credentials)
```

Python ≥ 3.11. CI runs Linux and macOS on Python 3.11–3.14, plus `shellcheck install.sh`.

To try the MCP server from your checkout, run `npx @modelcontextprotocol/inspector uv run kctx mcp --competition titanic`.

## Layout

| Path | What |
|---|---|
| `src/kctx/core/` | Kaggle client wrapper, data model, fetch pipeline, cache, token budget |
| `src/kctx/render/` | HTML→markdown, notebooks→markdown, key-facts card, section renderers |
| `src/kctx/exporters/` | Workspace folder, Claude skill, MCP registration |
| `src/kctx/mcp_server.py` | The local stdio MCP server |
| `src/kctx/interactive.py`, `src/kctx/multiselect.py` | The step-by-step prompts behind plain `kctx` |
| `src/kctx/ui.py` | Terminal output shared by the prompts and the headless commands |
| `install.sh` | The `curl \| sh` installer |
| `skills/`, `.claude-plugin/` | The generic skill and Claude Code plugin manifests |
| `tests/` | pytest suite; `conftest.py` has the synthetic Kaggle fixtures |

## Ground rules

- **Only the official Kaggle API.** No HTML scraping and no private endpoints.
- **Never commit Kaggle content.** Test fixtures in `tests/conftest.py` are synthetic but mirror the real API's shapes. If you find a new quirk (a field that's sometimes a string, a missing author…), reproduce it there.
- **Never download competition data** on the user's behalf. Point them to `data/download.sh`.
- **Stdout is sacred.** The MCP server speaks JSON-RPC over stdout, and prompts own the terminal. Log to stderr.
- Keep `CLAUDE.md` and `SKILL.md` output short: they cost context on every turn.
- **Never log or write credentials.** Kaggle tokens must not end up in output, caches or generated files.

## Pull requests

1. Fork the repo and create a branch off `main` (e.g. `fix/refresh-crash`, `feat/windows-installer`).
2. Keep the PR focused on one change, and add tests for new behaviour.
3. Make sure `uv run pytest`, `uv run ruff check src tests` and `uv run ruff format --check src tests` pass. CI checks the same things.
4. Write commit messages in the [Conventional Commits](https://www.conventionalcommits.org/) style used in the history: `feat: …`, `fix: …`, `docs: …`, `test: …`, `chore: …`.
5. Open the PR and fill in the template. The maintainer is requested for review automatically. PRs are squash-merged once CI is green and the review is done.

For user-visible changes, add a line under **Unreleased** in [CHANGELOG.md](CHANGELOG.md).

## Releases (maintainers)

1. Bump `version` in `pyproject.toml` and `__version__` in `src/kctx/__init__.py`.
2. Move the **Unreleased** notes under the new version in `CHANGELOG.md`, then merge.
3. Publish a GitHub release tagged `vX.Y.Z` (e.g. `gh release create v0.2.0`). The release workflow tests, builds and uploads to PyPI through Trusted Publishing.
