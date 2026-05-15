#!/usr/bin/env python3
"""
ANUBIX Navigation Stack — Node (Raspberry Pi)
===============================================
Subscribes to: /supervisor/nav_goal     (geometry_msgs/PoseStamped) <- from Jetson master
               /supervisor/nav_vision   (std_msgs/Bool)             <- from Jetson master
               /supervisor/force_stop   (std_msgs/Bool)             <- from Jetson master
Publishes to:  /nav/status              (std_msgs/String)           -> to Jetson master

Status values: navigating | success | blocked | failure

Vision flag:
  - True  → nav stops ~vision_standoff_m metres short of the goal so the
            on-board camera can take over the final approach.
  - False → nav drives all the way to the goal.

The mock just sleeps and reports success either way; the standoff
behaviour is logged so the architecture is in place for the real Nav2
hook-up later.
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
        # How far in front of the goal nav stops when vision=True.
        self.declare_parameter('vision_standoff_m', 1.0)
        self._simulate = self.get_parameter('simulate').value
        self._nav_delay = self.get_parameter('nav_delay').value
        self._vision_standoff_m = float(self.get_parameter('vision_standoff_m').value)
        self._force_stopped = False
        self._navigating = False
        self._nav_lock = threading.Lock()
        # Latched: True means "stop short, vision takes over". Defaults
        # False so older callers that don't set the flag keep working.
        self._vision_flag = False

        self._sub_group = ReentrantCallbackGroup()

        cmd_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        # force_stop is edge-triggered — must be VOLATILE so a stale
        # latched True (e.g. from a previous rpi_bridge emergency stop)
        # cannot strand this node on every restart.
        force_stop_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            durability=DurabilityPolicy.VOLATILE,
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
            Bool, '/supervisor/nav_vision', self._on_nav_vision, cmd_qos,
            callback_group=self._sub_group)
        self.create_subscription(
            Bool, '/supervisor/force_stop', self._on_force_stop, force_stop_qos,
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
        # Edge semantics: True aborts any in-flight nav (the simulated
        # move loop checks the flag mid-sleep). False re-arms the node so
        # the next nav_goal works. Mirrors the master's True+False edge
        # publish so a stale latched True can never strand the robot.
        was = self._force_stopped
        self._force_stopped = bool(msg.data)
        if self._force_stopped:
            self.get_logger().warning(
                '[NAV] *** FORCE STOP RECEIVED *** — aborting in-flight nav')
        elif was:
            self.get_logger().info(
                '[NAV] Force stop CLEARED — ready for new goals')

    def _on_nav_vision(self, msg: Bool):
        self._vision_flag = bool(msg.data)
        self.get_logger().info(
            f'[NAV] vision flag = {self._vision_flag} '
            f'(stop {self._vision_standoff_m:.2f} m short of goal '
            f'when True)')

    def _on_nav_goal(self, msg: PoseStamped):
        x = msg.pose.position.x
        y = msg.pose.position.y
        frame = msg.header.frame_id
        vision = self._vision_flag

        self.get_logger().info(
            f'[NAV] ========================================')
        self.get_logger().info(
            f'[NAV] Goal RECEIVED: ({x:.3f}, {y:.3f}) frame="{frame}" '
            f'vision={vision}')
        if vision:
            self.get_logger().info(
                f'[NAV] vision=True → will stop ~{self._vision_standoff_m:.2f} m '
                f'short of ({x:.3f}, {y:.3f}); on-board camera handles the rest.')
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
            threading.Thread(
                target=self._simulate_navigation,
                args=(x, y, vision),
                daemon=True).start()
        else:
            # TODO: Send goal to Nav2 action server. When vision=True,
            # truncate the goal to be vision_standoff_m short along the
            # current heading before forwarding to Nav2.
            self.get_logger().warning(
                '[NAV] Hardware mode not yet implemented! '
                'Falling back to simulated delay.')
            threading.Thread(
                target=self._simulate_navigation,
                args=(x, y, vision),
                daemon=True).start()

    def _simulate_navigation(self, x: float, y: float, vision: bool):
        try:
            if vision:
                self.get_logger().info(
                    f'[NAV] Simulating navigation to '
                    f'({x:.3f}, {y:.3f}) but stopping '
                    f'~{self._vision_standoff_m:.2f} m short '
                    f'(vision=True) — waiting {self._nav_delay}s...')
            else:
                self.get_logger().info(
                    f'[NAV] Simulating navigation to ({x:.3f}, {y:.3f}) '
                    f'— waiting {self._nav_delay}s...')
            time.sleep(self._nav_delay)

            if self._force_stopped:
                self._status_pub.publish(String(data='failure'))
                self.get_logger().warning(
                    f'[NAV] Navigation ABORTED (force stopped) -> "failure"')
            else:
                self._status_pub.publish(String(data='success'))
                if vision:
                    self.get_logger().info(
                        f'[NAV] Navigation COMPLETE (vision standoff) -> '
                        f'"success" near ({x:.3f}, {y:.3f}) '
                        f'(stopped {self._vision_standoff_m:.2f} m short)')
                else:
                    self.get_logger().info(
                        f'[NAV] Navigation COMPLETE -> "success" '
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
