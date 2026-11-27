# Mischief Bot

The robot has three running parts:

1. A Mac runs YOLO object detection on port `8081`.
2. A planner shim runs on port `8090` and calls an OpenAI-compatible VLM.
3. The Raspberry Pi runs the camera, safety, motion, skills, and web cockpit on
   port `8080`.

Start them in that order. The Pi must be able to reach the Mac or GPU host URLs
set in `systemd/mischief-bot.service`.

## 1. Object Detection on the Mac

Requirements: macOS, Apple silicon, and [`uv`](https://docs.astral.sh/uv/).
The first run downloads the YOLO model. No API key is needed.

```sh
bin/start-pc-inference.sh
```

Useful settings:

```sh
DETECT_PORT=8081 \
OBJECT_MODEL=yolo11s.pt \
OBJECT_IMGSZ=640 \
OBJECT_CONF=0.15 \
bin/start-pc-inference.sh
```

Check it:

```sh
curl http://127.0.0.1:8081/health
```

The Pi uses `PC_DETECT_URL`. High-detail skill requests use up to
`MAX_DETECT_IMGSZ=1920`; the camera still captures at its full still-image
size.

## 2. VLM Planner

The planner shim accepts robot observations and images, then asks an
OpenAI-compatible `/v1/chat/completions` server for one bounded action.

Install the server dependencies:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Test the full HTTP path without a model or API key:

```sh
VLM_PLANNER_TOKEN=local-test \
  .venv/bin/python pc_inference/vlm_server.py --mock
```

For local inference on a 16 GB Apple silicon Mac, start the bundled 4-bit
Qwen3-VL 8B model, then start the planner shim in another terminal:

```sh
bin/start-vlm-inference.sh
```

```sh
VLM_MODEL=mlx-community/Qwen3-VL-8B-Instruct-4bit \
VLM_PLANNER_TOKEN=choose-a-shared-token \
  .venv/bin/python pc_inference/vlm_server.py
```

The model is cached after its first download. `VLM_INFERENCE_HOST`,
`VLM_INFERENCE_PORT`, and `VLM_MAX_KV_SIZE` tune the local inference server.
The defaults bind it to `127.0.0.1:8000` and cap the context cache at 4096
tokens.

For a real remote VLM:

```sh
VLM_BASE_URL=http://gpu-host:8000/v1 \
VLM_MODEL=your-vision-model \
VLM_API_KEY=your-upstream-key \
VLM_PLANNER_TOKEN=choose-a-shared-token \
  .venv/bin/python pc_inference/vlm_server.py
```

`VLM_MODEL` is required outside mock mode. `VLM_API_KEY` is needed only when
the upstream VLM server checks bearer tokens. `VLM_PLANNER_TOKEN` protects this
shim; it is optional, but when set it must use the same value on the Pi.

Check it:

```sh
curl http://127.0.0.1:8090/health
```

## 3. Raspberry Pi

Install the Pi packages once:

```sh
python3 -m pip install -r requirements.txt
```

Set the detector and planner addresses in `systemd/mischief-bot.service`.
If the planner shim uses a token, add:

```ini
Environment=VLM_PLANNER_TOKEN=choose-a-shared-token
```

Deploy from the Mac:

```sh
PI_HOST=rpi bin/deploy-pi.sh
```

The deploy command uses SSH, syncs the robot code, installs the systemd unit,
and restarts `mischief-bot.service`. The Pi user needs password-free `sudo` for
those service commands, or you can set `PI_SUDO_PASSWORD` for that run.

View live coordinated logs:

```sh
ssh rpi 'journalctl -fu mischief-bot.service'
```

Open the cockpit:

```text
http://raspberrypi.local:8080/
```

The cockpit can run `find`, `follow`, `go_to`, `push`, `push_to`, emotes, and
level-3 autonomy. Keep `EDGE_SAFETY_ENABLED=1`. Contact actions from autonomy
remain off unless `AUTONOMY_ALLOW_CONTACT=1`.

## Motor Power Gauge

Below a battery-dependent PWM duty cycle, the motors cannot overcome static
friction. `skills/power_gauge.py` tracks the live minimum power floor for turns
and forward moves so skills adapt as batteries drain or change:

- **Ramp calibration:** open the cockpit **Menu** and click **Calibrate min
  power**, or call `POST /skill/power-gauge`. The robot sends short alternating
  in-place turn pulses (`0.12s`, `linear=0`), starting at `15%` and stepping up
  by `3%` until visual odometry confirms rotation in both directions (`|dx| >=
  0.5 px`). It stores `breakaway + 2%` as the new floor.
- **Online stall recovery:** during normal `lock_on`, `find`, and `follow`
  pulses, `timed_velocity` compares camera frames before and after each pulse.
  If three short pulses in a row fail to move the robot while odometry is fresh,
  the gauge bumps the minimum power up by `3%` and keeps bumping on subsequent
  stalled pulses until motion succeeds, then saves the working value.
- **Persistence & HUD:** the remembered floor is saved to
  `~/.local/state/mischief-bot/power_gauge.json` (override with
  `MOTOR_POWER_GAUGE_FILE`), exposed at `/api/state` under `power_gauge`, and
  shown as **Min pwr** in the cockpit HUD.

## Local Checks

These checks do not need the robot or API keys:

```sh
.venv/bin/python -m unittest discover -s tests -v
ruff check --ignore E401,E402,E701,E702,F841 \
  autonomy hardware/motion.py hardware/safety mischief_common pc_inference \
  perception robot_api.py skills tests web/web_interface.py
node --check web/static/cockpit.js
bash -n bin/deploy-pi.sh
```

Physical edge, wheel, approach, and push checks still require the Pi on flat,
clear ground with space around it.

Run the live non-moving checks with:

```sh
ROBOT_HARDWARE_TESTS=1 .venv/bin/python -m unittest tests.test_live_robot -v
```

With the robot on clear, flat ground, enable the bounded wheel and fault tests:

```sh
ROBOT_HARDWARE_TESTS=1 ROBOT_MOTION_TESTS=1 ROBOT_FAULT_TESTS=1 \
ROBOT_FOLLOW_TARGET='visible label' ROBOT_GOTO_TARGET='safe visible label' \
  .venv/bin/python -m unittest tests.test_live_robot -v
```

Contact stays off unless the test area contains a safe movable object. To test
it, also set `ROBOT_CONTACT_TESTS=1` and `ROBOT_PUSH_TARGET`.
