"""Small runtime helpers shared by actuating skills."""

import time

from skills.tuning import FORWARD_MAX, FORWARD_MIN, TURN_MAX, TURN_MIN


def turn_bounds(robot, default_min=TURN_MIN, default_max=TURN_MAX):
    movement = getattr(robot, "movement", None)
    fn = getattr(movement, "turn_bounds", None)
    if callable(fn):
        return fn(default_max=default_max)
    return float(default_min), float(default_max)


def forward_bounds(robot, default_min=FORWARD_MIN, default_max=FORWARD_MAX):
    movement = getattr(robot, "movement", None)
    fn = getattr(movement, "forward_bounds", None)
    if callable(fn):
        return fn(default_max=default_max)
    return float(default_min), float(default_max)


def turn_pulse_seconds(error, spinup_s=0.055, gain=0.55, min_s=0.085, max_s=0.22):
    """Compensate motor static-friction spin-up (~55 ms) with damped duration gain so turns never overshoot."""
    raw = float(spinup_s) + abs(float(error)) * float(gain)
    return round(max(float(min_s), min(float(max_s), raw)), 3)


class VisualTurnController:
    """Smooth delayed box centers and reject one-frame turn reversals."""

    def __init__(self, stop_deadband, alpha=0.45, reverse_frames=2):
        self.stop_deadband = float(stop_deadband)
        self.alpha = float(alpha)
        self.reverse_frames = int(reverse_frames)
        self.filtered = None
        self.direction = 0
        self.pending_direction = 0
        self.pending_frames = 0

    def update(self, raw_offset):
        raw_offset = float(raw_offset)
        self.filtered = (
            raw_offset
            if self.filtered is None
            else self.alpha * raw_offset + (1 - self.alpha) * self.filtered
        )
        wanted = (
            1
            if self.filtered > self.stop_deadband
            else -1
            if self.filtered < -self.stop_deadband
            else 0
        )
        if not wanted:
            self.direction = self.pending_direction = self.pending_frames = 0
            return self.filtered, True
        # The latest box must still support the proposed turn.
        if wanted * raw_offset <= self.stop_deadband:
            self.pending_direction = self.pending_frames = 0
            return self.filtered, False
        if not self.direction or wanted == self.direction:
            self.direction = wanted
            self.pending_direction = self.pending_frames = 0
            return self.filtered, True
        if wanted != self.pending_direction:
            self.pending_direction, self.pending_frames = wanted, 1
        else:
            self.pending_frames += 1
        if self.pending_frames < self.reverse_frames:
            return self.filtered, False
        self.direction = wanted
        self.pending_direction = self.pending_frames = 0
        return self.filtered, True


class SkillStatus:
    def __init__(self, initial=None):
        self._data = dict(initial or {})

    def update(self, **items):
        self._data = {**self._data, **items}
        return self.snapshot()

    def reset(self, **items):
        self._data = dict(items)
        return self.snapshot()

    def snapshot(self):
        return dict(self._data)


def number(value, default, lo=None, hi=None):
    try:
        out = float(value)
    except Exception:
        out = float(default)
    if lo is not None:
        out = max(lo, out)
    if hi is not None:
        out = min(hi, out)
    return out


def integer(value, default, lo=None, hi=None):
    return int(number(value, default, lo, hi))


def timed_velocity(
    robot,
    stop_event,
    linear,
    angular,
    seconds,
    source,
    settle_seconds=0.0,
    refresh_seconds=0.2,
    observe_stall=True,
):
    duration = max(0.0, float(seconds))
    gauge = getattr(robot, "power_gauge", None) if observe_stall else None
    odometry = getattr(robot, "odometry", None) if gauge is not None else None
    pure_turn = bool(angular) and not bool(linear)
    axis = "turn" if pure_turn else None
    before_gray, before_id = None, None
    if (
        axis
        and duration >= 0.085
        and odometry is not None
        and hasattr(odometry, "capture_gray")
        and hasattr(odometry, "measure_shift")
    ):
        before_gray, _, before_id, _ = odometry.capture_gray()

    deadline = time.monotonic() + duration
    result = None
    vetoed = False
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = robot.movement.set_velocity(linear, angular, source=source)
        if result and result.get("ok") is False:
            vetoed = True
            break
        if stop_event.wait(min(refresh_seconds, remaining)):
            break
    robot.movement.stop(source=source)
    if settle_seconds and not stop_event.is_set():
        time.sleep(settle_seconds)

    if before_gray is not None and not vetoed and not stop_event.is_set():
        stop_id = before_id or 0
        camera = getattr(robot, "camera", None)
        if camera is not None and hasattr(camera, "latest"):
            _, _, latest_id = camera.latest()
            if latest_id:
                stop_id = max(stop_id, latest_id)
        # Wait past camera pipeline latency (~2 frames at 30fps) when no settle delay ran.
        target_id = stop_id + (0 if settle_seconds >= 0.06 else 2)
        after_gray, _, _, _ = odometry.capture_gray(after_frame_id=target_id, timeout=0.14)
        if after_gray is not None:
            shift = odometry.measure_shift(before_gray, after_gray)
            power_cap = getattr(getattr(robot, "motion", None), "power", None)
            gauge.observe_pulse(axis, abs(angular), shift["dx"], shift["fresh"], power_cap=power_cap)
    return result
