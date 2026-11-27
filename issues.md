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
