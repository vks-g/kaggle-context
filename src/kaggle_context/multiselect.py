"""A multi-choice prompt where Enter ticks options and a final "Continue" row submits.

questionary's checkbox submits on Enter and ticks only with Space, so people who press
Enter on each option end up with just one choice. Here both Enter and Space tick the
highlighted option, number keys tick option N, and choosing "Continue" finishes.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

CONTINUE = "Continue →"
HINT = "(↑/↓ move · enter or space to tick · then pick Continue)"


def multiselect(
    message: str,
    options: Sequence[tuple[str, Any, str]],
    checked: Sequence[bool] | None = None,
    **app_kwargs: Any,
) -> list[Any]:
    """Ask for one or more ``(label, value, hint)`` options; returns the ticked values.

    Raises ``KeyboardInterrupt`` on Ctrl-C. ``app_kwargs`` (input/output) go to
    prompt_toolkit, which is how the tests drive it.
    """
    from prompt_toolkit.application import Application
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.shortcuts import print_formatted_text
    from prompt_toolkit.styles import Style

    ticked = list(checked) if checked else [False] * len(options)
    last = len(options)  # index of the Continue row
    state = {"pos": 0, "error": ""}

    def render() -> FormattedText:
        rows: list[tuple[str, str]] = [
            ("class:qmark", "? "),
            ("class:question", message + " "),
            ("class:hint", HINT + "\n"),
        ]
        for i, (label, _, hint) in enumerate(options):
            here = state["pos"] == i
            box = "[x]" if ticked[i] else "[ ]"
            rows.append(("class:pointer" if here else "", " ❯ " if here else "   "))
            rows.append(("class:ticked" if ticked[i] else "", f"{box} "))
            rows.append(("class:highlighted" if here else "", label))
            rows.append(("class:hint", f"  {hint}\n" if hint else "\n"))
        here = state["pos"] == last
        rows.append(("class:pointer" if here else "", " ❯ " if here else "   "))
        rows.append(("class:continue-on" if here else "class:continue", f"{CONTINUE}\n"))
        if state["error"]:
            rows.append(("class:error", f"   {state['error']}\n"))
        return FormattedText(rows)

    kb = KeyBindings()

    def move(step: int) -> None:
        state["pos"] = (state["pos"] + step) % (last + 1)
        state["error"] = ""

    def toggle(i: int) -> None:
        ticked[i] = not ticked[i]
        state["error"] = ""

    @kb.add("up")
    @kb.add("k")
    @kb.add("s-tab")
    def _up(event: Any) -> None:
        move(-1)

    @kb.add("down")
    @kb.add("j")
    @kb.add("tab")
    def _down(event: Any) -> None:
        move(1)

    @kb.add(" ")
    def _space(event: Any) -> None:
        if state["pos"] < last:
            toggle(state["pos"])

    @kb.add("enter")
    def _enter(event: Any) -> None:
        if state["pos"] < last:
            toggle(state["pos"])
        elif any(ticked):
            event.app.exit(result=[opt[1] for opt, on in zip(options, ticked, strict=True) if on])
        else:
            state["error"] = "Tick at least one option first."

    for n in range(1, min(len(options), 9) + 1):

        @kb.add(str(n))
        def _number(event: Any, i: int = n - 1) -> None:
            toggle(i)
            state["pos"] = i

    @kb.add("c-c")
    @kb.add("c-d")
    def _cancel(event: Any) -> None:
        event.app.exit(exception=KeyboardInterrupt())

    style = Style.from_dict(
        {
            "qmark": "fg:#5f87ff bold",
            "question": "bold",
            "hint": "fg:#808080",
            "pointer": "fg:#5f87ff bold",
            "highlighted": "fg:#5f87ff",
            "ticked": "fg:#5faf5f bold",
            "continue": "fg:#808080",
            "continue-on": "fg:#5faf5f bold",
            "error": "fg:#ff5f5f",
            "answer": "fg:#5faf5f",
        }
    )
    app: Application[list[Any]] = Application(
        layout=Layout(
            Window(FormattedTextControl(render, show_cursor=False), dont_extend_height=True)
        ),
        key_bindings=kb,
        style=style,
        full_screen=False,
        erase_when_done=True,
        **app_kwargs,
    )
    result = app.run()
    labels = ", ".join(opt[0] for opt, on in zip(options, ticked, strict=True) if on)
    print_formatted_text(
        FormattedText(
            [("class:qmark", "? "), ("class:question", message + " "), ("class:answer", labels)]
        ),
        style=style,
        output=app_kwargs.get("output"),
    )
    return result
