#!/bin/bash
# Launch PX4 SITL + Gazebo. QGC auto-connects on UDP 14550.
#
# Requires PX4_AUTOPILOT_DIR pointing at a built PX4-Autopilot tree.
# See sim/README.md for one-time setup.
#
# Usage:
#   launch.sh [airframe]      airframe defaults to gz_x500

set -euo pipefail

AIRFRAME="${1:-gz_x500}"

if [[ -z "${PX4_AUTOPILOT_DIR:-}" ]]; then
    echo "ERROR: PX4_AUTOPILOT_DIR not set." >&2
    echo "  export PX4_AUTOPILOT_DIR=\"\$HOME/sim_tools/PX4-Autopilot\"" >&2
    exit 1
fi

if [[ ! -d "$PX4_AUTOPILOT_DIR" ]]; then
    echo "ERROR: PX4_AUTOPILOT_DIR does not exist: $PX4_AUTOPILOT_DIR" >&2
    exit 1
fi

cd "$PX4_AUTOPILOT_DIR"

echo "launching PX4 SITL: airframe=$AIRFRAME"
echo "  MAVLink for QGC : udp://:14550"
echo "  ground-truth log: build/px4_sitl_default/rootfs/log/"
echo

exec make "px4_sitl" "$AIRFRAME"
