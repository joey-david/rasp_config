#!/usr/bin/env python3
"""Calibrate one-shot turn pulses for centering a fixed target.

Run on the Pi while the web service is stopped:

    sudo systemctl stop mischief-bot.service
    python3 calibrations/turn_centering.py

The script owns the camera and motors. Every control decision is made from fresh
post-motion camera frames captured after the robot has stopped and settled.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from perception.vision import DETECT_URL, box_center_x, resolve_label, select_target
from robot_api import robot

CENTER = 0.5
OFFSETS = {"edge": 0.47, "7/8": 0.375, "1/2": 0.25, "1/4": 0.125}
DRY_POSITIONS = [
    ("far-left", -1.0),
    ("three-quarter-left", -0.75),
    ("half-left", -0.5),
    ("quarter-left", -0.25),
    ("quarter-right", 0.25),
    ("half-right", 0.5),
    ("three-quarter-right", 0.75),
    ("far-right", 1.0),
]


def emergency_stop(signum=None, frame=None):
    try:
        robot.movement.stop(source="turn-calibration-signal")
    finally:
        raise KeyboardInterrupt


def log(args, msg):
    if args.verbose:
        print(msg, flush=True)


def clamp(x, lo, hi):
    return max(lo, min(hi, float(x)))


def side_sign(side):
    return -1 if side == "left" else 1


def center_turn_for_error(err, args):
    if abs(err) <= args.center_tolerance:
        return 0.0
    power = args.center_power or args.adjust_power
    return power if err > 0 else -power


def position_turn_for_error(err, args):
    return args.adjust_power if err > 0 else -args.adjust_power


def adjust_duration(err, args):
    return clamp(abs(err) * args.adjust_pulse_gain, args.adjust_pulse_min, args.adjust_pulse_max)


def position_duration(err, args):
    return clamp(abs(err) * args.position_pulse_gain, args.position_pulse_min, args.position_pulse_max)


def move(angular, duration, args, source="turn-calibration"):
    """Send a finite turn command, then stop and wait before any capture."""
    try:
        robot.movement.set_velocity(0, angular, source=source)
        time.sleep(duration)
    finally:
        robot.movement.stop(source=source)
    time.sleep(args.motion_settle)


def detect_one(label, last_cx, args):
    # Use the calibration-owned stream and wait for a fresh frame after motion.
    time.sleep(args.capture_settle)
    try:
        frame = robot.camera.snapshot(timeout=args.capture_timeout)
        detections, meta = post_detection(frame, label, args)
        det = select_target(detections, label, last_cx)
    except Exception as e:
        return None, {"error": str(e)}
    if not det:
        return None, meta
    box = [float(x) for x in det["box"]]
    return {
        "box": box,
        "cx": box_center_x(box),
        "score": det.get("score"),
    }, meta


def post_detection(frame, label, args):
    url = DETECT_URL + "?" + urllib.parse.urlencode({"label": label, "imgsz": int(args.imgsz)})
    req = urllib.request.Request(url, data=frame, method="POST", headers={"Content-Type": "image/jpeg"})
    started = time.time()
    with urllib.request.urlopen(req, timeout=args.timeout) as response:
        out = json.loads(response.read().decode())
    return out.get("detections") or [], {
        "infer_ms": out.get("infer_ms"),
        "image_size": out.get("image_size"),
        "imgsz": out.get("imgsz"),
        "roundtrip_ms": round((time.time() - started) * 1000, 1),
    }


def measure(label, args, last_cx=CENTER, samples=None, min_hits=None):
    """Return a median detection from several fresh max-res captures."""
    samples = samples or args.samples
    min_hits = min_hits or args.min_hits
    hits, metas = [], []
    for _ in range(samples):
        det, meta = detect_one(label, last_cx, args)
        metas.append(meta)
        if det:
            hits.append(det)
            last_cx = det["cx"]
        time.sleep(args.sample_gap)
    if len(hits) < min_hits:
        return None, summarize_meta(metas, len(hits), samples)
    hits.sort(key=lambda d: d["cx"])
    det = hits[len(hits) // 2]
    return det, summarize_meta(metas, len(hits), samples)


def summarize_meta(metas, hits, samples):
    last = metas[-1] if metas else {}
    return {
        "hits": hits,
        "samples": samples,
        "infer_ms": last.get("infer_ms"),
        "image_size": last.get("image_size"),
        "frame_id": last.get("frame_id"),
        "detect_error": last.get("error"),
    }


def scan_find(label, args, preferred=1):
    det, meta = measure(label, args, samples=args.find_samples, min_hits=args.find_min_hits)
    if det:
        return det

    # Sweep both sides of the current heading. The middle segment is doubled so
    # it crosses back through the starting view and searches equally far beyond.
    step = 0
    for direction, count in [
        (preferred, args.find_cycles),
        (-preferred, args.find_cycles * 2),
        (preferred, args.find_cycles),
    ]:
        for _ in range(count):
            step += 1
            move(direction * args.find_power, args.find_pulse, args, "turn-calibration-find")
            det, meta = measure(label, args, samples=args.find_samples, min_hits=args.find_min_hits)
            log(args, f"find step={step} dir={direction} seen={bool(det)} meta={meta}")
            if det:
                return det
    return None


def center_target(label, args, quiet=False):
    det = scan_find(label, args)
    if not det:
        return None
    start_cx = det["cx"]
    for step in range(args.center_cycles):
        det, meta = measure(label, args, det["cx"], samples=args.center_samples, min_hits=args.center_min_hits)
        if not det:
            det = scan_find(label, args)
            if not det:
                return None
        err = det["cx"] - CENTER
        turn = center_turn_for_error(err, args)
        if not quiet:
            print(f"center step {step + 1}: cx={det['cx']:.3f} err={err:.3f} turn={turn:.1f}", flush=True)
        else:
            log(args, f"center step={step + 1} cx={det['cx']:.3f} err={err:.3f} turn={turn:.1f}")
        if turn == 0:
            if not quiet:
                print(f"centered: cx {start_cx:.3f} -> {det['cx']:.3f} in {step} pulses", flush=True)
            return det
        move(turn, adjust_duration(err, args), args, "turn-calibration-center")
    return None


def tune_adjustment_power(label, args):
    """Find the smallest adjustment power that moves, but not too far."""
    print("tuning adjustment power", flush=True)
    tests = []
    for power in range(args.adjust_power_min, args.adjust_power_max + 1, args.adjust_power_step):
        ok = 0
        args.center_power = args.startup_center_power
        if not center_target(label, args, quiet=True):
            continue
        for direction in [1, -1] * args.adjust_repeats:
            before, _ = measure(label, args, samples=args.center_samples, min_hits=args.center_min_hits)
            if not before:
                center_target(label, args, quiet=True)
                continue
            move(direction * power, args.adjust_test_pulse, args, "turn-calibration-adjust-test")
            after, _ = measure(label, args, before["cx"], samples=args.center_samples, min_hits=args.center_min_hits)
            if not after:
                center_target(label, args, quiet=True)
                continue
            delta = after["cx"] - before["cx"]
            moved = abs(delta)
            expected = delta < 0 if direction > 0 else delta > 0
            good = expected and args.adjust_min_shift <= moved <= args.adjust_max_shift
            ok += int(good)
            tests.append({"power": power, "direction": direction, "delta": round(delta, 4), "ok": good})
            log(args, f"adjust test power={power} dir={direction} delta={delta:.4f} ok={good}")
            if abs(after["cx"] - CENTER) > args.adjust_recenter_error:
                center_target(label, args, quiet=True)
        if ok == 2 * args.adjust_repeats:
            args.adjust_power = power
            args.center_power = power
            print(f"adjustment power: {power}", flush=True)
            return {"power": power, "tests": tests}
        print(f"power {power}: {ok}/{2 * args.adjust_repeats} good adjustment pulses", flush=True)
    args.adjust_power = args.adjust_fallback_power
    args.center_power = args.adjust_power
    print(f"adjustment power fallback: {args.adjust_power}", flush=True)
    return {"power": args.adjust_power, "fallback": True, "tests": tests}


def target_for(side, offset_name):
    if offset_name == "edge":
        return {"kind": "edge", "side": side, "fraction": side_sign(side)}
    cx = CENTER + side_sign(side) * OFFSETS[offset_name]
    return {"kind": "cx", "side": side, "cx": cx, "fraction": (cx - CENTER) / 0.5}


def target_from_fraction(name, fraction):
    if abs(fraction) >= 0.999:
        return {"kind": "edge", "side": "left" if fraction < 0 else "right", "fraction": fraction}
    return {"kind": "cx", "side": "left" if fraction < 0 else "right", "cx": CENTER + 0.5 * fraction, "fraction": fraction}


def position_error(det, target, args):
    x1, _, x2, _ = det["box"]
    if target["kind"] == "edge" and target["side"] == "left":
        return x1 - args.edge_tolerance, x1 <= args.edge_tolerance
    if target["kind"] == "edge" and target["side"] == "right":
        return x2 - (1.0 - args.edge_tolerance), x2 >= 1.0 - args.edge_tolerance
    err = det["cx"] - target["cx"]
    return err, abs(err) <= args.position_tolerance


def near_position_target(det, target, args):
    x1, _, x2, _ = det["box"]
    if target["kind"] == "edge" and target["side"] == "left":
        return x1 <= args.edge_confirm_band
    if target["kind"] == "edge" and target["side"] == "right":
        return x2 >= 1.0 - args.edge_confirm_band
    return abs(det["cx"] - target["cx"]) <= args.position_confirm_band


def recover_position_detection(label, target, last_cx, args):
    """Recover from an edge miss without throwing away the start placement."""
    direction = side_sign(target["side"])
    for step in range(args.edge_recovery_steps):
        move(direction * args.adjust_power, args.edge_recovery_pulse, args, "turn-calibration-edge-recover")
        det, meta = measure(
            label,
            args,
            last_cx,
            samples=args.edge_samples if target["kind"] == "edge" else args.samples,
            min_hits=args.edge_min_hits if target["kind"] == "edge" else args.min_hits,
        )
        log(args, f"edge recover step={step + 1} side={target['side']} seen={bool(det)} meta={meta}")
        if det:
            return det
    det = scan_find(label, args, preferred=direction)
    if det:
        return det
    return center_target(label, args, quiet=True)


def position_target(label, name, target, args):
    """Servo until the target is at the requested image position."""
    history, last_cx = [], CENTER
    for step in range(1, args.position_steps + 1):
        samples, min_hits = args.position_samples, args.position_min_hits
        if history and history[-1].get("near"):
            samples, min_hits = args.edge_samples, args.edge_min_hits
        det, meta = measure(label, args, last_cx, samples=samples, min_hits=min_hits)
        if not det:
            history.append({"step": step, "seen": False, **meta})
            print(f"position {name} step {step}: lost; recovering", flush=True)
            det = recover_position_detection(label, target, last_cx, args)
            if not det:
                continue
            last_cx = det["cx"]
            continue

        last_cx = det["cx"]
        err, reached = position_error(det, target, args)
        near = near_position_target(det, target, args)
        turn = 0.0 if reached else position_turn_for_error(err, args)
        row = {
            "step": step,
            "cx": round(det["cx"], 4),
            "box": [round(x, 4) for x in det["box"]],
            "err": round(err, 4),
            "near": near,
            "turn": round(turn, 1),
            **meta,
        }
        history.append(row)
        print(
            f"position {name} step {step}: cx={det['cx']:.3f} "
            f"box=({det['box'][0]:.3f},{det['box'][2]:.3f}) err={err:.3f} "
            f"turn={turn:.1f} hits={meta.get('hits')}/{meta.get('samples')}",
            flush=True,
        )
        if reached:
            return {"ok": True, "position": name, "cx": det["cx"], "box": det["box"], "steps": step, "history": history}
        move(turn, position_duration(err, args), args, "turn-calibration-position")
    return {"ok": False, "position": name, "reason": "position_timeout", "history": history}


def classify_end(det, side, args):
    if not det:
        return "lost", None
    err = det["cx"] - CENTER
    if abs(err) <= args.center_tolerance:
        return "centered", err
    start_side = (side == "left" and det["cx"] < CENTER) or (side == "right" and det["cx"] > CENTER)
    return ("undershoot" if start_side else "overshoot"), err


def run_trial(label, side, offset_name, power, duration, args, pos_log):
    target = target_for(side, offset_name)
    pos = position_target(label, f"{side}-{offset_name}", target, args)
    write_jsonl(pos_log, pos)
    if not pos["ok"]:
        raise RuntimeError(f"position failed: {pos['reason']}")

    move(side_sign(side) * abs(power), duration, args, "turn-calibration-pulse")
    det, meta = measure(label, args, pos["cx"])
    outcome, err = classify_end(det, side, args)
    return {
        "side": side,
        "offset_name": offset_name,
        "power": power,
        "duration": round(duration, 4),
        "start_cx": round(pos["cx"], 4),
        "end_cx": None if not det else round(det["cx"], 4),
        "error": None if err is None else round(err, 4),
        "outcome": outcome,
        **meta,
    }


def measured_trial(label, side, offset_name, power, duration, args, pos_log):
    for retry in range(args.trial_retries + 1):
        print(
            f"\n{side} {offset_name}: power={power} duration={duration:.3f}s"
            + (f" retry={retry}" if retry else ""),
            flush=True,
        )
        trial = run_trial(label, side, offset_name, power, duration, args, pos_log)
        if trial["outcome"] != "lost":
            return trial
        print("lost after pulse; re-finding and retrying same duration", flush=True)
        center_target(label, args)
    return trial


def tune_duration(label, side, offset_name, power, args, data_log, pos_log):
    low, high, best = 0.0, args.initial_duration, None

    while high <= args.max_duration:
        trial = measured_trial(label, side, offset_name, power, high, args, pos_log)
        write_jsonl(data_log, trial)
        print(trial, flush=True)
        best = better(best, trial)
        if trial["outcome"] in {"centered", "overshoot"}:
            break
        if trial["outcome"] == "lost":
            return {"ok": False, "reason": "lost", "best": best}
        low, high = high, high * args.grow
    else:
        return {"ok": False, "reason": "max_duration", "best": best, "low": low, "high": high}

    for _ in range(args.binary_steps):
        mid = (low + high) / 2
        trial = measured_trial(label, side, offset_name, power, mid, args, pos_log)
        write_jsonl(data_log, trial)
        print(trial, flush=True)
        best = better(best, trial)
        if trial["outcome"] == "centered":
            break
        if trial["outcome"] == "undershoot":
            low = mid
        elif trial["outcome"] == "overshoot":
            high = mid
        else:
            return {"ok": False, "reason": "lost", "best": best}

    confirms = []
    duration = best["duration"] if best else (low + high) / 2
    for i in range(args.confirmations):
        print(f"\nconfirm {i + 1}/{args.confirmations}: {side} {offset_name} power={power} duration={duration:.3f}s", flush=True)
        trial = measured_trial(label, side, offset_name, power, duration, args, pos_log)
        write_jsonl(data_log, trial)
        print(trial, flush=True)
        confirms.append(trial)
    ok = sum(t["outcome"] == "centered" for t in confirms) >= args.min_confirmed
    return {"ok": ok, "duration": duration, "best": best, "confirmations": confirms}


def better(best, trial):
    if trial["error"] is None:
        return best
    if best is None or abs(trial["error"]) < abs(best["error"]):
        return trial
    return best


def dry_run(label, args, out_path):
    rows = []
    prepare_adjustment(label, args)
    for name, fraction in DRY_POSITIONS:
        row = position_target(label, name, target_from_fraction(name, fraction), args)
        rows.append(row)
        print({k: row.get(k) for k in ("position", "ok", "cx", "steps", "reason")}, flush=True)
    out_path.write_text(json.dumps(rows, indent=2, sort_keys=True))


def prepare_adjustment(label, args):
    print("initializing: finding and centering target", flush=True)
    args.center_power = args.startup_center_power
    if not center_target(label, args):
        raise RuntimeError("could not find and center target")
    if not args.tune_adjustment:
        args.adjust_power = args.adjust_fallback_power
        args.center_power = args.adjust_power
        print(f"adjustment power: {args.adjust_power} (fixed; use --tune-adjustment to measure)", flush=True)
        return {"power": args.adjust_power, "fixed": True}
    result = tune_adjustment_power(label, args)
    if not center_target(label, args):
        raise RuntimeError("could not re-center target after adjustment-power tuning")
    return result


def write_jsonl(path, row):
    with path.open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def parse_range(spec):
    start, stop, step = [int(x) for x in spec.split(":")]
    return list(range(start, stop + 1, step))


def args_parser():
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="potted plant")
    p.add_argument("--powers", default="30:80:5")
    p.add_argument("--offsets", default="edge,7/8,1/2,1/4")
    p.add_argument("--sides", default="left,right")
    p.add_argument("--out-dir", default="calibrations/turn_centering")
    p.add_argument("--dry-run", "--dry", action="store_true")
    p.add_argument("--init-only", action="store_true")
    p.add_argument("--tune-adjustment", action="store_true")
    p.add_argument("--samples", type=int, default=3)
    p.add_argument("--min-hits", type=int, default=2)
    p.add_argument("--sample-gap", type=float, default=0.05)
    p.add_argument("--timeout", type=float, default=12.0)
    p.add_argument("--capture-timeout", type=float, default=5.0)
    p.add_argument("--imgsz", type=int, default=1280)
    p.add_argument("--motion-settle", type=float, default=0.18)
    p.add_argument("--capture-settle", type=float, default=0.08)
    p.add_argument("--edge-tolerance", type=float, default=0.025)
    p.add_argument("--position-tolerance", type=float, default=0.025)
    p.add_argument("--center-tolerance", type=float, default=0.025)
    p.add_argument("--center-samples", type=int, default=2)
    p.add_argument("--center-min-hits", type=int, default=1)
    p.add_argument("--position-samples", type=int, default=2)
    p.add_argument("--position-min-hits", type=int, default=1)
    p.add_argument("--find-samples", type=int, default=3)
    p.add_argument("--find-min-hits", type=int, default=1)
    p.add_argument("--edge-samples", type=int, default=5)
    p.add_argument("--edge-min-hits", type=int, default=2)
    p.add_argument("--adjust-power-min", type=int, default=25)
    p.add_argument("--adjust-power-max", type=int, default=55)
    p.add_argument("--adjust-power-step", type=int, default=5)
    p.add_argument("--adjust-fallback-power", type=float, default=35)
    p.add_argument("--startup-center-power", type=float, default=45)
    p.add_argument("--adjust-test-pulse", type=float, default=0.10)
    p.add_argument("--adjust-min-shift", type=float, default=0.010)
    p.add_argument("--adjust-max-shift", type=float, default=0.080)
    p.add_argument("--adjust-repeats", type=int, default=1)
    p.add_argument("--adjust-recenter-error", type=float, default=0.18)
    p.add_argument("--adjust-pulse-min", type=float, default=0.05)
    p.add_argument("--adjust-pulse-max", type=float, default=0.16)
    p.add_argument("--adjust-pulse-gain", type=float, default=0.45)
    p.add_argument("--position-pulse-min", type=float, default=0.08)
    p.add_argument("--position-pulse-max", type=float, default=0.25)
    p.add_argument("--position-pulse-gain", type=float, default=0.65)
    p.add_argument("--center-cycles", type=int, default=30)
    p.add_argument("--position-steps", type=int, default=45)
    p.add_argument("--edge-confirm-band", type=float, default=0.12)
    p.add_argument("--position-confirm-band", type=float, default=0.08)
    p.add_argument("--edge-recovery-steps", type=int, default=6)
    p.add_argument("--edge-recovery-pulse", type=float, default=0.08)
    p.add_argument("--find-power", type=float, default=40)
    p.add_argument("--find-pulse", type=float, default=0.28)
    p.add_argument("--find-cycles", type=int, default=18)
    p.add_argument("--initial-duration", type=float, default=0.04)
    p.add_argument("--max-duration", type=float, default=1.6)
    p.add_argument("--grow", type=float, default=1.55)
    p.add_argument("--binary-steps", type=int, default=6)
    p.add_argument("--trial-retries", type=int, default=2)
    p.add_argument("--confirmations", type=int, default=3)
    p.add_argument("--min-confirmed", type=int, default=2)
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()
    args.adjust_power = args.adjust_fallback_power
    args.center_power = args.startup_center_power
    return args


def main():
    signal.signal(signal.SIGINT, emergency_stop)
    signal.signal(signal.SIGTERM, emergency_stop)
    args = args_parser()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    data_log = out_dir / f"{run_id}.jsonl"
    pos_log = out_dir / f"{run_id}.positions.jsonl"
    summary_path = out_dir / f"{run_id}-summary.json"

    label, resolve_meta = resolve_label(args.target)
    print(f"target {args.target!r} resolved to {label!r}: {resolve_meta}", flush=True)

    summary = {"target": args.target, "label": label, "resolve": resolve_meta, "args": vars(args), "results": {}}
    robot.camera.start()
    time.sleep(2.0)
    robot.vision.stop()
    try:
        if args.dry_run:
            dry_run(label, args, out_dir / f"{run_id}-dry-run.json")
            return

        summary["adjustment"] = prepare_adjustment(label, args)
        if args.init_only:
            return
        summary["args"] = vars(args)

        for side in [s.strip() for s in args.sides.split(",") if s.strip()]:
            summary["results"][side] = {}
            for offset_name in [o.strip() for o in args.offsets.split(",") if o.strip()]:
                summary["results"][side][offset_name] = {}
                for power in parse_range(args.powers):
                    try:
                        result = tune_duration(label, side, offset_name, power, args, data_log, pos_log)
                    except KeyboardInterrupt:
                        raise
                    except Exception as e:
                        result = {"ok": False, "reason": "error", "error": str(e)}
                        print(result, flush=True)
                    summary["results"][side][offset_name][str(power)] = result
                    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    except KeyboardInterrupt:
        summary["interrupted"] = True
        print("\ninterrupted", flush=True)
    finally:
        robot.movement.stop(source="turn-calibration")
        robot.camera.stop()
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
        print(f"wrote {data_log}", flush=True)
        print(f"wrote {pos_log}", flush=True)
        print(f"wrote {summary_path}", flush=True)


if __name__ == "__main__":
    main()
