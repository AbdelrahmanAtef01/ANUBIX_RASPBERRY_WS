#!/bin/bash
# =============================================================================
# Raspberry Pi — Direct Ethernet to Jetson Orin Nano
# =============================================================================
# Configures the ethernet interface with a static IP for the
# point-to-point link to the Jetson.
#
# Tested on: Raspberry Pi OS (Debian Bookworm/Trixie) 64-bit
#
# RPi    → 192.168.10.2/24
# Jetson → 192.168.10.1/24
#
# Usage:
#   sudo ./configure_rpi_network.sh [INTERFACE]
#
# INTERFACE defaults to "eth0". Override with:
#   sudo ./configure_rpi_network.sh eth1
# =============================================================================

set -eo pipefail

RPI_IP="192.168.10.2"
JETSON_IP="192.168.10.1"
PREFIX="24"
IFACE="${1:-eth0}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
die() { log "ERROR: $*"; exit 1; }

log "Raspberry Pi direct-link ethernet setup"
log "Interface: $IFACE  IP: $RPI_IP/$PREFIX  Peer: $JETSON_IP"

ip link show "$IFACE" > /dev/null 2>&1 \
    || die "Interface '$IFACE' not found. Run 'ip link show' to list interfaces."

ip addr flush dev "$IFACE" 2>/dev/null || true
ip addr add "${RPI_IP}/${PREFIX}" dev "$IFACE"
ip link set "$IFACE" up
log "Assigned ${RPI_IP}/${PREFIX} to $IFACE"

log "Waiting for link..."
for i in $(seq 1 10); do
    if ip link show "$IFACE" | grep -q 'state UP\|LOWER_UP'; then
        log "Link is UP"
        break
    fi
    sleep 1
done

log "Pinging Jetson at $JETSON_IP (3 packets)..."
if ping -c 3 -W 2 -I "$IFACE" "$JETSON_IP" > /dev/null 2>&1; then
    log "SUCCESS: Jetson ($JETSON_IP) is reachable"
else
    log "WARNING: No ping reply from $JETSON_IP"
    log "  - Make sure the Jetson network is configured first"
    log "  - Check the ethernet cable connection"
fi

# ── Persist config (dhcpcd for Raspberry Pi OS, NetworkManager fallback) ─────
if systemctl is-active --quiet dhcpcd; then
    log "Detected dhcpcd — writing persistent config..."
    DHCPCD_CONF="/etc/dhcpcd.conf"
    if ! grep -q "# ANUBIX static IP" "$DHCPCD_CONF" 2>/dev/null; then
        cat >> "$DHCPCD_CONF" << DHCPCD

# ANUBIX static IP for direct Jetson link
interface ${IFACE}
static ip_address=${RPI_IP}/${PREFIX}
nolink
DHCPCD
        systemctl restart dhcpcd 2>/dev/null || log "  WARNING: dhcpcd restart failed"
        log "  dhcpcd config updated (survives reboots)"
    else
        log "  dhcpcd already contains ANUBIX config — skipping"
    fi

elif command -v nmcli &>/dev/null; then
    log "Detected NetworkManager — creating connection profile..."
    nmcli con add type ethernet \
        con-name anubix-link \
        ifname "$IFACE" \
        ipv4.method manual \
        ipv4.addresses "${RPI_IP}/${PREFIX}" \
        2>/dev/null || log "  nmcli profile creation failed (may already exist)"
    nmcli con up anubix-link 2>/dev/null || true
    log "  NetworkManager profile 'anubix-link' created"

else
    log "  Neither dhcpcd nor NetworkManager detected."
    log "  Config is temporary. To persist, manually edit /etc/network/interfaces"
fi

log ""
log "==================================================="
log "  RPi network configured"
log "  Interface : $IFACE"
log "  RPi IP    : $RPI_IP / $PREFIX"
log "  Jetson IP : $JETSON_IP (expected)"
log "==================================================="
