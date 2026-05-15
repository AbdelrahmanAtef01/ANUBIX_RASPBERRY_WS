#!/usr/bin/env python3
"""
ANUBIX Perception Stack — Placeholder Node (Raspberry Pi)
===========================================================
Subscribes to: /supervisor/perception_goal (std_msgs/String)    ← from Jetson master
               /supervisor/target_camera   (std_msgs/String)    ← from Jetson master
               /supervisor/force_stop      (std_msgs/Bool)      ← from Jetson master
Publishes to:  /perception/status          (std_msgs/String)    → to Jetson master
               /perception/target_pose     (geometry_msgs/Pose) → to Jetson master

Status values: found | not_found

TODO: Integrate actual perception pipeline:
      - Camera driver (CSI / USB cameras on Raspberry Pi)
      - YOLO or custom crop detection model (TFLite / ONNX on RPi)
      - Depth estimation for target_pose (stereo or depth camera)
      - Camera switching logic (camera 1 = wide, camera 2 = close-up)
      - Water stress detection via NDVI / thermal imaging
      - Disease classification model
      - Harvest readiness assessment
"""

import time
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import String, Bool
from geometry_msgs.msg import Pose


class PerceptionNode(Node):

    def __init__(self):
        super().__init__('anubix_perception')

        self.declare_parameter('simulate', True)
        self.declare_parameter('detection_delay', 1.5)
        self.declare_parameter('default_target_x', 0.5)
        self.declare_parameter('default_target_y', 0.0)
        self.declare_parameter('default_target_z', 0.2)

        self._simulate = self.get_parameter('simulate').value
        self._detection_delay = self.get_parameter('detection_delay').value
        self._active_camera = 1
        self._force_stopped = False
        self._busy = False
        self._lock = threading.Lock()

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
            String, '/supervisor/perception_goal', self._on_perception_goal, cmd_qos)
        self.create_subscription(
            String, '/supervisor/target_camera', self._on_target_camera, cmd_qos)
        self.create_subscription(
            Bool, '/supervisor/force_stop', self._on_force_stop, force_stop_qos)

        self._status_pub = self.create_publisher(
            String, '/perception/status', pub_qos)
        self._pose_pub = self.create_publisher(
            Pose, '/perception/target_pose', pub_qos)

        self.get_logger().info(
            f'[PERCEPTION] Node ready — '
            f'mode={"simulate" if self._simulate else "hardware"} '
            f'delay={self._detection_delay}s')

    def _on_force_stop(self, msg: Bool):
        # Edge semantics: True aborts/blocks new goals, False re-arms
        # the node. Matches master's True+False edge so a single
        # force_stop doesn't permanently disable perception.
        was = self._force_stopped
        self._force_stopped = bool(msg.data)
        if self._force_stopped:
            self.get_logger().warning('[PERCEPTION] Force stop — ignoring future goals')
        elif was:
            self.get_logger().info('[PERCEPTION] Force stop CLEARED — ready for new goals')

    def _on_target_camera(self, msg: String):
        try:
            self._active_camera = int(msg.data)
        except ValueError:
            self._active_camera = 1
        self.get_logger().info(
            f'[PERCEPTION] Camera → {self._active_camera}')

    def _on_perception_goal(self, msg: String):
        if self._force_stopped:
            self.get_logger().warning('[PERCEPTION] Ignoring goal — force stopped')
            self._status_pub.publish(String(data='not_found'))
            return

        with self._lock:
            if self._busy:
                self.get_logger().warning(
                    '[PERCEPTION] Already processing — ignoring new goal')
                return
            self._busy = True

        task = msg.data
        self.get_logger().info(
            f'[PERCEPTION] Goal received: task={task!r} camera={self._active_camera}')

        if self._simulate:
            threading.Thread(
                target=self._simulate_detection,
                args=(task,),
                daemon=True,
            ).start()
        else:
            # TODO: Run detection model, publish result
            with self._lock:
                self._busy = False

    def _simulate_detection(self, task: str):
        try:
            self.get_logger().info(
                f'[PERCEPTION] Simulating detection for task={task!r} '
                f'— waiting {self._detection_delay}s...')
            time.sleep(self._detection_delay)

            if self._force_stopped:
                self._status_pub.publish(String(data='not_found'))
                self.get_logger().warning(
                    f'[PERCEPTION] Detection aborted: task={task!r} — force stopped')
                return

            self._status_pub.publish(String(data='found'))
            self.get_logger().info(
                f'[PERCEPTION] Status → found  task={task!r}')

            pose = Pose()
            pose.position.x = self.get_parameter('default_target_x').value
            pose.position.y = self.get_parameter('default_target_y').value
            pose.position.z = self.get_parameter('default_target_z').value
            pose.orientation.w = 1.0
            self._pose_pub.publish(pose)
            self.get_logger().info(
                f'[PERCEPTION] target_pose published: '
                f'({pose.position.x}, {pose.position.y}, {pose.position.z})')
        finally:
            with self._lock:
                self._busy = False


def main(args=None):
    rclpy.init(args=args)
    node = PerceptionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('[PERCEPTION] Shutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
