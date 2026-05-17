# ANUBIX — Complete Testing & Verification Guide

Run these tests in order after installing on both machines.

**Recent fixes applied:**
- Navigation: Master now waits for terminal status ('point_reached', 'blocked', 'failure') instead of returning early on 'navigating' status
- Jetson bridge now forwards `/supervisor/nav_vision`, `/supervisor/robot_id`, and `/supervisor/task_id` to RPi
- Robot/task IDs now published on separate topics (not embedded in nav geometry) for cleaner architecture
- Spectrometer cloud model output parsing updated for "Control with virus" / "Control without virus" format (capital C)
- Perception/Vision stack now properly handles multiple consecutive requests (no longer ignores after first detection)
- Vision node confidence threshold lowered to 0.2 for better leaf detection
- Vision arm status callback now only logs when actively waiting for camera 2 calibration move
- Supabase uploader now uses last nav_goal position from `/master/last_nav_position` for plant_location
- Camera 2 now calculates depth (Z) using parallax from 1cm horizontal arm movement

> **For the real arm and real navigation rollouts, see the dedicated
> guides kept alongside the project (one level above this workspace,
> NOT inside either git repo):**
> - `REAL_ARM_STACK.md`
> - `REAL_NAVIGATION_STACK.md` — also contains the spec for the 2 Hz
>   live-location uploader that the real-nav implementer must add

---

## Phase 0: Pre-Launch Checks

### On Raspberry Pi

```bash
# 1. Verify environment is loaded
source ~/.bashrc
env | grep -E "ROS_|CYCLONE|RMW"

# Expected output:
# ROS_DOMAIN_ID=42
# RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# CYCLONEDDS_URI=file:///home/pi/.ros/rpi_cyclone.xml
# ROS_LOCALHOST_ONLY=0

# 2. Check network
ip addr show eth0
# Should show: 192.168.10.2/24

# 3. Ping Jetson
ping -c 3 192.168.10.1
# Should get replies

# 4. Verify DDS config
cat ~/.ros/rpi_cyclone.xml | grep -A2 "NetworkInterface"
# Should show: <NetworkInterface name="eth0">
```

### On Jetson

```bash
# 1. Verify environment is loaded
source ~/.bashrc
env | grep -E "ROS_|CYCLONE|RMW|OMNI|SUPABASE"

# Expected output includes:
# ROS_DOMAIN_ID=42
# RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
# OMNI_KEY=olink_4ekYIgHACfZaGlq6WJOgu59U
# SUPABASE_URL=https://bdkutmmrcjckaazzzspe.supabase.co
# SUPABASE_KEY=sb_publishable_VY6...

# 2. Check network (look for USB-C ethernet interface)
ip addr show
# Should show 192.168.10.1/24 on usb0/enx*/enp*

# 3. Ping RPi
ping -c 3 192.168.10.2
# Should get replies

# 4. Verify DDS config interface name matches
cat ~/.ros/jetson_cyclone.xml | grep -A2 "NetworkInterface"
# Should show your actual interface name (e.g., <NetworkInterface name="usb0">)

# 5. Check YOLO model exists
ls -lh ~/anubix_ws/best.engine
# Should show the TensorRT model file

# 6. Check USB camera (optional, for vision testing)
ls /dev/video*
# Should show /dev/video0 (or similar)
```

---

## Phase 1: Launch Both Systems

### Terminal 1 — Raspberry Pi

```bash
source ~/.bashrc
ros2 launch anubix_bringup_rpi rpi_full.launch.py
```

**Expected output:**
```
[anubix_navigation]: Node ready (placeholder mode)
[anubix_rpi_bridge]: RPi bridge ready | publishing heartbeat at 1 Hz
[anubix_rpi_bridge]: Listening for Jetson heartbeat on /bridge/jetson_heartbeat
```

### Terminal 2 — Jetson

```bash
source ~/.bashrc
ros2 launch anubix_bringup jetson.launch.py
```

**Expected output:**
```
[anubix_master]: ANUBIX ROS 2 Master Node - Jetson Orin Nano
[anubix_master]: 4-stack architecture: NAV | PERCEPTION | ARM | SPECTRO
[anubix_master]: Listening on agent "ANUBIX" (memory at X msgs)
[anubix_arm]: Arm control node ready (placeholder mode)
[anubix_spectrometer]: Node ready | mode=simulated | channels=257
[anubix_vision]: ANUBIX Vision Node — Jetson Orin Nano
[anubix_vision]: Model: ../best.engine
[anubix_vision]: RealSense SDK: available/NOT found
[anubix_jetson_bridge]: Jetson bridge ready | publishing heartbeat at 1 Hz
[anubix_supabase_uploader]: ANUBIX Supabase Uploader Node
```

---

## Phase 1.5: Laptop → Jetson SSH Port Forward (required for OmniLink)

The master node on the Jetson runs an HTTP tool-callback server on
**port 5055**. OmniLink's web UI is loaded in the **laptop's browser**
and its Content-Security-Policy only allows requests to `localhost/*`.
To bridge the two, open one SSH tunnel from the laptop that forwards
`localhost:5055` → `jetson:5055`.

### On the LAPTOP (where the browser runs)

Open a new terminal **on the laptop** (NOT on the Pi, NOT on the
Jetson):

```bash
# Replace 192.168.1.10 with the Jetson's LAN IP if different.
ssh -L 5055:localhost:5055 anubix@192.168.1.10
```

**Keep this shell open for the entire session.** Closing it kills the
tunnel and OmniLink tool calls start failing with
`ERR_CONNECTION_REFUSED`.

Verify it works:

```bash
# On the laptop:
curl -i http://localhost:5055/tool
# 200 / 405 / JSON from the master = tunnel is alive.
# "Connection refused" = master not running on Jetson.
# "Failed to connect" = SSH tunnel is not up.
```

---

## Phase 2: Connectivity Tests

Open **Terminal 3 on Jetson** (or RPi, doesn't matter — topics are shared):

```bash
source ~/.bashrc

# 1. List all topics — should see topics from BOTH machines
ros2 topic list
```

**Expected topics (partial list):**
```
/supervisor/nav_goal
/supervisor/nav_vision          ← Navigation vision flag (True=vision-based approach)
/supervisor/robot_id            ← Robot ID (latched, forwarded to RPi nav stack)
/supervisor/task_id             ← Task ID (latched, forwarded to RPi nav stack)
/supervisor/perception_goal
/supervisor/target_camera
/supervisor/arm_nav_goal
/supervisor/grip
/supervisor/spectral_target
/supervisor/force_stop
/arm/current_pose
/nav/status
/perception/status
/perception/target_pose
/arm/arm_status
/arm/gripper_status
/arm/touch_status
/spectrometer/status
/spectrometer/result
/supabase/upload_status
/bridge/jetson_heartbeat
/bridge/rpi_heartbeat
/bridge/connection_status
```

```bash
# 2. Check heartbeats — should see messages at 1 Hz from BOTH sides
ros2 topic echo /bridge/jetson_heartbeat --once
ros2 topic echo /bridge/rpi_heartbeat --once

# 3. Check connection status
ros2 topic echo /bridge/connection_status --once
# Should show: jetson_alive: true, rpi_alive: true

# 4. Monitor bridge logs (look for "ESTABLISHED" and no ERROR messages)
ros2 topic echo /rosout | grep -i bridge
```

**✅ If you see topics from both machines and heartbeats flowing → DDS link is working**

---

## Phase 3: Stack-by-Stack Manual Tests

### Test 1: Navigation Stack (runs on RPi)

```bash
# Terminal 3 — Publish robot_id and task_id (latched, set before nav_goal)
ros2 topic pub --once /supervisor/robot_id std_msgs/String \
  '{data: "34a957fd-d45c-4dbf-8e02-be8e1b5e349a"}'
ros2 topic pub --once /supervisor/task_id std_msgs/String \
  '{data: "40e4060b-5bc8-4044-9d71-046fee27a757"}'

# Terminal 3 — Send a navigation goal
ros2 topic pub --once /supervisor/nav_goal geometry_msgs/PoseStamped \
  '{header: {frame_id: "map"}, pose: {position: {x: 3.0, y: 5.0, z: 0.0}, orientation: {w: 1.0}}}'

# Watch Terminal 1 (RPi) — should see:
# [NAV] robot_id = "34a957fd-d45c-4dbf-8e02-be8e1b5e349a"
# [NAV] task_id = "40e4060b-5bc8-4044-9d71-046fee27a757"
# [NAV] Goal RECEIVED: (3.000, 5.000) frame="map" vision=False
# [NAV] robot_id='34a957fd-...' task_id='40e4060b-...'

# Terminal 3 — Check navigation status
ros2 topic echo /nav/status --once
# Should show: data: 'point_reached'
```

### Test 2: Arm Stack (runs on Jetson)

```bash
# Terminal 3 — Send arm navigation goal
ros2 topic pub --once /supervisor/arm_nav_goal geometry_msgs/PoseStamped \
  '{header: {frame_id: "base_link"}, pose: {position: {x: 0.3, y: 0.2, z: 0.15}, orientation: {w: 1.0}}}'

# Watch Terminal 2 (Jetson) — should see:
# [anubix_arm]: Goal received: (0.300, 0.200, 0.150)
# [anubix_arm]: Move complete: (0.300, 0.200, 0.150)

# Terminal 3 — Check arm status
ros2 topic echo /arm/arm_status --once
# Should show: data: 'success'

# Test gripper
ros2 topic pub --once /supervisor/grip std_msgs/Bool '{data: true}'

# Terminal 3 — Check gripper status
ros2 topic echo /arm/gripper_status --once
# Should show: data: 'successful_grip'

ros2 topic echo /arm/touch_status --once
# Should show: data: true
```

### Test 3: Spectrometer Stack (runs on Jetson)

```bash
# Terminal 3 — Trigger spectrometer scan (task: disease)
ros2 topic pub --once /supervisor/spectral_target std_msgs/String '{data: "disease"}'

# Watch Terminal 2 (Jetson) — should see:
# [SPECTRO] Target RECEIVED: task="disease"
# [SPECTRO] Status published: "reading"
# [SPECTRO] Status published: "applying_ML"
# [SPECTRO] Analysis complete: classification="healthy" value=0.0000
# [SPECTRO] Status published: "success"
# [SPECTRO] Result published to /spectrometer/result

# Terminal 3 — Check spectrometer status
ros2 topic echo /spectrometer/status --once
# Should show: data: 'success'

# Check spectrometer result (JSON)
ros2 topic echo /spectrometer/result --once
# Should show JSON like:
# data: '{"task_type":"disease","value":0.0,"classification":"healthy","details":{...},...}'
# OR if infected:
# data: '{"task_type":"disease","value":1.0,"classification":"infected","details":{...},...}'
```

### Test 4: Supabase Uploader (runs on Jetson, triggered by spectrometer)

```bash
# Terminal 3 — After spectrometer publishes result, watch Supabase node
# Watch Terminal 2 (Jetson) — should see:
# [anubix_supabase_uploader]: /spectrometer/result received [total=1]
# [anubix_supabase_uploader]: Step 1/2 — capturing plant photo from USB camera
# [anubix_supabase_uploader]: Opening USB camera index=0
# [anubix_supabase_uploader]: Photo saved locally: /tmp/anubix_scan_...jpg
# [anubix_supabase_uploader]: Photo uploaded → https://...supabase.co/storage/.../plant-images/scan_...jpg
# [anubix_supabase_uploader]: Step 2/2 — building ReadingModel
# [anubix_supabase_uploader]: DB insert attempt 1/3
# [anubix_supabase_uploader]: INSERT SUCCESS

# Terminal 3 — Check upload status
ros2 topic echo /supabase/upload_status --once
# Should show: data: 'success'
```

**Note:** 
- If camera is not available, node will log a warning but DB insert still proceeds (photo_url = null).
- Cloud model returns "control with virus" → disease_detected=true, disease_name="TMV"
- Cloud model returns "control without virus" → disease_detected=false, disease_name="none"

### Test 5: Vision Stack (runs on Jetson)

**Note:** Vision/perception stack now properly handles multiple consecutive requests. You can send detection goals multiple times and they will all be processed correctly.

#### Camera 1 (RealSense) test — only if you have RealSense connected:

```bash
# Terminal 3 — Set camera to RealSense
ros2 topic pub --once /supervisor/target_camera std_msgs/String '{data: "1"}'

# Trigger perception (task: disease)
ros2 topic pub --once /supervisor/perception_goal std_msgs/String '{data: "disease"}'

# Watch Terminal 2 (Jetson) — should see:
# [anubix_vision]: perception_goal received: task="disease" camera=1
# [anubix_vision]: Pipeline start — task="disease" camera=1
# [anubix_vision]: RealSense pipeline started
# [anubix_vision]: TARGET LEAF pixel=(320,240) 3D=(0.450, 0.120, 0.850) m depth=0.850 m

# Terminal 3 — Check perception status
ros2 topic echo /perception/status --once
# Should show: data: 'found'

ros2 topic echo /perception/target_pose --once
# Should show 3D position in metres
```

#### Camera 2 (USB mono) test — requires arm calibration:

```bash
# Terminal 3 — Set camera to USB
ros2 topic pub --once /supervisor/target_camera std_msgs/String '{data: "2"}'

# Trigger perception
ros2 topic pub --once /supervisor/perception_goal std_msgs/String '{data: "disease"}'

# Watch Terminal 2 (Jetson) — should see:
# [anubix_vision]: perception_goal received: task="disease" camera=2
# [anubix_vision]: USB Phase 1 — searching for initial leaf position
# [anubix_vision]: Phase 1 complete — centroid_1=(320, 240)
# [anubix_vision]: Sending calibration arm move: 1 cm right (frame_id=calibration)
# [anubix_vision]: Waiting for arm confirmation (timeout=30 s)
# [anubix_arm]: Goal received: (0.010, 0.000, 0.000)  ← arm receives calibration move
# [anubix_arm]: Move complete: (0.010, 0.000, 0.000)
# [anubix_vision]: Arm move confirmed — starting Phase 2
# [anubix_vision]: USB Phase 2 — searching for leaf after arm move
# [anubix_vision]: Phase 2 complete — centroid_2=(340, 240)
# [anubix_vision]: Calibration: 1 cm = 20.00 px | offset from grabber: dx=1.00 cm, dy=0.00 cm

# Terminal 3 — Check perception status
ros2 topic echo /perception/status --once
# Should show: data: 'found'

ros2 topic echo /perception/target_pose --once
# Should show relative position (x in cm converted to m)
```

---

## Phase 4: End-to-End Mission Test via OmniLink

This tests the full loop: OmniLink AI → Master → All Stacks → Feedback to AI.

### On the OmniLink Web UI

1. Go to https://omnilink.ai (or wherever the agent is hosted)
2. Find agent "ANUBIX" (or create one with the profile from your original files)
3. Send this mission in the chat:

```
Go to plant at coordinates 3,5. Check for disease using camera 1. If found, move the arm to the target and grip it. Then run the spectrometer to confirm disease status.
```

### Watch All Terminals

**Terminal 2 (Jetson) — You should see:**

```
[anubix_master]: [POLL] 1 command(s) detected
[anubix_master]: [CMD] supervisor/nav_goal_3_5
[anubix_master]: [TX] /supervisor/nav_goal (3.00, 5.00)
[anubix_navigation]: Goal received: (3.000, 5.000)        ← on RPi terminal
[anubix_navigation]: Move complete: (3.000, 5.000)
[anubix_master]: [RX] /nav/status = "navigating"
[anubix_master]: [RX] /nav/status = "point_reached"
[anubix_master]: [FEEDBACK -> ANUBIX] /nav/status: point_reached
[anubix_master]: [POLL] 2 command(s) detected
[anubix_master]: [CMD] supervisor/target_camera_1
[anubix_master]: [TX] /supervisor/target_camera 1
[anubix_master]: [CMD] supervisor/perception_goal_disease
[anubix_master]: [TX] /supervisor/perception_goal disease
[anubix_vision]: perception_goal received: task="disease" camera=1
...
[anubix_vision]: TARGET LEAF pixel=(320,240) 3D=(0.450, 0.120, 0.850) m
[anubix_master]: [RX] /perception/status = found
[anubix_master]: [FEEDBACK -> ANUBIX] /perception/status: found
[anubix_master]: [CMD] supervisor/arm_nav_goal_move
[anubix_master]: [TX] /supervisor/arm_nav_goal (signal=move, dest=target)
[anubix_arm]: Goal received: (0.450, 0.120, 0.850)
[anubix_arm]: Move complete: (0.450, 0.120, 0.850)
[anubix_master]: [RX] /arm/arm_status = success
[anubix_master]: [CMD] supervisor/grip_true
[anubix_master]: [TX] /supervisor/grip true
[anubix_arm]: Grip closed - touch confirmed
[anubix_master]: [RX] /arm/gripper_status = successful_grip
[anubix_master]: [RX] /arm/touch_status = true
[anubix_master]: [FEEDBACK -> ANUBIX] /arm/gripper_status: successful_grip
/arm/touch_status: true
[anubix_master]: [CMD] supervisor/spectral_target_disease
[anubix_master]: [TX] /supervisor/spectral_target disease
[anubix_spectrometer]: Target received: disease
[anubix_spectrometer]: Status: reading
[anubix_spectrometer]: Status: applying_ML
[anubix_spectrometer]: Status: success
[anubix_master]: [RX] /spectrometer/status = success
[anubix_master]: [FEEDBACK -> ANUBIX] /spectrometer/status: success
robot_id: 34a957fd-d45c-4dbf-8e02-be8e1b5e349a
task_id: 40e4060b-5bc8-4044-9d71-046fee27a757
[anubix_supabase_uploader]: /spectrometer/result received
[anubix_supabase_uploader]: Step 1/2 — capturing plant photo
[anubix_supabase_uploader]: Photo uploaded → https://...
[anubix_supabase_uploader]: Upload SUCCESS on attempt 1
[anubix_master]: [DONE] No more commands - mission complete
```

**Terminal 1 (RPi) — You should see:**

```
[anubix_navigation]: Goal received: (3.000, 5.000)
[anubix_navigation]: Move complete: (3.000, 5.000)
[anubix_rpi_bridge]: [DIAGNOSTICS] Jetson heartbeat OK (last seen 0.2s ago)
```

### Check OmniLink Chat

The AI agent should respond with something like:

```
Mission complete. I navigated to plant at (3, 5), detected a leaf using the depth camera, moved the arm to position (0.45m, 0.12m, 0.85m), successfully gripped it (touch sensor confirmed), and ran the spectrometer. The spectral analysis shows the plant is healthy. The reading has been uploaded to Supabase with robot_id 34a957fd-d45c-4dbf-8e02-be8e1b5e349a and task_id 40e4060b-5bc8-4044-9d71-046fee27a757.
```

---

## Phase 5: Verify Supabase Upload

1. Go to your Supabase dashboard: https://supabase.com/dashboard
2. Navigate to **Table Editor** → `readings` table
3. You should see a new row with:
   - `reading_id`: (auto-generated UUID)
   - `robot_id`: 34a957fd-d45c-4dbf-8e02-be8e1b5e349a
   - `task_id`: 40e4060b-5bc8-4044-9d71-046fee27a757
   - `plant_location`: "3.00,5.00" (the last nav_goal coordinates)
   - `disease_detected`: true (if "control with virus") or false (if "control without virus")
   - `disease_name`: "TMV" (if infected) or "none" (if healthy)
   - `photo_1_url`: https://bdkutmmrcjckaazzzspe.supabase.co/storage/v1/object/public/plant-images/scan_...jpg
   - `recorded_at`: timestamp

4. Click the photo URL — should open the captured plant image in your browser

**Cloud model output mapping:**
- "control with virus" → disease_detected=true, disease_name="TMV"
- "control without virus" → disease_detected=false, disease_name="none"

---

## Phase 6: Emergency Stop Test

```bash
# Terminal 3 — Trigger emergency stop
ros2 topic pub --once /supervisor/force_stop std_msgs/Bool '{data: true}'

# Watch Terminal 1 (RPi) — should see:
# [anubix_rpi_bridge]: ALERT: Force stop received from Jetson
# [anubix_navigation]: Ignoring nav_goal - force stopped

# Watch Terminal 2 (Jetson) — should see:
# [anubix_master]: *** FORCE STOP PUBLISHED ***
# [anubix_arm]: Ignoring arm_goal - force stopped
# [anubix_spectrometer]: Ignoring - force stopped
# [anubix_vision]: Force stop — aborting pipeline

# Try sending a command — should be ignored:
ros2 topic pub --once /supervisor/nav_goal geometry_msgs/PoseStamped \
  '{header: {frame_id: "map"}, pose: {position: {x: 1.0, y: 1.0, z: 0.0}, orientation: {w: 1.0}}}'

# Terminal 1 — should see:
# [anubix_navigation]: Ignoring - force stopped

# To recover: restart both launch files (Ctrl+C, then relaunch)
```

---

## Troubleshooting Commands

### If topics don't appear across machines

```bash
# On both machines:
ros2 daemon stop && ros2 daemon start

# Check DDS discovery:
ros2 topic list -v
ros2 node list

# Check if the peer address is correct:
cat ~/.ros/jetson_cyclone.xml | grep Peer
cat ~/.ros/rpi_cyclone.xml | grep Peer

# Manually test DDS with a simple publisher/subscriber:
# Terminal on Jetson:
ros2 topic pub /test std_msgs/String '{data: "hello from jetson"}'

# Terminal on RPi:
ros2 topic echo /test
# Should see: data: 'hello from jetson'
```

### If OmniLink doesn't respond

```bash
# Check if the master is actually polling:
# Terminal 2 (Jetson) — look for periodic log lines like:
# [anubix_master]: [POLL] ...

# Check the OmniLink agent name matches:
ros2 param get /anubix_master agent_name
# Should return: ANUBIX

# Test OmniLink key directly (outside ROS):
python3 -c "
from omnilink.client import OmniLinkClient
client = OmniLinkClient(omni_key='olink_4ekYIgHACfZaGlq6WJOgu59U')
memory = client.get_memory('ANUBIX')
print(f'Memory length: {len(memory)} messages')
"
```

### If camera doesn't work

```bash
# Check if camera device exists:
ls -l /dev/video*

# Test camera capture manually:
python3 << 'EOF'
import cv2
cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
if not cap.isOpened():
    print("ERROR: Cannot open camera")
else:
    ret, frame = cap.read()
    print(f"Capture OK: {ret}, frame shape: {frame.shape if ret else 'N/A'}")
    cap.release()
EOF

# Check RealSense (if you have it):
rs-enumerate-devices
# Should list connected RealSense cameras
```

### If Supabase upload fails

```bash
# Watch the Supabase node logs closely — it logs every attempt:
ros2 topic echo /rosout | grep SUPABASE

# Test Supabase connection directly:
python3 << 'EOF'
from supabase import create_client
url = "https://bdkutmmrcjckaazzzspe.supabase.co"
key = "sb_publishable_VY6-Jjc6f20Wcbb3Rm8gwg_ZK6CYuh3"
client = create_client(url, key)
result = client.table('readings').select('*').limit(1).execute()
print(f"Supabase connection OK, found {len(result.data)} rows")
EOF
```

---

## Summary of Success Indicators

✅ **Network**: Both machines can ping each other  
✅ **DDS**: Topics from both sides visible with `ros2 topic list`  
✅ **Heartbeats**: `/bridge/jetson_heartbeat` and `/bridge/rpi_heartbeat` flowing at 1 Hz  
✅ **Navigation**: Publishes `point_reached` on `/nav/status`  
✅ **Arm**: Publishes `success` on `/arm/arm_status`, `successful_grip` on `/arm/gripper_status`  
✅ **Spectrometer**: Publishes `success` on `/spectrometer/status`, JSON on `/spectrometer/result`  
✅ **Vision**: Publishes `found` on `/perception/status`, 3D Pose on `/perception/target_pose`  
✅ **Supabase**: Publishes `success` on `/supabase/upload_status`, new row appears in dashboard  
✅ **OmniLink**: Master sends feedback, AI responds with next command, full mission completes  

**If all these pass → ANUBIX is fully operational 🚀**
