#!/bin/bash
# Launch PX4 SITL + Gazebo inside the official PX4 simulation container.
# QGC auto-connects on UDP 14550. capture.py also subscribes there.
#
# Requires:
#   - docker or podman on PATH (this host uses podman in docker-emulation)
#   - PX4_AUTOPILOT_DIR pointing at a host clone of PX4/PX4-Autopilot
#   - For GUI mode: an X server (your desktop session)
#
# Usage:
#   launch.sh [airframe]              airframe defaults to gz_x500
#   HEADLESS=1 launch.sh              run without Gazebo GUI
#   PX4_IMAGE=<other> launch.sh       override container image
#
# See sim/README.md for one-time setup.

set -euo pipefail

AIRFRAME="${1:-gz_x500}"
PX4_IMAGE="${PX4_IMAGE:-docker.io/px4io/px4-dev-simulation-jammy:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-px4-sitl}"
HEADLESS="${HEADLESS:-0}"

if command -v podman >/dev/null 2>&1; then
    RUNTIME=podman
elif command -v docker >/dev/null 2>&1; then
    RUNTIME=docker
else
    echo "ERROR: neither podman nor docker on PATH." >&2
    exit 1
fi

if [[ -z "${PX4_AUTOPILOT_DIR:-}" ]]; then
    PX4_AUTOPILOT_DIR="$HOME/sim_tools/PX4-Autopilot"
fi
if [[ ! -d "$PX4_AUTOPILOT_DIR" ]]; then
    echo "ERROR: PX4_AUTOPILOT_DIR does not exist: $PX4_AUTOPILOT_DIR" >&2
    echo "  clone with: git clone --recursive https://github.com/PX4/PX4-Autopilot.git \\" >&2
    echo "              \"$PX4_AUTOPILOT_DIR\"" >&2
    exit 1
fi

# Build runtime args. SELinux hosts (Rocky) need :Z on bind mounts.
MOUNT_FLAG=":Z"
[[ "$RUNTIME" = "docker" ]] && MOUNT_FLAG=""

RUN_ARGS=(
    --rm -it
    --name "$CONTAINER_NAME"
    --network host
    -w /src/PX4-Autopilot
    -v "${PX4_AUTOPILOT_DIR}:/src/PX4-Autopilot${MOUNT_FLAG}"
    -e LOCAL_USER_ID="$(id -u)"
)

if [[ "$HEADLESS" = "1" ]]; then
    RUN_ARGS+=( -e HEADLESS=1 )
    GUI_NOTE="(headless: no Gazebo window)"
else
    # GUI: forward X11. xhost permission is best-effort; user runs it once.
    if command -v xhost >/dev/null 2>&1; then
        xhost +SI:localuser:"$(id -un)" >/dev/null 2>&1 || true
    fi
    RUN_ARGS+=(
        -e "DISPLAY=${DISPLAY:-:0}"
        -e QT_X11_NO_MITSHM=1
        -v /tmp/.X11-unix:/tmp/.X11-unix:rw
    )
    [[ "$RUNTIME" = "podman" ]] && RUN_ARGS+=( --security-opt label=disable )
    GUI_NOTE="(GUI: X11 forwarded via DISPLAY=${DISPLAY:-:0})"
fi

cat <<EOF
launching PX4 SITL in container
  runtime  : $RUNTIME
  image    : $PX4_IMAGE
  airframe : $AIRFRAME  $GUI_NOTE
  source   : $PX4_AUTOPILOT_DIR  ->  /src/PX4-Autopilot
  MAVLink  : udp://:14550 (host network)
EOF

exec "$RUNTIME" run "${RUN_ARGS[@]}" "$PX4_IMAGE" \
    bash -c "make px4_sitl $AIRFRAME"
