import argparse

from .app import Ros2TuiApp
from .ros import RosBridge, close_session, create_session


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ros2-tui", description="TUI for ROS 2 actions/topics/services/params"
    )
    parser.add_argument(
        "-d", "--domain",
        type=int,
        default=None,
        help="ROS domain id (default: ROS_DOMAIN_ID env or 0)",
    )
    args = parser.parse_args()

    session = create_session(args.domain)
    try:
        Ros2TuiApp(RosBridge(session)).run()
    finally:
        close_session(session)


if __name__ == "__main__":
    main()
