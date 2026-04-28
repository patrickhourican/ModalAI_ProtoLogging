"""Compare two SITL captures (e.g. PX4 vs ArduPilot of the same plan).

Prints summary stats and, with --plot, draws side-by-side trajectory
and IMU plots.

Usage:
  python sim/shared/compare.py <capture_a> <capture_b> [--plot]

Each capture directory is expected to have clean/imu.csv and
clean/gps.csv (the schema produced by sim/<stack>/capture.py or by
host/parse_logs.py on real flights).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _load(flight: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    info = {}
    info_path = flight / "info.json"
    if info_path.exists():
        info = json.loads(info_path.read_text())
    imu = pd.read_csv(flight / "clean" / "imu.csv") \
        if (flight / "clean" / "imu.csv").exists() else pd.DataFrame()
    gps = pd.read_csv(flight / "clean" / "gps.csv") \
        if (flight / "clean" / "gps.csv").exists() else pd.DataFrame()
    return imu, gps, info


def _summarize(label: str, imu: pd.DataFrame, gps: pd.DataFrame, info: dict) -> None:
    print(f"--- {label} ---")
    if info:
        print(f"  stack: {info.get('stack', '?')}  duration_s: {info.get('duration_s', '?')}")
    if imu.empty:
        print("  imu: (empty)")
    else:
        dur = (imu.timestamp_ns.iloc[-1] - imu.timestamp_ns.iloc[0]) / 1e9
        print(f"  imu: rows={len(imu)} dur={dur:.2f}s rate={len(imu)/dur:.1f}Hz "
              f"|az_mean|={imu.az_ms2.mean():+.3f}m/s2")
    if gps.empty:
        print("  gps: (empty)")
    else:
        fixed = gps[gps.fix_type >= 3]
        print(f"  gps: rows={len(gps)} fixed={len(fixed)} "
              f"sats_max={gps.satellites_visible.max()}")
        if not fixed.empty:
            d_lat = fixed.lat_deg.max() - fixed.lat_deg.min()
            d_lon = fixed.lon_deg.max() - fixed.lon_deg.min()
            d_alt = fixed.alt_m.max() - fixed.alt_m.min()
            print(f"       Δlat={d_lat:+.6f}°  Δlon={d_lon:+.6f}°  Δalt={d_alt:+.2f}m")


def _plot(flight_a, flight_b, imu_a, imu_b, gps_a, gps_b) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed — skip --plot or pip install matplotlib",
              file=sys.stderr)
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    for label, gps, ax in [(flight_a.name, gps_a, axes[0, 0]),
                            (flight_b.name, gps_b, axes[0, 1])]:
        if not gps.empty:
            fixed = gps[gps.fix_type >= 3]
            ax.plot(fixed.lon_deg, fixed.lat_deg, "o-", markersize=2)
        ax.set_title(f"{label}: GPS path")
        ax.set_xlabel("lon_deg"); ax.set_ylabel("lat_deg")
        ax.grid(True)

    for label, imu, ax in [(flight_a.name, imu_a, axes[1, 0]),
                            (flight_b.name, imu_b, axes[1, 1])]:
        if not imu.empty:
            t = (imu.timestamp_ns - imu.timestamp_ns.iloc[0]) / 1e9
            ax.plot(t, imu.ax_ms2, label="ax", linewidth=0.6)
            ax.plot(t, imu.ay_ms2, label="ay", linewidth=0.6)
            ax.plot(t, imu.az_ms2, label="az", linewidth=0.6)
            ax.legend(loc="upper right", fontsize=8)
        ax.set_title(f"{label}: accel")
        ax.set_xlabel("t (s)"); ax.set_ylabel("m/s²")
        ax.grid(True)

    fig.tight_layout()
    plt.show()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("flight_a", type=Path)
    p.add_argument("flight_b", type=Path)
    p.add_argument("--plot", action="store_true",
                   help="also show matplotlib comparison plots")
    args = p.parse_args(argv)

    imu_a, gps_a, info_a = _load(args.flight_a)
    imu_b, gps_b, info_b = _load(args.flight_b)

    _summarize(str(args.flight_a), imu_a, gps_a, info_a)
    _summarize(str(args.flight_b), imu_b, gps_b, info_b)

    if args.plot:
        _plot(args.flight_a, args.flight_b, imu_a, imu_b, gps_a, gps_b)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
