"""Fibonacci action server for trying out ros2-tui: pixi run demo-server"""

import time

import rclpy
from example_interfaces.action import Fibonacci
from rclpy.action import ActionServer, CancelResponse
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


class FibonacciServer(Node):
    def __init__(self) -> None:
        super().__init__("fibonacci_server")
        self._server = ActionServer(
            self,
            Fibonacci,
            "fibonacci",
            self._execute,
            cancel_callback=lambda _: CancelResponse.ACCEPT,
        )

    def _execute(self, goal_handle):
        seq = [0, 1]
        fb = Fibonacci.Feedback()
        for _ in range(1, goal_handle.request.order):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                return Fibonacci.Result(sequence=seq)
            seq.append(seq[-1] + seq[-2])
            fb.sequence = seq
            goal_handle.publish_feedback(fb)
            time.sleep(0.5)
        goal_handle.succeed()
        return Fibonacci.Result(sequence=seq)


def main() -> None:
    rclpy.init()
    node = FibonacciServer()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    print("fibonacci action server ready: /fibonacci")
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
