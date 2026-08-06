"""Textual TUI: action list / goal form / feedback log."""

from __future__ import annotations

import asyncio

import asyncio_for_robotics.ros2 as afor
from rosidl_runtime_py import message_to_yaml
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, RichLog

from .form import flatten_fields
from .ros import RosBridge, build_goal

REFRESH_INTERVAL = 3.0


class Ros2TuiApp(App):
    TITLE = "ros2-tui"

    CSS = """
    #body { height: 2fr; }
    #actions { width: 1fr; border: solid $primary; }
    #form { width: 2fr; border: solid $primary; }
    #log { height: 1fr; border: solid $secondary; }
    .field-row { height: 3; }
    .field-label { width: 24; padding: 1 1; text-align: right; }
    .field-type { width: 18; padding: 1 1; color: $text-muted; }
    .field-row Input { width: 1fr; }
    #buttons { height: 3; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh actions"),
        ("ctrl+s", "send_goal", "Send goal"),
        ("ctrl+g", "cancel_goal", "Cancel goal"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, bridge: RosBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._actions: dict[str, str] = {}  # action name -> type string
        self._selected: tuple[str, str] | None = None
        self._goal_handle = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="body"):
            yield ListView(id="actions")
            with VerticalScroll(id="form"):
                yield Label("Select an action", id="form-title")
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh()
        self.set_interval(REFRESH_INTERVAL, self.action_refresh)

    # ── Action list ───────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self._fetch_actions()

    @work(thread=True, exclusive=True, group="refresh")
    def _fetch_actions(self) -> None:
        actions = {name: types[0] for name, types in self.bridge.list_actions()}
        self.call_from_thread(self._update_action_list, actions)

    def _update_action_list(self, actions: dict[str, str]) -> None:
        if actions == self._actions:
            return
        self._actions = actions
        lv = self.query_one("#actions", ListView)
        selected = self._selected[0] if self._selected else None
        lv.clear()
        for name in sorted(actions):
            lv.append(ListItem(Label(f"{name}"), name=name))
        if selected and selected in actions:
            for i, name in enumerate(sorted(actions)):
                if name == selected:
                    lv.index = i
                    break

    @on(ListView.Selected, "#actions")
    async def _on_action_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name is None:
            return
        type_str = self._actions[name]
        self._selected = (name, type_str)
        await self._build_form(name, type_str)

    # ── Goal form ─────────────────────────────────────────────────────────────

    async def _build_form(self, name: str, type_str: str) -> None:
        from rosidl_runtime_py.utilities import get_action

        form = self.query_one("#form", VerticalScroll)
        await form.remove_children()
        form.mount(Label(f"[b]{name}[/b]  ({type_str})", id="form-title"))
        action_type = get_action(type_str)
        for field in flatten_fields(action_type.Goal()):
            form.mount(
                Horizontal(
                    Label(field.path, classes="field-label"),
                    Input(value=field.default, id=f"field-{field.path.replace('.', '-')}", name=field.path),
                    Label(field.type_str, classes="field-type"),
                    classes="field-row",
                )
            )
        form.mount(
            Horizontal(
                Button("Send Goal", id="send", variant="primary"),
                Button("Cancel Goal", id="cancel"),
                id="buttons",
            )
        )

    def _collect_values(self) -> dict[str, str]:
        return {
            inp.name: inp.value
            for inp in self.query_one("#form").query(Input)
            if inp.name
        }

    # ── Send / feedback / cancel ──────────────────────────────────────────────

    @on(Button.Pressed, "#send")
    def action_send_goal(self) -> None:
        if self._selected is None:
            return
        from rosidl_runtime_py.utilities import get_action

        name, type_str = self._selected
        action_type = get_action(type_str)
        try:
            goal = build_goal(action_type, self._collect_values())
        except Exception as exc:
            self._log(f"[red]invalid input:[/red] {exc}")
            return
        client = self.bridge.client(name, type_str)
        self._run_goal(name, client, goal)

    @work(exclusive=True, group="goal")
    async def _run_goal(self, name: str, client, goal) -> None:
        self._log(f"[b]{name}[/b] send_goal: {_oneline(goal)}")
        gh = client.send_goal(goal)
        self._goal_handle = gh
        if not await gh.accepted:
            self._log(f"[red]{name}: goal REJECTED[/red]")
            return
        self._log(f"{name}: [yellow]ACCEPTED[/yellow]")
        try:
            async for fb in gh.feedback_until_result():
                self._log(f"feedback: {_oneline(fb)}")
            result = await gh.result
            self._log(f"[green]SUCCEEDED[/green] result: {_oneline(result)}")
        except afor.ActionCanceled as e:
            self._log(f"[magenta]CANCELED[/magenta] result: {_oneline(e.result)}")
        except afor.ActionAborted as e:
            self._log(f"[red]ABORTED[/red] result: {_oneline(e.result)}")
        except afor.ActionResultUnknown:
            self._log(f"[red]{name}: result UNKNOWN (server lost the goal)[/red]")
        finally:
            self._goal_handle = None

    @on(Button.Pressed, "#cancel")
    def action_cancel_goal(self) -> None:
        if self._goal_handle is None:
            self._log("no goal in flight")
            return
        self._cancel_goal()

    @work(group="cancel")
    async def _cancel_goal(self) -> None:
        gh = self._goal_handle
        if gh is not None:
            await gh.cancel_goal()
            self._log("cancel requested")

    def _log(self, text: str) -> None:
        self.query_one("#log", RichLog).write(text)


def _oneline(msg) -> str:
    return message_to_yaml(msg).replace("\n", " ").strip()
