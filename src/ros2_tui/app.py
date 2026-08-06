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
    TabbedContent { height: 2fr; }
    .entity-list { width: 1fr; border: solid $primary; }
    .detail { width: 2fr; border: solid $primary; }
    #log { height: 1fr; border: solid $secondary; }
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
        ("d", "set_domain", "Domain ID"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, bridge: RosBridge) -> None:
        super().__init__()
        self.bridge = bridge

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

    def on_mount(self) -> None:
        self.theme = "rose-pine"
        self._update_status()

    def _update_status(self) -> None:
        import os

        distro = os.environ.get("ROS_DISTRO", "?")
        self.sub_title = (
            f"domain {self.bridge.domain_id} · {self.bridge.rmw()} · {distro}"
        )

    def action_refresh(self) -> None:
        active = self.query_one(TabbedContent).active_pane
        if active is not None:
            active.query_one(ListDetailPane).refresh_list()

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
        for pane in self.query(ListDetailPane):
            pane.refresh_list()
