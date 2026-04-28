#!/bin/bash
# Launch QGroundControl on Rocky 9 (or any RHEL-family box).
#
# Assumes the AppImage has been extracted with:
#   cd ~/sim_tools && ./QGroundControl.AppImage --appimage-extract
# Override the location with QGC_DIR.
#
# Required one-time host fixes (see README.md):
#   sudo setsebool -P selinuxuser_execmod 1     # SELinux: allow QtQml JIT
#   sudo usermod -aG dialout $USER              # QGC startup pre-flight
#   sudo systemctl disable --now ModemManager   # QGC startup pre-flight
#
# Optional: set QGC_SOFTWARE_RENDER=1 to force software rendering on
# hosts with flaky/dual GPU drivers (NVIDIA Optimus, hybrid, etc.).

set -euo pipefail

QGC_DIR="${QGC_DIR:-$HOME/sim_tools/squashfs-root}"
APPRUN="$QGC_DIR/AppRun"

if [[ ! -x "$APPRUN" ]]; then
    echo "ERROR: QGC AppRun not found at $APPRUN" >&2
    echo "  extract the AppImage first:" >&2
    echo "    cd ~/sim_tools && ./QGroundControl.AppImage --appimage-extract" >&2
    echo "  or override:  QGC_DIR=/path/to/squashfs-root ./qgc.sh" >&2
    exit 1
fi

ENV_VARS=()
if [[ "${QGC_SOFTWARE_RENDER:-0}" == "1" ]]; then
    ENV_VARS+=("QT_QUICK_BACKEND=software" "LIBGL_ALWAYS_SOFTWARE=1")
fi

USER_NAME="$(id -un)"
in_dialout_now=0
in_dialout_group=0
id -Gn | tr ' ' '\n' | grep -qx dialout && in_dialout_now=1
getent group dialout | awk -F: '{print $4}' | tr ',' '\n' \
    | grep -qx "$USER_NAME" && in_dialout_group=1

echo "launching QGroundControl"
echo "  AppRun     : $APPRUN"
echo "  software   : ${QGC_SOFTWARE_RENDER:-0}"
echo "  MAVLink    : auto-binds UDP 14550"
echo

if [[ $in_dialout_now -eq 1 ]]; then
    exec env "${ENV_VARS[@]}" "$APPRUN"
elif [[ $in_dialout_group -eq 1 ]]; then
    echo "(wrapping with 'sg dialout' — group not yet active in this shell)"
    exec sg dialout -c "$(printf '%q ' "${ENV_VARS[@]}" "$APPRUN")"
else
    echo "WARN: $USER_NAME is not in 'dialout' group — QGC will likely exit at startup." >&2
    echo "  fix:  sudo usermod -aG dialout $USER_NAME" >&2
    exec env "${ENV_VARS[@]}" "$APPRUN"
fi
