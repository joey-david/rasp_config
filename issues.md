# Software redesign issues

## L0 — Edge safety

- [ ] The robot cannot reliably detect a drop and stop before the edge.

## L1 — Wheel control

- [ ] Equal wheel commands appear to produce unequal travel.
- [ ] Battery charge changes wheel response, making timed moves and emotes inconsistent.
- [ ] Mixing forward and turn commands can leave one wheel below its starting duty (forward 40, turn 35 gives 70/5 after clipping).
- [x] Watchdog could stop a fresh command after its timeout check (fixed and replayed offline).
- [ ] UDP drive commands can override an active skill without acquiring motor control.

## L2 — Tracking and contact

- [x] Follow and lock-on issued wrong-side turns after a detected center crossing (fixed in offline replay).
- [ ] Follow can act on an old detection without checking its age at motor start.
- [ ] Lock-on ignores the requested track ID and can switch between same-label targets.
- [ ] Follow reports requested motion even when edge safety vetoes it.
- [ ] Pushing fails in practice. At close range the detector can lose the object before contact is confirmed.

## L3 — Autonomous decisions

- [ ] The map advances on wheel commands even when the robot stalls.
- [ ] A delayed planner reply can dispatch an action after its observation is obsolete.
