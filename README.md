# ANUBIX — Raspberry Pi Workspace

ROS 2 workspace for the ANUBIX agricultural robot — **Raspberry Pi side**.

Runs on **Raspberry Pi OS (Debian Bookworm/Trixie) 64-bit**.

---

## What Runs Here

- **anubix_navigation**: Navigation stack (placeholder — receives goals via ROS topics)
- **anubix_rpi_bridge**: Cross-machine link monitor, heartbeat publisher, emergency watchdog

---

## Hardware Requirements

- **Raspberry Pi 4/5** (4GB+ RAM recommended)
- **Raspberry Pi OS 64-bit** (Debian Bookworm 12 or Trixie 13)
- **Ethernet cable** connected to Jetson Orin Nano via USB-C adapter

---

## One-Command Setup

```bash
git clone https://github.com/AbdelrahmanAtef01/ANUBIX_RASPBERRY_WS.git ~/anubix_rpi_ws
cd ~/anubix_rpi_ws
chmod +x install_rpi.sh
./install_rpi.sh
```

The script installs ROS 2 Humble, builds the workspace, configures the static IP (192.168.10.2), and writes all environment variables to `~/.bashrc`.

---

## Launch

After setup completes:

```bash
source ~/.bashrc
ros2 launch anubix_bringup_rpi rpi_full.launch.py
```

---

## Architecture

```
┌─────────────────────────────────────┐
│         Raspberry Pi                │
│         192.168.10.2                │
│                                     │
│  - anubix_navigation                │
│  - anubix_rpi_bridge                │
└──────────────┬──────────────────────┘
               │
               │ Direct Ethernet
               │ (CycloneDDS unicast)
               │
┌──────────────┴──────────────────────┐
│         Jetson Orin Nano            │
│         192.168.10.1                │
│                                     │
│  - anubix_master (OmniLink AI)      │
│  - anubix_arm                       │
│  - anubix_spectrometer              │
│  - anubix_vision (YOLO cameras)     │
│  - anubix_supabase                  │
│  - anubix_jetson_bridge             │
└─────────────────────────────────────┘
```

---

## Testing

See [TESTING.md](TESTING.md) for the complete verification guide.

---

## Network Configuration

- **RPi IP**: 192.168.10.2/24 on `eth0`
- **Jetson IP**: 192.168.10.1/24 (USB-C ethernet adapter)
- **DDS**: CycloneDDS with unicast peer discovery (no multicast)
- **ROS_DOMAIN_ID**: 42 (must match on both machines)

The install script detects **dhcpcd** (Raspberry Pi OS default) or **NetworkManager** and writes the appropriate persistent config.

---

## Manual Setup (if install script fails)

```bash
# 1. Clone repo
git clone https://github.com/AbdelrahmanAtef01/ANUBIX_RASPBERRY_WS.git ~/anubix_rpi_ws
cd ~/anubix_rpi_ws

# 2. Run individual setup scripts
chmod +x setup_rpi.sh configure_rpi_network.sh
./setup_rpi.sh
sudo ./configure_rpi_network.sh

# 3. Source environment
source ~/.bashrc

# 4. Launch
ros2 launch anubix_bringup_rpi rpi_full.launch.py
```

---

## Troubleshooting

### ROS 2 install fails on Raspberry Pi OS

Raspberry Pi OS (Debian) is not officially supported by ROS 2, but Humble works using the Ubuntu Jammy repository. If you get dependency errors:

```bash
sudo apt-get update
sudo apt-get install -f
```

### Topics don't appear from Jetson

```bash
# Check DDS peer address
cat ~/.ros/rpi_cyclone.xml | grep Peer
# Should show: <Peer address="192.168.10.1"/>

# Restart ROS daemon
ros2 daemon stop && ros2 daemon start

# Test simple pub/sub
ros2 topic echo /bridge/jetson_heartbeat
# Should see messages at 1 Hz if Jetson is running
```

### Network config doesn't persist after reboot

```bash
# Check if dhcpcd is running
systemctl status dhcpcd

# If not, manually edit dhcpcd.conf
sudo nano /etc/dhcpcd.conf

# Add at the end:
interface eth0
static ip_address=192.168.10.2/24
nolink
```

---

## Repository Structure

```
anubix_rpi_ws/
├── src/
│   ├── anubix_navigation/       # Nav stack placeholder
│   ├── anubix_rpi_bridge/       # Cross-machine link monitor
│   └── anubix_bringup_rpi/      # Launch files
├── dds_config/
│   └── rpi_cyclone.xml          # CycloneDDS unicast config
├── install_rpi.sh               # One-command setup
├── setup_rpi.sh                 # Manual setup (ROS + build)
├── configure_rpi_network.sh     # Manual network config
├── TESTING.md                   # Complete testing guide
└── README.md                    # This file
```

---

## License

MIT
