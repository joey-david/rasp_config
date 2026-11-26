"""Adaptive motor breakaway power gauge and online stall tracker."""

from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time

from skills.tuning import FORWARD_MAX, FORWARD_MIN, TURN_MAX, TURN_MIN

DEFAULT_STATE_PATH = Path(
    os.environ.get(
        "MOTOR_POWER_GAUGE_FILE",
        Path.home() / ".local" / "state" / "mischief-bot" / "power_gauge.json",
    )
)

MIN_ALLOWED_POWER = 15.0
MAX_ALLOWED_POWER = 48.0
HEADROOM = 10.0

DEFAULT_START_POWER = 15.0
DEFAULT_STEP = 3.0
DEFAULT_MARGIN = 5.0
DEFAULT_PULSE_SECONDS = 0.11
DEFAULT_SETTLE_SECONDS = 0.08
DEFAULT_PRE_SETTLE_SECONDS = 0.35

DEFAULT_STALL_LIMIT = 3
DEFAULT_BUMP_STEP = 3.0
TURN_MOTION_DX = 0.5
CALIBRATE_MOTION_DX = 0.8
CALIBRATE_MIN_SCORE = 0.15
LINEAR_MOTION_DY = 0.5
MIN_OBSERVE_SECONDS = 0.085


def _clamp(value: float, lo: float = MIN_ALLOWED_POWER, hi: float = MAX_ALLOWED_POWER) -> float:
    return round(max(lo, min(hi, float(value))), 1)


class PowerGauge:
    """Measure and remember the minimum PWM power that breaks motor static friction.

    Two paths keep the floor accurate as batteries discharge or change:
    1. ``calibrate(robot)`` ramps short in-place turn pulses from a low floor until
       visual odometry confirms motion, then stores breakaway + safety margin.
    2. ``observe_pulse(...)`` watches real skill pulses; after ``stall_limit``
       consecutive stalled pulses, it bumps the floor up until a pulse moves and
       persists the working value.
    """

    def __init__(
        self,
        path: Path | str | None = None,
        min_turn: float = TURN_MIN,
        min_forward: float = FORWARD_MIN,
        stall_limit: int = DEFAULT_STALL_LIMIT,
        bump_step: float = DEFAULT_BUMP_STEP,
        max_power: float = MAX_ALLOWED_POWER,
        turn_dx_threshold: float = TURN_MOTION_DX,
        linear_dy_threshold: float = LINEAR_MOTION_DY,
    ):
        self.path = Path(path) if path is not None else DEFAULT_STATE_PATH
        self.stall_limit = max(1, int(stall_limit))
        self.bump_step = max(1.0, float(bump_step))
        self.max_power = _clamp(max_power, MIN_ALLOWED_POWER, 100.0)
        self.turn_dx_threshold = float(turn_dx_threshold)
        self.linear_dy_threshold = float(linear_dy_threshold)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._running = False
        self._min_power = {
            "turn": _clamp(min_turn, MIN_ALLOWED_POWER, self.max_power),
            "forward": _clamp(min_forward, MIN_ALLOWED_POWER, self.max_power),
        }
        self._breakaway = {"turn": None, "forward": None}
        self._stall_streak = {"turn": 0, "forward": 0}
        self._recovering = {"turn": False, "forward": False}
        self._bumps = {"turn": 0, "forward": 0}
        self._last_probe = None
        self._source = "default"
        self._measured_at = None
        self._load()
        self._confirmed = dict(self._min_power)

    def _load(self) -> None:
        try:
            if not self.path.is_file():
                return
            data = json.loads(self.path.read_text())
        except Exception:
            return
        if not isinstance(data, dict):
            return
        with self._lock:
            for axis in ("turn", "forward"):
                key = f"min_{axis}"
                if key in data:
                    self._min_power[axis] = _clamp(data[key], MIN_ALLOWED_POWER, self.max_power)
                bkey = f"breakaway_{axis}"
                if data.get(bkey) is not None:
                    self._breakaway[axis] = _clamp(data[bkey], MIN_ALLOWED_POWER, self.max_power)
            self._source = str(data.get("source") or "saved")
            self._measured_at = data.get("measured_at")

    def _save(self) -> None:
        with self._lock:
            payload = {
                "min_turn": self._confirmed["turn"],
                "min_forward": self._confirmed["forward"],
                "breakaway_turn": self._breakaway["turn"],
                "breakaway_forward": self._breakaway["forward"],
                "source": self._source,
                "measured_at": self._measured_at,
                "bumps": dict(self._bumps),
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2) + "\n")
            tmp.replace(self.path)
        except Exception as exc:
            print(f"[power-gauge] failed to save {self.path}: {exc}", flush=True)

    @property
    def min_turn(self) -> float:
        with self._lock:
            return self._min_power["turn"]

    @property
    def min_forward(self) -> float:
        with self._lock:
            return self._min_power["forward"]

    def _effective_cap(self, power_cap: float | None) -> float:
        if power_cap is None:
            return self.max_power
        return _clamp(min(self.max_power, float(power_cap)), MIN_ALLOWED_POWER, 100.0)

    def turn_bounds(
        self,
        default_max: float = TURN_MAX,
        power_cap: float | None = None,
    ) -> tuple[float, float]:
        cap = self._effective_cap(power_cap)
        with self._lock:
            lo = min(cap, self._min_power["turn"])
        hi = min(cap, max(float(default_max), lo + HEADROOM))
        return round(lo, 1), round(max(lo, hi), 1)

    def forward_bounds(
        self,
        default_max: float = FORWARD_MAX,
        power_cap: float | None = None,
    ) -> tuple[float, float]:
        cap = self._effective_cap(power_cap)
        with self._lock:
            lo = min(cap, self._min_power["forward"])
        hi = min(cap, max(float(default_max), lo + HEADROOM))
        return round(lo, 1), round(max(lo, hi), 1)

    def observe_pulse(
        self,
        axis: str,
        power: float,
        delta: float,
        fresh: bool,
        power_cap: float | None = None,
    ) -> dict:
        """Update stall state from one observed motion pulse."""
        if axis not in ("turn", "forward") or not fresh:
            return {"axis": axis, "ignored": True}
        power = abs(float(power))
        delta = abs(float(delta))
        threshold = self.turn_dx_threshold if axis == "turn" else self.linear_dy_threshold
        moved = delta >= threshold
        cap = self._effective_cap(power_cap)
        bumped_to = None
        should_save = False

        with self._lock:
            if not moved and power < self._min_power[axis] - 0.5:
                return {
                    "axis": axis,
                    "power": round(power, 1),
                    "delta": round(delta, 3),
                    "moved": False,
                    "ignored": True,
                    "min_power": self._min_power[axis],
                }
            if moved:
                was_recovering = self._recovering[axis]
                self._stall_streak[axis] = 0
                self._recovering[axis] = False
                if was_recovering:
                    self._min_power[axis] = _clamp(max(self._min_power[axis], power), MIN_ALLOWED_POWER, cap)
                    self._confirmed[axis] = self._min_power[axis]
                    self._source = f"stall-bump:{axis}"
                    self._measured_at = round(time.time(), 1)
                    should_save = True
            else:
                self._stall_streak[axis] += 1
                trigger = self._recovering[axis] or self._stall_streak[axis] >= self.stall_limit
                if trigger:
                    self._recovering[axis] = True
                    base = max(self._min_power[axis], power)
                    updated = _clamp(base + self.bump_step, MIN_ALLOWED_POWER, cap)
                    if updated > self._min_power[axis]:
                        self._min_power[axis] = updated
                        self._bumps[axis] += 1
                        bumped_to = updated
                    self._stall_streak[axis] = 0
            streak = self._stall_streak[axis]
            recovering = self._recovering[axis]
            current_min = self._min_power[axis]

        if should_save:
            self._save()
        if bumped_to is not None:
            print(
                f"[power-gauge] {axis} stalled at {power:.1f} (delta={delta:.2f}); "
                f"bumped min_{axis} to {bumped_to:.1f}",
                flush=True,
            )
        return {
            "axis": axis,
            "power": round(power, 1),
            "delta": round(delta, 3),
            "moved": moved,
            "stall_streak": streak,
            "recovering": recovering,
            "bumped_to": bumped_to,
            "min_power": current_min,
        }

    def stop(self) -> dict:
        self._stop.set()
        return self.status()

    def calibrate(
        self,
        robot,
        start_power: float = DEFAULT_START_POWER,
        step: float = DEFAULT_STEP,
        max_power: float | None = None,
        pulse_seconds: float = DEFAULT_PULSE_SECONDS,
        settle_seconds: float = DEFAULT_SETTLE_SECONDS,
        margin: float = DEFAULT_MARGIN,
        confirm_reverse: bool = True,
        pre_settle_seconds: float = DEFAULT_PRE_SETTLE_SECONDS,
    ) -> dict:
        """Ramp short in-place turn pulses until visual odometry confirms rotation."""
        self._stop.clear()
        cap = self._effective_cap(getattr(getattr(robot, "motion", None), "power", None))
        hi = _clamp(max_power if max_power is not None else cap, MIN_ALLOWED_POWER, cap)
        lo = _clamp(start_power, MIN_ALLOWED_POWER, hi)
        step = max(1.0, float(step))
        pulse_seconds = max(0.05, min(0.35, float(pulse_seconds)))
        settle_seconds = max(0.0, min(0.3, float(settle_seconds)))
        margin = max(0.0, min(10.0, float(margin)))
        pre_settle_seconds = max(0.0, min(1.0, float(pre_settle_seconds)))

        odometry = getattr(robot, "odometry", None)
        if odometry is None or not hasattr(odometry, "capture_gray") or not hasattr(odometry, "measure_shift"):
            return {"ok": False, "error": "visual odometry unavailable", "status": self.status()}

        def _measure_pulse(pwr: float, dir_sign: int) -> tuple[dict | None, str]:
            before, _, before_id, err = odometry.capture_gray()
            if before is None:
                return None, err or "camera unavailable"
            res = robot.movement.set_velocity(0, dir_sign * pwr, source="power-gauge")
            if res and res.get("ok") is False:
                return None, res.get("veto") or "motion vetoed"
            stopped_early = self._stop.wait(pulse_seconds)
            robot.movement.stop(source="power-gauge")
            if stopped_early:
                return None, "stopped"
            if settle_seconds:
                self._stop.wait(settle_seconds)
            _, _, stop_id = robot.camera.latest()
            after, _, _, after_err = odometry.capture_gray(
                after_frame_id=max(before_id or 0, stop_id or 0),
                timeout=0.15,
            )
            if after is None:
                after, _, _, after_err = odometry.capture_gray()
            shift = odometry.measure_shift(before, after)
            signed_dx = float(shift.get("dx", 0.0))
            score = float(shift.get("score", 0.0))
            fresh = bool(shift.get("fresh")) and score >= CALIBRATE_MIN_SCORE
            moved = fresh and abs(signed_dx) >= CALIBRATE_MOTION_DX
            return {
                "power": round(pwr, 1),
                "direction": dir_sign,
                "signed_dx": round(signed_dx, 3),
                "dx": round(abs(signed_dx), 3),
                "score": round(score, 3),
                "fresh": fresh,
                "moved": moved,
                **({"error": after_err} if after_err and not fresh else {}),
            }, ""

        trials = []
        breakaway = None
        direction = 1
        with self._lock:
            self._running = True
        print(
            f"[power-gauge] calibrate start lo={lo:g} hi={hi:g} step={step:g} pulse={pulse_seconds:.2f}s",
            flush=True,
        )
        try:
            if pre_settle_seconds:
                self._stop.wait(pre_settle_seconds)
            power = lo
            while power <= hi + 1e-6 and not self._stop.is_set():
                trial, err = _measure_pulse(power, direction)
                if err:
                    if err == "stopped":
                        break
                    return {"ok": False, "error": err, "trials": trials, "status": self.status()}
                trials.append(trial)
                print(
                    f"[power-gauge] trial power={power:.1f} dir={direction:+d} "
                    f"dx={trial['signed_dx']:+.2f} score={trial['score']:.2f} moved={trial['moved']}",
                    flush=True,
                )
                if trial["moved"]:
                    if not confirm_reverse:
                        breakaway = round(power, 1)
                        break
                    rev, rev_err = _measure_pulse(power, -direction)
                    if rev_err:
                        if rev_err == "stopped":
                            break
                        return {"ok": False, "error": rev_err, "trials": trials, "status": self.status()}
                    rev["confirm"] = True
                    trials.append(rev)
                    print(
                        f"[power-gauge] confirm power={power:.1f} dir={-direction:+d} "
                        f"dx={rev['signed_dx']:+.2f} score={rev['score']:.2f} moved={rev['moved']}",
                        flush=True,
                    )
                    opposite_sign = (trial["signed_dx"] * rev["signed_dx"]) < 0
                    if rev["moved"] and opposite_sign:
                        breakaway = round(power, 1)
                        break
                    # Either reverse stalled or scene motion shifted both same way: keep ramping.
                direction = -direction
                power = round(power + step, 1)

            if self._stop.is_set():
                return {"ok": False, "error": "stopped", "trials": trials, "status": self.status()}
            if breakaway is None:
                return {
                    "ok": False,
                    "error": f"no rotation detected up to {hi:g}%",
                    "trials": trials,
                    "status": self.status(),
                }

            measured_min = _clamp(breakaway + margin, MIN_ALLOWED_POWER, hi)
            with self._lock:
                self._running = False
                self._breakaway["turn"] = breakaway
                self._min_power["turn"] = measured_min
                self._confirmed["turn"] = measured_min
                self._stall_streak["turn"] = 0
                self._stall_streak["forward"] = 0
                self._recovering["turn"] = False
                self._recovering["forward"] = False
                self._source = "ramp-calibration"
                self._measured_at = round(time.time(), 1)
                self._last_probe = {
                    "breakaway_turn": breakaway,
                    "min_turn": measured_min,
                    "trials": len(trials),
                }
            self._save()
            print(
                f"[power-gauge] calibrated breakaway={breakaway:.1f}% -> min_power={measured_min:.1f}%",
                flush=True,
            )
            return {
                "ok": True,
                "skill": "power-gauge",
                "breakaway_turn": breakaway,
                "min_turn": measured_min,
                "min_forward": self.min_forward,
                "trials": trials,
                "status": self.status(),
            }
        finally:
            robot.movement.stop(source="power-gauge")
            with self._lock:
                self._running = False

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "min_turn": self._min_power["turn"],
                "min_forward": self._min_power["forward"],
                "breakaway_turn": self._breakaway["turn"],
                "breakaway_forward": self._breakaway["forward"],
                "stall_streak": dict(self._stall_streak),
                "recovering": dict(self._recovering),
                "bumps": dict(self._bumps),
                "stall_limit": self.stall_limit,
                "bump_step": self.bump_step,
                "source": self._source,
                "measured_at": self._measured_at,
                "last_probe": dict(self._last_probe) if self._last_probe else None,
            }
