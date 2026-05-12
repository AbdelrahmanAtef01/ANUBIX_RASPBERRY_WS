#!/usr/bin/env python3
"""
ANUBIX Navigation Stack — Node (Raspberry Pi)
===============================================
Subscribes to: /supervisor/nav_goal   (geometry_msgs/PoseStamped)  <- from Jetson master
               /supervisor/force_stop (std_msgs/Bool)               <- from Jetson master
Publishes to:  /nav/status            (std_msgs/String)             -> to Jetson master

Status values: navigating | point_reached | blocked | failure
"""

import time
import threading
import traceback

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseStamped


class NavigationNode(Node):

    def __init__(self):
        super().__init__('anubix_navigation')

        self.declare_parameter('simulate', True)
        self.declare_parameter('nav_delay', 2.0)
        self._simulate = self.get_parameter('simulate').value
        self._nav_delay = self.get_parameter('nav_delay').value
        self._force_stopped = False
        self._navigating = False
        self._nav_lock = threading.Lock()

        self._sub_group = ReentrantCallbackGroup()

        cmd_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        pub_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self.create_subscription(
            PoseStamped, '/supervisor/nav_goal', self._on_nav_goal, cmd_qos,
            callback_group=self._sub_group)
        self.create_subscription(
            Bool, '/supervisor/force_stop', self._on_force_stop, cmd_qos,
            callback_group=self._sub_group)

        self._status_pub = self.create_publisher(String, '/nav/status', pub_qos)

        self.get_logger().info('=' * 50)
        self.get_logger().info('  ANUBIX Navigation Node - Raspberry Pi')
        self.get_logger().info(
            f'  Mode: {"SIMULATE" if self._simulate else "HARDWARE"}')
        self.get_logger().info(f'  Nav delay: {self._nav_delay}s')
        self.get_logger().info('=' * 50)
        self.get_logger().info(
            '[NAV] Subscribed to /supervisor/nav_goal (PoseStamped, TRANSIENT_LOCAL)')
        self.get_logger().info(
            '[NAV] Publishing on /nav/status (String, RELIABLE)')
        self.get_logger().info('[NAV] Ready and waiting for goals.')

    def _on_force_stop(self, msg: Bool):
        if msg.data:
            self._force_stopped = True
            self.get_logger().warning(
                '[NAV] *** FORCE STOP RECEIVED *** — ignoring future goals')

    def _on_nav_goal(self, msg: PoseStamped):
        x = msg.pose.position.x
        y = msg.pose.position.y
        frame = msg.header.frame_id

        self.get_logger().info(
            f'[NAV] ========================================')
        self.get_logger().info(
            f'[NAV] Goal RECEIVED: ({x:.3f}, {y:.3f}) frame="{frame}"')
        self.get_logger().info(
            f'[NAV] ========================================')

        if self._force_stopped:
            self.get_logger().warning(
                '[NAV] REJECTED: robot is force_stopped. Publishing "failure".')
            self._status_pub.publish(String(data='failure'))
            return

        with self._nav_lock:
            if self._navigating:
                self.get_logger().warning(
                    '[NAV] Already navigating! Ignoring new goal. Publishing "failure".')
                self._status_pub.publish(String(data='failure'))
                return
            self._navigating = True

        # Publish "navigating" immediately so the master knows we received it
        self._status_pub.publish(String(data='navigating'))
        self.get_logger().info('[NAV] Published status: "navigating"')

        if self._simulate:
            # Run navigation in a thread with sleep (NOT a repeating timer)
            threading.Thread(
                target=self._simulate_navigation,
                args=(x, y),
                daemon=True).start()
        else:
            # TODO: Send goal to Nav2 action server
            self.get_logger().warning(
                '[NAV] Hardware mode not yet implemented! '
                'Falling back to simulated delay.')
            threading.Thread(
                target=self._simulate_navigation,
                args=(x, y),
                daemon=True).start()

    def _simulate_navigation(self, x: float, y: float):
        try:
            self.get_logger().info(
                f'[NAV] Simulating navigation to ({x:.3f}, {y:.3f}) '
                f'— waiting {self._nav_delay}s...')
            time.sleep(self._nav_delay)

            if self._force_stopped:
                self._status_pub.publish(String(data='failure'))
                self.get_logger().warning(
                    f'[NAV] Navigation ABORTED (force stopped) -> "failure"')
            else:
                self._status_pub.publish(String(data='point_reached'))
                self.get_logger().info(
                    f'[NAV] Navigation COMPLETE -> "point_reached" '
                    f'at ({x:.3f}, {y:.3f})')
        except Exception as e:
            self.get_logger().error(
                f'[NAV] Exception during navigation: {e}\n'
                f'{traceback.format_exc()}')
            self._status_pub.publish(String(data='failure'))
        finally:
            with self._nav_lock:
                self._navigating = False


def main(args=None):
    rclpy.init(args=args)
    node = NavigationNode()
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        node.get_logger().info('[NAV] Shutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
