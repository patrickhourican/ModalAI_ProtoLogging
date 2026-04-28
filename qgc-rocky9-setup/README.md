# QGroundControl on Rocky 9 / RHEL 9

Standalone launcher + setup notes for getting QGroundControl running on
Rocky Linux 9 (and other RHEL-family distros). Works around three host
quirks the upstream AppImage doesn't handle:

- SELinux blocks Qt's QtQml JIT (W^X enforcement)
- QGC refuses to start unless the user is in `dialout`
- QGC refuses to start while ModemManager is active

Tested with **QGC v5.0.8** on Rocky 9.x (glibc 2.34), GNOME/X11 session.

## Install

```bash
# 1. download + extract (no fuse2 on stock Rocky 9, so don't try to mount)
mkdir -p ~/sim_tools && cd ~/sim_tools
curl -L -o QGroundControl.AppImage \
  https://github.com/mavlink/qgroundcontrol/releases/download/v5.0.8/QGroundControl-x86_64.AppImage
chmod +x QGroundControl.AppImage
./QGroundControl.AppImage --appimage-extract            # produces ./squashfs-root/

# 2. one-time host fixes (each is reversible — see bottom of this file)
sudo setsebool -P selinuxuser_execmod 1                 # SELinux: QtQml JIT
sudo usermod -aG dialout $USER                          # QGC startup pre-flight
sudo systemctl disable --now ModemManager               # QGC startup pre-flight
```

## Launch

```bash
./qgc.sh
```

The script wraps the launch in `sg dialout` so step 2's group change
takes effect without a re-login. Override the AppImage location with
`QGC_DIR=/path/to/squashfs-root ./qgc.sh` if you extracted somewhere
other than `~/sim_tools/`.

On hosts with a broken or hybrid GPU stack (NVIDIA Optimus, etc.) where
QGC opens but renders black or hangs:

```bash
QGC_SOFTWARE_RENDER=1 ./qgc.sh
```

## Connecting to a vehicle

QGC auto-binds **UDP 14550** at startup. Anything that emits MAVLink to
that port — a real radio link, a SITL fan-out, mavproxy `--out
udp:127.0.0.1:14550` — will appear as a vehicle within ~1 s.

## Symptoms → fixes

| Symptom | Cause | Fix |
|---|---|---|
| `fusermount: not found` / mount fails | no fuse2 on Rocky 9 | extract + run `AppRun` (the install steps above) |
| Process exits silently, `journalctl -t setroubleshoot` mentions `execmod` | SELinux blocks QtQml JIT | `sudo setsebool -P selinuxuser_execmod 1` |
| Tiny "must be in dialout / remove modemmanager" dialog then exit | startup pre-flight check | usermod + disable ModemManager (steps above) |
| Window opens but is black / `NVRM` errors in `dmesg` | broken or hybrid GL driver | `QGC_SOFTWARE_RENDER=1 ./qgc.sh` |
| `version 'GLIBC_2.35' not found` | AppImage too new for glibc 2.34 | use QGC v5.0.8 (instructions above) or older |
| Window opens but stays "Disconnected" | nothing on UDP 14550 | start something that emits MAVLink to that port |

## Reverting the host fixes

All three changes from step 2 are easily undone:

```bash
sudo setsebool -P selinuxuser_execmod 0
sudo gpasswd -d $USER dialout
sudo systemctl enable --now ModemManager
```

## Notes

- `selinuxuser_execmod` lets unconfined user-domain processes mark a
  page writable + executable (i.e. JIT). All other SELinux rules still
  apply (network, file labels, type transitions, confined daemons).
- `disable --now ModemManager` stops the service and prevents it
  starting on boot. The rpm stays installed because NetworkManager
  pulls it in for cellular handling on some systems.
- Headless / no-GPU hosts: add `QT_QPA_PLATFORM=offscreen` in front of
  the launch (not currently exposed by the script, but trivial to wire
  in if you need it).
