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
#   launch.sh [airframe]              airframe defaults from $SIM
#   SIM=gz launch.sh                  gz_x500 in Gazebo (default; needs GPU)
#   SIM=jmavsim launch.sh             jmavsim_iris (Java/AWT, no GPU)
#   SIM=none launch.sh                none_iris (no simulator, MAVLink only)
#   HEADLESS=1 launch.sh              skip the simulator GUI window
#   GPU=1 launch.sh                   pass /dev/dri to use Intel iGPU (gz only)
#   PX4_IMAGE=<other> launch.sh       override container image
#
# See sim/README.md for one-time setup.

set -euo pipefail

SIM="${SIM:-gz}"
case "$SIM" in
    gz)      DEFAULT_AIRFRAME=gz_x500 ;;
    jmavsim) DEFAULT_AIRFRAME=jmavsim_iris ;;
    none)    DEFAULT_AIRFRAME=none_iris ;;
    *) echo "ERROR: SIM must be gz|jmavsim|none, got: $SIM" >&2; exit 1 ;;
esac

AIRFRAME="${1:-$DEFAULT_AIRFRAME}"
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
)

if [[ "$RUNTIME" = "podman" ]]; then
    # Rootless podman maps container UIDs to sub-UIDs on the host, which
    # breaks writes to bind-mounted source. --userns=keep-id maps our
    # host UID 1:1 into the container so build artifacts land back on
    # the host owned correctly. With keep-id we ARE the target user
    # already, so skip the image's LOCAL_USER_ID entrypoint (which
    # tries to usermod a UID that now collides) and exec bash directly.
    RUN_ARGS+=(
        --userns=keep-id
        --entrypoint=/bin/bash
        --replace
    )
else
    # docker (with the daemon's UID mapping) still needs the entrypoint
    # to switch from root to our UID via LOCAL_USER_ID.
    RUN_ARGS+=( -e LOCAL_USER_ID="$(id -u)" )
fi

# SIM=none has no simulator process, so no display is ever needed.
# SIM=jmavsim uses plain Java/AWT (no OpenGL) so X11 yes, GPU no.
# SIM=gz uses Gazebo: X11 yes, GPU strongly recommended.
NEEDS_DISPLAY=1
NEEDS_GPU=0
case "$SIM" in
    gz)      NEEDS_GPU=1 ;;
    jmavsim) NEEDS_GPU=0 ;;
    none)    NEEDS_DISPLAY=0 ;;
esac
[[ "$HEADLESS" = "1" ]] && NEEDS_DISPLAY=0

if [[ "$HEADLESS" = "1" ]]; then
    RUN_ARGS+=( -e HEADLESS=1 -e PX4_SIM_HEADLESS=1 )
    GUI_NOTE="(headless: no simulator window)"
elif [[ "$NEEDS_DISPLAY" = "0" ]]; then
    GUI_NOTE="(no GUI: SIM=$SIM has no simulator window)"
else
    # GUI: forward X11. xhost permission is best-effort; user runs it once.
    if command -v xhost >/dev/null 2>&1; then
        xhost +SI:localuser:"$(id -un)" >/dev/null 2>&1 || true
    fi
    RUN_ARGS+=(
        -e "DISPLAY=${DISPLAY:-:0}"
        -e QT_X11_NO_MITSHM=1
        -e XDG_RUNTIME_DIR=/tmp/runtime-rocky
        -v /tmp/.X11-unix:/tmp/.X11-unix:rw
    )
    [[ "$RUNTIME" = "podman" ]] && RUN_ARGS+=( --security-opt label=disable )
    GUI_NOTE="(GUI: X11 forwarded via DISPLAY=${DISPLAY:-:0})"

    # GPU rendering. Default is software (LIBGL_ALWAYS_SOFTWARE=1): slow
    # but works on any host. Set GPU=1 to pass the Intel iGPU through
    # via /dev/dri (mesa/iris driver, no NVIDIA toolkit required).
    GPU="${GPU:-0}"
    if [[ "$NEEDS_GPU" = "0" ]]; then
        :  # jmavsim doesn't use OpenGL; leave Mesa untouched
    elif [[ "$GPU" = "1" ]]; then
        RUN_ARGS+=(
            --device /dev/dri
            -e MESA_LOADER_DRIVER_OVERRIDE=iris
        )
        # /dev/dri/renderD* is owned by group 'render' on the host; the
        # container needs that GID added so the user can open the device.
        RENDER_GID="$(getent group render | cut -d: -f3 || true)"
        [[ -n "$RENDER_GID" ]] && RUN_ARGS+=( --group-add "$RENDER_GID" )
        GUI_NOTE="$GUI_NOTE (GPU: Intel iGPU via /dev/dri)"
    else
        RUN_ARGS+=( -e LIBGL_ALWAYS_SOFTWARE=1 )
        GUI_NOTE="$GUI_NOTE (GPU: software rendering; set GPU=1 to use Intel iGPU)"
    fi
fi

cat <<EOF
launching PX4 SITL in container
  runtime  : $RUNTIME
  image    : $PX4_IMAGE
  sim      : $SIM
  airframe : $AIRFRAME  $GUI_NOTE
  source   : $PX4_AUTOPILOT_DIR  ->  /src/PX4-Autopilot
  MAVLink  : udp://:14550 (host network)
EOF

# With --entrypoint=/bin/bash (podman path) args are passed straight
# to bash, so we use `-c "..."`. Docker keeps the image's entrypoint
# wrapper so we still need an explicit `bash -c "..."` after the image.
if [[ "$RUNTIME" = "podman" ]]; then
    exec "$RUNTIME" run "${RUN_ARGS[@]}" "$PX4_IMAGE" \
        -c "make px4_sitl $AIRFRAME"
else
    exec "$RUNTIME" run "${RUN_ARGS[@]}" "$PX4_IMAGE" \
        bash -c "make px4_sitl $AIRFRAME"
fi
