# Security policy

## Supported versions

Security fixes go into the latest release on [PyPI](https://pypi.org/project/kctx/).

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Report them privately through GitHub instead: go to the repository's **Security** tab and choose **Report a vulnerability** ([direct link](https://github.com/vks-g/kctx/security/advisories/new)). Include what you found, how to reproduce it, and the impact you expect.

You'll get a reply within a week. We'll agree on a fix and a disclosure date with you, and credit you in the advisory unless you'd rather stay anonymous.

Areas that deserve extra care:

- **Kaggle credentials.** kctx reads your `~/.kaggle` credentials and can save an API token. They must never be logged, cached or written into generated files.
- **The installer.** `install.sh` is run through `curl | sh`.
- **Config edits.** kctx writes to Claude Desktop's config and to `.mcp.json`.
- **The MCP server.** It serves content fetched from Kaggle to the model.
