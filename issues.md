# Software redesign issues

## L0 — Edge safety

- [ ] The robot cannot reliably detect a drop and stop before the edge.

## L1 — Wheel control

- [ ] Equal wheel commands appear to produce unequal travel.
- [~] Battery charge changes wheel response, making timed moves and emotes inconsistent (adaptive `PowerGauge` ramp calibration + 3-stall auto-bump added for skill floors; emote scaling still open).
- [x] Mixing forward and turn commands can leave one wheel below its starting duty (follow now separates turning from advancing and enforces the minimum turn floor).
- [x] Watchdog could stop a fresh command after its timeout check (fixed and replayed offline).
- [ ] UDP drive commands can override an active skill without acquiring motor control.

## L2 — Tracking and contact

- [x] Follow and lock-on issued wrong-side turns after a detected center crossing (fixed in offline replay).
- [x] Lock-on kept turning during inference (bounded pulses centered a person in a live 20-cycle test).
- [ ] Follow can act on an old detection without checking its age at motor start.
- [ ] Lock-on ignores the requested track ID and can switch between same-label targets.
- [x] Follow reports requested motion even when edge safety vetoes it (follow now reports `phase="blocked"` with zero linear/turn and the cockpit displays safety vetoes).
- [ ] Pushing fails in practice. At close range the detector can lose the object before contact is confirmed.

## L3 — Autonomous decisions

- [ ] The map advances on wheel commands even when the robot stalls.
- [ ] A delayed planner reply can dispatch an action after its observation is obsolete.

## Architecture review · 2026-11-28 · revision 227cdad

**Build order.** First make the Pi the sole authority for who can move, for how long, and on which safety evidence. Next give L2 a fresh, identified observation and a measured action result. Then let L3 choose among the skills that demonstrably work. Keep camera capture, edge checks and stopping on the Pi, YOLO on the Mac, and the slower VLM at action boundaries. All four levels can stay in the existing Pi process.

**Bench evidence.** Neon recorded 28 distinct procedure runs. Across six completed six-second follow runs, forward-command sample counts ranged from 0 to 15 and normalized box-height change ranged from −0.06 to +0.12. Two runs with zero forward samples had different causes: one reported an edge veto, the other issued seven pivot samples with six reversals. These are sampled commands and image measurements. They cannot identify wheel travel, isolate battery effects, or prove that a tuning change caused the difference.

### First — ownership, stopping and support

- [ ] HTTP checks skill ownership before dispatch, UDP calls RobotAPI directly, and a pending worker can clear its own stop event after cancellation. Give RobotAPI one action owner with a generation number. Acquire before starting work, inherit it for nested skills, revoke before stopping, and validate at the final wheel write. Replay stop during startup, inference and nested skill entry. See `web/web_interface.py`, `hardware/motion_udp.py`, `skills/runtime.py`.
- [ ] A single sequence counter spans clients, and a stale sequence can reject stop. Scope ordered movement to the active session, accept stop independently of sequence, and require a fresh owner to resume. Test reconnect, reordered packets and a stopped client's late reply. See `robot_api.py` methods `_fresh_motion_seq` and `stop`.
- [ ] A successful safety check and the motor write are separate operations. Bind each write to the latest valid safety verdict and owner at application time. Replay a veto between check and write. See `RobotAPI._velocity`, `safety.enforce`, `Motion.tank`.
- [ ] The monitor and command path both evaluate the edge detector. The detector records the frame timestamp before finishing its features, so a second caller can receive the preceding verdict for the new frame. Give the monitor one immutable frame/timestamp pair and publish one completed verdict per frame. Fail closed until that verdict is ready and fresh. See `hardware/safety/danger.py` and `hardware/safety/safety.py`.
- [ ] A forward-facing texture cue covers only part of the support surface. Reverse and pivot bypass the forward veto, and the chassis corners sweep outside the camera strip. Define allowed motion from observed support and measured stopping distance. Test corners, glare, shadows and low-texture surfaces on a restrained rig. If the required area remains unobservable, restrict tabletop motion or add a downward sensor.
- [ ] The software watchdog uses wall time and shares the motor process. Use monotonic command expiry, reject nonfinite inputs at the motor boundary, and verify what the driver does if the process hangs or loses power. Require an independent motor timeout if the wheels can stay energized. See `hardware/motion.py`, `hardware/motors.py`.
- [ ] A partial GPIO write can leave the driver active before Motion records the failed command. Disable standby on write failure, latch the fault and require an explicit re-arm. Inject backend failures on each wheel write and verify the enable line on hardware. See `Motors.drive` and `Motion.tank`.
- [ ] HTTP and UDP accept motion on network listeners. Bind control to a trusted operator connection, authorize actuating routes, bound request sizes and separate read-only telemetry. Test rejected commands with a fake backend. See `web/web_interface.py`, `hardware/motion_udp.py`.

### Next — one observation and one motion result

- [ ] Camera frame time begins after JPEG parsing/cropping. Follow bounds elapsed request time, while lock-on and other skills apply different freshness rules. Carry frame ID, local frame-ready time, capture mode and deadline through observation, selection and actuation. Measure camera buffering separately. Reject a late result even when inference succeeds. See `perception/camera.py`, `perception/vision.py`, `skills/follow.py`, `skills/lock_on.py`.
- [ ] Maximum stills suspend the safety stream, and contact confirmation can request several. Keep the safety stream continuous or make still capture an explicit stationary mode with fresh support evidence required before resuming. Exercise capture failure and stream restart. See `Camera.maximum_snapshot`, `ObjectSkills._approach`.
- [ ] Background scans, target requests, pair sampling and planning contend for the same detector and inference lock. Reuse one Pi vision worker with a latest-frame request slot and frame-tagged results. Give active skills priority, discard superseded work and limit high-resolution requests to cases where they change a decision. Benchmark observation age and stop latency under contention. See `VisionScanner.exclusive`, `detect_target_samples`, `capture_detect_all`.
- [ ] Perception exposes raw boxes, enriched detections, a receiver map and a command-integrated spatial map. Return one observation to skills, telemetry and planning. Keep the current image-space scene authoritative and mark historical sightings with age and pose uncertainty. Remove redundant map fields after migrating callers. See `perception/remote.py`, `receiver.py`, `spatial_map.py`, `RobotAPI.ingest_detections`.
- [ ] Label plus horizontal proximity loses identity at crossings, and semantic resolution always chooses a nearest supported class. Bind a target to an observation, track spatial continuity across a short gap, and report ambiguity or unsupported labels. Require reacquisition before approach or contact. Replay two people crossing and an unknown object name. See `select_target`, `skills/lock_on.py`, `pc_inference/resolve_label.py`.
- [ ] Wheel duty, target box motion and actual chassis motion are distinct. Record requested duty, accepted wheel pair, veto, command expiry and independent displacement under one action ID. Timestamp the applied pair inside the wheel lock so map updates retain write order. See `Motion.tank`, `Motion._notify`, `SpatialMap.command`.
- [ ] A scene shift after a pulse can come from target motion, and repeated failed probes can push the working floor upward. Treat calibration as a stationary-scene experiment, keep confirmed floors per axis, and report inconclusive measurements. Characterize each wheel, direction, load and surface before introducing battery compensation. See `skills/power_gauge.py`, `skills/runtime.py`, `perception/odometry/runtime.py`.
- [ ] Multiple skills own variants of turn, settle, stop and veto handling. Keep one bounded pivot and one capped forward-arc primitive with an explicit result. Find owns search, lock owns bearing, follow owns bearing plus image-size regulation, and emotes own sequences. Retire unused stuck bonuses and the rotation-setpoint API if caller inspection confirms they have no consumer. See `robot_api.py`, `skills/objects.py`, `skills/emotes.py`, `skills/runtime.py`.
- [ ] Box height, bottom-edge proximity and two-dimensional overlap do not establish contact or arrival. Restrict push to an allowed movable object, stop on loss of identity or support, and verify object displacement relative to the scene after each push. Treat target loss near the bumper as unknown. Test foreground/background overlap and a stationary object while the camera moves. See `ObjectSkills._approach`, `push`, `_push_toward`.

### Then — bounded autonomy for a prankster robot

- [ ] A successful planner response can outlive its scene. Include observation revision, action deadline and preconditions in the proposal. Recheck them on the Pi before dispatch. Exercise a moved target, expired observation and operator stop while the planner is busy. See `AutonomyController._sense`, `_run`, `RemotePlanner.plan`.
- [ ] Planner, prompt, capability advertisement, validation and execution each encode action semantics. Generate the advertised schema from a single registry of enabled Pi skills, argument limits, preconditions and result types. Omit disabled contact actions and advertise bounded follow only when its loss and stop behavior pass. See `autonomy/controller.py`, `pc_inference/vlm_server.py`.
- [ ] The planner can declare completion with stop, and three explicit failures miss repeated successful actions with no progress. Let the operator choose a reversible routine with an observable end condition, such as find person → center → emote once → stop. Give the run a time budget and terminate on repeated unchanged observations. Keep the VLM for choosing or revising intent. Record completion, abandonment and operator interruption separately.
- [ ] Planning waits synchronously for a remote call, with a default 60 s Pi timeout and 120 s upstream timeout. Propagate one end-to-end deadline, cancel or discard expired upstream work, and expose planner availability independently of camera, detector and manual control. On loss of inference, let active visual motion expire locally. See `autonomy/remote.py`, `pc_inference/vlm_server.py`.
- [ ] A 120 s landmark lifetime can turn moving people or mistaken identities into durable locations. Start with last-seen bearing and confidence for reacquisition. Use accumulated pose only where measured drift improves search over a turn-and-look baseline. See `perception/spatial_map.py`.

### Make the design diagnosable and deployable

- [ ] Polling status can miss short pulses and GET odometry advances the estimator. Run odometry once per fresh frame when needed, make status reads side-effect free, and record command transitions at the producer. Report detector queue/compute time separately from total HTTP time. See `web/static/cockpit.js`, `web/web_interface.py`, `perception/receiver.py`, `skills/procedures.py`.
- [ ] A final centered sample or any positive box-height change can pass a benchmark despite oscillation or target motion. Score sustained center time, reversals, visibility gaps and displacement against a stationary reference. Report vetoes, cancellations and inconclusive trials separately. Compare matched starts, surfaces and battery states. See `skills/procedures.py`.
- [ ] Shared requirements mix Pi GPIO, Mac model tooling and planner packages. The detector launcher and shared requirements even select different Transformers ranges. Split dependencies by executable, pin tested environments and expose model/version/config in health responses. See `requirements.txt`, `bin/start-pc-inference.sh`, `bin/start-vlm-inference.sh`.
- [ ] Deployment syncs live directories, removes files under the Pi home and verifies only service activity. Stage a versioned release outside user data, validate imports/config, stop motion, switch releases atomically and check a fresh frame, safety state and zero wheel duty. Keep credentials out of remote command arguments. See `bin/deploy-pi.sh`, `systemd/mischief-bot.service`.

**First end-to-end acceptance run.** Delay a detection, revoke the skill, then deliver the detection while a new manual owner is active. The old skill must issue zero accepted wheel writes and must never stop the new owner in its cleanup. Next measure physical stop distance on the supported surfaces. Only then compare tracking on matched runs and score one complete find–center–emote routine. Keep contact disabled until its separate physical checks pass.
