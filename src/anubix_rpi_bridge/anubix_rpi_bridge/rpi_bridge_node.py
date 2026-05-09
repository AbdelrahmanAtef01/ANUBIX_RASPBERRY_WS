#!/usr/bin/env python3
"""
ANUBIX RPi Bridge Node
=======================
Runs on the Raspberry Pi. This is the primary interface between the RPi
stacks and the Jetson Orin Nano master node.

Responsibilities
----------------
1. Publish a 1 Hz heartbeat so the Jetson knows the RPi is alive.
2. Monitor the Jetson heartbeat; escalate through WARNING → ERROR as
   the silence grows; trigger an EMERGENCY STOP to local stacks after
   `connection_timeout` seconds.
3. Log every supervisor command arriving from the Jetson (nav_goal,
   perception_goal, target_camera, force_stop) with full details.
4. Log every feedback message sent by local stacks back to the Jetson
   (nav/status, perception/status, perception/target_pose).
5. Publish /bridge/connection_status at 1 Hz for system dashboards.

Data-plane note
---------------
All topic messages (supervisor commands and stack feedback) flow
directly between nodes via CycloneDDS over the ethernet link — this
node only OBSERVES them (read-only subscriptions). Nothing is
republished or modified, so there is no latency added to the control
loop.

Topics produced:
  /bridge/rpi_heartbeat      std_msgs/String  (JSON, 1 Hz)
  /bridge/connection_status  std_msgs/String  (JSON, 1 Hz)

Safety topic (only when emergency stop triggers):
  /supervisor/force_stop     std_msgs/Bool    (true, once)

Topics subscribed (read-only):
  /bridge/jetson_heartbeat     std_msgs/String
  /supervisor/nav_goal         geometry_msgs/PoseStamped
  /supervisor/perception_goal  std_msgs/String
  /supervisor/target_camera    std_msgs/String
  /supervisor/force_stop       std_msgs/Bool
  /nav/status                  std_msgs/String
  /perception/status           std_msgs/String
  /perception/target_pose      geometry_msgs/Pose
"""

import json
import time
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import String, Bool
from geometry_msgs.msg import PoseStamped, Pose


class RpiBridgeNode(Node):

    def __init__(self):
        super().__init__('anubix_rpi_bridge')

        # ── Parameters ────────────────────────────────────────────────────────
        self.declare_parameter('jetson_ip', '192.168.10.1')
        self.declare_parameter('heartbeat_interval', 1.0)
        self.declare_parameter('connection_timeout', 5.0)
        self.declare_parameter('emergency_stop_on_disconnect', True)

        self._jetson_ip = self.get_parameter('jetson_ip').value
        self._hb_interval = self.get_parameter('heartbeat_interval').value
        self._conn_timeout = self.get_parameter('connection_timeout').value
        self._estop_enabled = self.get_parameter('emergency_stop_on_disconnect').value

        # ── State ─────────────────────────────────────────────────────────────
        self._last_jetson_hb: float = 0.0
        self._jetson_connected: bool = False
        self._estop_sent: bool = False
        self._seq: int = 0
        self._lock = threading.Lock()

        self._stats = {
            'nav_goals_received': 0,
            'perception_goals_received': 0,
            'camera_switches_received': 0,
            'force_stops_received': 0,
            'nav_feedbacks_sent': 0,
            'perception_feedbacks_sent': 0,
            'target_poses_sent': 0,
            'emergency_stops_triggered': 0,
        }

        # ── QoS profiles ──────────────────────────────────────────────────────
        reliable_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        cmd_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )

        # ── Publishers ────────────────────────────────────────────────────────
        self._hb_pub = self.create_publisher(
            String, '/bridge/rpi_heartbeat', reliable_qos)
        self._conn_pub = self.create_publisher(
            String, '/bridge/connection_status', reliable_qos)
        # Safety: emergency stop forwarded to all local stacks
        self._estop_pub = self.create_publisher(
            Bool, '/supervisor/force_stop', cmd_qos)

        # ── Subscriptions ─────────────────────────────────────────────────────
        # Heartbeat from Jetson
        self.create_subscription(
            String, '/bridge/jetson_heartbeat', self._on_jetson_heartbeat, reliable_qos)

        # Cross-machine commands arriving from Jetson → RPi stacks
        self.create_subscription(
            PoseStamped, '/supervisor/nav_goal', self._on_nav_goal, cmd_qos)
        self.create_subscription(
            String, '/supervisor/perception_goal', self._on_perception_goal, cmd_qos)
        self.create_subscription(
            String, '/supervisor/target_camera', self._on_target_camera, cmd_qos)
        self.create_subscription(
            Bool, '/supervisor/force_stop', self._on_force_stop, cmd_qos)

        # Feedback from local RPi stacks heading back to Jetson
        self.create_subscription(
            String, '/nav/status', self._on_nav_status, reliable_qos)
        self.create_subscription(
            String, '/perception/status', self._on_perception_status, reliable_qos)
        self.create_subscription(
            Pose, '/perception/target_pose', self._on_target_pose, reliable_qos)

        # ── Timers ────────────────────────────────────────────────────────────
        self.create_timer(self._hb_interval, self._publish_heartbeat)
        self.create_timer(self._hb_interval, self._check_jetson_connection)

        self.get_logger().info('=' * 62)
        self.get_logger().info('  ANUBIX RPi Bridge Node')
        self.get_logger().info(f'  Monitoring link to Jetson @ {self._jetson_ip}')
        self.get_logger().info(
            f'  Emergency stop on disconnect: {self._estop_enabled}')
        self.get_logger().info(
            f'  Timeout: {self._conn_timeout}s  HB interval: {self._hb_interval}s')
        self.get_logger().info('=' * 62)

    # ── Heartbeat ──────────────────────────────────────────────────────────────

    def _publish_heartbeat(self):
        with self._lock:
            self._seq += 1
            seq = self._seq
            stats = dict(self._stats)
            jetson_ok = self._jetson_connected
            estop = self._estop_sent

        payload = json.dumps({
            'source': 'rpi',
            'seq': seq,
            'stamp': round(time.time(), 3),
            'status': 'ok',
            'jetson_connected': jetson_ok,
            'emergency_stop_sent': estop,
            'stats': stats,
        }, separators=(',', ':'))
        self._hb_pub.publish(String(data=payload))

    def _on_jetson_heartbeat(self, msg: String):
        now = time.time()
        with self._lock:
            prev_hb = self._last_jetson_hb
            self._last_jetson_hb = now
            was_estop = self._estop_sent

        if was_estop and prev_hb == 0.0:
            self.get_logger().warning(
                '[BRIDGE] Jetson reconnected after disconnect. '
                'Emergency stop flag cleared. Operator must explicitly resume missions.')
            with self._lock:
                self._estop_sent = False

        try:
            pl = json.loads(msg.data)
            self.get_logger().debug(
                f'[BRIDGE] Jetson heartbeat seq={pl.get("seq","?")} '
                f'status={pl.get("status","?")}')
        except (json.JSONDecodeError, TypeError):
            self.get_logger().warning(
                f'[BRIDGE] Malformed Jetson heartbeat: {msg.data!r}')

    def _check_jetson_connection(self):
        with self._lock:
            last = self._last_jetson_hb
            was_ok = self._jetson_connected
            estop_already_sent = self._estop_sent

        elapsed = time.time() - last if last > 0 else float('inf')
        now_ok = last > 0 and elapsed < self._conn_timeout

        with self._lock:
            self._jetson_connected = now_ok

        # State transitions
        if was_ok and not now_ok:
            self.get_logger().error(
                f'[BRIDGE] *** JETSON CONNECTION LOST *** '
                f'No heartbeat for {elapsed:.1f}s '
                f'(timeout={self._conn_timeout}s). '
                f'Check: ethernet cable, Jetson power, Jetson bridge node running, '
                f'same ROS_DOMAIN_ID on both machines.')
            if self._estop_enabled and not estop_already_sent:
                self._trigger_emergency_stop(reason='jetson_heartbeat_timeout')

        elif not was_ok and now_ok:
            self.get_logger().info(
                f'[BRIDGE] Jetson connection ESTABLISHED '
                f'(heartbeat age={elapsed:.2f}s)')

        elif not now_ok and last > 0 and elapsed > self._conn_timeout:
            # Repeated warning while still disconnected
            self.get_logger().warning(
                f'[BRIDGE] Jetson still DISCONNECTED — '
                f'no heartbeat for {elapsed:.0f}s')

        # Publish health status
        conn_payload = json.dumps({
            'source': 'rpi',
            'stamp': round(time.time(), 3),
            'jetson_connected': now_ok,
            'jetson_heartbeat_age_s': round(elapsed, 2) if last > 0 else None,
            'emergency_stop_sent': estop_already_sent,
        }, separators=(',', ':'))
        self._conn_pub.publish(String(data=conn_payload))

    def _trigger_emergency_stop(self, reason: str):
        with self._lock:
            self._estop_sent = True
            self._stats['emergency_stops_triggered'] += 1
            total = self._stats['emergency_stops_triggered']

        self._estop_pub.publish(Bool(data=True))
        self.get_logger().error(
            f'[BRIDGE] *** EMERGENCY STOP TRIGGERED *** '
            f'reason={reason!r}  '
            f'Published /supervisor/force_stop=true to all local stacks  '
            f'[total triggered={total}]')

    # ── Command monitors: Jetson → RPi ─────────────────────────────────────────

    def _on_nav_goal(self, msg: PoseStamped):
        with self._lock:
            self._stats['nav_goals_received'] += 1
            total = self._stats['nav_goals_received']
            jetson_ok = self._jetson_connected

        x = msg.pose.position.x
        y = msg.pose.position.y
        z = msg.pose.position.z
        frame = msg.header.frame_id

        self.get_logger().info(
            f'[BRIDGE←Jetson] /supervisor/nav_goal  '
            f'pos=({x:.3f}, {y:.3f}, {z:.3f})  frame={frame!r}  '
            f'[received total={total}]')

        if not jetson_ok:
            self.get_logger().warning(
                '[BRIDGE←Jetson] WARNING: nav_goal arrived but Jetson heartbeat is '
                'stale — possible replay from DDS cache')

    def _on_perception_goal(self, msg: String):
        with self._lock:
            self._stats['perception_goals_received'] += 1
            total = self._stats['perception_goals_received']

        self.get_logger().info(
            f'[BRIDGE←Jetson] /supervisor/perception_goal  '
            f'task={msg.data!r}  [received total={total}]')

    def _on_target_camera(self, msg: String):
        with self._lock:
            self._stats['camera_switches_received'] += 1
            total = self._stats['camera_switches_received']

        self.get_logger().info(
            f'[BRIDGE←Jetson] /supervisor/target_camera  '
            f'camera={msg.data}  [total={total}]')

    def _on_force_stop(self, msg: Bool):
        if not msg.data:
            return
        with self._lock:
            self._stats['force_stops_received'] += 1
            total = self._stats['force_stops_received']

        self.get_logger().warning(
            f'[BRIDGE←Jetson] /supervisor/force_stop=true  '
            f'Received from master — all stacks should halt  [total={total}]')

    # ── Feedback monitors: RPi → Jetson ────────────────────────────────────────

    def _on_nav_status(self, msg: String):
        with self._lock:
            self._stats['nav_feedbacks_sent'] += 1
            total = self._stats['nav_feedbacks_sent']

        status = msg.data.strip().lower()
        log = (self.get_logger().warning
               if status in ('blocked', 'failure')
               else self.get_logger().info)
        log(f'[BRIDGE→Jetson] /nav/status = {status!r}  [total={total}]')

    def _on_perception_status(self, msg: String):
        with self._lock:
            self._stats['perception_feedbacks_sent'] += 1
            total = self._stats['perception_feedbacks_sent']

        self.get_logger().info(
            f'[BRIDGE→Jetson] /perception/status = {msg.data.strip()!r}  '
            f'[total={total}]')

    def _on_target_pose(self, msg: Pose):
        with self._lock:
            self._stats['target_poses_sent'] += 1
            total = self._stats['target_poses_sent']

        self.get_logger().info(
            f'[BRIDGE→Jetson] /perception/target_pose  '
            f'pos=({msg.position.x:.3f}, {msg.position.y:.3f}, {msg.position.z:.3f})  '
            f'[total={total}]')


def main(args=None):
    rclpy.init(args=args)
    node = RpiBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('[BRIDGE] RPi bridge node shutting down...')
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
