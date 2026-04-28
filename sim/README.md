# SITL environments — PX4 and ArduPilot

Run the same mission on two autopilot stacks, capture each via MAVLink,
and feed the captures back through the existing `host/parse_logs.py`
pipeline. Lets you exercise B1/B2 logger code end-to-end without a
drone, and lets you compare PX4 vs ArduPilot behaviour on identical
flight plans.

```
sim/
├── px4/
│   ├── launch.sh             boots PX4 SITL + Gazebo, opens QGC
│   ├── capture.py            pymavlink → CSV in our schema
│   └── missions/             QGC .plan files (created in QGC, saved here)
├── ardupilot/
│   ├── launch.sh             boots ArduCopter SITL headless (TCP 5760)
│   ├── capture.py            MAVLink → CSV: IMU + GPS + ATTITUDE + CAMERA_FEEDBACK
│   ├── camera_defaults.parm  SITL boot params: enable CAM1 + servo trigger
│   ├── run_mission.py        headless QGC .plan replay (arm/takeoff/AUTO/tail)
│   └── missions/
├── cameras/
│   └── starling2_hires.json  Starling 2 hi-res camera model (intrinsics + mount)
├── shared/
│   └── compare.py            load both captures, diff trajectories / IMU
└── qgc.sh                    QGroundControl launcher wrapper
```

Toolchains (`PX4-Autopilot/`, `ardupilot/`) are NOT in this repo —
they're 5+ GB each. Clone them into a sibling directory and point
`launch.sh` at them via env vars.

## One-time setup

### Common prerequisites
```bash
.venv/bin/pip install -r sim/requirements.txt        # pymavlink, matplotlib
```

### QGroundControl (Rocky 9 / RHEL family)

Tested with QGC v5.0.8 on Rocky 9.x (glibc 2.34), GNOME/X11 session.

```bash
# 1. download + extract (no fuse2 on stock Rocky 9, so don't try to mount)
mkdir -p ~/sim_tools && cd ~/sim_tools
curl -L -o QGroundControl.AppImage \
  https://github.com/mavlink/qgroundcontrol/releases/download/v5.0.8/QGroundControl-x86_64.AppImage
chmod +x QGroundControl.AppImage
./QGroundControl.AppImage --appimage-extract            # produces ./squashfs-root/

# 2. one-time host fixes
sudo setsebool -P selinuxuser_execmod 1                 # SELinux: QtQml JIT
sudo usermod -aG dialout $USER                          # QGC startup pre-flight
sudo systemctl disable --now ModemManager               # QGC startup pre-flight

# 3. launch (sim/qgc.sh wraps `sg dialout` so step 2 takes effect without re-login)
sim/qgc.sh
# on hosts with broken/dual GPU drivers (NVIDIA Optimus etc.):
QGC_SOFTWARE_RENDER=1 sim/qgc.sh
```

Symptoms → fixes:

| Symptom | Cause | Fix |
|---|---|---|
| `fusermount: not found` / mount fails | no fuse2 on Rocky 9 | extract + run `AppRun` |
| Process exits silently, `journalctl -t setroubleshoot` mentions `execmod` | SELinux blocks QtQml JIT | `setsebool -P selinuxuser_execmod 1` |
| Tiny "must be in dialout / remove modemmanager" dialog then exit | startup pre-flight | usermod + disable ModemManager |
| Window opens but is black / `NVRM` errors in dmesg | broken GL driver | `QGC_SOFTWARE_RENDER=1 sim/qgc.sh` |
| `version 'GLIBC_2.35' not found` | AppImage too new for glibc 2.34 | use older QGC release |
| Window opens but stays "Disconnected" | nothing on UDP 14550 | run mavproxy with `--out udp:127.0.0.1:14550` |

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
ArduCopter SITL has a built-in physics model and needs no external
simulator (no Gazebo, no jmavsim). On Rocky 9 the official
`install-prereqs-ubuntu.sh` won't run, so install the Python deps into
`.venv` directly and rely on the host's gcc/g++ for the build:

```bash
# 1. shallow clone of a stable Copter tag (~1 GB)
mkdir -p ~/sim_tools && cd ~/sim_tools
git clone --recursive --depth 1 --shallow-submodules \
    --branch Copter-4.6.3 https://github.com/ArduPilot/ardupilot.git

# 2. python deps (MAVProxy is only needed if you want a CLI shell or
#    UDP fan-out; our launch.sh is headless and skips it)
.venv/bin/pip install MAVProxy pexpect future 'empy<4' lxml

# 3. build the SITL copter binary (~1 min on first build, ccache cached)
export ARDUPILOT_DIR="$HOME/sim_tools/ardupilot"
cd "$ARDUPILOT_DIR"
./waf configure --board sitl
./waf copter
```

Add to `~/.bashrc`:
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
Terminal 1 (SITL, headless, MAVLink on TCP 5760):
```bash
sim/ardupilot/launch.sh             # default model '+'
# or:  sim/ardupilot/launch.sh quad
```
Terminal 2 (capture telemetry — defaults to tcp:127.0.0.1:5760):
```bash
.venv/bin/python sim/ardupilot/capture.py -o flights/sim_apm_$(date +%Y%m%d_%H%M%S) -t 120
```

QGC over UDP 14550: ArduCopter SITL only exposes TCP 5760. Run
mavproxy.py as a daemon to fan out to UDP — one port per consumer
(QGC, capture.py, run_mission.py) so all three can coexist:
```bash
# terminal 2: TCP 5760 -> UDP 14550 (QGC) + 14551 (capture) + 14552 (mission runner)
.venv/bin/mavproxy.py --master tcp:127.0.0.1:5760 \
                      --out udp:127.0.0.1:14550 \
                      --out udp:127.0.0.1:14551 \
                      --out udp:127.0.0.1:14552 \
                      --non-interactive --daemon
# terminal 3: QGC (auto-binds UDP 14550)
sim/qgc.sh
# terminal 4: capture against the fan-out
.venv/bin/python sim/ardupilot/capture.py -c udp:127.0.0.1:14551 \
    -o flights/sim_apm_$(date +%Y%m%d_%H%M%S) -t 120
```
Note that capture.py and QGC cannot both connect to TCP 5760 directly —
only one TCP client at a time. Either run capture.py against TCP 5760
on its own, or use the mavproxy fan-out above.

## Telemetry topology

ArduCopter SITL only opens one MAVLink endpoint (TCP 5760). Everything
else hangs off a single MAVProxy fan-out. Each consumer takes its own
UDP port so QGC, the headless mission driver, and the capture process
don't fight over the link.

```
┌──────────────────────┐        ┌──────────────────────────┐
│  arducopter (SITL)   │ TCP    │       mavproxy.py        │
│   physics + EKF +    ├────────▶  --master tcp:5760       │
│   AP_Camera backend  │  5760  │  --out udp:14550 (QGC)   │
└──────────────────────┘        │  --out udp:14551 (cap)   │
                                │  --out udp:14552 (miss)  │
                                └──┬───────────┬───────────┘
                                   │           │
                ┌──────────────────┘           └─────────────┐
                ▼                                            ▼
   ┌─────────────────────────┐              ┌─────────────────────────┐
   │  capture.py  (14551)    │              │  run_mission.py (14552) │
   │  SET_MESSAGE_INTERVAL:  │              │  upload .plan, arm,     │
   │   SCALED_IMU2  200 Hz   │              │  takeoff, AUTO, tail    │
   │   GPS_RAW_INT    5 Hz   │              │  CAM1_TRIGG_DIST set    │
   │   ATTITUDE      50 Hz   │              │  via PARAM_SET on 14550 │
   │  event:                 │              └─────────────────────────┘
   │   CAMERA_FEEDBACK       │
   │  → flights/<ts>/clean/  │              ┌─────────────────────────┐
   └─────────────────────────┘              │       QGC (14550)       │
                                            │   passive map view +    │
                                            │   manual overrides      │
                                            └─────────────────────────┘
```

MAVLink streams subscribed by `capture.py` and where they land:

| Stream            | Source msg          | Rate    | Output CSV       |
|-------------------|---------------------|---------|------------------|
| IMU               | `SCALED_IMU2`       | 200 Hz  | `imu.csv`        |
| GPS fix           | `GPS_RAW_INT`       |   5 Hz  | `gps.csv`        |
| Attitude (Euler)  | `ATTITUDE`          |  50 Hz  | `attitude.csv`   |
| Camera trigger    | `CAMERA_FEEDBACK`   |  event  | `triggers.csv`   |
| (joined)          | IMU + nearest GPS   | 200 Hz  | `unified.csv`    |

Achieved rates over the MAVProxy fan-out are typically lower than the
requested rates because MAVProxy collapses duplicate messages across
outputs. For full requested rates, point `capture.py` directly at
`tcp:127.0.0.1:5760` (without QGC / mission runner attached).

`CAMERA_FEEDBACK` is event-driven and only fires when the AP_Camera
backend is instantiated. See **Camera triggering** below.

## Mission workflow

The .plan file is QGC's native JSON; ArduPilot reads it as a series of
MAVLink mission items. Two paths:

### A. Plan + fly in QGC (interactive)
1. In QGC: **Plan** view → drop waypoints → **Upload** → switch to
   **Fly** view → arm → **Start Mission**.
2. Save the plan: Plan view → **Sync → Save to file** →
   `sim/ardupilot/missions/<name>.plan`. Commit it.
3. To replay later, **Open** the saved plan in QGC and Upload.

### B. Headless replay (scriptable, repeatable)
Plan once in QGC and save the .plan, then drive the autopilot from the
CLI via `sim/ardupilot/run_mission.py` — uploads the mission, arms,
takes off, switches to AUTO, and tails progress. QGC stays open as a
passive observer on 14550 if you want a live map view.

```bash
# upload only (mission stays armed-disabled until you start it elsewhere)
.venv/bin/python sim/ardupilot/run_mission.py \
    sim/ardupilot/missions/square_50m.plan

# upload + arm + takeoff + start AUTO + tail until the last waypoint
.venv/bin/python sim/ardupilot/run_mission.py \
    sim/ardupilot/missions/square_50m.plan --auto-start --tail
```

A reference `square_50m.plan` (takeoff → 50 m square → RTL, 30 m AGL,
at the default ArduCopter SITL home location near Canberra) lives in
`sim/ardupilot/missions/`. Use it as a template for your own missions.

Both stacks load the same `.plan` JSON, but waypoint behaviour may
differ slightly between PX4 and ArduPilot (e.g. loiter vs hold
semantics). For best comparability, keep missions simple: takeoff,
waypoint square, land.

## Capture schema

`capture.py` writes the same CSV schema `host/parse_logs.py` produces,
so simulated captures slot into the same downstream tooling. The
ArduPilot capture additionally writes attitude and camera-trigger
streams used by the imagery / georegistration pipeline:

```
flights/sim_apm_<ts>/
├── info.json          run metadata (connection, duration, row counts)
└── clean/
    ├── imu.csv        timestamp_ns, ax_ms2, ..., temp_c                (200 Hz)
    ├── gps.csv        timestamp_ns, time_usec, fix_type, lat_deg, ...    (5 Hz)
    ├── attitude.csv   timestamp_ns, roll/pitch/yaw_deg, rates rad/s     (50 Hz)
    ├── triggers.csv   timestamp_ns, img_idx, lat/lon/alt, r/p/y         (event)
    └── unified.csv    IMU rows + nearest-prior GPS fix
```

`triggers.csv` is the geotag table for the imagery pipeline: one row
per shutter event from `CAMERA_FEEDBACK`, each carrying lat/lon, MSL
and relative altitude, and the vehicle's roll/pitch/yaw at the moment
of the shot. Pair it with `sim/cameras/starling2_hires.json` (sensor
geometry, intrinsics, mount transform) to project a footprint, write
EXIF/MAVLink geotags, or render a synthetic frame against a reference
3D model for georegistration testing.

`attitude.csv` is the dense interpolation source for any
non-shot-aligned timestamps (e.g. resampling to camera-IMU offsets, or
filling in attitude between geotag rows).

PlotJuggler, parsing tests, and `shared/compare.py` all work the same
on real and simulated flights.

## Camera triggering (ArduPilot SITL)

The AP_Camera backend is **not** instantiated by default in SITL — by
default `CAM1_TYPE = 0` and any `DO_DIGICAM_CONTROL` /
`IMAGE_START_CAPTURE` / `DO_SET_CAM_TRIGG_DIST` is silently a no-op.

`sim/ardupilot/camera_defaults.parm` is chained after `copter.parm` by
`launch.sh` and sets:

```
CAM1_TYPE        1     # Servo backend; emits CAMERA_FEEDBACK on every shot
SERVO9_FUNCTION  10    # AUX1 -> k_cam_trigger PWM output
```

`CAM1_TYPE` is read **once at boot**. Setting it via `PARAM_SET` at
runtime exposes the param block but does not allocate the backend
until the autopilot reboots — keep it in the .parm file.

Trigger sources, in order of operational realism:

| Trigger                          | Use it for                            |
|----------------------------------|---------------------------------------|
| `MAV_CMD_DO_DIGICAM_CONTROL`     | manual one-shot from a script         |
| `MAV_CMD_IMAGE_START_CAPTURE`    | one-shot or N-shot from QGC / script  |
| `CAM1_TRIGG_DIST = N` (metres)   | distance-based auto trigger in AUTO   |
| `MAV_CMD_DO_SET_CAM_TRIGG_DIST`  | mission-item-driven dist trigger      |

Distance-based triggering is the fastest path to a populated
`triggers.csv` over a real flight: set `CAM1_TRIGG_DIST` via
`PARAM_SET` on UDP 14550 immediately before starting the mission, and
the autopilot fires + emits `CAMERA_FEEDBACK` every N metres of
horizontal travel.

> Modern AP_Camera no longer emits the legacy `CAMERA_TRIGGER` (msg
> 112). `capture.py` subscribes only to `CAMERA_FEEDBACK` (msg 180),
> which carries geotag and attitude in a single message.

## GPS-denied capture (vision-nav consumers)

The end goal is a flight dataset that a GPS-denied, vision-based
navigation stack can ingest as if it had been recorded on a real drone
without GPS. Two paths:

### A. Capture with GPS, suppress on consumption (default, easiest)

Fly the mission with the standard configuration — full GPS available
to the EKF and to mission planning — then simply **don't pass
`gps.csv`** to the vision-nav consumer. `imu.csv`, `attitude.csv`,
`triggers.csv`, and the rendered imagery are all GPS-independent and
form a complete GPS-denied input set. `gps.csv` is still useful as
ground-truth for scoring the vision-nav output.

This is the recommended path for quick iteration: nothing about the
SITL flight changes, you just split the dataset at the consumer
boundary.

### B. Fly GPS-denied in SITL (optical flow EKF)

For a stricter test where the autopilot itself has no GPS solution,
chain ArduPilot's stock optical-flow profile via the
`EXTRA_PARMS` env var picked up by `launch.sh`:

```bash
EXTRA_PARMS="$ARDUPILOT_DIR/Tools/autotest/default_params/copter-optflow.parm" \
    sim/ardupilot/launch.sh
```

That profile sets `EK3_SRC1_POSXY=0`, `EK3_SRC1_VELXY=5` (optical
flow), `FLOW_TYPE=10` and `SIM_FLOW_ENABLE=1`, and configures
`RNGFND1_*` for the SITL rangefinder. The EKF then has to navigate
from optical-flow velocity + baro/rangefinder altitude only.

Caveats:
- AUTO missions with absolute lat/lon waypoints will not work without
  a GPS-derived position estimate; fly LOITER / GUIDED-relative
  trajectories in this mode, or use path B only for hover / position
  hold benchmarks.
- For mission-style replays under GPS denial, use the stock
  `copter-vicon.parm` profile and feed `VISION_POSITION_ESTIMATE`
  messages from your vision-nav stack so the EKF has an external
  position source.
- `gps.csv` will be empty (or sparse / `fix_type=0`) in this mode by
  construction; treat it as expected, not a capture bug.

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
