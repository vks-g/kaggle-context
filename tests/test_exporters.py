from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from conftest import SLUG

from kaggle_context.core.models import Bundle
from kaggle_context.exporters import mcp_register
from kaggle_context.exporters.skill import MARKER, export_skill, skill_name
from kaggle_context.exporters.workspace import export_workspace, read_manifest
from kaggle_context.pipeline import ExportPlan, run_exports


def test_workspace_tree(bundle: Bundle, tmp_path: Path) -> None:
    root = export_workspace(bundle, tmp_path)
    assert root == tmp_path / SLUG
    for rel in (
        "CLAUDE.md",
        "AGENTS.md",
        "CONTEXT.md",
        "overview/README.md",
        "overview/evaluation.md",
        "overview/leaderboard.md",
        "rules/rules.md",
        "data/README.md",
        "data/download.sh",
        "discussions/INDEX.md",
        "code/INDEX.md",
        "code/alice__strong-baseline.md",
        "code/notebooks/alice__strong-baseline.ipynb",
        ".gitignore",
    ):
        assert (root / rel).is_file(), rel
    assert any((root / "discussions/solutions").iterdir())
    assert [p.name for p in (root / "data/raw").iterdir()] == [".gitkeep"]
    assert os.access(root / "data/download.sh", os.X_OK)
    assert f"-c {SLUG}" in (root / "data/download.sh").read_text()
    assert read_manifest(root)["slug"] == SLUG


def test_workspace_reexport_keeps_user_files(bundle: Bundle, tmp_path: Path) -> None:
    root = export_workspace(bundle, tmp_path)
    (root / "data/raw/train.csv").write_text("a,b\n")
    (root / "my_model.py").write_text("print('mine')")
    (root / ".gitignore").write_text("custom\n")
    export_workspace(bundle, root)  # exporting into the folder itself also works
    assert (root / "data/raw/train.csv").exists()
    assert (root / "my_model.py").exists()
    assert (root / ".gitignore").read_text() == "custom\n"


def test_skill_layout_and_frontmatter(bundle: Bundle, tmp_path: Path) -> None:
    root = export_skill(bundle, "project", project_dir=tmp_path)
    assert root == tmp_path / ".claude/skills" / skill_name(SLUG)
    skill_md = (root / "SKILL.md").read_text()
    assert skill_md.startswith(f'---\nname: kaggle-{SLUG}\ndescription: "')
    front = skill_md.split("---")[1]
    assert "Demo Competition" in front and "AUC" in front
    assert "references/rules/rules.md" in skill_md
    assert (root / "references/rules/rules.md").is_file()
    assert (root / "references/code/alice__strong-baseline.md").is_file()
    assert not (root / "references/code/notebooks").exists()  # no raw .ipynb in skills


def test_skill_refuses_to_clobber_foreign_folder(bundle: Bundle, tmp_path: Path) -> None:
    foreign = tmp_path / ".claude/skills" / skill_name(SLUG)
    foreign.mkdir(parents=True)
    (foreign / "SKILL.md").write_text("hand written")
    with pytest.raises(FileExistsError):
        export_skill(bundle, "project", project_dir=tmp_path)
    assert (foreign / "SKILL.md").read_text() == "hand written"


def test_skill_zip_has_folder_at_root(bundle: Bundle, tmp_path: Path) -> None:
    path = export_skill(bundle, "zip", zip_dir=tmp_path)
    names = zipfile.ZipFile(path).namelist()
    assert f"{skill_name(SLUG)}/SKILL.md" in names
    assert all(n.startswith(skill_name(SLUG) + "/") for n in names)
    assert not any(n.endswith(MARKER) for n in names)
    assert not any(p.name.endswith(".build") for p in tmp_path.iterdir())


def test_desktop_config_merge_preserves_other_servers(tmp_path: Path) -> None:
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    res = mcp_register.register_claude_desktop(cfg)
    assert res.ok
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark" and "other" in data["mcpServers"]
    assert data["mcpServers"]["kaggle-context"]["args"][-1] == "mcp"
    assert list(tmp_path.glob("claude_desktop_config.json.bak-*"))


def test_desktop_config_invalid_json_is_left_alone(tmp_path: Path) -> None:
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text("{not json")
    assert not mcp_register.register_claude_desktop(cfg).ok
    assert cfg.read_text() == "{not json"


def test_project_mcp_json_pins_competition(tmp_path: Path) -> None:
    res = mcp_register.register_project(tmp_path, SLUG)
    assert res.ok
    entry = json.loads((tmp_path / ".mcp.json").read_text())["mcpServers"]["kaggle-context"]
    assert entry["args"][-3:] == ["mcp", "--competition", SLUG]


def test_run_exports_all_modes(bundle: Bundle, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    plan = ExportPlan(
        modes=("folder", "skill", "mcp"),
        out_dir=tmp_path,
        skill_scope="user",
        mcp_targets=("project", "print"),
    )
    res = run_exports(bundle, plan)
    assert not res.failed, res.failed
    assert (tmp_path / "claude-home/skills" / skill_name(SLUG) / "SKILL.md").is_file()
    assert (tmp_path / SLUG / ".mcp.json").is_file()
    assert any("mcpServers" in line for line in res.done)
