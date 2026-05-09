#!/usr/bin/env python3
"""
ANUBIX Raspberry Pi Full Launch
================================
Launches all nodes that run on the Raspberry Pi:
  - anubix_navigation  (nav stack, receives goals from Jetson master)
  - anubix_rpi_bridge  (link monitor, heartbeat, emergency watchdog)

Perception (YOLO leaf detection) runs on the Jetson Orin Nano via anubix_vision.
Do NOT run anubix_perception here — it would conflict with the Jetson vision node
on the shared /perception/status and /perception/target_pose topics.

The Jetson side runs:
  ros2 launch anubix_bringup jetson.launch.py

Usage:
    ros2 launch anubix_bringup_rpi rpi_full.launch.py
    ros2 launch anubix_bringup_rpi rpi_full.launch.py simulate:=false
"""

import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    simulate_arg = DeclareLaunchArgument(
        'simulate', default_value='true',
        description='Run stacks in simulation/placeholder mode (no hardware)')

    nav_share    = get_package_share_directory('anubix_navigation')
    bridge_share = get_package_share_directory('anubix_rpi_bridge')

    nav_node = Node(
        package='anubix_navigation',
        executable='nav_node',
        name='anubix_navigation',
        parameters=[os.path.join(nav_share, 'config', 'nav_params.yaml')],
        output='screen',
        emulate_tty=True,
    )

    bridge_node = Node(
        package='anubix_rpi_bridge',
        executable='rpi_bridge_node',
        name='anubix_rpi_bridge',
        parameters=[os.path.join(bridge_share, 'config', 'rpi_bridge_params.yaml')],
        output='screen',
        emulate_tty=True,
    )

    return LaunchDescription([
        simulate_arg,
        nav_node,
        bridge_node,
    ])
