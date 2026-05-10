#!/bin/bash
# =============================================================================
# ANUBIX — Raspberry Pi  ·  One-Command Setup
# =============================================================================
#
# Run ONE command on a fresh Raspberry Pi (Ubuntu 22.04 arm64):
#
#   bash <(curl -fsSL https://raw.githubusercontent.com/AbdelrahmanAtef01/ANUBIX_RASPBERRY_WS/main/install_rpi.sh)
#
# Or if you already cloned:
#
#   chmod +x install_rpi.sh && ./install_rpi.sh
#
# What this script does (fully automatic, no extra input needed):
#   1.  Clones ANUBIX_RASPBERRY_WS → ~/anubix_rpi_ws   (skip if already present)
#   2.  Installs ROS 2 Humble                           (skip if already present)
#   3.  Installs build tools (colcon, rosdep)
#   4.  Installs Python dependencies
#   5.  Builds the workspace with colcon
#   6.  Configures eth0 with static IP 192.168.10.2/24
#   7.  Writes a persistent netplan config              (survives reboots)
#   8.  Copies & patches the CycloneDDS XML
#   9.  Writes all env vars to ~/.bashrc
#  10.  Prints the single launch command
#
# After this script finishes just run:
#   source ~/.bashrc
#   ros2 launch anubix_bringup_rpi rpi_full.launch.py
# =============================================================================

set -eo pipefail

# ── Constants ─────────────────────────────────────────────────────────────────
REPO_URL="https://github.com/AbdelrahmanAtef01/ANUBIX_RASPBERRY_WS.git"
WS_DIR="$HOME/anubix_rpi_ws"
LOG_FILE="$WS_DIR/install_rpi.log"
RPI_IP="192.168.10.2"
JETSON_IP="192.168.10.1"
IFACE="eth0"     # RPi uses the built-in ethernet port

# ── Logging ───────────────────────────────────────────────────────────────────
mkdir -p "$WS_DIR" 2>/dev/null || true
log()  { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
warn() { log "WARNING: $*"; }
die()  { log "ERROR: $*"; exit 1; }

log "============================================================"
log "  ANUBIX Raspberry Pi — Full Setup"
log "  Log: $LOG_FILE"
log "============================================================"

# ── 0. Prerequisites ──────────────────────────────────────────────────────────
log ""
log "[0/9] Installing prerequisites (git, curl) ..."
sudo apt-get update -qq
sudo apt-get install -y git curl > /dev/null

# ── 1. Clone workspace ────────────────────────────────────────────────────────
log ""
log "[1/9] Setting up workspace at $WS_DIR ..."

if [ -d "$WS_DIR/.git" ]; then
    log "  Workspace already cloned — pulling latest..."
    git -C "$WS_DIR" pull --ff-only || warn "git pull failed — continuing with existing code"
else
    log "  Cloning $REPO_URL → $WS_DIR ..."
    git clone "$REPO_URL" "$WS_DIR" || die "git clone failed"
fi

LOG_FILE="$WS_DIR/install_rpi.log"
cd "$WS_DIR"

# ── 2. ROS 2 Humble ───────────────────────────────────────────────────────────
log ""
log "[2/9] Checking ROS 2 Humble ..."

if [ ! -f /opt/ros/humble/setup.bash ]; then
    log "  Installing ROS 2 Humble (this takes ~5 minutes) ..."

    sudo apt-get install -y locales > /dev/null
    sudo locale-gen en_US en_US.UTF-8
    sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
    export LANG=en_US.UTF-8

    sudo apt-get install -y software-properties-common > /dev/null
    sudo add-apt-repository -y universe > /dev/null
    sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
        -o /usr/share/keyrings/ros-archive-keyring.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
        | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y \
        ros-humble-ros-base \
        ros-humble-rmw-cyclonedds-cpp \
        || die "ROS 2 Humble install failed"
    log "  ROS 2 Humble installed."
else
    log "  ROS 2 Humble already installed."
fi

# ── 3. Build tools ────────────────────────────────────────────────────────────
log ""
log "[3/9] Installing build tools ..."

sudo apt-get install -y \
    python3-colcon-common-extensions \
    python3-rosdep \
    python3-pip \
    ros-humble-geometry-msgs \
    ros-humble-std-msgs \
    ros-humble-sensor-msgs \
    || die "apt install failed"

if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    sudo rosdep init 2>/dev/null || true
fi
rosdep update 2>&1 | tail -5

# ── 4. Python dependencies ────────────────────────────────────────────────────
log ""
log "[4/9] Installing Python dependencies ..."
pip3 install --quiet numpy || die "pip install failed"

# ── 5. Build workspace ────────────────────────────────────────────────────────
log ""
log "[5/9] Building ANUBIX RPi workspace (this takes ~2 minutes) ..."

. /opt/ros/humble/setup.bash

rosdep install --from-paths src --ignore-src -r -y 2>&1 | tail -5 \
    || warn "rosdep had errors (may be OK for placeholder packages)"

colcon build --symlink-install \
    --packages-select \
        anubix_navigation \
        anubix_rpi_bridge \
        anubix_bringup_rpi \
    2>&1 | tee -a "$LOG_FILE" \
    || die "colcon build failed — see $LOG_FILE for details"

log "  Build complete."

# ── 6. Network configuration ─────────────────────────────────────────────────
log ""
log "[6/9] Configuring direct ethernet link (RPi $IFACE → 192.168.10.2) ..."

if ip link show "$IFACE" > /dev/null 2>&1; then
    sudo ip addr flush dev "$IFACE" 2>/dev/null || true
    sudo ip addr add "${RPI_IP}/24" dev "$IFACE" 2>/dev/null || true
    sudo ip link set "$IFACE" up
    log "  Static IP ${RPI_IP}/24 assigned to $IFACE"

    if command -v netplan &>/dev/null; then
        sudo tee /etc/netplan/99-anubix-link.yaml > /dev/null << NETPLAN
network:
  version: 2
  ethernets:
    ${IFACE}:
      dhcp4: false
      addresses:
        - ${RPI_IP}/24
      optional: true
NETPLAN
        sudo netplan apply 2>/dev/null || warn "netplan apply failed"
        log "  Persistent netplan config written (survives reboots)"
    fi

    if ping -c 2 -W 2 -I "$IFACE" "$JETSON_IP" > /dev/null 2>&1; then
        log "  Jetson ($JETSON_IP) is reachable — link OK"
    else
        log "  Jetson not reachable yet (run install_jetson.sh on Jetson first)"
    fi
else
    warn "Interface $IFACE not found."
    warn "After setup, run: sudo ip addr add 192.168.10.2/24 dev <YOUR_IFACE>"
    warn "And edit: ~/.ros/rpi_cyclone.xml  (replace eth0 with your interface name)"
fi

# ── 7. DDS configuration ──────────────────────────────────────────────────────
log ""
log "[7/9] Installing CycloneDDS config ..."

mkdir -p "$HOME/.ros"
cp "$WS_DIR/dds_config/rpi_cyclone.xml" "$HOME/.ros/rpi_cyclone.xml"
log "  DDS config: $HOME/.ros/rpi_cyclone.xml"
log "  Interface: $IFACE (if your ethernet is not eth0, edit the XML)"

# ── 8. Shell environment ──────────────────────────────────────────────────────
log ""
log "[8/9] Writing environment to ~/.bashrc ..."

BASHRC="$HOME/.bashrc"
if ! grep -q "anubix_rpi_ws" "$BASHRC" 2>/dev/null; then
    cat >> "$BASHRC" << 'BASHRC_BLOCK'

# ── ANUBIX ROS 2 — Raspberry Pi ──────────────────────────────────────────────
source /opt/ros/humble/setup.bash
source $HOME/anubix_rpi_ws/install/setup.bash

# CycloneDDS unicast config for direct RPi↔Jetson ethernet link
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI=file://$HOME/.ros/rpi_cyclone.xml

# Must match the Jetson's ROS_DOMAIN_ID
export ROS_DOMAIN_ID=42
export ROS_LOCALHOST_ONLY=0
# ─────────────────────────────────────────────────────────────────────────────
BASHRC_BLOCK
    log "  Environment block written to ~/.bashrc"
else
    log "  ~/.bashrc already contains ANUBIX entries — skipping"
fi

# ── 9. Done ───────────────────────────────────────────────────────────────────
log ""
log "============================================================"
log "  ANUBIX RPi SETUP COMPLETE"
log "============================================================"
log ""
log "  To launch (run these 2 commands):"
log ""
log "    source ~/.bashrc"
log "    ros2 launch anubix_bringup_rpi rpi_full.launch.py"
log ""
log "  Verify ethernet link to Jetson:  ping 192.168.10.1"
log "  Log saved to: $LOG_FILE"
log "============================================================"
