from asyncio_for_robotics.ros2.session import session_context
from asyncio_for_robotics.ros2.session_types import ThreadedSession

from .app import Ros2TuiApp
from .ros import RosBridge


def main() -> None:
    with session_context(ThreadedSession("ros2_tui")) as session:
        Ros2TuiApp(RosBridge(session)).run()


if __name__ == "__main__":
    main()
