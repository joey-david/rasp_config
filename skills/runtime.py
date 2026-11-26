"""Small runtime helpers shared by actuating skills."""

import time


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
):
    deadline = time.monotonic() + max(0.0, float(seconds))
    while not stop_event.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        robot.movement.set_velocity(linear, angular, source=source)
        if stop_event.wait(min(refresh_seconds, remaining)):
            break
    robot.movement.stop(source=source)
    if settle_seconds and not stop_event.is_set():
        time.sleep(settle_seconds)
