"""Capture a SITL flight from ArduPilot over MAVLink into our standard
CSV schema (host/parse_logs.py compatible).

The default endpoint is tcp://127.0.0.1:5760 (the autopilot's native
SERIAL0 when launched headless via sim/ardupilot/launch.sh). Override
with -c udpin:0.0.0.0:14550 if you've fanned out via mavproxy.py or
sim_vehicle.py.

ArduPilot does not generate HIGHRES_IMU; SCALED_IMU2 is the standard
high-rate IMU message. Default rates are too low, so we request
SCALED_IMU2 @ 200 Hz, GPS_RAW_INT @ 5 Hz, and ATTITUDE @ 50 Hz via
SET_MESSAGE_INTERVAL after the heartbeat. CAMERA_FEEDBACK is
event-driven (fires only on DO_DIGICAM_CONTROL / IMAGE_START_CAPTURE /
DO_SET_CAM_TRIGG_DIST, and only when CAM1_TYPE != 0; see
sim/ardupilot/camera_defaults.parm) and does not need a rate request.
Modern AP_Camera no longer emits the legacy CAMERA_TRIGGER (msg 112).

Outputs under <out_dir>/clean/:
  imu.csv       200 Hz SCALED_IMU2 in SI units
  gps.csv       5 Hz GPS_RAW_INT
  attitude.csv  50 Hz ATTITUDE (roll/pitch/yaw in deg, rates in rad/s)
  triggers.csv  CAMERA_FEEDBACK events (one row per shutter, geotagged)
  unified.csv   IMU rows + nearest-prior GPS fix

Usage:
  python sim/ardupilot/capture.py -o flights/sim_apm_<ts> -t 120
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

import pandas as pd
from pymavlink import mavutil

_STOP = False


def _request_stop(signum, frame):
    global _STOP
    _STOP = True

CONNECTION_DEFAULT = "tcp:127.0.0.1:5760"

# SCALED_IMU2 reports milli-units. Conversion factors to SI:
MG_TO_MS2 = 9.80665e-3      # mg -> m/s^2
MRAD_TO_RADS = 1e-3          # mrad/s -> rad/s
CDEG_TO_C = 1e-2             # centi-degrees C -> C
RAD_TO_DEG = 57.2957795130823

# ArduPilot's default stream rates (SR1_RAW_SENS, SR1_POSITION) are too low
# for our purposes. Request the messages we want explicitly via
# SET_MESSAGE_INTERVAL. ArduPilot does not generate HIGHRES_IMU; SCALED_IMU2
# is the standard high-rate IMU for GCSes. CAMERA_TRIGGER is event-driven
# and does not need a rate request.
STREAM_REQUESTS = [
    (mavutil.mavlink.MAVLINK_MSG_ID_SCALED_IMU2,  5_000),    # 200 Hz
    (mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,  200_000),  # 5 Hz
    (mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE,     20_000),   # 50 Hz
]

IMU_COLUMNS = ["timestamp_ns", "ax_ms2", "ay_ms2", "az_ms2",
               "gx_rads", "gy_rads", "gz_rads", "temp_c"]
GPS_COLUMNS = ["timestamp_ns", "time_usec", "fix_type",
               "lat_deg", "lon_deg", "alt_m",
               "eph_m", "epv_m", "vel_ms", "cog_deg",
               "satellites_visible"]
ATT_COLUMNS = ["timestamp_ns", "time_boot_ms",
               "roll_deg", "pitch_deg", "yaw_deg",
               "rollspeed_rads", "pitchspeed_rads", "yawspeed_rads"]
TRIG_COLUMNS = ["timestamp_ns", "time_usec", "img_idx", "cam_idx",
                "lat_deg", "lon_deg", "alt_msl_m", "alt_rel_m",
                "roll_deg", "pitch_deg", "yaw_deg",
                "foc_len_mm", "flags", "completed_captures"]


def request_streams(mav) -> None:
    for msg_id, interval_us in STREAM_REQUESTS:
        mav.mav.command_long_send(
            mav.target_system, mav.target_component,
            mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
            0,
            msg_id, interval_us,
            0, 0, 0, 0, 0,
        )


def _imu_from_highres(msg) -> dict:
    return {
        "ax_ms2":  msg.xacc,  "ay_ms2": msg.yacc,  "az_ms2": msg.zacc,
        "gx_rads": msg.xgyro, "gy_rads": msg.ygyro, "gz_rads": msg.zgyro,
        "temp_c":  msg.temperature,
    }


def _imu_from_scaled(msg) -> dict:
    return {
        "ax_ms2":  msg.xacc * MG_TO_MS2,
        "ay_ms2":  msg.yacc * MG_TO_MS2,
        "az_ms2":  msg.zacc * MG_TO_MS2,
        "gx_rads": msg.xgyro * MRAD_TO_RADS,
        "gy_rads": msg.ygyro * MRAD_TO_RADS,
        "gz_rads": msg.zgyro * MRAD_TO_RADS,
        "temp_c":  getattr(msg, "temperature", 0) * CDEG_TO_C,
    }


def capture(out_dir: Path, duration_s: float, conn_str: str) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    clean = out_dir / "clean"
    clean.mkdir(exist_ok=True)

    print(f"connecting: {conn_str}")
    mav = mavutil.mavlink_connection(conn_str)
    mav.wait_heartbeat(timeout=30)
    print(f"  heartbeat from sysid={mav.target_system} compid={mav.target_component}")

    request_streams(mav)
    print(f"  requested SCALED_IMU2 @ 200 Hz, GPS_RAW_INT @ 5 Hz, ATTITUDE @ 50 Hz")

    imu_rows: list[dict] = []
    gps_rows: list[dict] = []
    att_rows: list[dict] = []
    trig_rows: list[dict] = []

    t0_wall = time.time()
    t0_mono_ns = time.monotonic_ns()
    deadline = t0_wall + duration_s
    msg_types = ["HIGHRES_IMU", "SCALED_IMU2", "GPS_RAW_INT",
                 "ATTITUDE", "CAMERA_FEEDBACK"]

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    while time.time() < deadline and not _STOP:
        msg = mav.recv_match(type=msg_types, blocking=True, timeout=1.0)
        if msg is None:
            continue
        ts_ns = time.monotonic_ns() - t0_mono_ns
        mtype = msg.get_type()
        if mtype == "HIGHRES_IMU":
            imu_rows.append({"timestamp_ns": ts_ns, **_imu_from_highres(msg)})
        elif mtype == "SCALED_IMU2":
            imu_rows.append({"timestamp_ns": ts_ns, **_imu_from_scaled(msg)})
        elif mtype == "GPS_RAW_INT":
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
        elif mtype == "ATTITUDE":
            att_rows.append({
                "timestamp_ns":    ts_ns,
                "time_boot_ms":    msg.time_boot_ms,
                "roll_deg":        msg.roll * RAD_TO_DEG,
                "pitch_deg":       msg.pitch * RAD_TO_DEG,
                "yaw_deg":         msg.yaw * RAD_TO_DEG,
                "rollspeed_rads":  msg.rollspeed,
                "pitchspeed_rads": msg.pitchspeed,
                "yawspeed_rads":   msg.yawspeed,
            })
        elif mtype == "CAMERA_FEEDBACK":
            trig_rows.append({
                "timestamp_ns":        ts_ns,
                "time_usec":           msg.time_usec,
                "img_idx":             msg.img_idx,
                "cam_idx":             msg.cam_idx,
                "lat_deg":             msg.lat / 1e7,
                "lon_deg":             msg.lng / 1e7,
                "alt_msl_m":           msg.alt_msl,
                "alt_rel_m":           msg.alt_rel,
                "roll_deg":            msg.roll,
                "pitch_deg":           msg.pitch,
                "yaw_deg":             msg.yaw,
                "foc_len_mm":          msg.foc_len,
                "flags":               msg.flags,
                "completed_captures":  msg.completed_captures,
            })

    imu = pd.DataFrame(imu_rows, columns=IMU_COLUMNS)
    gps = pd.DataFrame(gps_rows, columns=GPS_COLUMNS)
    att = pd.DataFrame(att_rows, columns=ATT_COLUMNS)
    trig = pd.DataFrame(trig_rows, columns=TRIG_COLUMNS)
    for df in (imu, gps, att, trig):
        if not df.empty:
            df.sort_values("timestamp_ns", inplace=True, ignore_index=True)

    imu.to_csv(clean / "imu.csv", index=False)
    gps.to_csv(clean / "gps.csv", index=False)
    att.to_csv(clean / "attitude.csv", index=False)
    trig.to_csv(clean / "triggers.csv", index=False)
    print(f"  imu:      {len(imu):>6d} samples -> clean/imu.csv")
    print(f"  gps:      {len(gps):>6d} fixes   -> clean/gps.csv")
    print(f"  attitude: {len(att):>6d} samples -> clean/attitude.csv")
    print(f"  triggers: {len(trig):>6d} events  -> clean/triggers.csv")

    if not imu.empty and not gps.empty:
        unified = pd.merge_asof(imu, gps, on="timestamp_ns", direction="backward")
        unified.to_csv(clean / "unified.csv", index=False)
        print(f"  unified:  {len(unified):>6d} rows    -> clean/unified.csv")
    else:
        print("  unified:  skipped (empty imu or gps)")

    info = {
        "stack": "ardupilot_sitl",
        "connection": conn_str,
        "wall_start": t0_wall,
        "duration_s": time.time() - t0_wall,
        "n_imu":      len(imu),
        "n_gps":      len(gps),
        "n_attitude": len(att),
        "n_triggers": len(trig),
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
