# Raspberry Pi Camera

Minimal camera service for the Raspberry Pi 3B+ robot base.

## What This Uses

Current camera:

- Sensor: OV5647
- Stack: modern Raspberry Pi camera stack, `rpicam-*` / `libcamera`
- Overlay: `dtoverlay=ov5647`
- Web app: `/home/joey/camera/app.py`
- Recordings: `/home/joey/camera-recordings/`
- Service: `pi-camera-web.service`

## Web UI

Open from the PC:

```text
http://192.168.0.43:8080
```
The UI does three things:

- Shows a live MJPEG preview stream.
- Starts and stops MJPEG recording using `rpicam-vid`.
- Lists recordings as clickable downloads.

## Service Commands

Status:

```bash
systemctl status pi-camera-web.service
```

Restart:

```bash
sudo systemctl restart pi-camera-web.service
```

Logs:

```bash
journalctl -u pi-camera-web.service -f
```

Enable on boot:

```bash
sudo systemctl enable --now pi-camera-web.service
```

## Health Check

From the Pi:

```bash
curl http://127.0.0.1:8080/health
```

From the PC:

```bash
curl http://192.168.0.43:8080/health
```

Healthy output starts with:

```text
ok
Available cameras
```

and should list `ov5647`.

## Manual Camera Tests

List cameras:

```bash
rpicam-hello --list-cameras
```

Take a still:

```bash
rpicam-still -n -t 2000 -o /tmp/test.jpg
```

Record 10 seconds of MJPEG:

```bash
rpicam-vid -n \
  --codec mjpeg \
  --width 1296 \
  --height 972 \
  --framerate 15 \
  --timeout 10000 \
  --output /tmp/test.mjpeg
```

## Recording Files

Recordings are saved as:

```text
/home/joey/camera-recordings/recording-YYYYMMDD-HHMMSS.mjpeg
```

`app.py` shells out to:

- `rpicam-hello --list-cameras` for health.
- `rpicam-vid --codec mjpeg` for the live stream and recordings.

## Web Controls

- `Invert` maps directly to `rpicam-vid --hflip` and `--vflip`.
- `Dewarp model strength` uses a radial remap model in Python. It is a real undistortion stage, not a crop.
- `Preview FPS` changes the live MJPEG stream and recording frame rate together, which keeps the implementation simple and avoids split camera pipelines.

## Robot Integration

For the robot, keep this as the camera component. Put motors and speech behind separate services or modules.

Recommended shape:

```text
robot web/API server
├── camera: this service or module
├── motors: safe motion primitives + watchdog
├── speech: text-to-speech
└── planner: VLM calls bounded actions
```

Do not let a VLM directly set GPIO/PWM. Give it safe primitives such as:

- `stop`
- `turn_left`
- `turn_right`
- `drive_forward_for_ms`
- `say`
- `capture_frame`

Add a hardware emergency stop before attaching real motors.

## Useful Links

- Raspberry Pi camera software docs: https://www.raspberrypi.com/documentation/computers/camera_software.html
- `rpicam-apps` options reference: https://www.raspberrypi.com/documentation/computers/camera_software.html#rpicam-apps-options-reference
- Raspberry Pi camera hardware docs: https://www.raspberrypi.com/documentation/hardware/camera/
- Raspberry Pi `config.txt` camera settings: https://www.raspberrypi.com/documentation/computers/config_txt.html#camera-settings
- Raspberry Pi SSH/remote access docs: https://www.raspberrypi.com/documentation/computers/remote-access.html
- Raspberry Pi GPIO from Python: https://www.raspberrypi.com/documentation/computers/os.html#gpio-in-python

## Known Hardware Notes

- The fake/counterfeit microSD is not suitable for booting. Keep using the USB boot drive until you replace it with a real card or SSD.
- If the Pi becomes unreachable after heavy I/O, suspect storage instability first.
- Current camera is OV5647. Do not use the old `dtoverlay=imx219` line unless the sensor changes again.
