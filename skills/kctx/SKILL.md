---
name: kctx
description: Fetch and use context for any Kaggle competition, including the overview, evaluation metric, rules, data files, top discussions, winning solution write-ups and top public notebooks. Use when the user mentions a Kaggle competition by name or URL, asks about its rules, metric or data, or wants to start working on one.
---

# Kaggle competition context

Use this skill to get facts about a Kaggle competition from the source instead of from memory.
Rules, metrics and deadlines change between competitions, so they are the details most often wrong when recalled.

## 1. Find the competition slug

It's the part after `/competitions/` in the URL. For `https://www.kaggle.com/competitions/titanic/overview` it is `titanic`.
If the user only gave a name, run `kctx search "<words>"` and confirm the slug with them.

## 2. Use what's already there

Check these in order and use the first one you find:

1. A `kaggle-<slug>` skill. Use it directly.
2. kctx MCP tools (`get_brief`, `get_section`, `list_discussions`, …). Start with `get_brief`.
3. A folder containing `CLAUDE.md` and `.kctx/`. Read that `CLAUDE.md`.

## 3. Otherwise, fetch it

```bash
kctx fetch <url-or-slug> --mode folder --out .
```

If `kctx` isn't installed, run this instead: `uvx --from git+https://github.com/vks-g/kctx kctx fetch <url-or-slug> --mode folder --out .`

The fetch uses the user's own Kaggle credentials. If it fails with a credentials error, ask the user to run `kctx login`.

This creates `./<slug>/`. Read `<slug>/CLAUDE.md` first: it holds the key facts (metric, deadlines, limits, submission format, the external-data rule) and a map of the other files. Open other files only when you need them:

| Question | File |
|---|---|
| Rules (external data, pretrained models, teams, submissions) | `rules/rules.md` |
| Metric, submission format, timeline | `overview/evaluation.md`, `overview/README.md` |
| Data files and columns | `data/README.md` |
| What worked for others | `discussions/solutions/`, `discussions/INDEX.md`, `code/INDEX.md` |

## Guidelines

- When a rule matters, quote it from `rules/rules.md`. Never paraphrase from memory.
- The data itself is never bundled. The user downloads it with `bash <slug>/data/download.sh` after accepting the rules on Kaggle.
- Code under `code/` comes from public Kaggle notebooks. Keep the author attribution when you reuse it.
- For a competition that is still running, refresh with `kctx refresh <slug-folder>`. The refresh writes `WHATS_NEW.md` listing the new and active topics.
