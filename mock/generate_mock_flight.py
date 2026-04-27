"""Synthesize a fake voxl-logger flight folder for offline parser testing.

Produces, under <out_dir>:
  info.json
  imu_apps/data.csv          (voxl-logger IMU schema)
  imu_px4/data.csv           (voxl-logger IMU schema)
  gps/data.csv               (B2 voxl-clean-logger schema, decoded GPS)

The IMU stream is a slow sinusoid + noise; the GPS stream walks a small
circle around a configurable origin at 5 Hz.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

IMU_HEADER = (
    "i,timestamp(ns),batch_id,AX(m/s2),AY(m/s2),AZ(m/s2),"
    "GX(rad/s),GY(rad/s),GZ(rad/s),T(C)\n"
)
GPS_HEADER = (
    "timestamp_ns,time_usec,fix_type,lat_deg,lon_deg,alt_m,"
    "eph_m,epv_m,vel_ms,cog_deg,satellites_visible\n"
)


def _write_imu(path: Path, duration_s: float, hz: float, seed: int) -> int:
    rng = random.Random(seed)
    n = int(duration_s * hz)
    dt_ns = int(1e9 / hz)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(IMU_HEADER)
        for i in range(n):
            t_ns = i * dt_ns
            t_s = i / hz
            ax = 0.05 * math.sin(2 * math.pi * 0.5 * t_s) + rng.gauss(0, 0.02)
            ay = 0.05 * math.cos(2 * math.pi * 0.5 * t_s) + rng.gauss(0, 0.02)
            az = 9.81 + rng.gauss(0, 0.05)
            gx = 0.01 * math.sin(2 * math.pi * 0.2 * t_s) + rng.gauss(0, 0.001)
            gy = 0.01 * math.cos(2 * math.pi * 0.2 * t_s) + rng.gauss(0, 0.001)
            gz = rng.gauss(0, 0.001)
            temp = 35.0 + 0.5 * math.sin(2 * math.pi * 0.05 * t_s)
            f.write(
                f"{i},{t_ns},0,"
                f"{ax:.6f},{ay:.6f},{az:.6f},"
                f"{gx:.6f},{gy:.6f},{gz:.6f},"
                f"{temp:.3f}\n"
            )
    return n


def _write_gps(path: Path, duration_s: float, hz: float,
               lat0: float, lon0: float, alt0: float) -> int:
    n = int(duration_s * hz)
    dt_ns = int(1e9 / hz)
    radius_m = 5.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        f.write(GPS_HEADER)
        for i in range(n):
            t_ns = i * dt_ns
            t_s = i / hz
            theta = 2 * math.pi * (t_s / 30.0)
            dlat = (radius_m * math.sin(theta)) / m_per_deg_lat
            dlon = (radius_m * math.cos(theta)) / m_per_deg_lon
            lat = lat0 + dlat
            lon = lon0 + dlon
            alt = alt0 + 0.5 * math.sin(2 * math.pi * 0.1 * t_s)
            vel = 2 * math.pi * radius_m / 30.0
            cog = (math.degrees(theta) + 90.0) % 360.0
            f.write(
                f"{t_ns},{t_ns // 1000},3,"
                f"{lat:.7f},{lon:.7f},{alt:.3f},"
                f"1.200,1.500,{vel:.3f},{cog:.2f},14\n"
            )
    return n


def _write_info(out_dir: Path, channels: list[dict], duration_s: float) -> None:
    info = {
        "log_format_version": 1,
        "note": "mock_flight",
        "n_channels": len(channels),
        "start_time_monotonic_ns": 0,
        "start_time_date": "1970-01-01 00:00:00",
        "duration_s": duration_s,
        "channels": channels,
    }
    (out_dir / "info.json").write_text(json.dumps(info, indent=2))


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("out_dir", type=Path, help="where to create the mock flight")
    p.add_argument("--duration", type=float, default=10.0, help="seconds (default 10)")
    p.add_argument("--imu-hz", type=float, default=1000.0)
    p.add_argument("--gps-hz", type=float, default=5.0)
    p.add_argument("--lat", type=float, default=37.7749)
    p.add_argument("--lon", type=float, default=-122.4194)
    p.add_argument("--alt", type=float, default=30.0)
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)

    n_apps = _write_imu(args.out_dir / "imu_apps" / "data.csv",
                        args.duration, args.imu_hz, args.seed)
    n_px4 = _write_imu(args.out_dir / "imu_px4" / "data.csv",
                       args.duration, args.imu_hz, args.seed + 1)
    n_gps = _write_gps(args.out_dir / "gps" / "data.csv",
                       args.duration, args.gps_hz,
                       args.lat, args.lon, args.alt)

    _write_info(args.out_dir, [
        {"channel": 0, "type_string": "imu", "pipe_path": "/run/mpa/imu_apps/", "n_samples": n_apps},
        {"channel": 1, "type_string": "imu", "pipe_path": "/run/mpa/imu_px4/",  "n_samples": n_px4},
        {"channel": 2, "type_string": "gps", "pipe_path": "/run/mpa/mavlink_gps_raw_int/", "n_samples": n_gps},
    ], args.duration)

    print(f"wrote mock flight to {args.out_dir}")
    print(f"  imu_apps: {n_apps} samples")
    print(f"  imu_px4:  {n_px4} samples")
    print(f"  gps:      {n_gps} fixes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
