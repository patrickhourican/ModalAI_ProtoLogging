#!/bin/bash
# B1: thin wrapper around voxl-logger that captures IMU + GPS pipes.
#
# Runs on the drone (VOXL 2). Output lands in /data/voxl-logger/logNNNN/.
#
# Usage:
#   start_logging.sh [-t SECONDS] [-n NOTE] [-d OUTPUT_DIR]
#
# Defaults to running until ctrl-c.

set -euo pipefail

TIMEOUT=""
NOTE=""
OUT_DIR="/data/voxl-logger"

usage() {
    cat <<EOF
Usage: $(basename "$0") [-t seconds] [-n note] [-d output_dir]

  -t SECONDS    stop logging after SECONDS (default: run until ctrl-c)
  -n NOTE       short note appended to the log directory name
  -d OUT_DIR    base output directory (default: /data/voxl-logger)
  -h            this help

Pipes captured:
  imu_apps                (apps-proc IMU,  imu_data_t)
  imu_px4                 (sDSP IMU,       imu_data_t)
  mavlink_gps_raw_int     (GPS_RAW_INT,    mavlink_message_t -> raw)
  vvpx4_vehicle_gps       (vehicle GPS,    mavlink_message_t -> raw)

Note: GPS pipes are MAVLink and are written as raw mavlink_message_t
records by voxl-logger. Use voxl-clean-logger (B2) for decoded GPS CSV.
EOF
}

while getopts ":t:n:d:h" opt; do
    case "$opt" in
        t) TIMEOUT="$OPTARG" ;;
        n) NOTE="$OPTARG" ;;
        d) OUT_DIR="$OPTARG" ;;
        h) usage; exit 0 ;;
        *) usage; exit 1 ;;
    esac
done

if ! command -v voxl-logger >/dev/null 2>&1; then
    echo "ERROR: voxl-logger not found on PATH. Run this on a VOXL 2." >&2
    exit 1
fi

ARGS=(
    -d "$OUT_DIR"
    -i imu_apps
    -i imu_px4
    -m mavlink_gps_raw_int
    -m vvpx4_vehicle_gps
)
[[ -n "$TIMEOUT" ]] && ARGS+=( -t "$TIMEOUT" )
[[ -n "$NOTE"    ]] && ARGS+=( -n "$NOTE" )

echo "running: voxl-logger ${ARGS[*]}"
exec voxl-logger "${ARGS[@]}"
