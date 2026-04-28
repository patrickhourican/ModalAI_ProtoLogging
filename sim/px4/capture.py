"""Capture a SITL flight from PX4 over MAVLink into our standard CSV
schema (host/parse_logs.py compatible).

Subscribes to HIGHRES_IMU and GPS_RAW_INT on udp://:14550 (default
PX4 SITL endpoint) and writes:

  <out>/clean/imu.csv         timestamp_ns, ax_ms2, ..., temp_c
  <out>/clean/gps.csv         timestamp_ns, time_usec, fix_type, lat_deg, ...
  <out>/clean/unified.csv     IMU rows + nearest-prior GPS fix
  <out>/info.json             capture metadata

Usage:
  python sim/px4/capture.py -o flights/sim_px4_<ts> -t 120
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
from pymavlink import mavutil

CONNECTION_DEFAULT = "udpin:0.0.0.0:14550"


def capture(out_dir: Path, duration_s: float, conn_str: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    clean = out_dir / "clean"
    clean.mkdir(exist_ok=True)

    print(f"connecting: {conn_str}")
    mav = mavutil.mavlink_connection(conn_str)
    mav.wait_heartbeat(timeout=30)
    print(f"  heartbeat from sysid={mav.target_system} compid={mav.target_component}")

    imu_rows: list[dict] = []
    gps_rows: list[dict] = []

    t0_wall = time.time()
    t0_mono_ns = time.monotonic_ns()
    deadline = t0_wall + duration_s

    while time.time() < deadline:
        msg = mav.recv_match(
            type=["HIGHRES_IMU", "GPS_RAW_INT"],
            blocking=True,
            timeout=1.0,
        )
        if msg is None:
            continue
        # synthesize a host-monotonic timestamp_ns aligned to capture start
        ts_ns = time.monotonic_ns() - t0_mono_ns
        if msg.get_type() == "HIGHRES_IMU":
            imu_rows.append({
                "timestamp_ns": ts_ns,
                "ax_ms2":  msg.xacc,
                "ay_ms2":  msg.yacc,
                "az_ms2":  msg.zacc,
                "gx_rads": msg.xgyro,
                "gy_rads": msg.ygyro,
                "gz_rads": msg.zgyro,
                "temp_c":  msg.temperature,
            })
        elif msg.get_type() == "GPS_RAW_INT":
            gps_rows.append({
                "timestamp_ns": ts_ns,
                "time_usec":    msg.time_usec,
                "fix_type":     msg.fix_type,
                "lat_deg":      msg.lat / 1e7,
                "lon_deg":      msg.lon / 1e7,
                "alt_m":        msg.alt / 1000.0,
                "eph_m":        msg.eph / 100.0 if msg.eph != 65535 else float("nan"),
                "epv_m":        msg.epv / 100.0 if msg.epv != 65535 else float("nan"),
                "vel_ms":       msg.vel / 100.0 if msg.vel != 65535 else float("nan"),
                "cog_deg":      msg.cog / 100.0 if msg.cog != 65535 else float("nan"),
                "satellites_visible": msg.satellites_visible,
            })

    imu = pd.DataFrame(imu_rows).sort_values("timestamp_ns").reset_index(drop=True)
    gps = pd.DataFrame(gps_rows).sort_values("timestamp_ns").reset_index(drop=True)

    imu.to_csv(clean / "imu.csv", index=False)
    gps.to_csv(clean / "gps.csv", index=False)
    print(f"  imu: {len(imu):>6d} samples -> clean/imu.csv")
    print(f"  gps: {len(gps):>6d} fixes   -> clean/gps.csv")

    if not imu.empty and not gps.empty:
        unified = pd.merge_asof(imu, gps, on="timestamp_ns", direction="backward")
        unified.to_csv(clean / "unified.csv", index=False)
        print(f"  unified: {len(unified):>6d} rows -> clean/unified.csv")

    info = {
        "stack": "px4_sitl",
        "connection": conn_str,
        "wall_start": t0_wall,
        "duration_s": time.time() - t0_wall,
        "n_imu": len(imu),
        "n_gps": len(gps),
    }
    (out_dir / "info.json").write_text(json.dumps(info, indent=2))
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--out-dir", type=Path, required=True,
                   help="output flight directory")
    p.add_argument("-t", "--duration", type=float, default=60.0,
                   help="seconds to capture (default: 60)")
    p.add_argument("-c", "--connection", default=CONNECTION_DEFAULT,
                   help=f"pymavlink connection string (default: {CONNECTION_DEFAULT})")
    args = p.parse_args(argv)
    return capture(args.out_dir, args.duration, args.connection)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
