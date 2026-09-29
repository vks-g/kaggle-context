from __future__ import annotations

from pathlib import Path

import pytest
from conftest import SLUG, FakeClient
from textual.widgets import Button, Checkbox, Input, Static

from kaggle_context.core.client import AuthError
from kaggle_context.tui.app import (
    AuthScreen,
    CompetitionScreen,
    DoneScreen,
    KaggleContextApp,
    ModesScreen,
)


class TuiClient(FakeClient):
    def __init__(self, user: str | None = "tester", entered: bool = False) -> None:
        super().__init__()
        self.user = user
        self.entered = entered

    def whoami(self) -> str | None:
        if self.user is None:
            raise AuthError("No Kaggle credentials found.")
        return self.user

    def has_entered(self, slug: str) -> bool:
        return self.entered


def make_app(client: TuiClient, initial: str | None = None) -> KaggleContextApp:
    return KaggleContextApp(initial, client_factory=lambda: client, skip_credential_file_check=True)


async def wait_for_screen(pilot, cls, tries: int = 100) -> None:
    for _ in range(tries):
        if isinstance(pilot.app.screen, cls):
            return
        await pilot.pause(0.05)
    raise AssertionError(f"never reached {cls.__name__}; at {type(pilot.app.screen).__name__}")


def text_of(screen, selector: str) -> str:
    return str(screen.query_one(selector, Static).render())


async def test_full_flow_workspace_and_skill(cache, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.chdir(tmp_path)
    app = make_app(TuiClient())
    async with app.run_test(size=(120, 50)) as pilot:
        await wait_for_screen(pilot, CompetitionScreen)
        assert "tester" in text_of(app.screen, "#who")

        app.screen.query_one(
            "#url", Input
        ).value = f"https://www.kaggle.com/competitions/{SLUG}/overview"
        await pilot.press("enter")
        for _ in range(100):
            if not app.screen.query_one("#continue", Button).disabled:
                break
            await pilot.pause(0.05)
        card = text_of(app.screen, "#card")
        assert "Demo Competition" in card and "AUC" in card and "accepted the rules" in card

        await pilot.click("#continue")
        await wait_for_screen(pilot, ModesScreen)
        app.screen.query_one("#m-skill", Checkbox).value = True
        await pilot.pause()
        assert app.screen.query_one("#o-skill").display
        await pilot.click("#go")

        await wait_for_screen(pilot, DoneScreen)
        wiz = app.wizard
        assert wiz.bundle is not None and wiz.result is not None
        assert not wiz.result.failed, wiz.result.failed
        await pilot.click("#finish")

    assert (tmp_path / SLUG / "CLAUDE.md").is_file()
    assert (tmp_path / "claude-home/skills" / f"kaggle-{SLUG}" / "SKILL.md").is_file()


async def test_initial_url_is_looked_up_automatically(cache) -> None:
    app = make_app(TuiClient(entered=True), initial=SLUG)
    async with app.run_test(size=(120, 50)) as pilot:
        await wait_for_screen(pilot, CompetitionScreen)
        for _ in range(100):
            if "joined" in text_of(app.screen, "#card"):
                break
            await pilot.pause(0.05)
        assert "You have joined this competition" in text_of(app.screen, "#card")


async def test_bad_url_shows_error(cache) -> None:
    app = make_app(TuiClient())
    async with app.run_test() as pilot:
        await wait_for_screen(pilot, CompetitionScreen)
        app.screen.query_one("#url", Input).value = "https://example.com/nope"
        await pilot.press("enter")
        await pilot.pause()
        assert "Not a kaggle.com URL" in text_of(app.screen, "#url-error")


async def test_unknown_competition_shows_error(cache) -> None:
    app = make_app(TuiClient())
    async with app.run_test() as pilot:
        await wait_for_screen(pilot, CompetitionScreen)
        app.screen.query_one("#url", Input).value = "no-such-comp"
        await pilot.press("enter")
        for _ in range(100):
            if text_of(app.screen, "#url-error"):
                break
            await pilot.pause(0.05)
        assert "Couldn't find 'no-such-comp'" in text_of(app.screen, "#url-error")


async def test_missing_credentials_offer_login(cache, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", str(tmp_path / "kaggle"))
    client = TuiClient(user=None)
    app = make_app(client)
    async with app.run_test() as pilot:
        for _ in range(100):
            if not app.screen.query_one("#login").has_class("hidden"):
                break
            await pilot.pause(0.05)
        assert isinstance(app.screen, AuthScreen)
        assert "No Kaggle credentials" in text_of(app.screen, "#auth-status")

        client.user = "newbie"  # the token below "fixes" auth
        app.screen.query_one("#token", Input).value = "KGAT_example"
        await pilot.click("#save-token")
        await wait_for_screen(pilot, CompetitionScreen)
    assert (tmp_path / "kaggle/access_token").read_text().strip() == "KGAT_example"


@pytest.mark.parametrize("modes_off", [("#m-folder",)])
async def test_modes_screen_requires_a_mode(cache, modes_off) -> None:
    app = make_app(TuiClient(), initial=SLUG)
    async with app.run_test(size=(120, 50)) as pilot:
        await wait_for_screen(pilot, CompetitionScreen)
        for _ in range(100):
            if not app.screen.query_one("#continue", Button).disabled:
                break
            await pilot.pause(0.05)
        await pilot.click("#continue")
        await wait_for_screen(pilot, ModesScreen)
        for wid in modes_off:
            app.screen.query_one(wid, Checkbox).value = False
        await pilot.pause()
        app.screen.query_one("#go", Button).press()
        await pilot.pause()
        assert isinstance(app.screen, ModesScreen)
        assert "at least one" in text_of(app.screen, "#modes-error")
