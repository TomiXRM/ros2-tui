"""One pane per feature tab: Topic / Service / Action / Set Param / Get Param."""

from __future__ import annotations

import asyncio

import asyncio_for_robotics.ros2 as afor
from rosidl_runtime_py import message_to_yaml
from rosidl_runtime_py.utilities import get_action, get_message, get_service
from textual import on, work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, ListItem, ListView, RichLog

from .form import flatten_fields
from .ros import RosBridge, build_message, parse_value

REFRESH_INTERVAL = 3.0
FILTER_DEBOUNCE = 0.5
SERVICE_TIMEOUT = 5.0


def _oneline(msg) -> str:
    return message_to_yaml(msg).replace("\n", " ").strip()


class SafeListView(ListView):
    """Ignore clicks on items that were removed by a list rebuild in the
    instant between the click and its handler (auto-refresh race)."""

    def _on_list_item__child_clicked(self, event) -> None:
        try:
            super()._on_list_item__child_clicked(event)
        except ValueError:
            event.stop()


class ListDetailPane(Horizontal):
    """Left: auto-refreshing list of graph entities; right: detail area."""

    def __init__(self, bridge: RosBridge, **kwargs) -> None:
        super().__init__(**kwargs)
        self.bridge = bridge
        self._items: dict[str, object] = {}  # name -> payload (e.g. type string)
        self.selected: tuple[str, object] | None = None
        self._filter = ""
        self._pending_filter = ""
        self._filter_timer = None

    def compose(self):
        with Vertical(classes="entity-col"):
            yield Input(placeholder="/ filter", classes="filter")
            yield SafeListView(classes="entity-list")
        with VerticalScroll(classes="detail"):
            yield Label("Select an item", classes="detail-title")

    def on_mount(self) -> None:
        self.refresh_list()
        self.set_interval(REFRESH_INTERVAL, self.refresh_list)

    # override: blocking graph query -> {name: payload}
    def fetch(self) -> dict[str, object]:
        raise NotImplementedError

    # override: (re)build the right side for the selected item
    async def build_detail(self, name: str, payload) -> None:
        raise NotImplementedError

    def refresh_list(self) -> None:
        self._fetch_worker()

    @work(thread=True, exclusive=True)
    def _fetch_worker(self) -> None:
        items = self.fetch()
        self.app.call_from_thread(self._update_list, items)

    def _update_list(self, items: dict[str, object]) -> None:
        if items == self._items:
            return
        self._items = items
        self._render_list()

    def _render_list(self) -> None:
        lv = self.query_one(ListView)
        selected = self.selected[0] if self.selected else None
        shown = [n for n in sorted(self._items) if self._filter in n]
        lv.clear()
        for i, name in enumerate(shown):
            lv.append(ListItem(Label(name), name=name))
            if name == selected:
                lv.index = i

    @on(Input.Changed, ".filter")
    def _on_filter_changed(self, event: Input.Changed) -> None:
        # Debounce: rebuilding the list on every keystroke stalls typing.
        self._pending_filter = event.value.strip()
        if self._filter_timer is not None:
            self._filter_timer.stop()
        self._filter_timer = self.set_timer(FILTER_DEBOUNCE, self._apply_filter)

    def _apply_filter(self) -> None:
        self._filter_timer = None
        if self._pending_filter != self._filter:
            self._filter = self._pending_filter
            self._render_list()

    @on(Input.Submitted, ".filter")
    def _on_filter_submitted(self) -> None:
        self.query_one(ListView).focus()

    def focus_filter(self) -> None:
        self.query_one(".filter", Input).focus()

    @on(ListView.Selected)
    async def _on_selected(self, event: ListView.Selected) -> None:
        name = event.item.name
        if name is None or name not in self._items:
            return
        self.selected = (name, self._items[name])
        try:
            await self.build_detail(name, self._items[name])
        except Exception as exc:
            self.log(f"[red]{name}: cannot build detail:[/red] {exc}")

    # ── shared helpers ────────────────────────────────────────────────────────

    @property
    def detail(self) -> VerticalScroll:
        return self.query_one(".detail", VerticalScroll)

    async def reset_detail(self, title: str) -> list:
        detail = self.detail
        await detail.remove_children()
        detail.mount(Label(title, classes="detail-title"))
        return detail

    def mount_form(self, detail, msg_instance) -> None:
        for field in flatten_fields(msg_instance):
            detail.mount(
                Horizontal(
                    Label(field.path, classes="field-label"),
                    Input(value=field.default, name=field.path),
                    Label(field.type_str, classes="field-type"),
                    classes="field-row",
                )
            )

    def collect_form(self) -> dict[str, str]:
        return {i.name: i.value for i in self.detail.query(Input) if i.name}

    def log(self, text: str) -> None:
        self.app.query_one("#log", RichLog).write(text)


# ── Action ────────────────────────────────────────────────────────────────────


class ActionPane(ListDetailPane):
    def __init__(self, bridge: RosBridge, **kwargs) -> None:
        super().__init__(bridge, **kwargs)
        self._goal_handle = None

    def fetch(self):
        return {name: types[0] for name, types in self.bridge.list_actions()}

    async def build_detail(self, name: str, type_str) -> None:
        detail = await self.reset_detail(f"[b]{name}[/b]  ({type_str})")
        self.mount_form(detail, get_action(type_str).Goal())
        detail.mount(
            Horizontal(
                Button("Send Goal", id="send", variant="primary"),
                Button("Cancel Goal", id="cancel"),
                classes="buttons",
            )
        )

    @on(Button.Pressed, "#send")
    def _send(self) -> None:
        if self.selected is None:
            return
        name, type_str = self.selected
        try:
            goal = build_message(get_action(type_str).Goal, self.collect_form())
        except Exception as exc:
            self.log(f"[red]invalid input:[/red] {exc}")
            return
        self._run_goal(name, self.bridge.action_client(name, type_str), goal)

    @work(exclusive=True, group="goal")
    async def _run_goal(self, name: str, client, goal) -> None:
        self.log(f"[b]{name}[/b] send_goal: {_oneline(goal)}")
        gh = client.send_goal(goal)
        self._goal_handle = gh
        if not await gh.accepted:
            self.log(f"[red]{name}: goal REJECTED[/red]")
            return
        self.log(f"{name}: [yellow]ACCEPTED[/yellow]")
        try:
            async for fb in gh.feedback_until_result():
                self.log(f"feedback: {_oneline(fb)}")
            result = await gh.result
            self.log(f"[green]SUCCEEDED[/green] result: {_oneline(result)}")
        except afor.ActionCanceled as e:
            self.log(f"[magenta]CANCELED[/magenta] result: {_oneline(e.result)}")
        except afor.ActionAborted as e:
            self.log(f"[red]ABORTED[/red] result: {_oneline(e.result)}")
        except afor.ActionResultUnknown:
            self.log(f"[red]{name}: result UNKNOWN (server lost the goal)[/red]")
        finally:
            self._goal_handle = None

    @on(Button.Pressed, "#cancel")
    async def _cancel(self) -> None:
        gh = self._goal_handle
        if gh is None:
            self.log("no goal in flight")
            return
        await gh.cancel_goal()
        self.log("cancel requested")


# ── Topic ─────────────────────────────────────────────────────────────────────


class TopicPane(ListDetailPane):
    def fetch(self):
        return {name: types[0] for name, types in self.bridge.list_topics()}

    async def build_detail(self, name: str, type_str) -> None:
        detail = await self.reset_detail(f"[b]{name}[/b]  ({type_str})")
        self.mount_form(detail, get_message(type_str)())
        detail.mount(
            Horizontal(Button("Publish", id="publish", variant="primary"), classes="buttons")
        )

    @on(Button.Pressed, "#publish")
    def _publish(self) -> None:
        if self.selected is None:
            return
        name, type_str = self.selected
        try:
            msg = build_message(get_message(type_str), self.collect_form())
        except Exception as exc:
            self.log(f"[red]invalid input:[/red] {exc}")
            return
        self._publish_worker(name, type_str, msg)

    @work(thread=True, group="publish")
    def _publish_worker(self, name: str, type_str: str, msg) -> None:
        self.bridge.publish(name, type_str, msg)
        self.app.call_from_thread(self.log, f"[b]{name}[/b] published: {_oneline(msg)}")


# ── Service ───────────────────────────────────────────────────────────────────


class ServicePane(ListDetailPane):
    def fetch(self):
        return {name: types[0] for name, types in self.bridge.list_services()}

    async def build_detail(self, name: str, type_str) -> None:
        detail = await self.reset_detail(f"[b]{name}[/b]  ({type_str})")
        self.mount_form(detail, get_service(type_str).Request())
        detail.mount(
            Horizontal(Button("Call", id="call", variant="primary"), classes="buttons")
        )

    @on(Button.Pressed, "#call")
    def _call(self) -> None:
        if self.selected is None:
            return
        name, type_str = self.selected
        try:
            req = build_message(get_service(type_str).Request, self.collect_form())
        except Exception as exc:
            self.log(f"[red]invalid input:[/red] {exc}")
            return
        self._call_worker(name, type_str, req)

    @work(exclusive=True, group="call")
    async def _call_worker(self, name: str, type_str: str, req) -> None:
        self.log(f"[b]{name}[/b] request: {_oneline(req)}")
        client = self.bridge.service_client(name, type_str)
        try:
            res = await asyncio.wait_for(client.call(req), SERVICE_TIMEOUT)
        except asyncio.TimeoutError:
            self.log(f"[red]{name}: no response in {SERVICE_TIMEOUT}s[/red]")
            return
        self.log(f"[green]response:[/green] {_oneline(res)}")


# ── Params ────────────────────────────────────────────────────────────────────


class GetParamPane(ListDetailPane):
    """Node list → read-only parameter dump."""

    def fetch(self):
        return {name: None for name in self.bridge.list_nodes()}

    async def build_detail(self, name: str, _payload) -> None:
        detail = await self.reset_detail(f"[b]{name}[/b] parameters")
        try:
            params = await asyncio.wait_for(
                self.bridge.get_params(name), SERVICE_TIMEOUT
            )
        except asyncio.TimeoutError:
            detail.mount(Label("[red]param services not responding[/red]"))
            return
        for pname, value in params.items():
            detail.mount(
                Horizontal(
                    Label(pname, classes="field-label"),
                    Label(repr(value), classes="param-value"),
                    Label(type(value).__name__, classes="field-type"),
                    classes="field-row",
                )
            )


class SetParamPane(ListDetailPane):
    """Node list → editable parameters; Apply sets the changed ones."""

    def __init__(self, bridge: RosBridge, **kwargs) -> None:
        super().__init__(bridge, **kwargs)
        self._snapshot: dict[str, object] = {}

    def fetch(self):
        return {name: None for name in self.bridge.list_nodes()}

    async def build_detail(self, name: str, _payload) -> None:
        detail = await self.reset_detail(f"[b]{name}[/b] parameters")
        try:
            self._snapshot = await asyncio.wait_for(
                self.bridge.get_params(name), SERVICE_TIMEOUT
            )
        except asyncio.TimeoutError:
            detail.mount(Label("[red]param services not responding[/red]"))
            return
        for pname, value in self._snapshot.items():
            detail.mount(
                Horizontal(
                    Label(pname, classes="field-label"),
                    Input(value=_param_text(value), name=pname),
                    Label(type(value).__name__, classes="field-type"),
                    classes="field-row",
                )
            )
        detail.mount(
            Horizontal(Button("Apply changed", id="apply", variant="primary"), classes="buttons")
        )

    @on(Button.Pressed, "#apply")
    def _apply(self) -> None:
        if self.selected is None:
            return
        changed: dict[str, object] = {}
        for pname, text in self.collect_form().items():
            current = self._snapshot.get(pname)
            try:
                value = parse_value(text, current)
            except Exception as exc:
                self.log(f"[red]{pname}: invalid input:[/red] {exc}")
                return
            if value != current:
                changed[pname] = value
        if not changed:
            self.log("no parameter changed")
            return
        self._apply_worker(self.selected[0], changed)

    @work(exclusive=True, group="setparam")
    async def _apply_worker(self, node_fqn: str, changed: dict) -> None:
        for pname, value in changed.items():
            try:
                ok, reason = await asyncio.wait_for(
                    self.bridge.set_param(node_fqn, pname, value), SERVICE_TIMEOUT
                )
            except asyncio.TimeoutError:
                self.log(f"[red]{pname}: set_parameters timed out[/red]")
                continue
            if ok:
                self._snapshot[pname] = value
                self.log(f"[green]set[/green] {pname} = {value!r}")
            else:
                self.log(f"[red]set {pname} failed:[/red] {reason or 'rejected'}")


def _param_text(value) -> str:
    return value if isinstance(value, str) else repr(value)
