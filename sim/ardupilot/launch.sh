#!/bin/bash
# Launch ArduPilot SITL (Copter), headless. MAVLink is exposed on
# TCP 127.0.0.1:5760 (the autopilot's native SERIAL0). Connect QGC or
# capture.py to that endpoint, or run mavproxy.py to fan out to UDP.
#
# Requires ARDUPILOT_DIR pointing at a built ardupilot tree.
# See sim/README.md for one-time setup.
#
# Usage:
#   launch.sh [model]
#     model defaults to '+'  (basic quad). Other useful values:
#                          'quad', 'hexa', 'X', 'iris'.

set -euo pipefail

MODEL="${1:-+}"
INSTANCE="${INSTANCE:-0}"
SPEEDUP="${SPEEDUP:-1}"

if [[ -z "${ARDUPILOT_DIR:-}" ]]; then
    echo "ERROR: ARDUPILOT_DIR not set." >&2
    echo "  export ARDUPILOT_DIR=\"\$HOME/sim_tools/ardupilot\"" >&2
    exit 1
fi

if [[ ! -d "$ARDUPILOT_DIR" ]]; then
    echo "ERROR: ARDUPILOT_DIR does not exist: $ARDUPILOT_DIR" >&2
    exit 1
fi

ARDUCOPTER="$ARDUPILOT_DIR/build/sitl/bin/arducopter"
DEFAULTS="$ARDUPILOT_DIR/Tools/autotest/default_params/copter.parm"
EXTRA_DEFAULTS="$(dirname "$0")/camera_defaults.parm"
if [[ -f "$EXTRA_DEFAULTS" ]]; then
    DEFAULTS="${DEFAULTS},${EXTRA_DEFAULTS}"
fi
# Optional comma-separated list of additional .parm files chained at boot,
# e.g.  EXTRA_PARMS=$ARDUPILOT_DIR/Tools/autotest/default_params/copter-optflow.parm
# for a GPS-denied / optical-flow EKF profile. See sim/README.md.
if [[ -n "${EXTRA_PARMS:-}" ]]; then
    DEFAULTS="${DEFAULTS},${EXTRA_PARMS}"
fi
if [[ ! -x "$ARDUCOPTER" ]]; then
    echo "ERROR: arducopter binary not found at $ARDUCOPTER" >&2
    echo "  build it with:  cd \$ARDUPILOT_DIR && ./waf configure --board sitl && ./waf copter" >&2
    exit 1
fi

cd "$ARDUPILOT_DIR"

echo "launching ArduPilot SITL"
echo "  vehicle    : ArduCopter"
echo "  model      : $MODEL"
echo "  instance   : $INSTANCE   (TCP port = $((5760 + 10*INSTANCE)))"
echo "  speedup    : $SPEEDUP"
echo "  MAVLink    : tcp://127.0.0.1:$((5760 + 10*INSTANCE))   (use as -c arg to capture.py)"
echo "  dataflash  : logs/      (ArduPilot .bin logs)"
echo

exec "$ARDUCOPTER" \
    -S \
    --model "$MODEL" \
    --speedup "$SPEEDUP" \
    --slave 0 \
    --defaults "$DEFAULTS" \
    --sim-address=127.0.0.1 \
    -I"$INSTANCE"
