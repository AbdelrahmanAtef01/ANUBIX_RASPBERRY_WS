#!/usr/bin/env python3
"""
ANUBIX Navigation Stack — Placeholder Node (Raspberry Pi)
===========================================================
Subscribes to: /supervisor/nav_goal   (geometry_msgs/PoseStamped)  ← from Jetson master
               /supervisor/force_stop (std_msgs/Bool)               ← from Jetson master
Publishes to:  /nav/status            (std_msgs/String)             → to Jetson master

Status values: navigating | point_reached | blocked | failure

The topic transport is handled transparently by CycloneDDS over the
direct Jetson↔RPi ethernet link. No bridge node is needed for the
data plane; the anubix_rpi_bridge node handles monitoring only.

TODO: Integrate Nav2 or custom path planner:
      - Replace placeholder timer with Nav2 NavigateToPose action client
      - Add obstacle avoidance via costmap
      - Add GPS/RTK waypoint conversion for outdoor operation
      - Add odometry fusion (wheel encoders + IMU + GPS)
"""

import rclpy
from rclpy.node import Node
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
            PoseStamped, '/supervisor/nav_goal', self._on_nav_goal, cmd_qos)
        self.create_subscription(
            Bool, '/supervisor/force_stop', self._on_force_stop, cmd_qos)

        self._status_pub = self.create_publisher(String, '/nav/status', pub_qos)

        self.get_logger().info(
            f'[NAV] Navigation node ready — '
            f'mode={"simulate" if self._simulate else "hardware"} '
            f'nav_delay={self._nav_delay}s')

    def _on_force_stop(self, msg: Bool):
        if msg.data:
            self._force_stopped = True
            self.get_logger().warning('[NAV] Force stop received — ignoring future goals')

    def _on_nav_goal(self, msg: PoseStamped):
        if self._force_stopped:
            self.get_logger().warning('[NAV] Ignoring nav_goal — force stopped')
            self._status_pub.publish(String(data='failure'))
            return

        x = msg.pose.position.x
        y = msg.pose.position.y
        frame = msg.header.frame_id
        self.get_logger().info(
            f'[NAV] Goal received: ({x:.3f}, {y:.3f}) frame={frame!r}')

        self._status_pub.publish(String(data='navigating'))
        self.get_logger().info('[NAV] Status → navigating')

        if self._simulate:
            self.create_timer(
                self._nav_delay,
                lambda: self._complete_navigation(x, y),
            )
        else:
            # TODO: Send goal to Nav2 action server
            # from nav2_msgs.action import NavigateToPose
            pass

    def _complete_navigation(self, x: float, y: float):
        if self._force_stopped:
            self._status_pub.publish(String(data='failure'))
            self.get_logger().warning('[NAV] Navigation aborted — force stopped')
            return
        self._status_pub.publish(String(data='point_reached'))
        self.get_logger().info(f'[NAV] Status → point_reached  ({x:.3f}, {y:.3f})')


def main(args=None):
    rclpy.init(args=args)
    node = NavigationNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('[NAV] Shutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
