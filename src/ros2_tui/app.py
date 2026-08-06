"""Textual TUI shell: feature tabs on top, shared log at the bottom."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    TabbedContent,
    TabPane,
)


from .panes import (
    ActionPane,
    GetParamPane,
    ListDetailPane,
    ServicePane,
    SetParamPane,
    TopicPane,
)
from .ros import RosBridge


class DomainScreen(ModalScreen[int | None]):
    """Small modal prompting for a ROS domain id."""

    CSS = """
    DomainScreen { align: center middle; }
    #domain-dialog { width: 44; height: auto; padding: 1 2; border: thick $primary; background: $surface; }
    #domain-dialog .buttons { height: 3; margin-top: 1; }
    """

    BINDINGS = [("escape", "dismiss(None)", "Cancel")]

    def __init__(self, current: int) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        with Horizontal(id="domain-dialog"):
            yield Label("ROS_DOMAIN_ID: ")
            yield Input(value=str(self._current), type="integer", id="domain-input")

    @on(Input.Submitted, "#domain-input")
    def _submit(self, event: Input.Submitted) -> None:
        try:
            self.dismiss(int(event.value))
        except ValueError:
            self.dismiss(None)

class Ros2TuiApp(App):
    TITLE = "ros2-tui"

    CSS = """
    TabbedContent { height: 1fr; }
    .entity-col { width: 33%; }
    .filter { height: 3; }
    .entity-list { height: 1fr; border: solid $primary; }
    .detail { width: 1fr; border: solid $primary; }
    #log { height: 30%; border: solid $secondary; }
    .detail-title { padding: 0 1; }
    .field-row { height: 3; }
    .field-label { width: 24; padding: 1 1; text-align: right; }
    .field-type { width: 18; padding: 1 1; color: $text-muted; }
    .field-row Input { width: 1fr; }
    .param-value { width: 1fr; padding: 1 1; }
    .buttons { height: 3; }
    """

    BINDINGS = [
        ("r", "refresh", "Refresh list"),
        ("slash", "focus_filter", "Filter"),
        ("d", "set_domain", "Domain ID"),
        ("left_square_bracket", "resize_list(-5)", "List narrower"),
        ("right_square_bracket", "resize_list(5)", "List wider"),
        ("left_curly_bracket", "resize_log(-5)", "Log shorter"),
        ("right_curly_bracket", "resize_log(5)", "Log taller"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, bridge: RosBridge) -> None:
        super().__init__()
        self.bridge = bridge
        self._list_width = 33  # percent
        self._log_height = 30  # percent

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="tab-action"):
            with TabPane("Topic", id="tab-topic"):
                yield TopicPane(self.bridge)
            with TabPane("Service", id="tab-service"):
                yield ServicePane(self.bridge)
            with TabPane("Action", id="tab-action"):
                yield ActionPane(self.bridge)
            with TabPane("Set Param", id="tab-set-param"):
                yield SetParamPane(self.bridge)
            with TabPane("Get Param", id="tab-get-param"):
                yield GetParamPane(self.bridge)
        yield RichLog(id="log", markup=True, wrap=True)
        yield Footer()

    POLL_INTERVAL = 1.0

    def on_mount(self) -> None:
        self.theme = "rose-pine"
        self._update_status()
        self._poll()
        self.set_interval(self.POLL_INTERVAL, self._poll)

    @work(thread=True, exclusive=True, group="poll")
    def _poll(self) -> None:
        """Single background poller: one lock acquisition for all lists."""
        try:
            snapshot = self.bridge.snapshot()
        except Exception:
            return  # session is restarting (domain switch) — next tick will catch up
        self.call_from_thread(self._distribute, snapshot)

    def _distribute(self, snapshot: dict) -> None:
        for pane in self.query(ListDetailPane):
            pane.receive_items(snapshot[pane.SNAPSHOT_KEY])

    def _update_status(self) -> None:
        import os

        distro = os.environ.get("ROS_DISTRO", "?")
        self.sub_title = (
            f"domain {self.bridge.domain_id} · {self.bridge.rmw()} · {distro}"
        )

    def action_refresh(self) -> None:
        self._poll()

    def action_focus_filter(self) -> None:
        active = self._active_list_pane()
        if active is not None:
            active.focus_filter()

    def action_resize_list(self, delta: int) -> None:
        self._list_width = max(15, min(70, self._list_width + delta))
        for col in self.query(".entity-col"):
            col.styles.width = f"{self._list_width}%"

    def action_resize_log(self, delta: int) -> None:
        self._log_height = max(10, min(60, self._log_height + delta))
        self.query_one("#log", RichLog).styles.height = f"{self._log_height}%"

    def _active_list_pane(self) -> ListDetailPane | None:
        active = self.query_one(TabbedContent).active_pane
        return active.query_one(ListDetailPane) if active is not None else None

    def action_set_domain(self) -> None:
        self.push_screen(DomainScreen(self.bridge.domain_id), self._on_domain_chosen)

    def _on_domain_chosen(self, domain_id: int | None) -> None:
        if domain_id is None or domain_id == self.bridge.domain_id:
            return
        self._switch_domain(domain_id)

    @work(thread=True, exclusive=True, group="domain")
    def _switch_domain(self, domain_id: int) -> None:
        self.call_from_thread(
            self.query_one("#log", RichLog).write,
            f"switching to ROS domain {domain_id}…",
        )
        try:
            self.bridge.restart(domain_id)
        except Exception as exc:
            self.call_from_thread(
                self.query_one("#log", RichLog).write,
                f"[red]domain switch failed:[/red] {exc}",
            )
            return
        self.call_from_thread(self._after_domain_switch)

    def _after_domain_switch(self) -> None:
        self._update_status()
        self.query_one("#log", RichLog).write(
            f"[green]connected to ROS domain {self.bridge.domain_id}[/green]"
        )
        self._poll()
