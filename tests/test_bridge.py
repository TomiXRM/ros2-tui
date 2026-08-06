"""Bridge-level tests for params and topic publish (exercises service clients too)."""

import pytest

pytest.importorskip("rclpy")

import asyncio
import threading
import time

from ros2_tui.ros import RosBridge, build_message, parse_value


def test_parse_value_keeps_double_type():
    assert parse_value("5", 1.5) == 5.0
    assert isinstance(parse_value("5", 1.5), float)
    assert parse_value("[1, 2]", None) == [1, 2]
    assert parse_value("true", False) is True


def test_param_roundtrip_and_publish():
    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from std_msgs.msg import String
    from asyncio_for_robotics.ros2.session import session_context
    from asyncio_for_robotics.ros2.session_types import ThreadedSession

    received: list = []

    class Target(Node):
        def __init__(self):
            super().__init__("bridge_test_target")
            self.declare_parameter("speed", 1.5)
            self.declare_parameter("label", "hello")
            self.create_subscription(String, "bridge_test/chat", received.append, 10)

    if not rclpy.ok():
        rclpy.init()
    ex = MultiThreadedExecutor()
    ex.add_node(Target())
    threading.Thread(target=ex.spin, daemon=True).start()

    async def run(bridge: RosBridge):
        node_fqn = "/bridge_test_target"
        for _ in range(20):  # wait for discovery
            if node_fqn in await asyncio.to_thread(bridge.list_nodes):
                break
            await asyncio.sleep(0.5)

        params = await asyncio.wait_for(bridge.get_params(node_fqn), 5)
        assert params["speed"] == 1.5
        assert params["label"] == "hello"

        value = parse_value("3", params["speed"])  # int text -> float param
        ok, reason = await asyncio.wait_for(
            bridge.set_param(node_fqn, "speed", value), 5
        )
        assert ok, reason
        params = await asyncio.wait_for(bridge.get_params(node_fqn), 5)
        assert params["speed"] == 3.0

        msg = build_message(String, {"data": "hi from tui"})
        await asyncio.to_thread(bridge.publish, "bridge_test/chat", "std_msgs/msg/String", msg)
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.25)
        assert received and received[0].data == "hi from tui"

    try:
        with session_context(ThreadedSession("bridge_test_client")) as ses:
            asyncio.run(run(RosBridge(ses)))
    finally:
        ex.shutdown(timeout_sec=2)
