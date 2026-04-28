# SITL environments — PX4 and ArduPilot

Run the same mission on two autopilot stacks, capture each via MAVLink,
and feed the captures back through the existing `host/parse_logs.py`
pipeline. Lets you exercise B1/B2 logger code end-to-end without a
drone, and lets you compare PX4 vs ArduPilot behaviour on identical
flight plans.

```
sim/
├── px4/
│   ├── launch.sh           boots PX4 SITL + Gazebo, opens QGC
│   ├── capture.py          pymavlink → CSV in our schema
│   └── missions/           QGC .plan files (created in QGC, saved here)
├── ardupilot/
│   ├── launch.sh           boots ArduPilot SITL + Gazebo
│   ├── capture.py          same CSV schema, different MAVLink endpoint
│   └── missions/
└── shared/
    └── compare.py          load both captures, diff trajectories / IMU
```

Toolchains (`PX4-Autopilot/`, `ardupilot/`) are NOT in this repo —
they're 5+ GB each. Clone them into a sibling directory and point
`launch.sh` at them via env vars.

## One-time setup

### Common prerequisites
```bash
.venv/bin/pip install -r sim/requirements.txt        # pymavlink, matplotlib
# QGroundControl: download AppImage from
#   https://qgroundcontrol.com/downloads/  -> chmod +x QGroundControl.AppImage
```

### PX4 SITL (Docker / podman)
PX4 SITL on Rocky 9 is run inside the official PX4 simulation
container. This avoids the apt-only `Tools/setup/ubuntu.sh` install
path and ships Gazebo Harmonic preinstalled. The host only needs
`podman` (or `docker`) and a clone of PX4 source for missions / edits.

```bash
# 1. host source (used as a bind-mount into the container)
mkdir -p ~/sim_tools && cd ~/sim_tools
git clone --recursive https://github.com/PX4/PX4-Autopilot.git
export PX4_AUTOPILOT_DIR="$HOME/sim_tools/PX4-Autopilot"   # add to ~/.bashrc

# 2. pull the PX4 simulation image (~3 GB, one time)
podman pull docker.io/px4io/px4-dev-simulation-jammy:latest

# 3. allow the container to talk to the X server (one time per login)
xhost +SI:localuser:$(id -un)
```
First build inside the container is ~20 min; the build is cached
under `$PX4_AUTOPILOT_DIR/build/` on the host so subsequent
`launch.sh` calls boot in seconds.

Headless variant (no Gazebo window, useful over SSH or in CI):
```bash
HEADLESS=1 sim/px4/launch.sh
```

### ArduPilot SITL
```bash
cd ~/sim_tools
git clone https://github.com/ArduPilot/ardupilot.git --recursive
cd ardupilot
Tools/environment_install/install-prereqs-ubuntu.sh -y
. ~/.profile
./waf configure --board sitl
./waf copter
```
Set:
```bash
export ARDUPILOT_DIR="$HOME/sim_tools/ardupilot"
```

## Running a sim

### PX4
Terminal 1:
```bash
sim/px4/launch.sh
```
Terminal 2 (capture telemetry):
```bash
.venv/bin/python sim/px4/capture.py -o flights/sim_px4_$(date +%Y%m%d_%H%M%S) -t 120
```
Terminal 3 (or just open it from your app menu): launch QGC, it
auto-connects on UDP `14550`.

### ArduPilot
Terminal 1:
```bash
sim/ardupilot/launch.sh
```
Terminal 2:
```bash
.venv/bin/python sim/ardupilot/capture.py -o flights/sim_apm_$(date +%Y%m%d_%H%M%S) -t 120
```
ArduPilot SITL exposes MAVLink on UDP `14550` by default too — so QGC
auto-connects the same way.

## Mission workflow

1. In QGC: **Plan** view → drop waypoints → **Upload** → switch to
   **Fly** view → arm → **Start Mission**.
2. Save the plan: Plan view → **Sync → Save to file** →
   `sim/<stack>/missions/<name>.plan`. Commit it.
3. To replay later, **Open** the saved plan in QGC and Upload.

Both stacks load the same `.plan` JSON format, but waypoint behaviour
may differ slightly between PX4 and ArduPilot (e.g., loiter vs hold
semantics). For best comparability, keep missions simple: takeoff,
waypoint square, land.

## Capture schema

`capture.py` writes the same CSV schema `host/parse_logs.py` produces,
so simulated captures slot into the same downstream tooling:

```
flights/sim_px4_<ts>/clean/
├── imu.csv         (timestamp_ns, ax_ms2, ..., temp_c)
├── gps.csv         (timestamp_ns, time_usec, fix_type, lat_deg, ...)
└── unified.csv     (IMU rows + nearest-prior GPS fix)
```

This means PlotJuggler, your parsing tests, and `shared/compare.py` all
work the same on real and simulated flights.

## Comparing two stacks

After capturing the same mission on both:
```bash
.venv/bin/python sim/shared/compare.py \
    flights/sim_px4_20260427_153012 \
    flights/sim_apm_20260427_154500
```
Prints summary stats and (with `--plot`) shows side-by-side trajectory
and IMU plots.

## Notes & caveats

- PX4 SITL and ArduPilot SITL both bind UDP 14550 for QGC. Run only
  one at a time, or remap with `--instance N` on the second.
- Vanilla SITL has no `/run/mpa/` pipes — that's a VOXL-specific layer.
  For pipe-level testing, use ModalAI's `voxl-px4-sitl` Docker image
  instead.
- PX4 `.ulg` ground-truth logs land under
  `$PX4_AUTOPILOT_DIR/build/px4_sitl_default/rootfs/log/`.
- ArduPilot `.bin` logs land under `$ARDUPILOT_DIR/logs/`.
