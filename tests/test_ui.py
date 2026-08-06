"""Headless TUI acceptance test: list → form → send → feedback → SUCCEEDED."""

import pytest

pytest.importorskip("rclpy")

import asyncio
import threading

from example_interfaces.action import Fibonacci


async def test_send_goal_via_ui():
    import rclpy
    from rclpy.action import ActionServer, CancelResponse
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from asyncio_for_robotics.ros2.session import session_context
    from asyncio_for_robotics.ros2.session_types import ThreadedSession
    from textual.widgets import Input, ListView, RichLog

    from ros2_tui.app import Ros2TuiApp
    from ros2_tui.panes import ActionPane
    from ros2_tui.ros import RosBridge

    class Srv(Node):
        def __init__(self):
            super().__init__("ui_test_fib_server")
            self._s = ActionServer(
                self, Fibonacci, "ui_test/fibonacci", self._exec,
                cancel_callback=lambda _: CancelResponse.ACCEPT,
            )

        def _exec(self, gh):
            seq = [0, 1]
            fb = Fibonacci.Feedback()
            for _ in range(1, gh.request.order):
                seq.append(seq[-1] + seq[-2])
                fb.sequence = seq
                gh.publish_feedback(fb)
            gh.succeed()
            return Fibonacci.Result(sequence=seq)

    if not rclpy.ok():
        rclpy.init()
    ex = MultiThreadedExecutor()
    ex.add_node(Srv())
    threading.Thread(target=ex.spin, daemon=True).start()

    def log_text(app) -> str:
        return "\n".join(line.text for line in app.query_one("#log", RichLog).lines)

    try:
        with session_context(ThreadedSession("ui_test_client")) as ses:
            app = Ros2TuiApp(RosBridge(ses))
            async with app.run_test() as pilot:
                names: list = []
                for _ in range(20):  # wait for discovery + refresh tick
                    await asyncio.sleep(0.5)
                    lv = app.query_one(ActionPane).query_one(ListView)
                    names = [li.name for li in lv.children]
                    if "/ui_test/fibonacci" in names:
                        break
                assert "/ui_test/fibonacci" in names, f"not discovered: {names}"

                lv.index = names.index("/ui_test/fibonacci")
                lv.action_select_cursor()
                await pilot.pause()
                next(i for i in app.query_one(ActionPane).query(Input) if i.name == "order").value = "6"
                await pilot.click("#send")

                for _ in range(30):
                    await asyncio.sleep(0.5)
                    if "SUCCEEDED" in log_text(app):
                        break
                else:
                    raise AssertionError(f"no SUCCEEDED in log:\n{log_text(app)}")
                assert "feedback" in log_text(app)
    finally:
        ex.shutdown(timeout_sec=2)
