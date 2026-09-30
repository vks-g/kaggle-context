## What and why

<!-- What does this change, and what problem does it solve? Link the issue: "Fixes #123". -->

## How I tested it

<!-- Commands you ran, competitions you tried, screenshots of prompts if the UI changed. -->

## Checklist

- [ ] `uv run pytest` passes
- [ ] `uv run ruff check src tests` and `uv run ruff format --check src tests` pass
- [ ] New behaviour has tests (fixtures stay synthetic; no real Kaggle content committed)
- [ ] Only the official Kaggle API is used; no competition data is downloaded for the user
- [ ] Nothing new is printed to stdout by library code (the MCP server speaks JSON-RPC there)
- [ ] README / CHANGELOG updated if users will notice the change
