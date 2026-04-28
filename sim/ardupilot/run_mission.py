"""Headless mission replay for ArduCopter SITL.

Loads a QGroundControl .plan file, uploads its mission items to the
autopilot via the standard MAVLink mission protocol (MISSION_COUNT ->
MISSION_REQUEST_INT -> MISSION_ITEM_INT -> MISSION_ACK), and
optionally arms, takes off, and switches to AUTO to start the mission.

Designed to run alongside QGC + capture.py via mavproxy's UDP fan-out:
  mavproxy.py --master tcp:127.0.0.1:5760 \
              --out udp:127.0.0.1:14550   (QGC observer)
              --out udp:127.0.0.1:14551   (capture.py)
              --out udp:127.0.0.1:14552   (this script)

Usage:
  python sim/ardupilot/run_mission.py sim/ardupilot/missions/square_50m.plan \
      --auto-start --tail
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from pymavlink import mavutil

CONNECTION_DEFAULT = "udp:127.0.0.1:14552"


def _nz(v):
    return 0.0 if v is None else float(v)


def _home_item(home: list[float]) -> dict:
    # ArduPilot reserves seq 0 for HOME and silently overwrites whatever
    # is uploaded there. QGC prepends an explicit HOME item; do the same
    # so the user's seq 0 (typically TAKEOFF) survives at seq 1.
    return {
        "seq": 0, "frame": mavutil.mavlink.MAV_FRAME_GLOBAL,
        "command": mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
        "current": 0, "autocontinue": 1,
        "param1": 0.0, "param2": 0.0, "param3": 0.0, "param4": 0.0,
        "x": int(home[0] * 1e7), "y": int(home[1] * 1e7), "z": float(home[2]),
    }


def _flatten_simple_items(raw_items: list[dict]) -> list[dict]:
    # QGC stores patterns (Survey, CorridorScan, StructureScan, ...) as a
    # ComplexItem wrapping a list of SimpleItems. The nested list lives at
    # TransectStyleComplexItem.Items for transect-based patterns and at
    # Items for StructureScan. Walk both, recursively, and yield only the
    # leaf SimpleItems so the upload path stays MAVLink-compliant.
    out: list[dict] = []
    for raw_idx, item in enumerate(raw_items):
        kind = item.get("type")
        if kind == "SimpleItem":
            out.append(item)
        elif kind == "ComplexItem":
            nested = (item.get("TransectStyleComplexItem", {}).get("Items")
                      or item.get("Items"))
            if not nested:
                ctype = item.get("complexItemType", "?")
                raise ValueError(
                    f"item {raw_idx}: ComplexItem ({ctype}) has no expandable Items[]"
                )
            out.extend(_flatten_simple_items(nested))
        else:
            raise ValueError(f"item {raw_idx}: unsupported type {kind}")
    return out


def load_plan(path: Path) -> tuple[list[dict], list[float]]:
    data = json.loads(path.read_text())
    if data.get("fileType") != "Plan":
        raise ValueError(f"{path}: not a QGC .plan file")
    home = data["mission"]["plannedHomePosition"]
    items: list[dict] = [_home_item(home)]
    for item in _flatten_simple_items(data["mission"]["items"]):
        p = item["params"]
        items.append({
            "seq":           len(items),
            "frame":         item["frame"],
            "command":       item["command"],
            "current":       0,
            "autocontinue":  int(item.get("autoContinue", True)),
            "param1": _nz(p[0]), "param2": _nz(p[1]),
            "param3": _nz(p[2]), "param4": _nz(p[3]),
            "x":             int(_nz(p[4]) * 1e7),
            "y":             int(_nz(p[5]) * 1e7),
            "z":             _nz(p[6]),
        })
    return items, home


def upload_mission(mav, items: list[dict]) -> None:
    mav.mav.mission_clear_all_send(mav.target_system, mav.target_component)
    time.sleep(0.3)
    mav.mav.mission_count_send(mav.target_system, mav.target_component,
                               len(items), 0)
    for _ in range(len(items)):
        req = mav.recv_match(type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
                             blocking=True, timeout=5)
        if req is None:
            raise TimeoutError("autopilot did not request a mission item")
        it = items[req.seq]
        mav.mav.mission_item_int_send(
            mav.target_system, mav.target_component,
            it["seq"], it["frame"], it["command"],
            it["current"], it["autocontinue"],
            it["param1"], it["param2"], it["param3"], it["param4"],
            it["x"], it["y"], it["z"], 0,
        )
    ack = mav.recv_match(type="MISSION_ACK", blocking=True, timeout=5)
    if ack is None or ack.type != mavutil.mavlink.MAV_MISSION_ACCEPTED:
        raise RuntimeError(f"mission upload not ACKed cleanly: {ack}")


def _set_mode(mav, mode_name: str) -> None:
    mode_id = mav.mode_mapping()[mode_name]
    mav.mav.set_mode_send(mav.target_system,
                          mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                          mode_id)


def _wait_gps_fix(mav, min_fix: int = 3, timeout: float = 60) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = mav.recv_match(type="GPS_RAW_INT", blocking=True, timeout=1)
        if msg and msg.fix_type >= min_fix:
            return True
    return False


def _wait_armed(mav, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        hb = mav.recv_match(type="HEARTBEAT", blocking=True, timeout=1)
        if hb and hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
            return True
    return False


def arm_and_start(mav, takeoff_alt: float) -> None:
    print("waiting for GPS 3D fix...")
    if not _wait_gps_fix(mav):
        raise TimeoutError("no GPS 3D fix within 60 s")
    print("setting mode GUIDED")
    _set_mode(mav, "GUIDED")
    time.sleep(1)
    print("arming")
    mav.arducopter_arm()
    if not _wait_armed(mav):
        raise TimeoutError("arming timeout (PreArm check failed?)")
    print(f"takeoff to {takeoff_alt:.0f} m")
    mav.mav.command_long_send(mav.target_system, mav.target_component,
                              mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0,
                              0, 0, 0, 0, 0, 0, takeoff_alt)
    time.sleep(2)
    print("setting mode AUTO (mission start)")
    _set_mode(mav, "AUTO")


def tail_progress(mav, n_items: int, timeout: float = 600) -> bool:
    deadline = time.time() + timeout
    last_seq = -1
    while time.time() < deadline:
        msg = mav.recv_match(
            type=["MISSION_CURRENT", "MISSION_ITEM_REACHED", "STATUSTEXT"],
            blocking=True, timeout=1)
        if msg is None:
            continue
        mtype = msg.get_type()
        if mtype == "MISSION_ITEM_REACHED":
            print(f"  reached waypoint {msg.seq}")
        elif mtype == "MISSION_CURRENT" and msg.seq != last_seq:
            print(f"  current waypoint -> {msg.seq}")
            last_seq = msg.seq
            if msg.seq >= n_items - 1:
                return True
        elif mtype == "STATUSTEXT":
            print(f"  STATUSTEXT[{msg.severity}]: {msg.text}")
    return False


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("plan", type=Path, help="QGC .plan JSON file")
    p.add_argument("-c", "--connection", default=CONNECTION_DEFAULT)
    p.add_argument("--auto-start", action="store_true",
                   help="arm, takeoff, then switch to AUTO after upload")
    p.add_argument("--tail", action="store_true",
                   help="follow MISSION_CURRENT until last waypoint")
    p.add_argument("--takeoff-alt", type=float, default=30.0)
    args = p.parse_args(argv)

    items, home = load_plan(args.plan)
    print(f"loaded {len(items)} items from {args.plan}")
    print(f"  home: {home[0]:.6f}, {home[1]:.6f}, {home[2]} m AMSL")

    print(f"connecting: {args.connection}")
    mav = mavutil.mavlink_connection(args.connection)
    mav.wait_heartbeat(timeout=30)
    print(f"  heartbeat from sysid={mav.target_system} compid={mav.target_component}")

    upload_mission(mav, items)
    print(f"uploaded {len(items)} mission items")

    if args.auto_start:
        arm_and_start(mav, args.takeoff_alt)
    if args.tail:
        ok = tail_progress(mav, len(items))
        print("mission complete" if ok else "tail timeout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
