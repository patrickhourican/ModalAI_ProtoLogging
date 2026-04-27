#!/bin/bash
# Pull voxl-logger flight folders from the drone to ./flights/.
#
# Usage:
#   pull_logs.sh <drone-ip-or-host> [remote-base-dir] [local-dest-dir]
#
# Defaults:
#   remote-base-dir  /data/voxl-logger
#   local-dest-dir   ./flights
#
# Requires: rsync + ssh access to the drone (root@<ip> by default for VOXL 2).

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: $(basename "$0") <drone-ip> [remote-dir] [local-dir]" >&2
    exit 1
fi

DRONE="$1"
REMOTE_DIR="${2:-/data/voxl-logger}"
LOCAL_DIR="${3:-flights}"
SSH_USER="${SSH_USER:-root}"

mkdir -p "$LOCAL_DIR"

echo "pulling ${SSH_USER}@${DRONE}:${REMOTE_DIR}/  ->  ${LOCAL_DIR}/"
rsync -avh --progress \
    -e "ssh -o StrictHostKeyChecking=accept-new" \
    "${SSH_USER}@${DRONE}:${REMOTE_DIR}/" \
    "${LOCAL_DIR}/"

echo "done. flights available under: ${LOCAL_DIR}/"
ls -1 "$LOCAL_DIR"
