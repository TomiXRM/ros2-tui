"""ROS graph queries and action client management (no ros2cli subprocess)."""

from __future__ import annotations

import yaml
import asyncio_for_robotics.ros2 as afor
from rclpy.action.graph import get_action_names_and_types
from rosidl_runtime_py import set_message_fields
from rosidl_runtime_py.utilities import get_action


class RosBridge:
    def __init__(self, session) -> None:
        self.session = session
        self._clients: dict[tuple[str, str], afor.ActionClient] = {}

    def list_actions(self) -> list[tuple[str, list[str]]]:
        """Same graph API ros2action uses. Blocking; call from a worker thread."""
        with self.session.lock() as node:
            return get_action_names_and_types(node)

    def client(self, action_name: str, type_str: str) -> afor.ActionClient:
        key = (action_name, type_str)
        if key not in self._clients:
            self._clients[key] = afor.ActionClient(
                get_action(type_str), action_name, session=self.session
            )
        return self._clients[key]


def build_goal(action_type, values: dict[str, str]):
    """Build a Goal message from {flattened.field.path: input text}.

    Each leaf is parsed as YAML (so 42, 3.14, true, [1, 2] all work) and
    set_message_fields does the type coercion — the same path ros2cli takes
    after parsing its YAML argument.
    """
    data: dict = {}
    for path, text in values.items():
        if not text.strip():
            continue
        cur = data
        *parents, leaf = path.split(".")
        for p in parents:
            cur = cur.setdefault(p, {})
        cur[leaf] = yaml.safe_load(text)
    goal = action_type.Goal()
    set_message_fields(goal, data)
    return goal
