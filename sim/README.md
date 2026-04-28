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
│   ├── launch.sh           boots ArduCopter SITL headless (TCP 5760)
│   ├── capture.py          same CSV schema, MAVLink over TCP 5760
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
