"""Mode 3: register the local kaggle-context MCP server with Claude.

The server is a local stdio process (``kctx mcp``) that Claude starts on demand. It uses
your own Kaggle credentials and the on-disk cache, so no hosting is needed.
One registration serves every competition; tools take an optional ``competition``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SERVER_NAME = "kaggle-context"
TARGETS = ("claude-code", "claude-desktop", "project", "print")


@dataclass
class Result:
    target: str
    ok: bool
    message: str


def kctx_command() -> list[str]:
    """An absolute command for launching the server.

    GUI apps like Claude Desktop don't inherit your shell PATH, so a bare ``kctx``
    often fails there. Prefer the script next to the running interpreter.
    """
    local = Path(sys.executable).parent / ("kctx.exe" if os.name == "nt" else "kctx")
    if local.exists():
        return [str(local)]
    found = shutil.which("kctx")
    if found:
        return [str(Path(found).resolve())]
    uvx = shutil.which("uvx")
    return [uvx or "uvx", "kaggle-context"]


def server_entry(competition: str | None = None) -> dict[str, object]:
    cmd = kctx_command()
    args = [*cmd[1:], "mcp"]
    if competition:
        args += ["--competition", competition]
    return {"command": cmd[0], "args": args}


def config_snippet(competition: str | None = None) -> str:
    return json.dumps({"mcpServers": {SERVER_NAME: server_entry(competition)}}, indent=2)


def register_claude_code() -> Result:
    claude = shutil.which("claude")
    if not claude:
        entry = server_entry()
        cmd = " ".join([entry["command"], *entry["args"]])  # type: ignore[list-item]
        return Result(
            "claude-code",
            False,
            f"`claude` CLI not found. Once it is installed, run: claude mcp add --scope user {SERVER_NAME} -- {cmd}",
        )
    existing = subprocess.run(
        [claude, "mcp", "get", SERVER_NAME], capture_output=True, text=True, check=False
    )
    if existing.returncode == 0:
        return Result("claude-code", True, f"Already registered in Claude Code as '{SERVER_NAME}'.")
    entry = server_entry()
    proc = subprocess.run(
        [
            claude,
            "mcp",
            "add",
            "--scope",
            "user",
            SERVER_NAME,
            "--",
            entry["command"],
            *entry["args"],
        ],  # type: ignore[list-item]
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return Result("claude-code", False, (proc.stderr or proc.stdout).strip())
    return Result("claude-code", True, f"Registered '{SERVER_NAME}' in Claude Code (user scope).")


def claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def register_claude_desktop(config_path: Path | None = None) -> Result:
    path = config_path or claude_desktop_config_path()
    config: dict[str, object] = {}
    if path.exists():
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            return Result(
                "claude-desktop",
                False,
                f"{path} is not valid JSON; not touching it. Add this manually:\n{config_snippet()}",
            )
        backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(path, backup)
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return Result("claude-desktop", False, "Unexpected 'mcpServers' format; not touching it.")
    servers[SERVER_NAME] = server_entry()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return Result(
        "claude-desktop",
        True,
        f"Added '{SERVER_NAME}' to {path}. Restart Claude Desktop to load it.",
    )


def register_project(folder: Path, competition: str) -> Result:
    """Write/merge ``.mcp.json`` in a workspace folder with this competition as the default."""
    path = folder / ".mcp.json"
    config: dict[str, object] = {}
    if path.exists():
        try:
            config = json.loads(path.read_text() or "{}")
        except json.JSONDecodeError:
            return Result("project", False, f"{path} is not valid JSON; not touching it.")
    servers = config.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        return Result("project", False, "Unexpected 'mcpServers' format; not touching it.")
    servers[SERVER_NAME] = server_entry(competition)
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")
    return Result(
        "project", True, f"Wrote {path} (Claude Code asks you to approve it on first use)."
    )


def register(targets: list[str], competition: str, workspace: Path | None = None) -> list[Result]:
    results: list[Result] = []
    for target in targets:
        if target == "claude-code":
            results.append(register_claude_code())
        elif target == "claude-desktop":
            results.append(register_claude_desktop())
        elif target == "project":
            if workspace is None:
                results.append(
                    Result("project", False, "No workspace folder to write .mcp.json into.")
                )
            else:
                results.append(register_project(workspace, competition))
        elif target == "print":
            results.append(Result("print", True, config_snippet(competition)))
        else:
            results.append(Result(target, False, f"Unknown MCP target {target!r}"))
    return results
