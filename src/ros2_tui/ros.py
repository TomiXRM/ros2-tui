"""ROS graph queries, action/service clients, publishers, params (no ros2cli subprocess)."""

from __future__ import annotations

import yaml
import asyncio_for_robotics.ros2 as afor
from rcl_interfaces.srv import GetParameters, ListParameters, SetParameters
from rclpy.action.graph import get_action_names_and_types
from rclpy.parameter import Parameter, parameter_value_to_python
from rosidl_runtime_py import set_message_fields
from rosidl_runtime_py.utilities import get_action, get_message, get_service


def create_session(domain_id: int | None = None):
    """ThreadedSession on its own rclpy context so the domain can be chosen
    (and changed later by building a fresh session)."""
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from asyncio_for_robotics.ros2.session_types import ThreadedSession

    ctx = rclpy.Context()
    rclpy.init(context=ctx, domain_id=domain_id)
    node = rclpy.create_node("ros2_tui", context=ctx)
    session = ThreadedSession(node, SingleThreadedExecutor(context=ctx))
    session.start()
    session._ros2_tui_ctx = ctx  # keep the context alive / findable
    return session


def close_session(session) -> None:
    ctx = getattr(session, "_ros2_tui_ctx", None)
    session.close()
    if ctx is not None:
        ctx.try_shutdown()


def _is_hidden(name: str) -> bool:
    """Hidden ROS names (same rule ros2cli uses): any token starting with '_',
    e.g. /fibonacci/_action/send_goal."""
    return any(part.startswith("_") for part in name.split("/"))


class RosBridge:
    def __init__(self, session) -> None:
        self.session = session
        self._action_clients: dict[tuple[str, str], afor.ActionClient] = {}
        self._service_clients: dict[tuple[str, str], afor.Client] = {}
        self._publishers: dict[tuple[str, str], object] = {}

    # ── environment info / domain switching ───────────────────────────────────

    @property
    def domain_id(self) -> int:
        with self.session.lock() as node:
            return node.context.get_domain_id()

    @staticmethod
    def rmw() -> str:
        from rclpy.utilities import get_rmw_implementation_identifier

        return get_rmw_implementation_identifier()

    def restart(self, domain_id: int) -> None:
        """Tear down the session and reconnect on another ROS domain.
        Blocking; call from a worker thread. In-flight goals are dropped."""
        for client in [*self._action_clients.values(), *self._service_clients.values()]:
            try:
                client.close()
            except Exception:
                pass
        self._action_clients.clear()
        self._service_clients.clear()
        self._publishers.clear()
        close_session(self.session)
        self.session = create_session(domain_id)

    # ── graph queries (blocking; call from a worker thread) ───────────────────

    def snapshot(self) -> dict[str, dict]:
        """All entity lists in one lock acquisition (lock pauses the executor,
        so one shared poll beats five competing ones)."""
        with self.session.lock() as node:
            actions = get_action_names_and_types(node)
            topics = node.get_topic_names_and_types()
            services = node.get_service_names_and_types()
            node_names = node.get_node_names_and_namespaces()
        return {
            "actions": {n: t[0] for n, t in actions},
            "topics": {n: t[0] for n, t in topics if not _is_hidden(n)},
            "services": {n: t[0] for n, t in services if not _is_hidden(n)},
            "nodes": {ns.rstrip("/") + "/" + n: None for n, ns in node_names},
        }

    def list_actions(self) -> list[tuple[str, list[str]]]:
        with self.session.lock() as node:
            return get_action_names_and_types(node)

    def list_topics(self) -> list[tuple[str, list[str]]]:
        with self.session.lock() as node:
            topics = node.get_topic_names_and_types()
        return [t for t in topics if not _is_hidden(t[0])]

    def list_services(self) -> list[tuple[str, list[str]]]:
        with self.session.lock() as node:
            services = node.get_service_names_and_types()
        return [s for s in services if not _is_hidden(s[0])]

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
