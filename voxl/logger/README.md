# voxl-clean-logger (B2)

Custom MPA subscriber that writes pre-decoded IMU + GPS CSVs directly on
the drone, bypassing voxl-logger's binary MAVLink output.

## Build

On the drone (or inside the `voxl-cross` docker image):

```bash
cd voxl/logger
make
```

Requires:
- `libmodal_pipe-dev`
- MAVLink C headers (`c_library_v2/common/mavlink.h`)
  These ship with the VOXL SDK; on a stock Starling 2 they're available
  by default. If not, add them via `voxl-vision-hub` or `voxl-mavlink-server`
  development packages.

## Run

```bash
./voxl-clean-logger                       # logs under /data/voxl-clean-logger/
./voxl-clean-logger -d /data/my_flights   # custom base dir
```

A new timestamped subfolder is created per run, e.g.
`/data/voxl-clean-logger/20260427_103015/` containing:

```
imu_apps/data.csv
imu_px4/data.csv
gps/data.csv
```

These files match the schemas expected by `host/parse_logs.py`, so you
can pull the folder and run the parser directly to get a `clean/`
directory with a unified CSV.

## Pipes consumed

| Channel | Pipe                  | Type                |
|---------|-----------------------|---------------------|
| 0       | imu_apps              | imu_data_t          |
| 1       | imu_px4               | imu_data_t          |
| 2       | mavlink_gps_raw_int   | mavlink_message_t (decodes GPS_RAW_INT) |

If your unit publishes GPS on a different pipe (e.g. `vvpx4_gps_raw_int`
on older SDKs), edit `PIPE_GPS` in `src/voxl_clean_logger.c`. List
available pipes with `voxl-list-pipes -t`.
