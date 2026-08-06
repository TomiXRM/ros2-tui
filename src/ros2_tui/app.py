"""Textual TUI shell: feature tabs on top, shared log at the bottom."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, RichLog, TabbedContent, TabPane

from .panes import (
    ActionPane,
    GetParamPane,
    ListDetailPane,
    ServicePane,
    SetParamPane,
    TopicPane,
)
from .ros import RosBridge


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

    def action_refresh(self) -> None:
        active = self.query_one(TabbedContent).active_pane
        if active is not None:
            active.query_one(ListDetailPane).refresh_list()
