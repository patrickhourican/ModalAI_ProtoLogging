# ModalAI Starling 2 / VOXL 2 Prototyping

Tools for capturing and post-processing IMU + GPS logs from a ModalAI
Starling 2 (VOXL 2 compute), with both an on-drone capture path and a
host-side parser that produces clean CSVs suitable for analysis.

The video-to-QGC path is intentionally not part of this repo: the stock
VOXL SDK already serves an RTSP stream via `voxl-streamer` and advertises
it to QGroundControl through `voxl-mavcam-manager`. See
[ModalAI's docs](https://docs.modalai.com/voxl-streamer) for setup.

## Layout

```
voxl/                 # runs on the drone (VOXL 2)
  scripts/            # B1: bash wrapper around voxl-logger
  logger/             # B2: custom MPA -> CSV subscriber (C)
host/                 # runs on your PC
  pull_logs.sh        # rsync logs off the drone
  parse_logs.py       # parse a flight folder into clean CSVs
  requirements.txt
mock/                 # offline-testing data generator (no drone needed)
flights/              # captured / pulled flights (gitignored)
docs/                 # architecture notes
```

## Two capture paths

### B1 — `voxl-logger` wrapper (works today, IMU only is clean)
Runs `voxl-logger` on the drone with sensible defaults for IMU + GPS pipes.
The IMU output lands as a tidy CSV; the GPS pipe is captured as raw
MAVLink and is best decoded by B2.

### B2 — Custom MPA subscriber (clean IMU + GPS in one program)
Small C program built against `libmodal_pipe` that subscribes to
`imu_apps`, `imu_px4`, and `mavlink_gps_raw_int`, decodes the GPS
MAVLink inline, and writes one clean CSV per stream with controlled
schema.

## Quick start

### On the drone
```bash
# B1 — bash wrapper around voxl-logger
voxl/scripts/start_logging.sh -t 60 -n bench_test
# logs land in /data/voxl-logger/logNNNN/
```

### On your PC
```bash
# pull a flight
host/pull_logs.sh <drone-ip>

# parse the most recent pulled flight to clean CSVs
python -m pip install -r host/requirements.txt
python host/parse_logs.py flights/log0001
# -> flights/log0001/clean/imu_apps.csv, imu_px4.csv, unified.csv
```

### Without a drone (mock data)
```bash
python mock/generate_mock_flight.py flights/mock_log
python host/parse_logs.py flights/mock_log
```

## Output schema

`clean/imu_apps.csv`, `clean/imu_px4.csv`:
```
timestamp_ns, ax_ms2, ay_ms2, az_ms2, gx_rads, gy_rads, gz_rads, temp_c
```

`clean/gps.csv` (B2 only, or mock):
```
timestamp_ns, time_usec, fix_type, lat_deg, lon_deg, alt_m, eph_m, epv_m,
vel_ms, cog_deg, satellites_visible
```

`clean/unified.csv` — IMU samples with the latest GPS fix joined per row.

## Status

| Component | Status |
|---|---|
| B1 wrapper script | ready |
| B1 host puller | ready |
| B1 Python parser (IMU + unified) | ready |
| Mock data generator | ready |
| B2 custom C subscriber | ready (needs to be built on the drone) |
