"""Headless smoke test: introspection → form fields → build_goal → send_goal."""

import pytest

pytest.importorskip("rclpy")

import asyncio
import threading

from example_interfaces.action import Fibonacci

from ros2_tui.form import flatten_fields
from ros2_tui.ros import RosBridge, build_message


def build_goal(action_type, values):
    return build_message(action_type.Goal, values)


def test_flatten_fields():
    fields = flatten_fields(Fibonacci.Goal())
    assert [(f.path, f.type_str) for f in fields] == [("order", "int32")]


def test_flatten_fields_nested():
    from geometry_msgs.msg import PoseStamped

    paths = {f.path: f.type_str for f in flatten_fields(PoseStamped())}
    assert paths["pose.position.x"] == "double"
    assert paths["header.frame_id"] == "string"


def test_build_goal():
    goal = build_goal(Fibonacci, {"order": "7"})
    assert goal.order == 7
    # empty inputs keep defaults
    assert build_goal(Fibonacci, {"order": ""}).order == 0


def test_send_goal_roundtrip():
    import rclpy
    from rclpy.action import ActionServer, CancelResponse
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from asyncio_for_robotics.ros2.session import session_context
    from asyncio_for_robotics.ros2.session_types import ThreadedSession

    class Srv(Node):
        def __init__(self):
            super().__init__("smoke_fib_server")
            self._s = ActionServer(
                self, Fibonacci, "smoke/fibonacci", self._exec,
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
    srv_node = Srv()
    ex = MultiThreadedExecutor()
    ex.add_node(srv_node)
    spin = threading.Thread(target=ex.spin, daemon=True)
    spin.start()

    async def run(bridge: RosBridge):
        client = bridge.action_client("smoke/fibonacci", "example_interfaces/action/Fibonacci")
        await asyncio.wait_for(client.wait_for_server(), 5)
        actions = dict(await asyncio.to_thread(bridge.list_actions))
        assert "/smoke/fibonacci" in actions
        goal = build_goal(Fibonacci, {"order": "6"})
        gh = client.send_goal(goal)
        assert await gh.accepted
        feedback = [fb async for fb in gh.feedback_until_result()]
        result = await asyncio.wait_for(gh.result, 5)
        assert list(result.sequence) == [0, 1, 1, 2, 3, 5, 8]
        assert feedback, "expected feedback messages"

    try:
        with session_context(ThreadedSession("smoke_client")) as ses:
            asyncio.run(run(RosBridge(ses)))
    finally:
        ex.shutdown(timeout_sec=2)
