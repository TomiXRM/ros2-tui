"""ROS graph queries, action/service clients, publishers, params (no ros2cli subprocess)."""

from __future__ import annotations

import yaml
import asyncio_for_robotics.ros2 as afor
from rcl_interfaces.srv import GetParameters, ListParameters, SetParameters
from rclpy.action.graph import get_action_names_and_types
from rclpy.parameter import Parameter, parameter_value_to_python
from rosidl_runtime_py import set_message_fields
from rosidl_runtime_py.utilities import get_action, get_message, get_service


class RosBridge:
    def __init__(self, session) -> None:
        self.session = session
        self._action_clients: dict[tuple[str, str], afor.ActionClient] = {}
        self._service_clients: dict[tuple[str, str], afor.Client] = {}
        self._publishers: dict[tuple[str, str], object] = {}

    # ── graph queries (blocking; call from a worker thread) ───────────────────

    def list_actions(self) -> list[tuple[str, list[str]]]:
        with self.session.lock() as node:
            return get_action_names_and_types(node)

    def list_topics(self) -> list[tuple[str, list[str]]]:
        with self.session.lock() as node:
            return node.get_topic_names_and_types()

    def list_services(self) -> list[tuple[str, list[str]]]:
        with self.session.lock() as node:
            return node.get_service_names_and_types()

    def list_nodes(self) -> list[str]:
        with self.session.lock() as node:
            names = node.get_node_names_and_namespaces()
        return [ns.rstrip("/") + "/" + name for name, ns in names]

    # ── clients / publishers (cached) ─────────────────────────────────────────

    def action_client(self, action_name: str, type_str: str) -> afor.ActionClient:
        key = (action_name, type_str)
        if key not in self._action_clients:
            self._action_clients[key] = afor.ActionClient(
                get_action(type_str), action_name, session=self.session
            )
        return self._action_clients[key]

    def service_client(self, srv_name: str, type_str: str) -> afor.Client:
        key = (srv_name, type_str)
        if key not in self._service_clients:
            self._service_clients[key] = afor.Client(
                get_service(type_str), srv_name, session=self.session
            )
        return self._service_clients[key]

    def publish(self, topic: str, type_str: str, msg) -> None:
        key = (topic, type_str)
        if key not in self._publishers:
            with self.session.lock() as node:
                self._publishers[key] = node.create_publisher(
                    get_message(type_str), topic, 10
                )
        self._publishers[key].publish(msg)

    # ── parameters (via the same services ros2param uses) ─────────────────────

    def _param_client(self, node_fqn: str, suffix: str, srv_type) -> afor.Client:
        key = (f"{node_fqn}/{suffix}", srv_type.__name__)
        if key not in self._service_clients:
            self._service_clients[key] = afor.Client(
                srv_type, key[0], session=self.session
            )
        return self._service_clients[key]

    async def get_params(self, node_fqn: str) -> dict[str, object]:
        """All parameters of a node as {name: python value}."""
        lister = self._param_client(node_fqn, "list_parameters", ListParameters)
        names = sorted((await lister.call(ListParameters.Request())).result.names)
        if not names:
            return {}
        getter = self._param_client(node_fqn, "get_parameters", GetParameters)
        res = await getter.call(GetParameters.Request(names=names))
        return {
            n: parameter_value_to_python(v) for n, v in zip(names, res.values)
        }

    async def set_param(self, node_fqn: str, name: str, value) -> tuple[bool, str]:
        """Set one parameter; returns (successful, reason)."""
        setter = self._param_client(node_fqn, "set_parameters", SetParameters)
        msg = Parameter(name=name, value=value).to_parameter_msg()
        res = await setter.call(SetParameters.Request(parameters=[msg]))
        r = res.results[0]
        return r.successful, r.reason


def parse_value(text: str, current):
    """Parse input text as YAML, coercing to the current value's type where sane
    (typing 5 into a double param must not flip its type to integer)."""
    value = yaml.safe_load(text)
    if isinstance(current, float) and isinstance(value, int):
        return float(value)
    return value


def build_message(msg_type_or_cls, values: dict[str, str], factory=None):
    """Build a message from {flattened.field.path: input text}.

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
    msg = msg_type_or_cls()
    set_message_fields(msg, data)
    return msg
