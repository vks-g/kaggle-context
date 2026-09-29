"""Run the selected export modes for a fetched bundle. Shared by the CLI and the TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kaggle_context.core.models import Bundle
from kaggle_context.exporters import mcp_register
from kaggle_context.exporters.skill import export_skill, skill_name
from kaggle_context.exporters.workspace import export_workspace

MODES = ("folder", "skill", "mcp")


@dataclass
class ExportPlan:
    modes: tuple[str, ...] = ("folder",)
    out_dir: Path = field(default_factory=Path.cwd)
    skill_scope: str = "user"
    project_dir: Path | None = None
    mcp_targets: tuple[str, ...] = ("claude-code",)
    budget: int = 50_000

    def settings(self) -> dict[str, object]:
        return {
            "modes": list(self.modes),
            "skill_scope": self.skill_scope,
            "mcp_targets": list(self.mcp_targets),
            "budget": self.budget,
        }


@dataclass
class ExportResult:
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    workspace: Path | None = None


def run_exports(bundle: Bundle, plan: ExportPlan) -> ExportResult:
    res = ExportResult()
    slug = bundle.slug

    if "folder" in plan.modes:
        try:
            res.workspace = export_workspace(bundle, plan.out_dir, plan.budget, plan.settings())
            res.done.append(f"Workspace folder: {res.workspace}")
            res.next_steps.append(f"cd {res.workspace} && claude   # CLAUDE.md loads the context")
            res.next_steps.append(
                f"Accept the rules at https://www.kaggle.com/competitions/{slug}/rules, "
                "then run: bash data/download.sh"
            )
        except OSError as exc:
            res.failed.append(f"Workspace folder: {exc}")

    if "skill" in plan.modes:
        try:
            path = export_skill(bundle, plan.skill_scope, plan.project_dir, plan.out_dir)
            res.done.append(f"Claude skill ({plan.skill_scope}): {path}")
            if plan.skill_scope == "zip":
                res.next_steps.append(
                    f"Upload {path.name} at claude.ai → Settings → Capabilities → Skills"
                )
            else:
                res.next_steps.append(
                    f"In Claude Code, the skill loads automatically when relevant, "
                    f"or call it with /{skill_name(slug)}"
                )
        except (OSError, ValueError) as exc:
            res.failed.append(f"Claude skill: {exc}")

    if "mcp" in plan.modes:
        targets = list(plan.mcp_targets)
        if "project" in targets and res.workspace is None:
            targets.remove("project")
            res.failed.append("MCP project config needs the workspace folder mode; skipped.")
        for result in mcp_register.register(targets, slug, res.workspace):
            if result.target == "print":
                res.done.append("MCP config (add this to your client):\n" + result.message)
            elif result.ok:
                res.done.append(f"MCP ({result.target}): {result.message}")
            else:
                res.failed.append(f"MCP ({result.target}): {result.message}")
        if any(t in targets for t in ("claude-code", "claude-desktop", "project")):
            res.next_steps.append(
                f'Restart Claude, then ask: "use kaggle-context to get the brief for {slug}"'
            )
    return res
