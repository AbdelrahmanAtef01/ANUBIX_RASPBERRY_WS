# ANUBIX Perception (Raspberry Pi) - Development Placeholder

## ⚠️ DO NOT USE IN PRODUCTION

This is a **development placeholder** for early testing. The actual perception/vision system runs on the Jetson Orin Nano via the `anubix_vision` package.

## Architecture

- **Raspberry Pi**: Navigation stack only (`anubix_navigation`)
- **Jetson Orin Nano**: Vision/perception (`anubix_vision`) with YOLO + RealSense/USB cameras

## Why This Package Exists

This placeholder was created during early development to:
1. Test the ROS 2 topic structure before hardware was available
2. Provide a simple mock for integration testing
3. Allow RPi-only testing without requiring the Jetson

## Usage

**Production:** Never launch this node. Use `anubix_vision` on the Jetson instead.

**Testing only:** If you need to test RPi nodes in isolation:
```bash
ros2 launch anubix_perception perception.launch.py
```

This will publish mock detection results on:
- `/perception/status` → always "found" after a delay
- `/perception/target_pose` → fixed dummy coordinates

## Migration Notes

If you're working on the codebase:
- All **actual** vision/perception code is in `anubix_ws/src/anubix_vision/`
- This package is **not** included in `rpi_full.launch.py`
- Do not add features here - they belong in `anubix_vision` on Jetson
