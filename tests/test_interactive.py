from __future__ import annotations

import io
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import SLUG, FakeClient
from rich.console import Console

from kaggle_context.core.client import AuthError
from kaggle_context.exporters import mcp_register
from kaggle_context.interactive import Cancelled, Choice, QuestionaryPrompter, run_interactive


class TermClient(FakeClient):
    def __init__(self, user: str | None = "tester", entered: bool = False) -> None:
        super().__init__()
        self.user = user
        self.entered = entered

    def whoami(self) -> str | None:
        if self.user is None:
            raise AuthError("Invalid Kaggle credentials.")
        return self.user

    def has_entered(self, slug: str) -> bool:
        return self.entered

    def login_with_browser(self) -> None:
        self.user = "browser-user"


class ScriptedPrompter:
    """Answers questions in order and records what was asked."""

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str, Any]] = []

    def _next(self, kind: str, message: str, extra: Any = None) -> Any:
        self.asked.append((kind, message, extra))
        if not self.answers:
            raise AssertionError(f"unexpected {kind} prompt: {message}")
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def text(self, message: str, default: str = "", validate=None) -> str:
        answer = self._next("text", message, default)
        if validate and validate(answer):
            raise AssertionError(f"scripted answer {answer!r} fails validation")
        return answer

    def password(self, message: str) -> str:
        return self._next("password", message)

    def select(self, message: str, choices: list[Choice]) -> Any:
        return self._next("select", message, [c.value for c in choices])

    def checkbox(self, message: str, choices: list[Choice]) -> list[Any]:
        return self._next("checkbox", message, [(c.value, c.checked) for c in choices])

    def confirm(self, message: str, default: bool = False) -> bool:
        return self._next("confirm", message, default)


def run(prompter: ScriptedPrompter, client: FakeClient, initial: str | None = None, **kw: Any):
    out = io.StringIO()
    console = Console(file=out, width=120, soft_wrap=True)
    result = run_interactive(
        initial,
        prompter=prompter,
        console=console,
        client_factory=lambda: client,
        has_credentials=kw.pop("has_credentials", lambda: True),
        **kw,
    )
    return result, out.getvalue()


def test_full_flow_folder_and_skill(cache, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    prompter = ScriptedPrompter(
        f"https://www.kaggle.com/competitions/{SLUG}/overview",  # URL
        ["folder", "skill"],  # modes
        str(tmp_path),  # workspace parent
        "user",  # skill scope
        False,  # advanced?
    )
    result, out = run(prompter, TermClient(), cwd=tmp_path)
    assert result is not None and not result.failed, out
    assert "signed in as tester" in out
    assert "Demo Competition" in out and "accepted the rules" in out
    assert "✓ overview" in out and "✓ notebooks" in out
    assert (tmp_path / SLUG / "CLAUDE.md").is_file()
    assert (tmp_path / "claude-home/skills" / f"kaggle-{SLUG}" / "SKILL.md").is_file()
    kinds = [k for k, _, _ in prompter.asked]
    assert kinds == ["text", "checkbox", "text", "select", "confirm"]
    # folder is pre-selected
    modes = prompter.asked[1][2]
    assert ("folder", True) in modes and ("skill", False) in modes


def test_url_argument_skips_the_url_question(cache, tmp_path: Path) -> None:
    prompter = ScriptedPrompter(["folder"], str(tmp_path), False)
    result, out = run(prompter, TermClient(entered=True), initial=SLUG, cwd=tmp_path)
    assert result is not None
    assert "You have joined this competition" in out
    assert prompter.asked[0][0] == "checkbox"


def test_bad_then_unknown_then_good_competition(cache, tmp_path: Path) -> None:
    prompter = ScriptedPrompter("no-such-comp", SLUG, ["folder"], str(tmp_path), False)
    result, out = run(prompter, TermClient(), initial="https://example.com/x", cwd=tmp_path)
    assert result is not None
    assert "Not a kaggle.com URL" in out
    assert "Couldn't find 'no-such-comp'" in out


def test_mcp_targets_offer_project_only_with_folder(cache, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)  # no claude CLI installed
    prompter = ScriptedPrompter(["mcp"], ["print"], False)
    result, out = run(prompter, TermClient(), initial=SLUG, cwd=tmp_path)
    assert result is not None and not result.failed
    targets = dict(prompter.asked[1][2])
    assert "project" not in targets
    assert targets == {"claude-code": False, "claude-desktop": False, "print": True}
    assert '"mcpServers"' in out


def test_advanced_settings(cache, tmp_path: Path) -> None:
    client = TermClient()
    prompter = ScriptedPrompter(["folder"], str(tmp_path), True, "2", "3", "1", "8000", True)
    result, _ = run(prompter, client, initial=SLUG, cwd=tmp_path)
    assert result is not None
    code_md = list((tmp_path / SLUG / "code").glob("*__*.md"))
    assert len(code_md) == 1


def test_missing_credentials_token_login(cache, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path / "kaggle"))
    creds = {"ok": False}
    prompter = ScriptedPrompter("token", "KGAT_example", ["folder"], str(tmp_path), False)

    def has_credentials() -> bool:
        ok = creds["ok"]
        creds["ok"] = True  # the saved token counts from now on
        return ok

    result, out = run(
        prompter, TermClient(), initial=SLUG, cwd=tmp_path, has_credentials=has_credentials
    )
    assert result is not None
    assert "No Kaggle credentials found" in out
    assert (tmp_path / "kaggle/access_token").read_text().strip() == "KGAT_example"


def test_invalid_credentials_browser_login(cache, tmp_path: Path) -> None:
    client = TermClient(user=None)
    prompter = ScriptedPrompter("browser", ["folder"], str(tmp_path), False)
    result, out = run(prompter, client, initial=SLUG, cwd=tmp_path)
    assert result is not None
    assert "Invalid Kaggle credentials" in out and "signed in as browser-user" in out


def test_ctrl_c_cancels_cleanly(cache, tmp_path: Path) -> None:
    prompter = ScriptedPrompter(Cancelled())
    result, out = run(prompter, TermClient(), cwd=tmp_path)
    assert result is None and "Cancelled" in out


def test_quit_from_login(cache, tmp_path: Path) -> None:
    prompter = ScriptedPrompter("quit")
    result, out = run(prompter, TermClient(), cwd=tmp_path, has_credentials=lambda: False)
    assert result is None and "Cancelled" in out


# -- the real prompt library, driven through a pipe ---------------------------------------


@pytest.fixture
def pipe():
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as inp:
        yield inp, QuestionaryPrompter(input=inp, output=DummyOutput())


def test_questionary_text_and_validation(pipe) -> None:
    inp, prompter = pipe
    inp.send_text("bad url!\r" + "\x7f" * 20 + "titanic\r")
    answer = prompter.text("URL:", validate=lambda v: None if v == "titanic" else "nope")
    assert answer == "titanic"


def test_questionary_checkbox_arrows_and_space(pipe) -> None:
    inp, prompter = pipe
    # first item is pre-checked; move down twice, select the third, confirm
    inp.send_text("\x1b[B\x1b[B \r")
    picked = prompter.checkbox(
        "Modes:", [Choice("a", "a", True), Choice("b", "b"), Choice("c", "c")]
    )
    assert picked == ["a", "c"]


def test_questionary_select(pipe) -> None:
    inp, prompter = pipe
    inp.send_text("\x1b[B\r")
    assert prompter.select("Scope:", [Choice("x", 1), Choice("y", 2)]) == 2


def test_questionary_ctrl_c_is_cancelled(pipe) -> None:
    inp, prompter = pipe
    inp.send_text("\x03")
    with pytest.raises(Cancelled):
        prompter.confirm("Sure?")


# -- claude CLI registration ----------------------------------------------------------------

FAKE_CLAUDE = """#!{python}
import os, sys
log = os.environ["FAKE_CLAUDE_LOG"]
# the real claude (Bun) crashes if stdin is a tty on macOS; insist on /dev/null
st, null = os.fstat(0), os.stat(os.devnull)
with open(log, "a") as f:
    f.write(" ".join(sys.argv[1:]) + f" stdin_is_devnull={{(st.st_rdev, st.st_ino) == (null.st_rdev, null.st_ino)}}\\n")
if sys.argv[1:3] == ["mcp", "get"]:
    sys.exit(1)
if os.environ.get("FAKE_CLAUDE_FAIL"):
    sys.stderr.write("  45 | return applyHandlers(...)\\n  50 | throw er;\\nerror: EINVAL: invalid argument, kqueue\\n    at emitError\\n")
    sys.exit(1)
"""


@pytest.fixture
def fake_claude(tmp_path: Path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "claude"
    script.write_text(FAKE_CLAUDE.format(python=sys.executable))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "claude.log"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(log))
    return log


def test_claude_code_registration_detaches_stdin(fake_claude: Path) -> None:
    res = mcp_register.register_claude_code()
    assert res.ok, res.message
    lines = fake_claude.read_text().splitlines()
    assert lines[0].startswith("mcp get kaggle-context")
    assert lines[1].startswith("mcp add --scope user kaggle-context -- ")
    assert all(line.endswith("stdin_is_devnull=True") for line in lines)


def test_claude_code_failure_is_one_line_with_a_fix(fake_claude: Path, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_FAIL", "1")
    res = mcp_register.register_claude_code()
    assert not res.ok
    assert "\n" not in res.message
    assert "EINVAL: invalid argument, kqueue" in res.message
    assert "claude mcp add --scope user kaggle-context --" in res.message
