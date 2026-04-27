"""Parse a voxl-logger flight folder into clean CSVs.

Reads (voxl-logger nests pipe captures under run/mpa/; fallback to flat
layout for mock data):
  <flight>/info.json
  <flight>/run/mpa/imu_apps/data.csv         (or <flight>/imu_apps/data.csv)
  <flight>/run/mpa/imu_mavlink/data.csv      (or imu_px4 on older SDKs)
  <flight>/gps/data.csv                      (B2 voxl-clean-logger output, optional)

Writes:
  <flight>/clean/imu_apps.csv
  <flight>/clean/imu_mavlink.csv     (or imu_px4.csv, mirroring source name)
  <flight>/clean/gps.csv             (if gps source present)
  <flight>/clean/unified.csv         (IMU rows + nearest-prior GPS fix)

GPS captured by raw voxl-logger (mavlink_message_t binary in data.raw)
is not decoded here; use the B2 voxl-clean-logger to get a clean gps CSV.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

IMU_RAW_COLS = [
    "i", "timestamp(ns)", "batch_id",
    "AX(m/s2)", "AY(m/s2)", "AZ(m/s2)",
    "GX(rad/s)", "GY(rad/s)", "GZ(rad/s)",
    "T(C)",
]
IMU_CLEAN_COLS = [
    "timestamp_ns", "ax_ms2", "ay_ms2", "az_ms2",
    "gx_rads", "gy_rads", "gz_rads", "temp_c",
]
GPS_CLEAN_COLS = [
    "timestamp_ns", "time_usec", "fix_type",
    "lat_deg", "lon_deg", "alt_m",
    "eph_m", "epv_m", "vel_ms", "cog_deg", "satellites_visible",
]


def _read_imu(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in IMU_RAW_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing expected IMU columns {missing}")
    out = pd.DataFrame({
        "timestamp_ns": df["timestamp(ns)"].astype("int64"),
        "ax_ms2":  df["AX(m/s2)"].astype(float),
        "ay_ms2":  df["AY(m/s2)"].astype(float),
        "az_ms2":  df["AZ(m/s2)"].astype(float),
        "gx_rads": df["GX(rad/s)"].astype(float),
        "gy_rads": df["GY(rad/s)"].astype(float),
        "gz_rads": df["GZ(rad/s)"].astype(float),
        "temp_c":  df["T(C)"].astype(float),
    })
    return out.sort_values("timestamp_ns").reset_index(drop=True)


def _read_gps(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = [c for c in GPS_CLEAN_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: missing expected GPS columns {missing}")
    return df[GPS_CLEAN_COLS].sort_values("timestamp_ns").reset_index(drop=True)


def _unify(imu: pd.DataFrame, gps: pd.DataFrame | None) -> pd.DataFrame:
    if gps is None or gps.empty:
        return imu.copy()
    return pd.merge_asof(
        imu, gps,
        on="timestamp_ns",
        direction="backward",
        suffixes=("", "_gps"),
    )


def parse_flight(flight_dir: Path) -> int:
    if not flight_dir.is_dir():
        print(f"ERROR: not a directory: {flight_dir}", file=sys.stderr)
        return 1

    out_dir = flight_dir / "clean"
    out_dir.mkdir(exist_ok=True)

    info_path = flight_dir / "info.json"
    if info_path.exists():
        info = json.loads(info_path.read_text())
        print(f"flight note: {info.get('note', 'n/a')}, "
              f"channels: {info.get('n_channels', '?')}, "
              f"duration_s: {info.get('duration_s', '?')}")

    def _pipe_dir(name: str) -> Path:
        nested = flight_dir / "run" / "mpa" / name
        return nested if nested.is_dir() else flight_dir / name

    imu_frames: dict[str, pd.DataFrame] = {}
    for name in ("imu_apps", "imu_mavlink", "imu_px4"):
        csv = _pipe_dir(name) / "data.csv"
        if csv.exists():
            df = _read_imu(csv)
            imu_frames[name] = df
            df.to_csv(out_dir / f"{name}.csv", index=False)
            print(f"  {name}: {len(df):>7d} samples -> clean/{name}.csv")

    gps = None
    gps_csv = _pipe_dir("gps") / "data.csv"
    if gps_csv.exists():
        gps = _read_gps(gps_csv)
        gps.to_csv(out_dir / "gps.csv", index=False)
        print(f"  gps:      {len(gps):>7d} fixes   -> clean/gps.csv")
    else:
        # voxl-logger MAVLink-only flights have data.raw but no decoded csv
        for raw_name in ("mavlink_gps_raw_int", "vvpx4_vehicle_gps"):
            if _pipe_dir(raw_name).is_dir():
                print(f"  note: {raw_name}/ present but not decoded; "
                      f"use voxl-clean-logger (B2) for clean GPS CSV")
                break

    if imu_frames:
        primary = imu_frames["imu_apps"] if "imu_apps" in imu_frames \
            else next(iter(imu_frames.values()))
        unified = _unify(primary, gps)
        unified.to_csv(out_dir / "unified.csv", index=False)
        print(f"  unified:  {len(unified):>7d} rows    -> clean/unified.csv")

    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("flight_dir", type=Path,
                   help="path to a voxl-logger flight folder, e.g. flights/log0001")
    args = p.parse_args(argv)
    return parse_flight(args.flight_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
